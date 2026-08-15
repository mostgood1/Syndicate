from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import sys
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
            # PER-LEAGUE SCOPE, REACHABLE FROM OPS (`#433`). `launch_refresh_run`
            # has accepted `soccer_leagues` since `#282` and
            # `refresh_odds_sources.py` has implemented `--soccer-leagues`, but
            # this function never passed it -- so every ops-triggered soccer
            # refresh was all-leagues, all 50 steps, whether the caller wanted
            # one league or ten.
            #
            # That gap had teeth on 2026-08-14. Three leagues' odds were 3.6
            # days stale with kickoffs two hours out, and the only remedy
            # reachable through the API was a full ten-league run -- which is
            # exactly the run that had been dying at step 27 and leaving those
            # leagues dark in the first place. Scoping to one league turns a
            # 50-step job into ~6, which finishes long before anything can
            # truncate it.
            #
            # Unknown slugs are rejected loudly by `refresh_odds_sources.py`
            # itself (`SystemExit` naming the known set), so no validation is
            # duplicated here -- an unrecognised league must not silently become
            # "all leagues", which is what passing it through unchecked would
            # risk if that guard were ever relaxed.
            soccer_leagues=_payload_value(launch_payload, "soccer_leagues"),
            soccer_date=_payload_value(launch_payload, "soccer_date"),
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


@ops_bp.get("/api/ops/wnba/refresh-decision")
def api_ops_wnba_refresh_decision() -> Any:
    """`#344`: WHY the WNBA odds refresh did or did not fetch.

    WNBA made zero OddsAPI calls for 45+ minutes on a live slate -- `wnba_calls`
    pinned at 1158 while MLB climbed 135,645 -> 135,714 -- and nothing readable
    said why. The parent ran every tick while the child that fetches and writes
    `book_quotes` never spawned, because a reuse guard returned a cached state.

    Every route to that answer was blocked: the script's stdout goes to a log
    file on the WORKER's disk, run artifacts return 403, and
    `/api/ops/odds-refresh/status` reads WEB's disk (the `#304` split). The skip
    was only diagnosable because a memory instrument happens to log process
    cmdlines -- an accident. This endpoint exists so the next person does not
    need that accident.

    Reads the keyvalue store, which crosses the service boundary, rather than a
    path on whichever disk happens to be mounted.
    """
    # `central_today_iso` is NOT a module global here -- every other user in this
    # file imports it inside the function. Without this line the route raises
    # NameError before doing any work: confirmed 500 against production
    # 2026-08-15, `GET /api/ops/wnba/refresh-decision`. Found incidentally while
    # adding the quote-feed-age route; fixed rather than filed because it is one
    # line and the endpoint is dead until it lands.
    from syndicate.features.shared.timezone import central_today_iso

    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    try:
        from syndicate.features.shared.refresh_state_store import read_json_file, reports_root

        path = reports_root() / "refresh_status" / "latest" / f"wnba_refresh_decision_{selected_date}.json"
        payload = read_json_file(path)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "date": selected_date, "error": f"{type(exc).__name__}: {exc}"})
    if not payload:
        # Absent is a REAL answer here and must not read as "it fetched": it
        # means no tick has recorded a decision for this date yet.
        return jsonify({
            "ok": True,
            "date": selected_date,
            "decision": None,
            "reason": "no_decision_recorded_for_date",
        })
    return jsonify({"ok": True, "date": selected_date, **payload})


@ops_bp.get("/api/ops/odds-refresh/status")
def api_ops_odds_refresh_status() -> Any:
    return jsonify({"ok": True, "status": normalize_timestamped_payload(load_latest_refresh_status())})


@ops_bp.get("/api/ops/opportunity-contract/status")
def api_ops_opportunity_contract_status() -> Any:
    """Identity coverage of opportunity rows, per sport and lane (#222).

    Step 2 of the one-opportunity-pipeline plan: measure the gap before closing
    it. Reports how many rows arrive WITHOUT the fields the price/CLV join
    actually needs -- a canonical `market_key`, an `entity_name` for props, and
    an event identity -- so a fix can be shown to have moved something rather
    than assumed to have.

    Serves the in-process counters when this instance has built a dashboard, and
    falls back to the persisted report otherwise. Both carry `service_role`,
    because the instrumented lanes run on web AND refresh-worker and those are
    separate disks -- a count without it is not interpretable.
    """
    from syndicate.features.shared import opportunity_contract_metrics

    live = opportunity_contract_metrics.snapshot()
    if live.get("by_sport"):
        return jsonify({"ok": True, "source": "in_process", "metrics": live})
    try:
        from syndicate.features.shared.refresh_state_store import read_json_file, reports_root

        persisted = read_json_file(reports_root() / "opportunity_contract" / "latest.json")
    except Exception:
        persisted = None
    return jsonify({"ok": True, "source": "persisted", "metrics": persisted or live})


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

    # #327. The ring is a time series and rotates; a stage that spikes once per
    # 75 minutes can age out of it entirely. The high-water marks are
    # O(distinct stages) rather than O(samples), never rotate, and are the only
    # place a rare excursion is guaranteed to still be visible. Sorted worst
    # first, because "which stage is the OOM risk" is the question being asked.
    from syndicate.features.shared.memory_observability import process_memory_high_water_path

    high_water_payload = read_json_file(process_memory_high_water_path())
    stages = (high_water_payload or {}).get("stages") if isinstance(high_water_payload, dict) else None
    high_water = sorted(
        (dict(v) for v in (stages or {}).values() if isinstance(v, dict)),
        key=lambda item: item.get("peak_mb") if isinstance(item.get("peak_mb"), (int, float)) else -1.0,
        reverse=True,
    )
    return jsonify(
        {
            "ok": True,
            "record_count": len(records),
            "records": records,
            "high_water_stage_count": len(high_water),
            "high_water": high_water,
        }
    )


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
    from pipeline.intelligence_state import expand_persisted_state

    # #317/#320. The persisted payload is aliased AND compressed, so a raw read
    # sees `response = {"__compressed__": ...}` and counts zero recommendations
    # for a perfectly healthy board -- measured 2026-08-10T02:10Z, this endpoint
    # said 0 while /api/intelligence/status said 150 for the same snapshot.
    snapshot = expand_persisted_state(read_json_file(BOARD_SNAPSHOT_PATH))
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


@ops_bp.get("/api/ops/odds-history/matchup-coverage")
def api_ops_odds_history_matchup_coverage() -> Any:
    # Read-only. Diagnostic for todo.md's "MLB odds-history: 18/30-team
    # coverage gap" -- _sync_odds_history_for_refresh (odds_refresh_tracking.py)
    # only ever runs inside whichever service's odds-refresh subprocess is
    # currently active (live-odds-worker's round-robin or refresh-worker's
    # own run), and that subprocess's stdout is captured to a file the ops
    # log-read endpoint truncates to its last 64KB -- too small to reach a
    # busy run's MLB section. Keyvalue-backed like evaluation-settlement's
    # status endpoint above, so this is readable from the web service
    # regardless of which service actually wrote it or how large that
    # service's own captured log got.
    #
    # 2026-08-04: this accepted ?sport= and ?date= and honoured NEITHER -- it
    # always returned whatever the last refresh happened to write. Asked for
    # 2026-08-04 during triage it answered for 2026-08-05 (a look-ahead run
    # had written last), which read as "the diagnostic ignores its date" and
    # sent the investigation sideways; asked for 2026-07-01 or 2026-01-15 it
    # answered 2026-08-04 just as confidently. A diagnostic that silently
    # answers a different question than the one asked is worse than one that
    # refuses: it is trusted. The stored record is genuinely last-write-only
    # (one file, keyed by sport), so rather than invent per-date history the
    # response now says exactly which date it is describing and whether that
    # is the date you asked for.
    status_path = reports_root() / "refresh_status" / "latest" / "odds_history_h2h_matchup_coverage_status.json"
    by_sport = read_json_file(status_path) or {}
    if not isinstance(by_sport, dict):
        by_sport = {}

    requested_sport = str(request.args.get("sport") or "").strip().lower()
    if requested_sport:
        by_sport = {key: value for key, value in by_sport.items() if str(key).strip().lower() == requested_sport}

    requested_date = str(request.args.get("date") or "").strip()
    matches_requested_date = None
    reported_dates = sorted(
        {str(value.get("date") or "") for value in by_sport.values() if isinstance(value, dict) and value.get("date")}
    )
    if requested_date:
        matches_requested_date = bool(reported_dates) and all(date == requested_date for date in reported_dates)

    return jsonify({
        "ok": True,
        "by_sport": by_sport,
        "requested_sport": requested_sport or None,
        "requested_date": requested_date or None,
        "reported_dates": reported_dates,
        # True/False when a date was asked for, null when it wasn't. False
        # means every number below describes a DIFFERENT day than the one
        # requested -- the record is last-write-only, not per-date.
        "matches_requested_date": matches_requested_date,
        "source": "last_refresh_write_only",
    })


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


_PUBLISH_STREAM_CHUNK_BYTES = 1024 * 1024


def _publish_streamed_body() -> Any:
    """Receive a raw streamed artifact body, one chunk resident at a time.

    The JSON form below reads the whole body, parses it into a dict holding a
    full copy of the file as a str, and then encodes that str again on the way
    to disk -- three full copies of the artifact on a 2Gi instance. Measured
    2026-08-08: refresh-worker publishes `intelligence_state_2026_08_08.json` at
    27,420,309 bytes on every cycle that produces a real board, and web had
    675MB of headroom at the time. #29746931 identified this exact shape as the
    reason web was OOMing "with no correlation to anyone's deploys" and fixed
    only which files the sweep selects; the direct publishers were never bounded.

    Metadata arrives in headers so the body can stay raw. Checksum is verified
    BEFORE the rename, so a truncated transfer leaves the previous artifact in
    place rather than replacing it with a partial one -- the failure mode that
    matters here, since every consumer of these files reads them whole.
    """
    relative_path = str(request.headers.get("X-Artifact-Path") or "").strip().replace("\\", "/")
    if not relative_path:
        return jsonify({"ok": False, "error": "X-Artifact-Path is required."}), 400
    if relative_path.startswith("/") or ".." in relative_path.split("/"):
        return jsonify({"ok": False, "error": "invalid relative_path."}), 400
    if not is_hot_artifact_relative_path(relative_path):
        return jsonify({"ok": False, "error": "relative_path is not an allowed hot artifact."}), 403

    expected_checksum = str(request.headers.get("X-Artifact-Checksum") or "").strip().lower()
    target_path = data_root() / Path(relative_path)
    temp_path = target_path.parent / f"{target_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    digest = hashlib.sha256()
    written = 0
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        stream = request.stream
        with temp_path.open("wb") as handle:
            while True:
                chunk = stream.read(_PUBLISH_STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                written += len(chunk)
                handle.write(chunk)
        if expected_checksum and digest.hexdigest() != expected_checksum:
            temp_path.unlink(missing_ok=True)
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "checksum mismatch",
                        "relative_path": relative_path,
                        "bytes": written,
                    }
                ),
                400,
            )
        os.replace(temp_path, target_path)
    except Exception as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    return jsonify({"ok": True, "relative_path": relative_path, "bytes": written, "transport": "stream"}), 200


# Encoding a whole `content` str in one call is a second full copy of the
# artifact; a megabyte at a time is not. Slicing a str is by code point, so a
# chunk boundary can never split a character.
_PUBLISH_ENCODE_CHUNK_CHARS = 1024 * 1024


def _write_published_artifact(relative_path: str, content: Any) -> Any:
    """Validate and atomically write one envelope-form artifact."""
    if not relative_path or content is None:
        return jsonify({"ok": False, "error": "relative_path and content are required."}), 400
    if relative_path.startswith("/") or ".." in relative_path.split("/"):
        return jsonify({"ok": False, "error": "invalid relative_path."}), 400
    if not is_hot_artifact_relative_path(relative_path):
        return jsonify({"ok": False, "error": "relative_path is not an allowed hot artifact."}), 403

    if not isinstance(content, str):
        content = str(content)

    target_path = data_root() / Path(relative_path)
    temp_path = target_path.parent / f"{target_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with temp_path.open("wb") as handle:
            for start in range(0, len(content), _PUBLISH_ENCODE_CHUNK_CHARS):
                handle.write(content[start : start + _PUBLISH_ENCODE_CHUNK_CHARS].encode("utf-8"))
        os.replace(temp_path, target_path)
    except Exception as exc:
        # write_text() left the .tmp behind on any failure, on the same disk
        # that holds the artifacts, once per failed publish.
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    return jsonify({"ok": True, "relative_path": relative_path, "bytes": target_path.stat().st_size}), 200


@ops_bp.post("/api/ops/artifacts/publish")
def api_ops_artifacts_publish() -> Any:
    # Two accepted forms on one route, deliberately. The JSON envelope stays
    # because live-odds-worker is pinned to an older commit and must keep
    # publishing, and because a receiver that only understood the new form would
    # make the deploy order load-bearing. The sender picks the streamed form by
    # size and falls back on a 4xx that means "unsupported".
    if str(request.headers.get("X-Artifact-Path") or "").strip():
        return _publish_streamed_body()

    # MEASURED on this receiver 2026-08-09 against a 3.9MB artifact, peak
    # resident as a multiple of the artifact:
    #
    #     envelope, before   3.76x  (14.0 MiB)
    #     envelope, after    2.63x  ( 9.8 MiB)
    #     streamed form      0.81x  ( 3.0 MiB)   <- unchanged, already correct
    #
    # THIS IS NOT THE WEB OOM, and must not be reported as if it were. Same
    # service, same evening: minutes serving 154 publishes sat flat at ~748
    # MiB, while every 1.6-1.8 GiB spike landed on a minute serving 24-74. The
    # bound is why -- 8 gunicorn slots x 14 MiB was ~112 MiB, ~5% of the 2Gi
    # limit. See #319; the cause is request-path compute, see #318.
    #
    # It is worth having anyway because the envelope is still what a refused
    # streamed publish falls back to, and a 27.6MB intelligence_state down
    # that path cost ~104 MiB in a single request and now costs ~73 MiB.
    if request.mimetype == "application/json":
        raw = request.get_data(cache=False)
        # Decode to str and drop the bytes BEFORE parsing. json.loads(bytes)
        # decodes internally and holds the bytes and the decoded envelope and
        # the extracted content all at once -- that parse, not the write, is
        # what sets the peak here. Chunking the write alone changed nothing.
        try:
            text = raw.decode("utf-8")
        except Exception:
            text = None
        del raw
        payload = None
        if text is not None:
            try:
                payload = json.loads(text)
            except Exception:
                payload = None
        del text
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "relative_path and content are required."}), 400
        relative_path = str(payload.get("relative_path") or "").strip().replace("\\", "/")
        # pop, so the envelope dict stops being a second reference to the
        # artifact the moment we have our own.
        content = payload.pop("content", None)
        payload = None
        return _write_published_artifact(relative_path, content)

    payload = _request_data()
    return _write_published_artifact(
        str(payload.get("relative_path") or "").strip().replace("\\", "/"),
        payload.get("content"),
    )


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
    # ?names_only=1 -- inventory without bodies. Answers "what exists, how big,
    # how fresh" for a matched set at a few bytes per file.
    #
    # THE INCIDENT THIS COMES FROM, 2026-08-08 21:29:41Z: a lane doing routine
    # reconnaissance called
    #   /api/ops/artifacts/export?pattern=reports/intelligence/intelligence_state*.json&names_only=1
    # and web returned 30,308,015 bytes. That was read as "names_only=1 does not
    # suppress bodies". It is worse than that -- THE PARAMETER DID NOT EXIST.
    # Flask ignores unknown query args, so the request ran as an ordinary
    # full-body export and the flag the caller believed was protecting them was
    # never read by anything. 30MB through the 2Gi service, from a query whose
    # author thought they had asked for names.
    #
    # (30,308,015 is the JSON envelope of one 27,420,309-byte state file, within
    # three bytes of the figure measured independently on the publish path --
    # so it was one artifact's body, exactly as an un-flagged export would give.)
    #
    # Implemented rather than rejected: the intent was reasonable and the cheap
    # inventory is genuinely useful, which is why someone reached for it. An
    # unknown-parameter rejection would also have prevented this and is a
    # bigger, separate behaviour change across every ops route.
    names_only = _coerce_bool(request.args.get("names_only"))
    artifacts: dict[str, str] = {}
    if names_only:
        listing: dict[str, dict[str, Any]] = {}
        for pattern in HOT_ARTIFACT_PATTERNS:
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
                    listing[relative_path] = {"bytes": stat.st_size, "mtime": stat.st_mtime}
                except Exception:
                    continue
        # No `truncated` key on purpose: this path never reads a file, so there
        # is no budget to exceed and nothing to truncate. Reporting a field that
        # is structurally always False would invite a caller to trust it on the
        # body-carrying path too.
        return jsonify(
            {
                "ok": True,
                "count": len(listing),
                "names_only": True,
                "bytes": sum(int(entry["bytes"]) for entry in listing.values()),
                "artifacts": listing,
            }
        )
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


@ops_bp.get("/api/ops/artifacts/stream")
def api_ops_artifacts_stream() -> Any:
    # Protected endpoint: requires admin token (enforced by before_request).
    #
    # Single-artifact companion to /api/ops/artifacts/export, for the one file
    # class that endpoint structurally cannot deliver: odds_history shards.
    # They are ~51MB on a real MLB slate (measured 2026-07-28: 51.1MB / 3,713
    # markets) against export's 24MB whole-response budget, so the shard is
    # either skipped as truncation (and the puller never advances its
    # watermark past it, so it truncates at the same place forever) or, when
    # it happens to be the first match, read whole into a dict and
    # JSON-encoded on a 2GB web instance -- the exact shape of #50's OOM.
    # Confirmed live 2026-08-04: web held 3,436 MLB markets while every one of
    # 354 MLB board candidates rendered history_points=0, because the board is
    # built on refresh-worker (render.yaml: it alone sets
    # SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=true) and
    # refresh-worker can only receive artifacts by pulling them. WNBA was
    # unaffected the whole time -- 34 markets, kilobytes, well inside budget.
    #
    # Differs from export in exactly the ways that matter for a large file:
    # the body is streamed from disk by send_file rather than accumulated in
    # memory, and ?since= answers 304 (headers only, no body) instead of
    # re-sending an unchanged 51MB every ~30s. Same allowlist, same admin
    # gate -- this widens the transport, not what may cross it.
    relative_path = str(request.args.get("path") or "").strip().replace("\\", "/")
    if not relative_path:
        return jsonify({"ok": False, "error": "path parameter required."}), 400
    if relative_path.startswith("/") or ".." in relative_path.split("/"):
        return jsonify({"ok": False, "error": "invalid path."}), 400
    if not is_hot_artifact_relative_path(relative_path):
        return jsonify({"ok": False, "error": "path is not an allowed hot artifact."}), 403

    target = data_root() / Path(relative_path)
    if not target.is_file():
        return jsonify({"ok": False, "error": "not found."}), 404
    # Defence in depth against a symlink or a pattern that escapes the root:
    # the allowlist check above is on the requested string, this is on what
    # that string actually resolved to on disk.
    try:
        resolved = target.resolve()
        if not str(resolved).startswith(str(data_root().resolve())):
            return jsonify({"ok": False, "error": "invalid path."}), 400
    except Exception:
        return jsonify({"ok": False, "error": "invalid path."}), 400

    try:
        stat = target.stat()
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500

    since_raw = str(request.args.get("since") or "").strip()
    if since_raw:
        try:
            if stat.st_mtime <= float(since_raw):
                # Not modified. The caller keeps its local copy and pays one
                # round trip instead of one transfer -- the whole reason this
                # is worth calling every cycle.
                response = Response(status=304)
                response.headers["X-Artifact-Mtime"] = str(stat.st_mtime)
                response.headers["X-Artifact-Size"] = str(stat.st_size)
                return response
        except ValueError:
            pass

    from flask import send_file

    response = send_file(target, mimetype="application/json", conditional=True)
    # The puller stamps its local copy with this so its next since= is
    # web's own clock, not the moment the file finished downloading --
    # otherwise a slow transfer looks newer than the source and the copy
    # never refreshes again.
    response.headers["X-Artifact-Mtime"] = str(stat.st_mtime)
    response.headers["X-Artifact-Size"] = str(stat.st_size)
    return response


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


@ops_bp.get("/api/ops/quote-feed-age")
def api_ops_quote_feed_age() -> Any:
    """How old is the newest quote we have, per sport.

    THE FAILURE THIS EXISTS FOR, measured 2026-08-15: MLB quote capture stopped
    at 11:07:48Z and resumed at 16:56:49Z -- 5.8 hours -- while the tick loop
    reported ok every 60 s, Layer 2 rebuilt every ~5 min (its healthiest gaps
    ever measured), and the board served 150 normal-looking rows. Every existing
    instrument was green because they all report on their OWN work, and their
    own work was fine; they were promptly processing a frozen input.

    Deliberately NOT derived from the board, the manifest or the tick. Those are
    the signals that were green. This reads the age of the newest sample in the
    quote shard itself, which is the only quantity that moves during this
    failure.

    Safe on web: an O(1) tail read, not a shard parse -- same cost on a 217 MB
    shard as on a 10 MB one, so it does not violate the no-heavy-compute rule.

    `?sports=mlb,nfl` and `?date=` override the defaults; `?threshold_seconds=`
    overrides `SYNDICATE_QUOTE_FEED_STALE_SECONDS` for one call, so an operator
    can ask "what would a tighter alarm have said" without an env change.
    """
    from syndicate.features.shared.quote_feed_age import feed_age_report
    from syndicate.features.shared.timezone import central_today_iso

    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    raw_sports = str(request.args.get("sports") or "").strip()
    if raw_sports:
        sports = [s.strip().lower() for s in raw_sports.split(",") if s.strip()]
    else:
        configured = str(os.environ.get("SYNDICATE_ACTIVE_SPORTS") or "").strip()
        sports = (
            [s.strip().lower() for s in configured.split(",") if s.strip()]
            if configured
            else ["mlb", "nfl", "wnba", "soccer", "nba", "nhl", "ncaaf", "ncaab"]
        )

    threshold_raw = str(request.args.get("threshold_seconds") or "").strip()
    try:
        threshold = int(threshold_raw) if threshold_raw else None
    except ValueError:
        threshold = None

    try:
        report = feed_age_report(sports, selected_date, threshold_seconds=threshold)
    except Exception as exc:
        # Fail loud. A 500 here is better than a green payload, which is the
        # exact failure mode this endpoint exists to end.
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({"ok": True, **report})


@ops_bp.get("/api/ops/oddsapi/quota")
def api_ops_oddsapi_quota() -> Any:
    # Ground truth for OddsAPI credit burn, straight from the counters the
    # vendor bills against (x-requests-used / -remaining). Every cadence
    # decision so far has been made against an ESTIMATE -- notably "MLB alone
    # is ~585 credits/sweep at 60s ticks, so ~6.3M/month against a 5M
    # budget". This is how that gets checked before #15 tunes anything.
    from syndicate.features.shared.oddsapi_quota import read_oddsapi_quota

    return jsonify({"ok": True, "quota": normalize_timestamped_payload(read_oddsapi_quota())})


@ops_bp.get("/api/ops/oddsapi/sports")
def api_ops_oddsapi_sports() -> Any:
    """WHICH COMPETITIONS THE VENDOR IS ACTUALLY OFFERING, right now (`#433`).

    THE QUESTION THIS EXISTS TO ANSWER. On 2026-08-14 three soccer leagues --
    primeira_liga, championship, belgian_pro_league -- went 3.6 days without a
    single quote reaching `tracking/book_quotes`, while eredivisie on the same
    shard, the same fetch script, the same key and the same region kept
    capturing normally. Every explanation tried from inside the pipeline was
    falsified: the season gate returns all ten leagues active, a per-league
    scoped run captured nothing either (so it is not the 50-step run being
    truncated), and the shard append logged no failure.

    The one input nobody could see is the vendor's own catalogue. If OddsAPI
    has stopped listing (or stopped marking `active`) those three sport keys,
    then no cadence, ordering or scoping change in this repo can fix it, and
    every hour spent inside the pipeline is wasted. That is a big enough fork
    in the diagnosis to deserve a route.

    STRICTLY READ-ONLY, AND FREE. `/v4/sports` is the vendor's catalogue
    endpoint: it takes no market or region parameters and returns no prices.
    Per OddsAPI's own documentation it does not count against the quota --
    **and this does not take that on trust.** The response's quota headers are
    recorded through the normal `record_oddsapi_quota` path, so if it ever DOES
    bill, the burn shows up in `/api/ops/oddsapi/quota` attributed to this
    endpoint rather than silently inflating some sport's total. Measuring the
    cost of the thing you added to measure costs is cheap; assuming it is free
    is how an unattributed line item is born.

    This writes nothing else and triggers no refresh.
    """
    # `urllib.parse` explicitly, not relied on as a side effect of importing
    # `urllib.request` -- that happens to work in CPython and is not a contract.
    import urllib.parse
    import urllib.request

    from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota

    api_key = str(os.environ.get("ODDS_API_KEY") or "").strip()
    if not api_key:
        # Named explicitly. "unavailable" would leave a caller unable to tell a
        # missing key from a vendor outage, which is the same
        # absence-without-a-reason failure the board keeps being fixed for.
        return jsonify({"ok": False, "error": "ODDS_API_KEY is not set on this service"}), 503

    base = str(os.environ.get("ODDS_API_BASE") or "https://api.the-odds-api.com/v4").rstrip("/")
    url = f"{base}/sports?apiKey={urllib.parse.quote(api_key)}"
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
            headers = dict(response.headers)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 502

    try:
        # `endpoint` carries no apiKey: `_sanitize_endpoint` redacts it, but the
        # URL is not handed over in the first place.
        record_oddsapi_quota(headers, sport="ops_catalogue", endpoint=f"{base}/sports")
    except Exception:  # noqa: BLE001
        # Telemetry must never fail the read it is describing.
        pass

    listed = {str(item.get("key")): item for item in payload if isinstance(item, dict)}

    # The join the caller actually wants: OUR league slug -> the vendor's key ->
    # is it there. Reading a raw 60-entry catalogue and matching slugs by eye is
    # how the wrong key gets blamed.
    from scripts.fetch_soccer_oddsapi_odds_local import LEAGUE_SPORT_KEYS

    soccer = []
    for league, sport_key in sorted(LEAGUE_SPORT_KEYS.items()):
        entry = listed.get(sport_key)
        soccer.append(
            {
                "league": league,
                "sport_key": sport_key,
                # Three distinct states, never collapsed: absent from the
                # catalogue, present but inactive (out of season), present and
                # active. Only the third can produce odds.
                "listed": entry is not None,
                "active": bool((entry or {}).get("active")) if entry is not None else None,
                "title": (entry or {}).get("title"),
                "has_outrights": (entry or {}).get("has_outrights"),
            }
        )

    return jsonify(
        {
            "ok": True,
            "server_time": _utc_now(),
            "catalogue_count": len(listed),
            "soccer": soccer,
            # The unfiltered key list, so a sport this repo has not mapped yet
            # is still discoverable without another deploy.
            "all_keys": sorted(listed),
        }
    )


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


@ops_bp.get("/api/ops/live-refresh/sport-liveness-check")
def api_ops_live_refresh_sport_liveness_check() -> Any:
    # Read-only diagnostic (2026-08-05): WNBA's odds-history updated_at
    # stayed frozen from BEFORE a real live game's tip-off for over an hour,
    # even after a confirmed, deployed fix to the artifact-freezing write
    # gate -- meaning refresh_wnba_oddsapi_props.py appears to not be
    # running at all during a live game. _apply_pregame_sport_cadence's
    # own liveness check (_LIVE_STATUS_CHECKERS[sport] -- artifact check OR
    # an ESPN-scoreboard subprocess fallback) should, by reading the code,
    # force the sport into every sweep once live. Whether that's true in
    # PRODUCTION's own process/environment is unverified -- the ESPN
    # subprocess call works when run locally, but a subprocess spawn
    # failure, PATH/env difference, or timeout under load on Render would
    # silently make it return False via its own bare except-return-False,
    # indistinguishable anywhere in current logging from "genuinely not
    # live". Exercises each layer of _wnba_has_live_game/_nba_has_live_game/
    # etc. individually and reports which one is actually true right now,
    # instead of only the combined boolean.
    from syndicate.features.shared import live_refresh_loop as _loop
    from syndicate.features.shared.timezone import central_today_iso

    sport = str(request.args.get("sport") or "").strip().lower()
    date_str = str(request.args.get("date") or "").strip() or central_today_iso()
    if not sport:
        return jsonify({"ok": False, "error": "sport parameter required (e.g. wnba)"}), 400

    checker = _loop._LIVE_STATUS_CHECKERS.get(sport)
    if checker is None:
        return jsonify({"ok": False, "error": f"no liveness checker registered for sport={sport!r}"}), 400

    artifact_checker_name = f"_{sport}_has_live_game_via_artifact"
    artifact_checker = getattr(_loop, artifact_checker_name, None)

    result: dict[str, Any] = {"ok": True, "sport": sport, "date": date_str}
    helper_path = _loop.REPO_ROOT / "scripts" / "fetch_espn_live_status_for_date.py"

    if callable(artifact_checker):
        try:
            result["artifact_check"] = {"ok": True, "value": bool(artifact_checker(date_str))}
        except Exception as exc:
            result["artifact_check"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    else:
        result["artifact_check"] = {"ok": False, "error": f"no {artifact_checker_name} on live_refresh_loop"}

    espn_started = time.perf_counter()
    try:
        espn_live = bool(_loop._espn_has_live_game(sport, date_str))
        result["espn_fallback_check"] = {
            "ok": True,
            "value": espn_live,
            "elapsed_ms": round((time.perf_counter() - espn_started) * 1000, 1),
        }
    except Exception as exc:
        result["espn_fallback_check"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_ms": round((time.perf_counter() - espn_started) * 1000, 1),
        }

    # _espn_has_live_game swallows the subprocess's own returncode/stderr
    # internally (any failure just becomes False, same as "genuinely not
    # live") -- run the exact same subprocess call directly here so a
    # network failure, a non-zero exit, or a malformed response is visible
    # instead of indistinguishable from a real "not live" answer.
    helper_started = time.perf_counter()
    try:
        raw = subprocess.run(
            [sys.executable, str(helper_path), "--sport", sport, "--date", date_str],
            cwd=str(_loop.REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=12.0,
        )
        result["espn_helper_raw"] = {
            "return_code": raw.returncode,
            "stdout": (raw.stdout or "").strip()[:2000],
            "stderr": (raw.stderr or "").strip()[:2000],
            "elapsed_ms": round((time.perf_counter() - helper_started) * 1000, 1),
        }
    except Exception as exc:
        result["espn_helper_raw"] = {
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_ms": round((time.perf_counter() - helper_started) * 1000, 1),
        }

    try:
        result["combined_checker_result"] = bool(checker(date_str))
    except Exception as exc:
        result["combined_checker_result_error"] = f"{type(exc).__name__}: {exc}"

    try:
        result["any_tracked_sport_game_live"] = bool(_loop._any_tracked_sport_game_live())
    except Exception as exc:
        result["any_tracked_sport_game_live_error"] = f"{type(exc).__name__}: {exc}"

    result["espn_helper_script_exists"] = helper_path.exists()
    result["python_executable"] = sys.executable

    return jsonify(result)


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


@ops_bp.get("/api/ops/sims/ledger")
def api_ops_sim_run_ledger() -> Any:
    """`#390`. The per-sport sim run ledger -- the answer to "when did each
    sport sim, how long did it take, and did it work".
    
    Before this, MLB was the only sport with any run record; the other six were
    measurable only by sampling child cmdlines out of a MEMORY diagnostic, which
    gives lower bounds rather than facts and requires Render API credentials.
    
    Reads the shared (keyvalue-backed) store, so it answers for runs recorded on
    either worker -- the `#304` web/worker disk split means a plain file read
    here would see only what web itself wrote, which is nothing.
    """
    date = str(request.args.get("date") or "").strip()
    if not date:
        return jsonify({"ok": False, "error": "date parameter required (YYYY-MM-DD)"}), 400
    try:
        from syndicate.features.shared.sim_run_ledger import read_sim_run_index
        from syndicate.features.shared.sim_run_ledger import summarize_by_sport
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500
    index = read_sim_run_index(date)
    return jsonify({
        "ok": True,
        "date": date,
        # Explicitly distinguishes "no runs recorded" from "the ledger is not
        # reachable from here". A bare empty list would read as the former when
        # it could be the latter -- the failure this whole ticket is about.
        "index_present": index is not None,
        "summary": summarize_by_sport(date),
        "runs": (index or {}).get("runs") or [],
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


@ops_bp.get("/api/ops/clv/report")
def api_ops_clv_report() -> Any:
    """CLV for a date, joined from the recorded openings (audit §7 #1).

    Read-only. Needs no grading, no outcomes, no `settle_result`, and never
    touches `evaluation_ledger_chunks` — the 367MB path whose 2026-08-05 chunk
    is already SKIPPED at read time against a 256MB ceiling.

    ON WEB, deliberately, and it is not a violation of the no-compute rule: the
    openings are a ~90KB published artifact and the join is over a few hundred
    rows against an odds-history payload this blueprint already loads for
    `/api/ops/odds-history/inspect` right below. That is display-side
    transformation, not the 1.3GB book-grid pivot the split exists to keep out.

    **`avg_clv_pct` COUNTS SAME-BOOK ROWS ONLY AND IS OFTEN None.** The board
    publishes the best price across ~13 books; pairing that opening with some
    other book's close compares a best-of-N draw to a single draw and reads
    +6.2pts at a 91% beat rate, which is the selection effect and not skill.
    Biased scopes are reported separately under `by_book_scope`. A None here
    means "no unbiased comparison was available", never "no edge".

    `unresolved_reasons` is the other half of the answer and should be read
    every time: `close_precedes_open` and `line_mismatch` are the two defects
    that made this endpoint's first number (-5.215) wrong, and they are now
    counted rather than silently folded into an average.
    """
    # Protected endpoint: requires admin token (enforced by before_request).
    date = str(request.args.get("date") or "").strip()
    sport = str(request.args.get("sport") or "").strip().lower()
    if not date:
        from syndicate.features.shared.timezone import central_today_iso

        # CENTRAL, not UTC. An MLB slate spans two UTC dates and one Central
        # one, and the openings are bucketed by the board's own Central date --
        # defaulting to a UTC today would ask for a file that does not exist
        # for five hours every evening.
        date = central_today_iso()
    if not sport:
        return jsonify({"ok": False, "error": "sport parameter required."}), 400
    include_rows = str(request.args.get("rows") or "").strip().lower() in {"1", "true", "yes"}
    try:
        from syndicate.features.shared.clv_join import compute_clv_for_date

        report = compute_clv_for_date(date, sport)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500
    if not include_rows:
        # Summary by default; the per-row detail is large and only wanted when
        # someone is chasing a specific pairing.
        report = {key: value for key, value in report.items() if key != "rows"}
    return jsonify({"ok": True, **report})


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
        from syndicate.features.wnba.sources import processed_root as wnba_processed_root
        from syndicate.features.wnba.sources import processed_roots as wnba_processed_roots
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500

    # processed_root() unconditionally prefers a "source_artifacts" candidate
    # root whether or not that location actually has anything written to it,
    # so report every candidate root's status rather than just the first one
    # -- that mismatch is exactly what made this endpoint necessary.
    # `#310`. Ask the WNBA module for its own roots (`processed_roots()`, which
    # calls `preferred_artifact_roots` with `wnba/sources.py`'s `__file__`)
    # instead of resolving them from THIS file.
    #
    # `repo_root_from` is hardcoded to `parents[3]`, which is only correct for
    # modules three packages deep. `ops.py` is two, so passing `__file__` from
    # here resolved the local-mirror candidates to the directory ABOVE the repo
    # and every file read `exists: false`.
    #
    # It is masked in production because `SYNDICATE_WNBA_SOURCE_ROOT` is set,
    # so `preferred_artifact_roots` takes its env branch and never touches
    # `repo_root` -- verified live 2026-08-09, this endpoint reported correct
    # `/opt/render/project/data/...` paths throughout. **The failure only
    # appears where that env var is absent, and there it reports a confident,
    # uniform "everything is missing".** That is the worst possible behaviour
    # for the endpoint someone reaches for to find out what is missing.
    candidate_roots = wnba_processed_roots()
    # `#310`. THE GRADER'S INPUTS COME FIRST, and they were absent from this
    # list entirely until now.
    #
    # This endpoint was built specifically to diagnose WNBA grading a zero, and
    # of the six files it originally checked, exactly ONE
    # (`props_recommendations`) is something the grader reads. Both `recon_*`
    # files -- which gate `{"available": False}` and therefore decide whether any
    # row is graded at all -- were not checked. `props_edges` and
    # `props_predictions` are checked, look alarming when absent, and **are
    # never read by the grader**.
    #
    # So "0 of 6 families" was a true measurement of the wrong six files, and
    # `17d4f203` was built on it. An instrument purpose-built for a defect,
    # answering a neighbouring question.
    #
    # `_score_market_games_day` / `_score_market_props_day` (live_lens_local.py)
    # read these in two gated PAIRS -- either side of a pair missing yields
    # `{"available": False}` and zero graded rows:
    #     games: recommendations   (or recommendations_sim)  +  recon_games
    #     props: props_recommendations                       +  recon_props
    # and both recon files are BUILT from `boxscores_{date}.csv`
    # (refresh_wnba_oddsapi_props._build_local_recon_{games,props}_artifact,
    # which return (0, None) without it), so it is listed too.
    grader_input_names = [
        f"recommendations_{date}.csv",
        f"recommendations_sim_{date}.csv",
        f"recon_games_{date}.csv",
        f"props_recommendations_{date}.csv",
        f"recon_props_{date}.csv",
        f"boxscores_{date}.csv",
    ]
    file_names = grader_input_names + [
        f"game_cards_{date}.csv",
        f"props_edges_{date}.csv",
        f"props_predictions_{date}.csv",
        f"props_recommendations_top_by_game_{date}.json",
        f"recommendations_slate_{date}.json",
    ]
    results: dict[str, Any] = {}
    for file_name in file_names:
        results[file_name] = [
            {"root": str(root), "is_processed_root_default": root == wnba_processed_root(), **_inspect_artifact_path(root / file_name)}
            for root in candidate_roots
        ]

    def _resolves_anywhere(file_name: str) -> bool:
        return any(bool(entry.get("exists")) for entry in results.get(file_name) or [])

    # `#310`. Answer the question the caller actually has -- "can this date be
    # graded" -- instead of leaving them to reassemble it from a file list.
    # Reported per PAIR because that is how the grader gates: either side
    # missing yields `{"available": False}`, and a reader looking at six
    # independent booleans has no way to know that.
    games_pair = {
        "recommendations": _resolves_anywhere(f"recommendations_{date}.csv") or _resolves_anywhere(f"recommendations_sim_{date}.csv"),
        "recon_games": _resolves_anywhere(f"recon_games_{date}.csv"),
    }
    props_pair = {
        "props_recommendations": _resolves_anywhere(f"props_recommendations_{date}.csv"),
        "recon_props": _resolves_anywhere(f"recon_props_{date}.csv"),
    }
    grader_readiness = {
        "games": {**games_pair, "gradeable": all(games_pair.values())},
        "props": {**props_pair, "gradeable": all(props_pair.values())},
        # The recon builders' own precondition. If this is present and the recon
        # files are not, the builder had what it needed and still produced
        # nothing -- which is a DIFFERENT defect from missing inputs and the two
        # are otherwise indistinguishable.
        "boxscores_present": _resolves_anywhere(f"boxscores_{date}.csv"),
        "note": "resolved per requested file across every candidate root (`#309`), not against processed_root alone",
    }

    return jsonify(
        {
            "ok": True,
            "date": date,
            "processed_root": str(wnba_processed_root()),
            "candidate_roots": [str(root) for root in candidate_roots],
            "grader_input_files": grader_input_names,
            "grader_readiness": grader_readiness,
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
        from syndicate.features.wnba.sources import processed_root as wnba_processed_root
        from syndicate.features.wnba.sources import processed_roots as wnba_processed_roots
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500

    # `#310`. Ask the WNBA module for its own roots (`processed_roots()`, which
    # calls `preferred_artifact_roots` with `wnba/sources.py`'s `__file__`)
    # instead of resolving them from THIS file.
    #
    # `repo_root_from` is hardcoded to `parents[3]`, which is only correct for
    # modules three packages deep. `ops.py` is two, so passing `__file__` from
    # here resolved the local-mirror candidates to the directory ABOVE the repo
    # and every file read `exists: false`.
    #
    # It is masked in production because `SYNDICATE_WNBA_SOURCE_ROOT` is set,
    # so `preferred_artifact_roots` takes its env branch and never touches
    # `repo_root` -- verified live 2026-08-09, this endpoint reported correct
    # `/opt/render/project/data/...` paths throughout. **The failure only
    # appears where that env var is absent, and there it reports a confident,
    # uniform "everything is missing".** That is the worst possible behaviour
    # for the endpoint someone reaches for to find out what is missing.
    candidate_roots = wnba_processed_roots()
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
        from syndicate.features.wnba.sources import processed_root as wnba_processed_root
        from syndicate.features.wnba.sources import processed_roots as wnba_processed_roots
    except Exception as exc:
        return jsonify({"ok": False, "error": f"ImportError: {type(exc).__name__}: {exc}"}), 500

    # `#310`. Ask the WNBA module for its own roots (`processed_roots()`, which
    # calls `preferred_artifact_roots` with `wnba/sources.py`'s `__file__`)
    # instead of resolving them from THIS file.
    #
    # `repo_root_from` is hardcoded to `parents[3]`, which is only correct for
    # modules three packages deep. `ops.py` is two, so passing `__file__` from
    # here resolved the local-mirror candidates to the directory ABOVE the repo
    # and every file read `exists: false`.
    #
    # It is masked in production because `SYNDICATE_WNBA_SOURCE_ROOT` is set,
    # so `preferred_artifact_roots` takes its env branch and never touches
    # `repo_root` -- verified live 2026-08-09, this endpoint reported correct
    # `/opt/render/project/data/...` paths throughout. **The failure only
    # appears where that env var is absent, and there it reports a confident,
    # uniform "everything is missing".** That is the worst possible behaviour
    # for the endpoint someone reaches for to find out what is missing.
    candidate_roots = wnba_processed_roots()
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


def _board_snapshot_read_summary(snapshot: Any) -> dict[str, Any]:
    """The read-side numbers `#338` needs, computed ONCE for both trace blocks.

    THIS IS A HELPER BECAUSE THE ENDPOINT HAS TWO NEAR-IDENTICAL BLOCKS AND MY
    FIRST FIX LANDED ON ONLY ONE. `/api/ops/intelligence/candidate-trace` builds
    `read_only_trace` (the `?read_only=1` fast path) and `read_path_trace` (the
    full path) from copy-pasted read logic. The `None` that sent a debugging
    session after the instrument came from the SECOND one; the fix went to the
    first, deployed, and the trace still answered `None`.

    Same shape as `#327` -- two emitters, one patched -- where the lesson was to
    EXTRACT rather than patch the second copy. Both blocks call this now, so a
    third fix cannot land on one and miss the other.

    Three numbers rather than one, because `#338` is precisely about them
    disagreeing:
      * `candidate_count` -- the stored int at the TOP level. The old code never
        looked at it, checking `candidates`/`top_opportunities` instead, which do
        not exist at the top level (`_intelligence_board_snapshot_payload` nests
        the whole state under `response`), so both `.get()`s missed and
        `else None` reported "absent" for a field one level down.
      * the list lengths -- capped at 150 by `_default_unbounded_candidate_cap`
        BY DESIGN, so a trace reporting this as the candidate count reports the cap.
      * `by_sport` total -- the true pool when the overview is complete, and a
        partial one when `#285`'s headroom guard truncated it.
    """
    summary: dict[str, Any] = {"board_snapshot_read_is_dict": isinstance(snapshot, dict)}
    if not isinstance(snapshot, dict):
        return summary
    response = snapshot.get("response") if isinstance(snapshot.get("response"), dict) else {}
    summary["board_snapshot_read_keys"] = list(snapshot.keys())
    summary["board_snapshot_read_latest_key"] = snapshot.get("latest_key")
    stored = snapshot.get("candidate_count")
    summary["board_snapshot_read_candidate_count"] = int(stored) if isinstance(stored, (int, float)) else None
    for field in ("top_opportunities", "recommendations", "candidates"):
        value = response.get(field)
        if value is None:
            value = snapshot.get(field)
        summary[f"board_snapshot_read_{field}_len"] = len(value) if isinstance(value, list) else None
    by_sport = response.get("by_sport") or snapshot.get("by_sport")
    if isinstance(by_sport, dict):
        summary["board_snapshot_read_by_sport_sports"] = sorted(by_sport)
        summary["board_snapshot_read_by_sport_total"] = sum(
            len(items) for items in by_sport.values() if isinstance(items, list)
        )
    summary["board_snapshot_read_updated_at"] = snapshot.get("updated_at") or snapshot.get("generated_at")
    return summary


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

            # #317/#320: expanded, or this trace counts zero candidates on a
            # healthy board -- the payload is aliased and compressed on the wire.
            from pipeline.intelligence_state import expand_persisted_state as _expand_persisted_state_public

            board_snapshot_raw = _expand_persisted_state_public(_read_json_file(_BOARD_SNAPSHOT_PATH))
            read_only_trace.update(_board_snapshot_read_summary(board_snapshot_raw))

            state_raw = _expand_persisted_state_public(_read_json_file(_STATE_PATH))
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
        # This fast path is genuinely sport-agnostic -- it reads the whole
        # board's persisted state and snapshot paths, which have no per-sport
        # dimension. Say that outright rather than accepting ?sport= and
        # returning a response that mentions it nowhere, which is how the
        # main path's partial scoping went unnoticed in the first place.
        return jsonify({
            "ok": True,
            "date": date,
            "requested_sport": sport_filter,
            "sport_filter_applies": False,
            "scope": "all_sports",
            "read_only_trace": read_only_trace,
        })

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

    # 2026-08-04: ?sport= used to reach ONLY the per-sport loop at the bottom.
    # Everything above it -- these preferences (hardcoded sport="all") and the
    # fallback_merge_trace built from them -- silently described every sport
    # while sitting at the top of a response fetched with ?sport=mlb. Those
    # are the numbers a reader looks at first, so "collect=412, filtered=0"
    # got read as MLB's drop-off when it was the whole board's. Same class of
    # dishonesty as /api/ops/odds-history/matchup-coverage's date param, fixed
    # the same day: scope what can be scoped, and label what genuinely cannot.
    scoped_overview = [
        sport_row
        for sport_row in overview
        if isinstance(sport_row, dict)
        and (not sport_filter or str(sport_row.get("slug") or "").strip().lower() == sport_filter)
    ]
    preferences = _query_preferences(
        "top edges today",
        mode="recommendation",
        sport=sport_filter or "all",
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

        fallback_merge_trace["0_scope"] = sport_filter or "all_sports"
        raw = _cc(scoped_overview, preferences, None)
        fallback_merge_trace["1_collect_candidates_count"] = len(raw)
        if raw:
            tracked = _trf()
            advanced_by_sport = {
                str(sport_row.get("slug") or "sport").strip().lower(): _airfs(sport_row, tracked)
                for sport_row in scoped_overview
                if isinstance(sport_row, dict)
            }
            scored = _sc(raw, advanced_by_sport, preferences, pipeline="ops_trace")
            fallback_merge_trace["2_scored_count"] = len(scored)
            # sport=sport_filter, not sport=None: filter_candidates' own
            # sport argument is what the real pipeline varies, so a scoped
            # trace has to vary it too or stage 3 is answering a different
            # question than stages 1 and 2.
            filtered = _fc(scored, sport=sport_filter)
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

        # #317/#320: expanded, for the same reason as the sibling trace above.
        from pipeline.intelligence_state import expand_persisted_state as _expand_persisted_state_public

        board_snapshot_raw = _expand_persisted_state_public(_read_json_file(_BOARD_SNAPSHOT_PATH))
        read_path_trace.update(_board_snapshot_read_summary(board_snapshot_raw))

        # #338: expanded for the same reason as the board snapshot above -- #322
        # compresses this file's `snapshots`, and the envelope still passes
        # isinstance(dict), so a raw read degrades quietly into the wrong keys.
        state_raw = _expand_persisted_state_public(_read_json_file(_STATE_PATH))
        read_path_trace["state_read_is_dict"] = isinstance(state_raw, dict)
        if isinstance(state_raw, dict):
            read_path_trace["state_read_latest_key"] = state_raw.get("latest_key")
            snapshots = state_raw.get("snapshots")
            read_path_trace["state_read_snapshot_keys"] = list(snapshots.keys()) if isinstance(snapshots, dict) else None
            read_path_trace["state_read_updated_at"] = state_raw.get("updated_at")
    except Exception as exc:
        read_path_trace["error"] = f"{type(exc).__name__}: {exc}"

    overview_slugs = [
        str(sport_row.get("slug") or "").strip().lower() for sport_row in overview if isinstance(sport_row, dict)
    ]
    result: dict[str, Any] = {
        "ok": True,
        "date": date,
        "requested_sport": sport_filter,
        # _build_candidate_pool takes no sport argument -- it builds the whole
        # board's pool by design, and that IS what the background loop does.
        # These three therefore stay pool-wide even when ?sport= is set, so
        # they say so rather than letting a scoped request imply otherwise.
        "pool_wide_sections": ["manifest_check", "full_pool_check", "app_context_pool_check"],
        "sports_in_overview": overview_slugs,
        # Explicit, because an out-of-season or misspelled sport otherwise
        # returns a bare empty list that reads like "this sport produced no
        # candidates" rather than "this sport was never in the overview".
        "requested_sport_present": (sport_filter in overview_slugs) if sport_filter else None,
        "preferences": preferences,
        "manifest_check": manifest_check,
        "full_pool_check": full_pool_check,
        "app_context_pool_check": app_context_pool_check,
        "fallback_merge_trace": fallback_merge_trace,
        "read_path_trace": read_path_trace,
        "sports": [],
    }
    for sport in scoped_overview:
        if not isinstance(sport, dict):
            continue
        slug = str(sport.get("slug") or "").strip().lower()
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
    # Was hardcoded mode="fast" here regardless of what the caller sent --
    # _start_refresh_job's own mode= kwarg unconditionally overwrites
    # launch_payload["mode"] before _payload_value ever gets a chance to read
    # the request body's own "mode" key, so no caller of this endpoint could
    # ever trigger a "full" refresh through it. Confirmed live 2026-08-05: a
    # manually-triggered soccer refresh through this exact route ran
    # end-to-end (all steps ok) but never reached
    # refresh_odds_sources.py's post-refresh odds_history sync, because that
    # call sits behind an `if refresh_mode == "fast": return` a few lines
    # earlier in that script -- a manual "run odds refresh now" trigger
    # could never populate movement data for anyone using this endpoint.
    # Defaults to fast (unchanged for a bare POST), but a caller that
    # explicitly asks for "full" now gets it.
    requested_mode = str((payload or {}).get("mode") or "").strip().lower()
    # Default to manifest_only, same reason and same fix as
    # /api/ops/full-refresh/run just below -- without an explicit launch_mode
    # this falls through to SYNDICATE_REFRESH_LAUNCH_MODE, detached_subprocess
    # on the WEB service, spawning refresh_odds_sources.py inside web's 2GB
    # container. Confirmed live 2026-08-06: two manual triggers through this
    # exact route (soccer alone, then the full mlb/wnba/nfl/soccer combo) sat
    # running/never finished for 13+ minutes each and had to be canceled --
    # versus the same commands completing in ~3.5min, cleanly, when they ran
    # on refresh-worker's 4GB box instead. manifest_only routes the job onto
    # refresh-worker's own claim loop (scripts/run_refresh_worker.py's
    # _has_pending_external_contract/_spawn_pending_job), which already
    # exists and already runs every autorun -- this endpoint was the one
    # caller not using it. An explicit launch_mode in the request still wins.
    payload = dict(payload or {})
    payload.setdefault("launch_mode", "manifest_only")
    try:
        job_id, job = _start_refresh_job(payload, mode=requested_mode or "fast")
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
            # Same fix, same reason as /api/ops/odds-refresh/run just above --
            # this dashboard-form route had the identical gap: no launch_mode
            # passed at all, so it always fell through to detached_subprocess
            # on whichever service serves the click (web). An explicit
            # launch_mode field in the form/request still wins.
            launch_mode=_payload_value(payload, "launch_mode", "manifest_only"),
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