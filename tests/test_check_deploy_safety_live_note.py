"""`check_deploy_safety`'s live-game note names what it covers (lane `deploy-safety-live-note-sports`).

`latest_tick.anyLive` covers only the live-refresh loop's `_LIVE_STATUS_CHECKERS`; NCAAB and WNCAAB have
no checker. Measured 2026-11-09 04:41:07Z: "No live games" printed while the NCAAB re-sim ticked
`live=2 resimmed=2`. The note now reads the college re-sim snapshots too, and UNKNOWN never reads as none.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_deploy_safety.py"
spec = importlib.util.spec_from_file_location("check_deploy_safety_live_note_under_test", MODULE_PATH)
cds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cds)

STATE_PATH = "/api/ops/live-refresh/state"
SNAPSHOT_PATH = "/api/ops/live-lens/snapshot-index?sport="


def _stamp(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _tick(any_live=False, minutes_ago=2.0, **extra):
    return {"anyLive": any_live, "adaptive": any_live is not None, "sports": "active",
            "finishedAt": _stamp(minutes_ago), "result": {"state": "idle"}, **extra}


def _snapshot(games: int, minutes_ago: float = 1.0) -> dict:
    return {"ok": True, "snapshot_present": True, "snapshot_date": "2026-11-09",
            "snapshot_generated_at": _stamp(minutes_ago), "snapshot_game_count": games}


def _run_main(capsys, tick, snapshots, *argv):
    """main() on the fleet with every reader faked; `snapshots[sport]` is a payload or an exception."""
    state = {"state": {"sim_run_status": {"state": "finished", "exit_code": 0}, "latest_tick": tick}}

    def fake_get_json(base_url, path, token, timeout=90):
        if path == STATE_PATH:
            return state
        assert path.startswith(SNAPSHOT_PATH), path
        found = snapshots[path[len(SNAPSHOT_PATH):]]
        if isinstance(found, Exception):
            raise found
        return found

    none = ([], {"applicable": True, "worker_pid": 200})
    with mock.patch.object(cds, "_load_admin_token", return_value="t"), \
         mock.patch.object(cds, "_get_json", side_effect=fake_get_json), \
         mock.patch.object(cds, "board_build_state", return_value=(False, {"newest_build_complete": "x"})), \
         mock.patch.object(cds, "fleet_worker_children",
                           return_value={"refresh-worker": none, "live-odds-worker": none}), \
         mock.patch("sys.argv", ["check_deploy_safety.py", "--base-url", "http://127.0.0.1:10000", *argv]):
        rc = cds.main()
    return rc, capsys.readouterr().out


# --- the incident: anyLive false, NCAAB live --------------------------------


def test_ncaab_live_while_anylive_is_false_is_named_and_warned(capsys):
    rc, out = _run_main(capsys, _tick(any_live=False), {"ncaab": _snapshot(2), "wncaab": _snapshot(0)})
    assert "WARNING: Live games in progress (ncaab: 2 live D1-vs-D1)" in out
    assert "live re-sims" in out
    assert "No live games" not in out
    # What each source said, so the reader can see the loop and the re-sims disagree for a reason.
    assert "live-refresh loop [mlb,wnba,nba,nhl,soccer,nfl,ncaaf]: none (2m ago)" in out
    assert "ncaab re-sim (D1 vs D1): 2 live (1m ago)" in out and "wncaab re-sim (D1 vs D1): 0 live (1m ago)" in out
    # Still a note, never a blocker.
    assert rc == 0 and "CLEAR: nothing in flight" in out
    assert "(Live games are in progress -- see the warning above.)" in out


def test_allow_live_games_marks_it_allowed_and_never_blocks(capsys):
    rc, out = _run_main(capsys, _tick(any_live=False), {"ncaab": _snapshot(0), "wncaab": _snapshot(3)},
                        "--allow-live-games")
    assert rc == 0
    assert "Live games in progress (wncaab: 3 live D1-vs-D1)" in out and "(allowed)" in out
    assert "WARNING: Live games" not in out and "see the warning above" not in out


def test_all_sources_read_none_says_no_live_games_and_names_them(capsys):
    rc, out = _run_main(capsys, _tick(any_live=False), {"ncaab": _snapshot(0), "wncaab": _snapshot(0)})
    assert rc == 0
    assert "No live games on any source below" in out
    assert ("Live-game sources: live-refresh loop [mlb,wnba,nba,nhl,soccer,nfl,ncaaf]: none (2m ago); "
            "ncaab re-sim (D1 vs D1): 0 live (1m ago); wncaab re-sim (D1 vs D1): 0 live (1m ago)") in out


def test_loop_live_names_the_sport_from_slate_phases(capsys):
    phases = {"observing": True, "sports": {"nhl": {"phase": "live"}, "nba": {"phase": "pregame"},
                                            "ncaab": {"phase": "live"}}}
    rc, out = _run_main(capsys, _tick(any_live=True, slatePhases=phases),
                        {"ncaab": _snapshot(0), "wncaab": _snapshot(0)})
    assert rc == 0
    # ncaab is not one of the loop's sports, so the loop cannot vouch for it.
    assert "WARNING: Live games in progress (nhl)" in out
    assert "live-refresh loop [mlb,wnba,nba,nhl,soccer,nfl,ncaaf]: LIVE (nhl) (2m ago)" in out


def test_loop_live_without_slate_phases_says_the_sport_is_not_named(capsys):
    _rc, out = _run_main(capsys, _tick(any_live=True), {"ncaab": _snapshot(0), "wncaab": _snapshot(0)})
    assert "WARNING: Live games in progress (one of mlb,wnba,nba,nhl,soccer,nfl,ncaaf)" in out
    assert "LIVE, sport not named (2m ago)" in out


# --- UNKNOWN is not none ----------------------------------------------------


def test_stale_ncaab_snapshot_is_unknown_not_none(capsys):
    rc, out = _run_main(capsys, _tick(any_live=False), {"ncaab": _snapshot(0, minutes_ago=47), "wncaab": _snapshot(0)})
    assert rc == 0
    assert "No live games" not in out
    assert "Live games UNKNOWN for ncaab -- not the same as none; none on the sources that answered" in out
    assert "ncaab re-sim (D1 vs D1): UNKNOWN (snapshot 47m old > 10m: producer off or stalled, said 0 live)" in out
    assert "(Live games could not be ruled out for ncaab -- see the note above.)" in out


def test_unreadable_or_absent_snapshot_is_unknown(capsys):
    absent = {"ok": True, "snapshot_present": False, "reason": "no_snapshot_at_path"}
    _rc, out = _run_main(capsys, _tick(any_live=False), {"ncaab": TimeoutError("slow"), "wncaab": absent})
    assert "Live games UNKNOWN for ncaab, wncaab" in out and "No live games" not in out
    assert "ncaab re-sim (D1 vs D1): UNKNOWN (snapshot unreadable: TimeoutError)" in out
    assert "wncaab re-sim (D1 vs D1): UNKNOWN (no snapshot (no_snapshot_at_path))" in out


def test_anylive_null_is_unknown_for_the_loops_sports(capsys):
    _rc, out = _run_main(capsys, _tick(any_live=None), {"ncaab": _snapshot(0), "wncaab": _snapshot(0)})
    assert "No live games" not in out
    assert "Live games UNKNOWN for mlb, wnba, nba, nhl, soccer, nfl, ncaaf" in out
    assert "live-refresh loop [mlb,wnba,nba,nhl,soccer,nfl,ncaaf]: UNKNOWN (anyLive=null" in out


def test_stale_tick_is_unknown_even_when_it_said_none(capsys):
    _rc, out = _run_main(capsys, _tick(any_live=False, minutes_ago=95), {"ncaab": _snapshot(0), "wncaab": _snapshot(0)})
    assert "No live games" not in out
    assert "UNKNOWN (tick 95m old > 30m, said anyLive=False)" in out


def test_every_source_unknown_does_not_claim_the_others_read_none(capsys):
    _rc, out = _run_main(capsys, {}, {"ncaab": TimeoutError(), "wncaab": TimeoutError()})
    assert "Live games UNKNOWN for mlb, wnba, nba, nhl, soccer, nfl, ncaaf, ncaab, wncaab -- not the same as none\n" in out
    assert "none on the sources that answered" not in out


def test_a_live_reading_wins_over_an_unknown_one(capsys):
    _rc, out = _run_main(capsys, _tick(any_live=None), {"ncaab": _snapshot(4), "wncaab": _snapshot(0)})
    assert "WARNING: Live games in progress (ncaab: 4 live D1-vs-D1)" in out
    assert "could not be ruled out" not in out


# --- what the loop covers ---------------------------------------------------


def test_configured_sports_narrow_the_loops_coverage_to_its_checkers():
    # SYNDICATE_LIVE_ODDS_REFRESH_SPORTS lists sports; `_any_tracked_sport_game_live` skips any without a checker.
    assert cds.loop_live_sports({"sports": "mlb,ncaab,NHL"}) == ["mlb", "nhl"]
    assert cds.loop_live_sports({"sports": "active"}) == list(cds.LIVE_REFRESH_LOOP_SPORTS)
    assert cds.loop_live_sports({}) == list(cds.LIVE_REFRESH_LOOP_SPORTS)


def test_bool_game_count_is_not_a_count():
    payload = {**_snapshot(0), "snapshot_game_count": True}
    with mock.patch.object(cds, "_get_json", return_value=payload):
        reading = cds.resim_snapshot_reading("http://x", "t", "ncaab")
    assert reading["unknown"] == "snapshot has no game count"


# --- drift: the copies against what they copy -------------------------------


def test_loop_sports_match_the_loops_liveness_checkers():
    from syndicate.features.shared import live_refresh_loop

    assert set(cds.LIVE_REFRESH_LOOP_SPORTS) == set(live_refresh_loop._LIVE_STATUS_CHECKERS)


def test_every_live_priced_board_sport_is_covered_by_the_loop_or_a_resim_snapshot():
    from syndicate.features.shared import board_enrichment as be
    from syndicate.features.shared import live_refresh_loop

    covered = set(cds.LIVE_REFRESH_LOOP_SPORTS) | set(cds.RESIM_SNAPSHOT_SPORTS)
    board = set(be._LIVE_GAMELINE_SPORTS) | set(be.ENV_GATED_LIVE_SPORTS)
    assert board - covered == set(), "a live sport the deploy-safety note cannot see -- add its reading"
    # The re-sim list is for sports the loop is blind to; the snapshot-index endpoint must read the re-sim's file.
    assert not set(cds.RESIM_SNAPSHOT_SPORTS) & set(live_refresh_loop._LIVE_STATUS_CHECKERS)
    for sport in cds.RESIM_SNAPSHOT_SPORTS:
        assert be._LIVE_GAMELINE_SNAPSHOT_PATHS[sport] == f"{sport}_live_resim.json"


def test_college_snapshot_rows_are_its_live_count(monkeypatch):
    """The note reads `snapshot_game_count` as live games: every live event gets a row, reached or not."""
    from syndicate.features.ncaab import live_resim as lr

    monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_LANE_AGE_GATE", "off")
    monkeypatch.setenv("SYNDICATE_COLLEGE_LIVE_MARGIN_ANCHOR", "0")
    events = [{"event_id": str(i), "status_state": "in"} for i in range(4)]
    events.append({"event_id": "9", "status_state": "post"})
    monkeypatch.setattr("syndicate.features.shared.request_path_guard.refuse_if_compute_in_request_path", lambda *_: None)
    monkeypatch.setattr("syndicate.features.shared.basketball_pbp.scoreboard_events", lambda sb: events)
    monkeypatch.setattr(lr, "load_player_priors", lambda *a, **k: lr.NcaabResimRefusal("no_player_priors"))
    monkeypatch.setattr(lr, "odds_team_names", lambda *a, **k: {})
    facts = lr.ResumeFacts("x", "10", "20", 40, 38, 2, 600.0, "home", 300, "t")
    monkeypatch.setattr(lr, "resume_from_summary", lambda s, **k: (None, None, facts))
    monkeypatch.setattr(lr, "build_engine_inputs", lambda *a, **k: {"home_players": None, "away_players": None})
    monkeypatch.setattr("syndicate.features.nba.live_resim.map_state_names", lambda gs, h, a: (gs, {}))
    now = {"t": 0.0}

    def resim(inputs, gs, **kw):
        now["t"] += 10.0
        return {"sims_run": 100, "home_win_prob": 0.6, "total_mean": 140.0, "home_margin_mean": 3.0,
                "total_dist": {}, "margin_dist": {}, "segments": {}}

    monkeypatch.setattr(lr, "resim_live_game", resim)
    lr._ROTATION_CURSOR.clear()
    snap = lr.build_live_lens_snapshot("2026-01-10", previous={}, fetch_scoreboard=lambda *a: {},
                                       fetch_summary=lambda *a: {"header": {}}, budget_seconds=25,
                                       clock=lambda: now["t"])
    # The budget ran out on one game: it is still a row, and the final game is not.
    assert snap["counts"]["not_reached"] == 1
    assert len(snap["games"]) == snap["counts"]["live"] == 4
