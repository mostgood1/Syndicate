"""Lane `slate-starting-soon-phase`: REACHABILITY of the starting-soon phase.

Every test drives the real call path twice -- flag off, then on -- against the
same reading and asserts the outcomes DIFFER (`model_engine_standard.md`:
reachability before correctness). The motivating reading is NFL 75 minutes
before kickoff, 2026-09-27.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.shared import live_refresh_loop as loop
from syndicate.features.shared import slate_phase as sp
from syndicate.features.shared.schedule_adapter import ScheduleEvent

NOW = 1_790_000_000.0
KICKOFF = NOW + 75 * 60
FLAG = "SYNDICATE_SLATE_STARTING_SOON_ENABLED"


@pytest.fixture(autouse=True)
def _nfl_starting_soon(monkeypatch):
    """NFL: next start 75 min out, not live. Everything else: nothing scheduled."""
    for key in (
        FLAG,
        "SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS",
        "SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_NFL",
        "SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE",
        "SYNDICATE_LIVE_REFRESH_LOOP_SPORTS",
        "SYNDICATE_T_WINDOW_MIN_GAP_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(loop, "_next_fixture_epoch", lambda sport, now_epoch: KICKOFF if sport == "nfl" else None)
    monkeypatch.setattr(loop, "_LIVE_STATUS_CHECKERS", {"nfl": lambda date_str: False, "mlb": lambda date_str: False})
    sp._LIVE_CACHE.clear()
    loop._COMMENCE_TIMES_CACHE.clear()
    yield
    sp._LIVE_CACHE.clear()
    loop._COMMENCE_TIMES_CACHE.clear()


def test_sweep_interval_off_is_baseline_on_is_starting_soon(monkeypatch):
    off = loop._pregame_sweep_interval_for_tick("nfl", now_epoch=NOW)
    monkeypatch.setenv(FLAG, "true")
    on = loop._pregame_sweep_interval_for_tick("nfl", now_epoch=NOW)
    assert off == 7200, "pre-change behaviour: <3h fell back to the flat 2h baseline"
    assert on == sp.DEFAULT_STARTING_SOON_SWEEP_INTERVAL_SECONDS
    assert off != on


def test_sweep_interval_on_but_far_from_kickoff_is_unchanged(monkeypatch):
    monkeypatch.setattr(loop, "_next_fixture_epoch", lambda sport, now_epoch: NOW + 8 * 3600)
    monkeypatch.setenv(FLAG, "true")
    assert loop._pregame_sweep_interval_for_tick("nfl", now_epoch=NOW) == 7200


def test_explicit_every_tick_override_is_never_slowed(monkeypatch):
    monkeypatch.setenv("SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_NFL", "0")
    monkeypatch.setenv(FLAG, "true")
    assert loop._pregame_sweep_interval_for_tick("nfl", now_epoch=NOW) == 0


def _nfl_schedule(sport, date_str, **_):
    if sport != "nfl":
        return []
    stamp = __import__("datetime").datetime.fromtimestamp(NOW + 60 * 60, tz=__import__("datetime").timezone.utc)
    return [ScheduleEvent("nfl", "401", "KC", "BUF", stamp.strftime("%Y-%m-%dT%H:%M:%SZ"))]


def test_t_window_reaches_nfl_only_when_on(monkeypatch):
    monkeypatch.setattr(loop, "fetch_schedule_for_date", _nfl_schedule)
    monkeypatch.setattr(loop, "_read_t_window_markers", lambda date_str: {})
    for sport in ("mlb", "wnba", "soccer"):
        monkeypatch.setitem(loop._T_WINDOW_COMMENCE_PROVIDERS, sport, lambda date_str: [])
    off = loop._t_window_due_sports(now_epoch=NOW, date_str="2026-09-27")
    loop._COMMENCE_TIMES_CACHE.clear()
    monkeypatch.setenv(FLAG, "true")
    on = loop._t_window_due_sports(now_epoch=NOW, date_str="2026-09-27")
    assert "nfl" not in off
    assert on == {"nfl": {"nfl:ramp:401": NOW}}


def test_relaunch_cooldown_shorter_only_when_on(monkeypatch):
    monkeypatch.setattr(
        loop,
        "_read_last_pregame_launch",
        lambda: {"date": "2026-09-27", "epoch": NOW - 900, "sports": {"nfl": NOW - 900}},
    )
    off = loop._pregame_relaunch_blocked(now_epoch=NOW, date_str="2026-09-27", sports=["nfl"])
    monkeypatch.setenv(FLAG, "true")
    on = loop._pregame_relaunch_blocked(now_epoch=NOW, date_str="2026-09-27", sports=["nfl"])
    assert off is True and on is False


def test_off_hours_ceiling_shorter_only_when_on(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_REFRESH_LOOP_SPORTS", "nfl")
    monkeypatch.setattr(loop, "_any_tracked_sport_has_upcoming_game", lambda date_str, now_epoch: True)
    monkeypatch.setattr(loop, "_read_last_odds_refresh_launch", lambda: {"epoch": NOW - 700})
    off = loop._off_hours_gate_blocks_launch(now_epoch=NOW, any_live=False, date_str="2026-09-27")
    monkeypatch.setenv(FLAG, "true")
    on = loop._off_hours_gate_blocks_launch(now_epoch=NOW, any_live=False, date_str="2026-09-27")
    assert off is True and on is False


def test_injury_change_forces_nfl_only_when_on(monkeypatch, tmp_path: Path):
    store: dict = {}
    injuries = tmp_path / "injuries_2026.csv"
    injuries.write_text("player,status\nA,Questionable\n")
    monkeypatch.setattr(loop, "_meta_dir", lambda: tmp_path)
    monkeypatch.setattr(loop, "read_json_file", lambda path: store.get(str(path)))
    monkeypatch.setattr(loop, "write_json_file", lambda path, payload: store.__setitem__(str(path), payload))
    monkeypatch.setitem(loop._STARTING_SOON_INJURY_FILES, "nfl", lambda date_str: injuries)

    def run():
        return loop._starting_soon_injury_change_sports(["nfl", "mlb"], now_epoch=NOW, date_str="2026-09-27")

    assert run() == set()  # flag off: never checked
    injuries.write_text("player,status\nA,Out\n")
    assert run() == set()
    monkeypatch.setenv(FLAG, "true")
    assert run() == set()  # baseline recorded
    injuries.write_text("player,status\nA,Out\nB,Doubtful\n")
    assert run() == {"nfl"}
    assert run() == set()


def test_t_window_min_gap_credits_instead_of_forcing(monkeypatch):
    credited = {}
    monkeypatch.setattr(loop, "_read_pregame_sport_sweep_epochs", lambda: {"nfl": NOW - 60, "mlb": NOW - 3600})
    monkeypatch.setattr(loop, "_record_t_window_markers", lambda date_str, markers: credited.update(markers))
    due = {"nfl": {"nfl:ramp:1": NOW}, "mlb": {"mlb:closing:2": NOW}}
    kept = loop._drop_t_windows_covered_by_recent_sweep({"nfl", "mlb"}, due, now_epoch=NOW, date_str="d")
    assert kept == {"mlb"}
    assert credited == {"nfl:ramp:1": NOW}


def test_tick_meta_off_computes_nothing_observe_shows_phases(monkeypatch, capsys):
    """Both flags absent: no phase work at all (it costs subprocesses). OBSERVE:
    the phase is visible while the starting-soon behaviour stays off."""
    monkeypatch.delenv("SYNDICATE_SLATE_PHASE_OBSERVE", raising=False)

    def must_not_run(date_str):
        raise AssertionError("phase resolved with both flags off")

    monkeypatch.setattr(loop, "_active_sports_for_date", must_not_run)
    assert loop._slate_phases_for_tick(now_epoch=NOW, date_str="2026-09-27") == {"enabled": False, "observing": False}

    monkeypatch.setattr(loop, "_active_sports_for_date", lambda date_str: "nfl,mlb")
    monkeypatch.setenv("SYNDICATE_SLATE_PHASE_OBSERVE", "true")
    sp._LAST_PRINTED.clear()
    meta = loop._slate_phases_for_tick(now_epoch=NOW, date_str="2026-09-27")
    assert meta["enabled"] is False and meta["observing"] is True
    assert loop._pregame_sweep_interval_for_tick("nfl", now_epoch=NOW) == 7200, "observe must not act"
    assert meta["sports"]["nfl"]["phase"] == sp.PHASE_STARTING_SOON
    assert meta["sports"]["nfl"]["seconds_to_next"] == 75 * 60
    assert meta["sports"]["mlb"]["phase"] == sp.PHASE_PREGAME
    assert "SLATE_PHASE sport=nfl from=unknown to=starting_soon" in capsys.readouterr().out


def test_nfl_injury_and_news_poll_intervals(monkeypatch):
    from scripts import run_refresh_worker as worker

    monkeypatch.delenv("NFL_INJURIES_FETCH_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("NFL_NEWS_CAPTURE_INTERVAL_SECONDS", raising=False)
    monkeypatch.setattr(sp, "current_phase", lambda sport, **_: sp.SlatePhase(sport, sp.PHASE_STARTING_SOON, 4500, "t"))
    off = (worker._nfl_injuries_fetch_interval_seconds(), worker._nfl_news_capture_interval_seconds())
    monkeypatch.setenv(FLAG, "true")
    on = (worker._nfl_injuries_fetch_interval_seconds(), worker._nfl_news_capture_interval_seconds())
    assert off == (21600, 21600)
    assert on == (900, 900)


def test_tick_publishes_for_the_board_only_while_observing(monkeypatch):
    written = {}
    monkeypatch.setattr(loop, "write_json_file", lambda path, payload: written.__setitem__(str(path), payload))
    monkeypatch.setattr(loop, "_active_sports_for_date", lambda date_str: "nfl")
    monkeypatch.delenv("SYNDICATE_SLATE_PHASE_OBSERVE", raising=False)
    loop._slate_phases_for_tick(now_epoch=NOW, date_str="2026-09-27")
    assert written == {}, "flag off: nothing published"
    monkeypatch.setenv("SYNDICATE_SLATE_PHASE_OBSERVE", "true")
    loop._slate_phases_for_tick(now_epoch=NOW, date_str="2026-09-27")
    (path, payload), = written.items()
    assert path.endswith("live_refresh_loop/slate_phases.json")
    assert payload["sports"]["nfl"]["phase"] == sp.PHASE_STARTING_SOON
    assert payload["sports"]["nfl"]["next_start_epoch"] == KICKOFF


def test_board_endpoint_serves_published_phases(monkeypatch):
    from flask import Flask

    from syndicate.blueprints import intelligence as blueprint

    store = {}
    sp.publish_phases(
        {"nfl": sp.SlatePhase("nfl", sp.PHASE_STARTING_SOON, 4500.0, "t")},
        now_epoch=__import__("time").time(),
        write=lambda path, payload: store.__setitem__(str(path), payload),
    )
    monkeypatch.setattr(blueprint, "read_json_file", lambda path: store.get(str(path)))
    app = Flask(__name__)
    app.register_blueprint(blueprint.intelligence_bp)
    body = app.test_client().get("/api/intelligence/slate-phases").get_json()
    assert body["available"] is True
    assert body["sports"]["nfl"]["phase"] == "starting_soon"

    store.clear()
    body = app.test_client().get("/api/intelligence/slate-phases").get_json()
    assert body == {"available": False, "reason": "not_published", "sports": {}}


def test_soccer_relaunch_cooldown_unchanged_when_on(monkeypatch):
    """Soccer is excluded: its 1800 s cooldown must not drop to 600 s."""
    monkeypatch.setattr(loop, "_next_fixture_epoch", lambda sport, now_epoch: KICKOFF)
    monkeypatch.setattr(
        loop,
        "_read_last_pregame_launch",
        lambda: {"date": "2026-09-27", "epoch": NOW - 900, "sports": {"soccer": NOW - 900}},
    )
    monkeypatch.setenv(FLAG, "true")
    assert loop._pregame_relaunch_blocked(now_epoch=NOW, date_str="2026-09-27", sports=["soccer"]) is True
