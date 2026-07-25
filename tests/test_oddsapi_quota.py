from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared.oddsapi_quota import parse_quota_headers
from syndicate.features.shared.oddsapi_quota import read_oddsapi_quota
from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota


class ParseQuotaHeadersTests(unittest.TestCase):
    def test_parses_the_three_quota_headers(self) -> None:
        parsed = parse_quota_headers(
            {"x-requests-remaining": "4821931", "x-requests-used": "178069", "x-requests-last": "45"}
        )
        self.assertEqual(parsed, {"remaining": 4821931, "used": 178069, "last_cost": 45})

    def test_is_case_insensitive(self) -> None:
        parsed = parse_quota_headers({"X-Requests-Remaining": "10", "X-Requests-Used": "5"})
        self.assertEqual(parsed, {"remaining": 10, "used": 5})

    def test_returns_none_when_no_quota_headers_present(self) -> None:
        # "not an OddsAPI response" must be distinguishable from "zero
        # remaining", which is a real and alarming state.
        self.assertIsNone(parse_quota_headers({"content-type": "application/json"}))
        self.assertIsNone(parse_quota_headers({}))
        self.assertIsNone(parse_quota_headers(None))

    def test_zero_remaining_is_reported_not_dropped(self) -> None:
        parsed = parse_quota_headers({"x-requests-remaining": "0", "x-requests-used": "5000000"})
        self.assertEqual(parsed["remaining"], 0)

    def test_tolerates_float_and_junk_values(self) -> None:
        parsed = parse_quota_headers({"x-requests-remaining": "12.0", "x-requests-used": "junk"})
        self.assertEqual(parsed, {"remaining": 12})


class RecordAndReadQuotaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["SYNDICATE_REPORTS_ROOT"] = str(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: os.environ.pop("SYNDICATE_REPORTS_ROOT", None))

    def test_records_observation_and_reports_latest(self) -> None:
        record_oddsapi_quota(
            {"x-requests-remaining": "100", "x-requests-used": "50", "x-requests-last": "5"},
            sport="mlb",
            endpoint="https://api.the-odds-api.com/v4/sports/baseball_mlb/events",
        )
        state = read_oddsapi_quota()
        self.assertEqual(state["latest"]["used"], 50)
        self.assertEqual(state["latest"]["sport"], "mlb")
        self.assertEqual(state["observation_count"], 1)

    def test_burn_is_derived_from_absolute_counter_delta(self) -> None:
        # The whole point of recording observations rather than accumulating:
        # `used` is an absolute server-side counter, so burn survives lost
        # writes from the three services racing on a non-atomic store.
        record_oddsapi_quota({"x-requests-used": "1000", "x-requests-remaining": "9000"}, sport="mlb")
        record_oddsapi_quota({"x-requests-used": "1600", "x-requests-remaining": "8400"}, sport="mlb")
        state = read_oddsapi_quota()
        self.assertEqual(state["credits_burned_in_window"], 600)

    def test_single_observation_reports_unmeasured_not_zero(self) -> None:
        # "not measured yet" and "not burning" must not look identical --
        # confusing the two is why this module exists at all.
        record_oddsapi_quota({"x-requests-used": "1000"}, sport="mlb")
        state = read_oddsapi_quota()
        self.assertIsNone(state["credits_burned_in_window"])
        self.assertIsNone(state["credits_per_hour"])
        self.assertIsNone(state["projected_30d_credits"])

    def test_attributes_credits_per_sport(self) -> None:
        record_oddsapi_quota({"x-requests-used": "10", "x-requests-last": "45"}, sport="mlb")
        record_oddsapi_quota({"x-requests-used": "20", "x-requests-last": "2400"}, sport="soccer")
        record_oddsapi_quota({"x-requests-used": "30", "x-requests-last": "45"}, sport="mlb")
        by_sport = read_oddsapi_quota()["by_sport"]
        self.assertEqual(by_sport["mlb"], {"calls": 2, "credits": 90})
        self.assertEqual(by_sport["soccer"], {"calls": 1, "credits": 2400})

    def test_ignores_responses_without_quota_headers(self) -> None:
        self.assertIsNone(record_oddsapi_quota({"content-type": "application/json"}, sport="mlb"))
        self.assertEqual(read_oddsapi_quota()["observation_count"], 0)

    def test_never_raises_when_the_store_write_fails(self) -> None:
        # Called from fetchers' HTTP seams inside detached subprocesses --
        # instrumentation must never be able to fail the refresh it measures.
        with patch(
            "syndicate.features.shared.oddsapi_quota.write_json_file",
            side_effect=OSError("disk gone"),
        ):
            self.assertIsNone(record_oddsapi_quota({"x-requests-used": "1"}, sport="mlb"))

    def test_never_raises_when_the_store_read_fails(self) -> None:
        with patch(
            "syndicate.features.shared.oddsapi_quota.read_json_file",
            side_effect=OSError("disk gone"),
        ):
            self.assertIsNone(record_oddsapi_quota({"x-requests-used": "1"}, sport="mlb"))

    def test_observations_are_bounded(self) -> None:
        for index in range(520):
            record_oddsapi_quota({"x-requests-used": str(index)}, sport="mlb")
        self.assertLessEqual(read_oddsapi_quota()["observation_count"], 500)

    def test_read_on_empty_store_is_safe(self) -> None:
        state = read_oddsapi_quota()
        self.assertIsNone(state["latest"])
        self.assertEqual(state["observation_count"], 0)
        self.assertEqual(state["by_sport"], {})
