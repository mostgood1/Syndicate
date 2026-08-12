"""`#368` -- first/last goal scorer, the largest unprojected block on the board.

Measured live 2026-08-11: `player_first_goal_scorer` (823 rows) and
`player_last_goal_scorer` (454) at **0.0%**, while `player_goal_scorer_anytime`
ran at 16.2% off the same artifact. 1,277 rows with nothing.

`soccer_projections` excluded them deliberately, and its reasoning was right as
far as it went: "anytime is not first, and reusing the anytime probability would
overstate every one of those rows." A Poisson race is not reuse -- it converts
P(anytime) into a rate and lets the players compete for the first arrival.

THE PART THAT DECIDES WHETHER THE NUMBERS ARE HONEST is what Lambda is anchored
on. Reconciled across 55 real matches, sum(lambda_p) against the sim's own
`total_distribution.mean`: mean diff -0.176, max |diff| 1.573. Some fixtures
agree to four decimals; others are short by 1.5 goals because their player list
is incomplete. Normalising by the player sum would force the shares to total 1
and inflate every listed player exactly where the data is weakest. Anchoring on
the match mean leaves the missing players' share unallocated.

Verified on 55 matches after the fix: max attributable_share exactly 1.0, worst
sum-minus-P(any goal) 2e-6 (per-player rounding), zero violations past 1e-4.
"""

from __future__ import annotations

import math

import pytest

from syndicate.features.shared.soccer_scorer_markets import player_goal_rate, scorer_race


def _p(name: str, prob: float) -> dict:
    return {"player_name": name, "anytime_scorer_probability": prob}


def test_the_rate_inverts_the_anytime_probability():
    # P(anytime) = 1 - exp(-lambda), so lambda = -ln(1 - P).
    assert player_goal_rate(0.0657) == pytest.approx(math.log(1 / (1 - 0.0657)))
    assert player_goal_rate(0) is None
    assert player_goal_rate(None) is None
    # 1.0 implies an infinite rate and would swamp every other player.
    assert player_goal_rate(1.0) is None


def test_first_scorer_is_always_below_anytime():
    # A player cannot be likelier to score FIRST than to score at all. This is
    # the exact overstatement the original exclusion was protecting against.
    race = scorer_race([_p("A", 0.30), _p("B", 0.25), _p("C", 0.10)], match_expected_goals=None)
    assert race["by_player"]["A"] < 0.30
    assert race["by_player"]["B"] < 0.25


def test_shares_never_exceed_the_chance_of_any_goal():
    rows = [_p(f"p{n}", 0.08) for n in range(20)]
    race = scorer_race(rows, match_expected_goals=None)
    assert sum(race["by_player"].values()) <= race["any_goal_probability"] + 1e-6


def test_an_incomplete_player_list_leaves_probability_unallocated():
    # THE case this is built for. Two players implying ~0.4 goals, in a match the
    # sim says will have 2.9 -- the other 2.5 belongs to players who are missing,
    # and must NOT be redistributed onto these two.
    rows = [_p("A", 0.10), _p("B", 0.10)]
    anchored = scorer_race(rows, match_expected_goals=2.89)
    naive = scorer_race(rows, match_expected_goals=None)
    assert anchored["attributable_share"] < 0.25
    # Measured: anchored 0.0344 vs naive 0.0950 -- a 2.76x reduction. The
    # threshold states the direction and magnitude without pinning an exact
    # ratio that would break on any reasonable model change.
    assert anchored["by_player"]["A"] < naive["by_player"]["A"] / 2, (
        "anchoring on the player sum inflates the listed players -- the whole defect"
    )
    assert sum(anchored["by_player"].values()) < anchored["any_goal_probability"] / 2


def test_a_complete_list_allocates_nearly_everything():
    rows = [_p(f"p{n}", 0.09) for n in range(30)]
    listed = sum(player_goal_rate(0.09) for _ in range(30))
    race = scorer_race(rows, match_expected_goals=listed)
    assert race["attributable_share"] > 0.99
    assert race["usable"] is True


def test_a_stale_match_mean_below_the_listed_players_is_ignored():
    # Lambda can never be less than what the listed players already imply, or
    # the shares would sum past 1.
    rows = [_p("A", 0.5), _p("B", 0.5)]
    race = scorer_race(rows, match_expected_goals=0.1)
    assert race["attributable_share"] <= 1.0
    assert sum(race["by_player"].values()) <= race["any_goal_probability"] + 1e-6


def test_low_coverage_is_flagged_rather_than_hidden():
    rows = [_p("A", 0.05)]
    race = scorer_race(rows, match_expected_goals=3.0)
    assert race["usable"] is False, "a match where listed players cover ~2% must be flagged"


def test_empty_input_is_a_blank_not_a_crash():
    race = scorer_race([], match_expected_goals=2.5)
    assert race["by_player"] == {}
    assert race["usable"] is False
    assert scorer_race([{"player_name": "", "anytime_scorer_probability": None}], match_expected_goals=None)["by_player"] == {}
