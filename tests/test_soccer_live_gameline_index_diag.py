"""Soccer's live game-line join must survive a match IN PLAY, and its zero must say why.

WHY `[lane soccer-live-gameline-index-diag, 2026-09-30]`. `attach_live_gamelines_for_sport`
assigned `index_diag` only in its non-soccer branch, then passed it to
`_attribute_live_gameline_zero` for every sport. Soccer's EMPTY index returns early with a
named reason, so the crash fired on the other path: a soccer match in play. Read on the
local production fleet 2026-09-30/10-01: `BOOK_GRID_LIVE_GAMELINE_FAILURE sport=soccer`
(76 times in one refresh-worker.log), each followed by `LIVE_GAMELINE_BUILD sport=soccer
... index=na ... written=0`. Soccer live game-lines were never built in exactly the windows
they exist for. The exception was caught and logged, so nothing else noticed.

THE SECOND HALF IS THE RULE, NOT THE CRASH. Setting `index_diag = {}` for soccer would stop
the raise and then label the zero "no soccer game in play" -- the counters read 0 because
nobody filled them, and an unknown read as the permissive answer. Absent diagnostics now
say so.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import soccer_live_gameline_source as src
from syndicate.features.shared.board_enrichment import (
    _attribute_live_gameline_zero,
    attach_live_gamelines_for_sport,
)

DATE = "2026-09-30"


def _live_game(event_id, away, home, league="epl"):
    return {"event_id": event_id, "league": league, "away_team": away, "home_team": home,
            "status_display_clock": "30'", "score_home": 0, "score_away": 0,
            "generated_at": "2026-09-30T19:00:00+00:00",
            "projection": {"simulations": 80, "home_win_probability": 0.5,
                           "draw_probability": 0.27, "away_win_probability": 0.23,
                           "projected_final_home_goals": 1.4,
                           "projected_final_away_goals": 1.1,
                           "projected_final_total": 2.5, "over_2_5_probability": 0.5}}


def _board_row(away, home):
    return {"kind": "game", "market": "h2h", "segment": "full", "away_team": away,
            "home_team": home, "game": {"state": "live"}, "age_seconds": 5, "projection": {}}


@pytest.fixture
def two_matches_in_play(monkeypatch):
    # Patched at the producer's READER, so the real index builder and the real
    # `_CanonicalMatchIndex` run -- the crash path is everything downstream of it.
    games = [_live_game("1", "Chelsea", "Brentford"), _live_game("2", "Watford", "Bristol City")]
    monkeypatch.setattr(src, "soccer_live_games", lambda *_a, **_k: [dict(g) for g in games])


def test_a_match_in_play_with_no_board_row_does_not_crash_and_names_the_join(two_matches_in_play):
    """The reported crash. Fails on the pre-fix code with UnboundLocalError (caught inside,
    so it surfaces as `error: live gameline join failed`)."""
    cov = attach_live_gamelines_for_sport([], sport="soccer", selected_date=DATE)
    assert "error" not in cov, cov
    assert cov["supported"] is True
    assert cov["rows_live_gameline_projected"] == 0
    # Two matches indexed, nothing on the board to price them against -- the JOIN, not the
    # producer, and never "nothing in play".
    assert "2 soccer game(s) indexed from 2" in cov["reason"]
    assert "no board row matched" in cov["reason"]
    assert "no soccer game in play" not in cov["reason"]
    assert cov["index_diagnostics"]["source"] == "soccer_live_state"
    assert cov["index_diagnostics"]["indexed"] == 2


def test_a_match_in_play_with_a_board_row_reaches_the_pricer(two_matches_in_play):
    """The non-crash branch past the join: a row was considered, so the reason (if any)
    comes from `withheld_by_reason`, and nothing raises on the way."""
    cov = attach_live_gamelines_for_sport(
        [_board_row("Chelsea", "Brentford")], sport="soccer", selected_date=DATE)
    assert "error" not in cov, cov
    assert cov["rows_live_gameline_considered"] == 1


def test_an_empty_soccer_index_keeps_its_named_early_return(monkeypatch):
    monkeypatch.setattr(src, "soccer_live_games", lambda *_a, **_k: [])
    cov = attach_live_gamelines_for_sport([], sport="soccer", selected_date=DATE)
    assert cov["reason"] == "no soccer match in play in any league's live-state artifact"


@pytest.mark.parametrize("diag", [None, {}, [], {"games_in_snapshot": "many"}])
def test_absent_or_unreadable_diagnostics_never_read_as_nothing_in_play(diag):
    """Unknown must not default permissive: counters nobody filled are not a zero."""
    cov = {"rows_live_gameline_considered": 0, "rows_live_gameline_projected": 0}
    _attribute_live_gameline_zero(cov, diag, sport="soccer")
    assert "no soccer game in play" not in cov["reason"]
    assert "index diagnostics unavailable" in cov["reason"]
