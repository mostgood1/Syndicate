from __future__ import annotations

import csv
import importlib.util
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import refresh_state_store


class _FakeKeyValueClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str) -> bool:
        self.store[key] = str(value)
        return True

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0


class WnbaRefreshRunnerTests(unittest.TestCase):
    def tearDown(self) -> None:
        refresh_state_store.reset_state_store_caches()

    def _load_module(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_wnba_oddsapi_props.py"
        spec = importlib.util.spec_from_file_location("test_refresh_wnba_oddsapi_props", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_main_calls_syndicate_cli_refresh_path(self) -> None:
        module = self._load_module()

        calls = []

        def _fake_refresh(**kwargs):
            calls.append(kwargs)
            return {
                "snapshot_rows": 12,
                "snapshot_alias_rows": 12,
                "edges_rows": 5,
                "recs_rows": 3,
                "error": None,
            }

        with tempfile.TemporaryDirectory() as tmp_dir:
            argv = [
                "refresh_wnba_oddsapi_props.py",
                "--date",
                "2026-05-22",
                "--regions",
                "us",
                "--source-root",
                tmp_dir,
                "--log-file",
                str(Path(tmp_dir) / "refresh.log"),
                "--do-edges",
                "--do-export",
            ]
            with patch.object(module, "_run_refresh_via_cli", side_effect=_fake_refresh), patch("sys.argv", argv):
                rc = module.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["date_str"], "2026-05-22")
        self.assertTrue(calls[0]["do_edges"])
        self.assertTrue(calls[0]["do_export"])

    def test_ensure_source_game_inputs_fetches_with_periods_enabled(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            raw_root = source_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"
            (processed_root / f"game_odds_{date_str}.csv").write_text(
                "game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker\n"
                "1,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus\n",
                encoding="utf-8",
            )

            calls: list[list[str]] = []

            def fake_cli(*, source_root, package_name, command_parts, log_file, heartbeat_cb, timeout_s):
                calls.append(list(command_parts))
                if command_parts and command_parts[0] == "export-game-cards":
                    out_path = source_root / "data" / "processed" / f"game_cards_{date_str}.csv"
                    out_path.write_text(
                        "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                        "2026-05-22,1,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                        encoding="utf-8",
                    )
                return 0

            module._run_source_subprocess_cli_command = fake_cli
            module._seed_game_odds_from_props_snapshot = lambda **kwargs: None
            module._seed_game_odds_from_raw_history = lambda **kwargs: None

            module._ensure_source_game_inputs(
                source_root=source_root,
                package_name="wnba_betting",
                date_str=date_str,
                log_file=Path(tmp_dir) / "refresh.log",
                heartbeat_cb=None,
            )

        self.assertIn(["fetch", "--years", "10"], calls)

    def test_build_local_game_recommendations_artifact_uses_game_cards_and_smart_sim(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            date_str = "2026-05-22"
            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,1,Home Team,Away Team,2026-05-22T19:00:00Z,-130,110,-4.5,4.5,219.5,oddsapi_consensus,HTM,ATM\n",
                encoding="utf-8",
            )
            (processed_root / f"smart_sim_{date_str}_HTM_ATM.json").write_text(
                json.dumps(
                    {
                        "date": date_str,
                        "home": "HTM",
                        "away": "ATM",
                        "quarters": [
                            {"home_pts_mu": 28.0, "away_pts_mu": 24.0},
                            {"home_pts_mu": 27.0, "away_pts_mu": 25.0},
                            {"home_pts_mu": 26.0, "away_pts_mu": 24.0},
                            {"home_pts_mu": 25.0, "away_pts_mu": 23.0},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            rows, out_path = module._build_local_game_recommendations_artifact(processed_root=processed_root, date_str=date_str)

            self.assertEqual(rows, 2)
            self.assertIsNotNone(out_path)
            assert out_path is not None
            with out_path.open("r", encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual([row.get("market") for row in written], ["ATS", "TOTAL"])
        self.assertEqual(written[0].get("side"), "Home Team")
        self.assertEqual(written[1].get("side"), "Under")

    def test_build_local_game_cards_artifact_uses_raw_team_odds_snapshot(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            raw_root = source_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"
            (raw_root / f"odds_wnba_current_{date_str}.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,h2h,Chicago Sky,,,-140,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,h2h,Minnesota Lynx,,,120,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,spreads,Chicago Sky,,-4.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,spreads,Minnesota Lynx,,4.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,totals,Over,,164.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,totals,Under,,164.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n",
                encoding="utf-8",
            )

            rows, out_path = module._build_local_game_cards_artifact(
                source_root=source_root,
                processed_root=processed_root,
                date_str=date_str,
                log_file=Path(tmp_dir) / "refresh.log",
            )

            self.assertEqual(rows, 1)
            self.assertIsNotNone(out_path)
            assert out_path is not None
            with out_path.open("r", encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].get("home_team"), "Chicago Sky")
        self.assertEqual(written[0].get("visitor_team"), "Minnesota Lynx")
        self.assertEqual(written[0].get("home_tri"), "CHI")
        self.assertEqual(written[0].get("away_tri"), "MIN")
        self.assertEqual(written[0].get("bookmaker"), "oddsapi_consensus")

    def test_build_local_game_cards_artifact_uses_raw_player_props_snapshot_fallback(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            raw_root = source_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-06-17"
            (raw_root / f"odds_wnba_player_props_{date_str}.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-06-17T13:55:26Z,401,2026-06-17T23:00:00Z,draftkings,DraftKings,player_points,Over,Sonia Citron,16.5,-113,2026-06-17T13:55:01Z,Connecticut Sun,Washington Mystics\n"
                "2026-06-17T13:55:26Z,401,2026-06-17T23:00:00Z,draftkings,DraftKings,player_points,Under,Sonia Citron,16.5,-117,2026-06-17T13:55:01Z,Connecticut Sun,Washington Mystics\n",
                encoding="utf-8",
            )

            rows, out_path = module._build_local_game_cards_artifact(
                source_root=source_root,
                processed_root=processed_root,
                date_str=date_str,
                log_file=Path(tmp_dir) / "refresh.log",
            )

            self.assertEqual(rows, 1)
            self.assertIsNotNone(out_path)
            assert out_path is not None
            with out_path.open("r", encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].get("home_team"), "Connecticut Sun")
        self.assertEqual(written[0].get("visitor_team"), "Washington Mystics")
        self.assertEqual(written[0].get("home_tri"), "CON")
        self.assertEqual(written[0].get("away_tri"), "WSH")
        self.assertEqual(written[0].get("bookmaker"), "oddsapi_consensus")

    def test_build_local_game_cards_artifact_derives_odds_from_props_snapshot_market_rows(self) -> None:
        # Regression: game_odds_{date}.csv is normally only ever seeded with a
        # bare matchup skeleton (no prices), so the props-snapshot fallback path
        # must aggregate h2h/spreads/totals rows directly out of the raw combined
        # snapshot rather than relying solely on the (price-less) game_odds lookup.
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            raw_root = source_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-07-13"
            (raw_root / f"odds_wnba_player_props_{date_str}.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,h2h,Atlanta Dream,,,-770,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,h2h,Los Angeles Sparks,,,450,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,spreads,Atlanta Dream,,-10.5,-110,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,spreads,Los Angeles Sparks,,10.5,-110,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,totals,Over,,197.5,-110,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,totals,Under,,197.5,-110,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,player_points,Over,Allisha Gray,16.5,-115,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n",
                encoding="utf-8",
            )

            rows, out_path = module._build_local_game_cards_artifact(
                source_root=source_root,
                processed_root=processed_root,
                date_str=date_str,
                log_file=Path(tmp_dir) / "refresh.log",
            )

            self.assertEqual(rows, 1)
            self.assertIsNotNone(out_path)
            assert out_path is not None
            with out_path.open("r", encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual(len(written), 1)
        row = written[0]
        self.assertEqual(row.get("home_tri"), "ATL")
        self.assertEqual(row.get("away_tri"), "LAS")
        self.assertAlmostEqual(float(row.get("home_ml")), -770.0)
        self.assertAlmostEqual(float(row.get("away_ml")), 450.0)
        self.assertAlmostEqual(float(row.get("home_spread")), -10.5)
        self.assertAlmostEqual(float(row.get("away_spread")), 10.5)
        self.assertAlmostEqual(float(row.get("total")), 197.5)

    def test_build_local_game_cards_artifact_derives_odds_in_game_odds_fallback_when_skeleton_only(self) -> None:
        # Regression: when the predictions-vs-snapshot matchup check fails (e.g. a
        # team-name formatting mismatch) the builder falls back to reading
        # game_odds_{date}.csv directly. In production that file is usually only
        # ever seeded with a bare matchup skeleton (no prices) by
        # _seed_game_odds_from_props_snapshot, so this path must also aggregate
        # h2h/spreads/totals straight out of the props snapshot per matchup.
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            raw_root = source_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-07-13"

            (raw_root / f"odds_wnba_player_props_{date_str}.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,h2h,Atlanta Dream,,,-770,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,h2h,Los Angeles Sparks,,,450,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,spreads,Atlanta Dream,,-10.5,-110,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,spreads,Los Angeles Sparks,,10.5,-110,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,totals,Over,,197.5,-110,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,totals,Under,,197.5,-110,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n",
                encoding="utf-8",
            )

            # predictions uses a team-name variant that doesn't match the props
            # snapshot's names, so expected_matchups never becomes a subset of
            # snapshot_matchups and the builder must fall through to game_odds.
            (processed_root / f"predictions_{date_str}.csv").write_text(
                "date,home_team,visitor_team,home_win_prob,spread_margin,totals,commence_time\n"
                "2026-07-13,ATL,LAS,0.6,,,2026-07-13T23:08:15Z\n",
                encoding="utf-8",
            )

            # game_odds is only ever seeded with a bare matchup skeleton -- no prices.
            (processed_root / f"game_odds_{date_str}.csv").write_text(
                "date,home_team,visitor_team,commence_time\n"
                "2026-07-13,Atlanta Dream,Los Angeles Sparks,2026-07-13T23:08:15Z\n",
                encoding="utf-8",
            )

            rows, out_path = module._build_local_game_cards_artifact(
                source_root=source_root,
                processed_root=processed_root,
                date_str=date_str,
                log_file=Path(tmp_dir) / "refresh.log",
            )

            self.assertEqual(rows, 1)
            self.assertIsNotNone(out_path)
            assert out_path is not None
            with out_path.open("r", encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual(len(written), 1)
        row = written[0]
        self.assertAlmostEqual(float(row.get("home_ml")), -770.0)
        self.assertAlmostEqual(float(row.get("away_ml")), 450.0)
        self.assertAlmostEqual(float(row.get("home_spread")), -10.5)
        self.assertAlmostEqual(float(row.get("away_spread")), 10.5)
        self.assertAlmostEqual(float(row.get("total")), 197.5)

    def test_build_local_game_cards_artifact_writes_and_reads_through_keyvalue_backend(self) -> None:
        # Regression: game_cards.csv must be written to BOTH the keyvalue
        # store (this same script's own re-read, for top-by-game building,
        # goes through the keyvalue store) AND plain local disk -- every
        # external reader (syndicate/features/wnba/sources.py, cards.py,
        # archive.py) and artifact_publisher.py's HOT_ARTIFACT_PATTERNS HTTP
        # push use plain pathlib access and were never made keyvalue-aware,
        # so a keyvalue-only write left the file invisible to the live site
        # despite the refresh pipeline succeeding (confirmed live on Render).
        module = self._load_module()
        fake_client = _FakeKeyValueClient()

        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {"SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue", "SYNDICATE_REFRESH_STATE_URL": "redis://example"},
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            raw_root = source_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-07-13"
            (raw_root / f"odds_wnba_player_props_{date_str}.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,h2h,Atlanta Dream,,,-770,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n"
                "2026-07-13T20:00:00Z,401,2026-07-13T23:08:15Z,draftkings,DraftKings,h2h,Los Angeles Sparks,,,450,2026-07-13T20:00:00Z,Atlanta Dream,Los Angeles Sparks\n",
                encoding="utf-8",
            )

            rows, out_path = module._build_local_game_cards_artifact(
                source_root=source_root,
                processed_root=processed_root,
                date_str=date_str,
                log_file=Path(tmp_dir) / "refresh.log",
            )

            self.assertEqual(rows, 1)
            self.assertIsNotNone(out_path)
            assert out_path is not None
            # Went to both the keyvalue store and plain local disk.
            self.assertTrue(out_path.exists())
            self.assertTrue(fake_client.store)

            # This script's own re-read (used to build top_by_game) must see
            # the same data back out of the keyvalue store.
            _, by_team, _ = module._local_game_cards_index(processed_root=processed_root, date_str=date_str)
            self.assertIn("ATL", by_team)
            self.assertIn("LAS", by_team)

    def test_build_local_game_cards_artifact_promotes_full_slate_when_snapshot_is_partial(self) -> None:
        module = self._load_module()

        games = [
            ("Washington Mystics", "Golden State Valkyries", "WSH", "GSV", "2026-07-06T23:40:00Z", 401, 24.5, 22.5, -4.5, 4.5, 166.5),
            ("Minnesota Lynx", "Connecticut Sun", "MIN", "CON", "2026-07-07T00:00:00Z", 402, 25.0, 21.0, -6.5, 6.5, 162.5),
            ("Los Angeles Sparks", "Seattle Storm", "LAS", "SEA", "2026-07-07T02:10:00Z", 403, 26.0, 24.0, -2.5, 2.5, 169.5),
        ]

        def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            raw_root = source_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-07-06"

            write_csv(
                raw_root / f"odds_wnba_player_props_{date_str}.csv",
                ["snapshot_ts", "event_id", "commence_time", "bookmaker", "bookmaker_title", "market", "outcome_name", "player_name", "point", "price", "last_update", "home_team", "away_team"],
                [
                    {
                        "snapshot_ts": "2026-07-06T20:00:00Z",
                        "event_id": "401",
                        "commence_time": "2026-07-07T02:07:44Z",
                        "bookmaker": "draftkings",
                        "bookmaker_title": "DraftKings",
                        "market": "player_points",
                        "outcome_name": "Over",
                        "player_name": "Ariel Atkins",
                        "point": 12.5,
                        "price": -115,
                        "last_update": "2026-07-06T20:00:00Z",
                        "home_team": "Los Angeles Sparks",
                        "away_team": "Seattle Storm",
                    }
                ],
            )

            write_csv(
                processed_root / f"predictions_{date_str}.csv",
                ["date", "home_team", "visitor_team", "home_win_prob", "spread_margin", "totals", "commence_time"],
                [
                    {"date": date_str, "home_team": home, "visitor_team": away, "home_win_prob": 0.5, "spread_margin": "", "totals": "", "commence_time": commence}
                    for home, away, _, _, commence, _, _, _, _, _, _ in games
                ],
            )

            write_csv(
                processed_root / f"game_odds_{date_str}.csv",
                ["game_id", "home_team", "visitor_team", "commence_time", "home_ml", "away_ml", "home_spread", "away_spread", "total", "bookmaker"],
                [
                    {
                        "game_id": game_id,
                        "home_team": home,
                        "visitor_team": away,
                        "commence_time": commence,
                        "home_ml": -110,
                        "away_ml": -110,
                        "home_spread": home_spread,
                        "away_spread": away_spread,
                        "total": total,
                        "bookmaker": "oddsapi_consensus",
                    }
                    for home, away, _, _, commence, game_id, _, _, home_spread, away_spread, total in games
                ],
            )

            for home, away, home_tri, away_tri, _, _, _, _, _, _, _ in games:
                smart_path = processed_root / f"smart_sim_{date_str}_{home_tri}_{away_tri}.json"
                smart_path.write_text(
                    json.dumps(
                        {
                            "date": date_str,
                            "home": home_tri,
                            "away": away_tri,
                            "quarters": [
                                {"home_pts_mu": 24.0, "away_pts_mu": 20.0},
                                {"home_pts_mu": 23.0, "away_pts_mu": 21.0},
                                {"home_pts_mu": 22.0, "away_pts_mu": 20.0},
                                {"home_pts_mu": 21.0, "away_pts_mu": 19.0},
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

            rows, out_path = module._build_local_game_cards_artifact(
                source_root=source_root,
                processed_root=processed_root,
                date_str=date_str,
                log_file=Path(tmp_dir) / "refresh.log",
            )

            self.assertEqual(rows, 3)
            self.assertIsNotNone(out_path)
            assert out_path is not None
            with out_path.open("r", encoding="utf-8", newline="") as handle:
                written_cards = list(csv.DictReader(handle))

            write_csv(
                processed_root / f"props_recommendations_{date_str}.csv",
                ["player", "team", "model", "top_play", "top_play_reasons", "top_play_explain"],
                [
                    {
                        "player": f"Player {home_tri}",
                        "team": home_tri,
                        "model": json.dumps({"pts": 10.0}),
                        "top_play": json.dumps(
                            {
                                "market": "pts",
                                "stat": "pts",
                                "side": "OVER",
                                "line": 8.5,
                                "price": -110,
                                "edge": 0.12,
                                "ev": 0.12,
                                "ev_pct": 12.0,
                                "p_win": 0.56,
                                "proj": 10.0,
                                "book": "draftkings",
                            }
                        ),
                        "top_play_reasons": json.dumps(["EV 12.0%", "Best line available"]),
                        "top_play_explain": "model 10.0 vs line 8.5 (+1.5)",
                    }
                    for _, _, home_tri, _, _, _, _, _, _, _, _ in games
                ],
            )

            prop_rows, prop_path = module._build_local_cards_props_snapshot_artifact(processed_root=processed_root, date_str=date_str)
            self.assertEqual(prop_rows, 3)

            self.assertIsNotNone(prop_path)
            assert prop_path is not None
            prop_payload = json.loads(prop_path.read_text(encoding="utf-8"))
            self.assertEqual(len(prop_payload.get("games") or []), 3)

            recommendation_rows, recommendation_path = module._build_local_game_recommendations_artifact(processed_root=processed_root, date_str=date_str)
            self.assertEqual(recommendation_rows, 6)
            self.assertIsNotNone(recommendation_path)

            slate_rows, slate_path = module._build_local_recommendations_slate_artifact(processed_root=processed_root, date_str=date_str)
            self.assertEqual(slate_rows, 3)
            self.assertIsNotNone(slate_path)
            assert slate_path is not None
            slate_payload = json.loads(slate_path.read_text(encoding="utf-8"))
            self.assertEqual(slate_payload.get("counts", {}).get("games"), 3)
            self.assertEqual(len(slate_payload.get("per_game") or []), 3)

            self.assertEqual(len(written_cards), 3)
            self.assertEqual(
                sorted((row.get("home_tri"), row.get("away_tri")) for row in written_cards),
                [("LAS", "SEA"), ("MIN", "CON"), ("WSH", "GSV")],
            )

    def test_build_local_game_cards_artifact_keeps_slate_games_on_next_utc_day(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            raw_root = source_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-07-07"

            (raw_root / f"odds_wnba_player_props_{date_str}.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-07-07T07:35:03Z,a5c10cf00d97057ef1bd2f450afb222d,2026-07-08T00:00:00Z,draftkings,DraftKings,player_points,Over,Paige Bueckers,21.5,-106,2026-07-07T07:34:08Z,New York Liberty,Dallas Wings\n"
                "2026-07-07T07:35:03Z,a5c10cf00d97057ef1bd2f450afb222d,2026-07-08T00:00:00Z,draftkings,DraftKings,player_points,Under,Sabrina Ionescu,14.5,-108,2026-07-07T07:34:08Z,New York Liberty,Dallas Wings\n"
                "2026-07-07T07:35:03Z,7cc2478497e9ecb0694604a911b80966ea11323e152b7aaedf3b94acc3a54d95,2026-07-08T02:00:00Z,draftkings,DraftKings,player_points,Over,Alyssa Thomas,17.5,-110,2026-07-07T07:34:08Z,Phoenix Mercury,Chicago Sky\n"
                "2026-07-07T07:35:03Z,7cc2478497e9ecb0694604a911b80966ea11323e152b7aaedf3b94acc3a54d95,2026-07-08T02:00:00Z,draftkings,DraftKings,player_points,Under,Courtney Vandersloot,12.5,-110,2026-07-07T07:34:08Z,Phoenix Mercury,Chicago Sky\n",
                encoding="utf-8",
            )

            (processed_root / f"predictions_{date_str}.csv").write_text(
                "date,home_team,visitor_team,home_win_prob,spread_margin,totals,commence_time\n"
                "2026-07-07,New York Liberty,Dallas Wings,0.5,,,2026-07-08T00:00:00Z\n"
                "2026-07-07,Phoenix Mercury,Chicago Sky,0.5,,,2026-07-08T02:00:00Z\n",
                encoding="utf-8",
            )

            rows, out_path = module._build_local_game_cards_artifact(
                source_root=source_root,
                processed_root=processed_root,
                date_str=date_str,
                log_file=Path(tmp_dir) / "refresh.log",
            )

            self.assertEqual(rows, 2)
            self.assertIsNotNone(out_path)
            assert out_path is not None
            with out_path.open("r", encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual(len(written), 2)
        self.assertEqual(
            {(row.get("home_team"), row.get("visitor_team")) for row in written},
            {("New York Liberty", "Dallas Wings"), ("Phoenix Mercury", "Chicago Sky")},
        )
        self.assertEqual({row.get("home_tri") for row in written}, {"NYL", "PHX"})
        self.assertEqual({row.get("away_tri") for row in written}, {"DAL", "CHI"})

    def test_repair_predictions_slate_rebuilds_when_predictions_missing(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            date_str = "2026-06-05"
            (processed_root / f"game_odds_{date_str}.csv").write_text(
                "date,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker\n"
                "2026-06-05,Chicago Sky,Minnesota Lynx,2026-06-05T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus\n",
                encoding="utf-8",
            )
            (processed_root / f"oddsapi_player_props_{date_str}.csv").write_text(
                "home_team,away_team,commence_time\n"
                "Chicago Sky,Minnesota Lynx,2026-06-05T23:00:00Z\n",
                encoding="utf-8",
            )

            repaired = module._repair_predictions_slate_from_game_odds_if_needed(
                processed_root=processed_root,
                date_str=date_str,
                log_file=processed_root / "refresh.log",
            )

            self.assertTrue(repaired)
            pred_path = processed_root / f"predictions_{date_str}.csv"
            self.assertTrue(pred_path.exists())
            with pred_path.open("r", encoding="utf-8", newline="") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].get("date"), date_str)
        self.assertEqual(written[0].get("home_team"), "Chicago Sky")
        self.assertEqual(written[0].get("visitor_team"), "Minnesota Lynx")

    def test_main_returns_error_when_refresh_runner_returns_none(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            argv = [
                "refresh_wnba_oddsapi_props.py",
                "--date",
                "2026-05-22",
                "--regions",
                "us",
                "--source-root",
                tmp_dir,
                "--log-file",
                str(Path(tmp_dir) / "refresh.log"),
            ]
            with patch.object(module, "_run_refresh_via_cli", return_value=None), patch("sys.argv", argv):
                rc = module.main()

        self.assertEqual(rc, 1)

    def test_local_basketball_json_exports_use_owned_inputs(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"
            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            with (processed_root / f"recommendations_{date_str}.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "market",
                        "side",
                        "home",
                        "away",
                        "date",
                        "ev",
                        "price",
                        "implied_prob",
                        "edge",
                        "line",
                        "pred_margin",
                        "market_home_margin",
                        "pred_total",
                        "tier",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "market": "ATS",
                        "side": "Chicago Sky",
                        "home": "Chicago Sky",
                        "away": "Minnesota Lynx",
                        "date": date_str,
                        "ev": 0.07,
                        "price": -110,
                        "implied_prob": 0.5238,
                        "edge": 1.7,
                        "line": 4.5,
                        "pred_margin": 6.0,
                        "market_home_margin": -4.5,
                        "pred_total": "",
                        "tier": "Medium",
                    }
                )
            prop_columns = [
                "player",
                "team",
                "plays",
                "ladders",
                "sim_ladders",
                "model",
                "_plays_list",
                "top_play",
                "top_play_explain",
                "top_play_baseline",
                "top_play_reasons",
                "top_play_consensus",
                "top_play_line_adv",
                "last5_average",
                "last10_average",
                "last_game_value",
                "projected_minutes",
                "last10_workload",
            ]
            with (processed_root / f"props_recommendations_{date_str}.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=prop_columns)
                writer.writeheader()
                writer.writerow(
                    {
                        "player": "Angel Reese",
                        "team": "CHI",
                        "plays": str([{"market": "reb", "side": "OVER", "line": 10.5, "price": -110, "edge": 1.4, "ev": 0.08, "ev_pct": 8.0, "book": "fanduel"}]),
                        "ladders": "[]",
                        "sim_ladders": "[]",
                        "model": str({"reb": 11.3, "pts": 15.1}),
                        "_plays_list": str([{"market": "reb", "side": "OVER", "line": 10.5, "price": -110, "edge": 1.4, "ev": 0.08, "ev_pct": 8.0, "book": "fanduel"}]),
                        "top_play": str({"market": "reb", "side": "OVER", "line": 10.5, "price": -110, "edge": 1.4, "ev": 0.08, "ev_pct": 8.0, "book": "fanduel"}),
                        "top_play_explain": "model 11.3 vs line 10.5 (+0.8)",
                        "top_play_baseline": "11.3",
                        "top_play_reasons": str(["EV 8.0%", "Regular price range (-150 to +150)"]),
                        "top_play_consensus": "0.5",
                        "top_play_line_adv": "1.0",
                        "last5_average": "12.4",
                        "last10_average": "11.7",
                        "last_game_value": "13.0",
                        "projected_minutes": "34.5",
                        "last10_workload": "32.0",
                    }
                )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                slate_path = module._export_recommendations_slate_snapshot(source_root=source_root, date_str=date_str, processed_root=processed_root)
                props_path = module._export_cards_props_snapshot(source_root=source_root, date_str=date_str, processed_root=processed_root)
                top_path = module._export_top_by_game_snapshot(source_root=source_root, date_str=date_str, processed_root=processed_root)

            self.assertIsNotNone(slate_path)
            self.assertIsNotNone(props_path)
            self.assertIsNotNone(top_path)
            slate_payload = json.loads((processed_root / f"recommendations_slate_{date_str}.json").read_text(encoding="utf-8"))
            props_payload = json.loads((processed_root / f"cards_props_snapshot_{date_str}.json").read_text(encoding="utf-8"))
            top_payload = json.loads((processed_root / f"props_recommendations_top_by_game_{date_str}.json").read_text(encoding="utf-8"))

        self.assertEqual(slate_payload["counts"]["games"], 1)
        self.assertEqual(slate_payload["per_game"][0]["home"], "CHI")
        self.assertTrue(any(float(pick.get("last5_average") or 0.0) == 12.4 for pick in (slate_payload["per_game"][0]["picks"] or []) if isinstance(pick, dict)))
        self.assertEqual(props_payload["games"][0]["prop_recommendations"]["home"][0]["player"], "Angel Reese")
        self.assertEqual(props_payload["games"][0]["prop_recommendations"]["home"][0]["last10_workload"], 32.0)
        self.assertEqual(top_payload["data"][0]["team_tricode"], "CHI")
        self.assertEqual(top_payload["data"][0]["top_play"]["market"], "reb")
        self.assertEqual(top_payload["data"][0]["top_play"]["projected_minutes"], 34.5)

    def test_cards_props_snapshot_writes_empty_structure_when_props_missing(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir) / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"
            game_row = {"home_tri": "CHI", "away_tri": "MIN", "game_id": "12345"}
            by_team = {
                "CHI": {"home_tri": "CHI", "away_tri": "MIN", "side": "home", "opponent": "MIN"},
                "MIN": {"home_tri": "CHI", "away_tri": "MIN", "side": "away", "opponent": "CHI"},
            }

            with patch.object(module, "_local_game_cards_index", return_value=([game_row], by_team, None)), patch.object(module, "_load_local_props_recommendations", return_value=[]):
                rows, out_path = module._build_local_cards_props_snapshot_artifact(processed_root=processed_root, date_str=date_str)

            self.assertEqual(rows, 0)
            self.assertEqual(out_path, processed_root / f"cards_props_snapshot_{date_str}.json")
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["date"], date_str)
        self.assertEqual(payload["games"], [])

    def test_recon_games_export_uses_local_boxscores_and_game_cards(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-29"
            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-29,9876543210,Chicago Sky,Minnesota Lynx,2026-05-29T19:00:00Z,120,-140,3.5,-3.5,162.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"boxscores_{date_str}.csv").write_text(
                "GAME_ID,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,PTS\n"
                "9876543210,CHI,1,Angel Reese,19\n"
                "9876543210,CHI,2,Kamilla Cardoso,14\n"
                "9876543210,MIN,3,Napheesa Collier,26\n"
                "9876543210,MIN,4,Kayla McBride,17\n",
                encoding="utf-8",
            )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                out = module._export_recon_games_artifact(source_root=source_root, date_str=date_str, processed_root=processed_root)

            self.assertEqual(out, str(processed_root / f"recon_games_{date_str}.csv"))
            with (processed_root / f"recon_games_{date_str}.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home_team"], "Chicago Sky")
        self.assertEqual(rows[0]["visitor_team"], "Minnesota Lynx")
        self.assertEqual(rows[0]["home_pts"], "33")
        self.assertEqual(rows[0]["visitor_pts"], "43")
        self.assertEqual(rows[0]["total_actual"], "76")

    def test_run_refresh_via_cli_uses_local_snapshot_fetcher(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            (source_root / "data" / "raw").mkdir(parents=True, exist_ok=True)
            commands = []

            def _fake_run(args, log_file, **kwargs):
                commands.append((list(args), kwargs.get("cwd")))
                out_idx = args.index("--out") + 1
                out_path = Path(args[out_idx])
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n", encoding="utf-8")
                return 0

            with patch.object(module, "_run_to_file", side_effect=_fake_run):
                state = module._run_refresh_via_cli(
                    source_root=source_root,
                    date_str="2026-05-22",
                    regions="us",
                    bookmakers="fanduel,draftkings",
                    markets="player_points,player_rebounds",
                    do_edges=False,
                    do_export=False,
                    do_push=False,
                    log_file=tmp_root / "refresh.log",
                )

        self.assertEqual(len(commands), 1)
        self.assertEqual(Path(commands[0][0][1]).name, "fetch_basketball_oddsapi_props_local.py")
        self.assertIn("--league", commands[0][0])
        self.assertIn("wnba", commands[0][0])
        self.assertEqual(commands[0][1], module.REPO_ROOT)
        self.assertEqual(int(state["rc_snapshot"]), 0)
        self.assertEqual(int(state["snapshot_rows"]), 1)

    def test_player_logs_preflight_accepts_local_boxscores(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            processed_root = source_root / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            (processed_root / "boxscores_2026-05-22.csv").write_text(
                "date,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,MIN,PTS,REB,AST,FG3M\n"
                "2026-05-21,NYL,1,Test Player,30,20,5,6,3\n",
                encoding="utf-8",
            )

            ready, reason = module._ensure_player_logs_for_props_refresh(
                source_root=source_root,
                date_str="2026-05-22",
                log_file=Path(tmp_dir) / "refresh.log",
                heartbeat_cb=lambda *_args, **_kwargs: None,
            )

        self.assertTrue(ready)
        self.assertIsNone(reason)

    def test_player_logs_preflight_bootstraps_local_history_when_missing(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            (source_root / "data" / "processed").mkdir(parents=True, exist_ok=True)

            with patch.object(module, "_bootstrap_local_boxscores_history_for_props", return_value=(True, None)):
                ready, reason = module._ensure_player_logs_for_props_refresh(
                    source_root=source_root,
                    date_str="2026-05-22",
                    log_file=Path(tmp_dir) / "refresh.log",
                    heartbeat_cb=lambda *_args, **_kwargs: None,
                )

        self.assertTrue(ready)
        self.assertIsNone(reason)

    def test_run_refresh_via_cli_uses_inprocess_predict_props(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            predict_calls = []
            run_calls = []

            def _fake_run(args, log_file, **kwargs):
                run_calls.append(list(args))
                if "--out" in args:
                    out_idx = args.index("--out") + 1
                    out_path = Path(args[out_idx])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text("snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n", encoding="utf-8")
                elif "props-edges" in args:
                    edges_path = processed_root / "props_edges_2026-05-22.csv"
                    edges_path.parent.mkdir(parents=True, exist_ok=True)
                    edges_path.write_text("market\nPTS\n", encoding="utf-8")
                return 0

            def _fake_predict_export(**kwargs):
                predict_calls.append(dict(kwargs))
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_game_predictions_for_props_refresh", return_value=(True, None)):
                state = module._run_refresh_via_cli(
                    source_root=source_root,
                    date_str="2026-05-22",
                    regions="us",
                    bookmakers="",
                    markets="",
                    do_edges=True,
                    do_export=False,
                    do_push=False,
                    log_file=tmp_root / "refresh.log",
                )

        self.assertEqual(len(run_calls), 1)
        self.assertEqual(Path(run_calls[0][1]).name, "fetch_basketball_oddsapi_props_local.py")
        self.assertEqual(len(predict_calls), 1)
        self.assertEqual(predict_calls[0]["date_str"], "2026-05-22")
        self.assertTrue(predict_calls[0]["use_smart_sim"])
        self.assertEqual(int(state["predictions_rows"]), 1)

    def test_run_refresh_via_cli_uses_inprocess_props_edges(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            predict_calls = []
            edges_calls = []

            def _fake_run(args, log_file, **kwargs):
                if "--out" in args:
                    out_idx = args.index("--out") + 1
                    out_path = Path(args[out_idx])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text("snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n", encoding="utf-8")
                return 0

            def _fake_predict_export(**kwargs):
                predict_calls.append(dict(kwargs))
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            def _fake_edges_export(**kwargs):
                edges_calls.append(dict(kwargs))
                out_path = kwargs["out_path"]
                out_path.write_text("market\nPTS\n", encoding="utf-8")
                return 1, out_path

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "export_props_edges_local", side_effect=_fake_edges_export), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_game_predictions_for_props_refresh", return_value=(True, None)):
                state = module._run_refresh_via_cli(
                    source_root=source_root,
                    date_str="2026-05-22",
                    regions="us",
                    bookmakers="",
                    markets="",
                    do_edges=True,
                    do_export=True,
                    do_push=False,
                    log_file=tmp_root / "refresh.log",
                )

        self.assertEqual(len(predict_calls), 1)
        self.assertEqual(len(edges_calls), 1)
        self.assertEqual(edges_calls[0]["bookmakers"], "")
        self.assertEqual(int(state["rc_edges"]), 0)
        self.assertEqual(int(state["edges_rows"]), 1)

    def test_run_refresh_via_cli_treats_zero_row_edges_as_warning(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            predict_calls = []

            def _fake_run(args, log_file, **kwargs):
                if "--out" in args:
                    out_idx = args.index("--out") + 1
                    out_path = Path(args[out_idx])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text("snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n", encoding="utf-8")
                return 0

            def _fake_predict_export(**kwargs):
                predict_calls.append(dict(kwargs))
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            def _fake_recommendations_export(*, processed_root, date_str, max_plus_odds=125.0):
                out_path = processed_root / f"props_recommendations_{date_str}.csv"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            def _fake_edges_export(**kwargs):
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("", encoding="utf-8")
                raise RuntimeError("simulated zero-row edges failure")

            def _fake_game_cards_artifact(*, source_root, processed_root, date_str, log_file):
                game_cards_path = source_root / "data" / "processed" / f"game_cards_{date_str}.csv"
                game_cards_path.write_text("game_id\n1\n", encoding="utf-8")
                return 1, game_cards_path

            def _fake_game_recommendations_artifact(*, processed_root, date_str):
                recs_path = processed_root / f"props_recommendations_{date_str}.csv"
                recs_path.write_text("market\nA\n", encoding="utf-8")
                return 1, recs_path

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "export_props_edges_local", side_effect=_fake_edges_export), patch.object(module, "export_props_recommendations_local", return_value=(1, processed_root / "props_recommendations_2026-05-22.csv")), patch.object(module, "_build_local_game_cards_artifact", side_effect=_fake_game_cards_artifact), patch.object(module, "_build_local_game_recommendations_artifact", side_effect=_fake_game_recommendations_artifact), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_game_predictions_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_source_game_inputs", return_value={"schedule": 1, "fetch": 0, "build_features": 0, "predict_date": 0}):
                state = module._run_refresh_via_cli(
                    source_root=source_root,
                    date_str="2026-05-22",
                    regions="us",
                    bookmakers="",
                    markets="",
                    do_edges=True,
                    do_export=True,
                    do_push=False,
                    log_file=tmp_root / "refresh.log",
                )

        self.assertEqual(int(state["rc_edges"]), 0)
        self.assertEqual(int(state["rc_export"]), 0)
        self.assertEqual(int(state["edges_rows"]), 0)
        self.assertIn("WNBA props-edges produced no rows", str(state.get("warning")))
        self.assertEqual(len(predict_calls), 1)
        self.assertTrue(predict_calls[0]["use_smart_sim"])

    def test_run_refresh_via_cli_allows_missing_edges_when_recs_and_game_cards_exist(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)

            def _fake_run(args, log_file, **kwargs):
                if "--out" in args:
                    out_idx = args.index("--out") + 1
                    out_path = Path(args[out_idx])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text("snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n", encoding="utf-8")
                return 0

            def _fake_predict_export(**kwargs):
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            def _fake_edges_export(**kwargs):
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("", encoding="utf-8")
                raise RuntimeError("simulated zero-row edges failure")

            def _fake_game_cards_artifact(*, source_root, processed_root, date_str, log_file):
                game_cards_path = source_root / "data" / "processed" / f"game_cards_{date_str}.csv"
                game_cards_path.write_text("game_id\n1\n", encoding="utf-8")
                return 1, game_cards_path

            def _fake_recommendations_export(*, processed_root, date_str, max_plus_odds=125.0):
                out_path = processed_root / f"props_recommendations_{date_str}.csv"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "export_props_edges_local", side_effect=_fake_edges_export), patch.object(module, "export_props_recommendations_local", side_effect=_fake_recommendations_export), patch.object(module, "_build_local_game_cards_artifact", side_effect=_fake_game_cards_artifact), patch.object(module, "_build_local_game_recommendations_artifact", return_value=(0, None)), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_game_predictions_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_source_game_inputs", return_value={"schedule": 1, "fetch": 0, "build_features": 0, "predict_date": 0}):
                state = module._run_refresh_via_cli(
                    source_root=source_root,
                    date_str="2026-05-22",
                    regions="us",
                    bookmakers="",
                    markets="",
                    do_edges=True,
                    do_export=True,
                    do_push=False,
                    log_file=tmp_root / "refresh.log",
                )

        self.assertEqual(int(state["rc_edges"]), 0)
        self.assertEqual(int(state["rc_export"]), 0)
        self.assertEqual(int(state["edges_rows"]), 0)
        self.assertGreater(int(state["recs_rows"]), 0)
        self.assertIn("WNBA recommendation artifacts were unavailable", str(state.get("warning")))

    def test_run_refresh_via_cli_uses_inprocess_export_props_recommendations(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            (raw_root / "odds_wnba_current_2026-05-22.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,h2h,Chicago Sky,,,-140,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,h2h,Minnesota Lynx,,,120,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,spreads,Chicago Sky,,-4.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,spreads,Minnesota Lynx,,4.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,totals,Over,,164.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-05-22T12:00:00Z,401,2026-05-22T23:00:00Z,fanduel,FanDuel,totals,Under,,164.5,-110,2026-05-22T12:00:00Z,Chicago Sky,Minnesota Lynx\n",
                encoding="utf-8",
            )
            (processed_root / "smart_sim_2026-05-22_CHI_MIN.json").write_text(
                json.dumps(
                    {
                        "date": "2026-05-22",
                        "home": "CHI",
                        "away": "MIN",
                        "quarters": [
                            {"home_pts_mu": 21.0, "away_pts_mu": 19.0},
                            {"home_pts_mu": 22.0, "away_pts_mu": 20.0},
                            {"home_pts_mu": 21.0, "away_pts_mu": 19.0},
                            {"home_pts_mu": 20.0, "away_pts_mu": 18.0}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            predict_calls = []
            edges_calls = []
            export_calls = []

            def _fake_run(args, log_file, **kwargs):
                if "--out" in args:
                    out_idx = args.index("--out") + 1
                    out_path = Path(args[out_idx])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text("snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n", encoding="utf-8")
                elif "props-edges" in args:
                    (processed_root / "props_edges_2026-05-22.csv").write_text("market\nPTS\n", encoding="utf-8")
                return 0

            def _fake_predict_export(**kwargs):
                predict_calls.append(dict(kwargs))
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            def _fake_edges_export(**kwargs):
                edges_calls.append(dict(kwargs))
                out_path = kwargs["out_path"]
                out_path.write_text("market\nPTS\n", encoding="utf-8")
                return 1, out_path

            def _fake_export(*, processed_root, date_str, max_plus_odds=125.0):
                export_calls.append({"processed_root": processed_root, "date_str": date_str, "max_plus_odds": max_plus_odds})
                out_path = processed_root / f"props_recommendations_{date_str}.csv"
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "export_props_edges_local", side_effect=_fake_edges_export), patch.object(module, "export_props_recommendations_local", side_effect=_fake_export), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_game_predictions_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_source_game_inputs", return_value={"schedule": 1, "fetch": 0, "build_features": 0, "predict_date": 0}):
                state = module._run_refresh_via_cli(
                    source_root=source_root,
                    date_str="2026-05-22",
                    regions="us",
                    bookmakers="",
                    markets="",
                    do_edges=True,
                    do_export=True,
                    do_push=False,
                    log_file=tmp_root / "refresh.log",
                )

        self.assertEqual(len(predict_calls), 1)
        self.assertEqual(len(edges_calls), 1)
        self.assertEqual(len(export_calls), 1)
        self.assertTrue(predict_calls[0]["use_smart_sim"])
        self.assertEqual(int(state["rc_export"]), 0)
        self.assertEqual(int(state["recs_rows"]), 1)

    def test_core_outputs_are_enough_for_reuse_without_recommendation_artifacts(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            source_raw = source_root / "data" / "raw"
            source_processed = source_root / "data" / "processed"
            bundle_raw = artifact_root / "data" / "raw"
            bundle_processed = artifact_root / "data" / "processed"
            for path in (source_raw, source_processed, bundle_raw, bundle_processed):
                path.mkdir(parents=True, exist_ok=True)

            date_str = "2026-05-22"
            snapshot_name = f"odds_wnba_player_props_{date_str}.csv"
            game_predictions_name = f"predictions_{date_str}.csv"
            predictions_name = f"props_predictions_{date_str}.csv"
            core_csv = "snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n"
            (source_raw / snapshot_name).write_text(core_csv, encoding="utf-8")
            (source_processed / game_predictions_name).write_text("home_team,visitor_team\nCHI,MIN\n", encoding="utf-8")
            (source_processed / predictions_name).write_text("player\nA\n", encoding="utf-8")
            (bundle_raw / snapshot_name).write_text(core_csv, encoding="utf-8")
            (bundle_processed / game_predictions_name).write_text("home_team,visitor_team\nCHI,MIN\n", encoding="utf-8")
            (bundle_processed / predictions_name).write_text("player\nA\n", encoding="utf-8")

            refresh_state = module._existing_refresh_state(
                source_root=source_root,
                date_str=date_str,
                do_edges=False,
                do_export=True,
            )
            artifact_state = module._existing_artifact_bundle_state(
                artifact_root=artifact_root,
                date_str=date_str,
                do_edges=False,
                do_export=True,
            )

        self.assertIsNotNone(refresh_state)
        self.assertIsNotNone(artifact_state)
        assert refresh_state is not None
        assert artifact_state is not None
        self.assertTrue(refresh_state.get("reused_existing_outputs"))
        self.assertTrue(artifact_state.get("reused_existing_artifact_bundle"))
        self.assertEqual(refresh_state.get("snapshot_bundle_path"), str(source_raw / snapshot_name))
        self.assertEqual(artifact_state.get("snapshot_bundle_path"), str(bundle_raw / snapshot_name))
        self.assertEqual(int(refresh_state["recs_rows"]), 0)
        self.assertEqual(int(artifact_state["recs_rows"]), 0)

    def test_existing_refresh_state_requires_game_predictions_for_reuse(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)

            date_str = "2026-05-22"
            snapshot_name = f"odds_wnba_player_props_{date_str}.csv"
            predictions_name = f"props_predictions_{date_str}.csv"
            core_csv = "snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n"
            (raw_root / snapshot_name).write_text(core_csv, encoding="utf-8")
            (processed_root / predictions_name).write_text("player\nA\n", encoding="utf-8")

            refresh_state = module._existing_refresh_state(
                source_root=source_root,
                date_str=date_str,
                do_edges=False,
                do_export=True,
            )

        self.assertIsNone(refresh_state)

    def test_run_refresh_via_cli_allows_missing_recommendation_artifacts_when_core_outputs_exist(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)

            def _fake_run(args, log_file, **kwargs):
                if "--out" in args:
                    out_idx = args.index("--out") + 1
                    out_path = Path(args[out_idx])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text("snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n", encoding="utf-8")
                return 0

            def _fake_predict_export(**kwargs):
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            def _fake_game_cards_artifact(*, source_root, processed_root, date_str, log_file):
                game_cards_path = processed_root / f"game_cards_{date_str}.csv"
                game_cards_path.write_text(
                    "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                    "2026-05-22,401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                    encoding="utf-8",
                )
                return 1, game_cards_path

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "export_props_recommendations_local", return_value=(0, None)), patch.object(module, "_build_local_game_cards_artifact", side_effect=_fake_game_cards_artifact), patch.object(module, "_build_local_game_recommendations_artifact", return_value=(0, None)), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_game_predictions_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_source_game_inputs", return_value={"schedule": 1, "fetch": 0, "build_features": 0, "predict_date": 0}):
                state = module._run_refresh_via_cli(
                    source_root=source_root,
                    date_str="2026-05-22",
                    regions="us",
                    bookmakers="",
                    markets="",
                    do_edges=False,
                    do_export=True,
                    do_push=False,
                    log_file=tmp_root / "refresh.log",
                )

        self.assertIsNone(state["error"])
        self.assertEqual(int(state["rc_export"]), 0)
        self.assertEqual(int(state["recs_rows"]), 0)
        self.assertGreater(int(state["game_cards_rows"]), 0)
        self.assertEqual(state.get("snapshot_bundle_path"), state.get("snapshot_path"))
        self.assertEqual(state.get("snapshot_bundle_rows"), state.get("snapshot_rows"))
        self.assertEqual(state.get("prediction_bundle_path"), state.get("predictions_path"))
        self.assertEqual(state.get("prediction_bundle_rows"), state.get("predictions_rows"))

    def test_run_refresh_via_cli_treats_written_export_artifacts_as_success(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)

            def _fake_run(args, log_file, **kwargs):
                if "--out" in args:
                    out_idx = args.index("--out") + 1
                    out_path = Path(args[out_idx])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text("snapshot_ts,event_id\n2026-05-22T12:00:00Z,evt-1\n", encoding="utf-8")
                elif "props-edges" in args:
                    (processed_root / "props_edges_2026-05-22.csv").write_text("market\nPTS\n", encoding="utf-8")
                return 0

            def _fake_predict_export(**kwargs):
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("player\nA\n", encoding="utf-8")
                return 1, out_path

            def _fake_edges_export(**kwargs):
                out_path = kwargs["out_path"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text("market\nPTS\n", encoding="utf-8")
                return 1, out_path

            def _fake_game_cards_artifact(*, source_root, processed_root, date_str, log_file):
                game_cards_path = processed_root / f"game_cards_{date_str}.csv"
                recs_path = processed_root / f"props_recommendations_{date_str}.csv"
                game_cards_path.write_text(
                    "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                    "2026-05-22,401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                    encoding="utf-8",
                )
                recs_path.write_text("market\nATS\n", encoding="utf-8")
                raise RuntimeError("simulated export helper failure after writing artifacts")

            with patch.object(module, "_run_to_file", side_effect=_fake_run), patch.object(module, "export_props_predictions_local", side_effect=_fake_predict_export), patch.object(module, "export_props_edges_local", side_effect=_fake_edges_export), patch.object(module, "_ensure_player_logs_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_game_predictions_for_props_refresh", return_value=(True, None)), patch.object(module, "_ensure_source_game_inputs", return_value={"schedule": 1, "fetch": 0, "build_features": 0, "predict_date": 0}), patch.object(module, "_build_local_game_cards_artifact", side_effect=_fake_game_cards_artifact):
                state = module._run_refresh_via_cli(
                    source_root=source_root,
                    date_str="2026-05-22",
                    regions="us",
                    bookmakers="",
                    markets="",
                    do_edges=True,
                    do_export=True,
                    do_push=False,
                    log_file=tmp_root / "refresh.log",
                )

        self.assertEqual(int(state["rc_export"]), 0)
        self.assertIsNone(state["error"])
        self.assertGreater(int(state["game_cards_rows"]), 0)
        self.assertGreater(int(state["recs_rows"]), 0)

    def test_cli_backed_exports_prefer_existing_processed_files(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_source.mkdir(parents=True)
            processed_root = tmp_root / "bundle" / "data" / "processed"
            date_str = "2026-05-22"

            expected = {
                f"recon_quarters_{date_str}.csv": module._export_recon_quarters_artifact,
                f"recon_props_{date_str}.csv": module._export_recon_props_artifact,
                f"game_cards_{date_str}.csv": module._export_game_cards_artifact,
                f"boxscores_{date_str}.csv": module._export_boxscores_artifact,
                f"recommendations_{date_str}.csv": module._export_recommendations_artifact,
            }
            for name in expected:
                (processed_source / name).write_text("id\n1\n", encoding="utf-8")

            with patch.object(module, "_load_source_cli", side_effect=AssertionError("source CLI should not load")):
                for name, exporter in expected.items():
                    out = exporter(source_root=source_root, date_str=date_str, processed_root=processed_root)
                    self.assertEqual(out, str(processed_root / name))
                    self.assertTrue((processed_root / name).exists())

    def test_app_backed_exports_prefer_existing_processed_files(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_source.mkdir(parents=True)
            processed_root = tmp_root / "bundle" / "data" / "processed"
            live_lens_root = tmp_root / "bundle" / "data" / "live_lens"
            date_str = "2026-05-22"

            expected = {
                f"recon_games_{date_str}.csv": module._export_recon_games_artifact,
                f"recommendations_slate_{date_str}.json": module._export_recommendations_slate_snapshot,
                f"cards_props_snapshot_{date_str}.json": module._export_cards_props_snapshot,
                f"cards_sim_detail_{date_str}.json": module._export_cards_sim_detail_snapshot,
                f"props_recommendations_top_by_game_{date_str}.json": module._export_top_by_game_snapshot,
            }
            for name in expected:
                (processed_source / name).write_text('{"ok": true}\n', encoding="utf-8")
            (processed_source / f"live_lens_signals_{date_str}.jsonl").write_text('{"kind":"signal"}\n', encoding="utf-8")
            (processed_source / f"live_lens_projections_{date_str}.jsonl").write_text('{"kind":"projection"}\n', encoding="utf-8")
            (processed_source / "live_lens_tuning_override.json").write_text('{"alpha":1.25}\n', encoding="utf-8")

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                for name, exporter in expected.items():
                    out = exporter(source_root=source_root, date_str=date_str, processed_root=processed_root)
                    self.assertEqual(out, str(processed_root / name))
                    self.assertTrue((processed_root / name).exists())
                copied = module._export_live_lens_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                    live_lens_root=live_lens_root,
                )
                self.assertEqual(copied["live_lens_signals_path"], str(processed_root / f"live_lens_signals_{date_str}.jsonl"))
                self.assertEqual(copied["live_lens_projections_path"], str(processed_root / f"live_lens_projections_{date_str}.jsonl"))
                self.assertEqual(copied["live_lens_tuning_override_path"], str(processed_root / "live_lens_tuning_override.json"))
                self.assertEqual(copied["live_lens_tuning_override_live_lens_path"], str(live_lens_root / "live_lens_tuning_override.json"))

    def test_live_lens_tuning_export_uses_local_builder(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            live_lens_root = tmp_root / "bundle" / "data" / "live_lens"
            date_str = "2026-05-22"
            processed_source.mkdir(parents=True, exist_ok=True)
            (processed_source / f"live_lens_signals_{date_str}.jsonl").write_text('{"kind":"signal"}\n', encoding="utf-8")
            (processed_source / f"live_lens_projections_{date_str}.jsonl").write_text('{"kind":"projection"}\n', encoding="utf-8")

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                copied = module._export_live_lens_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                    live_lens_root=live_lens_root,
                )

            self.assertEqual(copied["live_lens_tuning_override_path"], str(processed_root / "live_lens_tuning_override.json"))
            self.assertEqual(copied["live_lens_tuning_override_live_lens_path"], str(live_lens_root / "live_lens_tuning_override.json"))
            payload = json.loads((processed_root / "live_lens_tuning_override.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["markets"]["player_prop"]["bet"], 4.0)

    def test_live_lens_signals_export_uses_local_smart_sim_builder(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            live_lens_root = tmp_root / "bundle" / "data" / "live_lens"
            date_str = "2026-05-22"
            processed_source.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            live_lens_root.mkdir(parents=True, exist_ok=True)

            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"smart_sim_{date_str}_CHI_MIN.json").write_text(
                json.dumps(
                    {
                        "date": date_str,
                        "home": "CHI",
                        "away": "MIN",
                        "periods": {
                            "q1": {"home_mean": 22.0, "away_mean": 20.0},
                            "q2": {"home_mean": 21.0, "away_mean": 21.0},
                            "q3": {"home_mean": 23.0, "away_mean": 20.0},
                            "q4": {"home_mean": 22.0, "away_mean": 21.0},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (processed_source / f"live_lens_projections_{date_str}.jsonl").write_text(
                json.dumps({"market": "player_prop", "player": "Angel Reese"}) + "\n",
                encoding="utf-8",
            )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                copied = module._export_live_lens_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                    live_lens_root=live_lens_root,
                )

            self.assertEqual(copied["live_lens_signals_path"], str(processed_root / f"live_lens_signals_{date_str}.jsonl"))
            rows = [
                json.loads(line)
                for line in (processed_root / f"live_lens_signals_{date_str}.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market"], "total")
        self.assertEqual(rows[0]["klass"], "WATCH")
        self.assertEqual(rows[0]["side"], "OVER")
        self.assertEqual(rows[0]["live_line"], 164.5)
        self.assertEqual(rows[0]["pred"], 170.0)
        self.assertEqual(rows[0]["remaining"], 40)

    def test_live_lens_signals_export_prefers_existing_source_artifact(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            live_lens_root = tmp_root / "bundle" / "data" / "live_lens"
            date_str = "2026-05-22"
            processed_source.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            live_lens_root.mkdir(parents=True, exist_ok=True)

            source_rows = [
                {
                    "market": "quarter_total",
                    "klass": "BET",
                    "game_id": "0401",
                    "home": "CHI",
                    "away": "MIN",
                    "side": "OVER",
                    "live_line": 40.5,
                    "pred": 45.0,
                    "edge": 4.5,
                    "edge_adj": 4.5,
                    "horizon": "q1",
                }
            ]
            (processed_source / f"live_lens_signals_{date_str}.jsonl").write_text(
                "\n".join(json.dumps(row) for row in source_rows) + "\n",
                encoding="utf-8",
            )
            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"smart_sim_{date_str}_CHI_MIN.json").write_text(
                json.dumps(
                    {
                        "date": date_str,
                        "home": "CHI",
                        "away": "MIN",
                        "periods": {
                            "q1": {"home_mean": 22.0, "away_mean": 20.0},
                            "q2": {"home_mean": 21.0, "away_mean": 21.0},
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                copied = module._export_live_lens_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                    live_lens_root=live_lens_root,
                )

            self.assertEqual(copied["live_lens_signals_path"], str(processed_root / f"live_lens_signals_{date_str}.jsonl"))
            rows = [
                json.loads(line)
                for line in (processed_root / f"live_lens_signals_{date_str}.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(rows, source_rows)

    def test_flat_props_rows_still_build_top_by_game_snapshot(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            date_str = "2026-06-17"
            processed_source.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)

            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-06-17,0401,Chicago Sky,Minnesota Lynx,2026-06-17T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"props_recommendations_{date_str}.csv").write_text(
                "date,team,player,market,side,line,price,ev,ev_pct,book,top_play_explain,top_play_reasons\n"
                "2026-06-17,CHI,Angel Reese,reb,OVER,10.5,-110,0.08,8.0,fanduel,model 11.3 vs line 10.5 (+0.8),['EV 8.0%','Regular price range (-150 to +150)']\n",
                encoding="utf-8",
            )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                props_path = module._export_cards_props_snapshot(source_root=source_root, date_str=date_str, processed_root=processed_root)
                top_path = module._export_top_by_game_snapshot(source_root=source_root, date_str=date_str, processed_root=processed_root)

            self.assertIsNotNone(props_path)
            self.assertIsNotNone(top_path)
            props_payload = json.loads((processed_root / f"cards_props_snapshot_{date_str}.json").read_text(encoding="utf-8"))
            top_payload = json.loads((processed_root / f"props_recommendations_top_by_game_{date_str}.json").read_text(encoding="utf-8"))

        self.assertEqual(props_payload["games"][0]["prop_recommendations"]["home"][0]["player"], "Angel Reese")
        self.assertEqual(top_payload["data"][0]["team_tricode"], "CHI")
        self.assertEqual(top_payload["data"][0]["top_play"]["market"], "reb")
        self.assertEqual(top_payload["data"][0]["top_play"]["side"], "OVER")

    def test_generate_offline_live_lens_signals_emits_period_totals(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "vendor" / "wnba_betting_repo" / "tools" / "generate_offline_live_lens_signals.py"
        spec = importlib.util.spec_from_file_location("test_generate_offline_live_lens_signals", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            date_str = "2026-05-22"
            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,halves_h1_total,quarters_q1_total,quarters_q2_total,quarters_q3_total,quarters_q4_total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,82.0,40.5,41.5,39.5,42.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"_predictions_backup_{date_str}.csv").write_text(
                "home_team,visitor_team,totals,pred_h1_total,pred_q1_total,pred_q2_total,pred_q3_total,pred_q4_total\n"
                "Chicago Sky,Minnesota Lynx,170.0,86.0,45.0,39.5,41.0,43.0\n",
                encoding="utf-8",
            )

            out_path = processed_root / f"live_lens_signals_{date_str}.jsonl"
            argv = ["generate_offline_live_lens_signals.py", "--date", date_str, "--out", str(out_path), "--min-left", "40"]
            with patch.object(module, "PROCESSED", processed_root), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            rows = [
                json.loads(line)
                for line in out_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(len(rows), 6)
        markets = {(row["market"], row.get("horizon")) for row in rows}
        self.assertIn(("total", "game"), markets)
        self.assertIn(("half_total", "h1"), markets)
        self.assertIn(("quarter_total", "q1"), markets)
        self.assertIn(("quarter_total", "q2"), markets)
        self.assertIn(("quarter_total", "q3"), markets)
        self.assertIn(("quarter_total", "q4"), markets)

    def test_live_lens_projections_export_uses_local_predictions_builder(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            live_lens_root = tmp_root / "bundle" / "data" / "live_lens"
            processed_source.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            live_lens_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"

            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"props_predictions_{date_str}.csv").write_text(
                "player_name,team,opponent,home,pred_pts,mean_pts,pred_reb,mean_reb\n"
                "Angel Reese,CHI,MIN,1,15.8,15.1,10.9,10.4\n",
                encoding="utf-8",
            )
            (processed_root / f"props_edges_{date_str}.csv").write_text(
                "player_name,team,stat,line\n"
                "Angel Reese,CHI,reb,10.5\n",
                encoding="utf-8",
            )
            (processed_source / f"live_lens_signals_{date_str}.jsonl").write_text(
                json.dumps({"market": "total", "game_id": "0401"}) + "\n",
                encoding="utf-8",
            )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                copied = module._export_live_lens_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                    live_lens_root=live_lens_root,
                )

            self.assertEqual(copied["live_lens_projections_path"], str(processed_root / f"live_lens_projections_{date_str}.jsonl"))
            rows = [
                json.loads(line)
                for line in (processed_root / f"live_lens_projections_{date_str}.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(len(rows), 2)
        reb_row = next(row for row in rows if row["stat"] == "reb")
        self.assertEqual(reb_row["market"], "player_prop")
        self.assertEqual(reb_row["game_id"], "0401")
        self.assertEqual(reb_row["home"], "CHI")
        self.assertEqual(reb_row["away"], "MIN")
        self.assertEqual(reb_row["proj"], 10.9)
        self.assertEqual(reb_row["sim_mu"], 10.4)
        self.assertEqual(reb_row["line"], 10.5)

    def test_recon_props_export_uses_local_boxscores_builder(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"

            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"boxscores_{date_str}.csv").write_text(
                "date,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,PTS,REB,AST,FG3M,STL,BLK,TOV\n"
                "2026-05-22,CHI,5,Angel Reese,24,11,4,0,1,2,3\n",
                encoding="utf-8",
            )

            out = module._export_recon_props_artifact(
                source_root=source_root,
                date_str=date_str,
                processed_root=processed_root,
            )

            self.assertEqual(out, str(processed_root / f"recon_props_{date_str}.csv"))
            with (processed_root / f"recon_props_{date_str}.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["game_id"], "0401")
        self.assertEqual(rows[0]["player_name"], "Angel Reese")
        self.assertEqual(rows[0]["team_abbr"], "CHI")
        self.assertEqual(rows[0]["blk"], "2")
        self.assertEqual(rows[0]["pr"], "35")
        self.assertEqual(rows[0]["pa"], "28")
        self.assertEqual(rows[0]["ra"], "15")
        self.assertEqual(rows[0]["pra"], "39")

    def test_cards_sim_detail_export_preserves_quarter_summary(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True)
            (processed_root / "smart_sim_2026-05-29_POR_ATL.json").write_text(
                json.dumps(
                    {
                        "home": "POR",
                        "away": "ATL",
                        # Real raw smart_sim payloads have a top-level "quarters"
                        # list keyed by "q", not a "periods" dict keyed by "q1" --
                        # see test_cards_sim_detail_export_uses_source_cards_api_fallback
                        # below for the same (correct) shape used elsewhere.
                        "quarters": [{"q": 1, "away_pts_mu": 21.4, "home_pts_mu": 19.8}],
                        "players_summary": {"home": 1, "away": 1},
                        "players": {"home": [{"player_name": "Home Player"}], "away": [{"player_name": "Away Player"}]},
                        "missing_prop_players": {"home": [], "away": []},
                        "injuries": {"home": [], "away": []},
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(module, "_copy_existing_processed_artifact", return_value=None), patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                out = module._export_cards_sim_detail_snapshot(source_root=source_root, date_str="2026-05-29", processed_root=processed_root)

            self.assertEqual(out, str(processed_root / "cards_sim_detail_2026-05-29.json"))
            payload = json.loads((processed_root / "cards_sim_detail_2026-05-29.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["games"][0]["sim"]["quarters"][0]["away_pts_mu"], 21.4)

    def test_cards_sim_detail_export_uses_source_cards_api_fallback(self) -> None:
        module = self._load_module()

        class _FakeResponse:
            def get_json(self):
                return {
                    "games": [
                        {
                            "home_tri": "LVA",
                            "away_tri": "CHI",
                            "sim": {
                                "players_summary": {"home": 1, "away": 1},
                                "players": {"home": [{"player_name": "Home Player"}], "away": [{"player_name": "Away Player"}]},
                                "missing_prop_players": {"home": [], "away": []},
                                "injuries": {"home": [], "away": []},
                                "quarters": [{"q": 1, "away_pts_mu": 19.5, "home_pts_mu": 22.5}],
                            },
                        }
                    ]
                }

        class _FakeClient:
            def get(self, query):
                self.query = query
                return _FakeResponse()

        class _FakeApp:
            def test_client(self):
                return _FakeClient()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = source_root / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)

            with patch.object(module, "_copy_existing_processed_artifact", return_value=None), patch.object(module, "_load_source_app", return_value=types.SimpleNamespace(app=_FakeApp())):
                out = module._export_cards_sim_detail_snapshot(source_root=source_root, date_str="2026-05-22", processed_root=processed_root)

            self.assertEqual(out, str(processed_root / "cards_sim_detail_2026-05-22.json"))
            payload = json.loads((processed_root / "cards_sim_detail_2026-05-22.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["date"], "2026-05-22")
            self.assertEqual(payload["games"][0]["home_tri"], "LVA")
            self.assertEqual(payload["games"][0]["away_tri"], "CHI")

    def test_cards_sim_detail_export_rebuilds_sparse_existing_artifact(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            source_processed = source_root / "data" / "processed"
            source_processed.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            (source_processed / "cards_sim_detail_2026-05-29.json").write_text(
                json.dumps(
                    {
                        "date": "2026-05-29",
                        "games": [
                            {
                                "home_tri": "POR",
                                "away_tri": "ATL",
                                "sim": {
                                    "quarters": [],
                                    "players_summary": {"home": 1, "away": 1},
                                    "players": {"home": [{"player_name": "Home Player"}], "away": [{"player_name": "Away Player"}]},
                                    "missing_prop_players": {"home": [], "away": []},
                                    "injuries": {"home": [], "away": []},
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (processed_root / "smart_sim_2026-05-29_POR_ATL.json").write_text(
                json.dumps(
                    {
                        "home": "POR",
                        "away": "ATL",
                        "quarters": [{"q": 1, "away_pts_mu": 21.4, "home_pts_mu": 19.8}],
                        "players_summary": {"home": 1, "away": 1},
                        "players": {"home": [{"player_name": "Home Player"}], "away": [{"player_name": "Away Player"}]},
                        "missing_prop_players": {"home": [], "away": []},
                        "injuries": {"home": [], "away": []},
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")):
                out = module._export_cards_sim_detail_snapshot(source_root=source_root, date_str="2026-05-29", processed_root=processed_root)

            self.assertEqual(out, str(processed_root / "cards_sim_detail_2026-05-29.json"))
            payload = json.loads((processed_root / "cards_sim_detail_2026-05-29.json").read_text(encoding="utf-8"))
            self.assertGreater(len(payload["games"][0]["sim"]["quarters"]), 0)
            self.assertEqual(payload["games"][0]["sim"]["quarters"][0]["away_pts_mu"], 21.4)

    def test_optional_tool_exports_prefer_existing_processed_files(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_source = source_root / "data" / "processed"
            processed_source.mkdir(parents=True)
            processed_root = tmp_root / "bundle" / "data" / "processed"
            date_str = "2026-05-22"

            (processed_source / f"recon_players_{date_str}.csv").write_text("player\nA\n", encoding="utf-8")
            (processed_source / f"live_player_lens_tuning_{date_str}.csv").write_text("player\nA\n", encoding="utf-8")

            with patch.object(module, "_load_module_from_path", side_effect=AssertionError("tool module should not load")):
                copied = module._build_optional_player_recon_artifacts(
                    source_root=source_root,
                    date_str=date_str,
                    processed_root=processed_root,
                )
                self.assertEqual(copied["recon_players_path"], str(processed_root / f"recon_players_{date_str}.csv"))
                self.assertEqual(copied["live_player_lens_tuning_path"], str(processed_root / f"live_player_lens_tuning_{date_str}.csv"))

    def test_optional_tool_exports_use_local_vendored_builders(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            date_str = "2026-05-22"

            (processed_root / f"game_cards_{date_str}.csv").write_text(
                "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-05-22,0401,Chicago Sky,Minnesota Lynx,2026-05-22T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus,CHI,MIN\n",
                encoding="utf-8",
            )
            (processed_root / f"smart_sim_{date_str}_CHI_MIN.json").write_text(
                json.dumps(
                    {
                        "game_id": "0401",
                        "home": "CHI",
                        "away": "MIN",
                        "players": {
                            "home": [
                                {
                                    "player_id": 5,
                                    "player_name": "Angel Reese",
                                    "min_mean": 34.0,
                                    "pts_mean": 18.0,
                                    "reb_mean": 11.0,
                                    "ast_mean": 4.0,
                                    "threes_mean": 0.0,
                                    "pra_mean": 33.0,
                                    "stl_mean": 1.0,
                                    "blk_mean": 2.0,
                                    "tov_mean": 3.0,
                                }
                            ],
                            "away": [],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (processed_root / f"boxscores_{date_str}.csv").write_text(
                "GAME_ID,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,MIN,PTS,REB,AST,FG3M,FG3A,FGM,FGA,FTM,FTA,STL,BLK,TOV,PF,OREB,DREB,PLUS_MINUS\n"
                "0401,CHI,5,Angel Reese,35:00,20,12,3,0,0,9,16,2,4,1,2,3,3,5,7,9\n",
                encoding="utf-8",
            )
            (processed_root / f"props_predictions_{date_str}.csv").write_text(
                "player_id,player_name,team,opponent,roll10_min,mean_pts,mean_reb,mean_ast,mean_threes,mean_pra\n"
                "5,Angel Reese,CHI,MIN,34.0,18.0,11.0,4.0,0.0,33.0\n",
                encoding="utf-8",
            )
            (processed_root / f"props_edges_{date_str}.csv").write_text(
                "team,player_name,stat,line\n"
                "CHI,Angel Reese,reb,10.5\n"
                "CHI,Angel Reese,pra,31.5\n",
                encoding="utf-8",
            )

            copied = module._build_optional_player_recon_artifacts(
                source_root=source_root,
                date_str=date_str,
                processed_root=processed_root,
            )

            self.assertEqual(copied["recon_players_path"], str(processed_root / f"recon_players_{date_str}.csv"))
            self.assertEqual(copied["live_player_lens_tuning_path"], str(processed_root / f"live_player_lens_tuning_{date_str}.csv"))
            with (processed_root / f"recon_players_{date_str}.csv").open("r", encoding="utf-8", newline="") as handle:
                recon_rows = list(csv.DictReader(handle))
            with (processed_root / f"live_player_lens_tuning_{date_str}.csv").open("r", encoding="utf-8", newline="") as handle:
                tuning_rows = list(csv.DictReader(handle))

        self.assertEqual(len(recon_rows), 1)
        self.assertEqual(recon_rows[0]["player_name"], "Angel Reese")
        self.assertEqual(recon_rows[0]["actual_reb"], "12.0")
        reb_row = next(row for row in tuning_rows if row["stat"] == "reb")
        self.assertEqual(reb_row["player_name"], "Angel Reese")
        self.assertEqual(reb_row["game_id"], "0401")
        self.assertEqual(reb_row["actual"], "12.0")
        self.assertEqual(reb_row["line"], "10.5")

    def test_write_and_read_live_snapshot_payload_round_trips_through_keyvalue_backend(self) -> None:
        # Regression: live_state.jsonl (game status/score) is read
        # cross-service, same reasoning as game_cards.csv above -- must go
        # through the keyvalue store rather than a plain local write/read.
        module = self._load_module()
        fake_client = _FakeKeyValueClient()

        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {"SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue", "SYNDICATE_REFRESH_STATE_URL": "redis://example"},
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            path = Path(tmp_dir) / "processed" / "live_snapshots" / "live_state_2026-07-13.jsonl"
            payload = {"ok": True, "games": [{"event_id": "401857064", "status": "Live", "in_progress": True}]}

            wrote = module._write_live_snapshot_payload(path, payload)

            self.assertTrue(wrote)
            self.assertFalse(path.exists())
            self.assertTrue(fake_client.store)

            read_back = module._read_live_snapshot_payload(path)
            self.assertEqual(read_back, payload)

    def test_payload_has_snapshot_content_rejects_scheduled_only_live_state(self) -> None:
        # Regression: every WNBA game starts life as a bare "Scheduled"
        # placeholder with no real evidence (no score, no clock/period, not
        # final). Treating that as "already has content" made the reuse-
        # existing shortcut in _export_live_snapshot_artifacts permanently
        # skip recomputing live_state once any placeholder got written,
        # freezing status at "Scheduled" forever regardless of how many
        # force-refreshes ran afterward -- this is what silently broke both
        # the live-lens loop's status and the default /wnba/cards page.
        module = self._load_module()

        scheduled_only = {
            "games": [
                {"event_id": "401857064", "status": "Scheduled", "final": False, "in_progress": False, "home_pts": None, "away_pts": None},
                {"event_id": "401857065", "status": "Scheduled", "final": False, "in_progress": False, "home_pts": None, "away_pts": None},
            ]
        }
        self.assertFalse(module._payload_has_snapshot_content("live_state", scheduled_only))

        final_game = {"games": [{"event_id": "401857064", "status": "Final", "final": True, "in_progress": False}]}
        self.assertTrue(module._payload_has_snapshot_content("live_state", final_game))

        live_with_score = {"games": [{"event_id": "401857065", "status": "Live", "final": False, "in_progress": True, "home_pts": 42, "away_pts": 38}]}
        self.assertTrue(module._payload_has_snapshot_content("live_state", live_with_score))

        live_no_evidence = {"games": [{"event_id": "401857065", "status": "Live", "final": False, "in_progress": True, "home_pts": None, "away_pts": None, "period": None, "clock": ""}]}
        self.assertFalse(module._payload_has_snapshot_content("live_state", live_no_evidence))

    def test_export_live_snapshot_artifacts_overwrites_empty_lens_snapshot_with_local_build(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            source_snapshots = source_root / "data" / "processed" / "live_snapshots"
            source_snapshots.mkdir(parents=True, exist_ok=True)
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)

            module._write_live_snapshot_payload(
                source_snapshots / "live_state_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401856963", "status": "Scheduled"}]},
            )
            module._write_live_snapshot_payload(
                source_snapshots / "live_player_lens_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401856963", "rows": []}]},
            )

            def _fake_local_payload(*, kind: str, date_str: str, event_ids: list[str]):
                if kind == "live_player_lens":
                    return {"ok": True, "games": [{"event_id": "401856963", "rows": [{"player": "Aneesah Morrow"}]}]}
                return None

            with patch.object(module, "_source_app_fallback_enabled", return_value=False), patch.object(
                module,
                "_build_local_live_snapshot_payload",
                side_effect=_fake_local_payload,
            ):
                copied = module._export_live_snapshot_artifacts(
                    source_root=source_root,
                    date_str="2026-06-05",
                    processed_root=processed_root,
                )

            self.assertIn("live_player_lens_path", copied)
            payload = module._read_live_snapshot_payload(processed_root / "live_snapshots" / "live_player_lens_2026-06-05.jsonl")
            self.assertEqual((((payload or {}).get("games") or [{}])[0].get("rows") or [{}])[0].get("player"), "Aneesah Morrow")

    def test_export_live_snapshot_artifacts_skips_empty_shells_without_replacement(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            source_snapshots = source_root / "data" / "processed" / "live_snapshots"
            source_snapshots.mkdir(parents=True, exist_ok=True)
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)

            module._write_live_snapshot_payload(
                source_snapshots / "live_state_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401856963", "status": "Live"}]},
            )
            module._write_live_snapshot_payload(
                source_snapshots / "live_lines_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401856963", "found": False, "lines": {}}]},
            )
            module._write_live_snapshot_payload(
                source_snapshots / "live_player_lens_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401856963", "rows": []}]},
            )

            with patch.object(module, "_source_app_fallback_enabled", return_value=False), patch.object(
                module,
                "_build_local_live_snapshot_payload",
                return_value=None,
            ):
                copied = module._export_live_snapshot_artifacts(
                    source_root=source_root,
                    date_str="2026-06-05",
                    processed_root=processed_root,
                )

            self.assertIn("live_state_path", copied)
            self.assertNotIn("live_lines_path", copied)
            self.assertNotIn("live_player_lens_path", copied)
            self.assertFalse((processed_root / "live_snapshots" / "live_lines_2026-06-05.jsonl").exists())
            self.assertFalse((processed_root / "live_snapshots" / "live_player_lens_2026-06-05.jsonl").exists())

    def test_export_live_snapshot_artifacts_builds_from_bundle_live_lens_artifacts(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            source_snapshots = source_root / "data" / "processed" / "live_snapshots"
            source_snapshots.mkdir(parents=True, exist_ok=True)
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)

            module._write_live_snapshot_payload(
                source_snapshots / "live_state_2026-06-05.jsonl",
                {"ok": True, "games": [{"event_id": "401856963", "home": "LAS", "away": "NYL", "status": "Live"}]},
            )
            (processed_root / "game_cards_2026-06-05.csv").write_text(
                "date,game_id,event_id,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
                "2026-06-05,0401,401856963,Las Vegas Aces,New York Liberty,2026-06-05T23:00:00Z,-140,120,-4.5,4.5,163.5,oddsapi_consensus,LAS,NYL\n",
                encoding="utf-8",
            )
            (processed_root / "live_lens_signals_2026-06-05.jsonl").write_text(
                json.dumps({"market": "total", "game_id": "0401", "home": "LAS", "away": "NYL", "live_line": 163.5}) + "\n",
                encoding="utf-8",
            )
            (processed_root / "live_lens_projections_2026-06-05.jsonl").write_text(
                json.dumps({"market": "player_prop", "game_id": "0401", "home": "LAS", "away": "NYL", "player": "Breanna Stewart", "team": "NYL", "opponent": "LAS", "stat": "pts", "line": 17.5, "proj": 23.0, "sim_mu": 21.0, "klass": "BET"}) + "\n",
                encoding="utf-8",
            )

            with patch.object(module, "_source_app_fallback_enabled", return_value=False), patch(
                "syndicate.features.wnba.cards.build_live_player_boxscore_payload",
                return_value={"games": [{"event_id": "401856963", "players": []}]},
            ):
                copied = module._export_live_snapshot_artifacts(
                    source_root=source_root,
                    date_str="2026-06-05",
                    processed_root=processed_root,
                )

            self.assertIn("live_lines_path", copied)
            self.assertIn("live_player_lens_path", copied)
            lines_payload = module._read_live_snapshot_payload(processed_root / "live_snapshots" / "live_lines_2026-06-05.jsonl")
            lens_payload = module._read_live_snapshot_payload(processed_root / "live_snapshots" / "live_player_lens_2026-06-05.jsonl")

        self.assertIsNotNone(((((lines_payload or {}).get("games") or [{}])[0].get("lines") or {}).get("total")))
        self.assertEqual((((lens_payload or {}).get("games") or [{}])[0].get("rows") or [{}])[0].get("player"), "Breanna Stewart")
        self.assertEqual((((lens_payload or {}).get("games") or [{}])[0].get("rows") or [{}])[0].get("line_source"), "live_lens_projection_artifact")

    def test_export_live_snapshot_artifacts_prefers_richer_local_live_lines(self) -> None:
        module = self._load_module()

        class _FakeResponse:
            def __init__(self, payload):
                self.status_code = 200
                self._payload = payload

            def get_json(self):
                return self._payload

        class _FakeClient:
            def get(self, query):
                if query.startswith("/api/live_state"):
                    return _FakeResponse({"ok": True, "games": [{"event_id": "401856963", "status": "Live"}]})
                if query.startswith("/api/live_lines"):
                    return _FakeResponse(
                        {
                            "ok": True,
                            "games": [{"event_id": "401856963", "found": True, "lines": {"total": 163.5, "period_totals": {}, "period_spreads": {}}}],
                        }
                    )
                return _FakeResponse({"ok": True, "games": []})

        class _FakeSourceApp:
            class app:
                @staticmethod
                def test_client():
                    return _FakeClient()

        def _fake_local_payload(*, kind, date_str, event_ids):
            if kind != "live_lines":
                return None
            return {
                "ok": True,
                "games": [
                    {
                        "event_id": "401856963",
                        "found": True,
                        "lines": {
                            "total": 162.5,
                            "period_totals": {"q1": 40.5},
                            "period_spreads": {"q1": -2.5},
                        },
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)

            with patch.object(module, "_source_app_fallback_enabled", return_value=True), patch.object(
                module,
                "_load_source_app",
                return_value=_FakeSourceApp(),
            ), patch.object(
                module,
                "_build_local_live_snapshot_payload",
                side_effect=_fake_local_payload,
            ), patch.object(
                module,
                "_build_bundle_local_live_snapshot_payload",
                return_value=None,
            ):
                copied = module._export_live_snapshot_artifacts(
                    source_root=source_root,
                    date_str="2026-06-05",
                    processed_root=processed_root,
                )

            self.assertIn("live_lines_path", copied)
            lines_payload = module._read_live_snapshot_payload(processed_root / "live_snapshots" / "live_lines_2026-06-05.jsonl")

        lines = ((((lines_payload or {}).get("games") or [{}])[0].get("lines") or {}))
        self.assertEqual((lines.get("period_totals") or {}).get("q1"), 40.5)
        self.assertEqual((lines.get("period_spreads") or {}).get("q1"), -2.5)

    def test_export_live_snapshot_artifacts_builds_live_lines_from_processed_game_odds(self) -> None:
        module = self._load_module()

        class _FakeSourceApp:
            @staticmethod
            def _live_oddsapi_period_totals_for_game(date_str, home_tri, away_tri):
                return {}

        def _fake_local_payload(*, kind, date_str, event_ids):
            if kind == "live_state":
                return {
                    "ok": True,
                    "games": [
                        {
                            "event_id": "401856963",
                            "game_id": "0401",
                            "home": "LVA",
                            "away": "NYL",
                            "in_progress": False,
                            "final": True,
                            "status": "Final",
                        }
                    ],
                }
            if kind == "live_lines":
                return {"ok": True, "games": [{"event_id": "401856963", "found": True, "lines": {"period_totals": None, "period_spreads": None}}]}
            return None

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            processed_root = tmp_root / "bundle" / "data" / "processed"
            (source_root / "data" / "processed").mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)
            (source_root / "data" / "processed" / "game_odds_2026-06-05.csv").write_text(
                "date,commence_time,home_team,visitor_team,home_ml,away_ml,home_spread,away_spread,total,bookmaker\n"
                "2026-06-05,2026-06-05T23:00:00Z,Las Vegas Aces,New York Liberty,-140,120,-4.5,4.5,163.5,oddsapi_consensus\n",
                encoding="utf-8",
            )

            with patch.object(module, "_source_app_fallback_enabled", return_value=False), patch.object(
                module,
                "_load_source_app",
                return_value=_FakeSourceApp(),
            ), patch.object(
                module,
                "_build_local_live_snapshot_payload",
                side_effect=_fake_local_payload,
            ), patch.object(
                module,
                "_build_bundle_local_live_snapshot_payload",
                return_value=None,
            ):
                copied = module._export_live_snapshot_artifacts(
                    source_root=source_root,
                    date_str="2026-06-05",
                    processed_root=processed_root,
                )

            self.assertIn("live_lines_path", copied)
            lines_payload = module._read_live_snapshot_payload(processed_root / "live_snapshots" / "live_lines_2026-06-05.jsonl")

        game = ((lines_payload or {}).get("games") or [{}])[0]
        lines = game.get("lines") or {}
        self.assertEqual(lines.get("total"), 163.5)
        self.assertEqual(lines.get("home_spread"), -4.5)
        self.assertEqual(lines.get("away_spread"), 4.5)
        self.assertEqual(game.get("home"), "LVA")
        self.assertEqual(game.get("away"), "NYL")

    def test_materialize_artifact_bundle_exports_live_snapshots_when_outputs_already_in_bundle(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            artifact_root = tmp_root / "bundle"
            processed_root = artifact_root / "data" / "processed"
            raw_root = artifact_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            source_root = tmp_root / "source"
            source_root.mkdir(parents=True, exist_ok=True)

            state = {
                "date": "2026-06-06",
                "snapshot_alias_path": str(processed_root / "oddsapi_player_props_2026-06-06.csv"),
                "predictions_path": str(processed_root / "props_predictions_2026-06-06.csv"),
                "edges_path": str(processed_root / "props_edges_2026-06-06.csv"),
                "recs_path": str(processed_root / "props_recommendations_2026-06-06.csv"),
                "snapshot_path": str(raw_root / "odds_wnba_player_props_2026-06-06.csv"),
            }
            for path_text in state.values():
                if isinstance(path_text, str) and path_text.endswith((".csv", ".jsonl", ".json")):
                    Path(path_text).parent.mkdir(parents=True, exist_ok=True)
                    Path(path_text).write_text("id\n1\n", encoding="utf-8")

            with patch.object(module, "_export_live_snapshot_artifacts", return_value={"live_lines_path": "written"}) as export_snapshots, patch.object(
                module,
                "_build_optional_player_recon_artifacts",
                return_value={},
            ):
                copied = module._materialize_artifact_bundle(
                    state=state,
                    artifact_root=artifact_root,
                    source_root=source_root,
                )

        export_snapshots.assert_called_once_with(source_root=artifact_root, date_str="2026-06-06", processed_root=processed_root)
        self.assertEqual(copied.get("live_lines_path"), "written")

    def test_materialize_artifact_bundle_builds_game_cards_when_bundle_lacks_export(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            artifact_root = tmp_root / "bundle"
            processed_root = artifact_root / "data" / "processed"
            raw_root = artifact_root / "data" / "raw"
            processed_root.mkdir(parents=True, exist_ok=True)
            raw_root.mkdir(parents=True, exist_ok=True)
            source_root = tmp_root / "source"
            source_root.mkdir(parents=True, exist_ok=True)

            date_str = "2026-06-27"
            (processed_root / f"game_odds_{date_str}.csv").write_text(
                "date,home_team,visitor_team,commence_time,home_ml,away_ml,home_spread,away_spread,total,bookmaker\n"
                "2026-06-27,Chicago Sky,Minnesota Lynx,2026-06-27T23:00:00Z,-140,120,-4.5,4.5,164.5,oddsapi_consensus\n",
                encoding="utf-8",
            )
            (raw_root / f"odds_wnba_player_props_{date_str}.csv").write_text(
                "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
                "2026-06-27T12:00:00Z,401,2026-06-27T23:00:00Z,fanduel,FanDuel,h2h,Chicago Sky,,,-140,2026-06-27T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-06-27T12:00:00Z,401,2026-06-27T23:00:00Z,fanduel,FanDuel,h2h,Minnesota Lynx,,,120,2026-06-27T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-06-27T12:00:00Z,401,2026-06-27T23:00:00Z,fanduel,FanDuel,spreads,Chicago Sky,,-4.5,-110,2026-06-27T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-06-27T12:00:00Z,401,2026-06-27T23:00:00Z,fanduel,FanDuel,spreads,Minnesota Lynx,,4.5,-110,2026-06-27T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-06-27T12:00:00Z,401,2026-06-27T23:00:00Z,fanduel,FanDuel,totals,Over,,164.5,-110,2026-06-27T12:00:00Z,Chicago Sky,Minnesota Lynx\n"
                "2026-06-27T12:00:00Z,401,2026-06-27T23:00:00Z,fanduel,FanDuel,totals,Under,,164.5,-110,2026-06-27T12:00:00Z,Chicago Sky,Minnesota Lynx\n",
                encoding="utf-8",
            )

            state = {
                "date": date_str,
                "snapshot_alias_path": str(processed_root / f"oddsapi_player_props_{date_str}.csv"),
                "predictions_path": str(processed_root / f"props_predictions_{date_str}.csv"),
                "edges_path": str(processed_root / f"props_edges_{date_str}.csv"),
                "recs_path": str(processed_root / f"props_recommendations_{date_str}.csv"),
                "snapshot_path": str(raw_root / f"odds_wnba_player_props_{date_str}.csv"),
            }
            (processed_root / f"oddsapi_player_props_{date_str}.csv").write_text("id\n1\n", encoding="utf-8")

            with patch.object(module, "_export_recon_games_artifact", return_value=None), patch.object(module, "_export_recon_quarters_artifact", return_value=None), patch.object(module, "_export_boxscores_artifact", return_value=None), patch.object(module, "_export_recommendations_artifact", return_value=None), patch.object(module, "_export_recommendations_slate_snapshot", return_value=None), patch.object(module, "_export_cards_props_snapshot", return_value=None), patch.object(module, "_export_cards_sim_detail_snapshot", return_value=None), patch.object(module, "_export_top_by_game_snapshot", return_value=None), patch.object(module, "_export_live_lens_artifacts", return_value={}), patch.object(module, "_build_optional_player_recon_artifacts", return_value={}), patch.object(module, "_export_live_snapshot_artifacts", return_value={}):
                copied = module._materialize_artifact_bundle(
                    state=state,
                    artifact_root=artifact_root,
                    source_root=source_root,
                )

            game_cards_path = processed_root / f"game_cards_{date_str}.csv"
            self.assertTrue(game_cards_path.exists())
            self.assertIn("game_cards_path", copied)
            written = game_cards_path.read_text(encoding="utf-8")
            self.assertIn("Chicago Sky", written)
            self.assertIn("Minnesota Lynx", written)

    def test_main_materializes_core_artifacts_into_bundle_root(self) -> None:
        module = self._load_module()

        class _FakeSourceModule:
            def run_refresh_oddsapi_props_job(self, **kwargs):
                return {
                    "date": "2026-05-22",
                    "snapshot_rows": 12,
                    "snapshot_alias_rows": 12,
                    "edges_rows": 5,
                    "recs_rows": 3,
                    "error": None,
                    "snapshot_path": kwargs["log_file"].parent / "odds_wnba_player_props_2026-05-22.csv",
                    "snapshot_alias_path": kwargs["log_file"].parent / "oddsapi_player_props_2026-05-22.csv",
                    "predictions_path": kwargs["log_file"].parent / "props_predictions_2026-05-22.csv",
                    "edges_path": kwargs["log_file"].parent / "props_edges_2026-05-22.csv",
                    "recs_path": kwargs["log_file"].parent / "props_recommendations_2026-05-22.csv",
                }

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            for name in [
                "odds_wnba_player_props_2026-05-22.csv",
                "oddsapi_player_props_2026-05-22.csv",
                "props_predictions_2026-05-22.csv",
                "props_edges_2026-05-22.csv",
                "props_recommendations_2026-05-22.csv",
                "smart_sim_2026-05-22_ATL_DAL.json",
                "smart_sim_2026-05-22_IND_GSV.json",
            ]:
                (tmp_root / name).write_text("id\n1\n", encoding="utf-8")
            source_root = tmp_root / "source"
            source_root.mkdir()
            artifact_root = tmp_root / "bundle"
            argv = [
                "refresh_wnba_oddsapi_props.py",
                "--date",
                "2026-05-22",
                "--regions",
                "us",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--log-file",
                str(tmp_root / "refresh.log"),
                "--do-edges",
                "--do-export",
            ]
            class _FakeSourceApp:
                class _Client:
                    @staticmethod
                    def get(query):
                        class _Response:
                            @staticmethod
                            def get_json():
                                if "cron/reconcile-games" in query:
                                    recon_source = tmp_root / "recon_games_2026-05-22.csv"
                                    recon_source.write_text("game_id\n123\n", encoding="utf-8")
                                    return {"output": str(recon_source), "rows": 1}
                                if "view=slate" in query:
                                    return {"games": [{"home_tri": "ATL", "away_tri": "DAL"}]}
                                if "/api/cards" in query:
                                    return {
                                        "games": [
                                            {
                                                "home_tri": "ATL",
                                                "away_tri": "DAL",
                                                "prop_recommendations": {
                                                    "home": [{"player": "Home WNBA Prop"}],
                                                    "away": [{"player": "Away WNBA Prop"}],
                                                },
                                                "sim": {
                                                    "players": {
                                                        "home": [{"player": "Home WNBA Sim"}],
                                                        "away": [{"player": "Away WNBA Sim"}],
                                                    },
                                                    "missing_prop_players": {
                                                        "home": [{"player": "Missing Home WNBA"}],
                                                        "away": [{"player": "Missing Away WNBA"}],
                                                    },
                                                    "injuries": {
                                                        "home": [{"player": "Injured Home WNBA"}],
                                                        "away": [{"player": "Injured Away WNBA"}],
                                                    },
                                                },
                                            }
                                        ]
                                    }
                                return {"data": [{"player": "Test WNBA Player"}]}

                            @staticmethod
                            def get_data():
                                if "download_live_lens_signals" in query:
                                    return b'{"kind":"signal"}\n'
                                if "download_live_lens_projections" in query:
                                    return b'{"kind":"projection"}\n'
                                if "download_live_lens_tuning" in query:
                                    return b'{"alpha": 1.25}\n'
                                return b""

                            status_code = 200

                        return _Response()

                app = type("_App", (), {"test_client": staticmethod(lambda: _FakeSourceApp._Client())})()

            def _fake_optional_artifacts(*, source_root, date_str, processed_root):
                recon_path = processed_root / f"recon_players_{date_str}.csv"
                tuning_path = processed_root / f"live_player_lens_tuning_{date_str}.csv"
                recon_path.write_text("player\nTest WNBA Player\n", encoding="utf-8")
                tuning_path.write_text("player\nTest WNBA Player\n", encoding="utf-8")
                return {
                    "recon_players_path": str(recon_path),
                    "live_player_lens_tuning_path": str(tuning_path),
                }

            def _fake_recon_quarters_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"recon_quarters_{date_str}.csv"
                out_path.write_text("game_id\nquarter-123\n", encoding="utf-8")
                return str(out_path)

            def _fake_recon_props_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"recon_props_{date_str}.csv"
                out_path.write_text("player_id\n42\n", encoding="utf-8")
                return str(out_path)

            def _fake_recon_games_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"recon_games_{date_str}.csv"
                out_path.write_text("game_id\n123\n", encoding="utf-8")
                return str(out_path)

            def _fake_game_cards_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"game_cards_{date_str}.csv"
                out_path.write_text("game_id\ncard-123\n", encoding="utf-8")
                return str(out_path)

            def _fake_boxscores_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"boxscores_{date_str}.csv"
                out_path.write_text("gameId\nbox-123\n", encoding="utf-8")
                return str(out_path)

            def _fake_recommendations_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"recommendations_{date_str}.csv"
                out_path.write_text("market\nATS\n", encoding="utf-8")
                return str(out_path)

            def _fake_cards_sim_detail_artifact(*, source_root, date_str, processed_root, force_refresh=False):
                out_path = processed_root / f"cards_sim_detail_{date_str}.json"
                out_path.write_text('{"games": []}\n', encoding="utf-8")
                return str(out_path)

            def _fake_recommendations_slate_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"recommendations_slate_{date_str}.json"
                out_path.write_text('{"counts": {"games": 1, "picks": 1}, "per_game": []}\n', encoding="utf-8")
                return str(out_path)

            def _fake_cards_props_snapshot_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"cards_props_snapshot_{date_str}.json"
                out_path.write_text('{"games": []}\n', encoding="utf-8")
                return str(out_path)

            def _fake_top_by_game_artifact(*, source_root, date_str, processed_root):
                out_path = processed_root / f"props_recommendations_top_by_game_{date_str}.json"
                out_path.write_text('{"data": []}\n', encoding="utf-8")
                return str(out_path)

            def _fake_live_lens_artifacts(*, source_root, date_str, processed_root, live_lens_root):
                processed_root.mkdir(parents=True, exist_ok=True)
                live_lens_root.mkdir(parents=True, exist_ok=True)
                signals_processed = processed_root / f"live_lens_signals_{date_str}.jsonl"
                projections_processed = processed_root / f"live_lens_projections_{date_str}.jsonl"
                tuning_processed = processed_root / "live_lens_tuning_override.json"
                signals_live_lens = live_lens_root / f"live_lens_signals_{date_str}.jsonl"
                projections_live_lens = live_lens_root / f"live_lens_projections_{date_str}.jsonl"
                tuning_live_lens = live_lens_root / "live_lens_tuning_override.json"
                for path, content in (
                    (signals_processed, '{"kind":"signal"}\n'),
                    (projections_processed, '{"kind":"projection"}\n'),
                    (tuning_processed, '{"alpha":1.25}\n'),
                    (signals_live_lens, '{"kind":"signal"}\n'),
                    (projections_live_lens, '{"kind":"projection"}\n'),
                    (tuning_live_lens, '{"alpha":1.25}\n'),
                ):
                    path.write_text(content, encoding="utf-8")
                return {
                    "live_lens_signals_path": str(signals_processed),
                    "live_lens_projections_path": str(projections_processed),
                    "live_lens_tuning_override_path": str(tuning_processed),
                    "live_lens_signals_live_lens_path": str(signals_live_lens),
                    "live_lens_projections_live_lens_path": str(projections_live_lens),
                    "live_lens_tuning_override_live_lens_path": str(tuning_live_lens),
                }

            with patch.object(module, "_run_refresh_via_cli", return_value=_FakeSourceModule().run_refresh_oddsapi_props_job(log_file=tmp_root / "refresh.log")), patch.object(module, "_load_source_app", return_value=_FakeSourceApp()), patch.object(module, "_build_optional_player_recon_artifacts", side_effect=_fake_optional_artifacts), patch.object(module, "_export_recon_games_artifact", side_effect=_fake_recon_games_artifact), patch.object(module, "_export_game_cards_artifact", side_effect=_fake_game_cards_artifact), patch.object(module, "_export_boxscores_artifact", side_effect=_fake_boxscores_artifact), patch.object(module, "_export_recommendations_artifact", side_effect=_fake_recommendations_artifact), patch.object(module, "_export_recommendations_slate_snapshot", side_effect=_fake_recommendations_slate_artifact), patch.object(module, "_export_cards_props_snapshot", side_effect=_fake_cards_props_snapshot_artifact), patch.object(module, "_export_cards_sim_detail_snapshot", side_effect=_fake_cards_sim_detail_artifact), patch.object(module, "_export_top_by_game_snapshot", side_effect=_fake_top_by_game_artifact), patch.object(module, "_export_live_lens_artifacts", side_effect=_fake_live_lens_artifacts), patch.object(module, "_export_recon_quarters_artifact", side_effect=_fake_recon_quarters_artifact), patch.object(module, "_export_recon_props_artifact", side_effect=_fake_recon_props_artifact), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "raw" / "odds_wnba_player_props_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "oddsapi_player_props_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_predictions_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_edges_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_recommendations_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "smart_sim_2026-05-22_ATL_DAL.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "smart_sim_2026-05-22_IND_GSV.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "recon_games_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "game_cards_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "boxscores_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "recommendations_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "recon_quarters_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "recon_props_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "recommendations_slate_2026-05-22.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "cards_props_snapshot_2026-05-22.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "cards_sim_detail_2026-05-22.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_recommendations_top_by_game_2026-05-22.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "live_lens_signals_2026-05-22.jsonl").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "live_lens_projections_2026-05-22.jsonl").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "live_lens_tuning_override.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "recon_players_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "live_player_lens_tuning_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / "live_lens_signals_2026-05-22.jsonl").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / "live_lens_projections_2026-05-22.jsonl").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / "live_lens_tuning_override.json").exists())

    def test_main_prefers_existing_refresh_outputs_before_source_job(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            artifact_root = tmp_root / "bundle"
            date_str = "2026-05-22"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)

            required_files = {
                raw_root / f"odds_wnba_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"oddsapi_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"predictions_{date_str}.csv": "home_team,visitor_team\nCHI,MIN\n",
                processed_root / f"props_predictions_{date_str}.csv": "player\nA\n",
                processed_root / f"props_edges_{date_str}.csv": "player\nA\n",
                processed_root / f"props_recommendations_{date_str}.csv": "player\nA\n",
                processed_root / f"game_cards_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recommendations_slate_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"cards_props_snapshot_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"cards_sim_detail_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"props_recommendations_top_by_game_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"boxscores_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recommendations_{date_str}.csv": "market\nATS\n",
                processed_root / f"recon_quarters_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recon_props_{date_str}.csv": "player_id\n1\n",
                processed_root / f"recon_games_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recommendations_slate_{date_str}.json": '{"ok": true}\n',
                processed_root / f"cards_props_snapshot_{date_str}.json": '{"ok": true}\n',
                processed_root / f"cards_sim_detail_{date_str}.json": '{"ok": true}\n',
                processed_root / f"props_recommendations_top_by_game_{date_str}.json": '{"ok": true}\n',
                processed_root / f"live_lens_signals_{date_str}.jsonl": '{"kind":"signal"}\n',
                processed_root / f"live_lens_projections_{date_str}.jsonl": '{"kind":"projection"}\n',
                processed_root / "live_lens_tuning_override.json": '{"alpha":1.25}\n',
                processed_root / f"recon_players_{date_str}.csv": "player\nA\n",
                processed_root / f"live_player_lens_tuning_{date_str}.csv": "player\nA\n",
            }
            for path, content in required_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            (processed_root / "boxscores_2026-05-21.csv").write_text("game_id,player_id\nold-game,11\n", encoding="utf-8")
            (processed_root / "smart_sim_2026-05-22_ATL_DAL.json").write_text('{"ok": true}\n', encoding="utf-8")

            argv = [
                "refresh_wnba_oddsapi_props.py",
                "--date",
                date_str,
                "--regions",
                "us",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--log-file",
                str(tmp_root / "refresh.log"),
                "--do-edges",
                "--do-export",
            ]
            with patch.object(module, "_run_refresh_via_cli", side_effect=AssertionError("cli refresh path should not load")), patch.object(module, "_load_source_app", side_effect=AssertionError("source app should not load")), patch.object(module, "_load_source_cli", side_effect=AssertionError("source cli should not load")), patch.object(module, "_load_module_from_path", side_effect=AssertionError("source tools should not load")), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "raw" / f"odds_wnba_player_props_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / f"props_predictions_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / f"props_edges_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / f"props_recommendations_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / f"game_cards_{date_str}.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "boxscores_history.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "smart_sim_2026-05-22_ATL_DAL.json").exists())
            history_text = (artifact_root / "data" / "processed" / "boxscores_history.csv").read_text(encoding="utf-8")
            self.assertIn("old-game", history_text)
            self.assertIn("game_id", history_text)

    def test_main_prefers_existing_artifact_bundle_before_source_job(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "missing-source"
            artifact_root = tmp_root / "bundle"
            raw_root = artifact_root / "data" / "raw"
            processed_root = artifact_root / "data" / "processed"
            date_str = "2026-05-22"

            required_files = {
                raw_root / f"odds_wnba_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"oddsapi_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"predictions_{date_str}.csv": "home_team,visitor_team\nCHI,MIN\n",
                processed_root / f"props_predictions_{date_str}.csv": "player\nA\n",
                processed_root / f"props_edges_{date_str}.csv": "player\nA\n",
                processed_root / f"props_recommendations_{date_str}.csv": "player\nA\n",
                processed_root / f"game_cards_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recommendations_slate_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"cards_props_snapshot_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"cards_sim_detail_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"props_recommendations_top_by_game_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"smart_sim_{date_str}_ATL_DAL.json": "{\"ok\": true}\n",
            }
            for path, content in required_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            argv = [
                "refresh_wnba_oddsapi_props.py",
                "--date",
                date_str,
                "--regions",
                "us",
                "--artifact-root",
                str(artifact_root),
                "--log-file",
                str(tmp_root / "refresh.log"),
                "--do-edges",
                "--do-export",
            ]
            with patch.object(module, "_run_refresh_via_cli", side_effect=AssertionError("cli refresh path should not load")), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)

    def test_main_refreshes_live_snapshots_even_when_reusing_existing_outputs(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            raw_root = source_root / "data" / "raw"
            processed_root = source_root / "data" / "processed"
            artifact_root = tmp_root / "bundle"
            date_str = "2026-05-22"
            raw_root.mkdir(parents=True, exist_ok=True)
            processed_root.mkdir(parents=True, exist_ok=True)

            required_files = {
                raw_root / f"odds_wnba_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"oddsapi_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"predictions_{date_str}.csv": "home_team,visitor_team\nCHI,MIN\n",
                processed_root / f"props_predictions_{date_str}.csv": "player\nA\n",
                processed_root / f"props_edges_{date_str}.csv": "player\nA\n",
                processed_root / f"props_recommendations_{date_str}.csv": "player\nA\n",
                processed_root / f"game_cards_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recommendations_slate_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"cards_props_snapshot_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"cards_sim_detail_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"props_recommendations_top_by_game_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"boxscores_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recommendations_{date_str}.csv": "market\nATS\n",
                processed_root / f"recon_quarters_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recon_props_{date_str}.csv": "player_id\n1\n",
                processed_root / f"recon_games_{date_str}.csv": "game_id\n1\n",
                processed_root / f"live_lens_signals_{date_str}.jsonl": '{"kind":"signal"}\n',
                processed_root / f"live_lens_projections_{date_str}.jsonl": '{"kind":"projection"}\n',
                processed_root / "live_lens_tuning_override.json": '{"alpha":1.25}\n',
                processed_root / f"recon_players_{date_str}.csv": "player\nA\n",
                processed_root / f"live_player_lens_tuning_{date_str}.csv": "player\nA\n",
            }
            for path, content in required_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            (processed_root / "smart_sim_2026-05-22_ATL_DAL.json").write_text('{"ok": true}\n', encoding="utf-8")

            argv = [
                "refresh_wnba_oddsapi_props.py",
                "--date",
                date_str,
                "--regions",
                "us",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--log-file",
                str(tmp_root / "refresh.log"),
                "--mode",
                "fast",
                "--do-edges",
                "--do-export",
            ]
            with patch.object(
                module, "_run_refresh_via_cli", side_effect=AssertionError("cli refresh path should not load")
            ), patch.object(
                module, "_export_live_snapshot_artifacts", return_value={}
            ) as export_snapshots, patch(
                "sys.argv", argv
            ):
                rc = module.main()

            self.assertEqual(rc, 0)
            export_snapshots.assert_called_once_with(
                source_root=source_root.resolve(),
                date_str=date_str,
                processed_root=(artifact_root / "data" / "processed").resolve(),
            )

    def test_main_skips_live_snapshot_refresh_without_source_root(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            artifact_root = tmp_root / "bundle"
            raw_root = artifact_root / "data" / "raw"
            processed_root = artifact_root / "data" / "processed"
            date_str = "2026-05-22"

            required_files = {
                raw_root / f"odds_wnba_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"oddsapi_player_props_{date_str}.csv": "id\n1\n",
                processed_root / f"props_predictions_{date_str}.csv": "player\nA\n",
                processed_root / f"props_edges_{date_str}.csv": "player\nA\n",
                processed_root / f"props_recommendations_{date_str}.csv": "player\nA\n",
                processed_root / f"game_cards_{date_str}.csv": "game_id\n1\n",
                processed_root / f"recommendations_slate_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"cards_props_snapshot_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"cards_sim_detail_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"props_recommendations_top_by_game_{date_str}.json": "{\"ok\": true}\n",
                processed_root / f"smart_sim_{date_str}_ATL_DAL.json": "{\"ok\": true}\n",
            }
            for path, content in required_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            argv = [
                "refresh_wnba_oddsapi_props.py",
                "--date",
                date_str,
                "--regions",
                "us",
                "--artifact-root",
                str(artifact_root),
                "--log-file",
                str(tmp_root / "refresh.log"),
                "--mode",
                "fast",
                "--do-edges",
                "--do-export",
            ]
            with patch.object(
                module, "_run_refresh_via_cli", side_effect=AssertionError("cli refresh path should not load")
            ), patch.object(module, "_export_live_snapshot_artifacts") as export_snapshots, patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            export_snapshots.assert_not_called()

    def test_canonical_wnba_tri_does_not_confuse_la_sparks_with_las_vegas(self) -> None:
        module = self._load_module()

        # LA Sparks' own canonical code is "LAS" -- it must be stable under
        # repeated canonicalization, not drift into Las Vegas' "LVA" code.
        self.assertEqual(module._canonical_wnba_tri("LAS"), "LAS")
        self.assertEqual(module._canonical_wnba_tri("LA"), "LAS")
        self.assertEqual(module._canonical_wnba_tri(module._to_tricode_local("Los Angeles Sparks")), "LAS")

        # Las Vegas Aces must still resolve correctly via its own aliases.
        self.assertEqual(module._canonical_wnba_tri("LV"), "LVA")
        self.assertEqual(module._canonical_wnba_tri("LVA"), "LVA")
        self.assertEqual(module._canonical_wnba_tri(module._to_tricode_local("Las Vegas Aces")), "LVA")
