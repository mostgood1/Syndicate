"""#222 step 2 -- counting the identity gap before closing it.

Exists because three changes on 2026-08-06 passed their tests and did nothing in
production, and then a three-line change moved top_props from 0 of 14 priced to
12 of 14. That effect had been invisible for as long as it existed, because
nothing counted it.
"""

from __future__ import annotations

import unittest

from syndicate.features.shared import opportunity_contract_metrics as metrics


class ContractMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        metrics.reset()
        self.addCleanup(metrics.reset)

    def _counts(self, sport: str, lane: str, date_str: str) -> dict:
        return metrics.snapshot()["by_sport"][sport][date_str][lane]

    def test_display_market_strings_do_not_count_as_a_market_key(self) -> None:
        """The whole point. A row with market "Hits" and no canonical key cannot
        join "batter_hits", so counting `market` would report the gap as closed
        while the join still fails -- which is the failure being measured."""
        metrics.record_rows(
            [{"market": "Hits", "player_name": "A Batter", "event_id": "e1"}],
            sport="mlb", lane="prop_source_in", date_str="2026-08-06",
        )
        counts = self._counts("mlb", "prop_source_in", "2026-08-06")
        self.assertEqual(counts["missing_market_key"], 1)
        self.assertEqual(counts["complete"], 0)

    def test_a_canonical_key_counts(self) -> None:
        metrics.record_rows(
            [{"prop": "batter_hits", "market": "Hits", "player_name": "A Batter", "event_id": "e1"}],
            sport="mlb", lane="prop_source_in", date_str="2026-08-06",
        )
        counts = self._counts("mlb", "prop_source_in", "2026-08-06")
        self.assertEqual(counts["missing_market_key"], 0)
        self.assertEqual(counts["complete"], 1)

    def test_a_missing_player_is_counted_for_props(self) -> None:
        """The exact production row: the player is in the label, not the field."""
        metrics.record_rows(
            [{"market_key": "batter_hits", "name": "Chelsea Gray OVER 1.5", "event_id": "e1"}],
            sport="mlb", lane="prop_source_in", date_str="2026-08-06",
        )
        counts = self._counts("mlb", "prop_source_in", "2026-08-06")
        self.assertEqual(counts["missing_entity_name"], 1)
        self.assertEqual(counts["complete"], 0, "a prop with no player is not emittable")

    def test_a_game_market_is_complete_without_a_player(self) -> None:
        """Requiring an entity everywhere would count every moneyline as broken
        and make the number meaningless."""
        metrics.record_rows(
            [{"market_key": "h2h", "selection": "home", "event_id": "e1"}],
            sport="mlb", lane="game_candidate", date_str="2026-08-06",
        )
        counts = self._counts("mlb", "game_candidate", "2026-08-06")
        self.assertEqual(counts["missing_entity_name"], 1, "still reported...")
        self.assertEqual(counts["complete"], 1, "...but not held against a game market")

    def test_a_team_pair_counts_as_event_identity(self) -> None:
        metrics.record_rows(
            [{"market_key": "h2h", "home_team": "Chicago Cubs", "away_team": "Toronto Blue Jays"}],
            sport="mlb", lane="game_candidate", date_str="2026-08-06",
        )
        counts = self._counts("mlb", "game_candidate", "2026-08-06")
        self.assertEqual(counts["missing_event_identity"], 0)

    def test_lanes_and_sports_are_counted_separately(self) -> None:
        """A single blended number would hide that one lane is fine and another
        is empty -- which is exactly what 'top_game_bets 5/12, top_props 0/14'
        revealed."""
        metrics.record_rows([{"market_key": "h2h", "event_id": "e1"}], sport="mlb", lane="game_candidate", date_str="2026-08-06")
        metrics.record_rows([{"market": "Pts"}], sport="wnba", lane="prop_source_in", date_str="2026-08-06")
        snap = metrics.snapshot()
        self.assertIn("mlb", snap["by_sport"])
        self.assertIn("wnba", snap["by_sport"])
        self.assertEqual(snap["by_sport"]["wnba"]["2026-08-06"]["prop_source_in"]["missing_market_key"], 1)

    def test_quote_coverage_is_tracked_alongside(self) -> None:
        metrics.record_rows(
            [{"market_key": "h2h", "event_id": "e1", "quote": {"price": -110}},
             {"market_key": "h2h", "event_id": "e2"}],
            sport="mlb", lane="game_candidate", date_str="2026-08-06",
        )
        self.assertEqual(self._counts("mlb", "game_candidate", "2026-08-06")["with_quote"], 1)

    def test_snapshot_records_which_service_produced_it(self) -> None:
        """The lanes run on web AND refresh-worker, and those are separate
        disks. A count without this cannot be interpreted."""
        self.assertIn("service_role", metrics.snapshot())

    def test_instrumentation_never_raises(self) -> None:
        """Instrumentation that can break what it measures is worse than none."""
        metrics.record_rows(None, sport=None, lane="x", date_str=None)
        metrics.record_rows(["not-a-dict", 7, None], sport="mlb", lane="x", date_str="2026-08-06")
        self.assertIsInstance(metrics.snapshot(), dict)


class UniversalCandidateContractTests(unittest.TestCase):
    """#223 step 1 -- the contract itself."""

    def _c(self, **payload):
        from syndicate.features.shared.intelligence_contracts import UniversalCandidate

        return UniversalCandidate.from_raw({"sport": "mlb", **payload})

    def test_canonical_key_and_display_label_are_separate(self) -> None:
        """from_raw used to fold both into `market`, display-first, so a row
        showing "Hits" could never be joined to the odds log's "batter_hits"."""
        c = self._c(prop="batter_hits", market="Hits", player_name="A Batter",
                    event_id="e1", pick="over", line=0.5)
        self.assertEqual(c.market_key, "batter_hits")
        self.assertEqual(c.market_label, "Hits")
        self.assertEqual(c.market, "Hits", "the legacy display field must not change meaning")

    def test_a_display_string_alone_never_satisfies_market_key(self) -> None:
        c = self._c(market="Hits", player_name="A Batter", event_id="e1", pick="over")
        self.assertIsNone(c.market_key)
        self.assertIn("missing_market_key", c.validate())

    def test_a_complete_prop_validates(self) -> None:
        c = self._c(prop="batter_hits", player_name="A Batter", event_id="e1", pick="over", line=0.5)
        self.assertEqual(c.validate(), [])

    def test_the_real_broken_production_row_is_rejected(self) -> None:
        """Served live 2026-08-06: the player is in the label, not the field."""
        c = self._c(market="Threes", name="Chelsea Gray OVER 1.5", pick="over")
        self.assertTrue(c.validate())

    def test_a_game_market_needs_no_entity(self) -> None:
        """Requiring one everywhere would reject every moneyline."""
        c = self._c(market_key="h2h", home_team="Chicago Cubs",
                    away_team="Toronto Blue Jays", selection="home")
        self.assertFalse(c.is_prop())
        self.assertEqual(c.validate(), [])

    def test_a_team_pair_satisfies_event_identity(self) -> None:
        """MLB board rows carry a StatsAPI gamePk while quotes carry an OddsAPI
        hash, so event_id alone cannot be the only accepted signal."""
        c = self._c(market_key="h2h", home_team="Chicago Cubs",
                    away_team="Toronto Blue Jays", selection="home")
        self.assertNotIn("missing_event_identity", c.validate())

    def test_identity_and_quote_survive_a_round_trip(self) -> None:
        c = self._c(prop="batter_hits", player_name="A Batter", event_id="e1",
                    pick="over", line=0.5, quote={"bookmaker": "draftkings", "price": -108})
        from syndicate.features.shared.intelligence_contracts import UniversalCandidate

        again = UniversalCandidate.from_raw(c.to_dict())
        self.assertEqual(again.market_key, "batter_hits")
        self.assertEqual(again.entity_name, "A Batter")
        self.assertEqual(again.quote["bookmaker"], "draftkings")
        self.assertEqual(again.validate(), [])

    def test_validate_reports_rather_than_raises(self) -> None:
        """Producers reject on these; a migration counts them. Both need the
        reasons, and neither wants an exception mid-board-build."""
        self.assertIsInstance(self._c().validate(), list)


if __name__ == "__main__":
    unittest.main()
