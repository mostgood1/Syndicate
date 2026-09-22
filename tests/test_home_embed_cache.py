"""`/`'s embed is built once per TTL per worker, not once per request.

MEASURED 2026-09-22: after the embed itself went 30,994,816 -> 11,986,801 chars,
the server-side median for `/` moved 7,843 -> 7,600 ms -- unchanged. The cost is
`read_combined_intelligence_response` + `_hydrate_board_response_payload` +
`_slim_embedded_board_payload`, run per request, and web has 8 request slots.

The properties pinned here are the ones that make a cache safe rather than clever:
an empty build is never stored, a rebuild in flight never queues other requests
behind it, and the text is byte-identical to what `| tojson` produced before.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from syndicate.blueprints import intelligence as intel


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    monkeypatch.setattr(intel, "_HOME_EMBED_CACHE", {})
    monkeypatch.setattr(intel, "_HOME_EMBED_LOCKS", {})
    monkeypatch.delenv("SYNDICATE_HOME_EMBED_CACHE_SECONDS", raising=False)
    yield


def _payload(n=3, tag="a"):
    return {"ranked_all": [{"sport": "mlb", "id": i, "tag": tag} for i in range(n)]}


def _counting_build(payload=None, calls=None):
    calls = calls if calls is not None else []

    def build():
        calls.append(1)
        return payload if payload is not None else _payload()

    build.calls = calls
    return build


def test_the_second_request_inside_the_ttl_does_not_rebuild():
    build = _counting_build()
    first = intel.cached_home_embed_json("default", build)
    second = intel.cached_home_embed_json("default", build)
    assert first == second
    assert len(build.calls) == 1, "the embed was rebuilt inside its TTL"


def test_the_cache_expires():
    build = _counting_build()
    intel.cached_home_embed_json("default", build)
    # Expire it the way the wall clock would.
    stamp, text = intel._HOME_EMBED_CACHE["default"]
    intel._HOME_EMBED_CACHE["default"] = (time.time() - 1, text)
    intel.cached_home_embed_json("default", build)
    assert len(build.calls) == 2


def test_two_windows_do_not_share_an_entry():
    build_a = _counting_build(_payload(tag="default"))
    build_b = _counting_build(_payload(tag="dated"))
    a = intel.cached_home_embed_json("default:2026-09-22", build_a)
    b = intel.cached_home_embed_json("date=2026-09-23", build_b)
    assert a != b and "default" in a and "dated" in b


def test_an_empty_build_is_never_cached():
    """`learnings.md` 2026-08-18: a result that resolved nothing is returned but
    not stored, so recovery is immediate instead of TTL-delayed."""
    build = _counting_build({"ranked_all": []})
    intel.cached_home_embed_json("default", build)
    intel.cached_home_embed_json("default", build)
    assert len(build.calls) == 2
    assert "default" not in intel._HOME_EMBED_CACHE


def test_zero_disables_the_cache(monkeypatch):
    """off != on."""
    monkeypatch.setenv("SYNDICATE_HOME_EMBED_CACHE_SECONDS", "0")
    build = _counting_build()
    intel.cached_home_embed_json("default", build)
    intel.cached_home_embed_json("default", build)
    assert len(build.calls) == 2


def test_a_rebuild_in_flight_serves_the_previous_text_instead_of_queueing():
    """THE SLOT PROPERTY. A request that waits 7 s for someone else's rebuild is
    exactly what starves `/healthz` (lane `web-flap-0922`)."""
    release = threading.Event()
    calls = []

    def slow_build():
        calls.append(1)
        if len(calls) > 1:
            release.wait(5)
        return _payload(tag=f"build{len(calls)}")

    first = intel.cached_home_embed_json("default", slow_build)
    stamp, text = intel._HOME_EMBED_CACHE["default"]
    intel._HOME_EMBED_CACHE["default"] = (time.time() - 1, text)   # now stale

    started = threading.Event()
    result = {}

    def rebuild_thread():
        started.set()
        result["fresh"] = intel.cached_home_embed_json("default", slow_build)

    worker = threading.Thread(target=rebuild_thread, daemon=True)
    worker.start()
    started.wait(2)
    time.sleep(0.2)                       # let it take the lock and block

    began = time.time()
    served = intel.cached_home_embed_json("default", slow_build)
    waited = time.time() - began

    release.set()
    worker.join(10)

    assert served == first, "a concurrent request must get the previous text"
    assert waited < 1.0, f"it queued behind the rebuild for {waited:.1f}s"
    assert len(calls) == 2, "only the rebuilding thread should build"


def test_the_text_is_what_tojson_produced_and_is_script_safe():
    """The template now emits this string directly, so it must carry `| tojson`'s
    escaping -- a payload containing `</script>` must not close the tag."""
    from jinja2.utils import htmlsafe_json_dumps

    payload = {"ranked_all": [{"sport": "mlb", "note": "</script><b>&'\""}]}
    text = intel.cached_home_embed_json("default", lambda: payload)

    assert text == str(htmlsafe_json_dumps(payload, dumps=lambda o, **kw: json.dumps(o, default=str, **kw)))
    assert "</script>" not in text
    assert json.loads(text)["ranked_all"][0]["note"] == "</script><b>&'\""
