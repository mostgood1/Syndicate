"""Is it safe to deploy right now?

The standing pre-deploy habit was to read `/api/ops/live-refresh/state`'s
`sim_run_status` and treat "finished" as a clear window. That check is
narrower than it looks: it covers the MLB sim ONLY. On 2026-08-03 a deploy
made under exactly that check killed an in-flight odds-refresh run
(`odds_refresh_20260803_033243`) mid-flight -- its early artifacts
(refresh_and_gate_run, refresh_job_status) were written while
odds_refresh.json/.stderr.txt never were, which is what
/api/ops/odds-refresh/status reporting exists=False actually meant.

Nothing was lost there (the next cycle rewrites those artifacts), but the
window was reported as clean when it was not. This checks every in-flight
thing a restart would interrupt, and says plainly which one is busy.

    python scripts/check_deploy_safety.py

Exit code 0 = clear, 1 = something is in flight, 2 = could not determine
(which is NOT the same as clear, and is deliberately not exit 0).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_BASE_URL = "https://syndicate-an21.onrender.com"


def _load_admin_token() -> str:
    token = str(os.environ.get("ADMIN_TOKEN") or os.environ.get("SYNDICATE_ADMIN_TOKEN") or "").strip()
    if token:
        return token
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition("=")
            if key.strip() in {"ADMIN_TOKEN", "SYNDICATE_ADMIN_TOKEN"}:
                return value.strip().strip('"').strip("'")
    return ""


def _get_json(base_url: str, path: str, token: str, timeout: int = 90) -> Any:
    request = urllib.request.Request(f"{base_url.rstrip('/')}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


_SIM_MAX_RUNTIME_MINUTES = 90

# --- refresh-worker board build -------------------------------------------
#
# A RESTART DESTROYS AN IN-FLIGHT BOARD BUILD, AND NOTHING HERE COULD SEE IT.
#
# Measured 2026-08-12 by the oversight session, after three deploys inside 25
# minutes left the served board ~35 minutes stale:
#
#     22:04:57  last COMPLETED build (LAYER2_SHORTLIST)
#     22:08     deploy 03937acb
#     22:19:59  deploy 23ffbbbc
#     22:28:51  deploy 8a8df610
#     22:30:02  build STARTS again
#
# The 22:28:51 deploy was mine. I announced it, waited ~15 minutes for the MLB
# sim to clear, confirmed it clear from worker logs, and deployed into what this
# script called a clear window. It still cost 23 minutes of board work, because
# the script checked for sims and the thing at risk was a build. A protocol
# followed correctly that still produces the bad outcome is a protocol defect,
# which is why this belongs in the tool rather than in a rule four sessions have
# to remember.
#
# THE PREDICATE: `BUILD_SPAN_ENTER` marks the start of
# `candidate_collection_with_fallback`; `LAYER2_SHORTLIST` is written only on a
# completed build. If the newest enter is more recent than the newest
# completion, a build is running and a restart discards it.
#
# THE WAIT IS DERIVED, NOT HARDCODED. `collect_candidates` measured 804s at
# 19:49 and 1372s at 21:43 on the same worker -- it is GROWING, so any constant
# is wrong within days. Reading it from recent `COLLECT_SPAN_EXIT elapsed_s`
# keeps the number honest and makes the growth visible to whoever runs this,
# which is worth more than the guard itself.
_REFRESH_WORKER_SERVICE_ID = "srv-d91dpertqb8s73co8ls0"
_RENDER_OWNER_ID = "tea-d2bb5n95pdvs73cje4fg"
_BUILD_LOOKBACK_MINUTES = 180


def _load_render_key() -> str:
    key = str(os.environ.get("RENDER_API_KEY") or "").strip()
    if key:
        return key
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "RENDER_API_KEY":
                return value.strip().strip('"').strip("'")
    return ""


def _render_logs(key: str, text: str, *, minutes: int, limit: int = 20) -> list[dict[str, Any]]:
    import urllib.parse
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    query = urllib.parse.urlencode(
        {
            "ownerId": _RENDER_OWNER_ID,
            "resource": _REFRESH_WORKER_SERVICE_ID,
            "text": text,
            "startTime": (now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": str(limit),
            "direction": "backward",
        }
    )
    request = urllib.request.Request(
        "https://api.render.com/v1/logs?" + query, headers={"Authorization": f"Bearer {key}"}
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return (json.loads(response.read().decode("utf-8")) or {}).get("logs") or []


def _newest_timestamp(rows: list[dict[str, Any]]) -> str:
    stamps = [str(row.get("timestamp") or "") for row in rows if row.get("timestamp")]
    return max(stamps) if stamps else ""


def _expected_build_seconds(key: str) -> float | None:
    """SLOWEST recent COLLECT_SPAN_EXIT elapsed_s, or None when unreadable.

    MAX, NOT MEDIAN -- BECAUSE THE COST IS ASYMMETRIC, NOT BECAUSE THE SERIES
    GROWS. The first version of this comment said `collect_candidates` "grows
    through the day as the slate fills", from two measurements: 804s at 19:49
    and 1372s at 21:43. A third landed at 1080.81s at 22:52, which falsifies it
    -- the series VARIES with slate size, it does not trend.

    The decision does not change and the reasoning had to. Max is right because
    the two errors cost wildly different amounts: over-waiting costs idle
    minutes, under-waiting costs ~23 minutes of destroyed board work plus a
    stale board for everyone verifying anything against it. A median over the
    last dozen runs returned 13.4min against a real build of 22.9min, which is
    exactly how the next person deploys into one.

    Worth keeping the correction visible rather than quietly editing the number:
    a right decision resting on a wrong stated reason is the more dangerous of
    the two, because the next person to touch this will reason from the premise,
    not the outcome -- and "it grows" invites someone to replace max with a trend
    extrapolation, which on a varying series is worse than either.
    """
    import re

    try:
        rows = _render_logs(key, "COLLECT_SPAN_EXIT", minutes=_BUILD_LOOKBACK_MINUTES, limit=12)
    except Exception:
        return None
    values: list[float] = []
    for row in rows:
        match = re.search(r"elapsed_s[\"']?\s*[:=]\s*([0-9.]+)", str(row.get("message") or ""))
        if match:
            try:
                values.append(float(match.group(1)))
            except ValueError:
                continue
    if not values:
        return None
    return max(values)


def board_build_state() -> tuple[bool | None, dict[str, Any]]:
    """(in_flight, facts). None means UNKNOWN, which callers must treat as a
    BLOCK -- an unreadable log is not evidence of a quiet worker."""
    facts: dict[str, Any] = {}
    key = _load_render_key()
    if not key:
        facts["reason"] = "RENDER_API_KEY not found in environment or .env"
        return None, facts
    try:
        enters = _render_logs(key, "BUILD_SPAN_ENTER", minutes=_BUILD_LOOKBACK_MINUTES)
        done = _render_logs(key, "LAYER2_SHORTLIST", minutes=_BUILD_LOOKBACK_MINUTES)
    except Exception as exc:
        facts["reason"] = f"{type(exc).__name__}: {exc}"
        return None, facts

    newest_enter = _newest_timestamp(enters)
    newest_done = _newest_timestamp(done)
    facts["newest_build_start"] = newest_enter or "(none in window)"
    facts["newest_build_complete"] = newest_done or "(none in window)"

    expected = _expected_build_seconds(key)
    if expected is not None:
        facts["typical_build_seconds"] = int(expected)
        facts["typical_build_minutes"] = round(expected / 60.0, 1)

    if not newest_enter:
        # No build start seen at all in a 3h window. That is more likely a
        # log-visibility problem than a genuinely idle worker, so it is UNKNOWN
        # rather than clear.
        facts["reason"] = "no BUILD_SPAN_ENTER in the lookback window"
        return None, facts

    in_flight = (not newest_done) or (newest_enter > newest_done)
    if in_flight and expected is not None:
        try:
            started = datetime.strptime(newest_enter[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - started).total_seconds()
            facts["build_age_seconds"] = int(age)
            facts["estimated_seconds_remaining"] = max(0, int(expected - age))
        except ValueError:
            pass
    return in_flight, facts


def _run_age_minutes(started_at: Any) -> float | None:
    """Age in minutes of an ISO-8601 start stamp, or None if unparsable."""
    text = str(started_at or "").strip()
    if not text:
        return None
    try:
        started = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - started).total_seconds() / 60.0


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}



def _run_drain(*, owner: str, wait_seconds: int) -> int:
    """Request a drain, wait for the worker to go idle, report.

    NEVER deploys and never clears the drain on timeout. A drain that gives up
    and reports is recoverable; one that gives up and proceeds is the 23-minute
    build this whole mechanism exists to protect.

    Exit 0 = idle, safe to deploy (then clear the drain).
    Exit 1 = still busy at the cap.
    Exit 2 = UNKNOWN -- the worker never acked, or its heartbeat is stale. NOT
             the same as clear, and deliberately not exit 0.
    """
    import time as _time

    from syndicate.features.shared.deploy_drain import (
        read_worker_state,
        request_drain,
        _HEARTBEAT_STALE_SECONDS,
    )

    # THE DRAIN FLAG MUST REACH THE SAME STORE THE WORKER READS, and from a
    # laptop it does not by default. `refresh_state_store` falls back to LOCAL
    # FILES when the keyvalue backend is unconfigured -- so without this guard
    # `--drain` writes a file on your machine, prints DRAIN_REQUESTED, waits,
    # and the production worker never hears about any of it. A no-op that
    # reports success is the worst shape a safety tool can have, and it is the
    # same defect class as `#401` shipping an env flag nothing read.
    from syndicate.features.shared.refresh_state_store import _state_backend_kind

    if _state_backend_kind() != "keyvalue":
        print("[UNKNOWN] Drain requires the keyvalue backend; this shell is not configured for it.")
        print("  Without it the flag is written to a LOCAL FILE and the production worker never sees it.")
        print("  Set SYNDICATE_REFRESH_STATE_BACKEND=keyvalue and SYNDICATE_REFRESH_STATE_URL to the")
        print("  same values the workers use, then re-run. Refusing rather than pretending.")
        return 2

    # TTL DERIVED FROM MEASUREMENT, NOT A CONSTANT. The expiry must exceed the
    # longest work the drain can wait on, or it expires mid-wait and the deploy
    # lands on the build anyway -- reporting success while destroying what it
    # protected, and only on the slowest builds. Same COLLECT_SPAN_EXIT series
    # `#403` already reads, same max-not-median rule, x3 headroom, floored at
    # the module default so a missing measurement can never SHORTEN it.
    from syndicate.features.shared.deploy_drain import _DEFAULT_TTL_SECONDS

    measured = _expected_build_seconds(_load_render_key())
    ttl = max(int(_DEFAULT_TTL_SECONDS), int((measured or 0) * 3))
    if measured:
        print(f"  longest recent build {measured:.0f}s -> drain expiry {ttl}s ({ttl/60:.0f} min)")
    else:
        print(f"  build duration unmeasurable -> drain expiry floored at {ttl}s ({ttl/60:.0f} min)")
    request_drain(owner, ttl_seconds=ttl, reason="check_deploy_safety --drain")
    print(f"Drain requested by {owner}. Waiting up to {wait_seconds}s for refresh-worker to go idle.")
    print("  (a build already running is NOT interrupted -- drain waits for it to finish)")
    deadline = _time.time() + max(30, int(wait_seconds))
    last = ""
    while _time.time() < deadline:
        state, verdict = read_worker_state("refresh-worker")
        busy = [k for k, v in ((state or {}).get("in_flight") or {}).items() if v]
        line = f"  {verdict:<8} in_flight={busy or '[]'} commit={(state or {}).get('commit')}"
        if line != last:
            print(line, flush=True)
            last = line
        if verdict == "idle":
            print("")
            print("CLEAR: refresh-worker is drained and idle. Deploy now, then:")
            print(f"  python scripts/check_deploy_safety.py --undrain --drain-owner {owner}")
            return 0
        _time.sleep(15)

    state, verdict = read_worker_state("refresh-worker")
    if verdict == "unknown":
        print("")
        print("[UNKNOWN] refresh-worker never acknowledged the drain.")
        print("  Either the running build predates drain support, or its heartbeat is stale")
        print(f"  (> {_HEARTBEAT_STALE_SECONDS}s). An unacknowledged drain is NOT a drained worker --")
        print("  deploying now would kill whatever is in flight. Drain left in place; it expires on its own.")
        return 2
    print("")
    print("NOT CLEAR: still busy at the wait cap. Drain left in place (it expires on its own).")
    print("  Re-run to keep waiting, or clear it with --undrain if you are abandoning the deploy.")
    return 1


def _run_undrain(*, owner: str) -> int:
    from syndicate.features.shared.deploy_drain import clear_drain

    return 0 if clear_drain(owner) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--undrain", action="store_true",
                        help="Clear a drain this owner set (after deploying, or on abandon).")
    parser.add_argument("--drain", action="store_true",
                        help="Request a drain on refresh-worker and wait for it to go idle, then report.")
    parser.add_argument("--drain-owner", default=os.environ.get("USER") or os.environ.get("USERNAME") or "deployer",
                        help="Owner token: only this owner can clear the drain it set.")
    parser.add_argument("--drain-wait-seconds", type=int, default=1800,
                        help="Cap on how long to wait for idle. On timeout this REPORTS and never auto-deploys.")
    parser.add_argument(
        "--allow-live-games",
        action="store_true",
        help="Treat in-progress games as acceptable. They are only a warning by default, never a block.",
    )
    args = parser.parse_args()

    # `#409` phase 2. Drain: ask refresh-worker to stop STARTING new builds and
    # sims, wait for what is running to finish, then report a clear window.
    # Surfaced here rather than as a separate script because this is the tool
    # every lane already runs -- a drain nobody invokes is not a protocol.
    if args.undrain:
        return _run_undrain(owner=args.drain_owner)
    if args.drain:
        return _run_drain(owner=args.drain_owner, wait_seconds=args.drain_wait_seconds)

    token = _load_admin_token()
    if not token:
        print("ADMIN_TOKEN not found in environment or .env", file=sys.stderr)
        return 2

    try:
        payload = _get_json(args.base_url, "/api/ops/live-refresh/state", token)
    except Exception as exc:
        # Explicitly NOT exit 0: an unreachable control plane means the
        # window is unknown, and "unknown" must never read as "clear".
        print(f"[UNKNOWN] Could not read live-refresh state: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    state = _as_dict(_as_dict(payload).get("state"))
    sim = _as_dict(state.get("sim_run_status"))
    tick = _as_dict(state.get("latest_tick"))
    refresh_run = _as_dict(tick.get("result"))

    blockers: list[str] = []
    notes: list[str] = []

    sim_state = str(sim.get("state") or "").strip().lower()
    if sim_state == "running":
        # sim_run_status is written by the sim job and is NOT corrected when
        # the process dies without updating it -- e.g. killed by a deploy, or
        # hung. Confirmed live 2026-08-04: pid 2517 still read "running" 167
        # minutes after start, across a refresh-worker redeploy, blocking
        # every subsequent deploy. Trusting it unconditionally made this
        # script refuse to ever return CLEAR.
        #
        # Mirror the loop's own ceiling (_MLB_SIM_MAX_RUNTIME_SECONDS, 90
        # min): past that, the run cannot legitimately still be alive, so
        # report it as stale rather than treating it as a blocker.
        age_minutes = _run_age_minutes(sim.get("started_at"))
        if age_minutes is not None and age_minutes > _SIM_MAX_RUNTIME_MINUTES:
            notes.append(
                f"MLB sim: STALE pointer, ignoring (pid={sim.get('pid')}, started={sim.get('started_at')}, "
                f"age={age_minutes:.0f}m > {_SIM_MAX_RUNTIME_MINUTES}m ceiling)"
            )
        else:
            age_text = f", age={age_minutes:.0f}m" if age_minutes is not None else ""
            blockers.append(
                f"MLB sim RUNNING (pid={sim.get('pid')}, reason={sim.get('reason')}, started={sim.get('started_at')}{age_text})"
            )
    else:
        notes.append(f"MLB sim: {sim_state or 'none'} (exit={sim.get('exit_code')})")

    # The gap that motivated this script: an odds-refresh job in flight is
    # a separate process from the MLB sim and is invisible to sim_run_status.
    refresh_state = str(refresh_run.get("state") or "").strip().lower()
    if refresh_state == "running":
        blockers.append(
            f"Odds refresh RUNNING (pid={refresh_run.get('pid')}, lane={refresh_run.get('lane')}, "
            f"stamp={refresh_run.get('run_stamp')})"
        )
    else:
        notes.append(f"Odds refresh: {refresh_state or 'idle'}")

    any_live = bool(tick.get("anyLive"))
    if any_live:
        message = "Live games in progress -- a restart interrupts live-lens ticks and live prop hydration"
        if args.allow_live_games:
            notes.append(f"{message} (allowed)")
        else:
            # A warning, not a blocker: live games are normal for hours at a
            # time, and treating them as a hard block would make deploying
            # nearly impossible in season. Surfaced so it is a decision.
            notes.append(f"WARNING: {message}")
    else:
        notes.append("No live games")

    # A restart also destroys an in-flight board build (~23 min of work), which
    # every earlier version of this script was blind to. UNKNOWN blocks: an
    # unreadable log is not evidence of a quiet worker, and this script already
    # produced one bad window tonight by letting an unreadable state read as
    # benign.
    build_in_flight, build_facts = board_build_state()
    if build_in_flight is None:
        blockers.append(
            f"Board build state UNKNOWN ({build_facts.get('reason')}) -- "
            "cannot confirm no build is in flight"
        )
    elif build_in_flight:
        remaining = build_facts.get("estimated_seconds_remaining")
        typical = build_facts.get("typical_build_minutes")
        detail = f"started={build_facts.get('newest_build_start')}"
        if typical is not None:
            detail += f", typical={typical}min"
        if remaining is not None:
            detail += f", ~{int(remaining) // 60}min remaining"
        blockers.append(f"Board build IN FLIGHT on refresh-worker ({detail})")
    else:
        note = f"Board build idle (last completed {build_facts.get('newest_build_complete')})"
        if build_facts.get("typical_build_minutes") is not None:
            note += f"; a build takes ~{build_facts['typical_build_minutes']}min, so that is the quiet window a deploy needs"
        notes.append(note)

    print("\nDeploy safety check")
    for note in notes:
        print(f"  - {note}")

    if blockers:
        print("\nNOT CLEAR -- in flight:")
        for blocker in blockers:
            print(f"  * {blocker}")
        print("\nDeploying now would kill the above. Wait, or proceed deliberately.")
        return 1

    print("\nCLEAR: nothing in flight that a restart would interrupt.")
    if any_live and not args.allow_live_games:
        print("(Live games are in progress -- see the warning above.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
