"""Real shot-quality (expected goals) model for hockeysim, built from NHL's `play-by-play`
endpoint's shot-location data -- closes the gap `docs/ai_context/hockeysim_engine_reference.md` §5
flagged as genuinely absent: `xgf_per_60`/`xga_per_60` have a reader (`loaders.load_team_xg_map`)
but NO PRODUCER anywhere, because neither the `landing` feed (goals/penalties/period splits) nor
the `boxscore` feed (per-player box totals) the truth loader already reads carries shot-location
data at all. `play-by-play` does: each shot/goal/missed-shot/blocked-shot event carries
`xCoord`/`yCoord`, `shotType`, `situationCode` (strength state), and `zoneCode`.

WHY FENWICK (unblocked attempts), NOT CORSI. `blocked-shot` events record the coordinate of the
BLOCK, not the shooter's release point -- using it for a distance/angle feature would systematically
understate shot distance. Every public NHL xG model (MoneyPuck, Corsica/Evolving-Hockey, etc.)
fits on Fenwick events (shots-on-goal + missed-shots + goals) for exactly this reason; this module
does the same. Blocked shots still count toward raw shot VOLUME elsewhere in this package
(`boxscore_shot_strength.py`), just not toward shot QUALITY here.

WHY sign(xCoord), NOT `homeTeamDefendingSide` BOOKKEEPING. The attacked net's x-coordinate could be
derived by tracking `homeTeamDefendingSide` (which flips each period) against `eventOwnerTeamId`,
but there is a simpler, standard, and equally correct shortcut used across the public NHL analytics
community: a shot recorded in (or near) the offensive zone has on-ice coordinates naturally closer
to the net it is attacking, so `sign(xCoord)` directly identifies which net (+89 or -89) without any
period-flip bookkeeping at all. This trades a small amount of noise on rare neutral-zone attempts
for a much simpler, less error-prone implementation -- the same trade-off every public model makes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

NET_X = 89.0

# Rare/miscellaneous shot types collapse into "other" so the one-hot feature space doesn't fit
# noise on a handful of examples (e.g. "between-legs", "poke", "cradle" each occur a handful of
# times across an entire season).
_KNOWN_SHOT_TYPES = {"wrist", "slap", "snap", "backhand", "tip-in", "deflected", "wrap-around"}

_FENWICK_TYPES = {"shot-on-goal", "missed-shot", "goal"}


@dataclass(frozen=True)
class ShotEvent:
    """One Fenwick shot attempt (SOG, missed shot, or goal), fully featurized."""

    game_id: str
    team_id: int          # eventOwnerTeamId -- the SHOOTING team
    is_goal: bool
    distance: float        # feet from the net being attacked
    angle: float           # degrees off the direct line to the net (0 = straight on)
    shot_type: str          # bucketed to _KNOWN_SHOT_TYPES or "other"
    strength_state: str     # "EV" / "PP" / "SH" -- of the SHOOTING team
    is_rebound: bool        # a Fenwick attempt by the SAME team within 3s of the prior one
    is_empty_net: bool
    period: int
    seconds_elapsed: int    # absolute game-clock seconds from the start of the game (period-aware)


def _period_start_seconds(period: int) -> int:
    # Periods 1-3 are 20 minutes; OT (period 4+) is treated as a continuation for ordering
    # purposes only -- exact OT length doesn't matter for a same-team-rebound lookback.
    if period <= 3:
        return (period - 1) * 20 * 60
    return 3 * 20 * 60 + (period - 4) * 5 * 60


def _time_in_period_to_seconds(text: str) -> Optional[int]:
    try:
        mm, ss = str(text).split(":")
        return int(mm) * 60 + int(ss)
    except (ValueError, AttributeError):
        return None


def _situation_state(situation_code: object, *, shooter_is_home: bool) -> Optional[str]:
    """`situationCode` is a 4-digit string: [awayGoalie][awaySkaters][homeSkaters][homeGoalie].
    e.g. "1551" = away goalie in net, 5 away skaters, 5 home skaters, home goalie in net (5v5 EV).
    Returns the STRENGTH STATE of the shooting team, or None if the code can't be parsed (a
    shootout/rare event) -- callers skip those shots rather than guessing."""
    code = str(situation_code or "")
    if len(code) != 4 or not code.isdigit():
        return None
    away_skaters, home_skaters = int(code[1]), int(code[2])
    if shooter_is_home:
        my, opp = home_skaters, away_skaters
    else:
        my, opp = away_skaters, home_skaters
    if my == opp:
        return "EV"
    return "PP" if my > opp else "SH"


def _bucket_shot_type(raw: object) -> str:
    t = str(raw or "").strip().lower()
    return t if t in _KNOWN_SHOT_TYPES else "other"


def parse_play_by_play_shots(payload: Dict) -> List[ShotEvent]:
    """Parse one `play-by-play` payload into its Fenwick shot events (pure; never raises). Returns
    `[]` for a payload missing team ids or a `plays` list."""
    if not isinstance(payload, dict):
        return []
    home = payload.get("homeTeam") or {}
    away = payload.get("awayTeam") or {}
    home_id = home.get("id")
    away_id = away.get("id")
    if home_id is None or away_id is None:
        return []
    game_id = str(payload.get("id") or "")
    plays = payload.get("plays") or []

    # last Fenwick-event clock (seconds) per team, for the rebound feature -- a shot attempt by
    # the SAME team within 3s of its own prior Fenwick attempt.
    last_fenwick_at: Dict[int, int] = {}

    out: List[ShotEvent] = []
    for p in plays:
        type_key = p.get("typeDescKey")
        if type_key not in _FENWICK_TYPES:
            continue
        details = p.get("details") or {}
        team_id = details.get("eventOwnerTeamId")
        x = details.get("xCoord")
        y = details.get("yCoord")
        if team_id is None or x is None or y is None:
            continue
        try:
            x = float(x)
            y = float(y)
            team_id = int(team_id)
        except (TypeError, ValueError):
            continue

        period = int((p.get("periodDescriptor") or {}).get("number") or 1)
        secs_in_period = _time_in_period_to_seconds(p.get("timeInPeriod"))
        seconds_elapsed = _period_start_seconds(period) + (secs_in_period or 0)

        net_x = NET_X if x >= 0 else -NET_X
        distance = math.hypot(net_x - x, y)
        angle = math.degrees(math.atan2(abs(y), max(abs(net_x - x), 0.01)))

        shooter_is_home = team_id == home_id
        strength = _situation_state(p.get("situationCode"), shooter_is_home=shooter_is_home)
        if strength is None:
            continue  # unparseable situation code -- skip rather than guess

        is_rebound = False
        prev = last_fenwick_at.get(team_id)
        if prev is not None and 0 <= seconds_elapsed - prev <= 3:
            is_rebound = True
        last_fenwick_at[team_id] = seconds_elapsed

        is_empty_net = "goalieInNetId" not in details

        out.append(ShotEvent(
            game_id=game_id, team_id=team_id, is_goal=(type_key == "goal"),
            distance=round(distance, 2), angle=round(angle, 2),
            shot_type=_bucket_shot_type(details.get("shotType")),
            strength_state=strength, is_rebound=is_rebound, is_empty_net=is_empty_net,
            period=period, seconds_elapsed=seconds_elapsed,
        ))
    return out


def build_shot_dataset(payloads: Sequence[Dict]) -> List[ShotEvent]:
    """Parse many `play-by-play` payloads into one flat shot dataset (pure)."""
    out: List[ShotEvent] = []
    for payload in payloads:
        out.extend(parse_play_by_play_shots(payload))
    return out


# Feature ordering is FIXED so the same vectorization is used for fitting and scoring -- a drift
# between the two would silently corrupt every prediction. `_bucket_shot_type` already collapses
# rare types, so this covers every value that function can return.
SHOT_TYPE_LEVELS = sorted(_KNOWN_SHOT_TYPES) + ["other"]
STRENGTH_LEVELS = ["EV", "PP", "SH"]


def featurize(shots: Sequence[ShotEvent]) -> List[List[float]]:
    """Fixed-order numeric feature matrix: [distance, angle, is_rebound, is_empty_net,
    one-hot(shot_type, baseline=wrist), one-hot(strength_state, baseline=EV)]. Baseline levels are
    OMITTED (standard dummy-variable encoding) so the matrix isn't rank-deficient."""
    rows: List[List[float]] = []
    shot_type_cols = [t for t in SHOT_TYPE_LEVELS if t != "wrist"]
    strength_cols = [s for s in STRENGTH_LEVELS if s != "EV"]
    for s in shots:
        row = [s.distance, s.angle, 1.0 if s.is_rebound else 0.0, 1.0 if s.is_empty_net else 0.0]
        row.extend(1.0 if s.shot_type == t else 0.0 for t in shot_type_cols)
        row.extend(1.0 if s.strength_state == st else 0.0 for st in strength_cols)
        rows.append(row)
    return rows


FEATURE_NAMES = (
    ["distance", "angle", "is_rebound", "is_empty_net"]
    + [f"shot_type_{t}" for t in SHOT_TYPE_LEVELS if t != "wrist"]
    + [f"strength_{s}" for s in STRENGTH_LEVELS if s != "EV"]
)
