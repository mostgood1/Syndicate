"""Targeted expiry of old per-run diagnostic artifacts.

Measured 2026-08-03: `migration_runs/**` held 185.71MB of a 212.67MB
keyvalue total on a 256MB instance already evicting coordination state
under `allkeys-lru`. Truncating new writes stops the growth but cannot
reclaim the backlog, which carries ~37h TTLs -- so keyvalue_sweep_apply
(TTL-less keys only) cannot touch it either. Upgrading is not an option.

This is a mutating production tool over shared state, so the scoping and
dry-run behaviour are the parts worth pinning down.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from syndicate.features.shared.refresh_state_store import _run_stamp_age_hours
from syndicate.features.shared.refresh_state_store import keyvalue_expire_run_artifacts


class RunStampAgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)

    def test_age_is_parsed_from_a_run_stamp(self) -> None:
        key = "syndicate:refresh-state:/data/reports/migration_runs/2026-08-03/odds_refresh_20260803_060000/odds_refresh.json"
        self.assertAlmostEqual(_run_stamp_age_hours(key, now=self.now), 6.0, places=3)

    def test_recent_run_is_near_zero(self) -> None:
        stamp = (self.now - timedelta(minutes=5)).strftime("%Y%m%d_%H%M%S")
        key = f"syndicate:refresh-state:/data/reports/migration_runs/x/odds_refresh_{stamp}/odds_refresh.json"
        self.assertLess(_run_stamp_age_hours(key, now=self.now), 0.2)

    def test_key_without_a_stamp_is_declined_not_guessed(self) -> None:
        # Returning 0 or infinity here would either never expire these or
        # expire them all; neither is a safe default for a mutating sweep.
        self.assertIsNone(_run_stamp_age_hours("syndicate:refresh-state:/data/reports/manifests/mlb.json", now=self.now))

    def test_unparseable_stamp_is_declined(self) -> None:
        self.assertIsNone(_run_stamp_age_hours("run_99999999_999999/file.json", now=self.now))


class ExpireRunArtifactsScopeTests(unittest.TestCase):
    def test_empty_scope_is_refused(self) -> None:
        # An unscoped run would happily expire board state and coordination
        # keys, which is exactly the failure this guard exists to prevent.
        result = keyvalue_expire_run_artifacts(path_contains="", dry_run=True)
        if result is None:
            self.skipTest("keyvalue backend not configured in this environment")
        self.assertFalse(result.get("ok"))
        self.assertIn("path_contains", str(result.get("error")))

    def test_whitespace_only_scope_is_refused(self) -> None:
        result = keyvalue_expire_run_artifacts(path_contains="   ", dry_run=True)
        if result is None:
            self.skipTest("keyvalue backend not configured in this environment")
        self.assertFalse(result.get("ok"))

    def test_returns_none_when_backend_is_not_keyvalue(self) -> None:
        # Local/filesystem environments must get a clear None rather than a
        # partial success that implies something was swept.
        from syndicate.features.shared.refresh_state_store import _state_backend_kind

        if _state_backend_kind() == "keyvalue":
            self.skipTest("this environment IS keyvalue-backed")
        self.assertIsNone(keyvalue_expire_run_artifacts(dry_run=True))


if __name__ == "__main__":
    unittest.main()
