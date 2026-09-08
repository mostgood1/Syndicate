"""`estimate_live` publishes a FIRST-FIVE readout of the sims it already runs.

WHY THIS EXISTS. **An earlier version of this docstring claimed MLB's segment
lanes are EMPTY. That was wrong**, and the way it was wrong is the point: it
sampled the first three games in `/api/ops/live-lens/snapshot-index` and all
three were FINAL. `_build_game_lens` returns `[]` for a final game, so those
rows carried the card-derived lens, which has no `source` and no probability by
construction. The wrong population was measured and its absence reported as the
system's.

ON LIVE GAMES the lanes are populated (2026-09-07): gamePk 823902 read
`first5 0.3242, first7 0.2991`; 823175 read `first7 0.6511`. The `None`s are
monotone in segment length -- `_segment_projection`'s `closed` flag, correctly
refusing to project a segment whose innings are already played.

THE REAL DEFECT is what that probability IS. `_live_margin_win_prob` over
`_segment_projection` is a LINEAR INTERPOLATION OF PREGAME MEANS -- `mean *
innings/9`, less expected runs to date, plus actual runs -- reading no bases, no
outs, no pitcher. And it carries no `simsRun`, so `sqrt(p(1-p)/n)` has no `n`
and the publish-refuse-to-price gate has no interval to clear. That is why it
cannot price, and why the fix is a real Monte-Carlo readout carrying its own
trials rather than admitting the interpolation.

Either way the consequence is unchanged: every first5 market row on a live MLB
board is refused `segment_is_not_full_game` -- 25 of 29 and 34 of 41 rows
considered on the 2026-09-05/06 builds -- and the 49 mis-graded settled orders
were all first5.

THE LOAD-BEARING ASSUMPTION, pinned below. `simulate_game` indexes its
per-inning arrays by ABSOLUTE inning -- `inning_idx = state.inning - 1`
(`simulate.py`) -- and pads already-played innings with zeros. So on a mid-game
start `sum(inning_runs[:5])` is exactly the runs simulated in innings 1-5, and
`situation.<team>_score` is exactly everything before the start point. If that
alignment ever changed to "index 0 is the first SIMULATED inning", every first5
number would be silently mis-inninged and still look plausible -- which is what
`test_the_arrays_are_indexed_by_ABSOLUTE_inning` is here to catch.

The sim itself is stubbed. Building a real `TeamRoster` would test the vendored
engine, not the readout added here; stubbing pins exactly the arithmetic that is
new, with inning runs chosen so a mis-indexed sum gives a DIFFERENT answer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vendor.mlb_bettingv2.sim_engine import live_mc  # noqa: E402
from vendor.mlb_bettingv2.sim_engine.live_mc import FIRST5_INNINGS, estimate_live  # noqa: E402


class _Res:
    """The subset of `GameResult` the readout touches."""

    def __init__(self, away_innings, home_innings):
        self.away_inning_runs = list(away_innings)
        self.home_inning_runs = list(home_innings)
        self.away_score = sum(away_innings)
        self.home_score = sum(home_innings)
        self.batter_stats = {}
        self.pitcher_stats = {}


class _Situation:
    def __init__(self, inning, away_score=0, home_score=0):
        self.inning = inning
        self.away_score = away_score
        self.home_score = home_score


def _stub(monkeypatch, away_innings, home_innings):
    monkeypatch.setattr(live_mc, "_build_initial_state", lambda *a, **k: None)
    monkeypatch.setattr(live_mc, "simulate_game",
                        lambda *a, **k: _Res(away_innings, home_innings))


def _run(monkeypatch, *, inning, away_score=0, home_score=0,
         away_innings=(0, 0, 0, 0, 0), home_innings=(0, 0, 0, 0, 0), sims=10):
    _stub(monkeypatch, away_innings, home_innings)
    return estimate_live(None, None, _Situation(inning, away_score, home_score),
                         sims=sims, seed=1, track_player_stats=False)


class TestTheArithmetic:
    def test_the_arrays_are_indexed_by_ABSOLUTE_inning(self, monkeypatch):
        """The whole readout rests on this. Start at inning 4 with 3-2 on the
        board; the sim scores in innings 4 and 5 only (indices 3 and 4), with
        zeros padding 1-3. First five = base + simulated-through-5.

        The runs are placed so a mis-indexed read gives a different answer: if
        index 0 were the first SIMULATED inning, `[:5]` would also sweep up the
        inning-6 and inning-7 runs and the totals below would be wrong.
        """
        res = _run(monkeypatch, inning=4, away_score=3, home_score=2,
                   #        i1 i2 i3 i4 i5 | i6 i7  <- 6 and 7 must NOT be counted
                   away_innings=(0, 0, 0, 1, 0, 5, 5),
                   home_innings=(0, 0, 0, 0, 2, 9, 9))
        assert res.first5_available is True
        # away 3 + 1 = 4, home 2 + 2 = 4  -> tie, total 8, margin 0
        assert res.first5_avg_total_runs == pytest.approx(8.0)
        assert res.first5_tie_prob == pytest.approx(1.0)
        assert res.first5_home_win_prob == pytest.approx(0.0)
        assert res.first5_away_win_prob == pytest.approx(0.0)
        assert list(res.first5_margin_dist) == [0]

    def test_the_base_score_is_added_exactly_once(self, monkeypatch):
        res = _run(monkeypatch, inning=1, away_score=0, home_score=0,
                   away_innings=(2, 0, 0, 0, 0), home_innings=(0, 0, 0, 0, 1))
        assert res.first5_avg_total_runs == pytest.approx(3.0)
        assert res.first5_away_win_prob == pytest.approx(1.0)

    def test_innings_after_the_fifth_are_EXCLUDED(self, monkeypatch):
        res = _run(monkeypatch, inning=1,
                   away_innings=(1, 0, 0, 0, 0, 40, 40),
                   home_innings=(0, 0, 0, 0, 0, 40, 40))
        assert res.first5_avg_total_runs == pytest.approx(1.0), \
            "a late-inning run leaked into the first-five total"
        assert FIRST5_INNINGS == 5


class TestItRefusesOnceTheSegmentIsDecided:
    @pytest.mark.parametrize("inning", [6, 7, 9, 12])
    def test_past_the_fifth_every_field_is_None(self, monkeypatch, inning):
        """The sim holds no line score for innings 1-5 on a start at inning 6+:
        those slots are PADDED ZEROS, not the game. Reporting them would be
        reporting the padding as the result -- the same defect class as pricing
        a full-game projection against a first-inning market."""
        res = _run(monkeypatch, inning=inning, away_score=7, home_score=1,
                   away_innings=(0,) * (inning - 1) + (2,),
                   home_innings=(0,) * (inning - 1) + (1,))
        assert res.first5_available is False
        assert res.first5_home_win_prob is None
        assert res.first5_away_win_prob is None
        assert res.first5_tie_prob is None
        assert res.first5_avg_total_runs is None
        assert res.first5_total_runs_dist == {}
        assert res.first5_margin_dist == {}

    @pytest.mark.parametrize("inning", [1, 2, 3, 4, 5])
    def test_through_the_fifth_it_is_available(self, monkeypatch, inning):
        res = _run(monkeypatch, inning=inning)
        assert res.first5_available is True
        assert res.first5_home_win_prob is not None


class TestTiesAreNotFoldedHalfHalf:
    def test_the_three_probabilities_sum_to_one_and_the_tie_is_its_own(self, monkeypatch):
        """Five innings end level often, and a first-five market is commonly
        three-way or a push on the tie. The full-game path folds ties half/half;
        doing that here would bake a presentation convention into the sim and be
        wrong for BOTH market shapes."""
        res = _run(monkeypatch, inning=1,
                   away_innings=(1, 0, 0, 0, 0), home_innings=(1, 0, 0, 0, 0))
        assert res.first5_tie_prob == pytest.approx(1.0)
        assert res.first5_home_win_prob == pytest.approx(0.0)
        assert res.first5_away_win_prob == pytest.approx(0.0)
        total = (res.first5_home_win_prob + res.first5_away_win_prob
                 + res.first5_tie_prob)
        assert total == pytest.approx(1.0)

    def test_a_home_first_five_win_is_not_diluted_by_the_tie_bucket(self, monkeypatch):
        res = _run(monkeypatch, inning=1,
                   away_innings=(0, 0, 0, 0, 0), home_innings=(3, 0, 0, 0, 0))
        assert res.first5_home_win_prob == pytest.approx(1.0)
        assert res.first5_tie_prob == pytest.approx(0.0)


class TestItIsTheSameTrialsAsTheFullGame:
    def test_the_distributions_hold_exactly_sims_run_trials(self, monkeypatch):
        """This is what lets the SAME binomial `sqrt(p(1-p)/n)` error bar apply
        with no new assumption: first5 is a different readout of the identical
        Bernoulli trials, not a separate estimator."""
        res = _run(monkeypatch, inning=2, sims=37,
                   away_innings=(0, 1, 0, 0, 0), home_innings=(0, 0, 0, 0, 0))
        assert res.sims_run == 37
        assert sum(res.first5_total_runs_dist.values()) == 37
        assert sum(res.first5_margin_dist.values()) == 37
        # and the full-game readout is untouched by any of this
        assert sum(res.total_runs_dist.values()) == 37

    def test_the_full_game_numbers_are_UNCHANGED_by_the_addition(self, monkeypatch):
        """Regression guard: the full-game path is the one that works today."""
        res = _run(monkeypatch, inning=1,
                   away_innings=(0, 0, 0, 0, 0, 0, 0, 0, 1),
                   home_innings=(0, 0, 0, 0, 0, 0, 0, 0, 0))
        assert res.away_win_prob == pytest.approx(1.0)
        assert res.avg_total_runs == pytest.approx(1.0)
        # the ninth-inning run is in the full game and NOT in the first five
        assert res.first5_avg_total_runs == pytest.approx(0.0)
        assert res.first5_tie_prob == pytest.approx(1.0)
