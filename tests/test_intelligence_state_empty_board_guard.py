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

        with unittest.mock.patch.object(intelligence_state, "read_json_file", return_value=None):
            self.assertFalse(
                intelligence_state._empty_write_would_clobber_good_board({"selected_date": date, "candidate_count": 0})
            )

    def test_guard_does_not_protect_a_different_date(self) -> None:
        intelligence_state._record_good_board_write("2026-08-08", 511, _utc_iso(-60))

        with unittest.mock.patch.object(intelligence_state, "read_json_file", return_value=None):
            self.assertFalse(
                intelligence_state._empty_write_would_clobber_good_board(
                    {"selected_date": "2026-08-09", "candidate_count": 0}
                )
            )

    def test_keyvalue_fallback_still_works_when_there_is_no_in_process_record(self) -> None:
        """After a restart the in-process record is empty; the pre-existing
        keyvalue read must still protect a board small enough to live there."""
        date = "2026-08-08"
        with unittest.mock.patch.object(
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
