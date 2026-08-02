from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared import refresh_state_store
from syndicate.features.nba import cards as nba_cards
from syndicate.features.nba import sources as nba_sources


class _FakeKeyValueClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = str(value)
        return True

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0


class NbaCardsKeyvalueBackendTests(unittest.TestCase):
    def tearDown(self) -> None:
        refresh_state_store.reset_state_store_caches()
        nba_cards._local_live_snapshot_payload.cache_clear()
        nba_cards._local_live_state_payload.cache_clear()

    def _keyvalue_env(self, data_root: Path) -> dict[str, str]:
        return {
            "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
            "SYNDICATE_REFRESH_STATE_URL": "redis://example",
            "SYNDICATE_DATA_ROOT": str(data_root),
        }

    def test_live_snapshot_payload_reads_cross_service_keyvalue_write(self) -> None:
        # Regression: live_lines/live_player_lens/live_player_boxscore/
        # live_pbp_stats snapshots (build_live_lines_payload and friends, via
        # _local_live_snapshot_payload_cached) were read via plain
        # path.read_text() -- invisible cross-service under the keyvalue
        # backend, same root cause already fixed for WNBA's copy of this
        # function. A write that only ever reaches the keyvalue store (as
        # the real live-odds-worker writer now does) must still be visible
        # to a process that never touched the local file itself.
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ, self._keyvalue_env(Path(tmp_dir)), clear=False
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            processed_root = Path(tmp_dir) / "data" / "processed"
            with patch.object(nba_sources, "artifact_processed_root", return_value=processed_root):
                date_str = "2026-07-13"
                path = nba_sources.live_snapshot_path(f"live_player_lens_{date_str}.jsonl")
                payload = {
                    "ok": True,
                    "date": date_str,
                    "games": [{"event_id": "401585", "rows": [{"player": "A", "line_live": 22.5}]}],
                }
                import json as _json

                refresh_state_store.write_text_file(path, _json.dumps({"payload": payload}) + "\n")

                nba_cards._local_live_snapshot_payload.cache_clear()
                result = nba_cards._local_live_snapshot_payload("live_player_lens", date_str)
                nba_cards._local_live_snapshot_payload.cache_clear()

        self.assertIsNotNone(result)
        self.assertEqual(result["games"][0]["event_id"], "401585")
        self.assertEqual(result["games"][0]["rows"], payload["games"][0]["rows"])

    def test_live_snapshot_payload_cache_invalidates_on_new_keyvalue_write(self) -> None:
        # The old cache key was path.stat() mtime/size, which under the
        # keyvalue backend either raises (no local file) or never changes,
        # collapsing every call onto the same cache entry forever regardless
        # of fresh writes. The content-hash signature must invalidate when
        # the underlying keyvalue text changes.
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ, self._keyvalue_env(Path(tmp_dir)), clear=False
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            processed_root = Path(tmp_dir) / "data" / "processed"
            with patch.object(nba_sources, "artifact_processed_root", return_value=processed_root):
                date_str = "2026-07-13"
                path = nba_sources.live_snapshot_path(f"live_lines_{date_str}.jsonl")
                import json as _json

                first_payload = {"ok": True, "date": date_str, "games": [{"event_id": "evt-1", "total": 219.5}]}
                refresh_state_store.write_text_file(path, _json.dumps({"payload": first_payload}) + "\n")
                nba_cards._local_live_snapshot_payload.cache_clear()
                first_result = nba_cards._local_live_snapshot_payload("live_lines", date_str)

                second_payload = {"ok": True, "date": date_str, "games": [{"event_id": "evt-1", "total": 224.5}]}
                refresh_state_store.write_text_file(path, _json.dumps({"payload": second_payload}) + "\n")
                second_result = nba_cards._local_live_snapshot_payload("live_lines", date_str)
                nba_cards._local_live_snapshot_payload.cache_clear()

        self.assertEqual(first_result["games"][0]["total"], 219.5)
        self.assertEqual(second_result["games"][0]["total"], 224.5)

    def test_local_live_state_payload_reads_from_keyvalue(self) -> None:
        # Regression: live_state.jsonl (live game status/score) is written
        # cross-service through the keyvalue store, same reasoning as the
        # snapshot payload tests above.
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ, self._keyvalue_env(Path(tmp_dir)), clear=False
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            processed_root = Path(tmp_dir) / "data" / "processed"
            with patch.object(nba_sources, "artifact_processed_root", return_value=processed_root):
                date_str = "2026-07-13"
                path = nba_sources.live_snapshot_path(f"live_state_{date_str}.jsonl")
                import json as _json

                payload = {"ok": True, "games": [{"event_id": "401585", "away": "BOS", "home": "NYK", "status": "Live", "in_progress": True}]}
                refresh_state_store.write_text_file(path, _json.dumps({"payload": payload}) + "\n")

                nba_cards._local_live_state_payload.cache_clear()
                result = nba_cards._local_live_state_payload(date_str)
                nba_cards._local_live_state_payload.cache_clear()

        self.assertEqual(result, payload)


if __name__ == "__main__":
    unittest.main()
