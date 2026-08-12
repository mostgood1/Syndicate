"""`#384` -- the board de-vigged across bookmakers and called the result fair.

`_fair_by_side` took the BEST price on each side and de-vigged them together.
The best over and the best under routinely come from different books, so the
pair sums to less than any real market, and normalising that to 1.0 folds the
line-shopping gap into "fair value" -- which then subtracts it back out of the
EV it was supposed to measure.

Measured on the served board 2026-08-12: 29 of 52 two-sided groups drew their
sides from different bookmakers, and `edge == ev_vs_fair_pct` on 127 of 127
rows. Both sides of a market carried the SAME positive ev_pct, which is the
signature of an arb surplus rather than an edge -- a real edge cannot exist on
both sides at once.

`opportunity_signals.fair_probability_by_book` had documented exactly this in
its own docstring, and `consensus_fair_probability` -- the correct
implementation -- already existed and was used by neither board.
"""

from __future__ import annotations

from syndicate.features.shared.layer2_board import _fair_by_side


def _row(cells=None, best=None):
    row = {}
    if cells is not None:
        row["cells"] = cells
    if best is not None:
        row["best"] = best
    return row


def test_the_consensus_is_taken_per_book_not_across_best_prices():
    # Two books, each pricing both sides with a normal hold. The consensus must
    # come from de-vigging each book against ITSELF.
    cells = {
        "bookA": {"home": {"price": -110}, "away": {"price": -110}},
        "bookB": {"home": {"price": -105}, "away": {"price": -115}},
    }
    fair, method = _fair_by_side(_row(cells=cells), ["home", "away"])
    assert method == "consensus"
    assert abs(sum(fair.values()) - 1.0) < 1e-9, "fair probabilities must be a distribution"
    assert 0.45 < fair["home"] < 0.55


def test_a_cross_book_best_pair_no_longer_becomes_fair_value():
    """THE REGRESSION. bookA is best on home, bookB is best on away.

    Taking those two together de-vigs a pair that no single book ever offered.
    The old code returned `two_sided` here; nothing may now produce a fair value
    from a cross-book pair.
    """
    best = {
        "home": {"price": 120, "bookmaker": "bookA"},
        "away": {"price": 110, "bookmaker": "bookB"},
    }
    fair, method = _fair_by_side(_row(best=best), ["home", "away"])
    assert method != "two_sided", "a cross-book pair was de-vigged as if one book offered it"
    assert method in (None, "book_margin_model")
    assert not fair


def test_a_same_book_two_sided_pair_is_still_honoured():
    # Both sides from ONE book is a legitimate de-vig -- it must not be lost as
    # collateral damage from removing the cross-book path.
    best = {
        "home": {"price": -110, "bookmaker": "bookA"},
        "away": {"price": -110, "bookmaker": "bookA"},
    }
    fair, method = _fair_by_side(_row(best=best), ["home", "away"])
    assert method == "two_sided_same_book"
    assert abs(sum(fair.values()) - 1.0) < 1e-9


def test_a_book_quoting_one_side_cannot_anchor_the_consensus():
    # bookB quotes only `home`. A per-book de-vig has nothing to normalise
    # against there, so bookB must not contribute a 1.0-normalised "fair".
    cells = {
        "bookA": {"home": {"price": -110}, "away": {"price": -110}},
        "bookC": {"home": {"price": -108}, "away": {"price": -112}},
        "bookB": {"home": {"price": 5000}},
    }
    fair, method = _fair_by_side(_row(cells=cells), ["home", "away"])
    assert method == "consensus"
    assert 0.45 < fair["home"] < 0.55, "a one-sided longshot book moved the consensus"


def test_no_prices_yields_no_fair_value_rather_than_a_guess():
    fair, method = _fair_by_side(_row(cells={}), ["home", "away"])
    assert method is None
    assert not fair
