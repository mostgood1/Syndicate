from __future__ import annotations

from datetime import date
from datetime import datetime, timedelta
from typing import Any

from syndicate.features.mlb.ladders_common import build_module_links
from syndicate.features.mlb.sources import daily_rfi_targets_path
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


def _cards_from_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for signal in signals:
        cards.append(
            {
                "title": signal["title"],
                "eyebrow": signal["tone"],
                "badge": signal["nrfi_prob"] if signal["tone"] == "F1 NRFI" else signal["yrfi_prob"],
                "meta": signal["matchup"],
                "metrics": [
                    {"label": "NRFI", "value": signal["nrfi_prob"]},
                    {"label": "YRFI", "value": signal["yrfi_prob"]},
                    {"label": "F1 runs", "value": signal["mean_runs"]},
                    {"label": "Side lead", "value": signal["lead_prob"]},
                ],
                "summary": signal["summary"],
                "list_items": [signal["detail"]],
            }
        )
    return cards


def _signals_from_summary(summary: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    rows = summary.get("signals") if isinstance(summary.get("signals"), list) else []
    signals: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        signal = row.get("signal") if isinstance(row.get("signal"), dict) else {}
        starters = row.get("starter_names") if isinstance(row.get("starter_names"), dict) else {}
        away_abbr = str(row.get("away_abbr") or "").strip() or "AWY"
        home_abbr = str(row.get("home_abbr") or "").strip() or "HOM"
        signals.append(
            {
                "title": f"{away_abbr} @ {home_abbr}",
                "tone": str(signal.get("label") or "F1 signal").strip() or "F1 signal",
                "matchup": f"{str(starters.get('away') or 'TBD').strip() or 'TBD'} vs {str(starters.get('home') or 'TBD').strip() or 'TBD'}",
                "summary": str(signal.get("summary") or "No summary available.").strip() or "No summary available.",
                "detail": str(signal.get("detail") or "").strip() or "No detail available.",
                "nrfi_prob": _format_pct(signal.get("nrfiProb")),
                "yrfi_prob": _format_pct(signal.get("yrfiProb")),
                "mean_runs": _format_num(signal.get("meanTotalRuns")),
                "lead_prob": _format_pct(signal.get("maxSideLeadProb")),
            }
        )
    return signals


def build_rfi_targets_page_context(selected_date: str) -> dict[str, Any]:
    parsed_date = _parse_iso_date(selected_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()

    module_links = build_module_links(selected_date, "RFI targets")

    summary_path = daily_rfi_targets_path(selected_date)
    summary = load_json_file(summary_path)
    signals = _signals_from_summary(summary) if summary else []
    using_sample_data = False

    return {
        "date": selected_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "module_links": module_links,
        "signals": signals,
        "cards": _cards_from_signals(signals),
        "rank_cards": _cards_from_signals(signals),
        "source_path": str(summary_path),
        "using_sample_data": using_sample_data,
        "source_title": "MLB RFI targets artifact" if signals else "MLB RFI targets unavailable",
        "header_stats": [
            {"label": "Signals", "value": str(len(signals))},
            {"label": "Locked", "value": "Yes" if (summary or {}).get("locked") else "No"},
            {"label": "Profile", "value": str((summary or {}).get("source_profile") or "Fallback")},
        ],
        "route_path": "/mlb/rfi-targets",
        "intro_title": "MLB RFI targets",
        "intro_body": "This module reuses the shared target-board layout for first-inning scoring signals from the daily RFI artifact.",
        "aria_label": "RFI target board",
        "empty_state": {
            "eyebrow": "MLB RFI targets",
            "title": "No stored MLB first-inning targets were available for this date",
            "body": "The RFI targets board only renders saved first-inning target artifacts, and none were available for the requested date.",
            "list_items": ["Choose another stored MLB date from the date control."],
        } if not signals else None,
    }