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
        self.reports_root = Path(self._tmp.name)
        os.environ["SYNDICATE_REPORTS_ROOT"] = str(self.reports_root)
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

    def test_stored_payload_stays_small_regardless_of_call_volume(self) -> None:
        # #54: this used to store the last 500 observations, making it the
        # largest key in a Redis instance that also holds sim pointers,
        # refresh manifests and board state -- and on 2026-07-25 the key went
        # from 20 observations to absent across a deploy. Telemetry must not
        # be the biggest thing in a store critical operations depend on.
        for index in range(520):
            record_oddsapi_quota({"x-requests-used": str(index), "x-requests-last": "1"}, sport="mlb")

        raw = json.loads((self.reports_root / "odds_control_plane" / "oddsapi_quota.json").read_text(encoding="utf-8"))

        self.assertNotIn("observations", raw)
        self.assertEqual(raw["observation_count"], 520)
        self.assertLess(len(json.dumps(raw)), 2000, "payload must stay O(1), not grow with call count")

    def test_counts_every_call_even_though_it_stores_two(self) -> None:
        for index in range(5):
            record_oddsapi_quota({"x-requests-used": str(index)}, sport="mlb")
        self.assertEqual(read_oddsapi_quota()["observation_count"], 5)

    def test_baseline_rolls_forward_when_the_counter_resets(self) -> None:
        # `used` going down is a billing-period rollover; measuring against
        # the old baseline would report a negative burn.
        record_oddsapi_quota({"x-requests-used": "900000"}, sport="mlb")
        record_oddsapi_quota({"x-requests-used": "12"}, sport="mlb")
        record_oddsapi_quota({"x-requests-used": "40"}, sport="mlb")
        self.assertEqual(read_oddsapi_quota()["credits_burned_in_window"], 28)

    def test_reports_burn_even_when_no_rate_can_be_derived(self) -> None:
        # "600 credits burned, rate unknown" is more useful than reporting
        # nothing because the two samples landed in the same clock tick.
        with patch("syndicate.features.shared.oddsapi_quota._utc_now_iso", return_value="2026-07-25T18:00:00.000+00:00"):
            record_oddsapi_quota({"x-requests-used": "1000"}, sport="mlb")
            record_oddsapi_quota({"x-requests-used": "1600"}, sport="mlb")
        state = read_oddsapi_quota()
        self.assertEqual(state["credits_burned_in_window"], 600)
        self.assertIsNone(state["credits_per_hour"])

    def test_reads_the_pre_54_observations_schema(self) -> None:
        # A partially rolled-out deploy should report a slightly stale window
        # rather than nothing at all.
        path = self.reports_root / "odds_control_plane" / "oddsapi_quota.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "latest": {"used": 1600, "observedAt": "2026-07-25T18:10:00+00:00", "sport": "mlb"},
                    "observations": [
                        {"used": 1000, "observedAt": "2026-07-25T18:00:00+00:00", "sport": "mlb", "last_cost": 5},
                        {"used": 1600, "observedAt": "2026-07-25T18:10:00+00:00", "sport": "mlb", "last_cost": 5},
                    ],
                }
            ),
            encoding="utf-8",
        )
        state = read_oddsapi_quota()
        self.assertEqual(state["credits_burned_in_window"], 600)
        self.assertEqual(state["window_seconds"], 600)
        self.assertEqual(state["by_sport"]["mlb"]["calls"], 2)

    def test_read_on_empty_store_is_safe(self) -> None:
        state = read_oddsapi_quota()
        self.assertIsNone(state["latest"])
        self.assertEqual(state["observation_count"], 0)
        self.assertEqual(state["by_sport"], {})


class MarketFamilyAttributionTests(unittest.TestCase):
    """#15. 371,563 credits/day measured with MLB at 96.3%, and every cut on
    the table (#16 a/b, tiering, event scoping) needs to know which MARKETS
    the credits went to. Families are decision-mapped levers, not taxonomy.
    """

    def test_families_mirror_the_16_audit_axes(self) -> None:
        from syndicate.features.shared.oddsapi_quota import _market_family

        # (b): first7 wins even when also alternate_-prefixed, mirroring the
        # audit's disjoint 8-alternates / 6-first7 counts.
        self.assertEqual(_market_family("h2h_1st_7_innings"), "first7")
        self.assertEqual(_market_family("alternate_totals_1st_7_innings"), "first7")
        # (a): alternates, full-game or segment.
        self.assertEqual(_market_family("alternate_spreads"), "alternate")
        self.assertEqual(_market_family("alternate_spreads_1st_1_innings"), "alternate")
        # Cadence-tier candidate.
        self.assertEqual(_market_family("h2h_3_way_1st_3_innings"), "segment")
        # Event-scoping candidate.
        self.assertEqual(_market_family("batter_total_bases"), "props")
        self.assertEqual(_market_family("pitcher_strikeouts"), "props")
        # The board's core -- not a cut candidate.
        self.assertEqual(_market_family("h2h"), "full_game")
        self.assertEqual(_market_family("totals"), "full_game")

    def test_request_cost_splits_proportionally_across_families(self) -> None:
        from syndicate.features.shared.oddsapi_quota import _attribute_request_families

        url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/events/abc/odds?regions=us&markets=h2h,totals,batter_hits,alternate_spreads"
        split = _attribute_request_families(url, 8)
        self.assertEqual(split, {"full_game": 4.0, "props": 2.0, "alternate": 2.0})

    def test_no_markets_param_is_the_event_list(self) -> None:
        from syndicate.features.shared.oddsapi_quota import _attribute_request_families

        split = _attribute_request_families("https://api.the-odds-api.com/v4/sports/baseball_mlb/events?date=x", 0)
        self.assertEqual(split, {"event_list": 0.0})

    def test_historical_endpoints_get_their_own_alarm_bucket(self) -> None:
        # #21: 10x-billed, should never appear in production. A non-zero
        # bucket IS the alarm.
        from syndicate.features.shared.oddsapi_quota import _attribute_request_families

        url = "https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/odds?markets=h2h"
        self.assertEqual(_attribute_request_families(url, 20), {"historical": 20.0})

    def test_recorder_accumulates_family_and_hour_buckets(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            quota_file = Path(tmp_dir) / "oddsapi_quota.json"
            with patch("syndicate.features.shared.oddsapi_quota._quota_path", return_value=quota_file):
                for _ in range(2):
                    record_oddsapi_quota(
                        {"x-requests-remaining": "100", "x-requests-used": "50", "x-requests-last": "6"},
                        sport="mlb",
                        endpoint="https://api.the-odds-api.com/v4/sports/baseball_mlb/events/abc/odds?markets=h2h,batter_hits,h2h_1st_7_innings",
                    )
            payload = json.loads(quota_file.read_text(encoding="utf-8"))
            families = payload["by_market_family"]
            self.assertEqual(families["full_game"], {"calls": 2, "credits": 4.0})
            self.assertEqual(families["props"], {"calls": 2, "credits": 4.0})
            self.assertEqual(families["first7"], {"calls": 2, "credits": 4.0})
            self.assertIn("aggregates_started_at", payload)
            # Exactly one UTC hour bucket, carrying the full cost.
            hours = payload["by_hour_utc"]
            self.assertEqual(len(hours), 1)
            (bucket,) = hours.values()
            self.assertEqual(bucket, {"calls": 2, "credits": 12})

    def test_attribution_failure_degrades_to_unattributed_not_unrecorded(self) -> None:
        # The burn counter is load-bearing (#15's whole decision rests on it);
        # attribution is a bonus. A bug in the classifier must cost the
        # breakdown, never the observation.
        with TemporaryDirectory() as tmp_dir:
            quota_file = Path(tmp_dir) / "oddsapi_quota.json"
            with patch("syndicate.features.shared.oddsapi_quota._quota_path", return_value=quota_file):
                with patch(
                    "syndicate.features.shared.oddsapi_quota._attribute_request_families",
                    side_effect=RuntimeError("boom"),
                ):
                    result = record_oddsapi_quota(
                        {"x-requests-remaining": "100", "x-requests-used": "50", "x-requests-last": "6"},
                        sport="mlb",
                        endpoint="whatever",
                    )
            self.assertIsNotNone(result, "the observation itself must survive")
            payload = json.loads(quota_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["latest"]["used"], 50)
            self.assertEqual(payload["by_market_family"], {})
