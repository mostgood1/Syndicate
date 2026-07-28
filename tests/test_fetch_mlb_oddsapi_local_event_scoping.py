from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.fetch_mlb_oddsapi_local import _event_scoping_enabled
from scripts.fetch_mlb_oddsapi_local import _event_scoping_window_seconds
from scripts.fetch_mlb_oddsapi_local import _event_wants_full_game_markets
from scripts.fetch_mlb_oddsapi_local import _load_mlb_status_by_matchup
from scripts.fetch_mlb_oddsapi_local import _normalize_matchup_team


def _schedule_fixture(*, away: str, home: str, abstract: str, detailed: str, game_date: str = "2026-07-27T18:00:00Z") -> list[dict]:
    return [
        {
            "gamePk": 1,
            "gameDate": game_date,
            "status": {"abstractGameState": abstract, "detailedState": detailed},
            "teams": {
                "away": {"team": {"name": away}},
                "home": {"team": {"name": home}},
            },
        }
    ]


class NormalizeMatchupTeamTests(unittest.TestCase):
    def test_collapses_case_and_whitespace(self) -> None:
        self.assertEqual(_normalize_matchup_team("  Seattle   Mariners "), "seattle mariners")


class LoadMlbStatusByMatchupTests(unittest.TestCase):
    def test_reads_real_shaped_schedule_snapshot_via_default_source_root(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fake_root = Path(tmp_dir)
            path = fake_root / "source_artifacts" / "data" / "daily" / "snapshots" / "2026-07-27" / "schedule_raw.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(_schedule_fixture(away="Seattle Mariners", home="Texas Rangers", abstract="Live", detailed="In Progress")),
                encoding="utf-8",
            )
            with patch("scripts.fetch_mlb_oddsapi_local.default_mlb_source_root", return_value=fake_root):
                result = _load_mlb_status_by_matchup("2026-07-27")
            self.assertEqual(
                result[("seattle mariners", "texas rangers")],
                {"abstract": "Live", "detailed": "In Progress", "commence": "2026-07-27T18:00:00Z"},
            )

    def test_missing_file_returns_empty_dict_not_raise(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch("scripts.fetch_mlb_oddsapi_local.default_mlb_source_root", return_value=Path(tmp_dir)):
                self.assertEqual(_load_mlb_status_by_matchup("2026-07-27"), {})


class EventWantsFullGameMarketsTests(unittest.TestCase):
    NOW = datetime(2026, 7, 27, 18, 0, 0, tzinfo=timezone.utc)

    def _status_map(self, *, abstract: str, detailed: str, commence: str | None = None) -> dict:
        return {("seattle mariners", "texas rangers"): {"abstract": abstract, "detailed": detailed, "commence": commence}}

    def test_live_game_wants_full(self) -> None:
        status = self._status_map(abstract="Live", detailed="In Progress")
        self.assertTrue(
            _event_wants_full_game_markets(
                away_team="Seattle Mariners", home_team="Texas Rangers", commence_time=None,
                status_by_matchup=status, now=self.NOW, window_seconds=4500,
            )
        )

    def test_warmup_is_not_live_confirmed_production_case(self) -> None:
        status = {
            ("baltimore orioles", "detroit tigers"): {
                "abstract": "Live", "detailed": "Warmup",
                "commence": (self.NOW + timedelta(hours=3)).isoformat(),
            }
        }
        self.assertFalse(
            _event_wants_full_game_markets(
                away_team="Baltimore Orioles", home_team="Detroit Tigers", commence_time=None,
                status_by_matchup=status, now=self.NOW, window_seconds=4500,
            )
        )

    def test_final_game_wants_reduced(self) -> None:
        status = self._status_map(abstract="Final", detailed="Final")
        self.assertFalse(
            _event_wants_full_game_markets(
                away_team="Seattle Mariners", home_team="Texas Rangers", commence_time=None,
                status_by_matchup=status, now=self.NOW, window_seconds=4500,
            )
        )

    def test_postponed_game_wants_reduced(self) -> None:
        # #16's own real-production example: Cleveland @ Cincinnati,
        # abstract "Final" / detailed "Postponed" -- confirmed via
        # mlb_status_is_final, not a special case here.
        status = self._status_map(abstract="Final", detailed="Postponed")
        self.assertFalse(
            _event_wants_full_game_markets(
                away_team="Seattle Mariners", home_team="Texas Rangers", commence_time=None,
                status_by_matchup=status, now=self.NOW, window_seconds=4500,
            )
        )

    def test_pregame_inside_window_wants_full(self) -> None:
        commence = (self.NOW + timedelta(minutes=30)).isoformat()
        status = self._status_map(abstract="Preview", detailed="Scheduled", commence=commence)
        self.assertTrue(
            _event_wants_full_game_markets(
                away_team="Seattle Mariners", home_team="Texas Rangers", commence_time=None,
                status_by_matchup=status, now=self.NOW, window_seconds=4500,
            )
        )

    def test_pregame_outside_window_wants_reduced(self) -> None:
        commence = (self.NOW + timedelta(hours=5)).isoformat()
        status = self._status_map(abstract="Preview", detailed="Scheduled", commence=commence)
        self.assertFalse(
            _event_wants_full_game_markets(
                away_team="Seattle Mariners", home_team="Texas Rangers", commence_time=None,
                status_by_matchup=status, now=self.NOW, window_seconds=4500,
            )
        )

    def test_unmatched_game_fails_open_to_full(self) -> None:
        self.assertTrue(
            _event_wants_full_game_markets(
                away_team="Nobody FC", home_team="Nowhere United", commence_time=None,
                status_by_matchup={}, now=self.NOW, window_seconds=4500,
            )
        )

    def test_naive_commence_time_is_treated_as_utc_not_rejected(self) -> None:
        commence = (self.NOW + timedelta(hours=5)).replace(tzinfo=None).isoformat()
        status = self._status_map(abstract="Preview", detailed="Scheduled", commence=commence)
        self.assertFalse(
            _event_wants_full_game_markets(
                away_team="Seattle Mariners", home_team="Texas Rangers", commence_time=None,
                status_by_matchup=status, now=self.NOW, window_seconds=4500,
            )
        )


class EventScopingEnvTests(unittest.TestCase):
    def test_enabled_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("SYNDICATE_ODDS_EVENT_SCOPING_ENABLED", None)
            self.assertTrue(_event_scoping_enabled())

    def test_can_be_disabled(self) -> None:
        with patch.dict("os.environ", {"SYNDICATE_ODDS_EVENT_SCOPING_ENABLED": "false"}):
            self.assertFalse(_event_scoping_enabled())

    def test_window_default_matches_t_window_ramp_boundary(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("SYNDICATE_ODDS_EVENT_SCOPING_WINDOW_SECONDS", None)
            self.assertEqual(_event_scoping_window_seconds(), 75 * 60)


if __name__ == "__main__":
    unittest.main()
