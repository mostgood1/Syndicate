"""P3 live mechanisms in the native engine (lane nba-native-live-resim, LOAN from basketball-native-engine).

Every mechanism is default-off and must be (1) byte-identical when off and (2) REACHABLE (`off != on`) where it
must bite. No rate here is fitted: re-fits are on hold until #473 (NBA team_adj unfed), user decision 2026-10-09.
"""
from __future__ import annotations

import dataclasses

import numpy as np

from syndicate.features.basketball_engine import NBA, EventSimConfig, GameState, simulate_pbp_game_boxscore
from tests.basketball_engine_fixtures import synthetic_game_kwargs


def _kw(seed: int = 7):
    kw = synthetic_game_kwargs(np.random.default_rng(seed), league="nba", entrypoint="simulate_pbp_game_boxscore")
    kw.pop("rng", None)
    return kw


def _with_cfg(kw, **fields):
    base = kw.get("cfg") or EventSimConfig(possessions_per_game=float(NBA.default_possessions_per_game))
    vals = {f.name: getattr(base, f.name) for f in dataclasses.fields(base) if hasattr(EventSimConfig, f.name)}
    return {**kw, "cfg": EventSimConfig(**{**vals, **fields, "record_events": True})}


def _run(kw, state, seed):
    rng = np.random.default_rng(seed)
    out = simulate_pbp_game_boxscore(rng=rng, **kw, league=NBA, state=state)
    return out, rng.bit_generator.state


DOWN5_2MIN = GameState(period=4, seconds_remaining=120, home_period_pts=(25, 25, 25, 20), away_period_pts=(25, 25, 25, 25))
ENDGAME_ON = dict(endgame_foul_window_s=120, endgame_foul_max_deficit=10, endgame_foul_p=0.6,
                  endgame_foul_seconds=5.0, endgame_extend_possessions=True)


def _late_rates(kw, state, draws=60):
    fta = pts = 0.0
    for s in range(draws):
        (hb, ab, hq, aq), _ = _run(kw, state, s)
        evs = [e for e in (hb.get("events") or []) if e.get("q") == 4 and e.get("type") == "FTA"]
        fta += sum(e.get("fta", 0) for e in evs)
        pts += hq[3] + aq[3] - sum(x for x in (state.home_period_pts[3:4] + state.away_period_pts[3:4]))
    return fta / draws / 2.0, pts / draws / 2.0


def test_off_is_byte_identical_with_explicit_zero_fields():
    kw = _kw()
    a = _run(kw, DOWN5_2MIN, 3)
    zeroed = _with_cfg(kw, endgame_foul_window_s=0, endgame_foul_p=0.9, endgame_extend_possessions=True)
    zeroed["cfg"] = dataclasses.replace(zeroed["cfg"], record_events=bool(getattr(kw.get("cfg"), "record_events", False)))
    b = _run(zeroed, DOWN5_2MIN, 3)
    assert a[0][2] == b[0][2] and a[0][3] == b[0][3]
    assert a[1] == b[1]  # identical RNG consumption


def test_endgame_fouling_is_reachable_and_raises_late_fta_and_scoring():
    kw = _kw()
    off_fta, off_pts = _late_rates(_with_cfg(kw), DOWN5_2MIN)
    on_fta, on_pts = _late_rates(_with_cfg(kw, **ENDGAME_ON), DOWN5_2MIN)
    assert on_fta > off_fta + 1.0
    assert on_pts > off_pts


def test_endgame_fouling_never_fires_outside_its_window():
    kw = _with_cfg(_kw(), **ENDGAME_ON)
    q3 = GameState(period=3, seconds_remaining=120, home_period_pts=(25, 25, 20), away_period_pts=(25, 25, 25))
    # 30 down with 2:00 left cannot get back inside the 1-10 band in time.
    blowout = GameState(period=4, seconds_remaining=120, home_period_pts=(25, 25, 25, 0), away_period_pts=(30, 30, 30, 30))
    for s in range(20):
        (hb, ab, _hq, _aq), _ = _run(kw, q3, s)
        evs = (hb.get("events") or []) + (ab.get("events") or [])
        # a Q3 resume plays Q4 too: fouls may appear there, never in Q3
        assert not any(e.get("intentional") and e.get("q") != 4 for e in evs)
        (hb, ab, _hq, _aq), _ = _run(kw, blowout, s)
        evs = (hb.get("events") or []) + (ab.get("events") or [])
        assert not any(e.get("intentional") for e in evs)


def test_production_config_class_without_the_fields_is_unaffected():
    """Production passes its own frozen config class (EventSimConfigLocal) lacking every P3 field: getattr defaults
    must read as OFF."""
    from syndicate.features.shared.basketball_props_smart_sim import EventSimConfigLocal

    names = {f.name for f in dataclasses.fields(EventSimConfigLocal)}
    assert not names & {"endgame_foul_window_s", "endgame_foul_p", "endgame_extend_possessions"}


def test_per_deficit_bucket_probability_routes_by_deficit():
    """Bucket 4-6 ON alone must raise late FTA at down 5 and leave down 2 at the OFF rate."""
    kw = _kw()
    only_4_6 = dict(ENDGAME_ON, endgame_foul_p=0.0, endgame_foul_p_by_deficit=(0.0, 0.7, 0.0))
    down2 = GameState(period=4, seconds_remaining=120, home_period_pts=(25, 25, 25, 23), away_period_pts=(25, 25, 25, 25))
    off2, _ = _late_rates(_with_cfg(kw), down2, draws=40)
    on2, _ = _late_rates(_with_cfg(kw, **only_4_6), down2, draws=40)
    off5, _ = _late_rates(_with_cfg(kw), DOWN5_2MIN, draws=40)
    on5, _ = _late_rates(_with_cfg(kw, **only_4_6), DOWN5_2MIN, draws=40)
    assert on5 > off5 + 1.0
    # down 2 bites only once the margin wanders into 4-6 during the 2:00 (a real path), so its lift is a fraction
    # of the direct one
    assert (on5 - off5) > 2.0 * (on2 - off2)


def test_empty_bucket_tuple_is_the_scalar_path():
    kw = _kw()
    a = _run(_with_cfg(kw, **ENDGAME_ON), DOWN5_2MIN, 9)
    b = _run(_with_cfg(kw, **ENDGAME_ON, endgame_foul_p_by_deficit=()), DOWN5_2MIN, 9)
    assert a[0][2] == b[0][2] and a[1] == b[1]


# ------------------------------------------------------------------------------------------- in-sim foul-outs

def _over_limit_share(kw, state, draws, seed0=0):
    over = n = 0
    for s in range(draws):
        (hb, ab, _hq, _aq), _ = _run(kw, state, seed0 + s)
        for box in (hb, ab):
            for r in box.get("players") or []:
                n += 1
                over += int(r.get("pf") or 0) > NBA.personal_foul_limit
    return over / max(1, n)


def test_foul_out_in_sim_benches_players_at_the_league_limit():
    """Reachability: with fouls forced high, OFF lets many players foul past 6; ON almost never does. Not exactly
    never: the check runs at possession start (one multi-foul possession can add two), and a team short of eligible
    players must field fouled-out ones -- the real rule too."""
    kw = _kw()
    hot = dict(base_nonshooting_foul_per_poss=0.45, base_shooting_foul_per_fga=0.4)
    off = _over_limit_share(_with_cfg(kw, **hot), None, 12)
    on = _over_limit_share(_with_cfg(kw, **hot, foul_out_in_sim=True), None, 12)
    assert off > 0.05 and on < off / 5


def test_foul_out_in_sim_counts_fouls_carried_from_a_resumed_state():
    kw = _with_cfg(_kw(), base_nonshooting_foul_per_poss=0.45, base_shooting_foul_per_fga=0.4, foul_out_in_sim=True)
    name = str(kw["home_players"]["player_name"].iloc[0])
    st = GameState(period=3, seconds_remaining=600, home_period_pts=(25, 25, 10), away_period_pts=(25, 25, 10),
                   home_player_fouls={name: 5})
    for s in range(12):
        (hb, _ab, _hq, _aq), _ = _run(kw, st, s)
        row = next(r for r in hb["players"] if r["player_name"] == name)
        assert int(row.get("pf") or 0) <= 1  # 5 carried + at most 1 more, then out


def test_foul_out_off_is_byte_identical():
    kw = _kw()
    a = _run(_with_cfg(kw), DOWN5_2MIN, 4)
    b = _run(_with_cfg(kw, foul_out_in_sim=False), DOWN5_2MIN, 4)
    assert a[0][2] == b[0][2] and a[1] == b[1]


# ------------------------------------------------------------------------------------------- foul-trouble benching

def _foul_outs(kw, draws, seed0=0):
    n = 0
    for s in range(draws):
        (hb, ab, _hq, _aq), _ = _run(kw, None, seed0 + s)
        n += sum(1 for b in (hb, ab) for r in b.get("players") or [] if int(r.get("pf") or 0) >= NBA.personal_foul_limit)
    return n / draws


def test_foul_trouble_benching_is_reachable_and_cuts_foul_outs():
    kw = _kw()
    warm = dict(base_nonshooting_foul_per_poss=0.2, base_shooting_foul_per_fga=0.2)
    off = _foul_outs(_with_cfg(kw, **warm), 20)
    on = _foul_outs(_with_cfg(kw, **warm, foul_trouble_bench_mult=0.05), 20)
    assert off > 0.5 and on < off * 0.7


def test_foul_trouble_off_is_byte_identical():
    kw = _kw()
    a = _run(_with_cfg(kw), None, 6)
    b = _run(_with_cfg(kw, foul_trouble_bench_mult=1.0, foul_trouble_thresholds=(1, 1, 1, 1)), None, 6)
    assert a[0][2] == b[0][2] and a[1] == b[1]


def test_foul_trouble_mult_zero_is_full_benching_not_off():
    """0.0 must bench outright -- `x or 1.0` once read it as OFF (calibration lane #3b, 2026-10-14)."""
    kw = _kw()
    warm = dict(base_nonshooting_foul_per_poss=0.2, base_shooting_foul_per_fga=0.2)
    off = _foul_outs(_with_cfg(kw, **warm), 20)
    zero = _foul_outs(_with_cfg(kw, **warm, foul_trouble_bench_mult=0.0), 20)
    small = _foul_outs(_with_cfg(kw, **warm, foul_trouble_bench_mult=0.05), 20)
    assert zero < off * 0.7
    assert zero <= small + 0.25


# ------------------------------------------------------------------------------------------- foul avoidance in trouble

def test_foul_avoidance_off_is_byte_identical():
    kw = _kw()
    a = _run(_with_cfg(kw), None, 6)
    b = _run(_with_cfg(kw, foul_trouble_foul_mult=1.0, foul_trouble_thresholds=(1, 1, 1, 1)), None, 6)
    assert a[0][2] == b[0][2] and a[1] == b[1]


def test_foul_avoidance_is_reachable_and_cuts_foul_outs_without_benching():
    """off != on, and it works in the release window too: benching is OFF here (bench_mult 1.0)."""
    kw = _kw()
    warm = dict(base_nonshooting_foul_per_poss=0.2, base_shooting_foul_per_fga=0.2, foul_out_in_sim=True)
    off = _foul_outs(_with_cfg(kw, **warm), 20)
    on = _foul_outs(_with_cfg(kw, **warm, foul_trouble_foul_mult=0.2), 20)
    assert on != off
    assert on < off * 0.8


# ------------------------------------------------------------------------------------------- per-minute fouler

def _top5_pf_share(kw, draws, seed0=0):
    top = tot = 0
    for s in range(draws):
        (hb, ab, _hq, _aq), _ = _run(kw, None, seed0 + s)
        for b in (hb, ab):
            rows = sorted(b.get("players") or [], key=lambda r: -float(r.get("min") or 0))
            pf = [int(r.get("pf") or 0) for r in rows]
            top += sum(pf[:5]); tot += sum(pf)
    return top / max(tot, 1)


def test_fouler_per_minute_off_is_byte_identical():
    kw = _kw()
    a = _run(_with_cfg(kw), None, 6)
    b = _run(_with_cfg(kw, fouler_per_minute=False), None, 6)
    assert a[0][2] == b[0][2] and a[1] == b[1]


def test_fouler_per_minute_is_reachable_and_lowers_the_starter_pf_share():
    """The blended weight's 0.25 minutes share tilts fouls toward high-minute players; per-minute removes it."""
    kw = _kw()
    off = _top5_pf_share(_with_cfg(kw), 20)
    on = _top5_pf_share(_with_cfg(kw, fouler_per_minute=True), 20)
    assert on != off
    assert on < off


# ------------------------------------------------------------------------------------------- solver terms (EXACT target)

def test_solver_bonus_share_zero_is_the_old_solve():
    from syndicate.features.basketball_engine.engine import _solve_eff_mult
    args = dict(p_tov=0.13, p3=0.39, fg2=0.53, fg3=0.36, foul=0.11, ft=0.78, oreb=0.25)
    assert _solve_eff_mult(1.14, **args) == _solve_eff_mult(1.14, **args, bonus_trip_share=0.0, bonus_ft=0.9)


def test_solver_bonus_share_lowers_eff_when_trips_outscore_loop_possessions():
    """A two-shot trip at 78% (1.56 pts) beats a ~1.1 ppp loop possession, so hitting the same target needs less eff."""
    from syndicate.features.basketball_engine.engine import _solve_eff_mult
    args = dict(p_tov=0.13, p3=0.39, fg2=0.53, fg3=0.36, foul=0.11, ft=0.78, oreb=0.25)
    assert _solve_eff_mult(1.14, **args, bonus_trip_share=0.05, bonus_ft=0.78) < _solve_eff_mult(1.14, **args)


def _exact_total(kw, draws, **fields):
    lp = dataclasses.replace(NBA, exact_target_calibration=True)
    t = 0.0
    for s in range(draws):
        rng = np.random.default_rng(100 + s)
        (_hb, _ab, hq, aq) = simulate_pbp_game_boxscore(rng=rng, **_with_cfg(kw, **fields), league=lp, state=None)
        t += sum(hq) + sum(aq)
    return t / draws


def test_solver_terms_are_inert_when_their_mechanism_is_off():
    kw = _kw()
    lp = dataclasses.replace(NBA, exact_target_calibration=True)
    a = simulate_pbp_game_boxscore(rng=np.random.default_rng(3), **_with_cfg(kw), league=lp, state=None)
    b = simulate_pbp_game_boxscore(rng=np.random.default_rng(3), **_with_cfg(kw, solver_bonus_trip_share=0.05, solver_endgame_pts_per_team=1.0), league=lp, state=None)
    assert a[2] == b[2] and a[3] == b[3]


def test_solver_endgame_offset_is_reachable_and_lowers_totals():
    kw = _kw()
    eg = dict(ENDGAME_ON)
    off = _exact_total(kw, 30, **eg)
    on = _exact_total(kw, 30, **eg, solver_endgame_pts_per_team=3.0)
    assert on != off and on < off


def test_solver_bonus_term_is_reachable_with_the_bonus_on():
    kw = _kw()
    bonus = dict(bonus_free_throws=True, bonus_nonshoot_foul_per_poss=0.04)
    off = _exact_total(kw, 30, **bonus)
    on = _exact_total(kw, 30, **bonus, solver_bonus_trip_share=0.05)
    assert on != off and on < off
