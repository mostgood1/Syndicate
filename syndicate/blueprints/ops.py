from __future__ import annotations

import fnmatch
import json
import os
import threading
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint
from flask import current_app
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import Response
from flask import url_for

from syndicate.features.shared.artifact_publisher import HOT_ARTIFACT_PATTERNS
from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path
from syndicate.features.shared.artifact_publisher import relative_to_data_root
from syndicate.features.shared.ops_refresh import build_refresh_plan
from syndicate.features.shared.ops_refresh import _assert_no_active_refresh_run
from syndicate.features.shared.ops_refresh import cancel_latest_refresh_run
from syndicate.features.shared.ops_refresh import launch_refresh_run
from syndicate.features.shared.ops_refresh import load_latest_refresh_log
from syndicate.features.shared.ops_refresh import load_latest_refresh_status
from syndicate.features.shared.refresh_state_store import data_root
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.timezone import normalize_timestamped_payload


ops_bp = Blueprint("ops", __name__)
_OPS_JOBS_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ops_jobs_path() -> Path:
    return reports_root() / "ops_jobs.json"


def _read_ops_jobs() -> dict[str, Any]:
    payload = read_json_file(_ops_jobs_path())
    return payload if isinstance(payload, dict) else {}


def _write_ops_jobs(jobs: dict[str, Any]) -> None:
    write_json_file(_ops_jobs_path(), jobs)


def _store_ops_job(job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    with _OPS_JOBS_LOCK:
        jobs = _read_ops_jobs()
        current = jobs.get(job_id)
        job = dict(current) if isinstance(current, dict) else {}
        job.update(updates)
        jobs[job_id] = job
        _write_ops_jobs(jobs)
        return job


def _job_current_step(payload: dict[str, Any]) -> str:
    sports_text = str(payload.get("sports") or "").strip().lower()
    if not sports_text or sports_text == "all":
        return "odds_refresh"
    first_sport = sports_text.replace("|", ",").split(",")[0].strip()
    return f"{first_sport}_refresh" if first_sport else "odds_refresh"


def _start_refresh_job(payload: dict[str, Any], *, mode: str = "fast") -> tuple[str, dict[str, Any]]:
    _assert_no_active_refresh_run()
    job_id = uuid.uuid4().hex
    launch_payload = dict(payload)
    launch_payload["mode"] = str(mode or "fast")
    initial_job = {
        "status": "running",
        "start_time": _utc_now(),
        "current_step": _job_current_step(launch_payload),
    }
    _store_ops_job(job_id, initial_job)
    try:
        result = launch_refresh_run(
            date=_payload_value(launch_payload, "date"),
            sports=_payload_value(launch_payload, "sports"),
            phase=_payload_value(launch_payload, "phase"),
            execution_mode=_payload_value(launch_payload, "execution_mode"),
            regions=_payload_value(launch_payload, "regions"),
            bookmakers=_payload_value(launch_payload, "bookmakers"),
            markets=_payload_value(launch_payload, "markets"),
            season=_coerce_int(_payload_value(launch_payload, "season")),
            week=_coerce_int(_payload_value(launch_payload, "week")),
            skip_mirror=_coerce_bool(_payload_value(launch_payload, "skip_mirror")),
            mirror_only=_coerce_bool(_payload_value(launch_payload, "mirror_only")),
            dry_run=_coerce_bool(_payload_value(launch_payload, "dry_run")),
            mode=str(_payload_value(launch_payload, "mode", "fast") or "fast"),
            force_refresh=_coerce_bool(_payload_value(launch_payload, "force_refresh")),
            launch_mode=_payload_value(launch_payload, "launch_mode"),
        )
    except Exception as exc:
        return job_id, _store_ops_job(
            job_id,
            {
                "status": "failed",
                "end_time": _utc_now(),
                "current_step": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            },
        )

    pid_raw = result.get("pid")
    pid = int(pid_raw) if isinstance(pid_raw, int) or (isinstance(pid_raw, str) and str(pid_raw).strip().isdigit()) else None
    state = str(result.get("state") or "").strip().lower()
    updates: dict[str, Any] = {"launch_result": result, "pid": pid, "current_step": initial_job["current_step"]}
    if state == "pending_external":
        updates["status"] = "running"
        updates["current_step"] = "pending_external"
    elif pid is None:
        updates["status"] = "done" if bool(result.get("ok")) else "failed"
        updates["end_time"] = _utc_now()
        updates["current_step"] = updates["status"]
    else:
        updates["status"] = "running"
    return job_id, _store_ops_job(job_id, updates)


def _git_value(repo_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    value = (completed.stdout or "").strip()
    return value or None


def _build_version_payload() -> dict[str, Any]:
    repo_root = Path(current_app.root_path).resolve().parent
    env_commit = str(
        os.environ.get("RENDER_GIT_COMMIT")
        or os.environ.get("GIT_COMMIT")
        or os.environ.get("SOURCE_VERSION")
        or ""
    ).strip()
    env_branch = str(
        os.environ.get("RENDER_GIT_BRANCH")
        or os.environ.get("GIT_BRANCH")
        or ""
    ).strip()

    git_commit = _git_value(repo_root, "rev-parse", "HEAD")
    git_branch = _git_value(repo_root, "rev-parse", "--abbrev-ref", "HEAD")

    commit = env_commit or git_commit
    branch = env_branch or git_branch
    commit_source = "env" if env_commit else "git" if git_commit else "unknown"
    branch_source = "env" if env_branch else "git" if git_branch else "unknown"

    return {
        "service": "syndicate",
        "commit": commit,
        "commit_source": commit_source,
        "branch": branch,
        "branch_source": branch_source,
        "render_service_name": str(os.environ.get("RENDER_SERVICE_NAME") or "").strip() or None,
        "render_instance_id": str(os.environ.get("RENDER_INSTANCE_ID") or "").strip() or None,
        "render_external_url": str(os.environ.get("RENDER_EXTERNAL_URL") or "").strip() or None,
        "syndicate_data_root": str(current_app.config.get("SYNDICATE_DATA_ROOT") or os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() or None,
        "syndicate_reports_root": str(current_app.config.get("SYNDICATE_REPORTS_ROOT") or os.environ.get("SYNDICATE_REPORTS_ROOT") or "").strip() or None,
    }


def _configured_admin_token() -> str:
    configured = current_app.config.get("ADMIN_TOKEN")
    if configured:
        return str(configured).strip()
    return str(os.environ.get("ADMIN_TOKEN") or os.environ.get("SYNDICATE_ADMIN_TOKEN") or "").strip()


def _request_admin_token() -> str:
    auth_header = str(request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    header_or_query = str(request.headers.get("X-Admin-Token") or request.args.get("admin_token") or "").strip()
    if header_or_query:
        return header_or_query
    return str(request.form.get("admin_token") or "").strip()


def _coerce_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_int(value: str | None) -> int | None:
    if value is None or not str(value).strip():
        return None
    return int(str(value).strip())


def _request_data() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else request.form


def _payload_value(payload: dict[str, Any], key: str, default: str | None = None) -> str | None:
    if key not in payload:
        return default
    value = payload.get(key)
    if value is None:
        return default
    return str(value)


@ops_bp.before_request
def _require_admin_token() -> Any:
    configured = _configured_admin_token()
    if not configured:
        return jsonify({"ok": False, "error": "ADMIN_TOKEN not configured."}), 503
    if _request_admin_token() != configured:
        return jsonify({"ok": False, "error": "Unauthorized."}), 401
    return None


@ops_bp.get("/api/ops/odds-refresh/status")
def api_ops_odds_refresh_status() -> Any:
    return jsonify({"ok": True, "status": normalize_timestamped_payload(load_latest_refresh_status())})


@ops_bp.get("/api/ops/version")
def api_ops_version() -> Any:
    return jsonify({"ok": True, "version": _build_version_payload()})


@ops_bp.get("/api/ops/memory")
def api_ops_memory() -> Any:
    # Read-only, same instrumentation the workers already use to diagnose OOMs
    # (2026-07-18/19 incidents) -- exposed here too so the web service's own
    # memory profile can be checked directly instead of guessed at when tuning
    # gunicorn --workers/--threads (each extra worker is a full extra process;
    # threads share memory with the existing worker process).
    from syndicate.features.shared.memory_observability import get_all_process_memory_snapshot

    return jsonify({"ok": True, "memory": get_all_process_memory_snapshot()})


@ops_bp.get("/api/ops/keyvalue/diagnostics")
def api_ops_keyvalue_diagnostics() -> Any:
    # Board audit follow-up, 2026-07-31: read-only Redis INFO stats for the
    # shared keyvalue backend (one Redis instance, "starter" plan, shared
    # across web + refresh-worker + live-odds-worker) -- built to answer,
    # with real numbers instead of guessing, whether WNBA's intermittent
    # dashboard_games_count=0 (and the same-instant zero seen across every
    # other sport in one refresh cycle) is memory-pressure eviction
    # (evicted_keys climbing), connection exhaustion (rejected_connections
    # climbing, connected_clients near a plan ceiling), or something else.
    from syndicate.features.shared.refresh_state_store import keyvalue_diagnostics

    diagnostics = keyvalue_diagnostics()
    if diagnostics is None:
        return jsonify({"ok": False, "error": "SYNDICATE_REFRESH_STATE_BACKEND is not keyvalue on this service."})
    return jsonify(diagnostics)


def _stale_after_days_param() -> int:
    raw = str(request.args.get("stale_after_days") or "").strip()
    try:
        value = int(raw) if raw else 2
    except ValueError:
        value = 2
    return max(1, value)


@ops_bp.get("/api/ops/keyvalue/sweep-preview")
def api_ops_keyvalue_sweep_preview() -> Any:
    # Board audit follow-up, 2026-07-31: read-only -- reports how many
    # date-scoped keys are stale (older than stale_after_days, default 10)
    # AND currently carry no TTL, i.e. exactly what api_ops_keyvalue_sweep
    # below would touch if called with the same stale_after_days. Mutates
    # nothing; safe to call any time to see the current backlog before
    # deciding whether/when to actually sweep it.
    from syndicate.features.shared.refresh_state_store import keyvalue_sweep_preview

    preview = keyvalue_sweep_preview(stale_after_days=_stale_after_days_param())
    if preview is None:
        return jsonify({"ok": False, "error": "SYNDICATE_REFRESH_STATE_BACKEND is not keyvalue on this service."})
    return jsonify(preview)


@ops_bp.get("/api/ops/mlb/betting-card-day")
def api_ops_mlb_betting_card_day() -> Any:
    # Read-only STRUCTURAL dump of the season betting-card day artifact --
    # the file syndicate/features/mlb/market_accuracy.py reads to produce
    # graded rows, and therefore the file evaluation_settlement joins ledger
    # records against.
    #
    # Added 2026-08-04 for one specific question: /mlb/api/market-accuracy
    # has returned zero graded rows on EVERY date for 16+ days (checked 5
    # hours after a slate went final, so not a timing artifact), which
    # leaves the whole evaluation loop unable to settle anything. The
    # artifact loads and parses fine, so the failure is inside it -- either
    # `games` is empty (never populated) or the games are present but carry
    # none of _ROW_SETS' settled-row fields (populated but never graded).
    # Those are different bugs in different places, and the web service
    # cannot read the worker's disk to tell them apart.
    #
    # Deliberately a SUMMARY, not the raw file: these artifacts are large,
    # and dumping one through an HTTP response is how you turn a diagnostic
    # into an outage.
    from syndicate.features.mlb.sources import season_betting_card_day_path

    date_str = str(request.args.get("date") or "").strip()
    if not date_str:
        return jsonify({"ok": False, "error": "date=YYYY-MM-DD is required."})
    profile = str(request.args.get("profile") or "retuned").strip() or "retuned"
    try:
        season = int(date_str[:4])
    except ValueError:
        return jsonify({"ok": False, "error": f"could not parse a season from date={date_str!r}"})

    path = season_betting_card_day_path(season, date_str, profile=profile)
    payload: dict[str, Any] = {
        "ok": True,
        "date": date_str,
        "season": season,
        "profile": profile,
        "path": str(path),
        "exists": path.exists(),
    }
    if not path.exists():
        payload["verdict"] = "artifact_missing"
        return jsonify(payload)

    try:
        payload["size_bytes"] = path.stat().st_size
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = f"{type(exc).__name__}: {exc}"
        return jsonify(payload)

    if not isinstance(parsed, dict):
        payload["verdict"] = "artifact_not_an_object"
        return jsonify(payload)

    row_fields = ("settled_rows", "playable_settled_rows", "all_settled_rows")
    payload["top_level_keys"] = sorted(parsed.keys())
    payload["has_results_block"] = isinstance(parsed.get("results"), dict)
    # `results`/`selected_counts` come straight off settled_card in
    # _static_day_payload, while `games` ALSO requires each row to carry a
    # positive game_pk (_season_betting_games_payload). So populated results
    # + empty games means rows exist but have no game_pk (fix the game_pk
    # join), whereas empty results + empty games means settled_card itself
    # is empty (fix is upstream, in the card/settlement step). Those are
    # different bugs, and "has_results_block" alone cannot tell them apart
    # because an empty dict is still a dict.
    for block in ("results", "playable_results", "all_results", "selected_counts", "summary"):
        value = parsed.get(block)
        if isinstance(value, dict):
            payload[f"{block}_keys"] = sorted(value.keys())[:12]
            payload[f"{block}_is_empty"] = not value
            payload[f"{block}_sample"] = json.dumps({k: value[k] for k in sorted(value.keys())[:4]})[:220]
        else:
            payload[f"{block}_is_empty"] = True
    games = parsed.get("games") if isinstance(parsed.get("games"), dict) else {}
    payload["games_count"] = len(games)

    totals = {field: 0 for field in row_fields}
    games_with_any_rows = 0
    sample_game: dict[str, Any] | None = None
    sample_row: dict[str, Any] | None = None
    for game_pk, game_payload in list(games.items()):
        if not isinstance(game_payload, dict):
            continue
        per_game = {field: len(game_payload.get(field) or []) if isinstance(game_payload.get(field), list) else 0 for field in row_fields}
        for field, count in per_game.items():
            totals[field] += count
        if any(per_game.values()):
            games_with_any_rows += 1
            if sample_row is None:
                for field in row_fields:
                    rows = game_payload.get(field)
                    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                        sample_row = {k: rows[0].get(k) for k in ("market", "selection", "result", "actual", "market_line", "odds", "profit_u", "stake_u")}
                        break
        if sample_game is None:
            sample_game = {"game_pk": str(game_pk), "keys": sorted(game_payload.keys())[:25], "row_counts": per_game}

    payload["row_totals"] = totals
    payload["games_with_any_rows"] = games_with_any_rows
    payload["sample_game"] = sample_game
    payload["sample_row"] = sample_row

    # The locked card is what the generator selects FROM. games is seeded by
    # _recommendations_by_game(card) before any settlement is joined, so an
    # empty games with zero selected_counts points here, not at the
    # generator. Proving it rather than inferring it: report the card's own
    # recommendation count.
    summary_block = parsed.get("summary") if isinstance(parsed.get("summary"), dict) else {}
    card_path_text = str(summary_block.get("card_path") or parsed.get("card_source") or "").strip()
    card_info: dict[str, Any] = {"path": card_path_text or None}
    if card_path_text:
        try:
            card_path = Path(card_path_text)
            card_info["exists"] = card_path.exists()
            if card_path.exists():
                card_info["size_bytes"] = card_path.stat().st_size
                card_doc = json.loads(card_path.read_text(encoding="utf-8"))
                if isinstance(card_doc, dict):
                    card_info["top_level_keys"] = sorted(card_doc.keys())[:20]
                    for key in ("recommendations", "playable_recommendations", "all_recommendations", "shadow_recommendations"):
                        value = card_doc.get(key)
                        if isinstance(value, (list, dict)):
                            card_info[f"{key}_count"] = len(value)
                    card_info["cap_profile"] = card_doc.get("cap_profile")
        except Exception as exc:
            card_info["error"] = f"{type(exc).__name__}: {exc}"
    payload["locked_card"] = card_info

    # The batch dir is the day payload's INPUT: daily_update.py resolves it
    # to <data>/eval/batches/season_{season}_ui_daily_live and hands it to
    # build_season_betting_cards_manifest.py as --batch-dir, which is what
    # populates `games`. Derived from the day-payload path rather than from
    # env vars so it follows whatever root this service actually resolved:
    # .../data/eval/seasons/<season>/betting_day_payloads_retuned/<file>
    #        ^parents[4] ^[3]  ^[2]    ^[1]   ^parents[0]
    try:
        eval_root = path.parents[3]
        batch_dir = eval_root / "batches" / f"season_{season}_ui_daily_live"
        batch: dict[str, Any] = {"path": str(batch_dir), "exists": batch_dir.is_dir()}
        if batch_dir.is_dir():
            # Both spellings appear across this pipeline (the day payload
            # file uses underscores, the batch report uses hyphens), so
            # check each rather than guess.
            for token in (date_str, date_str.replace("-", "_")):
                candidate = batch_dir / f"sim_vs_actual_{token}.json"
                if candidate.exists():
                    batch["sim_vs_actual"] = {"path": str(candidate), "exists": True, "size_bytes": candidate.stat().st_size}
                    try:
                        report = json.loads(candidate.read_text(encoding="utf-8"))
                        if isinstance(report, dict):
                            batch["sim_vs_actual"]["top_level_keys"] = sorted(report.keys())[:25]
                            for games_key in ("games", "rows", "results"):
                                value = report.get(games_key)
                                if isinstance(value, (list, dict)):
                                    batch["sim_vs_actual"][f"{games_key}_count"] = len(value)
                            # 633KB holding 2 games is the last unexplained
                            # number in the chain. Either the report covers
                            # only a slice of the slate, or `games` is not the
                            # per-game map its name implies -- the shape and a
                            # sample entry's keys tell them apart immediately.
                            # failures_n is checked in the same pass because a
                            # broad sim-failure count would explain a thin
                            # report outright.
                            games_value = report.get("games")
                            batch["sim_vs_actual"]["games_type"] = type(games_value).__name__
                            if isinstance(games_value, dict):
                                sample_keys = list(games_value.keys())[:6]
                                batch["sim_vs_actual"]["games_keys_sample"] = [str(k) for k in sample_keys]
                                if sample_keys:
                                    first = games_value.get(sample_keys[0])
                                    if isinstance(first, dict):
                                        batch["sim_vs_actual"]["games_entry_keys"] = sorted(first.keys())[:20]
                            elif isinstance(games_value, list) and games_value:
                                first = games_value[0]
                                if isinstance(first, dict):
                                    batch["sim_vs_actual"]["games_entry_keys"] = sorted(first.keys())[:20]
                            for scalar_key in ("failures_n", "failures", "n_games", "games_n", "requested_n", "completed_n", "skipped_n", "date", "season"):
                                scalar = report.get(scalar_key)
                                if isinstance(scalar, (int, float, str)):
                                    batch["sim_vs_actual"][scalar_key] = scalar
                                elif isinstance(scalar, (list, dict)):
                                    batch["sim_vs_actual"][f"{scalar_key}_count"] = len(scalar)
                            # meta.skipped_games is the last link: the report
                            # covers 2 games with failures_n = 0, so the other
                            # ~13 were SKIPPED, not failed. Its contents say
                            # why, which is the actual answer to "why is
                            # grading empty".
                            meta_block = report.get("meta")
                            if isinstance(meta_block, dict):
                                # source_sim_dir is what reconcile actually
                                # READ. sims-list reports a different root
                                # (source_artifacts), so the two can disagree
                                # -- comparing the dir's real file count
                                # against games_count says whether the input
                                # was thin or the tool dropped games.
                                sim_dir_text = str(meta_block.get("source_sim_dir") or "").strip()
                                if sim_dir_text:
                                    batch["sim_vs_actual"]["meta_source_sim_dir"] = sim_dir_text
                                    try:
                                        sim_dir = Path(sim_dir_text)
                                        batch["sim_vs_actual"]["source_sim_dir_exists"] = sim_dir.is_dir()
                                        if sim_dir.is_dir():
                                            sim_files = sorted(p.name for p in sim_dir.iterdir() if p.is_file())
                                            batch["sim_vs_actual"]["source_sim_dir_file_count"] = len(sim_files)
                                            batch["sim_vs_actual"]["source_sim_dir_sample"] = sim_files[:8]
                                            # The loop in reconcile appends to
                                            # `failures` on EVERY drop, so 8
                                            # paths -> 2 results with
                                            # failures_n 0 is impossible. The
                                            # only consistent story is that
                                            # glob saw 2 files. Comparing each
                                            # sim's mtime against the report's
                                            # generated_at proves whether the
                                            # other 6 were written afterwards
                                            # (a race) or were already there
                                            # (a real filter bug).
                                            import datetime as _dt

                                            stamps = []
                                            for name in sim_files:
                                                try:
                                                    mtime = (sim_dir / name).stat().st_mtime
                                                    stamps.append({
                                                        "file": name,
                                                        "mtime_local": _dt.datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
                                                    })
                                                except Exception:
                                                    continue
                                            stamps.sort(key=lambda row: row["mtime_local"])
                                            batch["sim_vs_actual"]["source_sim_mtimes"] = stamps
                                            generated_at = str(meta_block.get("generated_at") or "").strip()
                                            if generated_at and stamps:
                                                after = [row["file"] for row in stamps if row["mtime_local"] > generated_at]
                                                batch["sim_vs_actual"]["sims_written_after_report"] = len(after)
                                                batch["sim_vs_actual"]["sims_written_before_report"] = len(stamps) - len(after)
                                    except Exception as exc:
                                        batch["sim_vs_actual"]["source_sim_dir_error"] = f"{type(exc).__name__}: {exc}"
                                for meta_key in ("skipped_games", "jobs", "sims_per_game", "prop_lines_source", "date", "season", "generated_at", "tool", "use_raw"):
                                    meta_value = meta_block.get(meta_key)
                                    if isinstance(meta_value, (list, dict)):
                                        batch["sim_vs_actual"][f"meta_{meta_key}_count"] = len(meta_value)
                                        batch["sim_vs_actual"][f"meta_{meta_key}_sample"] = json.dumps(
                                            meta_value[:6] if isinstance(meta_value, list) else {k: meta_value[k] for k in list(meta_value.keys())[:6]},
                                            default=str,
                                        )[:600]
                                    elif meta_value is not None:
                                        batch["sim_vs_actual"][f"meta_{meta_key}"] = meta_value
                            for block_key in ("meta", "assessment", "summary"):
                                block = report.get(block_key)
                                if isinstance(block, dict):
                                    batch["sim_vs_actual"][f"{block_key}_keys"] = sorted(block.keys())[:15]
                                    batch["sim_vs_actual"][f"{block_key}_sample"] = json.dumps({k: block[k] for k in sorted(block.keys())[:6]}, default=str)[:300]
                    except Exception as exc:
                        batch["sim_vs_actual"]["parse_error"] = f"{type(exc).__name__}: {exc}"
                    break
            batch.setdefault("sim_vs_actual", {"exists": False, "looked_for": f"sim_vs_actual_{date_str}.json"})
            entries = sorted(p.name for p in batch_dir.iterdir() if p.is_file())
            batch["file_count"] = len(entries)
            batch["sample_files"] = entries[:12]
            batch["sim_vs_actual_file_count"] = sum(1 for name in entries if name.startswith("sim_vs_actual_"))
        payload["batch_dir"] = batch
    except Exception as exc:
        payload["batch_dir"] = {"error": f"{type(exc).__name__}: {exc}"}

    # The whole point of the endpoint: name which of the two failures it is.
    if not games:
        batch_info = payload.get("batch_dir") if isinstance(payload.get("batch_dir"), dict) else {}
        sim_vs_actual = batch_info.get("sim_vs_actual") if isinstance(batch_info.get("sim_vs_actual"), dict) else {}
        if not batch_info.get("exists"):
            payload["verdict"] = "games_empty + BATCH DIR MISSING -- the generator had no input directory at all"
        elif not sim_vs_actual.get("exists"):
            payload["verdict"] = "games_empty + no sim_vs_actual for this date -- the generator's per-date input was never written"
        else:
            payload["verdict"] = "games_empty BUT sim_vs_actual exists -- input is present, the generator is dropping it"
    elif sum(totals.values()) == 0:
        payload["verdict"] = "games_present_but_ungraded -- games exist, no settled-row fields populated"
    else:
        payload["verdict"] = "graded_rows_present -- grading works for this date; look downstream"
    return jsonify(payload)


@ops_bp.get("/api/ops/keyvalue/usage")
def api_ops_keyvalue_usage() -> Any:
    # Read-only. Estimated memory grouped by key bucket, plus the largest
    # individual keys. Added 2026-08-03 because the instance was at 230MB of
    # a 256MB ceiling with allkeys-lru already evicting, and sweep-preview
    # only accounts for stale TTL-less keys (183KB of that 230MB) -- it
    # could not say what actually held the memory. Upgrading the instance
    # is not an option, so reduction work needs this measurement first.
    from syndicate.features.shared.refresh_state_store import keyvalue_usage_by_prefix

    raw_top = str(request.args.get("top_keys") or "").strip()
    try:
        top_keys = int(raw_top) if raw_top else 15
    except ValueError:
        top_keys = 15
    usage = keyvalue_usage_by_prefix(top_keys=max(0, min(100, top_keys)))
    if usage is None:
        return jsonify({"ok": False, "error": "SYNDICATE_REFRESH_STATE_BACKEND is not keyvalue on this service."})
    return jsonify(usage)


@ops_bp.post("/api/ops/keyvalue/expire-run-artifacts")
def api_ops_keyvalue_expire_run_artifacts() -> Any:
    # Mutating. Force-expires OLD per-run diagnostic artifacts
    # (migration_runs/** by default) that already carry long TTLs, which
    # keyvalue_sweep can't touch since it only targets TTL-less keys.
    # Added 2026-08-03: those keys held 185.71MB of a 212.67MB total on a
    # 256MB instance already evicting coordination state under allkeys-lru,
    # and truncating new writes cannot reclaim the existing backlog.
    # Defaults to dry_run=1 so the blast radius is inspectable first; pass
    # ?dry_run=0 to actually apply.
    from syndicate.features.shared.refresh_state_store import keyvalue_expire_run_artifacts

    def _int_param(name: str, default: int) -> int:
        raw = str(request.args.get(name) or "").strip()
        try:
            return int(raw) if raw else default
        except ValueError:
            return default

    result = keyvalue_expire_run_artifacts(
        older_than_hours=max(1, _int_param("older_than_hours", 6)),
        grace_period_seconds=max(60, _int_param("grace_period_seconds", 300)),
        path_contains=str(request.args.get("path_contains") or "migration_runs").strip(),
        dry_run=_coerce_bool(request.args.get("dry_run"), default=True),
    )
    if result is None:
        return jsonify({"ok": False, "error": "SYNDICATE_REFRESH_STATE_BACKEND is not keyvalue on this service."})
    return jsonify(result)


@ops_bp.post("/api/ops/keyvalue/sweep")
def api_ops_keyvalue_sweep() -> Any:
    # Board audit follow-up, 2026-07-31: mutating -- sets a short
    # grace-period EXPIRE (default 1 hour, ?grace_period_seconds=) on every
    # stale (older than ?stale_after_days=, default 10), currently-TTL-less,
    # date-scoped key -- reclaiming the pre-existing backlog the TTL fix on
    # new writes (write_json_file/write_text_file) can't touch by itself.
    # Deliberately POST (not GET) since this mutates production state, and
    # deliberately EXPIRE rather than DELETE -- see
    # refresh_state_store.keyvalue_sweep_apply's own docstring.
    from syndicate.features.shared.refresh_state_store import keyvalue_sweep_apply

    grace_raw = str(request.args.get("grace_period_seconds") or "").strip()
    try:
        grace_period_seconds = int(grace_raw) if grace_raw else 3600
    except ValueError:
        grace_period_seconds = 3600
    grace_period_seconds = max(60, grace_period_seconds)

    result = keyvalue_sweep_apply(stale_after_days=_stale_after_days_param(), grace_period_seconds=grace_period_seconds)
    if result is None:
        return jsonify({"ok": False, "error": "SYNDICATE_REFRESH_STATE_BACKEND is not keyvalue on this service."})
    return jsonify(result)


@ops_bp.get("/api/ops/intelligence/memory-diagnostics")
def api_ops_intelligence_memory_diagnostics() -> Any:
    # /api/ops/memory above only ever reports the CALLING service's own
    # process -- no help for diagnosing refresh-worker's OOM crashes from
    # here, since refresh-worker runs no HTTP server at all. Temporary
    # diagnostic (2026-07-24 OOM incident): pipeline/intelligence_state.py's
    # _build_candidate_pool checkpoints write here via write_json_file/
    # read_json_file, which route through the same SYNDICATE_REFRESH_STATE_BACKEND=keyvalue
    # store both this web service and refresh-worker share -- confirmed
    # necessary because that background thread's own stdout/stderr doesn't
    # reliably reach the platform log collector before a SIGKILL once memory
    # pressure gets severe. Remove this endpoint once resolved.
    from pipeline.intelligence_state import _diag_memory_dump_path

    payload = read_json_file(_diag_memory_dump_path())
    records = list(payload.get("records") or []) if isinstance(payload, dict) else []
    return jsonify({"ok": True, "record_count": len(records), "records": records})


@ops_bp.get("/api/ops/board-snapshot/inspect")
def api_ops_board_snapshot_inspect() -> Any:
    # Read-only. Confirms (or refutes) the theory in todo.md's "OPEN
    # 2026-08-04 -- Ask the Syndicate can't reach game-market picks" entry:
    # that read_latest_intelligence_board_snapshot_response reads a single
    # shared "latest" board_snapshot.json slot, so whichever request last
    # got persisted into it (potentially with its own limit/sport
    # narrowing) determines the pool every OTHER caller inherits --
    # including Ask, on a totally unrelated request. Reports the raw
    # persisted payload's own recorded request_payload/limit/sport (if
    # any) plus a candidate_type/market breakdown of its recommendations,
    # so this can be answered directly instead of guessed at again.
    from pipeline.intelligence_state import BOARD_SNAPSHOT_PATH

    snapshot = read_json_file(BOARD_SNAPSHOT_PATH)
    if not isinstance(snapshot, dict):
        return jsonify({"ok": True, "path": str(BOARD_SNAPSHOT_PATH), "exists": False})

    response = snapshot.get("response") if isinstance(snapshot.get("response"), dict) else snapshot
    recommendations = response.get("recommendations") if isinstance(response.get("recommendations"), list) else []
    top_opportunities = response.get("top_opportunities") if isinstance(response.get("top_opportunities"), list) else []

    def _type_market_breakdown(items: list) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            key = f"{item.get('candidate_type') or item.get('type') or '?'} / {item.get('market') or item.get('market_type') or '?'}"
            counts[key] = counts.get(key, 0) + 1
        return counts

    return jsonify(
        {
            "ok": True,
            "path": str(BOARD_SNAPSHOT_PATH),
            "exists": True,
            "snapshot_top_level_keys": sorted(snapshot.keys()),
            "response_top_level_keys": sorted(response.keys()) if response is not snapshot else None,
            "recommendation_count": len(recommendations),
            "top_opportunities_count": len(top_opportunities),
            "recommendations_candidate_type_market_breakdown": _type_market_breakdown(recommendations),
            "top_opportunities_candidate_type_market_breakdown": _type_market_breakdown(top_opportunities),
            # If either of these is set on the persisted payload, that's
            # direct evidence the last-cached request narrowed the pool
            # before it was persisted (the theory) rather than the pool
            # genuinely only containing prop/steam candidates board-wide.
            "recorded_limit": response.get("limit") or response.get("requested_sport") if isinstance(response, dict) else None,
            "recorded_sport": response.get("requested_sport") or response.get("sport") if isinstance(response, dict) else None,
            "candidate_count_field": response.get("candidate_count") if isinstance(response, dict) else None,
            "selected_date": response.get("selected_date") if isinstance(response, dict) else None,
            "snapshot_generated_at": snapshot.get("updated_at") or response.get("snapshot_generated_at") if isinstance(response, dict) else snapshot.get("updated_at"),
        }
    )


@ops_bp.get("/api/ops/evaluation-settlement/status")
def api_ops_evaluation_settlement_status() -> Any:
    # Read-only. The evaluation-settlement autorun (run_refresh_worker.py)
    # only ever runs inside refresh-worker's own process and settles against
    # its own local evaluation ledger -- both invisible to this web service,
    # which has no disk access to refresh-worker's filesystem. Its per-cycle
    # totals (pending/matched/settled/unmatched) are written through the
    # shared keyvalue-backed refresh_state_store though (same path
    # run_refresh_worker.py's _evaluation_settlement_autorun_status_path()
    # writes to), so this is the only way from the web service to answer
    # "is settlement actually finding matches in production" instead of just
    # inferring it from a possibly-never-regenerated performance_summary.json.
    from syndicate.features.shared.evaluation_settlement import _SUPPORTED_SPORTS
    from pipeline.intelligence_state import _canonical_board_state_ledger_fingerprint_path

    status_path = reports_root() / "refresh_status" / "latest" / "evaluation_settlement_autorun_status.json"
    return jsonify(
        {
            "ok": True,
            "supported_sports": list(_SUPPORTED_SPORTS),
            "autorun_status": normalize_timestamped_payload(read_json_file(status_path)),
            # Direct evidence the write side (pipeline/intelligence_state.py's
            # maybe_record_board_state_to_evaluation_ledger, added 2026-08-03
            # to fix the root cause behind the totals above) actually ran and
            # persisted a ledger record for a given date -- a stored
            # fingerprint only gets written AFTER build_intelligence_evaluation_bundle
            # succeeds, so its presence is proof of a real write, not just that
            # a rebuild cycle happened. Keyvalue-backed like the status file
            # above, so readable here even though this endpoint runs on the
            # web service and recording itself only ever runs on refresh-worker
            # (not shown: whether the FLAG is on, since that's an env var local
            # to whichever service reads it -- checking it here would report
            # this web service's own value, not refresh-worker's).
            "board_state_ledger_recorded_fingerprints": read_json_file(_canonical_board_state_ledger_fingerprint_path()) or {},
        }
    )


@ops_bp.post("/api/ops/bootstrap/run")
def api_ops_bootstrap_run() -> Any:
    # Calls _sync_bootstrap_roots directly (not main(), which only ever
    # returns an exit code) so a real per-root file-copy count comes back in
    # the response -- confirmed 2026-08-02: main()'s "ok: true" doesn't rule
    # out one root silently failing (each root is try/excepted
    # independently, on purpose, so one root's failure can't hide the rest),
    # which made "did ncaaf_source's real files actually land on disk"
    # unanswerable from this endpoint's response alone. Verify by real
    # returned state, not by re-inferring from an unrelated page render.
    try:
        try:
            from pathlib import Path as _Path

            from scripts.bootstrap_data_root import _sync_bootstrap_roots  # type: ignore
        except Exception as exc:
            return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500
        repo_root = _Path(__file__).resolve().parents[2]
        root = data_root()
        counters = _sync_bootstrap_roots(repo_root, root)
        return jsonify({"ok": True, "message": "bootstrap completed", "repo_root": str(repo_root), "data_root": str(root), "counters": counters}), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500


@ops_bp.get("/api/ops/ncaaf/season-weeks")
def api_ops_ncaaf_season_weeks() -> Any:
    # Live diagnostic for exactly the class of bug hit 2026-08-02: real
    # smartsim2_projections_*.csv files confirmed present on disk (via the
    # bootstrap-run endpoint's own file counters) yet /ncaaf/api/cards kept
    # resolving to the old historical fallback. Surfaces every real value
    # the resolution chain depends on directly, so "which specific link is
    # wrong" is answerable from one request instead of another guess-and-
    # redeploy cycle.
    from syndicate.features.ncaaf.cards import _engine_seasons_and_weeks
    from syndicate.features.ncaaf.cards import _resolve_ncaaf_active_season_and_weeks
    from syndicate.features.ncaaf.cards import _smartsim2_standalone_seasons_and_weeks
    from syndicate.features.ncaaf.sources import default_ncaaf_source_root

    root = default_ncaaf_source_root()
    data_dir = root / "data"
    glob_matches = sorted(str(path) for path in data_dir.glob("smartsim2_projections_*_wk*.csv")) if data_dir.exists() else []
    active_season, active_weeks = _resolve_ncaaf_active_season_and_weeks()
    return jsonify(
        {
            "ok": True,
            "default_ncaaf_source_root": str(root),
            "data_dir": str(data_dir),
            "data_dir_exists": data_dir.exists(),
            "smartsim2_glob_match_count": len(glob_matches),
            "smartsim2_glob_matches_sample": glob_matches[:5],
            "smartsim2_standalone_seasons_and_weeks": _smartsim2_standalone_seasons_and_weeks(),
            "engine_seasons_and_weeks": _engine_seasons_and_weeks(),
            "resolved_active_season": active_season,
            "resolved_active_weeks": active_weeks,
        }
    )


@ops_bp.post("/api/ops/artifacts/publish")
def api_ops_artifacts_publish() -> Any:
    payload = _request_data()
    relative_path = str(payload.get("relative_path") or "").strip().replace("\\", "/")
    content = payload.get("content")
    if not relative_path or content is None:
        return jsonify({"ok": False, "error": "relative_path and content are required."}), 400
    if relative_path.startswith("/") or ".." in relative_path.split("/"):
        return jsonify({"ok": False, "error": "invalid relative_path."}), 400
    if not is_hot_artifact_relative_path(relative_path):
        return jsonify({"ok": False, "error": "relative_path is not an allowed hot artifact."}), 403

    target_path = data_root() / Path(relative_path)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.parent / f"{target_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        temp_path.write_text(str(content), encoding="utf-8")
        os.replace(temp_path, target_path)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    return jsonify({"ok": True, "relative_path": relative_path, "bytes": target_path.stat().st_size}), 200


@ops_bp.get("/api/ops/artifacts/export")
def api_ops_artifacts_export() -> Any:
    # Phase 4 of migrating off the daily-update GHA cron: read-only
    # counterpart to /api/ops/artifacts/publish above. The GHA runner has no
    # filesystem access to any Render disk, so this lets the reduced
    # backup-only workflow pull the current hot-artifact set back down over
    # HTTP and git-commit it as a cold-start safety net, instead of
    # regenerating everything by re-running the full pipeline. Scoped to the
    # exact same allowlist as the publish endpoint -- never returns
    # bulk/historical data.
    #
    # Optional filters (both stay allowlist-scoped):
    #   ?path=<relative_path>     exact single artifact
    #   ?pattern=<fnmatchglob>    subset of the hot-artifact set
    #   ?since=<epoch_seconds>    skip files not modified since this time --
    #     mirrors sweep_changed_hot_artifacts' own mtime-watermark check on
    #     the push side (artifact_publisher.py), so the pull side (which had
    #     none) can skip re-fetching files the caller already has. Confirmed
    #     in production: this endpoint was serving 8.6-28.9MB responses every
    #     ~30s to a single caller (the intelligence-state background loop's
    #     hot-artifact pull), the overwhelming majority of it unchanged since
    #     the caller's own last successful pull.
    # Exporting everything at once can exceed Render's proxy timeout (502),
    # so callers debugging a single artifact should always pass ?path=.
    root = data_root()
    since_raw = str(request.args.get("since") or "").strip()
    since_epoch: float | None = None
    if since_raw:
        try:
            since_epoch = float(since_raw)
        except ValueError:
            since_epoch = None
    exact_path = str(request.args.get("path") or "").strip().replace("\\", "/")
    if exact_path:
        if exact_path.startswith("/") or ".." in exact_path.split("/"):
            return jsonify({"ok": False, "error": "invalid path."}), 400
        if not is_hot_artifact_relative_path(exact_path):
            return jsonify({"ok": False, "error": "path is not an allowed hot artifact."}), 403
        target = root / Path(exact_path)
        if not target.is_file():
            return jsonify({"ok": True, "count": 0, "artifacts": {}})
        try:
            if since_epoch is not None and target.stat().st_mtime < since_epoch:
                return jsonify({"ok": True, "count": 0, "artifacts": {}})
            return jsonify({"ok": True, "count": 1, "artifacts": {exact_path: target.read_text(encoding="utf-8")}})
        except Exception as exc:
            return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    subset_pattern = str(request.args.get("pattern") or "").strip().replace("\\", "/")
    artifacts: dict[str, str] = {}
    # Hard byte ceiling on one response (#50). This handler accumulates whole
    # file contents into a dict and serialises it, so an unbounded matched set
    # is unbounded memory on a 2GB web instance -- and the client
    # (artifact_publisher) json.loads() the whole thing, so it is unbounded on
    # the worker too. On 2026-07-25 that combination produced a refresh-worker
    # OOM crash loop and cascading web 502s that took every route down.
    #
    # Truncation is REPORTED, never silent: the puller only advances its
    # watermark on a complete response, so a caller that cannot see it was
    # truncated would skip the remainder forever.
    budget_bytes = _artifact_export_budget_bytes()
    total_bytes = 0
    truncated = False
    for pattern in HOT_ARTIFACT_PATTERNS:
        if truncated:
            break
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            relative_path = relative_to_data_root(path)
            if not relative_path or not is_hot_artifact_relative_path(relative_path):
                continue
            if subset_pattern and not fnmatch.fnmatch(relative_path, subset_pattern):
                continue
            try:
                stat = path.stat()
                if since_epoch is not None and stat.st_mtime < since_epoch:
                    continue
                if total_bytes + stat.st_size > budget_bytes and artifacts:
                    # Stop before reading, not after -- reading it is the
                    # memory we are trying not to spend.
                    truncated = True
                    break
                artifacts[relative_path] = path.read_text(encoding="utf-8")
                total_bytes += stat.st_size
            except Exception:
                continue
    return jsonify({
        "ok": True,
        "count": len(artifacts),
        "truncated": truncated,
        "bytes": total_bytes,
        "artifacts": artifacts,
    })


def _artifact_export_budget_bytes() -> int:
    # 24MB default: comfortably above a normal incremental pull (the
    # watermark keeps those small) and far below what put a 2GB instance
    # near its ceiling. Tunable without a deploy during an incident.
    raw = str(os.environ.get("SYNDICATE_ARTIFACT_EXPORT_MAX_BYTES") or "").strip()
    try:
        value = int(raw or 24 * 1024 * 1024)
    except ValueError:
        value = 24 * 1024 * 1024
    return max(1024 * 1024, value)


@ops_bp.get("/api/ops/oddsapi/quota")
def api_ops_oddsapi_quota() -> Any:
    # Ground truth for OddsAPI credit burn, straight from the counters the
    # vendor bills against (x-requests-used / -remaining). Every cadence
    # decision so far has been made against an ESTIMATE -- notably "MLB alone
    # is ~585 credits/sweep at 60s ticks, so ~6.3M/month against a 5M
    # budget". This is how that gets checked before #15 tunes anything.
    from syndicate.features.shared.oddsapi_quota import read_oddsapi_quota

    return jsonify({"ok": True, "quota": normalize_timestamped_payload(read_oddsapi_quota())})


@ops_bp.post("/api/ops/oddsapi/quota/reset")
def api_ops_oddsapi_quota_reset() -> Any:
    # Protected endpoint: requires admin token (enforced by before_request)
    # #106/#107. by_sport/by_market_family/by_hour_utc never reset (O(1)
    # counters, #54's constraint), so a real early bug that's since been
    # fixed (c01302f1 -> 6e98ae80, the endpoint-query-stripping bug that
    # made attribution blind for part of this aggregation window) stays
    # baked into the cumulative ratio forever, diluting only as slowly as
    # new data accumulates. Confirmed 2026-07-28: every incremental delta
    # since has matched exactly (100% attribution), so the fix is already
    # live -- this just gives the reported ratio a clean baseline to
    # measure from instead of carrying broken history indefinitely.
    # credits_burned_in_window is unaffected: it's derived from the
    # provider's absolute used-counter delta, not from this file.
    from syndicate.features.shared.oddsapi_quota import _quota_path

    path = _quota_path()
    write_json_file(path, {})
    return jsonify({"ok": True, "path": str(path)})


@ops_bp.get("/api/ops/live-refresh/state")
def api_ops_live_refresh_state() -> Any:
    # Read-only view of the live-refresh loop's shared state (tick meta, gate
    # checks). Written by the live-odds-worker through the Redis-backed
    # refresh-state store, so the web service can serve it without sharing a
    # disk -- this is the only way to see WHY the worker's MLB daily-sim /
    # look-ahead gates did or didn't fire on a given tick.
    from syndicate.features.shared.refresh_state_store import read_json_file as _state_read_json
    from syndicate.features.shared.refresh_state_store import read_text_file as _state_read_text
    from syndicate.features.shared.refresh_state_store import reports_root as _state_reports_root

    base = _state_reports_root() / "live_refresh_loop"
    state = {
        "latest_tick": _state_read_json(base / "latest_live_refresh_tick.json"),
        "loop_status": _state_read_json(base / "live_refresh_loop_status.json"),
        "last_mlb_sim_check": _state_read_json(base / "last_mlb_sim_check.json"),
        "last_look_ahead_check": _state_read_json(base / "last_look_ahead_check.json"),
    }
    sim_base = base / "mlb_sim_runs"
    run_stamp = str(request.args.get("sim_run") or "").strip()
    sim_date = str(request.args.get("sim_date") or "").strip()

    # Resolving sim_run used to be the caller's problem: both params were
    # required, and passing only sim_date returned a payload with
    # "sim_run_status" simply ABSENT -- indistinguishable from "no sim is
    # running". The run stamp is minted inside _launch_mlb_daily_sim and only
    # ever printed to the worker log, so the one documented way to inspect a
    # sim required grepping Render's logs first. Fall back to the shared
    # pointers instead, and always report which run was resolved and from
    # where so an empty status is never ambiguous again.
    resolution = {"run_stamp": run_stamp or None, "date": sim_date or None, "source": "request" if run_stamp else None}
    if not run_stamp:
        # _active.json is the live run; it is reset to {} on completion, so an
        # empty/missing payload means "nothing running" and we fall through to
        # _last_attempt.json, which is written at launch and never cleared and
        # therefore still identifies the most recent finished run.
        for pointer_name, source in (("_active.json", "active_pointer"), ("_last_attempt.json", "last_attempt")):
            pointer = _state_read_json(sim_base / pointer_name)
            if not isinstance(pointer, dict):
                continue
            candidate_stamp = str(pointer.get("run_stamp") or "").strip()
            if not candidate_stamp:
                continue
            candidate_date = str(pointer.get("date") or "").strip()
            if sim_date and candidate_date and candidate_date != sim_date:
                # Caller asked about a specific date; don't answer with another one.
                continue
            run_stamp = candidate_stamp
            sim_date = sim_date or candidate_date
            resolution = {"run_stamp": run_stamp, "date": sim_date or None, "source": source}
            break

    state["sim_run_resolution"] = resolution
    if run_stamp and sim_date:
        state["sim_run_status"] = _state_read_json(sim_base / f"{sim_date}_{run_stamp}_status.json")
        # Written every _progress_poll_interval_seconds() while the run is
        # still in flight (run_mlb_daily_sim_job.py) -- absent for a run
        # older than this feature, present-but-stale ("updated_at" far in
        # the past relative to now) is the signal a "running" state is
        # actually hung, not the earlier all-or-nothing "no news for 90
        # minutes" state this replaces.
        state["sim_run_progress"] = _state_read_json(sim_base / f"{sim_date}_{run_stamp}_progress.json")
        log_text = _state_read_text(sim_base / f"{sim_date}_{run_stamp}.log")
        if log_text:
            # Combined stdout+stderr of the sim subprocess; tail is where the
            # traceback lives. Bounded to keep the response reasonable.
            state["sim_run_log_tail"] = log_text[-8000:]
    return jsonify({"ok": True, "state": normalize_timestamped_payload(state)})


@ops_bp.post("/api/ops/live-refresh/force-mlb-resim")
def api_ops_live_refresh_force_mlb_resim() -> Any:
    # Ops lever: invalidate the MLB daily-sim gate's stored fingerprint for
    # specific game(s) so the live-odds-worker's next tick fires a scoped
    # fingerprint_change launch for exactly those games -- without waiting for
    # a real lineup change or the tip-off window (e.g. after an OOM stranded a
    # completed-but-unpublished run on the worker disk).
    #
    # 2026-07-19 incident: the old version of this endpoint wrote a single
    # "fingerprint" marker string (pre-migration schema). The gate can't tell
    # WHICH game changed from a non-dict record, so it fell back to "resim the
    # whole slate" -- a 45-55min run, exactly what per-game scoping exists to
    # avoid. Worse, if called more than once, each call queued another
    # full-slate resim behind the current one, chaining for hours. game_pks is
    # now required, and only those games' stored hashes are invalidated --
    # every other game's real current hash is preserved so it reads
    # "unchanged" next tick, keeping the launch scoped through the normal
    # per-game diff path.
    from syndicate.features.shared.live_refresh_loop import _mlb_sim_input_fingerprint_by_game
    from syndicate.features.shared.live_refresh_loop import _read_last_mlb_sim_check
    from syndicate.features.shared.live_refresh_loop import _record_mlb_sim_check
    from syndicate.features.shared.schedule_adapter import fetch_schedule_for_date
    from syndicate.features.shared.timezone import central_today_iso

    date_str = str(request.args.get("date") or "").strip() or central_today_iso()
    game_pks_raw = str(request.args.get("game_pks") or "").strip()
    if not game_pks_raw:
        return jsonify({
            "ok": False,
            "error": "game_pks query param required (comma-separated game_pk values). "
                     "This endpoint no longer force-resims the whole slate -- pass the specific game(s) that need it.",
        }), 400
    requested_game_pks = {piece.strip() for piece in game_pks_raw.split(",") if piece.strip()}

    try:
        events = fetch_schedule_for_date("mlb", date_str)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"failed to load schedule: {type(exc).__name__}: {exc}"}), 500
    if not events:
        return jsonify({"ok": False, "error": f"no MLB games scheduled for {date_str}"}), 404

    known_game_pks = {str(event.event_id).strip() for event in events if str(event.event_id or "").strip()}
    unknown_game_pks = requested_game_pks - known_game_pks
    if unknown_game_pks:
        return jsonify({"ok": False, "error": f"game_pks not on {date_str}'s slate: {sorted(unknown_game_pks)}"}), 400

    current_fingerprints = _mlb_sim_input_fingerprint_by_game(date_str, events)
    last = _read_last_mlb_sim_check()
    stored_fingerprints = last.get("fingerprints") if str(last.get("date") or "") == date_str else None
    if not isinstance(stored_fingerprints, dict):
        stored_fingerprints = {}

    marker_suffix = f"|forced-resim:{datetime.now(timezone.utc).isoformat(timespec='seconds')}"
    next_fingerprints = dict(current_fingerprints)
    for game_pk in requested_game_pks:
        # Guaranteed to differ from the plain hash _mlb_daily_sim_decision computes
        # next tick, so only these game(s) show as changed -- every other key above
        # already holds its real current hash and will correctly read "unchanged".
        next_fingerprints[game_pk] = (stored_fingerprints.get(game_pk) or "") + marker_suffix

    _record_mlb_sim_check(1.0, date_str, next_fingerprints, launched=False)
    return jsonify({
        "ok": True,
        "date": date_str,
        "game_pks": sorted(requested_game_pks),
        "note": "next live-odds-worker tick will launch scoped to exactly these game(s) via reason=fingerprint_change (once no sim is already active)",
    })


@ops_bp.get("/api/ops/mlb/sims-list")
def api_ops_mlb_sims_list() -> Any:
    # Protected endpoint: requires admin token (enforced by before_request)
    date = str(request.args.get("date") or "").strip()
    if not date:
        return jsonify({"ok": False, "error": "date parameter required (YYYY-MM-DD)"}), 400
    try:
        from syndicate.features.mlb import sources as mlb_sources
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500

    # Build candidate roots similar to sources.daily_sim_artifact_path
    repo_root = Path(current_app.root_path).resolve().parent
    roots: list[Path] = []
    env_value = str(os.environ.get("SYNDICATE_MLB_SOURCE_ROOT") or "").strip()
    if env_value:
        roots.append(Path(env_value))
    data_root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    if data_root:
        roots.append(Path(data_root).resolve() / "mlb_source")
    roots.append(repo_root / "data" / "mlb_source")

    results = []
    rel = Path("data", "daily", "sims", date)
    for root in roots:
        try:
            cand = root
            # check both root and root/source_artifacts
            for probe in (cand, cand / "source_artifacts"):
                if not probe.exists() or not probe.is_dir():
                    continue
                sims_dir = (probe / rel)
                if not sims_dir.exists() or not sims_dir.is_dir():
                    continue
                files = [p.name for p in sorted(sims_dir.glob("*.json")) if p.is_file()]
                results.append({"root": str(probe), "count": len(files), "files": files[:200]})
        except Exception:
            continue

    return jsonify({"ok": True, "date": date, "results": results})


def _inspect_artifact_path(path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": str(path), "exists": path.exists() and path.is_file()}
    if not entry["exists"]:
        return entry
    try:
        entry["size_bytes"] = path.stat().st_size
        if path.suffix == ".csv":
            with path.open("r", encoding="utf-8", newline="") as handle:
                line_count = sum(1 for _ in handle)
            entry["data_rows"] = max(0, line_count - 1)
        elif path.suffix == ".json":
            import json as _json

            payload = _json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                data_value = payload.get("data") if payload.get("data") is not None else payload.get("per_game")
                entry["data_rows"] = len(data_value) if isinstance(data_value, list) else None
                entry["top_level_keys"] = sorted(payload.keys())[:20]
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"
    return entry


@ops_bp.post("/api/ops/live-refresh-loop/reset-lineup-gate")
def api_ops_reset_lineup_gate() -> Any:
    # Protected endpoint: requires admin token (enforced by before_request)
    # Clears the shared (keyvalue-backed) "last lineup/injury check" state that
    # gates when live-odds-worker's background loop is allowed to force a
    # smart-sim recompute (see _should_force_sim_rerun in live_refresh_loop.py).
    # An empty stored fingerprint set unconditionally reads as "changed" on the
    # next tick, so this forces that loop to recompute+republish on its next
    # cycle without waiting for an actual roster/injury change to be detected.
    path = reports_root() / "live_refresh_loop" / "last_lineup_check.json"
    write_json_file(path, {})
    return jsonify({"ok": True, "path": str(path)})


@ops_bp.get("/api/ops/odds-history/inspect")
def api_ops_odds_history_inspect() -> Any:
    # Protected endpoint: requires admin token (enforced by before_request).
    # Read-only diagnostic for a real symptom (confirmed live 2026-07-29):
    # several distinct WNBA prop candidates in the same game showed the
    # identical line_odds_movement (opening_line/latest_line/history) despite
    # having distinct, correctly-computed market_id values. reports/odds_control_plane/odds_history/*
    # isn't in artifact_publisher's HOT_ARTIFACT_PATTERNS allowlist (that
    # list is for cross-service sync, not debugging), so there was no way to
    # see the raw payload's actual `markets` dict shape to confirm whether
    # multiple keys collapse onto the same stored object (a write-side
    # collision) versus a read-side join bug. Returns a per-market_id summary
    # (never the full raw history array, to keep the response small) so a
    # collision -- multiple different requested/stored market_ids sharing
    # identical opening/latest line+price -- is visible at a glance.
    sport = str(request.args.get("sport") or "").strip().lower()
    date = str(request.args.get("date") or "").strip()
    if not sport or not date:
        return jsonify({"ok": False, "error": "sport and date parameters required (date as YYYY-MM-DD)."}), 400
    market_id_filter = str(request.args.get("market_id") or "").strip() or None
    try:
        from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport
        from syndicate.features.shared.odds_control_plane import odds_history_path_status_for_sport
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500

    path_status = odds_history_path_status_for_sport(sport, date)
    payload = load_odds_history_payload_for_sport(sport, date)
    if not isinstance(payload, dict):
        return jsonify({"ok": True, "sport": sport, "date": date, "path_status": path_status, "markets": None, "market_count": 0})

    markets = payload.get("markets")
    if not isinstance(markets, dict):
        return jsonify({"ok": True, "sport": sport, "date": date, "path_status": path_status, "markets": None, "market_count": 0})

    summaries: dict[str, Any] = {}
    seen_object_ids: dict[int, list[str]] = {}
    content_signatures: dict[tuple[Any, ...], list[str]] = {}
    for key, value in markets.items():
        if market_id_filter and key != market_id_filter and not (isinstance(value, dict) and str(value.get("market_id") or "") == market_id_filter):
            continue
        if not isinstance(value, dict):
            continue
        history = value.get("history") if isinstance(value.get("history"), list) else []
        summaries[key] = {
            "stored_market_id": value.get("market_id"),
            "last_line": value.get("last_line"),
            "last_odds": value.get("last_odds"),
            "history_points": len(history),
            "history_first": history[0] if history else None,
            "history_last": history[-1] if history else None,
            "is_live": value.get("is_live"),
            "closing_line": value.get("closing_line"),
            "closing_price": value.get("closing_price"),
            "closing_captured_at": value.get("closing_captured_at"),
        }
        seen_object_ids.setdefault(id(value), []).append(key)
        # id()-based collision only catches a shared in-memory reference within
        # THIS process -- useless once the payload has round-tripped through
        # JSON on disk, where a write-side bug that produced identical content
        # under different keys shows up as separate objects with equal values,
        # not equal identity. history_points alone would false-positive on two
        # genuinely-untouched (0-point) markets, so require at least one point.
        if history:
            signature = (value.get("last_line"), value.get("last_odds"), len(history), json.dumps(history[0], sort_keys=True, default=str), json.dumps(history[-1], sort_keys=True, default=str))
            content_signatures.setdefault(signature, []).append(key)

    identity_collisions = {obj_id: keys for obj_id, keys in seen_object_ids.items() if len(keys) > 1}
    content_collisions = {i: keys for i, keys in enumerate(sig_keys for sig_keys in content_signatures.values() if len(sig_keys) > 1)}
    return jsonify(
        {
            "ok": True,
            "sport": sport,
            "date": date,
            "path_status": path_status,
            "market_count": len(markets),
            "returned_count": len(summaries),
            "markets": summaries,
            # Non-empty only if the SAME in-memory dict object is stored under
            # multiple distinct keys -- a shared-mutable reference bug caught
            # within this one process's memory.
            "shared_object_collisions": {str(obj_id): keys for obj_id, keys in identity_collisions.items()},
            # Non-empty if multiple DIFFERENT market_id keys have byte-identical
            # last_line/last_odds/history endpoints -- the real signal for a
            # write-side key collision that already happened before this read,
            # survives a JSON round-trip, and is what actually explains the
            # live symptom (several distinct props showing one shared movement).
            "content_collisions": {str(i): keys for i, keys in content_collisions.items()},
        }
    )


@ops_bp.get("/api/ops/wnba/artifact-counts")
def api_ops_wnba_artifact_counts() -> Any:
    # Protected endpoint: requires admin token (enforced by before_request)
    date = str(request.args.get("date") or "").strip()
    if not date:
        return jsonify({"ok": False, "error": "date parameter required (YYYY-MM-DD)"}), 400
    try:
        from syndicate.features.shared.source_roots import preferred_artifact_roots
        from syndicate.features.wnba.sources import processed_root as wnba_processed_root
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500

    # processed_root() unconditionally prefers a "source_artifacts" candidate
    # root whether or not that location actually has anything written to it,
    # so report every candidate root's status rather than just the first one
    # -- that mismatch is exactly what made this endpoint necessary.
    candidate_roots = [
        candidate / "data" / "processed"
        for candidate in preferred_artifact_roots(__file__, env_var="SYNDICATE_WNBA_SOURCE_ROOT", local_dir_name="wnba_source")
    ]
    file_names = [
        f"game_cards_{date}.csv",
        f"props_edges_{date}.csv",
        f"props_predictions_{date}.csv",
        f"props_recommendations_{date}.csv",
        f"props_recommendations_top_by_game_{date}.json",
        f"recommendations_slate_{date}.json",
    ]
    results: dict[str, Any] = {}
    for file_name in file_names:
        results[file_name] = [
            {"root": str(root), "is_processed_root_default": root == wnba_processed_root(), **_inspect_artifact_path(root / file_name)}
            for root in candidate_roots
        ]

    return jsonify(
        {
            "ok": True,
            "date": date,
            "processed_root": str(wnba_processed_root()),
            "candidate_roots": [str(root) for root in candidate_roots],
            "results": results,
        }
    )


@ops_bp.get("/api/ops/wnba/live-lines-export-diag")
def api_ops_wnba_live_lines_export_diag() -> Any:
    # Protected endpoint: requires admin token (enforced by before_request)
    # Found live 2026-08-01: every print() diagnostic added inside
    # scripts/refresh_wnba_oddsapi_props.py's main() is unobservable for a
    # successful run -- refresh_odds_sources.py's _run_command runs this
    # whole script via subprocess.run(capture_output=True), and a
    # successful step's captured stdout is discarded entirely (only a
    # bounded stderr tail survives for a FAILED step). That script now
    # writes a small _live_lines_export_diag.json state file through the
    # keyvalue-aware write_json_file instead, so this endpoint reads it
    # back through the same backend (read_json_file, NOT the filesystem-
    # only /api/ops/artifacts/export, which can never see a keyvalue-only
    # write) -- this is the only way to observe whether that step's
    # _export_live_snapshot_artifacts call actually ran and what it wrote.
    try:
        from syndicate.features.shared.source_roots import preferred_artifact_roots
        from syndicate.features.wnba.sources import processed_root as wnba_processed_root
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500

    candidate_roots = [
        candidate / "data" / "processed"
        for candidate in preferred_artifact_roots(__file__, env_var="SYNDICATE_WNBA_SOURCE_ROOT", local_dir_name="wnba_source")
    ]
    results = [
        {
            "root": str(root),
            "is_processed_root_default": root == wnba_processed_root(),
            "payload": read_json_file(root / "_live_lines_export_diag.json"),
        }
        for root in candidate_roots
    ]
    return jsonify({"ok": True, "candidate_roots": [str(root) for root in candidate_roots], "results": results})


@ops_bp.get("/api/ops/wnba/live-lines-raw")
def api_ops_wnba_live_lines_raw() -> Any:
    # Protected endpoint: requires admin token (enforced by before_request)
    # The export-diag endpoint above only shows what the writer script
    # COMPUTED (source_payload_games) -- it doesn't prove that content
    # actually landed in the real live_lines_<date>.jsonl snapshot file
    # cards.py reads at request time. Reads the raw keyvalue-stored text
    # for that file directly, across every candidate root, bypassing all
    # of build_live_lines_payload's merge/fallback logic entirely -- the
    # most direct way to tell a write-side gap from a read-side one.
    date = str(request.args.get("date") or "").strip()
    if not date:
        return jsonify({"ok": False, "error": "date parameter required (YYYY-MM-DD)"}), 400
    try:
        from syndicate.features.shared.refresh_state_store import read_text_file as _state_read_text
        from syndicate.features.shared.source_roots import preferred_artifact_roots
        from syndicate.features.wnba.sources import processed_root as wnba_processed_root
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500

    candidate_roots = [
        candidate / "data" / "processed"
        for candidate in preferred_artifact_roots(__file__, env_var="SYNDICATE_WNBA_SOURCE_ROOT", local_dir_name="wnba_source")
    ]
    file_name = f"live_lines_{date}.jsonl"
    results = []
    for root in candidate_roots:
        path = root / "live_snapshots" / file_name
        raw_text = _state_read_text(path)
        parsed_lines = []
        for line in (raw_text or "").splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                parsed_lines.append(json.loads(raw))
            except Exception as exc:
                parsed_lines.append({"parse_error": f"{type(exc).__name__}: {exc}"})
        results.append(
            {
                "root": str(path),
                "is_processed_root_default": root == wnba_processed_root(),
                "raw_text_length": len(raw_text) if raw_text is not None else None,
                "line_count": len(parsed_lines),
                "last_record": parsed_lines[-1] if parsed_lines else None,
            }
        )
    return jsonify({"ok": True, "date": date, "results": results})


@ops_bp.get("/api/ops/wnba/status-trace")
def api_ops_wnba_status_trace() -> Any:
    # Protected endpoint: requires admin token (enforced by before_request)
    date = str(request.args.get("date") or "").strip()
    if not date:
        return jsonify({"ok": False, "error": "date parameter required (YYYY-MM-DD)"}), 400
    try:
        from syndicate.features.wnba import cards as wnba_cards
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500

    def _summarize_games(games: Any) -> Any:
        if not isinstance(games, list):
            return games
        out = []
        for game in games:
            if not isinstance(game, dict):
                continue
            out.append(
                {
                    "event_id": game.get("event_id"),
                    "away_tri": game.get("away_tri"),
                    "home_tri": game.get("home_tri"),
                    "status": game.get("status"),
                    "detail": game.get("detail"),
                    "live_state": game.get("live_state"),
                }
            )
        return out

    trace: dict[str, Any] = {"ok": True, "date": date}
    try:
        trace["render_web_dyno"] = wnba_cards._render_web_dyno()
    except Exception as exc:
        trace["render_web_dyno_error"] = f"{type(exc).__name__}: {exc}"
    try:
        trace["local_live_state_payload"] = wnba_cards._local_live_state_payload(date)
    except Exception as exc:
        trace["local_live_state_payload_error"] = f"{type(exc).__name__}: {exc}"
    try:
        live_games, live_source_path = wnba_cards._games_from_live_state_fallback(date)
        trace["games_from_live_state_fallback"] = {"source_path": live_source_path, "games": _summarize_games(live_games)}
    except Exception as exc:
        trace["games_from_live_state_fallback_error"] = f"{type(exc).__name__}: {exc}"
    try:
        artifact_games, cards_path, _recs_path = wnba_cards._games_from_artifacts(date)
        trace["games_from_artifacts"] = {"source_path": str(cards_path), "games": _summarize_games(artifact_games)}
    except Exception as exc:
        trace["games_from_artifacts_error"] = f"{type(exc).__name__}: {exc}"
    try:
        cards_context = wnba_cards.build_cards_page_context(date, allow_stored_date_fallback=False)
        trace["build_cards_page_context_games"] = _summarize_games(cards_context.get("games"))
        trace["build_cards_page_context_source_path"] = cards_context.get("source_path")
    except Exception as exc:
        trace["build_cards_page_context_error"] = f"{type(exc).__name__}: {exc}"
    try:
        source_payload = wnba_cards.build_source_cards_payload(date, allow_stored_date_fallback=False)
        trace["build_source_cards_payload_games"] = _summarize_games(source_payload.get("games"))
    except Exception as exc:
        trace["build_source_cards_payload_error"] = f"{type(exc).__name__}: {exc}"

    return jsonify(trace)


@ops_bp.get("/api/ops/intelligence/candidate-trace")
def api_ops_intelligence_candidate_trace() -> Any:
    # Protected endpoint: requires admin token. Diagnostic-only: exercises the
    # exact same build_intelligence_overview -> collect_candidates path the
    # refresh-worker background loop uses, but returns the raw per-game
    # betting/game_market_recommendations/prop_recommendations fields (which
    # /api/ops/wnba/status-trace strips) so a zero-candidate output can be
    # root-caused without relying on production log scraping.
    date = str(request.args.get("date") or "").strip() or None
    sport_filter = str(request.args.get("sport") or "").strip().lower() or None

    if _coerce_bool(request.args.get("read_only")):
        # Fast path: the full trace below runs collect/score/filter 3-4x and
        # can exceed the gunicorn request timeout. This isolates just the
        # cheap path/key resolution + raw persisted-state reads (no
        # candidate computation at all) for quick iteration during an
        # incident where only the read side is in question.
        read_only_trace: dict[str, Any] = {}
        try:
            from syndicate.features.shared.refresh_state_store import reports_root as _reports_root
            from syndicate.features.shared.refresh_state_store import read_json_file as _read_json_file
            from syndicate.features.shared.refresh_state_store import _state_key_for_path
            from pipeline.intelligence_state import STATE_PATH as _STATE_PATH
            from pipeline.intelligence_state import BOARD_SNAPSHOT_PATH as _BOARD_SNAPSHOT_PATH

            read_only_trace["reports_root"] = str(_reports_root())
            read_only_trace["state_path"] = str(_STATE_PATH)
            read_only_trace["board_snapshot_path"] = str(_BOARD_SNAPSHOT_PATH)
            read_only_trace["state_path_redis_key"] = _state_key_for_path(_STATE_PATH)
            read_only_trace["board_snapshot_path_redis_key"] = _state_key_for_path(_BOARD_SNAPSHOT_PATH)

            board_snapshot_raw = _read_json_file(_BOARD_SNAPSHOT_PATH)
            read_only_trace["board_snapshot_read_is_dict"] = isinstance(board_snapshot_raw, dict)
            if isinstance(board_snapshot_raw, dict):
                read_only_trace["board_snapshot_read_keys"] = list(board_snapshot_raw.keys())
                read_only_trace["board_snapshot_read_latest_key"] = board_snapshot_raw.get("latest_key")
                candidates_field = board_snapshot_raw.get("candidates") or board_snapshot_raw.get("top_opportunities")
                read_only_trace["board_snapshot_read_candidate_count"] = len(candidates_field) if isinstance(candidates_field, list) else None
                read_only_trace["board_snapshot_read_updated_at"] = board_snapshot_raw.get("updated_at") or board_snapshot_raw.get("generated_at")

            state_raw = _read_json_file(_STATE_PATH)
            read_only_trace["state_read_is_dict"] = isinstance(state_raw, dict)
            if isinstance(state_raw, dict):
                read_only_trace["state_read_latest_key"] = state_raw.get("latest_key")
                snapshots = state_raw.get("snapshots")
                read_only_trace["state_read_snapshot_keys"] = list(snapshots.keys()) if isinstance(snapshots, dict) else None
                if isinstance(snapshots, dict) and state_raw.get("latest_key") in snapshots:
                    latest_snap = snapshots[state_raw.get("latest_key")]
                    resp = latest_snap.get("response") if isinstance(latest_snap, dict) else None
                    top_opps = resp.get("top_opportunities") if isinstance(resp, dict) else None
                    read_only_trace["state_read_latest_snapshot_candidate_count"] = len(top_opps) if isinstance(top_opps, list) else None
                    read_only_trace["state_read_latest_snapshot_computed_at"] = latest_snap.get("computed_at") if isinstance(latest_snap, dict) else None
                read_only_trace["state_read_updated_at"] = state_raw.get("updated_at")
        except Exception as exc:
            read_only_trace["error"] = f"{type(exc).__name__}: {exc}"
        return jsonify({"ok": True, "date": date, "read_only_trace": read_only_trace})

    try:
        from syndicate.features.intelligence import build_intelligence_overview
        from syndicate.features.intelligence import _query_preferences
        from syndicate.features.intelligence import _collect_candidates
        from syndicate.features.intelligence import collect_candidates
        from syndicate.features.intelligence import normalize_candidate
        from syndicate.features.intelligence import classify_candidate
        from syndicate.features.intelligence import _candidate_classification_removal_reason
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500

    try:
        overview = build_intelligence_overview(selected_date=date, force_refresh=True)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"build_intelligence_overview: {type(exc).__name__}: {exc}"}), 500

    manifest_check: dict[str, Any] = {}
    full_pool_check: dict[str, Any] = {}
    app_context_pool_check: dict[str, Any] = {}
    try:
        from pipeline.intelligence_state import _INTELLIGENCE_STATE_SERVICE

        manifests = _INTELLIGENCE_STATE_SERVICE._available_sport_manifests(date)
        manifest_check = {"available_sport_slugs": list(manifests.keys())}
        source_fingerprint = _INTELLIGENCE_STATE_SERVICE._source_state_fingerprint(date)
        pool = _INTELLIGENCE_STATE_SERVICE._build_candidate_pool(date, source_fingerprint)
        full_pool_check = {
            "source_fingerprint": source_fingerprint,
            "candidate_count": pool.get("candidate_count"),
            "candidate_pool_keys": list(pool.keys()) if isinstance(pool, dict) else None,
            "self_app_was": repr(_INTELLIGENCE_STATE_SERVICE._app),
        }

        # refresh-worker's background loop sets self._app (via .start(app))
        # and calls build_intelligence_overview inside
        # `with self._app.app_context():` from a background thread -- this
        # web-service diagnostic call runs inside a real Flask request
        # context instead, with self._app left None (web never starts the
        # background loop), so it never exercises that branch. Force it on,
        # bust this exact cache entry, and rebuild to see if the
        # manually-pushed background-thread app context changes the result.
        cache_key = _INTELLIGENCE_STATE_SERVICE._candidate_pool_key(date, source_fingerprint)
        with _INTELLIGENCE_STATE_SERVICE._condition:
            _INTELLIGENCE_STATE_SERVICE._candidate_pools.pop(cache_key, None)
        original_app = _INTELLIGENCE_STATE_SERVICE._app
        try:
            _INTELLIGENCE_STATE_SERVICE._app = current_app._get_current_object()
            pool_with_app_context = _INTELLIGENCE_STATE_SERVICE._build_candidate_pool(date, source_fingerprint)
            app_context_pool_check = {"candidate_count": pool_with_app_context.get("candidate_count")}
        finally:
            _INTELLIGENCE_STATE_SERVICE._app = original_app
            with _INTELLIGENCE_STATE_SERVICE._condition:
                _INTELLIGENCE_STATE_SERVICE._candidate_pools.pop(cache_key, None)
    except Exception as exc:
        manifest_check["error"] = f"{type(exc).__name__}: {exc}"

    preferences = _query_preferences(
        "top edges today",
        mode="recommendation",
        sport="all",
        timing="all",
        include_props=True,
        include_games=True,
    )

    # Stage-by-stage trace of collect_candidates_with_fallback_merge -- the
    # function _build_candidate_pool actually calls (not the plain
    # collect_candidates checked below), so this is the only way to see
    # where a count drops to 0 specifically inside _score_candidates /
    # filter_candidates(sport=None) / the thin-pool merge, none of which the
    # per-sport collect_candidates() checks below exercise.
    fallback_merge_trace: dict[str, Any] = {}
    try:
        from syndicate.features.intelligence import collect_candidates as _cc
        from syndicate.features.intelligence import _score_candidates as _sc
        from syndicate.features.intelligence import _tracked_repo_files as _trf
        from syndicate.features.intelligence import _advanced_input_rows_for_sport as _airfs
        from syndicate.features.shared.recommendation_engine import filter_candidates as _fc
        from syndicate.features.intelligence import _THIN_CANDIDATE_POOL_THRESHOLD as _thin_threshold

        raw = _cc(overview, preferences, None)
        fallback_merge_trace["1_collect_candidates_count"] = len(raw)
        if raw:
            tracked = _trf()
            advanced_by_sport = {
                str(sport_row.get("slug") or "sport").strip().lower(): _airfs(sport_row, tracked)
                for sport_row in overview
                if isinstance(sport_row, dict)
            }
            scored = _sc(raw, advanced_by_sport, preferences, pipeline="ops_trace")
            fallback_merge_trace["2_scored_count"] = len(scored)
            filtered = _fc(scored, sport=None)
            fallback_merge_trace["3_filter_candidates_count"] = len(filtered)
            fallback_merge_trace["4_thin_pool_threshold"] = _thin_threshold
            fallback_merge_trace["5_would_trigger_thin_merge"] = 0 < len(filtered) < _thin_threshold
    except Exception as exc:
        fallback_merge_trace["error"] = f"{type(exc).__name__}: {exc}"

    # Read-path trace: compute above is proven healthy (161 candidates), but
    # the served page still shows empty -- meaning refresh-worker's persisted
    # snapshot isn't being found by this same process's read functions. Read
    # the exact same paths/keys the real serving code reads, plus what
    # reports_root() resolves to here, to see whether this is a path/key
    # mismatch between the writer (refresh-worker) and this reader (web).
    read_path_trace: dict[str, Any] = {}
    try:
        from syndicate.features.shared.refresh_state_store import reports_root as _reports_root
        from syndicate.features.shared.refresh_state_store import read_json_file as _read_json_file
        from syndicate.features.shared.refresh_state_store import _state_key_for_path
        from pipeline.intelligence_state import STATE_PATH as _STATE_PATH
        from pipeline.intelligence_state import BOARD_SNAPSHOT_PATH as _BOARD_SNAPSHOT_PATH

        read_path_trace["reports_root"] = str(_reports_root())
        read_path_trace["state_path"] = str(_STATE_PATH)
        read_path_trace["board_snapshot_path"] = str(_BOARD_SNAPSHOT_PATH)
        read_path_trace["state_path_redis_key"] = _state_key_for_path(_STATE_PATH)
        read_path_trace["board_snapshot_path_redis_key"] = _state_key_for_path(_BOARD_SNAPSHOT_PATH)

        board_snapshot_raw = _read_json_file(_BOARD_SNAPSHOT_PATH)
        read_path_trace["board_snapshot_read_is_dict"] = isinstance(board_snapshot_raw, dict)
        if isinstance(board_snapshot_raw, dict):
            read_path_trace["board_snapshot_read_keys"] = list(board_snapshot_raw.keys())
            read_path_trace["board_snapshot_read_latest_key"] = board_snapshot_raw.get("latest_key")
            candidates_field = board_snapshot_raw.get("candidates") or board_snapshot_raw.get("top_opportunities")
            read_path_trace["board_snapshot_read_candidate_count"] = len(candidates_field) if isinstance(candidates_field, list) else None

        state_raw = _read_json_file(_STATE_PATH)
        read_path_trace["state_read_is_dict"] = isinstance(state_raw, dict)
        if isinstance(state_raw, dict):
            read_path_trace["state_read_latest_key"] = state_raw.get("latest_key")
            snapshots = state_raw.get("snapshots")
            read_path_trace["state_read_snapshot_keys"] = list(snapshots.keys()) if isinstance(snapshots, dict) else None
            read_path_trace["state_read_updated_at"] = state_raw.get("updated_at")
    except Exception as exc:
        read_path_trace["error"] = f"{type(exc).__name__}: {exc}"

    result: dict[str, Any] = {
        "ok": True,
        "date": date,
        "preferences": preferences,
        "manifest_check": manifest_check,
        "full_pool_check": full_pool_check,
        "app_context_pool_check": app_context_pool_check,
        "fallback_merge_trace": fallback_merge_trace,
        "read_path_trace": read_path_trace,
        "sports": [],
    }
    for sport in overview:
        if not isinstance(sport, dict):
            continue
        slug = str(sport.get("slug") or "").strip().lower()
        if sport_filter and slug != sport_filter:
            continue
        dashboard_games = sport.get("dashboard_games") if isinstance(sport.get("dashboard_games"), list) else []
        sample_game = dashboard_games[0] if dashboard_games else None
        sample_game_summary = None
        if isinstance(sample_game, dict):
            sample_game_summary = {
                "game_id": sample_game.get("game_id") or sample_game.get("gamePk"),
                "betting": sample_game.get("betting"),
                "game_market_recommendations": sample_game.get("game_market_recommendations"),
                "prop_recommendations": sample_game.get("prop_recommendations"),
                "status": sample_game.get("status"),
                "live_state": sample_game.get("live_state"),
                "home_rails_present": isinstance(sport.get("home_rails"), dict),
            }
        try:
            sport_candidates = _collect_candidates([sport], preferences)
        except Exception as exc:
            sport_candidates = None
            candidate_error = f"{type(exc).__name__}: {exc}"
        else:
            candidate_error = None

        removal_reasons: dict[str, int] = {}
        full_pipeline_count = None
        full_pipeline_error = None
        if isinstance(sport_candidates, list):
            for raw_candidate in sport_candidates:
                normalized = normalize_candidate(raw_candidate)
                if classify_candidate(normalized) is None:
                    reason = _candidate_classification_removal_reason(normalized)
                    removal_reasons[reason] = removal_reasons.get(reason, 0) + 1
            try:
                full_pipeline_candidates = collect_candidates([sport], preferences)
                full_pipeline_count = len(full_pipeline_candidates)
            except Exception as exc:
                full_pipeline_error = f"{type(exc).__name__}: {exc}"

        result["sports"].append(
            {
                "slug": slug,
                "dashboard_games_count": len(dashboard_games),
                "sample_game": sample_game_summary,
                "candidate_count": len(sport_candidates) if isinstance(sport_candidates, list) else None,
                "candidate_error": candidate_error,
                "second_pass_removal_reasons": removal_reasons,
                "full_pipeline_candidate_count": full_pipeline_count,
                "full_pipeline_error": full_pipeline_error,
            }
        )
    return jsonify(result)


@ops_bp.get("/api/ops/mlb/live-check")
def api_ops_mlb_live_check() -> Any:
    # Protected endpoint: requires admin token
    date = str(request.args.get("date") or "").strip()
    game_pk_raw = request.args.get("game_pk") or request.args.get("gamePk") or request.args.get("game")
    try:
        game_pk = int(str(game_pk_raw)) if game_pk_raw is not None else None
    except Exception:
        game_pk = None
    if not date:
        return jsonify({"ok": False, "error": "date parameter required (YYYY-MM-DD)"}), 400
    try:
        repo_root = Path(current_app.root_path).resolve().parent
        data_root = Path(str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() or "data")
        # live_lens report path candidates
        live_lens_candidates = []
        for base in (data_root / "mlb_source", repo_root / "data" / "mlb_source"):
            live_path = base / "source_artifacts" / "data" / "live_lens" / f"live_lens_report_{date.replace('-', '_')}.json"
            live_lens_candidates.append(str(live_path))
        # raw feed candidates
        raw_candidates = []
        season = date.split("-", 1)[0] if date else None
        if season and game_pk:
            for base in (data_root / "mlb_source", repo_root / "data" / "mlb_source"):
                raw_dir = base / "source_artifacts" / "data" / "raw" / "statsapi" / season / date
                for suffix in (".json.gz", ".json"):
                    raw_candidates.append(str(raw_dir / f"{int(game_pk)}{suffix}"))

        # check existence and sizes
        live_results = []
        for path in live_lens_candidates:
            p = Path(path)
            live_results.append({"path": path, "exists": p.exists() and p.is_file(), "size": p.stat().st_size if p.exists() and p.is_file() else None})

        raw_results = []
        for path in raw_candidates:
            p = Path(path)
            raw_results.append({"path": path, "exists": p.exists() and p.is_file(), "size": p.stat().st_size if p.exists() and p.is_file() else None})

        return jsonify({"ok": True, "date": date, "game_pk": game_pk, "live_lens": live_results, "raw_feed": raw_results})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500


@ops_bp.get("/api/ops/odds-refresh/plan")
def api_ops_odds_refresh_plan() -> Any:
    try:
        payload = build_refresh_plan(
            date=request.args.get("date"),
            sports=request.args.get("sports"),
            phase=request.args.get("phase"),
            execution_mode=request.args.get("execution_mode"),
            regions=request.args.get("regions"),
            bookmakers=request.args.get("bookmakers"),
            markets=request.args.get("markets"),
            season=_coerce_int(request.args.get("season")),
            week=_coerce_int(request.args.get("week")),
            skip_mirror=_coerce_bool(request.args.get("skip_mirror")),
            mirror_only=_coerce_bool(request.args.get("mirror_only")),
            force_refresh=_coerce_bool(request.args.get("force_refresh")),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"ok": True, "plan": payload})


@ops_bp.post("/api/ops/odds-refresh/run")
def api_ops_odds_refresh_run() -> Any:
    payload = _request_data()
    try:
        job_id, job = _start_refresh_job(payload, mode="fast")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"ok": True, "status": "started", "job_id": job_id, "job": normalize_timestamped_payload(job)}), 202


@ops_bp.post("/api/ops/full-refresh/run")
def api_ops_full_refresh_run() -> Any:
    payload = _request_data()
    # Default to manifest_only, and only here. A full refresh is the heaviest
    # thing this API can start, and without an explicit launch_mode it falls
    # through to SYNDICATE_REFRESH_LAUNCH_MODE, which render.yaml sets to
    # detached_subprocess on the WEB service -- so a POST here would spawn the
    # whole refresh tree inside the request-serving container. That breaks the
    # load-bearing rule in CLAUDE.md (the web service does no heavy
    # computation, workers write artifacts and web reads them), and it is the
    # same starvation that produced #56's health-check kills on 2026-07-25.
    #
    # manifest_only records the intent for a worker to execute, which is what
    # the ops trigger is for. An explicit launch_mode in the request still
    # wins, so a worker calling this can still run it directly.
    payload = dict(payload or {})
    payload.setdefault("launch_mode", "manifest_only")
    try:
        job_id, job = _start_refresh_job(payload, mode="full")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"ok": True, "status": "started", "job_id": job_id, "job": job}), 202


@ops_bp.post("/api/ops/odds-refresh/cancel")
def api_ops_odds_refresh_cancel() -> Any:
    lane = str(request.args.get("lane") or _request_data().get("lane") or "").strip() or None
    try:
        result = cancel_latest_refresh_run(lane=lane)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"ok": bool(result.get("ok")), "cancel": normalize_timestamped_payload(result)}), 200 if result.get("ok") else 409


@ops_bp.get("/api/ops/odds-refresh/logs")
def api_ops_odds_refresh_logs() -> Any:
    stream = request.args.get("stream") or "stderr"
    raw = _coerce_bool(request.args.get("raw"))
    lane = str(request.args.get("lane") or "").strip() or None
    try:
        payload = load_latest_refresh_log(stream=stream, lane=lane)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    if raw:
        return Response(payload.get("content") or "", mimetype="text/plain")
    return jsonify({"ok": True, "log": payload})


@ops_bp.get("/ops/odds-refresh")
def page_ops_odds_refresh() -> Any:
    plan_error: str | None = None
    plan_payload: dict[str, Any] | None = None
    status_payload: dict[str, Any] = {
        "refresh_status": {
            "manifest_path": "",
            "manifest_exists": False,
            "manifest": {},
            "artifacts": {},
            "mirror_manifests": [],
            "runtime": {"state": "unknown", "detail": "Refresh status is unavailable."},
            "history": [],
        },
        "daily_update": {
            "manifest_path": "",
            "manifest_exists": False,
            "manifest": {},
            "runtime": {"state": "unknown", "detail": "Daily update status is unavailable."},
            "checkpoint_path": "",
            "checkpoint_exists": False,
            "checkpoint": {},
            "run_state_path": "",
            "run_state_exists": False,
            "run_state": {},
            "trace_path": "",
            "trace_exists": False,
            "trace": {},
        },
    }
    try:
        loaded_status = load_latest_refresh_status()
        if isinstance(loaded_status, dict):
            status_payload = loaded_status
    except Exception as exc:
        plan_error = f"{type(exc).__name__}: {exc}"
    try:
        plan_payload = build_refresh_plan(
            date=request.args.get("date"),
            sports=request.args.get("sports"),
            phase=request.args.get("phase"),
            execution_mode=request.args.get("execution_mode"),
            regions=request.args.get("regions"),
            bookmakers=request.args.get("bookmakers"),
            markets=request.args.get("markets"),
            season=_coerce_int(request.args.get("season")),
            week=_coerce_int(request.args.get("week")),
            skip_mirror=_coerce_bool(request.args.get("skip_mirror")),
            mirror_only=_coerce_bool(request.args.get("mirror_only")),
            force_refresh=_coerce_bool(request.args.get("force_refresh")),
        )
    except ValueError as exc:
        plan_error = str(exc)
    except Exception as exc:
        plan_error = plan_error or f"{type(exc).__name__}: {exc}"

    form_state = {
        "date": str(request.args.get("date") or "").strip(),
        "sports": str(request.args.get("sports") or "all").strip() or "all",
        "phase": str(request.args.get("phase") or "all").strip() or "all",
        "execution_mode": str(request.args.get("execution_mode") or "source").strip() or "source",
        "regions": str(request.args.get("regions") or "us").strip() or "us",
        "bookmakers": str(request.args.get("bookmakers") or "").strip(),
        "markets": str(request.args.get("markets") or "").strip(),
        "season": str(request.args.get("season") or "").strip(),
        "week": str(request.args.get("week") or "").strip(),
        "skip_mirror": _coerce_bool(request.args.get("skip_mirror")),
        "mirror_only": _coerce_bool(request.args.get("mirror_only")),
        "force_refresh": _coerce_bool(request.args.get("force_refresh")),
        "mode": str(request.args.get("mode") or "fast").strip().lower() or "fast",
    }
    return render_template(
        "shared/ops_odds_refresh.html",
        page_title_text="Ops Odds Refresh",
        page_body_class="ops-page",
        page_shell_class="ops-shell",
        status_payload=status_payload,
        plan_payload=plan_payload,
        plan_error=plan_error,
        launch_notice={
            "started": _coerce_bool(request.args.get("launched")),
            "pid": str(request.args.get("pid") or "").strip(),
            "run_stamp": str(request.args.get("run_stamp") or "").strip(),
            "dry_run": _coerce_bool(request.args.get("dry_run")),
            "canceled": _coerce_bool(request.args.get("canceled")),
        },
        form_state=form_state,
    )


@ops_bp.post("/ops/odds-refresh/run")
def page_ops_odds_refresh_run() -> Any:
    payload = _request_data()
    try:
        result = launch_refresh_run(
            date=_payload_value(payload, "date"),
            sports=_payload_value(payload, "sports"),
            phase=_payload_value(payload, "phase"),
            execution_mode=_payload_value(payload, "execution_mode"),
            regions=_payload_value(payload, "regions"),
            bookmakers=_payload_value(payload, "bookmakers"),
            markets=_payload_value(payload, "markets"),
            season=_coerce_int(_payload_value(payload, "season")),
            week=_coerce_int(_payload_value(payload, "week")),
            skip_mirror=_coerce_bool(_payload_value(payload, "skip_mirror")),
            mirror_only=_coerce_bool(_payload_value(payload, "mirror_only")),
            dry_run=_coerce_bool(_payload_value(payload, "dry_run")),
            mode=str(_payload_value(payload, "mode", "fast") or "fast"),
            force_refresh=_coerce_bool(_payload_value(payload, "force_refresh")),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    args = {
        "launched": "1",
        "pid": str(result.get("pid") or "").strip(),
        "run_stamp": str(result.get("run_stamp") or "").strip(),
        "dry_run": "1" if _coerce_bool(_payload_value(payload, "dry_run")) else "0",
    }
    admin_token = _request_admin_token()
    if admin_token:
        args["admin_token"] = admin_token
    return redirect(url_for("ops.page_ops_odds_refresh", **args))


@ops_bp.post("/ops/odds-refresh/cancel")
def page_ops_odds_refresh_cancel() -> Any:
    lane = str(request.form.get("lane") or request.args.get("lane") or "").strip() or None
    result = cancel_latest_refresh_run(lane=lane)
    args = {"canceled": "1"}
    admin_token = _request_admin_token()
    if admin_token:
        args["admin_token"] = admin_token
    if not result.get("ok"):
        args["cancel_error"] = "1"
    return redirect(url_for("ops.page_ops_odds_refresh", **args))