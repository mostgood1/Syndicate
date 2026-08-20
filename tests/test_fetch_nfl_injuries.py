"""`nfl-injuries-fetcher` lane — the injuries fetcher must not install a file
that recreates the failure this lane exists to close: `injury_adjustment.py`
silently reading zero injured players because nothing kept its one input
current (or because a truncated/mis-scoped download replaced a good file).

Mirrors `test_fetch_nfl_pbp.py`'s shape. Differences from that fixture, both
deliberate:

- No `epa`-drop-style silent-schema-change case -- the injuries required
  columns are exactly what `_injured_players_for_team` reads
  (team/week/gsis_id/position/full_name/report_status), so a missing column
  there is caught the same way, but there is no equivalent of "count is fine,
  content is garbage" the way EPA-less pbp rows still resemble real football.
- Adds the season-mismatch check `fetch_nfl_pbp.py` has no equivalent of
  (pbp's file naming makes this a non-issue there; the injuries release
  process does not guarantee it).
- No `--only-season` flag and no prior-season fallback test: injuries have no
  sensible "who was hurt last year" fallback, unlike pbp's team-rating prior.
"""
from __future__ import annotations

import gzip
import io
import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scripts.fetch_nfl_injuries as fetcher


def _writer_for(body: bytes):
    """Stand-in for _download_to: writes *body* to the staging path it is given."""
    def _write(season, destination, *, timeout):
        Path(destination).write_bytes(body)
    return _write


def _csv_bytes(rows: list[dict], columns: tuple[str, ...] | None = None) -> bytes:
    cols = list(columns or fetcher.REQUIRED_COLUMNS)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=cols)
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in cols})
    return buffer.getvalue().encode("utf-8")


def _good_rows(n: int, *, season: int = 2025) -> list[dict]:
    return [
        {
            "season": str(season), "season_type": "REG", "team": "KC", "week": "1",
            "gsis_id": f"00-000{i:04d}", "position": "WR", "full_name": f"Player {i}",
            "report_status": "Out",
        }
        for i in range(n)
    ]


class ValidationRefusesDegenerateDownloads(unittest.TestCase):
    def test_truncated_body_is_rejected_and_leaves_the_existing_file(self):
        """THE CORE CASE. A short body must not overwrite a good file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "tracking" / "nflverse" / "injuries" / "injuries_2025.csv"
            dest.parent.mkdir(parents=True)
            dest.write_text("GOOD EXISTING FILE", encoding="utf-8")
            short = _csv_bytes(_good_rows(10))  # well under MIN_ROWS
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root), \
                 patch.object(fetcher, "_download_to", side_effect=_writer_for(short)):
                result = fetcher.fetch_season(2025, force=True, timeout=5)
            self.assertEqual(result["status"], "rejected")
            self.assertTrue(any("rows" in p for p in result["problems"]))
            self.assertEqual(dest.read_text(encoding="utf-8"), "GOOD EXISTING FILE")

    def test_missing_required_column_is_rejected(self):
        cols = tuple(c for c in fetcher.REQUIRED_COLUMNS if c != "report_status")
        body = _csv_bytes(_good_rows(fetcher.MIN_ROWS + 50), columns=cols)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root), \
                 patch.object(fetcher, "_download_to", side_effect=_writer_for(body)):
                result = fetcher.fetch_season(2025, force=True, timeout=5)
            self.assertEqual(result["status"], "rejected")
            self.assertTrue(any("report_status" in p for p in result["problems"]))
            self.assertFalse((root / "tracking" / "nflverse" / "injuries" / "injuries_2025.csv").exists())

    def test_season_mismatch_is_rejected(self):
        """A file whose own `season` column disagrees with the requested season
        must not install -- every future read call resolves it as the wrong
        season's reports otherwise."""
        body = _csv_bytes(_good_rows(fetcher.MIN_ROWS + 50, season=2024))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root), \
                 patch.object(fetcher, "_download_to", side_effect=_writer_for(body)):
                result = fetcher.fetch_season(2025, force=True, timeout=5)
            self.assertEqual(result["status"], "rejected")
            self.assertTrue(any("season" in p for p in result["problems"]))

    def test_a_healthy_body_is_written_atomically(self):
        body = _csv_bytes(_good_rows(fetcher.MIN_ROWS + 100))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root), \
                 patch.object(fetcher, "_download_to", side_effect=_writer_for(body)):
                result = fetcher.fetch_season(2025, force=True, timeout=5)
            dest = root / "tracking" / "nflverse" / "injuries" / "injuries_2025.csv"
            self.assertEqual(result["status"], "written")
            self.assertTrue(dest.is_file())
            self.assertGreaterEqual(result["rows"], fetcher.MIN_ROWS)
            # no temp files left behind
            leftovers = [p.name for p in dest.parent.iterdir() if p.name != dest.name]
            self.assertEqual(leftovers, [])


class PublishesToWebOnSuccess(unittest.TestCase):
    """`nfl-artifact-publish-wiring`: THE FALSIFICATION CASE. Before this
    lane, this script had no publish call site at all -- confirmed live
    2026-08-20, `/api/ops/artifacts/export` returned `count: 0` after the
    allowlist fix alone. `HOT_ARTIFACT_PATTERNS` PERMITS the transfer;
    this is what makes one happen."""

    def test_a_healthy_write_calls_publish_hot_artifact_with_the_real_path(self):
        body = _csv_bytes(_good_rows(fetcher.MIN_ROWS + 100))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root), \
                 patch.object(fetcher, "_download_to", side_effect=_writer_for(body)), \
                 patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", return_value=True) as mock_publish:
                result = fetcher.fetch_season(2025, force=True, timeout=5)
            dest = root / "tracking" / "nflverse" / "injuries" / "injuries_2025.csv"
            mock_publish.assert_called_once_with(dest)
            self.assertTrue(result["published"])

    def test_publish_failure_does_not_fail_the_fetch(self):
        body = _csv_bytes(_good_rows(fetcher.MIN_ROWS + 100))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root), \
                 patch.object(fetcher, "_download_to", side_effect=_writer_for(body)), \
                 patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", side_effect=RuntimeError("network down")):
                result = fetcher.fetch_season(2025, force=True, timeout=5)
            self.assertEqual(result["status"], "written")
            self.assertFalse(result["published"])
            self.assertIn("RuntimeError", result["publish_error"])

    def test_rejected_write_does_not_attempt_to_publish(self):
        short = _csv_bytes(_good_rows(10))  # under MIN_ROWS
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root), \
                 patch.object(fetcher, "_download_to", side_effect=_writer_for(short)), \
                 patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact") as mock_publish:
                result = fetcher.fetch_season(2025, force=True, timeout=5)
            self.assertEqual(result["status"], "rejected")
            mock_publish.assert_not_called()


class UnavailableSeasonIsNotAFailure(unittest.TestCase):
    def test_404_on_a_season_with_no_release_yet_does_not_fail_the_run(self):
        """A season with no injury reports published yet is NORMAL, not a
        failure -- it must not alarm every day until reports start."""
        import urllib.error

        def _download(season, destination, *, timeout):
            raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root), \
                 patch.object(fetcher, "_download_to", side_effect=_download):
                code = fetcher.main(["--season", "2026", "--json"])
        self.assertEqual(code, 0)

    def test_everything_failing_does_exit_non_zero(self):
        import urllib.error

        def _download(season, destination, *, timeout):
            raise urllib.error.HTTPError("u", 500, "Server Error", {}, None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root), \
                 patch.object(fetcher, "_download_to", side_effect=_download):
                code = fetcher.main(["--season", "2026", "--json"])
        self.assertEqual(code, 1)


class WritesToTheMountedDiskResolver(unittest.TestCase):
    def test_destination_uses_the_output_resolver_not_default_root(self):
        """Same rule `#389`/`#441` established for pbp: `default_nfl_source_
        root()` resolves to the ephemeral checkout on refresh-worker. The
        fetcher must use the OUTPUT resolver, not that one."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mounted"
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root):
                path = fetcher._injuries_destination(2025)
        self.assertEqual(path, root / "tracking" / "nflverse" / "injuries" / "injuries_2025.csv")


class GzipHandling(unittest.TestCase):
    def _run_download(self, wire: bytes) -> bytes:
        """Drive _download_to with a chunked fake response and return the file."""
        class _Resp:
            def __init__(self, data): self._buf = io.BytesIO(data)
            def read(self, n=-1): return self._buf.read(n)
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.csv"
            with patch.object(fetcher.urllib.request, "urlopen", return_value=_Resp(wire)):
                fetcher._download_to(2025, dest, timeout=5)
            return dest.read_bytes()

    def test_gzipped_release_is_decompressed(self):
        """The release is plain CSV today, confirmed live -- but format is
        upstream's to change, so this must still work if it ever isn't."""
        body = _csv_bytes(_good_rows(fetcher.MIN_ROWS + 5))
        self.assertEqual(self._run_download(gzip.compress(body)), body)

    def test_plain_csv_release_still_works(self):
        body = _csv_bytes(_good_rows(fetcher.MIN_ROWS + 5))
        self.assertEqual(self._run_download(body), body)

    def test_streaming_holds_no_whole_file_in_memory(self):
        import inspect
        sig = inspect.signature(fetcher._download_to)
        self.assertIn("destination", sig.parameters)
        self.assertIn(str(sig.return_annotation), ("None", "<class 'NoneType'>"))
        self.assertLessEqual(fetcher._CHUNK, 8 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
