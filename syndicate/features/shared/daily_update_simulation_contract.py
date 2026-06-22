from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from syndicate.features.ncaaf.sources import default_week as ncaaf_default_week
from syndicate.features.nfl.sources import default_week as nfl_default_week
from syndicate.features.shared.simulation_adapter import build_unified_simulation_adapter


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _default_selection_for_sport(sport: str, *, date_value: str, season: int | None = None) -> Any:
    sport_key = _safe_text(sport, "").lower()
    if sport_key in {"nfl", "ncaaf"}:
        return nfl_default_week(season) if sport_key == "nfl" else ncaaf_default_week()
    if sport_key == "ncaab":
        return date_value
    return date_value


def build_daily_update_simulation_contract(*, date_value: str, season: int | None = None) -> dict[str, Any]:
    sport_contracts: list[dict[str, Any]] = []
    for sport in ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab"):
        selection = _default_selection_for_sport(sport, date_value=date_value, season=season)
        try:
            contract = build_unified_simulation_adapter(
                sport,
                selection,
                season=season,
                allow_stored_date_fallback=(sport in {"nba", "wnba"}),
            )
        except Exception as exc:
            contract = {
                "adapter_version": "v1",
                "sport": sport,
                "selection": {
                    "kind": "week" if sport in {"nfl", "ncaaf"} else "date",
                    "requested": _safe_text(selection, ""),
                    "resolved": _safe_text(selection, ""),
                },
                "source_mode": "error",
                "source_title": "simulation adapter error",
                "source_paths": {},
                "freshness": {
                    "requested": _safe_text(selection, ""),
                    "resolved": _safe_text(selection, ""),
                    "selection_kind": "week" if sport in {"nfl", "ncaaf"} else "date",
                    "is_current_day": sport not in {"nfl", "ncaaf"},
                    "is_stale": False,
                    "lookahead_applied": False,
                },
                "games": [],
                "game_count": 0,
                "error": str(exc),
            }
        sport_contracts.append(deepcopy(contract))

        advanced_by_sport = {contract["sport"]: contract.get("advanced") for contract in sport_contracts}

    return {
        "contract_version": "v1",
        "scope": "daily_update",
        "date": _safe_text(date_value, ""),
        "season": season,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sport_count": len(sport_contracts),
        "sports": sport_contracts,
        "sports_by_key": {contract["sport"]: contract for contract in sport_contracts},
        "advanced_by_sport": advanced_by_sport,
        "source_modes": {contract["sport"]: contract.get("source_mode") for contract in sport_contracts},
        "freshness": {contract["sport"]: contract.get("freshness") for contract in sport_contracts},
        "source_paths": {contract["sport"]: contract.get("source_paths") for contract in sport_contracts},
    }


__all__ = ["build_daily_update_simulation_contract"]