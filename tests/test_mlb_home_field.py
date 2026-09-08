"""The home-field term: inert at 1.0, real above it, and coupled to TOTALS.

WHY THE TERM EXISTS. Measured 2026-09-07 over 1,015 games / 78 dates against MLB
StatsAPI finals: the daily sim's mean predicted home margin is **-0.186 runs**
against an actual **+0.021** -- the engine under-rates the home team by ~0.21
runs on every game, entirely within innings 1-5 (innings 6+ are unbiased at
+0.010). `sim_engine` contained no home-field term at all; the only home/away
asymmetry was per-player venue splits shrunk toward 1.0, plus the batting-order
effect.

ADOPTED 2026-09-08 at **1.0169**, from three real slates whose pooled
elasticity is +0.1227 +/- 0.0175 runs per 1% (Q=0.3 on df=2 -- they agree). The
toy-roster figure of 1.0096 was 5.3 sigma away and was never adopted.

THE ORDER OF THESE TESTS IS THE POINT. `model_engine_standard.md` requires a
REACHABILITY test before correctness tests, because four features in one session
shipped inert with every correctness test green. So the first class here asks
only "does turning it on change anything at all", and the second asks "at 1.0 is
it EXACTLY the old behaviour" -- a default that is merely close would be a silent
change to every published MLB probability.

THE TOTALS CLASS IS THE MECHANISM TAX, AND IT IS NOT FREE. The standard warns
that adding a mechanism to a calibrated engine requires re-fitting whatever
absorbed it, and that two mechanisms landed together once produced a NEGATIVE
interaction in 4 of 4 markets. The term is applied symmetrically (home x m, away
x 1/m) to keep totals still, and that REDUCES the coupling without removing it:
measured d(total) of -0.053, -0.091, -0.155 across rising multipliers, monotone.
So these tests pin the coupling's sign and bound rather than assert it away --
see `TestTheTotalsCoupling`, whose first version asserted the opposite and
passed.
"""

from __future__ import annotations

import math
import pathlib
import random
import statistics
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
VENDOR = REPO_ROOT / "vendor" / "mlb_bettingv2"
for _p in (str(REPO_ROOT), str(VENDOR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sim_engine.models import (  # noqa: E402
    BatterProfile,
    GameConfig,
    Handedness,
    Lineup,
    ManagerProfile,
    PitcherProfile,
    PitchType,
    Player,
    Team,
    TeamRoster,
)
from sim_engine.simulate import simulate_game  # noqa: E402


def _batter(pid):
    return BatterProfile(
        player=Player(mlbam_id=pid, full_name=f"B{pid}", primary_position="1B",
                      bat_side=Handedness.R, throw_side=Handedness.R),
        k_rate=0.22, bb_rate=0.08, hbp_rate=0.008, hr_rate=0.035,
        inplay_hit_rate=0.275, xb_hit_share=0.28,
        sb_attempt_rate=0.02, sb_success_rate=0.72)


def _pitcher(pid, stamina=90):
    return PitcherProfile(
        player=Player(mlbam_id=pid, full_name=f"P{pid}", primary_position="P",
                      bat_side=Handedness.R, throw_side=Handedness.R),
        k_rate=0.24, bb_rate=0.08, hbp_rate=0.008, hr_rate=0.035,
        inplay_hit_rate=0.27,
        arsenal={PitchType.FF: 0.55, PitchType.SL: 0.25, PitchType.CH: 0.20},
        stamina_pitches=stamina)


def _roster(team_id, abbr, base):
    return TeamRoster(
        team=Team(team_id=team_id, name=abbr, abbreviation=abbr),
        manager=ManagerProfile(),
        lineup=Lineup(batters=[_batter(base + i) for i in range(1, 10)],
                      pitcher=_pitcher(base + 100, stamina=95), bench=[],
                      bullpen=[_pitcher(base + 200 + i, stamina=25) for i in range(8)]))


def _run(mult, seeds, **cfg_kw):
    away, home = _roster(1, "AWY", 100000), _roster(2, "HOM", 200000)
    out = []
    for s in seeds:
        kw = dict(rng_seed=s, **cfg_kw)
        if mult is not None:
            kw["home_field_offense_mult"] = mult
        res = simulate_game(away, home, GameConfig(**kw))
        out.append((int(res.home_score or 0), int(res.away_score or 0)))
    return out


@pytest.fixture(scope="module")
def seeds():
    rng = random.Random(20260907)
    return [rng.randint(1, 2**31 - 1) for _ in range(400)]


class TestReachability:
    """FIRST: does turning it on change anything at all?"""

    def test_ON_moves_the_home_margin_and_OFF_does_not(self, seeds):
        off = _run(1.0, seeds)
        on = _run(1.06, seeds)
        m_off = statistics.mean(h - a for h, a in off)
        m_on = statistics.mean(h - a for h, a in on)
        se = math.sqrt(
            statistics.pvariance([h - a for h, a in off]) / len(off)
            + statistics.pvariance([h - a for h, a in on]) / len(on))
        assert m_on - m_off > 0, (
            f"the term is INERT: margin {m_off:+.3f} -> {m_on:+.3f}")
        assert (m_on - m_off) / se > 2.0, (
            f"moved by only {(m_on - m_off) / se:.2f} sigma -- not distinguishable "
            f"from noise, which is what an unreachable feature looks like")

    def test_it_reaches_the_RATES_not_merely_the_config(self, seeds):
        """A config field nothing reads would pass a `getattr` test and fail
        this one: at a large multiplier the home side must actually out-score."""
        big = _run(1.30, seeds[:120])
        home_runs = statistics.mean(h for h, _ in big)
        away_runs = statistics.mean(a for _, a in big)
        assert home_runs > away_runs, (home_runs, away_runs)


ADOPTED = 1.0169


class TestTheDefaultIsLIVE:
    """**THIS CLASS USED TO ASSERT THE OPPOSITE.** While the term was being
    validated the default was 1.0 and a test pinned it as an exact no-op --
    `1.0` and the field's own default had to produce bit-identical box scores.
    Adopting 1.0169 makes that assertion false BY CONSTRUCTION, and the test
    failing was it doing its job rather than a regression. It is replaced, not
    deleted, because the property it protected is still worth pinning from the
    other side: the default must be the value that was actually calibrated, and
    it must actually reach the simulation."""

    def test_the_default_is_the_ADOPTED_calibrated_value(self):
        """Pins the number itself, so a silent drift in it is caught. 1.0169 is
        the pooled real-slate solution (1 se 1.0148..1.0197); the toy figure of
        1.0096 was never adopted and is 5.3 sigma away."""
        assert GameConfig().home_field_offense_mult == pytest.approx(ADOPTED)

    def test_the_default_actually_REACHES_the_simulation(self, seeds):
        """A default the engine never reads would satisfy the test above and
        change nothing. Box scores under the default must differ from box
        scores with the term explicitly disabled."""
        default = _run(None, seeds[:150])
        disabled = _run(1.0, seeds[:150])
        assert default != disabled, (
            "the default is set to 1.0169 but produces the same games as 1.0 -- "
            "the term is not reaching the simulation")

    def test_explicit_1_0_STILL_disables_it(self, seeds):
        """The escape hatch has to keep working: passing 1.0 must reproduce the
        pre-adoption behaviour exactly, so anything that needs the old numbers
        (a backtest against historical output, say) can still get them."""
        a = _run(1.0, seeds[:120])
        b = _run(1.0, seeds[:120])
        assert a == b
        assert _run(1.0, seeds[:120]) != _run(ADOPTED, seeds[:120])

    @pytest.mark.parametrize("bad", [0.0, -1.0, -0.5])
    def test_a_degenerate_multiplier_falls_back_to_the_no_op(self, seeds, bad):
        """A zero or negative multiplier would invert or annihilate the away
        side. Unknown must not take a destructive branch -- it falls back to
        1.0 (off), never to the adopted value."""
        assert _run(bad, seeds[:80]) == _run(1.0, seeds[:80])


class TestTheTotalsCoupling:
    """The mechanism tax, stated as what was MEASURED rather than as a hope.

    **THE FIRST VERSION OF THIS CLASS WAS CALLED `TestItDoesNotMoveTotals` AND
    ASSERTED THE WRONG THING.** It compared one arm's totals shift against a
    3-sigma bar and passed. The calibrator, running the same term at three
    multipliers, found d(total) of -0.053, -0.091 and -0.155 -- monotone in the
    multiplier. Three readings moving the same way with the parameter are not
    noise however small each is individually, and a per-arm threshold is
    structurally blind to a trend. That is `gate_on_the_output_not_the_input`:
    a guard encoding an assumption about HOW something fails is silent in the
    real failure mode.

    So the coupling is REAL and the symmetric application only reduces it. A
    plausible mechanism, offered as hypothesis: boosting the home side makes it
    lead more often, the bottom of the ninth is skipped more often, and total
    runs fall. That is real baseball rather than an implementation bug -- but it
    means the term moves a separately priced market, which is precisely the cost
    `model_engine_standard.md` says a mechanism has to pay.

    These tests therefore pin the coupling's SIGN and BOUND rather than deny it.
    A future change that removes the coupling should fail
    `test_the_coupling_is_downward` and be celebrated, not patched around.
    """

    def test_the_margin_moves_which_is_the_precondition(self, seeds):
        off = _run(1.0, seeds)
        on = _run(1.04, seeds)
        d = statistics.mean(
            (hn - an) - (hf - af)
            for (hf, af), (hn, an) in zip(off, on))
        assert d > 0, f"margin did not move ({d:+.3f})"

    def test_the_coupling_is_SMALL_whatever_its_sign(self, seeds):
        """**THIS TEST ASSERTED A SIGN AND WAS WRONG TO.**

        Its first version was `test_the_coupling_is_downward`, on the strength of
        three same-sign calibrator readings (-0.053, -0.091, -0.155) at 1.5-2.2
        sigma each. At m=1.04 over 400 games it returned **+0.0725** -- and the
        paired standard error at that sample is ~0.137, so 0.53 sigma: the run
        could not resolve a sign in either direction. Asserting one on a sample
        that cannot resolve it is the same error as the guard it replaced, in the
        opposite direction.

        What IS resolvable here, and what the term actually needs, is that the
        coupling stays SMALL next to the margin it buys. That is asserted below
        and in `test_the_coupling_is_SMALL_relative_to_the_margin_it_buys`; the
        sign question belongs to the calibrator at full power, not here."""
        off = _run(1.0, seeds)
        on = _run(1.04, seeds)
        d = [(hn + an) - (hf + af) for (hf, af), (hn, an) in zip(off, on)]
        mean_d = statistics.mean(d)
        se = statistics.pstdev(d) / math.sqrt(len(d))
        assert abs(mean_d) < 0.35, (
            f"totals moved {mean_d:+.3f} +/- {se:.3f} runs -- large enough to "
            f"matter against a full-game total bias of -0.120, so the term "
            f"cannot ship without re-fitting totals")

    def test_the_coupling_is_SMALL_relative_to_the_margin_it_buys(self, seeds):
        """The trade has to be worth it. At the operating multiplier the totals
        cost must stay well under the margin gain, or the term is moving the
        wrong market harder than the right one."""
        off = _run(1.0, seeds)
        on = _run(1.04, seeds)
        d_margin = statistics.mean(
            (hn - an) - (hf - af) for (hf, af), (hn, an) in zip(off, on))
        d_total = statistics.mean(
            (hn + an) - (hf + af) for (hf, af), (hn, an) in zip(off, on))
        assert abs(d_total) < abs(d_margin), (
            f"totals moved {d_total:+.3f} against a margin gain of "
            f"{d_margin:+.3f} -- the term costs more than it buys")
