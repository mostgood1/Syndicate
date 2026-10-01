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
        patcher = patch("syndicate.features.nba.live_prop_audit._processed_roots", return_value=[self.root])
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


class NbaLivePropAuditRootTests(unittest.TestCase):
    """The audit resolves files across every NBA processed root, like the rest
    of NBA. Measured 2026-10-01 on the local fleet: the data disk's root held no
    live-lens projections, the second root held 2026-06-05..06-13, and the audit
    -- which read only the first root -- answered empty for all of them."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.first = Path(tmp.name) / "disk" / "data" / "processed"
        self.second = Path(tmp.name) / "checkout" / "data" / "processed"
        self.first.mkdir(parents=True)
        self.second.mkdir(parents=True)
        roots = [self.first.parent.parent, self.second.parent.parent]
        patcher = patch("syndicate.features.nba.live_prop_audit._nba_artifact_roots", return_value=roots)
        patcher.start()
        self.addCleanup(patcher.stop)
        primary = patch("syndicate.features.nba.live_prop_audit.artifact_processed_root", return_value=self.first)
        primary.start()
        self.addCleanup(primary.stop)

    def test_a_file_only_in_the_second_root_is_found(self) -> None:
        from syndicate.features.nba import live_prop_audit as audit

        (self.second / "live_lens_projections_2026-06-13.jsonl").write_text("", encoding="utf-8")
        self.assertEqual(audit._artifact_path("live_lens_projections_2026-06-13.jsonl"), self.second / "live_lens_projections_2026-06-13.jsonl")

    def test_the_first_root_wins_when_both_have_the_file(self) -> None:
        from syndicate.features.nba import live_prop_audit as audit

        for root in (self.first, self.second):
            (root / "recon_props_2026-06-13.csv").write_text("x", encoding="utf-8")
        self.assertEqual(audit._artifact_path("recon_props_2026-06-13.csv"), self.first / "recon_props_2026-06-13.csv")

    def test_projections_without_actuals_say_so_instead_of_a_bare_empty(self) -> None:
        """The fleet's real shape: Finals projection rows present, recon_props
        header-only, so nothing can be graded. The payload must name the gap."""
        from syndicate.features.nba import live_prop_audit as audit

        row = '{"game_id": "1", "player": "Jordan Clarkson", "name_key": "Jordan Clarkson", "stat": "pts", "proj": 5.49, "sim_mu": 5.49, "market": "player_prop"}'
        (self.second / "live_lens_projections_2026-06-13.jsonl").write_text(row + "\n", encoding="utf-8")
        (self.second / "recon_props_2026-06-13.csv").write_text("game_id,player_name,pts\n", encoding="utf-8")
        payload = audit.build_live_prop_audit_payload("date=2026-06-13")
        self.assertEqual(payload["status"], "empty")
        self.assertEqual(payload["projection_rows"], 1)
        self.assertEqual(payload["debug"]["days"][0]["unsettled_reason"], "no_actuals")
        self.assertIn("no actual box-score results", payload["message"])
        self.assertEqual(payload["latest_available_date"], "2026-06-13")

    def test_a_new_source_file_refreshes_the_cached_payload(self) -> None:
        """The cache was keyed on the query string alone, so a day's answer was
        frozen for the life of the web process. A landed file must show up."""
        from syndicate.features.nba import live_prop_audit as audit

        before = audit.build_live_prop_audit_payload("date=2026-06-13")
        self.assertEqual(before["projection_rows"] if "projection_rows" in before else 0, 0)
        (self.second / "live_lens_projections_2026-06-13.jsonl").write_text(
            '{"game_id": "1", "player": "J", "name_key": "J", "stat": "pts", "proj": 5.0, "market": "player_prop"}\n',
            encoding="utf-8",
        )
        after = audit.build_live_prop_audit_payload("date=2026-06-13")
        self.assertEqual(after["projection_rows"], 1)

    def test_the_default_window_moves_with_the_date(self) -> None:
        from syndicate.features.nba import live_prop_audit as audit

        class _Clock:
            now_value = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)

            @classmethod
            def now(cls, tz=None):
                return cls.now_value

        with patch.object(audit, "datetime", _Clock), patch(
            "syndicate.features.shared.live_lens_local.datetime", _Clock
        ):
            first = audit.build_live_prop_audit_payload("")["meta"]["end"]
            _Clock.now_value = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
            second = audit.build_live_prop_audit_payload("")["meta"]["end"]
        self.assertEqual((first, second), ("2026-09-30", "2026-10-01"))

    def _write_finals_day(self, recon_rows: list[str]) -> dict:
        """One projection row shaped like the real 2026 Finals file (game_id "1")
        and a recon_props file built from ESPN box scores (event-id game_id)."""
        from syndicate.features.nba import live_prop_audit as audit

        proj = [
            '{"game_id": "1", "player": "Pac\\u00f4me Dadiet", "name_key": "Pac\\u00f4me Dadiet", "team_tri": "NYK", "stat": "pts", "proj": 4.0, "sim_mu": 4.0, "market": "player_prop"}',
            '{"game_id": "1", "player": "Victor Wembanyama", "name_key": "Victor Wembanyama", "team_tri": "SAS", "stat": "pts", "proj": 27.0, "sim_mu": 27.0, "market": "player_prop"}',
        ]
        (self.second / "live_lens_projections_2026-06-13.jsonl").write_text("\n".join(proj) + "\n", encoding="utf-8")
        header = "game_id,player_id,player_name,team_abbr,pts,reb,ast,threes,stl,blk,tov,pr,pa,ra,pra"
        (self.second / "recon_props_2026-06-13.csv").write_text("\n".join([header, *recon_rows]) + "\n", encoding="utf-8")
        audit.build_live_prop_audit_payload.cache_clear()
        return audit.build_live_prop_audit_payload("date=2026-06-13")

    def test_an_unusable_projection_game_id_falls_back_to_team_and_player(self) -> None:
        payload = self._write_finals_day([
            "401859967,1,Victor Wembanyama,SAS,31,12,4,2,1,5,3,43,35,16,47",
        ])
        self.assertEqual(payload["overall"]["n"], 1)
        self.assertEqual(payload["history"], None)  # include_rows not requested

    def test_accented_names_join_to_unaccented_box_scores(self) -> None:
        payload = self._write_finals_day([
            "401859967,1,Victor Wembanyama,SAS,31,12,4,2,1,5,3,43,35,16,47",
            "401859967,2,Pacome Dadiet,NYK,6,1,0,2,0,0,0,7,6,1,7",
        ])
        self.assertEqual(payload["overall"]["n"], 2)

    def test_a_team_under_two_game_ids_on_one_date_gets_no_fallback(self) -> None:
        payload = self._write_finals_day([
            "401859967,1,Victor Wembanyama,SAS,31,12,4,2,1,5,3,43,35,16,47",
            "401859999,1,Victor Wembanyama,SAS,10,1,1,0,0,0,0,11,11,2,12",
        ])
        self.assertEqual(payload["overall"]["n"], 0)
        self.assertEqual(payload["debug"]["days"][0]["unsettled_reason"], "no_matching_actuals")

    def test_latest_available_date_spans_every_root(self) -> None:
        from syndicate.features.nba import live_prop_audit as audit

        (self.first / "live_lens_projections_2026-06-05.jsonl").write_text("", encoding="utf-8")
        (self.second / "live_lens_projections_2026-06-13.jsonl").write_text("", encoding="utf-8")
        self.assertEqual(audit._latest_available_date(), "2026-06-13")


if __name__ == "__main__":
    unittest.main()
