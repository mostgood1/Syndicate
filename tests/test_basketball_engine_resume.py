"""Resume API of the native basketball engine (lane basketball-native-engine, plan P1).

1. A resume at the opening tip is SEED-IDENTICAL to the pregame run. That is
   the NHL precedent (syndicate/features/nhl/live_resim.py docstring :34-49),
   and it is what lets a live re-sim tell its own drift from the game's.
2. A resumed state moves the answer the RIGHT WAY and MONOTONICALLY. The
   draws are common random numbers (the same seeds in every arm), so a
   non-monotone step means a defect, not noise.
3. The state's consumed fields reach the loop (off != on), and an impossible
   state is refused by name.
"""

from __future__ import annotations

from dataclasses import fields, replace

import numpy as np
import pytest

from syndicate.features.basketball_engine import NBA, WNBA, EventSimConfig, GameState, simulate_pbp_game_boxscore
from syndicate.features.basketball_engine.league import NCAAB, LeagueParams
from tests.basketball_engine_fixtures import synthetic_game_kwargs


def _kwargs(league: str, seed: int = 7):
    kw = synthetic_game_kwargs(np.random.default_rng(seed), league=league, entrypoint="simulate_pbp_game_boxscore")
    kw.pop("rng", None)
    return kw


def _run(kw, lp, seed, state=None, sampler=None):
    rng = np.random.default_rng(seed)
    out = simulate_pbp_game_boxscore(rng=rng, **kw, league=lp, sample_lineup=sampler, state=state)
    return out, rng.bit_generator.state


def _final(out):
    h_box, a_box, hq, aq = out
    return sum(hq) + sum(h_box.get("ot_pts") or []), sum(aq) + sum(a_box.get("ot_pts") or [])


def _win_prob(kw, lp, state, seeds):
    wins = 0
    for s in seeds:
        h, a = _final(_run(kw, lp, s, state)[0])
        wins += int(h > a)
    return wins / len(seeds)


# ---------------------------------------------------------------------------------------------------------------
# 1. Opening tip == pregame, seed for seed
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("lp,league", [(NBA, "nba"), (WNBA, "wnba")])
def test_opening_tip_resume_is_seed_identical_to_pregame(lp, league):
    kw = _kwargs(league)
    tips = [
        GameState(),
        GameState(period=1, seconds_remaining=lp.regulation_period_seconds),
        GameState(period=1, home_period_pts=(0,), away_period_pts=(0,), home_team_fouls=0, home_player_fouls={"H Player 00": 2}),
    ]
    for seed in range(12):
        pregame, pre_state = _run(kw, lp, seed, state=None)
        for st in tips:
            assert st.is_opening_tip(lp)
            resumed, res_state = _run(kw, lp, seed, state=st)
            assert resumed == pregame, f"seed {seed}: tip resume {st} differs from pregame"
            assert res_state == pre_state, f"seed {seed}: tip resume drew a different number of variates"


# ---------------------------------------------------------------------------------------------------------------
# 2. Right way, monotone
# ---------------------------------------------------------------------------------------------------------------


def test_ten_up_with_two_minutes_left_is_nearly_won():
    kw = _kwargs("nba", seed=11)
    st = GameState(period=4, seconds_remaining=120, home_period_pts=(25, 26, 24, 25), away_period_pts=(24, 22, 23, 21))
    assert st.home_score - st.away_score == 10
    p = _win_prob(kw, NBA, st, range(200))
    assert p >= 0.97, p


@pytest.mark.parametrize("lp,league,last_q", [(NBA, "nba", 25), (WNBA, "wnba", 20)])
def test_win_prob_is_monotone_in_the_margin(lp, league, last_q):
    # Common random numbers keep the arms close but cannot keep them identical, because the margin itself picks
    # branches (rotation windows, late-clock fouling, garbage time) that consume draws differently. So: STRICT
    # monotonicity on a 4-point grid, where a real step dwarfs the noise, and only 2 SE of slack between
    # 1-point neighbours. Measured on the first run (WNBA, n=250): 0.320 at 0 vs 0.316 at +1, a 0.004 dip at an SE
    # of ~0.03.
    kw = _kwargs(league, seed=3)
    n = 120
    seeds = range(n)

    def p_at(margin: int) -> float:
        st = GameState(period=4, seconds_remaining=240, home_period_pts=(last_q, last_q, last_q, 10 + max(margin, 0)), away_period_pts=(last_q, last_q, last_q, 10 + max(-margin, 0)))
        assert st.home_score - st.away_score == margin
        return _win_prob(kw, lp, st, seeds)

    coarse = {m: p_at(m) for m in (-12, -8, -4, 0, 4, 8, 12)}
    vals = list(coarse.values())
    assert all(b > a or (a == b and a in (0.0, 1.0)) for a, b in zip(vals, vals[1:])), coarse
    assert coarse[-12] <= 0.08 and coarse[12] >= 0.92, coarse
    for m in (-1, 1):
        p, p0 = p_at(m), coarse[0]
        se = float(np.sqrt(max(p0 * (1 - p0), 1e-9) / n))
        assert (p - p0) * m >= -2 * se, (m, p, p0, se)


def test_a_lead_is_worth_more_the_less_time_is_left():
    kw = _kwargs("nba", seed=5)
    seeds = range(120)
    probs = []
    for left in (720, 480, 240, 120, 30):
        st = GameState(period=4, seconds_remaining=left, home_period_pts=(25, 25, 25, 6), away_period_pts=(25, 25, 25, 0))
        probs.append(_win_prob(kw, NBA, st, seeds))
    assert all(b >= a for a, b in zip(probs, probs[1:])), probs
    assert probs[-1] >= 0.97, probs


def test_expected_remaining_points_shrink_with_the_clock():
    kw = _kwargs("wnba", seed=9)
    means = []
    for left in (600, 300, 120, 30, 0):
        st = GameState(period=4, seconds_remaining=left, home_period_pts=(20, 20, 20, 5), away_period_pts=(20, 20, 20, 0))
        tot = [sum(_final(_run(kw, WNBA, s, st)[0])) - (st.home_score + st.away_score) for s in range(80)]
        means.append(float(np.mean(tot)))
    assert all(b <= a for a, b in zip(means, means[1:])), means
    assert means[-1] == 0.0, means  # Q4 0:00, not tied: the game is over


# ---------------------------------------------------------------------------------------------------------------
# 3. What a resumed run returns, and that each consumed field reaches the loop
# ---------------------------------------------------------------------------------------------------------------


def test_completed_periods_come_from_the_state_and_the_current_one_includes_its_points_so_far():
    kw = _kwargs("nba", seed=13)
    st = GameState(period=3, seconds_remaining=300, home_period_pts=(30, 22, 9), away_period_pts=(21, 27, 4))
    for seed in range(20):
        h_box, a_box, hq, aq = _run(kw, NBA, seed, st)[0]
        assert hq[:2] == [30, 22] and aq[:2] == [21, 27]
        assert hq[2] >= 9 and aq[2] >= 4
        # Player lines are the REMAINDER only: they cannot account for the points already on the board.
        assert sum(p["pts"] for p in h_box["players"]) == sum(hq) + sum(h_box.get("ot_pts") or []) - st.home_score


def test_resume_in_overtime_keeps_the_regulation_and_earlier_overtime_points():
    kw = _kwargs("nba", seed=17)
    st = GameState(period=6, seconds_remaining=60, home_period_pts=(25, 25, 25, 25, 10, 3), away_period_pts=(25, 25, 25, 25, 10, 1))
    for seed in range(10):
        h_box, a_box, hq, aq = _run(kw, NBA, seed, st)[0]
        assert hq == [25, 25, 25, 25] and aq == [25, 25, 25, 25]
        assert h_box["ot_pts"][0] == 10 and a_box["ot_pts"][0] == 10
        assert h_box["ot_pts"][1] >= 3 and a_box["ot_pts"][1] >= 1
        h, a = _final((h_box, a_box, hq, aq))
        assert h != a or len(h_box["ot_pts"]) == 6  # decided, or the 6-overtime safety cap


def test_possession_and_on_floor_reach_the_first_possession():
    kw = _kwargs("nba", seed=19)
    cfg = replace(kw.get("cfg") or EventSimConfig(), record_events=True)
    kw["cfg"] = cfg
    names = list(kw["home_players"]["player_name"])
    five = tuple(names[-5:])  # the five LOWEST-minute players: the sampler would almost never pick exactly these
    for side in ("home", "away"):
        st = GameState(period=2, seconds_remaining=400, home_period_pts=(20, 10), away_period_pts=(22, 9), possession=side, home_on_floor=five)
        for seed in range(15):
            h_box = _run(kw, NBA, seed, st)[0][0]
            first = h_box["events"][0]
            assert first["off"] == ("H" if side == "home" else "A")
            if side == "home":
                idx = first.get("sh", first.get("player_i"))
                assert names[idx] in five


def test_a_fouled_out_player_takes_no_further_part():
    kw = _kwargs("nba", seed=23)
    star = str(kw["home_players"].sort_values("_sim_min", ascending=False)["player_name"].iloc[0])
    st = GameState(period=3, seconds_remaining=600, home_period_pts=(25, 25, 2), away_period_pts=(25, 25, 0), home_player_fouls={star: 6})
    from syndicate.features.shared.basketball_props_smart_sim import _sample_lineup_local

    for sampler in (None, _sample_lineup_local):
        for seed in range(25):
            h_box = _run(kw, NBA, seed, st, sampler=sampler)[0][0]
            line = next(p for p in h_box["players"] if p["player_name"] == star)
            assert all(line[k] == 0 for k in ("pts", "fga", "reb", "ast", "tov", "stl", "blk", "pf")), line
    # Five fouls is not out (foul trouble is a P3 mechanism): the star still plays.
    st5 = replace(st, home_player_fouls={star: 5})
    assert any(next(p for p in _run(kw, NBA, s, st5)[0][0]["players"] if p["player_name"] == star)["fga"] > 0 for s in range(10))


def test_resume_off_differs_from_on():
    """Reachability (model engine standard §4.3): a non-tip state must change the run."""
    kw = _kwargs("wnba", seed=29)
    st = GameState(period=2, seconds_remaining=200, home_period_pts=(18, 12), away_period_pts=(20, 9))
    assert any(_run(kw, WNBA, s)[0] != _run(kw, WNBA, s, st)[0] for s in range(3))


@pytest.mark.parametrize(
    "bad,match",
    [
        (GameState(period=0), "period"),
        (GameState(period=2, seconds_remaining=900), "seconds_remaining"),
        (GameState(period=2, home_period_pts=(1, 2, 3)), "home_period_pts"),
        (GameState(period=5, home_period_pts=(20, 20, 20, 20), away_period_pts=(20, 20, 20, 21)), "not tied"),
        (GameState(period=3, possession="neither"), "possession"),
        (GameState(period=3, home_on_floor=("a", "b")), "home_on_floor"),
        (GameState(period=3, home_period_pts=(10, -1)), "negative"),
    ],
)
def test_an_impossible_state_is_refused_by_name(bad, match):
    kw = _kwargs("nba")
    with pytest.raises(ValueError, match=match):
        _run(kw, NBA, 0, bad)


def test_an_unknown_on_floor_name_is_refused_not_dropped():
    kw = _kwargs("nba")
    st = GameState(period=2, home_period_pts=(20, 0), away_period_pts=(20, 0), home_on_floor=("x", "y", "z", "u", "v"))
    with pytest.raises(ValueError, match="not in the home player frame"):
        _run(kw, NBA, 0, st)


# ---------------------------------------------------------------------------------------------------------------
# NCAAB geometry hook (P4 owns its rates)
# ---------------------------------------------------------------------------------------------------------------


def test_ncaab_plays_two_halves_and_resumes_in_the_second():
    kw = _kwargs("nba", seed=31)
    kw.pop("quarters", None)
    for seed in range(5):
        h_box, a_box, hq, aq = _run(kw, NCAAB, seed)[0]
        assert len(hq) == 2 and len(aq) == 2
        assert all(len(p["q_pts"]) == 2 for p in h_box["players"])
    st = GameState(period=2, seconds_remaining=60, home_period_pts=(35, 30), away_period_pts=(30, 20))
    p = _win_prob(kw, NCAAB, st, range(100))
    assert p >= 0.97, p


def test_league_params_unknown_code_raises():
    from syndicate.features.basketball_engine import league_params

    with pytest.raises(ValueError):
        league_params("euroleague")
    assert {f.name for f in fields(LeagueParams)} >= {"regulation_periods", "personal_foul_limit", "shot_clock_seconds"}
