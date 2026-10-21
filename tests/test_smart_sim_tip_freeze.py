"""A SmartSim whose game has tipped is kept, not rebuilt (lane freeze-nba-pregame-sims).

Drives the REAL per-game loop of _smart_sim_run_date_local with the worker stubbed. The seeded sim is stale on
exclusions (built before Kelsey Plum went out), so with the freeze off the reuse check rebuilds it. That is the
production shape of 10-20, where 8 of 10 post-tip rebuilds came from exclusion drift. Reachability first: off != on.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from syndicate.features.shared import smart_sim_tip_freeze as tf
from syndicate.features.shared.basketball_props_smart_sim import _smart_sim_run_date_local

DATE = "2026-10-07"
TIP = datetime(2026, 10, 7, 23, 30, tzinfo=timezone.utc)


def _fake_worker_run(job: dict) -> dict:
    return {"status": "wrote", "home": job.get("home_tri"), "away": job.get("away_tri")}


def _seed(root: Path, *, tip: str = "2026-10-07T23:30:00Z", with_sim: bool = True) -> tuple[Path, Path, Path]:
    processed, raw = root / "data" / "processed", root / "data" / "raw"
    processed.mkdir(parents=True)
    raw.mkdir(parents=True)
    (processed / f"predictions_{DATE}.csv").write_text(
        f"home_team,visitor_team,totals,spread_margin,commence_time\nLVA,NYL,160,4,{tip}\n", encoding="utf-8")
    (processed / f"props_predictions_{DATE}.csv").write_text(
        "player_name,team\nKelsey Plum,LVA\nA'ja Wilson,LVA\nBreanna Stewart,NYL\n", encoding="utf-8")
    (raw / "injuries.csv").write_text("team,player,status,injury,date\nLVA,Kelsey Plum,OUT,Out,2026-10-06\n",
                                      encoding="utf-8")
    sim = processed / f"smart_sim_{DATE}_LVA_NYL.json"
    if with_sim:
        # no excluded_players stamp: built when nobody was out -> stale on exclusions today
        sim.write_text(json.dumps({"home": "LVA", "away": "NYL",
                                   "players": {"home": [{"player": "A"}], "away": [{"player": "B"}]}}), encoding="utf-8")
    return processed, raw, sim


def _run(processed: Path, raw: Path, *, now: datetime, overwrite: bool = False, only_matchups=None,
         league: str = "wnba") -> dict:
    with patch("syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_run_local",
               side_effect=_fake_worker_run), \
            patch("syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_init_local", return_value=None), \
            patch.object(tf, "_now", return_value=now):
        return _smart_sim_run_date_local(
            processed_root=processed, raw_root=raw, date_str=DATE, n_sims=10, seed=None, max_games=None,
            overwrite=overwrite, workers=1, league_code=league, only_matchups=only_matchups,
        )


@pytest.fixture(autouse=True)
def _checks_on(monkeypatch):
    monkeypatch.delenv("SYNDICATE_SMART_SIM_REUSE_EXCLUSION_CHECK", raising=False)
    monkeypatch.delenv(tf.SWITCH_ENV, raising=False)


# --- reachability first ---------------------------------------------------------------------------------------------

def test_tipped_game_is_kept_with_the_switch_absent_and_rebuilt_with_it_off(tmp_path, monkeypatch, capsys):
    processed, raw, sim = _seed(tmp_path)
    before = sim.read_bytes()
    on = _run(processed, raw, now=TIP + timedelta(minutes=55))
    assert (on["wrote"], on["skipped"]) == (0, 1)
    assert sim.read_bytes() == before
    out = capsys.readouterr().out
    assert "SMART_SIM_TIP_FREEZE league=wnba" in out and "frozen=1 reuse=True" in out
    assert "SMART_SIM_REUSE_STALE_EXCLUSIONS" not in out  # the reuse checks never ran

    monkeypatch.setenv(tf.SWITCH_ENV, "off")
    off = _run(processed, raw, now=TIP + timedelta(minutes=55))
    assert (off["wrote"], off["skipped"]) == (1, 0)
    out = capsys.readouterr().out
    assert "SMART_SIM_TIP_FREEZE" not in out and "SMART_SIM_REUSE_STALE_EXCLUSIONS" in out


def test_pregame_stale_sim_is_still_rebuilt(tmp_path, capsys):
    processed, raw, _ = _seed(tmp_path)
    result = _run(processed, raw, now=TIP - timedelta(hours=3))
    assert (result["wrote"], result["skipped"]) == (1, 0)
    assert "SMART_SIM_TIP_FREEZE" not in capsys.readouterr().out


def test_a_rebuild_that_would_finish_after_tip_is_frozen(tmp_path, capsys):
    processed, raw, sim = _seed(tmp_path)
    before = sim.read_bytes()
    result = _run(processed, raw, now=TIP - timedelta(seconds=tf.PER_JOB_SECONDS / 2))
    assert (result["wrote"], result["skipped"]) == (0, 1)
    assert sim.read_bytes() == before
    assert "frozen=1" in capsys.readouterr().out


def test_shadow_logs_and_rebuilds(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(tf.SWITCH_ENV, "shadow")
    processed, raw, _ = _seed(tmp_path)
    result = _run(processed, raw, now=TIP + timedelta(hours=1))
    assert (result["wrote"], result["skipped"]) == (1, 0)
    assert "mode=shadow" in (out := capsys.readouterr().out) and "would_freeze=1 frozen=0" in out


def test_targeted_trigger_after_tip_is_frozen(tmp_path, monkeypatch):
    processed, raw, sim = _seed(tmp_path)
    before = sim.read_bytes()
    result = _run(processed, raw, now=TIP + timedelta(hours=2), only_matchups={("LVA", "NYL")})
    assert (result["wrote"], result["skipped"]) == (0, 1)
    assert sim.read_bytes() == before
    monkeypatch.setenv(tf.SWITCH_ENV, "0")
    result = _run(processed, raw, now=TIP + timedelta(hours=2), only_matchups={("LVA", "NYL")})
    assert (result["wrote"], result["skipped"]) == (1, 0)


def test_overwrite_is_never_frozen(tmp_path, capsys):
    processed, raw, _ = _seed(tmp_path)
    result = _run(processed, raw, now=TIP + timedelta(days=10), overwrite=True)
    assert (result["wrote"], result["skipped"]) == (1, 0)
    assert "SMART_SIM_TIP_FREEZE" not in capsys.readouterr().out


def test_missing_sim_after_tip_is_built_and_logged(tmp_path, capsys):
    processed, raw, _ = _seed(tmp_path, with_sim=False)
    result = _run(processed, raw, now=TIP + timedelta(minutes=5))
    assert (result["wrote"], result["skipped"]) == (1, 0)
    assert "built_after_tip=1 reason=no_existing_sim" in capsys.readouterr().out


def test_unknown_tip_rebuilds_and_says_so(tmp_path, capsys):
    processed, raw, _ = _seed(tmp_path, tip="")
    result = _run(processed, raw, now=TIP + timedelta(hours=1))
    assert (result["wrote"], result["skipped"]) == (1, 0)
    assert "tip=unknown frozen=0" in capsys.readouterr().out


def test_nba_tipped_game_is_kept(tmp_path, monkeypatch, capsys):
    # the 10-20 shape: an NBA sim stale on exclusions, refreshed 55 minutes after tip
    processed, raw = tmp_path / "data" / "processed", tmp_path / "data" / "raw"
    processed.mkdir(parents=True)
    raw.mkdir(parents=True)
    (processed / f"predictions_{DATE}.csv").write_text(
        "home_team,visitor_team,totals,spread_margin,commence_time\nNew York Knicks,Philadelphia 76ers,228,4,"
        "2026-10-07T23:30:00Z\n", encoding="utf-8")
    (processed / f"props_predictions_{DATE}.csv").write_text(
        "player_name,team\nJalen Brunson,NYK\nAdem Bona,PHI\nJoel Embiid,PHI\n", encoding="utf-8")
    (raw / "injuries.csv").write_text("team,player,status,injury,date\nPHI,Adem Bona,OUT,Out,2026-10-06\n",
                                      encoding="utf-8")
    sim = processed / f"smart_sim_{DATE}_NYK_PHI.json"
    sim.write_text(json.dumps({"home": "NYK", "away": "PHI",
                               "players": {"home": [{"player": "A"}], "away": [{"player": "B"}]}}), encoding="utf-8")
    on = _run(processed, raw, now=TIP + timedelta(minutes=55), league="nba")
    assert (on["wrote"], on["skipped"]) == (0, 1)
    assert "SMART_SIM_TIP_FREEZE league=nba" in capsys.readouterr().out
    monkeypatch.setenv(tf.SWITCH_ENV, "off")
    off = _run(processed, raw, now=TIP + timedelta(minutes=55), league="nba")
    assert (off["wrote"], off["skipped"]) == (1, 0)


# --- the pieces -----------------------------------------------------------------------------------------------------

def test_queue_position_moves_the_finish_past_tip():
    now = TIP - timedelta(minutes=10)
    # first in the queue finishes 90 s later: before tip. Tenth: 15 min later: after tip.
    assert tf.keep_existing(Path("x.json"), has_players=True, tip=TIP, queued=0, date_str=DATE, league="nba",
                            now=lambda: now) is False
    assert tf.keep_existing(Path("x.json"), has_players=True, tip=TIP, queued=9, date_str=DATE, league="nba",
                            now=lambda: now) is True


def test_tip_sources_predictions_then_game_odds_then_schedule(tmp_path):
    processed = tmp_path
    (processed / "schedule_2026_27.csv").write_text(
        "game_id,date_est,datetime_utc,home_tricode,away_tricode\n"
        "0022600010,2026-10-07,2026-10-08 02:00:00+00:00,LAL,GSW\n"
        "0022600011,2026-10-08,2026-10-08 23:00:00+00:00,BOS,NYK\n", encoding="utf-8")
    schedule = tf.schedule_tips(processed, DATE)
    assert schedule == {("LAL", "GSW"): datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc)}
    odds = pd.DataFrame([{"home_tri": "LAL", "away_tri": "GSW", "commence_time": "2026-10-08T02:10:00Z"}])
    row_with = pd.Series({"commence_time": "2026-10-08T02:05:00Z"})
    row_nan = pd.Series({"commence_time": float("nan")})
    assert tf.tip_time(row_with, odds_df=odds, schedule=schedule, home="LAL", away="GSW").minute == 5
    assert tf.tip_time(row_nan, odds_df=odds, schedule=schedule, home="LAL", away="GSW").minute == 10
    assert tf.tip_time(row_nan, odds_df=None, schedule=schedule, home="LAL", away="GSW").minute == 0
    assert tf.tip_time(row_nan, odds_df=None, schedule=schedule, home="BOS", away="NYK") is None


def test_switch_values(monkeypatch):
    for raw, want in (("", "on"), ("on", "on"), ("1", "on"), ("shadow", "shadow"), ("OFF", "off"), ("0", "off"),
                      ("false", "off"), ("no", "off")):
        monkeypatch.setenv(tf.SWITCH_ENV, raw)
        assert tf.mode() == want, raw
    monkeypatch.delenv(tf.SWITCH_ENV)
    assert tf.mode() == "on"
