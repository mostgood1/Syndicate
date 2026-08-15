"""A published probability is computed or absent -- never the midpoint.

Sized before it was fixed: across 40 local artifacts and 4,240
probability-bearing rows, 73 carried an exact 0.5 and **6 of those had no
price at all** -- every price-missing row in the set. `_american_price_to_prob`
returns None for a missing or zero price, and `... or 0.5` turned each of
those into a coin flip that looked computed.

Two kinds of test here, deliberately:

* behavioural, on the helpers the fixed code now composes; and
* a STATIC check that the fabrication shape is not present in the two
  producers. The inline expressions live inside 200-line functions that need
  live odds to run, so a behavioural test cannot reach them -- but the rule
  ("never substitute the midpoint") is a property of the source, and a source
  test cannot rot the way a data fixture does.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    REPO_ROOT / "scripts" / "refresh_nba_oddsapi_props.py",
    REPO_ROOT / "scripts" / "refresh_wnba_oddsapi_props.py",
]

# `or 0.5` / `or 50.0` / `or .5` outside a comment.
FABRICATION = re.compile(r"\bor\s+(?:0?\.5|50\.0)\b")


def _code_lines(path: Path) -> list[tuple[int, str]]:
    lines = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        lines.append((number, raw.split("  #")[0]))
    return lines


class NoMidpointSubstitutionTests(unittest.TestCase):
    def test_the_producers_do_not_substitute_a_midpoint_probability(self) -> None:
        offenders = []
        for path in SCRIPTS:
            for number, line in _code_lines(path):
                if FABRICATION.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual(
            [],
            offenders,
            "a missing probability must propagate as None, not become 0.5:\n" + "\n".join(offenders),
        )


class HelperAbsenceTests(unittest.TestCase):
    """The helpers the fixed expressions compose."""

    def setUp(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "refresh_wnba_oddsapi_props_under_test",
            REPO_ROOT / "scripts" / "refresh_wnba_oddsapi_props.py",
        )
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_no_price_yields_no_implied_probability(self) -> None:
        for missing in (None, "", 0, "0"):
            self.assertIsNone(
                self.module._american_price_to_prob(missing),
                f"{missing!r} is not a price and cannot imply a probability",
            )

    def test_a_real_price_still_converts(self) -> None:
        self.assertAlmostEqual(0.5, self.module._american_price_to_prob(-100), places=6)
        self.assertAlmostEqual(0.5, self.module._american_price_to_prob(100), places=6)
        self.assertAlmostEqual(0.6, self.module._american_price_to_prob(-150), places=6)

    def test_an_exact_half_from_a_real_price_is_legitimate(self) -> None:
        # Why the fix targets price-missing rows and not "every 0.5": a
        # -100 quote implies exactly 0.5, and 67 of the 73 exact-0.5 rows
        # measured had a real price. Those are data, not defects.
        self.assertEqual(0.5, self.module._american_price_to_prob(-100))

    def test_clamp_passes_absence_through(self) -> None:
        self.assertIsNone(self.module._clamp_probability(None))
        self.assertEqual(0.0, self.module._clamp_probability(-1.0))
        self.assertEqual(1.0, self.module._clamp_probability(2.0))

    def test_a_genuine_zero_probability_is_not_falsy_swallowed(self) -> None:
        # The `or` chain this replaced fired on 0.0 as well as on None.
        self.assertEqual(0.0, self.module._clamp_probability(0.0))


if __name__ == "__main__":
    unittest.main()
