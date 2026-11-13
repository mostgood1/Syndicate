"""The pre-registered college half-line grade (lane college-segment-grade, #763): outcomes, orientation, the row
filter, and the decision rule -- including a planted-edge positive control and a books-vs-books null, so a 'no edge'
verdict is known to come from an instrument that could have seen one."""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

import pytest

from syndicate.features.shared import engine_experts as ee

_spec = importlib.util.spec_from_file_location(
    "college_segment_grade", Path(__file__).resolve().parents[1] / "scripts" / "college_segment_grade.py")
csg = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = csg  # dataclasses resolve string annotations through sys.modules
_spec.loader.exec_module(csg)

FAST = {**csg.PREREG, "bootstrap": 2000}


# ----------------------------------------------------------------------------- outcomes


def test_h1_is_period_one_and_h2_takes_every_overtime():
    assert csg.segment_points([30, 34], "h1") == 30
    assert csg.segment_points([30, 34], "h2") == 34
    assert csg.segment_points([30, 34, 8, 6], "h2") == 48  # two overtimes ride on the second half
    assert csg.segment_points([30, 34, 8], "h1") == 30
    for bad in (None, [], [30], [30, None], ["30", 34], [30, True]):
        assert csg.segment_points(bad, "h2") is None
    assert csg.segment_points([30, 34], "q1") is None


def test_the_spread_event_is_the_experts_away_frame_line():
    """A book's home -2.5 is the expert's line 2.5 (`canonical_quote_side`); home covers when it wins by 3 or more."""
    assert ee.canonical_quote_side("spreads", "home", -2.5) == ("over", 2.5)
    assert csg.outcome("spreads", 2.5, 40, 35) == 1
    assert csg.outcome("spreads", 2.5, 40, 38) == 0
    # the line is the AWAY team's handicap: away -3.5 (home +3.5) is line -3.5, and home covers when margin > -3.5
    assert ee.canonical_quote_side("spreads", "away", -3.5) == ("under", -3.5)
    assert csg.outcome("spreads", -3.5, 30, 35) == 0  # away by 5: home did not cover +3.5
    assert csg.outcome("spreads", -3.5, 33, 35) == 1  # away by 2: home covered +3.5
    assert csg.outcome("totals", 70.5, 36, 35) == 1 and csg.outcome("totals", 71.5, 36, 35) == 0
    assert csg.outcome("totals", 71.0, 36, 35) is None and csg.outcome("spreads", 1.0, 36, 35) is None  # pushes


def _game(eid="401", home=("Duke Blue Devils", "DUKE"), away=("Army Black Knights", "ARMY"), hp=(30, 34),
          ap=(25, 31), final=True):
    return {"event_id": eid, "home": {"name": home[0], "short_name": home[0].split()[0], "abbr": home[1]},
            "away": {"name": away[0], "short_name": away[0].split()[0], "abbr": away[1]},
            "live_state": {"final": final, "home_linescores": list(hp) if hp is not None else None,
                           "away_linescores": list(ap) if ap is not None else None}}


def test_orientation_follows_the_teams_not_the_label():
    ev = {"home_name": "Duke Blue Devils", "away_name": "Army Black Knights", "home": "DUKE", "away": "ARMY"}
    assert csg.orientation(ev, _game()) == "same"
    flipped = _game(home=("Army Black Knights", "ARMY"), away=("Duke Blue Devils", "DUKE"))
    assert csg.orientation(ev, flipped) == "swapped"
    stranger = _game(home=("Kansas Jayhawks", "KU"), away=("Army Black Knights", "ARMY"))
    assert csg.orientation(ev, stranger) is None
    assert csg.orientation({}, _game()) is None  # empty keys never match each other


def test_final_games_keeps_final_records_only():
    boards = [{"games": [_game("1", final=False), _game("2")]}, {"games": [_game("1")]}]
    assert sorted(csg.final_games(boards)) == ["1", "2"]


# ----------------------------------------------------------------------------- rows


def _op(eid="401", segment="h2", market="totals", line=64.5, t="2026-11-11T19:30:00-06:00", p=0.6, prior=0.5,
        age=20.0, version="live_segment/1", sport="ncaab"):
    return csg.SlimOpinion(sport=sport, expert_version=version, event_id=eid, segment=segment, market=market,
                           line=line, t=t, p_expert=p, p_prior=prior, prior_age_s=age, clock_bucket="50-75",
                           delta_logit=0.1)


TEAMS = {"401": {"home_name": "Duke Blue Devils", "away_name": "Army Black Knights", "home": "DUKE", "away": "ARMY"}}


def test_rows_are_deduplicated_scored_and_counted():
    games = csg.final_games([{"games": [_game()]}])  # Duke 30+34, Army 25+31: h2 total 65, h2 margin +3
    ops = [_op(), _op(),  # the same row twice (a game in two dates' runs)
           _op(t="2026-11-11T19:31:00-06:00", line=65.0),  # lands on the line: push
           _op(market="spreads", line=2.5, t="2026-11-11T19:32:00-06:00"),  # home by 3 covers 2.5
           _op(eid="999", t="2026-11-11T19:33:00-06:00"),  # no final score
           _op(segment="q1", t="2026-11-11T19:34:00-06:00"),  # out of scope
           _op(age=None, t="2026-11-11T19:35:00-06:00")]
    rows, counts = csg.build_rows(ops, TEAMS, games, read_scores=True)
    assert [(r.market, r.y) for r in rows] == [("totals", 1), ("spreads", 1)]
    assert counts == {**counts, "duplicate": 1, "push": 1, "no_final_score": 1, "out_of_scope": 1, "no_age": 1,
                      "kept": 2}


def test_a_swapped_neutral_site_flips_the_spread_and_not_the_total():
    flipped = _game(home=("Army Black Knights", "ARMY"), away=("Duke Blue Devils", "DUKE"), hp=(25, 31), ap=(30, 34))
    games = csg.final_games([{"games": [flipped]}])
    rows, _ = csg.build_rows([_op(market="spreads", line=2.5), _op(t="x2")], TEAMS, games, read_scores=True)
    assert [(r.market, r.y) for r in rows] == [("spreads", 1), ("totals", 1)]  # Duke still won the half by 3
    unknown = {"401": {"home_name": "Kansas", "away_name": "Army Black Knights", "home": "KU", "away": "ARMY"}}
    rows, counts = csg.build_rows([_op(market="spreads", line=2.5), _op(t="x2")], unknown, games, read_scores=True)
    assert [r.market for r in rows] == ["totals"] and counts["orientation_unresolved"] == 1


def test_the_count_only_run_reads_no_score():
    games = csg.final_games([{"games": [_game(hp=None, ap=None)]}])  # final, but no line score at all
    rows, counts = csg.build_rows([_op()], TEAMS, games, read_scores=False)
    assert len(rows) == 1 and rows[0].y is None and counts["unscorable"] == 0
    rows, counts = csg.build_rows([_op()], TEAMS, games, read_scores=True)
    assert rows == [] and counts["unscorable"] == 1


# ----------------------------------------------------------------------------- the decision


def _rows(n_games, model, *, ages=(10.0, 60.0), seed=1, per_game=6):
    """Synthetic rows on all four pairs. `model(y, p_books, rng)` gives the engine's number."""
    rng = random.Random(seed)
    rows = []
    for g in range(n_games):
        for segment in ("h1", "h2"):
            for market in ("totals", "spreads"):
                for k in range(per_game):
                    p_books = rng.uniform(0.3, 0.7)
                    y = 1 if rng.random() < p_books else 0
                    rows.append(csg.GradeRow(f"g{g}", segment, market, 0.5, f"t{k}", model(y, p_books, rng),
                                             p_books, ages[k % len(ages)], "50-75", y))
    return rows


def test_a_planted_edge_passes_every_primary_test():
    """POSITIVE CONTROL: an engine that leans toward the outcome beats the books in every cell."""
    res = csg.grade(_rows(40, lambda y, pb, rng: min(0.95, max(0.05, pb + (0.15 if y else -0.15)))), FAST)
    assert [p["status"] for p in res["primary"]] == ["PASS"] * 8
    assert res["verdict"]["hypothesis"] == "FALSIFIED" and len(res["verdict"]["passing"]) == 8
    assert all(e["realised_pp"] > 0 for e in res["edges"])


def test_the_books_against_themselves_never_pass():
    """NULL: d is exactly 0 on every row, so no upper bound is below 0."""
    res = csg.grade(_rows(40, lambda y, pb, rng: pb), FAST)
    assert [p["status"] for p in res["primary"]] == ["no_edge"] * 8
    assert all(p["d_brier"] == 0 for p in res["primary"]) and res["verdict"]["hypothesis"] == "HOLDS"


def test_a_noisy_engine_with_no_information_does_not_pass():
    """NULL with noise: an engine that is the books plus noise is worse, never 'better beyond noise'."""
    res = csg.grade(_rows(60, lambda y, pb, rng: min(0.97, max(0.03, pb + rng.gauss(0, 0.08)))), FAST)
    assert all(p["status"] == "no_edge" for p in res["primary"])
    assert sum(p["d_brier"] for p in res["primary"]) > 0  # worse on the whole (noise costs its variance)


def test_too_few_games_is_insufficient_not_a_verdict():
    res = csg.grade(_rows(12, lambda y, pb, rng: 0.9 if y else 0.1), FAST)
    assert {p["status"] for p in res["primary"]} == {"insufficient"}
    assert res["verdict"]["hypothesis"] == "HOLDS" and len(res["verdict"]["insufficient"]) == 8


def test_ceilings_are_cumulative_and_age_buckets_disjoint():
    rows = _rows(35, lambda y, pb, rng: pb, ages=(-0.5, 25.0, 90.0, 200.0, 900.0), per_game=5)
    res = csg.grade(rows, FAST)
    first = [p for p in res["primary"] if p["segment"] == "h1" and p["market"] == "totals"]
    assert [p["rows"] for p in first] == [35 * 2, 35 * 3]  # <= 30 s: -0.5 and 25; <= 120 s adds 90
    buckets = [b for b in res["by_age"] if b["segment"] == "h1" and b["market"] == "totals"]
    assert [b["rows"] for b in buckets] == [35 * 2, 35, 35, 35]  # 900 s closes the last bucket


def test_the_family_interval_is_wider_than_the_nominal_one():
    res = csg.grade(_rows(40, lambda y, pb, rng: min(0.97, max(0.03, pb + rng.gauss(0, 0.05)))), FAST)
    for p in res["primary"]:
        assert p["ci_fw"][0] <= p["ci95"][0] and p["ci_fw"][1] >= p["ci95"][1]
    assert res["family_level"] == pytest.approx(1 - 0.05 / 8)
