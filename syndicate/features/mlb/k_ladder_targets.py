from __future__ import annotations

from datetime import date
from datetime import datetime, timedelta
from typing import Any

from syndicate.features.mlb.ladders_common import build_module_links
from syndicate.features.mlb.sources import daily_artifact_path
from syndicate.features.mlb.sources import load_json_file
from syndicate.features.shared.timezone import central_today


def _parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return central_today()


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


def _k_target_writeup(row: dict[str, Any]) -> str:
    summary = str(row.get("k_target_summary") or "").strip()
    reasons = [str(item).strip() for item in (row.get("k_target_reasons") or []) if str(item).strip()]
    if summary:
        return summary
    if reasons:
        return " ".join(reasons[:2])
    return "No summary available."


def _k_target_summary_stats(row: dict[str, Any]) -> list[dict[str, str]]:
    stats: list[dict[str, str]] = []
    p_over = _safe_float(row.get("p_so_over"))
    if p_over is not None:
        stats.append({"label": "P(over)", "value": _format_pct(p_over)})
    edge = _safe_float(row.get("edge"))
    if edge is not None:
        stats.append({"label": "Edge", "value": f"{edge * 100.0:+.1f}pt"})
    so_mean = _safe_float(row.get("so_mean"))
    if so_mean is not None:
        stats.append({"label": "Model mean", "value": _format_num(so_mean)})
    line = _safe_float(row.get("market_line"))
    if line is not None:
        stats.append({"label": "Line", "value": _format_num(line)})
    return stats


def _k_target_context_table(row: dict[str, Any]) -> list[dict[str, Any]]:
    market_rows: list[dict[str, str]] = []
    odds = row.get("odds")
    if odds is not None:
        market_rows.append({"name": "Over price", "detail": "", "value": str(odds)})
    market_prob = _safe_float(row.get("market_prob_over"))
    if market_prob is not None:
        market_rows.append({"name": "Market no-vig", "detail": "P(over)", "value": _format_pct(market_prob)})

    groups: list[dict[str, Any]] = []
    if market_rows:
        groups.append({"heading": "Market", "rows": market_rows})
    return groups


def _targets_from_summary(summary: dict[str, Any], *, selected_date: str = "", limit: int = 24) -> list[dict[str, Any]]:
    rows = summary.get("rows") if isinstance(summary.get("rows"), list) else []
    targets: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        support_score = _safe_float(row.get("k_support_score"))
        pitcher_id = _safe_int(row.get("pitcher_id"))
        team_id = _safe_int(row.get("team_id") or row.get("opponent_team_id"))
        opponent_team_id = _safe_int(row.get("opponent_team_id"))
        game_pk = _safe_int(row.get("game_pk"))
        team = str(row.get("team") or "").strip() or "-"
        opponent = str(row.get("opponent") or "").strip() or "-"
        pitcher_name = str(row.get("pitcher_name") or "").strip() or "Unknown pitcher"
        summary_text = _k_target_writeup(row)
        target = dict(row)
        target.update(
            {
                "pitcher_name": pitcher_name,
                "team": team,
                "opponent": opponent,
                "matchup": str(row.get("matchup") or "").strip() or "-",
                "probability": _format_pct(row.get("p_so_over")),
                "support": _format_num(support_score),
                "support_score": support_score,
                "support_label": str(row.get("k_support_label") or "").strip(),
                "summary": summary_text,
                "reasons": [str(item).strip() for item in (row.get("k_target_reasons") or []) if str(item).strip()][:4],
                "market_line": _safe_float(row.get("market_line")),
                "edge": _safe_float(row.get("edge")),
                "so_mean": _safe_float(row.get("so_mean")),
                "game_pk": game_pk,
                "pitcher_id": pitcher_id,
                "team_id": team_id,
                "opponent_team_id": opponent_team_id,
                "headshot_url": _mlb_headshot_url(pitcher_id),
                "team_logo_url": _mlb_logo_url(team_id),
                "opponent_logo_url": _mlb_logo_url(opponent_team_id),
                "writeup": summary_text,
                "source_row": row,
            }
        )
        targets.append(target)
    return targets


def _cards_from_targets(targets: list[dict[str, Any]], *, selected_date: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for target in targets:
        game_pk = target.get("game_pk")
        href = f"/mlb/k-ladder-targets?date={selected_date}"
        if game_pk is not None:
            href = f"{href}&game={int(game_pk)}"
        support_display = target.get("support") or "-"
        support_label = str(target.get("support_label") or "").strip()
        if support_label:
            support_display = f"{support_display} ({support_label})"
        line = target.get("market_line")
        badge = target["probability"]
        if line is not None:
            badge = f"O {_format_num(line)} | {badge}"
        cards.append(
            {
                "title": target["pitcher_name"],
                "eyebrow": target["team"],
                "badge": badge,
                "meta": target["matchup"],
                "metrics": [
                    {"label": "P(over)", "value": target["probability"]},
                    {"label": "Support", "value": support_display},
                    {"label": "Line", "value": _format_num(line) if line is not None else "-"},
                ],
                "summary": target["writeup"],
                "list_items": target["reasons"],
                "summary_stats": _k_target_summary_stats(target.get("source_row") or {}),
                "table_groups": _k_target_context_table(target.get("source_row") or {}),
                "headshot_url": target.get("headshot_url"),
                "team_logo_url": target.get("team_logo_url"),
                "opponent_logo_url": target.get("opponent_logo_url"),
                "team": target.get("team"),
                "opponent": target.get("opponent"),
                "href": href,
                "href_label": "Open matchup view",
            }
        )
    return cards


def build_k_ladder_targets_page_context(selected_date: str) -> dict[str, Any]:
    parsed_date = _parse_iso_date(selected_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()

    module_links = build_module_links(selected_date, "K ladder targets")

    summary_path = daily_artifact_path(selected_date, suffix="_k_targets")
    summary = load_json_file(summary_path)
    targets = _targets_from_summary(summary, selected_date=selected_date, limit=24) if summary else []
    using_sample_data = False

    header_stats = [
        {"label": "Rows", "value": str(len(targets))},
        {"label": "Policy", "value": str(((summary or {}).get("policy") or {}).get("label") or "Saved artifact")},
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
        "source_title": "MLB K ladder targets artifact" if targets else "MLB K ladder targets unavailable",
        "header_stats": header_stats,
        "route_path": "/mlb/k-ladder-targets",
        "intro_title": "MLB K ladder targets",
        "intro_body": "Starting pitchers ranked by modeled probability of clearing their strikeout line, using the same sim distribution and matchup context (BvP, pitch mix, opposing-lineup composition, workload) that drives the pitcher-props recommendation engine.",
        "aria_label": "K ladder target board",
        "empty_state": {
            "eyebrow": "MLB K ladder targets",
            "title": "No stored MLB K ladder targets were available for this date",
            "body": "The K ladder board only renders saved K-target artifacts, and none were available for the requested date.",
            "list_items": ["Choose another stored MLB date from the date control."],
        } if not targets else None,
    }
