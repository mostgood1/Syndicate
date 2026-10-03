"""Tests for syndicate/features/shared/wnba_sim_availability.py (lane `wnba-sim-availability`).

Reachability first: flag off and on must give different exclusion maps. Then the properties a wrong answer would
hide: only games STRICTLY before the slate count (as-of), a `playing_today` flag beats the recency guess, NBA is never
touched, a missing history adds nothing and names why, and the engine's own key function is what lands in the map."""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from syndicate.features.shared import wnba_sim_availability as A
from syndicate.features.shared.basketball_props_smart_sim import _norm_name_key

ON = {A.FLAG: "1"}


def _history(root: Path, rows):
    with (root / A.HISTORY_FILE).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["game_id", "date", "TEAM_ABBREVIATION", "PLAYER_NAME", "MIN"])
        w.writerows(rows)
    return root


def _season(root):
    # LVA: A'ja Wilson plays every game; Kierstan Bell plays game 1 then sits out games 2 and 3 (absent from the box);
    # Dana Evans is listed DNP (MIN 0) in game 3 only. A game ON the slate date must be ignored.
    return _history(root, [
        ("g1", "2026-07-01", "LVA", "A'ja Wilson", 34), ("g1", "2026-07-01", "LVA", "Kierstan Bell", 12),
        ("g1", "2026-07-01", "LVA", "Dana Evans", 15),
        ("g2", "2026-07-03", "LVA", "A'ja Wilson", 35), ("g2", "2026-07-03", "LVA", "Dana Evans", 14),
        ("g3", "2026-07-05", "LVA", "A'ja Wilson", 33), ("g3", "2026-07-05", "LVA", "Dana Evans", 0),
        ("g4", "2026-07-07", "LVA", "Kierstan Bell", 30),              # the slate itself: must not count
    ])


def test_reachability_off_and_on_differ(tmp_path):
    root = _season(tmp_path)
    off, on = {}, {}
    s_off = A.add_recency_exclusions(off, processed_root=root, date_str="2026-07-07", league_code="wnba", props_df=None,
                                     name_key=_norm_name_key, env={})
    s_on = A.add_recency_exclusions(on, processed_root=root, date_str="2026-07-07", league_code="wnba", props_df=None,
                                    name_key=_norm_name_key, env=ON)
    assert off == {} and s_off["reason"] == f"{A.FLAG} off"
    assert s_on["applied"] is True
    assert on["LVA"] == {_norm_name_key("Kierstan Bell").upper(), _norm_name_key("Dana Evans").upper()}


def test_k_two_keeps_a_one_game_absence(tmp_path):
    root = _season(tmp_path)
    m = {}
    A.add_recency_exclusions(m, processed_root=root, date_str="2026-07-07", league_code="wnba", props_df=None,
                             name_key=_norm_name_key, env={**ON, A.K_ENV: "2"})
    assert m["LVA"] == {_norm_name_key("Kierstan Bell").upper()}   # Evans played in g2, inside the last 2


def test_only_games_before_the_slate_count(tmp_path):
    root = _season(tmp_path)
    m = {}
    # As of 2026-07-04 the team's last game is g2, in which Bell did not play and Evans did.
    A.add_recency_exclusions(m, processed_root=root, date_str="2026-07-04", league_code="wnba", props_df=None,
                             name_key=_norm_name_key, env=ON)
    assert m["LVA"] == {_norm_name_key("Kierstan Bell").upper()}


def test_playing_today_beats_the_recency_guess(tmp_path):
    root = _season(tmp_path)
    props = pd.DataFrame([{"team": "LVA", "player_name": "Kierstan Bell", "playing_today": True}])
    m = {}
    A.add_recency_exclusions(m, processed_root=root, date_str="2026-07-07", league_code="wnba", props_df=props,
                             name_key=_norm_name_key, env=ON)
    assert m["LVA"] == {_norm_name_key("Dana Evans").upper()}


def test_existing_exclusions_are_kept_and_nba_is_untouched(tmp_path):
    root = _season(tmp_path)
    m = {"LVA": {"INJURED PLAYER"}}
    A.add_recency_exclusions(m, processed_root=root, date_str="2026-07-07", league_code="wnba", props_df=None,
                             name_key=_norm_name_key, env=ON)
    assert "INJURED PLAYER" in m["LVA"] and len(m["LVA"]) == 3
    n = {}
    s = A.add_recency_exclusions(n, processed_root=root, date_str="2026-07-07", league_code="nba", props_df=None,
                                 name_key=_norm_name_key, env=ON)
    assert n == {} and s["reason"] == "not wnba"


def test_missing_history_adds_nothing_and_names_why(tmp_path):
    m = {}
    s = A.add_recency_exclusions(m, processed_root=tmp_path, date_str="2026-07-07", league_code="wnba", props_df=None,
                                 name_key=_norm_name_key, env=ON)
    assert m == {} and s["applied"] is False and "history absent" in s["reason"]
