"""Every NCAAF card builder must be able to build a card.

MEASURED 2026-08-27 on `origin/main`: `_build_ncaaf_card_contract` and
`_build_smartsim_ncaaf_card_contract` both passed a BARE `projection` to
`_ncaaf_shared_predictions_block`, and neither function binds that name. Every
call raised `NameError`. Only the third builder
(`_build_smartsim2_standalone_ncaaf_card_contract`) binds it, from
`row["projection"]`, which is why the defect survived review -- one of three
call sites was correct and the other two read identically.

WHY A SEPARATE FILE. The existing coverage test exercised these builders and
failed with the NameError, but it is about SLATE COVERAGE -- the failure looked
like a slate problem and says nothing about name binding. This file makes the
actual invariant explicit: a builder must not reference a name it does not
define, and a missing projection must DEGRADE to an empty block rather than
raise.
"""

from __future__ import annotations

import inspect

import pytest

from syndicate.features.ncaaf import cards


BUILDERS = [
    "_build_ncaaf_card_contract",
    "_build_smartsim_ncaaf_card_contract",
    "_build_smartsim2_standalone_ncaaf_card_contract",
]


@pytest.mark.parametrize("name", BUILDERS)
def test_the_builder_does_not_reference_an_unbound_projection(name):
    """Compile-level check: no builder may read a free `projection`.

    `co_names` holds names the function reads from an enclosing or global
    scope; `co_varnames` holds the ones it binds locally. A builder that reads
    `projection` without binding it is the exact defect, and this catches it
    without needing the fixture data that makes the builders hard to call.
    """
    func = getattr(cards, name)
    code = func.__code__
    bound = set(code.co_varnames) | set(code.co_cellvars) | set(code.co_freevars)
    assert not ("projection" in code.co_names and "projection" not in bound), (
        f"{name} reads a free `projection` it never binds"
    )


@pytest.mark.parametrize("name", BUILDERS)
def test_the_builder_calls_the_shared_predictions_helper(name):
    """The binding fix must not be achieved by deleting the call.

    Without this, dropping `predictions` entirely would pass the test above --
    and NCAAF would silently go back to publishing no projected score, spread
    or total, which is the bug the helper was written to fix.
    """
    src = inspect.getsource(getattr(cards, name))
    assert "_ncaaf_shared_predictions_block(" in src


def test_a_missing_projection_degrades_to_an_empty_block():
    """Absent stays absent -- never a fabricated neutral."""
    assert cards._ncaaf_shared_predictions_block(None) == {}


def test_a_projection_without_the_fields_yields_nulls_not_zeros():
    """A projection missing its means must publish None, not 0.0.

    `_safe_float(getattr(..., None))` is the mechanism; a zero here would read
    downstream as a real projected score of nothing.
    """

    class Empty:
        pass

    block = cards._ncaaf_shared_predictions_block(Empty())
    assert block["home_mean"] is None
    assert block["away_mean"] is None
    assert block["probabilities"]["home_win"] is None
    # Absent market lines must leave cover probabilities absent, not 0.5.
    assert block["probabilities"]["home_cover"] is None
    assert block["probabilities"]["total_over"] is None
