from __future__ import annotations

import unittest
from json import loads
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared.daily_update_simulation_contract import build_daily_update_simulation_contract
from scripts.build_daily_update_simulation_contract import write_daily_update_simulation_contract


class DailyUpdateSimulationContractTests(unittest.TestCase):
    def test_builder_emits_one_contract_per_sport_with_source_metadata(self) -> None:
        fake_contract = {
            "adapter_version": "v1",
            "sport": "mlb",
            "selection": {"kind": "date", "requested": "2026-06-22", "resolved": "2026-06-22"},
            "source_mode": "live_supplement",
            "source_title": "MLB daily summary",
            "source_paths": {"source_path": "/tmp/mlb"},
            "freshness": {"requested": "2026-06-22", "resolved": "2026-06-22", "selection_kind": "date", "is_current_day": True, "is_stale": False, "lookahead_applied": False},
            "advanced": {"available": True, "page": {"workflow": {"mode": "daily_update"}}, "game": {"first1BetSignal": {"market": "first1"}}},
            "games": [{"game_id": "g1", "event_id": "e1", "market_features": {"movement_delta": 1.0, "history_points": 2}}],
            "game_count": 1,
        }

        with patch(
            "syndicate.features.shared.daily_update_simulation_contract.build_unified_simulation_adapter",
            side_effect=lambda sport, selection, **kwargs: dict(fake_contract, sport=sport, selection={"kind": "week" if sport in {"nfl", "ncaaf"} else "date", "requested": str(selection), "resolved": str(selection)}),
        ):
            payload = build_daily_update_simulation_contract(date_value="2026-06-22")

        self.assertEqual(payload["scope"], "daily_update")
        self.assertEqual(payload["date"], "2026-06-22")
        self.assertEqual(len(payload["sports"]), 7)
        self.assertIn("mlb", payload["sports_by_key"])
        self.assertIn("wnba", payload["source_modes"])
        self.assertIn("nfl", payload["freshness"])
        self.assertIn("ncaab", payload["source_paths"])
        self.assertEqual(payload["sports_by_key"]["mlb"]["source_mode"], "live_supplement")
        self.assertIn("mlb", payload["advanced_by_sport"])
        self.assertEqual(payload["advanced_by_sport"]["mlb"], fake_contract.get("advanced"))
        self.assertIn("market_summary", payload)
        self.assertIn("market_summary_by_sport", payload)
        self.assertEqual(payload["market_summary_by_sport"]["mlb"]["market_feature_count"], 1)
        self.assertEqual(payload["market_summary"]["market_feature_count"], 7)

    def test_writer_persists_advanced_contract_shape(self) -> None:
        fake_contract = {
            "adapter_version": "v1",
            "sport": "mlb",
            "selection": {"kind": "date", "requested": "2026-06-22", "resolved": "2026-06-22"},
            "source_mode": "live_supplement",
            "source_title": "MLB daily summary",
            "source_paths": {"source_path": "/tmp/mlb"},
            "freshness": {"requested": "2026-06-22", "resolved": "2026-06-22", "selection_kind": "date", "is_current_day": True, "is_stale": False, "lookahead_applied": False},
            "advanced": {"available": True, "page": {"workflow": {"mode": "daily_update"}}, "game": {"first1BetSignal": {"market": "first1"}}},
            "games": [{"game_id": "g1", "event_id": "e1", "market_features": {"movement_delta": 1.0, "history_points": 2}}],
            "game_count": 1,
        }

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            run_path = temp_path / "run.json"
            latest_path = temp_path / "latest.json"

            with patch(
                "scripts.build_daily_update_simulation_contract.build_unified_simulation_adapter",
                side_effect=lambda sport, selection, **kwargs: dict(
                    fake_contract,
                    sport=sport,
                    selection={"kind": "week" if sport in {"nfl", "ncaaf"} else "date", "requested": str(selection), "resolved": str(selection)},
                ),
            ):
                payload = write_daily_update_simulation_contract(
                    date_value="2026-06-22",
                    sports=["mlb"],
                    run_output_path=run_path,
                    latest_output_path=latest_path,
                )

            run_payload = loads(run_path.read_text(encoding="utf-8"))
            latest_payload = loads(latest_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["advanced_by_sport"]["mlb"]["game"]["first1BetSignal"]["market"], "first1")
        self.assertEqual(payload["market_summary_by_sport"]["mlb"]["market_feature_count"], 1)
        self.assertEqual(run_payload["advanced_by_sport"]["mlb"]["page"]["workflow"]["mode"], "daily_update")
        self.assertEqual(run_payload["market_summary"]["market_feature_count"], 1)
        self.assertEqual(latest_payload["advanced_by_sport"]["mlb"]["game"]["first1BetSignal"]["market"], "first1")
