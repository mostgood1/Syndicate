"""Canonical market keys — the join key between our board and any odds feed (#224).

Step 3 of `docs/ai_context/plan_one_opportunity_pipeline.md`.

THE MEASUREMENT THAT MOTIVATED THIS
-----------------------------------
`/api/ops/opportunity-contract/status`, first reading 2026-08-06:
`missing_market_key` was **100% of every row, in every lane, in both sports** --
106/106 game candidates, 46/46 prop sources, 45/45 dashboard rows. Every board
row carried only a display string ("Hits", "Total Bases", "Moneyline") while the
odds log keys on `batter_hits`, `batter_total_bases`, `h2h`. Nothing could join.

The keys mostly exist upstream (MLB prop rows carry `prop: "batter_total_bases"`,
rail sources carry `stat`), they were just never carried to the board. This
module is the one place that decides what canonical means, so producers thread a
key rather than each inventing one.

WHY OddsAPI's VOCABULARY
------------------------
Because that is what the quote log is keyed on, and the quote log is what a
canonical key has to join TO. Choosing our own vocabulary would mean translating
at every read instead of once at production.

NOT A PARSER OF DISPLAY TEXT
----------------------------
`canonical_market_key` takes a candidate key or a stat name. It deliberately
returns None rather than guessing from free text: a wrong key silently joins a
bet to another market's price, which is worse than an unjoined row and is exactly
the class of error #217 fixed by making identity a hard filter.
"""

from __future__ import annotations

from typing import Any

# Stat/label vocabulary -> OddsAPI market key. Left side is what our producers
# actually emit (checked against live rail sources and prop artifacts); right
# side is what `book_quotes` is keyed on.
_MLB: dict[str, str] = {
    "hits": "batter_hits",
    "batter_hits": "batter_hits",
    "total_bases": "batter_total_bases",
    "total bases": "batter_total_bases",
    "batter_total_bases": "batter_total_bases",
    "home_runs": "batter_home_runs",
    "home runs": "batter_home_runs",
    "hr": "batter_home_runs",
    "batter_home_runs": "batter_home_runs",
    "rbis": "batter_rbis",
    "rbi": "batter_rbis",
    "batter_rbis": "batter_rbis",
    "runs": "batter_runs_scored",
    "runs_scored": "batter_runs_scored",
    "batter_runs_scored": "batter_runs_scored",
    "hits_runs_rbis": "batter_hits_runs_rbis",
    "batter_hits_runs_rbis": "batter_hits_runs_rbis",
    # HOW KALSHI ACTUALLY WRITES IT, and the two underscored forms above did
    # not cover it. MEASURED 2026-08-25T20:33:06Z, on the deploy that had
    # registered `KXMLBHRR` twelve minutes earlier:
    #
    #   GAP series=KXMLBHRR count=136 reason=stat_not_in_market_vocabulary
    #       detail='hits + runs + RBIs'
    #       sample='William Contreras: 5+ hits + runs + RBIs?'
    #
    # 136 markets -- the LARGEST single MLB prop family on the venue -- and
    # every one of them refused. This is exactly the failure the `player_threes`
    # block below already documents: the series title ("Player Hits + Runs +
    # RBIs") is not what the MARKET titles say, so a registered series whose
    # markets all refuse is indistinguishable from a series Kalshi does not
    # list. Registering a series and reading its markets are two different
    # gates and this one has now cost us twice.
    #
    # `_normalize` lowercases and collapses whitespace but does NOT strip `+`,
    # so the spaced and unspaced forms are different keys and both are listed.
    # WIDENING CANNOT MISMAP: no other baseball market means hits+runs+RBIs.
    # Guessing at Kalshi's exact wording and adding only that is what left
    # `player_threes` refusing, so the near spellings go in together.
    "hits + runs + rbis": "batter_hits_runs_rbis",
    "hits + runs + rbi": "batter_hits_runs_rbis",
    "hits+runs+rbis": "batter_hits_runs_rbis",
    "hits+runs+rbi": "batter_hits_runs_rbis",
    "hits runs rbis": "batter_hits_runs_rbis",
    "hits runs and rbis": "batter_hits_runs_rbis",
    "hits, runs and rbis": "batter_hits_runs_rbis",
    "hits, runs + rbis": "batter_hits_runs_rbis",
    "h+r+rbi": "batter_hits_runs_rbis",
    "hrr": "batter_hits_runs_rbis",
    # ------------------------------------------------------------------
    # STOLEN BASES. `KXMLBSB` is registered in `kalshi_catalogue` alongside
    # this entry; without the entry the series would register and then refuse
    # every market, which is the KXMLBHRR failure directly above.
    #
    #   GAP series=KXMLBSB count=44 reason=unmapped_series
    #       sample='William Contreras: 1+ stolen bases?'
    #                                   [2026-08-25T20:33:06Z]
    #
    # `batter_stolen_bases` is NOT invented here -- it is the key this repo
    # already uses (`tests/test_bet_status_mlb_gamepk.py` resolves an order on
    # it). `tests/test_mlb_ladders_build.py` lists it in `known_unfed`: the MLB
    # sim carries the market and nothing feeds it a price. This gives it one.
    # ------------------------------------------------------------------
    "stolen_bases": "batter_stolen_bases",
    "stolen bases": "batter_stolen_bases",
    "stolen base": "batter_stolen_bases",
    "sb": "batter_stolen_bases",
    "batter_stolen_bases": "batter_stolen_bases",
    "strikeouts": "strikeouts",
    "pitcher_strikeouts": "strikeouts",
    "outs": "outs",
    "outs_recorded": "outs",
    "outs recorded": "outs",
    "pitcher_outs": "outs",
    "earned_runs": "earned_runs",
    "earned runs": "earned_runs",
    "pitcher_earned_runs": "earned_runs",
    "walks_allowed": "walks_allowed",
    "walks allowed": "walks_allowed",
    "pitcher_walks": "walks_allowed",
    "hits_allowed": "hits_allowed",
    "hits allowed": "hits_allowed",
    "pitcher_hits_allowed": "hits_allowed",
}

_BASKETBALL: dict[str, str] = {
    "pts": "player_points",
    "points": "player_points",
    "player_points": "player_points",
    "reb": "player_rebounds",
    "rebounds": "player_rebounds",
    "player_rebounds": "player_rebounds",
    "ast": "player_assists",
    "assists": "player_assists",
    "player_assists": "player_assists",
    "threes": "player_threes",
    "3pm": "player_threes",
    "player_threes": "player_threes",
    "pra": "player_points_rebounds_assists",
    "pr": "player_points_rebounds",
    "pa": "player_points_assists",
    "ra": "player_rebounds_assists",
    "player_points_rebounds_assists": "player_points_rebounds_assists",
    # The tail the counter was still reporting: 2 of 18 WNBA rows. Taken from
    # the markets the WNBA quote log actually carries (measured 2026-08-06:
    # player_points/rebounds/assists/threes/points_rebounds_assists/
    # points_rebounds/points_assists/double_double) plus the standard box-score
    # codes our rails emit, rather than from another production read -- the web
    # service began returning 502 under repeated dashboard rebuilds and is not
    # worth destabilising for a two-row lookup.
    "blk": "player_blocks",
    "blocks": "player_blocks",
    "stl": "player_steals",
    "steals": "player_steals",
    "to": "player_turnovers",
    "tov": "player_turnovers",
    "turnovers": "player_turnovers",
    "dd": "player_double_double",
    "double_double": "player_double_double",
    "double double": "player_double_double",
    "td": "player_triple_double",
    "triple_double": "player_triple_double",
    "triple double": "player_triple_double",
    "fg3m": "player_threes",
    "3s": "player_threes",
    # EVERY WAY A MARKET TITLE SPELLS A MADE THREE. `KXWNBA3PT` is
    # hand-registered in `kalshi_catalogue` and its comment says "market_keys
    # resolves all three for wnba" -- true of the series title ("Player
    # Threes") and NOT of the market titles, which are worded per market and
    # were refusing `stat_not_in_market_vocabulary` on anything but the bare
    # word. A registered series whose markets all refuse is indistinguishable
    # from a series Kalshi does not list, which is the absence/failure
    # confusion this integration keeps paying for.
    #
    # Widening a vocabulary that already resolves the stat cannot mismap
    # anything: no other basketball market means "three pointer". The reverse
    # -- guessing at Kalshi's exact wording and adding only that -- is what
    # left this refusing in the first place.
    "three pointers": "player_threes",
    "three pointers made": "player_threes",
    "three-pointers": "player_threes",
    "three-pointers made": "player_threes",
    "3 pointers": "player_threes",
    "3 pointers made": "player_threes",
    "3-pointers": "player_threes",
    "3-pointers made": "player_threes",
    "3pt": "player_threes",
    "3pt made": "player_threes",
    "3pts": "player_threes",
    "threes made": "player_threes",
    "made threes": "player_threes",
    "three point field goals": "player_threes",
    "three point field goals made": "player_threes",
}

# --------------------------------------------------------------------------
# PERIODS AND ALTERNATES, added 2026-08-24.
#
# Kalshi lists a game's intervals as their own series -- `KXWNBA1QTOTAL`
# ("1st Quarter Total"), `KXWNBA2HSPREAD` ("2nd Half Spread"), `KXWNBA2H`
# ("2nd Half Winner") -- and the board already carries the matching keys
# (`totals_q1`, `spreads_h2`, `h2h_h2`). Nothing joined them because the
# vocabulary stopped at the full-game words.
#
# SUFFIXES ARE THE BOARD'S, NOT INVENTED: q1..q4 quarters, h1/h2 halves,
# p1..p3 hockey periods, `_alt` for alternate lines. All are already in use in
# this repo, which is what makes them the right spelling -- a period key that
# only Kalshi's side understands joins to nothing.
_PERIOD_SUFFIX: dict[str, str] = {
    "1st quarter": "q1", "first quarter": "q1", "1q": "q1", "q1": "q1",
    "2nd quarter": "q2", "second quarter": "q2", "2q": "q2", "q2": "q2",
    "3rd quarter": "q3", "third quarter": "q3", "3q": "q3", "q3": "q3",
    "4th quarter": "q4", "fourth quarter": "q4", "4q": "q4", "q4": "q4",
    "1st half": "h1", "first half": "h1", "1h": "h1", "h1": "h1",
    "2nd half": "h2", "second half": "h2", "2h": "h2", "h2": "h2",
    "1st period": "p1", "first period": "p1", "p1": "p1",
    "2nd period": "p2", "second period": "p2", "p2": "p2",
    "3rd period": "p3", "third period": "p3", "p3": "p3",
    # "FULL GAME" IS THE ABSENCE OF A PERIOD, mapped to the empty suffix so
    # `total_market_from_stat` returns a bare `totals`. Kalshi words its NFL
    # game total "Full Game: over 58.5 points scored?", which names the whole
    # game the way every other entry here names a part of one.
    #
    # Measured 2026-08-26T01:49:32Z, the tick that first read these titles:
    #
    #   GAP series=KXNFLTOTAL count=304 reason=stat_not_in_market_vocabulary
    #       detail='Full Game points scored'
    #
    # 304 markets, parsed and then refused one gate later for want of this
    # line -- which is exactly the shape the coverage audit records for
    # KXMLBHRR ("the series registered, was fetched, and then every market
    # refused one gate later"). The refusal was correct: `totals_full game` is
    # not a board key and inventing one would have been worse.
    "full game": "", "fullgame": "", "full-game": "",
}

# What a GAME TOTAL counts, per sport. The unit and nothing else.
#
# THIS EXISTS BECAUSE THE TOTALS GRAMMAR THREW ITS STAT AWAY. Kalshi words a
# game total "Over 7.5 runs scored?", and `kalshi_catalogue._TEAM_TOTAL`
# matched `Over <line> <anything>?` and then hardcoded the market as `totals`
# -- so the stat was parsed and discarded. Every one of these became a
# full-game points/runs total:
#
#     "Over 4.5 corners?"                  -> totals 4.5
#     "Over 77.5 1st half points scored?"  -> totals 77.5
#     "Over 2.5 1H goals scored"           -> totals 2.5   (real, KXUCL1HTOTAL)
#
# The first is a WRONG BET, not a miscount: soccer boards carry a goals total
# at 4.5, so our goals model would have priced a corners market and the join
# would have looked clean. The second is the same shape one period over -- an
# NBA 1st-half total at 110.5 against a full-game line at 110.5 matches on
# (market, line) and is a bet on a different thing.
#
# A game total is the only market where the unit is implicit, which is why it
# was easy to drop: nobody writes "goals" on a totals board row. So the unit is
# checked HERE and the period is kept, rather than the tail being trusted.
_TOTAL_UNIT: dict[str, frozenset[str]] = {
    "mlb": frozenset({"run", "runs"}),
    "nba": frozenset({"point", "points"}),
    "wnba": frozenset({"point", "points"}),
    "ncaab": frozenset({"point", "points"}),
    "nfl": frozenset({"point", "points"}),
    "ncaaf": frozenset({"point", "points"}),
    "nhl": frozenset({"goal", "goals"}),
    "soccer": frozenset({"goal", "goals"}),
}

# Words Kalshi appends that carry no meaning for the key. "scored" is the only
# one seen so far and it is stripped rather than enumerated into every unit.
_TOTAL_FILLER = ("scored", "in total", "total")


# NON-SCORING SOCCER TOTALS THAT ARE REAL BOARD MARKETS IN THEIR OWN RIGHT.
#
# `_TOTAL_UNIT` refuses any unit that is not the sport's scoring unit, and that
# refusal is CORRECT and stays: "Over 4.5 corners?" priced as a 4.5 GOALS total
# is a bet on a different event, and the comment above records exactly that
# trap. But refusing is only right while we have nowhere to put it -- and we
# do. MEASURED 2026-08-28 from `KALSHI_BOARD_JOIN board_market_vocabulary`:
#
#     alternate_totals_corners  239   <- the LARGEST board market of any sport
#     totals                    211
#     h2h                       156
#     btts                       44
#
# Corners is bigger than goals totals and bigger than every moneyline on the
# board, and every one of those rows was unreachable from Kalshi -- 400 markets
# a build refused `stat_not_in_market_vocabulary` with the stat named.
#
# MAPPED TO ITS OWN MARKET, NEVER TO `totals`. That separation is the whole
# safety property: a corners line and a goals line can sit at the same number,
# so a shared key would join them and look clean. Different key, different bet.
_NON_SCORING_TOTAL_MARKET: dict[tuple[str, str], str] = {
    # "Over 4.5 corners?" -- the stat text production actually sends, recorded
    # verbatim in the `_TOTAL_UNIT` comment above from a real refused market.
    ("soccer", "corners"): "alternate_totals_corners",
    ("soccer", "corner"): "alternate_totals_corners",
}


def non_scoring_total_market(sport: Any, stat_text: Any) -> str | None:
    """A total whose UNIT is not the sport's scoring unit but IS a board market.

    Returns None for anything unmapped, so an unrecognised unit keeps landing
    in `stat_not_in_market_vocabulary` by name rather than being folded into
    the nearest market that happens to share a line.

    BTTS IS DELIBERATELY ABSENT. The board carries 44 `btts` rows and Kalshi
    lists the family (`KXLALIGA1HBTTS` was user-confirmed 2026-08-25), but no
    BTTS title has appeared in `unreadable_titles` yet, so its wording is
    UNKNOWN. This module's own history is the argument for waiting: three
    grammars were once written against an imagined phrasing and matched NONE of
    production. The instrument already prints one title per series, so the
    evidence arrives on its own.
    """
    sport_key = str(sport or "").strip().lower()
    token = " ".join(str(stat_text or "").strip().lower().split())
    for filler in _TOTAL_FILLER:
        if token.endswith(" " + filler):
            token = token[: -len(filler) - 1].strip()
    return _NON_SCORING_TOTAL_MARKET.get((sport_key, token))


def total_market_from_stat(sport: Any, stat_text: Any) -> str | None:
    """"1st half points scored" -> `totals_h1`. A corners line -> None.

    Returns None for ANY unit that is not this sport's scoring unit, and that
    refusal is the point: `classify_market` turns it into
    `stat_not_in_market_vocabulary` with the stat text verbatim, so a real
    market we cannot yet price lands in the work queue by name instead of
    being priced as something else.
    """
    units = _TOTAL_UNIT.get(str(sport or "").strip().lower())
    if not units:
        return None
    token = " ".join(str(stat_text or "").strip().lower().split())
    if not token:
        return None

    period = ""
    for phrase, suffix in sorted(_PERIOD_SUFFIX.items(), key=lambda kv: -len(kv[0])):
        if token == phrase:
            return None
        if token.startswith(phrase + " "):
            period, token = suffix, token[len(phrase) :].strip()
            break

    for filler in _TOTAL_FILLER:
        if token.endswith(" " + filler):
            token = token[: -len(filler)].strip()
        if token.startswith(filler + " "):
            token = token[len(filler) :].strip()

    if token not in units:
        return None
    return f"totals_{period}" if period else "totals"


# The market word, once the period has been stripped off the front.
_GAME_CORE: dict[str, str] = {
    "winner": "h2h",
    "moneyline": "h2h",
    "money line": "h2h",
    "ml": "h2h",
    "h2h": "h2h",
    # "Game" is Kalshi's OWN word for the straight moneyline series, not a
    # synonym anyone here invented. Measured 2026-08-24: KXMLBGAME's real
    # series-level title is exactly "Professional Baseball Game" (confirmed
    # against a live $6.7M-volume market the user found on kalshi.com that
    # this vocabulary gap was silently dropping) -- no "moneyline"/"winner"
    # word at all, so `canonical_game_market` returned None and the series
    # was never registered, never fetched, never priced. The same "<Sport>
    # Game" pattern is Kalshi's title for the moneyline series on EVERY
    # sport carried here (KXNFLGAME "Professional Football Game", KXNBAGAME
    # "Pro Basketball Game", KXNHLGAME "NHL Game", KXNCAAFGAME "College
    # Football Game", KXMLSGAME "Major League Soccer Game", ...) -- this was
    # not an MLB-only gap.
    "game": "h2h",
    "spread": "spreads",
    "spreads": "spreads",
    "ats": "spreads",
    "run line": "spreads",
    "runline": "spreads",
    "puck line": "spreads",
    "puckline": "spreads",
    "total": "totals",
    "totals": "totals",
    "over/under": "totals",
    "ou": "totals",
}


def canonical_game_market(text: Any) -> str | None:
    """A game-line market name, period and alternate included, or None.

    Separate from `canonical_market_key` because the grammar is different: this
    one PARSES rather than looks up, since "2nd Half Spread" is a period and a
    market word rather than a phrase any table could enumerate.

    None is a real answer and the caller must refuse on it. A game line joined
    to the wrong period is the same class of error as one joined to the wrong
    game -- a confidently-priced bet on something else entirely.
    """
    token = _normalize(text)
    if not token:
        return None

    alt = False
    for marker in ("alternate ", "alt "):
        if token.startswith(marker):
            alt, token = True, token[len(marker):].strip()
    for marker in (" alternate", " alt"):
        if token.endswith(marker):
            alt, token = True, token[: -len(marker)].strip()

    # THREE-WAY IS ITS OWN MARKET, not a moneyline with a footnote. A draw is a
    # third outcome, so pricing it as `h2h` would misstate every soccer line.
    three_way = False
    for marker in ("3 way", "three way", "3way"):
        if marker in token:
            three_way = True
            token = token.replace(marker, " ").strip()

    period = ""
    for phrase, suffix in _PERIOD_SUFFIX.items():
        if token.startswith(phrase + " "):
            period, token = suffix, token[len(phrase):].strip()
            break

    core = _GAME_CORE.get(token)
    if core is None:
        return None
    if three_way:
        # Only a moneyline has a three-way form.
        return "h2h_3_way" if core == "h2h" and not period else None
    if period:
        # `_alt` and a period together are not a shape the board carries, so it
        # is refused rather than spelled into existence.
        return None if alt else f"{core}_{period}"
    return f"{core}_alt" if alt else core


# Game-level markets are the same three words in every sport, which is why they
# are not per-sport. "ATS"/"run line"/"puck line" are the same wager as a spread.
_GAME: dict[str, str] = {
    "moneyline": "h2h",
    "money line": "h2h",
    "ml": "h2h",
    "h2h": "h2h",
    "spread": "spreads",
    "spreads": "spreads",
    "ats": "spreads",
    "run line": "spreads",
    "runline": "spreads",
    "puck line": "spreads",
    "puckline": "spreads",
    "total": "totals",
    "totals": "totals",
    "over/under": "totals",
    "ou": "totals",
}

# --------------------------------------------------------------------------
# FOOTBALL and SOCCER, added 2026-08-24 to open Kalshi beyond MLB/WNBA.
#
# Until now only mlb/nba/wnba had any vocabulary here, which is why the Kalshi
# boot census read `KALSHI_SPORT NFL ticker_substring_n=317 classified_n=0`:
# 317 NFL series listed and not one classified. `auto_series_from_catalogue`
# requires `canonical_market_key(sport, stat)` to resolve before it will
# register a series, so a sport with no map can never discover anything however
# player-shaped its titles are. The gap was in this file, not in the discovery.
#
# The VALUES are OddsAPI's keys, because that is what the board emits and the
# join compares against -- taken from what the repo already uses
# (`player_pass_yds`, `player_reception_yds`, `player_anytime_td`), never
# invented here. The KEYS are the stat wordings a title might carry; Kalshi's
# exact wording is reported by `prop_candidates` rather than assumed, and any
# spelling this table misses shows up there as an unmapped stat instead of
# silently joining to the wrong market.
_FOOTBALL: dict[str, str] = {
    "passing yards": "player_pass_yds",
    "pass yards": "player_pass_yds",
    "pass yds": "player_pass_yds",
    "passing touchdowns": "player_pass_tds",
    "passing tds": "player_pass_tds",
    "pass tds": "player_pass_tds",
    "passing attempts": "player_pass_attempts",
    "pass attempts": "player_pass_attempts",
    "passing completions": "player_pass_completions",
    "completions": "player_pass_completions",
    "interceptions thrown": "player_pass_interceptions",
    "passing interceptions": "player_pass_interceptions",
    "rushing yards": "player_rush_yds",
    "rush yards": "player_rush_yds",
    "rush yds": "player_rush_yds",
    "rushing attempts": "player_rush_attempts",
    "rush attempts": "player_rush_attempts",
    "carries": "player_rush_attempts",
    "receiving yards": "player_reception_yds",
    "reception yards": "player_reception_yds",
    "reception yds": "player_reception_yds",
    "receptions": "player_receptions",
    "catches": "player_receptions",
    "touchdowns": "player_anytime_td",
    "anytime touchdown": "player_anytime_td",
    "anytime td": "player_anytime_td",
    "touchdown": "player_anytime_td",
}

_SOCCER: dict[str, str] = {
    "goals": "player_goals",
    "goal": "player_goals",
    "anytime goalscorer": "player_goal_scorer_anytime",
    "goalscorer": "player_goal_scorer_anytime",
    "to score": "player_goal_scorer_anytime",
    "assists": "player_assists",
    "shots": "player_shots",
    "shots on target": "player_shots_on_target",
    "shots on goal": "player_shots_on_goal",
}

# --------------------------------------------------------------------------
# HOCKEY, added 2026-08-25.
#
# WHY THIS FILE HAD NO `nhl` KEY AND WHY THAT WAS NOT COSMETIC.
# `auto_series_from_catalogue` registers a prop series only if
# `canonical_market_key(sport, stat)` resolves first, so a sport ABSENT from
# `_BY_SPORT` can never discover a player prop however many the venue lists --
# it is the exact mechanism that held football at `KALSHI_SPORT NFL
# ticker_substring_n=317 classified_n=0` until `_FOOTBALL` was written.
#
# `_TOTAL_UNIT` already carried `nhl`, so GAME TOTALS resolved while every prop
# refused. That asymmetry is what made it read as coverage rather than as an
# absence, and it is why the gap survived a whole audit pass.
#
# Kalshi lists these today -- observed in the signed catalogue
# 2026-08-25T20:21:24Z, `[refresh_worker] KALSHI_SPORT NHL n=52`:
#
#     KXNHLSAVES   KXNHLPTS   KXNHLANYGOAL   KXNHLPLAYOFFGOALS
#
# The NHL season had not started on that date, so this map cannot be verified
# end to end against a live market until it does. Registering the vocabulary
# now is still right: without it those series cannot even reach the work queue
# by name on opening night -- they would present as "Kalshi lists no NHL
# props", which is false.
#
# THE VALUES ARE NOT INVENTED HERE. They are the keys this repo's own vendored
# NHL module already requests and recognises
# (`vendor/nhl_betting_repo/nhl_betting/data/player_props.py`), whose comment
# says they are "confirmed by provider docs and our live probes" and warns that
# an unsupported key 422s the request. `player_points` / `player_assists` /
# `player_goals` / `player_shots_on_goal` are the four it requests;
# `player_saves` and `player_blocked_shots` are in the map it parses arrivals
# with.
#
# DELIBERATELY ABSENT: the anytime-goal-scorer market, which `KXNHLANYGOAL`
# may or may not be. Its SERIES TITLE has never been observed -- only the
# ticker -- so whether it is a player prop or a team market ("will any goal be
# scored") is unknown, and this repo already carries TWO different spellings of
# that key (`player_goal_scorer_anytime` in `_SOCCER` below,
# `player_anytime_goal_scorer` in `tests/test_layer2_excluded_markets.py`).
# Guessing between them on an unread title is how a bet gets priced as a
# different bet. Left out so the series surfaces in the COVERAGE_GAPS queue BY
# NAME with its real title, which is the answer this file wants anyway.
_HOCKEY: dict[str, str] = {
    "points": "player_points",
    "pts": "player_points",
    "player_points": "player_points",
    "assists": "player_assists",
    "ast": "player_assists",
    "player_assists": "player_assists",
    "goals": "player_goals",
    "goal": "player_goals",
    "player_goals": "player_goals",
    # SOG is the box-score abbreviation and the vendored module's own canonical
    # name for this market, so both spellings resolve.
    "shots on goal": "player_shots_on_goal",
    "shots_on_goal": "player_shots_on_goal",
    "sog": "player_shots_on_goal",
    "shots": "player_shots_on_goal",
    "player_shots_on_goal": "player_shots_on_goal",
    "saves": "player_saves",
    "save": "player_saves",
    "goalie saves": "player_saves",
    "player_saves": "player_saves",
    "blocked shots": "player_blocked_shots",
    "blocks": "player_blocked_shots",
    "blk": "player_blocked_shots",
    "player_blocked_shots": "player_blocked_shots",
}

_BY_SPORT: dict[str, dict[str, str]] = {
    "mlb": _MLB,
    "nba": _BASKETBALL,
    "wnba": _BASKETBALL,
    # NCAAF shares the football vocabulary. The STATS are identical; only the
    # rosters differ, and rosters are not this table's concern.
    "nfl": _FOOTBALL,
    "ncaaf": _FOOTBALL,
    # NCAAB shares the basketball vocabulary for exactly the reason NCAAF
    # shares football's, and its absence had exactly the consequence described
    # on `_HOCKEY` above: `_TOTAL_UNIT` carries `ncaab`, so a college game
    # total resolved while every college player prop refused.
    #
    # SAFE AGAINST THE ONE REAL COLLISION IN THIS TABLE. `sport_for_ticker`
    # matches `NCAAB` as a SUBSTRING, and `KXNCAABASEBALL` -- NCAA *baseball*,
    # observed in the catalogue 2026-08-25T20:21:24Z -- contains it. That
    # series now resolves to sport `ncaab` and reaches this map, where baseball
    # stats (hits, home runs, RBIs, strikeouts) appear nowhere, so it still
    # refuses rather than pricing a baseball prop off a basketball model. A
    # test pins that, because it is the kind of thing that only stays true
    # while somebody is watching.
    "ncaab": _BASKETBALL,
    "nhl": _HOCKEY,
    "soccer": _SOCCER,
}


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("-", " ").split())


def canonical_market_key(sport: Any, *values: Any) -> str | None:
    """First value that resolves to a canonical key, else None.

    Pass candidates in order of trustworthiness -- an explicit key first, a stat
    name after, and the display label LAST if at all. Returning None is a real
    answer: `validate()` reports it and the counter records it, which is how a
    gap stays visible instead of becoming a wrong join.
    """
    sport_map = _BY_SPORT.get(_normalize(sport), {})
    for value in values:
        token = _normalize(value)
        if not token:
            continue
        underscored = token.replace(" ", "_")
        for key in (token, underscored):
            if key in _GAME:
                return _GAME[key]
            if key in sport_map:
                return sport_map[key]
        # An unmapped value that already looks like an OddsAPI key (the feed's
        # own vocabulary, e.g. a market we do not have a label for yet) is
        # accepted as-is rather than dropped -- it will join, and refusing it
        # would lose a key we already have.
        if underscored.startswith(("batter_", "pitcher_", "player_")):
            return underscored
        # GAME-LINE SPELLINGS TOO. `totals_1st_5_innings` and
        # `spreads_1st_5_innings` are the board's own keys, produced by
        # `canonical_game_market`, and the prop-only passthrough refused them --
        # so a period market the parser had just resolved correctly came back
        # `stat_not_in_market_vocabulary` one step later.
        if underscored.startswith(("totals", "spreads", "h2h", "team_totals")):
            return underscored
        # #247: strip a leading ROLE word and retry. Our boards label props by
        # role ("Hitter Hits", "Pitcher Outs") while graders and the odds feed
        # use the bare stat ("hits", "outs") -- and the table already holds the
        # bare form, so the role word was the only thing preventing the join.
        #
        # This is not cosmetic. `canonical_market_key("mlb", "Hitter Hits")`
        # returned None while `("mlb", "batter_hits")` returned batter_hits, so
        # the two sides of settlement could never agree on what market a bet was
        # in. Safe by construction: every role-stripped form either hits the
        # same entry the prefixed alias already pointed at ("batter_home_runs" ->
        # "home_runs" -> batter_home_runs) or nothing at all.
        head, _, tail = underscored.partition("_")
        if tail and head in {"hitter", "batter", "pitcher", "player"}:
            if tail in _GAME:
                return _GAME[tail]
            if tail in sport_map:
                return sport_map[tail]
    return None
