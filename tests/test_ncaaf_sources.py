from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.ncaaf import sources


class NcaafTargetWeekTests(unittest.TestCase):
    def test_missing_season_returns_none(self) -> None:
        with patch(
            "syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader.load_games_season",
            side_effect=Exception("no cache"),
        ):
            self.assertIsNone(sources.ncaaf_target_week(2099))

    def test_all_games_unplayed_returns_lowest_week(self) -> None:
        games = [
            {"week": 1, "completed": False},
            {"week": 2, "completed": False},
        ]
        with patch(
            "syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader.load_games_season",
            return_value=games,
        ):
            self.assertEqual(sources.ncaaf_target_week(2026), 1)

    def test_completed_weeks_are_skipped(self) -> None:
        games = [
            {"week": 1, "completed": True},
            {"week": 2, "completed": False},
        ]
        with patch(
            "syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader.load_games_season",
            return_value=games,
        ):
            self.assertEqual(sources.ncaaf_target_week(2026), 2)

    def test_all_games_played_returns_none(self) -> None:
        games = [{"week": 1, "completed": True}]
        with patch(
            "syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader.load_games_season",
            return_value=games,
        ):
            self.assertIsNone(sources.ncaaf_target_week(2026))


class DefaultSeasonDelegationTests(unittest.TestCase):
    """Regression coverage for a real bug: default_season() used to be a
    fully separate implementation from cards.py's own
    _resolve_ncaaf_active_season_and_weeks(), so it returned a stale
    season (2025) even after cards.py's own resolver had already found a
    newer one (2026) via real SmartSim2 projection artifacts. Also guards
    against the circular-call trap this fix introduced: cards.py's
    resolver falls back to a *different* function (not default_season()
    itself) when neither data source has anything, to avoid infinite
    recursion between the two."""

    def test_delegates_to_the_real_active_season_resolver(self) -> None:
        with patch(
            "syndicate.features.ncaaf.cards._resolve_ncaaf_active_season_and_weeks",
            return_value=(2026, [1, 2]),
        ):
            self.assertEqual(sources.default_season(), 2026)

    def test_falls_back_to_legacy_when_resolver_finds_nothing(self) -> None:
        with patch(
            "syndicate.features.ncaaf.cards._resolve_ncaaf_active_season_and_weeks",
            return_value=(0, []),
        ), patch.object(
            sources, "_legacy_default_season_from_summary_index", return_value=2024,
        ):
            self.assertEqual(sources.default_season(), 2024)

    def test_never_recurses_when_neither_source_has_data(self) -> None:
        # The real _resolve_ncaaf_active_season_and_weeks (not mocked here)
        # must not call back into default_season() in its own empty-data
        # fallback -- this would previously have recursed forever.
        from syndicate.features.ncaaf import cards as ncaaf_cards

        with patch.object(ncaaf_cards, "_engine_seasons_and_weeks", return_value={}), patch.object(
            ncaaf_cards, "_smartsim2_standalone_seasons_and_weeks", return_value={},
        ):
            result = sources.default_season()
        self.assertIsInstance(result, int)


if __name__ == "__main__":
    unittest.main()
