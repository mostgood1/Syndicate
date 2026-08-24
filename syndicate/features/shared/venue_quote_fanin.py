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
SOURCES: tuple[str, ...] = ("kalshi", "polymarket_us", "novig", "oddsapi")

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
    stamped["quote"] = quote_block

    if quote.venue_ref:
        stamped["venue_ref"] = quote.venue_ref
    return stamped


def apply_venue_quotes(
    rows: Sequence[Mapping[str, Any]],
    sport: str,
    selected_date: str,
    *,
    collected: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Re-price rows from the freshest venue quote available, and report it.

    ONLY ROWS WE ACTUALLY PRICED ARE STAMPED. A row with no venue quote is
    returned untouched and stays as stale as it really is. Blanket-refreshing
    timestamps would launder staleness through a gate designed to catch it,
    which is the one outcome worse than the empty board this exists to fix.
    """
    payload = collected if collected is not None else collect_quotes(sport, selected_date, now=now)
    quotes = payload.get("quotes") or {}

    out: list[Mapping[str, Any]] = []
    stamped = 0
    for row in rows:
        key = row.get("venue_quote_key") or row.get("key")
        quote = quotes.get(str(key)) if key else None
        if quote is None:
            out.append(row)
            continue
        out.append(stamp_candidate_freshness(dict(row), quote))
        stamped += 1

    return {
        "rows": out,
        "rows_in": len(rows),
        "stamped": stamped,
        # The number that predicts whether this actually helped. Rows left
        # unstamped keep whatever age they had and will be gated on it.
        "unstamped": len(rows) - stamped,
        "by_source": payload.get("by_source"),
        "selected_by_source": payload.get("selected_by_source"),
        "ceiling_seconds": payload.get("ceiling_seconds"),
    }


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
    }
