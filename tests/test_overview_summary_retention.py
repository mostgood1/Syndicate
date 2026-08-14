"""The candidate pool must not retain every sport's hydrated overview.

`_build_candidate_pool` embedded the FULL hydrated overview in the pool it
returns -- `dashboard_games`, `home_rails`, `prop_opportunities` for all eight
sports -- which was then cached up to `_max_snapshots` (12) deep and JSON
round-tripped on every build AND every cache hit. Its only consumer,
`_live_pipeline_summary`, reads it for five derived values per sport.

The load-bearing test here is EQUIVALENCE: the compact summary must produce a
`by_sport` block identical to what the hydrated rows produced, or this is a
behaviour change wearing a memory fix's clothes.

It is also the prerequisite for the handoff's SUM -> MAX overview fix, which
cannot release a sport before the next hydrates while anything holds the whole
list alive.
"""

from __future__ import annotations

import json
import unittest

from pipeline.intelligence_state import IntelligenceStateService


def _overview() -> list[dict]:
    return [
        {
            "slug": "mlb",
            "dashboard_games": [
                {"is_live": True, "game_id": "g1", "timestamp": "2026-08-14T18:00:00Z"},
                {"is_live": False, "game_id": "g2"},
                {"is_live": True, "game_id": "g3"},
            ],
            "home_rails": {
                "live": {
                    "items": [
                        {"game_id": "g1", "timestamp": "2026-08-14T19:00:00Z"},
                        {"game_id": "g1"},           # duplicate id -> one distinct
                        {"event_id": "g9"},
                        {"id": ""},                  # a mapping, so an ITEM, but no distinct id
                        "not-a-mapping",
                    ]
                }
            },
            # The bulk that must NOT survive into the pool:
            "prop_opportunities": {"pregame": [{"x": "y"} for _ in range(50)]},
        },
        {"slug": "wnba", "dashboard_games": [], "home_rails": {}},
        {"slug": "nba"},                              # sparse row
        "not-a-mapping",                              # must be skipped
    ]


def _by_sport_from(pool: dict) -> dict:
    """Run the real consumer and return just its per-sport block."""
    service = IntelligenceStateService()
    result = service._live_pipeline_summary(
        candidate_pool=pool,
        candidates=[{"sport": "mlb", "is_live": True}, {"sport": "mlb", "is_live": False}],
        top_candidates=[{"sport": "mlb"}],
        top_opportunities=[{"sport": "mlb", "is_live": True}],
        board_contract={"cards": [{"sport": "mlb", "is_live": True}]},
        selected_date="2026-08-14",
        sport="all",
    )
    return result["by_sport"]


class OverviewSummaryRetentionTests(unittest.TestCase):
    def test_summary_and_hydrated_overview_agree_exactly(self) -> None:
        """The whole point. If these differ, it is a behaviour change."""
        overview = _overview()
        legacy_pool = {"overview": overview}
        new_pool = {"overview_summary": IntelligenceStateService._overview_live_summary(overview)}
        self.assertEqual(
            json.dumps(_by_sport_from(new_pool), sort_keys=True),
            json.dumps(_by_sport_from(legacy_pool), sort_keys=True),
        )

    def test_the_counts_are_actually_right_not_just_equal(self) -> None:
        """Equality to a broken baseline would also pass the test above."""
        rows = IntelligenceStateService._overview_live_summary(_overview())
        mlb = next(row for row in rows if row["slug"] == "mlb")
        self.assertEqual(mlb["live_games"], 2)
        self.assertEqual(mlb["live_prop_items"], 4, "4 mappings; the bare string is not one")
        self.assertEqual(mlb["live_odds_game_ids"], 2, "g1 twice + g9; the blank id is excluded")

    def test_the_hydrated_payload_does_not_survive(self) -> None:
        """A summary that still carried the rows would pass every test above."""
        blob = json.dumps(IntelligenceStateService._overview_live_summary(_overview()))
        self.assertNotIn("prop_opportunities", blob)
        self.assertNotIn("dashboard_games", blob)
        self.assertNotIn("home_rails", blob)

    # -- the fallback, which is what makes this safe to deploy -------------

    def test_a_pool_persisted_before_this_change_still_reads(self) -> None:
        """`run_intelligence_query` embeds the pool in a PERSISTED response, so
        old snapshots carry the hydrated shape. Reading one must not yield
        zeros -- absent-and-unknown is not measured-zero."""
        by_sport = _by_sport_from({"overview": _overview()})
        self.assertEqual(by_sport["mlb"]["live_games"], 2)
        self.assertEqual(by_sport["mlb"]["live_prop_items"], 4)

    def test_a_pool_with_neither_key_degrades_to_zero_not_a_crash(self) -> None:
        by_sport = _by_sport_from({})
        self.assertEqual(by_sport["mlb"]["live_games"], 0)
        self.assertFalse(by_sport["mlb"]["live_mirror_exists"])

    def test_non_mapping_rows_are_skipped(self) -> None:
        rows = IntelligenceStateService._overview_live_summary(_overview())
        self.assertEqual({row["slug"] for row in rows}, {"mlb", "wnba", "nba"})

    def test_none_overview_is_safe(self) -> None:
        self.assertEqual(IntelligenceStateService._overview_live_summary(None), [])


if __name__ == "__main__":
    unittest.main()
