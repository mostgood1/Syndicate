"""Merge-on-receive for append-only artifacts — `#630`.

THE DEFECT THIS FIXES, measured 2026-09-01. Two services each keep their own
copy of `<sport>_source/tracking/book_quotes/<date>.jsonl`, append only their
own rows to it, and then publish the WHOLE FILE. Web kept whichever published
last. A refetch an hour later had LOST 1,318 exchange rows and gained none — a
clean tail truncation — while sportsbook rows gained an entire new hour.

`test_the_measured_clobber_no_longer_happens` is the regression: it replays that
exact shape and asserts both writers survive.

TWO INVARIANTS CARRY THE REST OF THE DESIGN, and each has tests because each
would fail silently:

  * THE EXISTING FILE STAYS A BYTE PREFIX. `pull_streamed_artifact` fetches
    these families by HTTP Range from the worker's local size, so any edit
    before that offset splices two different files together on the worker.
  * NON-APPEND-ONLY FAMILIES STILL REPLACE. Merging a rebuilt board or the
    `.state.json` sidecar — which is a dict rewritten whole every flush — would
    concatenate two documents and corrupt them. `_is_append_only` decides, and
    it is the SAME predicate the Range pull uses.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.blueprints import ops

BOOK_QUOTES = "mlb_source/tracking/book_quotes/2026-09-01.jsonl"
STATE_SIDECAR = "mlb_source/tracking/book_quotes/2026-09-01.state.json"
TOKEN = "secret-token"


def _row(book: str, player: str, stamp: str) -> str:
    return ('{"kind":"prop","bookmaker":"%s","player_name":"%s","snapshot_ts":"%s"}'
            % (book, player, stamp))


class MergeHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.target = self.root / "target.jsonl"
        self.incoming = self.root / "incoming.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _merge(self) -> dict:
        return ops._merge_append_only_publish(self.target, self.incoming)

    def test_disjoint_writers_both_survive(self) -> None:
        self.target.write_text("a\nb\n", encoding="utf-8")
        self.incoming.write_text("c\nd\n", encoding="utf-8")
        result = self._merge()
        self.assertTrue(result["merged"])
        self.assertEqual(result["added"], 2)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "a\nb\nc\nd\n")

    def test_the_existing_file_stays_a_byte_prefix(self) -> None:
        """The Range/tail pull reads from the worker's local byte offset. If
        anything before that offset changes, the worker splices two different
        files together."""
        before = b"first\nsecond\nthird\n"
        self.target.write_bytes(before)
        self.incoming.write_text("fourth\n", encoding="utf-8")
        self._merge()
        after = self.target.read_bytes()
        self.assertTrue(after.startswith(before), "existing bytes must be untouched")
        self.assertGreater(len(after), len(before))

    def test_republishing_the_same_file_adds_nothing(self) -> None:
        """Idempotence. Every publisher sends its COMPLETE file every cycle, so
        without this the artifact would grow without bound."""
        self.target.write_text("a\nb\n", encoding="utf-8")
        self.incoming.write_text("a\nb\n", encoding="utf-8")
        result = self._merge()
        self.assertEqual(result["added"], 0)
        self.assertEqual(result["duplicates"], 2)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "a\nb\n")

    def test_only_the_genuinely_new_rows_are_added(self) -> None:
        self.target.write_text("a\nb\n", encoding="utf-8")
        self.incoming.write_text("b\nc\n", encoding="utf-8")
        result = self._merge()
        self.assertEqual((result["added"], result["duplicates"]), (1, 1))
        self.assertEqual(self.target.read_text(encoding="utf-8"), "a\nb\nc\n")

    def test_a_missing_trailing_newline_does_not_glue_two_rows(self) -> None:
        """Without the guard, 'b' and 'c' become the single unparseable 'bc'
        and BOTH rows are lost."""
        self.target.write_text("a\nb", encoding="utf-8")
        self.incoming.write_text("c\n", encoding="utf-8")
        self._merge()
        self.assertEqual(self.target.read_text(encoding="utf-8").splitlines(), ["a", "b", "c"])

    def test_blank_lines_are_not_treated_as_content(self) -> None:
        self.target.write_text("a\n\n\nb\n", encoding="utf-8")
        self.incoming.write_text("\n\n", encoding="utf-8")
        result = self._merge()
        self.assertEqual(result["added"], 0)

    def test_incoming_duplicates_collapse_against_each_other(self) -> None:
        self.target.write_text("a\n", encoding="utf-8")
        self.incoming.write_text("z\nz\nz\n", encoding="utf-8")
        result = self._merge()
        self.assertEqual((result["added"], result["duplicates"]), (1, 2))

    def test_a_failure_reports_rather_than_corrupting(self) -> None:
        self.target.write_text("a\n", encoding="utf-8")
        self.incoming.write_text("b\n", encoding="utf-8")
        with patch("shutil.copyfileobj", side_effect=OSError("disk full")):
            result = self._merge()
        self.assertFalse(result["merged"])
        self.assertIn("disk full", result["error"])
        self.assertEqual(self.target.read_text(encoding="utf-8"), "a\n",
                         "a failed merge must leave the original intact")

    def test_no_merge_temp_files_are_left_behind(self) -> None:
        self.target.write_text("a\n", encoding="utf-8")
        self.incoming.write_text("b\n", encoding="utf-8")
        self._merge()
        self.assertEqual([p.name for p in self.root.glob("*.merge")], [])


class PublishEndpointMergeTests(unittest.TestCase):
    """Both receive forms must merge. live-odds-worker is PINNED to an older
    commit and sends the ENVELOPE form, so fixing only the streamed path would
    leave the clobber live for one of the two writers that cause it."""

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._patch = patch.object(ops, "data_root", return_value=self.root)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _target(self, relative_path: str = BOOK_QUOTES) -> Path:
        return self.root / relative_path

    def _publish_envelope(self, content: str, relative_path: str = BOOK_QUOTES):
        with patch.dict(os.environ, {"ADMIN_TOKEN": TOKEN}, clear=False):
            return self.client.post(
                "/api/ops/artifacts/publish",
                json={"relative_path": relative_path, "content": content},
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

    def _publish_streamed(self, content: str, publisher: str,
                          relative_path: str = BOOK_QUOTES):
        with patch.dict(os.environ, {"ADMIN_TOKEN": TOKEN}, clear=False):
            return self.client.post(
                "/api/ops/artifacts/publish",
                data=content.encode("utf-8"),
                content_type="application/octet-stream",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "X-Artifact-Path": relative_path,
                    "X-Artifact-Publisher": publisher,
                },
            )

    def test_the_measured_clobber_no_longer_happens(self) -> None:
        """THE REGRESSION. Replays 2026-09-01: the exchange writer publishes its
        rows, then the sportsbook writer publishes a file that does not contain
        them at all — and previously that dropped every exchange row."""
        exchange = "\n".join(_row("kalshi", f"Batter{i}", "2026-09-01T21:30:00Z")
                             for i in range(5)) + "\n"
        sportsbook = "\n".join(_row("fanduel", f"Batter{i}", "2026-09-01T22:56:00Z")
                               for i in range(5)) + "\n"

        self.assertEqual(self._publish_streamed(exchange, "live-odds-worker").status_code, 200)
        response = self._publish_streamed(sportsbook, "refresh-worker")
        self.assertEqual(response.status_code, 200)

        stored = self._target().read_text(encoding="utf-8")
        self.assertEqual(stored.count("kalshi"), 5, "the exchange rows were clobbered")
        self.assertEqual(stored.count("fanduel"), 5)
        self.assertTrue(response.get_json()["merged"]["merged"])

    def test_publishing_is_commutative(self) -> None:
        """Order stops mattering — which is the whole point. Whoever publishes
        last, the result is the same union."""
        a, b = "a\nb\n", "c\nd\n"
        self._publish_streamed(a, "worker-a")
        self._publish_streamed(b, "worker-b")
        one = sorted(self._target().read_text(encoding="utf-8").split())

        self._target().unlink()
        self._publish_streamed(b, "worker-b")
        self._publish_streamed(a, "worker-a")
        two = sorted(self._target().read_text(encoding="utf-8").split())
        self.assertEqual(one, two)

    def test_the_envelope_form_merges_too(self) -> None:
        self._publish_envelope("a\nb\n")
        self._publish_envelope("c\n")
        self.assertEqual(self._target().read_text(encoding="utf-8"), "a\nb\nc\n")

    def test_the_two_forms_interoperate(self) -> None:
        """One writer pinned to the envelope form, one on the streamed form —
        which is the actual production arrangement."""
        self._publish_envelope("envelope-row\n")
        self._publish_streamed("streamed-row\n", "refresh-worker")
        stored = self._target().read_text(encoding="utf-8")
        self.assertIn("envelope-row", stored)
        self.assertIn("streamed-row", stored)

    def test_a_first_publish_is_a_plain_write(self) -> None:
        response = self._publish_streamed("a\n", "worker-a")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json().get("merged"))
        self.assertEqual(self._target().read_text(encoding="utf-8"), "a\n")

    def test_a_shrinking_publish_from_another_writer_is_no_longer_REFUSED(self) -> None:
        """The `#488` shrink guard would reject this. Under merge it must not:
        refusing would reject the publish carrying the other service's rows,
        which turns the fix off."""
        self._publish_streamed("\n".join(f"row{i}" for i in range(400)) + "\n", "worker-a")
        response = self._publish_streamed("tiny\n", "worker-b")
        self.assertEqual(response.status_code, 200)
        stored = self._target().read_text(encoding="utf-8")
        self.assertIn("tiny", stored)
        self.assertIn("row399", stored, "the larger writer's rows must survive")


class NonAppendOnlyStillReplacesTests(unittest.TestCase):
    """The dangerous direction. Merging a file that is REWRITTEN WHOLE glues two
    documents together — `_is_append_only`'s own docstring calls this out for
    the `.state.json` sidecar, which lives in the same directory."""

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._patch = patch.object(ops, "data_root", return_value=self.root)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _publish(self, content: str, relative_path: str):
        with patch.dict(os.environ, {"ADMIN_TOKEN": TOKEN}, clear=False):
            return self.client.post(
                "/api/ops/artifacts/publish",
                json={"relative_path": relative_path, "content": content},
                headers={"Authorization": f"Bearer {TOKEN}"},
            )

    def test_the_state_sidecar_is_replaced_not_merged(self) -> None:
        """It is a dict of quote-key -> [line, price, last_seen], rewritten on
        every flush. Concatenating two of them yields a file
        `read_quote_last_seen` silently returns {} for."""
        self.assertFalse(ops._is_append_only(STATE_SIDECAR))
        self._publish('{"k":1}', STATE_SIDECAR)
        self._publish('{"k":2}', STATE_SIDECAR)
        self.assertEqual((self.root / STATE_SIDECAR).read_text(encoding="utf-8"), '{"k":2}')

    def test_another_jsonl_family_still_replaces(self) -> None:
        """The sharpest version of the discrimination: `clv_openings` is
        allowlisted AND ends in `.jsonl` AND is rebuilt whole. If the rule ever
        degrades to 'ends with .jsonl' this test fails and the merge starts
        concatenating successive rebuilds of a file that is not a log."""
        path = "reports/intelligence/clv_openings/2026-09-01.jsonl"
        self.assertTrue(ops._is_append_only(BOOK_QUOTES))
        self.assertFalse(ops._is_append_only(path), "must not merge on the extension alone")

        first = self._publish("big\npayload\nhere\n", path)
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        second = self._publish("small\n", path)
        self.assertEqual(second.status_code, 200, second.get_data(as_text=True))
        self.assertEqual((self.root / path).read_text(encoding="utf-8"), "small\n")


if __name__ == "__main__":
    unittest.main()
