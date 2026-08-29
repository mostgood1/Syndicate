"""The call-scoped soccer read memo. `[2026-08-29]`

WHY THESE TESTS ARE SHAPED LIKE THIS. The thing being added is a cache, in a
module whose four hottest loaders each carry an explicit "Not cached (2026-07-24
fix)" comment -- an `@lru_cache` there once froze every MLS match at
`status_state="pre"` 0-0 for days. So the property under test is not "does it
cache" but "does it cache for EXACTLY one assembly pass and not one instruction
longer", and the no-scope and across-scope cases matter more than the hit case.

REACHABILITY BEFORE CORRECTNESS: `test_no_scope_is_not_memoized` is the
`off != on` control. Four fixes in one session on 2026-08-28 were deployed inert
and passed their correctness tests, because nothing asserted the new path was
reached at all.
"""

from __future__ import annotations

import threading

import pytest

from syndicate.features.soccer import sources as S


@pytest.fixture
def counting_reads(monkeypatch):
    """Count calls to the UNCACHED impls, which is what a read actually costs."""
    counts: dict[str, int] = {"live_state": 0, "picks": 0, "markets": 0}

    def fake_live(league, selected_date):
        counts["live_state"] += 1
        return {"games": {}, "match_box": {}}

    def fake_picks(league, selected_date):
        counts["picks"] += 1
        return ()

    def fake_markets(league, selected_date):
        counts["markets"] += 1
        return ()

    monkeypatch.setattr(S, "_live_state_payload_uncached", fake_live)
    monkeypatch.setattr(S, "_picks_rows_uncached", fake_picks)
    monkeypatch.setattr(S, "_game_markets_rows_uncached", fake_markets)
    return counts


def test_no_scope_is_not_memoized(counting_reads):
    """OFF != ON. Without a scope every call reads, exactly as before."""
    for _ in range(5):
        S.live_state_payload("epl", "2026-08-29")
        S.picks_rows("epl", "2026-08-29")
        S.game_markets_rows("epl", "2026-08-29")
    assert counting_reads == {"live_state": 5, "picks": 5, "markets": 5}
    assert not S.soccer_read_scope_active()


def test_scope_collapses_repeat_reads(counting_reads):
    with S.soccer_read_scope():
        assert S.soccer_read_scope_active()
        for _ in range(5):
            S.live_state_payload("epl", "2026-08-29")
            S.picks_rows("epl", "2026-08-29")
            S.game_markets_rows("epl", "2026-08-29")
    assert counting_reads == {"live_state": 1, "picks": 1, "markets": 1}


def test_scope_keys_on_league_and_date(counting_reads):
    """A memo that ignored its arguments would serve one league's live state
    for another -- the failure this key exists to prevent."""
    with S.soccer_read_scope():
        S.live_state_payload("epl", "2026-08-29")
        S.live_state_payload("mls", "2026-08-29")
        S.live_state_payload("epl", "2026-08-30")
        S.live_state_payload("epl", "2026-08-29")
    assert counting_reads["live_state"] == 3


def test_memo_does_not_survive_the_scope(counting_reads):
    """THE 2026-07-24 REGRESSION TEST. A second pass must re-read: this is the
    whole difference between this and the `@lru_cache` that was removed."""
    for _ in range(3):
        with S.soccer_read_scope():
            S.live_state_payload("epl", "2026-08-29")
            S.live_state_payload("epl", "2026-08-29")
    assert counting_reads["live_state"] == 3
    assert not S.soccer_read_scope_active()


def test_scope_is_reentrant_and_inner_exit_does_not_tear_down_outer(counting_reads):
    with S.soccer_read_scope():
        S.live_state_payload("epl", "2026-08-29")
        with S.soccer_read_scope():
            S.live_state_payload("epl", "2026-08-29")
        # The inner `with` has exited; the outer memo must still be live.
        assert S.soccer_read_scope_active()
        S.live_state_payload("epl", "2026-08-29")
    assert counting_reads["live_state"] == 1
    assert not S.soccer_read_scope_active()


def test_scope_is_released_when_the_body_raises(counting_reads):
    with pytest.raises(RuntimeError):
        with S.soccer_read_scope():
            S.live_state_payload("epl", "2026-08-29")
            raise RuntimeError("boom")
    assert not S.soccer_read_scope_active()
    S.live_state_payload("epl", "2026-08-29")
    assert counting_reads["live_state"] == 2


def test_scope_does_not_leak_between_threads(counting_reads):
    """refresh-worker assembles boards on a dedicated drain thread while web
    serves requests on others. A module-global dict would hand one thread's
    live-state snapshot to another."""
    seen: list[bool] = []
    barrier = threading.Barrier(2)

    def other():
        barrier.wait()
        seen.append(S.soccer_read_scope_active())
        S.live_state_payload("epl", "2026-08-29")

    thread = threading.Thread(target=other)
    with S.soccer_read_scope():
        S.live_state_payload("epl", "2026-08-29")
        thread.start()
        barrier.wait()
        thread.join()
    assert seen == [False], "a scope leaked into another thread"
    assert counting_reads["live_state"] == 2


def test_none_and_empty_results_are_memoized_too(counting_reads, monkeypatch):
    """A MISS IS THE EXPENSIVE CASE on the keyvalue path -- it pays the store
    round trip AND the disk fallback -- so it must not be re-run per fixture."""
    monkeypatch.setattr(S, "_live_state_payload_uncached", lambda l, d: (counting_reads.__setitem__("live_state", counting_reads["live_state"] + 1), None)[1])
    with S.soccer_read_scope():
        for _ in range(4):
            assert S.live_state_payload("epl", "2026-08-29") is None
    assert counting_reads["live_state"] == 1


# ---------------------------------------------------------------------------
# INTEGRATION: does `week_games` actually REACH the memo?
#
# The unit tests above prove the mechanism works when called. They cannot prove
# the production path establishes a scope at all -- which is exactly how four
# fixes shipped inert on 2026-08-28. This asserts the load COUNT through the
# real `week_games`, with fixtures fabricated so the test does not depend on
# `data/` (a worktree has none, and a data-less arm once produced a confident
# wrong "5 tests are failing" in this same subsystem).

FIXTURE_COUNT = 9
_DATES = ("2026-08-29", "2026-08-30")


@pytest.fixture
def fabricated_week(monkeypatch, counting_reads):
    from syndicate.features.soccer import cards as C

    fixtures = [
        {
            "event_id": f"evt{i}",
            "home_team": f"Home {i}",
            "away_team": f"Away {i}",
            "date": _DATES[0],
        }
        for i in range(FIXTURE_COUNT)
    ]

    def fake_matches(league, season, week):
        return list(fixtures)

    def fake_dates(league, season, week):
        return list(_DATES)

    def fake_reco(league, date_str):
        return {
            "matches": [
                {
                    "event_id": f["event_id"],
                    "match_id": f["event_id"],
                    "date": date_str,
                    "matchup": {"home_team": f["home_team"], "away_team": f["away_team"]},
                    "status_state": "pre",
                    "win_probability": {},
                    "team_projection": {},
                    "total_distribution": {},
                    "volume_projection": {},
                    "periods": {},
                    "top_props": [],
                }
                for f in fixtures
            ],
            "player_props": [],
        }

    monkeypatch.setattr(C, "week_matches", fake_matches)
    monkeypatch.setattr(C, "week_date_list", fake_dates)
    monkeypatch.setattr(C, "recommendations_payload", fake_reco)
    return C, counting_reads


def test_week_games_collapses_the_per_fixture_reads(fabricated_week):
    cards, counts = fabricated_week
    games = cards.week_games("epl", 3, 2026)
    assert len(games) == FIXTURE_COUNT, "fixtures must still all build"
    # One read per (league, date) that the pass touches, NOT one per fixture.
    assert counts["live_state"] <= len(_DATES), counts
    assert counts["picks"] <= len(_DATES), counts
    assert counts["markets"] <= len(_DATES), counts


def test_week_games_without_the_scope_reads_per_fixture(fabricated_week, monkeypatch):
    """THE CONTROL. Neutralises the scope and asserts the count explodes, so a
    passing test above cannot be explained by the reads having gone away for
    some unrelated reason."""
    import contextlib

    cards, counts = fabricated_week

    @contextlib.contextmanager
    def no_scope():
        yield {}

    monkeypatch.setattr(cards, "soccer_read_scope", no_scope)
    cards.week_games("epl", 3, 2026)
    assert counts["live_state"] >= FIXTURE_COUNT, counts


def test_week_games_leaves_no_scope_behind(fabricated_week):
    cards, _counts = fabricated_week
    cards.week_games("epl", 3, 2026)
    assert not S.soccer_read_scope_active()
