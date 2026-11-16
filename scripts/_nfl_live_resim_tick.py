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

import re
from collections import Counter
from typing import Any, Mapping

# The state `resim_live_game` used for EVERY tick before todo #813: no owner (so
# it marginalises: each side at its own 25), 1st and 10. Every fallback below
# returns exactly this, so an unreadable situation behaves as it always did.
_MARGINALISED = {"possession_owner": None, "down": 1, "distance": 10, "field_position": 25,
                 "yardline_frame": "absent"}

# "BAL 35", "LAR 4", "50" (midfield carries no side).
_SPOT_RE = re.compile(r"^\s*(?:([A-Za-z]{2,4})\s+)?(\d{1,2})\s*$")
# "1st & 10 at BAL 35", "3rd & Goal at KC 4", "2nd & 6 at 50".
_AT_RE = re.compile(r"\bat\s+(?:([A-Za-z]{2,4})\s+)?(\d{1,2})\s*$")


def _down_or_distance(value: Any, *, hi: int) -> int | None:
    """ESPN sends -1 for both between plays (kickoffs, tries, changes of
    possession) -- NCAAF measured 2 of 14 games on 2026-09-05. None means "not a
    snap state", which the caller treats as unknown rather than as 1st and 1."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 1 <= parsed <= hi else None


def _spot_from_text(situation: Mapping[str, Any]) -> tuple[str, int] | None:
    """(side abbreviation, yards) from ESPN's own words: `possessionText`
    ("BAL 35"), else the tail of `downDistanceText` ("... at BAL 35"). Side is
    "" at midfield."""
    match = _SPOT_RE.match(str(situation.get("possessionText") or ""))
    if match is None:
        match = _AT_RE.search(str(situation.get("downDistanceText") or ""))
    if match is None:
        return None
    side, yards = (match.group(1) or "").upper(), int(match.group(2))
    if not 1 <= yards <= 50:
        return None
    return side, yards


def _yardline_frame(situation: Mapping[str, Any], *, owner: str, field_position: int) -> str:
    """Which reading of `yardLine` agrees with the text-derived spot -- a
    DIAGNOSTIC, never an input. NCAAF measured `yardLine` from the HOME goal
    line (`ncaaf/live_resim.field_position_for_possessor`, 2026-09-05);
    `shared/game_shape` reads it as distance to the opponent's goal. Nobody has
    checked NFL's, so this records which one the feed actually uses."""
    try:
        yard_line = int(situation.get("yardLine"))
    except (TypeError, ValueError):
        return "absent"
    if not 0 <= yard_line <= 100:
        return "absent"
    home_frame = (yard_line if owner == "home" else 100 - yard_line) == field_position
    to_goal = (100 - yard_line) == field_position
    if home_frame and to_goal:
        return "both"
    return "home_frame" if home_frame else ("to_goal" if to_goal else "neither")


def drive_state_from_situation(row: Mapping[str, Any]) -> dict[str, Any]:
    """The drive in progress from one live `nfl_game_state_index` row.

    -> {possession_owner, down, distance, field_position, situation_basis,
    yardline_frame}. `field_position` is smartsim2's: yards from the POSSESSING
    team's own goal line (own 25 = 25, the opponent's 5 = 95).

    - the side: `situation.possession` is a team ID; it must equal the row's
      `home_team_id` or `away_team_id`, or it is unknown;
    - down / distance: must be a real snap state (1-4, 1-99); ESPN's -1 between
      plays (a kickoff names the KICKING team in possession) falls back, rather
      than handing the ball to the wrong side;
    - field position: from ESPN's text, matched to the two teams' abbreviations;
      a side that matches neither falls back.

    Any fallback is the pre-#813 marginalised state, named in `situation_basis`.
    """
    situation = row.get("situation")
    if not isinstance(situation, Mapping) or not situation:
        return dict(_MARGINALISED, situation_basis="no_situation")
    holder = str(situation.get("possession") or "").strip()
    if not holder:
        return dict(_MARGINALISED, situation_basis="no_possession")
    if holder == str(row.get("home_team_id") or "").strip():
        owner, mine, theirs = "home", row.get("home_abbr"), row.get("away_abbr")
    elif holder == str(row.get("away_team_id") or "").strip():
        owner, mine, theirs = "away", row.get("away_abbr"), row.get("home_abbr")
    else:
        return dict(_MARGINALISED, situation_basis="unknown_possessor_id")
    down = _down_or_distance(situation.get("down"), hi=4)
    distance = _down_or_distance(situation.get("distance"), hi=99)
    if down is None or distance is None:
        return dict(_MARGINALISED, situation_basis="between_plays")
    spot = _spot_from_text(situation)
    if spot is None:
        return dict(_MARGINALISED, situation_basis="no_spot_text")
    side, yards = spot
    mine, theirs = str(mine or "").strip().upper(), str(theirs or "").strip().upper()
    if yards == 50:
        field_position = 50
    elif side and side == mine:
        field_position = yards
    elif side and side == theirs:
        field_position = 100 - yards
    else:
        return dict(_MARGINALISED, situation_basis="spot_side_unmatched")
    return {
        "possession_owner": owner,
        "down": down,
        "distance": distance,
        "field_position": max(1, min(99, field_position)),
        "situation_basis": "text",
        "yardline_frame": _yardline_frame(situation, owner=owner, field_position=field_position),
    }


def situation_tally(live_index: Mapping[str, Mapping[str, Any]]) -> str:
    """One log line per tick: how many live games carried the drive in progress,
    why the rest did not, and which `yardLine` frame agreed with the text."""
    basis: Counter = Counter()
    frames: Counter = Counter()
    for row in (live_index or {}).values():
        if not isinstance(row, Mapping) or row.get("state") != "in":
            continue
        basis[str(row.get("situation_basis"))] += 1
        if row.get("situation_basis") == "text":
            frames[str(row.get("yardline_frame"))] += 1
    live = sum(basis.values())
    carried = basis.get("text", 0)
    return (f"live={live} carried={carried} marginalised={live - carried} "
            f"basis={dict(sorted(basis.items()))} yardline_frame={dict(sorted(frames.items()))}")


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
        possession_owner      inside raw `situation`      (see `drive_state_from_situation`)
        down / distance /     inside raw `situation`
        field_position

    Wired without this, EVERY game refuses: `game_not_in_progress` on the
    display text, then `incomplete_live_state`. The producer takes normalised
    rows precisely so that mismatch surfaces as a named refusal rather than a
    confident state assembled from defaults -- this is the translation it
    expects a caller to own.

    THE DRIVE IN PROGRESS IS NOW CARRIED (todo #813, 2026-11-16). Until then
    possession was left absent on purpose, so `resim_live_game` restarted every
    tick with a fresh 1st-and-10 at each side's own 25 (all 313 live rows of
    11-09..11-16 `possession_marginalised`). Measured on 65 replayed games,
    independent seeds: resumed at the end of Q3 with the TRUE drive state, Q4
    matches the game played through (-0.06 [-0.26, +0.15]); marginalised, it
    loses 1.47 [-1.65, -1.30] points. The old worry -- inverting the starting
    side from an unverified payload -- is why the side comes from ESPN's team
    ID and the spot from ESPN's own text, never from `yardLine`, whose frame two
    readers of this feed describe differently. Anything ambiguous falls back to
    the old marginalised state, by name (`situation_basis`).
    """
    if row.get("final"):
        state = "final"
    elif row.get("in_progress"):
        state = "in"
    else:
        state = "pre"
    drive = drive_state_from_situation(row) if state == "in" else dict(_MARGINALISED, situation_basis="not_live")
    return {
        "state": state,
        "away_score": row.get("away_pts"),
        "home_score": row.get("home_pts"),
        "period": row.get("period"),
        "clock_seconds": _clock_seconds(row),
        # None = unknown: the producer marginalises, exactly as before #813.
        "possession_owner": drive["possession_owner"],
        "down": drive["down"],
        "distance": drive["distance"],
        "field_position": drive["field_position"],
        # Diagnostics only (`situation_tally`); `live_state_from_row` ignores them.
        "situation_basis": drive["situation_basis"],
        "yardline_frame": drive["yardline_frame"],
        # CARRIED THROUGH FOR THE PROP CAPTURE, added 2026-09-27 after it cost a
        # live slate. `live_state_from_row` does not need this, so the adapter
        # dropped it -- and `nfl/live_resim._maybe_capture_prop_snapshot` reads
        # it to fetch the per-quarter player box. With the field absent the
        # capture returned silently on every game of every tick: zero CAPTURED
        # lines AND zero FAILED lines for 37 minutes with three games sitting
        # inside the capture window. An adapter that drops a field its consumer
        # needs looks exactly like a feature nobody enabled.
        "event_id": row.get("event_id"),
    }


# nflverse -> ESPN team abbreviations, for the ONE join where the two meet.
#
# MEASURED 2026-09-28T00:38Z. `nfl_game_state_index` keys its index
# `f"{away_abbr}@{home_abbr}"` using ESPN's abbreviations, while `live_key` is
# built from the PROJECTIONS, which are nflverse-style. For 30 of 32 teams the
# two agree and the join works, which is exactly why this went unnoticed: it
# fails only for the Rams and the Commanders.
#
# The cost was a whole slate. The per-quarter prop capture reported
# `PROP_CAPTURE_TICK no_period_or_clock=14 no_row=2` while the board showed one
# live game -- `LA_DEN`, Sunday night, a RAMS game. The single remaining
# capturable game of the night was the one team whose abbreviation does not
# join, so the capture could not fire and the slate's data is unrecoverable.
#
# The same mismatch was already found on a DIFFERENT join
# (`backtest_nfl_live_totals.ESPN_TO_RATINGS_ABBR`, ratings lookup) and fixed
# there in isolation. It is the same defect in two places, which is the argument
# for a named map rather than a fuzzy match: a fuzzy match would have silently
# joined something.
NFLVERSE_TO_ESPN_ABBR = {"LA": "LAR", "WAS": "WSH"}


def _espn_key(live_key: str) -> str:
    """`LA@DEN` -> `LAR@DEN`. Unchanged when neither side needs mapping."""
    away, sep, home = str(live_key or "").partition("@")
    if not sep:
        return live_key
    return (f"{NFLVERSE_TO_ESPN_ABBR.get(away, away)}@"
            f"{NFLVERSE_TO_ESPN_ABBR.get(home, home)}")


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
            raw = state_index.get(_espn_key(key))
        if raw is None:
            continue
        out[key] = normalise_live_row(raw)
    return out
