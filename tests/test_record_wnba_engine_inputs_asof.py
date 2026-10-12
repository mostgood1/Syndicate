"""Hermetic tests for scripts/record_wnba_engine_inputs_asof.py (no scratch run, no data/)."""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import record_wnba_engine_inputs_asof as rec  # noqa: E402
from syndicate.features.nba import live_resim as lr  # noqa: E402


def test_copy_switches_copies_present_and_reports_missing(tmp_path):
    live, dst = tmp_path / "live", tmp_path / "dst"
    live.mkdir()
    dst.mkdir()
    (live / "wnba_sim_availability.json").write_text('{"enabled": true}', encoding="utf-8")
    got = rec.copy_switches(live, dst)
    assert got["wnba_sim_availability.json"] is True and (dst / "wnba_sim_availability.json").exists()
    assert got["wnba_sim_rate_shrink.json"] is False and not (dst / "wnba_sim_rate_shrink.json").exists()
    assert set(got) == set(rec.SWITCH_FILES)


def test_rotation_inputs_are_truncated_to_before_the_slate(tmp_path):
    import pandas as pd
    live, dst = tmp_path / "live", tmp_path / "dst"
    (live / "rotation_stints").mkdir(parents=True)
    dst.mkdir()
    pd.DataFrame({"date": ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"], "team": ["DAL"] * 4,
                  "duration_sec": [60] * 4, "lineup_player_ids": ["1|2|3|4|5"] * 4}).to_csv(
        live / "rotation_stints_history.csv", index=False)
    for day in ("2026-08-11", "2026-08-12"):
        (live / "rotation_stints" / f"player_checks_{day}.csv").write_text("date,team,player_id,player_name" + chr(10),
                                                                         encoding="utf-8")
    got = rec.add_rotation_inputs(live, dst, "2026-08-12")
    assert got == {"stints_rows": 2, "player_checks": 1}           # < D only: D's own game never leaks in
    assert set(pd.read_parquet(dst / "rotation_stints_history.parquet")["date"]) == {"2026-08-10", "2026-08-11"}
    assert [f.name for f in (dst / "rotation_stints").glob("*.csv")] == ["player_checks_2026-08-11.csv"]


def test_wnba_inputs_round_trip_through_live_resim_with_a_wnba_stamp(tmp_path):
    kwargs = {k: f"v_{k}" for k in lr._INPUT_KEYS}
    path = lr.persist_engine_inputs("2026-08-12", "dal", "tor", kwargs, root=tmp_path, league="wnba")
    assert pickle.loads(path.read_bytes())["league"] == "wnba"
    assert lr.load_engine_inputs("2026-08-12", "DAL", "TOR", root=tmp_path, league="wnba") == kwargs
