"""scripts/local_audit_routes.py rebuilds the audit sweep's route list.

The hand-made list went stale: on 2026-10-01 it still held six MLB
betting-card URLs deleted in d5aeeca4, and the sweep reported six 404s.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from scripts.local_audit_routes import build_route_list, diff_route_lists, main, write_route_list


def _rule(rule: str, endpoint: str, methods: set[str], args: set[str] = frozenset()) -> SimpleNamespace:
    return SimpleNamespace(rule=rule, endpoint=endpoint, methods=set(methods), arguments=set(args))


class BuildAndDiffTests(unittest.TestCase):
    def test_only_get_rules_in_the_sweeps_shape(self) -> None:
        rules = [
            _rule("/", "home.home", {"GET", "HEAD", "OPTIONS"}),
            _rule("/api/ops/run", "ops.run", {"POST", "OPTIONS"}),
            _rule("/nba/game/<game_pk>", "nba.game_detail", {"GET", "HEAD"}, {"game_pk"}),
        ]
        self.assertEqual(
            build_route_list(rules),
            [
                {"rule": "/", "endpoint": "home.home", "args": []},
                {"rule": "/nba/game/<game_pk>", "endpoint": "nba.game_detail", "args": ["game_pk"]},
            ],
        )

    def test_diff_names_removed_and_added_routes(self) -> None:
        old = [{"rule": "/a", "endpoint": "x.a", "args": []}, {"rule": "/mlb/api/betting-card", "endpoint": "mlb.stub", "args": []}]
        new = [{"rule": "/a", "endpoint": "x.a", "args": []}, {"rule": "/b/<id>", "endpoint": "x.b", "args": ["id"]}]
        report = diff_route_lists(old, new)
        self.assertEqual(report["removed"], [("/mlb/api/betting-card", "mlb.stub")])
        self.assertEqual(report["added"], [("/b/<id>", "x.b")])
        self.assertEqual((report["old_param_free"], report["new_param_free"]), (2, 1))


class WriteTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "audit_routes.json"

    def test_write_keeps_the_old_file_as_a_timestamped_backup(self) -> None:
        self.path.write_text('[{"rule": "/old", "endpoint": "x.old", "args": []}]', encoding="utf-8")
        backup = write_route_list(self.path, [{"rule": "/new", "endpoint": "x.new", "args": []}], now=datetime(2026, 10, 1, 22, 0, tzinfo=timezone.utc))
        self.assertEqual(backup.name, "audit_routes.json.20261001T220000Z.bak")
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8"))[0]["rule"], "/old")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))[0]["rule"], "/new")

    def test_first_write_has_no_backup(self) -> None:
        self.assertIsNone(write_route_list(self.path, []))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), [])


class MainTests(unittest.TestCase):
    def test_a_dry_run_against_the_real_app_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(main(["--home", home]), 0)
            self.assertFalse((Path(home) / "audit_routes.json").exists())

    def test_write_produces_the_real_apps_get_routes(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(main(["--home", home, "--write"]), 0)
            routes = json.loads((Path(home) / "audit_routes.json").read_text(encoding="utf-8"))
        rules = {item["rule"] for item in routes}
        self.assertIn("/", rules)
        self.assertIn("/api/ops/intelligence/candidate-trace", rules)
        self.assertNotIn("/mlb/api/betting-card", rules)  # deleted in d5aeeca4
        self.assertTrue(all(set(item) == {"rule", "endpoint", "args"} for item in routes))


if __name__ == "__main__":
    unittest.main()
