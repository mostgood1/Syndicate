"""Situational pace/efficiency measurement, and proof it can DETECT an effect.

**A TABLE THAT REPORTS "FLAT" IS ONLY MEANINGFUL IF IT WOULD REPORT "NOT FLAT"
ON A REAL EFFECT.** The first fixture written for this was degenerate -- the
margin ran away past 20 so only the blowout bucket populated, and every shot
landed on a 3 -- so it exercised the code and validated nothing. That is the
same vacuous-check failure as `url.count("/sports/") == 1`, hit a third time in
one day, and it is why the injection test below exists.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

import scripts.analyze_situational_pace as situational
from syndicate.features.shared.basketball_momentum_artifacts import momentum_events_path


def _game(close_late_multiplier: float, seed: int = 0) -> dict:
    """A game whose margin OSCILLATES near zero, with pace optionally inflated
    when close and late. A runaway margin populates only one bucket and tests
    nothing."""
    rng = random.Random(seed)
    pressure, scoring = [], []
    poss = t = 0.0
    margin = 0.0
    while t < 2400:
        _, _, left = situational.period_bounds("wnba", t)
        close_late = abs(margin) < 5 and left < 120
        step = (12.0 / close_late_multiplier) if close_late else 12.0
        poss += 1.0
        sign = 1.0 if margin <= 0 else -1.0
        kind = "shot_attempt_3" if rng.random() < 0.35 else "shot_attempt_2"
        pressure.append({"clock_seconds": t, "possession_index": poss, "sign": sign,
                         "weight": 1.0, "type": kind,
                         "team": "IND" if sign > 0 else "NYL"})
        if rng.random() < 0.45:
            pts = 3.0 if kind == "shot_attempt_3" else 2.0
            scoring.append({"clock_seconds": t, "sign": sign, "weight": pts})
            margin += sign * pts
        t += step
    return {"pressure": pressure, "narrator": scoring, "home_tri": "IND", "away_tri": "NYL"}


def _write(tmp_path: Path, close_late_multiplier: float, games: int = 25) -> Path:
    path = momentum_events_path(tmp_path, league_code="wnba", date_str="2026-05-01")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"games": {f"g{i}": _game(close_late_multiplier, seed=i) for i in range(games)}}))
    return tmp_path


def _run(root: Path, capsys) -> str:
    situational.main(["--league", "wnba", "--start", "2026-05-01",
                      "--end", "2026-05-01", "--data-root", str(root)])
    return capsys.readouterr().out


def test_it_detects_an_injected_pace_effect(tmp_path, capsys) -> None:
    """**THE FALSIFICATION.** 3x pace when close and late must show up as a
    ~3x spread, and in the right cell."""
    out = _run(_write(tmp_path, close_late_multiplier=3.0), capsys)
    assert "PACE_SPREAD" in out
    ratio = float(out.split("PACE_SPREAD")[1].split("ratio=")[1].split("x")[0])
    assert ratio > 2.0, f"a 3x injected effect must survive measurement, got {ratio}"
    assert "margin=0-5 left=0-120s" in out, "and be located in the close+late cell"


def test_it_reports_flat_when_there_is_no_effect(tmp_path, capsys) -> None:
    """The other direction. A table that always says 'not flat' is as useless as
    one that always says 'flat'."""
    out = _run(_write(tmp_path, close_late_multiplier=1.0), capsys)
    ratio = float(out.split("PACE_SPREAD")[1].split("ratio=")[1].split("x")[0])
    assert ratio < 1.5, f"no injected effect must read as flat, got {ratio}"


def test_team_shooting_profile_recovers_the_injected_three_share(tmp_path, capsys) -> None:
    out = _run(_write(tmp_path, close_late_multiplier=1.0), capsys)
    shares = [float(line.split("three_share=")[1].split()[0])
              for line in out.splitlines() if "three_share=" in line]
    assert shares, "team profiles must be emitted"
    for share in shares:
        assert 0.30 < share < 0.40, f"injected 0.35 must be recovered, got {share}"


def test_no_games_exits_three(tmp_path, capsys) -> None:
    assert situational.main(["--league", "wnba", "--start", "2026-05-01",
                             "--end", "2026-05-01", "--data-root", str(tmp_path)]) == 3


def test_pooled_estimators_are_not_medians_of_per_window_ratios() -> None:
    """**THE STATISTIC ITSELF.** The first season run reported ppp=1.031 in three
    unrelated cells and ft_share=0.286 (=2/7) in every late cell -- agreement
    that looked measured and was an artifact of taking a MEDIAN over ~4-possession
    windows, whose ratios live on a coarse lattice. Free throws were worse: most
    windows have none, so a median reads 0.000 until the zero share crosses one
    half, then jumps.

    This pins the fix directly. A cell where 60% of windows are scoreless and
    40% score heavily has a per-window median of 0, and a real pooled rate."""
    cell = {"windows": 100.0, "poss": 400.0, "points": 480.0, "ft": 60.0, "fga": 240.0}
    assert situational._pace(cell) == pytest.approx(4.0)
    assert situational._ppp(cell) == pytest.approx(1.2)
    assert situational._ft_share(cell) == pytest.approx(0.2)

    empty = {"windows": 0.0, "poss": 0.0, "points": 0.0, "ft": 0.0, "fga": 0.0}
    assert situational._pace(empty) == 0.0
    assert situational._ppp(empty) == 0.0
    assert situational._ft_share(empty) == 0.0


def test_free_throw_share_survives_zero_inflation(tmp_path, capsys) -> None:
    """A median would report 0.000 here; the pooled rate must not."""
    pressure, scoring = [], []
    poss = t = 0.0
    while t < 2400:
        poss += 1.0
        # Every fifth minute is a free-throw burst; the rest are field goals.
        kind = "free_throw" if int(t // 60) % 5 == 4 else "shot_attempt_2"
        pressure.append({"clock_seconds": t, "possession_index": poss, "sign": 1.0,
                         "weight": 1.0, "type": kind, "team": "IND"})
        scoring.append({"clock_seconds": t, "sign": 1.0 if int(t) % 2 else -1.0,
                        "weight": 2.0})
        t += 12.0
    path = momentum_events_path(tmp_path, league_code="wnba", date_str="2026-05-01")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"games": {
        f"g{i}": {"pressure": pressure, "narrator": scoring,
                  "home_tri": "IND", "away_tri": "NYL"} for i in range(25)}}))

    out = _run(tmp_path, capsys)
    shares = [float(line.split("ft_share=")[1].split()[0])
              for line in out.splitlines() if "CELL " in line]
    assert shares, "cells must be emitted"
    assert max(shares) > 0.05, (
        f"one minute in five is all free throws; a pooled share must see it, got {shares}")
