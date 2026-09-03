"""The board must say when its own sim points the other way -- and must never
say a number it does not have.

Every case here is pinned to a reading off the SERVED production board
(`/api/intelligence/query`, 2026-09-03), not to a fixture someone invented, so a
failure means the board changed rather than that a test got stale.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import layer2_board as lb


# --------------------------------------------------------------------------
# The team-name framing. Three producers write the home team's NAME into
# `projection["side"]` while the row's own side is "home"/"away", and a bare
# string compare negated BOTH sides of every such market.
# --------------------------------------------------------------------------

def _ncaaf_h2h_row(side: str, *, home_win_rate: float) -> dict:
    """Shaped exactly as `ncaaf/game_projections.py` builds it."""
    return {
        "home_team": "Illinois Fighting Illini",
        "away_team": "UAB Blazers",
        "side": side,
        "projection": {
            "model_prob_over": home_win_rate,
            # THE DEFECT'S SOURCE: a team NAME, not a side token.
            "side": "Illinois Fighting Illini",
            "basis": "smartsim2_home_win_rate",
        },
    }


def test_home_moneyline_gets_the_home_probability_not_its_complement():
    """Illinois at -2532 served `Win% 0.67%` while the sim said 99.33%."""
    row = _ncaaf_h2h_row("home", home_win_rate=0.9933)
    assert lb._model_prob_for_side(row) == pytest.approx(0.9933)


def test_away_moneyline_gets_the_complement():
    row = _ncaaf_h2h_row("away", home_win_rate=0.9933)
    assert lb._model_prob_for_side(row) == pytest.approx(0.0067)


def test_two_sides_of_one_market_no_longer_carry_the_same_number():
    """17 of 17 NCAAF h2h pairs were identical on the served board.

    This is the assertion that catches the bug WITHOUT knowing which direction
    it broke in: whatever the two sides are, they must sum to one.
    """
    home = lb._model_prob_for_side(_ncaaf_h2h_row("home", home_win_rate=0.65))
    away = lb._model_prob_for_side(_ncaaf_h2h_row("away", home_win_rate=0.65))
    assert home != away
    assert home + away == pytest.approx(1.0)


def test_model_edge_is_not_negated_on_the_side_the_projection_frames():
    """Same framing bug, the other consumer. WNBA/NFL carry a real
    `edge_vs_market_pct` here, so this one moves money-adjacent numbers."""
    row = {
        "home_team": "Las Vegas Aces",
        "away_team": "Seattle Storm",
        "projection": {
            "edge_vs_market_pct": 4.0,
            "model_prob_over": 0.61,
            "side": "Las Vegas Aces",
        },
    }
    assert lb._model_edge_for(row, "home") == pytest.approx(4.0)
    assert lb._model_edge_for(row, "away") == pytest.approx(-4.0)


def test_an_unplaceable_framing_is_dropped_rather_than_negated():
    """"Not equal" is not "opposite". A framing naming neither team is unknown,
    and an unknown must not silently become the complement."""
    row = {
        "home_team": "Las Vegas Aces",
        "away_team": "Seattle Storm",
        "projection": {
            "edge_vs_market_pct": 4.0,
            "model_prob_over": 0.61,
            "side": "Some Team That Is Not In This Game",
        },
    }
    assert lb._model_edge_for(row, "home") is None
    assert lb._model_prob_for_side(row, "home") is None


def test_prop_over_under_framing_still_negates():
    """The two-way identity is INTENDED between real opposites -- this is the
    control that proves the fix narrowed the negation instead of removing it."""
    row = {"projection": {"edge_vs_market_pct": 3.0, "model_prob_over": 0.58, "side": "over"}}
    assert lb._model_edge_for(row, "over") == pytest.approx(3.0)
    assert lb._model_edge_for(row, "under") == pytest.approx(-3.0)
    assert lb._model_prob_for_side(row, "under") == pytest.approx(0.42)


# --------------------------------------------------------------------------
# The direction contradiction itself.
# --------------------------------------------------------------------------

def _totals_row(side: str, line: float, projected: float) -> tuple[dict, dict]:
    projection = {"projected": projected, "side": "over", "basis": "smartsim2_total_mean"}
    return {"side": side, "line": line, "projected": projected, "projection": projection}, projection


def test_the_row_the_report_was_written_about_is_a_contradiction():
    """UMass @ Rutgers: line 53.5, pick UNDER, sim projects 67.803."""
    row, projection = _totals_row("under", 53.5, 67.803)
    assert lb._sim_direction_contradiction(row, projection) == pytest.approx(14.303)


def test_a_pick_that_agrees_with_the_projection_is_not_a_contradiction():
    row, projection = _totals_row("over", 51.5, 53.297)
    assert lb._sim_direction_contradiction(row, projection) is None


def test_a_gap_inside_the_noise_band_is_not_tagged():
    """0.5 points on a 53.5 line is 0.9% -- noise, and a tag on it is a tag
    nobody reads. 50% of NCAAF totals rows contradict at a zero threshold."""
    row, projection = _totals_row("under", 53.5, 54.0)
    assert lb._sim_direction_contradiction(row, projection) is None


def test_the_threshold_is_relative_so_one_number_can_serve_every_sport():
    """0.8 goals against a 2.5 total is 32% and must tag; the identical 0.8
    against a 53.5 total is 1.5% and must not. An absolute threshold cannot do
    both, which is why this one is a fraction of the line."""
    soccer, soccer_projection = _totals_row("under", 2.5, 3.3)
    ncaaf, ncaaf_projection = _totals_row("under", 53.5, 54.3)
    assert lb._sim_direction_contradiction(soccer, soccer_projection) == pytest.approx(0.8)
    assert lb._sim_direction_contradiction(ncaaf, ncaaf_projection) is None


def test_a_spread_is_refused_because_its_line_has_no_stated_side():
    """A guessed sign inverts the verdict while looking plausible."""
    row = {"side": "home", "line": -29.5, "projected": 12.0, "projection": {"projected": 12.0}}
    assert lb._sim_direction_contradiction(row, row["projection"]) is None


# --------------------------------------------------------------------------
# What the board publishes.
# --------------------------------------------------------------------------

def _publish(row: dict) -> dict:
    return lb._layer2_board_columns(row, {}, {})


def test_a_contradicted_row_with_no_priced_edge_is_tagged_not_silent():
    """The whole report in one assertion: `model_edge_pct` is null on 100% of
    NCAAF rows by design, so the older tag can never fire there."""
    columns = _publish(
        {
            "side": "under",
            "line": 53.5,
            "model_edge_pct": None,
            "projection": {"projected": 67.803, "side": "over", "basis": "smartsim2_total_mean"},
        }
    )
    assert columns["sim_view"] == "contradicts"
    assert columns["sim_line_gap"] == pytest.approx(14.303)
    assert columns["sim_view_basis"] == "projection_vs_line"


def test_no_projection_at_all_still_reports_none():
    """`contradicts` must never be manufactured out of an absent model --
    absent and contradicting are different states and this is the one that
    stays `none`."""
    columns = _publish({"side": "under", "line": 53.5, "model_edge_pct": None})
    assert columns["sim_view"] == "none"
    assert "sim_line_gap" not in columns


def test_a_priced_disagreement_still_wins_the_older_word():
    """`disagrees` is a claim about rating and outranks the direction fallback
    wherever a priced edge exists -- the fallback is a fallback."""
    columns = _publish(
        {
            "side": "under",
            "line": 53.5,
            "model_edge_pct": -3.2,
            "projection": {"projected": 67.803, "side": "over"},
        }
    )
    assert columns["sim_view"] == "disagrees"


def test_a_railed_probability_is_flagged_as_its_own_state():
    """`Win% 0%` beside a recommended moneyline is an instrument off-scale."""
    columns = _publish(
        {
            "side": "home",
            "home_team": "Rutgers Scarlet Knights",
            "away_team": "UMass Minutemen",
            "model_edge_pct": None,
            "projection": {"model_prob_over": 0.9995, "side": "Rutgers Scarlet Knights"},
        }
    )
    assert columns["sim_probability_railed"] is True
    assert columns["model_probability"] == pytest.approx(0.9995)


def test_an_ordinary_probability_is_not_flagged():
    columns = _publish(
        {
            "side": "home",
            "home_team": "Georgia Tech Yellow Jackets",
            "away_team": "Colorado Buffaloes",
            "model_edge_pct": None,
            "projection": {"model_prob_over": 0.65, "side": "Georgia Tech Yellow Jackets"},
        }
    )
    assert "sim_probability_railed" not in columns
    assert columns["model_probability"] == pytest.approx(0.65)


def test_win_percent_stays_blank_where_there_is_no_model():
    """`confidence` is the Win% column. A row with no projection must publish
    NO confidence -- the book-count ladder wearing a percent sign is the defect
    this blank exists to prevent."""
    columns = _publish({"side": "under", "line": 53.5, "model_edge_pct": None})
    assert "confidence" not in columns


def test_the_state_backfill_no_longer_puts_book_breadth_in_the_win_percent_column():
    """`intelligence_state` used to `setdefault("confidence", book_confidence)`,
    which fired on EXACTLY the rows the blank above protects."""
    from pipeline import intelligence_state

    card = {"score_breakdown": {"book_confidence": 1.0, "score": 1.67}}
    intelligence_state._backfill_layer2_board_columns(card)
    assert "confidence" not in card
    assert card["book_confidence"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# `none` HAD TWO STATES IN IT, and naming the bucket printed the wrong one.
#
# USER-REPORTED 2026-09-03, minutes after the badge shipped: MLB rows labelled
# "no sim view" with a number in the PROJECTED column beside them. Measured the
# same minute on the served payload -- 16,284 rows, `sim_view: none` on 10,032,
# and 3,300 of those (32.9%) carrying a model number (ncaaf 2,364, mlb 732,
# soccer 204). The sim had a view; it could not be PRICED into an edge.
#
# Split at the SOURCE and not only in the renderer, because `sim_view` is about
# to be persisted onto orders for the ROI split. A field that conflates "no
# model" with "model, unpriced" makes that split wrong on its first day, and
# unlike a badge nobody would see it.
# ---------------------------------------------------------------------------


def test_a_model_with_no_priced_edge_is_UNPRICED_not_none():
    """The reported row, values copied off the served payload.

    Gap is 1.5 - 1.046 = 0.454 on a 1.5 line = 30% -- above the contradiction
    threshold -- so this row is `contradicts` once the direction fallback can
    see it. The point of THIS test is the one below it: the same shape without a
    qualifying gap must still not claim the sim was silent.
    """
    columns = _publish(
        {
            "side": "over",
            "line": 1.5,
            "model_edge_pct": None,
            "model_probability": 0.2407,
            "projection": {"projected": 1.046, "side": "over"},
        }
    )
    assert columns["sim_view"] in {"contradicts", "unpriced"}
    assert columns["sim_view"] != "none", "the sim projected 1.046 -- it was not silent"


def test_a_model_that_AGREES_in_direction_but_cannot_be_priced_is_unpriced():
    """THE DISCRIMINATING CASE. The direction fallback returns None here --
    the sim points the SAME way as the pick -- so before this split the row fell
    through to `none` and was published as "the sim has no view", while carrying
    a projection of 2.4 against a 1.5 line."""
    columns = _publish(
        {
            "side": "over",
            "line": 1.5,
            "model_edge_pct": None,
            "projection": {"projected": 2.4, "side": "over"},
        }
    )
    assert columns["sim_view"] == "unpriced"
    assert "sim_line_gap" not in columns, "nothing contradicts here"


def test_a_model_probability_alone_is_enough_to_count_as_a_view():
    """A moneyline has no line to contradict, so the direction fallback can
    never speak for it -- but a `model_probability` is still a view."""
    columns = _publish({"side": "home", "market": "h2h", "model_edge_pct": None,
                        "model_probability": 0.62})
    assert columns["sim_view"] == "unpriced"


def test_genuinely_no_model_is_STILL_none():
    """The state the badge was built for. `unpriced` must not swallow it --
    absent is not the same as unpriced, and neither is agreement."""
    columns = _publish({"side": "under", "line": 53.5, "model_edge_pct": None})
    assert columns["sim_view"] == "none"


def test_a_projection_of_ZERO_is_a_view():
    """`0.0` is a real projection. A truthiness test would call it absent --
    the same class of bug `_as_optional_float` exists to prevent on the order
    side, where a real 0.0 edge must not read as "no model ran"."""
    columns = _publish({"side": "over", "line": 1.5, "model_edge_pct": None,
                        "projection": {"projected": 0.0, "side": "over"}})
    assert columns["sim_view"] in {"contradicts", "unpriced"}
    assert columns["sim_view"] != "none"
