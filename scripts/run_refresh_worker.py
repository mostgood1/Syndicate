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
from typing import Any, Mapping

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


def _bootstrap_soccer_history_seed_files() -> None:
    # Third of the same family as #145 (players) and #170 (schedule), and the
    # one that was actually stopping every non-MLS sim from producing anything.
    #
    # `build_soccer_artifacts.py`'s `_load_team_ratings` reads per-league match
    # history from its `--source-root`, which on the worker is the RUNTIME disk.
    # The history CSVs are committed to git for all nine non-MLS leagues and
    # nothing ever copied them across, so the sim raised
    #
    #   "no match history under <root>/<league>/history;
    #    run fetch_soccer_history_local.py --kind matches first"
    #
    # and exited in TWO SECONDS, before writing any artifact. Reproduced
    # directly against an empty source root, 2026-08-08.
    #
    # MLS is legitimately absent here and must stay absent: it has no
    # `history/` directory in git because it sources team history from ASA
    # (`fetch_asa_mls_team_history`) instead. That is exactly why MLS was the
    # ONE league still producing recommendations while the other nine went
    # silent -- the split that made this look like a per-league data problem
    # for two sessions.
    #
    # Note this is the SECOND stage of the same failure: `c9fbb736` fixed the
    # schedule read (which had pinned every league to `--week 1`), and the run
    # then got one step further and died here instead. Both had to be fixed;
    # neither alone produces a sim.
    # BOTH ratings inputs, because `_load_team_ratings` has TWO disk branches and
    # seeding one of them is what left this half-fixed for a further session
    # (`#361`):
    #
    #   mls                                    live ASA fetch, nothing on disk
    #   eredivisie/primeira/championship/       <league>/history/matches_*.csv
    #     belgian_pro_league                      -- seeded since the comment above
    #   epl/la_liga/bundesliga/serie_a/ligue_1  <league>/team_history/teams_*.csv
    #                                             -- NOT seeded until now
    #
    # Both raise `SystemExit` on an empty glob, so both exit ~10s before writing
    # anything. Measured 2026-08-11: after the `history` seeding landed, the four
    # goals-based leagues began writing and la_liga did not -- 44 launches, 0
    # writes -- and the split read as a per-league data problem rather than as a
    # per-BRANCH one for most of a session.
    #
    # This is latent for four more leagues, not just a la_liga fix. epl,
    # bundesliga, serie_a and ligue_1 take the same Understat branch and open on
    # 08-21/08-22/08-28, so they sit outside the 7-day sim horizon today and would
    # each have failed identically on entering it.
    seeded_leagues = _bootstrap_soccer_seed_files(relative_subdir="history", glob_pattern="*.csv")
    if seeded_leagues:
        print(f"[refresh_worker] SOCCER_HISTORY_SEED_BOOTSTRAPPED leagues={seeded_leagues}", flush=True)
    seeded_team_history = _bootstrap_soccer_seed_files(relative_subdir="team_history", glob_pattern="teams_*.csv")
    if seeded_team_history:
        print(
            f"[refresh_worker] SOCCER_TEAM_HISTORY_SEED_BOOTSTRAPPED leagues={seeded_team_history}",
            flush=True,
        )


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


# PER-LEAGUE-DATE UNITS (#282), user-directed.
#
# THE PROBLEM THIS BOUNDS. `_has_pending_external_contract` re-claims a
# manifest that is `running` + `queue_state: queued` + no live pid, on every
# poll tick, and NOTHING in that path bounds how many claims run concurrently.
# So when a manifest wedges, the steady-state overlap is
#
#     concurrent jobs ~= job_duration / poll_interval
#
# On 2026-08-08 that arithmetic OOM-killed refresh-worker nine times in 82
# minutes (process count 13 -> 79). Shrinking the JOB shrinks both terms of the
# damage: fewer overlapping jobs, and each one holding a fraction of the work.
#
# MEASURED IN PRODUCTION, 2026-08-09, off refresh-worker's own
# ALL_PROCESS_MEMORY per-process lists (STEP_END never reaches the log
# collector -- run_refresh_odds_job.py pipes the orchestrator's stdout/stderr
# to files). Eight consecutive whole-sport jobs:
#
#     job start   eredivisie  primeira_liga  belgian_pro_league   whole job
#     01:55Z         596s          315s            340s            1391s
#     04:45Z         332s          322s            363s            1154s
#     05:55Z         179s          251s            187s             660s
#     08:04Z         182s          168s            209s             603s
#     09:03Z         146s          211s            216s             616s
#     09:56Z         155s          203s            234s             628s
#     13:56Z         147s          191s            228s             606s
#     17:56Z         311s          431s            390s            1213s
#
# The other seven in-season leagues exit in ~0s -- 16c26e5f's horizon bound
# means they have nothing inside today+1 to simulate.
#
# SO THE HONEST RATIO IS ~2.8x, NOT THE ~6x THE ORIGINAL ESTIMATE ASSUMED, and
# the reason is worth keeping: concurrency after the split is set by the
# LONGEST SINGLE UNIT, not the average one. Three leagues do essentially all
# the work, so splitting ten ways buys 616/216 ~= 2.9x on the median job and
# 1213/431 ~= 2.8x on the worst observed one -- not 10x, and not the 6x that
# an equal-league-dates model predicts. Still a real reduction: at a 30s poll
# interval a wedged claim goes from ~20 concurrent jobs to ~7, each holding one
# league instead of ten.
def _soccer_refresh_units(selected_date: str) -> tuple[list[dict[str, str]], str]:
    """Every (league, date) the soccer sim should cover, and how we got it.

    Returns (units, scope_kind). `scope_kind` is part of the contract, not
    debug colour: it says which of three different things an empty or small
    unit list MEANS, and those must never render identically.

      league_date  -- the schedule resolved; one unit per in-horizon date
      league_only  -- the schedule did NOT resolve for some league, so that
                      league falls back to its own horizon-bounded matchweek
                      (still one league per job, just possibly >1 date)
    """
    from syndicate.features.soccer.sources import active_leagues_for_date
    from syndicate.features.soccer.sources import default_season
    from syndicate.features.soccer.sources import default_week
    from syndicate.features.soccer.sources import week_dates_within_horizon

    horizon_raw = str(os.environ.get("SYNDICATE_SOCCER_SIM_HORIZON_DAYS") or "").strip()
    try:
        horizon_days = max(0, int(horizon_raw)) if horizon_raw else 1
    except ValueError:
        horizon_days = 1

    units: list[dict[str, str]] = []
    scope_kind = "league_date"
    for league in active_leagues_for_date(selected_date):
        try:
            season = default_season(league)
            week = default_week(league, season, reference_date=selected_date)
            dates = week_dates_within_horizon(
                league,
                season,
                week,
                reference_date=selected_date,
                horizon_days=horizon_days,
            )
        except Exception as exc:
            # Degrade to league-only scope rather than dropping the league.
            # Dropping it would be a silent zero, and the whole point of this
            # change is that a soccer league producing nothing must say why.
            print(
                f"[refresh_worker] SOCCER_UNIT_RESOLVE_FAILED league={league} date={selected_date} "
                f"error={type(exc).__name__}: {exc} fallback=league_only",
                flush=True,
            )
            units.append({"league": league, "date": ""})
            scope_kind = "league_only"
            continue
        if not dates:
            # Legitimately nothing inside the horizon for this league. Not a
            # unit, and not a failure -- but it must be distinguishable from
            # the exception branch above, which is why they log differently.
            continue
        for date_text in dates:
            units.append({"league": league, "date": str(date_text)})
    return units, scope_kind


def _soccer_unit_key(unit: dict[str, str]) -> str:
    return f"{unit.get('league') or ''}|{unit.get('date') or ''}"


def _soccer_unit_last_touched(
    key: str,
    unit_epochs: Mapping[str, Any] | None,
    last_attempts: Mapping[str, Any] | None,
) -> float:
    """When this unit last consumed a slot -- by succeeding OR by trying.

    The soccer autorun picks `due[0]` after sorting on this, so it decides which
    league runs. `#356`: it used to sort on the success epoch alone, which starves
    the queue the moment a unit can launch but not write -- that unit's success
    epoch never advances, so it is permanently the stalest and wins every round.

    `max()` and not `min()`, and not the attempt epoch alone:

      - a unit that just attempted goes to the BACK, so a broken league costs one
        slot per backoff instead of every slot;
      - a unit that has not attempted recently has an attempt epoch older than its
        success epoch, so `max()` collapses to the success epoch and genuine
        stalest-first ordering is preserved for every healthy unit;
      - a never-seen unit scores 0.0 and sorts first, which is what a cold start
        should do.
    """
    return max(
        _coerce_epoch((unit_epochs or {}).get(key)),
        _coerce_epoch((last_attempts or {}).get(key)),
    )


def _coerce_epoch(value: Any) -> float:
    # State comes back through the keyvalue store as JSON, so a stamp can arrive
    # as a string or as null. A raw float() would raise on either and take the
    # whole autorun down rather than treating an unreadable stamp as "never".
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


# Last skip reason printed, so steady state does not reprint every 30s tick.
_SOCCER_SKIP_REASON_LAST: dict[str, str] = {}


def _soccer_autorun_skipped(reason: str, detail: str) -> bool:
    """Say why the soccer autorun declined, exactly once per reason change.

    WHY THIS EXISTS. The first #282 deploy produced no `SOCCER_UNIT_LAUNCHED`
    and no `SOCCER_UNITS_EMPTY` for 15 minutes, and from outside the container
    there was no way to tell which of three gates had stopped it -- spacing,
    an active job, or nothing due. All three returned a bare `False`.

    That is the same defect this item was written to fix, in my own code: I made
    the empty-unit zero attributable and left the three that actually fire in
    steady state silent. A gate that declines without saying so is
    indistinguishable from a gate that is broken.

    Printed on CHANGE rather than every tick: at a 30s poll a per-tick line
    would be ~2900 lines a day saying nothing new, on a service whose log and
    write volume is already load-bearing. A transition is the informative event;
    the steady state is not.
    """
    # Dedup on the REASON only. `detail` carries counters that tick every cycle
    # (`since_last_launch_s`, `next_due_in_s`), so keying on reason+detail would
    # differ every time and print every time -- the exact spam this is avoiding.
    if _SOCCER_SKIP_REASON_LAST.get("reason") != reason:
        _SOCCER_SKIP_REASON_LAST["reason"] = reason
        print(f"[refresh_worker] SOCCER_AUTORUN_SKIPPED reason={reason} {detail}", flush=True)
    return False


def _soccer_unit_launch_spacing_seconds(unit_count: int) -> int:
    """How long to wait between two per-league launches.

    Default spreads one full pass over the same interval the whole-sport job
    used, so each league's own refresh PERIOD is unchanged -- this trades a
    single ~10-20 minute burst every 4h for ~10 short jobs spread across the
    same 4h, which is the entire point. Without it, the first tick after a
    deploy would find every unit stale and fire them back-to-back on
    consecutive 30s ticks, recreating by design the overlap this exists to
    prevent.
    """
    raw = str(os.environ.get("SYNDICATE_SOCCER_LEAGUE_LAUNCH_SPACING_SECONDS") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    interval = _soccer_weekly_refresh_interval_seconds()
    return max(60, interval // max(1, int(unit_count)))


def _soccer_unit_wrote_since(unit_key: str, launched_epoch: float) -> tuple[bool | None, str, float]:
    """Did this unit's recommendations file land AFTER its launch? (`#353`)

    Returns (wrote, path, mtime). `wrote is None` means unknowable -- an
    unparseable key or an IO error -- and callers must treat that as "do not
    conclude", never as failure. Marking a unit failed because we could not
    look would retry it forever.

    One definition of "wrote", shared by the diagnostic and the scheduler, so
    the line an operator reads and the decision the worker makes can never
    disagree.
    """
    key = str(unit_key or "").strip()
    league, sep, unit_date = key.partition("|")
    if not sep or not league or not unit_date or launched_epoch <= 0.0:
        return None, "", 0.0
    try:
        from syndicate.features.shared.refresh_state_store import data_root

        rec_path = (
            data_root() / "soccer_source" / league / "api" / "recommendations"
            / f"recommendations_{unit_date}.json"
        )
        if not rec_path.is_file():
            return False, str(rec_path), 0.0
        mtime = rec_path.stat().st_mtime
    except Exception:
        return None, "", 0.0
    # 5s slack for clock skew between the launch stamp and the file write.
    return bool(mtime >= launched_epoch - 5.0), str(rec_path), mtime


# Diagnostics that fire on EVERY run, success or failure, and are written LAST.
# A plain tail therefore shows only these. Measured 2026-08-11: the first real
# `SOCCER_RUN_FAILED` (run_stamp=20260811_213249, exit 1 in 10s) reported three
# MAIN_THREAD_STACK/MAIN_RETURN frames and not one word about the cause -- the
# instrumentation worked and still could not answer the question it was built for.
_STDERR_NOISE_SUBSTRINGS = (
    "ALL_PROCESS_MEMORY",
    "PROCESS_TREE_MEMORY",
    "PROCESS_ENUM_DEBUG",
    "CONTAINER_MEMORY",
    "MAIN_THREAD_STACK",
    "MAIN_RETURN",
)
_STDERR_NOISE_PREFIXES = (
    "[refresh_odds_sources] THREADS",
    "[refresh_odds_sources] RUNTIME_SNAPSHOT",
    "[refresh_odds_sources] CHILD_PROCESSES",
)
# Lines that actually explain an exit. `_load_team_ratings` and `_load_player_rows`
# both `raise SystemExit(f"no ... under {dir}")`, which names the exact directory
# that was empty -- the single most useful line in the file, and the one a tail
# was dropping.
_STDERR_CAUSAL_SUBSTRINGS = (
    "Traceback",
    "SystemExit",
    "Error",
    "error=",
    "STEP_FAIL",
    "MISSING",
    "no team history under",
    "no match history under",
    "no dates found for",
    "no fixtures",
)


def _is_stderr_noise(line: str) -> bool:
    if any(marker in line for marker in _STDERR_NOISE_SUBSTRINGS):
        return True
    return line.startswith(_STDERR_NOISE_PREFIXES)


def _stderr_failure_tail(
    text: str, *, limit: int = 15, max_chars: int = 2400, head_may_be_partial: bool = False
) -> str:
    """The lines that explain the exit, not merely the last lines written.

    A blocklist alone is whack-a-mole: every new heartbeat marker refills the
    window and pushes the cause back out, and the next person only finds out
    during an incident. So causal lines are pulled in FIRST regardless of how
    far back they sit, and the remaining slots are filled from the tail.

    Output stays in file order, because a stack trace read bottom-up is worse
    than useless when the point is to hand someone a cause at a glance.
    """
    if head_may_be_partial:
        # The caller slices the file by CHARACTERS, so the first line is a
        # fragment whose leading marker was cut away -- and the noise test keys
        # on that marker, so an orphaned heartbeat tail reads as signal and gets
        # emitted as the cause. Measured on the worker its heartbeat lines are
        # 800-2,572 chars (15+ per 40KB window), so this drops at most one line;
        # measured on a dev box with 300 processes a SINGLE such line exceeded
        # the whole window and the emitted "tail" was pure garbage.
        text = text.split("\n", 1)[1] if "\n" in text else ""
    lines = [line.strip() for line in text.splitlines() if line.strip() and not _is_stderr_noise(line.strip())]
    if not lines:
        return ""
    position = {}
    for index, line in enumerate(lines):
        position.setdefault(line, index)
    causal = [line for line in lines if any(marker in line for marker in _STDERR_CAUSAL_SUBSTRINGS)]
    picked: list[str] = []
    for line in causal[-6:]:
        if line not in picked:
            picked.append(line)
    for line in reversed(lines):
        if len(picked) >= limit:
            break
        if line not in picked:
            picked.append(line)
    picked.sort(key=lambda line: position.get(line, 0))
    return " | ".join(picked)[:max_chars]


def _report_soccer_unit_failure(latest_manifest_path: Path) -> None:
    """Say WHY the last soccer run failed, in the worker's own log (`#357`).

    THE FAILURE WAS NEVER HIDDEN -- IT WAS WRITTEN DOWN AND NOTHING READ IT.
    Every soccer run on 2026-08-11 recorded `exitCode: 1` with a 9-14s runtime in
    the shared manifest, while the board showed ten leagues fully simulated off
    git artifacts stamped 2026-07-20. Three instruments were each blind in a
    different way: the launcher is fire-and-forget, `SOCCER_UNIT_OUTCOME` reports
    only that the file is absent, and `stderr_preview` is computed READ-SIDE
    against a path on the other service's disk -- so on web it is `""` always,
    which is not "no error" but "wrong disk".

    The asymmetry this exploits: **the worker CAN read its own stderr file.** The
    bytes were on local disk the whole time; only the reader was on the wrong
    service. So the tail goes to stdout, which Render's collector does receive.

    Deliberately reports FAILURES only, and only the tail. A per-tick dump of a
    healthy run would be the log spam `_soccer_autorun_skipped` already avoids.
    """
    try:
        manifest = _refresh_state_store()["read_json_file"](latest_manifest_path) or {}
    except Exception:
        return
    if str(manifest.get("oddsSports") or "").strip().lower() != "soccer":
        return
    exit_code = manifest.get("exitCode")
    if exit_code in (None, 0):
        return
    run_stamp = str(manifest.get("runStamp") or "")
    stderr_path = str(((manifest.get("externalRunner") or {}).get("stderrPath")) or "")
    tail = ""
    if stderr_path:
        try:
            raw = Path(stderr_path).read_text(encoding="utf-8", errors="replace")
            tail = _stderr_failure_tail(raw[-40000:], head_may_be_partial=len(raw) > 40000)
        except Exception as exc:  # noqa: BLE001
            tail = f"<unreadable: {type(exc).__name__}: {exc}>"
    print(
        f"[refresh_worker] SOCCER_RUN_FAILED exit_code={exit_code} run_stamp={run_stamp} "
        f"stderr_path={stderr_path or '<none>'} tail={tail or '<empty>'}",
        flush=True,
    )


def _report_soccer_unit_outcome(last_status: dict) -> None:
    """Did the PREVIOUS soccer unit actually write its artifact? (`#352`)

    The launch is fire-and-forget: the worker records a pid and returns without
    ever checking what the subprocess did. So a unit that dies in two seconds
    and one that simulates a full slate are indistinguishable from outside --
    both produce a `SOCCER_UNIT_LAUNCHED` line, both decrement `due`, neither
    reports an outcome.

    Measured 2026-08-11: units ran at 15:36 (la_liga 08-15) and 16:13 (la_liga
    08-16), `due` fell 8 -> 7, and BOTH target files still carried
    `generated_at: 2026-07-20T21:32` -- 22 days old. The subprocess emitted none
    of its own prints either, not even the unconditional "wrote empty artifact"
    on its no-fixtures path, because its stdout does not reach this log.

    VERIFIES BY STATE, NOT BY LOG. The file is the outcome; a captured stdout we
    cannot read is not. This is the same approach that settled `#344` -- one
    tick converts "the units do nothing" from an inference into a fact, and
    distinguishes the three live hypotheses: wrote nothing (died early), wrote
    elsewhere (wrong root), or wrote correctly (the join is at fault after all).
    """
    unit_key = str(last_status.get("lastUnit") or "").strip()
    launched = float(last_status.get("lastLaunchEpoch") or 0.0)
    if not unit_key or launched <= 0.0:
        return
    # `lastUnit` is "<league>|<date>" -- see `_soccer_unit_key`, which uses a
    # PIPE. I first wrote this parsing on ":" without reading that function, so
    # the split produced no date, the guard below returned early, and the
    # diagnostic printed NOTHING on every tick. An instrument that declines
    # silently is the exact defect it was built to expose, so it now says so.
    league, sep, unit_date = unit_key.partition("|")
    if not sep or not league or not unit_date:
        print(
            f"[refresh_worker] SOCCER_UNIT_OUTCOME_UNPARSED unit={unit_key!r} "
            "expected=<league>|<date>",
            flush=True,
        )
        return
    try:
        from syndicate.features.shared.refresh_state_store import data_root

        rec_path = (
            data_root() / "soccer_source" / league / "api" / "recommendations"
            / f"recommendations_{unit_date}.json"
        )
        exists = rec_path.is_file()
        mtime = rec_path.stat().st_mtime if exists else 0.0
    except Exception as exc:  # noqa: BLE001
        print(f"[refresh_worker] SOCCER_UNIT_OUTCOME_ERROR unit={unit_key} {type(exc).__name__}: {exc}", flush=True)
        return
    # Written AFTER the launch is the only thing that proves this run produced
    # it. An older file means the unit ran and left it untouched, which is the
    # failure being chased -- and is NOT the same as the file being absent.
    wrote = bool(exists and mtime >= launched - 5.0)
    print(
        f"[refresh_worker] SOCCER_UNIT_OUTCOME unit={unit_key} exists={exists} "
        f"wrote_since_launch={wrote} file_age_s={int(time.time() - mtime) if exists else -1} "
        f"since_launch_s={int(time.time() - launched)} path={rec_path}",
        flush=True,
    )


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

    # `#353`: CONFIRM THE PREVIOUS UNIT BEFORE DECIDING WHAT IS DUE.
    #
    # `unitEpochs` was stamped at LAUNCH, before the subprocess had done
    # anything -- so a unit that failed marked itself satisfied for the full
    # 4-hour interval, exactly as if it had succeeded. Measured 2026-08-11:
    # la_liga launched at 15:36, 16:13 and 16:46, wrote nothing at any of its
    # three dates, and at 18:36 the autorun reported
    # `no_unit_due units=8 next_due_in_s=3612` while five other leagues had
    # refreshed. Its files stayed on `generated_at: 2026-07-20` -- 22 days --
    # and would have stayed there indefinitely, because each retry re-stamps on
    # launch and sleeps again.
    #
    # Same shape as `#347`, where the reuse recorder fired after a REUSE and the
    # guard agreed with itself forever. Here the scheduler agrees with itself.
    #
    # So the success epoch is now written only once the file is verified on
    # disk. A launch records an ATTEMPT; only a write records a refresh.
    unit_epochs_state = last_status.get("unitEpochs") if isinstance(last_status.get("unitEpochs"), dict) else {}
    pending_key = str(last_status.get("lastUnit") or "").strip()
    pending_epoch = float(last_status.get("lastLaunchEpoch") or 0.0)
    if pending_key and pending_epoch > 0.0:
        wrote, _path, mtime = _soccer_unit_wrote_since(pending_key, pending_epoch)
        if wrote is True and float(unit_epochs_state.get(pending_key) or 0.0) < mtime:
            unit_epochs_state = {**unit_epochs_state, pending_key: mtime}
            _refresh_state_store()["write_json_file"](
                status_path, {**last_status, "unitEpochs": unit_epochs_state}
            )
            last_status = {**last_status, "unitEpochs": unit_epochs_state}
            print(
                f"[refresh_worker] SOCCER_UNIT_CONFIRMED unit={pending_key} "
                f"wrote_at={int(mtime)} launched_at={int(pending_epoch)}",
                flush=True,
            )
        # `wrote is None` is deliberately NOT a failure: unknowable means do not
        # conclude. Marking a unit failed because we could not look would retry
        # it forever.

    # `#352`: report what the PREVIOUS unit produced, before queuing the next.
    # Placed here so it runs on every tick regardless of which gate stops this
    # one -- an outcome that only prints when a new launch happens would go
    # silent exactly when the units stop working.
    _report_soccer_unit_outcome(last_status)
    # `#357`: and WHY, if the run that produced that outcome failed. Same
    # placement and same reason -- the cause must print on the tick where the
    # outcome does, not only when a new launch happens.
    _report_soccer_unit_failure(latest_manifest_path)

    # #282: one job per league-date instead of one job for all ten leagues.
    units, scope_kind = _soccer_refresh_units(selected_date)
    if not units:
        # Every in-season league resolved cleanly and none has a fixture inside
        # the horizon. A real, attributable zero -- say so once per tick rather
        # than returning a bare False that looks identical to "disabled".
        print(
            f"[refresh_worker] SOCCER_UNITS_EMPTY date={selected_date} reason=no_fixtures_in_horizon",
            flush=True,
        )
        return False

    now = time.time()
    interval_seconds = float(_soccer_weekly_refresh_interval_seconds())
    spacing_seconds = float(_soccer_unit_launch_spacing_seconds(len(units)))

    # Spacing gate. Distinct from the per-unit interval below: that one decides
    # WHETHER a unit is due, this one decides whether it is this tick's turn.
    last_launch_epoch = float(last_status.get("lastLaunchEpoch") or last_status.get("epoch") or 0.0)
    if last_launch_epoch > 0.0 and (now - last_launch_epoch) < spacing_seconds:
        return _soccer_autorun_skipped(
            "spacing_gate",
            f"units={len(units)} spacing_s={int(spacing_seconds)} since_last_launch_s={int(now - last_launch_epoch)}",
        )

    # Never stack a soccer job on top of a live one. launch_refresh_run's own
    # _assert_no_active_refresh_run would raise here, which is caught below and
    # written out as an `error` status -- true but misleading, since declining
    # to start a second job is correct behaviour, not a failure.
    active_jobs_now = _current_active_job_count(latest_manifest_path)
    if active_jobs_now > 0:
        return _soccer_autorun_skipped("active_job", f"active_jobs={active_jobs_now}")

    unit_epochs = last_status.get("unitEpochs") if isinstance(last_status.get("unitEpochs"), dict) else {}
    last_attempts = last_status.get("lastAttemptEpochs") if isinstance(last_status.get("lastAttemptEpochs"), dict) else {}

    # `#353`: two clocks, because a refresh and an attempt are different events.
    #
    # `unitEpochs` is the last VERIFIED write and gates the normal 4h cadence.
    # `lastAttemptEpochs` is the last launch and paces RETRIES, so a unit that
    # fails comes back in minutes instead of sleeping four hours pretending it
    # succeeded -- while still not hammering: a permanently broken league
    # retries on this backoff, not on every spacing window.
    #
    # 600s chosen against the measured unit cost (~105MB, 41-66s observed), so
    # a league failing all day costs ~6 attempts an hour rather than 12, and
    # recovers within ten minutes of whatever was wrong being fixed.
    retry_backoff_seconds = max(600.0, float(spacing_seconds))

    def _unit_due(unit: dict[str, str]) -> bool:
        key = _soccer_unit_key(unit)
        since_success = now - float(unit_epochs.get(key) or 0.0)
        if since_success < interval_seconds:
            return False
        # Never verified, or verified long ago -- but do not retry faster than
        # the backoff allows.
        since_attempt = now - float(last_attempts.get(key) or 0.0)
        return since_attempt >= retry_backoff_seconds

    due = [unit for unit in units if _unit_due(unit)]
    if not due:
        soonest = min(
            (interval_seconds - (now - float(unit_epochs.get(_soccer_unit_key(unit)) or 0.0)) for unit in units),
            default=0.0,
        )
        return _soccer_autorun_skipped(
            "no_unit_due",
            f"units={len(units)} interval_s={int(interval_seconds)} next_due_in_s={int(max(0.0, soonest))}",
        )
    # LEAST-RECENTLY-TOUCHED FIRST, where "touched" is a success OR an attempt.
    #
    # `#356`. This used to sort on `unit_epochs` alone -- last VERIFIED write --
    # and the comment claimed "a unit can never be starved by ordering", which was
    # true right up until `#353` stopped stamping that field on launch. After
    # `#353` a unit that launches cleanly and writes nothing keeps its ancient
    # success epoch forever, so it is permanently the stalest unit, wins `due[0]`
    # every retry window, and starves every other league. Measured on 2026-08-11:
    #
    #   before #353 (17:30-19:07)  belgian 35 · eredivisie 32 · mls 25 · champ 7 · primeira 1
    #   after  #353 (19:07-20:10)  la_liga 44 · belgian 27
    #
    # la_liga|2026-08-15 launched cleanly 44 times, wrote nothing 44 times, and
    # took the slot every ten minutes. `run_refresh_worker.py` already warns about
    # exactly this starvation mode on the launch-exception path below -- `#353`
    # opened the same door on the success path.
    #
    # Sorting on max(success, attempt) fixes it without giving back what `#353`
    # bought: `unitEpochs` still means "last verified write" and still gates the
    # 4h cadence, so nothing pretends to be fresh. A unit that just burned a slot
    # simply goes to the back of the queue. Among units that have NOT attempted
    # recently the attempt epoch is older than the success epoch, so `max()`
    # collapses to the success epoch and genuine stalest-first is preserved.
    due.sort(key=lambda unit: _soccer_unit_last_touched(_soccer_unit_key(unit), unit_epochs, last_attempts))
    unit = due[0]
    unit_league = str(unit.get("league") or "")
    unit_date = str(unit.get("date") or "")

    try:
        result = launch_refresh_run(
            date=selected_date,
            sports="soccer",
            soccer_leagues=unit_league,
            soccer_date=unit_date,
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
        # Stamp the unit even on failure. Leaving its epoch untouched would
        # make a permanently-failing unit the stalest one forever, so the
        # stalest-first pick above would return it every spacing interval and
        # nothing else would ever run -- a starvation bug that only appears
        # once something is already broken.
        _refresh_state_store()["write_json_file"](
            status_path,
            {
                **last_status,
                "epoch": time.time(),
                "lastLaunchEpoch": time.time(),
                "sports": "soccer",
                "date": selected_date,
                "unitEpochs": {**unit_epochs, _soccer_unit_key(unit): time.time()},
                "lastUnit": _soccer_unit_key(unit),
                "scopeKind": scope_kind,
                "unitCount": len(units),
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        print(
            f"[refresh_worker] SOCCER_UNIT_LAUNCH_FAILED league={unit_league} unit_date={unit_date or 'week_scope'} "
            f"error={type(exc).__name__}: {exc}",
            flush=True,
        )
        _write_worker_status(
            worker_status_path=worker_status_path,
            latest_manifest_path=latest_manifest_path,
            state="error",
            detail=f"Failed to auto-launch soccer refresh for {unit_league} {unit_date or '(week scope)'}: {type(exc).__name__}: {exc}",
            ran_job=False,
            latest_manifest_state=str((_latest_manifest_payload(latest_manifest_path).get("state") or "")).strip().lower() or None,
            refresh_cycle=refresh_cycle,
        )
        return False

    launched_epoch = time.time()
    # A launch ends the current skip regime, so the next skip -- even for the
    # same reason -- is a new transition and should print.
    _SOCCER_SKIP_REASON_LAST.pop("reason", None)
    _refresh_state_store()["write_json_file"](
        status_path,
        {
            **last_status,
            "epoch": launched_epoch,
            "lastLaunchEpoch": launched_epoch,
            "sports": "soccer",
            "date": selected_date,
            # `#353`: NOT stamped here. `unitEpochs` now means "last verified
            # write", confirmed against the file on a later tick. Stamping on
            # launch is what let three failed la_liga units sleep four hours
            # each while reporting themselves done.
            "unitEpochs": unit_epochs,
            "lastAttemptEpochs": {**last_attempts, _soccer_unit_key(unit): launched_epoch},
            "lastUnit": _soccer_unit_key(unit),
            "scopeKind": scope_kind,
            "unitCount": len(units),
            "error": None,
        },
    )
    refresh_cycle["claimed_count"] = int(refresh_cycle.get("claimed_count") or 0) + 1
    print(
        f"[refresh_worker] SOCCER_UNIT_LAUNCHED league={unit_league} unit_date={unit_date or 'week_scope'} "
        f"scope_kind={scope_kind} unit={due.index(unit) + 1}/{len(units)} due={len(due)} "
        # `#356`: WHY this unit won. The starvation ran for an hour undetected
        # because the launch line named the winner and never the queue -- 44
        # identical la_liga launches read as "the autorun is working". Printing
        # the runners-up makes one league monopolizing the slot visible in a
        # single line instead of requiring a unit histogram over the log window.
        f"queue={','.join(_soccer_unit_key(u) for u in due[:4])}{'...' if len(due) > 4 else ''} "
        f"last_success_age_s={int(now - float(unit_epochs.get(_soccer_unit_key(unit)) or 0.0))} "
        f"last_attempt_age_s={int(now - float(last_attempts.get(_soccer_unit_key(unit)) or 0.0))} "
        f"spacing_seconds={int(spacing_seconds)} pid={int(result.get('pid') or 0)}",
        flush=True,
    )
    _write_worker_status(
        worker_status_path=worker_status_path,
        latest_manifest_path=latest_manifest_path,
        state="launched",
        detail=f"Auto-launched soccer refresh for {unit_league} {unit_date or '(week scope)'} on {selected_date}.",
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
    age = time.time() - last_epoch if last_epoch > 0.0 else None
    interval = float(_reconciliation_interval_seconds())
    # A FAILED RUN MUST NOT CONSUME THE WHOLE DAY. The status epoch is written
    # on the error path too, so before this a single transient failure -- a
    # results API timeout, a half-written shard -- blocked every retry for 24
    # hours and produced nothing, silently. That is the same "enabled but mute"
    # outcome as the ordering bug, reached by a different route, so fixing one
    # without the other would leave the loop just as easy to stall.
    #
    # Backs off an hour rather than retrying immediately: a persistent failure
    # should not become a hot loop on a worker that has been at 2.6GB RSS.
    if str((last_status or {}).get("error") or "").strip():
        interval = min(interval, 3600.0)
    if age is not None and age < interval:
        # SAY WHY. Silence here is what made `#341` invisible: an enabled job
        # that declines every tick and an enabled job that never gets a tick
        # look identical from outside, and neither emits anything. Printed
        # rather than logger.info -- logger.info does not reach Render's
        # collector.
        print(
            f"[refresh_worker] RECONCILIATION_AUTORUN_GATED age_sec={age:.0f} "
            f"interval_sec={interval:.0f} next_in_sec={interval - age:.0f}",
            flush=True,
        )
        return False
    print(
        f"[refresh_worker] RECONCILIATION_AUTORUN_RUNNING last_epoch_age_sec="
        f"{'never' if age is None else f'{age:.0f}'}",
        flush=True,
    )

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


# #275: emitted ONCE PER PROCESS, and deliberately BEFORE the disabled-autorun
# early return below, because it must report from the service that cannot be
# asked.
#
# The chunk index is the DOMINANT term in settlement's per-record cost -- measured
# 2026-08-08, halving the chunk changed nothing while shrinking the index 10x cut
# the cost 6.5x. It is also the one term nobody can see: it is not in
# HOT_ARTIFACT_PATTERNS so it never crosses to web, refresh-worker serves no HTTP,
# and two lanes independently confirmed there is no path to it from any service
# with an API. A subsystem whose dominant cost is observable only from a process
# that publishes nothing cannot be priced without changing it first -- this is
# that change, and it is the cheapest possible one.
#
# WHY THIS IS NOT "periodic worker work is never free" (#241): it is one
# `Path.stat()` -- a metadata syscall, no read, no parse, no allocation -- fired
# once per process lifetime, not once per cycle. The worker reboots often enough
# (7 restarts in two hours on 2026-08-08) that the number arrives promptly
# regardless. Guarded once-per-boot rather than rate-limited so it cannot become
# periodic work by accident later.
#
# Reaches the Render logs API only via print(..., flush=True); logger.info does
# not survive the collector.
_EVALUATION_LEDGER_INDEX_SIZE_REPORTED = False


def _report_evaluation_ledger_index_size() -> None:
    global _EVALUATION_LEDGER_INDEX_SIZE_REPORTED
    if _EVALUATION_LEDGER_INDEX_SIZE_REPORTED:
        return
    _EVALUATION_LEDGER_INDEX_SIZE_REPORTED = True
    try:
        from syndicate.features.shared.intelligence_evaluation import DEFAULT_LEDGER_PATH
        from syndicate.features.shared.intelligence_evaluation import _ledger_index_path

        index_path = _ledger_index_path(DEFAULT_LEDGER_PATH)
        size = index_path.stat().st_size if index_path.exists() else -1
        print(
            "[evaluation_settlement] LEDGER_INDEX_SIZE "
            f"bytes={size} path={index_path} autorun_enabled={_evaluation_settlement_auto_refresh_enabled()} "
            "-- #275: the dominant per-record cost term; ~2.58MB RSS and ~0.058s per MB of this file, "
            "PER SETTLED RECORD, until the round trip is hoisted out of the loop",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        # Never let a diagnostic break the refresh cycle.
        print(f"[evaluation_settlement] LEDGER_INDEX_SIZE_FAILED {type(exc).__name__}: {exc}", flush=True)


def _launch_autorun_evaluation_settlement(
    *,
    latest_manifest_path: Path,
    worker_status_path: Path,
    refresh_cycle: dict[str, int],
) -> bool:
    _report_evaluation_ledger_index_size()
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


# #311. Count `run_refresh_odds_job.py`, because it is the ONE process both
# launch paths have in common, exactly once per running job:
#
#   queued-contract path   _spawn_pending_job -> run_queued_refresh_job.py
#                          -> run_refresh_odds_job.py        <- counted here
#   autorun path           launch_refresh_run(launch_mode="web_process")
#                          -> run_refresh_odds_job.py        <- counted here
#
# CORRECTED 2026-08-10 after the first deploy. This was
# `run_queued_refresh_job.py`, which only the queued path uses, so it read 0
# during every autorun-launched job. Measured on refresh-worker, 1.5h window:
#
#   run_queued_refresh_job.py    0 samples >0
#   run_refresh_odds_job.py     33 samples >0  (max concurrent 1)
#
# Two consequences, and the second is the one that mattered:
#   - the cap fell back to the manifest for the COMMON case, leaving the hole
#     this item exists to close still open on the autorun path;
#   - `JOB_COUNT_DISAGREEMENT` fired on every ordinary autorun job
#     (`manifest=1 processes=0`), so a marker documented as "the wedged-manifest
#     signature" was in fact mostly noise. A signal that cries wolf during
#     normal operation is worse than no signal, because it is indistinguishable
#     from the real thing at the moment you need it.
#
# NOT `refresh_odds_sources.py`: `run_refresh_odds_job.py` carries it as a
# trailing argument, so that string matches twice per job.
_JOB_PROCESS_MARKER = "run_refresh_odds_job.py"


def _running_job_process_count() -> int | None:
    """Live refresh-job processes, or None when that cannot be determined.

    Counts `run_refresh_odds_job.py` -- see `_JOB_PROCESS_MARKER` for why that
    specific process and not the one this originally counted.

    WHY THIS EXISTS RATHER THAN REUSING `_current_active_job_count`. That
    function reads the manifest, and the manifest is the thing that lies. It
    returns 0 whenever the state is `running` with no live pid -- which is
    EXACTLY the condition `_has_pending_external_contract` requires in order to
    re-claim. The two predicates are mutually exclusive by construction, so the
    manifest-derived cap reads zero precisely when the runaway it is supposed to
    bound is running. On 2026-08-08 that let the process count reach 79.

    None means "could not enumerate", and callers MUST NOT treat that as zero.
    """
    try:
        proc_root = Path("/proc")
        if proc_root.is_dir():
            count = 0
            enumerated = 0
            for entry in proc_root.iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
                except (OSError, PermissionError):
                    # A pid that exited mid-walk is normal and not a failure to
                    # enumerate; keep going.
                    continue
                enumerated += 1
                if _JOB_PROCESS_MARKER in cmdline:
                    count += 1
            if enumerated:
                return count
            return None
    except Exception:
        pass
    try:
        import psutil  # type: ignore

        count = 0
        for process in psutil.process_iter(attrs=["cmdline"]):
            try:
                parts = process.info.get("cmdline") or []
            except Exception:
                continue
            if any(_JOB_PROCESS_MARKER in str(part) for part in parts):
                count += 1
        return count
    except Exception:
        return None


def _resolve_active_job_count(latest_manifest_path: Path) -> tuple[int, str]:
    """How many refresh jobs are running, and which instrument said so.

    Takes the MAXIMUM of the process count and the manifest count rather than
    replacing one with the other: they fail in opposite directions. The
    manifest misses a job whose pid it never recorded; process enumeration
    misses a job that has been claimed but has not spawned yet. Either alone
    reads low, and reading low is the direction that spawns.
    """
    manifest_jobs = _current_active_job_count(latest_manifest_path)
    process_jobs = _running_job_process_count()
    if process_jobs is None:
        # UNKNOWN MUST NOT MEAN ZERO. Treating an un-enumerable container as
        # "no jobs running" hands the permissive branch to exactly the case we
        # cannot see, which is how the cap failed in the first place. Report
        # the manifest count but label the source, so a reader can tell a
        # verified zero from an unverifiable one.
        return manifest_jobs, "manifest_only_process_enum_unavailable"
    if process_jobs != manifest_jobs:
        # Worth a line: a persistent disagreement here IS the wedged-manifest
        # signature, and it was previously invisible.
        print(
            f"[refresh_worker] JOB_COUNT_DISAGREEMENT manifest={manifest_jobs} processes={process_jobs} "
            f"using={max(manifest_jobs, process_jobs)}",
            flush=True,
        )
    return max(manifest_jobs, process_jobs), "process_and_manifest"


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
    #
    # #327. THIS FUNCTION USED TO CALL `log_all_process_memory`, WHICH WRITES
    # STDERR ONLY. Its identically-named twin in pipeline/intelligence_state.py
    # also persisted to the ring buffer behind
    # /api/ops/intelligence/memory-diagnostics, and nothing at either call site
    # showed the difference. Measured 2026-08-10, 15:59-16:38Z: 172 pid-38
    # samples in the logs against 39 in the ring buffer, and the missing 77%
    # carried the highest values -- `post_mlb_sim_tick` (called at :2306 below)
    # peaked at 1867.4MB where the visible stages topped out at 1044.1MB. The
    # single largest memory excursion on this service was invisible to the
    # instrument built to find memory excursions.
    #
    # Both are now one implementation in memory_observability. Anything that
    # must be readable from WEB has to go through `log_and_persist_process_memory`
    # -- refresh-worker has no HTTP server of its own.
    try:
        from syndicate.features.shared.memory_observability import log_and_persist_process_memory

        log_and_persist_process_memory(stage)
    except Exception as exc:
        print(f"[refresh_worker] DIAG_MEMORY_LOG_FAILED stage={stage} {type(exc).__name__}: {exc}", flush=True)


_BOOK_GRID_LAST_RUN: dict[str, float] = {}


def _book_grid_live_refresh_interval_seconds() -> int:
    """Rebuild cadence while a game is actually live.

    120s, and ADAPTIVE rather than standing, which is the whole point. The board
    was rebuilding every 600s, so a live board could be nine minutes behind the
    market no matter how fast capture ran or how often the page polled -- this
    interval was the binding constraint on live freshness, sitting between a 60s
    capture and a 60s page poll and throwing most of both away.

    NOT applied all day. Measured 2026-08-11 00:0xZ, refresh-worker sat at
    **3,211MB of 4,096** -- 885MB raw headroom, the highest reading of the night
    and above the ~2,884MB plateau. A standing 5x increase in periodic work at
    that level is `#241` exactly: that lane caused a production restart loop by
    adding worker work that looked affordable. Tying the fast cadence to live
    games bounds the extra cost to the window where it buys something, and the
    slate is the thing that ends it.

    Costs, from tonight rather than from assumption: the MLB builder alone peaks
    211.5MB / 18.0s on the full shard, and a whole tick measured +245MB.
    """
    raw = str(os.environ.get("SYNDICATE_BOOK_GRID_LIVE_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return 120


def _book_grid_refresh_interval_seconds() -> int:
    raw_value = str(os.environ.get("SYNDICATE_BOOK_GRID_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        # An explicit override wins and DISABLES the adaptive path entirely --
        # someone pinning this value is answering the cadence question by hand,
        # and having the worker quietly speed up underneath that would make the
        # setting a lie.
        return max(60, int(raw_value))
    except ValueError:
        # 10 minutes. The shard is a per-day accumulator (measured 2026-08-09:
        # 0.9MB a few hours in, 207MB by end of day) and the grid is a research
        # surface, not a live-price feed -- rebuilding it every tick would be
        # the "worker periodic work is never free" mistake (#241 caused a
        # production restart loop that way).
        #
        # ...except while a game is live, where a 10-minute-old board is wrong
        # rather than merely stale. The flag is set by the PREVIOUS tick from the
        # grid it just built, so this needs no extra probe and cannot be fooled
        # by the liveness gate that spent 91 minutes returning False tonight
        # (`#339`). If the last tick saw a live game, run fast.
        if _BOOK_GRID_LAST_RUN.get("any_live"):
            return _book_grid_live_refresh_interval_seconds()
        return 600


# How much slower forward dates rebuild than today. 6x the main interval: a
# fixture four days out is not repriced on a ten-minute timescale, and today's
# board -- the one anyone is actually betting -- keeps the fast cadence.
_BOOK_GRID_FORWARD_INTERVAL_MULTIPLE = 6


def _book_grid_forward_days() -> int:
    """How many days past today to build, covering the widest slate window.

    Derived from `layer1_board`'s own window table rather than restated here, so
    the worker cannot build four days while the board asks for seven. A constant
    duplicated across a producer and a consumer is the drift `#329` exists to
    remove -- and this is exactly where it would reappear.
    """
    raw = str(os.environ.get("SYNDICATE_BOOK_GRID_FORWARD_DAYS") or "").strip()
    if raw:
        try:
            return max(0, min(14, int(raw)))
        except ValueError:
            pass
    try:
        from syndicate.features.shared.layer1_board import max_slate_window_days

        # -1 because a window of N days is today plus N-1 forward.
        return max(0, max_slate_window_days() - 1)
    except Exception:
        return 0


def _run_book_grid_artifact_tick() -> dict[str, Any] | None:
    """#322: pivot the book_quotes shard HERE so web never has to.

    Web cannot do this pivot. Measured 2026-08-09: the MLB shard is 207MB and
    costs ~6.3x resident, so one read is ~1.3GB against a 2GB container -- it
    OOM-killed web twice on 2026-08-10. This worker has 4GB and already holds
    shards for other work.

    Deliberately does NOT run for every sport every tick. It walks sports that
    actually have a shard today, which is the same set the odds sweep wrote,
    and skips the rest -- an absent shard is not an empty grid and writing one
    would make those indistinguishable downstream.
    """
    if str(os.environ.get("SYNDICATE_ENABLE_BOOK_GRID_ARTIFACT") or "true").strip().lower() in {"0", "false", "no", "off"}:
        return None
    interval = _book_grid_refresh_interval_seconds()
    now = time.time()
    if now - _BOOK_GRID_LAST_RUN.get("all", 0.0) < interval:
        return None
    _BOOK_GRID_LAST_RUN["all"] = now

    from syndicate.features.shared.book_grid_artifact import (
        build_book_grid_artifact,
        write_book_grid_artifact,
    )
    from syndicate.features.shared.artifact_publisher import (
        publish_hot_artifact,
        pull_streamed_artifact,
    )
    from syndicate.features.shared.odds_book_quotes import book_quotes_path
    from syndicate.features.shared.refresh_state_store import data_root

    selected_date = central_today_iso()
    # #322 follow-up. Building ONLY today froze every finished slate at whatever
    # the shard held when the Central date rolled. Measured 2026-08-10: the
    # 2026-08-09 artifact was last written ~04:5xZ and served 807 rows all
    # segment=full, while that day's completed shard pivots to 5,547 rows
    # including 1,251 segment rows. A reader looking back at a finished slate
    # saw a partial board with nothing saying it was partial.
    #
    # Yesterday is rebuilt ONCE PER DAY, not every tick: its shard stops growing
    # after rollover, so re-pivoting a 207MB file every 10 minutes forever would
    # be pure cost for a byte-identical result. #241 is the standing reminder
    # that periodic worker work is never free.
    previous_date = (date.fromisoformat(selected_date) - timedelta(days=1)).isoformat()
    rebuild_previous = _BOOK_GRID_LAST_RUN.get("previous_date") != previous_date
    dates = [selected_date] + ([previous_date] if rebuild_previous else [])

    # FORWARD DATES, so a slate window has something to read (`#329`).
    #
    # Building today and yesterday only made the multi-day window structurally
    # empty for every sport whose slate spans days. Measured 2026-08-10: soccer's
    # 7-day window resolved 08-10..08-16 and served 7 rows, because 6 of the 7
    # artifacts do not exist -- while /api/board/book-grid for 08-15 alone
    # returns 690 rows by falling through to a LIVE PIVOT ON WEB, which is the
    # thing `#323` moved off web for OOM-killing it.
    #
    # Soccer already shards quotes by the event's own KICKOFF date, so these
    # forward shards are real files with real fixtures in them, not empty
    # placeholders.
    #
    # ON A SLOWER CADENCE THAN TODAY, and that is `#241` applied rather than
    # quoted: a forward shard grows as books quote a fixture days out, so it
    # does need rebuilding, but nothing about a fixture four days away changes
    # in ten minutes. Absent shards cost a stat() and are skipped below.
    #
    # COST NOT YET MEASURED, and said plainly rather than assumed: I tried to
    # size the forward shards on 2026-08-10 and web was mid-deploy, so the
    # numbers are not in hand. The interval is the mitigation -- and
    # BOOK_GRID_TICK already logs what it built, so the first ticks after this
    # ships are the measurement.
    forward_days = _book_grid_forward_days()
    if forward_days > 0:
        interval_forward = interval * _BOOK_GRID_FORWARD_INTERVAL_MULTIPLE
        if now - _BOOK_GRID_LAST_RUN.get("forward", 0.0) >= interval_forward:
            _BOOK_GRID_LAST_RUN["forward"] = now
            anchor = date.fromisoformat(selected_date)
            dates.extend(
                (anchor + timedelta(days=offset)).isoformat()
                for offset in range(1, forward_days + 1)
            )

    written: list[str] = []
    skipped: list[str] = []
    any_live_today = False
    for build_date in dates:
        for sport in ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"):
            try:
                # RECONCILE THE SHARD FIRST (`#331`). This worker is not the
                # service that captures odds -- live-odds-worker is, and it
                # publishes the shard to web, which makes WEB canonical. The
                # existing repair pass only fetches artifacts this worker is
                # missing OUTRIGHT ("the list is empty once the files exist"),
                # so once a shard is pulled at date-rollover it is never
                # refreshed again.
                #
                # Measured 2026-08-10: the 2026-08-09 MLB artifact was built
                # from 7,987 quote rows against web's 478,782 -- 1.7% -- which
                # is exactly the shard's state at ~06:00Z, the hour it was
                # first pulled. The board served 807 rows instead of 5,547 and
                # ZERO segment rows instead of 1,251, which is the user-visible
                # "we lost the F1/F3/F5 filters" on /market-board/books.
                #
                # `pull_streamed_artifact` already tails append-only families by
                # HTTP Range (`#248`), so steady state is the few KB appended
                # since the last tick, not a re-fetch. A 416 means we already
                # hold everything. Failure is deliberately NOT fatal: a stale
                # shard still builds a board, and the row counts in the artifact
                # say how stale rather than leaving it to look complete.
                shard_path = book_quotes_path(sport, build_date)
                try:
                    relative = shard_path.relative_to(data_root()).as_posix()
                except ValueError:
                    relative = ""
                if relative:
                    try:
                        pull_streamed_artifact(relative, timeout_seconds=300)
                        # The `.state.json` sidecar too, and it is NOT optional.
                        # It backs `read_quote_last_seen`, which is the only
                        # thing separating "this market has not moved" from "we
                        # stopped looking at it" -- `seen_age_seconds`. A
                        # reconciled shard with a stale sidecar gives the board
                        # real prices and wrong ages, which is worse than the
                        # starvation it replaces because it looks correct.
                        #
                        # Whole-file, not tail: this one is rewritten on every
                        # flush. `_is_append_only` now requires `.jsonl` for
                        # exactly that reason -- before `#331` it matched this
                        # path too, and pulling it here would have appended a
                        # second JSON document onto the first.
                        pull_streamed_artifact(
                            relative[: -len(".jsonl")] + ".state.json"
                            if relative.endswith(".jsonl")
                            else relative,
                            timeout_seconds=120,
                        )
                    except Exception as exc:
                        print(
                            f"[refresh_worker] BOOK_GRID_SHARD_PULL_ERROR sport={sport} "
                            f"date={build_date} {type(exc).__name__}: {exc}",
                            flush=True,
                        )
                if not shard_path.is_file():
                    if build_date == selected_date:
                        skipped.append(sport)
                    continue
                payload = build_book_grid_artifact(sport, build_date)
                if not payload:
                    if build_date == selected_date:
                        skipped.append(sport)
                    continue
                if build_date == selected_date and not any_live_today:
                    for _row in (payload.get("rows") or []):
                        _g = _row.get("game")
                        if isinstance(_g, dict) and str(_g.get("state") or "").lower() == "live":
                            any_live_today = True
                            break
                path = write_book_grid_artifact(sport, build_date, payload)
                label = f"{sport}:{payload.get('rows_total')}"
                written.append(label if build_date == selected_date else f"{label}@{build_date}")
                try:
                    # Timeout raised from the 10s default ON PURPOSE (`#331`).
                    # Reconciling the shard grows this artifact by an order of
                    # magnitude: measured 2026-08-09, a full 5,547-row day with
                    # `#328`'s enrichment serialises to 15.7MB against the ~2.2MB
                    # a starved shard produces today. 10 seconds was sized for
                    # the small file and would start failing on the real one --
                    # a fix that makes the board correct and then cannot ship it.
                    #
                    # The result is CHECKED rather than fired and forgotten: the
                    # sweep that would otherwise repair a missed publish refuses
                    # this file at `_PUBLISH_MAX_BYTES` (12MB) once it is real, so
                    # a failure here is not backstopped by anything and must not
                    # be silent. See `#333`.
                    if not publish_hot_artifact(path, timeout_seconds=120):
                        print(
                            f"[refresh_worker] BOOK_GRID_PUBLISH_FAILED sport={sport} "
                            f"date={build_date} bytes={path.stat().st_size} "
                            f"(sweep will NOT repair this above 12MB -- see #333)",
                            flush=True,
                        )
                except Exception as exc:
                    print(f"[refresh_worker] BOOK_GRID_PUBLISH_ERROR sport={sport} date={build_date} {type(exc).__name__}: {exc}", flush=True)
            except Exception as exc:
                print(f"[refresh_worker] BOOK_GRID_BUILD_ERROR sport={sport} date={build_date} {type(exc).__name__}: {exc}", flush=True)
    # LIVENESS, READ OFF THE GRID WE JUST BUILT rather than probed for.
    #
    # `#328` stamps `game.state` on every row, so the tick already holds the
    # answer and a second source would be a second thing to disagree. It also
    # sidesteps `_mlb_has_live_game()`, which returned False through an entire
    # live game tonight for reasons still unknown (`#339`) -- a cadence that
    # depended on it would inherit that failure.
    #
    # Only TODAY's build counts: yesterday's artifact is full of finals and a
    # forward date cannot have a live game, so including them would latch the
    # fast cadence on permanently.
    _BOOK_GRID_LAST_RUN["any_live"] = bool(any_live_today)

    # Marked only after the pass, so a crash mid-rebuild retries next tick
    # rather than marking the day done and leaving it frozen for good.
    if rebuild_previous:
        _BOOK_GRID_LAST_RUN["previous_date"] = previous_date

    if not written and not skipped:
        return None
    return {
        "date": selected_date,
        "written": written,
        "skipped_no_shard": skipped,
        "rebuilt_previous": previous_date if rebuild_previous else None,
        # Which cadence the NEXT tick will use, and why. A board rebuilding every
        # 10 minutes during a live slate looks identical to one rebuilding every
        # 2 unless the tick says which it chose.
        "any_live": bool(any_live_today),
        "next_interval_seconds": _book_grid_refresh_interval_seconds(),
    }


def main() -> int:
    store = _refresh_state_store()
    assert_refresh_state_backend_ready = store["assert_refresh_state_backend_ready"]
    read_json_file = store["read_json_file"]
    print("[refresh_worker] BOOTED", flush=True)
    # #285. Cap glibc arenas BEFORE the loops spawn threads -- `mallopt` only
    # governs arenas created after it returns, so this is worthless if it moves
    # later in main(). The trim proved allocator retention is real (1109.6MB
    # returned by trim vs -104.3MB by gc across 24 calls) and only halved the
    # ratchet; by the time the guard fires there is nothing left to hand back,
    # so the residual is fragmentation or live retention. This tests the first.
    # Imported at the call site, matching _diag_log_all_process_memory's own
    # pattern in this file: memory_observability pulls in psutil-adjacent paths
    # and a module-level import here would fail the whole worker on a machine
    # where that is unavailable, rather than degrading one diagnostic.
    try:
        from syndicate.features.shared.memory_observability import configure_malloc_arenas

        configure_malloc_arenas(2)
    except Exception as exc:  # noqa: BLE001 - a memory hint must never stop boot
        print(f"[refresh_worker] MALLOC_ARENA_SETUP_FAILED {type(exc).__name__}: {exc}", flush=True)
    _diag_log_all_process_memory("boot")
    assert_refresh_state_backend_ready(process_name="refresh-worker")
    _bootstrap_soccer_player_seed_files()
    _bootstrap_soccer_schedule_seed_files()
    _bootstrap_soccer_history_seed_files()
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

        # #322: the Layer 1 book grid. Unconditional for the same reason as the
        # ticks above -- web physically cannot pivot the shard, so this is the
        # only thing that makes that surface exist.
        try:
            book_grid_meta = _run_book_grid_artifact_tick()
            if book_grid_meta:
                print(f"[refresh_worker] BOOK_GRID_TICK {json.dumps(book_grid_meta, sort_keys=True, default=str)}", flush=True)
        except Exception as exc:
            print(f"[refresh_worker] BOOK_GRID_TICK_ERROR {type(exc).__name__}: {exc}", flush=True)

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

        # #311. This was a bare `if` followed by a separate `if
        # _has_pending_external_contract(...)`, and the throttle branch
        # `return`ed only under --run-once. In the long-running loop it fell
        # straight through and spawned anyway -- the cap was computed, reported
        # in the worker status as `throttled`, and then ignored. Making it the
        # leading branch of the existing chain is what actually enforces it:
        # at cap, nothing else in the cycle runs and control reaches the
        # poll sleep at the bottom.
        active_jobs, active_jobs_source = _resolve_active_job_count(latest_manifest_path)
        if active_jobs >= max_active_jobs:
            refresh_cycle["skipped_due_to_cap"] = 1
            _mark_throttled_worker_status(
                worker_status_path=worker_status_path,
                latest_manifest_path=latest_manifest_path,
                active_jobs=active_jobs,
                max_active_jobs=max_active_jobs,
            )
            print(
                f"[refresh_worker] JOB_CAP_THROTTLED active={active_jobs} max={max_active_jobs} "
                f"source={active_jobs_source}",
                flush=True,
            )
            if args.run_once:
                return 0
        elif _has_pending_external_contract(latest_manifest_path):
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
        # `#341`: RECONCILIATION RUNS BEFORE THE REFRESH AUTORUNS, not after.
        #
        # It used to sit 6th in this exclusive chain, behind mlb_refresh,
        # weekly_sports and soccer_weekly. Every branch here is `elif`, so it
        # only got a turn on a tick where all three declined -- and during a
        # slate mlb_refresh keeps winning. The result: an autorun that is
        # ENABLED and correctly configured (RECONCILIATION_ENABLE_REFRESH_WORKER_
        # AUTORUN=true, interval 86400) emitted nothing for weeks.
        # `chunk_diagnostics` shows exists=false for 2026-07-17..08-04 and true
        # for 08-05 -- the signature of a job that gets a free tick occasionally
        # and is otherwise starved. `/api/portfolio/summary` read settled_count
        # 0 and avg_clv null the entire time.
        #
        # Safe to put first, and this is why rather than a hope: it is DAILY
        # GATED, so it wins at most one tick per 24h, and it runs INLINE rather
        # than launching a job -- it never held a job slot the refresh branches
        # were waiting for. Costing mlb_refresh one tick a day is not a
        # trade-off worth protecting; being mute for three weeks is.
        elif _launch_autorun_reconciliation(
            latest_manifest_path=latest_manifest_path,
            worker_status_path=worker_status_path,
            refresh_cycle=refresh_cycle,
        ):
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