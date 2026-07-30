from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared import recommendation_engine
from syndicate.features.shared.intelligence_evaluation import build_artifact_metadata
from syndicate.features.shared.recommendation_engine import calculate_edge
from syndicate.features.shared.recommendation_engine import build_policy_optimization_summary
from syndicate.features.shared.recommendation_engine import filter_candidates
from syndicate.features.shared.recommendation_engine import compare_policies
from syndicate.features.shared.recommendation_engine import rank_recommendations
from syndicate.features.shared.recommendation_engine import select_policy


# filter_candidates does `evaluation_records or _load_records_from_ledger(...)`
# -- an empty list is falsy, so passing [] still falls through to a REAL
# on-disk ledger read (intelligence_evaluation.py's _load_chunked_ledger_records),
# which can stall for a long time (confirmed: a OneDrive-synced repo checkout
# hung on this exact read). Every test in this file must pass a genuinely
# non-empty evaluation_records list to avoid it -- this one is for a market
# no test candidate uses, so it never affects scoring.
_UNRELATED_HISTORY = [
    {
        "result": "win",
        "pnl": 0.0,
        "stake": 1.0,
        "implied_probability": 0.5,
        "recommendation": {"market": "unrelated_placeholder_market", "selection": "n/a", "line": None, "odds": "+100"},
        "artifact_metadata": {"sport": "mlb"},
    }
]


class RecommendationEngineTests(unittest.TestCase):
    def test_filter_candidates_reliability_profile_calls_scale_with_markets_not_candidates(self) -> None:
        # Reproduces a production incident: filter_candidates recomputed
        # build_reliability_profile from scratch for every candidate instead
        # of once per distinct market, causing a 48.5s ranking pass over only
        # 161 candidates. With a fixed set of distinct markets, the call
        # count should stay constant as candidate volume grows -- before the
        # fix it scaled linearly (1 sport-level call + 2 per-candidate calls).
        def build_candidates(count: int) -> list[dict]:
            return [
                {
                    "name": f"Player {i} Over 5.5 Strikeouts",
                    "event_id": f"game-{i}",
                    "market": "strikeouts" if i % 2 == 0 else "moneyline",
                    "selection": f"Player {i}",
                    "odds": "+100",
                    "score": 80.0,
                    "confidence": "60%",
                    "model_probability": 0.55,
                }
                for i in range(count)
            ]

        historical_records = [
            {
                "result": "win",
                "pnl": 0.5,
                "stake": 1.0,
                "implied_probability": 0.5,
                "recommendation": {"market": "strikeouts", "selection": "irrelevant", "line": None, "odds": "+100"},
                "artifact_metadata": {"sport": "mlb"},
            }
        ]

        call_counts: dict[int, int] = {}
        for count in (10, 40):
            with patch(
                "syndicate.features.shared.recommendation_engine.build_reliability_profile",
                wraps=recommendation_engine.build_reliability_profile,
            ) as mocked_profile:
                filter_candidates(build_candidates(count), sport="mlb", evaluation_records=historical_records)
            call_counts[count] = mocked_profile.call_count

        self.assertEqual(call_counts[10], call_counts[40])
        self.assertEqual(call_counts[10], 3)  # 1 sport-level + 2 distinct markets (strikeouts, moneyline)

    def test_filter_candidates_suppresses_poor_market_history(self) -> None:
        candidates = [
            {
                "name": "Jayson Tatum Over 28.5 Points",
                "event_id": "game-1",
                "market": "points",
                "pick": "Over 28.5",
                "odds": "+100",
                "score": 86.0,
                "confidence": "63%",
                "model_probability": 0.53,
            },
            {
                "name": "Boston Celtics Moneyline",
                "event_id": "game-1",
                "market": "moneyline",
                "selection": "Boston Celtics",
                "odds": "+140",
                "score": 80.0,
                "confidence": "61%",
                "model_probability": 0.64,
            },
        ]
        historical_records = [
            {
                "result": "loss",
                "pnl": -1.0,
                "stake": 1.0,
                "implied_probability": 0.53,
                "recommendation": {"market": "points", "selection": "Over 28.5", "line": 28.5, "odds": "+100"},
                "artifact_metadata": {"sport": "nba"},
            },
            {
                "result": "loss",
                "pnl": -1.0,
                "stake": 1.0,
                "implied_probability": 0.53,
                "recommendation": {"market": "points", "selection": "Over 28.5", "line": 28.5, "odds": "+100"},
                "artifact_metadata": {"sport": "nba"},
            },
            {
                "result": "loss",
                "pnl": -1.0,
                "stake": 1.0,
                "implied_probability": 0.53,
                "recommendation": {"market": "points", "selection": "Over 28.5", "line": 28.5, "odds": "+100"},
                "artifact_metadata": {"sport": "nba"},
            },
            {
                "result": "win",
                "pnl": 0.4,
                "stake": 1.0,
                "implied_probability": 0.49,
                "recommendation": {"market": "moneyline", "selection": "Boston Celtics", "line": None, "odds": "+140"},
                "artifact_metadata": {"sport": "nba"},
            },
        ]

        filtered = filter_candidates(candidates, sport="nba", evaluation_records=historical_records)
        ranked = rank_recommendations(candidates, sport="nba", evaluation_records=historical_records)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["market"], "moneyline")
        self.assertEqual(ranked[0]["recommendation_id"].startswith("reco_"), True)
        self.assertEqual(ranked[0]["market"], "moneyline")
        self.assertIn("reasoning", ranked[0])
        self.assertIn("risk_factors", ranked[0])
        self.assertIn("confidence_drivers", ranked[0])

    def test_filter_candidates_rejects_pregame_candidate_stale_beyond_the_sla(self) -> None:
        # #117 follow-up (Layer 2 Phase 2a). MLB's pregame sweep interval
        # defaults to 2h, so the SLA ceiling is 3x that = 6h. 8h stale is
        # well past it.
        now = datetime.now(timezone.utc)
        stale_last_updated = (now - timedelta(hours=8)).isoformat()
        fresh_manifest = now.isoformat()
        candidates = [
            {
                "name": "Home ML",
                "event_id": "game-1",
                "market": "moneyline",
                "selection": "Home ML",
                "odds": "+110",
                "model_probability": 0.6,
                "last_updated": stale_last_updated,
                "sport_manifest_last_updated": fresh_manifest,
                "sport_slug": "mlb",
            }
        ]
        filtered = filter_candidates(candidates, sport="mlb", evaluation_records=_UNRELATED_HISTORY)
        self.assertEqual(filtered, [])

    def test_filter_candidates_keeps_a_fresh_pregame_candidate(self) -> None:
        now = datetime.now(timezone.utc)
        fresh_last_updated = (now - timedelta(hours=1)).isoformat()
        candidates = [
            {
                "name": "Home ML",
                "event_id": "game-1",
                "market": "moneyline",
                "selection": "Home ML",
                "odds": "+110",
                "model_probability": 0.6,
                "last_updated": fresh_last_updated,
                "sport_manifest_last_updated": now.isoformat(),
                "sport_slug": "mlb",
            }
        ]
        filtered = filter_candidates(candidates, sport="mlb", evaluation_records=_UNRELATED_HISTORY)
        self.assertEqual(len(filtered), 1)

    def test_filter_candidates_exempts_steam_moves_from_the_edge_threshold(self) -> None:
        # #137 follow-up, confirmed live: a steam move's model_probability is
        # deliberately sourced from the market's own implied_prob (there is
        # no independent model to compare against -- the signal IS the
        # market's recent movement), so its computed edge is always ~0 by
        # construction. Before this fix, every steam candidate failed the
        # ordinary edge-quality gate unconditionally, even though
        # candidate_generation/candidate_scoring showed them surviving
        # every earlier pipeline stage -- traced to this exact gate.
        now = datetime.now(timezone.utc)
        fresh = now.isoformat()
        base = {
            "event_id": "game-1",
            "market": "hits_allowed",
            "selection": "Over 4.5",
            "odds": "+130",
            "implied_probability": 0.435,
            "model_probability": 0.435,  # edge ~= 0, same as a real steam candidate
            "last_updated": fresh,
            "sport_manifest_last_updated": fresh,
            "sport_slug": "mlb",
        }
        steam_candidate = {**base, "name": "Jacob Lopez Over 4.5", "candidate_type": "steam"}
        ordinary_prop = {**base, "name": "Some Other Prop", "candidate_type": "prop"}

        # min_edge forces a real positive threshold -- with the default 0.0
        # and no market history, edge(0.0) < threshold(0.0) is False for
        # EVERYONE, which would make the contrast assertion below pass
        # vacuously regardless of whether the exemption is scoped correctly.
        filtered = filter_candidates(
            [steam_candidate, ordinary_prop], sport="mlb", evaluation_records=_UNRELATED_HISTORY, min_edge=0.05
        )

        filtered_types = {c.get("candidate_type") for c in filtered}
        self.assertIn("steam", filtered_types, filtered)
        # Contrast: the ordinary prop, with the identical near-zero edge,
        # must still be rejected -- this test would pass vacuously if the
        # fix accidentally exempted everything instead of just steam.
        self.assertNotIn("prop", filtered_types, filtered)

    def test_filter_candidates_does_not_reject_for_staleness_when_the_whole_pipeline_is_stalled(self) -> None:
        # If the sport's own manifest is just as stale, an individual
        # candidate being stale isn't a candidate-specific data problem --
        # it's the whole pipeline being down, a bigger issue this gate
        # should not silently paper over by emptying the board.
        now = datetime.now(timezone.utc)
        stale_timestamp = (now - timedelta(hours=8)).isoformat()
        candidates = [
            {
                "name": "Home ML",
                "event_id": "game-1",
                "market": "moneyline",
                "selection": "Home ML",
                "odds": "+110",
                "model_probability": 0.6,
                "last_updated": stale_timestamp,
                "sport_manifest_last_updated": stale_timestamp,
                "sport_slug": "mlb",
            }
        ]
        filtered = filter_candidates(candidates, sport="mlb", evaluation_records=_UNRELATED_HISTORY)
        self.assertEqual(len(filtered), 1)

    def test_filter_candidates_never_time_gates_a_confirmed_open_live_candidate(self) -> None:
        # #124, per explicit user direction ("market still open should be
        # the SLA"): superseded the old 30-minute time-based live ceiling.
        # A live candidate that has already passed the upstream state guard
        # (not final, live claim not frozen for 8h+, player not inactive --
        # i.e. no state_invalid) is trusted regardless of how long ago its
        # price last moved. Confirmed live: real, currently-open MLB prop
        # markets were being discarded by exactly this old time check the
        # moment real live data started flowing through the pipeline.
        now = datetime.now(timezone.utc)
        very_stale_last_updated = (now - timedelta(hours=2)).isoformat()
        candidates = [
            {
                "name": "Home ML",
                "event_id": "game-1",
                "market": "moneyline",
                "selection": "Home ML",
                "odds": "+110",
                "model_probability": 0.6,
                "is_live": True,
                "last_updated": very_stale_last_updated,
                "sport_manifest_last_updated": now.isoformat(),
                "sport_slug": "mlb",
            }
        ]
        filtered = filter_candidates(candidates, sport="mlb", evaluation_records=_UNRELATED_HISTORY)
        self.assertEqual(len(filtered), 1)

    def test_filter_candidates_still_time_gates_a_live_candidate_the_state_guard_already_flagged(self) -> None:
        # Defense in depth: state_invalid should never reach filter_candidates
        # in the real pipeline (the upstream state guard drops it first), but
        # if it somehow does, the market-confirmed-open bypass must not apply
        # to it -- it falls back to the old, tighter time-based ceiling.
        now = datetime.now(timezone.utc)
        stale_last_updated = (now - timedelta(minutes=40)).isoformat()
        candidates = [
            {
                "name": "Home ML",
                "event_id": "game-1",
                "market": "moneyline",
                "selection": "Home ML",
                "odds": "+110",
                "model_probability": 0.6,
                "is_live": True,
                "state_invalid": True,
                "last_updated": stale_last_updated,
                "sport_manifest_last_updated": now.isoformat(),
                "sport_slug": "mlb",
            }
        ]
        filtered = filter_candidates(candidates, sport="mlb", evaluation_records=_UNRELATED_HISTORY)
        self.assertEqual(filtered, [])

    def test_calculate_edge_uses_fair_probability_and_implied_probability(self) -> None:
        edge = calculate_edge({"odds": "+120", "model_probability": 0.58})

        self.assertAlmostEqual(edge["fair_probability"], 0.58, places=2)
        self.assertIsNotNone(edge["implied_probability"])
        self.assertGreater(edge["edge"], 0.0)

    def test_rank_recommendations_standardizes_probability_fields(self) -> None:
        ranked = rank_recommendations(
            [
                {
                    "name": "Jayson Tatum Over 28.5 Points",
                    "event_id": "game-1",
                    "market": "points",
                    "selection": "Over 28.5",
                    "odds": "+100",
                    "score": 86.0,
                    "confidence": 0.63,
                    "model_probability": 0.58,
                    "ev_pct": 12.0,
                }
            ],
            sport="nba",
            evaluation_records=[],
        )

        self.assertEqual(len(ranked), 1)
        self.assertAlmostEqual(ranked[0]["expected_value"], 0.12, places=2)
        self.assertAlmostEqual(ranked[0]["edge_pct"], 8.0, places=2)
        self.assertAlmostEqual(ranked[0]["model_probability"], 0.58, places=2)
        self.assertAlmostEqual(ranked[0]["market_probability"], 0.5, places=2)

    def test_rank_recommendations_applies_bounded_performance_multiplier(self) -> None:
        def _rank_with_summary(summary: dict[str, object]) -> dict[str, object]:
            with TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                ledger_path = root / "reports" / "intelligence" / "evaluation_ledger.jsonl"
                ledger_path.parent.mkdir(parents=True, exist_ok=True)
                (root / "reports" / "performance_summary.json").write_text(json.dumps(summary), encoding="utf-8")

                ranked = rank_recommendations(
                    [
                        {
                            "name": "Jayson Tatum Over 28.5 Points",
                            "event_id": "game-1",
                            "market": "points",
                            "selection": "Over 28.5",
                            "odds": "+100",
                            "score": 86.0,
                            "confidence": 0.63,
                            "model_probability": 0.62,
                        }
                    ],
                    sport="nba",
                    ledger_path=ledger_path,
                    evaluation_records=[],
                )

            return ranked[0]

        positive = _rank_with_summary(
            {
                "schema_version": 1,
                "by_sport": {"nba": {"roi": 0.18}},
                "by_market": {"points": {"roi": 0.12}},
                "by_probability_bucket": [
                    {"bucket": "0.60-0.70", "predicted_probability": 0.62, "actual_win_rate": 0.70, "roi": 0.09}
                ],
            }
        )
        negative = _rank_with_summary(
            {
                "schema_version": 1,
                "by_sport": {"nba": {"roi": -0.18}},
                "by_market": {"points": {"roi": -0.12}},
                "by_probability_bucket": [
                    {"bucket": "0.60-0.70", "predicted_probability": 0.62, "actual_win_rate": 0.54, "roi": -0.09}
                ],
            }
        )

        self.assertGreater(positive["performance_multiplier"], 1.0)
        self.assertLess(negative["performance_multiplier"], 1.0)
        self.assertGreater(positive["adjusted_score"], positive["core_adjusted_score"])
        self.assertLess(negative["adjusted_score"], negative["core_adjusted_score"])
        self.assertGreater(positive["adjusted_score"], negative["adjusted_score"])

    def test_rank_recommendations_reprices_live_current_odds(self) -> None:
        ranked = rank_recommendations(
            [
                {
                    "name": "Jayson Tatum Over 28.5 Points",
                    "event_id": "game-1",
                    "market": "points",
                    "selection": "Over 28.5",
                    "odds": "+100",
                    "current_odds": "+150",
                    "score": 86.0,
                    "is_live": True,
                    "model_probability": 0.60,
                }
            ],
            sport="nba",
            evaluation_records=[],
        )

        self.assertEqual(len(ranked), 1)
        self.assertAlmostEqual(ranked[0]["market_probability"], 0.4, places=2)
        self.assertAlmostEqual(ranked[0]["expected_value"], 0.5, places=2)
        self.assertAlmostEqual(ranked[0]["ev_open"], 0.2, places=2)
        self.assertAlmostEqual(ranked[0]["ev_current"], 0.5, places=2)
        self.assertAlmostEqual(ranked[0]["ev_delta"], 0.3, places=2)
        self.assertEqual(ranked[0]["odds_open"], "+100")
        self.assertEqual(ranked[0]["odds_current"], "+150")
        self.assertAlmostEqual(ranked[0]["line_movement_impact"], 0.1, places=2)
        self.assertAlmostEqual(ranked[0]["edge"], 0.2, places=2)

    def test_rank_recommendations_preserves_pregame_expected_value(self) -> None:
        ranked = rank_recommendations(
            [
                {
                    "name": "Jayson Tatum Over 28.5 Points",
                    "event_id": "game-1",
                    "market": "points",
                    "selection": "Over 28.5",
                    "odds": "+100",
                    "score": 86.0,
                    "model_probability": 0.58,
                    "ev_pct": 12.0,
                }
            ],
            sport="nba",
            evaluation_records=[],
        )

        self.assertEqual(len(ranked), 1)
        self.assertAlmostEqual(ranked[0]["expected_value"], 0.12, places=2)

    def test_rank_recommendations_derives_model_probability_from_simulation_distribution(self) -> None:
        ranked = rank_recommendations(
            [
                {
                    "name": "Jayson Tatum Over 28.5 Points",
                    "event_id": "game-1",
                    "market": "points",
                    "selection": "Over 28.5",
                    "odds": "+100",
                    "score": 86.0,
                    "simulation": {"probability_distributions": {"win": 0.64, "loss": 0.36}},
                }
            ],
            sport="nba",
            evaluation_records=[],
        )

        self.assertEqual(len(ranked), 1)
        self.assertAlmostEqual(ranked[0]["model_probability"], 0.64, places=2)

    def test_rank_recommendations_derives_model_probability_from_sim_hit_rate(self) -> None:
        ranked = rank_recommendations(
            [
                {
                    "name": "Jayson Tatum Over 28.5 Points",
                    "event_id": "game-1",
                    "market": "points",
                    "selection": "Over 28.5",
                    "odds": "+100",
                    "score": 86.0,
                    "sim": {"hit_rate": 0.57},
                }
            ],
            sport="nba",
            evaluation_records=[],
        )

        self.assertEqual(len(ranked), 1)
        self.assertAlmostEqual(ranked[0]["model_probability"], 0.57, places=2)

    def test_rank_recommendations_attaches_historical_context_from_performance_summary(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ledger_path = root / "reports" / "intelligence" / "evaluation_ledger.jsonl"
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            (root / "reports" / "performance_summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "by_sport_market": {
                            "nba": {
                                "points": {"roi_segment": 0.142, "sample_size": 28, "total_bets": 28, "settled_count": 28},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            ranked = rank_recommendations(
                [
                    {
                        "name": "Jayson Tatum Over 28.5 Points",
                        "event_id": "game-1",
                        "sport": "nba",
                        "market": "points",
                        "selection": "Over 28.5",
                        "odds": "+100",
                        "score": 86.0,
                        "confidence": 0.63,
                        "model_probability": 0.58,
                        "ev_pct": 12.0,
                    }
                ],
                sport="nba",
                ledger_path=ledger_path,
                evaluation_records=[],
            )

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["historical_context"], {"roi_segment": 0.142, "sample_size": 28})

    def test_rank_recommendations_leaves_historical_context_null_without_summary_match(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ledger_path = root / "reports" / "intelligence" / "evaluation_ledger.jsonl"
            ledger_path.parent.mkdir(parents=True, exist_ok=True)

            ranked = rank_recommendations(
                [
                    {
                        "name": "Jayson Tatum Over 28.5 Points",
                        "event_id": "game-1",
                        "sport": "nba",
                        "market": "points",
                        "selection": "Over 28.5",
                        "odds": "+100",
                        "score": 86.0,
                        "confidence": 0.63,
                        "model_probability": 0.58,
                        "ev_pct": 12.0,
                    }
                ],
                sport="nba",
                ledger_path=ledger_path,
                evaluation_records=[],
            )

        self.assertEqual(len(ranked), 1)
        self.assertIsNone(ranked[0]["historical_context"])

    def test_policy_specific_filtering_changes_threshold_behavior(self) -> None:
        candidate = {
            "name": "Jayson Tatum Over 28.5 Points",
            "event_id": "game-1",
            "market": "points",
            "pick": "Over 28.5",
            "odds": "+100",
            "score": 81.0,
            "confidence": 0.57,
            "model_probability": 0.51,
        }

        conservative = filter_candidates([candidate], sport="nba", evaluation_records=[], policy="conservative")
        aggressive = filter_candidates([candidate], sport="nba", evaluation_records=[], policy="aggressive")

        self.assertEqual(conservative, [])
        self.assertEqual(len(aggressive), 1)
        self.assertEqual(aggressive[0]["market"], "points")

    def test_policy_summary_promotes_better_labeled_strategy(self) -> None:
        # Phase 5: min_sample_size was raised 8 -> 50 (see DecisionPolicy's
        # own comment) -- bumped from range(8) to range(50) so this clean,
        # unambiguous all-win-vs-all-loss scenario still clears the new gate.
        # The test's intent (an obvious signal still promotes) is unchanged.
        balanced_records = [
            {
                "result": "loss",
                "pnl": -1.0,
                "stake": 1.0,
                "implied_probability": 0.53,
                "decision_strategy": "balanced",
                "recommendation": {"market": "points", "selection": "Over 28.5", "confidence": 0.57, "edge": 0.02},
                "artifact_metadata": {"sport": "nba"},
            }
            for _ in range(50)
        ]
        aggressive_records = [
            {
                "result": "win",
                "pnl": 0.8,
                "stake": 1.0,
                "implied_probability": 0.49,
                "decision_strategy": "aggressive",
                "recommendation": {"market": "moneyline", "selection": "Boston Celtics", "confidence": 0.64, "edge": 0.07},
                "artifact_metadata": {"sport": "nba"},
            }
            for _ in range(50)
        ]
        history = balanced_records + aggressive_records

        comparison = compare_policies(history, sport="nba")
        summary = build_policy_optimization_summary(history, sport="nba")

        self.assertEqual(comparison[0]["policy"], "aggressive")
        self.assertEqual(summary["selected_policy"], "aggressive")
        self.assertTrue(summary["promoted"])
        self.assertEqual(select_policy(history, sport="nba"), "aggressive")

    def test_small_sample_noise_does_not_trigger_promotion(self) -> None:
        # Phase 5 regression test for the exact bug found: a 1-bet-out-of-12
        # swing (ordinary binomial noise for a ~55% strategy) used to
        # immediately promote the "luckier" policy under the old
        # promotion_margin=0.01-0.02 / min_sample_size=8 thresholds. With the
        # rescaled thresholds, this small, noisy sample must NOT promote.
        def _record(policy: str, win: bool) -> dict:
            return {
                "result": "win" if win else "loss",
                "pnl": 0.91 if win else -1.0,
                "stake": 1.0,
                "implied_probability": 0.5,
                "recommendation": {"policy": policy, "edge": 0.04, "confidence": 0.58, "sport": "mlb"},
                "query": {"sport": "mlb"},
            }

        history = []
        for policy, wins in (("balanced", 6), ("aggressive", 7)):
            for i in range(12):
                history.append(_record(policy, win=i < wins))

        summary = build_policy_optimization_summary(history, sport="mlb")

        self.assertFalse(summary["promoted"])
        self.assertEqual(summary["selected_policy"], recommendation_engine.DEFAULT_POLICY)

    def test_artifact_metadata_carries_policy_selection(self) -> None:
        policy_comparison = [
            {
                "policy": "aggressive",
                "sample_size": 8,
                "settled_count": 8,
                "weighted_roi": 0.12,
                "weighted_win_rate": 0.75,
                "average_alignment": 0.81,
                "average_edge": 0.06,
                "average_confidence": 0.64,
                "average_calibration_error": 0.08,
                "promotion_score": 18.4,
                "promotion_margin": 0.01,
                "min_sample_size": 8,
            }
        ]
        metadata = build_artifact_metadata(
            query={"sport": "nba"},
            response={"recommendations": [{"decision_strategy": "aggressive", "historical_profile": {"policy_comparison": policy_comparison}}]},
        )

        self.assertEqual(metadata["decision_strategy"], "aggressive")
        self.assertEqual(metadata["policy_comparison"], policy_comparison)


if __name__ == "__main__":
    unittest.main()