from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from syndicate.features.shared.atomic_artifact_write import atomic_write_csv
from syndicate.features.shared.atomic_artifact_write import atomic_write_text


class AtomicWriteTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_writes_content(self) -> None:
        target = self.root / "artifact.csv"
        atomic_write_text(target, "a,b\n1,2\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "a,b\n1,2\n")

    def test_creates_missing_parent_directories(self) -> None:
        target = self.root / "nested" / "deeper" / "artifact.json"
        atomic_write_text(target, "{}")
        self.assertTrue(target.is_file())

    def test_replaces_existing_file(self) -> None:
        target = self.root / "artifact.csv"
        target.write_text("old", encoding="utf-8")
        atomic_write_text(target, "new")
        self.assertEqual(target.read_text(encoding="utf-8"), "new")

    def test_leaves_previous_file_intact_when_write_fails(self) -> None:
        # The whole point: a failed write must not truncate the artifact a
        # reader is about to load.
        target = self.root / "artifact.csv"
        target.write_text("original", encoding="utf-8")
        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                atomic_write_text(target, "replacement")
        self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_leaves_no_temp_file_behind_on_success(self) -> None:
        target = self.root / "artifact.csv"
        atomic_write_text(target, "x")
        self.assertEqual([p.name for p in self.root.iterdir()], ["artifact.csv"])

    def test_leaves_no_temp_file_behind_on_failure(self) -> None:
        # Temps live in the destination directory, which artifact readers
        # glob over -- an orphan would be picked up as an artifact.
        target = self.root / "artifact.csv"
        with patch("os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                atomic_write_text(target, "x")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_temp_name_is_unique_per_writer(self) -> None:
        # Two processes writing the same artifact must not share a temp path.
        # The `path.with_suffix(".tmp")` pattern used elsewhere in the repo
        # gives both writers the SAME temp file, so they interleave into it
        # and one renames a file the other is still writing.
        target = self.root / "artifact.csv"
        seen: list[str] = []
        real_replace = os.replace

        def _capture(src, dst):
            seen.append(Path(src).name)
            return real_replace(src, dst)

        with patch("os.replace", side_effect=_capture):
            atomic_write_text(target, "one")
            atomic_write_text(target, "two")

        self.assertEqual(len(set(seen)), 2, f"temp names must differ per write, got {seen}")
        self.assertTrue(all(name.startswith("artifact.csv.") for name in seen))

    def test_temp_is_created_beside_the_destination(self) -> None:
        # os.replace is only atomic within one filesystem; a temp elsewhere
        # would silently degrade to a copy across a mount boundary.
        target = self.root / "nested" / "artifact.csv"
        captured: list[Path] = []
        real_replace = os.replace

        with patch("os.replace", side_effect=lambda src, dst: (captured.append(Path(src)), real_replace(src, dst))[1]):
            atomic_write_text(target, "x")

        self.assertEqual(captured[0].parent, target.parent)

    def test_none_is_written_as_empty_not_the_string_none(self) -> None:
        target = self.root / "artifact.csv"
        atomic_write_text(target, None)  # type: ignore[arg-type]
        self.assertEqual(target.read_text(encoding="utf-8"), "")


class AtomicWriteCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_writes_dataframe_without_index_by_default(self) -> None:
        target = self.root / "props.csv"
        atomic_write_csv(target, pd.DataFrame({"a": [1, 2], "b": [3, 4]}))
        self.assertEqual(target.read_text(encoding="utf-8").splitlines()[0], "a,b")

    def test_round_trips(self) -> None:
        target = self.root / "props.csv"
        frame = pd.DataFrame({"event_id": ["e1", "e2"], "price": [-110, 145]})
        atomic_write_csv(target, frame)
        pd.testing.assert_frame_equal(pd.read_csv(target), frame)

    def test_serialisation_failure_leaves_previous_artifact_intact(self) -> None:
        # Renders to a string before touching the destination, so a bad frame
        # leaves a stale artifact rather than a truncated one -- staleness is
        # detectable downstream, truncation is not.
        target = self.root / "props.csv"
        target.write_text("event_id,price\ne1,-110\n", encoding="utf-8")

        class Exploding:
            def to_csv(self, **_kwargs):
                raise ValueError("bad frame")

        with self.assertRaises(ValueError):
            atomic_write_csv(target, Exploding())
        self.assertEqual(target.read_text(encoding="utf-8"), "event_id,price\ne1,-110\n")

    def test_honours_explicit_to_csv_kwargs(self) -> None:
        target = self.root / "props.csv"
        atomic_write_csv(target, pd.DataFrame({"a": [1]}), index=True)
        self.assertTrue(target.read_text(encoding="utf-8").startswith(","))
