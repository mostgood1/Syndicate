from __future__ import annotations

import unittest

from pipeline.formatter import format_intelligence_query_error
from pipeline.formatter import format_intelligence_query_response
from pipeline.intelligence_models import IntelligenceResult


class FormatterTests(unittest.TestCase):
    def test_format_intelligence_query_response_serializes_typed_result(self) -> None:
        result = IntelligenceResult.from_raw(
            {
                "headline": "Top board",
                "recommendations": [{"name": "Play 1"}],
                "supporting_evidence": {"title": "Evidence"},
            },
            pipeline_request={"question": "What are the best live bets?"},
        )

        payload = format_intelligence_query_response(question="What are the best live bets?", result=result)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["query"], "What are the best live bets?")
        self.assertEqual(payload["response"]["headline"], "Top board")
        self.assertEqual(payload["response"]["recommendations"][0]["name"], "Play 1")

    def test_format_intelligence_query_error_normalizes_message(self) -> None:
        payload = format_intelligence_query_error(error="  question is required  ")

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "question is required")


if __name__ == "__main__":
    unittest.main()