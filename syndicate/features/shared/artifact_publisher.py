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
from pathlib import Path
from typing import Any, NamedTuple
from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger("artifact_publisher")

HOT_ARTIFACT_PATTERNS: tuple[str, ...] = (
    "*_source/source_artifacts/data/live_lens/live_lens_report_*.json",
    "*_source/source_artifacts/data/live_lens/render_sync/*.json",
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
    # Same set again, one directory shallower: some sports (confirmed for WNBA)
    # write their processed artifacts straight to "<sport>_source/data/processed/"
    # rather than nesting under a "source_artifacts" nested root, so the patterns
    # above alone silently match zero files for those sports.
    "*_source/data/live_lens/live_lens_report_*.json",
    "*_source/data/live_lens/render_sync/*.json",
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
    # Note: reports/intelligence/board_snapshot.json and intelligence_state.json are
    # intentionally excluded here. They're written through refresh_state_store's
    # write_json_file, which already goes over the shared keyvalue (Redis) backend on
    # Render, so all three services see them without needing this HTTP push at all.
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


def _export_url() -> str:
    base = _env("SYNDICATE_WEB_PUBLISH_URL")
    if not base:
        return ""
    return base.rstrip("/") + "/api/ops/artifacts/export"


def pull_hot_artifacts(*, timeout_seconds: int = 45) -> int:
    """Best-effort pull of the full hot-artifact set from the web service's
    disk onto this process's own disk.

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
    """
    url = _export_url()
    token = _admin_token()
    if not url or not token:
        print(f"[artifact_publisher] PULL_SKIP_NOT_CONFIGURED url_set={bool(url)} token_set={bool(token)}", flush=True)
        return 0

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
        return 0
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(f"[artifact_publisher] PULL_UNEXPECTED_ERROR url={url} error={exc}", flush=True)
        return 0

    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    if not isinstance(artifacts, dict):
        print(f"[artifact_publisher] PULL_EMPTY_RESPONSE url={url}", flush=True)
        return 0

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
            temp_path = target_path.parent / f"{target_path.name}.{os.getpid()}.pull.tmp"
            temp_path.write_text(str(content), encoding="utf-8")
            os.replace(temp_path, target_path)
            written += 1
        except Exception as exc:
            print(f"[artifact_publisher] PULL_WRITE_FAILED path={normalized} error={exc}", flush=True)
            continue

    print(f"[artifact_publisher] PULL_OK url={url} artifacts_received={len(artifacts)} written={written}", flush=True)
    return written
