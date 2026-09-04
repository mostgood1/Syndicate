"""`#387` -- the two reductions on the MLB overview hydration path, and the
invariants that make each of them safe.

Both changes are supposed to be INVISIBLE in output and only visible in memory,
which is a shape that tests easily wave through: "nothing changed" passes just
as well when the code is inert. So each one is covered twice -- once for the
behaviour that must not change, and once for the mechanism actually firing
(`model_engine_standard.md`'s reachability rule: prove `off != on` before
proving `on` is correct).
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.mlb import cards


def _feed_live_doc() -> dict:
    """A feed/live document shaped like StatsAPI's, with every section this
    module is known to read plus the two it is not."""
    return {
        "gamePk": 823368,
        "gameData": {
            "status": {"abstractGameState": "Live", "detailedState": "In Progress"},
            "probablePitchers": {"away": {"id": 1, "fullName": "A Pitcher"}},
            "teams": {"away": {"abbreviation": "MIL"}, "home": {"abbreviation": "LAD"}},
            "datetime": {"dateTime": "2026-06-14T22:41:00Z"},
            "players": {"ID1": {"id": 1}},
        },
        "liveData": {
            "linescore": {"currentInning": 5, "teams": {"away": {"runs": 2}, "home": {"runs": 3}}},
            "boxscore": {"teams": {"away": {"players": {"ID1": {"person": {"id": 1}}}}}},
            "decisions": {},
            "plays": {
                "currentPlay": {"matchup": {"batter": {"id": 7}}},
                "allPlays": [{"about": {"atBatIndex": index}} for index in range(500)],
                "playsByInning": [{"startIndex": 0}],
            },
        },
    }


class FeedLivePruneTests(unittest.TestCase):
    """`_prune_feed_live_payload` -- 66% of a feed/live document is `allPlays`,
    and nothing in `syndicate/` reads it."""

    def test_drops_only_the_two_unread_play_sections(self) -> None:
        pruned = cards._prune_feed_live_payload(_feed_live_doc())
        plays = pruned["liveData"]["plays"]
        self.assertNotIn("allPlays", plays)
        self.assertNotIn("playsByInning", plays)
        # Everything a consumer reads survives, by value not just by presence.
        self.assertEqual(plays["currentPlay"], {"matchup": {"batter": {"id": 7}}})
        self.assertEqual(pruned["liveData"]["linescore"]["currentInning"], 5)
        self.assertEqual(pruned["gameData"]["status"]["detailedState"], "In Progress")
        self.assertEqual(pruned["gameData"]["probablePitchers"]["away"]["fullName"], "A Pitcher")
        self.assertEqual(pruned["liveData"]["boxscore"]["teams"]["away"]["players"]["ID1"]["person"]["id"], 1)
        self.assertEqual(pruned["gameData"]["players"], {"ID1": {"id": 1}})

    def test_does_not_mutate_the_document_it_was_given(self) -> None:
        # `load_json_or_gz_file` parses fresh today, so no caller shares a
        # document -- but a prune that mutates in place would become a
        # corruption bug the moment one does, and that is not a failure mode
        # anyone would look for in a memory fix.
        original = _feed_live_doc()
        cards._prune_feed_live_payload(original)
        self.assertEqual(len(original["liveData"]["plays"]["allPlays"]), 500)

    def test_returns_the_same_object_when_there_is_nothing_to_drop(self) -> None:
        payload = {"liveData": {"plays": {"currentPlay": {}}}}
        self.assertIs(cards._prune_feed_live_payload(payload), payload)

    def test_tolerates_documents_that_are_not_shaped_like_a_feed(self) -> None:
        for payload in ({}, {"liveData": None}, {"liveData": {"plays": None}}):
            self.assertIs(cards._prune_feed_live_payload(payload), payload)

    def test_consumers_read_identical_values_before_and_after(self) -> None:
        """Parity at the level that matters: the functions that read this
        document, not the document itself."""
        full = _feed_live_doc()
        pruned = cards._prune_feed_live_payload(_feed_live_doc())
        for reader in (
            cards._actual_payload_is_live,
            cards._source_status,
            cards._live_progress_fraction,
            cards._current_pitching_side,
        ):
            self.assertEqual(reader(full), reader(pruned), reader.__name__)
        self.assertEqual(
            cards._iter_team_players(full, "away"),
            cards._iter_team_players(pruned, "away"),
        )

    def test_flag_off_keeps_the_full_payload_and_flag_on_prunes_it(self) -> None:
        """REACHABILITY, not correctness: `off != on` proves the loader is
        actually routed through the prune. Four inert features shipped in one
        session on this codebase were caught by exactly this and nothing else."""
        pks = [823368]

        def _must_not_fetch(_game_pk):
            # HERMETIC BY ASSERTION, not by luck. This test pins a PAST date so
            # the loader takes the cached document -- but "past" is a moving
            # target: `mlb_feed_live_is_refreshable` now also refreshes
            # YESTERDAY off the request path, and the old `2026-06-15` "today"
            # made 06-14 exactly that. The test then made a REAL call to
            # statsapi and quietly graded a live 79-play document against its
            # 500-play fixture. Two days back keeps it outside any window, and
            # this stub turns a future widening into a failure that names
            # itself instead of a network call nobody notices.
            raise AssertionError(
                "the prune test must not re-fetch -- its date is meant to be outside the refresh window"
            )

        with patch.object(cards, "raw_feed_live_path", return_value=Path("unused")), patch.object(
            cards, "load_json_or_gz_file", side_effect=lambda _path: _feed_live_doc()
        ), patch.object(cards, "_fetch_current_feed_live", side_effect=_must_not_fetch), patch.object(
            cards, "central_today_iso", return_value="2026-06-16"
        ):
            with patch.dict("os.environ", {"SYNDICATE_MLB_FEED_LIVE_PRUNE": "0"}):
                off = cards._daily_actual_by_game("2026-06-14", pks)
            with patch.dict("os.environ", {"SYNDICATE_MLB_FEED_LIVE_PRUNE": "1"}):
                on = cards._daily_actual_by_game("2026-06-14", pks)

        self.assertEqual(len(off[823368]["liveData"]["plays"]["allPlays"]), 500)
        self.assertNotIn("allPlays", on[823368]["liveData"]["plays"])
        self.assertNotEqual(off, on)

    def test_default_is_on(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("SYNDICATE_MLB_FEED_LIVE_PRUNE", None)
            self.assertTrue(cards._feed_live_prune_enabled())


class SharedGameLinesShardRemovalTests(unittest.TestCase):
    """`_enrich_games_with_tracked_market_lines` used to load the whole
    odds_history shard (~19.8MB file, ~125MB resident) to consult a `games` key
    the shard does not have. The load is gone; these hold the reasons in place."""

    def test_odds_history_shard_schema_has_no_games_key(self) -> None:
        """THE INVARIANT THE REMOVAL RESTS ON.

        If the shard writer ever grows a `games` key, the removed branch would
        stop being dead and this assertion is what says so -- otherwise the
        removal degrades from "provably inert" to "was inert once, in 2026".
        """
        source = Path(cards.__file__).resolve().parents[2] / "features" / "shared" / "odds_refresh_tracking.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        shard_literals = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if {"schema_version", "shard_key", "markets"} <= keys:
                shard_literals.append(keys)
        self.assertTrue(
            shard_literals,
            "could not find the odds_history shard payload literal in "
            "odds_refresh_tracking.py -- if the writer was restructured, re-derive "
            "whether cards.py's removed `games` branch is still dead before "
            "deleting this test",
        )
        for keys in shard_literals:
            self.assertNotIn("games", keys)

    def test_enrichment_never_loads_the_odds_history_shard(self) -> None:
        """The regression guard for the removal itself. A reinstated load would
        pass every behavioural test in the suite -- it changed no output, which
        is exactly why it survived for months."""
        with patch.object(cards, "load_oddsapi_game_lines_doc", return_value=None), patch(
            "syndicate.features.mlb.cards.load_odds_history_payload_for_sport"
        ) as loader, patch.object(cards, "central_today_iso", return_value="2026-07-23"), patch.object(
            cards, "_render_web_dyno", return_value=False
        ):
            cards._enrich_games_with_tracked_market_lines(
                [{"gamePk": 1, "away": {"abbr": "DET"}, "home": {"abbr": "ATH"}, "markets": {}}],
                "2026-07-23",
            )
        loader.assert_not_called()

    def test_output_is_unchanged_on_the_worker_today_path(self) -> None:
        """The removed branch could only ever have replaced `game_lines_doc`.
        With a realistic (games-less) shard available, the result must equal the
        result with no shard at all -- which is what "inert" means here."""
        game_lines_doc = {
            "date": "2026-07-23",
            "retrieved_at": "2026-07-23T20:00:00Z",
            "games": [
                {
                    "away_team": "Detroit Tigers",
                    "home_team": "Athletics",
                    "commence_time": "2026-07-23T22:41:00Z",
                    "markets": {
                        "h2h": {"home_odds": 119, "away_odds": -143},
                        "totals": {"line": 8.5, "over_odds": -110, "under_odds": -110},
                    },
                }
            ],
        }
        realistic_shard = {
            "schema_version": 1,
            "sport": "mlb",
            "shard_key": "2026-07-23",
            "date": "2026-07-23",
            "updated_at": "2026-07-23T20:00:00Z",
            "history_limit": 20,
            "markets": {"event=1|market=h2h": {"history": []}},
        }
        game = {"gamePk": 1, "away": {"abbr": "DET", "name": "Detroit Tigers"}, "home": {"abbr": "ATH", "name": "Athletics"}, "markets": {}}

        with patch.object(cards, "load_oddsapi_game_lines_doc", return_value=game_lines_doc), patch.object(
            cards, "central_today_iso", return_value="2026-07-23"
        ), patch.object(cards, "_render_web_dyno", return_value=False), patch(
            "syndicate.features.mlb.cards.load_odds_history_payload_for_sport",
            return_value=realistic_shard,
        ):
            with_shard = cards._enrich_games_with_tracked_market_lines([dict(game)], "2026-07-23")

        with patch.object(cards, "load_oddsapi_game_lines_doc", return_value=game_lines_doc), patch.object(
            cards, "central_today_iso", return_value="2026-07-23"
        ), patch.object(cards, "_render_web_dyno", return_value=False), patch(
            "syndicate.features.mlb.cards.load_odds_history_payload_for_sport",
            return_value=None,
        ):
            without_shard = cards._enrich_games_with_tracked_market_lines([dict(game)], "2026-07-23")

        self.assertEqual(with_shard, without_shard)
        self.assertEqual(with_shard[0]["markets"]["ml"]["home_odds"], 119)


if __name__ == "__main__":
    unittest.main()
