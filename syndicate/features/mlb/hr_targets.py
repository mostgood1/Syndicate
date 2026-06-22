from __future__ import annotations

import json
from datetime import date
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from syndicate.features.mlb.ladders_common import build_module_links
from syndicate.features.mlb.sources import daily_artifact_path
from syndicate.features.mlb.sources import default_mlb_source_root
from syndicate.features.mlb.sources import load_json_file


def _statcast_features_path() -> Path:
    return default_mlb_source_root() / "data" / "statcast" / "features" / "player_features_latest.json"


def _daily_snapshot_root() -> Path:
    return default_mlb_source_root() / "source_artifacts" / "data" / "daily" / "snapshots"


@lru_cache(maxsize=512)
def _load_json_path(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return date.today()


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


def _team_abbreviation(value: Any) -> str:
    return str(value or "").strip().upper()


def _profile_player_id(profile: dict[str, Any] | None) -> int | None:
    if not isinstance(profile, dict):
        return None
    player = profile.get("player") if isinstance(profile.get("player"), dict) else {}
    return _safe_int(profile.get("id")) or _safe_int(player.get("id")) or _safe_int(player.get("mlbam_id"))


def _profile_player_name(profile: dict[str, Any] | None) -> str:
    if not isinstance(profile, dict):
        return ""
    player = profile.get("player") if isinstance(profile.get("player"), dict) else {}
    return str(profile.get("name") or player.get("full_name") or player.get("name") or "").strip()


def _lineup_batters(side_doc: dict[str, Any]) -> list[dict[str, Any]]:
    lineup = side_doc.get("lineup") if isinstance(side_doc, dict) else None
    if isinstance(lineup, dict) and isinstance(lineup.get("batters"), list):
        return [row for row in lineup.get("batters") if isinstance(row, dict)]
    if isinstance(lineup, list):
        return [row for row in lineup if isinstance(row, dict)]
    return []


def _side_pitcher_profile(side_doc: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(side_doc, dict):
        return {}
    lineup = side_doc.get("lineup")
    if isinstance(lineup, dict) and isinstance(lineup.get("pitcher"), dict):
        return lineup["pitcher"]
    starter_profile = side_doc.get("starter_profile")
    if isinstance(starter_profile, dict):
        return starter_profile
    starter = side_doc.get("starter")
    if isinstance(starter, dict) and any(key in starter for key in ("arsenal", "pitch_mix", "pitch_type_hr_mult")):
        return starter
    return {}


def _primary_pitch_type(pitch_mix: dict[str, Any]) -> tuple[str | None, float | None]:
    if not isinstance(pitch_mix, dict) or not pitch_mix:
        return None, None
    best_pitch = None
    best_share = None
    for pitch_type, share_value in pitch_mix.items():
        share = _safe_float(share_value)
        if share is None:
            continue
        if best_share is None or share > best_share:
            best_pitch = str(pitch_type)
            best_share = share
    return best_pitch, best_share


def _load_roster_game_payload(selected_date: str, game_pk: int | None) -> dict[str, Any]:
    if not selected_date or game_pk is None:
        return {}
    snapshot_dir = _daily_snapshot_root() / selected_date
    if not snapshot_dir.exists():
        return {}
    candidate_dirs = [snapshot_dir / "roster_objs", snapshot_dir]
    for candidate_dir in candidate_dirs:
        if not candidate_dir.exists():
            continue
        matches = sorted(candidate_dir.glob(f"*pk{int(game_pk)}*.json"))
        if not matches:
            continue
        payload = _load_json_path(str(matches[0]))
        if payload:
            return payload
    return {}


def _pitch_mix_context(selected_date: str, row: dict[str, Any]) -> dict[str, Any]:
    game_pk = _safe_int(row.get("game_pk"))
    batter_id = _safe_int(row.get("batter_id"))
    batter_name = str(row.get("player_name") or row.get("name") or "").strip()
    if not selected_date or game_pk is None or batter_id is None:
        return {}

    roster_payload = _load_roster_game_payload(selected_date, game_pk)
    if not roster_payload:
        return {}

    team = _team_abbreviation(row.get("team"))
    side_key: str | None = None
    opponent_key: str | None = None
    batter_profile: dict[str, Any] | None = None
    for current_side in ("away", "home"):
        side_doc = roster_payload.get(current_side)
        if not isinstance(side_doc, dict):
            continue
        side_team = _team_abbreviation(((side_doc.get("team") or {}) if isinstance(side_doc.get("team"), dict) else {}).get("abbreviation"))
        if team and side_team and team != side_team:
            continue
        for batter in _lineup_batters(side_doc):
            if _profile_player_id(batter) == batter_id or (
                batter_name and _profile_player_name(batter).lower() == batter_name.lower()
            ):
                side_key = current_side
                opponent_key = "home" if current_side == "away" else "away"
                batter_profile = batter
                break
        if batter_profile is not None:
            break

    if batter_profile is None or side_key is None or opponent_key is None:
        for current_side in ("away", "home"):
            side_doc = roster_payload.get(current_side)
            if not isinstance(side_doc, dict):
                continue
            for batter in _lineup_batters(side_doc):
                if _profile_player_id(batter) == batter_id or (
                    batter_name and _profile_player_name(batter).lower() == batter_name.lower()
                ):
                    side_key = current_side
                    opponent_key = "home" if current_side == "away" else "away"
                    batter_profile = batter
                    break
            if batter_profile is not None:
                break

    if batter_profile is None or side_key is None or opponent_key is None:
        return {}

    opponent_doc = roster_payload.get(opponent_key)
    if not isinstance(opponent_doc, dict):
        return {}
    pitcher_profile = _side_pitcher_profile(opponent_doc)
    if not pitcher_profile:
        return {}

    statcast_payload = _load_json_path(str(_statcast_features_path()))
    batter_feature = {}
    pitcher_feature = {}
    if isinstance(statcast_payload.get("batters"), dict):
        batter_feature = statcast_payload["batters"].get(str(batter_id)) or {}
    pitcher_feature_id = _profile_player_id(pitcher_profile)
    if pitcher_feature_id is not None and isinstance(statcast_payload.get("pitchers"), dict):
        pitcher_feature = statcast_payload["pitchers"].get(str(pitcher_feature_id)) or {}

    batter_overall = batter_feature.get("overall") if isinstance(batter_feature.get("overall"), dict) else {}
    pitcher_overall = pitcher_feature.get("overall") if isinstance(pitcher_feature.get("overall"), dict) else {}

    batter_vs_pitch_type = batter_profile.get("vs_pitch_type") if isinstance(batter_profile.get("vs_pitch_type"), dict) else {}
    if not batter_vs_pitch_type and isinstance(batter_feature.get("vs_pitch_type"), dict):
        batter_vs_pitch_type = batter_feature.get("vs_pitch_type")
    batter_vs_pitch_type_hr = batter_profile.get("vs_pitch_type_hr") if isinstance(batter_profile.get("vs_pitch_type_hr"), dict) else {}

    pitch_mix = pitcher_profile.get("arsenal") if isinstance(pitcher_profile.get("arsenal"), dict) else {}
    if not pitch_mix and isinstance(pitcher_profile.get("pitch_mix"), dict):
        pitch_mix = pitcher_profile.get("pitch_mix")
    if not pitch_mix and isinstance(pitcher_feature.get("pitch_mix"), dict):
        pitch_mix = pitcher_feature.get("pitch_mix")

    primary_pitch_type, primary_pitch_share = _primary_pitch_type(pitch_mix)
    pitch_type_hr_mult = pitcher_profile.get("pitch_type_hr_mult") if isinstance(pitcher_profile.get("pitch_type_hr_mult"), dict) else {}

    weighted_total = 0.0
    weight_sum = 0.0
    pitch_mix_breakdown: list[dict[str, Any]] = []
    for pitch_type, share_value in sorted(pitch_mix.items(), key=lambda item: _safe_float(item[1]) or 0.0, reverse=True):
        share = _safe_float(share_value)
        if share is None or share <= 0:
            continue
        batter_mult = _safe_float((batter_vs_pitch_type or {}).get(pitch_type))
        if batter_mult is None:
            batter_mult = 1.0
        weighted_total += share * batter_mult
        weight_sum += share
        pitch_mix_breakdown.append(
            {
                "pitch_type": str(pitch_type),
                "share": share,
                "batter_vs_pitch_type_mult": batter_mult,
            }
        )

    pitch_mix_score = weighted_total / weight_sum if weight_sum > 0 else None
    batter_primary_mult = _safe_float((batter_vs_pitch_type or {}).get(primary_pitch_type)) if primary_pitch_type else None
    batter_primary_hr_mult = _safe_float((batter_vs_pitch_type_hr or {}).get(primary_pitch_type)) if primary_pitch_type else None
    pitcher_primary_hr_mult = _safe_float((pitch_type_hr_mult or {}).get(primary_pitch_type)) if primary_pitch_type else None

    pitch_mix_reason = None
    if pitch_mix_score is not None and primary_pitch_type:
        if pitch_mix_score >= 1.04:
            pitch_mix_reason = (
                f"The starter leans on {primary_pitch_type}, and the full pitch mix grades well for this bat profile "
                f"({_format_num(pitch_mix_score)}x)."
            )
        elif pitch_mix_score <= 0.96:
            pitch_mix_reason = (
                f"The starter leans on {primary_pitch_type}, but the full pitch mix is a tougher fit for this bat profile "
                f"({_format_num(pitch_mix_score)}x)."
            )

    batter_launch_angle_mean = _safe_float(batter_overall.get("la_mean"))
    batter_hardhit_rate = _safe_float(batter_overall.get("hardhit_rate"))
    batter_barrel_rate = _safe_float(batter_overall.get("barrel_rate"))
    batter_xwoba = _safe_float(batter_overall.get("xwoba"))
    pitcher_launch_angle_mean = _safe_float(pitcher_overall.get("la_mean"))
    pitcher_hardhit_rate = _safe_float(pitcher_overall.get("hardhit_rate"))
    pitcher_barrel_rate = _safe_float(pitcher_overall.get("barrel_rate"))
    pitcher_xwoba_allowed = _safe_float(pitcher_overall.get("xwoba"))

    if batter_xwoba is not None and batter_xwoba >= 0.340:
        pitch_mix_reason = (
            f"{pitch_mix_reason} Batter xwOBA is strong at {_format_num(batter_xwoba)}."
            if pitch_mix_reason
            else f"Batter xwOBA is strong at {_format_num(batter_xwoba)}."
        )
    if batter_hardhit_rate is not None and batter_hardhit_rate >= 0.40:
        pitch_mix_reason = (
            f"{pitch_mix_reason} Hard-hit rate sits at {_format_pct(batter_hardhit_rate)}."
            if pitch_mix_reason
            else f"Hard-hit rate sits at {_format_pct(batter_hardhit_rate)}."
        )
    if batter_launch_angle_mean is not None:
        pitch_mix_reason = (
            f"{pitch_mix_reason} Launch angle averages {_format_num(batter_launch_angle_mean)} degrees."
            if pitch_mix_reason
            else f"Launch angle averages {_format_num(batter_launch_angle_mean)} degrees."
        )

    return {
        "opponent_pitch_mix": pitch_mix,
        "opponent_primary_pitch_type": primary_pitch_type,
        "opponent_primary_pitch_share": primary_pitch_share,
        "batter_vs_pitch_type": batter_vs_pitch_type,
        "batter_vs_pitch_type_hr": batter_vs_pitch_type_hr,
        "batter_vs_primary_pitch_type_mult": batter_primary_mult,
        "batter_vs_primary_pitch_type_hr_mult": batter_primary_hr_mult,
        "pitcher_primary_pitch_type_hr_mult": pitcher_primary_hr_mult,
        "batter_launch_angle_mean": batter_launch_angle_mean,
        "batter_hardhit_rate": batter_hardhit_rate,
        "batter_barrel_rate": batter_barrel_rate,
        "batter_xwoba": batter_xwoba,
        "pitcher_launch_angle_mean": pitcher_launch_angle_mean,
        "pitcher_hardhit_rate": pitcher_hardhit_rate,
        "pitcher_barrel_rate": pitcher_barrel_rate,
        "pitcher_xwoba_allowed": pitcher_xwoba_allowed,
        "pitch_mix_score": pitch_mix_score,
        "pitch_mix_breakdown": pitch_mix_breakdown,
        "pitch_mix_reason": pitch_mix_reason,
    }


def _apply_pitch_mix_context(selected_date: str, row: dict[str, Any]) -> dict[str, Any]:
    if not selected_date or not isinstance(row, dict):
        return row
    pitch_mix_context = _pitch_mix_context(selected_date, row)
    if not pitch_mix_context:
        return row
    enriched = dict(row)
    metrics = dict(enriched.get("hr_target_metrics") or {})
    metrics.update({k: v for k, v in pitch_mix_context.items() if k != "pitch_mix_reason"})
    enriched["hr_target_metrics"] = metrics
    if pitch_mix_context.get("pitch_mix_reason"):
        reasons = [str(item).strip() for item in (enriched.get("hr_target_reasons") or []) if str(item).strip()]
        if pitch_mix_context["pitch_mix_reason"] not in reasons:
            reasons.append(str(pitch_mix_context["pitch_mix_reason"]))
        enriched["hr_target_reasons"] = reasons
    for key, value in pitch_mix_context.items():
        if key == "pitch_mix_reason":
            continue
        enriched[key] = value
    return enriched


def _mlb_logo_url(team_id: int | None) -> str | None:
    if not team_id:
        return None
    return f"https://www.mlbstatic.com/team-logos/{int(team_id)}.svg"


def _mlb_headshot_url(player_id: int | None) -> str | None:
    if not player_id:
        return None
    return (
        "https://img.mlbstatic.com/mlb-photos/image/upload/"
        f"w_180,q_auto:best/v1/people/{int(player_id)}/headshot/67/current"
    )


def _support_score_display(score: float | None) -> str:
    if score is None:
        return "-"
    return "100+" if float(score) > 100.0 else f"{float(score):.1f}"


def _hr_target_driver_payload(row: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = row.get("hr_target_metrics") if isinstance(row.get("hr_target_metrics"), dict) else {}
    drivers: list[dict[str, Any]] = []

    def add_driver(*, label: str, value: Any, suffix: str = "", baseline: float | None = None) -> None:
        number = _safe_float(value)
        if number is None:
            return
        display = f"{number:.2f}{suffix}".rstrip("0").rstrip(".") + suffix
        payload: dict[str, Any] = {"label": label, "display": display}
        if baseline is not None:
            payload["delta"] = float(number - baseline)
        drivers.append(payload)

    add_driver(label="PA", value=metrics.get("paMean"), baseline=4.0)
    add_driver(label="Lineup", value=metrics.get("lineupOrder"), baseline=5.0)
    add_driver(label="Park HR", value=metrics.get("parkHr"), baseline=1.0)
    add_driver(label="Weather HR", value=metrics.get("weatherHr"), baseline=1.0)
    add_driver(label="Batter split", value=metrics.get("batterPlatoonHr"), baseline=1.0)
    add_driver(label="Pitcher split", value=metrics.get("pitcherPlatoonHr"), baseline=1.0)
    return drivers[:4]


def _sim_input_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    metrics = row.get("hr_target_metrics") if isinstance(row.get("hr_target_metrics"), dict) else {}
    if metrics:
        payload["hr_target_metrics"] = dict(metrics)
    return payload


def _hr_target_writeup(row: dict[str, Any]) -> str:
    summary = str(row.get("hr_target_summary") or "").strip()
    reasons = [str(item).strip() for item in (row.get("hr_target_reasons") or []) if str(item).strip()]
    if summary:
        return summary
    if reasons:
        return " ".join(reasons[:2])
    return "No summary available."


def _targets_from_summary(summary: dict[str, Any], *, selected_date: str = "", limit: int = 12) -> list[dict[str, Any]]:
    rows = summary.get("rows") if isinstance(summary.get("rows"), list) else []
    targets: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        source_row = _apply_pitch_mix_context(selected_date, dict(row))
        support_score = _safe_float(row.get("hr_support_raw_score"))
        if support_score is None:
            support_score = _safe_float(row.get("hr_support_score"))
        support_score_raw = _safe_float(row.get("hr_support_raw_score"))
        if support_score_raw is None:
            support_score_raw = support_score
        batter_id = _safe_int(row.get("batter_id"))
        team_id = _safe_int(row.get("team_id"))
        opponent_team_id = _safe_int(row.get("opponent_team_id"))
        game_pk = _safe_int(row.get("game_pk"))
        team = str(row.get("team") or "").strip() or "-"
        opponent = str(row.get("opponent") or "").strip() or "-"
        summary_text = _hr_target_writeup(row)
        player_name = str(row.get("player_name") or "").strip() or "Unknown hitter"
        target = dict(source_row)
        target.update(
            {
                "player_name": player_name,
                "team": team,
                "opponent": opponent,
                "matchup": str(row.get("matchup") or "").strip() or "-",
                "probability": _format_pct(row.get("p_hr_1plus")),
                "support": _format_num(support_score),
                "summary": summary_text,
                "reasons": [str(item).strip() for item in (row.get("hr_target_reasons") or []) if str(item).strip()][:3],
                "p_hr_1plus": _safe_float(row.get("p_hr_1plus")),
                "support_score": support_score,
                "support_score_raw": support_score_raw,
                "support_label": str(row.get("hr_support_label") or "").strip(),
                "support_score_display": _support_score_display(support_score_raw),
                "pa_mean": _safe_float(row.get("pa_mean")),
                "lineup_order": _safe_int(row.get("lineup_order")),
                "opponent_pitcher_name": str(row.get("opponent_pitcher_name") or "").strip(),
                "game_pk": game_pk,
                "batter_id": batter_id,
                "team_id": team_id,
                "opponent_team_id": opponent_team_id,
                "headshot_url": _mlb_headshot_url(batter_id),
                "team_logo_url": _mlb_logo_url(team_id),
                "opponent_logo_url": _mlb_logo_url(opponent_team_id),
                "drivers": _hr_target_driver_payload(row),
                "writeup": summary_text,
                "sim_inputs": _sim_input_payload(source_row),
                "source_row": source_row,
                "gamePk": game_pk,
                "batterId": batter_id,
                "playerName": player_name,
                "teamId": team_id,
                "opponentTeamId": opponent_team_id,
                "opponentPitcherName": str(row.get("opponent_pitcher_name") or "").strip(),
                "headshotUrl": _mlb_headshot_url(batter_id),
                "teamLogoUrl": _mlb_logo_url(team_id),
                "opponentLogoUrl": _mlb_logo_url(opponent_team_id),
                "lineupOrder": _safe_int(row.get("lineup_order")),
                "paMean": _safe_float(row.get("pa_mean")),
                "pHr1Plus": _safe_float(row.get("p_hr_1plus")),
                "supportScore": support_score,
                "supportScoreRaw": support_score_raw,
                "supportScoreDisplay": _support_score_display(support_score_raw),
                "supportLabel": str(row.get("hr_support_label") or "").strip(),
            }
        )
        targets.append(target)
    return targets


def _target_key(target: dict[str, Any]) -> str:
    player_name = str(target.get("player_name") or "").strip().lower()
    team = str(target.get("team") or "").strip().lower()
    matchup = str(target.get("matchup") or "").strip().lower()
    return "|".join((player_name, team, matchup))


def _summary_target_matchup(team: str, away_abbr: str, home_abbr: str) -> str:
    normalized_team = str(team or "").strip().upper()
    away = str(away_abbr or "").strip().upper()
    home = str(home_abbr or "").strip().upper()
    if normalized_team and normalized_team == away and home:
        return f"{away} @ {home}"
    if normalized_team and normalized_team == home and away:
        return f"{away} @ {home}"
    if away and home:
        return f"{away} @ {home}"
    return normalized_team or "-"


def _targets_from_daily_summary(summary: dict[str, Any], *, selected_date: str = "", limit: int = 24) -> list[dict[str, Any]]:
    outputs = summary.get("outputs") if isinstance(summary.get("outputs"), list) else []
    candidates: list[dict[str, Any]] = []
    for output in outputs:
        if not isinstance(output, dict):
            continue
        hr_block = output.get("hitter_hr_likelihood_all") if isinstance(output.get("hitter_hr_likelihood_all"), dict) else {}
        rows = hr_block.get("overall") if isinstance(hr_block.get("overall"), list) else []
        away_abbr = str(output.get("away") or "").strip().upper()
        home_abbr = str(output.get("home") or "").strip().upper()
        for row in rows:
            if not isinstance(row, dict):
                continue
            source_row = _apply_pitch_mix_context(selected_date, dict(row))
            player_name = str(row.get("name") or "").strip()
            team = str(row.get("team") or "").strip().upper()
            if not player_name or not team:
                continue
            probability_raw = row.get("p_hr_1plus_cal") if row.get("p_hr_1plus_cal") is not None else row.get("p_hr_1plus")
            try:
                probability_value = float(probability_raw)
            except Exception:
                continue
            lineup_order = row.get("lineup_order")
            pa_mean = row.get("pa_mean")
            hr_mean = row.get("hr_mean")
            reasons: list[str] = []
            if lineup_order is not None:
                reasons.append(f"Projected lineup spot: {lineup_order}.")
            if pa_mean is not None:
                reasons.append(f"Expected plate appearances: {_format_num(pa_mean)}.")
            if hr_mean is not None:
                reasons.append(f"Mean HR outcome: {_format_num(hr_mean)}.")
            support_score = _safe_float(hr_mean)
            summary_text = reasons[0] if reasons else "Derived from the daily HR-likelihood board."
            opponent = home_abbr if team == away_abbr else away_abbr if team == home_abbr else ""
            target = dict(source_row)
            target.update(
                {
                    "player_name": player_name,
                    "team": team,
                    "opponent": opponent,
                    "matchup": _summary_target_matchup(team, away_abbr, home_abbr),
                    "probability": _format_pct(probability_value),
                    "support": _format_num(hr_mean),
                    "summary": summary_text,
                    "reasons": reasons[:3],
                    "p_hr_1plus": probability_value,
                    "support_score": support_score,
                    "support_score_raw": support_score,
                    "support_label": "",
                    "support_score_display": _support_score_display(support_score),
                    "pa_mean": _safe_float(pa_mean),
                    "lineup_order": _safe_int(lineup_order),
                    "opponent_pitcher_name": "",
                    "game_pk": None,
                    "batter_id": None,
                    "team_id": None,
                    "opponent_team_id": None,
                    "headshot_url": None,
                    "team_logo_url": None,
                    "opponent_logo_url": None,
                    "drivers": [],
                    "writeup": summary_text,
                    "sim_inputs": _sim_input_payload(source_row),
                    "source_row": source_row,
                    "gamePk": None,
                    "batterId": None,
                    "playerName": player_name,
                    "teamId": None,
                    "opponentTeamId": None,
                    "opponentPitcherName": "",
                    "headshotUrl": None,
                    "teamLogoUrl": None,
                    "opponentLogoUrl": None,
                    "lineupOrder": _safe_int(lineup_order),
                    "paMean": _safe_float(pa_mean),
                    "pHr1Plus": probability_value,
                    "supportScore": support_score,
                    "supportScoreRaw": support_score,
                    "supportScoreDisplay": _support_score_display(support_score),
                    "supportLabel": "",
                    "_probability_sort": probability_value,
                }
            )
            candidates.append(target)
    candidates.sort(key=lambda item: float(item.get("_probability_sort") or 0.0), reverse=True)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = _target_key(candidate)
        if not key or key in seen:
            continue
        cleaned = dict(candidate)
        cleaned.pop("_probability_sort", None)
        merged.append(cleaned)
        seen.add(key)
        if len(merged) >= limit:
            break
    return merged


def _merge_targets(primary: list[dict[str, Any]], fallback: list[dict[str, Any]], *, limit: int = 24) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in (primary, fallback):
        for target in bucket:
            if not isinstance(target, dict):
                continue
            key = _target_key(target)
            if not key or key in seen:
                continue
            merged.append(dict(target))
            seen.add(key)
            if len(merged) >= limit:
                return merged
    return merged


def _cards_from_targets(targets: list[dict[str, Any]], *, selected_date: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for target in targets:
        game_pk = _safe_int(target.get("game_pk"))
        href = f"/mlb/hr-targets?date={selected_date}"
        if game_pk is not None:
            href = f"{href}&game={int(game_pk)}"
        cards.append(
            {
                "title": target["player_name"],
                "eyebrow": target["team"],
                "badge": target["probability"],
                "meta": target["matchup"],
                "metrics": [
                    {"label": "HR 1+", "value": target["probability"]},
                    {"label": "Support", "value": target["support"]},
                ],
                "summary": target["writeup"],
                "list_items": target["reasons"],
                "headshot_url": target.get("headshot_url"),
                "team_logo_url": target.get("team_logo_url"),
                "opponent_logo_url": target.get("opponent_logo_url"),
                "team": target.get("team"),
                "opponent": target.get("opponent"),
                "lineup_order": target.get("lineup_order"),
                "pa_mean": target.get("pa_mean"),
                "opponent_pitcher_name": target.get("opponent_pitcher_name"),
                "href": href,
                "href_label": "Open matchup view",
            }
        )
    return cards


def build_hr_targets_page_context(selected_date: str) -> dict[str, Any]:
    parsed_date = _parse_iso_date(selected_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()

    module_links = build_module_links(selected_date, "HR targets")

    summary_path = daily_artifact_path(selected_date, suffix="_hr_targets")
    summary = load_json_file(summary_path)
    daily_summary_path = daily_artifact_path(selected_date)
    daily_summary = load_json_file(daily_summary_path)
    summary_targets = _targets_from_summary(summary, selected_date=selected_date, limit=24) if summary else []
    daily_targets = _targets_from_daily_summary(daily_summary, selected_date=selected_date, limit=24) if daily_summary else []
    if summary_targets:
        # Keep dedicated HR-target rows first, but backfill from daily summary when sparse.
        targets = _merge_targets(summary_targets, daily_targets, limit=24)
    else:
        targets = daily_targets
    using_sample_data = False

    header_stats = [
        {"label": "Rows", "value": str(len(targets))},
        {"label": "Policy", "value": str(((summary or {}).get("policy") or {}).get("label") or "Fallback")},
    ]

    return {
        "date": selected_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "module_links": module_links,
        "targets": targets,
        "cards": _cards_from_targets(targets, selected_date=selected_date),
        "rank_cards": _cards_from_targets(targets, selected_date=selected_date),
        "source_path": str(summary_path),
        "using_sample_data": using_sample_data,
        "source_title": "MLB HR targets artifact" if targets else "MLB HR targets unavailable",
        "header_stats": header_stats,
        "route_path": "/mlb/hr-targets",
        "intro_title": "MLB HR targets",
        "intro_body": "This is the second real MLB module inside Syndicate, backed by the existing HR targets artifact and reusing shared layout blocks.",
        "aria_label": "HR target board",
        "empty_state": {
            "eyebrow": "MLB HR targets",
            "title": "No stored MLB HR targets were available for this date",
            "body": "The HR targets board only renders saved HR-target artifacts, and none were available for the requested date.",
            "list_items": ["Choose another stored MLB date from the date control."],
        } if not targets else None,
    }