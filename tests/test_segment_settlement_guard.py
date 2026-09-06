"""A segment bet must never be graded off a whole-game actual.

WHY THIS FILE EXISTS
--------------------
The board spells a segment bet as TWO fields -- `market="totals"` plus
`segment="first5"` -- and every stage from `odds_book_quotes._KEY_FIELDS` down
to the `execution_ledger` row keeps them apart. The GRADERS then read `market`
alone. Measured 2026-09-05, before this guard: `bet_status_wnba` refused a
non-full segment and was the only resolver in the repo that did. mlb, ncaaf,
nfl and soccer each matched `"totals"`, took the whole-game combined score, and
would have settled a first-five-innings UNDER 3.5 against a nine-inning total
of 8 -- LOST, with confidence and with no log line.

That is the expensive direction. An ungraded bet appears in the work list; a
mis-graded one appears in the P&L as skill.

WHAT THESE TESTS ARE BUILT TO CATCH, AND WHAT THEY ARE NOT
----------------------------------------------------------
They assert the REFUSAL, per sport, at the resolver's own entry point -- not
against a helper the resolver happens to call, because the defect was precisely
that the resolvers did not call one. `test_the_guard_is_load_bearing_*` is the
mutation check: it re-runs the same order with the guard neutralised and asserts
the row DOES grade, so a test that passes because the resolver refused for some
unrelated reason cannot read as success. Without that pair, a resolver that
refuses everything would look perfect here.

The full-game cases are not padding. A false positive in this guard refuses the
ENTIRE BOOK -- every order ever written carries no `segment` key at all -- which
is a worse outcome than the defect being fixed, and is the failure
`kalshi_catalogue` records having paid for once.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.bet_status import (
    FULL_GAME_SEGMENT,
    REASON_SEGMENT_PREFIX,
    segment_refusal,
)


# --------------------------------------------------------------------------
# The shared helper, on its own.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("segment", ["h1", "h2", "q1", "q2", "q3", "q4", "first1", "first3", "first5", "p1"])
def test_every_segment_in_the_platform_vocabulary_refuses(segment):
    """`market_segments.SPORT_SEGMENTS` is the source of these names.

    Parametrised over the real vocabulary rather than one example, because the
    guard's whole job is to be indifferent to WHICH segment it was handed --
    the enumeration that stood in `kalshi_catalogue._SEGMENT_MARKERS` failed
    exactly by being a list of the spellings somebody thought of.
    """
    out = segment_refusal({"market": "totals", "segment": segment})
    assert out is not None
    assert out["unavailable_reason"] == f"{REASON_SEGMENT_PREFIX}{segment}"


def test_the_vocabulary_this_asserts_is_the_one_the_fetchers_request():
    """Pin the parametrisation above to the shared map, so a segment added to
    `market_segments` cannot quietly go untested here."""
    from syndicate.features.shared.market_segments import SPORT_SEGMENTS

    every = {seg for segs in SPORT_SEGMENTS.values() for seg in segs}
    for segment in every:
        assert segment_refusal({"segment": segment}) is not None, segment


@pytest.mark.parametrize("value", [None, "", "  ", "full", "FULL", " Full "])
def test_absent_blank_and_full_all_grade(value):
    """THE PERMISSIVE DIRECTION, and the one this guard is allowed to take.

    Every full-game order in the ledger's history carries no `segment` key --
    the field was added for the board's quote rows, never retrofitted. Refusing
    on absence would refuse the whole book rather than the segment rows.
    """
    order = {"market": "totals"} if value is None else {"market": "totals", "segment": value}
    assert segment_refusal(order) is None


def test_a_non_mapping_does_not_raise_into_the_settlement_loop():
    assert segment_refusal(None) is None
    assert segment_refusal("not-an-order") is None


def test_full_game_segment_is_what_normalize_segment_produces():
    """One vocabulary, not two. `market_segments.normalize_segment` is what the
    capture side writes; this guard is what the grading side reads."""
    from syndicate.features.shared.market_segments import normalize_segment

    assert normalize_segment(None) == FULL_GAME_SEGMENT
    assert normalize_segment("") == FULL_GAME_SEGMENT


def test_the_wnba_wording_is_preserved_for_its_recorded_reading():
    """`final_box_is_full_game_not_<seg>` is quoted in `state_basketball.md`.
    Unifying it away would orphan that reading."""
    out = segment_refusal({"segment": "first_half"}, reason_prefix="final_box_is_full_game_not_")
    assert out["unavailable_reason"] == "final_box_is_full_game_not_first_half"


# --------------------------------------------------------------------------
# Every resolver, at its own entry point.
# --------------------------------------------------------------------------

# (module, factory, the sport token the resolver gates on)
_RESOLVERS = [
    ("bet_status_ncaaf", "ncaaf_status_resolver", "ncaaf"),
    ("bet_status_nfl", "nfl_status_resolver", "nfl"),
    ("bet_status_mlb", "mlb_status_resolver", "mlb"),
    ("bet_status_soccer", "soccer_status_resolver", "soccer"),
    ("bet_status_wnba", "wnba_status_resolver", "wnba"),
]


def _resolver(module_name, factory_name):
    import importlib

    mod = importlib.import_module(f"syndicate.features.shared.{module_name}")
    return mod, getattr(mod, factory_name)("2026-09-05")


def _segment_order(sport, segment="h1"):
    """A totals order that WOULD match each resolver's game-total market set.

    `market="totals"` is the point: it is the canonical name the board emits for
    a segment total, so this order is exactly the shape that used to be graded
    against the whole game.
    """
    return {
        "sport": sport,
        "market": "totals",
        "segment": segment,
        "side": "under",
        "line": 24.5,
        "home_team": "Ohio State",
        "away_team": "Texas",
        "event_id": "seg-guard-1",
    }


@pytest.mark.parametrize("module_name,factory_name,sport", _RESOLVERS)
def test_a_segment_order_refuses_in_every_sport(module_name, factory_name, sport):
    _mod, resolve = _resolver(module_name, factory_name)
    out = resolve(_segment_order(sport))

    reason = str((out or {}).get("unavailable_reason") or "")
    assert reason, f"{sport}: graded a segment order instead of refusing -- {out}"
    assert reason.endswith("_h1"), f"{sport}: refused for the wrong cause -- {reason}"
    assert "full_game_not" in reason or reason.startswith(REASON_SEGMENT_PREFIX), reason
    # And the refusal must be a REFUSAL, not a graded row wearing one.
    assert (out or {}).get("current_value") is None, out


@pytest.mark.parametrize("module_name,factory_name,sport", _RESOLVERS)
def test_the_guard_is_load_bearing_not_incidental(monkeypatch, module_name, factory_name, sport):
    """MUTATION CHECK, and the reason the test above can be believed.

    A resolver that refuses EVERYTHING would pass the assertion above while
    proving nothing. Neutralise the guard and the very same order must reach a
    DIFFERENT outcome -- either it grades, or it refuses for a different,
    non-segment cause. If the outcome is identical with the guard disabled, the
    guard is not what produced it.

    This is the check `learnings.md` asks for by name: a test whose fixture
    cannot violate the property it asserts is zero coverage that reads as
    strong.
    """
    mod, _ = _resolver(module_name, factory_name)
    assert hasattr(mod, "segment_refusal"), f"{sport}: resolver does not import the shared guard"

    with_guard = _resolver(module_name, factory_name)[1](_segment_order(sport))
    monkeypatch.setattr(mod, "segment_refusal", lambda *a, **k: None)
    without_guard = _resolver(module_name, factory_name)[1](_segment_order(sport))

    assert with_guard != without_guard, (
        f"{sport}: disabling the guard changed nothing, so the refusal above "
        f"was produced by something else -- {with_guard}"
    )
    assert str((without_guard or {}).get("unavailable_reason") or "").find("_h1") == -1, (
        f"{sport}: still refusing on the segment with the guard disabled -- "
        f"a second copy of this check exists somewhere and the two can drift"
    )


@pytest.mark.parametrize("module_name,factory_name,sport", _RESOLVERS)
def test_a_full_game_order_is_not_refused_by_this_guard(module_name, factory_name, sport):
    """The false-positive direction. A whole-game order may still fail to grade
    -- no artifact for the date, an unmapped market, a team that will not
    resolve -- but it must NEVER fail with a SEGMENT reason."""
    _mod, resolve = _resolver(module_name, factory_name)

    for order in (_segment_order(sport, segment="full"), {k: v for k, v in _segment_order(sport).items() if k != "segment"}):
        out = resolve(order) or {}
        reason = str(out.get("unavailable_reason") or "")
        assert "full_game_not" not in reason, f"{sport}: whole-game order refused as a segment -- {reason}"
        assert not reason.startswith(REASON_SEGMENT_PREFIX), f"{sport}: {reason}"
