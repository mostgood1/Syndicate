"""Asian handicap legs must share an anchor key even when spelled by club.

THE DEFECT, measured 2026-09-08 on
`soccer_source/eredivisie/api/odds/game_odds_current.csv`, grouped by
(away, home, line, book):

    Willem II @ AZ Alkmaar  line '-2.25'  sides=['AZ Alkmaar']   ONE SIDE
    Willem II @ AZ Alkmaar  line  '2.25'  sides=['Willem II']    ONE SIDE

    groups with BOTH sides:  2      groups with ONE side:  36

`AZ Alkmaar -2.25` and `Willem II +2.25` are the SAME market. `_canonical_line`
pairs such legs by flipping the home side's sign -- but it tested
`selection == "home"`, and soccer spells the home side as the CLUB. The flip
never fired, the legs landed under different anchor keys, and every soccer
spreads row reached the de-vig with one leg: **0 of 874 priceable over three
days**, all `no_two_sided_market_price`.

Only `line 0.0` worked, being its own mirror -- which is why this read as a
vocabulary problem for weeks rather than a sign problem.

THE OTHER HALF OF THIS FILE GUARDS `#262`, which is why `_canonical_line` exists
at all: `away +1.5 / home -1.5` and `away -1.5 / home +1.5` are DIFFERENT
markets and must keep different keys. An earlier implementation used
`abs(line)`, collapsed them, and lost one instance entirely. A fix for the
pairing bug that reintroduced that would be a worse trade.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.book_grid import (  # noqa: E402
    _canonical_line,
    _row_selection_is_home,
)


def row(selection, line, home_team=None, away_team="Willem II", sport="soccer"):
    return {"selection": selection, "line": line, "home_team": home_team,
            "away_team": away_team, "sport": sport}


class TestClubNamedLegsPair:
    def test_the_eredivisie_shape_now_shares_one_key(self):
        """The exact production rows. If these two disagree the market is split
        in half again and the de-vig sees one leg."""
        home = _canonical_line(row("AZ Alkmaar", -2.25, "AZ Alkmaar"))
        away = _canonical_line(row("Willem II", 2.25, "AZ Alkmaar"))
        assert home == away == pytest.approx(2.25)

    @pytest.mark.parametrize("line", [-0.25, -0.5, -0.75, -1.0, -2.25, -3.5])
    def test_every_quarter_and_half_line_pairs(self, line):
        assert _canonical_line(row("AZ Alkmaar", line, "AZ Alkmaar")) == pytest.approx(
            _canonical_line(row("Willem II", -line, "AZ Alkmaar")))

    def test_a_punctuated_club_name_still_resolves(self):
        """`teams_match`, not a string compare -- so `1. FC Köln` and friends
        resolve the way the rest of the platform resolves them."""
        assert _row_selection_is_home(
            row("1. FC Köln", -1.5, "1. FC Köln", sport="soccer")) is True


class TestNothingElseMoves:
    def test_literal_home_and_away_are_unchanged(self):
        assert _canonical_line(row("home", -1.5)) == pytest.approx(1.5)
        assert _canonical_line(row("away", 1.5)) == pytest.approx(1.5)

    def test_over_under_is_untouched(self):
        assert _canonical_line(row("over", 8.5)) == pytest.approx(8.5)
        assert _canonical_line(row("under", 8.5)) == pytest.approx(8.5)

    def test_an_UNRECOGNISED_selection_does_not_flip(self):
        """Conservative on purpose: an unknown token keeps today's behaviour
        rather than guessing that it means home."""
        assert _canonical_line(row("Some Other FC", -2.25, "AZ Alkmaar")) == pytest.approx(-2.25)

    def test_a_row_with_no_home_team_does_not_flip(self):
        """No home team is nothing to match against. It must not reach the
        matcher and must not guess."""
        assert _canonical_line(row("AZ Alkmaar", -2.25, None)) == pytest.approx(-2.25)

    def test_an_absent_line_stays_absent(self):
        assert _canonical_line(row("AZ Alkmaar", None, "AZ Alkmaar")) is None

    def test_an_empty_selection_is_not_home(self):
        assert _row_selection_is_home(row("", -1.5, "AZ Alkmaar")) is False


class TestIssue262IsStillHeld:
    """`_canonical_line` exists because `abs(line)` collapsed two real markets.
    The pairing fix must not undo that."""

    def test_mirrored_pairs_stay_DISTINCT_markets(self):
        plus = _canonical_line(row("Willem II", 1.5, "AZ Alkmaar"))     # away +1.5
        plus_home = _canonical_line(row("AZ Alkmaar", -1.5, "AZ Alkmaar"))  # home -1.5
        minus = _canonical_line(row("Willem II", -1.5, "AZ Alkmaar"))   # away -1.5
        minus_home = _canonical_line(row("AZ Alkmaar", 1.5, "AZ Alkmaar"))  # home +1.5
        assert plus == plus_home == pytest.approx(1.5)
        assert minus == minus_home == pytest.approx(-1.5)
        assert plus != minus, (
            "away+1.5/home-1.5 and away-1.5/home+1.5 are DIFFERENT markets; "
            "collapsing them is the bug #262 fixed")
