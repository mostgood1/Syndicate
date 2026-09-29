"""Tests for the shared cross-league live-prop grading core.

These are OFFLINE: every test drives a synthetic ESPN-shaped summary rather than
the network, so they assert the computation and never the vendor's uptime. The
network equivalence (this core reproduces
`scripts/grade_wnba_live_prop_projection.py` byte-for-byte on a real event, and
NBA reconciles against a real official box) is recorded in the lane, not here.

The load-bearing cases, each of which has burned this repo before:
  * the sub-minute clock form ("55.7") -- dropping it silently loses every play
    in the last minute of every quarter, and those are disproportionately free
    throws;
  * a team rebound, which carries NO participant and must be credited to nobody;
  * a two-participant play that is NOT a scoring play (a block), which must
    never be read as an assist;
  * `stat_reconciles` on a stat the report does not carry, which must be False
    rather than falling through to the permissive branch.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import live_prop_grading as grading


# --------------------------------------------------------------------------
# LeagueSpec
# --------------------------------------------------------------------------

def test_known_leagues_carry_their_real_period_lengths():
    wnba, nba = grading.league("wnba"), grading.league("nba")
    assert (wnba.period_minutes, wnba.ot_minutes) == (10.0, 5.0)
    assert (nba.period_minutes, nba.ot_minutes) == (12.0, 5.0)
    assert wnba.espn_path == "basketball/wnba"
    assert nba.espn_path == "basketball/nba"


def test_league_lookup_is_case_insensitive_and_refuses_the_unknown():
    assert grading.league("NBA").sport == "nba"
    with pytest.raises(KeyError):
        grading.league("nhl")


def test_urls_are_built_from_the_league_path():
    nba = grading.league("nba")
    assert nba.summary_url.endswith("/basketball/nba/summary")
    assert nba.scoreboard_url.endswith("/basketball/nba/scoreboard")


# --------------------------------------------------------------------------
# elapsed_minutes
# --------------------------------------------------------------------------

def _clock(text):
    return {"displayValue": text}


@pytest.mark.parametrize(
    "sport,period,clock,expected",
    [
        ("wnba", 1, "10:00", 0.0),
        ("wnba", 1, "0:00", 10.0),
        ("wnba", 3, "5:30", 24.5),
        ("nba", 1, "12:00", 0.0),
        ("nba", 1, "0:00", 12.0),
        ("nba", 4, "0:00", 48.0),
    ],
)
def test_elapsed_minutes_follows_each_league_convention(sport, period, clock, expected):
    spec = grading.league(sport)
    assert grading.elapsed_minutes({"number": period}, _clock(clock), spec) == pytest.approx(expected)


def test_sub_minute_clock_without_a_colon_is_parsed_not_dropped():
    """ESPN renders the final minute as bare seconds. Returning None here would
    throw away every play in the last minute of every quarter."""
    spec = grading.league("wnba")
    got = grading.elapsed_minutes({"number": 4}, _clock("55.7"), spec)
    assert got is not None
    assert got == pytest.approx(40.0 - 55.7 / 60.0)


def test_overtime_is_timed_off_regulation_not_off_the_period_number():
    wnba, nba = grading.league("wnba"), grading.league("nba")
    # First OT tip: all of regulation elapsed, none of the extra period.
    assert grading.elapsed_minutes({"number": 5}, _clock("5:00"), wnba) == pytest.approx(40.0)
    assert grading.elapsed_minutes({"number": 5}, _clock("5:00"), nba) == pytest.approx(48.0)
    # Second OT tip: regulation plus one full OT.
    assert grading.elapsed_minutes({"number": 6}, _clock("5:00"), wnba) == pytest.approx(45.0)
    assert grading.elapsed_minutes({"number": 6}, _clock("5:00"), nba) == pytest.approx(53.0)


def test_unparseable_clock_or_period_returns_none():
    spec = grading.league("wnba")
    assert grading.elapsed_minutes(None, _clock("5:00"), spec) is None
    assert grading.elapsed_minutes({"number": 1}, _clock(""), spec) is None
    assert grading.elapsed_minutes({"number": 1}, _clock("abc"), spec) is None


# --------------------------------------------------------------------------
# A synthetic game, built so every credited stat is known by construction.
# --------------------------------------------------------------------------

_KEYS = [
    "minutes", "points", "rebounds", "assists",
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
]


def _athlete(aid, name, starter, minutes, points, rebounds, assists, threes_made):
    return {
        "athlete": {"id": aid, "displayName": name},
        "starter": starter,
        "stats": [str(minutes), str(points), str(rebounds), str(assists), f"{threes_made}-5"],
    }


def _summary():
    """A 4-minute WNBA fragment whose official box matches the plays exactly.

    A (home starter): a made three          -> 3 pts, 1 three
    C (away starter): a two, plus the assist on A's three -> 2 pts, 1 ast
    B (home bench):   one rebound            -> 1 reb, 0 minutes (never subbed in)
    Plus a TEAM rebound (no participant) and a BLOCK (two participants, no
    scoring play), neither of which may be credited to anyone.
    """
    return {
        "header": {"competitions": [{"competitors": [
            {"id": "10", "homeAway": "home"},
            {"id": "20", "homeAway": "away"},
        ]}]},
        "boxscore": {"players": [
            {"team": {"id": "10"}, "statistics": [{"keys": _KEYS, "athletes": [
                _athlete("A", "Player A", True, 4.0, 3, 0, 0, 1),
                _athlete("B", "Player B", False, 0.0, 0, 1, 0, 0),
            ]}]},
            {"team": {"id": "20"}, "statistics": [{"keys": _KEYS, "athletes": [
                _athlete("C", "Player C", True, 4.0, 2, 0, 1, 0),
            ]}]},
        ]},
        "plays": [
            {"period": {"number": 1}, "clock": _clock("9:00"), "scoringPlay": True,
             "scoreValue": 3, "homeScore": 3, "awayScore": 0,
             "type": {"text": "Made Three Point Jumper"},
             "participants": [{"athlete": {"id": "A"}}, {"athlete": {"id": "C"}}]},
            {"period": {"number": 1}, "clock": _clock("8:00"),
             "type": {"text": "Defensive Rebound"},
             "participants": [{"athlete": {"id": "B"}}]},
            {"period": {"number": 1}, "clock": _clock("7:00"),
             "type": {"text": "Team Rebound"}, "participants": []},
            {"period": {"number": 1}, "clock": _clock("6:30"),
             "type": {"text": "Blocked Shot"},
             "participants": [{"athlete": {"id": "A"}}, {"athlete": {"id": "C"}}]},
            {"period": {"number": 1}, "clock": _clock("6:00"), "scoringPlay": True,
             "scoreValue": 2, "homeScore": 3, "awayScore": 2,
             "type": {"text": "Made Layup"},
             "participants": [{"athlete": {"id": "C"}}]},
        ],
    }


def test_official_box_reads_every_stat_including_the_made_attempted_pair():
    box = grading.official_box(_summary())
    assert set(box) == {"A", "B", "C"}
    assert box["A"]["points"] == 3.0
    assert box["A"]["threes"] == 1.0          # "1-5" -> the MADE half
    assert box["B"]["rebounds"] == 1.0
    assert box["C"]["assists"] == 1.0
    assert box["A"]["starter"] is True and box["B"]["starter"] is False
    assert box["A"]["team_id"] == "10" and box["C"]["team_id"] == "20"


def test_replay_credits_points_threes_rebounds_and_assists_structurally():
    spec = grading.league("wnba")
    state = grading.replay(_summary(), spec)
    assert state["points"] == {"A": 3.0, "B": 0.0, "C": 2.0}
    assert state["threes"] == {"A": 1.0, "B": 0.0, "C": 0.0}
    assert state["rebounds"] == {"A": 0.0, "B": 1.0, "C": 0.0}
    # The assist is participants[1] on the SCORING play, and only that.
    assert state["assists"] == {"A": 0.0, "B": 0.0, "C": 1.0}


def test_team_rebound_and_block_are_credited_to_nobody():
    """A team rebound carries no participant; a block is two participants on a
    play that is not a scoring play. Either one leaking would inflate a stat the
    official box never credits, and the reconcile gate would then fail a game
    that is actually fine."""
    state = grading.replay(_summary(), grading.league("wnba"))
    assert sum(state["rebounds"].values()) == 1.0     # not 2 -- the team board is uncredited
    assert sum(state["assists"].values()) == 1.0      # not 2 -- the block is not an assist


def test_the_synthetic_game_reconciles_exactly_on_every_stat():
    state = grading.replay(_summary(), grading.league("wnba"))
    report = grading.reconcile(state)
    assert report["players"] == 3
    assert report["points_exact"] == 3
    assert report["rebounds_exact"] == 3
    assert report["assists_exact"] == 3
    assert report["threes_exact"] == 3
    assert report["points_off"] == []
    for stat in ("points", "rebounds", "assists", "threes"):
        assert grading.stat_reconciles(report, stat) is True


def test_a_wrong_league_spec_fails_the_gate_rather_than_skewing_quietly():
    """The period constants are self-checking: grade an NBA-length game with
    WNBA periods and MINUTES stop reconciling. Without this the gate would be
    blind to the one thing a new LeagueSpec is most likely to get wrong."""
    summary = _summary()
    # Same plays, but the box says these players were on for NBA-length periods.
    for team in summary["boxscore"]["players"]:
        for block in team["statistics"]:
            for athlete in block["athletes"]:
                if athlete["starter"]:
                    athlete["stats"][0] = "28.0"
    state = grading.replay(summary, grading.league("wnba"))
    report = grading.reconcile(state)
    assert report["minutes_within_tolerance"] < report["players"]
    assert report["minutes_off"]


# --------------------------------------------------------------------------
# The admission gate and the residual table
# --------------------------------------------------------------------------

def test_stat_reconciles_is_false_for_a_stat_the_report_does_not_carry():
    """UNKNOWN MUST NOT DEFAULT PERMISSIVE: a stat with no `<stat>_exact` key is
    one this replay never tracked, so it is NOT admitted. Reading an absent key
    as 'fine' would silently widen what gets graded."""
    report = {"players": 5, "points_exact": 5}
    assert grading.stat_reconciles(report, "points") is True
    assert grading.stat_reconciles(report, "steals") is False
    assert grading.stat_reconciles(report, "rebounds") is False


def test_stat_reconciles_requires_every_player_not_merely_most():
    report = {"players": 10, "points_exact": 9}
    assert grading.stat_reconciles(report, "points") is False


def test_residual_buckets_report_spread_and_bias_separately():
    residuals = [{"minutes_left": 7.0, "residual": r} for r in ([2.0, -2.0] * 20)]
    out = grading.residual_by_bucket(residuals, edges=(5.0, 10.0), min_n=30)
    assert len(out) == 1
    entry = out[0]
    assert entry["n"] == 40
    assert entry["mean_residual"] == pytest.approx(0.0)      # unbiased
    assert entry["stdev_residual"] == pytest.approx(2.0)     # but a real spread
    assert entry["mean_abs_residual"] == pytest.approx(2.0)


def test_a_thin_bucket_is_reported_with_its_n_rather_than_dropped():
    """Thin coverage must stay VISIBLE. A dropped bucket is indistinguishable
    from a bucket that had no data, which is how a residual measured on almost
    nothing gets read as a measurement."""
    residuals = [{"minutes_left": 2.0, "residual": 1.0} for _ in range(4)]
    out = grading.residual_by_bucket(residuals, edges=(0.0, 5.0), min_n=30)
    assert out[0]["n"] == 4
    assert "under-powered" in out[0]["status"]
    assert "stdev_residual" not in out[0]
