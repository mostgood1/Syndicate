"""`#441` — the pbp fetcher must not install a file that recreates the defect.

The guard this feeds refuses when the pbp yields zero usable plays, because then
every team rates `neutral_no_data` and all games get one league-average
projection -- which production actually served on 2026-08-13 (`margin 0.96 /
total 44.38 / home_win 0.5267` on all 16 preseason games).

So the failure these tests pin is NOT "the download failed" -- that is loud and
self-correcting. It is "the download SUCCEEDED and was garbage", which installs
silently and takes days to notice. A truncated body or an upstream schema change
that dropped `epa` both produce exactly that.
"""
from __future__ import annotations

import gzip
import io
import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scripts.fetch_nfl_pbp as fetcher


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


def _good_rows(n: int) -> list[dict]:
    return [
        {
            "season_type": "REG", "play_type": "pass", "posteam": "KC", "defteam": "BUF",
            "epa": "0.12", "week": "1", "game_id": f"g{i}", "home_team": "BUF", "away_team": "KC",
        }
        for i in range(n)
    ]


class ValidationRefusesDegenerateDownloads(unittest.TestCase):
    def test_truncated_body_is_rejected_and_leaves_the_existing_file(self):
        """THE CORE CASE. A short body must not overwrite a good file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "tracking" / "nflverse" / "pbp" / "pbp_2025.csv"
            dest.parent.mkdir(parents=True)
            dest.write_text("GOOD EXISTING FILE", encoding="utf-8")
            short = _csv_bytes(_good_rows(10))  # well under MIN_REG_PLAYS
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root), \
                 patch.object(fetcher, "_download_to", side_effect=_writer_for(short)):
                result = fetcher.fetch_season(2025, force=True, timeout=5)
            self.assertEqual(result["status"], "rejected")
            self.assertTrue(any("truncated" in p for p in result["problems"]))
            self.assertEqual(dest.read_text(encoding="utf-8"), "GOOD EXISTING FILE")

    def test_missing_epa_column_is_rejected(self):
        """An upstream schema change that drops `epa` yields all-neutral ratings.

        This is the silent one: the row COUNT is fine, so a count-only check
        would pass it straight through.
        """
        cols = tuple(c for c in fetcher.REQUIRED_COLUMNS if c != "epa")
        body = _csv_bytes(_good_rows(fetcher.MIN_REG_PLAYS + 50), columns=cols)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root), \
                 patch.object(fetcher, "_download_to", side_effect=_writer_for(body)):
                result = fetcher.fetch_season(2025, force=True, timeout=5)
            self.assertEqual(result["status"], "rejected")
            self.assertTrue(any("epa" in p for p in result["problems"]))
            self.assertFalse((root / "tracking" / "nflverse" / "pbp" / "pbp_2025.csv").exists())

    def test_a_healthy_body_is_written_atomically(self):
        body = _csv_bytes(_good_rows(fetcher.MIN_REG_PLAYS + 100))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root), \
                 patch.object(fetcher, "_download_to", side_effect=_writer_for(body)):
                result = fetcher.fetch_season(2025, force=True, timeout=5)
            dest = root / "tracking" / "nflverse" / "pbp" / "pbp_2025.csv"
            self.assertEqual(result["status"], "written")
            self.assertTrue(dest.is_file())
            self.assertGreaterEqual(result["reg_plays"], fetcher.MIN_REG_PLAYS)
            # no temp files left behind
            leftovers = [p.name for p in dest.parent.iterdir() if p.name != dest.name]
            self.assertEqual(leftovers, [])


class SeasonSelection(unittest.TestCase):
    def test_prior_season_is_fetched_by_default(self):
        """THE REASON THIS FETCHER WOULD OTHERWISE SHIP AND DO NOTHING.

        Week 1 has no current-season REG plays, so ratings come from the prior
        season. Fetching only --season would leave the guard refusing.
        """
        seen: list[int] = []

        def _fake(season, *, force, timeout):
            seen.append(season)
            return {"season": season, "status": "written", "path": "x"}

        with patch.object(fetcher, "fetch_season", side_effect=_fake):
            fetcher.main(["--season", "2026", "--json"])
        self.assertEqual(seen, [2026, 2025])

    def test_only_season_flag_narrows_it(self):
        seen: list[int] = []

        def _fake(season, *, force, timeout):
            seen.append(season)
            return {"season": season, "status": "written", "path": "x"}

        with patch.object(fetcher, "fetch_season", side_effect=_fake):
            fetcher.main(["--season", "2026", "--only-season", "--json"])
        self.assertEqual(seen, [2026])


class UnavailableSeasonIsNotAFailure(unittest.TestCase):
    def test_404_on_the_young_season_does_not_fail_the_run(self):
        """A season that has not kicked off has no release yet.

        That must not exit non-zero, or a scheduled run would alarm every day
        until September. It is only a failure if NOTHING was written.
        """
        import urllib.error

        good = _csv_bytes(_good_rows(fetcher.MIN_REG_PLAYS + 10))

        def _download(season, destination, *, timeout):
            if season == 2026:
                raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)
            Path(destination).write_bytes(good)

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
    def test_destination_uses_the_389_output_resolver_not_default_root(self):
        """`#389`: default_nfl_source_root() resolves to the ephemeral checkout on
        refresh-worker, which is where projections were written and discarded on
        every deploy. The fetcher must use the OUTPUT resolver."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mounted"
            with patch.object(fetcher, "nfl_artifact_output_root", return_value=root):
                path = fetcher._pbp_destination(2025)
        self.assertEqual(path, root / "tracking" / "nflverse" / "pbp" / "pbp_2025.csv")


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
        body = _csv_bytes(_good_rows(fetcher.MIN_REG_PLAYS + 5))
        self.assertEqual(self._run_download(gzip.compress(body)), body)

    def test_plain_csv_release_still_works(self):
        body = _csv_bytes(_good_rows(fetcher.MIN_REG_PLAYS + 5))
        self.assertEqual(self._run_download(body), body)

    def test_streaming_holds_no_whole_file_in_memory(self):
        """The reason for the rewrite: peak memory must be a chunk, not the file.

        Asserted structurally -- _download_to writes to a path and returns None,
        so there is no whole-body object for a caller to hold.
        """
        import inspect
        sig = inspect.signature(fetcher._download_to)
        # It takes a destination and returns nothing, so no caller can hold the body.
        self.assertIn("destination", sig.parameters)
        self.assertIn(str(sig.return_annotation), ("None", "<class 'NoneType'>"))
        # And the chunk size is a real bound, not a whole-file read.
        self.assertLessEqual(fetcher._CHUNK, 8 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
