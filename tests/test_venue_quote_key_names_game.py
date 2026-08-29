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
    col_qualified = [k for k in col if "|@" in k]
    sd_qualified = [k for k in sd if "|@" in k]
    assert col_qualified and sd_qualified, (
        f"no game-qualified key offered:\n  COL@ATL -> {col}\n  SD@TB   -> {sd}"
    )
    assert not (set(col_qualified) & set(sd_qualified)), (
        "the game-qualified keys collide between two different games:\n"
        f"  COL@ATL -> {col_qualified}\n  SD@TB   -> {sd_qualified}"
    )
    # The BARE key IS still shared, deliberately, and the ROLE key stays first
    # (`test_the_role_key_is_still_tried_FIRST...` in the sibling suites asserts
    # that invariant with a measurement behind it). Dropping the fallback would
    # take venue coverage to zero on every source that cannot yet name its game.
    # What stops it being a hole is the rejection check, asserted in
    # `test_a_bare_key_match_on_a_DIFFERENT_game_is_rejected`. Pinned here so
    # the fallback's existence stays a DECISION rather than drifting back into
    # being the whole key.
    assert set(col) & set(sd) == {"mlb|totals|over|7.5"}


def test_spreads_are_the_same_defect_and_must_also_name_the_game():
    """Spreads have no game term either, and `#603` measured 2 of 14 keys
    spanning more than one SEGMENT on top of that."""
    a = _candidate_keys(
        _row("evt-a", "Colorado Rockies", "Atlanta Braves", market="spreads", side="home", line=-1.5),
        "mlb",
    )
    b = _candidate_keys(
        _row("evt-c", "San Diego Padres", "Tampa Bay Rays", market="spreads", side="home", line=-1.5),
        "mlb",
    )
    aq = [k for k in a if "|@" in k]
    bq = [k for k in b if "|@" in k]
    assert aq and bq, f"no game-qualified spreads key: {a} / {b}"
    assert not (set(aq) & set(bq)), f"qualified spreads key shared across games: {aq} vs {bq}"


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


def test_the_role_key_stays_first_and_the_qualified_key_is_offered_after_it():
    """Ordering is DELIBERATE, and it is not "most specific first".

    Putting the qualified key first broke eleven tests asserting "the role key
    is tried FIRST and unchanged, so every match that worked before still
    works" -- two of them assert `keys[1]`/`keys[2]` by POSITION. Ordering buys
    nothing here: the match loop rejects a quote naming a different fixture and
    falls through, so a bare hit on the wrong game lands on the qualified key on
    the next iteration anyway. So it is appended LAST and every existing index
    is untouched.
    """
    keys = _candidate_keys(COL_ATL, "mlb")
    assert keys[0] == "mlb|totals|over|7.5", f"role key is not first: {keys}"
    assert "mlb|totals|over|7.5|@atlanta braves+colorado rockies" in keys


def test_a_bare_key_match_on_a_DIFFERENT_game_is_rejected():
    """THE SAFETY PROPERTY, and the reason the bare fallback is allowed to stay.

    Dropping the bare key would take venue coverage to zero on every source
    that cannot yet name its game, so it stays — and this is what stops it
    being a hole. A quote whose `game` names another fixture must not price
    this row even when its key matched.

    This is the exact production shape: one `over 7.5 @ -400` quote belonging
    to SD@TB, offered under the bare key, reaching COL@ATL.
    """
    from syndicate.features.shared.venue_quote_fanin import Quote, apply_venue_quotes

    foreign = Quote(
        key="mlb|totals|over|7.5",
        source="polymarket_us",
        sport="mlb",
        market="totals",
        side="over",
        probability=0.80,
        american=-400,
        line=7.5,
        fetched_at=1_000_000.0,
        game="san diego padres+tampa bay rays",
    )
    row = dict(COL_ATL, sport="mlb", game={"state": "live"})
    result = apply_venue_quotes(
        [row],
        selected_date="2026-08-29",
        now=1_000_010.0,
        collected_by_sport={"mlb": {"quotes": {foreign.key: foreign}}},
    )
    assert result["stamped"] == 0, "a quote naming SD@TB priced a COL@ATL row"
    assert result["cross_game_rejected"] == 1, (
        "the rejection must be COUNTED, not silent -- a zero here is how the"
        " bleed stayed invisible for as long as it did"
    )


def test_a_quote_that_names_no_game_still_matches():
    """The asymmetry that makes this incapable of regressing coverage.

    `game=None` means the SOURCE could not name the fixture. Those pass exactly
    as they do today, so this change can only ever remove a match that is
    provably wrong.
    """
    from syndicate.features.shared.venue_quote_fanin import Quote, apply_venue_quotes

    unnamed = Quote(
        key="mlb|totals|over|7.5",
        source="oddsapi",
        sport="mlb",
        market="totals",
        side="over",
        probability=0.5,
        american=-110,
        line=7.5,
        fetched_at=1_000_000.0,
        game=None,
    )
    row = dict(COL_ATL, sport="mlb", game={"state": "live"})
    result = apply_venue_quotes(
        [row],
        selected_date="2026-08-29",
        now=1_000_010.0,
        collected_by_sport={"mlb": {"quotes": {unnamed.key: unnamed}}},
    )
    assert result["stamped"] == 1
    assert result["cross_game_rejected"] == 0


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


def test_a_totals_row_that_cannot_name_its_game_is_not_priced():
    """THE COVERAGE TRADE, made explicit so it is a decision and not a surprise.

    Polymarket's totals quote is keyed to the GAME. A board row with no teams
    cannot build that key, so it goes unmatched rather than taking a price
    belonging to whichever fixture happened to be in the pool.

    That is a real loss of coverage and it is the correct direction: if the
    board cannot name the fixture, nothing can verify the price, and matching
    anyway IS the cross-game pricing this whole change removes. Coverage may be
    traded for certainty; a price may not.
    """
    from syndicate.features.shared.venue_quote_fanin import Quote, apply_venue_quotes

    quote = Quote(
        key="mlb|totals|over|7.5|@atlanta braves+colorado rockies",
        source="polymarket_us",
        sport="mlb",
        market="totals",
        side="over",
        probability=0.02,
        american=4900,
        line=7.5,
        fetched_at=1_000_000.0,
        game="atlanta braves+colorado rockies",
    )
    teamless = {"sport": "mlb", "market": "totals", "side": "over", "line": 7.5}
    result = apply_venue_quotes(
        [teamless],
        selected_date="2026-08-29",
        now=1_000_010.0,
        collected_by_sport={"mlb": {"quotes": {quote.key: quote}}},
    )
    assert result["stamped"] == 0
    # NOT counted as a cross-game rejection: nothing was rejected, the key was
    # never built. The two are different facts and the counters keep them apart.
    assert result["cross_game_rejected"] == 0


def test_h2h_is_deliberately_left_unqualified():
    """h2h keys already name the game IMPLICITLY -- their side is the CLUB.

    A club plays one game a day, so `mlb|h2h|chicago cubs` cannot collide across
    fixtures the way `mlb|totals|over|7.5` does. Production agreed: all 26
    shared quotes were totals, while every Polymarket h2h row carried a price
    unique to its game. Qualifying h2h would add a redundant key to every
    moneyline row and fix nothing.
    """
    keys = _candidate_keys(
        _row("evt-x", "Colorado Rockies", "Atlanta Braves", market="h2h", side="home", line=None),
        "mlb",
    )
    assert keys[0] == "mlb|h2h|home"
    assert not any("|@" in k for k in keys), f"h2h gained a game-qualified key: {keys}"


# ---------------------------------------------------------------------------
# `#603`, Kalshi half. The ticker names the fixture -- via `match_event_blob`,
# never by splitting the blob here.
# ---------------------------------------------------------------------------


def _kalshi_totals_payload():
    """The shape the WRITER persists (`series` -> `markets`), not the old flat
    `markets` key -- the same fixture correction `test_kalshi_catalogue` records.

    `BOSMIA` is the run-together club blob. Nothing in it says whether the
    boundary is BOS|MIA or BOSM|IA; `match_event_blob` decides by checking every
    legal split against the schedule passed in.
    """
    return {
        "fetched_at": "2026-08-25T20:15:00Z",
        "series": {
            "KXMLBTOTAL": {
                "markets": [{
                    "ticker": "KXMLBTOTAL-26AUG251840BOSMIA-7",
                    "series": "KXMLBTOTAL",
                    "title": "Over 7.5 runs scored?",
                    "yes_ask_dollars": 0.54,
                    "no_ask_dollars": 0.48,
                }]
            }
        },
    }


_BOS_MIA = [{"event_id": "evt-bos-mia",
             "home_team": "Miami Marlins",
             "away_team": "Boston Red Sox"}]


def test_a_kalshi_totals_quote_names_its_game_OFF_vs_ON(monkeypatch):
    """off != on for the whole Kalshi conversion.

    Without `games` the adapter cannot resolve the blob and keys bare -- which
    is exactly its behaviour before this change. With `games` it keys to the
    fixture. Asserting only the ON case would pass just as happily if the
    qualifier were unconditional, and asserting only OFF would pass if the
    conversion were inert.
    """
    import time

    from syndicate.features.shared import venue_quote_adapters as adapters

    monkeypatch.setattr(adapters, "_artifact", lambda parts: (_kalshi_totals_payload(), time.time()))

    off = {q.key for q in adapters.kalshi_outcome("mlb", "2026-08-25").quotes}
    on = adapters.kalshi_outcome("mlb", "2026-08-25", games=_BOS_MIA).quotes
    on_keys = {q.key for q in on}

    assert off, "the adapter produced no quotes at all -- fixture is wrong, not the code"
    assert not any("|@" in k for k in off), f"keyed to a game with no schedule to resolve against: {off}"
    assert on_keys != off, "passing `games` changed nothing -- the conversion is inert"
    assert all("|@boston red sox+miami marlins" in k for k in on_keys), on_keys
    # And the quote CARRIES the game, so the fan-in's cross-game rejection can
    # refuse it on the wrong row even if a bare key matched.
    assert {q.game for q in on} == {"boston red sox+miami marlins"}


def test_a_kalshi_ticker_whose_blob_matches_NO_game_keys_bare(monkeypatch):
    """Unresolvable falls back to today's behaviour, never to a guess.

    `match_event_blob` refuses rather than picking a split, and this must
    inherit that refusal as a BARE key -- not as a fabricated fixture and not
    as a dropped quote.
    """
    import time

    from syndicate.features.shared import venue_quote_adapters as adapters

    monkeypatch.setattr(adapters, "_artifact", lambda parts: (_kalshi_totals_payload(), time.time()))
    elsewhere = [{"event_id": "evt-other",
                  "home_team": "Atlanta Braves",
                  "away_team": "Colorado Rockies"}]

    keys = {q.key for q in adapters.kalshi_outcome("mlb", "2026-08-25", games=elsewhere).quotes}

    assert keys, "an unresolvable blob must not drop the quote"
    assert not any("|@" in k for k in keys), f"a blob matching no game was keyed anyway: {keys}"


def test_the_kalshi_blob_is_never_split_locally():
    """The rule `event_blob_from_ticker` states, asserted rather than trusted.

    It returns the blob WHOLE. A future edit that split it here -- rather than
    letting `match_event_blob` check every split against the schedule -- would
    pair bets with the wrong game, which is the failure the whole module exists
    to prevent.
    """
    from syndicate.features.shared.kalshi_catalogue import event_blob_from_ticker

    assert event_blob_from_ticker("KXMLBTOTAL-26AUG251840BOSMIA-7") == "BOSMIA"
