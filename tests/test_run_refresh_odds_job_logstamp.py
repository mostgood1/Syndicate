"""run_refresh_odds_job parses the child's result through the local fleet's
per-line UTC stamp (lane odds-run-result-parse-logstamp).

Since the 2026-10-02 supervisor restarts every line the child prints starts with
`2026-10-02T20:04:34.877Z `, so the indent=2 result's opening brace never began
a line and every run file lost `result` and `failureSummary`.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULT = {"ok": False, "results": [{"sport": "soccer", "ok": False, "refresh_steps": [
    {"name": "soccer_belgian_pro_league_schedule", "ok": False, "return_code": 1,
     "stderr_tail": "requests.exceptions.HTTPError: 502 Server Error"}]}]}


def _load():
    spec = importlib.util.spec_from_file_location("run_refresh_odds_job_under_test", REPO_ROOT / "scripts" / "run_refresh_odds_job.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _stdout(stamped: bool) -> str:
    body = "[refresh_odds_sources] serial_gate raw='true' enabled=True\nSTART soccer\n" + json.dumps(RESULT, indent=2) + "\n"
    if not stamped:
        return body
    return "".join(f"2026-10-02T20:04:34.{i % 1000:03d}Z {line}" for i, line in enumerate(body.splitlines(keepends=True)))


def test_stamped_stdout_parses_like_unstamped():
    mod = _load()
    assert mod._result_payload_from_stdout(_stdout(stamped=True)) == RESULT
    assert mod._result_payload_from_stdout(_stdout(stamped=False)) == RESULT


def test_the_failure_summary_names_the_step_from_stamped_output():
    mod = _load()
    summary = mod._failure_summary_from_result(mod._result_payload_from_stdout(_stdout(stamped=True)))
    assert summary and summary[0]["sport"] == "soccer"
    assert "soccer_belgian_pro_league_schedule" in json.dumps(summary)


def test_a_stamp_shaped_string_inside_a_json_value_is_untouched():
    """Only a stamp at LINE START is stripped; JSON values keep their text."""
    mod = _load()
    payload = {"ok": True, "results": [], "note": "2026-10-02T20:04:34.877Z inside a value"}
    stamped = "".join("2026-10-02T20:04:34.877Z " + line for line in json.dumps(payload, indent=2).splitlines(keepends=True))
    assert mod._result_payload_from_stdout(stamped) == payload
