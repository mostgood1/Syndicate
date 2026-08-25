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
from typing import Any, Mapping, Sequence

__all__ = [
    "parse_slug",
    "join_polymarket_to_board",
    "polymarket_price_resolver",
    "polymarket_ticker_resolver",
    "load_polymarket_markets",
    "MARKET_TYPE_TO_BOARD",
]

# The venue's type vocabulary -> the board's market names. Observed values only;
# an unseen type is refused rather than mapped to a plausible neighbour.
MARKET_TYPE_TO_BOARD: dict[str, str] = {
    "SPORTS_MARKET_TYPE_MONEYLINE": "h2h",
    "SPORTS_MARKET_TYPE_SPREAD": "spreads",
    "SPORTS_MARKET_TYPE_TOTAL": "totals",
}

# `14pt5` -> 14.5. The venue writes decimals this way in slugs; reading it as an
# integer would price a +14.5 spread at +145.
_SLUG_NUMBER = re.compile(r"^(?P<sign>neg|pos)?(?P<whole>\d+)(?:pt(?P<frac>\d+))?$")

_SLUG_SHAPE = re.compile(
    r"^(?P<prefix>[a-z]+)-(?P<league>[a-z0-9]+)-(?P<away>[a-z0-9]+)-(?P<home>[a-z0-9]+)"
    r"-(?P<date>\d{4}-\d{2}-\d{2})(?:-(?P<rest>.+))?$"
)


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

    # Index the venue side once, keyed on what a board row can be asked for.
    index: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in markets:
        parsed = parse_slug(row.get("slug"))
        if parsed is None:
            refuse("slug_unparseable")
            continue
        board_market = MARKET_TYPE_TO_BOARD.get(str(row.get("sportsMarketTypeV2") or "").upper())
        if board_market is None:
            # PROP and DRAWABLE_OUTCOME land here. Real markets, deliberately
            # out of scope -- see the module header.
            refuse("market_type_not_a_game_line")
            continue
        if _has_segment(parsed["modifiers"]):
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
        key = (parsed["league"], parsed["date"], board_market)
        index.setdefault(key, []).append(
            {"parsed": parsed, "row": row, "outcomes": outcomes,
             "line": _line_from_modifiers(parsed["modifiers"])}
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
            if "ambiguous_polymarket_match" not in refusals or refusals.get("ambiguous_polymarket_match", 0) == 0:
                refuse("no_matching_polymarket_market")
            continue

        probability = _probability_for_side(side, picked, board_row.get("sport") or sport, board_row)
        if probability is None:
            # The measured failure of the game-line join, kept as its own
            # counter: the market matched but we cannot place the SIDE.
            refuse("side_not_an_outcome_of_this_market")
            continue

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
    }


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
    return bool(
        alias_match(sport, parsed.get("home"), home)
        and alias_match(sport, parsed.get("away"), away)
    )


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
