"""Lane `live-winpct-blank` [2026-10-15]: live NFL/NCAAF rows with a PREGAME projection show no sim probability.

User decision in chat, "Blank the live Win%": keep the pregame projection, labelled as the pregame sim, but show no
probability (Win%, `model_probability`, the "Our sim has..." explainer) and no direction-contradiction tag against an
in-play line unless a live re-sim priced it. Diagnostic H-NFL (lane sim-gap-ev-study): on 10-11/10-12 11,999 of
12,563 NFL ledger rows first seen live carried the pregame normal read at a mid-game line; sims of 0.9-1.0 realised 0.458.
"""

from __future__ import annotations

import copy

from syndicate.features.shared import board_enrichment as be
from syndicate.features.shared import layer2_board as lb
from syndicate.features.shared.layer2_row_context import row_explainer


def _row(sport="nfl", state="live", *, live_aware=False, side="over", line=29.5, prob=0.832, edge=12.0):
    # A totals projection is framed on the OVER (no team side): `model_prob_over` is P(over).
    projection = {"projected": 41.18, "model_prob_over": prob, "edge_vs_market_pct": edge}
    if live_aware:
        projection["live_aware"] = True
    return {"sport": sport, "market": "totals", "segment": "full", "side": side, "line": line,
            "home_team": "Houston Texans", "away_team": "Tennessee Titans",
            "game": {"state": state}, "projection": projection}


def test_a_live_nfl_row_loses_its_pregame_probability_and_edge_but_keeps_the_projection():
    row = _row()
    report = be._enforce_live_edge_policy([row])
    p = row["projection"]
    assert p["model_prob_over"] is None and p["sim_model_prob_over"] == 0.832
    assert p["edge_vs_market_pct"] is None and p["projected"] == 41.18
    assert p["pregame_on_live"] is True and "withheld on an in-play line" in p["model_prob_over_unavailable_reason"]
    assert report["live_probability_withheld_rows"] == 1 and report["live_edge_enforced_rows"] == 1


def test_ncaaf_too_and_a_live_row_with_a_probability_but_no_edge_is_still_reached():
    """The old sweep `continue`d past rows with no edge -- the shape most live NFL/NCAAF rows have (edge refused upstream)."""
    row = _row(sport="ncaaf", edge=None)
    assert be._enforce_live_edge_policy([row])["live_probability_withheld_rows"] == 1
    assert row["projection"]["model_prob_over"] is None


def test_untouched_a_live_re_sim_row_a_pregame_row_and_another_sports_live_row():
    live_resim, pregame, mlb = _row(live_aware=True), _row(state="pregame"), _row(sport="mlb", edge=None)
    before = copy.deepcopy([live_resim, pregame, mlb])
    report = be._enforce_live_edge_policy([live_resim, pregame, mlb])
    assert [live_resim, pregame, mlb] == before
    assert report["live_probability_withheld_rows"] == 0


def test_a_final_nfl_game_withholds_too_and_says_so():
    row = _row(state="final", edge=None)
    be._enforce_live_edge_policy([row])
    assert row["projection"]["model_prob_over"] is None
    assert "final" in row["projection"]["model_prob_over_unavailable_reason"]


def test_downstream_no_win_pct_no_our_sim_sentence_no_contradiction_tag():
    row = _row(side="under")     # TEN@HOU: P(over 29.5) 0.832 from the pregame 41.18/12.14 normal -> the under at 16.8%
    quote = {"fair_probability": 0.5, "price": -110, "bookmaker": "draftkings", "books_quoting": 8}
    # Controls first, so the assertions below cannot pass on a fixture the board never reads.
    assert abs(lb._model_prob_for_side(row) - 0.168) < 1e-9
    assert "Our sim has the under 29.5 at 16.8%" in (row_explainer(row, quote) or "")
    assert lb._sim_direction_contradiction(row, row["projection"]) is not None, "pregame mean 41.2 vs live 29.5 under"
    be._enforce_live_edge_policy([row])
    assert lb._model_prob_for_side(row) is None
    assert lb._sim_direction_contradiction(row, row["projection"]) is None
    text = row_explainer(row, quote) or ""
    assert "Our sim has" not in text and "16.8%" not in text


def test_the_pregame_row_keeps_its_contradiction_tag():
    row = _row(state="pregame", side="under", line=29.5)
    be._enforce_live_edge_policy([row])
    assert lb._sim_direction_contradiction(row, row["projection"]) is not None
