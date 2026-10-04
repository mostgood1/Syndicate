"""An injured player must not be re-admitted to the SmartSim pool just because it has a props projection.

Production `props_predictions_<D>.csv` never carries `playing_today` (0 of 4 fleet files, 2026-10-01..04), and the
old re-inclusion loop re-admitted EVERY player in props_df when the column was absent -- 83 exclusions -> 30 on
2026-08-12, and the 10-04 playoff sims simulated OUT-listed players. Fixture shapes are production's: the injury file
columns are the fleet's `raw/injuries.csv` (team, player, status, injury, date); the props frame carries team and
player_name with no playing_today, as production does."""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from syndicate.features.shared.basketball_props_smart_sim import (
    _norm_name_key,
    _smart_sim_injuries_excluded_map_for_date_local as excluded_map,
)


def _roots(tmp_path: Path):
    processed, raw = tmp_path / "processed", tmp_path / "raw"
    processed.mkdir()
    raw.mkdir()
    with (raw / "injuries.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["team", "player", "status", "injury", "date"])
        w.writerow(["LVA", "Stephanie Talbot", "OUT", "Knee", "2026-10-03"])
        w.writerow(["NYL", "Satou Sabally", "OUT", "Ankle", "2026-10-03"])
        w.writerow(["NYL", "Breanna Stewart", "Day-To-Day", "Rest", "2026-10-03"])
    return processed, raw


def _keys(m, team):
    return {k.upper() for k in m.get(team, set())}


def test_out_player_with_a_projection_stays_excluded_when_playing_today_is_absent(tmp_path):
    processed, raw = _roots(tmp_path)
    props = pd.DataFrame([{"team": "LVA", "player_name": "Stephanie Talbot", "pred_pts": 8.1},
                          {"team": "NYL", "player_name": "Satou Sabally", "pred_pts": 13.0}])
    m = excluded_map(processed_root=processed, raw_root=raw, date_str="2026-10-04", props_df=props)
    assert _norm_name_key("Stephanie Talbot").upper() in _keys(m, "LVA")     # failed on the old code: re-admitted
    assert _norm_name_key("Satou Sabally").upper() in _keys(m, "NYL")
    assert _norm_name_key("Breanna Stewart").upper() not in _keys(m, "NYL")  # day-to-day is not an exclusion


def test_a_positive_playing_today_flag_still_re_admits(tmp_path):
    processed, raw = _roots(tmp_path)
    props = pd.DataFrame([{"team": "LVA", "player_name": "Stephanie Talbot", "playing_today": True},
                          {"team": "NYL", "player_name": "Satou Sabally", "playing_today": False}])
    m = excluded_map(processed_root=processed, raw_root=raw, date_str="2026-10-04", props_df=props)
    assert _norm_name_key("Stephanie Talbot").upper() not in _keys(m, "LVA")
    assert _norm_name_key("Satou Sabally").upper() in _keys(m, "NYL")


def test_no_props_frame_keeps_every_exclusion(tmp_path):
    processed, raw = _roots(tmp_path)
    m = excluded_map(processed_root=processed, raw_root=raw, date_str="2026-10-04", props_df=None)
    assert _norm_name_key("Stephanie Talbot").upper() in _keys(m, "LVA")
