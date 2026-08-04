from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features import intelligence
from syndicate.features.intelligence import _build_odds_history_player_index
from syndicate.features.intelligence import _candidate_odds_history_context
from syndicate.features.intelligence import _enrich_candidates_with_odds_history
from syndicate.features.intelligence import _load_odds_history_payload_for_sport
from syndicate.features.intelligence import build_pick_card_view
from syndicate.features.intelligence import score_candidate
from syndicate.features.shared import refresh_state_store


class IntelligenceOddsHistoryTests(unittest.TestCase):
    def test_mlb_odds_history_prefers_shared_control_plane_history(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ",
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ):
            shared_history_path = Path(tmp_dir) / "reports" / "odds_control_plane" / "odds_history" / "mlb" / "2026-07-05.json"
            shared_history_path.parent.mkdir(parents=True, exist_ok=True)
            refresh_state_store.write_json_file(
                shared_history_path,
                {
                    "date": "2026-07-05",
                    "history_limit": 50,
                    "markets": {
                        "home_team=Home|away_team=Away|market=h2h|bookmaker=draftkings": {
                            "last_line": -140.0,
                            "previous_line": -140.0,
                            "delta": 0.0,
                            "movement": "flat",
                            "history": [],
                        }
                    },
                },
            )

            payload = _load_odds_history_payload_for_sport("mlb", "2026-07-05")

        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("date"), "2026-07-05")
        self.assertIn("markets", payload)

    def test_candidate_movement_is_attached_and_rendered(self) -> None:
        candidate = {
            "sport_slug": "nhl",
            "sport": "NHL",
            "matchup": "Away @ Home",
            "market": "Total",
            "pick": "Over 6.5",
            "name": "Away @ Home Over 6.5",
            "line": 7.0,
            "odds": "-110",
            "market_data": {"opening_line": 6.5, "current_line": 7.0, "movement_history": []},
        }
        odds_history = {
            "markets": {
                "matchup=Away @ Home|market=total|selection=over": {
                    "last_line": 7.0,
                    "previous_line": 6.5,
                    "delta": 0.5,
                    "movement": "up",
                    "percent_change": 7.6923076923,
                    "last_updated": "2026-06-11T12:00:00Z",
                    "history": [
                        {"current_line": 6.5, "movement": "flat"},
                        {"current_line": 7.0, "movement": "up"},
                    ],
                }
            }
        }

        enriched = _enrich_candidates_with_odds_history([candidate], {"nhl": odds_history})[0]
        movement_context = _candidate_odds_history_context(enriched, _build_odds_history_player_index(odds_history))
        self.assertEqual(movement_context["trend"], "up")
        self.assertEqual(movement_context["delta"], 0.5)
        self.assertEqual(movement_context["recent_movement_trend"], "up")
        self.assertAlmostEqual(movement_context["percent_change"], 7.6923076923, places=6)
        self.assertEqual(movement_context["last_updated"], "2026-06-11T12:00:00Z")

        self.assertEqual(enriched["movement"]["trend"], "up")
        self.assertEqual(enriched["movement"]["delta"], 0.5)
        self.assertEqual(enriched["movement"]["recent_movement_trend"], "up")
        self.assertAlmostEqual(enriched["movement"]["percent_change"], 7.6923076923, places=6)
        self.assertEqual(enriched["last_updated"], "2026-06-11T12:00:00Z")

        scored = score_candidate(enriched, preferences={})

        self.assertIn("movement", scored)
        self.assertEqual(scored["movement"]["delta"], 0.5)
        self.assertEqual(scored["movement"]["trend"], "up")

        card = build_pick_card_view(scored)
        self.assertEqual(card["movement"]["trend"], "up")
        self.assertEqual(card["movement"]["delta_display"], "+0.5")
        self.assertEqual(card["movement"]["last_updated"], "2026-06-11T12:00:00Z")


if __name__ == "__main__":
    unittest.main()


class OddsHistoryShardWindowTests(unittest.TestCase):
    """Soccer's board spans fixture dates; the reader only ever asked for one.

    odds_history shards by the GAME's date. Daily sports never noticed
    because their fixture date IS the board date. Soccer's is not: confirmed
    live 2026-08-04, soccer had 399 markets under shard 2026-08-02 and 206
    under 2026-08-16 but ZERO under 2026-08-04, so all 18 MLS candidates on
    that board showed no movement. Nothing was wrong with soccer's capture --
    the reader asked the wrong day.
    """

    def test_extra_shards_come_from_the_sports_own_fixture_dates(self) -> None:
        sport = {
            "slug": "soccer",
            "dashboard_games": [
                {"commence_time": "2026-08-08T23:30:00Z"},
                {"commence_time": "2026-08-09T20:00:00Z"},
                # Same fixture date again -- must not add a duplicate shard.
                {"commence_time": "2026-08-09T22:00:00Z"},
            ],
        }
        keys = intelligence._odds_history_shard_keys_for_sport(sport, "soccer", "2026-08-04")
        self.assertEqual(keys[0], "2026-08-04", "primary shard must stay first")
        self.assertIn("2026-08-08", keys)
        self.assertIn("2026-08-09", keys)
        self.assertEqual(len(keys), len(set(keys)))

    def test_a_daily_sport_asks_for_exactly_one_shard(self) -> None:
        # An MLB shard is ~30MB; this must not become "load everything".
        sport = {
            "slug": "mlb",
            "dashboard_games": [
                {"commence_time": "2026-08-04T17:10:00Z"},
                {"commence_time": "2026-08-05T00:40:00Z"},  # 7:40pm Central, same day
            ],
        }
        keys = intelligence._odds_history_shard_keys_for_sport(sport, "mlb", "2026-08-04")
        self.assertEqual(keys, ["2026-08-04"])

    def test_the_extra_shard_count_is_bounded(self) -> None:
        sport = {
            "slug": "soccer",
            "dashboard_games": [{"commence_time": f"2026-09-{day:02d}T20:00:00Z"} for day in range(1, 20)],
        }
        keys = intelligence._odds_history_shard_keys_for_sport(sport, "soccer", "2026-08-04")
        self.assertLessEqual(len(keys), intelligence._MAX_EXTRA_ODDS_HISTORY_SHARDS + 1)

    def test_week_scoped_sports_are_left_alone(self) -> None:
        # nfl/ncaaf shard by a season/week token, not a date.
        sport = {"slug": "nfl", "dashboard_games": [{"commence_time": "2026-09-13T17:00:00Z"}]}
        self.assertEqual(
            intelligence._odds_history_shard_keys_for_sport(sport, "nfl", "2026_wk1"), ["2026_wk1"]
        )

    def test_merging_shards_unions_their_markets(self) -> None:
        merged = intelligence._merge_odds_history_payloads(
            [{"markets": {"a": {"last_line": 1}}}, {"markets": {"b": {"last_line": 2}}}]
        )
        self.assertEqual(sorted(merged["markets"]), ["a", "b"])

    def test_a_later_shard_wins_an_exact_key_collision(self) -> None:
        # Market keys carry event_id/player_name, so a collision is the same
        # market in the same game -- the later shard is the fresher copy.
        merged = intelligence._merge_odds_history_payloads(
            [{"markets": {"a": {"last_line": 1}}}, {"markets": {"a": {"last_line": 2}}}]
        )
        self.assertEqual(merged["markets"]["a"]["last_line"], 2)


class OddsHistoryCandidateDateSupplementTests(unittest.TestCase):
    """The overview-derived shard window was not enough for soccer.

    _odds_history_shard_keys_for_sport widens the window using the
    overview's dashboard_games. Confirmed live 2026-08-04 that soccer's
    overview row carries no per-game dates at all: post-deploy, the
    odds_history_shard_window trace logged ZERO times and soccer still asked
    only for shard 2026-08-04, so all 18 MLS candidates stayed at zero
    movement while their history sat in the 2026-08-02 and 2026-08-16
    shards. The candidates themselves always carry a game date, and are in
    hand at enrichment time -- deriving the shard set from the thing being
    joined works regardless of how a sport shapes its overview row.
    """

    def _loader(self, available: dict[str, dict]):
        def _load(slug: str, shard_key: str):
            return available.get(f"{slug}:{shard_key}")

        return _load

    def test_a_fixture_date_shard_is_loaded_for_soccer(self) -> None:
        candidates = [{"sport_slug": "soccer", "commence_time": "2026-08-16T20:00:00Z"}]
        available = {"soccer:2026-08-16": {"markets": {"soccer:m1": {"history": [{"line": 1}]}}}}
        with patch.object(
            intelligence, "_load_odds_history_payload_for_sport", side_effect=self._loader(available)
        ):
            result = intelligence._supplement_odds_history_from_candidate_dates(
                candidates, {"soccer": {"markets": {}}}
            )
        self.assertIn("soccer:m1", result["soccer"]["markets"])

    def test_existing_markets_are_preserved_not_replaced(self) -> None:
        candidates = [{"sport_slug": "soccer", "commence_time": "2026-08-16T20:00:00Z"}]
        available = {"soccer:2026-08-16": {"markets": {"new": {}}}}
        with patch.object(
            intelligence, "_load_odds_history_payload_for_sport", side_effect=self._loader(available)
        ):
            result = intelligence._supplement_odds_history_from_candidate_dates(
                candidates, {"soccer": {"markets": {"already": {}}}}
            )
        self.assertEqual(sorted(result["soccer"]["markets"]), ["already", "new"])

    def test_a_daily_sport_does_not_reload_the_shard_it_already_holds(self) -> None:
        # An MLB shard is ~30MB and this runs on every board build.
        from syndicate.features.intelligence import central_today_iso

        today = central_today_iso()
        candidates = [{"sport_slug": "mlb", "game_date": today}]
        with patch.object(intelligence, "_load_odds_history_payload_for_sport") as mocked_load:
            intelligence._supplement_odds_history_from_candidate_dates(
                candidates, {"mlb": {"markets": {"already": {}}}}
            )
        mocked_load.assert_not_called()

    def test_week_scoped_sports_are_skipped(self) -> None:
        candidates = [{"sport_slug": "nfl", "commence_time": "2026-09-13T17:00:00Z"}]
        with patch.object(intelligence, "_load_odds_history_payload_for_sport") as mocked_load:
            intelligence._supplement_odds_history_from_candidate_dates(candidates, {})
        mocked_load.assert_not_called()

    def test_the_number_of_supplemental_shards_is_bounded(self) -> None:
        candidates = [
            {"sport_slug": "soccer", "commence_time": f"2026-09-{day:02d}T20:00:00Z"} for day in range(1, 20)
        ]
        with patch.object(intelligence, "_load_odds_history_payload_for_sport", return_value=None) as mocked_load:
            intelligence._supplement_odds_history_from_candidate_dates(candidates, {})
        self.assertLessEqual(mocked_load.call_count, intelligence._MAX_EXTRA_ODDS_HISTORY_SHARDS)
