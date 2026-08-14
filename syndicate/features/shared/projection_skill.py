"""Every projection declares whether its model has ever been evaluated.

`#425` gap 1. `skill_note` was called in **exactly one of seven** projection
builders -- only `nfl_game_projections`. `soccer_projections`,
`wnba_game_projections`, `wnba_projections`, `prop_projections`,
`live_projection_join` and `game_board_contract` had none, so a board row from
those six carried a number with no statement of whether the model behind it
predicts anything at all. A consumer could not distinguish "measured and good"
from "never measured", because both looked like a bare number.

WHAT THIS DOES AND DOES NOT DO -- read this before assuming the models are fine.

It does NOT measure the six models. It converts SILENT absence into DECLARED
absence: `status: "unmeasured"` is now a first-class value that says, on the
row, that nothing is known about this model's accuracy.

It does not measure them because the data is not available. Measured on the
repo checkout 2026-08-14: soccer results **0 files**, MLB `feed_live` **1
date**, WNBA processed game-cards **4 files**. CLAUDE.md's standing warning
covers exactly this -- a backtest built on those "will look like it ran on
months of data and actually be running on whatever the narrowest family
happens to cover". Emitting `correlation: 0.31` from n=4 would be `#377`'s own
failure (an authoritative-looking number that means nothing) committed by the
work written to prevent it. An honest `unmeasured` beats a dishonest number.

HOW TO ACTUALLY MEASURE ONE, when someone has the data. NFL's numbers came from
`scripts/backtest_nfl_preseason_projection.py`: regenerate historical
projections in memory from the era's own inputs, join to real final scores, and
report correlation and MAE **against a constant baseline** -- the baseline is
what makes the number meaningful, since NFL's totals model at r=0.269 is
"barely better than predicting the historical mean". That harness is
NFL-specific by construction (it imports `shrunk_rating`, `team_rating`,
`load_pbp_plays`), so each sport needs its own. Write the result into a
constant like `nfl_preseason_calibration.MEASURED_SKILL` and have the producer
attach it itself; this module then stands aside automatically.

PAYLOAD DISCIPLINE. This block lands on EVERY projection row on EVERY sport.
`#374` records `gameMarkets.extraHitterProps` reaching 68% of the MLB live-lens
payload at 117 keys per record. So the unmeasured note is four small keys and
no prose -- the explanation lives in this docstring, not in two thousand rows.
"""

from __future__ import annotations

from typing import Any

STATUS_MEASURED = "measured"
STATUS_UNMEASURED = "unmeasured"

# Deliberately terse. See PAYLOAD DISCIPLINE above -- this repeats per row.
_UNMEASURED_VERDICT = "model never backtested -- projection is unvalidated"


def unmeasured_note() -> dict[str, Any]:
    """The declared-absence block.

    `correlation: None` and `sample_games: 0` rather than omitting the keys, so
    a consumer reading `model_skill["correlation"]` gets an explicit null
    instead of a KeyError, and so measured and unmeasured blocks share one
    shape. A caller must never have to branch on which producer wrote it.
    """
    return {
        "status": STATUS_UNMEASURED,
        "correlation": None,
        "sample_games": 0,
        "verdict": _UNMEASURED_VERDICT,
    }


def normalize_existing_note(note: dict[str, Any]) -> dict[str, Any]:
    """Stamp `status: "measured"` onto a producer's own skill note.

    NFL's `skill_note` predates this module and carries richer, profile-aware
    content (`sample_games`, `seasons`, `correlation`, `verdict`). It is NOT
    rewritten -- only the discriminating key is added, so both shapes answer
    `model_skill["status"]` and nothing that was measured gets reworded by code
    that did not measure it.
    """
    if note.get("status"):
        return note
    note["status"] = STATUS_MEASURED
    return note


def attach_projection_skill(grid: list, *, sport: str) -> dict[str, Any]:
    """Ensure every projection on the grid carries a `model_skill` block.

    Applied at the `attach_projections` wrapper -- the same choke point the
    degeneracy detector uses -- so it covers all seven sports, all 13 per-sport
    return sites, and any producer wired later, touching zero call sites
    (`#334`'s lesson).

    A producer that measured its own model keeps its note; this only fills the
    gap. Returns coverage counts so "every model on this board is unmeasured"
    is a number someone can read, rather than something they would have to
    notice.
    """
    measured = 0
    unmeasured = 0
    for row in grid:
        if not isinstance(row, dict):
            continue
        projection = row.get("projection")
        if not isinstance(projection, dict):
            continue
        existing = projection.get("model_skill")
        if isinstance(existing, dict) and existing:
            projection["model_skill"] = normalize_existing_note(existing)
            measured += 1
            continue
        projection["model_skill"] = unmeasured_note()
        unmeasured += 1

    if not (measured or unmeasured):
        return {}
    return {
        "rows_with_measured_skill": measured,
        "rows_with_unmeasured_skill": unmeasured,
    }
