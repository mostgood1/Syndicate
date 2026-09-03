"""NCAAF: an FBS-vs-FCS game gets a scoreboard CHIP, but still no card.

WHY THIS EXISTS. Three places carried the identical `homeClassification ==
awayClassification == "fbs"` gate, and the one that mattered for display was a
mirror of the one that mattered for modelling. Consequence, reported by the user
on 2026-09-03: 7 of the 11 NCAAF games on the board had no chip at all, so their
cards rendered "Arkansas Pine Bluff Golden Lions @ Missouri Tigers" where every
other sport shows tri-codes, a score and a clock.

THE ASYMMETRY IS THE WHOLE DESIGN, and these tests exist to keep it. Measured
2026-09-03 on the real 2026 schedule:

  * classification data is complete -- 888 rows, ('fbs','fbs') 761 and
    ('fbs','fcs') 127, no nulls and no FCS home team;
  * all seven of that night's FCS visitors resolve in the team registry with a
    `team_id` and a logo, so the ESPN live-score join works for them;
  * the SmartSim 2.0 projection index for week 1 holds exactly 51 entries
    against exactly 51 FBS-vs-FBS games -- **the sim does not cover FCS
    opponents at all.**

So a chip (teams, kickoff, score) can widen and a card (which joins a
projection) cannot. Widening the card builder would manufacture cards with no
model behind them, which is worse than a full-name label.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf import sources as ncaaf_sources  # noqa: E402
from syndicate.features.ncaaf.sources import fbs_relevant  # noqa: E402

MODULE = ("syndicate.features.football.sim_engine.smartsim2.historical_truth"
          ".ncaaf_historical_loader.load_games_season")


def _row(week, away, home, start, away_cls="fbs", home_cls="fbs"):
    return {"week": week, "awayTeam": away, "homeTeam": home, "startDate": start,
            "awayClassification": away_cls, "homeClassification": home_cls}


# Two of 2026-09-03's real games: one FBS-vs-FBS that already worked, one
# FBS-vs-FCS that did not.
_SLATE = [
    _row(1, "Massachusetts", "Rutgers", "2026-09-03T22:00:00.000Z"),
    _row(1, "Arkansas-Pine Bluff", "Missouri", "2026-09-04T00:00:00.000Z", away_cls="fcs"),
]


def test_at_least_one_side_fbs_is_enough():
    assert fbs_relevant(_SLATE[0]) is True, "fbs vs fbs"
    assert fbs_relevant(_SLATE[1]) is True, "the game the user reported"
    assert fbs_relevant(_row(1, "A", "B", "x", away_cls="fbs", home_cls="fcs")) is True


def test_neither_side_fbs_is_not_on_this_board():
    assert fbs_relevant(_row(1, "A", "B", "x", away_cls="fcs", home_cls="fcs")) is False


def test_UNKNOWN_is_not_treated_as_fbs():
    """A guard that maps "I could not tell" onto its permissive branch turns a
    data gap into a silently relaxed rule. Nothing takes this branch today --
    the 2026 schedule has no null classifications -- so it is here to keep the
    direction of the failure fixed if the feed ever changes."""
    assert fbs_relevant(_row(1, "A", "B", "x", away_cls="", home_cls="")) is False
    assert fbs_relevant({"week": 1, "awayTeam": "A", "homeTeam": "B"}) is False
    assert fbs_relevant(None) is False
    assert fbs_relevant("not a row") is False


def test_the_fcs_game_now_earns_a_card_key():
    with patch(MODULE, return_value=_SLATE):
        resolved = ncaaf_sources.ncaaf_week_and_card_keys_for_date(2026, "2026-09-03")
    assert resolved is not None
    week, keys = resolved
    assert week == 1
    assert "1_Massachusetts_Rutgers" in keys
    assert "1_Arkansas-Pine_Bluff_Missouri" in keys, "the reported game"
    assert len(keys) == 2


def test_the_CARD_builder_still_refuses_the_fcs_game():
    """THE CONTROL, and the reason the two gates are no longer one.

    `_smartsim2_standalone_rows` joins a SmartSim 2.0 projection. The sim has no
    FCS rows, so widening here would build a card with nothing behind it. If a
    future change makes `fbs_relevant` the gate everywhere, this test is what
    fails.
    """
    from syndicate.features.ncaaf import cards as ncaaf_cards

    src = Path(ncaaf_cards.__file__).read_text(encoding="utf-8")
    body = src[src.index("def _smartsim2_standalone_rows("):]
    body = body[: body.index("\ndef ", 10)]
    assert 'homeClassification") != "fbs"' in body, (
        "the card builder must keep the both-sides-FBS gate -- the sim has no "
        "FCS projections"
    )
    assert "fbs_relevant" not in body, "cards must not adopt the chip gate"
