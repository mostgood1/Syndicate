"""The MLB prop pregame seal reads every tree, and names every refusal — `#611`.

The prop seal stopped on 2026-08-16 and produced ZERO files for sixteen days
while GAME LINES sealed normally on the same runs (2026-09-01: a 15-game
game-line freeze and zero prop seals, from three passes that each ran ~8 hours
BEFORE first pitch). The asymmetry lived inside one loop body:

  - `best_frozen` was computed across EVERY `market_dir` — its own comment says
    *"'Already frozen' is asked of EVERY tree, not just this one"*;
  - the SOURCE doc was read from `market_dirs[0]` alone, and a miss was a bare
    `continue` that emitted nothing.

Game lines cannot fail that way because `_merge_pregame_game_lines` seeds from
every copy. `market_dirs[0]` is the tree the fetch writes to LATER in the same
pass, and git tracks zero files under it.

`test_a_refusal_names_itself` and its siblings matter as much as the fix: `#611`
spent three sessions unable to say which branch stopped the seal, because all
three refusals were silent.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "refresh_mlb_oddsapi_under_test", REPO_ROOT / "scripts" / "refresh_mlb_oddsapi.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _load_module()
DATE = "2026-09-01"
SLUG = "2026_09_01"


def _props_doc(*, family: str = "hitter_props", priced: int = 4) -> str:
    """A doc `_oddsapi_props_richness` scores at `priced` (it counts PRICED SIDES)."""
    entries = {}
    for index in range(priced // 2):
        entries[f"market_{index}"] = {"line": 1.5, "over_odds": -110, "under_odds": -110}
    return json.dumps({family: {"Player One": entries}})


class SealReadsEveryTreeTests(unittest.TestCase):
    """The fix: a live doc in ANY tree can be sealed."""

    def _freeze(self, *, place_in: str, priced: int = 4, env_root: Path | None = None):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "mlb_source"
            trees = {
                "checkout": root / "data" / "market" / "oddsapi",
                "artifacts": root / "source_artifacts" / "data" / "market" / "oddsapi",
            }
            if env_root is not None:
                trees["env"] = env_root / "market" / "oddsapi"
            target = trees[place_in]
            target.mkdir(parents=True, exist_ok=True)
            for prefix in ("oddsapi_hitter_props", "oddsapi_pitcher_props"):
                family = "hitter_props" if "hitter" in prefix else "pitcher_props"
                (target / f"{prefix}_{SLUG}.json").write_text(
                    _props_doc(family=family, priced=priced), encoding="utf-8"
                )
            environ = {"MLB_BETTING_DATA_ROOT": str(env_root)} if env_root else {}
            with patch.dict(MOD.os.environ, environ, clear=False):
                if not env_root:
                    MOD.os.environ.pop("MLB_BETTING_DATA_ROOT", None)
                    MOD.os.environ.pop("MLB_BETTING_DATA_ROOT_DIR", None)
                copied = MOD._freeze_oddsapi_pregame_markets(source_root=root, date_str=DATE)
            return copied, root

    def test_a_doc_only_in_the_first_tree_still_seals(self) -> None:
        """The unchanged case — this must not regress."""
        copied, _root = self._freeze(place_in="checkout")
        self.assertTrue(any("_pregame.json" in key for key in copied))

    def test_a_doc_only_in_a_LATER_tree_now_seals(self) -> None:
        """THE `#611` FIX. Before this, the source was `market_dirs[0]` alone,
        so a doc living only in the artifacts tree sealed nothing, silently."""
        copied, _root = self._freeze(place_in="artifacts")
        self.assertTrue(
            any("_pregame.json" in key for key in copied),
            "a live doc in a non-first tree must be sealable",
        )

    def test_the_seal_reaches_the_snapshot_path_the_export_can_see(self) -> None:
        """`#611` was diagnosed through
        `/api/ops/artifacts/export?pattern=*oddsapi_*props_*_pregame.json`, which
        reads `daily/snapshots/` — so a seal that never lands there is invisible
        to the instrument that would confirm it."""
        copied, _root = self._freeze(place_in="artifacts")
        self.assertTrue(
            any("snapshots" in key and "_pregame.json" in key for key in copied),
            f"no snapshot destination among {list(copied)}",
        )

    def test_both_prop_families_seal(self) -> None:
        copied, _root = self._freeze(place_in="artifacts")
        self.assertTrue(any("hitter_props" in key and "_pregame" in key for key in copied))
        self.assertTrue(any("pitcher_props" in key and "_pregame" in key for key in copied))


class RefusalsAreNamedTests(unittest.TestCase):
    """`#611` could not say WHICH branch refused, because all three were bare
    `continue`s. Each now emits a reason."""

    def _run_and_capture(self, *, build) -> str:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "mlb_source"
            build(root)
            MOD.os.environ.pop("MLB_BETTING_DATA_ROOT", None)
            MOD.os.environ.pop("MLB_BETTING_DATA_ROOT_DIR", None)
            with patch("builtins.print") as printer:
                MOD._freeze_oddsapi_pregame_markets(source_root=root, date_str=DATE)
            return " ".join(str(call.args[0]) for call in printer.call_args_list if call.args)

    def test_no_live_doc_in_any_tree_is_named(self) -> None:
        """The reason that FALSIFIES this change's own hypothesis: if this is
        what production reports, the doc is in no tree at freeze time and the
        cause is upstream, not the single-directory read."""
        printed = self._run_and_capture(build=lambda root: root.mkdir(parents=True, exist_ok=True))
        self.assertIn("PROP_FREEZE_SKIPPED", printed)
        self.assertIn("reason=no_live_doc_in_any_tree", printed)

    def test_a_poorer_doc_is_refused_by_name_and_the_seal_survives(self) -> None:
        def _build(root: Path) -> None:
            tree = root / "data" / "market" / "oddsapi"
            tree.mkdir(parents=True, exist_ok=True)
            (tree / f"oddsapi_hitter_props_{SLUG}.json").write_text(_props_doc(priced=2), encoding="utf-8")
            (tree / f"oddsapi_hitter_props_{SLUG}_pregame.json").write_text(
                _props_doc(priced=8), encoding="utf-8"
            )

        printed = self._run_and_capture(build=_build)
        self.assertIn("reason=not_richer_than_existing", printed)

    def test_a_successful_seal_reports_which_tree_it_came_from(self) -> None:
        def _build(root: Path) -> None:
            tree = root / "source_artifacts" / "data" / "market" / "oddsapi"
            tree.mkdir(parents=True, exist_ok=True)
            (tree / f"oddsapi_hitter_props_{SLUG}.json").write_text(_props_doc(priced=6), encoding="utf-8")

        printed = self._run_and_capture(build=_build)
        self.assertIn("PROP_FREEZE_WROTE", printed)
        self.assertIn("source_tree_index=", printed)


class MonotonicityAndTieBreakPreservedTests(unittest.TestCase):
    """The fix must not weaken the two rules the seal already had."""

    def test_a_richer_doc_still_replaces_a_poorer_seal(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "mlb_source"
            tree = root / "data" / "market" / "oddsapi"
            tree.mkdir(parents=True, exist_ok=True)
            frozen = tree / f"oddsapi_hitter_props_{SLUG}_pregame.json"
            frozen.write_text(_props_doc(priced=2), encoding="utf-8")
            (tree / f"oddsapi_hitter_props_{SLUG}.json").write_text(_props_doc(priced=8), encoding="utf-8")
            MOD.os.environ.pop("MLB_BETTING_DATA_ROOT", None)
            MOD.os.environ.pop("MLB_BETTING_DATA_ROOT_DIR", None)
            MOD._freeze_oddsapi_pregame_markets(source_root=root, date_str=DATE)
            self.assertEqual(MOD._oddsapi_props_richness(frozen), 8)

    def test_a_tie_keeps_the_writers_own_tree(self) -> None:
        """`max` returns the FIRST maximum, so equal richness is byte-identical
        to the pre-fix behaviour."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "mlb_source"
            first = root / "data" / "market" / "oddsapi"
            later = root / "source_artifacts" / "data" / "market" / "oddsapi"
            for tree in (first, later):
                tree.mkdir(parents=True, exist_ok=True)
                (tree / f"oddsapi_hitter_props_{SLUG}.json").write_text(_props_doc(priced=4), encoding="utf-8")
            MOD.os.environ.pop("MLB_BETTING_DATA_ROOT", None)
            MOD.os.environ.pop("MLB_BETTING_DATA_ROOT_DIR", None)
            with patch("builtins.print") as printer:
                MOD._freeze_oddsapi_pregame_markets(source_root=root, date_str=DATE)
            printed = " ".join(str(call.args[0]) for call in printer.call_args_list if call.args)
            self.assertIn("source_tree_index=0", printed)


class GameLineFreezeUntouchedTests(unittest.TestCase):
    """Game lines were never broken; the change must not touch them."""

    def test_game_lines_still_seal_from_their_own_tree(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "mlb_source"
            tree = root / "data" / "market" / "oddsapi"
            tree.mkdir(parents=True, exist_ok=True)
            (tree / f"oddsapi_game_lines_{SLUG}.json").write_text(
                json.dumps({"games": [{"event_id": "e1", "commence_time": "2099-09-01T23:00:00Z"}]}),
                encoding="utf-8",
            )
            MOD.os.environ.pop("MLB_BETTING_DATA_ROOT", None)
            MOD.os.environ.pop("MLB_BETTING_DATA_ROOT_DIR", None)
            copied = MOD._freeze_oddsapi_pregame_markets(source_root=root, date_str=DATE)
        self.assertTrue(any("game_lines" in key and "_pregame" in key for key in copied))


if __name__ == "__main__":
    unittest.main()
