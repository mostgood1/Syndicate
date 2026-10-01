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

import json

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


# --------------------------------------------------------------------------
# The producer gap: an EMPTY index has three causes, and only one is "nothing
# in play". All three used to return that reason.
# --------------------------------------------------------------------------

@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.data_root", lambda: tmp_path)
    return tmp_path


def _write_aggregate(root, games, *, date=DATE):
    d = root / "live"
    d.mkdir(parents=True, exist_ok=True)
    (d / "soccer_live_lens.json").write_text(json.dumps(
        {"date": date, "generated_at": "2026-09-30T19:00:00+00:00",
         "leagues_checked": ["epl"], "count": len(games), "games": games}),
        encoding="utf-8")


def test_a_readable_empty_aggregate_is_the_one_real_nothing_in_play(root):
    _write_aggregate(root, [])
    cov = attach_live_gamelines_for_sport([], sport="soccer", selected_date=DATE)
    assert cov["reason"] == "no soccer match in play in any league's live-state artifact"
    assert cov["index_diagnostics"]["artifact"] == "aggregate"
    assert cov["index_diagnostics"]["aggregate"] == "empty"


def test_matches_in_play_that_the_producer_drops_are_not_nothing_in_play(root):
    """Every in-play match lacks a projection. Pre-fix: "no soccer match in play"."""
    no_proj = [dict(_live_game(str(i), a, h), projection=None)
               for i, (a, h) in enumerate([("Chelsea", "Brentford"), ("Watford", "Bristol City")])]
    _write_aggregate(root, no_proj)
    cov = attach_live_gamelines_for_sport([], sport="soccer", selected_date=DATE)
    assert "no soccer match in play" not in cov["reason"]
    assert "2 soccer game(s) in the live snapshot but none indexed" in cov["reason"]
    assert "skipped_no_projection=2" in cov["reason"]


def test_an_ambiguous_pair_only_slate_names_the_ambiguity(root):
    _write_aggregate(root, [_live_game("1", "Chelsea", "Brentford"),
                            _live_game("2", "Chelsea", "Brentford")])
    cov = attach_live_gamelines_for_sport([], sport="soccer", selected_date=DATE)
    assert "skipped_ambiguous=2" in cov["reason"]
    assert "no soccer match in play" not in cov["reason"]


@pytest.mark.parametrize("setup, aggregate", [
    (lambda root: None, "absent"),
    (lambda root: _write_aggregate(root, [], date="1999-01-01"), "stale_date"),
])
def test_no_readable_artifact_is_unknown_not_nothing_in_play(root, setup, aggregate):
    setup(root)
    cov = attach_live_gamelines_for_sport([], sport="soccer", selected_date=DATE)
    assert "no soccer match in play" not in cov["reason"]
    assert "no soccer live-state artifact readable" in cov["reason"]
    assert f"aggregate={aggregate}" in cov["reason"]
    assert cov["index_diagnostics"]["artifact"] == "none"


def test_a_producer_that_reports_nothing_reads_as_unavailable(monkeypatch):
    """A games loader that fills no diagnostics (a fake, or a future caller) is
    unknown too."""
    monkeypatch.setattr(src, "soccer_live_gameline_index", lambda *_a, **_k: {})
    cov = attach_live_gamelines_for_sport([], sport="soccer", selected_date=DATE)
    assert "no soccer match in play" not in cov["reason"]


def test_every_in_play_match_lands_in_exactly_one_bucket(root):
    games = [
        _live_game("1", "Chelsea", "Brentford"),                       # indexed
        dict(_live_game("2", "Watford", "Bristol City"), projection=None),
        _live_game("3", "Sassuolo", "Monza"),
        _live_game("4", "Sassuolo", "Monza"),                          # ambiguous pair
        _live_game("5", "", "Lens"),                                   # no team name
    ]
    bad_p = _live_game("6", "Elche", "Espanyol")
    bad_p["projection"]["home_win_probability"] = 1.7
    games.append(bad_p)
    _write_aggregate(root, games)
    diag: dict = {}
    src.soccer_live_gameline_index(DATE, diagnostics=diag)
    assert diag["games_in_snapshot"] == 6
    assert diag["indexed"] == 1
    assert diag["skipped_no_projection"] == 1
    assert diag["skipped_ambiguous"] == 2
    assert diag["skipped_no_team_names"] == 1
    assert diag["skipped_no_probability"] == 1
    assert diag["indexed"] + sum(v for k, v in diag.items() if k.startswith("skipped_")) == 6


def test_an_empty_aggregate_still_falls_through_to_per_league_files(root):
    _write_aggregate(root, [])
    d = root / "soccer_source" / "epl" / "api" / "live_state"
    d.mkdir(parents=True)
    (d / f"live_state_{DATE}.json").write_text(json.dumps(
        {"league": "epl", "games": {"9": _live_game("9", "Chelsea", "Brentford")}}),
        encoding="utf-8")
    diag: dict = {}
    assert len(src.soccer_live_games(DATE, diagnostics=diag)) == 1
    assert diag["artifact"] == "per_league"
    assert diag["per_league_files"] == 1


@pytest.mark.parametrize("diag", [
    None, {}, [], {"games_in_snapshot": "many"},
    # PRESENT BUT NULL is still unknown. The first version of the guard read
    # `int(raw or 0)`, which turned all three into a real 0 before int() could
    # raise -- found by the owning lane against bc8a8340, 2026-09-30.
    {"games_in_snapshot": None}, {"games_in_snapshot": ""}, {"games_in_snapshot": []},
])
def test_absent_or_unreadable_diagnostics_never_read_as_nothing_in_play(diag):
    """Unknown must not default permissive: counters nobody filled are not a zero."""
    cov = {"rows_live_gameline_considered": 0, "rows_live_gameline_projected": 0}
    _attribute_live_gameline_zero(cov, diag, sport="soccer")
    assert "no soccer game in play" not in cov["reason"]
    assert "index diagnostics unavailable" in cov["reason"]


def test_a_real_zero_still_reads_as_nothing_in_play():
    """The guard must not swallow the honest state: a counted 0 IS nothing in play."""
    cov = {"rows_live_gameline_considered": 0, "rows_live_gameline_projected": 0}
    _attribute_live_gameline_zero(cov, {"games_in_snapshot": 0, "indexed": 0}, sport="soccer")
    assert cov["reason"] == "no soccer game in play in the published live snapshot"
