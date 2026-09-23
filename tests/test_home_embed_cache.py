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
import os
import threading
import time

import pytest

from syndicate.blueprints import intelligence as intel


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(intel, "_HOME_EMBED_CACHE", {})
    monkeypatch.setattr(intel, "_HOME_EMBED_LOCKS", {})
    monkeypatch.delenv("SYNDICATE_HOME_EMBED_CACHE_SECONDS", raising=False)
    # The shared layer is a real file in the container's temp dir; point it at a
    # per-test directory so these tests cannot read each other's copies.
    monkeypatch.setattr(intel, "_home_embed_cache_path",
                        lambda key: str(tmp_path / f"embed_{key.replace(':', '_').replace('=', '_')}.json"),
                        raising=False)
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


def _expire(key="default"):
    """Age BOTH layers. Since the shared file exists, expiring only the
    in-process entry is not expiry -- the worker would (correctly) serve the
    file, which is what two of these tests caught when the file layer landed."""
    stamp, text = intel._HOME_EMBED_CACHE.get(key, (0.0, ""))
    if text:
        intel._HOME_EMBED_CACHE[key] = (time.time() - 1, text)
    path = intel._home_embed_cache_path(key)
    if os.path.exists(path):
        old = time.time() - 3600
        os.utime(path, (old, old))


def _wait_for(predicate, timeout=5.0):
    """Background refreshes are threads; poll rather than sleep a fixed time."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_the_cache_expires():
    build = _counting_build()
    intel.cached_home_embed_json("default", build)
    _expire()
    intel.cached_home_embed_json("default", build)
    # The rebuild now happens BEHIND the response (see the 2026-09-22 block at
    # the bottom), so it is the thread, not this call, that raises the count.
    assert _wait_for(lambda: len(build.calls) == 2), f"no rebuild ran: {len(build.calls)}"


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
    _expire()                                                      # both layers

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


# --------------------------------------------------------------------------
# THE SHARED LAYER (2026-09-22). The in-process cache is per WORKER: web runs
# two, so each paid the build every window (6 BUILD lines in 8 min, measured),
# and every recycle by the memory guard starts cold. Both workers share this
# container's filesystem -- the same fact `app.py:_bootstrap_lock_path` relies
# on -- so the rendered text goes in the temp dir.
# --------------------------------------------------------------------------


def _as_a_cold_worker(monkeypatch):
    """A worker with an empty in-process cache, sharing the same container."""
    monkeypatch.setattr(intel, "_HOME_EMBED_CACHE", {})
    monkeypatch.setattr(intel, "_HOME_EMBED_LOCKS", {})


def test_a_cold_worker_reads_the_siblings_file_instead_of_building(monkeypatch):
    build = _counting_build()
    first = intel.cached_home_embed_json("default", build)

    _as_a_cold_worker(monkeypatch)
    second = intel.cached_home_embed_json("default", build)

    assert second == first
    assert len(build.calls) == 1, "the second worker rebuilt instead of reading the file"


def test_a_stale_file_is_not_served(monkeypatch):
    build = _counting_build()
    intel.cached_home_embed_json("default", build)
    path = intel._home_embed_cache_path("default")
    old = time.time() - 3600
    os.utime(path, (old, old))

    _as_a_cold_worker(monkeypatch)
    intel.cached_home_embed_json("default", build)
    assert len(build.calls) == 2


def test_an_unreadable_file_falls_back_to_a_build(monkeypatch):
    build = _counting_build()
    intel.cached_home_embed_json("default", build)
    path = intel._home_embed_cache_path("default")
    os.remove(path)
    os.mkdir(path)                      # a directory where the file should be

    _as_a_cold_worker(monkeypatch)
    text = intel.cached_home_embed_json("default", build)
    assert json.loads(text)["ranked_all"]
    assert len(build.calls) == 2


def test_an_empty_build_writes_no_file():
    build = _counting_build({"ranked_all": []})
    intel.cached_home_embed_json("default", build)
    assert not os.path.exists(intel._home_embed_cache_path("default"))


def test_zero_neither_writes_nor_reads_the_file(monkeypatch):
    monkeypatch.setenv("SYNDICATE_HOME_EMBED_CACHE_SECONDS", "0")
    build = _counting_build()
    intel.cached_home_embed_json("default", build)
    assert not os.path.exists(intel._home_embed_cache_path("default"))
    assert len(build.calls) == 1


def test_a_failed_write_neither_raises_nor_corrupts_the_previous_copy(monkeypatch, capsys):
    """A cache that raises is worse than a cache that misses."""
    build = _counting_build(_payload(tag="first"))
    intel.cached_home_embed_json("default", build)
    good = open(intel._home_embed_cache_path("default"), encoding="utf-8").read()

    def _boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(intel.os, "replace", _boom)
    _as_a_cold_worker(monkeypatch)
    path = intel._home_embed_cache_path("default")
    os.utime(path, (time.time() - 3600, time.time() - 3600))   # force a rebuild
    text = intel.cached_home_embed_json("default", _counting_build(_payload(tag="second")))

    assert json.loads(text)["ranked_all"][0]["tag"] == "second"   # served anyway
    assert open(path, encoding="utf-8").read() == good            # previous copy intact
    assert "FILE_WRITE_FAILED" in capsys.readouterr().out


# --------------------------------------------------------------------------
# REFRESH OFF THE REQUEST PATH (2026-09-22). With the per-container cache, the
# three requests that landed on a window boundary took 10.3 / 6.2 / 8.2 s while
# the other nine took 0.41-1.81 s. A stale copy is now served immediately and
# the rebuild runs behind it -- the same rebuild a request would have done,
# which is `_warm_combined_board_overlays_once`'s contract one layer up.
# --------------------------------------------------------------------------


def test_a_stale_copy_is_served_immediately_and_refreshed_behind_it():
    slow = threading.Event()
    calls = []

    def build():
        calls.append(1)
        if len(calls) > 1:
            slow.wait(3)              # a real rebuild takes seconds
        return _payload(tag=f"build{len(calls)}")

    first = intel.cached_home_embed_json("default", build)
    _expire()

    began = time.time()
    served = intel.cached_home_embed_json("default", build)
    waited = time.time() - began

    assert served == first, "the caller must get the previous copy"
    assert waited < 1.0, f"the caller waited {waited:.1f}s for the rebuild"
    assert _wait_for(lambda: len(calls) == 2), "no background refresh ran"
    slow.set()
    # Once the refresh lands, the next caller gets the NEW text, no build.
    assert _wait_for(lambda: intel.cached_home_embed_json("default", build) != first, timeout=6)
    assert len(calls) == 2


def test_only_one_refresh_runs_at_a_time():
    release = threading.Event()
    calls = []

    def build():
        calls.append(1)
        if len(calls) > 1:
            release.wait(3)
        return _payload(tag=f"build{len(calls)}")

    intel.cached_home_embed_json("default", build)
    _expire()
    for _ in range(4):
        intel.cached_home_embed_json("default", build)

    assert _wait_for(lambda: len(calls) == 2)
    time.sleep(0.2)
    assert len(calls) == 2, f"{len(calls) - 1} refreshes ran for one expiry"
    release.set()


def test_an_ancient_in_memory_copy_is_not_served_either(monkeypatch):
    """The cap is not only about the file: a worker idle for an hour holds an
    hour-old entry in memory, and that must not be served either."""
    monkeypatch.setenv("SYNDICATE_HOME_EMBED_MAX_STALE_SECONDS", "30")
    build = _counting_build(_payload(tag="first"))
    intel.cached_home_embed_json("default", build)
    text, = [v[1] for v in [intel._HOME_EMBED_CACHE["default"]]]
    intel._HOME_EMBED_CACHE["default"] = (time.time() - 3600, text)   # ancient
    path = intel._home_embed_cache_path("default")
    old_stamp = time.time() - 3600
    os.utime(path, (old_stamp, old_stamp))

    fresh_build = _counting_build(_payload(tag="second"))
    served = intel.cached_home_embed_json("default", fresh_build)
    assert json.loads(served)["ranked_all"][0]["tag"] == "second"
    assert len(fresh_build.calls) == 1


def test_past_the_staleness_cap_the_caller_waits_for_a_real_build(monkeypatch):
    """off != on for the cap: serving stale is about keeping a slot free, not
    about showing an hour-old board after a quiet period."""
    monkeypatch.setenv("SYNDICATE_HOME_EMBED_MAX_STALE_SECONDS", "0")
    build = _counting_build(_payload(tag="second"))
    intel._HOME_EMBED_CACHE.clear()
    path = intel._home_embed_cache_path("default")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"ranked_all": [{"tag": "ancient"}]}')
    old = time.time() - 3600
    os.utime(path, (old, old))

    text = intel.cached_home_embed_json("default", build)
    assert json.loads(text)["ranked_all"][0]["tag"] == "second"
    assert len(build.calls) == 1


def test_a_failing_background_refresh_leaves_the_served_copy_usable(capsys):
    calls = []

    def build():
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("board read failed")
        return _payload(tag="good")

    first = intel.cached_home_embed_json("default", build)
    _expire()
    served = intel.cached_home_embed_json("default", build)
    assert served == first
    assert _wait_for(lambda: "REFRESH_FAILED" in capsys.readouterr().out or len(calls) > 1)
    # The previous copy is still there to serve, and the next request is not stuck.
    _expire()
    assert intel.cached_home_embed_json("default", build) == first
