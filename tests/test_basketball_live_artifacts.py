from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from syndicate.features.shared.basketball_live_artifacts import build_live_player_lens_payload_from_artifacts


class BuildLivePlayerLensPayloadSimMuTests(unittest.TestCase):
    # Layer 2 board follow-up: sim_mu (pregame sim mean) and sim_mu_adjusted
    # (live-recomputed mean) used to get merged into a single value before
    # ever reaching the board -- the same bug already fixed for MLB's
    # live-lens props, one layer down in the shared basketball artifact
    # reader. Once a game went live, home.py's "Projected" column for an
    # NBA/WNBA prop silently started showing the live-adjusted number.
    def test_pregame_and_live_adjusted_sim_mu_stay_distinct(self) -> None:
        row = {
            "market": "player_prop",
            "name_key": "test player",
            "player": "Test Player",
            "stat": "points",
            "game_id": "0022300123",
            "event_id": "evt1",
            "team": "BOS",
            "opponent": "NYK",
            "line": 20.5,
            "sim_mu": 19.5,
            "sim_mu_adjusted": 22.0,
            "live_projection": 21.0,
            "actual": 14,
        }
        event_games = {
            "evt1": {
                "event_id": "evt1",
                "gamePk": "0022300123",
                "away": {"abbr": "BOS"},
                "home": {"abbr": "NYK"},
            }
        }
        with TemporaryDirectory() as tmp:
            processed_root = Path(tmp)
            jsonl_path = processed_root / "live_lens_projections_2026-07-30.jsonl"
            jsonl_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

            payload = build_live_player_lens_payload_from_artifacts(
                processed_root=processed_root,
                date_str="2026-07-30",
                event_games=event_games,
                source="test",
            )

        self.assertIsNotNone(payload)
        games = payload.get("games") if isinstance(payload, dict) else None
        self.assertTrue(games)
        rendered_row = games[0]["rows"][0]
        self.assertEqual(rendered_row["sim_mu"], 19.5)
        self.assertEqual(rendered_row["sim_mu_adjusted"], 22.0)
        self.assertNotEqual(rendered_row["sim_mu"], rendered_row["sim_mu_adjusted"])
        self.assertEqual(rendered_row["live_projection"], 21.0)
        self.assertEqual(rendered_row["actual"], 14.0)
        # Edge/ranking math stays keyed off the live-adjusted value, same as
        # before this fix -- only the two output field identities changed.
        self.assertEqual(rendered_row["sim_vs_line"], round(22.0 - 20.5, 3))
        self.assertEqual(rendered_row["sim_vs_line_adjusted"], round(22.0 - 20.5, 3))

    def test_sim_mu_falls_back_to_pregame_value_when_no_adjusted_value_exists(self) -> None:
        row = {
            "market": "player_prop",
            "name_key": "test player",
            "player": "Test Player",
            "stat": "points",
            "game_id": "0022300123",
            "event_id": "evt1",
            "line": 20.5,
            "sim_mu": 19.5,
        }
        event_games = {
            "evt1": {
                "event_id": "evt1",
                "gamePk": "0022300123",
                "away": {"abbr": "BOS"},
                "home": {"abbr": "NYK"},
            }
        }
        with TemporaryDirectory() as tmp:
            processed_root = Path(tmp)
            jsonl_path = processed_root / "live_lens_projections_2026-07-30.jsonl"
            jsonl_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

            payload = build_live_player_lens_payload_from_artifacts(
                processed_root=processed_root,
                date_str="2026-07-30",
                event_games=event_games,
                source="test",
            )

        rendered_row = payload["games"][0]["rows"][0]
        self.assertEqual(rendered_row["sim_mu"], 19.5)
        self.assertEqual(rendered_row["sim_mu_adjusted"], 19.5)


if __name__ == "__main__":
    unittest.main()
