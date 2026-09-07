"""Soccer's moneyline legs were the last raw Monte-Carlo certainty on the board.

`79149c94` published the Agresti-Coull point estimate instead of the raw `k/n`
across the platform, and it reached only the paths that go through
`live_gameline_join.price_moneyline`. Soccer's `h2h` / `h2h_3_way` legs do not:

  * the HOME leg's edge was `soccer_projections._price_against_market`'s
    `round((model_prob - fair) * 100.0, 2)` -- a bare subtraction;
  * the DRAW and AWAY legs' edges were `layer2_board._model_edge_for`'s
    `(model_prob - fair_prob) * 100.0` -- the same bare subtraction, in a
    different file.

Neither had an interval behind it, because neither had `n`: the projection dict
built by `_probability_projection` carried `model_prob_over` / `side` / `basis`
/ `source` and no sim count at all, while `adapters.py:104` had been writing
`"simulations"` onto every match output the whole time.

WHY THE DRAW LEG IS THE EXPOSED ONE. A draw is a NARROW outcome -- once a second
goal separates the sides `draws / n` genuinely reaches zero -- so `0/300` is
ordinary late in a match rather than a tail case. On the MLB live ledger for the
six days to 2026-09-06 the same shape produced 83 rows at exactly 0.0/1.0, 59 of
them priced, and two games LOST on a stated certainty (ARI 2 @ SF 7, BOS 2 @ NYY
9, both `p=0.0`, max |edge_pp| 46.2 and 55.9). An exact 0.0 that loses takes
Brier to its 1.0 ceiling and log loss to infinity.

REACHABILITY FIRST. The first two tests drive the REAL entrypoint
(`attach_soccer_projections`) over an artifact shaped like the producer's own
output, and assert the gate is ENTERED -- `off != on`. A fix behind a path
nothing reaches passes every assertion about its output.
"""

from __future__ import annotations

import math

from syndicate.features.shared.live_gameline_join import (
    REASON_NOT_PRICEABLE,
    REASON_UNUSABLE_SIMS,
    agresti_coull_point,
    prob_std_err,
)
from syndicate.features.shared.soccer_projections import (
    SoccerProjectionIndex,
    _norm_team,
    attach_soccer_projections,
)

SIMULATIONS = 300

#: A model far enough from the quote below to CLEAR the bar. At n=300 the
#: 2-sigma bar is ~5.3-5.7 pp across the middle of the range, so a disagreement
#: of ~14 pp is what a priceable soccer moneyline edge actually looks like. A
#: model that merely agrees with the market to within a point is exactly what
#: this gate exists to withhold -- see
#: `test_an_edge_inside_the_simulation_noise_is_withheld_by_name`.
PRICEABLE = {"home": 0.70, "draw": 0.18, "away": 0.12}


def _match(*, home: float, draw: float, away: float, simulations: object = SIMULATIONS):
    """One match output, shaped like `soccer/adapters.py::_match_output`.

    Only the keys this path reads are present, and `simulations` sits at the
    match level exactly where the adapter writes it -- not smuggled onto the
    projection, which is the thing under test.
    """
    payload = {
        "match_id": "m1",
        "league": "la_liga",
        "matchup": {"home_team": "Real Sociedad", "away_team": "Getafe"},
        "win_probability": {"home": home, "draw": draw, "away": away},
    }
    if simulations is not None:
        payload["simulations"] = simulations
    return payload


def _index(match):
    idx = SoccerProjectionIndex()
    idx.by_teams[(_norm_team("Real Sociedad"), _norm_team("Getafe"))] = match
    return idx


def _row(*, market="h2h_3_way", side="home", home_odds=-140, draw_odds=260, away_odds=420):
    """A board row with a REAL three-leg quote, so the de-vig is a real de-vig.

    The prices are independent of the model probabilities on purpose: a fixture
    that builds both sides of the comparison from one source proves nothing
    about a join.
    """
    return {
        "kind": "game",
        "market": market,
        "side": side,
        "segment": "full_game",
        "league": "la_liga",
        "home_team": "Real Sociedad",
        "away_team": "Getafe",
        "sides": ["home", "draw", "away"],
        "consensus": {"home": home_odds, "draw": draw_odds, "away": away_odds},
        "game": {"state": "pregame"},
    }


def _project(row, match):
    grid = [row]
    attach_soccer_projections(grid, _index(match))
    return grid[0].get("projection")


# --------------------------------------------------------------------------
# REACHABILITY -- is the new code entered at all, through the real entrypoint?
# --------------------------------------------------------------------------


def test_reachability_the_sim_count_reaches_the_projection():
    """`sims_run` is on the projection after the REAL attach, not just the helper.

    This is the plumbing the gate is built on. Before this change the projection
    dict had four keys and none of them was a count, so every gate below would
    have been unreachable no matter how it was written.
    """
    projection = _project(_row(), _match(home=0.55, draw=0.25, away=0.20))
    assert projection is not None, "the fixture must join, or nothing below tests anything"
    assert projection["sims_run"] == SIMULATIONS


def test_reachability_the_gate_changes_the_answer_off_versus_on():
    """`off != on`. The SAME probabilities, priced with and without a sim count.

    With no `n` there is no interval, so the row is refused by name; with one it
    is priced. If these two ever return the same thing the gate is inert, and
    every correctness assertion below would still pass.
    """
    on = _project(_row(), _match(**PRICEABLE))
    off = _project(_row(), _match(**PRICEABLE, simulations=None))

    assert "sims_run" not in off
    assert off["edge_vs_market_pct"] is None
    assert REASON_UNUSABLE_SIMS in off["edge_unavailable_reason"]

    assert on["edge_vs_market_pct"] is not None
    assert on["prob_std_err"] is not None
    assert on["edge_vs_market_pct"] != off["edge_vs_market_pct"]


# --------------------------------------------------------------------------
# THE ESTIMATOR
# --------------------------------------------------------------------------


def test_the_published_edge_is_built_from_the_smoothed_estimate():
    """The edge moves onto the Agresti-Coull centre, not the raw `k/n`.

    Checked as a RELATION to the raw arithmetic rather than a hard-coded
    constant, so the test still means something if the de-vig changes.
    """
    projection = _project(_row(), _match(**PRICEABLE))

    fair = projection["market_fair_prob_over"]
    raw_edge = (PRICEABLE["home"] - fair) * 100.0
    smoothed = agresti_coull_point(PRICEABLE["home"], SIMULATIONS)
    smoothed_edge = (smoothed - fair) * 100.0

    assert projection["edge_vs_market_pct"] == round(smoothed_edge, 2)
    assert projection["edge_vs_market_pct"] != round(raw_edge, 2)
    assert projection["point_estimator"] == "agresti_coull"


def test_the_smoothed_estimate_is_not_published_as_a_field():
    """It would SURVIVE `refuse_published_certainty` and contradict the row.

    That refusal runs on the line after `_price_against_market` and blanks a
    `model_prob_over` of exactly 0.0/1.0. It clears a fixed list of derived
    fields and cannot know about one this module invented, so a published
    smoothed value would sit at `0.0066` on a row whose probability was
    explicitly refused -- readable as a probability by anyone who found it.
    """
    projection = _project(_row(), _match(**PRICEABLE))
    assert "model_prob_over_smoothed" not in projection


def test_model_prob_over_keeps_its_raw_value():
    """The raw `k/n` stays put, and that is load-bearing, not conservatism.

    `prob_std_err` reconstructs `successes = p * n`. If the smoothed estimate
    were written back over `model_prob_over`, any later consumer that recomputes
    an interval from it -- `layer2_board._model_edge_for` does exactly that for
    the draw and away legs -- would apply add-two a second time and over-widen
    its own bar, silently withholding real edges.
    """
    projection = _project(_row(), _match(**PRICEABLE))
    assert projection["model_prob_over"] == PRICEABLE["home"]


def test_the_interval_is_computed_from_the_raw_probability():
    """Add-two applied ONCE. The stamped SE must match `prob_std_err(raw, n)`.

    Smoothing before the SE inflates it ~39% at the boundary, which reads as a
    tighter model rather than as a bug.
    """
    projection = _project(_row(), _match(**PRICEABLE))
    assert projection["prob_std_err"] == prob_std_err(PRICEABLE["home"], SIMULATIONS)
    assert projection["std_err_basis"] == "sim_count"


# --------------------------------------------------------------------------
# THE GATE
# --------------------------------------------------------------------------


def test_an_edge_inside_the_simulation_noise_is_withheld_by_name():
    """A model that agrees with the market gets no edge, and says why.

    The home price is chosen so the de-vigged fair lands within the 2-sigma bar
    of the model probability. Before this change the row published a small
    non-zero edge with nothing behind it.
    """
    # First find the fair this quote implies, then aim the model straight at it.
    fair = _project(_row(), _match(**PRICEABLE))["market_fair_prob_over"]
    aligned = _project(_row(), _match(home=round(fair, 4), draw=0.25, away=0.20))

    bar = 2.0 * prob_std_err(round(fair, 4), SIMULATIONS) * 100.0
    assert bar > 0.0
    assert aligned["edge_vs_market_pct"] is None
    assert REASON_NOT_PRICEABLE in aligned["edge_unavailable_reason"]


def test_the_home_legs_exact_certainty_was_ALREADY_covered_and_still_is():
    """MEASURED, not assumed: `refuse_published_certainty` gets there first.

    This corrects the premise this lane opened on. `attach_soccer_projections`
    calls that refusal on the line after `_price_against_market`, and it blanks
    a `model_prob_over` of exactly 0.0/1.0 and clears the derived edge. So the
    HOME leg's `0/300` was never the live certainty -- it was already refused,
    for a reason that has nothing to do with an interval.

    What was NOT covered is the draw and away legs, which that function does not
    look at. See `test_the_draw_leg_is_the_one_the_certainty_refusal_misses`.

    The interval is still computed and stamped here, which is what makes the two
    mechanisms distinguishable in the row rather than one silently masking the
    other.
    """
    projection = _project(_row(), _match(home=0.0, draw=0.30, away=0.70))

    assert projection["model_prob_over"] is None
    assert projection["model_prob_over_refused"] == "exact_certainty"
    assert projection["model_prob_over_refused_value"] == 0.0
    assert projection["edge_vs_market_pct"] is None
    assert projection["prob_std_err"] > 0.0, "Wald would be 0.0 here -- the whole bug"


def test_the_draw_leg_is_the_one_the_certainty_refusal_misses():
    """`refuse_published_certainty` reads `model_prob_over` and NOTHING ELSE.

    A `0/300` draw leg therefore reaches the board intact, as an exact 0.0, on a
    row whose home probability was fine. This pins the gap rather than asserting
    it away: the leg is priced downstream in `layer2_board._model_edge_for`,
    which is where the gate for it belongs and where `sims_run` now arrives.
    """
    projection = _project(_row(side="draw"), _match(home=0.70, draw=0.0, away=0.30))

    assert projection["model_prob_over"] == 0.70, "the home leg is not a certainty"
    assert projection["draw_probability"] == 0.0, "and the draw leg is, untouched"
    assert "model_prob_over_refused" not in projection
    # The input the downstream gate needs is present on the same row.
    assert projection["sims_run"] == SIMULATIONS
    assert not math.isclose(agresti_coull_point(0.0, SIMULATIONS), 0.0)


def test_the_refusal_still_stamps_an_interval_when_it_has_one():
    """A withheld row is diagnosable, not blank.

    `live_gameline_join`'s premise is that every zero is nameable. A refusal
    that leaves no interval behind is indistinguishable from a row nothing ever
    tried to price.
    """
    fair = _project(_row(), _match(**PRICEABLE))["market_fair_prob_over"]
    aligned = _project(_row(), _match(home=round(fair, 4), draw=0.25, away=0.20))
    assert aligned["edge_vs_market_pct"] is None
    assert aligned["prob_std_err"] is not None
    assert aligned["std_err_basis"] == "sim_count"


# --------------------------------------------------------------------------
# SCOPE -- what this change deliberately does NOT touch
# --------------------------------------------------------------------------


def test_a_distribution_based_basis_keeps_the_previous_arithmetic():
    """Totals are renormalised out of a scoreline distribution, not counted.

    They are not `k/n`, so add-two on them would be a mechanism change to a
    different estimator -- one that needs its own re-fit, per
    `model_engine_standard.md`. The omission is a decision; this pins it so a
    later reader does not "finish the job" by accident.
    """
    match = _match(**PRICEABLE)
    match["total_distribution"] = {"mean": 2.7, "over_2_5_probability": 0.62}
    row = _row(market="totals", side="over")
    row["sides"] = ["over", "under"]
    row["line"] = 2.5
    row["consensus"] = {"over": -110, "under": -110}

    projection = _project(row, match)
    assert projection["basis"] == "over_2_5_probability"
    assert "point_estimator" not in projection
    fair = projection["market_fair_prob_over"]
    assert projection["edge_vs_market_pct"] == round((0.62 - fair) * 100.0, 2)
