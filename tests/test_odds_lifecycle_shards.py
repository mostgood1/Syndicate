from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared.odds_lifecycle import _candidate_market_id
from syndicate.features.shared.odds_lifecycle import _recent_history_rows
from syndicate.features.shared.odds_lifecycle import _resolve_market_state_across_shards
from syndicate.features.shared.odds_lifecycle import build_market_features
from syndicate.features.shared.odds_lifecycle import build_market_history_view


def _write_shard(
    root: Path,
    *,
    sport: str,
    shard_key: str,
    market_id: str,
    history: list[dict],
    closing_line: float | None = None,
    closing_price: float | None = None,
) -> None:
    path = root / "odds_control_plane" / "odds_history" / sport / f"{shard_key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    market_state = {"history": history, "last_line": history[-1]["current_line"] if history else None}
    if closing_line is not None:
        market_state["closing_line"] = closing_line
        market_state["closing_price"] = closing_price
    payload = {
        "schema_version": 1,
        "sport": sport,
        "shard_key": shard_key,
        "markets": {market_id: market_state},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class RecentHistoryRowsFilterTests(unittest.TestCase):
    # Confirmed live 2026-07-29 on the WNBA board: when the odds-history shard
    # lookup misses (as it always does today for WNBA -- a separate,
    # pre-existing key-format mismatch between the write side's descriptive
    # key and _candidate_market_id's own colon-normalized format),
    # build_market_history_view falls through to _recent_history_rows, whose
    # alias chain degrades to a bare event_id/game_id match shared by every
    # candidate in the same game. Without filtering, every player's (and
    # every stat's) "recent history" merged into one shared list, so several
    # different props showed the identical wrong opening/latest line.
    _EVENTS = [
        {"event_id": "GAME1", "game_id": "GAME1", "entity": "Alyssa Thomas", "stat": "ast", "current_line": 8.5, "timestamp": "2026-07-30T00:00:00Z"},
        {"event_id": "GAME1", "game_id": "GAME1", "entity": "Kahleah Copper", "stat": "threes", "current_line": 9.5, "timestamp": "2026-07-30T00:01:00Z"},
        {"event_id": "GAME1", "game_id": "GAME1", "entity": "Kahleah Copper", "stat": "threes", "current_line": 24.5, "timestamp": "2026-07-30T00:02:00Z"},
    ]

    def test_game_level_alias_fallback_filters_by_subject_and_stat(self) -> None:
        with patch("syndicate.features.shared.odds_lifecycle.load_recent_odds_events", return_value=self._EVENTS):
            kahleah = _recent_history_rows(
                {"entity": "Kahleah Copper", "stat": "threes", "sport_slug": "wnba", "game_id": "GAME1", "candidate_type": "prop"},
                sport="wnba",
            )
            alyssa = _recent_history_rows(
                {"entity": "Alyssa Thomas", "stat": "ast", "sport_slug": "wnba", "game_id": "GAME1", "candidate_type": "prop"},
                sport="wnba",
            )

        self.assertEqual([row["current_line"] for row in kahleah], [9.5, 24.5])
        self.assertTrue(all(row["entity"] == "Kahleah Copper" for row in kahleah))
        self.assertEqual([row["current_line"] for row in alyssa], [8.5])
        self.assertTrue(all(row["entity"] == "Alyssa Thomas" for row in alyssa))

    def test_game_level_alias_falls_back_unfiltered_when_candidate_has_no_subject(self) -> None:
        # A game-level candidate (a team ATS/Total pick) genuinely has no
        # player subject -- there's nothing to filter by, so the existing
        # unfiltered game-wide behavior is correct and must be preserved.
        with patch("syndicate.features.shared.odds_lifecycle.load_recent_odds_events", return_value=self._EVENTS):
            rows = _recent_history_rows({"sport_slug": "wnba", "game_id": "GAME1", "candidate_type": "game"}, sport="wnba")
        self.assertEqual(len(rows), 3)

    def test_placeholder_dash_fields_still_extract_subject_from_selection_text(self) -> None:
        # Confirmed live 2026-07-30, right after deploying the fix above:
        # some WNBA prop candidates ("Veronica Burton UNDER 19.5", "Alyssa
        # Thomas UNDER 17.5") carry player="-" (this codebase's own
        # _safe_text default="-" placeholder, a TRUTHY string) with
        # entity/stat both None -- "-" short-circuited the `or` chain before
        # ever reaching the selection-text fallback, so these candidates
        # still fell into the "no subject" unfiltered branch and kept
        # showing the exact cross-candidate collision this whole fix targets.
        candidate = {
            "candidate_type": "prop",
            "player": "-",
            "entity": None,
            "stat": None,
            "market": "PTS+AST",
            "market_type": "PTS+AST",
            "selection": "Veronica Burton UNDER 19.5",
            "sport_slug": "wnba",
            "game_id": "GAME1",
        }
        events = self._EVENTS + [
            {"event_id": "GAME1", "game_id": "GAME1", "selection": "Veronica Burton UNDER 19.5", "market": "PTS+AST", "current_line": 19.5, "timestamp": "2026-07-30T00:03:00Z"},
        ]
        with patch("syndicate.features.shared.odds_lifecycle.load_recent_odds_events", return_value=events):
            rows = _recent_history_rows(candidate, sport="wnba")
        self.assertEqual([row.get("current_line") for row in rows], [19.5])


class OddsLifecycleShardMergeTests(unittest.TestCase):
    def test_resolve_market_state_across_shards_merges_opening_and_closing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")}, clear=False
        ):
            reports_root = Path(tmp_dir) / "reports"
            _write_shard(
                reports_root,
                sport="mlb",
                shard_key="2026-06-07",
                market_id="market-x",
                history=[{"current_line": -3.0, "captured_at": "2026-06-07T10:00:00Z", "event_type": "open"}],
            )
            _write_shard(
                reports_root,
                sport="mlb",
                shard_key="2026-06-08",
                market_id="market-x",
                history=[{"current_line": -3.5, "captured_at": "2026-06-08T18:00:00Z", "event_type": "close"}],
            )

            merged = _resolve_market_state_across_shards(sport="mlb", market_id="market-x", shard_key="2026-06-08", shard_lookback=1)
            self.assertIsNotNone(merged)
            history = merged["history"]
            self.assertEqual(len(history), 2)
            self.assertEqual({entry["event_type"] for entry in history}, {"open", "close"})

            no_lookback = _resolve_market_state_across_shards(sport="mlb", market_id="market-x", shard_key="2026-06-08", shard_lookback=0)
            self.assertEqual(len(no_lookback["history"]), 1)
            self.assertEqual(no_lookback["history"][0]["event_type"], "close")

    def test_build_market_history_view_uses_candidate_date_to_merge_shards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")}, clear=False
        ):
            reports_root = Path(tmp_dir) / "reports"
            candidate = {
                "sport": "mlb",
                "event_id": "Away@Home",
                "market_type": "spread",
                "entity": "Home",
                "line": -3.5,
                "date": "2026-06-08",
            }
            market_id = _candidate_market_id(candidate, sport="mlb")
            self.assertIsNotNone(market_id)

            _write_shard(
                reports_root,
                sport="mlb",
                shard_key="2026-06-07",
                market_id=market_id,
                history=[{"current_line": -3.0, "captured_at": "2026-06-07T10:00:00Z", "event_type": "open"}],
            )
            _write_shard(
                reports_root,
                sport="mlb",
                shard_key="2026-06-08",
                market_id=market_id,
                history=[{"current_line": -3.5, "captured_at": "2026-06-08T18:00:00Z", "event_type": "close"}],
            )

            view = build_market_history_view(candidate, sport="mlb")
            self.assertEqual(view["opening_line"], -3.0)
            self.assertEqual(view["closing_line"], -3.5)
            self.assertEqual(view["history_points"], 2)

            features = build_market_features(candidate, sport="mlb")
            self.assertEqual(features["opening_line"], -3.0)
            self.assertEqual(features["closing_line"], -3.5)

    def test_stamped_closing_line_wins_over_latest_when_history_has_no_event_type(self) -> None:
        # odds_refresh_tracking.py's own market_state.history entries never
        # carry an "event_type" key (only the separate day-based lifecycle
        # log does) -- so the closing_entry scan in build_market_history_view
        # silently falls back to latest_entry for any market resolved via
        # this (normal, preferred) shard path. Confirmed live: this made
        # closing_line a bare alias for the still-moving latest_line for
        # every in-play market. The fix stamps closing_line/closing_price
        # directly onto market_state once, at the real pregame->live
        # transition -- this must win over the (here, non-matching) scan.
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")}, clear=False
        ):
            reports_root = Path(tmp_dir) / "reports"
            candidate = {
                "sport": "mlb",
                "event_id": "Away@Home",
                "market_type": "moneyline",
                "entity": "Home",
                "line": -150.0,
                "date": "2026-06-08",
            }
            market_id = _candidate_market_id(candidate, sport="mlb")
            self.assertIsNotNone(market_id)

            _write_shard(
                reports_root,
                sport="mlb",
                shard_key="2026-06-08",
                market_id=market_id,
                history=[
                    {"current_line": -150.0, "captured_at": "2026-06-08T17:00:00Z"},
                    {"current_line": -180.0, "captured_at": "2026-06-08T20:00:00Z"},
                ],
                closing_line=-150.0,
                closing_price=-150.0,
            )

            view = build_market_history_view(candidate, sport="mlb")
            self.assertEqual(view["latest_line"], -180.0)
            self.assertEqual(view["closing_line"], -150.0)

    def test_price_delta_and_direction_tracked_independently_from_line(self) -> None:
        # 2026-07-24 fix: opening_price/latest_price were already recorded
        # but no delta was ever computed from them -- a line move (3.5 ->
        # 4.5) and an odds/juice move (-110 -> -120) are two independent
        # things a market can do, and callers had no way to report the
        # price side separately from the line side.
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")}, clear=False
        ):
            reports_root = Path(tmp_dir) / "reports"
            candidate = {
                "sport": "mlb",
                "event_id": "Away@Home",
                "market_type": "spread",
                "entity": "Home",
                "line": -3.5,
                "date": "2026-06-08",
            }
            market_id = _candidate_market_id(candidate, sport="mlb")
            _write_shard(
                reports_root,
                sport="mlb",
                shard_key="2026-06-07",
                market_id=market_id,
                history=[{"current_line": -3.5, "odds": -110, "captured_at": "2026-06-07T10:00:00Z", "event_type": "open"}],
            )
            _write_shard(
                reports_root,
                sport="mlb",
                shard_key="2026-06-08",
                market_id=market_id,
                history=[{"current_line": -3.5, "odds": -120, "captured_at": "2026-06-08T18:00:00Z", "event_type": "close"}],
            )

            view = build_market_history_view(candidate, sport="mlb")
            self.assertEqual(view["opening_price"], -110.0)
            self.assertEqual(view["latest_price"], -120.0)
            self.assertEqual(view["price_delta"], -10.0)
            self.assertEqual(view["price_direction"], "negative")
            # The line never moved in this fixture -- must stay flat/zero
            # independent of the price move.
            self.assertEqual(view["movement_delta"], 0.0)
            self.assertEqual(view["movement_direction"], "flat")

    def test_no_history_fallback_still_reports_flat_price_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            "os.environ", {"SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports")}, clear=False
        ):
            candidate = {"sport": "mlb", "line": 3.5, "odds": 106}
            view = build_market_history_view(candidate, sport="mlb")
            self.assertEqual(view["price_delta"], None)
            self.assertEqual(view["price_direction"], "flat")


if __name__ == "__main__":
    unittest.main()
