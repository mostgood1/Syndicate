"""`chunk_lines_on_disk` is counted by streaming the chunk, never by loading it.

The old count, `read_text().splitlines()`, held the whole day's ledger chunk
plus a list of its lines: +512 / +561 MB of anon for ~2 s per board cycle on
2026-09-21, and refresh-worker was oomKilled inside that window at 04:08:47Z
09-22 (deploys.md, lane refresh-worker-oom-0922). These tests run the real
recording function against a real chunk file and forbid `Path.read_text`, so
a regression back to whole-file reads fails loudly instead of reading as a
correct count.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import intelligence_state
from syndicate.features.shared import intelligence_evaluation


class BoardStateLedgerLineCountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        ledger = self.tmp / "evaluation_ledger.jsonl"
        for target, kwargs in (
            (intelligence_state, {"attribute": "intelligence_ledger_recording_enabled", "return_value": True}),
            (intelligence_state, {"attribute": "_canonical_board_state_last_recorded_fingerprint", "return_value": None}),
            (intelligence_state, {"attribute": "_record_canonical_board_state_ledger_fingerprint", "return_value": None}),
            (intelligence_evaluation, {"attribute": "DEFAULT_LEDGER_PATH", "new": ledger}),
        ):
            p = patch.object(target, **kwargs)
            p.start()
            self.addCleanup(p.stop)
        self.chunk = intelligence_evaluation._ledger_chunk_path(ledger, "2026-09-21")
        self.chunk.parent.mkdir(parents=True, exist_ok=True)

    def _record(self) -> str:
        state = {
            "selected_date": "2026-09-21",
            "source_fingerprint": "fp-0123456789ab",
            "ranked_all": [{"selection": "Home ML"}],
        }
        out = io.StringIO()
        with patch(
            "syndicate.features.shared.intelligence_evaluation.build_intelligence_evaluation_bundle",
            return_value={"ok": True},
        ), patch.object(Path, "read_text", side_effect=AssertionError("chunk must be streamed, not read whole")), \
                contextlib.redirect_stdout(out):
            intelligence_state.maybe_record_board_state_to_evaluation_ledger(state)
        return out.getvalue()

    def test_counts_non_blank_lines_without_reading_the_whole_file(self) -> None:
        self.chunk.write_bytes(b'{"a": 1}\n\n{"b": 2}\r\n   \n{"c": "\xc3\xa9"}')
        printed = self._record()
        self.assertIn("chunk_lines_on_disk=3", printed)

    def test_missing_chunk_reads_zero(self) -> None:
        printed = self._record()
        self.assertIn("chunk_lines_on_disk=0", printed)


if __name__ == "__main__":
    unittest.main()
