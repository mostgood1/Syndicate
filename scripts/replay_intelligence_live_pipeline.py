from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root


def _extract_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("response"), dict):
        return dict(payload.get("response") or {})
    return dict(payload)


def _pick_sport_block(live_pipeline: dict[str, Any], sport: str | None) -> dict[str, Any] | None:
    if not sport:
        return dict(live_pipeline)
    by_sport = live_pipeline.get("by_sport") if isinstance(live_pipeline.get("by_sport"), dict) else {}
    sport_key = str(sport or "").strip().lower()
    if sport_key and isinstance(by_sport.get(sport_key), dict):
        return dict(by_sport.get(sport_key) or {})
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a persisted intelligence live pipeline snapshot.")
    parser.add_argument("--state-path", default=str(reports_root() / "intelligence" / "intelligence_state.json"))
    parser.add_argument("--sport", default="")
    parser.add_argument("--date", default="")
    args = parser.parse_args()

    state_path = Path(str(args.state_path)).expanduser().resolve()
    payload = read_json_file(state_path)
    if not isinstance(payload, dict):
        raise SystemExit(f"No intelligence snapshot found at {state_path}")

    snapshot = _extract_snapshot(payload)
    live_pipeline = snapshot.get("live_pipeline") if isinstance(snapshot.get("live_pipeline"), dict) else {}
    selected_block = _pick_sport_block(live_pipeline, str(args.sport).strip() or None)
    if selected_block is None and str(args.sport).strip():
        raise SystemExit(f"No live pipeline block found for sport={str(args.sport).strip()}")

    output = {
        "ok": True,
        "state_path": str(state_path),
        "selected_date": str(args.date).strip() or snapshot.get("selected_date") or snapshot.get("date"),
        "sport": str(args.sport).strip() or snapshot.get("sport") or "all",
        "live_pipeline": selected_block or dict(live_pipeline),
        "board_contract": snapshot.get("board_contract") if isinstance(snapshot.get("board_contract"), dict) else payload.get("board_contract"),
    }
    print(json.dumps(output, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())