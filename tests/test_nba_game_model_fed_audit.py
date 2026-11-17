"""todo #821 F0 (lane nba-game-model-fed-audit): the pregame smart-sim records whether the game model reached the
quarter model's team ratings. Behaviour-neutral: the read itself is unchanged.

The pregame job build reads the game model's predicted total/margin as `totals`/`spread_margin` (WNBA's names). NBA's
predictions_<D>.csv carries `pred_total`/`pred_margin`, so on NBA both teams fall back to baseline_off_rating and the raw
margin is only the injury/back-to-back adjustment (.syndicate/findings_2026-11-16_nba_margin_raw_zero.md).

Branch first: the REAL per-game loop of _smart_sim_run_date_local (worker stubbed, jobs recorded) carries the audit on
its jobs, and the REAL worker writes it into market_anchor. These tests pin today's numbers too, so F1 (feeding the NBA
names) has to change them on purpose.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared import basketball_props_smart_sim as bps
from syndicate.features.shared import smart_sim_anchor_refresh as ar
from syndicate.features.shared import smart_sim_tip_freeze as tf

DATE = "2026-11-16"
TIP = datetime(2026, 11, 17, 0, 30, tzinfo=timezone.utc)
HOME, AWAY = "Washington Wizards", "Milwaukee Bucks"
NBA_BASELINE = 110.6


def _num(value):
    """The job build's own coercion (`_smart_sim_run_date_local._num`)."""
    try:
        numeric = float(pd.to_numeric(value, errors="coerce"))
        return numeric if np.isfinite(numeric) else None
    except Exception:
        return None


@pytest.fixture(autouse=True)
def _switches(monkeypatch):
    for env in (ar.SWITCH_ENV, ar.MIN_PTS_ENV, tf.SWITCH_ENV, "SYNDICATE_SMART_SIM_REUSE_EXCLUSION_CHECK"):
        monkeypatch.delenv(env, raising=False)


# --- the read ------------------------------------------------------------------------------------------------------

def test_nba_named_row_is_unfed_and_reads_nothing():
    home_mu, away_mu, audit = bps._game_model_points_local(pd.Series({"pred_total": 226.4, "pred_margin": 3.1}), _num)
    assert (home_mu, away_mu) == (None, None)
    assert audit == {"game_model_fed": False, "game_model_columns": ["pred_total", "pred_margin"]}


def test_wnba_named_row_is_fed_with_the_same_means_as_before():
    row = pd.Series({"totals": 161.0, "spread_margin": 4.0})
    home_mu, away_mu, audit = bps._game_model_points_local(row, _num)
    # the pre-F0 inline formula
    assert (home_mu, away_mu) == (0.5 * (161.0 + 4.0), 0.5 * (161.0 - 4.0))
    assert audit == {"game_model_fed": True, "game_model_columns": ["totals", "spread_margin"]}


@pytest.mark.parametrize("row", [{"totals": 161.0}, {"spread_margin": 4.0}, {"totals": "", "spread_margin": 4.0},
                                 {"totals": float("nan"), "spread_margin": 4.0}, {}])
def test_a_half_read_is_unfed(row):
    home_mu, away_mu, audit = bps._game_model_points_local(pd.Series(row, dtype=object), _num)
    assert (home_mu, away_mu, audit["game_model_fed"]) == (None, None, False)


def test_absent_audit_is_not_false():
    assert bps._game_model_anchor_fields_local({"home_tri": "WAS"}) == {}
    assert bps._game_model_anchor_fields_local(None) == {}
    assert bps._game_model_anchor_fields_local({"game_model_fed": False, "game_model_columns": ("pred_total",)}) == {
        "game_model_fed": False, "game_model_columns": ["pred_total"]}


# --- the real per-game loop ----------------------------------------------------------------------------------------

def _seed(root: Path, *, header: str, values: str) -> tuple[Path, Path]:
    processed, raw = root / "data" / "processed", root / "data" / "raw"
    processed.mkdir(parents=True)
    raw.mkdir(parents=True)
    (processed / f"predictions_{DATE}.csv").write_text(
        f"home_team,visitor_team,{header},commence_time,total,home_spread\n"
        f"{HOME},{AWAY},{values},2026-11-17T00:30:00Z,229.5,-3.5\n", encoding="utf-8")
    (processed / f"props_predictions_{DATE}.csv").write_text(
        "player_name,team\nKyshawn George,WAS\nGiannis Antetokounmpo,MIL\n", encoding="utf-8")
    return processed, raw


def _run(processed: Path, raw: Path, *, league: str = "nba") -> tuple[dict, list[dict]]:
    jobs: list[dict] = []

    def _fake_worker_run(job: dict) -> dict:
        jobs.append(dict(job))
        return {"status": "wrote", "home": job.get("home_tri"), "away": job.get("away_tri")}

    with patch.object(bps, "_smart_sim_worker_run_local", side_effect=_fake_worker_run), \
            patch.object(bps, "_smart_sim_worker_init_local", return_value=None), \
            patch.object(tf, "_now", return_value=TIP - timedelta(hours=3)):
        result = bps._smart_sim_run_date_local(
            processed_root=processed, raw_root=raw, date_str=DATE, n_sims=10, seed=None, max_games=None,
            overwrite=False, workers=1, league_code=league,
        )
    return result, jobs


def test_run_loop_nba_names_job_is_unfed_at_baseline_and_says_so_once(tmp_path, capsys):
    processed, raw = _seed(tmp_path, header="pred_total,pred_margin", values="226.4,3.1")
    result, jobs = _run(processed, raw)
    assert result["wrote"] == 1 and len(jobs) == 1
    job = jobs[0]
    assert job["game_model_fed"] is False
    assert job["game_model_columns"] == ["pred_total", "pred_margin"]
    # today's numbers, pinned: both teams at the league baseline whatever the game model said
    assert job["home_off_rtg"] == job["away_off_rtg"] == pytest.approx(NBA_BASELINE)
    assert job["off_rtg_from_points"] is False
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.startswith(bps.GAME_MODEL_UNFED_TAG_LOCAL)]
    assert lines == [f"SMART_SIM_GAME_MODEL_UNFED league=nba date={DATE} unfed=1 of=1 read=totals/spread_margin "
                     "found=pred_total,pred_margin games=WAS_MIL"]


def test_run_loop_wnba_names_on_nba_feed_the_ratings_and_stay_quiet(tmp_path, capsys):
    processed, raw = _seed(tmp_path, header="totals,spread_margin", values="226.4,3.1")
    _, jobs = _run(processed, raw)
    job = jobs[0]
    assert job["game_model_fed"] is True and job["game_model_columns"] == ["totals", "spread_margin"]
    pace = job["matchup_pace"]
    assert job["home_off_rtg"] == pytest.approx(0.5 * (226.4 + 3.1) / pace * 100.0)
    assert job["away_off_rtg"] == pytest.approx(0.5 * (226.4 - 3.1) / pace * 100.0)
    assert job["home_off_rtg"] != job["away_off_rtg"]
    assert bps.GAME_MODEL_UNFED_TAG_LOCAL not in capsys.readouterr().out


# --- the real worker writes it into market_anchor ------------------------------------------------------------------

def _worker_artifact(tmp_path: Path, job: dict, name: str) -> dict:
    out_path = tmp_path / name / f"smart_sim_{DATE}_WAS_MIL.json"
    out_path.parent.mkdir(parents=True)
    job = {**job, "out_path": str(out_path)}
    state = {"date_str": DATE, "n_sims": 10, "seed": 7, "pbp": False, "roster_mode": "historical",
             "league_code": "nba", "props_df": None, "excluded_map": {}, "adv_map": {}, "game_id_map": {},
             "name_to_id": {}, "team_name_to_id": {}}
    engine_out = {"players": {"home": [{"player_name": "Kyshawn George", "player_id": 1}],
                              "away": [{"player_name": "Giannis Antetokounmpo", "player_id": 2}]}}
    with patch.object(bps, "_SMARTSIM_WORKER_STATE", state), \
            patch.object(bps, "_call_source_simulate_smart_game_local", side_effect=lambda **_: json.loads(json.dumps(engine_out))):
        result = bps._smart_sim_worker_run_local(job)
    assert result["status"] == "wrote", result
    return json.loads(out_path.read_text(encoding="utf-8"))


def test_worker_records_the_audit_and_changes_nothing_else(tmp_path):
    processed, raw = _seed(tmp_path / "seed", header="pred_total,pred_margin", values="226.4,3.1")
    _, jobs = _run(processed, raw)
    job = jobs[0]
    with_audit = _worker_artifact(tmp_path, job, "a")["market_anchor"]
    bare_job = {k: v for k, v in job.items() if k not in ("game_model_fed", "game_model_columns")}
    without = _worker_artifact(tmp_path, bare_job, "b")["market_anchor"]

    assert with_audit["game_model_fed"] is False
    assert with_audit["game_model_columns"] == ["pred_total", "pred_margin"]
    assert "game_model_fed" not in without and "game_model_columns" not in without
    # behaviour-neutral: every pre-existing field identical, including the means the player sim is driven by
    assert {k: v for k, v in with_audit.items() if k not in ("game_model_fed", "game_model_columns")} == without
    # the defect, pinned: equal outs + b2b -> the raw margin is exactly 0
    assert (job["home_outs"], job["away_outs"], job["home_b2b"], job["away_b2b"]) == (0, 0, False, False)
    assert with_audit["model_margin_raw"] == 0.0


def test_worker_records_fed_true_for_a_fed_job(tmp_path):
    processed, raw = _seed(tmp_path / "seed", header="totals,spread_margin", values="226.4,3.1")
    _, jobs = _run(processed, raw)
    anchor = _worker_artifact(tmp_path, jobs[0], "a")["market_anchor"]
    assert anchor["game_model_fed"] is True and anchor["game_model_columns"] == ["totals", "spread_margin"]
    assert anchor["model_margin_raw"] != 0.0
