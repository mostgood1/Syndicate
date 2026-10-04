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
            "syndicate.features.shared.oddsapi_quota.compare_and_swap_json_file",
            side_effect=OSError("disk gone"),
        ):
            self.assertIsNone(record_oddsapi_quota({"x-requests-used": "1"}, sport="mlb"))

    def test_never_raises_when_the_store_read_fails(self) -> None:
        with patch(
            "syndicate.features.shared.oddsapi_quota.read_json_file_result",
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


class ConcurrentWriteRaceProbeTests(unittest.TestCase):
    """Concurrent writers must not lose increments (lane `layer2-freshness-1h`, 2026-10-02).

    The recorder used to read -> add -> blind-write, so the last writer won and
    every other writer's increment vanished: 73% of one fleet window's spend
    never reached `by_sport`. It now writes through compare-and-swap. These
    replace the old race PROBE tests -- the probe counted collisions; the swap
    prevents them.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.reports_root = Path(self._tmp.name)
        os.environ["SYNDICATE_REPORTS_ROOT"] = str(self.reports_root)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: os.environ.pop("SYNDICATE_REPORTS_ROOT", None))

    @unittest.skipIf(os.name == "nt", "Windows cannot replace a file another thread holds open; the disk "
                     "backend's writes fail there, which tests the OS, not the swap. Production is keyvalue.")
    def test_concurrent_writers_lose_no_increment(self) -> None:
        import threading

        threads, per_thread = 8, 25
        barrier = threading.Barrier(threads)

        def _writer(n: int) -> None:
            barrier.wait()
            for i in range(per_thread):
                record_oddsapi_quota(
                    {"x-requests-used": str(n * 1000 + i), "x-requests-last": "1"},
                    sport="nhl" if n % 2 else "ncaaf",
                )

        workers = [threading.Thread(target=_writer, args=(n,)) for n in range(threads)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()

        state = read_oddsapi_quota()
        total_calls = sum(b["calls"] for b in state["by_sport"].values())
        total_credits = sum(b["credits"] for b in state["by_sport"].values())
        self.assertEqual(total_calls, threads * per_thread)
        self.assertEqual(total_credits, threads * per_thread)
        self.assertEqual(state["by_sport"]["nhl"]["calls"], (threads // 2) * per_thread)
        self.assertEqual(state["observation_count"], threads * per_thread)

    def test_a_conflict_retries_and_is_counted_not_lost(self) -> None:
        from syndicate.features.shared import oddsapi_quota as module
        from syndicate.features.shared.refresh_state_store import write_json_file

        record_oddsapi_quota({"x-requests-used": "0", "x-requests-last": "0"}, sport="mlb")
        real_read = module.read_json_file_result
        state = {"interleaved": False}

        def _read_then_another_writer_commits(path):
            payload, ok = real_read(path)
            if not state["interleaved"]:
                # Another writer commits AFTER this call read the document and
                # BEFORE it writes -- the interleaving that used to lose an
                # increment. The swap must notice and rebuild from a fresh read.
                state["interleaved"] = True
                bumped = json.loads(json.dumps(payload))
                bumped["by_sport"]["nhl"] = {"calls": 1, "credits": 2}
                bumped["observation_count"] = int(bumped.get("observation_count") or 0) + 1
                write_json_file(path, bumped)
            return payload, ok

        with patch.object(module, "read_json_file_result", side_effect=_read_then_another_writer_commits):
            record_oddsapi_quota({"x-requests-used": "2", "x-requests-last": "3"}, sport="mlb")

        quota = read_oddsapi_quota()
        self.assertEqual(quota["by_sport"]["mlb"], {"calls": 2, "credits": 3})
        self.assertEqual(quota["by_sport"]["nhl"], {"calls": 1, "credits": 2}, "the other writer's increment survived")
        self.assertGreaterEqual(quota["cas_conflicts_count"], 1)

    def test_a_failed_read_never_zeroes_the_counters(self) -> None:
        from syndicate.features.shared import oddsapi_quota as module

        for i in range(3):
            record_oddsapi_quota({"x-requests-used": str(i), "x-requests-last": "5"}, sport="nhl")
        with patch.object(module, "read_json_file_result", return_value=(None, False)):
            self.assertIsNone(record_oddsapi_quota({"x-requests-used": "9", "x-requests-last": "5"}, sport="nhl"))
        self.assertEqual(read_oddsapi_quota()["by_sport"]["nhl"], {"calls": 3, "credits": 15})

    def test_an_older_observation_committed_late_does_not_replace_latest(self) -> None:
        record_oddsapi_quota({"x-requests-used": "100", "x-requests-last": "1"}, sport="nhl")
        record_oddsapi_quota({"x-requests-used": "150", "x-requests-last": "1"}, sport="nhl")
        # A slower writer that read `used` 120 commits after the 150 reading.
        record_oddsapi_quota({"x-requests-used": "120", "x-requests-last": "1"}, sport="nhl")
        state = read_oddsapi_quota()
        self.assertEqual(state["latest"]["used"], 150)
        self.assertEqual(state["by_sport"]["nhl"]["calls"], 3)

    def test_gives_up_quietly_when_every_attempt_conflicts(self) -> None:
        from syndicate.features.shared import oddsapi_quota as module
        from syndicate.features.shared.refresh_state_store import WriteConflict

        with patch.object(module, "compare_and_swap_json_file", side_effect=WriteConflict(Path("x"), 8)):
            self.assertIsNone(record_oddsapi_quota({"x-requests-used": "1"}, sport="mlb"))


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

    def test_recorded_endpoint_keeps_markets_but_never_the_api_key(self) -> None:
        # Fetchers now pass the REAL requested URL (response.url), which
        # carries both apiKey and markets=. The stored endpoint must keep the
        # markets (attribution reads them) and must never persist the key --
        # the shared-store privacy rule that used to make callers strip the
        # whole query, which is what filed 100% of a day's burn under
        # event_list.
        with TemporaryDirectory() as tmp_dir:
            quota_file = Path(tmp_dir) / "oddsapi_quota.json"
            with patch("syndicate.features.shared.oddsapi_quota._quota_path", return_value=quota_file):
                record_oddsapi_quota(
                    {"x-requests-remaining": "100", "x-requests-used": "50", "x-requests-last": "4"},
                    sport="mlb",
                    endpoint="https://api.the-odds-api.com/v4/sports/baseball_mlb/events/abc/odds?apiKey=SECRET&regions=us&markets=h2h,batter_hits",
                )
                result = read_oddsapi_quota()
            raw = quota_file.read_text(encoding="utf-8")
        self.assertNotIn("SECRET", raw)
        self.assertIn("markets=", result["latest"]["endpoint"])
        # And the cost attributed by market, not filed under event_list.
        self.assertEqual(result["by_market_family"]["full_game"], {"calls": 1, "credits": 2.0})
        self.assertEqual(result["by_market_family"]["props"], {"calls": 1, "credits": 2.0})
        self.assertNotIn("event_list", result["by_market_family"])

    def test_endpoint_sanitizer_drops_the_query_when_it_cannot_parse(self) -> None:
        # Losing one observation's attribution is acceptable; persisting a
        # credential never is.
        from syndicate.features.shared.oddsapi_quota import _sanitize_endpoint

        self.assertEqual(
            _sanitize_endpoint("https://x/odds?apiKey=SECRET&markets=h2h"),
            "https://x/odds?markets=h2h",
        )
        self.assertEqual(
            _sanitize_endpoint("https://x/odds?api_key=SECRET"),
            "https://x/odds",
        )
        self.assertEqual(_sanitize_endpoint("https://x/events"), "https://x/events")
        self.assertEqual(_sanitize_endpoint(""), "")

    def test_reader_passes_the_attribution_buckets_through(self) -> None:
        # The recorder aggregated by_market_family/by_hour_utc for a full day
        # before anyone noticed the reader silently dropped them -- the quota
        # endpoint served an attribution-free payload while the store had the
        # answer the whole time. The reader must surface what the recorder
        # writes, plus aggregates_started_at (the only epoch a rate over these
        # never-resetting aggregates can be computed against).
        with TemporaryDirectory() as tmp_dir:
            quota_file = Path(tmp_dir) / "oddsapi_quota.json"
            with patch("syndicate.features.shared.oddsapi_quota._quota_path", return_value=quota_file):
                record_oddsapi_quota(
                    {"x-requests-remaining": "100", "x-requests-used": "50", "x-requests-last": "6"},
                    sport="mlb",
                    endpoint="https://api.the-odds-api.com/v4/sports/baseball_mlb/events/abc/odds?markets=h2h,batter_hits,h2h_1st_7_innings",
                )
                result = read_oddsapi_quota()
        self.assertEqual(result["by_market_family"]["full_game"], {"calls": 1, "credits": 2.0})
        self.assertEqual(result["by_market_family"]["props"], {"calls": 1, "credits": 2.0})
        self.assertEqual(result["by_market_family"]["first7"], {"calls": 1, "credits": 2.0})
        self.assertEqual(len(result["by_hour_utc"]), 1)
        self.assertTrue(result["aggregates_started_at"])

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

    def test_attribution_failure_is_recorded_not_silently_swallowed(self) -> None:
        # Confirmed live 2026-07-28: by_market_family/by_hour_utc measured
        # ~54% of by_sport's total for the entire tracked window, with a
        # bare `except Exception: pass` giving zero signal as to why. The
        # burn counter must still survive a classifier bug (previous test),
        # but "must still survive" should not mean "must stay a mystery
        # forever" -- the next occurrence should be a one-read diagnosis.
        with TemporaryDirectory() as tmp_dir:
            quota_file = Path(tmp_dir) / "oddsapi_quota.json"
            with patch("syndicate.features.shared.oddsapi_quota._quota_path", return_value=quota_file):
                with patch(
                    "syndicate.features.shared.oddsapi_quota._attribute_request_families",
                    side_effect=RuntimeError("boom"),
                ):
                    record_oddsapi_quota(
                        {"x-requests-remaining": "100", "x-requests-used": "50", "x-requests-last": "6"},
                        sport="mlb",
                        endpoint="whatever",
                    )
            payload = json.loads(quota_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["attribution_error_count"], 1)
            self.assertEqual(payload["last_attribution_error"]["error"], "RuntimeError: boom")
            self.assertEqual(payload["last_attribution_error"]["sport"], "mlb")
            self.assertEqual(payload["last_attribution_error"]["endpoint"], "whatever")

    def test_attribution_error_count_accumulates_across_calls(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            quota_file = Path(tmp_dir) / "oddsapi_quota.json"
            with patch("syndicate.features.shared.oddsapi_quota._quota_path", return_value=quota_file):
                with patch(
                    "syndicate.features.shared.oddsapi_quota._attribute_request_families",
                    side_effect=RuntimeError("boom"),
                ):
                    for used in (50, 51, 52):
                        record_oddsapi_quota(
                            {"x-requests-remaining": "100", "x-requests-used": str(used), "x-requests-last": "1"},
                            sport="mlb",
                            endpoint="whatever",
                        )
            payload = json.loads(quota_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["attribution_error_count"], 3)

    def test_read_surfaces_attribution_error_fields(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            quota_file = Path(tmp_dir) / "oddsapi_quota.json"
            with patch("syndicate.features.shared.oddsapi_quota._quota_path", return_value=quota_file):
                with patch(
                    "syndicate.features.shared.oddsapi_quota._attribute_request_families",
                    side_effect=RuntimeError("boom"),
                ):
                    record_oddsapi_quota(
                        {"x-requests-remaining": "100", "x-requests-used": "50", "x-requests-last": "6"},
                        sport="mlb",
                        endpoint="whatever",
                    )
                result = read_oddsapi_quota()
            self.assertEqual(result["attribution_error_count"], 1)
            self.assertEqual(result["last_attribution_error"]["error"], "RuntimeError: boom")

    def test_no_attribution_failure_leaves_error_fields_at_zero_and_none(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            quota_file = Path(tmp_dir) / "oddsapi_quota.json"
            with patch("syndicate.features.shared.oddsapi_quota._quota_path", return_value=quota_file):
                record_oddsapi_quota(
                    {"x-requests-remaining": "100", "x-requests-used": "50", "x-requests-last": "6"},
                    sport="mlb",
                    endpoint="https://api.the-odds-api.com/v4/sports/baseball_mlb/odds?markets=h2h",
                )
                result = read_oddsapi_quota()
            self.assertEqual(result["attribution_error_count"], 0)
            self.assertIsNone(result["last_attribution_error"])


class OffFleetAbsentDocumentTests(unittest.TestCase):
    """An off-fleet run must never CREATE the quota document.

    `read_json_file_result` returns `(None, ok=True)` both for "no document yet"
    and for "absent in THIS process's `reports_root()` while the real ledger is
    elsewhere". The retry guard already distinguishes a FAILED read, but not that
    third state -- so an off-fleet run built from `{}` and committed a fresh
    document, zeroing every other sport.

    MEASURED 2026-10-03: a backfill run from a worktree whose sparse checkout
    excludes `reports/` replaced a tracked document's
    `by_sport={"nfl": ..., "ncaaf": ...}` with `{"nfl": ...}` alone, and its three
    market families with one. Reproduced both ways before fixing: PRESENT merges
    correctly, ABSENT loses everything. These tests pin both halves plus the
    on-fleet case, so the fix cannot be mistaken for "never create a document".
    """

    HEADERS = {"x-requests-remaining": "4601831", "x-requests-used": "398169", "x-requests-last": "1"}
    PRIOR = {
        "baseline": {"remaining": 3094956, "used": 1905044, "last_cost": 0, "sport": "nfl",
                     "endpoint": "x", "observedAt": "2026-09-29T16:52:54.522+00:00"},
        "latest": {"remaining": 3094903, "used": 1905097, "last_cost": 1, "sport": "nfl",
                   "endpoint": "y", "observedAt": "2026-09-29T16:52:56.996+00:00"},
        "by_sport": {"nfl": {"calls": 18, "credits": 56}, "ncaaf": {"calls": 1, "credits": 3}},
        "by_market_family": {"full_game": {"calls": 2, "credits": 6.0},
                             "event_list": {"calls": 1, "credits": 0.0},
                             "props": {"calls": 16, "credits": 53.0}},
        "observation_count": 19,
    }

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.reports_root = Path(self._tmp.name)
        os.environ["SYNDICATE_REPORTS_ROOT"] = str(self.reports_root)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: os.environ.pop("SYNDICATE_REPORTS_ROOT", None))
        self.addCleanup(lambda: os.environ.pop("SYNDICATE_ODDSAPI_QUOTA_ALLOW_LOCAL_CREATE", None))
        self.quota_file = self.reports_root / "odds_control_plane" / "oddsapi_quota.json"
        self.quota_file.parent.mkdir(parents=True, exist_ok=True)

    def _write_prior(self) -> None:
        self.quota_file.write_text(json.dumps(self.PRIOR), encoding="utf-8")

    # `_fleet_forward_enabled` is deliberately False under pytest (fake headers
    # must never reach the fleet), so off-fleet-ness is patched rather than
    # enabled via the env -- which also keeps `_forward_to_fleet` a no-op here.
    @staticmethod
    def _off_fleet(enabled: bool):
        return patch("syndicate.features.shared.oddsapi_quota._fleet_forward_enabled",
                     return_value=enabled)

    def test_off_fleet_with_no_document_creates_nothing(self) -> None:
        with self._off_fleet(True):
            returned = record_oddsapi_quota(self.HEADERS, sport="nfl", endpoint="historical/events")
        self.assertFalse(
            self.quota_file.exists(),
            "an off-fleet run must not mint a local quota document it cannot see the ledger for",
        )
        # The observation is still returned: the caller's spend happened, and
        # `_forward_to_fleet` is the path that accounts for it.
        self.assertIsNotNone(returned)
        self.assertEqual(returned["used"], 398169)

    def test_off_fleet_with_an_existing_document_still_merges(self) -> None:
        # The merge was never the bug. If this ever fails, the fix has gone too
        # far and off-fleet runs have stopped counting at all.
        self._write_prior()
        with self._off_fleet(True):
            record_oddsapi_quota(self.HEADERS, sport="nfl", endpoint="historical/events")
        after = json.loads(self.quota_file.read_text(encoding="utf-8"))
        self.assertIn("ncaaf", after["by_sport"], "another sport's counters were dropped")
        self.assertEqual(after["by_sport"]["ncaaf"]["credits"], 3)
        self.assertEqual(after["by_sport"]["nfl"]["credits"], 57)
        for family in ("full_game", "event_list", "props"):
            self.assertIn(family, after["by_market_family"], family)

    def test_on_fleet_with_no_document_still_creates_it(self) -> None:
        # A fresh fleet install has no document and must get one; the refusal is
        # about being off-fleet, not about absence.
        with self._off_fleet(False):
            record_oddsapi_quota(self.HEADERS, sport="nfl", endpoint="historical/events")
        self.assertTrue(self.quota_file.exists())
        after = json.loads(self.quota_file.read_text(encoding="utf-8"))
        self.assertEqual(after["by_sport"]["nfl"]["calls"], 1)

    def test_the_escape_hatch_restores_local_creation(self) -> None:
        os.environ["SYNDICATE_ODDSAPI_QUOTA_ALLOW_LOCAL_CREATE"] = "1"
        with self._off_fleet(True):
            record_oddsapi_quota(self.HEADERS, sport="nfl", endpoint="historical/events")
        self.assertTrue(
            self.quota_file.exists(),
            "a dev measuring their own spend in isolation can opt back in",
        )
