"""Floor vs peak -- which SHAPE kills web. `#632`.

Attribution has gone as far as it can: requests own ~82% of net anon movement
(measured, n=16 windows), no single route owns it, and per-request deltas do not
compose into net process change under munmap-heavy churn. So the remaining
question is not "who allocated it" but which shape the service dies of:

  a RISING FLOOR   -> retention. Bounding concurrency cannot save it.
  a FLAT FLOOR with a HIGH PEAK -> churn. The merge-child CAP -- the one
                       intervention that measurably worked all session, taking
                       peak summed child memory 400.6 -> 163.3 MB -- bounds
                       exactly this and nothing else.

`VmHWM` is the kernel's own high-water mark and CANNOT be lowered by a free,
which is the property that matters: a process whose current RSS is modest while
its HWM sits near the limit died of a peak no sampling cadence would have caught.

The floor must be read over a window that excludes boot warm-up. That is a known
confound in this repo -- every deploy reboots, so every fix looks good for five
minutes -- and it is why these tests pin `n` alongside the extremes.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from syndicate.features.shared import memory_observability as MOD


class ExtremeTrackingTests(unittest.TestCase):

    def setUp(self) -> None:
        MOD.reset_request_memory_attribution()

    tearDown = setUp

    def test_it_records_BOTH_ends_not_just_the_peak(self) -> None:
        """A peak alone cannot distinguish the two shapes. The floor is the half
        that says whether memory is being returned."""
        for value, route in ((100.0, "/a"), (340.0, "/spike"), (95.0, "/low"), (280.0, "/b")):
            MOD._note_anon_extreme(value, route, 1)

        extremes = MOD.request_memory_attribution_payload()["anon_extremes"]

        self.assertAlmostEqual(extremes["floor_mb"], 95.0, places=1)
        self.assertEqual(extremes["floor_route"], "/low")
        self.assertAlmostEqual(extremes["peak_mb"], 340.0, places=1)
        self.assertEqual(extremes["peak_route"], "/spike")
        self.assertAlmostEqual(extremes["spread_mb"], 245.0, places=1)
        self.assertEqual(extremes["n"], 4)

    def test_a_FLAT_FLOOR_under_a_high_peak_is_the_churn_signature(self) -> None:
        """Memory returns to the same level after each spike."""
        for value in (100.0, 400.0, 101.0, 380.0, 100.5, 420.0):
            MOD._note_anon_extreme(value, "/x", 1)

        extremes = MOD.request_memory_attribution_payload()["anon_extremes"]

        self.assertAlmostEqual(extremes["floor_mb"], 100.0, places=1)
        self.assertAlmostEqual(extremes["peak_mb"], 420.0, places=1)
        self.assertGreater(extremes["spread_mb"], 300.0)

    def test_a_RISING_FLOOR_is_the_retention_signature(self) -> None:
        """The falsification case. Here the floor is set by the FIRST reading and
        never revisited, so floor and peak are the two ends of a ramp -- which is
        what retention looks like and churn does not."""
        for value in (100.0, 150.0, 200.0, 250.0, 300.0):
            MOD._note_anon_extreme(value, "/x", 1)

        extremes = MOD.request_memory_attribution_payload()["anon_extremes"]

        self.assertAlmostEqual(extremes["floor_mb"], 100.0, places=1)
        self.assertAlmostEqual(extremes["peak_mb"], 300.0, places=1)

    def test_the_extremes_survive_a_LATER_ordinary_reading(self) -> None:
        """A running min/max must not decay toward the most recent value -- the
        spike that kills the process may be hundreds of requests before the
        emission that reports it."""
        MOD._note_anon_extreme(500.0, "/spike", 1)
        for _ in range(50):
            MOD._note_anon_extreme(120.0, "/ordinary", 1)

        extremes = MOD.request_memory_attribution_payload()["anon_extremes"]

        self.assertAlmostEqual(extremes["peak_mb"], 500.0, places=1)
        self.assertEqual(extremes["peak_route"], "/spike")

    def test_an_unsampled_process_publishes_None_not_a_crash(self) -> None:
        extremes = MOD.request_memory_attribution_payload()["anon_extremes"]

        self.assertIsNone(extremes["floor_mb"])
        self.assertIsNone(extremes["peak_mb"])
        self.assertIsNone(extremes["spread_mb"])
        self.assertEqual(extremes["n"], 0)

    def test_reset_clears_them(self) -> None:
        MOD._note_anon_extreme(500.0, "/x", 1)

        MOD.reset_request_memory_attribution()

        self.assertIsNone(MOD.request_memory_attribution_payload()["anon_extremes"]["peak_mb"])


class VmHighWaterTests(unittest.TestCase):

    def _status(self, hwm_kb: int, rss_kb: int) -> str:
        return (
            "Name:\tpython3.11\n"
            "VmPeak:\t 2400000 kB\n"
            f"VmHWM:\t{hwm_kb:>9} kB\n"
            f"VmRSS:\t{rss_kb:>9} kB\n"
            "Threads:\t5\n"
        )

    def test_it_reads_the_KERNELS_high_water_mark(self) -> None:
        """The reading that survives a free. A modest VmRSS beside a VmHWM near
        the limit is the signature of a peak nothing sampled."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "self").mkdir()
            (root / "self" / "status").write_text(self._status(1_900_000, 700_000),
                                                  encoding="utf-8")
            with mock.patch.object(MOD, "_PROCFS_ROOT", root):
                values = MOD._read_vm_highwater()

        self.assertAlmostEqual(values["vm_hwm_mb"], 1855.47, places=1)
        self.assertAlmostEqual(values["vm_rss_mb"], 683.59, places=1)
        self.assertGreater(values["vm_hwm_mb"], values["vm_rss_mb"])

    def test_it_lands_in_the_attribution_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "self").mkdir()
            (root / "self" / "status").write_text(self._status(1_000_000, 500_000),
                                                  encoding="utf-8")
            with mock.patch.object(MOD, "_PROCFS_ROOT", root):
                payload = MOD.request_memory_attribution_payload()

        self.assertAlmostEqual(payload["vm_hwm_mb"], 976.56, places=1)
        self.assertAlmostEqual(payload["vm_rss_mb"], 488.28, places=1)

    def test_a_missing_procfs_yields_NO_KEYS_rather_than_zeros(self) -> None:
        """A zero would read as "the process never grew", which is a claim. An
        absent key reads as "not measured", which is the truth off Linux."""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(MOD, "_PROCFS_ROOT", pathlib.Path(tmp)):
                values = MOD._read_vm_highwater()

        self.assertEqual(values, {})

    def test_a_malformed_line_is_skipped_not_crashed_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "self").mkdir()
            (root / "self" / "status").write_text(
                "VmHWM:\tnot-a-number kB\nVmRSS:\t   500000 kB\n", encoding="utf-8")
            with mock.patch.object(MOD, "_PROCFS_ROOT", root):
                values = MOD._read_vm_highwater()

        self.assertNotIn("vm_hwm_mb", values)
        self.assertAlmostEqual(values["vm_rss_mb"], 488.28, places=1)


if __name__ == "__main__":
    unittest.main()
