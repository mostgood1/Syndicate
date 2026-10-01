"""`/nba/api/live-player-props-audit` defaults its window instead of 502ing.

Measured 2026-10-01 on the local production fleet: the bare call was the one
502 in a 290-route sweep (`{"error": "failed to load live player props audit"}`).
Both payload builders returned None for any request without `date` or a
`since`/`until` pair, and the route turned None into a 502. WNBA's twin
answered the same bare call 200 because it parses its window with the shared
`_parse_window` (trailing 14 days ending yesterday). NBA now does the same.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from syndicate.app import create_app


class NbaLivePropAuditWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patcher = patch("syndicate.features.nba.live_prop_audit._artifact_root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _get(self, query: str = ""):
        return self.client.get(f"/nba/api/live-player-props-audit{query}")

    def test_bare_request_is_200_over_the_trailing_14_settled_days(self) -> None:
        response = self._get()
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:300])
        meta = response.get_json()["meta"]
        yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
        self.assertEqual(meta["days"], 14)
        self.assertEqual(meta["end"], yesterday.isoformat())
        self.assertEqual(meta["start"], (yesterday - timedelta(days=13)).isoformat())

    def test_a_single_date_is_still_one_day(self) -> None:
        payload = self._get("?date=2026-06-13").get_json()
        self.assertEqual((payload["meta"]["start"], payload["meta"]["end"], payload["meta"]["days"]), ("2026-06-13", "2026-06-13", 1))

    def test_since_until_and_start_end_and_days_are_honoured(self) -> None:
        self.assertEqual(self._get("?since=2026-06-01&until=2026-06-03").get_json()["meta"]["days"], 3)
        self.assertEqual(self._get("?start=2026-06-01&end=2026-06-05").get_json()["meta"]["days"], 5)
        self.assertEqual(self._get("?days=3").get_json()["meta"]["days"], 3)

    def test_an_unparsable_window_is_a_400_not_a_502(self) -> None:
        response = self._get("?since=not-a-date&until=2026-06-03")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid date window")

    def test_an_empty_window_names_the_latest_date_that_has_data(self) -> None:
        for day in ("2026-06-10", "2026-06-13"):
            (self.root / f"live_lens_projections_{day}.jsonl").write_text("", encoding="utf-8")
        payload = self._get("?date=2026-09-30").get_json()
        self.assertEqual(payload["status"], "empty")
        self.assertEqual(payload["latest_available_date"], "2026-06-13")

    def test_no_data_anywhere_says_so_rather_than_inventing_a_date(self) -> None:
        payload = self._get().get_json()
        self.assertIsNone(payload["latest_available_date"])


if __name__ == "__main__":
    unittest.main()
