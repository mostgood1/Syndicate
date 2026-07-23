from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared import refresh_state_store
from syndicate.features.wnba import cards as wnba_cards


class _FakeKeyValueClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str) -> bool:
        self.store[key] = str(value)
        return True

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0


class WnbaCardsKeyvalueBackendTests(unittest.TestCase):
    def tearDown(self) -> None:
        refresh_state_store.reset_state_store_caches()

    def _keyvalue_env(self, data_root: Path) -> dict[str, str]:
        return {
            "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
            "SYNDICATE_REFRESH_STATE_URL": "redis://example",
            "SYNDICATE_DATA_ROOT": str(data_root),
        }

    def test_artifact_bundle_prefers_keyvalue_game_cards_over_local_disk(self) -> None:
        # Regression: game_cards.csv is written cross-service through the
        # keyvalue store (the live-lens loop on live-odds-worker and the web
        # service each have their own separate local disk), so
        # _artifact_bundle must read the same way instead of trusting
        # whichever local candidate root this particular service happens to
        # have on disk.
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ, self._keyvalue_env(Path(tmp_dir)), clear=False
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            date_str = "2026-07-13"
            canonical_path = wnba_cards._game_cards_keyvalue_path(date_str)
            csv_text = (
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-07-13,0401,Atlanta Dream,Los Angeles Sparks,2026-07-13T23:08:15Z,-770,450,-10.5,10.5,197.5,oddsapi_consensus,ATL,LAS\n"
            )
            refresh_state_store.write_text_file(canonical_path, csv_text)

            bundle = wnba_cards._artifact_bundle(date_str)

        self.assertEqual(len(bundle["rows"]), 1)
        self.assertEqual(bundle["rows"][0].get("home_tri"), "ATL")
        self.assertEqual(bundle["paths"]["cards"], canonical_path)

    def test_local_live_state_payload_reads_from_keyvalue(self) -> None:
        # Regression: live_state.jsonl (live game status/score) is written
        # cross-service through the keyvalue store, same reasoning as
        # game_cards.csv above.
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ, self._keyvalue_env(Path(tmp_dir)), clear=False
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            date_str = "2026-07-13"
            canonical_path = wnba_cards._live_state_keyvalue_path(date_str)
            payload = {"ok": True, "games": [{"event_id": "401857064", "away": "LAS", "home": "ATL", "status": "Live", "in_progress": True}]}
            refresh_state_store.write_json_file(canonical_path, {"payload": payload})

            result = wnba_cards._local_live_state_payload(date_str)

        self.assertEqual(result, payload)

    def test_live_snapshot_artifact_round_trips_through_keyvalue(self) -> None:
        # Regression: live_player_lens/live_player_boxscore/live_lines/
        # live_pbp_stats snapshots (build_live_player_lens_payload and
        # friends) were written via plain path.write_text() and read via
        # plain path.read_text() -- invisible cross-service under the
        # keyvalue backend, the same root cause already fixed for
        # game_cards.csv/live_state.jsonl above. Confirmed live 2026-07-22
        # as the reason WNBA live player props stayed sparse/empty: the web
        # service could never see the snapshot live-odds-worker computed.
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ, self._keyvalue_env(Path(tmp_dir)), clear=False
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            date_str = "2026-07-13"
            path = wnba_cards._live_snapshot_artifact_path("live_player_lens", date_str)
            payload = {"games": [{"event_id": "401857064", "players": [{"name": "A'ja Wilson", "market": "points", "line": 22.5}]}]}

            written = wnba_cards._write_jsonl_snapshot_payload(path, payload)
            self.assertTrue(written)
            self.assertTrue(fake_client.store, "expected the live-snapshot write to reach the keyvalue store")

            result = wnba_cards._read_jsonl_snapshot_payload(path)

        # _read_jsonl_snapshot_payload normalizes each game's status fields
        # (adding default status/in_progress/final/etc.) -- that's expected,
        # unrelated behavior; this only checks the round trip preserved the
        # actual snapshot content through the keyvalue store.
        self.assertEqual(result["games"][0]["event_id"], "401857064")
        self.assertEqual(result["games"][0]["players"], payload["games"][0]["players"])


if __name__ == "__main__":
    unittest.main()
