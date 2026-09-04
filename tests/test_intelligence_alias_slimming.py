"""Opt-in alias slimming for `/api/intelligence/query` (`#632`).

MEASURED on the live endpoint 2026-09-04, after the self-mirror fix landed:

    recommendations == top_opportunities      6,441,138 B
    boardContract   == board_contract         5,857,770 B
    by_sport         regroups from ranked_all 5,859,557 B
    --------------------------------------------------------
                                             18,158,465 B   ~50% of what remains

THE CANONICAL FOR THE OPPORTUNITY PAIR IS `top_opportunities`, NOT `ranked_all`.
`_slim_embedded_board_payload` aliases both to `ranked_all`, which is right for
the HTML embed and wrong here: on this payload `recommendations` matches
`top_opportunities` (both 6,441,138 B) and does NOT match `ranked_all`
(5,859,516 B). Reusing that function unchanged would have saved 6.4 MB less and
looked like it had worked.

WHY THE PROOF IS NOT `json.dumps`. `_slim_embedded_board_payload` compares by
serialising both sides. That is fine once per page render and wrong on a request
path: these pairs are 5.9-6.4 MB each, so the proof would add ~13 MB of transient
strings to the very peak this exists to reduce. `_provably_same` proves deep
equality by RECURSIVE SHALLOW IDENTITY instead -- measured on real alias output,
15 of a row's 19 fields are literally the same object and the rest are cheap
scalars -- so nothing is allocated to prove anything.

WHY IT IS OPT-IN. Dropping keys is a contract change and the consumers of this
endpoint are not all in this repository. A caller that does not ask gets exactly
what it got before; that is the test that matters most below.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.blueprints import intelligence as I


class ProvablySameTests(unittest.TestCase):
    """Conservative in every direction: unproven means KEEP."""

    def test_identity_and_equal_nested_values_both_prove(self) -> None:
        shared = {"x": 1}
        self.assertTrue(I._provably_same(shared, shared))
        self.assertTrue(I._provably_same({"a": [1, {"b": "s"}]}, {"a": [1, {"b": "s"}]}))

    def test_the_four_freshly_computed_SCALARS_still_prove(self) -> None:
        """Real alias output shares 15 of 19 fields by identity; the rest are
        recomputed strings/floats/empty lists. Those must compare by value or the
        proof fails on every row."""
        left = {"sport_slug": "mlb", "american_odds": -110.0,
                "rationale": "The stored edge reads 2.4.", "missing_advanced_inputs": []}
        right = {"sport_slug": "mlb", "american_odds": -110.0,
                 "rationale": "The stored edge reads 2.4.", "missing_advanced_inputs": []}
        self.assertTrue(I._provably_same(left, right))

    def test_a_difference_anywhere_refuses(self) -> None:
        self.assertFalse(I._provably_same({"a": 1}, {"a": 2}))
        self.assertFalse(I._provably_same({"a": 1}, {"a": 1, "b": 2}))
        self.assertFalse(I._provably_same([1, 2], [1, 2, 3]))
        self.assertFalse(I._provably_same({"a": [1]}, {"a": [2]}))

    def test_type_mismatch_refuses_without_coercing(self) -> None:
        """`1 == True` and `1 == 1.0` in Python; a payload is not the place to
        let those pass as the same value."""
        self.assertFalse(I._provably_same([1], "1"))
        self.assertFalse(I._provably_same({"a": 1}, [1]))
        self.assertFalse(I._provably_same(1, True))

    def test_an_unprovable_type_refuses_rather_than_guessing(self) -> None:
        self.assertFalse(I._provably_same({1, 2}, {1, 2}))

    def test_runaway_depth_refuses(self) -> None:
        deep_a: dict = {}
        deep_b: dict = {}
        a, b = deep_a, deep_b
        for _ in range(14):
            a["n"] = {}; b["n"] = {}
            a, b = a["n"], b["n"]
        self.assertFalse(I._provably_same(deep_a, deep_b))


class SlimResponseAliasesTests(unittest.TestCase):

    @staticmethod
    def _payload():
        rows = [{"sport": "mlb", "v": 1}, {"sport": "nba", "v": 2}]
        opportunities = [{"name": "a", "edge": 1.0}]
        return {
            "ranked_all": rows,
            "top_opportunities": opportunities,
            "recommendations": [{"name": "a", "edge": 1.0}],       # equal, not identical
            "board_contract": {"games": [1], "version": "v1"},
            "boardContract": {"games": [1], "version": "v1"},
            "by_sport": {"mlb": [rows[0]], "nba": [rows[1]]},
        }

    def test_all_three_redundancies_are_dropped_and_described(self) -> None:
        out = I._slim_response_aliases(self._payload())

        self.assertNotIn("recommendations", out)
        self.assertNotIn("boardContract", out)
        self.assertNotIn("by_sport", out)
        self.assertEqual(out["_response_aliases"], {
            "recommendations": "top_opportunities",
            "boardContract": "board_contract",
            "by_sport": "__group_ranked_all_by_sport__",
        })

    def test_the_canonical_survivors_are_untouched(self) -> None:
        payload = self._payload()
        out = I._slim_response_aliases(payload)

        self.assertIs(out["top_opportunities"], payload["top_opportunities"])
        self.assertIs(out["ranked_all"], payload["ranked_all"])
        self.assertIs(out["board_contract"], payload["board_contract"])

    def test_a_DIFFERING_alias_is_kept(self) -> None:
        payload = self._payload()
        payload["recommendations"] = [{"name": "DIFFERENT", "edge": 9.9}]

        out = I._slim_response_aliases(payload)

        self.assertIn("recommendations", out)
        self.assertNotIn("recommendations", out.get("_response_aliases", {}))

    def test_by_sport_is_kept_when_the_regrouping_is_not_exact(self) -> None:
        """Ordering, a missing sport, or an extra key all mean the partition
        cannot be rebuilt -- so it must survive."""
        payload = self._payload()
        payload["by_sport"] = {"mlb": [{"sport": "mlb", "v": 1}], "nhl": []}

        self.assertIn("by_sport", I._slim_response_aliases(payload))

    def test_nothing_redundant_means_no_alias_key_at_all(self) -> None:
        out = I._slim_response_aliases({"ranked_all": [], "ok": True})

        self.assertNotIn("_response_aliases", out)

    def test_the_input_is_not_mutated(self) -> None:
        payload = self._payload()
        I._slim_response_aliases(payload)

        self.assertIn("recommendations", payload)
        self.assertIn("by_sport", payload)


class OptInTests(unittest.TestCase):
    """The contract half: a caller that does not ask must see NO change."""

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    @staticmethod
    def _board():
        rows = [{"sport": "mlb", "name": "Judge Over 0.5 HR", "market": "HR",
                 "pick": "Over 0.5", "edge": 2.4, "score": 1.1}]
        return {"ok": True, "ranked_all": list(rows), "top_opportunities": list(rows),
                "recommendations": list(rows),
                "board_contract": {"games": [], "version": "game_board_v1"},
                "candidate_count": 1}

    def _post(self, body):
        with patch("syndicate.blueprints.intelligence.combined_board_default_enabled",
                   return_value=True), \
             patch("syndicate.blueprints.intelligence.read_combined_intelligence_response",
                   return_value=self._board()):
            return self.client.post("/api/intelligence/query", json=body).get_json()

    def test_flag_recognition(self) -> None:
        self.assertTrue(I._alias_slim_requested({"slim_aliases": True}))
        self.assertTrue(I._alias_slim_requested({"slim_aliases": "true"}))
        self.assertFalse(I._alias_slim_requested({}))
        self.assertFalse(I._alias_slim_requested({"slim_aliases": False}))
        self.assertFalse(I._alias_slim_requested(None))

    def test_WITHOUT_the_flag_every_alias_key_still_arrives(self) -> None:
        """The test that protects every consumer outside this repository."""
        served = self._post({"question": "show me the board"})["response"]

        self.assertIn("recommendations", served)
        self.assertIn("boardContract", served)
        self.assertNotIn("_response_aliases", served)

    def test_WITH_the_flag_the_redundant_keys_are_dropped(self) -> None:
        served = self._post({"question": "show me the board", "slim_aliases": True})["response"]

        self.assertNotIn("recommendations", served)
        self.assertNotIn("boardContract", served)
        self.assertIn("_response_aliases", served)
        self.assertIn("top_opportunities", served, "the canonical must survive")
        self.assertIn("board_contract", served)

    def test_the_slimmed_payload_can_be_rebuilt_exactly(self) -> None:
        """A saving nobody can undo is data loss. This mirrors what
        `rehydrateAliases` does in the browser."""
        full = self._post({"question": "show me the board"})["response"]
        slim = self._post({"question": "show me the board", "slim_aliases": True})["response"]

        rebuilt = dict(slim)
        for key, source in (rebuilt.pop("_response_aliases", {}) or {}).items():
            if source == "__group_ranked_all_by_sport__":
                grouped: dict = {}
                for row in rebuilt.get("ranked_all") or []:
                    grouped.setdefault(str(row.get("sport") or ""), []).append(row)
                rebuilt[key] = grouped
            else:
                rebuilt[key] = rebuilt[source]

        for key in ("recommendations", "boardContract", "top_opportunities", "board_contract"):
            self.assertEqual(rebuilt.get(key), full.get(key), key)


if __name__ == "__main__":
    unittest.main()
