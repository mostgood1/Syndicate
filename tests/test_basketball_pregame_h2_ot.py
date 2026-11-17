"""The pregame smart-sim's second half = q3 + q4 + every overtime, DEFAULT OFF (todo #820, lane nba-pregame-h2-ot).

`score.dist.segments.h2` was quarters 3+4 only. Every book settles a second-half line with all its overtime, and
so do `segment_actuals` and the NBA live re-sim. These tests pin, in order:

  1. the switch: per league, absent / empty / unknown / "0" are OFF;
  2. OFF is byte-identical to the attach without the keyword (no stamp, h2 = q3 + q4);
  3. ON: h2 is q3 + q4 + that draw's OT points, draw by draw, for total AND margin; nothing else moves; the dist is
     stamped `h2_includes_ot: true`; with no OT draw the segments equal OFF's;
  4. REACHABILITY: through the real `_call_source_simulate_smart_game_local` (what the sim worker calls per game),
     env unset != env set, and the NBA switch does not turn WNBA on;
  5. the served NBA h2 row's raw sim probability (`p_model_raw`) moves with it.
"""

from __future__ import annotations

import json

import pytest

import syndicate.features.shared.basketball_props_smart_sim as smart_sim
from syndicate.features.shared import nba_game_projections as ngp

NBA_ENV = "SYNDICATE_NBA_SIM_H2_INCLUDES_OT"
WNBA_ENV = "SYNDICATE_WNBA_SIM_H2_INCLUDES_OT"


def _draw(hq, aq, *, hot=(), aot=()):
    return {"ot_pts": list(hot), "players": []}, {"ot_pts": list(aot), "players": []}, list(hq), list(aq)


# Two draws tie after regulation (one single OT, one double OT); two do not.
DRAWS = [
    _draw([28, 27, 26, 29], [27, 28, 25, 30], hot=(12,), aot=(10,)),        # 110-110 -> OT 12-10
    _draw([30, 25, 28, 27], [26, 27, 29, 24]),                               # 110-106
    _draw([25, 28, 27, 30], [29, 26, 28, 24]),                               # 110-107
    _draw([27, 27, 27, 27], [28, 26, 26, 28], hot=(11, 9), aot=(11, 12)),    # 108-108 -> 2OT 20-23
]


def _recorded(draws):
    recorded: list = []
    wrapped = smart_sim._recording_sim_draws_local(lambda **kw: draws[kw["i"]], recorded)
    for i in range(len(draws)):
        wrapped(i=i)
    return recorded


def _values(hist):
    return sorted(int(v) for v, c in hist.items() for _ in range(c))


def _dist(draws, **kwargs):
    out = {"score": {}, "players": {}}
    smart_sim._attach_sim_distributions_local(out, _recorded(draws), **kwargs)
    return out["score"]["dist"]


# 1. ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", "0", "off", "false", "no", "maybe"])
def test_the_switch_is_off_unless_set_truthy(raw):
    env = {} if raw is None else {NBA_ENV: raw}
    assert smart_sim._sim_h2_includes_ot_local("nba", env) is False


@pytest.mark.parametrize("raw", ["1", "true", "yes", "on", " ON "])
def test_the_switch_is_on_for_its_own_league_only(raw):
    env = {NBA_ENV: raw}
    assert smart_sim._sim_h2_includes_ot_local("nba", env) is True
    assert smart_sim._sim_h2_includes_ot_local("NBA", env) is True
    assert smart_sim._sim_h2_includes_ot_local("wnba", env) is False
    assert smart_sim._sim_h2_includes_ot_local("wnba", {WNBA_ENV: raw}) is True
    # A league with no switch is never on.
    assert smart_sim._sim_h2_includes_ot_local("ncaab", {NBA_ENV: raw, WNBA_ENV: raw}) is False


# 2. ---------------------------------------------------------------------------


def test_off_is_byte_identical_to_the_attach_without_the_keyword():
    before = _dist(DRAWS)
    off = _dist(DRAWS, h2_includes_ot=False)
    assert json.dumps(off, sort_keys=True) == json.dumps(before, sort_keys=True)
    assert "h2_includes_ot" not in off
    q3q4 = [d[2][2] + d[2][3] + d[3][2] + d[3][3] for d in DRAWS]
    assert _values(off["segments"]["h2"]["total"]) == sorted(q3q4)


# 3. ---------------------------------------------------------------------------


def test_on_adds_each_draws_overtime_to_h2_total_and_margin_and_nothing_else():
    off = _dist(DRAWS)
    on = _dist(DRAWS, h2_includes_ot=True)

    h2_total = [d[2][2] + d[2][3] + sum(d[0]["ot_pts"]) + d[3][2] + d[3][3] + sum(d[1]["ot_pts"]) for d in DRAWS]
    h2_margin = [(d[2][2] + d[2][3] + sum(d[0]["ot_pts"])) - (d[3][2] + d[3][3] + sum(d[1]["ot_pts"])) for d in DRAWS]
    assert _values(on["segments"]["h2"]["total"]) == sorted(h2_total) == [108, 109, 132, 151]
    assert _values(on["segments"]["h2"]["margin"]) == sorted(h2_margin) == [-3, 2, 2, 5]
    assert on["segments"]["h2"] != off["segments"]["h2"]

    # Every other segment is untouched; full still adds OT; h1 + h2 now partitions the whole game.
    for segment in ("q1", "q2", "q3", "q4", "h1", "regulation", "full"):
        assert on["segments"][segment] == off["segments"][segment], segment
    full = sum(_values(on["segments"]["full"]["total"]))
    assert sum(_values(on["segments"]["h1"]["total"])) + sum(_values(on["segments"]["h2"]["total"])) == full
    assert on["h2_includes_ot"] is True
    assert {k: v for k, v in on.items() if k != "h2_includes_ot"}.keys() == off.keys()


def test_on_with_no_overtime_draw_changes_no_histogram():
    no_ot = [DRAWS[1], DRAWS[2]]
    off = _dist(no_ot)
    on = _dist(no_ot, h2_includes_ot=True)
    assert on["segments"] == off["segments"]
    assert on["h2_includes_ot"] is True


# 4. ---------------------------------------------------------------------------


def _through_the_worker_call(monkeypatch, tmp_path, league_code):
    """A stand-in orchestrator that calls the per-draw hook as the real one does (`orchestrator/hooks.py`)."""
    from syndicate.features.basketball_engine import orchestrator as orch_pkg
    from syndicate.features.basketball_engine.orchestrator import hooks, prop_ladders

    draws = iter(DRAWS)
    monkeypatch.setattr(smart_sim, "_simulate_pbp_game_boxscore_local", lambda **kw: next(draws))
    monkeypatch.setattr(prop_ladders, "build_exact_ladder_payload", lambda values: {"values": sorted(values)})

    def simulate_smart_game(n_sims, *, orch):
        for _ in range(n_sims):
            hooks.simulate_pbp_game_boxscore(rng=None, orch=orch)
        return {"score": {"p_total_over": 0.5}, "players": {"home": [], "away": []}}

    monkeypatch.setattr(orch_pkg, "simulate_smart_game", simulate_smart_game)
    out = smart_sim._call_source_simulate_smart_game_local(
        processed_root=tmp_path / "data" / "processed", league_code=league_code, kwargs={"n_sims": len(DRAWS)}
    )
    return out["score"]["dist"]


def test_reachability_through_the_worker_call_off_is_not_on(monkeypatch, tmp_path):
    monkeypatch.delenv(NBA_ENV, raising=False)
    monkeypatch.delenv(WNBA_ENV, raising=False)
    off = _through_the_worker_call(monkeypatch, tmp_path, "nba")
    assert "h2_includes_ot" not in off
    assert _values(off["segments"]["h2"]["total"]) == [108, 108, 109, 110]

    monkeypatch.setenv(NBA_ENV, "1")
    on = _through_the_worker_call(monkeypatch, tmp_path, "nba")
    assert on["h2_includes_ot"] is True
    assert _values(on["segments"]["h2"]["total"]) == [108, 109, 132, 151]
    assert on["segments"]["h2"] != off["segments"]["h2"]
    assert on["segments"]["full"] == off["segments"]["full"]


def test_the_nba_switch_does_not_reach_a_wnba_sim(monkeypatch, tmp_path):
    monkeypatch.setenv(NBA_ENV, "1")
    monkeypatch.delenv(WNBA_ENV, raising=False)
    wnba = _through_the_worker_call(monkeypatch, tmp_path, "wnba")
    assert "h2_includes_ot" not in wnba
    assert _values(wnba["segments"]["h2"]["total"]) == [108, 108, 109, 110]

    monkeypatch.setenv(WNBA_ENV, "1")
    wnba_on = _through_the_worker_call(monkeypatch, tmp_path, "wnba")
    assert _values(wnba_on["segments"]["h2"]["total"]) == [108, 109, 132, 151]


# 5. ---------------------------------------------------------------------------


def test_the_served_h2_total_rows_raw_sim_probability_moves(monkeypatch):
    """The NBA board prices an h2 row from this histogram (`nba_game_projections._project_row`). OFF, 1 of 4 draws
    clear 109.5; ON, 2 of 4 do (the two OT draws reach 132 and 151, the 110 regulation draw is now 132)."""
    row = {"kind": "game", "market": "totals", "line": 109.5, "segment": "h2", "side": "over",
           "home_team": "Home Team", "away_team": "Away Team"}

    def raw_p(dist):
        entry = ngp.NbaGameEntry(slate_date="2026-11-16", home_team="Home Team", away_team="Away Team",
                                 home_tri="HOM", away_tri="AWY", dist=dist, sim_draws=dist["n"])
        projection, reason = ngp._project_row(row, "totals", "h2", entry)
        assert reason is None, reason
        return projection["p_model_raw"]

    assert raw_p(_dist(DRAWS)) == pytest.approx(0.25)
    assert raw_p(_dist(DRAWS, h2_includes_ot=True)) == pytest.approx(0.5)
