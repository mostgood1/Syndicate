"""The pregame odds freeze, and the grading builder that reads it.

Both halves were dead, which is why a full MLB slate graded ONE row.

WRITE side (`_freeze_oddsapi_pregame_markets`): the guard was
`mode == "live" -> skip`, and every writer of these files stamps
`"mode": "live"`. The condition was unconditionally true, so the freeze was
unreachable -- production held zero `*_pregame.json` files (count=0,
untruncated, 2026-08-08).

READ side (`_odds_paths`): the builder only ever looked for the live
filename, so even a frozen file would not have been read.

Why it matters: the live file is rewritten all day with only the events
still in progress. Measured in production -- 2026-08-05 13 games -> 1,
08-06 4 -> 1, 08-07 14 -> 2, each last written ~04:30Z the following day.
The builder joins the day's report against that file, warns
`Missing game-line match` for every vanished game, and grades one row. No
graded rows -> settlement matches nothing -> the ledger stays fully
pending, gating CLV and every weight derived from it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BUILDER_PATH = _REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "eval" / "build_season_betting_cards_manifest.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("_bscm_pregame_under_test", _BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        # Heavy sim-engine imports are not needed for path resolution; a
        # partially-initialised module still exposes the function under test.
        pass
    return module


def _load_refresh():
    import scripts.refresh_mlb_oddsapi as mod

    return mod


def _game_lines_doc(commence: datetime, *, games: int = 3) -> dict:
    return {
        "date": "2026-08-07",
        "mode": "live",
        "games": [
            {
                "event_id": f"evt{i}",
                "commence_time": commence.isoformat().replace("+00:00", "Z"),
                "home_team": f"Home {i}",
                "away_team": f"Away {i}",
                "markets": {"h2h": {"home_odds": "-110", "away_odds": "-110"}},
            }
            for i in range(games)
        ],
    }


class PregameFreezeWriteTests(unittest.TestCase):
    """The freeze must fire on a live-stamped doc -- that is the whole bug."""

    def setUp(self) -> None:
        self.refresh = _load_refresh()
        self._tmp = tempfile.TemporaryDirectory()
        self.source_root = Path(self._tmp.name) / "mlb_source"
        self.market_dir = self.source_root / "data" / "market" / "oddsapi"
        self.market_dir.mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)

    def _write_lines(self, doc: dict) -> Path:
        path = self.market_dir / "oddsapi_game_lines_2026_08_07.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_freezes_a_live_stamped_doc_before_first_pitch(self) -> None:
        """The regression. Every real doc says mode=live; the old guard made
        that alone a reason to skip, so nothing was ever frozen."""
        future = datetime.now(timezone.utc) + timedelta(hours=3)
        self._write_lines(_game_lines_doc(future))

        copied = self.refresh._freeze_oddsapi_pregame_markets(
            source_root=self.source_root, date_str="2026-08-07"
        )

        frozen = self.market_dir / "oddsapi_game_lines_2026_08_07_pregame.json"
        self.assertTrue(frozen.exists(), "a live-stamped pregame doc must still be frozen")
        # `copied` is keyed by FULL PATH, not basename: the freeze now lands in
        # every tree the grading builder might resolve odds against, and those
        # copies share one filename -- a name-keyed dict reported one of them
        # and hid the rest, which is precisely the divergence being fixed.
        self.assertTrue(
            any(Path(key).name == "oddsapi_game_lines_2026_08_07_pregame.json" for key in copied),
            f"the freeze should be reported in the return value: {sorted(copied)}",
        )
        self.assertEqual(len(json.loads(frozen.read_text(encoding="utf-8"))["games"]), 3)

    def test_freeze_is_sealed_once_the_slate_starts(self) -> None:
        """The freeze must hold the full slate, not be overwritten by the
        collapsed live file that comes later."""
        past = datetime.now(timezone.utc) - timedelta(hours=3)
        frozen = self.market_dir / "oddsapi_game_lines_2026_08_07_pregame.json"
        frozen.write_text(json.dumps(_game_lines_doc(past, games=14)), encoding="utf-8")
        # The live file has since collapsed to the last game standing.
        self._write_lines(_game_lines_doc(past, games=1))

        self.refresh._freeze_oddsapi_pregame_markets(source_root=self.source_root, date_str="2026-08-07")

        self.assertEqual(
            len(json.loads(frozen.read_text(encoding="utf-8"))["games"]),
            14,
            "a started slate must not overwrite the sealed pregame freeze",
        )

    def test_freeze_refreshes_while_still_pregame(self) -> None:
        """Later is better before first pitch -- it converges on the close."""
        future = datetime.now(timezone.utc) + timedelta(hours=2)
        frozen = self.market_dir / "oddsapi_game_lines_2026_08_07_pregame.json"
        frozen.write_text(json.dumps(_game_lines_doc(future, games=2)), encoding="utf-8")
        self._write_lines(_game_lines_doc(future, games=9))

        self.refresh._freeze_oddsapi_pregame_markets(source_root=self.source_root, date_str="2026-08-07")

        self.assertEqual(len(json.loads(frozen.read_text(encoding="utf-8"))["games"]), 9)

    def test_without_commence_times_the_first_freeze_is_not_clobbered(self) -> None:
        """No slate clock means we cannot prove we are pregame, so write once
        and never overwrite -- degrade toward keeping data, not losing it."""
        doc = _game_lines_doc(datetime.now(timezone.utc), games=5)
        for row in doc["games"]:
            row.pop("commence_time")
        frozen = self.market_dir / "oddsapi_game_lines_2026_08_07_pregame.json"
        frozen.write_text(json.dumps({"games": [{"event_id": "kept"}]}), encoding="utf-8")
        self._write_lines(doc)

        self.refresh._freeze_oddsapi_pregame_markets(source_root=self.source_root, date_str="2026-08-07")

        self.assertEqual(json.loads(frozen.read_text(encoding="utf-8"))["games"][0]["event_id"], "kept")

    def test_collapse_to_late_games_cannot_shrink_the_freeze(self) -> None:
        """The flaw a slate-wide clock has, caught by replaying the real
        2026-08-08 production doc: when the live file collapses to the late
        West-Coast games, those games have NOT started, so a slate-wide rule
        still reads "pregame" and overwrites a 15-game freeze with 2. Each
        game's own clock is what makes this safe.
        """
        now = datetime.now(timezone.utc)
        early = now - timedelta(hours=2)   # already under way
        late = now + timedelta(hours=4)    # first pitch still ahead
        full = {
            "games": [
                {"event_id": "early1", "commence_time": early.isoformat().replace("+00:00", "Z")},
                {"event_id": "early2", "commence_time": early.isoformat().replace("+00:00", "Z")},
                {"event_id": "late1", "commence_time": late.isoformat().replace("+00:00", "Z")},
            ]
        }
        frozen = self.market_dir / "oddsapi_game_lines_2026_08_07_pregame.json"
        frozen.write_text(json.dumps(full), encoding="utf-8")
        # Overnight the live file holds only the game still in progress.
        self._write_lines({"games": [full["games"][2]]})

        self.refresh._freeze_oddsapi_pregame_markets(source_root=self.source_root, date_str="2026-08-07")

        kept = {row["event_id"] for row in json.loads(frozen.read_text(encoding="utf-8"))["games"]}
        self.assertEqual(kept, {"early1", "early2", "late1"}, "the freeze must never lose a game")

    def test_started_games_keep_their_pregame_price(self) -> None:
        """A game under way must not have its frozen line replaced by a live
        one -- that price is what CLV is measured against."""
        now = datetime.now(timezone.utc)
        started = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        frozen = self.market_dir / "oddsapi_game_lines_2026_08_07_pregame.json"
        frozen.write_text(
            json.dumps({"games": [{"event_id": "g1", "commence_time": started, "markets": {"h2h": "pregame"}}]}),
            encoding="utf-8",
        )
        self._write_lines({"games": [{"event_id": "g1", "commence_time": started, "markets": {"h2h": "live"}}]})

        self.refresh._freeze_oddsapi_pregame_markets(source_root=self.source_root, date_str="2026-08-07")

        row = json.loads(frozen.read_text(encoding="utf-8"))["games"][0]
        self.assertEqual(row["markets"]["h2h"], "pregame")

    def test_snapshot_copy_accompanies_the_market_copy(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(hours=3)
        self._write_lines(_game_lines_doc(future))

        self.refresh._freeze_oddsapi_pregame_markets(source_root=self.source_root, date_str="2026-08-07")

        snapshot = (
            self.source_root / "data" / "daily" / "snapshots" / "2026-08-07"
            / "oddsapi_game_lines_2026_08_07_pregame.json"
        )
        self.assertTrue(snapshot.exists(), "the snapshot tree is what the mirror publishes")


class PregameFreezeReadTests(unittest.TestCase):
    """`_odds_paths` must prefer the freeze, and still fall back without one."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_builder()
        if not hasattr(cls.module, "_odds_paths"):
            raise unittest.SkipTest("vendored module did not expose _odds_paths")

    def test_pregame_freeze_wins_over_the_live_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            odds_dir = data_root / "market" / "oddsapi"
            odds_dir.mkdir(parents=True)
            (odds_dir / "oddsapi_game_lines_2026_08_07.json").write_text("{}", encoding="utf-8")
            frozen = odds_dir / "oddsapi_game_lines_2026_08_07_pregame.json"
            frozen.write_text("{}", encoding="utf-8")

            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(data_root)}, clear=False):
                paths = self.module._odds_paths("2026-08-07")

            self.assertEqual(paths["game_lines"].resolve(), frozen.resolve())

    def test_falls_back_to_the_live_file_when_no_freeze_exists(self) -> None:
        """Every date before the freeze was repaired has only the live file."""
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            odds_dir = data_root / "market" / "oddsapi"
            odds_dir.mkdir(parents=True)
            live = odds_dir / "oddsapi_game_lines_2026_08_07.json"
            live.write_text("{}", encoding="utf-8")

            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(data_root)}, clear=False):
                paths = self.module._odds_paths("2026-08-07")

            self.assertEqual(paths["game_lines"].resolve(), live.resolve())

    def test_all_three_families_prefer_their_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            odds_dir = data_root / "market" / "oddsapi"
            odds_dir.mkdir(parents=True)
            for name in ("oddsapi_game_lines", "oddsapi_hitter_props", "oddsapi_pitcher_props"):
                (odds_dir / f"{name}_2026_08_07.json").write_text("{}", encoding="utf-8")
                (odds_dir / f"{name}_2026_08_07_pregame.json").write_text("{}", encoding="utf-8")

            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(data_root)}, clear=False):
                paths = self.module._odds_paths("2026-08-07")

            for key in ("game_lines", "hitter_lines", "pitcher_lines"):
                self.assertTrue(str(paths[key]).endswith("_pregame.json"), f"{key} must prefer the freeze")

    def test_missing_date_still_names_the_live_path_for_the_warning(self) -> None:
        """The caller's `Missing game lines:` warning must stay meaningful."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(Path(tmp) / "data")}, clear=False):
                paths = self.module._odds_paths("2030-01-01")
            self.assertFalse(paths["game_lines"].exists())
            self.assertIn("oddsapi_game_lines_2030_01_01.json", str(paths["game_lines"]))


class FreezeReachesTheGradingReaderTests(unittest.TestCase):
    """The freeze was written where nothing read it.

    `_freeze_oddsapi_pregame_markets` wrote to `source_root/data/market/oddsapi`,
    while `build_season_betting_cards_manifest._odds_data_roots` resolves odds
    against `MLB_BETTING_DATA_ROOT` -- on all three services
    `.../mlb_source/source_artifacts/data`. One path segment apart, so the
    grading builder never saw a fresh seal: measured in production 2026-08-16,
    `ml` graded EXACTLY 1 row on all 8 dates checked, with 4-14
    `Missing game-line match` warnings each.
    """

    def setUp(self) -> None:
        self.refresh = _load_refresh()
        self._tmp = tempfile.TemporaryDirectory()
        self.source_root = Path(self._tmp.name) / "mlb_source"
        self.market_dir = self.source_root / "data" / "market" / "oddsapi"
        self.market_dir.mkdir(parents=True)
        self.reader_dir = self.source_root / "source_artifacts" / "data" / "market" / "oddsapi"
        self.addCleanup(self._tmp.cleanup)

    def _write_lines(self, doc: dict) -> None:
        (self.market_dir / "oddsapi_game_lines_2026_08_07.json").write_text(
            json.dumps(doc), encoding="utf-8"
        )

    def test_freeze_lands_in_the_source_artifacts_tree(self) -> None:
        """The fix. Before it, this directory was never written at all."""
        self._write_lines(_game_lines_doc(datetime.now(timezone.utc) + timedelta(hours=3)))

        self.refresh._freeze_oddsapi_pregame_markets(
            source_root=self.source_root, date_str="2026-08-07"
        )

        frozen = self.reader_dir / "oddsapi_game_lines_2026_08_07_pregame.json"
        self.assertTrue(frozen.exists(), "the tree the grading builder reads must get the freeze")
        self.assertEqual(len(json.loads(frozen.read_text(encoding="utf-8"))["games"]), 3)

    def test_env_data_root_directs_the_freeze(self) -> None:
        """Derived from the SAME env var the reader uses, so the two cannot
        drift apart again. A hardcoded second layout would not survive the
        next time someone repoints `MLB_BETTING_DATA_ROOT`."""
        elsewhere = Path(self._tmp.name) / "mounted" / "data"
        self._write_lines(_game_lines_doc(datetime.now(timezone.utc) + timedelta(hours=3)))

        with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(elsewhere)}, clear=False):
            self.refresh._freeze_oddsapi_pregame_markets(
                source_root=self.source_root, date_str="2026-08-07"
            )

        frozen = elsewhere / "market" / "oddsapi" / "oddsapi_game_lines_2026_08_07_pregame.json"
        self.assertTrue(frozen.exists(), "the env-pointed reader root must get the freeze")

    def test_seal_survives_a_wiped_tree(self) -> None:
        """THE ACCUMULATION BUG, and it discriminates.

        Seeding only from this tree's own copy means an ephemeral filesystem
        loses the slate: a deploy recreates it empty, the merge re-seeds from
        the LIVE doc, and the live doc by then holds only the games still
        pregame. Measured 2026-08-16: a 14-game freeze became 8 games in 20
        minutes. Here the primary copy is deleted and the surviving copy in
        the reader's tree must carry the started games back.
        """
        started = datetime.now(timezone.utc) - timedelta(hours=3)
        # A full slate was sealed earlier, while every game was still pregame.
        self.reader_dir.mkdir(parents=True, exist_ok=True)
        (self.reader_dir / "oddsapi_game_lines_2026_08_07_pregame.json").write_text(
            json.dumps(_game_lines_doc(started, games=14)), encoding="utf-8"
        )
        # The primary tree is gone (deploy), and the live file has collapsed.
        self._write_lines(_game_lines_doc(started, games=1))

        self.refresh._freeze_oddsapi_pregame_markets(
            source_root=self.source_root, date_str="2026-08-07"
        )

        for directory in (self.market_dir, self.reader_dir):
            frozen = directory / "oddsapi_game_lines_2026_08_07_pregame.json"
            doc = json.loads(frozen.read_text(encoding="utf-8"))
            self.assertEqual(
                len(doc["games"]),
                14,
                f"{directory} lost the sealed slate to the collapsed live file",
            )

if __name__ == "__main__":
    unittest.main()
