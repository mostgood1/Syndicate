from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "data"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass(frozen=True)
class LeaderboardRow:
    label: str
    matchup: str
    market: str
    selection: str
    expected_value: float | None
    confidence: float | None
    historical_context: Mapping[str, Any]
    raw: Mapping[str, Any]
    source_path: str


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        converted = value.to_dict()
        if isinstance(converted, Mapping):
            return converted
    return {}


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_value(value: Any, *, digits: int = 2) -> str:
    number = _coerce_float(value)
    if number is None:
        return "n/a"
    return f"{number:.{digits}f}"


def _format_historical_context(context: Mapping[str, Any]) -> str:
    roi_segment = _coerce_float(context.get("roi_segment"))
    sample_size = context.get("sample_size")
    roi_text = f"{roi_segment:+.3f}" if roi_segment is not None else "n/a"
    sample_text = str(sample_size) if sample_size is not None else "n/a"
    return f"roi_segment={roi_text}, sample_size={sample_text}"


def _latest_local_recommendation_source() -> tuple[Path | None, str | None, str | None]:
    recommendation_files = sorted(
        SOURCE_ROOT.glob("*_source/api/recommendations/recommendations_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not recommendation_files:
        return None, None, None
    latest_path = recommendation_files[0]
    try:
        relative_path = latest_path.relative_to(REPO_ROOT)
    except ValueError:
        relative_path = latest_path
    sport = None
    if len(relative_path.parts) >= 2 and relative_path.parts[0] == "data" and relative_path.parts[1].endswith("_source"):
        sport = relative_path.parts[1][:-7]
    filename_match = re.search(r"recommendations_(\d{4}-\d{2}-\d{2})\.json$", latest_path.name)
    date_text = filename_match.group(1) if filename_match else None
    return latest_path, date_text, sport


def _row_from_recommendation(item: Mapping[str, Any]) -> LeaderboardRow:
    historical_context = item.get("historical_context") if isinstance(item.get("historical_context"), Mapping) else {}
    return LeaderboardRow(
        label=str(item.get("label") or item.get("name") or item.get("selection") or "Recommendation"),
        matchup=str(item.get("matchup") or "-"),
        market=str(item.get("market") or item.get("market_label") or "-"),
        selection=str(item.get("selection") or item.get("pick") or "-"),
        expected_value=_coerce_float(item.get("expected_value")),
        confidence=_coerce_float(item.get("confidence")),
        historical_context=historical_context,
        raw=item,
        source_path=str(item.get("source_path") or item.get("basketball_source") or item.get("basketball_source_path") or ""),
    )


def _print_board(title: str, rows: list[LeaderboardRow], *, metric_label: str) -> None:
    print()
    print(title)
    print("-" * len(title))
    if not rows:
        print("No recommendations found.")
        return
    for index, row in enumerate(rows[:5], start=1):
        print(
            f"{index}. {row.label} | {row.matchup} | {row.market} | {row.selection} | "
            f"expected_value={_format_value(row.expected_value)} | confidence={_format_value(row.confidence)} | "
            f"historical_context={_format_historical_context(row.historical_context)}"
        )


def _extract_recommendations(response: Any) -> list[Mapping[str, Any]]:
    payload = _as_mapping(response)
    recommendations = payload.get("recommendations")
    if not isinstance(recommendations, list):
        recommendations = _as_mapping(payload.get("data")).get("recommendations") if isinstance(payload.get("data"), Mapping) else []
    if not isinstance(recommendations, list):
        return []
    return [item for item in recommendations if isinstance(item, Mapping)]


def _load_recommendation_snapshot(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("data") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _enrich_snapshot_rows(rows: list[dict[str, Any]], *, sport: str | None) -> list[LeaderboardRow]:
    from syndicate.features.shared.recommendation_engine import build_recommendation_output

    enriched_rows: list[LeaderboardRow] = []
    for row in rows:
        enriched = build_recommendation_output(row, sport=sport)
        historical_context = enriched.get("historical_context") if isinstance(enriched.get("historical_context"), Mapping) else {}
        enriched_rows.append(
            LeaderboardRow(
                label=str(enriched.get("label") or enriched.get("name") or enriched.get("selection") or "Recommendation"),
                matchup=str(enriched.get("matchup") or enriched.get("away_team") or enriched.get("home_team") or "-"),
                market=str(enriched.get("market") or enriched.get("market_label") or "-"),
                selection=str(enriched.get("selection") or enriched.get("pick") or "-"),
                expected_value=_coerce_float(enriched.get("expected_value")),
                confidence=_coerce_float(enriched.get("confidence")),
                historical_context=historical_context,
                raw=enriched,
                source_path=str(enriched.get("source_path") or enriched.get("basketball_source") or ""),
            )
        )
    return enriched_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Print validation leaderboards for current Syndicate recommendations.")
    parser.add_argument("--date", default="", help="Selected date to load, defaults to today in Central time.")
    args = parser.parse_args()

    source_path, selected_date, latest_sport = _latest_local_recommendation_source()
    if source_path is None:
        print("No local recommendation snapshot found.")
        return 1
    selected_date = args.date.strip() or selected_date or "unknown"
    recommendations = _enrich_snapshot_rows(_load_recommendation_snapshot(source_path), sport=latest_sport)

    by_ev = sorted(
        (row for row in recommendations if row.expected_value is not None),
        key=lambda row: row.expected_value if row.expected_value is not None else float("-inf"),
        reverse=True,
    )
    by_confidence = sorted(
        (row for row in recommendations if row.confidence is not None),
        key=lambda row: row.confidence if row.confidence is not None else float("-inf"),
        reverse=True,
    )
    by_historical_roi = sorted(
        (row for row in recommendations if _coerce_float(row.historical_context.get("roi_segment")) is not None),
        key=lambda row: _coerce_float(row.historical_context.get("roi_segment")) if _coerce_float(row.historical_context.get("roi_segment")) is not None else float("-inf"),
        reverse=True,
    )

    print(f"Source: {source_path.relative_to(REPO_ROOT) if source_path.is_relative_to(REPO_ROOT) else source_path}")
    print(f"Selected date: {selected_date}")
    if latest_sport:
        print(f"Sport: {latest_sport}")
    print(f"Loaded recommendations: {len(recommendations)}")
    _print_board("Top recommendations by EV", by_ev, metric_label="expected_value")
    _print_board("Top recommendations by confidence", by_confidence, metric_label="confidence")
    _print_board("Top recommendations by historical ROI", by_historical_roi, metric_label="historical_context")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())