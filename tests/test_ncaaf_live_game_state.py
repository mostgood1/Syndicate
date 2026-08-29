"""Tests for the NCAAF board's ESPN live-state join.

MODELLED ON `tests/test_nfl_live_game_state.py`, and on its opening warning:
asserting that `attach_ncaaf_live_game_state` sets a field would only prove the
field is set. The defect this code fixes was NOT a wrong value -- it was a
field that no producer ever wrote, passing every test, on a board whose live
branch was therefore unreachable for the entire 2026 preseason.

So the tests that matter here are the NEGATIVE and JOIN ones:

  * an empty index must leave cards untouched (state unknown != nothing live)
  * a card whose ESPN ids are absent must not match anything
  * the ABBREVIATION join, which is what a naive implementation would reach
    for, must be shown to fail on this board's real data
  * `matched` must be readable separately from `live`/`final`

`test_abbreviation_join_would_have_failed` is the regression test for the
actual bug: it pins the measured fact that CFBD abbreviations are not ESPN's.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf.live_game_state import (  # noqa: E402
    attach_ncaaf_live_game_state,
    espn_team_id_from_logo,
    past_or_current_dates,
)


def _card(away_id: str, home_id: str, *, away_abbr: str = "AWY", home_abbr: str = "HOM") -> dict:
    return {
        "gamePk": f"1_{away_abbr}_{home_abbr}",
        "status": "Week 1",
        "away": {
            "abbr": away_abbr,
            "logo_url": f"https://a.espncdn.com/i/teamlogos/ncaa/500/{away_id}.png",
        },
        "home": {
            "abbr": home_abbr,
            "logo_url": f"https://a.espncdn.com/i/teamlogos/ncaa/500/{home_id}.png",
        },
    }


def _state(**overrides) -> dict:
    base = {
        "event_id": "401757000",
        "away_id": "153",
        "home_id": "2628",
        "away_abbr": "UNC",
        "home_abbr": "TCU",
        "in_progress": False,
        "final": False,
        "status": "",
        "start_time": "2026-08-29T16:00Z",
        "away_score": None,
        "home_score": None,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# The join key
# --------------------------------------------------------------------------


def test_espn_team_id_is_read_from_the_logo_url():
    assert espn_team_id_from_logo({"logo_url": "https://a.espncdn.com/i/teamlogos/ncaa/500/153.png"}) == "153"
    assert espn_team_id_from_logo({"logo_url": "https://a.espncdn.com/i/teamlogos/ncaa/500/2628.png"}) == "2628"


def test_espn_team_id_absent_is_none_not_a_guess():
    assert espn_team_id_from_logo({}) is None
    assert espn_team_id_from_logo({"logo_url": ""}) is None
    assert espn_team_id_from_logo({"logo_url": "https://example.com/crest.svg"}) is None
    assert espn_team_id_from_logo(None) is None


def test_abbreviation_join_would_have_failed():
    """The measured reason this joins on ids and not abbreviations.

    Left column is what the NCAAF board carries (CFBD), right is what ESPN
    sends, taken from the 2026-08-29 opener slate. NOT ONE MATCHES. A board
    joined on abbreviations would report every game pregame forever -- exactly
    the bug being fixed, with a green test suite over it.
    """
    measured = [
        ("NC", "UNC"), ("SJS", "SJSU"), ("NS", "NCSU"), ("VIR", "UVA"),
        ("JS", "JVST"), ("NDS", "NDSU"), ("SS", "SAC"), ("EM", "EMU"),
        ("NMS", "NMSU"), ("FS", "FSU"),
    ]
    assert not any(board == espn for board, espn in measured)


# --------------------------------------------------------------------------
# Absence -- the branch that made this defect invisible
# --------------------------------------------------------------------------


def test_empty_index_leaves_every_card_untouched():
    cards = [_card("153", "2628")]
    coverage = attach_ncaaf_live_game_state(cards, {})
    assert coverage == {"matched": 0, "live": 0, "final": 0, "games": 1, "index": 0}
    assert "live_state" not in cards[0]
    # The week label must survive: an unknown state is not a live one.
    assert cards[0]["status"] == "Week 1"


def test_card_without_espn_ids_does_not_match():
    card = {"status": "Week 1", "away": {"abbr": "NC"}, "home": {"abbr": "TCU"}}
    coverage = attach_ncaaf_live_game_state([card], {"153@2628": _state(in_progress=True)})
    assert coverage["matched"] == 0
    assert "live_state" not in card


def test_matched_is_reported_separately_from_live():
    """A join that worked on an all-pregame slate must not read as a dead join."""
    cards = [_card("153", "2628")]
    coverage = attach_ncaaf_live_game_state(cards, {"153@2628": _state()})
    assert coverage["matched"] == 1
    assert coverage["live"] == 0
    assert coverage["final"] == 0
    assert cards[0]["live_state"]["in_progress"] is False


# --------------------------------------------------------------------------
# The states themselves
# --------------------------------------------------------------------------


def test_live_game_carries_period_clock_and_score():
    cards = [_card("153", "2628")]
    coverage = attach_ncaaf_live_game_state(
        cards,
        {"153@2628": _state(in_progress=True, period=1, clock="10:07", status="10:07 - 1st Quarter",
                            away_score=3, home_score=0)},
    )
    assert coverage["live"] == 1
    live_state = cards[0]["live_state"]
    assert live_state["in_progress"] is True
    assert live_state["period"] == 1
    assert live_state["clock"] == "10:07"
    assert live_state["source"] == "espn_scoreboard"
    # Scores reach the side containers, where the card template reads them.
    assert cards[0]["away"]["score"] == 3
    assert cards[0]["home"]["score"] == 0
    # The constant week label must be replaced, or a live eyebrow reads
    # "Week 1" whenever period/clock are missing.
    assert cards[0]["status"] == "10:07 - 1st Quarter"


def test_final_game_is_final_not_live():
    cards = [_card("153", "2628")]
    coverage = attach_ncaaf_live_game_state(
        cards, {"153@2628": _state(final=True, status="Final", away_score=17, home_score=24)}
    )
    assert coverage["final"] == 1
    assert coverage["live"] == 0
    assert cards[0]["live_state"]["final"] is True
    assert cards[0]["status"] == "Final"


def test_pregame_keeps_its_week_label_and_gains_a_start_time():
    cards = [_card("153", "2628")]
    attach_ncaaf_live_game_state(cards, {"153@2628": _state()})
    # `shared_game_state.startTime` was null on all 51 cards, so the shared
    # contract could not sort or filter the slate by kickoff.
    assert cards[0]["startTime"] == "2026-08-29T16:00Z"
    assert cards[0]["status"] == "Week 1"


def test_pregame_score_is_never_stamped():
    """A 0-0 placeholder on an unstarted game must not reach the card."""
    cards = [_card("153", "2628")]
    attach_ncaaf_live_game_state(cards, {"153@2628": _state(away_score=None, home_score=None)})
    assert "score" not in cards[0]["away"]
    assert "score" not in cards[0]["home"]


# --------------------------------------------------------------------------
# Date bounding
# --------------------------------------------------------------------------


def test_only_dates_that_have_started_are_fetched():
    """An NCAAF week spans up to 10 days; a future date cannot be live."""
    week = ("2026-08-29", "2026-08-30", "2026-09-05", "2026-09-07")
    assert past_or_current_dates(week, today="2026-08-29") == ("2026-08-29",)
    assert past_or_current_dates(week, today="2026-09-05") == ("2026-08-29", "2026-08-30", "2026-09-05")


def test_malformed_and_duplicate_dates_are_dropped():
    assert past_or_current_dates(["", None, "2026-08-29", "2026-08-29", "garbage"], today="2026-08-29") == (
        "2026-08-29",
    )
    assert past_or_current_dates(None, today="2026-08-29") == ()
