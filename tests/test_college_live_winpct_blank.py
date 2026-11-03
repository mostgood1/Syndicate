"""College joins the live Win% blank (lane wncaab-module, user "Yes, blank it", 2026-11-03).

A live or final NCAAB / WNCAAB row with a PREGAME projection keeps the projection and shows no sim probability; a
live re-sim row keeps its live number. NFL/NCAAF's rule (`tests/test_live_winpct_blank.py`), extended by sport."""

from __future__ import annotations

import copy

import pytest

from syndicate.features.shared import board_enrichment as be


def _row(sport="ncaab", state="live", *, live_aware=False, line=104.5, prob=0.985, edge=None):
    projection = {"projected": 135.385, "model_prob_over": prob, "edge_vs_market_pct": edge}
    if live_aware:
        projection["live_aware"] = True
    return {"sport": sport, "market": "totals", "segment": "full", "side": "over", "line": line,
            "home_team": "East Carolina Pirates", "away_team": "Charleston Southern Buccaneers",
            "game": {"state": state}, "projection": projection}


@pytest.mark.parametrize("sport", ["ncaab", "wncaab"])
@pytest.mark.parametrize("state", ["live", "final"])
def test_a_live_or_final_college_row_loses_its_pregame_probability_and_keeps_the_projection(sport, state):
    row = _row(sport=sport, state=state)
    report = be._enforce_live_edge_policy([row])
    p = row["projection"]
    assert p["model_prob_over"] is None and p["sim_model_prob_over"] == 0.985 and p["projected"] == 135.385
    assert p["pregame_on_live"] is True and state in p["model_prob_over_unavailable_reason"]
    assert report["live_probability_withheld_rows"] == 1


def test_untouched_a_college_pregame_row_a_live_re_sim_row_and_an_nba_live_row():
    """Reachability's control half: the sport gate is what moved, so a sport outside it must still be untouched."""
    pregame, resim, nba = _row(state="pregame"), _row(sport="wncaab", live_aware=True), _row(sport="nba")
    before = copy.deepcopy([pregame, resim, nba])
    report = be._enforce_live_edge_policy([pregame, resim, nba])
    assert [pregame, resim, nba] == before
    assert report["live_probability_withheld_rows"] == 0


def test_production_order_the_live_re_sim_join_keeps_its_number_and_its_edge():
    """`book_grid_artifact` sweeps BEFORE `live_gameline_join`; the join then writes its own probability and edge."""
    row = _row(line=150.5, prob=0.42)
    be._enforce_live_edge_policy([row])
    row["projection"].update({"live_aware": True, "live_model_prob_over": 0.61, "edge_vs_market_pct": 9.4})
    assert row["projection"]["model_prob_over"] is None, "no pregame Win% on the in-play line"
    assert row["projection"]["live_model_prob_over"] == 0.61 and row["projection"]["edge_vs_market_pct"] == 9.4
