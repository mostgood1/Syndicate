"""nba_season_phase: the resolver, its conservative unknown, and the same-phase filter on the props bias windows."""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import basketball_props_calibration as bpc
from syndicate.features.shared import nba_season_phase as ph
from tests.test_nba_prop_calibration import ESPN_TYPES, write_season_types


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(ph, "_fetch_types", lambda year, timeout=10.0: None)   # never the network in tests
    write_season_types(tmp_path)
    return tmp_path


@pytest.mark.parametrize("d,phase", [
    ("2026-10-05", "preseason"), ("2026-10-19", "preseason"), ("2026-10-20", "regular"), ("2027-02-01", "regular"),
    ("2027-04-11", "regular"), ("2027-04-14", "play_in"), ("2027-04-20", "postseason"),
    ("2025-10-21", "regular"), ("2026-04-15", "play_in"), ("2026-05-10", "postseason"), ("2026-08-01", "off_season"),
])
def test_phase_from_the_espn_season_table(root, d, phase):
    assert ph.phase_for_date(d, processed_root=root) == phase


def test_scoreboard_wins_over_the_table_and_mixed_or_missing_is_unknown(root, monkeypatch):
    cache = root / "_espn_cache" / "nba"
    (cache / "scoreboard_20261020.json").write_text(json.dumps({"events": [{"season": {"type": 1}}]}), encoding="utf-8")
    assert ph.phase_for_date("2026-10-20", processed_root=root) == "preseason"     # what the game itself says
    (cache / "scoreboard_20261020.json").write_text(
        json.dumps({"events": [{"season": {"type": 1}}, {"season": {"type": 2}}]}), encoding="utf-8")
    assert ph.phase_for_date("2026-10-20", processed_root=root) == "regular"       # mixed scoreboard -> table
    for p in cache.glob("season_types_*.json"):
        p.unlink()
    ph._types_cached.cache_clear()
    assert ph.phase_for_date("2027-01-05", processed_root=root) is None            # no source -> UNKNOWN, not regular


def test_phase_start_is_the_local_date(root):
    assert ph.phase_start("2026-11-01", "regular", processed_root=root) == "2026-10-20"
    assert ph.phase_start("2026-01-10", "regular", processed_root=root) == "2025-10-21"
    assert ph.phase_start("2027-04-20", "postseason", processed_root=root) == "2027-04-17"


def test_same_phase_filter_admits_nothing_for_preseason_or_unknown(root):
    f = ph.same_phase_date_filter("2026-10-25", processed_root=root)
    assert f.slate_phase == "regular" and f("2026-10-21") and not f("2026-10-18")
    pre = ph.same_phase_date_filter("2026-10-10", processed_root=root)
    assert pre.slate_phase == "preseason" and not pre("2026-10-09")
    post = ph.same_phase_date_filter("2027-04-20", processed_root=root)
    assert post("2027-04-14") and post("2027-04-18") and not post("2027-04-10")


def test_bias_window_reachability_filter_off_differs_from_on(root):
    """The 7-day window on 2026-10-25 spans 10-18..10-24: with the filter, the preseason dates 10-18/19 are gone."""
    off = bpc._window_dates("2026-10-25", 7, None)
    on = bpc._window_dates("2026-10-25", 7, ph.same_phase_date_filter("2026-10-25", processed_root=root))
    assert off != on and "2026-10-18" in off and "2026-10-19" in off
    assert on == [d for d in off if d >= "2026-10-20"] and on
    # opening night: the whole 7-day window is preseason -> an empty window, not preseason calibration
    assert bpc._window_dates("2026-10-20", 7, ph.same_phase_date_filter("2026-10-20", processed_root=root)) == []


def test_espn_table_matches_the_pinned_fixture():
    assert set(ESPN_TYPES) == {2026, 2027}


# --- rotation-history lookback (basketball_props_smart_sim._rotation_sim_minutes_from_history_local, loaned) ---------

def _rotation_call(root, monkeypatch, league, slate):
    import types

    import pandas as pd

    from syndicate.features.shared import basketball_props_smart_sim as bpss

    stints = pd.DataFrame({"team": ["NYK"] * 4, "duration_sec": [600] * 4, "lineup_player_ids": ["1;2;3;4;5"] * 4,
                           "date": ["2026-10-12", "2026-10-15", "2026-10-17", "2026-10-21"]})
    mod = types.SimpleNamespace(
        _read_hist_any=lambda *paths: stints, _roll_minutes_unscaled=None, _regularize_rotation_minutes=None,
        _minutes_caps_from_team_df=None, _cap_and_redistribute_minutes=None, _rotation_minutes_signal_guardrail=None,
        _clean_id_str=str, paths=types.SimpleNamespace(data_processed=root))
    monkeypatch.setattr(bpss, "_espn_name_to_id_map_for_game_local", lambda **k: {})   # stop right after the filter
    team_df = pd.DataFrame({"player_name": ["A. Player"]})
    return bpss._rotation_sim_minutes_from_history_local(
        smart_sim_module=mod, league_code=league, team_df=team_df, date_str=slate, home_tri="NYK", away_tri="BOS",
        team_tri="NYK")[3]


def test_rotation_lookback_keeps_same_phase_stints_only(root, monkeypatch):
    """Opening night 2026-10-20: the 28-day window holds only preseason stints -> nothing kept (on), while WNBA (off)
    keeps them. Two days later the regular-season stint survives and the preseason ones do not."""
    on = _rotation_call(root, monkeypatch, "nba", "2026-10-20")
    off = _rotation_call(root, monkeypatch, "wnba", "2026-10-20")
    assert on["reason"] == "no_recent_history" and on["phase_filtered_rows"] == 3 and on["slate_phase"] == "regular"
    assert off["reason"] == "no_espn_name_map" and "phase_filtered_rows" not in off
    later = _rotation_call(root, monkeypatch, "nba", "2026-10-22")
    assert later["reason"] == "no_espn_name_map" and later["phase_filtered_rows"] == 3   # 10-21 regular stint kept
