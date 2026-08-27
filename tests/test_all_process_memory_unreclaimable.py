"""`#566` -- `ALL_PROCESS_MEMORY` must carry the number that actually kills.

WHY THIS EXISTS, and it is an error I made rather than one I found.
`log_container_memory`'s own docstring records the defect for its sibling line:
the anon/page-cache breakdown "was simply never wired into the line that gets
logged, which is the one people actually read." That was fixed for
`CONTAINER_MEMORY` and left undone for `ALL_PROCESS_MEMORY` -- which is the line
a deploy preflight reads, because it is the one carrying the process list.

MEASURED BY BEING TAKEN IN, 2026-08-25. Across one session I quoted
`container_memory_pct_of_max` at 93.2%, 96.8% and 99.8% off this line and
reported a memory emergency four times. There was none: zero `oomKilled` events
in the preceding two days, and anonymous memory over the same window ran
1135-1760 MB of 4096 -- 28-43%. `#79` and `#417` had already established twice
that `memory.current` counts clean page cache the kernel drops before it
OOM-kills anything.

A reader with both numbers cannot make that mistake. A reader with only the
first one reliably does.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from syndicate.features.shared import memory_observability as mo

MB = 1024 * 1024


class AllProcessMemoryUnreclaimableTests(unittest.TestCase):
    def _snapshot(self, *, current_mb, max_mb, stat):
        with patch.object(mo, "_read_container_memory_current_bytes", return_value=int(current_mb * MB)), \
             patch.object(mo, "_read_container_memory_max_bytes", return_value=int(max_mb * MB)), \
             patch.object(mo, "_read_container_memory_stat", return_value=stat), \
             patch.object(mo, "_procfs_pid_list", return_value=[]):
            return mo.get_all_process_memory_snapshot()

    def test_the_pathological_case_from_2026_08_25_reads_correctly_now(self):
        # 99.8% of max, of which the overwhelming majority is evictable page
        # cache. THIS is the reading that produced four false alarms.
        stat = {"anon": int(1400 * MB), "inactive_file": int(2000 * MB),
                "active_file": int(600 * MB), "slab_reclaimable": 0}
        snap = self._snapshot(current_mb=4087, max_mb=4096, stat=stat)
        self.assertAlmostEqual(snap["container_memory_pct_of_max"], 99.8, delta=0.2)
        # The number that decides whether the container dies.
        self.assertIsNotNone(snap["container_memory_unreclaimable_pct_of_max"])
        self.assertLess(
            snap["container_memory_unreclaimable_pct_of_max"], 50.0,
            "the anonymous figure must show this container was never near an OOM",
        )

    def test_a_genuinely_full_container_still_reads_full(self):
        # The guard this must NOT weaken: anon actually at the limit.
        stat = {"anon": int(3900 * MB), "inactive_file": int(100 * MB),
                "active_file": 0, "slab_reclaimable": 0}
        snap = self._snapshot(current_mb=4000, max_mb=4096, stat=stat)
        self.assertGreater(snap["container_memory_unreclaimable_pct_of_max"], 90.0)

    def test_both_numbers_are_present_so_neither_can_be_read_alone(self):
        stat = {"anon": int(1000 * MB), "inactive_file": int(1000 * MB),
                "active_file": 0, "slab_reclaimable": 0}
        snap = self._snapshot(current_mb=2000, max_mb=4096, stat=stat)
        for field in (
            "container_memory_mb",
            "container_memory_pct_of_max",
            "container_memory_unreclaimable_mb",
            "container_memory_unreclaimable_pct_of_max",
        ):
            with self.subTest(field=field):
                self.assertIsNotNone(snap[field])

    def test_an_unreadable_stat_leaves_the_fields_ABSENT_not_misleading(self):
        # Degrading to `container_memory_mb` under this NAME would be worse than
        # the omission being fixed -- a reader seeing a number here is entitled
        # to assume it is the anonymous one.
        snap = self._snapshot(current_mb=4000, max_mb=4096, stat={})
        self.assertIsNone(snap["container_memory_unreclaimable_mb"])
        self.assertIsNone(snap["container_memory_unreclaimable_pct_of_max"])
        self.assertIsNotNone(snap["container_memory_pct_of_max"])

    def test_telemetry_never_raises(self):
        with patch.object(mo, "_read_container_memory_stat", side_effect=RuntimeError("no cgroup")), \
             patch.object(mo, "_read_container_memory_current_bytes", return_value=int(2000 * MB)), \
             patch.object(mo, "_read_container_memory_max_bytes", return_value=int(4096 * MB)), \
             patch.object(mo, "_procfs_pid_list", return_value=[]):
            snap = mo.get_all_process_memory_snapshot()
        self.assertIsNone(snap["container_memory_unreclaimable_mb"])

    def test_the_two_lines_now_agree_on_the_same_container(self):
        # CONTAINER_MEMORY and ALL_PROCESS_MEMORY must not tell two stories.
        stat = {"anon": int(1400 * MB), "inactive_file": int(2600 * MB),
                "active_file": 0, "slab_reclaimable": 0}
        with patch.object(mo, "_read_container_memory_current_bytes", return_value=int(4000 * MB)), \
             patch.object(mo, "_read_container_memory_max_bytes", return_value=int(4096 * MB)), \
             patch.object(mo, "_read_container_memory_stat", return_value=stat), \
             patch.object(mo, "_procfs_pid_list", return_value=[]):
            all_proc = mo.get_all_process_memory_snapshot()
            container = mo.container_memory_payload("test")
        self.assertAlmostEqual(
            all_proc["container_memory_unreclaimable_mb"],
            container["memory_unreclaimable_mb"],
            delta=1.0,
        )


if __name__ == "__main__":
    unittest.main()
