from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import syndicate.features.shared.intelligence_evaluation as intelligence_evaluation
from syndicate.features.shared.intelligence_evaluation import build_intelligence_evaluation_bundle
from syndicate.features.shared.intelligence_evaluation import build_recommendation_performance_analytics
from syndicate.features.shared.intelligence_evaluation import build_recommendation_performance_analytics_for_window
from syndicate.features.shared.intelligence_evaluation import adjust_confidence
from syndicate.features.shared.intelligence_evaluation import compute_metrics
from syndicate.features.shared.intelligence_evaluation import record_prediction
from syndicate.features.shared.intelligence_evaluation import record_portfolio_event
from syndicate.features.shared.intelligence_evaluation import record_recommendation
from syndicate.features.shared.intelligence_evaluation import settle_result


class IntelligenceEvaluationTests(unittest.TestCase):
    def test_build_intelligence_evaluation_bundle_includes_prediction_and_recommendations(self) -> None:
        bundle = build_intelligence_evaluation_bundle(
            query={
                "question": "preview the Celtics game tonight",
                "selected_date": "2026-06-08",
                "sport": "nba",
            },
            response={
                "selected_date": "2026-06-08",
                "recommendations": [
                    {
                        "name": "Boston Celtics",
                        "pick": "Over 28.5",
                        "line": 28.5,
                        "model_probability": 0.63,
                    }
                ],
                "analysis_views": {"focus": "nba_matchups"},
            },
            persist=False,
        )

        self.assertEqual(bundle["schema_version"], 1)
        self.assertIn("prediction", bundle)
        self.assertEqual(bundle["prediction"]["prediction_id"].startswith("pred_"), True)
        self.assertEqual(len(bundle["recommendations"]), 1)
        self.assertTrue(bundle["recommendations"][0]["recommendation_id"].startswith("rec_"))
        self.assertEqual(bundle["artifact_metadata"]["sport"], "nba")

    def test_build_intelligence_evaluation_bundle_includes_line_movement_metadata(self) -> None:
        bundle = build_intelligence_evaluation_bundle(
            query={
                "question": "preview the slate",
                "selected_date": "2026-06-11",
                "sport": "nhl",
            },
            response={
                "selected_date": "2026-06-11",
                "recommendations": [
                    {
                        "name": "Home Team Over 6.5",
                        "pick": "Over 6.5",
                        "line": 6.5,
                        "movement": {"delta": 0.0, "trend": "flat", "last_updated": "2026-06-11T12:00:00Z"},
                    },
                    {
                        "name": "Away Team Under 2.5",
                        "pick": "Under 2.5",
                        "line": 2.5,
                        "movement": {"delta": -0.5, "trend": "down", "last_updated": "2026-06-11T14:30:00Z"},
                    },
                ],
            },
            persist=False,
        )

        metadata = bundle["artifact_metadata"]
        self.assertTrue(metadata["has_line_movement"])
        self.assertAlmostEqual(metadata["max_delta_detected"], 0.5)
        self.assertEqual(metadata["last_odds_update_timestamp"], "2026-06-11T14:30:00Z")

    def test_build_intelligence_evaluation_bundle_includes_history_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            bundle = build_intelligence_evaluation_bundle(
                query={
                    "question": "top edges today",
                    "selected_date": "2026-06-11",
                    "sport": "nba",
                },
                response={
                    "selected_date": "2026-06-11",
                    "recommendations": [
                        {
                            "name": "Jayson Tatum Over 28.5",
                            "market": "points",
                            "line": 28.5,
                            "model_probability": 0.63,
                        }
                    ],
                },
                persist=True,
                ledger_path=ledger_path,
            )

        self.assertEqual(bundle["history"]["sport"], "nba")
        self.assertEqual(bundle["history"]["market_family"], "props")
        self.assertIn("history_status", bundle["history"])

    def test_build_recommendation_performance_analytics_groups_roi_and_clv(self) -> None:
        records = [
            {
                "prediction_id": "pred_1",
                "recommendation_id": "rec_1",
                "created_at": "2026-06-11T12:00:00Z",
                "stake": 1.0,
                "pnl": 0.8,
                "result": "win",
                "closing_line": 27.5,
                "recommendation": {
                    "sport": "nba",
                    "market": "points",
                    "selection": "Over 28.5",
                    "name": "Jayson Tatum Over 28.5",
                    "line": 28.5,
                    "odds": -110,
                    "model_probability": 0.64,
                    "implied_probability": 0.55,
                    "edge_pct": 7.0,
                    "confidence": 0.78,
                    "recommendation_type": "prop",
                },
            },
            {
                "prediction_id": "pred_2",
                "recommendation_id": "rec_2",
                "created_at": "2026-06-11T12:05:00Z",
                "stake": 2.0,
                "pnl": -2.0,
                "result": "loss",
                "closing_line": 10.5,
                "recommendation": {
                    "sport": "wnba",
                    "market": "rebounds",
                    "selection": "Under 8.5",
                    "name": "A'ja Wilson Under 8.5 Rebounds",
                    "line": 8.5,
                    "odds": +102,
                    "model_probability": 0.58,
                    "implied_probability": 0.49,
                    "edge_pct": 4.0,
                    "confidence": 0.62,
                    "recommendation_type": "prop",
                },
            },
        ]

        analytics = build_recommendation_performance_analytics(records=records)

        self.assertEqual(analytics["summary"]["publish_count"], 2)
        self.assertEqual(analytics["summary"]["settled_count"], 2)
        self.assertAlmostEqual(analytics["summary"]["roi"], -0.4, places=2)
        self.assertEqual(len(analytics["by_sport"]), 2)
        self.assertEqual(analytics["by_sport"][0]["bucket"], "nba")
        self.assertEqual(analytics["by_market"][0]["bucket"], "points")
        self.assertIn("high", {row["bucket"] for row in analytics["by_confidence_tier"]})
        self.assertIn("5-8", {row["bucket"] for row in analytics["by_edge_bucket"]})
        self.assertEqual({row["bucket"] for row in analytics["by_recommendation_type"]}, {"prop"})
        self.assertEqual(analytics["records"][0]["publish_timestamp"], "2026-06-11T12:00:00Z")
        self.assertIn("clv", analytics["records"][0])
        self.assertEqual(len(analytics["by_date"]), 1)
        self.assertEqual(analytics["by_date"][0]["bucket"], "2026-06-11")
        self.assertEqual(analytics["by_date"][0]["publish_count"], 2)

    def test_performance_analytics_for_window_scopes_by_date_and_sport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path):
                for date_str, sport in (
                    ("2026-06-01", "mlb"),
                    ("2026-06-05", "wnba"),
                    ("2026-06-10", "mlb"),
                ):
                    prediction = record_prediction(
                        query={"question": "test", "selected_date": date_str, "sport": sport},
                        response={"selected_date": date_str, "recommendations": []},
                        persist=True,
                    )
                    record_recommendation(
                        prediction_record=prediction,
                        recommendation={"name": "pick", "pick": "Over", "line": 1.5, "sport": sport},
                        persist=True,
                    )

                # Each date writes one prediction record + one recommendation
                # record; both survive _latest_by_recommendation_id (the
                # prediction falls back to a prediction_id key), so 2
                # in-window dates -> 4 normalized records.
                windowed = build_recommendation_performance_analytics_for_window(
                    since="2026-06-04", until="2026-06-10", ledger_path=ledger_path
                )
                self.assertEqual(windowed["summary"]["publish_count"], 4)
                dates_seen = {row["publish_date"] for row in windowed["records"]}
                self.assertEqual(dates_seen, {"2026-06-05", "2026-06-10"})

                sport_scoped = build_recommendation_performance_analytics_for_window(
                    since="2026-06-01", until="2026-06-10", sport="mlb", ledger_path=ledger_path
                )
                self.assertEqual(sport_scoped["summary"]["publish_count"], 4)
                self.assertTrue(all(row.get("sport") == "mlb" for row in sport_scoped["records"] if "sport" in row))

                empty_window = build_recommendation_performance_analytics_for_window(
                    since="2026-07-01", until="2026-07-05", ledger_path=ledger_path
                )
                self.assertEqual(empty_window["summary"]["publish_count"], 0)

    def test_default_ledger_path_writes_chunked_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path):
                first_record = record_prediction(
                    query={"question": "chunked default ledger", "selected_date": "2026-06-14", "sport": "nba"},
                    response={"selected_date": "2026-06-14", "recommendations": []},
                    persist=True,
                )
                second_record = record_prediction(
                    query={"question": "chunked default ledger", "selected_date": "2026-06-14", "sport": "nba"},
                    response={"selected_date": "2026-06-14", "recommendations": []},
                    persist=True,
                )

            chunk_file = ledger_path.parent / "evaluation_ledger_chunks" / "2026-06-14.jsonl"
            manifest_file = ledger_path.parent / "evaluation_ledger_chunks" / "manifest.json"

            self.assertEqual(first_record["prediction_id"], second_record["prediction_id"])
            self.assertFalse(ledger_path.exists())
            self.assertTrue(chunk_file.exists())
            self.assertTrue(manifest_file.exists())
            self.assertEqual(len(chunk_file.read_text(encoding="utf-8").strip().splitlines()), 1)

    def test_build_intelligence_evaluation_bundle_includes_portfolio_tracking_summary(self) -> None:
        bundle = build_intelligence_evaluation_bundle(
            query={
                "question": "top edges today",
                "selected_date": "2026-06-11",
                "sport": "nba",
            },
            response={
                "selected_date": "2026-06-11",
                "portfolio": {
                    "total_exposure": 0.12,
                    "risk_level": "low",
                    "expected_return": 0.034,
                    "average_correlation": 0.21,
                    "diversification_score": 0.88,
                },
                "recommendations": [
                    {
                        "name": "Jayson Tatum Over 28.5",
                        "market": "points",
                        "line": 28.5,
                        "model_probability": 0.63,
                    }
                ],
            },
            persist=False,
        )

        tracking = bundle["portfolio_tracking"]
        self.assertAlmostEqual(tracking["open_exposure"], 0.12)
        self.assertEqual(tracking["risk_level"], "low")
        self.assertEqual(tracking["wager_count"], 1)

    def test_artifact_manifest_summary_for_all_uses_per_sport_manifests(self) -> None:
        fake_manifest = type(
            "FakeManifest",
            (),
            {
                "to_dict": lambda self: {"sport_slug": "nba", "selected_date": "2026-07-04"},
            },
        )()

        with patch.object(intelligence_evaluation, "load_artifact_manifests", return_value=[fake_manifest]) as mocked_loader:
            summary = intelligence_evaluation._artifact_manifest_summary(selected_date="2026-07-04", sport="all")

        mocked_loader.assert_called_once_with(selected_date="2026-07-04", sport_slugs=None)
        self.assertEqual(summary["manifest_count"], 1)
        self.assertEqual(summary["sport_manifests"][0]["sport_slug"], "nba")

    def test_build_intelligence_evaluation_bundle_includes_portfolio_event_summary(self) -> None:
        bundle = build_intelligence_evaluation_bundle(
            query={
                "question": "top edges today",
                "selected_date": "2026-06-11",
                "sport": "nba",
            },
            response={
                "selected_date": "2026-06-11",
                "portfolio_events": [
                    {"action": "add", "status": "open"},
                    {"action": "remove", "status": "closed"},
                    {"action": "adjust", "status": "open"},
                ],
                "recommendations": [],
            },
            persist=False,
        )

        events = bundle["portfolio_events"]
        self.assertEqual(events["event_count"], 3)
        self.assertEqual(events["added_count"], 1)
        self.assertEqual(events["removed_count"], 1)
        self.assertEqual(events["adjusted_count"], 1)

    def test_build_intelligence_evaluation_bundle_includes_policy_control_summary(self) -> None:
        bundle = build_intelligence_evaluation_bundle(
            query={
                "question": "top edges today",
                "selected_date": "2026-06-11",
                "sport": "nba",
            },
            response={
                "selected_date": "2026-06-11",
                "recommendations": [
                    {
                        "decision_strategy": "aggressive",
                        "historical_profile": {
                            "policy_comparison": [
                                {
                                    "policy": "aggressive",
                                    "sample_size": 8,
                                    "promotion_score": 18.4,
                                }
                            ],
                        },
                    }
                ],
            },
            persist=False,
        )

        policy_control = bundle["policy_control"]
        self.assertEqual(policy_control["selected_policy"], "aggressive")
        self.assertEqual(policy_control["leader_policy"], "aggressive")
        self.assertEqual(policy_control["policy_status"], "available")

    def test_record_portfolio_event_is_stable_and_bundle_exposes_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            prediction = record_prediction(
                query={"question": "manual portfolio event", "selected_date": "2026-06-13", "sport": "nba"},
                response={"selected_date": "2026-06-13", "recommendations": []},
                persist=False,
            )
            event_payload = {"action": "add", "status": "open", "name": "Boston Celtics", "market": "points"}
            first_record = record_portfolio_event(
                prediction_record=prediction,
                portfolio_event=event_payload,
                persist=True,
                ledger_path=ledger_path,
            )
            second_record = record_portfolio_event(
                prediction_record=prediction,
                portfolio_event=event_payload,
                persist=True,
                ledger_path=ledger_path,
            )
            bundle = build_intelligence_evaluation_bundle(
                query={"question": "manual portfolio event", "selected_date": "2026-06-13", "sport": "nba"},
                response={
                    "selected_date": "2026-06-13",
                    "recommendations": [],
                    "portfolio_events": [event_payload],
                },
                persist=True,
                ledger_path=ledger_path,
            )

            ledger_lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()

        self.assertEqual(first_record["record_type"], "portfolio_event")
        self.assertEqual(first_record["portfolio_event"]["action"], "add")
        self.assertEqual(first_record["portfolio_event_id"], second_record["portfolio_event_id"])
        self.assertEqual(len(ledger_lines), 3)
        self.assertEqual(bundle["portfolio_event_records"][0]["record_type"], "portfolio_event")
        self.assertEqual(bundle["portfolio_event_records"][0]["portfolio_event"]["action"], "add")

    def test_record_portfolio_event_preserves_prediction_and_recommendation_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            prediction = record_prediction(
                query={"question": "manual portfolio event", "selected_date": "2026-06-13", "sport": "nba"},
                response={"selected_date": "2026-06-13", "recommendations": []},
                persist=False,
            )
            portfolio_event = {
                "action": "add",
                "status": "open",
                "name": "Boston Celtics",
                "market": "points",
                "prediction_id": prediction["prediction_id"],
                "recommendation_id": "rec_test_123",
            }

            first_record = record_portfolio_event(
                prediction_record=prediction,
                portfolio_event=portfolio_event,
                persist=True,
                ledger_path=ledger_path,
            )
            second_record = record_portfolio_event(
                prediction_record=prediction,
                portfolio_event=portfolio_event,
                persist=True,
                ledger_path=ledger_path,
            )

            ledger_lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()

        self.assertEqual(first_record["prediction_id"], prediction["prediction_id"])
        self.assertEqual(first_record["recommendation_id"], "rec_test_123")
        self.assertEqual(first_record["portfolio_event_id"], second_record["portfolio_event_id"])
        self.assertEqual(len(ledger_lines), 1)

    def test_build_intelligence_evaluation_bundle_appends_only_changed_event_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            base_query = {
                "question": "preview the slate",
                "selected_date": "2026-06-08",
                "sport": "nba",
            }
            base_response = {
                "selected_date": "2026-06-08",
                "recommendations": [
                    {
                        "event_id": "game_1",
                        "name": "Boston Celtics",
                        "pick": "Over 28.5",
                        "line": 28.5,
                        "model_probability": 0.63,
                    },
                    {
                        "event_id": "game_2",
                        "name": "Los Angeles Lakers",
                        "pick": "Under 24.5",
                        "line": 24.5,
                        "model_probability": 0.57,
                    },
                ],
            }

            first_bundle = build_intelligence_evaluation_bundle(
                query=base_query,
                response=base_response,
                ledger_path=ledger_path,
            )
            second_bundle = build_intelligence_evaluation_bundle(
                query=base_query,
                response={
                    **base_response,
                    "recommendations": [
                        base_response["recommendations"][0],
                        {
                            "event_id": "game_2",
                            "name": "Los Angeles Lakers",
                            "pick": "Under 25.5",
                            "line": 25.5,
                            "model_probability": 0.59,
                        },
                    ],
                },
                ledger_path=ledger_path,
            )

            ledger_lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(ledger_lines), 4)
            self.assertEqual(first_bundle["prediction"]["prediction_id"], second_bundle["prediction"]["prediction_id"])
            self.assertEqual(first_bundle["recommendations"][0]["recommendation_id"], second_bundle["recommendations"][0]["recommendation_id"])
            self.assertNotEqual(first_bundle["recommendations"][1]["recommendation_id"], second_bundle["recommendations"][1]["recommendation_id"])

    def test_settle_result_and_compute_metrics(self) -> None:
        prediction = record_prediction(
            query={"question": "analyze Tatum tonight", "selected_date": "2026-06-08"},
            response={"selected_date": "2026-06-08", "recommendations": []},
            persist=False,
        )
        recommendation = record_recommendation(
            prediction_record=prediction,
            recommendation={"name": "Jayson Tatum Over 28.5", "pick": "Over 28.5", "line": 28.5, "model_probability": 0.63},
            persist=False,
        )
        settled = settle_result(
            record=recommendation,
            result="win",
            pnl=0.91,
            closing_line=27.5,
            implied_probability=0.63,
            persist=False,
        )

        metrics = compute_metrics(
            records=[
                settled,
                settle_result(
                    record={**recommendation, "recommendation_id": "rec_other"},
                    result="loss",
                    pnl=-1.0,
                    closing_line=29.5,
                    implied_probability=0.55,
                    persist=False,
                ),
            ]
        )

        self.assertEqual(settled["result"], "win")
        self.assertAlmostEqual(metrics["win_rate"], 0.5)
        self.assertAlmostEqual(metrics["roi"], -0.045, places=3)
        self.assertAlmostEqual(metrics["clv"], 0.0, places=3)
        self.assertAlmostEqual(metrics["calibration"]["mae"], 0.46, places=2)

    def test_settle_result_persists_in_place_on_chunked_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path):
                prediction = record_prediction(
                    query={"question": "analyze Tatum tonight", "selected_date": "2026-06-08", "sport": "nba"},
                    response={"selected_date": "2026-06-08", "recommendations": []},
                    persist=True,
                )
                recommendation = record_recommendation(
                    prediction_record=prediction,
                    recommendation={"name": "Jayson Tatum Over 28.5", "pick": "Over 28.5", "line": 28.5, "model_probability": 0.63},
                    persist=True,
                )

                chunk_file = ledger_path.parent / "evaluation_ledger_chunks" / "2026-06-08.jsonl"
                pending_lines = chunk_file.read_text(encoding="utf-8").strip().splitlines()
                self.assertEqual(len(pending_lines), 2)  # prediction + recommendation records
                self.assertIn('"pending"', pending_lines[-1])

                settled = settle_result(
                    record=recommendation,
                    result="win",
                    pnl=0.91,
                    closing_line=27.5,
                    implied_probability=0.63,
                    persist=True,
                )

                # persist=True must actually rewrite the on-disk record, not silently no-op
                # because the identity was already present in evaluation_ledger_chunks/index.json.
                settled_lines = chunk_file.read_text(encoding="utf-8").strip().splitlines()
                self.assertEqual(len(settled_lines), 2)  # updated in place, no duplicate line
                on_disk_recommendation = json.loads(settled_lines[-1])
                self.assertEqual(on_disk_recommendation["result"], "win")
                self.assertEqual(on_disk_recommendation["recommendation_id"], recommendation["recommendation_id"])

                loaded_records = intelligence_evaluation._iter_record_payloads(ledger_path=ledger_path)
                loaded_recommendation = next(
                    r for r in loaded_records if r.get("recommendation_id") == recommendation["recommendation_id"]
                )
                self.assertEqual(loaded_recommendation["result"], "win")

                metrics = compute_metrics(ledger_path=ledger_path)
                self.assertEqual(metrics["settled_count"], 1)
                self.assertEqual(metrics["win_rate"], 1.0)

                profile = intelligence_evaluation.build_reliability_profile(ledger_path=ledger_path, sport="nba")
                self.assertEqual(profile["sample_size"], 1)

    def test_adjust_confidence_penalizes_poor_calibration(self) -> None:
        adjusted, profile = adjust_confidence(
            0.72,
            records=[
                {"result": "win", "pnl": 1.0, "stake": 1.0, "implied_probability": 0.72, "artifact_metadata": {"sport": "nba"}},
                {"result": "loss", "pnl": -1.0, "stake": 1.0, "implied_probability": 0.72, "artifact_metadata": {"sport": "nba"}},
                {"result": "loss", "pnl": -1.0, "stake": 1.0, "implied_probability": 0.72, "artifact_metadata": {"sport": "nba"}},
            ],
            sport="nba",
        )

        self.assertLess(adjusted, 0.72)
        self.assertGreater(profile["calibration_error"], 0.0)
        self.assertEqual(profile["sport"], "nba")


if __name__ == "__main__":
    unittest.main()