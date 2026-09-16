from __future__ import annotations

import unittest

from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_lineups import extract_match_player_rows


def _summary_fixture() -> dict:
    return {
        "rosters": [
            {
                "homeAway": "home",
                "team": {"displayName": "LA Galaxy"},
                "roster": [
                    {
                        "starter": True,
                        "subbedIn": False,
                        "athlete": {"id": "1", "displayName": "Home Keeper"},
                        "position": {"name": "Goalkeeper"},
                        "stats": [
                            {"name": "shotsFaced", "value": 5.0},
                            {"name": "goalsConceded", "value": 1.0},
                        ],
                    },
                    {
                        "starter": True,
                        "subbedIn": False,
                        "athlete": {"id": "2", "displayName": "Home Striker"},
                        "position": {"name": "Forward"},
                        "stats": [
                            {"name": "totalShots", "value": 4.0},
                            {"name": "shotsOnTarget", "value": 2.0},
                            {"name": "totalGoals", "value": 1.0},
                            {"name": "goalAssists", "value": 0.0},
                        ],
                    },
                    {
                        "starter": False,
                        "subbedIn": True,
                        "athlete": {"id": "3", "displayName": "Home Sub"},
                        "position": {"name": "Midfielder"},
                        "stats": [
                            {"name": "totalShots", "value": 1.0},
                            {"name": "shotsOnTarget", "value": 0.0},
                            {"name": "totalGoals", "value": 0.0},
                            {"name": "goalAssists", "value": 1.0},
                        ],
                    },
                ],
            },
            {
                "homeAway": "away",
                "team": {"displayName": "LAFC"},
                "roster": [
                    {
                        "starter": True,
                        "subbedIn": False,
                        "athlete": {"id": "4", "displayName": "Away Winger"},
                        "position": {"name": "Forward"},
                        "stats": [
                            {"name": "totalShots", "value": 3.0},
                            {"name": "shotsOnTarget", "value": 1.0},
                            {"name": "totalGoals", "value": 0.0},
                            {"name": "goalAssists", "value": 0.0},
                        ],
                    },
                ],
            },
        ]
    }


class EspnLineupsTests(unittest.TestCase):
    def test_league_slugs_cover_engine_leagues(self) -> None:
        for league in ("epl", "la_liga", "bundesliga", "serie_a", "ligue_1", "mls"):
            self.assertIn(league, LEAGUE_ESPN_SLUGS)

    def test_extract_match_player_rows_splits_sides_and_flags_starters(self) -> None:
        rows = extract_match_player_rows(_summary_fixture(), event_id="evt1")

        self.assertEqual(len(rows), 4)
        by_name = {row["player_name"]: row for row in rows}

        striker = by_name["Home Striker"]
        self.assertEqual(striker["team"], "LA Galaxy")
        self.assertEqual(striker["side"], "home")
        self.assertTrue(striker["starter"])
        self.assertFalse(striker["is_goalkeeper"])
        self.assertEqual(striker["total_shots"], 4.0)
        self.assertEqual(striker["shots_on_target"], 2.0)
        self.assertEqual(striker["total_goals"], 1.0)

        sub = by_name["Home Sub"]
        self.assertFalse(sub["starter"])
        self.assertTrue(sub["subbed_in"])
        self.assertEqual(sub["goal_assists"], 1.0)

        keeper = by_name["Home Keeper"]
        self.assertTrue(keeper["is_goalkeeper"])
        # Keeper stat block has no totalShots entry -- missing stats default
        # to 0.0 rather than raising.
        self.assertEqual(keeper["total_shots"], 0.0)

        away = by_name["Away Winger"]
        self.assertEqual(away["side"], "away")
        self.assertEqual(away["team"], "LAFC")

    def test_extract_match_player_rows_handles_missing_rosters(self) -> None:
        self.assertEqual(extract_match_player_rows({}, event_id="evt2"), [])



def _event(event_id: str, iso_date: str, state: str = "pre") -> dict:
    """One ESPN scoreboard event, trimmed to what `fetch_events` reads."""
    return {
        "id": event_id,
        "date": iso_date,
        "competitions": [
            {
                "status": {"type": {"state": state}},
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": "Home FC"}, "score": "0"},
                    {"homeAway": "away", "team": {"displayName": "Away FC"}, "score": "0"},
                ],
            }
        ],
    }


class WindowGuardTests(unittest.TestCase):
    """`fetch_events` must not return an event from outside the window it asked for.

    WHY THIS EXISTS. Nothing used to compare a returned event against the requested
    dates, so a 200 carrying another period's events became fixtures for the requested
    date -- and `build_soccer_artifacts._attach_confirmed_starters` then set
    `start_probability` from the wrong lineup, which is the input the conditional shot
    ladder and the goal mixture both key off. Lane `soccer-espn-window-validation`
    could NOT demonstrate the stale 200 live (on 2026-09-16 ESPN returned 400 to all
    10 range probes), so this is a guard against a shape the endpoint has produced
    before rather than a fix for a measured failure. The tests say which is which.
    """

    def _fetch(self, events: list[dict], windows: list[str]):
        from unittest.mock import patch as _patch

        from syndicate.features.soccer.ingestion import espn_lineups

        with _patch.object(espn_lineups, "fetch_espn_scoreboard", return_value={"events": events}):
            return espn_lineups.fetch_events("epl", date_windows=windows, statuses={"pre", "in", "post"})

    def test_an_off_window_event_is_dropped(self) -> None:
        rows = self._fetch([_event("1", "2026-09-09T14:00Z")], ["20260916"])
        self.assertEqual(rows, [], "an event a week outside the window became a fixture for it")

    def test_an_in_window_event_is_kept(self) -> None:
        rows = self._fetch([_event("1", "2026-09-16T14:00Z")], ["20260916"])
        self.assertEqual([r["event_id"] for r in rows], ["1"])

    def test_a_late_kickoff_that_lands_on_the_NEXT_utc_day_is_KEPT(self) -> None:
        """ESPN keys `dates` to US Eastern; a 19:30 ET kickoff on the 15th is
        2026-09-16T23:30Z. An exact UTC-day match would delete a real fixture, which
        is why the guard carries a one-day skirt."""
        rows = self._fetch([_event("1", "2026-09-16T23:30Z")], ["20260915"])
        self.assertEqual([r["event_id"] for r in rows], ["1"])

    def test_an_event_with_an_unreadable_date_is_KEPT(self) -> None:
        """An unreadable date is not evidence that the event is off-window, and a
        guard that drops what it cannot parse would hide a feed change as a quiet
        shortfall."""
        rows = self._fetch([_event("1", "not-a-date")], ["20260916"])
        self.assertEqual([r["event_id"] for r in rows], ["1"])

    def test_an_unparseable_window_disables_the_filter_rather_than_dropping_everything(self) -> None:
        rows = self._fetch([_event("1", "2026-09-16T14:00Z")], ["whenever"])
        self.assertEqual([r["event_id"] for r in rows], ["1"])

    def test_a_range_window_keeps_both_ends_and_drops_outside(self) -> None:
        rows = self._fetch(
            [
                _event("inside-start", "2026-09-14T14:00Z"),
                _event("inside-end", "2026-09-20T14:00Z"),
                _event("outside", "2026-10-05T14:00Z"),
            ],
            ["20260914-20260920"],
        )
        self.assertEqual(sorted(r["event_id"] for r in rows), ["inside-end", "inside-start"])

    def test_the_drop_is_announced_so_it_is_observable_in_production(self) -> None:
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self._fetch([_event("1", "2026-09-09T14:00Z")], ["20260916"])
        self.assertIn("ESPN_OFF_WINDOW_EVENTS_DROPPED", buffer.getvalue())
        self.assertIn("dropped=1", buffer.getvalue())


class BuilderSendsBareDateTests(unittest.TestCase):
    """The builder must not send a form ESPN refuses.

    Measured 2026-09-16 03:51Z: every `dates=` range returned 400, including two the
    module docstring recorded as 200 the day before, while the bare `YYYYMMDD`
    returned 200. The one-day range therefore bought a guaranteed 400 plus a retry on
    every build, for a request the fallback then issued in this exact shape anyway.
    """

    def _load_builder(self):
        import importlib.util
        from pathlib import Path as _Path

        root = _Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "builder_under_window_test", root / "scripts" / "build_soccer_artifacts.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_fetch_fixtures_sends_a_bare_date_not_a_one_day_range(self) -> None:
        from unittest.mock import patch as _patch

        module = self._load_builder()
        with _patch.object(module, "fetch_events", return_value=[]) as mocked:
            module._fetch_fixtures("epl", "2026-09-16")
        windows = mocked.call_args.kwargs["date_windows"]
        self.assertEqual(windows, ["20260916"])
        self.assertNotIn("-", windows[0], "a range form costs a guaranteed 400 as of 2026-09-16")


if __name__ == "__main__":
    unittest.main()


class EspnRequestsUseNoCustomHeadersTests(unittest.TestCase):
    """ESPN's public site API 403s Render's outbound IP for this repo's
    generic browser-spoof User-Agent -- confirmed for 3 other call sites
    (ded23a0d) and, live 2026-08-05, for THIS module's fetch_espn_scoreboard
    too (a 403 for ned.1/por.1's date-ranged query silently blocked
    odds_history for all of soccer, see todo.md's "ROOT CAUSED 2026-08-05"
    entry). A prior probe (81f091b7) had cleared this exact header string
    for a narrower request shape (usa.1, no date-range param) and that
    conclusion did not generalize. No custom header is the only
    confirmed-safe choice; lock it in so a future edit can't quietly
    reintroduce one.
    """

    def test_fetch_espn_scoreboard_sends_no_custom_headers(self) -> None:
        from unittest.mock import MagicMock, patch

        from syndicate.features.soccer.ingestion.espn_lineups import fetch_espn_scoreboard

        fake_response = MagicMock()
        fake_response.json.return_value = {"events": []}
        with patch("syndicate.features.soccer.ingestion.espn_lineups.requests.get", return_value=fake_response) as mocked_get:
            fetch_espn_scoreboard("mls", date_range="20260807-20260807")

        mocked_get.assert_called_once()
        self.assertNotIn("headers", mocked_get.call_args.kwargs)

    def test_fetch_match_summary_sends_no_custom_headers(self) -> None:
        from unittest.mock import MagicMock, patch

        from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary

        fake_response = MagicMock()
        fake_response.json.return_value = {}
        with patch("syndicate.features.soccer.ingestion.espn_lineups.requests.get", return_value=fake_response) as mocked_get:
            fetch_match_summary("mls", "123")

        mocked_get.assert_called_once()
        self.assertNotIn("headers", mocked_get.call_args.kwargs)

    def test_fetch_team_roster_sends_no_custom_headers(self) -> None:
        from unittest.mock import MagicMock, patch

        from syndicate.features.soccer.ingestion.espn_teams import fetch_team_roster

        fake_response = MagicMock()
        fake_response.json.return_value = {"athletes": []}
        with patch("syndicate.features.soccer.ingestion.espn_teams.requests.get", return_value=fake_response) as mocked_get:
            fetch_team_roster("mls", "12345")

        mocked_get.assert_called_once()
        self.assertNotIn("headers", mocked_get.call_args.kwargs)
