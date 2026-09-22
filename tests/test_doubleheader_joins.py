"""An MLB doubleheader is TWO games at every join that keys a game by team pair.

Measured on production 2026-09-22, TB @ NYY split doubleheader:

    StatsAPI   G1 gamePk 823543  gameDate 17:05Z   G2 823494  gameDate 23:05Z
    OddsAPI    G1 event 394e1e2b commence 17:06Z   G2 574050c1 commence 23:06Z

and every team-pair join kept ONE of them for both: game 2's Layer 2 rows read
game 1's chip (`12:05P CT`), game 1's moneyline read game 2's sim (home 0.531
vs its own 0.606), game 2's props read game 1's projections and game 1's
Kalshi ticker, and game 1's MLB card carried game 2's odds.

These tests use the production shape (two games, same pair, ~6 h apart) and
call the real join functions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import board_enrichment as BE
from syndicate.features.shared import doubleheader as DH

G1_START = "2026-09-22T17:05:00Z"
G2_START = "2026-09-22T23:05:00Z"
G1_COMMENCE = "2026-09-22T17:06:00Z"
G2_COMMENCE = "2026-09-22T23:06:00Z"


# --- the rule itself ---------------------------------------------------------


def test_nearest_start_separates_the_two_halves():
    games = [{"pk": 823543, "start": G1_START}, {"pk": 823494, "start": G2_START}]
    for commence, pk in ((G1_COMMENCE, 823543), (G2_COMMENCE, 823494)):
        hit, reason = DH.pick_by_start_time(games, commence, start_of=lambda g: g["start"])
        assert (hit["pk"], reason) == (pk, DH.NEAREST_START)


def test_candidate_order_does_not_decide():
    games = [{"pk": 823494, "start": G2_START}, {"pk": 823543, "start": G1_START}]
    hit, _ = DH.pick_by_start_time(games, G1_COMMENCE, start_of=lambda g: g["start"])
    assert hit["pk"] == 823543


@pytest.mark.parametrize(
    "target, starts, reason",
    [
        (None, [G1_START, G2_START], DH.AMBIGUOUS_NO_TARGET_TIME),
        (G1_COMMENCE, [G1_START, None], DH.AMBIGUOUS_NO_CANDIDATE_TIME),
        (G1_COMMENCE, [None, None], DH.AMBIGUOUS_NO_CANDIDATE_TIME),
        # Two games inside the separation window cannot be told apart on time.
        ("2026-09-22T17:30:00Z", ["2026-09-22T17:05:00Z", "2026-09-22T17:55:00Z"], DH.AMBIGUOUS_NOT_SEPARABLE),
    ],
)
def test_a_pair_it_cannot_separate_returns_nothing(target, starts, reason):
    games = [{"start": s} for s in starts]
    assert DH.pick_by_start_time(games, target, start_of=lambda g: g["start"]) == (None, reason)


def test_a_single_candidate_is_kept_without_a_gap_bound():
    only = {"start": G1_START}
    assert DH.pick_by_start_time([only], G2_COMMENCE, start_of=lambda g: g["start"]) == (only, DH.SINGLE)


def test_max_gap_refuses_a_lone_game_from_another_day():
    # Tomorrow's game of the series, with only today's game as a candidate.
    only = {"start": G1_START}
    hit, reason = DH.pick_by_start_time(
        [only], "2026-09-23T17:06:00Z", start_of=lambda g: g["start"], max_gap_seconds=DH.MAX_SAME_GAME_GAP_SECONDS
    )
    assert (hit, reason) == (None, DH.BEYOND_MAX_GAP)


def test_central_clock_reads_the_lens_start():
    assert DH.central_clock_start_epoch("2026-09-22", "12:05 PM") == DH.start_epoch(G1_START)
    assert DH.central_clock_start_epoch("2026-09-22", "6:05 PM") == DH.start_epoch(G2_START)
    assert DH.central_clock_start_epoch("2026-09-22", "Postponed") is None
    assert DH.central_clock_start_epoch("", "6:05 PM") is None


# --- the Layer 2 game block (chip join) -------------------------------------


def _chip(start, token, state="pregame"):
    return {
        "home": {"name": "New York Yankees", "abbr": "NYY"},
        "away": {"name": "Tampa Bay Rays", "abbr": "TB"},
        "state": state,
        "start_time_utc": start,
        "status_token": token,
        "matchup": "TB @ NYY",
    }


def _grid_row(commence):
    return {"home_team": "New York Yankees", "away_team": "Tampa Bay Rays", "commence_time": commence}


@pytest.fixture
def chips(monkeypatch):
    import syndicate.features.shared.game_chip_scoreboard as gcs

    def _install(by_date):
        def fake(date_str, sports):
            return list(by_date.get(date_str, []))

        monkeypatch.setattr(gcs, "build_game_chips", fake)

    return _install


def test_each_half_of_a_doubleheader_gets_its_own_chip(chips):
    # Production order: game 1's chip first, which is the one both halves took.
    chips({"2026-09-22": [_chip(G1_START, "12:05P CT", "live"), _chip(G2_START, "6:05P CT")]})
    grid = [_grid_row(G1_COMMENCE), _grid_row(G2_COMMENCE)]
    coverage = BE.attach_game_state(grid, sport="mlb", selected_date="2026-09-22")
    assert grid[0]["game"]["start_time_utc"] == G1_START
    assert grid[0]["game"]["state"] == "live"
    assert grid[1]["game"]["start_time_utc"] == G2_START
    assert grid[1]["game"]["status_token"] == "6:05P CT"
    assert grid[1]["game"]["state"] == "pregame"
    assert coverage["rows_matched"] == 2
    assert coverage["rows_resolved_by_start_time"] == 2


def test_tomorrows_series_game_does_not_take_todays_chip(chips):
    tomorrow_start = "2026-09-23T17:05:00Z"
    chips({
        "2026-09-22": [_chip(G1_START, "FINAL", "final")],
        "2026-09-23": [_chip(tomorrow_start, "12:05P CT")],
    })
    grid = [_grid_row("2026-09-23T17:06:00Z")]
    BE.attach_game_state(grid, sport="mlb", selected_date="2026-09-22")
    assert grid[0]["game"]["start_time_utc"] == tomorrow_start
    assert grid[0]["game"]["state"] == "pregame"


def test_an_mlb_row_whose_only_chip_is_another_days_game_gets_no_block(chips):
    chips({"2026-09-22": [_chip(G1_START, "FINAL", "final")]})
    grid = [_grid_row("2026-09-23T17:06:00Z")]
    coverage = BE.attach_game_state(grid, sport="mlb", selected_date="2026-09-22")
    assert "game" not in grid[0]
    assert coverage["rows_refused_other_day_game"] == 1


def test_a_row_with_no_start_time_is_refused_when_the_pair_is_ambiguous(chips):
    chips({"2026-09-22": [_chip(G1_START, "12:05P CT"), _chip(G2_START, "6:05P CT")]})
    grid = [_grid_row(None)]
    coverage = BE.attach_game_state(grid, sport="mlb", selected_date="2026-09-22")
    assert "game" not in grid[0]
    assert coverage["rows_ambiguous_game"] == 1


# --- the live-lens state overlay --------------------------------------------


def _lens_game(pk, start_clock, abstract, detailed=""):
    return {
        "gamePk": pk,
        "startTime": start_clock,
        "status": {"abstract": abstract, "detailed": detailed},
        "away": {"abbr": "TB", "name": "Tampa Bay Rays"},
        "home": {"abbr": "NYY", "name": "New York Yankees"},
        "matchup": {"score": {"away": 1, "home": 0}},
    }


@pytest.fixture
def lens(monkeypatch):
    def _install(*games):
        import syndicate.features.shared.refresh_state_store as store

        generated = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        snapshot = {"date": "2026-09-22", "generatedAt": generated, "games": list(games)}
        monkeypatch.setattr(store, "read_json_file", lambda *_a, **_k: snapshot)

    return _install


def _board_row(commence, state):
    return {**_grid_row(commence), "game": {"state": state, "status_token": ""}}


def test_game_one_going_live_leaves_game_two_pregame(lens):
    # Snapshot order as served: game 1 first.
    lens(_lens_game(823543, "12:05 PM", "Live", "In Progress"), _lens_game(823494, "6:05 PM", "Preview", "Scheduled"))
    grid = [_board_row(G1_COMMENCE, "pregame"), _board_row(G2_COMMENCE, "pregame")]
    coverage = BE.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-09-22")
    assert grid[0]["game"]["state"] == "live"
    assert grid[1]["game"]["state"] == "pregame"
    assert coverage["rows_corrected"] == 1


def test_game_one_final_does_not_final_game_two(lens):
    lens(_lens_game(823543, "12:05 PM", "Final"), _lens_game(823494, "6:05 PM", "Live", "In Progress"))
    grid = [_board_row(G1_COMMENCE, "live"), _board_row(G2_COMMENCE, "pregame")]
    BE.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-09-22")
    assert grid[0]["game"]["state"] == "final"
    assert grid[1]["game"]["state"] == "live"


def test_a_tomorrow_row_in_todays_grid_is_not_corrected_from_todays_game(lens):
    lens(_lens_game(823543, "12:05 PM", "Final"))
    grid = [_board_row("2026-09-23T17:06:00Z", "pregame")]
    coverage = BE.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-09-22")
    assert grid[0]["game"]["state"] == "pregame"
    assert coverage["rows_refused_other_day_game"] == 1
