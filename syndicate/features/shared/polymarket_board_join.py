"""Board row -> the Polymarket US market quoting it, and that market's price.

--------------------------------------------------------------------------
WHY THIS EXISTS
--------------------------------------------------------------------------

`portfolio_commit._venue_price_resolver` returns `(None, None)` for every venue
but Kalshi (`portfolio_commit.py:170`). So the `paper:polymarket` book has been
priced from the AGGREGATOR, not from Polymarket — a venue label on someone
else's prices. Any historical `paper:polymarket` P&L is not a Polymarket
result, and Stage D cannot rest on it.

This is Kalshi's `kalshi_board_join` for Polymarket, and it deliberately mirrors
that module's shape: two resolvers, keyed on the SAME identity the join matched
on, so a lookup can never pair a row with a price for a different bet.

--------------------------------------------------------------------------
THE SLUG IS A STRUCTURED KEY, AND THAT CHANGES THE JOIN'S CHARACTER
--------------------------------------------------------------------------

Measured 2026-08-24 across the live slate:

    aec-nfl-lac-ten-2025-11-02              moneyline
    asc-nfl-nyg-nyj-2026-08-28-pos-14pt5    spread,  +14.5
    tsc-nfl-tb-jax-2026-08-28-1q-17pt5      total,   1st quarter, 17.5
    astatc-mlb-pit-sd-2026-08-24-hits-jakman-gte2   player prop

`<prefix>-<league>-<away>-<home>-<date>[-<modifiers>]`. So the join is EXACT on
league, teams and date — not a similarity score. That matters because the
game-line join's measured failure mode was `side_not_a_team_in_this_game: 77`,
and a threshold cannot tell a miss from a wrong match. Here an unmatched row is
a fact.

It also means we never needed the teams endpoint, which 404s on this host
anyway.

--------------------------------------------------------------------------
WHAT IS REFUSED, BY NAME
--------------------------------------------------------------------------

Game lines (`h2h`, `spreads`, `totals`), plus the individually-admitted
families: `btts`, corners, and — as of 2026-09-01 — MLB PLAYER PROPS.

Player props were refused wholesale here for as long as resolving a slug token
like `jakman` to a roster name was a guess, because a prop priced by a guessed
player is a real order on the wrong person. That token is a guess NO LONGER:
the encoding was measured against the venue's own `question` text (99 ground
-truth pairs across 8 fixtures, 2026-09-01,
`.syndicate/findings_2026-09-01_polymarket_prop_census.md`) — and `jakman` is
Jake MANGUM, not any of the names a reader might have guessed. See
`_polymarket_player_token` for the rule and `_parse_player_prop` for the
admission bound. The join direction stays exact-or-refuse: we derive the token
from OUR `player_name` and require equality, so a venue token we cannot derive
is a COVERAGE miss, never a wrong-person match. `refusals` counts every drop
by reason, so coverage is diagnosable instead of merely low.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Collection, Iterable, Mapping, Sequence

__all__ = [
    "parse_slug",
    "market_web_url",
    "join_polymarket_to_board",
    "polymarket_price_resolver",
    "polymarket_ticker_resolver",
    "load_polymarket_markets",
    "MARKET_TYPE_TO_BOARD",
]

# The venue's type vocabulary -> the board's market names. Observed values only;
# an unseen type is refused rather than mapped to a plausible neighbour.
#
# DRAWABLE_OUTCOME -> h2h, added 2026-08-25: confirmed live in
# `POLYMARKET_US_GAMES` catalogue logs as a real game-market type (a 3-way
# home/draw/away shape -- soccer's moneyline). It was previously absent from
# this map entirely, which put it in `market_type_not_a_game_line` alongside
# PROP -- 5,810-6,612 of ~12,200-12,900 markets refused that way every cycle,
# the largest refusal bucket measured. Routed to the SAME generic path
# MONEYLINE already uses (`_outcome_probabilities` parses outcomes/prices
# generically; each outcome name is resolved independently via
# `team_aliases.canonical_team` downstream in `venue_quote_adapters`), so no
# type-specific parsing is added on an unconfirmed row shape -- an outcome
# that resolves to a club prices normally, and a "Draw" outcome (which no
# board `h2h` side asks for today) simply never matches anything and is
# dropped, the same way an unresolved club already is.
MARKET_TYPE_TO_BOARD: dict[str, str] = {
    "SPORTS_MARKET_TYPE_MONEYLINE": "h2h",
    "SPORTS_MARKET_TYPE_SPREAD": "spreads",
    "SPORTS_MARKET_TYPE_TOTAL": "totals",
    "SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME": "h2h",
}

# THE BOARD MARKETS THIS JOIN CAN PAIR. `MARKET_TYPE_TO_BOARD.values()` plus
# the families admitted from a slug modifier rather than a venue type.
#
# DERIVED, NOT RETYPED. The board-side gate used to read
# `MARKET_TYPE_TO_BOARD.values()` directly, so admitting BTTS on the venue side
# left the board side still refusing it -- `board_market_not_a_game_line`, one
# half of the join fixed and the other silently not. Both halves now read this
# one name, which is the property this repo keeps insisting on: two guards that
# must agree should not be two literals.
_JOINABLE_BOARD_MARKETS: frozenset[str] = frozenset(MARKET_TYPE_TO_BOARD.values()) | {
    # Polymarket types both of these as PROP. BTTS is admitted by its slug
    # modifier, corners by its question text -- see the branch in the join.
    "btts",
    "alternate_totals_corners",
}

# ---------------------------------------------------------------------------
# MLB PLAYER PROPS -- admitted per FAMILY, per LEAGUE, from measurement.
# ---------------------------------------------------------------------------
#
# Slug grammar, measured on 8 of 8 live fixtures 2026-09-01 against the
# venue's own `question` text (the field `persist_game_slate` drops; fetched
# from the public web gateway -- full evidence with all 98 (token, name)
# pairs in `.syndicate/findings_2026-09-01_polymarket_prop_census.md`;
# the implemented encoder reproduces 97 of 99, and both misses are the
# venue's own collision-extended forms, which fail SAFE -- underivable):
#
#     astatc-mlb-<away>-<home>-<date>-<family>-<playertoken>-gte<N>
#     e.g.  astatc-mlb-sd-cin-2026-09-01-hits-jacmer-gte2
#           "Will Jackson Merrill record at least 2 hits in SD vs CIN?"
#
# `gte<N>` is "at least N", so YES is the board's OVER at line N-0.5 BY THE
# MARKET'S OWN CONSTRUCTION -- the polarity is pinned by the slug the same way
# `_greater_than_line`'s `gt` token pins corners, not by a side constant.
#
# Values are the CANONICAL market keys (`market_keys._MLB`), the vocabulary
# `book_quotes` is keyed on and the board's own rows canonicalise into.
# MLB ONLY: these family tokens were measured on MLB slugs. Another league
# reusing a token (`k-` on cfb, say) stays refused until measured -- admission
# is per (family, league), the same rule BTTS and corners were admitted under.
_PROP_FAMILY_TO_BOARD: dict[str, str] = {
    "hits": "batter_hits",
    "tb": "batter_total_bases",
    "hr": "batter_home_runs",
    "hrr": "batter_hits_runs_rbis",
    "k": "strikeouts",
    "outs": "outs",
    "er": "earned_runs",
    "wa": "walks_allowed",
    "ha": "hits_allowed",
}

# The board-side gate for prop rows. DERIVED, NOT RETYPED -- the same rule
# `_JOINABLE_BOARD_MARKETS` states for game lines: two guards that must agree
# should not be two literals. Kept SEPARATE from the game-line set because a
# prop row must ALSO carry a player and a line; membership alone does not
# admit it (see the board loop).
_JOINABLE_PROP_BOARD_MARKETS: frozenset[str] = frozenset(_PROP_FAMILY_TO_BOARD.values())

# `gte2` -> 2.0. At-least-N. Distinct from `_GT_TOKEN` (`gt10pt5`, strictly
# more than): both appear in venue slugs and they differ by half a rung.
_GTE_TOKEN = re.compile(r"^gte(?P<num>\d+)$")

# The venue's player token: 3+3 prefix encoding, plus the venue's OWN
# league-wide collision handling (a digit suffix -- `wilcon2` = William
# Contreras beside Willson -- or a longer prefix -- `bretbat` = Brett
# Bateman beside Brett Baty). We never derive those extended forms, so they
# can never match; the pattern still recognises them as player tokens so the
# row indexes and a miss shows up as `no_match` instead of out-of-scope.
_PROP_PLAYER_TOKEN = re.compile(r"^[a-z]{2,12}\d{0,2}$")

# `14pt5` -> 14.5. The venue writes decimals this way in slugs; reading it as an
# integer would price a +14.5 spread at +145.
_SLUG_NUMBER = re.compile(r"^(?P<sign>neg|pos)?(?P<whole>\d+)(?:pt(?P<frac>\d+))?$")

_SLUG_SHAPE = re.compile(
    r"^(?P<prefix>[a-z]+)-(?P<league>[a-z0-9]+)-(?P<away>[a-z0-9]+)-(?P<home>[a-z0-9]+)"
    r"-(?P<date>\d{4}-\d{2}-\d{2})(?:-(?P<rest>.+))?$"
)


def market_web_url(slug: Any) -> str | None:
    """The browsable page for a slug's GAME, or None.

    CONFIRMED BY THE USER 2026-08-25, one example, verbatim:

        slug  tsc-mlb-cin-sf-2026-08-25-7pt5
        url   https://polymarket.us/sports/mlb/mlb-cin-sf-2026-08-25

    So the address is `<league>-<away>-<home>-<date>` under `/sports/<league>/`:
    the slug's PREFIX and its MODIFIERS are both dropped.

    IT ADDRESSES THE GAME, NOT THE MARKET. Every market on one game -- the
    total at 7.5, the spread ladder, each prop -- collapses to this same URL,
    because the modifiers that distinguish them are exactly what the web form
    discards. Good enough to eyeball coverage, and not a per-market link; a
    coverage report that implied otherwise would send someone looking for a
    market the page does not single out.

    THE LEAGUE TOKEN IS POLYMARKET'S OWN, and that is confirmed rather than
    assumed. Both examples came from the user the same day:

        aec/tsc-mlb-cin-sf-2026-08-25    -> /sports/mlb/mlb-cin-sf-2026-08-25
        astatc-epl-cry-mnc-2026-08-28    -> /sports/epl/epl-cry-mnc-2026-08-28

    The second is the one that mattered. Syndicate calls that sport `soccer`
    and Polymarket calls the competition `epl`, so the open question was
    whether the web form spoke our vocabulary or theirs -- and it is theirs,
    unchanged from the slug. That makes every soccer row in the coverage gap
    checkable with a link built from what we already store, including the
    league codes (`lal`, `lg1`, `sea`, `bun`) we do not yet map.

    This repo still never fetches a Polymarket web page -- it has no business
    being that caller -- so a league neither example covers is a CANDIDATE
    built by the same rule, not a verified address.
    """
    parsed = parse_slug(slug)
    if not parsed:
        return None
    league = str(parsed.get("league") or "").strip()
    away = str(parsed.get("away") or "").strip()
    home = str(parsed.get("home") or "").strip()
    date = str(parsed.get("date") or "").strip()
    if not (league and away and home and date):
        return None
    return f"https://polymarket.us/sports/{league}/{league}-{away}-{home}-{date}"


def parse_slug(slug: Any) -> dict[str, Any] | None:
    """`<prefix>-<league>-<away>-<home>-<date>[-<modifiers>]`, or None.

    None on anything that does not match the shape. A slug we cannot parse is
    a market we cannot place, and inventing a parse for it is how a row gets
    joined to the wrong game.
    """
    text = str(slug or "").strip().lower()
    match = _SLUG_SHAPE.match(text)
    if not match:
        return None
    rest = match.group("rest") or ""
    return {
        "prefix": match.group("prefix"),
        "league": match.group("league"),
        "away": match.group("away"),
        "home": match.group("home"),
        "date": match.group("date"),
        "modifiers": [m for m in rest.split("-") if m],
    }


def _slug_number(token: str) -> float | None:
    match = _SLUG_NUMBER.match(str(token or "").strip().lower())
    if not match:
        return None
    whole = match.group("whole")
    frac = match.group("frac") or ""
    try:
        value = float(f"{whole}.{frac}") if frac else float(whole)
    except ValueError:
        return None
    return -value if match.group("sign") == "neg" else value


def _line_from_modifiers(modifiers: Sequence[str]) -> float | None:
    """The LAST numeric modifier is the line, and the token BEFORE it is its sign.

    Two traps, both measured on real slugs:

    `tsc-nfl-tb-jax-2026-08-28-1q-17pt5` carries two numbers -- `1q` is a
    SEGMENT and `17pt5` is the line. Taking the first prices a full-game total
    at the first quarter's number.

    `asc-nfl-nyg-nyj-2026-08-28-pos-14pt5` puts the sign in its OWN token.
    `pos`/`neg` are not prefixes of the number, so a regex that only handles
    `neg14pt5` reads -14.5 as +14.5 -- the opposite side of the same spread, at
    a price that looks entirely reasonable.
    """
    tokens = [str(m).strip().lower() for m in (modifiers or [])]
    for index in range(len(tokens) - 1, -1, -1):
        value = _slug_number(tokens[index])
        if value is None:
            continue
        if index > 0 and tokens[index - 1] == "neg":
            return -abs(value)
        if index > 0 and tokens[index - 1] == "pos":
            return abs(value)
        return value
    return None


# League tokens that are definitively NOT soccer, so a club-code coincidence
# cannot reclassify them. These are the sports Syndicate models with their own
# board rows; anything else still reaches the soccer test below.
_NON_SOCCER_LEAGUE_TOKENS = frozenset({
    "mlb", "nba", "wnba", "nfl", "nhl", "ncaaf", "ncaab", "ncaabb",
})


# Venue league token -> the sport Syndicate's board stamps. One entry, because
# one is all that is PROVEN; see the block inside `_effective_league`.
_VENUE_LEAGUE_ALIASES: dict[str, str] = {
    # 2,194 venue rows vs zero under `ncaaf`, plus a named fixture match
    # (`sacst-emich`). Measured 2026-08-29.
    "cfb": "ncaaf",
}


def _effective_league(
    parsed: Mapping[str, Any], soccer_tokens: Collection[str] | None = None
) -> str:
    """The slug's own league token, UNLESS both clubs resolve as soccer clubs.

    Measured 2026-08-25: Polymarket lists soccer per COMPETITION (a refused
    production row carried league token `eflc`, EFL Championship) while
    Syndicate stamps every soccer board row `sport="soccer"` uniformly --
    one umbrella sport, ten competitions (`soccer/sources.py`
    `LEAGUE_DISPLAY_NAMES`: epl/la_liga/bundesliga/serie_a/ligue_1/mls/
    eredivisie/primeira_liga/championship/belgian_pro_league), none of which
    is the literal string "soccer". A plain `parsed["league"] == sport`
    compare therefore can never match a soccer row -- the same class of bug
    the KXMLBGAME fix corrected one level down (there, a market key; here, a
    league key) -- and this lane has confirmed only ONE of Polymarket's
    competition tokens, not enough to build a translation table without
    guessing the rest.

    So this asks a question the rest of this module already trusts an answer
    for instead: do both clubs resolve as known soccer clubs via
    `team_aliases.canonical_team`? If so, the row is treated as league
    `"soccer"` regardless of its own token; if either club is unresolved (a
    real, counted gap -- ambiguous cross-league tri-codes are deliberately
    dropped by `_soccer_alias_to_name`) or the sport is not soccer at all,
    the literal token is returned unchanged, so mlb/nfl/nba/wnba/nhl are not
    touched by this at all.
    """
    league = str(parsed.get("league") or "")
    if league == "soccer":
        return league
    # THE VENUE'S NAME FOR A SPORT WE MODEL UNDER A DIFFERENT ONE.
    #
    # Applied BEFORE `_NON_SOCCER_LEAGUE_TOKENS` so the alias resolves rather
    # than being returned verbatim as its own league.
    #
    # PROVEN, NOT GUESSED -- and the first evidence for it was WRONG. The
    # `key_miss` diagnostic reports `market_indexed_under` as `sorted(...)[:4]`,
    # and `cfb` sorts first alphabetically, so it filled the cap on every market
    # it touched. The identical `['cfb|...']` list appeared under `wnba|totals`,
    # where `cfb` cannot possibly be the alias. That is truncation, not
    # attribution, and it was nearly recorded as a finding twice.
    #
    # What settles it, measured 2026-08-29T14:5xZ against the production slate:
    #
    #     cfb    h2h 180 | spreads 1265 | totals 749   = 2,194 rows
    #     ncaaf  nothing, under any market
    #     tsc-cfb-sacst-emich-2026-08-29-total-52pt5
    #
    # That last slug is Sacramento State @ Eastern Michigan -- the exact board
    # fixture in the refusal sample, same date, filed under `cfb`. A named
    # fixture on both sides is evidence a sorted-and-truncated list can never be.
    #
    # ONLY `cfb`. `nba`, `nhl`, `ncaab` and `ncaabb` also show zero venue rows
    # today, and that is AUGUST rather than an alias -- they are out of season,
    # so there is nothing to prove and a guessed mapping would be indistinguish
    # -able from a working one until their season started.
    aliased = _VENUE_LEAGUE_ALIASES.get(league)
    if aliased is not None:
        return aliased

    # A LEAGUE TOKEN WE ALREADY KNOW IS NOT SOCCER ENDS THE QUESTION HERE.
    #
    # This function's own docstring promised exactly that -- "so mlb/nfl/nba/
    # wnba/nhl are not touched by this at all" -- and the code never checked
    # the token. It asked only whether BOTH clubs resolve as soccer clubs, and
    # MLB tri-codes collide with soccer clubs:
    #
    #     min -> Minnesota United FC (MLS)      | Minnesota Twins
    #     ath -> Athletic Club (Bilbao)         | Athletics
    #     sd  -> San Diego FC                   | San Diego Padres
    #
    # So `tsc-mlb-min-ath-2026-08-25-10pt5` was indexed under league `soccer`
    # while its MLB board row looked up `mlb`, and the two could never meet.
    #
    # MEASURED 2026-08-25T18:49:14Z, in production, as a lost position: a
    # `totals under 10.5` on Minnesota Twins @ Athletics reached the placer
    # with `venue_ticker=None` because the join never paired it --
    # `POLYMARKET_NO_SLUG ... (type=NoneType)`. Tampa Bay @ Detroit filled
    # minutes earlier from the same code path, because `tb` and `det` happen
    # not to collide. The bug was invisible for exactly that reason: it hits
    # only the games whose codes overlap, so it reads as intermittent coverage
    # rather than as a rule.
    #
    # An explicit allowlist rather than a soccer denylist: a new Polymarket
    # competition token we have never seen should still be ABLE to reach the
    # soccer test, while a sport we model can never be reclassified out of
    # itself by a club-code coincidence.
    if league in _NON_SOCCER_LEAGUE_TOKENS:
        return league

    # THE COMPETITION WAS ALREADY PROVEN SOCCER BY ITS OWN SIBLING MARKETS.
    #
    # Checked BEFORE the per-row club test, because this is the case the row
    # test cannot answer: an ambiguous tri-code (`fcb` -- Bayern or Barcelona)
    # is deliberately dropped by `_soccer_alias_to_name`, so the row alone
    # looks unidentifiable while its competition is not in doubt. Optional so
    # every existing caller keeps its exact behaviour -- `None` means "no slate
    # in hand", and then this is the same function it always was.
    if soccer_tokens and league in soccer_tokens:
        return "soccer"

    try:
        from syndicate.features.shared.team_aliases import canonical_team
    except Exception:
        return league
    if canonical_team("soccer", parsed.get("home")) and canonical_team("soccer", parsed.get("away")):
        return "soccer"
    return league


def soccer_competition_tokens(markets: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """League tokens PROVEN to be soccer competitions, from the slate itself.

    THE GAP THIS CLOSES, measured in production 2026-08-27 through the new
    `/api/ops/polymarket/slate` reader:

        h2h markets in the slate      2,486 across 89 league tokens
        reachable by a soccer board row   111   (keyed `soccer`)

    `_effective_league` calls a row soccer only when BOTH clubs resolve via
    `canonical_team`. Any row with one unresolved club keeps its raw
    competition token -- `bun`, `arg2`, `bra`, `alsv` -- and the board, which
    stamps every soccer row `sport="soccer"`, looks up `("soccer", date,
    market)` and never sees it. Two rows on the SAME COMPETITION land in
    different buckets purely because of which clubs are playing:

        atc-lal-cel-osa-2026-08-16-cel   cel + osa resolve      -> "soccer"
        atc-bun-fcb-stu-2026-08-28-fcb   fcb ambiguous, dropped -> "bun"

    And `fcb` is ambiguous ON PURPOSE -- Bayern and Barcelona both claim it, so
    `_soccer_alias_to_name` drops it rather than guess. That refusal is correct
    per row and catastrophic per market: the safety behaviour silently removed
    the market from the board's reach.

    WHY THIS IS NOT THE TRANSLATION TABLE `_effective_league` REFUSED TO GUESS.
    Its docstring declined to hand-write a token->sport map on one confirmed
    example, and it was right to. Nothing here is hand-written. A token earns
    membership only when one of ITS OWN markets has BOTH clubs resolve as
    soccer clubs -- the same `canonical_team` test, the same evidence, just
    asked once per COMPETITION instead of once per ROW. A competition nobody
    can identify never joins the set, and a token invented by the venue
    tomorrow is admitted the moment one of its fixtures is recognisable.

    `_NON_SOCCER_LEAGUE_TOKENS` still short-circuits FIRST and is never
    consulted here, so the measured MLB collision (`min`->Minnesota United,
    `ath`->Athletic Club) cannot be reintroduced: `mlb` can never enter this
    set, whatever its tri-codes look like.

    TWO TESTS, UNIONED -- AND THE SECOND ONE IS WHY MLS WAS INVISIBLE.

    The test above is `canonical_team` on each club SEPARATELY, against the
    flat cross-league map. `_teams_match` already learned that this is too weak
    for soccer and falls back to `soccer_fixture_clubs`, which asks the same
    question as a PAIR: both codes inside ONE league, and exactly one league
    qualifying. That fallback is documented there as able to "add matches and
    never remove one". The identical argument applies one level up, to proving
    a COMPETITION -- and it was never applied here.

    MEASURED 2026-08-28, 9 MLS fixtures taken from the live slate:

        flat, both clubs resolve separately   0 of 9
        pair, `soccer_fixture_clubs`          1 of 9   (`tor-nyc`)

    One is enough: a token earns membership from ANY ONE of its fixtures. So
    `mls` goes from never-proven to proven, and all of its markets -- 30 h2h
    plus its spreads and totals -- become reachable by a board that stamps
    every soccer row `sport="soccer"`. Production before this: `no_match|
    soccer|h2h: 104`, i.e. EVERY soccer h2h row on the board.

    UNION, NOT REPLACEMENT, and that is load-bearing rather than caution. The
    pair test is STRICTER in places, not uniformly stronger: on the same
    sample `elv-lev` passes the flat test and returns None as a pair. Swapping
    one for the other would have bought MLS and silently sold a Bundesliga
    fixture. Either test proving a token is enough; neither can veto the other.
    """
    try:
        from syndicate.features.shared.team_aliases import (
            canonical_team,
            soccer_fixture_clubs,
        )
    except Exception:  # noqa: BLE001 -- the join must survive a missing resolver
        return frozenset()

    proven: set[str] = set()
    alias_table_broken = False
    for row in markets or ():
        parsed = parse_slug(row.get("slug") if isinstance(row, Mapping) else None)
        if parsed is None:
            continue
        league = str(parsed.get("league") or "")
        if (
            not league
            or league == "soccer"
            or league in _NON_SOCCER_LEAGUE_TOKENS
            # An ALIASED token names a sport we model, so it can never be a
            # soccer competition however its tri-codes happen to resolve. Same
            # guarantee `_NON_SOCCER_LEAGUE_TOKENS` gives the literal names, for
            # the tokens that reach the board under a different one.
            or league in _VENUE_LEAGUE_ALIASES
        ):
            continue
        if league in proven:
            continue
        home, away = parsed.get("home"), parsed.get("away")
        # DECLINING AND RAISING ARE DIFFERENT ANSWERS, and only one of them may
        # fall through.
        #
        # A resolver that RETURNS falsy has read the alias table and said "I do
        # not know this club" -- a healthy answer, and exactly the case the
        # pair test exists to take a second look at.
        #
        # A resolver that RAISES means the alias table itself is unreadable. Its
        # sibling lives in the same module and is built from the same artifacts,
        # so asking it next is not a second opinion; it is the same broken
        # source wearing a different name. `test_a_raising_resolver_yields_an_
        # empty_set_not_an_exception` pins this: a broken alias table must admit
        # NOTHING rather than admit tokens on whichever resolver happens to
        # still answer. Caught by that test when the first version of this
        # change fell through on both.
        try:
            if canonical_team("soccer", home) and canonical_team("soccer", away):
                proven.add(league)
            continue
        except Exception:  # noqa: BLE001
            # THE ALIAS TABLE IS UNREADABLE, AND THAT DISQUALIFIES BOTH TESTS.
            # `soccer_fixture_clubs` is built from the same artifacts, so
            # running the second pass now would admit tokens on the strength of
            # a source we have just been told is broken.
            alias_table_broken = True
            break
    if alias_table_broken:
        return frozenset(proven)
    for row in markets or ():
        # SECOND PASS, so the flat test above decides every row before the pair
        # test sees any. Interleaving them would make a token's membership
        # depend on slate order, which is the defect this lane fixed one file
        # over in `spread_sign_test`.
        parsed = parse_slug(row.get("slug") if isinstance(row, Mapping) else None)
        if parsed is None:
            continue
        league = str(parsed.get("league") or "")
        if (
            not league
            or league == "soccer"
            or league in _NON_SOCCER_LEAGUE_TOKENS
            # An ALIASED token names a sport we model, so it can never be a
            # soccer competition however its tri-codes happen to resolve. Same
            # guarantee `_NON_SOCCER_LEAGUE_TOKENS` gives the literal names, for
            # the tokens that reach the board under a different one.
            or league in _VENUE_LEAGUE_ALIASES
        ):
            continue
        if league in proven:
            continue
        try:
            if soccer_fixture_clubs(parsed.get("home"), parsed.get("away")):
                proven.add(league)
        except Exception:  # noqa: BLE001
            continue
    return frozenset(proven)


# `#595` step 2 -- DOES THE PRICE WE ASSIGN TO A SIDE BELONG TO THAT SIDE?
#
# --------------------------------------------------------------------------
# THE ASSUMPTION UNDER TEST, WHICH NOBODY HAS EVER CHECKED
# --------------------------------------------------------------------------
#
# Three call sites zip the venue's two arrays positionally --
# `polymarket_board_join:_outcome_probabilities`, and
# `venue_quote_adapters._polymarket_sides` twice -- so every Polymarket price
# in this system rests on `outcomes[i]` naming the club that `outcomePrices[i]`
# prices.
#
# **CORRECTION TO THIS COMMENT AS FIRST WRITTEN.** It said the assumption was
# "asserted NOWHERE and proven NOWHERE". That is false and the error was mine:
# I searched `state.md` and `todo.md` and not `learnings.md`, where the proof
# is recorded at lines 3647-3651 (lane `local_bb0d1330`, 2026-08-28). It
# proposed misalignment, then refuted it: a TOTALS market, `under` at index 1
# priced 0.445 against a planned 0.4444, where misalignment would have read
# Over's ~0.555. Alignment proven at both indices, ~0.11 separation.
#
# **SO THE ACCURATE STATEMENT IS NEITHER "UNPROVEN" NOR "SETTLED":**
#
#     tested ONCE, on a TOTALS market, at ~0.11 separation
#     the doubt is a MONEYLINE, at 0.01 separation
#
# Different populations, and neither settles the other. That distinction is
# not pedantic, because THIS CODEBASE ALREADY CONTAINS THAT EXACT SPLIT:
# `_side_to_outcome` maps `over`/`under` BY NAME and measured 9-of-9 correct,
# while team sides had no name to fall back on and measured 3-of-8 WRONG. The
# venue demonstrably treats totals and moneylines differently for the SIDE, so
# assuming it treats them identically for the PRICE is unwarranted in the same
# way. One measurement, taken on the market type least likely to expose the
# failure, stands behind all three zip sites.
#
# The doubt arose when lane `portfolio-venue-and-side-integrity` measured
# `marketSides[].long` varying across `outcomes[0]`/`[1]`, and found one market
# where `marketSides` priced a club at `outcomePrices[0]` while the arrays said
# `[1]`. **Their separation was ONE CENT (0.51 vs 0.50)** and they flagged
# rather than asserted it, correctly -- a penny cannot carry this either.
#
# --------------------------------------------------------------------------
# WHY THIS TEST CAN CARRY IT WHERE A ONE-CENT GAP CANNOT
# --------------------------------------------------------------------------
#
# An inversion is not a small error. If we hand a side the OTHER side's price,
# the number lands near `1 - fair` rather than `fair` -- on a lopsided market
# that is a gap of tens of cents, not one. So the test compares the venue price
# we assigned against the BOOKS' own no-vig probability for the same side
# (`quote.fair_probability`, consensus across every book quoting it, wholly
# independent of Polymarket) and asks which hypothesis it sits closer to.
#
# **IT REFUSES TO SCORE WHAT IT CANNOT SEPARATE**, which is the lesson from
# this lane's spread-sign audit: a comparison whose two hypotheses are a cent
# apart returns ~0.5 forever and looks like weak evidence when it is none.
# Near a coin flip `fair` and `1 - fair` converge, so a market must be lopsided
# by `_ALIGN_MIN_EDGE` before it votes at all, and the winning hypothesis must
# beat the other by `_ALIGN_MIN_MARGIN`. Everything else is `too_close`, which
# is a real answer and is reported.
#
# A normal betting edge is a few points; these thresholds put the two
# hypotheses at least 0.20 apart, so an edge cannot masquerade as an inversion.
_ALIGN_MIN_EDGE = 0.10     # |fair - 0.5|: hypotheses >= 0.20 apart
_ALIGN_MIN_MARGIN = 0.10   # the winner must be closer by at least this much


def _classify_alignment(
    board_row: Mapping[str, Any],
    venue_probability: Any,
    key: str,
    counts: dict[str, int],
    samples: list[dict[str, Any]],
) -> str:
    """Classify one matched row as aligned / inverted / too_close / no_reference.

    RETURNS THE VERDICT NOW, AND THE CALLER REFUSES ON `inverted`. This used to
    say "Never decides", and that was the defect: it detected wrong-side pricing
    and let the order through.

    MEASURED 2026-08-29T19:38:25Z, after the leg fixes made these rows match:

        soccer|h2h|inverted 13  vs aligned 10
        mlb|h2h|inverted     2  ·  soccer|alternate_totals_corners|inverted 3

        'San Jose Earthquakes@Houston Dynamo' side=draw
             venue_p 0.79   book_fair 0.2285   complement 0.7715

    A draw priced at 0.79. `venue_p` tracks the COMPLEMENT, so the order pays
    the opposite outcome's price -- reported by the user as "orders going
    through at non-market prices". The inversion predates this lane (mlb|h2h and
    nfl|totals were inverted at 17:49Z, before any of today's leg work); what
    the leg fixes changed is how MANY rows reach it.

    The thresholds below are why this is safe to act on: a market must be
    lopsided by >= 0.20 before it votes at all, and the winning hypothesis must
    beat the other by >= 0.10, so an ordinary betting edge cannot masquerade as
    an inversion.
    """
    quote = board_row.get("quote") if isinstance(board_row.get("quote"), Mapping) else None
    fair = _as_float((quote or {}).get("fair_probability"))
    p = _as_float(venue_probability)
    if fair is None or p is None or not (0.0 < fair < 1.0) or not (0.0 < p < 1.0):
        counts[f"{key}|no_reference"] = counts.get(f"{key}|no_reference", 0) + 1
        return "no_reference"
    if abs(fair - 0.5) < _ALIGN_MIN_EDGE:
        # Too near a coin flip for `fair` and `1 - fair` to be told apart.
        counts[f"{key}|too_close"] = counts.get(f"{key}|too_close", 0) + 1
        return "too_close"
    d_aligned, d_inverted = abs(p - fair), abs(p - (1.0 - fair))
    if d_aligned + _ALIGN_MIN_MARGIN <= d_inverted:
        verdict = "aligned"
    elif d_inverted + _ALIGN_MIN_MARGIN <= d_aligned:
        verdict = "inverted"
    else:
        verdict = "too_close"
    counts[f"{key}|{verdict}"] = counts.get(f"{key}|{verdict}", 0) + 1
    if verdict == "inverted" and len(samples) < 8:
        samples.append({
            "board": f"{board_row.get('away_team')}@{board_row.get('home_team')}",
            "side": board_row.get("side"),
            "venue_p": round(p, 4),
            "book_fair": round(fair, 4),
            "complement": round(1.0 - fair, 4),
        })
    return verdict


def _canonical_fixture(sport: Any, home: Any, away: Any) -> frozenset[str] | None:
    """The two clubs as an UNORDERED, canonical pair -- or None if unreadable.

    --------------------------------------------------------------------------
    WHY THIS EXISTS AND WHY IT MUST NOT USE `teams_match`
    --------------------------------------------------------------------------

    `POLYMARKET_ORIENTATION` reported `soccer|h2h` flipping 10 of 106 tried, and
    10/106 is NOT the orientation rate. A row can fail to flip-match for a
    reason that has nothing to do with orientation -- most obviously, the venue
    never listed that fixture at all. Those rows sit in the denominator and
    cannot possibly reach the numerator.

    The denominator that makes it a rate is "rows whose fixture the venue lists,
    orientation aside". That question has to be answered WITHOUT the
    orientation-sensitive matcher, or it answers itself: `_teams_match` in
    either orientation is exactly what the flip test already does, so defining
    eligibility that way would make the rate 100% by construction and mean
    nothing.

    So this uses `canonical_team` on each token independently and compares the
    two clubs as a SET. Order cannot affect a set, which is the whole point.

    **IT IS A LOWER BOUND, STATED HERE SO THE NUMBER IS NOT OVER-READ.**
    `canonical_team` is stricter than `teams_match`: measured 2026-08-28,
    `canonical_team('soccer', 'rrc')` is None while
    `teams_match('soccer', 'rrc', 'Real Racing Club de Santander')` is True. A
    fixture whose venue tri-code will not canonicalise returns None here and is
    counted as UNREADABLE rather than as absent -- "listed but we cannot read
    it" and "not listed" are different facts and must not share a bucket, which
    is the same conflation `no_match` itself makes one level up.
    """
    if str(sport or "").strip().lower() != "soccer":
        # Only soccer needs this today, and canonicalising every MLB/NFL market
        # would cost a resolver call per market for a question nobody asks of
        # them. Non-soccer rows report as unreadable, which reads correctly:
        # this counter has nothing to say about them.
        return None
    try:
        from syndicate.features.shared.team_aliases import canonical_team
    except Exception:  # noqa: BLE001
        return None
    try:
        a, b = canonical_team("soccer", home), canonical_team("soccer", away)
    except Exception:  # noqa: BLE001
        return None
    if not a or not b or a == b:
        # `a == b` would collapse a fixture to a one-element set and match any
        # other self-pair, which is a wrong answer rather than a missing one.
        return None
    return frozenset((a, b))


# How far past the board's own date a soccer fixture may be looked up. `#545`
# builds TWO MATCHDAYS per league, and a league matchday cycle is a week, so a
# fortnight covers the horizon with room and still cannot reach a fixture the
# board is not carrying. Bounded rather than unbounded because the slate holds
# futures dated months out.
_FORWARD_HORIZON_DAYS = 14


def _resolved_line(
    parsed: Mapping[str, Any],
    row: Mapping[str, Any],
    board_market: str,
    line_source: dict[str, int],
    gap_samples: list[dict[str, Any]],
) -> float | None:
    """The market's line: from the SLUG, else from the row's own `line` field.

    ------------------------------------------------------------------
    WHY A FALLBACK, measured 2026-08-29T16:11:39Z
    ------------------------------------------------------------------

    `no_match|soccer|alternate_totals_corners: 37`, and the sample says why:

        board    Rayo Vallecano @ Barcelona  alternate_totals_corners|over|13.5
        offered  ['lev-bet@None', 'lev-bet@None', ... ]

    `@None` is the candidate's own line. Corners is in
    `_LINE_BEARING_BOARD_MARKETS`, so a candidate with no line is SKIPPED --
    every corners rung was being discarded before it could be compared.

    The slug parser is not at fault: `cor-all-13pt5` resolves to 13.5 correctly.
    These corners slugs simply do not carry the number. The persisted slate row
    DOES keep a `line` field (`polymarket_us_markets._KEEP`), and this join has
    only ever read the slug -- the same shape as the corners `question` route
    and the `refusals`/`reasons` key: a field that exists, populated, unread.

    SLUG WINS WHEN IT HAS ONE. Every match working today is slug-derived, so the
    fallback can only add rows, never re-price an existing one. A disagreement
    between the two is COUNTED rather than silently resolved -- if the venue
    ever ships both and they differ, that is a fact worth a line in the log, not
    a preference buried in a helper.

    SELF-VERIFYING, DELIBERATELY. I cannot read a soccer PROP row from outside
    the worker -- `/api/ops/polymarket/slate` skips PROP before it samples -- so
    whether `row["line"]` is populated for corners is UNMEASURED at the time of
    writing. `line_source` reports where each line came from and
    `line_gap_samples` carries the real slug shape, so the next reading either
    shows the fallback firing or shows this is inert. Four routes this session
    looked installed and could not fire; this one says which it is.
    """
    slug_line = _line_from_modifiers(parsed.get("modifiers") or [])
    row_line = _as_float(row.get("line"))
    if slug_line is not None:
        if row_line is not None and abs(slug_line - row_line) > 1e-9:
            line_source[f"{board_market}|DISAGREE"] = (
                line_source.get(f"{board_market}|DISAGREE", 0) + 1
            )
        line_source[f"{board_market}|slug"] = line_source.get(f"{board_market}|slug", 0) + 1
        return slug_line
    if row_line is not None:
        line_source[f"{board_market}|row_field"] = (
            line_source.get(f"{board_market}|row_field", 0) + 1
        )
        return row_line
    line_source[f"{board_market}|none"] = line_source.get(f"{board_market}|none", 0) + 1
    # THE REAL SLUG SHAPE, for the families that carry no number anywhere. This
    # is the field that would have named the corners format without a guess.
    if len(gap_samples) < 6 and not any(
        g.get("market") == board_market for g in gap_samples
    ):
        gap_samples.append({
            "market": board_market,
            "slug": str(row.get("slug") or "")[:64],
            "row_line_raw": repr(row.get("line"))[:24],
        })
    return None


def _has_segment(modifiers: Sequence[str]) -> bool:
    """A period/quarter/half qualifier. `1q`, `2h`, `1p`, `f5`, `fh`, `sh`.

    Segment markets are refused: the board's `totals` means the FULL GAME, and
    pricing it from a first-quarter market is a different bet at a confident
    -looking number.

    `fh`/`sh` ARE SOCCER HALVES AND THIS SCREEN DID NOT CATCH THEM. Measured
    from `prop_modifier_census` 2026-08-29T04:14:58Z: the venue publishes
    `fh-btts` (62) and `sh-btts` (62) alongside full-game `btts` (62). The old
    pattern only matched a DIGIT-led half (`1h`, `2h`), so `fh` and `sh` fell
    through -- and because this screen runs AFTER the market is assigned, the
    BTTS branch had already keyed on `"btts" in modifiers`, which is true of
    all three. 124 first- and second-half contracts were therefore admitted as
    full-game BTTS.

    That is the same error the corners note one screen up warns about and the
    same one that cost $7.08 in MLB orders on 2026-08-28: a segment priced as
    the full game, at a number that looks entirely reasonable. It shipped in
    the BTTS admission earlier the same day and was invisible until the census
    printed the venue's own vocabulary -- the token set was ASSUMED to be
    digit-led because every previously-read sport's was.
    """
    return any(
        re.fullmatch(r"(?:[1-4](?:q|h|p)|f[357]|fh|sh)", str(m).lower())
        for m in modifiers or []
    )


# Board markets whose match REQUIRES the line to agree. `alternate_totals_corners`
# was missing and that was a real defect: a corners total is quoted at many rungs
# per fixture, so without the line every rung matched the same board row and they
# refused each other as ambiguous -- the same failure as the 3-way legs below,
# from the opposite cause.
_LINE_BEARING_BOARD_MARKETS = frozenset({"spreads", "totals", "alternate_totals_corners"})


_SEGMENT_TOKEN = re.compile(r"(?:[1-4](?:q|h|p)|f[357]|fh|sh)")

# The board sides that name a ROLE rather than an outcome. Only these reach the
# subject logic below: `btts` and `totals` name their own outcome (`yes`/`no`,
# `over`/`under`) and the literal compare in `_probability_for_side` already
# resolves them. Routing those through a subject test would break a working
# family to fix a broken one.
_ROLE_SIDES = frozenset({"home", "away", "draw"})


_GT_TOKEN = re.compile(r"^gt(?P<num>\d+(?:pt\d+)?)$", re.IGNORECASE)


def _greater_than_line(parsed: Mapping[str, Any]) -> float | None:
    """The threshold in a `gt<number>` modifier, or None.

    `cor-all-gt10pt5` is "more than 10.5 corners". The `gt` is the venue SAYING
    which direction its `Yes` means, in the slug, and it is the reason the
    over/under map below is not a guess.
    """
    for token in parsed.get("modifiers") or []:
        match = _GT_TOKEN.match(str(token).strip())
        if match:
            return _slug_number(match.group("num"))
    return None


def _is_yes_no_market(outcomes: Any) -> bool:
    """A binary Yes/No contract, as opposed to one naming both teams."""
    return {_norm(name) for name, _ in (outcomes or ())} == {"yes", "no"}


# Name suffixes the venue's token encoding ignores: `fertat` is Fernando Tatis
# Jr., `michar` is Michael Harris II. Measured, not assumed -- see the census.
_PROP_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})


def _player_name_words(player_name: Any) -> list[str]:
    """The name words BOTH encoders read. One cleaner, not two that drift.

    Drops, in order: parenthetical groups -- our board disambiguates two real
    same-named players with them (`Max Muncy (2002)` is the Athletics' Muncy,
    b. 2002, beside the Dodgers' 1990 one) and the year was surviving cleaning
    to become the "surname" (`max200`, measured in production 2026-09-01
    20:30Z, classified player_not_listed with a token no venue will ever
    write); hyphens to spaces (the venue keys `Crow-Armstrong` off
    `armstrong`); diacritics and punctuation; generational suffixes; and
    pure-digit words, which can never be a name half regardless of where the
    board writes them.
    """
    import unicodedata

    text = str(player_name or "").strip().lower()
    if not text:
        return []
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("-", " ")
    folded = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in folded if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-z0-9 ]", "", stripped)
    return [
        w for w in cleaned.split()
        if w and w not in _PROP_NAME_SUFFIXES and not w.isdigit()
    ]


def _polymarket_player_token(player_name: Any) -> str | None:
    """OUR player's name -> the venue's slug token, or None when underivable.

    The rule, validated on 97 of 99 measured (token, question-name) pairs
    across 8 fixtures on 2026-09-01 (the other 2 are the venue's own
    collision-extended forms, which this NEVER produces -- see below):

        first 3 of the FIRST NAME + first 3 of the SURNAME, lowercased
        - a first name shorter than 3 keeps its length: `tyfra` (Ty France),
          `jjble` (JJ Bleday), `joade` (Jo Adell)
        - suffixes dropped: `fertat` (Fernando Tatis Jr.)
        - the surname is the LAST space- or hyphen-separated word:
          `ellcru` (Elly De La Cruz), `petarm` (Pete Crow-Armstrong),
          `ajsha` (AJ Smith-Shawver)
        - diacritics and punctuation folded: `eugsua` (Eugenio Suarez),
          `julrod` (Julio Rodriguez)
        - board disambiguators dropped: `maxmun` (Max Muncy (2002))

    WHY DERIVE-AND-COMPARE STILL NEEDS A COLLISION GUARD. The venue
    disambiguates its token space LEAGUE-WIDE: `wilcon2` (William Contreras,
    beside Willson) and `bretbat` (Brett Bateman at 4+3, beside Brett Baty).
    We only produce the plain 3+3 form, so an EXTENDED venue token can never
    match ours -- a coverage miss, the refusal this module prefers. But the
    PLAIN form is not safe by construction: whichever of a same-named pair
    owns it at the venue, the OTHER one's name derives to exactly that plain
    token, and when the two appear in ONE fixture (Willson's and William's
    clubs meet repeatedly every season) a plain-token match would price the
    wrong person. That is what `prop_same_name_collision_at_venue` in the
    match loop refuses: both forms coexisting in the matched fixture makes
    the plain form's identity undecidable from our side, so BOTH same-named
    players refuse there. Board-side, two of OUR rows sharing a token in one
    game still refuse via `prop_player_token_ambiguous`.

    NAMED RESIDUAL, not closed: both players in one game, the venue listing
    ONLY the plain-owner, and our board quoting ONLY the extended-owner --
    no variant token exists anywhere to detect, and deciding it needs lineup
    knowledge the join does not have. Refusing every league-ambiguous token
    outright would cost the plain-owner's legitimate matches all season, so
    the fixture-scoped guard is the deliberate stopping point.
    """
    words = _player_name_words(player_name)
    if len(words) < 2:
        # One word cannot fill both halves of the encoding; inventing a
        # repeat would be the guess this function exists to avoid.
        return None
    return words[0][:3] + words[-1][:3]


def _polymarket_token_alt43(player_name: Any) -> str | None:
    """The 4+3 encoding of OUR OWN name, or None when it adds nothing.

    `bretbat` is Brett Bateman at 4+3 because Brett Baty collides at
    `brebat` -- the venue's longer-prefix collision mechanism, beside the
    digit suffix. This exists ONLY for the collision guard: seeing our own
    4+3 beside our plain 3+3 in one fixture proves a same-named pair there.
    It is never used to MATCH -- decoding which player owns which form is
    the guess this file refuses to make.
    """
    words = _player_name_words(player_name)
    if len(words) < 2 or len(words[0]) <= 3:
        return None
    return words[0][:4] + words[-1][:3]


def _parse_player_prop(parsed: Mapping[str, Any]) -> dict[str, Any] | None:
    """`{market, token, line}` for an admitted player-prop slug, or None.

    The shape is exactly `<family>-<playertoken>-gte<N>` -- three modifiers,
    no more, no fewer. `yrfi` (one token), `ftts-tou` (two), `es-3-0`
    (numbers), and inning/segment shapes all fail this bound and stay in the
    out-of-scope census, which is where an unadmitted family must remain
    visible.

    MLB ONLY, by the raw slug league token: the family vocabulary was
    measured on MLB slugs and nowhere else. `k-` on some other league is not
    known to mean strikeouts, and admission-by-analogy is how a segment got
    priced as a full game twice in August.

    The line is `N - 0.5`: "at least N" is the board's OVER of N-0.5. Integer
    thresholds only -- a fractional `gte` has never been observed, and a shape
    we have not seen refuses rather than rounding.
    """
    if str(parsed.get("league") or "") != "mlb":
        return None
    modifiers = [str(m).strip().lower() for m in (parsed.get("modifiers") or [])]
    if len(modifiers) != 3:
        return None
    family, token, threshold = modifiers
    board_market = _PROP_FAMILY_TO_BOARD.get(family)
    if board_market is None:
        return None
    if not _PROP_PLAYER_TOKEN.match(token) or _GTE_TOKEN.match(token):
        return None
    gte = _GTE_TOKEN.match(threshold)
    if not gte:
        return None
    try:
        at_least = int(gte.group("num"))
    except ValueError:
        return None
    if at_least < 1:
        return None
    return {"market": board_market, "token": token, "line": at_least - 0.5}


def _prop_probability_for_side(side: Any, candidate: Mapping[str, Any]) -> float | None:
    """P(board side) of a `gte` prop from its Yes/No outcomes, or None.

    `over` -> `Yes` and `under` -> `No` is NOT the fixed-constant trap the
    Kalshi order path fell into: a `gte<N>` market's Yes IS the at-least side
    by the slug's own grammar, the way `_greater_than_line` reads `gt`. A
    market whose outcomes are not literally Yes/No refuses -- never a
    positional pick, and never `1 - p` on a one-sided quote (the venue quotes
    one-sided for real: a missing No is a missing price, not 1 - Yes).
    """
    wanted = {"over": "yes", "under": "no"}.get(_norm(side))
    if wanted is None:
        return None
    for name, probability in candidate.get("outcomes") or ():
        if _norm(name) == wanted:
            return probability
    return None


def _subject_token(parsed: Mapping[str, Any]) -> str:
    """The slug's trailing SUBJECT -- who the Yes/No contract is ABOUT.

    `atc-epl-liv-not-2026-08-29-liv` is "Liverpool win?", `-draw` is "draw?".
    Numbers and period tokens are skipped so a subject is never read off a line
    or a half qualifier.
    """
    for token in reversed(parsed.get("modifiers") or []):
        text = str(token).strip().lower()
        if not text or _slug_number(text) is not None or _SEGMENT_TOKEN.fullmatch(text):
            continue
        return text
    return ""


def _subject_is_side(
    candidate: Mapping[str, Any], board_row: Mapping[str, Any], side: Any, sport: Any
) -> bool:
    """Is this Yes/No contract the one the board's ROLE side is asking about?

    ------------------------------------------------------------------
    WHY THIS EXISTS: soccer h2h is THREE markets, not one.
    ------------------------------------------------------------------

    Polymarket splits a 3-way into one binary per outcome, with the subject in
    the slug. MEASURED 2026-08-29T05:16:29Z, the sample says it literally:

        offered: ['liv-not@None', 'liv-not@None', 'liv-not@None', ...]

    All three carry the same fixture and `line=None`, so all three passed the
    candidate filter, and the ambiguity guard -- correctly -- refused rather
    than picking one by iteration order: `ambiguous_polymarket_match: 186`.

    The guard was never the problem. Nothing was reading the leg.

    AND THE SECOND HALF, which the same fact causes: the outcomes are literally
    `["Yes","No"]`, so `_probability_for_side` could not map a board side onto
    them either -- "Liverpool" is not "Yes". That is
    `side_not_an_outcome_of_this_market`. One root, two counters.

    REFUSES RATHER THAN GUESSING. An unreadable subject returns False, which
    costs a match; assigning a leg positionally would price the wrong team at a
    confident-looking number, and this file already refuses a positional pick in
    `_probability_for_side` and `_side_for_team` for that reason.
    """
    wanted = str(side or "").strip().lower()
    subject = _subject_token(candidate.get("parsed") or {})
    if not subject or wanted not in _ROLE_SIDES:
        return False
    if wanted == "draw" or subject == "draw":
        # A draw contract can only ever be the draw leg, in either direction.
        return wanted == "draw" and subject == "draw"

    # ------------------------------------------------------------------
    # THE BOARD'S OWN TEAM NAMES DECIDE. THE SLUG'S POSITIONS NEVER DO.
    # ------------------------------------------------------------------
    #
    # This used to check `subject == parsed[wanted]` FIRST and return True on
    # it. `parse_slug` documents the shape as `<away>-<home>` and applies it to
    # every sport. MEASURED 2026-08-31, two live orders, both wrong-side:
    #
    #   atc-lal-osa-get-2026-08-31-get   board: Getafe @ CA Osasuna, we bet HOME
    #     parsed as away=osa home=get -> subject 'get' == parsed['home'] -> TRUE
    #     bought GETAFE. Osasuna WON. The bet LOST. -$5.96.
    #   atc-sea-ata-bol-2026-08-31-bol   board: Bologna @ Atalanta, we bet HOME
    #     parsed as away=ata home=bol -> subject 'bol' == parsed['home'] -> TRUE
    #     bought BOLOGNA.
    #
    # SOCCER SLUGS ARE `<home>-<away>`; MLB'S ARE `<away>-<home>`. Verified on
    # MLB from the venue's own outcome order -- `aec-mlb-bal-col` reports
    # away_index=1 = Baltimore Orioles, and `bal` is the FIRST token. So the
    # positional convention is SPORT-DEPENDENT and the parser has one rule.
    #
    # The alias check below was already here, as a third-stage fallback, and it
    # answers all four legs of both fixtures correctly (`get`/Getafe True,
    # `get`/CA Osasuna False, and so on). It never ran, because the positional
    # branch returned first -- and the "definitive NO" branch could not save it
    # either, since that reads the SAME inverted parse and so confirms the wrong
    # answer rather than contradicting it. Two checks, one shared broken input.
    #
    # So the positional parse is gone from this decision entirely. It is not
    # repaired here: `parse_slug`'s soccer orientation is used elsewhere for
    # FIXTURE matching, where both teams are present and the roles do not
    # change which game is found, and widening this fix into that is a
    # different change with a different blast radius.
    #
    # REFUSES WHEN IT CANNOT TELL, which is this file's existing rule and the
    # reason the wrong-side loss was possible at all: a confident answer from a
    # broken input is worse than no answer.
    other = "away" if wanted == "home" else "home"
    ours = _subject_names_team(subject, (board_row or {}).get(f"{wanted}_team"), sport)
    theirs = _subject_names_team(subject, (board_row or {}).get(f"{other}_team"), sport)
    if ours and not theirs:
        return True
    # Names the OTHER side, or names both, or names neither: all refuse. Both
    # is a resolver that cannot separate the teams, and neither is a subject we
    # cannot place -- guessing from either is what this function exists to stop.
    return False


def _subject_names_team(subject: Any, team: Any, sport: Any) -> bool:
    """Does the slug's subject token name THIS team, by the alias resolver?

    False on anything unresolvable -- an absent team, a missing resolver, or a
    raise. The caller treats False as "cannot confirm", and every path that
    cannot confirm refuses.
    """
    if not str(team or "").strip():
        return False
    try:
        from syndicate.features.shared.team_aliases import teams_match as alias_match
    except Exception:  # noqa: BLE001
        return False
    try:
        return bool(alias_match(sport, subject, str(team)))
    except Exception:  # noqa: BLE001
        return False


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def load_polymarket_markets() -> tuple[list[Mapping[str, Any]], float | None]:
    """The persisted slate, or `([], None)`.

    Reads the ARTIFACT rather than the venue, like every other consumer in this
    layer: a second independent caller per venue is a documented incident class
    (`#139/#144`, `#148`).
    """
    try:
        from syndicate.features.shared.polymarket_us_markets import GAME_SLATE_ARTIFACT
        from syndicate.features.shared.refresh_state_store import read_json_file, reports_root

        payload = read_json_file(reports_root().joinpath(*GAME_SLATE_ARTIFACT))
    except Exception:
        return [], None
    if not isinstance(payload, Mapping):
        return [], None
    rows = payload.get("markets")
    if not isinstance(rows, list):
        return [], None
    fetched_at = payload.get("fetched_at")
    return [r for r in rows if isinstance(r, Mapping)], (
        float(fetched_at) if isinstance(fetched_at, (int, float)) else None
    )


def _outcome_probabilities(row: Mapping[str, Any]) -> tuple[list[tuple[str, float]] | None, str]:
    """`([(outcome_name, probability)], reason)`. `reason` is "" on success.

    WHY THIS RETURNS A REASON RATHER THAN JUST None. Measured 2026-08-24, the
    first live run: `outcomes_unreadable: 132` (1.7% of 7,940). That single
    counter lumps four different things together, and they call for opposite
    responses — a market with a missing field is broken, while a market quoted
    on ONE SIDE ONLY is a real, tradeable market this join was silently
    discarding. Naming them is how we find out which.

    A one-sided quote is known to exist on this venue: a logged row carried
    `outcomes=["Yes","No"]` against `outcomePrices=["0.0010"]`, and a parallel
    lane measured 88% of soccer live prop quotes as one-sided.
    """
    import json

    def _list(value: Any) -> list[Any] | None:
        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except Exception:
                return None
            return parsed if isinstance(parsed, list) else None
        return None

    raw_names, raw_prices = row.get("outcomes"), row.get("outcomePrices")
    if raw_names in (None, "") or raw_prices in (None, ""):
        return None, "outcomes_field_missing"

    names, prices = _list(raw_names), _list(raw_prices)
    if names is None or prices is None:
        return None, "outcomes_not_a_json_list"
    if not names or not prices:
        return None, "outcomes_empty"
    if len(names) != len(prices):
        # THE ONE-SIDED CASE, and deliberately still a refusal for now.
        # Pairing positionally would assume `prices[0]` belongs to
        # `names[0]` -- plausible, unverified, and wrong half the time if it
        # is not. On a two-outcome market that is a real order on the opposite
        # team. Counted separately so the decision can be made on data.
        return None, "outcomes_count_mismatch"

    out: list[tuple[str, float]] = []
    for name, price in zip(names, prices):
        try:
            out.append((str(name), float(price)))
        except (TypeError, ValueError):
            return None, "price_not_numeric"
    return out, ""


def join_polymarket_to_board(
    markets: Sequence[Mapping[str, Any]],
    board_rows: Sequence[Mapping[str, Any]],
    *,
    sport: str | None = None,
    selected_date: str | None = None,
) -> dict[str, Any]:
    """Pair each board row with the Polymarket market quoting the same bet.

    Every drop is COUNTED BY REASON. A join that reports only its hit count
    cannot be improved: `matched=0` is the same number whether the slugs failed
    to parse, the date was wrong, or the venue simply does not quote the sport.
    """
    refusals: dict[str, int] = {}
    # Shapes behind the parse refusals. A count says how many; only a sample
    # says WHAT, and every unexplained refusal this week needed the sample.
    shapes: list[dict[str, Any]] = []

    def refuse(reason: str) -> None:
        refusals[reason] = refusals.get(reason, 0) + 1

    # THE OUT-OF-SCOPE WORK LIST. Complete counts keyed by (venue type, league)
    # plus one sampled row each -- the same shape that turned Kalshi's
    # `unreadable_title` from a number into an actionable list.
    out_of_scope_counts: dict[str, int] = {}
    out_of_scope_samples: list[dict[str, Any]] = []
    out_of_scope_seen: set[str] = set()

    # A BOARD ROW THE VENUE COULD NOT BE PAIRED WITH -- BOTH SIDES, NOT A COUNT.
    #
    # MEASURED 2026-08-25T18:49:14Z: a `totals under 10.5` position on Minnesota
    # Twins @ Athletics reached the placer with `venue_ticker=None`, because
    # nothing was ever stamped at commit time:
    #
    #   POLYMARKET_NO_SLUG -- venue_ticker unset (type=NoneType)
    #   LIVE_ORDER rejected market=totals side=under line=10.5
    #
    # The order path was right to refuse; the gap is the JOIN. And the join
    # reported it as `no_matching_polymarket_market: 54` -- a number with no
    # way to tell "the venue does not list this game" from "the venue lists it
    # under a name we do not recognise". Those need opposite responses, and
    # guessing between them is what has cost this session repeatedly.
    #
    # `Athletics` is a live example of why the distinction matters: the club
    # moved, so `ATH` / `OAK` / `SAC` are all plausible venue spellings and our
    # club map carries only `ATH`. This prints what the BOARD wanted beside the
    # blobs the VENUE offered for the same league, date and market, so the
    # answer is read rather than inferred.
    unmatched_counts: dict[str, int] = {}
    unmatched_samples: list[dict[str, Any]] = []
    unmatched_seen: set[str] = set()

    # THE COMPLETE CLASSIFICATION beside the bounded sample. The samples above
    # decompose ONE row per (kind, league, market); a RATE needs the whole
    # population, and "2 of 3 samples are rung-misses" is an anecdote wearing a
    # percentage. `<class>|<family>` -> count, counted for EVERY prop no-match
    # row, so `rung_miss|batter_hits / no_match|mlb|batter_hits` is readable
    # from one log line. Invariant, asserted in tests: per family, the class
    # counts sum exactly to `no_match|mlb|<family>`.
    prop_unmatched_classes: dict[str, int] = {}

    # token -> sorted venue lines, for ONE fixture+family. Built at most once
    # per (family, date, fixture) per join and shared by the classifier and
    # the sample builder -- two scanners over the same candidates would be two
    # implementations that must agree, which is the two-guards trap. Cache is
    # naturally bounded by families x dates x fixtures on the slate.
    prop_fixture_profiles: dict[tuple[str, str, str], dict[str, list[float]]] = {}

    def _prop_fixture_profile(
        board_row: Mapping[str, Any],
        board_market: str,
        league: str,
        date: str,
        candidates: Sequence[Mapping[str, Any]],
    ) -> dict[str, list[float]]:
        cache_key = (
            board_market,
            date,
            str(board_row.get("event_id") or "")
            or f"{board_row.get('away_team')}|{board_row.get('home_team')}",
        )
        cached = prop_fixture_profiles.get(cache_key)
        if cached is not None:
            return cached
        profile: dict[str, list[float]] = {}
        for c in candidates:
            cand_prop = c.get("prop")
            if not isinstance(cand_prop, Mapping):
                continue
            cand_token = str(cand_prop.get("token") or "")
            if not cand_token:
                continue
            if not _teams_match(
                board_row, c["parsed"], board_row.get("sport") or sport,
                board_fixtures.get((league, date)),
            ):
                continue
            slot = profile.setdefault(cand_token, [])
            if c.get("line") is not None and float(c["line"]) not in slot:
                slot.append(float(c["line"]))
        for slot in profile.values():
            slot.sort()
        prop_fixture_profiles[cache_key] = profile
        return profile

    def _note_unmatched(
        kind: str,
        board_row: Mapping[str, Any],
        board_market: str,
        league: str,
        date: str,
        candidates: Sequence[Mapping[str, Any]],
        prop_token: str | None = None,
        prop_profile: Mapping[str, Sequence[float]] | None = None,
    ) -> None:
        key = f"{kind}|{league}|{board_market}"
        unmatched_counts[key] = unmatched_counts.get(key, 0) + 1
        if key in unmatched_seen or len(unmatched_samples) >= 10:
            return
        unmatched_seen.add(key)
        sample: dict[str, Any] = {
            "kind": kind,
            "board": f"{board_row.get('away_team')} @ {board_row.get('home_team')}"[:52],
            "want": f"{board_market}|{board_row.get('side')}|{board_row.get('line')}",
            "date": date,
            # WHAT THE VENUE HAD for the same league/date/market. Empty means it
            # listed nothing; a populated list beside a failed match means the
            # game is there and the PAIRING is what failed.
            "offered": [
                f"{c['parsed']['away']}-{c['parsed']['home']}@{c.get('line')}"
                for c in list(candidates)[:5]
            ],
        }
        if prop_token is not None:
            # WHO THE PROP IS ABOUT, because for a prop the fields above name
            # everything EXCEPT the player: `want` is market|side|line and
            # `offered` is fixtures drawn unfiltered from the whole
            # (league, date, market) bucket. Measured 2026-09-01T18:20:10Z:
            # ~230 `no_match|mlb|<prop market>` per cycle, and a token-encoding
            # miss -- `wilcon2` (William Contreras) or `bretbat` (Brett
            # Bateman), the venue's own collision-extended forms our derived
            # 3+3 encoding deliberately never produces -- was indistinguishable
            # in the sample from a rung the venue does not list or a player it
            # does not list. (`prop_modifier_census` cannot see them either:
            # it strips digit-bearing tokens, so `wilcon2`-class rows collapse
            # to bare family shapes there.)
            #
            # `fixture_tokens` is the venue's player tokens for the SAME
            # fixture and family, NEAR tokens first -- collision-extended
            # forms share the 3-char first-name prefix (`wilcon2`/`wilcon`,
            # `bretbat`/`brebat`), so ordering on that prefix keeps them
            # inside the bound instead of truncated behind teammates.
            # `token_lines` is the venue's rungs for OUR token in this
            # fixture. One read now decomposes:
            #   token-miss         near variant in fixture_tokens, ours absent
            #   rung-miss          token_lines non-empty, our line not in them
            #   player-not-listed  fixture_tokens filled by other players only
            #   fixture-miss       offered non-empty, fixture_tokens empty
            #
            # Derived from the SHARED fixture profile (see
            # `_prop_fixture_profile`) when the caller already built one for
            # the complete classifier; the no_candidates call site passes none
            # and the empty-bucket scan below produces empties at zero cost.
            # Profile keys keep candidate insertion order, so near-first here
            # orders identically to the original per-sample scan.
            # Diagnostic only: nothing here changes what is matched.
            if prop_profile is None:
                prop_profile = _prop_fixture_profile(
                    board_row, board_market, league, date, candidates
                )
            near_tokens = [t for t in prop_profile if t[:3] == prop_token[:3]]
            far_tokens = [t for t in prop_profile if t[:3] != prop_token[:3]]
            sample["player"] = str(board_row.get("player_name") or "")[:28]
            sample["token"] = prop_token
            sample["fixture_tokens"] = (near_tokens + far_tokens)[:6]
            sample["token_lines"] = list(prop_profile.get(prop_token) or ())[:6]
        unmatched_samples.append(sample)

    def _note_out_of_scope(venue_type: str, parsed: Mapping[str, Any], row: Mapping[str, Any]) -> None:
        key = f"{venue_type}|{parsed.get('league')}"
        out_of_scope_counts[key] = out_of_scope_counts.get(key, 0) + 1
        if key in out_of_scope_seen or len(out_of_scope_samples) >= 14:
            return
        out_of_scope_seen.add(key)
        out_of_scope_samples.append({
            "key": key,
            "slug": str(row.get("slug") or "")[:64],
            # THE PAGE, so a coverage gap is CHECKABLE rather than just
            # counted. Until the user supplied one confirmed URL on
            # 2026-08-25, this repo had never seen a browsable Polymarket
            # address and the coverage audit refused to construct one -- which
            # left its whole gap table unactionable. It addresses the GAME, not
            # the individual market; see `market_web_url`.
            "url": market_web_url(row.get("slug")),
            # THE QUESTION IS THE PAYLOAD HERE. A slug says which game; only the
            # question says what the bet IS, and that is what decides whether a
            # parser can be written for the family.
            "question": str(row.get("question") or "")[:90],
            "outcomes": str(row.get("outcomes") or "")[:60],
        })

    # Index the venue side once, keyed on what a board row can be asked for.
    index: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    # ONE PASS OVER THE SLATE FIRST, so a competition proven soccer by any of
    # its fixtures is keyed `soccer` for ALL of them -- including the rows whose
    # own tri-codes are ambiguous and deliberately unresolvable. Derived once
    # rather than per row: the test is per COMPETITION, and running it inside
    # the loop would make it depend on iteration order.
    soccer_tokens = soccer_competition_tokens(markets)
    # league token -> a bounded set of its club codes. See the note at the
    # assignment below for why the CODES and not just a count.
    unproven_league_tokens: dict[str, set[str]] = {}
    # `<league>|<market>` -> rows that would pair if the fixture's sides were
    # swapped. Diagnostic only; the flip is never applied.
    orientation_flip_counts: dict[str, int] = {}
    # THE DENOMINATOR. Unmatched rows the flip was actually TRIED on, per
    # `<league>|<market>`. Without it, a sport absent from the rescue counter
    # above is indistinguishable from a sport the flip never ran on.
    orientation_flip_attempts: dict[str, int] = {}
    # THE ELIGIBILITY SPLIT. `listed` is the denominator that makes
    # `flipped` a rate; `not_listed` is coverage; `unreadable` is the
    # honest third bucket where we cannot tell. See `_canonical_fixture`.
    orientation_listed: dict[str, int] = {}
    orientation_not_listed: dict[str, int] = {}
    orientation_unreadable: dict[str, int] = {}
    # HOW listing was established. `by_canonical` is independent of the
    # orientation matcher; `by_flip_only` is not. See the split below.
    orientation_listed_by_canonical: dict[str, int] = {}
    orientation_listed_by_flip_only: dict[str, int] = {}
    # `#595` step 2: does the price we ASSIGN to a side actually belong to it?
    alignment_counts: dict[str, int] = {}
    # Why a `no_candidates` key missed -- see the block that fills it.
    key_miss_samples: list[dict[str, Any]] = []
    # Soccer PROP slug-modifier shapes -- the venue's own vocabulary.
    prop_modifier_census: dict[str, int] = {}
    key_miss_seen: set[str] = set()
    line_source: dict[str, int] = {}
    line_gap_samples: list[dict[str, Any]] = []
    side_gap_samples: list[dict[str, Any]] = []
    ladder_points: dict[tuple[str, str, str], list[tuple[float, float, int]]] = {}
    forward_date_widened: dict[str, int] = {}
    alignment_samples: list[dict[str, Any]] = []
    orientation_flip_samples: list[dict[str, Any]] = []

    # Kill switch for the player-prop admission, ON by default. The prop path
    # feeds the QUOTE CAPTURE; the money path is gated separately and OFF in
    # `portfolio_commit._polymarket_price_resolver`, so this switch exists
    # only to turn the instrumentation off without a code deploy.
    import os as _os

    prop_join_enabled = str(
        _os.environ.get("SYNDICATE_POLYMARKET_PROP_JOIN") or ""
    ).strip().lower() not in {"0", "off", "false", "no"}

    for row in markets:
        parsed = parse_slug(row.get("slug"))
        if parsed is None:
            refuse("slug_unparseable")
            continue
        venue_type = str(row.get("sportsMarketTypeV2") or "").upper()
        board_market = MARKET_TYPE_TO_BOARD.get(venue_type)
        # THE PROP VOCABULARY, CENSUSED SO THE NEXT FAMILY DOES NOT NEED A GUESS.
        #
        # THIS CENSUS IS WHY CORNERS WORKS. The corners route used to key on
        # `row["question"]`, which is NEVER POPULATED in the persisted slate --
        # 14 of 14 sampled questions were the empty string. It was inert, and
        # its 221 `no_candidates` read as "the venue lists no corners", which
        # was never measured. This line measured it: `cor-all`, 434 rows. KEEP
        # IT -- it is the standing instrument for the next unknown family, and
        # it is the reason `fh`/`sh` were caught as unscreened halves too.
        #
        # BTTS was found because its slug carries a plain `-btts` token. This
        # counts the modifier SHAPES on every soccer PROP row so the rest of
        # the vocabulary is readable the same way -- the instrument that made
        # Kalshi's soccer titles fixable rather than guessable.
        #
        # NUMBERS STRIPPED, so `exact-score-0-0` and `exact-score-2-1` collapse
        # to one family instead of one row each. Bounded to 40 shapes.
        #
        # ABOVE THE `board_market is None` REFUSAL, DELIBERATELY. Placed below
        # it the census only ever saw PROP rows already ADMITTED -- `btts` and
        # nothing else -- which makes an instrument for finding UNKNOWN
        # families structurally unable to find one. Same placed-below-the-guard
        # mistake as the fixture matcher earlier today, caught here because the
        # census returned `{'btts': 1}` on a fixture that also contained an
        # exact-score row.
        if venue_type == "SPORTS_MARKET_TYPE_PROP":
            # EVERY SPORT, NOT JUST SOCCER -- and the soccer-only gate is the
            # reason this had to be widened.
            #
            # MEASURED 2026-08-29T19:08:56Z: the venue discards
            # `SPORTS_MARKET_TYPE_PROP|mlb 5000` every cycle -- the LARGEST
            # family it lists -- plus ufc 1039, cfb 556, nfl 119. This census
            # could not see any of it, and the `_note_out_of_scope` sampler caps
            # at 14 keys and never reached MLB. So the platform had a COUNT with
            # NO SHAPE for its biggest discarded family.
            #
            # That is exactly the state corners were in for a day: 221 refusals
            # that read as "the venue does not list them" while it listed 434.
            # A count without a vocabulary cannot answer whether those 5,000 are
            # player lines the board wants or team props nothing asks for, and
            # that question decides whether player props are worth wiring at all.
            #
            # KEYED BY LEAGUE, because the answer differs per sport: soccer's
            # props are team-level (`ftts`, `exact-score`) while MLB's are most
            # likely player lines, and one merged vocabulary would hide that.
            league_key = _norm(_effective_league(parsed, soccer_tokens)) or "?"
            shape = "-".join(
                tok for tok in (parsed.get("modifiers") or [])
                if not any(ch.isdigit() for ch in tok)
            ) or "(no-modifier)"
            key = f"{league_key}|{shape}"
            if key in prop_modifier_census or len(prop_modifier_census) < 60:
                prop_modifier_census[key] = prop_modifier_census.get(key, 0) + 1


        if board_market is None:
            # ONE PROP FAMILY IS ADMITTED BY NAME, AND ONLY BY NAME.
            #
            # Polymarket types BTTS as `SPORTS_MARKET_TYPE_PROP`, so it was
            # refused wholesale with the other 8,029 -- while the board carries
            # 36 `btts` rows it can never reach. MEASURED 2026-08-28, three of
            # them on fixtures this lane has been chasing all day:
            #
            #     astatc-lg1-lil-psg-2026-08-28-btts    Lille v PSG
            #     astatc-sea-mil-ven-2026-08-28-btts    Milan v Venezia
            #     astatc-lal-ala-vil-2026-08-28-btts    Alaves v Villarreal
            #
            # THE SLUG MODIFIER IS THE WHOLE IDENTIFICATION -- `-btts`, a plain
            # token this module already parses. No question text, no grammar.
            #
            # ADMITTED INDIVIDUALLY, NEVER BY OPENING `PROP`. The same bucket
            # holds `exact-score-0-0` and `winner-1h-was`, which MUST keep
            # refusing: an exact-score market is not a board row and a 1H
            # winner is a segment. The module header's refusal of PROP stands;
            # this is one named family stepping out of it with its own
            # evidence, which is how `DRAWABLE_OUTCOME` was admitted in August.
            #
            # `_has_segment` below still screens period variants, so a
            # first-half BTTS cannot be priced as a full-game one.
            if venue_type == "SPORTS_MARKET_TYPE_PROP" and "btts" in (
                parsed.get("modifiers") or []
            ):
                board_market = "btts"
            elif venue_type == "SPORTS_MARKET_TYPE_PROP" and "cor" in (
                parsed.get("modifiers") or []
            ) and "all" in (parsed.get("modifiers") or []):
                # CORNERS, IDENTIFIED FROM THE SLUG MODIFIER `cor-all`.
                #
                # THE PREVIOUS ROUTE KEYED ON `row["question"]` AND COULD NEVER
                # FIRE -- that field is the empty string in every persisted
                # slate row, and `/api/ops/polymarket/slate` exposes only
                # line/orderable/outcomes/slug. It was kept as a named gap with
                # an explicit instruction to DELETE it if the census found no
                # corners family, on the reasoning that 19 sampled PROP slugs
                # showed only ftts/exact-score/btts.
                #
                # THE CENSUS FOUND THE OPPOSITE. `prop_modifier_census`, read
                # 2026-08-29T04:14:58Z:
                #
                #     exact-score 930 · fh-exact-score 496 · cor-all 434
                #     · btts 62 · ftts-none 62 · ...
                #
                # 434 corners rows -- the third-largest soccer PROP family at
                # the venue -- against 239 `alternate_totals_corners` board
                # rows. The 19-slug sample was not a rate; deleting on it would
                # have removed the route to a market the venue lists 434 times
                # and recorded "the venue does not publish corners" as fact.
                #
                # `all` IS REQUIRED, NOT DECORATIVE. It is the full-match
                # qualifier, and it is the only corners shape observed -- there
                # is no bare `cor` in the census. Requiring it means a future
                # period variant refuses rather than being priced as full-game,
                # which is the failure `_has_segment` exists for and which the
                # BTTS branch above shipped for `fh`/`sh` earlier today.
                #
                # ADMITTED INDIVIDUALLY, NEVER BY OPENING `PROP` -- the same
                # rule BTTS was admitted under one branch up. The bucket still
                # holds exact-score and LoL map winners, which must keep
                # refusing.
                #
                # THE LINE STILL COMES FROM THE SLUG (`_line_from_modifiers`,
                # e.g. `cor-all-9pt5` -> 9.5). A corners total without a number
                # would match any corners line at all, so a slug carrying none
                # refuses downstream rather than pricing the wrong contract.
                board_market = "alternate_totals_corners"
        prop_info: dict[str, Any] | None = None
        if (
            board_market is None
            and prop_join_enabled
            and venue_type == "SPORTS_MARKET_TYPE_PROP"
        ):
            # MLB PLAYER PROPS, admitted per family from the measured census
            # -- see `_parse_player_prop` and the constants block. A slug that
            # does not fit the measured three-modifier `gte` shape falls
            # through to the out-of-scope census below, where an unadmitted
            # family stays countable.
            prop_info = _parse_player_prop(parsed)
            if prop_info is not None:
                board_market = prop_info["market"]
        if board_market is None:
            # PROP lands here -- a real market, deliberately out of scope (see
            # the module header). DRAWABLE_OUTCOME no longer does; it is in
            # `MARKET_TYPE_TO_BOARD` as of 2026-08-25, so this branch is
            # unreachable for it now -- the note below predates that fix.
            #
            # PROP is fetched every cycle and thrown away, so "out of scope"
            # needs to be a MEASURED decision rather than a standing one.
            #
            # WHAT `PROP` ACTUALLY CONTAINS IS NOT OBVIOUS, and assuming it was
            # already produced one wrong claim. Measured 2026-08-25T17:05:02Z:
            #
            #   slug='astatc-lol-bam-gng-2026-08-20-game1'
            #   type='SPORTS_MARKET_TYPE_PROP'
            #   question='Will Baam Esports win Game 1 vs GnG Amazigh?'
            #
            # That is a League of Legends MAP WINNER, not a player prop. So
            # `PROP` is a mixed bucket and the 6,838 cannot be characterised
            # without looking. This samples one row per (type, league) with the
            # slug and the QUESTION -- the question is what names the bet, the
            # slug alone does not -- and counts every one completely, so a
            # family that is absent is distinguishable from one past the cap.
            _note_out_of_scope(venue_type, parsed, row)
            refuse("market_type_not_a_game_line")
            continue
        if _has_segment(parsed["modifiers"]):
            _note_out_of_scope(f"{venue_type}|SEGMENT", parsed, row)
            refuse("segment_market_not_full_game")
            continue
        outcomes, outcome_reason = _outcome_probabilities(row)
        if not outcomes:
            refuse(outcome_reason or "outcomes_unreadable")
            # A SAMPLE OF THE SHAPE, not the values -- enough to see what the
            # venue actually sent without turning the log line into the payload.
            if len(shapes) < 6:
                shapes.append({
                    "slug": str(row.get("slug") or "")[:60],
                    "type": str(row.get("sportsMarketTypeV2") or ""),
                    "reason": outcome_reason,
                    "outcomes": str(row.get("outcomes"))[:80],
                    "prices": str(row.get("outcomePrices"))[:80],
                })
            continue
        row_league = _effective_league(parsed, soccer_tokens)
        # THE WORK LIST FOR THE COMPETITIONS STILL OUT OF REACH.
        #
        # A game-line row whose league is neither `soccer` nor a sport we model
        # is a competition NOTHING on the board can ever look up -- the board
        # stamps every soccer row `sport="soccer"`, so a row filed under `nas`
        # or `arg2` is unreachable by construction. That was previously a
        # silence: the rows were indexed under a key no lookup uses and nobody
        # counted them.
        #
        # The CLUB CODES are what make this actionable rather than another
        # count. Both tests in `soccer_competition_tokens` failed for every one
        # of this token's fixtures, and the reason is that Polymarket's
        # tri-codes are its OWN vocabulary, not ESPN's abbreviations -- measured
        # 2026-08-28, `ner dcu sje nas fcc vwh aus sdg lag mim` are absent from
        # the derived alias map entirely. Each code printed here is one
        # confirmable club, which is the ONLY basis on which a vendor alias may
        # be added. Guessing them from the name is how a bet reaches the wrong
        # team, and `_soccer_alias_to_name` drops ambiguous keys precisely to
        # stop that -- so this emits evidence and deliberately does not act.
        if (
            row_league
            and row_league != "soccer"
            and row_league not in _NON_SOCCER_LEAGUE_TOKENS
            and len(unproven_league_tokens) < 40
        ):
            seen = unproven_league_tokens.setdefault(row_league, set())
            if len(seen) < 8:
                seen.update(
                    str(code) for code in (parsed.get("home"), parsed.get("away")) if code
                )
        key = (row_league, parsed["date"], board_market)
        index.setdefault(key, []).append(
            {"parsed": parsed, "row": row, "outcomes": outcomes,
             # A prop's line comes from its `gte` token and NOWHERE else --
             # `_resolved_line` would fall back to the row's `line` field,
             # which has never been measured for props, and its counters
             # would drown in per-player noise.
             "prop": prop_info,
             "line": (
                 prop_info["line"] if prop_info is not None
                 else _resolved_line(parsed, row, board_market, line_source, line_gap_samples)
             ),
             # THE FIXTURE AS AN UNORDERED PAIR OF CANONICAL CLUB NAMES, or
             # None when either token will not canonicalise. Computed ONCE per
             # market here rather than per unmatched row, which is the
             # difference between one pass over ~17k markets and a nested scan.
             #
             # Deliberately NOT `teams_match`: see `_canonical_fixture`.
             # `_canonical_fixture` first; the venue tri-code table as a
             # fallback, so a fixture whose codes only Polymarket names still
             # becomes classifiable instead of counting as unreadable forever.
             "canon_pair": _canonical_fixture(
                 row_league, parsed.get("home"), parsed.get("away")
             ) or _venue_canonical_fixture(parsed)}
        )

    # THE SAME MARKETS KEYED WITHOUT THE DATE, for the forward-horizon lookup
    # below. Built once here for the same reason `board_fixtures` is: scanning
    # `index` on every missed row would be O(rows x keys).
    by_league_market: dict[tuple[str, str], list[tuple[str, list[dict[str, Any]]]]] = {}
    for (_lg, _dt_key, _mk), _entries in index.items():
        by_league_market.setdefault((_lg, _mk), []).append((_dt_key, _entries))
    for _slots in by_league_market.values():
        _slots.sort(key=lambda pair: pair[0])

    # BOARD FIXTURES PER (LEAGUE, DATE) -- the "matchups by league" the token
    # elimination below reasons over. Built once; a nested scan per unmatched
    # row would be O(rows x rows) on a 1,300-row board.
    board_fixtures: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for board_row in board_rows:
        bl = _norm(board_row.get("sport") or sport)
        bd = str(
            board_row.get("selected_date") or board_row.get("date") or selected_date or ""
        ).strip()
        bh = board_row.get("home") or board_row.get("home_team")
        ba = board_row.get("away") or board_row.get("away_team")
        if bl and bd and bh and ba:
            pair = (str(bh), str(ba))
            slot = board_fixtures.setdefault((bl, bd), [])
            if pair not in slot:
                slot.append(pair)

    # WHICH BOARD PLAYERS SHARE A DERIVED TOKEN, PER GAME. Two of our own
    # players encoding to one token cannot be told apart at the venue, so BOTH
    # refuse -- picking either is the wrong-person order this module exists to
    # prevent. Keyed on the board's own `event_id` (the game IS part of a
    # prop's identity -- learned the hard way, see `_resolver_key`), owners
    # deduplicated through `normalize_person` so two spellings of one player
    # do not read as a collision.
    from syndicate.features.shared.kalshi_board_join import normalize_person as _norm_person
    from syndicate.features.shared.market_keys import canonical_market_key as _canon_market

    prop_token_owners: dict[tuple[str, str], set[str]] = {}
    for board_row in board_rows:
        _raw_mk = str(board_row.get("market") or "").strip().lower()
        _canon_mk = _canon_market(board_row.get("sport"), _raw_mk) or _raw_mk
        if _canon_mk not in _JOINABLE_PROP_BOARD_MARKETS:
            continue
        _tok = _polymarket_player_token(board_row.get("player_name"))
        if not _tok:
            continue
        prop_token_owners.setdefault(
            (str(board_row.get("event_id") or ""), _tok), set()
        ).add(_norm_person(board_row.get("player_name")))

    matches: list[dict[str, Any]] = []
    for board_row in board_rows:
        board_market = str(board_row.get("market") or "").strip().lower()
        is_prop = False
        prop_token: str | None = None
        if board_market not in _JOINABLE_BOARD_MARKETS:
            # THE PROP GATE. Canonicalised first (`pitcher_strikeouts` and
            # `strikeouts` are one market, `#224`), then bounded exactly the
            # way the venue side is: MLB only, player present, token
            # derivable, token unambiguous among OUR OWN players for this
            # game. Every bound refuses BY NAME -- a prop that stops matching
            # with no reason emitted is indistinguishable from a venue that
            # stopped quoting.
            _canon_mk = _canon_market(board_row.get("sport"), board_market) or board_market
            if (
                prop_join_enabled
                and _canon_mk in _JOINABLE_PROP_BOARD_MARKETS
                and _norm(board_row.get("sport") or sport) == "mlb"
            ):
                if not str(board_row.get("player_name") or "").strip():
                    refuse("prop_row_missing_player")
                    continue
                prop_token = _polymarket_player_token(board_row.get("player_name"))
                if not prop_token:
                    refuse("prop_player_token_underivable")
                    continue
                owners = prop_token_owners.get(
                    (str(board_row.get("event_id") or ""), prop_token)
                ) or set()
                if len(owners) > 1:
                    refuse("prop_player_token_ambiguous")
                    continue
                board_market = _canon_mk
                is_prop = True
            else:
                refuse("board_market_not_a_game_line")
                continue
        # THE MIRROR OF THE VENUE-SIDE GUARD ABOVE. That one refuses a segment
        # MARKET; this refuses a segment ROW. Without both, the only markets in
        # the index are full-game and the only thing a `first3` row can match is
        # the wrong contract -- which is what it did, four times, for real money.
        #
        # Counted rather than dropped: `_resolver_key` now also refuses these,
        # but silently, and a bet that stops being placed with no reason emitted
        # is indistinguishable from a venue that stopped quoting.
        from syndicate.features.shared.kalshi_catalogue import FULL_GAME_SEGMENT

        if str(board_row.get("segment") or FULL_GAME_SEGMENT).strip().lower() != FULL_GAME_SEGMENT:
            refuse("board_row_is_a_segment_bet")
            continue
        league = _norm(board_row.get("sport") or sport)
        # THE CALLER'S DATE IS THE FALLBACK, and in practice it is the value
        # that does the work. MEASURED 2026-08-25T01:23:04Z, the first build
        # where game-line rows reached this loop at all:
        #
        #   board_rows=10 matched=0
        #     board_market_not_a_game_line=6
        #     no_polymarket_market_for_league_date_market=4
        #
        # All four game-line rows refused for want of a candidate. Shortlist
        # rows carry neither `selected_date` nor `date` -- `_board_rows_for_join`
        # returns them verbatim from `read_layer2_shortlist` and nothing stamps
        # one on -- so this read produced "" and the index key could never match
        # a slug's real date. The same shape as `apply_venue_quotes` reading a
        # key board rows do not carry, which reported a confident stamped=0
        # earlier the same evening.
        #
        # Row first, so a row that DOES carry its own date still wins; a
        # multi-date board must not be collapsed onto one caller's date.
        date = str(
            board_row.get("selected_date")
            or board_row.get("date")
            or selected_date
            or ""
        ).strip()
        wanted_key = (league, date, board_market)
        candidates = index.get(wanted_key) or []
        # ------------------------------------------------------------------
        # THE BOARD DATES BY SLATE; THE VENUE DATES BY FIXTURE.
        # ------------------------------------------------------------------
        #
        # A shortlist row carries no date of its own, so `date` above falls
        # back to `selected_date` -- the date of the FILE being priced, i.e.
        # today. Polymarket's slug carries the date the fixture is PLAYED. For
        # a same-day sport those are the same string and this never fires.
        #
        # The soccer board is not same-day. `#545` widened the card build to
        # TWO MATCHDAYS per league "to cover the board's forward horizon", so
        # most soccer rows describe a fixture that has not happened yet.
        #
        # MEASURED 2026-08-29T04:14:58Z, and it is not a coverage gap:
        #
        #     venue soccer rows      420 h2h + 750 spreads + 868 totals = 2,038
        #     of them on 2026-08-28  0        (`markets_for_our_league_date: []`)
        #     board soccer h2h rows refusing  118 -- i.e. ALL of them
        #
        # 2,038 markets the board cannot see, because every one is filed under
        # the day it is played and the board asked for today.
        #
        # SOCCER ONLY, AND THE GATE IS THE WHOLE SAFETY ARGUMENT. MLB plays the
        # SAME FIXTURE on consecutive days -- a three-game series is one club
        # pair on three dates -- so widening by date there could price tonight's
        # game off tomorrow's market, which is a worse bug than the one being
        # fixed. Soccer club pairs do not repeat inside a two-matchday horizon.
        #
        # FORWARD ONLY. `d >= date` excludes SETTLED markets: the slate still
        # carries 2026-08-16 rows, and matching one would price a live board row
        # off a resolved contract at 0.99.
        #
        # NOTHING HERE RELAXES THE FIXTURE TEST. The widened rows go through the
        # same `_teams_match` loop and the same ambiguity refusal below, so a
        # two-legged tie that does repeat a club pair refuses as ambiguous
        # rather than guessing a leg.
        if not candidates and date and _norm(board_row.get("sport") or sport) == "soccer":
            try:
                _horizon = (
                    _dt.date.fromisoformat(date) + _dt.timedelta(days=_FORWARD_HORIZON_DAYS)
                ).isoformat()
            except ValueError:
                _horizon = ""
            if _horizon:
                widened: list[dict[str, Any]] = []
                for _cand_date, _entries in by_league_market.get((league, board_market)) or ():
                    if date <= _cand_date <= _horizon:
                        widened.extend(_entries)
                if widened:
                    candidates = widened
                    _wkey = f"{league}|{board_market}"
                    forward_date_widened[_wkey] = forward_date_widened.get(_wkey, 0) + 1
        if not candidates:
            # WHY THE KEY MISSED, not just that it did.
            #
            # `no_candidates` says the bucket was empty and stops there, which
            # is why BTTS is currently unexplainable: venue BTTS rows ARE
            # indexed (+198 markets on 2026-08-28) and 34 board rows still find
            # nothing, so the two halves are keyed DIFFERENTLY -- and neither
            # key was ever printed. A refusal that cannot say which component
            # disagreed sends the reader to guess between league, date and
            # market.
            #
            # Bounded to six board markets so a slate-wide miss cannot turn the
            # log line into the index. Nothing here changes what is matched.
            if len(key_miss_samples) < 6 and board_market not in key_miss_seen:
                key_miss_seen.add(board_market)
                same_market = sorted(
                    {(k[0], k[1]) for k in index if k[2] == board_market}
                )[:4]
                same_league_date = sorted(
                    {k[2] for k in index if k[0] == league and k[1] == date}
                )[:8]
                key_miss_samples.append({
                    "wanted": f"{league}|{date}|{board_market}",
                    # Which (league, date) DO carry this market -- if this is
                    # non-empty the market is indexed and the league or the
                    # date is the disagreement.
                    "market_indexed_under": [f"{a}|{b}" for a, b in same_market],
                    # Which markets DO exist for our league and date -- if this
                    # is non-empty the fixture bucket exists and the MARKET
                    # name is the disagreement.
                    "markets_for_our_league_date": same_league_date,
                })
            _note_unmatched(
                "no_candidates", board_row, board_market, league, date, [],
                prop_token=prop_token,
            )
            refuse("no_polymarket_market_for_league_date_market")
            continue

        board_line = _as_float(board_row.get("line"))
        side = str(board_row.get("side") or "").strip()
        picked: dict[str, Any] | None = None
        # Whether THIS row's search ended in ambiguity, read as a delta on the
        # shared counter -- the prop no-match path below must not stack a
        # second refusal on a row the ambiguity guard already refused.
        _ambiguous_before = refusals.get("ambiguous_polymarket_match", 0)
        for candidate in candidates:
            if is_prop:
                # A prop's identity is (game, market, PLAYER, line) -- the
                # player and the line are both mandatory, exact, and derived,
                # never fuzzy. A candidate without prop fields is a game-line
                # market sharing nothing but the bucket.
                cand_prop = candidate.get("prop")
                if not isinstance(cand_prop, Mapping):
                    continue
                if str(cand_prop.get("token") or "") != prop_token:
                    continue
                if board_line is None or candidate["line"] is None:
                    continue
                if abs(float(candidate["line"]) - float(board_line)) > 1e-9:
                    continue
            elif board_market in _LINE_BEARING_BOARD_MARKETS:
                if board_line is None or candidate["line"] is None:
                    continue
                if abs(float(candidate["line"]) - float(board_line)) > 1e-9:
                    continue
            # THE LEG, for a venue that splits a 3-way into three binaries.
            # Without this every leg of a soccer h2h matches the same board row
            # and the ambiguity guard refuses all of them -- 186 rows on
            # 2026-08-29T05:16:29Z. Only Yes/No contracts asked about a ROLE
            # side reach this; `btts` (yes/no) and totals (over/under) name
            # their own outcome and are untouched.
            if (
                str(side or "").strip().lower() in _ROLE_SIDES
                and _is_yes_no_market(candidate["outcomes"])
                and not _subject_is_side(
                    candidate, board_row, side, board_row.get("sport") or sport
                )
            ):
                continue
            if not _teams_match(
                board_row, candidate["parsed"], board_row.get("sport") or sport,
                board_fixtures.get((league, date)),
            ):
                continue
            if picked is not None:
                # AMBIGUITY IS A REFUSAL. Two venue markets claiming one board
                # row, resolved by iteration order, is a bet on whichever came
                # first -- confident and wrong half the time.
                picked = None
                refuse("ambiguous_polymarket_match")
                break
            picked = candidate
        if picked is None and is_prop:
            # NO ORIENTATION FORENSICS FOR PROPS. The flip counters below are
            # a calibrated instrument for a soccer GAME-LINE question, read
            # denominator-first in production; letting ~200 prop rows per
            # cycle into `tried` would move every rate it reports without
            # touching the question it answers. A prop that found candidates
            # and paired none is a token, rung, or listing miss -- and which
            # one is readable from the sample: `prop_token` makes
            # `_note_unmatched` print the player, our derived token, and the
            # venue's tokens for this fixture+family beside the rungs it
            # offers for ours. See the decomposition table there.
            #
            # AND COUNTED COMPLETELY, not just sampled. The first production
            # read of the samples (2026-09-01T19:18:45Z) showed 2 rung-misses
            # and 1 player-not-listed -- three rows standing in for ~224, which
            # is a reading, not a rate. The class counter makes the rate: per
            # family, these buckets sum exactly to `no_match|mlb|<family>`.
            # Class order is decisive-first: our token listed at other lines
            # (rung_miss) beats a shared 3-char prefix (near_token, the
            # `wilcon2`-class candidate), beats other players only
            # (player_not_listed), beats a bucket holding no row for OUR
            # fixture at all (fixture_miss).
            if refusals.get("ambiguous_polymarket_match", 0) == _ambiguous_before:
                _profile = _prop_fixture_profile(
                    board_row, board_market, league, date, candidates
                )
                if _profile.get(prop_token):
                    _cls = "rung_miss"
                elif any(t[:3] == prop_token[:3] for t in _profile):
                    _cls = "near_token"
                elif _profile:
                    _cls = "player_not_listed"
                else:
                    _cls = "fixture_miss"
                _cls_key = f"{_cls}|{board_market}"
                prop_unmatched_classes[_cls_key] = (
                    prop_unmatched_classes.get(_cls_key, 0) + 1
                )
                _note_unmatched(
                    "no_match", board_row, board_market, league, date, candidates,
                    prop_token=prop_token, prop_profile=_profile,
                )
                refuse("no_matching_polymarket_market")
            continue
        if picked is None:
            # ----------------------------------------------------------
            # WOULD THIS ROW PAIR IF THE FIXTURE'S SIDES WERE SWAPPED?
            # ----------------------------------------------------------
            #
            # COUNTING ONLY. Nothing below changes what is matched or priced;
            # the row still refuses. This exists because a single fixture
            # suggested an orientation bug and one fixture is an anecdote:
            #
            #   board  'Elche CF @ Real Racing Club de Santander' totals under 2.5
            #   venue  offered rrc-elc@0.5 @1.5 @2.5 @3.5
            #
            # Same two clubs, same line, refused. `parse_slug` reads
            # `<away>-<home>`, so `rrc-elc` gives home=elc / away=rrc while the
            # board has home=Racing / away=Elche. Flipped, it pairs:
            # `teams_match('soccer','rrc','Real Racing Club de Santander')` is
            # True and the same call with `elc` is False.
            #
            # PER SPORT, AND THAT IS THE POINT. MLB and NFL game lines pair
            # correctly today, so they are the control: if the flip rescues
            # soccer and leaves them near zero, the slug order genuinely
            # differs by sport. If it rescues MLB too, the orientation reading
            # is wrong and the cause is elsewhere -- a counter that could only
            # confirm would not be worth printing.
            #
            # THE FLIP IS NOT APPLIED. Acting on a plausible orientation
            # without ground truth is the `pos`/`neg` trap in a new costume: a
            # confident bet on the wrong team. This produces the rate that
            # decides whether the question is worth chasing, and nothing else.
            _row_attempted = False
            _flip_matched = False
            for candidate in candidates:
                if board_market in {"spreads", "totals"}:
                    if board_line is None or candidate["line"] is None:
                        continue
                    if abs(float(candidate["line"]) - float(board_line)) > 1e-9:
                        continue
                parsed_candidate = candidate["parsed"]
                flipped = dict(parsed_candidate)
                flipped["home"], flipped["away"] = (
                    parsed_candidate.get("away"),
                    parsed_candidate.get("home"),
                )
                # THE DENOMINATOR, AND WITHOUT IT THE CONTROL IS NOT ONE.
                #
                # The rescue counter below only ever gains a key when a flip
                # SUCCEEDS, so a sport's absence from it was being read as
                # "tried and never matched". It cannot mean that on its own. An
                # absent key is equally "the flip was never attempted here",
                # and those imply opposite conclusions.
                #
                # WORSE, THE CONTROL WAS SELECTED FOR THE PROPERTY THAT HOLLOWS
                # IT OUT: mlb/nfl are the control BECAUSE they pair correctly
                # today, which is exactly the condition that leaves them almost
                # no unmatched rows to try. The cleaner the control sport
                # pairs, the less its silence proves. Caught by a second reader
                # (`portfolio-endpoint-improvements`) BEFORE the first
                # production run, which is the only reason the first reading is
                # interpretable at all.
                #
                # Counted once per ROW, not per candidate: the question is how
                # many unmatched rows the flip was tried on. `mlb|h2h 0 of 47
                # tried` is a control; `mlb|h2h 0 of 0 tried` is an untested
                # branch, and they must not print the same way.
                if not _row_attempted:
                    _row_attempted = True
                    attempt_key = f"{league}|{board_market}"
                    orientation_flip_attempts[attempt_key] = (
                        orientation_flip_attempts.get(attempt_key, 0) + 1
                    )
                if _teams_match(
                    board_row, flipped, board_row.get("sport") or sport,
                    board_fixtures.get((league, date)),
                ):
                    key = f"{league}|{board_market}"
                    _flip_matched = True
                    orientation_flip_counts[key] = orientation_flip_counts.get(key, 0) + 1
                    if len(orientation_flip_samples) < 8:
                        orientation_flip_samples.append({
                            "board": f"{board_row.get('away_team')}@{board_row.get('home_team')}",
                            # From the ROW. `parse_slug` returns prefix/league/
                            # away/home/date/modifiers and carries no `slug`
                            # key, so reading one there would print an empty
                            # string for every sample and the evidence would be
                            # silently useless.
                            "slug": str((candidate.get("row") or {}).get("slug") or "")[:60],
                            # NAMED NEUTRALLY, BECAUSE THE OLD NAME WAS THE
                            # ASSUMPTION UNDER TEST. This was `slug_away_home`,
                            # which asserts `parse_slug`'s `<away>-<home>`
                            # reading in the very field collected to question
                            # it -- a premise stated as a label, which is how a
                            # wrong one survives review.
                            #
                            # REFUTED FOR SOCCER, 2026-08-28, against ESPN
                            # scoreboards and verified independently in two
                            # sessions:
                            #   eng.1  Manchester City @ Crystal Palace
                            #          slug atc-epl-cry-mnc  -> cry = HOME, FIRST
                            #   fra.1  Paris Saint-Germain @ Lille
                            #          slug atc-lg1-lil-psg  -> lil = HOME, FIRST
                            #   esp.1  Villarreal @ Alaves
                            #          slug atc-lal-ala-vil  -> ala = HOME, FIRST
                            # Our board is CORRECT on all three; the soccer slug
                            # is HOME-first. MLB is away-first (`aec-mlb-lad-det`
                            # = Dodgers @ Tigers) and pairs correctly today, so
                            # the order really does differ by sport.
                            #
                            # Still NOT a licence to flip: see the lane notes on
                            # what the 10-of-106 denominator can and cannot say.
                            "slug_first_second": f"{parsed_candidate.get('away')}-{parsed_candidate.get('home')}",
                            "market": board_market,
                            "line": board_line,
                        })
                    break

            # ---------------------------------------------------------------
            # IS THIS FIXTURE LISTED AT ALL, ORIENTATION ASIDE?
            # ---------------------------------------------------------------
            #
            # The denominator that turns `flipped/tried` into a rate: a row
            # whose fixture the venue never listed sits in `tried` and cannot
            # reach the numerator, so that ratio moves with COVERAGE rather
            # than with orientation.
            #
            # RUNS AFTER THE FLIP LOOP, AND THAT ORDER IS THE FIX. The first
            # version classified BEFORE it and could not use the one piece of
            # hard evidence available: **a flip-match PROVES the fixture is
            # listed.** Production 18:55:16Z returned `flipped={'soccer|h2h':
            # 9}` against `listed={'soccer|h2h': 4}` -- nine rows paired with a
            # fixture the classifier said was absent five times over. The data
            # falsified the instrument on its first run.
            #
            # `flipped <= listed` IS NOW AN INVARIANT rather than a hope, and
            # it is the cheapest self-check this counter can carry: any future
            # regression in the classifier shows up as a violation of an
            # inequality the same log line already prints.
            #
            # AND `not_listed` NEEDS EVERY CANDIDATE READABLE. The first
            # version concluded absence from `elif readable` -- some candidates
            # canonicalised and none matched ours, therefore ours is absent.
            # That does not follow: OUR fixture's candidate may be one of the
            # unreadable ones, and other candidates reading fine says nothing
            # about it. That reproduced, one level down, the exact conflation
            # this counter exists to remove -- `no_match` mixing "listed but
            # unpairable" with "not listed". Absence is now claimed only when
            # the whole bucket canonicalised.
            eligibility_key = f"{league}|{board_market}"
            board_pair = _canonical_fixture(
                board_row.get("sport") or sport,
                board_row.get("home") or board_row.get("home_team"),
                board_row.get("away") or board_row.get("away_team"),
            )
            # SPLIT BY HOW LISTING WAS ESTABLISHED, AND THAT IS THE WHOLE
            # POINT OF THIS BLOCK.
            #
            # `listed` was `flip_matched OR canonical_pair_matched`, reported as
            # one number, and used as the DENOMINATOR for `flipped / listed`.
            # If the canonical test never independently establishes listing,
            # that denominator is just the numerator wearing a denominator's
            # clothes and the rate is 1.0 TAUTOLOGICALLY -- a ratio that cannot
            # come out any other way is not a measurement.
            #
            # MEASURED, and this is why it is being split rather than trusted:
            # two consecutive production readings returned `listed` and
            # `would_match_if_flipped` IDENTICAL -- 5/5, then 24/24. Flagged by
            # a second reader (`layer-2-board-recommendation-engine`) as a
            # coincidence worth distrusting, and they were right. That output
            # cannot distinguish "every identifiable listed fixture is inverted"
            # (the hypothesis) from "the canonical test contributes nothing"
            # (an instrument that always reads 1.0).
            #
            # `by_canonical` is the INDEPENDENT evidence: the fixture was
            # identified by comparing canonical club pairs, without consulting
            # the orientation matcher at all. `by_flip_only` is the dependent
            # kind. A rate computed against `by_canonical` cannot be circular;
            # one computed against the total can be, and now says so.
            canonical_listed = board_pair is not None and any(
                c.get("canon_pair") == board_pair for c in candidates
            )
            if canonical_listed or _flip_matched:
                orientation_listed[eligibility_key] = (
                    orientation_listed.get(eligibility_key, 0) + 1
                )
                bucket = (
                    orientation_listed_by_canonical
                    if canonical_listed
                    else orientation_listed_by_flip_only
                )
                bucket[eligibility_key] = bucket.get(eligibility_key, 0) + 1
            elif board_pair is not None and all(c.get("canon_pair") for c in candidates):
                orientation_not_listed[eligibility_key] = (
                    orientation_not_listed.get(eligibility_key, 0) + 1
                )
            else:
                orientation_unreadable[eligibility_key] = (
                    orientation_unreadable.get(eligibility_key, 0) + 1
                )

            if "ambiguous_polymarket_match" not in refusals or refusals.get("ambiguous_polymarket_match", 0) == 0:
                _note_unmatched(
                    "no_match", board_row, board_market, league, date, candidates
                )
                refuse("no_matching_polymarket_market")
            continue

        if is_prop:
            # THE SAME-NAME COLLISION GUARD, and it runs ONLY on a row that
            # just matched -- a refusal path cannot pick a wrong person. The
            # venue extends a colliding token league-wide (`wilcon2` beside
            # `wilcon`, `bretbat` beside `brebat`); we derive only the plain
            # form, so when BOTH forms sit in the fixture we just matched,
            # the plain rows we picked belong to WHICHEVER of the two the
            # venue keyed plain -- undecidable from our side, and Willson's
            # and William's clubs meet repeatedly every season. Both
            # same-named board rows refuse here; a fixture holding only one
            # form keeps matching exactly as before (test-pinned both ways).
            # FIXTURE-SCOPED deliberately: a variant in another game says the
            # pair exists, not that OUR fixture's plain rows are ambiguous --
            # and refusing league-wide would cost the plain-owner's
            # legitimate matches every day both are listed. The residual this
            # cannot see is named in `_polymarket_player_token`'s docstring.
            _alt43 = _polymarket_token_alt43(board_row.get("player_name"))
            _collision_token = None
            for c in candidates:
                cand_prop = c.get("prop")
                if not isinstance(cand_prop, Mapping):
                    continue
                _ct = str(cand_prop.get("token") or "")
                if not _ct or _ct == prop_token:
                    continue
                _digit_ext = (
                    _ct.startswith(prop_token)
                    and _ct[len(prop_token):].isdigit()
                    and len(_ct) - len(prop_token) <= 2
                )
                if not _digit_ext and _ct != _alt43:
                    continue
                if not _teams_match(
                    board_row, c["parsed"], board_row.get("sport") or sport,
                    board_fixtures.get((league, date)),
                ):
                    continue
                _collision_token = _ct
                break
            if _collision_token is not None:
                refuse("prop_same_name_collision_at_venue")
                continue
            probability = _prop_probability_for_side(side, picked)
        else:
            probability = _probability_for_side(side, picked, board_row.get("sport") or sport, board_row)
        if probability is None:
            # The measured failure of the game-line join, kept as its own
            # counter: the market matched but we cannot place the SIDE.
            #
            # WHAT THE VENUE ACTUALLY OFFERED, because the count alone cannot
            # be acted on. This counter went 30 -> 93 on 2026-08-29T17:49:25Z
            # the moment the corners line fix let 454 corners rungs reach this
            # line: they pair the fixture AND the rung, then fail here. The
            # loss moved downstream rather than closing.
            #
            # THE OBVIOUS READING IS THAT CORNERS ARE `["Yes","No"]` while the
            # board asks `over`/`under`, and mapping over->Yes would close it.
            # THAT IS NOT SHIPPED, DELIBERATELY: if the polarity is reversed --
            # if `Yes` is the UNDER -- the map prices the opposite side of a
            # real bet at a confident-looking number. This file already refuses
            # a positional pick in `_probability_for_side` and `_side_for_team`
            # for exactly that reason, and a wrong-side fill is the single most
            # expensive mistake available here ($7.08 in MLB, 2026-08-28).
            #
            # So this samples the OUTCOME NAMES beside the wanted side and the
            # slug. One reading names the polarity from data instead of from
            # the shape of the words, and then the map is safe to write.
            if len(side_gap_samples) < 8:
                _sg_key = f"{board_market}|{side}"
                if not any(g.get("key") == _sg_key for g in side_gap_samples):
                    side_gap_samples.append({
                        "key": _sg_key,
                        "wanted_side": str(side),
                        "board_line": board_line,
                        "slug": str((picked.get("row") or {}).get("slug") or "")[:56],
                        # The names AND their prices: polarity is readable from
                        # the price when the board's own line is known.
                        "outcomes": [
                            (str(n)[:14], p) for n, p in (picked.get("outcomes") or [])
                        ][:4],
                    })
            refuse("side_not_an_outcome_of_this_market")
            continue

        alignment_verdict = _classify_alignment(
            board_row, probability, f"{league}|{board_market}",
            alignment_counts, alignment_samples,
        )
        if alignment_verdict == "inverted":
            # THE PRICE WE WOULD PAY BELONGS TO THE OTHER OUTCOME. Refuse.
            #
            # REFUSES, DOES NOT FLIP. Taking `1 - p` would assume the complement
            # is the right price, which is a SECOND guess on top of the one that
            # produced this -- and if the real cause is something other than a
            # swap, flipping prices a bet on a number the venue never quoted.
            # A refusal costs the bet; a flip can pay the wrong side twice.
            #
            # THE GATE IS THE BOARD'S OWN FAIR VALUE, per row, and only on
            # markets lopsided enough for `fair` and `1 - fair` to be told apart
            # (>= 0.20). A `too_close` row is NOT refused: the test cannot
            # separate the hypotheses there, and refusing on an unreadable
            # signal would silently drop half the slate.
            refuse("venue_price_inverted_vs_book")
            continue

        # LADDER POINT, for the monotonicity check after the loop. Keyed on the
        # BOARD's own fixture id so two clubs cannot be conflated across dates.
        _lkey = (
            str(board_row.get("event_id") or ""),
            # THE PLAYER IS PART OF A PROP LADDER'S IDENTITY. Without the
            # token, Tatis's hits rungs and Machado's sort into ONE ladder and
            # the monotonicity check compares prices that share no market --
            # condemning ladders that are individually clean. The standing
            # rule (learnings 2026-08-27): a join key for a player prop that
            # omits the player is a defect that looks like a working join.
            f"{board_market}|{prop_token}" if is_prop else board_market,
            str(side or "").strip().lower(),
        )
        if _lkey[0] and board_line is not None and _lkey[2] in {"over", "under"}:
            ladder_points.setdefault(_lkey, []).append(
                (float(board_line), float(probability), len(matches))
            )

        from syndicate.features.shared.venue_quote_adapters import probability_to_american

        matches.append({
            # THE GAME. Carried because the resolvers below key on it -- see
            # `_resolver_key`. Without it a match is `(market, player, line,
            # side)`, which is not an identity on a game line: every MLB h2h
            # home row in a slate collapses to one key.
            "event_id": board_row.get("event_id"),
            # Diagnostics only, never keyed on: `event_id` is exact and these
            # would need aliasing. They are here so a wrong-game slug is
            # READABLE in the artifact rather than needing a second join to spot.
            "home_team": board_row.get("home_team"),
            "away_team": board_row.get("away_team"),
            "market": board_market,
            "side": side,
            "line": board_line,
            "player_name": board_row.get("player_name"),
            "polymarket_slug": str(picked["row"].get("slug") or ""),
            "polymarket_probability": probability,
            "polymarket_american": probability_to_american(probability),
            "tick_size": picked["row"].get("orderPriceMinTickSize"),
            "minimum_trade_qty": picked["row"].get("minimumTradeQty"),
        })

    # ----------------------------------------------------------------------
    # LADDER MONOTONICITY -- the one check that works where the fair-value
    # alignment gate is BLIND.
    # ----------------------------------------------------------------------
    #
    # On ONE fixture, P(over) must not RISE as the line rises: over 3.5 goals
    # cannot be likelier than over 2.5 in the same match. P(under) must not
    # FALL. That is arithmetic, not a model opinion, so it needs no fair value
    # and no reference book -- which is exactly why it can see what
    # `_classify_alignment` cannot.
    #
    # WHY IT WAS BUILT, measured 2026-08-29:
    #
    #     soccer|totals|over   7      mlb|totals|under  4
    #     soccer|totals|under  1      mlb|totals|over   2
    #
    # Soccer totals ran 7:1 OVER while MLB stayed balanced, on a day down
    # $42.80. The alignment gate votes only when the book is lopsided by >=0.20
    # from a coin flip, and a 2.5-goal total sits ON the coin flip: every soccer
    # total classified `too_close`, zero aligned, zero inverted. A systematic
    # side error had nowhere to show up.
    #
    # A VIOLATION CONDEMNS THE WHOLE LADDER, not the rung that trips it. If two
    # rungs of one fixture contradict each other, the pairing that produced them
    # is not trustworthy at ANY rung, and picking which of the two is "right"
    # would be the same guess this file refuses everywhere else. So every match
    # on that fixture/market/side is dropped.
    ladder_counts: dict[str, int] = {}
    ladder_samples: list[dict[str, Any]] = []
    drop_indices: set[int] = set()
    for (event_id, market_name, side_name), points in ladder_points.items():
        if len({round(line, 6) for line, _p, _i in points}) < 2:
            continue
        ordered = sorted(points, key=lambda t: t[0])
        # `over` must be non-increasing in the line; `under` non-decreasing.
        worst = 0.0
        for (l_a, p_a, _ia), (l_b, p_b, _ib) in zip(ordered, ordered[1:]):
            delta = (p_b - p_a) if side_name == "over" else (p_a - p_b)
            if delta > worst:
                worst = delta
        # The COUNT aggregates per market -- a prop ladder key carries its
        # player token (`batter_hits|jacmer`), and per-player count keys would
        # turn this summary into a roster. The LADDER key keeps the token; the
        # counter drops it.
        league_key = f"{market_name.split('|')[0]}|{side_name}"
        # A tolerance, because two rungs quoted a tick apart are noise rather
        # than a contradiction. Anything above it is an ORDERING error.
        if worst > 0.02:
            ladder_counts[f"{league_key}|non_monotonic"] = (
                ladder_counts.get(f"{league_key}|non_monotonic", 0) + 1
            )
            drop_indices.update(i for _l, _p, i in points)
            if len(ladder_samples) < 6:
                ladder_samples.append({
                    "event_id": event_id[:12],
                    "market": market_name,
                    "side": side_name,
                    "worst_rise": round(worst, 4),
                    "ladder": [(l, round(p, 4)) for l, p, _i in ordered][:6],
                })
        else:
            ladder_counts[f"{league_key}|monotonic"] = (
                ladder_counts.get(f"{league_key}|monotonic", 0) + 1
            )
    if drop_indices:
        for idx in drop_indices:
            refuse("ladder_not_monotonic")
        matches = [m for i, m in enumerate(matches) if i not in drop_indices]

    return {
        "matched": len(matches),
        "matches": matches,
        "board_rows": len(board_rows),
        "polymarket_markets": len(markets),
        "indexed": sum(len(v) for v in index.values()),
        "refusals": refusals,
        "unreadable_shapes": shapes,
        # What we FETCH and discard, by (venue type, league). Complete counts
        # plus one sampled row each, so "out of scope" is a decision that can
        # be revisited from data rather than a standing assumption.
        "out_of_scope_counts": dict(
            sorted(out_of_scope_counts.items(), key=lambda kv: -kv[1])
        ),
        "out_of_scope_samples": out_of_scope_samples,
        # Board rows the venue could not be paired with, both sides shown.
        "unmatched_counts": dict(
            sorted(unmatched_counts.items(), key=lambda kv: -kv[1])
        ),
        "unmatched_samples": unmatched_samples,
        # The COMPLETE prop no-match classification (`<class>|<family>` ->
        # count). Per family these sum exactly to `no_match|mlb|<family>`
        # above, so class/family IS a rate, not a sampled reading.
        "prop_unmatched_classes": dict(
            sorted(prop_unmatched_classes.items(), key=lambda kv: -kv[1])
        ),
        # One per board market that found an empty bucket, with the
        # neighbouring index keys that say WHICH component disagreed.
        "key_miss_samples": key_miss_samples,
        # WHERE EACH MARKET'S LINE CAME FROM. `|row_field` non-zero proves the
        # fallback fires; `|none` with a slug sample names the format that
        # carries no number at all; `|DISAGREE` is the one that would matter.
        "line_source": dict(sorted(line_source.items(), key=lambda kv: -kv[1])),
        "line_gap_samples": line_gap_samples,
        # WHY A MATCHED MARKET COULD NOT PLACE THE SIDE -- outcome names and
        # prices beside the side we wanted. Names the polarity from data.
        "side_gap_samples": side_gap_samples,
        # P(over) must not rise with the line on one fixture. Works where the
        # fair-value gate is blind, which is precisely soccer totals.
        "ladder_counts": dict(sorted(ladder_counts.items(), key=lambda kv: -kv[1])),
        "ladder_samples": ladder_samples,
        # HOW MANY BOARD ROWS ONLY FOUND CANDIDATES BY LOOKING FORWARD. This is
        # the reachability reading for the slate/fixture date split: zero with
        # soccer still refusing means the diagnosis was wrong, and a non-zero
        # count that does NOT reduce `no_candidates|soccer|*` means the rows
        # were found and then lost further down.
        "forward_date_widened": dict(
            sorted(forward_date_widened.items(), key=lambda kv: -kv[1])
        ),
        # What soccer PROP markets Polymarket actually publishes, by
        # slug-modifier shape. `btts` was found this way; corners has
        # not been found at all yet.
        "prop_modifier_census": dict(
            sorted(prop_modifier_census.items(), key=lambda kv: -kv[1])
        ),
        # Rows that refused on fixture pairing but WOULD pair with the
        # slug's two sides swapped. Per sport deliberately: MLB and NFL
        # pair correctly today and act as the control.
        "orientation_flip_counts": dict(
            sorted(orientation_flip_counts.items(), key=lambda kv: -kv[1])
        ),
        "orientation_flip_attempts": dict(
            sorted(orientation_flip_attempts.items(), key=lambda kv: -kv[1])
        ),
        # THE INVARIANT, CARRIED IN THE PAYLOAD. `flipped <= listed` per key,
        # because a flip-match proves the fixture is listed. Violated on the
        # counter's first production run (`flipped 9 > listed 4`, 18:55:16Z),
        # which is how the classifier's defect was found. Reported rather than
        # asserted: a diagnostic must never take down a board build, and a
        # `False` here on the same log line is as loud as a traceback and does
        # not cost a slate.
        # `#595` step 2. `<league>|<market>|aligned|inverted|too_close` --
        # whether the venue price we assign to a side tracks the BOOKS'
        # independent no-vig probability for that same side, or its complement.
        "price_alignment": dict(sorted(alignment_counts.items())),
        "price_alignment_samples": alignment_samples,
        "orientation_invariant_ok": all(
            orientation_listed.get(k, 0) >= v for k, v in orientation_flip_counts.items()
        ),
        "orientation_fixture_listed": dict(
            sorted(orientation_listed.items(), key=lambda kv: -kv[1])
        ),
        # THE NON-CIRCULAR DENOMINATOR. `flipped / listed` can be 1.0 by
        # construction when every listing was established BY the flip;
        # `flipped / listed_by_canonical` cannot.
        "orientation_listed_by_canonical": dict(
            sorted(orientation_listed_by_canonical.items(), key=lambda kv: -kv[1])
        ),
        "orientation_listed_by_flip_only": dict(
            sorted(orientation_listed_by_flip_only.items(), key=lambda kv: -kv[1])
        ),
        "orientation_fixture_not_listed": dict(
            sorted(orientation_not_listed.items(), key=lambda kv: -kv[1])
        ),
        "orientation_fixture_unreadable": dict(
            sorted(orientation_unreadable.items(), key=lambda kv: -kv[1])
        ),
        "orientation_flip_samples": orientation_flip_samples,
        # Competitions no board row can reach, with the club codes that would
        # settle each one. Sorted so the list is stable across builds.
        "soccer_tokens_proven": sorted(soccer_tokens),
        "unproven_league_tokens": {
            token: sorted(codes)
            for token, codes in sorted(unproven_league_tokens.items())
        },
    }


# POLYMARKET'S OWN CLUB TRI-CODES, KEYED BY COMPETITION.
#
# --------------------------------------------------------------------------
# EVERY ENTRY IS PROVEN BY A NAMED FIXTURE. NONE ARE GUESSED.
# --------------------------------------------------------------------------
#
# `_soccer_alias_to_name` is DERIVED from the team artifacts and deliberately
# drops a token that names two clubs. That is correct and must stay -- but it
# leaves Polymarket's vocabulary unreachable, because its tri-codes are its own
# and are not ESPN's abbreviations. MEASURED 2026-08-28: of 17 codes seen on
# the live slate, 13 resolve through neither the flat nor the per-league map.
#
# The consequence was not a missing club, it was a missing MEASUREMENT: with
# these unresolved, `POLYMARKET_ORIENTATION` could classify only 5 of 71
# unmatched soccer rows, and `not_listed` came back EMPTY -- we could not prove
# a single fixture absent because we could not read the candidates.
#
# EACH ROW BELOW WAS READ OFF ESPN'S OWN SCOREBOARD for that competition and
# date, using the slug's home-first ordering (itself established against ESPN
# the same day). The fixture is recorded beside the code so the evidence
# travels with the claim, exactly as `_SOCCER_VENDOR_NAME_ALIASES` does.
#
# --------------------------------------------------------------------------
# KEYED BY (COMPETITION, CODE) AND NOT BY CODE ALONE -- THIS IS LOAD-BEARING
# --------------------------------------------------------------------------
#
# A flat table would reintroduce the exact bug the derived map avoids:
#
#   `mil`  serie_a -> AC Milan, championship -> Millwall   (both in OUR maps)
#   `fcb`  Bayern in `bun`; Barcelona is the other claimant, and this module's
#          own history records `fcb` as the canonical ambiguous token
#
# Evidence for `mil` and `fcb` covers ONE competition each, so the entry is
# scoped to that competition and says nothing about any other. A code seen in a
# competition not listed here resolves to nothing and the row stays counted as
# unreadable, which is the honest outcome.
_VENUE_TRI_CODES: dict[tuple[str, str], str] = {
    ("ligpor", "bra"): "Braga",          # atc-ligpor-bra-gil-2026-08-16  Gil Vicente @ Braga
    ("ligpor", "rav"): "Rio Ave",        # atc-ligpor-rav-spo-2026-08-28  Sporting CP @ Rio Ave
    ("ligpor", "spo"): "Sporting CP",    # atc-ligpor-rav-spo-2026-08-28  Sporting CP @ Rio Ave
    ("bun", "fcb"): "Bayern Munich",     # asc-bun-fcb-stu-2026-08-28     VfB Stuttgart @ Bayern Munich
    ("bun", "stu"): "VfB Stuttgart",     # asc-bun-fcb-stu-2026-08-28     VfB Stuttgart @ Bayern Munich
    ("sea", "mil"): "AC Milan",          # asc-sea-mil-ven-2026-08-28     Venezia @ AC Milan
    ("eflch", "wre"): "Wrexham",         # atc-eflch-wre-bir-2026-08-28   Birmingham City @ Wrexham
}


def _club_token_names(token: Any, club: Any) -> bool:
    """Does `token` prefix this club's name, or one of its words?

    Conservative on purpose -- see the call site. `ala`/"Alaves" and
    `hof`/"1899 Hoffenheim" match; `mnc`/"Manchester City" does not.
    """
    tok = "".join(ch for ch in str(token or "").lower() if ch.isalnum())
    if len(tok) < 2:
        return False
    raw = str(club or "")
    try:
        from syndicate.features.shared.team_aliases import fold_accents
        raw = fold_accents(raw) or raw
    except Exception:  # noqa: BLE001
        pass
    low = raw.lower()
    flat = "".join(ch for ch in low if ch.isalnum())
    if flat.startswith(tok):
        return True
    if any(
        "".join(ch for ch in word if ch.isalnum()).startswith(tok)
        for word in low.split()
        if word
    ):
        return True
    # INITIALS, which is the OTHER shape the venue actually uses and is not
    # fuzzy: `psg`->Paris Saint Germain, `whu`->West Ham United,
    # `rrc`->Real Racing Club de Santander. Taken as a PREFIX of the word
    # initials so a trailing "de Santander" does not defeat it.
    #
    # Still refuses `mnc`->Manchester City ("mc"), which is neither a prefix
    # nor initials. That stays refused rather than reached for with a looser
    # rule: `mnc` would subsequence-match Manchester UNITED too, and a club
    # match that can name the wrong team is worth less than no match.
    initials = "".join(w[0] for w in low.split() if w and w[0].isalnum())
    return len(tok) >= 2 and initials.startswith(tok)


def _fixture_tokens_name_matchup(
    token_a: Any, token_b: Any, board_home: Any, board_away: Any
) -> bool:
    """Do the slug's two tokens name this board fixture, in EITHER order?

    Both clubs must be named and the two tokens must name DIFFERENT clubs --
    otherwise one token matching both sides of a fixture would pair anything.
    """
    if not (board_home and board_away):
        return False
    a_home, a_away = _club_token_names(token_a, board_home), _club_token_names(token_a, board_away)
    b_home, b_away = _club_token_names(token_b, board_home), _club_token_names(token_b, board_away)
    return bool((a_home and b_away and not a_away) or (a_away and b_home and not a_home))


def _slug_is_home_first(parsed: Mapping[str, Any], sport: Any) -> bool:
    """Does this competition list the HOME club first in its slug?

    SOCCER ONLY, and stated as a per-sport fact rather than a global rule
    because the two known answers DIFFER: soccer is home-first (three ESPN
    fixtures, two sessions), MLB is away-first and pairs correctly today. A
    single global ordering would be wrong for one of them whichever way it was
    written.

    Keyed on the SPORT rather than the competition token because the evidence
    spans five competitions (`epl`, `lg1`, `lal`, `eflch`, `mlp`) and both slug
    prefixes with no counterexample -- narrowing it per competition would
    refuse the ones nobody has checked yet, for no measured reason. A
    competition that turns out to differ shows up as a soccer row matching
    NORMALLY, which is the falsifier named at the call site.
    """
    return str(sport or "").strip().lower() == "soccer"


def _venue_canonical_fixture(parsed: Mapping[str, Any]) -> frozenset[str] | None:
    """The fixture as an unordered canonical pair, via the venue tri-codes.

    The eligibility classifier's fallback. Without it a fixture Polymarket
    names in its own vocabulary stays `unreadable` even once we can read it,
    and the denominator never improves.
    """
    a = _venue_club(parsed, (parsed or {}).get("home"))
    b = _venue_club(parsed, (parsed or {}).get("away"))
    if not a or not b or a == b:
        return None
    return frozenset((a, b))


def _venue_club(parsed: Mapping[str, Any], token: Any) -> str | None:
    """Polymarket's tri-code -> a canonical club, scoped to its competition.

    Returns the CANONICAL name (through `canonical_team`) so this cannot become
    a second vocabulary alongside the alias map -- the failure this repo keeps
    paying for is two resolvers disagreeing, not one resolver missing a key.
    """
    league = str((parsed or {}).get("league") or "").strip().lower()
    name = _VENUE_TRI_CODES.get((league, str(token or "").strip().lower()))
    if not name:
        return None
    try:
        from syndicate.features.shared.team_aliases import canonical_team
    except Exception:  # noqa: BLE001
        return None
    return canonical_team("soccer", name)


def _teams_match(
    board_row: Mapping[str, Any],
    parsed: Mapping[str, Any],
    sport: Any,
    fixtures: Sequence[tuple[str, str]] | None = None,
) -> bool:
    """Both clubs, or no match.

    THROUGH `team_aliases`, NOT STRING CONTAINMENT. The venue writes
    abbreviations -- `sd`, `lac`, `nyg`, `jax` -- and "sd" is not a substring of
    "sandiegopadres". A containment test silently matched nothing here, which is
    the failure mode this repo keeps paying for: a join that returns zero and
    looks like "the venue does not quote this".

    It is also the same resolver `_side_for_team` uses, so the two halves of a
    join can never end up on different vocabularies.

    Matching on ONE club would pair a row with that team's OTHER fixture -- a
    real risk on a doubleheader, which is exactly the case `#117` found stale by
    21.7 hours.
    """
    try:
        from syndicate.features.shared.team_aliases import teams_match as alias_match
    except Exception:
        return False

    home = board_row.get("home") or board_row.get("home_team")
    away = board_row.get("away") or board_row.get("away_team")
    if not home or not away:
        return False
    if alias_match(sport, parsed.get("home"), home) and alias_match(
        sport, parsed.get("away"), away
    ):
        return True

    # FALLBACK: RESOLVE THE FIXTURE AS A PAIR. Soccer only, and only after the
    # normal path has already failed, so this can add matches and never remove
    # one.
    #
    # MEASURED 2026-08-27, after the competition fold made the venue's soccer
    # markets reachable: 119 h2h rows still refused as `no_match`, because
    # `team_aliases` drops club tokens that name two clubs ACROSS leagues --
    # `fcb` is Bayern and Barcelona, `stl` is Standard Liege and St. Louis. The
    # drop is correct and must stay: a confidently wrong club is a real bet on
    # the wrong team.
    #
    # Asked as a PAIR the ambiguity mostly disappears, because only one league
    # contains both clubs of a real fixture. On 295 sampled venue fixtures the
    # global map resolved 50 and the pair resolved 93 -- 43 rescued that were
    # previously unjoinable.
    #
    # STRICTER, NOT LOOSER: `soccer_fixture_clubs` requires both codes to
    # resolve inside ONE league and exactly one league to qualify, so an
    # unresolvable pair still refuses rather than guessing.
    if str(sport or "").strip().lower() != "soccer":
        return False

    # BEFORE THE CANONICALISATION GUARD BELOW, DELIBERATELY.
    #
    # This path compares the slug's tokens against the board's RAW club names
    # and never calls `canonical_team`, so gating it behind that resolver would
    # refuse exactly the population it exists to serve: fixtures our alias map
    # cannot name. Measured tonight, that is 76 of 80 unmatched `soccer|h2h`
    # rows. Placing it after the guard made it unreachable for all of them --
    # a fix that only helps the rows that were never broken.
    if str(sport or "").strip().lower() == "soccer":
        # ------------------------------------------------------------------
        # THE PAIR RESOLVER IS AUTHORITATIVE, AND IT RUNS FIRST.
        # ------------------------------------------------------------------
        #
        # `soccer_fixture_clubs` requires BOTH slug codes to resolve inside the
        # SAME league and exactly ONE league to satisfy that. When it answers,
        # it has named the COMPETITION as well as the clubs -- which is the
        # check this function could not otherwise make, because the board stamps
        # every soccer row `sport="soccer"` and never carries its league here.
        #
        # WHY IT IS A REFUSAL AND NOT JUST A MATCH. The wrong-game bet of
        # 2026-08-29 (filled $5.20: board `Nice @ Paris FC`, Ligue 1, placed
        # against `tsc-sea-juv-par`, Serie A) happened because ELIMINATION ran
        # and this did not. The resolver knew the answer the whole time:
        #
        #     soccer_fixture_clubs('juv','par') -> ('juventus', 'parma')
        #
        # Juventus and Parma, unambiguously, in Serie A. Nothing consulted it,
        # so a club-token prefix collision (`par` prefixes both "Paris FC" and
        # "Parma") was allowed to decide the fixture instead.
        #
        # So: if the resolver names the pair and it is NOT this board row's
        # fixture, refuse outright. No later rule may rescue it -- that is the
        # whole point of putting it first.
        #
        # COMPARED AS AN UNORDERED PAIR, because slug order and board order are
        # a separate question this function has its own handling for; a
        # wrong-GAME check must not be entangled with a wrong-SIDE one.
        #
        # AND IT RESTORES THE `mnc` FAMILY the first fix traded away:
        # `soccer_fixture_clubs('cry','mnc')` resolves to
        # ('crystal palace', 'manchester city'), so that pair now matches HERE
        # rather than needing elimination to carry a token naming nothing.
        try:
            from syndicate.features.shared.team_aliases import (
                canonical_team as _canon,
                soccer_fixture_clubs as _pair,
            )
            resolved = _pair(parsed.get("home"), parsed.get("away"))
        except Exception:  # noqa: BLE001 -- a dark resolver must not decide
            resolved = None
        if resolved:
            try:
                board_pair = {
                    _norm(_canon("soccer", home) or home),
                    _norm(_canon("soccer", away) or away),
                }
            except Exception:  # noqa: BLE001
                board_pair = None
            slug_pair = {_norm(resolved[0]), _norm(resolved[1])}
            if board_pair:
                # A named pair that is not this fixture is a DIFFERENT GAME.
                return board_pair == slug_pair
        if _fixture_tokens_name_matchup(
            parsed.get("home"), parsed.get("away"), home, away
        ):
            return True
        # ELIMINATION ACROSS THE LEAGUE'S MATCHUPS FOR THAT DATE.
        #
        # A token that names exactly ONE fixture in the slate determines the
        # other club even when the other token names nothing. That is how
        # `mnc` (neither a prefix nor initials of "Manchester City") gets
        # resolved: `cry` names Crystal Palace and no other fixture that day,
        # so the slug is that fixture and `mnc` is its opponent.
        #
        # THE GUARD IS "EXACTLY ONE". If the token names two fixtures it
        # discriminates nothing and this refuses -- the same rule as
        # `_soccer_alias_to_name` dropping a code that names two clubs, and the
        # reason a bare token cannot pair a row on its own.
        if fixtures:
            for token, other in (
                (parsed.get("home"), parsed.get("away")),
                (parsed.get("away"), parsed.get("home")),
            ):
                named = [
                    (fh, fa) for fh, fa in fixtures
                    if _club_token_names(token, fh) or _club_token_names(token, fa)
                ]
                if len(named) == 1 and (str(named[0][0]), str(named[0][1])) == (str(home), str(away)):
                    # THE OTHER TOKEN MUST POSITIVELY NAME THE OTHER SIDE.
                    #
                    # This used to accept `not (hit_h or hit_a)` -- an opponent
                    # token that names NOTHING was read as "does not contradict".
                    # That is `unknown defaulting permissive`, and it placed a
                    # REAL BET ON THE WRONG GAME.
                    #
                    # MEASURED 2026-08-29, user-reported, order filled $5.20:
                    #
                    #   board row   Nice @ Paris FC          (Ligue 1)
                    #   slug        tsc-sea-juv-par-...-2pt5 (Serie A, Juventus-Parma)
                    #   ledger      "totals over 2.5 · Nice @ Paris FC"
                    #   Polymarket  "Over 2.5 total goals — Juventus FC vs Parma"
                    #
                    # `par` is a prefix of BOTH "Paris FC" and "Parma", so it
                    # named exactly one fixture on OUR board and looked
                    # decisive. `juv` then matched neither Nice nor Paris FC --
                    # and naming nothing was treated as consent. Two clubs, two
                    # competitions, one bet on the wrong match.
                    #
                    # THE COST OF THE FIX IS THE `mnc` CASE the note above
                    # describes: a slug whose second token resolves to nothing
                    # no longer pairs by elimination alone. That is coverage,
                    # and coverage is the cheaper thing to lose. A wrong-game
                    # fill cannot be unwound.
                    fh, fa = named[0]
                    hit_h, hit_a = _club_token_names(other, fh), _club_token_names(other, fa)
                    if (_club_token_names(token, fh) and hit_a) or (
                        _club_token_names(token, fa) and hit_h
                    ):
                        return True


    try:
        from syndicate.features.shared.team_aliases import (
            canonical_team,
            soccer_fixture_clubs,
        )
    except Exception:
        return False
    board_home = canonical_team("soccer", home)
    board_away = canonical_team("soccer", away)
    if not board_home or not board_away:
        return False

    # POLYMARKET'S OWN TRI-CODES, tried before the pair resolver. Additive and
    # last-resort: reached only after `alias_match` has already declined both
    # clubs, so it can add a pairing and can never remove one. Scoped to the
    # slug's competition -- see `_VENUE_TRI_CODES` for why a flat table would
    # be wrong.
    venue_home = _venue_club(parsed, parsed.get("home"))
    venue_away = _venue_club(parsed, parsed.get("away"))
    if venue_home and venue_away:
        return bool(venue_home == board_home and venue_away == board_away)

    # ----------------------------------------------------------------------
    # IDENTIFY THE FIXTURE FROM THE BOARD'S OWN MATCHUP, NOT FROM AN ALIAS
    # ----------------------------------------------------------------------
    #
    # The alias route does not scale and the numbers say so: seven tri-codes
    # verified one fixture at a time against ESPN moved `unreadable` for
    # `soccer|h2h` from 80 to 76. Polymarket's club vocabulary is its own and
    # there are hundreds of codes across ten competitions.
    #
    # But the pairing question never needed the vocabulary. The board row
    # ALREADY NAMES THE FIXTURE -- `home_team` and `away_team` -- and the index
    # has already narrowed candidates to the same `(league, date, market)`. So
    # the only question left is whether this slug's two tokens are consistent
    # with THIS matchup, and that can be answered against the board's own club
    # names with no alias map at all.
    #
    # ORDER-INDEPENDENT, WHICH SUBSUMES THE ORIENTATION QUESTION ENTIRELY.
    # Soccer slugs are home-first and MLB's are away-first (both measured
    # against ESPN, 2026-08-28), and a matcher that compares the two clubs as
    # an unordered pair does not care. That is strictly better than swapping
    # per sport: it needs no per-competition ordering rule and cannot be wrong
    # about one. The board row supplies home/away afterwards, and it is
    # correct -- verified on three ESPN fixtures.
    #
    # PREFIX MATCHING ONLY, DELIBERATELY CONSERVATIVE. A token counts as naming
    # a club when it prefixes the club's normalised name or one of its words.
    # `ala`->Alaves, `vil`->Villarreal, `juv`->Juventus, `hof`->Hoffenheim all
    # resolve; `mnc`->Manchester City does NOT and is refused. Subsequence or
    # initials matching would catch `mnc` and would also let `mnc` name
    # Manchester United -- a fuzzy club match is how a bet reaches the wrong
    # team, which is the one outcome this module refuses everywhere else.
    # Recovering fewer fixtures correctly beats recovering more on a guess.
    #
    # BOTH CLUBS MUST MATCH, and ambiguity is already refused one level up:
    # `join_polymarket_to_board` counts `ambiguous_polymarket_match` when a
    # board row is claimed by two candidates rather than resolving by order.
    pair = soccer_fixture_clubs(parsed.get("home"), parsed.get("away"))
    if not pair:
        return False
    return bool(pair[0] == board_home and pair[1] == board_away)


def _probability_for_side(
    side: str,
    candidate: Mapping[str, Any],
    sport: Any,
    board_row: Mapping[str, Any] | None = None,
) -> float | None:
    """Which outcome is this board side? None if we cannot tell.

    None is the important return, for the same reason `_side_for_team`'s is:
    assigning a side positionally is a bet on the wrong team half the time, at
    a price that looks confident.

    Over/Under name themselves; team outcomes go through `team_aliases` for the
    same reason `_teams_match` does -- the venue writes "Padres" where the board
    writes "San Diego Padres", and on some rows an abbreviation.
    """
    wanted = str(side or "").strip()
    if not wanted:
        return None

    # A YES/NO CONTRACT PRICES ITS SUBJECT, NOT A NAMED TEAM.
    #
    # Polymarket splits a soccer 3-way into three binaries whose outcomes are
    # literally `["Yes","No"]`, so neither the literal compare nor `teams_match`
    # below can ever place a board side on them -- "Liverpool" is not "Yes".
    # That was `side_not_an_outcome_of_this_market`.
    #
    # THE SUBJECT IS RE-VERIFIED HERE rather than trusted from the candidate
    # filter. This function's whole contract is "None if we cannot tell", and a
    # helper that returns the Yes price on the strength of a check made
    # somewhere else would hand a confident price to any future caller that
    # skipped it -- the inert-route failure this lane has now hit four times.
    if str(side or "").strip().lower() in _ROLE_SIDES and _is_yes_no_market(
        candidate.get("outcomes")
    ):
        if not _subject_is_side(candidate, board_row or {}, side, sport):
            return None
        for name, probability in candidate.get("outcomes") or ():
            if _norm(name) == "yes":
                return probability
        return None

    # A ROLE IS NOT AN OUTCOME NAME. The board keys a moneyline side as
    # `home`/`away`; this venue names the CLUB. Neither the literal compare nor
    # `teams_match` below can bridge that -- "home" is not a club and resolves
    # to nothing -- so every game-line row refused `side_not_an_outcome_of_this
    # _market` once the date fix let them reach this function at all
    # (measured 2026-08-25, the refusal that replaced
    # `no_polymarket_market_for_league_date_market`).
    #
    # Translate the role into the row's OWN team first, then fall through to
    # the existing name matching. Same fix as `venue_quote_adapters`
    # `_polymarket_sides` -- the board and this venue describe a side two
    # different ways and exactly one place should reconcile them per consumer.
    #
    # Refuses rather than guessing when the row does not name that team: an
    # unresolvable role must not fall through to a positional pick.
    if wanted.lower() in {"home", "away"}:
        team = (board_row or {}).get(f"{wanted.lower()}_team")
        if not str(team or "").strip():
            return None
        wanted = str(team).strip()

    outcomes = candidate.get("outcomes") or []

    # A `gt<line>` YES/NO CONTRACT PRICES "OVER", AND SAYS SO IN THE SLUG.
    #
    # MEASURED 2026-08-29T18:33:49Z via `side_gap_samples`, which exists because
    # guessing this polarity is the one mistake here that costs money rather
    # than coverage:
    #
    #   astatc-mls-sdg-lag-2026-08-29-cor-all-gt10pt5  board over 10.5
    #                                                  Yes 0.41  No 0.67
    #   astatc-sea-juv-par-2026-08-29-cor-all-gt7pt5   board under 7.5
    #                                                  Yes 0.76  No 0.26
    #
    # TWO INDEPENDENT CONFIRMATIONS, which is why this is now safe to write:
    #
    #   1. THE TOKEN. `gt10pt5` is "greater than 10.5". The venue states the
    #      direction in the slug; nothing is being inferred from word order.
    #   2. THE PRICE. `Yes` on the 7.5 line is 0.76. Over 7.5 corners is the
    #      likely side of a ~10-corner match and under would be ~0.24, so `Yes`
    #      tracks OVER at a magnitude the reverse reading cannot explain.
    #
    # GATED ON THE `gt` TOKEN, NOT ON "Yes/No + a line". A Yes/No contract with
    # no stated direction gets no map and keeps refusing: the gate IS the
    # evidence, so a family that never carried `gt` can never be silently
    # assigned a polarity it did not declare.
    #
    # AND THE THRESHOLD MUST EQUAL THE BOARD'S LINE. `gt10pt5` against a board
    # row on 9.5 is a different contract, and pricing one as the other is the
    # rung-mismatch this file already refuses everywhere else.
    if str(side or "").strip().lower() in {"over", "under"} and _is_yes_no_market(outcomes):
        threshold = _greater_than_line(candidate.get("parsed") or {})
        board_line = None if board_row is None else _as_float(board_row.get("line"))
        if (
            threshold is not None
            and board_line is not None
            and abs(threshold - board_line) <= 1e-9
        ):
            want_yes = str(side).strip().lower() == "over"
            for name, probability in outcomes:
                if _norm(name) == ("yes" if want_yes else "no"):
                    return probability
            return None

    for name, probability in outcomes:
        if _norm(name) == _norm(wanted):
            return probability

    try:
        from syndicate.features.shared.team_aliases import teams_match as alias_match
    except Exception:
        return None

    hits = [p for name, p in outcomes if alias_match(sport, name, wanted)]
    # UNIQUE or nothing. Two outcomes both resolving to the board side means we
    # cannot tell them apart, and picking one is a coin flip on a real order.
    return hits[0] if len(hits) == 1 else None


def _resolver_key(record: Mapping[str, Any]) -> tuple[str, str, str, float | None, str, str] | None:
    """`(event_id, market, player, line, side, segment)`, or None when not an identity.

    --------------------------------------------------------------------------
    THE GAME IS PART OF THE KEY. IT WAS NOT, AND THAT BOUGHT THE WRONG GAME.
    --------------------------------------------------------------------------

    MEASURED 2026-08-25 14:57:34Z, three attempted purchases:

      board row                                       stamped slug
      totals under 8.5 · Cincinnati Reds @ SF Giants  tsc-mlb-bal-stl-2026-08-25-8pt5
      h2h home · Texas Rangers @ Chicago White Sox    aec-mlb-pit-sd-2026-08-25

    BAL@STL on a CIN@SF row. PIT@SD on a TEX@CWS row. Both resolvers keyed on
    `(market, player_name, line, side)` and a GAME LINE HAS NO PLAYER, so every
    MLB h2h home row in the slate hashed to `("h2h", "", None, "home")` and the
    index kept whichever game was written last. Same for `("totals", "", 8.5,
    "under")`.

    The JOIN was never wrong -- it matches each row through `_teams_match` and
    refuses ambiguity. The defect was entirely in flattening that per-row result
    into a key that no longer said which row it came from. The price resolver's
    own docstring claimed "a lookup cannot be looser than the join"; it was
    looser than the join, and that sentence is why nobody looked.

    **THE ORDER DID NOT GO THROUGH, AND THAT WAS LUCK, NOT DESIGN.** It failed
    at `polymarket_us_orders`' `market_unresolved_for_position` because the
    submit-time resolver was rebuilt from a slate that happened to hold fewer
    matches. Had it held one for that key, the order would have been submitted
    against a different game's contract at a price quoted for that other game.

    `event_id` rather than the team names: it is exact, it is on every published
    board row (`layer2_board.py:1825`), and matching on names here would need an
    alias table -- which is the machinery `build_live_gameline_index` refuses for
    exactly this reason.

    **A ROW WITH NO `event_id` RETURNS None AND IS NEVER INDEXED.** An empty
    string would restore the collision under a different spelling, which is the
    failure mode this function exists to end: not indexed means not resolved
    means no order, and that is the direction that fails safe.
    """
    from syndicate.features.shared.kalshi_board_join import normalize_person
    from syndicate.features.shared.kalshi_catalogue import FULL_GAME_SEGMENT

    event_id = str(record.get("event_id") or "").strip()
    if not event_id:
        return None
    # WHICH PORTION OF THE GAME. Absent means the whole game, which is what a
    # board row without an explicit segment has always meant AND what every
    # match record is -- the venue side of this join refuses a segment market
    # outright (`segment_market_not_full_game`, ~200 lines above), so an indexed
    # Polymarket market is guaranteed full-game. That guarantee is exactly what
    # made the omission here dangerous rather than merely incomplete: a first3
    # row could not match a CORRECT contract, only a wrong one.
    #
    # MEASURED 2026-08-28, real money, four orders: `first3`/`first5` h2h rows
    # resolved to full-game slugs `aec-mlb-lad-det-2026-08-28`,
    # `aec-mlb-tex-mil-2026-08-28`, `aec-mlb-pit-stl-2026-08-28` at +199/+160/
    # +208/+106. Same defect Kalshi had the same day (`#601`); the board's own
    # dedupe key (`layer2_board.py:623`) has always counted `segment` as part of
    # a row's identity and both venue resolvers dropped it.
    segment = str(record.get("segment") or FULL_GAME_SEGMENT).strip().lower()
    return (
        event_id,
        str(record.get("market") or "").strip().lower(),
        normalize_person(record.get("player_name")),
        _as_float(record.get("line")),
        str(record.get("side") or "").strip().lower(),
        segment,
    )


def polymarket_price_resolver(matches: Sequence[Mapping[str, Any]]):
    """Board row -> Polymarket's own American price. Mirrors Kalshi's.

    Keyed by `_resolver_key`, the SAME tuple the ticker resolver uses. Two
    resolvers keyed by two slightly different tuples would pair a row with one
    market's price and another's contract -- a bet placed at a price that was
    never quoted for it, which is the hazard `kalshi_board_join._match_key`
    states and the reason this is one shared function rather than two copies.
    """
    index: dict[tuple[str, str, str, float | None, str, str], float] = {}
    for match in matches:
        price = match.get("polymarket_american")
        key = _resolver_key(match)
        if price is None or key is None:
            continue
        index[key] = float(price)

    def resolve(row: Mapping[str, Any]) -> float | None:
        key = _resolver_key(row)
        return index.get(key) if key else None

    resolve.market_count = len(index)  # type: ignore[attr-defined]
    return resolve


def polymarket_ticker_resolver(matches: Sequence[Mapping[str, Any]]):
    """Board row -> the Polymarket market to BUY, or None.

    Separate from the price resolver rather than folded into its return type,
    for the reason Kalshi's docstring gives: a function returning either a
    float or a dict is one every caller must shape-test, and the caller that
    forgets places an order priced by a dict.
    """
    index: dict[tuple[str, str, str, float | None, str, str], dict[str, Any]] = {}
    for match in matches:
        slug = str(match.get("polymarket_slug") or "")
        key = _resolver_key(match)
        if not slug or key is None:
            continue
        index[key] = {
            "slug": slug,
            # Carried because `order_body` REFUSES to infer them, so a caller
            # that has the ticker also has everything the order needs.
            "tick_size": match.get("tick_size"),
            "minimum_trade_qty": match.get("minimum_trade_qty"),
        }

    def resolve(row: Mapping[str, Any]) -> dict[str, Any] | None:
        key = _resolver_key(row)
        return index.get(key) if key else None

    resolve.market_count = len(index)  # type: ignore[attr-defined]
    return resolve


def _as_float(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
