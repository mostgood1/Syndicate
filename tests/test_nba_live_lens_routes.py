from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app


class NbaLiveLensRouteTests(unittest.TestCase):
    def test_nba_live_lens_snapshot_readers_return_empty_contract_on_failure(self) -> None:
        from syndicate.features.nba import live_lens as nba_live_lens

        with patch.object(nba_live_lens, "_load_live_lens_snapshot", side_effect=FileNotFoundError("missing snapshot")), patch(
            "builtins.print"
        ) as mocked_print:
            page_context = nba_live_lens.read_latest_live_lens_page_context("2026-06-05", season=2026, profile="retuned")
            api_payload = nba_live_lens.read_latest_live_lens_api_payload("2026-06-05")

        expected = {
            "games": [],
            "cards": [],
            "date": "2026-06-05",
            "status": "empty",
        }

        self.assertEqual(page_context, expected)
        self.assertEqual(api_payload, expected)
        self.assertGreaterEqual(mocked_print.call_count, 2)
        self.assertTrue(
            any(
                call.args
                and call.args[0] == "WNBA SNAPSHOT ERROR:"
                and len(call.args) > 1
                and isinstance(call.args[1], FileNotFoundError)
                for call in mocked_print.call_args_list
            )
        )

    def test_nba_live_lens_routes_read_snapshot_payloads(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        page_context = {
            "route_path": "/nba/live-lens",
            "rank_cards": [{"title": "BOS @ NYK"}],
            "source_path": "/opt/render/project/data/live/nba_live_lens.json",
        }
        api_payload = {
            "ok": True,
            "route_path": "/nba/live-lens",
            "rank_cards": [{"title": "BOS @ NYK"}],
        }

        with patch("syndicate.blueprints.nba.read_latest_live_lens_page_context", return_value=dict(page_context)) as mocked_page, patch(
            "syndicate.blueprints.nba.render_template",
            return_value="PAGE",
        ) as mocked_render, patch(
            "syndicate.blueprints.nba.read_latest_live_lens_api_payload",
            return_value=dict(api_payload),
        ) as mocked_api:
            page_response = client.get("/nba/live-lens?date=2026-06-05")
            api_response = client.get("/nba/api/live-lens?date=2026-06-05")

        self.assertEqual(page_response.status_code, 200)
        self.assertEqual(page_response.get_data(as_text=True), "PAGE")
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.get_json(), api_payload)
        mocked_page.assert_called_once_with("2026-06-05")
        mocked_render.assert_called_once()
        mocked_api.assert_called_once_with("2026-06-05")

    def test_nba_live_lens_season_route_uses_snapshot_reader(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        page_context = {
            "route_path": "/nba/season/2025/live-lens",
            "rank_cards": [{"title": "BOS @ NYK"}],
            "source_path": "/opt/render/project/data/live/nba_live_lens.json",
            "hidden_fields": [{"name": "profile", "value": "retuned"}],
        }

        with patch("syndicate.blueprints.nba.read_latest_live_lens_page_context", return_value=dict(page_context)) as mocked_page, patch(
            "syndicate.blueprints.nba.render_template",
            return_value="SEASON_PAGE",
        ):
            response = client.get("/nba/season/2025/live-lens?date=2025-06-05&profile=retuned")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "SEASON_PAGE")
        mocked_page.assert_called_once_with("2025-06-05", season=2025, profile="retuned")

    def test_nba_live_player_lines_pbp_routes_read_snapshot_payloads(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        player_payload = {"ok": True, "games": [{"event_id": "evt-1", "rows": [{"player": "Jayson Tatum"}]}]}
        lines_payload = {"ok": True, "games": [{"event_id": "evt-1", "found": True, "total": 219.5}]}
        pbp_payload = {"ok": True, "games": [{"event_id": "evt-1", "pbp_recent": {"points_total": 12}}]}

        with patch(
            "syndicate.blueprints.nba.read_latest_live_player_lens_payload",
            return_value=dict(player_payload),
        ) as mocked_player, patch(
            "syndicate.blueprints.nba.read_latest_live_lines_payload",
            return_value=dict(lines_payload),
        ) as mocked_lines, patch(
            "syndicate.blueprints.nba.read_latest_live_pbp_stats_payload",
            return_value=dict(pbp_payload),
        ) as mocked_pbp:
            player_response = client.get("/nba/api/live_player_lens?date=2026-06-05&event_ids=evt-1")
            lines_response = client.get("/nba/api/live_lines?date=2026-06-05&event_ids=evt-1&include_period_totals=1")
            pbp_response = client.get("/nba/api/live_pbp_stats?date=2026-06-05&event_ids=evt-1")

        self.assertEqual(player_response.status_code, 200)
        self.assertEqual(player_response.get_json(), player_payload)
        self.assertEqual(lines_response.status_code, 200)
        self.assertEqual(lines_response.get_json(), lines_payload)
        self.assertEqual(pbp_response.status_code, 200)
        self.assertEqual(pbp_response.get_json(), pbp_payload)
        mocked_player.assert_called_once_with("2026-06-05", ["evt-1"], ttl=20, allow_stored_date_fallback=False)
        mocked_lines.assert_called_once_with("2026-06-05", ["evt-1"], ttl=20, include_period_totals=True, allow_stored_date_fallback=False)
        mocked_pbp.assert_called_once_with("2026-06-05", ["evt-1"], ttl=20, allow_stored_date_fallback=False)


if __name__ == "__main__":
    unittest.main()
