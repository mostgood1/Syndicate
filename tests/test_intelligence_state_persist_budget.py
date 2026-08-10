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

import base64
import json
import random
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


def _incompressible(n_bytes: int, seed: int) -> str:
    """Deterministic, effectively incompressible filler.

    #322 changed what "oversized" means. These tests pin the property that an
    oversized payload is TRIMMED rather than dropped, and the fixture used to
    be `"x" * 1_500_000` -- which zlib collapses roughly a thousandfold, so
    once compression landed the payload sailed under the ceiling, the trim
    never fired, and the test failed asserting on a trim that correctly had not
    happened. Filling with base64 of a seeded PRNG keeps the payload genuinely
    over the ceiling AFTER compression, so the guard is still exercised for
    real rather than being deleted or asserted away.
    """
    return base64.b64encode(random.Random(seed).randbytes(n_bytes)).decode("ascii")


class PersistNeverKillsTheCallerTests(unittest.TestCase):
    def _service_with_big_board(self) -> IntelligenceStateService:
        service = IntelligenceStateService()
        service._snapshots = OrderedDict()
        for i in range(7):
            key = f"key{i}"
            service._snapshots[key] = IntelligenceSnapshot(
                key=key,
                payload={"date": "2026-07-26", "sport": "all"},
                response={"ok": True, "candidate_count": 27, "bulk": _incompressible(1_500_000, i)},
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
        # #322: the write is compressed, so inspect it the way a reader does.
        trimmed = intelligence_state._decompress_oversized_values(state_writes[0])["snapshots"]
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

class QueryStateCacheCompressionTests(unittest.TestCase):
    """#322. `query_state_cache.json` was the LAST write still refused every
    cycle after `#317` fixed board_snapshot.

    Measured on the refresh-worker 2026-08-10T01:25:26Z:
    `snapshots=33,017,421` against an 8,388,608 ceiling, with a single snapshot
    (`399c2dc4...`) holding 33,017,351 of it. Because it was refused every
    cycle, `_budgeted_snapshots_payload` was running constantly -- and every
    entry that trim strips is a key that must be RECOMPUTED after a reboot. So
    this was not a cosmetic rejection; it was a standing cost.

    The trim is kept. Compression is the first line, the trim the second:
    compression buys ~17x, not infinity.
    """

    _CAP = 8_388_608

    @staticmethod
    def _realistic_entry(key: str, candidates: int) -> dict:
        # NOT `"x" * n`. zlib collapses a repeated character ~1000x, which would
        # make "it fits now" pass for a reason production will never enjoy.
        # These are candidate-shaped records with a shared key vocabulary and
        # varying values -- the thing that actually measured ~17.7x on the real
        # 2026-08-09 board.
        return {
            "key": key,
            "payload": {"date": "2026-08-09", "sport": "all"},
            "response": {
                "ok": True,
                "candidate_count": candidates,
                "recommendations": [
                    {
                        "candidate_id": f"{key}-{i}",
                        "sport": ["mlb", "nba", "nhl", "nfl"][i % 4],
                        "edge": 0.05 + (i % 97) / 1000,
                        "features": {f"f_{n}": (n * i) % 89 / 7 for n in range(120)},
                        "simulation": {"runs": 20000, "dist": [(n * i) % 53 for n in range(100)]},
                    }
                    for i in range(candidates)
                ],
            },
            "computed_at": "2026-08-10T02:27:00Z",
            "source_fingerprint": "fp",
        }

    def _payload(self, snapshot_count: int = 6, candidates: int = 500) -> dict:
        # Shaped exactly as _persist_locked builds it. 6x500 is ~10.6MB raw --
        # comfortably over the 8,388,608 ceiling, and small next to the 33MB
        # production was actually refusing. These synthetic candidates only
        # reach ~5.6x compression where the real 2026-08-09 board measured
        # 17.7x, so the fixture UNDERSTATES the headroom rather than flattering
        # it, which is the direction a fixture should err.
        return {
            "latest_key": "key0",
            "updated_at": "2026-08-10T02:27:48Z",
            "watched_payloads": {"k": {"question": "top edges today", "sport": "all"}},
            "pending_keys": {"k2": {"date": "2026-08-09"}},
            "watched_board_dates": {"2026-08-09": "2026-08-10T02:27:00Z"},
            "snapshots": {
                f"key{i}": self._realistic_entry(f"key{i}", candidates) for i in range(snapshot_count)
            },
        }

    def test_the_uncompressed_payload_really_does_breach_the_cap(self) -> None:
        # The premise. If this stops holding, everything below measures nothing.
        self.assertGreater(len(json.dumps(self._payload(), default=str)), self._CAP)

    def test_compressed_payload_fits(self) -> None:
        packed = intelligence_state._compress_oversized_values(self._payload())
        self.assertLess(len(json.dumps(packed, default=str)), self._CAP)

    def test_round_trip_is_lossless(self) -> None:
        original = self._payload()
        packed = intelligence_state._compress_oversized_values(original)
        with patch.object(intelligence_state, "read_json_file", return_value=packed):
            restored = intelligence_state._read_query_state_payload()
        self.assertEqual(restored, original)

    def test_queue_sync_never_inflates_the_snapshots_blob(self) -> None:
        # The whole point of include_snapshots=False: _sync_persisted_queue_locked
        # reads three small dicts and nothing else, and `snapshots` is 33MB.
        packed = intelligence_state._compress_oversized_values(self._payload())
        with patch.object(intelligence_state, "read_json_file", return_value=packed):
            queue_only = intelligence_state._read_query_state_payload(include_snapshots=False)
        self.assertNotIn("snapshots", queue_only)
        self.assertEqual(queue_only["pending_keys"], {"k2": {"date": "2026-08-09"}})
        self.assertEqual(queue_only["latest_key"], "key0")

    def test_queue_fields_are_never_compressed(self) -> None:
        # They are small, and _sync_persisted_queue_locked must be able to read
        # them with no decode step at all.
        packed = intelligence_state._compress_oversized_values(self._payload())
        self.assertEqual(packed["pending_keys"], {"k2": {"date": "2026-08-09"}})
        self.assertEqual(packed["latest_key"], "key0")
        self.assertIn(intelligence_state._COMPRESSED_VALUE_KEY, packed["snapshots"])

    def test_compression_fires_before_the_trim_not_instead_of_it(self) -> None:
        # A payload that fits once compressed must NOT be trimmed -- every
        # trimmed entry is a key recomputed after a reboot.
        service = IntelligenceStateService()
        service._snapshots = OrderedDict(
            (f"key{i}", IntelligenceSnapshot(
                key=f"key{i}",
                payload={"date": "2026-08-09"},
                response={"ok": True, "candidate_count": 150, "bulk": "x" * 3_000_000},
                computed_at="2026-08-10T02:27:00Z",
                source_fingerprint="fp",
            )) for i in range(6)
        )
        service._latest_key = "key5"
        service._watched_payloads = OrderedDict()
        service._pending_keys = OrderedDict()
        service._watched_board_dates = OrderedDict()

        written: list[dict] = []

        def _store(path, payload):
            # A real ceiling, so the test exercises the actual guard.
            if len(json.dumps(payload, default=str)) > self._CAP:
                raise KeyValuePayloadTooLarge("too big")
            written.append(payload)

        with patch.object(intelligence_state, "write_json_file", side_effect=_store):
            with patch.object(intelligence_state, "_write_state_payload"):
                service._persist_locked()

        state_writes = [p for p in written if "snapshots" in p]
        self.assertTrue(state_writes, "the state write must have succeeded")
        packed = state_writes[0]
        self.assertIn(intelligence_state._COMPRESSED_VALUE_KEY, packed["snapshots"])
        restored = intelligence_state._decompress_oversized_values(packed)
        self.assertEqual(len(restored["snapshots"]), 6, "nothing should have been trimmed")
        self.assertTrue(
            all(isinstance(e.get("response"), dict) for e in restored["snapshots"].values()),
            "every response must survive full -- a stripped one is a recompute after reboot",
        )

    def test_unknown_codec_is_refused_rather_than_half_understood(self) -> None:
        poisoned = {"snapshots": {intelligence_state._COMPRESSED_VALUE_KEY: "zstd-v9", "data": "x"}}
        with patch.object(intelligence_state, "read_json_file", return_value=poisoned):
            self.assertIsNone(intelligence_state._read_query_state_payload())

    def test_legacy_uncompressed_state_still_reads(self) -> None:
        legacy = self._payload(snapshot_count=1, candidates=1)
        with patch.object(intelligence_state, "read_json_file", return_value=legacy):
            self.assertEqual(intelligence_state._read_query_state_payload(), legacy)


class AliasedBySportMustNotCollapseTheCandidateCountTests(unittest.TestCase):
    """#337. `#317`'s member-aliasing silently reintroduced the 2026-07-21
    "stuck at 10" bug at a different scale.

    `_intelligence_state_candidate_count` prefers `by_sport`'s total because it
    is built before any per-request cap. Aliasing replaces those lists with
    marker DICTS, the old `isinstance(items, list)` sum scored them zero, and
    the function dropped through to `top_opportunities` -- returning the
    request-capped display count as the true pool.

    Measured on production 2026-08-10:
        21:03:42  CANDIDATE_POOL_READY count=203
        21:06:38  STATE_PERSIST_BEGIN candidate_count=150   <- _default_candidate_cap()

    Intermittent, which is why it survived: `_compact_member_lists` keeps the
    verbatim list when any element is not byte-identical to a `recommendations`
    member, so a 187 pool aliased on some cycles and not others.
    """

    def _state(self, pool: int, cap: int) -> dict:
        recs = [{"candidate_id": f"c{i}", "sport": ["mlb", "wnba"][i % 2], "blob": "x" * 80} for i in range(pool)]
        by_sport: dict[str, list] = {}
        for item in recs:
            by_sport.setdefault(item["sport"], []).append(item)
        return {"recommendations": recs, "top_opportunities": recs[:cap], "by_sport": by_sport}

    def test_the_production_case_203_reported_as_150(self) -> None:
        state = self._state(203, 150)
        compact = intelligence_state._compact_state_for_persist(dict(state))
        self.assertEqual(intelligence_state._intelligence_state_candidate_count(state), 203)
        self.assertEqual(
            intelligence_state._intelligence_state_candidate_count(compact), 203,
            "a compacted payload must still report the TRUE pool, not the cap",
        )

    def test_the_alias_is_actually_present_in_the_fixture(self) -> None:
        # Otherwise this suite would pass by measuring nothing -- the same
        # inert-fixture trap #317 hit.
        compact = intelligence_state._compact_state_for_persist(dict(self._state(203, 150)))
        marker_values = [v for v in compact["by_sport"].values()
                         if isinstance(v, dict) and v.get(intelligence_state._MEMBER_ALIAS_KEY)]
        self.assertTrue(marker_values, "fixture must actually alias by_sport or this proves nothing")

    def test_expansion_agrees_with_the_compacted_count(self) -> None:
        compact = intelligence_state._compact_state_for_persist(dict(self._state(203, 150)))
        expanded = intelligence_state._expand_persisted_state(compact)
        self.assertEqual(
            intelligence_state._intelligence_state_candidate_count(compact),
            intelligence_state._intelligence_state_candidate_count(expanded),
        )

    def test_unaliased_and_legacy_shapes_are_unchanged(self) -> None:
        self.assertEqual(intelligence_state._intelligence_state_candidate_count(
            {"by_sport": {"mlb": [{"a": 1}] * 7}}), 7)
        self.assertEqual(intelligence_state._intelligence_state_candidate_count(
            {"top_opportunities": [{"a": 1}] * 12}), 12)
        self.assertEqual(intelligence_state._intelligence_state_candidate_count({}), 0)

    def test_a_malformed_marker_does_not_inflate_the_count(self) -> None:
        # Unknown must not become a bigger number than the evidence supports.
        self.assertEqual(intelligence_state._intelligence_state_candidate_count(
            {"by_sport": {"mlb": {intelligence_state._MEMBER_ALIAS_KEY: "recommendations", "__indices__": "nope"}},
             "top_opportunities": [{"a": 1}] * 5}), 5)
if __name__ == "__main__":
    unittest.main()
