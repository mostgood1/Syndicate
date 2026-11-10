"""An NBA game still live at midnight Central keeps its live re-sim (#776, lane nba-live-resim-midnight).

Measured 2026-11-10 on the fleet's `live_resim_history` (20 regular-season slates): 4 had regulation or overtime
play after the roll -- POR @ LAL 10-27 lost 56.7 min, MIA @ LAC 11-04 21.1 min (overtime), POR @ LAL 11-06 4.9
min, LAL @ LAC 10-28 2.6 min -- and every NBA game-line join after the 11-05 / 11-07 rolls read
games_in_snapshot=0 (0 projected) where the joins just before priced 25-76 rows.

Everything below goes through `run_live_resim_tick` with no date -- the call the loop makes -- with only ESPN, the
engine's draws and the keyvalue store faked. The engine inputs are REAL and persisted under the previous date ONLY,
so a build that read the new date's inputs would refuse `no_pregame_inputs`. The switch is read from its ENV
(off != on); the published lane goes through the board's own index builder on the carryover date, the chips'
reader, and the live evidence log's NBA cross-check, which must still agree with the tick history across the roll.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from syndicate.features.nba import live_resim as lr
from tests.basketball_engine_fixtures import synthetic_game_kwargs
from tests.basketball_pbp_fixtures import Game

PRIOR, TODAY = "2026-11-06", "2026-11-07"
PRE_ROLL = datetime(2026, 11, 7, 5, 59, 0, tzinfo=timezone.utc)      # 11:59 PM CST on 11-06
ROLL_PLUS_3 = datetime(2026, 11, 7, 6, 3, 0, tzinfo=timezone.utc)    # 12:03 AM CST on 11-07
MORNING = datetime(2026, 11, 7, 15, 0, 0, tzinfo=timezone.utc)       # 9:00 AM CST
RESULT = {"sims_run": 200, "home_win_prob": 0.6, "total_mean": 228.0, "home_margin_mean": 4.0,
          "total_dist": {"228": 200}, "margin_dist": {"4": 200}, "segments": {},
          "player_remainders": {"home": {}, "away": {}}}
NK = lr.normalize_name("De'Aaron Fox")


def _summary() -> dict:
    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1").shot(1, "10:30", "away", "a1", pts=3)
    return g.summary()


def _board(*events: tuple[str, str]) -> dict:
    return {"events": [{"id": eid, "competitions": [{"status": {"type": {"state": st}}, "competitors": []}]}
                       for eid, st in events]}


def _persist_inputs(root: Path, date: str) -> None:
    kw = synthetic_game_kwargs(np.random.default_rng(7), league="nba", entrypoint="simulate_pbp_game_boxscore")
    kw.pop("rng", None)
    lr.persist_engine_inputs(date, "GSW", "NYK", {**{k: None for k in lr._INPUT_KEYS}, **kw}, root=root)


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    """ESPN by date, the engine's draws and the keyvalue store faked; the tick, the window, the build, the carry,
    the merge and the history are real."""
    for key in (lr.PRIOR_DATE_HOURS_ENV, lr.CARRY_ENV, lr.CARRY_MAX_AGE_ENV, lr.PULLED_LINES_ENV,
                lr.LIVE_RESIM_HISTORY_ENV, lr.LIVE_MECHANISMS_ENV):
        monkeypatch.delenv(key, raising=False)
    _persist_inputs(tmp_path, PRIOR)
    state: dict = {"boards": {}, "fetched": [], "store": {}, "resimmed": [], "refuse": None, "lines": {},
                   "props_paths": [], "now": None}
    import syndicate.features.shared.refresh_state_store as store

    monkeypatch.setattr(store, "read_json_file", lambda path, *a, **k: json.loads(json.dumps(state["store"].get(str(path)))))
    monkeypatch.setattr(store, "write_json_file", lambda path, payload, *a, **k: state["store"].__setitem__(
        str(path), json.loads(json.dumps(payload, default=str))))
    monkeypatch.setattr(store, "data_root", lambda: tmp_path)
    real_resume = lr.resume_from_summary

    def resume(summary, *, date="", as_of="", league=lr.LEAGUE):
        # The state is 30 s old when the tick reads it.
        return real_resume(summary, date=date, league=league, as_of=(state["now"] - timedelta(seconds=30)).isoformat())

    def resim(inputs, gs, **_k):
        state["resimmed"].append(getattr(gs, "period", None))
        return lr.NbaResimRefusal(state["refuse"], "stub") if state["refuse"] else dict(RESULT)

    def lines(path, *_a, **_k):
        state["props_paths"].append(Path(path).name)
        return dict(state["lines"])

    monkeypatch.setattr(lr, "resume_from_summary", resume)
    monkeypatch.setattr(lr, "resim_live_game", resim)
    monkeypatch.setattr(lr, "lines_from_props_csv", lines)
    lr._PRIOR_SLATE_FINAL.clear()
    summary = _summary()

    def fetch_scoreboard(league, yyyymmdd):
        state["fetched"].append(yyyymmdd)
        return state["boards"].get(yyyymmdd, {"events": []})

    def tick(now, **kw):
        state["now"] = now
        return lr.run_live_resim_tick(now=now, fetch_scoreboard=fetch_scoreboard, fetch_summary=lambda *_a: summary,
                                      inputs_root=tmp_path, clock=lambda: 0.0, **kw)

    def published():
        return state["store"].get(str(lr.live_lens_snapshot_path()))

    state.update(tick=tick, published=published, root=tmp_path)
    yield state
    lr._PRIOR_SLATE_FINAL.clear()


def _lane(game: dict) -> dict:
    return game["gameLens"][0]


# ------------------------------------------------------------------ the switch and the window

def test_prior_date_hours_parse_safely():
    assert lr.prior_date_hours({}) == 4.0
    assert lr.prior_date_hours({lr.PRIOR_DATE_HOURS_ENV: "0"}) == 0.0
    assert lr.prior_date_hours({lr.PRIOR_DATE_HOURS_ENV: "2.5"}) == 2.5
    assert lr.prior_date_hours({lr.PRIOR_DATE_HOURS_ENV: "30"}) == 12.0
    for bad in ("-1", "inf", "nan", "soon"):
        assert lr.prior_date_hours({lr.PRIOR_DATE_HOURS_ENV: bad}) == 4.0


def test_the_window_is_hours_after_midnight_central():
    assert lr.prior_slate_date(ROLL_PLUS_3, hours=4) == PRIOR
    assert lr.prior_slate_date(datetime(2026, 11, 7, 9, 59, tzinfo=timezone.utc), hours=4) == PRIOR
    assert lr.prior_slate_date(datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc), hours=4) is None  # 4:00 AM CST
    assert lr.prior_slate_date(PRE_ROLL, hours=4) is None
    assert lr.prior_slate_date(MORNING, hours=4) is None
    assert lr.prior_slate_date(ROLL_PLUS_3, hours=0) is None
    # CDT: POR @ LAL 10-27 was in Q3 at 05:00Z; 05:57Z is 12:57 AM CDT on 10-28.
    assert lr.prior_slate_date(datetime(2026, 10, 28, 5, 57, tzinfo=timezone.utc), hours=4) == "2026-10-27"
    # DST ended 2026-11-01 02:00 CDT: 03:30 CST is 4.5 real hours past midnight CDT, so a 4 h window has closed.
    assert lr.prior_slate_date(datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc), hours=4) is None
    assert lr.prior_slate_date(datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc), hours=4) == "2026-10-31"


# ------------------------------------------------------------------ off != on, through the loop's call

def test_off_and_on_differ_through_the_env_after_the_roll(fleet, monkeypatch, capsys):
    """POR @ LAL (11-06) still in play 3 min after the roll, nothing live on 11-07. Absent env re-sims it from
    11-06's own inputs and props file into the published snapshot; "0" publishes what the fleet published at
    06:01Z on 11-07 (games=0)."""
    fleet["boards"]["20261106"] = _board(("P", "in"), ("Q", "post"))
    on = fleet["tick"](ROLL_PLUS_3)
    snap = fleet["published"]()
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert fleet["fetched"] == ["20261106", "20261107"] and len(fleet["resimmed"]) == 1
    assert (on["date"], on["games"], on["resimmed"], on["carried"]) == (TODAY, 1, 1, 0)
    assert (on["prior_date"], on["prior_games"], on["prior_resimmed"], on["prior_skip"]) == (PRIOR, 1, 1, "-")
    assert snap["date"] == TODAY and [g["event_id"] for g in snap["games"]] == ["P"]
    game = snap["games"][0]
    assert game["slateDate"] == PRIOR and _lane(game)["source"] == lr.LIVE_RESIM_LENS_SOURCE
    assert fleet["props_paths"] == [lr.props_csv_path(PRIOR, root=fleet["root"]).name]
    assert snap["priorSlate"]["date"] == PRIOR and snap["priorSlate"]["resimmed"] == 1
    assert "prior_date=2026-11-06 prior_games=1 prior_resimmed=1 prior_carried=0 prior_skip=-" in line

    monkeypatch.setenv(lr.PRIOR_DATE_HOURS_ENV, "0")
    fleet["resimmed"].clear()
    fleet["fetched"].clear()
    off = fleet["tick"](ROLL_PLUS_3)
    off_line = capsys.readouterr().out.strip().splitlines()[-1]
    assert fleet["fetched"] == ["20261107"] and fleet["resimmed"] == []
    assert (off["games"], off["resimmed"]) == (0, 0) and "prior_date" not in off
    assert fleet["published"]()["games"] == [] and "prior_" not in off_line


def test_the_new_dates_inputs_would_have_refused(fleet):
    """The reason the build must run on the PREVIOUS date: its inputs live there. Re-simming the same game under
    the new date (what an explicit-date tick does) refuses."""
    fleet["boards"]["20261107"] = _board(("P", "in"))
    fleet["now"] = ROLL_PLUS_3
    snap = lr.build_live_lens_snapshot(TODAY, fetch_scoreboard=lambda lg, d: fleet["boards"].get(d, {"events": []}),
                                       fetch_summary=lambda *_a: _summary(), inputs_root=fleet["root"],
                                       clock=lambda: 0.0, now=ROLL_PLUS_3)
    assert _lane(snap["games"][0])["liveResimRefusal"] == "no_pregame_inputs"


def test_the_published_prior_lane_keys_the_carryover_boards_join_and_chip(fleet):
    """The hop that read games_in_snapshot=0 on the fleet: the board's own index builder, on the CARRYOVER date,
    over the snapshot the tick published (date = the new day); and the chips' reader by event id."""
    from syndicate.features.shared.game_chip_intervals import _live_lane
    from syndicate.features.shared.live_gameline_join import (
        analytic_std_err_for_sport,
        build_live_gameline_index,
        lens_sources_for_sport,
    )

    fleet["boards"]["20261106"] = _board(("P", "in"))
    fleet["tick"](ROLL_PLUS_3)
    diag: dict = {}
    index = build_live_gameline_index(fleet["published"](), sources=lens_sources_for_sport("nba"),
                                      analytic_std_err=analytic_std_err_for_sport("nba"), sport="nba",
                                      slate_date=PRIOR, diagnostics=diag)
    assert diag["games_in_snapshot"] == 1 and diag["indexed"] == 1 and len(index) == 1
    assert _live_lane(fleet["published"](), "nba", {"game_key": "P"}) is not None


def test_no_prior_fetch_outside_the_window(fleet, capsys):
    fleet["boards"]["20261106"] = _board(("P", "in"))
    status = fleet["tick"](MORNING)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert fleet["fetched"] == ["20261107"] and fleet["resimmed"] == []
    assert "prior_date" not in status and "prior_" not in line


def test_an_explicit_date_never_reads_the_previous_one(fleet):
    fleet["boards"]["20261106"] = _board(("P", "in"))
    fleet["now"] = ROLL_PLUS_3
    status = lr.run_live_resim_tick(TODAY, now=ROLL_PLUS_3, inputs_root=fleet["root"], clock=lambda: 0.0,
                                    fetch_scoreboard=lambda lg, d: fleet["fetched"].append(d) or {"events": []},
                                    fetch_summary=lambda *_a: _summary())
    assert fleet["fetched"] == ["20261107"] and "prior_date" not in status


# ------------------------------------------------------------------ NBA's own state across the roll

def test_the_lane_carries_across_the_roll_and_then_expires(fleet):
    """Tick 1 after the roll reads the PRE-midnight snapshot (date 11-06); tick 2 reads the merged one (date 11-07,
    row stamped 11-06). Both must hand the previous date its own rows, so a budget refusal republishes the last
    lane within the 900 s bound -- and past it, refuses as before."""
    fleet["boards"]["20261106"] = _board(("P", "in"))
    fleet["tick"](PRE_ROLL)
    assert fleet["published"]()["date"] == PRIOR and "slateDate" not in fleet["published"]()["games"][0]

    fleet["refuse"] = "budget_exhausted"
    first = fleet["tick"](ROLL_PLUS_3)
    lane = _lane(fleet["published"]()["games"][0])
    assert (first["resimmed"], first["carried"], first["prior_carried"]) == (0, 1, 1)
    assert lane["source"] == lr.LIVE_RESIM_LENS_SOURCE and lane["carriedForward"] is True
    assert lane["carriedRefusal"] == "budget_exhausted"

    second = fleet["tick"](ROLL_PLUS_3 + timedelta(minutes=2))
    assert (second["carried"], second["prior_carried"]) == (1, 1)
    assert fleet["published"]()["games"][0]["slateDate"] == PRIOR

    expired = fleet["tick"](ROLL_PLUS_3 + timedelta(minutes=16))  # the 05:58:30Z state is now > 900 s old
    lane = _lane(fleet["published"]()["games"][0])
    assert expired["carried"] == 0 and lane["source"] == lr.PREGAME_LENS_SOURCE
    assert lane["liveResimRefusal"] == "budget_exhausted"


def test_remembered_lines_survive_the_roll(fleet):
    """A line the books posted before midnight and pulled after it is still remembered on the previous date's row."""
    fleet["boards"]["20261106"] = _board(("P", "in"))
    fleet["lines"] = {(NK, "pts"): (15.5,)}
    fleet["tick"](PRE_ROLL)
    fleet["lines"] = {}
    fleet["tick"](ROLL_PLUS_3)
    game = fleet["published"]()["games"][0]
    assert lr._posted_lines_from_payload(game["postedLines"]) == {(NK, "pts"): (15.5,)}
    assert game["livePropsCoverage"]["lines_remembered"] == 1


def test_today_never_sees_the_previous_dates_rows():
    row = {"event_id": "P", "gameLens": []}
    pre_midnight = {"date": PRIOR, "generatedAt": "x", "games": [row]}
    assert [g["event_id"] for g in lr.previous_for_slate(pre_midnight, PRIOR)["games"]] == ["P"]
    assert lr.previous_for_slate(pre_midnight, TODAY)["games"] == []
    merged = {"date": TODAY, "games": [{**row, "slateDate": PRIOR}, {"event_id": "T", "gameLens": []}]}
    assert [g["event_id"] for g in lr.previous_for_slate(merged, PRIOR)["games"]] == ["P"]
    assert [g["event_id"] for g in lr.previous_for_slate(merged, TODAY)["games"]] == ["T"]
    assert lr.previous_for_slate(pre_midnight, PRIOR)["generatedAt"] == "x"
    assert lr.previous_for_slate(None, PRIOR) is None


def test_each_dates_build_is_handed_only_its_own_rows(fleet, monkeypatch):
    """Through the tick: after a merged snapshot is published, the previous date's build gets its stamped row and
    today's build gets none of it (stalest-first, the carry and remembered lines are keyed by event id, so a row
    handed to the wrong date would feed an event on both scoreboards from the other date's build)."""
    fleet["boards"]["20261106"] = _board(("P", "in"))
    fleet["tick"](ROLL_PLUS_3)
    handed = {}
    real = lr.build_live_lens_snapshot
    monkeypatch.setattr(lr, "build_live_lens_snapshot",
                        lambda d, **kw: handed.__setitem__(d, kw.get("previous")) or real(d, **kw))
    fleet["tick"](ROLL_PLUS_3 + timedelta(minutes=2))
    assert [(g["event_id"], g["slateDate"]) for g in handed[PRIOR]["games"]] == [("P", PRIOR)]
    assert handed[PRIOR]["date"] == PRIOR and handed[TODAY]["date"] == TODAY and handed[TODAY]["games"] == []


def test_history_stays_in_the_ticks_file_and_the_evidence_crosscheck_still_agrees(fleet, capsys):
    """NBA's tick history and the live evidence log are two writers of the same ticks; `nba-crosscheck` compares
    them per date. Both file a previous date's late rows under the TICK's date, so they still agree."""
    from syndicate.features.shared import live_evidence_log as lel

    fleet["boards"]["20261106"] = _board(("P", "in"))
    status = fleet["tick"](ROLL_PLUS_3)
    assert status["history_rows"] == 1
    hist = lr.live_resim_history_path(TODAY, root=fleet["root"])
    (row,) = [json.loads(x) for x in hist.read_text(encoding="utf-8").splitlines()]
    assert (row["date"], row["slate_date"], row["event_id"]) == (TODAY, PRIOR, "P")
    assert not lr.live_resim_history_path(PRIOR, root=fleet["root"]).exists()

    collector = lel.Collector(root=fleet["root"], read=lambda _name: fleet["published"](), sports={"nba": "n.json"})
    assert collector.collect_once() == {"nba": 1}
    spec = importlib.util.spec_from_file_location(
        "live_evidence_check", Path(__file__).resolve().parents[1] / "scripts" / "live_evidence_check.py")
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    capsys.readouterr()
    assert check.nba_crosscheck(TODAY, root=fleet["root"]) == 0
    assert "history_fresh=1 log_fresh=1 matched=1 missing=0" in capsys.readouterr().out


# ------------------------------------------------------------------ cost and failure

def test_a_final_slate_is_fetched_once_then_skipped(fleet):
    fleet["boards"]["20261106"] = _board(("P", "post"), ("Q", "post"))
    first = fleet["tick"](ROLL_PLUS_3)
    second = fleet["tick"](ROLL_PLUS_3 + timedelta(minutes=2))
    assert first["prior_skip"] == second["prior_skip"] == "slate_final"
    assert fleet["fetched"].count("20261106") == 1 and fleet["resimmed"] == []


def test_a_quiet_but_unfinished_slate_skips_the_build(fleet, monkeypatch):
    fleet["boards"]["20261106"] = _board(("P", "pre"), ("Q", "post"))
    built = []
    real = lr.build_live_lens_snapshot
    monkeypatch.setattr(lr, "build_live_lens_snapshot", lambda d, **kw: built.append(d) or real(d, **kw))
    status = fleet["tick"](ROLL_PLUS_3)
    assert status["prior_skip"] == "none_in_progress" and built == [TODAY]
    fleet["tick"](ROLL_PLUS_3)
    assert fleet["fetched"].count("20261106") == 2  # not final: read again next tick


def test_today_gets_the_budget_the_previous_date_leaves(fleet, monkeypatch):
    seen = {}

    def build(date_str, **kw):
        seen[date_str] = kw.get("budget_seconds", lr.DEFAULT_BUDGET_SECONDS)
        return {"date": date_str, "games": [], "refusalsByReason": {},
                "elapsedSeconds": 100.0 if date_str == PRIOR else 1.0}

    monkeypatch.setattr(lr, "build_live_lens_snapshot", build)
    fleet["boards"]["20261106"] = _board(("P", "in"))
    status = fleet["tick"](ROLL_PLUS_3)
    assert seen == {PRIOR: lr.DEFAULT_BUDGET_SECONDS, TODAY: lr.DEFAULT_BUDGET_SECONDS - 100.0}
    assert status["prior_skip"] == "-"


def test_a_failing_previous_date_never_costs_today_its_tick(fleet, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("espn down")

    monkeypatch.setattr(lr, "prior_slate_snapshot", boom)
    _persist_inputs(fleet["root"], TODAY)
    fleet["boards"]["20261107"] = _board(("T", "in"))
    status = fleet["tick"](ROLL_PLUS_3)
    out = capsys.readouterr().out
    assert status["prior_skip"] == "error:RuntimeError" and status["resimmed"] == 1 and status["written"] is True
    assert "NBA_LIVE_RESIM_PRIOR_ERROR date=2026-11-06 RuntimeError: espn down" in out


def test_a_scoreboard_failure_is_named_and_today_still_runs(fleet):
    def fetch(league, d):
        if d == "20261106":
            raise TimeoutError("slow")
        return {"events": []}

    fleet["now"] = ROLL_PLUS_3
    status = lr.run_live_resim_tick(now=ROLL_PLUS_3, fetch_scoreboard=fetch, fetch_summary=lambda *_a: _summary(),
                                    inputs_root=fleet["root"], clock=lambda: 0.0)
    assert status["prior_skip"] == "scoreboard_fetch_failed:TimeoutError" and status["written"] is True


def test_merge_keeps_todays_row_for_an_event_on_both_dates_and_adds_the_counts():
    carried = {"source": lr.LIVE_RESIM_LENS_SOURCE, "carriedForward": True, "carriedRefusal": "budget_exhausted"}
    today = {"date": TODAY, "games": [{"event_id": "X", "gameLens": [{"source": lr.LIVE_RESIM_LENS_SOURCE}]}],
             "refusalsByReason": {}, "carriedForward": 0, "elapsedSeconds": 4.0}
    prior = {"date": PRIOR, "games": [{"event_id": "X", "gameLens": [{"source": lr.LIVE_RESIM_LENS_SOURCE}]},
                                      {"event_id": "P", "gameLens": [carried]}],
             "refusalsByReason": {"budget_exhausted": 1}, "carriedForward": 1, "elapsedSeconds": 6.0}
    out = lr.merge_prior_slate(today, prior)
    assert [(g["event_id"], g.get("slateDate")) for g in out["games"]] == [("P", PRIOR), ("X", None)]
    assert out["carriedForward"] == 1 and out["refusalsByReason"] == {"budget_exhausted": 1}
    assert out["elapsedSeconds"] == 10.0 and out["date"] == TODAY
    assert out["priorSlate"] == {"date": PRIOR, "games": 1, "resimmed": 0, "carriedForward": 1, "elapsedSeconds": 6.0,
                                 "refusalsByReason": {"budget_exhausted": 1}, "dropped_also_today": 1}


def test_the_tick_line_keeps_every_existing_field_in_place(fleet, capsys):
    fleet["boards"]["20261106"] = _board(("P", "in"))
    fleet["tick"](ROLL_PLUS_3)
    keys = [tok.split("=", 1)[0] for tok in capsys.readouterr().out.strip().splitlines()[-1].split(" ")[1:]
            if "=" in tok and not tok.startswith(("'", "{"))]
    assert keys == ["date", "games", "resimmed", "carried", "prior_date", "prior_games", "prior_resimmed",
                    "prior_carried", "prior_skip", "refusals", "bytes", "written", "elapsed_s", "history_rows"]
