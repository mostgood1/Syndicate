from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from syndicate.features.shared.basketball_live_artifacts import _latest_projection_rows
from syndicate.features.shared.basketball_live_artifacts import _normalize_name
from syndicate.features.shared.basketball_live_artifacts import build_live_player_lens_payload_from_artifacts


class NormalizeNameTests(unittest.TestCase):
    # Phase C (Layer 2 task): mirrors mlb/cards.py's _normalize_live_name
    # diacritic-stripping fix, applied here since this is shared WNBA/NBA
    # infra with the same cross-source spelling-mismatch risk.
    def test_strips_diacritics(self) -> None:
        self.assertEqual(_normalize_name("Luka Dončić"), _normalize_name("Luka Doncic"))

    def test_collapses_whitespace_and_uppercases(self) -> None:
        self.assertEqual(_normalize_name("  angel   reese "), "ANGEL REESE")

    def test_none_returns_empty_string(self) -> None:
        self.assertEqual(_normalize_name(None), "")


class LatestProjectionRowsDiacriticDedupTests(unittest.TestCase):
    def test_accented_and_unaccented_spellings_of_the_same_player_dedupe(self) -> None:
        rows = [
            {"market": "player_prop", "name_key": "Luka Doncic", "stat": "points", "game_id_canon": "123", "line": 25.5},
            {"market": "player_prop", "name_key": "Luka Dončić", "stat": "points", "game_id_canon": "123", "line": 26.5},
        ]
        result = _latest_projection_rows(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["line"], 26.5)


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
