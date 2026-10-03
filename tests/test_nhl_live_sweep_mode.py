"""NHL's refresh step runs FAST in a live sweep unless its generation is due (lane `nhl-live-sweep-fast`).

Measured on the fleet 10-02/03: `nhl_oddsapi_refresh` was 6,291 of ~7,000 step-seconds
across the 8 slowest full live sweeps -- full owned generation on every live sweep.
"""
from __future__ import annotations

import argparse
import os
import time

import pytest

from scripts import refresh_odds_sources as ros

DATE = "2026-10-03"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(ros, "_local_source_artifact_root", lambda slug: tmp_path)
    monkeypatch.delenv("SYNDICATE_NHL_LIVE_FULL_GENERATION_SECONDS", raising=False)
    return tmp_path


def _predictions(root, age_seconds):
    path = root / "data" / "processed" / f"predictions_{DATE}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))


def _command(phase):
    step = ros._build_nhl_steps(argparse.Namespace(date=DATE, phase=phase))[0]
    assert step.name == "nhl_oddsapi_refresh" and step.phases == ("pregame", "live")
    return list(step.command)


def _is_fast(cmd):
    return "--mode" in cmd and cmd[cmd.index("--mode") + 1] == "fast"


def test_reachability_live_with_fresh_predictions_is_fast(root):
    _predictions(root, age_seconds=600)
    assert _is_fast(_command("live")) is True
    _predictions(root, age_seconds=2400)
    assert _is_fast(_command("live")) is False, "generation due after the pregame cadence"


def test_missing_predictions_always_generate(root):
    assert _is_fast(_command("live")) is False


def test_pregame_and_combined_sweeps_are_unchanged(root):
    _predictions(root, age_seconds=60)
    assert _is_fast(_command("pregame")) is False
    assert _is_fast(_command("all")) is False


def test_zero_restores_full_on_every_live_sweep(root, monkeypatch):
    _predictions(root, age_seconds=60)
    monkeypatch.setenv("SYNDICATE_NHL_LIVE_FULL_GENERATION_SECONDS", "0")
    assert _is_fast(_command("live")) is False
