"""query_state_cache.json must fit the keyvalue cap (lane `query-state-cache-oversize`).

Measured on the fleet 2026-10-09: every write of STATE_PATH that day was
refused at 11.7-13.5MB, because each date-snapshot's response embedded the full
Layer 2 shortlist (40.8 of 42.4MB raw). The refusal fell back to the raw-byte
trim, which cannot keep a 42MB snapshot, so the cache was persisted with NO
response at all (546 of 546 fallbacks `kept_full=0`).

Pinned here: the persisted copy omits `layer2_shortlist` (a marker remains),
the in-memory snapshot and the board_snapshot write keep it, the first write
fits without the trim, and a reload restores every snapshot.
"""

from __future__ import annotations

import base64
import json
import random
import unittest
from collections import OrderedDict
from unittest.mock import patch

import pipeline.intelligence_state as intelligence_state
from pipeline.intelligence_state import IntelligenceSnapshot
from pipeline.intelligence_state import IntelligenceStateService
from pipeline.intelligence_state import _query_state_persist_response
from syndicate.features.shared.refresh_state_store import KeyValuePayloadTooLarge

_CAP = 8 * 1024 * 1024
_MARKER = intelligence_state._QUERY_STATE_LAYER2_OMITTED_KEY


def _incompressible(n_bytes: int, seed: int) -> str:
    # zlib collapses "x" * n; a seeded PRNG keeps the shortlist big AFTER
    # compression, the way 2026-10-09's real 5.36MB-per-snapshot was.
    return base64.b64encode(random.Random(seed).randbytes(n_bytes)).decode("ascii")


def _response(date: str, seed: int) -> dict:
    return {
        "ok": True,
        "selected_date": date,
        "candidate_count": 3,
        "recommendations": [{"id": f"{date}-{i}"} for i in range(3)],
        "layer2_shortlist": {
            "selected_date": date,
            "rows": [{"blob": _incompressible(1_000_000, seed * 10 + i)} for i in range(3)],
            "cards": [{"id": "c1"}, {"id": "c2"}],
        },
    }


def _service() -> IntelligenceStateService:
    service = IntelligenceStateService()
    service._snapshots = OrderedDict()
    for seed, date in enumerate(("2026-10-08", "2026-10-09", "2026-10-10")):
        key = f"key-{date}"
        service._snapshots[key] = IntelligenceSnapshot(
            key=key,
            payload={"question": "top edges today", "date": date, "sport": "all"},
            response=_response(date, seed),
            computed_at="2026-10-09T16:25:22Z",
            source_fingerprint="fp",
        )
    service._latest_key = "key-2026-10-09"
    return service


def _persist(service: IntelligenceStateService) -> tuple[list[dict], list[tuple[str, dict]]]:
    """Run `_persist_locked` against a store with the real 8MB guard.

    Returns (every STATE_PATH attempt incl. refused ones, every accepted write).
    """
    state_attempts: list[dict] = []
    accepted: list[tuple[str, dict]] = []

    def fake_write(path, payload):
        if str(path) == str(intelligence_state.STATE_PATH):
            state_attempts.append(payload)
        if len(json.dumps(payload, default=str)) > _CAP:
            raise KeyValuePayloadTooLarge("over cap")
        accepted.append((str(path), payload))

    with patch.object(intelligence_state, "write_json_file", side_effect=fake_write):
        service._persist_locked()
    return state_attempts, accepted


class PersistedSnapshotsFitTests(unittest.TestCase):
    def test_first_write_fits_and_keeps_every_response(self) -> None:
        service = _service()
        state_attempts, accepted = _persist(service)

        self.assertEqual(len(state_attempts), 1, "no refusal, so no trimmed retry")
        state_writes = [p for path, p in accepted if path == str(intelligence_state.STATE_PATH)]
        self.assertEqual(len(state_writes), 1)
        snapshots = intelligence_state._decompress_oversized_values(state_writes[0])["snapshots"]
        self.assertEqual(len(snapshots), 3)
        for key, entry in snapshots.items():
            response = entry["response"]
            self.assertIsInstance(response, dict, f"{key} must keep its response")
            self.assertEqual(len(response["recommendations"]), 3)
            shortlist = response["layer2_shortlist"]
            self.assertTrue(shortlist[_MARKER])
            self.assertEqual(shortlist["rows_count"], 3)
            self.assertEqual(shortlist["cards_count"], 2)
            self.assertEqual(shortlist["selected_date"], entry["payload"]["date"])
            self.assertNotIn("rows", shortlist, "absent rows must read None, not an empty board")

    def test_in_memory_and_board_snapshot_keep_the_shortlist(self) -> None:
        service = _service()
        _, accepted = _persist(service)
        for snapshot in service._snapshots.values():
            self.assertEqual(len(snapshot.response["layer2_shortlist"]["rows"]), 3)
        board_writes = [p for path, p in accepted if path == str(intelligence_state.BOARD_SNAPSHOT_PATH)]
        # The board snapshot is out of this lane's scope and must be unchanged:
        # it still carries the latest snapshot's full shortlist.
        self.assertTrue(board_writes, "the latest snapshot's board_snapshot write must still happen")
        for payload in board_writes:
            expanded = intelligence_state.expand_persisted_state(payload)
            shortlist = expanded["response"]["layer2_shortlist"]
            self.assertNotIn(_MARKER, shortlist)
            self.assertEqual(len(shortlist["rows"]), 3)

    def test_reachability_without_the_omission_the_write_is_refused(self) -> None:
        # off != on: with the helper made a no-op, the same board is refused
        # and falls back to the trim -- the 2026-10-09 production behaviour.
        service = _service()
        with patch.object(intelligence_state, "_query_state_persist_response", side_effect=lambda r: r):
            state_attempts, accepted = _persist(service)
        self.assertEqual(len(state_attempts), 2, "first write refused, trimmed retry follows")
        state_writes = [p for path, p in accepted if path == str(intelligence_state.STATE_PATH)]
        snapshots = intelligence_state._decompress_oversized_values(state_writes[0])["snapshots"]
        self.assertTrue(any(e["response"] is None for e in snapshots.values()), "the trim strips responses")

    def test_reload_restores_every_snapshot(self) -> None:
        service = _service()
        _, accepted = _persist(service)
        stored = [p for path, p in accepted if path == str(intelligence_state.STATE_PATH)][0]

        fresh = IntelligenceStateService()
        with patch.object(intelligence_state, "read_json_file", return_value=stored):
            fresh._load_persisted_state_locked(force=True)
        self.assertEqual(set(fresh._snapshots), set(service._snapshots))
        self.assertEqual(fresh._latest_key, "key-2026-10-09")
        for snapshot in fresh._snapshots.values():
            self.assertTrue(snapshot.response["layer2_shortlist"][_MARKER])


class PersistResponseHelperTests(unittest.TestCase):
    def test_passthrough_cases(self) -> None:
        self.assertIsNone(_query_state_persist_response(None))
        plain = {"ok": True, "candidate_count": 0}
        self.assertIs(_query_state_persist_response(plain), plain)
        no_dict = {"layer2_shortlist": None}
        self.assertIs(_query_state_persist_response(no_dict), no_dict)

    def test_idempotent(self) -> None:
        once = _query_state_persist_response(_response("2026-10-09", 1))
        self.assertIs(_query_state_persist_response(once), once)

    def test_does_not_mutate_the_input(self) -> None:
        response = _response("2026-10-09", 2)
        _query_state_persist_response(response)
        self.assertEqual(len(response["layer2_shortlist"]["rows"]), 3)


if __name__ == "__main__":
    unittest.main()
