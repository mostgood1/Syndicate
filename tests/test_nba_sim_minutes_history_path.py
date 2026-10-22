"""NBA SmartSim minutes on the rotation-HISTORY path (lane nba-sim-minutes-history-path, todo #723).

`scripts/nba_sim_minutes_audit.py --history` replays the REAL `_rotation_sim_minutes_from_history_local` on a frozen
engine-input frame, with spies on the module view, and splits each pool player's minutes into MAPPED (his stint share),
LEFTOVER (his share of the minutes of history players missing from today's pool), BLEND (the regularizer's pull toward
roll minutes) and CAPS. These tests pin that the split closes to the function's own output, that a history player
missing from the pool produces LEFTOVER minutes that reach zero-stint pool players, and that a side whose replay does
not reproduce production's `_sim_min` is dropped, not split.
"""
from __future__ import annotations

import csv
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared import basketball_props_smart_sim as b
from syndicate.features.shared import nba_season_phase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import nba_sim_minutes_audit as audit  # noqa: E402

SLATE, ASOF, HIST_DAY = "2026-10-22", "2026-10-21", "2026-10-20"
# id: (name, stint minutes in the history game). Player 8 played in the window but is NOT in today's pool.
HIST = {1: ("Bos Alpha", 40), 2: ("Bos Bravo", 38), 3: ("Bos Charlie", 40), 4: ("Bos Delta", 34), 5: ("Bos Echo", 32),
        6: ("Bos Foxtrot", 24), 7: ("Bos Golf", 18), 8: ("Bos Gone", 14)}
# (on-court ids, minutes): 48 minutes, 5 on court, giving every id exactly its HIST minutes; 5 units avoid player 8.
UNITS = [((1, 2, 3, 4, 5), 12), ((1, 2, 3, 4, 6), 8), ((1, 2, 3, 5, 7), 6), ((1, 2, 4, 6, 7), 4), ((2, 3, 5, 6, 7), 4),
         ((1, 3, 4, 5, 8), 6), ((1, 2, 6, 7, 8), 4), ((3, 4, 5, 6, 8), 4)]
POOL = [HIST[i][0] for i in range(1, 8)] + ["Bos Deep One", "Bos Deep Two"]   # two zero-stint pool players


def _write_history(processed: Path) -> None:
    rows = [{"team": "BOS", "date": HIST_DAY, "duration_sec": m * 60, "lineup_player_ids": ";".join(map(str, ids))}
            for ids, m in UNITS]
    pd.DataFrame(rows).to_csv(processed / "rotation_stints_history.csv", index=False)
    checks = processed / "rotation_stints"
    checks.mkdir(parents=True, exist_ok=True)
    with (checks / f"player_checks_{HIST_DAY}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "team", "player_id", "player_name"])
        w.writeheader()
        for pid, (name, _m) in HIST.items():
            w.writerow({"date": HIST_DAY, "team": "BOS", "player_id": pid, "player_name": name})


def _pool_frame() -> pd.DataFrame:
    rows = []
    for i, name in enumerate(POOL):
        m = HIST[i + 1][1] if i < 7 else 18.0          # the deep bench carries a last-season roll base
        rows.append({"player_name": name, "team": "BOS", "asof_date": ASOF, "roll5_min": m, "roll10_min": m,
                     "roll3_min": m, "lag1_min": m})
    return pd.DataFrame(rows)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    processed = tmp_path / "nba_source" / "data" / "processed"
    processed.mkdir(parents=True)
    _write_history(processed)

    def same_phase(_slate, **_k):
        ok = lambda d: True  # noqa: E731
        ok.slate_phase = "regular"
        return ok

    monkeypatch.setattr(nba_season_phase, "same_phase_date_filter", same_phase)
    monkeypatch.setattr(b, "_espn_event_id_for_matchup_local", lambda **_k: "")
    return processed


def _production_minutes(processed: Path, frame: pd.DataFrame):
    view = b._build_local_smart_sim_module(processed_root=processed, league_code="nba")
    return b._rotation_sim_minutes_from_history_local(smart_sim_module=view, league_code="nba", team_df=frame,
                                                      date_str=ASOF, home_tri="BOS", away_tri="NYK", team_tri="BOS")


def _freeze(processed: Path, frame: pd.DataFrame, sim_min, *, box: dict) -> None:
    """What production writes: the engine-input frame (with _sim_min), the sim's rotation diag, and the box."""
    frozen = frame.copy()
    frozen["_sim_min"] = np.asarray(sim_min, dtype=float)
    away = frozen.iloc[0:0].copy()
    (processed / "engine_inputs" / SLATE).mkdir(parents=True)
    rec = {"home": "BOS", "away": "NYK", "written_at": f"{SLATE}T12:00:00+00:00",
           "kwargs": {"home_players": frozen, "away_players": away}}
    (processed / "engine_inputs" / SLATE / "BOS_NYK.pkl").write_bytes(pickle.dumps(rec))
    (processed / f"smart_sim_{SLATE}_BOS_NYK.json").write_text(json.dumps(
        {"rotation_minutes": {"home": {"applied": True}, "away": {"applied": False, "reason": "no_recent_history"}}}),
        encoding="utf-8")
    with (processed / "rotation_stints" / f"player_checks_{SLATE}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "team", "player_id", "player_name", "season_type", "box_minutes", "starter"])
        w.writeheader()
        for name, (mins, starter) in box.items():
            w.writerow({"date": SLATE, "team": "BOS", "player_id": "", "player_name": name, "season_type": "regular",
                        "box_minutes": mins, "starter": int(starter)})


def test_decompose_history_closes_and_puts_leftover_on_roll_weights():
    x = np.array([100.0, 90.0, 50.0])           # after a leftover of 40 spread 2:1:1 and a rescale of 1
    y = 0.9 * x + 0.1 * np.array([80.0, 80.0, 80.0])
    z = y + np.array([-1.0, 0.5, 0.5])
    mapped, left, blend, caps = audit.decompose_history(x, y, z, np.array([20.0, 10.0, 10.0]), mapped_minutes=200.0,
                                                        leftover_minutes=40.0, blend=0.1)
    assert np.allclose(left, 0.9 * np.array([20.0, 10.0, 10.0]))
    assert np.allclose(mapped, 0.9 * np.array([80.0, 80.0, 40.0]))
    assert np.allclose(blend, 8.0) and np.allclose(caps, [-1.0, 0.5, 0.5])
    assert np.allclose(mapped + left + blend + caps, z)


def test_history_replay_splits_the_real_function_and_finds_the_leftover(tree):
    frame = _pool_frame()
    sim_min, lineups, _w, diag = _production_minutes(tree, frame)
    assert diag["applied"] and diag["leftover_minutes"] > 0          # player 8 is in the window and not in the pool
    box = {name: (HIST[i + 1][1], i < 5) for i, name in enumerate(POOL[:7])}
    box["Bos Deep One"] = (6, False)                                  # a zero-stint player who PLAYS (returning)
    _freeze(tree, frame, sim_min, box=box)                            # "Bos Deep Two" did not play

    rep = audit.history_replay(tree, [SLATE])
    assert rep["dropped"] == []
    [side] = rep["sides"]
    assert side["max_dev"] == pytest.approx(0.0, abs=1e-9)
    rows = {r["player"]: r for r in side["rows"]}
    for r in rows.values():                                            # the split closes to production's own minutes
        assert r["mapped"] + r["leftover"] + r["blend"] + r["caps"] == pytest.approx(r["sim_min"], abs=1e-9)
    assert rows["Bos Deep Two"]["zero_stint"] and rows["Bos Deep Two"]["mapped"] == pytest.approx(0.0, abs=1e-12)
    assert rows["Bos Deep Two"]["leftover"] > 0.5                      # the leak: a DNP player fed by the leftover
    assert not rows["Bos Alpha"]["zero_stint"]
    sm = audit.history_summary(rep)
    assert sm["dnp_component_per_side"]["leftover"][0] == pytest.approx(rows["Bos Deep Two"]["leftover"])
    assert sm["returning_n"] == 1 and sm["returning"][0]["player"] == "Bos Deep One"


def test_history_replay_drops_a_side_it_does_not_reproduce(tree):
    frame = _pool_frame()
    sim_min, _l, _w, _d = _production_minutes(tree, frame)
    _freeze(tree, frame, np.asarray(sim_min, dtype=float) + np.r_[1.0, -1.0, [0.0] * (len(frame) - 2)], box={})
    rep = audit.history_replay(tree, [SLATE])
    assert rep["sides"] == []
    assert rep["dropped"][0]["reason"] == "does_not_reproduce" and rep["dropped"][0]["max_dev"] == pytest.approx(1.0)
