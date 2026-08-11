"""`#275`: parse the ledger chunk index ONCE per settlement pass, not per record.

WHY THIS EXISTS. `_update_evaluation_ledger_record` reads AND fully re-serialises
the chunk index for every settled record. Production index measured 2026-08-11:
**10.63 MB, growing ~3 MB/day**. This module's own diagnostic puts the cost at
**27.4 MB RSS and 0.616 s per settled record**, so a ~150-record night is ~3.2 GB
of IO and 150 repeated 27 MB allocations on a 4 GB worker.

That is `#256`'s failure: **110 OOM kills over eleven hours**, boot-settle-die-
repeat. `#256` stopped the loop from repeating. It did not remove the cost, and
the cost is why `EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN` is still
`false` in production -- i.e. why the feedback loop is open.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from syndicate.features.shared import intelligence_evaluation as E


class LedgerIndexSessionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.ledger = Path(self._tmp.name) / "evaluation_ledger.jsonl"
        E._write_chunk_index_to_disk(
            self.ledger,
            {f"rec{i}": {"chunk": "c1", "path": "c1.jsonl"} for i in range(200)},
        )
        self.reads = 0
        self.writes = 0
        self._orig_read = E._read_chunk_index_from_disk
        self._orig_write = E._write_chunk_index_to_disk

        def counted_read(path=None):
            self.reads += 1
            return self._orig_read(path)

        def counted_write(path, index):
            self.writes += 1
            return self._orig_write(path, index)

        E._read_chunk_index_from_disk = counted_read
        E._write_chunk_index_to_disk = counted_write

    def tearDown(self):
        E._read_chunk_index_from_disk = self._orig_read
        E._write_chunk_index_to_disk = self._orig_write
        E._LEDGER_INDEX_SESSION.update(
            {"active": False, "key": None, "index": None, "dirty": False}
        )
        self._tmp.cleanup()

    def _simulate_settles(self, count):
        for i in range(count):
            index = E._load_chunk_index(self.ledger)
            index[f"new{i}"] = {"chunk": "c1", "path": "c1.jsonl"}
            E._write_chunk_index(self.ledger, index)

    def test_without_a_session_every_record_pays_full_io(self):
        # Pins the CURRENT production cost, so the fix below has a baseline that
        # fails loudly if someone reverts it.
        self._simulate_settles(10)
        self.assertEqual(self.reads, 10)
        self.assertEqual(self.writes, 10)

    def test_a_session_collapses_it_to_one_read_and_one_write(self):
        with E.ledger_index_session(self.ledger):
            self._simulate_settles(10)
        self.assertEqual(self.reads, 1)
        self.assertEqual(self.writes, 1)

    def test_every_mutation_survives_the_session(self):
        # The session hands back the SAME dict rather than a copy; if that ever
        # becomes a copy, mutations vanish silently and settled records are lost.
        with E.ledger_index_session(self.ledger):
            self._simulate_settles(10)
        final = self._orig_read(self.ledger)
        for i in range(10):
            self.assertIn(f"new{i}", final)
        self.assertIn("rec0", final, "pre-existing entries must survive too")

    def test_a_read_only_session_writes_nothing(self):
        # A dry run must not touch the index.
        with E.ledger_index_session(self.ledger):
            E._load_chunk_index(self.ledger)
        self.assertEqual(self.writes, 0)

    def test_nesting_does_not_flush_early(self):
        with E.ledger_index_session(self.ledger):
            self._simulate_settles(2)
            with E.ledger_index_session(self.ledger):
                self._simulate_settles(2)
            self.assertEqual(self.writes, 0, "inner session must not flush")
        self.assertEqual(self.writes, 1)

    def test_the_index_is_flushed_even_when_the_batch_raises(self):
        # Chunk FILES are already mutated by the time an exception lands; an
        # index that does not describe them is worse than one written mid-run.
        with self.assertRaises(RuntimeError):
            with E.ledger_index_session(self.ledger):
                self._simulate_settles(3)
                raise RuntimeError("boom")
        self.assertEqual(self.writes, 1)
        final = self._orig_read(self.ledger)
        self.assertIn("new2", final)

    def test_a_different_ledger_path_does_not_use_the_session(self):
        other = Path(self._tmp.name) / "other_ledger.jsonl"
        with E.ledger_index_session(self.ledger):
            E._load_chunk_index(other)
        # 1 for the session's own load, 1 for the unrelated path.
        self.assertEqual(self.reads, 2)

    def test_settle_ledger_for_date_is_wrapped(self):
        from syndicate.features.shared import evaluation_settlement as S

        self.assertTrue(
            hasattr(S.settle_ledger_for_date, "__wrapped__"),
            "settle_ledger_for_date must run inside a ledger index session",
        )


if __name__ == "__main__":
    unittest.main()
