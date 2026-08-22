"""Basketball pressure events, from ESPN's `plays` feed.

Shared across NBA / WNBA / NCAAB rather than per-sport, matching the precedent
`basketball_props_*.py` and `basketball_live_artifacts.py` already set: the
three leagues differ only in period geometry and tricode space, and three
copies of a shot taxonomy is three places for a weight to drift.

The decay math is NOT here -- `shared/momentum_core.py` owns it. This module
owns the one thing that is genuinely basketball: what counts as pressure.

WHY THIS IS NOT A COPY OF SOCCER'S TAXONOMY. Soccer excludes goals from the
series because a goal is a rounding error in the feed (~2.7 a match) and a
series that counts them spikes at the thing it claims to predict. Basketball
has ~200 scoring events a game, so "exclude the scoring event" would discard
most of the feed. The resolution is two series from one pass:

    pressure  -- attempts, offensive rebounds, free-throw trips, steals,
                 blocks, and turnovers forced. POINTS ARE NOT IN IT.
                 This is the series that gets lead/lag-validated and drawn.
    scoring   -- actual point differential under the same decay. A NARRATOR by
                 construction: it may drive a label ("PHX on a 9-0 run") and
                 must never be fed to a model or reported as predictive.

Keeping them separate is the same rule as soccer's `include_goals=False`, at a
sport where the naive version of that rule does not work. `learnings.md`
2026-08-21 FORBIDS publishing a field under a name that describes a different
quantity, which is exactly what one merged series would be.

**A MADE SHOT'S ATTEMPT IS IN `pressure`; ITS POINTS ARE NOT.** Dropping makes
would be perverse -- a team's pressure would FALL at the moment it converted --
and it is not circular: the points from a make at `t` land in the PAST
differential, while the validation window is `(t, t+H]`, which is disjoint.

WHAT WE CAN AND CANNOT SEE, stated up front because it bounds every claim made
from this module:

    shot volume        -> DIRECT (`pointsAttempted`, verified present: 2,778
                          attempts measured across the tracked mirror, 0 of
                          them unattributed to a team)
    shot quality       -> NONE. ESPN's basketball plays carry no reliable shot
                          location. Soccer's `_classify_location` reads its
                          commentary TEXT; the basketball text has no
                          equivalent we have verified, and this module does
                          NOT guess one.
    possession context -> NOT USED HERE. `poss_est` exists in the
                          `live_pbp_stats` family and is the better decay axis
                          (see the module note on half-life), but wiring it is
                          Phase B/C work, not Phase A.

EVERY WEIGHT AND THE HALF-LIFE BELOW ARE PROPOSALS, NOT MEASUREMENTS. Nothing
in this module has been validated against outcomes. Do not read a series
produced here as evidence that basketball momentum has predictive content --
that is what `scripts/basketball_momentum_leadlag.py` (Phase C) is for, and it
does not exist yet.
"""

from __future__ import annotations

from typing import Any, Mapping

from syndicate.features.shared.game_shape import basketball_elapsed_minutes

# League period geometry.
#
# **THE `nba`/`wnba` ROWS MUST AGREE WITH `game_shape._BASKETBALL_RULES`**, and
# `test_basketball_momentum.py` asserts it. They are duplicated rather than
# imported because that table is private AND does not carry the NCAA rows;
# reaching into a private name to get two thirds of what is needed buys nothing
# a test does not buy more safely.
#
# NCAA men play two 20-minute HALVES, women four 10-minute quarters. Neither is
# in `_BASKETBALL_RULES` today; adding them there is Phase E, alongside putting
# NCAAB into `live_lens_loop._LIVE_LENS_SPORTS` (it is absent from both).
# **NEITHER NCAA ROW IS VERIFIED AGAINST A REAL ESPN FEED** -- no NCAAB summary
# has been captured, and the season does not start until November 2026.
_LEAGUE_PERIODS: dict[str, dict[str, float]] = {
    "nba": {"quarter_minutes": 12.0, "ot_minutes": 5.0, "regulation_periods": 4.0},
    "wnba": {"quarter_minutes": 10.0, "ot_minutes": 5.0, "regulation_periods": 4.0},
    "ncaab": {"quarter_minutes": 20.0, "ot_minutes": 5.0, "regulation_periods": 2.0},
    "ncaabw": {"quarter_minutes": 10.0, "ot_minutes": 5.0, "regulation_periods": 4.0},
}

# Pressure weights. Ordered by how strongly each says "this team is threatening
# RIGHT NOW", not by how often it happens -- soccer's stated principle, kept.
#
# NON-SHOOTING FOULS ARE DELIBERATELY ABSENT, for soccer's reason transferred
# intact: a foul is committed BY one side and suffered by the other, and which
# of those indicates pressure depends on context the feed does not carry.
# Shooting fouls ARE counted, because they resolve to free throws and the feed
# tells us who shoots them.
#
# DEFENSIVE REBOUNDS ARE DELIBERATELY ABSENT: a defensive board is the DEFAULT
# outcome of a miss, so counting it would credit a team for its opponent having
# already been counted for the attempt.
_SHOT_ATTEMPT_WEIGHT = 1.0
_OFFENSIVE_REBOUND_WEIGHT = 1.0
# Per FREE THROW, not per trip. ESPN emits each attempt as its own play, so a
# two-shot trip accumulates ~0.8 and a three-shot trip ~1.2. Weighting per-trip
# would need trip grouping (team + period + clock), which is inference this
# module does not need to make.
_FREE_THROW_WEIGHT = 0.4
_STEAL_WEIGHT = 1.0
_BLOCK_WEIGHT = 0.75
# Credited to the team that did NOT commit it -- see `_TURNOVER_FLIPS_SIGN`.
_TURNOVER_WEIGHT = 1.25

# Half-life, in seconds. **A CHOSEN CONSTANT, NOT A FITTED ONE**, and unlike
# soccer's it is not even inherited from a sport that swept it -- soccer's own
# docstring says its 300s "should be swept before any number from it is
# trusted", and 300s in a game with a 24-second shot clock is ~12 possessions
# per side, far too long to read as "right now".
#
# 120s is a starting point for the Phase C sweep over {60, 90, 120, 180}, and
# the sweep should also settle whether the axis ought to be POSSESSIONS rather
# than seconds -- one constant that ports across NBA/WNBA/NCAAB pace regimes
# instead of three tunings. Scope section 7, decision 1.
DEFAULT_HALF_LIFE_SECONDS = 120.0

# ESPN attributes a turnover to the team that COMMITTED it. Pressure belongs to
# the other side, so this taxonomy is the one place a play's team and its sign
# deliberately disagree. Named rather than inlined because a silent sign flip
# is the single easiest thing to misread in this file.
_TURNOVER_FLIPS_SIGN = True


def _normalize_clock(display_clock: Any) -> str | None:
    """ESPN's clock to the strict `M:SS` `basketball_elapsed_minutes` demands.

    **THIS EXISTS BECAUSE OF THE LAST MINUTE OF EVERY PERIOD.** ESPN switches
    to a tenths format under 1:00 -- `"48.6"`, no colon. `basketball_elapsed_
    minutes` splits on `":"` and returns None for anything that is not exactly
    two parts, so every event inside the final minute would be DROPPED. That is
    the stretch of a period where pressure matters most, and the loss would be
    silent: fewer events, a plausible-looking series, no error anywhere.

    The fix belongs HERE, not there. That function is byte-for-byte pinned to
    `wnba/cards.py:_wnba_elapsed_minutes` by
    `test_basketball_elapsed_minutes_agrees_with_the_wnba_implementation`, and
    its own docstring says being more permissive "would BE the drift -- one
    caller would accept a clock the other rejects, and the disagreement would
    surface as a population difference in a scoring cell rather than as an
    error". Normalising on the way in respects that pin and still keeps the
    events.
    """
    text = str(display_clock or "").strip()
    if not text:
        return None
    if ":" in text:
        return text
    try:
        seconds = float(text)
    except (TypeError, ValueError):
        return None
    if seconds < 0.0 or seconds >= 60.0:
        return None
    # Truncate, do not round: 59.7 must not become 1:00 and push the event into
    # the previous period's elapsed time.
    return f"0:{int(seconds):02d}"


def _team_index(summary: Mapping[str, Any]) -> tuple[dict[str, str], str | None]:
    """ESPN team id -> tricode, plus the HOME tricode.

    Read from `header.competitions[0].competitors[]`, which carries
    `homeAway` -- so home orientation comes from the feed rather than from a
    caller's guess. Returns `({}, None)` rather than raising: an unparseable
    header means no event can be signed, which the caller reports as an honest
    `supported: False`.
    """
    index: dict[str, str] = {}
    home_tri: str | None = None
    header = summary.get("header") if isinstance(summary.get("header"), dict) else {}
    competitions = header.get("competitions") if isinstance(header.get("competitions"), list) else []
    if not competitions or not isinstance(competitions[0], dict):
        return {}, None
    competitors = competitions[0].get("competitors")
    if not isinstance(competitors, list):
        return {}, None
    for competitor in competitors:
        if not isinstance(competitor, dict):
            continue
        team = competitor.get("team") if isinstance(competitor.get("team"), dict) else {}
        team_id = str(team.get("id") or "").strip()
        tricode = str(team.get("abbreviation") or "").strip().upper()
        if not team_id or not tricode:
            continue
        index[team_id] = tricode
        if str(competitor.get("homeAway") or "").strip().lower() == "home":
            home_tri = tricode
    return index, home_tri


def _classify(play: Mapping[str, Any]) -> tuple[str, float] | None:
    """(kind, weight) for a pressure play, or None if it carries no pressure.

    Reads the DERIVED numeric fields first (`pointsAttempted`, `scoreValue`,
    `shootingPlay`) and falls back to `type.text` only for the non-shooting
    events, which have no numeric signature. Text matching is last because it
    is the part most likely to differ between leagues and to change under us.
    """
    type_text = str((play.get("type") or {}).get("text") or "").strip().lower()
    text = str(play.get("text") or "").strip().lower()
    shooting = bool(play.get("shootingPlay"))

    points_attempted = play.get("pointsAttempted")
    try:
        attempted = int(points_attempted) if points_attempted is not None else 0
    except (TypeError, ValueError):
        attempted = 0

    if shooting and attempted == 1:
        return "free_throw", _FREE_THROW_WEIGHT
    if shooting and attempted in (2, 3):
        # 2PA and 3PA weigh the same. Weighting by expected value is defensible
        # and unmeasured; it is a Phase C sweep question, not a Phase A guess.
        return ("shot_attempt_3" if attempted == 3 else "shot_attempt_2"), _SHOT_ATTEMPT_WEIGHT

    # Non-shooting plays: no numeric signature, so match on the type label.
    if "offensive rebound" in type_text or "offensive rebound" in text:
        return "offensive_rebound", _OFFENSIVE_REBOUND_WEIGHT
    if "steal" in type_text or "steal" in text:
        return "steal", _STEAL_WEIGHT
    if "block" in type_text or "blocked shot" in text:
        return "block", _BLOCK_WEIGHT
    if "turnover" in type_text or "turnover" in text:
        return "turnover", _TURNOVER_WEIGHT
    return None



def possession_index_stream(plays: Any) -> list[float]:
    """Running game-level possession estimate, one entry per play, in feed order.

    **THE SECOND DECAY AXIS** (scope section 7, decision 1: publish both, decide
    in Phase C). A half-life in SECONDS means different things in a fast NCAAB
    game and a slow NBA one, so it needs re-tuning per league; a half-life in
    POSSESSIONS ports across all three unchanged.

    Uses the platform's existing estimator so two possession counts cannot
    disagree: `FGA + TOV + 0.44*FTA - OREB`, which
    `vendor/wnba_betting_repo/app.py:3572` computes and `game_shape.py:447`
    documents. **Computed HERE from the play stream rather than joined from the
    `live_pbp_stats` family**, deliberately: that family's coverage measured 19
    of 126 records on ONE date in the tracked mirror, and a decay axis that
    silently disappears when its source artifact is thin is worse than one that
    is merely mis-scaled.

    Accumulated over BOTH teams -- it counts possessions in the GAME, which is
    the clock this replaces, not possessions BY a team.
    """
    out: list[float] = []
    total = 0.0
    for play in (plays if isinstance(plays, list) else []):
        if isinstance(play, dict):
            attempted = play.get("pointsAttempted")
            try:
                attempted_int = int(attempted) if attempted is not None else 0
            except (TypeError, ValueError):
                attempted_int = 0
            shooting = bool(play.get("shootingPlay"))
            type_text = str((play.get("type") or {}).get("text") or "").strip().lower()
            text = str(play.get("text") or "").strip().lower()
            if shooting and attempted_int in (2, 3):
                total += 1.0
            elif shooting and attempted_int == 1:
                total += 0.44
            elif "turnover" in type_text or "turnover" in text:
                total += 1.0
            elif "offensive rebound" in type_text or "offensive rebound" in text:
                total -= 1.0
        # Emitted for EVERY play, including the ones that move nothing, so the
        # list stays index-aligned with `plays`. A filtered list would silently
        # misalign every annotation after the first non-scoring play.
        out.append(round(total, 3))
    return out


def basketball_pressure_events(
    summary: Mapping[str, Any],
    *,
    league_code: str,
    home_tri: str | None = None,
) -> list[dict[str, Any]]:
    """Weighted pressure rows, signed +1 home / -1 away, keyed on ELAPSED time.

    **POINTS ARE NOT IN THESE ROWS.** See the module docstring; use
    `basketball_scoring_events` for the narrator series.

    Rows carry `clock_seconds` measured from tip-off, NOT the period-relative
    countdown ESPN publishes. Decay is meaningless against a clock that resets
    every quarter and runs backwards: two events 30 real seconds apart across a
    period boundary would read as ~12 minutes apart, in the wrong direction.

    `home_tri` overrides the header's own `homeAway`, for the caller that
    already knows it. Passing a tricode that is not in the game silently signs
    every event away-negative, so it is validated against the team index.
    """
    league = str(league_code or "").strip().lower()
    rules = _LEAGUE_PERIODS.get(league)
    if rules is None:
        raise ValueError(
            f"unknown league_code {league_code!r}; known: {sorted(_LEAGUE_PERIODS)}"
        )

    index, header_home = _team_index(summary)
    if not index:
        return []
    resolved_home = str(home_tri or "").strip().upper() or header_home
    if not resolved_home or resolved_home not in set(index.values()):
        # An unresolvable home side means nothing can be signed. Returning []
        # lets the caller emit a stated reason; inventing a sign would produce a
        # chart that is confidently mirrored.
        return []

    plays = summary.get("plays")
    if not isinstance(plays, list):
        return []

    possessions = possession_index_stream(plays)
    out: list[dict[str, Any]] = []
    for play_index, play in enumerate(plays):
        if not isinstance(play, dict):
            continue
        classified = _classify(play)
        if classified is None:
            continue
        kind, weight = classified

        team_id = str((play.get("team") or {}).get("id") or "").strip()
        tricode = index.get(team_id)
        if not tricode:
            continue

        seconds = elapsed_seconds(play, league_code=league)
        if seconds is None:
            continue

        credited = tricode
        if kind == "turnover" and _TURNOVER_FLIPS_SIGN:
            others = [tri for tri in index.values() if tri != tricode]
            if len(others) != 1:
                continue
            credited = others[0]

        out.append({
            "clock_seconds": seconds,
            "possession_index": possessions[play_index],
            "team": credited,
            "committed_by": tricode if credited != tricode else None,
            "sign": 1.0 if credited == resolved_home else -1.0,
            "weight": weight,
            "type": kind,
        })
    out.sort(key=lambda row: row["clock_seconds"])
    return out


def basketball_scoring_events(
    summary: Mapping[str, Any],
    *,
    league_code: str,
    home_tri: str | None = None,
) -> list[dict[str, Any]]:
    """Points scored, signed home-positive -- THE NARRATOR SERIES.

    A series over these correlates with scoring by construction and carries no
    predictive content whatsoever. It exists to drive a human-readable label
    and to be the OUTCOME side of the Phase C lead/lag test. **It must never be
    fed to a model, and must never be published under a name that does not say
    what it is.**
    """
    league = str(league_code or "").strip().lower()
    if league not in _LEAGUE_PERIODS:
        raise ValueError(
            f"unknown league_code {league_code!r}; known: {sorted(_LEAGUE_PERIODS)}"
        )

    index, header_home = _team_index(summary)
    if not index:
        return []
    resolved_home = str(home_tri or "").strip().upper() or header_home
    if not resolved_home or resolved_home not in set(index.values()):
        return []

    plays = summary.get("plays")
    if not isinstance(plays, list):
        return []

    possessions = possession_index_stream(plays)
    out: list[dict[str, Any]] = []
    for play_index, play in enumerate(plays):
        if not isinstance(play, dict):
            continue
        try:
            points = int(play.get("scoreValue") or 0)
        except (TypeError, ValueError):
            continue
        if points <= 0:
            continue
        tricode = index.get(str((play.get("team") or {}).get("id") or "").strip())
        if not tricode:
            continue
        seconds = elapsed_seconds(play, league_code=league)
        if seconds is None:
            continue
        out.append({
            "clock_seconds": seconds,
            "possession_index": possessions[play_index],
            "team": tricode,
            "sign": 1.0 if tricode == resolved_home else -1.0,
            "weight": float(points),
            "type": "points",
        })
    out.sort(key=lambda row: row["clock_seconds"])
    return out


def elapsed_seconds(play: Mapping[str, Any], *, league_code: str) -> float | None:
    """Seconds since tip-off for one ESPN play, or None if it cannot be placed.

    Delegates the arithmetic to `game_shape.basketball_elapsed_minutes` rather
    than repeating it -- that function already handles OT period lengths and is
    test-pinned against WNBA's implementation. This wrapper does two things it
    does not: normalises the sub-minute clock format (`_normalize_clock`) and
    converts minutes to seconds, which is the unit `momentum_core` decays in.
    """
    rules = _LEAGUE_PERIODS.get(str(league_code or "").strip().lower())
    if rules is None:
        return None
    period = (play.get("period") or {}).get("number") if isinstance(play.get("period"), dict) else None
    clock = (play.get("clock") or {}).get("displayValue") if isinstance(play.get("clock"), dict) else None
    normalized = _normalize_clock(clock)
    if normalized is None:
        return None
    minutes = basketball_elapsed_minutes(
        period,
        normalized,
        quarter_minutes=rules["quarter_minutes"],
        ot_minutes=rules["ot_minutes"],
        regulation_periods=int(rules["regulation_periods"]),
    )
    if minutes is None:
        return None
    return round(float(minutes) * 60.0, 3)


# Half-life on the POSSESSION axis, for the same sweep. ~8 possessions is
# roughly two minutes of NBA game time at league-average pace, so the two
# defaults describe a comparable window and the Phase C sweep compares like
# with like. Equally a CHOSEN constant.
DEFAULT_HALF_LIFE_POSSESSIONS = 8.0

__all__ = [
    "DEFAULT_HALF_LIFE_POSSESSIONS",
    "DEFAULT_HALF_LIFE_SECONDS",
    "basketball_pressure_events",
    "basketball_scoring_events",
    "elapsed_seconds",
    "possession_index_stream",
]
