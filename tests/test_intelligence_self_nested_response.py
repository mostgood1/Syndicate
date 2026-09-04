"""The `/api/intelligence/query` payload stops carrying a copy of itself (`#632`).

MEASURED on the live endpoint 2026-09-04, one call:

    served response                                   67.19 MB on the wire
      response.response  (the payload's own copy)       36.42 MB   <- 50%
      top_opportunities == recommendations               6.44 MB each
      board_contract    == boardContract                 5.86 MB each
      ranked_all / by_sport                              5.86 MB each

Dropping the self-copy took the serialised payload **72.85 MB -> 36.42 MB, a
50.0% cut**, and this route was the largest per-request allocator the fixed
profiler found (~82 MB/call, replicated on both workers).

WHY IT IS DROPPED AT SERIALISATION AND NOT AT CONSTRUCTION. Five sites in
`blueprints/intelligence.py` do `payload.setdefault("response", dict(payload))`
and then read `payload["response"]` straight back to set `LAST_RESULT`. The
nesting is load-bearing while the response is being built. It is only redundant
by the time it is about to be encoded, and that is where it is removed.

WHY IT IS SAFE, AND WHY THE CHECK IS AN IDENTITY TEST. `dict(payload)` is a
SHALLOW copy, so the inner mapping's values are THE SAME OBJECTS as the outer's.
Redundancy is therefore `outer[key] is inner[key]` -- O(1) per key, impossible to
fool, and the only affordable option: serialising 36 MB twice to compare it would
cost more than the saving. Anything not provably identical is kept, so the
failure mode is "no saving", never "wrong data".

THE CLIENT ALREADY TOLERATES THE ABSENCE, which is what made this a payload
change and not a client change:
  * `intelligence.html:1517` -- `unwrapVersionedIntelligenceResponse(
    boardResponse.response || boardResponse)` falls back to the outer mapping.
  * `normalizeIntelligenceResponse` (:1483) reads every field from the TOP LEVEL
    first and consults the nested copy only as a fallback.
Replaying the real 67 MB payload through the page's own merge, with and without
the inner copy, produced identical keys; the only key whose value differed was
`response` itself, which in the new shape is a SUPERSET of what it was.
"""

from __future__ import annotations

import unittest

from syndicate.blueprints import intelligence as I


class DropSelfNestedResponseTests(unittest.TestCase):

    @staticmethod
    def _real_shape():
        """The production idiom: setdefault with a SHALLOW copy."""
        rows = [{"market": "h2h", "edge": 1.5}, {"market": "total", "edge": 0.2}]
        payload = {"ranked_all": rows, "board_contract": {"games": 8}, "ok": True}
        payload["response"] = dict(payload)
        return payload, rows

    def test_the_self_copy_is_dropped(self) -> None:
        payload, _rows = self._real_shape()

        out = I._drop_self_nested_response(payload)

        self.assertNotIn("response", out)
        self.assertEqual(sorted(out), ["board_contract", "ok", "ranked_all"])

    def test_the_surviving_values_are_the_SAME_objects(self) -> None:
        """Nothing is copied or rebuilt -- this must not itself allocate."""
        payload, rows = self._real_shape()

        out = I._drop_self_nested_response(payload)

        self.assertIs(out["ranked_all"], rows)

    def test_the_callers_payload_is_NOT_mutated(self) -> None:
        """`LAST_RESULT` is assigned from `payload["response"]` at four sites
        BEFORE this runs. Mutating in place would empty it."""
        payload, _rows = self._real_shape()

        I._drop_self_nested_response(payload)

        self.assertIn("response", payload, "the caller still needs its own copy")

    # -- the conservative half: anything unproven is KEPT ------------------

    def test_an_EQUAL_but_not_identical_copy_is_KEPT(self) -> None:
        """The check is identity, not equality. A payload whose inner mapping
        merely looks the same may have been built independently, and dropping it
        would be a guess."""
        payload = {"ranked_all": [{"a": 1}]}
        payload["response"] = {"ranked_all": [{"a": 1}]}      # equal, different object

        self.assertIn("response", I._drop_self_nested_response(payload))

    def test_an_inner_key_ABSENT_from_the_outer_keeps_everything(self) -> None:
        """Then the inner mapping carries something the outer does not, and it is
        not redundant at all."""
        rows = [{"a": 1}]
        payload = {"ranked_all": rows}
        payload["response"] = {"ranked_all": rows, "analysis": {"note": "only here"}}

        self.assertIn("response", I._drop_self_nested_response(payload))

    def test_an_inner_value_that_DIFFERS_keeps_everything(self) -> None:
        rows = [{"a": 1}]
        payload = {"ranked_all": rows, "ok": True}
        payload["response"] = {"ranked_all": rows, "ok": False}

        self.assertIn("response", I._drop_self_nested_response(payload))

    def test_absent_empty_or_non_dict_inner_is_a_no_op(self) -> None:
        self.assertEqual(I._drop_self_nested_response({"a": 1}), {"a": 1})
        self.assertEqual(I._drop_self_nested_response({"a": 1, "response": {}}),
                         {"a": 1, "response": {}})
        self.assertEqual(I._drop_self_nested_response({"a": 1, "response": "text"}),
                         {"a": 1, "response": "text"})
        self.assertIsNone(I._drop_self_nested_response(None))


class VersionedResponseTests(unittest.TestCase):
    """The wrapper must apply the drop, and must still wrap."""

    def test_the_versioned_wrapper_no_longer_carries_the_self_copy(self) -> None:
        rows = [{"market": "h2h"}]
        payload = {"ranked_all": rows, "ok": True}
        payload["response"] = dict(payload)

        wrapped = I._versioned_query_response(payload)

        self.assertIn("response", wrapped, "the OUTER wrapper key must remain")
        self.assertNotIn("response", wrapped["response"],
                         "the payload's copy of ITSELF must be gone")
        self.assertEqual(wrapped["response"]["ranked_all"], rows)
        for key in ("version", "timestamp", "response_hash"):
            self.assertIn(key, wrapped)

    def test_a_payload_with_no_self_copy_is_wrapped_unchanged(self) -> None:
        wrapped = I._versioned_query_response({"ranked_all": [], "ok": True})

        self.assertEqual(wrapped["response"]["ok"], True)
        self.assertIn("version", wrapped)


if __name__ == "__main__":
    unittest.main()
