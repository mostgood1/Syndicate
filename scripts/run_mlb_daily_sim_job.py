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
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.mlb.sources import daily_snapshot_oddsapi_game_lines_path
from syndicate.features.mlb.sources import daily_snapshot_oddsapi_hitter_props_path
from syndicate.features.mlb.sources import daily_snapshot_oddsapi_pitcher_props_path
from syndicate.features.shared.artifact_publisher import publish_changed_hot_artifacts
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.refresh_state_store import write_text_file


def _vendor_mlb_data_dir(vendor_cwd: Path) -> Path:
    # Mirrors vendor/mlb_bettingv2/tools/daily_update_multi_profile.py's own
    # _DATA_DIR resolution exactly. render.yaml sets MLB_BETTING_DATA_ROOT to
    # /opt/render/project/data/mlb_source/source_artifacts/data on all three
    # services -- a first attempt at this fix assumed the vendored tool read
    # its own git-checkout-relative data/ dir (the fallback below, used only
    # when the env var is unset) and hydrated THAT tree. Confirmed wrong via
    # a production sim-job log tail after deploying it: the run still logged
    # "no pitcher prop market entries in
    # .../mlb_source/source_artifacts/data/market/oddsapi/oddsapi_pitcher_props_*.json"
    # -- i.e. _DATA_DIR was actually the MLB_BETTING_DATA_ROOT override the
    # whole time, so the first fix wrote to a tree nothing ever reads.
    override = str(os.environ.get("MLB_BETTING_DATA_ROOT") or os.environ.get("MLB_BETTING_DATA_ROOT_DIR") or "").strip()
    if override:
        return Path(override).resolve()
    return (vendor_cwd / "data").resolve()


def _hydrate_vendor_oddsapi_mirror(date_str: str, vendor_cwd: Path) -> None:
    """Copy this service's already-fetched odds snapshots into the tree
    tools/daily_update_multi_profile.py's K-ladder-targets builder actually
    reads pitcher/hitter/game-line prop lines from (_DATA_DIR/market/oddsapi/
    oddsapi_*_<date>.json, resolved via _vendor_mlb_data_dir above). On
    Render that tree is MLB_BETTING_DATA_ROOT/market/oddsapi -- a real
    subfolder of the SAME data/mlb_source/source_artifacts tree the odds
    orchestrator (scripts/refresh_odds_sources.py -> refresh_mlb_oddsapi.py)
    already writes daily/snapshots/<date>/ into and that the normal hot-
    artifact sync keeps current on this service's own disk -- but the
    orchestrator only ever writes the snapshots/ copy, never a market/oddsapi/
    one. Before #129/#130 (commit 1465a5dc, 2026-07-29) this job called
    daily_update.py with --refresh-current-oddsapi on, which had
    daily_update.py do its own OddsAPI pull straight into market/oddsapi/ --
    incidentally also keeping it populated. That flag is now off (correctly,
    to stop refresh-worker duplicating live-odds-worker's OddsAPI calls), and
    nothing replaced the population it happened to provide as a side effect:
    K-ladder-targets silently regressed to "missing pitcher sim_dir or
    pitcher lines" on any date with no pre-existing artifact to fall back on
    (masked for a few days by _prefer_richer_k_ladder_targets_doc keeping
    older dates' already-written artifacts). This is a pure local file copy
    (whatever this service's own snapshot mirror already has, via the normal
    hot-artifact sync) -- no OddsAPI call, so it doesn't reintroduce the
    duplication #129/#130 removed. A missing source snapshot is left alone;
    daily_update_multi_profile.py already handles a genuinely absent pitcher
    lines file by skipping K-ladder-targets for that run.
    """
    dest_dir = _vendor_mlb_data_dir(vendor_cwd) / "market" / "oddsapi"
    token = date_str.replace("-", "_")
    pairs = (
        (daily_snapshot_oddsapi_game_lines_path(date_str), f"oddsapi_game_lines_{token}.json"),
        (daily_snapshot_oddsapi_pitcher_props_path(date_str), f"oddsapi_pitcher_props_{token}.json"),
        (daily_snapshot_oddsapi_hitter_props_path(date_str), f"oddsapi_hitter_props_{token}.json"),
    )
    for source, filename in pairs:
        try:
            if not source.exists() or not source.is_file():
                continue
            dest = dest_dir / filename
            if dest.exists() and dest.stat().st_mtime_ns >= source.stat().st_mtime_ns:
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            print(f"MLB_DAILY_SIM_HYDRATE_ODDSAPI_MIRROR copied {source} -> {dest}", flush=True)
        except Exception as exc:
            print(f"MLB_DAILY_SIM_HYDRATE_ODDSAPI_MIRROR_FAILED source={source} error={type(exc).__name__}: {exc}", flush=True)
            continue


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# The ops log only ever gets eyeballed for "how did this run end", and the
# failure detail that matters lives at the tail. Capping what we read back
# keeps a multi-hundred-MB workflow log from being pulled into RAM (and then
# pushed through the keyvalue-backed state store) just to surface a traceback.
_MAX_CAPTURED_LOG_BYTES = 512 * 1024


# Default matches live_refresh_loop.py's _MLB_SIM_MAX_RUNTIME_SECONDS (90 min)
# so leaving the env var unset preserves the effective ceiling that was in
# place before this was wired up. The two are related but not the same thing:
# this one KILLS a hung child, that one decides when a "running" pointer stops
# being trusted. Keeping this <= that value means a timed-out run is reaped
# here and reported honestly, rather than lingering until the pointer expires.
_DEFAULT_SIM_TIMEOUT_SECONDS = 90 * 60


def _timeout_seconds() -> int:
    raw = str(os.environ.get("SYNDICATE_MLB_SIM_TIMEOUT_SECONDS") or "").strip()
    try:
        if raw:
            return max(60, int(raw))
    except Exception:
        pass
    return _DEFAULT_SIM_TIMEOUT_SECONDS


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
        # #129: this job was still doing its OWN fresh OddsAPI pull by default
        # (daily_update.py's --refresh-current-oddsapi defaults "on") despite
        # the comment above already saying "the live-odds loop owns odds
        # ingestion" -- a second, redundant OddsAPI caller for MLB, on top of
        # the render.yaml-level duplication this same incident fixed. The sim
        # itself never consumes odds as a model input (join_odds_to_sim joins
        # odds onto sim output post-hoc), so it doesn't need a fresh pull --
        # whatever live-odds-worker last wrote (or nothing, per
        # --allow-empty-current-oddsapi above) is enough.
        "--refresh-current-oddsapi", "off",
    ]
    only_game_pks = str(args.only_game_pks or "").strip()
    if only_game_pks:
        command.extend(["--only-game-pks", only_game_pks])
    vendor_cwd = REPO_ROOT / "vendor" / "mlb_bettingv2"
    _hydrate_vendor_oddsapi_mirror(str(args.date), vendor_cwd)

    started_at = _utc_now()
    started_epoch = time.time()
    capture_path: Path | None = None
    print(f"MLB_DAILY_SIM_START date={args.date} season={args.season} sims={args.sims} workers={args.workers} reason={args.reason}", flush=True)

    timeout_seconds = _timeout_seconds()
    timed_out = False
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
                timeout=timeout_seconds,
            )
        return_code = int(result.returncode)
        combined_output = _read_log_tail(capture_path)
    except subprocess.TimeoutExpired:
        # subprocess.run has already killed the child by the time this
        # surfaces. Previously nothing enforced this at all: the comment here
        # claimed the launch side applied SYNDICATE_MLB_SIM_TIMEOUT_SECONDS,
        # but live_refresh_loop.py's reader for that var was never called by
        # anything (since removed) -- the only real ceiling was that module's
        # hardcoded 90-minute _MLB_SIM_MAX_RUNTIME_SECONDS, which is
        # stale-POINTER detection (when to stop trusting a "running" record),
        # not a kill. A genuinely hung sim therefore held the container for
        # 90 minutes before anything noticed.
        timed_out = True
        return_code = 124
        tail = _read_log_tail(capture_path) if capture_path is not None else ""
        combined_output = f"TimeoutExpired: killed after {timeout_seconds}s (SYNDICATE_MLB_SIM_TIMEOUT_SECONDS)\n{tail}"
        print(f"MLB_DAILY_SIM_TIMEOUT date={args.date} timeout_seconds={timeout_seconds}", flush=True)
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
        "timedOut": bool(timed_out),
        "timeoutSeconds": int(timeout_seconds),
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
