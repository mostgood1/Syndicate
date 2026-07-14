from __future__ import annotations

from typing import Any


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _first_float(payload: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = _safe_float(payload.get(key))
        if value is not None:
            return value
    return None


def build_advanced_metrics(row: dict[str, Any]) -> dict[str, Any]:
    home_off_epa = _first_float(row, ["home_off_epa", "home_off_epa_ema", "home_off_epa_prior", "home_off_epa_blend"])
    home_def_epa = _first_float(row, ["home_def_epa", "home_def_epa_ema", "home_def_epa_prior", "home_def_epa_blend"])
    away_off_epa = _first_float(row, ["away_off_epa", "away_off_epa_ema", "away_off_epa_prior", "away_off_epa_blend"])
    away_def_epa = _first_float(row, ["away_def_epa", "away_def_epa_ema", "away_def_epa_prior", "away_def_epa_blend"])

    home_pass_rate = _first_float(row, ["home_pass_rate", "home_pass_rate_ema", "home_pass_rate_prior", "home_pass_rate_blend"])
    away_pass_rate = _first_float(row, ["away_pass_rate", "away_pass_rate_ema", "away_pass_rate_prior", "away_pass_rate_blend"])

    home_rz_pass_rate = _first_float(row, ["home_off_rz_pass_rate", "home_off_rz_pass_rate_ema", "home_rzd_off_eff"])
    away_rz_pass_rate = _first_float(row, ["away_off_rz_pass_rate", "away_off_rz_pass_rate_ema", "away_rzd_off_eff"])

    home_explosive_pass_rate = _first_float(row, ["home_explosive_pass_rate"])
    away_explosive_pass_rate = _first_float(row, ["away_explosive_pass_rate"])

    def_pressure_avg = _first_float(row, ["def_pressure_avg", "def_pressure_avg_ema"])
    pace_secs_play = _first_float(row, ["home_pace_secs_play", "away_pace_secs_play", "pace_secs_play_diff"])

    off_epa_diff = _first_float(row, ["off_epa_diff", "home_off_epa_ema_diff"])
    def_epa_diff = _first_float(row, ["def_epa_diff", "home_def_epa_ema_diff"])
    pass_rate_diff = _first_float(row, ["pass_rate_diff", "home_pass_rate_ema_diff"])
    off_rz_pass_rate_diff = _first_float(row, ["off_rz_pass_rate_diff", "rzd_off_eff_diff"])
    def_rz_pass_rate_diff = _first_float(row, ["def_rz_pass_rate_diff", "rzd_def_eff_diff"])
    explosive_pass_rate_diff = _first_float(row, ["explosive_pass_rate_diff"])
    explosive_run_rate_diff = _first_float(row, ["explosive_run_rate_diff"])

    home_success_rate = _first_float(row, ["home_success_rate", "home_success_rate_ema"])
    away_success_rate = _first_float(row, ["away_success_rate", "away_success_rate_ema"])
    home_success_rate_allowed = _first_float(row, ["home_success_rate_allowed", "home_def_success_rate", "home_success_rate_allowed_ema"])
    away_success_rate_allowed = _first_float(row, ["away_success_rate_allowed", "away_def_success_rate", "away_success_rate_allowed_ema"])

    return {
        "game_id": str(row.get("game_id") or "").strip(),
        "season": _safe_float(row.get("season")),
        "week": _safe_float(row.get("week")),
        "home_team": str(row.get("home_team") or "").strip(),
        "away_team": str(row.get("away_team") or "").strip(),
        "home_offensive_epa": home_off_epa,
        "home_defensive_epa": home_def_epa,
        "away_offensive_epa": away_off_epa,
        "away_defensive_epa": away_def_epa,
        "home_success_rate": home_success_rate,
        "away_success_rate": away_success_rate,
        "home_success_rate_allowed": home_success_rate_allowed,
        "away_success_rate_allowed": away_success_rate_allowed,
        "home_pass_rate": home_pass_rate,
        "away_pass_rate": away_pass_rate,
        "home_red_zone_efficiency": home_rz_pass_rate,
        "away_red_zone_efficiency": away_rz_pass_rate,
        "home_explosive_pass_rate": home_explosive_pass_rate,
        "away_explosive_pass_rate": away_explosive_pass_rate,
        "home_pace_secs_play": _safe_float(row.get("home_pace_secs_play")),
        "away_pace_secs_play": _safe_float(row.get("away_pace_secs_play")),
        "pace_secs_play": pace_secs_play,
        "def_pressure_avg": def_pressure_avg,
        "off_epa_diff": off_epa_diff,
        "def_epa_diff": def_epa_diff,
        "pass_rate_diff": pass_rate_diff,
        "off_rz_pass_rate_diff": off_rz_pass_rate_diff,
        "def_rz_pass_rate_diff": def_rz_pass_rate_diff,
        "explosive_pass_rate_diff": explosive_pass_rate_diff,
        "explosive_run_rate_diff": explosive_run_rate_diff,
        "model_source": "weekly_advanced_schema",
        "adapter": "football_advanced_metrics",
    }
