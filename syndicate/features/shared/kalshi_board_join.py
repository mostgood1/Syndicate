"""Match a Kalshi market to a board row -- the join Stage D actually needs.

WHY THIS IS THE HARD PART. Kalshi and the board describe the same bet in two
unrelated vocabularies:

    Kalshi  ticker KXMLBKS-..., title "Andrew Abbott: 7+ strikeouts?",
            YES/NO, price in dollars
    board   market `pitcher_strikeouts`, player_name "Andrew Abbott",
            line 6.5, side Over/Under, price in American odds

Nothing lines up automatically, and `#505` is what a wrong join costs: the
settlement path matched on an id that changed whenever the price moved and
reported **4,560 `no_key_match` of 8,276**. So every mapping here is explicit,
every failure is named, and nothing is inferred from a pattern that merely
looks right.

--------------------------------------------------------------------------
"7+" IS OVER 6.5, AND OFF-BY-A-HALF WOULD MISMATCH EVERY SINGLE LINE
--------------------------------------------------------------------------

Kalshi states a threshold as "at least N". YES on "7+ strikeouts" pays when the
pitcher records 7 or more. The board states the same bet as a half-point line:
Over 6.5 pays at 7 or more. So

    Kalshi YES at threshold N  ==  board Over  (N - 0.5)
    Kalshi NO  at threshold N  ==  board Under (N - 0.5)

Matching "7+" against a line of 7.0 would find nothing, and -- worse -- matching
it against Over 7.5 would find a DIFFERENT BET and price it confidently. This is
the same shape as the cents/dollars error the probe caught: a convention
mismatch that produces plausible numbers rather than an obvious failure.

--------------------------------------------------------------------------
SIDES ARE NOT SYMMETRIC AND ARE NOT DERIVED FROM EACH OTHER
--------------------------------------------------------------------------

`yes_ask_dollars` and `no_ask_dollars` are separately quoted; they do not sum to
1 (the gap is the spread). Each board side is matched to its OWN Kalshi side and
priced from that side's ask -- deriving the Under from the Over's price would
erase the spread and invent an edge that is not there.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "normalize_person",
    "join_kalshi_to_board",
    "kalshi_price_resolver",
    "kalshi_ticker_resolver",
]

# "Andrew Abbott: 7+ strikeouts?" / "Andrew Abbott: 17+ Outs Recorded?"
_PROP_TITLE = re.compile(
    r"^\s*(?P<player>[^:]+?)\s*:\s*(?P<threshold>\d+)\s*\+\s*(?P<stat>.+?)\s*\??\s*$"
)

# THE CATALOGUE'S NAMES, re-exported rather than restated. Two modules with
# their own spelling of the same refusal is how a log line and a test end up
# disagreeing about what happened.
from syndicate.features.shared.kalshi_catalogue import (  # noqa: E402
    REASON_COMBINATORIAL,
    game_date_from_ticker,
    REASON_OUT_OF_SCOPE,
    REASON_UNMAPPED_SERIES,
    REASON_UNMAPPED_STAT,
    REASON_UNREADABLE_TITLE,
)

# Renamed from `market_closes_on_another_date`, which named the field the
# check USED rather than the fact it asserts -- and that field turned out to be
# the wrong one. A reason string that describes a mechanism goes stale the
# moment the mechanism is corrected; this one describes the finding.
REASON_WRONG_DATE = "market_is_for_another_date"
# Split out from the above: this one means the player, market and line all
# matched a board row and ONLY the date disagreed. Same refusal, opposite
# diagnosis -- one says Kalshi is quoting a slate we are not looking at, the
# other says our date field is wrong.
REASON_WOULD_MATCH_WRONG_DATE = "would_match_but_wrong_date"
REASON_NO_BOARD_ROW = "no_matching_board_row"
REASON_NO_PRICE = "no_kalshi_price"
# A market whose title does not say which game it is. Distinct from every other
# refusal: these are markets we CAN read and CANNOT yet place, so the number is
# the size of the game-lines gap rather than a defect.
REASON_NEEDS_EVENT_MAPPING = "needs_event_mapping"
# The game-line resolution outcomes, each counted by name. `unmatched` is the
# one that says which club-code ALIASES to add; `ambiguous` means two of our
# own games produce the same code pair (a doubleheader) and must never be
# guessed between. `disabled` means it WOULD have resolved and the flag is off,
# which is what makes the measurement readable before anything is priced.
REASON_EVENT_UNMATCHED = "event_not_on_our_board"
REASON_EVENT_AMBIGUOUS = "event_matches_two_games"
REASON_GAME_LINES_DISABLED = "game_lines_disabled"
# A team-named game line whose club we cannot place on either side of the
# resolved game. Its own reason because it is the LAST guard before a bet
# on the wrong team, and it must never be quietly folded into "no row".
REASON_TEAM_SIDE_UNRESOLVED = "team_side_unresolved"
# A market whose ticker carries no readable game date. Separated from every
# other refusal because it is the ONLY one that would previously have been
# silently mis-dated instead of refused.
REASON_UNDATABLE = "no_game_date_in_ticker"


def game_lines_enabled() -> bool:
    """Are game lines allowed to be PRICED? Absent means no.

    Off by default and read per call rather than at import, so the flag can be
    turned on without a code deploy once the resolution numbers justify it.
    """
    import os

    raw = str(os.environ.get("SYNDICATE_KALSHI_GAME_LINES") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _resolve_event(
    market: Mapping[str, Any], board_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Which of our games this game-line market belongs to."""
    from syndicate.features.shared.kalshi_catalogue import (
        event_blob_from_ticker,
        match_event_blob,
        sport_for_series,
    )

    blob = event_blob_from_ticker(market.get("ticker"))
    if not blob:
        return {"status": "no_match", "reason": "no_blob"}
    # The SPORT decides which club map resolves the codes -- `WSH` is the
    # Nationals in mlb and the Mystics in wnba, and resolving against the wrong
    # map is how a bet lands on the wrong league's game.
    sport = sport_for_series(market.get("series"))
    # DISTINCT GAMES ONLY. The board carries one row per market per game, so
    # feeding every row in would make an ordinary slate look ambiguous.
    seen: dict[str, dict[str, Any]] = {}
    for row in board_rows:
        event_id = str(row.get("event_id") or "")
        if event_id and event_id not in seen:
            seen[event_id] = {
                "event_id": event_id,
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
            }
    result = match_event_blob(blob, list(seen.values()), sport=sport)
    result.setdefault("sport", sport)
    return result


def _event_key(row: Mapping[str, Any]) -> tuple[str, str, float] | None:
    """A game line's identity: (event, market, line). No player involved.

    Canonicalised through `market_keys` like `_board_key`, so both indexes
    speak one vocabulary -- a second spelling here is how the two would drift.
    """
    from syndicate.features.shared.market_keys import canonical_market_key

    event_id = str(row.get("event_id") or "").strip()
    if not event_id:
        return None
    raw = str(row.get("market") or "").strip().lower()
    market = canonical_market_key(row.get("sport"), raw) or raw
    try:
        line = float(row.get("line"))
    except (TypeError, ValueError):
        # A moneyline has no line. Keyed at 0.0 so it is reachable rather than
        # dropped -- `h2h` rows genuinely carry no number.
        line = 0.0
    return (event_id, market, line)


def _side_for_team(
    team: Any, resolution: Mapping[str, Any], *, sport: Any = None
) -> str | None:
    """Is `team` the away or the home side of this resolved game? None if unsure.

    Through `team_aliases`, because Kalshi writes "Texas" where the board
    writes "TEX" -- and because a club resolver that disagrees with the one the
    event matcher used would put the two halves of the same join on different
    vocabularies.

    None is the important return. A market naming a club we cannot place is
    refused, never assigned positionally: guessing which side a name refers to
    is a bet on the wrong team half the time, at a price that looks confident.
    """
    try:
        from syndicate.features.shared.team_aliases import canonical_team
    except Exception:
        return None

    away = canonical_team(sport, resolution.get("away_team"))
    home = canonical_team(sport, resolution.get("home_team"))
    if not away or not home:
        return None

    named = canonical_team(sport, team)
    if named:
        if named == away and named != home:
            return "away"
        if named == home and named != away:
            return "home"
        return None

    # KALSHI NAMES THE CITY. Titles say "Texas wins by over 3.5 runs", and the
    # club map carries tri-codes and full names -- `canonical_team("mlb",
    # "Texas")` is None, so an exact resolver refuses every team-named game
    # line. Measured: `team_side_unresolved` on all of them.
    #
    # So a city or nickname is matched as a TOKEN SUBSET of the full club name
    # ("texas" within "texas rangers"), and only against the two clubs already
    # resolved for THIS game -- never against the league. That bound is what
    # keeps it safe: the candidate set is two, and both are known to be playing
    # each other.
    #
    # AMBIGUITY REFUSES. "Chicago" is inside both "chicago cubs" and "chicago
    # white sox", so on a Cubs-White Sox game it names neither side. Returning
    # a guess there is a bet on the wrong team half the time, at a price that
    # looks confident.
    wanted = set(str(team or "").strip().lower().split())
    if not wanted:
        return None
    hits = [
        side
        for side, full in (("away", away), ("home", home))
        if wanted and wanted.issubset(set(str(full).split()))
    ]
    return hits[0] if len(hits) == 1 else None


def normalize_person(value: Any) -> str:
    """Same normalisation MLB's own name matching uses (accents folded, cased
    down, whitespace collapsed) rather than a third private variant -- two
    normalisers that disagree on one name is a silent mismatch nobody sees."""
    text = " ".join(str(value or "").strip().lower().split())
    folded = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in folded if not unicodedata.combining(ch))
    # Punctuation varies between feeds ("Jr.", "O'Neill"); drop it rather than
    # let a period decide whether a bet matches.
    return re.sub(r"[^a-z0-9 ]", "", stripped).strip()


def _board_key(row: Mapping[str, Any]) -> tuple[str, str, float] | None:
    """The board row's identity, in the CANONICAL market vocabulary.

    Canonicalised here rather than matched against a list of aliases, because
    `market_keys` already knows that `pitcher_strikeouts` and `strikeouts` are
    the same market (`#224`). Both sides of the join therefore speak one
    vocabulary and the aliases live in the module that owns them -- an alias
    tuple in this file was a second place for the two to drift apart, which is
    the whole failure this join exists to avoid.

    Falls back to the raw name when the vocabulary does not know it: an
    unrecognised market keys on itself rather than being dropped, so a market we
    have no entry for can still match one Kalshi spells identically.
    """
    from syndicate.features.shared.market_keys import canonical_market_key

    raw = str(row.get("market") or "").strip().lower()
    market = canonical_market_key(row.get("sport"), raw) or raw
    player = normalize_person(row.get("player_name"))
    try:
        line = float(row.get("line"))
    except (TypeError, ValueError):
        return None
    if not market or not player:
        return None
    return (market, player, line)


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _match_key(match: Mapping[str, Any]) -> tuple[str, str, float, str] | None:
    """The identity the join matched on. Shared by both resolvers ON PURPOSE.

    Two resolvers keyed by two slightly different tuples would pair a row with
    one venue's price and another venue's contract -- a bet placed at a price
    that was never quoted for it.
    """
    try:
        line = float(match.get("line"))
    except (TypeError, ValueError):
        return None
    return (
        str(match.get("market") or "").strip().lower(),
        normalize_person(match.get("player_name")),
        line,
        str(match.get("board_side") or "").strip().lower(),
    )


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, float, str] | None:
    from syndicate.features.shared.market_keys import canonical_market_key

    try:
        line = float(row.get("line"))
    except (TypeError, ValueError):
        return None
    raw = str(row.get("market") or "").strip().lower()
    return (
        canonical_market_key(row.get("sport"), raw) or raw,
        normalize_person(row.get("player_name")),
        line,
        str(row.get("side") or "").strip().lower(),
    )


def kalshi_ticker_resolver(matches: Sequence[Mapping[str, Any]]):
    """Board row -> the Kalshi CONTRACT to buy, or None.

    Separate from the price resolver rather than folded into its return type: a
    function that returns either a float or a dict is a function every caller
    has to test the shape of, and the one caller that forgets places an order
    priced by a dict.

    THE TICKER IS THE THING MONEY IS SPENT ON. It is stamped at decision time
    and carried on the order, so the contract we priced and the contract we buy
    are recorded as the same object rather than re-derived later from a
    catalogue that may have moved.
    """
    index: dict[tuple[str, str, float, str], str] = {}
    for match in matches:
        key = _match_key(match)
        ticker = str(match.get("ticker") or "").strip()
        if key is None or not ticker:
            continue
        index[key] = ticker

    def resolve(row: Mapping[str, Any]) -> str | None:
        key = _row_key(row)
        return index.get(key) if key else None

    return resolve


def kalshi_price_resolver(matches: Sequence[Mapping[str, Any]]):
    """A resolver `venue_scope` can price from: board row -> Kalshi's own price.

    THE SEAM THAT MAKES PAPER2 REAL. Until now paper2 priced Kalshi from
    `quote.book_prices["kalshi"]`, which is OddsAPI's view -- game lines only,
    and the reason every coverage figure in this thread was about the aggregator
    rather than the venue. This prices from what Kalshi is actually quoting.

    Keyed on (market, player, line, side): the same identity the join matched
    on, so a resolver cannot pair a row with a price for a different bet. A
    lookup that is looser than the join would silently reintroduce exactly the
    mismatches the join refuses.
    """
    index: dict[tuple[str, str, float, str], float] = {}
    for match in matches:
        try:
            line = float(match.get("line"))
        except (TypeError, ValueError):
            continue
        price = match.get("kalshi_american")
        if price is None:
            continue
        key = (
            str(match.get("market") or "").strip().lower(),
            normalize_person(match.get("player_name")),
            line,
            str(match.get("board_side") or "").strip().lower(),
        )
        index[key] = float(price)

    def resolve(row: Mapping[str, Any]) -> float | None:
        try:
            line = float(row.get("line"))
        except (TypeError, ValueError):
            return None
        return index.get(
            (
                str(row.get("market") or "").strip().lower(),
                normalize_person(row.get("player_name")),
                line,
                str(row.get("side") or "").strip().lower(),
            )
        )

    resolve.market_count = len(index)  # type: ignore[attr-defined]
    return resolve


def _classify(market):
    from syndicate.features.shared.kalshi_catalogue import classify_market

    return classify_market(market)


def join_kalshi_to_board(
    kalshi_markets: Sequence[Mapping[str, Any]],
    board_rows: Sequence[Mapping[str, Any]],
    *,
    selected_date: str | None = None,
) -> dict[str, Any]:
    """Pair each Kalshi market with the board row for the same bet.

    Returns matches plus a named reason for every market that did not pair, so
    "Kalshi has nothing we bet" and "our join is broken" can never share a
    number -- which is the failure mode that produced `#505`.

    **`selected_date` KEEPS THE JOIN INSIDE ONE SLATE.** Kalshi's open markets
    span several days ahead; the board is built for one date. Measured
    2026-08-23T04:22Z: Kalshi was quoting tomorrow's MLB while the board had
    rolled to European soccer, so the join saw 132 markets and 421 rows with
    nothing in common -- correct, but only by luck of the vocabularies not
    overlapping. A starting pitcher with the same strikeout line on two
    different days WOULD have matched the wrong game and been priced
    confidently. Same class as `clv_join`'s arrow-of-time check: a pairing that
    looks well-formed and joins two unrelated instants.

    Absent, the check is skipped rather than guessed at -- a caller that does
    not know the slate date should get the old behaviour, not a silent filter.
    """
    by_key: dict[tuple[str, str, float], list[Mapping[str, Any]]] = {}
    # A SECOND INDEX, keyed by GAME rather than by player. A game line has no
    # player to key on, so `by_key`'s (market, player, line) cannot reach it --
    # the player slot would be empty for every row and every market.
    by_event: dict[tuple[str, str, float], list[Mapping[str, Any]]] = {}
    for row in board_rows:
        key = _board_key(row)
        if key is not None:
            by_key.setdefault(key, []).append(row)
        event_key = _event_key(row)
        if event_key is not None:
            by_event.setdefault(event_key, []).append(row)

    matches: list[dict[str, Any]] = []
    reasons: dict[str, int] = {}
    unmatched_samples: list[dict[str, Any]] = []

    def _refuse(reason: str) -> None:
        reasons[reason] = reasons.get(reason, 0) + 1

    wanted_date = str(selected_date or "").strip()[:10]
    for market in kalshi_markets:
        # THE CATALOGUE DECIDES WHAT THIS MARKET IS, for every sport at once.
        # This used to be a two-entry series table plus a private title parser,
        # which is a mapping that works for two series and stops at three.
        verdict = _classify(market)
        if verdict.get("status") != "ok":
            _refuse(str(verdict.get("reason")))
            continue

        if verdict.get("needs_event_identity"):
            # A player prop names a human, and a human plays one game a day, so
            # (player, market, line) is a complete identity. A total names
            # NEITHER team, so pairing it needs the game -- and the game is in
            # the ticker, which is where the game date turned out to be too:
            # `KXMLBHR-26AUG242140MINATH-...` is MIN at ATH.
            #
            # GATED OFF BY DEFAULT. The identity is resolved by matching
            # Kalshi's concatenated club codes against OUR schedule
            # (`match_event_blob`), and how often our codes agree with Kalshi's
            # is UNMEASURED -- `OAK` against `ATH` is a real possibility and
            # every such gap is an alias nobody has written yet. So the resolver
            # runs and REPORTS on every build, and the flag decides only whether
            # a resolved game may be priced. That way the measurement arrives
            # before the money does, which is the opposite of how tonight went.
            #
            # A total joined to the wrong game is a confidently-priced bet on
            # strangers, so `ambiguous` and `no_match` are refused by name and
            # never softened into a best guess.
            resolution = _resolve_event(market, board_rows)
            status = str(resolution.get("status") or "")
            if status == "no_match" and len(unmatched_samples) < 8:
                # THE ALIAS LIST, WRITTEN FROM DATA. `event_not_on_our_board`
                # is a count; it cannot say WHICH code we failed to recognise,
                # and guessing at club spellings is how a bet lands on the
                # wrong game. This prints Kalshi's blob beside the blobs our
                # own board offered for the same date, so the missing alias is
                # readable rather than inferred. Bounded at 8 -- enough to name
                # the pattern, not enough to flood the log money moves through.
                unmatched_samples.append(
                    {
                        "kalshi": resolution.get("blob"),
                        "ticker": market.get("ticker"),
                        "sport": resolution.get("sport"),
                    }
                )
            if status != "ok":
                _refuse(
                    REASON_EVENT_AMBIGUOUS
                    if status == "ambiguous"
                    else REASON_EVENT_UNMATCHED
                )
                continue
            if not game_lines_enabled():
                # RESOLVED, and still not priced. Counted separately from the
                # unresolved ones so the log answers "would this work?" while
                # the answer is still free.
                _refuse(REASON_GAME_LINES_DISABLED)
                continue

            # THE PRICING PATH. Until now this fell through to
            # `needs_event_mapping` even when the event HAD resolved, so 60
            # game lines a build were identified and then dropped -- the flag
            # bought measurement and nothing else.
            if wanted_date:
                game_date = game_date_from_ticker(market.get("ticker"))
                if game_date is None:
                    _refuse(REASON_UNDATABLE)
                    continue
                if game_date != wanted_date:
                    _refuse(REASON_WRONG_DATE)
                    continue

            game_rows = by_event.get(
                (str(resolution.get("event_id") or ""), verdict["market"], verdict["line"])
            )
            if not game_rows:
                _refuse(REASON_NO_BOARD_ROW)
                continue

            yes_price = _as_float(market.get("yes_american"))
            no_price = _as_float(market.get("no_american"))
            if yes_price is None and no_price is None:
                _refuse(REASON_NO_PRICE)
                continue

            # WHICH SIDE IS KALSHI'S `YES`? Two different questions depending
            # on the grammar, and getting it wrong is a real bet on the
            # opposite outcome at a confident price.
            subject = verdict.get("subject")
            for row in game_rows:
                board_side = str(row.get("side") or "").strip().lower()
                if subject:
                    # A TEAM-NAMED market: "Texas wins by over 3.5 runs" is YES
                    # on Texas. The board row's side is `away`/`home`, so the
                    # named club has to be resolved against the event's own two
                    # clubs -- never positionally, and never by assuming the
                    # first team named is the away side.
                    named = _side_for_team(
                        subject,
                        resolution,
                        sport=verdict.get("sport") or resolution.get("sport"),
                    )
                    if named is None:
                        # We cannot say which club this names. REFUSED: a coin
                        # flip between two sides of a real game is a bet on the
                        # wrong team half the time.
                        _refuse(REASON_TEAM_SIDE_UNRESOLVED)
                        continue
                    if board_side not in {"away", "home"}:
                        _refuse("unmapped_board_side")
                        continue
                    # YES pays when the NAMED club covers. So the board row for
                    # that club takes the yes quote, and the other side takes no.
                    kalshi_side = "yes" if board_side == named else "no"
                else:
                    # A TOTAL names no club, so the side is the direction the
                    # title already gave us.
                    if board_side in {"over", "o"}:
                        kalshi_side = "yes" if verdict.get("side") == "over" else "no"
                    elif board_side in {"under", "u"}:
                        kalshi_side = "no" if verdict.get("side") == "over" else "yes"
                    else:
                        _refuse("unmapped_board_side")
                        continue

                kalshi_price = yes_price if kalshi_side == "yes" else no_price
                if kalshi_price is None:
                    _refuse(REASON_NO_PRICE)
                    continue
                matches.append(
                    {
                        "ticker": market.get("ticker"),
                        "series": verdict.get("series"),
                        "market": verdict["market"],
                        "player_name": None,
                        "team": subject,
                        "line": verdict["line"],
                        "board_side": board_side,
                        "kalshi_side": kalshi_side,
                        "kalshi_american": kalshi_price,
                        "kalshi_probability": market.get(
                            "yes_probability" if kalshi_side == "yes" else "no_probability"
                        ),
                        "board_price": row.get("quote", {}).get("price")
                        if isinstance(row.get("quote"), Mapping)
                        else None,
                        "board_event_id": row.get("event_id"),
                        "model_edge_pct": row.get("model_edge_pct"),
                        "game_line": True,
                    }
                )
            continue

        series = verdict.get("series")
        board_market = verdict["market"]
        line = verdict["line"]
        player_key = normalize_person(verdict.get("subject"))
        parsed = {"player_name": verdict.get("subject"), "player_key": player_key}
        rows = by_key.get((board_market, player_key, line))

        # THE DATE CHECK RUNS AFTER THE KEY LOOKUP, not before it. Ordering it
        # first is cheaper and it is what this module shipped with -- and it
        # cost a whole diagnostic cycle: `market_closes_on_another_date: 213`
        # swallowed every market before anything could report whether the NAMES
        # agreed, so one wrong assumption hid another. Refusing late means one
        # run answers both questions: `would_match_but_wrong_date` says the key
        # is right and only the calendar disagrees, while `no_matching_board_row`
        # says the key is still wrong.
        if wanted_date:
            # THE GAME DATE COMES FROM THE TICKER, NOT FROM `close_time`.
            # `close_time` is a SETTLEMENT deadline days after the event --
            # `KXMLBHR-26AUG242140MINATH-...` closes 2026-08-28 for a game on
            # the 24th -- so comparing it to the board's slate date refused
            # every market on every build: `matched=0 reasons={
            # 'market_closes_on_another_date': 190}` for hours, straight
            # through a live slate. The DATE_FIELDS probe was printing the
            # disproof the whole time; nothing had read it.
            game_date = game_date_from_ticker(market.get("ticker"))
            if game_date is None:
                # NO FALLBACK TO `close_time`. Falling back would reinstate the
                # bug this replaces, and it would do it silently on exactly the
                # markets whose identity we understand least. An undatable
                # market gets its own reason so the count is visible.
                _refuse(REASON_UNDATABLE)
                continue
            if game_date != wanted_date:
                _refuse(REASON_WOULD_MATCH_WRONG_DATE if rows else REASON_WRONG_DATE)
                continue

        if not rows:
            _refuse(REASON_NO_BOARD_ROW)
            continue

        yes_price = _as_float(market.get("yes_american"))
        no_price = _as_float(market.get("no_american"))
        if yes_price is None and no_price is None:
            _refuse(REASON_NO_PRICE)
            continue

        for row in rows:
            side = str(row.get("side") or "").strip().lower()
            # EACH SIDE FROM ITS OWN QUOTE. See the module docstring -- deriving
            # one from the other erases the spread and invents edge.
            if side in {"over", "o"}:
                kalshi_price = yes_price
                kalshi_side = "yes"
            elif side in {"under", "u"}:
                kalshi_price = no_price
                kalshi_side = "no"
            else:
                _refuse("unmapped_board_side")
                continue
            if kalshi_price is None:
                _refuse(REASON_NO_PRICE)
                continue
            matches.append(
                {
                    "ticker": market.get("ticker"),
                    "series": series,
                    "market": board_market,
                    "player_name": parsed["player_name"],
                    "line": line,
                    "board_side": side,
                    "kalshi_side": kalshi_side,
                    "kalshi_american": kalshi_price,
                    "kalshi_probability": market.get(
                        "yes_probability" if kalshi_side == "yes" else "no_probability"
                    ),
                    "board_price": row.get("quote", {}).get("price")
                    if isinstance(row.get("quote"), Mapping)
                    else None,
                    "board_event_id": row.get("event_id"),
                    "model_edge_pct": row.get("model_edge_pct"),
                }
            )

    # SAMPLES FROM BOTH SIDES, so a zero-match join says WHICH FIELD disagrees.
    # `no_matching_board_row: 132` alone is exactly the `#505` report -- a count
    # of failures with no way to see the mismatch. Keys from each side side by
    # side is what turns that into a fixable observation.
    kalshi_keys: list[str] = []
    for market in kalshi_markets:
        verdict = _classify(market)
        if verdict.get("status") != "ok":
            continue
        # Built by the SAME code path the join uses, so the sample cannot say
        # one thing while the join does another -- which would make this line
        # actively misleading rather than merely unhelpful.
        kalshi_keys.append(
            f"{verdict['market']}|{normalize_person(verdict.get('subject'))}|{verdict['line']}"
        )
        if len(kalshi_keys) >= 6:
            break
    board_keys = [f"{k[0]}|{k[1]}|{k[2]}" for k in list(by_key)[:5]]
    # The board's market vocabulary, counted -- if the market the catalogue
    # resolved is not in it, the mapping is simply wrong and that is visible at
    # a glance.
    board_markets: dict[str, int] = {}
    for row in board_rows:
        name = str(row.get("market") or "").strip().lower()
        if name:
            board_markets[name] = board_markets.get(name, 0) + 1

    return {
        "kalshi_markets": len(kalshi_markets),
        "board_rows": len(board_rows),
        "matched": len(matches),
        "reasons": dict(sorted(reasons.items())),
        "kalshi_key_sample": kalshi_keys,
        "board_key_sample": board_keys,
        "board_market_vocabulary": dict(
            sorted(board_markets.items(), key=lambda kv: -kv[1])[:12]
        ),
        # Kalshi blobs we could not pair, beside the blobs OUR board offered.
        # The count alone cannot say which club spelling is missing, and a club
        # alias guessed rather than read is how a bet reaches the wrong game.
        "unmatched_events": unmatched_samples,
        "board_event_sample": sorted(
            {
                f"{str(r.get('away_team') or '?')}{str(r.get('home_team') or '?')}"
                for r in board_rows
                if r.get("away_team") or r.get("home_team")
            }
        )[:12],
        "matches": matches,
    }
