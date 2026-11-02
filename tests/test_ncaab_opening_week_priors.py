"""Opening week: the NCAAB live re-sim must not refuse every game once a few finals exist.

Measured on the 2026-11-02 opener: `team_ratings_2027_asof_20261101` rated 4 teams and
`player_priors_2027_asof_20261102` held 4 teams, while the 361-team 2026 ratings and the 346-team
preseason player table sat unused -- `NCAAB_LIVE_RESIM_TICK live=7 resimmed=0 refused=7
refusals={'team_unrated': 7}`. The fallback is per game / per team now.
"""
from __future__ import annotations

import csv
import datetime as dt

from syndicate.features.ncaab import live_resim
from syndicate.features.ncaab import live_team_model as tm

GAME_DAY = dt.date(2026, 11, 2)


def _ratings(path, rows):
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["espn_id", "team", "adj_off", "adj_def", "tempo", "games", "prior_weight"])
        writer.writeheader()
        for tid, off, deff, tempo, games in rows:
            writer.writerow({"espn_id": tid, "team": f"T{tid}", "adj_off": off, "adj_def": deff, "tempo": tempo, "games": games, "prior_weight": 0.5})


def _players(path, team_rows):
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["team_id", "athlete_id", "source"])
        writer.writeheader()
        for tid, aid, source in team_rows:
            writer.writerow({"team_id": tid, "athlete_id": aid, "source": source})


def test_a_game_with_an_unrated_team_is_priced_off_last_seasons_table(tmp_path):
    _ratings(tmp_path / "team_ratings_2027_asof_20261101.csv", [("1", 110, 100, 70, 1), ("4", 104, 101, 68, 1)])
    _ratings(tmp_path / "team_ratings_2026_asof_20260406.csv", [("1", 115, 95, 69, 33), ("2", 100, 105, 67, 31), ("4", 102, 103, 70, 30)])
    fallback = tm.prior_for_game(GAME_DAY, "1", "2", neutral=False, dirs=[tmp_path])
    assert not isinstance(fallback, tm.NcaabPriorRefusal)
    assert fallback.prior_season_fallback is True and fallback.ratings_season == 2026
    # Both teams rated this season: this season's table wins.
    in_season = tm.prior_for_game(GAME_DAY, "1", "4", neutral=False, dirs=[tmp_path])
    assert in_season.prior_season_fallback is False and in_season.ratings_season == 2027
    # A team in neither table still refuses by name -- never a league-average default.
    missing = tm.prior_for_game(GAME_DAY, "1", "999", neutral=False, dirs=[tmp_path])
    assert isinstance(missing, tm.NcaabPriorRefusal) and missing.reason == "team_unrated"


def test_no_table_this_season_still_uses_last_season(tmp_path):
    _ratings(tmp_path / "team_ratings_2026_asof_20260406.csv", [("1", 115, 95, 69, 33), ("2", 100, 105, 67, 31)])
    prior = tm.prior_for_game(GAME_DAY, "1", "2", neutral=True, dirs=[tmp_path])
    assert prior.prior_season_fallback is True


def test_a_team_that_has_not_played_takes_its_preseason_rows(tmp_path):
    _players(tmp_path / "player_priors_2027_asof_20261102.csv", [("1", "a1", "in_season"), ("1", "a2", "in_season")])
    _players(tmp_path / "player_preseason_2027_asof_20261101.csv", [("1", "a1", "preseason"), ("2", "b1", "preseason"), ("2", "b2", "preseason")])
    _players(tmp_path / "player_preseason_2027_asof_20261103.csv", [("3", "c1", "future")])  # dated after the game: ignored
    priors = live_resim.load_player_priors(GAME_DAY, dirs=[tmp_path])
    assert {r["source"] for r in priors.by_team["1"]} == {"in_season"}   # in-season rows are never overwritten
    assert [r["athlete_id"] for r in priors.by_team["2"]] == ["b1", "b2"]
    assert "3" not in priors.by_team


def test_without_a_preseason_table_the_in_season_table_is_unchanged(tmp_path):
    _players(tmp_path / "player_priors_2027_asof_20261102.csv", [("1", "a1", "in_season")])
    priors = live_resim.load_player_priors(GAME_DAY, dirs=[tmp_path])
    assert set(priors.by_team) == {"1"}
