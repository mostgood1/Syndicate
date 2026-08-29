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

import csv
import json
import time
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.shared.venue_quote_fanin import (
    NOVIG_PUBLIC_TIER_REFUSAL,
    Quote,
    SourceOutcome,
    _ROLE_KEYED_MARKETS,
)

__all__ = [
    "kalshi_outcome",
    "polymarket_us_outcome",
    "novig_outcome",
    "oddsapi_outcome",
    "probability_to_american",
    "quote_key",
    "game_token",
]


def quote_key(sport: str, market: str, side: str, line: float | None, game: str | None = None) -> str:
    """The join key. Line is part of it: a spread at -1.5 and the same spread
    at -2.5 are different bets, and collapsing them prices one at the other's
    number.

    --------------------------------------------------------------------------
    `#603`: THE GAME IS PART OF IT TOO, AND LEAVING IT OUT PRICED THE WRONG GAME
    --------------------------------------------------------------------------

    This key used to be `sport|market|side|line` and nothing else. The fan-in
    resolves it against `quotes_for_sport` -- a pool scoped to the WHOLE SPORT
    -- so every live MLB game with a 7.5 total asked for the single key
    `mlb|totals|over|7.5`, and one venue quote answered all of them.

    MEASURED IN PRODUCTION 2026-08-29, board `written_at 21:56:11Z`:
    **26 of 28 live Polymarket totals quotes were shared across games.**

        over  7.5 @ -400   AZ@SF, COL@ATL, HOU@NYM, SD@TB   (four at once)
        over  8.5 @ +1233  three games
        over 10.5 @ -6567  two games

    COL@ATL was 1 run in the 7th, so over 7.5 was worth ~2% (Kalshi quoted
    0.08). SD@TB was 13 runs, so over 7.5 had ALREADY WON -- 100%. Both carried
    `-400` (=80%). One price cannot be both, which is what makes this a defect
    rather than a market. `best_any_book` was `polymarket` on 28 of 28 of those
    rows, so the cross-game quote was the price the board held up as best.

    `#603` had already measured the same thing from the order side: 6 of 14
    game-line keys spanned more than one event, 2 more than one segment, across
    74 real orders.

    THE SAME FIX PROPS ALREADY GOT. `prop_quote_key` exists because every
    player's row keyed to one player-blind string and "rows that share a key are
    indistinguishable here: the first wins, and the quote it wins describes a
    different human." Identical shape, one market family over: a different GAME.

    `game` is OPTIONAL and appended last, so a caller that does not pass one
    produces exactly the old string. That keeps this additive -- see
    `venue_quote_fanin._candidate_keys`, which offers the qualified key FIRST
    and the bare key after it, and the game check in the fan-in's match loop,
    which is what makes the bare fallback safe rather than a hole.
    """
    line_part = "" if line is None else f"|{float(line):g}"
    game_part = "" if not game else f"|@{str(game).lower()}"
    return (
        f"{str(sport or '').lower()}|{str(market or '').lower()}"
        f"|{str(side or '').lower()}{line_part}{game_part}"
    )


def game_token(sport: Any, home: Any, away: Any) -> str | None:
    """A game's identity as BOTH clubs, order-independent, or None.

    --------------------------------------------------------------------------
    SORTED, SO HOME/AWAY CONFUSION CANNOT BREAK THE JOIN
    --------------------------------------------------------------------------

    The two halves of this join disagree about roles constantly -- that is the
    whole subject of `_candidate_keys`' docstring, and Polymarket's `outcomes`
    array has already been measured reversed against its own slug. A token that
    depended on which club is "home" would inherit every one of those
    arguments. Sorting removes the question: home/away and away/home produce the
    same token, and the SIDE carries direction, as it already did.

    RESOLVED THROUGH `canonical_team`, THE SAME RESOLVER BOTH HALVES ALREADY
    USE. `_candidate_keys` says it outright -- "two resolvers is how the halves
    of a join end up on different vocabularies; one cannot disagree with
    itself." A raw-string fallback here would rebuild that disagreement, so
    there is none: **either club unresolvable yields None**, and the caller
    falls back to the bare key rather than keying on a name only one side would
    recognise.

    KNOWN RESIDUAL -- DOUBLEHEADERS, and it is NOT closed. Two games between the
    same clubs on the same date share a token. The pool is already date-scoped
    (`collect_quotes(sport, selected_date)`), so this narrows the collision from
    "any game in the sport sharing a line" -- four at once, measured -- to "the
    two halves of a doubleheader". It is not eliminated because neither venue
    can distinguish them either: Polymarket's slug carries the date and no game
    number (`aec-mlb-az-sf-2026-08-29`), so there is no shared vocabulary to key
    on. The fan-in's game check cannot catch it either, since both halves
    produce the same token. Recorded rather than papered over -- AZ@SF and
    BOS@NYY both played doubleheaders on the day this was written.
    """
    from syndicate.features.shared.team_aliases import canonical_team

    try:
        one = canonical_team(sport, home)
        two = canonical_team(sport, away)
    except Exception:
        return None
    if not one or not two:
        return None
    return "+".join(sorted([str(one).strip().lower(), str(two).strip().lower()]))


def prop_quote_key(sport: Any, market: Any, player: Any, side: Any, line: float | None) -> str | None:
    """The join key for a PLAYER PROP, or None when the player cannot be named.

    THE PLAYER IS PART OF THE BET AND WAS MISSING FROM THE KEY. `quote_key`
    builds `<sport>|<market>|<side>|<line>`, which is complete for a game line
    and dangerously incomplete for a prop: every player's anytime-scorer row
    collapses to the single string `soccer|player_goal_scorer_anytime|yes`, and
    every 2.5-three-pointer row to `wnba|player_threes|over|2.5`. Two rows with
    the same key are indistinguishable to `apply_venue_quotes`, so the first
    one wins and the quote it wins describes a DIFFERENT HUMAN.

    `kalshi_board_join` -- the OTHER join over the same markets -- has always
    keyed props as `market|normalize_person(subject)|line`. This brings the
    venue fan-in onto that same shape, and reuses that module's own
    `normalize_person` rather than adding a third normaliser, because two
    normalisers disagreeing on one name is the silent mismatch this repo has
    already paid for.

    Returns None rather than a player-blind key when the name is unusable. A
    key that matches the wrong player is worse than no key at all: it stamps a
    row as freshly observed on the strength of an observation of someone else.
    """
    from syndicate.features.shared.kalshi_board_join import normalize_person

    person = normalize_person(player)
    if not person:
        return None
    return quote_key(sport, market, f"{person}|{side}", line)


def team_quote_token(sport: Any, name: Any) -> str | None:
    """A team's identity for a quote key, or None.

    ONE NORMALISER, IMPORTED BY BOTH SIDES. `venue_quote_fanin._candidate_keys`
    calls this for the BOARD's team names and `kalshi_outcome` calls it for the
    VENUE's, so the two halves of the join cannot end up on different
    spellings. A private copy in either file is the drift this repo has already
    paid for three times in one day (`learnings.md` 2026-08-23).

    `canonical_team` FIRST, so a name the club map knows keeps the exact
    spelling the existing `h2h|<club>` key already uses and nothing that
    matches today stops matching. Only an unresolvable name falls through to a
    normalised raw form -- which is the common case for Kalshi, whose titles
    say "Texas" where the club map carries "texas rangers".
    """
    raw = " ".join(str(name or "").strip().lower().replace(".", " ").split())
    if not raw:
        return None
    try:
        from syndicate.features.shared.team_aliases import canonical_team

        resolved = canonical_team(sport, name)
    except Exception:
        resolved = None
    return str(resolved).strip().lower() if resolved else raw


def team_name_tokens(sport: Any, name: Any) -> set[str]:
    """The distinguishing words of a club name, for matching a venue that names
    a team by its CITY or nickname alone.

    Kalshi writes "Texas wins by over 3.5 runs" while the board carries "Texas
    Rangers", so an exact compare refuses every team-named game line --
    `kalshi_board_join._side_for_team` records exactly that measurement
    (`team_side_unresolved` on all of them) and solves it the same way: match a
    token against the club name.

    A TOKEN IS REPORTED ONLY IF IT NAMES EXACTLY ONE CLUB IN THIS SPORT.
    "chicago" sits inside both "chicago cubs" and "chicago white sox", so it
    names neither side, and returning a guess there is a bet on the wrong team
    at a price that looks confident.

    THE OPPONENT IS THE WRONG BOUND, and was the one this function used to rely
    on its caller for. `_candidate_keys` drops the tokens the opponent shares,
    which is correct about the ROW and irrelevant to the LOOKUP:
    `apply_venue_quotes` resolves a candidate key against the sport's whole
    quote pool, not against the row's own game. A Manchester City row offering
    `soccer|h2h|city` could therefore win a Bristol City quote from an entirely
    different fixture. Measured 2026-08-27, `city` names 14 clubs in the soccer
    map and `real` names 4; mlb, nfl and nba carry 7, 5 and 3 such tokens. So
    the bound is `unambiguous_club_tokens`, the sport's WHOLE vocabulary, and
    the opponent subtraction upstream is left in place as a second, narrower
    check rather than the only one.

    AN UNRESOLVABLE NAME YIELDS NOTHING. `team_quote_token` deliberately falls
    back to a normalised raw string, because that is right at the VENUE --
    Kalshi says "Texas" and no club map carries it. It is wrong here: the board
    half of the join is where both clubs are supposed to be known, and a raw
    fallback made "Not A Real Club" offer `mlb|h2h|club`, `mlb|h2h|not` and
    `mlb|h2h|real` -- words with no team behind them, one of which is a real
    soccer club token. Sports whose `_alias_map` is empty (nhl, ncaaf, ncaab)
    resolve nothing and so offer nothing; NCAAF reaching the board on
    2026-08-27 would otherwise have offered `ncaaf|h2h|state`.
    """
    from syndicate.features.shared.team_aliases import (
        canonical_team,
        unambiguous_club_tokens,
    )

    # `canonical_team`, NOT `team_quote_token`: the raw fallback that makes the
    # venue side work is exactly what must not happen on the board side.
    club = canonical_team(sport, name)
    if not club:
        return set()
    token = str(club).strip().lower()
    if not token:
        return set()
    allowed = unambiguous_club_tokens(str(sport or "").strip().lower())
    # The full form is a token too, so an exact name still matches through the
    # same path rather than through a second one.
    candidates = {token} | {word for word in token.split() if len(word) > 2}
    return {word for word in candidates if word in allowed}


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


_MIRROR_SIDE = {"over": "under", "under": "over"}


def _kalshi_leg_probability(row: Mapping[str, Any], leg: str) -> float | None:
    """The quoted probability for one leg of a Kalshi contract, or None.

    THIS READ WAS BROKEN AND SILENTLY SO. It used to be

        _as_float(row.get("yes_bid") or row.get("last_price"))

    and NEITHER FIELD IS PERSISTED. `kalshi_odds_refresh._LEAN_MARKET_FIELDS`
    is the whole schema that reaches this artifact -- `yes_ask_dollars`,
    `no_ask_dollars`, `yes_american`, `no_american`, `yes_probability`,
    `no_probability` -- and `_lean_market` at its one call site (line 895) drops
    everything else. `yes_bid` and `last_price` are `normalize_market` diagnosis
    fields that never survive persistence.

    So `probability` was None on EVERY Kalshi quote, `probability_to_american`
    turned that into None, and the adapter published 400 nfl / 400 ncaaf / 121
    wnba quotes carrying no price at all. `status` read `ok` because `quotes`
    was non-empty -- the exact "count that looks like coverage while carrying
    nothing" failure this module's header was written about, and the same one
    that hid the OddsAPI key-space bug for an evening.

    `yes_probability` first because it is already 0..1 and computed by
    `kalshi_client` from the ask; `*_ask_dollars` as the fallback, since a
    binary contract's price in dollars IS its probability. The cents guard is
    kept: Kalshi has quoted CENTS on some routes, and 54 read as a probability
    is the 100x error its first live run found.
    """
    prefix = "yes" if leg == "yes" else "no"
    value = _as_float(row.get(f"{prefix}_probability"))
    if value is None:
        value = _as_float(row.get(f"{prefix}_ask_dollars"))
    if value is None:
        return None
    if value > 1.0:
        value = value / 100.0
    if value <= 0.0 or value >= 1.0:
        # A degenerate price is not a quote. Refused rather than published as a
        # certainty, which `probability_to_american` would turn into a
        # nonsensical payout.
        return None
    return value


def _kalshi_game_token(ticker: Any, sport: Any, games: Any) -> str | None:
    """The fixture a Kalshi ticker names, as a `game_token`, or None.

    --------------------------------------------------------------------------
    THE BLOB IS NOT SPLIT HERE. `match_event_blob` INVERTS THE PROBLEM.
    --------------------------------------------------------------------------

    `KXMLBTOTAL-26AUG291610SDTB-14` carries its event as `SDTB` --
    `event_blob_from_ticker` strips the date and MLB's optional start time and
    returns the run-together club codes. Its docstring is emphatic that the
    blob must NOT be split into two teams: codes run 2-4 characters, nothing in
    the string says where the boundary is, and "a wrong split pairs a bet with
    the wrong game, which is the one failure this whole module is built to
    prevent".

    So this does not split it. `match_event_blob` tries every legal split and
    CHECKS each against our own schedule, which is why it needs `games` -- and
    it is the same resolver `kalshi_board_join._resolve_event` uses, reused
    rather than reimplemented so a fix to it cannot be silently missed here.
    (`kalshi_polymarket_arb` reuses it for the same reason and says so.)

    RETURNS None ON ANY DOUBT, and every branch below is a doubt: no blob, no
    schedule, no match, or a match `match_event_blob` itself will not vouch
    for. A None key falls back to the bare key, which is exactly today's
    behaviour -- so this can add precision and never subtract coverage.
    """
    if not games:
        return None
    try:
        from syndicate.features.shared.kalshi_catalogue import (
            event_blob_from_ticker,
            match_event_blob,
        )
    except Exception:  # noqa: BLE001
        return None
    blob = event_blob_from_ticker(ticker)
    if not blob:
        return None
    try:
        result = match_event_blob(blob, list(games), sport=sport)
    except Exception:  # noqa: BLE001
        return None
    # `match_event_blob`'s vocabulary is `ok` / `no_match` / `ambiguous`, read
    # from the function rather than assumed. THE FIRST VERSION OF THIS LINE
    # CHECKED FOR `"matched"`, a string that does not exist, so every Kalshi
    # quote fell through to a bare key and the whole conversion was INERT --
    # caught by `test_a_kalshi_totals_quote_names_its_game_OFF_vs_ON` and by
    # nothing else, because an inert conversion looks exactly like a correct
    # one from the outside.
    #
    # `ambiguous` is a REFUSAL and must stay one: it means the blob split more
    # than one way against the schedule, and picking a winner there is the
    # wrong-game pairing this is built to prevent.
    if not isinstance(result, Mapping) or str(result.get("status") or "") != "ok":
        return None
    return game_token(sport, result.get("home_team"), result.get("away_team"))


def kalshi_outcome(
    sport: str,
    selected_date: str,
    *,
    games: Any = None,
) -> SourceOutcome:
    """Kalshi's book as quotes.

    `games` is `#603`'s Kalshi half and is OPTIONAL: absent, every key is bare
    and this behaves exactly as before. Present, a game-line quote is keyed to
    the fixture its TICKER names -- see `_kalshi_game_token`.
    """
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
    # THE WORK QUEUE, not decoration -- same reasoning as `polymarket_us_outcome`'s
    # `spread_rows`: a refusal nobody counts is indistinguishable from a venue
    # that lists nothing, which is the confusion this whole module exists to
    # prevent.
    spread_rows = 0
    no_price = 0
    prop_unnamed = 0
    h2h_unresolved = 0
    h2h_keyed = 0
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

        # THE SIDE VOCABULARY, AND WHY IT IS NOT ONE STRING FOR EVERY MARKET.
        #
        # `classify_market` reports the side the GRAMMAR read: a player prop and
        # a game total both say over/under, and the board asks for over/under
        # too, so those already meet and are passed through untouched. The two
        # game-line families do NOT:
        #
        #   moneyline   Kalshi "Texas wins"                -> side "yes"
        #   spread      Kalshi "Texas wins by over 3.5"     -> side "over"
        #   board       mlb|h2h|home  ·  mlb|spreads|away|1
        #
        # Measured 2026-08-25T21:12:14Z, `[layer2_shortlist] VENUE_REPRICE_KEYS`
        # with kalshi finally present in `sources_offered` for all four sports:
        #
        #   kalshi offered   nfl|h2h|yes      nfl|spreads|over|7.5
        #   board wanted     mlb|spreads|away|1   soccer|h2h|real betis
        #
        # A moneyline quoted `yes` and a spread quoted `over` can never meet a
        # board row keyed by ROLE, at any line -- so this sits UPSTREAM of every
        # line- or freshness-related reason the fan-in reports. Nothing was
        # broken; the two halves were never speaking the same words.
        if market == "h2h":
            # THE TEAM IS THE SIDE. `_MONEYLINE` already parsed it into
            # `subject` and this adapter was discarding it.
            # `venue_quote_fanin._candidate_keys` offers the matching shapes
            # from the board's own row -- club name, and the city or nickname
            # with any token the OPPONENT shares removed -- so the
            # disambiguation happens where both clubs are known, which is the
            # only place it is safe.
            subject = team_quote_token(sport, classified.get("subject"))
            if not subject:
                # A moneyline naming nobody. Counted, never published under a
                # positional guess.
                h2h_unresolved += 1
                continue
            side = subject
            line = None
        elif market.startswith("spreads"):
            # REFUSED BY NAME, PENDING THE SIGN CONVENTION -- exactly as
            # `polymarket_us_outcome` refuses spreads "pending a measurement of
            # which team a handicap belongs to".
            #
            # Kalshi says "Texas wins by over 3.5 runs", which is Texas -3.5,
            # and the board carries a SIGNED line per role (`spreads|home|-1.5`,
            # `spreads|away|1`). Publishing a club key here needs that sign to
            # be read off the board's own producer rather than inferred from
            # two samples, and `under` is not the mirror of `over` on this
            # grammar at all: "wins by under 3.5" is "wins, by less than 3.5",
            # which is not the other side of a handicap.
            #
            # Today these publish `spreads|over|<line>` and match nothing, so
            # refusing costs no match that exists -- it converts a silent
            # non-match into a counted one, which is the difference between
            # "Kalshi lists no spreads" and "we cannot key them yet".
            spread_rows += 1
            continue

        # A PLAYER MARKET KEYS ON ITS PLAYER, the same shape the board now
        # offers and the same one `kalshi_board_join` has always used. Game
        # lines (h2h / spreads / totals) have no subject and are unchanged.
        # Without this, Kalshi's prop quotes would stay player-blind while the
        # board went player-aware, and every prop match would disappear
        # SILENTLY rather than being corrected -- so this counts what it cannot
        # name instead.
        prop_player = None
        if not (market.startswith("h2h") or market.startswith("spreads") or market.startswith("totals")):
            prop_player = classified.get("subject")
            if not prop_player:
                prop_unnamed += 1
                continue

        probability = _kalshi_leg_probability(row, "yes")
        if probability is None:
            no_price += 1
        if market == "h2h":
            h2h_keyed += 1
        else:
            line = _as_float(classified.get("line"))
        # `#603`, Kalshi half. A GAME-LINE key names its fixture where the
        # ticker resolves to one. Props are untouched -- `prop_quote_key`
        # already names the PLAYER, which is a stronger identity than the game.
        # h2h is excluded for the same reason it is on the board side: its side
        # IS the club, so it cannot collide across fixtures.
        k_game = (
            _kalshi_game_token(row.get("ticker"), sport, games)
            if (not prop_player and market in _ROLE_KEYED_MARKETS)
            else None
        )
        primary_key = (
            prop_quote_key(sport, market, prop_player, side, line)
            if prop_player
            else quote_key(sport, market, side, line, k_game)
        )
        if primary_key is None:
            prop_unnamed += 1
            continue
        quotes.append(
            Quote(
                key=primary_key,
                source="kalshi",
                # Carried even when the key is bare, so the fan-in's
                # cross-game rejection can refuse a bare-key match that lands
                # on the wrong fixture. None means the ticker named no game we
                # could resolve, which is treated as unknown, not as "any".
                game=k_game,
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

        # THE OTHER SIDE OF A THRESHOLD MARKET, FROM ITS OWN QUOTED PRICE.
        #
        # Kalshi titles every total as an OVER ("Full Game: over 58.5 points
        # scored?"), so `classify_market` reads `side="over"` for all of them
        # and this adapter published only that leg. The board asks for both.
        # Measured on production 2026-08-27, `board_wanted_by_sport`:
        #
        #     ncaaf  board wants  ncaaf|totals|under|52.5
        #            kalshi has   ncaaf|totals|over|71.5      (over only, 400 quotes)
        #     nfl    board wants  nfl|totals|under|36
        #
        # Every `under` row the board carried was unmatchable against a venue
        # that does list that bet -- it lists it as the NO leg of the same
        # contract.
        #
        # PRICED FROM `no_*`, NEVER DERIVED FROM THE YES LEG. `kalshi_board_
        # join`'s header is the rule and it is not a style preference:
        # "`yes_ask_dollars` and `no_ask_dollars` are separately quoted; they do
        # not sum to 1 (the gap is the spread) ... deriving the Under from the
        # Over's price would erase the spread and invent an edge that is not
        # there." A `1 - p` here would manufacture EV on a money path.
        #
        # Threshold markets only. `h2h`'s NO leg is "the other team wins",
        # which needs the opponent's name to key and is refused above rather
        # than guessed; `spreads` is refused outright pending its sign
        # convention.
        mirrored = _MIRROR_SIDE.get(side)
        if mirrored and market != "h2h":
            mirror_probability = _kalshi_leg_probability(row, "no")
            if mirror_probability is None:
                no_price += 1
            else:
                mirror_key = (
                    prop_quote_key(sport, market, prop_player, mirrored, line)
                    if prop_player
                    # Same `k_game` as the primary leg: the mirror is the OTHER
                    # SIDE of the same contract on the same fixture, so keying
                    # it to a different game would be incoherent.
                    else quote_key(sport, market, mirrored, line, k_game)
                )
                quotes.append(
                    Quote(
                        key=mirror_key,
                        source="kalshi",
                        game=k_game,
                        sport=str(sport or ""),
                        market=market,
                        side=mirrored,
                        probability=mirror_probability,
                        american=probability_to_american(mirror_probability),
                        line=line,
                        fetched_at=fetched_at,
                        venue_ref=str(row.get("ticker") or "") or None,
                    )
                )
    return SourceOutcome(
        source="kalshi",
        status="ok" if quotes else "no_rows",
        # Carried on a SUCCESSFUL outcome too, for the reason
        # `_polymarket_ok_reason` already states: spreads refused while
        # moneylines and props price is the normal state until the sign
        # question is settled, and it must stay visible rather than vanish the
        # moment anything else succeeds.
        reason=_kalshi_ok_reason(spread_rows, h2h_keyed, h2h_unresolved, no_price, prop_unnamed)
        or (None if quotes else "no_kalshi_market_classified_to_this_sport"),
        quotes=quotes,
        age_seconds=max(0.0, time.time() - fetched_at),
    )


def _kalshi_ok_reason(spread_rows: int, h2h_keyed: int, h2h_unresolved: int, no_price: int = 0, prop_unnamed: int = 0) -> str | None:
    """What this adapter could not key, by name and count.

    `h2h_keyed` is reported alongside the refusals rather than only on failure:
    it is the number that says whether the moneyline re-key is reaching
    anything at all, and a counter that appears only when it fires cannot
    distinguish "ran and matched nothing" from "never ran".
    """
    parts = []
    if spread_rows:
        parts.append(f"spreads_refused:{spread_rows}")
    if h2h_unresolved:
        parts.append(f"h2h_team_unresolved:{h2h_unresolved}")
    if h2h_keyed:
        parts.append(f"h2h_keyed_by_team:{h2h_keyed}")
    if prop_unnamed:
        parts.append(f"prop_without_player:{prop_unnamed}")
    if no_price:
        # THE COUNTER THAT WOULD HAVE CAUGHT THIS. Every Kalshi quote was
        # published priceless for as long as the adapter read `yes_bid`, and
        # nothing said so: `quotes` was non-empty, so `status` read `ok`. A leg
        # we cannot price is now named and counted like every other refusal
        # here.
        parts.append(f"leg_without_price:{no_price}")
    return " ".join(parts) if parts else None


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
        # `#603`. THE SLUG NAMES BOTH CLUBS AND THE KEY WAS THROWING THEM AWAY.
        #
        # `parse_slug` returns `away`/`home` -- this venue's own tokens for the
        # two clubs -- and until now they were used only to pick the league and
        # then discarded. So every live game sharing a line collapsed onto one
        # key and one quote answered all of them: measured 2026-08-29,
        # `over 7.5 @ -400` on FOUR games at once, one worth ~2% and one already
        # won. See `quote_key`'s docstring for the full reading.
        #
        # ONE QUOTE PER SIDE, KEYED QUALIFIED WHERE THE SLUG NAMES BOTH CLUBS.
        #
        # The first version emitted TWO -- qualified and bare -- so a board row
        # that could not name its own teams would still match. That was the
        # wrong trade and the tests said so: it doubled every count in this
        # adapter's contract, and the coverage it bought is coverage we should
        # not want. If the BOARD cannot name the fixture, the fixture cannot be
        # verified, and matching anyway is exactly the cross-game pricing this
        # is fixing. Refusing there is the standing rule -- coverage may be
        # traded for certainty, a price may not.
        #
        # Where the slug does NOT name both clubs, the key stays bare and this
        # adapter behaves exactly as it did. `game` is still carried so the
        # fan-in can reject a bare-key match that lands on the wrong fixture.
        # ROLE-KEYED MARKETS ONLY, mirroring `_candidate_keys`. An h2h key
        # already names the game implicitly (its side is the CLUB), so
        # qualifying it adds a key nothing asks for. Totals and spreads name
        # nothing, which is where every one of the 26 shared quotes was.
        pm_game = (
            game_token(sport, parsed_slug.get("home"), parsed_slug.get("away"))
            if market in _ROLE_KEYED_MARKETS
            else None
        )
        for side, probability in sides:
            quotes.append(
                Quote(
                    key=quote_key(sport, market, side, line, pm_game),
                    source="polymarket_us",
                    sport=str(sport or ""),
                    market=market,
                    side=side,
                    probability=probability,
                    american=probability_to_american(probability),
                    line=line,
                    fetched_at=fetched_at,
                    venue_ref=str(row.get("slug") or "") or None,
                    game=pm_game,
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
    no_line = 0
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
        line = _oddsapi_quote_line(market, parsed_key, entry)
        if line is None and not str(market).strip().lower().startswith("h2h"):
            no_line += 1
        # `#603`, OddsAPI half -- and this source needs NO schedule at all.
        #
        # The shard's own key names the fixture outright:
        #   event_id=..|home_team=..|away_team=..|market=h2h|bookmaker=fanduel
        # `_parse_odds_history_key` is a generic `k=v` splitter, so both club
        # names are already in `parsed_key`. Kalshi needed `match_event_blob`
        # against a schedule because its ticker carries a run-together blob;
        # here the identity is handed over directly and was simply unused.
        #
        # SAME SCOPE AS THE OTHER TWO: role-keyed markets only. h2h keys by
        # ROLE here too (`side` comes from the shard), but a moneyline's side
        # is `home`/`away`/`Draw` rather than a club, so h2h on THIS source has
        # no implicit game -- and is deliberately still excluded, because the
        # board's h2h rows carry club and token keys that this source cannot
        # produce, and qualifying only one half of that pair would break the
        # match rather than sharpen it. Totals and spreads are where both
        # halves key by role and the collision is real.
        oa_game = (
            game_token(sport, parsed_key.get("home_team"), parsed_key.get("away_team"))
            if str(market).strip().lower() in _ROLE_KEYED_MARKETS
            else None
        )
        quotes.append(
            Quote(
                key=quote_key(sport, market, side, line, oa_game),
                source="oddsapi",
                sport=str(sport or ""),
                market=str(market),
                side=str(side),
                probability=None,
                american=int(american),
                line=line,
                fetched_at=fetched_at,
                # Carried even when the key is bare, so the fan-in can refuse a
                # bare-key match that lands on the wrong fixture.
                game=oa_game,
            )
        )
    dropped = []
    if no_side:
        dropped.append(f"no_side_in_key:{no_side}")
    if no_price:
        dropped.append(f"no_last_odds:{no_price}")
    if no_line:
        # NOT dropped -- these quotes are still emitted, exactly as before.
        # Reported because a lined market with no line ANYWHERE (neither the
        # key's `line=` nor the value's `last_line`) publishes a key that
        # cannot meet a board row, and this module's header is about counts
        # that look like coverage while carrying nothing. Naming it is what
        # separates "the shard has no line for these" from "the join is broken".
        dropped.append(f"lined_market_without_line:{no_line}")
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


def _oddsapi_quote_line(market: Any, parsed_key: Mapping[str, Any], entry: Mapping[str, Any]) -> float | None:
    """The line this quote is at -- from the KEY when it says, else the VALUE.

    THE COMMENT ABOVE THIS FUNCTION'S CALLER USED TO SAY "THE MARKET, SIDE AND
    LINE ARE IN THE KEY, NOT THE VALUE." Two thirds of that is right and the
    third is what made every lined OddsAPI quote unmatchable.

    Measured against the real shard shape recorded in that same comment:

        KEY   event_id=..|home_team=..|away_team=..|market=h2h|bookmaker=fanduel
        VALUE delta, delta_line, history, last_line, last_odds, ... previous_line

    There is no `line=` in the key. `american` was already read from the VALUE
    (`last_odds`); the line was not, so `parsed_key.get("line")` returned None
    for every spreads/totals row and `quote_key` built a LINELESS key. Observed
    on production 2026-08-27, `VENUE_REPRICE_KEYS sources_offered`:

        oddsapi: ['soccer|h2h|draw', 'soccer|spreads|real madrid',
                  'soccer|spreads|celta vigo', 'soccer|totals|over']

    `soccer|totals|over` is not a bet -- a total without a number cannot be one
    -- and it can never meet the board's `soccer|totals|over|2.5`. So OddsAPI
    published spreads and totals that were structurally incapable of matching,
    while its h2h quotes (legitimately lineless) matched fine and made the
    source look healthy.

    THIS CANNOT CREATE A WRONG-LINE MATCH, which is the property that matters
    on a money path. `quote_key`'s own docstring is the rule -- "a spread at
    -1.5 and the same spread at -2.5 are different bets, and collapsing them
    prices one at the other's number" -- and adding the real line ENFORCES it.
    Today these keys match nothing; afterwards they match only a board row at
    the SAME number. Strictly additive, and never a match at a different line.

    H2H IS LEFT ALONE, DELIBERATELY. A moneyline has no line, but these shards
    still carry `last_line` on some h2h entries (it is a movement field, not a
    market term). Reading it there would turn `soccer|h2h|draw` into
    `soccer|h2h|draw|0` and BREAK the one market family that currently matches
    -- a regression bought with a fix. The key's own `line=` still wins when a
    shard does carry one, so a sport whose keys are line-bearing is unchanged.
    """
    key_line = parsed_key.get("line")
    if key_line is not None:
        return key_line
    if str(market or "").strip().lower().startswith("h2h"):
        return None
    return _as_float(entry.get("last_line"))


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


# --------------------------------------------------------------------------
# ODDSAPI PLAYER PROPS -- the captured CSV, which nothing in the fan-in read
# --------------------------------------------------------------------------
#
# SOCCER'S UNMATCHED COUNT IS ALMOST ENTIRELY PLAYER PROPS, and until this
# adapter existed the honest conclusion was that they were unmatchable by
# nature: no exchange lists a soccer player prop, so `kalshi` and
# `polymarket_us` genuinely have nothing to offer. Measured 2026-08-27,
# `board_wanted_by_sport['soccer']` is EVERY key a player prop:
#
#     soccer|player_last_goal_scorer|yes      soccer|player_shots|over|1.5
#     soccer|player_first_goal_scorer|yes     soccer|player_shots_on_target|over|0.5
#     soccer|player_goal_scorer_anytime|yes   soccer|player_shots|over|5.5
#
# THAT CONCLUSION WAS WRONG ABOUT ONE SOURCE. `oddsapi` is in `SOURCES` and its
# adapter reads the `odds_history` shard -- game lines only, 44 soccer quotes at
# 26,886 seconds old on the reading above. Meanwhile the SAME vendor's player
# props are captured every pregame sweep to
# `soccer_source/<league>/props/<date>.csv`, and nothing in the fan-in opened
# them. Measured on the real 2026-08-27 ligue_1 capture: 2,720 rows, four books
# (draftkings 955, betrivers 764, fanduel 587, betmgm 414), and 647 of 1,529
# selections quoted by MORE THAN ONE BOOK.
#
# The vocabularies already agree exactly -- the CSV carries `market_key`, which
# IS the board's market token (`player_goal_scorer_anytime`, `player_shots`).
# Nothing needed translating; the file simply had no reader.


_YES_PRICED_PROP_MARKETS = frozenset({
    "player_goal_scorer_anytime",
    "player_first_goal_scorer",
    "player_last_goal_scorer",
    "player_to_receive_card",
    "player_to_receive_red_card",
})


def _prop_capture_probability(american: float | None) -> float | None:
    """Implied probability from american odds, vig included.

    NOT de-vigged, deliberately. Every other adapter here reports the price the
    venue actually shows and lets the board's own math handle the overround; a
    de-vigged number from one source and raw numbers from three others would be
    compared against each other by `select_quote` as though they were the same
    quantity.
    """
    if american is None:
        return None
    if american > 0:
        return 100.0 / (american + 100.0)
    if american < 0:
        return -american / (-american + 100.0)
    return None


def _soccer_prop_files(selected_date: str) -> list[Path]:
    """The freshest props capture per league, within the window.

    LEAGUES ARE DISCOVERED BY GLOB, not from a list. The canonical slugs live in
    `scripts/refresh_odds_sources._SOCCER_LEAGUE_SLUGS`, which is a script and
    not importable from here; copying it would be a second list to drift, and
    this module has already paid for that twice. Globbing also picks up a league
    the moment it starts being captured.

    ONE FILE PER LEAGUE -- the NEWEST inside the window, not every file in it.
    `build_soccer_picks._props_rows_near_date` scans a +-3/+10 day window
    because a capture is filed under the day it RAN, not the day the matches
    are played. That is right for finding rows; it is wrong for FRESHNESS,
    which is what this adapter exists to supply. Mixing a ten-day-old capture
    into today's quotes would launder a stale price as a current one, and
    `fetched_at` would then describe the newest file rather than the row.
    """
    from datetime import date as _date, timedelta as _timedelta

    try:
        base = _date.fromisoformat(str(selected_date or "")[:10])
    except ValueError:
        return []
    window = {(base + _timedelta(days=offset)).isoformat() for offset in range(-3, 11)}

    from syndicate.features.soccer.sources import _source_roots as _soccer_roots

    # ORDERED BY THE FILE'S OWN CAPTURE DATE FIRST, mtime only as a tie-break.
    # The stem IS the day the sweep ran, and it is the more trustworthy signal:
    # `_fetched_at` in this module already documents that "an artifact
    # republished unchanged gets a new mtime while its contents are hours old",
    # and the artifact-pull sweep touches files exactly that way. Ordering on
    # mtime alone also loses outright when two files land in the same
    # filesystem tick -- which is how a test caught this picking the STALE
    # capture over the fresh one.
    newest_by_league: dict[str, tuple[str, float, Path]] = {}
    for root in _soccer_roots():
        try:
            candidates = list(root.glob("*/props/*.csv"))
        except OSError:
            continue
        for path in candidates:
            if path.stem not in window:
                continue
            league = path.parent.parent.name
            try:
                mtime = float(path.stat().st_mtime)
            except OSError:
                continue
            held = newest_by_league.get(league)
            if held is None or (path.stem, mtime) > (held[0], held[1]):
                newest_by_league[league] = (path.stem, mtime, path)
    return [entry[2] for entry in sorted(newest_by_league.values(), key=lambda e: e[2].as_posix())]


def oddsapi_props_outcome(sport: str, selected_date: str) -> SourceOutcome:
    """Player-prop quotes from the captured OddsAPI CSVs.

    Soccer only for now, and the refusal is stated rather than silent: NFL's
    props live at a different path under a different schema
    (`nfl_source/oddsapi_player_props_<season>_wk<week>.csv`, keyed by week not
    date) and reach the board through `nfl/props.py` instead. Extending this to
    NFL is real work, not a path tweak.

    BEST PRICE PER SELECTION, ACROSS BOOKS. The capture is multi-book as of
    2026-08-27, so a selection can be quoted four times; the board renders one
    row, and the one it should get is the best available price. Higher american
    odds pay more on the same stake on both sides of zero, so `>` is correct
    without converting to decimal.
    """
    if str(sport or "").strip().lower() != "soccer":
        return SourceOutcome(
            source="oddsapi_props",
            status="no_rows",
            reason=f"player_prop_capture_not_wired_for_{sport}",
        )

    paths = _soccer_prop_files(selected_date)
    if not paths:
        return SourceOutcome(
            source="oddsapi_props",
            status="no_rows",
            reason="no_props_capture_within_window",
        )

    best: dict[str, Quote] = {}
    no_price = 0
    unnamed = 0
    unmapped: set[str] = set()
    newest = 0.0
    for path in paths:
        try:
            mtime = float(path.stat().st_mtime)
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, UnicodeDecodeError):
            continue
        newest = max(newest, mtime)
        for row in rows:
            market_key = str(row.get("market_key") or "").strip()
            player = str(row.get("player") or "").strip()
            if not market_key or not player:
                continue
            line = _as_float(row.get("line"))
            if market_key in _YES_PRICED_PROP_MARKETS:
                legs = [("yes", _as_float(row.get("over_price")), None)]
            else:
                legs = [
                    ("over", _as_float(row.get("over_price")), line),
                    ("under", _as_float(row.get("under_price")), line),
                ]
                if line is None:
                    # A threshold market with no number is not a bet, and
                    # `quote_key` would build one that no board row asks for.
                    unmapped.add(market_key)
                    continue
            for side, american, leg_line in legs:
                if american is None:
                    no_price += 1
                    continue
                key = prop_quote_key(sport, market_key, player, side, leg_line)
                if key is None:
                    unnamed += 1
                    continue
                held = best.get(key)
                if held is not None and held.american is not None and int(american) <= held.american:
                    continue
                best[key] = Quote(
                    key=key,
                    source="oddsapi_props",
                    sport="soccer",
                    market=market_key,
                    side=side,
                    probability=_prop_capture_probability(american),
                    american=int(american),
                    line=leg_line,
                    fetched_at=mtime,
                    venue_ref=str(row.get("event_id") or "") or None,
                )

    parts = []
    if no_price:
        parts.append(f"leg_without_price:{no_price}")
    if unmapped:
        parts.append(f"threshold_market_without_line:{len(unmapped)}")
    if unnamed:
        parts.append(f"player_unnameable:{unnamed}")
    quotes = list(best.values())
    return SourceOutcome(
        source="oddsapi_props",
        status="ok" if quotes else "no_rows",
        reason=" ".join(parts) or (None if quotes else "capture_had_no_priced_rows"),
        quotes=quotes,
        age_seconds=max(0.0, time.time() - newest) if newest else None,
    )
