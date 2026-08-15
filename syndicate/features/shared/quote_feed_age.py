"""How old is the newest quote we have? The question nothing could answer.

MEASURED 2026-08-15 (`.syndicate/tier5_quote_to_ui_WINDOW2_2026-08-15.md`): MLB
quote capture stopped at 11:07Z and did not resume until 16:56Z -- **5.8 hours**.
Throughout that outage:

  - the live-refresh tick ran every ~60 s and reported `ok`
  - Layer 2 rebuilt every ~5 min (6.1 / 5.3 / 4.8 min gaps -- the healthiest
    ever measured on this system)
  - the board served 150 rows and looked entirely normal
  - end-to-end staleness rose smoothly from 5.51 h to 5.80 h, one second per
    second, because nothing upstream was moving

**Every existing instrument was green for six hours.** The board cannot see this
because it reports on ITS OWN build, and its build was healthy; it was building
promptly from a frozen input. A cadence metric cannot see it either -- the loop
kept ticking on schedule, it was simply refused every time.

The only quantity that moves during this failure is the AGE OF THE NEWEST
SAMPLE, and nothing in the system computed it. That is what this module is.

WHY IT IS SAFE TO CALL FROM THE WEB SERVICE. Reading the newest `captured_at`
does not require reading the shard: the file is append-ordered, so the last
complete line carries it. This seeks to the end and reads a bounded tail
(64 KB), so it costs the same on today's 10 MB MLB shard as on the 217 MB
post-book-widening ones -- no full parse, no heavy compute in a request path.

WHAT THIS DELIBERATELY DOES NOT DO: decide what to do about it. It reports an
age and compares it against one explicit, env-tunable threshold. It does not
infer the slate regime -- the tick's own `anyLive` was `true` today while the
board carried zero live rows in any sport, so regime inference from existing
signals is not currently trustworthy enough to gate an alarm on.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Read at call time, not import time, so a deploy-free env change takes effect.
_THRESHOLD_ENV = "SYNDICATE_QUOTE_FEED_STALE_SECONDS"

# 3 hours. Chosen against MEASURED extremes, not picked round:
#   - the worst healthy pregame gap ever measured is 123 min (2026-08-15) and
#     the ledger's empty-slate figure is 121.6 min, so a threshold at or below
#     2 h fires on normal pregame operation and would be muted within a week
#   - the outage this exists to catch was 5.8 h
# 3 h is the widest gap that is still unambiguously wrong. It is a DETECTION
# floor, not a target: during a live slate the feed runs at ~60 s, so a 3 h
# alarm is ~180x slower than it could be. The honest fix is per-regime
# thresholds once a trustworthy regime signal exists; this is the version that
# does not depend on one.
_DEFAULT_STALE_SECONDS = 10800

# Bounded tail. Comfortably larger than one JSON line (production rows run
# ~300-600 bytes) while staying O(1) against a 217 MB shard.
_TAIL_BYTES = 65536

STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_UNKNOWN = "unknown"


def stale_threshold_seconds() -> int:
    raw = str(os.environ.get(_THRESHOLD_ENV) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_STALE_SECONDS
    return value if value > 0 else _DEFAULT_STALE_SECONDS


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def newest_captured_at(path: Path) -> str | None:
    """The newest `captured_at` in an append-ordered shard, read in O(1).

    Returns None when the file is absent, empty, or carries no parseable
    `captured_at` in its tail -- all of which are UNKNOWN, never OK. See
    `feed_age` for why that distinction is the whole point.

    Scans the tail backwards line by line rather than trusting the very last
    one: a shard being appended to concurrently can end mid-line, and a torn
    final line must not be read as "no data".
    """
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size <= 0:
        return None
    try:
        with path.open("rb") as handle:
            start = max(0, size - _TAIL_BYTES)
            handle.seek(start)
            chunk = handle.read(size - start)
    except OSError:
        return None

    lines = chunk.split(b"\n")
    # A tail that starts mid-file almost always begins mid-line; drop it rather
    # than fail to parse it. (When start == 0 the first line is genuinely whole.)
    if start > 0 and lines:
        lines = lines[1:]
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(row, Mapping):
            continue
        stamp = row.get("captured_at") or row.get("snapshot_ts")
        if _parse_ts(stamp) is not None:
            return str(stamp)
    return None


def feed_age(
    sport: str,
    date_str: str,
    *,
    now: datetime | None = None,
    threshold_seconds: int | None = None,
) -> dict[str, Any]:
    """Age of the newest quote sample for one sport, with a verdict.

    UNKNOWN IS NOT OK, and that is load-bearing rather than tidy. The failure
    this alarm exists for is "the feed stopped and everything looked fine", so
    a version that maps a missing or unreadable shard onto its healthy branch
    reproduces the exact bug at a different layer. A shard that cannot be read
    is a thing to look at, not a thing to pass.
    """
    from syndicate.features.shared.odds_book_quotes import book_quotes_path

    threshold = int(threshold_seconds) if threshold_seconds else stale_threshold_seconds()
    moment = now or datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "sport": str(sport or "").strip().lower(),
        "date": str(date_str or ""),
        "threshold_seconds": threshold,
        "newest_captured_at": None,
        "age_seconds": None,
        "status": STATUS_UNKNOWN,
        "reason": None,
    }

    try:
        path = book_quotes_path(sport, date_str)
    except Exception as exc:  # a bad sport/date must not 500 the whole report
        result["reason"] = f"cannot resolve shard path: {type(exc).__name__}"
        return result

    result["path"] = str(path)
    if not path.exists():
        result["reason"] = "no quote shard for this sport and date"
        return result

    stamp = newest_captured_at(path)
    if stamp is None:
        result["reason"] = "shard carries no parseable captured_at in its tail"
        return result

    parsed = _parse_ts(stamp)
    if parsed is None:  # newest_captured_at already validated it; belt and braces
        result["reason"] = f"unparseable captured_at: {stamp!r}"
        return result

    age = (moment - parsed).total_seconds()
    result["newest_captured_at"] = stamp
    result["age_seconds"] = round(age, 1)
    if age > threshold:
        result["status"] = STATUS_STALE
        result["reason"] = (
            f"newest quote is {round(age / 60.0, 1)} min old, over the "
            f"{round(threshold / 60.0, 1)} min threshold"
        )
    else:
        result["status"] = STATUS_OK
    return result


def feed_age_report(
    sports: Iterable[str],
    date_str: str,
    *,
    now: datetime | None = None,
    threshold_seconds: int | None = None,
) -> dict[str, Any]:
    """Per-sport ages plus one roll-up verdict.

    `worst_status` is STALE if ANY sport is stale, else UNKNOWN if any is
    unknown, else OK. Ordered so that a single dead feed cannot be averaged away
    by seven healthy ones -- today's outage was one sport out of eight.
    """
    per_sport = {
        str(sport).strip().lower(): feed_age(
            sport, date_str, now=now, threshold_seconds=threshold_seconds
        )
        for sport in sports
        if str(sport or "").strip()
    }
    statuses = {entry["status"] for entry in per_sport.values()}
    if STATUS_STALE in statuses:
        worst = STATUS_STALE
    elif STATUS_UNKNOWN in statuses or not statuses:
        worst = STATUS_UNKNOWN
    else:
        worst = STATUS_OK
    return {
        "date": str(date_str or ""),
        "threshold_seconds": int(threshold_seconds)
        if threshold_seconds
        else stale_threshold_seconds(),
        "worst_status": worst,
        "stale_sports": sorted(
            s for s, e in per_sport.items() if e["status"] == STATUS_STALE
        ),
        "unknown_sports": sorted(
            s for s, e in per_sport.items() if e["status"] == STATUS_UNKNOWN
        ),
        "per_sport": per_sport,
    }
