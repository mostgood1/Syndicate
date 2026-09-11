"""Ask answers about the exact Layer 2 row it was asked from, in every sport.

Lane `ask-sport-parity`. Measured on the production board 2026-09-11 before
this change, clicking the rail's Ask on one prop and one game row per sport:
only MLB carried evidence, an NCAAF receiving-yards prop ("Ben Black") was
answered with an unrelated spread, and every game total asked about "Under"
with no game named. The row already carried its identity -- its event id IS
the shortlist's `event_id` -- and nothing sent it or read it.
"""
from __future__ import annotations

import unittest
from unittest import mock

from flask import Flask

from syndicate.blueprints import ask_the_syndicate_data as ask_data
from syndicate.blueprints.ask_the_syndicate import ask_the_syndicate_bp

READER = "pipeline.intelligence_state.read_layer2_shortlist"
PROP_EVENT = "db698f29983406d35dea606edfdc5922"
GAME_EVENT = "c9c138c45cb4d0e8a39f962795671ffb"
MODEL_EVENT = "e55c6fe19fce094ce214c8b0e5b504e9"


def _row(**fields):
    base = {
        "sport": "ncaaf", "event_id": PROP_EVENT, "segment": "full", "kind": "prop",
        "home_team": "Boston College Eagles", "away_team": "Rutgers Scarlet Knights",
        "quote": {"price": -112, "bookmaker": "draftkings", "books_quoting": 4, "quote_seen_age_seconds": 30.0},
        "model_edge_pct": None, "ev_pct": 3.1, "projection": None,
    }
    base.update(fields)
    return base


BEN_UNDER = _row(market="Receiving Yards", side="under", line=24.5, player_name="Ben Black")
BEN_OVER = _row(market="Receiving Yards", side="over", line=24.5, player_name="Ben Black",
                quote={"price": -108, "bookmaker": "fanduel", "books_quoting": 4})
TERRY_UNDER = _row(market="Receiving Yards", side="under", line=22.5, player_name="Shaun Terry II")
SPREAD_HOME = _row(market="spreads", side="home", line=-3.5, player_name=None, kind="game", model_edge_pct=3.7)
GAME = dict(event_id=GAME_EVENT, kind="game", player_name=None,
            home_team="Kennesaw State Owls", away_team="Georgia State Panthers")
TOTAL_UNDER = _row(market="totals", side="under", line=53.5, **GAME)
TOTAL_OVER = _row(market="totals", side="over", line=53.5, **GAME)
TOTAL_H1_UNDER = _row(market="totals", side="under", line=26.5, segment="h1", **GAME)
MODEL_H2H = _row(
    sport="nfl", event_id=MODEL_EVENT, market="h2h", side="home", line=None, player_name=None, kind="game",
    home_team="Jacksonville Jaguars", away_team="Cleveland Browns", model_edge_pct=10.0,
    projection={"side": "home", "model_prob_over": 0.6, "market_fair_prob_over": 0.5, "projected": 3.1,
                "basis": "smartsim2_home_win_rate", "source": "nfl_smartsim2"},
)
PAYLOAD = {
    "written_at": "2026-09-11T18:00:00Z",
    # Decoys first, so a resolver that took the first event+market hit would fail.
    "rows": [TERRY_UNDER, BEN_OVER, SPREAD_HOME, BEN_UNDER, TOTAL_OVER, TOTAL_H1_UNDER, TOTAL_UNDER, MODEL_H2H],
}


class ResolveBoardRowTests(unittest.TestCase):
    def _resolve(self, context, payload=PAYLOAD):
        with mock.patch(READER, return_value=payload):
            return ask_data.resolve_board_row(context)

    def test_the_exact_prop_among_same_event_decoys(self) -> None:
        row, written_at = self._resolve({
            "event_id": PROP_EVENT, "market": "Receiving Yards", "side": "under", "line": "24.5",
            "name": "Ben Black", "selection": "Ben Black",
        })
        self.assertIs(row, BEN_UNDER)
        self.assertEqual(written_at, "2026-09-11T18:00:00Z")

    def test_a_prop_without_its_side_is_two_bets_and_resolves_nothing(self) -> None:
        # Over and under on one line are different bets. Guessing between them
        # is the failure this replaces, so the caller keeps today's behaviour.
        row, _ = self._resolve({"event_id": PROP_EVENT, "market": "Receiving Yards", "name": "Ben Black"})
        self.assertIsNone(row)

    def test_a_total_resolves_the_full_game_unless_the_segment_is_named(self) -> None:
        full, _ = self._resolve({"event_id": GAME_EVENT, "market": "totals", "side": "under", "line": "53.5"})
        self.assertIs(full, TOTAL_UNDER)
        half, _ = self._resolve({
            "event_id": GAME_EVENT, "market": "totals", "side": "under", "line": "26.5", "segment": "h1",
        })
        self.assertIs(half, TOTAL_H1_UNDER)

    def test_a_team_side_resolves_from_the_selection(self) -> None:
        row, _ = self._resolve({
            "event_id": PROP_EVENT, "market": "spreads", "selection": "Boston College Eagles", "line": "-3.5",
        })
        self.assertIs(row, SPREAD_HOME)

    def test_nothing_to_resolve(self) -> None:
        self.assertEqual(self._resolve({"market": "totals"}), (None, None))
        self.assertEqual(self._resolve({"event_id": "nope", "market": "totals", "side": "under"}), (None, None))
        self.assertEqual(
            self._resolve({"event_id": GAME_EVENT, "market": "totals", "side": "under", "line": "53.5"}, payload=None),
            (None, None),
        )
        with mock.patch(READER, side_effect=RuntimeError("keyvalue down")):
            self.assertEqual(ask_data.resolve_board_row({"event_id": GAME_EVENT, "market": "totals"}), (None, None))


class EvidenceQuestionTests(unittest.TestCase):
    def test_a_total_names_its_game(self) -> None:
        question = ask_data._board_row_evidence_question("What's the case for and against Under?", TOTAL_UNDER, "ncaaf")
        self.assertIn("Georgia State Panthers @ Kennesaw State Owls", question)

    def test_a_football_prop_names_its_game_and_an_mlb_prop_is_left_alone(self) -> None:
        ncaaf = ask_data._board_row_evidence_question("What's the case for and against Ben Black?", BEN_UNDER, "ncaaf")
        self.assertIn("Rutgers Scarlet Knights @ Boston College Eagles", ncaaf)
        # MLB props have player fetchers, and adding the game would change the
        # reference answer (a game outlook table ahead of the player's own).
        mlb_row = dict(BEN_UNDER, sport="mlb", player_name="Alec Bohm",
                       home_team="Atlanta Braves", away_team="Philadelphia Phillies")
        question = "What's the case for and against Alec Bohm?"
        self.assertEqual(ask_data._board_row_evidence_question(question, mlb_row, "mlb"), question)

    def test_the_fetchers_are_handed_the_resolved_game(self) -> None:
        seen: list[str] = []

        def recorder(question, context):
            seen.append(question)
            return None

        question = "What's the case for and against Under?"
        with mock.patch.object(ask_data, "_fetchers_for_sport", return_value=[recorder]):
            ask_data.collect_focused_evidence(question, {"sport": "ncaaf"})
            ask_data.collect_focused_evidence(question, {"sport": "ncaaf"}, board_row=TOTAL_UNDER)
        self.assertEqual(seen[0], question)  # off: no row, the words alone
        self.assertIn("Georgia State Panthers @ Kennesaw State Owls", seen[1])  # on


class AskFromTheBoardRowTests(unittest.TestCase):
    # The snapshot pick the question's words match: "black" is in it.
    DECOY = {
        "query_type": "player_analysis",
        "recommendations": [{
            "selection": "Army Black Knights -3.5", "name": "Army Black Knights", "market": "spreads",
            "model_probability": 0.6, "market_probability": 0.5, "edge": 0.1,
        }],
        "readiness_gate": {"ok": True},
        "local_only": True,
    }
    BEN = {"sport": "ncaaf", "market": "Receiving Yards", "selection": "Ben Black", "name": "Ben Black"}

    def _ask(self, context, question="What's the case for and against Ben Black?"):
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)
        with mock.patch(
            "syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value=dict(self.DECOY)
        ), mock.patch(READER, return_value=PAYLOAD):
            response = app.test_client().post("/api/syndicate/query", json={"question": question, "context": context})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_the_answer_is_the_row_the_button_was_on(self) -> None:
        schema = self._ask({**self.BEN, "event_id": PROP_EVENT, "side": "under", "line": "24.5"})["schema"]
        self.assertEqual(schema["selection"], "Ben Black under 24.5")
        self.assertEqual(schema["price"], -112)
        self.assertEqual(schema["bookmaker"], "draftkings")
        self.assertIs(schema["relevance_matched"], True)

    def test_without_the_row_identity_the_word_match_still_decides(self) -> None:
        # off != on: the same question and context minus the row's identity
        # keeps today's behaviour. The test above therefore exercises the new
        # branch, not a fixture that happens to agree with it.
        schema = self._ask(dict(self.BEN))["schema"]
        self.assertEqual(schema["selection"], "Army Black Knights -3.5")

    def test_a_resolved_rows_numbers_are_its_own(self) -> None:
        schema = self._ask(
            {"sport": "nfl", "market": "h2h", "selection": "Jacksonville Jaguars",
             "name": "Jacksonville Jaguars", "event_id": MODEL_EVENT},
            question="What's the case for and against Jacksonville Jaguars?",
        )["schema"]
        self.assertEqual(schema["selection"], "Jacksonville Jaguars")
        self.assertEqual(schema["model_probability"], 60.0)
        self.assertEqual(schema["market_probability"], 50.0)
        self.assertEqual(schema["edge_pct"], 10.0)

    def test_the_evidence_is_handed_the_same_row(self) -> None:
        seen: dict = {}

        def spy(question, context, *, board_row=None):
            seen["board_row"] = board_row
            return None

        with mock.patch("syndicate.blueprints.ask_the_syndicate.collect_focused_evidence", side_effect=spy):
            self._ask({**self.BEN, "event_id": PROP_EVENT, "side": "under", "line": "24.5"})
        self.assertIs(seen["board_row"], BEN_UNDER)


class FetcherWiringTests(unittest.TestCase):
    """Reachability before correctness: each new fetcher is dispatched, and it
    receives the row and both team names it reads."""

    def test_each_sport_dispatches_its_board_row_fetcher(self) -> None:
        self.assertIn(ask_data._soccer_match_evidence, ask_data._entity_fetchers_for_sport("soccer", "q"))
        self.assertIs(ask_data._entity_fetchers_for_sport("ncaaf", "q")[0], ask_data._ncaaf_player_log_evidence)
        self.assertIs(ask_data._entity_fetchers_for_sport("nfl", "q")[0], ask_data._nfl_player_projection_evidence)

    def test_the_fetchers_are_handed_the_row_and_its_teams(self) -> None:
        seen: list[dict] = []

        def recorder(question, context):
            seen.append(context)
            return None

        with mock.patch.object(ask_data, "_fetchers_for_sport", return_value=[recorder]):
            ask_data.collect_focused_evidence("q", {"sport": "ncaaf"}, board_row=TOTAL_UNDER)
        self.assertIs(seen[0]["board_row"], TOTAL_UNDER)
        self.assertEqual(
            (seen[0]["board_away_team"], seen[0]["board_home_team"]),
            ("Georgia State Panthers", "Kennesaw State Owls"),
        )


class MlbExactGameTests(unittest.TestCase):
    """A board row names its game exactly. `_mlb_game_score` alone scores ANY
    shared team word ("New York") at 100 and keeps slate order on a tie."""

    QUESTION = "What's the case for and against Under 8.5 in New York Mets @ Atlanta Braves?"

    def setUp(self) -> None:
        import json
        import os
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        daily = os.path.join(self._tmp.name, "mlb", "daily")
        os.makedirs(daily)
        full = {"home_win_prob": 0.5, "away_win_prob": 0.5, "away_runs_mean": 4.0, "home_runs_mean": 4.0,
                "total_runs_dist": {"8": 10}, "run_margin_dist": {"1": 5}}
        summary = {"date": "2026-09-11", "outputs": [
            {"game_pk": 1, "away": "NYY", "home": "BOS", "starter_names": {}, "full": full, "pitcher_props": {}},
            {"game_pk": 2, "away": "NYM", "home": "ATL", "starter_names": {}, "full": full, "pitcher_props": {}},
        ]}
        targets = {"games": [
            {"game_pk": 1, "away": "New York Yankees", "home": "Boston Red Sox", "away_abbr": "NYY",
             "home_abbr": "BOS", "targets": []},
            {"game_pk": 2, "away": "New York Mets", "home": "Atlanta Braves", "away_abbr": "NYM",
             "home_abbr": "ATL", "targets": []},
        ]}
        with open(os.path.join(daily, "daily_summary_2026_09_11.json"), "w", encoding="utf-8") as handle:
            json.dump(summary, handle)
        with open(os.path.join(daily, "daily_summary_2026_09_11_hr_targets.json"), "w", encoding="utf-8") as handle:
            json.dump(targets, handle)
        self.env = {"MLB_BETTING_DATA_ROOT": os.path.join(self._tmp.name, "mlb")}

    def test_the_board_rows_teams_pick_the_game(self) -> None:
        with mock.patch.dict("os.environ", self.env):
            found = ask_data._mlb_match_game(self.QUESTION, {
                "selected_date": "2026-09-11",
                "board_away_team": "New York Mets", "board_home_team": "Atlanta Braves",
            })
        self.assertEqual(found[0]["game_pk"], 2)

    def test_without_them_new_york_collides_and_slate_order_decides(self) -> None:
        # off != on: the collision the exact match exists for.
        with mock.patch.dict("os.environ", self.env):
            found = ask_data._mlb_match_game(self.QUESTION, {"selected_date": "2026-09-11"})
        self.assertEqual(found[0]["game_pk"], 1)


class SoccerMatchEvidenceTests(unittest.TestCase):
    ROW = {"sport": "soccer", "event_id": "2a284d621fe10e2a722fd9b6d17814a2", "market": "totals", "side": "under",
           "line": 2.5, "home_team": "Lorient", "away_team": "Toulouse",
           "game": {"start_time_utc": "2026-09-12T18:45:00+00:00"}}
    MATCH = {
        "matchup": {"home_team": "Lorient", "away_team": "Toulouse"},
        "kickoff": "2026-09-12T18:45:00Z", "league": "ligue_1",
        "win_probability": {"home": 0.41, "draw": 0.27, "away": 0.32},
        "team_projection": {"home_mean": 1.42, "away_mean": 1.18, "total_mean": 2.6},
        "total_distribution": {"mean": 2.6, "over_2_5_probability": 0.52, "both_teams_scored_probability": 0.55},
        "volume_projection": {"home_shots": 12.4, "away_shots": 10.9},
        "scoreline_probabilities": {"0-0": 0.08, "1-0": 0.11, "1-1": 0.13, "2-1": 0.09, "0-2": 0.05},
        "adapter_metadata": {"home_rating_detail": {"attack_rating": 1.05, "xg_for_per_match": 1.4},
                             "away_rating_detail": {"attack_rating": 0.97, "xg_for_per_match": 1.2}},
    }
    LOADER = "syndicate.features.shared.soccer_projections.load_soccer_projections"

    def _index(self):
        from syndicate.features.shared import soccer_projections as sp

        index = sp.SoccerProjectionIndex()
        index.by_teams[(sp._norm_team("Lorient"), sp._norm_team("Toulouse"))] = dict(self.MATCH)
        index.generated_at_by_league["ligue_1"] = "2026-09-11T13:28:12-05:00"
        return index

    def test_a_soccer_row_gets_the_sims_view_of_its_fixture(self) -> None:
        with mock.patch(self.LOADER, return_value=self._index()):
            result = ask_data._soccer_match_evidence("q", {"board_row": self.ROW, "selected_date": "2026-09-11"})
        titles = [table["title"] for table in result["tables"]]
        self.assertTrue(titles[0].startswith("Match sim outlook — Toulouse @ Lorient"), titles)
        outlook = {row[0]: row[1:] for row in result["tables"][0]["rows"]}
        self.assertEqual(outlook["Win probability"], ["32.0%", "41.0%"])  # away, home
        self.assertNotIn("Corners", outlook)  # not published -> absent, not a row of dashes
        goals = {row[0]: row[1] for row in result["tables"][1]["rows"]}
        self.assertEqual(goals["Over 2.5 goals"], "52.0%")
        self.assertIn("Team ratings the sim used — Toulouse @ Lorient", titles)
        self.assertEqual(result["charts"][0]["title"], "Simulated total goals — Toulouse @ Lorient")

    def test_only_a_soccer_row_with_a_matching_fixture_answers(self) -> None:
        with mock.patch(self.LOADER, return_value=self._index()):
            self.assertIsNone(ask_data._soccer_match_evidence("q", {}))
            self.assertIsNone(ask_data._soccer_match_evidence("q", {"board_row": dict(self.ROW, sport="mlb")}))
            other = dict(self.ROW, event_id="x", home_team="Nantes", away_team="Brest")
            self.assertIsNone(ask_data._soccer_match_evidence("q", {"board_row": other}))


class NcaafPlayerLogTests(unittest.TestCase):
    ROW = dict(BEN_UNDER, game={"start_time_utc": "2026-09-11T23:30:00+00:00"})
    LOG = [
        {"game_id": "g1", "week": 1, "receptions": 3.0, "receiving_yards": 31.0, "anytime_td": 0.0},
        {"game_id": "g2", "week": 2, "receptions": 5.0, "receiving_yards": 57.0, "anytime_td": 1.0},
    ]

    def test_a_college_prop_gets_the_players_real_game_log(self) -> None:
        with mock.patch(
            "syndicate.features.ncaaf.player_stats.resolve_player_id",
            side_effect=lambda season, name: "p1" if season == 2026 and name == "Ben Black" else None,
        ), mock.patch("syndicate.features.ncaaf.player_stats.player_game_log", return_value=list(self.LOG)):
            result = ask_data._ncaaf_player_log_evidence("q", {"board_row": self.ROW})
        table = result["tables"][0]
        self.assertEqual(table["title"], "Last 2 games — Ben Black (CFBD box scores)")
        self.assertEqual(table["columns"], ["Season", "Week", "Rec", "Rec yds", "TD"])
        self.assertEqual(table["rows"][0], ["2026", "2", "5", "57", "1"])  # newest first
        self.assertEqual(table["rows"][-1], ["Avg", "", "4.0", "44.0", "0.5"])
        chart = result["charts"][0]
        self.assertEqual(chart["title"], "Receiving Yards by game — Ben Black (line 24.5)")
        self.assertEqual([point["y"] for point in chart["points"]], [31.0, 57.0])  # chronological

    def test_a_game_row_or_an_unknown_player_gets_no_log(self) -> None:
        with mock.patch("syndicate.features.ncaaf.player_stats.resolve_player_id", return_value=None):
            self.assertIsNone(ask_data._ncaaf_player_log_evidence("q", {"board_row": self.ROW}))
        self.assertIsNone(ask_data._ncaaf_player_log_evidence("q", {"board_row": TOTAL_UNDER}))


class NflPlayerProjectionTests(unittest.TestCase):
    ROW = dict(MODEL_H2H, market="Receptions", side="over", line=4.5, player_name="Michael Pittman Jr.", kind="prop")

    def test_an_nfl_prop_gets_every_line_the_model_prices_for_the_player(self) -> None:
        from syndicate.features.shared.nfl_prop_projections import NflPropProjectionIndex

        index = NflPropProjectionIndex(season=2026, week=1, entries={
            "receptions::michael pittman jr.::5.5": {"projected_value": 4.9, "sim_projection": 0.41},
            "receptions::michael pittman jr.::4.5": {"projected_value": 4.9, "sim_projection": 0.55},
            "receiving_yards::michael pittman jr.::52.5": {"projected_value": 55.1, "sim_projection": 0.53},
            "receptions::someone else::3.5": {"projected_value": 3.0, "sim_projection": 0.4},
        })
        with mock.patch(
            "syndicate.features.shared.nfl_prop_projections.load_nfl_prop_projections", return_value=index
        ):
            result = ask_data._nfl_player_projection_evidence("q", {"board_row": self.ROW})
        table = result["tables"][0]
        self.assertEqual(table["title"], "Prop model projections — Michael Pittman Jr. (NFL 2026 week 1)")
        self.assertEqual(table["rows"], [
            ["Receiving yards", "52.5", "55.1", "53.0%"],
            ["Receptions", "4.5", "4.9", "55.0%"],
            ["Receptions", "5.5", "4.9", "41.0%"],
        ])

    def test_a_player_the_model_does_not_price_gets_nothing(self) -> None:
        from syndicate.features.shared.nfl_prop_projections import NflPropProjectionIndex

        with mock.patch(
            "syndicate.features.shared.nfl_prop_projections.load_nfl_prop_projections",
            return_value=NflPropProjectionIndex(season=2026, week=1, entries={}),
        ):
            self.assertIsNone(ask_data._nfl_player_projection_evidence("q", {"board_row": self.ROW}))


if __name__ == "__main__":
    unittest.main()
