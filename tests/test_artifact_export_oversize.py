"""The bulk artifact export must not let one giant file eat the whole budget.

MEASURED 2026-09-16 03:40Z (lane `web-export-timeout`), a 30-minute window on
`pattern=*2026-09-15*` against production: **133 files, 312.4 MB — 13x the 24 MB
budget — and the top 12 files were 96% of it.** The remaining 121 files came to
11.1 MB and fit inside the budget with room to spare. They are the ones the pull
exists to move; they were the ones dropped, because the accumulators
(`book_quotes` 126.53 MB, two `odds_history` at ~56 MB) are met in arbitrary walk
order and consume the budget first. A pull asking for 133 changed files received
FOUR, reported `truncated`, and nothing read that field.

Two properties are pinned here, and the second is the one that would otherwise
only show up as an outage:

1. an oversize file is SKIPPED and NAMED, so the small artifacts still arrive;
2. it is skipped even when it is FIRST, because the budget test is
   `total_bytes + size > budget and artifacts` — the `and artifacts` clause
   admits the first file at any size, which on a 2 GB instance means
   `read_text`-ing 126 MB into a dict and `jsonify`-ing it.
"""
from __future__ import annotations

import json
import os
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from syndicate.app import create_app


TOKEN = "secret-token"
# Real hot-artifact paths, so `is_exportable_artifact_relative_path` admits them
# rather than the test passing on a path the endpoint would refuse anyway.
SMALL = "soccer_source/epl/api/live_state/live_state_2026-09-15.json"
HUGE = "mlb_source/data/book_grid/book_grid_2026-09-15.json"


def _write(root: str, relative: str, payload: str) -> None:
    path = os.path.join(root, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload)


class ArtifactExportOversizeTests(TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def _export(self, tmp_dir: str, extra_env: dict | None = None) -> dict:
        env = {"ADMIN_TOKEN": TOKEN, "SYNDICATE_DATA_ROOT": tmp_dir}
        env.update(extra_env or {})
        with patch.dict(os.environ, env, clear=False):
            response = self.client.get(
                "/api/ops/artifacts/export?pattern=*2026-09-15*",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
        self.assertEqual(response.status_code, 200)
        return json.loads(response.data.decode("utf-8"))

    def test_an_oversize_file_is_skipped_and_the_small_one_still_arrives(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, SMALL, json.dumps({"league": "epl", "games": {}}))
            _write(tmp_dir, HUGE, "x" * (3 * 1024 * 1024))
            body = self._export(tmp_dir, {"SYNDICATE_ARTIFACT_EXPORT_MAX_FILE_BYTES": str(1024 * 1024)})

        self.assertIn(SMALL, body["artifacts"], "the small artifact was dropped")
        self.assertNotIn(HUGE, body["artifacts"], "the oversize file was inlined anyway")
        self.assertEqual(body["oversize_skipped"], 1)
        self.assertEqual(body["oversize_bytes"], 3 * 1024 * 1024)
        self.assertEqual([entry["path"] for entry in body["oversize"]], [HUGE])

    def test_an_oversize_file_is_skipped_even_when_it_is_the_ONLY_file(self) -> None:
        """The `and artifacts` clause admits the first file at any size.

        With nothing else in the tree the oversize file IS first, so this is the
        memory hazard in its purest form: pre-change it is read and returned.
        """
        with TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, HUGE, "x" * (3 * 1024 * 1024))
            body = self._export(tmp_dir, {"SYNDICATE_ARTIFACT_EXPORT_MAX_FILE_BYTES": str(1024 * 1024)})

        self.assertEqual(body["artifacts"], {}, "a 3MB file was inlined for being first")
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["oversize_skipped"], 1)

    def test_skipping_oversize_does_NOT_report_truncation(self) -> None:
        """`truncated` means the BUDGET stopped the walk. A capped file is a
        different event with a different remedy (stream it), and collapsing the
        two would leave a caller unable to tell which happened."""
        with TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, SMALL, json.dumps({"league": "epl"}))
            _write(tmp_dir, HUGE, "x" * (3 * 1024 * 1024))
            body = self._export(tmp_dir, {"SYNDICATE_ARTIFACT_EXPORT_MAX_FILE_BYTES": str(1024 * 1024)})

        self.assertFalse(body["truncated"])
        self.assertEqual(body["oversize_skipped"], 1)

    def test_a_file_UNDER_the_cap_is_untouched(self) -> None:
        """The cap must not become a second budget: ordinary artifacts, which is
        everything this endpoint exists for, pass through unchanged."""
        with TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, SMALL, json.dumps({"league": "epl", "games": {}}))
            body = self._export(tmp_dir, {"SYNDICATE_ARTIFACT_EXPORT_MAX_FILE_BYTES": str(8 * 1024 * 1024)})

        self.assertIn(SMALL, body["artifacts"])
        self.assertEqual(body["oversize_skipped"], 0)
        self.assertEqual(body["oversize"], [])

    def test_the_cap_floor_refuses_to_starve_ordinary_artifacts(self) -> None:
        """A cap below 1 MB would skip normal board artifacts. `max(1MB, ...)`
        is the guard, and this pins it against a hostile env value."""
        with TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, SMALL, "y" * (600 * 1024))
            body = self._export(tmp_dir, {"SYNDICATE_ARTIFACT_EXPORT_MAX_FILE_BYTES": "1024"})

        self.assertIn(SMALL, body["artifacts"], "a 600KB artifact was skipped by a 1KB cap")
        self.assertEqual(body["oversize_skipped"], 0)

    def test_the_inventory_still_LISTS_an_oversize_file(self) -> None:
        """`names_only=1` is how a caller discovers what to stream. Hiding the
        capped files there would make them unreachable rather than merely
        un-inlined."""
        with TemporaryDirectory() as tmp_dir:
            _write(tmp_dir, HUGE, "x" * (3 * 1024 * 1024))
            env = {
                "ADMIN_TOKEN": TOKEN,
                "SYNDICATE_DATA_ROOT": tmp_dir,
                "SYNDICATE_ARTIFACT_EXPORT_MAX_FILE_BYTES": str(1024 * 1024),
            }
            with patch.dict(os.environ, env, clear=False):
                response = self.client.get(
                    "/api/ops/artifacts/export?pattern=*2026-09-15*&names_only=1",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )
            body = json.loads(response.data.decode("utf-8"))

        self.assertIn(HUGE, body["artifacts"], "the cap hid the file from the inventory too")


# ---------------------------------------------------------------------------
# The BUDGET, raised 24 MB -> 48 MB (2026-09-16, user decision).
#
# After the per-file cap shipped, refresh-worker's `*2026-09-16*` pull still
# reported `truncated=True` at 77 files with ZERO oversize skips: ordinary
# artifacts under the cap filling 24 MB on their own. Measured at the cap's own
# boundary, a 30-minute window carried 36.65 MB and the 2-hour clamp 37.30 MB.
# ---------------------------------------------------------------------------

# Four real hot-artifact paths, each a separate league, so the export admits all
# of them and the test is about the budget rather than the allowlist.
_UNDER_CAP_PATHS = [
    f"soccer_source/{league}/api/live_state/live_state_2026-09-15.json"
    for league in ("epl", "la_liga", "serie_a", "bundesliga")
]


class ArtifactExportBudgetTests(TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_the_default_budget_is_48_MB(self) -> None:
        """Pinned directly, with the override ABSENT -- which is how all three
        services run (checked 2026-09-16 on the single-key endpoint)."""
        from syndicate.blueprints.ops import _artifact_export_budget_bytes

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYNDICATE_ARTIFACT_EXPORT_MAX_BYTES", None)
            self.assertEqual(_artifact_export_budget_bytes(), 48 * 1024 * 1024)

    def test_a_set_between_24_and_48_MB_is_delivered_WHOLE(self) -> None:
        """The behaviour the raise is for: 28 MB of under-cap files, which the
        old budget truncated, now arrives complete with `truncated` false.

        Each file is 7 MB -- under the 8 MB per-file cap, so this cannot pass by
        way of the cap skipping them."""
        seven_mb = "z" * (7 * 1024 * 1024)
        with TemporaryDirectory() as tmp_dir:
            for relative in _UNDER_CAP_PATHS:
                _write(tmp_dir, relative, seven_mb)
            env = {"ADMIN_TOKEN": TOKEN, "SYNDICATE_DATA_ROOT": tmp_dir}
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("SYNDICATE_ARTIFACT_EXPORT_MAX_BYTES", None)
                os.environ.pop("SYNDICATE_ARTIFACT_EXPORT_MAX_FILE_BYTES", None)
                response = self.client.get(
                    "/api/ops/artifacts/export?pattern=*2026-09-15*",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )
            body = json.loads(response.data.decode("utf-8"))

        self.assertFalse(body["truncated"], "28 MB of under-cap files was still truncated")
        self.assertEqual(sorted(body["artifacts"]), sorted(_UNDER_CAP_PATHS))
        self.assertEqual(body["oversize_skipped"], 0, "the cap, not the budget, decided this")


# ---------------------------------------------------------------------------
# The RESUME CURSOR (2026-09-16, "fix the watermark so it stops skipping
# truncated files"). A `since` read is filled oldest-first and reports
# `next_since`, the mtime of the first file that did not fit. The pull records
# that instead of its own start time. The property that matters is the last
# one below: chaining the cursor delivers EVERY file, with no gap.
# ---------------------------------------------------------------------------

_BASE_MTIME = 1_700_000_000.0


def _league_path(i: int) -> str:
    # One real hot-artifact family, a distinct league directory per file, so every
    # path is admitted by the allowlist and the test is about ORDER and CURSOR.
    return f"soccer_source/league{i}/api/live_state/live_state_2026-09-15.json"


class ArtifactExportResumeCursorTests(TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def _tree(self, tmp_dir: str, count: int, *, same_mtime: bool = False) -> list[str]:
        paths = []
        for i in range(count):
            relative = _league_path(i)
            _write(tmp_dir, relative, "q" * (700 * 1024))
            mtime = _BASE_MTIME if same_mtime else _BASE_MTIME + (count - i) * 10.0
            os.utime(os.path.join(tmp_dir, *relative.split("/")), (mtime, mtime))
            paths.append(relative)
        return paths

    def _read(self, tmp_dir: str, since: float, budget: int | None = 1024 * 1024) -> dict:
        query = f"/api/ops/artifacts/export?pattern=*2026-09-15*&since={since}"
        if budget is not None:
            query += f"&budget_bytes={budget}"
        env = {"ADMIN_TOKEN": TOKEN, "SYNDICATE_DATA_ROOT": tmp_dir}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("SYNDICATE_ARTIFACT_EXPORT_MAX_BYTES", None)
            response = self.client.get(query, headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(response.status_code, 200)
        return json.loads(response.data.decode("utf-8"))

    def test_a_since_read_is_filled_OLDEST_FIRST_and_names_where_to_resume(self) -> None:
        """Files are written newest-first on purpose, so walk order and mtime order
        disagree and the test cannot pass by accident of directory listing."""
        with TemporaryDirectory() as tmp_dir:
            self._tree(tmp_dir, 3)
            body = self._read(tmp_dir, since=_BASE_MTIME - 1.0)
        oldest = _league_path(2)
        self.assertTrue(body["truncated"])
        self.assertEqual(list(body["artifacts"]), [oldest], "the budget was not spent on the OLDEST file")
        self.assertEqual(body["next_since"], _BASE_MTIME + 20.0, "the cursor is not the first undelivered mtime")

    def test_chaining_next_since_delivers_EVERY_file_with_no_gap(self) -> None:
        """THE PROPERTY. Pre-fix, a pull recorded its start time after the first
        truncated read and the other four files were never requested again."""
        with TemporaryDirectory() as tmp_dir:
            everything = set(self._tree(tmp_dir, 5))
            delivered: set[str] = set()
            since, reads = _BASE_MTIME - 1.0, 0
            while True:
                body = self._read(tmp_dir, since=since)
                delivered.update(body["artifacts"])
                reads += 1
                if not body["truncated"]:
                    break
                self.assertIsNotNone(body["next_since"], "a truncated since-read gave no cursor")
                self.assertGreater(body["next_since"], since, "the cursor did not advance")
                since = body["next_since"]
                self.assertLess(reads, 20, "the cursor never reached the end")
        self.assertEqual(delivered, everything, f"files skipped: {sorted(everything - delivered)}")
        # ASSERT THE BRANCH RAN, NOT ONLY THE OUTCOME. The first version of this
        # test ended at the line above and PASSED ON THE PRE-CHANGE CODE: without
        # the `budget_bytes` override the budget stayed 48 MB, all five 700 KB
        # files fit one read, the loop exited at once, and "every file arrived"
        # held without a cursor ever being issued. At a 1 MB budget each read can
        # carry exactly one 700 KB file, so the chain must take exactly five reads.
        self.assertEqual(reads, 5, f"the cursor path did not run as designed ({reads} reads)")

    def test_a_read_WITHOUT_since_keeps_its_old_behaviour_and_no_cursor(self) -> None:
        """The no-`since` caller is the backup workflow, which never asked for a
        cursor and must not have its file selection silently reordered."""
        with TemporaryDirectory() as tmp_dir:
            self._tree(tmp_dir, 3)
            env = {"ADMIN_TOKEN": TOKEN, "SYNDICATE_DATA_ROOT": tmp_dir}
            with patch.dict(os.environ, env, clear=False):
                response = self.client.get(
                    "/api/ops/artifacts/export?pattern=*2026-09-15*&budget_bytes=1048576",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )
            body = json.loads(response.data.decode("utf-8"))
        self.assertTrue(body["truncated"])
        self.assertIsNone(body["next_since"])

    def test_the_budget_override_can_only_LOWER_the_budget(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            self._tree(tmp_dir, 1)
            body = self._read(tmp_dir, since=_BASE_MTIME - 1.0, budget=10 * 1024 * 1024 * 1024)
        self.assertEqual(body["budget_bytes"], 48 * 1024 * 1024, "a request raised the memory ceiling")

    def test_a_resume_that_cannot_progress_WITHHOLDS_the_cursor(self) -> None:
        """Every file at exactly the request's own `since`: resuming would return the
        identical response forever. The cursor is withheld so the pull HOLDS -- a
        stall that is logged, never a skip."""
        with TemporaryDirectory() as tmp_dir:
            self._tree(tmp_dir, 3, same_mtime=True)
            body = self._read(tmp_dir, since=_BASE_MTIME)
        self.assertTrue(body["truncated"])
        self.assertIsNone(body["next_since"])
