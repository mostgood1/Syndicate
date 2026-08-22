"""`#520`. A league whose match is UNDER WAY must never be scoped out of the sweep.

WHY THIS EXISTS. Measured in production 2026-08-22 21:13:37Z:

    soccer_source/primeira_liga/.../live_state_2026-08-22.json  (1 live games, ...)
    refresh_odds_sources.py --sports mlb,soccer --phase live --soccer-leagues mls

One league playing, a different league refreshed. Soccer's board quote age was
p50 23,941s (6.7h) and max 49,626s (13.8h) against `opportunity_gate`'s 900s
`LIVE_MARKET_MAX_AGE_SECONDS`, so every live soccer row was deleted for staleness
that the scope itself caused.

THE MECHANISM, and why no per-league tier logic could have caught it.
`_due_leagues_for_sport` builds its candidate set from
`_next_fixture_epoch_by_league`, which answers "when does this league NEXT play"
and therefore must discard fixtures that have already started
(`epoch <= now_epoch: continue`). A league with a match in progress contributes
no clock, so it is not in `candidates` at all -- not due, not skipped, absent.
`_league_interval_from_epoch`'s own `fixture_in_progress` branch is unreachable
from that caller, which is the tell: a branch written for this case that this
case can never reach.

The fix unions the live leagues in ahead of the ladder. These tests pin both
signals, the fail-open direction, and the property that matters -- that the scope
can only ever GROW for a live league, never shrink.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import live_refresh_loop as loop


NOW = 1_756_000_000.0  # fixed; a cadence test must not depend on the day it runs


class _Event:
    def __init__(self, event_id: str, epoch: float | None) -> None:
        self.event_id = event_id
        self._epoch = epoch

    def start_time_epoch(self) -> float | None:
        return self._epoch


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for key in (
        "SYNDICATE_IN_PROGRESS_FIXTURE_WINDOW_SECONDS",
        "SYNDICATE_IN_PROGRESS_FIXTURE_WINDOW_SECONDS_SOCCER",
        "SYNDICATE_LEAGUE_SCOPED_CADENCE",
    ):
        monkeypatch.delenv(key, raising=False)
    loop._NEXT_FIXTURE_BY_LEAGUE_CACHE.clear()
    yield
    loop._NEXT_FIXTURE_BY_LEAGUE_CACHE.clear()


def _schedule(monkeypatch, events_by_date):
    def _fetch(sport, date_str):
        return events_by_date.get(date_str, [])

    monkeypatch.setattr(loop, "fetch_schedule_for_date", _fetch)


def _no_artifacts(monkeypatch):
    monkeypatch.setattr(loop, "_artifact_live_leagues_for_sport", lambda sport, date: set())


# ---------------------------------------------------------------------------
# Signal 1: the kickoff window
# ---------------------------------------------------------------------------


def test_a_league_that_kicked_off_an_hour_ago_is_in_progress(monkeypatch):
    date_str = loop.central_datetime_from_epoch(NOW).date().isoformat()
    _schedule(monkeypatch, {date_str: [_Event("primeira_liga:1", NOW - 3600)]})
    assert loop._in_progress_leagues_for_sport("soccer", now_epoch=NOW) == {"primeira_liga"}


def test_a_league_kicking_off_later_is_not_in_progress(monkeypatch):
    date_str = loop.central_datetime_from_epoch(NOW).date().isoformat()
    _schedule(monkeypatch, {date_str: [_Event("epl:1", NOW + 3600)]})
    assert loop._in_progress_leagues_for_sport("soccer", now_epoch=NOW) == set()


def test_a_match_older_than_the_window_has_finished(monkeypatch):
    """The window is what makes this terminate. Without it every league that
    played at any point today would stay in scope until midnight."""
    date_str = loop.central_datetime_from_epoch(NOW).date().isoformat()
    _schedule(monkeypatch, {date_str: [_Event("epl:1", NOW - 5 * 3600)]})
    assert loop._in_progress_leagues_for_sport("soccer", now_epoch=NOW) == set()


def test_yesterdays_late_kickoff_still_counts(monkeypatch):
    """A 20:45 local kickoff is still playing at 00:15 the next day. Scanning
    only today would drop it at exactly the moment it is most live."""
    today = loop.central_datetime_from_epoch(NOW).date()
    from datetime import timedelta

    yesterday = (today - timedelta(days=1)).isoformat()
    _schedule(monkeypatch, {yesterday: [_Event("serie_a:9", NOW - 1800)]})
    assert loop._in_progress_leagues_for_sport("soccer", now_epoch=NOW) == {"serie_a"}


def test_an_unparseable_event_never_raises(monkeypatch):
    date_str = loop.central_datetime_from_epoch(NOW).date().isoformat()

    class _Broken:
        event_id = "epl:1"

        def start_time_epoch(self):
            raise RuntimeError("adapter changed shape")

    _schedule(monkeypatch, {date_str: [_Broken(), _Event("la_liga:2", NOW - 600)]})
    assert loop._in_progress_leagues_for_sport("soccer", now_epoch=NOW) == {"la_liga"}


def test_an_unreadable_date_does_not_decide_the_whole_answer(monkeypatch):
    today = loop.central_datetime_from_epoch(NOW).date().isoformat()

    def _fetch(sport, date_str):
        if date_str == today:
            return [_Event("epl:1", NOW - 900)]
        raise OSError("no schedule")

    monkeypatch.setattr(loop, "fetch_schedule_for_date", _fetch)
    assert loop._in_progress_leagues_for_sport("soccer", now_epoch=NOW) == {"epl"}


def test_the_window_is_configurable_and_zero_disables(monkeypatch):
    date_str = loop.central_datetime_from_epoch(NOW).date().isoformat()
    _schedule(monkeypatch, {date_str: [_Event("epl:1", NOW - 3600)]})
    monkeypatch.setenv("SYNDICATE_IN_PROGRESS_FIXTURE_WINDOW_SECONDS_SOCCER", "0")
    assert loop._in_progress_leagues_for_sport("soccer", now_epoch=NOW) == set()


# ---------------------------------------------------------------------------
# Signal 2: the league's own live-state artifact
# ---------------------------------------------------------------------------


def test_the_artifact_keeps_a_match_that_ran_past_the_window(monkeypatch, tmp_path):
    """The two signals are not redundant. A delayed or extra-time match outlives
    the kickoff window, and only the artifact still says it is playing."""
    league_dir = tmp_path / "soccer_source" / "epl" / "api" / "live_state"
    league_dir.mkdir(parents=True)
    (league_dir / "live_state_2026-08-22.json").write_text(json.dumps({"count": 1}), encoding="utf-8")
    monkeypatch.setattr(loop, "data_root", lambda: tmp_path)
    monkeypatch.setattr(
        "syndicate.features.soccer.sources.active_leagues_for_date", lambda date: ["epl", "la_liga"]
    )
    assert loop._artifact_live_leagues_for_sport("soccer", "2026-08-22") == {"epl"}


def test_a_zero_count_artifact_is_not_live(monkeypatch, tmp_path):
    league_dir = tmp_path / "soccer_source" / "epl" / "api" / "live_state"
    league_dir.mkdir(parents=True)
    (league_dir / "live_state_2026-08-22.json").write_text(json.dumps({"count": 0}), encoding="utf-8")
    monkeypatch.setattr(loop, "data_root", lambda: tmp_path)
    monkeypatch.setattr(
        "syndicate.features.soccer.sources.active_leagues_for_date", lambda date: ["epl"]
    )
    assert loop._artifact_live_leagues_for_sport("soccer", "2026-08-22") == set()


def test_a_non_league_scoped_sport_reads_no_artifacts(monkeypatch):
    assert loop._artifact_live_leagues_for_sport("mlb", "2026-08-22") == set()


# ---------------------------------------------------------------------------
# The union, and what it does to the scope
# ---------------------------------------------------------------------------


def test_the_in_progress_league_becomes_due_even_though_it_has_no_next_fixture(monkeypatch):
    """THE REGRESSION, stated at the level the bug lived at.

    `mls` plays tonight and is due on the ladder. `primeira_liga` is playing RIGHT
    NOW and has nothing scheduled after it, so `_next_fixture_epoch_by_league`
    returns nothing for it. Before `#520` the scope was `mls` alone.
    """
    today = loop.central_datetime_from_epoch(NOW).date().isoformat()
    _schedule(
        monkeypatch,
        {today: [_Event("mls:1", NOW + 1800), _Event("primeira_liga:2", NOW - 3600)]},
    )
    _no_artifacts(monkeypatch)

    by_league = loop._next_fixture_epoch_by_league("soccer", now_epoch=NOW)
    assert "primeira_liga" not in by_league, "the premise: the ladder cannot see it"

    due, reasons = loop._due_leagues_for_sport("soccer", now_epoch=NOW, markers={})
    assert "primeira_liga" in due
    assert reasons["primeira_liga"] == "due:live_now"
    assert "mls" in due


def test_a_live_league_ignores_its_own_cadence_marker(monkeypatch):
    """60 seconds, not the tier. A marker stamped one second ago would otherwise
    skip the league for hours, which is what an 8h soccer baseline means."""
    today = loop.central_datetime_from_epoch(NOW).date().isoformat()
    _schedule(monkeypatch, {today: [_Event("epl:1", NOW - 1800), _Event("epl:2", NOW + 86_400)]})
    _no_artifacts(monkeypatch)
    markers = {loop._league_marker_key("soccer", "epl"): NOW - 1.0}

    due, reasons = loop._due_leagues_for_sport("soccer", now_epoch=NOW, markers=markers)
    assert due == ["epl"]
    assert reasons["epl"] == "due:live_now"


def test_a_quiet_league_still_rides_its_tier(monkeypatch):
    """The fix ADDS live leagues. It must not turn the cadence gate off."""
    today = loop.central_datetime_from_epoch(NOW).date().isoformat()
    _schedule(monkeypatch, {today: [_Event("epl:1", NOW + 86_400)]})
    _no_artifacts(monkeypatch)
    markers = {loop._league_marker_key("soccer", "epl"): NOW - 1.0}

    due, reasons = loop._due_leagues_for_sport("soccer", now_epoch=NOW, markers=markers)
    assert due == []
    assert reasons["epl"].startswith("skip:")


def test_an_explicit_league_list_is_never_widened(monkeypatch):
    """A caller that names its leagues has stated a scope. A live league outside
    it is somebody else's problem -- growing past an explicit list would make
    this function unusable for any scoped caller."""
    today = loop.central_datetime_from_epoch(NOW).date().isoformat()
    _schedule(monkeypatch, {today: [_Event("epl:1", NOW - 600), _Event("mls:2", NOW - 600)]})
    _no_artifacts(monkeypatch)

    due, _ = loop._due_leagues_for_sport("soccer", now_epoch=NOW, markers={}, leagues=["mls"])
    assert due == ["mls"]


def test_liveness_failing_can_never_narrow_the_scope(monkeypatch):
    """The fail-open direction. If both signals blow up, the answer must be the
    pre-`#520` answer -- never a scope with the live league removed."""
    today = loop.central_datetime_from_epoch(NOW).date().isoformat()
    _schedule(monkeypatch, {today: [_Event("mls:1", NOW + 1800)]})

    def _boom(*args, **kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(loop, "_in_progress_leagues_for_sport", _boom)
    monkeypatch.setattr(loop, "_artifact_live_leagues_for_sport", _boom)

    due, _ = loop._due_leagues_for_sport("soccer", now_epoch=NOW, markers={})
    assert due == ["mls"], "an unresolvable liveness signal must be a no-op, not a filter"


def test_the_launch_scope_text_carries_the_live_league(monkeypatch):
    """End to end at the boundary that actually produces `--soccer-leagues`."""
    today = loop.central_datetime_from_epoch(NOW).date().isoformat()
    _schedule(
        monkeypatch,
        {today: [_Event("mls:1", NOW + 1800), _Event("primeira_liga:2", NOW - 3600)]},
    )
    _no_artifacts(monkeypatch)
    monkeypatch.setattr(loop, "_league_scoped_cadence_enabled", lambda: True)
    monkeypatch.setattr(loop, "_read_pregame_sport_sweep_epochs", lambda: {})

    scope = loop._due_league_scope_text("soccer", now_epoch=NOW)
    assert scope is not None
    assert set(scope.split(",")) == {"mls", "primeira_liga"}


# ---------------------------------------------------------------------------
# The remaining shape of the bug, made loud rather than auto-fixed
# ---------------------------------------------------------------------------


def test_a_live_sport_dropped_by_active_sports_says_so_loudly(monkeypatch, capsys):
    """nba/nhl are not weekly sports, so the carve-out does not claim them -- there
    is no counterpart yielding on the same predicate, and claiming them would be a
    double-write race rather than a partition. What must not happen is the silence
    that let NFL go 10 hours: `SWEEP_OWNERSHIP_EXCLUDED` alone reads as routine.
    """
    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_REFRESH_SPORTS", "mlb,nba")
    monkeypatch.setenv("SYNDICATE_ACTIVE_SPORTS", "mlb")
    monkeypatch.setenv("SYNDICATE_MLB_REFRESH_TICK_OWNER", "true")
    monkeypatch.setattr(loop, "_sport_has_in_progress_fixture", lambda sport, now_epoch: sport == "nba")

    kept = loop._live_refresh_loop_effective_sports("2026-11-14")
    printed = capsys.readouterr().out

    assert kept == ["mlb"]
    assert "SWEEP_OWNERSHIP_DROPPED_WHILE_LIVE" in printed
    assert "sport=nba" in printed


def test_a_dropped_sport_that_is_not_playing_stays_quiet(monkeypatch, capsys):
    """The warning has to be rare to be worth reading."""
    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_REFRESH_SPORTS", "mlb,nba")
    monkeypatch.setenv("SYNDICATE_ACTIVE_SPORTS", "mlb")
    monkeypatch.setenv("SYNDICATE_MLB_REFRESH_TICK_OWNER", "true")
    monkeypatch.setattr(loop, "_sport_has_in_progress_fixture", lambda sport, now_epoch: False)

    loop._live_refresh_loop_effective_sports("2026-11-14")
    printed = capsys.readouterr().out

    assert "SWEEP_OWNERSHIP_EXCLUDED" in printed
    assert "SWEEP_OWNERSHIP_DROPPED_WHILE_LIVE" not in printed


def test_the_liveness_probe_never_shells_out(monkeypatch):
    """`_espn_has_live_game` costs a subprocess with a 12s timeout. Running it per
    dropped sport per 60s tick to emit a warning would cost more than the refresh
    it warns about, so this probe must read only the TTL-cached schedule."""
    today = loop.central_datetime_from_epoch(NOW).date().isoformat()
    _schedule(monkeypatch, {today: [_Event("nba:1", NOW - 3600)]})

    def _forbidden(*args, **kwargs):
        raise AssertionError("the diagnostic probe must not shell out")

    monkeypatch.setattr(loop.subprocess, "run", _forbidden)
    assert loop._sport_has_in_progress_fixture("nba", now_epoch=NOW) is True
