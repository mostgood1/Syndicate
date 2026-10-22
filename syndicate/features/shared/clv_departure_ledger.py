"""Which +EV prices LEFT the Layer 2 board, and when -- recorded on the worker.

Lane `layer2-live-scorecard-gate`, 2026-09-13. The opening ledger records the
price we published FIRST. It cannot say whether that price was still there to
bet a few minutes later, and on 09-12 that turned out to be the question the
live board's results hang on. Measured from a session capture of the served
shortlist (all 80 NCAAF finals): of live +EV prices served under 5 minutes old,
61% were gone from the board 10 minutes later; of those served 10+ minutes old,
75%. The shown-price ROI said the opposite of what a bettor could collect. That
capture ran on one PC, so it existed for one night. This module is the same
measurement, made by the service that builds the board, every build.

WHAT IS RECORDED. At each build, per sport present in the build:

- `departure` -- a market that had been +EV at some build while continuously on
  the board is ABSENT from this one. Carries the last price, book, EV and game
  state it was seen with, `last_seen_at` (the previous build) and `gone_by`
  (this build). The truth lies between the two stamps.
- `return` -- a market that departed earlier the same date is back. Without it a
  line that flickers off for one build reads as gone for good, and so would a
  market that one build path omits and another includes.
- `build` -- one heartbeat per build, `{sport: markets present}`. A departure
  that never happened cannot be told from a board that stopped building (the
  09-12 shortlist froze at the Central date roll, 04:58:55Z) without knowing
  which builds DID happen.

"GONE" MEANS GONE FROM THE BOARD, not proven gone from the book. A market can
leave because its price moved, its line moved (a new identity), the book pulled
it, or it fell out of the ranked shortlist. That is the same thing the capture
measured, and the thing a person watching the board experiences.

IDENTITY IGNORES THE BOOK. `clv_opening_ledger._opening_key` includes
`bookmaker` on purpose, for the settlement join; here a best-book change is not
the price leaving the board, so the identity is sport, event, market, player,
segment, side and line.

A SPORT ABSENT FROM A BUILD FIRES NOTHING. Its tracked markets are kept until a
build that contains the sport again. The cost is that markets still up when a
sport's rows stop entirely never record a departure; the heartbeat makes that
visible as censoring rather than as "still there".

THE STATE FILE IS WORKER-LOCAL. `<date>.state.json` is rewritten whole every
build, so it is deliberately NOT `.jsonl` and never matches the publish
allowlist (`reports/intelligence/clv_departures/*.jsonl`). An unreadable state
records no departures for that build and says so (`state_unreadable`), which
undercounts; it never invents one.

A SPORT WHOSE RECORDS A CEILING REFUSED IS CENSORED for the rest of the date
(lane `clv-departures-ceiling`, 2026-10-22). Its later heartbeats move from
`sports` to `censored`, because a heartbeat listing a sport claims every
departure of that build is in the file, and `layer2_live_scorecard.look_after`
reads a missing departure under a listed build as "kept". Censored, the scorecard
reads those sightings as `unobserved`, which is true.

Builds are assumed sequential per date. Two interleaved builds would race on
the state file the same way `record_openings` races on its `seen` set.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "DEPARTURE_LEDGER_SUBDIR",
    "departure_ledger_enabled",
    "departure_ledger_path",
    "departure_state_path",
    "load_departures",
    "market_identity",
    "record_departures",
]

DEPARTURE_LEDGER_SUBDIR = "clv_departures"

# A tripwire, not a budget. 09-12 carried 1,661 +EV NCAAF openings and ~24.5k
# openings across sports; at ~350 B per departure a full Saturday is a few MB.
# A state bug that re-fires every tracked market every build is what this
# bounds: one truncated file, not a disk.
#
# RE-SIZED AND SPLIT BY SPORT 2026-10-22 (lane `clv-departures-ceiling`,
# `.syndicate/findings_2026-10-22_clv_departures_ceiling.md`), the sibling of
# `clv_opening_ledger`'s `22e3a0aa`. The 8 MiB tripwire had not fired yet, but
# 10-17 reached 7,938,374 B (94.6%) before NBA's season began, and NBA alone
# wrote 2.35 MiB on Wednesday 10-21. The old loop `break`s at the first
# oversized record, so the first sport to fill the file would cost EVERY sport
# its evening, with the heartbeat dropped as well, while the state moved on and
# the departures were gone for good. Measured on the fleet, 24 dates 09-30..10-23:
#   * largest sport-day: NCAAF 10-10 at 3.80 MiB (10-17: 3.64 MiB);
#   * largest day: 10-17 at 7.57 MiB; a Saturday plus 10-21's NBA is ~10 MiB.
# So, still tripwires against a state bug and not budgets:
#   * `_MAX_SPORT_BYTES` 16 MiB per (date, sport): ~4x the largest sport-day,
#     and a runaway sport costs only its own records;
#   * `_MAX_LEDGER_BYTES` 32 MiB per date: ~4x the largest day, ~3x a projected
#     NBA Saturday;
#   * heartbeats are refused only past `_MAX_LEDGER_BYTES` plus
#     `_HEARTBEAT_RESERVE_BYTES`, so the builds that ran stay visible after a
#     day ceiling fires (the largest day measured carried 59 KB of heartbeats).
# Readers take the bigger file: the scorecard fetches `?path=` (no per-file
# cap; the bulk export's 8 MB cap does not apply) and the weekly backtests
# stream.
_MAX_LEDGER_BYTES = 32 * 1024 * 1024
_MAX_SPORT_BYTES = 16 * 1024 * 1024
_HEARTBEAT_RESERVE_BYTES = 1024 * 1024

_IDENTITY_FIELDS = ("event_id", "market", "segment", "side", "line", "player_name")


def _reports_root() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root()


def departure_ledger_path(date: str, *, root: Path | str | None = None) -> Path:
    base = Path(root) if root is not None else _reports_root()
    return base / "intelligence" / DEPARTURE_LEDGER_SUBDIR / f"{str(date).strip()}.jsonl"


def departure_state_path(date: str, *, root: Path | str | None = None) -> Path:
    return departure_ledger_path(date, root=root).with_suffix(".state.json")


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def market_identity(row: Mapping[str, Any]) -> str | None:
    """The market, without the book. Works on board rows AND opening records,
    which carry the same field names."""
    sport = str(row.get("sport") or "").strip().lower()
    event_id = str(row.get("event_id") or "").strip()
    market = str(row.get("market") or "").strip().lower()
    if not sport or not event_id or not market:
        return None
    line = _as_float(row.get("line"))
    return "|".join(
        (
            f"sport={sport}",
            f"event_id={event_id}",
            f"market={market}",
            f"player={str(row.get('player_name') or '').strip().lower()}",
            f"segment={str(row.get('segment') or '').strip().lower()}",
            f"side={str(row.get('side') or '').strip().lower()}",
            f"line={'' if line is None else line}",
        )
    )


def _summary(row: Mapping[str, Any], first_ev_at: str | None) -> dict[str, Any]:
    quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    quote = quote or {}
    return {
        "event_id": str(row.get("event_id") or "").strip() or None,
        "market": str(row.get("market") or "").strip().lower() or None,
        "segment": row.get("segment"),
        "side": str(row.get("side") or "").strip().lower() or None,
        "line": _as_float(row.get("line")),
        "player_name": row.get("player_name"),
        "price": quote.get("price"),
        "bookmaker": str(quote.get("bookmaker") or "").strip().lower() or None,
        "ev_pct": _as_float(row.get("ev_pct")),
        "game_state": row.get("game_state"),
        "first_ev_at": first_ev_at,
    }


def load_departures(date: str, *, root: Path | str | None = None) -> list[dict[str, Any]]:
    """Every record for `date`. Malformed lines are skipped."""
    path = departure_ledger_path(date, root=root)
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


def _load_state(path: Path) -> tuple[dict[str, Any], bool]:
    """(state, unreadable). A missing file is a first build, not an error."""
    if not path.exists():
        return {}, False
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}, True
    return (parsed, False) if isinstance(parsed, dict) else ({}, True)


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def _record_sport(record: Mapping[str, Any]) -> str:
    """The ceiling slot a record counts against. Heartbeats are "" (no sport)."""
    if record.get("type") == "build":
        return ""
    return str(record.get("sport") or "").strip().lower()


def _ledger_tally(path: Path, saved: Any) -> tuple[int, dict[str, int], dict[str, str], bool]:
    """(bytes on disk, bytes per sport, censored sports, ends without a newline).

    The state sidecar carries the per-sport bytes it last wrote, so a build does
    not re-read the day's file. They are trusted only while the file is exactly
    the size the state recorded. Anything else -- a first build on this code, an
    unreadable state, a crash between the append and the state write -- re-reads
    the file once, and recovers the censored sports from the heartbeats too.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return 0, {}, {}, False
    torn = False
    if size:
        with path.open("rb") as handle:
            handle.seek(size - 1)
            torn = handle.read(1) != b"\n"
    if isinstance(saved, dict) and saved.get("bytes") == size and isinstance(saved.get("sport_bytes"), dict):
        censored = saved.get("censored") if isinstance(saved.get("censored"), dict) else {}
        return size, {str(k): int(v) for k, v in saved["sport_bytes"].items()}, dict(censored), torn
    sport_bytes: dict[str, int] = {}
    censored: dict[str, str] = {}
    with path.open("rb") as handle:
        for raw in handle:
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = None
            slot = _record_sport(parsed) if isinstance(parsed, dict) else ""
            sport_bytes[slot] = sport_bytes.get(slot, 0) + len(raw)
            if isinstance(parsed, dict) and parsed.get("type") == "build" and isinstance(parsed.get("censored"), dict):
                for sport in parsed["censored"]:
                    censored.setdefault(str(sport), str(parsed.get("at") or ""))
    return size, sport_bytes, censored, torn


def record_departures(
    rows: Iterable[Mapping[str, Any]],
    *,
    date: str,
    now: datetime | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Diff this build against the previous one for `date`; append what left or came back.

    Returns counters even when nothing moved, for the same reason
    `record_openings` does: a counter that only appears when it fires cannot
    tell "ran, nothing left" from "never ran".
    """
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    build_at = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    path = departure_ledger_path(date, root=root)
    state_path = departure_state_path(date, root=root)

    rows_in = 0
    unkeyable = 0
    present: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        rows_in += 1
        if not isinstance(row, Mapping):
            unkeyable += 1
            continue
        identity = market_identity(row)
        if identity is None:
            unkeyable += 1
            continue
        sport = str(row.get("sport") or "").strip().lower()
        held = present.setdefault(sport, {}).get(identity)
        # Several books can carry one market in a build; keep the best EV so a
        # market counts as +EV if any of its rows is.
        if held is None or (_as_float(row.get("ev_pct")) or float("-inf")) > (_as_float(held.get("ev_pct")) or float("-inf")):
            present[sport][identity] = row

    report: dict[str, Any] = {
        "date": str(date),
        "path": str(path),
        "published": None,
        "rows_in": rows_in,
        "unkeyable_rows": unkeyable,
        "sports": len(present),
        "tracked": 0,
        "departed": 0,
        "returned": 0,
        "records_written": 0,
        "truncated_at_ceiling": False,
        # How many records a ceiling refused this build, and whose. A count,
        # not just the flag: a fired tripwire has to say what it cost.
        "dropped_at_ceiling": 0,
        "dropped_by_sport": {},
        "bytes_on_disk": None,
        "censored_sports": [],
        "state_unreadable": False,
    }
    if not present:
        # Nothing to diff and nothing to heartbeat: an empty build says nothing
        # about any sport, and writing state for it would only churn the disk.
        _print_report(report)
        return report

    state, unreadable = _load_state(state_path)
    report["state_unreadable"] = unreadable
    sports_state = state.get("sports") if isinstance(state.get("sports"), dict) else {}
    departed_today = state.get("departed") if isinstance(state.get("departed"), dict) else {}

    records: list[dict[str, Any]] = []
    tracked = 0
    for sport in sorted(present):
        now_rows = present[sport]
        previous = sports_state.get(sport) if isinstance(sports_state.get(sport), dict) else {}
        prev_markets = previous.get("markets") if isinstance(previous.get("markets"), dict) else {}
        prev_build = previous.get("build_at")

        for identity, last in prev_markets.items():
            if identity in now_rows or not isinstance(last, dict):
                continue
            records.append({
                "type": "departure",
                "identity": identity,
                "sport": sport,
                **{field: last.get(field) for field in _IDENTITY_FIELDS},
                "last_seen_at": prev_build,
                "gone_by": build_at,
                "last_price": last.get("price"),
                "last_bookmaker": last.get("bookmaker"),
                "last_ev_pct": last.get("ev_pct"),
                "last_game_state": last.get("game_state"),
                "first_ev_at": last.get("first_ev_at"),
            })
            departed_today[identity] = build_at
            report["departed"] += 1

        markets: dict[str, Any] = {}
        for identity, row in now_rows.items():
            if identity in departed_today:
                records.append({
                    "type": "return",
                    "identity": identity,
                    "sport": sport,
                    "gone_by": departed_today.pop(identity),
                    "back_at": build_at,
                })
                report["returned"] += 1
            was = prev_markets.get(identity) if isinstance(prev_markets.get(identity), dict) else None
            ev = _as_float(row.get("ev_pct"))
            is_positive = ev is not None and ev > 0
            if was is None and not is_positive:
                continue
            first_ev_at = (was or {}).get("first_ev_at") or (build_at if is_positive else None)
            markets[identity] = _summary(row, first_ev_at)
        tracked += len(markets)
        sports_state[sport] = {"build_at": build_at, "markets": markets}

    report["tracked"] = tracked

    saved_ledger = state.get("ledger") if isinstance(state.get("ledger"), dict) else None
    bytes_on_disk, sport_bytes, censored, torn = _ledger_tally(path, saved_ledger)
    chunks: list[str] = []
    # A torn final line would swallow the first record appended after it.
    if torn:
        chunks.append("\n")
        bytes_on_disk += 1
        sport_bytes[""] = sport_bytes.get("", 0) + 1
    written = 0
    moved = 0
    dropped: dict[tuple[str, str], int] = {}  # (scope, sport) -> records refused at a ceiling
    for record in records:
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        size = len(line.encode("utf-8"))
        sport = _record_sport(record)
        # Refuse PER RECORD, never `break`: a runaway sport costs its own
        # records, then the day's, and never another sport's evening.
        if bytes_on_disk + size > _MAX_LEDGER_BYTES:
            scope = "day"
        elif sport_bytes.get(sport, 0) + size > _MAX_SPORT_BYTES:
            scope = "sport"
        else:
            scope = None
        if scope is not None:
            dropped[(scope, sport)] = dropped.get((scope, sport), 0) + 1
            censored.setdefault(sport, build_at)
            if record["type"] == "departure" and departed_today.get(record["identity"]) == build_at:
                # Its departure is not in the file, so a return must not be either.
                departed_today.pop(record["identity"], None)
            continue
        chunks.append(line)
        bytes_on_disk += size
        sport_bytes[sport] = sport_bytes.get(sport, 0) + size
        written += 1
        moved += 1

    # The heartbeat lists only sports whose every record of the date is in the
    # file; a censored sport is named apart, so a reader sees the gap instead of
    # reading a refused departure as a market still on the board.
    heartbeat: dict[str, Any] = {
        "type": "build",
        "at": build_at,
        "sports": {s: len(present[s]) for s in sorted(present) if s not in censored},
    }
    censored_now = {s: len(present[s]) for s in sorted(present) if s in censored}
    if censored_now:
        heartbeat["censored"] = censored_now
    line = json.dumps(heartbeat, sort_keys=True, separators=(",", ":")) + "\n"
    size = len(line.encode("utf-8"))
    if bytes_on_disk + size > _MAX_LEDGER_BYTES + _HEARTBEAT_RESERVE_BYTES:
        dropped[("day", "")] = dropped.get(("day", ""), 0) + 1
    else:
        chunks.append(line)
        bytes_on_disk += size
        sport_bytes[""] = sport_bytes.get("", 0) + size
        written += 1

    if written:
        path.parent.mkdir(parents=True, exist_ok=True)
        # One write per build, so a crash tears at most one line. Binary, so the
        # bytes on disk are the bytes counted (text mode writes CRLF on Windows).
        with path.open("ab") as handle:
            handle.write("".join(chunks).encode("utf-8"))
    elif torn:
        bytes_on_disk -= 1  # the closing newline was never written
        sport_bytes[""] -= 1
    report["records_written"] = written
    report["truncated_at_ceiling"] = bool(dropped)
    report["dropped_at_ceiling"] = sum(dropped.values())
    dropped_by_sport: dict[str, int] = {}
    for (scope, sport), count in sorted(dropped.items()):
        dropped_by_sport[sport or "heartbeat"] = dropped_by_sport.get(sport or "heartbeat", 0) + count
        # LOUD, on every build it fires. The openings tripwire fired on 6 of 24
        # days with only `truncated=True` in a summary line to say so.
        print(
            "[clv_departure_ledger] DEPARTURES_CEILING_HIT date=%s scope=%s sport=%s dropped=%d "
            "bytes_on_disk=%d ceiling=%d"
            % (
                date,
                scope,
                sport or "heartbeat",
                count,
                bytes_on_disk,
                _MAX_SPORT_BYTES if scope == "sport" else _MAX_LEDGER_BYTES,
            ),
            flush=True,
        )
    report["dropped_by_sport"] = dropped_by_sport
    report["bytes_on_disk"] = bytes_on_disk
    report["censored_sports"] = sorted(censored)

    _write_state(
        state_path,
        {
            "sports": sports_state,
            "departed": departed_today,
            "ledger": {"bytes": bytes_on_disk, "sport_bytes": sport_bytes, "censored": censored},
        },
    )

    # Pushed only when a market actually left or came back. A heartbeat-only
    # build has nothing a reader needs yet, and re-pushing a growing file every
    # build is periodic worker work that is never free; the heartbeats ride
    # along with the next real change.
    if moved:
        try:
            from syndicate.features.shared.artifact_publisher import publish_hot_artifact

            report["published"] = bool(publish_hot_artifact(path))
        except Exception:
            report["published"] = False

    _print_report(report)
    return report


def _print_report(report: Mapping[str, Any]) -> None:
    print(
        "[clv_departure_ledger] DEPARTURES date=%s rows_in=%d sports=%d tracked=%d departed=%d "
        "returned=%d written=%d truncated=%s dropped=%d bytes=%s censored=%s state_unreadable=%s"
        % (
            report["date"], report["rows_in"], report["sports"], report["tracked"], report["departed"],
            report["returned"], report["records_written"], report["truncated_at_ceiling"],
            report["dropped_at_ceiling"], report["bytes_on_disk"], ",".join(report["censored_sports"]) or "-",
            report["state_unreadable"],
        ),
        flush=True,
    )


def departure_ledger_enabled() -> bool:
    """Default ON, for the opening ledger's reason: what is not recorded at the
    build cannot be reconstructed from a board that has moved on."""
    raw = os.environ.get("SYNDICATE_CLV_DEPARTURE_LEDGER_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}
