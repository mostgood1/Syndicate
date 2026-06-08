from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pipeline.intelligence_entrypoint import route_intelligence_request
from pipeline.intelligence_entrypoint import run_routed_intelligence_pipeline


class IntelligenceEntrypointTests(unittest.TestCase):
    def test_route_intelligence_request_attaches_classification(self) -> None:
        request = SimpleNamespace(get_json=lambda silent=True: {"question": "What are the best live bets right now?"}, form={})

        payload = route_intelligence_request(request)

        self.assertEqual(payload["mode"], "live")
        self.assertEqual(payload["query_type"], "live_analysis")

    def test_run_routed_intelligence_pipeline_uses_routed_payload(self) -> None:
        request = SimpleNamespace(get_json=lambda silent=True: {"question": "Compare Player A vs Player B"}, form={})

        with patch("pipeline.intelligence_entrypoint.run_intelligence_pipeline", return_value="ok") as mocked_pipeline:
            result = run_routed_intelligence_pipeline(request)

        self.assertEqual(result, "ok")
        mocked_pipeline.assert_called_once()
        routed_payload = mocked_pipeline.call_args.args[0]
        self.assertEqual(routed_payload["mode"], "comparison")
        self.assertEqual(routed_payload["query_type"], "comparison")


if __name__ == "__main__":
    unittest.main()