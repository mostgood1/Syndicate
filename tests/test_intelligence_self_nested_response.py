"""`/api/intelligence/query` stops serving the payload's copy of itself (`#632`).

MEASURED on the live endpoint 2026-09-04, one call:

    served response                                 67.19 MB on the wire
      response.response  (the mirror)                 36.42 MB   <- 50%
      top_opportunities == recommendations             6.44 MB each
      board_contract    == boardContract               5.86 MB each

All 17 keys of the mirror were VALUE-EQUAL to the outer payload, and this route
is the largest per-request allocator the per-process profiler found
(~82 MB/call, replicated on both workers).

THE MIRROR HAS EXACTLY ONE READER: `LAST_RESULT`, assigned two lines after it is
created. Once that is taken it is dead weight on the wire. The client already
copes without it -- `intelligence.html:1517` reads `boardResponse.response ||
boardResponse`, and `normalizeIntelligenceResponse` (:1483) prefers top-level
keys and consults the nested copy only as a fallback. Replaying the real 67 MB
payload through the page's own merge, with and without the mirror, produced
identical keys.

WHY A FLAG AND NOT A COMPARISON -- and this is the part worth keeping. The first
attempt dropped the mirror only when `outer[key] is inner[key]` for every key, on
the reasoning that `dict(payload)` is a shallow copy so the values are the same
objects. That reasoning is correct in isolation and was INERT in production:
`_attach_intelligence_response_aliases` runs between the copy and the
serialisation, and `_normalize_opportunity_item` rebuilds every item with
`dict(item)`, so the identities no longer match. It shipped, saved nothing, and
was caught only by measuring the SERVED payload rather than trusting the deploy.

`setdefault` creates the mirror only when the key is ABSENT, so "did we create
it?" is the exact question, costs nothing, and can never remove a `response` that
a caller genuinely supplied.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app


def _board_payload():
    """The shape the combined-board reader returns: no `response` key of its own,
    so the route's `setdefault` is what creates the mirror."""
    rows = [{"name": "Judge Over 0.5 HR", "market": "HR", "pick": "Over 0.5",
             "sport": "mlb", "edge": 2.4, "score": 1.1}]
    return {
        "ok": True,
        "ranked_all": list(rows),
        "top_opportunities": list(rows),
        "board_contract": {"games": [], "version": "game_board_v1"},
        "dates_covered": ["2026-09-04"],
        "candidate_count": 1,
    }


class SelfNestedResponseTests(unittest.TestCase):

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def _post(self):
        return self.client.post("/api/intelligence/query",
                                json={"question": "show me the board"})

    def test_the_served_payload_does_NOT_carry_a_copy_of_itself(self) -> None:
        """The whole point: 50% of the bytes were this key."""
        with patch("syndicate.blueprints.intelligence.combined_board_default_enabled",
                   return_value=True), \
             patch("syndicate.blueprints.intelligence.read_combined_intelligence_response",
                   return_value=_board_payload()):
            response = self._post()

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIn("response", body, "the OUTER wrapper key must remain")
        self.assertNotIn("response", body["response"],
                         "the payload must not contain a copy of itself")

    def test_the_real_content_still_arrives(self) -> None:
        """A saving that also drops the data is not a saving."""
        with patch("syndicate.blueprints.intelligence.combined_board_default_enabled",
                   return_value=True), \
             patch("syndicate.blueprints.intelligence.read_combined_intelligence_response",
                   return_value=_board_payload()):
            body = self._post().get_json()

        served = body["response"]
        self.assertEqual(len(served.get("ranked_all") or []), 1)
        self.assertEqual(served["ranked_all"][0]["market"], "HR")
        self.assertTrue(served.get("board_contract"))
        for key in ("version", "timestamp", "response_hash"):
            self.assertIn(key, body)

    def test_a_response_key_the_READER_supplied_is_PRESERVED(self) -> None:
        """`setdefault` does not overwrite, so a `response` that arrived with the
        payload is not ours to remove. This is the case the flag exists for, and
        the one a blanket `pop` would have silently destroyed."""
        payload = _board_payload()
        payload["response"] = {"analysis": {"note": "supplied by the reader"}}

        with patch("syndicate.blueprints.intelligence.combined_board_default_enabled",
                   return_value=True), \
             patch("syndicate.blueprints.intelligence.read_combined_intelligence_response",
                   return_value=payload):
            body = self._post().get_json()

        inner = body["response"].get("response")
        self.assertIsInstance(inner, dict, "a caller-supplied response must survive")
        self.assertEqual(inner.get("analysis", {}).get("note"), "supplied by the reader")


if __name__ == "__main__":
    unittest.main()
