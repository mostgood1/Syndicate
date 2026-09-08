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


def test_possession_is_left_ABSENT_rather_than_guessed():
    """ESPN's `situation` payload is unverified for NFL.

    `resim_live_game` marginalises over both starting owners when possession is
    absent, costing roughly a possession of field position. Guessing it from an
    unchecked payload could invert the starting side, which is worth more and
    would be invisible.
    """
    assert normalise_live_row(ESPN_SHAPE)["possession_owner"] is None


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
