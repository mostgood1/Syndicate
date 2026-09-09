"""The forward-date widening is not a fact about soccer, and the sport that
needs it next is NCAAF -- but opening that gate does NOT yet buy a match.

--------------------------------------------------------------------------
WHAT WAS MEASURED, 2026-09-09, PRODUCTION
--------------------------------------------------------------------------

`/api/portfolio/paper?date=2026-09-09` -> the Kalshi plan sized **11
positions, every one NCAAF, every one `price_source='aggregator'` with NO
`venue_ticker`**, matching that tick's
`PAPER2_PLAN_WRITTEN venue=kalshi ... venue_priced=781 placeable_committed=0/11`.
Their `commence_time`s are 2026-09-11/12, so every corresponding Kalshi market
refused in `_date_verdict` as `market_is_for_another_date` -- for no reason
except `sport != "soccer"`.

Kalshi lists them. `[kalshi_odds] BY_GAME_DATE` the same day, 2026-09-12:
`KXNCAAFGAME 182, KXNCAAFSPREAD 400, KXNCAAFTOTAL 400`, and a real title off
`[kalshi_odds] TITLE`:

    KXNCAAFTOTAL :: 'Over 77.5 points scored'
    ticker=KXNCAAFTOTAL-26SEP12UTUMONT-78

--------------------------------------------------------------------------
AND THE HONEST PART, WHICH IS WHY THIS FLAG SHIPS OFF
--------------------------------------------------------------------------

`canonical_team("ncaaf", ...)` returns **None for every NCAAF club** -- there
is no NCAAF alias map -- so `match_event_blob`'s resolver branch skips every
game and an NCAAF game line can only resolve if our board happens to spell a
club exactly as Kalshi's ticker blob does. It does not; the board carries
`'South Florida Bulls'`, the blob is `USFARMY`.

So this change moves NCAAF markets from `market_is_for_another_date` to
`event_not_on_our_board`. That is a REFUSAL WE CAN NAME replacing one we
could not act on -- and it populates the `unmatched_events` alias work list
with real NCAAF blobs, which is the only thing that can produce a correct
alias map. It is explicitly NOT a match-rate gain, and
`test_the_ALIAS_MAP_is_the_real_gate` pins that so nobody later reads this
lane as having delivered one.

A guessed club alias is how a bet lands on the wrong game (see
`match_event_blob`'s docstring). None are guessed here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import kalshi_board_join as kbj  # noqa: E402
from syndicate.features.shared.kalshi_board_join import (  # noqa: E402
    REASON_FORWARD_DATE_SPORT_OFF,
    join_kalshi_to_board,
)

SLATE = "2026-09-09"

# THE LITERAL TITLE AND TICKER PRODUCTION EMITTED, not a paraphrase. A guessed
# title is how a registration passes its own test and fails on the venue.
REAL_NCAAF_TICKER = "KXNCAAFTOTAL-26SEP12UTUMONT-78"
REAL_NCAAF_TITLE = "Over 77.5 points scored"


def _ncaaf_total(ticker=REAL_NCAAF_TICKER, title=REAL_NCAAF_TITLE):
    return {
        "ticker": ticker,
        "series": "KXNCAAFTOTAL",
        "title": title,
        "yes_american": -115,
        "no_american": -105,
    }


def _soccer_market(ticker="KXLALIGAGAME-26SEP15BARVAL-TIE"):
    return {
        "ticker": ticker,
        "series": "KXLALIGAGAME",
        "title": "Tie is the result",
        "yes_american": 120,
        "no_american": -140,
    }


def _mlb_market(ticker="KXMLBKS-26SEP10BACHAR-6"):
    return {
        "ticker": ticker,
        "series": "KXMLBKS",
        "title": "Lake Bachar: 6+ strikeouts?",
        "yes_american": -120,
        "no_american": 100,
    }


def _mlb_row():
    return {
        "sport": "mlb",
        "market": "strikeouts",
        "player_name": "Lake Bachar",
        "line": 5.5,
        "side": "over",
        "event_id": "evt-mlb-1",
        "quote": {"price": -110},
    }


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test states its own flag. An inherited value is how an `off != on`
    pair silently becomes `on != on`."""
    monkeypatch.delenv("SYNDICATE_KALSHI_FORWARD_DATE_SPORTS", raising=False)
    monkeypatch.delenv("SYNDICATE_KALSHI_SOCCER_FORWARD_DATES", raising=False)


# ---------------------------------------------------------------------------
# REACHABILITY FIRST: off != on. A widening tested only in its ON state cannot
# be told apart from a join that ignores its own switch.
# ---------------------------------------------------------------------------


def test_OFF_an_ncaaf_forward_market_refuses_on_the_SPORT_not_the_date():
    """The flag's own instrument. With NCAAF off the market is still refused --
    but under a reason that names the FLAG, so the population the flag governs
    is countable in production before anyone turns it on."""
    out = join_kalshi_to_board([_ncaaf_total()], [], selected_date=SLATE)
    assert out["reasons"].get(REASON_FORWARD_DATE_SPORT_OFF, 0) == 1
    assert out["reasons"].get("market_is_for_another_date", 0) == 0
    assert out["matched"] == 0


def test_ON_the_same_market_passes_the_date_gate(monkeypatch):
    """off != on, asserted on the same input. The refusal MOVES -- past the
    calendar and on to fixture identity, which is the next real question."""
    monkeypatch.setenv("SYNDICATE_KALSHI_FORWARD_DATE_SPORTS", "soccer,ncaaf")
    out = join_kalshi_to_board([_ncaaf_total()], [], selected_date=SLATE)
    assert out["reasons"].get(REASON_FORWARD_DATE_SPORT_OFF, 0) == 0
    assert out["reasons"].get("market_is_for_another_date", 0) == 0
    # It reached the event resolver, and was refused BY NAME there.
    assert out["reasons"].get("event_not_on_our_board", 0) == 1


def test_the_ALIAS_MAP_gate_is_OPEN_as_of_2026_09_09_and_the_flag_default_is_NOT():
    """REWRITTEN AT THE MOMENT ITS PREDECESSOR NAMED.

    This test used to pin the honest result that turning the flag on gained
    ZERO matched NCAAF rows, because `canonical_team('ncaaf', ...)` resolved
    nothing -- and it said in its own docstring: "If someone later adds an
    NCAAF alias map this test fails and must be rewritten -- which is the
    correct moment to re-argue the flag's default."

    `team_aliases._ncaaf_alias_to_name` landed on 2026-09-09, so that moment is
    now and the clubs below resolve. **THE FLAG'S DEFAULT IS DELIBERATELY NOT
    RE-ARGUED HERE.** The two gates are independent: this one was the alias map
    and it is open; the forward-date gate is a separate decision with its own
    evidence, and the lane that opened the map explicitly did not touch it.
    The assertions below say exactly that and nothing more.

    Registry-dependent, and the skip says so rather than passing vacuously --
    a data-free tree resolves nothing and would look like the old world.
    """
    from syndicate.features.shared.team_aliases import canonical_team

    try:
        from syndicate.features.ncaaf.oddsapi_lines import fbs_canonical_names

        registry = bool(fbs_canonical_names())
    except Exception:
        registry = False
    if not registry:
        pytest.skip(
            "ncaaf_team_registry_snapshot.csv absent (data/ is excluded from session "
            "worktrees) -- this assertion did NOT run"
        )

    for club in (
        "South Florida Bulls",
        "Army Black Knights",
        "USF",
        "ARMY",
        "Alabama Crimson Tide",
    ):
        assert canonical_team("ncaaf", club) is not None, club
    # ...and the control: sports that DO have a map still resolve.
    assert canonical_team("nfl", "Kansas City Chiefs") is not None
    # The FORWARD-DATE gate is untouched by that, and stays the second blocker.
    assert _forward_date_sports_default_is_soccer_only()


def _forward_date_sports_default_is_soccer_only() -> bool:
    """The flag's default with no env decision, read rather than assumed."""
    out = join_kalshi_to_board([_ncaaf_total()], [], selected_date=SLATE)
    return out["reasons"].get(REASON_FORWARD_DATE_SPORT_OFF, 0) == 1


# ---------------------------------------------------------------------------
# NOTHING ELSE MOVED. The default must be byte-identical to the old behaviour.
# ---------------------------------------------------------------------------


def test_ABSENT_means_soccer_exactly_as_before():
    """A deploy without an env decision is a no-op. Soccer keeps its widening."""
    out = join_kalshi_to_board([_soccer_market()], [], selected_date=SLATE)
    assert out["reasons"].get("market_is_for_another_date", 0) == 0
    assert out["reasons"].get(REASON_FORWARD_DATE_SPORT_OFF, 0) == 0


def test_the_ORIGINAL_soccer_kill_switch_still_speaks_only_for_soccer(monkeypatch):
    """`SYNDICATE_KALSHI_SOCCER_FORWARD_DATES=off` was set by somebody for one
    reason. Folding it into a blanket disable would silently re-scope it."""
    monkeypatch.setenv("SYNDICATE_KALSHI_SOCCER_FORWARD_DATES", "off")
    monkeypatch.setenv("SYNDICATE_KALSHI_FORWARD_DATE_SPORTS", "soccer,ncaaf")
    soccer = join_kalshi_to_board([_soccer_market()], [], selected_date=SLATE)
    assert soccer["reasons"].get(REASON_FORWARD_DATE_SPORT_OFF, 0) == 1
    ncaaf = join_kalshi_to_board([_ncaaf_total()], [], selected_date=SLATE)
    assert ncaaf["reasons"].get(REASON_FORWARD_DATE_SPORT_OFF, 0) == 0


@pytest.mark.parametrize("value", ["off", "none", "0"])
def test_the_list_can_disable_the_widening_entirely(monkeypatch, value):
    monkeypatch.setenv("SYNDICATE_KALSHI_FORWARD_DATE_SPORTS", value)
    out = join_kalshi_to_board([_soccer_market()], [], selected_date=SLATE)
    assert out["reasons"].get(REASON_FORWARD_DATE_SPORT_OFF, 0) == 1


def test_MLB_IS_NOT_WIDENED_AND_CANNOT_BE_BY_THIS_FLAG(monkeypatch):
    """THE SAFETY ARGUMENT, and it must survive a careless env value.

    MLB plays the SAME FIXTURE on consecutive days, so pricing tonight's game
    off tomorrow's market is a worse bug than the one being fixed. MLB has no
    entry in `_FORWARD_HORIZON_DAYS`, so naming it in the list buys nothing --
    asserted rather than assumed.
    """
    monkeypatch.setenv("SYNDICATE_KALSHI_FORWARD_DATE_SPORTS", "soccer,ncaaf,mlb")
    out = join_kalshi_to_board([_mlb_market()], [_mlb_row()], selected_date=SLATE)
    assert out["matched"] == 0
    assert (
        out["reasons"].get("market_is_for_another_date", 0)
        + out["reasons"].get("would_match_but_wrong_date", 0)
    ) == 1
    assert out["reasons"].get(REASON_FORWARD_DATE_SPORT_OFF, 0) == 0


def test_an_exact_date_match_is_unaffected():
    out = join_kalshi_to_board(
        [_mlb_market(ticker="KXMLBKS-26SEP09BACHAR-6")],
        [_mlb_row()],
        selected_date=SLATE,
    )
    assert out["matched"] == 1


# ---------------------------------------------------------------------------
# THE HORIZON IS A BOUND, AND THE NEW REASON MUST NOT SWALLOW WHAT IT CANNOT FIX
# ---------------------------------------------------------------------------


def test_BEYOND_the_horizon_is_the_DATE_reason_not_the_flag_reason():
    """`forward_date_sport_not_enabled` counts only what the flag would admit.
    A market a month out is not that population, and counting it there would
    make the reading that justifies the flag a lie."""
    far = _ncaaf_total(ticker="KXNCAAFTOTAL-26OCT12UTUMONT-78")
    out = join_kalshi_to_board([far], [], selected_date=SLATE)
    assert out["reasons"].get("market_is_for_another_date", 0) == 1
    assert out["reasons"].get(REASON_FORWARD_DATE_SPORT_OFF, 0) == 0


def test_a_market_BEFORE_the_slate_still_refuses_on_the_date(monkeypatch):
    """FORWARD ONLY, on every sport the list can name. A past market is settled
    or in progress; matching one prices a live row off a resolved contract."""
    monkeypatch.setenv("SYNDICATE_KALSHI_FORWARD_DATE_SPORTS", "soccer,ncaaf")
    stale = _ncaaf_total(ticker="KXNCAAFTOTAL-26SEP06UTUMONT-78")
    out = join_kalshi_to_board([stale], [], selected_date=SLATE)
    assert out["reasons"].get("market_is_for_another_date", 0) == 1
    assert out["reasons"].get(REASON_FORWARD_DATE_SPORT_OFF, 0) == 0


def test_the_NCAAF_horizon_is_a_WEEK_not_soccers_fortnight(monkeypatch):
    """A college club pair can legitimately recur across weeks, and
    `event_matches_two_games` would then be the only thing between us and a bet
    on the wrong game. Nine days out is past NCAAF's horizon and inside
    soccer's -- the one input that separates the two constants."""
    monkeypatch.setenv("SYNDICATE_KALSHI_FORWARD_DATE_SPORTS", "soccer,ncaaf")
    nine_days = _ncaaf_total(ticker="KXNCAAFTOTAL-26SEP18UTUMONT-78")
    out = join_kalshi_to_board([nine_days], [], selected_date=SLATE)
    assert out["reasons"].get("market_is_for_another_date", 0) == 1
    soccer_nine = join_kalshi_to_board(
        [_soccer_market(ticker="KXLALIGAGAME-26SEP18BARVAL-TIE")],
        [],
        selected_date=SLATE,
    )
    assert soccer_nine["reasons"].get("market_is_for_another_date", 0) == 0


# ---------------------------------------------------------------------------
# CORRECTNESS OF THE PAIRING THE WIDENING WOULD PRODUCE
# ---------------------------------------------------------------------------


def test_the_production_title_carries_the_HALF_POINT_line_already(monkeypatch):
    """THE OFF-BY-A-HALF CHECK, on the real string.

    A prop says `"7+"` and means Over 6.5. A game TOTAL does not: Kalshi's
    ticker suffix is `-78` while its title says `Over 77.5`, and the title is
    what the classifier reads. So the board's 77.5 is the SAME line, and no
    half-point shift may be applied. Getting this backwards would price every
    total against the neighbouring rung.
    """
    from syndicate.features.shared import kalshi_catalogue as kc

    out = kc.classify_market(
        {
            "ticker": REAL_NCAAF_TICKER,
            "title": REAL_NCAAF_TITLE,
            "series": "KXNCAAFTOTAL",
            "event_ticker": "KXNCAAFTOTAL",
        }
    )
    assert out["status"] == "ok"
    assert out["line"] == pytest.approx(77.5)
    assert out["side"] == "over"
    assert out["needs_event_identity"] is True
    assert REAL_NCAAF_TICKER.endswith("-78"), "the SUFFIX is the integer strike"


def test_a_widened_market_still_cannot_take_a_row_from_ANOTHER_fixture(monkeypatch):
    """`#603`: a quote that answers every fixture sharing a line is a
    spectacular and entirely fictional edge. The widening relaxes the CALENDAR
    and nothing else -- identity still runs, and an unrelated board row at the
    same line is refused."""
    monkeypatch.setenv("SYNDICATE_KALSHI_FORWARD_DATE_SPORTS", "soccer,ncaaf")
    other_fixture = {
        "sport": "ncaaf",
        "market": "totals",
        "line": 77.5,
        "side": "over",
        "event_id": "evt-someone-else",
        "away_team": "Rutgers Scarlet Knights",
        "home_team": "Boston College Eagles",
        "commence_time": "2026-09-12T19:30:00Z",
        "quote": {"price": -110},
    }
    out = join_kalshi_to_board(
        [_ncaaf_total()], [other_fixture], selected_date=SLATE
    )
    assert out["matched"] == 0
    assert out["reasons"].get("event_not_on_our_board", 0) == 1


def test_the_SEGMENT_guard_is_what_protects_the_dates_that_list_only_halves():
    """2026-09-11 carried ONLY `KXNCAAF1H*` for NCAAF while 09-12 carried the
    full-game families. Those 09-11 rows must keep refusing after the date gate
    opens -- and they do, on a real predicate rather than the date accident."""
    from syndicate.features.shared import kalshi_catalogue as kc

    assert kc.segment_for_series("KXNCAAF1HTOTAL") == "h1"
    assert kc.segment_for_series("KXNCAAFTOTAL") == "full"


def test_the_forward_sport_list_is_readable_without_running_a_join(monkeypatch):
    """The helper is the thing production reads; a test that only exercises it
    through the join cannot say whether an env value parsed."""
    monkeypatch.setenv("SYNDICATE_KALSHI_FORWARD_DATE_SPORTS", " NCAAF , soccer ")
    assert kbj._forward_date_sports() == frozenset({"ncaaf", "soccer"})
