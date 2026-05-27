from __future__ import annotations

from collections import defaultdict
from datetime import date
from datetime import datetime, timedelta
import importlib.util
import json
from math import exp
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.mlb.ladders_common import build_module_links
from syndicate.features.mlb.sources import default_mlb_source_root
from syndicate.features.mlb.sources import daily_sim_artifact_path
from syndicate.features.mlb.sources import season_betting_card_day_path
from syndicate.features.mlb.sources import daily_artifact_path
from syndicate.features.mlb.sources import daily_ladders_path
from syndicate.features.mlb.sources import daily_rfi_targets_path
from syndicate.features.mlb.sources import daily_ops_report_path
from syndicate.features.mlb.sources import daily_snapshot_oddsapi_game_lines_path
from syndicate.features.mlb.sources import daily_snapshot_oddsapi_hitter_props_path
from syndicate.features.mlb.sources import daily_snapshot_oddsapi_pitcher_props_path
from syndicate.features.mlb.sources import daily_snapshot_lineups_path
from syndicate.features.mlb.sources import live_lens_report_path
from syndicate.features.mlb.sources import live_prop_registry_path
from syndicate.features.mlb.sources import market_refresh_history_oddsapi_path
from syndicate.features.mlb.sources import raw_feed_live_path
from syndicate.features.mlb.sources import load_json_or_gz_file
from syndicate.features.mlb.sources import load_json_file


_MLB_TEAM_META_BY_ABBR: dict[str, dict[str, Any]] = {
    "ARI": {"id": 109, "name": "Arizona Diamondbacks"},
    "ATL": {"id": 144, "name": "Atlanta Braves"},
    "BAL": {"id": 110, "name": "Baltimore Orioles"},
    "BOS": {"id": 111, "name": "Boston Red Sox"},
    "CHC": {"id": 112, "name": "Chicago Cubs"},
    "CWS": {"id": 145, "name": "Chicago White Sox"},
    "CIN": {"id": 113, "name": "Cincinnati Reds"},
    "CLE": {"id": 114, "name": "Cleveland Guardians"},
    "COL": {"id": 115, "name": "Colorado Rockies"},
    "DET": {"id": 116, "name": "Detroit Tigers"},
    "HOU": {"id": 117, "name": "Houston Astros"},
    "KC": {"id": 118, "name": "Kansas City Royals"},
    "LAA": {"id": 108, "name": "Los Angeles Angels"},
    "LAD": {"id": 119, "name": "Los Angeles Dodgers"},
    "MIA": {"id": 146, "name": "Miami Marlins"},
    "MIL": {"id": 158, "name": "Milwaukee Brewers"},
    "MIN": {"id": 142, "name": "Minnesota Twins"},
    "NYM": {"id": 121, "name": "New York Mets"},
    "NYY": {"id": 147, "name": "New York Yankees"},
    "ATH": {"id": 133, "name": "Athletics"},
    "PHI": {"id": 143, "name": "Philadelphia Phillies"},
    "PIT": {"id": 134, "name": "Pittsburgh Pirates"},
    "SD": {"id": 135, "name": "San Diego Padres"},
    "SEA": {"id": 136, "name": "Seattle Mariners"},
    "SF": {"id": 137, "name": "San Francisco Giants"},
    "STL": {"id": 138, "name": "St. Louis Cardinals"},
    "TB": {"id": 139, "name": "Tampa Bay Rays"},
    "TEX": {"id": 140, "name": "Texas Rangers"},
    "TOR": {"id": 141, "name": "Toronto Blue Jays"},
    "WSH": {"id": 120, "name": "Washington Nationals"},
}


_MLB_TEAM_ABBR_ALIASES: dict[str, str] = {
    "AZ": "ARI",
    "CHW": "CWS",
    "KCR": "KC",
    "SDP": "SD",
    "SFG": "SF",
    "TBR": "TB",
    "WAS": "WSH",
    "WSN": "WSH",
}


_MLB_USER_TIMEZONE = datetime.now().astimezone().tzinfo


def _source_live_prop_ranking_roots() -> list[Path]:
    return [default_mlb_source_root().resolve()]


def _load_source_live_prop_ranking_cfg() -> dict[str, Any] | None:
    for root in _source_live_prop_ranking_roots():
        candidate = root / "data" / "tuning" / "live_prop_ranking" / "default.json"
        loaded = load_json_file(candidate)
        if isinstance(loaded, dict):
            return loaded
    return None


def _load_source_live_prop_ranking_predictor() -> Any | None:
    module_name = "syndicate_mlb_source_live_prop_ranking"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return getattr(cached, "predict_live_prop_win_probability", None)
    for root in _source_live_prop_ranking_roots():
        candidate = root / "sim_engine" / "live_prop_ranking.py"
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location(module_name, candidate)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return getattr(module, "predict_live_prop_win_probability", None)
        except Exception:
            sys.modules.pop(module_name, None)
            continue
    return None


def _apply_source_live_prop_ranking_scores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    predictor = _load_source_live_prop_ranking_predictor()
    cfg = _load_source_live_prop_ranking_cfg()
    scored_rows: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item.get("ranking_score") is None and predictor is not None and isinstance(cfg, dict):
            try:
                probability = predictor(item, cfg, prop_key=str(item.get("prop") or ""))
            except Exception:
                probability = None
            if probability is not None:
                item["estimated_win_prob"] = float(probability)
                item["ranking_score"] = float(probability)
        scored_rows.append(item)
    scored_rows.sort(
        key=lambda row: (
            -float(_safe_float(row.get("ranking_score")) or -1.0),
            -float(_safe_float(row.get("edge")) or -999.0),
            -float(_safe_float(row.get("live_edge")) or -999.0),
            -float(_safe_float(row.get("projection_gap")) or -999.0),
            str(row.get("pitcher_name") or row.get("player_name") or ""),
            str(row.get("market") or ""),
        )
    )
    out: list[dict[str, Any]] = []
    for index, row in enumerate(scored_rows, start=1):
        item = dict(row)
        item["rank"] = int(index)
        out.append(item)
    return out


def _annotate_source_live_prop_rows_with_state(
    rows: list[dict[str, Any]],
    actual_payload: dict[str, Any] | None,
    live_lens_row: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    linescore = ((actual_payload or {}).get("liveData") or {}).get("linescore") if isinstance((actual_payload or {}).get("liveData"), dict) else {}
    actual_status = ((actual_payload or {}).get("gameData") or {}).get("status") if isinstance((actual_payload or {}).get("gameData"), dict) else {}
    lens_status = (live_lens_row or {}).get("status") if isinstance((live_lens_row or {}).get("status"), dict) else {}
    status_abstract = str((actual_status or {}).get("abstractGameState") or (lens_status or {}).get("abstract") or "").strip()
    status_detailed = str((actual_status or {}).get("detailedState") or (lens_status or {}).get("detailed") or "").strip()
    count = ((actual_payload or {}).get("liveData") or {}).get("plays") if isinstance((actual_payload or {}).get("liveData"), dict) else {}
    current_play = (count.get("currentPlay") or {}) if isinstance(count, dict) else {}
    teams = ((linescore or {}).get("teams") or {}) if isinstance(linescore, dict) else {}
    score_away = _safe_float((((teams.get("away") or {}).get("runs") if isinstance(teams, dict) else None)) )
    score_home = _safe_float((((teams.get("home") or {}).get("runs") if isinstance(teams, dict) else None)) )
    progress_fraction = _live_progress_fraction(actual_payload)
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item.setdefault("status_abstract", status_abstract)
        item.setdefault("status_detailed", status_detailed)
        item.setdefault("inning", _safe_int((linescore or {}).get("currentInning") if isinstance(linescore, dict) else None))
        item.setdefault("half_inning", str((linescore or {}).get("inningHalf") or "").strip().lower() or None)
        item.setdefault("outs", _safe_int((linescore or {}).get("outs") if isinstance(linescore, dict) else None))
        item.setdefault("progress_fraction", progress_fraction)
        item.setdefault("score_away", score_away)
        item.setdefault("score_home", score_home)
        if item.get("actual_so_far") is None:
            item["actual_so_far"] = item.get("actual_value", item.get("actual"))
        if item.get("actual_value") is None:
            item["actual_value"] = item.get("actual_so_far", item.get("actual"))
        if item.get("actual") is None:
            item["actual"] = item.get("actual_value", item.get("actual_so_far"))
        if item.get("outs") is None:
            item["outs"] = _safe_int((current_play.get("count") or {}).get("outs")) if isinstance(current_play.get("count"), dict) else None
        out.append(item)
    return out


def _parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return date.today()


def _format_start_time_local(game_date: Any, *, fallback_time: Any = None, fallback_ampm: Any = None) -> str:
    text = str(game_date or "").strip()
    if text:
        try:
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if stamp.tzinfo is None and _MLB_USER_TIMEZONE is not None:
                stamp = stamp.replace(tzinfo=_MLB_USER_TIMEZONE)
            local_stamp = stamp.astimezone(_MLB_USER_TIMEZONE) if _MLB_USER_TIMEZONE is not None else stamp.astimezone()
            return f"{local_stamp.strftime('%I').lstrip('0') or '12'}:{local_stamp.strftime('%M')} {local_stamp.strftime('%p')}"
        except Exception:
            pass
    time_text = str(fallback_time or "").strip()
    ampm_text = str(fallback_ampm or "").strip().upper()
    if time_text and ampm_text:
        return f"{time_text} {ampm_text}"
    if time_text:
        return time_text
    return "-"


def _schedule_context(
    *,
    selected_date: str,
    actual_payload: dict[str, Any] | None,
    betting_game: dict[str, Any] | None,
) -> dict[str, str]:
    game_data = (actual_payload or {}).get("gameData") if isinstance((actual_payload or {}).get("gameData"), dict) else {}
    game_meta = (game_data or {}).get("game") if isinstance((game_data or {}).get("game"), dict) else {}
    datetime_meta = (game_data or {}).get("datetime") if isinstance((game_data or {}).get("datetime"), dict) else {}
    betting_meta = betting_game if isinstance(betting_game, dict) else {}

    game_date = str(
        datetime_meta.get("dateTime")
        or betting_meta.get("game_date")
        or betting_meta.get("commence_time")
        or ""
    ).strip()
    official_date = str(
        datetime_meta.get("officialDate")
        or datetime_meta.get("originalDate")
        or betting_meta.get("official_date")
        or selected_date
        or ""
    ).strip()
    start_time = _format_start_time_local(
        game_date,
        fallback_time=datetime_meta.get("time") or betting_meta.get("start_time"),
        fallback_ampm=datetime_meta.get("ampm"),
    )
    detail = start_time if start_time != "-" else (official_date or "Scheduled")
    return {
        "detail": detail,
        "gameDate": game_date,
        "gameType": str(game_meta.get("type") or betting_meta.get("game_type") or "MLB").strip() or "MLB",
        "officialDate": official_date,
        "startTime": start_time,
    }


def _mlb_logo_url(team_id: int | None) -> str | None:
    if not team_id:
        return None
    return f"https://www.mlbstatic.com/team-logos/{int(team_id)}.svg"


def _team_display(abbr: str, fallback_name: str | None = None) -> dict[str, Any]:
    team_abbr = str(abbr or "").strip().upper() or "UNK"
    lookup_abbr = _MLB_TEAM_ABBR_ALIASES.get(team_abbr, team_abbr)
    team_meta = _MLB_TEAM_META_BY_ABBR.get(lookup_abbr, {})
    team_id = team_meta.get("id")
    team_name = str(fallback_name or team_meta.get("name") or team_abbr).strip() or team_abbr
    return {
        "abbr": team_abbr,
        "id": team_id,
        "logo": _mlb_logo_url(team_id),
        "name": team_name,
    }


def _format_pct(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    return f"{number * 100:.1f}%"


def _format_num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _format_signed_num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    prefix = "+" if number > 0 else ""
    return f"{prefix}{_format_num(number)}"


def _format_odds(value: Any) -> str:
    text = str(value or "").strip()
    return text or "-"


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _relative_source_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(default_mlb_source_root()).as_posix()
    except Exception:
        return path.name


def _lineup_health_summary(lineups_path: Path | None, lineups_doc: dict[str, Any] | None) -> dict[str, Any]:
    summary = dict(((lineups_doc or {}).get("summary") or {})) if isinstance(lineups_doc, dict) else {}
    adjusted_teams = int(summary.get("adjusted_teams") or 0)
    partial_teams = int(summary.get("partial_teams") or 0)
    return {
        "exists": bool(lineups_path and lineups_path.exists() and lineups_path.is_file()),
        "path": _relative_source_path(lineups_path),
        "status": "warning" if adjusted_teams > 0 or partial_teams > 0 else "ok",
        "summary": summary,
        "projectedTeams": int(summary.get("projected_teams") or 0),
        "adjustedTeams": adjusted_teams,
        "partialTeams": partial_teams,
        "fallbackPoolTeams": int(summary.get("fallback_pool_teams") or 0),
    }


def _workflow_summary(ops_report_path: Path | None, ops_report_doc: dict[str, Any] | None) -> dict[str, Any]:
    warnings = list((ops_report_doc or {}).get("warnings") or []) if isinstance(ops_report_doc, dict) else []
    raw_errors = list((ops_report_doc or {}).get("errors") or []) if isinstance(ops_report_doc, dict) else []
    validation_errors = [
        str(msg)
        for msg in raw_errors
        if str(msg).strip().lower().startswith("render frontend validation failed:")
    ]
    errors = [
        str(msg)
        for msg in raw_errors
        if not str(msg).strip().lower().startswith("render frontend validation failed:")
    ]
    sims_per_game = None
    stages = (ops_report_doc or {}).get("stages") if isinstance(ops_report_doc, dict) else None
    if isinstance(stages, dict):
        for stage in stages.values():
            command = (stage or {}).get("command") if isinstance(stage, dict) else None
            if not isinstance(command, list):
                continue
            try:
                sims_idx = command.index("--sims")
            except ValueError:
                continue
            if sims_idx + 1 >= len(command):
                continue
            sims_per_game = _safe_int(command[sims_idx + 1])
            if sims_per_game is not None:
                break
    return {
        "exists": bool(ops_report_path and ops_report_path.exists() and ops_report_path.is_file()),
        "path": _relative_source_path(ops_report_path),
        "status": str((ops_report_doc or {}).get("status") or "") if isinstance(ops_report_doc, dict) else "",
        "simsPerGame": sims_per_game,
        "warningCount": int(len(warnings)),
        "errorCount": int(len(errors)),
        "warnings": [str(msg) for msg in warnings[:6]],
        "errors": errors[:6],
        "rawErrorCount": int(len(raw_errors)),
        "rawErrors": [str(msg) for msg in raw_errors[:6]],
        "validationErrorCount": int(len(validation_errors)),
    }


def _snapshot_market_summary(
    snapshot_path: Path | None,
    snapshot_doc: dict[str, Any] | None,
    *,
    root_key: str,
    fallback_counts: dict[str, Any],
) -> dict[str, Any]:
    doc = snapshot_doc if isinstance(snapshot_doc, dict) else {}
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    counts = meta.get("counts") if isinstance(meta.get("counts"), dict) else None
    warnings = meta.get("warnings")
    markets = meta.get("markets")
    rows_value = doc.get(root_key)
    rows = rows_value if isinstance(rows_value, list) else []
    mapping_rows = rows_value if isinstance(rows_value, dict) else {}
    exists = bool(snapshot_path and snapshot_path.exists() and snapshot_path.is_file())
    available = bool(rows or mapping_rows)
    if not available and counts:
        available = any(int(value or 0) > 0 for key, value in counts.items() if key != "markets" and not isinstance(value, dict))
        if not available:
            market_counts = counts.get("markets") if isinstance(counts.get("markets"), dict) else {}
            available = any(int(value or 0) > 0 for value in market_counts.values())
    return {
        "exists": exists,
        "available": available,
        "counts": dict(counts) if counts else dict(fallback_counts),
        "mode": str(doc.get("mode") or "").strip() or None,
        "path": _relative_source_path(snapshot_path),
        "retrievedAt": str(doc.get("retrieved_at") or "").strip() or None,
        "markets": markets if isinstance(markets, (list, dict)) else None,
        "warnings": [str(item) for item in warnings] if isinstance(warnings, list) else [],
    }


def _status_badge_class(status_text: Any) -> str:
    text = str(status_text or "").strip().lower()
    if "live" in text or "in progress" in text:
        return "is-live"
    if "final" in text:
        return "is-final"
    return ""


def _season_for_date(selected_date: str) -> int:
    try:
        return int(str(selected_date).split("-", 1)[0])
    except Exception:
        return date.today().year


def _panel_items_from_hr_targets(output: dict[str, Any], *, limit: int = 3) -> list[str]:
    hr_block = output.get("hitter_hr_likelihood_all") if isinstance(output.get("hitter_hr_likelihood_all"), dict) else {}
    overall = hr_block.get("overall") if isinstance(hr_block.get("overall"), list) else []
    items: list[str] = []
    for row in overall[:limit]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        team = str(row.get("team") or "").strip()
        prob = _format_pct(row.get("p_hr_1plus_cal") or row.get("p_hr_1plus"))
        if name:
            items.append(f"{name} ({team}) - {prob}")
    return items


def _likelihood_items(output: dict[str, Any], group_key: str, prob_key: str, mean_key: str, label: str, *, limit: int = 2) -> list[str]:
    block = output.get("hitter_props_likelihood_topn") if isinstance(output.get("hitter_props_likelihood_topn"), dict) else {}
    rows = block.get(group_key) if isinstance(block.get(group_key), list) else []
    items: list[str] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        items.append(f"{name} {label} { _format_pct(row.get(prob_key)) } | mean {_format_num(row.get(mean_key)) }")
    return items


def _hr_targets_shelf(selected_date: str) -> dict[str, Any] | None:
    summary_path = daily_artifact_path(selected_date, suffix="_hr_targets")
    summary = load_json_file(summary_path)
    rows = summary.get("rows") if isinstance((summary or {}).get("rows"), list) else []
    counts = summary.get("counts") if isinstance((summary or {}).get("counts"), dict) else {}
    top_rows: list[dict[str, str]] = []
    for index, row in enumerate(rows[:4], start=1):
        if not isinstance(row, dict):
            continue
        top_rows.append(
            {
                "rank": f"#{index}",
                "player_name": str(row.get("player_name") or "Unknown hitter").strip() or "Unknown hitter",
                "team": str(row.get("team") or "-").strip() or "-",
                "matchup": str(row.get("matchup") or "-").strip() or "-",
                "probability": _format_pct(row.get("p_hr_1plus")),
                "support": _format_num(row.get("hr_support_score")),
                "summary": str(row.get("hr_target_summary") or "No summary available.").strip() or "No summary available.",
                "p_hr_1plus": row.get("p_hr_1plus"),
                "support_score": row.get("hr_support_score"),
                "support_label": str(row.get("hr_support_label") or "").strip(),
                "pa_mean": row.get("pa_mean"),
                "lineup_order": row.get("lineup_order"),
                "opponent_pitcher_name": str(row.get("opponent_pitcher_name") or "").strip(),
                "writeup": str(row.get("hr_target_summary") or row.get("matchup") or "").strip(),
            }
        )
    if not top_rows:
        return None
    return {
        "label": "Home run targets",
        "title": "HR Targets",
        "kicker": "Best 1+ HR looks",
        "body": f"{len(rows)} targets surfaced for the slate.",
        "href": f"/mlb/hr-targets?date={selected_date}",
        "cta": "Open board",
        "source_path": Path(summary_path).name,
        "row_count": int(counts.get("rows") or len(rows)),
        "game_count": int(counts.get("games") or 0),
        "rows": top_rows,
    }


def _market_title(row: dict[str, Any], away_abbr: str, home_abbr: str) -> str:
    player_name = str(row.get("player_name") or row.get("pitcher_name") or "").strip()
    selection = str(row.get("selection") or "pick").strip().title()
    market_name = str(row.get("prop") or row.get("market") or "bet").strip().replace("_", " ").title()
    line = row.get("market_line") if row.get("market_line") is not None else row.get("line")
    if player_name:
        line_piece = f" { _format_num(line) }" if line is not None else ""
        return f"{player_name} {selection}{line_piece} {market_name}".strip()
    market_key = str(row.get("market") or "").strip().lower()
    if market_key == "ml":
        side = str(row.get("selection") or "").strip().lower()
        team = away_abbr if side == "away" else home_abbr if side == "home" else f"{away_abbr} @ {home_abbr}"
        return f"{team} ML"
    if market_key == "totals":
        line_piece = f" { _format_num(line) }" if line is not None else ""
        return f"{selection}{line_piece} Total".strip()
    return f"{away_abbr} @ {home_abbr} {selection} {market_name}".strip()


def _selected_market_odds(row: dict[str, Any]) -> Any:
    return row.get("odds") or row.get("price")


def _market_tiles(game_payload: dict[str, Any], away_abbr: str, home_abbr: str) -> list[dict[str, str]]:
    markets = game_payload.get("markets") if isinstance(game_payload.get("markets"), dict) else {}
    totals = markets.get("totals") if isinstance(markets.get("totals"), dict) else None
    moneyline = markets.get("ml") if isinstance(markets.get("ml"), dict) else None
    pitcher_rows = markets.get("pitcherProps") if isinstance(markets.get("pitcherProps"), list) else []
    pitcher_extra_rows = markets.get("extraPitcherProps") if isinstance(markets.get("extraPitcherProps"), list) else []
    hitter_rows = markets.get("hitterProps") if isinstance(markets.get("hitterProps"), list) else []
    hitter_extra_rows = markets.get("extraHitterProps") if isinstance(markets.get("extraHitterProps"), list) else []

    def tile(label: str, title: str, sub: str) -> dict[str, str]:
        return {"label": label, "title": title, "sub": sub}

    if totals:
        total_title = f"{str(totals.get('selection') or '').upper()} { _format_num(totals.get('market_line')) } { _format_odds(_selected_market_odds(totals)) }".strip()
        total_sub = f"model { _format_pct(totals.get('model_prob')) }" if totals.get("model_prob") is not None else "Official total"
    else:
        total_title = "No total play"
        total_sub = "Off card"

    if moneyline:
        selection = str(moneyline.get("selection") or "").strip().lower()
        picked_team = home_abbr if selection == "home" else away_abbr if selection == "away" else "No ML play"
        ml_title = f"{picked_team} { _format_odds(_selected_market_odds(moneyline)) }".strip()
        ml_sub = f"model { _format_pct(moneyline.get('model_prob')) }" if moneyline.get("model_prob") is not None else "Official ML"
    else:
        ml_title = "No ML play"
        ml_sub = "Off card"

    first_pitcher = next((row for row in pitcher_rows if isinstance(row, dict)), None) or next((row for row in pitcher_extra_rows if isinstance(row, dict)), None)
    if first_pitcher:
        pitch_title = f"{str(first_pitcher.get('pitcher_name') or 'Pitcher').strip()} { str(first_pitcher.get('selection') or '').title() } { _format_num(first_pitcher.get('market_line')) } { str(first_pitcher.get('prop') or '').replace('_', ' ').title() }".strip()
        pitch_sub = _format_odds(_selected_market_odds(first_pitcher)) if pitcher_rows else f"Playable only | { _format_odds(_selected_market_odds(first_pitcher)) }".strip()
    else:
        pitch_title = "No locked pitcher prop"
        pitch_sub = "Off card"

    first_hitter = next((row for row in hitter_rows if isinstance(row, dict)), None) or next((row for row in hitter_extra_rows if isinstance(row, dict)), None)
    if first_hitter:
        hit_title = f"{str(first_hitter.get('player_name') or 'Hitter').strip()} { str(first_hitter.get('selection') or '').title() } { _format_num(first_hitter.get('market_line')) } { str(first_hitter.get('prop') or '').replace('_', ' ').title() }".strip()
        hit_sub = _format_odds(_selected_market_odds(first_hitter)) if hitter_rows else f"Playable only | { _format_odds(_selected_market_odds(first_hitter)) }".strip()
    else:
        hit_title = "No locked hitter prop"
        hit_sub = "Off card"

    return [
        tile("Game total", total_title, total_sub),
        tile("Moneyline", ml_title, ml_sub),
        tile("Pitcher props", pitch_title, pitch_sub),
        tile("Hitter props", hit_title, hit_sub),
    ]


def _starter_metrics(output: dict[str, Any]) -> list[dict[str, str]]:
    starters = output.get("starter_names") if isinstance(output.get("starter_names"), dict) else {}
    return [
        {"label": "Away starter", "value": str(starters.get("away") or "TBD").strip() or "TBD"},
        {"label": "Home starter", "value": str(starters.get("home") or "TBD").strip() or "TBD"},
    ]


def _starter_badge_short_label(prop_key: Any) -> str:
    normalized = str(prop_key or "").strip().lower()
    if normalized == "strikeouts":
        return "K"
    if normalized == "outs":
        return "O"
    if normalized == "hits_allowed":
        return "H"
    if normalized == "walks_allowed":
        return "BB"
    if normalized == "earned_runs":
        return "ER"
    return normalized[:3].upper() or "P"


def _starter_badge_tone(row: dict[str, Any]) -> str:
    edge = abs(float(_safe_float(row.get("edge")) or 0.0))
    model_prob = float(_safe_float(row.get("selected_side_model_prob")) or _safe_float(row.get("model_prob_over")) or 0.0)
    if edge >= 0.07 or model_prob >= 0.58:
        return "strong"
    if edge >= 0.04 or model_prob >= 0.54:
        return "solid"
    return "soft"


def _starter_badges_for_pitcher_rows(rows: list[dict[str, Any]], pitcher_name: str) -> list[dict[str, Any]]:
    if not rows:
        return []
    normalized_name = _normalize_live_name(pitcher_name)
    if not normalized_name:
        return []

    matched_rows = [
        row for row in rows
        if isinstance(row, dict) and _normalize_live_name(row.get("pitcher_name")) == normalized_name
    ]
    badges: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for row in matched_rows[:2]:
        prop_key = str(row.get("prop") or "").strip().lower()
        selection = str(row.get("selection") or "").strip().lower()
        line_float = _safe_float(row.get("market_line"))
        line_value = _format_num(line_float)
        short_label = _starter_badge_short_label(prop_key)
        target_value: int | None = None
        target_text = line_value
        if line_float is not None:
            if selection == "over":
                target_value = int(float(line_float) // 1) + 1
                target_text = f"{target_value}+"
            elif selection == "under":
                target_value = int(float(line_float) // 1)
                target_text = f"<={target_value}"
        label = f"{short_label} {target_text}".strip()
        if not label or label in seen_labels:
            continue
        model_prob = float(_safe_float(row.get("selected_side_model_prob")) or _safe_float(row.get("model_prob_over")) or 0.0)
        market_text = prop_key.replace("_", " ").title()
        detail_lead = f"{str(row.get('pitcher_name') or pitcher_name).strip()} {selection.title()} {line_value} {market_text}".strip()
        detail_parts = [
            detail_lead,
        ]
        if row.get("odds") is not None:
            detail_parts.append(f"Odds {_format_odds(row.get('odds'))}")
        if row.get("edge") is not None:
            detail_parts.append(f"Edge {_format_pct(abs(float(_safe_float(row.get('edge')) or 0.0)))}")
        badge = {
            "label": label,
            "stat": prop_key or None,
            "target": target_value if target_value is not None else line_float,
            "targets": [target_value] if target_value is not None else [],
            "tone": _starter_badge_tone(row),
            "detail": " | ".join(part for part in detail_parts if part),
            "hitProb": round(model_prob, 3) if model_prob else None,
        }
        badges.append(badge)
        seen_labels.add(label)
    return badges


def _starter_pitcher_id(rows: list[dict[str, Any]], pitcher_name: str) -> int | None:
    normalized_name = _normalize_live_name(pitcher_name)
    if not normalized_name:
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _normalize_live_name(row.get("pitcher_name")) != normalized_name:
            continue
        pitcher_id = _safe_int(row.get("pitcher_id"))
        if pitcher_id is not None:
            return int(pitcher_id)
    return None


def _pregame_starter_ladder_badge_configs() -> dict[str, dict[str, Any]]:
    return {
        "strikeouts": {"min_hit_prob": 0.2, "max_rungs": 4, "include_base_over": True},
        "outs": {"min_hit_prob": 0.24, "max_rungs": 2, "include_base_over": False},
        "hits_allowed": {"min_hit_prob": 0.2, "max_rungs": None, "include_base_over": True},
        "walks_allowed": {"min_hit_prob": 0.2, "max_rungs": None, "include_base_over": True},
    }


def _starter_ladder_market_line_from_row(row: dict[str, Any], *, stat_key: str) -> float | None:
    direct_line = _safe_float(row.get("marketLine"))
    if direct_line is not None:
        return float(direct_line)
    pregame_line = _safe_float(row.get("pregameMarketLine"))
    if pregame_line is not None:
        return float(pregame_line)
    market_rows = row.get("marketLinesByStat") if isinstance(row.get("marketLinesByStat"), list) else []
    for market_row in market_rows:
        if not isinstance(market_row, dict):
            continue
        if str(market_row.get("stat") or "").strip().lower() != str(stat_key or "").strip().lower():
            continue
        line_value = _safe_float(market_row.get("line"))
        if line_value is not None:
            return float(line_value)
    return None


def _starter_ladder_badge_from_ladder_row(
    row: dict[str, Any] | None,
    *,
    stat_key: str,
    short_label: str,
    min_hit_prob: float,
    include_base_over: bool,
    max_rungs: int | None,
) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    market_line = _starter_ladder_market_line_from_row(row, stat_key=stat_key)
    ladder_rows = [entry for entry in (row.get("ladder") or []) if isinstance(entry, dict)]
    if market_line is None or not ladder_rows:
        return None
    base_over_total = int(float(market_line) // 1) + 1
    supported_totals: list[int] = []
    last_supported_prob: float | None = None
    for ladder_row in ladder_rows:
        total = _safe_int(ladder_row.get("total"))
        hit_prob = _safe_float(ladder_row.get("hitProb"))
        if total is None or hit_prob is None:
            continue
        if float(total) <= float(market_line):
            continue
        if not include_base_over and int(total) <= int(base_over_total):
            continue
        if float(hit_prob) < float(min_hit_prob):
            continue
        supported_totals.append(int(total))
        last_supported_prob = float(hit_prob)

    if max_rungs is not None and int(max_rungs) > 0 and len(supported_totals) > int(max_rungs):
        supported_totals = supported_totals[: int(max_rungs)]
        matched_prob = next(
            (
                _safe_float(ladder_row.get("hitProb"))
                for ladder_row in ladder_rows
                if _safe_int(ladder_row.get("total")) == int(supported_totals[-1])
            ),
            last_supported_prob,
        )
        last_supported_prob = float(matched_prob) if matched_prob is not None else last_supported_prob

    if not supported_totals or last_supported_prob is None:
        return None
    detail_parts: list[str] = []
    matchup_summary = str(row.get("matchupSummary") or "").strip()
    if matchup_summary:
        detail_parts.append(matchup_summary)
    return _starter_ladder_badge_from_supported_totals(
        supported_totals,
        stat_key=stat_key,
        short_label=short_label,
        last_supported_prob=last_supported_prob,
        detail_parts=detail_parts,
        max_rungs=max_rungs,
    )


def _pregame_starter_ladder_badges_for_pitcher(
    game_groups: dict[str, Any] | None,
    *,
    game_pk: int | None,
    pitcher_id: int | None,
    pitcher_name: str,
) -> list[dict[str, Any]]:
    if not isinstance(game_groups, dict) or game_pk is None or int(game_pk) <= 0:
        return []
    normalized_pitcher = _normalize_live_name(pitcher_name)

    def _resolve_row(group_key: str) -> dict[str, Any] | None:
        group = game_groups.get(group_key) if isinstance(game_groups.get(group_key), dict) else {}
        rows = group.get("rows") if isinstance(group.get("rows"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_game_pk = _safe_int(row.get("gamePk"))
            if row_game_pk is None or int(row_game_pk) != int(game_pk):
                continue
            row_pitcher_id = _safe_int(row.get("pitcherId"))
            if pitcher_id is not None and row_pitcher_id is not None and int(row_pitcher_id) == int(pitcher_id):
                return row
            if normalized_pitcher and _normalize_live_name(row.get("pitcherName")) == normalized_pitcher:
                return row
        return None

    badges: list[dict[str, Any]] = []
    for stat_key, cfg in _pregame_starter_ladder_badge_configs().items():
        badge = _starter_ladder_badge_from_ladder_row(
            _resolve_row(stat_key),
            stat_key=stat_key,
            short_label=_starter_ladder_badge_short_label(stat_key),
            min_hit_prob=float(cfg.get("min_hit_prob") or 0.2),
            include_base_over=bool(cfg.get("include_base_over", True)),
            max_rungs=_safe_int(cfg.get("max_rungs")),
        )
        if isinstance(badge, dict):
            badges.append(badge)
    return badges


def _merge_starter_badge_lists(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for bucket in (primary, secondary):
        for badge in bucket:
            if not isinstance(badge, dict):
                continue
            badge_key = str(badge.get("stat") or badge.get("label") or "").strip().lower()
            if not badge_key or badge_key in seen_keys:
                continue
            merged.append(dict(badge))
            seen_keys.add(badge_key)
    return merged


def _pregame_market_supported_totals(
    market_entry: dict[str, Any] | None,
    *,
    stat_key: str | None,
) -> list[int]:
    if not isinstance(market_entry, dict):
        return []
    market = market_entry.get(str(stat_key or "").strip().lower())
    if not isinstance(market, dict):
        return []
    out: list[int] = []
    for candidate in _live_pitcher_ladder_market_candidates(market):
        line_value = _safe_float(candidate.get("line"))
        if line_value is None:
            continue
        total = int(float(line_value) // 1) + 1
        if int(total) not in out:
            out.append(int(total))
    return out


def _filter_badges_to_current_market(
    badges: list[dict[str, Any]],
    *,
    market_entry: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for badge in badges:
        if not isinstance(badge, dict):
            continue
        stat_key = _starter_ladder_badge_stat_key(badge)
        if not stat_key:
            continue
        allowed_totals = _pregame_market_supported_totals(market_entry, stat_key=stat_key)
        if not allowed_totals:
            continue
        raw_targets = [int(total) for total in (badge.get("targets") or []) if _safe_int(total) is not None]
        if not raw_targets:
            target_total = _safe_int(badge.get("target"))
            if target_total is not None:
                raw_targets = [int(target_total)]
        if not raw_targets:
            continue
        supported = [int(total) for total in raw_targets if int(total) in set(allowed_totals)]
        if not supported:
            continue
        if supported == raw_targets:
            filtered.append(dict(badge))
            continue
        rebuilt = _starter_ladder_badge_from_supported_totals(
            supported,
            stat_key=stat_key,
            short_label=_starter_ladder_badge_short_label(stat_key),
            last_supported_prob=_safe_float(badge.get("hitProb")),
            detail_parts=[str(badge.get("detail") or "").strip()],
            max_rungs=None,
        )
        if isinstance(rebuilt, dict):
            rebuilt["tone"] = badge.get("tone") or rebuilt.get("tone")
            filtered.append(rebuilt)
    return filtered


def _attach_cards_pregame_starter_ladder_badges(games: list[dict[str, Any]], *, selected_date: str) -> None:
    if not isinstance(games, list):
        return
    ladders_doc = load_json_file(daily_ladders_path(selected_date))
    groups = ((ladders_doc or {}).get("groups") or {}).get("pitcher") if isinstance((ladders_doc or {}).get("groups"), dict) else {}
    if not isinstance(groups, dict):
        return
    market_lines = _pitcher_snapshot_market_lines(selected_date)
    for card in games:
        if not isinstance(card, dict):
            continue
        game_pk = _safe_int(card.get("gamePk"))
        probable = card.get("probable") if isinstance(card.get("probable"), dict) else None
        if game_pk is None or not isinstance(probable, dict):
            continue
        for side in ("away", "home"):
            entry = probable.get(side)
            if not isinstance(entry, dict):
                continue
            starter_name = str(entry.get("fullName") or entry.get("name") or "").strip()
            if not starter_name:
                continue
            market_entry = _market_lines_for_live_name(market_lines, starter_name)
            starter_id = _safe_int(entry.get("id"))
            ladder_badges = _pregame_starter_ladder_badges_for_pitcher(
                groups,
                game_pk=int(game_pk),
                pitcher_id=starter_id,
                pitcher_name=starter_name,
            )
            ladder_badges = _filter_badges_to_current_market(ladder_badges, market_entry=market_entry)
            existing_badges = [
                badge
                for badge in (
                    entry.get("pregameLadderBadges")
                    if isinstance(entry.get("pregameLadderBadges"), list)
                    else (entry.get("ladderBadges") or [])
                )
                if isinstance(badge, dict)
            ]
            existing_badges = _filter_badges_to_current_market(existing_badges, market_entry=market_entry)
            merged_badges = _merge_starter_badge_lists(ladder_badges, existing_badges)
            if merged_badges:
                entry["ladderBadges"] = [dict(badge) for badge in merged_badges]
                entry["pregameLadderBadges"] = [dict(badge) for badge in merged_badges]
            else:
                entry.pop("ladderBadges", None)
                entry.pop("pregameLadderBadges", None)


def _source_probable(output: dict[str, Any], betting_game: dict[str, Any] | None = None) -> dict[str, Any]:
    starters = output.get("starter_names") if isinstance(output.get("starter_names"), dict) else {}
    markets = (betting_game or {}).get("markets") if isinstance((betting_game or {}).get("markets"), dict) else {}
    pitcher_rows = [
        row
        for key in ("pitcherProps", "extraPitcherProps")
        for row in (markets.get(key) if isinstance(markets.get(key), list) else [])
        if isinstance(row, dict)
    ]
    away_name = str(starters.get("away") or "TBD").strip() or "TBD"
    home_name = str(starters.get("home") or "TBD").strip() or "TBD"
    away_id = _starter_pitcher_id(pitcher_rows, away_name)
    home_id = _starter_pitcher_id(pitcher_rows, home_name)
    away_badges = _starter_badges_for_pitcher_rows(pitcher_rows, away_name)
    home_badges = _starter_badges_for_pitcher_rows(pitcher_rows, home_name)
    return {
        "away": {
            "id": away_id,
            "fullName": away_name,
            "ladderBadges": away_badges,
            "pregameLadderBadges": [dict(badge) for badge in away_badges],
        },
        "home": {
            "id": home_id,
            "fullName": home_name,
            "ladderBadges": home_badges,
            "pregameLadderBadges": [dict(badge) for badge in home_badges],
        },
    }


def _source_predictions(output: dict[str, Any]) -> dict[str, Any]:
    predictions: dict[str, Any] = {}
    for key in ("first1", "first3", "first5", "full"):
        section = output.get(key) if isinstance(output.get(key), dict) else {}
        predictions[key] = {
            "away_runs_mean": section.get("away_runs_mean"),
            "home_runs_mean": section.get("home_runs_mean"),
            "away_win_prob": section.get("away_win_prob"),
            "home_win_prob": section.get("home_win_prob"),
            "tie_prob": section.get("tie_prob"),
        }
    return predictions


def _source_status(actual_payload: dict[str, Any] | None) -> dict[str, str]:
    status = (actual_payload.get("gameData") or {}).get("status") if isinstance((actual_payload or {}).get("gameData"), dict) else {}
    abstract = str((status or {}).get("abstractGameState") or "Pregame").strip() or "Pregame"
    detailed = str((status or {}).get("detailedState") or "Scheduled").strip() or "Scheduled"
    return {"abstract": abstract, "detailed": detailed}


def _probability_rows(output: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, label in (("first1", "First 1"), ("first3", "First 3"), ("first5", "First 5"), ("full", "Full game")):
        section = output.get(key) if isinstance(output.get(key), dict) else {}
        away_prob = float(section.get("away_win_prob") or 0.0) if section.get("away_win_prob") is not None else None
        home_prob = float(section.get("home_win_prob") or 0.0) if section.get("home_win_prob") is not None else None
        tie_prob = float(section.get("tie_prob") or 0.0) if section.get("tie_prob") is not None else None
        if away_prob is None and home_prob is None:
            continue
        away_pct = max(0.0, min(100.0, (away_prob or 0.0) * 100.0))
        home_pct = max(0.0, min(100.0, (home_prob or 0.0) * 100.0))
        rows.append(
            {
                "label": label,
                "away_pct": f"{away_pct:.1f}",
                "home_pct": f"{home_pct:.1f}",
                "summary": f"{str(output.get('away') or 'Away').strip() or 'Away'} { _format_pct(section.get('away_win_prob')) } | { str(output.get('home') or 'Home').strip() or 'Home'} { _format_pct(section.get('home_win_prob')) } | Tie { _format_pct(tie_prob) }",
            }
        )
    return rows


def _run_projection_bins(mean_total: float | None) -> list[dict[str, str]]:
    if mean_total is None:
        return []
    center = max(0, int(round(mean_total)))
    raw = []
    for total in range(max(0, center - 3), center + 4):
        weight = exp(-((total - mean_total) ** 2) / (2 * (1.35 ** 2)))
        raw.append((total, weight))
    total_weight = sum(weight for _, weight in raw) or 1.0
    return [
        {
            "total": str(total),
            "pct": f"{(weight / total_weight) * 100:.1f}",
            "width": f"{max((weight / total_weight) * 100.0, 1.5):.2f}",
        }
        for total, weight in raw
    ]


def _run_projection_rows(output: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, label in (("first1", "First 1"), ("first3", "First 3"), ("first5", "First 5"), ("full", "Full game")):
        section = output.get(key) if isinstance(output.get(key), dict) else {}
        away_mean = float(section.get("away_runs_mean") or 0.0) if section.get("away_runs_mean") is not None else None
        home_mean = float(section.get("home_runs_mean") or 0.0) if section.get("home_runs_mean") is not None else None
        if away_mean is None and home_mean is None:
            continue
        total_mean = (away_mean or 0.0) + (home_mean or 0.0)
        bins = _run_projection_bins(total_mean)
        mode_bin = max(bins, key=lambda row: float(row.get("pct") or 0.0), default=None)
        summary_bits = []
        if mode_bin:
            summary_bits.append(f"Mode {mode_bin.get('total')} ({mode_bin.get('pct')}%)")
        summary_bits.append(f"Mean { _format_num(total_mean) }")
        rows.append({"label": label, "bins": bins, "summary": " | ".join(summary_bits)})
    return rows


def _segment_overview_cards(output: dict[str, Any], betting_game: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    markets = betting_game.get("markets") if isinstance((betting_game or {}).get("markets"), dict) else {}
    ml = markets.get("ml") if isinstance(markets.get("ml"), dict) else None
    totals = markets.get("totals") if isinstance(markets.get("totals"), dict) else None
    away_abbr = str(output.get("away") or "Away").strip() or "Away"
    home_abbr = str(output.get("home") or "Home").strip() or "Home"
    cards: list[dict[str, Any]] = []
    for key, label in (("first1", "F1"), ("first3", "F3"), ("first5", "F5"), ("full", "Full game")):
        section = output.get(key) if isinstance(output.get(key), dict) else {}
        away_mean = float(section.get("away_runs_mean") or 0.0) if section.get("away_runs_mean") is not None else None
        home_mean = float(section.get("home_runs_mean") or 0.0) if section.get("home_runs_mean") is not None else None
        total_mean = (away_mean or 0.0) + (home_mean or 0.0)
        margin = (home_mean or 0.0) - (away_mean or 0.0)
        has_full_market = key == "full" and (ml or totals)
        if has_full_market and totals:
            main = f"{str(totals.get('selection') or '').title()} { _format_num(totals.get('market_line')) }"
            badge = "Total bet"
            live_market = f"{str(totals.get('selection') or '').title()} { _format_num(totals.get('market_line')) } { _format_odds(_selected_market_odds(totals)) }"
            best_edge = _format_pct(totals.get("edge"))
        elif has_full_market and ml:
            pick_team = home_abbr if str(ml.get('selection') or '').lower() == 'home' else away_abbr
            main = f"{pick_team} ML"
            badge = "ML bet"
            live_market = f"{pick_team} { _format_odds(_selected_market_odds(ml)) }"
            best_edge = _format_pct(ml.get("edge"))
        else:
            main = "No surfaced bet"
            badge = "No bet"
            live_market = "Below threshold"
            best_edge = "-"
        market_prob = _format_pct(ml.get("model_prob") if ml else None) if key == "full" and ml else "0.0%"
        cards.append(
            {
                "label": label,
                "main": main,
                "badge": badge,
                "badge_class": "is-live" if badge != "No bet" else "",
                "subtitle": f"{away_abbr} { _format_num(away_mean) } - {home_abbr} { _format_num(home_mean) } | Total { _format_num(total_mean) }",
                "score": f"{away_abbr} 0 - {home_abbr} 0",
                "home_win": _format_pct(section.get("home_win_prob")),
                "market": market_prob,
                "best_edge": best_edge,
                "best_edge_class": "is-positive" if best_edge not in {"-", "0.0%"} else "",
                "live_market": live_market,
                "reason": "Pregame recommendations are suppressed while this surface is under re-evaluation." if badge == "No bet" else "Official full-game recommendation surfaced from the saved market payload.",
                "foot_left": (
                    f"Total { _format_num(totals.get('market_line') if totals else None) } | {away_abbr} { _format_odds(ml.get('away_odds')) if ml else '-' } / {home_abbr} { _format_odds(ml.get('home_odds')) if ml else '-' }"
                    if (ml or totals)
                    else "No tracked market line"
                ),
                "foot_right": f"Projected margin { _format_signed_num(margin) }",
            }
        )
    return cards


def _prop_item_detail(row: dict[str, Any]) -> str:
    parts: list[str] = []
    odds = _format_odds(row.get("odds") or row.get("price"))
    if odds != "-":
        parts.append(odds)
    edge = _format_pct(row.get("edge"))
    if edge != "-":
        parts.append(f"edge {edge}")
    confidence = str(row.get("confidence") or row.get("tier") or "").strip()
    if confidence:
        parts.append(confidence)
    return " | ".join(parts) or "Model-qualified play"


def _is_pitcher_prop_row(row: dict[str, Any]) -> bool:
    market_key = str(row.get("market") or "").strip().lower()
    if market_key == "pitcher_props":
        return True
    return bool(str(row.get("pitcher_name") or "").strip())


def _prop_group_section(title: str, rows: list[dict[str, Any]], away_abbr: str, home_abbr: str) -> dict[str, Any] | None:
    items = [
        {
            "title": _market_title(row, away_abbr, home_abbr),
            "detail": _prop_item_detail(row),
        }
        for row in rows
        if isinstance(row, dict)
    ]
    if not items:
        return None
    return {"title": title, "items": items}


def _prop_row_type(row: dict[str, Any]) -> str:
    return "pitcher" if _is_pitcher_prop_row(row) else "hitter"


def _prop_filter_option(label: str, value: str, count: int, *, active: bool = False, disabled: bool = False) -> dict[str, Any]:
    return {
        "label": label,
        "value": value,
        "count": count,
        "active": active,
        "disabled": disabled,
    }


def _props_panel_context(
    game_payload: dict[str, Any],
    hitter_items: list[str],
    starter_title: str,
    starter_body: str,
    sim_items: list[str],
    official_items: list[str],
) -> dict[str, Any]:
    markets = game_payload.get("markets") if isinstance(game_payload.get("markets"), dict) else {}
    away_abbr = str(((markets.get("ml") or markets.get("totals") or {}).get("away_abbr") if isinstance(markets.get("ml") or markets.get("totals"), dict) else game_payload.get("away_abbr") or "AWY")).strip() or "AWY"
    home_abbr = str(((markets.get("ml") or markets.get("totals") or {}).get("home_abbr") if isinstance(markets.get("ml") or markets.get("totals"), dict) else game_payload.get("home_abbr") or "HOM")).strip() or "HOM"
    official_rows = [row for key in ("pitcherProps", "hitterProps") for row in (markets.get(key) if isinstance(markets.get(key), list) else []) if isinstance(row, dict)]
    playable_rows = [row for key in ("extraPitcherProps", "extraHitterProps") for row in (markets.get(key) if isinstance(markets.get(key), list) else []) if isinstance(row, dict)]
    all_rows = official_rows + playable_rows
    prop_groups = _props_tab_groups(game_payload)

    over_count = sum(1 for row in all_rows if str(row.get("selection") or "").strip().lower() == "over")
    under_count = sum(1 for row in all_rows if str(row.get("selection") or "").strip().lower() == "under")
    pitcher_count = sum(1 for row in all_rows if _prop_row_type(row) == "pitcher")
    hitter_count = sum(1 for row in all_rows if _prop_row_type(row) == "hitter")
    total_count = len(all_rows)

    if official_rows and playable_rows:
        prop_summary = f"{len(official_rows)} official · +{len(playable_rows)} playable"
    elif official_rows:
        prop_summary = f"{len(official_rows)} official play{'s' if len(official_rows) != 1 else ''}"
    elif playable_rows:
        prop_summary = f"{len(playable_rows)} playable lane{'s' if len(playable_rows) != 1 else ''}"
    else:
        prop_summary = "No prop board"

    filter_groups = [
        {
            "label": "Board",
            "options": [
                _prop_filter_option("Live", "live", 0, disabled=True),
                _prop_filter_option("Pregame", "pregame", total_count, active=True, disabled=total_count == 0),
            ],
        },
        {
            "label": "Side",
            "options": [
                _prop_filter_option("All", "all", total_count, active=True, disabled=total_count == 0),
                _prop_filter_option("Over", "over", over_count, disabled=over_count == 0),
                _prop_filter_option("Under", "under", under_count, disabled=under_count == 0),
            ],
        },
        {
            "label": "Type",
            "options": [
                _prop_filter_option("All", "all", total_count, active=True, disabled=total_count == 0),
                _prop_filter_option("Pitcher", "pitcher", pitcher_count, disabled=pitcher_count == 0),
                _prop_filter_option("Hitter", "hitter", hitter_count, disabled=hitter_count == 0),
            ],
        },
    ]

    selected_row = official_rows[0] if official_rows else playable_rows[0] if playable_rows else None
    if selected_row:
        line = selected_row.get("market_line") if selected_row.get("market_line") is not None else selected_row.get("line")
        line_label = f"{str(selected_row.get('selection') or 'Pick').strip().title()} {_format_num(line)}" if line is not None else str(selected_row.get("selection") or "Pick").strip().title()
        confidence = str(selected_row.get("confidence") or selected_row.get("tier") or "-").strip() or "-"
        lens_main = _market_title(selected_row, away_abbr, home_abbr)
        lens_copy = _prop_item_detail(selected_row)
        lens_metrics = [
            {"label": "Board", "value": "Official" if selected_row in official_rows else "Playable"},
            {"label": "Line", "value": line_label or "-"},
            {"label": "Odds", "value": _format_odds(_selected_market_odds(selected_row))},
            {"label": "Edge", "value": _format_pct(selected_row.get("edge"))},
            {"label": "Confidence", "value": confidence},
            {"label": "Prop", "value": str(selected_row.get("prop") or selected_row.get("market") or "Prop").replace("_", " ").title()},
        ]
        lens_badge = "Official" if selected_row in official_rows else "Playable"
        lens_badge_class = "is-live" if selected_row in official_rows else ""
    else:
        lens_main = "No prop selected"
        lens_copy = "No published official or secondary playable pregame props were captured for this matchup on the selected date."
        lens_metrics = [
            {"label": "Board", "value": "Pregame"},
            {"label": "Status", "value": "Unavailable"},
        ]
        lens_badge = "Pregame"
        lens_badge_class = ""

    context_sections = [
        {
            "title": "Top prop context",
            "items": hitter_items or ["No hitter look summary was available for this game."],
        },
        {
            "title": "Starters",
            "items": [starter_title] + ([starter_body] if starter_body else []),
        },
    ]
    if sim_items:
        context_sections.append({"title": "Sim context", "items": sim_items[:2]})
    if official_items:
        context_sections.append({"title": "Card context", "items": official_items[:2]})

    return {
        "prop_groups": prop_groups,
        "prop_summary": prop_summary,
        "prop_filter_groups": filter_groups,
        "empty_copy": "No live or pregame props are available for this game yet. When market snapshots are present, official and secondary playable lanes will populate here.",
        "prop_lens": {
            "main": lens_main,
            "copy": lens_copy,
            "badge": lens_badge,
            "badge_class": lens_badge_class,
            "metrics": [metric for metric in lens_metrics if str(metric.get("value") or "").strip()],
            "sections": context_sections,
        },
    }


def _props_tab_groups(game_payload: dict[str, Any]) -> list[dict[str, Any]]:
    markets = game_payload.get("markets") if isinstance(game_payload.get("markets"), dict) else {}
    away_abbr = str(((markets.get("ml") or markets.get("totals") or {}).get("away_abbr") if isinstance(markets.get("ml") or markets.get("totals"), dict) else game_payload.get("away_abbr") or "AWY")).strip() or "AWY"
    home_abbr = str(((markets.get("ml") or markets.get("totals") or {}).get("home_abbr") if isinstance(markets.get("ml") or markets.get("totals"), dict) else game_payload.get("home_abbr") or "HOM")).strip() or "HOM"
    official_rows = [row for key in ("pitcherProps", "hitterProps") for row in (markets.get(key) if isinstance(markets.get(key), list) else []) if isinstance(row, dict)]
    playable_rows = [row for key in ("extraPitcherProps", "extraHitterProps") for row in (markets.get(key) if isinstance(markets.get(key), list) else []) if isinstance(row, dict)]

    grouped: list[dict[str, Any]] = []
    for title, variant, body, rows in (
        (
            "Official picks",
            "official",
            "Qualified player props that made the published card for this matchup.",
            official_rows,
        ),
        (
            "Other playable props",
            "secondary",
            "Qualified lanes that did not make the official card after caps and one-prop-per-player selection.",
            playable_rows,
        ),
    ):
        if not rows:
            continue
        pitcher_rows = [row for row in rows if _is_pitcher_prop_row(row)]
        hitter_rows = [row for row in rows if not _is_pitcher_prop_row(row)]
        sections = [
            section
            for section in (
                _prop_group_section("Pitcher props", pitcher_rows, away_abbr, home_abbr),
                _prop_group_section("Hitter props", hitter_rows, away_abbr, home_abbr),
            )
            if section
        ]
        if sections:
            grouped.append(
                {
                    "title": title,
                    "variant": variant,
                    "body": body,
                    "count": len(rows),
                    "sections": sections,
                }
            )
    return grouped


def _official_market_items(game_payload: dict[str, Any], *, limit: int = 4) -> tuple[list[str], int, int]:
    markets = game_payload.get("markets") if isinstance(game_payload.get("markets"), dict) else {}
    away_abbr = str(((markets.get("ml") or markets.get("totals") or {}).get("away_abbr") if isinstance(markets.get("ml") or markets.get("totals"), dict) else game_payload.get("away_abbr") or "AWY")).strip() or "AWY"
    home_abbr = str(((markets.get("ml") or markets.get("totals") or {}).get("home_abbr") if isinstance(markets.get("ml") or markets.get("totals"), dict) else game_payload.get("home_abbr") or "HOM")).strip() or "HOM"
    official_rows: list[dict[str, Any]] = []
    playable_rows: list[dict[str, Any]] = []
    for key in ("ml", "totals"):
        row = markets.get(key)
        if isinstance(row, dict):
            official_rows.append(row)
    for key in ("pitcherProps", "hitterProps"):
        rows = markets.get(key) if isinstance(markets.get(key), list) else []
        official_rows.extend([row for row in rows if isinstance(row, dict)])
    for key in ("extraPitcherProps", "extraHitterProps"):
        rows = markets.get(key) if isinstance(markets.get(key), list) else []
        playable_rows.extend([row for row in rows if isinstance(row, dict)])

    items = [
        f"{_market_title(row, away_abbr, home_abbr)} ({_format_odds(row.get('odds') or row.get('price'))}, edge {_format_pct(row.get('edge'))})"
        for row in official_rows[:limit]
    ]
    return items, len(official_rows), len(playable_rows)


def _betting_counts_and_flags(game_payload: dict[str, Any]) -> tuple[dict[str, int], dict[str, bool]]:
    markets = game_payload.get("markets") if isinstance(game_payload.get("markets"), dict) else {}
    totals_row = markets.get("totals") if isinstance(markets.get("totals"), dict) else None
    ml_row = markets.get("ml") if isinstance(markets.get("ml"), dict) else None
    pitcher_rows = markets.get("pitcherProps") if isinstance(markets.get("pitcherProps"), list) else []
    hitter_rows = markets.get("hitterProps") if isinstance(markets.get("hitterProps"), list) else []
    extra_pitcher_rows = markets.get("extraPitcherProps") if isinstance(markets.get("extraPitcherProps"), list) else []
    extra_hitter_rows = markets.get("extraHitterProps") if isinstance(markets.get("extraHitterProps"), list) else []

    official_count = int(bool(totals_row)) + int(bool(ml_row)) + len(pitcher_rows) + len(hitter_rows)
    playable_count = len(extra_pitcher_rows) + len(extra_hitter_rows)
    counts = {
        "official": int(official_count),
        "playable": int(playable_count),
        "pitcher": int(len(pitcher_rows)),
        "hitter": int(len(hitter_rows)),
        "extra_pitcher": int(len(extra_pitcher_rows)),
        "extra_hitter": int(len(extra_hitter_rows)),
    }
    flags = {
        "hasAnyRecommendations": bool(official_count or playable_count),
        "hasOfficialRecommendations": bool(official_count),
        "hasPlayableCandidates": bool(playable_count),
    }
    return counts, flags


def _apply_betting_counts_and_flags(game_payload: dict[str, Any]) -> dict[str, Any]:
    counts, flags = _betting_counts_and_flags(game_payload)
    enriched = dict(game_payload)
    enriched["counts"] = counts
    enriched["flags"] = flags
    return enriched


def _recommendations_by_game(locked_policy: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if not isinstance(locked_policy, dict):
        return {}

    grouped: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            "totals": None,
            "ml": None,
            "pitcher_props": [],
            "hitter_props": [],
            "extra_pitcher_props": [],
            "extra_hitter_props": [],
        }
    )
    markets = locked_policy.get("markets") or {}
    if not isinstance(markets, dict):
        return {}

    def _append_reco(bucket: dict[str, Any], market_name: str, reco: dict[str, Any], *, tier: str) -> None:
        item = dict(reco)
        item["recommendation_tier"] = tier
        if market_name == "totals":
            bucket["totals"] = item
        elif market_name == "ml":
            bucket["ml"] = item
        elif market_name == "pitcher_props":
            bucket["extra_pitcher_props" if tier == "candidate" else "pitcher_props"].append(item)
        else:
            bucket["extra_hitter_props" if tier == "candidate" else "hitter_props"].append(item)

    for market_name, section in markets.items():
        if not isinstance(section, dict):
            continue
        recos = section.get("recommendations") or []
        extra_recos = section.get("other_playable_candidates") or []
        if isinstance(recos, list):
            for reco in recos:
                if not isinstance(reco, dict):
                    continue
                game_pk = _safe_int(reco.get("game_pk"))
                if not game_pk or int(game_pk) <= 0:
                    continue
                _append_reco(grouped[int(game_pk)], str(market_name), reco, tier="official")
        if isinstance(extra_recos, list):
            for reco in extra_recos:
                if not isinstance(reco, dict):
                    continue
                game_pk = _safe_int(reco.get("game_pk"))
                if not game_pk or int(game_pk) <= 0:
                    continue
                _append_reco(grouped[int(game_pk)], str(market_name), reco, tier="candidate")

    for bucket in grouped.values():
        for key in ("pitcher_props", "hitter_props", "extra_pitcher_props", "extra_hitter_props"):
            bucket[key].sort(key=lambda reco: (_safe_int(reco.get("rank")) or 9999, -float(reco.get("edge") or 0.0)))
    return dict(grouped)


def _reco_bucket_from_betting_markets(markets: Any) -> dict[str, Any]:
    market_map = markets if isinstance(markets, dict) else {}
    return {
        "totals": dict(market_map.get("totals") or {}) if isinstance(market_map.get("totals"), dict) else None,
        "ml": dict(market_map.get("ml") or {}) if isinstance(market_map.get("ml"), dict) else None,
        "pitcher_props": [dict(row) for row in (market_map.get("pitcherProps") or []) if isinstance(row, dict)],
        "hitter_props": [dict(row) for row in (market_map.get("hitterProps") or []) if isinstance(row, dict)],
        "extra_pitcher_props": [dict(row) for row in (market_map.get("extraPitcherProps") or []) if isinstance(row, dict)],
        "extra_hitter_props": [dict(row) for row in (market_map.get("extraHitterProps") or []) if isinstance(row, dict)],
    }


def _supplement_recos_by_game_with_betting_games(
    recos_by_game: dict[int, dict[str, Any]],
    betting_games: Any,
) -> dict[int, dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {
        int(game_pk): {
            "totals": bucket.get("totals"),
            "ml": bucket.get("ml"),
            "pitcher_props": [dict(row) for row in (bucket.get("pitcher_props") or []) if isinstance(row, dict)],
            "hitter_props": [dict(row) for row in (bucket.get("hitter_props") or []) if isinstance(row, dict)],
            "extra_pitcher_props": [dict(row) for row in (bucket.get("extra_pitcher_props") or []) if isinstance(row, dict)],
            "extra_hitter_props": [dict(row) for row in (bucket.get("extra_hitter_props") or []) if isinstance(row, dict)],
        }
        for game_pk, bucket in (recos_by_game or {}).items()
        if _safe_int(game_pk) is not None and isinstance(bucket, dict)
    }
    if not isinstance(betting_games, dict):
        return merged

    for raw_game_pk, raw_game_betting in betting_games.items():
        game_pk = _safe_int(raw_game_pk)
        game_betting = raw_game_betting if isinstance(raw_game_betting, dict) else {}
        markets = game_betting.get("markets") if isinstance(game_betting.get("markets"), dict) else {}
        if not game_pk or int(game_pk) <= 0:
            continue
        supplemental = _reco_bucket_from_betting_markets(markets)
        existing = merged.get(int(game_pk))
        if not isinstance(existing, dict):
            merged[int(game_pk)] = supplemental
            continue
        for key in ("totals", "ml"):
            if existing.get(key) is None and supplemental.get(key) is not None:
                existing[key] = supplemental.get(key)
        for key in ("pitcher_props", "hitter_props", "extra_pitcher_props", "extra_hitter_props"):
            if not existing.get(key) and supplemental.get(key):
                existing[key] = supplemental.get(key)
    return merged


def _cards_recommendation_payload_by_game(selected_date: str) -> dict[int, dict[str, Any]]:
    betting_games = _betting_payload_by_game(selected_date)
    locked_policy = load_json_file(daily_artifact_path(selected_date, suffix="_locked_policy"))
    recos_by_game = _recommendations_by_game(locked_policy)
    merged_recos = _supplement_recos_by_game_with_betting_games(recos_by_game, betting_games)

    out: dict[int, dict[str, Any]] = {int(game_pk): dict(payload) for game_pk, payload in betting_games.items()}
    for game_pk, reco_bucket in merged_recos.items():
        existing = dict(out.get(int(game_pk)) or {})
        existing_markets = existing.get("markets") if isinstance(existing.get("markets"), dict) else {}
        merged_markets = {
            "totals": reco_bucket.get("totals") if reco_bucket.get("totals") is not None else existing_markets.get("totals"),
            "ml": reco_bucket.get("ml") if reco_bucket.get("ml") is not None else existing_markets.get("ml"),
            "pitcherProps": [dict(row) for row in (reco_bucket.get("pitcher_props") or existing_markets.get("pitcherProps") or []) if isinstance(row, dict)],
            "hitterProps": [dict(row) for row in (reco_bucket.get("hitter_props") or existing_markets.get("hitterProps") or []) if isinstance(row, dict)],
            "extraPitcherProps": [dict(row) for row in (reco_bucket.get("extra_pitcher_props") or existing_markets.get("extraPitcherProps") or []) if isinstance(row, dict)],
            "extraHitterProps": [dict(row) for row in (reco_bucket.get("extra_hitter_props") or existing_markets.get("extraHitterProps") or []) if isinstance(row, dict)],
        }
        existing["markets"] = merged_markets
        out[int(game_pk)] = _apply_betting_counts_and_flags(existing)
    return out


def _betting_payload_by_game(selected_date: str) -> dict[int, dict[str, Any]]:
    season = _season_for_date(selected_date)
    payload = load_json_file(season_betting_card_day_path(season, selected_date))
    games = payload.get("games") if isinstance((payload or {}).get("games"), dict) else {}
    out: dict[int, dict[str, Any]] = {}
    for game_key, game_payload in games.items():
        if not isinstance(game_payload, dict):
            continue
        try:
            current_pk = int(game_key)
        except Exception:
            try:
                current_pk = int(game_payload.get("game_pk") or 0)
            except Exception:
                current_pk = 0
        if current_pk:
            out[current_pk] = _apply_betting_counts_and_flags(game_payload)
    return out


def _daily_sim_by_game(selected_date: str, game_pks: list[int]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for game_pk in game_pks:
        sim_path = daily_sim_artifact_path(selected_date, int(game_pk))
        if sim_path is None:
            continue
        payload = load_json_file(sim_path)
        if isinstance(payload, dict):
            out[int(game_pk)] = payload
    return out


def _daily_actual_by_game(selected_date: str, game_pks: list[int]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    today_iso = date.today().isoformat()
    for game_pk in game_pks:
        feed_path = raw_feed_live_path(selected_date, int(game_pk))
        payload = load_json_or_gz_file(feed_path)
        if not isinstance(payload, dict) and selected_date == today_iso:
            payload = _fetch_current_feed_live(int(game_pk))
        if isinstance(payload, dict):
            out[int(game_pk)] = payload
    return out


def _fetch_current_feed_live(game_pk: int) -> dict[str, Any] | None:
    try:
        with urlopen(f"https://statsapi.mlb.com/api/v1.1/game/{int(game_pk)}/feed/live", timeout=8) as response:
            if int(getattr(response, "status", 200) or 200) >= 400:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, URLError):
        return None


def source_cards_api_payload(context: dict[str, Any]) -> dict[str, Any]:
    games = context.get("games") if isinstance(context.get("games"), list) else []
    hr_targets = context.get("hr_targets_shelf") if isinstance(context.get("hr_targets_shelf"), dict) else None
    hr_rows = hr_targets.get("rows") if hr_targets and isinstance(hr_targets.get("rows"), list) else []
    selected_date = str(context.get("date") or "").strip()
    lineups_path = daily_snapshot_lineups_path(selected_date) if selected_date else None
    game_lines_path = daily_snapshot_oddsapi_game_lines_path(selected_date) if selected_date else None
    pitcher_props_path = daily_snapshot_oddsapi_pitcher_props_path(selected_date) if selected_date else None
    hitter_props_path = daily_snapshot_oddsapi_hitter_props_path(selected_date) if selected_date else None
    ops_report_path = daily_ops_report_path(selected_date) if selected_date else None
    lineups_doc = load_json_file(lineups_path) if lineups_path else None
    game_lines_doc = load_json_file(game_lines_path) if game_lines_path else None
    pitcher_props_doc = load_json_file(pitcher_props_path) if pitcher_props_path else None
    hitter_props_doc = load_json_file(hitter_props_path) if hitter_props_path else None
    ops_report_doc = load_json_file(ops_report_path) if ops_report_path else None
    top_rows = []
    for row in hr_rows:
        if not isinstance(row, dict):
            continue
        top_rows.append(
            {
                "playerName": str(row.get("player_name") or "").strip(),
                "team": str(row.get("team") or "").strip(),
                "opponent": str(row.get("matchup") or "").strip(),
                "matchup": str(row.get("matchup") or "").strip(),
                "pHr1Plus": row.get("p_hr_1plus"),
                "probability": str(row.get("probability") or "").strip(),
                "supportLabel": str(row.get("support") or "").strip(),
                "supportScore": row.get("support_score"),
                "supportScoreDisplay": str(row.get("support") or "").strip(),
                "paMean": row.get("pa_mean"),
                "lineupOrder": row.get("lineup_order"),
                "opponentPitcherName": str(row.get("opponent_pitcher_name") or "").strip(),
                "writeup": str(row.get("writeup") or row.get("summary") or "").strip(),
                "summary": str(row.get("summary") or "").strip(),
                "detailHref": hr_targets.get("href") if hr_targets else None,
            }
        )

    moneyline_games = 0
    totals_games = 0
    spread_games = 0
    pitcher_rows = 0
    hitter_rows = 0
    pitcher_players: set[str] = set()
    hitter_players: set[str] = set()
    sim_counts: list[int] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        markets = game.get("markets") if isinstance(game.get("markets"), dict) else {}
        if isinstance(markets.get("ml"), dict) and markets.get("ml"):
            moneyline_games += 1
        if isinstance(markets.get("totals"), dict) and markets.get("totals"):
            totals_games += 1
        if isinstance(markets.get("spreads"), dict) and markets.get("spreads"):
            spread_games += 1
        for key in ("pitcherProps", "extraPitcherProps"):
            for row in (markets.get(key) if isinstance(markets.get(key), list) else []):
                if not isinstance(row, dict):
                    continue
                pitcher_rows += 1
                name = str(row.get("pitcher_name") or row.get("player_name") or "").strip()
                if name:
                    pitcher_players.add(name)
        for key in ("hitterProps", "extraHitterProps"):
            for row in (markets.get(key) if isinstance(markets.get(key), list) else []):
                if not isinstance(row, dict):
                    continue
                hitter_rows += 1
                name = str(row.get("player_name") or row.get("pitcher_name") or "").strip()
                if name:
                    hitter_players.add(name)

        panels = game.get("panels") if isinstance(game.get("panels"), list) else []
        sim_panel = panels[4] if len(panels) > 4 and isinstance(panels[4], dict) else None
        sim_title = str((sim_panel or {}).get("title") or "").strip()
        match = re.search(r"(\d+)\s+sims", sim_title, flags=re.IGNORECASE)
        if match:
            try:
                sim_counts.append(int(match.group(1)))
            except Exception:
                pass

    sims_per_game = sim_counts[0] if sim_counts and len(set(sim_counts)) == 1 else 0
    market_warnings: list[str] = []
    if games and not (moneyline_games or totals_games or spread_games):
        market_warnings.append("game lines are unavailable for this slate")
    if games and pitcher_rows <= 0:
        market_warnings.append("pitcher props are unavailable for this slate")
    if games and hitter_rows <= 0:
        market_warnings.append("hitter props are unavailable for this slate")
    lineup_health = _lineup_health_summary(lineups_path, lineups_doc)
    workflow = _workflow_summary(ops_report_path, ops_report_doc)

    game_lines_summary = _snapshot_market_summary(
        game_lines_path,
        game_lines_doc,
        root_key="games",
        fallback_counts={
            "h2h_games": moneyline_games,
            "totals_games": totals_games,
            "spreads_games": spread_games,
        },
    )
    pitcher_props_summary = _snapshot_market_summary(
        pitcher_props_path,
        pitcher_props_doc,
        root_key="pitcher_props",
        fallback_counts={
            "players": len(pitcher_players),
            "rows": pitcher_rows,
        },
    )
    hitter_props_summary = _snapshot_market_summary(
        hitter_props_path,
        hitter_props_doc,
        root_key="hitter_props",
        fallback_counts={
            "players": len(hitter_players),
            "rows": hitter_rows,
        },
    )

    # Only keep local fallback warnings when the corresponding snapshot lane is actually unavailable.
    filtered_market_warnings: list[str] = []
    for warning in market_warnings:
        normalized = str(warning or "").strip().lower()
        if "game lines" in normalized and bool(game_lines_summary.get("available")):
            continue
        if "pitcher props" in normalized and bool(pitcher_props_summary.get("available")):
            continue
        if "hitter props" in normalized and bool(hitter_props_summary.get("available")):
            continue
        filtered_market_warnings.append(warning)

    combined_market_warnings = list(filtered_market_warnings)
    for summary in (game_lines_summary, pitcher_props_summary, hitter_props_summary):
        for warning in summary.get("warnings") or []:
            if warning not in combined_market_warnings:
                combined_market_warnings.append(warning)

    return {
        "date": context.get("date"),
        "cards": games,
        "games": games,
        "scoreboard": context.get("scoreboard_items", []),
        "board_contract": context.get("board_contract", {}),
        "source_path": context.get("source_path"),
        "sourcePath": context.get("source_path"),
        "using_sample_data": context.get("using_sample_data", False),
        "usingSampleData": context.get("using_sample_data", False),
        "hasSampleData": not bool(context.get("using_sample_data", False)),
        "hasArtifactData": not bool(context.get("using_sample_data", False)),
        "nav": {
            "prevDate": context.get("prev_date"),
            "nextDate": context.get("next_date"),
        },
        "marketAvailability": {
            "gameLines": game_lines_summary,
            "pitcherProps": pitcher_props_summary,
            "hitterProps": hitter_props_summary,
            "warnings": combined_market_warnings,
        },
        "lineupHealth": lineup_health,
        "workflow": workflow,
        "hrTargets": {
            "found": bool(hr_targets and top_rows),
            "pageHref": hr_targets.get("href") if hr_targets else f"/mlb/hr-targets?date={context.get('date')}",
            "sourcePath": hr_targets.get("source_path") if hr_targets else None,
            "rows": int(hr_targets.get("row_count") or len(hr_rows)) if hr_targets else 0,
            "games": int(hr_targets.get("game_count") or len(games)) if hr_targets else len(games),
            "topRows": top_rows,
        },
    }


def _live_lens_game_row(selected_date: str, game_pk: int) -> dict[str, Any] | None:
    report = load_json_file(live_lens_report_path(selected_date))
    rows = report.get("games") if isinstance((report or {}).get("games"), list) else []
    for row in rows:
        if isinstance(row, dict) and int(row.get("gamePk") or 0) == int(game_pk):
            return row
    return None


def _live_prop_kind(market_label: str) -> tuple[str, str]:
    label = str(market_label or "").strip().lower()
    compact = label.replace("-", " ").replace("_", " ")
    if "strikeout" in compact:
        return "pitcher_props", "strikeouts"
    if "earned run" in compact:
        return "pitcher_props", "earned_runs"
    if "hits allowed" in compact or "hit allowed" in compact:
        return "pitcher_props", "hits_allowed"
    if "walk" in compact and "allowed" in compact:
        return "pitcher_props", "walks_allowed"
    if "out" in compact:
        return "pitcher_props", "outs"
    if "home run" in compact:
        return "hitter_props", "home_runs"
    if "total base" in compact:
        return "hitter_props", "total_bases"
    if compact == "hits" or " hit" in compact:
        return "hitter_props", "hits"
    if "rbi" in compact:
        return "hitter_props", "rbis"
    if "run" in compact:
        return "hitter_props", "runs_scored"
    return "hitter_props", compact.replace(" ", "_") or "prop"


_LIVE_HITTER_MARKET_KEYS: dict[str, tuple[str, str]] = {
    "hits": ("batter_hits", "Hits"),
    "runs_scored": ("batter_runs_scored", "Runs"),
    "rbis": ("batter_rbis", "RBIs"),
    "total_bases": ("batter_total_bases", "Total Bases"),
    "home_runs": ("batter_home_runs", "Home Runs"),
}


def _normalize_live_name(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _market_name_variants(name: Any) -> list[str]:
    base = _normalize_live_name(name)
    if not base:
        return []
    variants = [base]
    tokens = base.split()
    if len(tokens) >= 2:
        first = tokens[0]
        alias_map = {
            "chris": "christopher",
            "christopher": "chris",
            "jeff": "jeffrey",
            "jeffrey": "jeff",
            "matt": "matthew",
            "matthew": "matt",
            "mike": "michael",
            "michael": "mike",
            "nick": "nicholas",
            "nicholas": "nick",
        }
        alias = alias_map.get(first)
        if alias:
            variants.append(" ".join([alias] + tokens[1:]))
    seen: set[str] = set()
    return [variant for variant in variants if not (variant in seen or seen.add(variant))]


def _market_lines_for_live_name(all_lines: dict[str, dict[str, Any]], name: Any) -> dict[str, Any]:
    if not isinstance(all_lines, dict):
        return {}
    for variant in _market_name_variants(name):
        candidate = all_lines.get(variant)
        if isinstance(candidate, dict) and candidate:
            return candidate
    return {}


def _extract_hitter_market_lines(doc: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    raw = (doc or {}).get("hitter_props") if isinstance(doc, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for raw_name, markets in raw.items():
        normalized = _normalize_live_name(raw_name)
        if not normalized or not isinstance(markets, dict):
            continue
        player_lines: dict[str, Any] = {}
        for market_key, market in markets.items():
            if not isinstance(market, dict):
                continue
            line_value = _safe_float(market.get("line"))
            if line_value is None:
                continue
            player_lines[str(market_key)] = {
                "line": float(line_value),
                "over_odds": market.get("over_odds"),
                "under_odds": market.get("under_odds"),
            }
        if player_lines:
            out[normalized] = player_lines
    return out


def _merge_hitter_market_lines(primary: dict[str, dict[str, Any]], fallback: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in (fallback, primary):
        if not isinstance(source, dict):
            continue
        for player_name, markets in source.items():
            if not isinstance(markets, dict):
                continue
            target = merged.setdefault(str(player_name), {})
            for market_key, market in markets.items():
                if not isinstance(market, dict):
                    continue
                current = target.setdefault(str(market_key), {})
                if not isinstance(current, dict):
                    current = {}
                    target[str(market_key)] = current
                for field in ("line", "over_odds", "under_odds"):
                    if current.get(field) in {None, ""} and market.get(field) not in {None, ""}:
                        current[field] = market.get(field)
                    elif field == "line" and field not in current and market.get(field) is not None:
                        current[field] = market.get(field)
    return merged


def _hitter_snapshot_market_lines(selected_date: str) -> dict[str, dict[str, Any]]:
    current_lines = _extract_hitter_market_lines(load_json_file(daily_snapshot_oddsapi_hitter_props_path(selected_date)))
    archived_path = market_refresh_history_oddsapi_path(selected_date, "oddsapi_hitter_props")
    archived_lines = _extract_hitter_market_lines(load_json_file(archived_path)) if archived_path else {}
    return _merge_hitter_market_lines(current_lines, archived_lines)


def _extract_pitcher_market_lines(doc: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    rows = doc.get("pitcher_props") if isinstance((doc or {}).get("pitcher_props"), dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for name, markets in rows.items():
        normalized = _normalize_live_name(name)
        if not normalized or not isinstance(markets, dict):
            continue
        parsed: dict[str, Any] = {}
        for market_key, market in markets.items():
            if not isinstance(market, dict):
                continue
            line_value = _safe_float(market.get("line"))
            if line_value is None:
                continue
            alternates: list[dict[str, Any]] = []
            for alt in (market.get("alternates") or []):
                if not isinstance(alt, dict):
                    continue
                alt_line = _safe_float(alt.get("line"))
                if alt_line is None:
                    continue
                alternates.append(
                    {
                        "line": float(alt_line),
                        "over_odds": alt.get("over_odds"),
                        "under_odds": alt.get("under_odds"),
                    }
                )
            parsed[str(market_key).strip().lower()] = {
                "line": float(line_value),
                "over_odds": market.get("over_odds"),
                "under_odds": market.get("under_odds"),
                "alternates": alternates,
            }
        if parsed:
            out[normalized] = parsed
    return out


def _pitcher_snapshot_market_lines(selected_date: str) -> dict[str, dict[str, Any]]:
    return _extract_pitcher_market_lines(load_json_file(daily_snapshot_oddsapi_pitcher_props_path(selected_date)))


def _live_pitcher_ladder_market_candidates(market: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(market, dict):
        return []
    candidates: list[dict[str, Any]] = []
    line_value = _safe_float(market.get("line"))
    if line_value is not None:
        candidates.append(
            {
                "line": float(line_value),
                "over_odds": market.get("over_odds"),
                "under_odds": market.get("under_odds"),
            }
        )
    for alt in (market.get("alternates") or []):
        if not isinstance(alt, dict):
            continue
        alt_line = _safe_float(alt.get("line"))
        if alt_line is None:
            continue
        candidates.append(
            {
                "line": float(alt_line),
                "over_odds": alt.get("over_odds"),
                "under_odds": alt.get("under_odds"),
            }
        )
    deduped: dict[float, dict[str, Any]] = {}
    for item in candidates:
        item_line = _safe_float(item.get("line"))
        if item_line is None:
            continue
        deduped[float(item_line)] = dict(item)
    return [deduped[key] for key in sorted(deduped.keys())]


def _dist_prob_over_line(dist: Any, line: float) -> float | None:
    if not isinstance(dist, dict) or not dist:
        return None
    total_weight = 0.0
    over_weight = 0.0
    for key, value in dist.items():
        try:
            outcome = float(key)
            weight = float(value)
        except Exception:
            continue
        if weight <= 0.0:
            continue
        total_weight += weight
        if outcome > float(line):
            over_weight += weight
    if total_weight <= 0.0:
        return None
    return over_weight / total_weight


def _american_implied_prob(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        odds = int(text)
    except Exception:
        return None
    if odds == 0:
        return None
    if odds > 0:
        return 100.0 / (float(odds) + 100.0)
    return float(-odds) / (float(-odds) + 100.0)


def _normalized_two_way_probs(first_prob: float | None, second_prob: float | None) -> tuple[float | None, float | None]:
    if first_prob is None or second_prob is None:
        return None, None
    denom = float(first_prob) + float(second_prob)
    if denom <= 0.0:
        return None, None
    return float(first_prob) / denom, float(second_prob) / denom


def _prop_price_allowed(odds: Any, *, max_favorite_odds: int = -200) -> bool:
    odds_value = _safe_int(odds)
    if odds_value is None:
        return True
    if odds_value >= 0:
        return True
    return odds_value >= int(max_favorite_odds)


def _selection_live_edge(selection: str, live_projection: float | None, line_value: float | None) -> float | None:
    if live_projection is None or line_value is None:
        return None
    if selection == "under":
        return round(float(line_value) - float(live_projection), 3)
    if selection == "over":
        return round(float(live_projection) - float(line_value), 3)
    return None


def _live_hitter_prop_row_actionable(row: dict[str, Any]) -> bool:
    pa_mean = _safe_float(row.get("pa_mean"))
    model_mean = _safe_float(row.get("model_mean"))
    live_projection = _safe_float(row.get("live_projection"))
    actual_value = _safe_float(row.get("actual_value"))
    if pa_mean is not None and float(pa_mean) <= 0.0:
        return False
    if model_mean is not None and float(model_mean) <= 0.0:
        return False
    if live_projection is not None and float(live_projection) <= 0.0 and (actual_value is None or float(actual_value) <= 0.0):
        return False
    return True


def _select_bounded_live_side(
    *,
    model_prob_over: float | None,
    line_value: float,
    over_odds: Any,
    under_odds: Any,
    live_projection: float | None,
    min_edge: float = 0.05,
    max_favorite_odds: int = -200,
) -> dict[str, Any] | None:
    if model_prob_over is None:
        return None
    model_prob_under = max(0.0, min(1.0, 1.0 - float(model_prob_over)))
    raw_over_prob = _american_implied_prob(over_odds)
    raw_under_prob = _american_implied_prob(under_odds)
    market_prob_over, market_prob_under = _normalized_two_way_probs(raw_over_prob, raw_under_prob)
    if market_prob_over is None and market_prob_under is None:
        return None
    if market_prob_over is None:
        market_prob_over = max(0.0, min(1.0, 1.0 - float(market_prob_under or 0.0)))
    if market_prob_under is None:
        market_prob_under = max(0.0, min(1.0, 1.0 - float(market_prob_over or 0.0)))
    over_edge = float(model_prob_over) - float(market_prob_over or 0.0)
    under_edge = float(model_prob_under) - float(market_prob_under or 0.0)
    candidates: list[dict[str, Any]] = []
    for selection, odds, market_prob, market_edge in (
        ("over", over_odds, market_prob_over, over_edge),
        ("under", under_odds, market_prob_under, under_edge),
    ):
        if not _prop_price_allowed(odds, max_favorite_odds=max_favorite_odds):
            continue
        live_edge = _selection_live_edge(selection, live_projection, line_value)
        if live_edge is None or float(live_edge) <= 0.0:
            continue
        projection_gap = abs(float(live_edge))
        min_live_edge = 0.08 if selection == "over" else 0.18
        if projection_gap < float(min_live_edge):
            continue
        if float(market_edge) <= float(min_edge):
            continue
        candidates.append(
            {
                "selection": selection,
                "odds": odds,
                "marketProbOver": market_prob_over,
                "marketProbUnder": market_prob_under,
                "marketProbMode": "vig_normalized",
                "selectedSideMarketProb": market_prob,
                "marketEdge": market_edge,
                "liveEdge": live_edge,
                "projectionGap": projection_gap,
            }
        )
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            float(item.get("marketEdge") or 0.0),
            float(item.get("liveEdge") or 0.0),
            float(item.get("projectionGap") or 0.0),
            1 if item.get("selection") == "over" else 0,
        ),
        reverse=True,
    )
    return candidates[0]


def _live_progress_fraction(actual_payload: dict[str, Any] | None) -> float:
    linescore = ((actual_payload or {}).get("liveData") or {}).get("linescore") if isinstance((actual_payload or {}).get("liveData"), dict) else {}
    if not isinstance(linescore, dict):
        return 0.0
    inning = _safe_int(linescore.get("currentInning")) or 1
    outs = _safe_int(linescore.get("outs")) or 0
    half = str(linescore.get("inningHalf") or "top").strip().lower()
    completed_outs = max(0, (inning - 1) * 6)
    if half == "bottom":
        completed_outs += 3
    completed_outs += max(0, min(3, outs))
    return max(0.0, min(1.0, float(completed_outs) / 54.0))


def _actual_payload_is_live(actual_payload: dict[str, Any] | None) -> bool:
    status = ((actual_payload or {}).get("gameData") or {}).get("status") if isinstance((actual_payload or {}).get("gameData"), dict) else {}
    abstract = str((status or {}).get("abstractGameState") or "").strip().lower()
    detailed = str((status or {}).get("detailedState") or "").strip().lower()
    return abstract == "live" or detailed == "in progress"


def _parse_ip_to_outs(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        whole_text, _, frac_text = text.partition(".")
        whole = int(whole_text or "0")
        frac = int(frac_text or "0")
    except Exception:
        return None
    return (whole * 3) + frac


def _actual_pitching_context_by_name(actual_payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(actual_payload, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for side in ("away", "home"):
        for player_obj in _iter_team_players(actual_payload, side):
            person = player_obj.get("person") if isinstance(player_obj, dict) else {}
            pitching = ((player_obj.get("stats") or {}).get("pitching")) if isinstance(player_obj, dict) else None
            name = _normalize_live_name((person or {}).get("fullName"))
            if name and isinstance(pitching, dict) and pitching:
                out[name] = {
                    "stats": pitching,
                    "team_side": side,
                }
    return out


def _actual_pitcher_stat_value(actual_row: dict[str, Any] | None, prop_key: str) -> float | None:
    if not isinstance(actual_row, dict):
        return None
    key = str(prop_key or "").strip().lower()
    if key == "strikeouts":
        return _safe_float(actual_row.get("strikeOuts"))
    if key == "hits_allowed":
        return _safe_float(actual_row.get("hits"))
    if key == "earned_runs":
        return _safe_float(actual_row.get("earnedRuns"))
    if key == "walks_allowed":
        return _safe_float(actual_row.get("baseOnBalls"))
    if key == "outs":
        outs = _safe_float(actual_row.get("outs"))
        if outs is not None:
            return outs
        return _safe_float(_parse_ip_to_outs(actual_row.get("inningsPitched")))
    return None


def _pitching_stats_has_appearance(pitching_stats: dict[str, Any] | None) -> bool:
    if not isinstance(pitching_stats, dict):
        return False
    for key in ("outs", "battersFaced", "pitchesThrown", "strikeOuts", "earnedRuns", "runs", "hits", "baseOnBalls"):
        value = _safe_float(pitching_stats.get(key))
        if value is not None and float(value) > 0.0:
            return True
    outs_from_ip = _parse_ip_to_outs(pitching_stats.get("inningsPitched"))
    return outs_from_ip is not None and int(outs_from_ip) > 0


def _current_pitching_side(actual_payload: dict[str, Any] | None) -> str | None:
    batting_side = _current_batting_side(actual_payload)
    if batting_side == "away":
        return "home"
    if batting_side == "home":
        return "away"
    return None


def _starter_removed_from_actual_payload(
    actual_payload: dict[str, Any] | None,
    *,
    side: str,
    starter_id: int | None,
    starter_name: str,
) -> bool:
    if side not in {"away", "home"} or not isinstance(actual_payload, dict):
        return False
    normalized_starter = _normalize_live_name(starter_name)
    if starter_id is None and not normalized_starter:
        return False

    if _current_pitching_side(actual_payload) == side:
        current_play = ((actual_payload.get("liveData") or {}).get("plays") or {}).get("currentPlay")
        matchup = (current_play or {}).get("matchup") if isinstance(current_play, dict) else {}
        current_pitcher = (matchup or {}).get("pitcher") if isinstance(matchup, dict) else {}
        current_pitcher_id = _safe_int((current_pitcher or {}).get("id")) if isinstance(current_pitcher, dict) else None
        current_pitcher_name = _normalize_live_name((current_pitcher or {}).get("fullName")) if isinstance(current_pitcher, dict) else ""
        if starter_id is not None and current_pitcher_id is not None and int(current_pitcher_id) != int(starter_id):
            return True
        if normalized_starter and current_pitcher_name and current_pitcher_name != normalized_starter:
            return True

    for player_obj in _iter_team_players(actual_payload, side):
        person = player_obj.get("person") if isinstance(player_obj, dict) else {}
        row_id = _safe_int((person or {}).get("id")) if isinstance(person, dict) else None
        row_name = _normalize_live_name((person or {}).get("fullName")) if isinstance(person, dict) else ""
        is_starter_row = False
        if starter_id is not None and row_id is not None:
            is_starter_row = int(row_id) == int(starter_id)
        elif normalized_starter and row_name:
            is_starter_row = row_name == normalized_starter
        if is_starter_row:
            continue
        pitching_stats = ((player_obj.get("stats") or {}).get("pitching")) if isinstance(player_obj, dict) else None
        if _pitching_stats_has_appearance(pitching_stats if isinstance(pitching_stats, dict) else None):
            return True
    return False


def _bounded_live_pitcher_projection(actual_value: float | None, model_mean: float | None, progress_fraction: float) -> float | None:
    mean = _safe_float(model_mean)
    actual = _safe_float(actual_value)
    if mean is None:
        return actual
    if actual is None:
        return mean
    remaining_fraction = max(0.0, min(1.0, 1.0 - float(progress_fraction)))
    return round(float(actual) + max(float(mean) - float(actual), 0.0) * remaining_fraction, 3)


def _current_live_pitcher_prop_rows(selected_date: str, sim_payload: dict[str, Any] | None, actual_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(sim_payload, dict) or not isinstance(actual_payload, dict):
        return []
    sim_section = sim_payload.get("sim") if isinstance(sim_payload.get("sim"), dict) else {}
    pitcher_models = sim_section.get("pitcher_props") if isinstance(sim_section.get("pitcher_props"), dict) else {}
    market_lines = _pitcher_snapshot_market_lines(selected_date)
    probable_pitchers = ((actual_payload.get("gameData") or {}).get("probablePitchers")) if isinstance((actual_payload.get("gameData") or {}).get("probablePitchers"), dict) else {}
    if not pitcher_models or not market_lines or not probable_pitchers:
        return []
    actual_pitchers = _actual_pitching_context_by_name(actual_payload)
    progress_fraction = _live_progress_fraction(actual_payload)
    current_batting_side = _current_batting_side(actual_payload)
    current_pitcher_side = "away" if current_batting_side == "home" else "home" if current_batting_side == "away" else None
    config = {
        "strikeouts": {"label": "Strikeouts", "dist_key": "so_dist", "mean_key": "so_mean"},
        "outs": {"label": "Outs Recorded", "dist_key": "outs_dist", "mean_key": "outs_mean"},
        "hits_allowed": {"label": "Hits Allowed", "dist_key": "hits_dist", "mean_key": "hits_mean"},
        "earned_runs": {"label": "Earned Runs", "dist_key": "earned_runs_dist", "mean_key": "er_mean"},
        "walks_allowed": {"label": "Walks Allowed", "dist_key": "walks_dist", "mean_key": "walks_mean"},
    }
    out: list[dict[str, Any]] = []
    for side in ("away", "home"):
        probable = probable_pitchers.get(side) if isinstance(probable_pitchers, dict) else None
        pitcher_id = _safe_int((probable or {}).get("id")) if isinstance(probable, dict) else None
        pitcher_name = str((probable or {}).get("fullName") or "").strip() if isinstance(probable, dict) else ""
        if pitcher_id is None or not pitcher_name:
            continue
        model_row = pitcher_models.get(str(pitcher_id)) if isinstance(pitcher_models, dict) else None
        market_entry = _market_lines_for_live_name(market_lines, pitcher_name)
        actual_context = actual_pitchers.get(_normalize_live_name(pitcher_name)) if isinstance(actual_pitchers, dict) else None
        actual_row = (actual_context or {}).get("stats") if isinstance(actual_context, dict) else None
        if not isinstance(model_row, dict) or not isinstance(market_entry, dict):
            continue
        side_rows: list[dict[str, Any]] = []
        for prop_key, cfg in config.items():
            market = market_entry.get(prop_key)
            if not isinstance(market, dict):
                continue
            line_value = _safe_float(market.get("line"))
            if line_value is None:
                continue
            actual_value = _actual_pitcher_stat_value(actual_row, prop_key)
            if actual_value is not None and float(actual_value) > float(line_value):
                continue
            model_mean = _safe_float(model_row.get(cfg["mean_key"]))
            model_prob_over = _dist_prob_over_line(model_row.get(cfg["dist_key"]), float(line_value))
            live_projection = _bounded_live_pitcher_projection(actual_value, model_mean, progress_fraction)
            side_pick = _select_bounded_live_side(
                model_prob_over=model_prob_over,
                line_value=float(line_value),
                over_odds=market.get("over_odds"),
                under_odds=market.get("under_odds"),
                live_projection=live_projection,
                min_edge=0.03,
            )
            if side_pick is None:
                continue
            side_rows.append(
                {
                    "market": "pitcher_props",
                    "prop": prop_key,
                    "market_label": cfg["label"],
                    "game_pk": _safe_int(sim_payload.get("game_pk")) or _safe_int((actual_payload.get("gameData") or {}).get("game", {}).get("pk")),
                    "pitcher_name": pitcher_name,
                    "team_side": side,
                    "selection": side_pick.get("selection"),
                    "market_line": float(line_value),
                    "actual": actual_value,
                    "actual_so_far": actual_value,
                    "actual_value": actual_value,
                    "model_mean": model_mean,
                    "live_projection": live_projection,
                    "live_edge": side_pick.get("liveEdge"),
                    "edge": side_pick.get("marketEdge"),
                    "odds": side_pick.get("odds"),
                    "over_odds": market.get("over_odds"),
                    "under_odds": market.get("under_odds"),
                    "market_prob_over": side_pick.get("marketProbOver"),
                    "market_prob_under": side_pick.get("marketProbUnder"),
                    "market_prob_mode": side_pick.get("marketProbMode"),
                    "selected_side_market_prob": side_pick.get("selectedSideMarketProb"),
                    "projection_gap": side_pick.get("projectionGap"),
                    "recommendation_tier": "live",
                    "source": "current_market",
                }
            )
        side_rows.sort(
            key=lambda row: (
                float(row.get("edge") or 0.0),
                float(row.get("live_edge") or 0.0),
                float(row.get("projection_gap") or 0.0),
            ),
            reverse=True,
        )
        keep_count = 2 if current_pitcher_side == side else 1
        out.extend(side_rows[:keep_count])
    return out


def _lineup_slot_from_batting_order(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) >= 3:
            return max(1, min(9, int(text[:-2] or text[0])))
        return max(1, min(9, int(text)))
    except Exception:
        return None


def _current_batting_side(actual_payload: dict[str, Any] | None) -> str | None:
    linescore = ((actual_payload or {}).get("liveData") or {}).get("linescore") if isinstance((actual_payload or {}).get("liveData"), dict) else {}
    half = str((linescore or {}).get("inningHalf") or "").strip().lower()
    if half == "top":
        return "away"
    if half == "bottom":
        return "home"
    return None


def _actual_batting_context_by_name(actual_payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(actual_payload, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for side in ("away", "home"):
        for player_obj in _iter_team_players(actual_payload, side):
            person = player_obj.get("person") if isinstance(player_obj, dict) else {}
            batting = ((player_obj.get("stats") or {}).get("batting")) if isinstance(player_obj, dict) else None
            name = _normalize_live_name((person or {}).get("fullName"))
            if name and isinstance(batting, dict) and batting:
                out[name] = {
                    "stats": batting,
                    "team_side": side,
                    "batting_order": player_obj.get("battingOrder"),
                    "lineup_slot": _lineup_slot_from_batting_order(player_obj.get("battingOrder")),
                }
    return out


def _live_hitter_actual_pa(actual_row: dict[str, Any] | None) -> float | None:
    if not isinstance(actual_row, dict):
        return None
    components = [
        _safe_float(actual_row.get("atBats")),
        _safe_float(actual_row.get("baseOnBalls")),
        _safe_float(actual_row.get("hitByPitch")),
        _safe_float(actual_row.get("sacFlies")),
        _safe_float(actual_row.get("sacBunts")),
    ]
    values = [value for value in components if value is not None]
    if not values:
        return None
    return float(sum(values))


def _current_batter_slot(actual_payload: dict[str, Any] | None, team_side: str, batting_context: dict[str, dict[str, Any]]) -> int | None:
    current_side = _current_batting_side(actual_payload)
    if current_side != team_side:
        return None
    current_play = ((actual_payload or {}).get("liveData") or {}).get("plays") if isinstance((actual_payload or {}).get("liveData"), dict) else {}
    batter = ((current_play or {}).get("currentPlay") or {}).get("matchup") if isinstance((current_play or {}).get("currentPlay"), dict) else {}
    batter_name = _normalize_live_name((((batter or {}).get("batter") or {}).get("fullName")))
    if not batter_name:
        return None
    context = batting_context.get(batter_name) if isinstance(batting_context, dict) else None
    return _safe_int((context or {}).get("lineup_slot")) if isinstance(context, dict) else None


def _actual_hitter_stat_value(actual_row: dict[str, Any] | None, prop_key: str) -> float | None:
    if not isinstance(actual_row, dict):
        return None
    stat_map = {
        "hits": "hits",
        "runs_scored": "runs",
        "rbis": "rbi",
        "total_bases": "totalBases",
        "home_runs": "homeRuns",
    }
    stat_key = stat_map.get(str(prop_key))
    return float(_safe_int(actual_row.get(stat_key))) if stat_key and _safe_int(actual_row.get(stat_key)) is not None else None


def _bounded_live_projection(actual_value: float | None, model_mean: float | None, progress_fraction: float) -> float | None:
    if model_mean is None:
        return actual_value
    if actual_value is None:
        return model_mean
    return round(max(float(actual_value), float(model_mean)), 3)


def _bounded_live_hitter_projection(
    *,
    prop_key: str,
    player_name: str,
    team_side: str,
    actual_value: float | None,
    model_mean: float | None,
    model_row: dict[str, Any],
    actual_context: dict[str, Any] | None,
    actual_payload: dict[str, Any] | None,
    batting_context: dict[str, dict[str, Any]],
) -> float | None:
    mean = _safe_float(model_mean)
    if mean is None:
        return None
    actual_stats = (actual_context or {}).get("stats") if isinstance(actual_context, dict) else None
    actual = float(_safe_float(actual_value) or 0.0)
    use_ab_opportunity = prop_key in {"hits", "home_runs", "total_bases"}
    pa_mean = _safe_float(model_row.get("pa_mean"))
    ab_mean = _safe_float(model_row.get("ab_mean"))
    opportunity_mean = ab_mean if use_ab_opportunity else pa_mean
    actual_ab = _safe_float((actual_stats or {}).get("atBats")) if isinstance(actual_stats, dict) else None
    actual_pa = _live_hitter_actual_pa(actual_stats if isinstance(actual_stats, dict) else None)
    actual_opportunity = actual_ab if use_ab_opportunity else actual_pa
    if opportunity_mean is None or float(opportunity_mean) <= 0.0:
        return _bounded_live_projection(actual_value, model_mean, 0.0)
    remaining_opportunity = max(float(opportunity_mean) - float(actual_opportunity or 0.0), 0.0)
    lineup_slot = _safe_int((actual_context or {}).get("lineup_slot")) if isinstance(actual_context, dict) else _safe_int(model_row.get("lineup_order"))
    current_slot = _current_batter_slot(actual_payload, team_side, batting_context)
    if _current_batting_side(actual_payload) == team_side:
        if current_slot is not None and lineup_slot is not None:
            steps_until = (int(lineup_slot) - int(current_slot)) % 9
            if steps_until == 0:
                remaining_opportunity = max(remaining_opportunity, 0.6 if use_ab_opportunity else 0.8)
            elif steps_until == 1:
                remaining_opportunity += 0.2
            elif steps_until == 2:
                remaining_opportunity += 0.1

    linescore = ((actual_payload or {}).get("liveData") or {}).get("linescore") if isinstance((actual_payload or {}).get("liveData"), dict) else {}
    inning = _safe_int((linescore or {}).get("currentInning")) or 0
    away_score = _safe_float((((linescore or {}).get("teams") or {}).get("away") or {}).get("runs"))
    home_score = _safe_float((((linescore or {}).get("teams") or {}).get("home") or {}).get("runs"))
    current_side = _current_batting_side(actual_payload)
    if inning >= 9 and away_score is not None and home_score is not None:
        if team_side == "home" and current_side == "top" and float(home_score) > float(away_score):
            remaining_opportunity = 0.0
        if team_side == "away" and current_side == "bottom" and abs(float(home_score) - float(away_score)) > 1e-9:
            remaining_opportunity = 0.0

    rate = float(mean) / max(float(opportunity_mean), 1e-6)
    projection = float(actual) + max(0.0, float(remaining_opportunity)) * float(rate)
    return round(max(float(actual), projection), 3)


def _live_prop_signature(row: dict[str, Any]) -> tuple[str, str, str, str]:
    line_value = row.get("market_line") if row.get("market_line") is not None else row.get("line")
    return (
        _normalize_live_name(row.get("player_name") or row.get("pitcher_name")),
        _normalize_live_name(row.get("market_label") or row.get("market")),
        str(row.get("selection") or "").strip().lower(),
        "" if line_value is None else str(float(line_value)),
    )


def _registry_market_label(market: str, prop: str) -> str:
    market_key = str(market or "").strip().lower()
    prop_key = str(prop or "").strip().lower()
    if market_key == "pitcher_props":
        mapping = {
            "strikeouts": "Strikeouts",
            "outs": "Outs Recorded",
            "hits_allowed": "Hits Allowed",
            "walks_allowed": "Walks Allowed",
            "earned_runs": "Earned Runs",
        }
        return mapping.get(prop_key, prop_key.replace("_", " ").title())
    mapping = {
        "hits": "Hits",
        "runs": "Runs",
        "runs_scored": "Runs",
        "rbi": "RBIs",
        "rbis": "RBIs",
        "total_bases": "Total Bases",
        "home_runs": "Home Runs",
    }
    return mapping.get(prop_key, prop_key.replace("_", " ").title())


def _registry_live_prop_rows(selected_date: str, game_pk: int, existing_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    registry = load_json_file(live_prop_registry_path(selected_date))
    entries = registry.get("entries") if isinstance((registry or {}).get("entries"), dict) else {}
    if not entries:
        return []
    existing_signatures = {_live_prop_signature(row) for row in existing_rows if isinstance(row, dict)}
    out: list[dict[str, Any]] = []
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        if int(entry.get("gamePk") or 0) != int(game_pk):
            continue
        market = str(entry.get("market") or "").strip().lower()
        prop = str(entry.get("prop") or "").strip().lower()
        selection = str(entry.get("selection") or "").strip().lower()
        market_line = _safe_float(entry.get("marketLine"))
        if not market or not prop or not selection or market_line is None:
            continue
        first_snapshot = entry.get("firstSeenSnapshot") if isinstance(entry.get("firstSeenSnapshot"), dict) else {}
        last_snapshot = entry.get("lastSeenSnapshot") if isinstance(entry.get("lastSeenSnapshot"), dict) else {}
        snapshot = first_snapshot if first_snapshot else last_snapshot
        player_name = str(entry.get("owner") or "").strip()
        if not player_name:
            continue
        item = {
            "market": market,
            "prop": prop,
            "market_label": _registry_market_label(market, prop),
            "game_pk": int(game_pk),
            "selection": selection,
            "market_line": float(market_line),
            "actual": _safe_float(snapshot.get("actual")),
            "actual_so_far": _safe_float(snapshot.get("actualSoFar") if snapshot.get("actualSoFar") is not None else snapshot.get("actual")),
            "actual_value": _safe_float(snapshot.get("actual")),
            "model_mean": _safe_float(snapshot.get("modelMean")),
            "live_projection": _safe_float(snapshot.get("liveProjection")),
            "live_edge": _safe_float(snapshot.get("liveEdge")),
            "edge": _safe_float(snapshot.get("liveEdge")),
            "odds": _safe_int(snapshot.get("odds")),
            "first_seen_at": entry.get("firstSeenAt"),
            "last_seen_at": entry.get("lastSeenAt"),
            "first_seen_line": _safe_float(first_snapshot.get("marketLine")),
            "first_seen_live_projection": _safe_float(first_snapshot.get("liveProjection")),
            "first_seen_live_edge": _safe_float(first_snapshot.get("liveEdge")),
            "first_seen_odds": _safe_int(first_snapshot.get("odds")),
            "seen_count": _safe_int(entry.get("seenCount")),
            "reason_summary": str(snapshot.get("reasonSummary") or "").strip(),
            "reasons": [str(reason).strip() for reason in (snapshot.get("reasons") or []) if str(reason).strip()],
            "recommendation_tier": "live",
            "source": "live_registry",
        }
        if market == "pitcher_props":
            item["pitcher_name"] = player_name
        else:
            item["player_name"] = player_name
        signature = _live_prop_signature(item)
        if signature in existing_signatures:
            continue
        existing_signatures.add(signature)
        out.append(item)
    out.sort(key=lambda row: (float(row.get("edge") or 0.0), float(row.get("live_projection") or 0.0)), reverse=True)
    return out


def _live_lens_row_is_live(live_lens_row: dict[str, Any] | None) -> bool:
    status = (live_lens_row or {}).get("status") if isinstance((live_lens_row or {}).get("status"), dict) else {}
    abstract = str(status.get("abstract") or "").strip().lower()
    detailed = str(status.get("detailed") or "").strip().lower()
    return abstract == "live" or detailed == "in progress"


def _synth_live_hitter_prop_rows(
    selected_date: str,
    game_pk: int,
    sim_payload: dict[str, Any] | None,
    actual_payload: dict[str, Any] | None,
    existing_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sim_section = sim_payload.get("sim") if isinstance((sim_payload or {}).get("sim"), dict) else {}
    hitter_models = sim_section.get("hitter_props") if isinstance(sim_section.get("hitter_props"), dict) else {}
    if not hitter_models:
        return []
    hitter_market_lines = _hitter_snapshot_market_lines(selected_date)
    if not hitter_market_lines:
        return []
    existing_signatures = {_live_prop_signature(row) for row in existing_rows if isinstance(row, dict)}
    actual_rows = _actual_batting_context_by_name(actual_payload)
    progress_fraction = _live_progress_fraction(actual_payload)
    out: list[dict[str, Any]] = []
    away_abbr = _normalize_live_name((((actual_payload or {}).get("gameData") or {}).get("teams") or {}).get("away", {}).get("abbreviation"))
    home_abbr = _normalize_live_name((((actual_payload or {}).get("gameData") or {}).get("teams") or {}).get("home", {}).get("abbreviation"))
    for model_row in hitter_models.values():
        if not isinstance(model_row, dict):
            continue
        hitter_name = str(model_row.get("name") or "").strip()
        if not hitter_name:
            continue
        player_market_lines = _market_lines_for_live_name(hitter_market_lines, hitter_name)
        if not player_market_lines:
            continue
        actual_context = actual_rows.get(_normalize_live_name(hitter_name))
        actual_row = (actual_context or {}).get("stats") if isinstance(actual_context, dict) else None
        team = str(model_row.get("team") or "").strip()
        team_side = str(model_row.get("team_side") or "").strip().lower()
        if team_side not in {"away", "home"} and isinstance(actual_context, dict):
            team_side = str(actual_context.get("team_side") or "").strip().lower()
        if team_side not in {"away", "home"}:
            normalized_team = _normalize_live_name(team)
            if normalized_team and normalized_team == away_abbr:
                team_side = "away"
            elif normalized_team and normalized_team == home_abbr:
                team_side = "home"
        for prop_key, market_meta in _LIVE_HITTER_MARKET_KEYS.items():
            market_key, market_label = market_meta
            market = player_market_lines.get(market_key)
            if not isinstance(market, dict):
                continue
            line_value = _safe_float(market.get("line"))
            if line_value is None:
                continue
            dist_key = {
                "hits": "hits_dist",
                "runs_scored": "runs_dist",
                "rbis": "rbi_dist",
                "total_bases": "total_bases_dist",
                "home_runs": "home_runs_dist",
            }.get(prop_key)
            mean_key = {
                "hits": "h_mean",
                "runs_scored": "r_mean",
                "rbis": "rbi_mean",
                "total_bases": "tb_mean",
                "home_runs": "hr_mean",
            }.get(prop_key)
            model_prob_over = _dist_prob_over_line(model_row.get(dist_key), float(line_value)) if dist_key else None
            model_mean = _safe_float(model_row.get(mean_key)) if mean_key else None
            actual_value = _actual_hitter_stat_value(actual_row, prop_key)
            live_projection = _bounded_live_hitter_projection(
                prop_key=prop_key,
                player_name=hitter_name,
                team_side=team_side,
                actual_value=actual_value,
                model_mean=model_mean,
                model_row=model_row,
                actual_context=actual_context,
                actual_payload=actual_payload,
                batting_context=actual_rows,
            ) if team_side in {"away", "home"} else _bounded_live_projection(actual_value, model_mean, progress_fraction)
            side_pick = _select_bounded_live_side(
                model_prob_over=model_prob_over,
                line_value=float(line_value),
                over_odds=market.get("over_odds"),
                under_odds=market.get("under_odds"),
                live_projection=live_projection,
            )
            if side_pick is None:
                continue
            item = {
                "market": "hitter_props",
                "prop": prop_key,
                "market_label": market_label,
                "game_pk": int(game_pk),
                "player_name": hitter_name,
                "team": team,
                "team_side": team_side,
                "selection": side_pick.get("selection"),
                "market_line": float(line_value),
                "actual": actual_value,
                "actual_so_far": actual_value,
                "actual_value": actual_value,
                "model_mean": model_mean,
                "live_projection": live_projection,
                "live_edge": side_pick.get("liveEdge"),
                "edge": side_pick.get("marketEdge"),
                "odds": side_pick.get("odds"),
                "over_odds": market.get("over_odds"),
                "under_odds": market.get("under_odds"),
                "market_prob_over": side_pick.get("marketProbOver"),
                "market_prob_under": side_pick.get("marketProbUnder"),
                "market_prob_mode": side_pick.get("marketProbMode"),
                "model_prob_over": model_prob_over,
                "selected_side_market_prob": side_pick.get("selectedSideMarketProb"),
                "projection_gap": side_pick.get("projectionGap"),
                "lineup_order": _safe_int(model_row.get("lineup_order")),
                "pa_mean": _safe_float(model_row.get("pa_mean")),
                "ab_mean": _safe_float(model_row.get("ab_mean")),
                "rank": None,
                "recommendation_tier": "live",
                "source": "current_market",
            }
            if not _live_hitter_prop_row_actionable(item):
                continue
            signature = _live_prop_signature(item)
            if signature in existing_signatures:
                continue
            existing_signatures.add(signature)
            out.append(item)
    out.sort(key=lambda row: (float(row.get("edge") or 0.0), float(row.get("model_prob_over") or 0.0)), reverse=True)
    for index, row in enumerate(out, start=1):
        row["rank"] = index
    return out


def _source_live_prop_rows(live_lens_row: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = []
    for key in ("liveProps", "archivedLiveProps", "props"):
        candidate = live_lens_row.get(key) if isinstance((live_lens_row or {}).get(key), list) else []
        if candidate:
            rows = candidate
            break
    game_pk = int((live_lens_row or {}).get("gamePk") or 0)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_market = str(row.get("market") or "").strip().lower()
        raw_prop = str(row.get("prop") or "").strip().lower()
        market_label = str(row.get("marketLabel") or "").strip()
        if raw_market and raw_prop:
            market = raw_market
            prop = raw_prop
            market_label = market_label or _registry_market_label(market, prop)
        else:
            market_label = market_label or str(row.get("market") or "Prop").strip()
            market, prop = _live_prop_kind(market_label)
        tier = str(row.get("tier") or "live").strip().lower() or "live"
        item = {
            "market": market,
            "prop": prop,
            "market_label": market_label,
            "game_pk": game_pk or None,
            "player_name": str(row.get("playerName") or "").strip(),
            "team": str(row.get("team") or row.get("teamAbbr") or "").strip(),
            "team_side": str(row.get("teamSide") or "").strip().lower(),
            "selection": str(row.get("selection") or "over").strip().lower(),
            "market_line": row.get("line"),
            "actual": row.get("actual"),
            "actual_so_far": row.get("actualSoFar", row.get("actual")),
            "actual_value": row.get("actual"),
            "archived_for_reconciliation": row.get("archivedForReconciliation"),
            "batters_faced": row.get("battersFaced"),
            "model_mean": row.get("modelMean"),
            "live_projection": row.get("liveProjection"),
            "live_edge": row.get("liveEdge"),
            "edge": row.get("edge"),
            "odds": row.get("odds"),
            "over_odds": row.get("overOdds"),
            "under_odds": row.get("underOdds"),
            "market_prob_over": row.get("marketProbOver"),
            "market_prob_under": row.get("marketProbUnder"),
            "market_prob_mode": row.get("marketProbMode"),
            "model_prob_over": row.get("modelProbOver"),
            "estimated_win_prob": row.get("estimatedWinProb"),
            "selected_side_market_prob": row.get("selectedSideMarketProb", row.get("estimatedWinProb")),
            "outs_mean": row.get("outsMean"),
            "outs_recorded": row.get("outsRecorded"),
            "pitch_count": row.get("pitchCount"),
            "pitch_count_buffer": row.get("pitchCountBuffer"),
            "pitches_per_batter": row.get("pitchesPerBatter"),
            "expected_pitches_per_batter": row.get("expectedPitchesPerBatter"),
            "stamina_pitches": row.get("staminaPitches"),
            "strikes": row.get("strikes"),
            "strike_rate": row.get("strikeRate"),
            "strikeout_rate": row.get("strikeoutRate"),
            "times_through_order": row.get("timesThroughOrder"),
            "projection_gap": row.get("projectionGap"),
            "reason_summary": str(row.get("reason_summary") or "").strip(),
            "reasons": row.get("reasons") if isinstance(row.get("reasons"), list) else [],
            "first_seen_at": row.get("firstSeenAt"),
            "first_seen_actual": row.get("firstSeenActual"),
            "last_seen_at": row.get("lastSeenAt"),
            "first_seen_line": row.get("firstSeenLine"),
            "first_seen_live_projection": row.get("firstSeenLiveProjection"),
            "first_seen_live_edge": row.get("firstSeenLiveEdge"),
            "first_seen_odds": row.get("firstSeenOdds"),
            "seen_count": row.get("seenCount"),
            "ranking_score": row.get("rankingScore"),
            "rank": row.get("rank"),
            "status": str(row.get("status") or "").strip().lower(),
            "recommendation_tier": tier,
            "source": str(row.get("source") or "live_registry").strip() or "live_registry",
        }
        if market == "pitcher_props":
            item["pitcher_name"] = item["player_name"]
        out.append(item)
    return out


def _source_snapshot_detail(selected_date: str, game_pk: int, actual_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(actual_payload, dict):
        return None
    today_iso = date.today().isoformat()
    status = (actual_payload.get("gameData") or {}).get("status") if isinstance(actual_payload.get("gameData"), dict) else {}
    teams = (actual_payload.get("gameData") or {}).get("teams") if isinstance(actual_payload.get("gameData"), dict) else {}
    linescore = ((actual_payload.get("liveData") or {}).get("linescore")) if isinstance(actual_payload.get("liveData"), dict) else {}
    plays = ((actual_payload.get("liveData") or {}).get("plays")) if isinstance(actual_payload.get("liveData"), dict) else {}
    current_play = (plays.get("currentPlay") or {}) if isinstance(plays, dict) else {}
    matchup = current_play.get("matchup") if isinstance(current_play, dict) else {}
    batter = matchup.get("batter") if isinstance(matchup, dict) else {}
    pitcher = matchup.get("pitcher") if isinstance(matchup, dict) else {}
    away_abbr = str(((teams.get("away") or {}).get("abbreviation") if isinstance(teams, dict) else "") or "Away").strip() or "Away"
    home_abbr = str(((teams.get("home") or {}).get("abbreviation") if isinstance(teams, dict) else "") or "Home").strip() or "Home"
    return {
        "gamePk": int(game_pk),
        "date": selected_date or None,
        "archived": bool(selected_date and selected_date != today_iso),
        "streamAvailable": bool(selected_date == today_iso),
        "generatedAt": today_iso,
        "status": dict(status) if isinstance(status, dict) else {},
        "current": {
            "inning": linescore.get("currentInning") if isinstance(linescore, dict) else None,
            "halfInning": (str(linescore.get("inningHalf") or "").strip().lower() or None) if isinstance(linescore, dict) else None,
            "count": {
                "outs": linescore.get("outs") if isinstance(linescore, dict) else None,
                "balls": current_play.get("count", {}).get("balls") if isinstance(current_play.get("count"), dict) else None,
                "strikes": current_play.get("count", {}).get("strikes") if isinstance(current_play.get("count"), dict) else None,
            },
            "batter": {
                "fullName": str((batter or {}).get("fullName") or "").strip(),
                "id": _safe_int((batter or {}).get("id")),
            },
            "pitcher": {
                "fullName": str((pitcher or {}).get("fullName") or "").strip(),
                "id": _safe_int((pitcher or {}).get("id")),
            },
        },
        "teams": {
            "away": {
                "totals": _actual_team_totals(actual_payload, "away"),
                "boxscore": {
                    "batting": _actual_boxscore_batting(actual_payload, "away"),
                    "pitching": _actual_boxscore_pitching(actual_payload, "away"),
                },
                "abbr": away_abbr,
            },
            "home": {
                "totals": _actual_team_totals(actual_payload, "home"),
                "boxscore": {
                    "batting": _actual_boxscore_batting(actual_payload, "home"),
                    "pitching": _actual_boxscore_pitching(actual_payload, "home"),
                },
                "abbr": home_abbr,
            },
        },
    }


def _source_sim_detail(selected_date: str, game_pk: int, sim_payload: dict[str, Any] | None, actual_payload: dict[str, Any] | None = None, live_lens_row: dict[str, Any] | None = None) -> dict[str, Any]:
    matchup = (live_lens_row or {}).get("matchup") if isinstance((live_lens_row or {}).get("matchup"), dict) else {}
    away_team = matchup.get("away") if isinstance(matchup.get("away"), dict) else {}
    home_team = matchup.get("home") if isinstance(matchup.get("home"), dict) else {}
    today_iso = date.today().isoformat()
    is_historical_date = bool(selected_date and selected_date != today_iso)
    has_live_props = isinstance((live_lens_row or {}).get("liveProps"), list) and bool((live_lens_row or {}).get("liveProps"))
    has_archived_live_props = isinstance((live_lens_row or {}).get("archivedLiveProps"), list) and bool((live_lens_row or {}).get("archivedLiveProps"))
    live_prop_rows = _source_live_prop_rows(live_lens_row)
    is_live_game = _actual_payload_is_live(actual_payload) or _live_lens_row_is_live(live_lens_row)
    if is_historical_date and not has_live_props and not has_archived_live_props:
        live_prop_rows = []
    registry_rows = [] if has_archived_live_props else _registry_live_prop_rows(selected_date, int(game_pk), live_prop_rows)
    if registry_rows:
        live_prop_rows.extend(registry_rows)
        if is_historical_date or is_live_game:
            live_prop_rows = [
                row for row in live_prop_rows
                if str(row.get("market") or "").strip().lower() != "pitcher_props"
            ]
    elif is_live_game:
        live_prop_rows.extend(_synth_live_hitter_prop_rows(selected_date, int(game_pk), sim_payload, actual_payload, live_prop_rows))
    if not is_historical_date and is_live_game:
        same_day_hitter_synth = _synth_live_hitter_prop_rows(selected_date, int(game_pk), sim_payload, actual_payload, [])
        synth_signatures = {_live_prop_signature(row) for row in same_day_hitter_synth}
        live_prop_rows = [
            row for row in live_prop_rows
            if str(row.get("market") or "").strip().lower() != "pitcher_props"
            and (str(row.get("market") or "").strip().lower() != "hitter_props" or not synth_signatures or _live_prop_signature(row) in synth_signatures)
        ]
        for row in live_prop_rows:
            if str(row.get("market") or "").strip().lower() == "hitter_props":
                row["source"] = "current_market"
        live_prop_rows.extend(_current_live_pitcher_prop_rows(selected_date, sim_payload, actual_payload))
    ranking_rows = live_prop_rows
    if is_live_game:
        ranking_rows = _annotate_source_live_prop_rows_with_state(live_prop_rows, actual_payload, live_lens_row)
    live_prop_rows = _apply_source_live_prop_ranking_scores(ranking_rows)
    if not isinstance(sim_payload, dict):
        return {
            "found": False,
            "date": selected_date,
            "gamePk": int(game_pk),
            "away": {
                "abbreviation": str(away_team.get("abbr") or "").strip() or None,
                "name": str(away_team.get("name") or "").strip() or None,
                "team_id": away_team.get("teamId"),
            },
            "home": {
                "abbreviation": str(home_team.get("abbr") or "").strip() or None,
                "name": str(home_team.get("name") or "").strip() or None,
                "team_id": home_team.get("teamId"),
            },
            "hasPbp": False,
            "note": None,
            "predictedMode": None,
            "sourceFile": None,
            "segments": {},
            "livePitcherModelMismatches": [],
            "roster_snapshot": {},
            "livePropRows": live_prop_rows,
            "gameLens": live_lens_row.get("gameLens") if isinstance((live_lens_row or {}).get("gameLens"), list) else [],
        }
    sim_section = sim_payload.get("sim") if isinstance(sim_payload.get("sim"), dict) else {}
    aggregate = sim_section.get("aggregate_boxscore") if isinstance(sim_section.get("aggregate_boxscore"), dict) else {}
    away_box = aggregate.get("away") if isinstance(aggregate.get("away"), dict) else {}
    home_box = aggregate.get("home") if isinstance(aggregate.get("home"), dict) else {}
    away_totals = away_box.get("totals") if isinstance(away_box.get("totals"), dict) else {}
    home_totals = home_box.get("totals") if isinstance(home_box.get("totals"), dict) else {}
    return {
        "found": True,
        "date": selected_date,
        "gamePk": int(game_pk),
        "simCount": sim_section.get("sims"),
        "away": {
            "abbreviation": str(away_team.get("abbr") or sim_payload.get("away_abbr") or "").strip() or None,
            "name": str(away_team.get("name") or sim_payload.get("away") or "").strip() or None,
            "team_id": away_team.get("teamId"),
        },
        "home": {
            "abbreviation": str(home_team.get("abbr") or sim_payload.get("home_abbr") or "").strip() or None,
            "name": str(home_team.get("name") or sim_payload.get("home") or "").strip() or None,
            "team_id": home_team.get("teamId"),
        },
        "hasPbp": bool(sim_payload.get("pbp") or sim_payload.get("pbp_boxscore") or sim_section.get("pbp")),
        "note": sim_section.get("note") or sim_payload.get("note"),
        "predictedMode": sim_section.get("predictedMode") or sim_payload.get("predicted_mode"),
        "sourceFile": sim_payload.get("source_file") or sim_payload.get("sourceFile"),
        "segments": sim_section.get("segments") if isinstance(sim_section.get("segments"), dict) else {},
        "livePitcherModelMismatches": sim_section.get("livePitcherModelMismatches") if isinstance(sim_section.get("livePitcherModelMismatches"), list) else [],
        "roster_snapshot": sim_section.get("roster_snapshot") if isinstance(sim_section.get("roster_snapshot"), dict) else {},
        "boxscoreMode": "aggregate",
        "pitchingScope": "full_staff",
        "predicted": {
            "away": away_totals.get("R"),
            "home": home_totals.get("R"),
        },
        "boxscore": {
            "away": {
                "totals": away_totals,
                "batting": away_box.get("batting") if isinstance(away_box.get("batting"), list) else [],
                "pitching": away_box.get("pitching") if isinstance(away_box.get("pitching"), list) else [],
            },
            "home": {
                "totals": home_totals,
                "batting": home_box.get("batting") if isinstance(home_box.get("batting"), list) else [],
                "pitching": home_box.get("pitching") if isinstance(home_box.get("pitching"), list) else [],
            },
        },
        "livePropRows": live_prop_rows,
        "gameLens": live_lens_row.get("gameLens") if isinstance((live_lens_row or {}).get("gameLens"), list) else [],
    }


def source_card_detail_payload(selected_date: str, game_pk: int) -> dict[str, Any]:
    sim_payload = _daily_sim_by_game(selected_date, [int(game_pk)]).get(int(game_pk))
    actual_payload = _daily_actual_by_game(selected_date, [int(game_pk)]).get(int(game_pk))
    live_lens_row = _live_lens_game_row(selected_date, int(game_pk))
    return {
        "date": selected_date,
        "gamePk": int(game_pk),
        "snapshot": _source_snapshot_detail(selected_date, int(game_pk), actual_payload),
        "sim": _source_sim_detail(selected_date, int(game_pk), sim_payload, actual_payload, live_lens_row),
    }


def _iter_team_players(feed: dict[str, Any], side: str) -> list[dict[str, Any]]:
    box = (feed.get("liveData") or {}).get("boxscore") if isinstance(feed.get("liveData"), dict) else {}
    teams = box.get("teams") if isinstance(box, dict) else {}
    team = teams.get(side) if isinstance(teams, dict) else {}
    players = team.get("players") if isinstance(team, dict) else {}
    if not isinstance(players, dict):
        return []
    return [player for player in players.values() if isinstance(player, dict)]


def _pos_abbr(player_obj: dict[str, Any]) -> str:
    position = player_obj.get("position") if isinstance(player_obj.get("position"), dict) else {}
    return str(position.get("abbreviation") or "").strip()


def _actual_boxscore_batting(feed: dict[str, Any], side: str) -> list[dict[str, Any]]:
    rows: list[tuple[int, int, dict[str, Any]]] = []
    for player_obj in _iter_team_players(feed, side):
        batting = (player_obj.get("stats") or {}).get("batting") if isinstance(player_obj.get("stats"), dict) else {}
        if not isinstance(batting, dict) or not batting:
            continue
        person = player_obj.get("person") if isinstance(player_obj.get("person"), dict) else {}
        player_id = int(person.get("id") or 0)
        if player_id <= 0:
            continue
        batting_order_raw = player_obj.get("battingOrder")
        try:
            batting_order = int(str(batting_order_raw)) if batting_order_raw is not None else 999999
        except Exception:
            batting_order = 999999
        row = {
            "name": str(person.get("fullName") or "").strip(),
            "pos": _pos_abbr(player_obj),
            "AB": _format_num(_safe_int(batting.get("atBats"))),
            "H": _format_num(_safe_int(batting.get("hits"))),
            "R": _format_num(_safe_int(batting.get("runs"))),
            "RBI": _format_num(_safe_int(batting.get("rbi"))),
            "BB": _format_num(_safe_int(batting.get("baseOnBalls"))),
            "SO": _format_num(_safe_int(batting.get("strikeOuts"))),
            "HR": _format_num(_safe_int(batting.get("homeRuns"))),
            "TB": _format_num(_safe_int(batting.get("totalBases"))),
        }
        rows.append((batting_order, player_id, row))
    rows.sort(key=lambda value: (value[0], value[1]))
    return [row for _, __, row in rows if row.get("name")]


def _actual_boxscore_pitching(feed: dict[str, Any], side: str) -> list[dict[str, Any]]:
    rows: list[tuple[int, int, str, dict[str, Any]]] = []
    for player_obj in _iter_team_players(feed, side):
        pitching = (player_obj.get("stats") or {}).get("pitching") if isinstance(player_obj.get("stats"), dict) else {}
        if not isinstance(pitching, dict) or not pitching:
            continue
        person = player_obj.get("person") if isinstance(player_obj.get("person"), dict) else {}
        player_id = int(person.get("id") or 0)
        if player_id <= 0:
            continue
        games_started = _safe_int(pitching.get("gamesStarted")) or 0
        pitches = _safe_int(pitching.get("pitchesThrown")) or 0
        row = {
            "name": str(person.get("fullName") or "").strip(),
            "IP": str(pitching.get("inningsPitched") or "").strip(),
            "H": _format_num(_safe_int(pitching.get("hits"))),
            "R": _format_num(_safe_int(pitching.get("runs"))),
            "ER": _format_num(_safe_int(pitching.get("earnedRuns"))),
            "BB": _format_num(_safe_int(pitching.get("baseOnBalls"))),
            "SO": _format_num(_safe_int(pitching.get("strikeOuts"))),
            "HR": _format_num(_safe_int(pitching.get("homeRuns"))),
            "BF": _format_num(_safe_int(pitching.get("battersFaced"))),
            "P": _format_num(pitches),
        }
        rows.append((0 if games_started == 1 else 1, -pitches, row.get("name") or "", row))
    rows.sort(key=lambda value: (value[0], value[1], value[2]))
    return [row for _, __, ___, row in rows if row.get("name")]


def _actual_team_totals(feed: dict[str, Any], side: str) -> dict[str, str]:
    linescore = (feed.get("liveData") or {}).get("linescore") if isinstance(feed.get("liveData"), dict) else {}
    ls_teams = linescore.get("teams") if isinstance(linescore, dict) else {}
    ls_side = ls_teams.get(side) if isinstance(ls_teams, dict) else {}
    box = (feed.get("liveData") or {}).get("boxscore") if isinstance(feed.get("liveData"), dict) else {}
    teams = box.get("teams") if isinstance(box, dict) else {}
    team = teams.get(side) if isinstance(teams, dict) else {}
    team_stats = team.get("teamStats") if isinstance(team, dict) else {}
    batting = team_stats.get("batting") if isinstance(team_stats, dict) else {}
    runs = ls_side.get("runs") if isinstance(ls_side, dict) else None
    hits = ls_side.get("hits") if isinstance(ls_side, dict) else None
    errors = ls_side.get("errors") if isinstance(ls_side, dict) else None
    return {
        "R": _format_num(_safe_int(runs if runs is not None else batting.get("runs"))),
        "H": _format_num(_safe_int(hits if hits is not None else batting.get("hits"))),
        "E": _format_num(_safe_int(errors)),
    }


def _actual_box_panel(actual_payload: dict[str, Any] | None, away_abbr: str, home_abbr: str, selected_date: str, game_pk: int) -> dict[str, Any]:
    if not isinstance(actual_payload, dict):
        return {
            "title": "Live / final box unavailable",
            "body": "Archived live/final box data was not available for this game on the selected date.",
            "badge": "Unavailable",
            "items": ["Archived live/final box feed was not captured for this matchup."],
        }

    status = (actual_payload.get("gameData") or {}).get("status") if isinstance(actual_payload.get("gameData"), dict) else {}
    abstract_state = str((status or {}).get("abstractGameState") or "").strip()
    detailed_state = str((status or {}).get("detailedState") or "Archived feed").strip() or "Archived feed"
    batting_columns = ["name", "pos", "AB", "R", "H", "RBI", "BB", "SO", "HR", "TB"]
    pitching_columns = ["name", "IP", "H", "R", "ER", "BB", "SO", "HR", "BF", "P"]
    away_batting = _actual_boxscore_batting(actual_payload, "away")
    home_batting = _actual_boxscore_batting(actual_payload, "home")
    away_pitching = _actual_boxscore_pitching(actual_payload, "away")
    home_pitching = _actual_boxscore_pitching(actual_payload, "home")
    away_totals = _actual_team_totals(actual_payload, "away")
    home_totals = _actual_team_totals(actual_payload, "home")
    items = [
        f"Status: {detailed_state}",
        f"Score: {away_abbr} {away_totals.get('R')} - {home_abbr} {home_totals.get('R')}",
    ]
    current_play = (((actual_payload.get("liveData") or {}).get("linescore") or {}).get("currentInningOrdinal")) if isinstance((actual_payload.get("liveData") or {}).get("linescore"), dict) else None
    if current_play:
        items.append(f"Inning: {str(current_play).strip()}")
    return {
        "title": detailed_state,
        "body": "This lane is sourced from the archived StatsAPI raw feed when a committed historical game feed is available.",
        "badge": abstract_state or "Archived feed",
        "badge_class": _status_badge_class(abstract_state),
        "items": items,
        "actual_box": {
            "totals": [
                {"team": away_abbr, "totals": away_totals},
                {"team": home_abbr, "totals": home_totals},
            ],
            "batting_columns": batting_columns,
            "pitching_columns": pitching_columns,
            "away": {"batting": away_batting, "pitching": away_pitching},
            "home": {"batting": home_batting, "pitching": home_pitching},
        },
    }


def _sim_panel(sim_payload: dict[str, Any] | None, away_abbr: str, home_abbr: str) -> dict[str, Any]:
    if not isinstance(sim_payload, dict):
        return {
            "eyebrow": "Sim box",
            "title": "Aggregate sim leaders",
            "body": "No committed sim artifact was found for this game.",
            "items": ["Daily sim boxscore artifact unavailable for the selected date."],
        }

    sim_section = sim_payload.get("sim") if isinstance(sim_payload.get("sim"), dict) else {}
    aggregate = sim_section.get("aggregate_boxscore") if isinstance(sim_section.get("aggregate_boxscore"), dict) else {}
    away_box = aggregate.get("away") if isinstance(aggregate.get("away"), dict) else {}
    home_box = aggregate.get("home") if isinstance(aggregate.get("home"), dict) else {}
    away_totals = away_box.get("totals") if isinstance(away_box.get("totals"), dict) else {}
    home_totals = home_box.get("totals") if isinstance(home_box.get("totals"), dict) else {}
    away_batting = away_box.get("batting") if isinstance(away_box.get("batting"), list) else []
    home_batting = home_box.get("batting") if isinstance(home_box.get("batting"), list) else []
    away_pitching = away_box.get("pitching") if isinstance(away_box.get("pitching"), list) else []
    home_pitching = home_box.get("pitching") if isinstance(home_box.get("pitching"), list) else []
    batting_columns = ["name", "pos", "AB", "H", "R", "RBI", "BB", "SO", "HR", "TB"]
    pitching_columns = ["name", "IP", "H", "R", "ER", "BB", "SO", "HR", "BF", "P"]

    def top_by(rows: list[dict[str, Any]], key: str, *, limit: int = 3) -> list[dict[str, Any]]:
        values = [row for row in rows if isinstance(row, dict)]
        values.sort(key=lambda row: float(row.get(key) or 0.0), reverse=True)
        return [row for row in values[:limit] if str(row.get("name") or "").strip()]

    items = [
        f"Mean score: {away_abbr} {_format_num(away_totals.get('R'))} - {home_abbr} {_format_num(home_totals.get('R'))}",
    ]
    top_bats = away_top_bats = top_by(away_batting, "TB", limit=3)
    home_top_bats = top_by(home_batting, "TB", limit=3)
    away_top_arms = top_by(away_pitching, "SO", limit=3)
    home_top_arms = top_by(home_pitching, "SO", limit=3)
    if top_bats:
        items.append(
            "Top bats: "
            + " | ".join(
                [
                    f"{str(row.get('name') or '').strip()} {_format_num(row.get('TB'))} TB"
                    for row in (away_top_bats[:1] + home_top_bats[:1])
                    if str(row.get('name') or '').strip()
                ]
            )
        )
    top_arms = away_top_arms[:1] + home_top_arms[:1]
    if top_arms:
        items.append(
            "Top arms: "
            + " | ".join(
                [
                    f"{str(row.get('name') or '').strip()} {_format_num(row.get('IP'))} IP / {_format_num(row.get('SO'))} K"
                    for row in top_arms
                    if str(row.get('name') or '').strip()
                ]
            )
        )
    weather = sim_payload.get("weather") if isinstance(sim_payload.get("weather"), dict) else {}
    park = sim_payload.get("park") if isinstance(sim_payload.get("park"), dict) else {}
    weather_text = str(weather.get("wind_raw") or weather.get("condition") or "").strip()
    park_text = str(park.get("venue_name") or "").strip()
    if weather_text or park_text:
        items.append(f"Context: {park_text or 'Park'} | {weather_text or 'No weather note'}")

    def batting_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {
                "name": str(row.get("name") or "").strip(),
                "detail": str(row.get("pos") or "BAT").strip() or "BAT",
                "value": f"{_format_num(row.get('TB'))} TB | {_format_num(row.get('H'))} H | {_format_num(row.get('RBI'))} RBI",
            }
            for row in rows
            if str(row.get("name") or "").strip()
        ]

    def pitching_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {
                "name": str(row.get("name") or "").strip(),
                "detail": str(row.get("role") or "ARM").strip() or "ARM",
                "value": f"{_format_num(row.get('IP'))} IP | {_format_num(row.get('SO'))} K | {_format_num(row.get('ER'))} ER",
            }
            for row in rows
            if str(row.get("name") or "").strip()
        ]

    def table_rows(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, str]]:
        formatted_rows: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            formatted_row: dict[str, str] = {}
            for column in columns:
                value = row.get(column)
                if column in {"name", "pos", "role"}:
                    formatted_row[column] = str(value or "").strip()
                else:
                    formatted_row[column] = _format_num(value)
            formatted_rows.append(formatted_row)
        return formatted_rows

    summary_stats = [
        {"label": away_abbr, "value": f"{_format_num(away_totals.get('R'))} R | {_format_num(away_totals.get('H'))} H"},
        {"label": home_abbr, "value": f"{_format_num(home_totals.get('R'))} R | {_format_num(home_totals.get('H'))} H"},
        {"label": "Weather", "value": weather_text or "Indoor / neutral"},
    ]
    table_groups = [
        {"heading": f"{away_abbr} bats", "rows": batting_rows(away_top_bats)},
        {"heading": f"{home_abbr} bats", "rows": batting_rows(home_top_bats)},
        {"heading": f"{away_abbr} arms", "rows": pitching_rows(away_top_arms)},
        {"heading": f"{home_abbr} arms", "rows": pitching_rows(home_top_arms)},
    ]
    return {
        "eyebrow": "Sim box",
        "title": f"Aggregate sim leaders | {int((sim_section.get('sims') or 0)) or 1000} sims",
        "body": "This lane comes from the committed daily sim artifact for the matchup, which keeps Syndicate on the artifact-backed migration path while restoring more of the old cards-page density.",
        "items": items,
        "summary_stats": summary_stats,
        "table_groups": [group for group in table_groups if group.get("rows")],
        "sim_box": {
            "mode": "aggregate",
            "totals": [
                {"team": away_abbr, "totals": {"R": _format_num(away_totals.get("R")), "H": _format_num(away_totals.get("H")), "E": _format_num(away_totals.get("E"))}},
                {"team": home_abbr, "totals": {"R": _format_num(home_totals.get("R")), "H": _format_num(home_totals.get("H")), "E": _format_num(home_totals.get("E"))}},
            ],
            "batting_columns": batting_columns,
            "pitching_columns": pitching_columns,
            "away": {
                "batting": table_rows(away_batting, batting_columns),
                "pitching": table_rows(away_pitching, pitching_columns),
            },
            "home": {
                "batting": table_rows(home_batting, batting_columns),
                "pitching": table_rows(home_pitching, pitching_columns),
            },
        },
    }


def _panels_for_output(output: dict[str, Any], betting_game: dict[str, Any] | None = None, sim_payload: dict[str, Any] | None = None, actual_payload: dict[str, Any] | None = None, selected_date: str = "") -> list[dict[str, Any]]:
    starter_names = output.get("starter_names") if isinstance(output.get("starter_names"), dict) else {}
    away_starter = str(starter_names.get("away") or "TBD").strip() or "TBD"
    home_starter = str(starter_names.get("home") or "TBD").strip() or "TBD"
    full = output.get("full") if isinstance(output.get("full"), dict) else {}
    first3 = output.get("first3") if isinstance(output.get("first3"), dict) else {}
    first5 = output.get("first5") if isinstance(output.get("first5"), dict) else {}
    first1 = output.get("first1") if isinstance(output.get("first1"), dict) else {}
    hr_items = _panel_items_from_hr_targets(output)
    official_items, official_count, playable_count = _official_market_items(betting_game or {}) if betting_game else ([], 0, 0)
    props_tab_groups = _props_tab_groups(betting_game or {}) if betting_game else []
    hitter_items = _likelihood_items(output, "hits_1plus", "p_h_1plus_cal", "h_mean", "1+ hit")
    tb_items = _likelihood_items(output, "total_bases_2plus", "p_tb_2plus_cal", "tb_mean", "2+ total bases")
    top_hitter_items = (hitter_items + tb_items + hr_items)[:5]
    away_abbr = str(output.get("away") or "AWY").strip() or "AWY"
    home_abbr = str(output.get("home") or "HOM").strip() or "HOM"
    sim_panel = _sim_panel(sim_payload, away_abbr, home_abbr)
    sim_panel["actual_box_panel"] = _actual_box_panel(actual_payload, away_abbr, home_abbr, selected_date, int(output.get("game_pk") or 0))
    props_panel_context = _props_panel_context(
        betting_game or {},
        top_hitter_items,
        f"{away_starter} vs {home_starter}",
        "Starter names are coming directly from the MLB daily summary artifact.",
        sim_panel.get("items") if isinstance(sim_panel.get("items"), list) else [],
        official_items,
    )
    return [
        {
            "eyebrow": "Projected starters",
            "title": f"{away_starter} vs {home_starter}",
            "body": "Starter names are coming directly from the MLB daily summary artifact.",
        },
        {
            "eyebrow": "Game outlook",
            "title": f"Full total {_format_num((full.get('away_runs_mean') or 0) + (full.get('home_runs_mean') or 0))} | F5 total {_format_num((first5.get('away_runs_mean') or 0) + (first5.get('home_runs_mean') or 0))}",
            "body": "The legacy MLB cards page kept multiple game-horizon slices visible in the main pane; this card now does the same.",
            "items": [
                f"Full: home {_format_pct(full.get('home_win_prob'))} | total {_format_num((full.get('away_runs_mean') or 0) + (full.get('home_runs_mean') or 0))} | margin {_format_signed_num((full.get('home_runs_mean') or 0) - (full.get('away_runs_mean') or 0))}",
                f"F5: home {_format_pct(first5.get('home_win_prob'))} | total {_format_num((first5.get('away_runs_mean') or 0) + (first5.get('home_runs_mean') or 0))} | tie {_format_pct(first5.get('tie_prob'))}",
                f"F3: home {_format_pct(first3.get('home_win_prob'))} | total {_format_num((first3.get('away_runs_mean') or 0) + (first3.get('home_runs_mean') or 0))} | tie {_format_pct(first3.get('tie_prob'))}",
                f"F1: home {_format_pct(first1.get('home_win_prob'))} | tie {_format_pct(first1.get('tie_prob'))}",
            ],
        },
        {
            "eyebrow": "Official card",
            "title": f"{official_count} official pick(s){f' | +{playable_count} playable' if playable_count else ''}",
            "body": "Official picks are pulled from the same betting payload used by the dedicated MLB betting-card page, so the main cards pane carries the same recommendation lane.",
            "items": official_items or ["No official picks were published for this game on the selected date."],
        },
        {
            "eyebrow": "Top hitter looks",
            "title": "Hits, total bases, and HR",
            "body": "The strongest batter looks are shown inline so you can review the game without leaving the main cards pane.",
            "items": top_hitter_items or ["No hitter look summary was available for this game."],
            "prop_groups": props_tab_groups,
            "prop_summary": props_panel_context.get("prop_summary"),
            "prop_filter_groups": props_panel_context.get("prop_filter_groups"),
            "prop_lens": props_panel_context.get("prop_lens"),
            "empty_copy": props_panel_context.get("empty_copy"),
        },
        sim_panel,
    ]


def _metrics_for_output(output: dict[str, Any]) -> list[dict[str, str]]:
    full = output.get("full") if isinstance(output.get("full"), dict) else {}
    first5 = output.get("first5") if isinstance(output.get("first5"), dict) else {}
    first3 = output.get("first3") if isinstance(output.get("first3"), dict) else {}
    first1 = output.get("first1") if isinstance(output.get("first1"), dict) else {}
    return [
        {"label": "Away win", "value": _format_pct(full.get("away_win_prob"))},
        {"label": "Home win", "value": _format_pct(full.get("home_win_prob"))},
        {"label": "Full total", "value": _format_num((full.get("away_runs_mean") or 0) + (full.get("home_runs_mean") or 0))},
        {"label": "F5 total", "value": _format_num((first5.get("away_runs_mean") or 0) + (first5.get("home_runs_mean") or 0))},
        {"label": "F3 total", "value": _format_num((first3.get("away_runs_mean") or 0) + (first3.get("home_runs_mean") or 0))},
        {"label": "F1 tie", "value": _format_pct(first1.get("tie_prob"))},
    ]


def _cards_first1_zero_run_prob(row: dict[str, Any] | None) -> float | None:
    if not isinstance(row, dict):
        return None
    direct = _safe_float(row.get("nrfi_prob"))
    if direct is not None:
        return max(0.0, min(1.0, float(direct)))
    dist = row.get("total_runs_dist") or {}
    if not isinstance(dist, dict) or not dist:
        return None
    total_weight = 0.0
    zero_weight = 0.0
    for raw_key, raw_value in dist.items():
        weight = _safe_float(raw_value)
        if weight is None or weight < 0:
            continue
        total_weight += float(weight)
        key_int = _safe_int(raw_key)
        if key_int is not None and int(key_int) == 0:
            zero_weight += float(weight)
    if total_weight <= 0.0:
        return None
    return max(0.0, min(1.0, zero_weight / total_weight))


_CARDS_F1_NRFI_MIN_PROB = 0.55
_CARDS_F1_NRFI_MAX_MEAN_RUNS = 0.80
_CARDS_F1_YRFI_MAX_NRFI_PROB = 0.50
_CARDS_F1_YRFI_MIN_MEAN_RUNS = 0.95
_CARDS_F1_YRFI_MIN_SIDE_LEAD_PROB = 0.24


def _rfi_signal_from_first1_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    nrfi_prob = _cards_first1_zero_run_prob(row)
    if nrfi_prob is None:
        return None
    yrfi_prob = max(0.0, min(1.0, 1.0 - float(nrfi_prob)))
    away_runs_mean = _safe_float(row.get("away_runs_mean"))
    home_runs_mean = _safe_float(row.get("home_runs_mean"))
    mean_total_runs = None
    if away_runs_mean is not None or home_runs_mean is not None:
        mean_total_runs = float(away_runs_mean or 0.0) + float(home_runs_mean or 0.0)
    away_win_prob = _safe_float(row.get("away_win_prob"))
    home_win_prob = _safe_float(row.get("home_win_prob"))
    max_side_prob = max(float(away_win_prob or 0.0), float(home_win_prob or 0.0))
    if mean_total_runs is None:
        return None

    label = None
    tone = None
    summary = None
    detail = None
    if float(nrfi_prob) >= _CARDS_F1_NRFI_MIN_PROB and float(mean_total_runs) <= _CARDS_F1_NRFI_MAX_MEAN_RUNS:
        label = "F1 NRFI"
        tone = "nrfi"
        summary = f"0-run sim {float(nrfi_prob) * 100.0:.1f}% | F1 mean {float(mean_total_runs):.2f}"
        detail = (
            f"Season filter qualified: simulated scoreless first inning {float(nrfi_prob) * 100.0:.1f}% "
            f"with only {float(mean_total_runs):.2f} expected runs in the opening frame."
        )
    elif (
        float(nrfi_prob) <= _CARDS_F1_YRFI_MAX_NRFI_PROB
        and float(mean_total_runs) >= _CARDS_F1_YRFI_MIN_MEAN_RUNS
        and float(max_side_prob) >= _CARDS_F1_YRFI_MIN_SIDE_LEAD_PROB
    ):
        label = "F1 YRFI"
        tone = "yrfi"
        summary = f"F1 mean {float(mean_total_runs):.2f} | side lead {float(max_side_prob) * 100.0:.1f}%"
        detail = (
            f"Season filter qualified: only {float(nrfi_prob) * 100.0:.1f}% simulated NRFI, "
            f"{float(mean_total_runs):.2f} expected first-inning runs, and one side reaches a "
            f"{float(max_side_prob) * 100.0:.1f}% chance to be ahead after one."
        )
    else:
        return None

    return {
        "label": label,
        "tone": tone,
        "summary": summary,
        "detail": detail,
        "nrfiProb": round(float(nrfi_prob), 4),
        "yrfiProb": round(float(yrfi_prob), 4),
    }


def _rfi_targets_signal_index(doc: dict[str, Any] | None) -> dict[int, dict[str, Any]] | None:
    if not isinstance(doc, dict):
        return None
    rows = doc.get("signals")
    if not isinstance(rows, list):
        return None
    out: dict[int, dict[str, Any]] = {}
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            continue
        game_pk = _safe_int(raw_row.get("game_pk"))
        signal = raw_row.get("signal") if isinstance(raw_row.get("signal"), dict) else None
        if not game_pk or int(game_pk) <= 0 or not isinstance(signal, dict):
            continue
        out[int(game_pk)] = dict(signal)
    return out


def _cards_status_is_live(status: dict[str, Any] | None) -> bool:
    if not isinstance(status, dict):
        return False
    abstract = str(status.get("abstract") or status.get("abstractGameState") or "").strip().lower()
    detailed = str(status.get("detailed") or status.get("detailedState") or "").strip().lower()
    return abstract == "live" or detailed == "in progress"


def _cards_status_is_final(status: dict[str, Any] | None) -> bool:
    if not isinstance(status, dict):
        return False
    abstract = str(status.get("abstract") or status.get("abstractGameState") or "").strip().lower()
    detailed = str(status.get("detailed") or status.get("detailedState") or "").strip().lower()
    return abstract == "final" or "final" in detailed or detailed in {"game over", "completed early"}


def _starter_ladder_badge_from_supported_totals(
    supported_totals: list[int],
    *,
    stat_key: str | None,
    short_label: str,
    last_supported_prob: float | None,
    detail_parts: list[str] | None = None,
    max_rungs: int | None = None,
) -> dict[str, Any] | None:
    cleaned = [int(total) for total in supported_totals if _safe_int(total) is not None]
    if max_rungs is not None and int(max_rungs) > 0 and len(cleaned) > int(max_rungs):
        cleaned = cleaned[: int(max_rungs)]
    if not cleaned:
        return None
    probability = _safe_float(last_supported_prob)
    tone = "soft"
    if probability is not None:
        if float(probability) >= 0.35:
            tone = "strong"
        elif float(probability) >= 0.25:
            tone = "solid"
    supported_label = "/".join(str(int(total)) for total in cleaned)
    if short_label == "O" and len(cleaned) > 1:
        label = f"{short_label} {supported_label}"
    elif len(cleaned) == 1:
        label = f"{short_label} up to {int(cleaned[0])}"
    else:
        label = f"{short_label} up to {int(cleaned[-1])}"
    parts = [str(part).strip() for part in (detail_parts or []) if str(part).strip()]
    parts.append(f"Supported ladders: {supported_label}")
    parts.append(f"Last supported rung: {int(cleaned[-1])}")
    out: dict[str, Any] = {
        "label": label,
        "stat": str(stat_key or "").strip().lower() or None,
        "target": int(cleaned[-1]),
        "targets": cleaned,
        "tone": tone,
        "detail": " ".join(parts).strip(),
    }
    if probability is not None:
        out["hitProb"] = round(float(probability), 3)
    return out


def _starter_ladder_badge_stat_key(badge: dict[str, Any] | None) -> str | None:
    if not isinstance(badge, dict):
        return None
    stat_key = str(badge.get("stat") or "").strip().lower()
    if stat_key:
        return stat_key
    label = str(badge.get("label") or "").strip().upper()
    if label.startswith("K"):
        return "strikeouts"
    if label.startswith("O"):
        return "outs"
    if label.startswith("BB"):
        return "walks_allowed"
    if label.startswith("H"):
        return "hits_allowed"
    return None


def _starter_ladder_badge_short_label(stat_key: str | None) -> str:
    normalized = str(stat_key or "").strip().lower()
    if normalized == "strikeouts":
        return "K"
    if normalized == "outs":
        return "O"
    if normalized == "hits_allowed":
        return "H"
    if normalized == "walks_allowed":
        return "BB"
    if normalized == "earned_runs":
        return "ER"
    return normalized[:3].upper() or "L"


def _final_starter_ladder_badges_for_side(
    *,
    side: str,
    entry: dict[str, Any] | None,
    actual_payload: dict[str, Any] | None,
    stats_cache: dict[tuple[int, str, str, str], dict[str, Any] | None],
    game_pk: int,
) -> list[dict[str, Any]]:
    if side not in {"away", "home"} or not isinstance(entry, dict) or not isinstance(actual_payload, dict):
        return []
    actual_keys = {
        "strikeouts": "strikeOuts",
        "outs": "outs",
        "earned_runs": "earnedRuns",
        "hits_allowed": "hits",
        "walks_allowed": "baseOnBalls",
        "walks": "baseOnBalls",
        "batters_faced": "battersFaced",
        "pitches": "pitchesThrown",
    }
    pregame_badges = entry.get("pregameLadderBadges")
    ladder_badges = [
        badge for badge in (
            pregame_badges if isinstance(pregame_badges, list) else (entry.get("ladderBadges") or [])
        )
        if isinstance(badge, dict)
    ]
    if not ladder_badges:
        return []

    starter_name = str(entry.get("fullName") or entry.get("name") or "").strip()
    if not starter_name:
        return []
    cache_key = (int(game_pk), str(side), _normalize_live_name(starter_name), "pitching")
    if cache_key not in stats_cache:
        actual_pitchers = _actual_pitching_context_by_name(actual_payload)
        context = actual_pitchers.get(_normalize_live_name(starter_name)) if isinstance(actual_pitchers, dict) else None
        stats_cache[cache_key] = dict((context or {}).get("stats") or {}) if isinstance(context, dict) else None
    stats = stats_cache.get(cache_key)
    if not isinstance(stats, dict):
        return []

    grouped_badges: dict[str, dict[str, Any]] = {}
    for badge in ladder_badges:
        stat_key = _starter_ladder_badge_stat_key(badge)
        actual_key = actual_keys.get(str(stat_key or ""))
        if not actual_key:
            continue
        actual_value = _safe_float(stats.get(actual_key))
        if actual_value is None:
            continue
        targets = [int(total) for total in (badge.get("targets") or []) if _safe_int(total) is not None]
        if not targets:
            target_total = _safe_int(badge.get("target"))
            if target_total is not None:
                targets = [int(target_total)]
        if not targets:
            continue

        group = grouped_badges.setdefault(
            str(stat_key or _starter_ladder_badge_short_label(stat_key)),
            {
                "short_label": _starter_ladder_badge_short_label(stat_key),
                "stat": stat_key,
                "actual": int(round(float(actual_value))),
                "targets": [],
            },
        )
        existing_targets = {int(total) for total in (group.get("targets") or []) if _safe_int(total) is not None}
        for total in targets:
            if int(total) not in existing_targets:
                cast_targets = group.get("targets") if isinstance(group.get("targets"), list) else []
                cast_targets.append(int(total))
                group["targets"] = cast_targets
                existing_targets.add(int(total))

    resolved_badges: list[dict[str, Any]] = []
    for group in grouped_badges.values():
        targets = sorted(int(total) for total in (group.get("targets") or []) if _safe_int(total) is not None)
        if not targets:
            continue
        actual_value = int(group.get("actual") or 0)
        wins = sum(1 for total in targets if float(actual_value) + 1e-9 >= float(total))
        losses = max(0, len(targets) - int(wins))
        short_label = str(group.get("short_label") or "L").strip() or "L"
        tone = "win" if losses == 0 else "loss" if wins == 0 else "split"
        if tone == "win":
            label = f"{short_label} +{int(wins)} ({int(actual_value)})"
        elif tone == "loss":
            label = f"{short_label} -{int(losses)} ({int(actual_value)})"
        else:
            label = f"{short_label} {int(wins)}/{int(len(targets))} ({int(actual_value)})"
        resolved_badges.append(
            {
                "label": label,
                "stat": group.get("stat"),
                "tone": tone,
                "detail": (
                    f"Final {short_label}: {int(actual_value)}. Supported ladders: "
                    f"{'/'.join(str(int(total)) for total in targets)}. Correct ladders: {int(wins)}. Missed ladders: {int(losses)}."
                ),
                "count": int(wins if tone != "loss" else losses),
                "wins": int(wins),
                "losses": int(losses),
                "targetCount": int(len(targets)),
                "actual": int(actual_value),
                "targets": targets,
                "source": "final",
            }
        )
    return resolved_badges


def _live_starter_ladder_badges_for_side(
    *,
    side: str,
    selected_date: str,
    sim_payload: dict[str, Any] | None,
    actual_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if side not in {"away", "home"} or not isinstance(sim_payload, dict) or not isinstance(actual_payload, dict):
        return []
    sim_section = sim_payload.get("sim") if isinstance(sim_payload.get("sim"), dict) else {}
    pitcher_models = sim_section.get("pitcher_props") if isinstance(sim_section.get("pitcher_props"), dict) else {}
    market_lines = _pitcher_snapshot_market_lines(selected_date)
    probable_pitchers = ((actual_payload.get("gameData") or {}).get("probablePitchers")) if isinstance((actual_payload.get("gameData") or {}).get("probablePitchers"), dict) else {}
    if not pitcher_models or not market_lines or not probable_pitchers:
        return []
    probable = probable_pitchers.get(side) if isinstance(probable_pitchers, dict) else None
    pitcher_id = _safe_int((probable or {}).get("id")) if isinstance(probable, dict) else None
    pitcher_name = str((probable or {}).get("fullName") or "").strip() if isinstance(probable, dict) else ""
    if pitcher_id is None or not pitcher_name:
        return []
    if _starter_removed_from_actual_payload(
        actual_payload,
        side=side,
        starter_id=pitcher_id,
        starter_name=pitcher_name,
    ):
        return []
    model_row = pitcher_models.get(str(pitcher_id)) if isinstance(pitcher_models, dict) else None
    market_entry = _market_lines_for_live_name(market_lines, pitcher_name)
    actual_pitchers = _actual_pitching_context_by_name(actual_payload)
    actual_context = actual_pitchers.get(_normalize_live_name(pitcher_name)) if isinstance(actual_pitchers, dict) else None
    actual_row = (actual_context or {}).get("stats") if isinstance(actual_context, dict) else None
    progress_fraction = _live_progress_fraction(actual_payload)
    if not isinstance(model_row, dict) or not isinstance(market_entry, dict):
        return []

    config = {
        "strikeouts": {"dist_key": "so_dist", "mean_key": "so_mean", "ladder_min_hit_prob": 0.2, "ladder_max_rungs": 4},
        "outs": {"dist_key": "outs_dist", "mean_key": "outs_mean", "ladder_min_hit_prob": 0.24, "ladder_max_rungs": 2},
        "hits_allowed": {"dist_key": "hits_dist", "mean_key": "hits_mean", "ladder_min_hit_prob": 0.2, "ladder_max_rungs": None},
        "walks_allowed": {"dist_key": "walks_dist", "mean_key": "walks_mean", "ladder_min_hit_prob": 0.2, "ladder_max_rungs": None},
    }
    out: list[dict[str, Any]] = []
    for prop_key, cfg in config.items():
        market = market_entry.get(prop_key)
        if not isinstance(market, dict):
            continue
        short_label = _starter_ladder_badge_short_label(prop_key)
        base_line = _safe_float(market.get("line"))
        if base_line is None:
            continue
        actual_value = _actual_pitcher_stat_value(actual_row, prop_key)
        model_mean = _safe_float(model_row.get(cfg["mean_key"]))
        live_projection = _bounded_live_pitcher_projection(actual_value, model_mean, progress_fraction)
        supported_totals: list[int] = []
        last_supported_prob: float | None = None
        base_over_total = int(base_line) + 1
        for candidate in _live_pitcher_ladder_market_candidates(market):
            line_value = _safe_float(candidate.get("line"))
            if line_value is None:
                continue
            target_total = int(line_value) + 1
            if actual_value is not None and int(target_total) <= int(float(actual_value)):
                continue
            model_prob_over = _dist_prob_over_line(model_row.get(cfg["dist_key"]), float(line_value))
            if model_prob_over is None or float(model_prob_over) < float(cfg["ladder_min_hit_prob"] or 0.2):
                continue
            if live_projection is None or float(live_projection) + 1.0 < float(target_total):
                continue
            supported_totals.append(int(target_total))
            last_supported_prob = float(model_prob_over)
        if prop_key == "outs":
            higher_alts = [int(total) for total in supported_totals if int(total) > int(base_over_total)]
            if higher_alts:
                supported_totals = higher_alts
        badge = _starter_ladder_badge_from_supported_totals(
            supported_totals,
            stat_key=prop_key,
            short_label=short_label,
            last_supported_prob=last_supported_prob,
            detail_parts=[
                f"Live projection {float(live_projection):.1f}." if live_projection is not None else "",
                f"Current {float(actual_value):.1f}." if actual_value is not None else "",
                "Starter still active in live game state.",
            ],
            max_rungs=cfg["ladder_max_rungs"],
        )
        if not isinstance(badge, dict):
            continue
        badge["source"] = "live"
        if actual_value is not None:
            badge["actual"] = float(actual_value)
        detail_bits = []
        out.append(badge)
    return out


def _attach_cards_stateful_starter_ladder_badges(
    games: list[dict[str, Any]],
    *,
    selected_date: str,
    sim_games: dict[int, dict[str, Any]] | None,
    actual_games: dict[int, dict[str, Any]] | None,
) -> None:
    if not isinstance(games, list):
        return
    stats_cache: dict[tuple[int, str, str, str], dict[str, Any] | None] = {}
    for card in games:
        if not isinstance(card, dict):
            continue
        status = card.get("status") if isinstance(card.get("status"), dict) else {}
        probable = card.get("probable") if isinstance(card.get("probable"), dict) else None
        game_pk = _safe_int(card.get("gamePk"))
        if not isinstance(probable, dict) or game_pk is None or int(game_pk) <= 0:
            continue
        actual_payload = (actual_games or {}).get(int(game_pk)) if isinstance(actual_games, dict) else None
        if _cards_status_is_final(status) and isinstance(actual_payload, dict):
            for side in ("away", "home"):
                entry = probable.get(side)
                if not isinstance(entry, dict):
                    continue
                settled_badges = _final_starter_ladder_badges_for_side(
                    side=side,
                    entry=entry,
                    actual_payload=actual_payload,
                    stats_cache=stats_cache,
                    game_pk=int(game_pk),
                )
                if settled_badges:
                    entry["miniLadderBadges"] = settled_badges
                else:
                    entry.pop("miniLadderBadges", None)
            continue
        if _cards_status_is_live(status) and isinstance(actual_payload, dict):
            sim_payload = (sim_games or {}).get(int(game_pk)) if isinstance(sim_games, dict) else None
            for side in ("away", "home"):
                entry = probable.get(side)
                if not isinstance(entry, dict):
                    continue
                live_badges = _live_starter_ladder_badges_for_side(
                    side=side,
                    selected_date=selected_date,
                    sim_payload=sim_payload,
                    actual_payload=actual_payload,
                )
                if live_badges:
                    entry["miniLadderBadges"] = live_badges
                else:
                    entry.pop("miniLadderBadges", None)


def _games_from_daily_summary(summary: dict[str, Any], *, betting_games: dict[int, dict[str, Any]] | None = None, sim_games: dict[int, dict[str, Any]] | None = None, actual_games: dict[int, dict[str, Any]] | None = None, first1_signals_by_game: dict[int, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    outputs = summary.get("outputs") if isinstance(summary.get("outputs"), list) else []
    games: list[dict[str, Any]] = []
    selected_date = str(summary.get("date") or "").strip()
    for output in outputs:
        if not isinstance(output, dict):
            continue
        game_pk = int(output.get("game_pk") or 0)
        starter_names = output.get("starter_names") if isinstance(output.get("starter_names"), dict) else {}
        away_starter = str(starter_names.get("away") or "TBD").strip() or "TBD"
        home_starter = str(starter_names.get("home") or "TBD").strip() or "TBD"
        betting_game = (betting_games or {}).get(game_pk)
        sim_payload = (sim_games or {}).get(game_pk)
        actual_payload = (actual_games or {}).get(game_pk)
        official_items, official_count, playable_count = _official_market_items(betting_game or {}) if betting_game else ([], 0, 0)
        betting_flags = (betting_game or {}).get("flags") if isinstance((betting_game or {}).get("flags"), dict) else {}
        markets = betting_game.get("markets") if isinstance((betting_game or {}).get("markets"), dict) else {}
        away_abbr = str(output.get("away") or "").strip() or "AWY"
        home_abbr = str(output.get("home") or "").strip() or "HME"
        has_pitcher_props = bool(markets.get("pitcherProps") or markets.get("extraPitcherProps"))
        has_hitter_props = bool(markets.get("hitterProps") or markets.get("extraHitterProps"))
        schedule = _schedule_context(selected_date=selected_date, actual_payload=actual_payload, betting_game=betting_game)
        first1_signal = None
        if isinstance(first1_signals_by_game, dict):
            first1_signal = first1_signals_by_game.get(game_pk)
        if not isinstance(first1_signal, dict):
            first1_signal = _rfi_signal_from_first1_row(output.get("first1") if isinstance(output.get("first1"), dict) else None)
        games.append(
            {
                "gamePk": game_pk,
                "card_variant": "mlb_main",
            "gameType": schedule["gameType"],
                "away": _team_display(away_abbr),
                "home": _team_display(home_abbr),
                "status": _source_status(actual_payload),
            "detail": schedule["detail"],
                "detail_label": "First pitch",
            "startTime": schedule["startTime"],
            "gameDate": schedule["gameDate"],
            "officialDate": schedule["officialDate"],
                "summary": f"{away_starter} vs {home_starter}{f' | {official_count} official pick(s)' if official_count else ''}{f' | +{playable_count} playable' if playable_count else ''}",
                "status_badge": "Official card" if official_count else "Model-only board",
                "hero_note": f"{official_count} official pick(s){f' | +{playable_count} playable' if playable_count else ''}" if official_count or playable_count else "No official picks published yet",
                "probable": _source_probable(output, betting_game=betting_game),
                "predictions": _source_predictions(output),
                "flags": {
                    "hasAnyRecommendations": bool(betting_flags.get("hasAnyRecommendations") if betting_flags else (official_count or playable_count)),
                    "hasOfficialRecommendations": bool(betting_flags.get("hasOfficialRecommendations") if betting_flags else official_count),
                    "hasPlayableCandidates": bool(betting_flags.get("hasPlayableCandidates") if betting_flags else playable_count),
                    "hasPitcherProps": has_pitcher_props,
                    "hasHitterProps": has_hitter_props,
                },
                "markets": markets,
                "metrics": _metrics_for_output(output) + [{"label": "Official", "value": str(official_count)}] + ([{"label": "Playable", "value": str(playable_count)}] if playable_count else []),
                "market_tiles": _market_tiles(betting_game or {}, away_abbr, home_abbr),
                "starter_metrics": _starter_metrics(output),
                "segment_overview_cards": _segment_overview_cards(output, betting_game=betting_game),
                "probability_rows": _probability_rows(output),
                "run_projection_rows": _run_projection_rows(output),
                "panels": _panels_for_output(output, betting_game=betting_game, sim_payload=sim_payload, actual_payload=actual_payload, selected_date=selected_date),
                "href": f"/mlb/game/{game_pk}?date={selected_date or ''}",
                "href_label": "Open game detail",
                "first1BetSignal": dict(first1_signal) if isinstance(first1_signal, dict) else None,
            }
        )
    return games


def build_cards_page_context(selected_date: str) -> dict[str, Any]:
    parsed_date = _parse_iso_date(selected_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()

    module_links = build_module_links(selected_date, "Cards")
    module_link_labels = {
        str(link.get("label") or "").strip().lower()
        for link in module_links
        if isinstance(link, dict)
    }

    summary_path = daily_artifact_path(selected_date)
    summary = load_json_file(summary_path)
    betting_games = _cards_recommendation_payload_by_game(selected_date)
    output_rows = summary.get("outputs") if isinstance((summary or {}).get("outputs"), list) else []
    game_pks = [int(row.get("game_pk") or 0) for row in output_rows if isinstance(row, dict) and int(row.get("game_pk") or 0)]
    sim_games = _daily_sim_by_game(selected_date, game_pks)
    actual_games = _daily_actual_by_game(selected_date, game_pks)
    rfi_targets = load_json_file(daily_rfi_targets_path(selected_date))
    games = _games_from_daily_summary(
        summary,
        betting_games=betting_games,
        sim_games=sim_games,
        actual_games=actual_games,
        first1_signals_by_game=_rfi_targets_signal_index(rfi_targets),
    ) if summary else []
    _attach_cards_pregame_starter_ladder_badges(games, selected_date=selected_date)
    _attach_cards_stateful_starter_ladder_badges(
        games,
        selected_date=selected_date,
        sim_games=sim_games,
        actual_games=actual_games,
    )
    using_sample_data = False

    scoreboard_items = [
        {
            "target_id": f"game-{game['gamePk']}",
            "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
            "status": game["detail"],
        }
        for game in games
    ]

    cards_control_links = [
        {"label": "Pitcher ladders", "href": f"/mlb/pitcher-ladders?date={selected_date}"},
        {"label": "Hitter ladders", "href": f"/mlb/hitter-ladders?date={selected_date}"},
        {"label": "HR targets", "href": f"/mlb/hr-targets?date={selected_date}"},
        {"label": "Pitcher top props", "href": f"/mlb/pitcher-top-props?date={selected_date}"},
        {"label": "Hitter top props", "href": f"/mlb/hitter-top-props?date={selected_date}"},
        {"label": "Season review", "href": f"/mlb/season/{selected_date[:4]}?date={selected_date}"},
        {"label": "Betting card", "href": f"/mlb/season/{selected_date[:4]}/betting-card?date={selected_date}"},
    ]
    cards_control_links = [
        link
        for link in cards_control_links
        if str(link.get("label") or "").strip().lower() not in module_link_labels
    ]

    return apply_game_board_contract({
        "date": selected_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "module_links": module_links,
        "cards_control_links": cards_control_links,
        "games": games,
        "scoreboard_items": scoreboard_items,
        "source_path": Path(summary_path).name,
        "using_sample_data": using_sample_data,
        "source_title": "MLB daily summary artifact" if games else "MLB cards unavailable",
        "empty_state": {
            "eyebrow": "MLB cards",
            "title": "No game cards were available for this date",
            "body": "The cards board only renders saved MLB daily summary artifacts, and none were available for the requested date.",
            "list_items": [
                f"Requested date: {selected_date}",
                "Choose another stored MLB date from the date control.",
            ],
        } if not games else None,
        "header_stats": [{"label": "Games", "value": str(len(games))}],
        "cards_header_title": "MLB Game Cards",
        "cards_header_meta": f"Artifact-backed slate | {selected_date}",
        "plain_control_ids": True,
        "source_meta_items": [
            f"Date {selected_date}",
            f"Games {len(games)}",
            Path(summary_path).name if games else "No data",
        ],
        "route_path": "/mlb/cards",
        "intro_title": "MLB Cards",
        "intro_body": "This is the first real Syndicate route expanded from the MLB app. The layout now follows the MLB card-page structure, and reusable pieces are being extracted into the shared layer immediately.",
        "hr_targets_shelf": _hr_targets_shelf(selected_date),
        "show_app_header": False,
        "show_intro": False,
        "show_source_summary": False,
        "page_body_class": "cards-body syndicate-mlb-cards-page",
        "page_shell_class": "syndicate-mlb-cards-shell",
        "cards_grid_class": "cards-grid",
        "cards_stylesheet": "mlb/cards_exact.css",
        "cards_script": "mlb/board.js",
    }, sport="mlb", module="cards")