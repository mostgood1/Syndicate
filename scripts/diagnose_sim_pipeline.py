"""Per-sport simulation diagnostic: what runs, how long, how often, and
whether the rules for WHEN it may run are actually being followed.

    py -3 scripts\\diagnose_sim_pipeline.py
    py -3 scripts\\diagnose_sim_pipeline.py --json
    py -3 scripts\\diagnose_sim_pipeline.py --hours 6

Three columns per sport, and the third is the one that matters:

    CONFIGURED   the env flag and interval -- what was asked for
    OBSERVED     process starts/ends in the logs -- what happened
    COMPLIANT    do they agree, and are the run-rules being honoured

**CONFIGURED IS NOT REALITY, AND THAT GAP IS THE PRODUCT.** Measured on
2026-08-09: `SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS=60` while
snapshots were written 15m35s apart, and a standing instruction that "soccer
sims are off" was believed by four sessions while the autorun flag was `true`
in production the whole time. A tool that only prints configuration would
have confirmed both mistakes.

DURATION IS MEASURED FROM THE PROCESS TABLE, NOT FROM LOG MARKERS.
`STEP_END` never reaches Render's collector (the orchestrator is piped to
files), so its absence is legitimate and proves nothing. `ALL_PROCESS_MEMORY`
carries a per-process cmdline list every few seconds, so a sim's lifetime is
the span over which its process is present -- which is also how concurrency
gets counted honestly.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from scripts._pipeline_diag import (  # noqa: E402
    SERVICES,
    banner,
    cadence,
    fetch_logs,
    log_window,
    matches,
    render_json,
    render_owner_id,
    service_commits,
)

# The process names a sim shows up as, per sport. Matched against the cmdline
# strings inside ALL_PROCESS_MEMORY.
SIM_PROCESS_PATTERNS = {
    "soccer": r"build_soccer_artifacts",
    "mlb": r"build_mlb_artifacts|run_mlb_sim|smart_sim",
    "wnba": r"build_wnba_artifacts|wnba_sim|smart_sim_wnba",
    "nba": r"build_nba_artifacts|nba_sim",
    "nhl": r"build_nhl_artifacts|nhl_sim",
    "nfl": r"build_nfl_artifacts|nfl_sim",
    "ncaaf": r"build_ncaaf_artifacts",
    "ncaab": r"build_ncaab_artifacts",
}

# The env keys that decide whether, and how often, each sport may run.
SIM_ENV_KEYS = {
    "soccer": ("SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN", "SYNDICATE_SOCCER_WEEKLY_REFRESH_INTERVAL_SECONDS"),
    "mlb": ("SYNDICATE_MLB_REFRESH_TICK_OWNER_HERE", "SYNDICATE_MLB_REFRESH_INTERVAL_SECONDS"),
    "wnba": ("SYNDICATE_ENABLE_WNBA_REFRESH_AUTORUN", "SYNDICATE_WNBA_REFRESH_INTERVAL_SECONDS"),
}

GUARD_PATTERN = r"OVERVIEW_STOPPED_FOR_MEMORY|MEMORY_GUARD_ABORT|SKIPPED_FOR_MEMORY|throttled"


def service_env(service_id: str) -> dict[str, str]:
    """Live env for one service. Paginated deliberately: `limit` > 100 is an
    HTTP 400 on this endpoint, which returns nothing and reads as 'unset'.
    """
    out: dict[str, str] = {}
    payload, _, _ = render_json(f"/services/{service_id}/env-vars?limit=100")
    if isinstance(payload, list):
        for row in payload:
            env = row.get("envVar", row) if isinstance(row, dict) else {}
            key = str(env.get("key") or "")
            if key:
                out[key] = str(env.get("value") or "")
    return out


def process_samples(logs: list[dict]) -> list[tuple[datetime, str]]:
    """(timestamp, full message) for every process-table sample."""
    out: list[tuple[datetime, str]] = []
    for entry in matches(logs, r"ALL_PROCESS_MEMORY"):
        raw = str(entry.get("timestamp") or "")[:19]
        try:
            stamp = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        out.append((stamp, str(entry.get("message") or "")))
    return sorted(out, key=lambda pair: pair[0])


def runs_for(samples: list[tuple[datetime, str]], pattern: str) -> tuple[list[tuple[datetime, datetime]], int]:
    """Contiguous spans where the process is present, plus MAX CONCURRENCY.

    Concurrency is counted per sample rather than inferred from overlapping
    spans, because a re-claim loop can start a second copy of the same job
    and span-merging would hide exactly that.
    """
    compiled = re.compile(pattern, re.IGNORECASE)
    spans: list[tuple[datetime, datetime]] = []
    peak = 0
    open_start: datetime | None = None
    last_seen: datetime | None = None
    for stamp, message in samples:
        hits = len(compiled.findall(message))
        peak = max(peak, hits)
        if hits:
            if open_start is None:
                open_start = stamp
            last_seen = stamp
        elif open_start is not None:
            spans.append((open_start, last_seen or open_start))
            open_start = None
            last_seen = None
    if open_start is not None:
        spans.append((open_start, last_seen or open_start))
    return spans, peak


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--log-limit", type=int, default=1000, help="log lines (max 1000; the API 400s above that)")
    args = parser.parse_args()

    owner = render_owner_id()
    worker_id = SERVICES["refresh-worker"]
    logs, log_error = fetch_logs(worker_id, limit=args.log_limit, owner_id=owner)
    first, last, minutes = log_window(logs)
    samples = process_samples(logs)
    env = service_env(worker_id)
    commits = service_commits()

    rows = []
    for sport, pattern in SIM_PROCESS_PATTERNS.items():
        spans, peak = runs_for(samples, pattern)
        durations = [(end - start).total_seconds() for start, end in spans]
        enable_key, interval_key = SIM_ENV_KEYS.get(sport, ("", ""))
        enabled = env.get(enable_key, "<unset>") if enable_key else "n/a"
        interval = env.get(interval_key, "<unset>") if interval_key else "n/a"
        starts = [{"timestamp": start.isoformat()} for start, _ in spans]
        _, cadence_note = cadence(starts)
        rows.append(
            {
                "sport": sport,
                "configured_enabled": enabled,
                "configured_interval_s": interval,
                "observed_runs": len(spans),
                "max_concurrent": peak,
                "longest_s": round(max(durations), 1) if durations else None,
                "median_s": round(sorted(durations)[len(durations) // 2], 1) if durations else None,
                "cadence": cadence_note,
            }
        )

    guards = matches(logs, GUARD_PATTERN)

    if args.json:
        print(
            json.dumps(
                {
                    "log_window": {"first": first, "last": last, "minutes": round(minutes, 1)},
                    "log_error": log_error,
                    "commits": commits,
                    "sports": rows,
                    "guard_events": len(guards),
                },
                indent=2,
            )
        )
        return 0

    print(banner(f"SIM PIPELINE   (refresh-worker log window {first} -> {last}, {minutes:.0f} min)"))
    if log_error:
        print(f"  !! LOG FETCH FAILED: {log_error} -- everything below is UNMEASURED, not zero.")
    print(f"  live commits: " + ", ".join(f"{name}={sha}" for name, sha in commits.items()))
    print(
        f"\n  A {minutes:.0f}-MINUTE WINDOW CANNOT SEE A 4-HOUR CADENCE. Absence of a sport below\n"
        "  means it did not run IN THIS WINDOW -- never that it is disabled. Read the\n"
        "  CONFIGURED column for that, and trust neither alone.\n"
    )
    header = f"  {'sport':9} {'enabled':>9} {'interval':>10} {'runs':>5} {'peak':>5} {'longest':>9} {'median':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in rows:
        longest = f"{row['longest_s']:.0f}s" if row["longest_s"] else "-"
        median = f"{row['median_s']:.0f}s" if row["median_s"] else "-"
        print(
            f"  {row['sport']:9} {str(row['configured_enabled'])[:9]:>9} "
            f"{str(row['configured_interval_s'])[:10]:>10} {row['observed_runs']:>5} "
            f"{row['max_concurrent']:>5} {longest:>9} {median:>8}"
        )

    print("\n  RULES CHECK")
    problems = 0
    for row in rows:
        sport = row["sport"]
        if row["configured_enabled"] == "UNSET" and row["observed_runs"]:
            problems += 1
            print(
                f"    !! {sport}: ran {row['observed_runs']}x with its enable flag UNSET. "
                "Absent is not off -- check the code's default before assuming."
            )
        if str(row["configured_enabled"]).lower() == "true" and not row["observed_runs"] and minutes > 60:
            print(f"    ?  {sport}: enabled but no run in {minutes:.0f} min -- expected if its interval is longer.")
        if row["max_concurrent"] and row["max_concurrent"] > 1:
            problems += 1
            print(
                f"    !! {sport}: MAX CONCURRENT = {row['max_concurrent']}. The cap is inert "
                "(#311) -- it reads zero in exactly the state that lets a job re-claim."
            )
    if guards:
        print(
            f"    !! {len(guards)} memory-guard/throttle events in window "
            f"(most recent {str(guards[-1].get('timestamp'))[:19]}). A sim that never starts "
            "because a guard fired is NOT a sim that is disabled -- see #285/#290."
        )
    if not problems and not guards:
        print("    No rule violations detected in this window.")

    print(
        "\n  CAVEAT THAT TRAVELS WITH EVERY NUMBER ABOVE: durations come from the process\n"
        "  table, so a job shorter than the sampling gap is invisible, and a job still\n"
        "  running at the window edge is reported short. Widen --log-limit before\n"
        "  treating a duration as final."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
