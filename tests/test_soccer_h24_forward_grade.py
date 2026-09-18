# -*- coding: utf-8 -*-
"""scripts/soccer_season_audit/h24_forward_grade.py -- `#665`'s H24 grader.

End to end first: one frozen match, its ESPN result, a FotMob history and a football-data close must come out
graded with both arms, so a join that silently yields zero fails here rather than on 2026-10-15.
"""
import datetime as dt
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "soccer_season_audit"))

import h24_forward_grade as h  # noqa: E402

MID = "740777"
KICKOFF = "2026-09-19T14:00:00+00:00"


def _freeze(path: Path, home_mean=1.6, away_mean=1.1):
    match = {"match_id": MID, "kickoff": KICKOFF, "status_state": "pre",
             "matchup": {"home_team": "Arsenal", "away_team": "Chelsea"},
             "win_probability": {"home": 0.5, "draw": 0.25, "away": 0.25},
             "team_projection": {"home_mean": home_mean, "away_mean": away_mean},
             "total_distribution": {"mean": home_mean + away_mean, "over_2_5_probability": 0.52}}
    path.write_text(json.dumps({"league": "epl", "date": "2026-09-19", "service": "live-odds-worker",
                                "matches": {MID: {"frozen_at": "2026-09-19T13:30:00+00:00", "kickoff": KICKOFF,
                                                  "match": match, "player_props": []}}}), encoding="utf-8")


def _espn(home_goals, away_goals, completed=True):
    return {"header": {"competitions": [{
        "date": "2026-09-19T14:00Z",
        "status": {"type": {"name": "STATUS_FULL_TIME" if completed else "STATUS_POSTPONED", "completed": completed}},
        "competitors": [{"homeAway": "home", "score": str(home_goals), "team": {"id": "1", "displayName": "Arsenal"}},
                        {"homeAway": "away", "score": str(away_goals), "team": {"id": "2", "displayName": "Chelsea"}}]}]},
        "boxscore": {"teams": []}, "rosters": []}


def _fotmob(base_xg=2.5, window_xg=3.3, base_n=80, window_n=70):
    matches = []
    for i in range(base_n):                         # 2024-25: inside the base, outside a 2026-09 window
        matches.append({"match_id": f"b{i}", "league": "epl", "date": (dt.date(2024, 9, 1) + dt.timedelta(days=i)).isoformat(),
                        "shots": [{"xg": base_xg / 2}, {"xg": base_xg / 2}]})
    for i in range(window_n):                       # the trailing year before the match
        matches.append({"match_id": f"w{i}", "league": "epl", "date": (dt.date(2026, 7, 1) + dt.timedelta(days=i)).isoformat(),
                        "shots": [{"xg": window_xg}]})
    return {"matches": matches}


def _cache(tmp_path, home_goals=2, away_goals=1, with_close=True):
    cache, h24 = tmp_path / "fg", tmp_path / "h24"
    (cache / "freeze").mkdir(parents=True)
    (cache / "espn").mkdir(parents=True)
    (h24 / "fd").mkdir(parents=True)
    _freeze(cache / "freeze" / "epl__recommendations_prekickoff_2026-09-19.live-odds-worker.json")
    (cache / "espn" / f"epl__{MID}.json").write_text(json.dumps(_espn(home_goals, away_goals)), encoding="utf-8")
    (h24 / "fotmob_all.json").write_text(json.dumps(_fotmob()), encoding="utf-8")
    if with_close:
        (h24 / "fd" / "E0.csv").write_text("Date,HomeTeam,AwayTeam,AvgC>2.5,AvgC<2.5\n19/09/2026,Arsenal,Chelsea,1.90,1.95\n", encoding="latin-1")
    return cache, h24


# ---------------------------------------------------------------------------- end to end first

def test_one_frozen_finished_match_is_graded_with_both_arms_and_the_close(tmp_path):
    cache, h24 = _cache(tmp_path)
    r = h.grade(cache, h24, dt.date(2026, 9, 20))
    assert r["funnel"]["covered"] == 1 and r["coverage"]["intersection_graded"] == 1
    p = r["pooled"]
    assert p["n"] == 1
    lam0 = 2.7
    # window mean 3.3 over a base of 2.5 is 1.32, which the registered clamp cuts to 1.20
    assert p["bias_p0"] == pytest.approx(3.0 - lam0)
    assert p["bias_xe"] == pytest.approx(3.0 - lam0 * 1.20)
    assert p["ll_p0"] == pytest.approx(-math.log(h.over25(lam0)))
    assert r["per_league"]["epl"]["closing_n"] == 1
    assert r["factor_one_by_thin_window"] == 0
    assert r["verdict"] == "WATCHING"
    assert r["coverage"]["fotmob"]["epl"]["base_matches"] >= 80


def test_a_postponed_match_or_one_before_the_window_is_not_graded(tmp_path):
    cache, h24 = _cache(tmp_path)
    (cache / "espn" / f"epl__{MID}.json").write_text(json.dumps(_espn(0, 0, completed=False)), encoding="utf-8")
    r = h.grade(cache, h24, dt.date(2026, 9, 20))
    assert r["funnel"].get("finished", 0) == 0 and r["pooled"]["n"] == 0


def test_a_league_without_a_fotmob_base_is_counted_not_silently_dropped(tmp_path):
    cache, h24 = _cache(tmp_path)
    (h24 / "fotmob_all.json").write_text(json.dumps({"matches": []}), encoding="utf-8")
    r = h.grade(cache, h24, dt.date(2026, 9, 20))
    assert r["funnel"]["no_fotmob_base"] == 1 and r["pooled"]["n"] == 0


# ---------------------------------------------------------------------------- the predictor, as registered

def test_factor_is_the_window_over_the_base_clamped():
    rows = [(dt.date(2026, 1, 1) + dt.timedelta(days=i), 3.0) for i in range(60)]
    assert h.factor(rows, 3.0, dt.date(2026, 6, 1))[0] == pytest.approx(1.0)
    assert h.factor(rows, 2.0, dt.date(2026, 6, 1))[0] == pytest.approx(1.20)          # 1.5 clamps to 1.20
    assert h.factor(rows, 4.0, dt.date(2026, 6, 1))[0] == pytest.approx(0.85)          # 0.75 clamps to 0.85
    rows_mid = [(dt.date(2026, 1, 1) + dt.timedelta(days=i), 3.3) for i in range(60)]
    assert h.factor(rows_mid, 3.0, dt.date(2026, 6, 1))[0] == pytest.approx(1.10)


def test_fewer_than_60_window_matches_gives_factor_one_and_says_so():
    rows = [(dt.date(2026, 1, 1) + dt.timedelta(days=i), 5.0) for i in range(59)]
    f, n, thin = h.factor(rows, 2.0, dt.date(2026, 6, 1))
    assert (f, n, thin) == (1.0, 59, True)


def test_the_window_is_the_365_days_before_the_match_and_excludes_its_own_day():
    day = dt.date(2026, 9, 20)
    rows = [(day, 9.0)] + [(day - dt.timedelta(days=366), 9.0)] + [(day - dt.timedelta(days=i), 3.0) for i in range(1, 61)]
    f, n, _ = h.factor(rows, 3.0, day)
    assert n == 60 and f == pytest.approx(1.0)


def test_base_seasons_differ_for_mls():
    assert h.base_range("mls") == (dt.date(2024, 1, 1), dt.date(2025, 12, 31))
    assert h.base_range("epl") == (dt.date(2024, 7, 1), dt.date(2026, 6, 30))
    rows = [(dt.date(2026, 3, 1), 3.0), (dt.date(2025, 3, 1), 2.0)]
    assert h.xg_base(rows, "mls") == (2.0, 1)        # the 2026 MLS match is NOT base
    assert h.xg_base(rows, "epl") == (2.5, 2)


def test_over25_is_the_poisson_tail():
    lam = 2.7
    direct = 1.0 - sum(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(3))
    assert h.over25(lam) == pytest.approx(direct)


def test_fotmob_totals_sum_both_sides_and_dedupe_match_ids():
    payload = {"matches": [{"match_id": 1, "league": "epl", "date": "2026-01-01", "shots": [{"xg": 0.4}, {"xg": 1.1}]},
                           {"match_id": 1, "league": "epl", "date": "2026-01-01", "shots": [{"xg": 9.0}]},
                           {"match_id": 2, "league": "epl", "date": "2026-01-02", "shots": []}]}
    assert h.fotmob_totals(payload) == {"epl": [(dt.date(2026, 1, 1), pytest.approx(1.5))]}


# ---------------------------------------------------------------------------- verdict, as registered

@pytest.mark.parametrize("n,ll0,llx,b0,bx,today,expected", [
    (149, 0.68, 0.66, 0.3, 0.1, dt.date(2026, 10, 14), "WATCHING"),
    (40, 0.68, 0.66, 0.3, 0.1, dt.date(2026, 10, 15), "MET"),          # on the date, whatever n is -- no INSUFFICIENT
    (150, 0.68, 0.66, 0.3, 0.1, dt.date(2026, 9, 30), "MET"),
    (150, 0.66, 0.68, 0.3, 0.1, dt.date(2026, 9, 30), "FALSIFIED"),    # log loss worse
    (150, 0.68, 0.66, 0.1, 0.3, dt.date(2026, 9, 30), "FALSIFIED"),    # bias worse
    (150, 0.68, 0.66, 0.2, -0.2, dt.date(2026, 9, 30), "FALSIFIED"),   # equal |bias| is not smaller
    (0, float("nan"), float("nan"), float("nan"), float("nan"), dt.date(2026, 10, 15), "NO MATCHES"),
])
def test_verdict(n, ll0, llx, b0, bx, today, expected):
    assert h.verdict(n, ll0, llx, b0, bx, today) == expected
