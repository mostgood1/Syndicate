"""WNBA smart-sim player allocation (lane wnba-sim-usage-flattening).

Measured 2026-10-01 in the REAL PBP engine with actual minutes as input: the
vendored `events._sample_lineup` drew 5 with numpy `choice(replace=False, p=w)`,
which compresses inclusion probabilities toward uniform -- on-court/minutes share
0.88 for 28+ minute players, 1.23 for under-18. And "A'ja Wilson" missed her
prior on an apostrophe. (A proportional-usage change was ALSO tested and made
predictions worse on a 31-game backtest; it is deliberately absent.)
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared import basketball_props_smart_sim as sim

MINUTES = np.array([35, 34, 30, 28, 25, 18, 15, 12, 2.0])


def test_inclusion_probabilities_are_exactly_proportional_and_capped():
    pi = sim._pips_inclusion_probabilities_local(MINUTES, 5)
    assert pi.sum() == pytest.approx(5.0)
    assert pi[0] == pytest.approx(5 * 35 / MINUTES.sum())
    capped = sim._pips_inclusion_probabilities_local(np.array([100, 1, 1, 1, 1, 1]), 5)
    assert capped[0] == 1.0 and capped.sum() == pytest.approx(5.0)


def test_the_sampler_hits_the_target_and_the_vendor_draw_did_not():
    players = pd.DataFrame({"x": range(len(MINUTES))})
    rng = np.random.default_rng(0)
    n = 20000
    counts = np.zeros(len(MINUTES))
    vendor = np.zeros(len(MINUTES))
    p = MINUTES / MINUTES.sum()
    for _ in range(n):
        lineup = sim._sample_lineup_local(rng, players, MINUTES)
        assert len(lineup) == 5 and len(set(lineup)) == 5
        counts[lineup] += 1
        vendor[rng.choice(len(MINUTES), size=5, replace=False, p=p)] += 1
    target = sim._pips_inclusion_probabilities_local(MINUTES, 5)
    assert np.abs(counts / n - target).max() < 0.015
    # The defect being fixed: the 35-minute player is well under target there.
    assert vendor[0] / n < target[0] - 0.08


def test_blowout_bench_boost_is_kept():
    players = pd.DataFrame({"x": range(len(MINUTES))})
    rng = np.random.default_rng(1)
    plain = np.zeros(len(MINUTES))
    boosted = np.zeros(len(MINUTES))
    for _ in range(4000):
        plain[sim._sample_lineup_local(rng, players, MINUTES)] += 1
        boosted[sim._sample_lineup_local(rng, players, MINUTES, blowout_boost_bench=True)] += 1
    assert boosted[0] < plain[0] and boosted[-2] > plain[-2]


def test_prior_join_uses_the_priors_own_name_key():
    priors = SimpleNamespace(rates={("LVA", "AJA WILSON"): {"pts_pm": 0.88}, ("IND", "CAITLIN CLARK"): {"pts_pm": 0.69}})
    assert sim._prior_rates_for_player_local(priors=priors, team_tri="LVA", pkey="A'JA WILSON", player_name="A'ja Wilson") == {"pts_pm": 0.88}
    assert sim._prior_rates_for_player_local(priors=priors, team_tri="IND", pkey="CAITLIN CLARK", player_name="Caitlin Clark") == {"pts_pm": 0.69}
    assert sim._prior_rates_for_player_local(priors=priors, team_tri="LVA", pkey="NOBODY", player_name="Nobody") == {}


def test_the_real_engine_runs_with_the_local_sampler_and_is_restored(monkeypatch):
    seen = {}

    def vendor_sample(*args, **kwargs):
        return "vendor"

    def entry(players):
        seen["sampler"] = fake._sample_lineup
        return "ok"

    fake = SimpleNamespace(_sample_lineup=vendor_sample, simulate_pbp_game_boxscore=entry)
    monkeypatch.setattr(sim, "_import_real_events_module_local", lambda package_name: fake)
    assert sim._call_real_events_entrypoint_local(entrypoint_name="simulate_pbp_game_boxscore", league_code="wnba", kwargs={"players": None}) == "ok"
    assert seen["sampler"] is sim._sample_lineup_local
    assert fake._sample_lineup is vendor_sample
