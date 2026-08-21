"""The WNBA reuse guard must judge a LIVE tick against the LIVE cadence.

WHY THIS FILE EXISTS. `#383` bounded bundle reuse by the PREGAME sweep interval
(2h default) on the correct reasoning that "the bound is the cadence that CALLS
this". Since then a SECOND caller appeared -- the WNBA live autorun, every 240s
while a game is in progress -- and it kept being judged against the first
caller's cadence, so it was inert from the day it shipped.

MEASURED IN PRODUCTION 2026-08-21, IND@DAL live: `WNBA_LIVE_AUTORUN_LAUNCHED`
fired every ~4.3 min as designed while `/api/ops/wnba/refresh-decision` returned
`reused_artifact_bundle` on TEN CONSECUTIVE TICKS (19:45:30-19:56:24 CT,
identical `input_hash`). The child that fetches and appends `book_quotes` never
spawned; the quote shard's state file had all 5,489 keys' last-seen slot frozen
at 00:07:49.815Z, 36+ min cold.

REACHABILITY BEFORE CORRECTNESS. The first two tests assert `off != on` -- that
the live bound is genuinely a different number from the pregame one, and that
the guard actually DECLINES where it previously reused. A test that only checked
"live returns a float" would pass against the unfixed code. Per the standing
rule: a guard is not verified until you have watched it FAIL on purpose.

BOTH BRANCHES. `_existing_refresh_state` (source_root) and
`_existing_artifact_bundle_state` (artifact bundle) are tested separately and
deliberately. Production happened to be served by the bundle branch; fixing only
that one is what the 2026-08-20 standing rule forbids, and the source branch had
NO age bound at all, so it could reproduce the same starvation the first time a
source_root run took over.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "refresh_wnba_oddsapi_props.py"
    spec = importlib.util.spec_from_file_location("test_wnba_live_reuse_bound_mod", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_RELEVANT_ENV = (
    "SYNDICATE_WNBA_LIVE_REUSE_MAX_AGE_SECONDS",
    "SYNDICATE_WNBA_LIVE_REFRESH_INTERVAL_SECONDS",
    "SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS",
    "SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_WNBA",
    "SYNDICATE_WNBA_REUSE_MAX_AGE_SECONDS",
)


class ReuseBoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        # These bounds are read from the environment, so a stray value on the
        # developer's machine would silently rewrite what this file asserts.
        self._saved = {name: os.environ.pop(name, None) for name in _RELEVANT_ENV}

    def tearDown(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    # --- reachability: off != on -------------------------------------------

    def test_live_bound_differs_from_pregame_bound(self) -> None:
        """The whole fix is that these two are NOT the same number."""
        pregame = self.module._reuse_max_age_seconds("wnba")
        live = self.module._reuse_max_age_seconds("wnba", phase="live")
        self.assertEqual(pregame, 2 * 3600.0)
        self.assertEqual(live, 240.0)
        self.assertNotEqual(pregame, live)
        self.assertLess(live, pregame)

    def test_non_live_phases_keep_the_pregame_bound_exactly(self) -> None:
        """This change must be a no-op for every caller that is not a live tick.

        `all` is the combined-sweep phase and is explicitly NOT a live tick.
        """
        pregame = self.module._reuse_max_age_seconds("wnba")
        for phase in (None, "", "pregame", "all", "PREGAME", "unknown"):
            with self.subTest(phase=phase):
                self.assertEqual(
                    self.module._reuse_max_age_seconds("wnba", phase=phase), pregame
                )

    def test_live_bound_is_case_insensitive(self) -> None:
        self.assertEqual(self.module._reuse_max_age_seconds("wnba", phase="LIVE"), 240.0)
        self.assertEqual(self.module._reuse_max_age_seconds("wnba", phase=" live "), 240.0)

    # --- the live bound stays BOUNDED (credit protection) -------------------

    def test_live_bound_is_configurable_but_never_unbounded(self) -> None:
        """`#344`/`#383` exist to protect OddsAPI credits. One live interval
        means at most one fetch per live tick -- never zero bound."""
        os.environ["SYNDICATE_WNBA_LIVE_REFRESH_INTERVAL_SECONDS"] = "300"
        self.assertEqual(self.module._reuse_max_age_seconds("wnba", phase="live"), 300.0)
        os.environ["SYNDICATE_WNBA_LIVE_REUSE_MAX_AGE_SECONDS"] = "90"
        self.assertEqual(self.module._reuse_max_age_seconds("wnba", phase="live"), 90.0)
        # Junk and non-positive values fall through rather than disabling the bound.
        os.environ["SYNDICATE_WNBA_LIVE_REUSE_MAX_AGE_SECONDS"] = "not-a-number"
        os.environ["SYNDICATE_WNBA_LIVE_REFRESH_INTERVAL_SECONDS"] = "0"
        self.assertEqual(self.module._reuse_max_age_seconds("wnba", phase="live"), 240.0)


class _BundleFixture:
    """Builds a bundle complete enough that only the AGE gate can decline it."""

    def __init__(self, root: Path, date_str: str) -> None:
        self.root = root
        self.date_str = date_str
        raw = root / "data" / "raw"
        processed = root / "data" / "processed"
        raw.mkdir(parents=True, exist_ok=True)
        processed.mkdir(parents=True, exist_ok=True)
        self.snapshot = raw / f"odds_wnba_player_props_{date_str}.csv"
        files = [
            self.snapshot,
            processed / f"oddsapi_player_props_{date_str}.csv",
            processed / f"predictions_{date_str}.csv",
            processed / f"props_predictions_{date_str}.csv",
            processed / f"props_edges_{date_str}.csv",
            processed / f"props_recommendations_{date_str}.csv",
            processed / f"game_cards_{date_str}.csv",
        ]
        for path in files:
            path.write_text("a,b\n1,2\n", encoding="utf-8")
        (processed / f"recommendations_slate_{date_str}.json").write_text(
            '{"per_game": []}', encoding="utf-8"
        )

    def age_snapshot(self, seconds: float) -> None:
        old = time.time() - seconds
        os.utime(self.snapshot, (old, old))


class GuardBranchTests(unittest.TestCase):
    """Both reuse branches must decline a stale-for-live bundle.

    The ages chosen straddle the two bounds on purpose: 600s is FRESH for the
    2h pregame bound and STALE for the 240s live bound, which is exactly the
    window production sat in for a whole game.
    """

    DATE = "2026-08-20"

    def setUp(self) -> None:
        self.module = _load_module()
        self._saved = {name: os.environ.pop(name, None) for name in _RELEVANT_ENV}
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.fixture = _BundleFixture(self.root, self.DATE)

    def tearDown(self) -> None:
        self._tmp.cleanup()
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def _bundle(self, phase):
        return self.module._existing_artifact_bundle_state(
            artifact_root=self.root,
            date_str=self.DATE,
            do_edges=True,
            do_export=True,
            phase=phase,
        )

    def _source(self, phase):
        # step_key/input_hash left None so `should_recompute` cannot be the term
        # that decides this test -- the age gate must be what declines.
        return self.module._existing_refresh_state(
            source_root=self.root,
            date_str=self.DATE,
            do_edges=True,
            do_export=True,
            phase=phase,
        )

    def test_bundle_branch_reuses_at_600s_for_pregame_and_declines_for_live(self) -> None:
        """THE REGRESSION TEST. 600s old: reusable under the pregame bound,
        stale under the live bound. Before the fix both returned a state."""
        self.fixture.age_snapshot(600)
        self.assertIsNotNone(self._bundle("pregame"), "pregame behaviour must be unchanged")
        self.assertIsNone(self._bundle("live"), "a live tick must DECLINE and fetch")

    def test_source_branch_reuses_at_600s_for_pregame_and_declines_for_live(self) -> None:
        """The branch that had no age bound at all. Same assertion, because
        fixing only the branch observed failing is the forbidden move."""
        self.fixture.age_snapshot(600)
        self.assertIsNotNone(self._source("pregame"), "pregame behaviour must be unchanged")
        self.assertIsNone(self._source("live"), "a live tick must DECLINE and fetch")

    def test_fresh_bundle_is_still_reused_on_a_live_tick(self) -> None:
        """The live bound must not degenerate into 'always fetch' -- that would
        be `#383`'s bug inverted and would spend credits every tick."""
        self.fixture.age_snapshot(30)
        self.assertIsNotNone(self._bundle("live"))
        self.assertIsNotNone(self._source("live"))

    def test_the_BOUND_is_what_discriminates_not_the_phase_argument(self) -> None:
        """Isolate the term that changed.

        Every other test here varies `phase`, which also changed the function
        SIGNATURE -- so against the old code they fail with TypeError, proving
        only that the argument is new. This one holds the signature fixed and
        moves ONLY the number: with the live bound configured equal to the
        pregame bound, a live tick reuses the same 600s bundle it otherwise
        declines. If this test ever fails, something other than the age bound is
        deciding, and the fix is not what the ledger says it is.
        """
        self.fixture.age_snapshot(600)
        self.assertIsNone(self._bundle("live"), "600s must be stale at the 240s bound")
        os.environ["SYNDICATE_WNBA_LIVE_REUSE_MAX_AGE_SECONDS"] = str(2 * 3600)
        self.assertIsNotNone(
            self._bundle("live"), "same call, same fixture -- only the bound moved"
        )
        self.assertIsNotNone(self._source("live"))

    def test_missing_files_still_win_over_any_bound(self) -> None:
        """Existence is checked FIRST and still wins, in both branches."""
        self.fixture.snapshot.unlink()
        self.assertIsNone(self._bundle("pregame"))
        self.assertIsNone(self._bundle("live"))
        self.assertIsNone(self._source("pregame"))
        self.assertIsNone(self._source("live"))


class StepWiringTests(unittest.TestCase):
    """`--phase live` must actually reach the child, or the bound is unreachable.

    Presence of the flag in the command is the ONLY thing connecting the fix to
    production; without it every test above passes against a system that still
    starves.
    """

    def _build(self, phase: str):
        repo_root = Path(__file__).resolve().parents[1]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        name = "test_refresh_odds_sources_mod"
        spec = importlib.util.spec_from_file_location(
            name, repo_root / "scripts" / "refresh_odds_sources.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # REGISTER BEFORE EXEC. `RefreshStep` is a dataclass, and
        # `dataclasses` resolves annotations via `sys.modules[cls.__module__]`
        # -- absent that entry it raises AttributeError on None during class
        # creation, which looks like a defect in the script under test and is
        # not one.
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
        self.addCleanup(sys.modules.pop, name, None)
        import argparse

        args = argparse.Namespace(
            date="2026-08-20",
            regions="us",
            phase=phase,
            markets="",
            bookmakers="",
        )
        with patch.object(module, "_basketball_source_root", return_value=Path("/tmp/src")), \
             patch.object(module, "_venv_python", return_value="python"), \
             patch.object(module, "_local_source_artifact_root", return_value=Path("/tmp/art")), \
             patch.object(
                 module,
                 "_build_nba_payload",
                 return_value={"WNBA_BETTING_ODDSAPI_PROPS_JOB": '{"log_file": "x", "started_at": "y"}'},
             ):
            steps = module._build_wnba_steps(args)
        return list(steps[0].command)

    def test_live_phase_forwards_the_flag(self) -> None:
        command = self._build("live")
        self.assertIn("--phase", command)
        self.assertEqual(command[command.index("--phase") + 1], "live")

    def test_pregame_and_all_do_not_forward_it(self) -> None:
        """`all` is a combined sweep, not a live tick. Saying nothing is the
        safe branch because the child defaults to pregame."""
        for phase in ("pregame", "all"):
            with self.subTest(phase=phase):
                self.assertNotIn("--phase", self._build(phase))


if __name__ == "__main__":
    unittest.main()
