"""The as-of and scoring rules of scripts/backtest_mlb_lines_props.py.

Each test pins a rule whose violation would make the backtest look BETTER than
it is: a quote taken after first pitch, a baseline that includes the game being
graded, a re-sim written after the game started, a push scored as a loss.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backtest_mlb_lines_props as bt  # noqa: E402


def test_devig_is_proportional_and_symmetric():
    p = bt.devig_two_way("-110", "-110")
    assert p == pytest.approx(0.5)
    p_over = bt.devig_two_way("-150", "+130")
    assert p_over == pytest.approx(1 - bt.devig_two_way("+130", "-150"))
    assert 0.5 < p_over < bt.american_to_prob("-150")  # vig removed


def test_dist_prob_over_excludes_the_push_value():
    dist = {"0": 25, "1": 50, "2": 25}
    assert bt.dist_prob_over(dist, 0.5) == pytest.approx(0.75)
    # integer line: P(X>1 | X != 1) = 25 / 50
    assert bt.dist_prob_over(dist, 1.0) == pytest.approx(0.5)


def test_normal_prob_over_continuity():
    assert bt.normal_prob_over(8.5, 3.0, 8.5) == pytest.approx(0.5)
    assert bt.normal_prob_over(8.0, 3.0, 8.0) == pytest.approx(0.5, abs=1e-9)
    assert bt.normal_prob_over(10.0, 3.0, 8.5) > 0.5


def test_verdict_follows_the_nhl_rule():
    assert bt.verdict(150, -0.2, -0.1, 200) == "INSUFFICIENT_N"
    assert bt.verdict(300, -0.2, -0.1, 200) == "MODEL_BETTER"
    assert bt.verdict(300, 0.1, 0.2, 200) == "MODEL_WORSE"
    assert bt.verdict(300, -0.1, 0.2, 200) == "NO_DIFFERENCE"


def test_cluster_bootstrap_is_deterministic_and_resamples_games():
    rows = [{"game_pk": g, "v": float(g % 3)} for g in range(60) for _ in range(4)]
    a = bt.cluster_boot_ci(rows, lambda r: r["v"], draws=200)
    b = bt.cluster_boot_ci(rows, lambda r: r["v"], draws=200)
    assert a == b
    assert a[1] <= a[0] <= a[2]


def test_skill_verdict_needs_both_baseline_and_book():
    better = {"verdict_vs_baseline": "MODEL_BETTER", "verdict_vs_book": "MODEL_BETTER"}
    assert bt.skill_verdict(None, better) == "BEATS_BASELINE_AND_BOOK"
    assert bt.skill_verdict(None, {**better, "verdict_vs_book": "NO_DIFFERENCE"}) == "PARITY_WITH_BOOK"
    assert bt.skill_verdict(None, {**better, "verdict_vs_book": "MODEL_WORSE"}) == "LOSES_TO_BOOK"
    assert bt.skill_verdict(None, {**better, "verdict_vs_baseline": "NO_DIFFERENCE"}) == "BEATS_BOOK_ONLY"
    assert bt.skill_verdict(None, {"verdict_vs_baseline": "MODEL_BETTER"}) == "NO_BOOK_ROWS"


def test_calibration_splits_reliability_from_resolution():
    ps = [0.2] * 50 + [0.8] * 50
    ys = [0] * 40 + [1] * 10 + [1] * 40 + [0] * 10   # perfectly calibrated
    c = bt.calibration(ps, ys)
    assert c["reliability"] == pytest.approx(0.0)
    assert c["resolution"] == pytest.approx(0.09)
    assert c["slope"] == pytest.approx(1.0)
    over = bt.calibration([0.05] * 50 + [0.95] * 50, ys)  # same ranking, over-confident
    assert over["reliability"] > 0 and over["slope"] < 1


def test_dist_var():
    assert bt.dist_var({"0": 1, "2": 1}) == pytest.approx(1.0)


def test_player_baseline_excludes_the_graded_date_and_dnps():
    rows = [
        {"date": "2026-06-01", "game_pk": 1, "stat": {"hits": 1, "plateAppearances": 4}},
        {"date": "2026-06-02", "game_pk": 2, "stat": {"hits": 3, "plateAppearances": 4}},
        {"date": "2026-06-03", "game_pk": 3, "stat": {"hits": 0, "plateAppearances": 0}},  # pinch-run, no PA
        {"date": "2026-06-04", "game_pk": 4, "stat": {"hits": 4, "plateAppearances": 5}},  # the graded game
    ]
    b = bt.asof_baseline(rows, "2026-06-04", lambda s: s["hits"],
                         lambda s: s["plateAppearances"] > 0, min_games=2)
    assert b["n"] == 2 and b["mean"] == pytest.approx(2.0)
    assert bt.asof_baseline(rows, "2026-06-04", lambda s: s["hits"],
                            lambda s: s["plateAppearances"] > 0, min_games=3) is None


def test_player_rows_derives_outs_from_innings_pitched():
    log = {"stats": [{"splits": [{"date": "2026-06-01", "game": {"gamePk": 9},
                                  "stat": {"inningsPitched": "5.2", "strikeOuts": 6}}]}]}
    r = bt.player_rows(log)[0]
    assert r["stat"]["outs"] == 17 and r["game_pk"] == 9


def _write(p: Path, doc: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def test_sims_written_after_first_pitch_are_dropped(tmp_path):
    for i, status in enumerate(["Scheduled", "In Progress", "Final", "Warmup"]):
        _write(tmp_path / "sims" / "2026-06-17" / f"sim_{i}.json",
               {"game_pk": 100 + i, "schedule": {"status": {"detailed": status}}})
    c = Counter()
    sims = bt.load_pregame_sims(tmp_path, None, c)
    assert sorted(sims) == [100, 103]
    assert c["sim_dropped_not_pregame:In Progress"] == 1 and c["sim_dropped_not_pregame:Final"] == 1


def _game(start="2026-06-17T23:05:00Z"):
    return {"game_pk": 7, "date": "2026-06-17", "start": bt.parse_utc(start), "status": "Final",
            "game_type": "R", "home_id": 1, "away_id": 2, "home_name": "Home", "away_name": "Away",
            "home_score": 5, "away_score": 3,
            "innings": [(1, 0), (0, 1), (2, 0), (0, 0), (0, 1), (1, 0), (0, 1), (1, 0), (None, 0)]}


def _sim():
    seg = {"home_win_prob": 0.6, "away_win_prob": 0.4, "tie_prob": 0.0,
           "home_runs_mean": 4.6, "away_runs_mean": 3.9,
           "total_runs_dist": {"7": 30, "8": 20, "9": 30, "10": 20},
           "run_margin_dist": {"-2": 20, "-1": 20, "1": 20, "2": 25, "3": 15}}
    return {7: {"_date": "2026-06-17", "sim": {"segments": {"full": seg}}}}


def _snap(retrieved, home_odds):
    return {"_retrieved": bt.parse_utc(retrieved), "games": [{
        "home_team": "Home", "away_team": "Away", "commence_time": "2026-06-17T23:05:00Z",
        "markets": {"h2h": {"home_odds": home_odds, "away_odds": "+100"},
                    "totals": {"line": 8.5, "over_odds": "-110", "under_odds": "-110"},
                    "spreads": {"home_line": -1.5, "home_odds": "+140", "away_line": 1.5, "away_odds": "-160"},
                    "segments": {}}}]}


class _NoBase:
    def baseline(self, *a, **k):
        return None


def test_quote_retrieved_after_first_pitch_is_never_used():
    c = Counter()
    snaps = {"2026-06-17": [_snap("2026-06-17T23:30:00", "-300")]}  # naive UTC, after 23:05Z
    rows, _ = bt.build_game_rows(_sim(), {7: _game()}, _NoBase(), snaps, c)
    assert c["game_no_pregame_quote"] == 1
    assert all(r["p_book"] is None for r in rows)


def test_latest_pregame_quote_wins_and_sides_are_right():
    c = Counter()
    snaps = {"2026-06-17": [_snap("2026-06-17T16:00:00", "-120"),
                            _snap("2026-06-17T22:00:00", "-150"),
                            _snap("2026-06-17T23:30:00", "-300")]}
    rows, points = bt.build_game_rows(_sim(), {7: _game()}, _NoBase(), snaps, c)
    by = {r["market"]: r for r in rows}
    assert by["full:moneyline"]["p_book"] == pytest.approx(bt.devig_two_way("-150", "+100"))
    assert by["full:moneyline"]["y"] == 1                     # 5-3 home win
    assert by["full:run_line"]["y"] == 1                      # 5-3 covers -1.5
    assert by["full:run_line"]["p_model"] == pytest.approx(0.40)  # margin >= 2
    assert by["full:total"]["y"] == 0                         # 8 under 8.5
    assert by["full:total"]["p_model"] == pytest.approx(0.50)
    assert points[0]["act_margin"] == 2 and points[0]["model_margin"] == pytest.approx(0.7)


def test_segment_runs_first5_and_incomplete():
    g = _game()
    assert bt.segment_runs(g, "first5") == (3, 2)
    assert bt.segment_runs(g, "first1") == (1, 0)
    short = {**g, "innings": g["innings"][:4]}
    assert bt.segment_runs(short, "first5") is None
