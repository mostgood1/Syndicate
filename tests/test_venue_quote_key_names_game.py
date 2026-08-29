"""`#603`: a game-market quote key must name the GAME.

`venue_quote_adapters.quote_key` is `sport|market|side|line`. For a totals row
that is `mlb|totals|over|7.5` — and EVERY live MLB game with a 7.5 total asks
for that one key, against a pool scoped to the whole sport
(`venue_quote_fanin`, `quotes_for_sport`). So one venue quote answers all of
them.

MEASURED IN PRODUCTION 2026-08-29 ~22:3xZ, board `written_at 21:56:11Z`:
**26 of 28 live Polymarket totals quotes on the board were shared across
games.**

    over  7.5 @ -400   AZ@SF, COL@ATL, HOU@NYM, SD@TB   (four games at once)
    over  8.5 @ +1233  three games
    over  9.5 @ +1900  three games
    over 10.5 @ -6567  two games

THE IMPOSSIBILITY THAT PROVES IT IS A DEFECT AND NOT A MARKET: COL@ATL was
1 run in the 7th, so over 7.5 was worth ~2% (Kalshi quoted 0.08). SD@TB was
13 runs, so over 7.5 had ALREADY WON — 100%. Both carried `-400` (=80%). One
price cannot be both.

`best_any_book` was `polymarket` on 28 of 28 of those rows, so the cross-game
quote is what the board presents as the best available price.

--------------------------------------------------------------------------
THIS IS THE SAME FIX PROPS ALREADY GOT, ONE MARKET FAMILY OVER
--------------------------------------------------------------------------

`prop_quote_key` exists because every player's anytime-scorer row keyed to the
single string `soccer|player_goal_scorer_anytime|yes` and "rows that share a
key are indistinguishable here: the first wins, and the quote it wins describes
a different human." Identical shape: rows that share a key are
indistinguishable, and the quote one wins describes a different GAME.

`_candidate_keys` returns the prop key ALONE, "with no player-blind fallback",
because "the blind key would still be tried and would still hit someone else's
quote." The same reasoning applies here and these tests encode it: a
game-market key must not fall back to a game-blind one. Coverage may be traded
for certainty; a PRICE may not.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.venue_quote_fanin import _candidate_keys


def _row(event_id, away, home, market="totals", side="over", line=7.5):
    return {
        "event_id": event_id,
        "away_team": away,
        "home_team": home,
        "market": market,
        "side": side,
        "line": line,
    }


COL_ATL = _row("evt-col-atl", "Colorado Rockies", "Atlanta Braves")
SD_TB = _row("evt-sd-tb", "San Diego Padres", "Tampa Bay Rays")


def test_two_games_with_the_same_total_do_not_share_a_key():
    """THE DEFECT. Two different games, same market/side/line.

    In production these two carried an identical `-400` while one was worth
    ~2% and the other had already won. They must not ask for the same key.
    """
    col = _candidate_keys(COL_ATL, "mlb")
    sd = _candidate_keys(SD_TB, "mlb")
    assert col, "COL@ATL produced no key at all"
    assert sd, "SD@TB produced no key at all"
    assert not (set(col) & set(sd)), (
        "a totals key is shared between two different games:\n"
        f"  COL@ATL -> {col}\n  SD@TB   -> {sd}\n"
        "One venue quote will answer both, and in production it did."
    )


def test_spreads_are_the_same_defect_and_must_also_name_the_game():
    """Spreads have no game term either, and `#603` measured 2 of 14 keys
    spanning more than one SEGMENT on top of that."""
    a = _candidate_keys(_row("evt-a", "Team A", "Team B", market="spreads", side="home", line=-1.5), "mlb")
    b = _candidate_keys(_row("evt-c", "Team C", "Team D", market="spreads", side="home", line=-1.5), "mlb")
    assert not (set(a) & set(b)), f"spreads key shared across games: {a} vs {b}"


def test_the_same_game_still_keys_consistently():
    """The fix must not make a row unmatchable against ITSELF.

    Two reads of the same row — the board's and the venue's, or two ticks —
    must produce the same key, or the join stops working entirely rather than
    stopping working wrongly.
    """
    first = _candidate_keys(COL_ATL, "mlb")
    second = _candidate_keys(dict(COL_ATL), "mlb")
    assert first == second


def test_different_lines_on_the_same_game_stay_distinct():
    """The property `quote_key`'s docstring already protects, kept intact:
    'a spread at -1.5 and the same spread at -2.5 are different bets'."""
    a = _candidate_keys(_row("evt-x", "Team A", "Team B", line=7.5), "mlb")
    b = _candidate_keys(_row("evt-x", "Team A", "Team B", line=8.5), "mlb")
    assert not (set(a) & set(b))


def test_different_sides_on_the_same_game_and_line_stay_distinct():
    over = _candidate_keys(_row("evt-x", "Team A", "Team B", side="over"), "mlb")
    under = _candidate_keys(_row("evt-x", "Team A", "Team B", side="under"), "mlb")
    assert not (set(over) & set(under))


def test_no_game_blind_fallback_key_is_offered():
    """The property that makes this a FIX rather than a preference.

    `_candidate_keys` tries every key it returns and takes the first hit. If a
    game-blind key remains in the list, the game-qualified key simply misses
    and the blind one still wins another game's quote — the bug intact, with a
    more complicated key list. `prop_quote_key` returns ALONE for exactly this
    reason.
    """
    keys = _candidate_keys(COL_ATL, "mlb")
    assert "mlb|totals|over|7.5" not in keys, (
        "the game-blind key is still offered as a fallback; it will still match"
        " another game's quote whenever the qualified key misses"
    )


def test_a_row_that_cannot_name_its_game_yields_no_key_rather_than_a_blind_one():
    """An unnameable game must go UNMATCHED, keeping its own (absent) price.

    Same discipline as the prop path: 'An unnameable player yields NO key. The
    row goes unmatched and keeps its own age, which is the honest outcome; a
    blind key here would launder someone else's freshness onto it.'
    """
    nameless = {"market": "totals", "side": "over", "line": 7.5}
    keys = _candidate_keys(nameless, "mlb")
    assert keys == [] or all("totals|over|7.5" != k for k in keys), (
        f"a row with no game identity still produced a usable key: {keys}"
    )


def test_explicit_venue_quote_key_still_wins():
    """The escape hatch stays: a row carrying its own key is authoritative."""
    row = dict(COL_ATL)
    row["venue_quote_key"] = "explicit|key"
    assert _candidate_keys(row, "mlb") == ["explicit|key"]
