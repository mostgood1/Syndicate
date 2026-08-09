"""#288 -- the per-sport manifest gate, tested for what it actually does.

Replaces the assertion `test_build_candidate_pool_skips_sports_without_manifests`
was *meant* to make. That test patched `syndicate.features.intelligence.
collect_all_recommendations`, which `pipeline/intelligence_state.py` does not
reference anywhere -- so the patch was a total no-op, the `18` it produced came
from whatever real git-tracked mirror data happened to sit in
`data/mlb_source/data/daily/sims/2026-06-10/` on the machine running it, and its
NBA arm returned 0 for want of NBA data on that date rather than for want of a
manifest. **Delete the gate entirely and that test does not move.** It is
plausibly the only automated check in the repo for per-sport manifest
divergence and it has never once exercised it.

So these tests start from what the gate means rather than from its old numbers:

    A sport reaches the candidate pool if and only if it has a readable
    manifest at reports_root()/manifests/<slug>.json.

Both halves matter. The "only if" is the gate working. The "if" is the half that
made this class of defect expensive all evening: a sport silently missing its
manifest is indistinguishable, from every downstream surface, from a sport that
simply has no games today.

Each test below goes through the real `_available_sport_manifests`, so removing
the gate fails them -- which is the property the old test lacked. No test here
reads `data/`, so none of them are machine-dependent.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

from pipeline.intelligence_state import IntelligenceStateService


def _overview(*slugs: str) -> list[dict[str, object]]:
    """The shape `_available_sport_manifests` reads: it only uses `slug`."""
    return [{"slug": slug, "name": slug.upper(), "data_health": "ready"} for slug in slugs]


class ManifestGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.reports_root = Path(self._tmp.name)
        (self.reports_root / "manifests").mkdir(parents=True, exist_ok=True)
        self.service = IntelligenceStateService()

    def _write_manifest(self, slug: str, *, status: str = "complete") -> None:
        (self.reports_root / "manifests" / f"{slug}.json").write_text(
            json.dumps(
                {
                    "sport": slug,
                    "last_updated": "2026-06-10T10:00:00Z",
                    "artifact_paths": [f"reports/intelligence/{slug}.json"],
                    "status": status,
                }
            ),
            encoding="utf-8",
        )

    def _available(self, *slugs: str, capture: io.StringIO | None = None):
        with unittest.mock.patch(
            "pipeline.intelligence_state.reports_root", return_value=self.reports_root
        ), unittest.mock.patch(
            "pipeline.intelligence_state.build_intelligence_overview", return_value=_overview(*slugs)
        ):
            if capture is not None:
                with redirect_stdout(capture):
                    return self.service._available_sport_manifests("2026-06-10")
            return self.service._available_sport_manifests("2026-06-10")

    # -- the gate itself -------------------------------------------------

    def test_a_sport_with_a_manifest_is_kept(self) -> None:
        self._write_manifest("mlb")
        self.assertIn("mlb", self._available("mlb"))

    def test_a_sport_without_a_manifest_is_dropped(self) -> None:
        """The 'only if' half. This is what the old test claimed to check."""
        self._write_manifest("mlb")
        available = self._available("mlb", "nba")
        self.assertEqual(list(available.keys()), ["mlb"])

    def test_the_drop_is_attributable_to_the_manifest_and_nothing_else(self) -> None:
        """Prove the exclusion is caused by the manifest, not by the sport being
        absent or malformed upstream -- the flaw that made the old test's NBA arm
        prove nothing. Both sports are identical in the overview; the ONLY
        difference is which one has a manifest file, and flipping which file
        exists flips which sport survives."""
        self._write_manifest("mlb")
        self.assertEqual(list(self._available("mlb", "nba").keys()), ["mlb"])

        (self.reports_root / "manifests" / "mlb.json").unlink()
        self._write_manifest("nba")
        self.assertEqual(list(self._available("mlb", "nba").keys()), ["nba"])

    def test_a_malformed_manifest_is_treated_as_absent(self) -> None:
        (self.reports_root / "manifests" / "nhl.json").write_text("not json", encoding="utf-8")
        self.assertEqual(list(self._available("nhl").keys()), [])

    def test_a_json_manifest_that_is_not_an_object_is_treated_as_absent(self) -> None:
        (self.reports_root / "manifests" / "nhl.json").write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(list(self._available("nhl").keys()), [])

    def test_every_configured_sport_survives_when_all_are_manifested(self) -> None:
        slugs = ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer")
        for slug in slugs:
            self._write_manifest(slug)
        self.assertEqual(tuple(self._available(*slugs).keys()), slugs)

    # -- absent legitimately vs absent silently --------------------------

    def test_skipped_sports_are_named_so_the_absence_is_not_silent(self) -> None:
        """The half that cost a cross-provider audit. Before this line, a sport
        missing its manifest and a sport with no games produced the identical
        observable: nothing."""
        self._write_manifest("mlb")
        captured = io.StringIO()
        self._available("mlb", "nba", "nhl", capture=captured)
        out = captured.getvalue()
        self.assertIn("MANIFEST_GATE_SKIPPED_SPORTS", out)
        self.assertIn("skipped=nba,nhl", out)
        self.assertIn("kept=mlb", out)

    def test_nothing_is_logged_when_every_sport_is_manifested(self) -> None:
        """A diagnostic that fires on a healthy slate is noise, and noise on a
        worker that prints hundreds of lines per cycle is how a real signal gets
        missed."""
        self._write_manifest("mlb")
        self._write_manifest("wnba")
        captured = io.StringIO()
        self._available("mlb", "wnba", capture=captured)
        self.assertNotIn("MANIFEST_GATE_SKIPPED_SPORTS", captured.getvalue())

    def test_the_log_line_is_one_per_build_not_one_per_sport(self) -> None:
        self._write_manifest("mlb")
        captured = io.StringIO()
        self._available("mlb", "nba", "nhl", "ncaab", "ncaaf", capture=captured)
        self.assertEqual(captured.getvalue().count("MANIFEST_GATE_SKIPPED_SPORTS"), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
