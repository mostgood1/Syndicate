from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_MODULE_PATH = REPO_ROOT / "scripts" / "fetch_mlb_injuries.py"
_spec = importlib.util.spec_from_file_location("fetch_mlb_injuries", _MODULE_PATH)
fetch_mlb_injuries = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("fetch_mlb_injuries", fetch_mlb_injuries)
assert _spec.loader is not None
_spec.loader.exec_module(fetch_mlb_injuries)


class StatusIsInjuredTests(unittest.TestCase):
    def test_il_and_dl_codes_are_injured(self) -> None:
        self.assertTrue(fetch_mlb_injuries._status_is_injured({"code": "D10", "description": "Injured 10-Day"}))
        self.assertTrue(fetch_mlb_injuries._status_is_injured({"code": "D60", "description": "Injured 60-Day"}))
        self.assertTrue(fetch_mlb_injuries._status_is_injured({"code": "IL15", "description": "Injured List"}))

    def test_description_only_match_is_injured(self) -> None:
        self.assertTrue(fetch_mlb_injuries._status_is_injured({"code": "XYZ", "description": "On the Injured List"}))

    def test_active_status_is_not_injured(self) -> None:
        self.assertFalse(fetch_mlb_injuries._status_is_injured({"code": "A", "description": "Active"}))

    def test_malformed_status_degrades_to_not_injured(self) -> None:
        self.assertFalse(fetch_mlb_injuries._status_is_injured(None))
        self.assertFalse(fetch_mlb_injuries._status_is_injured({}))
        self.assertFalse(fetch_mlb_injuries._status_is_injured("not a dict"))


class TeamIdsPlayingTests(unittest.TestCase):
    def test_extracts_unique_home_and_away_team_ids(self) -> None:
        games = [
            {"teams": {"home": {"team": {"id": 144}}, "away": {"team": {"id": 116}}}},
            {"teams": {"home": {"team": {"id": 111}}, "away": {"team": {"id": 144}}}},
        ]
        self.assertEqual(fetch_mlb_injuries._team_ids_playing(games), [111, 116, 144])

    def test_tolerates_malformed_rows(self) -> None:
        for games in ([], [None], ["nope"], [{"teams": None}], [{"teams": {"home": "bad"}}]):
            self.assertEqual(fetch_mlb_injuries._team_ids_playing(games), [])


if __name__ == "__main__":
    unittest.main()
