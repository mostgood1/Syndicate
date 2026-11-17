"""todo #821 F1 (lane nba-game-model-fed-audit, user 2026-11-17 "build F1 behind the switch, default off").

`"feed_game_model": true` in the NBA processed root's `nba_sim_total_inputs.json` makes the pregame job build fall back to
NBA's own column names (`pred_total` / `pred_margin`) when WNBA's (`totals` / `spread_margin`) are missing, so each team's
off_rating comes from the game model's points instead of `baseline_off_rating`. Absent, false, unreadable, or any other
league = today (F0), byte-identical.

Reachability first (model_engine_standard): off != on through the REAL per-game loop and the REAL worker, on the raw AND
the anchored margin, with the audit asserted from the branch that read the columns.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared import basketball_props_smart_sim as bps
from syndicate.features.shared import smart_sim_anchor_refresh as ar
from syndicate.features.shared import smart_sim_tip_freeze as tf

REPO = Path(__file__).resolve().parents[1]
DATE = "2026-11-16"
TIP = datetime(2026, 11, 17, 0, 30, tzinfo=timezone.utc)
NBA_BASELINE = 110.6
PRED_TOTAL, PRED_MARGIN = 226.4, 3.1
FEED_ON = {"feed_game_model": True, "skip_def_subtraction": True}   # the fleet already has skip_def_subtraction


def _num(value):
    try:
        numeric = float(pd.to_numeric(value, errors="coerce"))
        return numeric if np.isfinite(numeric) else None
    except Exception:
        return None


@pytest.fixture(autouse=True)
def _switches(monkeypatch):
    for env in (ar.SWITCH_ENV, ar.MIN_PTS_ENV, tf.SWITCH_ENV, "SYNDICATE_SMART_SIM_REUSE_EXCLUSION_CHECK"):
        monkeypatch.delenv(env, raising=False)


def _switch_file(root: Path, payload) -> None:
    root.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (root / bps.NBA_TOTAL_INPUTS_FILE_LOCAL).write_text(text, encoding="utf-8")


# --- the switch ----------------------------------------------------------------------------------------------------

def test_switch_absent_or_false_or_broken_is_off_and_only_nba_reads_it(tmp_path):
    assert bps._nba_feed_game_model_switch_local(processed_root=tmp_path, league_code="nba") is False
    for payload, want in (({"skip_def_subtraction": True}, False), ({"feed_game_model": False}, False),
                          ("{not json", False), ("[1, 2]", False), ({"feed_game_model": True}, True)):
        _switch_file(tmp_path, payload)
        assert bps._nba_feed_game_model_switch_local(processed_root=tmp_path, league_code="nba") is want, payload
        assert bps._nba_feed_game_model_switch_local(processed_root=tmp_path, league_code="wnba") is False
    assert bps._nba_feed_game_model_switch_local(processed_root=None, league_code="nba") is False


def test_the_other_lanes_loader_is_untouched_by_the_new_key(tmp_path):
    _switch_file(tmp_path, {**FEED_ON, "skip_outs_penalties": False})
    league = bps._league_for_code_local("nba")
    assert bps._nba_total_inputs_switch_local(processed_root=tmp_path, league=league) == {
        "skip_def_subtraction": True, "skip_outs_penalties": False}


# --- the read ------------------------------------------------------------------------------------------------------

def test_on_reads_the_nba_names_and_says_so():
    row = pd.Series({"pred_total": PRED_TOTAL, "pred_margin": PRED_MARGIN})
    off = bps._game_model_points_local(row, _num)
    on = bps._game_model_points_local(row, _num, read_pred_columns=True)
    assert off == (None, None, {"game_model_fed": False, "game_model_columns": ["pred_total", "pred_margin"]})
    assert on == (0.5 * (PRED_TOTAL + PRED_MARGIN), 0.5 * (PRED_TOTAL - PRED_MARGIN),
                  {"game_model_fed": True, "game_model_columns": ["pred_total", "pred_margin"],
                   "game_model_read": ["pred_total", "pred_margin"]})


def test_on_prefers_the_wnba_names_and_leaves_their_audit_unchanged():
    row = pd.Series({"totals": 161.0, "spread_margin": 4.0, "pred_total": 999.0, "pred_margin": -99.0})
    assert bps._game_model_points_local(row, _num, read_pred_columns=True) == bps._game_model_points_local(row, _num)
    assert bps._game_model_points_local(row, _num)[:2] == (82.5, 78.5)


def test_on_fills_one_missing_half_from_the_nba_name():
    row = pd.Series({"totals": 220.0, "pred_margin": 2.0}, dtype=object)
    home_mu, away_mu, audit = bps._game_model_points_local(row, _num, read_pred_columns=True)
    assert (home_mu, away_mu) == (111.0, 109.0) and audit["game_model_read"] == ["totals", "pred_margin"]
    assert bps._game_model_points_local(row, _num)[2]["game_model_fed"] is False


# --- the real per-game loop ----------------------------------------------------------------------------------------

def _seed(root: Path, *, header: str = "pred_total,pred_margin", values: str = f"{PRED_TOTAL},{PRED_MARGIN}",
          home: str = "Washington Wizards", away: str = "Milwaukee Bucks", switch=None) -> tuple[Path, Path]:
    processed, raw = root / "data" / "processed", root / "data" / "raw"
    processed.mkdir(parents=True)
    raw.mkdir(parents=True)
    (processed / f"predictions_{DATE}.csv").write_text(
        f"home_team,visitor_team,{header},commence_time,total,home_spread\n"
        f"{home},{away},{values},2026-11-17T00:30:00Z,229.5,-3.5\n", encoding="utf-8")
    (processed / f"props_predictions_{DATE}.csv").write_text(
        "player_name,team\nKyshawn George,WAS\nGiannis Antetokounmpo,MIL\nA'ja Wilson,LVA\nJonquel Jones,NYL\n",
        encoding="utf-8")
    if switch is not None:
        _switch_file(processed, switch)
    return processed, raw


def _run(processed: Path, raw: Path, *, league: str = "nba") -> list[dict]:
    jobs: list[dict] = []

    def _fake_worker_run(job: dict) -> dict:
        jobs.append(dict(job))
        return {"status": "wrote", "home": job.get("home_tri"), "away": job.get("away_tri")}

    with patch.object(bps, "_smart_sim_worker_run_local", side_effect=_fake_worker_run), \
            patch.object(bps, "_smart_sim_worker_init_local", return_value=None), \
            patch.object(tf, "_now", return_value=TIP - timedelta(hours=3)):
        bps._smart_sim_run_date_local(processed_root=processed, raw_root=raw, date_str=DATE, n_sims=10, seed=None,
                                      max_games=None, overwrite=False, workers=1, league_code=league)
    assert len(jobs) == 1
    return jobs


def test_run_loop_off_vs_on(tmp_path, capsys):
    off = _run(*_seed(tmp_path / "off"))[0]
    assert off["home_off_rtg"] == off["away_off_rtg"] == pytest.approx(NBA_BASELINE)
    assert off["game_model_fed"] is False and "game_model_read" not in off
    assert bps.GAME_MODEL_UNFED_TAG_LOCAL in capsys.readouterr().out

    on = _run(*_seed(tmp_path / "on", switch=FEED_ON))[0]
    assert on["game_model_fed"] is True and on["game_model_read"] == ["pred_total", "pred_margin"]
    pace = on["matchup_pace"]
    assert on["home_off_rtg"] == pytest.approx(0.5 * (PRED_TOTAL + PRED_MARGIN) / pace * 100.0)
    assert on["away_off_rtg"] == pytest.approx(0.5 * (PRED_TOTAL - PRED_MARGIN) / pace * 100.0)
    assert (on["home_off_rtg"], on["away_off_rtg"]) != (off["home_off_rtg"], off["away_off_rtg"])
    assert on["off_rtg_from_points"] is False   # NBA keeps it False; skip_def_subtraction decides the def term
    assert bps.GAME_MODEL_UNFED_TAG_LOCAL not in capsys.readouterr().out
    # every other job field is the same
    same = {k: v for k, v in on.items() if k not in ("home_off_rtg", "away_off_rtg", "game_model_fed", "game_model_read", "out_path")}
    assert same == {k: v for k, v in off.items() if k in same}


def test_switch_present_but_false_is_byte_identical_to_absent(tmp_path):
    absent = _run(*_seed(tmp_path / "a"))[0]
    false = _run(*_seed(tmp_path / "b", switch={"feed_game_model": False, "skip_def_subtraction": True}))[0]
    strip = lambda job: {k: v for k, v in job.items() if k != "out_path"}  # noqa: E731
    assert strip(absent) == strip(false)


def test_wnba_ignores_the_switch(tmp_path):
    named = _run(*_seed(tmp_path / "w1", header="totals,spread_margin", values="161,4", home="Las Vegas Aces",
                        away="New York Liberty", switch=FEED_ON), league="wnba")[0]
    assert named["game_model_fed"] is True and "game_model_read" not in named
    nba_names = _run(*_seed(tmp_path / "w2", home="Las Vegas Aces", away="New York Liberty", switch=FEED_ON),
                     league="wnba")[0]
    assert nba_names["game_model_fed"] is False


# --- the real worker: off != on on the raw AND anchored margin -----------------------------------------------------

def _worker_anchor(root: Path, job: dict, *, switch=None) -> dict:
    out_path = root / f"smart_sim_{DATE}_WAS_MIL.json"
    root.mkdir(parents=True, exist_ok=True)
    if switch is not None:
        _switch_file(root, switch)
    state = {"date_str": DATE, "n_sims": 10, "seed": 7, "pbp": False, "roster_mode": "historical",
             "league_code": "nba", "props_df": None, "excluded_map": {}, "adv_map": {}, "game_id_map": {},
             "name_to_id": {}, "team_name_to_id": {}}
    engine_out = {"players": {"home": [{"player_name": "Kyshawn George", "player_id": 1}],
                              "away": [{"player_name": "Giannis Antetokounmpo", "player_id": 2}]}}
    with patch.object(bps, "_SMARTSIM_WORKER_STATE", state), \
            patch.object(bps, "_call_source_simulate_smart_game_local",
                         side_effect=lambda **_: json.loads(json.dumps(engine_out))):
        result = bps._smart_sim_worker_run_local({**job, "out_path": str(out_path)})
    assert result["status"] == "wrote", result
    return json.loads(out_path.read_text(encoding="utf-8"))["market_anchor"]


def test_worker_off_vs_on(tmp_path):
    off_job = _run(*_seed(tmp_path / "s_off", switch={"skip_def_subtraction": True}))[0]
    on_job = _run(*_seed(tmp_path / "s_on", switch=FEED_ON))[0]
    off = _worker_anchor(tmp_path / "w_off", off_job, switch={"skip_def_subtraction": True})
    on = _worker_anchor(tmp_path / "w_on", on_job, switch=FEED_ON)

    assert off["game_model_fed"] is False and "game_model_read" not in off
    assert on["game_model_fed"] is True and on["game_model_read"] == ["pred_total", "pred_margin"]
    # off: the defect (equal outs/b2b -> 0); on: the game model's own margin and total (no drags, no def term)
    assert off["model_margin_raw"] == 0.0
    assert on["model_margin_raw"] == pytest.approx(PRED_MARGIN, abs=1e-9)
    assert on["model_total_raw"] == pytest.approx(PRED_TOTAL, abs=1e-9)
    assert on["anchored_margin"] != off["anchored_margin"]
    # the anchor blends with the weights it records (the policy picks them; the fleet's are 0.95 / 0.7)
    wm, wt = on["margin_w"], on["total_w"]
    assert (wm, wt) == (off["margin_w"], off["total_w"]) and 0.0 < wm < 1.0 and 0.0 < wt < 1.0
    # `_apply_market_anchor_local`: the total blend scales both means (so the margin by the same factor), then
    # the margin blends toward the market's.
    scale = (wt * 229.5 + (1.0 - wt) * PRED_TOTAL) / PRED_TOTAL
    assert on["anchored_margin"] == pytest.approx(wm * 3.5 + (1.0 - wm) * PRED_MARGIN * scale, abs=1e-9)
    assert on["anchored_total"] == pytest.approx(wt * 229.5 + (1.0 - wt) * PRED_TOTAL, abs=1e-9)
    assert off["anchored_margin"] == pytest.approx(wm * 3.5, abs=1e-9)
    assert on["nba_total_inputs"] == off["nba_total_inputs"] == {"skip_def_subtraction": True, "skip_outs_penalties": False}


# --- Level 4 follows the switch ------------------------------------------------------------------------------------

def test_checklist_level4_replays_under_the_same_switch(tmp_path):
    sys.path.insert(0, str(REPO / "scripts"))
    import basketball_sim_input_checklist as chk

    for day in ("2026-11-14", "2026-11-15"):
        (tmp_path / f"predictions_{day}.csv").write_text(
            "home_team,visitor_team,pred_total,pred_margin\nBOS,NYK,220,2\nLAL,GSW,231,-1\nMIA,ORL,214,4\n", encoding="utf-8")
    off = chk.game_model_feed_census(tmp_path, league="nba")
    assert (off["feed_game_model"], off["prediction_rows_fed"]) == (False, 0)
    assert len(chk.game_model_feed_alarms("nba", off)[0]) == 1

    _switch_file(tmp_path, FEED_ON)
    on = chk.game_model_feed_census(tmp_path, league="nba")
    assert (on["feed_game_model"], on["prediction_rows"], on["prediction_rows_fed"]) == (True, 6, 6)
    assert on["read_columns"] == ["totals", "spread_margin", "pred_total", "pred_margin"]
    assert chk.game_model_feed_alarms("nba", on)[0] == []
    assert chk.game_model_feed_census(tmp_path, league="wnba")["prediction_rows_fed"] == 0
