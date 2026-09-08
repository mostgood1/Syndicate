"""The MLB prop pregame seal fires on the pass's OWN fetch, and lands where the
grading builder can see it — `#611`, the two halves that survived `9a768443`.

`9a768443` made the seal SOURCE from every tree, and production confirmed it
fires (2026-09-06..09-08). Two things were still wrong, measured 2026-09-08:

  1. ORDER. `_refresh_source_artifacts` froze BEFORE it fetched, so a pass
     could only seal a doc some earlier pass had left in the checkout. After a
     deploy the checkout is empty and there is often one MLB pass per date, so
     2026-09-02..09-05 sealed nothing against rich pre-slate captures every
     day. The freeze now also runs AFTER the fetch.
  2. PLACE. The seal reached the other service only at
     `<bundle>/data/daily/snapshots/<date>/`; the builder's roots are
     `<bundle>/source_artifacts/data/...`. The 09-06 card, built 32 hours after
     a 644KB seal existed, read the live post-slate remnant. The freeze now
     also lands under `MLB_BETTING_DATA_ROOT/daily/snapshots/<date>`.

`test_a_live_phase_pass_does_not_overwrite_the_seal` is the guard the task
asked for by name: the post-fetch freeze must never let a post-slate fetch
(an empty market) replace a real pregame capture.
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
        "refresh_mlb_oddsapi_post_fetch_under_test", REPO_ROOT / "scripts" / "refresh_mlb_oddsapi.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _load_module()
DATE = "2026-09-08"
SLUG = "2026_09_08"
FUTURE = "2099-09-08T23:00:00Z"


def _props_doc(family: str, priced: int) -> dict:
    entries = {}
    for index in range(priced // 2):
        entries[f"market_{index}"] = {"line": 1.5, "over_odds": -110, "under_odds": -110}
    return {"date": DATE, "mode": "live", family: ({"Player One": entries} if entries else {})}


class _FakeOddsModule:
    """Stands in for `fetch_mlb_oddsapi_local`: writes the three live docs to
    `out_dir` exactly as the real fetch does, and returns their paths."""

    def __init__(self, *, commence_time: str, priced: int) -> None:
        self.commence_time = commence_time
        self.priced = priced
        self.calls = 0

    def fetch_and_write_live_odds_for_date(self, date_str, *, out_dir, overwrite=True, regions="us"):
        self.calls += 1
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = str(date_str).replace("-", "_")
        game_lines = out_dir / f"oddsapi_game_lines_{slug}.json"
        pitcher = out_dir / f"oddsapi_pitcher_props_{slug}.json"
        hitter = out_dir / f"oddsapi_hitter_props_{slug}.json"
        game_lines.write_text(
            json.dumps(
                {
                    "date": date_str,
                    "mode": "live",
                    "games": [{"event_id": "e1", "commence_time": self.commence_time, "home_team": "H", "away_team": "A"}],
                }
            ),
            encoding="utf-8",
        )
        pitcher.write_text(json.dumps(_props_doc("pitcher_props", self.priced)), encoding="utf-8")
        hitter.write_text(json.dumps(_props_doc("hitter_props", self.priced)), encoding="utf-8")
        return {
            "status": "ok",
            "date": str(date_str),
            "out_dir": str(out_dir),
            "game_lines_path": str(game_lines),
            "pitcher_props_path": str(pitcher),
            "hitter_props_path": str(hitter),
        }


def _frozen_clock(now_iso: str):
    """A `datetime` whose `now()` is pinned. A subclass, so `fromisoformat`
    and friends keep working for the commence-time parser in the same pass."""
    from datetime import datetime as _real_datetime

    fixed = _real_datetime.fromisoformat(now_iso.replace("Z", "+00:00"))

    class _Frozen(_real_datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D401 - mirrors datetime.now
            return fixed if tz is None else fixed.astimezone(tz)

    return _Frozen


def _run_pass(root: Path, odds_module: _FakeOddsModule, *, now: str | None = None) -> str:
    """One `_refresh_source_artifacts` pass with the side stages stubbed out.
    Returns everything the pass printed. `now` pins the freeze's clock."""
    clock = patch.object(MOD, "datetime", _frozen_clock(now)) if now else patch.object(MOD, "datetime", MOD.datetime)
    with clock, patch.object(MOD, "_archive_oddsapi_refresh_outputs", return_value={}), patch.object(
        MOD, "_refresh_live_lens_artifacts", return_value={}
    ), patch.object(MOD, "publish_hot_artifact", return_value=True), patch("builtins.print") as printer:
        MOD._refresh_source_artifacts(
            odds_module=odds_module, source_root=root, date_str=DATE, regions="us", overwrite=True
        )
    return " ".join(str(call.args[0]) for call in printer.call_args_list if call.args)


def _clear_env() -> None:
    MOD.os.environ.pop("MLB_BETTING_DATA_ROOT", None)
    MOD.os.environ.pop("MLB_BETTING_DATA_ROOT_DIR", None)


def _seal(root: Path, prefix: str) -> Path:
    return root / "data" / "daily" / "snapshots" / DATE / f"{prefix}_{SLUG}_pregame.json"


class SealsItsOwnFetchTests(unittest.TestCase):
    def test_a_single_pregame_pass_seals_its_own_fetch(self) -> None:
        """THE ORDER FIX. A fresh tree (post-deploy checkout), one pass, rich
        pre-slate props: both prop families must be sealed by the time the
        pass ends. Before this change the pre-fetch freeze found no doc and
        the pass ended with no seal."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "mlb_source"
            _clear_env()
            printed = _run_pass(root, _FakeOddsModule(commence_time=FUTURE, priced=6))
            for prefix in ("oddsapi_hitter_props", "oddsapi_pitcher_props"):
                self.assertTrue(_seal(root, prefix).exists(), f"{prefix} must be sealed by its own pass")
                self.assertEqual(MOD._oddsapi_props_richness(_seal(root, prefix)), 6)
            self.assertIn("PROP_FREEZE_WROTE", printed)
            self.assertIn("stage=post_fetch", printed)
            # The freeze's own record names the seal, per family.
            meta = json.loads((root / "data" / "live_lens" / "cron_meta" / "latest_refresh_oddsapi.json").read_text(encoding="utf-8"))
            frozen = meta.get("frozenPregame") or {}
            self.assertTrue(any("hitter_props" in key and key.endswith("_pregame.json") for key in frozen))
            self.assertTrue(any("pitcher_props" in key and key.endswith("_pregame.json") for key in frozen))

    def test_the_pre_fetch_freeze_still_runs_and_names_its_miss(self) -> None:
        """The pre-fetch pass is kept (it is what seals an earlier pass's doc
        when THIS pass's fetch fails), and its miss stays named."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "mlb_source"
            _clear_env()
            printed = _run_pass(root, _FakeOddsModule(commence_time=FUTURE, priced=6))
            self.assertIn("stage=pre_fetch reason=no_live_doc_in_any_tree", printed)


class SealSurvivesLaterPassesTests(unittest.TestCase):
    def test_a_live_phase_pass_does_not_overwrite_the_seal(self) -> None:
        """The task's named guard. Pass 1 pregame and rich; pass 2 after
        first pitch with the empty market books leave once games start. The
        live file IS rewritten (that is the live refresh's job); the seal is
        NOT (that is the seal's)."""
        first_pitch = "2026-09-08T23:05:00Z"
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "mlb_source"
            _clear_env()
            _run_pass(root, _FakeOddsModule(commence_time=first_pitch, priced=6), now="2026-09-08T14:00:00Z")
            self.assertEqual(MOD._oddsapi_props_richness(_seal(root, "oddsapi_hitter_props")), 6)
            # Same game, same first pitch; the clock is now seven minutes past it
            # (the 2026-08-31 shape: one MLB pass, 22:12Z against a 22:05Z slate).
            printed = _run_pass(root, _FakeOddsModule(commence_time=first_pitch, priced=0), now="2026-09-08T23:12:00Z")
            live = root / "data" / "market" / "oddsapi" / f"oddsapi_hitter_props_{SLUG}.json"
            self.assertEqual(MOD._oddsapi_props_richness(live), 0, "the live doc must reflect the post-slate fetch")
            self.assertEqual(MOD._oddsapi_props_richness(_seal(root, "oddsapi_hitter_props")), 6)
            self.assertEqual(MOD._oddsapi_props_richness(_seal(root, "oddsapi_pitcher_props")), 6)
            self.assertIn("stage=post_fetch reason=slate_started", printed)
            # And the game-line seal kept the started game rather than dropping it.
            frozen_lines = json.loads(_seal(root, "oddsapi_game_lines").read_text(encoding="utf-8"))
            self.assertEqual([g["event_id"] for g in frozen_lines["games"]], ["e1"])

    def test_a_thinner_pregame_fetch_does_not_downgrade_the_seal(self) -> None:
        """Monotonicity through the post-fetch path: still pregame, but the
        book pulled half its markets. The richer seal stands."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "mlb_source"
            _clear_env()
            _run_pass(root, _FakeOddsModule(commence_time=FUTURE, priced=6))
            printed = _run_pass(root, _FakeOddsModule(commence_time=FUTURE, priced=2))
            self.assertEqual(MOD._oddsapi_props_richness(_seal(root, "oddsapi_hitter_props")), 6)
            self.assertIn("reason=not_richer_than_existing", printed)

    def test_a_richer_pregame_fetch_upgrades_the_seal(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "mlb_source"
            _clear_env()
            _run_pass(root, _FakeOddsModule(commence_time=FUTURE, priced=2))
            _run_pass(root, _FakeOddsModule(commence_time=FUTURE, priced=8))
            self.assertEqual(MOD._oddsapi_props_richness(_seal(root, "oddsapi_hitter_props")), 8)


class SealLandsWhereTheReaderLooksTests(unittest.TestCase):
    """THE PLACE FIX. With `MLB_BETTING_DATA_ROOT` set (as on every service
    that runs this), the seal must also land under that root's
    `daily/snapshots/<date>` -- the tree the builder searches AND the
    relative path the cross-service pull preserves."""

    def test_prop_and_game_line_seals_land_in_the_env_root_snapshot_tree(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "mlb_source"
            env_root = bundle / "source_artifacts" / "data"
            with patch.dict(MOD.os.environ, {"MLB_BETTING_DATA_ROOT": str(env_root)}, clear=False):
                MOD.os.environ.pop("MLB_BETTING_DATA_ROOT_DIR", None)
                _run_pass(bundle, _FakeOddsModule(commence_time=FUTURE, priced=6))
                snapshot_dirs = MOD._freeze_snapshot_dirs(bundle, DATE)
            self.assertEqual(len(snapshot_dirs), 2)
            env_snapshots = env_root.resolve() / "daily" / "snapshots" / DATE
            for name in (
                f"oddsapi_hitter_props_{SLUG}_pregame.json",
                f"oddsapi_pitcher_props_{SLUG}_pregame.json",
                f"oddsapi_game_lines_{SLUG}_pregame.json",
            ):
                self.assertTrue((env_snapshots / name).exists(), f"{name} missing from {env_snapshots}")
                self.assertTrue((bundle / "data" / "daily" / "snapshots" / DATE / name).exists())

    def test_without_the_env_var_only_the_writers_own_snapshot_dir_is_used(self) -> None:
        with TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "mlb_source"
            _clear_env()
            self.assertEqual(MOD._freeze_snapshot_dirs(bundle, DATE), [bundle / "data" / "daily" / "snapshots" / DATE])


if __name__ == "__main__":
    unittest.main()
