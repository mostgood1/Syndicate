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


# ---------------------------------------------------------------------------
# `#603`, OddsAPI half. Its shard key already names the fixture -- no schedule.
# ---------------------------------------------------------------------------


def _oddsapi_shard(*keys):
    return {
        "fetched_at": "2026-08-29T21:00:00Z",
        "markets": {k: {"last_odds": -110, "last_line": 7.5} for k in keys},
    }


_OA_TOTALS_A = (
    "event_id=e1|home_team=Atlanta Braves|away_team=Colorado Rockies"
    "|market=totals|side=over|line=7.5|book=draftkings"
)
_OA_TOTALS_B = (
    "event_id=e2|home_team=Tampa Bay Rays|away_team=San Diego Padres"
    "|market=totals|side=over|line=7.5|book=draftkings"
)


def test_two_oddsapi_totals_on_the_same_line_no_longer_collide(monkeypatch):
    """THE DEFECT, on the source with the most volume.

    Two different games, same market/side/line. Before `#603` both emitted
    `mlb|totals|over|7.5` and the pool -- one entry per key -- kept whichever
    came last, so one game's price answered both.
    """
    import syndicate.features.shared.odds_control_plane as ocp

    from syndicate.features.shared import venue_quote_adapters as adapters

    # Patched on the SOURCE module, not on `adapters`: the import is inside
    # `oddsapi_outcome`, so it resolves through `odds_control_plane` at call
    # time and a name bound on the adapter module would never be consulted.
    monkeypatch.setattr(
        ocp, "load_odds_history_payload_for_sport",
        lambda sport, date: _oddsapi_shard(_OA_TOTALS_A, _OA_TOTALS_B),
    )

    quotes = adapters.oddsapi_outcome("mlb", "2026-08-29").quotes
    keys = {q.key for q in quotes}

    assert len(quotes) == 2, quotes
    assert len(keys) == 2, f"two different games still share one key: {keys}"
    assert all("|@" in k for k in keys), keys
    assert {q.game for q in quotes} == {
        "atlanta braves+colorado rockies",
        "san diego padres+tampa bay rays",
    }


def test_an_oddsapi_row_whose_clubs_do_not_resolve_keys_bare(monkeypatch):
    """off != on, via the only lever this source has.

    OddsAPI needs no schedule -- its key carries the clubs -- so the ON/OFF
    contrast is a resolvable pair against an unresolvable one. An unresolvable
    club must fall back to the bare key, never to a raw-string token that only
    one half of the join would recognise.
    """
    import syndicate.features.shared.odds_control_plane as ocp
    from syndicate.features.shared import venue_quote_adapters as adapters

    unresolvable = (
        "event_id=e9|home_team=Not A Real Club|away_team=Also Not Real"
        "|market=totals|side=over|line=7.5|book=draftkings"
    )
    monkeypatch.setattr(
        ocp, "load_odds_history_payload_for_sport",
        lambda sport, date: _oddsapi_shard(unresolvable),
    )

    quotes = adapters.oddsapi_outcome("mlb", "2026-08-29").quotes

    assert quotes, "an unresolvable club must not drop the quote"
    assert all("|@" not in q.key for q in quotes), [q.key for q in quotes]
    assert all(q.game is None for q in quotes)


def test_oddsapi_h2h_is_left_unqualified(monkeypatch):
    """Deliberate, and for a different reason than Kalshi's.

    The board's h2h rows offer a role key AND club/token keys that this source
    cannot produce. Qualifying only OddsAPI's half of that pair would break the
    match rather than sharpen it.
    """
    import syndicate.features.shared.odds_control_plane as ocp
    from syndicate.features.shared import venue_quote_adapters as adapters

    h2h = (
        "event_id=e1|home_team=Atlanta Braves|away_team=Colorado Rockies"
        "|market=h2h|side=home|book=draftkings"
    )
    monkeypatch.setattr(
        ocp, "load_odds_history_payload_for_sport",
        lambda sport, date: _oddsapi_shard(h2h),
    )

    quotes = adapters.oddsapi_outcome("mlb", "2026-08-29").quotes

    assert quotes
    assert all("|@" not in q.key for q in quotes), [q.key for q in quotes]


# ---------------------------------------------------------------------------
# `#603` NCAAF. No club map exists, so the club-pair token is unbuildable and
# the slug's team tokens are Polymarket's own abbreviations. Real production
# slugs and outcomes, read from /api/ops/polymarket/slate on 2026-08-29.
# ---------------------------------------------------------------------------


_NCAAF_GAMES = [
    {"event_id": "evt-nmxst-flst",
     "away_team": "New Mexico State Aggies", "home_team": "Florida State Seminoles"},
    {"event_id": "evt-jaxst-ndkst",
     "away_team": "Jacksonville State Gamecocks", "home_team": "North Dakota State Bison"},
]


def _ncaaf_slate():
    """The REAL shapes. `aec-` is the moneyline, `tsc-...-total-` the total, and
    the team tokens (`nmxst`, `flst`) are identical across both."""
    import time

    return {
        "fetched_at": time.time(),
        "markets": [
            {"slug": "aec-cfb-nmxst-flst-2026-08-29",
             "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
             "outcomes": '["Seminoles","Aggies"]', "outcomePrices": '["0.90","0.10"]'},
            {"slug": "tsc-cfb-nmxst-flst-2026-08-29-total-53pt5",
             "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL", "line": 53.5,
             "outcomes": '["Over","Under"]', "outcomePrices": '["0.52","0.48"]'},
            {"slug": "aec-cfb-jaxst-ndkst-2026-08-29",
             "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
             "outcomes": '["Gamecocks","Bison"]', "outcomePrices": '["0.35","0.65"]'},
            {"slug": "tsc-cfb-jaxst-ndkst-2026-08-29-total-53pt5",
             "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL", "line": 53.5,
             "outcomes": '["Over","Under"]', "outcomePrices": '["0.61","0.39"]'},
        ],
    }


def test_ncaaf_totals_on_the_same_line_stop_colliding_OFF_vs_ON(monkeypatch):
    """THE DEFECT MEASURED IN PRODUCTION: 4 of 7 live Polymarket NCAAF totals
    rows shared one price across games on the 00:30:59Z board.

    Two different games, the same 53.5 line. Without a schedule the tokens
    cannot be resolved and both key bare -- one pool entry, one price answering
    both. With it, the moneyline's nicknames resolve each pair and the totals
    inherit the answer.
    """
    import time

    from syndicate.features.shared import venue_quote_adapters as adapters

    monkeypatch.setattr(adapters, "_artifact", lambda parts: (_ncaaf_slate(), time.time()))

    off = {q.key for q in adapters.polymarket_us_outcome("ncaaf", "2026-08-29").quotes
           if q.market in ("totals", "totals_alt")}
    on = [q for q in adapters.polymarket_us_outcome("ncaaf", "2026-08-29", games=_NCAAF_GAMES).quotes
          if q.market in ("totals", "totals_alt")]
    on_keys = {q.key for q in on}

    assert off, "fixture produced no totals quotes at all"
    # OFF: both games collapse onto the same over/under keys.
    assert not any("|@" in k for k in off), off
    # ON: each game gets its own, and they are DIFFERENT from each other.
    assert on_keys != off, "passing `games` changed nothing -- the NCAAF path is inert"
    assert all("|@evt:" in k for k in on_keys), on_keys
    assert len(on_keys) == len(off) * 2, (
        f"the two games did not separate: off={off} on={on_keys}"
    )
    assert {q.game for q in on} == {"evt:evt-nmxst-flst", "evt:evt-jaxst-ndkst"}


def test_the_board_row_derives_the_SAME_ncaaf_token():
    """Both halves must agree or the qualified key never matches.

    The board side cannot build a club-pair token either (`_alias_map('ncaaf')`
    is empty), so it falls back to the same `evt:` identity.
    """
    row = {"sport": "ncaaf", "market": "totals", "side": "over", "line": 53.5,
           "event_id": "evt-nmxst-flst",
           "home_team": "Florida State Seminoles", "away_team": "New Mexico State Aggies"}

    keys = _candidate_keys(row, "ncaaf")

    assert keys[0] == "ncaaf|totals|over|53.5", f"role key must stay first: {keys}"
    assert "ncaaf|totals|over|53.5|@evt:evt-nmxst-flst" in keys, keys


def test_an_ncaaf_pair_matching_TWO_games_refuses(monkeypatch):
    """Ambiguity is dropped, not assigned.

    Two fixtures sharing a nickname is exactly what the PAIR constraint exists
    for; when the pair cannot separate them either, silence is the right answer.
    """
    import time

    from syndicate.features.shared import venue_quote_adapters as adapters

    slate = {"fetched_at": time.time(), "markets": [
        {"slug": "aec-cfb-aaa-bbb-2026-08-29",
         "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
         "outcomes": '["Aggies","Bulldogs"]', "outcomePrices": '["0.5","0.5"]'},
    ]}
    twins = [
        {"event_id": "g1", "away_team": "Texas A&M Aggies", "home_team": "Georgia Bulldogs"},
        {"event_id": "g2", "away_team": "Utah State Aggies", "home_team": "Fresno Bulldogs"},
    ]
    monkeypatch.setattr(adapters, "_artifact", lambda parts: (slate, time.time()))

    pairs = adapters._polymarket_pair_games(slate["markets"], "ncaaf", twins)

    assert pairs == {}, f"an ambiguous pair was assigned a game: {pairs}"


def test_a_game_with_NO_moneyline_in_the_slate_cannot_be_resolved(monkeypatch):
    """THE LIMITATION, pinned so it is a known bound and not a surprise.

    The pair is learned from the MONEYLINE, because that is the only market
    family whose `outcomes` name the teams. A game whose moneyline is absent
    from the slate keeps a bare key and stays exposed to the collision -- which
    is the pre-`#603` behaviour, not a new failure, but it IS a hole and the
    count of such games is worth watching.
    """
    import time

    from syndicate.features.shared import venue_quote_adapters as adapters

    totals_only = {"fetched_at": time.time(), "markets": [
        {"slug": "tsc-cfb-nmxst-flst-2026-08-29-total-53pt5",
         "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_TOTAL", "line": 53.5,
         "outcomes": '["Over","Under"]', "outcomePrices": '["0.52","0.48"]'},
    ]}
    monkeypatch.setattr(adapters, "_artifact", lambda parts: (totals_only, time.time()))

    quotes = adapters.polymarket_us_outcome("ncaaf", "2026-08-29", games=_NCAAF_GAMES).quotes

    assert quotes, "the quote must still be emitted, just unqualified"
    assert all("|@" not in q.key for q in quotes), [q.key for q in quotes]
    assert all(q.game is None for q in quotes)


# ---------------------------------------------------------------------------
# `#603` THE GRID PATH -- the one that actually runs.
#
# `apply_venue_quotes_to_grid` is what fires on the board build (`GRID_REPRICE`
# every cycle; `VENUE_REPRICE` absent from 45 minutes of production logs) and it
# is what calls `_reprice_live_benchmark`, which writes `cells[book][side]` ->
# `book_prices`. The first cut of `#603` landed entirely on `apply_venue_quotes`
# and was therefore INERT on the only path that produces the defect. These tests
# exist so that cannot recur silently.
# ---------------------------------------------------------------------------


def _grid_row(event_id, away, home, line=7.5):
    """A REALISTIC grid row.

    `best` must carry a dict per side or `sides_seen` never increments and a
    `repriced == 0` assertion passes trivially -- the fixture would agree with
    any implementation, including one that does nothing. `age_seconds` is
    deliberately STALE (9,999s) so a legitimate venue quote genuinely would win
    the freshness check and reprice; that is what makes "0 repriced" evidence
    of the refusal rather than evidence of an inert test.
    """
    return {
        "sport": "mlb", "event_id": event_id, "market": "totals", "line": line,
        "away_team": away, "home_team": home,
        "sides": ["over", "under"],
        "best": {
            "over": {"price": -110, "bookmaker": "draftkings", "age_seconds": 9999.0},
            "under": {"price": -110, "bookmaker": "draftkings", "age_seconds": 9999.0},
        },
        "game": {"state": "live"},
    }


def test_the_GRID_path_refuses_a_quote_naming_another_game():
    """THE DEFECT, on the path that writes the corrupted price.

    One quote belonging to SD@TB, offered under the bare key, must not price a
    COL@ATL grid row -- which is exactly what produced `over 7.5 @ -400` on four
    games at once in production.
    """
    from syndicate.features.shared.venue_quote_fanin import Quote, apply_venue_quotes_to_grid

    foreign = Quote(
        key="mlb|totals|over|7.5", source="polymarket_us", sport="mlb",
        market="totals", side="over", probability=0.80, american=-400,
        line=7.5, fetched_at=1_000_000.0, game="san diego padres+tampa bay rays",
    )
    grid = [_grid_row("evt-col-atl", "Colorado Rockies", "Atlanta Braves")]

    out = apply_venue_quotes_to_grid(
        grid, "mlb", "2026-08-29", now=1_000_010.0,
        collected={"quotes": {foreign.key: foreign}},
    )

    assert out["repriced"] == 0, "a quote naming SD@TB repriced a COL@ATL grid row"
    assert out["cross_game_rejected"] == 1, (
        "the rejection must be COUNTED on this path too -- an uncounted zero is"
        " how the first version stayed invisible"
    )


def test_the_GRID_path_still_takes_a_quote_that_names_no_game():
    """The asymmetry holds here as well: unknown passes, so no coverage is lost
    on any source that has not been converted."""
    from syndicate.features.shared.venue_quote_fanin import Quote, apply_venue_quotes_to_grid

    unnamed = Quote(
        key="mlb|totals|over|7.5", source="polymarket_us", sport="mlb",
        market="totals", side="over", probability=0.5, american=-110,
        line=7.5, fetched_at=1_000_000.0, game=None,
    )
    grid = [_grid_row("evt-col-atl", "Colorado Rockies", "Atlanta Braves")]

    out = apply_venue_quotes_to_grid(
        grid, "mlb", "2026-08-29", now=1_000_010.0,
        collected={"quotes": {unnamed.key: unnamed}},
    )

    assert out["cross_game_rejected"] == 0


def test_the_GRID_path_finds_a_game_QUALIFIED_key():
    """And it must actually ask for the qualified key, not merely tolerate one.

    Without this the rejection above would still pass while the qualified key
    was never looked up -- the quote would simply go unmatched, which reads as
    'safe' and silently drops every converted source.
    """
    from syndicate.features.shared.venue_quote_fanin import Quote, apply_venue_quotes_to_grid

    qualified = Quote(
        key="mlb|totals|over|7.5|@atlanta braves+colorado rockies",
        source="polymarket_us", sport="mlb", market="totals", side="over",
        probability=0.52, american=-108, line=7.5, fetched_at=1_000_000.0,
        game="atlanta braves+colorado rockies",
    )
    grid = [_grid_row("evt-col-atl", "Colorado Rockies", "Atlanta Braves")]

    out = apply_venue_quotes_to_grid(
        grid, "mlb", "2026-08-29", now=1_000_010.0,
        collected={"quotes": {qualified.key: qualified}},
    )

    assert out["cross_game_rejected"] == 0
    assert out["sides_seen"] >= 1
