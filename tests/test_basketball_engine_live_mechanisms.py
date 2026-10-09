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
