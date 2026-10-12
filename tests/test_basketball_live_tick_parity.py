"""NBA / WNBA live-lens tick parity, the in-repo half (lane nba-live-tick-native, 2026-10-12).

The gate of record is scripts/basketball_live_tick_parity.py on the fleet: the vendored tick recorded against live games,
the port replayed on the same network tape and on its own copy of the same files (deploys.md). This keeps one of those
recordings in the suite, cut down by `basketball_live_tick_parity.py reduce` (the tape, and only the opened files dated that
day and under 1 MB), with the vendored tick's output ON THAT SAME REDUCED ROOT (return value + every file it wrote). The test runs the PORT on them and requires every leaf equal,
then plants a one-leaf change and requires the comparison to find it -- a 0-diff result means something only if a
1-diff result is reported. It does not import the vendored app, so it keeps working once the vendor tree is gone.
"""
from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts" / "basketball_live_tick_parity.py"
FIXTURES = sorted((ROOT / "tests" / "fixtures" / "basketball_live_tick").glob("*/tape.json.gz"))


@pytest.mark.parametrize("tape", FIXTURES, ids=lambda p: p.parent.name)
def test_port_replays_the_vendored_tick_exactly(tape: Path, tmp_path: Path):
    fx = tape.parent
    meta = json.loads(gzip.decompress(tape.read_bytes()))
    date, league = meta["date"], meta["league"]
    data, ll = tmp_path / "data", tmp_path / "ll"
    shutil.copytree(fx / "data", data)
    shutil.copytree(fx / "live_lens", ll)
    out = tmp_path / "port.json"
    r = subprocess.run(
        [sys.executable, str(HARNESS), "replay", "--league", league, "--arm", "port", "--date", date, "--data-root", str(data),
         "--live-lens-dir", str(ll), "--tape", str(tape), "--out", str(out), "--allow-misses"],
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
    leagues = {json.loads(gzip.decompress(t.read_bytes()))["league"] for t in FIXTURES}
    assert leagues == {"nba", "wnba"}, (leagues, "need one fixture per league under tests/fixtures/basketball_live_tick/")
