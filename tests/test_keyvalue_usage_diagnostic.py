"""The keyvalue usage-by-prefix diagnostic.

Added because the shared keyvalue instance sat at 230MB of a 256MB ceiling
with `allkeys-lru` actively evicting, and the only existing instrument
(sweep-preview) accounted for stale TTL-less keys only -- 183KB of that
230MB. Upgrading the instance is not an option, so the reduction work needs
to know which live payloads actually hold the memory.
"""

from __future__ import annotations

import unittest

from syndicate.features.shared.refresh_state_store import _keyvalue_usage_bucket


class KeyvalueUsageBucketTests(unittest.TestCase):
    def test_dated_run_segments_collapse_so_buckets_stay_readable(self) -> None:
        first = _keyvalue_usage_bucket(
            "syndicate:refresh-state:/opt/render/project/data/reports/migration_runs/2026-07-31/odds_refresh_20260731_181911/odds_refresh.json"
        )
        second = _keyvalue_usage_bucket(
            "syndicate:refresh-state:/opt/render/project/data/reports/migration_runs/2026-08-01/odds_refresh_20260801_094502/odds_refresh.json"
        )
        # Two different days and run stamps must land in ONE bucket -- else
        # every run reports its own row and the output is as unusable as the
        # raw key list it is meant to summarise.
        self.assertEqual(first, second)
        self.assertIn("migration_runs", first)

    def test_distinct_areas_stay_in_distinct_buckets(self) -> None:
        migration = _keyvalue_usage_bucket(
            "syndicate:refresh-state:/opt/render/project/data/reports/migration_runs/2026-07-31/x/odds_refresh.json"
        )
        intelligence = _keyvalue_usage_bucket(
            "syndicate:refresh-state:/opt/render/project/data/reports/intelligence/board_snapshot_2026_08_02.json"
        )
        self.assertNotEqual(migration, intelligence)
        self.assertIn("intelligence", intelligence)

    def test_underscore_dated_filenames_are_collapsed_too(self) -> None:
        bucket = _keyvalue_usage_bucket(
            "syndicate:refresh-state:/opt/render/project/data/reports/intelligence/2026_08_02/board_state.json"
        )
        self.assertIn("<date>", bucket)

    def test_non_path_shaped_key_still_buckets_without_raising(self) -> None:
        self.assertTrue(_keyvalue_usage_bucket("syndicate:refresh-state-history"))

    def test_empty_key_is_handled(self) -> None:
        self.assertEqual(_keyvalue_usage_bucket(""), "(unbucketed)")


if __name__ == "__main__":
    unittest.main()
