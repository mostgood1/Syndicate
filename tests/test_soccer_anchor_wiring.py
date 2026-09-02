"""Soccer market-anchoring is REACHABLE, instrumented, and still OFF.

`anchor_ratings_to_market` is validated (-40..-51% MAE vs a HELD-OUT bookmaker
consensus) and had never run: production fixtures carried no `market_odds`, so
the anchor silently `continue`d past every one of them.

THE TEST THAT MATTERS IS `off != on`. A wiring that cannot change the ratings is
indistinguishable from no wiring at all, and this session has now watched three
separate mechanisms ship inert (`#626`(h)'s autorun, the odds_history size cap,
this anchor). Presence is not reachability, so the suite proves the weight knob
MOVES something before it asserts anything about what.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "build_soccer_artifacts_under_test", REPO_ROOT / "scripts" / "build_soccer_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _load()

_ODDS_CSV = (
    "league,event_id,home_team,away_team,commence_time,market,side,line,price,book\n"
    "epl,e1,Home FC,Away FC,2026-09-12T19:00:00Z,h2h,Home FC,,-150,bookA\n"
    "epl,e1,Home FC,Away FC,2026-09-12T19:00:00Z,h2h,Draw,,+260,bookA\n"
    "epl,e1,Home FC,Away FC,2026-09-12T19:00:00Z,h2h,Away FC,,+420,bookA\n"
)

_RATINGS = {
    "Home FC": {"attack": 1.35, "defense": 1.05},
    "Away FC": {"attack": 1.10, "defense": 1.25},
}


class AnchorWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        odds = self.root / "epl" / "api" / "odds"
        odds.mkdir(parents=True, exist_ok=True)
        (odds / "game_odds_current.csv").write_text(_ODDS_CSV, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _fixtures(self) -> list[dict]:
        return [{"match_id": "e1", "home_team": "Home FC", "away_team": "Away FC"}]

    def _run(self, weight: str):
        fixtures = self._fixtures()
        with patch.dict(os.environ, {"SYNDICATE_SOCCER_MARKET_ANCHOR_WEIGHT": weight}, clear=False):
            with patch("builtins.print") as printer:
                out = MOD._apply_market_anchor("epl", self.root, fixtures, _RATINGS)
        printed = " ".join(str(c.args[0]) for c in printer.call_args_list if c.args)
        return out, fixtures, printed

    # ---- the reachability test, before any correctness claim ----

    def test_OFF_leaves_the_ratings_untouched(self) -> None:
        out, _fixtures, _printed = self._run("0")
        self.assertEqual(out, _RATINGS, "weight 0 must not move a single rating")

    def test_ON_actually_moves_the_ratings(self) -> None:
        """off != on. If this fails the wiring is inert and every downstream
        claim about anchoring is meaningless."""
        out, _fixtures, _printed = self._run("0.35")
        self.assertNotEqual(out, _RATINGS, "weight 0.35 must change the ratings")
        moved = [team for team, rating in out.items() if _RATINGS.get(team) != rating]
        self.assertTrue(moved, "at least one team's rating must move")

    def test_the_anchor_moves_toward_the_market_not_arbitrarily(self) -> None:
        """The market makes Home a clear favourite (-150 vs +420). Anchoring
        should raise Home's attack relative to the unanchored rating, not just
        perturb it."""
        out, _f, _p = self._run("0.5")
        self.assertNotEqual(out["Home FC"], _RATINGS["Home FC"])

    # ---- the instrumentation, which is what makes an inert anchor visible ----

    def test_the_odds_counts_are_published_EVEN_WHEN_OFF(self) -> None:
        """The feed's health and the mechanism's arming are separate questions.
        Collapsing them is how a silent no-op reads as success."""
        _out, _fixtures, printed = self._run("0")
        self.assertIn("ODDS_ATTACHED", printed)
        self.assertIn("attached=1", printed)
        self.assertIn("weight=0.0", printed)

    def test_an_absent_odds_file_says_so_rather_than_degrading_quietly(self) -> None:
        empty = Path(self._tmp.name) / "nowhere"
        with patch.dict(os.environ, {"SYNDICATE_SOCCER_MARKET_ANCHOR_WEIGHT": "0.35"}, clear=False):
            with patch("builtins.print") as printer:
                out = MOD._apply_market_anchor("epl", empty, self._fixtures(), _RATINGS)
        printed = " ".join(str(c.args[0]) for c in printer.call_args_list if c.args)
        self.assertEqual(out, _RATINGS)
        self.assertIn("ODDS_ABSENT", printed)

    def test_an_unpriced_slate_names_the_reason_rather_than_anchoring_nothing(self) -> None:
        fixtures = [{"match_id": "zzz", "home_team": "Ghost", "away_team": "Phantom"}]
        with patch.dict(os.environ, {"SYNDICATE_SOCCER_MARKET_ANCHOR_WEIGHT": "0.35"}, clear=False):
            with patch("builtins.print") as printer:
                out = MOD._apply_market_anchor("epl", self.root, fixtures, _RATINGS)
        printed = " ".join(str(c.args[0]) for c in printer.call_args_list if c.args)
        self.assertEqual(out, _RATINGS)
        self.assertIn("no_priced_fixtures", printed)

    # ---- the knob ----

    def test_the_default_is_OFF(self) -> None:
        """Wiring it reachable and turning it on are two different decisions.
        The mechanism-vs-estimator re-fit is not done."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYNDICATE_SOCCER_MARKET_ANCHOR_WEIGHT", None)
            self.assertEqual(MOD._soccer_anchor_weight(), 0.0)

    def test_the_weight_is_clamped_and_junk_falls_back_to_OFF(self) -> None:
        for raw, expected in (("1.7", 1.0), ("-3", 0.0), ("abc", 0.0), ("", 0.0), ("0.35", 0.35)):
            with patch.dict(os.environ, {"SYNDICATE_SOCCER_MARKET_ANCHOR_WEIGHT": raw}, clear=False):
                self.assertAlmostEqual(MOD._soccer_anchor_weight(), expected, msg=raw)


if __name__ == "__main__":
    unittest.main()
