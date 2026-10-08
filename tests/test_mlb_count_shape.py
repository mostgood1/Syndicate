"""Per-count outcome table in the pitch model (lane mlb-statsapi-asof-rebuild)."""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import replace

from tests.test_mlb_starter_leash_tunable import _roster
from vendor.mlb_bettingv2.sim_engine.models import GameConfig
from vendor.mlb_bettingv2.sim_engine.simulate import simulate_game


def _calls(table, count_key, n_games=12):
    away, home = _roster(1, "AWY", 100000), _roster(2, "HOM", 200000)
    pmo = {} if table is None else {"count_outcome_mult": table}
    c = Counter()
    for i in range(n_games):
        r = simulate_game(away, home, GameConfig(rng_seed=40 + i, manager_pitching="v2", pbp="pitch", pitch_model_overrides=pmo))
        for ev in r.pbp or []:
            if ev.get("type") == "PITCH" and f"{ev['count']['balls']}-{ev['count']['strikes']}" == count_key:
                c[ev["call"]] += 1
    return c


def test_empty_table_is_identical_to_no_table():
    away, home = _roster(1, "AWY", 100000), _roster(2, "HOM", 200000)
    a = simulate_game(away, home, GameConfig(rng_seed=7, manager_pitching="v2"))
    b = simulate_game(away, home, GameConfig(rng_seed=7, manager_pitching="v2", pitch_model_overrides={"count_outcome_mult": {}}))
    assert (a.away_score, a.home_score, a.pitcher_stats) == (b.away_score, b.home_score, b.pitcher_stats)


def test_a_cell_multiplier_moves_only_its_count():
    base = _calls(None, "0-0")
    up = _calls({"0-0": {"inplay": 0.2}}, "0-0")
    share = lambda c: c["IN_PLAY"] / max(1, sum(c.values()))  # noqa: E731
    assert share(up) < 0.6 * share(base)


def test_a_three_oh_take_table_cuts_three_oh_balls_in_play():
    base = _calls(None, "3-0", n_games=30)
    take = _calls({"3-0": {"inplay": 0.07, "called": 4.8, "swing": 0.16, "foul": 0.2}}, "3-0", n_games=30)
    share = lambda c, k: c[k] / max(1, sum(c.values()))  # noqa: E731
    assert share(take, "IN_PLAY") < share(base, "IN_PLAY") and share(take, "CALLED_STRIKE") > share(base, "CALLED_STRIKE")
