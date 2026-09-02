"""The `#202` scan's six pass/fail rules each actually REJECT — `#624` step 4.

The rules were pre-registered on 2026-08-05 *before* any segment numbers were
computed, specifically so they could not be relaxed after seeing results. The
risk when transcribing them into code is not that a rule is wrong but that a
rule is INERT — a predicate that returns True for everything reads exactly like
a rule being satisfied.

So each test feeds a synthetic slice that violates ONE rule and nothing else,
and asserts that rule rejects it. `test_fragility_drops_winners_not_losers` is
the sharpest: the rule exists because five of 358 bets carried an earlier
moneyline "edge", and a version that trimmed losers instead would make every
slice look sturdier rather than weaker.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "mlb_edge_scan_under_test", REPO_ROOT / "scripts" / "run_mlb_edge_scan.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _load()


def _bet(date: str, won: bool, price: int = -110) -> dict:
    return {"date": date, "result": "win" if won else "loss", "odds": str(price)}


def _slice(n_win: int, n_loss: int, date: str = "2026-06-01") -> list[dict]:
    return [_bet(date, True) for _ in range(n_win)] + [_bet(date, False) for _ in range(n_loss)]


class PayoffTests(unittest.TestCase):
    def test_a_win_at_minus_110_pays_the_right_amount(self) -> None:
        self.assertAlmostEqual(MOD.profit_units(_bet("d", True, -110)), 100 / 110, places=6)

    def test_a_loss_costs_one_unit(self) -> None:
        self.assertEqual(MOD.profit_units(_bet("d", False)), -1.0)

    def test_the_settlement_ledger_wins_when_present(self) -> None:
        """The scan must not disagree with the ledger about who won."""
        row = {"result": "loss", "odds": "-110", "profit_u": 2.0, "stake_u": 1.0}
        self.assertEqual(MOD.profit_units(row), 2.0)


class EachRuleRejectsTests(unittest.TestCase):
    def test_size_rejects_a_thin_cell(self) -> None:
        self.assertFalse(MOD.rule_size(_slice(20, 20))[0])
        self.assertTrue(MOD.rule_size(_slice(40, 40))[0])

    def test_both_halves_rejects_a_decaying_edge(self) -> None:
        """The rule that killed an earlier moneyline candidate: +11.4% then
        +3.6%, decaying. A slice profitable overall but negative in its second
        half must fail."""
        rows = [_bet("2026-06-01", True) for _ in range(40)]
        rows += [_bet("2026-07-01", False) for _ in range(30)]
        self.assertFalse(MOD.rule_both_halves(rows)[0])

    def test_both_halves_accepts_a_consistent_edge(self) -> None:
        rows = [_bet("2026-06-01", i % 3 != 0) for i in range(45)]
        rows += [_bet("2026-07-01", i % 3 != 0) for i in range(45)]
        self.assertTrue(MOD.rule_both_halves(rows)[0])

    def test_fragility_rejects_a_slice_carried_by_five_bets(self) -> None:
        rows = [_bet("d", True, 5000) for _ in range(5)] + [_bet("d", False) for _ in range(60)]
        self.assertGreater(MOD.roi(rows), 0, "fixture must be profitable before trimming")
        self.assertFalse(MOD.rule_fragility(rows)[0])

    def test_fragility_drops_winners_not_losers(self) -> None:
        """Trimming losers would make every slice look STURDIER — the exact
        inversion this rule exists to prevent."""
        rows = [_bet("d", True) for _ in range(30)] + [_bet("d", False) for _ in range(30)]
        trimmed = MOD.rule_fragility(rows)[1]
        self.assertLess(float(trimmed), MOD.roi(rows), "trimming must remove the best outcomes")

    def test_bootstrap_rejects_a_ci_spanning_zero(self) -> None:
        rows = _slice(31, 29)
        self.assertFalse(MOD.rule_bootstrap(rows, resamples=400)[0])

    def test_bootstrap_accepts_a_decisive_slice(self) -> None:
        self.assertTrue(MOD.rule_bootstrap(_slice(70, 5), resamples=400)[0])

    def test_direction_rejects_the_wrong_sign(self) -> None:
        """'A result in the wrong direction is a failure, not a discovery.'"""
        self.assertFalse(MOD.rule_direction(-0.14, "positive")[0])
        self.assertFalse(MOD.rule_direction(+0.14, "negative")[0])
        self.assertTrue(MOD.rule_direction(+0.14, "positive")[0])

    def test_monotonicity_rejects_a_spiky_ordering(self) -> None:
        spiky = [("Q1", -0.14), ("Q2", 0.20), ("Q3", -0.13), ("Q4", 0.36)]
        self.assertFalse(MOD.rule_monotonic(spiky)[0])

    def test_monotonicity_accepts_a_trend_either_way(self) -> None:
        self.assertTrue(MOD.rule_monotonic([("a", -0.1), ("b", 0.0), ("c", 0.2)])[0])
        self.assertTrue(MOD.rule_monotonic([("a", 0.2), ("b", 0.0), ("c", -0.1)])[0])


class SlicingTests(unittest.TestCase):
    def test_line_buckets_match_the_preregistered_edges(self) -> None:
        rows = [{"market_line": v, "date": "d", "result": "win", "odds": "-110"}
                for v in (4.5, 5.5, 6.5, 8.5)]
        labels = [label for label, _ in MOD.line_buckets(rows)]
        self.assertEqual(labels, ["<=4.5", "5.5", "6.5", ">=7.5"])

    def test_quartiles_are_skipped_when_the_field_is_absent(self) -> None:
        """The scan must report NOT RUNNABLE rather than silently slicing on
        nothing — which is how five of these hypotheses were found to be
        unexecutable."""
        rows = [{"date": "d", "result": "win", "odds": "-110"} for _ in range(40)]
        self.assertEqual(MOD.quartile_buckets(rows, "park_hr_mult"), [])


if __name__ == "__main__":
    unittest.main()
