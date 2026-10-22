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

WHY THE FAIR-PRICE PROVENANCE IS STAMPED HERE (pricing plane v1, P1d). Since
1cdf5c17 / 5b5ad529 / 7d3efaf1 every board quote carries `fair_method`
(consensus | sharp_anchor | exchange_mid | two_sided_same_book |
book_margin_model), the anchor book, the devig method and the anchor's hold /
refusal state, and production has run `SYNDICATE_FAIR_ANCHOR=sharp_only` since
2026-09-09T00:40:13Z. The 3-day CLV reading due 09-12 has to split by
`fair_method` and by book EXACTLY -- did the sharp-anchored rows beat the close
where the consensus-priced rows did not -- and until this record carried the
stamps the only split available was by ERA, openings before versus after the
flag flipped, which is confounded by slate: a different set of games, books and
market mixes on either side of the cut. An opening is written once and never
rewritten, so a stamp that is not recorded at first sighting cannot be
reconstructed later from a board that has moved on. Copied flat from the quote
(`FAIR_PROVENANCE_FIELDS`), never re-derived, and `None` -- not absent, not a
default -- on a legacy row without them, so a split can never silently fold
unstamped rows into a tier.
"""

from __future__ import annotations

import json
import os
import threading
from collections import Counter, OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "FAIR_PROVENANCE_FIELDS",
    "OPENING_LEDGER_SUBDIR",
    "opening_ledger_path",
    "record_openings",
    "load_openings",
]

OPENING_LEDGER_SUBDIR = "clv_openings"

# The fair-price provenance stamps every opening carries, in record order. One
# list, imported by every downstream carrier that whitelists fields
# (`clv_join.compute_clv_for_date`, `order_clv.clv_for_orders`), so a stamp
# added here reaches the resolved rows without three lists having to agree.
# `fair_anchor_refusals` (a list) is deliberately absent: the record stays flat.
FAIR_PROVENANCE_FIELDS: tuple[str, ...] = (
    "fair_method",
    "fair_anchor_book",
    "fair_devig_method",
    "fair_consensus_prob",
    "fair_anchor_hold_pct",
    "fair_anchor_median_gap_pp",
    "fair_anchor_refusal",
)

# Hard ceiling on one date's file. A first-sighting-only ledger over ~3.4k MLB
# market ids is kilobytes, so this is not a budget -- it is a tripwire for the
# dedup silently failing and turning an append-once file into an append-always
# one. That is exactly how `evaluation_ledger_chunks` reached 367 MB/day, and
# the failure is invisible until something tries to read it.
#
# Re-sized 2026-09-09 (P1d): the "kilobytes" premise was already false -- the
# 2026-09-04 file measured 13,089,729 B over 17,515 openings (747 B/record)
# with every sport's props on the board, and the seven `FAIR_PROVENANCE_FIELDS`
# add ~200 B/record. At 16 MiB a Saturday slate would have truncated its
# evening openings, i.e. the tripwire would have eaten the exact rows the
# sharp-anchor CLV reading needs. 32 MiB keeps ~2.5x headroom over the largest
# measured day while still bounding an append-always failure to one file.
#
# RE-SIZED AND SPLIT BY SPORT 2026-10-22 (lane `clv-openings-ceiling`,
# `.syndicate/findings_2026-10-22_clv_openings_ceiling.md`). The 32 MiB
# tripwire WAS eating the evening: on the fleet it fired on 6 of 24 dates
# 09-30..10-23 (10-04, 10-10, 10-11, 10-17, 10-18, 10-21), and on 10-11 the
# file stopped at 19:03Z. 10-21, the one full date the price trail still
# covers, lost 3,939 openings of 36,710 (exact: the trail reproduces every
# other date's openings key for key). And the cut was CROSS-SPORT: NFL's
# Sunday props filled the shared file and MLB's LCS night lost its openings.
#
# So two ceilings, both tripwires for the dedup failing, neither a budget:
#   * `_MAX_SPORT_BYTES` per (date, sport). The largest sport-day measured is
#     NFL on 10-11: 20.0 MiB by the cut plus >= 8.6k openings after it, about
#     29-32 MiB uncapped. 64 MiB is ~2x that, and a runaway sport now costs
#     ITS OWN rows only -- every other sport keeps recording.
#   * `_MAX_LEDGER_BYTES` per date, all sports. The largest day measured is
#     10-11 at >= 43.5k openings, ~46 MiB with the pseudo-cut calibration;
#     128 MiB is ~2.75x that and still bounds a total failure to one file.
# Raising the ceiling was only affordable because dedup no longer re-reads the
# whole file each build -- see `_LedgerIndex`.
_MAX_LEDGER_BYTES = 128 * 1024 * 1024
_MAX_SPORT_BYTES = 64 * 1024 * 1024


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
        # THE OTHER SIDE(S) OF THE SAME MARKET, AS PRICED WHEN WE CHOSE.
        # `#626`(g). The opening ledger records one row per side we PUBLISH,
        # and we publish the side we took -- so before this the opposite leg
        # was absent from the ledger by construction, and 0 of 8,778 graded
        # MLB prop keys carried both sides. Carried through from the board's
        # quote rather than re-derived here: this module must not grow a second
        # opinion about what the market looked like.
        "other_sides": quote.get("other_sides") or None,
        "fair_probability": _as_float(quote.get("fair_probability")),
        "fair_method": quote.get("fair_method"),
        # The rest of the fair-price provenance (P1d): which anchor book priced
        # this side, devigged how, and what the anchor looked like at the
        # instant we chose. Stamped so the CLV reading splits by anchor tier
        # and book exactly, not by era. Copied from the quote, never
        # re-derived; a legacy row without them records None, never a default.
        "fair_anchor_book": quote.get("fair_anchor_book"),
        "fair_devig_method": quote.get("fair_devig_method"),
        "fair_consensus_prob": _as_float(quote.get("fair_consensus_prob")),
        "fair_anchor_hold_pct": _as_float(quote.get("fair_anchor_hold_pct")),
        "fair_anchor_median_gap_pp": _as_float(quote.get("fair_anchor_median_gap_pp")),
        "fair_anchor_refusal": quote.get("fair_anchor_refusal"),
        # Carried so CLV can later be split by whether a model had a view at
        # all, which is §4's open question and the reason `#425` made skill
        # first-class. Absent stays absent rather than becoming null.
        "model_edge_pct": _as_float(row.get("model_edge_pct")),
        "ev_pct": _as_float(row.get("ev_pct")),
        # IN-PLAY CONTEXT, AT THE INSTANT OF SIGHTING (lane
        # `layer2-live-scorecard-gate`, 2026-09-12). Without these an opening
        # cannot be split in-play vs pregame, or by how stale our view of the
        # price was -- the split the live board's results turn on. An in-play
        # reprice usually moves the line, which is a NEW key, so first-sighting-
        # only still records most in-play entries rather than their pregame
        # ancestor.
        #
        # FOUR FIELDS, NOT TEN, BY MEASUREMENT: the 2026-09-12 file was already
        # 17,499,898 B over 18,683 records (52% of `_MAX_LEDGER_BYTES`) at 2 PM
        # CT on a Saturday with the evening slate still to come, and every byte
        # here is paid on every record. Clock, score, lane and basis at sighting
        # were cut: useful, not needed for the split, ~150 B each record.
        # Copied from the row, never re-derived; absent stays None.
        "game_state": row.get("game_state"),
        "book_age_seconds": _as_float(quote.get("book_age_seconds")),
        "quote_seen_age_seconds": _as_float(quote.get("quote_seen_age_seconds")),
        "quote_source": quote.get("quote_source") if isinstance(quote.get("quote_source"), str) else None,
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


# ---------------------------------------------------------------------------
# WHAT IS ALREADY ON DISK, READ INCREMENTALLY (lane `clv-openings-ceiling`).
#
# Dedup used to call `load_openings` on every build: every record of the day
# parsed into a dict, just to collect the keys. Measured on the fleet
# 2026-10-22 at nice 19 on the 33,145-record 10-11 file: 9.9 s and a 155 MiB
# peak, per build, and that cost grows with the very ceiling this lane raised.
# The index keeps the keys and per-sport bytes per file and on each call reads
# only the bytes appended since the last one -- by this process or any other.
#
# It is trusted only while the file is provably the one it indexed: same
# device and inode, not shorter than what was consumed, and the bytes just
# before the consumed offset unchanged. Anything else (a replaced, truncated or
# rewritten file) rebuilds from byte 0, so a stale index can cost a re-read but
# never a wrong dedup answer.
# ---------------------------------------------------------------------------
_INDEX_TAIL_BYTES = 64
_INDEX_MAX_FILES = 4


@dataclass
class _LedgerIndex:
    identity: tuple[int, int] = (0, 0)
    offset: int = 0
    tail: bytes = b""
    keys: set[str] = field(default_factory=set)
    sport_bytes: Counter = field(default_factory=Counter)
    # Bytes after `offset` that do not end in a newline: a torn final write.
    pending_partial: bool = False


_INDEX: "OrderedDict[str, _LedgerIndex]" = OrderedDict()
_INDEX_LOCK = threading.Lock()


def _sport_slot(value: Any) -> str:
    return str(value or "").strip().lower()


def _index_for(path: Path) -> _LedgerIndex:
    """The index of `path` brought up to its current end. Caller holds `_INDEX_LOCK`."""
    cache_key = str(path)
    try:
        stat = path.stat()
    except OSError:
        _INDEX.pop(cache_key, None)
        return _LedgerIndex()
    identity = (stat.st_dev, stat.st_ino)
    index = _INDEX.get(cache_key)
    if index is not None and (index.identity != identity or stat.st_size < index.offset):
        index = None
    try:
        handle = path.open("rb")
    except OSError:
        _INDEX.pop(cache_key, None)
        return _LedgerIndex()
    with handle:
        if index is not None and index.tail:
            handle.seek(index.offset - len(index.tail))
            if handle.read(len(index.tail)) != index.tail:
                index = None
        if index is None:
            index = _LedgerIndex(identity=identity)
        handle.seek(index.offset)
        offset = index.offset
        partial = False
        for raw in handle:
            if not raw.endswith(b"\n"):
                # Left unconsumed: it is either a torn write or one still in
                # flight, and the next call re-reads it from here.
                partial = True
                break
            offset += len(raw)
            text = raw.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except (ValueError, TypeError):
                index.sport_bytes[""] += len(raw)
                continue
            if not isinstance(parsed, dict):
                index.sport_bytes[""] += len(raw)
                continue
            index.sport_bytes[_sport_slot(parsed.get("sport"))] += len(raw)
            key = parsed.get("key")
            if isinstance(key, str) and key:
                index.keys.add(key)
        index.offset = offset
        index.pending_partial = partial
        if offset:
            handle.seek(max(0, offset - _INDEX_TAIL_BYTES))
            index.tail = handle.read(offset - max(0, offset - _INDEX_TAIL_BYTES))
        else:
            index.tail = b""
    _INDEX[cache_key] = index
    _INDEX.move_to_end(cache_key)
    while len(_INDEX) > _INDEX_MAX_FILES:
        _INDEX.popitem(last=False)
    return index


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
    # Read twice below (openings, then departures), so an iterator must not be
    # consumed by the first pass.
    rows = list(rows)

    rows_in = 0
    unkeyable = 0
    duplicate = 0
    written = 0
    dropped: Counter = Counter()  # (scope, sport) -> rows refused at a ceiling
    bytes_on_disk = 0
    with _INDEX_LOCK:
        index = _index_for(path)
        on_disk = index.keys
        already = len(on_disk)
        batch_seen: set[str] = set()
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
            if key in on_disk or key in batch_seen:
                duplicate += 1
                continue
            batch_seen.add(key)
            pending.append(_opening_record(row, key, captured_at))

        try:
            bytes_on_disk = path.stat().st_size
        except OSError:
            bytes_on_disk = 0
        if pending:
            sport_bytes = Counter(index.sport_bytes)
            chunks: list[str] = []
            # A torn final line would swallow the first record appended after
            # it, so close it off: the fragment stays unreadable, as before, and
            # the opening behind it does not join it.
            if index.pending_partial:
                chunks.append("\n")
                bytes_on_disk += 1
            for record in pending:
                line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
                size = len(line.encode("utf-8"))
                sport = _sport_slot(record.get("sport"))
                # Refuse at a tripwire rather than growing without bound. A
                # silent dedup failure must cost one sport's rows, then one
                # file -- never a disk, and never ANOTHER sport's evening. A
                # refused row is not marked seen, so it is retried next build.
                if bytes_on_disk + size > _MAX_LEDGER_BYTES:
                    dropped[("day", sport)] += 1
                    continue
                if sport_bytes[sport] + size > _MAX_SPORT_BYTES:
                    dropped[("sport", sport)] += 1
                    continue
                chunks.append(line)
                bytes_on_disk += size
                sport_bytes[sport] += size
                written += 1
            if written:
                path.parent.mkdir(parents=True, exist_ok=True)
                # One write per build, so a crash tears at most one line.
                with path.open("a", encoding="utf-8") as handle:
                    handle.write("".join(chunks))

    truncated = bool(dropped)
    dropped_by_sport: Counter = Counter()
    for (scope, sport), count in sorted(dropped.items()):
        dropped_by_sport[sport or "unknown"] += count
        # LOUD, on every build it fires: this is a tripwire, and the last one
        # fired on 6 of 24 days for a month with only `truncated=True` buried
        # in a summary line to say so.
        print(
            "[clv_opening_ledger] OPENINGS_CEILING_HIT date=%s scope=%s sport=%s dropped=%d "
            "bytes_on_disk=%d ceiling=%d"
            % (
                date,
                scope,
                sport or "unknown",
                count,
                bytes_on_disk,
                _MAX_LEDGER_BYTES if scope == "day" else _MAX_SPORT_BYTES,
            ),
            flush=True,
        )

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
        # How many openings a ceiling refused this build, and whose. A count,
        # not just the flag: a fired tripwire has to say what it cost.
        "dropped_at_ceiling": sum(dropped.values()),
        "dropped_by_sport": dict(dropped_by_sport),
        "bytes_on_disk": bytes_on_disk,
        "total_openings": already + written,
    }
    # WHICH +EV PRICES LEFT THE BOARD SINCE THE LAST BUILD (lane
    # `layer2-live-scorecard-gate`, 2026-09-13; `clv_departure_ledger`). Called
    # HERE because every Layer 2 build already reaches this function with its
    # full row set, and with the same clock: a departure's `gone_by` and an
    # opening's `captured_at` are the same build stamp, which is what lets the
    # scorecard join them. Never raises into the openings -- losing a departure
    # costs a measurement, losing an opening costs a day.
    try:
        from syndicate.features.shared.clv_departure_ledger import (
            departure_ledger_enabled,
            record_departures,
        )

        report["departures"] = (
            record_departures(rows, date=str(date), now=stamp, root=root)
            if departure_ledger_enabled()
            else {"enabled": False}
        )
    except Exception as exc:
        report["departures"] = {"error": f"{type(exc).__name__}: {exc}"}
    print(
        "[clv_opening_ledger] OPENINGS date=%s rows_in=%d written=%d already=%d "
        "duplicate=%d unkeyable=%d truncated=%s dropped=%d bytes=%d"
        % (date, rows_in, written, already, duplicate, unkeyable, truncated, sum(dropped.values()), bytes_on_disk),
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
