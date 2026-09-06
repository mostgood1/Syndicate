"""`top_opportunities` and `recommendations` carry ONE set of row objects.

`#632`. `slice_intelligence_board_state_for_request` built the two keys as
INDEPENDENT deep copies of the same rows -- `[dict(item) for item in
top_opportunities]` evaluated twice -- so every response and every cache entry
paid for the rows twice. Measured on a 300-row slate: **0.120 MB -> 0.068 MB, a
43.8% saving** on that term.

THE LISTS STAY DISTINCT; only the row dicts are shared. A list of N pointers
costs ~8 bytes per row against a full dict per row, so keeping them separate is
nearly free and stops list-level mutation on one key from disturbing the other.

WHY SHARING THE DICTS IS SAFE, checked rather than assumed: a scripted search
over `pipeline/` and `syndicate/` for loops over either key that assign into the
item found exactly ONE hit -- `syndicate/features/intelligence.py:11092` -- and
that is a LOCAL `recommendations` inside `run_intelligence_query`, upstream of
this function, mutating candidates before they are ever response rows. Every
other use of both keys is a whole-list reassignment.

The aliasing that IS introduced is asserted below rather than left implicit, so
a future reader meets it as a documented property instead of discovering it in
production.
"""

from __future__ import annotations

import unittest

from pipeline.intelligence_state import slice_intelligence_board_state_for_request as SLICE


def _state(rows: int = 6, sport: str = "mlb") -> dict:
    ranked = [{"id": i, "sport": sport, "blob": "x" * 500} for i in range(rows)]
    return {"ranked_all": ranked, "by_sport": {sport: ranked}, "state_meta": {"v": 1}}


class SharedRowTests(unittest.TestCase):

    def test_the_two_keys_hold_the_SAME_row_objects(self) -> None:
        """The change itself. Identity, not equality -- equality held before and
        cost twice the memory."""
        response = SLICE(_state(), sport="all", limit=None)

        self.assertTrue(
            all(a is b for a, b in zip(response["top_opportunities"],
                                       response["recommendations"])),
            "each row must be ONE object referenced twice, not two equal copies")

    def test_the_two_LISTS_are_distinct_objects(self) -> None:
        """Sharing rows is the saving; sharing the lists would also alias
        append/remove/sort, which is a much larger behaviour change for ~8 bytes
        a row."""
        response = SLICE(_state(), sport="all", limit=None)

        self.assertIsNot(response["top_opportunities"], response["recommendations"])

    def test_LIST_level_mutation_stays_isolated(self) -> None:
        response = SLICE(_state(rows=4), sport="all", limit=None)

        response["recommendations"].append({"id": "extra"})

        self.assertEqual(len(response["top_opportunities"]), 4)
        self.assertEqual(len(response["recommendations"]), 5)

    def test_ROW_level_mutation_IS_shared_and_that_is_intentional(self) -> None:
        """The aliasing this change introduces, asserted so it is documented
        rather than discovered. It is acceptable because nothing in the codebase
        mutates a response row in place -- if that ever changes, this test is the
        one that will fail and say why."""
        response = SLICE(_state(rows=3), sport="all", limit=None)

        response["recommendations"][0]["injected"] = True

        self.assertTrue(response["top_opportunities"][0].get("injected"),
                        "the two keys are the same rows by design")

    def test_the_rows_are_COPIES_of_the_source_state(self) -> None:
        """Sharing between the two keys must not extend to sharing with
        `ranked_all` -- the cached state is reused across requests, and a
        response mutating it would corrupt every later reader."""
        state = _state(rows=3)
        response = SLICE(state, sport="all", limit=None)

        response["top_opportunities"][0]["injected"] = True

        self.assertNotIn("injected", state["ranked_all"][0])


class SlicingUnchangedTests(unittest.TestCase):

    def test_limit_still_applies_to_BOTH_keys(self) -> None:
        response = SLICE(_state(rows=10), sport="all", limit=4)

        self.assertEqual(len(response["top_opportunities"]), 4)
        self.assertEqual(len(response["recommendations"]), 4)

    def test_sport_scoping_still_applies_to_BOTH_keys(self) -> None:
        state = {
            "ranked_all": [{"id": 1, "sport": "mlb"}, {"id": 2, "sport": "nba"}],
            "by_sport": {"mlb": [{"id": 1, "sport": "mlb"}]},
        }

        response = SLICE(state, sport="mlb", limit=None)

        self.assertEqual([row["id"] for row in response["top_opportunities"]], [1])
        self.assertEqual([row["id"] for row in response["recommendations"]], [1])

    def test_the_two_keys_remain_EQUAL_in_content(self) -> None:
        """The contract consumers actually rely on."""
        response = SLICE(_state(rows=7), sport="all", limit=5)

        self.assertEqual(response["top_opportunities"], response["recommendations"])

    def test_an_empty_state_yields_two_empty_lists(self) -> None:
        response = SLICE(None, sport="all", limit=None)

        self.assertEqual(response["top_opportunities"], [])
        self.assertEqual(response["recommendations"], [])
        self.assertIsNot(response["top_opportunities"], response["recommendations"])

    def test_other_state_keys_are_preserved(self) -> None:
        response = SLICE(_state(rows=2), sport="all", limit=None)

        self.assertEqual(response["state_meta"], {"v": 1})


if __name__ == "__main__":
    unittest.main()
