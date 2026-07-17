"""Run MLB's vendored daily Monte Carlo sim for one date, then publish results.

Invoked (detached) by syndicate/features/shared/live_refresh_loop.py's MLB
daily-sim gate. Deliberately blocking inside this wrapper process rather than
being fire-and-forget: the tick-level publish sweep in live_refresh_loop.py
captures its "since" cutoff *before* spawning a detached subprocess, so any
later tick's sweep uses a *later* cutoff that would silently exclude this
subprocess's own (earlier) writes forever. Calling
publish_changed_hot_artifacts() synchronously, right here, after the sim
subprocess finishes, closes that race -- the same fix already applied to
scripts/run_queued_refresh_job.py.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.artifact_publisher import publish_changed_hot_artifacts
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.refresh_state_store import write_text_file


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _log_path(date_str: str, run_stamp: str) -> Path:
    return reports_root() / "live_refresh_loop" / "mlb_sim_runs" / f"{date_str}_{run_stamp}.log"


def _status_path(date_str: str, run_stamp: str) -> Path:
    return reports_root() / "live_refresh_loop" / "mlb_sim_runs" / f"{date_str}_{run_stamp}_status.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MLB's vendored daily sim for one date and publish results.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--season", required=True)
    parser.add_argument("--sims", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    command = [
        sys.executable,
        "tools/daily_update.py",
        "--workflow", "ui-daily",
        "--date", str(args.date),
        "--season", str(args.season),
        "--sims", str(int(args.sims)),
        "--workers", str(int(args.workers)),
        "--git-push", "off",
        "--validate-render-frontend", "off",
        "--build-next-day", "on",
        # Empty current-day odds must not kill the sim run: the live-odds
        # loop owns odds ingestion on its own cadence, and on late launches
        # (or All-Star-break days where the only game is already final) the
        # OddsAPI legitimately returns no markets. Without this the workflow
        # exits 1 before simming AND before the queued next-day build, which
        # left the board empty on 2026-07-16.
        "--allow-empty-current-oddsapi", "on",
    ]
    vendor_cwd = REPO_ROOT / "vendor" / "mlb_bettingv2"

    started_at = _utc_now()
    started_epoch = time.time()
    print(f"MLB_DAILY_SIM_START date={args.date} season={args.season} sims={args.sims} workers={args.workers} reason={args.reason}", flush=True)

    try:
        result = subprocess.run(
            command,
            cwd=str(vendor_cwd),
            capture_output=True,
            text=True,
            timeout=None,  # caller (live_refresh_loop.py) enforces its own launch-side timeout via SYNDICATE_MLB_SIM_TIMEOUT_SECONDS
        )
        return_code = int(result.returncode)
        combined_output = (result.stdout or "") + "\n---stderr---\n" + (result.stderr or "")
    except Exception as exc:
        return_code = 1
        combined_output = f"{type(exc).__name__}: {exc}"

    finished_at = _utc_now()
    ok = return_code == 0

    try:
        write_text_file(_log_path(str(args.date), run_stamp), combined_output)
    except Exception:
        pass

    published_count = 0
    try:
        published_count = publish_changed_hot_artifacts(started_epoch)
    except Exception:
        published_count = 0

    status_payload = {
        "ok": ok,
        "returnCode": return_code,
        "date": str(args.date),
        "season": str(args.season),
        "sims": int(args.sims),
        "workers": int(args.workers),
        "reason": str(args.reason),
        "command": command,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "publishedArtifacts": published_count,
    }
    try:
        write_json_file(_status_path(str(args.date), run_stamp), status_payload)
    except Exception:
        pass

    print(
        f"MLB_DAILY_SIM_END date={args.date} return_code={return_code} ok={ok} "
        f"published_artifacts={published_count}",
        flush=True,
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
