"""Which Kalshi series are which sport, and what bet each market actually is.

THE PIECE THAT MAKES KALSHI A MULTI-SPORT SOURCE. `kalshi_board_join` hardcoded
two MLB series to two board market names. That works for two series and stops
working at three, because the mapping it encodes -- Kalshi's wording to our
market vocabulary -- is a translation this repo already owns.

--------------------------------------------------------------------------
SERIES -> SPORT IS THE ONLY THING THIS FILE DECIDES
--------------------------------------------------------------------------

`market_keys.canonical_market_key(sport, stat_text)` is the authority on market
names (`#224`, whose first reading was `missing_market_key` at **100% of every
row, in every lane, in both sports**). It already maps Kalshi's own title
wording without help: "Outs Recorded" -> `outs`, "home runs" ->
`batter_home_runs`, "points" -> `player_points`.

So a series needs one fact from us -- WHICH SPORT -- and the stat text in its
own title supplies the rest. Adding NBA player points becomes one registry line
rather than a new mapping table, and a market vocabulary that changes changes in
exactly one place for every feed at once.

CLAUDE.md's rule against a third private normaliser is the reason this file does
not have its own market table. It nearly did.

--------------------------------------------------------------------------
NOTHING HERE IS GUESSED FROM A TICKER
--------------------------------------------------------------------------

Every series in `SERIES_SPORT` has been SEEN in a live listing, and the date it
was seen is in the comment beside it. Inventing plausible tickers (`KXNBAPTS`)
is the specific trap `kalshi_client`'s docstring warns about: a series that does
not exist returns an empty page that is indistinguishable from a venue listing
nothing, which is the false negative this whole integration was built to avoid.

An unrecognised series is therefore recorded BY NAME with a sample title rather
than dropped. That list is the work queue: it says what to add and what it looks
like, so one daily discovery run is the whole discovery loop.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

__all__ = [
    "SERIES_SPORT",
    "game_date_from_ticker",
    "prop_candidates",
    "event_blob_from_ticker",
    "match_event_blob",
    "game_market_from_title",
    "auto_game_series_from_catalogue",
    "sport_for_series",
    "sport_for_ticker",
    "auto_series_from_catalogue",
    "soccer_league_from_title",
    "register_discovered",
    "all_series",
    "classify_market",
    "unmapped_series",
    "GRAMMAR_PLAYER_THRESHOLD",
    "GRAMMAR_TEAM_TOTAL",
    "GRAMMAR_TEAM_SPREAD",
    "GRAMMAR_MONEYLINE",
]

# Kalshi series ticker -> the sport this repo calls it.
#
# EVERY ENTRY WAS OBSERVED, and the observation date is the point of the
# comment. `<seen>` means it appeared in a `[kalshi_discovery] LISTED` or
# `SERIES` line with the sample title quoted.
SERIES_SPORT: dict[str, str] = {
    # seen 2026-08-23, "Andrew Abbott: 7+ strikeouts?"
    "KXMLBKS": "mlb",
    # seen 2026-08-23, "... : 17+ Outs Recorded?"
    "KXMLBOUTS": "mlb",
    # seen 2026-08-23, "Pete Crow-Armstrong: 2+ home runs?"
    "KXMLBHR": "mlb",
    # seen 2026-08-23T23:28:49Z in the signed series catalogue, titled
    # "Women's Pro Basketball Player Rebounds". The ONLY WNBA player-prop
    # series in the 91 Kalshi lists -- every other one is a game line
    # (quarter/half winners, spreads, totals) or a future (MVP, ROY, draft),
    # and those need an event_ticker mapping that does not exist.
    #
    # `market_keys` resolves "rebounds" -> `player_rebounds` for wnba, and
    # `bet_status_wnba` reads `reb` off the live box, so this one line makes the
    # market priceable, joinable AND gradeable.
    "KXWNBAREB": "wnba",
    # The other three WNBA player props, seen in the same catalogue read:
    # "Women's Pro Basketball Player Points" / "Player Assists" /
    # "Player Threes". `market_keys` resolves all three for wnba and
    # `bet_status_wnba` reads pts / ast / threes_made off the live box.
    #
    # HAND-REGISTERED even though `auto_series_from_catalogue` finds all four,
    # and the duplication is deliberate. Discovery is PER-PROCESS state
    # populated at boot: if the catalogue read fails once -- a 429, a restart
    # mid-outage -- that process prices nothing but the hand-written entries for
    # its whole life, silently. Naming the ones that matter tonight makes them
    # independent of a network call succeeding at the right moment.
    # `register_discovered` never overwrites these, so discovery finding them
    # again is a no-op rather than a conflict.
    "KXWNBAPTS": "wnba",
    "KXWNBAAST": "wnba",
    "KXWNBA3PT": "wnba",
    # ------------------------------------------------------------------
    # FULL-GAME TOTALS, hand-registered because the TITLE GATE misses them.
    # ------------------------------------------------------------------
    #
    # `auto_game_series_from_catalogue` registers a series only if
    # `game_market_from_title` can name its market from Kalshi's own series
    # title. That gate is why `KXMLBGAME` was invisible for weeks (its title is
    # "Professional Baseball Game"; the vocabulary had no "game"), and it is
    # still failing one market family over.
    #
    # CONFIRMED BY THE USER 2026-08-25 against a live market page:
    #
    #     KXMLBTOTAL-26AUG251840BOSMIA-7
    #
    # A full-game total on today's Boston/Miami game, strike 7. It exists, it
    # is tradeable, and `KXMLBTOTAL` appears NOWHERE in our logs -- never
    # registered, never fetched, so an MLB `totals` board row had nothing to
    # join to and every Kalshi order refused `no_live_price`.
    #
    # We DO fetch `KXMLBF5TOTAL` (first five), `KXMLBINNINGTOTAL` (one inning)
    # and `KXMLBTEAMTOTAL` (one team). None of those is the full-game total,
    # and the near-miss is what made the gap read as coverage rather than as an
    # absence.
    #
    # WHY THE GATE MISSES IT while `KXWNBATOTAL` and `KXNHLTOTAL` register
    # fine: the vocabulary resolves a title ending "... Total", and
    # 'Professional Baseball Total Runs' / 'Professional Baseball Runs' both
    # return None. The sports whose totals are named for their scoring unit
    # fall through; the ones named "Total" do not.
    #
    # Hand-registered rather than patched into the vocabulary because the
    # registry needs no title at all -- `sport_for_series` checks it FIRST and
    # `register_discovered` never overwrites it, so these keep working through
    # a failed catalogue read, and a later vocabulary fix is a no-op here
    # rather than a conflict. Same reasoning the WNBA props above already
    # state: "naming the ones that matter makes them independent of a network
    # call succeeding at the right moment."
    # ------------------------------------------------------------------
    # MLB PLAYER PROPS. Six confirmed by the user from live market pages
    # 2026-08-25, plus one seen in a production catalogue read.
    # ------------------------------------------------------------------
    #
    # Only KXMLBKS / KXMLBOUTS / KXMLBHR were registered, so these were never
    # fetched -- and the board is ALREADY ASKING FOR THEM. Measured
    # 2026-08-25T16:13:44Z, `VENUE_REPRICE_KEYS board_wanted`:
    #
    #   mlb|batter_rbis|over|0.5        (x3)   -> KXMLBRBI
    #   mlb|batter_total_bases|over|1.5        -> KXMLBTB
    #   mlb|earned_runs|under|1.5              -> KXMLBERA
    #   mlb|hits_allowed|over|4.5              -> KXMLBHA
    #
    # Every one of those rows found nothing and reported it as Kalshi having
    # no market, when Kalshi had the market and we were not asking for it.
    #
    # The stat vocabulary already resolves all of them -- `canonical_market_key`
    # maps hits/total bases/RBIs/earned runs/walks allowed/hits allowed -- so
    # the ONLY thing missing was the series registration. Verified end to end
    # against the real tickers: classification returns the right market, line
    # and side (`1+ hits` -> `batter_hits over 0.5`).
    #
    # PROPS NEED NO GAME-LINE FLAG. A prop names a human and joins on
    # (player, market, line), so these are priceable and gradeable the moment
    # they are fetched -- unlike the game lines, which also wait on
    # `SYNDICATE_KALSHI_GAME_LINES` and an event resolution.
    "KXMLBHIT": "mlb",
    "KXMLBHRR": "mlb",
    "KXMLBTB": "mlb",
    "KXMLBRBI": "mlb",
    "KXMLBERA": "mlb",
    "KXMLBWA": "mlb",
    # Seen in a production `KALSHI_SPORT MLB` catalogue read rather than on a
    # market page, so it is evidence of the same kind: the venue lists it.
    "KXMLBHA": "mlb",
    # seen 2026-08-25T20:33:06Z, `[kalshi_discovery] GAP series=KXMLBSB
    # count=44 reason=unmapped_series sample='William Contreras: 1+ stolen
    # bases?'` -- 44 markets refused at the FIRST gate, before any title was
    # read. `market_keys` gained `stolen bases -> batter_stolen_bases` in the
    # same change; registering a series whose stat does not resolve just moves
    # the refusal one gate later, which is what `KXMLBHRR` did.
    #
    # WORTH MORE THAN THE COUNT SUGGESTS: `tests/test_mlb_ladders_build.py`
    # keeps `batter_stolen_bases` in `known_unfed` -- the MLB sim already
    # models this market and no feed prices it. This is the first price source
    # it has had.
    "KXMLBSB": "mlb",
    "KXMLBTOTAL": "mlb",
    "KXNBATOTAL": "nba",
    "KXNFLTOTAL": "nfl",
    "KXNCAAFTOTAL": "ncaaf",
    "KXNCAABTOTAL": "ncaab",
    # ...and the moneyline/spread pair for the same sports, for the same
    # reason. `KXMLBGAME` and `KXMLBSPREAD` currently register only because a
    # vocabulary entry happens to match their titles; a title Kalshi rewords
    # would silently un-register the most valuable market on the venue again.
    # A registry entry cannot be reworded out from under us.
    "KXMLBGAME": "mlb",
    "KXMLBSPREAD": "mlb",
    "KXWNBAGAME": "wnba",
    "KXWNBASPREAD": "wnba",
    "KXWNBATOTAL": "wnba",
}

# Series we have SEEN and deliberately do not cover. Kept explicit so they stop
# appearing in the unmapped work queue every day: "we do not model this" and
# "we have not looked at this yet" are different states and the queue is only
# useful if it means the second.
SERIES_OUT_OF_SCOPE: dict[str, str] = {
    # seen 2026-08-23 -- Japanese NPB and Korean KBO baseball, UFC, softball.
    # Real markets, no sim, no board rows: nothing could price them.
    "KXNPBTOTAL": "npb",
    "KXNPBSPREAD": "npb",
    "KXNPBRFI": "npb",
    "KXKBOTOTAL": "kbo",
    "KXKBOSPREAD": "kbo",
    "KXKBORFI": "kbo",
    "KXUFCFIGHT": "ufc",
    "KXSOWBBALLGAME": "softball",
    # ------------------------------------------------------------------
    # SEASON AND SLATE FUTURES, evicted 2026-08-25. Real markets, in sports
    # we model, that NO board row can ever match -- the board is built per
    # GAME DATE and these have no game.
    #
    # HOW THEY GOT IN: `auto_game_series_from_catalogue` registers any
    # sport-token series whose title TAIL resolves via `canonical_game_market`,
    # and Kalshi titles a division future "... Division Winner". "Winner" is a
    # game-market word, so the gate that exists to find moneylines let the
    # futures through with them.
    #
    # WHAT IT COST, measured 2026-08-25 on `[kalshi_odds] TICK this_tick` and
    # `[kalshi_odds] JOIN_TITLES by_series` (21:13:07Z / 21:15:49Z): roughly
    # 1,660 markets of the 6,000-market working set and ~34 of the 193 slots in
    # a 60-per-tick fetch rotation -- so a live ladder waited ~8 extra minutes
    # behind markets that cannot be bet. `KXNCAAFWINS` and `KXNCAAFAWARD` were
    # each capped at EXACTLY 400 by `MAX_MARKETS_PER_SERIES`, i.e. consuming
    # the whole per-series bound, and every one of those 800 came back
    # `unreadable_title`.
    #
    # WHY THE REGISTRY AND NOT A DATE FILTER. Dropping undated markets from the
    # working set is the obvious fix and `kalshi_odds_refresh` records that it
    # "was tried and reverted": player props skip the join's date check, so a
    # prop whose ticker shape does not parse was silently dropped from the
    # venue we actually trade, and six tests caught it. Evicting the SERIES is
    # both safer and strictly better -- it stops the FETCH, which a
    # market-level filter cannot.
    #
    # EVERY ENTRY BELOW WAS SEEN IN PRODUCTION, with the count beside it. This
    # list is deliberately not a title-pattern rule: the series-level titles
    # these register on have not been read, and inventing a pattern from market
    # titles is the guess this file exists to refuse.
    # ------------------------------------------------------------------
    # Division / conference winners. Sample title, KXNFLAFCEAST 21:13:07Z:
    # 'Will New York J win the Pro Football AFC East Division?'; KXNBACENTRAL
    # 21:15:49Z: 'Will Milwaukee be the Central Division winner in the 2026-27
    # season?'; KXMLBNLCENT 21:15:49Z: 'Will St. Louis be the 2026 NL Central
    # Division Winner'.
    "KXMLBALEAST": "season_futures",     # 5 markets
    "KXMLBALCENT": "season_futures",     # 5
    "KXMLBALWEST": "season_futures",     # 5
    "KXMLBNLEAST": "season_futures",     # 5
    "KXMLBNLCENT": "season_futures",     # 5
    "KXMLBNLWEST": "season_futures",     # 5
    "KXNBAATLANTIC": "season_futures",   # 5
    "KXNBACENTRAL": "season_futures",    # 5
    "KXNBANORTHWEST": "season_futures",  # 5
    "KXNBAPACIFIC": "season_futures",    # 5
    "KXNBASOUTHEAST": "season_futures",  # 5
    "KXNBASOUTHWEST": "season_futures",  # 5
    "KXNFLAFCEAST": "season_futures",    # 4
    "KXNFLAFCNORTH": "season_futures",   # 4
    "KXNFLAFCSOUTH": "season_futures",   # 4
    "KXNFLAFCWEST": "season_futures",    # 4
    "KXNFLNFCEAST": "season_futures",    # 4
    "KXNFLNFCNORTH": "season_futures",   # 4
    "KXNFLNFCSOUTH": "season_futures",   # 4
    "KXNFLNFCWEST": "season_futures",    # 4
    "KXNHLATLANTIC": "season_futures",   # 8
    "KXNHLCENTRAL": "season_futures",    # 8
    "KXNHLMETROPOLITAN": "season_futures",  # 8
    "KXNHLPACIFIC": "season_futures",    # 8
    # Season win totals, awards and season-long player races. The two largest
    # single wasters on the venue.
    "KXNCAAFWINS": "season_futures",     # 618 listed, 400 kept, 400 unreadable
    "KXNCAAFAWARD": "season_futures",    # 509 listed, 400 kept, 400 unreadable
    "KXNBAWINS": "season_futures",       # 312, all unreadable
    "KXNFLH2HWINS": "season_futures",    # 22
    "KXWNBAWINS": "season_futures",      # 19
    "KXNHLSEASONPTS": "season_futures",  # seen in AUTO_SERIES game_sample 19:11:24Z
    "KXNFLPLAYOFFHOST": "season_futures",  # 32
    "KXNBAMOSTWINS": "season_futures",   # 4
    # Slate-level and exhibition markets: real, and not a game line on any
    # board row. KXNFLCOMPETE 21:13:07Z: 'Jake Paul to compete in a Pro
    # Football game in the 2026-27 season?'.
    "KXNFLHIGHSCORE": "slate_futures",   # 9
    "KXNCAAFHIGHSCORE": "slate_futures", # 10
    "KXNBAPTSALLGAMES": "slate_futures", # AUTO_SERIES game_sample 19:35:08Z
    "KXNFLCOMPETE": "not_a_game_line",   # 2
    "KXNFLCELEBRITYGAME": "not_a_game_line",  # AUTO_SERIES game_sample 16:55:55Z
    "KXNBASLAMDUNK": "not_a_game_line",  # AUTO_SERIES game_sample 17:41:52Z
}

GRAMMAR_PLAYER_THRESHOLD = "player_threshold"
GRAMMAR_TEAM_TOTAL = "team_total"
GRAMMAR_TEAM_SPREAD = "team_spread"
GRAMMAR_MONEYLINE = "moneyline"

REASON_UNMAPPED_SERIES = "unmapped_series"
REASON_OUT_OF_SCOPE = "series_out_of_scope"
REASON_COMBINATORIAL = "combinatorial_series"
REASON_UNREADABLE_TITLE = "unreadable_title"
REASON_UNMAPPED_STAT = "stat_not_in_market_vocabulary"

# "Andrew Abbott: 7+ strikeouts?" / "Pete Crow-Armstrong: 2+ home runs?"
_PLAYER_THRESHOLD = re.compile(
    r"^\s*(?P<player>[^:]+?)\s*:\s*(?P<threshold>\d+)\s*\+\s*(?P<stat>.+?)\s*\??\s*$"
)
# "Over 7.5 runs scored?"
_TEAM_TOTAL = re.compile(
    r"^\s*(?P<direction>over|under)\s+(?P<line>\d+(?:\.\d+)?)\s+(?P<stat>.+?)\s*\??\s*$",
    re.IGNORECASE,
)
# "Will the Yomiuri Giants win by over 2.5 runs?"
_TEAM_SPREAD = re.compile(
    r"^\s*will\s+(?:the\s+)?(?P<team>.+?)\s+win\s+by\s+(?P<direction>over|under)\s+"
    r"(?P<line>\d+(?:\.\d+)?)\s+(?P<stat>.+?)\s*\??\s*$",
    re.IGNORECASE,
)
# "Mexico wins" / "Yadong Song wins"
_MONEYLINE = re.compile(r"^\s*(?P<team>.+?)\s+wins\s*\??\s*$", re.IGNORECASE)

# --------------------------------------------------------------------------
# THE GAME-LINE GRAMMARS KALSHI ACTUALLY USES, read from production titles
# 2026-08-24T02:12Z. The three above were written against a different wording
# and matched NONE of them -- 302 markets came back `unreadable_title` on the
# first build after game-line series were registered.
#
#   KXMLBSPREAD       'Texas wins by over 3.5 runs?'
#   KXMLBF5SPREAD     'Texas wins first 5 innings by over 2.5 runs?'
#   KXMLBF5TOTAL      'First 5 innings: Over 6.5 runs'
#   KXMLBTEAMTOTAL    'Will Texas score over 7.5 runs?'
#   KXMLBINNINGTOTAL  '9th inning: Over 1.5 runs'
#   KXMLBF5           'first 5 innings tie'
#
# `_TEAM_SPREAD` above wants "Will the X win by ..."; these say "X wins by ...".
# Close enough to look handled and different enough to match nothing, which is
# why the count was 302 and not a partial number.
# --------------------------------------------------------------------------

# The period phrase MLB uses, and the board's own suffix for it. Only the
# prefixes OddsAPI actually carries (`_1st_5_innings` and friends) are here --
# a 9th-inning total has no board key, so it must refuse rather than acquire a
# spelling that joins to nothing.
_INNINGS_PERIOD = {
    "1": "1st_1_innings",
    "3": "1st_3_innings",
    "5": "1st_5_innings",
    "7": "1st_7_innings",
}

# "Texas wins by over 3.5 runs?" / "Texas wins first 5 innings by over 2.5 runs?"
# / "Vallecano wins by more than 2.5 goals?" / "Tennessee wins 1Q by over 7.5 points?"
#
# THREE WORDINGS FOR ONE WAGER, and only the first was read. Measured
# 2026-08-25 5:01:52 PM Central, `JOIN_TITLES ... by_series`, every one of
# these `unreadable_title` on a series we had just registered:
#
#   KXMLSTOTAL 90  KXSERIEATOTAL 60  KXMLSSPREAD 60  KXLALIGASPREAD 52
#   KXSERIEASPREAD 40  KXSERIEAGAME 39  KXLIGUE1TOTAL 39  KXLIGUE1GAME 33
#   KXNFL1QSPREAD 160
#
# 413 soccer markets and 160 NFL quarter spreads, fetched and thrown away for
# a synonym. Registration was necessary and is not sufficient: the series has
# to be registered AND its titles read, and those fail independently.
#
# `more than`/`less than` are Kalshi's soccer wording and mean exactly
# over/under -- no other reading is available for "wins by more than 2.5
# goals". The PERIOD token is separate from MLB's innings phrase because the
# board spells them differently (`spreads_q1` vs `spreads_1st_5_innings`) and
# collapsing them would join a quarter line to a full-game row.
_TEAM_SPREAD_WINS_BY = re.compile(
    r"^\s*(?P<team>.+?)\s+wins\s+"
    r"(?:first\s+(?P<innings>\d+)\s+innings\s+)?"
    r"(?:(?P<period>[1-4](?:Q|H)|OT)\s+)?"
    r"by\s+(?P<direction>over|under|more\s+than|less\s+than)\s+"
    r"(?P<line>\d+(?:\.\d+)?)\s+(?P<stat>.+?)\s*\??\s*$",
    re.IGNORECASE,
)

# "Chicago vs Tennessee: Will neither team win the 1st Quarter?"
#
# THE DRAW LEG OF A THREE-WAY, recognised so it stops counting as unreadable
# and REFUSED for the same reason `_INNINGS_TIE` is: a draw is a third outcome
# and the board carries no three-way quarter market to join it to. Reading it
# as either side of a two-way line would be a bet on a different thing.
# 144 markets across KXNFL1Q/1H/2Q on 2026-08-25.
_NEITHER_TEAM_WINS = re.compile(
    r"^\s*(?:.+?:\s*)?will\s+neither\s+team\s+win\b.*$", re.IGNORECASE
)

# "First 5 innings: Over 6.5 runs"  (a TOTAL -- names no team)
_PERIOD_TOTAL = re.compile(
    r"^\s*first\s+(?P<innings>\d+)\s+innings\s*:\s*(?P<direction>over|under)\s+"
    r"(?P<line>\d+(?:\.\d+)?)\s+(?P<stat>.+?)\s*\??\s*$",
    re.IGNORECASE,
)

# "Will Texas score over 7.5 runs?"  (a TEAM total -- names the team)
_TEAM_SCORES = re.compile(
    r"^\s*will\s+(?:the\s+)?(?P<team>.+?)\s+score\s+(?P<direction>over|under)\s+"
    r"(?P<line>\d+(?:\.\d+)?)\s+(?P<stat>.+?)\s*\??\s*$",
    re.IGNORECASE,
)

# "first 5 innings tie" -- the DRAW leg of a three-way. Recognised so it stops
# counting as unreadable, and refused below: a draw is a third outcome and the
# board carries no MLB first-innings three-way market to join it to. Reading it
# as either side of a two-way line would be a bet on a different thing.
_INNINGS_TIE = re.compile(
    r"^\s*first\s+(?P<innings>\d+)\s+innings\s+tie\s*\??\s*$", re.IGNORECASE
)


# Ticker token -> sport. ORDER MATTERS AND IS THE WHOLE TRAP: "KXWNBAREB"
# contains "NBA", so a naive scan registers every WNBA series as NBA and prices
# women's rebounds off a men's box score. Longest-first, and WNBA before NBA.
_SPORT_TOKENS: tuple[tuple[str, str], ...] = (
    ("NCAAF", "ncaaf"),
    ("NCAAB", "ncaab"),
    ("WNBA", "wnba"),
    ("NBA", "nba"),
    ("MLB", "mlb"),
    ("NFL", "nfl"),
    ("NHL", "nhl"),
)

# Soccer competition display name -> Syndicate league slug, LONGEST FIRST.
# Built from `LEAGUE_DISPLAY_NAMES` rather than restated, so a league added to
# the soccer module is covered here without anybody remembering to. See
# `soccer_league_from_title` for why this is a title prefix and not a ticker
# token.
def _soccer_league_prefixes() -> tuple[tuple[str, str], ...]:
    try:
        from syndicate.features.soccer.sources import LEAGUE_DISPLAY_NAMES
    except Exception:
        # A soccer module that cannot import is a real failure, and returning
        # an empty table says "no soccer competition matched" -- which is
        # exactly the absence/failure confusion this file keeps refusing to
        # make. It is nonetheless the safe direction: soccer stays UNMAPPED and
        # keeps appearing in the COVERAGE_GAPS work queue, rather than being
        # registered against a guess.
        return ()
    pairs = [(slug, str(name).strip().lower()) for slug, name in LEAGUE_DISPLAY_NAMES.items()]
    pairs.sort(key=lambda pair: len(pair[1]), reverse=True)
    return tuple(pairs)


_SOCCER_LEAGUE_PREFIXES: tuple[tuple[str, str], ...] = _soccer_league_prefixes()

# A title that names a PLAYER prop. Kalshi words them "…Player Rebounds",
# "…Player Points". The word PLAYER is the discriminator: "Team Totals",
# "1st Quarter Spread" and "Rookie of the Year" all lack it, and every one of
# them is a market this system must not auto-register -- a game line has no
# player to join on and needs an event mapping that does not exist.
_PLAYER_PROP_TITLE = re.compile(r"\bplayer\s+(?P<stat>[A-Za-z0-9 +'-]+)$", re.IGNORECASE)


# The game date, which lives in the EVENT segment of the ticker and nowhere
# else. Two shapes are in production, both measured 2026-08-23T23:51Z:
#
#   KXWNBAPTS-26AUG23LVTOR-TORJALLEMAND22-15     event `26AUG23LVTOR`
#   KXMLBHR-26AUG242140MINATH-MINBBUXTON25-2     event `26AUG242140MINATH`
#
# MLB carries a start time after the date, WNBA does not, so only the leading
# `YYMMMDD` is common to both -- and that is all a date comparison needs. The
# time is deliberately NOT parsed: whether `2140` is Eastern or UTC is not
# settled by any reading I have, and a date taken from Kalshi's own labelling
# of the event does not depend on the answer.
_EVENT_DATE = re.compile(r"^(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})")
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def game_date_from_ticker(ticker: Any) -> str | None:
    """The date the game is played, as `YYYY-MM-DD`, or None if unreadable.

    NOT `close_time`, WHICH IS A SETTLEMENT DEADLINE. This is the correction to
    a wrong assumption that cost a whole slate. `kalshi_board_join` compared
    `close_time[:10]` against the board's date and refused everything that
    disagreed; the comment there said the assumption was unverified. Measured:

        ticker  KXMLBHR-26AUG242140MINATH-MINBBUXTON25-2
        open    2026-08-23T23:11:00Z
        close   2026-08-28T01:40:00Z      <- FOUR DAYS after the game
        expiration 2026-08-28T01:40:00Z

    Kalshi closes a market days after the event so late settlement data can
    land. So the date check refused 100% of markets, on every build for hours:
    `matched=0 reasons={'market_closes_on_another_date': 190}`. Nothing was
    wrong with the names, the prices or the parsing -- the join was comparing
    a game date against a settlement date and they never agree.

    Returns None rather than guessing. A caller must refuse an undatable market
    with its own named reason: falling back to `close_time` would restore
    exactly the bug this replaces.
    """
    text = str(ticker or "").strip().upper()
    parts = text.split("-")
    if len(parts) < 2:
        return None
    match = _EVENT_DATE.match(parts[1])
    if not match:
        return None
    month = _MONTHS.get(match.group("mon"))
    if month is None:
        return None
    try:
        # `26` is 2026. Kalshi has no markets from 1926 and none listed beyond
        # a few days out, so the century is not ambiguous in practice.
        return date(2000 + int(match.group("yy")), month, int(match.group("dd"))).isoformat()
    except ValueError:
        # A real date shape that is not a real date (`26FEB30`). Unreadable is
        # the honest answer; inventing March 2nd is not.
        return None


def event_blob_from_ticker(ticker: Any) -> str | None:
    """The TEAM part of the event segment: `26AUG242140MINATH` -> `MINATH`.

    The date, and MLB's optional four-digit start time, are stripped off the
    front; whatever remains identifies the two clubs. Returns None when the
    segment has no readable date, because without one the remainder is not
    reliably the team blob.

    DELIBERATELY NOT SPLIT INTO TWO TEAMS HERE. `MINATH` is MIN+ATH and `LVTOR`
    is LV+TOR, but nothing in the string says where the boundary is, and club
    codes vary in length. Splitting it needs a per-sport registry of Kalshi's
    own codes, which we do not have and would be guessing at -- and a wrong
    split pairs a bet with the wrong game, which is the one failure this whole
    module is built to prevent. `match_event_blob` inverts the problem instead.
    """
    text = str(ticker or "").strip().upper()
    parts = text.split("-")
    if len(parts) < 2:
        return None
    segment = parts[1]
    match = _EVENT_DATE.match(segment)
    if not match:
        return None
    rest = segment[len(match.group(0)):]
    # MLB carries HHMM after the date; WNBA does not. Strip exactly four
    # leading digits when present -- a club code is never all digits.
    if len(rest) >= 4 and rest[:4].isdigit():
        rest = rest[4:]
    return rest or None


def _clean_code(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _blob_for(away: Any, home: Any) -> str:
    return f"{_clean_code(away)}{_clean_code(home)}"


def _splits(blob: str) -> list[tuple[str, str]]:
    """Every way `MINATH` could be two club codes.

    Club codes run 2-4 characters, so the boundary is bounded rather than
    guessed at -- and every candidate is CHECKED against our own schedule
    below, so a wrong split cannot survive.
    """
    return [
        (blob[:i], blob[i:])
        for i in range(2, len(blob) - 1)
        if 2 <= i <= 4 and 2 <= len(blob) - i <= 4
    ]


def match_event_blob(
    blob: Any, games: Sequence[Mapping[str, Any]], *, sport: Any = None
) -> dict[str, Any]:
    """Which of OUR games is `blob`? Returns the answer AND how sure it is.

    THE INVERSION. Rather than splitting Kalshi's concatenated codes -- which
    needs a registry we do not have -- this builds `AWAY+HOME` from each game
    WE already know about and looks for the blob among them. Our own schedule
    supplies the boundary that the string omits, so no guess is required.

    Every outcome is named, and only `ok` is usable:

      ok         exactly one of our games produces this blob
      no_match   none does. Usually our club codes differ from Kalshi's
                 (`OAK` vs `ATH`), which is an ALIAS to add, not a bet to make
      ambiguous  more than one does -- a doubleheader, or two clubs whose codes
                 concatenate the same way. Refused: a coin flip between two
                 real games is worse than no bet, because it looks like a bet

    `no_match` being common is expected at first and is exactly the measurement
    that says which aliases to add. It must never soften into a best guess.
    """
    wanted = "".join(ch for ch in str(blob or "").upper() if ch.isalnum())
    if not wanted:
        return {"status": "no_match", "reason": "empty_blob"}

    # EXACT STRING FIRST -- cheap, and it is what matches when both sides
    # already spell a club the same way.
    hits = [
        game
        for game in (games or [])
        if _blob_for(game.get("away_team"), game.get("home_team")) == wanted
    ]

    if not hits:
        # THEN THROUGH THE CLUB RESOLVER. Kalshi says `ATH` where our board may
        # say `OAK`, and `CWS` where it may say `CHW`; comparing the raw
        # concatenation calls those different games and refuses a real match.
        # Measured 2026-08-24: `event_not_on_our_board: 66`.
        #
        # `team_aliases.canonical_team` is the repo's existing resolver, built
        # from the per-sport maps that already carry these spellings -- reused
        # rather than reimplemented, because two normalisers that disagree
        # about one club is a silent mismatch nobody sees (#218).
        #
        # The blob is SPLIT rather than the codes concatenated, because we do
        # not hold Kalshi's code list and cannot generate its spelling from
        # ours. Every candidate split is checked against a real game, so a
        # wrong boundary matches nothing rather than inventing a pairing.
        try:
            from syndicate.features.shared.team_aliases import canonical_team
        except Exception:
            canonical_team = None

        if canonical_team is not None:
            for game in games or []:
                ours_away = canonical_team(sport, game.get("away_team"))
                ours_home = canonical_team(sport, game.get("home_team"))
                if not ours_away or not ours_home:
                    # A club OUR side cannot resolve. Skipped rather than
                    # matched loosely -- an unresolvable name is not evidence.
                    continue
                for left, right in _splits(wanted):
                    if (
                        canonical_team(sport, left) == ours_away
                        and canonical_team(sport, right) == ours_home
                    ):
                        hits.append(game)
                        break
    if not hits:
        return {"status": "no_match", "blob": wanted}
    if len(hits) > 1:
        return {"status": "ambiguous", "blob": wanted, "count": len(hits)}
    game = hits[0]
    return {
        "status": "ok",
        "blob": wanted,
        "event_id": game.get("event_id"),
        "home_team": game.get("home_team"),
        "away_team": game.get("away_team"),
    }


def sport_for_ticker(ticker: Any) -> str | None:
    """The sport a series ticker names, or None. Longest token first."""
    text = str(ticker or "").strip().upper()
    for token, sport in _SPORT_TOKENS:
        if token in text:
            return sport
    return None


def soccer_league_from_title(title: Any) -> str | None:
    """The Syndicate soccer league a Kalshi series title names, or None.

    THE ONE SPORT WITH NO TICKER TOKEN, and the gap `prop_candidates` has been
    naming in its own docstring since it was written: "Kalshi names soccer
    series by COMPETITION (`KXEPL...`, `KXUCL...`), never by the word soccer,
    so there is no token to add until we have seen the real prefixes."

    We have now seen them. MEASURED 2026-08-25T19:12:01Z, `kalshi_discovery
    GAP`, every one of these reported `reason=unmapped_series`:

        KXLALIGASCORE     31  'Final score FC Barcelona wins 7-1?'
        KXLALIGA1HSCORE   13  'Will the 1st half score be FC Barcelona wins 3-2?'
        KXUECLSCORE      120  'Reg Time: Final score FK Partizan Belgrade wins 5-2?'
        KXUECLTEAMTOTAL   42  'Will Partizan Belgrade score over 2.5 goals?'
        KXUELTEAMTOTAL    12  'Will Anderlecht score over 2.5 goals?'
        KXUCL1HTOTAL      12  'Over 2.5 1H goals scored'
        KXEFLCUPTOTAL      3  'Will over 6.5 goals be scored?'

    ...and the user confirmed five more off live La Liga market pages the same
    day: KXLALIGAGAME, KXLALIGATOTAL, KXLALIGAGOAL, KXLALIGATCORNERS,
    KXLALIGA1HBTTS.

    ADDING TICKER PREFIXES WOULD BE THE WRONG FIX, for two reasons that both
    bit us this week. Kalshi runs dozens of competitions and we would be back
    to hand-adding one prefix per competition per week -- the whack-a-mole the
    user named. And a short competition code as a SUBSTRING is dangerous in a
    way the sport tokens are not: `UCL` sits inside `KXNUCLEARTEST`, so the
    same scan that made `KXWNBAREB` read as NBA would make a nuclear-test
    market read as soccer.

    So the COMPETITION comes from the title, which Kalshi writes in the same
    English this repo already stores in `LEAGUE_DISPLAY_NAMES` -- "La Liga
    Game", "EPL Total". Ten leagues, matched as a title PREFIX, and any of
    them registers the moment Kalshi lists it with no deploy on our side.

    A PREFIX, not a substring, and that is load-bearing: "Championship" would
    otherwise match "UEFA Champions League" and file a competition we do not
    model under one we do. Longest display name first, for the same reason
    `game_market_from_title` prefers the longest tail: "Belgian Pro League"
    and "Championship" must not race.

    Returns the LEAGUE, not the sport, because the caller needs both -- the
    sport for the registry and the league for the log line that says which
    competition just became legible.
    """
    text = str(title or "").strip()
    if not text:
        return None
    lowered = text.lower()
    for league, display in _SOCCER_LEAGUE_PREFIXES:
        if lowered.startswith(display):
            # A word boundary, so "MLS" does not match "MLSomething". Kalshi
            # separates the competition from the market with a space in every
            # title we have read.
            rest = lowered[len(display) :]
            if not rest or rest[0].isspace():
                return league
    return None


def auto_series_from_catalogue(titles: Mapping[str, Any]) -> dict[str, str]:
    """Series Kalshi lists that are PLAYER PROPS we can already price.

    THE ALTERNATIVE TO A HAND-MAINTAINED REGISTRY. Kalshi lists 13,389 series;
    four were registered by hand, and every sport added that way is a sport
    somebody has to remember. This reads the catalogue Kalshi gave us and keeps
    the ones that satisfy BOTH conditions:

      1. the TITLE says "Player <stat>" -- Kalshi's own word for a player prop,
         and the discriminator that excludes team totals, quarter spreads and
         every futures market, none of which have a player to join on; and
      2. `market_keys` resolves that stat for that sport -- so a market we
         cannot name is never registered, however player-shaped it looks.

    Both, because either alone is a guess. A title with "Player" in it whose
    stat we cannot resolve would price nothing; a stat we can resolve on a
    series that is actually a game line would join to the wrong thing.

    The SPORT comes from the ticker, never the title: "Women's Pro Basketball"
    is not a token this repo uses anywhere.
    """
    from syndicate.features.shared.market_keys import canonical_market_key

    found: dict[str, str] = {}
    for ticker, title in (titles or {}).items():
        # SOCCER COMES FROM THE TITLE, every other sport from the ticker. See
        # `soccer_league_from_title`: Kalshi names soccer series by competition
        # and there is no token to scan for.
        sport = sport_for_ticker(ticker)
        if sport is None and soccer_league_from_title(title) is not None:
            sport = "soccer"
        if sport is None:
            continue
        match = _PLAYER_PROP_TITLE.search(str(title or "").strip())
        if not match:
            continue
        if canonical_market_key(sport, match.group("stat").strip()) is None:
            continue
        found[str(ticker).strip().upper()] = sport
    return found


def prop_candidates(titles: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every series whose TITLE looks like a player prop, mapped or not.

    THE MEASUREMENT THAT PRECEDES A MAPPING. `auto_series_from_catalogue`
    returns only what already resolves, so a sport we cannot price is invisible
    in its output -- indistinguishable from a sport Kalshi does not list. That
    is the absence/failure confusion again, and it hid 317 NFL series behind
    `classified_n=0` for as long as football had no vocabulary.

    This reports the candidates BEFORE either filter, with the reason each one
    fails, so the gap is readable:

      - `sport=None`  the ticker carries no token we recognise. This is how
                      soccer surfaces at all: Kalshi names soccer series by
                      COMPETITION (`KXEPL...`, `KXUCL...`), never by the word
                      soccer, so there is no token to add until we have seen
                      the real prefixes.
      - `market=None` the sport is known and the STAT is not in `market_keys`.
                      A spelling to add, and until it is added the series is
                      refused rather than guessed at.

    Bounded by the shape of the pattern: only titles ending "Player <stat>"
    reach the list, which is a small subset of 13,389 series.
    """
    from syndicate.features.shared.market_keys import canonical_market_key

    found: list[dict[str, Any]] = []
    for ticker, title in (titles or {}).items():
        text = str(title or "").strip()
        match = _PLAYER_PROP_TITLE.search(text)
        if not match:
            continue
        stat = match.group("stat").strip()
        sport = sport_for_ticker(ticker)
        found.append(
            {
                "ticker": str(ticker).strip().upper(),
                "title": text,
                "stat": stat,
                "sport": sport,
                "market": canonical_market_key(sport, stat) if sport else None,
            }
        )
    found.sort(key=lambda c: (c["sport"] or "~unmapped", c["ticker"]))
    return found


def game_market_from_title(title: Any) -> str | None:
    """The game-line market a series title names, or None.

    Kalshi prefixes every title with the competition -- "Women's Pro Basketball
    1st Quarter Total" -- so the market is the TAIL, not the whole string. The
    longest tail that resolves wins, because "Total" and "1st Quarter Total"
    both resolve and only the longer one is right.

    Bounded at four words: the longest real phrase is "1st Quarter Spread" at
    three, and letting it run further would start swallowing competition names
    that happen to end in a market word.
    """
    from syndicate.features.shared.market_keys import canonical_game_market

    words = str(title or "").strip().split()
    if not words:
        return None
    for size in range(min(4, len(words)), 0, -1):
        resolved = canonical_game_market(" ".join(words[-size:]))
        if resolved:
            return resolved
    return None


def auto_game_series_from_catalogue(titles: Mapping[str, Any]) -> dict[str, str]:
    """Game-line series Kalshi lists that we can name -- totals, spreads,
    moneylines, and their quarter/half/period and alternate forms.

    SEPARATE FROM THE PLAYER-PROP DISCOVERY because the two have different
    identities and different risks. A prop names a human and a human plays one
    game a day, so its title is a complete identity. A game line names no team
    at all, so it can only be placed once the EVENT is resolved from the
    ticker -- which is why `kalshi_board_join` keeps these behind
    `SYNDICATE_KALSHI_GAME_LINES` and refuses an unresolved one by name.

    Registering the series is therefore not the same as agreeing to bet it. It
    only makes the market legible enough to be counted.
    """
    found: dict[str, str] = {}
    for ticker, title in (titles or {}).items():
        key = str(ticker).strip().upper()
        if key in SERIES_OUT_OF_SCOPE:
            continue
        sport = sport_for_ticker(key)
        if not sport and soccer_league_from_title(title) is not None:
            sport = "soccer"
        if not sport:
            continue
        if game_market_from_title(title) is None:
            continue
        found[key] = sport
    return found


def sport_for_series(series: Any) -> str | None:
    """The sport, or None. Hand registry first, then anything discovery added.

    Discovery writes into `_DISCOVERED` rather than into `SERIES_SPORT`, so a
    hand-written entry always wins and the two never become indistinguishable
    -- "we chose this" and "a title matched" are different confidence levels.
    """
    key = str(series or "").strip().upper()
    return SERIES_SPORT.get(key) or _DISCOVERED.get(key)


_DISCOVERED: dict[str, str] = {}


def register_discovered(found: Mapping[str, str]) -> dict[str, Any]:
    """Add auto-discovered series. Reports what was ADDED, not what was seen.

    Idempotent, and never overwrites a hand-written entry.
    """
    added = {
        ticker: sport
        for ticker, sport in (found or {}).items()
        if ticker not in SERIES_SPORT and _DISCOVERED.get(ticker) != sport
    }
    _DISCOVERED.update(added)
    return {"added": added, "total_discovered": len(_DISCOVERED)}


def all_series() -> dict[str, str]:
    """Every series we price: hand-registered plus discovered."""
    return {**_DISCOVERED, **SERIES_SPORT}


def threshold_to_line(threshold: Any) -> float | None:
    """Kalshi "N+" -> the board's half-point line. 7+ -> 6.5.

    The single most mismatch-prone number in this integration: matching 7+
    against a line of 7.0 finds nothing, and matching it against 7.5 finds a
    DIFFERENT bet and prices it confidently.
    """
    try:
        value = int(threshold)
    except (TypeError, ValueError):
        return None
    return float(value) - 0.5


# Kalshi's quarter/half token -> the board's suffix. Kept separate from
# `_INNINGS_PERIOD` because the board spells baseball and football periods
# differently (`spreads_1st_5_innings` vs `spreads_q1`) and one table would
# invite joining a quarter line to a full-game row.
_PERIOD_TOKEN = {
    "1q": "q1", "2q": "q2", "3q": "q3", "4q": "q4",
    "1h": "h1", "2h": "h2",
}


def _direction(word: Any) -> str:
    """`more than` -> `over`, `less than` -> `under`, otherwise verbatim.

    Kalshi words the same wager three ways and only one was read. There is no
    other reading available for "wins by more than 2.5 goals", so this is a
    synonym table rather than an interpretation.
    """
    token = " ".join(str(word or "").strip().lower().split())
    if token == "more than":
        return "over"
    if token == "less than":
        return "under"
    return token


def _parse_title(title: str) -> dict[str, Any] | None:
    """Which grammar reads this title, and what it says. None if none does.

    Ordered most-specific first. `_TEAM_SPREAD` must be tried before
    `_MONEYLINE`, because "Will the Giants win by over 2.5 runs?" contains
    "win" and a looser moneyline pattern would swallow it -- and a spread read
    as a moneyline is a bet on a different outcome at a confident price.
    """
    match = _PLAYER_THRESHOLD.match(title)
    if match:
        return {
            "grammar": GRAMMAR_PLAYER_THRESHOLD,
            "subject": match.group("player").strip(),
            "stat_text": match.group("stat").strip(),
            "line": threshold_to_line(match.group("threshold")),
            "side": "over",
        }

    # BEFORE `_TEAM_SPREAD` and `_MONEYLINE`. "Texas wins first 5 innings by
    # over 2.5 runs?" contains "wins", and a looser pattern reading it as a
    # moneyline would price the game winner as though it were a run line.
    if _NEITHER_TEAM_WINS.match(title):
        # Readable and deliberately unpriceable -- the draw leg of a three-way,
        # same reasoning as `_INNINGS_TIE`. Returning None keeps it refused;
        # the pattern exists so it is refused as a KNOWN shape rather than
        # counted as a title nobody has looked at.
        return None

    match = _TEAM_SPREAD_WINS_BY.match(title)
    if match:
        innings = match.group("innings")
        period = _INNINGS_PERIOD.get(str(innings)) if innings else None
        if innings and period is None:
            # A period the board has no key for. Refused rather than flattened
            # onto the full-game spread, which is a different wager.
            return None
        if period is None and match.group("period"):
            # A quarter/half token ("1Q", "2H"). The board's own suffix, via
            # the shared table -- a spelling only Kalshi's side understands
            # would join to nothing.
            period = _PERIOD_TOKEN.get(match.group("period").strip().lower())
            if period is None:
                return None
        return {
            "grammar": GRAMMAR_TEAM_SPREAD,
            "subject": match.group("team").strip(),
            "stat_text": f"spreads_{period}" if period else "spreads",
            "line": float(match.group("line")),
            "side": _direction(match.group("direction")),
        }

    match = _PERIOD_TOTAL.match(title)
    if match:
        period = _INNINGS_PERIOD.get(str(match.group("innings")))
        if period is None:
            return None
        return {
            "grammar": GRAMMAR_TEAM_TOTAL,
            # Names no team -- the game comes from the ticker.
            "subject": None,
            "stat_text": f"totals_{period}",
            "line": float(match.group("line")),
            "side": match.group("direction").strip().lower(),
        }

    match = _TEAM_SCORES.match(title)
    if match:
        return {
            "grammar": GRAMMAR_TEAM_SPREAD,
            "subject": match.group("team").strip(),
            # A TEAM total, not the game total -- a different market, and
            # conflating them would price one side's runs as both sides'.
            "stat_text": "team_totals",
            "line": float(match.group("line")),
            "side": match.group("direction").strip().lower(),
        }

    if _INNINGS_TIE.match(title):
        # Readable and deliberately unpriceable -- see the pattern's comment.
        return None

    match = _TEAM_SPREAD.match(title)
    if match:
        return {
            "grammar": GRAMMAR_TEAM_SPREAD,
            "subject": match.group("team").strip(),
            "stat_text": "spreads",
            "line": float(match.group("line")),
            "side": match.group("direction").strip().lower(),
        }

    match = _TEAM_TOTAL.match(title)
    if match:
        return {
            "grammar": GRAMMAR_TEAM_TOTAL,
            # A total names no team. The GAME is in `event_ticker`, which is why
            # this grammar cannot be joined by title alone -- see the note on
            # `needs_event_identity` below.
            "subject": None,
            # THE STAT, VERBATIM, and this used to be the string "totals".
            #
            # The pattern is `Over <line> <anything>?`, so hardcoding the market
            # meant "Over 4.5 corners?" and "Over 77.5 1st half points scored?"
            # both became FULL-GAME point/run totals. `total_market_from_stat`
            # resolves it against the sport's scoring unit in `classify_market`,
            # which is the only place the sport is known.
            "stat_text": match.group("stat").strip(),
            "line": float(match.group("line")),
            "side": match.group("direction").strip().lower(),
        }

    match = _MONEYLINE.match(title)
    if match:
        return {
            "grammar": GRAMMAR_MONEYLINE,
            "subject": match.group("team").strip(),
            "stat_text": "h2h",
            "line": None,
            "side": "yes",
        }
    return None


# Grammars whose title does NOT identify the game. A player prop names a human,
# and a human plays one game a day, so (player, market, line) is a complete
# identity. "Over 7.5 runs scored?" names neither team -- joining it needs
# Kalshi's `event_ticker` mapped to our event id, which does not exist yet.
# Flagged rather than silently attempted: a total joined to the wrong game is a
# confidently-priced bet on strangers.
_NEEDS_EVENT_IDENTITY = frozenset({GRAMMAR_TEAM_TOTAL, GRAMMAR_TEAM_SPREAD, GRAMMAR_MONEYLINE})


def classify_market(market: Mapping[str, Any]) -> dict[str, Any]:
    """One Kalshi market -> what bet it is, or a NAMED reason we cannot say.

    Never raises and never guesses. The refusal reasons are the work queue:
    `unmapped_series` says add a registry line, `stat_not_in_market_vocabulary`
    says add a `market_keys` entry, and those are different jobs.
    """
    from syndicate.features.shared.kalshi_client import is_combinatorial_series
    from syndicate.features.shared.market_keys import (
        canonical_market_key,
        total_market_from_stat,
    )

    series = str(market.get("series") or "").strip().upper()
    if is_combinatorial_series(series):
        return {"status": "refused", "reason": REASON_COMBINATORIAL, "series": series}
    if series in SERIES_OUT_OF_SCOPE:
        return {
            "status": "refused",
            "reason": REASON_OUT_OF_SCOPE,
            "series": series,
            "detail": SERIES_OUT_OF_SCOPE[series],
        }

    sport = sport_for_series(series)
    if sport is None:
        return {"status": "refused", "reason": REASON_UNMAPPED_SERIES, "series": series}

    parsed = _parse_title(str(market.get("title") or ""))
    if parsed is None:
        return {"status": "refused", "reason": REASON_UNREADABLE_TITLE, "series": series}

    # A GAME TOTAL IS RESOLVED BY ITS UNIT, not by the general vocabulary. The
    # `_TEAM_TOTAL` grammar matches `Over <line> <anything>?`, so its tail has
    # to be checked against what this sport's total actually counts -- runs,
    # points, goals -- or a corners line prices as a goals line. The other
    # totals grammar (`_PERIOD_TOTAL`, "First 5 innings: ...") has already
    # produced a `totals_*` key and is passed through untouched.
    stat_text = str(parsed["stat_text"])
    if parsed["grammar"] == GRAMMAR_TEAM_TOTAL and not stat_text.startswith("totals"):
        market_key = total_market_from_stat(sport, stat_text)
    else:
        market_key = canonical_market_key(sport, stat_text)
    if market_key is None:
        return {
            "status": "refused",
            "reason": REASON_UNMAPPED_STAT,
            "series": series,
            "sport": sport,
            # The stat text VERBATIM, so the `market_keys` entry to add is
            # readable straight off the log line.
            "detail": parsed["stat_text"],
        }

    return {
        "status": "ok",
        "series": series,
        "sport": sport,
        "market": market_key,
        "grammar": parsed["grammar"],
        "subject": parsed["subject"],
        "line": parsed["line"],
        "side": parsed["side"],
        "ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        # True means the title alone cannot say WHICH GAME this is. The join
        # must refuse these until an event mapping exists.
        "needs_event_identity": parsed["grammar"] in _NEEDS_EVENT_IDENTITY,
        # The league whose club map resolves this market's team names. `WSH` is
        # the Nationals in mlb and the Mystics in wnba.
        "sport": sport,
    }


def unmapped_series(markets) -> dict[str, Any]:
    """What Kalshi lists that we cannot yet price, by series, with an example.

    THE WORK QUEUE, and the reason discovery is worth running at all. A count of
    unmapped markets says nothing actionable; a series name beside a sample
    title says exactly which registry line to add and what its titles look like.
    """
    seen: dict[str, dict[str, Any]] = {}
    for market in markets:
        verdict = classify_market(market)
        if verdict.get("status") == "ok":
            continue
        reason = str(verdict.get("reason"))
        if reason in {REASON_COMBINATORIAL, REASON_OUT_OF_SCOPE}:
            # Known and deliberately excluded -- keeping them here would drown
            # the queue in things nobody intends to do.
            continue
        series = str(verdict.get("series") or "<absent>")
        entry = seen.setdefault(
            series,
            {"count": 0, "reason": reason, "sample_title": str(market.get("title") or "")[:80]},
        )
        entry["count"] += 1
        if verdict.get("detail") and "detail" not in entry:
            entry["detail"] = verdict["detail"]
    return dict(sorted(seen.items(), key=lambda kv: -kv[1]["count"]))
