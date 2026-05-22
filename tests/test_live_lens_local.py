from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.nhl.live_game_accuracy import build_live_game_accuracy_payload as build_nhl_game_accuracy
from syndicate.features.nhl.live_lens_daily_accuracy import build_live_lens_daily_accuracy_payload as build_nhl_daily_accuracy
from syndicate.features.nhl.market_accuracy import build_market_accuracy_payload as build_nhl_market_accuracy
from syndicate.features.nhl.betting_recap import build_betting_recap_payload as build_nhl_betting_recap
from syndicate.features.nhl.player_props_reconciliation import build_player_props_reconciliation_payload as build_nhl_props_reconciliation
from syndicate.features.nhl.props_lines import build_props_lines_payload as build_nhl_props_lines
from syndicate.features.mlb.live_lens_daily_accuracy import build_live_lens_daily_accuracy_payload as build_mlb_daily_accuracy
from syndicate.features.nba.live_lens_daily_accuracy import build_live_lens_daily_accuracy_payload as build_nba_daily_accuracy
from syndicate.features.wnba.live_lens_daily_accuracy import build_live_lens_daily_accuracy_payload as build_wnba_daily_accuracy
from syndicate.features.wnba.live_game_accuracy import build_live_game_accuracy_payload as build_wnba_game_accuracy
from syndicate.features.wnba.live_prop_accuracy import build_live_prop_accuracy_payload as build_wnba_prop_accuracy
from syndicate.features.wnba.live_prop_audit import build_live_prop_audit_payload as build_wnba_prop_audit


def _write_daily_accuracy_artifacts(root: Path, date_str: str) -> None:
    signals = [
        {
            "market": "total",
            "klass": "BET",
            "game_id": "1234567890",
            "home": "HOM",
            "away": "AWY",
            "side": "OVER",
            "live_line": 160.5,
            "elapsed": 18,
            "remaining": 30,
            "tags": ["sim:pace"],
        },
        {
            "market": "player_prop",
            "klass": "BET",
            "game_id": "1234567890",
            "player": "Jane Doe",
            "name_key": "Jane Doe",
            "side": "OVER",
            "stat": "points",
            "line": 19.5,
            "elapsed": 18,
            "remaining": 30,
            "tags": ["pace:up"],
        },
    ]
    (root / f"live_lens_signals_{date_str}.jsonl").write_text(
        "\n".join(json.dumps(row) for row in signals),
        encoding="utf-8",
    )


def _write_mlb_registry_artifact(root: Path, date_str: str) -> None:
    payload = {
        "date": date_str,
        "updatedAt": f"{date_str}T20:49:39-05:00",
        "entries": {
            "1|jane doe|hitter_props|hits|over|0.500": {
                "key": "1|jane doe|hitter_props|hits|over|0.500",
                "date": date_str,
                "gamePk": 1,
                "owner": "Jane Doe",
                "market": "hitter_props",
                "prop": "hits",
                "selection": "over",
                "marketLine": 0.5,
                "firstSeenAt": f"{date_str}T19:00:00-05:00",
                "firstSeenSnapshot": {"selection": "over", "marketLine": 0.5, "actual": 0.0},
                "lastSeenAt": f"{date_str}T22:00:00-05:00",
                "lastSeenSnapshot": {"selection": "over", "marketLine": 0.5, "actual": 1.0},
            },
            "1|john doe|pitcher_props|strikeouts|under|5.500": {
                "key": "1|john doe|pitcher_props|strikeouts|under|5.500",
                "date": date_str,
                "gamePk": 1,
                "owner": "John Doe",
                "market": "pitcher_props",
                "prop": "strikeouts",
                "selection": "under",
                "marketLine": 5.5,
                "firstSeenAt": f"{date_str}T19:00:00-05:00",
                "firstSeenSnapshot": {"selection": "under", "marketLine": 5.5, "actual": 2.0},
                "lastSeenAt": f"{date_str}T22:00:00-05:00",
                "lastSeenSnapshot": {"selection": "under", "marketLine": 5.5, "actual": 7.0},
            },
            "1|pending bat|hitter_props|runs|under|0.500": {
                "key": "1|pending bat|hitter_props|runs|under|0.500",
                "date": date_str,
                "gamePk": 1,
                "owner": "Pending Bat",
                "market": "hitter_props",
                "prop": "runs",
                "selection": "under",
                "marketLine": 0.5,
                "firstSeenAt": f"{date_str}T19:00:00-05:00",
                "firstSeenSnapshot": {"selection": "under", "marketLine": 0.5, "actual": None},
                "lastSeenAt": f"{date_str}T20:00:00-05:00",
                "lastSeenSnapshot": {"selection": "under", "marketLine": 0.5, "actual": None},
            },
        },
    }
    (root / f"live_prop_registry_{date_str.replace('-', '_')}.json").write_text(json.dumps(payload), encoding="utf-8")
    (root / f"recon_games_{date_str}.csv").write_text(
        "game_id,total_actual,home_pts,visitor_pts\n1234567890,171,90,81\n",
        encoding="utf-8",
    )


def _write_mlb_feed_live_artifact(root: Path, date_str: str) -> None:
    payload = {
        "liveData": {
            "boxscore": {
                "teams": {
                    "away": {
                        "players": {
                            "ID101": {
                                "person": {"id": 101, "fullName": "Jane Doe"},
                                "stats": {"batting": {"hits": 2, "runs": 1, "rbi": 0, "totalBases": 3, "homeRuns": 0}},
                            }
                        }
                    },
                    "home": {
                        "players": {
                            "ID202": {
                                "person": {"id": 202, "fullName": "John Doe"},
                                "stats": {"pitching": {"strikeOuts": 4}},
                            },
                            "ID303": {
                                "person": {"id": 303, "fullName": "Pending Bat"},
                                "stats": {"batting": {"hits": 0, "runs": 0, "rbi": 0, "totalBases": 0, "homeRuns": 0}},
                            },
                        }
                    },
                }
            }
        }
    }
    (root / f"{1}.json").write_text(json.dumps(payload), encoding="utf-8")
    (root / f"recon_props_{date_str}.csv").write_text(
        "game_id,player_name,pts\n1234567890,Jane Doe,22\n",
        encoding="utf-8",
    )


class LocalDailyAccuracyTests(unittest.TestCase):
    def test_mlb_daily_accuracy_prefers_feed_live_actuals_over_registry_snapshots(self) -> None:
        build_mlb_daily_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            _write_mlb_registry_artifact(artifact_root, "2026-05-16")
            _write_mlb_feed_live_artifact(artifact_root, "2026-05-16")
            with patch(
                "syndicate.features.mlb.live_lens_daily_accuracy.live_prop_registry_path",
                side_effect=lambda selected_date: artifact_root / f"live_prop_registry_{selected_date.replace('-', '_')}.json",
            ), patch(
                "syndicate.features.mlb.live_lens_daily_accuracy.raw_feed_live_path",
                side_effect=lambda selected_date, game_pk: artifact_root / f"{int(game_pk)}.json",
            ):
                payload = build_mlb_daily_accuracy("date=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["summary"]["wins"], 3)
        self.assertEqual(payload["summary"]["summary"]["losses"], 0)
        self.assertEqual(((payload["days"] or [])[0].get("signals") or {}).get("feedResolved"), 3)

    def test_mlb_daily_accuracy_uses_local_registry_artifacts(self) -> None:
        build_mlb_daily_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            _write_mlb_registry_artifact(artifact_root, "2026-05-16")
            with patch(
                "syndicate.features.mlb.live_lens_daily_accuracy.live_prop_registry_path",
                side_effect=lambda selected_date: artifact_root / f"live_prop_registry_{selected_date.replace('-', '_')}.json",
            ):
                payload = build_mlb_daily_accuracy("date=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "live-lens-accuracy-v1")
        self.assertTrue(payload["summary"]["available"])
        self.assertEqual(payload["summary"]["summary"]["wins"], 1)
        self.assertEqual(payload["summary"]["summary"]["losses"], 1)
        self.assertEqual(((payload["days"] or [])[0].get("signals") or {}).get("lines"), 3)

    def test_nba_daily_accuracy_uses_local_artifacts_before_source_proxy(self) -> None:
        build_nba_daily_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            _write_daily_accuracy_artifacts(artifact_root, "2026-05-16")
            with patch(
                "syndicate.features.nba.live_lens_daily_accuracy.processed_path",
                return_value=artifact_root / "game_cards_2099-01-01.csv",
            ):
                payload = build_nba_daily_accuracy("date=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "live-lens-accuracy-v1")
        self.assertTrue(payload["summary"]["available"])
        self.assertEqual(((payload["days"] or [])[0].get("date")), "2026-05-16")
        self.assertTrue(bool((((payload["days"] or [])[0].get("signals") or {}).get("exists"))))


def _write_game_accuracy_artifacts(root: Path, date_str: str) -> None:
    signals = [
        {
            "market": "total",
            "klass": "BET",
            "game_id": "1234567890",
            "home": "HOM",
            "away": "AWY",
            "side": "OVER",
            "live_line": 160.5,
            "elapsed": 18,
            "remaining": 30,
            "tags": ["sim:pace"],
        },
        {
            "market": "ats",
            "klass": "BET",
            "game_id": "1234567890",
            "home": "HOM",
            "away": "AWY",
            "side": "HOME",
            "live_line": -2.5,
            "elapsed": 18,
            "remaining": 30,
            "tags": ["injury:star"],
        },
    ]
    (root / f"live_lens_signals_{date_str}.jsonl").write_text(
        "\n".join(json.dumps(row) for row in signals),
        encoding="utf-8",
    )
    (root / f"recon_games_{date_str}.csv").write_text(
        "game_id,total_actual,home_pts,visitor_pts\n1234567890,171,90,81\n",
        encoding="utf-8",
    )


class LocalGameAccuracyTests(unittest.TestCase):
    def test_wnba_game_accuracy_uses_local_artifacts_before_source_proxy(self) -> None:
        build_wnba_game_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            _write_game_accuracy_artifacts(artifact_root, "2026-05-16")
            with patch(
                "syndicate.features.wnba.live_game_accuracy.processed_path",
                return_value=artifact_root / "game_cards_2099-01-01.csv",
            ):
                payload = build_wnba_game_accuracy("start=2026-05-16&end=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["overall"]["totals"]["n_settled"], 1)
        self.assertEqual(payload["overall"]["ats"]["n_settled"], 1)

    def test_wnba_game_accuracy_returns_local_empty_payload_without_artifacts(self) -> None:
        build_wnba_game_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            with patch(
                "syndicate.features.wnba.live_game_accuracy.processed_path",
                return_value=artifact_root / "game_cards_2099-01-01.csv",
            ):
                payload = build_wnba_game_accuracy("start=2026-05-16&end=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "empty")
        self.assertEqual(payload["meta"]["source"], "local_mirror")


class LocalPropAccuracyTests(unittest.TestCase):
    def test_wnba_prop_accuracy_returns_local_empty_payload_without_artifacts(self) -> None:
        build_wnba_prop_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            with patch(
                "syndicate.features.wnba.live_prop_accuracy.processed_path",
                return_value=artifact_root / "game_cards_2099-01-01.csv",
            ):
                payload = build_wnba_prop_accuracy("start=2026-05-16&end=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "empty")
        self.assertEqual(payload["meta"]["source"], "local_mirror")

    def test_wnba_prop_audit_returns_local_empty_payload_without_artifacts(self) -> None:
        build_wnba_prop_audit.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            with patch(
                "syndicate.features.wnba.live_prop_audit.processed_path",
                return_value=artifact_root / "game_cards_2099-01-01.csv",
            ):
                payload = build_wnba_prop_audit("date=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "empty")
        self.assertEqual(payload["meta"]["source"], "local_mirror")


class LocalWnbaDailyAccuracyTests(unittest.TestCase):
    def test_wnba_daily_accuracy_returns_local_empty_payload_without_artifacts(self) -> None:
        build_wnba_daily_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            with patch(
                "syndicate.features.wnba.live_lens_daily_accuracy.processed_path",
                return_value=artifact_root / "game_cards_2099-01-01.csv",
            ):
                payload = build_wnba_daily_accuracy("date=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["summary"]["available"])

    def test_nhl_game_accuracy_uses_local_artifacts_before_source_proxy(self) -> None:
        build_nhl_game_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            _write_game_accuracy_artifacts(artifact_root, "2026-05-16")
            with patch(
                "syndicate.features.nhl.live_game_accuracy.processed_path",
                return_value=artifact_root / "predictions_2099-01-01.csv",
            ):
                payload = build_nhl_game_accuracy("start=2026-05-16&end=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["overall"]["totals"]["n_settled"], 1)
        self.assertEqual(payload["overall"]["ats"]["n_settled"], 1)

    def test_nhl_game_accuracy_returns_local_empty_payload_without_artifacts(self) -> None:
        build_nhl_game_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            with patch(
                "syndicate.features.nhl.live_game_accuracy.processed_path",
                return_value=artifact_root / "predictions_2099-01-01.csv",
            ):
                payload = build_nhl_game_accuracy("days=14&full_game_only=1")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "empty")
        self.assertEqual((payload["meta"] or {}).get("source"), "local_mirror")
        self.assertEqual(((payload["overall"] or {}).get("totals") or {}).get("n_settled"), 0)
        self.assertEqual(((payload["overall"] or {}).get("ats") or {}).get("n_settled"), 0)

    def test_wnba_daily_accuracy_uses_local_artifacts_before_source_proxy(self) -> None:
        build_wnba_daily_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            _write_daily_accuracy_artifacts(artifact_root, "2026-05-16")
            with patch(
                "syndicate.features.wnba.live_lens_daily_accuracy.processed_path",
                return_value=artifact_root / "game_cards_2099-01-01.csv",
            ):
                payload = build_wnba_daily_accuracy("date=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "live-lens-accuracy-v1")
        self.assertTrue(payload["summary"]["available"])
        self.assertEqual(((payload["days"] or [])[0].get("date")), "2026-05-16")
        self.assertTrue(bool((((payload["days"] or [])[0].get("signals") or {}).get("exists"))))


def _write_market_accuracy_artifacts(root: Path, date_str: str) -> None:
    (root / f"recommendations_sim_{date_str}.csv").write_text(
        "market,home_team,away_team,pick,spread,total,moneyline_home,moneyline_away,home_win_prob\n"
        "spread,HOM,AWY,HOME,-2.5,171,-120,100,0.60\n",
        encoding="utf-8",
    )
    (root / f"props_recommendations_{date_str}.csv").write_text(
        'player,team,plays\n'
        'Jane Doe,HOM,"[{""market"": ""pts"", ""side"": ""OVER"", ""line"": 19.5, ""price"": -110}]"\n',
        encoding="utf-8",
    )
    (root / f"recon_games_{date_str}.csv").write_text(
        "game_id,home_team,away_team,total_actual,home_pts,visitor_pts\n1234567890,HOM,AWY,171,90,81\n",
        encoding="utf-8",
    )
    (root / f"recon_props_{date_str}.csv").write_text(
        "game_id,player_name,team_abbr,pts\n1234567890,Jane Doe,HOM,22\n",
        encoding="utf-8",
    )


def _write_market_accuracy_logs(root: Path, date_str: str) -> None:
    (root / "reconciliations_log.csv").write_text(
        "date,home,away,market,bet,ev,price,result,stake,payout\n"
        f"{date_str}T21:00:00Z,HOM,AWY,totals,under,0.20,-110.0,win,100.0,90.91\n",
        encoding="utf-8",
    )
    (root / "props_reconciliations_log.csv").write_text(
        "date,market,player,line,side,odds,ev,actual,result,stake,payout\n"
        f"{date_str},POINTS,Jane Doe,19.5,Over,-110.0,0.10,22.0,win,100.0,90.91\n",
        encoding="utf-8",
    )


class LocalMarketAccuracyTests(unittest.TestCase):
    def test_nhl_market_accuracy_uses_local_artifacts_before_source_proxy(self) -> None:
        build_nhl_market_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            _write_market_accuracy_artifacts(artifact_root, "2026-05-16")
            with patch(
                "syndicate.features.nhl.market_accuracy.processed_path",
                return_value=artifact_root / "predictions_2099-01-01.csv",
            ):
                payload = build_nhl_market_accuracy("date=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "accuracy-market-v1")
        self.assertTrue(payload["summary"]["combined"]["available"])

    def test_nhl_market_accuracy_uses_local_logs_when_recon_csvs_absent(self) -> None:
        build_nhl_market_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            _write_market_accuracy_logs(artifact_root, "2026-03-01")
            with patch(
                "syndicate.features.nhl.market_accuracy.processed_path",
                return_value=artifact_root / "predictions_2099-01-01.csv",
            ):
                payload = build_nhl_market_accuracy("date=2026-03-01")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "accuracy-market-v1")
        self.assertEqual(payload["summary"]["games"]["overall"]["resolved"], 1)
        self.assertEqual(payload["summary"]["props"]["overall"]["resolved"], 1)

    def test_nhl_market_accuracy_returns_native_empty_payload_without_artifacts(self) -> None:
        build_nhl_market_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            with patch(
                "syndicate.features.nhl.market_accuracy.processed_path",
                return_value=artifact_root / "predictions_2099-01-01.csv",
            ):
                payload = build_nhl_market_accuracy("since=2026-05-01&until=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "accuracy-market-v1")
        self.assertEqual(payload["window"], {"since": "2026-05-01", "until": "2026-05-16"})
        self.assertFalse(payload["summary"]["combined"]["available"])
        self.assertEqual(payload["days"][0]["date"], "2026-05-01")
        self.assertEqual(payload["days"][-1]["date"], "2026-05-16")
        self.assertFalse(payload["days"][0]["combined"]["available"])
        self.assertEqual(payload["days"][0]["combined"]["overall"]["resolved"], 0)


class LocalBettingRecapTests(unittest.TestCase):
    def test_nhl_betting_recap_uses_local_logs(self) -> None:
        build_nhl_betting_recap.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            _write_market_accuracy_logs(artifact_root, "2026-03-01")
            with patch(
                "syndicate.features.nhl.betting_recap.processed_path",
                return_value=artifact_root / "predictions_2099-01-01.csv",
            ):
                payload = build_nhl_betting_recap("since=2026-03-01&until=2026-03-01")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "recaps-v1")
        self.assertEqual(payload["window"], {"since": "2026-03-01", "until": "2026-03-01"})
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual((payload["items"][0]["games"]["buckets"]["Overall"])["resolved"], 1)
        self.assertEqual((payload["items"][0]["props"]["buckets"]["Overall"])["resolved"], 1)


class LocalPlayerPropsReconciliationTests(unittest.TestCase):
    def test_nhl_player_props_reconciliation_uses_local_logs(self) -> None:
        build_nhl_props_reconciliation.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            _write_market_accuracy_logs(artifact_root, "2026-03-01")
            with patch(
                "syndicate.features.nhl.player_props_reconciliation.processed_path",
                return_value=artifact_root / "predictions_2099-01-01.csv",
            ):
                payload = build_nhl_props_reconciliation("date=2026-03-01")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "player-props-reconciliation-v1")
        self.assertEqual(payload["date"], "2026-03-01")
        self.assertEqual(payload["summary"]["settled"], 1)
        self.assertEqual(len(payload["data"]), 1)


class LocalNhlDailyAccuracyTests(unittest.TestCase):
    def test_nhl_daily_accuracy_returns_local_empty_payload_without_artifacts(self) -> None:
        build_nhl_daily_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            with patch(
                "syndicate.features.nhl.live_lens_daily_accuracy.processed_path",
                return_value=artifact_root / "predictions_2099-01-01.csv",
            ):
                payload = build_nhl_daily_accuracy("since=2026-05-01&until=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "live-lens-accuracy-v1")
        self.assertEqual(payload["window"], {"since": "2026-05-01", "until": "2026-05-16"})
        self.assertFalse(payload["summary"]["available"])
        self.assertEqual(payload["days"][0]["date"], "2026-05-01")
        self.assertEqual(payload["days"][-1]["date"], "2026-05-16")
        self.assertFalse(payload["days"][0]["available"])

    def test_nhl_daily_accuracy_uses_local_artifacts_before_source_proxy(self) -> None:
        build_nhl_daily_accuracy.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir)
            _write_daily_accuracy_artifacts(artifact_root, "2026-05-16")
            with patch(
                "syndicate.features.nhl.live_lens_daily_accuracy.processed_path",
                return_value=artifact_root / "predictions_2099-01-01.csv",
            ):
                payload = build_nhl_daily_accuracy("date=2026-05-16")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "live-lens-accuracy-v1")
        self.assertTrue(payload["summary"]["available"])
        self.assertEqual(((payload["days"] or [])[0].get("date")), "2026-05-16")
        self.assertTrue(bool((((payload["days"] or [])[0].get("signals") or {}).get("exists"))))


class LocalPropsLinesTests(unittest.TestCase):
    def test_nhl_props_lines_uses_local_mirrored_csv(self) -> None:
        build_nhl_props_lines.cache_clear()
        with TemporaryDirectory() as tmp_dir:
            artifact_root = Path(tmp_dir) / "data" / "nhl_source" / "data" / "props" / "player_props_lines" / "date=2026-05-19"
            artifact_root.mkdir(parents=True, exist_ok=True)
            (artifact_root / "oddsapi.csv").write_text(
                "date,player_id,player_name,team,market,line,over_price,under_price,book,first_seen_at,last_seen_at,is_current\n"
                "2026-05-19,1,Jane Doe,HOM,GOALS,0.5,130,-160,oddsapi,2026-05-19T10:00:00Z,2026-05-19T11:00:00Z,1\n",
                encoding="utf-8",
            )
            with patch(
                "syndicate.features.nhl.props_lines.default_nhl_source_root",
                return_value=Path(tmp_dir) / "data" / "nhl_source",
            ), patch(
                "syndicate.features.nhl.props_lines.default_date",
                return_value="2026-05-19",
            ):
                payload = build_nhl_props_lines("date=2026-05-19&market=GOALS")

        self.assertIsInstance(payload, dict)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], "props-lines-v1")
        self.assertEqual(payload["date"], "2026-05-19")
        self.assertEqual(payload["total_rows"], 1)
