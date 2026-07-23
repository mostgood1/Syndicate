from __future__ import annotations

import json
import unittest
from io import BytesIO
from unittest.mock import patch

from syndicate.features.wnba import sources as wnba_sources


class _FakeEspnResponse:
    def __init__(self, payload: dict) -> None:
        self._buffer = BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self) -> bytes:
        return self._buffer.read()

    def __enter__(self) -> "_FakeEspnResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class HasGamesForDateTests(unittest.TestCase):
    def setUp(self) -> None:
        wnba_sources._HAS_GAMES_CONFIRMED_TRUE_CACHE.clear()

    def tearDown(self) -> None:
        wnba_sources._HAS_GAMES_CONFIRMED_TRUE_CACHE.clear()

    def test_past_date_trusts_artifact_existence_without_querying_espn(self) -> None:
        with patch.object(wnba_sources, "central_today_iso", return_value="2026-07-23"), patch.object(
            wnba_sources, "available_dates", return_value=["2026-07-22"]
        ), patch.object(
            wnba_sources.urllib_request, "urlopen", side_effect=AssertionError("must not query ESPN for a past date with an existing artifact")
        ):
            self.assertTrue(wnba_sources.has_games_for_date("2026-07-22"))

    def test_todays_date_ignores_artifact_existence_and_checks_espn(self) -> None:
        # Real bug found 2026-07-23: stale same-day artifacts (game_cards,
        # recommendations_slate) from a prior real slate day can persist
        # even once today is genuinely empty (e.g. All-Star break) --
        # trusting "an artifact exists for today" here made the board keep
        # showing a stale slate no matter how thoroughly the artifacts
        # themselves got fixed. Today must always fall through to a real
        # schedule check.
        with patch.object(wnba_sources, "central_today_iso", return_value="2026-07-23"), patch.object(
            wnba_sources, "available_dates", return_value=["2026-07-23"]
        ), patch.object(
            wnba_sources.urllib_request, "urlopen", return_value=_FakeEspnResponse({"events": []})
        ) as mock_urlopen:
            result = wnba_sources.has_games_for_date("2026-07-23")

        mock_urlopen.assert_called_once()
        self.assertFalse(result)

    def test_todays_date_returns_true_when_espn_confirms_real_games(self) -> None:
        with patch.object(wnba_sources, "central_today_iso", return_value="2026-07-23"), patch.object(
            wnba_sources, "available_dates", return_value=["2026-07-23"]
        ), patch.object(
            wnba_sources.urllib_request, "urlopen", return_value=_FakeEspnResponse({"events": [{"id": "1"}]})
        ):
            self.assertTrue(wnba_sources.has_games_for_date("2026-07-23"))

    def test_espn_confirmed_true_for_today_is_cached_and_not_requeried(self) -> None:
        with patch.object(wnba_sources, "central_today_iso", return_value="2026-07-23"), patch.object(
            wnba_sources, "available_dates", return_value=[]
        ), patch.object(
            wnba_sources.urllib_request, "urlopen", return_value=_FakeEspnResponse({"events": [{"id": "1"}]})
        ) as mock_urlopen:
            self.assertTrue(wnba_sources.has_games_for_date("2026-07-23"))
            self.assertTrue(wnba_sources.has_games_for_date("2026-07-23"))

        self.assertEqual(mock_urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
