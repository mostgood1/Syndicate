"""ESPN fantasy-football scoring — the rule set, as data.

Separate from every projection concern on purpose: a projection produces a
STAT LINE (yards, receptions, touchdowns), and scoring turns a stat line into
points. Keeping them apart is what lets one projection run serve PPR, half-PPR
and standard from the same numbers instead of three parallel model runs, and it
is the same orchestration/domain split
``docs/ai_context/model_engine_standard.md`` asks for elsewhere.

The defaults are ESPN's own default league settings. Anything a league commonly
changes is a field on ``ScoringProfile`` rather than a literal in the scoring
function, so a different league is a different profile, not a fork.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from typing import Any
from typing import Mapping


@dataclass(frozen=True)
class ScoringProfile:
    """One league's scoring rules. Every value is points."""

    key: str
    label: str

    # --- passing ---
    passing_yards_per_point: float = 25.0
    passing_td: float = 4.0
    interception_thrown: float = -2.0
    passing_2pt: float = 2.0

    # --- rushing ---
    rushing_yards_per_point: float = 10.0
    rushing_td: float = 6.0
    rushing_2pt: float = 2.0

    # --- receiving ---
    receiving_yards_per_point: float = 10.0
    receiving_td: float = 6.0
    receiving_2pt: float = 2.0
    reception: float = 0.0

    # --- shared ---
    fumble_lost: float = -2.0

    # --- kicking (ESPN default: distance-banded FGs) ---
    fg_made_0_39: float = 3.0
    fg_made_40_49: float = 4.0
    fg_made_50_plus: float = 5.0
    fg_missed: float = -1.0
    pat_made: float = 1.0
    pat_missed: float = -1.0

    # --- team defense / special teams ---
    dst_sack: float = 1.0
    dst_interception: float = 2.0
    dst_fumble_recovery: float = 2.0
    dst_safety: float = 2.0
    dst_touchdown: float = 6.0
    dst_blocked_kick: float = 2.0
    # ESPN's default points-allowed ladder, as (max_points_allowed, points).
    # Evaluated in order; the first band whose bound the opponent's score does
    # not exceed wins. The final band's bound is intentionally unbounded.
    dst_points_allowed_bands: tuple[tuple[float, float], ...] = (
        (0.0, 10.0),
        (6.0, 7.0),
        (13.0, 4.0),
        (17.0, 1.0),
        (27.0, 0.0),
        (34.0, -1.0),
        (45.0, -3.0),
        (float("inf"), -5.0),
    )


ESPN_PPR = ScoringProfile(key="ppr", label="ESPN PPR", reception=1.0)
ESPN_HALF_PPR = ScoringProfile(key="half_ppr", label="ESPN Half PPR", reception=0.5)
ESPN_STANDARD = ScoringProfile(key="standard", label="ESPN Standard", reception=0.0)

SCORING_PROFILES: dict[str, ScoringProfile] = {
    profile.key: profile for profile in (ESPN_PPR, ESPN_HALF_PPR, ESPN_STANDARD)
}

DEFAULT_SCORING_KEY = "ppr"

# Every stat key ``score_stat_line`` reads. Exported so the input checklist can
# enumerate what scoring CONSUMES without grepping for names it expects to find
# -- `model_engine_standard.md` s4.1: a name search proves only that your own
# vocabulary is absent.
SCORED_STAT_KEYS: tuple[str, ...] = (
    "passing_yards",
    "passing_tds",
    "interceptions",
    "passing_2pt",
    "rushing_yards",
    "rushing_tds",
    "rushing_2pt",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "receiving_2pt",
    "fumbles_lost",
    "fg_made_0_39",
    "fg_made_40_49",
    "fg_made_50_plus",
    "fg_missed",
    "pat_made",
    "pat_missed",
    "dst_sacks",
    "dst_interceptions",
    "dst_fumble_recoveries",
    "dst_safeties",
    "dst_touchdowns",
    "dst_blocked_kicks",
    "dst_points_allowed",
)

_SCORING_ALIASES = {
    "full_ppr": "ppr",
    "1ppr": "ppr",
    "half": "half_ppr",
    "0.5ppr": "half_ppr",
    "std": "standard",
    "non_ppr": "standard",
}


def resolve_scoring(key: str | None) -> ScoringProfile:
    """Look up a profile by key, falling back to the PPR default.

    Deliberately tolerant of the shapes a query string produces (``Half-PPR``,
    ``half ppr``, ``HALF_PPR``) because this is reached straight off a request
    argument.
    """
    if not key:
        return SCORING_PROFILES[DEFAULT_SCORING_KEY]
    normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
    normalized = _SCORING_ALIASES.get(normalized, normalized)
    return SCORING_PROFILES.get(normalized, SCORING_PROFILES[DEFAULT_SCORING_KEY])


def dst_points_allowed_score(points_allowed: float, profile: ScoringProfile) -> float:
    """The points-allowed ladder, isolated so it can be tested directly.

    Interpolates across band boundaries for a FRACTIONAL points-allowed value,
    which is what a projection produces -- a team is not projected to allow
    exactly 17.0 points, it is projected to allow 21.3. Snapping that to a
    single band would discard the whole distribution and systematically
    over-reward defenses sitting just under a boundary. The linear
    interpolation stands in for integrating the ladder over the real scoring
    distribution; it is monotone and exact at band centres, and it is an
    approximation this engine declares rather than hides.
    """
    bands = profile.dst_points_allowed_bands
    if not bands:
        return 0.0
    # Band centres: the midpoint between a band's lower edge (previous band's
    # bound + 1) and its own bound. The unbounded final band is anchored at its
    # lower edge.
    centres: list[tuple[float, float]] = []
    previous_bound = -1.0
    for bound, points in bands:
        if bound == float("inf"):
            centres.append((previous_bound + 1.0, points))
        else:
            centres.append(((previous_bound + 1.0 + bound) / 2.0, points))
        previous_bound = bound
    if points_allowed <= centres[0][0]:
        return centres[0][1]
    if points_allowed >= centres[-1][0]:
        return centres[-1][1]
    for index in range(len(centres) - 1):
        low_x, low_y = centres[index]
        high_x, high_y = centres[index + 1]
        if low_x <= points_allowed <= high_x:
            if high_x == low_x:
                return low_y
            weight = (points_allowed - low_x) / (high_x - low_x)
            return low_y + weight * (high_y - low_y)
    return centres[-1][1]


def score_stat_line(stat_line: Mapping[str, Any], profile: ScoringProfile) -> float:
    """Fantasy points for one stat line under one profile.

    Missing keys score zero -- a QB's line legitimately carries no
    ``fg_made_50_plus``. This is the ONE place in this engine where a missing
    key may mean zero, and it is safe here because scoring is a pure function
    of a line the projection already built; it is not reading an input
    something upstream was supposed to populate. Every other consumer goes
    through the input checklist instead (``model_engine_standard.md`` s4.2).
    """

    def value(key: str) -> float:
        raw = stat_line.get(key)
        if raw is None:
            return 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    points = 0.0

    points += value("passing_yards") / profile.passing_yards_per_point
    points += value("passing_tds") * profile.passing_td
    points += value("interceptions") * profile.interception_thrown
    points += value("passing_2pt") * profile.passing_2pt

    points += value("rushing_yards") / profile.rushing_yards_per_point
    points += value("rushing_tds") * profile.rushing_td
    points += value("rushing_2pt") * profile.rushing_2pt

    points += value("receptions") * profile.reception
    points += value("receiving_yards") / profile.receiving_yards_per_point
    points += value("receiving_tds") * profile.receiving_td
    points += value("receiving_2pt") * profile.receiving_2pt

    points += value("fumbles_lost") * profile.fumble_lost

    points += value("fg_made_0_39") * profile.fg_made_0_39
    points += value("fg_made_40_49") * profile.fg_made_40_49
    points += value("fg_made_50_plus") * profile.fg_made_50_plus
    points += value("fg_missed") * profile.fg_missed
    points += value("pat_made") * profile.pat_made
    points += value("pat_missed") * profile.pat_missed

    points += value("dst_sacks") * profile.dst_sack
    points += value("dst_interceptions") * profile.dst_interception
    points += value("dst_fumble_recoveries") * profile.dst_fumble_recovery
    points += value("dst_safeties") * profile.dst_safety
    points += value("dst_touchdowns") * profile.dst_touchdown
    points += value("dst_blocked_kicks") * profile.dst_blocked_kick
    if stat_line.get("dst_points_allowed") is not None:
        points += dst_points_allowed_score(value("dst_points_allowed"), profile)

    return points


def scoring_profile_summary(profile: ScoringProfile) -> dict[str, Any]:
    """The profile as a plain dict, for a payload's ``basis`` block.

    A served projection must be able to say what rules produced its number;
    this is how the API answers "what scoring is this".
    """
    payload: dict[str, Any] = {}
    for spec in dataclass_fields(profile):
        raw = getattr(profile, spec.name)
        if spec.name == "dst_points_allowed_bands":
            payload[spec.name] = [
                ["inf" if bound == float("inf") else bound, points] for bound, points in raw
            ]
            continue
        payload[spec.name] = raw
    return payload
