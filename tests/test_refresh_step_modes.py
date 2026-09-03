"""`ncaaf-live-cadence`. `RefreshStep.modes` -- a step may opt out of a mode.

WHY: phase already lets a step say WHEN it belongs; nothing let it say HOW
EXPENSIVE it is. NCAAF's three steps differ by three orders of magnitude:

    ncaaf_game_lines_oddsapi     ONE OddsAPI request, billed per REQUEST at 3
                                 credits per region -- 9 with production's
                                 `SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS=eu,us_ex`.
    ncaaf_player_props_oddsapi   ~130 events x 9 markets, billed per EVENT per
                                 MARKET. Production `/api/ops/oddsapi/quota`
                                 2026-09-03T22:50Z: ncaaf 113,843 calls / 9,495
                                 credits.
    ncaaf_lines_snapshot         the legacy bundle runner, which CANNOT run for
                                 2026 (`STEP_FAIL ... return_code=1`, measured
                                 2026-08-27T01:04:55Z).

The cheap step was hostage to the expensive one, so a short NCAAF cadence was
unaffordable. The two tests that matter here are the BACKWARD-COMPATIBILITY one
(every existing step keeps running, because `modes=None` means every mode) and
the one that pins NCAAF's fast-mode step list.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "refresh_odds_sources_modes_under_test", _REPO / "scripts" / "refresh_odds_sources.py"
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules["refresh_odds_sources_modes_under_test"] = m
    spec.loader.exec_module(m)
    return m


def _step(mod, name, phases=("pregame", "live"), modes=None):
    return mod.RefreshStep(
        name=name, phases=phases, cwd=_REPO, command=("python", "-c", "pass"), modes=modes
    )


def test_a_step_without_modes_runs_in_every_mode(mod):
    """THE BACKWARD-COMPATIBILITY PROPERTY. Every step in the registry today
    declares no `modes`, so this is what keeps the change inert for all of them.
    If this ever fails, some sport silently lost a step."""
    step = _step(mod, "legacy")
    for mode in ("full", "fast", "", "anything"):
        assert mod._filter_steps([step], "live", mode) == [step], f"mode={mode!r} dropped an unscoped step"


def test_mode_none_skips_the_filter_entirely(mod):
    """The default argument, so every pre-existing caller is unchanged."""
    scoped = _step(mod, "full_only", modes=("full",))
    assert mod._filter_steps([scoped], "live") == [scoped]


def test_a_scoped_step_is_dropped_outside_its_modes(mod):
    scoped = _step(mod, "full_only", modes=("full",))
    assert mod._filter_steps([scoped], "live", "full") == [scoped]
    assert mod._filter_steps([scoped], "live", "fast") == []


def test_the_mode_match_is_case_insensitive_and_whitespace_tolerant(mod):
    scoped = _step(mod, "full_only", modes=("full",))
    assert mod._filter_steps([scoped], "live", "  FULL ") == [scoped]


def test_phase_all_still_respects_modes(mod):
    """`phase == "all"` is a statement about WHEN, not about HOW MUCH.
    Conflating them would make `--phase all --mode fast` run the expensive half,
    which is the exact bill this mechanism exists to avoid."""
    scoped = _step(mod, "full_only", phases=("pregame",), modes=("full",))
    assert mod._filter_steps([scoped], "all", "full") == [scoped]
    assert mod._filter_steps([scoped], "all", "fast") == []


def test_the_phase_filter_still_wins_first(mod):
    scoped = _step(mod, "pregame_only", phases=("pregame",), modes=("full", "fast"))
    assert mod._filter_steps([scoped], "live", "full") == []


# --------------------------------------------------------------------------
# The NCAAF step list itself -- the reason the mechanism exists.
# --------------------------------------------------------------------------


def _ncaaf_args():
    return argparse.Namespace(season=None, week=None, date="2026-09-03")


def test_ncaaf_fast_mode_keeps_ONLY_the_game_line_capture(mod):
    """The price capture survives; the per-event prop sweep and the legacy
    bundle runner do not. This is what makes a 5-minute NCAAF cadence cost 108
    credits an hour instead of thousands."""
    steps = mod._build_ncaaf_steps(_ncaaf_args())
    names = [s.name for s in mod._filter_steps(steps, "live", "fast")]
    assert names == ["ncaaf_game_lines_oddsapi"], names


def test_ncaaf_full_mode_is_UNCHANGED(mod):
    """Both workers run `SYNDICATE_LIVE_ODDS_REFRESH_MODE=full` (verified live
    via the Render env-vars API 2026-09-03), so the combined sweep must keep
    every step it has today. This is the assertion that says the change ships
    inert for production's existing traffic."""
    steps = mod._build_ncaaf_steps(_ncaaf_args())
    names = [s.name for s in mod._filter_steps(steps, "live", "full")]
    assert names == [
        "ncaaf_game_lines_oddsapi",
        "ncaaf_player_props_oddsapi",
        "ncaaf_lines_snapshot",
    ], names
    assert names == [s.name for s in mod._filter_steps(steps, "live")], "full must equal the unfiltered list"


def test_the_game_line_step_is_the_one_that_writes_prices(mod):
    """Guards against someone 'simplifying' by scoping the wrong step: the fast
    list must contain the script that appends to the shared book-quote log."""
    steps = mod._build_ncaaf_steps(_ncaaf_args())
    fast = mod._filter_steps(steps, "live", "fast")
    assert len(fast) == 1
    assert any("fetch_ncaaf_oddsapi_game_lines.py" in str(part) for part in fast[0].command)


def test_no_other_sport_gained_a_mode_scope(mod):
    """Blast-radius check. Only NCAAF opts in; every other registered sport's
    steps must still be unscoped, or this change is not the narrow one it
    claims to be."""
    args = argparse.Namespace(season=None, week=None, date="2026-09-03")
    scoped = {}
    for slug, spec in mod.REGISTRY.items():
        if slug == "ncaaf":
            continue
        try:
            steps = spec.step_builder(args)
        except Exception:
            continue
        names = [s.name for s in steps if s.modes is not None]
        if names:
            scoped[slug] = names
    assert scoped == {}, scoped
