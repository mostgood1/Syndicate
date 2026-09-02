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

import json
import os
import tempfile
import time
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


def _hist(stamp: str, line: float) -> dict:
    return {"captured_at": stamp, "timestamp": stamp, "line": line}


def _entry(stamp: str, line: float, previous: float) -> dict:
    """An odds_history entry, shaped like the live one: a capped history list
    PLUS scalars DERIVED from consecutive points."""
    return {
        "history": [_hist(stamp, line)],
        "is_live": False,
        "last_line": line,
        "previous_line": previous,
        "last_odds": line,
        "last_snapshot_ts": stamp,
        "delta": line - previous,
        "movement": "up" if line > previous else "down",
        "last_updated": stamp,
    }


def _doc(markets: dict, updated_at: str) -> dict:
    return {"schema_version": 1, "sport": "soccer", "shard_key": "2026-09-05",
            "date": "2026-09-01", "updated_at": updated_at, "history_limit": 20,
            "markets": markets}


EARLY = "2026-09-01T18:00:00+00:00"
LATE = "2026-09-01T19:00:00+00:00"
LATEST = "2026-09-01T20:00:00+00:00"


class OddsHistoryMergeTests(unittest.TestCase):
    """`soccer_source/tracking/odds_history/<date>.json` is a SINGLE JSON
    document, so the line-union above would concatenate two documents and
    destroy both. Measured 2026-09-01: refresh-worker vs live-odds-worker,
    ALLOWED_WITH_WARNING at ratio ~0.79 — 43.9MB to 34.8MB, several times an
    hour, still live after the append-only fix shipped."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.target = self.root / "target.json"
        self.incoming = self.root / "incoming.json"
        # `_merge_odds_history_publish` takes the SERVICE-WIDE admission lock,
        # which lives at data_root() -- point it at the temp dir so tests never
        # touch the real one and never leak a lock between cases.
        self._patch = patch.object(ops, "data_root", return_value=self.root)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _merge(self, target_doc: dict, incoming_doc: dict) -> dict:
        self.target.write_text(json.dumps(target_doc), encoding="utf-8")
        self.incoming.write_text(json.dumps(incoming_doc), encoding="utf-8")
        return ops._merge_odds_history_publish(self.target, self.incoming)

    def _stored(self) -> dict:
        return json.loads(self.target.read_text(encoding="utf-8"))

    def test_a_market_only_the_existing_copy_has_SURVIVES(self) -> None:
        """THE REGRESSION. Today that market is destroyed on every publish."""
        result = self._merge(
            _doc({"only_mine": _entry(EARLY, 2.0, 1.0)}, EARLY),
            _doc({"only_theirs": _entry(LATE, 3.0, 2.0)}, LATE),
        )
        self.assertTrue(result["merged"])
        self.assertEqual(sorted(self._stored()["markets"]), ["only_mine", "only_theirs"])
        self.assertEqual(result["added"], 1)

    def test_the_newer_entry_wins_for_a_shared_key(self) -> None:
        result = self._merge(
            _doc({"k": _entry(EARLY, 2.0, 1.0)}, EARLY),
            _doc({"k": _entry(LATE, 5.0, 4.0)}, LATE),
        )
        self.assertEqual(result["replaced_by_newer"], 1)
        self.assertEqual(self._stored()["markets"]["k"]["last_line"], 5.0)

    def test_a_STALER_incoming_does_not_overwrite_a_newer_existing(self) -> None:
        """Strictly better than the replace it removes: today the incoming
        always wins, even when it is the older of the two copies."""
        result = self._merge(
            _doc({"k": _entry(LATEST, 9.0, 8.0)}, LATEST),
            _doc({"k": _entry(EARLY, 2.0, 1.0)}, EARLY),
        )
        self.assertEqual(result["kept_existing_newer"], 1)
        self.assertEqual(self._stored()["markets"]["k"]["last_line"], 9.0)

    def test_entries_are_never_FIELD_MIXED(self) -> None:
        """The safety property. Each entry's scalars (previous_line, delta,
        movement) are derived from its OWN history; splicing one entry's history
        onto another's scalars publishes a self-inconsistent entry that nothing
        downstream could detect."""
        winner = _entry(LATE, 5.0, 4.0)
        self._merge(_doc({"k": _entry(EARLY, 2.0, 1.0)}, EARLY), _doc({"k": winner}, LATE))
        self.assertEqual(self._stored()["markets"]["k"], winner, "entry must arrive intact")

    def test_updated_at_only_moves_forward(self) -> None:
        self._merge(_doc({"k": _entry(LATEST, 9.0, 8.0)}, LATEST),
                    _doc({"k": _entry(EARLY, 2.0, 1.0)}, EARLY))
        self.assertEqual(self._stored()["updated_at"], LATEST)

    def test_an_unrecognised_shape_is_REPLACED_not_merged(self) -> None:
        """Guessing a shape is how a merge corrupts something it was never meant
        to touch. Unknown falls back to today's behaviour."""
        for bad in ({"schema_version": 2, "markets": {}}, {"markets": "not-a-dict"}, {"nope": 1}, []):
            self.target.write_text(json.dumps(_doc({"k": _entry(EARLY, 2.0, 1.0)}, EARLY)), encoding="utf-8")
            self.incoming.write_text(json.dumps(bad), encoding="utf-8")
            result = ops._merge_odds_history_publish(self.target, self.incoming)
            self.assertFalse(result["merged"], bad)
            self.assertIn("shape_gate", result["error"])

    def test_unparseable_input_falls_back_rather_than_raising(self) -> None:
        self.target.write_text("{not json", encoding="utf-8")
        self.incoming.write_text(json.dumps(_doc({}, EARLY)), encoding="utf-8")
        result = ops._merge_odds_history_publish(self.target, self.incoming)
        self.assertFalse(result["merged"])
        self.assertIn("parse_failed", result["error"])

    def test_the_size_cap_refuses_rather_than_risking_the_receiver(self) -> None:
        """Measured 2.5x parse cost on the real 39.6MB shard (97MB resident).
        Web is 2Gi with 8 gunicorn slots and a documented request-path OOM
        history, so a merge that could OOM the receiver would be worse than the
        clobber it fixes."""
        self.target.write_text(json.dumps(_doc({}, EARLY)), encoding="utf-8")
        self.incoming.write_text(json.dumps(_doc({}, EARLY)), encoding="utf-8")
        with patch.object(ops, "_ODDS_HISTORY_MERGE_MAX_INPUT_BYTES", 1):
            result = ops._merge_odds_history_publish(self.target, self.incoming)
        self.assertFalse(result["merged"])
        self.assertIn("over_size_cap", result["error"])

    def test_no_merge_temp_files_are_left_behind(self) -> None:
        self._merge(_doc({"a": _entry(EARLY, 1.0, 1.0)}, EARLY),
                    _doc({"b": _entry(LATE, 2.0, 1.0)}, LATE))
        self.assertEqual([p.name for p in self.root.glob("*.merge")], [])


class OddsHistoryMergeAdmissionTests(unittest.TestCase):
    """The cap and the lock, both of which exist because of MEASURED memory and
    both of which got their first version wrong.

    The cap was sized on the 39.6MB soccer shard, and MLB's real pair is
    109,448,725 B combined — so the first live publish logged
    `over_size_cap: 109448725 > 104857600` and the merge was INERT on the
    biggest shards. `test_the_cap_covers_the_real_mlb_pair` pins that.
    """

    OBSERVED_MLB_COMBINED_BYTES = 109_448_725

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.target = self.root / "t.json"
        self.incoming = self.root / "i.json"
        self.target.write_text(json.dumps(_doc({"a": _entry(EARLY, 1.0, 1.0)}, EARLY)), encoding="utf-8")
        self.incoming.write_text(json.dumps(_doc({"b": _entry(LATE, 2.0, 1.0)}, LATE)), encoding="utf-8")
        # the admission lock is SERVICE-WIDE, so it lives at data_root()
        self._patch = patch.object(ops, "data_root", return_value=self.root)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def test_the_cap_covers_the_real_mlb_pair(self) -> None:
        """A regression on the CONSTANT. Measured 3.13x peak/input on the MLB
        shard, so this cap implies ~525MB worst case, admitted one at a time."""
        self.assertGreater(ops._ODDS_HISTORY_MERGE_MAX_INPUT_BYTES,
                           self.OBSERVED_MLB_COMBINED_BYTES,
                           "the cap must not exclude the shards that clobber worst")

    def test_the_lock_admits_one_and_refuses_the_second(self) -> None:
        first = ops._odds_history_merge_lock(self.target)
        self.assertIsNotNone(first)
        self.assertIsNone(ops._odds_history_merge_lock(self.target),
                          "a second worker must not merge concurrently")
        first.unlink()
        self.assertIsNotNone(ops._odds_history_merge_lock(self.target))

    def test_the_lock_is_SERVICE_WIDE_not_per_directory(self) -> None:
        """The tracking shard and its artifacts twin live in DIFFERENT
        directories and were observed publishing 2 SECONDS apart. A
        per-directory lock would have let exactly that pair run concurrently --
        the one case it exists to bound."""
        tracking = self.root / "mlb_source/tracking/odds_history/2026-09-01.json"
        twin = self.root / "mlb_source/artifacts/mlb/odds_history/2026-09-01.json"
        for path in (tracking, twin):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        held = ops._odds_history_merge_lock(tracking)
        self.assertIsNotNone(held)
        try:
            self.assertIsNone(ops._odds_history_merge_lock(twin),
                              "the twin must be blocked by the SAME lock")
        finally:
            held.unlink()

    def test_a_busy_lock_falls_back_instead_of_raising(self) -> None:
        held = ops._odds_history_merge_lock(self.target)
        try:
            result = ops._merge_odds_history_publish(self.target, self.incoming)
        finally:
            held.unlink()
        self.assertFalse(result["merged"])
        self.assertIn("merge_busy", result["error"])
        # and the target is untouched -- the caller does the plain replace
        self.assertEqual(sorted(json.loads(self.target.read_text(encoding="utf-8"))["markets"]), ["a"])

    def test_the_lock_is_released_after_a_successful_merge(self) -> None:
        result = ops._merge_odds_history_publish(self.target, self.incoming)
        self.assertTrue(result["merged"])
        self.assertEqual(list(self.root.glob("*.lock")), [], "lock leaked after success")

    def test_the_lock_is_released_after_a_FAILED_merge(self) -> None:
        """A leaked lock would disable merging for everything in this directory
        until the staleness timeout — worse than the bug it guards."""
        self.incoming.write_text("{not json", encoding="utf-8")
        result = ops._merge_odds_history_publish(self.target, self.incoming)
        self.assertFalse(result["merged"])
        self.assertEqual(list(self.root.glob("*.lock")), [], "lock leaked after failure")

    def test_a_stale_lock_is_broken(self) -> None:
        """A worker killed mid-merge must not disable merging forever."""
        stale = ops._odds_history_merge_lock(self.target)
        old = time.time() - ops._ODDS_HISTORY_MERGE_LOCK_STALE_SECONDS - 60
        os.utime(stale, (old, old))
        self.assertIsNotNone(ops._odds_history_merge_lock(self.target),
                             "a stale lock must be broken, not honoured forever")

    def test_a_fresh_lock_is_NOT_broken(self) -> None:
        held = ops._odds_history_merge_lock(self.target)
        try:
            self.assertIsNone(ops._odds_history_merge_lock(self.target))
        finally:
            held.unlink()


class DivergenceGuardTests(unittest.TestCase):
    """`#488`'s shrink guard recorded a publisher whose publish it was about to
    REFUSE, which made the refusal self-defeating. Measured 2026-09-01 on
    `ncaaf_source/tracking/book_quotes/2026-09-05.jsonl`:

        22:01:15  publisher=live-odds-worker  last=refresh-worker    REFUSED
        22:05:03  publisher=live-odds-worker  last=live-odds-worker  ALLOWED

    9.2MB replaced by 5.2MB four minutes later. The guard DELAYED the clobber by
    one cycle while logging a REFUSED line that reads like a save.
    """

    PATH = "ncaaf_source/tracking/book_quotes/2026-09-05.jsonl"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        target = self.root / self.PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 9_229_230)          # the real existing size
        self._patch = patch.object(ops, "data_root", return_value=self.root)
        self._patch.start()
        ops._PUBLISH_LAST_PUBLISHER.pop(self.PATH, None)
        ops._PUBLISH_CONSECUTIVE_REFUSALS.pop(self.PATH, None)

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()
        ops._PUBLISH_LAST_PUBLISHER.pop(self.PATH, None)
        ops._PUBLISH_CONSECUTIVE_REFUSALS.pop(self.PATH, None)

    SMALL = 5_159_915                                  # the real incoming size

    def test_a_refusal_does_not_become_permission_next_cycle(self) -> None:
        """THE REGRESSION, replaying the measured two-cycle sequence."""
        ops._PUBLISH_LAST_PUBLISHER[self.PATH] = "refresh-worker"
        first, marker = ops._publish_divergence_verdict(self.PATH, self.SMALL, "live-odds-worker")
        self.assertTrue(first, "a cross-publisher shrink must be refused")
        self.assertIn("verdict=REFUSED", marker)

        second, marker2 = ops._publish_divergence_verdict(self.PATH, self.SMALL, "live-odds-worker")
        self.assertTrue(second, "the SECOND attempt must still be refused -- this is the bug")
        self.assertIn("verdict=REFUSED", marker2)

    def test_a_refused_publisher_never_takes_the_last_publisher_slot(self) -> None:
        ops._PUBLISH_LAST_PUBLISHER[self.PATH] = "refresh-worker"
        ops._publish_divergence_verdict(self.PATH, self.SMALL, "live-odds-worker")
        self.assertEqual(ops._PUBLISH_LAST_PUBLISHER[self.PATH], "refresh-worker",
                         "a refused attempt did not publish, so it is not the last publisher")

    def test_consecutive_refusals_are_counted_so_a_permanent_block_is_visible(self) -> None:
        """A path refused over and over is two writers fighting; without the
        count that looks identical to a one-off."""
        ops._PUBLISH_LAST_PUBLISHER[self.PATH] = "refresh-worker"
        for expected in (1, 2, 3):
            _, marker = ops._publish_divergence_verdict(self.PATH, self.SMALL, "live-odds-worker")
            self.assertIn(f"consecutive_refusals={expected}", marker)

    def test_an_allowed_publish_clears_the_streak(self) -> None:
        ops._PUBLISH_LAST_PUBLISHER[self.PATH] = "refresh-worker"
        ops._publish_divergence_verdict(self.PATH, self.SMALL, "live-odds-worker")
        self.assertEqual(ops._PUBLISH_CONSECUTIVE_REFUSALS.get(self.PATH), 1)
        ops._publish_divergence_verdict(self.PATH, self.SMALL, "refresh-worker")
        self.assertNotIn(self.PATH, ops._PUBLISH_CONSECUTIVE_REFUSALS)

    def test_a_publisher_shrinking_its_OWN_artifact_is_still_allowed(self) -> None:
        """Retention pruning. `#488` is explicit that refusing this would break
        real writes -- the signature of divergence is a shrink from a DIFFERENT
        publisher."""
        ops._PUBLISH_LAST_PUBLISHER[self.PATH] = "refresh-worker"
        refuse, marker = ops._publish_divergence_verdict(self.PATH, self.SMALL, "refresh-worker")
        self.assertFalse(refuse)
        self.assertIn("verdict=ALLOWED_WITH_WARNING", marker)

    def test_a_non_shrinking_publish_still_records_the_publisher(self) -> None:
        """The ordinary path must keep working: `last` has to be maintained or
        the guard can never detect a cross-publisher shrink at all."""
        refuse, marker = ops._publish_divergence_verdict(self.PATH, 9_229_230, "refresh-worker")
        self.assertFalse(refuse)
        self.assertIsNone(marker)
        self.assertEqual(ops._PUBLISH_LAST_PUBLISHER[self.PATH], "refresh-worker")

    def test_an_unknown_publisher_is_allowed_with_a_marker_not_refused(self) -> None:
        """`#488`: an older sender omits the header, and mapping absent onto
        'same publisher' would silence exactly what this exists to catch."""
        ops._PUBLISH_LAST_PUBLISHER[self.PATH] = "refresh-worker"
        refuse, marker = ops._publish_divergence_verdict(self.PATH, self.SMALL, "")
        self.assertFalse(refuse)
        self.assertIn("publisher=UNKNOWN", marker)
        self.assertIn("verdict=ALLOWED_WITH_WARNING", marker)


class MergeDispatcherTests(unittest.TestCase):
    """ONE dispatcher, because there are TWO receive forms. A family merged by
    one transport and replaced by the other would clobber on exactly the
    transport nobody was watching."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.target = self.root / "t"
        self.incoming = self.root / "i"
        self.target.write_text("{}", encoding="utf-8")
        self.incoming.write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_a_first_write_never_merges(self) -> None:
        self.target.unlink()
        self.assertIsNone(ops._merge_published_artifact(BOOK_QUOTES, self.target, self.incoming))

    def test_an_unmergeable_family_returns_None(self) -> None:
        self.assertIsNone(ops._merge_published_artifact(
            "reports/intelligence/clv_openings/2026-09-01.jsonl", self.target, self.incoming))
        self.assertIsNone(ops._merge_published_artifact(STATE_SIDECAR, self.target, self.incoming))

    def test_it_routes_each_family_to_its_own_merge(self) -> None:
        with patch.object(ops, "_merge_append_only_publish",
                          return_value={"merged": True, "which": "lines"}) as lines, \
             patch.object(ops, "_merge_odds_history_publish",
                          return_value={"merged": True, "which": "json"}) as js:
            self.assertEqual(ops._merge_published_artifact(
                BOOK_QUOTES, self.target, self.incoming)["which"], "lines")
            self.assertEqual(ops._merge_published_artifact(
                "soccer_source/tracking/odds_history/2026-09-05.json",
                self.target, self.incoming)["which"], "json")
        self.assertEqual((lines.call_count, js.call_count), (1, 1))


if __name__ == "__main__":
    unittest.main()
