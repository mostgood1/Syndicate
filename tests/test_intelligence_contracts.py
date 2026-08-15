from __future__ import annotations

import unittest

from pipeline.intelligence_models import IntelligenceResult
from syndicate.features.intelligence import _candidate_summary
from syndicate.features.intelligence.scoring.edge import get_top_live_opportunities
from syndicate.features.shared.intelligence_contracts import build_intelligence_evaluation_record
from syndicate.features.shared.intelligence_contracts import resolve_candidate_game_date
from syndicate.features.shared.intelligence_contracts import UniversalCandidate


class UniversalCandidateSchemaTests(unittest.TestCase):
    def test_universal_candidate_normalizes_numeric_odds_and_metadata(self) -> None:
        candidate = UniversalCandidate.from_raw(
            {
                "candidate_id": "cand_123",
                "sport": "MLB",
                "type": "prop",
                "selection": "Bryce Eldridge Over 1.5 Total Bases",
                "market": "total_bases",
                "odds": "+110",
                "projection": "1.8",
                "model_probability": "58",
                "implied_probability": "47.62",
                "edge": "10.38",
                "normalized_edge": "0.1038",
                "confidence": "72",
                "score": "91.5",
                "scoring_mode": "full",
                "source_strength": "0.83",
                "is_live": False,
                "timestamp": "2026-06-18T12:34:56Z",
                "sport_context": {"matchup": "SF at LAA", "line": "1.5", "market_key": "total_bases"},
                "provenance": {"source": "mlb_pipeline"},
                "quality": {"score_inputs_missing": []},
            }
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.candidate_id, "cand_123")
        self.assertEqual(candidate.sport, "MLB")
        self.assertEqual(candidate.type, "prop")
        self.assertEqual(candidate.odds, 110.0)
        self.assertEqual(candidate.projection, 1.8)
        self.assertEqual(candidate.model_probability, 0.58)
        self.assertEqual(candidate.implied_probability, 0.4762)
        self.assertEqual(candidate.edge, 0.1038)
        self.assertEqual(candidate.normalized_edge, 0.1038)
        self.assertEqual(candidate.confidence, 0.72)
        self.assertEqual(candidate.score, 91.5)
        self.assertEqual(candidate.scoring_mode, "full")
        self.assertEqual(candidate.source_strength, 0.83)
        self.assertFalse(candidate.is_live)
        self.assertEqual(candidate.timestamp, "2026-06-18T12:34:56Z")
        self.assertEqual(candidate.sport_context["matchup"], "SF at LAA")
        self.assertEqual(candidate.provenance["source"], "mlb_pipeline")
        self.assertEqual(candidate.quality["score_inputs_missing"], [])

    def test_universal_candidate_supports_minimal_data_without_sport_specific_branching(self) -> None:
        candidate = UniversalCandidate.from_raw(
            {
                "sport": "nba",
                "selection": "Jayson Tatum Over 28.5 Points",
                "market": "points",
                "odds": -105,
                "is_live": True,
                "timestamp": "2026-06-18T15:00:00Z",
                "scoring_mode": "minimal",
            }
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.sport, "nba")
        self.assertEqual(candidate.odds, -105.0)
        self.assertEqual(candidate.source_strength, 0.5)
        self.assertTrue(candidate.is_live)
        self.assertEqual(candidate.timestamp, "2026-06-18T15:00:00Z")
        self.assertEqual(candidate.scoring_mode, "minimal")
        self.assertTrue(candidate.quality["has_market_price"])
        self.assertFalse(candidate.quality["has_model"])


class IntelligenceContractsTest(unittest.TestCase):
    def test_build_intelligence_evaluation_record_normalizes_query_and_response(self) -> None:
        record = build_intelligence_evaluation_record(
            query={
                "question": "preview the Celtics game tonight",
                "selected_date": "2026-06-08",
                "query_type": "game_preview",
                "intent": "game_preview",
                "sport": "nba",
                "preview_subject": "celtics",
                "requested_markets": ["moneyline", "total"],
                "limit": 3,
                "mode": "analysis",
            },
            response={
                "headline": "The Syndicate preview",
                "summary": "Scanned 3 board candidates across 1 sports.",
                "analysis_views": {"focus": "nba_matchups"},
                "recommendations": [
                    {
                        "name": "Boston Celtics",
                        "market": "moneyline",
                        "score": 9.8,
                        "market_fit_score": 7.4,
                    }
                ],
            },
            outcome={"status": "pending"},
        )

        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["query"]["query_type"], "game_preview")
        self.assertEqual(record["query"]["subject"], "celtics")
        self.assertEqual(record["query"]["requested_markets"], ["moneyline", "total"])
        self.assertEqual(record["recommendation_count"], 1)
        self.assertEqual(record["top_recommendation"]["name"], "Boston Celtics")
        self.assertEqual(record["analysis_focus"], "nba_matchups")
        self.assertEqual(record["outcome"]["status"], "pending")

    def test_intelligence_result_build_evaluation_record_uses_pipeline_request(self) -> None:
        result = IntelligenceResult.from_raw(
            {
                "selected_date": "2026-06-08",
                "query_type": "player_analysis",
                "headline": "The Syndicate player brief",
                "summary": "Example summary.",
                "parsed_request": {"question": "analyze Tatum tonight", "selected_date": "2026-06-08"},
                "recommendations": [
                    {
                        "name": "Jayson Tatum Over 28.5 Points",
                        "market": "points",
                        "score": 10.1,
                    }
                ],
                "analysis_views": {"focus": "nba_matchups"},
            },
            pipeline_request={
                "question": "analyze Tatum tonight",
                "selected_date": "2026-06-08",
                "query_type": "player_analysis",
                "player_subject": "Jayson Tatum",
                "sport": "nba",
            },
        )

        record = result.build_evaluation_record(outcome={"status": "final", "actual": "hit"})

        self.assertEqual(record["query"]["question"], "analyze Tatum tonight")
        self.assertEqual(record["query"]["player_subject"], "Jayson Tatum")
        self.assertEqual(record["response"]["recommendation_count"], 1)
        self.assertEqual(record["top_recommendation"]["name"], "Jayson Tatum Over 28.5 Points")
        self.assertEqual(record["outcome"]["actual"], "hit")

    def test_candidate_summary_includes_settlement_metadata(self) -> None:
        summary = _candidate_summary(
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "LAL @ BOS",
                "market": "Points",
                "pick": "Over 28.5",
                "name": "Jayson Tatum",
                "line": 28.5,
                "actual": 31,
                "status_display": "Final",
                "is_final": True,
            }
        )

        self.assertEqual(summary["actual"], "31")
        self.assertEqual(summary["settlement"]["status"], "settled")
        self.assertEqual(summary["settlement"]["result"], "won")

    def test_top_live_opportunities_include_actual_and_settlement(self) -> None:
        opportunities = get_top_live_opportunities(
            [
                {
                    "is_live": True,
                    "sport": "NBA",
                    "sport_slug": "nba",
                    "market": "Points",
                    "name": "Jayson Tatum",
                    "selection": "Over 28.5",
                    "ev_current": 0.12,
                    "line": 28.5,
                    "actual": 19,
                    "status_display": "In Progress",
                }
            ],
            limit=1,
        )

        self.assertEqual(opportunities[0]["actual"], "19")
        self.assertEqual(opportunities[0]["settlement"]["status"], "live")


class CandidateGameDateTests(unittest.TestCase):
    """#93 follow-up. Before this fix, UniversalCandidate.from_raw folded
    every candidate's date tag down to payload["selected_date"]/["date"] --
    the date the OUTER overview build was run for, identical for every
    candidate from that build. A cross-date combined board needs each
    candidate's OWN game date to filter correctly.
    """

    def test_from_raw_uses_commence_time_over_shared_selected_date(self) -> None:
        # Two candidates from the same overview build (same selected_date /
        # context_label) but different games -- their real game dates must
        # differ. This is the assertion that fails against pre-fix code:
        # both used to resolve to the identical shared "2026-07-27".
        candidate_a = UniversalCandidate.from_raw(
            {
                "candidate_id": "a",
                "sport": "WNBA",
                "selected_date": "2026-07-27",
                "commence_time": "2026-07-27T23:00:00Z",
            }
        )
        candidate_b = UniversalCandidate.from_raw(
            {
                "candidate_id": "b",
                "sport": "WNBA",
                "selected_date": "2026-07-27",
                "commence_time": "2026-07-29T02:00:00Z",
            }
        )
        assert candidate_a is not None and candidate_b is not None
        self.assertNotEqual(candidate_a.provenance["selected_date"], candidate_b.provenance["selected_date"])
        self.assertEqual(candidate_a.provenance["selected_date"], "2026-07-27")
        # 2026-07-29T02:00:00Z is 2026-07-28 21:00 Central -- still the 28th.
        self.assertEqual(candidate_b.provenance["selected_date"], "2026-07-28")

    def test_from_raw_falls_back_to_selected_date_when_no_game_timestamp(self) -> None:
        candidate = UniversalCandidate.from_raw(
            {
                "candidate_id": "c",
                "sport": "MLB",
                "selected_date": "2026-07-27",
            }
        )
        assert candidate is not None
        self.assertEqual(candidate.provenance["selected_date"], "2026-07-27")

    def test_resolve_candidate_game_date_priority_order(self) -> None:
        # commence_time wins over start_time_utc/game_time_utc/game_date when
        # more than one is present.
        resolved = resolve_candidate_game_date(
            {
                "commence_time": "2026-07-27T18:00:00Z",
                "start_time_utc": "2026-07-28T18:00:00Z",
                "game_date": "2026-07-29",
            }
        )
        self.assertEqual(resolved, "2026-07-27")

    def test_resolve_candidate_game_date_accepts_bare_date_string(self) -> None:
        self.assertEqual(resolve_candidate_game_date({"game_date": "2026-07-27"}), "2026-07-27")

    def test_resolve_candidate_game_date_returns_fallback_when_nothing_resolves(self) -> None:
        self.assertEqual(resolve_candidate_game_date({}, fallback="2026-07-27"), "2026-07-27")
        self.assertIsNone(resolve_candidate_game_date({}, fallback=None))

    def test_resolve_candidate_game_date_ignores_unparseable_timestamp(self) -> None:
        self.assertEqual(
            resolve_candidate_game_date({"commence_time": "not-a-date"}, fallback="2026-07-27"),
            "2026-07-27",
        )

    def test_to_dict_keeps_the_producer_line_text_and_only_fills_an_empty_slot(self) -> None:
        # This defect has now landed twice at this exact spot. `odds` was
        # flattened from "+124" to 124.0 (fixed 2026-07-28, 1f47b2d6, "Fix
        # candidate field corruption"); `line` was flattened from "4.5" to 4.5
        # nine days later (1f6c27b9, 2026-08-06) because the field was added to
        # a loop that writes unconditionally, sitting twelve lines below the
        # comment explaining why that is wrong. Neither had a test HERE -- the
        # second was caught only by a distant MLB blueprint test.
        #
        # The rule: self.line is the join-normalised float and stays that way
        # on the dataclass and in sport_context. payload["line"] is the
        # producer's display text and is overwritten ONLY when it holds no
        # parseable number.
        base = {
            "sport": "mlb",
            "type": "prop",
            "selection": "Over 4.5",
            "market_key": "strikeouts",
            "entity_name": "Brandon Young",
            "event_id": "776",
        }

        kept = UniversalCandidate.from_raw({**base, "line": "4.5"})
        self.assertEqual(kept.to_dict()["line"], "4.5")
        self.assertEqual(kept.line, 4.5)

        # The case that makes this more than cosmetic: the intelligence board's
        # displayLine() does a bare String(line), so a JSON 2.0 renders as "2"
        # and the half-point precision the column exists for is gone.
        whole = UniversalCandidate.from_raw({**base, "line": "2.0"})
        self.assertEqual(whole.to_dict()["line"], "2.0")

        # A placeholder is not a display value -- fill it from market_line.
        placeholder = UniversalCandidate.from_raw({**base, "line": "-", "market_line": 7.5})
        self.assertEqual(placeholder.to_dict()["line"], 7.5)

        # Absent entirely: fill it from prop_line.
        absent = UniversalCandidate.from_raw({**base, "prop_line": 2.5})
        self.assertEqual(absent.to_dict()["line"], 2.5)


if __name__ == "__main__":
    unittest.main()