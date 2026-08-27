"""NCAAF's slate window must reach its own opening weekend.

`#588`. The window was 3 days while NCAAF's first games sat 3 days out and its
"week 1" spanned TEN (2026-08-29 to 09-07). The quote shards on disk start at
the openers, so a 3-day forward window from any anchor in the preceding week
ended ONE DAY SHORT, `quote_rows` came back empty, and
`layer2_shortlist` hit `if not quote_rows: continue` -- skipping the sport
BEFORE the enrichment loop.

Every downstream symptom followed from that one cut, and each looked like its
own bug:

    /api/board/game-chips?date=2026-08-29  ->  total=250  ncaaf=0
                                               {nfl: 16, soccer: 234}
    no PREGAME_PROJECTION_JOIN sport=ncaaf line at all
    VENUE_REPRICE sports=['mlb','nfl','soccer','wnba']  -- no ncaaf, so the
      Kalshi/Polymarket NCAAF quotes were missing for this reason too

NFL's own entry in this table was raised 5 -> 7 for the identical shape: a
width correct for where fixtures cluster, one day short of the slate that
mattered.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.layer1_board import resolve_window_dates, slate_window_days


def test_ncaaf_window_reaches_its_own_opening_saturday():
    """The measured failure, pinned as a date rather than a width.

    2026-08-29 is the opening Saturday and 2026-08-26 is a plausible anchor
    three days before it. At width 3 this returned 08-26..08-28 and missed.
    """
    window = resolve_window_dates("ncaaf", "2026-08-26", window="slate")
    assert "2026-08-29" in window, (
        f"NCAAF window {window[0]}..{window[-1]} does not reach the openers; "
        "quote_rows will be empty and the sport is skipped before enrichment"
    )


@pytest.mark.parametrize("anchor_offset", range(0, 7))
def test_every_anchor_in_the_week_before_reaches_the_openers(anchor_offset):
    """Not just the one anchor that happened to be live when this was found.

    The build's anchor moves with the date, so a width that works from one
    anchor and not another produces a sport that appears and disappears -- which
    is what happened here: an `sport=ncaaf` join line existed at 00:52Z and was
    gone by 02:12Z, and the vanishing read as a regression rather than a window.
    """
    opener = date(2026, 8, 29)
    anchor = opener - timedelta(days=anchor_offset)
    window = resolve_window_dates("ncaaf", anchor.isoformat(), window="slate")
    assert opener.isoformat() in window, f"anchor {anchor} misses the openers"


def test_ncaaf_matches_the_other_multi_day_sports():
    """The chosen value, stated as a relationship rather than a literal."""
    assert slate_window_days("ncaaf") == slate_window_days("nfl") == slate_window_days("soccer") == 7


def test_single_day_sports_are_untouched():
    """Widening one sport must not widen the daily ones.

    `#329` records 1,244 NFL rows starting 34-156 days out reaching a today
    board once already -- over-inclusion is not free.
    """
    for sport in ("mlb", "nba", "wnba", "nhl"):
        assert slate_window_days(sport) == 1
        assert resolve_window_dates(sport, "2026-08-26", window="slate") == ["2026-08-26"]


def test_the_window_is_forward_only():
    """A symmetric window would put settled games on a pregame board."""
    window = resolve_window_dates("ncaaf", "2026-08-26", window="slate")
    assert window[0] == "2026-08-26"
    assert window == sorted(window)


def test_ncaaf_does_not_reach_a_second_full_week():
    """7 rather than 10, so a today board does not carry most of week 2.

    NCAAF week 1 spans 08-29..09-07. A 10-day window from 08-29 would pull the
    09-05 slate -- 30 games -- onto the openers' board.
    """
    window = resolve_window_dates("ncaaf", "2026-08-29", window="slate")
    assert "2026-09-05" not in window, f"window {window[0]}..{window[-1]} reaches the next weekend"
