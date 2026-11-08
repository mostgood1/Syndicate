"""Pure helpers of `scripts/ncaab_live_totals_bias.py` (lane ncaab-live-totals-bias): clock placement, the prior's
remaining points, and the engine's blowout rule, for the men's halves and the women's quarters."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def mod():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("ncaab_live_totals_bias", ROOT / "scripts" / "ncaab_live_totals_bias.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.PERIODS, m.PERIOD_S, m.SHARES = m.GEOMETRY["ncaab"]
    yield m
    sys.path.remove(str(ROOT / "scripts"))


def test_engine_blowout_constants_match_the_engine(mod):
    from syndicate.features.basketball_engine.engine import EventSimConfig
    from syndicate.features.ncaab import live_resim

    cfg = EventSimConfig()
    assert mod.BLOWOUT_Q4_MARGIN == cfg.blowout_q4_margin == 15
    assert cfg.blowout_margin == 18
    assert mod.H1_SHARE == live_resim.H1_SHARE


def test_men_blowout_flag_covers_the_whole_second_half(mod):
    # NCAAB has two periods, so the engine's "q >= N_PERIODS" rule is the whole second half.
    assert mod.blowout_flag(2, 15) and mod.blowout_flag(2, -20)
    assert not mod.blowout_flag(2, 14)
    assert not mod.blowout_flag(1, 30)  # the first half is never flagged


def test_women_blowout_flag_is_q4_at_15_or_second_half_at_18(mod):
    mod.PERIODS, mod.PERIOD_S, mod.SHARES = mod.GEOMETRY["wncaab"]
    assert mod.blowout_flag(4, 15) and not mod.blowout_flag(3, 15)
    assert mod.blowout_flag(3, 18) and not mod.blowout_flag(2, 30)


def test_prior_remaining_uses_the_half_split(mod):
    total = 150.0
    assert mod.prior_remaining(total, 1, 1200) == pytest.approx(total)
    assert mod.prior_remaining(total, 2, 1200) == pytest.approx(total * (1 - mod.H1_SHARE))
    assert mod.prior_remaining(total, 2, 600) == pytest.approx(total * (1 - mod.H1_SHARE) / 2)
    assert mod.prior_remaining(total, 3, 120) == 0.0  # overtime is never in a prior rate
    assert mod.regulation_left(1, 300) == 1500 and mod.regulation_left(2, 300) == 300 and mod.regulation_left(3, 60) == 0


def test_prior_remaining_women_even_quarters(mod):
    mod.PERIODS, mod.PERIOD_S, mod.SHARES = mod.GEOMETRY["wncaab"]
    assert mod.prior_remaining(140.0, 3, 300) == pytest.approx(140.0 * 0.25 * 0.5 + 140.0 * 0.25)
    assert mod.regulation_left(3, 300) == 900


def test_place_picks_the_last_play_with_that_score_before_the_state(mod):
    t0 = datetime(2026, 11, 5, 23, 0, tzinfo=timezone.utc)
    plays = [(t0, 1, 1200, 0, 0), (t0 + timedelta(seconds=30), 1, 1170, 2, 0),
             (t0 + timedelta(seconds=60), 1, 1140, 2, 0), (t0 + timedelta(seconds=90), 1, 1110, 2, 3)]
    period, clock, lag = mod.place(plays, t0 + timedelta(seconds=75), 2, 0)
    assert (period, clock, lag) == (1, 1140, 15.0)
    # ESPN's wallclock ahead of the state: the earliest play with the score
    assert mod.place(plays, t0 + timedelta(seconds=10), 2, 0)[:2] == (1, 1170)
    assert mod.place(plays, t0, 9, 9) is None


def test_phase_and_margin_bins(mod):
    assert mod.phase_bin(1, 1150) == "0 h1 >18m left"
    assert mod.phase_bin(2, 100) == "8 h2 <=2m left"
    assert mod.phase_bin(3, 200) == "9 OT"
    assert mod.margin_bin(-15) == "15-19" and mod.margin_bin(14) == "11-14" and mod.margin_bin(25) == "20+"
    assert mod.clock_seconds("18:40") == 1120 and mod.clock_seconds("12.5") == 12.5 and mod.clock_seconds("") is None


def test_blowout_penalty_counterfactual(mod):
    table = {"half": {"0": 0.0, "8": 0.0, "16": 1.0, "24": 3.0}, "h1mid": {"0": 0.0, "16": 1.0, "24": 2.0}}
    assert mod.blowout_penalty(table, 2, 1200, 14) == 0.0  # flag off below 15
    assert mod.blowout_penalty(table, 2, 1200, 15) == pytest.approx(1.0)  # 15 takes the 16 value
    assert mod.blowout_penalty(table, 2, 600, -20) == pytest.approx(2.0 * 0.5)  # interpolated, pro rata to h2 left
    assert mod.blowout_penalty(table, 2, 1200, 40) == pytest.approx(3.0)  # clamped beyond the table
    assert mod.blowout_penalty(table, 1, 900, 8) == pytest.approx(0.5)
    assert mod.blowout_penalty(table, 3, 100, 20) == 0.0  # overtime never flagged
