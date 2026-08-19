"""The football season-projection generators must PUBLISH what they write.

Measured 2026-08-19 and this is the whole reason the test exists: refresh-worker
regenerated the NCAAF projection artifact on its own disk and the served board
did not move. The worker and web do NOT share a disk, web reads its mounted disk
via SYNDICATE_NCAAF_SOURCE_ROOT, and nothing pushed the file across -- so the
season-projection autorun was regenerating a file **nothing read**. The only
other route was committing the CSV to git and riding a web deploy, i.e. a
production deploy per model change.

WHY AN AST TEST AND NOT A CALL TEST. `publish_hot_artifact` is best-effort: it
returns False when unconfigured, which is every local and CI run. So a test that
merely calls it cannot tell "wired but unconfigured" from "not wired at all" --
False is the answer in both cases, and the second is the bug. Asserting on the
SOURCE proves the call site exists at all.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

GENERATORS = (
    "scripts/generate_smartsim2_ncaaf_projections.py",
    "scripts/generate_smartsim2_nfl_projections.py",
)


def _tree(rel: str) -> ast.AST:
    return ast.parse((REPO / rel).read_text(encoding="utf-8"))


def _calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == name:
                out.append(node)
            elif isinstance(func, ast.Attribute) and func.attr == name:
                out.append(node)
    return out


class GeneratorsPublishTests(unittest.TestCase):
    def test_each_generator_calls_publish_hot_artifact(self) -> None:
        for rel in GENERATORS:
            with self.subTest(generator=rel):
                calls = _calls_named(_tree(rel), "publish_hot_artifact")
                self.assertTrue(
                    calls,
                    f"{rel} writes an artifact the worker cannot get to web -- "
                    "the autorun would regenerate a file nothing reads",
                )

    def test_publish_failure_cannot_fail_generation(self) -> None:
        """A transfer error must not take the generator down with it.

        The artifact on disk is correct whether or not the push succeeded, and
        a generator that dies on a network blip turns a display problem into a
        data problem.
        """
        for rel in GENERATORS:
            with self.subTest(generator=rel):
                tree = _tree(rel)
                guarded = False
                for node in ast.walk(tree):
                    if isinstance(node, ast.Try) and _calls_named(node, "publish_hot_artifact"):
                        if node.handlers:
                            guarded = True
                self.assertTrue(guarded, f"{rel}: publish_hot_artifact is not inside a try/except")

    def test_publish_outcome_is_reported(self) -> None:
        """`published=False` on the worker is the invisible-failure condition.

        It means the board is still serving whatever it had. That was silent
        for the entire life of this gap, so the generators must say it out loud
        rather than only reporting the local write.
        """
        for rel in GENERATORS:
            with self.subTest(generator=rel):
                src = (REPO / rel).read_text(encoding="utf-8")
                self.assertIn("artifact_published=", src)


class PublisherContractTests(unittest.TestCase):
    """What the generators rely on the publisher to guarantee."""

    def test_publish_is_best_effort_and_returns_false_unconfigured(self) -> None:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        # No PUBLISH URL / ADMIN_TOKEN in a test process: must return False,
        # not raise, or every local generator run would die on the last line.
        self.assertFalse(publish_hot_artifact(REPO / "does_not_exist_anywhere.csv"))

    @unittest.expectedFailure
    def test_projection_artifacts_are_allowlisted(self) -> None:
        """THE REMAINING BLOCKER, asserted so it cannot be forgotten.

        `publish_hot_artifact` refuses any path outside HOT_ARTIFACT_PATTERNS,
        so the call sites above are inert until this pattern lands:

            *_source/data/smartsim2_projections_*.csv

        `artifact_publisher.py` is claimed by another lane, so the pattern was
        handed to them rather than edited across lanes.

        MARKED expectedFailure ON PURPOSE, and the marker is the mechanism: the
        suite stays green while the blocker stands, and the MOMENT the pattern
        lands this reports an UNEXPECTED SUCCESS -- a loud, specific signal to
        delete the marker and confirm the publish path end to end. A plain
        failing test would just be red noise somebody learns to scroll past;
        a skip would say nothing at all when the blocker clears.
        """
        from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path

        for rel in (
            "ncaaf_source/data/smartsim2_projections_2026_wk1.csv",
            "nfl_source/data/smartsim2_projections_2026_wk1.csv",
        ):
            with self.subTest(path=rel):
                self.assertTrue(
                    is_hot_artifact_relative_path(rel),
                    f"{rel} is not allowlisted -- the worker's publish call is INERT, "
                    "and the season-projection autorun regenerates a file nothing reads",
                )


if __name__ == "__main__":
    unittest.main()
