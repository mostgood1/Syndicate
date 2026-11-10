"""A college game still live at midnight Central keeps its live re-sim (#774, lane college-live-resim-midnight).

Measured 2026-11-10: after 00:00 CT the tick read only the new date, so PORT @ HAW (11-09) went 78.5 min and
WICH vs USC (11-08) 30.4 min with no re-sim, and every NCAAB join on the carryover board read games_in_snapshot=0.

Everything below goes through `run_live_resim_tick` with no date -- the call the loop makes -- with only the
engine, ESPN and the store faked. The switch is read from its ENV (off != on), and the published lane is fed to
the board's own index builder with the carryover date, which is the hop that read 0 on the fleet.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import pytest

from syndicate.features.ncaab import live_resim as lr

ROLL_PLUS_30 = datetime(2026, 11, 10, 6, 30, 0, tzinfo=timezone.utc)  # 12:30 AM CST on 11-10
MORNING = datetime(2026, 11, 10, 15, 0, 0, tzinfo=timezone.utc)  # 9:00 AM CST
RESULT = {"sims_run": 200, "home_win_prob": 0.6, "total_mean": 140.0, "home_margin_mean": 3.0,
          "total_dist": {"140": 200}, "margin_dist": {"3": 200}, "segments": {}}
NAMES = {"P": ("Portland Pilots", "Hawai'i Rainbow Warriors"), "T": ("Duke Blue Devils", "Kansas Jayhawks")}


def _summary(eid: str) -> dict:
    away, home = NAMES.get(eid, (f"Away {eid}", f"Home {eid}"))
    comps = [{"homeAway": "home", "team": {"id": f"h{eid}", "displayName": home}},
             {"homeAway": "away", "team": {"id": f"a{eid}", "displayName": away}}]
    return {"header": {"competitions": [{"competitors": comps}]}, "eid": eid}


@pytest.fixture
def fleet(monkeypatch):
    """ESPN by date, the engine and the keyvalue store faked; the tick, the window and the merge are real."""
    monkeypatch.setenv("SYNDICATE_COLLEGE_LIVE_MARGIN_ANCHOR", "0")
    for key in (lr.PRIOR_DATE_HOURS_ENV, lr.CARRY_BOUND_ENV, lr.CARRY_MAX_AGE_ENV, lr.WORKERS_ENV):
        monkeypatch.delenv(key, raising=False)
    state: dict = {"boards": {}, "fetched": [], "store": {}, "resimmed": []}
    monkeypatch.setattr("syndicate.features.shared.request_path_guard.refuse_if_compute_in_request_path", lambda *_: None)
    monkeypatch.setattr("syndicate.features.shared.basketball_pbp.scoreboard_events", lambda sb: list(sb.get("events") or []))
    monkeypatch.setattr(lr, "load_player_priors", lambda *a, **k: lr.NcaabResimRefusal("no_player_priors"))
    monkeypatch.setattr(lr, "odds_team_names", lambda *a, **k: {})

    def resume(summary, **k):
        eid = summary["eid"]
        return (None, {"gs": eid}, lr.ResumeFacts(eid, f"h{eid}", f"a{eid}", 40, 38, 2, 600.0, "home", 300,
                                                  datetime.now(timezone.utc).isoformat()))

    monkeypatch.setattr(lr, "resume_from_summary", resume)
    monkeypatch.setattr(lr, "build_engine_inputs", lambda *a, **k: {k2: k2 for k2 in lr._ENGINE_KWARGS}
                        | {"home_players": "H", "away_players": "A"})
    monkeypatch.setattr("syndicate.features.nba.live_resim.map_state_names", lambda gs, h, a: (gs, {}))

    def resim(inputs, gs, **kw):
        state["resimmed"].append(gs["gs"])
        return dict(RESULT)

    monkeypatch.setattr(lr, "resim_live_game", resim)
    monkeypatch.setattr("syndicate.features.shared.refresh_state_store.read_json_file",
                        lambda path, *a, **k: json.loads(json.dumps(state["store"].get(str(path)))))
    monkeypatch.setattr("syndicate.features.shared.refresh_state_store.write_json_file",
                        lambda path, payload, *a, **k: state["store"].__setitem__(str(path), payload))
    lr._ROTATION_CURSOR.clear()
    lr._PRIOR_SLATE_FINAL.clear()

    def fetch_scoreboard(league, yyyymmdd):
        state["fetched"].append((league, yyyymmdd))
        return {"events": state["boards"].get((league, yyyymmdd), [])}

    def tick(now, league="ncaab", **kw):
        return lr.run_live_resim_tick(league=league, now=now, d1_ids=frozenset(), workers=0,
                                      fetch_scoreboard=fetch_scoreboard,
                                      fetch_summary=lambda lg, eid: _summary(eid), **kw)

    def published(league="ncaab"):
        return state["store"].get(str(lr.live_lens_snapshot_path(league)))

    state["tick"], state["published"] = tick, published
    yield state
    lr._PRIOR_SLATE_FINAL.clear()


def _in(eid: str, state: str = "in", home_id: str = "", away_id: str = "") -> dict:
    return {"event_id": eid, "state": state, "home_id": home_id, "away_id": away_id}


# ------------------------------------------------------------------ the switch and the window

def test_prior_date_hours_parse_safely():
    assert lr.prior_date_hours({}) == 4.0
    assert lr.prior_date_hours({lr.PRIOR_DATE_HOURS_ENV: "0"}) == 0.0
    assert lr.prior_date_hours({lr.PRIOR_DATE_HOURS_ENV: "2.5"}) == 2.5
    assert lr.prior_date_hours({lr.PRIOR_DATE_HOURS_ENV: "30"}) == 12.0
    for bad in ("-1", "inf", "nan", "soon"):
        assert lr.prior_date_hours({lr.PRIOR_DATE_HOURS_ENV: bad}) == 4.0


def test_the_window_is_hours_after_midnight_central():
    assert lr.prior_slate_date(ROLL_PLUS_30, hours=4) == "2026-11-09"
    assert lr.prior_slate_date(datetime(2026, 11, 10, 9, 59, tzinfo=timezone.utc), hours=4) == "2026-11-09"
    assert lr.prior_slate_date(datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc), hours=4) is None  # 4:00 AM CST
    assert lr.prior_slate_date(datetime(2026, 11, 10, 5, 59, tzinfo=timezone.utc), hours=4) is None  # 11:59 PM CST
    assert lr.prior_slate_date(MORNING, hours=4) is None
    assert lr.prior_slate_date(ROLL_PLUS_30, hours=0) is None
    # DST ended 2026-11-01 02:00 CDT: 03:30 CST is 4.5 real hours past midnight CDT, so a 4 h window has closed.
    assert lr.prior_slate_date(datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc), hours=4) is None
    assert lr.prior_slate_date(datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc), hours=4) == "2026-10-31"


# ------------------------------------------------------------------ off != on, through the loop's call

def test_off_and_on_differ_through_the_env_after_the_roll(fleet, monkeypatch, capsys):
    """PORT @ HAW at halftime 30 min after the roll, nothing live on the new date: absent env re-sims it into the
    published snapshot; "0" publishes what the fleet published on 11-10 (live=0, no game)."""
    fleet["boards"][("ncaab", "20261109")] = [_in("P"), _in("Q", "post")]
    on = fleet["tick"](ROLL_PLUS_30)
    on_snap = fleet["published"]()
    on_line = capsys.readouterr().out.strip().splitlines()[-1]
    assert fleet["resimmed"] == ["P"]
    assert (on["date"], on["live"], on["resimmed"]) == ("2026-11-10", 1, 1)
    assert (on["prior_date"], on["prior_live"], on["prior_resimmed"], on["prior_skip"]) == ("2026-11-09", 1, 1, "-")
    assert [g["event_id"] for g in on_snap["games"]] == ["P"]
    assert on_snap["date"] == "2026-11-10" and on_snap["games"][0]["slateDate"] == "2026-11-09"
    assert on_snap["games"][0]["gameLens"][0]["source"] == lr.LIVE_RESIM_LENS_SOURCE
    assert on_snap["priorSlate"]["date"] == "2026-11-09" and on_snap["priorSlate"]["counts"]["resimmed"] == 1
    assert "prior_date=2026-11-09 prior_live=1 prior_resimmed=1" in on_line

    monkeypatch.setenv(lr.PRIOR_DATE_HOURS_ENV, "0")
    fleet["resimmed"].clear()
    fleet["fetched"].clear()
    off = fleet["tick"](ROLL_PLUS_30)
    off_line = capsys.readouterr().out.strip().splitlines()[-1]
    assert fleet["resimmed"] == [] and fleet["fetched"] == [("ncaab", "20261110")]
    assert (off["live"], off["resimmed"]) == (0, 0) and "prior_date" not in off
    assert fleet["published"]()["games"] == [] and "prior_date" not in off_line


def test_the_published_prior_lane_keys_the_carryover_boards_join(fleet):
    """The hop that read games_in_snapshot=0 on the fleet: the board's own index builder, on the CARRYOVER date,
    over the snapshot the tick published (date = the new day)."""
    from syndicate.features.shared.live_gameline_join import (
        analytic_std_err_for_sport,
        build_live_gameline_index,
        lens_sources_for_sport,
    )

    fleet["boards"][("ncaab", "20261109")] = [_in("P")]
    fleet["tick"](ROLL_PLUS_30)
    diag: dict = {}
    index = build_live_gameline_index(fleet["published"](), sources=lens_sources_for_sport("ncaab"),
                                      analytic_std_err=analytic_std_err_for_sport("ncaab"), sport="ncaab",
                                      slate_date="2026-11-09", diagnostics=diag)
    assert diag["games_in_snapshot"] == 1 and diag["indexed"] == 1
    assert len(index) == 1


def test_no_prior_fetch_outside_the_window(fleet, capsys):
    fleet["boards"][("ncaab", "20261109")] = [_in("P")]
    status = fleet["tick"](MORNING)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert fleet["fetched"] == [("ncaab", "20261110")] and fleet["resimmed"] == []
    assert "prior_date" not in status and "prior_" not in line
    assert line.split(" ")[-1].startswith("elapsed_s=")


def test_an_explicit_date_never_reads_the_previous_one(fleet):
    fleet["boards"][("ncaab", "20261109")] = [_in("P")]
    status = lr.run_live_resim_tick("2026-11-10", now=ROLL_PLUS_30, d1_ids=frozenset(), workers=0,
                                    fetch_scoreboard=lambda lg, d: fleet["fetched"].append(d) or {"events": []},
                                    fetch_summary=lambda lg, eid: _summary(eid))
    assert fleet["fetched"] == ["20261110"] and "prior_date" not in status


def test_the_womens_loop_takes_the_same_path(fleet):
    fleet["boards"][("wncaab", "20261109")] = [_in("P")]
    status = fleet["tick"](ROLL_PLUS_30, league="wncaab")
    assert (status["prior_live"], status["prior_resimmed"]) == (1, 1)
    assert fleet["published"]("wncaab")["games"][0]["slateDate"] == "2026-11-09"


# ------------------------------------------------------------------ cost and carry

def test_a_final_slate_is_fetched_once_then_skipped(fleet):
    fleet["boards"][("ncaab", "20261109")] = [_in("P", "post"), _in("Q", "post")]
    first = fleet["tick"](ROLL_PLUS_30)
    second = fleet["tick"](ROLL_PLUS_30)
    assert first["prior_skip"] == second["prior_skip"] == "slate_final"
    assert fleet["fetched"].count(("ncaab", "20261109")) == 1


def test_a_quiet_but_unfinished_slate_skips_the_build(fleet, monkeypatch):
    fleet["boards"][("ncaab", "20261109")] = [_in("P", "pre"), _in("Q", "post")]
    built = []
    real = lr.build_live_lens_snapshot
    monkeypatch.setattr(lr, "build_live_lens_snapshot", lambda d, **kw: built.append(d) or real(d, **kw))
    status = fleet["tick"](ROLL_PLUS_30)
    assert status["prior_skip"] == "none_in_progress" and built == ["2026-11-10"]
    fleet["tick"](ROLL_PLUS_30)
    assert fleet["fetched"].count(("ncaab", "20261109")) == 2  # not final: read again next tick


def test_a_non_board_game_in_progress_builds_nothing(fleet):
    fleet["boards"][("ncaab", "20261109")] = [_in("B", home_id="62", away_id="9999")]
    status = lr.run_live_resim_tick(now=ROLL_PLUS_30, d1_ids=frozenset({"62", "2"}), workers=0,
                                    fetch_scoreboard=lambda lg, d: {"events": fleet["boards"].get((lg, d), [])},
                                    fetch_summary=lambda lg, eid: _summary(eid))
    assert status["prior_skip"] == "none_in_progress" and fleet["resimmed"] == []


def test_today_gets_the_budget_the_previous_date_leaves(fleet, monkeypatch):
    seen = {}

    def build(date_str, **kw):
        seen[date_str] = kw.get("budget_seconds", lr.DEFAULT_BUDGET_SECONDS)
        return {"date": date_str, "counts": {"live": 1}, "games": [], "refusalsByReason": {},
                "elapsedSeconds": 100.0 if date_str == "2026-11-09" else 1.0}

    monkeypatch.setattr(lr, "build_live_lens_snapshot", build)
    fleet["boards"][("ncaab", "20261109")] = [_in("P")]
    fleet["tick"](ROLL_PLUS_30)
    assert seen == {"2026-11-09": 240.0, "2026-11-10": 140.0}


def test_the_prior_lane_is_carried_across_ticks(fleet):
    """Tick 1 after the roll reads the PRE-midnight snapshot (date 11-09); tick 2 reads the merged one (date 11-10,
    row stamped 11-09). Both must hand the previous date its own rows, and only those."""
    store_key = str(lr.live_lens_snapshot_path("ncaab"))
    row = {"event_id": "P", "home": "H", "away": "A", "gameLens": []}
    fleet["store"][store_key] = {"date": "2026-11-09", "games": [row]}
    assert set(lr._previous_lanes_for_slate("2026-11-09")) == {"P"}
    fleet["store"][store_key] = {"date": "2026-11-10", "games": [{**row, "slateDate": "2026-11-09"},
                                                                {"event_id": "T", "gameLens": []}]}
    assert set(lr._previous_lanes_for_slate("2026-11-09")) == {"P"}
    assert set(lr._previous_lanes_for_slate("2026-11-10")) == {"T"}


def test_a_failing_previous_date_never_costs_today_its_tick(fleet, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("espn down")

    monkeypatch.setattr(lr, "prior_slate_snapshot", boom)
    fleet["boards"][("ncaab", "20261110")] = [_in("T")]
    status = fleet["tick"](ROLL_PLUS_30)
    out = capsys.readouterr().out
    assert status["prior_skip"] == "error:RuntimeError" and status["resimmed"] == 1 and status["written"] is True
    assert "NCAAB_LIVE_RESIM_PRIOR_ERROR date=2026-11-09 RuntimeError: espn down" in out


def test_merge_keeps_todays_row_for_an_event_on_both_dates_and_adds_the_cost():
    today = {"date": "2026-11-10", "games": [{"event_id": "X", "gameLens": []}], "counts": {"live": 1, "resimmed": 1},
             "resimTiming": {"workers": 2, "resim_jobs": 1, "resim_wall_s": 3.0, "resim_cpu_s": 2.9, "worker_errors": 0,
                             "worker_pids": [1]},
             "carryBound": {"mode": "shadow", "carriedAgeMaxSeconds": None}, "elapsedSeconds": 4.0}
    prior = {"date": "2026-11-09", "games": [{"event_id": "X", "gameLens": []}, {"event_id": "P", "gameLens": []}],
             "counts": {"live": 2, "resimmed": 1, "carried_forward": 1},
             "resimTiming": {"workers": 2, "resim_jobs": 1, "resim_wall_s": 5.0, "resim_cpu_s": 4.8, "worker_errors": 0,
                             "worker_pids": [2]},
             "carryBound": {"mode": "shadow", "carriedAgeMaxSeconds": 130.0}, "elapsedSeconds": 6.0}
    out = lr.merge_prior_slate(today, prior)
    assert [(g["event_id"], g.get("slateDate")) for g in out["games"]] == [("P", "2026-11-09"), ("X", None)]
    assert out["counts"] == {"live": 3, "resimmed": 2, "carried_forward": 1}
    assert out["resimTiming"]["resim_jobs"] == 2 and math.isclose(out["resimTiming"]["resim_wall_s"], 8.0)
    assert out["resimTiming"]["worker_pids"] == [1, 2] and out["carryBound"]["carriedAgeMaxSeconds"] == 130.0
    assert out["elapsedSeconds"] == 10.0 and out["priorSlate"]["dropped_also_today"] == 1


def test_the_tick_line_keeps_every_existing_field_in_place(fleet, capsys):
    fleet["boards"][("ncaab", "20261109")] = [_in("P")]
    fleet["tick"](ROLL_PLUS_30)
    keys = [tok.split("=", 1)[0] for tok in capsys.readouterr().out.strip().splitlines()[-1].split(" ")[1:]
            if "=" in tok and not tok.startswith(("'", "{"))]
    head = ["date", "live", "resimmed", "refused", "carried_forward", "not_reached", "dropped_non_d1", "carry_expired",
            "carry_bound", "carry_age_max_s", "workers", "resim_jobs", "resim_wall_s", "resim_cpu_s", "worker_errors"]
    assert keys[:len(head)] == head
    assert keys[len(head):len(head) + 5] == ["prior_date", "prior_live", "prior_resimmed", "prior_carried_forward",
                                             "prior_skip"]
    assert keys[-3:] == ["bytes", "written", "elapsed_s"]
