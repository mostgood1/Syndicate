"""Board-state -> evaluation-ledger recording.

The fingerprint written by this path is a "this (date, fingerprint) is
handled" marker that the function's own guard uses to skip re-recording.
Stamping it after a cycle that recorded NOTHING would permanently suppress
retry for that fingerprint, so a transient empty board would become a
silent, self-concealing gap in the ledger -- and the ledger is what every
downstream evaluation number (reliability multipliers, dynamic thresholds,
policy promotion, CLV, stake credibility) is computed from.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from pipeline import intelligence_state


class BoardStateLedgerRecordingTests(unittest.TestCase):
    def setUp(self) -> None:
        enabled = patch.object(intelligence_state, "intelligence_ledger_recording_enabled", return_value=True)
        enabled.start()
        self.addCleanup(enabled.stop)
        self.stamped: list[tuple[str, str]] = []
        stamp = patch.object(
            intelligence_state,
            "_record_canonical_board_state_ledger_fingerprint",
            side_effect=lambda date, fp: self.stamped.append((date, fp)),
        )
        stamp.start()
        self.addCleanup(stamp.stop)
        last = patch.object(intelligence_state, "_canonical_board_state_last_recorded_fingerprint", return_value=None)
        last.start()
        self.addCleanup(last.stop)

    @staticmethod
    def _state(recommendations: list[dict] | None) -> dict:
        return {
            "selected_date": "2026-08-04",
            "source_fingerprint": "fp-abc123456789",
            "ranked_all": recommendations if recommendations is not None else [],
        }

    def test_empty_board_does_not_stamp_so_the_next_cycle_can_retry(self) -> None:
        with patch("syndicate.features.shared.intelligence_evaluation.build_intelligence_evaluation_bundle", return_value={}):
            intelligence_state.maybe_record_board_state_to_evaluation_ledger(self._state([]))
        self.assertEqual(self.stamped, [], "a zero-recommendation cycle must not mark the date handled")

    def test_non_empty_board_stamps_the_fingerprint(self) -> None:
        with patch("syndicate.features.shared.intelligence_evaluation.build_intelligence_evaluation_bundle", return_value={"ok": True}):
            intelligence_state.maybe_record_board_state_to_evaluation_ledger(self._state([{"selection": "Home ML"}]))
        self.assertEqual(len(self.stamped), 1)
        self.assertEqual(self.stamped[0][0], "2026-08-04")

    def test_recording_stays_disabled_behind_the_flag(self) -> None:
        with patch.object(intelligence_state, "intelligence_ledger_recording_enabled", return_value=False):
            result = intelligence_state.maybe_record_board_state_to_evaluation_ledger(self._state([{"selection": "x"}]))
        self.assertIsNone(result)
        self.assertEqual(self.stamped, [])

    def test_already_recorded_fingerprint_is_not_re_recorded(self) -> None:
        with patch.object(intelligence_state, "_canonical_board_state_last_recorded_fingerprint", return_value="fp-abc123456789"):
            result = intelligence_state.maybe_record_board_state_to_evaluation_ledger(self._state([{"selection": "x"}]))
        self.assertIsNone(result)
        self.assertEqual(self.stamped, [])

    def test_a_raising_bundle_build_never_stamps(self) -> None:
        # Pre-existing behaviour, asserted so the empty-guard change above
        # cannot regress it: a failed write must stay retryable too.
        with patch(
            "syndicate.features.shared.intelligence_evaluation.build_intelligence_evaluation_bundle",
            side_effect=RuntimeError("ledger unavailable"),
        ):
            result = intelligence_state.maybe_record_board_state_to_evaluation_ledger(self._state([{"selection": "x"}]))
        self.assertIsNone(result)
        self.assertEqual(self.stamped, [])


if __name__ == "__main__":
    unittest.main()
