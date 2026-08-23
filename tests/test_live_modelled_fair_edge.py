"""`#539` `[USER DECISION 2026-08-23]`. A one-sided live market is priced against
the MODELLED fair — and only that case, only with a live probability.

WHY THIS EXISTS. `#538` established that soccer's live edge is zero because the
market genuinely has one side: MLS props, `Shots` 2,544 rows with **0** under
prices, ruled out as a parse bug (the price ladder is monotonic -250 -> +2000 with
zero favourites at 5.5+) and as a clobber (zero duplicate player/line/book keys).
A de-vig can never answer, so soccer's live tier would carry no number ever.

`soccer_projections._price_against_market` already prices one-sided markets this
way for PREGAME rows, and its comment says the path is deliberately NOT wired into
the live branch because "a modelled fair does not make a live PREGAME projection
priceable". Correct, and not this case: the probability here comes from the LIVE
RE-SIM, the distinction `live_edge_policy`'s own docstring draws.

THE REFUSAL TESTS ARE LENIENT ABOUT THE COUNTER KEY (`or 0`) and strict about
the FIELD. Asserting `== 0` made them fail against the pre-change file for a
missing counter rather than for a refusal that broke — failing for the wrong
reason, which misrepresents what a test covers. They guard a future widening,
not this change; only the four positive tests discriminate here.

WHAT THESE TESTS DEFEND is the narrowness. The risk of this change is not that it
fails to fire; it is that it fires somewhere it should not, putting a
weaker-evidence number where a reader expects a de-vig. So most of what follows
asserts a REFUSAL.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import live_projection_join as join
from syndicate.features.shared.book_margin_model import EDGE_FIELD as MODELLED_EDGE_FIELD


def _row(**over):
    row = {
        "sport": "soccer",
        "kind": "prop",
        "market": "player_shots",
        "player_name": "Asier Villalibre",
        "line": 1.5,
        "sides": ["over"],
        "game": {"state": "live"},
        "modelled_fair": {
            "over": {
                "fair_method": "book_margin_model",
                "fair_probability": 0.40,
                "basis": "measured_hold",
                "assumed_hold_pct": 6.5,
            }
        },
    }
    row.update(over)
    return row


# `attach_live_projections` takes the indexed REPORT, not a bare index -- it reads
# `indexed["index"]` and returns `supported: False` otherwise. My first fixture
# passed the raw dict and every assertion failed with `coverage.get(...) is None`,
# which is the tell: not a wrong answer, no answer at all.
def _indexed(**over):
    return {
        "index": _index(**over),
        "players_seen": {"asier villalibre"},
        "lines_by_player_market": {("asier villalibre", "player_shots"): {1.5}},
    }


def _index(**over):
    hit = {
        "live_prob_over": 0.62,
        "live_projection": 1.9,
        "model_prob_over": None,
        "actual_so_far": 0,
        "side": "over",
    }
    hit.update(over)
    return {("asier villalibre", "player_shots", 1.5): hit}


def _run(row=None, index=None, projection=None):
    grid = [dict(row or _row())]
    grid[0]["projection"] = projection if projection is not None else {
        "basis": "poisson_shots",
        "side": "over",
        # The one-sided marker the producer stamps before its own live return.
        "market_fair_unavailable_reason": "one_sided_quote",
    }
    coverage = join.attach_live_projections(grid, index if index is not None else _indexed())
    return grid[0].get("projection") or {}, coverage


def test_a_one_sided_live_row_is_priced_against_the_modelled_fair():
    """THE CHANGE. 0.62 live vs 0.40 modelled fair -> +22.0 points."""
    projection, coverage = _run()
    assert projection.get(MODELLED_EDGE_FIELD) == pytest.approx(22.0)
    assert coverage.get("rows_live_edged_modelled") == 1


def test_it_NEVER_writes_edge_vs_market_pct():
    """`book_margin_model` forbids mixing a modelled hold with a two-sided
    de-vig. A reader must be able to tell which claim they are looking at."""
    projection, _ = _run()
    assert projection.get("edge_vs_market_pct") is None
    assert "modelled fair" in (projection.get("edge_unavailable_reason") or "")


def test_it_is_counted_apart_from_edged():
    """A two-sided de-vig and a measured hold are different strengths of
    evidence; one total would let the weaker inflate the number the board is
    judged on."""
    _, coverage = _run()
    assert coverage.get("rows_live_edged") == 0
    assert coverage.get("rows_live_edged_modelled") == 1


def test_it_uses_the_LIVE_probability_not_the_pregame_one():
    """The entire justification. Against a pregame model this would be the
    live-edge leak `#340` fixed across three sports."""
    projection, _ = _run(index=_indexed(live_prob_over=0.90))
    assert projection.get(MODELLED_EDGE_FIELD) == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# The refusals. This change is dangerous by firing, not by staying quiet.
# ---------------------------------------------------------------------------


def test_it_refuses_when_the_devig_failed_for_ANY_OTHER_reason():
    """A substitute for a fair value that CANNOT exist -- not a fallback for one
    that went wrong. A two-sided market whose de-vig broke is our bug and must
    stay visible as a withhold."""
    projection, coverage = _run(projection={
        "basis": "poisson_shots", "side": "over",
        "market_fair_unavailable_reason": "consensus_present_devig_returned_none",
    })
    assert projection.get(MODELLED_EDGE_FIELD) is None
    assert (coverage.get("rows_live_edged_modelled") or 0) == 0


def test_it_refuses_a_row_with_no_pregame_projection():
    projection, coverage = _run(projection={"side": "over", "market_fair_unavailable_reason": "one_sided_quote"})
    assert projection.get(MODELLED_EDGE_FIELD) is None
    assert (coverage.get("rows_live_edged_modelled") or 0) == 0


def test_it_refuses_when_the_resim_produced_no_live_probability():
    """No live probability means we never reach the branch -- the row lands in
    `no_live_probability` above, which is the correct refusal."""
    projection, coverage = _run(index=_indexed(live_prob_over=None))
    assert projection.get(MODELLED_EDGE_FIELD) is None
    assert (coverage.get("rows_live_edged_modelled") or 0) == 0


def test_it_refuses_a_fair_that_is_not_a_book_margin_model_fair():
    """`modelled_fair_edge`'s own guard, asserted from this caller: a two-sided
    consensus arriving in that block would duplicate `edge_vs_market_pct` under a
    name that says it is modelled."""
    row = _row()
    row["modelled_fair"]["over"]["fair_method"] = "two_sided_consensus"
    projection, coverage = _run(row=row)
    assert projection.get(MODELLED_EDGE_FIELD) is None
    assert (coverage.get("rows_live_edged_modelled") or 0) == 0


def test_it_refuses_when_there_is_no_modelled_fair_at_all():
    row = _row()
    row.pop("modelled_fair")
    projection, coverage = _run(row=row)
    assert projection.get(MODELLED_EDGE_FIELD) is None


def test_an_already_decided_over_never_reaches_the_modelled_path():
    """A settled market has no price to beat, whichever fair is used. This
    refuses upstream in the same loop and must keep doing so."""
    projection, coverage = _run(index=_indexed(actual_so_far=3))
    assert projection.get(MODELLED_EDGE_FIELD) is None
    assert (coverage.get("rows_live_edged_modelled") or 0) == 0


def test_a_two_sided_row_still_takes_the_normal_devig_path():
    """The change must not touch the population that already worked."""
    projection, coverage = _run(projection={
        "basis": "poisson_shots", "side": "over", "market_fair_prob_over": 0.50,
    })
    assert projection.get("edge_vs_market_pct") == pytest.approx(12.0)
    assert projection.get(MODELLED_EDGE_FIELD) is None
    assert coverage.get("rows_live_edged") == 1
    assert coverage.get("rows_live_edged_modelled") == 0
