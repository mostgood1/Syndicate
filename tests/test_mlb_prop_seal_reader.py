"""The grading builder finds the MLB prop pregame seal where the cross-service
pull puts it, ranks prop docs by priced sides, and NAMES the doc it read — `#611`.

Measured 2026-09-08 on production: the 2026-09-06 hitter seal (644KB) sat at
`mlb_source/data/daily/snapshots/2026-09-06/` on web for 32 hours before the
09-06 card was built, and the card read the live post-slate remnant under
`source_artifacts/data/market/oddsapi/` instead -- `raw_candidates_n: 0` on
every prop market. `_odds_data_roots` searched `MLB_BETTING_DATA_ROOT`
(`<bundle>/source_artifacts/data`) and never the sibling `<bundle>/data`
tree the pulled seal lives in.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MODULE_PATH = _REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "eval" / "build_season_betting_cards_manifest.py"

DATE = "2026-09-06"
SLUG = "2026_09_06"


def _load_module():
    spec = importlib.util.spec_from_file_location("_bscm_prop_seal_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        # Heavy sim-engine imports are not needed for path resolution; a
        # partially-initialised module still exposes the functions under test.
        pass
    return module


def _props_doc(family: str, priced: int, players: int = 1) -> str:
    entries = {}
    for index in range(priced // 2):
        entries[f"market_{index}"] = {"line": 1.5, "over_odds": -110, "under_odds": -110}
    return json.dumps({family: {f"Player {n}": dict(entries) for n in range(players)}})


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class PulledSealIsFoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()
        if not hasattr(cls.module, "_odds_paths"):
            raise unittest.SkipTest("vendored module did not expose _odds_paths")

    def test_the_sibling_data_tree_is_searched_when_env_root_is_source_artifacts(self) -> None:
        """THE PRODUCTION LAYOUT. Live remnant where the builder always looked;
        seal only where the pull put it. The seal must win."""
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "mlb_source"
            env_root = bundle / "source_artifacts" / "data"
            _write(env_root / "market" / "oddsapi" / f"oddsapi_hitter_props_{SLUG}.json", _props_doc("hitter_props", 2))
            seal = _write(
                bundle / "data" / "daily" / "snapshots" / DATE / f"oddsapi_hitter_props_{SLUG}_pregame.json",
                _props_doc("hitter_props", 40, players=5),
            )
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(env_root)}, clear=False):
                os.environ.pop("MLB_BETTING_DATA_ROOT_DIR", None)
                roots = self.module._odds_data_roots()
                paths = self.module._odds_paths(DATE)
            self.assertIn((bundle / "data").resolve(), [Path(r).resolve() for r in roots])
            self.assertEqual(paths["hitter_lines"].resolve(), seal.resolve())

    def test_a_plain_env_root_does_not_grow_a_phantom_sibling(self) -> None:
        """Only the `<bundle>/source_artifacts/data` shape has a sibling; a
        root named anything else must not gain an invented one."""
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "mounted" / "data"
            data_root.mkdir(parents=True)
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(data_root)}, clear=False):
                roots = [Path(r).resolve() for r in self.module._odds_data_roots()]
            self.assertNotIn((Path(tmp) / "data").resolve(), roots)


class PropTierRanksByPricedSidesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()
        if not hasattr(cls.module, "_odds_doc_props_richness"):
            raise unittest.SkipTest("vendored module did not expose _odds_doc_props_richness")

    def test_within_a_tier_the_richer_props_doc_wins_regardless_of_order(self) -> None:
        """Props docs have no `games`, so the game-count tiebreak scored every
        one of them 0 and the first-found doc won. Two live docs under one
        root: the thin one in the directory searched first, the rich one in
        the directory searched second."""
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            _write(data_root / "market" / "oddsapi" / f"oddsapi_pitcher_props_{SLUG}.json", _props_doc("pitcher_props", 2))
            rich = _write(
                data_root / "daily" / "snapshots" / DATE / f"oddsapi_pitcher_props_{SLUG}.json",
                _props_doc("pitcher_props", 20),
            )
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(data_root)}, clear=False):
                paths = self.module._odds_paths(DATE)
            self.assertEqual(paths["pitcher_lines"].resolve(), rich.resolve())

    def test_a_freeze_still_beats_a_richer_live_doc(self) -> None:
        """Richness never promotes a live doc over a freeze -- the freeze is
        the correct PRICE for grading even when thinner."""
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            _write(data_root / "market" / "oddsapi" / f"oddsapi_hitter_props_{SLUG}.json", _props_doc("hitter_props", 40))
            seal = _write(
                data_root / "market" / "oddsapi" / f"oddsapi_hitter_props_{SLUG}_pregame.json",
                _props_doc("hitter_props", 4),
            )
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(data_root)}, clear=False):
                paths = self.module._odds_paths(DATE)
            self.assertEqual(paths["hitter_lines"].resolve(), seal.resolve())

    def test_game_lines_still_rank_by_game_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            _write(data_root / "market" / "oddsapi" / f"oddsapi_game_lines_{SLUG}.json", json.dumps({"games": [{"event_id": "a"}]}))
            full = _write(
                data_root / "daily" / "snapshots" / DATE / f"oddsapi_game_lines_{SLUG}.json",
                json.dumps({"games": [{"event_id": "a"}, {"event_id": "b"}, {"event_id": "c"}]}),
            )
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(data_root)}, clear=False):
                paths = self.module._odds_paths(DATE)
            self.assertEqual(paths["game_lines"].resolve(), full.resolve())


class ReadLinesAreNamedTests(unittest.TestCase):
    """`Game lines read: <path> (pregame-freeze|live, N games)` exists for game
    lines; props now say the same, so `raw_candidates_n: 0` on every prop market
    is readable next to the doc that produced it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()
        for name in ("_collect_report_hitter_recommendations", "_collect_report_pitcher_recommendations"):
            if not hasattr(cls.module, name):
                raise unittest.SkipTest(f"vendored module did not expose {name}")

    def _report(self) -> dict:
        return {"meta": {"date": DATE}, "games": []}

    def test_hitter_read_line_names_the_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            _write(
                data_root / "daily" / "snapshots" / DATE / f"oddsapi_hitter_props_{SLUG}_pregame.json",
                _props_doc("hitter_props", 4, players=3),
            )
            warnings: list = []
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(data_root)}, clear=False):
                self.module._collect_report_hitter_recommendations(self._report(), {}, warnings)
        line = next((w for w in warnings if w.startswith("Hitter lines read:")), None)
        self.assertIsNotNone(line, warnings)
        self.assertIn("(pregame-freeze, 3 players)", line)
        self.assertIn(f"oddsapi_hitter_props_{SLUG}_pregame.json", line)

    def test_pitcher_read_line_names_a_live_doc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            _write(
                data_root / "market" / "oddsapi" / f"oddsapi_pitcher_props_{SLUG}.json",
                _props_doc("pitcher_props", 2, players=2),
            )
            warnings: list = []
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(data_root)}, clear=False):
                self.module._collect_report_pitcher_recommendations(self._report(), {}, warnings)
        line = next((w for w in warnings if w.startswith("Pitcher lines read:")), None)
        self.assertIsNotNone(line, warnings)
        self.assertIn("(live, 2 players)", line)

    def test_pitcher_collector_still_accepts_the_two_argument_call(self) -> None:
        """Every other caller passes no warnings list; that must keep working."""
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            data_root.mkdir(parents=True)
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(data_root)}, clear=False):
                rows = self.module._collect_report_pitcher_recommendations(self._report(), {})
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
