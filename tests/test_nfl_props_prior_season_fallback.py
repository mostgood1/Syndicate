"""NFL props must survive week 1, when the current season has no plays yet.

WHY THIS FILE EXISTS. Measured on production 2026-09-08, the day before the
2026 season opener: `/nfl/api/props` served **0 cards** against a capture of
**5,929 real quotes** (519 players, 8 books, 16 matchups, 9 markets). Nothing
errored and nothing logged. The odds half was healthy the whole time --
production's own file through the real reader yields **2,442 odds rows** -- and
the model half was zero because it failed at the FIRST gate:

    player_name_index(2026):   0 names     <- no 2026 plays exist yet
    player_name_index(2025): 574 names

`player_name_index` is derived from `load_player_plays(season)`, so in week 1
`resolve_player_id` returns None for every player and the row loop hits
`continue`. `player_rate` fails the same way one line later: its window is
`row["week"] < week`, empty at week 1.

So NFL props were structurally dead EVERY week 1 and would have started working
in week 2 on their own -- the worst shape of defect, because it heals before
anyone finds it and returns a year later.

THE TEAM PATH HAD ALREADY SOLVED THIS and the player path had not:
`generate_smartsim2_nfl_projections.py:_team_rating` falls back to the whole
prior season and tags the result `prior_season_fallback`. Every 2026 week-1
GAME carries that tag today.

WHAT THIS FILE PINS, and the third is the one that would otherwise rot:
  1. the fallback resolves identity and rates when the current season is empty;
  2. the source travels with the row, so a prior-season projection can never be
     displayed as current form;
  3. the STRICT functions are untouched, because `backtest_nfl_props.py`,
     `fit_nfl_props_game_context.py` and `report_nfl_props_roi.py` call them and
     a fallback inside them would move what those runs measure.

Data-independent: every fixture is synthetic, so this runs in a worktree with
no `data/` and in CI.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import player_stats  # noqa: E402


@pytest.fixture
def two_seasons(monkeypatch):
    """2025 has a real game log; 2026 has nothing at all -- week 1."""
    prior_log = [
        {"week": w, "passing_yards": 250.0 + w, "anytime_td": 1.0 if w % 2 else 0.0}
        for w in range(1, 18)
    ]

    def fake_index(season: int):
        return {"p.mahomes": "00-0033873"} if int(season) == 2025 else {}

    def fake_log(season: int, player_id: str):
        return prior_log if int(season) == 2025 else []

    monkeypatch.setattr(player_stats, "player_name_index", fake_index)
    monkeypatch.setattr(player_stats, "player_game_log", fake_log)
    return prior_log


def test_week_one_resolves_the_player_through_the_prior_season(two_seasons):
    """The defect in one assertion: 2026 knows nobody, 2025 knows everybody."""
    assert player_stats.player_name_index(2026) == {}
    strict = player_stats.resolve_player_id(2026, "Patrick Mahomes")
    assert strict is None, "the strict resolver must stay strict -- backtests use it"

    pid, source = player_stats.resolve_player_id_with_prior(2026, "Patrick Mahomes")
    assert pid == "00-0033873"
    assert source == "prior_season_fallback"


def test_the_rate_falls_back_to_the_WHOLE_prior_season_not_a_slice(two_seasons):
    """The off-by-a-season trap: asking the prior season for `week < 1` returns
    an empty prior season too, which looks exactly like no fallback at all."""
    mean, stdev, n, source = player_stats.player_rate_with_prior(
        2026, 1, "00-0033873", "passing_yards"
    )
    assert source == "prior_season_fallback"
    assert n == 17, "the fallback must span the whole prior season, not week < 1"
    assert mean == pytest.approx(259.0)
    assert stdev is not None


def test_the_current_season_wins_once_it_can_answer(monkeypatch, two_seasons):
    """From week 3 or so this is the strict function plus a tag, and the
    fallback quietly stops being used as real form accumulates."""
    current = [{"week": w, "passing_yards": 300.0, "anytime_td": 0.0} for w in (1, 2)]
    monkeypatch.setattr(
        player_stats,
        "player_game_log",
        lambda season, pid: current if int(season) == 2026 else two_seasons,
    )
    mean, _stdev, n, source = player_stats.player_rate_with_prior(
        2026, 3, "00-0033873", "passing_yards"
    )
    assert source == "current_season_rolling"
    assert n == 2 and mean == pytest.approx(300.0)


def test_anytime_td_keeps_its_shrinkage_on_the_fallback_arm(two_seasons):
    """Routed through `anytime_td_rate` in BOTH arms on purpose. A full prior
    season is a large n so `#471`'s Gamma-Poisson shrinkage correctly does
    almost nothing -- but going around it would silently reintroduce the raw-MLE
    underestimate the shrinkage exists to fix."""
    mean, n, source = player_stats.anytime_td_rate_with_prior(2026, 1, "00-0033873")
    assert source == "prior_season_fallback"
    assert n == 17
    assert mean is not None and 0.0 < mean < 1.0


def test_an_unknown_player_stays_unresolved_rather_than_guessing(two_seasons):
    """An unresolvable name costs one bet; a wrongly resolved one prices a
    projection against a different human being. `player_name_index` records
    what that cost in practice -- a cornerback at +4000 carrying Tyreek Hill's
    game log, and a headline +125% ROI that was entirely a join artefact."""
    pid, source = player_stats.resolve_player_id_with_prior(2026, "Nobody At All")
    assert pid is None
    assert source == "unresolved"


def test_no_data_is_reported_as_no_data_not_as_a_zero(monkeypatch):
    """A silent zero is what made this defect invisible for a whole season."""
    monkeypatch.setattr(player_stats, "player_game_log", lambda season, pid: [])
    mean, stdev, n, source = player_stats.player_rate_with_prior(2026, 1, "X", "passing_yards")
    assert (mean, stdev, n, source) == (None, None, 0, "no_data")


def test_the_strict_functions_are_not_routed_through_the_fallback():
    """`backtest_nfl_props.py`, `fit_nfl_props_game_context.py` and
    `report_nfl_props_roi.py` call the strict functions. A fallback inside them
    would change what those runs measure -- a denominator moving for a reason
    unrelated to the thing being measured is how a model looks like it
    improved."""
    source = Path(player_stats.__file__).read_text(encoding="utf-8-sig")
    strict = source.index("def player_rate(")
    body = source[strict:source.index("\ndef ", strict + 10)]
    assert "prior_season_fallback" not in body, "the strict rate grew a fallback"

    strict_id = source.index("def resolve_player_id(")
    body_id = source[strict_id:source.index("\ndef ", strict_id + 10)]
    assert "season - 1" not in body_id, "the strict resolver grew a fallback"
