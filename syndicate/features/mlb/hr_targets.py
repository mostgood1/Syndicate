from __future__ import annotations

from datetime import date
from datetime import datetime, timedelta
from typing import Any

from syndicate.features.mlb.ladders_common import build_module_links
from syndicate.features.mlb.sources import daily_artifact_path
from syndicate.features.mlb.sources import load_json_file


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


def _hr_target_writeup(row: dict[str, Any]) -> str:
    summary = str(row.get("hr_target_summary") or "").strip()
    reasons = [str(item).strip() for item in (row.get("hr_target_reasons") or []) if str(item).strip()]
    if summary:
        return summary
    if reasons:
        return " ".join(reasons[:2])
    return "No summary available."


def _targets_from_summary(summary: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    rows = summary.get("rows") if isinstance(summary.get("rows"), list) else []
    targets: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        support_score = _safe_float(row.get("hr_support_raw_score"))
        if support_score is None:
            support_score = _safe_float(row.get("hr_support_score"))
        batter_id = _safe_int(row.get("batter_id"))
        team_id = _safe_int(row.get("team_id"))
        opponent_team_id = _safe_int(row.get("opponent_team_id"))
        team = str(row.get("team") or "").strip() or "-"
        opponent = str(row.get("opponent") or "").strip() or "-"
        summary_text = _hr_target_writeup(row)
        targets.append(
            {
                "player_name": str(row.get("player_name") or "").strip() or "Unknown hitter",
                "team": team,
                "opponent": opponent,
                "matchup": str(row.get("matchup") or "").strip() or "-",
                "probability": _format_pct(row.get("p_hr_1plus")),
                "support": _format_num(support_score),
                "summary": summary_text,
                "reasons": [str(item).strip() for item in (row.get("hr_target_reasons") or []) if str(item).strip()][:3],
                "p_hr_1plus": _safe_float(row.get("p_hr_1plus")),
                "support_score": support_score,
                "support_label": str(row.get("hr_support_label") or "").strip(),
                "support_score_display": _support_score_display(support_score),
                "pa_mean": _safe_float(row.get("pa_mean")),
                "lineup_order": _safe_int(row.get("lineup_order")),
                "opponent_pitcher_name": str(row.get("opponent_pitcher_name") or "").strip(),
                "game_pk": _safe_int(row.get("game_pk")),
                "batter_id": batter_id,
                "team_id": team_id,
                "opponent_team_id": opponent_team_id,
                "headshot_url": _mlb_headshot_url(batter_id),
                "team_logo_url": _mlb_logo_url(team_id),
                "opponent_logo_url": _mlb_logo_url(opponent_team_id),
                "drivers": _hr_target_driver_payload(row),
                "writeup": summary_text,
            }
        )
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


def _targets_from_daily_summary(summary: dict[str, Any], *, limit: int = 24) -> list[dict[str, Any]]:
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
            candidates.append(
                {
                    "player_name": player_name,
                    "team": team,
                    "opponent": home_abbr if team == away_abbr else away_abbr if team == home_abbr else "",
                    "matchup": _summary_target_matchup(team, away_abbr, home_abbr),
                    "probability": _format_pct(probability_value),
                    "support": _format_num(hr_mean),
                    "summary": reasons[0] if reasons else "Derived from the daily HR-likelihood board.",
                    "reasons": reasons[:3],
                    "p_hr_1plus": probability_value,
                    "support_score": _safe_float(hr_mean),
                    "support_label": "",
                    "support_score_display": _support_score_display(_safe_float(hr_mean)),
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
                    "writeup": reasons[0] if reasons else "Derived from the daily HR-likelihood board.",
                    "_probability_sort": probability_value,
                }
            )
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
    targets = _merge_targets(
        _targets_from_summary(summary, limit=24) if summary else [],
        _targets_from_daily_summary(daily_summary, limit=24) if daily_summary else [],
        limit=24,
    )
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