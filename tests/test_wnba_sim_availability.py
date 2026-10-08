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
    assert off == {} and s_off["reason"].startswith(f"{A.FLAG} unset and switch file absent")
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


def _run(root, env):
    m = {}
    s = A.add_recency_exclusions(m, processed_root=root, date_str="2026-07-07", league_code="wnba", props_df=None,
                                 name_key=_norm_name_key, env=env)
    return m, s


def _switch(root, body):
    (root / A.SWITCH_FILE).write_text(body, encoding="utf-8")
    return root


def test_file_switch_turns_it_on_with_the_env_unset(tmp_path):
    """FILE SWITCH (2026-10-04): the per-run SmartSim reads the file, so production turns this on with no restart."""
    m, s = _run(_switch(_season(tmp_path), '{"enabled": true}'), env={})
    assert s["applied"] is True and s["switch"] == "file"
    assert _norm_name_key("Kierstan Bell").upper() in m["LVA"]


def test_env_zero_is_a_kill_switch_over_an_enabled_file(tmp_path):
    m, s = _run(_switch(_season(tmp_path), '{"enabled": true}'), env={A.FLAG: "0"})
    assert m == {} and s["reason"] == f"{A.FLAG} off"


def test_only_the_json_true_enables_and_unknown_is_off(tmp_path):
    for body in ('{"enabled": "true"}', '{"enabled": 1}', '{}', 'not json'):
        root = tmp_path / str(abs(hash(body)))
        root.mkdir()
        m, s = _run(_switch(_season(root), body), env={})
        assert m == {} and s["applied"] is False and "unset and switch file" in s["reason"], body


def test_playoff_rows_under_espn_codes_count_as_the_teams_games(tmp_path):
    """Discriminating (2026-10-08): production writes PLAYOFF box rows as GS/LV/NY. Unfolded, LVA's "last game" stayed
    its regular-season finale, so a player who sat the finale but played the playoff game was excluded (10-07:
    Marine Fauthoux 31 min, Dana Evans 18, Aminata Gueye 13 -- all left out, all played)."""
    root = _history(tmp_path, [
        ("g1", "2026-09-29", "LVA", "A'ja Wilson", 34), ("g1", "2026-09-29", "LVA", "Dana Evans", 0),   # finale: DNP
        ("p1", "2026-10-04", "LV", "A'ja Wilson", 36), ("p1", "2026-10-04", "LV", "Dana Evans", 18),    # playoff, ESPN code
    ])
    m = {}
    s = A.add_recency_exclusions(m, processed_root=root, date_str="2026-10-07", league_code="wnba", props_df=None,
                                 name_key=_norm_name_key, env=ON)
    assert _norm_name_key("Dana Evans").upper() not in m.get("LVA", set())
    assert "LV" not in m                                       # nothing keyed under the raw ESPN code

