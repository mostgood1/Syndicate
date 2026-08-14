"""The pregame relaunch cooldown must be per-sport, not global.

MEASURED CAUSE (refresh-worker, 2026-08-14). `_pregame_relaunch_blocked` read
one marker keyed by date alone, so a launch for ANY sport started the 1800s
clock for EVERY sport -- and it skipped the whole tick before
`_apply_pregame_sport_cadence` (already per-sport, already correct) could run.
Launch gaps came out at 30.0/30.5/39.5/30.5 min with sports rotating across
launches, so MLB rode every 2nd-4th one and its quote capture ran every
121.6 min. Verified independently in the shard: bursts at 13:09:08 / 15:10:44 /
16:20:38, each ~20-40s after its launch.

THE COOLDOWN VALUE IS UNCHANGED. Only the coupling is. So these tests pin BOTH
directions -- that sports decouple, AND that a sport still cools against its
own last launch, which is the retry-storm protection the gate exists for.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import syndicate.features.shared.live_refresh_loop as loop


COOLDOWN = 1800
DATE = "2026-08-14"
NOW = 1_000_000.0


class PregameCooldownPerSportTests(unittest.TestCase):
    def _blocked(self, marker: dict, sports, *, now=NOW, date=DATE) -> bool:
        with patch.object(loop, "_read_last_pregame_launch", return_value=marker):
            with patch.object(loop, "_pregame_relaunch_cooldown_seconds", return_value=COOLDOWN):
                return loop._pregame_relaunch_blocked(now_epoch=now, date_str=date, sports=sports)

    # -- the defect this fixes -------------------------------------------

    def test_one_sports_launch_no_longer_silences_another(self) -> None:
        """NFL launched 60s ago; MLB last launched 2h ago. MLB must be due."""
        marker = {"date": DATE, "epoch": NOW - 60, "sports": {"nfl": NOW - 60, "mlb": NOW - 7200}}
        self.assertFalse(self._blocked(marker, ["mlb"]))
        self.assertFalse(
            self._blocked(marker, ["mlb", "nfl"]),
            "a tick with one due sport must proceed",
        )

    def test_the_measured_production_shape(self) -> None:
        """MLB last launched at the 15:10 slot; at 16:20 (4200s later) it is due
        even though soccer/wnba/nfl launched in between."""
        marker = {
            "date": DATE,
            "epoch": NOW - 600,                       # some other sport, 10 min ago
            "sports": {"mlb": NOW - 4200, "soccer": NOW - 600, "wnba": NOW - 1800},
        }
        self.assertFalse(self._blocked(marker, ["mlb"]))

    # -- what must NOT regress: the retry-storm guard ----------------------

    def test_a_sport_still_cools_against_its_own_launch(self) -> None:
        marker = {"date": DATE, "epoch": NOW - 60, "sports": {"mlb": NOW - 60}}
        self.assertTrue(
            self._blocked(marker, ["mlb"]),
            "MLB launched 60s ago against an 1800s cooldown and must be blocked",
        )

    def test_all_sports_cooling_still_blocks_the_tick(self) -> None:
        marker = {"date": DATE, "epoch": NOW - 100, "sports": {"mlb": NOW - 100, "nfl": NOW - 200}}
        self.assertTrue(self._blocked(marker, ["mlb", "nfl"]))

    def test_boundary_is_inclusive_of_due(self) -> None:
        marker = {"date": DATE, "epoch": NOW - COOLDOWN, "sports": {"mlb": NOW - COOLDOWN}}
        self.assertFalse(self._blocked(marker, ["mlb"]), "exactly at the cooldown is due")

    # -- fail-open and rollback safety ------------------------------------

    def test_unknown_sport_inherits_the_legacy_epoch_no_stampede(self) -> None:
        """First tick after deploy: no per-sport entries exist yet.

        Every sport must inherit the old global epoch, so behaviour is
        identical to before rather than releasing all eight sports at once onto
        a memory-constrained worker.
        """
        marker = {"date": DATE, "epoch": NOW - 60}  # legacy shape, no "sports"
        self.assertTrue(self._blocked(marker, ["mlb", "nfl", "wnba", "soccer"]))
        stale = {"date": DATE, "epoch": NOW - 7200}
        self.assertFalse(self._blocked(stale, ["mlb", "nfl"]))

    def test_no_sport_list_falls_back_to_global_behaviour(self) -> None:
        marker = {"date": DATE, "epoch": NOW - 60, "sports": {"mlb": NOW - 7200}}
        self.assertTrue(self._blocked(marker, None), "must not invent a per-sport answer")

    def test_different_date_never_blocks(self) -> None:
        marker = {"date": "2026-08-13", "epoch": NOW - 60, "sports": {"mlb": NOW - 60}}
        self.assertFalse(self._blocked(marker, ["mlb"]))

    def test_zero_cooldown_disables(self) -> None:
        marker = {"date": DATE, "epoch": NOW, "sports": {"mlb": NOW}}
        with patch.object(loop, "_read_last_pregame_launch", return_value=marker):
            with patch.object(loop, "_pregame_relaunch_cooldown_seconds", return_value=0):
                self.assertFalse(loop._pregame_relaunch_blocked(now_epoch=NOW, date_str=DATE, sports=["mlb"]))

    def test_corrupt_marker_values_fail_open(self) -> None:
        marker = {"date": DATE, "epoch": "not-a-number", "sports": {"mlb": "nope"}}
        self.assertFalse(self._blocked(marker, ["mlb"]), "unreadable marker must not block")

    # -- the writer -------------------------------------------------------

    def test_record_stamps_only_the_launched_sports(self) -> None:
        written: dict = {}
        existing = {"date": DATE, "epoch": NOW - 3600, "sports": {"wnba": NOW - 3600}}
        with patch.object(loop, "_read_last_pregame_launch", return_value=existing):
            with patch.object(loop, "write_json_file", side_effect=lambda p, d: written.update(d)):
                loop._record_pregame_launch(NOW, DATE, ["mlb", "soccer"])
        self.assertEqual(written["sports"]["mlb"], NOW)
        self.assertEqual(written["sports"]["soccer"], NOW)
        self.assertEqual(
            written["sports"]["wnba"], NOW - 3600,
            "a sport NOT in this launch must keep its own window armed",
        )
        self.assertEqual(written["epoch"], NOW, "legacy key kept so a rollback still reads it")

    def test_record_drops_carried_sports_on_a_new_date(self) -> None:
        written: dict = {}
        existing = {"date": "2026-08-13", "epoch": NOW - 90000, "sports": {"mlb": NOW - 90000}}
        with patch.object(loop, "_read_last_pregame_launch", return_value=existing):
            with patch.object(loop, "write_json_file", side_effect=lambda p, d: written.update(d)):
                loop._record_pregame_launch(NOW, DATE, ["nfl"])
        self.assertEqual(written["sports"], {"nfl": NOW})


if __name__ == "__main__":
    unittest.main()
