"""The NBA SmartSim anchors to the current pregame consensus, not the line stored ~2 days earlier (lane
nba-sim-anchor-staleness, todo #721).

Drives the REAL per-game loop of _smart_sim_run_date_local with the worker stubbed; the stub records each job, so the
line the sim would anchor to is read off the job. The seeded sim passes every other reuse check, and its recorded
anchor is the stored line (-5.5 / 238.5). This run's props snapshot says -4.5 / 239.5. That is the production shape
of 10-21 WAS_MIL: stored 10-19 3:04 AM CT, consensus -4.5 by 10:44 AM CT. Reachability first: off != on.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from syndicate.features.shared import smart_sim_anchor_refresh as ar
from syndicate.features.shared import smart_sim_tip_freeze as tf
from syndicate.features.shared.basketball_props_smart_sim import _smart_sim_run_date_local, _to_tricode_local

DATE = "2026-10-21"
TIP = datetime(2026, 10, 21, 23, 0, tzinfo=timezone.utc)
SNAPSHOT_TS = "2026-10-21T16:14:41.372184+00:00"
STORED_WRITTEN = datetime(2026, 10, 19, 8, 4, tzinfo=timezone.utc).timestamp()
HOME, AWAY = "Washington Wizards", "Milwaukee Bucks"


def _snapshot_rows(spread_points: list[float], total_points: list[float], *, snapshot_ts: str = SNAPSHOT_TS,
                   commence: str = "2026-10-21T23:00:00Z") -> list[str]:
    rows = []
    for i, point in enumerate(spread_points):
        book = f"book{i}"
        rows.append(f"{snapshot_ts},ev1,{commence},{book},spreads,{HOME},{point},-110,{HOME},{AWAY}")
        rows.append(f"{snapshot_ts},ev1,{commence},{book},spreads,{AWAY},{-point},-110,{HOME},{AWAY}")
    for i, point in enumerate(total_points):
        book = f"book{i}"
        rows.append(f"{snapshot_ts},ev1,{commence},{book},totals,Over,{point},-110,{HOME},{AWAY}")
        rows.append(f"{snapshot_ts},ev1,{commence},{book},totals,Under,{point},-110,{HOME},{AWAY}")
    # player-prop rows ride in the same file and must be ignored
    rows.append(f"{snapshot_ts},ev1,{commence},book0,player_points,Over,24.5,-110,{HOME},{AWAY}")
    return rows


def _write_snapshot(processed: Path, rows: list[str]) -> Path:
    path = processed / f"oddsapi_player_props_{DATE}.csv"
    path.write_text("snapshot_ts,event_id,commence_time,bookmaker,market,outcome_name,point,price,home_team,away_team\n"
                    + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def _seed(root: Path, *, with_sim: bool = True, snapshot: list[str] | None = None) -> tuple[Path, Path, Path]:
    processed, raw = root / "data" / "processed", root / "data" / "raw"
    processed.mkdir(parents=True)
    raw.mkdir(parents=True)
    pred = processed / f"predictions_{DATE}.csv"
    pred.write_text("home_team,visitor_team,totals,spread_margin,commence_time,total,home_spread\n"
                    f"{HOME},{AWAY},236,4,2026-10-21T23:00:00Z,238.5,-5.5\n", encoding="utf-8")
    os.utime(pred, (STORED_WRITTEN, STORED_WRITTEN))
    (processed / f"props_predictions_{DATE}.csv").write_text(
        "player_name,team\nKyshawn George,WAS\nGiannis Antetokounmpo,MIL\n", encoding="utf-8")
    _write_snapshot(processed, snapshot if snapshot is not None else _snapshot_rows([-4.5, -4.5, -5.0], [239.5] * 3))
    sim = processed / f"smart_sim_{DATE}_WAS_MIL.json"
    if with_sim:
        sim.write_text(json.dumps({
            "home": "WAS", "away": "MIL", "players": {"home": [{"player": "A"}], "away": [{"player": "B"}]},
            "market_anchor": {"state": "on", "market_total": 238.5, "market_spread": -5.5},
        }), encoding="utf-8")
    return processed, raw, sim


def _run(processed: Path, raw: Path, *, league: str = "nba") -> tuple[dict, list[dict]]:
    jobs: list[dict] = []

    def _fake_worker_run(job: dict) -> dict:
        jobs.append(dict(job))
        return {"status": "wrote", "home": job.get("home_tri"), "away": job.get("away_tri")}

    with patch("syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_run_local",
               side_effect=_fake_worker_run), \
            patch("syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_init_local", return_value=None), \
            patch.object(tf, "_now", return_value=TIP - timedelta(hours=3)):
        result = _smart_sim_run_date_local(
            processed_root=processed, raw_root=raw, date_str=DATE, n_sims=10, seed=None, max_games=None,
            overwrite=False, workers=1, league_code=league,
        )
    return result, jobs


@pytest.fixture(autouse=True)
def _switches(monkeypatch):
    for env in (ar.SWITCH_ENV, ar.MIN_PTS_ENV, tf.SWITCH_ENV, "SYNDICATE_SMART_SIM_REUSE_EXCLUSION_CHECK"):
        monkeypatch.delenv(env, raising=False)


# --- reachability first ---------------------------------------------------------------------------------------------

def test_drifted_sim_is_rebuilt_on_the_fresh_line_with_the_switch_absent_and_reused_with_it_off(tmp_path, monkeypatch,
                                                                                                capsys):
    processed, raw, sim = _seed(tmp_path)
    # off first: the rebuild below deletes the sim (the stub writes nothing back)
    monkeypatch.setenv(ar.SWITCH_ENV, "off")
    before = sim.read_bytes()
    off, jobs = _run(processed, raw)
    assert (off["wrote"], off["skipped"]) == (0, 1)
    assert sim.read_bytes() == before and jobs == []
    out = capsys.readouterr().out
    assert "SMART_SIM_ANCHOR" not in out and "ANCHOR_DRIFT" not in out

    monkeypatch.delenv(ar.SWITCH_ENV)
    on, jobs = _run(processed, raw)
    assert (on["wrote"], on["skipped"]) == (1, 0)
    assert (jobs[0]["market_total"], jobs[0]["home_spread"]) == (239.5, -4.5)
    assert jobs[0]["market_line_source"] == ar.SOURCE_LABEL and jobs[0]["market_line_as_of"].startswith("2026-10-21T16:14")
    out = capsys.readouterr().out
    assert "SMART_SIM_REUSE_ANCHOR_DRIFT league=nba" in out and "-> re-simulate" in out
    assert "SMART_SIM_ANCHOR_LINE league=nba date=2026-10-21 game=WAS_MIL stored=238.5/-5.5 fresh=239.5/-4.5" in out


def test_off_builds_a_missing_sim_on_the_stored_line_with_no_stamp(tmp_path, monkeypatch):
    monkeypatch.setenv(ar.SWITCH_ENV, "off")
    processed, raw, _ = _seed(tmp_path, with_sim=False)
    _, jobs = _run(processed, raw)
    assert (jobs[0]["market_total"], jobs[0]["home_spread"]) == (238.5, -5.5)
    assert "market_line_source" not in jobs[0]


def test_a_missing_sim_is_built_on_the_fresh_line(tmp_path):
    processed, raw, _ = _seed(tmp_path, with_sim=False)
    _, jobs = _run(processed, raw)
    assert (jobs[0]["market_total"], jobs[0]["home_spread"]) == (239.5, -4.5)


def test_shadow_logs_the_drift_and_the_line_and_changes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(ar.SWITCH_ENV, "shadow")
    processed, raw, _ = _seed(tmp_path)
    result, jobs = _run(processed, raw)
    assert (result["wrote"], result["skipped"]) == (0, 1)
    out = capsys.readouterr().out
    assert "SMART_SIM_REUSE_ANCHOR_DRIFT" in out and "(shadow: kept)" in out
    processed2, raw2, _ = _seed(tmp_path / "b", with_sim=False)
    _, jobs = _run(processed2, raw2)
    assert (jobs[0]["market_total"], jobs[0]["home_spread"]) == (238.5, -5.5)
    assert "market_line_source" not in jobs[0]
    assert "SMART_SIM_ANCHOR_LINE" in capsys.readouterr().out and "mode=shadow" in out


def test_drift_below_the_threshold_reuses(tmp_path, capsys):
    processed, raw, _ = _seed(tmp_path, snapshot=_snapshot_rows([-5.0] * 3, [239.0] * 3))
    result, jobs = _run(processed, raw)
    assert (result["wrote"], result["skipped"]) == (0, 1) and jobs == []
    assert "ANCHOR_DRIFT" not in capsys.readouterr().out


def test_threshold_is_configurable(tmp_path, monkeypatch):
    monkeypatch.setenv(ar.MIN_PTS_ENV, "0.5")
    processed, raw, _ = _seed(tmp_path, snapshot=_snapshot_rows([-5.0] * 3, [238.5] * 3))
    result, _ = _run(processed, raw)
    assert (result["wrote"], result["skipped"]) == (1, 0)


def test_wnba_is_untouched(tmp_path, capsys):
    processed, raw = tmp_path / "data" / "processed", tmp_path / "data" / "raw"
    processed.mkdir(parents=True)
    raw.mkdir(parents=True)
    (processed / f"predictions_{DATE}.csv").write_text(
        "home_team,visitor_team,totals,spread_margin,commence_time,total,home_spread\n"
        "LVA,NYL,160,4,2026-10-21T23:00:00Z,161.5,-3.5\n", encoding="utf-8")
    (processed / f"props_predictions_{DATE}.csv").write_text("player_name,team\nA'ja Wilson,LVA\n", encoding="utf-8")
    _write_snapshot(processed, [f"{SNAPSHOT_TS},ev1,2026-10-21T23:00:00Z,b,totals,Over,170.5,-110,Las Vegas Aces,New York Liberty"])
    _, jobs = _run(processed, raw, league="wnba")
    assert (jobs[0]["market_total"], jobs[0]["home_spread"]) == (161.5, -3.5)
    assert "SMART_SIM_ANCHOR" not in capsys.readouterr().out


# --- the fresh line -------------------------------------------------------------------------------------------------

def _fresh(processed: Path, *, stored_written: float | None = STORED_WRITTEN):
    return ar.fresh_lines(processed, DATE, league="nba", to_tricode=_to_tricode_local, stored_written=stored_written)


def test_the_fresh_line_is_predict_dates_modal_statistic(tmp_path):
    # 2 books at -4.5, 1 at -5.0 -> -4.5 (the mean would be -4.67); a 1-1 tie goes to the smaller value, as pandas'
    # Series.mode().iloc[0] does inside consensus_lines_at_close.
    processed = tmp_path
    _write_snapshot(processed, _snapshot_rows([-4.5, -4.5, -5.0], [239.5, 240.0, 239.5]))
    line = _fresh(processed)[("WAS", "MIL")]
    assert (line.spread, line.total) == (-4.5, 239.5)
    _write_snapshot(processed, _snapshot_rows([-4.5, -5.0], [240.0, 239.5]))
    line = _fresh(processed)[("WAS", "MIL")]
    assert (line.spread, line.total) == (-5.0, 239.5)


def test_in_play_rows_are_never_a_line(tmp_path, capsys):
    _write_snapshot(tmp_path, _snapshot_rows([-4.5] * 3, [239.5] * 3, snapshot_ts="2026-10-21T23:20:00+00:00"))
    assert _fresh(tmp_path, stored_written=None) == {}
    assert "reason=no_pregame_rows" in capsys.readouterr().out


def test_a_snapshot_no_newer_than_the_stored_line_is_ignored(tmp_path, capsys):
    _write_snapshot(tmp_path, _snapshot_rows([-4.5] * 3, [239.5] * 3))
    assert _fresh(tmp_path, stored_written=datetime(2026, 10, 21, 17, 0, tzinfo=timezone.utc).timestamp()) == {}
    assert "reason=snapshot_not_newer_than_stored_line" in capsys.readouterr().out


def test_missing_or_empty_snapshot_gives_no_line(tmp_path, capsys):
    assert _fresh(tmp_path) == {}
    (tmp_path / f"oddsapi_player_props_{DATE}.csv").write_text("snapshot_ts,event_id\n", encoding="utf-8")
    assert _fresh(tmp_path) == {}
    out = capsys.readouterr().out
    assert "reason=no_snapshot" in out and "reason=empty_snapshot" in out


def test_a_side_the_snapshot_does_not_price_keeps_the_stored_line():
    fresh = ar.FreshLine(total=None, spread=-4.5, as_of=SNAPSHOT_TS)
    total, spread, stamp = ar.override(238.5, -5.5, fresh, date_str=DATE, league="nba", home="WAS", away="MIL")
    assert (total, spread) == (238.5, -4.5) and stamp["market_line_source"] == ar.SOURCE_LABEL


def test_an_unanchored_sim_is_stale_once_a_line_exists(tmp_path):
    sim = tmp_path / "s.json"
    sim.write_text(json.dumps({"players": {}, "market_anchor": {"market_total": None, "market_spread": None}}),
                   encoding="utf-8")
    fresh = ar.FreshLine(total=239.5, spread=-4.5, as_of=SNAPSHOT_TS)
    assert ar.anchor_current(sim, fresh, date_str=DATE, league="nba") is False
    assert ar.anchor_current(sim, None, date_str=DATE, league="nba") is True


def test_switch_values(monkeypatch):
    for raw, want in (("", "on"), ("on", "on"), ("1", "on"), ("shadow", "shadow"), ("OFF", "off"), ("0", "off"),
                      ("false", "off"), ("no", "off")):
        monkeypatch.setenv(ar.SWITCH_ENV, raw)
        assert ar.mode() == want, raw
    for raw, want in (("", 1.0), ("0.5", 0.5), ("x", 1.0), ("-1", 1.0), ("nan", 1.0)):
        monkeypatch.setenv(ar.MIN_PTS_ENV, raw)
        assert ar.min_pts() == want, raw
