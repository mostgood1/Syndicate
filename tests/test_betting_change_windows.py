"""Betting changes load only in scheduled windows (user 2026-11-18, lane betting-change-windows)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import betting_change as bc  # noqa: E402
import deploy_preflight as dp  # noqa: E402

SCHEDULE = """# windows
Effective from: `2026-11-18T00:00:00Z`
- 2026-11-24T08:00:00Z .. 2026-11-24T13:00:00Z
- 2026-12-08T08:00:00Z .. 2026-12-08T13:00:00Z
- not a window line
- 2026-12-30T13:00:00Z .. 2026-12-30T08:00:00Z
"""
REGISTER = """# register

Classified from: `2026-11-16T18:15:00Z`

| id | kind | loaded_at (UTC) | what changed | deploys.md entry | lane |
|---|---|---|---|---|---|
| BC-001 | yes | 2026-11-17T00:04:38Z | something | 2026-11-17T00:04:20Z | lane-a |
"""


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def test_schedule_parses_only_well_formed_forward_windows():
    w = bc.parse_windows(SCHEDULE)
    assert w == [(utc("2026-11-24T08:00:00Z"), utc("2026-11-24T13:00:00Z")),
                 (utc("2026-12-08T08:00:00Z"), utc("2026-12-08T13:00:00Z"))]


def test_window_is_start_inclusive_end_exclusive():
    w = bc.parse_windows(SCHEDULE)
    assert bc.window_at(utc("2026-11-24T08:00:00Z"), w)
    assert bc.window_at(utc("2026-11-24T12:59:59Z"), w)
    assert bc.window_at(utc("2026-11-24T13:00:00Z"), w) is None
    assert bc.next_window(utc("2026-11-24T13:00:00Z"), w)[0] == utc("2026-12-08T08:00:00Z")


def test_refusal_outside_unless_a_recorded_exception_and_an_empty_schedule_fails_closed():
    w = bc.parse_windows(SCHEDULE)
    assert bc.window_refusal(utc("2026-11-24T09:00:00Z"), w) is None
    msg = bc.window_refusal(utc("2026-11-18T18:00:00Z"), w)
    assert msg and "outside every betting-change window" in msg and "2026-11-24 08:00" in msg
    assert bc.window_refusal(utc("2026-11-18T18:00:00Z"), w, "revert of BC-050") is None
    assert "no future window" in bc.window_refusal(utc("2027-06-01T00:00:00Z"), w)
    assert bc.window_refusal(utc("2026-11-24T09:00:00Z"), []) is not None


def _cli(tmp_path: Path, *args: str) -> int:
    reg, win = tmp_path / "reg.md", tmp_path / "win.md"
    if not reg.exists():
        reg.write_text(REGISTER, encoding="utf-8")
        win.write_text(SCHEDULE, encoding="utf-8")
        (tmp_path / "deploys.md").write_text("", encoding="utf-8")
    return bc.main(["--register", str(reg), "--deploys", str(tmp_path / "deploys.md"), "--windows", str(win), *args])


def test_register_refuses_an_out_of_window_yes_and_records_the_exception(tmp_path):
    with pytest.raises(SystemExit):
        _cli(tmp_path, "add", "--kind", "yes", "--loaded-at", "2026-11-18T18:00:00Z", "--what", "x",
             "--deploy", "2026-11-18 17:59:00Z", "--lane", "l")
    assert _cli(tmp_path, "add", "--kind", "yes", "--loaded-at", "2026-11-18T18:00:00Z", "--what", "kill switch",
                "--deploy", "2026-11-18 17:59:00Z", "--lane", "l", "--outside-window", "risk reduction") == 0
    assert "[OUTSIDE WINDOW: risk reduction]" in (tmp_path / "reg.md").read_text(encoding="utf-8")
    assert _cli(tmp_path, "add", "--kind", "yes", "--loaded-at", "2026-11-24T09:00:00Z", "--what", "batch",
                "--deploy", "2026-11-24 08:59:00Z", "--lane", "l") == 0
    assert _cli(tmp_path, "add", "--kind", "no", "--deploy", "2026-11-18 19:00:00Z", "--what", "display") == 0


def test_register_refuses_resolving_a_pending_yes_outside_a_window(tmp_path):
    assert _cli(tmp_path, "add", "--kind", "yes", "--pending", "refresh-worker", "--what", "queued",
                "--deploy", "2026-11-20 10:00:00Z", "--lane", "l") == 0
    with pytest.raises(SystemExit):
        _cli(tmp_path, "resolve", "BC-002", "--loaded-at", "2026-11-20T11:00:00Z")
    assert _cli(tmp_path, "resolve", "BC-002", "--loaded-at", "2026-11-24T08:30:00Z") == 0


def test_cli_window_status_exit_codes(tmp_path):
    assert _cli(tmp_path, "window", "--at", "2026-11-24T08:30:00Z") == 0
    assert _cli(tmp_path, "window", "--at", "2026-11-18T18:00:00Z") == 1


def test_preflight_refuses_a_declared_betting_change_outside_a_window(tmp_path):
    win = tmp_path / "win.md"
    win.write_text(SCHEDULE, encoding="utf-8")
    outside, inside = utc("2026-11-18T18:00:00Z"), utc("2026-11-24T09:00:00Z")
    assert dp.betting_window_problem("", "", outside, win)[0] is None          # undeclared: not checked
    assert dp.betting_window_problem("no", "", outside, win)[0] is None
    problem, detail = dp.betting_window_problem("yes", "", outside, win)
    assert problem and detail["in_window"] is False
    assert dp.betting_window_problem("yes", "", inside, win)[0] is None
    problem, detail = dp.betting_window_problem("yes", "revert of BC-050", outside, win)
    assert problem is None and detail["outside_window_reason"] == "revert of BC-050"
    assert dp.EXIT_OUTSIDE_WINDOW == 8


def test_loads_before_the_rule_took_effect_are_not_checked():
    w = bc.parse_windows(SCHEDULE)
    eff = bc.parse_effective(SCHEDULE)
    assert eff == utc("2026-11-18T00:00:00Z")
    assert bc.window_refusal(utc("2026-11-17T06:01:00Z"), w, "", eff) is None
    assert bc.window_refusal(utc("2026-11-18T06:01:00Z"), w, "", eff) is not None
