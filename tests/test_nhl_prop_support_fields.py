"""NHL prop projections publish the VOLUME and ROLE their producer already writes.

Measured 2026-10-16 on the served board: all **156** NHL prop rows carried no
support field at all, so the 15-point magnitude ceiling was the only gate
available -- the same hole NFL had.

WHY THESE FIELDS AND NOT A SAMPLE COUNT. The NFL version of this fix shipped
`sample_games` and step 2 then measured that it does NOT discriminate: in week 6
the median is 5.0 on BOTH sides of the ceiling, because it is a CALENDAR count,
not a volume one. The signal that did separate the populations was volume/role
(a projection far below its line). NHL's producer already writes exactly that,
and the index already holds it:

    proj_toi     364/364 populated, 76 distinct, 6.77..52.10 (median 17.30)
                 -> a real VOLUME signal, the one worth gating on
    line_slot    360/364, 7 distinct (the PP/even-strength unit)
                 -> a real ROLE signal; `line_refusal` already reads it
    sim_starter    4/364 -- sparse BY DESIGN, read only for code == "SAVES"
                 (goalies). Published for completeness, never as a gate.
    game_type    364/364 but CONSTANT ("regular") -> provenance, so a
                 postseason row can say so; not a discriminator

So the distribution was checked BEFORE publishing, which is the lesson the NFL
pass paid for.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.nhl.prop_projections import (  # noqa: E402
    NhlPropProjectionIndex,
    _norm,
    attach_nhl_prop_projections,
    line_refusal,
)

DATE = "2026-10-16"
#: A real context row's field set, as `prop_projections.py:217` stores it --
#: every value a string, because it comes straight from a CSV.
CTX = {"line_slot": "L1", "proj_toi": "17.30", "sim_starter": "", "game_type": "regular"}

HOME, AWAY = "New Jersey Devils", "New York Rangers"


def _grid_row(player="Jack Hughes", market="sog", line=2.5):
    return {
        "kind": "prop",
        "market": market,
        "player_name": player,
        "line": line,
        "side": "over",
        "home_team": HOME,
        "away_team": AWAY,
    }


def _attach(ctx=CTX, lam=3.1, market="sog", code="SOG", line=2.5,
            player="Jack Hughes"):
    key = (_norm(player), code)
    index = NhlPropProjectionIndex(date=DATE)
    # The producer writes FULL team names ("Colorado Avalanche"), and
    # `lookup` intersects them with the row's teams so a same-named player in
    # another game cannot price this row. Storing codes here would fail that
    # check and every test would report an unmatched player.
    index.by_key[key] = (_norm(HOME), _norm(AWAY), lam)
    if ctx is not None:
        index.context[key] = dict(ctx)
    row = _grid_row(player=player, market=market, line=line)
    coverage = attach_nhl_prop_projections([row], index, selected_date=DATE)
    return row.get("projection"), coverage


# ---------------------------------------------------------------------------
# the fields reach the published projection
# ---------------------------------------------------------------------------

def test_the_projection_publishes_volume_and_role():
    projection, _ = _attach()
    assert projection is not None
    assert projection["proj_toi"] == pytest.approx(17.30)
    assert projection["line_slot"] == "L1"
    assert projection["game_type"] == "regular"


def test_proj_toi_comes_from_the_CONTEXT_and_not_a_constant():
    """Reachability: off != on. A hard-coded value passes the test above."""
    a, _ = _attach({**CTX, "proj_toi": "6.77", "line_slot": "L4"})
    b, _ = _attach({**CTX, "proj_toi": "52.10", "line_slot": "PP1"})
    assert a["proj_toi"] == pytest.approx(6.77)
    assert b["proj_toi"] == pytest.approx(52.10)
    assert a["line_slot"] == "L4" and b["line_slot"] == "PP1"


def test_absent_volume_is_NONE_and_not_zero():
    """"No projected ice time recorded" and "projected zero minutes" are
    different claims. Mapping absent onto 0.0 is the permissive direction, and a
    consumer gating on volume would read a missing field as a benched player.
    """
    projection, _ = _attach({**CTX, "proj_toi": ""})
    assert projection["proj_toi"] is None

    zero, _ = _attach({**CTX, "proj_toi": "0"})
    assert zero["proj_toi"] == pytest.approx(0.0)
    assert zero["proj_toi"] is not None


def test_a_non_numeric_toi_is_refused_not_crashed():
    """It arrives as CSV text, so a bad cell must not break the whole join."""
    projection, coverage = _attach({**CTX, "proj_toi": "n/a"})
    assert projection["proj_toi"] is None
    assert coverage["rows_considered"] == 1


def test_an_empty_slot_publishes_NONE_rather_than_an_empty_string():
    projection, _ = _attach({**CTX, "line_slot": ""})
    assert projection["line_slot"] is None


# ---------------------------------------------------------------------------
# the hoist must not have changed the refusal
# ---------------------------------------------------------------------------

def test_line_refusal_is_UNCHANGED_by_the_context_hoist():
    """The fetch moved above the dict and now passes {} where it used to pass
    None. `line_refusal` does `ctx = context or {}`, so the two are identical --
    asserted rather than assumed, because a changed refusal would silently
    re-price rows.
    """
    assert line_refusal(None, "SOG") == line_refusal({}, "SOG")
    assert line_refusal(None, "SAVES") == line_refusal({}, "SAVES")


def test_a_row_with_NO_context_still_publishes_support_keys_as_none():
    """A refused row should still say what it knew. The keys must be present
    and None, not absent, so a consumer need not distinguish the two cases.
    """
    projection, _ = _attach(ctx=None)
    assert projection is not None
    for key in ("proj_toi", "line_slot", "sim_starter", "game_type"):
        assert key in projection, key
        assert projection[key] is None
    # and the refusal still fires, since no context means no game_type
    assert projection.get("probability_unavailable_reason")


def test_a_priced_row_keeps_its_probability_alongside_the_support():
    """The support must not displace the pricing: a slotted regular-season row
    still gets its probability and ladder.
    """
    projection, coverage = _attach()
    assert coverage["rows_with_probability"] == 1, coverage
    assert projection.get("model_prob_over") is not None
    assert projection.get("ladder")
    assert projection["proj_toi"] == pytest.approx(17.30)


def test_a_non_finite_toi_is_refused():
    """The branch mutation testing found untested.

    `float("inf")` and `float("nan")` SUCCEED, so they skip the except clause
    and reach the `math.isfinite` guard. A CSV cell of "inf" or "nan" must
    publish None, not an infinity that every downstream comparison silently
    mishandles. A mutant that turned this branch's None into 0.0 survived the
    first suite, which is what exposed the gap.
    """
    for bad in ("inf", "-inf", "nan"):
        projection, _ = _attach({**CTX, "proj_toi": bad})
        assert projection["proj_toi"] is None, bad
