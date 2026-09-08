"""The NFL live re-sim tick, kept in its own module deliberately.

WHY NOT INLINE IN `run_refresh_worker.py` like NCAAF's. That file is already
6,500+ lines and its NCAAF tick is ~180 lines of sport-specific joins. The part
of this that is worth reviewing is the ADAPTER below, and burying it in the
worker is how it stops being read.

WHAT THIS DOES NOT DO: fetch play-by-play. `team_rating()` needs two
`load_pbp_plays()` calls -- measured 98 MB / 48,771 rows / 2.29 s per season --
and paying that on a tick cadence is `#241`, the hazard that restart-looped
production. Worse, a re-sim computing its OWN ratings could drift from the
pregame projection it exists to update, and neither the re-sim flag nor
`UNINFORMATIVE_BAND` would catch that: they gate the probability, not its
provenance. So the generator publishes the ratings it used and this reads them.
"""
from __future__ import annotations

from typing import Any, Mapping


def _clock_seconds(row: Mapping[str, Any]) -> int | None:
    """`"6:12"` -> 372. Returns None when the shape is not what we assume.

    NOT a best-effort parse that falls back to 0. A zero clock is a real game
    state -- end of quarter -- so guessing it from an unparseable string would
    hand the engine a confident, wrong situation. None makes the producer
    refuse by name instead.
    """
    raw = row.get("clock_seconds")
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(row.get("clock") or "").strip()
    if not text or ":" not in text:
        return None
    minutes, _, seconds = text.partition(":")
    try:
        return int(minutes) * 60 + int(float(seconds))
    except (TypeError, ValueError):
        return None


def normalise_live_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """`nfl_game_state_index` shape -> the shape `live_state_from_row` wants.

    THIS ADAPTER IS THE POINT OF THE MODULE, and it exists because the two
    shapes genuinely disagree -- checked field by field 2026-09-07, not assumed:

        producer wants        nfl_game_state_index emits
        --------------        --------------------------
        state in {live,in}    `status`  = "3rd Quarter"   (DISPLAY TEXT)
        away_score            `away_pts`
        home_score            `home_pts`
        clock_seconds         `clock`   = "6:12"          (DISPLAY STRING)
        period                `period`                     <- the only match
        possession_owner      inside raw `situation`

    Wired without this, EVERY game refuses: `game_not_in_progress` on the
    display text, then `incomplete_live_state`. The producer takes normalised
    rows precisely so that mismatch surfaces as a named refusal rather than a
    confident state assembled from defaults -- this is the translation it
    expects a caller to own.

    POSSESSION IS DELIBERATELY NOT DERIVED. ESPN's `situation` payload has never
    been checked against the shape this would need, and `resim_live_game`
    marginalises over both starting owners when it is absent
    (`possession_marginalised` in the output), costing roughly a possession of
    field position. Guessing it from an unverified payload could invert the
    sim's starting side, which is worth far more and would be invisible.
    """
    if row.get("final"):
        state = "final"
    elif row.get("in_progress"):
        state = "in"
    else:
        state = "pre"
    return {
        "state": state,
        "away_score": row.get("away_pts"),
        "home_score": row.get("home_pts"),
        "period": row.get("period"),
        "clock_seconds": _clock_seconds(row),
        # Absent on purpose -- see the docstring. The producer marginalises.
        "possession_owner": None,
    }


def build_live_index(
    state_index: Mapping[str, Mapping[str, Any]],
    games: Any,
) -> dict[str, dict[str, Any]]:
    """`{live_key: normalised_row}` for the games we are about to simulate.

    Keyed by the SAME `live_key` the caller put on each game, so a spelling
    divergence between the two sides shows up as `no_live_state` on a named
    game rather than as a silently empty index. NCAAF learned that the
    expensive way: its first snapshot indexed 8 games and joined ZERO, because
    the lens key came from the projections artifact and the board key from the
    odds source.
    """
    out: dict[str, dict[str, Any]] = {}
    for game in games or []:
        key = str(game.get("live_key") or "").strip()
        if not key:
            continue
        raw = state_index.get(key)
        if raw is None:
            continue
        out[key] = normalise_live_row(raw)
    return out
