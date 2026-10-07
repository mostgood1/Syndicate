"""NCAAB team ratings producer (lane intelligence-evidence-coverage)."""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_ncaab_team_ratings", Path(__file__).resolve().parents[1] / "scripts" / "build_ncaab_team_ratings.py"
)
ratings = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ratings)


def _summary(home=("265", "Washington State", 65), away=("2250", "Gonzaga", 86), neutral=False):
    def box(tid, name, fga, oreb, tov, fta):
        return {
            "team": {"id": tid, "location": name},
            "statistics": [
                {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": f"20-{fga}"},
                {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": f"10-{fta}"},
                {"name": "offensiveRebounds", "displayValue": str(oreb)},
                {"name": "totalTurnovers", "displayValue": str(tov)},
            ],
        }

    return {
        "header": {
            "id": "401829197",
            "season": {"year": 2026, "type": 2},
            "competitions": [
                {
                    "neutralSite": neutral,
                    "competitors": [
                        {"id": home[0], "homeAway": "home", "score": str(home[2])},
                        {"id": away[0], "homeAway": "away", "score": str(away[2])},
                    ],
                }
            ],
        },
        "boxscore": {"teams": [box(away[0], away[1], 68, 17, 8, 17), box(home[0], home[1], 52, 10, 17, 20)]},
    }


def test_season_calendar():
    assert ratings.default_season(dt.date(2026, 10, 7)) == 2026  # offseason -> last completed
    assert ratings.default_season(dt.date(2026, 11, 20)) == 2027
    assert ratings.default_season(dt.date(2027, 2, 1)) == 2027
    days = ratings.season_dates(2026, dt.date(2026, 10, 7))
    assert days[0] == dt.date(2025, 11, 1) and days[-1] == dt.date(2026, 4, 15)
    assert ratings.season_dates(2027, dt.date(2026, 10, 7)) == []


def test_parse_summary_builds_both_sides_with_one_possession_count():
    rows = ratings.parse_summary(_summary(), season=2026, day="2026-01-15")
    by_team = {r["team"]: r for r in rows}
    assert set(by_team) == {"Gonzaga", "Washington State"}
    gonzaga, wsu = by_team["Gonzaga"], by_team["Washington State"]
    # (68-17+8+0.475*17 + 52-10+17+0.475*20) / 2
    assert gonzaga["poss"] == wsu["poss"] == round((68 - 17 + 8 + 0.475 * 17 + 52 - 10 + 17 + 0.475 * 20) / 2, 2)
    assert gonzaga["site"] == "away" and wsu["site"] == "home"
    assert gonzaga["pts"] == 86 and gonzaga["opp_pts"] == 65


def test_neutral_site_is_neutral_for_both():
    rows = ratings.parse_summary(_summary(neutral=True), season=2026, day="2026-03-20")
    assert {r["site"] for r in rows} == {"neutral"}


def test_incomplete_box_is_skipped_not_guessed():
    payload = _summary()
    payload["boxscore"]["teams"][0]["statistics"] = []
    assert ratings.parse_summary(payload, season=2026, day="2026-01-15") == []


def _game(gid, a, b, a_pts, b_pts, poss=70.0, site_a="neutral"):
    site_b = {"home": "away", "away": "home", "neutral": "neutral"}[site_a]
    return [
        {"game_id": gid, "team_id": a, "opp_id": b, "pts": a_pts, "opp_pts": b_pts, "poss": poss, "site": site_a},
        {"game_id": gid, "team_id": b, "opp_id": a, "pts": b_pts, "opp_pts": a_pts, "poss": poss, "site": site_b},
    ]


def test_strength_of_schedule_separates_equal_raw_margins():
    d1 = {"A": "A", "B": "B", "C": "C", "D": "D"}
    rows = []
    # A and D both beat their opponent by 10 every time; A plays the strong team, D the weak one.
    rows += _game("1", "A", "B", 80, 70) + _game("2", "A", "B", 80, 70)
    rows += _game("3", "D", "C", 80, 70) + _game("4", "D", "C", 80, 70)
    rows += _game("5", "B", "C", 90, 60) + _game("6", "B", "C", 90, 60)
    out = ratings.compute_ratings(rows, d1)
    assert out["A"]["adj_em"] > out["D"]["adj_em"]
    assert out["B"]["adj_em"] > out["C"]["adj_em"]


def test_home_court_is_discounted():
    d1 = {"A": "A", "B": "B"}
    neutral = ratings.compute_ratings(_game("1", "A", "B", 75, 70), d1)
    at_home = ratings.compute_ratings(_game("1", "A", "B", 75, 70, site_a="home"), d1)
    assert at_home["A"]["adj_em"] < neutral["A"]["adj_em"]


def test_non_d1_games_are_excluded():
    d1 = {"A": "A", "B": "B"}
    rows = _game("1", "A", "B", 75, 70) + _game("2", "A", "X", 120, 40)
    assert ratings.compute_ratings(rows, d1)["A"]["games"] == 1


def test_prior_season_steadies_early_season_only():
    d1 = {"A": "A", "B": "B"}
    prior = {"A": {"adj_off": 120.0, "adj_def": 90.0, "tempo": 70.0}, "B": {"adj_off": 95.0, "adj_def": 110.0, "tempo": 70.0}}
    one_game = ratings.compute_ratings(_game("1", "A", "B", 70, 75), d1, prior=prior)
    assert one_game["A"]["prior_weight"] == pytest.approx(8 / 9, abs=1e-3)
    no_prior = ratings.compute_ratings(_game("1", "A", "B", 70, 75), d1)
    assert one_game["A"]["adj_em"] > no_prior["A"]["adj_em"]


def test_ratings_file_is_dated_and_readable_by_the_season_reader(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_NCAAB_SOURCE_ROOT", raising=False)
    d1 = {"2250": "Gonzaga", "265": "Washington State"}
    out = ratings.compute_ratings(ratings.parse_summary(_summary(), season=2026, day="2026-01-15"), d1)
    path = ratings.write_ratings(2026, out, d1, dt.date(2026, 4, 6))
    assert path.name == "team_ratings_2026_asof_20260406.csv"

    from syndicate.features import intelligence_season_evidence as se

    se._CACHE.clear()
    se._TABLES_MEMO.clear()
    rows = se.readiness_rows("ncaab", dt.date(2026, 10, 7))
    assert rows[0]["exists"] is True and rows[0]["row_count"] == 2


def test_fleet_supervisor_runs_the_producer_daily_without_publish():
    from scripts import local_production as lp

    jobs = {job.name: job for job in lp.SCHEDULED_JOBS}
    job = jobs["ncaab-team-ratings"]
    assert (job.hour, job.minute, job.weekday) == (10, 45, None)
    assert job.argv == ("scripts/build_ncaab_team_ratings.py",)
