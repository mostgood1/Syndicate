"""Native vs vendored basketball engine (lane basketball-native-engine, plan P1).

The PARITY CLAIM rests on the production corpus (scripts/basketball_engine_parity.py
--corpus, reading in .syndicate/deploys.md), not on these tests. These tests
keep the port honest in CI:
  * synthetic parity, leaf for leaf and RNG state for RNG state, both leagues,
    both lineup samplers;
  * engine.py is exactly what the port tool generates from the vendored source;
  * REACHABILITY (model engine standard §4.3): every LeagueParams switch the
    engine consumes changes the output when it is flipped (off != on). A switch
    that cannot move the output is wiring that does nothing;
  * the corpus checklist's AST consumption agrees with the dataclasses.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import fields, replace
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import basketball_engine_parity as parity  # noqa: E402

from syndicate.features.basketball_engine import NBA, WNBA, LeagueParams, simulate_pbp_game_boxscore  # noqa: E402
from syndicate.features.basketball_engine.league_engine import SWITCHES, LeagueEngine  # noqa: E402
from tests.basketball_engine_fixtures import synthetic_game_kwargs  # noqa: E402


@pytest.mark.parametrize("sampler_name", ["production", "vendored_default"])
def test_synthetic_parity_is_exact(sampler_name):
    sampler = parity.production_sampler() if sampler_name == "production" else None
    n = 0
    for source, case in parity.synthetic_cases(24, seed=91 if sampler is None else 17):
        res = parity.replay_case(case, sampler)
        assert res["ok"], (source, res["diffs"])
        n += 1
    assert n == 24


def test_engine_py_is_the_port_of_the_vendored_source():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "port_basketball_engine.py"), "--check"], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def _box(lp: LeagueParams, seed: int, kw):
    return simulate_pbp_game_boxscore(rng=np.random.default_rng(seed), **kw, league=lp)


# Switch -> a value that must change the run. Credits only matter with PLAYER_REBOUND_CREDIT on; block allocation only
# in the team_prior block mode; the fg3 assumption only in team_prior; the league fallback block rate only when the
# defense carries no block priors. Each is flipped from the league where it is LIVE.
_FLIPS = {
    "shooter_ft_rate": (NBA, True),
    "fouled_miss_not_fga": (NBA, True),
    "exact_target_calibration": (NBA, True),
    "team_prior_stacks_on_target": (NBA, False),
    "tov_per_attempt": (NBA, True),
    "player_rebound_credit": (NBA, True),
    "oreb_player_credit": (WNBA, 0.5),
    "dreb_player_credit": (WNBA, 0.5),
    "block_mode": (NBA, "team_prior"),
    "block_rate_assumed_fg3_pct": (WNBA, 0.95),
    "block_alloc_by_rate": (NBA, True),
    "block_alloc_floor_pm": (WNBA, 0.5),
    "min_rate_possessions": (NBA, 120.0),
    "regulation_period_seconds": (NBA, 600),
    "ft_mult_errors_neutral": None,  # differs only when the multiplier computation RAISES; covered below
    "league_blocks_per_missed_2pa": None,  # fallback only (no block priors); covered below
    "default_possessions_per_game": None,  # only when the caller passes no cfg; covered below
    "regulation_team_minutes": None,  # only when no player carries _sim_min; covered below
    "overtime_period_seconds": None,  # only in overtime; covered below
}


@pytest.mark.parametrize("field_name", sorted(k for k, v in _FLIPS.items() if v is not None))
def test_every_consumed_switch_reaches_the_output(field_name):
    base, value = _FLIPS[field_name]
    if field_name == "block_alloc_by_rate":
        base = replace(base, block_mode="team_prior")
    if field_name == "block_alloc_floor_pm":
        base = replace(base, block_alloc_by_rate=True)
    flipped = replace(base, **{field_name: value})
    assert flipped != base
    moved = False
    for seed in range(12):
        kw = synthetic_game_kwargs(np.random.default_rng(100 + seed), league=base.code, entrypoint="simulate_pbp_game_boxscore")
        if _box(base, seed, kw) != _box(flipped, seed, kw):
            moved = True
            break
    assert moved, f"LeagueParams.{field_name}: flipping it never changed the output (inert switch)"


def test_fallback_switches_reach_the_output_when_their_condition_holds():
    kw = synthetic_game_kwargs(np.random.default_rng(5), league="nba", entrypoint="simulate_pbp_game_boxscore")
    kw.pop("cfg", None)
    a = replace(NBA, default_possessions_per_game=80.0)
    assert _box(NBA, 1, kw) != _box(a, 1, kw)  # no cfg -> the league default pace is the pace
    for side in ("home_players", "away_players"):
        kw[side] = kw[side].drop(columns=["_prior_blk_pm"], errors="ignore")
    tp = replace(NBA, block_mode="team_prior")
    assert _box(tp, 1, kw) != _box(replace(tp, league_blocks_per_missed_2pa=0.39), 1, kw)
    # _ft_rate_multipliers coerces bad input itself, so the guard matters only if the helper RAISES: force that.
    import syndicate.features.basketball_engine.engine as eng_mod

    def boom(*_a, **_k):
        raise RuntimeError("forced")

    original = eng_mod._ft_rate_multipliers
    eng_mod._ft_rate_multipliers = boom
    try:
        with pytest.raises(RuntimeError):
            _box(replace(NBA, ft_mult_errors_neutral=False), 1, kw)  # the WNBA route: the error propagates
        _box(NBA, 1, kw)  # the NBA route swallows it (neutral 1.0), as the vendored NBA engine did
    finally:
        eng_mod._ft_rate_multipliers = original


def test_minutes_and_overtime_switches_reach_the_output_when_their_condition_holds():
    from syndicate.features.basketball_engine import GameState

    kw = synthetic_game_kwargs(np.random.default_rng(8), league="nba", entrypoint="simulate_pbp_game_boxscore")
    tied_ot = GameState(period=5, home_period_pts=(25, 25, 25, 25), away_period_pts=(25, 25, 25, 25))
    run = lambda lp, seed: simulate_pbp_game_boxscore(rng=np.random.default_rng(seed), **kw, league=lp, state=tied_ot)  # noqa: E731
    assert any(run(NBA, s) != run(replace(NBA, overtime_period_seconds=60), s) for s in range(4))
    # regulation_team_minutes is INERT, in the vendored engine too: _team_rates_from_priors assigns `total_min` and
    # never reads it. Carried for parity and documented in league.py. This pins the finding: if someone wires it, this
    # fails and the checklist entry must change.
    no_min = dict(kw, home_players=kw["home_players"].drop(columns=["_sim_min"]), away_players=kw["away_players"].drop(columns=["_sim_min"]))
    assert all(_box(NBA, s, no_min) == _box(replace(NBA, regulation_team_minutes=120.0), s, no_min) for s in range(3))


def test_league_engine_switches_are_the_vendored_names_and_refuse_unknown_ones():
    eng = LeagueEngine(WNBA)
    assert eng.SHOOTER_FT_RATE is True and eng.BLOCK_MODE == "team_prior"
    eng.BLOCK_MODE = "legacy"
    assert eng.params.block_mode == "legacy" and WNBA.block_mode == "team_prior"
    with pytest.raises(AttributeError):
        eng.BLOK_MODE = "legacy"
    with pytest.raises(AttributeError):
        _ = eng.NOT_A_SWITCH
    assert set(SWITCHES.values()) <= {f.name for f in fields(LeagueParams)}


def test_the_checklist_static_mode_sees_the_wiring_and_does_not_pass_on_population():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "basketball_engine_input_checklist.py"), "--static"], capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    assert '"verdict": "STATIC-ONLY"' in out.stdout
    assert '"wiring_problems": []' in out.stdout


@pytest.mark.parametrize("code", ["nba", "wnba", "ncaab"])
def test_engine_league_params_agree_with_the_shared_league_rules(code):
    """ONE rulebook (P4's request, 2026-10-09). syndicate/features/shared/basketball_league_rules.py owns the rules
    (bonus, free throws, foul-out). The engine's LeagueParams carry the geometry the loop consumes, and must never
    disagree with it."""
    from syndicate.features.basketball_engine import league_params
    from syndicate.features.shared.basketball_league_rules import rules_for

    lp, rules = league_params(code), rules_for(code)
    assert lp.regulation_periods == rules.periods
    assert lp.regulation_period_seconds == rules.period_seconds
    assert lp.overtime_period_seconds == rules.overtime_seconds
    assert lp.shot_clock_seconds == rules.shot_clock_seconds
    assert lp.personal_foul_limit == rules.foul_out
    assert lp.team_fouls_for_bonus == (rules.one_and_one_from or rules.two_shots_from)
