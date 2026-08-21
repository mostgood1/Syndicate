import unittest
from unittest.mock import patch
from syndicate.features.shared.board_enrichment import attach_live_projections_for_sport

class GateTests(unittest.TestCase):
    def _run(self, sport, snapshot):
        with patch("syndicate.features.shared.refresh_state_store.read_json_file",
                   return_value=snapshot):
            return attach_live_projections_for_sport([], sport=sport, selected_date="2026-08-20")

    def test_wnba_is_now_supported(self):
        out = self._run("wnba", {"games": [{"liveProps": [{"playerName": "X"}]}]})
        self.assertTrue(out.get("supported"))

    def test_an_unlisted_sport_still_fails_closed_by_name(self):
        out = self._run("nfl", {"games": []})
        self.assertFalse(out.get("supported"))
        self.assertIn("no live re-sim wired", out.get("reason", ""))

    def test_a_snapshot_with_no_liveProps_is_NAMED_not_a_silent_zero(self):
        out = self._run("wnba", {"games": [{"liveProps": []}, {}]})
        self.assertTrue(out.get("supported"))
        self.assertIn("producer not wired", out.get("reason", ""))
        self.assertEqual(out.get("rows_live_projected"), 0)

    def test_an_absent_snapshot_keeps_its_own_reason(self):
        out = self._run("wnba", None)
        self.assertIn("no published live-lens snapshot", out.get("reason", ""))

if __name__ == "__main__":
    unittest.main()
