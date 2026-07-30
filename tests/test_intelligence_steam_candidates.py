from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.intelligence import _classify_candidate_with_reason
from syndicate.features.intelligence import _steam_candidates_for_sport
from syndicate.features.mlb.hr_targets import mlb_player_game_lookup_for_date


LIVE_PROP_STEAM_EVENT = {
    "capture_phase": "live",
    "timestamp": "2026-07-29T23:05:00+00:00",
    "game_id": "824003",
    "sport": "mlb",
    "market_id": "mlb:824003:batter_hits:willy_adames",
    "player_id": None,
    "player_name": "willy adames",
    "selection": "Over",
    "market_type": "batter_hits",
    "event_type": "update",
    "line": 1.5,
    "price": 145.0,
    "implied_prob": 0.408,
    "source": "oddsapi",
    "is_live": True,
    "steam": {
        "line_delta": 0.5,
        "odds_delta": 30.0,
        "window_seconds": 120.0,
        "capture_phase": "live",
        "previous_line": 1.0,
        "previous_odds": 115.0,
    },
}

PREGAME_TEAM_STEAM_EVENT = {
    "capture_phase": "closing",
    "timestamp": "2026-07-29T22:00:00+00:00",
    "game_id": "823598",
    "sport": "mlb",
    "player_name": "Los Angeles Dodgers",
    "selection": None,
    "market_type": "totals",
    "event_type": "update",
    "line": 8.5,
    "price": -114.0,
    "implied_prob": 0.532,
    "source": "oddsapi",
    "is_live": False,
    "steam": {
        "line_delta": 1.0,
        "odds_delta": None,
        "window_seconds": 300.0,
        "capture_phase": "closing",
        "previous_line": 7.5,
        "previous_odds": -114.0,
    },
}


def _sport(slug: str = "mlb", context_label: str = "2026-07-29") -> dict:
    return {"slug": slug, "name": slug.upper(), "context_label": context_label}


class SteamCandidatesForSportTests(unittest.TestCase):
    def test_live_prop_steam_event_becomes_a_live_prop_candidate(self) -> None:
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[LIVE_PROP_STEAM_EVENT],
        ):
            candidates = _steam_candidates_for_sport(_sport())

        self.assertEqual(len(candidates), 1, candidates)
        candidate = candidates[0]
        self.assertEqual(candidate["candidate_type"], "steam")
        self.assertEqual(candidate["lane"], "live")
        self.assertTrue(candidate["is_live"])
        # Case-inconsistent source data ("willy adames") title-cased for display.
        self.assertEqual(candidate["player_name"], "Willy Adames")
        self.assertIn("Over 1.5", candidate["pick"])
        self.assertEqual(candidate["line_odds_movement"]["opening_line"], 1.0)
        self.assertEqual(candidate["line_odds_movement"]["latest_line"], 1.5)
        self.assertEqual(candidate["line_odds_movement"]["line_direction"], "up")
        classified, reason = _classify_candidate_with_reason(candidate)
        self.assertIsNone(reason)
        self.assertIsNotNone(classified)

    def test_pregame_team_total_steam_event_has_no_player_name(self) -> None:
        # #131-adjacent: a team/game-level steam move must not carry a
        # player_name -- the frontend's market-family filter
        # (matchesClientFilters, intelligence.html) treats any candidate
        # with a truthy player_name as a "prop", which would wrongly hide a
        # team total's steam move from "Game markets" and misfile it under
        # "Player props".
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[PREGAME_TEAM_STEAM_EVENT],
        ):
            candidates = _steam_candidates_for_sport(_sport())

        self.assertEqual(len(candidates), 1, candidates)
        candidate = candidates[0]
        self.assertEqual(candidate["lane"], "pregame")
        self.assertFalse(candidate["is_live"])
        self.assertIsNone(candidate["player_name"])
        classified, reason = _classify_candidate_with_reason(candidate)
        self.assertIsNone(reason)
        self.assertIsNotNone(classified)

    def test_events_for_a_different_sport_are_excluded(self) -> None:
        wnba_event = dict(LIVE_PROP_STEAM_EVENT, sport="wnba")
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[wnba_event],
        ):
            candidates = _steam_candidates_for_sport(_sport("mlb"))
        self.assertEqual(candidates, [])

    def test_event_without_a_steam_signal_is_skipped(self) -> None:
        plain_event = {key: value for key, value in LIVE_PROP_STEAM_EVENT.items() if key != "steam"}
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[plain_event],
        ):
            candidates = _steam_candidates_for_sport(_sport())
        self.assertEqual(candidates, [])

    def test_duplicate_events_collapse_to_one_candidate(self) -> None:
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[LIVE_PROP_STEAM_EVENT, dict(LIVE_PROP_STEAM_EVENT)],
        ):
            candidates = _steam_candidates_for_sport(_sport())
        self.assertEqual(len(candidates), 1, candidates)

    def test_no_context_label_or_events_returns_empty(self) -> None:
        self.assertEqual(_steam_candidates_for_sport({"slug": "mlb", "context_label": ""}), [])
        with patch("syndicate.features.intelligence._load_steam_events_for_date", return_value=[]):
            self.assertEqual(_steam_candidates_for_sport(_sport()), [])

    def test_different_players_same_market_line_selection_get_distinct_picks(self) -> None:
        # Confirmed live 2026-07-29: candidates were generating and surviving
        # candidate_scoring (INTEL_TRACE showed real counts intact) but never
        # reached the final board. Root cause: _collect_candidates' identity
        # dedup tuple is (candidate_type, sport_slug, matchup, market, pick[,
        # game_identity]) -- with no per-game matchup resolvable from a raw
        # steam event and no game_id on many real events, two DIFFERENT
        # players sharing the same generic "Over 4.5" pick text collided on
        # identity and all but the highest-scored one were silently dropped.
        # Regression: pick must be unique per subject even with identical
        # market/line/selection and no game_id -- this test constructs
        # exactly that collision shape and asserts it no longer collides.
        event_a = dict(LIVE_PROP_STEAM_EVENT, player_name="Player A", game_id=None)
        event_b = dict(LIVE_PROP_STEAM_EVENT, player_name="Player B", game_id=None)
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[event_a, event_b],
        ):
            candidates = _steam_candidates_for_sport(_sport())

        self.assertEqual(len(candidates), 2, candidates)
        picks = {c["pick"] for c in candidates}
        matchups = {c["matchup"] for c in candidates}
        markets = {c["market"] for c in candidates}
        # The actual identity-dedup collision shape: matchup and market
        # identical (both "-" / same market text) -- pick is the only field
        # that can disambiguate without a real game_id, so it must differ.
        self.assertEqual(len(matchups), 1, candidates)
        self.assertEqual(len(markets), 1, candidates)
        self.assertEqual(len(picks), 2, picks)
        self.assertTrue(any("Player A" in pick for pick in picks), picks)
        self.assertTrue(any("Player B" in pick for pick in picks), picks)


class SteamMatchupResolutionTests(unittest.TestCase):
    # #137 follow-up 3: user reported the soccer steam section was
    # unusable -- every row showed matchup "-", no way to tell which match
    # a player belonged to. Root cause: soccer's steam events carry a real,
    # consistent OddsAPI-hash event_id, but dashboard_games (the only
    # lookup that existed) is single-league-curated and keyed by the sim's
    # unrelated ESPN-numeric event_id -- the two id spaces never intersect.
    def test_event_level_home_away_team_wins_over_dashboard_lookup(self) -> None:
        # odds_refresh_tracking.py now stamps home_team/away_team directly
        # onto new events for sports whose raw rows carry those columns
        # (soccer) -- most direct source, should be used before any lookup.
        event = dict(LIVE_PROP_STEAM_EVENT, sport="soccer", home_team="Inter Miami", away_team="LA Galaxy", game_id="abc123")
        sport = _sport(slug="soccer")
        sport["dashboard_games"] = []  # would resolve to "-" if this were consulted
        with patch("syndicate.features.intelligence._load_steam_events_for_date", return_value=[event]):
            candidates = _steam_candidates_for_sport(sport)
        self.assertEqual(len(candidates), 1, candidates)
        # Converted to tricodes (not the raw OddsAPI team names) so this
        # candidate type displays and groups consistently with every other
        # soccer card on the Layer 2 mini game-card strip.
        self.assertEqual(candidates[0]["matchup"], "LA @ MIA")

    def test_soccer_falls_back_to_the_raw_odds_row_lookup_when_event_has_no_team_names(self) -> None:
        # Events recorded before the source-side stamp existed have no
        # home_team/away_team of their own -- soccer specifically can still
        # resolve them via the raw OddsAPI fetch rows (game_odds_current.csv/
        # props/<date>.csv), which _soccer_steam_matchup_lookup reads.
        event = dict(LIVE_PROP_STEAM_EVENT, sport="soccer", game_id="deadbeef")
        event.pop("home_team", None)
        event.pop("away_team", None)
        sport = _sport(slug="soccer")
        sport["dashboard_games"] = []
        with patch("syndicate.features.intelligence._load_steam_events_for_date", return_value=[event]), patch(
            "syndicate.features.intelligence._soccer_steam_matchup_lookup",
            return_value={"deadbeef": "NYCFC @ Inter Miami"},
        ):
            candidates = _steam_candidates_for_sport(sport)
        self.assertEqual(len(candidates), 1, candidates)
        self.assertEqual(candidates[0]["matchup"], "NYCFC @ Inter Miami")

    def test_soccer_matchup_lookup_never_raises_when_soccer_sources_unavailable(self) -> None:
        from syndicate.features.intelligence import _soccer_steam_matchup_lookup

        with patch(
            "syndicate.features.soccer.sources.active_leagues_for_date",
            side_effect=RuntimeError("boom"),
        ):
            self.assertEqual(_soccer_steam_matchup_lookup("2026-07-29"), {})


MLB_PROP_STEAM_EVENT_NO_GAME_ID = {
    "capture_phase": "closing",
    "timestamp": "2026-07-30T22:00:00+00:00",
    "sport": "mlb",
    "player_name": "nick sogard",
    "selection": "Over",
    "market_type": "batter_home_runs",
    "event_type": "update",
    "line": 0.5,
    "price": 650.0,
    "implied_prob": 0.133,
    "source": "oddsapi",
    "is_live": False,
    "steam": {
        "line_delta": None,
        "odds_delta": 120.0,
        "window_seconds": 300.0,
        "capture_phase": "closing",
        "previous_line": 0.5,
        "previous_odds": 530.0,
    },
}


class MlbSteamGameIdResolutionTests(unittest.TestCase):
    # Confirmed live 2026-07-30: MLB prop steam events (_flatten_mlb_props'
    # output feeds odds_refresh_tracking.py's lifecycle-event builder) carry
    # NO game_id, event_id, home_team, or away_team at all -- unlike soccer,
    # the raw hitter/pitcher props payload has no per-row game linkage
    # whatsoever, so every one of these candidates previously landed under
    # a shared "mlb|-" grouping key with no resolvable matchup.
    def test_mlb_event_without_game_id_resolves_via_roster_lookup(self) -> None:
        sport = _sport(slug="mlb")
        sport["dashboard_games"] = [
            {
                "gamePk": 824555,
                "away": {"abbr": "BOS"},
                "home": {"abbr": "NYY"},
            }
        ]
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[MLB_PROP_STEAM_EVENT_NO_GAME_ID],
        ), patch(
            "syndicate.features.mlb.hr_targets.mlb_player_game_lookup_for_date",
            return_value={"nick sogard": 824555},
        ):
            candidates = _steam_candidates_for_sport(sport)

        self.assertEqual(len(candidates), 1, candidates)
        candidate = candidates[0]
        self.assertEqual(candidate["game_id"], "824555")
        self.assertEqual(candidate["event_id"], "824555")
        self.assertEqual(candidate["game_pk"], 824555)
        self.assertEqual(candidate["matchup"], "BOS @ NYY")

    def test_mlb_event_without_game_id_and_no_roster_match_falls_back_to_dash(self) -> None:
        # No roster entry for this player -- must degrade to "-" rather than
        # raising or inventing a game, exactly like the pre-fix behavior for
        # every other unresolvable event.
        sport = _sport(slug="mlb")
        sport["dashboard_games"] = []
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[MLB_PROP_STEAM_EVENT_NO_GAME_ID],
        ), patch(
            "syndicate.features.mlb.hr_targets.mlb_player_game_lookup_for_date",
            return_value={},
        ):
            candidates = _steam_candidates_for_sport(sport)

        self.assertEqual(len(candidates), 1, candidates)
        candidate = candidates[0]
        self.assertEqual(candidate["game_id"], "")
        self.assertEqual(candidate["matchup"], "-")

    def test_event_with_its_own_game_id_skips_the_roster_lookup(self) -> None:
        # The roster-name join is a last resort -- an event that already
        # carries a real game_id (the normal, non-prop-collision case) must
        # not be overridden by a same-named roster entry from another game.
        event = dict(MLB_PROP_STEAM_EVENT_NO_GAME_ID, game_id="999111")
        sport = _sport(slug="mlb")
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[event],
        ), patch(
            "syndicate.features.mlb.hr_targets.mlb_player_game_lookup_for_date",
            return_value={"nick sogard": 824555},
        ):
            candidates = _steam_candidates_for_sport(sport)

        self.assertEqual(len(candidates), 1, candidates)
        self.assertEqual(candidates[0]["game_id"], "999111")


class MlbPlayerGameLookupForDateTests(unittest.TestCase):
    # Direct coverage of the new roster-glob lookup itself: game_pk only
    # exists in the flat roster filename (roster_<n>_<AWAY>_at_<HOME>_pk
    # <game_pk>_g1.json), never as a field inside the payload.
    def _write_roster_fixture(self, snapshot_dir: Path, *, filename: str) -> None:
        payload = {
            "away": {
                "team": {"abbreviation": "BOS"},
                "lineup": {
                    "batters": [{"name": "Nick Sogard", "player": {"id": 1}}],
                },
                "starter_profile": {"name": "Away Starter", "player": {"id": 2}},
            },
            "home": {
                "team": {"abbreviation": "NYY"},
                "lineup": {
                    "batters": [{"name": "Aaron Judge", "player": {"id": 3}}],
                },
                "starter_profile": {"name": "Home Starter", "player": {"id": 4}},
            },
        }
        (snapshot_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    def test_resolves_game_pk_for_every_lineup_name_from_the_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_root = Path(tmp)
            snapshot_dir = snapshot_root / "2026-07-30"
            snapshot_dir.mkdir(parents=True)
            self._write_roster_fixture(snapshot_dir, filename="roster_0_BOS_at_NYY_pk824555_g1.json")

            with patch(
                "syndicate.features.mlb.hr_targets._daily_snapshot_root",
                return_value=snapshot_root,
            ):
                lookup = mlb_player_game_lookup_for_date("2026-07-30")

        self.assertEqual(lookup.get("nick sogard"), 824555)
        self.assertEqual(lookup.get("aaron judge"), 824555)
        self.assertEqual(lookup.get("away starter"), 824555)
        self.assertEqual(lookup.get("home starter"), 824555)

    def test_missing_snapshot_dir_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_root = Path(tmp)
            with patch(
                "syndicate.features.mlb.hr_targets._daily_snapshot_root",
                return_value=snapshot_root,
            ):
                self.assertEqual(mlb_player_game_lookup_for_date("2026-07-30"), {})

    def test_no_selected_date_returns_empty(self) -> None:
        self.assertEqual(mlb_player_game_lookup_for_date(""), {})


if __name__ == "__main__":
    unittest.main()
