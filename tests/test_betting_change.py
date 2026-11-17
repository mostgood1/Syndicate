"""scripts/betting_change.py -- the register that restarts the scale-up gate's clock (todo #815)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "betting_change.py"
_spec = importlib.util.spec_from_file_location("betting_change", _PATH)
B = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = B
_spec.loader.exec_module(B)

REGISTER = """# register

Classified from: `2026-11-16T18:15:00Z`

| id | kind | loaded_at (UTC) | what changed | deploys.md entry | lane |
|---|---|---|---|---|---|
| BC-001 | yes | 2026-11-16T18:15:23Z | NBA exit gate | 2026-11-16T18:15:23Z | lpeg |
| BC-002 | no | 2026-11-16T21:15:00Z | a reading | 2026-11-16T21:15:00Z | other |
| BC-003 | yes | 2026-11-17T00:04:38Z | NCAAB total calibration | 2026-11-17T00:04:20Z | ncaab |
"""

DEPLOYS = """# deploys

## 2026-11-16 17:00:00Z (old) -- FLEET ff a -> b: before coverage
- body

## 2026-11-16 18:15:23Z (12:15 PM CST) -- READING: NBA gate LOADED in live-odds-worker
- body

## 2026-11-16 21:15:00Z (3:15 PM CST) -- READING, no deploy: something measured
- body

## 2026-11-17 00:04:20Z -- FLEET ff x -> y + refresh-worker TERM: calibration
- body

## 2026-11-17 00:20:21Z -- DEPLOY (ff only, no restart): a log line allowlisted
- body

## 2026-11-17 01:00Z -- FLEET ff y -> z: tagged in its own body
- betting change: no

## 2026-11-17 02:00:00Z -- FLEET env: tagged yes but not registered
- betting change: yes

## 2026-11-17 03:00:00Z -- READING, no deploy: a measurement only
- body

## 2026-11-17 04:00:00Z -- READING, no deploy: live-odds-worker came up by its ROUTINE RECYCLE
- body
"""


# --- timestamps -------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, want",
    [
        ("2026-11-17 00:04:20Z", "2026-11-17T00:04:20Z"),
        ("2026-11-17T00:04Z", "2026-11-17T00:04:00Z"),
        ("2026-11-17T00:04:20.467Z", "2026-11-17T00:04:20Z"),
        ("2026-11-17T00:04:20+00:00", "2026-11-17T00:04:20Z"),
    ],
)
def test_normalize_ts(raw, want):
    assert B.normalize_ts(raw) == want


@pytest.mark.parametrize("raw", ["2026-11-17", "2026-11-17 25:00Z", "11/17 00:04", "2026-11-17T00:04:20-06:00"])
def test_normalize_ts_refuses_what_is_not_utc(raw):
    with pytest.raises(ValueError):
        B.normalize_ts(raw)


def test_parse_utc_takes_nanosecond_fractions():
    assert B.parse_utc("2026-11-16T04:24:35.729507346Z") == datetime(2026, 11, 16, 4, 24, 35, 729507, tzinfo=timezone.utc)
    assert B.parse_utc("") is None and B.parse_utc("garbage") is None


# --- the register -----------------------------------------------------------------


def test_parse_register_reads_rows_and_coverage():
    changes, coverage = B.parse_register(REGISTER)
    assert [c.id for c in changes] == ["BC-001", "BC-002", "BC-003"]
    assert coverage == "2026-11-16T18:15:00Z"
    assert changes[2].deploy == "2026-11-17T00:04:20Z" and changes[2].loaded_at == "2026-11-17T00:04:38Z"


def test_parse_register_refuses_a_bad_kind_or_duplicate_id():
    with pytest.raises(ValueError):
        B.parse_register(REGISTER.replace("| BC-002 | no |", "| BC-002 | maybe |"))
    with pytest.raises(ValueError):
        B.parse_register(REGISTER.replace("| BC-003 |", "| BC-001 |"))


def test_the_clock_starts_at_the_latest_LOADED_yes_not_the_latest_row_or_ff():
    changes, _ = B.parse_register(REGISTER)
    clock = B.clock_start(changes)
    assert clock.start == "2026-11-17T00:04:38Z"  # the load, not the 00:04:20Z ff
    assert clock.change.id == "BC-003" and not clock.pending
    # A later NO does not move it.
    more = [*changes, B.Change("BC-004", "no", "2026-11-17T05:00:00Z", "x", "2026-11-17T05:00:00Z", "z")]
    assert B.clock_start(more).start == "2026-11-17T00:04:38Z"


def test_a_pending_yes_holds_the_count_at_zero():
    changes, _ = B.parse_register(REGISTER)
    pending = B.Change("BC-004", "yes", "pending:live-odds-worker", "on disk", "2026-11-17T05:00:00Z", "z")
    now = datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)
    clock = B.clock_start([*changes, pending], now=now)
    assert clock.pending and clock.start == "2026-11-17T06:00:00Z" and clock.change.id == "BC-004"
    assert "PENDING" in B.describe_clock(clock)


def test_no_yes_means_no_clock():
    assert B.clock_start([B.Change("BC-001", "no", "2026-11-17T00:00:00Z", "x", "", "")]) is None


def test_append_and_replace_rows_keep_the_table_parseable():
    changes, _ = B.parse_register(REGISTER)
    new = B.Change(B.next_id(changes), "yes", "pending:refresh-worker", "a | piped thing", "2026-11-17T05:00:00Z", "l")
    assert new.id == "BC-004"
    text = B.append_row(REGISTER, new)
    again, _ = B.parse_register(text)
    assert [c.id for c in again][-1] == "BC-004" and again[-1].what == "a / piped thing"  # a pipe would split the cell
    resolved = B.Change("BC-004", "yes", "2026-11-17T06:01:00Z", "a / piped thing", new.deploy, "l")
    final, _ = B.parse_register(B.replace_row(text, resolved))
    assert final[-1].loaded_at == "2026-11-17T06:01:00Z" and not final[-1].pending


# --- coverage of deploys.md ------------------------------------------------------


def test_deploy_like_filter():
    assert B.is_deploy_like("2026-11-17 00:04:20Z -- FLEET ff x -> y + refresh-worker TERM")
    assert not B.is_deploy_like("2026-11-17 03:00:00Z -- READING, no deploy: a measurement only")
    # A load that hides in a reading is still a load.
    assert B.is_deploy_like("2026-11-16 01:44:49Z READING -- live-odds-worker came up by its ROUTINE RECYCLE, not a deploy")


def test_candidates_lists_only_unclassified_loads_since_coverage():
    changes, coverage = B.parse_register(REGISTER)
    found = {row["deploy"]: row["why"] for row in B.candidates(changes, DEPLOYS, coverage)}
    assert found == {
        "2026-11-17T00:20:21Z": "unclassified",
        "2026-11-17T02:00:00Z": "tagged yes in deploys.md but no register row (needs its load time)",
        "2026-11-17T04:00:00Z": "unclassified",
    }
    # 17:00 is before coverage; 18:15 and 00:04 are referenced; 21:15 and 03:00 are not deploy-like;
    # 01:00 carries `betting change: no` in its own body.


# --- the CLI ------------------------------------------------------------------------


def _files(tmp_path):
    reg = tmp_path / "betting_changes.md"
    reg.write_text(REGISTER, encoding="utf-8")
    dep = tmp_path / "deploys.md"
    dep.write_text(DEPLOYS, encoding="utf-8")
    return ["--register", str(reg), "--deploys", str(dep)], reg


def test_cli_add_resolve_and_clock(tmp_path, capsys):
    base, reg = _files(tmp_path)
    assert B.main([*base, "add", "--kind", "yes", "--pending", "live-odds-worker", "--what", "gate",
                   "--deploy", "2026-11-17 00:20:21Z", "--lane", "l"]) == 0
    assert "count is 0" in capsys.readouterr().out
    assert B.main([*base, "resolve", "BC-004", "--loaded-at", "2026-11-17T06:01:00Z"]) == 0
    assert B.main([*base, "clock"]) == 0
    assert "starts 2026-11-17T06:01:00Z" in capsys.readouterr().out
    changes, _ = B.parse_register(reg.read_text(encoding="utf-8"))
    assert changes[-1].deploy == "2026-11-17T00:20:21Z" and changes[-1].loaded_at == "2026-11-17T06:01:00Z"


def test_cli_refuses_a_yes_without_a_load_and_a_double_classification(tmp_path):
    base, _ = _files(tmp_path)
    with pytest.raises(SystemExit):
        B.main([*base, "add", "--kind", "yes", "--what", "x", "--deploy", "2026-11-17 05:00Z"])
    with pytest.raises(SystemExit):
        B.main([*base, "add", "--kind", "no", "--what", "x", "--deploy", "2026-11-17 00:04:20Z"])


def test_cli_candidates_exits_nonzero_while_anything_is_unclassified(tmp_path, capsys):
    base, _ = _files(tmp_path)
    assert B.main([*base, "candidates"]) == 1
    assert "3 unclassified deploy entries since 2026-11-16T18:15:00Z" in capsys.readouterr().out


# --- the session-start digest line (lane betting-change-session-check) ----------------

_NOW = datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)


def test_digest_is_silent_when_the_register_is_whole():
    changes, coverage = B.parse_register(REGISTER)
    classified = [
        *changes,
        *(B.Change(f"BC-1{i:02d}", "no", ts, "x", ts, "l") for i, ts in enumerate(
            ["2026-11-17T00:20:21Z", "2026-11-17T02:00:00Z", "2026-11-17T04:00:00Z"]
        )),
    ]
    assert B.digest_line(classified, coverage, DEPLOYS, now=_NOW) == ""


def test_digest_names_unclassified_loads_with_the_newest():
    changes, coverage = B.parse_register(REGISTER)
    line = B.digest_line(changes, coverage, DEPLOYS, now=_NOW)
    assert line.startswith("BETTING CHANGES: 3 deploys.md load(s) unclassified, newest 2026-11-17T04:00Z")
    assert line.endswith("run: python scripts/betting_change.py candidates")
    assert len(line) <= B.DIGEST_CAP


def test_digest_flags_a_pending_load_only_once_it_is_stale():
    fresh = B.Change("BC-010", "yes", "pending:live-odds-worker", "x", "2026-11-17T00:00:00Z", "l")
    stale = B.Change("BC-011", "yes", "pending:refresh-worker", "y", "2026-11-16T12:00:00Z", "l")
    assert B.digest_line([fresh], None, None, now=_NOW) == ""  # 6 h: a recycle may still be coming
    line = B.digest_line([fresh, stale], None, None, now=_NOW)
    assert "pending its load: BC-011 18 h" in line and "BC-010" not in line


def test_digest_stays_under_its_cap_with_many_stale_pendings():
    many = [B.Change(f"BC-{i:03d}", "yes", "pending:r", "x" * 50, "2026-11-10T00:00:00Z", "l") for i in range(1, 9)]
    line = B.digest_line(many, None, None, now=_NOW)
    assert "+5 more" in line and len(line) <= B.DIGEST_CAP and line.endswith("candidates")


def test_cli_digest_never_fails_and_says_when_the_register_is_broken(tmp_path, capsys):
    base, reg = _files(tmp_path)
    assert B.main([*base, "digest"]) == 0
    assert "3 deploys.md load(s) unclassified" in capsys.readouterr().out
    reg.write_text(REGISTER.replace("| BC-002 | no |", "| BC-002 | maybe |"), encoding="utf-8")
    assert B.main([*base, "digest"]) == 0
    assert "does not parse" in capsys.readouterr().out
    missing = ["--register", str(tmp_path / "none.md"), "--deploys", str(tmp_path / "none2.md")]
    assert B.main([*missing, "digest"]) == 0
    assert capsys.readouterr().out == ""
