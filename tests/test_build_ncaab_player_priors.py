"""NCAAB player-prior producer (lane ncaab-native-live-tier)."""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_ncaab_player_priors", Path(__file__).resolve().parents[1] / "scripts" / "build_ncaab_player_priors.py"
)
pp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pp)

NAMES = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF"]


def _athlete(aid, name, starter, stats, dnp=False):
    return {"athlete": {"id": aid, "displayName": name}, "starter": starter, "didNotPlay": dnp, "stats": [] if dnp else stats}


def _payload():
    return {
        "header": {"id": "777"},
        "boxscore": {"players": [
            {"team": {"id": "10"}, "statistics": [{"names": NAMES, "athletes": [
                _athlete("1", "Ace", True, ["30", "20", "7-14", "2-5", "4-5", "6", "3", "2", "1", "0", "2", "4", "2"]),
                _athlete("2", "Bench", False, [], dnp=True),
                _athlete("3", "Broken", False, ["--", "", "", "", "", "", "", "", "", "", "", "", ""]),
            ]}]},
            {"team": {"id": "20"}, "statistics": [{"names": NAMES, "athletes": [
                _athlete("4", "Opp", True, ["40", "10", "4-9", "1-3", "1-2", "8", "5", "1", "0", "1", "1", "7", "3"]),
            ]}]},
        ]},
    }


def test_parse_player_box():
    rows = pp.parse_player_box(_payload(), season=2026, day="2026-01-10")
    by = {r["athlete_id"]: r for r in rows}
    assert set(by) == {"1", "2", "4"}, "an unreadable row is dropped, never zero-filled"
    ace = by["1"]
    assert (ace["min"], ace["pts"], ace["fgm"], ace["fga"], ace["threes"], ace["threes_att"], ace["ftm"], ace["fta"]) == (30, 20, 7, 14, 2, 5, 4, 5)
    assert (ace["oreb"], ace["dreb"], ace["reb"], ace["tov"], ace["pf"], ace["starter"], ace["opp_id"]) == (2, 4, 6, 2, 2, 1, "20")
    assert by["2"]["dnp"] == 1 and by["2"]["min"] == 0.0


def _rows(team="10", aid="1", games=6, minutes=30.0, pts=15.0, start_day=1, dnp_last=0):
    out = []
    for g in range(games):
        played = g < games - dnp_last
        out.append({"date": f"2026-01-{start_day + g:02d}", "game_id": f"{team}-{g}", "team_id": team, "athlete_id": aid,
                    "player_name": f"P{aid}", "starter": 1, "min": minutes if played else 0.0,
                    **{k: (pts if k == "pts" else 1.0) if played else 0.0 for k in pp.RATE_STATS}})
    return out


def test_no_leakage_strictly_before_as_of():
    rows = _rows(games=6)
    pri = pp.compute_priors(rows, as_of=dt.date(2026, 1, 4))
    assert pri[("10", "1")]["games"] == 3 and pri[("10", "1")]["last_game"] == "2026-01-03"


def test_shrinkage_toward_the_league():
    star = _rows(aid="1", games=10, minutes=35, pts=25)
    cameo = _rows(aid="2", games=10, minutes=35, pts=5)
    cameo = [{**r, "athlete_id": "3", "min": 2.0, "pts": 4.0} if i == 9 else {**r, "athlete_id": "3", "min": 0.0, "pts": 0.0}
             for i, r in enumerate(_rows(aid="3", games=10, minutes=35, pts=5))] + cameo
    pri = pp.compute_priors(star + cameo, as_of=dt.date(2026, 2, 1))
    league = (25 * 10 + 5 * 10 + 4) / (350 + 350 + 2)  # points per minute over every row
    raw_cameo = 4 / 2
    got = pri[("10", "3")]["pts_pm"]
    assert abs(got - league) < abs(raw_cameo - league), "a 2-minute cameo is mostly the league"
    assert pri[("10", "1")]["pts_pm"] == pytest.approx((250 + pp.SHRINK_MINUTES * league) / (350 + pp.SHRINK_MINUTES), rel=1e-3)


def test_out_of_rotation_is_dropped():
    rows = _rows(aid="1", games=8, dnp_last=pp.MISSED_GAMES_OUT) + _rows(aid="2", games=8)
    pri = pp.compute_priors(rows, as_of=dt.date(2026, 2, 1))
    assert ("10", "1") not in pri and ("10", "2") in pri


def test_minutes_and_starter_share_are_recent():
    rows = _rows(aid="1", games=10, minutes=10)
    for r in rows[-pp.RECENT_GAMES:]:
        r["min"], r["starter"] = 30.0, 1
    for r in rows[:-pp.RECENT_GAMES]:
        r["starter"] = 0
    pri = pp.compute_priors(rows, as_of=dt.date(2026, 2, 1))[("10", "1")]
    assert pri["min_proj"] == 30.0 and pri["starter_prob"] == 1.0


def test_last_season_feeds_rates_not_minutes():
    cur = _rows(aid="1", games=2, minutes=20, pts=2) + _rows(aid="9", games=2, minutes=20, pts=10)
    prev = [{**r, "date": "2025-02-01"} for r in _rows(aid="1", games=20, minutes=30, pts=20, start_day=1)]
    with_prev = pp.compute_priors(cur, as_of=dt.date(2026, 2, 1), prior_rows=prev)[("10", "1")]
    without = pp.compute_priors(cur, as_of=dt.date(2026, 2, 1))[("10", "1")]
    assert with_prev["pts_pm"] > without["pts_pm"] and with_prev["min_proj"] == without["min_proj"] == 20
    assert with_prev["prior_season_minutes"] == 600


def test_d1_filter():
    rows = _rows(team="10") + _rows(team="99", aid="5")
    pri = pp.compute_priors(rows, as_of=dt.date(2026, 2, 1), d1={"10": "Home U"})
    assert set(t for t, _ in pri) == {"10"}


def test_priors_table_is_dated_and_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "processed_dir", lambda: tmp_path)
    pri = pp.compute_priors(_rows(), as_of=dt.date(2026, 2, 1))
    path = pp.write_priors(2026, dt.date(2026, 2, 1), pri)
    assert path.name == "player_priors_2026_asof_20260201.csv" and not list(tmp_path.glob("*.tmp"))
    text = path.read_text(encoding="utf-8").splitlines()
    assert text[0].split(",") == list(pp.PRIOR_FIELDS) and len(text) == 2
