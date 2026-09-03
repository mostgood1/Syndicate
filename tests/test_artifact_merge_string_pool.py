"""The string pool that shrinks an `odds_history` merge (`#632`).

WHY IT EXISTS. The peak a merge pays is the PARSED form, not the file. Measured
on a document rebuilt from real production entries at the scale of the largest
shard actually merged in production (56.7 MB / 4,021 markets):

    interpreter                  29.9 MB
    file as bytes               +67.8 MB
    decoded to str              +67.7 MB
    PARSED                     +187.7 MB     <- 2.76x the file, and the real cost
    both documents parsed       403.9 MB
    merge peak (child RSS)      472.0 MB

Reading bytes rather than str saves nothing -- they are the same size. What
works is that CPython's decoder memoizes object KEYS within a parse but never
VALUES, and these documents repeat a tiny set of timestamps and labels across
thousands of markets: the whole 4,021-market document holds **279 distinct
strings**. Sharing them took the parsed form to 85.8 MB and the merge peak to
**268.5 MB, a 43% reduction**, with BYTE-IDENTICAL output (sha256 equal).

The tests below lock in the two things that make it safe rather than merely
smaller: it must not change what is parsed, and the pool must not outlive the
call.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from syndicate.features.shared import artifact_merge as am


class StringPoolLoaderTests(unittest.TestCase):

    def test_equal_string_values_become_THE_SAME_object(self) -> None:
        """The mechanism. Without this the parsed form is ~2.2x larger."""
        load, pool = am._string_pool_loader()
        doc = load('{"a": "2026-09-01T00:00:00+00:00", "b": "2026-09-01T00:00:00+00:00"}')

        self.assertEqual(doc["a"], doc["b"])
        self.assertIs(doc["a"], doc["b"], "equal values must be shared, not copied")
        self.assertEqual(len(pool), 1)

    def test_sharing_reaches_values_nested_in_lists_of_objects(self) -> None:
        """`history` is a LIST of dicts and is where the repetition actually is,
        so a hook that only reached top-level values would save nothing."""
        load, _pool = am._string_pool_loader()
        doc = load('{"markets": {"k": {"history": [{"sport": "mlb"}, {"sport": "mlb"}]}}}')

        first, second = doc["markets"]["k"]["history"]
        self.assertIs(first["sport"], second["sport"])

    def test_the_pool_is_shared_ACROSS_documents_from_one_loader(self) -> None:
        """A merge parses two documents that repeat each other's strings almost
        exactly -- that is why so many merges add nothing -- so the second parse
        should mostly hit the pool."""
        load, pool = am._string_pool_loader()
        a = load('{"x": "shared"}')
        b = load('{"y": "shared"}')

        self.assertIs(a["x"], b["y"])
        self.assertEqual(len(pool), 1)

    def test_a_fresh_loader_does_NOT_inherit_a_previous_pool(self) -> None:
        """Per-merge, never global. A module-level pool would accumulate every
        string this process ever parsed -- a leak on the service this change
        exists to protect."""
        _load_a, pool_a = am._string_pool_loader()
        load_b, pool_b = am._string_pool_loader()
        load_b('{"x": "only-in-b"}')

        self.assertEqual(len(pool_a), 0)
        self.assertEqual(len(pool_b), 1)
        self.assertIsNot(pool_a, pool_b)

    def test_non_string_values_are_passed_through_unchanged(self) -> None:
        load, pool = am._string_pool_loader()
        doc = load('{"i": 3, "f": 1.5, "t": true, "n": null, "l": [1, 2], "o": {"k": 9}}')

        self.assertEqual(doc, {"i": 3, "f": 1.5, "t": True, "n": None,
                               "l": [1, 2], "o": {"k": 9}})
        self.assertEqual(len(pool), 0, "only strings belong in the pool")

    def test_the_parsed_RESULT_is_equal_to_a_plain_parse(self) -> None:
        """The whole safety claim in one assertion: sharing changes identity,
        never value."""
        text = json.dumps({
            "schema_version": 1, "markets": {
                "a": {"history": [{"t": "s1", "v": 1}], "last_line": 2.5},
                "b": {"history": [{"t": "s1", "v": 2}], "last_line": None},
            }})
        load, _pool = am._string_pool_loader()

        self.assertEqual(load(text), json.loads(text))

    def test_duplicate_keys_resolve_the_SAME_WAY_as_a_plain_parse(self) -> None:
        """`object_pairs_hook` sees raw pairs, so a hook that built its dict
        differently could silently change which duplicate wins."""
        text = '{"k": "first", "k": "second"}'
        load, _pool = am._string_pool_loader()

        self.assertEqual(load(text), json.loads(text))
        self.assertEqual(load(text)["k"], "second")


class MergeStillMergesTests(unittest.TestCase):
    """The pool must not disturb the union it was added to speed up."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _doc(markets, updated_at):
        return {"schema_version": 1, "sport": "mlb", "shard_key": "2026-09-01",
                "date": "2026-09-01", "updated_at": updated_at,
                "history_limit": 20, "markets": markets}

    @staticmethod
    def _entry(stamp, line):
        return {"history": [{"captured_at": stamp, "line": line}],
                "last_line": line, "last_updated": stamp}

    def test_a_real_union_keeps_both_sides_and_the_newer_entry_wins(self) -> None:
        early, late = "2026-09-01T18:00:00+00:00", "2026-09-01T19:00:00+00:00"
        target = self.root / "t.json"
        incoming = self.root / "i.json"
        target.write_text(json.dumps(self._doc(
            {"only_mine": self._entry(early, 1.0),
             "both": self._entry(early, 1.0)}, early)), encoding="utf-8")
        incoming.write_text(json.dumps(self._doc(
            {"only_theirs": self._entry(late, 3.0),
             "both": self._entry(late, 2.0)}, late)), encoding="utf-8")

        result = am.merge_odds_history(target, incoming, root=self.root)

        self.assertTrue(result["merged"], result)
        stored = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(sorted(stored["markets"]), ["both", "only_mine", "only_theirs"],
                         "the union is the point -- no key may be lost")
        self.assertEqual(stored["markets"]["both"]["last_line"], 2.0,
                         "the newer entry must win")
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["replaced_by_newer"], 1)


if __name__ == "__main__":
    unittest.main()
