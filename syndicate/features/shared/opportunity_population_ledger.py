"""Every Layer 2 opportunity the board PRICED, recorded once per day -- published or not.

WHY THIS EXISTS. `[2026-09-14, user decision: "Build it for all sports"]`, lane
`accuracy-assessment-0914`. The user's direction was "we should still evaluate
EVERYTHING but based on what we learn about models/optimizations/and bucketing - this
should impact the actual SCORING and where the opps end up surfaced on the layer 2
board". Finding WHERE a model succeeds -- a bucket inside a category that loses on
average -- needs outcomes for the whole population the board priced, not only the rows
it published.

WHY NOT `clv_opening_ledger`. That ledger records the PUBLISHED rows (the shortlist).
Grading buckets from it is the 2026-09-12 FORBIDDEN shape, "measuring model quality on a
population defined by a PUBLICATION filter": when publishing changes, the metric freezes
rather than shrinks, and a bucket can look good only because the filter kept its
winners. This ledger records the candidates `build_layer2_rows` built, BEFORE
`select_shortlist` cuts them. Whether a row was published joins back from
`clv_openings` on the same identity (event, market, player, segment, side, line).

BOUNDED BY DISTINCT MARKETS PER DAY, NOT BY BUILDS. First sighting per identity, like
the openings ledger. Measured on the served 2026-09-14 shortlist rows with this record
shape: ~320 B per record and ~65 B per key; one build considered 14,471 opportunities
across sports. A day is therefore single-digit to ~20 MB per sport, under `MAX_DAY_BYTES`.

WHY PARTS AND A KEY SIDECAR.
- Dedup must know what is already recorded. Re-reading a day's records every build to
  rebuild that set is avoidable work on a 4 GB worker, so keys live in a small sidecar.
- One ever-growing file would be re-sent whole on every publish. Records go to parts
  that close at `PART_BYTES`, and only parts written in THIS call are published.

DEFAULT OFF (`SYNDICATE_OPPORTUNITY_POPULATION_LEDGER`). The user's decision said the
worker's memory cost is measured first. It ships inert, and is switched on only after
web carries the `HOT_ARTIFACT_PATTERNS` entry (a push before that is refused) and one
build's cost has been read.

THE RECORD, compact on purpose (it repeats tens of thousands of times a day). The
identity lives in `k` in `KEY_FIELDS` order; `parse_population_key` splits it back.
    k  identity key                  t  captured_at (UTC)
    sport, kind, ct (commence_time), ht / at (home / away team, for the final-score join)
    px price       fp fair_probability   fm fair_method   bq books_quoting
    ba book_age_seconds
    ev ev_pct      me model_edge_pct     eb ev_basis
    sc score       vp value_pct          sr skill_reliability (only when it applied)
    ss model_skill.status   vc verdict_class   el established_loss_rel
    ln board_lane  gs game_state   la live_aware (only when true)
Values are copied from the candidate, never re-derived; an absent value records null.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "ENV_FLAG",
    "KEY_FIELDS",
    "MAX_DAY_BYTES",
    "PART_BYTES",
    "POPULATION_SUBDIR",
    "keys_path",
    "parse_population_key",
    "part_path",
    "population_key",
    "population_ledger_enabled",
    "population_record",
    "record_population",
]

POPULATION_SUBDIR = "opportunity_population"
ENV_FLAG = "SYNDICATE_OPPORTUNITY_POPULATION_LEDGER"
KEY_FIELDS: tuple[str, ...] = ("event_id", "market", "player_name", "segment", "side", "line")

# A part closes before this many bytes; only parts written in a call are published.
PART_BYTES = 4 * 1024 * 1024
# Per (date, sport). A tripwire for the dedup failing and turning append-once into
# append-always, sized ~3x above the largest day the measured record size predicts.
MAX_DAY_BYTES = 64 * 1024 * 1024

_ENABLED_VALUES = frozenset({"1", "true", "on", "yes"})


def population_ledger_enabled() -> bool:
    """Off unless the flag says on. Unknown or malformed stays off."""
    return str(os.environ.get(ENV_FLAG) or "").strip().lower() in _ENABLED_VALUES


def _reports_root() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root()


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    cleaned = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in text)
    return cleaned or "unknown"


def population_dir(root: Path | str | None = None) -> Path:
    base = Path(root) if root is not None else _reports_root()
    return base / "intelligence" / POPULATION_SUBDIR


def part_path(date: Any, sport: Any, part: int, *, root: Path | str | None = None) -> Path:
    """`<date>__<sport>__partNNN.jsonl` -- flat, so one `*.jsonl` allowlist entry covers it."""
    return population_dir(root) / f"{_slug(date)}__{_slug(sport)}__part{int(part):03d}.jsonl"


def keys_path(date: Any, sport: Any, *, root: Path | str | None = None) -> Path:
    """The dedup sidecar. Not `.jsonl`, so it is never published."""
    return population_dir(root) / f"{_slug(date)}__{_slug(sport)}.keys"


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return round(parsed, 4)


def population_key(row: Mapping[str, Any]) -> str | None:
    """Identity of one priced side. None when it cannot be keyed (no event or market).

    No bookmaker: this records the FIRST price the board priced for the side, not one
    record per book. Side, line, player and segment are in the key because each changes
    the bet (the openings ledger measured player-less keys collapsing 17 rows onto 7).
    """
    event_id = str(row.get("event_id") or "").strip()
    market = str(row.get("market") or "").strip().lower()
    if not event_id or not market:
        return None
    line = _as_float(row.get("line"))
    parts = (
        event_id,
        market,
        str(row.get("player_name") or "").strip().lower(),
        str(row.get("segment") or "").strip().lower(),
        str(row.get("side") or "").strip().lower(),
        "" if line is None else repr(line),
    )
    if any("\n" in part or "|" in part for part in parts):
        return None
    return "|".join(parts)


def parse_population_key(key: str) -> dict[str, Any]:
    """Split a key back into `KEY_FIELDS`. `line` comes back as a float or None."""
    values = str(key).split("|")
    if len(values) != len(KEY_FIELDS):
        return {}
    out: dict[str, Any] = dict(zip(KEY_FIELDS, values))
    out["line"] = _as_float(out["line"]) if out["line"] else None
    return out


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def population_record(row: Mapping[str, Any], key: str, captured_at: str, *, sport: Any) -> dict[str, Any]:
    quote = _mapping(row.get("quote"))
    projection = _mapping(row.get("projection"))
    score = _mapping(row.get("score"))
    skill = _mapping(projection.get("model_skill"))
    return {
        "k": key,
        "t": captured_at,
        "sport": str(row.get("sport") or sport or "").strip().lower() or None,
        "kind": row.get("kind"),
        "ct": row.get("commence_time"),
        # Team names, so a record joins to a final score (`layer2_live_scorecard.match_chip`
        # matches on names; the scoreboard does not carry the odds feed's event id).
        "ht": row.get("home_team"),
        "at": row.get("away_team"),
        "px": quote.get("price"),
        "fp": _as_float(quote.get("fair_probability")),
        "fm": quote.get("fair_method"),
        "bq": quote.get("books_quoting"),
        "ba": _as_float(quote.get("book_age_seconds")),
        "ev": _as_float(row.get("ev_pct")),
        "me": _as_float(row.get("model_edge_pct")),
        "eb": row.get("ev_basis"),
        "sc": _as_float(score.get("score")),
        "vp": _as_float(score.get("value_pct")),
        "sr": _as_float(score.get("skill_reliability")),
        "ss": skill.get("status"),
        "vc": skill.get("verdict_class"),
        "el": _as_float(skill.get("established_loss_rel")),
        "ln": row.get("board_lane"),
        "gs": row.get("game_state"),
        "la": True if projection.get("live_aware") else None,
    }


def _existing_parts(date: Any, sport: Any, root: Path | str | None) -> list[tuple[int, Path]]:
    directory = population_dir(root)
    if not directory.exists():
        return []
    prefix = f"{_slug(date)}__{_slug(sport)}__part"
    found: list[tuple[int, Path]] = []
    for path in directory.glob(f"{prefix}*.jsonl"):
        number = path.name[len(prefix):-len(".jsonl")]
        if number.isdigit():
            found.append((int(number), path))
    return sorted(found)


LIVE_KEY_SUFFIX = "#live"


def seen_key(row: Mapping[str, Any], key: str, *, now: datetime) -> str:
    """The DEDUP key: the identity, plus `#live` when the side is priced in play.

    `[2026-09-17, lane model-scorecard-cron, user decision "Recorder live coverage"]`. The
    dedup used the identity alone, so a side first priced pregame was never recorded again
    once its game went live unless its LINE moved. Measured on the 2026-09-15/16 production
    records: 5,406 of 8,685 (62%) MLB pregame sides in games that went live had no live row,
    and h2h (no line) could never produce one. A side is now recorded once per phase. The
    record's `k` is unchanged; only the sidecar distinguishes the two sightings, and `gs`
    / `t` on the record say which one it is.
    """
    from syndicate.features.shared.measured_bucket_skill import _phase

    phase = _phase(row.get("game_state"), sighted_at=now, commence_time=row.get("commence_time"))
    return key + LIVE_KEY_SUFFIX if phase == "live" else key


def _load_keys(path: Path) -> set[str]:
    seen: set[str] = set()
    if not path.exists():
        return seen
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            key = line.rstrip("\n")
            if key:
                seen.add(key)
    return seen


def record_population(
    rows: Iterable[Mapping[str, Any]],
    *,
    sport: Any,
    date: Any,
    now: datetime | None = None,
    root: Path | str | None = None,
    part_bytes: int = PART_BYTES,
    max_day_bytes: int = MAX_DAY_BYTES,
    publish: bool = True,
) -> dict[str, Any]:
    """Append the FIRST sighting of each priced side for (`date`, `sport`). Never overwrite.

    Returns counters even when nothing is new: a counter that only appears when it fires
    cannot tell "ran, all already recorded" from "never ran".
    """
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    captured_at = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    sidecar = keys_path(date, sport, root=root)
    seen = _load_keys(sidecar)
    already = len(seen)

    rows_in = unkeyable = duplicate = live_written = 0
    pending: list[tuple[str, dict[str, Any]]] = []
    for row in rows or ():
        rows_in += 1
        if not isinstance(row, Mapping):
            unkeyable += 1
            continue
        key = population_key(row)
        if key is None:
            unkeyable += 1
            continue
        dedup = seen_key(row, key, now=stamp)
        if dedup in seen:
            duplicate += 1
            continue
        seen.add(dedup)
        if dedup != key:
            live_written += 1
        pending.append((dedup, population_record(row, key, captured_at, sport=sport)))

    written = 0
    truncated = False
    touched: list[Path] = []
    if pending:
        population_dir(root).mkdir(parents=True, exist_ok=True)
        parts = _existing_parts(date, sport, root)
        part = parts[-1][0] if parts else 0
        part_size = parts[-1][1].stat().st_size if parts else 0
        day_bytes = sum(path.stat().st_size for _, path in parts)
        written_keys: list[str] = []
        handle = None
        try:
            for key, record in pending:
                line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
                size = len(line.encode("utf-8"))
                if day_bytes + size > max_day_bytes:
                    truncated = True
                    break
                if part_size > 0 and part_size + size > part_bytes:
                    if handle is not None:
                        handle.close()
                        handle = None
                    part += 1
                    part_size = 0
                if handle is None:
                    path = part_path(date, sport, part, root=root)
                    handle = path.open("a", encoding="utf-8")
                    if path not in touched:
                        touched.append(path)
                handle.write(line)
                part_size += size
                day_bytes += size
                written += 1
                written_keys.append(key)
        finally:
            if handle is not None:
                handle.close()
        # Keys AFTER records: a crash in between costs a duplicate record later, never a
        # record silently skipped because its key was written first.
        if written_keys:
            with sidecar.open("a", encoding="utf-8") as keys_handle:
                keys_handle.write("\n".join(written_keys) + "\n")

    published = 0
    if publish and written:
        try:
            from syndicate.features.shared.artifact_publisher import publish_hot_artifact

            for path in touched:
                if publish_hot_artifact(path):
                    published += 1
        except Exception:
            pass

    report = {
        "sport": str(sport),
        "date": str(date),
        "rows_in": rows_in,
        "written": written,
        "already_recorded": already,
        "duplicate": duplicate,
        "unkeyable": unkeyable,
        "live_pending": live_written,
        "truncated_at_day_ceiling": truncated,
        "parts_touched": len(touched),
        "parts_published": published,
    }
    print(
        "[opportunity_population] POPULATION sport=%s date=%s rows_in=%d written=%d already=%d "
        "duplicate=%d unkeyable=%d live_pending=%d parts_touched=%d published=%d truncated=%s"
        % (sport, date, rows_in, written, already, duplicate, unkeyable, live_written, len(touched), published,
           truncated),
        flush=True,
    )
    return report
