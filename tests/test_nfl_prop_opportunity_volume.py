"""A yardage prop carries the OPPORTUNITY behind its rate, so a low-role
projection is distinguishable from a real edge.

WHY THIS EXISTS, and why `sample_games` was not enough. That field shipped on
2026-10-16 and the step-2 measurement then showed it does NOT discriminate:
over 157 ceiling-rejected vs 453 accepted distinct NFL prop markets its median
is **5.0 on both sides**, because in week 6 it is a CALENDAR count. What did
separate the two populations was a low ABSOLUTE projection -- a ROLE
disagreement. Braelon Allen's problem was never 5 games; it was 3.8 projected
receiving yards against a 15.5 line.

This publishes the role directly and needs NO new computation: `receptions`,
`rushing_attempts` and `passing_attempts` are already extracted stats and
already prop markets, so the opportunity count is the same player's own
projection under a companion stat, reached with the `inputs_for` the reprice
branch already uses.

MEASURED on `nfl_prop_projections_2026_wk6.json` before shipping:
  availability   receiving_yards 114/114 players also carry receptions,
                 passing_yards 24/24 carry passing_attempts,
                 rushing_yards 32/66 carry rushing_attempts (partial -- the
                 field must be ABSENT for the rest, never faked)
  discrimination projected receptions spans 0.67..10.33 (15x, median 3.20), and
                 4 of the 6 players below 1.00 are the collapsed rows from the
                 ceiling study: jalen brooks 0.67 (the population MINIMUM),
                 colby parkinson 0.80, bo melton 0.80, jalen royals 1.00,
                 braelon allen 1.40
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.nfl.props import (  # noqa: E402
    _NFL_PROP_MARKET_TO_STAT,
    _nfl_prop_join_market_key,
)
from syndicate.features.shared.nfl_prop_projections import (  # noqa: E402
    _OPPORTUNITY_STAT,
    NflPropProjectionIndex,
    attach_nfl_prop_projections,
)

YD_LABEL = next(k for k, v in _NFL_PROP_MARKET_TO_STAT.items() if v == "receiving_yards")
VOL_LABEL = next(k for k, v in _NFL_PROP_MARKET_TO_STAT.items() if v == "receptions")

PLAYER = "Braelon Allen"


def _row(stat, projected, line, sd=4.6, n=5):
    return {
        "market": "%s::%s" % (stat, PLAYER.lower()),
        "entity": PLAYER,
        "sim_projection": 0.06,
        "projected_value": projected,
        "projected_sd": sd,
        "sample_games": n,
        "sim_source": "nfl_season_rate",
        "rate_source": "current_season_rolling",
        "player_team": "NYJ",
    }


def _attach(*, yard_line=15.5, receptions=1.40, with_companion=True,
            stat="receiving_yards", label=None, vol_stat="receptions"):
    """Index the yardage row plus (optionally) its companion volume row."""
    entries = {
        _nfl_prop_join_market_key(stat, PLAYER, yard_line): _row(stat, 3.8, yard_line),
    }
    if with_companion:
        entries[_nfl_prop_join_market_key(vol_stat, PLAYER, 1.5)] = _row(
            vol_stat, receptions, 1.5)
    index = NflPropProjectionIndex(entries=entries, season=2026, week=6,
                                   row_count=len(entries))
    row = {
        "kind": "prop",
        "market": label or YD_LABEL,
        "player_name": PLAYER,
        "line": yard_line,
        "side": "over",
        "home_team": "New England Patriots",
        "away_team": "New York Jets",
    }
    coverage = attach_nfl_prop_projections([row], index)
    return row.get("projection"), coverage


# ---------------------------------------------------------------------------
# the opportunity reaches the published projection
# ---------------------------------------------------------------------------

def test_a_yardage_row_publishes_its_opportunity_and_names_the_stat():
    projection, coverage = _attach()
    assert coverage["rows_with_projection"] == 1, coverage
    assert projection["opportunity_stat"] == "receptions"
    assert projection["projected_opportunities"] == pytest.approx(1.40)


def test_the_opportunity_comes_from_the_COMPANION_ROW_and_not_a_constant():
    """Reachability: off != on. A hard-coded value passes the test above."""
    low, _ = _attach(receptions=0.67)   # the measured population minimum
    high, _ = _attach(receptions=10.33)  # the measured population maximum
    assert low["projected_opportunities"] == pytest.approx(0.67)
    assert high["projected_opportunities"] == pytest.approx(10.33)


def test_an_absent_companion_market_publishes_NONE_not_zero():
    """rushing_yards had the companion for only 32 of 66 players, so absence is
    the normal case for a third of rows. "No opportunity projection" and
    "projected zero touches" are different claims, and the second is the one a
    consumer would act on.
    """
    projection, _ = _attach(with_companion=False)
    assert projection["opportunity_stat"] == "receptions"
    assert projection["projected_opportunities"] is None


def test_a_VOLUME_market_gets_no_opportunity_field_at_all():
    """For a volume market the projection already IS the opportunity count, so a
    self-reference would publish the same number twice under two names.
    """
    assert "receptions" not in _OPPORTUNITY_STAT
    assert "rushing_attempts" not in _OPPORTUNITY_STAT
    assert "passing_attempts" not in _OPPORTUNITY_STAT
    projection, _ = _attach(stat="receptions", label=VOL_LABEL, yard_line=1.5,
                            with_companion=False)
    assert projection is not None
    assert "opportunity_stat" not in projection
    assert "projected_opportunities" not in projection


def test_only_the_three_measured_pairings_are_mapped():
    """anytime_td has no line and no natural denominator, so it must be absent
    rather than mapped to something plausible-looking."""
    assert _OPPORTUNITY_STAT == {
        "receiving_yards": "receptions",
        "rushing_yards": "rushing_attempts",
        "passing_yards": "passing_attempts",
    }


def test_rushing_and_passing_pairings_resolve_too():
    for stat, vol in (("rushing_yards", "rushing_attempts"),
                      ("passing_yards", "passing_attempts")):
        label = next(k for k, v in _NFL_PROP_MARKET_TO_STAT.items() if v == stat)
        projection, _ = _attach(stat=stat, label=label, vol_stat=vol,
                                receptions=17.6)
        assert projection["opportunity_stat"] == vol, stat
        assert projection["projected_opportunities"] == pytest.approx(17.6), stat


# ---------------------------------------------------------------------------
# THE POINT: it separates what sample_games could not
# ---------------------------------------------------------------------------

def test_it_separates_the_measured_collapsed_rows_from_the_population():
    """The five collapsed players from the ceiling study, against the measured
    population (median 3.20, p10 1.20, min 0.67, max 10.33).

    `sample_games` put all of these at 5.0 -- the same value as the accepted
    population's median -- so it could not have flagged any of them.

    STATED PRECISELY, because a first draft of this test over-claimed and
    failed on its own numbers: **four of the five sit at or below 1.00**
    (brooks 0.67 = the population minimum, parkinson 0.80, melton 0.80, royals
    1.00), and braelon allen at 1.40 is ABOVE the p10 of 1.20 -- but all five
    are below HALF the population median. So the field separates them; it does
    not put every one of them in the bottom decile.
    """
    collapsed = {"jalen brooks": 0.67, "colby parkinson": 0.80,
                 "bo melton": 0.80, "jalen royals": 1.00, "braelon allen": 1.40}
    POP_P10, POP_MEDIAN = 1.20, 3.20
    for who, receptions in collapsed.items():
        projection, _ = _attach(receptions=receptions)
        got = projection["projected_opportunities"]
        assert got == pytest.approx(receptions), who
        assert got < POP_MEDIAN / 2.0, (
            "%s should sit below half the population median" % who)
    at_or_below_p10 = [w for w, v in collapsed.items() if v <= POP_P10]
    assert len(at_or_below_p10) == 4, at_or_below_p10
    # and a genuine starter is NOT flagged by the same threshold
    starter, _ = _attach(receptions=5.80)  # the measured p90
    assert starter["projected_opportunities"] > POP_MEDIAN
