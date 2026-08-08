"""#286 -- the empty-board write guard must see a board that was too big for keyvalue.

Root-caused live on refresh-worker 2026-08-08. `_empty_write_would_clobber_good_board`
consulted the persisted daily state through `read_json_file`, which on the keyvalue
backend reads the keyvalue store ONLY. A rich board serializes to ~27MB against an
8.4MB ceiling, so `_write_state_payload` diverts it to the artifact transport and the
keyvalue copy keeps whatever small payload it last held -- an empty one. The guard then
asked keyvalue "is there a good board for this date?", got the stale empty copy, and
failed open. Production signature: `STATE_PERSIST_BEGIN candidate_count=0` on 80 of 100
persists across 14:52Z-21:12Z with `STATE_WRITE_SKIPPED_EMPTY_OVER_GOOD` on zero of them.

These tests are deliberately in their own file rather than appended to
`tests/test_intelligence_state.py`: that file carries pre-existing unrelated failures and
is edited concurrently, and this guard is small enough to pin on its own.
"""

from __future__ import annotations

import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

from pipeline import intelligence_state


def _utc_iso(offset_seconds: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


class EmptyBoardGuardSeesArtifactOnlyBoardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = dict(intelligence_state._LAST_GOOD_BOARD_WRITES)
        intelligence_state._LAST_GOOD_BOARD_WRITES.clear()
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        intelligence_state._LAST_GOOD_BOARD_WRITES.clear()
        intelligence_state._LAST_GOOD_BOARD_WRITES.update(self._saved)

    @staticmethod
    def _no_history():
        """Pin the history tier off. Not patched in setUp on purpose -- the tests
        that exercise the tail read call it directly and need the real function."""
        return unittest.mock.patch.object(intelligence_state, "_last_board_write_from_history", return_value=None)

    def test_guard_protects_a_good_board_the_keyvalue_copy_cannot_see(self) -> None:
        """The regression itself: keyvalue says empty, the real board was written
        through the artifact transport, and the empty write must still be refused."""
        date = "2026-08-08"
        intelligence_state._record_good_board_write(date, 511, _utc_iso(-180))

        # The keyvalue copy is stale-and-empty, exactly as production had it.
        with unittest.mock.patch.object(
            intelligence_state,
            "read_json_file",
            return_value={"selected_date": date, "candidate_count": 0, "state_last_updated": _utc_iso()},
        ):
            self.assertTrue(
                intelligence_state._empty_write_would_clobber_good_board({"selected_date": date, "candidate_count": 0})
            )

    def test_guard_still_fails_open_once_the_good_board_is_past_the_window(self) -> None:
        """An empty board is legitimately correct at the end of a slate. Protection
        is bounded by age, so a stale board must not be frozen in place forever."""
        date = "2026-08-08"
        window = intelligence_state._empty_board_protection_window_seconds()
        self.assertGreater(window, 0, "test assumes the default protection window is enabled")
        intelligence_state._record_good_board_write(date, 511, _utc_iso(-(window + 120)))

        # The history tier is pinned rather than left live: this checkout has a
        # real reports/intelligence/intelligence_state_history_2026_08_08.jsonl,
        # and a test about the staleness rule must not depend on what is in it.
        with self._no_history(), unittest.mock.patch.object(intelligence_state, "read_json_file", return_value=None):
            self.assertFalse(
                intelligence_state._empty_write_would_clobber_good_board({"selected_date": date, "candidate_count": 0})
            )

    def test_guard_does_not_protect_a_different_date(self) -> None:
        intelligence_state._record_good_board_write("2026-08-08", 511, _utc_iso(-60))

        with self._no_history(), unittest.mock.patch.object(intelligence_state, "read_json_file", return_value=None):
            self.assertFalse(
                intelligence_state._empty_write_would_clobber_good_board(
                    {"selected_date": "2026-08-09", "candidate_count": 0}
                )
            )

    def test_history_tail_protects_after_a_restart_when_keyvalue_is_blind(self) -> None:
        """The restart case: no in-process record, keyvalue holds the stale empty
        copy, and only the history JSONL still knows a good board was written."""
        date = "2026-08-08"
        with unittest.mock.patch.object(
            intelligence_state,
            "_last_board_write_from_history",
            return_value=(_utc_iso(-240), 511),
        ):
            with unittest.mock.patch.object(
                intelligence_state,
                "read_json_file",
                return_value={"selected_date": date, "candidate_count": 0, "state_last_updated": _utc_iso()},
            ):
                self.assertTrue(
                    intelligence_state._empty_write_would_clobber_good_board(
                        {"selected_date": date, "candidate_count": 0}
                    )
                )

    def test_history_tail_reads_the_last_entry_from_a_real_file(self) -> None:
        """Exercises the byte-level tail read rather than mocking it away."""
        import json as _json
        import tempfile
        from pathlib import Path

        date = "2026-08-08"
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            history = Path(tmp) / f"intelligence_state_history_{date}.jsonl"
            written_at = _utc_iso(-90)
            history.write_text(
                "\n".join(
                    [
                        _json.dumps({"selected_date": date, "candidate_count": 7, "updated_at": _utc_iso(-600)}),
                        _json.dumps({"selected_date": date, "candidate_count": 511, "updated_at": written_at}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with unittest.mock.patch.object(
                intelligence_state,
                "_intelligence_state_daily_paths",
                return_value={"history": history},
            ):
                self.assertEqual(intelligence_state._last_board_write_from_history(date), (written_at, 511))

    def test_history_tail_does_not_resurrect_a_board_already_replaced_by_an_empty_one(self) -> None:
        """Reads the LAST entry, not the last non-empty one. If an empty write
        already landed, there is nothing left to protect and the guard must not
        pretend otherwise."""
        import json as _json
        import tempfile
        from pathlib import Path

        date = "2026-08-08"
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            history = Path(tmp) / f"intelligence_state_history_{date}.jsonl"
            history.write_text(
                "\n".join(
                    [
                        _json.dumps({"selected_date": date, "candidate_count": 511, "updated_at": _utc_iso(-120)}),
                        _json.dumps({"selected_date": date, "candidate_count": 0, "updated_at": _utc_iso(-30)}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with unittest.mock.patch.object(
                intelligence_state,
                "_intelligence_state_daily_paths",
                return_value={"history": history},
            ):
                written_at, count = intelligence_state._last_board_write_from_history(date)
                self.assertEqual(count, 0)

    def test_history_tail_survives_a_seek_landing_mid_record(self) -> None:
        """The tail seek routinely lands inside a line. A truncated leading
        record must be skipped, not crash the guard."""
        import json as _json
        import tempfile
        from pathlib import Path

        date = "2026-08-08"
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            history = Path(tmp) / f"intelligence_state_history_{date}.jsonl"
            filler = _json.dumps(
                {"selected_date": date, "candidate_count": 3, "updated_at": _utc_iso(-900), "pad": "x" * 4000}
            )
            written_at = _utc_iso(-45)
            lines = [filler] * 40 + [
                _json.dumps({"selected_date": date, "candidate_count": 222, "updated_at": written_at})
            ]
            history.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertGreater(history.stat().st_size, intelligence_state._HISTORY_TAIL_PROBE_BYTES)
            with unittest.mock.patch.object(
                intelligence_state,
                "_intelligence_state_daily_paths",
                return_value={"history": history},
            ):
                self.assertEqual(intelligence_state._last_board_write_from_history(date), (written_at, 222))

    def test_history_tail_returns_none_when_the_file_is_absent(self) -> None:
        from pathlib import Path

        with unittest.mock.patch.object(
            intelligence_state,
            "_intelligence_state_daily_paths",
            return_value={"history": Path("does-not-exist-2026-08-08.jsonl")},
        ):
            self.assertIsNone(intelligence_state._last_board_write_from_history("2026-08-08"))

    def test_keyvalue_fallback_still_works_when_there_is_no_in_process_record(self) -> None:
        """After a restart the in-process record is empty; the pre-existing
        keyvalue read must still protect a board small enough to live there."""
        date = "2026-08-08"
        # History pinned off too, so a pass here can only come from the keyvalue
        # tier -- otherwise this test would still be green with that tier broken.
        with self._no_history(), unittest.mock.patch.object(
            intelligence_state,
            "read_json_file",
            return_value={"selected_date": date, "candidate_count": 12, "state_last_updated": _utc_iso(-60)},
        ):
            self.assertTrue(
                intelligence_state._empty_write_would_clobber_good_board({"selected_date": date, "candidate_count": 0})
            )

    def test_a_zero_candidate_write_is_never_recorded_as_a_good_board(self) -> None:
        intelligence_state._record_good_board_write("2026-08-08", 0, _utc_iso())
        self.assertIsNone(intelligence_state._last_good_board_write("2026-08-08"))

    def test_record_is_bounded(self) -> None:
        for index in range(intelligence_state._LAST_GOOD_BOARD_WRITES_MAX + 5):
            intelligence_state._record_good_board_write(f"2026-08-{index + 1:02d}", 1, _utc_iso())
        self.assertLessEqual(
            len(intelligence_state._LAST_GOOD_BOARD_WRITES), intelligence_state._LAST_GOOD_BOARD_WRITES_MAX
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
