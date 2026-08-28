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

Game lines only: `h2h`, `spreads`, `totals`. Player props are REAL on this
venue (`astatc-mlb-pit-sd-...-hits-jakman-gte2`) and are refused here rather
than half-matched, because resolving `jakman` to a roster name is a different
problem with its own failure modes, and a prop priced by a guessed player is a
real order on the wrong person. `refusals` counts every drop by reason, so
coverage is diagnosable instead of merely low.
"""

from __future__ import annotations

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
        if not league or league == "soccer" or league in _NON_SOCCER_LEAGUE_TOKENS:
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
        if not league or league == "soccer" or league in _NON_SOCCER_LEAGUE_TOKENS:
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
# prices. Searched 2026-08-28: that is asserted NOWHERE and proven NOWHERE.
#
# It came under suspicion when lane `portfolio-venue-and-side-integrity`
# measured `marketSides[].long` varying across `outcomes[0]`/`[1]`, and found
# one market where `marketSides` priced a club at `outcomePrices[0]` while the
# arrays said `[1]`. **Their separation was ONE CENT (0.51 vs 0.50)** and they
# flagged rather than asserted it, correctly -- a penny cannot carry this.
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
) -> None:
    """Count one matched row as aligned / inverted / too_close. Never decides."""
    quote = board_row.get("quote") if isinstance(board_row.get("quote"), Mapping) else None
    fair = _as_float((quote or {}).get("fair_probability"))
    p = _as_float(venue_probability)
    if fair is None or p is None or not (0.0 < fair < 1.0) or not (0.0 < p < 1.0):
        counts[f"{key}|no_reference"] = counts.get(f"{key}|no_reference", 0) + 1
        return
    if abs(fair - 0.5) < _ALIGN_MIN_EDGE:
        # Too near a coin flip for `fair` and `1 - fair` to be told apart.
        counts[f"{key}|too_close"] = counts.get(f"{key}|too_close", 0) + 1
        return
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


def _has_segment(modifiers: Sequence[str]) -> bool:
    """A period/quarter/half qualifier. `1q`, `2h`, `1p`, `f5`.

    Segment markets are refused: the board's `totals` means the FULL GAME, and
    pricing it from a first-quarter market is a different bet at a confident
    -looking number.
    """
    return any(re.fullmatch(r"(?:[1-4](?:q|h|p)|f[357])", str(m).lower()) for m in modifiers or [])


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

    def _note_unmatched(
        kind: str,
        board_row: Mapping[str, Any],
        board_market: str,
        league: str,
        date: str,
        candidates: Sequence[Mapping[str, Any]],
    ) -> None:
        key = f"{kind}|{league}|{board_market}"
        unmatched_counts[key] = unmatched_counts.get(key, 0) + 1
        if key in unmatched_seen or len(unmatched_samples) >= 10:
            return
        unmatched_seen.add(key)
        unmatched_samples.append({
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
        })

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
    # `#595` step 2: does the price we ASSIGN to a side actually belong to it?
    alignment_counts: dict[str, int] = {}
    alignment_samples: list[dict[str, Any]] = []
    orientation_flip_samples: list[dict[str, Any]] = []

    for row in markets:
        parsed = parse_slug(row.get("slug"))
        if parsed is None:
            refuse("slug_unparseable")
            continue
        venue_type = str(row.get("sportsMarketTypeV2") or "").upper()
        board_market = MARKET_TYPE_TO_BOARD.get(venue_type)
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
             "line": _line_from_modifiers(parsed["modifiers"]),
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

    matches: list[dict[str, Any]] = []
    for board_row in board_rows:
        board_market = str(board_row.get("market") or "").strip().lower()
        if board_market not in set(MARKET_TYPE_TO_BOARD.values()):
            refuse("board_market_not_a_game_line")
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
        candidates = index.get((league, date, board_market)) or []
        if not candidates:
            _note_unmatched("no_candidates", board_row, board_market, league, date, [])
            refuse("no_polymarket_market_for_league_date_market")
            continue

        board_line = _as_float(board_row.get("line"))
        side = str(board_row.get("side") or "").strip()
        picked: dict[str, Any] | None = None
        for candidate in candidates:
            if board_market in {"spreads", "totals"}:
                if board_line is None or candidate["line"] is None:
                    continue
                if abs(float(candidate["line"]) - float(board_line)) > 1e-9:
                    continue
            if not _teams_match(board_row, candidate["parsed"], board_row.get("sport") or sport):
                continue
            if picked is not None:
                # AMBIGUITY IS A REFUSAL. Two venue markets claiming one board
                # row, resolved by iteration order, is a bet on whichever came
                # first -- confident and wrong half the time.
                picked = None
                refuse("ambiguous_polymarket_match")
                break
            picked = candidate
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
                if _teams_match(board_row, flipped, board_row.get("sport") or sport):
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
            if _flip_matched or (
                board_pair is not None
                and any(c.get("canon_pair") == board_pair for c in candidates)
            ):
                orientation_listed[eligibility_key] = (
                    orientation_listed.get(eligibility_key, 0) + 1
                )
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

        probability = _probability_for_side(side, picked, board_row.get("sport") or sport, board_row)
        if probability is None:
            # The measured failure of the game-line join, kept as its own
            # counter: the market matched but we cannot place the SIDE.
            refuse("side_not_an_outcome_of_this_market")
            continue

        _classify_alignment(
            board_row, probability, f"{league}|{board_market}",
            alignment_counts, alignment_samples,
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


def _teams_match(board_row: Mapping[str, Any], parsed: Mapping[str, Any], sport: Any) -> bool:
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


def _resolver_key(record: Mapping[str, Any]) -> tuple[str, str, str, float | None, str] | None:
    """`(event_id, market, player, line, side)`, or None when it is not an identity.

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

    event_id = str(record.get("event_id") or "").strip()
    if not event_id:
        return None
    return (
        event_id,
        str(record.get("market") or "").strip().lower(),
        normalize_person(record.get("player_name")),
        _as_float(record.get("line")),
        str(record.get("side") or "").strip().lower(),
    )


def polymarket_price_resolver(matches: Sequence[Mapping[str, Any]]):
    """Board row -> Polymarket's own American price. Mirrors Kalshi's.

    Keyed by `_resolver_key`, the SAME tuple the ticker resolver uses. Two
    resolvers keyed by two slightly different tuples would pair a row with one
    market's price and another's contract -- a bet placed at a price that was
    never quoted for it, which is the hazard `kalshi_board_join._match_key`
    states and the reason this is one shared function rather than two copies.
    """
    index: dict[tuple[str, str, str, float | None, str], float] = {}
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
    index: dict[tuple[str, str, str, float | None, str], dict[str, Any]] = {}
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
