"""`backtest_soccer_h2h_calibration.py` must rate teams from the SAME source
`build_soccer_artifacts.py` uses in production, league for league.

Fixed 2026-08-19: the backtest previously used the goals-as-xG fallback for
every league, including the five with real Understat xG+ppda on disk, which
production reads directly for exactly those five
(`build_soccer_artifacts._GOALS_BASED_RATING_LEAGUES`). A backtest measuring
a different pipeline than production runs is not measuring production --
this guards against that drifting apart again silently."""
from __future__ import annotations

import glob
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_goals_based_league_set_matches_production():
    """The backtest's `_GOALS_BASED_RATING_LEAGUES` and production's must be
    the IDENTICAL set. If someone adds a league to one without the other,
    the backtest silently starts measuring the wrong pipeline again."""
    from scripts.backtest_soccer_h2h_calibration import _GOALS_BASED_RATING_LEAGUES as backtest_set
    from scripts.build_soccer_artifacts import _GOALS_BASED_RATING_LEAGUES as production_set

    assert backtest_set == production_set, (
        f"backtest set {backtest_set} != production set {production_set} -- "
        "the backtest would be rating at least one league from the wrong source"
    )


def test_understat_leagues_load_real_team_history_not_the_goals_fallback():
    """For a real Understat league, `_load_team_history` must return rows
    carrying `xg_for`/`xg_against`/`ppda` straight from `team_history/*.csv`
    -- not empty, and not goals standing in for xG."""
    from scripts.backtest_soccer_h2h_calibration import _load_team_history

    # epl is committed and NOT in the goals-based set -- a real Understat
    # league by construction of the set this test also checks above.
    rows = _load_team_history("epl")
    assert rows, "epl team_history/*.csv produced no rows -- check the committed files or the sparse-checkout scope"
    sample = rows[0]
    assert "xg_for" in sample and "xg_against" in sample, "team_history rows must carry real xG, not just goals"
    assert "ppda" in sample, "team_history rows must carry ppda -- the whole point of reading this file over the fallback"


def test_goals_based_leagues_still_use_the_fallback():
    """The four goals-based leagues have NO `team_history/` directory at all
    -- confirming they still correctly fall through to the goals-as-xG path,
    not silently broken by this branch existing."""
    for league in ("eredivisie", "primeira_liga", "championship", "belgian_pro_league"):
        matches = glob.glob(str(REPO_ROOT / "data" / "soccer_source" / league / "team_history" / "*.csv"))
        assert not matches, f"{league} unexpectedly has team_history/*.csv -- is it still goals-based?"
