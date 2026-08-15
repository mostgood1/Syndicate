"""The opening half of CLV, recorded compactly so it is not lost.

Audit §7 ranked fix **#1** — "make CLV computable without settlement" — needs
two numbers per market: the price we PUBLISHED (the opening) and the price at
the close. The close is already recoverable: `odds_refresh_tracking` stamps
`closing_line` on the pregame->live transition, and where that transition was
never observed the market's own history still carries every pregame
observation. Measured 2026-08-14 on `/api/ops/odds-history/inspect`: mlb
2026-08-13 had a stamped close on **18 of 1074** markets (1.7%) but
`history_points > 0` on **1074 of 1074** (100%, median 20 points).

**The opening is the half that is being lost.** The audit assumed it was
reachable "without touching the 367 MB chunk path". It is not:

- `data/prediction_ledger.json` holds **3** records — the portfolio's own
  positions, which is the `pending_count: 3` on `/api/portfolio/summary`. It is
  not the recommendation stream.
- The 8,276 recommendation records that DO carry an opening `quote` are written
  only to `evaluation_ledger_chunks/<date>.jsonl`.
- Those chunks are not merely expensive, they are SKIPPED at read time. From
  refresh-worker 2026-08-14T21:24:54Z:
  `SKIP_OVERSIZED_LEDGER_CHUNK path=2026-08-05.jsonl bytes=367229260
  ceiling=256000000`. And 19 of 21 dates in the window do not exist at all.

So today no opening price is readable for any date, while the closes for those
same markets are sitting in odds history. **Unrecorded is unrecoverable** — the
audit's own rule, and the reason this module exists and is deliberately tiny.

WHAT IT IS NOT. It does not compute CLV and it does not read odds history. The
join has a real unsolved problem (see `_opening_key`) and pairing an unfinished
join with an unwritten opening would lose another day of data while the join is
argued about. Recording is urgent; joining is not.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "OPENING_LEDGER_SUBDIR",
    "opening_ledger_path",
    "record_openings",
    "load_openings",
]

OPENING_LEDGER_SUBDIR = "clv_openings"

# Hard ceiling on one date's file. A first-sighting-only ledger over ~3.4k MLB
# market ids is kilobytes, so this is not a budget -- it is a tripwire for the
# dedup silently failing and turning an append-once file into an append-always
# one. That is exactly how `evaluation_ledger_chunks` reached 367 MB/day, and
# the failure is invisible until something tries to read it.
_MAX_LEDGER_BYTES = 16 * 1024 * 1024


def _reports_root() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root()


def opening_ledger_path(date: str, *, root: Path | str | None = None) -> Path:
    base = Path(root) if root is not None else _reports_root()
    return base / "intelligence" / OPENING_LEDGER_SUBDIR / f"{str(date).strip()}.jsonl"


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _opening_key(row: Mapping[str, Any]) -> str | None:
    """Identity of the thing whose price we are recording.

    OVER-SPECIFIED ON PURPOSE. The settlement join already failed this exact
    way -- `/api/ops/evaluation-settlement/status` reports **4,560
    `no_key_match`** against 8,276 records -- so this records every component
    any future join could need rather than guessing now which ones matter.

    `side` and `line` are in the key because they change the bet: home -1.5 and
    home -2.5 are different markets at the same book, and a ledger that
    collapses them records the first and silently discards the second.

    **The known unsolved problem, stated here so the joiner inherits it rather
    than rediscovers it:** odds history is keyed
    `event_id|home_team|away_team|market|bookmaker` and carries NO `side` and NO
    `line` -- the side lives as `entity` inside the history points. So this key
    does not join to that one directly, and the mapping from `side` to `entity`
    is the piece that must be measured against real data before any CLV number
    is published. Recording the full identity now is what makes that possible
    later; picking a lossy key now would not be.
    """
    event_id = str(row.get("event_id") or "").strip()
    market = str(row.get("market") or "").strip().lower()
    if not event_id or not market:
        # No identity, no record. A row we cannot key is a row we could never
        # join, and writing it would inflate the file while adding nothing.
        return None
    side = str(row.get("side") or "").strip().lower()
    line = _as_float(row.get("line"))
    quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    bookmaker = str((quote or {}).get("bookmaker") or "").strip().lower()
    # `player_name` and `segment` are in the key because leaving them out was
    # MEASURED to be lossy, not because they might be. Run over the 150 real
    # published rows on 2026-08-14, a key of
    # (event_id, market, side, line, bookmaker) collapsed **17 rows onto 7
    # keys** -- all player props, e.g. four distinct batters sharing
    # `batter_total_bases|over|1.5|betrivers` at prices 165/165/155/130. The
    # ledger would have kept ONE of those four and silently discarded the rest,
    # and worse, attributed whichever arrived first to all of them.
    #
    # `segment` joins it on the same argument rather than on a measurement: a
    # first-half line and a full-game line are different bets, and the field is
    # already on the row. Cheap to include, unrecoverable to omit.
    player_name = str(row.get("player_name") or "").strip().lower()
    segment = str(row.get("segment") or "").strip().lower()
    return "|".join(
        (
            f"event_id={event_id}",
            f"market={market}",
            f"player={player_name}",
            f"segment={segment}",
            f"side={side}",
            f"line={'' if line is None else line}",
            f"bookmaker={bookmaker}",
        )
    )


def _opening_record(row: Mapping[str, Any], key: str, captured_at: str) -> dict[str, Any]:
    quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    quote = quote or {}
    return {
        "key": key,
        "captured_at": captured_at,
        "sport": str(row.get("sport") or "").strip().lower() or None,
        "event_id": str(row.get("event_id") or "").strip() or None,
        "market": str(row.get("market") or "").strip().lower() or None,
        "side": str(row.get("side") or "").strip().lower() or None,
        "line": _as_float(row.get("line")),
        # Recorded as fields as well as in the key, so a consumer never has to
        # parse the key string back apart to know whose prop this was.
        "player_name": row.get("player_name"),
        "segment": row.get("segment"),
        "kind": row.get("kind"),
        "commence_time": row.get("commence_time"),
        "home_team": row.get("home_team"),
        "away_team": row.get("away_team"),
        # The opening price, and enough context to judge it later. `bookmaker`
        # matters because CLV must compare like with like -- the board publishes
        # the BEST book's price, so the close this is eventually paired with has
        # to be that same book's close (or an explicitly labelled consensus),
        # never whichever book happened to be quoting at the end.
        "price": quote.get("price"),
        "bookmaker": str(quote.get("bookmaker") or "").strip().lower() or None,
        "books_quoting": quote.get("books_quoting"),
        # OUR price at every book that quoted this side, captured at the same
        # instant as the opening. This is what makes a SAME-BOOK CLV possible:
        # odds history keeps a median of 2 books per (event, market) and the
        # board publishes the best of ~13, so the best book's own close is
        # usually absent. Measured 2026-08-14: exact (event, market, best_book)
        # existed in history for 3 of 55 mlb game rows. With every book's
        # opening recorded, the joiner can pair whichever book the close exists
        # for -- an unbiased comparison instead of a best-of-N one.
        "book_prices": quote.get("book_prices") or None,
        "fair_probability": _as_float(quote.get("fair_probability")),
        "fair_method": quote.get("fair_method"),
        # Carried so CLV can later be split by whether a model had a view at
        # all, which is §4's open question and the reason `#425` made skill
        # first-class. Absent stays absent rather than becoming null.
        "model_edge_pct": _as_float(row.get("model_edge_pct")),
        "ev_pct": _as_float(row.get("ev_pct")),
    }


def load_openings(date: str, *, root: Path | str | None = None) -> list[dict[str, Any]]:
    """Every opening recorded for `date`. Malformed lines are skipped, counted by absence."""
    path = opening_ledger_path(date, root=root)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
    return records


def record_openings(
    rows: Iterable[Mapping[str, Any]],
    *,
    date: str,
    now: datetime | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Append the FIRST price seen for each market on `date`. Never overwrite.

    First-sighting-only is the whole contract: the opening is the price we
    published first, so a later tick seeing the same market must not replace it.
    That also bounds the file to the number of distinct market ids in a day
    rather than to the number of ticks -- ~3.4k rows for MLB, kilobytes, versus
    the 367 MB/day the chunk ledger reaches by appending every tick.

    Returns counters rather than nothing, and returns them even when zero rows
    are new. A counter that only appears when it fires cannot distinguish "ran
    and everything was already recorded" from "never ran" -- the same lesson
    `#373`, `#381`, `#397` and `#400` each learned, and one this session paid
    for again on a log line four hours before writing this.
    """
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    captured_at = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    path = opening_ledger_path(date, root=root)

    seen: set[str] = set()
    for record in load_openings(date, root=root):
        key = record.get("key")
        if isinstance(key, str) and key:
            seen.add(key)
    already = len(seen)

    rows_in = 0
    unkeyable = 0
    duplicate = 0
    pending: list[dict[str, Any]] = []
    for row in rows:
        rows_in += 1
        if not isinstance(row, Mapping):
            unkeyable += 1
            continue
        key = _opening_key(row)
        if key is None:
            unkeyable += 1
            continue
        if key in seen:
            duplicate += 1
            continue
        seen.add(key)
        pending.append(_opening_record(row, key, captured_at))

    written = 0
    truncated = False
    if pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing_bytes = path.stat().st_size if path.exists() else 0
        with path.open("a", encoding="utf-8") as handle:
            for record in pending:
                line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
                # Stop at the tripwire rather than growing without bound. A
                # silent dedup failure must cost one truncated file, not a disk.
                if existing_bytes + len(line.encode("utf-8")) > _MAX_LEDGER_BYTES:
                    truncated = True
                    break
                handle.write(line)
                existing_bytes += len(line.encode("utf-8"))
                written += 1

    # PUSH IT TO WEB, because the worker's disk is not readable from anywhere a
    # person can look. `#208`: allowlisting in `HOT_ARTIFACT_PATTERNS` only
    # PERMITS this transfer; this call is what makes one happen. Without it the
    # allowlist entry is inert and the openings stay invisible — which is
    # exactly how this lane's own measurement would have been impossible to run
    # the next day.
    #
    # Only when something was actually written: a no-op tick has nothing new to
    # send, and re-pushing an unchanged ~90KB file every ~20 minutes is the kind
    # of periodic worker work that is never free on a 4GB container.
    #
    # Never raises. Losing the push costs visibility; letting it propagate would
    # cost the board.
    published: bool | None = None
    if written:
        try:
            from syndicate.features.shared.artifact_publisher import publish_hot_artifact

            published = bool(publish_hot_artifact(path))
        except Exception:
            published = False

    report = {
        "date": str(date),
        "path": str(path),
        "published": published,
        "rows_in": rows_in,
        "openings_written": written,
        "already_recorded": already,
        "duplicate_in_batch": duplicate,
        "unkeyable_rows": unkeyable,
        "truncated_at_ceiling": truncated,
        "total_openings": already + written,
    }
    print(
        "[clv_opening_ledger] OPENINGS date=%s rows_in=%d written=%d already=%d "
        "duplicate=%d unkeyable=%d truncated=%s"
        % (date, rows_in, written, already, duplicate, unkeyable, truncated),
        flush=True,
    )
    return report


def opening_ledger_enabled() -> bool:
    """Default ON.

    Absent must not mean off here. This records data that cannot be recovered
    later, so a missing env var costing a day of openings is a strictly worse
    failure than one costing a few kilobytes of disk. `#284`'s rule is to check
    the code's default for any key -- this is that default, stated.
    """
    raw = os.environ.get("SYNDICATE_CLV_OPENING_LEDGER_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}
