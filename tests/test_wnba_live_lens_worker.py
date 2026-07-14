from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.wnba import live_lens
from syndicate.features.wnba.live_lens import build_live_lens_snapshot
from syndicate.features.wnba.live_lens import build_live_lens_page_context
from syndicate.features.wnba.live_lens import validate_live_lens_snapshot


class WnbaLiveLensWorkerTests(unittest.TestCase):
    def test_load_live_lens_snapshot_uses_keyvalue_aware_reader(self) -> None:
        # Regression: the background live_lens_loop writes snapshots via
        # refresh_state_store.write_json_file(), which goes to the shared
        # keyvalue store when SYNDICATE_REFRESH_STATE_BACKEND=keyvalue. The
        # read side must use the matching keyvalue-aware read_json_file(),
        # not a plain local-filesystem read, or the loop's writes are
        # invisible to whichever service serves the request.
        snapshot = {"date": "2026-07-13", "rank_cards": [], "cards": [], "games": []}
        with patch.object(live_lens, "read_json_file", return_value=snapshot) as mocked_read:
            result = live_lens._load_live_lens_snapshot()

        self.assertEqual(result, snapshot)
        mocked_read.assert_called_once_with(live_lens.live_lens_snapshot_path())

    def test_snapshot_builder_limits_rank_cards_to_fifty(self) -> None:
        games = []
        for index in range(55):
            games.append(
                {
                    "event_id": f"evt-{index}",
                    "status": "Live",
                    "detail": f"Q{index % 4 + 1} 05:12",
                    "summary": f"Summary {index}",
                    "away": {"abbr": "LAS", "score": index},
                    "home": {"abbr": "NYL", "score": index + 1},
                    "betting": {"total": 150.5},
                    "shared_top_play_rows": [],
                    "shared_prop_rows": [],
                }
            )

        cards_context = {
            "date": "2026-06-19",
            "requested_date": "2026-06-19",
            "games": games,
            "source_path": "wnba_cards.csv",
        }
        live_lines_payload = {"games": [{"event_id": f"evt-{index}", "lines": {"total": 151.5}} for index in range(55)]}

        with patch("syndicate.features.wnba.live_lens.build_cards_page_context", return_value=cards_context), patch(
            "syndicate.features.wnba.live_lens.build_live_lines_payload", return_value=live_lines_payload
        ):
            snapshot = build_live_lens_snapshot("2026-06-19")

        self.assertEqual(len(snapshot.get("rank_cards") or []), 50)
        self.assertEqual(len(snapshot.get("cards") or []), 50)
        self.assertEqual((snapshot.get("api_payload") or {}).get("date"), "2026-06-19")
        self.assertEqual((snapshot.get("api_payload") or {}).get("rank_cards") and len(snapshot["api_payload"]["rank_cards"]), 50)

    def test_snapshot_builder_returns_safe_empty_board_when_cards_are_missing(self) -> None:
        with patch("syndicate.features.wnba.live_lens.build_cards_page_context", side_effect=RuntimeError("boom")):
            snapshot = build_live_lens_snapshot("2026-06-19")

        self.assertEqual(snapshot.get("date"), "2026-06-19")
        self.assertEqual(snapshot.get("rank_cards"), [])
        self.assertEqual(snapshot.get("cards"), [])
        self.assertEqual((snapshot.get("empty_state") or {}).get("eyebrow"), "WNBA live lens")
        self.assertEqual((snapshot.get("api_payload") or {}).get("rank_cards"), [])

    def test_page_context_uses_persisted_snapshot_without_request_path_rebuild(self) -> None:
        stale_snapshot = {
            "date": "2026-06-18",
            "rank_cards": [{"title": "Stale", "metrics": [], "summary": "old"}],
            "games": [],
            "cards": [],
            "source_path": "wnba_live_lens.json",
        }
        fresh_snapshot = {
            "date": "2026-06-21",
            "requested_date": "2026-06-21",
            "rank_cards": [{"title": "Fresh", "metrics": [], "summary": "new"}],
            "games": [{"event_id": "evt-1", "rows": []}],
            "cards": [{"title": "Fresh", "metrics": [], "summary": "new"}],
            "source_path": "wnba_live_lens.json",
        }

        with patch("syndicate.features.wnba.live_lens._load_live_lens_snapshot", return_value=stale_snapshot), patch(
            "syndicate.features.wnba.live_lens.build_live_lens_snapshot", return_value=fresh_snapshot
        ) as mocked_rebuild, patch("syndicate.features.wnba.live_lens.central_today_iso", return_value="2026-06-21"):
            context = build_live_lens_page_context("2026-06-21")

        mocked_rebuild.assert_not_called()
        self.assertEqual(context.get("date"), "2026-06-18")
        self.assertEqual(context.get("requested_date"), "2026-06-21")
        self.assertEqual((context.get("rank_cards") or [{}])[0].get("title"), "Stale")

    def test_snapshot_validator_rejects_nan_values(self) -> None:
        snapshot = {"rank_cards": [{"title": "Bad", "metrics": [{"label": "Score", "value": float("nan")}] }]}
        self.assertFalse(validate_live_lens_snapshot(snapshot))

    def test_snapshot_validator_requires_games_cards_and_date(self) -> None:
        self.assertFalse(validate_live_lens_snapshot({"date": "2026-06-19", "games": [], "rank_cards": []}))
        self.assertFalse(validate_live_lens_snapshot({"games": [], "cards": [], "rank_cards": []}))
        self.assertFalse(validate_live_lens_snapshot({"date": "2026-06-19", "cards": [], "rank_cards": []}))
