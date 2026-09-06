"""NFL team ratings must be denominated in POINTS PER GAME, not per play.

WHY THIS FILE EXISTS. Measured 2026-09-06 on the shipped artifacts: NFL's
across-game `margin_mean` stdev was **2.16 points** against NCAAF's **15.37**,
and **93.8%** of NFL games landed at P(home) 0.35..0.65. A model that puts every
matchup within a couple of points of even is not miscalibrated -- it is not
discriminating at all.

The cause was `team_rating` returning `_mean_epa(...)`: expected points added PER
PLAY, raw, uncentred and unscaled. NCAAF returns
`(sp_rating - league_mean) / SP_RATING_SCALE` -- points per game, centred,
divided by 10. EPA/play has stdev 0.0918 across teams; the same data at game
level has stdev 5.47 POINTS. NFL was feeding the engine ~1/60th of the spread.

THESE TESTS USE SYNTHETIC PLAYS, DELIBERATELY. A season's pbp is ~100 MB and the
properties under test -- units, centring, sign, and the gate -- are all
structural. A fixture that needs the real file would make this suite depend on a
`data/` tree the worktrees do not carry.
"""

from __future__ import annotations

import pytest

import scripts.generate_smartsim2_nfl_projections as G


def _plays():
    """Two weeks, three teams, deliberately lopsided.

    AAA is a strong offence (+2.0 EPA/play), CCC a weak one (-2.0), BBB neutral.
    Each team plays 5 offensive plays per week, so per-GAME EPA is 10x per-PLAY
    EPA -- which is what makes the units difference visible in the assertions
    rather than merely asserted in a comment.
    """
    rows = []
    for week in (1, 2):
        for _ in range(5):
            rows.append((week, "AAA", "BBB", "pass", 2.0))
            rows.append((week, "BBB", "CCC", "pass", 0.0))
            rows.append((week, "CCC", "AAA", "pass", -2.0))
    return rows


def test_the_gate_is_OFF_by_default_and_preserves_the_old_values(monkeypatch):
    """`absent != off` is a documented trap here, so the default is asserted.

    A units change to a money model must not arrive because someone forgot to
    set a variable.
    """
    monkeypatch.delenv("SYNDICATE_NFL_PPG_RATINGS", raising=False)
    off, dfn, src = G.team_rating("AAA", week=None, current_plays=_plays(), prior_plays=None)
    # Old path: the raw per-play mean, uncentred. AAA gains 2.0 per play.
    assert off == pytest.approx(2.0)
    assert src == "current_season_rolling"


def test_enabling_it_changes_the_rating_off_is_not_on(monkeypatch):
    """REACHABILITY before correctness. A gated change that computes the same
    number either way has shipped inert with a green suite vouching for it."""
    plays = _plays()
    monkeypatch.delenv("SYNDICATE_NFL_PPG_RATINGS", raising=False)
    before = G.team_rating("AAA", week=None, current_plays=plays, prior_plays=None)[:2]
    monkeypatch.setenv("SYNDICATE_NFL_PPG_RATINGS", "1")
    after = G.team_rating("AAA", week=None, current_plays=plays, prior_plays=None)[:2]
    assert before != after


def test_the_rating_is_CENTRED_on_the_league(monkeypatch):
    """The engine treats 0.0 as an AVERAGE team (`0.5 + rating`), so an
    uncentred rating shifts every team the same way -- the bias already recorded
    as "the NFL payload's league-mean offense_index at 0.405 against a neutral
    0.500". With a symmetric fixture the three offences must sum to ~0."""
    monkeypatch.setenv("SYNDICATE_NFL_PPG_RATINGS", "1")
    plays = _plays()
    offs = [G.team_rating(t, week=None, current_plays=plays, prior_plays=None)[0]
            for t in ("AAA", "BBB", "CCC")]
    assert sum(offs) == pytest.approx(0.0, abs=1e-9)
    assert offs[0] > offs[1] > offs[2], "ordering must survive centring"


def test_it_is_PER_GAME_not_per_play(monkeypatch):
    """The whole defect in one assertion.

    AAA gains 2.0 EPA on each of 5 plays per game = 10.0 points per game. Its
    centred, scaled rating must reflect the GAME total, not the play mean --
    otherwise the engine sees 1/5th of the real separation here (and ~1/60th on
    a real slate, where teams run ~60 plays a game).
    """
    monkeypatch.setenv("SYNDICATE_NFL_PPG_RATINGS", "1")
    off, _dfn, _src = G.team_rating("AAA", week=None, current_plays=_plays(), prior_plays=None)
    # league mean per game = (10.0 + 0.0 - 10.0)/3 = 0.0, so AAA is +10.0/scale.
    assert off == pytest.approx(10.0 / G.NFL_RATING_SCALE)


def test_the_defence_sign_is_NEGATED(monkeypatch):
    """The raw figure is points ALLOWED per game; the engine's `defense_rating`
    means "how good this defence is".

    Getting this backwards rates the best defence as the worst, and no amount of
    scaling would reveal it -- the spread would look perfectly healthy. AAA's
    defence concedes -2.0 per play (i.e. it is excellent), so its rating must be
    POSITIVE.
    """
    monkeypatch.setenv("SYNDICATE_NFL_PPG_RATINGS", "1")
    plays = _plays()
    aaa_def = G.team_rating("AAA", week=None, current_plays=plays, prior_plays=None)[1]
    bbb_def = G.team_rating("BBB", week=None, current_plays=plays, prior_plays=None)[1]
    assert aaa_def > 0 > bbb_def


def test_games_are_counted_as_distinct_weeks_not_assumed(monkeypatch):
    """A bye, a short season or a mid-week call must size itself.

    Dividing by an assumed 17 games would understate every team in an
    interrupted season and silently flatten the ratings again -- the same class
    of defect this change fixes.
    """
    monkeypatch.setenv("SYNDICATE_NFL_PPG_RATINGS", "1")
    one_week = [r for r in _plays() if r[0] == 1]
    off_one = G.team_rating("AAA", week=None, current_plays=one_week, prior_plays=None)[0]
    off_two = G.team_rating("AAA", week=None, current_plays=_plays(), prior_plays=None)[0]
    # Same per-game rate in both, so the rating must be identical.
    assert off_one == pytest.approx(off_two)


def test_a_team_with_no_plays_still_falls_back_and_is_NAMED(monkeypatch):
    """The neutral branch must survive the rewrite, and keep saying so.

    `neutral_no_data` is what distinguishes "this team has no data" from "this
    team is exactly average" -- and that distinction is how the falsification
    test for the original diagnosis was run at all.
    """
    monkeypatch.setenv("SYNDICATE_NFL_PPG_RATINGS", "1")
    off, dfn, src = G.team_rating("ZZZ", week=None, current_plays=_plays(), prior_plays=None)
    assert (off, dfn, src) == (0.0, 0.0, "neutral_no_data")
