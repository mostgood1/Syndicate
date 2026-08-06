"""Coverage for syndicate/features/nfl/live_lens.py -- Phase 1 of todo #119
(real live status/score/clock overlay, no re-sim). Mirrors
tests/test_wnba_live_lens_worker.py's mocking-the-pregame-context and
snapshot-validator conventions, adapted for NFL's week/season shape instead
of WNBA's date shape.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.nfl import live_lens
from syndicate.features.nfl.live_lens import build_live_lens_page_context
from syndicate.features.nfl.live_lens import build_live_lens_snapshot
from syndicate.features.nfl.live_lens import validate_live_lens_snapshot


def _pregame_game(*, away_abbr="BAL", away_name="Baltimore Ravens", home_abbr="KC", home_name="Kansas City Chiefs", gamepk="g1") -> dict:
    return {
        "gamePk": gamepk,
        "away": {"abbr": away_abbr, "name": away_name},
        "home": {"abbr": home_abbr, "name": home_name},
        "href": f"/nfl/game/{gamepk}?season=2026&week=1",
        "href_label": "Open NFL game detail",
        "status": "Week 1",
        "detail": "2026-09-08",
        "summary": "Stored weekly recommendation rows.",
        "metrics": [{"label": "Kickoff", "value": "2026-09-08"}],
        "shared_top_play_rows": [{"name": "Moneyline", "value": "+3.2% EV", "detail": "BAL ML"}],
        "panels": [],
    }


def _live_row(*, event_id="401671801", away="Baltimore Ravens", home="Kansas City Chiefs", away_abbr="BAL", home_abbr="KC", state="in", completed=False, period=3, display_clock="4:12", away_score=14.0, home_score=17.0) -> dict:
    return {
        "event_id": event_id,
        "away": away,
        "home": home,
        "away_abbr": away_abbr,
        "home_abbr": home_abbr,
        "away_score": away_score,
        "home_score": home_score,
        "state": state,
        "completed": completed,
        "period": period,
        "display_clock": display_clock,
        "status_detail": "3rd Quarter - 4:12",
    }


def _preseason_context(games: list[dict]) -> dict:
    return {
        "control_value": "1",
        "games": games,
        "source_path": "smartsim2_preseason_projections_2026_wk1.csv",
        "prev_date": "1",
        "next_date": "2",
    }


class NflLiveLensSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        # Regular-season fixtures in this class assume preseason is NOT the
        # current phase. Without pinning this, these tests would silently
        # exercise the real syndicate.features.nfl.sources.preseason_target_week
        # against whatever the real calendar says at test-run time (a real
        # concern: this session's own current date sits inside the real 2026
        # NFL preseason window), making the suite non-deterministic. The
        # dedicated preseason tests below override this per-test.
        patcher = patch.object(live_lens, "preseason_target_week", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _cards_context(self, games: list[dict]) -> dict:
        return {
            "week": 1,
            "season": 2026,
            "games": games,
            "source_path": "upcoming_recs_2026_wk1.csv",
            "prev_date": "0",
            "next_date": "2",
        }

    def test_merges_live_state_onto_matching_game_by_team_name(self) -> None:
        cards_context = self._cards_context([_pregame_game()])
        with patch.object(live_lens, "build_cards_page_context", return_value=cards_context), patch.object(
            live_lens, "_fetch_espn_football_live_state", return_value=[_live_row()]
        ):
            snapshot = build_live_lens_snapshot(1, 2026)

        self.assertEqual(snapshot["live_matches"], 1)
        game = snapshot["games"][0]
        self.assertIsInstance(game["status"], dict)
        self.assertEqual(game["status"]["status"], "Live")
        self.assertEqual(game["status"]["period"], 3)
        self.assertEqual(game["status"]["clock"], "4:12")
        self.assertTrue(game["status"]["in_progress"])
        self.assertEqual(game["detail"], "Q3 4:12")
        self.assertEqual(game["live_state"]["away_pts"], 14.0)
        self.assertEqual(game["live_state"]["home_pts"], 17.0)
        self.assertEqual(game["away"]["score"], 14.0)
        self.assertEqual(game["home"]["score"], 17.0)

        card = snapshot["rank_cards"][0]
        self.assertEqual(card["eyebrow"], "Live")
        self.assertEqual(card["badge"], "Live")
        self.assertIn("Q3 4:12", card["meta"])
        self.assertIn("BAL 14-17 KC", card["meta"])

    def test_merges_by_abbreviation_when_names_differ(self) -> None:
        # Real fixture drift: branding full-name text vs. ESPN's own
        # displayName can diverge (e.g. "Football Team" era naming); the
        # abbreviation fallback must still resolve the match.
        cards_context = self._cards_context([_pregame_game(away_name="Baltimore Ravens (Old Name)")])
        with patch.object(live_lens, "build_cards_page_context", return_value=cards_context), patch.object(
            live_lens, "_fetch_espn_football_live_state", return_value=[_live_row()]
        ):
            snapshot = build_live_lens_snapshot(1, 2026)

        self.assertEqual(snapshot["live_matches"], 1)

    def test_final_game_marked_final_not_live(self) -> None:
        cards_context = self._cards_context([_pregame_game()])
        final_row = _live_row(state="post", completed=True, period=4, display_clock="0:00", away_score=20.0, home_score=27.0)
        with patch.object(live_lens, "build_cards_page_context", return_value=cards_context), patch.object(
            live_lens, "_fetch_espn_football_live_state", return_value=[final_row]
        ):
            snapshot = build_live_lens_snapshot(1, 2026)

        game = snapshot["games"][0]
        self.assertTrue(game["status"]["final"])
        self.assertFalse(game["status"]["in_progress"])
        self.assertEqual(snapshot["rank_cards"][0]["badge"], "Final")

    def test_unmatched_game_falls_back_to_pregame_state_without_crashing(self) -> None:
        # Bye week / ESPN temporarily missing an event: no live row at all.
        cards_context = self._cards_context([_pregame_game(gamepk="bye-week-game")])
        with patch.object(live_lens, "build_cards_page_context", return_value=cards_context), patch.object(
            live_lens, "_fetch_espn_football_live_state", return_value=[]
        ):
            snapshot = build_live_lens_snapshot(1, 2026)

        self.assertEqual(snapshot["live_matches"], 0)
        game = snapshot["games"][0]
        self.assertEqual(game["status"], "Week 1")
        self.assertEqual(game["detail"], "2026-09-08")
        self.assertNotIn("live_state", game)
        card = snapshot["rank_cards"][0]
        self.assertEqual(card["eyebrow"], "Week 1")

    def test_pregame_espn_row_does_not_fabricate_live_status(self) -> None:
        # ESPN has the game listed but it hasn't kicked off yet -- must not
        # be treated as a live-state match.
        cards_context = self._cards_context([_pregame_game()])
        pre_row = _live_row(state="pre", completed=False, period=None, display_clock="", away_score=0.0, home_score=0.0)
        with patch.object(live_lens, "build_cards_page_context", return_value=cards_context), patch.object(
            live_lens, "_fetch_espn_football_live_state", return_value=[pre_row]
        ):
            snapshot = build_live_lens_snapshot(1, 2026)

        self.assertEqual(snapshot["live_matches"], 0)
        game = snapshot["games"][0]
        self.assertEqual(game["status"], "Week 1")
        self.assertNotIn("live_state", game)

    def test_live_state_fetch_exception_does_not_crash_snapshot_build(self) -> None:
        cards_context = self._cards_context([_pregame_game()])
        with patch.object(live_lens, "build_cards_page_context", return_value=cards_context), patch.object(
            live_lens, "_fetch_espn_football_live_state", side_effect=RuntimeError("boom")
        ):
            snapshot = build_live_lens_snapshot(1, 2026)

        self.assertEqual(snapshot["live_matches"], 0)
        self.assertEqual(len(snapshot["games"]), 1)

    def test_snapshot_returns_safe_empty_board_when_cards_context_missing(self) -> None:
        with patch.object(live_lens, "build_cards_page_context", side_effect=RuntimeError("boom")):
            snapshot = build_live_lens_snapshot(1, 2026)

        self.assertEqual(snapshot["games"], [])
        self.assertEqual(snapshot["rank_cards"], [])
        self.assertEqual(snapshot["cards"], [])
        self.assertEqual(snapshot["warning_panel"]["eyebrow"], "NFL live lens")


class NflLiveLensPreseasonSnapshotTests(unittest.TestCase):
    """Coordinator-flagged gap: build_live_lens_snapshot must route to the
    preseason cards builder (not the regular-season one) whenever
    preseason_target_week(season) returns a real week -- the same real
    "which phase is current" signal _build_sport_overview (home.py) and
    _NFLDataProvider.games() already use, both fixed earlier this session.
    Confirmed live against the real 2026-08-07 Hall of Fame Game this whole
    session has been validating against.
    """

    def test_routes_to_preseason_builder_and_ignores_regular_season_week_arg(self) -> None:
        preseason_context = _preseason_context(
            [_pregame_game(gamepk="hof-game", away_abbr="DET", away_name="Detroit Lions", home_abbr="LAC", home_name="Los Angeles Chargers")]
        )
        with patch.object(live_lens, "preseason_target_week", return_value=1), patch.object(
            live_lens, "build_preseason_cards_page_context", return_value=preseason_context
        ) as mocked_preseason_build, patch.object(
            live_lens, "build_cards_page_context", side_effect=AssertionError("must not call the regular-season cards builder during preseason")
        ), patch.object(live_lens, "_fetch_espn_football_live_state", return_value=[]), patch.object(
            live_lens, "build_preseason_module_links", return_value=[]
        ), patch.object(live_lens, "_available_preseason_weeks", return_value=[1, 2, 3, 4]):
            # week=99 stands in for whatever meaningless regular-season week
            # default_week()/_selected_week() would have resolved to (always
            # "week 1" during preseason) -- must be ignored entirely.
            snapshot = build_live_lens_snapshot(99, 2026)

        mocked_preseason_build.assert_called_once_with(1, season=2026)
        self.assertTrue(snapshot["is_preseason"])
        self.assertEqual(snapshot["season"], 2026)
        self.assertEqual(snapshot["week"], 1)
        self.assertEqual(snapshot["available_weeks"], [1, 2, 3, 4])
        self.assertEqual(len(snapshot["games"]), 1)
        self.assertEqual(snapshot["games"][0]["gamePk"], "hof-game")

    def test_live_state_overlay_merges_correctly_onto_preseason_game(self) -> None:
        preseason_context = _preseason_context(
            [_pregame_game(gamepk="hof-game", away_abbr="DET", away_name="Detroit Lions", home_abbr="LAC", home_name="Los Angeles Chargers")]
        )
        live_row = _live_row(
            away="Detroit Lions",
            home="Los Angeles Chargers",
            away_abbr="DET",
            home_abbr="LAC",
            state="in",
            period=2,
            display_clock="8:45",
            away_score=10.0,
            home_score=7.0,
        )
        with patch.object(live_lens, "preseason_target_week", return_value=1), patch.object(
            live_lens, "build_preseason_cards_page_context", return_value=preseason_context
        ), patch.object(live_lens, "_fetch_espn_football_live_state", return_value=[live_row]), patch.object(
            live_lens, "build_preseason_module_links", return_value=[]
        ), patch.object(live_lens, "_available_preseason_weeks", return_value=[1, 2, 3, 4]):
            snapshot = build_live_lens_snapshot(1, 2026)

        self.assertEqual(snapshot["live_matches"], 1)
        game = snapshot["games"][0]
        self.assertIsInstance(game["status"], dict)
        self.assertTrue(game["status"]["in_progress"])
        self.assertEqual(game["status"]["period"], 2)
        self.assertEqual(game["status"]["clock"], "8:45")
        self.assertEqual(game["live_state"]["away_pts"], 10.0)
        self.assertEqual(game["live_state"]["home_pts"], 7.0)
        self.assertEqual(game["away"]["score"], 10.0)
        self.assertEqual(game["home"]["score"], 7.0)
        card = snapshot["rank_cards"][0]
        self.assertEqual(card["badge"], "Live")

    def test_no_preseason_game_when_target_week_is_none(self) -> None:
        # Regression guard for the exact gap this fix addresses: once
        # preseason_target_week() genuinely returns None (season has moved
        # on), the regular-season builder must be used, not the preseason one.
        cards_context = {
            "week": 1,
            "season": 2026,
            "games": [_pregame_game()],
            "source_path": "upcoming_recs_2026_wk1.csv",
            "prev_date": "0",
            "next_date": "2",
        }
        with patch.object(live_lens, "preseason_target_week", return_value=None), patch.object(
            live_lens, "build_cards_page_context", return_value=cards_context
        ) as mocked_regular_build, patch.object(
            live_lens, "build_preseason_cards_page_context", side_effect=AssertionError("must not call the preseason builder outside preseason")
        ), patch.object(live_lens, "_fetch_espn_football_live_state", return_value=[]):
            snapshot = build_live_lens_snapshot(1, 2026)

        mocked_regular_build.assert_called_once_with(1, season=2026)
        self.assertFalse(snapshot["is_preseason"])


class NflLiveLensValidatorTests(unittest.TestCase):
    def test_rejects_non_dict(self) -> None:
        self.assertFalse(validate_live_lens_snapshot(None))
        self.assertFalse(validate_live_lens_snapshot([]))

    def test_requires_date_games_and_cards(self) -> None:
        self.assertFalse(validate_live_lens_snapshot({"games": [], "cards": []}))
        self.assertFalse(validate_live_lens_snapshot({"date": "2026 Week 1", "cards": []}))
        self.assertFalse(validate_live_lens_snapshot({"date": "2026 Week 1", "games": []}))
        self.assertTrue(validate_live_lens_snapshot({"date": "2026 Week 1", "games": [], "cards": []}))

    def test_rejects_nan_values(self) -> None:
        snapshot = {
            "date": "2026 Week 1",
            "games": [],
            "cards": [{"metrics": [{"label": "Score", "value": float("nan")}]}],
        }
        self.assertFalse(validate_live_lens_snapshot(snapshot))


class NflLiveLensPageContextTests(unittest.TestCase):
    def setUp(self) -> None:
        # Same non-determinism concern as NflLiveLensSnapshotTests.setUp --
        # _snapshot_matches_request() also re-checks preseason_target_week().
        patcher = patch.object(live_lens, "preseason_target_week", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_uses_persisted_snapshot_without_rebuild_when_current(self) -> None:
        fresh_snapshot = {
            "date": "2026 Week 1",
            "season": 2026,
            "week": 1,
            "is_preseason": False,
            "rank_cards": [{"title": "BAL @ KC", "metrics": [], "summary": "live"}],
            "cards": [{"title": "BAL @ KC", "metrics": [], "summary": "live"}],
            "games": [{"gamePk": "g1"}],
        }
        with patch.object(live_lens, "_load_live_lens_snapshot", return_value=fresh_snapshot), patch.object(
            live_lens, "build_live_lens_snapshot"
        ) as mocked_rebuild:
            context = build_live_lens_page_context(1, season=2026)

        mocked_rebuild.assert_not_called()
        self.assertEqual(context["season"], 2026)
        self.assertEqual(context["week"], 1)
        self.assertEqual(context["rank_cards"][0]["title"], "BAL @ KC")
        self.assertTrue(context["have_data"])

    def test_rebuilds_when_persisted_snapshot_is_for_a_different_week(self) -> None:
        stale_snapshot = {
            "date": "2026 Week 1",
            "season": 2026,
            "week": 1,
            "rank_cards": [{"title": "Stale"}],
            "cards": [{"title": "Stale"}],
            "games": [],
        }
        fresh_snapshot = {
            "date": "2026 Week 2",
            "season": 2026,
            "week": 2,
            "rank_cards": [{"title": "Fresh"}],
            "cards": [{"title": "Fresh"}],
            "games": [],
        }
        with patch.object(live_lens, "_load_live_lens_snapshot", return_value=stale_snapshot), patch.object(
            live_lens, "build_live_lens_snapshot", return_value=fresh_snapshot
        ) as mocked_rebuild:
            context = build_live_lens_page_context(2, season=2026)

        mocked_rebuild.assert_called_once_with(2, 2026)
        self.assertEqual(context["rank_cards"][0]["title"], "Fresh")

    def test_rebuilds_when_no_snapshot_is_persisted(self) -> None:
        fresh_snapshot = {
            "date": "2026 Week 1",
            "season": 2026,
            "week": 1,
            "rank_cards": [{"title": "Fresh"}],
            "cards": [{"title": "Fresh"}],
            "games": [],
        }
        with patch.object(live_lens, "_load_live_lens_snapshot", return_value=None), patch.object(
            live_lens, "build_live_lens_snapshot", return_value=fresh_snapshot
        ) as mocked_rebuild:
            context = build_live_lens_page_context(1, season=2026)

        mocked_rebuild.assert_called_once_with(1, 2026)
        self.assertEqual(context["rank_cards"][0]["title"], "Fresh")


if __name__ == "__main__":
    unittest.main()
