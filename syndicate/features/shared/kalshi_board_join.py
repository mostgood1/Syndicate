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

import datetime as _dt
import os
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
# The horizon a soccer fixture may sit ahead of the slate being committed.
# NOT A NEW NUMBER: `polymarket_board_join._FORWARD_HORIZON_DAYS` is 14 and
# fixed this identical defect for this identical sport. Two joins that must
# agree about which fixtures are reachable should not disagree by a constant.
_SOCCER_FORWARD_HORIZON_DAYS = 14


def _soccer_forward_dates_enabled() -> bool:
    """Kill switch for the soccer forward-date widening. ON by default.

    Present so the widening can be turned off without a code deploy if a
    production reading ever shows a soccer market pairing to the wrong
    fixture -- the one failure this change could cause. `off` restores the
    exact-date behaviour for every sport.
    """
    return str(
        os.environ.get("SYNDICATE_KALSHI_SOCCER_FORWARD_DATES") or ""
    ).strip().lower() not in {"0", "off", "false", "no"}


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
# A board row sitting at one of the two lines a spread market can name, but
# wearing the OTHER club. Counted by name rather than skipped: this is how many
# Kalshi spreads describe a margin our board never wrote a row for, and a silent
# `continue` here is exactly the shape `learnings.md` forbids.
REASON_SPREAD_ORIENTATION = "spread_line_orientation_mismatch"
# A market whose ticker carries no readable game date. Separated from every
# other refusal because it is the ONLY one that would previously have been
# silently mis-dated instead of refused.
REASON_UNDATABLE = "no_game_date_in_ticker"

# The board row is for part of a game and this venue market is for a different
# part -- or for a part we cannot name. NOT a match, and NOT silent.
#
# `#600`-adjacent in shape but a different defect: `_match_key`/`_row_key` were
# five-tuples with no `segment`, so a board row for "under 2.5, first 3 innings"
# matched Kalshi's FULL-GAME `KXMLBTOTAL` on game + market + line + side, and
# nothing checked that the contract covers a different portion of the game.
# Measured 2026-08-28: five orders, $7.08, all segment bets on full-game
# tickets. See `kalshi_catalogue._SERIES_SEGMENT` for the list.
REASON_SEGMENT_MISMATCH = "segment_has_no_matching_series"

# How many DISTINCT SERIES get a sample title. One per series, so the bound is
# on series rather than on samples.
#
# It was 10, and the noisiest families reached it before the quiet ones were
# named: on 2026-08-25 `by_series` reported eight soccer series as
# `unreadable_title` (413 markets) while not one soccer TITLE appeared in the
# sample. The grammar gap could be counted and not read, which cost a cycle.
# Named rather than written twice: the old literal lived here and in a test,
# and a bound nobody can find is a bound nobody revisits.
MAX_UNREADABLE_SAMPLES = 40


def game_lines_enabled() -> bool:
    """Are game lines allowed to be PRICED? Absent means no.

    Off by default and read per call rather than at import, so the flag can be
    turned on without a code deploy once the resolution numbers justify it.
    """
    import os

    raw = str(os.environ.get("SYNDICATE_KALSHI_GAME_LINES") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


# Market-type tokens a soccer series ticker ends with. Longest first, because
# `KXLALIGA1HSPREAD` must not be cut at `SPREAD` and leave `KXLALIGA1H`.
_SERIES_MARKET_SUFFIXES = (
    "1HSPREAD", "1HTOTAL", "1HWINNER", "2HSPREAD", "2HTOTAL", "2HWINNER",
    "SPREAD", "TOTAL", "WINNER", "GAME", "1H", "2H",
)


def _series_family(series: Any) -> str:
    """`KXLALIGATOTAL` -> `KXLALIGA`. The COMPETITION, not the market type.

    This is the scope a Kalshi club code is unique within, and scoping is not
    cosmetic: measured 2026-09-01, `PAR` is Paris FC in Ligue 1 and Parma in
    Serie A; `LEV` Levante or Leverkusen; `GEN` Genoa or Genk; `TOR` Torino or
    Toronto. A soccer-wide code map bets on the wrong club.

    `KXBUNDESLIGA2GAME` -> `KXBUNDESLIGA2`, which is CORRECT and deliberate:
    Bundesliga 2 is a different competition with its own club set, and folding
    it into `KXBUNDESLIGA` would recreate exactly the collision this prevents.
    """
    text = str(series or "").strip().upper()
    for suffix in _SERIES_MARKET_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


# "Real Madrid wins" -> "Real Madrid". Kalshi's own moneyline wording, the same
# one `kalshi_catalogue._MONEYLINE` reads; matched here only to harvest the
# NAME beside the ticker's code.
_WINS_TITLE = re.compile(r"^\s*(?P<team>.+?)\s+wins\s*\??\s*$", re.IGNORECASE)


def build_club_code_names(
    markets: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    """`{series_family: {CODE: "Club Name"}}`, read from Kalshi's own markets.

    THE VENUE PUBLISHES THIS PAIRING AND WE WERE NOT READING IT. Every
    `KX<LEAGUE>GAME` event lists one market per club whose ticker SUFFIX is the
    club code and whose TITLE is "<Club> wins":

        KXLALIGAGAME-26SEP15ELCRMA-RMA   "Real Madrid wins"
        KXLIGUE1GAME-26SEP13STBPSG-STB   "Stade Brest 29 wins"

    So the code -> name map is DERIVED, never guessed and never hand-listed.
    Measured 2026-09-01 across 9 live soccer series: 176 clubs, and using the
    name as a second key lifts club resolution from **63% to 82%** against our
    existing alias map.

    DERIVED PER BUILD RATHER THAN STORED. A static table of 176 clubs is a
    snapshot that rots on promotion, relegation and every new Kalshi series,
    and nothing would report the rot. This reads the same market list the join
    is already iterating, so it is always the venue's current answer.

    SCOPED BY SERIES FAMILY -- see `_series_family` for the four measured code
    collisions that make a single soccer-wide map unsafe.

    A code whose league disagrees with itself is DROPPED, not resolved by
    order: two clubs claiming one code inside one competition is the ambiguity
    this module refuses everywhere else.
    """
    found: dict[str, dict[str, set[str]]] = {}
    for market in markets or ():
        if not isinstance(market, Mapping):
            continue
        ticker = str(market.get("ticker") or "").strip().upper()
        if not ticker or "-" not in ticker:
            continue
        code = ticker.rsplit("-", 1)[-1].strip()
        # `TIE` is the draw leg and names no club.
        if not code or code == "TIE" or not code.isalnum():
            continue
        title_match = _WINS_TITLE.match(str(market.get("title") or ""))
        if not title_match:
            continue
        name = title_match.group("team").strip()
        if not name:
            continue
        family = _series_family(market.get("series"))
        if not family:
            continue
        found.setdefault(family, {}).setdefault(code, set()).add(name)
    out: dict[str, dict[str, str]] = {}
    for family, codes in found.items():
        resolved = {
            code: next(iter(names))
            for code, names in codes.items()
            if len(names) == 1
        }
        if resolved:
            out[family] = resolved
    return out


def _resolve_event(
    market: Mapping[str, Any],
    board_rows: Sequence[Mapping[str, Any]],
    code_names: Mapping[str, Mapping[str, str]] | None = None,
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
    # Kalshi's own code -> name pairing for THIS COMPETITION only. Absent for
    # every sport that does not supply one, which leaves those resolutions
    # byte-identical to before.
    family_names = (code_names or {}).get(_series_family(market.get("series"))) if code_names else None
    result = match_event_blob(
        blob, list(seen.values()), sport=sport, code_names=family_names
    )
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


def _key_line(value: Any) -> tuple[bool, float | None]:
    """A line for the resolver key: `(ok, line)`.

    **A MONEYLINE HAS NO LINE, AND REFUSING IT MADE KALSHI h2h UNPLACEABLE.**

    MEASURED 2026-08-25 14:57:34Z, on a live Kalshi order:

        h2h · Texas Rangers @ Chicago White Sox  +108
        OrderBuildError: no_live_price: None

    The trailing `None` is `request.venue_ticker`. Both key functions did
    `float(match.get("line"))` inside a `try` and returned None on TypeError, so
    an h2h -- whose line legitimately IS None -- was never indexed, no ticker was
    ever stamped, and `_kalshi_price_for` refused for want of one. Not a data
    gap: the market was matched and priced, and only the key could not hold it.

    None is now a VALUE in the key rather than a refusal, which is safe here for
    a reason that was not true before `#547`: the tuple leads with `event_id`, so
    `(evt, "h2h", "", None, "home")` names exactly one bet. Without the game it
    would have been the collision that stamped a BAL@STL slug on a CIN@SF row.

    An UNPARSEABLE line is still a refusal, and that distinction is the point: a
    market that has no line and a market whose line we could not read are
    different facts, and only the first is safe to key.

    Returns `(ok, line)`. `ok=False` means the caller must refuse -- NOT a NaN
    sentinel, which was the first attempt here and is wrong: a module-level
    `float("nan")` is ONE object, and a dict lookup compares by identity before
    equality, so two rows with unreadable lines would have matched each other.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return (True, None)
    try:
        return (True, float(value))
    except (TypeError, ValueError):
        return (False, None)


def _match_key(match: Mapping[str, Any]) -> tuple[str, str, str, float, str, str] | None:
    """The identity the join matched on. Shared by both resolvers ON PURPOSE.

    Two resolvers keyed by two slightly different tuples would pair a row with
    one venue's price and another venue's contract -- a bet placed at a price
    that was never quoted for it.

    **THE GAME IS IN THE KEY.** It was not, and Polymarket -- which had copied
    this module's shape -- stamped a BAL@STL slug onto a CIN@SF position and a
    PIT@SD slug onto a TEX@CWS one (measured 2026-08-25 14:57:34Z). Without
    `board_event_id`, `("totals", "", 8.5, "over")` is one key for every 8.5
    total on the slate and the index keeps whichever game was written last.

    Kalshi has not yet produced that failure for two reasons, NEITHER of which
    is a guard: its board join currently supplies only player props, whose
    `player_name` happens to identify a game; and the `float(line)` below
    returns None for an h2h with no line, so moneylines are not indexed at all.
    The 171 game series registered on 2026-08-25 would have removed both
    accidents at once.

    **THAT PARAGRAPH IS STALE AND THE ACCIDENT IT RELIED ON IS GONE.** This join
    supplies game TOTALS now, and on 2026-08-28 the same class of omission --
    `segment` missing from the key rather than the game -- put five orders on
    full-game contracts that were priced as three- and five-inning bets, $7.08
    of real money. `segment` is now in both tuples. Left in place as the record
    of a reassurance that expired without anyone noticing, which is the reason
    the correction sits here rather than replacing it.

    A record with no event id returns None and is never indexed -- an empty
    string would rebuild the same collision under a different spelling, and not
    indexed means no order, which is the direction that fails safe.

    **THE MARKET NAME IS TAKEN VERBATIM HERE AND CANONICALISED IN `_row_key`.**
    That asymmetry is deliberate and load-bearing: a match's `market` is
    `verdict["market"]`, which the join has already canonicalised, while a board
    row carries whatever the board spells it (`pitcher_strikeouts` where the
    canonical key is `strikeouts`). Canonicalising twice would be harmless;
    canonicalising NEITHER side would pair `pitcher_strikeouts` with nothing.
    Stated because a fixture built with a board-shaped market name resolves to
    None here and looks like a key bug rather than a fixture that does not
    match what the join emits.
    """
    from syndicate.features.shared.kalshi_catalogue import segment_for_series

    event_id = str(match.get("board_event_id") or "").strip()
    if not event_id:
        return None
    ok, line = _key_line(match.get("line"))
    if not ok:
        return None
    # WHICH PORTION OF THE GAME THIS CONTRACT SETTLES ON. An unrecognised series
    # returns None and is NOT indexed -- the same fail-safe direction the
    # missing-event-id branch above takes, and for the same reason: not indexed
    # means no order, which is the direction that cannot lose money.
    segment = segment_for_series(match.get("series"))
    if segment is None:
        return None
    return (
        event_id,
        str(match.get("market") or "").strip().lower(),
        normalize_person(match.get("player_name")),
        line,
        str(match.get("board_side") or "").strip().lower(),
        segment,
    )


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, str, float, str, str] | None:
    """The board row's side of `_match_key`. The two must stay one shape.

    A board row's game is `event_id`; a match carries the same value under
    `board_event_id` because that is what the join copied off the row.
    """
    from syndicate.features.shared.market_keys import canonical_market_key

    event_id = str(row.get("event_id") or "").strip()
    if not event_id:
        return None
    ok, line = _key_line(row.get("line"))
    if not ok:
        return None
    raw = str(row.get("market") or "").strip().lower()
    # ABSENT MEANS FULL GAME, which is what every board row without an explicit
    # segment has always meant. Stated rather than implied, because the whole
    # defect was an implied value nobody checked.
    from syndicate.features.shared.kalshi_catalogue import segment_for_board_row

    segment = segment_for_board_row(row)
    return (
        event_id,
        canonical_market_key(row.get("sport"), raw) or raw,
        normalize_person(row.get("player_name")),
        line,
        str(row.get("side") or "").strip().lower(),
        segment,
    )


def _segments_agree(row: Mapping[str, Any], verdict: Mapping[str, Any]) -> bool:
    """Does this board row cover the same portion of the game as this contract?

    The board row's `segment` is what we intend to BET; the series' segment is
    what the contract SETTLES on. They must be the same bet.

    `verdict["series"]` rather than `market["series"]`: `classify_market`
    already normalised it (`.strip().upper()`), and it is the value the record
    carries. An earlier version of this fix stamped `market.get("series")` into
    the record as a SECOND key of the same name -- redundant, raw rather than
    normalised, and it won only by being last in the dict literal.

    An unrecognised series returns None from `segment_for_series` and is refused
    here. That is narrower than it looks: unmapped defaults to `full`, so only a
    series carrying a segment MARKER we cannot map reaches None.
    """
    from syndicate.features.shared.kalshi_catalogue import (
        segment_for_board_row,
        segment_for_series,
    )

    contract = segment_for_series(verdict.get("series"))
    if contract is None:
        return False
    return segment_for_board_row(row) == contract


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

    KEYED BY `_match_key` / `_row_key`, THE SHARED FUNCTIONS -- not by a copy.

    This built its key INLINE while the ticker resolver called `_match_key`,
    and the docstring here claimed they were "the same identity the join
    matched on". They were the same tuple only for as long as nobody edited one
    of them. Adding the game to `_match_key` moved the ticker resolver and left
    this behind, and a test asking both for the same row got a CIN@SF contract
    priced at BAL@STL's number -- which is precisely the failure `_match_key`'s
    own docstring says the sharing exists to prevent, produced by the sharing
    not actually being shared.

    One function, two callers. The `canonical_market_key` normalisation on the
    row side comes along with it, which this copy also lacked.
    """
    index: dict[tuple[str, str, str, float, str], float] = {}
    for match in matches:
        key = _match_key(match)
        price = match.get("kalshi_american")
        if key is None or price is None:
            continue
        index[key] = float(price)

    def resolve(row: Mapping[str, Any]) -> float | None:
        key = _row_key(row)
        return index.get(key) if key else None

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
    from syndicate.features.shared.kalshi_catalogue import GRAMMAR_TEAM_SPREAD

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
    # Blobs already sampled, so the bounded sample spends its slots on distinct
    # club codes rather than on repeat markets from one game.
    unmatched_blobs: set[str] = set()
    # Titles the catalogue could not read, one per series -- the grammar work
    # list. Series already sampled, for the same reason blobs are deduplicated.
    unreadable_titles: list[dict[str, Any]] = []
    unreadable_series: set[str] = set()
    # Complete, not sampled: which series refuse and how many each.
    unreadable_by_series: dict[str, int] = {}

    def _refuse(reason: str) -> None:
        reasons[reason] = reasons.get(reason, 0) + 1

    wanted_date = str(selected_date or "").strip()[:10]

    # ----------------------------------------------------------------------
    # SOCCER DATES BY FIXTURE; THE BOARD DATES BY SLATE.
    # ----------------------------------------------------------------------
    #
    # `wanted_date` is ONE date -- the slate being committed, i.e. today -- and
    # every market whose ticker names another game date refuses
    # `market_is_for_another_date`. For a same-day sport that is exactly right.
    #
    # SOCCER IS NEVER SAME-DAY, so for soccer that check can only ever return
    # zero. MEASURED 2026-09-01T19:51:44Z from this join's own `BY_GAME_DATE`
    # and `TRIM_BY_SPORT` lines, on a build with `demand={'soccer': 1541}` and
    # `kept_by_sport={'soccer': 918}`:
    #
    #     soccer markets dated 2026-09-01 (today) ...........   0
    #     soccer markets dated 2026-09-02 .. 2026-09-15 ...... 918
    #       KXMLSTOTAL, KXMLSSPREAD, KXLALIGA{GAME,SPREAD,TOTAL},
    #       KXLIGUE1{...}, KXSERIEA{...}, KXBUNDESLIGA{...},
    #       KXEREDIVISIE{...}, KXBELGIANPLGAME, KXBUNDESLIGA2GAME
    #
    # 918 markets fetched, trimmed INTO the working set on soccer's own demand,
    # and then refused by a date test -- while `market_is_for_another_date` was
    # the largest refusal in the join at 3,495 of 6,000.
    #
    # THE TITLE PARSER IS NOT THE BLOCKER AND MUST NOT BE "FIXED" AGAIN.
    # `unreadable_title` is 18 of 6,000 and every sampled family is an NCAAF
    # season award. `_SOCCER_DRAW`/`_SOCCER_BTTS`/`_SOCCER_TOTAL` and the
    # `more than`/`less than` spread wording have all read production titles
    # since 2026-08-28.
    #
    # SOCCER ONLY, AND THAT GATE IS THE WHOLE SAFETY ARGUMENT -- copied
    # deliberately from `polymarket_board_join`, which fixed this same defect
    # for this same sport and states it: MLB plays the SAME FIXTURE on
    # consecutive days, so widening there could price tonight's game off
    # tomorrow's market, which is a worse bug than the one being fixed. Soccer
    # club pairs do not repeat inside the horizon.
    #
    # FORWARD ONLY. A market dated BEFORE the slate is a settled or in-progress
    # contract; matching one would price a live board row off a resolved market.
    #
    # NOTHING HERE RELAXES FIXTURE IDENTITY. The widened markets go through the
    # same `_resolve_event` club-blob match, and its `event_matches_two_games`
    # refusal is the backstop if a club pair ever does repeat in the window.
    #
    # THE HORIZON IS THE SIBLING JOIN'S, not a new number:
    # `polymarket_board_join._FORWARD_HORIZON_DAYS = 14`, and Kalshi's soccer
    # set occupies exactly that span (09-02..09-15 on the measured build).
    _forward_horizon_date = ""
    if wanted_date:
        try:
            _forward_horizon_date = (
                _dt.date.fromisoformat(wanted_date)
                + _dt.timedelta(days=_SOCCER_FORWARD_HORIZON_DAYS)
            ).isoformat()
        except ValueError:
            _forward_horizon_date = ""

    # KALSHI'S OWN CLUB CODE -> NAME PAIRING, derived once per build from the
    # market list already in hand. See `build_club_code_names`: the venue
    # publishes "<Club> wins" beside the ticker whose suffix IS the code, so
    # this is read rather than guessed, and it is scoped per competition
    # because four measured codes mean different clubs in different leagues.
    club_code_names = build_club_code_names(kalshi_markets)

    # Bound ONCE here rather than per market: this file imports
    # `sport_for_series` function-locally everywhere else, and `_date_ok` runs
    # once per market over a 6,000-market working set.
    from syndicate.features.shared.kalshi_catalogue import (
        sport_for_series as _sport_for_series,
    )

    def _date_ok(game_date: str, market: Mapping[str, Any]) -> bool:
        """Does this market's game date serve the slate being committed?

        Exact for every sport. Soccer additionally accepts a FUTURE fixture
        inside the horizon, because soccer's board rows carry the slate date
        while its markets carry the fixture date.
        """
        if game_date == wanted_date:
            return True
        if not _soccer_forward_dates_enabled() or not _forward_horizon_date:
            return False
        if _sport_for_series(market.get("series")) != "soccer":
            return False
        return bool(wanted_date < game_date <= _forward_horizon_date)

    for market in kalshi_markets:
        # THE CATALOGUE DECIDES WHAT THIS MARKET IS, for every sport at once.
        # This used to be a two-entry series table plus a private title parser,
        # which is a mapping that works for two series and stops at three.
        verdict = _classify(market)
        if verdict.get("status") != "ok":
            reason = str(verdict.get("reason"))
            if reason == REASON_UNREADABLE_TITLE:
                # THE GRAMMAR WORK LIST, WRITTEN FROM DATA -- same argument as
                # the alias sample below, and now the LARGEST remaining refusal
                # on an MLB slate rather than a secondary one. `unreadable_title` names the problem
                # and then withholds the one thing needed to fix it: the title.
                # 216 markets a build refused with the string never printed.
                #
                # Guessing at Kalshi's wording is specifically what failed here
                # before: three grammars written against an imagined phrasing
                # matched NONE of production and 302 markets came back
                # unreadable on the first build (see the grammar block in
                # `kalshi_catalogue.py`). The titles are readable from the same
                # payload the join already holds, so there is no reason to
                # guess.
                #
                # ONE ROW PER SERIES. A series shares a title grammar, so a
                # second title from the same series teaches nothing while a
                # first title from a new series is a whole market family. That
                # is also what keeps `KXMLBGAME` -- the moneyline, and the
                # market the rejected live order wanted -- from being buried
                # under whichever series happens to be largest.
                series = str(market.get("series") or "").strip()
                # THE COMPLETE PER-SERIES COUNT, beside the bounded sample.
                #
                # The sample is one title per series capped at 10, which names
                # the GRAMMAR but cannot answer "is series X in here at all" --
                # and that is the question that matters when a specific market
                # family is missing. Measured 2026-08-25T16:56:46Z, the sample
                # returned 10 series and `KXMLBGAME` (the moneyline) was not
                # among them, which is not evidence either way while more than
                # 10 series refuse. A count is small, complete, and settles it.
                unreadable_by_series[series] = unreadable_by_series.get(series, 0) + 1
                # ONE SAMPLE PER SERIES, and the bound is on SERIES rather
                # than on samples. At `< 10` the cap was reached by the noisiest
                # families and every quieter series went unnamed: on 2026-08-25
                # `by_series` reported eight soccer series `unreadable_title`
                # (413 markets) while not one soccer TITLE appeared in the
                # sample, so the grammar gap could be counted and not read.
                # De-duplicated by series already, so this is 40 short strings
                # at worst -- the cost of the low cap was another cycle.
                if series not in unreadable_series and len(unreadable_titles) < MAX_UNREADABLE_SAMPLES:
                    unreadable_series.add(series)
                    unreadable_titles.append(
                        {
                            "series": series,
                            "title": str(market.get("title") or ""),
                            "ticker": str(market.get("ticker") or ""),
                        }
                    )
            _refuse(reason)
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
            # (`match_event_blob`), and the flag decides only whether a resolved
            # game may be priced. The resolver runs and REPORTS on every build,
            # so the measurement arrives before the money does.
            #
            # THAT MEASUREMENT HAS NOW ARRIVED, and it retired the worry this
            # comment used to carry. It read: "how often our codes agree with
            # Kalshi's is UNMEASURED -- `OAK` against `ATH` is a real
            # possibility and every such gap is an alias nobody has written
            # yet." Measured across two consecutive builds, once the date was
            # checked before the resolver rather than after it:
            #
            #   16:14:40Z  matched=5  {'event_not_on_our_board': 20,
            #                          'market_is_for_another_date': 512, ...}
            #   16:41:09Z  matched=4  {'market_is_for_another_date': 532, ...}
            #
            # `event_not_on_our_board` went 20 -> 0 and the date counter took
            # exactly those 20. Every one was a stale game, not a club code we
            # could not read; there is no alias gap on this slate. The club map
            # is not the game-line blocker and adding spellings to it would
            # have changed nothing.
            #
            # A total joined to the wrong game is a confidently-priced bet on
            # strangers, so `ambiguous` and `no_match` are refused by name and
            # never softened into a best guess.
            # DATE FIRST, BEFORE THE CLUB CODES. This check used to sit
            # below the resolver, and being second made it unreachable for the
            # markets it describes: `_resolve_event` matches the blob against
            # TODAY'S board, so a game line from another date cannot resolve
            # and died as `event_not_on_our_board` -- a club code we failed to
            # recognise -- without the date ever being read.
            #
            # MEASURED 2026-08-25T16:14:40Z. All 8 sampled "unrecognised" MLB
            # events were `ATLMIL` on `26AUG23`, two days stale:
            #
            #   JOIN_EVENTS unmatched=[{'kalshi': 'ATLMIL',
            #       'ticker': 'KXMLBSPREAD-26AUG231910ATLMIL-MIL4', ...}, ...]
            #
            # `ATLMIL` is a blob the resolver handles fine. Nothing was wrong
            # with our club map; the game was simply over. That is exactly the
            # `#505` failure the counters above are named to prevent -- "Kalshi
            # has nothing we bet" and "our join is broken" sharing one number
            # -- reappearing one layer down, where the reason names were right
            # but their ORDER made one impersonate the other.
            #
            # The date is in the ticker (`game_date_from_ticker`), so it is
            # answerable without the board. Asking it first keeps
            # `event_not_on_our_board` a true alias-gap count and keeps the
            # JOIN_EVENTS sample an alias work list rather than a list of
            # yesterday's games.
            if wanted_date:
                game_date = game_date_from_ticker(market.get("ticker"))
                if game_date is None:
                    _refuse(REASON_UNDATABLE)
                    continue
                if not _date_ok(game_date, market):
                    _refuse(REASON_WRONG_DATE)
                    continue

            resolution = _resolve_event(market, board_rows, club_code_names)
            status = str(resolution.get("status") or "")
            if status == "no_match":
                # THE ALIAS LIST, WRITTEN FROM DATA. `event_not_on_our_board`
                # is a count; it cannot say WHICH code we failed to recognise,
                # and guessing at club spellings is how a bet lands on the
                # wrong game. This prints Kalshi's blob beside the blobs our
                # own board offered for the same date, so the missing alias is
                # readable rather than inferred. Bounded at 8 -- enough to name
                # the pattern, not enough to flood the log money moves through.
                #
                # ONE ROW PER BLOB, and the budget is spent on DISTINCT codes.
                # The bound used to be `len(unmatched_samples) < 8`, which
                # takes the first eight markets rather than the first eight
                # codes -- and one game offers far more than eight. Measured
                # 2026-08-25T16:14:40Z, all 8 slots went to `ATLMIL`: six
                # spreads and two team totals off a single event, so a sample
                # built to enumerate missing aliases named exactly one thing
                # and said nothing about the other 19 refusals. A blob is what
                # an alias is written against, so a blob is the unit to
                # deduplicate on.
                blob = str(resolution.get("blob") or "")
                if blob not in unmatched_blobs and len(unmatched_samples) < 8:
                    unmatched_blobs.add(blob)
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
            # WHICH BOARD LINE DOES THIS KALSHI MARKET NAME?
            #
            # A TEAM SPREAD STATES A MARGIN, NOT A HANDICAP, AND THE TWO CARRY
            # OPPOSITE SIGNS. "Texas wins by over 1.5 runs" is the board's
            # `TEX -1.5`; the board writes that same game's other row as
            # `CWS +1.5`. Keying this lookup on Kalshi's bare magnitude paired
            # the market with `TEX +1.5` -- THE ROW FOR THE OPPOSITE BET --
            # purely because 1.5 == 1.5.
            #
            # MEASURED 2026-08-26 against the live book: all 11 spread orders
            # carrying a ticker named THE TEAM THEY WERE FADING (TEX +1.5 ->
            # ...-TEX2, KC +1.5 -> ...-KC2), while every -1.5 row -- the one
            # that genuinely corresponds to a "wins by over" market -- was
            # stamped with no ticker at all. Nothing reached the venue only
            # because `_side_to_kalshi` refuses `home`/`away` on spreads; that
            # refusal was the last guard, not a gap to close.
            #
            # So both reachable rows are named explicitly, with the club each
            # one must wear:
            #     the NAMED club at -X  -> YES pays when it covers
            #     the OTHER club at +X  -> NO pays when it does not
            event_id = str(resolution.get("event_id") or "")
            market_key = verdict["market"]
            is_team_spread = (
                verdict.get("grammar") == GRAMMAR_TEAM_SPREAD
                and verdict.get("line") is not None
            )
            if is_team_spread:
                strike = float(verdict["line"])
                wanted: tuple[tuple[Any, Any], ...] = ((-strike, True), (strike, False))
            else:
                wanted = ((verdict["line"], None),)

            game_rows: list[tuple[Mapping[str, Any], Any, Any]] = []
            for board_line, expect_named in wanted:
                for candidate in by_event.get((event_id, market_key, board_line)) or ():
                    game_rows.append((candidate, board_line, expect_named))
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
            for row, board_line, expect_named in game_rows:
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
                    is_named = board_side == named
                    if expect_named is not None and is_named is not expect_named:
                        # The right line wearing the wrong club: this market's
                        # margin belongs to the other team, so our board never
                        # wrote a row for it. REFUSED BY NAME -- pricing it here
                        # is precisely the inversion this block exists to stop.
                        _refuse(REASON_SPREAD_ORIENTATION)
                        continue
                    kalshi_side = "yes" if is_named else "no"
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
                # SEGMENT AGREEMENT, COUNTED. `_match_key`/`_row_key` already
                # refuse this pairing downstream -- but SILENTLY, by two keys
                # failing to compare equal, which is indistinguishable from a
                # venue that stopped quoting. Two consequences fixed here:
                #
                #  1. `REASON_SEGMENT_MISMATCH` was defined and referenced
                #     NOWHERE. A named refusal that can never fire is not an
                #     instrument, and `#601`'s own stated verification asked for
                #     a count that did not exist.
                #  2. Without this, a full-game `KXMLBTOTAL` still COLLECTS the
                #     `first3` board row -- `_board_key`/`_event_key` are
                #     3-tuples with no segment -- and builds a match record the
                #     resolver can never price. `matched` counted a phantom.
                if not _segments_agree(row, verdict):
                    _refuse(REASON_SEGMENT_MISMATCH)
                    continue
                matches.append(
                    {
                        "ticker": market.get("ticker"),
                        "series": verdict.get("series"),
                        "market": verdict["market"],
                        "player_name": None,
                        "team": subject,
                        # THE BOARD'S SIGNED LINE, not Kalshi's magnitude.
                        # `_match_key` and `_row_key` must name the same bet;
                        # storing the strike here would rebuild the +X/-X
                        # collision inside the ticker resolver's index.
                        "line": board_line,
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
            if not _date_ok(game_date, market):
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
            # See the game-line branch. Props are whole-game today, so this
            # is expected to read zero -- which is the point: a guard that only
            # ever fires is a guard nobody can calibrate, and one that never
            # fires here proves the prop book is not being reclassified.
            if not _segments_agree(row, verdict):
                _refuse(REASON_SEGMENT_MISMATCH)
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
        # One refused title per series: what grammar is missing, not how many.
        "unreadable_titles": unreadable_titles,
        # ...and how many per series, complete, so a family that is ABSENT can
        # be distinguished from one the bounded sample simply did not reach.
        "unreadable_by_series": dict(
            sorted(unreadable_by_series.items(), key=lambda kv: -kv[1])
        ),
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
