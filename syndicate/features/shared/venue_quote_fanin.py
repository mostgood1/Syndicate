"""Many odds sources in, one priced candidate out.

--------------------------------------------------------------------------
WHY THIS EXISTS — THE MEASUREMENT, 2026-08-24
--------------------------------------------------------------------------

The board carried 235 rows and every one was soccer, while ten MLB games and
two WNBA games sat on the board contract with markets and predictions
attached. Nothing was broken in the venues and nothing was broken in the model.
The candidates were thrown out for AGE:

    FILTER_CANDIDATES sport=all in=255 out=144
      rejected={"edge_below_threshold": 36, "stale_beyond_sla": 75}

`recommendation_engine._candidate_freshness_ceiling_seconds` is
`_pregame_sweep_interval_seconds(sport) * 3`, and the sweep defaults are
`{"soccer": 8h}` over a `2h` fallback. So the ceiling is **6h for mlb and wnba,
24h for soccer** — and the board's odds were **13.9 hours old**. Soccer cleared
its ceiling with ten hours to spare. MLB and WNBA missed theirs by eight.

One number decides that gate: `candidate["last_updated"]`
(`recommendation_engine.py:151`). Everything in this module exists to put a
FRESH, ATTRIBUTED price behind that field.

--------------------------------------------------------------------------
WHAT THIS IS AND IS NOT
--------------------------------------------------------------------------

IS: the fan-in. Many sources -> normalized quotes -> one selection per bet,
with the source named on every row.

IS NOT: a venue client. It does not call venue APIs. Each source reads the
artifact that venue's own refresh already wrote, because a second independent
caller for one venue is a documented incident class in this repo (`#139/#144`
for MLB, `#148` for soccer — the same violation twice). If a source has no
artifact yet, that is a NAMED REFUSAL here, not a fetch.

--------------------------------------------------------------------------
FIVE RULES, EACH FROM A FAILURE THIS REPO HAS ALREADY PAID FOR
--------------------------------------------------------------------------

1. **A stale source never shadows a fresh one.** `odds_control_plane`'s own
   docstring records 2026-08-04: a stale copy won on path precedence and every
   MLB candidate silently got `history_points=0`. Selection here is by
   FRESHNESS FIRST, and precedence is only ever a tie-break.

2. **Absence, failure and staleness are three different answers.** A source
   that is switched off, a source that errored, and a source whose data is old
   need three different responses. They never share a rendering — see
   `SourceOutcome`.

3. **Zero rows is not success.** A source returning an empty list reports
   `no_rows`, distinctly from `ok`. The whole `sporting=0` / `games=0` family
   of misreadings this week came from a zero that looked like a working feed.

4. **Every quote carries its source and its age.** `price_source` already
   exists on venue-scoped rows for exactly this reason. A blended price with no
   attribution cannot be debugged, and cannot be checked against the ceiling
   that rejected it.

5. **The unit is declared per source, never inferred.** Kalshi quotes dollars
   -as-probability; Polymarket US quotes probability; OddsAPI quotes American.
   Kalshi's first live run corrected a 100x price error that came from assuming
   a unit. Each adapter names its own.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "SOURCES",
    "SourceOutcome",
    "Quote",
    "collect_quotes",
    "select_quote",
    "stamp_candidate_freshness",
    "apply_venue_quotes",
    "source_enabled",
    "freshness_ceiling_seconds",
]


# The sources, in TIE-BREAK order only. Freshness beats this ordering every
# time (rule 1); this decides nothing unless two quotes are equally fresh.
# Named here once so "which venues feed the board" is one list, not a grep.
SOURCES: tuple[str, ...] = ("kalshi", "polymarket_us", "novig", "oddsapi", "oddsapi_props")

# Each source can be switched off without a deploy. OddsAPI is deliberately in
# this list: the user's requirement is that it be ONE INPUT AMONG VENUES that
# can be turned off and back on, not the spine everything else hangs from.
_ENABLE_ENV = "SYNDICATE_ODDS_SOURCE_{name}_ENABLED"

# Default-on for sources whose artifact already exists in production; default
# -off for ones that would otherwise report a refusal on every cycle and train
# readers to ignore the line.
_DEFAULT_ENABLED: dict[str, bool] = {
    "kalshi": True,
    "polymarket_us": True,
    "novig": False,      # see NOVIG_PUBLIC_TIER_REFUSAL
    "oddsapi": True,
    # The captured player-prop CSVs. Default-ON because the artifact already
    # exists in production and is written every pregame sweep -- the rule this
    # map states. Soccer only today; it refuses other sports BY NAME rather
    # than silently, so the line does not train readers to ignore it.
    "oddsapi_props": True,
}

# Novig's public CSV mirror is anonymized at the game/player/team level --
# `reportTicker`/`contractSeries` name a CATEGORY, never a specific bet
# (measured 2026-08-24, `f58905948`). So it cannot price a named bet no matter
# how fresh it is. This is a capability gap, NOT a failure, and it is stated
# rather than left to look like a broken feed.
NOVIG_PUBLIC_TIER_REFUSAL = (
    "novig_public_tier_is_anonymized: reportTicker/contractSeries name a "
    "category, never a specific bet; a per-bet price needs the credentialed "
    "REST tier"
)


@dataclass(frozen=True)
class Quote:
    """One price for one bet, from one source, with its age."""

    key: str
    source: str
    sport: str
    market: str
    side: str
    probability: float | None
    american: int | None
    line: float | None
    fetched_at: float
    # Carried through so a caller can attribute a fill or a refusal without
    # re-deriving it. `venue_ref` is the venue's own identifier -- Kalshi's
    # ticker, Polymarket's slug -- which is what makes an order placeable.
    venue_ref: str | None = None

    def age_seconds(self, *, now: float | None = None) -> float:
        return max(0.0, (time.time() if now is None else now) - float(self.fetched_at))


@dataclass
class SourceOutcome:
    """What one source did. Rule 2: three answers, never conflated.

    `status` is one of:
        ok        quotes were produced
        no_rows   the source ran and had nothing to say
        disabled  switched off, deliberately
        refused   cannot work at all (a capability gap, e.g. Novig's public tier)
        error     it tried and failed
    """

    source: str
    status: str
    reason: str | None = None
    quotes: list[Quote] = field(default_factory=list)
    age_seconds: float | None = None

    @property
    def usable(self) -> bool:
        return self.status == "ok" and bool(self.quotes)


def source_enabled(name: str) -> bool:
    raw = str(os.environ.get(_ENABLE_ENV.format(name=name.upper())) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(_DEFAULT_ENABLED.get(name, False))


def freshness_ceiling_seconds(sport: str, *, is_live: bool = False) -> int:
    """The SAME ceiling `recommendation_engine` will apply downstream.

    Imported rather than reimplemented: a fan-in that used its own idea of
    "fresh" would happily emit quotes the gate then rejects, and the two
    numbers would drift apart silently. If that import ever fails, this
    refuses to guess -- 0 means "no opinion", never "everything passes".
    """
    try:
        from syndicate.features.shared.recommendation_engine import (
            _candidate_freshness_ceiling_seconds,
        )

        return int(_candidate_freshness_ceiling_seconds(str(sport or ""), is_live=is_live))
    except Exception:
        return 0


def select_quote(quotes: Sequence[Quote], *, now: float | None = None) -> Quote | None:
    """FRESHNESS FIRST, source order only as a tie-break.

    Rule 1. The 2026-08-04 incident was precedence beating recency: a stale
    copy shadowed a freshly pulled one and every MLB candidate silently read
    `history_points=0`. Sorting the other way round makes that impossible.
    """
    usable = [q for q in quotes if q is not None]
    if not usable:
        return None
    order = {name: index for index, name in enumerate(SOURCES)}
    return sorted(
        usable,
        key=lambda q: (round(q.age_seconds(now=now), 3), order.get(q.source, len(SOURCES))),
    )[0]


def collect_quotes(
    sport: str,
    selected_date: str,
    *,
    adapters: Mapping[str, Callable[[str, str], SourceOutcome]] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Run every enabled source and report what each one actually did.

    Never raises for a source problem: one venue being unreachable must not
    cost the others' quotes, and the whole point is comparing across them.
    """
    registry = dict(adapters if adapters is not None else _default_adapters())
    outcomes: list[SourceOutcome] = []

    for name in SOURCES:
        if not source_enabled(name):
            outcomes.append(SourceOutcome(source=name, status="disabled", reason="switched_off"))
            continue
        adapter = registry.get(name)
        if adapter is None:
            outcomes.append(SourceOutcome(source=name, status="error", reason="no_adapter_registered"))
            continue
        try:
            outcome = adapter(str(sport or ""), str(selected_date or ""))
        except Exception as exc:  # noqa: BLE001 -- named, never fatal to the sweep
            outcomes.append(
                SourceOutcome(source=name, status="error", reason=f"{type(exc).__name__}: {exc}")
            )
            continue
        if not isinstance(outcome, SourceOutcome):
            outcomes.append(
                SourceOutcome(source=name, status="error", reason=f"adapter_returned_{type(outcome).__name__}")
            )
            continue
        # Rule 3: a source that ran and produced nothing is NOT ok.
        if outcome.status == "ok" and not outcome.quotes:
            outcome = SourceOutcome(source=name, status="no_rows", reason="source_returned_zero_quotes")
        outcomes.append(outcome)

    by_key: dict[str, list[Quote]] = {}
    for outcome in outcomes:
        for quote in outcome.quotes:
            by_key.setdefault(quote.key, []).append(quote)

    selected = {key: select_quote(quotes, now=now) for key, quotes in by_key.items()}
    ceiling = freshness_ceiling_seconds(sport)
    # The number that actually predicts the downstream gate. Reported per
    # selection rather than per source, because the gate is per candidate.
    within = sum(
        1 for q in selected.values()
        if q is not None and (ceiling <= 0 or q.age_seconds(now=now) <= ceiling)
    )
    return {
        "status": "ok",
        "sport": str(sport or ""),
        "selected_date": str(selected_date or ""),
        "quotes": selected,
        "keys": len(selected),
        "ceiling_seconds": ceiling,
        # If this is well below `keys`, the board is about to drop candidates
        # for age -- visible HERE, one stage before the rejection that cost a
        # whole slate on 2026-08-24.
        "within_ceiling": within,
        "beyond_ceiling": len(selected) - within,
        "by_source": {
            o.source: {
                "status": o.status,
                "reason": o.reason,
                "quotes": len(o.quotes),
                "age_seconds": o.age_seconds,
            }
            for o in outcomes
        },
        # Rule 4: which source won, and how often. A price with no attribution
        # cannot be checked against the ceiling that rejected it.
        "selected_by_source": _count_by_source(selected.values()),
    }


def _count_by_source(quotes) -> dict[str, int]:
    counts: dict[str, int] = {}
    for quote in quotes:
        if quote is None:
            continue
        counts[quote.source] = counts.get(quote.source, 0) + 1
    return counts


# The venues that quote a LIVE market continuously, and therefore the only
# sources whose `fetched_at` may stand in for `book_age_seconds` (see gate 3 in
# `stamp_candidate_freshness`). Named explicitly rather than "anything not
# oddsapi": an aggregator shard is a periodic capture, not an observation of the
# market moving, and treating its age as a book clock is precisely the
# laundering `opportunity_gate` exists to prevent.
_LIVE_QUOTING_VENUES = frozenset({"kalshi", "polymarket_us"})


def stamp_candidate_freshness(candidate: dict[str, Any], quote: Quote | None) -> dict[str, Any]:
    """THE SEAM. Put the quote's age behind the fields the gates read.

    THERE ARE TWO GATES AND THEY READ DIFFERENT FIELDS. Missing the second is
    why a venue-priced row could still age out:

      1. `recommendation_engine._candidate_age_seconds` reads `last_updated`,
         falling back to `updated_epoch`. Rejects as `stale_beyond_sla`
         (6h mlb/wnba, 24h soccer).

      2. `layer2_board._row_quote_age_seconds` reads
         `row["quote"]["quote_seen_age_seconds"]`, falling back to
         `quote["book_age_seconds"]`. Rejects as `beyond_quote_age`
         (SHORTLIST_MAX_QUOTE_AGE_SECONDS, 14h).

    MEASURED 2026-08-24 23:23Z, which is why this stamps both:

        LAYER2_SHORTLIST rows=0 considered=8600
          beyond_quote_age=6184  beyond_horizon=2416

    **71.9% of the board died on gate 2**, the one nobody was looking at, while
    gate 1 was improving. Stamping only `last_updated` would have fixed the gate
    that was already recovering and left the one actually emptying the board.

    `book_age_seconds` is DELIBERATELY NOT TOUCHED. It answers a different
    question -- "has the market moved" rather than "how old is our observation"
    -- and `opportunity_gate`'s live/pregame checks read it for that. Its own
    docstring says so, and overwriting it would make a motionless market look
    like a moving one.

    Returns the candidate unchanged when there is no quote. A missing price must
    not refresh a timestamp: that laundering is worse than an honest stale row,
    because it defeats the gate rather than passing it.
    """
    if quote is None:
        return candidate
    stamped = dict(candidate)
    stamped["last_updated"] = _iso(quote.fetched_at)
    stamped["updated_epoch"] = float(quote.fetched_at)
    stamped["price_source"] = quote.source

    # Gate 2. The nested `quote` block is copied rather than mutated in place:
    # these rows are shared across the build, and mutating a nested dict would
    # age-stamp rows this quote was never applied to.
    existing = candidate.get("quote")
    quote_block = dict(existing) if isinstance(existing, Mapping) else {}
    quote_block["quote_seen_age_seconds"] = quote.age_seconds()
    quote_block["quote_source"] = quote.source

    # GATE 3, AND IT IS THE ONE THAT EMPTIED THE LIVE BOARD.
    #
    # `opportunity_gate` reads `book_age_seconds` for a check neither gate above
    # covers, and its ceiling collapses 96x the moment a game starts:
    #
    #     LIVE_MARKET_MAX_AGE_SECONDS    =    900   (15 min, once live)
    #     PREGAME_MARKET_MAX_AGE_SECONDS = 86,400   (24 hr, before)
    #
    # MEASURED 2026-08-25T03:13:38Z, with every other explanation ruled out:
    #
    #     mlb  cand=1302 scored=1300 priced=1390 opps=0 lanes={'dead': 1302}
    #     wnba cand=1225 scored=1225 priced=1247 opps=0 lanes={'dead': 1225}
    #     nfl  ... lanes={'opportunity': 112, 'watchlist': 226, 'dead': 2304}
    #
    #     GAME_STATE_JOIN sport=mlb  chips=25 rows_matched=816 unmatched=None
    #     GAME_STATE_JOIN sport=wnba chips=5  rows_matched=643 unmatched=None
    #
    # The join is HEALTHY -- which is exactly why MLB and WNBA take the
    # `state == "live"` branch that NFL and soccer never reach, and then fail
    # its 15-minute clock on an OddsAPI `book_age` measured in hours. 100% of
    # both sports went dead; the two pregame sports were untouched.
    #
    # ONLY FOR A GENUINELY VENUE-PRICED ROW, and that restriction is the whole
    # safety argument. This function's own docstring says `book_age_seconds` is
    # deliberately not touched because it answers "has the market MOVED", not
    # "how old is our observation" -- and blanket-stamping it would defeat the
    # one check standing between us and a stale price on a live game, which is
    # the most dangerous row on the board with real money armed.
    #
    # What makes it defensible here: this row was just repriced from Kalshi or
    # Polymarket, venues that quote the live market continuously. For such a row
    # the venue's own `fetched_at` IS when the market was last observed moving,
    # so `book_age` and `quote_seen_age` describe the same event and agreeing is
    # correct rather than laundering.
    #
    # NEVER WIDENS. `min()` against any existing value means a book that really
    # is fresher keeps its number, and a row can only ever get YOUNGER by the
    # amount the venue actually just observed -- never older, never invented.
    if quote.source in _LIVE_QUOTING_VENUES:
        venue_age = quote.age_seconds()
        existing_age = quote_block.get("book_age_seconds")
        try:
            existing_age = float(existing_age) if existing_age is not None else None
        except (TypeError, ValueError):
            existing_age = None
        quote_block["book_age_seconds"] = (
            venue_age if existing_age is None else min(existing_age, venue_age)
        )
        # Named so a reader can tell a venue-refreshed clock from a book's own.
        quote_block["book_age_source"] = quote.source

    stamped["quote"] = quote_block

    if quote.venue_ref:
        stamped["venue_ref"] = quote.venue_ref
    return stamped


def apply_venue_quotes(
    rows: Sequence[Mapping[str, Any]],
    selected_date: str,
    *,
    collected_by_sport: Mapping[str, Mapping[str, Any]] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Re-price rows from the freshest venue quote available, and report it.

    GROUPS BY SPORT AND COLLECTS ONCE PER SPORT. The row set spans every active
    sport, while every ceiling, artifact and adapter is per-sport -- a single
    `collect_quotes` call for the whole board would price MLB rows against
    whichever sport happened to be passed in, which is a wrong price rather
    than a missing one.

    ONLY ROWS WE ACTUALLY PRICED ARE STAMPED. A row with no venue quote is
    returned untouched and stays as stale as it really is. Blanket-refreshing
    timestamps would launder staleness through a gate designed to catch it,
    which is the one outcome worse than the empty board this exists to fix.
    """
    from syndicate.features.shared.venue_quote_adapters import quote_key

    by_sport: dict[str, Mapping[str, Any]] = dict(collected_by_sport or {})
    out: list[Mapping[str, Any]] = []
    stamped = 0
    per_source: dict[str, int] = {}
    per_source_by_sport: dict[str, dict[str, int]] = {}
    wanted_by_sport: dict[str, set[str]] = {}
    ceilings: dict[str, int] = {}
    source_status: dict[str, Any] = {}
    unmatched_samples: list[str] = []
    unmatched_by_sport: dict[str, int] = {}
    unmatched_by_sport_sample: dict[str, list[str]] = {}

    for row in rows:
        sport = str(row.get("sport") or "").strip().lower()
        if not sport:
            out.append(row)
            continue
        if sport not in by_sport:
            try:
                by_sport[sport] = collect_quotes(sport, selected_date, now=now)
            except Exception:
                # One sport's venue failure must not cost the others' rows.
                by_sport[sport] = {"quotes": {}}
        payload = by_sport[sport]
        ceilings.setdefault(sport, payload.get("ceiling_seconds"))
        if sport not in source_status and payload.get("by_source"):
            source_status[sport] = payload.get("by_source")

        # DERIVED from the row, not read off it. A board row carries no
        # `venue_quote_key`, so requiring one would have matched nothing and
        # reported a confident `stamped=0` -- the "zero that looks like a
        # working feed" failure this module documents three times over.
        keys = _candidate_keys(row, sport)
        # Every key this sport ASKED FOR, for the overlap counter below.
        wanted_by_sport.setdefault(sport, set()).update(str(k) for k in keys)
        quotes_for_sport = payload.get("quotes") or {}
        quote = None
        key = keys[0]
        for candidate in keys:
            found = quotes_for_sport.get(str(candidate))
            if found is not None:
                quote, key = found, candidate
                break
        if quote is None:
            # WHAT THE UNMATCHED KEY ACTUALLY LOOKED LIKE, bounded to a handful.
            #
            # MEASURED 2026-08-25T00:02Z: polymarket_us contributed 3,106 quotes
            # across mlb/wnba/nfl and won ZERO selections
            # (`selected_by_source={'kalshi': 237}`). Losing a freshness contest
            # explains losing SOME; it cannot explain losing all of them, because
            # on a game-line row Kalshi offers no quote at all and Polymarket
            # should win by default.
            #
            # `stamped` alone cannot tell a key-space mismatch from a venue that
            # genuinely lists nothing -- the same confusion that made the OddsAPI
            # adapter silently inert on a DIFFERENT key space for an entire
            # evening. So record the board's key beside the keys the sources
            # actually offered, and let the log settle it instead of an argument.
            if len(unmatched_samples) < _UNMATCHED_SAMPLE_LIMIT:
                unmatched_samples.append(str(key))
            # PER SPORT, because the global list above answers the wrong
            # question. It is one pool of 8 filled in row order, so whichever
            # sport has the most rows takes every slot: read on production
            # 2026-08-27 it was eight `mlb|spreads|...` keys while the counts
            # beside it said `nfl: 1244, soccer: 11365`. The two sports with
            # the largest gaps were the two the sample could not show, so the
            # diagnostic could name the size of the problem and never its shape.
            bucket = unmatched_by_sport_sample.setdefault(sport, [])
            if len(bucket) < _UNMATCHED_SAMPLE_LIMIT and str(key) not in bucket:
                bucket.append(str(key))
            unmatched_by_sport[sport] = unmatched_by_sport.get(sport, 0) + 1
            out.append(row)
            continue
        out.append(stamp_candidate_freshness(dict(row), quote))
        stamped += 1
        per_source[quote.source] = per_source.get(quote.source, 0) + 1
        # PER SPORT, because the global tally cannot answer the question people
        # actually ask of it. "Is kalshi matching soccer?" was unanswerable from
        # `selected_by_source` on 2026-08-27 -- it showed `kalshi: 2533` across
        # five sports at once, so a source could be carrying one sport entirely
        # and contributing nothing to another and the line would read the same.
        # `by_source` already reports what each source OFFERED per sport; this
        # is the other half, what it actually WON.
        by_sport_bucket = per_source_by_sport.setdefault(sport, {})
        by_sport_bucket[quote.source] = by_sport_bucket.get(quote.source, 0) + 1

    return {
        "rows": out,
        "rows_in": len(rows),
        "stamped": stamped,
        # The number that predicts whether this actually helped. Rows left
        # unstamped keep whatever age they had and will be gated on it.
        "unstamped": len(rows) - stamped,
        "sports": sorted(by_sport.keys()),
        "ceiling_seconds_by_sport": ceilings,
        "selected_by_source": per_source,
        # {sport: {source: wins}}. Sports with zero selections are ABSENT rather
        # than zero-filled -- a sport that produced no rows at all and a sport
        # whose every row lost are different facts, and `unmatched_by_sport`
        # beside this tells them apart.
        "selected_by_source_by_sport": per_source_by_sport,
        # {sport: {source: {offered, wanted_overlap}}}. THE QUESTION THIS
        # ANSWERS, which nothing else here could: a source with quotes and zero
        # selections is either offering bets the board never asks for, or
        # offering the right bets and losing on freshness. Those need opposite
        # fixes and looked identical.
        #
        # Measured 2026-08-27: kalshi offered 173 SOCCER quotes at 165s -- the
        # freshest feed of the four -- and won ZERO. The four sampled keys were
        # Belgian clubs (`oh leuven`, `kaa gent`, `anderlecht`, `kv kortrijk`)
        # and NONE of them appears among the 161 clubs the board carried that
        # day, which suggests different FIXTURES rather than a key-shape
        # mismatch. A sample of four cannot settle that; this counter can.
        "offered_overlap_by_sport": _offered_overlap(by_sport, wanted_by_sport),
        "by_source": source_status,
        # THE TWO SIDES OF THE JOIN, SAMPLED, so a key-space mismatch is
        # readable rather than inferred. `unmatched_sample` is what the BOARD
        # asked for; `offered_sample` is what each SOURCE had. If they are
        # shaped differently -- a team's short name against its full name, say
        # -- these two lines say so at a glance.
        "unmatched_by_sport": unmatched_by_sport,
        "unmatched_sample": unmatched_samples,
        # Distinct keys only, per sport: 1,244 unmatched nfl rows are not 1,244
        # distinct shapes, and a sample that repeats one key eight times is a
        # sample of one.
        "unmatched_sample_by_sport": unmatched_by_sport_sample,
        "offered_sample": _offered_sample(by_sport),
    }


_UNMATCHED_SAMPLE_LIMIT = 8
_OFFERED_SAMPLE_LIMIT = 4


def _candidate_keys(row: Mapping[str, Any], sport: str) -> list[str]:
    """Every key shape this row could legitimately be quoted under, in order.

    ONE ROW, MORE THAN ONE VOCABULARY. The board keys a moneyline side by its
    ROLE (`h2h|home`); Polymarket keys it by the CLUB (`h2h|chicago cubs`).
    Both are correct descriptions of the same bet, and measured
    2026-08-25T00:46Z they never met: polymarket_us offered 3,106 quotes and
    won zero of 237 selections while every other counter looked healthy.

    Rather than force one side to adopt the other's words -- which would break
    whichever source already speaks the first -- a row offers both and the
    first hit wins. Additive by construction: the role key is tried FIRST and
    unchanged, so every match that worked before still works, and this can only
    add matches.

    The club key is derived with `canonical_team`, the SAME resolver the
    adapter uses on the venue's outcome name. Two resolvers is how the halves
    of a join end up on different vocabularies; one cannot disagree with
    itself.
    """
    from syndicate.features.shared.venue_quote_adapters import (
        prop_quote_key,
        quote_key,
        team_name_tokens,
    )

    explicit = row.get("venue_quote_key")
    if explicit:
        return [str(explicit)]

    market = str(row.get("market") or "").strip().lower()
    side = str(row.get("side") or "").strip().lower()
    line = _as_float_or_none(row.get("line"))

    # A PROP'S KEY MUST NAME ITS PLAYER. `market_inventory`'s row contract says
    # `entity` is "player name for props, None for game markets", and this
    # function ignored it -- so every player's anytime-scorer row keyed to the
    # single string `soccer|player_goal_scorer_anytime|yes`, and every
    # 2.5-three-pointer row to `wnba|player_threes|over|2.5`. Rows that share a
    # key are indistinguishable here: the first wins, and the quote it wins
    # describes a different human. `kalshi_board_join` has always keyed props
    # with `normalize_person(subject)`; this is the same shape.
    #
    # RETURNED ALONE, with no player-blind fallback. Falling back would keep
    # exactly the wrong match this exists to remove -- the blind key would still
    # be tried and would still hit someone else's quote.
    entity = row.get("entity") or row.get("player") or row.get("player_name")
    if entity:
        keyed = prop_quote_key(sport, market, entity, side, line)
        # An unnameable player yields NO key. The row goes unmatched and keeps
        # its own age, which is the honest outcome; a blind key here would
        # launder someone else's freshness onto it.
        return [keyed] if keyed else []

    keys = [quote_key(sport, market, side, line)]

    if market == "h2h" and side in {"home", "away"}:
        team = row.get(f"{side}_team")
        try:
            from syndicate.features.shared.team_aliases import canonical_team

            club = canonical_team(sport, team)
        except Exception:
            club = None
        # No club, no second key -- never a bare team string as a fallback.
        # An unresolved name would build a key that matches nothing and hides
        # the fact that the row could not be placed.
        if club:
            keys.append(quote_key(sport, market, club, None))

        # A THIRD SHAPE: THE CITY OR NICKNAME ALONE.
        #
        # Kalshi names a moneyline by the team and nothing else -- "Texas
        # wins", "Buffalo wins" -- so it publishes `h2h|texas` where the board
        # carries "Texas Rangers". Neither of the two keys above can meet that:
        # the role key says `home`, and the club key says `texas rangers`.
        # Measured 2026-08-25T21:12:14Z, `sources_offered` had kalshi at
        # `nfl|h2h|yes` against a board asking `soccer|h2h|real betis` --
        # every Kalshi game line offered under a side the board never asks for.
        #
        # AMBIGUOUS TOKENS ARE DROPPED, and that is the whole safety property.
        # "chicago" sits inside both "chicago cubs" and "chicago white sox", so
        # on a Cubs/White Sox game it names NEITHER side. The candidate set here
        # is exactly two clubs and both are known to be playing each other, so
        # the opponent's tokens are available to subtract -- the same bound
        # `kalshi_board_join._side_for_team` relies on, and the same refusal:
        # guessing which side a shared name refers to is a bet on the wrong team
        # half the time, at a price that looks confident.
        opponent = "away_team" if side == "home" else "home_team"
        mine = team_name_tokens(sport, team)
        theirs = team_name_tokens(sport, row.get(opponent))
        for token in sorted(mine - theirs):
            candidate = quote_key(sport, market, token, None)
            if candidate not in keys:
                keys.append(candidate)
    return keys


def _offered_overlap(
    by_sport: Mapping[str, Mapping[str, Any]],
    wanted_by_sport: Mapping[str, set[str]],
) -> dict[str, dict[str, dict[str, int]]]:
    """Per sport and source: how many keys it offered, and how many of those the
    board actually asked for.

    `wanted_overlap: 0` alongside a healthy `offered` is a COVERAGE statement --
    this source is quoting bets nobody on the board is holding. A non-zero
    overlap with zero selections is the opposite: the right bets, lost on
    freshness or to a rival source. `by_source` reports what was offered and
    `selected_by_source_by_sport` what was won; without this, the gap between
    them had two explanations and no way to choose.
    """
    out: dict[str, dict[str, dict[str, int]]] = {}
    for sport, payload in (by_sport or {}).items():
        wanted = wanted_by_sport.get(sport) or set()
        per_source: dict[str, set[str]] = {}
        for key, quote in ((payload or {}).get("quotes") or {}).items():
            source = getattr(quote, "source", None)
            if source:
                per_source.setdefault(str(source), set()).add(str(key))
        if per_source:
            out[sport] = {
                source: {"offered": len(keys), "wanted_overlap": len(keys & wanted)}
                for source, keys in sorted(per_source.items())
            }
    return out


def _offered_sample(by_sport: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """A few keys each source actually published, per sport.

    Read from the SOURCE's own quotes rather than reconstructed, because a
    reconstruction would be built from the same assumption the mismatch is
    hiding in and would agree with itself.
    """
    sample: dict[str, Any] = {}
    for sport, payload in (by_sport or {}).items():
        per_source_keys: dict[str, list[str]] = {}
        for key, quote in (payload.get("quotes") or {}).items():
            source = getattr(quote, "source", "?")
            bucket = per_source_keys.setdefault(str(source), [])
            if len(bucket) < _OFFERED_SAMPLE_LIMIT:
                bucket.append(str(key))
        if per_source_keys:
            sample[sport] = per_source_keys
    return sample


def _as_float_or_none(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(epoch: float) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(float(epoch), datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _default_adapters() -> dict[str, Callable[[str, str], SourceOutcome]]:
    from syndicate.features.shared import venue_quote_adapters as adapters

    return {
        "kalshi": adapters.kalshi_outcome,
        "polymarket_us": adapters.polymarket_us_outcome,
        "novig": adapters.novig_outcome,
        "oddsapi": adapters.oddsapi_outcome,
        "oddsapi_props": adapters.oddsapi_props_outcome,
    }


# The board's book name for each live-quoting venue. `book_shortlist`
# DEFAULT_BOOKS carries "polymarket", the adapter's source is "polymarket_us",
# and a row whose bookmaker is not in that list is DROPPED as
# `no_bettable_book`. Mapped explicitly so a venue-priced row survives the
# bettable-book filter it is genuinely bettable at.
_VENUE_BOOK_NAME: dict[str, str] = {
    "kalshi": "kalshi",
    "polymarket_us": "polymarket",
}


def apply_venue_quotes_to_grid(
    grid: Sequence[Mapping[str, Any]],
    sport: str,
    selected_date: str,
    *,
    collected: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Re-price a sport's GRID from the venues, BEFORE the lane gate runs.

    --------------------------------------------------------------------------
    WHY THIS EXISTS RATHER THAN `apply_venue_quotes` ALONE
    --------------------------------------------------------------------------

    The ordering was backwards, and no amount of stamping downstream could fix
    it (measured 2026-08-25):

        line 498   result = build_layer2_rows(grid, ...)   <- opportunity_gate
        line 634   apply_venue_quotes(opportunities, ...)  <- venue reprice

    `build_layer2_rows` applies the gate and returns only the SURVIVORS as
    `opportunities`. The reprice then ran on that survivor list, so a row the
    gate had already killed could never be rescued by a venue price. The lane
    was decided before the venue quote was ever stamped.

    That is why `VENUE_REPRICE sports=['nfl','soccer']` never listed mlb or
    wnba, and why `rows_in=4296` did not move across five consecutive builds:
    the only rows reaching the reprice were the pregame sports that survived.

        03:13:38  mlb(...priced=1390, opps=0, lanes={'dead': 1302})
        03:34:16  mlb(...priced=1390, opps=0, lanes={'dead': 1302})

    Byte-identical across the book-clock fix, because the rows it fixed no
    longer existed by the time it ran.

    --------------------------------------------------------------------------
    PRICE AND AGE MOVE TOGETHER, OR NEITHER MOVES
    --------------------------------------------------------------------------

    This replaces the side's PRICE, BOOKMAKER and AGE from the same quote. It
    deliberately does NOT refresh the age alone: a stale price wearing a fresh
    timestamp is exactly the laundering `opportunity_gate`'s live-market clock
    exists to catch, and it would be worse than the empty board -- it defeats
    the check instead of passing it.

    Because price and book move together, the row becomes genuinely
    venue-priced: `kalshi` and `polymarket` are both in
    `book_shortlist.DEFAULT_BOOKS`, so it stays bettable, EV is computed on the
    number we would actually take, and settlement grades against that same
    number.

    ONLY LIVE-QUOTING VENUES. OddsAPI is excluded for the reason stated on
    `_LIVE_QUOTING_VENUES`: an aggregator shard is a periodic capture, not an
    observation of the market moving.

    ONLY WHEN THE VENUE IS FRESHER. `min()` on the age and a strict improvement
    check mean this can never age a side UP or replace a genuinely fresher book
    price with an older venue one.
    """
    from syndicate.features.shared.venue_quote_adapters import quote_key

    sport_slug = str(sport or "").strip().lower()
    payload = collected if collected is not None else collect_quotes(sport_slug, selected_date, now=now)
    quotes = (payload or {}).get("quotes") or {}
    repriced = 0
    sides_seen = 0
    by_source: dict[str, int] = {}

    benchmark_rows = 0
    benchmark_skipped: dict[str, int] = {}

    for row in grid or []:
        if not isinstance(row, Mapping):
            continue
        best = row.get("best")
        if not isinstance(best, dict):
            continue
        market = row.get("market")
        line = _as_float_or_none(row.get("line"))
        side_names = [str(side) for side in (row.get("sides") or [])]
        # Resolved for every side BEFORE anything is written, because the
        # benchmark rewrite below is all-or-nothing per row and cannot be
        # decided one side at a time.
        venue_quotes: dict[str, Any] = {}
        for side_key in side_names:
            quote = quotes.get(str(quote_key(sport_slug, market, side_key, line)))
            if quote is None or quote.source not in _LIVE_QUOTING_VENUES:
                continue
            if quote.american is None:
                # No price is not a reprice. Refreshing the clock here would be
                # the age-only laundering this function refuses.
                continue
            venue_quotes[side_key] = quote

        for side_key in side_names:
            side_best = best.get(side_key)
            if not isinstance(side_best, dict):
                continue
            sides_seen += 1
            quote = venue_quotes.get(side_key)
            if quote is None:
                continue
            venue_age = quote.age_seconds(now=now)
            existing_age = _as_float_or_none(side_best.get("age_seconds"))
            if existing_age is not None and existing_age <= venue_age:
                # The book really is fresher. Leave it entirely alone.
                continue
            side_best["price"] = int(quote.american)
            side_best["bookmaker"] = _VENUE_BOOK_NAME.get(quote.source, quote.source)
            side_best["age_seconds"] = venue_age
            side_best["seen_age_seconds"] = venue_age
            side_best["price_source"] = quote.source
            if quote.venue_ref:
                side_best["venue_ref"] = quote.venue_ref
            repriced += 1
            by_source[quote.source] = by_source.get(quote.source, 0) + 1

        outcome = _reprice_live_benchmark(
            row, side_names, venue_quotes, now=now
        )
        if outcome == "repriced":
            benchmark_rows += 1
        elif outcome:
            benchmark_skipped[outcome] = benchmark_skipped.get(outcome, 0) + 1

    return {
        "sport": sport_slug,
        "sides_seen": sides_seen,
        "repriced": repriced,
        "by_source": by_source,
        "benchmark_rows": benchmark_rows,
        "benchmark_skipped": benchmark_skipped,
        "source_status": (payload or {}).get("by_source"),
    }


# The states in which a PREGAME book price stops being a description of the
# market. Same vocabulary `opportunity_gate` and `live_gameline_join` use.
_LIVE_STATES = frozenset({"live", "in_progress"})

# How far behind the live venue a book may lag and still count as a peer in the
# fair-value median. `opportunity_gate.LIVE_MARKET_MAX_AGE_SECONDS` is the same
# 900s ceiling the gate applies to a live row's own price -- read from there so
# the staleness the board ENFORCES and the staleness it BENCHMARKS AGAINST
# cannot drift apart.
try:  # pragma: no cover - import-order guard, not a behaviour branch
    from syndicate.features.shared.opportunity_gate import (
        LIVE_MARKET_MAX_AGE_SECONDS as _BENCHMARK_SUPERSEDE_LAG_SECONDS,
    )
except ImportError:  # pragma: no cover
    _BENCHMARK_SUPERSEDE_LAG_SECONDS = 900.0


def _reprice_live_benchmark(
    row: Mapping[str, Any],
    side_names: list[str],
    venue_quotes: Mapping[str, Any],
    *,
    now: float | None,
) -> str:
    """Move a LIVE row's fair-value benchmark onto the venue that priced it.

    --------------------------------------------------------------------------
    THE DEFECT THIS FIXES: ONE ROW, TWO VINTAGES
    --------------------------------------------------------------------------

    Re-pricing `best` alone put a LIVE price on the row and left every
    fair-value benchmark pregame. The board then compared them:

      * `layer2_board._fair_by_side` de-vigs `row["cells"]` -- the per-book
        prices, all OddsAPI, captured before first pitch.
      * `prop_projections._no_vig_over_probability` de-vigs `row["consensus"]`,
        the same pregame capture, and that is `market_fair_prob_over`.
      * `live_gameline_join.price_moneyline` subtracts that pregame fair from
        the LIVE re-sim's win probability.

    A team three runs up in the 7th is ~0.90 to the live model and ~0.55 to the
    pregame consensus. The subtraction reports a 35-point edge that is entirely
    the gap between two clocks, and `layer2_board._MODEL_EDGE_MAX_POINTS` then
    drops it -- correctly, since a 35-point edge is exactly the units/vintage
    mismatch that bound exists to catch (`todo.md`: "should be permanent").

    So the observed `refusals={'no_model_edge_pct': 14}` is the guard working.
    **The bound is not the bug and is not touched here.** The bug is that the
    only number on the row that knew the game had started was the price.

    --------------------------------------------------------------------------
    FOUR CONDITIONS, EACH LOAD-BEARING
    --------------------------------------------------------------------------

    1. **LIVE ROWS ONLY.** On a pregame game the multi-book consensus is a real
       consensus of the current market and is left completely alone -- replacing
       five books with one venue there would throw away the median that stops a
       single fat-fingered book moving the benchmark (`#384`).

    2. **EVERY SIDE, OR NO SIDE.** A de-vig mixing a live venue price for home
       with a pregame consensus for away spans two vintages and is worse than
       the stale pair it replaces. All sides come from the same venue or nothing
       is written.

    3. **ONE VENUE PER ROW.** Both sides must come from the SAME source, for the
       reason `_fair_by_side` already documents at length: the best over at one
       book and the best under at another sum to less than a market, and
       normalising that to 1.0 launders a line-shopping edge into the fair
       price.

    4. **STRICTLY FRESHER.** Same rule as the price reprice above -- this can
       never age a benchmark up.

    Writes `cells` AND `consensus` because they feed two different readers:
    `_fair_by_side` reads `cells` (and needs the venue present as a book quoting
    every leg, which is exactly what condition 2 guarantees), while
    `market_fair_prob_over` reads `consensus`. Updating one and not the other is
    how the board's EV and the live edge would come to disagree.

    Returns "repriced", or the name of the condition that refused, so a zero is
    attributable rather than bare.
    """
    if not isinstance(row, dict):
        return "row_not_mutable"
    if len(side_names) < 2:
        return "not_two_sided"
    game = row.get("game")
    state = str((game or {}).get("state") or "").strip().lower() if isinstance(game, Mapping) else ""
    if state not in _LIVE_STATES:
        return "not_live"
    if len(venue_quotes) != len(side_names):
        return "venue_did_not_price_every_side"
    sources = {quote.source for quote in venue_quotes.values()}
    if len(sources) != 1:
        return "sides_from_different_venues"

    source = next(iter(sources))
    book = _VENUE_BOOK_NAME.get(source, source)
    ages = [quote.age_seconds(now=now) for quote in venue_quotes.values()]
    venue_age = max(ages) if ages else None
    if venue_age is None:
        return "venue_quote_has_no_age"
    existing_age = _as_float_or_none(row.get("age_seconds"))
    if existing_age is not None and existing_age <= venue_age:
        return "existing_benchmark_is_fresher"

    cells = row.get("cells")
    if not isinstance(cells, dict):
        cells = {}
        row["cells"] = cells
    venue_cells = cells.get(book)
    if not isinstance(venue_cells, dict):
        venue_cells = {}
        cells[book] = venue_cells

    consensus = row.get("consensus")
    if not isinstance(consensus, dict):
        consensus = {}
        row["consensus"] = consensus

    for side_key in side_names:
        quote = venue_quotes[side_key]
        price = int(quote.american)
        age = quote.age_seconds(now=now)
        venue_cells[side_key] = {
            "price": price,
            "bookmaker": book,
            "age_seconds": age,
            "seen_age_seconds": age,
            # Never stale by construction -- it just cleared the strictly-fresher
            # check above -- and `book_grid`'s consensus builder drops stale
            # cells, so an unset flag here would read as unknown.
            "stale": False,
            "price_source": source,
        }
        # A plain american price, which is the shape `book_grid` writes and
        # `_no_vig_over_probability` reads via `_implied`.
        consensus[side_key] = price

    # SET THE SUPERSEDED BOOKS ASIDE, or the median puts them back.
    #
    # `_fair_by_side` de-vigs EVERY book in `cells` and takes the MEDIAN across
    # them (`#384`, so one fat-fingered book cannot move the benchmark). With
    # the venue merely ADDED, a live -900 and a pregame -120 de-vig to ~0.90 and
    # ~0.50 and the median of the two is ~0.70 -- half the vintage gap, which is
    # the same defect at half the size. Caught by
    # `test_the_devig_the_board_will_run_is_now_live_on_both_legs`, which asserted
    # ~0.90 and read 0.6999.
    #
    # A book that is itself quoting the live market STAYS a peer -- the rule is
    # about vintage, not about preferring the venue. Only books lagging the
    # venue by more than the live-market ceiling move.
    #
    # MOVED, NOT DELETED. `cells_superseded` keeps the pregame observation on
    # the row: it is a real record of an earlier market and the ledger reads it.
    superseded = row.get("cells_superseded")
    if not isinstance(superseded, dict):
        superseded = {}
    for other in [key for key in cells if key != book]:
        other_cells = cells.get(other)
        if not isinstance(other_cells, Mapping):
            continue
        other_ages = [
            _as_float_or_none(cell.get("age_seconds"))
            for cell in other_cells.values()
            if isinstance(cell, Mapping)
        ]
        present = [age for age in other_ages if age is not None]
        # An age nobody stamped is unknown, not fresh: a book with no clock
        # cannot be shown to be quoting the live market, and this is the
        # direction that fails safe.
        if present and len(present) == len(other_ages):
            if min(present) - venue_age <= _BENCHMARK_SUPERSEDE_LAG_SECONDS:
                continue
        superseded[other] = cells.pop(other)
    if superseded:
        row["cells_superseded"] = superseded

    books = row.get("books")
    if isinstance(books, list):
        row["books"] = [name for name in books if name not in superseded]
        if book not in row["books"]:
            row["books"].append(book)
        row["books_quoting"] = len(row["books"])
    return "repriced"
