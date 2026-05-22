from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from syndicate.features.nba.sources import parse_iso_date
from syndicate.features.nba.sources import processed_path


def _artifact_root() -> Path:
    return processed_path("game_cards_2099-01-01.csv").parent


def _artifact_path(filename: str) -> Path:
    return _artifact_root() / filename


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except Exception:
        return []
    return rows


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [row for row in csv.DictReader(handle) if isinstance(row, dict)]
    except Exception:
        return []


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _number(value: Any) -> float | None:
    number = _safe_float(value)
    if number is None:
        return None
    return float(number)


def _norm_player_name(value: str) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _canon_gid10(game_id: Any) -> str:
    text = str(game_id or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 10:
        return digits.zfill(10)
    return digits


def _stat_key(value: Any) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "points": "pts",
        "point": "pts",
        "pts": "pts",
        "rebounds": "reb",
        "rebound": "reb",
        "reb": "reb",
        "assists": "ast",
        "assist": "ast",
        "ast": "ast",
        "3pm": "threes",
        "3pt": "threes",
        "threes": "threes",
        "steals": "stl",
        "stl": "stl",
        "blocks": "blk",
        "blk": "blk",
        "turnovers": "tov",
        "tov": "tov",
        "pra": "pra",
        "pr": "pr",
        "pa": "pa",
        "ra": "ra",
    }
    return mapping.get(raw, raw)


def _projection_ts(obj: dict[str, Any], idx: int) -> tuple[float, int]:
    for key in ("received_at", "ts", "created_at"):
        value = str(obj.get(key) or "").strip()
        if not value:
            continue
        try:
            return parse_iso_date(value[:10]).toordinal(), idx
        except Exception:
            continue
    return float(idx), idx


def _latest_player_prop_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], tuple[int, dict[str, Any]]] = {}
    for idx, row in enumerate(rows):
        if str(row.get("market") or "").strip().lower() != "player_prop":
            continue
        gid = _canon_gid10(row.get("game_id_canon") or row.get("game_id"))
        name_key = _norm_player_name(str(row.get("name_key") or row.get("player") or ""))
        stat_key = _stat_key(row.get("stat"))
        if not gid or not name_key or not stat_key:
            continue
        key = (gid, name_key, stat_key)
        current = grouped.get(key)
        if current is None or _projection_ts(row, idx) > _projection_ts(current[1], current[0]):
            grouped[key] = (idx, row)
    return [row for _, row in sorted(grouped.values(), key=lambda item: _projection_ts(item[1], item[0]))]


def _load_recon_props_lookup(date_str: str) -> dict[tuple[str, str], dict[str, Any]]:
    rows = _read_csv_rows(_artifact_path(f"recon_props_{date_str}.csv"))
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        gid = _canon_gid10(row.get("game_id"))
        name_key = _norm_player_name(str(row.get("player_name") or row.get("player") or ""))
        if not gid or not name_key:
            continue
        numeric_row: dict[str, Any] = dict(row)
        for key in ("pts", "reb", "ast", "threes", "stl", "blk", "tov", "pra", "pr", "pa", "ra"):
            numeric_row[key] = _number(row.get(key))
        if numeric_row.get("pr") is None and numeric_row.get("pts") is not None and numeric_row.get("reb") is not None:
            numeric_row["pr"] = float(numeric_row["pts"]) + float(numeric_row["reb"])
        if numeric_row.get("pa") is None and numeric_row.get("pts") is not None and numeric_row.get("ast") is not None:
            numeric_row["pa"] = float(numeric_row["pts"]) + float(numeric_row["ast"])
        if numeric_row.get("ra") is None and numeric_row.get("reb") is not None and numeric_row.get("ast") is not None:
            numeric_row["ra"] = float(numeric_row["reb"]) + float(numeric_row["ast"])
        if numeric_row.get("pra") is None and numeric_row.get("pts") is not None and numeric_row.get("reb") is not None and numeric_row.get("ast") is not None:
            numeric_row["pra"] = float(numeric_row["pts"]) + float(numeric_row["reb"]) + float(numeric_row["ast"])
        lookup[(gid, name_key)] = numeric_row
    return lookup


def _projection_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "mae_proj": None,
            "mae_raw": None,
            "mae_adjusted": None,
            "rmse_proj": None,
            "rmse_raw": None,
            "rmse_adjusted": None,
            "adjusted_beats_raw_rate": None,
            "proj_beats_adjusted_rate": None,
            "mean_adjustment": None,
            "mean_team_ratio": None,
            "mean_game_ratio": None,
        }

    def _series_mean(values: list[float]) -> float | None:
        return (sum(values) / len(values)) if values else None

    def _abs_mean(key: str) -> float | None:
        values = [abs(float(row[key])) for row in rows if _safe_float(row.get(key)) is not None]
        return _series_mean(values)

    def _rmse(key: str) -> float | None:
        values = [float(row[key]) for row in rows if _safe_float(row.get(key)) is not None]
        if not values:
            return None
        return (sum(value * value for value in values) / len(values)) ** 0.5

    def _rate(key: str) -> float | None:
        values = [float(row[key]) for row in rows if _safe_float(row.get(key)) is not None]
        return _series_mean(values)

    return {
        "n": len(rows),
        "mae_proj": _abs_mean("err_proj"),
        "mae_raw": _abs_mean("err_raw"),
        "mae_adjusted": _abs_mean("err_adjusted"),
        "rmse_proj": _rmse("err_proj"),
        "rmse_raw": _rmse("err_raw"),
        "rmse_adjusted": _rmse("err_adjusted"),
        "adjusted_beats_raw_rate": _rate("adjusted_beats_raw"),
        "proj_beats_adjusted_rate": _rate("proj_beats_adjusted"),
        "mean_adjustment": _rate("adjustment_delta"),
        "mean_team_ratio": _rate("pregame_team_total_ratio"),
        "mean_game_ratio": _rate("pregame_game_total_ratio"),
    }


def _rows_by_key(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = str(row.get(key) or "unknown")
        groups.setdefault(label, []).append(row)
    return [
        {key: label, **_projection_summary(group_rows)}
        for label, group_rows in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def _local_live_prop_audit_payload(query_string: str) -> dict[str, Any] | None:
    params = parse_qs(query_string or "", keep_blank_values=True)
    date_values = [str(value).strip() for value in params.get("date", []) if str(value).strip()]
    if date_values:
        date_list = [date_values[0]]
    else:
        until = str((params.get("until") or [""])[0]).strip()
        since = str((params.get("since") or [""])[0]).strip()
        if until and since:
            start = parse_iso_date(since)
            end = parse_iso_date(until)
            date_list = []
            current = start
            while current <= end:
                date_list.append(current.isoformat())
                current = current.fromordinal(current.toordinal() + 1)
        else:
            return None

    include_rows = str((params.get("include_rows") or [""])[0]).strip().lower() in {"1", "true", "yes"}
    try:
        max_rows = max(100, min(20000, int(float(str((params.get("max_rows") or ["1000"])[0])))))
    except Exception:
        max_rows = 1000

    all_rows: list[dict[str, Any]] = []
    per_day: list[dict[str, Any]] = []
    debug_days: list[dict[str, Any]] = []
    replay_mode = str((params.get("replay") or [""])[0]).strip().lower() or None

    for date_str in date_list:
        projection_path = _artifact_path(f"live_lens_projections_{date_str}.jsonl")
        signal_path = _artifact_path(f"live_lens_signals_{date_str}.jsonl")
        raw_rows = _read_jsonl(projection_path)
        latest_rows = _latest_player_prop_rows(raw_rows)
        recon_lookup = _load_recon_props_lookup(date_str)
        audit_rows: list[dict[str, Any]] = []
        for row in latest_rows:
            gid = _canon_gid10(row.get("game_id_canon") or row.get("game_id"))
            name_key = _norm_player_name(str(row.get("name_key") or row.get("player") or ""))
            stat_key = _stat_key(row.get("stat"))
            recon_row = recon_lookup.get((gid, name_key))
            actual = recon_row.get(stat_key) if recon_row else None
            if actual is None:
                continue
            proj = _number(row.get("proj"))
            sim_raw = _number(row.get("sim_mu"))
            sim_adjusted = _number(row.get("sim_mu_adjusted"))
            context = row.get("context") if isinstance(row.get("context"), dict) else {}
            if proj is None and sim_raw is None and sim_adjusted is None:
                continue
            entry: dict[str, Any] = {
                "date": date_str,
                "game_id": gid,
                "event_id": row.get("event_id"),
                "home": row.get("home"),
                "away": row.get("away"),
                "player": row.get("player"),
                "name_key": name_key,
                "team_tri": row.get("team_tri"),
                "stat": stat_key,
                "line": _number(row.get("line")),
                "actual": _number(actual),
                "proj": proj,
                "proj_original": _number(row.get("proj_original")),
                "sim_mu": sim_raw,
                "sim_mu_adjusted": sim_adjusted,
                "sim_mu_adjusted_original": _number(row.get("sim_mu_adjusted_original")),
                "elapsed": _number(row.get("elapsed")),
                "strength": _number(row.get("strength")),
                "pregame_team_total_ratio": _number(context.get("pregame_team_total_ratio")),
                "pregame_game_total_ratio": _number(context.get("pregame_game_total_ratio")),
                "pregame_margin_blended": _number(context.get("pregame_margin_blended")),
                "pregame_stat_multiplier": _number(context.get("pregame_stat_multiplier")),
                "pregame_stat_multiplier_original": _number(context.get("pregame_stat_multiplier_original")),
                "sim_vs_line": _number(context.get("sim_vs_line")),
                "sim_vs_line_adjusted": _number(context.get("sim_vs_line_adjusted")),
            }
            actual_num = _number(actual)
            if actual_num is not None and proj is not None:
                entry["err_proj"] = float(proj) - float(actual_num)
            if actual_num is not None and sim_raw is not None:
                entry["err_raw"] = float(sim_raw) - float(actual_num)
            if actual_num is not None and sim_adjusted is not None:
                entry["err_adjusted"] = float(sim_adjusted) - float(actual_num)
            if sim_raw is not None and sim_adjusted is not None:
                entry["adjustment_delta"] = float(sim_adjusted) - float(sim_raw)
            if entry.get("err_adjusted") is not None and entry.get("err_raw") is not None:
                entry["adjusted_beats_raw"] = 1.0 if abs(float(entry["err_adjusted"])) < abs(float(entry["err_raw"])) else 0.0
            if entry.get("err_proj") is not None and entry.get("err_adjusted") is not None:
                entry["proj_beats_adjusted"] = 1.0 if abs(float(entry["err_proj"])) < abs(float(entry["err_adjusted"])) else 0.0
            elapsed = _number(entry.get("elapsed"))
            if elapsed is None:
                entry["elapsed_bucket"] = "unknown"
            elif elapsed < 12:
                entry["elapsed_bucket"] = "Q1"
            elif elapsed < 24:
                entry["elapsed_bucket"] = "Q2"
            elif elapsed < 36:
                entry["elapsed_bucket"] = "Q3"
            else:
                entry["elapsed_bucket"] = "Q4+"
            ratio = _number(entry.get("pregame_team_total_ratio"))
            if ratio is None:
                entry["team_ratio_bucket"] = "unknown"
            elif ratio < 0.97:
                entry["team_ratio_bucket"] = "downshift"
            elif ratio > 1.03:
                entry["team_ratio_bucket"] = "upshift"
            else:
                entry["team_ratio_bucket"] = "flat"
            audit_rows.append(entry)

        all_rows.extend(audit_rows)
        per_day.append({"date": date_str, "summary": _projection_summary(audit_rows)})
        debug_days.append(
            {
                "date": date_str,
                "projection_path": str(projection_path),
                "signals_path": str(signal_path),
                "raw_rows": len(raw_rows),
                "latest_rows": len(latest_rows),
                "replay_mode": replay_mode,
                "audit_source": "projections",
                "settled_rows": len(audit_rows),
            }
        )

    if not any(_artifact_path(f"live_lens_projections_{date_str}.jsonl").exists() for date_str in date_list):
        return None

    history = None
    if include_rows and all_rows:
        history_rows = sorted(
            all_rows,
            key=lambda row: (str(row.get("date") or ""), _safe_float(row.get("elapsed")) or 0.0, str(row.get("player") or ""), str(row.get("stat") or "")),
            reverse=True,
        )[:max_rows]
        history = {"rows": history_rows}

    payload = {
        "ok": True,
        "status": "ok" if all_rows else "empty",
        "meta": {
            "start": date_list[0],
            "end": date_list[-1],
            "days": len(date_list),
            "include_rows": include_rows,
            "max_rows": max_rows,
            "replay": replay_mode,
            "source": "local_mirror",
        },
        "overall": _projection_summary(all_rows),
        "by_stat": _rows_by_key(all_rows, "stat"),
        "by_elapsed_bucket": _rows_by_key(all_rows, "elapsed_bucket"),
        "by_team_ratio_bucket": _rows_by_key(all_rows, "team_ratio_bucket"),
        "per_day": per_day,
        "history": history,
        "debug": {"days": debug_days},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    if not all_rows:
        payload["message"] = "No settled live player-prop projection rows were available for the requested window."
    return payload


def _empty_live_prop_audit_payload(query_string: str) -> dict[str, Any] | None:
    params = parse_qs(query_string or "", keep_blank_values=True)
    date_values = [str(value).strip() for value in params.get("date", []) if str(value).strip()]
    if date_values:
        date_list = [date_values[0]]
    else:
        until = str((params.get("until") or [""])[0]).strip()
        since = str((params.get("since") or [""])[0]).strip()
        if until and since:
            start = parse_iso_date(since)
            end = parse_iso_date(until)
            date_list = []
            current = start
            while current <= end:
                date_list.append(current.isoformat())
                current = current.fromordinal(current.toordinal() + 1)
        else:
            return None

    include_rows = str((params.get("include_rows") or [""])[0]).strip().lower() in {"1", "true", "yes"}
    try:
        max_rows = max(100, min(20000, int(float(str((params.get("max_rows") or ["1000"])[0])))))
    except Exception:
        max_rows = 1000
    replay_mode = str((params.get("replay") or [""])[0]).strip().lower() or None
    debug_days = [
        {
            "date": date_str,
            "projection_path": str(_artifact_path(f"live_lens_projections_{date_str}.jsonl")),
            "signals_path": str(_artifact_path(f"live_lens_signals_{date_str}.jsonl")),
            "raw_rows": 0,
            "latest_rows": 0,
            "replay_mode": replay_mode,
            "audit_source": "projections",
            "settled_rows": 0,
        }
        for date_str in date_list
    ]
    payload = {
        "ok": True,
        "status": "empty",
        "meta": {
            "start": date_list[0],
            "end": date_list[-1],
            "days": len(date_list),
            "include_rows": include_rows,
            "max_rows": max_rows,
            "replay": replay_mode,
            "source": "local_mirror",
        },
        "overall": _projection_summary([]),
        "by_stat": _rows_by_key([], "stat"),
        "by_elapsed_bucket": _rows_by_key([], "elapsed_bucket"),
        "by_team_ratio_bucket": _rows_by_key([], "team_ratio_bucket"),
        "per_day": [{"date": date_str, "summary": _projection_summary([])} for date_str in date_list],
        "history": None,
        "debug": {"days": debug_days},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "message": "No settled live player-prop projection rows were available for the requested window.",
    }
    return payload


@lru_cache(maxsize=256)
def build_live_prop_audit_payload(query_string: str) -> dict[str, Any] | None:
    local_payload = _local_live_prop_audit_payload(query_string)
    if isinstance(local_payload, dict):
        return local_payload
    return _empty_live_prop_audit_payload(query_string)
