"""NBA blowout bench study (todo #788, lane nba-pbp-blowout-bench): the college study (#787) on NBA geometry.

One synthetic score-matched game, home leading by 25 entering the 4th with its whole bench on, plus the rows the
study must NOT read (a preseason game, a game whose play-by-play misses the official score, refused and carried
re-sim rows), and a post-midnight tick filed in the NEXT date's history (#776).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts import nba_blowout_bench_study as study

DAY, NEXT_DAY = "2026-11-07", "2026-11-08"  # after h2 carried overtime (#789)
H5 = ["h1", "h2", "h3", "h4", "h5"]
HB = ["h6", "h7", "h8", "h9", "h10"]
A5 = ["a1", "a2", "a3", "a4", "a5"]
AB = ["a6", "a7", "a8"]


def _csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _stint(eid, team, start, end, lineup, pf, pa):
    return {"event_id": eid, "team": team, "start_sec": start, "end_sec": end, "pts_for": pf, "pts_against": pa,
            "lineup_player_ids": ";".join(lineup)}


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    base = tmp_path / "nba_source" / "data" / "processed" / "rotation_stints"
    games = [
        {"event_id": "G1", "season_type": "regular", "score_match": "1", "official_home": "120", "official_away": "97"},
        {"event_id": "PRE", "season_type": "preseason", "score_match": "1", "official_home": "100", "official_away": "90"},
        {"event_id": "BAD", "season_type": "regular", "score_match": "0", "official_home": "100", "official_away": "90"},
    ]
    checks = [{"event_id": eid, "team": t, "player_id": p, "starter": "1"}
              for eid in ("G1", "PRE", "BAD") for t, five in (("H", H5), ("A", A5)) for p in five]
    stints = []
    for eid in ("G1", "PRE", "BAD"):
        stints += [
            _stint(eid, "H", 0, 2160, H5, 100, 75),  # first 36 min: 175 points, home +25
            _stint(eid, "H", 2160, 2880, HB, 20, 22),  # the whole 4th: home bench, 42 points
            _stint(eid, "H", 2880, 3180, H5, 3, 0),  # overtime: dropped
            _stint(eid, "A", 0, 2160, A5, 75, 100),
            _stint(eid, "A", 2160, 2880, A5[:2] + AB, 22, 20),  # two starters left on
        ]
    _csv(base / f"games_{DAY}.csv", games)
    _csv(base / f"player_checks_{DAY}.csv", checks)
    _csv(base / f"stints_{DAY}.csv", stints)

    hist = tmp_path / "nba_source" / "data" / "processed" / "live_resim_history"
    hist.mkdir(parents=True)

    def row(eid, per, clk, hs, as_, tot, **kw):
        return {"event_id": eid, "source": "live_resim", "refusal": None, "period": per, "clock_s": clk,
                "home_score": hs, "away_score": as_, "total": tot, **kw}

    today = [
        row("G1", 2, 300, 50, 40, 220.0),  # Q2: error 217 - 220 = -3, not a late tick
        row("G1", 4, 600, 105, 80, 215.0),  # 10:00 left, +25, home bench on: error +2
        row("G1", 4, 600, 105, 80, 230.0, refusal="stale_state"),  # refused: not a measurement
        row("G1", 4, 590, 105, 80, 230.0, carried_forward=True),  # carried: not a measurement
        {**row("G1", 4, 590, 105, 80, 230.0), "source": "pregame_only"},
        row("PRE", 4, 600, 80, 60, 150.0),  # preseason: not graded
        row("BAD", 4, 600, 80, 60, 150.0),  # score mismatch: excluded
    ]
    after_midnight = [
        # 1:40 left, +22: error -2. Since h2 carries overtime, its segments say 0.4 expected OT points; p_ot 0.02 (#789)
        row("G1", 4, 100, 117, 95, 219.0, slate_date=DAY, t="2026-11-08T06:10:00+00:00",
            segments={"q3": 50.0, "q4": 60.0, "h2": 110.4}, p_ot=0.02),
        row("G1", 5, 200, 117, 95, 240.0, slate_date=DAY),  # an overtime tick: regulation only, in every table
    ]
    (hist / f"{DAY}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in today), encoding="utf-8")
    (hist / f"{NEXT_DAY}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in after_midnight), encoding="utf-8")
    return tmp_path


def test_engine_constants_match_the_engine():
    from syndicate.features.basketball_engine.engine import EventSimConfig
    from syndicate.features.basketball_engine.league import league_params

    cfg = EventSimConfig()
    assert study.ENGINE_BLOWOUT_MARGIN == cfg.blowout_margin
    assert study.ENGINE_BLOWOUT_Q4_MARGIN == cfg.blowout_q4_margin
    assert study.ENGINE_SECOND_HALF_FIRST_PERIOD == league_params("nba").second_half_first_period
    assert cfg.blowout_bench_rest is False  # the study describes production: the leader's bench rest is off


@pytest.mark.parametrize("period, margin, flagged", [
    (2, 30, False), (3, 17, False), (3, 18, True), (3, -18, True), (4, 14, False), (4, 15, True), (4, -15, True),
])
def test_engine_blowout_flag(period, margin, flagged):
    assert study.engine_blowout(period, margin) is flagged


def test_load_keeps_graded_score_matched_regulation_only(root):
    games, finals = study.load_team_stints(root, [DAY])
    assert set(games) == {"G1"} and finals == {"G1": 217.0}
    assert [s["end"] for s in games["G1"]["H"]] == [2160, 2880]  # overtime stint dropped
    q4 = games["G1"]["H"][1]
    assert (q4["margin"], q4["starters_on"], q4["points"]) == (25.0, 0, 42.0)
    assert games["G1"]["A"][1]["starters_on"] == 2


def test_q1_counts_a_stint_that_starts_at_the_fourth_quarter_tip(root):
    games, _ = study.load_team_stints(root, [DAY])
    q1 = study.q1_when(games)
    # every 2-minute bucket of the 4th is covered by the 25+ stints, including 12-10 (start exactly at 12:00 left)
    for left, *_ in study.LEFT_BUCKETS:
        assert q1[f"leader|25+|{left}"] == 0.0
        assert q1[f"trailer|25+|{left}"] == 2.0
    assert not any(k.split("|")[1] == "<10" for k in q1)  # the tied first stint is not leader or trailer


def test_q2_ratio_against_the_games_own_first_36_minutes(root):
    games, _ = study.load_team_stints(root, [DAY])
    q2 = study.q2_effect(games)
    assert set(q2) == {"25+|bench<=1"}  # the leader's stints only, 4th quarter only
    expected = 42.0 / (12.0 * 175.0 / 36.0)
    assert q2["25+|bench<=1"] == {"ratio": round(expected, 3), "ci95": None, "games": 1}


def test_q3_errors_by_bench_flag_and_period(root):
    games, finals = study.load_team_stints(root, [DAY])
    q3 = study.q3_model(games, finals, study.history_ticks(root, [DAY, NEXT_DAY]))
    assert q3["by_lead_bench"] == {
        "20-24|bench<=1": {"error": -2.0, "ci95": None, "games": 1, "ticks": 1},
        "25+|bench<=1": {"error": 2.0, "ci95": None, "games": 1, "ticks": 1},
    }
    assert q3["by_engine_flag"] == {
        "engine_blowout|12-6": {"error": 2.0, "ci95": None, "games": 1, "ticks": 1},
        "engine_blowout|6-0": {"error": -2.0, "ci95": None, "games": 1, "ticks": 1},
    }
    assert q3["by_period_all_ticks"] == {
        "Q2": {"error": -3.0, "ci95": None, "games": 1, "ticks": 1},
        "Q4": {"error": 0.0, "ci95": None, "games": 1, "ticks": 2},
    }


def test_main_reads_the_next_days_history_only_with_evidence(root, capsys):
    assert study.main(["--start", DAY, "--end", DAY, "--data-root", str(root)]) == 0
    off = json.loads(capsys.readouterr().out)
    assert off["games"] == 1 and "q3_live_resim_remaining_error" not in off

    assert study.main(["--start", DAY, "--end", DAY, "--data-root", str(root), "--evidence"]) == 0
    on = json.loads(capsys.readouterr().out)
    assert on != off
    # the post-midnight tick lives in NEXT_DAY's file and is still read (#776)
    assert on["q3_live_resim_remaining_error"]["by_lead_bench"]["20-24|bench<=1"]["ticks"] == 1
    # ... and reaches the overtime check: G1 went to no overtime (its official final is its regulation total)
    assert on["q4_overtime"] == {
        "expected_ot_points": {"10+|6-0": {"expected": 0.4, "actual": 0.0, "error": -0.4, "ci95": None, "games": 1,
                                           "ot_games": 0, "ticks": 1}},
        "p_ot": {"10+|6-0": {"p_ot": 0.02, "actual": 0.0, "error": -0.02, "ci95": None, "games": 1, "ot_games": 0,
                             "ticks": 1}},
    }


# ---- Q4: overtime (#789) ----

def _ot_tick(eid, per, clk, hs, as_, *, t="2026-11-08T03:00:00+00:00", seg=None, p_ot=None):
    return {"event_id": eid, "period": per, "clock_s": clk, "home_score": hs, "away_score": as_, "t": t,
            "segments": seg or {}, "p_ot": p_ot}


OT_GAMES = {"OT": {"H": [{"points": 100.0}, {"points": 100.0}]}, "REG": {"H": [{"points": 210.0}]}}
OT_FINALS = {"OT": 222.0, "REG": 210.0}  # OT: 200 in regulation + 22 in overtime


def test_q4_expected_overtime_points_against_the_real_overtime():
    ticks = [
        _ot_tick("OT", 4, 60, 98, 98, seg={"q3": 50.0, "q4": 50.0, "h2": 104.0}),  # tied, 1:00 left: 4 expected
        _ot_tick("OT", 4, 30, 99, 99, seg={"q3": 50.0, "q4": 51.0, "h2": 109.0}),  # 0:30 left: 8 expected
        _ot_tick("REG", 4, 60, 105, 95, seg={"q3": 50.0, "q4": 55.0, "h2": 105.5}),  # +10: 0.5 expected, none came
        _ot_tick("REG", 2, 300, 50, 45, seg={"q3": 52.0, "q4": 53.0, "h2": 106.0}),  # earlier ticks: one cell
    ]
    q4 = study.q4_overtime(OT_GAMES, OT_FINALS, ticks)["expected_ot_points"]
    assert q4["0-2|6-0"] == {"expected": 6.0, "actual": 22.0, "error": 16.0, "ci95": None, "games": 1, "ot_games": 1,
                             "ticks": 2}
    assert q4["10+|6-0"]["error"] == -0.5 and q4["10+|6-0"]["ot_games"] == 0
    assert q4["Q1-Q3|all"]["expected"] == 1.0
    tip = _ot_tick("REG", 4, 720, 80, 60, seg={"q3": 50.0, "q4": 55.0, "h2": 105.25})  # exactly 12:00 left
    assert set(study.q4_overtime(OT_GAMES, OT_FINALS, [tip])["expected_ot_points"]) == {"10+|12-6"}


def test_q4_rows_before_h2_carried_overtime_are_not_read_as_zero_expected():
    before = _ot_tick("OT", 4, 60, 98, 98, t="2026-11-06T15:51:29+00:00", seg={"q3": 50.0, "q4": 50.0, "h2": 100.0})
    after = _ot_tick("OT", 4, 60, 98, 98, t="2026-11-06T15:51:30+00:00", seg={"q3": 50.0, "q4": 50.0, "h2": 104.0})
    assert study.q4_overtime(OT_GAMES, OT_FINALS, [before])["expected_ot_points"] == {}
    assert study.q4_overtime(OT_GAMES, OT_FINALS, [before, after])["expected_ot_points"]["0-2|6-0"]["expected"] == 4.0
    no_time = {**after, "t": None}
    assert study.q4_overtime(OT_GAMES, OT_FINALS, [no_time])["expected_ot_points"] == {}


def test_q4_p_ot_against_whether_the_game_went_to_overtime():
    ticks = [_ot_tick("OT", 4, 30, 99, 99, p_ot=0.4), _ot_tick("REG", 4, 30, 99, 99, p_ot=0.2),
             _ot_tick("REG", 4, 20, 99, 99)]  # no p_ot: an old row, not a 0
    q4 = study.q4_overtime(OT_GAMES, OT_FINALS, ticks)["p_ot"]
    cell = q4["0-2|6-0"]
    assert (cell["p_ot"], cell["actual"], cell["games"], cell["ot_games"], cell["ticks"]) == (0.3, 0.5, 2, 1, 2)
    assert cell["error"] == 0.2  # mean of (1 - 0.4) and (0 - 0.2)


def test_season_types_flag_reaches_the_loader(root, capsys):
    study.main(["--start", DAY, "--end", DAY, "--data-root", str(root), "--season-types", "regular,preseason"])
    assert json.loads(capsys.readouterr().out)["games"] == 2
