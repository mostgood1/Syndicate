from __future__ import annotations

import unittest
from unittest.mock import patch

import syndicate.features.intelligence as intelligence_module
from syndicate.blueprints.intelligence import _refresh_live_columns_from_artifact


ROWS = [
    {"playerName": "Dylan Beavers", "marketLabel": "Hits + Runs + RBIs", "line": 0.5, "actual": 1.0, "liveProjection": 1.6}
]


def _live_candidate(**overrides) -> dict:
    candidate = {
        "sport_slug": "mlb",
        "is_live": True,
        "game_pk": 824805,
        "game_date": "2026-08-04",
        "player_name": "Dylan Beavers",
        "market": "Hits + Runs + RBIs",
        "line": 0.5,
        "actual": "-",
        "live_projection": "-",
    }
    candidate.update(overrides)
    return candidate


class BoardLiveColumnRefreshTests(unittest.TestCase):
    """LIVE PROJ. / LIVE ACTUAL aged at the worker's build cadence.

    Both columns were only ever written during refresh-worker's board build,
    so they were as old as the last build -- minutes -- while the values they
    display change every pitch. Confirmed live 2026-08-05: the board showed
    live_projection on 1 of 9 live MLB props for over 15 minutes while web's
    OWN live-lens artifact was 3 minutes old and carried 329 tracked props
    with real actual/liveProjection for every live game. The numbers were
    already on the box serving the page; nothing read them.

    Refreshing two display fields from an artifact web already holds is the
    "light transformation for display" the runtime split allows. It must
    never become a recompute.
    """

    def test_live_columns_are_refreshed_from_the_artifact(self) -> None:
        payload = {"top_opportunities": [_live_candidate()]}
        with patch.object(intelligence_module, "_mlb_live_lens_prop_rows_for_game", return_value=ROWS):
            _refresh_live_columns_from_artifact(payload)
        self.assertEqual(payload["top_opportunities"][0]["live_projection"], "1.6")
        self.assertEqual(payload["top_opportunities"][0]["actual"], "1.0")

    def test_non_live_candidates_are_left_alone(self) -> None:
        payload = {"top_opportunities": [_live_candidate(is_live=False)]}
        with patch.object(intelligence_module, "_mlb_live_lens_prop_rows_for_game", return_value=ROWS):
            _refresh_live_columns_from_artifact(payload)
        self.assertEqual(payload["top_opportunities"][0]["actual"], "-")

    def test_an_unreadable_artifact_leaves_the_board_intact(self) -> None:
        payload = {"top_opportunities": [_live_candidate()]}
        with patch.object(
            intelligence_module, "_mlb_live_lens_prop_rows_for_game", side_effect=OSError("gone")
        ):
            _refresh_live_columns_from_artifact(payload)
        self.assertEqual(payload["top_opportunities"][0]["actual"], "-")

    def test_every_board_collection_is_covered(self) -> None:
        payload = {
            "top_opportunities": [_live_candidate()],
            "top_live_opportunities": [_live_candidate()],
            "recommendations": [_live_candidate()],
            "by_sport": {"mlb": [_live_candidate()]},
        }
        with patch.object(intelligence_module, "_mlb_live_lens_prop_rows_for_game", return_value=ROWS):
            _refresh_live_columns_from_artifact(payload)
        for key in ("top_opportunities", "top_live_opportunities", "recommendations"):
            self.assertEqual(payload[key][0]["actual"], "1.0", key)
        self.assertEqual(payload["by_sport"]["mlb"][0]["actual"], "1.0")

    def test_the_artifact_is_read_once_per_game_not_once_per_candidate(self) -> None:
        payload = {"top_opportunities": [_live_candidate() for _ in range(25)]}
        with patch.object(
            intelligence_module, "_mlb_live_lens_prop_rows_for_game", return_value=ROWS
        ) as mocked_rows:
            _refresh_live_columns_from_artifact(payload)
        self.assertEqual(mocked_rows.call_count, 1)

    def test_other_sports_are_not_touched(self) -> None:
        payload = {"top_opportunities": [_live_candidate(sport_slug="wnba")]}
        with patch.object(intelligence_module, "_mlb_live_lens_prop_rows_for_game") as mocked_rows:
            _refresh_live_columns_from_artifact(payload)
        mocked_rows.assert_not_called()


if __name__ == "__main__":
    unittest.main()
