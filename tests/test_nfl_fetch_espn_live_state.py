"""Coverage for schedule_adapter._fetch_espn_football_live_state -- the NFL
live-lens data layer (todo #119, item 3). Mirrors
tests/test_wnba_sources_has_games_for_date.py's _FakeEspnResponse pattern for
mocking urllib.request.urlopen against a real-shaped ESPN scoreboard payload.
"""

from __future__ import annotations

import json
import unittest
from io import BytesIO
from unittest.mock import patch

from syndicate.features.shared import schedule_adapter


class _FakeEspnResponse:
    def __init__(self, payload: dict) -> None:
        self._buffer = BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self) -> bytes:
        return self._buffer.read()

    def __enter__(self) -> "_FakeEspnResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def _competitor(*, home_away: str, display_name: str, abbreviation: str, score: str) -> dict:
    return {
        "homeAway": home_away,
        "score": score,
        "team": {"displayName": display_name, "abbreviation": abbreviation},
    }


def _event(*, event_id: str, home_score: str, away_score: str, state: str, completed: bool, period, display_clock: str, short_detail: str) -> dict:
    return {
        "id": event_id,
        "date": "2026-09-08T17:00Z",
        "competitions": [
            {
                "date": "2026-09-08T17:00Z",
                "competitors": [
                    _competitor(home_away="home", display_name="Kansas City Chiefs", abbreviation="KC", score=home_score),
                    _competitor(home_away="away", display_name="Baltimore Ravens", abbreviation="BAL", score=away_score),
                ],
            }
        ],
        "status": {
            "period": period,
            "displayClock": display_clock,
            "type": {"state": state, "completed": completed, "shortDetail": short_detail},
        },
    }


class FetchEspnFootballLiveStateTests(unittest.TestCase):
    def test_returns_empty_for_unsupported_sport(self) -> None:
        self.assertEqual(schedule_adapter._fetch_espn_football_live_state("nba", "2026-09-08"), [])

    def test_returns_empty_for_bad_date(self) -> None:
        self.assertEqual(schedule_adapter._fetch_espn_football_live_state("nfl", "not-a-date"), [])

    def test_extracts_live_game_fields(self) -> None:
        payload = {
            "events": [
                _event(
                    event_id="401671801",
                    home_score="17",
                    away_score="14",
                    state="in",
                    completed=False,
                    period=3,
                    display_clock="4:12",
                    short_detail="3rd Quarter - 4:12",
                )
            ]
        }
        with patch.object(schedule_adapter.urllib.request, "urlopen", return_value=_FakeEspnResponse(payload)) as mock_urlopen:
            rows = schedule_adapter._fetch_espn_football_live_state("nfl", "2026-09-08")

        mock_urlopen.assert_called_once()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["event_id"], "401671801")
        self.assertEqual(row["home"], "Kansas City Chiefs")
        self.assertEqual(row["away"], "Baltimore Ravens")
        self.assertEqual(row["home_abbr"], "KC")
        self.assertEqual(row["away_abbr"], "BAL")
        self.assertEqual(row["home_score"], 17.0)
        self.assertEqual(row["away_score"], 14.0)
        self.assertEqual(row["state"], "in")
        self.assertFalse(row["completed"])
        self.assertEqual(row["period"], 3)
        self.assertEqual(row["display_clock"], "4:12")
        self.assertEqual(row["status_detail"], "3rd Quarter - 4:12")

    def test_extracts_not_yet_started_game_fields(self) -> None:
        payload = {
            "events": [
                _event(
                    event_id="401671802",
                    home_score="0",
                    away_score="0",
                    state="pre",
                    completed=False,
                    period=None,
                    display_clock="",
                    short_detail="9/8 - 1:00 PM EDT",
                )
            ]
        }
        with patch.object(schedule_adapter.urllib.request, "urlopen", return_value=_FakeEspnResponse(payload)):
            rows = schedule_adapter._fetch_espn_football_live_state("nfl", "2026-09-08")

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["state"], "pre")
        self.assertFalse(row["completed"])
        self.assertIsNone(row["period"])
        self.assertEqual(row["display_clock"], "")

    def test_extracts_completed_game_fields(self) -> None:
        payload = {
            "events": [
                _event(
                    event_id="401671803",
                    home_score="27",
                    away_score="20",
                    state="post",
                    completed=True,
                    period=4,
                    display_clock="0:00",
                    short_detail="Final",
                )
            ]
        }
        with patch.object(schedule_adapter.urllib.request, "urlopen", return_value=_FakeEspnResponse(payload)):
            rows = schedule_adapter._fetch_espn_football_live_state("nfl", "2026-09-08")

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["state"], "post")
        self.assertTrue(row["completed"])
        self.assertEqual(row["home_score"], 27.0)
        self.assertEqual(row["away_score"], 20.0)
        self.assertEqual(row["status_detail"], "Final")

    def test_skips_events_missing_id(self) -> None:
        payload = {"events": [{"competitions": []}]}
        with patch.object(schedule_adapter.urllib.request, "urlopen", return_value=_FakeEspnResponse(payload)):
            rows = schedule_adapter._fetch_espn_football_live_state("nfl", "2026-09-08")
        self.assertEqual(rows, [])

    def test_network_failure_returns_empty_list(self) -> None:
        with patch.object(schedule_adapter.urllib.request, "urlopen", side_effect=OSError("boom")):
            rows = schedule_adapter._fetch_espn_football_live_state("nfl", "2026-09-08")
        self.assertEqual(rows, [])

    def test_no_custom_headers_are_sent(self) -> None:
        # Confirmed live 2026-08-05: ESPN 403s this endpoint from Render's
        # outbound IP for any custom User-Agent -- regression guard for the
        # documented gotcha both this function and _fetch_espn_football_schedule
        # carry inline comments about.
        payload = {"events": []}
        captured: dict[str, object] = {}

        def _capture_request(request_obj, timeout=None):  # noqa: ANN001
            captured["headers"] = dict(request_obj.header_items())
            return _FakeEspnResponse(payload)

        with patch.object(schedule_adapter.urllib.request, "urlopen", side_effect=_capture_request):
            schedule_adapter._fetch_espn_football_live_state("nfl", "2026-09-08")

        self.assertEqual(captured.get("headers"), {})


if __name__ == "__main__":
    unittest.main()
