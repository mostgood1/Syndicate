"""`#505` — the settlement join matched on an id that is not stable.

`recommendation_id` is `_stable_id("rec", {...})` over `prediction_id` + the
WHOLE recommendation payload + artifact_metadata. `pipeline/intelligence_state.py`
states the consequence itself: those ids are minted "from a content hash of the
full recommendation payload (incl. live odds/edge/probability)" and so a rebuild
"would mint a fresh 'new' pending row almost every cycle purely from ordinary
price drift".

The board re-records 150 recommendations per rebuild. A portfolio bet captures
whichever id was on screen at click time; settlement later decides a DIFFERENT
snapshot of the same wager. The ids never meet. That is the measured
`4,560 no_key_match of 8,276`, the `matched: 0`, and the
`[ledger_bridge] straight_settled: 0, parlays_settled: 0, skipped: 25131`
observed in production on 2026-08-22.

These tests pin the fix AND its refusals. A join that silently guesses is worse
than one that misses, so the ambiguity case is tested as hard as the match case.
"""

from __future__ import annotations

import unittest

from syndicate.features.shared import ledger_bridge


def _settled(recommendation: dict, outcome: str, rec_id: str) -> dict:
    """An evaluation-ledger record as settlement leaves it."""
    return {
        "recommendation_id": rec_id,
        "recommendation": recommendation,
        "result": {"outcome": outcome, "closing_price": -105, "closing_line": 1.5},
    }


def _mlb_total_over() -> dict:
    return {
        "event_id": "evt-42",
        "market": "total",
        "side": "over",
        "line": 8.5,
        "name": "NYY@BOS",
    }


class StableIdentity(unittest.TestCase):
    def test_price_drift_does_not_change_the_identity(self) -> None:
        """The whole defect in one assertion.

        Same wager, two board rebuilds, different quoted price and edge — which
        is what mints a new `recommendation_id` every cycle.
        """
        first = {**_mlb_total_over(), "odds": -110, "edge": 0.031}
        second = {**_mlb_total_over(), "odds": -104, "edge": 0.052}
        self.assertEqual(
            ledger_bridge._settlement_identity(first),
            ledger_bridge._settlement_identity(second),
        )

    def test_side_and_line_are_part_of_the_identity(self) -> None:
        """over 8.5 and under 8.5 are different bets; so are 8.5 and 9.5."""
        base = _mlb_total_over()
        other_side = ledger_bridge._settlement_identity({**base, "side": "under"})
        other_line = ledger_bridge._settlement_identity({**base, "line": 9.5})
        self.assertNotEqual(ledger_bridge._settlement_identity(base), other_side)
        self.assertNotEqual(ledger_bridge._settlement_identity(base), other_line)

    def test_bookmaker_is_deliberately_not_in_the_identity(self) -> None:
        """An outcome is book-independent even though a price is not."""
        base = _mlb_total_over()
        self.assertEqual(
            ledger_bridge._settlement_identity({**base, "quote": {"bookmaker": "fanduel"}}),
            ledger_bridge._settlement_identity({**base, "quote": {"bookmaker": "betrivers"}}),
        )

    def test_a_row_without_event_or_market_is_unkeyable(self) -> None:
        """Same rule as `_opening_key`: never invent an identity."""
        self.assertIsNone(ledger_bridge._settlement_identity({"market": "total", "side": "over"}))
        self.assertIsNone(ledger_bridge._settlement_identity({"event_id": "evt-42", "side": "over"}))

    def test_a_bet_keys_from_features_snapshot_and_top_level_together(self) -> None:
        """Neither half alone carries a full identity.

        `event_id`/`line`/`pick` live in `features_snapshot`; `market` and
        `selection` at the top level.
        """
        bet = {
            "market": "total",
            "selection": "NYY@BOS",
            "features_snapshot": {"event_id": "evt-42", "line": 8.5, "pick": "over"},
        }
        self.assertEqual(
            ledger_bridge._settlement_identity(ledger_bridge._bet_identity_payload(bet)),
            ledger_bridge._settlement_identity({**_mlb_total_over(), "name": "NYY@BOS"}),
        )


class StraightBets(unittest.TestCase):
    def test_a_bet_settles_despite_a_drifted_recommendation_id(self) -> None:
        """FAILS before `#505`: the ids differ, so nothing matched."""
        bet = {
            "id": "bet-1",
            "sport": "mlb",
            "market": "total",
            "selection": "NYY@BOS",
            "stake": 100.0,
            "odds": -110,
            # Captured at click time.
            "features_snapshot": {
                "recommendation_id": "rec_clicktime01",
                "event_id": "evt-42",
                "line": 8.5,
                "pick": "over",
            },
        }
        # Settlement decided a LATER snapshot, under a different id.
        records = [_settled({**_mlb_total_over(), "odds": -104}, "win", "rec_laterdrift9")]

        index = ledger_bridge._outcome_by_recommendation(records)
        identity = ledger_bridge._outcome_by_identity(records)

        self.assertIsNone(
            next((index[k] for k in ledger_bridge._recommendation_ids(bet) if k in index), None),
            "precondition: the id tier must miss, or this proves nothing",
        )
        outcome, reason = ledger_bridge._resolve_by_identity(bet, identity)
        self.assertEqual(outcome, "win")
        self.assertEqual(reason, "matched")

    def test_the_exact_id_still_wins_when_it_is_present(self) -> None:
        records = [_settled(_mlb_total_over(), "loss", "rec_exact")]
        index = ledger_bridge._outcome_by_recommendation(records)
        bet = {"features_snapshot": {"recommendation_id": "rec_exact"}}
        match = next((index[k] for k in ledger_bridge._recommendation_ids(bet) if k in index), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["outcome"], "loss")

    def test_an_unkeyable_bet_is_named_not_silently_skipped(self) -> None:
        outcome, reason = ledger_bridge._resolve_by_identity({"market": "total"}, {})
        self.assertIsNone(outcome)
        self.assertEqual(reason, "unkeyable_bet")


class RefusesToGuess(unittest.TestCase):
    """`learnings.md` 2026-08-15 — never treat equality of a LABEL as identity
    of a BET. Dropping `segment` is forced (the bet slip never captures it), so
    the collision it creates must be refused rather than resolved."""

    def test_conflicting_outcomes_under_one_key_are_marked_ambiguous(self) -> None:
        records = [
            _settled({**_mlb_total_over(), "segment": "first_half"}, "win", "rec_a"),
            _settled({**_mlb_total_over(), "segment": "full_game"}, "loss", "rec_b"),
        ]
        identity = ledger_bridge._outcome_by_identity(records)
        key = ledger_bridge._settlement_identity(_mlb_total_over())
        self.assertIs(identity[key], ledger_bridge._AMBIGUOUS)

        outcome, reason = ledger_bridge._resolve_by_identity(
            {"market": "total", "selection": "NYY@BOS",
             "features_snapshot": {"event_id": "evt-42", "line": 8.5, "pick": "over"}},
            identity,
        )
        self.assertIsNone(outcome, "an ambiguous key must not settle a position")
        self.assertEqual(reason, "identity_ambiguous")

    def test_agreeing_duplicates_are_not_ambiguous(self) -> None:
        """The NORMAL case: one wager under many drifting ids, all agreeing."""
        records = [
            _settled({**_mlb_total_over(), "odds": -110}, "win", "rec_1"),
            _settled({**_mlb_total_over(), "odds": -105}, "win", "rec_2"),
            _settled({**_mlb_total_over(), "odds": -102}, "win", "rec_3"),
        ]
        identity = ledger_bridge._outcome_by_identity(records)
        key = ledger_bridge._settlement_identity(_mlb_total_over())
        self.assertIsNot(identity[key], ledger_bridge._AMBIGUOUS)
        self.assertEqual(identity[key]["outcome"], "win")

    def test_pending_records_never_enter_either_index(self) -> None:
        records = [{"recommendation_id": "rec_p", "recommendation": _mlb_total_over(), "result": {"outcome": "pending"}}]
        self.assertEqual(ledger_bridge._outcome_by_recommendation(records), {})
        self.assertEqual(ledger_bridge._outcome_by_identity(records), {})


class Parlays(unittest.TestCase):
    """The case reconciliation structurally cannot handle -- no single market to
    match -- so drifting leg ids were the only route and it never settled."""

    def _legs(self) -> list[dict]:
        return [
            {"recommendation_id": "rec_stale_a", "market": "total", "selection": "NYY@BOS",
             "event_id": "evt-42", "line": 8.5, "pick": "over"},
            {"recommendation_id": "rec_stale_b", "market": "moneyline", "selection": "LAD",
             "event_id": "evt-77", "line": None, "pick": "lad"},
        ]

    def _records(self, second_outcome: str) -> list[dict]:
        return [
            _settled({"event_id": "evt-42", "market": "total", "side": "over", "line": 8.5,
                      "name": "NYY@BOS"}, "win", "rec_fresh_a"),
            _settled({"event_id": "evt-77", "market": "moneyline", "side": "lad", "line": None,
                      "name": "LAD"}, second_outcome, "rec_fresh_b"),
        ]

    def test_a_parlay_settles_when_every_leg_resolves_by_identity(self) -> None:
        records = self._records("win")
        identity = ledger_bridge._outcome_by_identity(records)
        self.assertEqual(ledger_bridge.settle_parlay_outcome(self._legs(), {}, identity), "win")

    def test_one_losing_leg_loses_the_parlay(self) -> None:
        records = self._records("loss")
        identity = ledger_bridge._outcome_by_identity(records)
        self.assertEqual(ledger_bridge.settle_parlay_outcome(self._legs(), {}, identity), "loss")

    def test_without_the_identity_index_behaviour_is_unchanged(self) -> None:
        """Backward compatibility: the third argument is optional."""
        self.assertIsNone(ledger_bridge.settle_parlay_outcome(self._legs(), {}))


class Instrumentation(unittest.TestCase):
    """The settlement join has always reported bare counts. This repo's own note
    on it: "4,560 no_key_match of 8,276 with no per-reason breakdown deeper than
    the name" -- which is why `skipped: 25131` was undiagnosable."""

    def test_the_summary_names_why_rows_missed(self) -> None:
        import inspect

        src = inspect.getsource(ledger_bridge.bridge_settled_results)
        for field in ("matched_by_id", "matched_by_identity", "skip_reasons", "index_sizes"):
            self.assertIn(field, src)
        for reason in ("no_settled_match", "unkeyable_bet", "identity_ambiguous"):
            self.assertIn(reason, src)


if __name__ == "__main__":
    unittest.main()
