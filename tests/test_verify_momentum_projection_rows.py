"""The season-scale leakage check, and proof it can fail.

A check that reports PASS on real data is only worth something if it would have
said FAIL on leaking data. That is the whole content of this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.verify_momentum_projection_rows as verify
from syndicate.features.shared.basketball_momentum_artifacts import momentum_events_path


def _rows(n: int, seed: int = 0):
    pressure, scoring = [], []
    for i in range(n):
        t = i * 11.0
        sign = 1.0 if ((i + seed) // 4) % 2 == 0 else -1.0
        pressure.append({"clock_seconds": t, "possession_index": i * 0.72,
                         "sign": sign, "weight": 1.0})
        if i % 3 == 0:
            scoring.append({"clock_seconds": t, "possession_index": i * 0.72,
                            "sign": sign, "weight": 2.0})
    return pressure, scoring


@pytest.fixture
def season(tmp_path: Path) -> Path:
    for day, count in (("2026-05-01", 2), ("2026-05-02", 3)):
        games = {}
        for g in range(count):
            p, s = _rows(220, seed=g)
            games[f"40190{day[-2:]}{g}"] = {"pressure": p, "narrator": s,
                                            "home_tri": "IND", "away_tri": "NYL"}
        path = momentum_events_path(tmp_path, league_code="wnba", date_str=day)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"league": "wnba", "date": day, "games": games}))
    return tmp_path


def _run(root: Path) -> int:
    return verify.main(["--league", "wnba", "--start", "2026-05-01",
                        "--end", "2026-05-02", "--data-root", str(root)])


def test_a_clean_season_passes(season, capsys) -> None:
    assert _run(season) == 0
    out = capsys.readouterr().out
    assert "state_fields_that_MOVED=0 PASS" in out


def test_an_injected_leak_is_caught(season, monkeypatch, capsys) -> None:
    """**THE FALSIFICATION.** Both sides of the comparison run the same code on
    the same rows, so PASS is worthless until FAIL is demonstrated."""
    import syndicate.features.shared.basketball_projection_rows as pr

    original = pr.build_projection_rows

    def leaky(pressure, scoring, **kwargs):
        rows = original(pressure, scoring, **kwargs)
        for row in rows:
            row["state_leaked_total"] = sum(abs(r["weight"]) for r in scoring)
        return rows

    monkeypatch.setattr(verify, "build_projection_rows", leaky)
    assert _run(season) == 5
    assert "FAIL -- DO NOT FIT ON THIS" in capsys.readouterr().out


def test_no_captured_data_exits_three_not_zero(tmp_path) -> None:
    """A silent empty run is how a broken read is mistaken for a clean season."""
    assert _run(tmp_path) == 3


def test_it_reports_the_shape_a_projection_must_live_inside(season, capsys) -> None:
    _run(season)
    out = capsys.readouterr().out
    assert "PACE per_min" in out
    assert "POSSESSIONS_AT_END" in out
    # A truncated forward window looks like a low-scoring one; the share of
    # complete windows is what says whether a naive fit would learn that.
    assert "FWD_600_COMPLETE" in out


def test_the_verify_gate_is_inert_without_its_env_var(tmp_path, monkeypatch) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pbm_v", "scripts/poll_basketball_momentum.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.delenv("SYNDICATE_WNBA_MOMENTUM_VERIFY", raising=False)
    assert mod.maybe_start_verify("wnba", tmp_path) is False
