"""`#427`. The deploy gate's build estimate must not collapse on short-circuits.

MEASURED on Render (refresh-worker, 4h to 2026-08-14 18:0xZ, live `294f9ca9`), n=39
`COLLECT_SPAN_EXIT collect_candidates`:

    p50 0.00   p90 146.19   max 209.66
    of those >= 1s: n=9, p50 138.30, max 209.66
    ~77% sub-second, 23.1% >= 60s

The sub-second calls are `collect_candidates` short-circuiting on an empty pool.
MAX over a MIXED sample is the right statistic; what matters is excluding the
non-builds first, because the max of twelve zeros is zero.

Since 2026-11-15 (lane render-retirement) the only estimator is the FLEET one,
`_fleet_expected_build_seconds`, over `BOARD_BUILD_TIMING wall_s` in the fleet's
refresh-worker log. The same cases are pinned on it. One difference is deliberate:
with no real build in the window it returns None (unknown), and callers floor it,
where the Render estimator returned a 210 s constant.
"""

from __future__ import annotations

import unittest

import scripts.check_deploy_safety as gate


def _line(wall: float) -> str:
    return f"[intelligence_state] BOARD_BUILD_TIMING wall_s={wall} cpu_s=1.0 ok=True"


class FleetExpectedBuildSecondsTests(unittest.TestCase):
    def _expected(self, walls, noise=()):
        return gate._fleet_expected_build_seconds([*noise, *(_line(w) for w in walls)])

    # -- the defect `#427` closed -------------------------------------------

    def test_all_short_circuits_do_not_report_a_cheap_build(self) -> None:
        """Twelve zeros must not become 'a build takes 0 min': unknown, which callers floor."""
        self.assertIsNone(self._expected([0.0] * 12))

    def test_the_measured_production_mix(self) -> None:
        """77% zeros with real builds present -> the real maximum."""
        self.assertAlmostEqual(self._expected([0.0] * 9 + [138.3, 146.19, 209.66]), 209.66, places=2)

    def test_a_single_real_build_among_zeros_wins(self) -> None:
        self.assertAlmostEqual(self._expected([0.0] * 11 + [187.4]), 187.4, places=2)

    # -- what must NOT change ---------------------------------------------

    def test_max_not_median_on_a_mixed_real_sample(self) -> None:
        """Over-waiting costs idle minutes, under-waiting destroys a board build."""
        self.assertAlmostEqual(self._expected([120.0, 200.0, 1372.2, 180.0]), 1372.2, places=1)

    def test_only_the_last_twelve_builds_count(self) -> None:
        self.assertAlmostEqual(self._expected([5000.0] + [150.0] * 12), 150.0, places=1)

    def test_empty_log_returns_None(self) -> None:
        self.assertIsNone(gate._fleet_expected_build_seconds([]))

    def test_lines_without_a_wall_field_are_ignored_not_counted_as_zero(self) -> None:
        noise = ["[intelligence_state] BOARD_BUILD_TIMING ok=True", "MEMORY_WATCHDOG {\"wall_s\": 9999}"]
        self.assertAlmostEqual(self._expected([150.0], noise=noise), 150.0, places=1)

    def test_threshold_sits_below_every_measured_real_build(self) -> None:
        """A guard against someone raising the threshold into the real band."""
        self.assertLess(gate._MIN_REAL_BUILD_SECONDS, 138.3)
        self.assertGreater(gate._MIN_REAL_BUILD_SECONDS, 0.0)

    def test_the_render_estimator_is_gone(self) -> None:
        for name in ("_expected_build_seconds", "_NO_REAL_BUILD_FALLBACK_SECONDS", "_render_logs"):
            self.assertFalse(hasattr(gate, name), name)


if __name__ == "__main__":
    unittest.main()
