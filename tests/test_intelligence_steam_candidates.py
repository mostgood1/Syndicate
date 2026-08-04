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
            return_value={"deadbeef": {"matchup": "NYCFC @ Inter Miami", "league_display": "MLS"}},
        ):
            candidates = _steam_candidates_for_sport(sport)
        self.assertEqual(len(candidates), 1, candidates)
        self.assertEqual(candidates[0]["matchup"], "NYCFC @ Inter Miami")
        # #162: the league resolved by _soccer_steam_matchup_lookup should
        # replace the generic "Soccer" sport label on this candidate.
        self.assertEqual(candidates[0]["sport"], "MLS")

    def test_soccer_steam_candidate_uses_league_display_from_dashboard_games(self) -> None:
        # #162: soccer's game dicts (soccer/cards.py) stamp league_display
        # ("MLS", "La Liga", ...) -- a steam candidate resolvable to one of
        # today's dashboard_games via game_id should show the real league
        # instead of the generic "Soccer" sport label.
        event = dict(LIVE_PROP_STEAM_EVENT, sport="soccer", game_id="761689")
        event.pop("home_team", None)
        event.pop("away_team", None)
        sport = _sport(slug="soccer")
        sport["dashboard_games"] = [
            {
                "gamePk": "761689",
                "league": "la_liga",
                "league_display": "La Liga",
                "away": {"abbr": "RMA"},
                "home": {"abbr": "BAR"},
            }
        ]
        with patch("syndicate.features.intelligence._load_steam_events_for_date", return_value=[event]), patch(
            "syndicate.features.intelligence._soccer_steam_matchup_lookup", return_value={}
        ):
            candidates = _steam_candidates_for_sport(sport)
        self.assertEqual(len(candidates), 1, candidates)
        self.assertEqual(candidates[0]["sport"], "La Liga")

    def test_soccer_steam_candidate_uses_resolved_kickoff_date_from_lookup(self) -> None:
        # #165 follow-up: confirmed live -- every soccer steam candidate's
        # game_date got stamped with the board's own requested date ("when
        # this scan ran"), not the individual match's real kickoff date, so
        # several genuinely-Saturday MLS matches all showed "Fri Jul 31" on
        # the Games strip. _soccer_steam_matchup_lookup resolving a real
        # per-event game_date (season-schedule fuzzy match) must flow
        # through to the candidate instead of the blanket selected_date.
        event = dict(LIVE_PROP_STEAM_EVENT, sport="soccer", game_id="deadbeef")
        event.pop("home_team", None)
        event.pop("away_team", None)
        sport = _sport(slug="soccer", context_label="2026-07-31")
        sport["dashboard_games"] = []
        with patch("syndicate.features.intelligence._load_steam_events_for_date", return_value=[event]), patch(
            "syndicate.features.intelligence._soccer_steam_matchup_lookup",
            return_value={"deadbeef": {"matchup": "NSH @ DC", "league_display": "MLS", "game_date": "2026-08-01"}},
        ):
            candidates = _steam_candidates_for_sport(sport)
        self.assertEqual(len(candidates), 1, candidates)
        self.assertEqual(candidates[0]["game_date"], "2026-08-01")
        self.assertEqual(candidates[0]["source_board_date"], "2026-08-01")
        # context_label stays the scan date -- only game_date/
        # source_board_date (what the frontend's date badge actually reads
        # first) change.
        self.assertEqual(candidates[0]["context_label"], "2026-07-31")

    def test_soccer_steam_candidate_falls_back_to_selected_date_without_a_resolved_kickoff(self) -> None:
        event = dict(LIVE_PROP_STEAM_EVENT, sport="soccer", game_id="deadbeef")
        event.pop("home_team", None)
        event.pop("away_team", None)
        sport = _sport(slug="soccer", context_label="2026-07-31")
        sport["dashboard_games"] = []
        with patch("syndicate.features.intelligence._load_steam_events_for_date", return_value=[event]), patch(
            "syndicate.features.intelligence._soccer_steam_matchup_lookup",
            return_value={"deadbeef": {"matchup": "NSH @ DC", "league_display": "MLS"}},
        ):
            candidates = _steam_candidates_for_sport(sport)
        self.assertEqual(candidates[0]["game_date"], "2026-07-31")

    def test_soccer_steam_matchup_lookup_reads_commence_time_from_the_raw_odds_row(self) -> None:
        # #166: first fix attempt cross-referenced the season schedule via
        # fuzzy team-name matching -- unnecessary complexity, and buggy
        # besides (wrong field-access pattern, then no disambiguation for
        # team pairs meeting more than once in a season; still didn't work
        # end-to-end in production for reasons not fully chased down).
        # Confirmed against the real production odds CSV: the raw odds row
        # already carries its own kickoff timestamp directly --
        # "league,event_id,home_team,away_team,commence_time,market,side,
        # line,price,book" -- so this needs nothing beyond reading that
        # column off the same row already being processed.
        from syndicate.features.intelligence import _soccer_steam_matchup_lookup

        odds_rows = (
            {
                "event_id": "abc123",
                "home_team": "D.C. United",
                "away_team": "Nashville SC",
                "commence_time": "2026-08-01T23:30:00Z",
                "market": "h2h",
            },
        )
        with patch("syndicate.features.soccer.sources.active_leagues_for_date", return_value=["mls"]), patch(
            "syndicate.features.soccer.sources.game_odds_rows", return_value=odds_rows
        ), patch("syndicate.features.soccer.sources.props_odds_rows", return_value=()):
            lookup = _soccer_steam_matchup_lookup("2026-07-31")
        self.assertEqual(lookup["abc123"]["game_date"], "2026-08-01")

    def test_soccer_steam_matchup_lookup_omits_game_date_without_commence_time(self) -> None:
        from syndicate.features.intelligence import _soccer_steam_matchup_lookup

        odds_rows = ({"event_id": "abc123", "home_team": "D.C. United", "away_team": "Nashville SC"},)
        with patch("syndicate.features.soccer.sources.active_leagues_for_date", return_value=["mls"]), patch(
            "syndicate.features.soccer.sources.game_odds_rows", return_value=odds_rows
        ), patch("syndicate.features.soccer.sources.props_odds_rows", return_value=()):
            lookup = _soccer_steam_matchup_lookup("2026-07-31")
        self.assertNotIn("game_date", lookup["abc123"])

    def test_soccer_matchup_lookup_never_raises_when_soccer_sources_unavailable(self) -> None:
        from syndicate.features.intelligence import _soccer_steam_matchup_lookup

        with patch(
            "syndicate.features.soccer.sources.active_leagues_for_date",
            side_effect=RuntimeError("boom"),
        ):
            self.assertEqual(_soccer_steam_matchup_lookup("2026-07-29"), {})


class SteamCandidateActualFieldTests(unittest.TestCase):
    # Layer 2 board follow-up: production showed `"actual": null` (raw
    # None, not the "-" placeholder) for game-level steam candidates --
    # this candidate type never set an "actual" field at all, unlike
    # every other candidate builder on the board.
    def test_game_level_steam_candidate_uses_combined_score_as_actual(self) -> None:
        sport = _sport(slug="mlb")
        sport["dashboard_games"] = [
            {
                "gamePk": 823598,
                "away": {"abbr": "SEA", "score": 3},
                "home": {"abbr": "LAD", "score": 5},
            }
        ]
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[PREGAME_TEAM_STEAM_EVENT],
        ):
            candidates = _steam_candidates_for_sport(sport)

        self.assertEqual(len(candidates), 1, candidates)
        self.assertEqual(candidates[0]["actual"], "8.0")

    def test_game_level_steam_candidate_actual_stays_dash_without_a_score(self) -> None:
        sport = _sport(slug="mlb")
        sport["dashboard_games"] = []
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[PREGAME_TEAM_STEAM_EVENT],
        ):
            candidates = _steam_candidates_for_sport(sport)

        self.assertEqual(len(candidates), 1, candidates)
        self.assertEqual(candidates[0]["actual"], "-")

    def test_player_prop_steam_candidate_actual_stays_dash(self) -> None:
        # No per-player live box-score lookup exists at this layer -- must
        # never fabricate one from the game's combined score.
        sport = _sport(slug="mlb")
        sport["dashboard_games"] = [
            {
                "gamePk": 824003,
                "away": {"abbr": "HOU", "score": 3},
                "home": {"abbr": "LAA", "score": 5},
            }
        ]
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[LIVE_PROP_STEAM_EVENT],
        ):
            candidates = _steam_candidates_for_sport(sport)

        self.assertEqual(len(candidates), 1, candidates)
        self.assertEqual(candidates[0]["actual"], "-")


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

    def test_mlb_game_level_event_abbreviates_full_team_names_and_resolves_game_id(self) -> None:
        # #160: game-level (moneyline/spread/total) steam events carry
        # OddsAPI's full club names via home_team/away_team and no game_id
        # of their own -- previously left unabbreviated ("New York Yankees
        # @ Chicago White Sox"), which could never text-match a live
        # game-chip's "NYY @ CWS" and so rendered as a second, duplicate
        # mini-card on the board's Games strip for the same live game.
        event = dict(
            PREGAME_TEAM_STEAM_EVENT,
            game_id=None,
            home_team="Chicago White Sox",
            away_team="New York Yankees",
        )
        sport = _sport(slug="mlb")
        sport["dashboard_games"] = [
            {
                "gamePk": 824568,
                "away": {"abbr": "NYY"},
                "home": {"abbr": "CWS"},
            }
        ]
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[event],
        ), patch(
            "syndicate.features.mlb.hr_targets.mlb_player_game_lookup_for_date",
            return_value={},
        ):
            candidates = _steam_candidates_for_sport(sport)

        self.assertEqual(len(candidates), 1, candidates)
        candidate = candidates[0]
        self.assertEqual(candidate["matchup"], "NYY @ CWS")
        self.assertEqual(candidate["game_id"], "824568")
        self.assertEqual(candidate["event_id"], "824568")

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


class SteamOneMarketOneCardTests(unittest.TestCase):
    """One real market move produced one card per re-detection.

    The dedupe key included `timestamp`, so every refresh cycle that re-saw
    the same move appended another identical candidate. Confirmed live
    2026-08-04: fourteen "Baltimore Orioles Total steam move" rows, all at
    line 8.5, on one board. A board is a list of things to bet, not an event
    log -- one market carries one steam state, the latest.
    """

    def _observation(self, timestamp: str, line: float, previous_line: float) -> dict:
        event = json.loads(json.dumps(PREGAME_TEAM_STEAM_EVENT))
        event["timestamp"] = timestamp
        event["line"] = line
        event["steam"]["previous_line"] = previous_line
        return event

    def test_repeated_observations_of_one_move_collapse_to_a_single_card(self) -> None:
        events = [
            self._observation("2026-07-29T22:00:00+00:00", 8.5, 7.5),
            self._observation("2026-07-29T22:05:00+00:00", 8.5, 7.5),
            self._observation("2026-07-29T22:10:00+00:00", 8.5, 7.5),
        ]
        with patch("syndicate.features.intelligence._load_steam_events_for_date", return_value=events):
            candidates = _steam_candidates_for_sport(_sport())

        self.assertEqual(len(candidates), 1, candidates)
        self.assertEqual(candidates[0]["steam_observations"], 3)
        # Newest observation wins.
        self.assertEqual(candidates[0]["steam_last_seen"], "2026-07-29T22:10:00+00:00")

    def test_a_market_that_keeps_moving_reports_the_latest_line(self) -> None:
        events = [
            self._observation("2026-07-29T22:00:00+00:00", 8.5, 7.5),
            self._observation("2026-07-29T22:30:00+00:00", 9.5, 8.5),
        ]
        with patch("syndicate.features.intelligence._load_steam_events_for_date", return_value=events):
            candidates = _steam_candidates_for_sport(_sport())

        self.assertEqual(len(candidates), 1, candidates)
        self.assertEqual(candidates[0]["line"], "9.5")
        self.assertEqual(candidates[0]["steam_observations"], 2)

    def test_out_of_order_events_do_not_overwrite_a_newer_card(self) -> None:
        events = [
            self._observation("2026-07-29T22:30:00+00:00", 9.5, 8.5),
            self._observation("2026-07-29T22:00:00+00:00", 8.5, 7.5),
        ]
        with patch("syndicate.features.intelligence._load_steam_events_for_date", return_value=events):
            candidates = _steam_candidates_for_sport(_sport())

        self.assertEqual(len(candidates), 1, candidates)
        self.assertEqual(candidates[0]["line"], "9.5")

    def test_two_genuinely_different_markets_stay_separate(self) -> None:
        other = json.loads(json.dumps(PREGAME_TEAM_STEAM_EVENT))
        other["market_type"] = "h2h"
        other["player_name"] = "Los Angeles Dodgers"
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[PREGAME_TEAM_STEAM_EVENT, other],
        ):
            candidates = _steam_candidates_for_sport(_sport())
        self.assertEqual(len(candidates), 2, candidates)

    def test_two_players_in_the_same_market_stay_separate(self) -> None:
        other = json.loads(json.dumps(LIVE_PROP_STEAM_EVENT))
        other["player_name"] = "rafael devers"
        with patch(
            "syndicate.features.intelligence._load_steam_events_for_date",
            return_value=[LIVE_PROP_STEAM_EVENT, other],
        ):
            candidates = _steam_candidates_for_sport(_sport())
        self.assertEqual(len(candidates), 2, candidates)
