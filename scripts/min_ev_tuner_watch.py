"""The fleet watchdog's min_ev tuner checks (called from `scripts/local_watchdog.py` main()).

WHY. The tuner runs in shadow on refresh-worker once a UTC day at >= 12:00Z
(`min_ev_tuner.maybe_run_nightly`, from the intelligence-state loop). A week of
its readouts precedes the user's apply decision, and until now the only witness
that a pass happened -- or failed, or ran in a mode nobody chose -- was a Claude
session reading the log. These checks need no session.

WHAT IS CHECKED (keys carry the `exec:` prefix, so they are EMAILED as well as
toasted -- `execution_watchdog.emailable`):
  exec:min_ev_tuner:missing   no `[min_ev_tuner] MIN_EV_TUNER ... date=<today>` line
                              in refresh-worker.log by 13:00Z                       warn
  exec:min_ev_tuner:failed    MIN_EV_TUNER_FAILED / MIN_EV_TUNER_SAVE_FAILED /
                              MIN_EV_TUNER_HOOK_FAILED seen today and no pass
                              line after it (a later pass CLEARS it)                warn
  exec:min_ev_tuner:mode      today's pass line, or the newest readout artifact,
                              says a mode other than `shadow`, and
                              `<home>/min_ev_tuner_mode_decision.json` does not
                              record the user's decision for that mode             fail

RECORDING A DECISION. When the user decides to switch modes, write
`<home>/min_ev_tuner_mode_decision.json`:
    {"mode": "apply", "decided_by": "user", "decided_at": "<UTC>", "note": "<their words>"}
It covers that mode only; any other non-shadow mode still alerts.

HOW THE LOG IS READ. Incrementally: the byte offset of the last read is kept in
the watchdog state, so each 5-minute check reads only what the worker wrote
since, and a failure line is attributed to the check that first saw it (the
FAILED lines carry no date). A shrunk file means `rotate_running_log` copied
then truncated it; the tail of the copy (`refresh-worker.log.1`) past the old
offset is read first. The very first read has no offset: it reads the whole
file and counts only failures after the last pass line in it.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Mapping

FAIL, WARN = "fail", "warn"
PREFIX = "exec:min_ev_tuner:"
LOG_NAME = "refresh-worker.log"
DECISION_NAME = "min_ev_tuner_mode_decision.json"
READOUT_SUBDIR = ("reports", "intelligence", "min_ev_tuner_readout")  # under the data root
DUE_HOUR_UTC = 13  # the pass runs at >= 12:00Z; an hour of grace
# ANCHORED at the start of the line (after the supervisor's optional `2026-10-22T12:01:51.256Z ` stamp). A bare
# substring match is not safe here: refresh-worker's ALL_PROCESS_MEMORY line embeds every process's cmdline, and on
# 2026-10-22 it carried another session's `grep -E 'MIN_EV_TUNER_(FAILED|...'` -- one literal grep would have been
# read as a tuner failure.
_STAMP = r"^(?:(?P<stamp>\d{4}-\d\d-\d\d)T\S+ )?"
_PASS = re.compile(_STAMP + r"\[min_ev_tuner\] MIN_EV_TUNER mode=(?P<mode>\S+) date=(?P<date>\d{4}-\d\d-\d\d)\b")
_FAILURE = re.compile(
    _STAMP + r"\[(?:min_ev_tuner|intelligence_state)\] (?P<marker>MIN_EV_TUNER_(?:FAILED|SAVE_FAILED|HOOK_FAILED))\b"
)
_MAX_FAILURES_KEPT = 5


def parse_pass_line(line: str) -> dict[str, str] | None:
    """`{"mode", "date"}` for a pass line, else None. `MIN_EV_TUNER_MOVE` lines are not passes."""
    match = _PASS.match(line)
    return {"mode": match["mode"], "date": match["date"]} if match else None


def parse_failure_line(line: str) -> dict[str, str | None] | None:
    """`{"marker", "stamp"}` (stamp = the line's UTC date when the log stamps it) for a failure line, else None."""
    match = _FAILURE.match(line)
    return {"marker": match["marker"], "stamp": match["stamp"]} if match else None


def _read_from(path: Path, offset: int) -> tuple[str, int]:
    """Complete lines from `offset`, and the offset just past the last newline."""
    with path.open("rb") as handle:
        handle.seek(offset)
        blob = handle.read()
    cut = blob.rfind(b"\n")
    if cut < 0:
        return "", offset
    return blob[: cut + 1].decode("utf-8", "replace"), offset + cut + 1


def scan_log(logs_dir: Path, row: Mapping[str, Any], now: dt.datetime) -> dict[str, Any]:
    """Advance the incremental read of refresh-worker.log; returns the new row (pure apart from reading files)."""
    today = now.date().isoformat()
    new = dict(row or {})
    if new.get("date") != today:
        new.update(date=today, pass_mode=None, pass_line=None, failures=[], failures_today=0)
    path = logs_dir / LOG_NAME
    if not path.is_file():
        new["log_missing"] = True
        return new
    new["log_missing"] = False
    first_scan = "offset" not in new
    offset = int(new.get("offset") or 0)
    size = path.stat().st_size
    chunks: list[str] = []
    if offset > size:  # copy+truncate rotation: finish the copy, then start the live file over
        rotated = path.with_name(f"{LOG_NAME}.1")
        if rotated.is_file() and rotated.stat().st_size >= offset:
            chunks.append(_read_from(rotated, offset)[0])
        offset = 0
    text, offset = _read_from(path, offset)
    chunks.append(text)
    new["offset"] = offset

    failures: list[str] = list(new.get("failures") or [])
    count = int(new.get("failures_today") or 0)
    for line in "".join(chunks).splitlines():
        parsed = parse_pass_line(line)
        if parsed is not None:
            new["last_pass_date"] = parsed["date"]
            new["last_pass_mode"] = parsed["mode"]
            if parsed["date"] == today:
                new["pass_mode"] = parsed["mode"]
                new["pass_line"] = line.strip()[:300]
            if first_scan or parsed["date"] == today:
                # A pass after a failure means the retry worked (the hook retries every cycle until one
                # pass lands), so the failure finding CLEARS. On the first scan, failures before the
                # newest pass line belong to an earlier day.
                failures, count = [], 0
            continue
        failure = parse_failure_line(line)
        if failure is not None and failure["stamp"] in (None, today):  # a stamped line from another day is not today's
            failures.append(line.strip()[:300])
            count += 1
    new["failures"] = failures[-_MAX_FAILURES_KEPT:]
    new["failures_today"] = count
    return new


def newest_readout(data_root: Path) -> dict[str, Any]:
    directory = data_root.joinpath(*READOUT_SUBDIR)
    try:
        files = sorted(directory.glob("????-??-??.json"))
    except OSError:
        return {}
    for path in reversed(files):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def load_decision(home: Path) -> dict[str, Any]:
    try:
        payload = json.loads((home / DECISION_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def evaluate(row: Mapping[str, Any], readout: Mapping[str, Any], decision: Mapping[str, Any],
             now: dt.datetime) -> list[tuple[str, str, str]]:
    """(key, severity, message) findings (pure)."""
    out: list[tuple[str, str, str]] = []
    today = now.date().isoformat()
    if now.hour >= DUE_HOUR_UTC and not row.get("pass_line"):
        where = "refresh-worker.log is missing" if row.get("log_missing") else "no such line in refresh-worker.log"
        out.append((PREFIX + "missing", WARN,
                    f"min_ev tuner: no MIN_EV_TUNER pass line for {today} by {DUE_HOUR_UTC:02d}:00Z ({where}; "
                    f"last pass seen {row.get('last_pass_date') or 'never'}). The shadow readout for today has nothing new."))
    failures = list(row.get("failures") or [])
    if row.get("failures_today"):
        out.append((PREFIX + "failed", WARN,
                    f"min_ev tuner: {row.get('failures_today')} failure line(s) today; latest: {failures[-1] if failures else '?'}"))
    observed = {}
    if row.get("pass_mode"):
        observed["today's pass line"] = str(row["pass_mode"])
    if readout.get("mode"):
        observed[f"readout {readout.get('date')}"] = str(readout["mode"])
    decided = str(decision.get("mode") or "").strip().lower()
    for source, mode in observed.items():
        if mode.strip().lower() != "shadow" and mode.strip().lower() != decided:
            out.append((PREFIX + "mode", FAIL,
                        f"min_ev tuner mode={mode} ({source}) and no recorded user decision for it "
                        f"(<home>/{DECISION_NAME} says {decided or 'nothing'}). Non-shadow modes move live min_ev cuts."))
            break
    return out


def run(home: Path, logs_dir: Path, data_root: Path, state: Mapping[str, Any], now: dt.datetime
        ) -> tuple[list[tuple[str, str, str]], dict[str, Any]]:
    """(findings, new row for state["min_ev_tuner"]). Never raises."""
    row = dict(state.get("min_ev_tuner") or {})
    try:
        row = scan_log(logs_dir, row, now)
        return evaluate(row, newest_readout(data_root), load_decision(home), now), row
    except Exception as exc:  # noqa: BLE001 -- a broken check must not stop the fleet checks
        return [(PREFIX + "watch_error", WARN, f"min_ev tuner check crashed: {type(exc).__name__}: {exc}"[:300])], row
