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
import tempfile
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


# The ops log only ever gets eyeballed for "how did this run end", and the
# failure detail that matters lives at the tail. Capping what we read back
# keeps a multi-hundred-MB workflow log from being pulled into RAM (and then
# pushed through the keyvalue-backed state store) just to surface a traceback.
_MAX_CAPTURED_LOG_BYTES = 512 * 1024


def _read_log_tail(path: Path, max_bytes: int = _MAX_CAPTURED_LOG_BYTES) -> str:
    try:
        size = path.stat().st_size
    except Exception:
        return ""
    try:
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            payload = handle.read()
    except Exception as exc:
        return f"<could not read sim log: {type(exc).__name__}: {exc}>"
    text = payload.decode("utf-8", errors="replace")
    if size > max_bytes:
        skipped = size - max_bytes
        return f"<truncated: showing last {max_bytes} of {size} bytes ({skipped} omitted)>\n{text}"
    return text


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
    parser.add_argument("--only-game-pks", default="", help="Comma-separated gamePk allowlist; forwarded to daily_update.py's --only-game-pks unless empty.")
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
        # Next-day build off in the worker-centric loop: the date-rollover
        # first_appearance gate sims the new day at midnight Central and the
        # look-ahead warms next-day odds, so chaining tomorrow's slate here
        # only doubled runtime/memory and -- because the publish sweep runs
        # after the WHOLE job -- delayed today's artifacts by tomorrow's
        # entire build time.
        "--build-next-day", "off",
        # Empty current-day odds must not kill the sim run: the live-odds
        # loop owns odds ingestion on its own cadence, and on late launches
        # (or All-Star-break days where the only game is already final) the
        # OddsAPI legitimately returns no markets. Without this the workflow
        # exits 1 before simming AND before the queued next-day build, which
        # left the board empty on 2026-07-16.
        "--allow-empty-current-oddsapi", "on",
    ]
    only_game_pks = str(args.only_game_pks or "").strip()
    if only_game_pks:
        command.extend(["--only-game-pks", only_game_pks])
    vendor_cwd = REPO_ROOT / "vendor" / "mlb_bettingv2"

    started_at = _utc_now()
    started_epoch = time.time()
    capture_path: Path | None = None
    print(f"MLB_DAILY_SIM_START date={args.date} season={args.season} sims={args.sims} workers={args.workers} reason={args.reason}", flush=True)

    try:
        # Stream the child's output straight to a temp file instead of
        # capture_output=True. The ui-daily workflow runs 3 profiles x every
        # game in the slate with verbose per-game logging, and capture_output
        # buffered ALL of it in this process's RAM for the entire run, then
        # transiently doubled it building the combined string. On a 2GB
        # container already running the sim itself that is pure overhead --
        # and this wrapper only ever needs a tail of it for the ops log below.
        with tempfile.NamedTemporaryFile(prefix="mlb_daily_sim_", suffix=".log", delete=False) as out_fh:
            capture_path = Path(out_fh.name)
            result = subprocess.run(
                command,
                cwd=str(vendor_cwd),
                stdout=out_fh,
                stderr=subprocess.STDOUT,
                # No timeout here: the launch side kills a stale run via
                # _MLB_SIM_MAX_RUNTIME_SECONDS (live_refresh_loop.py). Note
                # SYNDICATE_MLB_SIM_TIMEOUT_SECONDS is NOT what enforces it --
                # _mlb_sim_timeout_seconds() is defined but never called, so
                # the real ceiling is that hardcoded 90 minutes.
                timeout=None,
            )
        return_code = int(result.returncode)
        combined_output = _read_log_tail(capture_path)
    except Exception as exc:
        return_code = 1
        combined_output = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if capture_path is not None:
                capture_path.unlink(missing_ok=True)
        except Exception:
            pass

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
        "onlyGamePks": only_game_pks,
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
