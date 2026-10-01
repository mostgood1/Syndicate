"""scripts/local_audit_sweep.py -- the local-fleet route sweep, now in the repo."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import local_audit_sweep as sweep_mod


def _fetcher(answers: dict[str, tuple[int | None, bytes, str]]):
    calls: list[str] = []

    def fetch(rule: str):
        calls.append(rule)
        return answers.get(rule, (200, b'{"ok": true}', ""))

    return fetch, calls


class SweepRulesTests(unittest.TestCase):
    def test_param_routes_are_ignored_and_mutating_routes_never_requested(self) -> None:
        routes = [
            {"rule": "/", "args": []},
            {"rule": "/nba/game/<game_pk>", "args": ["game_pk"]},
            {"rule": "/api/ops/odds/refresh", "args": []},
            {"rule": "/static/app.js", "args": []},
        ]
        fetch, calls = _fetcher({})
        results = sweep_mod.sweep(routes, fetch, echo=lambda _l: None)
        self.assertEqual(calls, ["/"])
        self.assertEqual([(r["rule"], r.get("skipped", False)) for r in results], [("/", False), ("/api/ops/odds/refresh", True), ("/static/app.js", True)])

    def test_failures_markers_and_empty_json_are_flagged(self) -> None:
        routes = [{"rule": r, "args": []} for r in ("/ok", "/boom", "/trace", "/empty", "/slow")]
        fetch, _ = _fetcher({
            "/boom": (502, b'{"error":"failed to load live player props audit"}', ""),
            "/trace": (200, b"<pre>Traceback (most recent call last)</pre>", ""),
            "/empty": (200, b"[]", ""),
            "/slow": (None, b"", "TimeoutError: timed out"),
        })
        results = {r["rule"]: r for r in sweep_mod.sweep(routes, fetch, echo=lambda _l: None)}
        self.assertFalse(sweep_mod.is_failure(results["/ok"]))
        self.assertTrue(sweep_mod.is_failure(results["/boom"]))
        self.assertEqual(results["/trace"]["err_marker"], "Traceback")
        self.assertTrue(results["/empty"]["json_empty"])
        self.assertTrue(sweep_mod.is_failure(results["/slow"]))
        summary = sweep_mod.summarize(list(results.values()))
        self.assertEqual(summary["failures"], ["/boom", "/slow", "/trace"])
        self.assertEqual(summary["json_empty"], ["/empty"])


class CompareTests(unittest.TestCase):
    def test_status_changes_are_reported_both_ways(self) -> None:
        before = [
            {"rule": "/nba/api/live-player-props-audit", "status": 502, "secs": 0.0, "error": ""},
            {"rule": "/api/ops/intelligence/candidate-trace", "status": None, "secs": 87.98, "error": "TimeoutError: timed out"},
            {"rule": "/same", "status": 200, "secs": 0.1, "error": ""},
        ]
        after = [
            {"rule": "/nba/api/live-player-props-audit", "status": 200, "secs": 0.01, "error": ""},
            {"rule": "/api/ops/intelligence/candidate-trace", "status": 400, "secs": 0.0, "error": ""},
            {"rule": "/same", "status": 200, "secs": 0.2, "error": ""},
        ]
        changes = {c["rule"]: c for c in sweep_mod.compare(before, after)}
        self.assertEqual(set(changes), {"/nba/api/live-player-props-audit", "/api/ops/intelligence/candidate-trace"})
        self.assertEqual(changes["/api/ops/intelligence/candidate-trace"]["before"]["status"], None)


class MainTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / "audit_routes.json").write_text(json.dumps([{"rule": "/", "endpoint": "home", "args": []}, {"rule": "/bad", "endpoint": "bad", "args": []}]), encoding="utf-8")
        (self.home / "local_production.env").write_text('ADMIN_TOKEN="tok-123"\n', encoding="utf-8")

    def _run(self, answers):
        seen = {}

        def factory(base_url, token, *, timeout):
            seen["token"], seen["base_url"] = token, base_url
            return _fetcher(answers)[0]

        with patch.object(sweep_mod, "http_fetcher", side_effect=factory), patch.object(sweep_mod, "supervisor_pid", return_value="42"), patch("builtins.print"):
            code = sweep_mod.main(["--home", str(self.home), "--quiet"])
        return code, seen

    def test_writes_results_keeps_the_previous_run_and_exits_nonzero_on_failure(self) -> None:
        code, seen = self._run({"/bad": (502, b"x", "")})
        self.assertEqual(code, 1)
        self.assertEqual(seen, {"token": "tok-123", "base_url": "http://127.0.0.1:10000"})
        first = json.loads((self.home / "audit_sweep.json").read_text(encoding="utf-8"))
        self.assertFalse((self.home / "audit_sweep.prev.json").exists())

        code, _ = self._run({})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads((self.home / "audit_sweep.prev.json").read_text(encoding="utf-8")), first)

    def test_a_supervisor_restart_mid_sweep_is_a_failure(self) -> None:
        pids = iter(["42", "43"])
        with patch.object(sweep_mod, "http_fetcher", return_value=_fetcher({})[0]), patch.object(sweep_mod, "supervisor_pid", side_effect=lambda: next(pids)), patch("builtins.print"):
            self.assertEqual(sweep_mod.main(["--home", str(self.home), "--quiet"]), 1)


if __name__ == "__main__":
    unittest.main()
