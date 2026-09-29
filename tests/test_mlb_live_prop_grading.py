"""Tests for the MLB feed_live replay adapter.

OFFLINE: every test drives a synthetic feed, so they assert the computation and
never the availability of a capture. The corpus-scale reconcile rate is recorded
in the lane, not here.

The cases that carry weight, each chosen because getting it wrong produces a
replay that looks clean:
  * a run is credited to the RUNNER WHO SCORED, on whatever play scored him --
    including a non-plate-appearance play like a wild pitch. Crediting the batter
    instead still reconciles on most games, because the batter usually IS the
    runner on a home run;
  * `count.outs` is POST-play and RESETS every half-inning, so cumulative outs
    must be accumulated per half rather than read off any single field;
  * an UNKNOWN eventType must refuse the batting stats, since an unrecognised
    event credits nobody and a silent zero is indistinguishable from agreement;
  * a player who never batted must not be counted, or every rate here inflates
    with free agreement from players who had nothing to agree about.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import mlb_live_prop_grading as mlb


def _batting(hits=0, tb=0, hr=0, rbi=0, runs=0, so=0):
    return {"hits": hits, "totalBases": tb, "homeRuns": hr,
            "rbi": rbi, "runs": runs, "strikeOuts": so}


def _player(pid, name, batting=None, pitching=None, order="100"):
    entry = {"person": {"id": pid, "fullName": name}, "battingOrder": order, "stats": {}}
    if batting is not None:
        entry["stats"]["batting"] = batting
    if pitching is not None:
        entry["stats"]["pitching"] = pitching
    return entry


def _play(batter, pitcher, event, outs, *, rbi=0, scorers=(), inning=1, half="top", idx=0):
    return {
        "about": {"inning": inning, "halfInning": half, "atBatIndex": idx},
        "result": {"eventType": event, "rbi": rbi},
        "matchup": {"batter": {"id": batter}, "pitcher": {"id": pitcher}},
        "count": {"outs": outs},
        "runners": [
            {"movement": {"end": "score"}, "details": {"runner": {"id": r}}}
            for r in scorers
        ],
    }


def _feed():
    """A half-inning whose official box matches the plays exactly.

    1 homers (scoring himself), 2 strikes out, 3 singles and then scores on a
    WILD PITCH -- a play that is not a plate appearance at all.
    """
    return {
        "liveData": {
            "plays": {"allPlays": [
                _play(1, 9, "home_run", 0, rbi=1, scorers=(1,), idx=0),
                _play(2, 9, "strikeout", 1, idx=1),
                _play(3, 9, "single", 1, idx=2),
                _play(3, 9, "wild_pitch", 1, scorers=(3,), idx=3),
                _play(4, 9, "field_out", 2, idx=4),
            ]},
            "boxscore": {"teams": {
                "away": {"players": {
                    "ID1": _player(1, "Batter One", _batting(hits=1, tb=4, hr=1, rbi=1, runs=1)),
                    "ID2": _player(2, "Batter Two", _batting(so=1)),
                    "ID3": _player(3, "Batter Three", _batting(hits=1, tb=1, runs=1)),
                    "ID4": _player(4, "Batter Four", _batting()),
                    "ID5": _player(5, "Never Played", None),
                }},
                "home": {"players": {
                    "ID9": _player(9, "Pitcher Nine", None, {"strikeOuts": 1, "outs": 2}),
                }},
            }},
        }
    }


# --------------------------------------------------------------------------
# Box parsing
# --------------------------------------------------------------------------

def test_official_box_separates_batters_from_pitchers_and_flags_who_appeared():
    box = mlb.official_box(_feed())
    assert box["1"]["batted"] is True
    assert box["1"]["pitched"] is False
    assert box["9"]["pitched"] is True
    assert box["9"]["batted"] is False
    # A player with no batting block at all did not appear.
    assert box["5"]["batted"] is False


def test_official_box_reads_the_graded_stats():
    box = mlb.official_box(_feed())
    assert box["1"]["batting"]["totalBases"] == 4
    assert box["3"]["batting"]["runs"] == 1
    assert box["9"]["pitching"] == {"strikeOuts": 1, "outs": 2}


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------

def test_replay_credits_the_batting_line_off_event_type():
    state = mlb.replay(_feed())
    assert state["batting"]["1"]["hits"] == 1
    assert state["batting"]["1"]["totalBases"] == 4
    assert state["batting"]["1"]["homeRuns"] == 1
    assert state["batting"]["1"]["rbi"] == 1
    assert state["batting"]["2"]["strikeOuts"] == 1
    assert state["batting"]["3"]["hits"] == 1
    assert state["batting"]["3"]["totalBases"] == 1


def test_a_run_is_credited_to_the_runner_including_on_a_non_plate_appearance():
    """Batter 3 scores on a WILD PITCH. The run belongs to him as the runner,
    and the wild pitch credits him no hit and no at-bat."""
    state = mlb.replay(_feed())
    assert state["batting"]["3"]["runs"] == 1
    assert state["batting"]["1"]["runs"] == 1     # scored himself on the homer
    assert state["batting"]["3"]["hits"] == 1     # the single only, not the wild pitch
    assert sum(line["runs"] for line in state["batting"].values()) == 2


def test_pitcher_is_charged_strikeouts_and_every_out_recorded():
    state = mlb.replay(_feed())
    assert state["pitching"]["9"]["strikeOuts"] == 1
    assert state["pitching"]["9"]["outs"] == 2


def test_outs_accumulate_across_half_innings_despite_the_per_half_reset():
    """`count.outs` restarts at 1 in the next half-inning. Reading it as a
    running total would lose three outs per half."""
    feed = {
        "liveData": {
            "plays": {"allPlays": [
                _play(1, 9, "field_out", 1, inning=1, half="top", idx=0),
                _play(2, 9, "field_out", 2, inning=1, half="top", idx=1),
                _play(3, 9, "field_out", 3, inning=1, half="top", idx=2),
                # New half: the field restarts at 1, but the game is at 4 outs.
                _play(7, 8, "field_out", 1, inning=1, half="bottom", idx=3),
            ]},
            "boxscore": {"teams": {"away": {"players": {}}, "home": {"players": {}}}},
        }
    }
    state = mlb.replay(feed)
    assert state["total_outs"] == 4.0


def test_the_synthetic_game_reconciles_exactly_on_every_graded_stat():
    state = mlb.replay(_feed())
    report = mlb.reconcile(state)
    assert report["players"] == 4          # ID5 never batted and is not counted
    assert report["pitchers"] == 1
    for stat in mlb.BATTING_STATS:
        assert report[f"{stat}_off"] == [], f"{stat}: {report[f'{stat}_off']}"
        assert mlb.stat_reconciles(report, stat) is True
    for stat in mlb.PITCHING_STATS:
        assert mlb.stat_reconciles(report, f"pitching_{stat}") is True


def test_a_player_who_never_batted_is_excluded_from_the_denominator():
    """Otherwise every rate inflates with agreement from players who had
    nothing to agree about."""
    report = mlb.reconcile(mlb.replay(_feed()))
    assert report["players"] == 4          # not 5


# --------------------------------------------------------------------------
# The refusals
# --------------------------------------------------------------------------

def test_an_unknown_event_type_is_recorded_and_refuses_the_batting_stats():
    feed = _feed()
    feed["liveData"]["plays"]["allPlays"][2]["result"]["eventType"] = "quantum_triple"
    state = mlb.replay(feed)
    assert state["unknown_events"] == {"quantum_triple": 1}
    report = mlb.reconcile(state)
    for stat in mlb.BATTING_STATS:
        assert mlb.stat_reconciles(report, stat) is False


def test_an_unknown_batting_event_does_not_refuse_the_pitching_stats():
    """The refusal is scoped to what the unknown event could have affected.
    Widening it further would withhold pitcher props for an unrelated reason."""
    feed = _feed()
    feed["liveData"]["plays"]["allPlays"][2]["result"]["eventType"] = "quantum_triple"
    report = mlb.reconcile(mlb.replay(feed))
    assert mlb.stat_reconciles(report, "pitching_outs") is True
    assert mlb.stat_reconciles(report, "pitching_strikeOuts") is True


def test_a_recognised_non_plate_appearance_event_is_not_reported_unknown():
    state = mlb.replay(_feed())
    assert state["unknown_events"] == {}     # the wild pitch is known, not unknown


def test_stat_reconciles_is_false_for_a_stat_the_report_does_not_carry():
    """UNKNOWN MUST NOT DEFAULT PERMISSIVE."""
    report = {"players": 4, "pitchers": 1, "hits_exact": 4, "unknown_events": {}}
    assert mlb.stat_reconciles(report, "hits") is True
    assert mlb.stat_reconciles(report, "stolenBases") is False


def test_stat_reconciles_requires_every_player_not_merely_most():
    report = {"players": 9, "pitchers": 2, "hits_exact": 8, "unknown_events": {}}
    assert mlb.stat_reconciles(report, "hits") is False


# --------------------------------------------------------------------------
# Samples
# --------------------------------------------------------------------------

def test_a_sample_is_emitted_per_plate_appearance_and_carries_outs_recorded():
    state = mlb.replay(_feed())
    # Four plate appearances; the wild pitch is not one.
    assert len(state["samples"]) == 4
    assert [s["outs_recorded"] for s in state["samples"]] == [0.0, 1.0, 1.0, 2.0]


def test_samples_snapshot_counts_as_of_that_moment_not_the_final_line():
    state = mlb.replay(_feed())
    first = state["samples"][0]
    assert first["batting"]["1"]["hits"] == 1
    # Batter 3's single has not happened yet at the first sample.
    assert first["batting"]["3"]["hits"] == 0
    assert state["samples"][-1]["batting"]["3"]["hits"] == 1
