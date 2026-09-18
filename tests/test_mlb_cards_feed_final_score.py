"""A past-date MLB game whose cached feed is Final carries the feed's score.

Lane `mlb-past-date-chip-score`. Measured 2026-09-18: the 09-15 slate's feeds
were Final on refresh-worker at every build behind the served board, but
`_games_from_daily_summary` copied only the feed's STATUS, `_apply_mlb_live_scores`
is gated to today, and the lens report carried `score: null` -- so every chip was
`final` with no score and `live_gameline_score` scored 0 of 15 games.

The first test drives the SAME chain production does (cards game -> lens merge ->
`build_game_chip`), because a score set on the cards dict under a key the chip
does not read would pass a narrower test and fix nothing.
"""
from __future__ import annotations

from syndicate.features.mlb import cards
from syndicate.features.shared.game_chip_scoreboard import build_game_chip

GAME_PK = 824466


def _feed(abstract: str, detailed: str, away_runs, home_runs) -> dict:
    teams = {"away": {}, "home": {}}
    if away_runs is not None:
        teams["away"]["runs"] = away_runs
    if home_runs is not None:
        teams["home"]["runs"] = home_runs
    return {
        "gameData": {"status": {"abstractGameState": abstract, "detailedState": detailed}},
        "liveData": {"linescore": {"teams": teams}},
    }


def _summary() -> dict:
    return {"date": "2026-09-15", "outputs": [{"game_pk": GAME_PK, "away": "LAD", "home": "CIN"}]}


def _game(feed: dict) -> dict:
    games = cards._games_from_daily_summary(_summary(), actual_games={GAME_PK: feed})
    assert len(games) == 1
    return games[0]


def _chip_scores(game: dict) -> tuple:
    chip = build_game_chip("mlb", game)
    return chip["state"], chip["away"]["score"], chip["home"]["score"]


def test_final_feed_with_scoreless_lens_row_reaches_the_chip_with_a_score():
    # The 09-15 shape: lens row Final, `score: null`, `matchup.score` absent.
    game = _game(_feed("Final", "Final", 4, 5))
    lens_row = {"gamePk": GAME_PK, "status": {"abstract": "Final", "detailed": "Final"}, "score": None}
    merged = cards._merge_live_lens_row_into_game(game, lens_row)
    assert _chip_scores(merged) == ("final", "4", "5")


def test_frozen_live_lens_score_does_not_overwrite_a_final_feed_score():
    # A lens row frozen mid-game at the midnight roll (`mlb-final-state-mapping`).
    game = _game(_feed("Final", "Final", 4, 5))
    lens_row = {
        "gamePk": GAME_PK,
        "status": {"abstract": "Live", "detailed": "In Progress"},
        "score": {"away": 2, "home": 3},
    }
    merged = cards._merge_live_lens_row_into_game(game, lens_row)
    assert _chip_scores(merged) == ("final", "4", "5")


def test_live_feed_sets_no_score_so_the_lens_still_owns_live_scores():
    game = _game(_feed("Live", "In Progress", 1, 0))
    assert "score" not in game
    lens_row = {
        "gamePk": GAME_PK,
        "status": {"abstract": "Live", "detailed": "In Progress"},
        "score": {"away": 2, "home": 0},
    }
    merged = cards._merge_live_lens_row_into_game(game, lens_row)
    assert merged["score"] == {"away": 2, "home": 0}


def test_final_feed_with_one_side_unreported_is_not_read_as_a_score():
    assert cards._source_final_score(_feed("Final", "Final", 4, None)) is None
    assert "score" not in _game(_feed("Final", "Final", 4, None))


def test_final_feed_with_a_shutout_keeps_the_zero():
    assert cards._source_final_score(_feed("Final", "Final", 0, 3)) == {"away": 0, "home": 3}
