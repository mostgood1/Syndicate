"""home's statsapi fan-out must not be able to starve `/healthz`.

THE INCIDENT THESE PIN. `_mlb_feed_live_payload` reads `raw_feed_live_path()`
and falls through to a live HTTPS call to statsapi.mlb.com when it misses. On
the web service it ALWAYS misses for today's date, because
`mlb_source/source_artifacts/data/raw/statsapi/feed_live/**` matches none of the
175 entries in `HOT_ARTIFACT_PATTERNS` -- so every home request made up to 15
network calls, uncached.

Measured on production web 2026-08-22 (`MLB_GAMES_STAGE_MS`): `apply_live_scores`
3318 / 7991 / 8400 / 5498 / 3494 ms against a `build_cards_page_context` of 19ms
in the same request, and 8400 > the 8000ms wall-clock budget -- i.e. the budget
was exhausted, which disk reads cannot do. With 8 request slots
(WEB_CONCURRENCY=2 x GUNICORN_THREADS=4), a handful of concurrent home requests
held all 8, `/healthz` went unanswered for 84s, and Render SIGTERM'd the process
three times in four minutes (17:14:08, 17:15:38, 17:17:38 -- new gunicorn master
pid each time, ~15s with no listener, every request in those windows a 502).

So the property that matters is NOT "there is a cache". It is that **at most one
request thread is ever blocked on statsapi**, which is what leaves a slot free
for the health check while the upstream is slow or down.
"""

from __future__ import annotations

import threading
import time

from unittest.mock import patch

import pytest

from syndicate.blueprints import home as home_module


@pytest.fixture(autouse=True)
def _clear_feed_live_cache():
    home_module._MLB_FEED_LIVE_STATE_CACHE.clear()
    home_module._MLB_FEED_LIVE_STATE_REFRESH_LOCKS.clear()
    yield
    home_module._MLB_FEED_LIVE_STATE_CACHE.clear()
    home_module._MLB_FEED_LIVE_STATE_REFRESH_LOCKS.clear()


def _live(runs: int) -> dict[str, object]:
    return {"away_pts": runs, "home_pts": 0, "in_progress": True, "final": False, "status": "Top 3"}


def _fetch_returning(mapping, calls):
    def _fake(game_pks, selected_date, *, overall_timeout=8.0):
        calls.append(tuple(sorted(game_pks)))
        return {pk: mapping.get(pk) for pk in game_pks}

    return _fake


def test_no_game_pks_never_reaches_the_fan_out():
    calls: list[tuple[int, ...]] = []
    with patch.object(home_module, "_mlb_feed_live_states_uncached", _fetch_returning({}, calls)):
        assert home_module._mlb_feed_live_states([], "2026-08-22") == {}
    assert calls == []


def test_second_call_inside_the_ttl_does_not_refetch():
    calls: list[tuple[int, ...]] = []
    mapping = {1: _live(2), 2: _live(0)}
    with patch.object(home_module, "_mlb_feed_live_states_uncached", _fetch_returning(mapping, calls)):
        first = home_module._mlb_feed_live_states([1, 2], "2026-08-22")
        second = home_module._mlb_feed_live_states([1, 2], "2026-08-22")
    assert len(calls) == 1
    assert first[1]["away_pts"] == 2
    assert second == first


def test_expiry_past_the_ttl_refetches():
    calls: list[tuple[int, ...]] = []
    mapping = {1: _live(2)}
    with patch.object(home_module, "_mlb_feed_live_states_uncached", _fetch_returning(mapping, calls)):
        home_module._mlb_feed_live_states([1], "2026-08-22")
        # Backdate the stored entry rather than patching the clock: the stored
        # shape is (stored_at, states) and this exercises the real comparison.
        key = home_module._mlb_feed_live_states_cache_key([1], "2026-08-22")
        stored_at, states = home_module._MLB_FEED_LIVE_STATE_CACHE[key]
        home_module._MLB_FEED_LIVE_STATE_CACHE[key] = (
            stored_at - home_module._MLB_FEED_LIVE_STATE_TTL_SECONDS - 1.0,
            states,
        )
        home_module._mlb_feed_live_states([1], "2026-08-22")
    assert len(calls) == 2


def test_a_result_that_resolved_nothing_is_not_cached():
    # learnings.md 2026-08-18: "a cache with a TTL can serve EMPTINESS as
    # authoritative" -- 1,282 BVP cache files, every one empty, concluded from
    # twice in opposite directions. An all-None fan-out means statsapi failed,
    # not that the games have no state, so it must not be stored. Single flight
    # (below) is what keeps the retry from costing every thread.
    calls: list[tuple[int, ...]] = []
    with patch.object(home_module, "_mlb_feed_live_states_uncached", _fetch_returning({}, calls)):
        first = home_module._mlb_feed_live_states([1, 2], "2026-08-22")
        second = home_module._mlb_feed_live_states([1, 2], "2026-08-22")
    assert first == {1: None, 2: None}
    assert second == {1: None, 2: None}
    assert len(calls) == 2
    assert home_module._MLB_FEED_LIVE_STATE_CACHE == {}


def test_a_partial_result_is_cached_because_it_resolved_something():
    calls: list[tuple[int, ...]] = []
    with patch.object(home_module, "_mlb_feed_live_states_uncached", _fetch_returning({1: _live(4)}, calls)):
        states = home_module._mlb_feed_live_states([1, 2], "2026-08-22")
        home_module._mlb_feed_live_states([1, 2], "2026-08-22")
    assert states[1]["away_pts"] == 4
    assert states[2] is None
    assert len(calls) == 1


def test_a_second_thread_does_not_queue_behind_an_in_flight_fetch():
    # THE LOAD-BEARING TEST. Without single flight all 8 gunicorn threads miss
    # the cold cache together and all 8 block on statsapi for up to 8s, which is
    # precisely what left /healthz unanswered for 84 seconds.
    started = threading.Event()
    release = threading.Event()
    calls: list[tuple[int, ...]] = []

    def _slow_fetch(game_pks, selected_date, *, overall_timeout=8.0):
        calls.append(tuple(sorted(game_pks)))
        started.set()
        assert release.wait(timeout=10), "fetch was never released"
        return {pk: _live(1) for pk in game_pks}

    with patch.object(home_module, "_mlb_feed_live_states_uncached", _slow_fetch):
        holder = threading.Thread(
            target=home_module._mlb_feed_live_states, args=([1, 2], "2026-08-22"), daemon=True
        )
        holder.start()
        assert started.wait(timeout=5), "holder never entered the fetch"

        began = time.monotonic()
        second = home_module._mlb_feed_live_states([1, 2], "2026-08-22")
        elapsed = time.monotonic() - began

        release.set()
        holder.join(timeout=10)

    # Returned without waiting on the holder, and degraded exactly the way the
    # 8s budget already degrades today: no state rather than a blocked thread.
    assert elapsed < 1.0
    assert second == {1: None, 2: None}
    # And only ONE fetch was ever started for the key.
    assert len(calls) == 1


def test_a_second_thread_serves_the_last_good_value_rather_than_nothing():
    calls: list[tuple[int, ...]] = []
    started = threading.Event()
    release = threading.Event()

    with patch.object(home_module, "_mlb_feed_live_states_uncached", _fetch_returning({1: _live(7)}, calls)):
        home_module._mlb_feed_live_states([1], "2026-08-22")

    key = home_module._mlb_feed_live_states_cache_key([1], "2026-08-22")
    stored_at, states = home_module._MLB_FEED_LIVE_STATE_CACHE[key]
    home_module._MLB_FEED_LIVE_STATE_CACHE[key] = (
        stored_at - home_module._MLB_FEED_LIVE_STATE_TTL_SECONDS - 1.0,
        states,
    )

    def _slow_fetch(game_pks, selected_date, *, overall_timeout=8.0):
        started.set()
        assert release.wait(timeout=10)
        return {pk: _live(9) for pk in game_pks}

    with patch.object(home_module, "_mlb_feed_live_states_uncached", _slow_fetch):
        holder = threading.Thread(
            target=home_module._mlb_feed_live_states, args=([1], "2026-08-22"), daemon=True
        )
        holder.start()
        assert started.wait(timeout=5)
        second = home_module._mlb_feed_live_states([1], "2026-08-22")
        release.set()
        holder.join(timeout=10)

    # One tick stale beats a blocked thread, and beats a blank score.
    assert second[1]["away_pts"] == 7


def test_callers_cannot_reach_into_the_cached_state():
    # _apply_mlb_live_scores assigns the returned state straight onto a game
    # dict that goes on to templates. A cached entry is shared by every request
    # in the window, so one request mutating it would corrupt the next.
    calls: list[tuple[int, ...]] = []
    with patch.object(home_module, "_mlb_feed_live_states_uncached", _fetch_returning({1: _live(3)}, calls)):
        first = home_module._mlb_feed_live_states([1], "2026-08-22")
        first[1]["away_pts"] = 999
        second = home_module._mlb_feed_live_states([1], "2026-08-22")
    assert second[1]["away_pts"] == 3


def test_different_dates_do_not_share_an_entry():
    calls: list[tuple[int, ...]] = []
    with patch.object(home_module, "_mlb_feed_live_states_uncached", _fetch_returning({1: _live(1)}, calls)):
        home_module._mlb_feed_live_states([1], "2026-08-21")
        home_module._mlb_feed_live_states([1], "2026-08-22")
    assert len(calls) == 2


def test_the_cache_is_bounded():
    calls: list[tuple[int, ...]] = []
    limit = home_module._MLB_FEED_LIVE_STATE_CACHE_MAX_ENTRIES
    with patch.object(home_module, "_mlb_feed_live_states_uncached", _fetch_returning({1: _live(1)}, calls)):
        for day in range(limit + 8):
            home_module._mlb_feed_live_states([1], f"2026-08-{day:02d}")
    assert len(home_module._MLB_FEED_LIVE_STATE_CACHE) == limit
    assert len(home_module._MLB_FEED_LIVE_STATE_REFRESH_LOCKS) <= limit
