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


if __name__ == "__main__":
    unittest.main()
