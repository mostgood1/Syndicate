from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.shared.game_chip_scoreboard import build_game_chip
from syndicate.features.shared.game_chip_scoreboard import build_game_chips


class GameChipBuilderTests(unittest.TestCase):
    def test_mlb_live_chip_with_inning_token_and_leader(self) -> None:
        game = {
            "gamePk": 823759,
            "away": {"abbr": "NYY", "score": 4},
            "home": {"abbr": "BOS", "score": 2},
            "status": {"abstract": "Live", "detailed": "In Progress - Top 7th"},
        }

        chip = build_game_chip("mlb", game)

        self.assertEqual(chip["state"], "live")
        self.assertEqual(chip["status_token"], "TOP 7")
        # `name` is empty here because this fixture carries only labels; the
        # key is always present so consumers see one chip shape, and the board
        # join falls back to `abbr` exactly as it did before names existed.
        self.assertEqual(chip["away"], {"abbr": "NYY", "name": "", "score": "4"})
        self.assertEqual(chip["home"], {"abbr": "BOS", "name": "", "score": "2"})
        self.assertEqual(chip["leader"], "away")
        self.assertEqual(chip["game_key"], "823759")

    def test_chip_carries_the_full_club_name_when_the_provider_has_one(self) -> None:
        """The abbr is a display label, not a reliable join key: soccer
        tri-codes collide across leagues (STL is both Standard Liege and
        St. Louis CITY SC), so `team_aliases` refuses to resolve them and an
        abbr-only join matched 0 of 300 soccer board rows on 2026-08-08."""
        chip = build_game_chip(
            "soccer",
            {
                "gamePk": "401875654",
                "away": {"abbr": "TEL", "name": "Telstar"},
                "home": {"abbr": "NEC", "name": "NEC Nijmegen"},
            },
        )

        self.assertEqual(chip["away"]["name"], "Telstar")
        self.assertEqual(chip["home"]["name"], "NEC Nijmegen")
        self.assertEqual(chip["away"]["abbr"], "TEL")

    def test_soccer_chip_carries_league_display(self) -> None:
        # #162: soccer's game dicts (soccer/cards.py) stamp league/
        # league_display -- passed through so a consumer can show "MLS"/
        # "La Liga" instead of the generic "soccer" sport slug.
        game = {
            "gamePk": "761689",
            "league": "mls",
            "league_display": "MLS",
            "away": {"abbr": "ATX", "score": 0},
            "home": {"abbr": "HOU", "score": 0},
            "status": {"abstract": "Scheduled"},
        }

        chip = build_game_chip("soccer", game)

        self.assertEqual(chip["league"], "mls")
        self.assertEqual(chip["league_display"], "MLS")

    def test_non_soccer_chip_has_no_league_fields(self) -> None:
        game = {"gamePk": 1, "away": {"abbr": "NYY", "score": 4}, "home": {"abbr": "BOS", "score": 2}}

        chip = build_game_chip("mlb", game)

        self.assertIsNone(chip["league"])
        self.assertIsNone(chip["league_display"])

    def test_mlb_live_chip_from_live_state_half_and_inning_fields(self) -> None:
        game = {
            "gamePk": 1,
            "away": {"abbr": "SD", "score": 1},
            "home": {"abbr": "LAD", "score": 3},
            "live_state": {"in_progress": True, "half": "Bottom", "inning": 4},
        }

        chip = build_game_chip("mlb", game)

        self.assertEqual(chip["state"], "live")
        self.assertEqual(chip["status_token"], "BOT 4")
        self.assertEqual(chip["leader"], "home")

    def test_wnba_live_chip_with_period_and_clock(self) -> None:
        game = {
            "game_id": "401736290",
            "away": {"abbr": "LV", "score": 61},
            "home": {"abbr": "NY", "score": 64},
            "live_state": {"in_progress": True, "period": 3, "clock": "6:12"},
        }

        chip = build_game_chip("wnba", game)

        self.assertEqual(chip["state"], "live")
        self.assertEqual(chip["status_token"], "Q3 6:12")
        self.assertEqual(chip["leader"], "home")

    def test_pregame_chip_has_scheduled_token_and_no_scores(self) -> None:
        game = {
            "gamePk": 2,
            "away": {"abbr": "CHC", "score": 0},
            "home": {"abbr": "ATL", "score": 0},
            "status": {"abstract": "Scheduled", "detailed": "Scheduled"},
            # 23:10 UTC == 6:10 PM Central during daylight saving time.
            "scheduled_start_utc": "2026-07-24T23:10:00Z",
        }

        with patch("syndicate.features.shared.game_chip_scoreboard.central_today_iso", return_value="2026-07-24"):
            chip = build_game_chip("mlb", game)

        self.assertEqual(chip["state"], "pregame")
        self.assertEqual(chip["status_token"], "6:10P CT")
        self.assertIsNone(chip["away"]["score"])
        self.assertIsNone(chip["home"]["score"])
        self.assertIsNone(chip["leader"])

    def test_pregame_chip_on_a_different_day_includes_date(self) -> None:
        # A chip strip can span several days at once (soccer's week-keyed
        # schedule is the clearest case), so a game not on "today" gets a
        # day/date prefix instead of a bare, ambiguous time.
        game = {
            "gamePk": 7,
            "away": {"abbr": "CHC", "score": 0},
            "home": {"abbr": "ATL", "score": 0},
            "status": {"abstract": "Scheduled", "detailed": "Scheduled"},
            "scheduled_start_utc": "2026-07-24T23:10:00Z",
        }

        with patch("syndicate.features.shared.game_chip_scoreboard.central_today_iso", return_value="2026-07-25"):
            chip = build_game_chip("mlb", game)

        self.assertEqual(chip["state"], "pregame")
        self.assertEqual(chip["status_token"], "Fri Jul 24 · 6:10P CT")

    def test_pregame_chip_falls_back_to_display_start_time(self) -> None:
        # MLB's cards payload has no ISO timestamp -- only a pre-formatted
        # local "startTime" like "3:10 PM". Same-day game: no date prefix.
        game = {
            "gamePk": 6,
            "away": {"abbr": "COL"},
            "home": {"abbr": "MIL"},
            "status": {"abstract": "Preview", "detailed": "Pre-Game"},
            "gameDate": "2026-07-24",
            "startTime": "3:10 PM",
        }

        with patch("syndicate.features.shared.game_chip_scoreboard.central_today_iso", return_value="2026-07-24"):
            chip = build_game_chip("mlb", game)

        self.assertEqual(chip["state"], "pregame")
        self.assertEqual(chip["status_token"], "3:10P CT")

    def test_pregame_chip_on_a_different_day_includes_date_without_iso_timestamp(self) -> None:
        # Same fallback path (no ISO timestamp, only a pre-formatted
        # "startTime"), but the game isn't today -- the date-only
        # gameDate/game_date field must still surface a day prefix, not
        # silently look identical to a same-day game (#160).
        game = {
            "gamePk": 8,
            "away": {"abbr": "COL"},
            "home": {"abbr": "MIL"},
            "status": {"abstract": "Preview", "detailed": "Pre-Game"},
            "gameDate": "2026-07-24",
            "startTime": "3:10 PM",
        }

        with patch("syndicate.features.shared.game_chip_scoreboard.central_today_iso", return_value="2026-07-25"):
            chip = build_game_chip("mlb", game)

        self.assertEqual(chip["state"], "pregame")
        self.assertEqual(chip["status_token"], "Fri Jul 24 · 3:10P CT")

    def test_final_chip_reports_final_token(self) -> None:
        game = {
            "gamePk": 3,
            "away": {"abbr": "SEA", "score": 5},
            "home": {"abbr": "MIN", "score": 7},
            "status": {"abstract": "Final", "detailed": "Final"},
        }

        chip = build_game_chip("mlb", game)

        self.assertEqual(chip["state"], "final")
        self.assertEqual(chip["status_token"], "FINAL")
        self.assertEqual(chip["leader"], "home")

    def test_nhl_style_game_state_fields(self) -> None:
        game = {
            "gamePk": 4,
            "away": {"abbr": "COL"},
            "home": {"abbr": "MIL"},
            "score": {"away": 2, "home": 1},
            "gameState": "LIVE",
            "period": 2,
            "clock": "12:34",
        }

        chip = build_game_chip("nhl", game)

        self.assertEqual(chip["state"], "live")
        self.assertEqual(chip["status_token"], "P2 12:34")
        self.assertEqual(chip["leader"], "away")

    def test_start_time_utc_resolved_from_iso_timestamp_for_a_live_game(self) -> None:
        # #160 follow-up: the Games mini-card strip sorts by each game's
        # ORIGINAL scheduled start, not its current live clock -- a live
        # game must still carry the timestamp it started at, not "now".
        game = {
            "gamePk": 823759,
            "away": {"abbr": "NYY", "score": 4},
            "home": {"abbr": "BOS", "score": 2},
            "status": {"abstract": "Live", "detailed": "In Progress - Top 7th"},
            "scheduled_start_utc": "2026-07-30T23:10:00Z",
        }

        chip = build_game_chip("mlb", game)

        self.assertEqual(chip["state"], "live")
        self.assertEqual(chip["start_time_utc"], "2026-07-30T23:10:00+00:00")

    def test_start_time_utc_resolved_from_date_and_display_time_fallback(self) -> None:
        # Same pre-formatted-local-time-only shape as
        # test_pregame_chip_falls_back_to_display_start_time -- no ISO
        # timestamp, only a plain date plus a "3:10 PM" display string.
        game = {
            "gamePk": 6,
            "away": {"abbr": "COL"},
            "home": {"abbr": "MIL"},
            "status": {"abstract": "Preview", "detailed": "Pre-Game"},
            "gameDate": "2026-07-24",
            "startTime": "3:10 PM",
        }

        with patch("syndicate.features.shared.game_chip_scoreboard.central_today_iso", return_value="2026-07-24"):
            chip = build_game_chip("mlb", game)

        # 3:10 PM Central == 20:10 UTC during daylight saving time.
        self.assertEqual(chip["start_time_utc"], "2026-07-24T20:10:00+00:00")

    def test_start_time_utc_is_none_without_any_resolvable_field(self) -> None:
        game = {
            "gamePk": 9,
            "away": {"abbr": "COL"},
            "home": {"abbr": "MIL"},
            "status": {"abstract": "Preview", "detailed": "Pre-Game"},
        }

        chip = build_game_chip("mlb", game)

        self.assertIsNone(chip["start_time_utc"])

    def test_wnba_pregame_start_time_resolved_from_camel_case_start_time_field(self) -> None:
        # #160 follow-up: WNBA's own game-list builder (wnba/cards.py)
        # stamps the real ISO commence timestamp onto "startTime"
        # (camelCase) rather than any of the snake_case ISO fields checked
        # above -- missing this key meant every WNBA chip's status_token
        # and start_time_utc came back None, so WNBA games sorted last on
        # the Games strip and showed no date/time at all (indistinguishable
        # from a phantom card).
        game = {
            "game_id": "401857900",
            "away": {"abbr": "NYL"},
            "home": {"abbr": "LVA"},
            "status": "Scheduled",
            "startTime": "2026-07-31T00:00:00Z",
        }

        with patch("syndicate.features.shared.game_chip_scoreboard.central_today_iso", return_value="2026-07-30"):
            chip = build_game_chip("wnba", game)

        self.assertEqual(chip["state"], "pregame")
        self.assertEqual(chip["start_time_utc"], "2026-07-31T00:00:00+00:00")
        self.assertIsNotNone(chip["status_token"])

    def test_start_time_resolved_from_nested_odds_commence_time(self) -> None:
        game = {
            "game_id": "401857901",
            "away": {"abbr": "NYL"},
            "home": {"abbr": "LVA"},
            "status": "Scheduled",
            "odds": {"commence_time": "2026-07-31T00:00:00Z"},
        }

        chip = build_game_chip("wnba", game)

        self.assertEqual(chip["start_time_utc"], "2026-07-31T00:00:00+00:00")


class BuildGameChipsTests(unittest.TestCase):
    def test_build_game_chips_reads_registered_providers(self) -> None:
        class _FakeContext:
            context_label = "2026-07-24"

        class _FakeProvider:
            slug = "mlb"

            def resolve_context(self, *, requested_date=None, season=None, week=None):
                return _FakeContext()

            def is_active(self, *, today_value, context_label):
                return True

            def games(self, context, *, is_active_today):
                return [
                    {
                        "gamePk": 5,
                        "away": {"abbr": "NYY", "score": 4},
                        "home": {"abbr": "BOS", "score": 2},
                        "status": {"abstract": "Live", "detailed": "In Progress - Top 7th"},
                    }
                ]

        with patch(
            "syndicate.features.shared.sport_data_provider.get_sport_data_provider",
            side_effect=lambda slug: _FakeProvider() if slug == "mlb" else None,
        ):
            with patch("syndicate.features.shared.game_chip_scoreboard._cache", {}):
                chips = build_game_chips("2026-07-24", ["mlb", "nba"])

        self.assertEqual(len(chips), 1)
        self.assertEqual(chips[0]["sport"], "mlb")
        self.assertEqual(chips[0]["status_token"], "TOP 7")

    def test_build_game_chips_survives_provider_failure(self) -> None:
        class _BrokenProvider:
            slug = "mlb"

            def resolve_context(self, *, requested_date=None, season=None, week=None):
                raise RuntimeError("boom")

            def is_active(self, *, today_value, context_label):
                return True

            def games(self, context, *, is_active_today):
                return []

        with patch(
            "syndicate.features.shared.sport_data_provider.get_sport_data_provider",
            return_value=_BrokenProvider(),
        ):
            with patch("syndicate.features.shared.game_chip_scoreboard._cache", {}):
                chips = build_game_chips("2026-07-24", ["mlb"])

        self.assertEqual(chips, [])


if __name__ == "__main__":
    unittest.main()
