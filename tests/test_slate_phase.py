"""Lane `slate-starting-soon-phase`: the per-sport pregame -> starting_soon -> live phase."""

from __future__ import annotations

from pathlib import Path

from syndicate.features.shared import slate_phase as sp

NOW = 1_790_000_000.0
ON = {"SYNDICATE_SLATE_STARTING_SOON_ENABLED": "true"}
OFF: dict[str, str] = {}


def _phase(seconds_out, *, is_live=False, env=OFF, sport="nfl"):
    nxt = None if seconds_out is None else NOW + seconds_out
    return sp.classify(sport, now_epoch=NOW, next_fixture_epoch=nxt, is_live=is_live, env=env)


def test_boundaries_default_three_hours():
    assert _phase(75 * 60).phase == sp.PHASE_STARTING_SOON  # the reported NFL case
    assert _phase(3 * 3600).phase == sp.PHASE_STARTING_SOON
    assert _phase(3 * 3600 + 1).phase == sp.PHASE_PREGAME
    assert _phase(None).phase == sp.PHASE_PREGAME
    assert _phase(10, is_live=True).phase == sp.PHASE_LIVE


def test_kickoff_grace_keeps_starting_soon_until_checker_flips():
    assert _phase(-120).phase == sp.PHASE_STARTING_SOON
    assert _phase(-120).reason == "start_passed_not_yet_live"
    assert _phase(-(sp.KICKOFF_GRACE_SECONDS + 1)).phase == sp.PHASE_PREGAME


def test_unknown_liveness_is_not_live():
    assert _phase(600, is_live=None).phase == sp.PHASE_STARTING_SOON


def test_per_sport_window_override():
    env = {"SYNDICATE_SLATE_STARTING_SOON_WINDOW_SECONDS_NHL": "7200"}
    assert _phase(9000, sport="nhl", env=env).phase == sp.PHASE_PREGAME
    assert _phase(9000, sport="nfl", env=env).phase == sp.PHASE_STARTING_SOON


def test_interval_off_is_untouched_on_shortens():
    """Reachability: the same reading, flag off vs on, must differ."""
    phase = _phase(75 * 60)
    off = sp.apply_starting_soon_interval("nfl", 7200, phase, env=OFF)
    on = sp.apply_starting_soon_interval("nfl", 7200, phase, env=ON)
    assert off == (7200, None)
    assert on[0] == sp.DEFAULT_STARTING_SOON_SWEEP_INTERVAL_SECONDS
    assert on[1].startswith("starting_soon:")
    assert off != on


def test_interval_never_lengthens():
    phase = _phase(75 * 60)
    assert sp.apply_starting_soon_interval("nfl", 0, phase, env=ON) == (0, None)
    assert sp.apply_starting_soon_interval("nfl", 600, phase, env=ON) == (600, None)
    pregame = _phase(8 * 3600)
    assert sp.apply_starting_soon_interval("nfl", 7200, pregame, env=ON) == (7200, None)


def test_poll_interval_off_vs_on():
    phase = _phase(75 * 60)
    assert sp.starting_soon_poll_interval("nfl", 21600, env_key="X", phase=phase, env=OFF) == 21600
    assert sp.starting_soon_poll_interval("nfl", 21600, env_key="X", phase=phase, env=ON) == 900
    assert sp.starting_soon_poll_interval("nfl", 21600, env_key="X", phase=phase, env={**ON, "X": "300"}) == 300
    assert sp.starting_soon_poll_interval("nfl", 21600, env_key="X", phase=_phase(8 * 3600), env=ON) == 21600


def test_current_phase_uses_injected_readers_and_caches_liveness():
    calls = []

    def checker(date_str):
        calls.append(date_str)
        return False

    sp._LIVE_CACHE.clear()
    kwargs = dict(
        now_epoch=NOW,
        date_str="2026-09-27",
        next_fixture=lambda sport, now_epoch: now_epoch + 4500,
        live_checkers={"nfl": checker},
        env=ON,
    )
    first = sp.current_phase("nfl", **kwargs)
    second = sp.current_phase("nfl", **kwargs)
    assert first.phase == second.phase == sp.PHASE_STARTING_SOON
    assert len(calls) == 1, "the ESPN checker is a subprocess; it must be cached"
    assert sp.is_starting_soon("nfl", **kwargs) is True
    assert sp.is_starting_soon("nfl", **{**kwargs, "env": OFF}) is False


def test_current_phase_never_raises():
    def boom(sport, now_epoch):
        raise RuntimeError("schedule down")

    result = sp.current_phase("nfl", now_epoch=NOW, date_str="d", next_fixture=boom, live_checkers={})
    assert result.phase == sp.PHASE_PREGAME
    assert result.reason == "unresolved:RuntimeError"


def test_transitions_print_once_per_change(capsys):
    sp._LAST_PRINTED.clear()
    phases = {"nfl": _phase(4000)}
    assert len(sp.print_transitions(phases)) == 1
    assert sp.print_transitions(phases) == []
    assert len(sp.print_transitions({"nfl": _phase(10, is_live=True)})) == 1
    out = capsys.readouterr().out
    assert "SLATE_PHASE sport=nfl from=unknown to=starting_soon" in out
    assert "from=starting_soon to=live" in out


def test_t_window_min_gap():
    assert sp.t_window_force_allowed(None, now_epoch=NOW, env=OFF)
    assert not sp.t_window_force_allowed(NOW - 60, now_epoch=NOW, env=OFF)
    assert sp.t_window_force_allowed(NOW - 301, now_epoch=NOW, env=OFF)
    assert sp.t_window_force_allowed(NOW - 60, now_epoch=NOW, env={"SYNDICATE_T_WINDOW_MIN_GAP_SECONDS": "0"})


def test_schedule_commence_times_from_adapter():
    from syndicate.features.shared.schedule_adapter import ScheduleEvent

    events = [
        ScheduleEvent("nfl", "b", "H", "A", "2026-09-27T20:25:00Z"),
        ScheduleEvent("nfl", "a", "H", "A", "2026-09-27T17:00:00Z"),
        ScheduleEvent("nfl", "c", "H", "A", None),
    ]
    times = sp.schedule_commence_times("nfl", "2026-09-27", fetch=lambda s, d: events)
    assert [event_id for event_id, _ in times] == ["a", "b"]
    assert sp.schedule_commence_times("nfl", "d", fetch=lambda s, d: 1 / 0) == []


def test_injury_file_changed(tmp_path: Path):
    store: dict[Path, object] = {}
    injuries = tmp_path / "injuries_2026.csv"
    state = tmp_path / "state.json"
    kwargs = dict(read_state=store.get, write_state=store.__setitem__, state_path=state)

    injuries.write_text("player,status\nA,Questionable\n")
    assert sp.injury_file_changed("nfl", injuries, date_str="2026-09-27", **kwargs) is False  # baseline
    assert sp.injury_file_changed("nfl", injuries, date_str="2026-09-27", **kwargs) is False
    injuries.write_text("player,status\nA,Out\n")
    assert sp.injury_file_changed("nfl", injuries, date_str="2026-09-27", **kwargs) is True
    injuries.write_text("player,status\nA,Out\nB,Out\n")
    assert sp.injury_file_changed("nfl", injuries, date_str="2026-09-28", **kwargs) is False  # rollover
    assert sp.injury_file_changed("nfl", tmp_path / "missing.csv", date_str="2026-09-28", **kwargs) is False


def test_need_live_false_skips_the_checker_outside_the_window():
    calls = []

    def checker(date_str):
        calls.append(date_str)
        return True

    sp._LIVE_CACHE.clear()
    far = sp.current_phase(
        "nhl", now_epoch=NOW, date_str="d", next_fixture=lambda s, now_epoch: None,
        live_checkers={"nhl": checker}, need_live=False,
    )
    assert far.phase == sp.PHASE_PREGAME and calls == []
    near = sp.current_phase(
        "nhl", now_epoch=NOW, date_str="d", next_fixture=lambda s, now_epoch: now_epoch + 600,
        live_checkers={"nhl": checker}, need_live=False,
    )
    assert near.phase == sp.PHASE_LIVE and calls == ["d"]


# --- publishing to the web board ---------------------------------------------


def test_publish_then_read_round_trip():
    store = {}
    phases = {
        "nfl": sp.SlatePhase("nfl", sp.PHASE_STARTING_SOON, 4500.0, "within_10800s"),
        "mlb": sp.SlatePhase("mlb", sp.PHASE_LIVE, None, "game_in_progress"),
    }
    sp.publish_phases(phases, now_epoch=NOW, write=store.__setitem__, path="p", env={"RENDER_SERVICE_NAME": "refresh-worker"})
    out = sp.read_published_phases(read=store.get, now_epoch=NOW + 60, path="p")
    assert out["available"] is True and out["service"] == "refresh-worker"
    assert out["sports"]["nfl"] == {"phase": "starting_soon", "next_start_epoch": NOW + 4500.0}
    assert out["sports"]["mlb"] == {"phase": "live", "next_start_epoch": None}


def test_read_refuses_stale_missing_and_garbage():
    store = {"p": {"written_at_epoch": NOW, "sports": {"nfl": {"phase": "starting_soon"}, "x": {"phase": "bogus"}}}}
    stale = sp.read_published_phases(read=store.get, now_epoch=NOW + sp.PUBLISHED_MAX_AGE_SECONDS + 1, path="p")
    assert stale["available"] is False and stale["reason"] == "stale" and stale["sports"] == {}
    assert sp.read_published_phases(read=lambda p: None, now_epoch=NOW)["reason"] == "not_published"
    assert sp.read_published_phases(read=lambda p: 1 / 0, now_epoch=NOW)["sports"] == {}
    fresh = sp.read_published_phases(read=store.get, now_epoch=NOW + 5, path="p")
    assert set(fresh["sports"]) == {"nfl"}, "an unknown phase value must not reach the board"


def test_soccer_never_starts_soon_but_can_be_live():
    """User decision 2026-09-27: soccer is excluded from starting_soon."""
    soon = _phase(40 * 60, sport="soccer")
    assert soon.phase == sp.PHASE_PREGAME and soon.reason == "starting_soon_excluded"
    assert _phase(-120, sport="soccer").phase == sp.PHASE_PREGAME, "no kickoff grace either"
    assert _phase(10, is_live=True, sport="soccer").phase == sp.PHASE_LIVE
    assert sp.apply_starting_soon_interval("soccer", 7200, soon, env=ON) == (7200, None)


def test_soccer_cadence_questions_never_run_the_checker():
    calls = []
    sp._LIVE_CACHE.clear()
    phase = sp.current_phase(
        "soccer", now_epoch=NOW, date_str="d", next_fixture=lambda s, now_epoch: now_epoch + 600,
        live_checkers={"soccer": lambda d: calls.append(d) or False}, need_live=False, env=ON,
    )
    assert phase.phase == sp.PHASE_PREGAME and calls == []
    assert sp.is_starting_soon("soccer", now_epoch=NOW, date_str="d", next_fixture=lambda s, now_epoch: now_epoch + 600,
                               live_checkers={}, env=ON) is False
