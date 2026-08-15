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

# Fallback for a sport with no measured entry below. Deliberately the old global
# value, so an unknown sport behaves exactly as it did before this change.
_DEFAULT_STALE_SECONDS = 10800

# PER-SPORT THRESHOLDS, SET FROM MEASURED CADENCE.
#
# The single global 3 h value this replaces was BOTH too slow and too tight,
# because the feeds' normal cadences span a 173x range. Measured on production
# shards 2026-08-15 (full day, distinct `captured_at` gaps, read from the
# artifacts rather than the logs):
#
#     sport   captures   p50 gap    p90     max
#     nfl        128      1.0 min    30     244
#     mlb         16     31.0 min   349     448
#     wnba        14    122.0 min   314     448
#     soccer      91    173.0 min   248     558
#
# **p50 IS THE ONLY ROBUST BASE HERE, and that is not a stylistic preference.**
# p90 and max are inflated by the overnight window for every sport, and for MLB
# they are inflated by the 5.8 h starvation this alarm exists to catch. Setting
# a threshold off MLB's p90 (349 min) would bake the outage into "normal" and
# guarantee the alarm never fires on a repeat of it.
#
# **EACH DEFAULT IS SET ABOVE ITS SPORT'S MEASURED HEALTHY GAPS, NOT off p50.**
# I first set these at ~3x p50 and the existing
# `test_healthy_pregame_gap_does_not_false_alarm` went red: it pins the real
# 123-min MLB pregame gap (09:06->11:07Z), and a 2 h MLB threshold fires on it.
# p50 is the right base for COMPARING feeds and the wrong one for setting a
# floor, because these distributions have long quiet tails and the alarm must
# clear the tail, not the middle.
#
# TWO CONSEQUENCES WORTH STATING BEFORE SOMEONE REDISCOVERS THEM:
#   1. NFL improves 3 h -> 2 h. Its p90 is 30 min, so 2 h is unambiguous while
#      still clearing its quiet stretches.
#   2. **Soccer gets LOOSER (3 h -> 7 h), and that is a correction, not a
#      regression.** Soccer's p50 is 173 min, so the old 180 min global flagged
#      it on roughly half of NORMAL operation. The `0c65a832` deploy note's
#      "caught soccer STALE at 340.9 min" was therefore substantially a
#      threshold artifact -- 340.9 min is above soccer's p90 (248) so the feed
#      was elevated, but an alarm that fires on half of normal traffic is muted
#      within a week, which is what makes alarms worthless.
#
# **KNOWN LIMIT, UNSOLVED HERE: an age-only alarm cannot tell "quiet" from
# "broken".** Every sport's max gap (244-558 min) is an overnight or
# between-slate window, not a fault. Clearing those tails is what keeps all
# four thresholds in hours rather than minutes. The real fix is to gate on
# whether the sport has games scheduled in the window -- then a 10-minute
# silence during a live slate is actionable. That needs a schedule signal this
# module deliberately does not reach for; per-sport is strictly better than one
# global, and is not the end state.
_DEFAULT_STALE_SECONDS_BY_SPORT: dict[str, int] = {
    "nfl": 7200,      # p50 1 min,   p90  30 min -> 2 h clears the quiet stretches
    "mlb": 10800,     # p50 31 min,  healthy pregame worst 123 min -> 3 h, PINNED BY TEST
    "wnba": 21600,    # p50 122 min, p90 314 min -> 6 h
    "soccer": 25200,  # p50 173 min, p90 248 min, max 558 -> 7 h
}

# Per-sport env override, checked before the global one:
#   SYNDICATE_QUOTE_FEED_STALE_SECONDS_MLB=5400
_SPORT_THRESHOLD_ENV_PREFIX = "SYNDICATE_QUOTE_FEED_STALE_SECONDS_"

# Bounded tail. Comfortably larger than one JSON line (production rows run
# ~300-600 bytes) while staying O(1) against a 217 MB shard.
_TAIL_BYTES = 65536

STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_UNKNOWN = "unknown"


def _positive_int(raw: Any) -> int | None:
    """An env value that is absent, unparseable or <= 0 yields None, never a guess."""
    try:
        value = int(str(raw or "").strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def stale_threshold_seconds(sport: Any = None) -> int:
    """The stale threshold for one sport, in seconds.

    PRECEDENCE, most specific first:
      1. `SYNDICATE_QUOTE_FEED_STALE_SECONDS_<SPORT>` -- one feed, one number
      2. `SYNDICATE_QUOTE_FEED_STALE_SECONDS` -- the old global, still honoured
         so an operator can flatten every sport in one move during an incident
      3. this sport's measured default
      4. `_DEFAULT_STALE_SECONDS` for a sport with no measured entry

    The global sits ABOVE the per-sport defaults on purpose. Setting it is an
    explicit operator act during an incident and must beat a constant compiled
    in from last week's measurements; the per-sport ENV still wins over it,
    because it is more specific still.

    Called with no sport (the old signature) this returns the global-or-fallback
    value, so existing callers keep working unchanged.
    """
    key = str(sport or "").strip().lower()
    if key:
        from_sport_env = _positive_int(
            os.environ.get(_SPORT_THRESHOLD_ENV_PREFIX + key.upper())
        )
        if from_sport_env is not None:
            return from_sport_env
    from_global_env = _positive_int(os.environ.get(_THRESHOLD_ENV))
    if from_global_env is not None:
        return from_global_env
    return _DEFAULT_STALE_SECONDS_BY_SPORT.get(key, _DEFAULT_STALE_SECONDS)


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

    # An explicit argument (the `?threshold_seconds=` query param) still wins
    # over everything -- it is a caller asking a specific question. Absent one,
    # the threshold is resolved PER SPORT.
    threshold = (
        int(threshold_seconds) if threshold_seconds else stale_threshold_seconds(sport)
    )
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
        # A SCALAR HERE WOULD NOW BE A LIE. Thresholds are per-sport, so this
        # carries the explicit override when a caller forced one and `None`
        # otherwise, with the real values in `thresholds_by_sport` (and on each
        # per-sport entry). Reporting one number while four are in use is the
        # shape of defect this module exists to catch, one layer up.
        "threshold_seconds": int(threshold_seconds) if threshold_seconds else None,
        "thresholds_by_sport": {
            sport: entry.get("threshold_seconds") for sport, entry in per_sport.items()
        },
        "worst_status": worst,
        "stale_sports": sorted(
            s for s, e in per_sport.items() if e["status"] == STATUS_STALE
        ),
        "unknown_sports": sorted(
            s for s, e in per_sport.items() if e["status"] == STATUS_UNKNOWN
        ),
        "per_sport": per_sport,
    }
