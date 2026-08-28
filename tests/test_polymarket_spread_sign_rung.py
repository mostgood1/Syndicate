"""The spread sign test must compare the rung the board is on.

LANE `venue-join-refusal-visibility`, 2026-08-28.

Polymarket lists a spread market PER SIDE PER LINE, so one fixture's ladder
spans both signs. `spread_sign_test` gave each fixture one vote and took it
from the first matching slug in slate order -- an arbitrary rung. Ten
production runs returned a rate pinned at a coin flip (0.44-0.60, n=9..22)
with every disagreement at the ladder extreme.

The verdict ladder maps ~0.5 to "FALSIFIED: the sign is not fixed per fixture.
Spreads must stay refused; do not ship a mapping on this." Only `n <
min_sample=30` was holding that back. These tests exist so a broken comparison
cannot write a durable wrong conclusion into the ledger again.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "audit_polymarket_coverage",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "audit_polymarket_coverage.py",
)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


DATE = "2026-08-28"


def _spread(slug):
    return {"slug": slug, "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD"}


def _board_row(line, side="home"):
    return {
        "market": "spreads",
        "side": side,
        "line": line,
        "sport": "mlb",
        "selected_date": DATE,
        "home_team": "Detroit Tigers",
        "away_team": "Los Angeles Dodgers",
    }


def test_the_vote_goes_to_the_rung_at_the_BOARDS_line_not_the_first_in_slate_order():
    """The real 2026-08-28 shape, and the reason the rate sat at 0.5.

    Board home line is +1.5. The venue's ladder carries `neg-2pt5` (listed
    first) and `pos-1pt5` (the comparable rung). Scoring the first one reports
    a DISAGREEMENT about a bet the board never asked for.
    """
    slate = [
        _spread(f"asc-mlb-lad-det-{DATE}-neg-2pt5"),
        _spread(f"asc-mlb-lad-det-{DATE}-pos-1pt5"),
    ]
    out = mod.spread_sign_test(slate, [_board_row(1.5)], min_sample=1, selected_date=DATE)
    assert out["fixtures_compared"] == 1
    assert out["agree_with_home_sign"] == 1, (
        "the +1.5 rung agrees with a +1.5 board line; the -2.5 rung is a different bet"
    )
    assert out["disagree"] == 0


def test_slate_ORDER_cannot_change_the_verdict():
    """The defect was order-dependence, so order is the thing to pin.

    An instrument whose answer depends on how the venue happened to sort its
    catalogue is not measuring the venue.
    """
    rungs = [
        _spread(f"asc-mlb-lad-det-{DATE}-neg-2pt5"),
        _spread(f"asc-mlb-lad-det-{DATE}-pos-1pt5"),
    ]
    forward = mod.spread_sign_test(rungs, [_board_row(1.5)], min_sample=1, selected_date=DATE)
    reverse = mod.spread_sign_test(
        list(reversed(rungs)), [_board_row(1.5)], min_sample=1, selected_date=DATE
    )
    assert forward["agreement_rate"] == reverse["agreement_rate"]


def test_a_fixture_with_no_rung_at_the_boards_line_is_COUNTED_NOT_SCORED():
    """"Nothing to compare" and "these disagreed" are different facts.

    Sharing one number is precisely what produced the 0.5. A fixture the venue
    quotes only at other lines must move `fixtures_no_comparable_rung` and must
    not move the rate in either direction.
    """
    slate = [_spread(f"asc-mlb-lad-det-{DATE}-neg-21pt5")]
    out = mod.spread_sign_test(slate, [_board_row(1.5)], min_sample=1, selected_date=DATE)
    assert out["fixtures_compared"] == 0
    assert out["fixtures_no_comparable_rung"] == 1
    assert out["agreement_rate"] is None


def test_an_unanimous_slate_still_reaches_a_real_verdict():
    """The fix must not make the question unanswerable in the other direction:
    when every comparable rung agrees, the audit must still be able to say so."""
    slate, board = [], []
    for i, (away, home) in enumerate(
        [("lad", "det"), ("hou", "nym"), ("bal", "ath"), ("pit", "stl")]
    ):
        slate.append(_spread(f"asc-mlb-{away}-{home}-{DATE}-pos-1pt5"))
        board.append(
            {
                "market": "spreads",
                "side": "home",
                "line": 1.5,
                "sport": "mlb",
                "selected_date": DATE,
                "home_team": home,
                "away_team": away,
            }
        )
    out = mod.spread_sign_test(slate, board, min_sample=1, selected_date=DATE)
    assert out["agreement_rate"] == 1.0
    assert "FALSIFIED" not in out["verdict"]


def test_a_fixture_carrying_BOTH_signs_is_not_scored_at_all():
    """The magnitude filter was necessary and NOT sufficient.

    MEASURED on the live slate 2026-08-28: 12 of 12 sampled MLB
    fixture/magnitude pairs carry BOTH `pos` and `neg`. Narrowing to the
    board's line leaves two rungs, one of each sign, so picking either is still
    arbitrary and the rate is still manufactured out of iteration order --
    which is exactly what production returned after the magnitude fix
    (rate=0.4706, n=17).
    """
    slate = [
        _spread(f"asc-mlb-lad-det-{DATE}-neg-1pt5"),
        _spread(f"asc-mlb-lad-det-{DATE}-pos-1pt5"),
    ]
    out = mod.spread_sign_test(slate, [_board_row(1.5)], min_sample=1, selected_date=DATE)
    assert out["fixtures_both_signs_present"] == 1
    assert out["fixtures_compared"] == 0
    assert out["agree_with_home_sign"] == 0 and out["disagree"] == 0


def test_the_verdict_says_NON_IDENTIFYING_not_UNDECIDED_and_never_FALSIFIED():
    """The trap, disarmed.

    UNDECIDED says "collect more"; here collecting more cannot help, because
    both legs exist at every line by construction. And the FALSIFIED branch
    fires at rate ~0.5 -- precisely what a non-identifying test returns -- so
    it was one sample away from recording a fact about the INSTRUMENT as a
    measurement about the VENUE.
    """
    slate = [
        _spread(f"asc-mlb-lad-det-{DATE}-neg-1pt5"),
        _spread(f"asc-mlb-lad-det-{DATE}-pos-1pt5"),
    ]
    out = mod.spread_sign_test(slate, [_board_row(1.5)], min_sample=1, selected_date=DATE)
    assert out["verdict"].startswith("NON-IDENTIFYING")
    assert "FALSIFIED" not in out["verdict"]
    assert "UNDECIDED" not in out["verdict"]
