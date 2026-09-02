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
                out, audit = MOD._apply_market_anchor("epl", self.root, fixtures, _RATINGS)
        printed = " ".join(str(c.args[0]) for c in printer.call_args_list if c.args)
        self._audit = audit
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
                out, audit = MOD._apply_market_anchor("epl", empty, self._fixtures(), _RATINGS)
        printed = " ".join(str(c.args[0]) for c in printer.call_args_list if c.args)
        self.assertEqual(out, _RATINGS)
        self.assertIn("ODDS_ABSENT", printed)
        self.assertEqual(audit["state"], "odds_absent")

    def test_an_unpriced_slate_names_the_reason_rather_than_anchoring_nothing(self) -> None:
        fixtures = [{"match_id": "zzz", "home_team": "Ghost", "away_team": "Phantom"}]
        with patch.dict(os.environ, {"SYNDICATE_SOCCER_MARKET_ANCHOR_WEIGHT": "0.35"}, clear=False):
            with patch("builtins.print") as printer:
                out, audit = MOD._apply_market_anchor("epl", self.root, fixtures, _RATINGS)
        printed = " ".join(str(c.args[0]) for c in printer.call_args_list if c.args)
        self.assertEqual(out, _RATINGS)
        self.assertIn("no_priced_fixtures", printed)
        self.assertEqual(audit["state"], "no_priced_fixtures")

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


class MarketAnchorAuditIsPublishedTests(unittest.TestCase):
    """The audit must be READABLE WHERE THE LOGS ARE NOT.

    `ops_refresh.py:1402` launches every refresh unit with
    `stdout=subprocess.DEVNULL`, so nothing `build_soccer_artifacts.py` prints
    reaches Render. Measured 2026-09-02 over a window where seven soccer units
    demonstrably ran: every token printed by that file returned 0 log matches,
    including `player projections` which prints on every success, while the
    parent's own token returned 5. The `[soccer_anchor]` lines are therefore not
    an instrument in production -- the published field is.

    The point of `state` is that the five outcomes must not collapse into one
    another. A test that only checks "a dict came back" would pass against
    exactly the ambiguity this replaces.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        odds = self.root / "epl" / "api" / "odds"
        odds.mkdir(parents=True, exist_ok=True)
        (odds / "game_odds_current.csv").write_text(_ODDS_CSV, encoding="utf-8")

    def _audit_at(self, weight: str, *, source_root=None, fixtures=None):
        fixtures = fixtures if fixtures is not None else [
            {"match_id": "e1", "home_team": "Home FC", "away_team": "Away FC"}
        ]
        with patch.dict(os.environ, {"SYNDICATE_SOCCER_MARKET_ANCHOR_WEIGHT": weight}, clear=False):
            with patch("builtins.print"):
                # simulations=2 keeps these fast. It is a COST knob, not a
                # correctness one: the assertions below are about which STATE
                # is reported and whether resolution was counted, and neither
                # depends on the solved shift's precision. The pre-existing
                # tests above deliberately keep the default -- they assert the
                # ratings MOVE, which is a claim about the solve itself.
                _out, audit = MOD._apply_market_anchor(
                    "epl", source_root if source_root is not None else self.root, fixtures, _RATINGS,
                    simulations=2,
                )
        return audit

    def test_the_five_states_are_DISTINCT_values(self) -> None:
        """If any two of these collapse, the field has rebuilt the silence."""
        disabled = self._audit_at("0")["state"]
        anchored = self._audit_at("0.35")["state"]
        absent = self._audit_at("0.35", source_root=Path(self._tmp.name) / "nowhere")["state"]
        unpriced = self._audit_at(
            "0.35", fixtures=[{"match_id": "zzz", "home_team": "Ghost", "away_team": "Phantom"}]
        )["state"]

        self.assertEqual(disabled, "disabled")
        self.assertEqual(anchored, "anchored")
        self.assertEqual(absent, "odds_absent")
        self.assertEqual(unpriced, "no_priced_fixtures")
        self.assertEqual(len({disabled, anchored, absent, unpriced}), 4)

    def test_DISABLED_still_reports_a_live_feed(self) -> None:
        """This is the state production is actually in. `disabled` with
        attached=1 is a WORKING FEED plus a DISARMED mechanism, and must not
        read like `odds_absent`."""
        audit = self._audit_at("0")
        self.assertEqual(audit["state"], "disabled")
        self.assertEqual(audit["attached"], 1)
        self.assertEqual(audit["weight"], 0.0)
        self.assertEqual(audit["by_stage"]["event_id"], 1)

    def test_ANCHORED_reports_REACHABILITY_not_just_that_a_dict_changed(self) -> None:
        """`teams_changed` counted spurious keys as successes before the
        2026-09-02 name-join fix -- it read `2 of 25` while 0 teams changed for
        the simulation. `teams_resolved`/`teams_unresolved` come from the
        resolver and are the honest pair."""
        audit = self._audit_at("0.35")
        self.assertEqual(audit["state"], "anchored")
        self.assertEqual(audit["teams_resolved"], 2)
        self.assertEqual(audit["teams_unresolved"], 0)
        self.assertEqual(audit["fixtures_priced"], 1)
        self.assertIsInstance(audit["elapsed_s"], float)

    def test_an_unresolvable_team_is_COUNTED_not_hidden(self) -> None:
        audit = self._audit_at(
            "0.35", fixtures=[{"match_id": "e1", "home_team": "Home FC", "away_team": "Away FC"},
                              {"match_id": "e1", "home_team": "Nobody United", "away_team": "Away FC"}]
        )
        self.assertEqual(audit["state"], "anchored")
        self.assertEqual(audit["teams_unresolved"], 1)
        self.assertIn("Nobody United", audit["unresolved_examples"])

    def test_every_state_carries_the_weight_so_a_reader_never_has_to_guess(self) -> None:
        for weight in ("0", "0.35"):
            with self.subTest(weight=weight):
                self.assertEqual(self._audit_at(weight)["weight"], float(weight))
        self.assertEqual(
            self._audit_at("0.35", source_root=Path(self._tmp.name) / "nowhere")["weight"], 0.35
        )
