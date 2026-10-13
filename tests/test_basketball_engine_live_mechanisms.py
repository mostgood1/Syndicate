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
