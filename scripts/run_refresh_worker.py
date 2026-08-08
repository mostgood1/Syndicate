from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
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
from syndicate.features.shared.timezone import central_datetime_from_epoch
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


def _bootstrap_soccer_seed_files(*, relative_subdir: str, glob_pattern: str) -> list[str]:
    # Shared by _bootstrap_soccer_player_seed_files (#145) and
    # _bootstrap_soccer_schedule_seed_files (#170 follow-up) -- same
    # deliberately narrow, provably safe pattern: only ever copies files
    # into a subdirectory that has NONE matching yet, so it can never touch
    # or replace anything the real pipeline has already written. See
    # _bootstrap_soccer_player_seed_files's own comment for why this doesn't
    # reuse bootstrap_data_root.py's broad copy-if-content-differs sync.
    try:
        data_root = _refresh_state_store()["data_root"]()
    except Exception as exc:
        print(f"[refresh_worker] SOCCER_SEED_BOOTSTRAP_SKIPPED subdir={relative_subdir} error={type(exc).__name__}: {exc}", flush=True)
        return []
    source_root = REPO_ROOT / "data" / "soccer_source"
    if not source_root.is_dir():
        return []
    seeded_leagues: list[str] = []
    for league_dir in sorted(source_root.iterdir()):
        if not league_dir.is_dir():
            continue
        source_dir = league_dir / relative_subdir
        source_files = sorted(source_dir.glob(glob_pattern)) if source_dir.is_dir() else []
        if not source_files:
            continue
        dest_dir = data_root / "soccer_source" / league_dir.name / relative_subdir
        existing = list(dest_dir.glob(glob_pattern)) if dest_dir.is_dir() else []
        if existing:
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        for src_file in source_files:
            shutil.copy2(src_file, dest_dir / src_file.name)
        seeded_leagues.append(league_dir.name)
    return seeded_leagues


def _bootstrap_soccer_player_seed_files() -> None:
    # #145. Root-caused live 2026-07-30: soccer's per-league player-roster
    # seed CSVs (data/soccer_source/{league}/players/players_{season}.csv --
    # committed to git, e.g. 572 real MLS players) are what
    # scripts/build_soccer_artifacts.py's _load_player_rows reads to run
    # SoccerSim's player-props pass (simulate_props). That function has no
    # error path at all for a missing file -- an empty players/ dir just
    # silently returns [], so simulate_props() ran "successfully" every
    # cycle producing real match-level sims (team ratings/history ARE
    # present) but zero player projections, with no error anywhere to catch.
    # Root cause: refresh_odds_sources.py's soccer steps resolve
    # --source-root to the RENDER PERSISTENT DISK
    # (_local_source_bundle_root -> SYNDICATE_DATA_ROOT/soccer_source), not
    # the git checkout -- and unlike web (syndicate/app.py's
    # _bootstrap_render_data, gated the same way), refresh-worker (a plain
    # script, no Flask app) never ran ANY bootstrap sync from git onto its
    # own disk. The committed players CSVs were real and correct the whole
    # time; refresh-worker's disk just never received them.
    seeded_leagues = _bootstrap_soccer_seed_files(relative_subdir="players", glob_pattern="players_*.csv")
    if seeded_leagues:
        print(f"[refresh_worker] SOCCER_PLAYER_SEED_BOOTSTRAPPED leagues={seeded_leagues}", flush=True)


def _bootstrap_soccer_schedule_seed_files() -> None:
    # #170 follow-up, root-caused 2026-08-01: soccer's per-league schedule
    # artifact (data/soccer_source/{league}/api/schedule/schedule_{season}.json
    # -- committed to git) is what syndicate/features/soccer/sources.py's
    # schedule_payload/available_weeks/default_week read to resolve "which
    # week is today" for the props/picks pipeline (build_props_page_context,
    # week-keyed not date-keyed). default_week() has an explicit fallback
    # (`if not weeks: return 1`) for exactly the missing-schedule case, but
    # week 1 is always in the past for an in-season league, so
    # week_date_list(league, season, 1) resolves to an empty date list --
    # every player-prop rank card silently comes back empty regardless of
    # how fresh or correct the underlying picks/recommendations data is.
    # Confirmed by direct local reproduction: build_props_page_context('mls',
    # None, None) produced 0 rank cards against a source root missing only
    # schedule_2026.json, and 36 real rank cards once it was added back --
    # everything else (player_props, picks.csv PROP rows) was already
    # correct. Same missing-bootstrap root cause as #145/#146, just for a
    # different file that per-cycle pull_hot_artifacts's date-scoped pattern
    # match can never reach either (schedule_2026.json has no date suffix).
    seeded_leagues = _bootstrap_soccer_seed_files(relative_subdir="api/schedule", glob_pattern="schedule_*.json")
    if seeded_leagues:
        print(f"[refresh_worker] SOCCER_SCHEDULE_SEED_BOOTSTRAPPED leagues={seeded_leagues}", flush=True)


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
    """Weekly sports this autorun still owns -- i.e. the ones NOT on the fast tick.

    The other half of the ownership partition described in
    live_refresh_loop.py's `_weekly_sport_claimed_by_fast_tick`. A sport with
    games in the horizon belongs to the fast odds tick (prices move all day and
    a 6-hourly capture left the NFL board 24 hours stale); a sport with no games
    stays here for schedule/artifact work.

    Dropping them here is what keeps the write race impossible. Both sides call
    the SAME predicate, so a sport is claimed by exactly one owner. If this ever
    stops mirroring the loop's exclusion, two refresh runs can target the same
    non-date-partitioned football artifacts again -- the reason the blanket
    split existed in the first place.
    """
    active = {item.strip().lower() for item in _active_sports_for_date(selected_date).split(",") if item.strip()}
    candidates = [sport for sport in ("nfl", "ncaaf", "ncaab") if sport in active]
    try:
        from syndicate.features.shared.live_refresh_loop import _weekly_sport_claimed_by_fast_tick

        candidates = [
            sport for sport in candidates if not _weekly_sport_claimed_by_fast_tick(sport, selected_date)
        ]
    except Exception:
        # Cannot resolve ownership -> YIELD, do not run them here.
        #
        # The two failure directions are not symmetric. The fast tick claims on
        # unknown, so yielding here means at worst nobody runs a weekly sport
        # for a cycle -- a stale board, which is visible and which
        # audit_slate_coverage.py (#264) is built to catch. Running them anyway
        # would mean BOTH owners writing the same non-date-partitioned football
        # artifact, which corrupts silently and is the exact race the blanket
        # split existed to prevent. Prefer the loud failure.
        return ""
    return ",".join(candidates)


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
            # #148: was "all" -- ran soccer_{league}_odds/props/schedule
            # (fetch_soccer_oddsapi_odds_local.py/fetch_soccer_oddsapi_props_local.py,
            # direct OddsAPI calls) from refresh-worker on top of
            # soccer_{league}_artifacts (the sim, the actual reason this
            # autorun belongs here). That's a second, independent OddsAPI
            # caller for soccer alongside live-odds-worker -- the same
            # violation class fixed for MLB in #139/#144, just for a
            # different sport. "live" keeps this autorun's real job (the sim
            # -- soccer_{league}_artifacts and _live_state both accept
            # phase="live" per their own phases tuples) while dropping the
            # pregame-only odds/props/schedule steps, which
            # _launch_autorun_soccer_pregame_refresh (run_live_odds_refresh_worker.py)
            # now owns instead, on live-odds-worker, independent of the
            # shared adaptive tick's global (cross-sport) phase.
            phase="live",
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
# yesterday's and today's Central-time dates PLUS every date that still has
# an unsettled prediction (pending_prediction_dates()) on every run: matching
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


def _mlb_actuals_writer_enabled() -> bool:
    raw_value = str(os.environ.get("RECONCILIATION_ENABLE_MLB_ACTUALS_WRITER") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _mlb_actuals_writer_interval_seconds() -> int:
    raw_value = str(os.environ.get("RECONCILIATION_MLB_ACTUALS_WRITER_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw_value or 3600)
    except ValueError:
        value = 3600
    return max(1, value)


def _mlb_actuals_writer_status_path() -> Path:
    return _refresh_state_store()["reports_root"]() / "refresh_status" / "latest" / "mlb_actuals_writer_status.json"


def _run_mlb_actuals_writer_tick() -> dict[str, Any] | None:
    # Gated and run independently of _launch_autorun_reconciliation below --
    # deliberately does NOT live inside that function's elif chain (see the
    # main loop), so a cycle that also claims a reconciliation-autorun turn
    # still gets a fresh actuals write first. Own env var/interval so it can
    # be toggled without touching the (already-working, per #96) reconciliation
    # autorun flag.
    if not _mlb_actuals_writer_enabled():
        return None
    status_path = _mlb_actuals_writer_status_path()
    last_status = _refresh_state_store()["read_json_file"](status_path) or {}
    last_epoch = float((last_status or {}).get("epoch") or 0.0)
    if last_epoch > 0.0 and (time.time() - last_epoch) < float(_mlb_actuals_writer_interval_seconds()):
        return None

    from scripts.build_mlb_actuals import write_mlb_actuals_for_date
    from syndicate.features.prediction_reconciliation import pending_prediction_dates

    today_date = central_today_iso()
    yesterday_date = (date.fromisoformat(today_date) - timedelta(days=1)).isoformat()
    try:
        stale_pending_dates = pending_prediction_dates()
    except Exception:
        stale_pending_dates = []
    target_dates = tuple(sorted({yesterday_date, today_date, *stale_pending_dates}))
    output_root = _refresh_state_store()["data_root"]()

    summaries: dict[str, Any] = {}
    error_text: str | None = None
    try:
        for target_date in target_dates:
            result = write_mlb_actuals_for_date(target_date, output_root=output_root)
            summaries[target_date] = result.get("summary")
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"

    status = {"epoch": time.time(), "dates": list(target_dates), "summaries": summaries, "error": error_text}
    _refresh_state_store()["write_json_file"](status_path, status)
    return status


def _mlb_betting_day_backfill_target_date() -> str | None:
    raw = str(os.environ.get("MLB_BETTING_DAY_BACKFILL_DATE") or "").strip()
    return raw or None


def _mlb_betting_day_backfill_status_path() -> Path:
    return _refresh_state_store()["reports_root"]() / "refresh_status" / "latest" / "mlb_betting_day_backfill_status.json"


def _run_mlb_betting_day_backfill_tick() -> dict[str, Any] | None:
    """One-off backfill (2026-08-04): re-runs
    vendor/mlb_bettingv2/tools/eval/build_season_betting_cards_manifest.py
    for a SINGLE named date, so a stale season_betting_day_{date}.json --
    written before df9df584's odds-path fix, when _odds_paths resolved
    against the code checkout instead of the mounted data disk and every
    day silently produced zero graded rows -- gets regenerated with the
    fix now in place. There is no automated daily trigger for this specific
    step on Render (see todo.md); this exists to backfill specific dates on
    demand without inventing a general-purpose remote-script-execution
    endpoint.

    Deliberately one-off, not interval-gated: fires once for the exact
    date named in MLB_BETTING_DAY_BACKFILL_DATE, writes a completion
    marker keyed to that date, and self-disables (returns None) on every
    later tick once that marker shows ok=True for the same date -- so the
    operator can leave the env var set without it silently repeating.
    Narrowly scoped by design: passes --date so the vendored script's own
    full_publish path (which touches the season-wide manifest/recap
    shared across every date) never engages; only this date's own card
    and day-payload files are written. --out/--recap-md are pointed at a
    scratch path for exactly that reason -- the script's own default
    would otherwise overwrite the real season-wide manifest with a
    single-day version.
    """
    target_date = _mlb_betting_day_backfill_target_date()
    if not target_date:
        return None
    status_path = _mlb_betting_day_backfill_status_path()
    last_status = _refresh_state_store()["read_json_file"](status_path) or {}
    if str(last_status.get("date") or "") == target_date and bool(last_status.get("ok")):
        return None

    try:
        season = int(target_date[:4])
    except ValueError:
        status = {"epoch": time.time(), "date": target_date, "ok": False, "error": f"could not parse a season from {target_date!r}"}
        _refresh_state_store()["write_json_file"](status_path, status)
        return status

    data_root = _refresh_state_store()["data_root"]()
    mlb_root = data_root / "mlb_source" / "source_artifacts" / "data"
    batch_dir = mlb_root / "eval" / "batches" / f"season_{season}_ui_daily_live"
    season_dir = mlb_root / "eval" / "seasons" / str(season)
    day_payload_dir = season_dir / "betting_day_payloads_retuned"
    cards_dir = season_dir / "locked_cards_retuned"
    scratch_dir = _refresh_state_store()["reports_root"]() / "refresh_status" / "latest"
    scratch_out = scratch_dir / f"mlb_betting_day_backfill_manifest_{target_date}.json"
    scratch_recap = scratch_dir / f"mlb_betting_day_backfill_recap_{target_date}.md"

    script_path = REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "eval" / "build_season_betting_cards_manifest.py"
    command = [
        sys.executable,
        str(script_path),
        "--season", str(season),
        "--batch-dir", str(batch_dir),
        "--date", target_date,
        "--day-payload-dir", str(day_payload_dir),
        "--cards-dir", str(cards_dir),
        "--profile-name", "retuned",
        "--out", str(scratch_out),
        "--recap-md", str(scratch_recap),
    ]
    started = time.time()
    try:
        scratch_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600)
        status = {
            "epoch": time.time(),
            "date": target_date,
            "ok": result.returncode == 0,
            "return_code": result.returncode,
            "elapsed_seconds": round(time.time() - started, 1),
            "stdout_tail": (result.stdout or "")[-4000:],
            "stderr_tail": (result.stderr or "")[-4000:],
            "command": [str(part) for part in command],
        }
    except Exception as exc:
        status = {
            "epoch": time.time(),
            "date": target_date,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "command": [str(part) for part in command],
        }
    _refresh_state_store()["write_json_file"](status_path, status)
    print(f"[refresh_worker] MLB_BETTING_DAY_BACKFILL_TICK date={target_date} ok={status.get('ok')}", flush=True)
    return status


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

    from syndicate.features.prediction_reconciliation import pending_prediction_dates
    from syndicate.features.prediction_reconciliation import reconcile_prediction_results_for_date

    today_date = central_today_iso()
    yesterday_date = (date.fromisoformat(today_date) - timedelta(days=1)).isoformat()
    # Always include yesterday/today (cheap, catches same-day settlement),
    # unioned with every date that still has an unsettled prediction --
    # reconcile_prediction_results_for_date is already a safe no-op for
    # anything already settled, so retrying a growing date list here costs
    # nothing extra once a date's predictions are actually resolved. Without
    # this union, any prediction dated outside yesterday/today (worker
    # downtime, the autorun flag not being live yet when it was logged, an
    # advance bet placed a few days ahead of the game) could never be
    # retried again, no matter how long the app kept running.
    try:
        stale_pending_dates = pending_prediction_dates()
    except Exception:
        stale_pending_dates = []
    target_dates = tuple(sorted({yesterday_date, today_date, *stale_pending_dates}))
    # reconcile_prediction_results_for_date's own default result_roots
    # ([repo_root]/data) is the EPHEMERAL code checkout, not the persistent
    # Render disk (data_root(), SYNDICATE_DATA_ROOT) result-file writers
    # (e.g. scripts/build_mlb_actuals.py) actually write to -- passing it
    # explicitly here is what lets the autorun path actually find them.
    # The CLI entrypoint (scripts/daily_update.ps1's GHA pipeline) keeps
    # using the function's own repo-relative default, unaffected by this.
    result_roots = [_refresh_state_store()["data_root"]()]
    # Emit the result files BEFORE reconciling. #214: reconciliation was never
    # broken, it was starved -- it globs for closing_lines_{date}.csv and found
    # nothing, so every prediction logged "no match found" and production sat at
    # settled_count 0 with avg_clv null. Emitting inside the same autorun keeps
    # the two in lockstep; a separate schedule would reintroduce the window
    # where reconciliation runs against files that do not exist yet.
    emit_summary: dict[str, Any] = {}
    try:
        from scripts.emit_settlement_inputs import emit_for_date

        for target_date in target_dates:
            emit_summary[target_date] = emit_for_date(target_date)
    except Exception as exc:  # noqa: BLE001
        # Never fatal: stale or missing result files degrade settlement, but a
        # failure here must not stop the reconciliation pass from retrying
        # whatever files already exist.
        emit_summary["error"] = f"{type(exc).__name__}: {exc}"
        print(f"[settlement_inputs] emit FAILED {emit_summary['error']}", flush=True)

    summaries: dict[str, Any] = {}
    error_text: str | None = None
    try:
        for target_date in target_dates:
            result = reconcile_prediction_results_for_date(target_date, result_roots=result_roots)
            summaries[target_date] = result.get("summary")
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"

    _refresh_state_store()["write_json_file"](
        status_path,
        {
            "epoch": time.time(),
            "dates": list(target_dates),
            "summaries": summaries,
            "settlement_inputs": emit_summary,
            "error": error_text,
        },
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
        detail=f"Auto-ran prediction reconciliation for {', '.join(target_dates)}.",
        ran_job=True,
        run_exit_code=0,
        latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
        refresh_cycle=refresh_cycle,
    )
    return True


# Evaluation-ledger settlement (syndicate.features.shared.evaluation_settlement)
# never runs on Render today -- the ledger's settle_result() had no caller at
# all until this autorun was added. Off by default so it can be verified
# against real production data (dry-run match rates) before being trusted to
# write on a schedule; mirrors the reconciliation autorun's shape above.
def _evaluation_settlement_auto_refresh_enabled() -> bool:
    raw_value = str(os.environ.get("EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _evaluation_settlement_interval_seconds() -> int:
    raw_value = str(os.environ.get("EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw_value or 86400)
    except ValueError:
        value = 86400
    return max(1, value)


def _evaluation_settlement_lookback_days() -> int:
    """How many days back the settlement autorun sweeps.

    Was hardcoded to (yesterday, today). That is only correct when grading
    has always worked: any date whose graded rows appear LATER than two days
    after the fact can never be settled, because the window has already moved
    past it. Confirmed live 2026-08-04 -- grading had produced zero rows for
    16 days, and when it was fixed, 14 dates (2026-07-20..2026-08-02) came
    back graded while the autorun was still only looking at 08-03/08-04. The
    ledger stayed 100% pending with matched=0 against rows that existed.

    Default 21 rather than 14: from 2026-08-04 a 14-day window still missed
    the two oldest graded dates (07-20, 07-21). 21 covers the whole observed
    backfill with margin.

    Re-sweeping settled dates is close to free: settle_ledger_for_date skips
    records that already have a non-pending result (already_resolved_records),
    so an old date costs one chunk read and no writes.
    """
    raw_value = str(os.environ.get("EVALUATION_SETTLEMENT_LOOKBACK_DAYS") or "").strip()
    try:
        value = int(raw_value or 21)
    except ValueError:
        value = 14
    # Bounded so a typo cannot turn every cycle into a full-season scan.
    return max(1, min(60, value))


def _evaluation_settlement_target_hour_central() -> int:
    """Central-time hour after which the daily settlement autorun is
    allowed to run.

    Reported live 2026-08-05: settlement had last run at 21:01 CT (an
    accident of when the interval-based gate last happened to fire), so the
    24h-interval default meant the NEXT run wasn't due until ~21:01 the
    following night -- hours after that morning's grading had already
    produced fresh rows for yesterday's slate. Interval-since-last-run has
    no concept of time of day, so "when it runs" was pure accident, not a
    schedule.

    Default 6 (6am Central): by then even a West-coast night game
    (finishing ~11pm-1am CT) plus its resim/reconcile has had hours of
    buffer, and settling before the board is used for the day means
    reliability multipliers / dynamic thresholds / policy promotion from
    yesterday's results can influence TODAY's recommendations, which is the
    entire point of the feedback loop existing.
    """
    raw_value = str(os.environ.get("EVALUATION_SETTLEMENT_TARGET_HOUR_CENTRAL") or "").strip()
    try:
        value = int(raw_value or 6)
    except ValueError:
        value = 6
    return max(0, min(23, value))


def _evaluation_settlement_should_run_now(*, now_epoch: float, last_epoch: float) -> bool:
    """Once per Central calendar day, at or after the target hour -- not a
    fixed interval since the last run.

    EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS, if explicitly set,
    overrides this entirely and restores the old interval-only gate -- kept
    for the diagnostic use this already had twice (forcing a fast cycle to
    confirm a fix), which the once-a-day gate below cannot do quickly.

    Self-catching-up by construction: if the worker was down at 6am and
    comes up at 9am having never run today, "different Central date than
    last run" is still true and it fires on the next tick, rather than
    waiting for tomorrow's window.
    """
    if str(os.environ.get("EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS") or "").strip():
        return last_epoch <= 0.0 or (now_epoch - last_epoch) >= float(_evaluation_settlement_interval_seconds())
    if last_epoch <= 0.0:
        return True
    last_central_date = central_datetime_from_epoch(last_epoch).date()
    now_central = central_datetime_from_epoch(now_epoch)
    if now_central.date() == last_central_date:
        # Already ran today (or the clock hasn't rolled to a new Central
        # date yet since the last run) -- wait for tomorrow's window.
        return False
    return now_central.hour >= _evaluation_settlement_target_hour_central()


def _evaluation_settlement_autorun_status_path() -> Path:
    return _refresh_state_store()["reports_root"]() / "refresh_status" / "latest" / "evaluation_settlement_autorun_status.json"


def _launch_autorun_evaluation_settlement(
    *,
    latest_manifest_path: Path,
    worker_status_path: Path,
    refresh_cycle: dict[str, int],
) -> bool:
    if not _evaluation_settlement_auto_refresh_enabled():
        return False

    status_path = _evaluation_settlement_autorun_status_path()
    last_status = _refresh_state_store()["read_json_file"](status_path) or {}
    last_epoch = float((last_status or {}).get("epoch") or 0.0)
    if not _evaluation_settlement_should_run_now(now_epoch=time.time(), last_epoch=last_epoch):
        return False

    # #256: CLAIM THE RUN BEFORE DOING THE WORK.
    #
    # This is the defect that turned an expensive pass into an eleven-hour
    # outage. The status file below was written only at the END, and
    # _evaluation_settlement_should_run_now is "self-catching-up by
    # construction" (its own docstring) -- so if the process died mid-run, the
    # epoch never advanced and the next boot ran it again. Measured on
    # refresh-worker 2026-08-07: 110 OOM kills over eleven hours at ~4 minute
    # intervals, which is one boot-to-kill cycle, repeating forever:
    #
    #     boot -> settlement fires (last run never completed)
    #          -> 21 date chunks read whole and accumulated (see below)
    #          -> OOM
    #          -> status never written
    #          -> boot -> settlement fires ...
    #
    # Every mitigation shipped that night missed it because they all guarded
    # the BOARD path: #249/#250's circuit breakers sit in _build_candidate_pool,
    # #251/#252 are board-build fixes, and #254 streamed seven readers in
    # intelligence_evaluation.py -- a file settlement does not call. The board
    # was already being refused correctly (candidate_count=0, MEMORY_GUARD_ABORT
    # at 3588MB); it was being refused on memory settlement had already spent.
    #
    # Claiming first makes a crash cost ONE run, not every run forever. The
    # trade is deliberate and it is the right way round: a genuine transient
    # failure now waits for the next window instead of retrying, and the
    # summary/error fields are still filled in by the final write below. An
    # autorun that cannot make progress is a bad day; an autorun that kills its
    # host and then retries is an outage.
    #
    # Deliberately NOT a short backoff-and-retry, which was the other proposal.
    # A backoff still retries, and if the run is fatal the result is the same
    # crash loop with a longer period -- slower, harder to spot, and it would
    # have taken far more than eleven hours to notice. "Claimed today, so not
    # again today" cannot loop by construction. The cost of being wrong is one
    # missed settlement day, which the loud log below makes visible.
    if str((last_status or {}).get("state") or "") == "started":
        # The previous run claimed and never finished -- i.e. the process died
        # inside it. This is the ONLY signal that the crash happened at all,
        # because a killed process writes no traceback and no completion.
        print(
            "[evaluation_settlement] PREVIOUS_RUN_NEVER_COMPLETED "
            f"claimed_epoch={last_epoch} -- the worker died inside settlement. "
            "Not retrying today (see #256); investigate before re-enabling.",
            flush=True,
        )
    _refresh_state_store()["write_json_file"](
        status_path,
        {
            "epoch": time.time(),
            "state": "started",
            "note": "#256: claimed before the work; the final write replaces this with results",
        },
    )

    from syndicate.features.shared.evaluation_settlement import settle_ledger_for_dates
    from syndicate.features.shared.graded_outcomes import GRADED_OUTCOME_GRADERS

    today_date = central_today_iso()
    lookback_days = _evaluation_settlement_lookback_days()
    # Oldest first, so a backfill settles in chronological order and the
    # status summary reads naturally.
    target_dates = tuple(
        (date.fromisoformat(today_date) - timedelta(days=offset)).isoformat()
        for offset in range(lookback_days - 1, -1, -1)
    )
    summaries: dict[str, Any] = {}
    error_text: str | None = None
    try:
        # Every sport with a registered grader (graded_outcomes.py), not the
        # old hardcoded ["mlb", "wnba"] -- that list predates Stage 1 of the
        # learning-loop plan, which is precisely what gave nba/nhl/nfl their
        # own graders. A sport whose grader is still a documented []-stub
        # (soccer/ncaab/ncaaf) costs one cheap no-op pass here and settles
        # for real the moment its grader lands, with no autorun change.
        result = settle_ledger_for_dates(list(target_dates), sports=sorted(GRADED_OUTCOME_GRADERS.keys()))
        summaries = result.get("totals") or {}
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"

    # #216: carry those outcomes across to the PORTFOLIO ledger. There are two
    # ledgers and /portfolio reads only data/prediction_ledger.json -- the
    # evaluation ledger settled just above is, in this repo's own words, "a
    # separate evaluation ledger the Portfolio page never reads". Both autoruns
    # were enabled and production still showed settled_count 0 on five tracked
    # bets, one of them a 4-leg parlay that reconciliation structurally cannot
    # settle because it has no single market to match on.
    #
    # Runs here rather than in the reconciliation autorun so it sees the records
    # settle_ledger_for_dates just wrote, instead of last cycle's.
    bridge_summary: dict[str, Any] = {}
    try:
        from syndicate.features.shared.evaluation_settlement import _read_ledger_records_for_date
        from syndicate.features.shared.intelligence_evaluation import DEFAULT_LEDGER_PATH
        from syndicate.features.shared.ledger_bridge import bridge_settled_results

        # #256: bridge ONE DATE AT A TIME.
        #
        # This accumulated every record from all 21 lookback dates into a single
        # list and held them simultaneously. Production ledger chunks measured
        # 367,229,260 and 480,112,146 bytes on 2026-08-07, and the reader
        # underneath (_read_chunk_records) has no size ceiling at all -- so this
        # loop was the single largest allocation on a 4GiB worker, and it ran
        # before anything else could be blamed for the floor.
        #
        # bridge_settled_results is per-record, so a date at a time is
        # equivalent: the only thing lost is a cross-date view it never took.
        # Peak is now one date instead of twenty-one.
        bridge_totals: dict[str, int] = {}
        bridged_dates = 0
        for target_date in target_dates:
            date_records = _read_ledger_records_for_date(DEFAULT_LEDGER_PATH, target_date) or []
            if not date_records:
                continue
            date_summary = bridge_settled_results(evaluation_records=date_records) or {}
            bridged_dates += 1
            for key, value in date_summary.items():
                if isinstance(value, (int, float)):
                    bridge_totals[key] = bridge_totals.get(key, 0) + int(value)
            del date_records
        bridge_summary = {**bridge_totals, "dates_bridged": bridged_dates}
        print(f"[ledger_bridge] {json.dumps(bridge_summary, default=str)[:400]}", flush=True)
    except Exception as exc:  # noqa: BLE001
        bridge_summary = {"error": f"{type(exc).__name__}: {exc}"}
        print(f"[ledger_bridge] FAILED {bridge_summary['error']}", flush=True)

    # Reported live 2026-08-05: total_recommendation_records dropped from a
    # real 194 (19:41Z) to 0 (15:17Z, ~19.5h later) across the SAME date
    # window, with no code change to the counting/reading path in between.
    # This status file is the ONLY cross-service visibility into
    # refresh-worker's local ledger disk -- the web service that serves
    # /api/ops/evaluation-settlement/status cannot see this filesystem at
    # all (refresh-worker runs no HTTP server), so a bare summary of "0"
    # cannot be told apart from "the chunk files are genuinely gone" without
    # this. Read directly, independent of settle_ledger_for_dates' own
    # counting, so a bug in ITS counting would not also hide from this.
    chunk_diagnostics: dict[str, Any] = {}
    try:
        from syndicate.features.shared.intelligence_evaluation import DEFAULT_LEDGER_PATH
        from syndicate.features.shared.intelligence_evaluation import _count_jsonl_records
        from syndicate.features.shared.intelligence_evaluation import _ledger_chunk_path

        # Reported live 2026-08-05: after fixing DEFAULT_LEDGER_PATH to use
        # reports_root() (ac068787), the chunk file this SAME process wrote
        # still resolved under /opt/render/project/src/... (the ephemeral
        # checkout) rather than /opt/render/project/data/... (the mounted
        # disk SYNDICATE_REPORTS_ROOT points at, confirmed set correctly via
        # the Render env-vars API). reports_root() was verified correct in
        # isolation with the same env var simulated locally. So something
        # about THIS process disagrees with that isolated test -- report
        # exactly what it sees, not what it should see.
        chunk_diagnostics["_env_as_seen_by_process"] = {
            "SYNDICATE_REPORTS_ROOT": os.environ.get("SYNDICATE_REPORTS_ROOT"),
            "SYNDICATE_STATE_ROOT": os.environ.get("SYNDICATE_STATE_ROOT"),
            "RENDER": os.environ.get("RENDER"),
        }
        chunk_diagnostics["_default_ledger_path_as_imported"] = str(DEFAULT_LEDGER_PATH)

        for chunk_date in target_dates:
            chunk_path = _ledger_chunk_path(DEFAULT_LEDGER_PATH, chunk_date)
            if not chunk_path.exists():
                chunk_diagnostics[chunk_date] = {"exists": False}
                continue
            try:
                stat = chunk_path.stat()
                # #256: streamed. This was
                #   sum(1 for line in chunk_path.read_text(...).splitlines() if line.strip())
                # inside a loop over all 21 lookback dates -- re-reading every
                # 367-480MB chunk whole, a second time, purely to report a line
                # count in a DIAGNOSTIC. Same defect #75 fixed in
                # odds_lifecycle and #254 fixed in intelligence_evaluation;
                # this is the third file it lived in.
                line_count = _count_jsonl_records(chunk_path)
            except Exception as exc:
                chunk_diagnostics[chunk_date] = {"exists": True, "error": f"{type(exc).__name__}: {exc}"}
                continue
            chunk_diagnostics[chunk_date] = {"exists": True, "size_bytes": stat.st_size, "line_count": line_count, "path": str(chunk_path)}
    except Exception as exc:
        chunk_diagnostics["_error"] = f"{type(exc).__name__}: {exc}"

    _refresh_state_store()["write_json_file"](
        status_path,
        {
            "epoch": time.time(),
            # #256: pairs with the "started" claim written before the work. A
            # status file left at "started" means the process died inside
            # settlement -- the only durable evidence of that, since a SIGKILL
            # writes no traceback.
            "state": "completed",
            "dates": list(target_dates),
            "summary": summaries,
            "error": error_text,
            "chunk_diagnostics": chunk_diagnostics,
            # The only cross-service visibility into whether the portfolio
            # ledger actually received these outcomes -- refresh-worker serves
            # no HTTP, so without this "the bridge ran and matched nothing" and
            # "the bridge never ran" look identical from the web service.
            "ledger_bridge": bridge_summary,
        },
    )

    if error_text:
        _write_worker_status(
            worker_status_path=worker_status_path,
            latest_manifest_path=latest_manifest_path,
            state="error",
            detail=f"Failed to auto-run evaluation-ledger settlement: {error_text}",
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
        detail=f"Auto-ran evaluation-ledger settlement for {', '.join(target_dates)}: {summaries}.",
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


_SEASON_PROJECTION_SPORTS: tuple[str, ...] = ("nfl", "ncaaf")


def _season_projection_auto_refresh_enabled() -> bool:
    raw_value = str(os.environ.get("SEASON_PROJECTION_ENABLE_REFRESH_WORKER_AUTORUN") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _season_projection_refresh_interval_seconds() -> int:
    raw_value = str(os.environ.get("SEASON_PROJECTION_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw_value or 86400)
    except ValueError:
        value = 86400
    return max(1, value)


def _season_projection_target_week(sport: str, season: int) -> int | None:
    if sport == "nfl":
        from syndicate.features.nfl.sources import nfl_target_week

        return nfl_target_week(season)
    if sport == "ncaaf":
        from syndicate.features.ncaaf.sources import ncaaf_target_week

        return ncaaf_target_week(season)
    return None


def _season_projection_artifact_path(sport: str, season: int, week: int) -> Path:
    # NFL and NCAAF's projection artifacts live at different depths under
    # their respective source roots (confirmed: data/nfl_source/
    # smartsim2_projections_*.csv vs data/ncaaf_source/data/
    # smartsim2_projections_*.csv) -- not a typo, each sport's own
    # generation script already writes to its own established location.
    data_root = _refresh_state_store()["data_root"]()
    if sport == "nfl":
        return data_root / "nfl_source" / f"smartsim2_projections_{season}_wk{week}.csv"
    return data_root / "ncaaf_source" / "data" / f"smartsim2_projections_{season}_wk{week}.csv"


def _season_projection_script_args(sport: str, season: int, week: int) -> list[str]:
    script_path = Path(__file__).resolve().parent / f"generate_smartsim2_{sport}_projections.py"
    return [sys.executable, str(script_path), "--season", str(season), "--week", str(week)]


_SEASON_PROJECTION_MAX_RUNTIME_SECONDS = 45 * 60


def _season_projection_launch_state_path(sport: str) -> Path:
    return _refresh_state_store()["reports_root"]() / "refresh_status" / "latest" / f"season_projection_launch_{sport}.json"


def _season_projection_process_still_running(sport: str) -> bool:
    # Confirmed live 2026-08-02: this autorun had no "already running" guard
    # at all -- unlike every sibling autorun here (MLB's daily sim, the
    # weekly/soccer/reconciliation/evaluation launchers), which all check a
    # persisted PID before launching. The staleness check just above (an
    # artifact-age check) can't substitute for one: the artifact's mtime
    # doesn't move until the subprocess finishes writing it, so every tick
    # while a run is still in progress sees the SAME "stale" artifact and
    # launches ANOTHER instance. Confirmed via
    # /api/ops/intelligence/memory-diagnostics on refresh-worker: 18 ->
    # 56+ concurrent generate_smartsim2_nfl_projections.py processes
    # (all still `running`) piling up over ~2 hours, driving container
    # memory from 31.6% to 53.8% of the 4GB limit and starving the actively
    # running MLB Sunday-slate sim of CPU on the same container.
    from syndicate.features.shared.live_refresh_loop import _process_exists

    store = _refresh_state_store()
    payload = store["read_json_file"](_season_projection_launch_state_path(sport))
    if not isinstance(payload, dict):
        return False
    pid = payload.get("pid")
    if not _process_exists(pid):
        return False
    started_at_epoch = float(payload.get("started_at_epoch") or 0.0)
    if started_at_epoch > 0.0 and (time.time() - started_at_epoch) > _SEASON_PROJECTION_MAX_RUNTIME_SECONDS:
        # Hung well past a generous ceiling for a single week's Monte Carlo
        # projection run -- don't let a stuck process block this sport's
        # autorun forever. Best-effort: a failed kill just means the next
        # check tries again: it never blocks re-evaluating this gate.
        try:
            os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass
        print(f"[refresh_worker] SEASON_PROJECTION_TIMEOUT sport={sport} pid={pid}", flush=True)
        return False
    return True


def _record_season_projection_launch(sport: str, pid: int) -> None:
    _refresh_state_store()["write_json_file"](
        _season_projection_launch_state_path(sport),
        {
            "sport": sport,
            "pid": int(pid),
            "started_at_epoch": time.time(),
            "started_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        },
    )


def _launch_autorun_season_projections(
    *,
    latest_manifest_path: Path,
    worker_status_path: Path,
    refresh_cycle: dict[str, int],
) -> bool:
    """Real per-week Monte Carlo projection generation for NFL/NCAAF --
    added this session, mirrors the shape of every other autorun here
    exactly (env-gated off by default, staleness via _file_age_seconds,
    same as MLB's autorun above). Unlike the odds-pipeline autoruns, this
    calls the generation scripts directly via subprocess (launch_refresh_run
    is specifically the odds-refresh orchestrator's own dispatcher, not a
    generic script launcher -- confirmed by reading it before reusing it
    would have been wrong here). Claims and launches at most one sport per
    tick, same "one job per invocation" spirit as every sibling autorun --
    the next tick picks up whichever sport is still stale."""
    if not _season_projection_auto_refresh_enabled():
        return False
    selected_date = central_today_iso()
    active = {item.strip().lower() for item in _active_sports_for_date(selected_date).split(",") if item.strip()}
    season = date.today().year  # calendar-year=season for both nfl/ncaaf, confirmed by this session's own real 2026 runs

    for sport in _SEASON_PROJECTION_SPORTS:
        if sport not in active:
            continue
        if _season_projection_process_still_running(sport):
            continue
        week = _season_projection_target_week(sport, season)
        if week is None:
            continue
        artifact_path = _season_projection_artifact_path(sport, season, week)
        age_seconds = _file_age_seconds(artifact_path)
        if age_seconds is not None and age_seconds < float(_season_projection_refresh_interval_seconds()):
            continue

        try:
            process = subprocess.Popen(_season_projection_script_args(sport, season, week))
        except Exception as exc:
            _write_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                state="error",
                detail=f"Failed to auto-launch {sport} season-projection refresh (season={season} week={week}): {type(exc).__name__}: {exc}",
                ran_job=False,
                latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
                refresh_cycle=refresh_cycle,
            )
            continue

        _record_season_projection_launch(sport, int(getattr(process, "pid", 0) or 0))
        refresh_cycle["claimed_count"] = int(refresh_cycle.get("claimed_count") or 0) + 1
        _write_worker_status(
            worker_status_path=worker_status_path,
            latest_manifest_path=latest_manifest_path,
            state="launched",
            detail=f"Auto-launched {sport} season-projection refresh (season={season} week={week}) because the artifact was stale/missing.",
            ran_job=True,
            run_exit_code=None,
            latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
            launch_pid=int(getattr(process, "pid", 0) or 0) or None,
            refresh_cycle=refresh_cycle,
        )
        return True

    return False


# ---------------------------------------------------------------------------
# NFL preseason autorun -- a separate, parallel job from
# _launch_autorun_season_projections above. Deliberately its own function
# rather than a third entry in _SEASON_PROJECTION_SPORTS: preseason has its
# own week domain (1-4, real-schedule-driven via preseason_target_week()),
# its own artifact filename prefix (smartsim2_preseason_projections_*), and
# its own generation script (generate_smartsim2_nfl_preseason_projections.py)
# -- interleaving it into the regular-season sport loop would risk the same
# "unsafe to interleave preseason into the regular-season domain" mistake
# that preseason_projection.py's own docstring already warns about.
# Env-gated independently (SEASON_PROJECTION_ENABLE_REFRESH_WORKER_
# PRESEASON_AUTORUN, default OFF) so turning on the regular-season autorun
# does not silently also start firing preseason runs, and uses its own
# "nfl_preseason" sport key throughout (a distinct PID-guard status file
# from the regular-season "nfl" key) so the two autoruns never block each
# other or race on the same launch-state file.
# ---------------------------------------------------------------------------

_PRESEASON_PROJECTION_SPORT_KEY = "nfl_preseason"


def _season_projection_preseason_auto_refresh_enabled() -> bool:
    raw_value = str(os.environ.get("SEASON_PROJECTION_ENABLE_REFRESH_WORKER_PRESEASON_AUTORUN") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _preseason_projection_target_week(season: int) -> int | None:
    from syndicate.features.nfl.sources import preseason_target_week

    return preseason_target_week(season)


def _preseason_projection_artifact_path(season: int, week: int) -> Path:
    data_root = _refresh_state_store()["data_root"]()
    return data_root / "nfl_source" / f"smartsim2_preseason_projections_{season}_wk{week}.csv"


def _preseason_projection_script_args(season: int, week: int) -> list[str]:
    script_path = Path(__file__).resolve().parent / "generate_smartsim2_nfl_preseason_projections.py"
    return [sys.executable, str(script_path), "--season", str(season), "--week", str(week)]


def _launch_autorun_preseason_projections(
    *,
    latest_manifest_path: Path,
    worker_status_path: Path,
    refresh_cycle: dict[str, int],
) -> bool:
    """NFL preseason's own Monte Carlo projection autorun -- mirrors
    _launch_autorun_season_projections's shape (env-gated off by default,
    staleness via _file_age_seconds, an "already running" PID guard via the
    same _season_projection_process_still_running/_record_season_projection_launch
    helpers keyed on _PRESEASON_PROJECTION_SPORT_KEY, direct subprocess.Popen
    dispatch) but scoped to the real preseason schedule/week domain and
    artifact instead of the regular-season one."""
    if not _season_projection_preseason_auto_refresh_enabled():
        return False
    selected_date = central_today_iso()
    active = {item.strip().lower() for item in _active_sports_for_date(selected_date).split(",") if item.strip()}
    if "nfl" not in active:
        return False
    if _season_projection_process_still_running(_PRESEASON_PROJECTION_SPORT_KEY):
        return False

    season = date.today().year  # calendar-year=season, same convention as the regular-season autorun
    week = _preseason_projection_target_week(season)
    if week is None:
        return False

    artifact_path = _preseason_projection_artifact_path(season, week)
    age_seconds = _file_age_seconds(artifact_path)
    if age_seconds is not None and age_seconds < float(_season_projection_refresh_interval_seconds()):
        return False

    try:
        process = subprocess.Popen(_preseason_projection_script_args(season, week))
    except Exception as exc:
        _write_worker_status(
            worker_status_path=worker_status_path,
            latest_manifest_path=latest_manifest_path,
            state="error",
            detail=f"Failed to auto-launch nfl preseason season-projection refresh (season={season} week={week}): {type(exc).__name__}: {exc}",
            ran_job=False,
            latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
            refresh_cycle=refresh_cycle,
        )
        return False

    _record_season_projection_launch(_PRESEASON_PROJECTION_SPORT_KEY, int(getattr(process, "pid", 0) or 0))
    refresh_cycle["claimed_count"] = int(refresh_cycle.get("claimed_count") or 0) + 1
    _write_worker_status(
        worker_status_path=worker_status_path,
        latest_manifest_path=latest_manifest_path,
        state="launched",
        detail=f"Auto-launched nfl preseason season-projection refresh (season={season} week={week}) because the artifact was stale/missing.",
        ran_job=True,
        run_exit_code=None,
        latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
        launch_pid=int(getattr(process, "pid", 0) or 0) or None,
        refresh_cycle=refresh_cycle,
    )
    return True


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
    _bootstrap_soccer_player_seed_files()
    _bootstrap_soccer_schedule_seed_files()
    if str(os.environ.get("SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP") or "").strip().lower() in {"1", "true", "yes", "on"}:
        print("[refresh_worker] INTELLIGENCE_LOOP_ENABLED calling start_intelligence_state_background_loop()", flush=True)
        loop_started = start_intelligence_state_background_loop()
        print(f"[refresh_worker] INTELLIGENCE_LOOP_START_RESULT started={loop_started}", flush=True)
    else:
        print("[refresh_worker] INTELLIGENCE_LOOP_DISABLED", flush=True)

    # LIVE-LENS LOOP, MOVED HERE FROM live-odds-worker.
    #
    # Its heavy piece is MLB's vendored 120-sim-per-live-game Monte Carlo, run
    # in-process with no batching. MEASURED 2026-08-08 with 13 MLB games live:
    #
    #     03:29:43   295.5MB   live_lens_tick_before_mlb
    #     03:30:02  1740.8MB   live_lens_tick_after_build_mlb   <- +1,445MB
    #                          killed 4 seconds later
    #
    # live-odds-worker is 2Gi with a ~700-900MB steady-state baseline, so a
    # 1.4GB build cannot fit there at ANY gate threshold -- and the cost scales
    # with the live slate, so it is worst exactly when the board matters most.
    # #124 already had to LOWER MLB's headroom gate because the correct value
    # (1800MB) was unsatisfiable on a 2Gi container; that was the squeeze
    # showing, and it was read as a gate-tuning problem.
    #
    # This is the same move made for the MLB SIM tick on 2026-07-20
    # (_mlb_sim_tick_owner_here), stopped one step short: the 4Gi service owns
    # the simulations, while the 2Gi service was left running a
    # ~1,560-simulation Monte Carlo.
    #
    # Ownership is the EXISTING env gate, not a new one -- SYNDICATE_ENABLE_
    # LIVE_LENS_LOOP already defaults False and start_live_lens_loop() returns
    # False when unset. Both services calling this is therefore safe by
    # construction: whichever has the flag runs it, and the flag must be
    # removed from live-odds-worker in the same change or BOTH will run it.
    try:
        _diag_log_all_process_memory("start_live_lens_loop_before")
        from syndicate.features.shared.live_lens_loop import start_live_lens_loop

        live_lens_started = start_live_lens_loop()
        print(f"[refresh_worker] LIVE_LENS_LOOP_START_RESULT started={live_lens_started}", flush=True)
        _diag_log_all_process_memory("start_live_lens_loop_after")
    except Exception as exc:
        print(f"[refresh_worker] LIVE_LENS_LOOP_START_FAILED {type(exc).__name__}: {exc}", flush=True)

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

        # Unconditional (not part of the claimed_count/elif chain below) so a
        # cycle that also claims a reconciliation-autorun turn still gets a
        # freshly-written actuals file first -- see _run_mlb_actuals_writer_tick.
        try:
            mlb_actuals_meta = _run_mlb_actuals_writer_tick()
            if mlb_actuals_meta:
                print(f"[refresh_worker] MLB_ACTUALS_TICK {json.dumps(mlb_actuals_meta, sort_keys=True, default=str)}", flush=True)
        except Exception as exc:
            print(f"[refresh_worker] MLB_ACTUALS_TICK_ERROR {type(exc).__name__}: {exc}", flush=True)

        # Unconditional, same reasoning as the actuals-writer tick above --
        # a one-off, self-disabling backfill (see
        # _run_mlb_betting_day_backfill_tick's own docstring) has no reason
        # to wait on the claimed_count/elif chain below.
        try:
            mlb_betting_day_backfill_meta = _run_mlb_betting_day_backfill_tick()
            if mlb_betting_day_backfill_meta:
                print(f"[refresh_worker] MLB_BETTING_DAY_BACKFILL {json.dumps(mlb_betting_day_backfill_meta, sort_keys=True, default=str)}", flush=True)
        except Exception as exc:
            print(f"[refresh_worker] MLB_BETTING_DAY_BACKFILL_ERROR {type(exc).__name__}: {exc}", flush=True)

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
        elif _launch_autorun_evaluation_settlement(
            latest_manifest_path=latest_manifest_path,
            worker_status_path=worker_status_path,
            refresh_cycle=refresh_cycle,
        ):
            if args.run_once:
                return 0
        elif _launch_autorun_season_projections(
            latest_manifest_path=latest_manifest_path,
            worker_status_path=worker_status_path,
            refresh_cycle=refresh_cycle,
        ):
            if args.run_once:
                return 0
        elif _launch_autorun_preseason_projections(
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