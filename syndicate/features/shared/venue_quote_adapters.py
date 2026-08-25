"""One adapter per odds source. Each reads an ARTIFACT, never a venue API.

A second independent API caller for one venue is a documented incident class
here -- `#139/#144` did it to MLB, `#148` did it to soccer, the same violation
twice. So every adapter below reads the artifact that venue's own refresh
already wrote. If a venue has no artifact yet, that is a NAMED REFUSAL, never
a fetch bolted on here.

THE UNIT IS DECLARED PER SOURCE, NEVER INFERRED (fan-in rule 5). Kalshi's first
live run corrected a 100x price error that came from assuming a unit matched
another venue's. Each adapter states its own and converts once.
"""

from __future__ import annotations

import json
import time
from typing import Any, Mapping

from syndicate.features.shared.venue_quote_fanin import (
    NOVIG_PUBLIC_TIER_REFUSAL,
    Quote,
    SourceOutcome,
)

__all__ = [
    "kalshi_outcome",
    "polymarket_us_outcome",
    "novig_outcome",
    "oddsapi_outcome",
    "probability_to_american",
    "quote_key",
]


def quote_key(sport: str, market: str, side: str, line: float | None) -> str:
    """The join key. Line is part of it: a spread at -1.5 and the same spread
    at -2.5 are different bets, and collapsing them prices one at the other's
    number."""
    line_part = "" if line is None else f"|{float(line):g}"
    return f"{str(sport or '').lower()}|{str(market or '').lower()}|{str(side or '').lower()}{line_part}"


def probability_to_american(probability: float | None) -> int | None:
    """Probability in (0,1) -> American odds. Declared once, used by every
    adapter whose venue quotes probability, so the conversion cannot drift
    between them."""
    try:
        p = float(probability)
    except (TypeError, ValueError):
        return None
    if not (0.0 < p < 1.0):
        # 0 and 1 are settled markets or a unit error. Both must stop here
        # rather than divide by zero downstream.
        return None
    return int(round(-100.0 * p / (1.0 - p))) if p > 0.5 else int(round(100.0 * (1.0 - p) / p))


def _artifact(path_parts: tuple[str, ...]) -> tuple[Any, float | None]:
    """`(payload, mtime)` or `(None, None)`. mtime is what makes the age real:
    a payload with no file behind it has no defensible freshness."""
    try:
        from syndicate.features.shared.refresh_state_store import read_json_file, reports_root

        path = reports_root().joinpath(*path_parts)
        payload = read_json_file(path)
        try:
            mtime = float(path.stat().st_mtime)
        except Exception:
            mtime = None
        return payload, mtime
    except Exception:
        return None, None


def _fetched_at(payload: Mapping[str, Any] | None, mtime: float | None) -> float | None:
    """Prefer the payload's OWN stamp over the file's mtime.

    An artifact republished unchanged gets a new mtime while its contents are
    hours old -- `PUBLISH_SKIPPED_UNCHANGED` and the artifact-pull sweep both
    touch files this way. Trusting mtime there would launder stale data as
    fresh, which is precisely the failure this module exists to catch.
    """
    # `updated_at` IS THE KEY THE ODDS-HISTORY SHARDS ACTUALLY USE, and its
    # absence from this list is why `oddsapi` contributed ZERO quotes to every
    # reprice on 2026-08-24/25.
    #
    # MEASURED: mlb, wnba and soccer all reported
    # `oddsapi: {'status': 'error', 'reason': 'shard_has_no_timestamp'}` on
    # every VENUE_REPRICE for a full evening. That reason is only reachable
    # AFTER the payload loads and after `markets` is confirmed non-empty -- so
    # the shards were present and full the whole time. Inspecting one:
    #
    #   data/mlb_source/artifacts/mlb/odds_history.json
    #     top-level: 'date', 'markets' (35), 'updated_at'
    #
    # `updated_at = '2026-07-12T02:47:30+00:00'`, and this loop never looked for
    # it. The same holds for the wnba and nhl shards. One missing key name took
    # an entire source offline while every counter said "error" rather than
    # "misconfigured", which is the difference between a feed someone chases
    # and a feed someone fixes.
    #
    # APPENDED, not inserted: the four names above keep their precedence, so a
    # shard carrying both an explicit fetch stamp and an update stamp still
    # prefers the fetch stamp. This can only ADD a resolvable timestamp.
    for key in ("fetched_at", "generated_at", "last_updated", "as_of", "updated_at"):
        raw = (payload or {}).get(key) if isinstance(payload, Mapping) else None
        if isinstance(raw, (int, float)) and raw > 0:
            return float(raw)
        if isinstance(raw, str) and raw.strip():
            parsed = _parse_iso(raw)
            if parsed is not None:
                return parsed
    return mtime


def _parse_iso(text: str) -> float | None:
    import datetime

    try:
        cleaned = str(text).strip().replace("Z", "+00:00")
        parsed = datetime.datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.timestamp()
    except Exception:
        return None


# --------------------------------------------------------------------------
# KALSHI -- quotes DOLLARS-AS-PROBABILITY (a $0.54 contract is p=0.54)
# --------------------------------------------------------------------------


def kalshi_outcome(sport: str, selected_date: str) -> SourceOutcome:
    payload, mtime = _artifact(("intelligence", "kalshi_markets.json"))
    if not isinstance(payload, Mapping):
        return SourceOutcome(source="kalshi", status="error", reason="kalshi_markets.json_unreadable")
    # THROUGH THE MERGE HELPER, never `payload["markets"]`.
    #
    # That key is no longer persisted. Storing the merged list beside the
    # per-series entries wrote the same payload twice and pushed the document
    # past the keyvalue store's 8MB ceiling, at which point it stopped being
    # written at all -- so the fix removed the duplicate and left the markets
    # under `series[<ticker>]["markets"]`.
    #
    # THIS READER WAS NOT UPDATED WITH THE WRITER, and it cost a whole evening.
    # Measured 2026-08-25T20:15:10Z, every sport, every cycle:
    #
    #   'kalshi': {'status': 'error', 'reason': 'markets_key_absent',
    #              'quotes': 0, 'age_seconds': None}
    #
    # Kalshi therefore offered ZERO quotes, won zero selections, put zero
    # positions in the plan, and `ORDER_PATH venue=kalshi` read
    # `status=no_positions` -- which looks exactly like "Kalshi has no markets
    # for us" and was in fact one dictionary key.
    from pipeline.kalshi_odds_refresh import markets_from_state

    if not isinstance(payload.get("series"), Mapping) and not isinstance(
        payload.get("markets"), list
    ):
        # Neither shape present: the document is not a markets artifact at all.
        # Distinct from an artifact that holds no markets right now.
        return SourceOutcome(source="kalshi", status="error", reason="markets_key_absent")
    rows = markets_from_state(payload)
    fetched_at = _fetched_at(payload, mtime)
    if fetched_at is None:
        # No defensible age. Refusing beats emitting quotes the freshness gate
        # cannot reason about.
        return SourceOutcome(source="kalshi", status="error", reason="no_fetched_at_or_mtime")

    quotes: list[Quote] = []
    try:
        from syndicate.features.shared.kalshi_catalogue import classify_market
    except Exception as exc:  # noqa: BLE001
        return SourceOutcome(source="kalshi", status="error", reason=f"classify_unavailable: {type(exc).__name__}")

    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            classified = classify_market(row)
        except Exception:
            continue
        if not isinstance(classified, Mapping):
            continue
        if str(classified.get("sport") or "").lower() != str(sport or "").lower():
            continue
        market = str(classified.get("market") or "")
        side = str(classified.get("side") or "")
        if not market or not side:
            continue
        probability = _as_float(row.get("yes_bid") or row.get("last_price"))
        if probability is not None and probability > 1.0:
            # Kalshi has quoted CENTS on some routes. 54 is not a probability;
            # converting it as one is the 100x error its first live run found.
            probability = probability / 100.0
        line = _as_float(classified.get("line"))
        quotes.append(
            Quote(
                key=quote_key(sport, market, side, line),
                source="kalshi",
                sport=str(sport or ""),
                market=market,
                side=side,
                probability=probability,
                american=probability_to_american(probability),
                line=line,
                fetched_at=fetched_at,
                venue_ref=str(row.get("ticker") or "") or None,
            )
        )
    return SourceOutcome(
        source="kalshi",
        status="ok" if quotes else "no_rows",
        reason=None if quotes else "no_kalshi_market_classified_to_this_sport",
        quotes=quotes,
        age_seconds=max(0.0, time.time() - fetched_at),
    )


# --------------------------------------------------------------------------
# POLYMARKET US -- quotes PROBABILITY directly (outcomePrices are 0..1)
# --------------------------------------------------------------------------


def polymarket_us_outcome(sport: str, selected_date: str) -> SourceOutcome:
    payload, mtime = _artifact(("intelligence", "polymarket_us_games.json"))
    if not isinstance(payload, Mapping):
        # The catalogue is reachable (7,585 game markets measured 2026-08-24)
        # but nothing persists it yet. A named refusal, not an error: this is a
        # missing writer, and saying so points at the fix.
        return SourceOutcome(
            source="polymarket_us",
            status="refused",
            reason="no_polymarket_us_games_artifact: the slate is reachable via "
                   "polymarket_us_markets.fetch_game_markets but no refresh persists it yet",
        )
    rows = payload.get("markets")
    if not isinstance(rows, list):
        return SourceOutcome(source="polymarket_us", status="error", reason="markets_key_absent")
    fetched_at = _fetched_at(payload, mtime)
    if fetched_at is None:
        return SourceOutcome(source="polymarket_us", status="error", reason="no_fetched_at_or_mtime")

    # FILTER BY SPORT FIRST. Measured 2026-08-24 23:45Z, the first live run:
    #
    #   mlb  polymarket_us quotes=7040     nfl     polymarket_us quotes=7040
    #   wnba polymarket_us quotes=7040     soccer  polymarket_us quotes=7040
    #
    # The same 7,040 for every sport, because this adapter took `sport` only to
    # BUILD THE KEY and never to select rows. So an NFL market was keyed
    # `mlb|h2h|Chargers` when called for mlb -- a WRONG PRICE if a name ever
    # collided across sports, not a missing one.
    #
    # It did not bite: Kalshi was fresher (654s vs 4272s) and won all 237
    # selections, so no Polymarket quote was used. That is a timing accident,
    # not a safeguard.
    #
    # The league is in the slug -- `aec-mlb-pit-sd-2026-08-24` -- which is the
    # same structured key the board join reads, so the two cannot disagree.
    from syndicate.features.shared.polymarket_board_join import _effective_league, parse_slug

    wanted_league = str(sport or "").strip().lower()

    quotes: list[Quote] = []
    # THE WORK QUEUE, not decoration. Spreads are refused pending a
    # measurement of which team a handicap belongs to; a refusal nobody counts
    # is indistinguishable from a venue that lists no spreads, which is the
    # confusion this whole module is built to prevent.
    spread_rows = 0
    unresolved_clubs: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        parsed_slug = parse_slug(row.get("slug"))
        # `_effective_league`, not the literal slug token: Polymarket lists
        # soccer per COMPETITION while every Syndicate soccer board row is
        # stamped `sport="soccer"` uniformly, so a literal compare can never
        # match soccer at all -- see that function's docstring for the
        # measurement. Same resolver `polymarket_board_join` uses, so the two
        # consumers of this venue cannot disagree about which league a row
        # belongs to.
        if parsed_slug is None or _effective_league(parsed_slug) != wanted_league:
            continue
        if str(row.get("sportsMarketTypeV2") or "").upper() == "SPORTS_MARKET_TYPE_SPREAD":
            spread_rows += 1
        parsed = _polymarket_sides(row, sport, parsed_slug, unresolved_clubs)
        if not parsed:
            continue
        market, sides, line = parsed
        for side, probability in sides:
            quotes.append(
                Quote(
                    key=quote_key(sport, market, side, line),
                    source="polymarket_us",
                    sport=str(sport or ""),
                    market=market,
                    side=side,
                    probability=probability,
                    american=probability_to_american(probability),
                    line=line,
                    fetched_at=fetched_at,
                    venue_ref=str(row.get("slug") or "") or None,
                )
            )
    if not quotes:
        # NAMED SEPARATELY. "this league is not listed here" and "this league
        # is listed but every market is a spread we cannot yet place" are
        # different facts that call for different work, and a shared reason
        # string would send someone to look at the wrong one.
        # THREE DIFFERENT FACTS, three different reasons. "this league is not
        # listed here", "it is listed but every market is a spread we cannot
        # place yet", and "it is listed but we cannot NAME any of the clubs"
        # send someone to three different places, and a shared string would
        # send them to the wrong one. The last is the dangerous one to
        # mis-report: an alias-map gap that reads as an absent league looks
        # like the venue's fault instead of ours.
        dropped = _polymarket_ok_reason(spread_rows, unresolved_clubs)
        reason = (
            f"no_placeable_polymarket_row_for_league_{sport} {dropped}"
            if dropped
            else f"no_polymarket_row_for_league_{sport}"
        )
        return SourceOutcome(
            source="polymarket_us",
            status="no_rows",
            reason=reason,
            quotes=[],
            age_seconds=max(0.0, time.time() - fetched_at),
        )
    return SourceOutcome(
        source="polymarket_us",
        status="ok",
        # Carried on a SUCCESSFUL outcome too: spreads refused while moneylines
        # and totals priced is the normal state until the handicap question is
        # settled, and it must stay visible rather than vanish on success.
        reason=_polymarket_ok_reason(spread_rows, unresolved_clubs),
        quotes=quotes,
        age_seconds=max(0.0, time.time() - fetched_at),
    )


def _polymarket_ok_reason(spread_rows: int, unresolved_clubs: list[str]) -> str | None:
    """What was dropped on a SUCCESSFUL read, or None if nothing was.

    Carried on `status="ok"` deliberately. Spreads refused and clubs the alias
    map cannot name are the normal state right now, not errors -- but a drop
    that only shows up when everything else fails is a drop nobody reads. The
    unresolved club NAMES are included (bounded) because that list is directly
    actionable: each one is a missing `team_aliases` entry.
    """
    parts = []
    if spread_rows:
        parts.append(f"spreads_refused:{spread_rows}")
    if unresolved_clubs:
        sample = sorted(set(unresolved_clubs))[:6]
        parts.append(f"clubs_unresolved:{len(unresolved_clubs)}:{sample}")
    return " ".join(parts) if parts else None


def _polymarket_sides(
    row: Mapping[str, Any],
    sport: Any = None,
    parsed_slug: Mapping[str, Any] | None = None,
    unresolved: list[str] | None = None,
) -> tuple[str, list[tuple[str, float | None]], float | None] | None:
    """`(market, [(side, probability)], line)` in THE BOARD'S OWN VOCABULARY.

    --------------------------------------------------------------------------
    WHY THIS TRANSLATES INSTEAD OF PASSING THE VENUE'S WORDS THROUGH
    --------------------------------------------------------------------------

    It used to emit the venue's raw outcome string as the side. MEASURED
    2026-08-25T00:46:19Z, `VENUE_REPRICE_KEYS`, the two sides of the join
    printed beside each other for the first time:

        board wanted      mlb|h2h|home            mlb|totals|over|6.5
        polymarket gave   mlb|h2h|chicago cubs    mlb|spreads|-2.50

    The board keys a side by its ROLE (`home`/`away`); Polymarket keys it by
    the TEAM'S IDENTITY (`chicago cubs`, and for WNBA the short forms `sky`,
    `sun`, `wings`). Those cannot match by string equality no matter how fresh
    either quote is -- which is why polymarket_us offered 3,106 quotes across
    three sports and won ZERO of 237 selections while looking, in every other
    counter, like a working feed. Same class as the OddsAPI adapter sitting on
    a different key space for an entire evening.

    --------------------------------------------------------------------------
    THE ROLE COMES FROM THE SLUG, NOT FROM ARRAY POSITION
    --------------------------------------------------------------------------

    `parse_slug` gives `<away>-<home>` as a structured fact, and
    `team_aliases.teams_match` resolves an abbreviation against a full name in
    either direction -- both already used by `polymarket_board_join` for this
    same problem, so the two cannot disagree about which side a name refers to.

    Array position is NOT used, deliberately. Measured 2026-08-24 on real
    spread rows: the order of `outcomes` does not reliably follow the slug --
    1 of 5 sampled rows would have been priced on the opposite handicap. A
    team we cannot place is REFUSED rather than assigned positionally, because
    guessing is a bet on the wrong team half the time at a confident price.

    --------------------------------------------------------------------------
    SPREADS REFUSE, BY NAME, PENDING A MEASUREMENT
    --------------------------------------------------------------------------

    The board wants `spreads|<home|away>|<line>` -- WHOSE handicap, and what
    number. Polymarket publishes one market per side with the handicap AS the
    outcome (`+2.50`/`-2.50`) and a `pos`/`neg` token in the slug, but nothing
    in the row or the slug that this module has MEASURED says which TEAM the
    handicap belongs to. Inventing that mapping is precisely the error the
    sign-token trap already cost once, so spreads are refused with their own
    reason and counted. `polymarket_spread_rows` is the work queue that
    settles it.
    """
    outcomes = _maybe_json_list(row.get("outcomes"))
    prices = _maybe_json_list(row.get("outcomePrices"))
    if not outcomes or not prices or len(outcomes) != len(prices):
        return None
    market_type = str(row.get("sportsMarketTypeV2") or "").upper()
    market = {
        "SPORTS_MARKET_TYPE_MONEYLINE": "h2h",
        "SPORTS_MARKET_TYPE_SPREAD": "spreads",
        "SPORTS_MARKET_TYPE_TOTAL": "totals",
        # DRAWABLE_OUTCOME -> h2h, added 2026-08-25: soccer's 3-way
        # home/draw/away shape, confirmed live in catalogue logs. Falls
        # through to the SAME generic moneyline resolution below (each
        # outcome name resolved independently via `canonical_team`), so an
        # unconfirmed "Draw" outcome shape costs nothing -- it simply never
        # resolves to a club and is dropped like any other unresolved name,
        # counted in `unresolved_clubs`. See `polymarket_board_join`'s
        # `MARKET_TYPE_TO_BOARD` for the matching change and its full note.
        "SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME": "h2h",
    }.get(market_type)
    if market is None:
        # PROP is real and joinable, but needs a market mapping this module
        # has not measured (player-name resolution, a different problem with
        # its own failure modes -- see `polymarket_board_join`'s header).
        # Refusing one row is cheaper than inventing a market name that
        # silently never matches.
        return None

    from syndicate.features.shared.polymarket_board_join import (
        _has_segment,
        _line_from_modifiers,
    )

    modifiers = list((parsed_slug or {}).get("modifiers") or [])

    # A FIRST-QUARTER TOTAL IS NOT A GAME TOTAL. The board's `totals` means the
    # full game, and this adapter had no segment check at all -- so a `1q` or
    # `f5` market was keyed plain `totals` and would have re-priced a full-game
    # row at a period's number. `polymarket_board_join` already refuses these;
    # the two consumers of this venue must not disagree about it.
    if _has_segment(modifiers):
        return None

    # The persisted row's own `line` first, then the slug's. MEASURED: the
    # offered keys carried no line at all (`mlb|spreads|-2.50`), because
    # `row["line"]` is absent on these rows -- so a totals key was built
    # without the number that decides which bet it is.
    line = _as_float(row.get("line"))
    if line is None:
        line = _line_from_modifiers(modifiers)

    if market == "spreads":
        # Refused by name rather than guessed. See the docstring.
        return None

    if market == "totals":
        sides: list[tuple[str, float | None]] = []
        for name, price in zip(outcomes, prices):
            token = str(name or "").strip().lower()
            if token not in {"over", "under"}:
                continue
            sides.append((token, _as_float(price)))
        # A total with no number is not a bet: `totals|over` would match any
        # line at all, which is worse than matching none.
        return (market, sides, line) if (sides and line is not None) else None

    # MONEYLINE, KEYED BY THE CANONICAL CLUB NAME.
    #
    # NOT by the slug's `<away>-<home>` roles, which was the first attempt and
    # is measurably too weak. `teams_match` against the slug abbreviation
    # resolves `chc`/"Chicago Cubs" but NOT `sd`/"Padres", `lac`/"Chargers" or
    # `chi`/"Sky" -- the WNBA tri-codes are absent from the alias map entirely.
    # Production carries both shapes at once: mlb rows name clubs in full
    # (`chicago cubs`) while wnba rows use bare nicknames (`sky`, `wings`).
    #
    # `canonical_team` resolves the OUTCOME NAME in every one of those cases
    # ("Sky" -> `chicago sky`), so the club name is the vocabulary both halves
    # of this join can actually speak. The fan-in derives the same canonical
    # name from the board row's own `home_team`/`away_team`, which means one
    # resolver decides both sides -- the property this repo keeps insisting on,
    # because two resolvers disagreeing is how the halves of a join end up on
    # different vocabularies without anyone noticing.
    #
    # Nothing is lost by moving off the role key: Kalshi's moneyline emits
    # `side="yes"` (the club lives in `subject`), so `h2h|yes` matched no board
    # row either. There was no working h2h match to preserve.
    from syndicate.features.shared.team_aliases import canonical_team

    resolved: list[tuple[str, float | None]] = []
    for name, price in zip(outcomes, prices):
        club = canonical_team(sport, name)
        # A club we cannot name is REFUSED, never taken positionally. Array
        # order does not reliably follow the slug (measured on spread rows,
        # 1 of 5 would have been the opposite side), and there is no reason to
        # trust it more here.
        #
        # COUNTED, because this is a live coverage gap and not a theoretical
        # one. `canonical_team` resolves a bare WNBA nickname ("Sky" ->
        # `chicago sky`) but NOT an MLB or NFL one -- "Padres" and "Chargers"
        # both return None. Production sends MLB clubs in full today, so
        # nothing is lost right now; the day it sends nicknames instead, this
        # counter is the difference between a visible alias-map gap and a feed
        # that quietly halves.
        if not club:
            if unresolved is not None:
                unresolved.append(str(name))
            continue
        resolved.append((club, _as_float(price)))
    # h2h carries no line -- passing one builds `h2h|<club>|-1.5`, which no
    # board row asks for.
    return (market, resolved, None) if resolved else None


def _maybe_json_list(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return None
        return parsed if isinstance(parsed, list) else None
    return None


# --------------------------------------------------------------------------
# NOVIG -- a CAPABILITY GAP, stated rather than left looking broken
# --------------------------------------------------------------------------


def novig_outcome(sport: str, selected_date: str) -> SourceOutcome:
    """Measured 2026-08-24 (`f58905948`): the public CSV mirror is anonymized
    at the game/player/team level. `reportTicker`/`contractSeries` name a
    CATEGORY, never a specific bet, so no amount of freshness makes it price a
    named row. The credentialed REST tier could; nobody has that credential."""
    return SourceOutcome(source="novig", status="refused", reason=NOVIG_PUBLIC_TIER_REFUSAL)


# --------------------------------------------------------------------------
# ODDSAPI -- quotes AMERICAN. One source among venues, switchable.
# --------------------------------------------------------------------------


def oddsapi_outcome(sport: str, selected_date: str) -> SourceOutcome:
    """Reads the odds_history shard the existing pipeline already loads.

    Deliberately NOT privileged. It is one entry in `SOURCES` and one env flag
    away from off, because it being the spine is what let a 13.9-hour quote
    define the board on 2026-08-24.
    """
    try:
        from syndicate.features.shared.odds_control_plane import (
            load_odds_history_payload_for_sport,
        )
    except Exception as exc:  # noqa: BLE001
        return SourceOutcome(source="oddsapi", status="error", reason=f"loader_unavailable: {type(exc).__name__}")

    try:
        payload = load_odds_history_payload_for_sport(str(sport or ""), str(selected_date or ""))
    except Exception as exc:  # noqa: BLE001
        return SourceOutcome(source="oddsapi", status="error", reason=f"{type(exc).__name__}: {exc}")
    if not isinstance(payload, Mapping):
        return SourceOutcome(source="oddsapi", status="no_rows", reason="no_odds_history_shard_for_this_sport_and_date")

    markets = payload.get("markets")
    if not isinstance(markets, Mapping) or not markets:
        return SourceOutcome(source="oddsapi", status="no_rows", reason="shard_has_no_markets")
    fetched_at = _fetched_at(payload, None)
    if fetched_at is None:
        return SourceOutcome(source="oddsapi", status="error", reason="shard_has_no_timestamp")

    quotes: list[Quote] = []
    no_side = 0
    no_price = 0
    for market_key, entry in markets.items():
        if not isinstance(entry, Mapping):
            continue
        # THE MARKET, SIDE AND LINE ARE IN THE KEY, NOT THE VALUE.
        #
        # MEASURED 2026-08-25 against a real shard entry:
        #
        #   KEY   event_id=..|home_team=..|away_team=..|market=h2h|bookmaker=fanduel
        #   VALUE delta, delta_line, history, last_line, last_odds,
        #         last_snapshot_ts, last_source_path, last_updated, movement,
        #         percent_change, previous_line
        #
        # `entry.get("market")`, `("side")`, `("line")`, `("american")`,
        # `("price")` and `("probability")` are ALL None. So every quote was
        # built as `quote_key(sport, None, None, None)` -- one identical,
        # useless key for the whole shard, carrying no price at all. That is
        # why oddsapi reported `quotes: 298` and won ZERO selections: it was
        # emitting 298 copies of `soccer||` with `american=None`.
        #
        # A count that looks like coverage while carrying nothing is the exact
        # failure this module's header is about, and it survived because
        # `quotes` was non-empty so `status` read `ok`.
        parsed_key = _parse_odds_history_key(market_key)
        american = _as_float(entry.get("last_odds"))
        # THE SAME KEY SHAPE AS EVERY OTHER SOURCE. The first cut used the
        # shard's own market key -- `event_id=...|home_team=...|market=h2h|
        # side=Draw|book=draftkings` -- which shares no key space with the
        # venue adapters, so `select_quote` could never have compared an
        # OddsAPI quote against a Kalshi one. Two sources on different keys do
        # not contend; they just never meet, and the freshest-wins rule this
        # module is built on would have been silently inert.
        market = parsed_key.get("market")
        side = parsed_key.get("side")
        # NO SIDE, NO QUOTE. MLB keys carry `market=h2h|bookmaker=fanduel` with
        # no side at all -- one entry per event+market+book -- so there is
        # nothing that says which team `last_odds` belongs to. Emitting it
        # against a guessed side is a price for the wrong team; counted by name
        # instead, because "this shard cannot express a side" and "this sport
        # is absent" are different facts.
        if not market or not side:
            no_side += 1
            continue
        if american is None:
            no_price += 1
            continue
        quotes.append(
            Quote(
                key=quote_key(sport, market, side, parsed_key.get("line")),
                source="oddsapi",
                sport=str(sport or ""),
                market=str(market),
                side=str(side),
                probability=None,
                american=int(american),
                line=parsed_key.get("line"),
                fetched_at=fetched_at,
            )
        )
    dropped = []
    if no_side:
        dropped.append(f"no_side_in_key:{no_side}")
    if no_price:
        dropped.append(f"no_last_odds:{no_price}")
    detail = " ".join(dropped)
    return SourceOutcome(
        source="oddsapi",
        status="ok" if quotes else "no_rows",
        # The drop counts ride on SUCCESS too. A shard that yields 12 usable
        # quotes out of 300 is not the same as one that yields 12 out of 12,
        # and only this says which.
        reason=(detail or None) if quotes else (detail or "shard_parsed_to_zero_quotes"),
        quotes=quotes,
        age_seconds=max(0.0, time.time() - fetched_at),
    )


def _parse_odds_history_key(market_key: Any) -> dict[str, Any]:
    """`event_id=..|home_team=..|market=h2h|side=Draw|book=draftkings` -> a dict.

    The shard's key is a pipe-delimited `k=v` string and it is the ONLY place
    the market and side appear -- the entry value holds movement fields
    (`delta`, `history`, `previous_line`) and no identity at all.

    Shapes differ BY SPORT, which is why this parses rather than assumes: the
    soccer keys carry `side=` and `book=`, the MLB keys carry `bookmaker=` and
    NO side. A parser that required one shape would silently drop the other.
    """
    out: dict[str, Any] = {}
    for part in str(market_key or "").split("|"):
        name, sep, value = part.partition("=")
        if not sep:
            continue
        out[name.strip().lower()] = value.strip()
    line = out.get("line")
    out["line"] = _as_float(line) if line is not None else None
    return out


def _as_float(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
