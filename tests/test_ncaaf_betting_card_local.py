from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.blueprints.ncaaf import api_betting_card as ncaaf_api_betting_card_route
from syndicate.blueprints.ncaaf import betting_card as ncaaf_betting_card_route
from syndicate.features.ncaaf.betting_card import _group_entries_by_day
from syndicate.features.ncaaf.betting_card import _kickoff_date_and_label
from syndicate.features.ncaaf.betting_card import build_ncaaf_betting_card_page_context


def _engine_row(*, home_team: str, away_team: str, start_date: str, week: str = "1", season: str = "2025") -> dict:
    return {
        "season": season,
        "week": week,
        "home_team": home_team,
        "away_team": away_team,
        "predicted_home_points": "27.5",
        "predicted_away_points": "20.1",
        "predicted_total_points": "47.6",
        "predicted_win_margin": "7.4",
        "model_home_win_prob": "0.64",
        "start_date": start_date,
        "venue": "Test Stadium",
    }


class NcaafBettingCardDayGroupingTests(unittest.TestCase):
    """Real per-game start_date/start_date_api-driven day grouping, nested
    inside the selected week -- mirrors the fixture shape used by
    test_ncaaf_picks_local.py / test_ncaaf_cards_local.py."""

    def test_kickoff_date_and_label_parses_iso_kickoff(self) -> None:
        date_key, weekday_label = _kickoff_date_and_label("2025-09-04T19:00:00Z")
        self.assertEqual(date_key, "2025-09-04")
        self.assertEqual(weekday_label, "Thursday, September 4")

    def test_kickoff_date_and_label_handles_missing_kickoff(self) -> None:
        date_key, weekday_label = _kickoff_date_and_label("")
        self.assertEqual(date_key, "")
        self.assertEqual(weekday_label, "Date TBD")

    def test_an_evening_kickoff_is_filed_on_its_CENTRAL_day(self) -> None:
        # 00:00Z Sunday is 7pm Central SATURDAY. Taking `.date()` off the
        # parsed UTC value filed the marquee Saturday slate under Sunday and
        # labelled it "Sunday" -- measured on the real 2026 schedule, 28 of
        # 157 kickoffs landed on the wrong day.
        date_key, weekday_label = _kickoff_date_and_label("2026-08-30T00:00:00.000Z")
        self.assertEqual(date_key, "2026-08-29")
        self.assertEqual(weekday_label, "Saturday, August 29")

    def test_a_late_window_kickoff_crosses_back_too(self) -> None:
        # 02:00Z Sunday is 9pm Central Saturday -- the west-coast window.
        date_key, weekday_label = _kickoff_date_and_label("2026-08-30T02:00:00.000Z")
        self.assertEqual(date_key, "2026-08-29")
        self.assertEqual(weekday_label, "Saturday, August 29")

    def test_a_naive_timestamp_is_treated_as_already_central(self) -> None:
        # Matches features/shared/timezone.py:central_date_from_iso rather
        # than assuming UTC, so a naive local string is not shifted a day.
        date_key, weekday_label = _kickoff_date_and_label("2026-08-29T19:00:00")
        self.assertEqual(date_key, "2026-08-29")
        self.assertEqual(weekday_label, "Saturday, August 29")

    def test_an_afternoon_kickoff_is_unchanged(self) -> None:
        # The case the original test covered: 19:00Z is 2pm Central, same day
        # either way. The fix must not move games that were already right.
        date_key, weekday_label = _kickoff_date_and_label("2025-09-04T19:00:00Z")
        self.assertEqual(date_key, "2025-09-04")
        self.assertEqual(weekday_label, "Thursday, September 4")

    def test_week_with_thursday_friday_saturday_games_produces_three_days_in_order(self) -> None:
        runtime_rows = [
            _engine_row(home_team="Sam Houston", away_team="UNLV", start_date="2025-09-06T19:00:00Z"),
            _engine_row(home_team="Tennessee", away_team="Syracuse", start_date="2025-09-04T19:00:00Z"),
            _engine_row(home_team="Ball State", away_team="Purdue", start_date="2025-09-05T19:00:00Z"),
        ]

        with patch(
            "syndicate.features.ncaaf.betting_card._resolve_ncaaf_active_season_and_weeks",
            return_value=(2025, [1]),
        ), patch(
            "syndicate.features.ncaaf.betting_card._engine_rows_for_season_week", return_value=runtime_rows
        ), patch(
            "syndicate.features.ncaaf.betting_card._prediction_source_path", return_value=Path("/tmp/predicted_totals.csv")
        ):
            context = build_ncaaf_betting_card_page_context(2025, 1)

        days = context["days"]
        self.assertEqual(len(days), 3)
        self.assertEqual([day["date"] for day in days], ["2025-09-04", "2025-09-05", "2025-09-06"])
        self.assertEqual(days[0]["weekday_label"], "Thursday, September 4")
        self.assertEqual(days[1]["weekday_label"], "Friday, September 5")
        self.assertEqual(days[2]["weekday_label"], "Saturday, September 6")
        for day in days:
            self.assertEqual(day["game_count"], 1)
            self.assertEqual(len(day["games"]), 1)
        self.assertEqual(context["week_summary"]["game_count"], 3)
        self.assertEqual(context["week_summary"]["day_count"], 3)

    def test_saturday_only_slate_produces_one_day_entry(self) -> None:
        runtime_rows = [
            _engine_row(home_team="Sam Houston", away_team="UNLV", start_date="2025-09-06T19:00:00Z"),
            _engine_row(home_team="Tennessee", away_team="Syracuse", start_date="2025-09-06T15:30:00Z"),
            _engine_row(home_team="Ball State", away_team="Purdue", start_date="2025-09-06T12:00:00Z"),
        ]

        with patch(
            "syndicate.features.ncaaf.betting_card._resolve_ncaaf_active_season_and_weeks",
            return_value=(2025, [1]),
        ), patch(
            "syndicate.features.ncaaf.betting_card._engine_rows_for_season_week", return_value=runtime_rows
        ), patch(
            "syndicate.features.ncaaf.betting_card._prediction_source_path", return_value=Path("/tmp/predicted_totals.csv")
        ):
            context = build_ncaaf_betting_card_page_context(2025, 1)

        days = context["days"]
        self.assertEqual(len(days), 1)
        self.assertEqual(days[0]["date"], "2025-09-06")
        self.assertEqual(days[0]["game_count"], 3)
        self.assertEqual(len(days[0]["games"]), 3)

    def test_group_entries_by_day_keeps_missing_dates_in_their_own_bucket(self) -> None:
        entries = [
            {"date": "2025-09-06", "kickoff": "2025-09-06T19:00:00Z", "weekday_label": "Saturday, September 6", "card": {"title": "A"}},
            {"date": "", "kickoff": "", "weekday_label": "Date TBD", "card": {"title": "B"}},
        ]
        days = _group_entries_by_day(entries)
        self.assertEqual(len(days), 2)
        self.assertEqual(days[0]["date"], "2025-09-06")
        self.assertIsNone(days[1]["date"])
        self.assertEqual(days[1]["weekday_label"], "Date TBD")


class NcaafBettingCardWeekNavigationTests(unittest.TestCase):
    def test_available_weeks_and_prev_next_hrefs_follow_shared_discrete_nav(self) -> None:
        runtime_rows = [_engine_row(home_team="Sam Houston", away_team="UNLV", start_date="2025-09-13T19:00:00Z", week="2")]

        with patch(
            "syndicate.features.ncaaf.betting_card._resolve_ncaaf_active_season_and_weeks",
            return_value=(2025, [1, 2, 3]),
        ), patch(
            "syndicate.features.ncaaf.betting_card._engine_rows_for_season_week", return_value=runtime_rows
        ), patch(
            "syndicate.features.ncaaf.betting_card._prediction_source_path", return_value=Path("/tmp/predicted_totals.csv")
        ):
            context = build_ncaaf_betting_card_page_context(2025, 2)

        self.assertEqual(context["available_weeks"], [1, 2, 3])
        self.assertEqual(context["week"], 2)
        self.assertEqual(context["prev_week"], 1)
        self.assertEqual(context["next_week"], 3)
        self.assertEqual(context["prev_href"], "/ncaaf/season/2025/betting-card?week=1")
        self.assertEqual(context["next_href"], "/ncaaf/season/2025/betting-card?week=3")

    def test_out_of_range_week_resolves_via_discrete_nav_clamp(self) -> None:
        runtime_rows: list[dict] = []

        with patch(
            "syndicate.features.ncaaf.betting_card._resolve_ncaaf_active_season_and_weeks",
            return_value=(2025, [1, 2, 3]),
        ), patch(
            "syndicate.features.ncaaf.betting_card._engine_rows_for_season_week", return_value=runtime_rows
        ), patch(
            "syndicate.features.ncaaf.betting_card._smartsim2_standalone_rows", return_value=[]
        ):
            context = build_ncaaf_betting_card_page_context(2025, 99)

        # resolve_selected_value falls back to the last available week when
        # the requested one isn't in the real available_weeks list.
        self.assertEqual(context["week"], 3)
        self.assertEqual(context["available_weeks"], [1, 2, 3])


class NcaafBettingCardStandaloneFallbackTests(unittest.TestCase):
    def test_falls_back_to_smartsim2_standalone_when_engine_has_no_rows(self) -> None:
        from syndicate.features.ncaaf.smartsim2_projection import SmartSimNcaafProjection

        projection = SmartSimNcaafProjection(
            game_id="g1", season=2026, week=1, home_team="Notre Dame", away_team="Wisconsin",
            home_score_mean=33.5, away_score_mean=25.7, margin_mean=7.8, total_mean=59.2,
            margin_stdev=12.0, total_stdev=10.0, home_win_rate=0.72, seeds_used=300,
            profile_name="ncaaf_v2", rating_source="test", generated_at="2026-01-01T00:00:00Z",
        )
        standalone_rows = [
            {
                "home_team": "Notre Dame",
                "away_team": "Wisconsin",
                "start_date": "2026-08-30T19:00:00Z",
                "venue": "Test Stadium",
                "projection": projection,
            }
        ]

        with patch(
            "syndicate.features.ncaaf.betting_card._resolve_ncaaf_active_season_and_weeks",
            return_value=(2026, [1]),
        ), patch(
            "syndicate.features.ncaaf.betting_card._engine_rows_for_season_week", return_value=[]
        ), patch(
            "syndicate.features.ncaaf.betting_card._smartsim2_standalone_rows", return_value=standalone_rows
        ):
            context = build_ncaaf_betting_card_page_context(2026, 1)

        self.assertEqual(context["week_summary"]["game_count"], 1)
        self.assertEqual(len(context["days"]), 1)
        game_card = context["days"][0]["games"][0]
        self.assertIn("Notre Dame", game_card["title"])
        self.assertEqual(game_card["eyebrow"], "SmartSim 2.0")

    def test_no_data_at_all_produces_empty_days_and_empty_state(self) -> None:
        with patch(
            "syndicate.features.ncaaf.betting_card._resolve_ncaaf_active_season_and_weeks",
            return_value=(2026, [1]),
        ), patch(
            "syndicate.features.ncaaf.betting_card._engine_rows_for_season_week", return_value=[]
        ), patch(
            "syndicate.features.ncaaf.betting_card._smartsim2_standalone_rows", return_value=[]
        ):
            context = build_ncaaf_betting_card_page_context(2026, 1)

        self.assertEqual(context["days"], [])
        self.assertIsNotNone(context["empty_state"])
        self.assertEqual(context["week_summary"]["game_count"], 0)


class NcaafBettingCardRouteTests(unittest.TestCase):
    def test_betting_card_route_uses_new_builder_and_template(self) -> None:
        app = create_app()
        runtime_context = {
            "season": 2025,
            "week": 1,
            "available_weeks": [1],
            "date": "2025 Week 1",
            "week_summary": {"season": 2025, "week": 1, "game_count": 0, "day_count": 0, "source_label": "No data"},
            "days": [],
            "using_sample_data": False,
            "empty_state": None,
        }

        with app.test_request_context("/ncaaf/season/2025/betting-card?week=1"), patch(
            "syndicate.blueprints.ncaaf.build_ncaaf_betting_card_page_context", return_value=runtime_context
        ) as build_context, patch("syndicate.blueprints.ncaaf.render_template", return_value="rendered") as render_template:
            response = ncaaf_betting_card_route(2025)

        self.assertEqual(response, "rendered")
        build_context.assert_called_once_with(2025, 1)
        render_template.assert_called_once()
        self.assertEqual(render_template.call_args.args[0], "ncaaf/betting_card.html")
        # The new dashboard shape, not the old relabeled-picks-board shape.
        self.assertIn("days", render_template.call_args.kwargs)
        self.assertIn("week_summary", render_template.call_args.kwargs)
        self.assertNotIn("rank_cards", render_template.call_args.kwargs)

    def test_api_betting_card_route_returns_real_dashboard_shape(self) -> None:
        app = create_app()
        runtime_rows = [_engine_row(home_team="Sam Houston", away_team="UNLV", start_date="2025-09-06T19:00:00Z")]

        with app.test_request_context("/ncaaf/api/season/2025/betting-card?week=1"), patch(
            "syndicate.features.ncaaf.betting_card._resolve_ncaaf_active_season_and_weeks",
            return_value=(2025, [1]),
        ), patch(
            "syndicate.features.ncaaf.betting_card._engine_rows_for_season_week", return_value=runtime_rows
        ), patch(
            "syndicate.features.ncaaf.betting_card._prediction_source_path", return_value=Path("/tmp/predicted_totals.csv")
        ):
            response = ncaaf_api_betting_card_route(2025)

        payload = response.get_json()
        self.assertEqual(payload["season"], 2025)
        self.assertEqual(payload["week"], 1)
        self.assertIn("days", payload)
        self.assertIn("week_summary", payload)
        self.assertEqual(payload["week_summary"]["game_count"], 1)
        # Old shape (build_rank_api_payload over the relabeled picks board)
        # always carried "rank_cards" -- the new dashboard payload must not.
        self.assertNotIn("rank_cards", payload)

    def test_betting_card_route_renders_end_to_end_with_real_template(self) -> None:
        app = create_app()
        runtime_rows = [_engine_row(home_team="Sam Houston", away_team="UNLV", start_date="2025-09-06T19:00:00Z")]

        with app.test_request_context("/ncaaf/season/2025/betting-card?week=1"), patch(
            "syndicate.features.ncaaf.betting_card._resolve_ncaaf_active_season_and_weeks",
            return_value=(2025, [1]),
        ), patch(
            "syndicate.features.ncaaf.betting_card._engine_rows_for_season_week", return_value=runtime_rows
        ), patch(
            "syndicate.features.ncaaf.betting_card._prediction_source_path", return_value=Path("/tmp/predicted_totals.csv")
        ):
            html = ncaaf_betting_card_route(2025)

        self.assertIn("Sam Houston", html)
        self.assertIn("Saturday, September 6", html)


if __name__ == "__main__":
    unittest.main()
