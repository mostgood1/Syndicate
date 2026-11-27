"""WNBA `has_games_for_date`: a PAST date in a web request answers from the artifacts, never from ESPN.

Lane `game-chips-request-path-espn` (2026-11-27). A past-date `/api/board/game-chips` build (the 8:15 AM
play-cards grader asks for every date since 10-16) called ESPN once per build for any past date with no WNBA
artifact -- the whole off-season. With the host's network down on 11-26 that call stalled in DNS inside the
request. A past date with no artifact has no slate this platform tracked, so the answer is False without the
GET. Today, future dates and every non-request caller are unchanged. Off != on: with
`SYNDICATE_REQUEST_PATH_ESPN_FETCH=on` the same request fetches again.
"""

from __future__ import annotations

import json
import unittest
from io import BytesIO
from unittest.mock import patch

from flask import Flask

from syndicate.features.wnba import sources as wnba_sources

_APP = Flask(__name__)
TODAY = "2026-11-27"
PAST = "2026-11-20"


class _FakeEspnResponse:
    def __init__(self, payload: dict) -> None:
        self._buffer = BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self) -> bytes:
        return self._buffer.read()

    def __enter__(self) -> "_FakeEspnResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class PastDateInARequestTests(unittest.TestCase):
    def setUp(self) -> None:
        wnba_sources._HAS_GAMES_CONFIRMED_TRUE_CACHE.clear()

    def tearDown(self) -> None:
        wnba_sources._HAS_GAMES_CONFIRMED_TRUE_CACHE.clear()

    def _ask(self, date: str, *, in_request: bool, env: dict | None = None, artifacts=()):
        with patch.object(wnba_sources, "central_today_iso", return_value=TODAY), \
             patch.object(wnba_sources, "available_dates", return_value=list(artifacts)), \
             patch.dict("os.environ", env or {"SYNDICATE_REQUEST_PATH_ESPN_FETCH": ""}), \
             patch.object(wnba_sources.urllib_request, "urlopen",
                          return_value=_FakeEspnResponse({"events": []})) as urlopen:
            if in_request:
                with _APP.test_request_context("/api/board/game-chips?date=" + date):
                    result = wnba_sources.has_games_for_date(date)
            else:
                result = wnba_sources.has_games_for_date(date)
        return result, urlopen.call_count

    def test_a_past_date_with_no_artifact_answers_false_with_no_espn_call(self) -> None:
        result, calls = self._ask(PAST, in_request=True)
        self.assertIs(result, False)
        self.assertEqual(calls, 0)

    def test_off_is_not_on_the_switch_brings_the_fetch_back(self) -> None:
        result, calls = self._ask(PAST, in_request=True, env={"SYNDICATE_REQUEST_PATH_ESPN_FETCH": "on"})
        self.assertEqual(calls, 1)
        self.assertIs(result, False)

    def test_outside_a_request_the_workers_still_ask_espn(self) -> None:
        _, calls = self._ask(PAST, in_request=False)
        self.assertEqual(calls, 1)

    def test_today_in_a_request_still_asks_espn(self) -> None:
        _, calls = self._ask(TODAY, in_request=True)
        self.assertEqual(calls, 1)

    def test_a_past_date_with_an_artifact_is_still_true(self) -> None:
        result, calls = self._ask(PAST, in_request=True, artifacts=[PAST])
        self.assertIs(result, True)
        self.assertEqual(calls, 0)


if __name__ == "__main__":
    unittest.main()
