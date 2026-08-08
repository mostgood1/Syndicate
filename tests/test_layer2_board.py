"""L2-A candidate builder over the Layer 1 grid.

Two tests carry most of the weight:

`test_mean_based_projection_is_not_added_to_ev` — WNBA and soccer-away-from-2.5
emit `edge_vs_line` in units of the stat (rebounds, goals). Adding that to an EV
percentage would be adding rebounds to percent. Only `edge_vs_market_pct`, which
is probability-space, may contribute.

`test_dead_market_is_never_ranked` — eligibility runs before scoring, so a
settled or stale market cannot appear on a shortlist however good its number
looks.
"""

from __future__ import annotations

from syndicate.features.shared.layer2_board import build_layer2_rows


def _row(**overrides):
    row = {
        "sport": "mlb",
        "event_id": "evt1",
        "kind": "game",
        "market": "totals",
        "segment": "full",
        "line": 8.5,
        "player_name": None,
        "home_team": "St. Louis Cardinals",
        "away_team": "Colorado Rockies",
        "commence_time": "2026-08-08T00:15:00Z",
        "sides": ["over", "under"],
        "books_quoting": 11,
        "game": {"state": "pregame", "status_token": "7:15P CT"},
        "best": {
            "over": {"price": -110, "bookmaker": "betopenly", "age_seconds": 52.0, "books_quoting": 9},
            "under": {"price": -105, "bookmaker": "betmgm", "age_seconds": 60.0, "books_quoting": 9},
        },
    }
    row.update(overrides)
    return row


def test_each_side_becomes_its_own_candidate():
    """A bet is one side; the grid row holds both."""
    result = build_layer2_rows([_row()])
    assert result["sides_priced"] == 2
    assert {c["side"] for c in result["opportunities"]} == {"over", "under"}


def test_two_sided_fair_is_devigged_and_drives_ev():
    result = build_layer2_rows([_row()])
    for candidate in result["opportunities"]:
        assert candidate["quote"]["fair_method"] == "two_sided"
        assert candidate["quote"]["fair_probability"] is not None
        assert candidate["ev_pct"] is not None


def test_dead_market_is_never_ranked():
    row = _row(game={"state": "final", "status_token": "F"})
    result = build_layer2_rows([row])
    assert result["opportunities"] == []
    assert result["by_lane"].get("dead") == 2


def test_unpriced_side_is_skipped_not_zero_filled():
    row = _row(best={"over": {"price": -110, "bookmaker": "b", "age_seconds": 10.0}, "under": {}})
    result = build_layer2_rows([row])
    assert result["sides_priced"] == 1


def test_one_sided_row_falls_back_to_the_margin_model_and_says_so():
    row = _row(
        sides=["over"],
        best={"over": {"price": 450, "bookmaker": "dk", "age_seconds": 20.0, "books_quoting": 11}},
        modelled_fair={"over": {"fair_probability": 0.2}},
    )
    result = build_layer2_rows([row])
    assert result["opportunities"]
    assert result["opportunities"][0]["quote"]["fair_method"] == "book_margin_model"


def test_probability_projection_contributes_a_model_edge():
    row = _row(projection={"edge_vs_market_pct": 6.0, "side": "over"})
    result = build_layer2_rows([row])
    over = [c for c in result["opportunities"] if c["side"] == "over"][0]
    under = [c for c in result["opportunities"] if c["side"] == "under"][0]
    assert over["model_edge_pct"] == 6.0
    # The projection is stated from one side; the other side inherits its inverse.
    assert under["model_edge_pct"] == -6.0


def test_mean_based_projection_is_not_added_to_ev():
    """WNBA/soccer means are in stat units, not probability points."""
    row = _row(
        projection={
            "projected": 9.1,
            "edge_vs_line": 0.6,
            "side": "over",
            "model_prob_over": None,
            "edge_vs_market_pct": None,
        }
    )
    result = build_layer2_rows([row])
    for candidate in result["opportunities"]:
        assert candidate["model_edge_pct"] is None


def test_rows_without_a_value_term_are_excluded_not_zeroed():
    """blended_score returns None with no EV and no model view; zeroing such a
    row would rank it above genuinely negative ones."""
    row = _row(
        sides=["over"],
        best={"over": {"price": 120, "bookmaker": "dk", "age_seconds": 15.0}},
    )
    result = build_layer2_rows([row])
    assert result["opportunities"] == []


def test_ranked_best_first():
    # Ranked on EV, not on model edge. With _SCORE_SIM_WEIGHT at 0 (gated on
    # S6) a model edge cannot order anything, so a fixture that differed ONLY
    # in model edge produced a tie and this test failed -- correctly reporting
    # that the board can no longer rank by the model. It now differs in the
    # term that actually ranks.
    #
    # History worth keeping: this fixture first used model edges of 20.0 vs
    # 1.0, which tripped _MODEL_EDGE_MAX_POINTS once that bound existed. 20
    # points was chosen as "clearly bigger", not as a realistic edge.
    # BOTH sides are required: EV comes from a two-sided de-vig, and a
    # one-sided `best` yields no fair, no EV, no score, and an EMPTY
    # opportunities list -- which is how the first attempt at this fixture
    # failed with an IndexError rather than a ranking assertion.
    #
    # The two rows differ in HOLD, because that is what the board now ranks on:
    # EV against a proportional de-vig is 1/overround - 1, so a tighter market
    # scores higher. strong ~2.4% hold, weak ~11.5%.
    strong = _row(
        event_id="strong",
        best={
            "over": {"price": -105, "bookmaker": "dk", "age_seconds": 15.0, "books_quoting": 9},
            "under": {"price": -105, "bookmaker": "dk", "age_seconds": 15.0, "books_quoting": 9},
        },
    )
    weak = _row(
        event_id="weak",
        best={
            "over": {"price": -130, "bookmaker": "dk", "age_seconds": 15.0, "books_quoting": 9},
            "under": {"price": -130, "bookmaker": "dk", "age_seconds": 15.0, "books_quoting": 9},
        },
    )
    result = build_layer2_rows([weak, strong])
    assert result["opportunities"][0]["event_id"] == "strong"


def test_cells_are_not_copied_into_the_shortlist():
    """The grid row carries every book x every side; a shortlist payload must not."""
    row = _row(cells={"betmgm": {"over": {"price": -110}}})
    result = build_layer2_rows([row])
    assert "cells" not in result["opportunities"][0]


def test_identity_survives_onto_the_candidate():
    result = build_layer2_rows([_row()])
    candidate = result["opportunities"][0]
    assert candidate["market"] == "totals"
    assert candidate["line"] == 8.5
    assert candidate["home_team"] == "St. Louis Cardinals"


# --- shortlist selection ------------------------------------------------------
# 100 rows per sport, ledger carries the rest. The mix rule exists because a pure
# score ranking would not produce one: MLB has 1,221 prop rows against 229 game
# rows, so props would plausibly take every slot.

from syndicate.features.shared.layer2_board import (  # noqa: E402
    SHORTLIST_KIND_FLOOR,
    SHORTLIST_ROWS_PER_SPORT,
    select_shortlist,
)
from datetime import datetime, timezone  # noqa: E402


def _cand(sport, kind, score, market="totals"):
    return {"sport": sport, "kind": kind, "market": market, "score": {"score": score}}


def test_caps_at_the_per_sport_limit():
    rows = [_cand("mlb", "prop", 100 - i) for i in range(400)]
    result = select_shortlist(rows)
    assert result["per_sport"]["mlb"]["selected"] == SHORTLIST_ROWS_PER_SPORT


def test_each_sport_gets_its_own_allowance():
    rows = [_cand("mlb", "prop", 10) for _ in range(200)] + [_cand("wnba", "prop", 10) for _ in range(200)]
    result = select_shortlist(rows)
    assert result["per_sport"]["mlb"]["selected"] == 100
    assert result["per_sport"]["wnba"]["selected"] == 100
    assert len(result["rows"]) == 200


def test_game_lines_survive_a_prop_dominated_slate():
    """The whole point of the floor: 400 high-scoring props vs 30 weak game lines."""
    rows = [_cand("mlb", "prop", 100) for _ in range(400)] + [_cand("mlb", "game", 1) for _ in range(30)]
    result = select_shortlist(rows)
    report = result["per_sport"]["mlb"]
    assert report["game"] >= SHORTLIST_KIND_FLOOR
    assert report["prop"] >= SHORTLIST_KIND_FLOOR
    assert report["selected"] == 100


def test_unused_floor_flows_to_the_other_kind():
    """A sport with only 3 game lines must still fill the cap, not floor+3."""
    rows = [_cand("mlb", "prop", 50) for _ in range(200)] + [_cand("mlb", "game", 40) for _ in range(3)]
    result = select_shortlist(rows)
    report = result["per_sport"]["mlb"]
    assert report["selected"] == 100
    assert report["game"] == 3
    assert report["prop"] == 97


def test_merit_decides_the_remainder():
    """Above the floors, the best score wins regardless of kind.

    Needs MORE candidates than the cap, or everything fits and the selection
    rule is never exercised — which is what an earlier version of this test did.
    """
    rows = [_cand("mlb", "prop", 100 - i) for i in range(200)] + [_cand("mlb", "game", 1) for _ in range(200)]
    result = select_shortlist(rows)
    report = result["per_sport"]["mlb"]
    assert report["selected"] == 100
    assert report["game"] == 30        # floor only; its scores lose
    assert report["prop"] == 70        # 30 floor + all 40 of the remainder


def test_out_of_season_sports_consume_no_budget():
    """Never all 8 at once -- an absent sport must not reserve slots."""
    rows = [_cand("mlb", "prop", 10) for _ in range(100)]
    result = select_shortlist(rows)
    assert result["active_sports"] == ["mlb"]
    assert len(result["rows"]) == 100


def test_persisted_bytes_is_reported():
    """The real constraint is bytes; the count is only the knob."""
    rows = [_cand("mlb", "prop", 10) for _ in range(60)]
    result = select_shortlist(rows)
    assert result["persisted_bytes"] > 0


def test_rows_come_back_ranked():
    rows = [_cand("mlb", "prop", 1), _cand("mlb", "prop", 99), _cand("wnba", "game", 50)]
    result = select_shortlist(rows)
    scores = [r["score"]["score"] for r in result["rows"]]
    assert scores == sorted(scores, reverse=True)


def test_rows_beyond_the_horizon_are_excluded_and_counted():
    """MEASURED 2026-08-07: all 1,244 NFL rows started 34-156 days out, so the
    board showed a full NFL slate on a day with no NFL game. A flat per-sport cap
    would spend a whole allowance on markets nobody can act on this week."""
    now = datetime(2026, 8, 7, 22, 45, tzinfo=timezone.utc)
    today = [dict(_cand("mlb", "game", 10), commence_time="2026-08-08T00:15:00Z") for _ in range(5)]
    far = [dict(_cand("nfl", "game", 99), commence_time="2026-09-10T17:00:00Z") for _ in range(50)]
    result = select_shortlist(today + far, now=now)
    assert result["active_sports"] == ["mlb"]
    assert result["rows_beyond_horizon"] == 50


def test_tomorrow_is_inside_the_horizon():
    """MLB carried 1,840 rows for tomorrow; an overnight boundary must stay usable."""
    now = datetime(2026, 8, 7, 22, 45, tzinfo=timezone.utc)
    rows = [dict(_cand("mlb", "game", 10), commence_time="2026-08-08T23:00:00Z")]
    result = select_shortlist(rows, now=now)
    assert len(result["rows"]) == 1


def test_missing_commence_time_is_kept_not_dropped():
    """Every non-MLB sport currently ships game.state as None; dropping unstamped
    rows would hide a whole sport if a feed stopped stamping starts."""
    now = datetime(2026, 8, 7, 22, 45, tzinfo=timezone.utc)
    rows = [dict(_cand("wnba", "prop", 10), commence_time=None)]
    result = select_shortlist(rows, now=now)
    assert len(result["rows"]) == 1


def test_horizon_can_be_disabled_for_a_forward_view():
    """Plan §4b wants forward-looking markets; this scopes the SHORTLIST only."""
    now = datetime(2026, 8, 7, 22, 45, tzinfo=timezone.utc)
    rows = [dict(_cand("nfl", "game", 99), commence_time="2026-09-10T17:00:00Z") for _ in range(5)]
    result = select_shortlist(rows, horizon_days=None, now=now)
    assert len(result["rows"]) == 5


# ---------------------------------------------------------------------------
# The model edge is bounded by what it IMPLIES, not just where it came from.
# ---------------------------------------------------------------------------


def test_an_implausible_model_edge_is_dropped_not_used():
    """MEASURED on the first MLB pregame board carrying projections
    (2026-08-08): 93 of 100 shortlisted rows had NEGATIVE EV against the
    market's own no-vig price, ranked by model edges of 9-48 points. On h2h
    that implies model win probabilities of 86-89% on games the market prices
    near even -- a units mismatch or a home/away join fault, not an edge.

    The name guard could not catch it: the field is literally called
    `edge_vs_market_pct`.
    """
    from syndicate.features.shared import layer2_board

    row = {"projection": {"edge_vs_market_pct": 39.38, "side": "away"}}
    assert layer2_board._model_edge_for(row, "away") is None


def test_a_large_but_plausible_edge_still_counts():
    """Deliberately generous: a genuine 15-point edge is enormous and passes.
    This is a guard against impossible values, not a calibration."""
    from syndicate.features.shared import layer2_board

    row = {"projection": {"edge_vs_market_pct": 12.0, "side": "away"}}
    assert layer2_board._model_edge_for(row, "away") == 12.0


def test_the_flip_is_bounded_too():
    """The other side of a rejected projection must also be rejected --
    otherwise flipping the sign smuggles the same bad number back in."""
    from syndicate.features.shared import layer2_board

    row = {"projection": {"edge_vs_market_pct": 39.38, "side": "away"}}
    assert layer2_board._model_edge_for(row, "home") is None


def test_a_dropped_edge_falls_back_to_ev_not_to_zero():
    """EV alone cannot pick a side, but it cannot INVERT one either. Scoring a
    rejected row zero would rank it above genuinely negative rows."""
    from syndicate.features.shared.opportunity_signals import blended_score

    assert blended_score(ev_pct=None, model_edge=None) is None
