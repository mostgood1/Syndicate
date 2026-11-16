"""The NFL live re-sim tick: default OFF, and the adapter that makes it work.

Three properties, each of which was a real defect at some point today:

1. ABSENT READS AS OFF, asserted rather than assumed. CLAUDE.md's rule exists
   because `_evaluation_settlement_auto_refresh_enabled` treats absent as False
   while `_mlb_refresh_tick_owner_here` defaults True -- the same edit is a
   no-op in one and a behaviour change in the other.
2. THE ADAPTER IS LOAD-BEARING. `nfl_game_state_index` and `live_state_from_row`
   disagree on field names AND value shapes; without translation every game
   refuses `game_not_in_progress` on a display string.
3. THE RATINGS COME FROM THE ARTIFACT the generator wrote, so a live re-sim
   cannot drift from the pregame projection it updates.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from scripts._nfl_live_resim_tick import (
    _clock_seconds,
    build_live_index,
    normalise_live_row,
    situation_tally,
)
from syndicate.features.nfl import live_resim as lr
from syndicate.features.nfl.smartsim2_projection import (
    ratings_artifact_path,
    read_ratings_artifact,
    write_ratings_artifact,
)

# Exactly what `nfl_game_state_index` emits -- copied from its own construction
# site, not invented, so this test breaks if that shape changes.
ESPN_SHAPE = {
    "in_progress": True,
    "final": False,
    "period": 4,
    "clock": "6:12",
    "status": "4th Quarter",
    "away_pts": 3,
    "home_pts": 31,
    "situation": {},
}


def test_the_flag_absent_reads_as_OFF():
    assert lr.nfl_live_resim_enabled(env={}) is False
    assert lr.nfl_live_resim_enabled(env={"SYNDICATE_NFL_LIVE_RESIM": ""}) is False
    assert lr.nfl_live_resim_enabled(env={"SYNDICATE_NFL_LIVE_RESIM": "0"}) is False
    assert lr.nfl_live_resim_enabled(env={"SYNDICATE_NFL_LIVE_RESIM": "1"}) is True


def test_the_raw_ESPN_shape_is_REFUSED_without_the_adapter():
    """The defect the adapter exists to prevent, pinned as a fact.

    If this ever passes, the producer has started accepting the raw shape and
    the adapter may be removable -- but that is a decision, not a silent drift.
    """
    state = lr.live_state_from_row(ESPN_SHAPE, away_team="Dallas Cowboys",
                                   home_team="Philadelphia Eagles")
    assert isinstance(state, lr.NflResimRefusal)
    assert state.reason == "game_not_in_progress", state.reason


def test_the_adapter_produces_a_usable_state():
    row = normalise_live_row(ESPN_SHAPE)
    assert row["state"] == "in"
    assert row["away_score"] == 3 and row["home_score"] == 31
    assert row["clock_seconds"] == 372          # "6:12"
    assert row["period"] == 4
    state = lr.live_state_from_row(row, away_team="Dallas Cowboys",
                                   home_team="Philadelphia Eagles")
    assert not isinstance(state, lr.NflResimRefusal), getattr(state, "reason", "")


def test_an_empty_situation_keeps_the_old_marginalised_state():
    """No situation -> exactly the pre-#813 state, named."""
    row = normalise_live_row(ESPN_SHAPE)
    assert (row["possession_owner"], row["down"], row["distance"], row["field_position"]) == (None, 1, 10, 25)
    assert row["situation_basis"] == "no_situation"


# todo #813. PHI (id 21) hosts DAL (id 6). field_position is smartsim2's: yards
# from the POSSESSING team's own goal line.
def _live(situation):
    return {**ESPN_SHAPE, "away_abbr": "DAL", "home_abbr": "PHI", "away_team_id": "6",
            "home_team_id": "21", "situation": situation}


def test_home_on_its_own_side_reads_the_spot_from_the_text():
    row = normalise_live_row(_live({"possession": "21", "down": 2, "distance": 7,
                                    "possessionText": "PHI 35", "yardLine": 35}))
    assert (row["possession_owner"], row["down"], row["distance"], row["field_position"]) == ("home", 2, 7, 35)
    assert row["situation_basis"] == "text"
    # Diagnostic only: NCAAF's measured frame (from the HOME goal line) agrees here.
    assert row["yardline_frame"] == "home_frame"


def test_away_in_the_red_zone_is_at_95_not_5():
    """The inversion that matters: DAL on PHI's 5 is 95 yards from its OWN goal.
    Getting it backwards would put the team at its own 5 -- a whole field."""
    row = normalise_live_row(_live({"possession": "6", "down": 1, "distance": 5,
                                    "possessionText": "PHI 5"}))
    assert (row["possession_owner"], row["field_position"]) == ("away", 95)


def test_midfield_and_the_downDistanceText_fallback():
    row = normalise_live_row(_live({"possession": "6", "down": 3, "distance": 2,
                                    "downDistanceText": "3rd & 2 at 50"}))
    assert (row["possession_owner"], row["field_position"], row["down"]) == ("away", 50, 3)
    row = normalise_live_row(_live({"possession": "21", "down": 3, "distance": 4,
                                    "downDistanceText": "3rd & 4 at DAL 22"}))
    assert (row["possession_owner"], row["field_position"]) == ("home", 78)


def test_between_plays_falls_back_instead_of_giving_the_kicker_the_ball():
    """ESPN reads down/distance -1 on kickoffs and tries, with the KICKING team
    in possession; carrying that would hand the ball to the wrong side."""
    row = normalise_live_row(_live({"possession": "21", "down": -1, "distance": -1,
                                    "possessionText": "PHI 35"}))
    assert row["possession_owner"] is None and row["field_position"] == 25
    assert row["situation_basis"] == "between_plays"


def test_every_ambiguity_falls_back_by_name():
    cases = {
        "no_possession": {"down": 1, "distance": 10, "possessionText": "PHI 35"},
        "unknown_possessor_id": {"possession": "99", "down": 1, "distance": 10, "possessionText": "PHI 35"},
        "no_spot_text": {"possession": "21", "down": 1, "distance": 10, "yardLine": 35},
        "spot_side_unmatched": {"possession": "21", "down": 1, "distance": 10, "possessionText": "NYG 35"},
    }
    for basis, situation in cases.items():
        row = normalise_live_row(_live(situation))
        assert row["situation_basis"] == basis, (basis, row["situation_basis"])
        assert (row["possession_owner"], row["down"], row["distance"], row["field_position"]) == (None, 1, 10, 25)
    # yardLine alone is never used for the spot: its NFL frame is unverified.
    assert normalise_live_row(_live(cases["no_spot_text"]))["field_position"] == 25


def test_a_final_or_pregame_row_never_carries_a_drive():
    row = normalise_live_row({**_live({"possession": "21", "down": 1, "distance": 10,
                                       "possessionText": "PHI 35"}), "in_progress": False, "final": True})
    assert row["possession_owner"] is None and row["situation_basis"] == "not_live"


def test_the_drive_REACHES_the_engine_and_changes_the_answer():
    """Reachability before correctness (model_engine_standard.md): the mapped
    state must arrive in `resim_live_game`, and ON must differ from OFF."""
    env = {"SYNDICATE_NFL_LIVE_RESIM": "1"}
    ratings = dict(home_offense=0.30, home_defense=0.10, away_offense=-0.20, away_defense=-0.10)
    base = {**ESPN_SHAPE, "period": 4, "clock": "9:00", "away_pts": 3, "home_pts": 31}
    on_row = normalise_live_row({**_live({"possession": "21", "down": 1, "distance": 5,
                                          "possessionText": "DAL 5"}), **{k: base[k] for k in
                                                                          ("period", "clock", "away_pts", "home_pts")}})
    off_row = normalise_live_row({**base, "situation": {}})
    on = lr.live_state_from_row(on_row, away_team="Dallas Cowboys", home_team="Philadelphia Eagles")
    off = lr.live_state_from_row(off_row, away_team="Dallas Cowboys", home_team="Philadelphia Eagles")
    assert (on.possession_owner, on.field_position, on.down, on.distance) == ("home", 95, 1, 5)
    assert off.possession_owner is None
    r_on = lr.resim_live_game(on, sims=40, env=env, **ratings)
    r_off = lr.resim_live_game(off, sims=40, env=env, **ratings)
    assert isinstance(r_on, dict) and isinstance(r_off, dict), (r_on, r_off)
    assert r_on["possession_marginalised"] is False and r_off["possession_marginalised"] is True
    assert r_on["total_mean"] != r_off["total_mean"]
    # 1st and goal at the 5 is worth more than a coin-flip drive from the 25.
    assert r_on["total_mean"] > r_off["total_mean"]


def test_timeouts_left_are_carried_only_as_ints_0_to_3():
    """For lane nfl-live-timeouts: the live resume's timeouts left, never a default."""
    row = normalise_live_row(_live({"possession": "21", "down": 1, "distance": 10, "possessionText": "PHI 35",
                                    "homeTimeouts": 2, "awayTimeouts": 0}))
    assert (row["home_timeouts"], row["away_timeouts"]) == (2, 0)
    for bad in (None, -1, 4, "x", True, 1.5):
        row = normalise_live_row(_live({"homeTimeouts": bad, "awayTimeouts": bad}))
        assert (row["home_timeouts"], row["away_timeouts"]) == (None, None), bad
    assert normalise_live_row(_live({"homeTimeouts": "3"}))["home_timeouts"] == 3
    # No situation, or a game not live: unknown, not 3.
    assert normalise_live_row(ESPN_SHAPE)["home_timeouts"] is None
    final = normalise_live_row({**_live({"homeTimeouts": 2}), "in_progress": False, "final": True})
    assert final["home_timeouts"] is None


def test_the_tally_counts_carried_and_names_the_rest():
    index = {
        "a": normalise_live_row(_live({"possession": "21", "down": 2, "distance": 7,
                                       "possessionText": "PHI 35", "yardLine": 35})),
        "b": normalise_live_row(_live({"possession": "21", "down": -1, "distance": -1})),
        "c": normalise_live_row({**ESPN_SHAPE, "in_progress": False, "final": True}),
    }
    line = situation_tally(index)
    assert line.startswith("live=2 carried=1 marginalised=1 "), line
    assert "'between_plays': 1" in line and "'text': 1" in line and "'home_frame': 1" in line


def test_an_unparseable_clock_is_None_not_zero():
    """A zero clock is a REAL state -- end of quarter. Guessing it from an
    unparseable string hands the engine a confident, wrong situation; None
    makes the producer refuse by name instead."""
    assert _clock_seconds({"clock": ""}) is None
    assert _clock_seconds({"clock": "garbage"}) is None
    assert _clock_seconds({"clock": "0:00"}) == 0
    assert _clock_seconds({"clock_seconds": 90}) == 90


def test_final_and_pregame_map_to_refusable_states():
    assert normalise_live_row({**ESPN_SHAPE, "in_progress": False, "final": True})["state"] == "final"
    assert normalise_live_row({"in_progress": False, "final": False})["state"] == "pre"


def test_build_live_index_keys_on_the_games_own_live_key():
    games = [{"away_team": "Dallas Cowboys", "home_team": "Philadelphia Eagles",
              "live_key": "Dallas Cowboys@Philadelphia Eagles"}]
    index = build_live_index({"Dallas Cowboys@Philadelphia Eagles": ESPN_SHAPE}, games)
    assert set(index) == {"Dallas Cowboys@Philadelphia Eagles"}
    # A game the state index does not cover is simply absent -- the producer
    # then refuses it `no_live_state` by name rather than the index being empty.
    assert build_live_index({}, games) == {}


def test_ratings_artifact_round_trips_and_keeps_per_team_source():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_ratings_artifact(
            {"Dallas Cowboys": (1.5, -0.5, "current_season_rolling"),
             "Chicago Bears": (0.0, 0.0, "neutral_no_data")},
            season=2026, week=1, data_root=root,
        )
        assert read_ratings_artifact(season=2026, week=1, data_root=root) == {
            "Dallas Cowboys": (1.5, -0.5), "Chicago Bears": (0.0, 0.0)}
        payload = json.loads(ratings_artifact_path(season=2026, week=1, data_root=root)
                             .read_text(encoding="utf-8"))
        # PER TEAM, not per file: the generator falls back per team, so one
        # file-level tag would report the first team's provenance for all.
        assert payload["teams"]["Chicago Bears"]["rating_source"] == "neutral_no_data"
        assert payload["teams"]["Dallas Cowboys"]["rating_source"] == "current_season_rolling"


def test_a_missing_ratings_artifact_yields_empty_not_an_exception():
    """So the tick refuses each game by name instead of the tick vanishing.
    A tick that disappears is indistinguishable from one that had no games."""
    with TemporaryDirectory() as tmp:
        assert read_ratings_artifact(season=2026, week=99, data_root=Path(tmp)) == {}


def test_the_ratings_artifact_is_allowlisted():
    """Written but not allowlisted is invisible to every other service -- the
    exact shape that left `espn_match_stats.json` off the worker for three
    weeks while it sat git-tracked in the checkout."""
    import fnmatch

    from syndicate.features.shared.artifact_publisher import HOT_ARTIFACT_PATTERNS

    path = "nfl_source/smartsim2_ratings_2026_wk1.json"
    assert any(fnmatch.fnmatch(path, pattern) for pattern in HOT_ARTIFACT_PATTERNS), (
        "the live re-sim reads this on a DIFFERENT service from the one that "
        "generates it; unallowlisted it can never arrive"
    )


def test_the_snapshot_refuses_every_game_when_the_flag_is_off():
    games = [{"away_team": "Dallas Cowboys", "home_team": "Philadelphia Eagles",
              "live_key": "dal@phi"}]
    snapshot = lr.build_live_lens_snapshot(
        "2026-09-07", games=games,
        live_index={"dal@phi": normalise_live_row(ESPN_SHAPE)},
        ratings={"Dallas Cowboys": (-6.0, 4.0), "Philadelphia Eagles": (8.0, -5.0)},
        env={},
    )
    coverage = snapshot.get("coverage") or {}
    assert coverage.get("live_resimmed") == 0
    assert "nfl_live_resim_disabled" in (coverage.get("refusals_by_reason") or {})


def test_the_adapter_carries_EVENT_ID_for_the_prop_capture():
    """It did not, and that cost a live slate on 2026-09-27.

    `live_state_from_row` has no use for `event_id`, so the adapter dropped it.
    But `nfl/live_resim._maybe_capture_prop_snapshot` reads it to fetch the
    per-quarter player box, and with the field absent the capture returned
    SILENTLY on every game of every tick -- zero CAPTURED lines and zero FAILED
    lines for 37 minutes while three games sat inside the capture window.

    An adapter that drops a field one of its consumers needs is
    indistinguishable from a feature nobody switched on, which is why this is a
    test and not a comment.
    """
    from scripts._nfl_live_resim_tick import normalise_live_row

    row = normalise_live_row({
        "event_id": "401772510", "in_progress": True, "final": False,
        "period": 2, "clock": "0:27", "home_pts": 17, "away_pts": 10,
    })
    assert row["event_id"] == "401772510"
    # and the fields the producer itself needs are untouched
    assert row["state"] == "in"
    assert row["period"] == 2
    assert row["home_score"] == 17


def test_the_live_index_joins_RAMS_and_COMMANDERS_across_the_abbr_mismatch():
    """It did not, and it cost a whole slate on 2026-09-27.

    `nfl_game_state_index` keys on ESPN abbreviations (`LAR@DEN`); `live_key`
    comes from the projections, which are nflverse-style (`LA@DEN`). 30 of 32
    teams agree, so the join looked fine -- it fails only for the Rams and the
    Commanders. The prop capture reported `no_row=2` with one live game on the
    board, `LA_DEN`, and the single capturable game of the night was the one
    team that does not join.
    """
    from scripts._nfl_live_resim_tick import build_live_index

    espn_state = {
        "LAR@DEN": {"event_id": "1", "in_progress": True, "final": False,
                    "period": 1, "clock": "7:30", "home_pts": 3, "away_pts": 0},
        "WSH@DAL": {"event_id": "2", "in_progress": True, "final": False,
                    "period": 2, "clock": "0:12", "home_pts": 10, "away_pts": 7},
        "KC@BUF": {"event_id": "3", "in_progress": True, "final": False,
                   "period": 3, "clock": "1:00", "home_pts": 21, "away_pts": 14},
    }
    games = [{"live_key": "LA@DEN"}, {"live_key": "WAS@DAL"}, {"live_key": "KC@BUF"}]
    index = build_live_index(espn_state, games)

    # Keyed by the caller's OWN live_key, so the producer still looks it up the
    # way it always did -- only the lookup into ESPN's index is mapped.
    assert set(index) == {"LA@DEN", "WAS@DAL", "KC@BUF"}
    assert index["LA@DEN"]["event_id"] == "1"
    assert index["LA@DEN"]["period"] == 1
    assert index["WAS@DAL"]["event_id"] == "2"
    assert index["KC@BUF"]["event_id"] == "3", "an unmapped team must still join directly"
