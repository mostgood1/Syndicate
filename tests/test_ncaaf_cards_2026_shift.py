"""Regression coverage for shifting the NCAAF cards page to a season the
legacy Enhanced Totals Engine has no data for (the 2026 bootstrap): the
season/week resolver that looks at real data instead of just the engine,
the SmartSim2-standalone schedule join, and the honestly-labeled standalone
card contract that never claims engine involvement it didn't have.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.ncaaf.cards import _build_smartsim2_standalone_ncaaf_card_contract
from syndicate.features.ncaaf.cards import _resolve_ncaaf_active_season_and_weeks
from syndicate.features.ncaaf.cards import _smartsim2_standalone_rows
from syndicate.features.ncaaf.cards import build_smartsim_cards_page_context
from syndicate.features.ncaaf.smartsim2_projection import LEGACY_ENGINE_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SMARTSIM2_PUBLIC_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SmartSimNcaafProjection


def _projection(**overrides) -> SmartSimNcaafProjection:
    base = dict(
        game_id="401856766",
        season=2026,
        week=1,
        home_team="TCU",
        away_team="North Carolina",
        home_score_mean=30.9,
        away_score_mean=27.0,
        margin_mean=3.9,
        total_mean=57.9,
        margin_stdev=13.5,
        total_stdev=13.0,
        home_win_rate=0.6133,
        seeds_used=300,
        profile_name="ncaaf_v2",
        rating_source="cfbd_ppa_season_2025_fallback_for_2026",
        generated_at="2026-07-21T14:26:55+00:00",
    )
    base.update(overrides)
    return SmartSimNcaafProjection(**base)


def _schedule_game(**overrides) -> dict:
    base = dict(
        id=401856766,
        season=2026,
        week=1,
        seasonType="regular",
        startDate="2026-08-29T16:00:00.000Z",
        completed=False,
        homeTeam="TCU",
        homeClassification="fbs",
        awayTeam="North Carolina",
        awayClassification="fbs",
        venue="Aviva Stadium",
    )
    base.update(overrides)
    return base


class ResolveActiveSeasonAndWeeksTests(unittest.TestCase):
    def test_prefers_later_season_when_only_smartsim2_has_it(self) -> None:
        with patch("syndicate.features.ncaaf.cards._engine_seasons_and_weeks", return_value={2025: [1, 2]}), patch(
            "syndicate.features.ncaaf.cards._smartsim2_standalone_seasons_and_weeks", return_value={2026: [1, 2, 3]}
        ):
            season, weeks = _resolve_ncaaf_active_season_and_weeks()
        self.assertEqual(season, 2026)
        self.assertEqual(weeks, [1, 2, 3])

    def test_uses_engine_season_when_it_is_later(self) -> None:
        with patch("syndicate.features.ncaaf.cards._engine_seasons_and_weeks", return_value={2026: [1]}), patch(
            "syndicate.features.ncaaf.cards._smartsim2_standalone_seasons_and_weeks", return_value={2025: [1, 2]}
        ):
            season, weeks = _resolve_ncaaf_active_season_and_weeks()
        self.assertEqual(season, 2026)
        self.assertEqual(weeks, [1])

    def test_unions_weeks_from_both_sources_for_the_active_season(self) -> None:
        with patch("syndicate.features.ncaaf.cards._engine_seasons_and_weeks", return_value={2025: [1, 2, 3]}), patch(
            "syndicate.features.ncaaf.cards._smartsim2_standalone_seasons_and_weeks", return_value={2025: [3, 4]}
        ):
            season, weeks = _resolve_ncaaf_active_season_and_weeks()
        self.assertEqual(season, 2025)
        self.assertEqual(weeks, [1, 2, 3, 4])

    def test_falls_back_to_default_season_when_nothing_available(self) -> None:
        with patch("syndicate.features.ncaaf.cards._engine_seasons_and_weeks", return_value={}), patch(
            "syndicate.features.ncaaf.cards._smartsim2_standalone_seasons_and_weeks", return_value={}
        ), patch("syndicate.features.ncaaf.cards.default_season", return_value=2025):
            season, weeks = _resolve_ncaaf_active_season_and_weeks()
        self.assertEqual(season, 2025)
        self.assertEqual(weeks, [])


class Smartsim2StandaloneRowsTests(unittest.TestCase):
    def test_joins_schedule_and_projection_by_normalized_team_names(self) -> None:
        with patch("syndicate.features.ncaaf.cards.load_games_season", return_value=[_schedule_game()]), patch(
            "syndicate.features.ncaaf.cards._smartsim2_projection_index",
            return_value={("tcu", "north carolina"): _projection()},
        ), patch("syndicate.features.ncaaf.cards._smartsim2_standalone_market_lines", return_value={}):
            rows = _smartsim2_standalone_rows(2026, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home_team"], "TCU")
        self.assertEqual(rows[0]["away_team"], "North Carolina")
        self.assertIsInstance(rows[0]["projection"], SmartSimNcaafProjection)

    def test_skips_games_with_no_matching_projection(self) -> None:
        with patch("syndicate.features.ncaaf.cards.load_games_season", return_value=[_schedule_game()]), patch(
            "syndicate.features.ncaaf.cards._smartsim2_projection_index", return_value={}
        ):
            rows = _smartsim2_standalone_rows(2026, 1)
        self.assertEqual(rows, [])

    def test_skips_non_fbs_vs_fbs_games(self) -> None:
        game = _schedule_game(awayClassification="fcs")
        with patch("syndicate.features.ncaaf.cards.load_games_season", return_value=[game]), patch(
            "syndicate.features.ncaaf.cards._smartsim2_projection_index",
            return_value={("tcu", "north carolina"): _projection()},
        ):
            rows = _smartsim2_standalone_rows(2026, 1)
        self.assertEqual(rows, [])

    def test_skips_games_for_a_different_week(self) -> None:
        game = _schedule_game(week=2)
        with patch("syndicate.features.ncaaf.cards.load_games_season", return_value=[game]), patch(
            "syndicate.features.ncaaf.cards._smartsim2_projection_index",
            return_value={("tcu", "north carolina"): _projection()},
        ):
            rows = _smartsim2_standalone_rows(2026, 1)
        self.assertEqual(rows, [])

    def test_attaches_market_line_when_available(self) -> None:
        with patch("syndicate.features.ncaaf.cards.load_games_season", return_value=[_schedule_game()]), patch(
            "syndicate.features.ncaaf.cards._smartsim2_projection_index",
            return_value={("tcu", "north carolina"): _projection()},
        ), patch(
            "syndicate.features.ncaaf.cards._smartsim2_standalone_market_lines",
            return_value={("tcu", "north carolina"): {"market_margin": 6.5, "market_total": 49.5}},
        ):
            rows = _smartsim2_standalone_rows(2026, 1)
        self.assertEqual(rows[0]["market_margin"], 6.5)
        self.assertEqual(rows[0]["market_total"], 49.5)

    def test_returns_empty_when_schedule_load_raises(self) -> None:
        with patch("syndicate.features.ncaaf.cards.load_games_season", side_effect=RuntimeError("boom")):
            rows = _smartsim2_standalone_rows(2026, 1)
        self.assertEqual(rows, [])


class BuildSmartsim2StandaloneCardContractTests(unittest.TestCase):
    def _row(self, **overrides) -> dict:
        base = dict(
            game_id="401856766",
            home_team="TCU",
            away_team="North Carolina",
            start_date="2026-08-29T16:00:00.000Z",
            venue="Aviva Stadium",
            projection=_projection(),
            market_margin=6.5,
            market_total=49.5,
        )
        base.update(overrides)
        return base

    def test_never_claims_engine_involvement(self) -> None:
        with patch("syndicate.features.ncaaf.cards._team_context", return_value=_FAKE_TEAM_CONTEXT):
            card = _build_smartsim2_standalone_ncaaf_card_contract(self._row(), 1, season=2026)
        self.assertEqual(card["detail"], SMARTSIM2_PUBLIC_LABEL)
        self.assertIn(SMARTSIM2_PUBLIC_LABEL, card["summary"])
        self.assertIn(f"{LEGACY_ENGINE_SOURCE_LABEL} has no prediction", card["summary"])
        self.assertNotIn(f"{LEGACY_ENGINE_SOURCE_LABEL} projects", card["summary"])

    def test_uses_real_smartsim2_numbers(self) -> None:
        with patch("syndicate.features.ncaaf.cards._team_context", return_value=_FAKE_TEAM_CONTEXT):
            card = _build_smartsim2_standalone_ncaaf_card_contract(self._row(), 1, season=2026)
        scoreboard = card["ncaaf_card"]["scoreboard"]
        self.assertEqual(scoreboard["home_points"], 30.9)
        self.assertEqual(scoreboard["away_points"], 27.0)
        self.assertEqual(scoreboard["total_points"], 57.9)
        self.assertEqual(scoreboard["spread_label"], "TCU by 3.9")

    def test_coverage_tier_is_distinct_and_always_publishable(self) -> None:
        with patch("syndicate.features.ncaaf.cards._team_context", return_value=_FAKE_TEAM_CONTEXT):
            card = _build_smartsim2_standalone_ncaaf_card_contract(self._row(), 1, season=2026)
        summary = card["ncaaf_card"]["summary"]
        self.assertEqual(summary["coverage_tier"], "smartsim2_only")
        self.assertIsNone(summary["coverage_score"])
        self.assertTrue(summary["publication_ready"])
        self.assertEqual(summary["publication_status"], "publishable")

    def test_negative_margin_favors_away_team(self) -> None:
        row = self._row(projection=_projection(margin_mean=-4.0))
        with patch("syndicate.features.ncaaf.cards._team_context", return_value=_FAKE_TEAM_CONTEXT):
            card = _build_smartsim2_standalone_ncaaf_card_contract(row, 1, season=2026)
        self.assertEqual(card["ncaaf_card"]["scoreboard"]["spread_label"], "North Carolina by 4.0")


_FAKE_TEAM_CONTEXT = {
    "team_name": "Placeholder",
    "team_id": "1",
    "abbreviation": "PLC",
    "rank": "",
    "school_name": "Placeholder",
    "mascot_name": "Placeholders",
    "conference": "Conf",
    "conference_short_name": "Conf",
    "subdivision": "FBS",
    "logo_url": None,
    "primary_color": None,
    "secondary_color": None,
    "returning": {"starter_estimate": "-", "percent_ppa": "-", "usage": "-", "summary": "No data"},
    "coach": {"name": "", "continuity_score": "-", "tenure_years": "-", "changed": "", "summary": "No data"},
    "transfer": {"incoming": 0, "outgoing": 0, "net": 0, "summary": "No transfer data"},
    "roster": {"active_count": 0, "summary": "0 active roster entries"},
}


class BuildSmartsimCardsPageContextIntegrationTests(unittest.TestCase):
    def test_falls_back_to_standalone_path_when_no_engine_rows_for_active_season(self) -> None:
        standalone_row = {
            "game_id": "1",
            "home_team": "TCU",
            "away_team": "North Carolina",
            "start_date": "2026-08-29T16:00:00.000Z",
            "venue": "Aviva Stadium",
            "projection": _projection(),
            "market_margin": 6.5,
            "market_total": 49.5,
        }
        with patch(
            "syndicate.features.ncaaf.cards._resolve_ncaaf_active_season_and_weeks", return_value=(2026, [1])
        ), patch("syndicate.features.ncaaf.cards._engine_rows_for_season_week", return_value=[]), patch(
            "syndicate.features.ncaaf.cards._smartsim2_standalone_rows", return_value=[standalone_row]
        ), patch("syndicate.features.ncaaf.cards._team_context", return_value=_FAKE_TEAM_CONTEXT), patch(
            "syndicate.features.ncaaf.cards.record_trial_page_view"
        ):
            context = build_smartsim_cards_page_context(1)
        self.assertEqual(len(context["games"]), 1)
        self.assertEqual(context["games"][0]["detail"], SMARTSIM2_PUBLIC_LABEL)
        self.assertEqual(context["date"], "2026 Week 1")
        self.assertIn(SMARTSIM2_PUBLIC_LABEL, context["source_title"])

    def test_uses_engine_path_unchanged_when_engine_rows_exist(self) -> None:
        engine_row = {
            "season": "2025",
            "week": "1",
            "home_team": "Sam Houston",
            "away_team": "UNLV",
            "predicted_home_points": "34.2",
            "predicted_away_points": "24.1",
            "predicted_total_points": "58.3",
            "predicted_win_margin": "10.1",
            "model_home_win_prob": "0.731",
            "start_date": "2025-09-01T19:00:00Z",
            "venue": "Test Stadium",
        }
        with patch(
            "syndicate.features.ncaaf.cards._resolve_ncaaf_active_season_and_weeks", return_value=(2025, [1])
        ), patch("syndicate.features.ncaaf.cards._engine_rows_for_season_week", return_value=[engine_row]), patch(
            "syndicate.features.ncaaf.cards._prediction_source_path", return_value=None
        ), patch("syndicate.features.ncaaf.cards.record_trial_page_view"):
            context = build_smartsim_cards_page_context(1)
        self.assertEqual(len(context["games"]), 1)
        self.assertEqual(context["games"][0]["detail"], LEGACY_ENGINE_SOURCE_LABEL)
        self.assertIn(LEGACY_ENGINE_SOURCE_LABEL, context["source_title"])


if __name__ == "__main__":
    unittest.main()
