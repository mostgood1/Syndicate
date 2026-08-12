"""`#390`. One launch/finish record per sim run, for EVERY sport.

**THE PROBLEM THIS EXISTS FOR.** Measured 2026-08-12 across all eight sports:
only MLB had any sim run record at all. NBA / WNBA / NHL / soccer / NCAAF sims
run *inside* the odds refresh -- no launch line, no run stamp, no status file,
no duration. The only reason a report could quantify them was that
`ALL_PROCESS_MEMORY`, a **memory** diagnostic, happens to print child
`cmdline`s. Measuring sim cost via the memory instrument is an accident, not a
capability, and it gives sampled lower bounds rather than facts.

**WHY IT IS WIRED AT CHOKE POINTS, NOT AT EACH SIM.** The sims are spawned from
at least four places. Instrumenting each one is how this ends up half-done and
silently missing whichever sport was added last -- the same shape as the guards
already on the TODO list that were correct and unreached. There are two places
every non-MLB sim already passes through:

  * `refresh_odds_sources._run_command` -- every odds-refresh step, which is
    where soccer / NBA / WNBA / NHL sims actually execute.
  * `run_refresh_worker`'s season-projection autoruns -- NFL and NCAAF.

MLB keeps its own richer record (`mlb_sim_runs/`, see `#388`) and is *also*
mirrored here at launch, so one reader answers the question for all sports
instead of MLB needing a different endpoint from everything else. The mirror is
launch-only: MLB's own finaliser stays the authority on how a run ended, and
duplicating that here would give two writers for one fact -- the exact defect
`#388` had to unpick.

**UNCLASSIFIED STEPS ARE LOGGED, NOT DROPPED.** `classify_step` decides whether
a step is a sim from its command. A name allowlist would silently miss a new
sport's step -- so when a step looks sim-shaped but cannot be attributed to a
sport, that is emitted rather than swallowed. An instrument that cannot record
its own blind spot is indistinguishable from one with none.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file

# command substring -> (sport, kind). Order matters: first match wins, and the
# more specific patterns come first.
_SIM_COMMAND_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("generate_smartsim2_nfl_preseason", "nfl", "smartsim2_preseason"),
    ("generate_smartsim2_nfl", "nfl", "smartsim2_season"),
    ("generate_smartsim2_ncaaf", "ncaaf", "smartsim2_season"),
    ("build_soccer_artifacts", "soccer", "soccersim_artifacts"),
    ("build_nhl_artifacts", "nhl", "hockeysim_artifacts"),
    ("refresh_nhl_oddsapi", "nhl", "odds_refresh_with_sim"),
    ("refresh_nba_oddsapi_props", "nba", "smart_sim_props"),
    ("refresh_wnba_oddsapi_props", "wnba", "smart_sim_props"),
    ("run_mlb_daily_sim_job", "mlb", "daily_sim"),
    ("tools/daily_update.py", "mlb", "daily_sim"),
)

# A step whose command matches none of the above but whose NAME looks like a
# sim step -- the blind-spot detector. Deliberately broad: a false alarm costs
# one log line, a miss costs a sport's entire visibility.
_SIM_SHAPED_NAME = re.compile(r"(artifacts|props_job|projections|_sim)\b")

_MAX_INDEX_ENTRIES = 500


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def classify_step(step_name: str, command: Any) -> tuple[str, str] | None:
    """(sport, kind) if this command runs a simulation, else None.

    Classified on the COMMAND, not the step name: the command is what actually
    determines whether a sim runs, and a name allowlist goes stale silently
    when a sport is added.
    """
    joined = " ".join(str(part) for part in (command or []))
    for needle, sport, kind in _SIM_COMMAND_PATTERNS:
        if needle in joined:
            return sport, kind
    return None


def step_looks_sim_shaped(step_name: str) -> bool:
    """Whether a step NAME suggests a sim that `classify_step` did not match.

    Used only to emit a blind-spot warning. Never used to record a run -- a
    guess about a sport is worse than a named gap.
    """
    return bool(_SIM_SHAPED_NAME.search(str(step_name or "")))


def duration_seconds(started_at: Any, finished_at: Any) -> int | None:
    """Both timestamps parsed tz-aware. Emitted as a FIELD so no reader has to
    diff a UTC string against a Central one -- the trap `#388` documented."""
    try:
        start_raw, end_raw = str(started_at or "").strip(), str(finished_at or "").strip()
        if not start_raw or not end_raw:
            return None
        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return max(0, int((end - start).total_seconds()))
    except Exception:
        return None


def _ledger_dir(date_str: str) -> Path:
    return reports_root() / "sim_runs" / str(date_str or "unknown")


def _index_path(date_str: str) -> Path:
    return _ledger_dir(date_str) / "_index.json"


def record_sim_run(
    *,
    sport: str,
    kind: str,
    date: str,
    run_stamp: str,
    started_at: str,
    finished_at: str | None = None,
    exit_code: int | None = None,
    state: str = "finished",
    trigger: str | None = None,
    scope: Any = None,
    service: str | None = None,
    detail: str | None = None,
) -> dict[str, Any] | None:
    """Write one run record, and append it to the day's index.

    The per-run file is the authority and cannot race -- its path carries a
    unique run stamp. The index is a convenience for listing and is written
    read-modify-write; a lost index entry costs discoverability, never the
    record itself.
    """
    if not str(sport or "").strip() or not str(run_stamp or "").strip():
        return None
    payload = {
        "sport": str(sport),
        "kind": str(kind or "sim"),
        "date": str(date or ""),
        "run_stamp": str(run_stamp),
        "state": str(state or "finished"),
        "started_at": str(started_at or ""),
        "finished_at": finished_at,
        "duration_seconds": duration_seconds(started_at, finished_at),
        "exit_code": exit_code,
        "trigger": trigger,
        "scope": scope,
        "service": service,
        "detail": detail,
        "recorded_at": _utc_now(),
    }
    record_path = _ledger_dir(str(date or "")) / f"{sport}__{kind}__{run_stamp}.json"
    try:
        write_json_file(record_path, payload)
    except Exception:
        return None

    try:
        existing = read_json_file(_index_path(str(date or "")))
        entries = list(existing.get("runs") or []) if isinstance(existing, dict) else []
        entries.append({
            key: payload[key]
            for key in ("sport", "kind", "run_stamp", "state", "started_at",
                        "finished_at", "duration_seconds", "exit_code", "trigger", "service")
        })
        write_json_file(_index_path(str(date or "")), {
            "date": str(date or ""),
            "updated_at": _utc_now(),
            "runs": entries[-_MAX_INDEX_ENTRIES:],
        })
    except Exception:
        pass
    return payload


def read_sim_run_index(date: str) -> dict[str, Any] | None:
    payload = read_json_file(_index_path(str(date or "")))
    return payload if isinstance(payload, dict) else None


def summarize_by_sport(date: str) -> dict[str, Any]:
    """Per-sport counts and durations -- the shape the `#390` question asks for.

    Reports a **rate and a denominator**, not a bare count: `runs` alongside
    `ok`/`failed` so a sport that ran ten times and failed ten times cannot read
    as a healthy ten.
    """
    index = read_sim_run_index(date) or {}
    by: dict[str, dict[str, Any]] = {}
    for run in index.get("runs") or []:
        sport = str(run.get("sport") or "unknown")
        bucket = by.setdefault(sport, {"runs": 0, "ok": 0, "failed": 0, "unfinished": 0, "durations": []})
        bucket["runs"] += 1
        code = run.get("exit_code")
        if run.get("finished_at") is None:
            bucket["unfinished"] += 1
        elif code == 0:
            bucket["ok"] += 1
        elif code is not None:
            bucket["failed"] += 1
        seconds = run.get("duration_seconds")
        if isinstance(seconds, int):
            bucket["durations"].append(seconds)
    out: dict[str, Any] = {}
    for sport, bucket in sorted(by.items()):
        durations = sorted(bucket.pop("durations"))
        bucket["p50_seconds"] = durations[len(durations) // 2] if durations else None
        bucket["max_seconds"] = durations[-1] if durations else None
        bucket["total_seconds"] = sum(durations) or None
        out[sport] = bucket
    return {"date": str(date or ""), "by_sport": out}
