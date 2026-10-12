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


# ------------------------------------------------------------------ preseason (roster x last season)

def _prev(aid, team, games=10, minutes=30.0, pts=15.0, starter=1):
    return [{"date": f"2026-01-{g + 1:02d}", "game_id": f"{team}-{g}", "team_id": team, "athlete_id": aid,
             "player_name": f"P{aid}", "starter": starter, "min": minutes, **{k: (pts if k == "pts" else 1.0) for k in pp.RATE_STATS}}
            for g in range(games)]


def test_preseason_sources_rates_and_minutes():
    prev = _prev("1", "10") + _prev("2", "20", minutes=20, starter=0) + _prev("9", "10", minutes=10)
    roster = {"10": [{"athlete_id": "1", "player_name": "Ret", "experience": "Senior"},
                     {"athlete_id": "2", "player_name": "Xfer", "experience": "Junior"},
                     {"athlete_id": "3", "player_name": "Frosh", "experience": "Freshman"}]}
    pre = pp.compute_preseason(roster, prev)
    assert {k[1]: v["prior_source"] for k, v in pre.items()} == {"1": "returning", "2": "transfer", "3": "newcomer"}
    assert pre[("10", "1")]["min_proj"] == 30.0 and pre[("10", "1")]["starter_prob"] == 1.0
    assert pre[("10", "2")]["min_proj"] == 20.0 and pre[("10", "2")]["starter_prob"] == 0.0
    assert pre[("10", "3")]["min_proj"] == pp.NEWCOMER_MINUTES and pre[("10", "3")]["prior_season_minutes"] == 0.0
    league_pts = (15 * 10 * 3) / (300 + 200 + 100)  # 15 points a game each, per minute over all minutes
    assert pre[("10", "3")]["pts_pm"] == pytest.approx(round(league_pts, 5))


def test_a_stale_roster_is_excluded_not_projected():
    """ESPN served last season's roster for most teams on 2026-10-12: a 'Freshman' with D-I box rows."""
    prev = _prev("1", "10") + _prev("5", "10", minutes=15)
    stale_roster = {"10": [{"athlete_id": "1", "experience": "Senior"}, {"athlete_id": "5", "experience": "Freshman"},
                           {"athlete_id": "7", "experience": "Freshman"}]}
    out: dict = {}
    assert pp.compute_preseason(stale_roster, prev, stale_out=out) == {}
    assert out == {"10": "freshman_with_prior_season_box"}
    all_returning = {"10": [{"athlete_id": "1", "experience": "Senior"}, {"athlete_id": "5", "experience": "Sophomore"}]}
    out = {}
    assert pp.compute_preseason(all_returning, prev, stale_out=out) == {}
    assert out == {"10": "returning_share_at_or_above_stale_floor"}


def test_preseason_blends_into_early_season_minutes_then_fades():
    pre = {("10", "1"): {"min_proj": 30.0, "starter_prob": 1.0}}
    early = _rows(aid="1", games=1, minutes=10)
    blended = pp.compute_priors(early, as_of=dt.date(2026, 2, 1), preseason=pre)[("10", "1")]
    w = pp.PRESEASON_WEIGHT_GAMES * (pp.PRESEASON_FADE_GAMES - 1) / pp.PRESEASON_FADE_GAMES
    assert blended["min_proj"] == pytest.approx(round((10 + w * 30) / (1 + w), 2), abs=0.01)
    assert blended["prior_source"] == "in_season+preseason"
    late = _rows(aid="1", games=pp.PRESEASON_FADE_GAMES, minutes=10)
    faded = pp.compute_priors(late, as_of=dt.date(2026, 2, 1), preseason=pre)[("10", "1")]
    assert faded["min_proj"] == 10.0 and faded["prior_source"] == "in_season"


def test_no_prior_season_box_refuses_to_write(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "processed_dir", lambda: tmp_path)
    monkeypatch.setattr(pp.ratings, "load_registry", lambda: {"10": "Home U"})
    monkeypatch.setattr(pp, "fetch_roster", lambda tid: [{"athlete_id": "1", "player_name": "A", "experience": "Senior"}])
    monkeypatch.setattr(pp.time, "sleep", lambda s: None)
    out = pp.build_preseason(2027, dt.date(2026, 10, 12), rate=100)
    assert "refused" in out and not list(tmp_path.glob("player_priors_*"))
