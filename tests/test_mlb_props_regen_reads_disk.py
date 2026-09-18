"""The MLB props-regen check must see top props where they are WRITTEN -- on disk.

WHY (lane `mlb-sim-retrigger-churn`, 2026-09-18). `_mlb_props_now_available_needs_regen`
read `daily_top_props_<date>.json` with `refresh_state_store.read_json_file`. On
refresh-worker the state backend is keyvalue and this path is not excluded from it,
so the read went to REDIS -- while the vendored MLB app writes the file to DISK, and
every other top-props reader reads disk. The check therefore never saw top props and
re-simmed the whole slate every time its cooldown expired.

Measured 2026-09-18: `MLB_PROPS_REGEN_DUE` six times 06:05-13:01Z, all pregame,
19-37 min per run, while web served that day's top props from disk with 12 real
candidates.

Each test here blinds the state store for the top-props path only (that is what
production looked like) and puts the truth on disk. Restoring the store-only read
turns `test_top_props_on_disk_are_seen` red.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import live_refresh_loop as lrl

DATE = "2026-09-18"


def _top_props(candidates: int) -> dict:
    return {"groups": {"pitcher": {"summary": {"candidateCount": candidates, "displayedCount": candidates}}}}


class PropsRegenReadsDiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.top_props_path = root / "daily_top_props_2026_09_18.json"
        self.summary_path = root / "daily_summary_2026_09_18.json"
        self.summary_path.write_text("{}", encoding="utf-8")  # the daily sim ran

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *, store_copy=None, odds=True):
        real_read = lrl.read_json_file

        def blinded_store(path):
            # Production: the store has no copy of top props, because nothing writes one there.
            if "daily_top_props" in str(path):
                return store_copy
            return real_read(path)

        with patch("syndicate.features.mlb.sources.daily_top_props_path", return_value=self.top_props_path), \
             patch.object(lrl, "read_json_file", side_effect=blinded_store), \
             patch.object(lrl, "_mlb_daily_summary_path", return_value=self.summary_path), \
             patch.object(lrl, "_mlb_oddsapi_props_snapshot_has_entries", return_value=odds), \
             patch("builtins.print") as printed:
            due = lrl._mlb_props_now_available_needs_regen(now_epoch=10_000.0, date_str=DATE)
        return due, [str(c.args[0]) for c in printed.call_args_list if c.args]

    def test_top_props_on_disk_are_seen(self):
        # THE REGRESSION GUARD: real candidates on disk, nothing in the store.
        self.top_props_path.write_text(json.dumps(_top_props(12)), encoding="utf-8")
        due, lines = self._run()
        self.assertFalse(due, "top props exist; re-simming the slate for them is the loop this fixes")
        self.assertTrue(any("reason=top_props_present candidates=12" in l for l in lines), lines)
        self.assertFalse(any("MLB_PROPS_REGEN_DUE" in l for l in lines), lines)

    def test_a_genuinely_empty_artifact_still_triggers_a_regen(self):
        # The trigger's real job must survive: odds are posted, top props came back empty.
        self.top_props_path.write_text(json.dumps(_top_props(0)), encoding="utf-8")
        due, lines = self._run()
        self.assertTrue(due)
        self.assertTrue(any("MLB_PROPS_REGEN_DUE" in l for l in lines), lines)

    def test_no_file_anywhere_after_a_run_still_triggers(self):
        # daily_summary exists but top props do not: a run died before the top-props stage.
        due, _ = self._run()
        self.assertTrue(due)

    def test_the_store_is_still_a_fallback_and_is_named_when_it_answers(self):
        due, lines = self._run(store_copy=_top_props(5))
        self.assertFalse(due)
        self.assertTrue(any("MLB_TOP_PROPS_KEYVALUE_ONLY" in l and "candidates=5" in l for l in lines), lines)

    def test_disk_wins_over_a_stale_store_copy(self):
        # If both exist, disk is authoritative -- it is where the writer writes.
        self.top_props_path.write_text(json.dumps(_top_props(12)), encoding="utf-8")
        due, lines = self._run(store_copy=_top_props(0))
        self.assertFalse(due)
        self.assertFalse(any("MLB_TOP_PROPS_KEYVALUE_ONLY" in l for l in lines), lines)

    def test_no_odds_means_no_regen_even_when_empty(self):
        self.top_props_path.write_text(json.dumps(_top_props(0)), encoding="utf-8")
        due, _ = self._run(odds=False)
        self.assertFalse(due)


if __name__ == "__main__":
    unittest.main()
