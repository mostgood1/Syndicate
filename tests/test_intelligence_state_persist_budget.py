"""The first populated board killed the background loop thread (2026-07-27).

27 real candidates made each snapshot's response ~4.6MB; _persist_locked
persists every snapshot's full response in ONE keyvalue payload (10.9MB for 7),
the store's #60 guard raised KeyValuePayloadTooLarge -- correctly and loudly --
and nothing caught it. The thread died at 01:04:42Z, the board froze on its
00:04:13Z snapshot, and the execution guard stayed held so the MLB sim
launcher deferred forever against a pipeline that no longer existed.

Two properties pinned here: a persist failure never propagates, and an
oversized payload is trimmed deterministically rather than dropped.
"""

from __future__ import annotations

import json
import unittest
from collections import OrderedDict
from unittest.mock import patch

import pipeline.intelligence_state as intelligence_state
from pipeline.intelligence_state import IntelligenceSnapshot
from pipeline.intelligence_state import IntelligenceStateService
from pipeline.intelligence_state import _budgeted_snapshots_payload
from syndicate.features.shared.refresh_state_store import KeyValuePayloadTooLarge


def _entry(key: str, response_bytes: int) -> dict:
    return {
        "key": key,
        "payload": {"date": "2026-07-26", "sport": "all"},
        "response": {"ok": True, "candidate_count": 27, "bulk": "x" * response_bytes},
        "computed_at": "2026-07-27T01:04:00Z",
        "source_fingerprint": "fp",
    }


class BudgetedSnapshotsPayloadTests(unittest.TestCase):
    def test_latest_is_kept_full_and_overflow_is_stripped_not_dropped(self) -> None:
        snapshots = {f"key{i}": _entry(f"key{i}", 3_000_000) for i in range(7)}
        trimmed = _budgeted_snapshots_payload(snapshots, "key3")

        self.assertEqual(set(trimmed), set(snapshots), "no entry may be dropped")
        self.assertIsInstance(trimmed["key3"]["response"], dict, "latest keeps its response")
        kept_full = [k for k, e in trimmed.items() if isinstance(e.get("response"), dict)]
        stripped = [k for k, e in trimmed.items() if e.get("response") is None]
        self.assertIn("key3", kept_full)
        self.assertTrue(stripped, "something must be stripped when over budget")
        # Stripped entries keep their metadata -- that is the difference
        # between "recompute after reboot" and "this snapshot never happened".
        for key in stripped:
            self.assertEqual(trimmed[key]["key"], key)
            self.assertEqual(trimmed[key]["computed_at"], "2026-07-27T01:04:00Z")
        # And the result genuinely fits.
        self.assertLess(
            len(json.dumps(trimmed, default=str)),
            8 * 1024 * 1024,
        )

    def test_small_payloads_pass_through_untouched(self) -> None:
        snapshots = {f"key{i}": _entry(f"key{i}", 1_000) for i in range(7)}
        trimmed = _budgeted_snapshots_payload(snapshots, "key0")
        for key in snapshots:
            self.assertIsInstance(trimmed[key]["response"], dict)

    def test_newest_entries_win_the_budget(self) -> None:
        # OrderedDict appends newest last; with room for ~2 full entries the
        # latest key and the newest other should keep responses.
        snapshots = OrderedDict((f"key{i}", _entry(f"key{i}", 2_500_000)) for i in range(5))
        trimmed = _budgeted_snapshots_payload(snapshots, "key1")
        kept_full = {k for k, e in trimmed.items() if isinstance(e.get("response"), dict)}
        self.assertIn("key1", kept_full)
        self.assertIn("key4", kept_full, "newest non-latest should be preferred")
        self.assertNotIn("key0", kept_full, "oldest should be stripped first")

    def test_a_latest_too_big_for_the_budget_strips_everything(self) -> None:
        snapshots = {"only": _entry("only", 10 * 1024 * 1024)}
        trimmed = _budgeted_snapshots_payload(snapshots, "only")
        self.assertIsNone(trimmed["only"]["response"])

    def test_deterministic(self) -> None:
        snapshots = OrderedDict((f"key{i}", _entry(f"key{i}", 2_500_000)) for i in range(6))
        first = _budgeted_snapshots_payload(dict(snapshots), "key2")
        second = _budgeted_snapshots_payload(dict(snapshots), "key2")
        self.assertEqual(
            {k for k, e in first.items() if e.get("response") is None},
            {k for k, e in second.items() if e.get("response") is None},
        )


class PersistNeverKillsTheCallerTests(unittest.TestCase):
    def _service_with_big_board(self) -> IntelligenceStateService:
        service = IntelligenceStateService()
        service._snapshots = OrderedDict()
        for i in range(7):
            key = f"key{i}"
            service._snapshots[key] = IntelligenceSnapshot(
                key=key,
                payload={"date": "2026-07-26", "sport": "all"},
                response={"ok": True, "candidate_count": 27, "bulk": "x" * 1_500_000},
                computed_at="2026-07-27T01:04:00Z",
                source_fingerprint="fp",
            )
        service._latest_key = "key6"
        return service

    def test_oversized_state_write_is_retried_trimmed_not_raised(self) -> None:
        service = self._service_with_big_board()
        writes: list[tuple[str, dict]] = []

        def fake_write(path, payload):
            serialized = json.dumps(payload, default=str)
            if len(serialized) > 8 * 1024 * 1024:
                raise KeyValuePayloadTooLarge(f"{len(serialized)} bytes")
            writes.append((str(path), payload))

        with patch.object(intelligence_state, "write_json_file", side_effect=fake_write):
            service._persist_locked()  # must not raise

        state_writes = [p for path, p in writes if "snapshots" in p]
        self.assertEqual(len(state_writes), 1, "the trimmed retry must succeed")
        trimmed = state_writes[0]["snapshots"]
        self.assertIsInstance(trimmed["key6"]["response"], dict, "latest survives")
        self.assertTrue(any(e.get("response") is None for e in trimmed.values()))

    def test_a_store_that_always_fails_cannot_kill_the_thread(self) -> None:
        # This is the exact production failure: the exception escaped
        # _background_loop, the thread died, and the execution guard leaked.
        service = self._service_with_big_board()
        with patch.object(intelligence_state, "write_json_file", side_effect=RuntimeError("store down")):
            service._persist_locked()  # must not raise

    def test_board_snapshot_write_failure_is_also_contained(self) -> None:
        service = self._service_with_big_board()
        calls = {"n": 0}

        def fail_after_state(path, payload):
            calls["n"] += 1
            if calls["n"] > 1:
                raise KeyValuePayloadTooLarge("board snapshot too big")

        with patch.object(intelligence_state, "write_json_file", side_effect=fail_after_state):
            service._persist_locked()  # must not raise



class GuardReleaseTests(unittest.TestCase):
    """#81. The execution guard must release even when the loop thread dies.

    Observed 2026-07-27T01:04Z: _persist_locked raised, the thread died, and
    the guard stayed held -- intelligence_pipeline_busy() read locked()
    forever and the MLB sim launcher deferred against a pipeline that no
    longer existed. The persist no longer raises, but the finally is the
    structural fix for the whole snapshot-install stretch.
    """

    def test_guard_releases_when_the_install_stretch_raises(self) -> None:
        import threading

        service = IntelligenceStateService()
        service._snapshots = OrderedDict()
        service._latest_key = None
        service._interval_seconds = 0.05
        payload = {"question": "top edges today", "sport": "all", "date": "2026-07-26"}
        service._pending_keys = OrderedDict({"k": payload})
        service._watched_payloads = OrderedDict()
        service._watched_board_dates = OrderedDict()

        with patch.object(service, "_sync_persisted_queue_locked"):
            with patch.object(intelligence_state, "_board_build_deferral_reason", return_value=None):
                with patch.object(service, "_compute_board_publication_response", return_value={"ok": True, "candidate_count": 1}):
                    with patch.object(intelligence_state, "write_latest_intelligence_state", side_effect=lambda state: dict(state)):
                        # Kill the thread INSIDE the post-compute install
                        # stretch -- exactly where the production death lived.
                        with patch.object(service, "_trim_ordered_dict", side_effect=RuntimeError("install stretch dies")):
                            thread = threading.Thread(target=service._background_loop, daemon=True)
                            thread.start()
                            thread.join(timeout=10.0)

        self.assertFalse(thread.is_alive(), "thread should have died from the injected error")
        self.assertFalse(
            service._execution_guard.locked(),
            "the guard must be released by the finally even though the thread died -- "
            "a held guard starves the MLB sim forever (#81's observed harm)",
        )

if __name__ == "__main__":
    unittest.main()
