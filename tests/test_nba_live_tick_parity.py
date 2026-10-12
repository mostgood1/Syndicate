"""NBA live-lens tick parity, the in-repo half (lane nba-live-tick-native, 2026-10-12).

The gate of record is scripts/nba_live_tick_parity.py on the fleet: the vendored tick recorded against live games,
the port replayed on the same network tape and on its own copy of the same files (deploys.md). This keeps one of those
recordings in the suite. The fixture holds the tape, ONLY the data files the vendored tick opened, and the vendored
tick's output (return value + every file it wrote). The test runs the PORT on them and requires every leaf equal,
then plants a one-leaf change and requires the comparison to find it -- a 0-diff result means something only if a
1-diff result is reported. It does not import the vendored app, so it keeps working once the vendor tree is gone.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "nba_live_tick_parity.py"
FIXTURES = sorted((ROOT / "tests" / "fixtures" / "nba_live_tick").glob("*/tape.json"))


@pytest.mark.parametrize("tape", FIXTURES, ids=lambda p: p.parent.name)
def test_port_replays_the_vendored_tick_exactly(tape: Path, tmp_path: Path):
    fx = tape.parent
    date = json.loads(tape.read_text(encoding="utf-8"))["date"]
    data, ll = tmp_path / "data", tmp_path / "ll"
    shutil.copytree(fx / "data", data)
    shutil.copytree(fx / "live_lens", ll)
    out = tmp_path / "port.json"
    r = subprocess.run(
        [sys.executable, str(HARNESS), "replay", "--arm", "port", "--date", date, "--data-root", str(data),
         "--live-lens-dir", str(ll), "--tape", str(tape), "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert r.returncode == 0, r.stdout + r.stderr[-4000:]
    vendored = fx / "vendored_output.json"
    same = subprocess.run([sys.executable, str(HARNESS), "compare", str(vendored), str(out)], capture_output=True, text=True, cwd=ROOT)
    report = json.loads(same.stdout)
    assert same.returncode == 0 and report["diffs"] == 0, report["first_diffs"]
    assert report["leaves"] > 100 and report["files"], report  # a real tick: it wrote JSONL and returned games
    planted = subprocess.run([sys.executable, str(HARNESS), "compare", str(vendored), str(out), "--plant"], capture_output=True, text=True, cwd=ROOT)
    assert planted.returncode == 0 and json.loads(planted.stdout)["diffs"] >= 1, planted.stdout


def test_fixture_present():
    """The suite must actually hold a recording; an empty glob would make the parametrized test vanish silently."""
    assert FIXTURES, "no tests/fixtures/nba_live_tick/*/tape.json"
