"""#253 -- the MLB cards-page caches must not act as retention on a worker.

The regression these cover, in full: `_MLB_CARDS_CONTEXT_CACHE` (32 entries) and
`_MLB_TODAY_CACHE` (64 entries) are bounded by ENTRY COUNT and nothing else --
not by age, not by bytes. On refresh-worker both keys are guaranteed to miss on
every cycle of a live slate:

  * the context key includes `_path_cache_signature()` of the live-lens report,
    which is `(st_mtime_ns << 16) ^ st_size`, and that file is rewritten
    continuously;
  * the today key includes `_today_cache_bucket()` == `int(time.time() // 60)`.

So each cycle appended a new entry to both and steady state was up to 96 full
MLB cards-page contexts. Measured on refresh-worker 2026-08-07: the container
sat at 3108-3994MB of 4096 with `candidate_count=0` and `MEMORY_GUARD_ABORT`
firing at the FIRST checkpoint -- the floor was retention carried over from
earlier cycles, not work being done in the current one.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from syndicate.features.mlb import cards as cards_module


@pytest.fixture(autouse=True)
def _clear_caches():
    cards_module._MLB_CARDS_CONTEXT_CACHE.clear()
    cards_module._MLB_TODAY_CACHE.clear()
    yield
    cards_module._MLB_CARDS_CONTEXT_CACHE.clear()
    cards_module._MLB_TODAY_CACHE.clear()


def _as_worker():
    return patch.object(cards_module, "_render_web_dyno", return_value=False)


def _as_web():
    return patch.object(cards_module, "_render_web_dyno", return_value=True)


def test_today_cache_is_a_noop_on_a_worker():
    # #251 put a 300s minimum rebuild interval on the hydrated overview, so a
    # 60-second bucket key can never be re-requested on the worker. Every put
    # was retention of a full page context that could not be read back.
    with _as_worker():
        cards_module._today_cache_put(("cards_context", "2026-08-07", 1, 2, 3), {"big": "payload"})
    assert len(cards_module._MLB_TODAY_CACHE) == 0


def test_today_cache_still_works_on_the_web_service():
    # There the hit rate is real -- many requests genuinely share a 60s bucket.
    key = ("cards_context", "2026-08-07", 1, 2, 3)
    with _as_web():
        cards_module._today_cache_put(key, {"big": "payload"})
        assert cards_module._today_cache_get(key) == {"big": "payload"}
    assert len(cards_module._MLB_TODAY_CACHE) == 1


def test_context_cache_holds_two_entries_on_a_worker():
    # The worker only ever asks for the selected date plus the next-day rollover
    # pool. 32 is a web-shaped number.
    with _as_worker():
        for i in range(10):
            cards_module._cards_context_cache_put((f"key-{i}",), {"n": i})
    assert len(cards_module._MLB_CARDS_CONTEXT_CACHE) == 2
    # Bounded from the OLD end -- the most recent entries survive.
    assert list(cards_module._MLB_CARDS_CONTEXT_CACHE) == [("key-8",), ("key-9",)]


def test_context_cache_keeps_its_web_limit():
    with _as_web():
        for i in range(40):
            cards_module._cards_context_cache_put((f"key-{i}",), {"n": i})
    assert len(cards_module._MLB_CARDS_CONTEXT_CACHE) == 32


def test_worker_limit_is_far_below_the_web_limit():
    # Pinned so the worker bound cannot drift back up to the value that made
    # this a retention buffer.
    assert cards_module._MLB_CARDS_CONTEXT_CACHE_MAX_ENTRIES_WORKER <= 2
    assert (
        cards_module._MLB_CARDS_CONTEXT_CACHE_MAX_ENTRIES_WORKER
        < cards_module._MLB_CARDS_CONTEXT_CACHE_MAX_ENTRIES
    )


def test_cache_limit_selection_follows_the_service_type():
    with _as_worker():
        assert cards_module._cards_cache_limit() == cards_module._MLB_CARDS_CONTEXT_CACHE_MAX_ENTRIES_WORKER
    with _as_web():
        assert cards_module._cards_cache_limit() == cards_module._MLB_CARDS_CONTEXT_CACHE_MAX_ENTRIES


def test_eviction_is_logged_so_thrash_cannot_go_silent(capfd):
    # 3ca6c11d's count-only bound was invisible for three weeks because a cache
    # with a 0% hit rate looks identical to a working one from outside. An
    # eviction on the worker means a distinct key was produced this cycle.
    with _as_worker():
        for i in range(4):
            cards_module._cards_context_cache_put((f"key-{i}",), {"n": i})
    out = capfd.readouterr().out
    assert "CONTEXT_CACHE_EVICTED" in out
    assert "limit=2" in out


def test_no_eviction_log_when_nothing_is_evicted(capfd):
    with _as_worker():
        cards_module._cards_context_cache_put(("only",), {"n": 1})
    assert "CONTEXT_CACHE_EVICTED" not in capfd.readouterr().out


def test_web_caches_must_not_alias_each_other():
    # _today_cache_get returns its entry WITHOUT copying, so if both caches held
    # the same object a caller mutating the today entry would corrupt the
    # context entry too. This is why the web path still deepcopies into the
    # context cache and #253's single-copy shortcut is worker-only.
    page_key = ("page",)
    today_key = ("today",)
    result = {"games": [{"id": 1}]}
    with _as_web():
        cards_module._cards_context_cache_put(page_key, cards_module.deepcopy(result))
        cards_module._today_cache_put(today_key, result)
        served = cards_module._today_cache_get(today_key)
        served["games"].append({"id": 2})
        cached_page = cards_module._cards_context_cache_get(page_key)
    assert len(cached_page["games"]) == 1
