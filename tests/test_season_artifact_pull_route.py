"""A week-keyed artifact must have a route onto the machine that BUILDS the board.

Measured 2026-09-29. `nfl_prop_projections_2026_wk4.json` was published to web at
16:53Z and refresh-worker was still serving the wk3 file hours later. Three
mechanisms, each behaving correctly, combined into a file with no route:

  * `pull_hot_artifacts` scopes its request to `?pattern=*<date>*` -- its own
    docstring says non-dated files are out of scope -- and this file is keyed by
    SEASON+WEEK, so it can never match.
  * `pull_season_artifacts` exists for exactly this class, but its patterns were
    all MLB (`arsenal_`, `quality_`, `batted_ball_`, `pitch_splits_`,
    `conditional_mix_`) and its only callers are MLB-only.
  * the worker's daily autorun reported `SEASON_PROJECTION_ARTIFACT_MISSING`
    truthfully and could never fix it, because the play-by-play it needs to BUILD
    the artifact is not allowlisted and lives on developer machines only.

The board's fallback to wk3 was therefore correct given a disk that could not
have wk4. The defect was the missing route, not the fallback.
"""
from __future__ import annotations

import fnmatch
import inspect
from unittest.mock import patch

from syndicate.features.shared import artifact_publisher as ap


def test_the_week_keyed_prop_artifact_matches_a_season_pattern() -> None:
    assert [p for p in ap._SEASON_ARTIFACT_PATTERNS
            if fnmatch.fnmatch("nfl_prop_projections_2026_wk4.json", p)]


def test_the_pattern_is_SPORT_AGNOSTIC() -> None:
    """`[user, 2026-09-29: "ensure this is across ALL SPORTS"]` -- any sport that
    adopts the same `<sport>_prop_projections_<season>_wk<week>.json` naming is
    covered without another edit."""
    for name in ("ncaaf_prop_projections_2026_wk4.json",
                 "nba_prop_projections_2026_wk4.json",
                 "wnba_prop_projections_2026_wk4.json"):
        assert [p for p in ap._SEASON_ARTIFACT_PATTERNS if fnmatch.fnmatch(name, p)], name


def test_a_date_keyed_pull_could_never_have_matched_it() -> None:
    """The reason this fix exists, pinned: the hot sweep's own scoping cannot
    reach a week-keyed name, so adding the file to HOT_ARTIFACT_PATTERNS (which it
    already was) never gave it a route."""
    assert not fnmatch.fnmatch("nfl_prop_projections_2026_wk4.json", "*2026-09-29*")


def test_the_sweep_actually_calls_it() -> None:
    """REACHABILITY. A helper nothing calls is the same as no helper -- and that
    was precisely the prior state of `pull_season_artifacts` on refresh-worker."""
    assert "_pull_season_artifacts_if_due(" in inspect.getsource(ap.pull_hot_artifacts)


def test_it_is_throttled_because_the_sweep_ticks_every_30_seconds() -> None:
    """`pull_season_artifacts`'s own docstring says to call it before a roster
    build, NOT on a per-cycle schedule -- unfiltered pulls are what hit Render's
    proxy timeout and caused the date scoping in the first place."""
    ap._LAST_SEASON_PULL_EPOCH.clear()
    calls: list[int] = []
    with patch.object(ap, "pull_season_artifacts", side_effect=lambda **k: calls.append(1) or 7):
        first = ap._pull_season_artifacts_if_due()
        second = ap._pull_season_artifacts_if_due()
    assert first == 7 and second == 0
    assert len(calls) == 1, "the throttle let a second pull through inside the window"
    assert ap._SEASON_PULL_MIN_INTERVAL_SECONDS >= 600


def test_a_failing_pull_never_breaks_the_sweep_carrying_it() -> None:
    ap._LAST_SEASON_PULL_EPOCH.clear()
    with patch.object(ap, "pull_season_artifacts", side_effect=RuntimeError("web down")):
        assert ap._pull_season_artifacts_if_due() == 0


def test_the_mlb_patterns_are_untouched() -> None:
    """This lane added one pattern; it did not reorganise someone else's."""
    for p in ("*arsenal_*.json", "*quality_*.json", "*batted_ball_*.json",
              "*pitch_splits_*.json", "*conditional_mix_*.json"):
        assert p in ap._SEASON_ARTIFACT_PATTERNS, p
