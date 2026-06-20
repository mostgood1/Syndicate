from __future__ import annotations

import unittest
from datetime import date

from syndicate.app import create_app
from syndicate.features.wnba.sources import build_module_links as build_wnba_module_links


class DailyUpdateSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        cls.client = app.test_client()

    def test_mlb_archive_smoke(self) -> None:
        response = self.client.get("/mlb/api/archive?date=2026-05-18")
        payload = response.get_json()
        resolved_date = str(payload.get("date") or "")
        resolved_season = resolved_date[:4]

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertEqual((payload.get("rank_cards") or [{}])[0].get("title"), resolved_date)
        self.assertEqual((payload.get("rank_cards") or [{}])[0].get("href"), f"/mlb/season/{resolved_season}?date={resolved_date}")
        self.assertTrue(payload.get("warning_panel"))

    def test_wnba_module_links_smoke(self) -> None:
        today_date = date.today().isoformat()
        links = build_wnba_module_links(today_date, "Cards")

        self.assertTrue(any(link.get("href") == f"/wnba/cards?date={today_date}" for link in links))
        self.assertTrue(any(link.get("href") == f"/wnba/live-lens?date={today_date}" for link in links))

    def test_home_exposes_live_lens_link(self) -> None:
        html = self.client.get("/").get_data(as_text=True)

        self.assertIn("Open Live Lens", html)
        self.assertIn("Live lens feed", html)
