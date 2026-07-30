from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared.odds_refresh_tracking import sync_post_refresh_tracking_for_source_root
from syndicate.features.shared.odds_refresh_tracking import refresh_impacted_recommendations_for_tracking
from syndicate.features.shared.odds_refresh_tracking import _odds_history_market_key
from syndicate.features.shared.odds_lifecycle import load_odds_lifecycle_events
from tests.test_refresh_state_store import _FakeKeyValueClient


class OddsHistoryMarketKeyTests(unittest.TestCase):
    # Confirmed live 2026-07-29: WNBA's live_lens_projections_*.jsonl rows
    # (log_pregame_prop_signals.py, the vendored pregame signal logger) use
    # "home"/"away"/"player"/"entity"/"team_tri" -- none of which matched
    # _odds_history_market_key's field list (home_team/away_team/player_name/
    # team/team_key), and "stat" (the actual points/rebounds/assists code)
    # wasn't checked at all, only the generic "market" category
    # ("player_prop"). Every real field silently missed, leaving only
    # game_id+market -- every player's every prop for one game collapsed
    # into a single history entry, showing several different props (and
    # players) with the identical, wrong line movement on the board.
    def _wnba_live_lens_row(self, *, player: str, stat: str, line: float) -> dict[str, object]:
        return {
            "away": "GSV",
            "home": "PHX",
            "event_id": "044c05d0bdf345dc1b2a2eef1bff78ce3",
            "game_id": "044c05d0bdf345dc1b2a2eef1bff78ce3",
            "entity": player,
            "player": player,
            "market": "player_prop",
            "stat": stat,
            "team_tri": "PHX",
            "line": line,
        }

    def test_distinct_players_in_the_same_game_get_distinct_keys(self) -> None:
        kahleah = _odds_history_market_key(self._wnba_live_lens_row(player="Kahleah Copper", stat="pra", line=23.5))
        alyssa = _odds_history_market_key(self._wnba_live_lens_row(player="Alyssa Thomas", stat="ast", line=8.5))
        self.assertIsNotNone(kahleah)
        self.assertIsNotNone(alyssa)
        self.assertNotEqual(kahleah, alyssa)

    def test_same_player_different_stat_gets_distinct_keys(self) -> None:
        pra = _odds_history_market_key(self._wnba_live_lens_row(player="Kahleah Copper", stat="pra", line=23.5))
        pts = _odds_history_market_key(self._wnba_live_lens_row(player="Kahleah Copper", stat="pts", line=17.5))
        self.assertIsNotNone(pra)
        self.assertIsNotNone(pts)
        self.assertNotEqual(pra, pts)


class OddsRefreshTrackingTests(unittest.TestCase):
    def test_sync_nhl_tracking_writes_tracking_files(self) -> None:
        # SYNDICATE_ODDS_EVENTS_ROOT keeps the lifecycle-event append from
        # landing in the real repo data/odds_events/ shard.
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports"), "SYNDICATE_ODDS_EVENTS_ROOT": str(Path(tmpdir) / "odds_events")}, clear=False):
            root = Path(tmpdir)
            props_root = root / "data" / "props" / "player_props_lines" / "date=2026-06-07"
            team_root = root / "data" / "odds" / "team" / "date=2026-06-07"
            props_root.mkdir(parents=True)
            team_root.mkdir(parents=True)
            (props_root / "oddsapi.csv").write_text(
                "player_name,market,book,line,over_price,last_seen_at\n"
                "Player One,POINTS,draftkings,2.5,-110,2026-06-07T12:00:00Z\n",
                encoding="utf-8",
            )
            (team_root / "oddsapi.csv").write_text(
                "home_team,away_team,bookmaker,market,selection,line,price\n"
                "Home,Away,draftkings,total,over,6.5,-110\n",
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            self.assertFalse(result.get("skipped", False))
            self.assertTrue((root / "tracking" / "odds_nhl_player_props_opening_2026-06-07.csv").exists())
            history_path = root / "tracking" / "odds_history" / "2026-06-07.json"
            shared_history_path = Path(result["artifacts"]["odds_history"]["shared_history_path"])
            self.assertTrue(history_path.exists())
            self.assertTrue(shared_history_path.exists())

            history_payload = json.loads(history_path.read_text(encoding="utf-8"))
            shared_history_payload = json.loads(shared_history_path.read_text(encoding="utf-8"))
            self.assertEqual(shared_history_payload["markets"].keys(), history_payload["markets"].keys())
            # Every market used to also be flattened onto the payload's own
            # top level (an exact duplicate of "markets", roughly doubling
            # this payload's size) -- confirmed no reader needs that shape
            # once "markets" is populated, so it should no longer appear.
            non_metadata_top_level_keys = set(history_payload) - {"schema_version", "sport", "shard_key", "date", "updated_at", "history_limit", "markets"}
            self.assertEqual(non_metadata_top_level_keys, set())
            market_key = next(key for key in history_payload["markets"] if "selection=over" in key)
            self.assertEqual(len(history_payload["markets"][market_key]["history"]), 1)
            first_state = history_payload["markets"][market_key]
            first_entry = first_state["history"][0]
            self.assertEqual(first_entry["market_id"], market_key)
            self.assertEqual(first_entry["sport"], "nhl")
            self.assertEqual(first_entry["event_id"], "Away@Home")
            self.assertEqual(first_entry["market_type"], "total")
            self.assertEqual(first_entry["entity"], "over")
            # "line" carries the raw price-field snapshot of the source row
            # (every populated line/price column); the canonical scalar the
            # board and intelligence readers consume is "current_line".
            self.assertEqual(first_entry["line"], {"line": 6.5, "price": -110})
            self.assertEqual(first_entry["current_line"], 6.5)
            self.assertEqual(first_entry["odds"], -110)
            # write_json_file re-renders "timestamp" keys in Central time
            # (normalize_timestamped_payload) while "captured_at" stays UTC --
            # same instant, different zone rendering.
            self.assertEqual(
                datetime.fromisoformat(first_entry["timestamp"]),
                datetime.fromisoformat(first_entry["captured_at"]),
            )
            self.assertEqual(first_state["last_line"], 6.5)
            self.assertEqual(first_state["movement"], "flat")
            self.assertIsNone(first_state["delta"])
            self.assertIsNone(first_state["percent_change"])

            (team_root / "oddsapi.csv").write_text(
                "home_team,away_team,bookmaker,market,selection,line,price\n"
                "Home,Away,draftkings,total,over,7.0,-110\n",
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            self.assertEqual(result["artifacts"]["odds_history"]["entries_appended"], 1)
            history_payload = json.loads(history_path.read_text(encoding="utf-8"))
            market_state = history_payload["markets"][market_key]
            self.assertEqual(len(market_state["history"]), 2)
            latest_entry = market_state["history"][-1]
            self.assertEqual(latest_entry["market_id"], market_key)
            self.assertEqual(latest_entry["sport"], "nhl")
            self.assertEqual(latest_entry["event_id"], "Away@Home")
            self.assertEqual(latest_entry["market_type"], "total")
            self.assertEqual(latest_entry["entity"], "over")
            self.assertEqual(latest_entry["line"], {"line": 7.0, "price": -110})
            self.assertEqual(latest_entry["current_line"], 7.0)
            self.assertEqual(latest_entry["odds"], -110)
            self.assertEqual(
                datetime.fromisoformat(latest_entry["timestamp"]),
                datetime.fromisoformat(latest_entry["captured_at"]),
            )
            self.assertEqual(market_state["last_line"], 7.0)
            self.assertEqual(market_state["movement"], "up")
            self.assertAlmostEqual(market_state["delta"], 0.5)
            self.assertAlmostEqual(market_state["percent_change"], 7.6923076923, places=6)
            self.assertNotEqual(market_state["history"][0]["current_line"], market_state["history"][1]["current_line"])
            self.assertEqual(market_state["history"][1]["movement"], "up")

    def test_history_strips_row_and_normalized_from_all_but_the_latest_entry(self) -> None:
        # #112. row/normalized (the full JSON-safe raw API row + normalized
        # entry) are the two heaviest fields on a history entry, and the
        # only reader of either (the missing-market "close" event synthesis)
        # only ever looks at the newest one. MLB's odds-history shard grew
        # to 18.9MB against the #60 8MB keyvalue ceiling on a normal slate
        # (confirmed live 2026-07-28) because every one of up to 50 entries
        # per market carried both fields in full. Stripping them from every
        # entry except the current last is what actually bounds shard size.
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports"), "SYNDICATE_ODDS_EVENTS_ROOT": str(Path(tmpdir) / "odds_events")}, clear=False):
            root = Path(tmpdir)
            team_root = root / "data" / "odds" / "team" / "date=2026-06-07"
            team_root.mkdir(parents=True)

            for line in ("6.5", "7.0", "7.5"):
                (team_root / "oddsapi.csv").write_text(
                    f"home_team,away_team,bookmaker,market,selection,line,price\nHome,Away,draftkings,total,over,{line},-110\n",
                    encoding="utf-8",
                )
                result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
                self.assertTrue(result["ok"])

            history_path = root / "tracking" / "odds_history" / "2026-06-07.json"
            history_payload = json.loads(history_path.read_text(encoding="utf-8"))
            market_key = next(key for key in history_payload["markets"] if "selection=over" in key)
            history = history_payload["markets"][market_key]["history"]
            self.assertEqual(len(history), 3)
            for older_entry in history[:-1]:
                self.assertNotIn("row", older_entry)
                self.assertNotIn("normalized", older_entry)
            latest_entry = history[-1]
            self.assertIn("row", latest_entry)
            self.assertIn("normalized", latest_entry)
            # Stripping row/normalized must not touch the compact fields
            # every reader actually uses (movement tracking, the board's
            # "Move" column, steam detection's previous_line/previous_odds).
            for entry in history:
                self.assertIn("current_line", entry)
                self.assertIn("market_id", entry)
                self.assertIn("timestamp", entry)

    def test_history_sweep_strips_pre_existing_bloat_on_a_market_not_touched_this_cycle(self) -> None:
        # #112 correction: an append-time-only version of the strip above
        # shipped first and did NOT stop KeyValuePayloadTooLarge recurring
        # in production (confirmed live 2026-07-28, one cycle post-deploy).
        # The real shard was 18.9MB accumulated over a full day; a market
        # that doesn't get a fresh append THIS cycle (dedupe short-circuit,
        # or simply no candidate row for it this pass) never re-enters the
        # per-row branch that strip lived in, so its old, already-bloated
        # entries are never revisited. Seeding a market with pre-existing
        # multi-entry, un-stripped history directly (simulating data
        # written before this fix existed) and running one more cycle for a
        # DIFFERENT market proves the shard-wide sweep -- which runs over
        # every market in the shard whenever the shard gets written at all,
        # not just the ones with a fresh entry this cycle -- actually
        # cleans up pre-existing bloat, not just newly-written entries.
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports"), "SYNDICATE_ODDS_EVENTS_ROOT": str(Path(tmpdir) / "odds_events")}, clear=False):
            root = Path(tmpdir)
            team_root = root / "data" / "odds" / "team" / "date=2026-06-07"
            team_root.mkdir(parents=True)
            (team_root / "oddsapi.csv").write_text(
                "home_team,away_team,bookmaker,market,selection,line,price\nHome,Away,draftkings,total,over,6.5,-110\n",
                encoding="utf-8",
            )
            result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
            self.assertTrue(result["ok"])

            history_path = root / "tracking" / "odds_history" / "2026-06-07.json"
            history_payload = json.loads(history_path.read_text(encoding="utf-8"))
            # Directly inject a second, pre-existing market with 3 fully
            # populated (un-stripped) history entries -- as if it had been
            # written by pre-#112 code earlier in the day and hasn't been
            # touched since.
            bloated_key = "home_team=quiet|away_team=team|market=total|selection=over|bookmaker=draftkings"
            history_payload["markets"][bloated_key] = {
                "last_line": 3.5,
                "history": [
                    {"current_line": 3.5, "market_id": bloated_key, "timestamp": f"2026-06-07T12:0{i}:00+00:00", "row": {"bulk": "x" * 200}, "normalized": {"bulk": "y" * 200}}
                    for i in range(3)
                ],
            }
            history_path.write_text(json.dumps(history_payload), encoding="utf-8")
            # The shared-store copy is what _load_shard_existing_markets
            # actually reads back on the next cycle (checked before the
            # local tracking-root copy) -- both must carry the seeded data.
            shared_path = root / "reports" / "odds_control_plane" / "odds_history" / "nhl" / "2026-06-07.json"
            shared_path.parent.mkdir(parents=True, exist_ok=True)
            shared_path.write_text(json.dumps(history_payload), encoding="utf-8")

            # A second cycle where ONLY the original market changes -- the
            # bloated market gets no candidate row at all this pass.
            (team_root / "oddsapi.csv").write_text(
                "home_team,away_team,bookmaker,market,selection,line,price\nHome,Away,draftkings,total,over,7.0,-110\n",
                encoding="utf-8",
            )
            result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
            self.assertTrue(result["ok"])

            history_payload = json.loads(history_path.read_text(encoding="utf-8"))
            bloated_history = history_payload["markets"][bloated_key]["history"]
            self.assertEqual(len(bloated_history), 3, "the sweep must not drop or add entries, only strip fields")
            for older_entry in bloated_history[:-1]:
                self.assertNotIn("row", older_entry)
                self.assertNotIn("normalized", older_entry)
            self.assertIn("row", bloated_history[-1])
            self.assertIn("normalized", bloated_history[-1])

    def test_history_sweep_trims_entry_count_on_a_quiet_market_too(self) -> None:
        # #112 correction 3, same shape of gap as the field-strip sweep
        # above but on the OTHER dimension: history[-_ODDS_HISTORY_LIMIT:]
        # also only ever ran in the per-row append branch, so a quiet
        # market sitting on more entries than the current limit (e.g. from
        # before _ODDS_HISTORY_LIMIT was cut 50->20) would get its fields
        # stripped by the sweep above but never get trimmed DOWN in count.
        # Confirmed live 2026-07-28: KeyValuePayloadTooLarge recurred on a
        # cycle that ran after both the field-strip sweep and the limit
        # cut were deployed and confirmed live -- this was the remaining
        # gap. Seeds a market with more entries than the (patched, lower)
        # limit and confirms the count itself drops on a cycle where that
        # market gets no candidate row at all.
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports"), "SYNDICATE_ODDS_EVENTS_ROOT": str(Path(tmpdir) / "odds_events")}, clear=False):
            from syndicate.features.shared import odds_refresh_tracking as tracking

            with patch.object(tracking, "_ODDS_HISTORY_LIMIT", 3):
                root = Path(tmpdir)
                team_root = root / "data" / "odds" / "team" / "date=2026-06-07"
                team_root.mkdir(parents=True)
                (team_root / "oddsapi.csv").write_text(
                    "home_team,away_team,bookmaker,market,selection,line,price\nHome,Away,draftkings,total,over,6.5,-110\n",
                    encoding="utf-8",
                )
                result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
                self.assertTrue(result["ok"])

                history_path = root / "tracking" / "odds_history" / "2026-06-07.json"
                history_payload = json.loads(history_path.read_text(encoding="utf-8"))
                # Inject a pre-existing market with MORE entries than the
                # patched limit of 3, as if written before the limit was
                # ever cut this low.
                overlong_key = "home_team=quiet|away_team=team|market=total|selection=over|bookmaker=draftkings"
                history_payload["markets"][overlong_key] = {
                    "last_line": 3.5,
                    "history": [
                        {"current_line": 3.5, "market_id": overlong_key, "timestamp": f"2026-06-07T12:0{i}:00+00:00", "row": {"bulk": "x"}, "normalized": {"bulk": "y"}}
                        for i in range(6)
                    ],
                }
                history_path.write_text(json.dumps(history_payload), encoding="utf-8")
                shared_path = root / "reports" / "odds_control_plane" / "odds_history" / "nhl" / "2026-06-07.json"
                shared_path.parent.mkdir(parents=True, exist_ok=True)
                shared_path.write_text(json.dumps(history_payload), encoding="utf-8")

                (team_root / "oddsapi.csv").write_text(
                    "home_team,away_team,bookmaker,market,selection,line,price\nHome,Away,draftkings,total,over,7.0,-110\n",
                    encoding="utf-8",
                )
                result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
                self.assertTrue(result["ok"])

                history_payload = json.loads(history_path.read_text(encoding="utf-8"))
                overlong_history = history_payload["markets"][overlong_key]["history"]
                self.assertEqual(len(overlong_history), 3, "count must drop to the current limit even though this market got no fresh row")
                self.assertIn("row", overlong_history[-1])
                for older_entry in overlong_history[:-1]:
                    self.assertNotIn("row", older_entry)

    def test_history_sweep_evicts_a_market_no_longer_touched_in_a_day(self) -> None:
        # #112 follow-up (breadth, not depth). Depth bounding (the two tests
        # above) caps how much history one market carries, but nothing
        # capped how many DISTINCT markets a shard could accumulate --
        # confirmed live 2026-07-28: MLB's shard grew from 21.6MB (3,452
        # markets) to 51.1MB (3,713 markets) over ~2 hours even with depth
        # bounding deployed and working, because a market is never removed
        # once created, whether or not its game is still relevant. A market
        # untouched well past the staleness ceiling should be evicted
        # outright; a market touched recently (even if quiet -- no new row
        # this cycle) must survive.
        from datetime import datetime, timedelta, timezone

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports"), "SYNDICATE_ODDS_EVENTS_ROOT": str(Path(tmpdir) / "odds_events")}, clear=False):
            root = Path(tmpdir)
            team_root = root / "data" / "odds" / "team" / "date=2026-06-07"
            team_root.mkdir(parents=True)
            (team_root / "oddsapi.csv").write_text(
                "home_team,away_team,bookmaker,market,selection,line,price\nHome,Away,draftkings,total,over,6.5,-110\n",
                encoding="utf-8",
            )
            result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
            self.assertTrue(result["ok"])

            history_path = root / "tracking" / "odds_history" / "2026-06-07.json"
            history_payload = json.loads(history_path.read_text(encoding="utf-8"))

            stale_key = "home_team=long gone|away_team=team|market=total|selection=over|bookmaker=draftkings"
            history_payload["markets"][stale_key] = {
                "last_line": 3.5,
                "last_updated": "2020-01-01T00:00:00+00:00",
                "history": [{"current_line": 3.5, "market_id": stale_key, "timestamp": "2020-01-01T00:00:00+00:00"}],
            }
            fresh_key = "home_team=still relevant|away_team=team|market=total|selection=over|bookmaker=draftkings"
            fresh_now = datetime.now(timezone.utc).isoformat()
            history_payload["markets"][fresh_key] = {
                "last_line": 4.5,
                "last_updated": fresh_now,
                "history": [{"current_line": 4.5, "market_id": fresh_key, "timestamp": fresh_now}],
            }
            history_path.write_text(json.dumps(history_payload), encoding="utf-8")
            shared_path = root / "reports" / "odds_control_plane" / "odds_history" / "nhl" / "2026-06-07.json"
            shared_path.parent.mkdir(parents=True, exist_ok=True)
            shared_path.write_text(json.dumps(history_payload), encoding="utf-8")

            (team_root / "oddsapi.csv").write_text(
                "home_team,away_team,bookmaker,market,selection,line,price\nHome,Away,draftkings,total,over,7.0,-110\n",
                encoding="utf-8",
            )
            result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
            self.assertTrue(result["ok"])

            history_payload = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertNotIn(stale_key, history_payload["markets"], "a market untouched for years must be evicted")
            self.assertIn(fresh_key, history_payload["markets"], "a market touched moments ago must survive even though it got no new row this cycle")

    def test_sync_nhl_tracking_appends_when_odds_change_without_line_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports"), "SYNDICATE_ODDS_EVENTS_ROOT": str(Path(tmpdir) / "odds_events")}, clear=False):
            root = Path(tmpdir)
            props_root = root / "data" / "props" / "player_props_lines" / "date=2026-06-07"
            props_root.mkdir(parents=True)
            (props_root / "oddsapi.csv").write_text(
                "player_name,market,book,line,over_price,last_seen_at\n"
                "Player One,POINTS,draftkings,2.5,-110,2026-06-07T12:00:00Z\n",
                encoding="utf-8",
            )

            first_result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
            self.assertTrue(first_result["ok"])

            (props_root / "oddsapi.csv").write_text(
                "player_name,market,book,line,over_price,last_seen_at\n"
                "Player One,POINTS,draftkings,2.5,-105,2026-06-07T12:05:00Z\n",
                encoding="utf-8",
            )

            second_result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")

            self.assertTrue(second_result["ok"])
            self.assertEqual(second_result["artifacts"]["odds_history"]["entries_appended"], 1)
            history_payload = json.loads((root / "tracking" / "odds_history" / "2026-06-07.json").read_text(encoding="utf-8"))
            # Props rows have no selection column, so the market key is built
            # only from the identity fields present on the row.
            market_key = "player_name=Player One|market=POINTS|book=draftkings"
            self.assertIn(market_key, history_payload["markets"])
            market_state = history_payload["markets"][market_key]
            self.assertEqual(len(market_state["history"]), 2)
            self.assertEqual(market_state["history"][0]["current_line"], market_state["history"][1]["current_line"])
            self.assertNotEqual(market_state["history"][0]["last_odds"], market_state["history"][1]["last_odds"])

    def test_sync_nhl_tracking_appends_when_refresh_timestamp_changes_without_market_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports"), "SYNDICATE_ODDS_EVENTS_ROOT": str(Path(tmpdir) / "odds_events")}, clear=False):
            root = Path(tmpdir)
            props_root = root / "data" / "props" / "player_props_lines" / "date=2026-06-07"
            props_root.mkdir(parents=True)
            csv_path = props_root / "oddsapi.csv"
            csv_path.write_text(
                "player_name,market,book,line,over_price,last_seen_at\n"
                "Player One,POINTS,draftkings,2.5,-110,2026-06-07T12:00:00Z\n",
                encoding="utf-8",
            )

            first_result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
            self.assertTrue(first_result["ok"])

            csv_path.write_text(
                "player_name,market,book,line,over_price,last_seen_at\n"
                "Player One,POINTS,draftkings,2.5,-110,2026-06-07T12:05:00Z\n",
                encoding="utf-8",
            )

            second_result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")

            self.assertTrue(second_result["ok"])
            self.assertEqual(second_result["artifacts"]["odds_history"]["entries_appended"], 1)
            history_payload = json.loads((root / "tracking" / "odds_history" / "2026-06-07.json").read_text(encoding="utf-8"))
            market_key = "player_name=Player One|market=POINTS|book=draftkings"
            self.assertIn(market_key, history_payload["markets"])
            market_state = history_payload["markets"][market_key]
            self.assertEqual(len(market_state["history"]), 2)
            self.assertEqual(market_state["history"][0]["current_line"], market_state["history"][1]["current_line"])
            self.assertEqual(market_state["history"][0]["last_odds"], market_state["history"][1]["last_odds"])
            self.assertNotEqual(market_state["history"][0]["snapshot_ts"], market_state["history"][1]["snapshot_ts"])

    def test_sync_nhl_tracking_stamps_closing_line_once_on_first_live_observation(self) -> None:
        # The real closing line/price must be captured the moment a market
        # is first observed live -- using the value from the tick BEFORE
        # (previous_line/previous_odds), not the in-play number itself -- and
        # then never overwritten by later live ticks, even though
        # seen_live_market_keys is rebuilt empty on every call to
        # sync_post_refresh_tracking_for_source_root (so it cannot alone
        # prove "first observation ever" the way the guard on
        # market_state["closing_line"] does).
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports"), "SYNDICATE_ODDS_EVENTS_ROOT": str(Path(tmpdir) / "odds_events")}, clear=False):
            root = Path(tmpdir)
            props_root = root / "data" / "props" / "player_props_lines" / "date=2026-06-07"
            props_root.mkdir(parents=True)
            csv_path = props_root / "oddsapi.csv"

            csv_path.write_text(
                "player_name,market,book,line,over_price,status,last_seen_at\n"
                "Player One,POINTS,draftkings,2.5,-110,scheduled,2026-06-07T12:00:00Z\n",
                encoding="utf-8",
            )
            pregame_result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
            self.assertTrue(pregame_result["ok"])

            csv_path.write_text(
                "player_name,market,book,line,over_price,status,last_seen_at\n"
                "Player One,POINTS,draftkings,3.5,-120,live,2026-06-07T19:05:00Z\n",
                encoding="utf-8",
            )
            live_result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
            self.assertTrue(live_result["ok"])

            market_key = "player_name=Player One|market=POINTS|book=draftkings"
            history_payload = json.loads((root / "tracking" / "odds_history" / "2026-06-07.json").read_text(encoding="utf-8"))
            market_state = history_payload["markets"][market_key]
            self.assertEqual(market_state["closing_line"], 2.5)
            self.assertEqual(market_state["closing_price"], -110.0)
            self.assertEqual(market_state["last_line"], 3.5)

            # A second live tick with a further-moved line must not disturb
            # the already-stamped closing snapshot.
            csv_path.write_text(
                "player_name,market,book,line,over_price,status,last_seen_at\n"
                "Player One,POINTS,draftkings,4.5,-130,live,2026-06-07T19:10:00Z\n",
                encoding="utf-8",
            )
            second_live_result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
            self.assertTrue(second_live_result["ok"])
            history_payload = json.loads((root / "tracking" / "odds_history" / "2026-06-07.json").read_text(encoding="utf-8"))
            market_state = history_payload["markets"][market_key]
            self.assertEqual(market_state["closing_line"], 2.5)
            self.assertEqual(market_state["closing_price"], -110.0)
            self.assertEqual(market_state["last_line"], 4.5)

    def test_sync_nfl_tracking_reads_source_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            artifact_root = root / "source_artifacts"
            artifact_root.mkdir(parents=True)
            (artifact_root / "current_week.json").write_text(json.dumps({"season": 2026, "week": 1}), encoding="utf-8")
            (artifact_root / "oddsapi_player_props_2026_wk1.csv").write_text(
                "player,market,book,line,over_price\n"
                "Player Two,Passing Yards,draftkings,250.5,-115\n",
                encoding="utf-8",
            )
            (artifact_root / "real_betting_lines_2026_06_07.json").write_text(
                json.dumps(
                    {
                        "fetched_at": "2026-06-07T12:00:00Z",
                        "lines": {
                            "Away @ Home": {
                                "moneyline": {"home": -150, "away": 130},
                                "total_runs": {"line": 44.5, "over": -110, "under": -110},
                                "run_line": {"home": -3.5},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="nfl", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            self.assertIn("player_props", result["artifacts"])
            self.assertTrue((root / "tracking" / "odds_nfl_player_props_opening_2026_wk1.csv").exists())
            team_opening_path = Path(result["artifacts"]["team_odds"]["opening_path"])
            self.assertTrue(team_opening_path.exists())

    def test_sync_mlb_tracking_writes_snapshot_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            snapshot_root = root / "source_artifacts" / "data" / "daily" / "snapshots" / "2026-06-07"
            snapshot_root.mkdir(parents=True)
            (snapshot_root / "oddsapi_game_lines_2026_06_07.json").write_text(
                json.dumps(
                    {
                        "retrieved_at": "2026-06-07T12:00:00Z",
                        "games": [
                            {
                                "away_team": "Away",
                                "home_team": "Home",
                                "bookmaker": "draftkings",
                                "markets": {
                                    "h2h": {"home_odds": "-140", "away_odds": "+120"},
                                    "spreads": {"home_line": -1.5, "home_odds": "+120"},
                                    "totals": {"line": 8.5, "over_odds": "-110"},
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (snapshot_root / "oddsapi_hitter_props_2026_06_07.json").write_text(
                json.dumps(
                    {
                        "retrieved_at": "2026-06-07T12:00:00Z",
                        "hitter_props": {"Player Three": {"batter_hits": {"line": 0.5, "over_odds": "+120", "under_odds": "-140"}}},
                    }
                ),
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="mlb", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            self.assertIn("game_lines", result["artifacts"])
            self.assertIn("hitter_props", result["artifacts"])
            self.assertTrue((root / "tracking" / "odds_mlb_game_lines_opening_2026-06-07.csv").exists())

    def test_sync_mlb_tracking_writes_prop_odds_history_entries(self) -> None:
        # 2026-07-24 fix: oddsapi_hitter_props/oddsapi_pitcher_props are
        # nested two levels deep (player_name -> market_name -> {line,
        # over_odds, under_odds}) -- the generic odds-history row reader
        # only understands one level of dynamic nesting, so these files were
        # being scanned but silently produced zero rows, leaving MLB player
        # props with no odds-history/movement tracking at all despite the
        # CSV-based props tracking (asserted below, already worked) reading
        # the exact same file correctly via _flatten_mlb_props.
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            snapshot_root = root / "source_artifacts" / "data" / "daily" / "snapshots" / "2026-06-07"
            snapshot_root.mkdir(parents=True)
            (snapshot_root / "oddsapi_game_lines_2026_06_07.json").write_text(
                json.dumps({"retrieved_at": "2026-06-07T12:00:00Z", "games": []}), encoding="utf-8"
            )
            (snapshot_root / "oddsapi_pitcher_props_2026_06_07.json").write_text(
                json.dumps(
                    {
                        "retrieved_at": "2026-06-07T12:00:00Z",
                        "pitcher_props": {
                            "shane drohan": {
                                "strikeouts": {"line": 5.5, "over_odds": "-125", "under_odds": "-102"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="mlb", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            self.assertEqual(result["artifacts"]["odds_history"]["markets_tracked"], 2)

            history_path = root / "tracking" / "odds_history" / "2026-06-07.json"
            payload = json.loads(history_path.read_text(encoding="utf-8"))
            markets = payload["markets"]
            prop_key = next(
                (key for key in markets if "player_name=shane drohan" in key and "market=strikeouts" in key and "selection=over" in key),
                None,
            )
            self.assertIsNotNone(prop_key, f"no prop market key found among {list(markets)}")
            self.assertEqual(markets[prop_key]["last_line"], 5.5)

    def test_sync_mlb_tracking_shards_by_commence_time_not_invocation_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            snapshot_root = root / "source_artifacts" / "data" / "daily" / "snapshots" / "2026-06-07"
            snapshot_root.mkdir(parents=True)
            (snapshot_root / "oddsapi_game_lines_2026_06_07.json").write_text(
                json.dumps(
                    {
                        "retrieved_at": "2026-06-07T12:00:00Z",
                        "games": [
                            {
                                "away_team": "Away",
                                "home_team": "Home",
                                "bookmaker": "draftkings",
                                "commence_time": "2026-06-07T23:00:00Z",
                                "markets": {
                                    "h2h": {"home_odds": "-140", "away_odds": "+120"},
                                },
                            },
                            {
                                "away_team": "Away2",
                                "home_team": "Home2",
                                "bookmaker": "draftkings",
                                "commence_time": "2026-06-08T00:30:00Z",
                                "markets": {
                                    "h2h": {"home_odds": "-130", "away_odds": "+110"},
                                },
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="mlb", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            shards = result["artifacts"]["odds_history"]["shards"]
            self.assertEqual(sorted(shards.keys()), ["2026-06-07", "2026-06-08"])

            today_path = root / "tracking" / "odds_history" / "2026-06-07.json"
            tomorrow_path = root / "tracking" / "odds_history" / "2026-06-08.json"
            self.assertTrue(today_path.exists())
            self.assertTrue(tomorrow_path.exists())

            today_payload = json.loads(today_path.read_text(encoding="utf-8"))
            tomorrow_payload = json.loads(tomorrow_path.read_text(encoding="utf-8"))
            today_key = next(key for key in today_payload["markets"] if "home_team=Home|" in key)
            tomorrow_key = next(key for key in tomorrow_payload["markets"] if "home_team=Home2|" in key)
            self.assertNotIn(tomorrow_key, today_payload["markets"])
            self.assertNotIn(today_key, tomorrow_payload["markets"])

    def test_sync_ncaab_tracking_writes_team_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            odds_root = root / "raw_outputs" / "by_date" / "2026-06-07"
            odds_root.mkdir(parents=True)
            (odds_root / "odds_2026-06-07.csv").write_text(
                "home_team,away_team,bookmaker,market,point,price\n"
                "Home,Away,draftkings,h2h,,-140\n",
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="ncaab", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            opening_path = Path(result["artifacts"]["team_odds"]["opening_path"])
            self.assertTrue(opening_path.exists())

    def test_sync_ncaaf_tracking_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            artifact_root = root / "source_artifacts"
            artifact_root.mkdir(parents=True)
            (artifact_root / "college_football_schedule_2025_predicted_totals_enhanced_20251123T161637Z.csv").write_text(
                "season,week,home_team,away_team\n2025,1,Home,Away\n",
                encoding="utf-8",
            )
            summary_root = artifact_root / "recommendations_summary"
            summary_root.mkdir(parents=True)
            (summary_root / "summary.json").write_text("{}", encoding="utf-8")

            result = sync_post_refresh_tracking_for_source_root(sport="ncaaf", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            manifest_path = Path(result["artifacts"]["source_manifest"]["manifest_path"])
            self.assertTrue(manifest_path.exists())

    def test_sync_soccer_tracking_writes_odds_history_across_leagues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            mls_odds_root = root / "mls" / "api" / "odds"
            mls_odds_root.mkdir(parents=True)
            (mls_odds_root / "game_odds_current.csv").write_text(
                "league,event_id,home_team,away_team,commence_time,market,side,line,price,book\n"
                "mls,1,Columbus Crew,New York City FC,2026-06-07T23:30:00Z,h2h,home,,210,fanduel\n"
                "mls,1,Columbus Crew,New York City FC,2026-06-07T23:30:00Z,h2h,draw,,260,fanduel\n",
                encoding="utf-8",
            )
            mls_props_root = root / "mls" / "props"
            mls_props_root.mkdir(parents=True)
            (mls_props_root / "2026-06-07.csv").write_text(
                "league,player,market,market_key,line,over_price,under_price,book,event,event_id,game_time,home_team,away_team\n"
                "mls,Diego Rossi,Anytime Goalscorer,player_goal_scorer_anytime,,250,,betmgm,x,1,2026-06-07T23:30:00Z,Columbus Crew,New York City FC\n",
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="soccer", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            self.assertFalse(result["artifacts"]["game_odds"].get("skipped", True))
            self.assertFalse(result["artifacts"]["player_props"].get("skipped", True))
            shared_history_path = Path(result["artifacts"]["odds_history"]["shared_history_path"])
            self.assertTrue(shared_history_path.exists())
            history_payload = json.loads(shared_history_path.read_text(encoding="utf-8"))
            market_key = "event_id=1|home_team=Columbus Crew|away_team=New York City FC|market=h2h|side=home|book=fanduel"
            self.assertIn(market_key, history_payload["markets"])
            self.assertEqual(history_payload["markets"][market_key]["last_line"], 210.0)

    def test_sync_soccer_tracking_with_no_files_is_a_graceful_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")}, clear=False):
            root = Path(tmpdir)
            result = sync_post_refresh_tracking_for_source_root(sport="soccer", source_root=root, date_str="2026-06-07")
            self.assertTrue(result["ok"])
            self.assertTrue(result["artifacts"]["game_odds"].get("skipped"))
            self.assertTrue(result["artifacts"]["player_props"].get("skipped"))

    def test_refresh_impacted_recommendations_updates_only_matching_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            processed_root = root / "data" / "processed"
            tracking_root = root / "tracking"
            processed_root.mkdir(parents=True)
            tracking_root.mkdir(parents=True)

            signals_path = tracking_root / "odds_nba_player_props_movement_signals_2026-06-07.csv"
            signals_path.write_text(
                "event_id,player_name,market,selection,line_move,implied_move\n"
                "game-1,Player One,points,Over 28.5,0.8,0.03\n",
                encoding="utf-8",
            )
            recommendation_path = processed_root / "recommendations_slate_2026-06-07.json"
            recommendation_path.write_text(
                json.dumps(
                    {
                        "data": [
                            {
                                "event_id": "game-1",
                                "sport": "nba",
                                "market": "points",
                                "selection": "Over 28.5",
                                "score": 86.0,
                                "simulation": {"probability_distributions": {"win": 0.64, "loss": 0.36}},
                            },
                            {
                                "event_id": "game-2",
                                "sport": "nba",
                                "market": "moneyline",
                                "selection": "Home",
                                "score": 81.0,
                                "model_probability": 0.52,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = refresh_impacted_recommendations_for_tracking(
                sport="nba",
                source_root=root,
                date_str="2026-06-07",
                tracking_meta={"signals_path": str(signals_path)},
            )

            payload = json.loads(recommendation_path.read_text(encoding="utf-8"))
            rows = payload["data"]

            self.assertTrue(result["ok"])
            self.assertEqual(result["files_updated"], 1)
            self.assertEqual(result["rows_updated"], 1)
            self.assertEqual(rows[0]["model_probability"], 0.64)
            self.assertEqual(rows[1]["model_probability"], 0.52)
            self.assertIn("lightweight_refresh", payload)

    def test_sync_tracking_appends_lifecycle_events_incrementally(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            lifecycle_root = root / "odds_events"
            team_root = root / "data" / "odds" / "team" / "date=2026-06-07"
            team_root.mkdir(parents=True)
            (team_root / "oddsapi.csv").write_text(
                "home_team,away_team,bookmaker,market,selection,line,price\n"
                "Home,Away,draftkings,total,over,6.5,-110\n",
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"SYNDICATE_ODDS_EVENTS_ROOT": str(lifecycle_root), "SYNDICATE_REPORTS_ROOT": str(root / "reports")}, clear=False):
                first = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")

                (team_root / "oddsapi.csv").write_text(
                    "home_team,away_team,bookmaker,market,selection,line,price\n"
                    "Home,Away,draftkings,total,over,7.0,-110\n",
                    encoding="utf-8",
                )

                second = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")
                events = load_odds_lifecycle_events("2026-06-07")

            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertGreaterEqual(len(events), 2)
            self.assertEqual(events[0]["event_type"], "open")
            self.assertEqual(events[-1]["event_type"], "update")
            self.assertEqual(events[-1]["line"], 7.0)
            self.assertEqual(events[-1]["sport"], "nhl")

    def test_odds_history_sync_never_touches_keyvalue_and_reaches_disk_directly(self) -> None:
        # Superseded architecture, per explicit user direction 2026-07-28
        # ("the file size limit is frankly unrealistic from keyvalue - we
        # need this to be artifact written/artifact read based"):
        # odds_history writes used to go through the keyvalue store (with a
        # #43/#108-style fallback to a published artifact only when
        # oversized) -- this test used to prove a fake keyvalue client
        # actually received the write. Now odds_history skips keyvalue
        # entirely, always: the shard is routinely tens of MB on a real
        # slate (measured live: 51.1MB for one MLB day), so keyvalue's 8MB
        # ceiling was never a fit for this data type at all. This confirms
        # the new contract: even with a keyvalue backend configured and
        # reachable, odds_history writes go straight to local disk (and
        # attempt publish_hot_artifact for cross-service reach) without
        # ever calling into the keyvalue client.
        fake_client = _FakeKeyValueClient()
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            "os.environ",
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports"),
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
            },
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            root = Path(tmpdir)
            team_root = root / "data" / "odds" / "team" / "date=2026-06-07"
            team_root.mkdir(parents=True)
            (team_root / "oddsapi.csv").write_text(
                "home_team,away_team,bookmaker,market,selection,line,price\n"
                "Home,Away,draftkings,total,over,6.5,-110\n",
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            shared_history_path = Path(result["artifacts"]["odds_history"]["shared_history_path"])

            # No keyvalue call at all -- not even attempted, let alone
            # falling back from a rejection.
            self.assertEqual(fake_client.store, {}, "odds_history must never write through the keyvalue client")
            self.assertTrue(shared_history_path.is_file(), "expected a direct local-disk write regardless of the keyvalue backend being configured")
            payload = json.loads(shared_history_path.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("sport"), "nhl")
            self.assertIn("markets", payload)

    def test_history_sync_writes_the_artifact_and_the_board_reads_it_back(self) -> None:
        # #112, superseded shape: this test used to force a 1-byte keyvalue
        # ceiling to PROVE the artifact-publish fallback (not the primary
        # keyvalue path) was what got exercised. Now that odds_history
        # never attempts keyvalue at all (see
        # test_odds_history_sync_never_touches_keyvalue_and_reaches_disk_directly),
        # there is no "fallback" left to force -- this keeps only what's
        # still meaningful: the write lands on local disk, AND the
        # board-facing reader (odds_control_plane.load_odds_history_payload_for_sport,
        # the one the live board actually calls) sees it on the very next
        # read, not just that the write survives.
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            "os.environ",
            {"SYNDICATE_REPORTS_ROOT": str(Path(tmpdir) / "reports")},
            clear=False,
        ):
            root = Path(tmpdir)
            team_root = root / "data" / "odds" / "team" / "date=2026-06-07"
            team_root.mkdir(parents=True)
            (team_root / "oddsapi.csv").write_text(
                "home_team,away_team,bookmaker,market,selection,line,price\n"
                "Home,Away,draftkings,total,over,6.5,-110\n",
                encoding="utf-8",
            )

            result = sync_post_refresh_tracking_for_source_root(sport="nhl", source_root=root, date_str="2026-06-07")

            self.assertTrue(result["ok"])
            history_path = Path(result["artifacts"]["odds_history"]["history_path"])
            self.assertTrue(history_path.exists(), "expected a direct local-disk write")

            from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport

            board_payload = load_odds_history_payload_for_sport("nhl", "2026-06-07")
            self.assertIsInstance(board_payload, dict)
            self.assertIn("markets", board_payload)
            self.assertTrue(board_payload["markets"], "expected the board reader to see the fallback-published markets")

    def test_write_json_writes_atomically(self) -> None:
        # This writes the odds-history artifacts that feed the Betting
        # Board's line-movement/CLV display. Overlapping refresh runs (see
        # docs/fix_notes_log.md) calling this concurrently for the same path
        # with a plain write_text could leave a truncated/corrupt file --
        # the likely cause of the board's "Move" column going blank.
        # Confirms this now routes through the atomic write helper.
        from syndicate.features.shared.odds_refresh_tracking import _write_json

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "odds_history" / "2026-05-22.json"
            captured: dict[str, object] = {}

            def _capture(path: Path, payload: str) -> None:
                captured["path"] = path
                captured["payload"] = payload

            with patch(
                "syndicate.features.shared.odds_refresh_tracking._atomic_write_text",
                side_effect=_capture,
            ):
                _write_json(out_path, {"markets": ["h2h"]})

            self.assertEqual(captured["path"], out_path)
            self.assertIn("h2h", str(captured["payload"]))
            self.assertFalse(out_path.exists())


if __name__ == "__main__":
    unittest.main()

class CapturePhaseTests(unittest.TestCase):
    """#82 Phase 3. Opening/closing lines become lookups, not timestamp
    inference: every lifecycle observation is tagged with the pregame phase it
    was captured in. event_type="open" already marks the opener; CLV's closing
    line is the last observation tagged "closing".
    """

    def _phase(self, *, minutes_to_start, is_live=False):
        from syndicate.features.shared.odds_refresh_tracking import _capture_phase

        observed = "2026-07-27T18:00:00+00:00"
        commence = f"2026-07-27T{18 + (minutes_to_start // 60):02d}:{minutes_to_start % 60:02d}:00+00:00"
        return _capture_phase(commence_time=commence, observed_at=observed, is_live=is_live)

    def test_boundaries_bracket_the_t_window_sweeps(self) -> None:
        # The T-75m sweep must land in "ramp", the T-10m sweep in "closing" --
        # the windows are 80/12 min so scheduler jitter cannot push a sweep's
        # observations into the wrong phase.
        self.assertEqual(self._phase(minutes_to_start=180), "drift")
        self.assertEqual(self._phase(minutes_to_start=75), "ramp")
        self.assertEqual(self._phase(minutes_to_start=10), "closing")

    def test_live_wins_regardless_of_clock(self) -> None:
        self.assertEqual(self._phase(minutes_to_start=75, is_live=True), "live")

    def test_started_games_are_live_even_without_the_flag(self) -> None:
        from syndicate.features.shared.odds_refresh_tracking import _capture_phase

        self.assertEqual(
            _capture_phase(
                commence_time="2026-07-27T17:00:00+00:00",
                observed_at="2026-07-27T18:00:00+00:00",
                is_live=False,
            ),
            "live",
        )

    def test_unknowable_fails_open_to_none_not_a_guess(self) -> None:
        from syndicate.features.shared.odds_refresh_tracking import _capture_phase

        for commence in (None, "", "not-a-date", "2026-07-27T18:00:00"):
            self.assertIsNone(
                _capture_phase(commence_time=commence, observed_at="2026-07-27T18:00:00+00:00", is_live=False),
                commence,
            )

    def test_lifecycle_events_carry_the_tag(self) -> None:
        from syndicate.features.shared.odds_refresh_tracking import _market_lifecycle_event

        event = _market_lifecycle_event(
            row={"commence_time": "2026-07-27T18:05:00+00:00", "event_id": "abc"},
            normalized_entry={},
            event_type="open",
            sport="mlb",
            timestamp="2026-07-27T18:00:00+00:00",
            market_key="mlb:abc:h2h",
            current_line=None,
            current_odds=-110.0,
            is_live=False,
        )
        self.assertEqual(event["capture_phase"], "closing")


class SteamDetectorTests(unittest.TestCase):
    """#83. The market is the best-aggregated news feed available: sharp money
    moves lines before news is actionable, and this pipeline already observes
    every move. Steam = a big move across a SMALL time gap. The actuator is
    deliberately just a flag + bounded record until #62's cheap re-price
    exists -- a false trigger that forced a re-sim would block the board.
    """

    def _signal(self, **overrides):
        from syndicate.features.shared.odds_refresh_tracking import _steam_signal

        kwargs = dict(
            previous_line=8.5,
            current_line=8.5,
            previous_odds=-110.0,
            current_odds=-110.0,
            previous_ts="2026-07-27T18:00:00+00:00",
            observed_ts="2026-07-27T18:10:00+00:00",
            capture_phase="drift",
        )
        kwargs.update(overrides)
        return _steam_signal(**kwargs)

    def test_a_half_point_line_move_in_ten_minutes_is_steam(self) -> None:
        steam = self._signal(current_line=9.0)
        self.assertIsNotNone(steam)
        self.assertEqual(steam["line_delta"], 0.5)
        self.assertEqual(steam["window_seconds"], 600.0)

    def test_the_same_move_across_four_hours_is_drift_not_steam(self) -> None:
        self.assertIsNone(self._signal(current_line=9.0, observed_ts="2026-07-27T22:00:00+00:00"))

    def test_a_fifteen_cent_price_move_is_steam_even_with_the_line_pinned(self) -> None:
        steam = self._signal(current_odds=-125.0)
        self.assertIsNotNone(steam)
        self.assertEqual(steam["odds_delta"], -15.0)

    def test_late_phases_lower_the_price_bar(self) -> None:
        # 12 cents: under the 15-cent drift bar, over the 10-cent late bar.
        # Late money is the most informed money.
        self.assertIsNone(self._signal(current_odds=-122.0, capture_phase="drift"))
        self.assertIsNotNone(self._signal(current_odds=-122.0, capture_phase="closing"))

    def test_small_moves_are_not_steam(self) -> None:
        self.assertIsNone(self._signal(current_line=8.0 + 0.5, previous_line=8.25))
        self.assertIsNone(self._signal(current_odds=-115.0))

    def test_no_prior_observation_fails_open_to_none(self) -> None:
        self.assertIsNone(self._signal(previous_ts=None, current_line=12.0))
        self.assertIsNone(self._signal(previous_ts="garbage", current_line=12.0))

    def test_naive_previous_ts_is_treated_as_utc_not_rejected(self) -> None:
        # Raw odds-fetch snapshots stamp retrieved_at with a naive
        # datetime.utcnow() (no offset) even though the value IS UTC -- the
        # every-other-timestamp-in-this-pipeline convention. Confirmed live
        # 2026-07-27: this silently zeroed out steam detection for every
        # prop-market observation all day despite real qualifying swings,
        # because the old code rejected any naive timestamp outright.
        steam = self._signal(
            current_line=9.0,
            previous_ts="2026-07-27T18:00:00",
            observed_ts="2026-07-27T18:10:00+00:00",
        )
        self.assertIsNotNone(steam)
        self.assertEqual(steam["line_delta"], 0.5)
        self.assertEqual(steam["window_seconds"], 600.0)

    def test_record_is_bounded_and_never_raises(self) -> None:
        import json as _json
        from tempfile import TemporaryDirectory
        from unittest.mock import patch as _patch

        from syndicate.features.shared import odds_refresh_tracking as tracking

        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "steam_events_2026-07-27.json"
            with _patch.object(tracking, "_steam_events_path", return_value=path):
                events = [{"market_id": f"m{i}", "steam": {"line_delta": 1.0}} for i in range(250)]
                tracking._record_steam_events("2026-07-27", events)
                payload = _json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["events"]), tracking._STEAM_EVENTS_KEEP)
        self.assertEqual(payload["events"][-1]["market_id"], "m249")
