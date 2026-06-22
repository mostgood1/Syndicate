from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf.sources import default_week as ncaaf_default_week
from syndicate.features.nfl.sources import default_week as nfl_default_week
from syndicate.features.shared.simulation_adapter import build_unified_simulation_adapter


def _normalize_sport(value: Any) -> str:
    return str(value or "").strip().lower()


def _selection_for_sport(sport: str, date_value: str) -> Any:
    if sport == "nfl":
        return nfl_default_week()
    if sport == "ncaaf":
        return ncaaf_default_week()
    return date_value


def _allow_stored_date_fallback(sport: str) -> bool:
    return sport in {"nba", "wnba"}


def build_daily_update_simulation_contract(date_value: str, sports: list[str]) -> dict[str, Any]:
    sport_contracts: list[dict[str, Any]] = []
    for sport in sports:
        sport_key = _normalize_sport(sport)
        if not sport_key:
            continue
        selection = _selection_for_sport(sport_key, date_value)
        sport_contract = build_unified_simulation_adapter(
            sport_key,
            selection,
            allow_stored_date_fallback=_allow_stored_date_fallback(sport_key),
        )
        sport_contracts.append(sport_contract)

    advanced_by_sport = {contract["sport"]: contract.get("advanced") for contract in sport_contracts}

    return {
        "contract_version": "v1",
        "scope": "daily_update",
        "date": date_value,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sport_count": len(sport_contracts),
        "sports": sport_contracts,
        "sports_by_key": {contract["sport"]: contract for contract in sport_contracts},
        "advanced_by_sport": advanced_by_sport,
        "source_modes": {contract["sport"]: contract.get("source_mode") for contract in sport_contracts},
        "freshness": {contract["sport"]: contract.get("freshness") for contract in sport_contracts},
        "source_paths": {contract["sport"]: contract.get("source_paths") for contract in sport_contracts},
    }


def write_daily_update_simulation_contract(
    *,
    date_value: str,
    sports: list[str],
    run_output_path: Path,
    latest_output_path: Path,
) -> dict[str, Any]:
    payload = build_daily_update_simulation_contract(date_value, sports)
    encoded = json.dumps(payload, indent=2, sort_keys=False)
    for output_path in (run_output_path, latest_output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(encoded + "\n", encoding="utf-8")
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the canonical daily-update simulation contract.")
    parser.add_argument("--date", required=True, help="ISO run date in YYYY-MM-DD format")
    parser.add_argument("--sports", required=True, help="Comma-separated list of active sports")
    parser.add_argument("--run-output", required=True, help="Path to the run-scoped contract artifact")
    parser.add_argument("--latest-output", required=True, help="Path to the latest-scoped contract artifact")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    sports = [sport.strip() for sport in str(args.sports or "").split(",") if sport.strip()]
    write_daily_update_simulation_contract(
        date_value=str(args.date).strip(),
        sports=sports,
        run_output_path=Path(args.run_output),
        latest_output_path=Path(args.latest_output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
