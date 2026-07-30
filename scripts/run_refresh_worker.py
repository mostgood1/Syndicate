from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.ops_refresh import launch_refresh_run
from syndicate.features.shared.ops_refresh import _active_sports_for_date
from syndicate.features.shared.ops_refresh import _REFRESH_WORKER_LANE_KEY
from syndicate.features.shared.ops_refresh import _refresh_lane_key
from syndicate.features.shared.ops_refresh import _refresh_manifest_filename
from pipeline.intelligence_state import start_intelligence_state_background_loop
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.shared.live_refresh_loop import _run_mlb_sim_tick


def _refresh_state_store() -> dict[str, Any]:
    from syndicate.features.shared.refresh_state_store import assert_refresh_state_backend_ready
    from syndicate.features.shared.refresh_state_store import data_root
    from syndicate.features.shared.refresh_state_store import read_json_file
    from syndicate.features.shared.refresh_state_store import reports_root
    from syndicate.features.shared.refresh_state_store import write_json_file

    return {
        "assert_refresh_state_backend_ready": assert_refresh_state_backend_ready,
        "data_root": data_root,
        "read_json_file": read_json_file,
        "reports_root": reports_root,
        "write_json_file": write_json_file,
    }


def _default_latest_manifest_path() -> Path:
    # This poll loop only ever runs on refresh-worker, and it's the only
    # process that claims queued/external-runner contracts -- so its manifest
    # must always be refresh-worker's own lane (matching the same hardcoded
    # lane launch_refresh_run resolves external-runner launches to), regardless
    # of which service actually enqueued the job.
    lane_key = _refresh_lane_key(_REFRESH_WORKER_LANE_KEY)
    return _refresh_state_store()["reports_root"]() / "refresh_status" / "latest" / _refresh_manifest_filename(lane_key)


def _default_worker_status_path() -> Path:
    return _refresh_state_store()["reports_root"]() / "refresh_status" / "latest" / "refresh_worker_status.json"


def _default_poll_seconds() -> float:
    raw_value = str(os.environ.get("SYNDICATE_REFRESH_WORKER_POLL_SECONDS") or "30").strip()
    try:
        poll_seconds = float(raw_value)
    except ValueError:
        poll_seconds = 30.0
    return max(1.0, poll_seconds)


def _default_max_active_jobs() -> int:
    raw_value = str(os.environ.get("SYNDICATE_REFRESH_WORKER_MAX_ACTIVE_JOBS") or "1").strip()
    try:
        value = int(raw_value)
    except ValueError:
        value = 1
    return max(1, value)


def _default_stuck_claim_timeout_minutes() -> int:
    raw_value = str(os.environ.get("SYNDICATE_REFRESH_WORKER_STUCK_CLAIM_TIMEOUT_MINUTES") or "15").strip()
    try:
        value = int(raw_value)
    except ValueError:
        value = 15
    return max(1, value)


def _mlb_auto_refresh_enabled() -> bool:
    raw_value = str(os.environ.get("MLB_ENABLE_REFRESH_WORKER_AUTORUN") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _mlb_live_lens_report_path(selected_date: str) -> Path:
    data_root = _refresh_state_store()["data_root"]()
    date_slug = str(selected_date or "").replace("-", "_")
    return data_root / "mlb_source" / "source_artifacts" / "data" / "live_lens" / f"live_lens_report_{date_slug}.json"


def _file_age_seconds(path: Path) -> float | None:
    try:
        stat_result = path.stat()
    except Exception:
        return None
    return max(0.0, time.time() - float(stat_result.st_mtime))


def _mlb_live_refresh_interval_seconds() -> int:
    raw_value = str(os.environ.get("MLB_LIVE_ODDSAPI_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw_value or 60)
    except ValueError:
        value = 60
    return max(1, value)


def _launch_autorun_mlb_refresh(
    *,
    latest_manifest_path: Path,
    worker_status_path: Path,
    refresh_cycle: dict[str, int],
) -> bool:
    if not _mlb_auto_refresh_enabled():
        return False
    selected_date = central_today_iso()
    report_path = _mlb_live_lens_report_path(selected_date)
    report_age_seconds = _file_age_seconds(report_path)
    if report_age_seconds is not None and report_age_seconds < float(_mlb_live_refresh_interval_seconds()):
        return False

    try:
        result = launch_refresh_run(
            date=selected_date,
            sports="mlb",
            phase="live",
            execution_mode="source",
            regions="us",
            skip_mirror=True,
            mode=str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MODE") or "full"),
            launch_mode="web_process",
        )
    except Exception as exc:
        _write_worker_status(
            worker_status_path=worker_status_path,
            latest_manifest_path=latest_manifest_path,
            state="error",
            detail=f"Failed to auto-launch MLB refresh: {type(exc).__name__}: {exc}",
            ran_job=False,
            latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
            refresh_cycle=refresh_cycle,
        )
        return False

    refresh_cycle["claimed_count"] = int(refresh_cycle.get("claimed_count") or 0) + 1
    _write_worker_status(
        worker_status_path=worker_status_path,
        latest_manifest_path=latest_manifest_path,
        state="launched",
        detail=f"Auto-launched MLB refresh because {selected_date} report was stale.",
        ran_job=True,
        run_exit_code=None,
        latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
        launch_pid=int(result.get("pid") or 0) or None,
        refresh_cycle=refresh_cycle,
    )
    return True


# NFL/NCAAF/NCAAB have no live worker coverage today -- they only ever
# refreshed via the daily-update GHA cron, since live_refresh_loop.py's
# adaptive tick only covers MLB/NBA/WNBA/NHL. Mirrors the MLB autorun above,
# but these are weekly (not daily) sports, so it uses its own last-attempt
# marker for staleness instead of a per-date report file, and reuses
# ops_refresh's own season-window gate rather than duplicating those windows
# here.
def _weekly_sports_auto_refresh_enabled() -> bool:
    raw_value = str(os.environ.get("WEEKLY_SPORTS_ENABLE_REFRESH_WORKER_AUTORUN") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _weekly_sports_refresh_interval_seconds() -> int:
    raw_value = str(os.environ.get("WEEKLY_SPORTS_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw_value or 21600)
    except ValueError:
        value = 21600
    return max(1, value)


def _weekly_sports_autorun_status_path() -> Path:
    return _refresh_state_store()["reports_root"]() / "refresh_status" / "latest" / "weekly_sports_autorun_status.json"


def _active_weekly_sports_for_date(selected_date: str) -> str:
    active = {item.strip().lower() for item in _active_sports_for_date(selected_date).split(",") if item.strip()}
    return ",".join(sport for sport in ("nfl", "ncaaf", "ncaab") if sport in active)


def _launch_autorun_weekly_sports_refresh(
    *,
    latest_manifest_path: Path,
    worker_status_path: Path,
    refresh_cycle: dict[str, int],
) -> bool:
    if not _weekly_sports_auto_refresh_enabled():
        return False
    selected_date = central_today_iso()
    weekly_sports = _active_weekly_sports_for_date(selected_date)
    if not weekly_sports:
        return False

    status_path = _weekly_sports_autorun_status_path()
    last_status = _refresh_state_store()["read_json_file"](status_path) or {}
    last_epoch = float((last_status or {}).get("epoch") or 0.0)
    if last_epoch > 0.0 and (time.time() - last_epoch) < float(_weekly_sports_refresh_interval_seconds()):
        return False

    try:
        result = launch_refresh_run(
            date=selected_date,
            sports=weekly_sports,
            phase="live",
            execution_mode="source",
            regions="us",
            skip_mirror=True,
            mode=str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MODE") or "full"),
            launch_mode="web_process",
        )
    except Exception as exc:
        _refresh_state_store()["write_json_file"](status_path, {"epoch": time.time(), "sports": weekly_sports, "date": selected_date, "error": f"{type(exc).__name__}: {exc}"})
        _write_worker_status(
            worker_status_path=worker_status_path,
            latest_manifest_path=latest_manifest_path,
            state="error",
            detail=f"Failed to auto-launch weekly-sports refresh ({weekly_sports}): {type(exc).__name__}: {exc}",
            ran_job=False,
            latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
            refresh_cycle=refresh_cycle,
        )
        return False

    _refresh_state_store()["write_json_file"](status_path, {"epoch": time.time(), "sports": weekly_sports, "date": selected_date})
    refresh_cycle["claimed_count"] = int(refresh_cycle.get("claimed_count") or 0) + 1
    _write_worker_status(
        worker_status_path=worker_status_path,
        latest_manifest_path=latest_manifest_path,
        state="launched",
        detail=f"Auto-launched weekly-sports refresh ({weekly_sports}) for {selected_date}.",
        ran_job=True,
        run_exit_code=None,
        latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
        launch_pid=int(result.get("pid") or 0) or None,
        refresh_cycle=refresh_cycle,
    )
    return True


# Soccer (MLS et al.) gets its own dedicated autorun, deliberately separate
# from the NFL/NCAAF/NCAAB weekly-sports one above, per explicit user
# direction (2026-07-29): reusing that flag/cadence would have activated a
# currently-dark path for those three sports too, as a side effect of just
# fixing soccer. Root cause this exists to fix, confirmed live: soccer's
# pregame-only steps (soccer_{league}_schedule/odds/props/picks --
# scripts/refresh_odds_sources.py's _build_soccer_steps, phases=("pregame",))
# never ran anywhere in production. live-odds-worker is the only service
# with SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP on, and it's pinned to
# SYNDICATE_LIVE_ODDS_REFRESH_PHASE=live, so those steps were silently
# excluded from the one tick that's actually running -- only
# soccer_{league}_artifacts (phases=("pregame", "live")) ever fired, against
# stale/missing odds and no real recommendations coverage. Confirmed via
# /soccer/mls/api/cards: this week's Saturday fixtures all carried
# is_unsimulated_placeholder=True (no real line, no sim -- matches todo #52's
# "71% of MLS board has no sim projection at all"), while Tue/Wed fixtures
# earlier in the same week did not, consistent with the pregame pipeline
# simply never running for the *current* week's later games.
#
# default_week()/_soccer_artifact_scope_args() (soccer/sources.py,
# refresh_odds_sources.py) already resolve the CONTAINING week correctly --
# there is no "wait until game day" gate to fix. phase="all" here is what
# actually runs schedule/odds/props/picks (pregame-only) AND artifacts/
# live_state (pregame+live / live-only) together in one launch, instead of
# needing two separate phase-scoped calls.
def _soccer_weekly_refresh_enabled() -> bool:
    raw_value = str(os.environ.get("SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _soccer_weekly_refresh_interval_seconds() -> int:
    raw_value = str(os.environ.get("SYNDICATE_SOCCER_WEEKLY_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw_value or 14400)  # 4h default -- shorter than NFL/NCAAF's 6h since soccer's tracked leagues run mid-week fixtures too, not just a single weekly slate.
    except ValueError:
        value = 14400
    return max(1, value)


def _soccer_weekly_autorun_status_path() -> Path:
    return _refresh_state_store()["reports_root"]() / "refresh_status" / "latest" / "soccer_weekly_autorun_status.json"


def _soccer_active_for_date(selected_date: str) -> bool:
    active = {item.strip().lower() for item in _active_sports_for_date(selected_date).split(",") if item.strip()}
    return "soccer" in active


def _launch_autorun_soccer_weekly_refresh(
    *,
    latest_manifest_path: Path,
    worker_status_path: Path,
    refresh_cycle: dict[str, int],
) -> bool:
    if not _soccer_weekly_refresh_enabled():
        return False
    selected_date = central_today_iso()
    if not _soccer_active_for_date(selected_date):
        return False

    status_path = _soccer_weekly_autorun_status_path()
    last_status = _refresh_state_store()["read_json_file"](status_path) or {}
    last_epoch = float((last_status or {}).get("epoch") or 0.0)
    if last_epoch > 0.0 and (time.time() - last_epoch) < float(_soccer_weekly_refresh_interval_seconds()):
        return False

    try:
        result = launch_refresh_run(
            date=selected_date,
            sports="soccer",
            phase="all",
            execution_mode="source",
            regions="us",
            skip_mirror=True,
            mode=str(os.environ.get("SYNDICATE_LIVE_ODDS_REFRESH_MODE") or "full"),
            launch_mode="web_process",
        )
    except Exception as exc:
        _refresh_state_store()["write_json_file"](status_path, {"epoch": time.time(), "sports": "soccer", "date": selected_date, "error": f"{type(exc).__name__}: {exc}"})
        _write_worker_status(
            worker_status_path=worker_status_path,
            latest_manifest_path=latest_manifest_path,
            state="error",
            detail=f"Failed to auto-launch soccer weekly refresh: {type(exc).__name__}: {exc}",
            ran_job=False,
            latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
            refresh_cycle=refresh_cycle,
        )
        return False

    _refresh_state_store()["write_json_file"](status_path, {"epoch": time.time(), "sports": "soccer", "date": selected_date})
    refresh_cycle["claimed_count"] = int(refresh_cycle.get("claimed_count") or 0) + 1
    _write_worker_status(
        worker_status_path=worker_status_path,
        latest_manifest_path=latest_manifest_path,
        state="launched",
        detail=f"Auto-launched soccer weekly refresh for {selected_date}.",
        ran_job=True,
        run_exit_code=None,
        latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
        launch_pid=int(result.get("pid") or 0) or None,
        refresh_cycle=refresh_cycle,
    )
    return True


# Prediction reconciliation/grading never runs on Render today -- it was only
# ever invoked from scripts/daily_update.ps1's GHA pipeline. Runs in-process
# (unlike the launch_refresh_run-based autoruns above) since it's a light
# read/write over the prediction ledger, not a heavy subprocess. Reconciles
# both yesterday's and today's Central-time dates on every run: matching
# predictions are skipped cheaply (see reconcile_prediction_results_for_date),
# so this is safe to call repeatedly rather than needing to precisely
# replicate the old pipeline's exact run-time semantics.
def _reconciliation_auto_refresh_enabled() -> bool:
    raw_value = str(os.environ.get("RECONCILIATION_ENABLE_REFRESH_WORKER_AUTORUN") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _reconciliation_interval_seconds() -> int:
    raw_value = str(os.environ.get("RECONCILIATION_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw_value or 86400)
    except ValueError:
        value = 86400
    return max(1, value)


def _reconciliation_autorun_status_path() -> Path:
    return _refresh_state_store()["reports_root"]() / "refresh_status" / "latest" / "reconciliation_autorun_status.json"


def _launch_autorun_reconciliation(
    *,
    latest_manifest_path: Path,
    worker_status_path: Path,
    refresh_cycle: dict[str, int],
) -> bool:
    if not _reconciliation_auto_refresh_enabled():
        return False

    status_path = _reconciliation_autorun_status_path()
    last_status = _refresh_state_store()["read_json_file"](status_path) or {}
    last_epoch = float((last_status or {}).get("epoch") or 0.0)
    if last_epoch > 0.0 and (time.time() - last_epoch) < float(_reconciliation_interval_seconds()):
        return False

    from syndicate.features.prediction_reconciliation import reconcile_prediction_results_for_date

    today_date = central_today_iso()
    yesterday_date = (date.fromisoformat(today_date) - timedelta(days=1)).isoformat()
    target_dates = (yesterday_date, today_date)
    summaries: dict[str, Any] = {}
    error_text: str | None = None
    try:
        for target_date in target_dates:
            result = reconcile_prediction_results_for_date(target_date)
            summaries[target_date] = result.get("summary")
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"

    _refresh_state_store()["write_json_file"](
        status_path,
        {"epoch": time.time(), "dates": list(target_dates), "summaries": summaries, "error": error_text},
    )

    if error_text:
        _write_worker_status(
            worker_status_path=worker_status_path,
            latest_manifest_path=latest_manifest_path,
            state="error",
            detail=f"Failed to auto-run prediction reconciliation: {error_text}",
            ran_job=False,
            latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
            refresh_cycle=refresh_cycle,
        )
        return False

    refresh_cycle["claimed_count"] = int(refresh_cycle.get("claimed_count") or 0) + 1
    _write_worker_status(
        worker_status_path=worker_status_path,
        latest_manifest_path=latest_manifest_path,
        state="launched",
        detail=f"Auto-ran prediction reconciliation for {yesterday_date} and {today_date}.",
        ran_job=True,
        run_exit_code=0,
        latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
        refresh_cycle=refresh_cycle,
    )
    return True


def _pid_is_running(pid: int | None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _parse_utc_timestamp(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except Exception:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _latest_manifest_payload(latest_manifest_path: Path) -> dict[str, Any]:
    payload = _refresh_state_store()["read_json_file"](latest_manifest_path) or {}
    return payload if isinstance(payload, dict) else {}


def _artifact_path_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and str(value).strip():
            return str(value).strip()
    return ""


def _job_status_path_from_manifest(payload: dict[str, Any]) -> Path | None:
    run_summary_path_text = _artifact_path_text(payload, "runSummaryPath")
    if not run_summary_path_text:
        external_runner = payload.get("externalRunner") if isinstance(payload.get("externalRunner"), dict) else {}
        if isinstance(external_runner, dict):
            run_summary_path_text = _artifact_path_text(external_runner, "runSummaryPath")
    if not run_summary_path_text:
        return None
    return Path(run_summary_path_text).parent / "refresh_job_status.json"


def _odds_refresh_path_from_manifest(payload: dict[str, Any]) -> Path | None:
    odds_refresh_path_text = _artifact_path_text(payload, "oddsRefreshPath", "stdoutPath")
    if not odds_refresh_path_text:
        external_runner = payload.get("externalRunner") if isinstance(payload.get("externalRunner"), dict) else {}
        if isinstance(external_runner, dict):
            odds_refresh_path_text = _artifact_path_text(external_runner, "stdoutPath")
    if not odds_refresh_path_text:
        return None
    return Path(odds_refresh_path_text)


def _current_active_job_count(latest_manifest_path: Path) -> int:
    payload = _latest_manifest_payload(latest_manifest_path)
    state = str(payload.get("state") or "").strip().lower()
    if state not in {"claimed", "launched", "running"}:
        return 0
    pid = payload.get("launchPid")
    if isinstance(pid, int) and _pid_is_running(pid):
        return 1
    pid = payload.get("pid")
    if isinstance(pid, int) and _pid_is_running(pid):
        return 1
    return 0


def _recover_stuck_claim(latest_manifest_path: Path, *, timeout_minutes: int) -> bool:
    payload = _latest_manifest_payload(latest_manifest_path)
    if str(payload.get("state") or "").strip().lower() != "claimed":
        return False
    if _current_active_job_count(latest_manifest_path) > 0:
        return False
    claimed_at = _parse_utc_timestamp(str(payload.get("workerClaimedAt") or "") or str(payload.get("runnerClaimedAt") or "") or str(payload.get("claimedAt") or ""))
    if claimed_at is None:
        return False
    age_minutes = max(0, int((datetime.utcnow() - claimed_at).total_seconds() // 60))
    if age_minutes < int(timeout_minutes):
        return False
    payload["state"] = "pending_external"
    payload["workerRecoveredAt"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    payload["workerRecoveryReason"] = f"stuck_claim_timeout_{timeout_minutes}m"
    for key in ("workerClaimedAt", "workerKind", "launchPid"):
        payload.pop(key, None)
    _refresh_state_store()["write_json_file"](latest_manifest_path, payload)
    return True


def _recover_dead_active_contract(latest_manifest_path: Path) -> bool:
    payload = _latest_manifest_payload(latest_manifest_path)
    state = str(payload.get("state") or "").strip().lower()
    if state not in {"launched", "running"}:
        return False

    launch_pid_raw = payload.get("launchPid")
    pid_raw = payload.get("pid")
    launch_pid = int(launch_pid_raw) if isinstance(launch_pid_raw, int) else None
    pid = int(pid_raw) if isinstance(pid_raw, int) else None

    if launch_pid is not None and _pid_is_running(launch_pid):
        return False
    if pid is not None and _pid_is_running(pid):
        return False
    if launch_pid is None and pid is None:
        return False

    job_status_path = _job_status_path_from_manifest(payload)
    job_status = _refresh_state_store()["read_json_file"](job_status_path) if job_status_path is not None else {}
    job_status = job_status if isinstance(job_status, dict) else {}
    job_status_state = str(job_status.get("state") or "").strip().lower()
    job_status_updated_at = _parse_utc_timestamp(str(job_status.get("updatedAt") or ""))
    if job_status_state == "running" and job_status_updated_at is not None:
        if (datetime.utcnow() - job_status_updated_at).total_seconds() < 120:
            return False
    if job_status_state in {"finished", "failed"}:
        return False

    odds_refresh_path = _odds_refresh_path_from_manifest(payload)
    if odds_refresh_path is not None:
        odds_refresh_payload = _refresh_state_store()["read_json_file"](odds_refresh_path)
        if isinstance(odds_refresh_payload, dict):
            return False

    run_summary_path_text = _artifact_path_text(payload, "runSummaryPath")
    if not run_summary_path_text:
        external_runner = payload.get("externalRunner") if isinstance(payload.get("externalRunner"), dict) else {}
        if isinstance(external_runner, dict):
            run_summary_path_text = _artifact_path_text(external_runner, "runSummaryPath")
    if run_summary_path_text:
        run_summary = _refresh_state_store()["read_json_file"](Path(run_summary_path_text)) or {}
        if isinstance(run_summary, dict):
            run_summary_state = str(run_summary.get("state") or "").strip().lower()
            if run_summary_state in {"finished", "failed"} or run_summary.get("finishedAt"):
                return False

    payload["state"] = "failed"
    payload["workerRecoveredAt"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    payload["workerRecoveryReason"] = "dead_refresh_process"
    for key in ("launchPid", "pid", "workerClaimedAt", "workerKind"):
        payload.pop(key, None)
    _refresh_state_store()["write_json_file"](latest_manifest_path, payload)
    return True


def _has_pending_external_contract(latest_manifest_path: Path) -> bool:
    payload = _refresh_state_store()["read_json_file"](latest_manifest_path) or {}
    state = str(payload.get("state") or "").strip().lower()
    if state == "pending_external":
        return isinstance(payload.get("externalRunner"), dict)
    if state != "running":
        return False
    if isinstance(payload.get("pid"), int) and int(payload.get("pid") or 0) > 0:
        return False
    contract = payload.get("externalRunner") if isinstance(payload.get("externalRunner"), dict) else {}
    if str(contract.get("queue_state") or "").strip().lower() != "queued":
        return False
    return bool(str(contract.get("command") or "").strip()) or bool(str(contract.get("runStamp") or "").strip())


def _build_runner_command(latest_manifest_path: Path) -> list[str]:
    payload = _refresh_state_store()["read_json_file"](latest_manifest_path) or {}
    run_stamp = str(payload.get("runStamp") or "").strip()
    return [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_queued_refresh_job.py"),
        "--latest-manifest",
        str(latest_manifest_path),
        *(["--run-stamp", run_stamp] if run_stamp else []),
    ]


def _write_worker_status(
    *,
    worker_status_path: Path,
    latest_manifest_path: Path,
    state: str,
    detail: str,
    ran_job: bool = False,
    run_exit_code: int | None = None,
    latest_manifest_state: str | None = None,
    launch_pid: int | None = None,
    refresh_cycle: dict[str, int] | None = None,
) -> None:
    _refresh_state_store()["write_json_file"](
        worker_status_path,
        {
            "state": state,
            "detail": detail,
            "latestManifestPath": str(latest_manifest_path),
            "ranJob": bool(ran_job),
            "runExitCode": int(run_exit_code) if run_exit_code is not None else None,
            "latestManifestState": latest_manifest_state,
            "launchPid": int(launch_pid) if launch_pid is not None else None,
            "refreshCycle": refresh_cycle or {"claimed_count": 0, "reclaimed_count": 0, "skipped_due_to_cap": 0},
            "updatedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        },
    )


def _spawn_pending_job(latest_manifest_path: Path) -> subprocess.Popen[Any]:
    command = _build_runner_command(latest_manifest_path)
    popen_kwargs: dict[str, Any] = {
        "cwd": str(REPO_ROOT),
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    return subprocess.Popen(command, **popen_kwargs)


def _mark_claimed_external_contract(latest_manifest_path: Path) -> None:
    latest_manifest = _refresh_state_store()["read_json_file"](latest_manifest_path) or {}
    if not latest_manifest:
        return
    claimed_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    latest_manifest["state"] = "claimed"
    latest_manifest["workerClaimedAt"] = claimed_at
    latest_manifest["workerKind"] = "refresh_worker"
    _refresh_state_store()["write_json_file"](latest_manifest_path, latest_manifest)


def _mark_throttled_worker_status(*, worker_status_path: Path, latest_manifest_path: Path, active_jobs: int, max_active_jobs: int) -> None:
    _write_worker_status(
        worker_status_path=worker_status_path,
        latest_manifest_path=latest_manifest_path,
        state="throttled",
        detail=f"Active refresh jobs {active_jobs} reached the configured limit {max_active_jobs}.",
        ran_job=False,
        latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
        refresh_cycle={"claimed_count": 0, "reclaimed_count": 0, "skipped_due_to_cap": 1},
    )


def _diag_log_all_process_memory(stage: str) -> None:
    # Temporary boot-crash diagnostic: the worker has been OOM-killed (2GB
    # limit) within seconds-to-minutes of boot even with the MLB daily-sim
    # subprocess trigger disabled, so the cause is either a boot-time cost in
    # this process itself or a surviving detached subprocess (sim jobs are
    # launched with start_new_session=True specifically so they outlive a
    # worker restart -- see _launch_mlb_daily_sim) that isn't visible in this
    # process's own memory. log_all_process_memory enumerates every process
    # in the container (via /proc, falling back to psutil) with RSS, so this
    # settles it directly instead of guessing further. Remove once resolved.
    try:
        from syndicate.features.shared.memory_observability import log_all_process_memory

        log_all_process_memory(stage)
    except Exception as exc:
        print(f"[refresh_worker] DIAG_MEMORY_LOG_FAILED stage={stage} {type(exc).__name__}: {exc}", flush=True)


def main() -> int:
    store = _refresh_state_store()
    assert_refresh_state_backend_ready = store["assert_refresh_state_backend_ready"]
    read_json_file = store["read_json_file"]
    print("[refresh_worker] BOOTED", flush=True)
    _diag_log_all_process_memory("boot")
    assert_refresh_state_backend_ready(process_name="refresh-worker")
    if str(os.environ.get("SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP") or "").strip().lower() in {"1", "true", "yes", "on"}:
        print("[refresh_worker] INTELLIGENCE_LOOP_ENABLED calling start_intelligence_state_background_loop()", flush=True)
        loop_started = start_intelligence_state_background_loop()
        print(f"[refresh_worker] INTELLIGENCE_LOOP_START_RESULT started={loop_started}", flush=True)
    else:
        print("[refresh_worker] INTELLIGENCE_LOOP_DISABLED", flush=True)
    parser = argparse.ArgumentParser(description="Poll Syndicate refresh state and execute queued external-runner jobs.")
    parser.add_argument("--latest-manifest", default=str(_default_latest_manifest_path()))
    parser.add_argument("--worker-status", default=str(_default_worker_status_path()))
    parser.add_argument("--poll-seconds", type=float, default=_default_poll_seconds())
    parser.add_argument("--max-active-jobs", type=int, default=_default_max_active_jobs())
    parser.add_argument("--stuck-claim-timeout-minutes", type=int, default=_default_stuck_claim_timeout_minutes())
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--max-iterations", type=int, default=0)
    args = parser.parse_args()

    latest_manifest_path = Path(str(args.latest_manifest or "").strip()).expanduser().resolve()
    worker_status_path = Path(str(args.worker_status or "").strip()).expanduser().resolve()
    poll_seconds = max(1.0, float(args.poll_seconds))
    max_active_jobs = max(1, int(args.max_active_jobs))
    stuck_claim_timeout_minutes = max(1, int(args.stuck_claim_timeout_minutes))
    max_iterations = max(0, int(args.max_iterations))

    iterations = 0
    while True:
        # MLB daily sim / look-ahead / evening-next-day sim: independent of
        # the queued-contract handling below, so it runs every poll cycle
        # regardless of what the if/elif chain decides. Each sub-decision
        # has its own interval gate (e.g. SYNDICATE_MLB_SIM_CHECK_INTERVAL_SECONDS),
        # so calling this every ~30s is cheap -- most calls are a no-op.
        # Ownership is controlled by SYNDICATE_ENABLE_MLB_DAILY_SIM_TRIGGER /
        # SYNDICATE_LOOK_AHEAD_ENABLED / SYNDICATE_MLB_EVENING_NEXT_DAY_SIM_ENABLED,
        # relocated here from live-odds-worker 2026-07-20 to isolate the
        # 1000-sim Monte Carlo job's memory footprint from that worker's
        # odds-refresh/SmartSim/live-lens load.
        try:
            mlb_sim_meta = _run_mlb_sim_tick()
            if mlb_sim_meta:
                print(f"[refresh_worker] MLB_SIM_TICK {json.dumps(mlb_sim_meta, sort_keys=True, default=str)}", flush=True)
        except Exception as exc:
            print(f"[refresh_worker] MLB_SIM_TICK_ERROR {type(exc).__name__}: {exc}", flush=True)
        _diag_log_all_process_memory("post_mlb_sim_tick")

        refresh_cycle = {"claimed_count": 0, "reclaimed_count": 0, "skipped_due_to_cap": 0}
        if _recover_stuck_claim(latest_manifest_path, timeout_minutes=stuck_claim_timeout_minutes):
            refresh_cycle["reclaimed_count"] = 1
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="recovered",
                detail=f"Recovered a stuck claimed refresh contract older than {stuck_claim_timeout_minutes} minutes.",
                ran_job=False,
                latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
                refresh_cycle=refresh_cycle,
            )

        if _recover_dead_active_contract(latest_manifest_path):
            refresh_cycle["reclaimed_count"] = max(1, int(refresh_cycle.get("reclaimed_count") or 0))
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="recovered",
                detail="Recovered a dead refresh contract and released the active-job cap.",
                ran_job=False,
                latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
                refresh_cycle=refresh_cycle,
            )

        active_jobs = _current_active_job_count(latest_manifest_path)
        if active_jobs >= max_active_jobs:
            refresh_cycle["skipped_due_to_cap"] = 1
            _mark_throttled_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                active_jobs=active_jobs,
                max_active_jobs=max_active_jobs,
            )
            if args.run_once:
                return 0

        if _has_pending_external_contract(latest_manifest_path):
            refresh_cycle["claimed_count"] = 1
            _mark_claimed_external_contract(latest_manifest_path)
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="claimed",
                detail="Queued refresh contract detected; job runner launched asynchronously.",
                ran_job=False,
                refresh_cycle=refresh_cycle,
            )
            process = _spawn_pending_job(latest_manifest_path)
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="launched",
                detail="Queued refresh contract launched asynchronously.",
                ran_job=True,
                run_exit_code=None,
                latest_manifest_state=str((read_json_file(latest_manifest_path) or {}).get("state") or "").strip().lower() or None,
                launch_pid=int(getattr(process, "pid", 0) or 0) or None,
                refresh_cycle=refresh_cycle,
            )
            if args.run_once:
                return 0
        elif _launch_autorun_mlb_refresh(
            latest_manifest_path=latest_manifest_path,
            worker_status_path=worker_status_path,
            refresh_cycle=refresh_cycle,
        ):
            if args.run_once:
                return 0
        elif _launch_autorun_weekly_sports_refresh(
            latest_manifest_path=latest_manifest_path,
            worker_status_path=worker_status_path,
            refresh_cycle=refresh_cycle,
        ):
            if args.run_once:
                return 0
        elif _launch_autorun_soccer_weekly_refresh(
            latest_manifest_path=latest_manifest_path,
            worker_status_path=worker_status_path,
            refresh_cycle=refresh_cycle,
        ):
            if args.run_once:
                return 0
        elif _launch_autorun_reconciliation(
            latest_manifest_path=latest_manifest_path,
            worker_status_path=worker_status_path,
            refresh_cycle=refresh_cycle,
        ):
            if args.run_once:
                return 0
        elif args.run_once:
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="idle",
                detail="No queued external refresh contract was available.",
                ran_job=False,
                run_exit_code=None,
                latest_manifest_state=str((read_json_file(latest_manifest_path) or {}).get("state") or "").strip().lower() or None,
                refresh_cycle=refresh_cycle,
            )
            return 0

        iterations += 1
        if args.run_once:
            return 0
        if max_iterations and iterations >= max_iterations:
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="idle",
                detail="Worker reached the configured max iterations.",
                ran_job=False,
                refresh_cycle=refresh_cycle,
            )
            return 0
        time.sleep(poll_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[refresh_worker_fatal] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        raise