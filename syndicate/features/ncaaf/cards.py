from __future__ import annotations

import csv
import json
import os
import re
import statistics
from typing import Any
from functools import lru_cache
from pathlib import Path

from syndicate.features.ncaaf.sources import available_weeks
from syndicate.features.ncaaf.sources import build_module_links
from syndicate.features.ncaaf.sources import default_ncaaf_source_root
from syndicate.features.ncaaf.sources import default_season
from syndicate.features.ncaaf.sources import default_week
from syndicate.features.ncaaf.sources import format_moneyline
from syndicate.features.ncaaf.sources import format_num
from syndicate.features.ncaaf.sources import format_pct
from syndicate.features.ncaaf.sources import load_json
from syndicate.features.ncaaf.sources import summary_path
from syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader import load_games_season
from syndicate.features.ncaaf.smartsim2_blend import compute_blend
from syndicate.features.ncaaf.smartsim2_projection import CONSENSUS_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_projection import LEGACY_ENGINE_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SMARTSIM2_PUBLIC_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SMARTSIM2_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SmartSimNcaafProjection
from syndicate.features.ncaaf.smartsim2_projection import read_projection_artifact
from syndicate.features.ncaaf.smartsim2_trial_monitoring import record_trial_page_view
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.shared.team_branding import read_team_branding_snapshot
from syndicate.features.shared.team_branding import team_branding_index_by_id


_WEEK1_PUBLISHABLE_MATCHUPS = {
    ("Western Michigan", "Michigan State"),
    ("Kennesaw State", "Wake Forest"),
    ("UNLV", "Sam Houston"),
    ("San Jose State", "Central Michigan"),
    ("Tennessee", "Syracuse"),
    ("Ball State", "Purdue"),
    ("Coastal Carolina", "Virginia"),
    ("Eastern Michigan", "Texas State"),
}

_WEEK1_SUPPRESSED_MATCHUPS = {
    ("Tarleton State", "Army"),
    ("Bethune-Cookman", "Florida International"),
    ("Nicholls", "Troy"),
    ("SE Louisiana", "Louisiana Tech"),
    ("Bryant", "New Mexico State"),
}

_WEEK1_COVERAGE_PROFILE = {
    "publishable": {
        "coverage_score": 1.0,
        "coverage_tier": "A",
        "publication_status": "publishable",
        "publication_priority": 3,
    },
    "suppressed": {
        "coverage_score": 0.675,
        "coverage_tier": "C",
        "publication_status": "suppressed",
        "publication_priority": 1,
    },
}


_NCAAF_CARD_CONTRACT_VERSION = "1"


@lru_cache(maxsize=1)
def _prediction_rows() -> tuple[dict[str, Any], ...]:
    data_root = default_ncaaf_source_root() / "data"
    if not data_root.exists():
        return ()
    candidate_paths = sorted(
        data_root.glob("college_football_schedule_*_predicted_totals_enhanced*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    fallback_rows: tuple[dict[str, Any], ...] = ()
    for path in candidate_paths:
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                headers = set(reader.fieldnames or [])
                required = {"home_team", "away_team", "predicted_home_points", "predicted_away_points", "predicted_total_points"}
                if not required.issubset(headers):
                    continue
                rows = tuple(dict(row) for row in reader)
                if "model_home_win_prob" in headers:
                    return rows
                if not fallback_rows:
                    fallback_rows = rows
        except Exception:
            continue
    return fallback_rows


@lru_cache(maxsize=1)
def _prediction_source_path() -> Path | None:
    data_root = default_ncaaf_source_root() / "data"
    if not data_root.exists():
        return None
    candidate_paths = sorted(
        data_root.glob("college_football_schedule_*_predicted_totals_enhanced*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidate_paths:
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                headers = set(reader.fieldnames or [])
                required = {"home_team", "away_team", "predicted_home_points", "predicted_away_points", "predicted_total_points"}
                if required.issubset(headers):
                    return path
        except Exception:
            continue
    return None


_SMARTSIM2_PROJECTION_FILENAME_RE = re.compile(r"^smartsim2_projections_(\d{4})_wk(\d+)\.csv$")


@lru_cache(maxsize=1)
def _smartsim2_standalone_seasons_and_weeks() -> dict[int, list[int]]:
    """Every (season, week) with a real, already-generated SmartSim 2.0
    projection artifact on disk -- independent of whether the legacy engine
    has any data for that season. The engine's own predicted-totals snapshot
    is only ever refreshed for its own season (see the 2026 season bootstrap:
    NCAAFCompare, the engine's real source, was unavailable), so this is the
    only reliable signal for "is there real projection data for a season the
    engine hasn't touched"."""
    data_root = default_ncaaf_source_root() / "data"
    if not data_root.exists():
        return {}
    result: dict[int, list[int]] = {}
    for path in data_root.glob("smartsim2_projections_*_wk*.csv"):
        match = _SMARTSIM2_PROJECTION_FILENAME_RE.match(path.name)
        if not match:
            continue
        season = int(match.group(1))
        week = int(match.group(2))
        result.setdefault(season, []).append(week)
    for season in result:
        result[season] = sorted(set(result[season]))
    return result


def _engine_seasons_and_weeks() -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    for row in _prediction_rows():
        try:
            season = int(str(row.get("season") or "").strip())
            week = int(str(row.get("week") or "").strip())
        except (TypeError, ValueError):
            continue
        result.setdefault(season, []).append(week)
    for season in result:
        result[season] = sorted(set(result[season]))
    return result


def _engine_rows_for_season_week(season: int, week: int) -> list[dict[str, Any]]:
    """Reuses ``_runtime_prediction_rows()``'s own completeness filtering and
    (away, home) dedup (a row missing predicted points, or a duplicate
    matchup, was never a valid engine row) and adds a season filter on top --
    harmless today (the engine CSV has only ever held one season), but
    required once its glob covers more than one season's file."""
    return [row for row in _runtime_prediction_rows(week) if str(row.get("season") or "").strip() == str(season)]


def _resolve_ncaaf_active_season_and_weeks() -> tuple[int, list[int]]:
    """The season/week source of truth for the runtime cards page: prefers
    whichever season has the most recent real data across *either* the
    legacy engine's predicted-totals snapshot or SmartSim 2.0's own
    projection artifacts, so a season the engine has no data for is still
    reachable once real SmartSim 2.0 projections exist for it."""
    engine_seasons = _engine_seasons_and_weeks()
    smartsim2_seasons = _smartsim2_standalone_seasons_and_weeks()
    all_seasons = set(engine_seasons) | set(smartsim2_seasons)
    if not all_seasons:
        return default_season(), []
    active_season = max(all_seasons)
    weeks = sorted(set(engine_seasons.get(active_season, [])) | set(smartsim2_seasons.get(active_season, [])))
    return active_season, weeks


def _smartsim2_standalone_market_lines(season: int, week: int) -> dict[tuple[str, str], dict[str, float | None]]:
    data_root = default_ncaaf_source_root() / "data"
    path = data_root / f"cfbd_lines_{season}_wk{week}.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            games = json.load(handle)
    except Exception:
        return {}
    index: dict[tuple[str, str], dict[str, float | None]] = {}
    if not isinstance(games, list):
        return index
    for game in games:
        if not isinstance(game, dict):
            continue
        lines = game.get("lines") if isinstance(game.get("lines"), list) else []
        spreads = [line["spread"] for line in lines if isinstance(line, dict) and line.get("spread") is not None]
        totals = [line["overUnder"] for line in lines if isinstance(line, dict) and line.get("overUnder") is not None]
        market_margin = -statistics.mean(spreads) if spreads else None
        market_total = statistics.mean(totals) if totals else None
        key = (_normalize_text(game.get("homeTeam")), _normalize_text(game.get("awayTeam")))
        index[key] = {"market_margin": market_margin, "market_total": market_total}
    return index


def _smartsim2_standalone_rows(season: int, week: int) -> list[dict[str, Any]]:
    """Real schedule + real SmartSim 2.0 projections, joined directly --
    used only for a (season, week) the legacy engine has no rows for, so
    this never overrides or competes with the engine's own path."""
    try:
        schedule = load_games_season(season)
    except Exception:
        return []
    projection_index = _smartsim2_projection_index(season, week)
    if not projection_index:
        return []
    lines_index = _smartsim2_standalone_market_lines(season, week)
    rows: list[dict[str, Any]] = []
    for game in schedule:
        if not isinstance(game, dict) or game.get("week") != week:
            continue
        if game.get("homeClassification") != "fbs" or game.get("awayClassification") != "fbs":
            continue
        home_team = str(game.get("homeTeam") or "").strip()
        away_team = str(game.get("awayTeam") or "").strip()
        if not home_team or not away_team:
            continue
        key = (_normalize_text(home_team), _normalize_text(away_team))
        projection = projection_index.get(key)
        if projection is None:
            continue
        market = lines_index.get(key, {"market_margin": None, "market_total": None})
        rows.append(
            {
                "game_id": str(game.get("id") or f"{season}_{week}_{home_team}_{away_team}"),
                "home_team": home_team,
                "away_team": away_team,
                "start_date": game.get("startDate"),
                "venue": game.get("venue"),
                "projection": projection,
                "market_margin": market.get("market_margin"),
                "market_total": market.get("market_total"),
            }
        )
    return rows


def _prediction_weeks() -> list[int]:
    weeks = sorted(
        {
            int(str(row.get("week") or "0").strip() or 0)
            for row in _prediction_rows()
            if str(row.get("week") or "").strip().isdigit()
        }
    )
    return [week for week in weeks if week > 0]


@lru_cache(maxsize=1)
def _prediction_index() -> dict[tuple[str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in _prediction_rows():
        week = str(row.get("week") or "").strip()
        home_team = _normalize_text(row.get("home_team"))
        away_team = _normalize_text(row.get("away_team"))
        if not week or not home_team or not away_team:
            continue
        index.setdefault((week, away_team, home_team), row)
    return index


_BLEND_TRIAL_DIAGNOSTICS_ENV_VAR = "SMARTSIM_BLEND_TRIAL_DIAGNOSTICS"


def _blend_trial_diagnostics_enabled() -> bool:
    """Internal-only gate for the Phase 2B blend-trial diagnostic view.

    Off by default (production/public behavior is completely unaffected).
    Deliberately an environment variable, not a query parameter or request
    header -- it cannot be toggled by an external HTTP request, only by
    whoever controls the process environment. See smartsim_blend_trial_plan.md
    Stage 1 and smartsim_blend_trial_report.md.
    """
    return os.environ.get(_BLEND_TRIAL_DIAGNOSTICS_ENV_VAR, "").strip().lower() in {"1", "true", "yes"}


# --- Phase 3: Public Blend Trial rollout controls -------------------------
# Separate and independent from the Phase 2B internal-diagnostics flag above
# -- that flag is untouched and still governs the engineer-only view. These
# control whether a *public* (but deliberately narrow) audience can see the
# same three-way comparison, styled as a real feature rather than a
# diagnostic. Two independent mechanisms, either of which grants visibility,
# both gated behind one master switch -- see smartsim_public_trial_report.md.
_PUBLIC_TRIAL_MASTER_ENV_VAR = "SMARTSIM_PUBLIC_TRIAL_ENABLED"
_PUBLIC_TRIAL_TOKEN_ALLOWLIST_ENV_VAR = "SMARTSIM_PUBLIC_TRIAL_TOKENS"
_PUBLIC_TRIAL_IP_ALLOWLIST_ENV_VAR = "SMARTSIM_PUBLIC_TRIAL_IP_ALLOWLIST"
_PUBLIC_TRIAL_TOKEN_PARAM = "smartsim_trial"


def _public_trial_master_enabled() -> bool:
    """The kill switch: if this is off, no request-level check is even attempted."""
    return os.environ.get(_PUBLIC_TRIAL_MASTER_ENV_VAR, "").strip().lower() in {"1", "true", "yes"}


def _env_list(env_var: str) -> frozenset[str]:
    raw = os.environ.get(env_var, "")
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def _public_trial_visible_for_request() -> bool:
    """Per-request gate for the public blend trial.

    Requires the master switch to be on, AND (a request context to exist --
    this is always False for CLI/batch callers such as the projection
    generation script or tests run outside an app context -- AND (the
    request's trial token matches the configured allowlist, OR the client's
    IP matches the configured IP allowlist)). Either allowlist mechanism is
    independently sufficient once the master switch is on; both default to
    empty (nobody whitelisted) so enabling the master switch alone still
    shows nothing until an allowlist is actually configured.
    """
    if not _public_trial_master_enabled():
        return False
    try:
        from flask import request as flask_request
        from flask import has_request_context
    except Exception:  # noqa: BLE001 - flask always installed in this app, but stay defensive
        return False
    if not has_request_context():
        return False

    token_allowlist = _env_list(_PUBLIC_TRIAL_TOKEN_ALLOWLIST_ENV_VAR)
    if token_allowlist:
        token = str(flask_request.args.get(_PUBLIC_TRIAL_TOKEN_PARAM) or flask_request.cookies.get(_PUBLIC_TRIAL_TOKEN_PARAM) or "").strip()
        if token and token in token_allowlist:
            return True

    ip_allowlist = _env_list(_PUBLIC_TRIAL_IP_ALLOWLIST_ENV_VAR)
    if ip_allowlist and str(flask_request.remote_addr or "").strip() in ip_allowlist:
        return True

    return False


@lru_cache(maxsize=16)
def _smartsim2_projection_index(season: int, week: int) -> dict[tuple[str, str], SmartSimNcaafProjection]:
    """Shadow-mode lookup for SmartSim 2.0 projections, keyed by (home, away).

    Returns an empty dict (never raises) when the artifact for this season/week
    has not been generated yet -- SmartSim 2.0 availability must never affect
    the legacy engine's own output. See smartsim_shadow_mode_report.md.
    """
    data_root = default_ncaaf_source_root() / "data"
    try:
        projections = read_projection_artifact(season=season, week=week, data_root=data_root)
    except Exception:
        return {}
    return {(_normalize_text(p.home_team), _normalize_text(p.away_team)): p for p in projections}


def _attach_smartsim2_shadow_fields(
    scoreboard: dict[str, Any],
    *,
    row: dict[str, Any],
    week: int,
    engine_home_points: float | None,
    engine_away_points: float | None,
    engine_total_points: float | None,
    engine_margin: float | None,
) -> None:
    """Additive-only: adds smartsim2_*/blend_* keys, never touches existing ones.

    Phase 1 (shadow mode): these fields are captured for monitoring only and
    are not read by any template today (verified against syndicate/templates
    before this integration landed) -- adding them cannot change published
    output. See smartsim_production_integration_plan.md task 5.
    """
    scoreboard["smartsim2_available"] = False
    season = default_season()
    index = _smartsim2_projection_index(season, week)
    home_name = _normalize_text(row.get("home_team"))
    away_name = _normalize_text(row.get("away_team"))
    projection = index.get((home_name, away_name))
    if projection is None:
        return

    scoreboard["smartsim2_available"] = True
    scoreboard["smartsim2_source_label"] = SMARTSIM2_SOURCE_LABEL
    scoreboard["smartsim2_home_points"] = projection.home_score_mean
    scoreboard["smartsim2_away_points"] = projection.away_score_mean
    scoreboard["smartsim2_total_points"] = projection.total_mean
    scoreboard["smartsim2_margin"] = projection.margin_mean
    scoreboard["smartsim2_margin_stdev"] = projection.margin_stdev
    scoreboard["smartsim2_total_stdev"] = projection.total_stdev
    scoreboard["smartsim2_home_win_rate"] = projection.home_win_rate
    scoreboard["smartsim2_profile_name"] = projection.profile_name
    scoreboard["smartsim2_rating_source"] = projection.rating_source

    if engine_home_points is None or engine_away_points is None or engine_total_points is None:
        return
    if engine_margin is None:
        engine_margin = engine_home_points - engine_away_points
    result = compute_blend(
        engine_margin=engine_margin,
        smartsim_margin=projection.margin_mean,
        engine_total=engine_total_points,
        smartsim_total=projection.total_mean,
    )
    scoreboard["blend_margin"] = result.margin
    scoreboard["blend_total"] = result.total
    scoreboard["blend_margin_applied"] = result.smartsim_margin_used
    scoreboard["blend_total_applied"] = result.total_blended

    if _public_trial_visible_for_request():
        visibility_mode = "public_trial"
    elif _blend_trial_diagnostics_enabled():
        visibility_mode = "internal_diagnostic"
    else:
        visibility_mode = None

    if visibility_mode is not None:
        smartsim2_label = SMARTSIM2_PUBLIC_LABEL if visibility_mode == "public_trial" else SMARTSIM2_SOURCE_LABEL
        scoreboard["projection_sources_mode"] = visibility_mode
        scoreboard["projection_sources"] = {
            "enhanced_totals_engine": {
                "label": LEGACY_ENGINE_SOURCE_LABEL,
                "home_points": engine_home_points,
                "away_points": engine_away_points,
                "margin": engine_margin,
                "total": engine_total_points,
            },
            "smartsim2": {
                "label": smartsim2_label,
                "home_points": projection.home_score_mean,
                "away_points": projection.away_score_mean,
                "margin": projection.margin_mean,
                "total": projection.total_mean,
                "available": True,
            },
            "consensus_projection": {
                "label": CONSENSUS_SOURCE_LABEL,
                "margin": result.margin,
                "total": result.total,
                "margin_blended": result.smartsim_margin_used,
                "total_blended": result.total_blended,
            },
        }


def _scoreboard_projection(row: dict[str, Any], week: int) -> dict[str, Any]:
    lookup = _prediction_index().get((str(week), _normalize_text(row.get("away_team")), _normalize_text(row.get("home_team"))))
    if not lookup:
        return {}
    home_points = _safe_float(lookup.get("predicted_home_points"))
    away_points = _safe_float(lookup.get("predicted_away_points"))
    total_points = _safe_float(lookup.get("predicted_total_points"))
    margin = _safe_float(lookup.get("predicted_win_margin"))
    if margin is None and home_points is not None and away_points is not None:
        margin = home_points - away_points
    win_probability = _safe_float(lookup.get("model_home_win_prob"))
    home_name = str(row.get("home_team") or "Home").strip() or "Home"
    away_name = str(row.get("away_team") or "Away").strip() or "Away"
    if margin is None:
        spread_label = "-"
    elif margin >= 0:
        spread_label = f"{home_name} by {abs(margin):.1f}"
    else:
        spread_label = f"{away_name} by {abs(margin):.1f}"
    kickoff = str(lookup.get("start_date_api") or lookup.get("start_date") or "").strip()
    venue = str(lookup.get("venue") or "").strip()
    return {
        "home_points": _format_decimal(home_points, places=1),
        "away_points": _format_decimal(away_points, places=1),
        "total_points": _format_decimal(total_points, places=1),
        "spread_label": spread_label,
        "win_probability": format_pct(win_probability),
        "source_label": "Predicted totals artifact",
        "kickoff": kickoff,
        "venue": venue,
    }


def _runtime_scoreboard_projection(row: dict[str, Any], week: int) -> dict[str, Any]:
    home_points = _safe_float(row.get("predicted_home_points"))
    away_points = _safe_float(row.get("predicted_away_points"))
    total_points = _safe_float(row.get("predicted_total_points"))
    margin = _safe_float(row.get("predicted_win_margin"))
    if margin is None and home_points is not None and away_points is not None:
        margin = home_points - away_points
    win_probability = _normalize_probability(row.get("model_home_win_prob"))
    home_name = str(row.get("home_team") or "Home").strip() or "Home"
    away_name = str(row.get("away_team") or "Away").strip() or "Away"
    if margin is None:
        spread_label = "-"
    elif margin >= 0:
        spread_label = f"{home_name} by {abs(margin):.1f}"
    else:
        spread_label = f"{away_name} by {abs(margin):.1f}"
    kickoff = str(row.get("start_date_api") or row.get("start_date") or "").strip()
    venue = str(row.get("venue") or "").strip()
    scoreboard = {
        "home_points": _format_decimal(home_points, places=1),
        "away_points": _format_decimal(away_points, places=1),
        "total_points": _format_decimal(total_points, places=1),
        "spread_label": spread_label,
        "win_probability": format_pct(win_probability),
        "source_label": LEGACY_ENGINE_SOURCE_LABEL,
        "kickoff": kickoff,
        "venue": venue,
    }
    _attach_smartsim2_shadow_fields(
        scoreboard,
        row=row,
        week=week,
        engine_home_points=home_points,
        engine_away_points=away_points,
        engine_total_points=total_points,
        engine_margin=margin,
    )
    return scoreboard


def _runtime_publication_profile(scoreboard: dict[str, Any]) -> dict[str, Any]:
    home_points = _safe_float(str(scoreboard.get("home_points") or "").strip())
    away_points = _safe_float(str(scoreboard.get("away_points") or "").strip())
    total_points = _safe_float(str(scoreboard.get("total_points") or "").strip())
    win_probability = _normalize_probability(scoreboard.get("win_probability"))
    margin = None
    if home_points is not None and away_points is not None:
        margin = abs(home_points - away_points)
    edge_strength = abs((win_probability or 0.5) - 0.5)
    spread_strength = min((margin or 0.0) / 28.0, 1.0)
    total_strength = min((total_points or 0.0) / 100.0, 1.0)
    coverage_score = round(min(1.0, max(0.0, (edge_strength * 0.55) + (spread_strength * 0.30) + (total_strength * 0.15))), 3)
    if coverage_score >= 0.75:
        coverage_tier = "A"
    elif coverage_score >= 0.60:
        coverage_tier = "B"
    elif coverage_score >= 0.45:
        coverage_tier = "C"
    else:
        coverage_tier = "D"
    publication_ready = coverage_tier in {"A", "B"}
    publication_status = "publishable" if publication_ready else "suppressed"
    if publication_ready:
        coverage_warnings = ["runtime candidate passes publication threshold"]
    else:
        coverage_warnings = ["runtime candidate below publication threshold"]
    return {
        "coverage_score": coverage_score,
        "coverage_tier": coverage_tier,
        "coverage_warnings": coverage_warnings,
        "publication_status": publication_status,
        "publication_priority": {"A": 3, "B": 2, "C": 1, "D": 0}.get(coverage_tier, 0),
        "publication_ready": publication_ready,
        "ready_label": "Publication ready" if publication_ready else "Publication blocked",
        "tier_badges": _tier_badges(coverage_tier),
    }


def _runtime_prediction_rows(week: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _prediction_rows():
        try:
            row_week = int(str(row.get("week") or "").strip())
        except Exception:
            continue
        if row_week != int(week):
            continue
        home_team = str(row.get("home_team") or "").strip()
        away_team = str(row.get("away_team") or "").strip()
        if not home_team or not away_team:
            continue
        if any(
            _safe_float(row.get(field)) is None
            for field in ("predicted_home_points", "predicted_away_points", "predicted_total_points")
        ):
            continue
        rows.append(dict(row))
    best_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (_normalize_text(row.get("away_team")), _normalize_text(row.get("home_team")))
        if not all(key):
            continue
        best_rows.setdefault(key, row)
    ordered_rows = sorted(
        best_rows.values(),
        key=lambda row: (
            abs((_safe_float(row.get("predicted_home_points")) or 0.0) - (_safe_float(row.get("predicted_away_points")) or 0.0)),
            _safe_float(row.get("predicted_total_points")) or 0.0,
        ),
        reverse=True,
    )
    return ordered_rows


def _processed_artifact_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "ncaaf_source" / "source_artifacts" / "data" / "processed" / Path(*parts)


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def _team_registry_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("team_registry", "ncaaf_team_registry.csv")))


@lru_cache(maxsize=1)
def _returning_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("returning_production", "ncaaf_returning_production_snapshot.csv")))


@lru_cache(maxsize=1)
def _coach_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("coach_continuity", "ncaaf_coach_continuity_snapshot.csv")))


@lru_cache(maxsize=1)
def _transfer_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("transfers", "ncaaf_transfer_portal_snapshot.csv")))


@lru_cache(maxsize=1)
def _roster_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_load_csv_rows(_processed_artifact_path("roster", "ncaaf_roster_snapshot.csv")))


@lru_cache(maxsize=1)
def _team_branding_index() -> dict[str, Any]:
    rows = read_team_branding_snapshot(_processed_artifact_path("team_branding", "ncaaf_team_branding.csv"))
    return team_branding_index_by_id(rows)


def _resolve_branding(team_id: str) -> Any | None:
    return _team_branding_index().get(str(team_id).strip()) if team_id else None


def _team_registry_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in _team_registry_rows():
        if not isinstance(row, dict):
            continue
        for candidate in (
            row.get("team_id"),
            row.get("canonical_team_name"),
            row.get("abbreviation"),
            row.get("display_name"),
            row.get("school_name"),
            row.get("mascot_name"),
        ):
            normalized = _normalize_text(candidate)
            if normalized:
                index.setdefault(normalized, row)
        for alias in str(row.get("aliases") or "").split("|"):
            normalized = _normalize_text(alias)
            if normalized:
                index.setdefault(normalized, row)
    return index


def _resolve_team(team_name: str) -> dict[str, Any] | None:
    return _team_registry_index().get(_normalize_text(team_name))


def _first_row(rows: tuple[dict[str, Any], ...], *, team_id: str | None = None, season: int | None = None, key: str = "team_id") -> dict[str, Any] | None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if team_id is not None and str(row.get(key) or "").strip() != str(team_id).strip():
            continue
        if season is not None:
            row_season = str(row.get("season") or "").strip()
            if row_season and row_season != str(season):
                continue
        return row
    return None


def _count_rows(rows: tuple[dict[str, Any], ...], *, key: str, team_id: str, season: int | None = None) -> int:
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get(key) or "").strip() != str(team_id).strip():
            continue
        if season is not None:
            row_season = str(row.get("season") or "").strip()
            if row_season and row_season != str(season):
                continue
        total += 1
    return total


def _count_transfer_rows(rows: tuple[dict[str, Any], ...], *, team_id: str, season: int | None = None, direction: str) -> int:
    key = "destination_team_id" if direction == "in" else "origin_team_id"
    return _count_rows(rows, key=key, team_id=team_id, season=season)


def _format_decimal(value: Any, *, places: int = 3) -> str:
    amount = _safe_float(value)
    if amount is None:
        return "-"
    return f"{amount:.{places}f}".rstrip("0").rstrip(".")


def _publication_ready(coverage_tier: str | None) -> bool:
    return str(coverage_tier or "").upper() in {"A", "B"}


def _tier_badges(coverage_tier: str | None) -> list[dict[str, Any]]:
    current = str(coverage_tier or "").upper()
    return [{"label": tier, "active": tier == current} for tier in ("A", "B", "C", "D")]


def _team_context(team_name: str, season: int) -> dict[str, Any]:
    registry_row = _resolve_team(team_name) or {}
    team_id = str(registry_row.get("team_id") or "").strip()
    team_rank = str(
        registry_row.get("rank")
        or registry_row.get("ap_rank")
        or registry_row.get("cfp_rank")
        or registry_row.get("ranking")
        or ""
    ).strip()
    returning_row = _first_row(_returning_rows(), team_id=team_id, season=season)
    coach_row = _first_row(_coach_rows(), team_id=team_id, season=season)
    roster_count = _count_rows(_roster_rows(), key="team_id", team_id=team_id, season=season)
    transfer_in = _count_transfer_rows(_transfer_rows(), team_id=team_id, season=season, direction="in")
    transfer_out = _count_transfer_rows(_transfer_rows(), team_id=team_id, season=season, direction="out")
    transfer_net = transfer_in - transfer_out
    returning_starter_estimate = _format_decimal(returning_row.get("returning_starter_estimate") if returning_row else None, places=1)
    returning_percent = _format_decimal(returning_row.get("percent_ppa") if returning_row else None, places=3)
    returning_usage = _format_decimal(returning_row.get("usage") if returning_row else None, places=3)
    coach_continuity = _format_decimal(coach_row.get("continuity_score") if coach_row else None, places=3)
    coach_tenure = _format_decimal(coach_row.get("coach_tenure_years") if coach_row else None, places=1)
    branding = _resolve_branding(team_id)
    return {
        "team_name": team_name,
        "team_id": team_id,
        "abbreviation": str(registry_row.get("abbreviation") or _abbr(team_name)).strip(),
        "rank": team_rank,
        "school_name": str(registry_row.get("school_name") or team_name).strip() or team_name,
        "mascot_name": str(registry_row.get("mascot_name") or "").strip(),
        "conference": str(registry_row.get("conference") or "").strip(),
        "conference_short_name": str(registry_row.get("conference_short_name") or "").strip(),
        "subdivision": str(registry_row.get("subdivision") or "").strip(),
        "logo_url": branding.logo_url if branding else None,
        "primary_color": branding.primary_color if branding else None,
        "secondary_color": branding.secondary_color if branding else None,
        "returning": {
            "starter_estimate": returning_starter_estimate,
            "percent_ppa": returning_percent,
            "usage": returning_usage,
            "summary": f"{returning_starter_estimate} starters | PPA {returning_percent} | Usage {returning_usage}",
        },
        "coach": {
            "name": str(coach_row.get("head_coach_name") or "").strip() if coach_row else "",
            "continuity_score": coach_continuity,
            "tenure_years": coach_tenure,
            "changed": str(coach_row.get("coach_changed") or "").strip() if coach_row else "",
            "summary": f"{str(coach_row.get('head_coach_name') or 'TBD').strip()} | continuity {coach_continuity} | tenure {coach_tenure}y" if coach_row else "Coach continuity unavailable",
        },
        "transfer": {
            "incoming": transfer_in,
            "outgoing": transfer_out,
            "net": transfer_net,
            "summary": f"{transfer_in} in / {transfer_out} out / net {transfer_net:+d}".replace("+", "") if transfer_in or transfer_out else "No transfer data",
        },
        "roster": {
            "active_count": roster_count,
            "summary": f"{roster_count} active roster entries",
        },
    }


def _team_context_tone(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"high", "positive", "stable", "veteran", "returning hc"}:
        return "positive"
    if normalized in {"neutral", "mixed"}:
        return "neutral"
    if normalized in {"low", "negative", "unstable", "freshman", "rebuilding"}:
        return "negative"
    return "neutral"


def _team_context_label(value: str, *, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _build_team_context_items(home_context: dict[str, Any], away_context: dict[str, Any]) -> list[dict[str, str]]:
    home_returning = home_context.get("returning") if isinstance(home_context.get("returning"), dict) else {}
    away_returning = away_context.get("returning") if isinstance(away_context.get("returning"), dict) else {}
    home_transfer = home_context.get("transfer") if isinstance(home_context.get("transfer"), dict) else {}
    away_transfer = away_context.get("transfer") if isinstance(away_context.get("transfer"), dict) else {}
    home_coach = home_context.get("coach") if isinstance(home_context.get("coach"), dict) else {}
    away_coach = away_context.get("coach") if isinstance(away_context.get("coach"), dict) else {}
    home_roster = home_context.get("roster") if isinstance(home_context.get("roster"), dict) else {}
    away_roster = away_context.get("roster") if isinstance(away_context.get("roster"), dict) else {}

    returning_home = _safe_float(home_returning.get("percent_ppa"))
    returning_away = _safe_float(away_returning.get("percent_ppa"))
    if returning_home is not None and returning_away is not None:
        returning_value = "High" if max(returning_home, returning_away) >= 0.70 else "Moderate" if max(returning_home, returning_away) >= 0.55 else "Developing"
    else:
        returning_value = "Available"

    transfer_net = int(_safe_float(home_transfer.get("net")) or 0) + int(_safe_float(away_transfer.get("net")) or 0)
    portal_value = "Positive" if transfer_net > 0 else "Negative" if transfer_net < 0 else "Neutral"
    coach_value = "Returning HC" if str(home_coach.get("name") or away_coach.get("name") or "").strip() else "Stable"
    roster_total = int(_safe_float(home_roster.get("active_count")) or 0) + int(_safe_float(away_roster.get("active_count")) or 0)
    roster_value = "Veteran" if roster_total >= 180 else "Balanced" if roster_total >= 120 else "Young"

    return [
        {
            "label": "Returning Production",
            "value": returning_value,
            "detail": f"Home {home_returning.get('summary') or '-'} | Away {away_returning.get('summary') or '-'}",
            "tone": _team_context_tone(returning_value),
        },
        {
            "label": "Portal Impact",
            "value": portal_value,
            "detail": f"Home {home_transfer.get('summary') or '-'} | Away {away_transfer.get('summary') or '-'}",
            "tone": _team_context_tone(portal_value),
        },
        {
            "label": "Coach Continuity",
            "value": coach_value,
            "detail": f"Home {home_coach.get('summary') or '-'} | Away {away_coach.get('summary') or '-'}",
            "tone": _team_context_tone(coach_value),
        },
        {
            "label": "Roster Experience",
            "value": roster_value,
            "detail": f"Home {home_roster.get('summary') or '-'} | Away {away_roster.get('summary') or '-'}",
            "tone": _team_context_tone(roster_value),
        },
    ]


def _build_matchup_context_items(home_context: dict[str, Any], away_context: dict[str, Any]) -> list[dict[str, str]]:
    def _team_label(context: dict[str, Any]) -> str:
        return str(context.get("school_name") or context.get("abbreviation") or context.get("team_name") or "Team").strip() or "Team"

    def _advantage_label(home_value: float | None, away_value: float | None, *, home_text: str, away_text: str, higher_is_better: bool, percent: bool = False, neutral_delta: float = 0.03) -> tuple[str, str, str]:
        if home_value is None or away_value is None:
            return "Unavailable", "Unable to compare", "neutral"
        delta = float(home_value) - float(away_value)
        if not higher_is_better:
            delta = -delta
        if abs(delta) <= float(neutral_delta):
            return "Even", f"{home_text} | {away_text}", "neutral"
        leader = home_text if delta > 0 else away_text
        magnitude = abs(delta)
        if percent:
            return f"{leader} +{magnitude * 100.0:.0f}%", f"{home_text} {float(home_value) * 100.0:.1f}% | {away_text} {float(away_value) * 100.0:.1f}%", "positive" if delta > 0 else "negative"
        return f"{leader} Advantage", f"{home_text} {float(home_value):.3f} | {away_text} {float(away_value):.3f}", "positive" if delta > 0 else "negative"

    home_returning = home_context.get("returning") if isinstance(home_context.get("returning"), dict) else {}
    away_returning = away_context.get("returning") if isinstance(away_context.get("returning"), dict) else {}
    home_transfer = home_context.get("transfer") if isinstance(home_context.get("transfer"), dict) else {}
    away_transfer = away_context.get("transfer") if isinstance(away_context.get("transfer"), dict) else {}
    home_coach = home_context.get("coach") if isinstance(home_context.get("coach"), dict) else {}
    away_coach = away_context.get("coach") if isinstance(away_context.get("coach"), dict) else {}
    home_roster = home_context.get("roster") if isinstance(home_context.get("roster"), dict) else {}
    away_roster = away_context.get("roster") if isinstance(away_context.get("roster"), dict) else {}

    home_conf = _team_context_label(str(home_context.get("conference_short_name") or home_context.get("conference") or ""), default="Home")
    away_conf = _team_context_label(str(away_context.get("conference_short_name") or away_context.get("conference") or ""), default="Away")
    home_name = _team_label(home_context)
    away_name = _team_label(away_context)

    home_returning_pct = _safe_float(home_returning.get("percent_ppa"))
    away_returning_pct = _safe_float(away_returning.get("percent_ppa"))
    home_transfer_net = _safe_float(home_transfer.get("net"))
    away_transfer_net = _safe_float(away_transfer.get("net"))
    home_coach_continuity = _safe_float(home_coach.get("continuity_score"))
    away_coach_continuity = _safe_float(away_coach.get("continuity_score"))
    home_roster_count = _safe_float(home_roster.get("active_count"))
    away_roster_count = _safe_float(away_roster.get("active_count"))
    home_experience = (
        (home_returning_pct or 0.0) * 0.6
        + (home_coach_continuity or 0.0) * 0.25
        + min((home_roster_count or 0.0) / 200.0, 1.0) * 0.15
    )
    away_experience = (
        (away_returning_pct or 0.0) * 0.6
        + (away_coach_continuity or 0.0) * 0.25
        + min((away_roster_count or 0.0) / 200.0, 1.0) * 0.15
    )

    conference_value = f"{away_conf} vs {home_conf}" if away_conf != home_conf else f"Same conference: {home_conf}"
    conference_detail = f"Away {away_conf} | Home {home_conf}"
    if away_conf == home_conf:
        conference_detail = f"Both teams are in {home_conf}"

    returning_value, returning_detail, returning_tone = _advantage_label(home_returning_pct, away_returning_pct, home_text=home_name, away_text=away_name, higher_is_better=True, percent=True, neutral_delta=0.03)
    portal_value, portal_detail, portal_tone = _advantage_label(home_transfer_net, away_transfer_net, home_text=home_name, away_text=away_name, higher_is_better=True, percent=False, neutral_delta=0.5)
    coach_value, coach_detail, coach_tone = _advantage_label(home_coach_continuity, away_coach_continuity, home_text=home_name, away_text=away_name, higher_is_better=True, percent=False, neutral_delta=0.03)
    roster_value, roster_detail, roster_tone = _advantage_label(home_roster_count, away_roster_count, home_text=home_name, away_text=away_name, higher_is_better=True, percent=False, neutral_delta=2.0)
    experience_value, experience_detail, experience_tone = _advantage_label(home_experience, away_experience, home_text=home_name, away_text=away_name, higher_is_better=True, percent=False, neutral_delta=0.03)

    return [
        {
            "label": "Conference Context",
            "value": conference_value,
            "detail": conference_detail,
            "tone": "neutral",
        },
        {
            "label": "Returning Production",
            "value": returning_value,
            "detail": returning_detail,
            "tone": returning_tone,
        },
        {
            "label": "Portal Impact",
            "value": portal_value,
            "detail": portal_detail,
            "tone": portal_tone,
        },
        {
            "label": "Coach Continuity",
            "value": coach_value,
            "detail": coach_detail,
            "tone": coach_tone,
        },
        {
            "label": "Roster Comparison",
            "value": roster_value if roster_value != "Even" else experience_value,
            "detail": f"Roster size {home_roster_count or 0:.0f} vs {away_roster_count or 0:.0f} | Experience {experience_detail}",
            "tone": roster_tone if roster_tone != "neutral" else experience_tone,
        },
    ]


def _build_smartsim_reasons_items(home_context: dict[str, Any], away_context: dict[str, Any], scoreboard: dict[str, Any]) -> dict[str, Any]:
    def _team_label(context: dict[str, Any]) -> str:
        return str(context.get("school_name") or context.get("abbreviation") or context.get("team_name") or "Team").strip() or "Team"

    def _subdivision_rank(value: str) -> int:
        normalized = str(value or "").strip().upper()
        if not normalized:
            return -1
        if "FBS" in normalized:
            return 4
        if "FCS" in normalized:
            return 3
        if "DIVISION I" in normalized or normalized in {"D1", "DI"}:
            return 4
        if "DIVISION II" in normalized or normalized in {"D2", "DII"}:
            return 2
        if "DIVISION III" in normalized or normalized in {"D3", "DIII"}:
            return 1
        if "NAIA" in normalized:
            return 0
        return 0

    def _positive_reason(favored_label: str, detail: str, *, weight: int, tone: str = "positive") -> dict[str, Any] | None:
        if not detail:
            return None
        return {
            "label": favored_label,
            "value": favored_label,
            "detail": detail,
            "tone": tone,
            "weight": weight,
        }

    home_returning = home_context.get("returning") if isinstance(home_context.get("returning"), dict) else {}
    away_returning = away_context.get("returning") if isinstance(away_context.get("returning"), dict) else {}
    home_transfer = home_context.get("transfer") if isinstance(home_context.get("transfer"), dict) else {}
    away_transfer = away_context.get("transfer") if isinstance(away_context.get("transfer"), dict) else {}
    home_coach = home_context.get("coach") if isinstance(home_context.get("coach"), dict) else {}
    away_coach = away_context.get("coach") if isinstance(away_context.get("coach"), dict) else {}
    home_roster = home_context.get("roster") if isinstance(home_context.get("roster"), dict) else {}
    away_roster = away_context.get("roster") if isinstance(away_context.get("roster"), dict) else {}

    home_returning_pct = _safe_float(home_returning.get("percent_ppa"))
    away_returning_pct = _safe_float(away_returning.get("percent_ppa"))
    home_transfer_net = _safe_float(home_transfer.get("net"))
    away_transfer_net = _safe_float(away_transfer.get("net"))
    home_coach_continuity = _safe_float(home_coach.get("continuity_score"))
    away_coach_continuity = _safe_float(away_coach.get("continuity_score"))
    home_roster_count = _safe_float(home_roster.get("active_count"))
    away_roster_count = _safe_float(away_roster.get("active_count"))
    home_experience = (
        (home_returning_pct or 0.0) * 0.6
        + (home_coach_continuity or 0.0) * 0.25
        + min((home_roster_count or 0.0) / 200.0, 1.0) * 0.15
    )
    away_experience = (
        (away_returning_pct or 0.0) * 0.6
        + (away_coach_continuity or 0.0) * 0.25
        + min((away_roster_count or 0.0) / 200.0, 1.0) * 0.15
    )

    home_points = _safe_float(scoreboard.get("home_points"))
    away_points = _safe_float(scoreboard.get("away_points"))
    favored_is_home = home_points is None or away_points is None or home_points >= away_points
    favored_context = home_context if favored_is_home else away_context
    underdog_context = away_context if favored_is_home else home_context
    favored_name = _team_label(favored_context)
    underdog_name = _team_label(underdog_context)

    items: list[dict[str, Any]] = []

    if home_returning_pct is not None and away_returning_pct is not None:
        if favored_is_home and home_returning_pct > away_returning_pct + 0.03:
            items.append({
                "label": "Returning Production",
                "value": "Higher returning production",
                "detail": f"{favored_name} {home_returning_pct:.3f} | {underdog_name} {away_returning_pct:.3f}",
                "tone": "positive",
                "weight": 100,
            })
        elif not favored_is_home and away_returning_pct > home_returning_pct + 0.03:
            items.append({
                "label": "Returning Production",
                "value": "Higher returning production",
                "detail": f"{favored_name} {away_returning_pct:.3f} | {underdog_name} {home_returning_pct:.3f}",
                "tone": "positive",
                "weight": 100,
            })

    if home_experience is not None and away_experience is not None:
        if favored_is_home and home_experience > away_experience + 0.03:
            items.append({
                "label": "Roster Experience",
                "value": "Stronger roster experience",
                "detail": f"{favored_name} experience {home_experience:.3f} | {underdog_name} experience {away_experience:.3f}",
                "tone": "positive",
                "weight": 90,
            })
        elif not favored_is_home and away_experience > home_experience + 0.03:
            items.append({
                "label": "Roster Experience",
                "value": "Stronger roster experience",
                "detail": f"{favored_name} experience {away_experience:.3f} | {underdog_name} experience {home_experience:.3f}",
                "tone": "positive",
                "weight": 90,
            })

    if home_transfer_net is not None and away_transfer_net is not None:
        if favored_is_home and home_transfer_net > away_transfer_net + 0.5:
            items.append({
                "label": "Portal Activity",
                "value": "Positive portal balance",
                "detail": f"{favored_name} net {home_transfer_net:+.0f} | {underdog_name} net {away_transfer_net:+.0f}".replace("+", ""),
                "tone": "positive",
                "weight": 80,
            })
        elif not favored_is_home and away_transfer_net > home_transfer_net + 0.5:
            items.append({
                "label": "Portal Activity",
                "value": "Positive portal balance",
                "detail": f"{favored_name} net {away_transfer_net:+.0f} | {underdog_name} net {home_transfer_net:+.0f}".replace("+", ""),
                "tone": "positive",
                "weight": 80,
            })

    if home_coach_continuity is not None and away_coach_continuity is not None:
        if favored_is_home and home_coach_continuity > away_coach_continuity + 0.03:
            items.append({
                "label": "Coach Continuity",
                "value": "More stable coach continuity",
                "detail": f"{favored_name} {home_coach_continuity:.3f} | {underdog_name} {away_coach_continuity:.3f}",
                "tone": "positive",
                "weight": 70,
            })
        elif not favored_is_home and away_coach_continuity > home_coach_continuity + 0.03:
            items.append({
                "label": "Coach Continuity",
                "value": "More stable coach continuity",
                "detail": f"{favored_name} {away_coach_continuity:.3f} | {underdog_name} {home_coach_continuity:.3f}",
                "tone": "positive",
                "weight": 70,
            })

    favored_conference = str(favored_context.get("conference_short_name") or favored_context.get("conference") or "").strip()
    underdog_conference = str(underdog_context.get("conference_short_name") or underdog_context.get("conference") or "").strip()
    favored_subdivision = str(favored_context.get("subdivision") or "").strip()
    underdog_subdivision = str(underdog_context.get("subdivision") or "").strip()
    context_detail = f"{favored_name} {favored_conference or '-'} / {favored_subdivision or '-'} | {underdog_name} {underdog_conference or '-'} / {underdog_subdivision or '-'}"
    if favored_conference == underdog_conference and favored_subdivision == underdog_subdivision:
        context_value = "Comparable conference / subdivision context"
        context_tone = "neutral"
    elif favored_subdivision and underdog_subdivision and _subdivision_rank(favored_subdivision) > _subdivision_rank(underdog_subdivision):
        context_value = "Higher subdivision context"
        context_tone = "positive"
    else:
        context_value = "Comparable conference / subdivision context"
        context_tone = "neutral"
    items.append({
        "label": "Conference / Subdivision Context",
        "value": context_value,
        "detail": context_detail,
        "tone": context_tone,
        "weight": 60,
    })

    ordered_items = sorted(items, key=lambda item: (1 if str(item.get("tone") or "").strip().lower() == "positive" else 0, int(item.get("weight") or 0)), reverse=True)
    lead_phrases = [str(item.get("value") or "").strip() for item in ordered_items if str(item.get("tone") or "").strip().lower() == "positive"]
    if not lead_phrases:
        lead_phrases = [str(item.get("value") or "").strip() for item in ordered_items[:3] if str(item.get("value") or "").strip()]
    lead_text = " and ".join(lead_phrases[:2]) if len(lead_phrases) == 2 else ", ".join(lead_phrases[:2])
    if len(lead_phrases) > 2:
        lead_text = f"{', '.join(lead_phrases[:2])}, and {lead_phrases[2]}"
    if lead_text:
        summary = f"{LEGACY_ENGINE_SOURCE_LABEL} favors {favored_name} because of {lead_text.lower()}."
    else:
        summary = f"{LEGACY_ENGINE_SOURCE_LABEL} favors {favored_name} because the current matchup context leans that way."

    return {
        "lead": summary,
        "summary": summary,
        "favored_team": favored_name,
        "items": ordered_items[:5],
    }


def _build_ncaaf_card_contract(row: dict[str, Any], week: int, *, season: int) -> dict[str, Any]:
    home_team = str(row.get("home_team") or "Home").strip() or "Home"
    away_team = str(row.get("away_team") or "Away").strip() or "Away"
    publication_profile = _week1_publication_profile(away_team, home_team, week)
    coverage_score = publication_profile.get("coverage_score")
    coverage_tier = publication_profile.get("coverage_tier")
    publication_status = publication_profile.get("publication_status")
    publication_priority = publication_profile.get("publication_priority")
    publication_ready = _publication_ready(coverage_tier)
    home_context = _team_context(home_team, season)
    away_context = _team_context(away_team, season)
    scoreboard = _scoreboard_projection(row, week)
    scoreboard_header = {
        "away": {
            "abbr": away_context["abbreviation"],
                "rank": away_context["rank"],
            "school_name": away_context["school_name"],
            "mascot_name": away_context["mascot_name"],
            "conference": away_context["conference"],
            "conference_short_name": away_context["conference_short_name"],
            "logo_url": away_context["logo_url"],
            "logo_text": away_context["abbreviation"],
            "primary_color": away_context["primary_color"],
            "secondary_color": away_context["secondary_color"],
        },
        "home": {
            "abbr": home_context["abbreviation"],
                "rank": home_context["rank"],
            "school_name": home_context["school_name"],
            "mascot_name": home_context["mascot_name"],
            "conference": home_context["conference"],
            "conference_short_name": home_context["conference_short_name"],
            "logo_url": home_context["logo_url"],
            "logo_text": home_context["abbreviation"],
            "primary_color": home_context["primary_color"],
            "secondary_color": home_context["secondary_color"],
        },
        "kickoff": scoreboard.get("kickoff") or f"{_week_label(week, season=season)} kickoff unavailable",
        "venue": scoreboard.get("venue") or "Venue unavailable",
        "status": f"Week {week}",
        "status_detail": "Historical summary",
    }
    context_sections = [
        {
            "label": "Returning production",
            "home": home_context["returning"]["summary"],
            "away": away_context["returning"]["summary"],
            "detail": "Starter estimate, production share, and usage from the published snapshot.",
        },
        {
            "label": "Coach continuity",
            "home": home_context["coach"]["summary"],
            "away": away_context["coach"]["summary"],
            "detail": "Continuity score and tenure from the published coach snapshot.",
        },
        {
            "label": "Transfer activity",
            "home": home_context["transfer"]["summary"],
            "away": away_context["transfer"]["summary"],
            "detail": "Incoming, outgoing, and net transfer counts.",
        },
        {
            "label": "Roster base",
            "home": home_context["roster"]["summary"],
            "away": away_context["roster"]["summary"],
            "detail": "Active roster snapshot rows linked to each team.",
        },
    ]
    team_context = {
        "items": _build_team_context_items(home_context, away_context),
        "summary": "Return production, portal impact, coach continuity, and roster experience",
    }
    matchup_context = {
        "items": _build_matchup_context_items(home_context, away_context),
        "summary": "Conference, returning production, portal, coach, and roster comparisons",
    }
    smartsim_reasons = _build_smartsim_reasons_items(home_context, away_context, scoreboard)
    return {
        "version": _NCAAF_CARD_CONTRACT_VERSION,
        "summary": {
            "coverage_score": coverage_score,
            "coverage_tier": coverage_tier,
            "publication_status": publication_status,
            "publication_priority": publication_priority,
            "publication_ready": publication_ready,
            "ready_label": "Publication ready" if publication_ready else "Publication blocked",
            "tier_badges": _tier_badges(coverage_tier),
        },
        "teams": {
            "home": home_context,
            "away": away_context,
        },
        "scoreboard": scoreboard,
        "scoreboard_header": scoreboard_header,
        "smartsim_reasons": smartsim_reasons,
        "team_context": team_context,
        "matchup_context": matchup_context,
        "context_sections": context_sections,
    }


def _abbr(team: str) -> str:
    tokens = [token for token in str(team or "").replace("&", " ").split() if token]
    if not tokens:
        return "TBD"
    if len(tokens) == 1:
        return tokens[0][:3].upper()
    return "".join(token[0] for token in tokens[:3]).upper()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _normalize_probability(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.rstrip("%").strip()
    try:
        amount = float(text)
    except Exception:
        return None
    if amount > 1.0:
        amount /= 100.0
    if amount < 0.0:
        return 0.0
    if amount > 1.0:
        return 1.0
    return amount


def _stake_text(value: Any) -> str:
    amount = _safe_float(value)
    return f"${amount:.2f}" if amount is not None else "-"


def _kelly_text(value: Any) -> str:
    amount = _safe_float(value)
    return f"{amount * 100:.1f}%" if amount is not None else "-"


def _week_label(week: int, *, season: int | None = None) -> str:
    resolved_season = int(season) if season is not None else default_season()
    return f"{resolved_season} Week {week}"


def _week1_publication_profile(away_team: str, home_team: str, week: int) -> dict[str, Any]:
    if week != 1:
        return {}
    matchup = (away_team, home_team)
    if matchup in _WEEK1_PUBLISHABLE_MATCHUPS:
        return dict(_WEEK1_COVERAGE_PROFILE["publishable"])
    if matchup in _WEEK1_SUPPRESSED_MATCHUPS:
        return dict(_WEEK1_COVERAGE_PROFILE["suppressed"])
    return {}


def _collapse_games(summary: dict[str, Any], week: int, *, limit: int = 16) -> list[dict[str, Any]]:
    results = summary.get("results") if isinstance(summary.get("results"), list) else []
    best_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        home_team = str(row.get("home_team") or "").strip()
        away_team = str(row.get("away_team") or "").strip()
        if not home_team or not away_team:
            continue
        key = (away_team, home_team)
        current = best_rows.get(key)
        candidate_edge = _safe_float(row.get("edge")) or float("-inf")
        if current is None:
            best_rows[key] = row
            continue
        current_edge = _safe_float(current.get("edge")) or float("-inf")
        if candidate_edge > current_edge:
            best_rows[key] = row
            continue
        candidate_stake = _safe_float(row.get("stake")) or 0.0
        current_stake = _safe_float(current.get("stake")) or 0.0
        if candidate_edge == current_edge and candidate_stake > current_stake:
            best_rows[key] = row

    ordered_rows = sorted(
        best_rows.values(),
        key=lambda row: ((_safe_float(row.get("edge")) or 0.0), (_safe_float(row.get("stake")) or 0.0)),
        reverse=True,
    )
    games: list[dict[str, Any]] = []
    for row in ordered_rows[:limit]:
        home_team = str(row.get("home_team") or "Home").strip() or "Home"
        away_team = str(row.get("away_team") or "Away").strip() or "Away"
        home_abbr = _abbr(home_team)
        away_abbr = _abbr(away_team)
        market = str(row.get("market") or "ML").strip().upper() or "ML"
        side = str(row.get("side") or "Home").strip() or "Home"
        provider = str(row.get("provider") or "Book").strip() or "Book"
        price = format_moneyline(row.get("price_american"))
        model_prob = format_pct(row.get("model_prob"))
        implied_prob = format_pct(row.get("implied_prob"))
        edge = format_pct(row.get("edge"))
        stake = _stake_text(row.get("stake"))
        favored_team = home_team if side.lower() == "home" else away_team
        ncaaf_card = _build_ncaaf_card_contract(row, week, season=default_season())
        games.append(
            {
                "gamePk": f"{week}_{away_team}_{home_team}".replace(" ", "_"),
                "card_variant": "ncaaf_main",
                "away": {"abbr": away_abbr, "name": away_team},
                "home": {"abbr": home_abbr, "name": home_team},
                "href": f"/ncaaf/game/{f'{week}_{away_team}_{home_team}'.replace(' ', '_')}?week={week}",
                "href_label": "Open NCAAF game detail",
                "status": f"Week {week}",
                "detail": "Historical summary",
                "summary": f"{favored_team} is the best {market} recommendation from {provider} at {price} with modeled edge {edge}.",
                **ncaaf_card.get("summary", {}),
                "ncaaf_card": ncaaf_card,
                "metrics": [
                    {"label": "Model", "value": model_prob},
                    {"label": "Implied", "value": implied_prob},
                    {"label": "Price", "value": price},
                    {"label": "Stake", "value": stake},
                    {"label": "Edge", "value": edge},
                ],
                "panels": [
                    {
                        "eyebrow": "Official card",
                        "title": provider,
                        "body": "The first NCAAF cards board groups the weekly recommendations summary into one best available recommendation per matchup.",
                        "items": [
                            f"Market: {market}",
                            f"Side: {side}",
                            f"Stake: {stake}",
                        ],
                    },
                    {
                        "eyebrow": "Model vs price",
                        "title": f"Model {model_prob} | Implied {implied_prob}",
                        "body": f"Best listed price is {price} from {provider}, producing modeled edge {edge}.",
                        "items": [
                            f"Kelly fraction: {_kelly_text(row.get('kelly_f'))}",
                            f"Raw edge multiple: {format_num(row.get('edge'))}",
                            f"Recommendation: {favored_team}",
                        ],
                    },
                    {
                        "eyebrow": "Game context",
                        "title": _week_label(week),
                        "body": f"{away_team} at {home_team} from the stored NCAAF recommendations summary.",
                        "items": [
                            f"Provider: {provider}",
                            "Current source artifacts are offseason weekly snapshots rather than live slate data.",
                        ],
                    },
                ],
                "market_tiles": [
                    {"label": "Coverage", "title": _format_decimal(ncaaf_card["summary"]["coverage_score"], places=3), "sub": ncaaf_card["summary"]["ready_label"]},
                    {"label": "Tier", "title": str(ncaaf_card["summary"]["coverage_tier"] or "-").upper(), "sub": "Enhanced Totals Engine tier"},
                    {"label": "Status", "title": str(ncaaf_card["summary"]["publication_status"] or "-").title(), "sub": "Publication state"},
                    {"label": "Priority", "title": str(ncaaf_card["summary"]["publication_priority"] or "-"), "sub": "Board order"},
                ],
            }
        )
    return games


def _clamp_week(selected_week: int) -> int:
    return resolve_selected_value(selected_week, available_weeks(), 1)


def _build_smartsim_ncaaf_card_contract(row: dict[str, Any], week: int, *, season: int) -> dict[str, Any]:
    home_team = str(row.get("home_team") or "Home").strip() or "Home"
    away_team = str(row.get("away_team") or "Away").strip() or "Away"
    home_abbr = _abbr(home_team)
    away_abbr = _abbr(away_team)
    home_context = _team_context(home_team, season)
    away_context = _team_context(away_team, season)
    scoreboard = _runtime_scoreboard_projection(row, week)
    publication_profile = _runtime_publication_profile(scoreboard)
    coverage_score = publication_profile.get("coverage_score")
    coverage_tier = publication_profile.get("coverage_tier")
    publication_status = publication_profile.get("publication_status")
    publication_priority = publication_profile.get("publication_priority")
    publication_ready = publication_profile.get("publication_ready")
    metric_rows = [
        {"label": "Home mean", "value": scoreboard.get("home_points") or "-"},
        {"label": "Away mean", "value": scoreboard.get("away_points") or "-"},
        {"label": "Projected total", "value": scoreboard.get("total_points") or "-"},
        {"label": "Projected spread", "value": scoreboard.get("spread_label") or "-"},
        {"label": "Win probability", "value": scoreboard.get("win_probability") or "-"},
    ]
    summary_text = (
        f"{LEGACY_ENGINE_SOURCE_LABEL} projects {home_team} {scoreboard.get('home_points') or '-'} - "
        f"{scoreboard.get('away_points') or '-'} {away_team} with a total of "
        f"{scoreboard.get('total_points') or '-'} and a home win probability of "
        f"{scoreboard.get('win_probability') or '-'}."
    )
    matchup_context_sections = [
        {
            "label": "Returned production",
            "home": home_context["returning"]["summary"],
            "away": away_context["returning"]["summary"],
            "detail": "Starter estimate, production share, and usage from the published snapshot.",
        },
        {
            "label": "Coach continuity",
            "home": home_context["coach"]["summary"],
            "away": away_context["coach"]["summary"],
            "detail": "Continuity score and tenure from the published coach snapshot.",
        },
        {
            "label": "Transfer activity",
            "home": home_context["transfer"]["summary"],
            "away": away_context["transfer"]["summary"],
            "detail": "Incoming, outgoing, and net transfer counts.",
        },
        {
            "label": "Roster base",
            "home": home_context["roster"]["summary"],
            "away": away_context["roster"]["summary"],
            "detail": "Active roster snapshot rows linked to each team.",
        },
    ]
    team_context = {
        "items": _build_team_context_items(home_context, away_context),
        "summary": "Return production, portal impact, coach continuity, and roster experience",
    }
    matchup_context = {
        "items": _build_matchup_context_items(home_context, away_context),
        "summary": "Conference, returning production, portal, coach, and roster comparisons",
    }
    smartsim_reasons = _build_smartsim_reasons_items(home_context, away_context, scoreboard)
    return {
        "gamePk": f"{week}_{away_team}_{home_team}".replace(" ", "_"),
        "card_variant": "ncaaf_main",
        "away": {"abbr": away_abbr, "name": away_team},
        "home": {"abbr": home_abbr, "name": home_team},
        "href": f"/ncaaf/game/{f'{week}_{away_team}_{home_team}'.replace(' ', '_')}?week={week}",
        "href_label": "Open NCAAF game detail",
        "status": f"Week {week}",
        "detail": LEGACY_ENGINE_SOURCE_LABEL,
        "summary": summary_text,
        "metrics": metric_rows,
        "smartsim_reasons": smartsim_reasons,
        "panels": [
            {
                "eyebrow": LEGACY_ENGINE_SOURCE_LABEL,
                "title": "Projection contract",
                "body": "Cards now read directly from the predicted totals snapshot instead of saved recommendation summaries.",
                "items": [
                    f"Home mean: {scoreboard.get('home_points') or '-'}",
                    f"Away mean: {scoreboard.get('away_points') or '-'}",
                    f"Projected spread: {scoreboard.get('spread_label') or '-'}",
                    f"Projected total: {scoreboard.get('total_points') or '-'}",
                    f"Win probability: {scoreboard.get('win_probability') or '-'}",
                ],
            },
            {
                "eyebrow": LEGACY_ENGINE_SOURCE_LABEL,
                "title": "Source and fallback",
                "body": "The runtime cards path can fall back to the summary artifact path if the predicted-totals snapshot is unavailable.",
                "items": [
                    f"Projection source: {scoreboard.get('source_label') or LEGACY_ENGINE_SOURCE_LABEL}",
                    f"Kickoff: {scoreboard.get('kickoff') or 'Kickoff unavailable'}",
                    f"Venue: {scoreboard.get('venue') or 'Venue unavailable'}",
                ],
            },
        ],
        "market_tiles": [
            {"label": "Coverage", "title": _format_decimal(coverage_score, places=3), "sub": "Enhanced Totals Engine tier"},
            {"label": "Tier", "title": str(coverage_tier or "-").upper(), "sub": "Enhanced Totals Engine tier"},
            {"label": "Status", "title": str(publication_status or "-").title(), "sub": "Publication state"},
            {"label": "Priority", "title": str(publication_priority or "-"), "sub": "Board order"},
        ],
        "ncaaf_card": {
            "version": _NCAAF_CARD_CONTRACT_VERSION,
            "summary": {
                "coverage_score": coverage_score,
                "coverage_tier": coverage_tier,
                "publication_status": publication_status,
                "publication_priority": publication_priority,
                "publication_ready": publication_ready,
                "ready_label": "Publication ready" if publication_ready else "Publication blocked",
                "tier_badges": publication_profile.get("tier_badges") or _tier_badges(coverage_tier),
            },
            "teams": {
                "home": home_context,
                "away": away_context,
            },
            "scoreboard": scoreboard,
            "scoreboard_header": {
                "away": {
                    "abbr": away_context["abbreviation"],
                    "rank": away_context["rank"],
                    "school_name": away_context["school_name"],
                    "mascot_name": away_context["mascot_name"],
                    "conference": away_context["conference"],
                    "conference_short_name": away_context["conference_short_name"],
                    "logo_url": away_context["logo_url"],
                    "logo_text": away_context["abbreviation"],
                    "primary_color": away_context["primary_color"],
                    "secondary_color": away_context["secondary_color"],
                },
                "home": {
                    "abbr": home_context["abbreviation"],
                    "rank": home_context["rank"],
                    "school_name": home_context["school_name"],
                    "mascot_name": home_context["mascot_name"],
                    "conference": home_context["conference"],
                    "conference_short_name": home_context["conference_short_name"],
                    "logo_url": home_context["logo_url"],
                    "logo_text": home_context["abbreviation"],
                    "primary_color": home_context["primary_color"],
                    "secondary_color": home_context["secondary_color"],
                },
                "kickoff": scoreboard.get("kickoff") or f"{_week_label(week, season=season)} kickoff unavailable",
                "venue": scoreboard.get("venue") or "Venue unavailable",
                "status": f"Week {week}",
                "status_detail": LEGACY_ENGINE_SOURCE_LABEL,
            },
            "team_context": team_context,
            "matchup_context": matchup_context,
            "smartsim_reasons": smartsim_reasons,
            "context_sections": matchup_context_sections,
        },
    }

def _build_smartsim2_standalone_ncaaf_card_contract(row: dict[str, Any], week: int, *, season: int) -> dict[str, Any]:
    """Honestly-labeled card for a (season, week) the legacy engine has no
    data for -- every label says SmartSim 2.0, never Enhanced Totals Engine.
    Fabricating engine involvement that never happened would violate this
    whole project's disclosure discipline (see smartsim_ats_policy_implementation_report.md
    and the 2026 season bootstrap this path was built for). Produces the
    same ``ncaaf_card`` contract shape as the engine path so templates need
    no changes; only the content and labeling differ."""
    home_team = str(row["home_team"])
    away_team = str(row["away_team"])
    projection: SmartSimNcaafProjection = row["projection"]
    home_abbr = _abbr(home_team)
    away_abbr = _abbr(away_team)
    home_context = _team_context(home_team, season)
    away_context = _team_context(away_team, season)

    home_points = round(projection.home_score_mean, 1)
    away_points = round(projection.away_score_mean, 1)
    total_points = round(projection.total_mean, 1)
    margin = projection.margin_mean
    if margin > 0:
        spread_label = f"{home_team} by {abs(margin):.1f}"
    elif margin < 0:
        spread_label = f"{away_team} by {abs(margin):.1f}"
    else:
        spread_label = "Pick'em"
    win_probability = format_pct(projection.home_win_rate)
    market_margin = row.get("market_margin")
    market_total = row.get("market_total")

    scoreboard = {
        "home_points": home_points,
        "away_points": away_points,
        "total_points": total_points,
        "spread_label": spread_label,
        "win_probability": win_probability,
        "source_label": SMARTSIM2_PUBLIC_LABEL,
        "kickoff": row.get("start_date") or "Kickoff unavailable",
        "venue": row.get("venue") or "Venue unavailable",
        "smartsim2_available": True,
        "smartsim2_margin": projection.margin_mean,
        "smartsim2_total_points": projection.total_mean,
        "market_margin": market_margin,
        "market_total": market_total,
    }

    summary_text = (
        f"{SMARTSIM2_PUBLIC_LABEL} projects {home_team} {home_points} - {away_points} {away_team} "
        f"with a total of {total_points} and a home win probability of {win_probability}. "
        f"{LEGACY_ENGINE_SOURCE_LABEL} has no prediction for this game yet."
    )
    metric_rows = [
        {"label": "Home mean", "value": home_points},
        {"label": "Away mean", "value": away_points},
        {"label": "Projected total", "value": total_points},
        {"label": "Projected spread", "value": spread_label},
        {"label": "Win probability", "value": win_probability},
    ]
    matchup_context_sections = [
        {
            "label": "Returned production",
            "home": home_context["returning"]["summary"],
            "away": away_context["returning"]["summary"],
            "detail": "Starter estimate, production share, and usage from the published snapshot.",
        },
        {
            "label": "Coach continuity",
            "home": home_context["coach"]["summary"],
            "away": away_context["coach"]["summary"],
            "detail": "Continuity score and tenure from the published coach snapshot.",
        },
        {
            "label": "Transfer activity",
            "home": home_context["transfer"]["summary"],
            "away": away_context["transfer"]["summary"],
            "detail": "Incoming, outgoing, and net transfer counts.",
        },
        {
            "label": "Roster base",
            "home": home_context["roster"]["summary"],
            "away": away_context["roster"]["summary"],
            "detail": "Active roster snapshot rows linked to each team.",
        },
    ]
    team_context = {
        "items": _build_team_context_items(home_context, away_context),
        "summary": "Return production, portal impact, coach continuity, and roster experience",
    }
    matchup_context = {
        "items": _build_matchup_context_items(home_context, away_context),
        "summary": "Conference, returning production, portal, coach, and roster comparisons",
    }

    return {
        "gamePk": f"{week}_{away_team}_{home_team}".replace(" ", "_"),
        "card_variant": "ncaaf_main",
        "away": {"abbr": away_abbr, "name": away_team},
        "home": {"abbr": home_abbr, "name": home_team},
        "href": f"/ncaaf/game/{f'{week}_{away_team}_{home_team}'.replace(' ', '_')}?week={week}",
        "href_label": "Open NCAAF game detail",
        "status": f"Week {week}",
        "detail": SMARTSIM2_PUBLIC_LABEL,
        "summary": summary_text,
        "metrics": metric_rows,
        "smartsim_reasons": [],
        "panels": [
            {
                "eyebrow": SMARTSIM2_PUBLIC_LABEL,
                "title": "Projection contract",
                "body": f"{LEGACY_ENGINE_SOURCE_LABEL} has no prediction for this game yet, so this card shows SmartSim 2.0's own projection directly, unblended.",
                "items": [
                    f"Home mean: {scoreboard['home_points']}",
                    f"Away mean: {scoreboard['away_points']}",
                    f"Projected spread: {scoreboard['spread_label']}",
                    f"Projected total: {scoreboard['total_points']}",
                    f"Win probability: {scoreboard['win_probability']}",
                ],
            },
            {
                "eyebrow": SMARTSIM2_PUBLIC_LABEL,
                "title": "Source and fallback",
                "body": "This game has no Enhanced Totals Engine row for this season yet -- there is no blend to fall back to.",
                "items": [
                    f"Projection source: {SMARTSIM2_PUBLIC_LABEL}",
                    f"Kickoff: {scoreboard['kickoff']}",
                    f"Venue: {scoreboard['venue']}",
                ],
            },
        ],
        "market_tiles": [
            {"label": "Source", "title": "SmartSim 2.0", "sub": "No Engine data yet"},
            {"label": "Tier", "title": "Preview", "sub": "Not yet calibrated"},
            {"label": "Status", "title": "Publishable", "sub": "Publication state"},
            {"label": "Priority", "title": "-", "sub": "Board order"},
        ],
        "ncaaf_card": {
            "version": _NCAAF_CARD_CONTRACT_VERSION,
            "summary": {
                "coverage_score": None,
                "coverage_tier": "smartsim2_only",
                "publication_status": "publishable",
                "publication_priority": None,
                "publication_ready": True,
                "ready_label": "Publication ready",
                "tier_badges": [{"label": "SmartSim 2.0", "active": True}],
            },
            "teams": {
                "home": home_context,
                "away": away_context,
            },
            "scoreboard": scoreboard,
            "scoreboard_header": {
                "away": {
                    "abbr": away_context["abbreviation"],
                    "rank": away_context["rank"],
                    "school_name": away_context["school_name"],
                    "mascot_name": away_context["mascot_name"],
                    "conference": away_context["conference"],
                    "conference_short_name": away_context["conference_short_name"],
                    "logo_url": away_context["logo_url"],
                    "logo_text": away_context["abbreviation"],
                    "primary_color": away_context["primary_color"],
                    "secondary_color": away_context["secondary_color"],
                },
                "home": {
                    "abbr": home_context["abbreviation"],
                    "rank": home_context["rank"],
                    "school_name": home_context["school_name"],
                    "mascot_name": home_context["mascot_name"],
                    "conference": home_context["conference"],
                    "conference_short_name": home_context["conference_short_name"],
                    "logo_url": home_context["logo_url"],
                    "logo_text": home_context["abbreviation"],
                    "primary_color": home_context["primary_color"],
                    "secondary_color": home_context["secondary_color"],
                },
                "kickoff": scoreboard["kickoff"],
                "venue": scoreboard["venue"],
                "status": f"Week {week}",
                "status_detail": SMARTSIM2_PUBLIC_LABEL,
            },
            "team_context": team_context,
            "matchup_context": matchup_context,
            "smartsim_reasons": [],
            "context_sections": matchup_context_sections,
        },
    }


def build_smartsim_cards_page_context(selected_week: int) -> dict[str, Any]:
    season, runtime_weeks = _resolve_ncaaf_active_season_and_weeks()
    if not runtime_weeks:
        return build_cards_page_context(selected_week)
    requested_week = int(selected_week or runtime_weeks[-1])
    resolved_week = resolve_selected_value(requested_week, runtime_weeks, runtime_weeks[-1])

    engine_rows = _engine_rows_for_season_week(season, resolved_week)
    if engine_rows:
        # Unchanged path: real Enhanced Totals Engine data exists for this
        # exact (season, week) -- byte-identical to the pre-2026-bootstrap
        # behavior.
        runtime_rows = engine_rows
        games = [
            _build_smartsim_ncaaf_card_contract(row, resolved_week, season=season)
            for row in runtime_rows[:16]
        ]
        source_label_for_page = LEGACY_ENGINE_SOURCE_LABEL
    else:
        # No engine row for this season/week (e.g. 2026, while NCAAFCompare
        # is unavailable) -- fall back to real schedule + real SmartSim 2.0
        # projections, honestly labeled, never claiming engine involvement.
        runtime_rows = _smartsim2_standalone_rows(season, resolved_week)
        if not runtime_rows:
            return build_cards_page_context(selected_week)
        games = [
            _build_smartsim2_standalone_ncaaf_card_contract(row, resolved_week, season=season)
            for row in runtime_rows[:16]
        ]
        source_label_for_page = SMARTSIM2_PUBLIC_LABEL

    record_trial_page_view(
        route="/ncaaf/cards",
        season=season,
        week=resolved_week,
        scoreboards=[
            game["ncaaf_card"]["scoreboard"]
            for game in games
            if isinstance(game.get("ncaaf_card"), dict) and isinstance(game["ncaaf_card"].get("scoreboard"), dict)
        ],
    )
    weeks = runtime_weeks
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    source_path = _prediction_source_path() if engine_rows else None
    betting_href = f"/ncaaf/season/{season}/betting-card?week={resolved_week}"
    return apply_game_board_contract(
        {
            "date": _week_label(resolved_week, season=season),
            "requested_date": _week_label(selected_week, season=season),
            "prev_date": str(prev_week),
            "next_date": str(next_week),
            "control_action": "/ncaaf/cards",
            "controls_prev_href": f"/ncaaf/cards?week={prev_week}",
            "controls_next_href": f"/ncaaf/cards?week={next_week}",
            "control_label": "Week",
            "control_type": "number",
            "control_name": "week",
            "control_value": str(resolved_week),
            "module_links": build_module_links(resolved_week, "Cards"),
            "games": games,
            "scoreboard_items": [
                {
                    "target_id": f"game-{game['gamePk']}",
                    "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
                    "status": game["status"],
                }
                for game in games
            ],
            "source_path": str(source_path) if source_path else f"NCAAF {source_label_for_page} predicted totals",
            "source_title": f"NCAAF {source_label_for_page} cards runtime",
            "empty_state": {
                "eyebrow": "NCAAF cards",
                "title": f"No {source_label_for_page} cards were available for this week",
                "body": f"The cards board first reads the {LEGACY_ENGINE_SOURCE_LABEL} predicted-totals snapshot, falls back to real SmartSim 2.0 projections for a season the engine has no data for, and falls back to saved weekly summaries only if neither runtime path is available.",
                "list_items": [
                    f"Requested week: {selected_week}",
                    f"Resolved week: {resolved_week}",
                ],
            } if not games else None,
            "using_sample_data": False,
            "route_path": "/ncaaf/cards",
            "intro_title": "NCAAF Cards",
            "intro_body": f"NCAAF cards now read directly from {source_label_for_page} predicted totals first, with saved recommendation summaries kept as a fallback path.",
            "cards_control_links": [
                {"label": "Betting Card", "href": betting_href},
                {"label": "Picks", "href": f"/ncaaf/picks?week={resolved_week}"},
                {"label": "Live Lens", "href": f"/ncaaf/live-lens?week={resolved_week}"},
            ],
            "header_stats": [
                {"label": "Games", "value": str(len(games))},
                {"label": "Candidates", "value": str(len(runtime_rows))},
                {"label": "Weeks", "value": str(len(weeks) or "-")},
                {"label": "Source", "value": source_label_for_page if games else "No data"},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "teaser": {
                "label": "NCAAF picks",
                "body": f"Use the picks board for the historical weekly recommendation rows that remain separate from the {LEGACY_ENGINE_SOURCE_LABEL} cards path.",
                "href": f"/ncaaf/picks?week={resolved_week}",
                "cta": "Open NCAAF picks",
            },
            "active_sport_name": "NCAAF",
        },
        sport="ncaaf",
        module="cards",
        source_kind="smartsim_runtime",
        live_lens_integrated=False,
        include_simulation_contract=True,
    )


def build_cards_page_context(selected_week: int) -> dict[str, Any]:
    season = default_season()
    resolved_week = _clamp_week(selected_week or default_week())
    betting_href = f"/ncaaf/season/{season}/betting-card?week={resolved_week}"
    path = summary_path(resolved_week)
    summary = load_json(path) or {}
    games = _collapse_games(summary, resolved_week)
    using_sample_data = False

    weeks = available_weeks()
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    return apply_game_board_contract(
        {
            "date": _week_label(resolved_week, season=season),
            "requested_date": _week_label(selected_week, season=season),
            "prev_date": str(prev_week),
            "next_date": str(next_week),
            "control_action": "/ncaaf/cards",
            "controls_prev_href": f"/ncaaf/cards?week={prev_week}",
            "controls_next_href": f"/ncaaf/cards?week={next_week}",
            "control_label": "Week",
            "control_type": "number",
            "control_name": "week",
            "control_value": str(resolved_week),
            "module_links": build_module_links(resolved_week, "Cards"),
            "games": games,
            "scoreboard_items": [
                {
                    "target_id": f"game-{game['gamePk']}",
                    "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
                    "status": game["status"],
                }
                for game in games
            ],
            "source_path": str(path),
            "source_title": "NCAAF recommendations summary" if games else "NCAAF cards unavailable",
            "empty_state": {
                "eyebrow": "NCAAF cards",
                "title": "No game cards were available for this week",
                "body": "The cards board only renders saved NCAAF recommendation summary rows, and none were available for the requested week.",
                "list_items": [
                    f"Requested week: {selected_week}",
                    f"Resolved week: {resolved_week}",
                ],
            } if not games else None,
            "using_sample_data": using_sample_data,
            "route_path": "/ncaaf/cards",
            "intro_title": "NCAAF Cards",
            "intro_body": "NCAAF enters the shared game-board contract with a first weekly cards surface built from stored recommendation summary artifacts in the source app.",
            "cards_control_links": [
                {"label": "Betting Card", "href": betting_href},
                {"label": "Picks", "href": f"/ncaaf/picks?week={resolved_week}"},
                {"label": "Live Lens", "href": f"/ncaaf/live-lens?week={resolved_week}"},
            ],
            "header_stats": [
                {"label": "Games", "value": str(len(games))},
                {"label": "Rows", "value": str(len(summary.get('results') or []))},
                {"label": "Weeks", "value": str(len(weeks) or "-")},
                {"label": "Source", "value": "Summary" if games else "No data"},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "teaser": {
                "label": "NCAAF picks",
                "body": "Use the picks board for the ranked weekly recommendation rows behind these matchup cards.",
                "href": f"/ncaaf/picks?week={resolved_week}",
                "cta": "Open NCAAF picks",
            },
            "active_sport_name": "NCAAF",
        },
        sport="ncaaf",
        module="cards",
        source_kind="artifact_backed",
        live_lens_integrated=False,
    )