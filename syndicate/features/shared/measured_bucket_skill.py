"""Bucket-level skill: where a model succeeds or fails INSIDE a category.

`[2026-09-14, user decisions: "Category now, buckets next"; "then build the bucket search
on the recorder data"]`, lane `accuracy-assessment-0914`.

The category table (`measured_market_skill`) says whether a model beats the market on
AVERAGE over a sport x market. The user's point was that averages hide success at the
game and prop level. This module holds the bucket definitions and the table of VALIDATED
buckets; `scripts/bucket_search.py` measures them from `opportunity_population_ledger`
records, and `layer2_board._apply_skill_reliability` reads them at score time.

ONE DEFINITION. The search script and the scorer both call `bucket_ids` on a `view`, and
both views read the SAME logical fields: the recorder copies them from the very candidate
fields the scorer sees (`quote.fair_probability`, `quote.book_age_seconds`,
`quote.books_quoting`, `quote.fair_method`, `model_edge_pct`, `game_state`). A bucket
measured on records is therefore the bucket a live row falls into, by construction. A
second copy of the bands anywhere else is the drift this repo keeps paying for.

PRE-REGISTERED BANDS. Recorded in the lane block before any data was searched. Each
bucket is sport x market x segment x phase x ONE band from ONE dimension, never a
cross-product, so the number of comparisons a search makes is bounded and known.

HOW THE TABLE MOVES A SCORE (`bucket_factor`):
- a validated `skill_pocket` -> 1.0, cancelling the category demotion (never above 1.0:
  the score's own guard only lowers);
- a validated `skill_loss` -> max(FLOOR, 1 - GAIN * established_loss_rel), the same
  scale as the category table;
- a row matching BOTH a pocket and a loss -> None: the category factor stands. Two
  measured buckets disagreeing about one row is not evidence for either;
- no validated match -> None: the category factor stands.
An EMPTY table (the shipped state until a search validates something) changes nothing.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from syndicate.features.shared.measured_market_skill import SKILL_FLOOR, SKILL_GAIN

TABLE_PATH = Path(__file__).with_suffix(".json")

VERDICT_SKILL_POCKET = "skill_pocket"
VERDICT_SKILL_LOSS = "skill_loss"
VERDICT_PROFIT_POCKET = "profit_pocket"
VERDICT_PARITY = "parity"
VERDICT_INSUFFICIENT = "insufficient"

GRADABLE_MARKETS = frozenset({"h2h", "spreads", "totals", "btts"})
LIVE_STATES = frozenset({"live", "in_progress"})
PREGAME_STATES = frozenset({"pregame", "scheduled", "pre"})

# (dimension, [(band label, lower inclusive, upper exclusive)]). Upper None = unbounded.
DISAGREEMENT_BANDS: tuple[tuple[str, float, float | None], ...] = (
    ("0-2", 0.0, 2.0), ("2-5", 2.0, 5.0), ("5-10", 5.0, 10.0), ("10+", 10.0, None),
)
PRICE_BANDS: tuple[tuple[str, float, float | None], ...] = (
    ("long", 0.0, 0.35), ("mid", 0.35, 0.65), ("fav", 0.65, None),
)
QUOTE_AGE_BANDS: tuple[tuple[str, float, float | None], ...] = (
    ("fresh", 0.0, 120.0), ("aging", 120.0, 600.0), ("stale", 600.0, None),
)
BOOKS_BANDS: tuple[tuple[str, float, float | None], ...] = (
    ("1-2", 1.0, 3.0), ("3-6", 3.0, 7.0), ("7+", 7.0, None),
)
FAIR_METHODS = frozenset({"consensus", "sharp_anchor", "book_margin_model"})

DIMENSIONS: tuple[str, ...] = ("disagreement", "direction", "price", "quote_age", "books", "fair_method")


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _band(value: float | None, bands: tuple[tuple[str, float, float | None], ...]) -> str | None:
    if value is None:
        return None
    for label, lower, upper in bands:
        if value >= lower and (upper is None or value < upper):
            return label
    return None


def _parse_time(value: Any) -> Any:
    from datetime import datetime, timezone

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _phase(game_state: Any, *, sighted_at: Any = None, commence_time: Any = None) -> str:
    """live / pregame from the row's game state; when that is absent, from WHEN it was sighted.

    The published openings carried no game state before 2026-09-12. Where both exist (the
    2026-09-13 openings) the time rule agrees with the field: MLB field-live 1,116 vs sighted
    after first pitch 1,106; NFL 1,359 vs 1,359.
    """
    state = _norm(game_state)
    if state in LIVE_STATES:
        return "live"
    if state in PREGAME_STATES:
        return "pregame"
    sighted, start = _parse_time(sighted_at), _parse_time(commence_time)
    if sighted is not None and start is not None:
        return "pregame" if sighted < start else "live"
    return "unknown"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def view_from_candidate(row: Mapping[str, Any], *, now: Any = None) -> dict[str, Any]:
    """The bucket view of a Layer 2 candidate, read at score time (`now`, default the clock)."""
    from datetime import datetime, timezone

    quote = _mapping(row.get("quote"))
    return {
        "sport": _norm(row.get("sport")),
        "market": _norm(row.get("market")),
        "segment": _norm(row.get("segment")) or "full",
        "phase": _phase(row.get("game_state"), sighted_at=now or datetime.now(timezone.utc),
                        commence_time=row.get("commence_time")),
        "model_edge_pct": _num(row.get("model_edge_pct")),
        "fair_probability": _num(quote.get("fair_probability")),
        "book_age_seconds": _num(quote.get("book_age_seconds")),
        "books_quoting": _num(quote.get("books_quoting")),
        "fair_method": _norm(quote.get("fair_method")),
    }


def view_from_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """The bucket view of an `opportunity_population_ledger` record."""
    from syndicate.features.shared.opportunity_population_ledger import parse_population_key

    identity = parse_population_key(str(record.get("k") or ""))
    return {
        "sport": _norm(record.get("sport")),
        "market": _norm(identity.get("market")),
        "segment": _norm(identity.get("segment")) or "full",
        "phase": _phase(record.get("gs"), sighted_at=record.get("t"), commence_time=record.get("ct")),
        "model_edge_pct": _num(record.get("me")),
        "fair_probability": _num(record.get("fp")),
        "book_age_seconds": _num(record.get("ba")),
        "books_quoting": _num(record.get("bq")),
        "fair_method": _norm(record.get("fm")),
    }


def dimension_bands(view: Mapping[str, Any]) -> dict[str, str]:
    """dimension -> band for every dimension this view has a value for."""
    edge = _num(view.get("model_edge_pct"))
    out: dict[str, str] = {}
    disagreement = _band(abs(edge) if edge is not None else None, DISAGREEMENT_BANDS)
    if disagreement:
        out["disagreement"] = disagreement
    if edge is not None and edge != 0:
        out["direction"] = "for" if edge > 0 else "against"
    price = _band(_num(view.get("fair_probability")), PRICE_BANDS)
    if price:
        out["price"] = price
    age = _band(_num(view.get("book_age_seconds")), QUOTE_AGE_BANDS)
    if age:
        out["quote_age"] = age
    books = _band(_num(view.get("books_quoting")), BOOKS_BANDS)
    if books:
        out["books"] = books
    method = _norm(view.get("fair_method"))
    if method:
        out["fair_method"] = method if method in FAIR_METHODS else "other"
    return out


def bucket_prefix(view: Mapping[str, Any]) -> str:
    return "|".join((view.get("sport") or "", view.get("market") or "", view.get("segment") or "full",
                     view.get("phase") or "unknown"))


def bucket_ids(view: Mapping[str, Any]) -> list[str]:
    """Every pre-registered bucket this view belongs to (at most one per dimension)."""
    prefix = bucket_prefix(view)
    bands = dimension_bands(view)
    return [f"{prefix}|{dimension}={bands[dimension]}" for dimension in DIMENSIONS if dimension in bands]


def load_table(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Validated buckets only. A missing or malformed table is an EMPTY table."""
    target = Path(path) if path is not None else TABLE_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    buckets = payload.get("buckets") if isinstance(payload, Mapping) else None
    if not isinstance(buckets, Mapping):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for bucket_id, entry in buckets.items():
        if isinstance(entry, Mapping) and entry.get("verdict") in (VERDICT_SKILL_POCKET, VERDICT_SKILL_LOSS):
            out[str(bucket_id)] = dict(entry)
    return out


MEASURED_BUCKET_SKILL: dict[str, dict[str, Any]] = load_table()


def bucket_factor(
    view: Mapping[str, Any],
    *,
    table: Mapping[str, Mapping[str, Any]] | None = None,
    gain: float = SKILL_GAIN,
    floor: float = SKILL_FLOOR,
) -> float | None:
    """The score factor a validated bucket assigns, or None to leave the category factor.

    With no `table`, the source is the daily scorecard's validated overlay when it is enabled,
    present and unexpired, else the shipped static table (`skill_overlay.active_table`; USER
    DECISION 2026-09-17 "Auto-update measured skill", kill switch `SYNDICATE_SKILL_OVERLAY=off`).
    """
    if table is None:
        from syndicate.features.shared.skill_overlay import active_table

        source = active_table(MEASURED_BUCKET_SKILL)
    else:
        source = table
    if not source:
        return None
    matched = [source[bucket_id] for bucket_id in bucket_ids(view) if bucket_id in source]
    pockets = [entry for entry in matched if entry.get("verdict") == VERDICT_SKILL_POCKET]
    losses = [entry for entry in matched if entry.get("verdict") == VERDICT_SKILL_LOSS]
    if pockets and losses:
        return None
    if pockets:
        return 1.0
    if losses:
        factors = []
        for entry in losses:
            loss = _num(entry.get("established_loss_rel"))
            if loss is None or loss <= 0:
                continue
            factors.append(max(floor, 1.0 - gain * loss))
        return min(factors) if factors else None
    return None
