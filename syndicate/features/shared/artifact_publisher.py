"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Pushes a small allowlist of frequently-refreshed ("hot") artifacts from a worker
  process to the web service's local disk, over HTTP, so the web dyno can serve
  current data without sharing a disk with the workers (Render disks are per-service).

Constraints:
- Must never raise: publish failures are logged and swallowed so a refresh loop
  never breaks because the web service is briefly unreachable.
- Only ever touches the fixed, explicit allowlist below. Bulk/historical/evaluation
  data is intentionally excluded and stays worker-local.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import os
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, NamedTuple
from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger("artifact_publisher")

HOT_ARTIFACT_PATTERNS: tuple[str, ...] = (
    "*_source/source_artifacts/data/live_lens/live_lens_report_*.json",
    "*_source/source_artifacts/data/live_lens/render_sync/*.json",
    # NBA/WNBA's in-game pace-adjusted live projections, written by the
    # vendored live-lens tick (now called in-process from
    # syndicate/features/wnba/live_lens.py instead of only over HTTP) and read
    # by wnba/cards.py's _artifact_live_player_lens_payload. Written on
    # live-odds-worker, read on web -- Render gives each service its own
    # disk, so this allowlist entry is what actually gets a live game's
    # projection from the worker that computes it to the service that serves
    # it, not just a path-naming fix.
    "*_source/source_artifacts/data/live_lens/live_lens_projections_*.jsonl",
    "*_source/source_artifacts/data/live_lens/live_lens_signals_*.jsonl",
    "*_source/source_artifacts/data/processed/recommendations*.json",
    "*_source/source_artifacts/data/processed/recommendations*.csv",
    "*_source/source_artifacts/data/processed/props_recommendations*.json",
    "*_source/source_artifacts/data/processed/props_recommendations*.csv",
    "*_source/source_artifacts/data/processed/game_cards_*.csv",
    "*_source/source_artifacts/data/processed/cards_sim_detail_*.json",
    "*_source/source_artifacts/data/processed/cards_props_snapshot_*.json",
    "*_source/source_artifacts/data/processed/smart_sim_*.json",
    "*_source/source_artifacts/data/market/*.json",
    # Phase 3 of migrating off the daily-update GHA cron: these were only
    # ever synced by the retired pipeline's blanket Sync-SportSourceArtifacts
    # robocopy. Confirmed live reads (not just worker-side generation) before
    # adding: season_betting_card_manifest -> nba/betting_card.py's
    # build_season_betting_card_manifest_payload, consumed by
    # blueprints/nba.py; live_player_lens_tuning -> nba/cards.py and
    # wnba/cards.py's live-game rendering. Deliberately NOT adding
    # calibration_active.json/prob_calibration.json/manifests/* -- those are
    # worker-only inputs to the odds refresh scripts, never read by any
    # blueprint, so pushing them would just reproduce the old robocopy's
    # "copy everything" bulk-data mistake.
    "*_source/source_artifacts/data/processed/season_betting_card_manifest_*.json",
    "*_source/source_artifacts/data/processed/live_player_lens_tuning_*.csv",
    "*_source/source_artifacts/current_week.json",
    # NBA/WNBA's raw (unfiltered, pre-recommendation-engine) OddsAPI player
    # props feed (scripts/fetch_basketball_oddsapi_props_local.py's flat
    # per-outcome rows). Confirmed via direct research 2026-07-23: this was
    # written worker-side but never allowlisted, so the market board's
    # Layer 1 join only ever saw the recommendation engine's own curated
    # picks -- the same gap MLB's oddsapi_pitcher_props/oddsapi_hitter_props
    # (already allowlisted above via the market/*.json pattern) had before
    # this session's market board work started reading it directly.
    "*_source/source_artifacts/data/processed/oddsapi_player_props_*.csv",
    "*_source/data/processed/oddsapi_player_props_*.csv",
    # Same set again, one directory shallower: some sports (confirmed for WNBA)
    # write their processed artifacts straight to "<sport>_source/data/processed/"
    # rather than nesting under a "source_artifacts" nested root, so the patterns
    # above alone silently match zero files for those sports.
    "*_source/data/live_lens/live_lens_report_*.json",
    "*_source/data/live_lens/render_sync/*.json",
    "*_source/data/live_lens/live_lens_projections_*.jsonl",
    "*_source/data/live_lens/live_lens_signals_*.jsonl",
    "*_source/data/processed/recommendations*.json",
    "*_source/data/processed/recommendations*.csv",
    "*_source/data/processed/props_recommendations*.json",
    "*_source/data/processed/props_recommendations*.csv",
    "*_source/data/processed/game_cards_*.csv",
    "*_source/data/processed/cards_sim_detail_*.json",
    "*_source/data/processed/cards_props_snapshot_*.json",
    "*_source/data/processed/smart_sim_*.json",
    "*_source/data/market/*.json",
    "*_source/data/processed/season_betting_card_manifest_*.json",
    "*_source/data/processed/live_player_lens_tuning_*.csv",
    "*_source/current_week.json",
    # #43. The intelligence board state, moved off the keyvalue store. It is
    # data, not coordination state: measured at 15.5MB for 150 candidates
    # against an 8MB ceiling the store cannot be raised past (~9MB closes the
    # connection). Deduplication could not close that -- the payload is five
    # near-copies of the candidate list and they are enriched differently, so
    # they are not aliasable. This path already moves tens of MB routinely and
    # matches the stated architecture: workers write artifacts, web reads them.
    "reports/intelligence/intelligence_state.json",
    "reports/intelligence/intelligence_state_*.json",
    # #83's bounded per-date steam record. capture_phase and steam detection
    # are otherwise only observable through the raw per-observation lifecycle
    # log (odds_events/<date>.jsonl), which reached 1.2GB in a single day
    # (odds_lifecycle.py) -- allowlisting that would reproduce the exact
    # oversized-payload pattern that caused #43/#50/#54. This file is the
    # opposite by construction: capped at the newest 200 events
    # (_STEAM_EVENTS_KEEP in odds_refresh_tracking.py), each event carrying
    # capture_phase directly, so it is the cheap, bounded way to verify both
    # without exporting bulk data.
    "reports/steam/steam_events_*.json",
    # Same-moment odds-events-coverage diagnostic for the pitcher live-lens
    # investigation (see fetch_mlb_oddsapi_local.py::_diagnose_live_events_coverage):
    # OddsAPI's raw/date-filtered event counts vs. MLB's own schedule-derived
    # live count, written on whichever service runs the odds-refresh
    # subprocess. Tiny (a handful of ints per date), so allowlisting it is
    # cheap; without this it is only readable on the writing service's own
    # disk, and the writer isn't necessarily the one this is investigated from.
    "reports/mlb_odds_diag/live_events_coverage_*.json",
    # #207. Same-moment provenance of odds_history as it exists on the ODDS
    # WORKER's own disk. odds_history is written to three paths and the third
    # (reports/odds_control_plane/odds_history/) sits outside data_root() by
    # construction, so it can never be allowlisted and never crosses services --
    # meaning web literally cannot see the copy the writing service keeps. This
    # tiny summary (book counts, bookmaker-coverage %, closing-capture %) is the
    # only way to compare what the odds worker CAPTURES against what web
    # RECEIVES, which is what decides whether #205/#206's single-book and
    # missing-closing-line findings are a capture defect or a publish defect.
    "reports/mlb_odds_diag/odds_history_provenance_*.json",
    # MLB's vendored daily sim (vendor/mlb_bettingv2/tools/daily_update.py,
    # triggered from live_refresh_loop.py's MLB daily-sim gate) writes under
    # data/daily/, data/manager/, data/park/, data/umpire/ -- none of which
    # the processed/live_lens/market patterns above cover. Bulk/historical
    # paths (data/cache, data/raw/statcast, data/eval/seasons/...) are
    # deliberately excluded here, consistent with this module's "no
    # bulk/historical data" constraint above.
    "*_source/source_artifacts/data/daily/daily_summary_*.json",
    "*_source/source_artifacts/data/daily/ladders/daily_ladders_*.json",
    "*_source/source_artifacts/data/daily/top_props/daily_top_props_*.json",
    "*_source/source_artifacts/data/daily/lineups_last_known_by_team.json",
    # Daily odds/lineup snapshots: confirmed live reads on web -- MLB cards.py
    # reads snapshots/<date>/{oddsapi_game_lines,oddsapi_hitter_props,
    # oddsapi_pitcher_props,lineups}.json for market tiles and lineup state,
    # and hr_targets.py walks the date dir. These are written worker-side by
    # refresh_mlb_oddsapi.py; without publishing them the web board renders
    # ml/totals as null (observed 2026-07-16). Small per-date JSONs, not bulk.
    "*_source/source_artifacts/data/daily/snapshots/*/*.json",
    # Per-game sim artifacts: cards.py hydrates output segments and starter
    # ladder badges from data/daily/sims/<date>/sim_*.json (and game detail
    # rides the same lookup). In the GHA era these reached web via git sync;
    # worker-centric sims left them stranded worker-side, so compact cards
    # rendered without sim tiles (observed 2026-07-17). ~200-400KB per game,
    # current + next day only -- not the bulk/historical case above.
    "*_source/source_artifacts/data/daily/sims/*/sim_*.json",
    "*_source/source_artifacts/data/manager/manager_tendencies.json",
    "*_source/source_artifacts/data/manager/probable_pitcher_overrides.json",
    "*_source/source_artifacts/data/park/park_factors.json",
    "*_source/source_artifacts/data/umpire/umpire_factors*.json",
    "*_source/data/daily/daily_summary_*.json",
    "*_source/data/daily/ladders/daily_ladders_*.json",
    "*_source/data/daily/top_props/daily_top_props_*.json",
    "*_source/data/daily/lineups_last_known_by_team.json",
    "*_source/data/daily/snapshots/*/*.json",
    "*_source/data/daily/sims/*/sim_*.json",
    "*_source/data/manager/manager_tendencies.json",
    "*_source/data/manager/probable_pitcher_overrides.json",
    "*_source/data/park/park_factors.json",
    "*_source/data/umpire/umpire_factors*.json",
    # #68. The per-date betting-card payload. It lives UNDER data/eval/seasons,
    # which the comment above excludes as bulk/historical -- correctly for that
    # tree in general, and wrongly for this one file, which is a small
    # per-date artifact that merely happens to be stored there (measured:
    # 5.4KB for a full slate, one per day, same category as
    # daily_summary_*.json two blocks up).
    #
    # Excluding it had a large consequence. mlb/cards.py's
    # _betting_payload_by_game reads exactly this file, and it is the ONLY
    # source of game["markets"] -- which _mlb_game_market_recommendation_rows
    # turns into the game_market_recommendations that
    # _game_bet_candidates_from_game reads. Measured on refresh-worker
    # 2026-07-26: BETTING_PAYLOAD_READ exists=False, betting_game_count 0,
    # every MLB market block 0, MLB contributing nothing to the board, while
    # web served the same games with a full 7-key markets dict. Not
    # allowlisted meant neither the push nor the pull could ever move it, so
    # the worker could not converge no matter how long it ran.
    #
    # Deliberately narrow: scoped to the betting_day_payloads_* directory and
    # the season_betting_day_* filename, so data/eval/seasons/** at large --
    # statcast, caches, season rollups -- stays excluded as before.
    "*_source/source_artifacts/data/eval/seasons/*/betting_day_payloads_*/season_betting_day_*.json",
    "*_source/data/eval/seasons/*/betting_day_payloads_*/season_betting_day_*.json",
    # #84. NWS park weather, one small per-date JSON written worker-side by
    # scripts/fetch_mlb_weather.py; the board and (once joined, #84's open
    # half) the sim read it.
    "*_source/source_artifacts/data/weather/weather_*.json",
    # Ask the Syndicate focused-evidence inputs (syndicate/blueprints/
    # ask_the_syndicate_data.py). These are live web-side reads: the Ask
    # endpoint builds last-10 game-log tables from the boxscore histories and
    # the sim-accuracy trend from sim_vs_actual. One file per day (evals,
    # ~4.5MB) or one rolling file per sport (boxscores). NBA's
    # boxscores_history.csv (~20MB) is deliberately NOT listed -- it rides
    # the git+bootstrap lane instead; the WNBA/NHL equivalents are small.
    "mlb_source/source_artifacts/data/eval/batches/*/sim_vs_actual_*.json",
    "wnba_source/source_artifacts/data/processed/boxscores_history.csv",
    "wnba_source/data/processed/boxscores_history.csv",
    "nhl_source/source_artifacts/data/raw/player_game_stats.csv",
    "nhl_source/data/raw/player_game_stats.csv",
    # #163's MLB player game-log index (last-N starts/games, history vs
    # opponent -- syndicate/features/mlb/player_game_log.py, read by
    # ask_the_syndicate_data.py's _mlb_player_history_evidence) is the same
    # category as WNBA/NHL's boxscore/game-stats CSVs two lines up and was
    # missed when those were added: written by refresh-worker
    # (run_mlb_daily_sim_job.py's post-sim hook) but read on web, so without
    # this entry it would build correctly forever on refresh-worker's disk
    # and never once reach the service that answers Ask The Syndicate
    # questions -- confirmed live 2026-07-30 (a real "Eury Perez outs" query
    # against production returned no visuals at all post-deploy). Small
    # per-season CSVs (thousands of rows, not the NBA-scale ~20MB case that
    # rides the git+bootstrap lane instead).
    "mlb_source/source_artifacts/data/processed/mlb_pitcher_game_log.csv",
    "mlb_source/data/processed/mlb_pitcher_game_log.csv",
    "mlb_source/source_artifacts/data/processed/mlb_batter_game_log.csv",
    "mlb_source/data/processed/mlb_batter_game_log.csv",
    # #163's MLB advanced Statcast profile (whiff/barrel/xwOBA/pitch-mix --
    # syndicate/features/intelligence.py's _mlb_statcast_feature_payload,
    # read on web by both Ask The Syndicate and other MLB features). Same
    # gap as the two entries above: worker-written, web-read, never
    # allowlisted. ~9-10MB, bounded (one curated feature file per season, not
    # a growing/unbounded tree like data/cache or data/raw/statcast).
    "mlb_source/source_artifacts/data/statcast/features/player_features_latest.json",
    "mlb_source/data/statcast/features/player_features_latest.json",
    # Soccer has no source_artifacts/data/processed nesting -- build_soccer_artifacts.py,
    # poll_soccer_live_state.py, build_soccer_schedule.py, fetch_soccer_oddsapi_odds_local.py,
    # fetch_soccer_oddsapi_props_local.py, and build_soccer_picks.py all write directly
    # under soccer_source/<league>/api/ (or soccer_source/<league>/props/), so the generic
    # "*_source/..." patterns above never match soccer's files. Literal sport prefix, same
    # as the mlb_source/wnba_source/nhl_source eval/boxscore entries above.
    "soccer_source/*/api/recommendations/recommendations_*.json",
    "soccer_source/*/api/live_state/live_state_*.json",
    "soccer_source/*/api/display_prediction_dates.json",
    "soccer_source/*/api/schedule/schedule_*.json",
    # Raw bookmaker odds/props/picks (2026-07-24 market-board work): these
    # three were never allowlisted even though the refresh dispatcher has
    # scheduled fetch_soccer_oddsapi_odds_local.py/build_soccer_picks.py for a
    # while -- confirmed live in production that the fetch step runs to
    # completion (return_code=0) and presumably writes its file on whichever
    # service happened to run it, but the market board (served by web) never
    # saw a single row, because these three patterns were missing here and
    # the file never got published/pulled to web's disk.
    "soccer_source/*/api/odds/game_odds_current.csv",
    "soccer_source/*/props/*.csv",
    "soccer_source/*/api/picks/picks_*.csv",
    # Note: reports/intelligence/board_snapshot.json and intelligence_state.json are
    # intentionally excluded here. They're written through refresh_state_store's
    # write_json_file, which already goes over the shared keyvalue (Redis) backend on
    # Render, so all three services see them without needing this HTTP push at all.
    #
    # #112: odds_history's per-shard payload is ALSO written through
    # write_json_file/the keyvalue backend by default -- but it can exceed the
    # 8MB keyvalue ceiling (confirmed live 2026-07-28, same class of failure
    # as #43's board_snapshot/intelligence_state), at which point
    # odds_refresh_tracking._sync_odds_history_for_refresh falls back to a
    # local-disk write + publish_hot_artifact via the #108 _write_state_payload
    # pattern. Two of the three paths it writes live under data_root() (the
    # third, reports/odds_control_plane/odds_history/, is outside data_root()
    # by construction and can't be matched by is_hot_artifact_relative_path --
    # that copy only ever reaches the SAME service's own disk, which is
    # sufficient for the refresh-worker's own next-cycle convergence but not
    # for cross-service reads). Without these two entries, publish_hot_artifact
    # would SKIP_NOT_ALLOWLISTED every fallback write and web would never see
    # an oversized shard no matter how many refresh cycles ran.
    "*_source/tracking/odds_history/*.json",
    "*_source/artifacts/*/odds_history/*.json",
    # #209: per-book quote log (syndicate/features/shared/odds_book_quotes.py).
    # Deliberately NOT a bookmaker dimension on the odds_history shards above --
    # that shard is already 54MB at 3,682 MLB keys and restoring ~5 books to its
    # 3,437 prop keys would push it toward 250MB, published every cycle on 2GB
    # services, while silently changing which book four existing single-book
    # consumers pick. This family carries the per-book truth (CLV, best-price
    # re-grade) and odds_history keeps its display-oriented single-book shape.
    # Written on live-odds-worker, read on web -- so like odds_history it needs
    # this entry to cross services at all, and unlike the #207 diagnostic it is
    # published explicitly by its own writer rather than relying on the
    # allowlist alone (allowlisting only PERMITS a push; something has to make
    # it).
    "*_source/tracking/book_quotes/*.jsonl",
    # #124: the actual root cause of MLB live props reading zero everywhere
    # except web. syndicate/features/shared/live_lens_loop.py runs on
    # live-odds-worker (per its own header comment: "runs independently ...
    # in the same process (live-odds-worker)"), builds a real per-game
    # live-lens snapshot with populated liveProps/archivedLiveProps (a real
    # in-game Monte Carlo re-sim for MLB), writes it to
    # data_root()/live/{mlb,nba,wnba}_live_lens.json via write_json_file, and
    # then calls publish_changed_hot_artifacts EVERY TICK specifically to
    # push files like this one to web. None of these three paths were ever
    # in this allowlist, so that periodic push always skipped them
    # (SKIP_NOT_ALLOWLISTED) -- not a keyvalue-size failure like #43/#112,
    # just a plain missing entry. Every other service (web serving a direct
    # page request, refresh-worker's candidate-pool build) has no path to
    # this data at all and falls back to an independent, thinner recompute
    # (mlb/live_lens.py's build_live_lens_snapshot_internal) from the lighter
    # live_lens_report_*.json artifact alone, which structurally carries the
    # liveProps/archivedLiveProps keys but never actually populates them --
    # confirmed live: web's own direct recompute had real data (24/18/16
    # prop rows across 3 games), refresh-worker's had prop_row_counts=[0]*9
    # across all 9 real live games, unchanged even after fixing two other
    # once-daily artifact gaps in the same investigation. These paths are
    # NOT under a "*_source/..." prefix like everything else in this list --
    # data/live/ is its own top-level tree -- so the pattern has to be
    # written out per sport rather than reusing the generic prefix.
    "live/mlb_live_lens.json",
    "live/nba_live_lens.json",
    "live/wnba_live_lens.json",
)


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _data_root() -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return data_root()


def relative_to_data_root(path: Path) -> str | None:
    try:
        relative = Path(path).expanduser().resolve().relative_to(_data_root())
    except Exception:
        return None
    return str(relative).replace("\\", "/")


def is_hot_artifact_relative_path(relative_path: str) -> bool:
    normalized = str(relative_path or "").strip().replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return False
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in HOT_ARTIFACT_PATTERNS)


def _publish_url() -> str:
    base = _env("SYNDICATE_WEB_PUBLISH_URL")
    if not base:
        return ""
    return base.rstrip("/") + "/api/ops/artifacts/publish"


def _admin_token() -> str:
    return _env("ADMIN_TOKEN") or _env("SYNDICATE_ADMIN_TOKEN")


def _hot_artifact_pull_watermark_path() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "refresh_status" / "latest" / "hot_artifact_pull_watermark.json"


# Hard ceiling on how far back a pull will ever reach.
#
# Without it this had two unbounded paths, and production hit both on
# 2026-07-25 (refresh-worker OOM crash loop + cascading web 502s):
#
# 1. No watermark meant "pull everything". Every deploy boots a worker with
#    no watermark, so every deploy pulled the entire artifact set at once.
#    That is the single OOM seen after each deploy that day.
# 2. The watermark only advances on a fully successful pull -- correct on its
#    own, but it means a FAILING pull leaves the window to grow forever. Each
#    failure makes the next attempt strictly heavier, so once the response
#    crossed what a 2GB container could parse, it could never get back under
#    it. That is a self-amplifying loop, not a transient.
#
# Both sides load the whole response in memory (the worker json.loads() it,
# the web service builds the dict to serve it), so window size translates
# directly into peak memory on two services at once.
#
# A bounded pull that succeeds beats an unbounded one that crashes: missing
# an artifact older than this window degrades one cycle, whereas the loop
# above pulls nothing at all and takes the worker down with it.
_MAX_PULL_WINDOW_SECONDS = 2 * 3600


def _hot_artifact_pull_since_epoch(*, pull_started_epoch: float) -> float | None:
    # Mirrors live_refresh_loop.py's _hot_artifact_publish_since_epoch on the
    # push side: floor = the start of the last successful pull, not each
    # call's own start time, so a slow or delayed cycle still catches
    # everything written since the last time this actually completed --
    # clamped to _MAX_PULL_WINDOW_SECONDS so neither a missing watermark nor
    # a stalled one can turn this into an unbounded fetch.
    from syndicate.features.shared.refresh_state_store import read_json_file

    payload = read_json_file(_hot_artifact_pull_watermark_path())
    try:
        stored = float(payload.get("epoch")) if isinstance(payload, dict) and payload.get("epoch") is not None else None
    except (TypeError, ValueError):
        stored = None
    window_floor = float(pull_started_epoch) - _MAX_PULL_WINDOW_SECONDS
    if stored is None or stored <= 0.0:
        return window_floor
    return max(stored, window_floor)


def _record_hot_artifact_pull_watermark(epoch: float) -> None:
    from syndicate.features.shared.refresh_state_store import write_json_file

    try:
        write_json_file(_hot_artifact_pull_watermark_path(), {"epoch": epoch})
    except Exception:
        # Must never raise (module-wide constraint) -- worst case, the next
        # pull just doesn't advance the watermark and re-fetches everything.
        pass


def publish_hot_artifact(path: Path, *, timeout_seconds: int = 10) -> bool:
    """Best-effort push of a single allowlisted artifact to the web service.

    Returns False (and never raises) on any condition that prevents publishing:
    not configured, not an allowlisted path, file missing, or a network error.
    """
    url = _publish_url()
    token = _admin_token()
    if not url or not token:
        print(f"[artifact_publisher] SKIP_NOT_CONFIGURED path={path} url_set={bool(url)} token_set={bool(token)}", flush=True)
        return False

    relative_path = relative_to_data_root(Path(path))
    if not relative_path or not is_hot_artifact_relative_path(relative_path):
        print(f"[artifact_publisher] SKIP_NOT_ALLOWLISTED path={path} relative_path={relative_path}", flush=True)
        return False

    file_path = Path(path)
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"[artifact_publisher] SKIP_READ_FAILED path={file_path} error={exc}", flush=True)
        return False

    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    body = json.dumps(
        {"relative_path": relative_path, "content": content, "checksum": checksum}
    ).encode("utf-8")

    request_obj = urllib_request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib_request.urlopen(request_obj, timeout=timeout_seconds) as response:
            response.read()
        print(f"[artifact_publisher] PUBLISH_OK path={relative_path} url={url}", flush=True)
        return True
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        print(f"[artifact_publisher] PUBLISH_FAILED path={relative_path} url={url} error={exc}", flush=True)
        return False
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(f"[artifact_publisher] PUBLISH_UNEXPECTED_ERROR path={relative_path} url={url} error={exc}", flush=True)
        return False


def publish_hot_artifacts(paths: Any) -> int:
    """Publish an iterable of paths, returning the count that succeeded."""
    published = 0
    for path in paths or ():
        if publish_hot_artifact(path):
            published += 1
    return published


class HotArtifactSweepResult(NamedTuple):
    """Outcome of a publish_hot_artifacts_since sweep.

    publish_hot_artifact never raises -- a network blip or a momentarily
    unreachable web service just returns False and is logged, not thrown.
    That means a bare published-count return can't tell a caller "every
    candidate in this window went through" from "some silently failed" --
    a caller that advances a persisted watermark on any non-raising return
    would permanently skip a file that failed for a transient reason, the
    exact same class of "async output missing on web forever" bug this was
    built to prevent in the first place. all_succeeded lets watermark-based
    callers only advance past a window once every candidate in it is
    confirmed published, so a real failure retries on the next sweep
    instead of vanishing.
    """

    published_count: int
    failed_paths: tuple[Path, ...]

    @property
    def all_succeeded(self) -> bool:
        return not self.failed_paths


def sweep_changed_hot_artifacts(since_epoch_seconds: float) -> HotArtifactSweepResult:
    """Sweep the allowlisted hot-artifact locations under the data root and publish
    any file modified at or after ``since_epoch_seconds``.

    Used after a refresh tick that runs per-sport work in a detached subprocess,
    where we can't easily hook every downstream write site directly.
    """
    if not _publish_url() or not _admin_token():
        return HotArtifactSweepResult(published_count=0, failed_paths=())
    root = _data_root()
    published = 0
    failed: list[Path] = []
    for pattern in HOT_ARTIFACT_PATTERNS:
        for candidate in root.glob(pattern):
            try:
                if not candidate.is_file() or candidate.stat().st_mtime < since_epoch_seconds:
                    continue
            except OSError:
                continue
            if publish_hot_artifact(candidate):
                published += 1
            else:
                failed.append(candidate)
    return HotArtifactSweepResult(published_count=published, failed_paths=tuple(failed))


def publish_changed_hot_artifacts(since_epoch_seconds: float) -> int:
    """Back-compat wrapper over sweep_changed_hot_artifacts for callers that
    only care about the published count, not per-file success (e.g. callers
    that publish synchronously right after their own subprocess finishes,
    where there's no persisted watermark to protect against advancing past
    a failed file -- see run_mlb_daily_sim_job.py / run_queued_refresh_job.py).
    """
    return sweep_changed_hot_artifacts(since_epoch_seconds).published_count


def _export_url(pattern: str | None = None, *, since_epoch: float | None = None, exact_path: str | None = None) -> str:
    base = _env("SYNDICATE_WEB_PUBLISH_URL")
    if not base:
        return ""
    url = base.rstrip("/") + "/api/ops/artifacts/export"
    params: list[str] = []
    if exact_path:
        from urllib.parse import quote

        # ?path= is the endpoint's single-artifact form: it skips the glob
        # entirely and returns one file, so a repair fetch costs one stat and
        # one read rather than a scan of the matched set.
        params.append(f"path={quote(exact_path, safe='')}")
    elif pattern:
        from urllib.parse import quote

        params.append(f"pattern={quote(pattern, safe='')}")
    if since_epoch is not None:
        params.append(f"since={since_epoch}")
    if params:
        url += "?" + "&".join(params)
    return url


def _pull_hot_artifacts_request(url: str, token: str, *, timeout_seconds: int) -> tuple[bool, int]:
    """Returns (succeeded, files_written). succeeded distinguishes a genuine
    request failure from a successful-but-empty response (e.g. nothing
    changed since the caller's own watermark) -- pull_hot_artifacts only
    advances its persisted watermark when every sub-request succeeded, so a
    transient network blip doesn't permanently skip files modified during
    the failed window.
    """
    request_obj = urllib_request.Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib_request.urlopen(request_obj, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        print(f"[artifact_publisher] PULL_FAILED url={url} error={exc}", flush=True)
        return False, 0
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(f"[artifact_publisher] PULL_UNEXPECTED_ERROR url={url} error={exc}", flush=True)
        return False, 0

    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    if not isinstance(artifacts, dict):
        print(f"[artifact_publisher] PULL_EMPTY_RESPONSE url={url}", flush=True)
        return False, 0

    root = _data_root()
    written = 0
    for relative_path, content in artifacts.items():
        normalized = str(relative_path or "").strip().replace("\\", "/")
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            continue
        if not is_hot_artifact_relative_path(normalized):
            continue
        target_path = root / Path(normalized)
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            # Keyed by pid alone, this collided whenever two pulls for the
            # same artifact ran concurrently in the same process (the
            # intelligence_state background loop's periodic tick and an
            # on-demand request both bypassing the cache around the same
            # moment, e.g.) -- both computed the identical temp_path, the
            # first os.replace() consumed it, and the second's os.replace()
            # then failed with ENOENT ('src' -> 'dst', the exact shape seen
            # in production PULL_WRITE_FAILED errors for soccer's MLS
            # recommendations/live_state artifacts). A uuid4 suffix makes
            # every write's temp file unique regardless of what's calling
            # concurrently, without needing to know why.
            temp_path = target_path.parent / f"{target_path.name}.{os.getpid()}.{uuid.uuid4().hex}.pull.tmp"
            temp_path.write_text(str(content), encoding="utf-8")
            os.replace(temp_path, target_path)
            written += 1
        except Exception as exc:
            print(f"[artifact_publisher] PULL_WRITE_FAILED path={normalized} error={exc}", flush=True)
            # temp_path is only ever unique to this one write attempt (see
            # above), so if it still exists here the failure happened after
            # it was written but before/during os.replace() -- clean it up
            # rather than leaving it orphaned on disk forever.
            try:
                if "temp_path" in locals() and temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            continue

    print(f"[artifact_publisher] PULL_OK url={url} artifacts_received={len(artifacts)} written={written}", flush=True)
    return True, written


def pull_hot_artifacts(*, date_str: str | None = None, timeout_seconds: int = 30) -> int:
    """Best-effort pull of hot artifacts from the web service's disk onto
    this process's own disk.

    2026-07-20: refresh-worker's board-computation loop reads sport artifacts
    (recommendations_slate, props_recommendations, game_cards, etc.) from its
    own Render disk, which is a separate physical disk from the one
    live-odds-worker (or an on-demand web request) actually writes them to --
    Render disks are per-service, not shared, and publish_hot_artifact/
    sweep_changed_hot_artifacts above only ever push worker -> web. Confirmed
    in production: refresh-worker computed a genuinely empty candidate pool
    for hours (repeated "Missing WNBA artifact" errors reading its own local
    disk) while the identical computation, run against the web service's
    disk, produced real candidates. This is the missing other direction: web
    -> refresh-worker, pulled (refresh-worker doesn't run an HTTP server, so
    it can't receive a push). Never raises -- a network blip here should
    degrade to stale local data, not break board computation.

    date_str scopes the request to today's ?pattern=*<date>* instead of the
    full combined hot-artifact set: an unfiltered call reproducibly hit
    Render's proxy timeout (502) in production once enough sports/days had
    accumulated hot artifacts -- this module's own docstring calls the
    allowlist "small", but small-per-file times many files times many days
    is not small in aggregate. Almost every hot artifact is date-suffixed
    (recommendations/props/game_cards/sims/snapshots), so this still covers
    the files board computation actually needs; a handful of non-dated
    files (current_week.json, park_factors.json, etc.) are out of scope for
    this per-cycle pull and would need a separate, infrequent full sync.

    2026-07-20: a plain f"*{date_str}*" (date_str = ISO "YYYY-MM-DD") only
    matched hyphen-separated filenames (WNBA's
    recommendations_slate_2026-07-20.json) and silently missed
    underscore-separated ones (MLB's live_lens_report_2026_07_20.json,
    season_betting_day_2026_07_20.json) -- confirmed in production: MLB's
    candidate_generation stayed at 0 on every cycle, with artifact_status
    showing artifact_exists=false, while WNBA worked fine, because MLB's
    required artifacts were never being pulled at all.

    A single combined bracket-expression pattern (matching either
    separator in one request) was tried first and also 502'd in
    production -- matching both separators at once roughly doubles the
    combined WNBA+MLB result set, and that larger payload hit the exact
    same Render proxy timeout this date-scoping was already built to
    avoid. Two separate, smaller requests (one per format) each stay
    close to the original per-request size that was already confirmed
    safe, and a failure on one doesn't cost the other.

    2026-07-24: every call re-fetched full content for every matching file,
    every ~30s (this function's only caller ticks on that interval) --
    confirmed as the dominant contributor to two 8.6MB/28.9MB responses
    every cycle once odds-history-driven artifact growth made the matched
    set large, which itself fed sustained near-ceiling memory on a 2GB web
    instance. Now passes a persisted since= watermark (floor = the start of
    the last successful pull) so the export endpoint only returns files
    modified since then; the watermark only advances when every sub-request
    for this call succeeds, so a partial failure re-fetches that same
    window next time instead of silently skipping it.
    """
    token = _admin_token()
    if not token or not _env("SYNDICATE_WEB_PUBLISH_URL"):
        print(f"[artifact_publisher] PULL_SKIP_NOT_CONFIGURED url_set={bool(_env('SYNDICATE_WEB_PUBLISH_URL'))} token_set={bool(token)}", flush=True)
        return 0
    pull_started_epoch = time.time()
    since_epoch = _hot_artifact_pull_since_epoch(pull_started_epoch=pull_started_epoch)
    if not date_str:
        succeeded, written = _pull_hot_artifacts_request(_export_url(None, since_epoch=since_epoch), token, timeout_seconds=timeout_seconds)
        if succeeded:
            _record_hot_artifact_pull_watermark(pull_started_epoch)
        return written
    written = 0
    all_succeeded = True
    for pattern in _date_glob_patterns(date_str):
        succeeded, sub_written = _pull_hot_artifacts_request(_export_url(pattern, since_epoch=since_epoch), token, timeout_seconds=timeout_seconds)
        written += sub_written
        all_succeeded = all_succeeded and succeeded
    if all_succeeded:
        _record_hot_artifact_pull_watermark(pull_started_epoch)
    # Repair pass, AFTER the watermark is recorded and deliberately not part of
    # all_succeeded. It fetches only artifacts this worker is missing outright,
    # one exact ?path= request each and no since= filter, so it is the one
    # thing the incremental pull structurally cannot do for itself. Costs
    # nothing on a healthy worker: the list is empty once the files exist, so
    # no request is made at all. If web is missing them too it retries each
    # cycle -- one small request, and the log line says so rather than
    # pretending the board is merely quiet.
    for relative_path in _missing_required_artifact_relative_paths(date_str):
        # #233: STREAM the big ones. /export loads the whole artifact into the
        # web service's memory to answer, and book_quotes shards are 52MB
        # (measured 2026-08-06, MLB) -- every repair request for one came back
        # PULL_FAILED / written=0 against a 2GB web instance, so the file the
        # Layer 2 board's prices depend on could be correctly requested and
        # still never arrive.
        #
        # pull_streamed_artifact already exists for exactly this and reads in
        # 1MB chunks ("a 51MB shard is ~51 reads", per its own note). Routing
        # the known-large families through it makes the repair pass able to
        # deliver them at all; everything else keeps /export, which is fine for
        # the small once-a-day artifacts this list was originally built for.
        if "/book_quotes/" in relative_path or "/odds_history/" in relative_path:
            repair_succeeded, repair_written = pull_streamed_artifact(
                relative_path, timeout_seconds=max(timeout_seconds, 300)
            )
        else:
            repair_succeeded, repair_written = _pull_hot_artifacts_request(
                _export_url(exact_path=relative_path), token, timeout_seconds=timeout_seconds
            )
        written += repair_written
        print(
            f"[artifact_publisher] PULL_REPAIR_MISSING path={relative_path} "
            f"ok={repair_succeeded} written={repair_written}",
            flush=True,
        )
    # #237: freshness pass for the shards that are APPENDED TO all day. The
    # repair pass above is presence-based and so, for these, does the wrong
    # thing exactly when it looks like it worked -- it fetched them once and
    # then skipped them forever, freezing this worker's prices at that instant.
    # Same defect the live-lens block below was written to fix, on the files
    # the board's prices are actually built from. Only re-streams copies that
    # already exist, so it never double-requests what the repair pass just
    # asked for, and a current copy costs one 304 with no body.
    for relative_path in _stale_streamable_artifact_relative_paths(date_str):
        refresh_succeeded, refresh_written = pull_streamed_artifact(
            relative_path, timeout_seconds=max(timeout_seconds, 300)
        )
        written += refresh_written
        if refresh_written:
            # Logged only when a NEWER copy actually landed. The steady state is
            # a 304 every cycle for every shard, and printing that would bury
            # the one line that says the board's prices just moved.
            print(
                f"[artifact_publisher] PULL_REFRESH_STALE path={relative_path} "
                f"ok={refresh_succeeded} written={refresh_written}",
                flush=True,
            )
    # #124: the live-lens snapshots (data/live/{mlb,nba,wnba}_live_lens.json,
    # now allowlisted above) are continuously rewritten -- every ~60s while
    # games are live -- but carry no date in their filename at all, so
    # _date_glob_patterns' *2026-07-28*/*2026_07_28* patterns can NEVER match
    # them; the incremental, date-scoped pull above structurally cannot ever
    # request them, regardless of watermark freshness. The missing-artifact
    # repair pass above doesn't fit either: it only fires once, the first
    # time a path is absent, and then skips forever once ANY copy exists
    # locally -- exactly wrong for a file that needs to be fresh every
    # cycle, not merely present once. So these three are fetched
    # unconditionally, every cycle, via the same cheap single-file ?path=
    # form (one stat, one read, no since=/pattern= glob over anything else).
    # Confirmed this is where the actual live MLB prop data lives: web's own
    # direct-request recompute has real liveProps (24/18/16 rows across 3
    # live games), while every other service's independent recompute from
    # the lighter, dated live_lens_report_*.json alone produces the
    # liveProps/archivedLiveProps keys with zero rows in them.
    for relative_path in ("live/mlb_live_lens.json", "live/nba_live_lens.json", "live/wnba_live_lens.json"):
        live_lens_succeeded, live_lens_written = _pull_hot_artifacts_request(
            _export_url(exact_path=relative_path), token, timeout_seconds=timeout_seconds
        )
        written += live_lens_written
        print(
            f"[artifact_publisher] PULL_LIVE_LENS_SNAPSHOT path={relative_path} "
            f"ok={live_lens_succeeded} written={live_lens_written}",
            flush=True,
        )
    return written


def _required_daily_artifact_paths(date_str: str) -> list[Path]:
    """Absolute paths to board-critical artifacts that are written ONCE a day.

    #68. The incremental pull can repair a copy that is OLDER than web's; it
    can never repair one that is MISSING, because `since=` filters on web's
    mtime and a once-a-morning artifact stops being newer than the watermark
    within minutes. That is fine for the continuously-rewritten artifacts this
    module was designed around, and permanently wrong for these.

    Kept as an explicit, tiny list rather than derived from
    _artifact_specs_for_sport: that lives in syndicate.features.intelligence,
    which imports most of the app, and this module is called from the pull
    path on every cycle.
    """
    paths: list[Path] = []
    try:
        from syndicate.features.mlb.sources import season_betting_card_day_path

        season = int(str(date_str).strip()[:4])
        paths.append(season_betting_card_day_path(season, str(date_str).strip()))
    except Exception:
        # Must never raise -- a repair that cannot be computed just means the
        # normal incremental pull is all this cycle gets.
        pass
    try:
        # 2026-07-28: the exact same "written once, permanently un-repairable"
        # gap as season_betting_card_day_path above, confirmed live for MLB
        # props specifically absent from the board. daily_top_props is
        # generated once (or a few times) per day by the vendored daily
        # pipeline, IS allowlisted (HOT_ARTIFACT_PATTERNS), and web's own
        # disk had it fully populated (307 pitcher + hitter rows, verified
        # live) -- but refresh-worker's incremental since= pull can only
        # repair a copy OLDER than web's, never one that never arrived, and
        # this file was never in the explicit repair list that exists
        # specifically to cover that case. home.py's
        # _load_mlb_home_top_prop_items (the sole source of MLB pregame
        # props for candidate generation, via _MLBDataProvider.pregame_props)
        # reads exactly this path, so a permanently-missing copy on
        # refresh-worker means zero MLB pregame prop candidates every cycle,
        # regardless of anything downstream (filter_candidates, freshness
        # gates) -- confirmed live: MLB prop rejections in filter_candidates
        # were exactly zero, meaning props never reached it at all.
        from syndicate.features.mlb.sources import daily_top_props_path

        paths.append(daily_top_props_path(str(date_str).strip()))
    except Exception:
        pass
    try:
        # Same class of gap again, found chasing MLB LIVE props specifically
        # (pregame props were fixed by daily_top_props above and confirmed
        # live: pregame_count 0 -> 18/28). Live props stayed at zero even
        # after that fix, with a diagnostic confirming _MLBDataProvider.
        # live_props independently finds real prop-backed live games
        # (prop_backed_games=9) but every one of them has an EMPTY
        # liveProps/archivedLiveProps list (prop_row_counts=[0]*9) --
        # structurally present, no actual rows. Traced to
        # _cards_recommendation_payload_by_game (mlb/cards.py), which merges
        # betting_games (season_betting_card_day_path, already required
        # above) with recos_by_game built from THIS file
        # (daily_artifact_path(date, "_locked_policy") ->
        # daily_summary_<date>_locked_policy.json) to populate
        # markets.{pitcher,hitter,extraPitcher,extraHitter}Props, which is
        # exactly what _live_props_from_card (live_lens.py) reads to build
        # each live game's liveProps. It matches the allowlist's existing
        # "daily_summary_*.json" glob (so incremental pulls DO carry it when
        # fresh), but like season_betting_card_day_path and daily_top_props
        # it is generated once per slate and can go permanently missing on a
        # worker that booted, or had its disk reset, after the since=
        # watermark first advanced past it.
        from syndicate.features.mlb.sources import daily_artifact_path

        paths.append(daily_artifact_path(str(date_str).strip(), suffix="_locked_policy"))
    except Exception:
        pass
    try:
        # #128: the base daily_summary_<date>.json (no suffix) is a DIFFERENT
        # file from the _locked_policy one just above -- build_cards_page_context
        # (mlb/cards.py) loads it separately as `summary_path`/`summary` for its
        # own `outputs`/game_pks list AND to decide its own source_title
        # ("MLB cards unavailable" whenever `summary` is falsy). Missing from
        # this list entirely until now: confirmed live on live-odds-worker,
        # after the _locked_policy repair above landed and ran, cards still
        # reported source_title "MLB cards unavailable" and zero props --
        # this is the file that check actually gates on.
        from syndicate.features.mlb.sources import daily_artifact_path

        paths.append(daily_artifact_path(str(date_str).strip()))
    except Exception:
        pass
    try:
        # Same "written once, permanently un-repairable if never pulled"
        # class of gap as the four MLB entries above, confirmed to exist in
        # principle (not yet observed in production) for WNBA during a
        # 2026-07-29 cross-sport comparison after MLB's own version of this
        # bug was fixed. recommendations_slate_<date>.json is WNBA's sole
        # pregame-props source (syndicate.features.wnba.picks._summary_for_date,
        # the only reader _WNBADataProvider.pregame_props -> home_rails.pregame
        # ultimately depends on) -- the normal incremental pull DOES cover a
        # stale copy (HOT_ARTIFACT_PATTERNS already globs recommendations*.json),
        # but not one that never arrived at all after the since= watermark
        # advanced past it, e.g. a worker that booted or had its disk reset
        # post-watermark. processed_path_or_default never raises (returns a
        # plain path even when the file doesn't exist yet), matching this
        # function's own "must never raise" contract without needing the
        # try/except below to do that work.
        from syndicate.features.wnba.sources import processed_path_or_default as _wnba_processed_path_or_default

        selected = str(date_str).strip()
        paths.append(_wnba_processed_path_or_default(f"recommendations_slate_{selected}.json"))
        paths.append(_wnba_processed_path_or_default(f"props_recommendations_{selected}.csv"))
    except Exception:
        pass
    try:
        # Same class of gap again, found chasing why soccer's steam-move
        # board candidates couldn't resolve a real matchup: confirmed live
        # 2026-07-29 that refresh-worker's own overview build reported
        # dashboard_games_count=0 for soccer on every cycle (both today and
        # tomorrow), while web's own /soccer/mls/api/cards correctly showed
        # 16 real games -- refresh-worker never had a usable copy of the
        # per-league season schedule at all. schedule_<season>.json is a
        # once-a-season artifact (week_matches/schedule_payload,
        # syndicate/features/soccer/sources.py), already allowlisted for
        # the normal incremental pull ("soccer_source/*/api/schedule/
        # schedule_*.json" in HOT_ARTIFACT_PATTERNS above), but a
        # since=-scoped pull can never repair a copy that never arrived in
        # the first place -- same shape as every entry above. Scoped to
        # only the leagues actually in season for this date (soccer tracks
        # 10 leagues; most of the year only 1-3 are active), so this stays
        # a handful of small requests, not ten.
        from syndicate.features.soccer.sources import active_leagues_for_date
        from syndicate.features.soccer.sources import default_season
        from syndicate.features.soccer.sources import schedule_path

        selected = str(date_str).strip()
        for league in active_leagues_for_date(selected):
            try:
                paths.append(schedule_path(league, default_season(league)))
            except Exception:
                continue
    except Exception:
        pass
    try:
        # #232: the per-book quote log, for every sport that keeps one.
        #
        # This is the file the Layer 2 board's price context is built from, and
        # it had NEVER reached refresh-worker -- zero book_quotes log lines
        # there, ever, while web's copy was fine. The board consequently served
        # 138 candidates with a canonical market_key and not one price.
        #
        # It was assumed to self-heal because it IS allowlisted and DOES match
        # the `*<date>*` incremental glob. Both are true and it still never
        # arrived: the incremental pull filters on `since=`, and a 502 on that
        # path holds the watermark back, so a file that is missing outright can
        # stay missing indefinitely. That is exactly the gap this repair list
        # exists for -- an exact `?path=` request with no `since=` filter -- and
        # book_quotes simply was not on it. Costs nothing once the file exists,
        # because _missing_required_artifact_relative_paths only asks for
        # artifacts this service does not already have.
        from syndicate.features.shared.odds_book_quotes import book_quotes_path

        selected = str(date_str).strip()
        for sport in ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"):
            try:
                paths.append(book_quotes_path(sport, selected))
            except Exception:
                continue
        # #239: soccer alone shards by each FIXTURE's date, not by the slate
        # date. `_append_soccer_prop_book_quotes` buckets rows by
        # `commence_time[:10]` before writing, so asking only for today gets a
        # 404 forever while the quotes sit in tomorrow's file. Verified on
        # production 2026-08-06: soccer/2026-08-06 was absent while 08-07
        # (120,637 B), 08-08 (533,825), 08-09 (483,682) and 08-10 (23,318) all
        # existed on web and had never been pulled -- which is the whole reason
        # soccer rows on the board carried no price.
        #
        # Soccer only, because it is the only writer that does this; every other
        # sport writes to the slate date and a forward window for them would be
        # 404s every cycle for nothing.
        for offset in range(1, _SOCCER_FIXTURE_LOOKAHEAD_DAYS + 1):
            try:
                future = (date.fromisoformat(selected) + timedelta(days=offset)).isoformat()
                paths.append(book_quotes_path("soccer", future))
            except Exception:
                continue
    except Exception:
        pass
    return paths


# How far ahead to fetch soccer's fixture-dated quote shards. Seven days covers
# a normal fixture list without asking for months of 404s; a far-future fixture
# (the Serie A opener 16 days out) stays unpriced until it comes inside the
# window, which is fine -- prices that far ahead would be stale by kickoff.
_SOCCER_FIXTURE_LOOKAHEAD_DAYS = 7

# Families that are APPENDED TO all day rather than written once. The repair
# pass above is presence-based, so for these it does the wrong thing precisely
# when it looks like it worked: it fetches the shard the first time it is
# absent and then skips it forever, freezing this worker on whatever the file
# contained at that moment.
_CONTINUOUSLY_APPENDED_MARKERS: tuple[str, ...] = ("/book_quotes/", "/odds_history/")


def _stale_streamable_artifact_relative_paths(date_str: str) -> list[str]:
    """Present-but-possibly-stale shards to re-stream this cycle (#237).

    Measured 2026-08-06. refresh-worker pulled its copies once, at 21:03:22Z,
    and never again -- `PULL_REPAIR_MISSING` fires only on absence. By 22:19Z
    web held wnba 1,486,090 bytes and mlb 55,799,948 while refresh-worker was
    still building the board off the 1,165,695 / 53,130,595 byte snapshots from
    21:03. WNBA's evening markets were posted after that capture, so its cards
    could not price at all: 2 of 20 on the served board, against a fix that
    prices them correctly on a current shard.

    Deliberately complements, rather than duplicates, the repair pass: that one
    owns MISSING files, this one owns files that exist. So an out-of-season
    sport is asked for exactly once per cycle, not twice.

    Cheap by construction. `pull_streamed_artifact` sends `since=<local mtime>`
    and web answers 304 with no body when the copy is current -- its own
    docstring calls that "the reason this is cheap enough to call every cycle",
    which is what this finally does.
    """
    relative_paths: list[str] = []
    try:
        root = _data_root().resolve()
    except Exception:
        return relative_paths
    for path in _required_daily_artifact_paths(date_str):
        try:
            if not path.is_file():
                continue  # the repair pass owns this one
            relative = path.resolve().relative_to(root).as_posix()
        except Exception:
            continue
        if not any(marker in relative for marker in _CONTINUOUSLY_APPENDED_MARKERS):
            continue
        if is_hot_artifact_relative_path(relative):
            relative_paths.append(relative)
    return relative_paths


def _missing_required_artifact_relative_paths(date_str: str) -> list[str]:
    relative_paths: list[str] = []
    try:
        root = _data_root().resolve()
    except Exception:
        return relative_paths
    for path in _required_daily_artifact_paths(date_str):
        try:
            if path.is_file():
                continue
            relative = path.resolve().relative_to(root).as_posix()
        except Exception:
            continue
        # The same allowlist the writer enforces. Asking for something outside
        # it would just be refused, and silently: worth failing here instead.
        if is_hot_artifact_relative_path(relative):
            relative_paths.append(relative)
    return relative_paths


# Sports whose odds_history shard key is the plain ISO date. Deliberately
# excludes nfl/ncaaf: _shard_key_for_row scopes those by season/week, so a
# date-named shard never exists for them and asking would just 404 every
# cycle. Kept as an explicit tuple for the same reason
# _required_daily_artifact_paths is an explicit list -- this runs on the pull
# path every cycle and must not import syndicate.features.intelligence.
_ODDS_HISTORY_DATE_SHARDED_SPORTS: tuple[str, ...] = ("mlb", "nba", "wnba", "nhl", "ncaab", "soccer")

# 1MB. Large enough that a 51MB shard is ~51 reads, small enough that peak
# resident cost of a transfer is a rounding error on a 4GB worker -- the
# entire point of streaming this rather than taking it through export's
# read-whole-file-into-a-dict path.
_STREAM_CHUNK_BYTES = 1024 * 1024


def odds_history_relative_paths_for_date(date_str: str, *, sports: tuple[str, ...] | None = None) -> list[str]:
    """Allowlisted odds_history shard paths the board build needs for a date.

    Only the "artifacts" path, not "tracking": both are allowlisted and both
    hold the same payload (odds_refresh_tracking._sync_odds_history_for_refresh
    writes all three copies), so pulling both would move ~51MB twice for one
    usable file. The reader's own precedence
    (odds_control_plane.odds_history_paths_for_sport) is shared -> artifacts
    -> tracking, and the shared copy lives under reports/odds_control_plane/,
    which is NOT allowlisted and so can never cross services -- on a worker
    that copy simply doesn't exist and the reader falls through to this one.
    """
    shard_key = str(date_str or "").strip()
    if not shard_key:
        return []
    return [
        f"{sport}_source/artifacts/{sport}/odds_history/{shard_key}.json"
        for sport in (sports or _ODDS_HISTORY_DATE_SHARDED_SPORTS)
    ]


def _stream_url(relative_path: str, *, since_epoch: float | None = None) -> str:
    base = _env("SYNDICATE_WEB_PUBLISH_URL")
    if not base:
        return ""
    from urllib.parse import quote

    url = base.rstrip("/") + "/api/ops/artifacts/stream?path=" + quote(relative_path, safe="")
    if since_epoch is not None:
        url += f"&since={since_epoch}"
    return url


def pull_streamed_artifact(relative_path: str, *, timeout_seconds: int = 120) -> tuple[bool, int]:
    """Stream ONE allowlisted artifact to local disk. Returns (ok, written).

    Never raises, same contract as the rest of this module. `ok` is False only
    on a genuine failure -- a 304 (this worker's copy is already current) is a
    success that writes nothing, which is the normal steady state.
    """
    normalized = str(relative_path or "").strip().replace("\\", "/")
    if not normalized or not is_hot_artifact_relative_path(normalized):
        return False, 0
    token = _admin_token()
    if not token or not _env("SYNDICATE_WEB_PUBLISH_URL"):
        return False, 0

    target_path = _data_root() / Path(normalized)
    local_mtime: float | None = None
    try:
        if target_path.is_file():
            local_mtime = target_path.stat().st_mtime
    except Exception:
        local_mtime = None

    url = _stream_url(normalized, since_epoch=local_mtime)
    if not url:
        return False, 0
    request_obj = urllib_request.Request(url, method="GET", headers={"Authorization": f"Bearer {token}"})

    temp_path: Path | None = None
    try:
        with urllib_request.urlopen(request_obj, timeout=timeout_seconds) as response:
            remote_mtime_raw = response.headers.get("X-Artifact-Mtime")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            # uuid4-suffixed for the same concurrency reason the bulk pull's
            # temp names are (see _pull_hot_artifacts_request).
            temp_path = target_path.parent / f"{target_path.name}.{os.getpid()}.{uuid.uuid4().hex}.stream.tmp"
            total = 0
            with open(temp_path, "wb") as handle:
                while True:
                    chunk = response.read(_STREAM_CHUNK_BYTES)
                    if not chunk:
                        break
                    handle.write(chunk)
                    total += len(chunk)
        os.replace(temp_path, target_path)
        temp_path = None
        # Stamp the copy with web's mtime, not now(): the next cycle sends
        # this back as since=, and a local mtime later than the source would
        # make an updated shard look already-current forever.
        if remote_mtime_raw:
            try:
                remote_mtime = float(remote_mtime_raw)
                os.utime(target_path, (remote_mtime, remote_mtime))
            except Exception:
                pass
        print(f"[artifact_publisher] STREAM_PULL_OK path={normalized} bytes={total}", flush=True)
        return True, 1
    except urllib_error.HTTPError as exc:
        if exc.code == 304:
            # Already current. The steady state, and the reason this is cheap
            # enough to call every cycle.
            return True, 0
        if exc.code == 404:
            # Web doesn't have it either (no refresh has written this date's
            # shard yet). Not an error worth failing the caller over, but say
            # so rather than letting the board look merely quiet.
            print(f"[artifact_publisher] STREAM_PULL_ABSENT path={normalized}", flush=True)
            return False, 0
        print(f"[artifact_publisher] STREAM_PULL_FAILED path={normalized} status={exc.code}", flush=True)
        return False, 0
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        print(f"[artifact_publisher] STREAM_PULL_FAILED path={normalized} error={exc}", flush=True)
        return False, 0
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(f"[artifact_publisher] STREAM_PULL_UNEXPECTED_ERROR path={normalized} error={exc}", flush=True)
        return False, 0
    finally:
        try:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass


def pull_odds_history_artifacts(
    *, date_str: str, sports: tuple[str, ...] | None = None, timeout_seconds: int = 120
) -> int:
    """Pull every date-sharded odds_history artifact for a date. Returns files written.

    Separate from pull_hot_artifacts on purpose: these are the files that do
    not fit its bulk transport (see api_ops_artifacts_stream's comment), and
    keeping them out of that call leaves its watermark semantics untouched.
    """
    written = 0
    for relative_path in odds_history_relative_paths_for_date(date_str, sports=sports):
        _, files = pull_streamed_artifact(relative_path, timeout_seconds=timeout_seconds)
        written += files
    return written


def _date_glob_patterns(date_str: str) -> list[str]:
    parts = str(date_str or "").strip().split("-")
    if len(parts) == 3 and all(parts):
        joined = "-".join(parts)
        return [f"*{joined}*", f"*{'_'.join(parts)}*"]
    return [f"*{date_str}*"]
