"""NFL joins the fast odds tick on game days -- without reviving the write race.

THE PROBLEM, measured on production 2026-08-07: NFL/NCAAF/NCAAB were blanket-
excluded from the fast odds tick (`_WEEKLY_SPORTS_TICK_EXCLUDABLE`) and handed to
refresh-worker's weekly autorun, which runs 6-hourly and is default-OFF. The NFL
board carried rows with `age_seconds ~86,455` -- 24 hours -- while MLB captured
every ~26 minutes. Prices move continuously whether or not games are weekly.

THE CONSTRAINT: that blanket split was not arbitrary. Both owners target the same
non-date-partitioned football artifacts, so letting both run is a real write race
-- silent corruption, not a visible gap.

THE FIX: one predicate, `sport_has_games_within`, called by BOTH services to
partition ownership rather than share it.

    games in horizon -> fast tick owns it, weekly autorun drops it
    no games         -> weekly autorun owns it, fast tick excludes it

These tests pin the three things that make that safe: the partition is exclusive,
an unresolvable schedule fails toward capture on the tick side, and it fails
toward YIELDING on the autorun side so the two can never both claim.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import schedule_adapter


@pytest.fixture(autouse=True)
def _clear_window_cache():
    schedule_adapter._GAME_WINDOW_CACHE.clear()
    yield
    schedule_adapter._GAME_WINDOW_CACHE.clear()


def _stub_espn(monkeypatch, by_date: dict[str, list[dict]] | Exception):
    """Replace the ESPN football fetcher. Pass an Exception to simulate a
    transport failure -- the case that must not read as "no games"."""

    def _fake(sport, date_str, *, timeout=12, strict=False):
        if isinstance(by_date, Exception):
            if strict:
                raise by_date
            return []
        return by_date.get(date_str, [])

    monkeypatch.setattr(schedule_adapter, "_fetch_espn_football_schedule", _fake)


_GAME = [{"event_id": "401873272", "home": "Cincinnati Bengals", "away": "Detroit Lions", "start_time_utc": "2026-08-13T23:00Z"}]


def test_game_today_claims_the_sport(monkeypatch):
    _stub_espn(monkeypatch, {"2026-08-13": _GAME})
    assert schedule_adapter.sport_has_games_within("nfl", "2026-08-13", horizon_days=1) is True


def test_game_tomorrow_claims_the_sport(monkeypatch):
    """Horizon 1 = today AND tomorrow. A game kicking off tonight has had its
    market moving all day, so day-of-only would start capturing too late."""
    _stub_espn(monkeypatch, {"2026-08-13": _GAME})
    assert schedule_adapter.sport_has_games_within("nfl", "2026-08-12", horizon_days=1) is True


def test_no_games_anywhere_in_horizon_does_not_claim(monkeypatch):
    _stub_espn(monkeypatch, {})
    assert schedule_adapter.sport_has_games_within("nfl", "2026-08-07", horizon_days=1) is False


def test_horizon_zero_looks_only_at_the_day(monkeypatch):
    _stub_espn(monkeypatch, {"2026-08-13": _GAME})
    assert schedule_adapter.sport_has_games_within("nfl", "2026-08-12", horizon_days=0) is False


def test_fetch_failure_does_not_read_as_no_games(monkeypatch):
    """The load-bearing one.

    `fetch_schedule_for_date` returns [] for a swallowed timeout exactly as it
    does for a genuinely empty slate. A gate that trusted empty would hand NFL
    back to the 6-hourly path every time ESPN was slow, and the failure would be
    invisible -- indistinguishable from a quiet week.
    """
    _stub_espn(monkeypatch, TimeoutError("espn slow"))
    assert schedule_adapter.sport_has_games_within("nfl", "2026-08-07", horizon_days=1) is True


def test_unknown_can_be_made_strict_explicitly(monkeypatch):
    _stub_espn(monkeypatch, TimeoutError("espn slow"))
    assert (
        schedule_adapter.sport_has_games_within(
            "nfl", "2026-08-07", horizon_days=1, unknown_means_yes=False
        )
        is False
    )


def test_a_real_game_outweighs_a_failed_day(monkeypatch):
    """One day failing must not discard a game found on another day."""
    calls = {"n": 0}

    def _flaky(sport, date_str, *, timeout=12, strict=False):
        calls["n"] += 1
        if date_str == "2026-08-12":
            raise TimeoutError("espn slow")
        return _GAME

    monkeypatch.setattr(schedule_adapter, "_fetch_espn_football_schedule", _flaky)
    assert schedule_adapter.sport_has_games_within("nfl", "2026-08-12", horizon_days=1) is True


def test_malformed_date_is_unknown_not_empty(monkeypatch):
    _stub_espn(monkeypatch, {})
    assert schedule_adapter.sport_has_games_within("nfl", "not-a-date", horizon_days=1) is True


def test_result_is_cached_so_the_tick_does_not_refetch(monkeypatch):
    calls = {"n": 0}

    def _counting(sport, date_str, *, timeout=12, strict=False):
        calls["n"] += 1
        return _GAME

    monkeypatch.setattr(schedule_adapter, "_fetch_espn_football_schedule", _counting)
    for _ in range(5):
        schedule_adapter.sport_has_games_within("nfl", "2026-08-13", horizon_days=1)
    assert calls["n"] == 1, f"predicate refetched per call ({calls['n']}) -- it runs on every tick"


# ---------------------------------------------------------------------------
# The partition itself: exactly one owner, never two.
# ---------------------------------------------------------------------------


def test_ownership_is_exclusive_on_a_game_day(monkeypatch):
    from syndicate.features.shared import live_refresh_loop
    import scripts.run_refresh_worker as worker

    _stub_espn(monkeypatch, {"2026-08-13": _GAME})
    monkeypatch.setattr(worker, "_active_sports_for_date", lambda d: "mlb,nfl,soccer")

    claimed = live_refresh_loop._weekly_sport_claimed_by_fast_tick("nfl", "2026-08-13")
    autorun_owns = "nfl" in worker._active_weekly_sports_for_date("2026-08-13").split(",")

    assert claimed is True
    assert autorun_owns is False, "both owners claimed nfl -- the write race is back"


def test_ownership_is_exclusive_on_a_quiet_day(monkeypatch):
    from syndicate.features.shared import live_refresh_loop
    import scripts.run_refresh_worker as worker

    _stub_espn(monkeypatch, {})
    monkeypatch.setattr(worker, "_active_sports_for_date", lambda d: "mlb,nfl,soccer")

    claimed = live_refresh_loop._weekly_sport_claimed_by_fast_tick("nfl", "2026-08-07")
    autorun_owns = "nfl" in worker._active_weekly_sports_for_date("2026-08-07").split(",")

    assert claimed is False
    assert autorun_owns is True, "nobody owns nfl on a quiet day -- schedule work would never run"


def test_autorun_yields_when_ownership_cannot_be_resolved(monkeypatch):
    """Asymmetric on purpose.

    The fast tick claims on unknown; the autorun must therefore YIELD on
    unknown. Both-claim corrupts a shared artifact silently; neither-claim is a
    stale board, which is visible and which audit_slate_coverage.py catches.
    """
    import scripts.run_refresh_worker as worker

    monkeypatch.setattr(worker, "_active_sports_for_date", lambda d: "mlb,nfl,soccer")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("cannot resolve ownership")

    monkeypatch.setattr(
        "syndicate.features.shared.live_refresh_loop._weekly_sport_claimed_by_fast_tick",
        _boom,
    )
    assert worker._active_weekly_sports_for_date("2026-08-07") == ""


def test_non_weekly_sports_are_untouched(monkeypatch):
    import scripts.run_refresh_worker as worker

    _stub_espn(monkeypatch, {})
    monkeypatch.setattr(worker, "_active_sports_for_date", lambda d: "mlb,wnba,soccer")
    # No weekly sport is in season -> nothing for the autorun, and mlb/wnba/soccer
    # were never in its remit to begin with.
    assert worker._active_weekly_sports_for_date("2026-08-07") == ""
