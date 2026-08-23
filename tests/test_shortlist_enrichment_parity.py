"""`#523`. The shortlist must run the SAME enrichment chain as the artifact build.

WHY THIS EXISTS. Two code paths stamp a board row's `game.state`:

    syndicate/features/shared/book_grid_artifact.py   the artifact build
    pipeline/layer2_shortlist.py                      the shortlist build

The artifact path runs `attach_live_game_state_from_lens`; the shortlist path did
not. It is not a cosmetic difference: `live_gameline_join.attach_live_gamelines`
counts a row only AFTER `game.state in {live, in_progress}`, so a row whose state
was never corrected is not merely unpriced -- it is never seen.

MEASURED IN PRODUCTION 2026-08-22 23:58:21Z:

    LIVE_PROJECTION_JOIN sport=soccer considered=0 projected=0
                         lens_indexed=864 lens_live_games=6

Six live matches in the index and zero rows considered, while soccer `live_rows`
sat at 0 on the board across three readings and its quote age fell 32x. Fresh
prices were necessary and not sufficient.

MLB hid it for months. MLB's chips are StatsAPI-derived and already carry a live
status, so `attach_game_state` alone is enough and MLB's live tier demonstrably
worked -- 276 live rows on the same board. Soccer's chips come from
`_unsimulated_game`, which defaults `status_state` to `"pre"` for the nine of ten
leagues the sim does not cover, so only the correction ever makes them live.

THE COMMENT ABOVE THAT LOOP ALREADY DESCRIBED THIS BUG. It records two joins that
"ran only for the serve-time endpoint" and were added to the shortlist. A third
was left behind -- and it is the one the other two depend on, because both read
the state this one writes. A partial fix to a drift is how the drift survives.

So these tests compare the two chains as SETS and pin the one ordering constraint
that carries a reason, rather than asserting a hand-copied list that would rot the
same way.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SHORTLIST = REPO / "pipeline" / "layer2_shortlist.py"
ARTIFACT = REPO / "syndicate" / "features" / "shared" / "book_grid_artifact.py"

# Enrichment functions whose ABSENCE changes what the board shows. Deliberately
# not "every attach_* in the module": `attach_margin_model` is a shortlist-only
# fallback and the artifact path is entitled not to run it.
SHARED_ENRICHMENT = {
    "attach_game_state",
    "attach_live_game_state_from_lens",
    "attach_projections",
}


def _called_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def test_the_shortlist_calls_every_enrichment_the_artifact_build_calls():
    """THE REGRESSION. `attach_live_game_state_from_lens` was the one missing."""
    artifact_calls = _called_names(ARTIFACT) & SHARED_ENRICHMENT
    shortlist_calls = _called_names(SHORTLIST) & SHARED_ENRICHMENT
    missing = artifact_calls - shortlist_calls
    assert not missing, (
        "the shortlist board and the artifact board would disagree about "
        f"{sorted(missing)} -- a row's game.state decides whether the live joins "
        "ever see it, so a missing correction is a silently empty live tier"
    )


def test_both_paths_actually_call_the_live_state_correction():
    """Guards the guard: if BOTH paths lost the call, the set comparison above
    would pass on an empty difference and report nothing."""
    for path in (ARTIFACT, SHORTLIST):
        assert "attach_live_game_state_from_lens" in _called_names(path), path.name


@pytest.mark.parametrize("path", [ARTIFACT, SHORTLIST], ids=["artifact", "shortlist"])
def test_the_state_correction_runs_before_projections(path: pathlib.Path):
    """`#413`'s ordering rule, pinned on BOTH paths.

    `live_edge_policy` decides whether a row may carry an edge by reading
    `game.state`. Correcting the state after the projections have been stamped
    would leave a settled game's edges standing -- the correction has to land
    while it can still change an answer.
    """
    text = path.read_text(encoding="utf-8")
    # First CALL of each, not first mention: both names appear in comments.
    state_at = text.index("attach_live_game_state_from_lens(")
    proj_at = text.index("attach_projections(")
    assert state_at < proj_at, (
        f"{path.name} stamps projections before correcting game state; "
        "live_edge_policy reads the state the correction writes"
    )


def test_the_live_state_step_degrades_alone_when_absent():
    """It is imported in the OPTIONAL block, not the mandatory one.

    The mandatory block's own comment: naming a function there turns an
    ImportError into the loss of THIS SPORT'S ENTIRE ENRICHMENT, because they
    share a try. A missing live tier must cost the live tier and nothing else --
    and this function is newer than the two beside it, so it is exactly the one a
    rollback would remove.
    """
    text = SHORTLIST.read_text(encoding="utf-8")
    optional = text[text.index("try:\n                from syndicate.features.shared.board_enrichment import (") :]
    optional = optional[: optional.index("except ImportError:")]
    assert "attach_live_game_state_from_lens" in optional
    assert "attach_live_game_state_from_lens = None" in text, "no fallback binding"


def test_the_step_is_registered_in_the_enrichment_loop_not_just_imported():
    """An import nothing calls is the inert-feature shape: it would satisfy every
    test above that reads calls, and run on no row."""
    text = SHORTLIST.read_text(encoding="utf-8")
    assert re.search(r'\(\s*\n\s*"live_game_state",', text), (
        "not registered as a named step in the enrichment loop, so it would "
        "never run and never report a reason"
    )
