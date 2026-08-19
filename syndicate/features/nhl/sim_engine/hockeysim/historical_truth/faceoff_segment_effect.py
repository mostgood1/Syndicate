"""Segment-level (not season-aggregate) validation of the faceoff-driven shot-share mechanism.

WHY THIS EXISTS. `hockeysim_faceoff_nz_calibration_report.md` measured Pearson correlation between
each per-team faceoff-zone index and real SEASON-AGGREGATE `shots_per_60` -- every correlation was
under 0.02, indistinguishable from zero. That result could not distinguish "faceoffs have no real
effect on shot generation" from "a real, LOCAL effect exists but washes out completely across a
season's worth of everything else that happens in the other ~58 minutes per game" -- the season
aggregate is simply the wrong timescale to see a segment-level effect, if one exists.

`_faceoff_multipliers` (`engine.py`) claims the LATTER kind of effect: winning a specific draw
shifts shot generation in the seconds immediately following THAT draw, within THAT segment. This
module checks that claim directly, on its own timescale: for every real EVEN-STRENGTH faceoff in
the `playbyplay` cache, count real shot-on-goal/goal events by the WINNING team vs the LOSING team
in a short window immediately after the draw (truncated at the next faceoff or period end, so no
shot is ever double-counted across two overlapping windows) -- a genuine post-faceoff shot
differential, the same kind of study public NHL analytics has used to investigate this question.

WHY A FIXED WINDOW, TRUNCATED AT THE NEXT STOPPAGE-CAUSING EVENT. A real shift following a faceoff
win typically runs 10-30 seconds before a whistle or change; a window in that range is standard for
this kind of study. Truncating at the next faceoff (rather than always using the full fixed window)
prevents a shot that happens well into the NEXT possession sequence from being credited to the
PREVIOUS draw just because it falls within a fixed time span -- this module only ever attributes a
shot to the most recent preceding faceoff.

SHOTS = shot-on-goal + goal, matching the "shots" event kind `engine.py`'s own simulation emits
(SOG-equivalent, not full Fenwick/Corsi attempts) -- the same basis this session's other real-data
checks against the engine's own output have used throughout.

STRENGTH-STATE (PP/PK) FACEOFFS, added in a later pass. `engine.py`'s entire faceoff mechanism --
EV, OZ, DZ, NZ alike -- is gated `faceoff_ev_only=True`, so NONE of it has ever applied during a
power-play/penalty-kill segment; PP/PK shot generation is driven only by `pp_shots_mult`/
`pk_shots_mult` (truth-calibrated, §2e), with no faceoff-driven modifier layered on top the way EV
segments get one. `compute_post_faceoff_shots_by_strength_role` checks whether winning a draw taken
DURING a power play or penalty kill has its own measurable post-draw shot effect, the same
methodology as every zone-specific check, applied to a population the EV-only extraction path
(`_extract_timed_events`'s default) deliberately excludes entirely. `winner_role="PP"` isolates
draws where the WINNER had the skater advantage (a team already on the man advantage also winning
the draw); `winner_role="PK"` isolates draws where the WINNER was shorthanded (the team killing a
penalty winning the draw, e.g. to clear the zone).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

_SHOT_TYPES = ("shot-on-goal", "goal")
_STOPPING_TYPES = ("faceoff",)  # the next event that ends a window's attribution


def _skaters_from_situation_code(code: object) -> Optional[tuple]:
    text = str(code or "").strip()
    if len(text) != 4 or not text.isdigit():
        return None
    return int(text[1]), int(text[2])


def _seconds_in_period(time_in_period: object) -> Optional[float]:
    """`"MM:SS"` elapsed-in-period -> seconds, or `None` if malformed."""
    text = str(time_in_period or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        return None
    try:
        minutes, seconds = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    return float(minutes * 60 + seconds)


@dataclass(frozen=True)
class _TimedEvent:
    period: int
    seconds: float
    team_id: Optional[int]
    is_faceoff: bool
    is_shot: bool
    zone: Optional[str] = None  # faceoff events only -- the WINNER's own zone ("O"/"N"/"D")
    role: Optional[str] = None  # faceoff events only, non-EV: "PP" or "PK" -- the WINNER's own
    # skater-count role at the draw. `None` for EV faceoffs and for all shots.


def _extract_timed_events(payload: Dict, *, include_non_ev: bool = False) -> List[_TimedEvent]:
    """Faceoffs and shots, in period+time order (the cache's own `plays` order is already
    chronological, so no re-sort is needed -- confirmed by `sortOrder` being monotonic within a
    period in every cached game spot-checked).

    `include_non_ev=False` (the default, EVERY pre-existing caller) reproduces the exact original
    EV-ONLY behavior byte-for-byte -- non-EV (PP/PK-strength) events are excluded entirely, same as
    before this parameter existed. `include_non_ev=True` additionally includes PP/PK-strength
    faceoffs and shots, tagging each faceoff's `role` as `"PP"` (winner had the skater advantage) or
    `"PK"` (winner was shorthanded) -- used by `compute_post_faceoff_shots_by_strength_role`."""
    out: List[_TimedEvent] = []
    for play in payload.get("plays") or []:
        if not isinstance(play, dict):
            continue
        kind = play.get("typeDescKey")
        is_faceoff = kind == "faceoff"
        is_shot = kind in _SHOT_TYPES
        if not is_faceoff and not is_shot:
            continue
        skaters = _skaters_from_situation_code(play.get("situationCode"))
        if skaters is None:
            continue
        is_ev = skaters[0] == skaters[1]
        if not is_ev and not include_non_ev:
            continue  # not even strength -- excluded from both faceoff and shot streams
        period_desc = play.get("periodDescriptor") or {}
        try:
            period = int(period_desc.get("number"))
        except (TypeError, ValueError):
            continue
        seconds = _seconds_in_period(play.get("timeInPeriod"))
        if seconds is None:
            continue
        details = play.get("details") or {}
        team_id = details.get("eventOwnerTeamId")  # winning team for a faceoff, shooting team for a shot
        # `zoneCode` is relative to the WINNER (`faceoff_ev_index.py`'s §2n docstring: confirmed
        # empirically -- two draws at identical rink coordinates showed opposite zone labels
        # depending who won). Only meaningful for faceoff events; `None` for shots.
        zone = str(details.get("zoneCode")).strip().upper() if (is_faceoff and details.get("zoneCode")) else None
        role: Optional[str] = None
        if is_faceoff and not is_ev and team_id is not None:
            # `situationCode`: [awayGoalieInNet][awaySkaters][homeSkaters][homeGoalieInNet].
            # `_skaters_from_situation_code` returns (away_skaters, home_skaters). Determine which
            # side had the skater advantage, purely from the CODE (not team identity), then check
            # whether the WINNER's team_id matches the home or away side to resolve the winner's
            # own role -- avoids needing home/away team ids threaded into this pure function.
            away_sk, home_sk = skaters
            home_has_advantage = home_sk > away_sk
            home_team_id = (payload.get("homeTeam") or {}).get("id")
            if home_team_id is not None:
                winner_is_home = team_id == home_team_id
                winner_has_advantage = (home_has_advantage and winner_is_home) or (
                    (not home_has_advantage) and (not winner_is_home))
                role = "PP" if winner_has_advantage else "PK"
        out.append(_TimedEvent(period=period, seconds=seconds, team_id=team_id,
                                is_faceoff=is_faceoff, is_shot=is_shot, zone=zone, role=role))
    return out


@dataclass(frozen=True)
class GamePostFaceoffShots:
    """One finished game's post-faceoff shot counts: for every EV faceoff, shots by the WINNING
    team and by the OTHER team within `window_seconds` after the draw, truncated at whichever
    comes first: the next faceoff, the period ending, or the window itself."""

    game_id: str
    n_faceoffs: int
    winner_shots: int
    other_shots: int
    window_seconds_total: float  # sum of each window's ACTUAL length (post-truncation)


_PERIOD_LENGTH_SECONDS = 1200.0  # 20-minute regulation period; a conservative cap for OT too,
# since OT periods (300s/1200s depending on season/situation) are always shorter than this --
# the cap only ever matters for a draw taken in the final `window_seconds` of a period.


def compute_post_faceoff_shots(
    payload: Dict, *, window_seconds: float = 15.0, winner_zone: Optional[str] = None,
) -> Optional[GamePostFaceoffShots]:
    """Parse one `playbyplay` payload. Returns `None` if the payload carries no `plays` list at
    all (never raises); a game with zero EV faceoffs (or zero matching `winner_zone`, if given)
    returns a record with `n_faceoffs==0` rather than `None`, so the caller's own aggregate
    decides whether to trust it.

    For each EV faceoff, the window is bounded by whichever comes first: the fixed
    `window_seconds`, the NEXT EV faceoff in the same period (so a shot is never attributed to
    more than one draw), or the period's own end -- two small scans per draw (find the boundary,
    then count shots up to it), not a single mutating pass, so the truncation logic stays simple
    and independently checkable.

    `winner_zone`, when given (`"O"`/`"N"`/`"D"`), restricts to draws where the WINNER's OWN zone
    matches -- e.g. `"D"` isolates draws a team won in their own defensive zone, the population
    `hockeysim_faceoff_dz_segment_validation_report.md` needs to test the DZ mechanism's dual
    offense/defense claim directly, the same way the unfiltered (default) population already
    tested the EV/OZ claim. The NEXT-faceoff truncation boundary is always the next EV faceoff
    REGARDLESS of its own zone (truncation is about not double-counting a shot across two windows,
    not about which draws are being studied) -- only which draws COUNT as a studied event is
    zone-filtered, never which events can end one.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("plays"), list):
        return None
    events = _extract_timed_events(payload)
    zone_filter = str(winner_zone).strip().upper() if winner_zone else None

    n_faceoffs = winner_shots = other_shots = 0
    window_total = 0.0
    for i, ev in enumerate(events):
        if not ev.is_faceoff or ev.team_id is None:
            continue
        if zone_filter is not None and ev.zone != zone_filter:
            continue
        n_faceoffs += 1

        window_end = min(ev.seconds + window_seconds, _PERIOD_LENGTH_SECONDS)
        next_faceoff_time: Optional[float] = None
        for later in events[i + 1:]:
            if later.period != ev.period:
                break
            if later.is_faceoff:
                next_faceoff_time = later.seconds
                break
        actual_end = window_end if next_faceoff_time is None else min(window_end, next_faceoff_time)
        window_total += max(0.0, actual_end - ev.seconds)

        for later in events[i + 1:]:
            if later.period != ev.period or later.seconds > actual_end:
                break
            if later.is_shot and later.team_id is not None:
                if later.team_id == ev.team_id:
                    winner_shots += 1
                else:
                    other_shots += 1

    return GamePostFaceoffShots(
        game_id=str(payload.get("id") or ""),
        n_faceoffs=n_faceoffs, winner_shots=winner_shots, other_shots=other_shots,
        window_seconds_total=window_total,
    )


def compute_post_faceoff_shots_by_strength_role(
    payload: Dict, *, window_seconds: float = 15.0, winner_role: str,
) -> Optional[GamePostFaceoffShots]:
    """Same methodology as `compute_post_faceoff_shots`, restricted to PP/PK-STRENGTH draws (the
    population the EV-only extraction path excludes entirely) and further filtered by the WINNER's
    own role at the draw: `winner_role="PP"` isolates draws the team already on the power play also
    won; `winner_role="PK"` isolates draws the shorthanded team won. Returns `None` for a payload
    with no `plays` list; a game with zero matching draws returns a record with `n_faceoffs==0`.

    Uses ALL shots (any strength state) in the post-draw window, truncated at the next faceoff OF
    ANY STRENGTH (not just matching-role ones) -- same "attribute to the most recent preceding
    draw" discipline as the zone-filtered function, now spanning strength-state changes too, since a
    penalty can expire mid-window and the shot stream does not pause for that.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("plays"), list):
        return None
    role_filter = str(winner_role).strip().upper()
    events = _extract_timed_events(payload, include_non_ev=True)

    n_faceoffs = winner_shots = other_shots = 0
    window_total = 0.0
    for i, ev in enumerate(events):
        if not ev.is_faceoff or ev.team_id is None or ev.role != role_filter:
            continue
        n_faceoffs += 1

        window_end = min(ev.seconds + window_seconds, _PERIOD_LENGTH_SECONDS)
        next_faceoff_time: Optional[float] = None
        for later in events[i + 1:]:
            if later.period != ev.period:
                break
            if later.is_faceoff:
                next_faceoff_time = later.seconds
                break
        actual_end = window_end if next_faceoff_time is None else min(window_end, next_faceoff_time)
        window_total += max(0.0, actual_end - ev.seconds)

        for later in events[i + 1:]:
            if later.period != ev.period or later.seconds > actual_end:
                break
            if later.is_shot and later.team_id is not None:
                if later.team_id == ev.team_id:
                    winner_shots += 1
                else:
                    other_shots += 1

    return GamePostFaceoffShots(
        game_id=str(payload.get("id") or ""),
        n_faceoffs=n_faceoffs, winner_shots=winner_shots, other_shots=other_shots,
        window_seconds_total=window_total,
    )


@dataclass(frozen=True)
class PostFaceoffShotSummary:
    n_games: int
    n_faceoffs: int
    winner_shots: int
    other_shots: int
    winner_share: float          # winner_shots / (winner_shots + other_shots)
    window_seconds_total: float
    shots_per_100_faceoff_seconds_winner: float
    shots_per_100_faceoff_seconds_other: float


def summarize_post_faceoff_shots(records: Sequence[GamePostFaceoffShots]) -> PostFaceoffShotSummary:
    n_games = len(records)
    n_faceoffs = sum(r.n_faceoffs for r in records)
    winner_shots = sum(r.winner_shots for r in records)
    other_shots = sum(r.other_shots for r in records)
    window_total = sum(r.window_seconds_total for r in records)
    total = winner_shots + other_shots
    winner_share = (winner_shots / total) if total else 0.0
    per100_winner = (winner_shots / window_total * 100.0) if window_total else 0.0
    per100_other = (other_shots / window_total * 100.0) if window_total else 0.0
    return PostFaceoffShotSummary(
        n_games=n_games, n_faceoffs=n_faceoffs, winner_shots=winner_shots, other_shots=other_shots,
        winner_share=round(winner_share, 4), window_seconds_total=round(window_total, 1),
        shots_per_100_faceoff_seconds_winner=round(per100_winner, 4),
        shots_per_100_faceoff_seconds_other=round(per100_other, 4),
    )
