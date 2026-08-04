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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--allow-live-games",
        action="store_true",
        help="Treat in-progress games as acceptable. They are only a warning by default, never a block.",
    )
    args = parser.parse_args()

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
