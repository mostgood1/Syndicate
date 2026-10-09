"""`#473`: NBA team ratings + starter flags reach the smart sim (and off restores the old inputs exactly)."""
from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

from syndicate.features.shared import nba_team_inputs as nti
from syndicate.features.shared import basketball_props_smart_sim as bpss


def _team_rows(game_id, date, season, season_id, team, opp, pts, fga, fta=20, oreb=10, dreb=33, tov=13, fgm=40, fg3m=12, fg3a=35):
    # Two player rows per team-game so the player -> team aggregation is exercised.
    rows = []
    for share in (0.5, 0.5):
        rows.append({
            "SEASON_ID": season_id, "SEASON": season, "GAME_ID": game_id, "GAME_DATE": date, "TEAM_ABBREVIATION": team,
            "MATCHUP": f"{team} vs. {opp}", "PTS": pts * share, "FGM": fgm * share, "FGA": fga * share, "FG3M": fg3m * share,
            "FG3A": fg3a * share, "FTA": fta * share, "OREB": oreb * share, "DREB": dreb * share, "TOV": tov * share,
        })
    return rows


def _write_logs(root: Path, games):
    rows = []
    for g in games:
        rows += _team_rows(g["id"], g["date"], g["season"], g["sid"], g["home"], g["away"], g["hp"], 88)
        rows += _team_rows(g["id"], g["date"], g["season"], g["sid"], g["away"], g["home"], g["ap"], 88)
    pd.DataFrame(rows).to_csv(root / "player_logs.csv", index=False)


def _prior_season_games():
    # 2025-26 regular season: BOS beats NYK by 20 every night; plus a preseason game that must never count.
    games = [{"id": f"00225{i:05d}", "date": f"2026-01-{i + 1:02d}", "season": "2025-26", "sid": "22025",
              "home": "BOS", "away": "NYK", "hp": 120, "ap": 100} for i in range(10)]
    games.append({"id": "0012500001", "date": "2025-10-05", "season": "2025-26", "sid": "12025",
                  "home": "NYK", "away": "BOS", "hp": 150, "ap": 60})
    return games


@pytest.fixture(autouse=True)
def _clear_caches():
    bpss._TEAM_ADVANCED_STATS_CACHE_LOCAL.clear()
    bpss._PREGAME_EXPECTED_MINUTES_CACHE_LOCAL.clear()
    yield
    bpss._TEAM_ADVANCED_STATS_CACHE_LOCAL.clear()
    bpss._PREGAME_EXPECTED_MINUTES_CACHE_LOCAL.clear()


def test_preseason_rating_is_the_prior_regular_season_shrunk(tmp_path):
    _write_logs(tmp_path, _prior_season_games())
    out = nti.build_team_ratings_asof(processed_root=tmp_path, season=2027, as_of="20261008")
    by = out.set_index("team")
    assert set(by["population"]) == {"prior_regular_shrunk"}
    assert by.loc["BOS", "games"] == 0 and by.loc["BOS", "prior_games"] == 10  # the preseason row is excluded
    prior = nti.team_season_ratings(nti._load_regular_player_logs(tmp_path), season_label="2025-26")
    mean = prior["off_rtg"].mean()
    raw = prior.set_index("team").loc["BOS", "off_rtg"]
    assert by.loc["BOS", "off_rtg"] == pytest.approx(mean + nti.YOY_BETA * (raw - mean))
    assert by.loc["BOS", "off_rtg"] > by.loc["NYK", "off_rtg"]
    assert out["source"].map(nti.is_ours).all()


def test_in_season_blend_weights_current_games_by_k(tmp_path):
    games = _prior_season_games() + [
        {"id": f"00226{i:05d}", "date": f"2026-10-{21 + i:02d}", "season": "2026-27", "sid": "22026",
         "home": "NYK", "away": "BOS", "hp": 115, "ap": 105} for i in range(5)
    ]
    _write_logs(tmp_path, games)
    out = nti.build_team_ratings_asof(processed_root=tmp_path, season=2027, as_of="2026-10-31").set_index("team")
    logs = nti._load_regular_player_logs(tmp_path)
    cur = nti.team_season_ratings(logs, season_label="2026-27").set_index("team")
    prior = nti.team_season_ratings(logs, season_label="2025-26")
    anchor = prior["off_rtg"].mean() + nti.YOY_BETA * (prior.set_index("team").loc["NYK", "off_rtg"] - prior["off_rtg"].mean())
    want = (5 * cur.loc["NYK", "off_rtg"] + nti.PRIOR_GAMES_K * anchor) / (5 + nti.PRIOR_GAMES_K)
    assert out.loc["NYK", "games"] == 5
    assert out.loc["NYK", "off_rtg"] == pytest.approx(want)
    # as-of is a hard cut: nothing after it leaks in
    early = nti.build_team_ratings_asof(processed_root=tmp_path, season=2027, as_of="2026-10-22").set_index("team")
    assert early.loc["NYK", "games"] == 2


def _nba_team_adj(tmp_path):
    return bpss._team_adj_from_advanced_stats_local(
        processed_root=tmp_path, date_str="2026-10-08", home_tri="BOS", away_tri="NYK",
        league=bpss._league_for_code_local("nba"),
    )


def test_reachability_team_adj_on_vs_off(tmp_path):
    _write_logs(tmp_path, _prior_season_games())
    with mock.patch.dict(os.environ, {"SYNDICATE_NBA_TEAM_INPUTS": "1"}):
        home, away, _pace, diag = _nba_team_adj(tmp_path)
    assert diag["applied"] is True, diag
    assert home["eff_mult"] > 1.0 > away["eff_mult"]
    assert (tmp_path / "team_advanced_stats_2027_asof_20261008.csv").is_file()
    bpss._TEAM_ADVANCED_STATS_CACHE_LOCAL.clear()
    # OFF with the producer's file still on disk == the pre-#473 inputs (neutral)
    with mock.patch.dict(os.environ, {"SYNDICATE_NBA_TEAM_INPUTS": "0"}), \
            mock.patch.object(bpss, "_import_advanced_stats_builders_local", return_value=(None, None)):
        home_off, away_off, _p, diag_off = _nba_team_adj(tmp_path)
    assert home_off is None and away_off is None
    assert diag_off["reason"] == "missing_team_advanced_stats"


def _write_checks(root: Path, rows):
    d = root / "rotation_stints"
    d.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    for date, grp in df.groupby("date"):
        grp.to_csv(d / f"player_checks_{date}.csv", index=False)


def _check_rows(date, event, season, stype, team, starters, bench):
    return [{"league": "nba", "season": season, "season_type": stype, "date": date, "event_id": event, "team": team,
             "player_id": 1000 + i, "player_name": n, "starter": int(n in starters)} for i, n in enumerate(starters + bench)]


def test_starters_same_phase_then_any_phase(tmp_path):
    five = ["A One", "B Two", "C Three", "D Four", "E Five"]
    rows = []
    for k, date in enumerate(["2026-10-02", "2026-10-04", "2026-10-06"]):
        starters = five if k else ["A One", "B Two", "C Three", "D Four", "Bench Guy"]
        rows += _check_rows(date, f"e{k}", 2027, "preseason", "BOS", starters, [n for n in ("Bench Guy", "E Five") if n not in starters])
    rows += _check_rows("2026-10-09", "late", 2027, "preseason", "BOS", ["Z Late"], [])  # on/after the slate: excluded
    _write_checks(tmp_path, rows)
    pre = nti.build_starters(processed_root=tmp_path, date_str="2026-10-09", slate_phase="preseason").set_index("player_name")
    assert pre.loc["A One", "starter_prob"] == 1.0 and bool(pre.loc["A One", "is_starter"])
    assert pre.loc["E Five", "starter_prob"] == pytest.approx(2 / 3, abs=1e-4) and bool(pre.loc["E Five", "is_starter"])
    assert pre.loc["Bench Guy", "starter_prob"] == pytest.approx(1 / 3, abs=1e-4) and not bool(pre.loc["Bench Guy", "is_starter"])
    assert "Z Late" not in pre.index
    assert set(pre["exp_min_source"]) == {"nba_starters_v1:2027_preseason:last3"}
    # regular-season slate with no regular games yet: current season, any phase -- labelled as such
    reg = nti.build_starters(processed_root=tmp_path, date_str="2026-10-21", slate_phase="regular")
    assert set(reg["exp_min_source"]) == {"nba_starters_v1:2027_any_phase:last4"}  # 4 = the three earlier games + the 10-09 one


def test_reachability_starter_flags_on_vs_off(tmp_path):
    rows = []
    for k, date in enumerate(["2026-10-02", "2026-10-04", "2026-10-06"]):
        rows += _check_rows(date, f"e{k}", 2027, "preseason", "BOS", ["Jayson Tatum", "Jaylen Brown"], ["Sam Hauser"])
    _write_checks(tmp_path, rows)
    team_df = pd.DataFrame({"player_name": ["Jayson Tatum", "Jaylen Brown", "Sam Hauser"], "team": ["BOS"] * 3})
    with mock.patch.dict(os.environ, {"SYNDICATE_NBA_TEAM_INPUTS": "1"}):
        on, diag = bpss._merge_pregame_expected_minutes_for_team_local(
            processed_root=tmp_path, team_df=team_df, date_str="2026-10-09", team_tri="BOS", league_code="nba")
    assert diag["applied"] is True, diag
    assert on.set_index("player_name")["starter_prob"].to_dict() == {"Jayson Tatum": 1.0, "Jaylen Brown": 1.0, "Sam Hauser": 0.0}
    bpss._PREGAME_EXPECTED_MINUTES_CACHE_LOCAL.clear()
    with mock.patch.dict(os.environ, {"SYNDICATE_NBA_TEAM_INPUTS": "0"}):
        off, diag_off = bpss._merge_pregame_expected_minutes_for_team_local(
            processed_root=tmp_path, team_df=team_df, date_str="2026-10-09", team_tri="BOS", league_code="nba")
    assert diag_off["reason"] == "missing_pregame_expected_minutes"
    assert "starter_prob" not in off.columns
    # WNBA calls never invoke the NBA producer
    with mock.patch.object(nti, "ensure_starters") as ensure:
        bpss._load_pregame_expected_minutes_local(processed_root=tmp_path, date_str="2026-10-10", league_code="wnba")
    ensure.assert_not_called()
