"""The live-gameline index named the team PAIR, so a doubleheader lost a game.

`build_live_gameline_index` mapped `(away_team, home_team)` to ONE projection
and stamped that projection's `game_pk`, so both of a doubleheader's odds events
were priced against whichever half happened to be live. Measured over production
ledgers 2026-09-22 (`.syndicate/findings_2026-09-22_ledger_key_clv_impact.md`):
the SECOND event's rows carry the FIRST game's score series, window and gamePk --
2026-09-04 DET@CLE 69 rows under 824424, 2026-08-29 AZ@SF 222 under 823177,
2026-08-29 BOS@NYY 137 under 823539.

The shapes here are production's, not invented:

  * a lens game carries `gamePk` and `startTime` as a CENTRAL CLOCK STRING --
    "1:10 PM" / "6:15 PM" for 824424 / 824387 on 2026-09-04, read off
    `mlb_source/data/live_lens/live_lens_report_2026_09_04.json`;
  * a book-grid game row carries `event_id` and `commence_time` at top level
    (read off `mlb_source/data/book_grid/book_grid_2026-09-22.json`).
"""

from __future__ import annotations

import datetime as dt

import pytest

from syndicate.features.shared.live_gameline_join import (
    REASON_GAME_AMBIGUOUS,
    LiveGamelineIndex,
    attach_live_gamelines,
    build_live_gameline_index,
    resolve_live_gameline,
)

PAIR = ("detroit tigers", "cleveland guardians")
SLATE = "2026-09-04"


def _lens_game(game_pk: int, clock: str, home_win_prob: float):
    """One production-shaped lens game with an accepted `live_resim` lane."""
    return {
        "gamePk": game_pk,
        "startTime": clock,
        "matchup": {"away": {"name": "Detroit Tigers"}, "home": {"name": "Cleveland Guardians"}},
        "gameLens": [{
            # `live_mc` is what `lens_sources_for_sport("mlb")` accepts, and the
            # probability field is `modelHomeWinProb` -- keying on a bare
            # probability would admit a lens the re-sim never touched.
            "source": "live_mc",
            "modelHomeWinProb": home_win_prob,
            "simsRun": 20000,
            "probStdErr": 0.004,
        }],
    }


def _index(*games, sport: str = "mlb", slate_date: str | None = SLATE):
    return build_live_gameline_index(
        {"games": list(games)},
        sources=("live_mc",),
        sport=sport,
        slate_date=slate_date,
    )


# --- the index keeps both halves ------------------------------------------


def test_both_halves_survive_the_index():
    index = _index(_lens_game(824424, "1:10 PM", 0.62), _lens_game(824387, "6:15 PM", 0.41))
    assert [row["game_pk"] for row in index.candidates[PAIR]] == [824424, 824387]


def test_an_ordinary_pair_is_one_candidate_and_the_mapping_still_answers():
    index = _index(_lens_game(824424, "1:10 PM", 0.62))
    assert len(index.candidates[PAIR]) == 1
    assert index[PAIR]["game_pk"] == 824424


def test_the_lens_clock_string_becomes_an_instant():
    # "1:10 PM" Central on 2026-09-04 is 18:10:00Z -- 824424's real StatsAPI
    # start, which is what makes this a join and not a guess.
    index = _index(_lens_game(824424, "1:10 PM", 0.62))
    got = dt.datetime.fromtimestamp(index[PAIR]["start_epoch"], dt.timezone.utc)
    assert got.isoformat() == "2026-09-04T18:10:00+00:00"


def test_without_a_slate_date_a_clock_string_yields_no_start():
    index = _index(_lens_game(824424, "1:10 PM", 0.62), slate_date=None)
    assert index[PAIR]["start_epoch"] is None


# --- the resolver ----------------------------------------------------------


@pytest.mark.parametrize("commence, expected", [
    ("2026-09-04T18:10:00Z", 824424),
    ("2026-09-04T23:15:00Z", 824387),
])
def test_each_event_resolves_to_its_own_half_by_start(commence, expected):
    index = _index(_lens_game(824424, "1:10 PM", 0.62), _lens_game(824387, "6:15 PM", 0.41))
    hit, _why = resolve_live_gameline(index, PAIR, target_start=commence, sport="mlb")
    assert hit["game_pk"] == expected


def test_lens_order_does_not_decide():
    index = _index(_lens_game(824387, "6:15 PM", 0.41), _lens_game(824424, "1:10 PM", 0.62))
    hit, _why = resolve_live_gameline(
        index, PAIR, target_start="2026-09-04T18:10:00Z", sport="mlb")
    assert hit["game_pk"] == 824424


def test_an_exact_game_pk_beats_the_clock():
    index = _index(_lens_game(824424, "1:10 PM", 0.62), _lens_game(824387, "6:15 PM", 0.41))
    hit, why = resolve_live_gameline(
        index, PAIR, target_start="2026-09-04T18:10:00Z", game_pk=824387, sport="mlb")
    assert (hit["game_pk"], why) == (824387, "game_pk")


def test_a_pair_it_cannot_separate_is_refused_not_guessed():
    # No start on the row: the old code handed over whichever game was indexed.
    index = _index(_lens_game(824424, "1:10 PM", 0.62), _lens_game(824387, "6:15 PM", 0.41))
    hit, why = resolve_live_gameline(index, PAIR, target_start=None, sport="mlb")
    assert hit is None
    assert why == REASON_GAME_AMBIGUOUS


def test_two_games_inside_the_separation_window_resolve_on_a_near_exact_start():
    """CHANGED 2026-09-25, and the old expectation was the bug.

    This used to assert a refusal, because the rule only asked whether the
    winner was 45 minutes clearer than the runner-up. Here the target matches
    824424 to the SECOND and is 30 minutes from 824387 -- knowable, and the old
    rule answered None anyway.

    That blanket refusal is what broke the board: a TRADITIONAL doubleheader
    (`doubleHeader: "Y"`) publishes its halves five minutes apart, so it could
    never clear the window and BAL @ NYY seated four tiles for two games on
    2026-09-25. See `doubleheader.NEAR_EXACT_SECONDS`.
    """
    index = _index(_lens_game(824424, "1:10 PM", 0.62), _lens_game(824387, "1:40 PM", 0.41))
    hit, why = resolve_live_gameline(
        index, PAIR, target_start="2026-09-04T18:10:00Z", sport="mlb")
    assert hit is not None and hit["game_pk"] == 824424
    assert why == "nearest_start_near_exact"


def test_a_start_inside_the_window_but_not_near_exact_is_still_refused():
    """CONTROL: the near-exact rule must not become a nearest-wins rule.

    10 minutes from one half and 20 from the other is exactly the shape the
    refusal exists for -- a row whose own time cannot be trusted to name its
    game. Without this, `NEAR_EXACT_SECONDS` could be widened to anything and
    the suite would stay green.
    """
    index = _index(_lens_game(824424, "1:10 PM", 0.62), _lens_game(824387, "1:40 PM", 0.41))
    hit, why = resolve_live_gameline(
        index, PAIR, target_start="2026-09-04T18:20:00Z", sport="mlb")
    assert hit is None and why == REASON_GAME_AMBIGUOUS


def test_a_target_equidistant_between_two_games_is_still_refused():
    """CONTROL: equal gaps name no winner, however near-exact they are."""
    index = _index(_lens_game(824424, "1:10 PM", 0.62), _lens_game(824387, "1:40 PM", 0.41))
    hit, why = resolve_live_gameline(
        index, PAIR, target_start="2026-09-04T18:25:00Z", sport="mlb")
    assert hit is None and why == REASON_GAME_AMBIGUOUS


def test_a_plain_dict_keeps_its_old_behaviour():
    # `scripts/verify_segment_visibility.py` passes a dict literal, and fixtures
    # elsewhere do the same. No `candidates` must mean no change.
    plain = {PAIR: {"home_win_prob": 0.6}}
    hit, _why = resolve_live_gameline(plain, PAIR, target_start="2026-09-04T18:10:00Z")
    assert hit == {"home_win_prob": 0.6}


def test_a_missing_pair_is_no_candidates():
    hit, why = resolve_live_gameline(LiveGamelineIndex(), PAIR, target_start=None)
    assert hit is None and why == "no_candidates"


# --- end to end through the join ------------------------------------------


def _grid_row(event_id: str, commence: str):
    return {
        "kind": "game",
        "market": "h2h",
        "segment": "full",
        "away_team": "Detroit Tigers",
        "home_team": "Cleveland Guardians",
        "event_id": event_id,
        "commence_time": commence,
        "age_seconds": 30.0,
        "game": {"state": "live"},
        "sides": [{"side": "home", "price": -120}, {"side": "away", "price": 100}],
    }


def test_the_second_event_is_not_priced_off_the_first_games_projection():
    index = _index(_lens_game(824424, "1:10 PM", 0.62), _lens_game(824387, "6:15 PM", 0.41))
    rows = [_grid_row("062e69d4", "2026-09-04T18:10:00Z"),
            _grid_row("a78d8674", "2026-09-04T23:15:00Z")]
    attach_live_gamelines(rows, index, sport="mlb")
    # Each event against ITS OWN half. On origin/main both read 824424.
    assert [row.get("live_gameline", {}).get("game_pk") for row in rows] == [824424, 824387]


def test_a_row_with_no_start_is_refused_by_name():
    index = _index(_lens_game(824424, "1:10 PM", 0.62), _lens_game(824387, "6:15 PM", 0.41))
    row = _grid_row("a78d8674", "2026-09-04T23:15:00Z")
    row.pop("commence_time")
    coverage = attach_live_gamelines([row], index, sport="mlb")
    assert coverage["withheld_by_reason"].get(REASON_GAME_AMBIGUOUS) == 1, coverage


def test_a_single_game_slate_is_unchanged_end_to_end():
    index = _index(_lens_game(824424, "1:10 PM", 0.62))
    rows = [_grid_row("062e69d4", "2026-09-04T18:10:00Z")]
    coverage = attach_live_gamelines(rows, index, sport="mlb")
    assert REASON_GAME_AMBIGUOUS not in coverage["withheld_by_reason"], coverage
    assert rows[0]["live_gameline"]["game_pk"] == 824424
