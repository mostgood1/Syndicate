"""Which OddsAPI regions a GAME-LINE call asks for. One owner, every sport.

Lifted verbatim out of `scripts/fetch_mlb_oddsapi_local.py` on 2026-08-29 so a
second sport could use it without a second copy. The mechanism, the reasoning
and the safety property below are MLB's and are unchanged -- what is new is that
NCAAF can reach them.

WHY THIS IS A SEPARATE KNOB FROM THE PROP CALLS
-----------------------------------------------
THE SPLIT IS A BILLING FACT, NOT A PREFERENCE. OddsAPI bills game lines per
REQUEST and player props per EVENT, and measured on production 2026-08-07 the
per-event families (props + segment + alternate) are **95.5% of all credits**.
So a region added to the game-line call costs roughly 30K/month, while the same
region added to the prop calls costs ~1M. Wiring both through one flat `regions`
string is what made "eu and us_ex on game lines only" inexpressible.

EXTRAS, NEVER A REPLACEMENT
---------------------------
The base `regions` is always kept, so a misconfigured value can widen coverage
but can never silently drop `us`. Unset is exactly today's behaviour. Order is
preserved so `us` stays first, and a region named twice is not billed twice.

WHY NCAAF NEEDED THIS (2026-08-29)
----------------------------------
`SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS` had exactly ONE reader -- the MLB
fetcher. `fetch_ncaaf_oddsapi_game_lines.py` takes a single `--region` off
`ODDS_API_REGION` (default `us`), so setting that env var was **inert for
NCAAF**: the value would have been present in the environment, read by nothing,
and the sharps would not have appeared. Measured the same day, NCAAF's served
book set was 11 books with **0 of 5 sharps/exchanges** -- absent are `pinnacle`
(45 events via `eu`), `novig` (51) and `prophetx` (8) via `us_ex` -- while the
board's own consensus, and therefore every market-basis edge computed against
it, was anchored on soft books alone.

Region coverage measured live, same instant, `americanfootball_ncaaf`:

    us     111 events   the 11 soft books        3 credits
    us_ex   51 events   novig, prophetx, betopenly   3 credits
    eu     111 events   pinnacle, matchbook, betfair_ex_eu, +9   3 credits

Credits are not the constraint: quota read `x-requests-remaining: 4,853,063`
during that probe.
"""

from __future__ import annotations

import os

#: The env var. Named here so the two fetchers and the tests all read the same
#: string rather than three string literals that can drift apart.
GAME_LINE_REGIONS_ENV = "SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS"

#: WNBA's own knob, and it is SEPARATE ON PURPOSE.
#:
#: WNBA has no cheap game-line call to widen. Measured 2026-09-01:
#: `fetch_basketball_oddsapi_props_local.py` makes only PER-EVENT requests
#: (`/events/{id}/markets` and `/events/{id}/odds`), and its game lines
#: (h2h/spreads/totals) ride the same per-event call as its player props. So
#: pointing WNBA at `GAME_LINE_REGIONS_ENV` would silently put `eu,us_ex` on the
#: EXPENSIVE side of the billing split this module exists to keep apart -- the
#: one costing ~1M rather than ~30K.
#:
#: It is affordable anyway, on this sport, at today's budget: quota read
#: **4,959,329 of 5,000,000 remaining (99.2% unused)** on 2026-09-01, WNBA is
#: ~0.7% of credits, and a WNBA slate is 1-6 games against MLB's ~15. But that
#: is a JUDGEMENT ABOUT WNBA'S SIZE, not the billing property the shared knob
#: encodes, so it gets its own name and can be turned off alone.
WNBA_REGIONS_ENV = "SYNDICATE_WNBA_ODDS_REGIONS"


def widened_regions(regions: str, env_var: str, *, env: "dict[str, str] | None" = None) -> str:
    """`regions` widened by `env_var`'s extras. Never narrowed.

    The merge every caller shares. `game_line_regions` and `wnba_regions` are
    thin wrappers so each one's BILLING contract stays visible at its own name.
    """
    source = os.environ if env is None else env
    extra = str(source.get(env_var) or "").strip()
    if not extra:
        return regions
    seen: set[str] = set()
    merged: list[str] = []
    for candidate in list(str(regions or "").split(",")) + list(extra.split(",")):
        name = candidate.strip().lower()
        if name and name not in seen:
            seen.add(name)
            merged.append(name)
    return ",".join(merged) or regions


def wnba_regions(regions: str, *, env: "dict[str, str] | None" = None) -> str:
    """WNBA's per-event regions. Unset is exactly today's behaviour (`us`).

    Widening this reaches novig, prophetx and betopenly via `us_ex` -- the books
    that made NCAAF's board go from 0 of 5 sharps to a real consensus. It does
    NOT reach kalshi or polymarket: `book_grid` drops those by name
    (`is_direct_feed_book`) because the direct venue feed owns them, so they
    arrive by a different route entirely.
    """
    return widened_regions(regions, WNBA_REGIONS_ENV, env=env)


#: PER-SPORT PROP REGIONS, and the per-sport part is the whole point.
#:
#: `ODDS_API_REGION` (singular) is read by SIX fetchers across four sports and
#: is unset in production, so all six default to `us`. Setting it to reach `eu`
#: on soccer props would silently widen NFL and NCAAF props too -- and props
#: bill per EVENT, the ~1M/month side of the split this module exists to keep
#: apart. One name per sport makes that decision takeable for one sport.
#:
#: Measured 2026-09-06, served board: soccer `oddsapi_props` rows were 164 of
#: 174 SINGLE-BOOK (fanduel 135, betrivers 39) while soccer rows overall carried
#: 12 books. The thinness is specific to player props, not to `us`.
PROP_REGIONS_ENV_TEMPLATE = "SYNDICATE_{sport}_PROP_REGIONS"


def prop_regions_env(sport: str) -> str:
    """The env var name for one sport's PROP-call regions."""
    return PROP_REGIONS_ENV_TEMPLATE.format(sport=str(sport or "").strip().upper())


def prop_regions(sport: str, regions: str, *, env: "dict[str, str] | None" = None) -> str:
    """`regions` widened by THIS SPORT's prop extras. Never narrowed.

    Unset is exactly today's behaviour, which is the safety property that makes
    this landable without a spend: the base `regions` is always kept, so a
    misconfigured value can widen coverage but can never silently drop `us`.

    WHAT WIDENING BUYS, AND WHAT IT COSTS. `eu` reached pinnacle, matchbook and
    betfair_ex_eu on NCAAF game lines -- real sharps against a board consensus
    that was otherwise soft-book only. On PROPS the same region is billed per
    event, so it is the ~1M/month side. Do not turn this on for a sport without
    pricing that sport's event count first.
    """
    return widened_regions(regions, prop_regions_env(sport), env=env)


#: PER-SPORT PROP BOOK LISTS (lane props-book-coverage, user 2026-10-16: "as long as we dont increase expense lets go
#: ahead"). OddsAPI bills a `bookmakers` list of up to 10 -- from ANY regions -- as ONE region, so ten named books cost
#: exactly what `regions=us` costs, and the list can reach books `us` does not have. The `us2` books (ESPN Bet, Hard
#: Rock, Fliff, Bally, betPARX) were in no props shard of any sport since 09-30.
#:
#: Measured 2026-10-16, one event + one market per sport, `x-requests-last`: this list cost 1 credit on NFL (9 books
#: back), NCAAF (7) and MLB (7) -- the same 1 credit `us` costs -- each with ESPN Bet and Hard Rock. Against what each
#: sport's props got from `us` since 10-01 it keeps every NFL and NCAAF book and drops one MLB book (MyBookie, 11% of
#: MLB prop lines). NHL has its own ten (`syndicate/local_nhl_odds.NHL_PROP_BOOKMAKERS`, with Pinnacle).
#:
#: NEVER MORE THAN 10: an 11th book bills a second region (tests/test_prop_bookmakers.py holds the line).
PROP_BOOKMAKERS = {
    sport: "draftkings,fanduel,betmgm,williamhill_us,betrivers,fanatics,bovada,betonlineag,espnbet,hardrockbet"
    for sport in ("nfl", "ncaaf", "mlb", "nba")
}       # NBA (2026-10-16, before its props start 10-20): its props ask plain `us` -- WNBA, which widens to the `us_ex`
        # exchanges through `wnba_regions`, gets no list, so ProphetX / Novig there are untouched.
# NBA TAKES PINNACLE IN BETONLINE'S SLOT (lane live-cell-scorecard, user 2026-10-25 "Add it now" via the coordinator:
# "Include Pinnacle for NBA/NFL/soccer/WNBA in the odds fetch"). NBA's game lines -- h2h, spreads, totals and the alt
# ladders -- ride this per-event call, so this list is the ONLY place NBA can see Pinnacle, and the fleet's NBA quote
# log held 0 Pinnacle quotes in 2.1M (October). An 11th book would bill a second region on every NBA event and market;
# a swap costs nothing. Measured 10-20..10-24 (fleet NBA book_quotes): betonlineag was 1.3% of NBA quotes and the ONLY
# sportsbook on 0-45 lines a day out of 5.5k-29k (~0.15%). Whether Pinnacle prices NBA PROPS through OddsAPI is
# unmeasured; its game lines are the point.
PROP_BOOKMAKERS["nba"] = (
    "draftkings,fanduel,betmgm,williamhill_us,betrivers,fanatics,bovada,pinnacle,espnbet,hardrockbet"
)
# SOCCER (lane soccer-uefa-competitions, at props-book-coverage's invitation, 2026-10-16). NOT the shared list: soccer's
# prop call has returned 8 books since 10-01 (fleet props shards, 573,710 rows), and MyBookie is 7.9% of them -- the
# shared list would drop it. So: all 8 seen, plus the two `us2` books an EPL probe showed adding coverage (ballybet,
# betparx). Pinnacle is NOT in it: whether it prices soccer props is unmeasured.
PROP_BOOKMAKERS["soccer"] = (
    "betrivers,fanduel,draftkings,betmgm,mybookieag,bovada,fanatics,williamhill_us,ballybet,betparx"
)
PROP_BOOKMAKERS_ENV_TEMPLATE = "SYNDICATE_{sport}_PROP_BOOKMAKERS"


def prop_bookmakers(sport: str, *, env: "dict[str, str] | None" = None) -> "str | None":
    """The `bookmakers` value for one sport's PROP calls, or None (ask the region, as before).

    `SYNDICATE_<SPORT>_PROP_BOOKMAKERS` overrides the list; set to "" it restores `regions` alone. A sport whose prop
    REGIONS were widened (`SYNDICATE_<SPORT>_PROP_REGIONS`) gets None: OddsAPI lets `bookmakers` override `regions`,
    and that knob's decision must keep meaning what it says."""
    environ = os.environ if env is None else env
    key = str(sport or "").strip().lower()
    if str(environ.get(prop_regions_env(key)) or "").strip():
        return None
    raw = environ.get(PROP_BOOKMAKERS_ENV_TEMPLATE.format(sport=key.upper()))
    value = PROP_BOOKMAKERS.get(key) if raw is None else raw
    return str(value or "").strip() or None


#: PER-SPORT GAME-LINE REGIONS (lane live-cell-scorecard, 2026-10-25, user "Add it now" via the coordinator).
#: `GAME_LINE_REGIONS_ENV` has two readers, MLB and NCAAF, and is `eu,us_ex` on the fleet -- which is why those two
#: sports' quote logs carry Pinnacle and NFL's and soccer's (whose game-line calls read `ODDS_API_REGION`, unset ->
#: `us`) carry none. A per-sport knob rather than a third and fourth reader of the shared one, because the cost is
#: per sport: game-line calls bill per REQUEST, markets x regions, so `eu` adds 3 credits per call, and soccer makes
#: ~4x NFL's calls (one per league per launch). Unset is exactly today's behaviour.
GAME_LINE_REGIONS_SPORT_ENV_TEMPLATE = "SYNDICATE_{sport}_GAME_LINE_REGIONS"


def sport_game_line_regions(sport: str, regions: str, *, env: "dict[str, str] | None" = None) -> str:
    """`regions` widened by `SYNDICATE_<SPORT>_GAME_LINE_REGIONS`. Never narrowed; unset = unchanged."""
    return widened_regions(regions, GAME_LINE_REGIONS_SPORT_ENV_TEMPLATE.format(sport=str(sport or "").strip().upper()),
                           env=env)


def game_line_regions(regions: str, *, env: "dict[str, str] | None" = None) -> str:
    """`regions` widened by the configured extras. Never narrowed.

    `env` is injectable so a test can prove the merge without mutating the
    process environment -- the default reads `os.environ`, which is what both
    fetchers pass through.
    """
    source = os.environ if env is None else env
    extra = str(source.get(GAME_LINE_REGIONS_ENV) or "").strip()
    if not extra:
        return regions
    seen: set[str] = set()
    merged: list[str] = []
    for candidate in list(str(regions or "").split(",")) + list(extra.split(",")):
        name = candidate.strip().lower()
        if name and name not in seen:
            seen.add(name)
            merged.append(name)
    return ",".join(merged) or regions
