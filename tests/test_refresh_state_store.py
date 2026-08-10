from __future__ import annotations

import json
import os
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared import ops_refresh
from syndicate.features.shared import refresh_state_store
from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.source_roots import preferred_source_roots


class _FakeKeyValueClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.last_ex: int | None = None

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = str(value)
        self.last_ex = ex
        if ex is not None:
            self.ttls[key] = ex
        else:
            self.ttls.pop(key, None)
        return True

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    def delete(self, key: str) -> int:
        self.ttls.pop(key, None)
        return 1 if self.store.pop(key, None) is not None else 0

    def scan(self, cursor: int = 0, match: str | None = None, count: int | None = None):
        import fnmatch

        pattern = str(match or "*")
        matched = [key for key in self.store.keys() if fnmatch.fnmatch(key, pattern)]
        return 0, matched

    def ttl(self, key: str) -> int:
        if key not in self.store:
            return -2
        return self.ttls.get(key, -1)

    def memory_usage(self, key: str) -> int | None:
        value = self.store.get(key)
        return len(value.encode("utf-8")) if value is not None else None

    def expire(self, key: str, seconds: int) -> bool:
        if key not in self.store:
            return False
        self.ttls[key] = seconds
        return True

    def info(self) -> dict[str, object]:
        return {
            "used_memory": 1234567,
            "used_memory_human": "1.18M",
            "maxmemory": 26214400,
            "maxmemory_human": "25.00M",
            "maxmemory_policy": "allkeys_lru",
            "evicted_keys": 42,
            "expired_keys": 3,
            "connected_clients": 5,
            "rejected_connections": 0,
            "role": "master",
            "redis_version": "8.1.4",
            "db0": {"keys": 100, "expires": 10, "avg_ttl": 0},
        }


class RefreshStateStoreTests(unittest.TestCase):
    def tearDown(self) -> None:
        refresh_state_store.reset_state_store_caches()

    def test_hosted_storage_requires_explicit_roots(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_REQUIRE_HOSTED_STORAGE": "true",
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                refresh_state_store.data_root()
            with self.assertRaises(RuntimeError):
                refresh_state_store.reports_root()

        with TemporaryDirectory() as tmp_dir:
            probe_file = Path(tmp_dir) / "probe.py"
            probe_file.write_text("", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_REQUIRE_HOSTED_STORAGE": "true",
                },
                clear=False,
            ):
                with self.assertRaises(RuntimeError):
                    preferred_source_roots(probe_file, env_var="SYNDICATE_SOURCE_ROOT_NBA", local_dir_name="nba_source")
                with self.assertRaises(RuntimeError):
                    preferred_artifact_roots(probe_file, env_var="SYNDICATE_ARTIFACT_ROOT_NBA", local_dir_name="nba_source")

    def test_hosted_refresh_state_backend_rejects_filesystem_and_logs_backend(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RENDER": "true",
                "SYNDICATE_REFRESH_STATE_BACKEND": "filesystem",
                "SYNDICATE_REQUIRE_HOSTED_STORAGE": "true",
            },
            clear=False,
        ), patch("builtins.print") as mocked_print:
            with self.assertRaises(RuntimeError):
                refresh_state_store.assert_refresh_state_backend_ready(process_name="web")

        printed_text = "\n".join(str(call.args[0]) for call in mocked_print.call_args_list if call.args)
        self.assertIn("REFRESH_STATE_BACKEND = filesystem", printed_text)

    def test_hosted_refresh_state_backend_accepts_keyvalue_and_logs_backend(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RENDER": "true",
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REQUIRE_HOSTED_STORAGE": "true",
            },
            clear=False,
        ), patch("builtins.print") as mocked_print:
            backend_name = refresh_state_store.assert_refresh_state_backend_ready(process_name="web")

        self.assertEqual(backend_name, "keyvalue")
        printed_text = "\n".join(str(call.args[0]) for call in mocked_print.call_args_list if call.args)
        self.assertIn("REFRESH_STATE_BACKEND = keyvalue", printed_text)

    def test_hosted_refresh_state_backend_defaults_to_keyvalue_when_url_is_present(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RENDER": "true",
                "SYNDICATE_REQUIRE_HOSTED_STORAGE": "true",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
            },
            clear=False,
        ), patch("builtins.print") as mocked_print:
            backend_name = refresh_state_store.assert_refresh_state_backend_ready(process_name="refresh-worker")

        self.assertEqual(backend_name, "keyvalue")
        printed_text = "\n".join(str(call.args[0]) for call in mocked_print.call_args_list if call.args)
        self.assertIn("REFRESH_STATE_BACKEND = keyvalue", printed_text)

    def test_render_hosted_reports_root_falls_back_to_repo_reports(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RENDER": "1",
                "SYNDICATE_REQUIRE_HOSTED_STORAGE": "true",
            },
            clear=False,
        ):
            self.assertEqual(refresh_state_store.reports_root(), refresh_state_store.REPORTS_ROOT)

    def test_keyvalue_backend_round_trips_json_and_text_by_path(self) -> None:
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
            },
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            manifest_path = Path(tmp_dir) / "reports" / "refresh_status" / "latest" / "refresh_status_latest.json"
            # #324: deliberately NOT a migration_runs path. That prefix is now
            # excluded from the keyvalue store, so this test would still have
            # passed -- via disk -- while claiming to prove a keyvalue
            # round-trip. A test that passes for the wrong reason is worse than
            # one that fails.
            stderr_path = Path(tmp_dir) / "reports" / "live_refresh_loop" / "x" / "odds_refresh.stderr.txt"

            refresh_state_store.write_json_file(manifest_path, {"state": "pending_external", "date": "2026-05-22"})
            refresh_state_store.write_text_file(stderr_path, "worker stderr")

            self.assertEqual(refresh_state_store.read_json_file(manifest_path), {"state": "pending_external", "date": "2026-05-22"})
            self.assertEqual(refresh_state_store.read_text_file(stderr_path), "worker stderr")
            self.assertTrue(refresh_state_store.path_exists(manifest_path))
            self.assertGreater(refresh_state_store.path_size(stderr_path), 0)

    def test_delete_text_file_removes_keyvalue_entry(self) -> None:
        # Real bug found 2026-07-23: write_text_file had no delete
        # counterpart on the keyvalue backend at all -- every caller that
        # deletes a stale artifact's filesystem copy (e.g. WNBA's
        # game_cards_{date}.csv, cleared on a genuinely empty slate) left
        # the keyvalue-stored copy from that same write untouched, so a
        # deployment using the keyvalue backend kept serving stale content
        # indefinitely even after the filesystem file was correctly gone.
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
            },
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            text_path = Path(tmp_dir) / "reports" / "wnba_source" / "data" / "processed" / "game_cards_2026-07-23.csv"

            refresh_state_store.write_text_file(text_path, "stale content")
            self.assertTrue(refresh_state_store.path_exists(text_path))

            refresh_state_store.delete_text_file(text_path)

            self.assertFalse(refresh_state_store.path_exists(text_path))
            self.assertIsNone(refresh_state_store.read_text_file(text_path))

    def test_delete_text_file_removes_filesystem_copy_on_filesystem_backend(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            text_path = Path(tmp_dir) / "game_cards_2026-07-23.csv"
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text("stale content", encoding="utf-8")

            refresh_state_store.delete_text_file(text_path)

            self.assertFalse(text_path.exists())

    def test_delete_text_file_is_a_noop_when_nothing_exists(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            text_path = Path(tmp_dir) / "does_not_exist.csv"
            refresh_state_store.delete_text_file(text_path)

    def test_keyvalue_backend_tracks_refresh_history_paths(self) -> None:
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            manifest_path = Path(tmp_dir) / "reports" / "refresh_status" / "2026-05-22" / "20260522_120000" / "refresh_status_manifest.json"
            refresh_state_store.write_json_file(manifest_path, {"date": "2026-05-22", "runStamp": "20260522_120000"})

            history_paths = refresh_state_store.list_refresh_status_manifest_paths(limit=6)

            self.assertEqual(history_paths, [manifest_path.resolve()])

    def test_known_refresh_lanes_tracked_on_keyvalue_backend(self) -> None:
        # Per-service refresh-run lanes: "latest" manifest files aren't
        # necessarily materialized on any single service's local disk under
        # the keyvalue backend, so a raw filesystem glob can't discover
        # lanes written by a different service. This explicit index (mirrors
        # the existing refresh-history index) is what makes cross-service
        # lane discovery possible.
        fake_client = _FakeKeyValueClient()
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
            },
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            self.assertEqual(refresh_state_store.known_refresh_lanes(), [])

            refresh_state_store.record_known_refresh_lane("refresh-worker")
            refresh_state_store.record_known_refresh_lane("live-odds-worker")
            refresh_state_store.record_known_refresh_lane("refresh-worker")  # duplicate, should not repeat

            self.assertEqual(refresh_state_store.known_refresh_lanes(), ["refresh-worker", "live-odds-worker"])

    def test_known_refresh_lanes_is_noop_on_filesystem_backend(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_REFRESH_STATE_BACKEND": "filesystem"}, clear=False):
            refresh_state_store.record_known_refresh_lane("refresh-worker")
            self.assertEqual(refresh_state_store.known_refresh_lanes(), [])

    def test_refresh_state_hash_round_trips_and_reuses_identical_inputs(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ):
            state_path = refresh_state_store.refresh_state_path()
            input_hash = refresh_state_store.build_input_hash({"step": "nba_live_lens", "inputs": ["a", "b"]})

            self.assertTrue(refresh_state_store.should_recompute("nba_live_lens", input_hash))
            refresh_state_store.record_refresh_state(
                "nba_live_lens",
                input_hash,
                outputs=[str(Path(tmp_dir) / "reports" / "nba_live_lens.jsonl")],
                metadata={"date": "2026-06-10"},
            )

            self.assertFalse(refresh_state_store.should_recompute("nba_live_lens", input_hash))
            self.assertEqual(
                refresh_state_store.read_json_file(state_path),
                {
                    "steps": {
                        "nba_live_lens": {
                            "inputHash": input_hash,
                            "outputs": [str(Path(tmp_dir) / "reports" / "nba_live_lens.jsonl")],
                            "metadata": {"date": "2026-06-10"},
                            "updatedAt": refresh_state_store.read_json_file(state_path)["steps"]["nba_live_lens"]["updatedAt"],
                        }
                    }
                },
            )

    def test_read_json_file_result_distinguishes_absent_from_read_failure(self) -> None:
        # read_json_file collapses "genuinely absent" and "read failed" into
        # the same None -- callers that use "no manifest" as a
        # safety-relevant signal (the refresh-run concurrency guard) need to
        # tell those apart, or a transient backend hiccup gets treated the
        # same as "nothing is running."
        with TemporaryDirectory() as tmp_dir:
            missing_path = Path(tmp_dir) / "does_not_exist.json"
            payload, ok = refresh_state_store.read_json_file_result(missing_path)
            self.assertIsNone(payload)
            self.assertTrue(ok)

            malformed_path = Path(tmp_dir) / "malformed.json"
            malformed_path.write_text("{not valid json", encoding="utf-8")
            payload, ok = refresh_state_store.read_json_file_result(malformed_path)
            self.assertIsNone(payload)
            self.assertFalse(ok)

            good_path = Path(tmp_dir) / "good.json"
            good_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            payload, ok = refresh_state_store.read_json_file_result(good_path)
            self.assertEqual(payload, {"state": "running"})
            self.assertTrue(ok)

    def test_read_json_file_result_reports_keyvalue_backend_failures(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
            },
            clear=False,
        ), patch(
            "syndicate.features.shared.refresh_state_store._get_keyvalue_client",
            side_effect=RuntimeError("connection reset"),
        ):
            path = Path(tmp_dir) / "reports" / "refresh_status" / "latest" / "refresh_status_latest.json"
            payload, ok = refresh_state_store.read_json_file_result(path)

        self.assertIsNone(payload)
        self.assertFalse(ok)

    def test_read_text_file_result_distinguishes_absent_from_read_failure(self) -> None:
        # Board audit follow-up, 2026-07-31: read_text_file had the exact
        # same "absent vs. failed" ambiguity read_json_file_result was
        # already built to fix, just never given the same treatment --
        # root-caused live as the reason a transient keyvalue hiccup wiped
        # WNBA's entire game/prop candidate pool off the board instead of
        # being distinguishable from a real "no data" result.
        with TemporaryDirectory() as tmp_dir:
            missing_path = Path(tmp_dir) / "does_not_exist.csv"
            text, ok = refresh_state_store.read_text_file_result(missing_path)
            self.assertIsNone(text)
            self.assertTrue(ok)

            good_path = Path(tmp_dir) / "good.csv"
            good_path.write_text("a,b\n1,2\n", encoding="utf-8")
            text, ok = refresh_state_store.read_text_file_result(good_path)
            self.assertEqual(text, "a,b\n1,2")
            self.assertTrue(ok)

    def test_read_text_file_result_reports_keyvalue_backend_failures(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
            },
            clear=False,
        ), patch(
            "syndicate.features.shared.refresh_state_store._get_keyvalue_client",
            side_effect=RuntimeError("connection reset"),
        ):
            path = Path(tmp_dir) / "data" / "processed" / "game_cards_2026-07-31.csv"
            text, ok = refresh_state_store.read_text_file_result(path)

        self.assertIsNone(text)
        self.assertFalse(ok)

    def test_read_text_file_unchanged_behavior_still_collapses_to_none(self) -> None:
        # read_text_file itself (the pre-existing, still-used-elsewhere
        # entry point) must keep returning bare None for both cases --
        # only the new _result variant exposes the distinction.
        with TemporaryDirectory() as tmp_dir:
            missing_path = Path(tmp_dir) / "does_not_exist.csv"
            self.assertIsNone(refresh_state_store.read_text_file(missing_path))

    def test_keyvalue_diagnostics_returns_none_on_filesystem_backend(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_REFRESH_STATE_BACKEND": "filesystem"}, clear=False):
            self.assertIsNone(refresh_state_store.keyvalue_diagnostics())

    def test_keyvalue_diagnostics_reports_real_info_stats(self) -> None:
        # Board audit follow-up, 2026-07-31: built to answer, with real
        # numbers, whether WNBA's (and every other sport's, at the same
        # instant) intermittent dashboard_games_count=0 is keyvalue memory
        # eviction, connection exhaustion, or something else.
        fake_client = _FakeKeyValueClient()
        with patch.dict(
            os.environ,
            {"SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue", "SYNDICATE_REFRESH_STATE_URL": "redis://example"},
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            diagnostics = refresh_state_store.keyvalue_diagnostics()

        self.assertTrue(diagnostics["ok"])
        self.assertEqual(diagnostics["stats"]["evicted_keys"], 42)
        self.assertEqual(diagnostics["stats"]["maxmemory_policy"], "allkeys_lru")
        self.assertEqual(diagnostics["keyspace"]["db0"]["keys"], 100)

    def test_default_ttl_detects_hyphenated_and_underscored_date_tokens(self) -> None:
        # Board audit follow-up, 2026-07-31: root-caused live -- the shared
        # keyvalue store had expired_keys=0 despite sitting at 96% of its
        # 256MB cap with 34,529 LRU evictions and a 44% miss rate. Most
        # keyvalue-backed artifacts are scoped to one calendar date embedded
        # in their own filename but never got a TTL, so old, dead dates
        # competed with today's actively-needed keys for the same fixed
        # memory forever.
        self.assertEqual(
            refresh_state_store._default_keyvalue_ttl_seconds(Path("game_cards_2026-07-31.csv")),
            refresh_state_store._KEYVALUE_DATE_SCOPED_TTL_SECONDS,
        )
        self.assertEqual(
            refresh_state_store._default_keyvalue_ttl_seconds(Path("live_lens_report_2026_07_31.json")),
            refresh_state_store._KEYVALUE_DATE_SCOPED_TTL_SECONDS,
        )

    def test_default_ttl_is_none_for_paths_with_no_date_token(self) -> None:
        self.assertIsNone(refresh_state_store._default_keyvalue_ttl_seconds(Path("refresh_state.json")))
        self.assertIsNone(refresh_state_store._default_keyvalue_ttl_seconds(Path("intelligence_state.json")))

    def test_default_ttl_is_none_for_an_invalid_date_like_token(self) -> None:
        # A "2026-13-99"-shaped substring isn't a real date -- must not
        # crash or false-positive into applying a TTL.
        self.assertIsNone(refresh_state_store._default_keyvalue_ttl_seconds(Path("weird_2026-13-99_file.json")))

    def test_default_ttl_is_shorter_for_run_scoped_paths(self) -> None:
        # Board audit follow-up, 2026-07-31: the first real production sweep
        # found the actual bloat wasn't one-key-per-date artifacts (those are
        # safe on the 10-day default) -- it was one-key-per-RUN paths under
        # refresh_status/, migration_runs/, and live_refresh_loop/, where
        # every single refresh/odds-refresh/sim tick writes a brand-new,
        # never-reused key. A 10-day TTL on this category alone would let it
        # re-accumulate to the same ~56MB/1,337-key backlog within a day or
        # two, so these get a much shorter TTL.
        self.assertEqual(
            refresh_state_store._default_keyvalue_ttl_seconds(
                Path("reports/refresh_status/2026-07-31/run123/refresh_status_manifest.json")
            ),
            refresh_state_store._KEYVALUE_RUN_SCOPED_TTL_SECONDS,
        )
        self.assertEqual(
            refresh_state_store._default_keyvalue_ttl_seconds(
                Path("reports/migration_runs/2026-07-31/odds_refresh_20260731_120000/manifest.json")
            ),
            refresh_state_store._KEYVALUE_RUN_SCOPED_TTL_SECONDS,
        )
        self.assertEqual(
            refresh_state_store._default_keyvalue_ttl_seconds(
                Path("reports/live_refresh_loop/mlb_sim_runs/2026-07-31/tick_9.json")
            ),
            refresh_state_store._KEYVALUE_RUN_SCOPED_TTL_SECONDS,
        )
        self.assertLess(
            refresh_state_store._KEYVALUE_RUN_SCOPED_TTL_SECONDS,
            refresh_state_store._KEYVALUE_DATE_SCOPED_TTL_SECONDS,
        )

    def test_default_ttl_stays_at_the_longer_default_for_non_run_scoped_date_paths(self) -> None:
        # A date-scoped path that doesn't match any run-scoped marker keeps
        # the longer 10-day default -- the shorter TTL must not leak onto
        # unrelated date-scoped artifacts like game_cards.csv.
        self.assertEqual(
            refresh_state_store._default_keyvalue_ttl_seconds(Path("game_cards_2026-07-31.csv")),
            refresh_state_store._KEYVALUE_DATE_SCOPED_TTL_SECONDS,
        )

    def test_write_json_file_passes_the_detected_ttl_to_the_keyvalue_set_call(self) -> None:
        fake_client = _FakeKeyValueClient()
        with patch.dict(
            os.environ,
            {"SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue", "SYNDICATE_REFRESH_STATE_URL": "redis://example"},
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            refresh_state_store.write_json_file(Path("game_cards_2026-07-31.csv"), {"ok": True})
        self.assertEqual(fake_client.last_ex, refresh_state_store._KEYVALUE_DATE_SCOPED_TTL_SECONDS)

    def test_write_json_file_passes_no_ttl_for_a_non_date_scoped_path(self) -> None:
        fake_client = _FakeKeyValueClient()
        with patch.dict(
            os.environ,
            {"SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue", "SYNDICATE_REFRESH_STATE_URL": "redis://example"},
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            refresh_state_store.write_json_file(Path("refresh_state.json"), {"ok": True})
        self.assertIsNone(fake_client.last_ex)

    def test_write_text_file_passes_the_detected_ttl_to_the_keyvalue_set_call(self) -> None:
        fake_client = _FakeKeyValueClient()
        with patch.dict(
            os.environ,
            {"SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue", "SYNDICATE_REFRESH_STATE_URL": "redis://example"},
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            refresh_state_store.write_text_file(Path("game_cards_2026-07-31.csv"), "a,b\n1,2\n")
        self.assertEqual(fake_client.last_ex, refresh_state_store._KEYVALUE_DATE_SCOPED_TTL_SECONDS)

    def _seed_sweep_fixture(self, fake_client: _FakeKeyValueClient) -> None:
        prefix = refresh_state_store._keyvalue_namespace_key_prefix()
        # A stale date (>= 10 days old), no TTL -- should be reported/swept.
        fake_client.store[f"{prefix}/wnba_source/data/processed/game_cards_2026-07-01.csv"] = "a" * 100
        # A fresh, recent date -- must NOT be touched.
        fake_client.store[f"{prefix}/wnba_source/data/processed/game_cards_2026-07-30.csv"] = "b" * 50
        # A stale date that ALREADY has a TTL (e.g. written after the Phase 1
        # fix shipped) -- must not be double-counted/touched again.
        stale_but_ttl_key = f"{prefix}/wnba_source/data/processed/recommendations_slate_2026-07-05.json"
        fake_client.store[stale_but_ttl_key] = "c" * 30
        fake_client.ttls[stale_but_ttl_key] = 500000
        # No date token at all -- must be excluded from staleness entirely.
        fake_client.store[f"{prefix}/reports/refresh_state.json"] = "d" * 20

    def test_sweep_preview_reports_stale_no_ttl_keys_without_mutating_anything(self) -> None:
        fake_client = _FakeKeyValueClient()
        self._seed_sweep_fixture(fake_client)
        with patch.dict(
            os.environ,
            {"SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue", "SYNDICATE_REFRESH_STATE_URL": "redis://example"},
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client), patch(
            "syndicate.features.shared.refresh_state_store.datetime"
        ) as fake_datetime:
            fake_datetime.now.return_value.date.return_value = date(2026, 7, 31)
            preview = refresh_state_store.keyvalue_sweep_preview(stale_after_days=10)

        self.assertTrue(preview["ok"])
        self.assertEqual(preview["total_keys_scanned"], 4)
        self.assertEqual(preview["stale_no_ttl_key_count"], 1)
        self.assertEqual(preview["stale_no_ttl_estimated_bytes"], 100)
        self.assertEqual(preview["fresh_or_already_ttl_keys"], 2)
        self.assertEqual(preview["no_date_token_keys"], 1)
        # Read-only: nothing in the fake store should have changed.
        self.assertEqual(len(fake_client.store), 4)
        self.assertNotIn(
            f"{refresh_state_store._keyvalue_namespace_key_prefix()}/wnba_source/data/processed/game_cards_2026-07-01.csv",
            fake_client.ttls,
        )

    def test_sweep_apply_sets_grace_period_ttl_only_on_stale_no_ttl_keys(self) -> None:
        fake_client = _FakeKeyValueClient()
        self._seed_sweep_fixture(fake_client)
        prefix = refresh_state_store._keyvalue_namespace_key_prefix()
        stale_key = f"{prefix}/wnba_source/data/processed/game_cards_2026-07-01.csv"
        fresh_key = f"{prefix}/wnba_source/data/processed/game_cards_2026-07-30.csv"

        with patch.dict(
            os.environ,
            {"SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue", "SYNDICATE_REFRESH_STATE_URL": "redis://example"},
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client), patch(
            "syndicate.features.shared.refresh_state_store.datetime"
        ) as fake_datetime:
            fake_datetime.now.return_value.date.return_value = date(2026, 7, 31)
            result = refresh_state_store.keyvalue_sweep_apply(stale_after_days=10, grace_period_seconds=3600)

        self.assertTrue(result["ok"])
        self.assertEqual(result["keys_touched"], 1)
        self.assertEqual(result["estimated_bytes_reclaimed"], 100)
        # The stale key now has the grace-period TTL; nothing else was touched.
        self.assertEqual(fake_client.ttls.get(stale_key), 3600)
        self.assertNotIn(fresh_key, fake_client.ttls)
        # Still present (not deleted) -- readers get their grace period.
        self.assertIn(stale_key, fake_client.store)

    def test_sweep_functions_return_none_on_filesystem_backend(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_REFRESH_STATE_BACKEND": "filesystem"}, clear=False):
            self.assertIsNone(refresh_state_store.keyvalue_sweep_preview())
            self.assertIsNone(refresh_state_store.keyvalue_sweep_apply())

    def test_keyvalue_diagnostics_reports_connection_failure(self) -> None:
        with patch.dict(
            os.environ,
            {"SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue", "SYNDICATE_REFRESH_STATE_URL": "redis://example"},
            clear=False,
        ), patch(
            "syndicate.features.shared.refresh_state_store._get_keyvalue_client",
            side_effect=RuntimeError("connection reset"),
        ):
            diagnostics = refresh_state_store.keyvalue_diagnostics()

        self.assertFalse(diagnostics["ok"])
        self.assertIn("connection reset", diagnostics["error"])

    def test_ops_status_reads_latest_manifest_and_artifacts_from_keyvalue_backend(self) -> None:
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            artifacts_dir = reports_root / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000"
            historical_manifest_path = reports_root / "refresh_status" / "2026-05-21" / "20260521_120000" / "refresh_status_manifest.json"

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                    "SYNDICATE_REFRESH_STATE_URL": "redis://example",
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "ADMIN_TOKEN": "secret-token",
                },
                clear=False,
            ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
                refresh_state_store.write_json_file(
                    latest_manifest_path,
                    {
                        "date": "2026-05-22",
                        "artifactsDir": str(artifacts_dir),
                        "state": "finished",
                    },
                )
                refresh_state_store.write_json_file(artifacts_dir / "odds_refresh.json", {"ok": True, "sports": ["mlb"]})
                refresh_state_store.write_text_file(artifacts_dir / "odds_refresh.stderr.txt", "")
                refresh_state_store.write_json_file(
                    historical_manifest_path,
                    {
                        "date": "2026-05-21",
                        "runStamp": "20260521_120000",
                        "artifactsDir": str(reports_root / "migration_runs" / "2026-05-21" / "odds_refresh_20260521_120000"),
                        "state": "failed",
                    },
                )
                refresh_state_store.write_json_file(
                    reports_root / "daily_update" / "latest" / "daily_update_latest.json",
                    {"date": "2026-05-22"},
                )

                status = ops_refresh.load_latest_refresh_status()

            self.assertEqual(status["refresh_status"]["manifest"]["date"], "2026-05-22")
            self.assertTrue(status["refresh_status"]["manifest_exists"])
            self.assertTrue(status["refresh_status"]["artifacts"]["odds_refresh"]["exists"])
            self.assertGreaterEqual(len(status["refresh_status"]["history"]), 1)

    def test_launch_refresh_run_writes_latest_manifest_through_keyvalue_backend(self) -> None:
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client), patch("syndicate.features.shared.ops_refresh.subprocess.Popen") as mocked_popen:
            mocked_popen.return_value.pid = 4321

            result = ops_refresh.launch_refresh_run(sports="wnba", phase="pregame", dry_run=True)
            status = ops_refresh.load_latest_refresh_status()

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "running")
        self.assertEqual(status["refresh_status"]["manifest"]["runStamp"], result["run_stamp"])
        self.assertEqual(status["refresh_status"]["runtime"]["pid"], 4321)
        self.assertEqual(status["refresh_status"]["runtime"]["launch_owner"], "web_process")

    def test_load_latest_refresh_status_prefers_unified_daily_update_manifest(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ):
            reports_root = Path(tmp_dir) / "reports"
            refresh_latest = reports_root / "refresh_status" / "latest"
            daily_latest = reports_root / "daily_update" / "latest"
            artifacts_dir = reports_root / "migration_runs" / "2026-06-04" / "20260604_110712"

            refresh_latest.mkdir(parents=True, exist_ok=True)
            daily_latest.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(parents=True, exist_ok=True)

            refresh_state_store.write_json_file(
                refresh_latest / "refresh_status_latest.json",
                {
                    "date": "2026-06-04",
                    "artifactsDir": str(artifacts_dir),
                    "state": "finished",
                },
            )
            refresh_state_store.write_json_file(artifacts_dir / "odds_refresh.json", {"ok": True, "sports": ["wnba"]})
            refresh_state_store.write_text_file(artifacts_dir / "odds_refresh.stderr.txt", "")
            refresh_state_store.write_json_file(
                daily_latest / "daily_update_latest.json",
                {"date": "2026-05-18"},
            )
            refresh_state_store.write_json_file(
                daily_latest / "unified_daily_update_latest.json",
                {"date": "2026-06-04", "skipped": {"nba": True}},
            )
            refresh_state_store.write_json_file(
                daily_latest / "unified_daily_update_latest_simulation_contract.json",
                {
                    "contract_version": "v1",
                    "scope": "daily_update",
                    "date": "2026-06-04",
                    "market_summary": {"market_feature_count": 2},
                    "market_summary_by_sport": {"mlb": {"market_feature_count": 1}},
                },
            )

            status = ops_refresh.load_latest_refresh_status()

        self.assertEqual(status["daily_update"]["manifest"]["date"], "2026-06-04")
        self.assertTrue(status["daily_update"]["manifest_exists"])
        self.assertTrue(status["daily_update"]["manifest_path"].endswith("unified_daily_update_latest.json"))
        self.assertEqual(status["daily_update"]["market_summary"]["market_feature_count"], 2)
        self.assertEqual(status["daily_update"]["market_summary_by_sport"]["mlb"]["market_feature_count"], 1)


if __name__ == "__main__":
    unittest.main()

class KeyValuePayloadCeilingTests(unittest.TestCase):
    """#60. Three separate outages on 2026-07-25 were one bug -- an unbounded
    payload crossing this boundary -- and each presented as something else: an
    empty board (#43), a missing metric (#54), a memory leak (#50).

    #43 is the reason this exists. An 8.9MB intelligence state threw
    ConnectionError from deep inside redis, a generic handler caught it, and a
    healthy-looking loop discarded a correctly computed 222-candidate board
    every cycle for hours. The size was never the hard part; the silence was.
    """

    def _guard(self, size_bytes: int):
        return refresh_state_store._guard_keyvalue_payload_size(
            Path("/data/reports/intelligence/intelligence_state.json"), "x" * size_bytes
        )

    def test_small_payloads_are_silent(self) -> None:
        with patch("builtins.print") as printed:
            self._guard(1024)
            printed.assert_not_called()

    def test_growing_payloads_warn_but_are_allowed(self) -> None:
        # Visibility before it becomes an outage -- the write still happens.
        with patch("builtins.print") as printed:
            self._guard(2 * 1024 * 1024)
            self.assertTrue(printed.called)
            self.assertIn("KEYVALUE_WRITE_LARGE", str(printed.call_args))

    def test_oversized_payloads_are_refused_with_a_named_error(self) -> None:
        # A dedicated type so callers can tell "this payload is wrong" from a
        # transient ConnectionError -- exactly the confusion that hid #43.
        with self.assertRaises(refresh_state_store.KeyValuePayloadTooLarge):
            self._guard(9 * 1024 * 1024)

    def test_the_real_post_fix_state_size_still_writes(self) -> None:
        # 4.37MB is #43's payload after its trim. A ceiling below this would
        # break the board this rule exists to protect.
        with patch("builtins.print"):
            self._guard(int(4.37 * 1024 * 1024))

    def test_rejection_names_key_size_and_caller(self) -> None:
        # The whole point: a refusal you can act on in minutes.
        with patch("builtins.print") as printed:
            with self.assertRaises(refresh_state_store.KeyValuePayloadTooLarge):
                self._guard(9 * 1024 * 1024)
            logged = str(printed.call_args)
        self.assertIn("KEYVALUE_WRITE_REJECTED", logged)
        self.assertIn("intelligence_state.json", logged)
        self.assertIn("size_bytes=", logged)
        self.assertIn("caller=", logged)
        self.assertNotIn("caller=unknown", logged)

    def test_thresholds_are_env_tunable(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_KEYVALUE_MAX_BYTES": str(2 * 1024 * 1024)}, clear=False):
            with patch("builtins.print"):
                with self.assertRaises(refresh_state_store.KeyValuePayloadTooLarge):
                    self._guard(3 * 1024 * 1024)

    def test_write_json_file_enforces_the_ceiling(self) -> None:
        client = _FakeKeyValueClient()
        with patch.object(refresh_state_store, "_state_backend_kind", return_value="keyvalue"), patch.object(
            refresh_state_store, "_get_keyvalue_client", return_value=client
        ), patch("builtins.print"):
            with self.assertRaises(refresh_state_store.KeyValuePayloadTooLarge):
                refresh_state_store.write_json_file(
                    Path("/data/reports/intelligence/intelligence_state.json"),
                    {"blob": "x" * (9 * 1024 * 1024)},
                )
            self.assertEqual(client.store, {}, "nothing should be written when the payload is refused")

    def test_filesystem_backend_is_unaffected(self) -> None:
        # Large files on disk are fine; only the shared store has this limit.
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "big.json"
            with patch.object(refresh_state_store, "_state_backend_kind", return_value="filesystem"):
                refresh_state_store.write_json_file(target, {"blob": "x" * (9 * 1024 * 1024)})
            self.assertTrue(target.exists())


class MigrationRunsAreNotKeyvalueBackedTests(unittest.TestCase):
    """#324. Run diagnostics must never reach the keyvalue store.

    Measured on production 2026-08-10: `migration_runs/**` held 211.41MB across
    5,293 keys -- 86% of a 256MB instance at 96.1% under allkeys-lru, with
    38,865 keys already evicted, while `reports/intelligence` (the actual board)
    held 11.96MB and competed with it for residency.

    The 2-day TTL was NOT the failure. It was applied to 6,992 of 7,058 keys and
    `avg_ttl` sat at 24.74h against a 48h TTL -- TTL/2 to within 3%, the
    signature of uniform steady state. A TTL bounds age, not size.
    """

    def _env(self):
        return patch.dict(
            os.environ,
            {"SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue", "SYNDICATE_REFRESH_STATE_URL": "redis://example"},
            clear=False,
        )

    def test_migration_runs_never_touches_the_store(self) -> None:
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, self._env(), patch(
            "syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client
        ):
            path = Path(tmp_dir) / "reports" / "migration_runs" / "2026-08-10" / "odds_refresh_1" / "odds_refresh.json"
            refresh_state_store.write_json_file(path, {"ok": True, "candidates": 150})

            self.assertEqual(fake_client.store, {}, "nothing may be written to the keyvalue store")
            self.assertTrue(path.is_file(), "it must land on disk instead")
            # Read must agree with write, or the artifact reads as vanished.
            self.assertEqual(refresh_state_store.read_json_file(path), {"ok": True, "candidates": 150})
            self.assertTrue(refresh_state_store.path_exists(path))
            self.assertGreater(refresh_state_store.path_size(path), 0)

    def test_text_artifacts_are_excluded_too(self) -> None:
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, self._env(), patch(
            "syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client
        ):
            path = Path(tmp_dir) / "reports" / "migration_runs" / "2026-08-10" / "r" / "odds_refresh.stderr.txt"
            refresh_state_store.write_text_file(path, "worker stderr")
            self.assertEqual(fake_client.store, {})
            self.assertEqual(refresh_state_store.read_text_file(path), "worker stderr")

    def test_refresh_status_latest_is_still_keyvalue_backed(self) -> None:
        # The half that would break a working path if I over-reached.
        # refresh_status/latest IS read cross-service (record_known_refresh_lane
        # exists precisely for that), and refresh_status + live_refresh_loop
        # together were 4.4MB -- they are not the problem.
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, self._env(), patch(
            "syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client
        ):
            path = Path(tmp_dir) / "reports" / "refresh_status" / "latest" / "refresh_worker_status.json"
            refresh_state_store.write_json_file(path, {"lane": "worker"})
            self.assertTrue(fake_client.store, "refresh_status/latest must still cross services")

    def test_intelligence_board_state_is_still_keyvalue_backed(self) -> None:
        # #317/#322 depend on this one entirely.
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, self._env(), patch(
            "syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client
        ):
            path = Path(tmp_dir) / "reports" / "intelligence" / "board_snapshot.json"
            refresh_state_store.write_json_file(path, {"candidate_count": 150})
            self.assertTrue(fake_client.store, "the board must still cross services")

    def test_exclusion_is_backend_agnostic_on_filesystem(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ, {"SYNDICATE_REFRESH_STATE_BACKEND": "filesystem"}, clear=False
        ):
            path = Path(tmp_dir) / "reports" / "migration_runs" / "2026-08-10" / "r" / "odds_refresh.json"
            refresh_state_store.write_json_file(path, {"ok": True})
            self.assertEqual(refresh_state_store.read_json_file(path), {"ok": True})
