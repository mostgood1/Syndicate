from __future__ import annotations

from typing import Any
from typing import Callable


def _analysis_brief_driver_items(
    recommendation: dict[str, Any],
    analysis_views: dict[str, Any] | None,
    *,
    safe_text: Callable[[Any, str], str],
    humanize_signal_key: Callable[[str], str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for signal in (recommendation.get("advanced_signals") or [])[:4]:
        if not isinstance(signal, dict):
            continue
        label = safe_text(signal.get("label"), "Advanced signal")
        value = signal.get("value")
        if label in seen or value in {None, ""}:
            continue
        seen.add(label)
        if isinstance(value, (int, float)):
            detail = f"{float(value):.2f}".rstrip("0").rstrip(".")
        else:
            detail = safe_text(value, "-")
        items.append({"label": label, "detail": detail})

    if items:
        return items

    chart = analysis_views.get("chart") if isinstance(analysis_views, dict) and isinstance(analysis_views.get("chart"), dict) else {}
    chart_rows = chart.get("rows") if isinstance(chart.get("rows"), list) else []
    chart_series = chart.get("series") if isinstance(chart.get("series"), list) else []
    first_row = chart_rows[0] if chart_rows and isinstance(chart_rows[0], dict) else {}
    for key in chart_series[:4]:
        if key in {"score", "market_fit_score", "advanced_signal_score", "source_summary_score"}:
            continue
        value = first_row.get(key)
        if value in {None, ""}:
            continue
        label = humanize_signal_key(key)
        if label in seen:
            continue
        seen.add(label)
        if isinstance(value, (int, float)):
            detail = f"{float(value):.2f}".rstrip("0").rstrip(".")
        else:
            detail = safe_text(value, "-")
        items.append({"label": label, "detail": detail})
    return items


def _analysis_brief_primary_row(
    recommendation: dict[str, Any],
    analysis_views: dict[str, Any] | None,
    *,
    safe_text: Callable[[Any, str], str],
) -> dict[str, Any]:
    table = analysis_views.get("table") if isinstance(analysis_views, dict) and isinstance(analysis_views.get("table"), dict) else {}
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    if not rows:
        return {}
    target_label = safe_text(recommendation.get("name") or recommendation.get("pick"), "")
    if target_label:
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_label = safe_text(row.get("label") or row.get("player") or row.get("name"), "")
            if row_label == target_label:
                return row
    first_row = rows[0]
    return first_row if isinstance(first_row, dict) else {}


def _brief_detail_text(value: Any, *, suffix: str = "", safe_text: Callable[[Any, str], str]) -> str | None:
    if value in {None, "", "-"}:
        return None
    if isinstance(value, (int, float)):
        text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    else:
        text = safe_text(value, "")
    if not text:
        return None
    return f"{text}{suffix}" if suffix else text


def _analysis_brief_focus_sections(
    recommendation: dict[str, Any],
    analysis_views: dict[str, Any] | None,
    *,
    safe_text: Callable[[Any, str], str],
) -> list[dict[str, Any]]:
    focus = safe_text((analysis_views or {}).get("focus"), "").lower()
    row = _analysis_brief_primary_row(recommendation, analysis_views, safe_text=safe_text)
    sections: list[dict[str, Any]] = []

    def add_section(title: str, raw_items: list[tuple[str, Any, str]]) -> None:
        items = []
        for label, value, suffix in raw_items:
            detail = _brief_detail_text(value, suffix=suffix, safe_text=safe_text)
            if detail is None:
                continue
            items.append({"label": label, "detail": detail})
        if items:
            sections.append({"kind": "list", "title": title, "items": items})

    if focus == "mlb_props":
        add_section(
            "Pitch and contact context",
            [
                ("Pitcher K mult", row.get("pitcher_k_mult"), "x"),
                ("Batter K mult", row.get("batter_k_mult"), "x"),
                ("Batter in-play mult", row.get("batter_inplay_mult"), "x"),
                ("Pitcher in-play mult", row.get("pitcher_inplay_mult"), "x"),
                ("Batter EV", row.get("batter_ev_mean"), " mph"),
                ("Hard-hit rate", row.get("batter_hardhit_rate"), "%"),
                ("Batter xwOBA", row.get("batter_xwoba"), ""),
                ("Pitcher xwOBA allowed", row.get("pitcher_xwoba_allowed"), ""),
                ("Pitch mix", row.get("pitch_mix"), ""),
            ],
        )
    elif focus in {"nba_matchups", "wnba_matchups", "ncaab_matchups"}:
        title = "Matchup environment"
        if focus == "wnba_matchups":
            add_section(
                title,
                [
                    ("Team environment", row.get("team_environment_signal"), "x"),
                    ("Possession profile", row.get("possession_profile_signal"), "x"),
                    ("Matchup pressure", row.get("matchup_pressure_signal"), "x"),
                    ("Rotation pressure", row.get("rotation_pressure_signal"), "x"),
                    ("Live shift", row.get("live_shift_signal"), "x"),
                ],
            )
        elif focus == "ncaab_matchups":
            add_section(
                title,
                [
                    ("Tempo bucket", row.get("tempo_bucket_signal"), "x"),
                    ("Volatility", row.get("volatility_signal"), "x"),
                    ("Role signal", row.get("role_signal"), "x"),
                ],
            )
        else:
            add_section(
                title,
                [
                    ("Pace", row.get("pace_signal"), "x"),
                    ("Usage", row.get("usage_signal"), "x"),
                    ("Shot profile", row.get("shot_profile_signal"), "x"),
                    ("Role", row.get("role_signal"), "x"),
                ],
            )
        add_section(
            "Recent form pressure",
            [
                ("Last 5 average", row.get("last5_average"), ""),
                ("Last 10 average", row.get("last10_average"), ""),
                ("Last game", row.get("last_game_value"), ""),
                ("Projected minutes", row.get("projected_minutes"), ""),
                ("Last-10 workload", row.get("last10_workload"), ""),
                ("Last 5 delta", row.get("last5_delta_signal"), "x"),
                ("Last 10 delta", row.get("last10_delta_signal"), "x"),
                ("Workload delta", row.get("workload_delta_signal"), "x"),
            ],
        )
    elif focus == "football_markets":
        add_section(
            "Game script context",
            [
                ("Offensive EPA", row.get("off_epa_signal"), "x"),
                ("Target share", row.get("target_share_signal"), ""),
                ("Pass rate", row.get("pass_rate_signal"), "x"),
                ("Air yards", row.get("air_yards_signal"), "x"),
                ("Implied probability", row.get("implied_probability"), "%"),
            ],
        )
    elif focus == "hockey_props":
        add_section(
            "Shot and market context",
            [
                ("Live projection", recommendation.get("live_projection"), ""),
                ("Projection", recommendation.get("projected"), ""),
                ("Line", recommendation.get("line"), ""),
                ("Price edge", recommendation.get("price_edge_pct"), "%"),
                ("Market fit", recommendation.get("market_fit_score"), ""),
                ("Implied probability", recommendation.get("implied_probability"), "%"),
            ],
        )
    elif focus == "mlb_home_runs":
        add_section(
            "Power context",
            [
                ("Batter EV", row.get("batter_ev_mean"), " mph"),
                ("Hard-hit rate", row.get("batter_hardhit_rate"), "%"),
                ("Pitcher HR/BIP allowed", row.get("pitcher_hr_per_bip_allowed"), "%"),
                ("Pitcher xwOBA allowed", row.get("pitcher_xwoba_allowed"), ""),
                ("Pitch mix", row.get("pitch_mix"), ""),
            ],
        )
    return sections


def build_analysis_brief(
    recommendations: list[dict[str, Any]],
    analysis_views: dict[str, Any] | None,
    supporting_evidence: dict[str, Any] | None,
    *,
    preferences: dict[str, Any],
    safe_text: Callable[[Any, str], str],
    humanize_signal_key: Callable[[str], str],
) -> dict[str, Any] | None:
    if not recommendations:
        return None

    top = recommendations[0] if isinstance(recommendations[0], dict) else {}
    if not top:
        return None

    sections: list[dict[str, Any]] = []
    matchup_bits = []
    target_name = safe_text(top.get("name") or top.get("pick"), "Top target")
    matchup = safe_text(top.get("matchup"), "")
    market = safe_text(top.get("market") or top.get("market_label"), "")
    if matchup:
        matchup_bits.append(f"{target_name} is being evaluated in {matchup}.")
    else:
        matchup_bits.append(f"{target_name} is the lead returned target on the board.")
    if market:
        matchup_bits.append(f"The current angle is {market.lower()} with {safe_text(top.get('pick'), target_name)}.")

    projected = top.get("live_projection") if top.get("is_live") and safe_text(top.get("live_projection"), "") not in {"", "-"} else top.get("projected")
    line = top.get("line")
    if safe_text(projected, "") not in {"", "-"} and safe_text(line, "") not in {"", "-"}:
        projection_label = "Live projection" if top.get("is_live") and safe_text(top.get("live_projection"), "") not in {"", "-"} else "Projection"
        matchup_bits.append(f"{projection_label} is {projected} against a listed line of {line}.")
    if safe_text(top.get("odds"), "") not in {"", "-"}:
        matchup_bits.append(f"Available odds are {top.get('odds')} with {safe_text(top.get('confidence'), 'model confidence')} on the returned side.")
    rationale = safe_text(top.get("rationale"), "")
    if rationale:
        matchup_bits.append(rationale)
    sections.append({"kind": "narrative", "title": "Matchup case", "body": " ".join(bit for bit in matchup_bits if bit)})

    driver_items = _analysis_brief_driver_items(
        top,
        analysis_views,
        safe_text=safe_text,
        humanize_signal_key=humanize_signal_key,
    )
    if driver_items:
        sections.append({"kind": "list", "title": "Advanced drivers", "items": driver_items})

    sections.extend(_analysis_brief_focus_sections(top, analysis_views, safe_text=safe_text))

    input_items = [
        {
            "label": safe_text(item.get("label"), "Tracked input"),
            "detail": ", ".join(str(metric).strip() for metric in (item.get("metrics") or [])[:4] if str(metric).strip()) or "Tracked input",
        }
        for item in (top.get("advanced_inputs") or [])
        if isinstance(item, dict)
    ]
    pbp_items = [
        item
        for item in input_items
        if any(
            token in f"{safe_text(item.get('label'), '').lower()} {safe_text(item.get('detail'), '').lower()}"
            for token in ("play-by-play", "pbp", "live recap", "sequence", "shift", "scoring run", "points per possession")
        )
    ]
    if pbp_items:
        sections.append({"kind": "list", "title": "Play-by-play context", "items": pbp_items})
    elif input_items:
        sections.append({"kind": "list", "title": "Data inputs", "items": input_items[:4]})

    risk_items: list[dict[str, Any]] = []
    state_note = safe_text(top.get("state_note"), "")
    if state_note:
        risk_items.append({"label": "Live state", "detail": state_note})
    for item in (top.get("missing_advanced_inputs") or [])[:3]:
        if not isinstance(item, dict):
            continue
        risk_items.append(
            {
                "label": safe_text(item.get("label"), "Missing input"),
                "detail": safe_text(item.get("missing_reason"), "Missing or unpublished"),
            }
        )
    if not risk_items:
        notes_sections = (supporting_evidence or {}).get("sections") if isinstance(supporting_evidence, dict) else []
        if isinstance(notes_sections, list):
            source_section = next((section for section in notes_sections if isinstance(section, dict) and section.get("kind") == "sources"), None)
            if isinstance(source_section, dict) and (source_section.get("items") or []):
                risk_items.append({"label": "Coverage", "detail": "Advanced inputs are available for the returned read."})
    if risk_items:
        sections.append({"kind": "list", "title": "Watchouts", "items": risk_items})

    if not sections:
        return None

    focus = safe_text((analysis_views or {}).get("focus"), "")
    title = "Returned analysis brief"
    if focus:
        title = f"{humanize_signal_key(focus)} brief"
    elif preferences.get("requested_subjects"):
        title = f"{' / '.join(str(item).title() for item in (preferences.get('requested_subjects') or [])[:2])} brief"

    return {
        "title": title,
        "focus": focus or None,
        "sections": sections,
    }