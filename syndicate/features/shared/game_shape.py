"""Game shape — the state a live projection was computed FROM, written down.

Lane `game-shape-capture`. Plan:
`.syndicate/plan_2026-08-16_state_conditional_learning.md`, Phase 1.

WHY THIS EXISTS. Every live model in this repo is scored, when it is scored at
all, on its average error. Nothing can currently ask *when* it is wrong --
whether the miss concentrates in high-traffic innings, on a third time through
the order, in blowouts, or late in a grinding game -- because **the conditioning
variable is never persisted**. Measured 2026-08-16:

  * MLB's live-lens JSONL stores game shape as a RENDERED STRING:
    `"liveText": "Top 5 | 1-1, 0 out | Colton Cowser vs Freddy Peralta"`, plus
    a scoreline and a status word.
  * `live_gameline_ledger` v2 -- the newest and best-shaped store in this family
    -- records `game_state`, `home_score`, `away_score`. A status word and a
    scoreline again.

Meanwhile `LiveSituation` (`vendor/mlb_bettingv2/sim_engine/live_mc.py:20`) is
constructed in full on every live tick to feed 120 sims, and is **discarded at
the return**: the live-MC lens carries `homeWinProb`, `total`, `batterStatDist`
and friends -- the sim's RESULTS -- and nothing about the state they were
computed from. This module turns that state into a record.

THREE DESIGN DECISIONS, each with a reason that is not stylistic.

1. **CAPTURE FINE, BUCKET COARSE, AND KEEP THEM SEPARATE FIELDS.**
   `estimate_live` runs 120 sims, so a win probability off it has a standard
   error of ~4.56 pp at p=0.5. Slicing that into the 24-cell base-out grid
   yields cells whose contents are noise with a decimal point. So the bucket
   this module PUBLISHES is coarse (phase x margin band, <=17 labels), while
   every fine field stays on the record. Anyone who later has the sample for a
   finer cut can re-bucket from stored records -- **re-bucketing must never
   require re-capturing.** That asymmetry is the whole point of the split.

2. **NO LEVERAGE INDEX.** A real leverage index needs a fitted win-expectancy
   table, and this repo does not have one. Emitting a plausible-looking
   `leverage` computed from a formula nobody validated is precisely `#377`'s
   failure -- an authoritative-looking number that means nothing -- committed by
   the module written to enable measurement. The INPUTS to leverage
   (`base_out_state`, `home_margin`, `phase`) are all here; a caller that
   acquires a real table can compute it. This module refuses to guess.

3. **NO VENDOR IMPORT.** `shared/` must not depend on `vendor/mlb_bettingv2`.
   Every accessor here is duck-typed over attribute *or* mapping access, so the
   same function reads a live `LiveSituation`, a JSON round-trip of one, or a
   test fixture dict. This also keeps the module importable in contexts where
   the vendor tree is absent.

WHAT THIS DOES NOT DO. No I/O, no persistence, no join, no opinion about whether
a projection was good. Pure functions over one situation. Persistence is the
caller's problem, deliberately: the natural store
(`live_gameline_ledger`) is held by an OPEN lane whose v2 measurement has not
fired yet, and changing a record shape underneath a running measurement is how
a result gets silently confounded.

SPORTS COVERED, and no two of them are the same job — which is the single most
useful thing to know before reading further:

  * **MLB is SERIALISATION.** Its state vector (`LiveSituation`) already exists
    in full at tick time and is merely discarded.
  * **Basketball is DERIVATION.** No state vector exists, so period, clock,
    score and the per-quarter array are assembled into one. Possession pace is
    not available at all.
  * **Football is PARTIAL CAPTURE.** Period/clock/score are captured; down,
    distance, field position and possession sit in the fetched ESPN payload and
    are never read. `situation=` accepts them so that upstream fix needs no
    change here.

Each sport's margin bands are in ITS OWN unit — baseball runs, basketball
points, football scores. An 8-point football game and an 8-point basketball
game are entirely different states, so a shared band table would mis-bucket
almost everything. Every sport is capped at 17 bucket labels for the same
reason (see the MLB header on the precision floor).

NEVER RAISES. An unparseable situation returns `valid: False` with a `reason`,
mirroring `model_scoring`'s philosophy that a bad record should cost one
observation rather than the whole batch. **An invalid shape buckets to
`"unknown"` and never to a real label** -- an unknown that defaults onto a
permissive branch turns a failed parse into a confident wrong segment.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

# Bump when a FIELD'S MEANING changes, not when a field is added. Readers must
# filter on this before aggregating: a rate computed across two shape versions
# is a rate over two different definitions. Same rule the sibling ledger
# documents for `LEDGER_VERSION`.
SHAPE_VERSION = 1

# Nine innings x two halves x three outs. Used to normalise progress; extras
# legitimately exceed it and are flagged rather than clamped away.
_OUTS_IN_REGULATION = 54

_UNKNOWN_BUCKET = "unknown"

# The eight base states, in the standard occupancy notation the vendor enum
# already uses ("1-3" = runners on first and third).
_VALID_BASE_STATES = frozenset({"---", "1--", "-2-", "--3", "12-", "1-3", "-23", "123"})


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read `key` from a mapping OR an object attribute.

    Both shapes occur for real: a live `LiveSituation` dataclass on the tick
    path, and a plain dict after any JSON round-trip or in a test fixture.
    """
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_int(value: Any) -> int | None:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(value)
    except (TypeError, ValueError):
        return None


def _base_state_text(value: Any) -> str | None:
    """Normalise a `BaseState` enum member, or its value, to occupancy text.

    **The trap this exists for:** `BaseState` is `class BaseState(str, Enum)`,
    not `StrEnum`, so on Python 3.11 `str(BaseState.FIRST)` returns
    `"BaseState.FIRST"` -- not `"1--"`. Reading it with `str()` would silently
    store the repr for every record. `.value` is checked first for that reason.
    """
    if value is None:
        return None
    raw = getattr(value, "value", value)
    text = str(raw).strip()
    return text if text in _VALID_BASE_STATES else None


def _runner_count(base_state: str) -> int:
    return sum(1 for ch in base_state if ch != "-")


def _sum_counts(mapping: Any) -> int:
    """Total across a `{pitcher_id: count}` map, tolerating JSON key drift."""
    if not isinstance(mapping, Mapping):
        return 0
    total = 0
    for raw in mapping.values():
        number = _as_int(raw)
        if number is not None and number > 0:
            total += number
    return total


def _lookup_by_id(mapping: Any, pitcher_id: Any) -> int | None:
    """Look up a pitcher id whose key may be an int or a str.

    A `LiveSituation` built in-process keys these maps by int; the same map
    read back from JSON keys them by str. Checking one shape only would report
    a fresh pitcher (0 pitches) for every record that had been serialised --
    which reads as a plausible number rather than as a miss.
    """
    if not isinstance(mapping, Mapping) or pitcher_id is None:
        return None
    if pitcher_id in mapping:
        return _as_int(mapping[pitcher_id])
    key = str(pitcher_id)
    if key in mapping:
        return _as_int(mapping[key])
    return None


def _invalid(reason: str) -> dict[str, Any]:
    return {
        "shape_version": SHAPE_VERSION,
        "sport": "mlb",
        "valid": False,
        "reason": reason,
        "bucket": _UNKNOWN_BUCKET,
    }


def mlb_game_shape(situation: Any) -> dict[str, Any]:
    """Flat, JSON-safe game shape for one MLB live situation.

    Accepts a `LiveSituation`, a mapping with the same field names, or anything
    else duck-typed alike. Never raises.
    """
    if situation is None:
        return _invalid("situation_absent")

    inning = _as_int(_get(situation, "inning"))
    outs = _as_int(_get(situation, "outs"))
    top_raw = _get(situation, "top")
    base_state = _base_state_text(_get(situation, "bases"))
    away_score = _as_int(_get(situation, "away_score"))
    home_score = _as_int(_get(situation, "home_score"))

    # Each of these is required to place the situation in the state space at
    # all. A missing one is reported, never defaulted -- a defaulted `outs=0`
    # would file the record in a real cell it does not belong to.
    if inning is None or inning < 1:
        return _invalid("inning_absent_or_invalid")
    if outs is None or not (0 <= outs <= 2):
        return _invalid("outs_absent_or_invalid")
    if base_state is None:
        return _invalid("base_state_unrecognised")
    if top_raw is None:
        return _invalid("half_absent")
    if away_score is None or home_score is None:
        return _invalid("score_absent")

    top = bool(top_raw)
    half = "top" if top else "bottom"
    batting_side = "away" if top else "home"

    # Outs recorded so far. Each completed inning is 6; a bottom half means the
    # top's 3 are already in the book.
    outs_recorded = (inning - 1) * 6 + (0 if top else 3) + outs
    extra_innings = outs_recorded >= _OUTS_IN_REGULATION

    pitch_counts = _get(situation, "pitcher_pitch_count")
    batters_faced = _get(situation, "pitcher_batters_faced")
    entered_mid = _get(situation, "pitcher_entered_mid_inning")

    # The pitcher currently on the mound is the FIELDING side's pitcher, which
    # is the opposite of who is batting.
    current_pitcher_id = _get(situation, "home_pitcher_id") if top else _get(situation, "away_pitcher_id")

    current_pitches = _lookup_by_id(pitch_counts, current_pitcher_id)
    current_batters_faced = _lookup_by_id(batters_faced, current_pitcher_id)

    # Times through the order: the classic TTO penalty variable. Batter 1-9 of a
    # pitcher's night is TTO 1, 10-18 is TTO 2, and so on. `None` when the
    # pitcher is unidentified -- not 1, which would assert a fresh starter.
    times_through_order = None
    if current_batters_faced is not None and current_batters_faced >= 0:
        times_through_order = current_batters_faced // 9 + 1

    pitches_thrown = _sum_counts(pitch_counts)
    # Pace, in the only currency baseball has: work per out retired. A grinding,
    # high-traffic game and a brisk one differ here by a factor of ~2, and the
    # difference is exactly the kind of game shape a run-scoring model can be
    # systematically wrong about.
    pitches_per_out = round(pitches_thrown / outs_recorded, 3) if outs_recorded > 0 else None

    pitchers_used = len(pitch_counts) if isinstance(pitch_counts, Mapping) else 0

    entered_mid_inning = None
    if isinstance(entered_mid, Mapping) and current_pitcher_id is not None:
        flag = _lookup_by_id(entered_mid, current_pitcher_id)
        if flag is None:
            # `_lookup_by_id` coerces to int; a real absence stays None so a
            # missing entry is not reported as "started the inning".
            entered_mid_inning = None
        else:
            entered_mid_inning = bool(flag)

    balls = _as_int(_get(situation, "balls")) or 0
    strikes = _as_int(_get(situation, "strikes")) or 0

    home_margin = home_score - away_score

    shape: dict[str, Any] = {
        "shape_version": SHAPE_VERSION,
        "sport": "mlb",
        "valid": True,
        # --- raw state: the 24-cell run-expectancy grid ---
        "inning": inning,
        "half": half,
        "outs": outs,
        "bases": base_state,
        "base_out_state": f"{base_state}|{outs}",
        "runners_on": _runner_count(base_state),
        "in_scoring_position": base_state[1] != "-" or base_state[2] != "-",
        "batting_side": batting_side,
        # --- score, oriented to match `model_home_win_prob` ---
        "away_score": away_score,
        "home_score": home_score,
        "home_margin": home_margin,
        # --- progress ---
        "outs_recorded": outs_recorded,
        "outs_remaining_regulation": max(0, _OUTS_IN_REGULATION - outs_recorded),
        "game_pct_complete": round(min(1.0, outs_recorded / _OUTS_IN_REGULATION), 4),
        "extra_innings": extra_innings,
        # --- pace and pitcher workload: the "game shape" half ---
        "pitches_thrown": pitches_thrown,
        "pitches_per_out": pitches_per_out,
        "pitchers_used": pitchers_used,
        "current_pitcher_pitch_count": current_pitches,
        "current_pitcher_batters_faced": current_batters_faced,
        "times_through_order": times_through_order,
        "current_pitcher_entered_mid_inning": entered_mid_inning,
        "current_pa_pitch_count": _as_int(_get(situation, "current_pa_pitch_count")) or 0,
        "balls": balls,
        "strikes": strikes,
        "count": f"{balls}-{strikes}",
    }
    shape["bucket"] = mlb_shape_bucket(shape)
    return shape


def mlb_phase(shape: Any) -> str:
    """Coarse progress phase. `"unknown"` when the shape did not parse."""
    if not isinstance(shape, Mapping) or not shape.get("valid"):
        return _UNKNOWN_BUCKET
    outs_recorded = _as_int(shape.get("outs_recorded"))
    if outs_recorded is None:
        return _UNKNOWN_BUCKET
    if outs_recorded >= _OUTS_IN_REGULATION:
        return "extras"
    if outs_recorded < 18:
        return "early"
    if outs_recorded < 36:
        return "middle"
    return "late"


def mlb_margin_band(shape: Any) -> str:
    """Coarse score-gap band, sign-free.

    Sign is dropped ON PURPOSE. The question a calibration cell answers is "how
    wrong is the model in a two-run game", and home/away asymmetry is a
    SEPARATE hypothesis that `home_margin` (kept signed on the record) can test
    without doubling the cell count here.
    """
    if not isinstance(shape, Mapping) or not shape.get("valid"):
        return _UNKNOWN_BUCKET
    margin = _as_int(shape.get("home_margin"))
    if margin is None:
        return _UNKNOWN_BUCKET
    gap = abs(margin)
    if gap == 0:
        return "tied"
    if gap <= 2:
        return "close"
    if gap <= 4:
        return "moderate"
    return "blowout"


def mlb_shape_bucket(shape: Any) -> str:
    """The bucket a state-conditional score is aggregated over.

    **Deliberately coarse: at most 17 labels** (4 phases x 4 margin bands, plus
    `unknown`). See this module's header -- at 120 sims per estimate, a finer
    partition produces cells that cannot be distinguished from noise, and the
    fine fields on the record make a later re-cut possible without re-capture.
    """
    phase = mlb_phase(shape)
    if phase == _UNKNOWN_BUCKET:
        return _UNKNOWN_BUCKET
    band = mlb_margin_band(shape)
    if band == _UNKNOWN_BUCKET:
        return _UNKNOWN_BUCKET
    return f"{phase}|{band}"


# ---------------------------------------------------------------------------
# BASKETBALL (WNBA / NBA)
# ---------------------------------------------------------------------------
#
# WHAT IS AVAILABLE, MEASURED -- and it is a different situation from MLB's.
# MLB's state vector existed in full and was merely discarded. Basketball's
# does not exist: `live_state` on the WNBA card context carries
# `period`, `clock`, `home_pts`, `away_pts`, `in_progress`, `final` and a
# per-quarter `periods` array, and the team objects carry ONLY branding
# (`abbr`, `logo`, `name`, colours).
# `[measured 2026-08-16, data/live/wnba_cards_context_2026-06-05.json,
#   a real in-progress game: period 4, clock "7:43", 84-83]`
#
# **THERE IS NO POSSESSION PACE HERE, AND THIS MODULE WILL NOT INVENT ONE.**
# Possessions need FGA, TOV, OREB and FTA. None of the four appears anywhere in
# any live basketball artifact measured, and `basketball_props_features`'
# column map is box-score totals with no pace column either. So the pace field
# below is `points_per_minute` -- SCORING pace, which is a real and useful game
# shape signal and is NOT the same statistic as possessions per 40. Naming it
# `pace` would let a reader join it to a possession-pace prior and get a
# silently wrong answer. If box stats are ever captured live, add possessions
# as a NEW field; do not redefine this one.
#
# **PERIOD/CLOCK PRECEDENCE IS NOT ARBITRARY.** `live_state` first, then
# `status` -- the same order as `wnba/cards.py:1048-1049`, which records the
# reason: an in-progress game measured 2026-07-30 had a `live_state` carrying
# only `{away_pts, final, home_pts, in_progress, status}` with no period or
# clock at all. Reading either source alone loses real live games.

_BASKETBALL_RULES: dict[str, dict[str, float]] = {
    # WNBA quarters are 10 minutes (regulation 40), NOT NBA's 12 (regulation
    # 48). A shared basketball function that hardcoded either one would be
    # silently wrong for the other sport, which is why this is a table.
    "wnba": {"quarter_minutes": 10.0, "ot_minutes": 5.0, "regulation_periods": 4.0},
    "nba": {"quarter_minutes": 12.0, "ot_minutes": 5.0, "regulation_periods": 4.0},
}


def basketball_elapsed_minutes(
    period: Any,
    clock: Any,
    *,
    quarter_minutes: float = 10.0,
    ot_minutes: float = 5.0,
    regulation_periods: int = 4,
) -> float | None:
    """Minutes elapsed since tip-off. Can exceed regulation in OT.

    **This is deliberately byte-for-byte equivalent to
    `wnba/cards.py:_wnba_elapsed_minutes` for WNBA parameters**, including its
    strict clock parsing (exactly `M:SS`, integer parts, seconds 0-58). That
    function's own comment says it was relocated once precisely so two copies
    would not drift apart, so this one is pinned to it by
    `test_basketball_elapsed_minutes_agrees_with_the_wnba_implementation`.

    Being *more* permissive here would BE the drift -- one caller would accept
    a clock the other rejects, and the disagreement would surface as a
    population difference in a scoring cell rather than as an error. The
    consolidation (having `cards.py` delegate here) needs that file, which is
    held by another lane; until then the test is the guard.
    """
    try:
        period_int = int(period)
    except (TypeError, ValueError):
        return None
    if period_int < 1:
        return None
    parts = str(clock or "").strip().split(":")
    if len(parts) != 2:
        return None
    try:
        minutes_left = int(parts[0])
        seconds_left = int(parts[1])
    except ValueError:
        return None
    if minutes_left < 0 or not (0 <= seconds_left < 60):
        return None
    reg = int(regulation_periods)
    period_length = float(quarter_minutes) if period_int <= reg else float(ot_minutes)
    remaining_in_period = max(0.0, min(period_length, minutes_left + seconds_left / 60.0))
    elapsed_in_period = period_length - remaining_in_period
    if period_int <= reg:
        prior_minutes = (period_int - 1) * float(quarter_minutes)
    else:
        prior_minutes = reg * float(quarter_minutes) + (period_int - reg - 1) * float(ot_minutes)
    return prior_minutes + elapsed_in_period


def _period_rows(live_state: Any) -> list[dict[str, Any]]:
    rows = _get(live_state, "periods")
    out: list[dict[str, Any]] = []
    if not isinstance(rows, (list, tuple)):
        return out
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        num = _as_int(row.get("period"))
        home = _as_float(row.get("home"))
        away = _as_float(row.get("away"))
        if num is None or home is None or away is None:
            continue
        out.append({"period": num, "home": home, "away": away})
    out.sort(key=lambda r: r["period"])
    return out


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def basketball_game_shape(live_state: Any, *, sport: str = "wnba", status: Any = None) -> dict[str, Any]:
    """Flat, JSON-safe game shape for one live basketball game. Never raises.

    `live_state` is the card context's `live_state` block; `status` is the
    sibling `status` block, consulted only for period/clock (see the precedence
    note above).
    """
    slug = str(sport or "").strip().lower()
    rules = _BASKETBALL_RULES.get(slug)
    if rules is None:
        return {
            "shape_version": SHAPE_VERSION,
            "sport": slug or "unknown",
            "valid": False,
            "reason": "sport_not_supported",
            "bucket": _UNKNOWN_BUCKET,
        }

    def invalid(reason: str) -> dict[str, Any]:
        return {
            "shape_version": SHAPE_VERSION,
            "sport": slug,
            "valid": False,
            "reason": reason,
            "bucket": _UNKNOWN_BUCKET,
        }

    if live_state is None and status is None:
        return invalid("live_state_absent")

    period = _get(live_state, "period")
    if period is None:
        period = _get(status, "period")
    clock = _get(live_state, "clock")
    if clock is None:
        clock = _get(status, "clock")

    home_pts = _as_float(_get(live_state, "home_pts"))
    away_pts = _as_float(_get(live_state, "away_pts"))

    period_int = _as_int(period)
    if period_int is None or period_int < 1:
        return invalid("period_absent_or_invalid")
    if home_pts is None or away_pts is None:
        return invalid("score_absent")

    reg_periods = int(rules["regulation_periods"])
    quarter_minutes = rules["quarter_minutes"]
    regulation_minutes = quarter_minutes * reg_periods

    elapsed = basketball_elapsed_minutes(
        period_int,
        clock,
        quarter_minutes=quarter_minutes,
        ot_minutes=rules["ot_minutes"],
        regulation_periods=reg_periods,
    )
    # A clock can legitimately be missing on a live game (measured 2026-07-30).
    # That costs the pace fields and nothing else -- the score, margin and
    # period are still real, so the record stays VALID with a stated gap rather
    # than being thrown away.
    clock_parsed = elapsed is not None

    total_points = home_pts + away_pts
    home_margin = home_pts - away_pts

    points_per_minute = None
    if elapsed is not None and elapsed > 0:
        points_per_minute = round(total_points / elapsed, 3)

    rows = _period_rows(live_state)
    completed = [r for r in rows if r["period"] < period_int]
    current_row = next((r for r in rows if r["period"] == period_int), None)
    largest_swing = None
    if completed:
        largest_swing = max(abs(r["home"] - r["away"]) for r in completed)

    shape: dict[str, Any] = {
        "shape_version": SHAPE_VERSION,
        "sport": slug,
        "valid": True,
        # --- clock state ---
        "period": period_int,
        "clock": str(clock or "").strip() or None,
        "clock_parsed": clock_parsed,
        "overtime": period_int > reg_periods,
        # --- progress ---
        "elapsed_minutes": round(elapsed, 4) if elapsed is not None else None,
        "minutes_remaining_regulation": (
            round(max(0.0, regulation_minutes - elapsed), 4) if elapsed is not None else None
        ),
        "game_pct_complete": (
            round(min(1.0, elapsed / regulation_minutes), 4) if elapsed is not None else None
        ),
        # --- score, oriented to match a home win probability ---
        "home_pts": home_pts,
        "away_pts": away_pts,
        "home_margin": home_margin,
        "total_points": total_points,
        # --- pace: SCORING pace. NOT possessions. See the header note. ---
        "points_per_minute": points_per_minute,
        "possession_pace_available": False,
        # --- game shape across periods: run detection ---
        "periods_completed": len(completed),
        "period_scores": rows,
        "largest_completed_period_swing": largest_swing,
        "current_period_points": (
            (current_row["home"] + current_row["away"]) if current_row else None
        ),
        # --- lifecycle ---
        "in_progress": bool(_get(live_state, "in_progress") or _get(status, "in_progress")),
        "final": bool(_get(live_state, "final") or _get(status, "final")),
    }
    shape["bucket"] = basketball_shape_bucket(shape)
    return shape


def wnba_game_shape(live_state: Any, *, status: Any = None) -> dict[str, Any]:
    """WNBA convenience wrapper -- 10-minute quarters, 40-minute regulation."""
    return basketball_game_shape(live_state, sport="wnba", status=status)


def basketball_phase(shape: Any) -> str:
    if not isinstance(shape, Mapping) or not shape.get("valid"):
        return _UNKNOWN_BUCKET
    period = _as_int(shape.get("period"))
    if period is None or period < 1:
        return _UNKNOWN_BUCKET
    if shape.get("overtime"):
        return "overtime"
    if period <= 2:
        return "first_half"
    if period == 3:
        return "third_quarter"
    return "fourth_quarter"


def basketball_margin_band(shape: Any) -> str:
    """Coarse score-gap band, sign-free.

    **The thresholds are NOT MLB's, deliberately.** A two-run baseball game and
    a two-point basketball game are not comparable states: basketball margins
    are an order of magnitude larger and a 5-point gap late is the canonical
    "clutch" boundary. Reusing the baseball bands here would put ~every live
    basketball game in one cell and measure nothing.
    """
    if not isinstance(shape, Mapping) or not shape.get("valid"):
        return _UNKNOWN_BUCKET
    margin = shape.get("home_margin")
    value = _as_float(margin)
    if value is None:
        return _UNKNOWN_BUCKET
    gap = abs(value)
    if gap <= 5:
        return "close"
    if gap <= 10:
        return "moderate"
    if gap <= 19:
        return "comfortable"
    return "blowout"


def basketball_shape_bucket(shape: Any) -> str:
    """At most 17 labels (4 phases x 4 margin bands, plus `unknown`).

    Same coarseness bound and same reason as MLB: production basketball
    `n_sims` is 100, so a finer partition produces cells indistinguishable from
    noise. The fine fields stay on the record for a later re-cut.
    """
    phase = basketball_phase(shape)
    if phase == _UNKNOWN_BUCKET:
        return _UNKNOWN_BUCKET
    band = basketball_margin_band(shape)
    if band == _UNKNOWN_BUCKET:
        return _UNKNOWN_BUCKET
    return f"{phase}|{band}"


# ---------------------------------------------------------------------------
# FOOTBALL (NFL / NCAAF)
# ---------------------------------------------------------------------------
#
# WHAT IS CAPTURED TODAY, MEASURED -- and it is a THIRD situation, different
# again from MLB's and basketball's.
#
# `nfl/live_game_state.py:_state_from_event` builds `period`, `clock`
# (ESPN's `displayClock`, "8:05"), `away_pts`, `home_pts`, `in_progress`,
# `final` -- and writes `period`/`clock` onto the same `live_state` block the
# WNBA path uses. So the input contract is shared. `[from-code]`
#
# **DOWN, DISTANCE, FIELD POSITION AND POSSESSION ARE IN THE FETCHED PAYLOAD AND
# ARE NEVER READ.** `_fetch_scoreboard` returns the whole ESPN scoreboard JSON,
# whose events carry a `situation` block; nothing in `nfl/`, `ncaaf/` or
# `football/` reads it -- the only `down` references in the tree are the sim
# engine's internal `play_state` and the historical loaders. This is the same
# shape as MLB: **discarded, not absent.** `situation=` below accepts it so the
# capture change upstream is a one-liner that needs no edit here, and every
# record states `situation_available` either way.
#
# **`pace_features.py` IS NOT A LIVE PACE SOURCE.** It reads
# `game["pace_features"]` -- a season-level secs/play feature from the rbsdm
# ingestion, used by the pregame drive priors. Joining it to a live record as
# though it were in-game tempo would be a silent category error. As with
# basketball, the live statistic here is SCORING pace.
#
# **NCAAF OVERTIME IS NOT TIMED.** College OT is alternating possessions from
# the 25 with no game clock, so elapsed minutes is UNDEFINED there rather than
# computable. This module returns `None` for it and keeps the record valid,
# rather than extrapolating a 15-minute period that does not exist. NFL regular
# season OT is 10 minutes.
#
# **NCAAF HAS NO LIVE-STATE PRODUCER AT ALL** (no `live_game_state` analog in
# `syndicate/features/ncaaf/`), and its season opens 2026-08-29, so nothing here
# can be verified against a live college game today. The rules entry exists so
# the contract is ready; that is not the same as coverage.

_FOOTBALL_RULES: dict[str, dict[str, Any]] = {
    "nfl": {
        "quarter_minutes": 15.0,
        "ot_minutes": 10.0,      # regular season; playoff OT is 15 and is not modelled
        "regulation_periods": 4,
        "ot_timed": True,
    },
    "ncaaf": {
        "quarter_minutes": 15.0,
        "ot_minutes": None,      # untimed alternating possessions -- see above
        "regulation_periods": 4,
        "ot_timed": False,
    },
}

# The scoring unit football margins are actually read in: a touchdown plus a
# two-point conversion. "Two scores down" is the sport's own coarse state
# description, so the bands below are built from it rather than from a
# points grid borrowed off another sport.
_FOOTBALL_MAX_SCORE = 8


def _football_situation(situation: Any) -> dict[str, Any]:
    """Normalise ESPN's `situation` block if a caller supplies one."""
    if not isinstance(situation, Mapping):
        return {"situation_available": False}
    down = _as_int(situation.get("down"))
    distance = _as_int(situation.get("distance"))
    yardline = _as_int(situation.get("yardLine") if situation.get("yardLine") is not None else situation.get("yard_line"))
    possession = situation.get("possession") if situation.get("possession") is not None else situation.get("possession_team")
    out: dict[str, Any] = {
        "situation_available": True,
        "down": down if (down is not None and 1 <= down <= 4) else None,
        "distance": distance if (distance is not None and distance >= 0) else None,
        "yard_line": yardline if (yardline is not None and 0 <= yardline <= 100) else None,
        "possession_team": str(possession).strip() if possession is not None and str(possession).strip() else None,
    }
    # ESPN's `yardLine` is distance-to-opponent-goal on this feed, so <=20 is
    # the red zone. Emitted only when the yard line parsed -- an absent yard
    # line must not read as "not in the red zone".
    out["red_zone"] = (out["yard_line"] is not None and out["yard_line"] <= 20) or None
    if out["yard_line"] is None:
        out["red_zone"] = None
    return out


def football_game_shape(
    live_state: Any,
    *,
    sport: str = "nfl",
    status: Any = None,
    situation: Any = None,
) -> dict[str, Any]:
    """Flat, JSON-safe game shape for one live football game. Never raises."""
    slug = str(sport or "").strip().lower()
    rules = _FOOTBALL_RULES.get(slug)
    if rules is None:
        return {
            "shape_version": SHAPE_VERSION,
            "sport": slug or "unknown",
            "valid": False,
            "reason": "sport_not_supported",
            "bucket": _UNKNOWN_BUCKET,
        }

    def invalid(reason: str) -> dict[str, Any]:
        return {
            "shape_version": SHAPE_VERSION,
            "sport": slug,
            "valid": False,
            "reason": reason,
            "bucket": _UNKNOWN_BUCKET,
        }

    if live_state is None and status is None:
        return invalid("live_state_absent")

    period = _get(live_state, "period")
    if period is None:
        period = _get(status, "period")
    clock = _get(live_state, "clock")
    if clock is None:
        clock = _get(status, "clock")

    period_int = _as_int(period)
    if period_int is None or period_int < 1:
        return invalid("period_absent_or_invalid")

    home_pts = _as_float(_get(live_state, "home_pts"))
    away_pts = _as_float(_get(live_state, "away_pts"))
    if home_pts is None or away_pts is None:
        return invalid("score_absent")

    reg_periods = int(rules["regulation_periods"])
    quarter_minutes = float(rules["quarter_minutes"])
    regulation_minutes = quarter_minutes * reg_periods
    overtime = period_int > reg_periods

    # NCAAF OT has no clock, so there is nothing to compute and nothing is
    # invented. NFL OT is timed and uses its own period length.
    if overtime and not rules["ot_timed"]:
        elapsed = None
    else:
        elapsed = basketball_elapsed_minutes(
            period_int,
            clock,
            quarter_minutes=quarter_minutes,
            ot_minutes=float(rules["ot_minutes"] or quarter_minutes),
            regulation_periods=reg_periods,
        )

    total_points = home_pts + away_pts
    home_margin = home_pts - away_pts
    points_per_minute = None
    if elapsed is not None and elapsed > 0:
        points_per_minute = round(total_points / elapsed, 3)

    shape: dict[str, Any] = {
        "shape_version": SHAPE_VERSION,
        "sport": slug,
        "valid": True,
        "period": period_int,
        "clock": str(clock or "").strip() or None,
        "clock_parsed": elapsed is not None,
        "overtime": overtime,
        "overtime_is_timed": bool(rules["ot_timed"]),
        "elapsed_minutes": round(elapsed, 4) if elapsed is not None else None,
        "minutes_remaining_regulation": (
            round(max(0.0, regulation_minutes - elapsed), 4) if elapsed is not None else None
        ),
        "game_pct_complete": (
            round(min(1.0, elapsed / regulation_minutes), 4) if elapsed is not None else None
        ),
        "home_pts": home_pts,
        "away_pts": away_pts,
        "home_margin": home_margin,
        "total_points": total_points,
        # Football's own coarse reading of a margin: how many scores behind.
        "margin_in_scores": int(math.ceil(abs(home_margin) / _FOOTBALL_MAX_SCORE)) if home_margin else 0,
        # SCORING pace. Football's other "pace" (secs/play) is a SEASON feature
        # in `pace_features.py`, not an in-game measurement -- see header.
        "points_per_minute": points_per_minute,
        "possession_pace_available": False,
        "in_progress": bool(_get(live_state, "in_progress") or _get(status, "in_progress")),
        "final": bool(_get(live_state, "final") or _get(status, "final")),
    }
    shape.update(_football_situation(situation))
    shape["bucket"] = football_shape_bucket(shape)
    return shape


def football_phase(shape: Any) -> str:
    if not isinstance(shape, Mapping) or not shape.get("valid"):
        return _UNKNOWN_BUCKET
    period = _as_int(shape.get("period"))
    if period is None or period < 1:
        return _UNKNOWN_BUCKET
    if shape.get("overtime"):
        return "overtime"
    if period <= 2:
        return "first_half"
    if period == 3:
        return "third_quarter"
    return "fourth_quarter"


def football_margin_band(shape: Any) -> str:
    """Bands in football's own unit: how many scores separate the teams.

    **A third distinct scale, and deliberately so.** Baseball bands are runs,
    basketball's are points, football's are SCORES -- an 8-point football game
    and an 8-point basketball game are completely different states (one
    possession vs. three). Reusing either of the other two here would mis-bucket
    almost every game.
    """
    if not isinstance(shape, Mapping) or not shape.get("valid"):
        return _UNKNOWN_BUCKET
    margin = _as_float(shape.get("home_margin"))
    if margin is None:
        return _UNKNOWN_BUCKET
    gap = abs(margin)
    if gap <= _FOOTBALL_MAX_SCORE:
        return "one_score"
    if gap <= 2 * _FOOTBALL_MAX_SCORE:
        return "two_score"
    if gap <= 3 * _FOOTBALL_MAX_SCORE:
        return "three_score"
    return "blowout"


def football_shape_bucket(shape: Any) -> str:
    """At most 17 labels (4 phases x 4 margin bands, plus `unknown`)."""
    phase = football_phase(shape)
    if phase == _UNKNOWN_BUCKET:
        return _UNKNOWN_BUCKET
    band = football_margin_band(shape)
    if band == _UNKNOWN_BUCKET:
        return _UNKNOWN_BUCKET
    return f"{phase}|{band}"


# ---------------------------------------------------------------------------
# SOCCER
# ---------------------------------------------------------------------------
#
# **SOCCER HAS THE RICHEST LIVE STATE OF ANY SPORT HERE, AND IT IS THE ONLY ONE
# THAT CARRIES REAL IN-GAME EVENTS.** Measured on a populated record
# (`data/soccer_source/mls/api/live_state/live_state_2026-07-22.json`, CF
# Montréal v Toronto FC): `half`, `clock_remaining`, `score_home`/`score_away`,
# `home_red_cards`/`away_red_cards`, `home_shots_so_far`,
# `home_shots_on_target_so_far`, `home_corners_so_far` and their away twins.
#
# So soccer is the one sport where a genuine TEMPO statistic is derivable --
# shots per minute is an event rate, not a scoring proxy. Basketball and
# football could only offer points per minute because their event counts are
# not captured. `shot_dominance` is the other thing only soccer can say: which
# side is actually on top, which routinely disagrees with the scoreline and is
# exactly the "game shape" a 0-0 hides.
#
# **THE REFUSAL THAT MATTERS MOST IN THIS MODULE, AND IT IS UNIQUE TO SOCCER.**
# The same `live_state` record embeds a `projection` block (`home_win_probability`,
# `projected_final_total`, ...) and a `goal_windows` block. **Those are MODEL
# OUTPUT and they are deliberately excluded from the shape.** Game shape is the
# conditioning variable a model's error is scored AGAINST; folding the model's
# own prediction into it makes the analysis circular -- you would be asking "is
# the model wrong when the model says X", which cannot separate a bad model from
# a bad state. No other sport's live_state carries its projection inline, so
# this trap exists here and nowhere else. If a caller wants the projection, it
# is still on the record they passed in; it just is not shape.
#
# **KNOWN BLIND SPOT, STATED RATHER THAN PAPERED OVER.**
# `_current_half_and_clock_remaining` clamps `clock_remaining` at 0.0 and never
# returns a half above 2, so second-half stoppage time is invisible: 90' and
# 95' both read as `match_minute == 90.0`. `clock_saturated` flags exactly that
# case so a reader can exclude it rather than mistake a stoppage-time state for
# a regulation one. Fixing it needs the ingestion contract to carry the raw
# match clock, which is upstream of this module.
#
# NOT AVAILABLE and NOT invented: possession share and xG. Neither appears in
# the payload. Shots on target is captured and is not a substitute for either.

_SOCCER_HALF_SECONDS = 2700.0
_SOCCER_REGULATION_SECONDS = 2 * _SOCCER_HALF_SECONDS
# Final 15 minutes of the second half -- the window where game state starts
# driving behaviour (chasing, closing out) rather than merely describing it.
_SOCCER_CLOSING_SECONDS = 900.0


def soccer_game_shape(live_state: Any) -> dict[str, Any]:
    """Flat, JSON-safe game shape for one live soccer match. Never raises."""

    def invalid(reason: str) -> dict[str, Any]:
        return {
            "shape_version": SHAPE_VERSION,
            "sport": "soccer",
            "valid": False,
            "reason": reason,
            "bucket": _UNKNOWN_BUCKET,
        }

    if live_state is None:
        return invalid("live_state_absent")

    half = _as_int(_get(live_state, "half"))
    if half is None or half < 1:
        return invalid("half_absent_or_invalid")
    # The producer only ever emits 1 or 2; anything else means the contract
    # changed and this module should be re-read rather than guess at it.
    if half > 2:
        return invalid("half_out_of_contract")

    clock_remaining = _as_float(_get(live_state, "clock_remaining"))
    if clock_remaining is None or clock_remaining < 0:
        return invalid("clock_remaining_absent_or_invalid")

    score_home = _as_float(_get(live_state, "score_home"))
    score_away = _as_float(_get(live_state, "score_away"))
    if score_home is None or score_away is None:
        return invalid("score_absent")

    elapsed_seconds = half * _SOCCER_HALF_SECONDS - clock_remaining
    elapsed_seconds = max(0.0, min(_SOCCER_REGULATION_SECONDS, elapsed_seconds))
    match_minute = round(elapsed_seconds / 60.0, 3)
    # See the header: 90' and 95' are indistinguishable once the clock clamps.
    clock_saturated = half == 2 and clock_remaining <= 0.0

    def side(name: str) -> float:
        return _as_float(_get(live_state, name)) or 0.0

    home_shots = side("home_shots_so_far")
    away_shots = side("away_shots_so_far")
    home_sot = side("home_shots_on_target_so_far")
    away_sot = side("away_shots_on_target_so_far")
    home_corners = side("home_corners_so_far")
    away_corners = side("away_corners_so_far")
    home_reds = side("home_red_cards")
    away_reds = side("away_red_cards")

    total_shots = home_shots + away_shots
    total_sot = home_sot + away_sot

    # Shares are None on a zero denominator rather than 0.5 -- "nobody has shot
    # yet" and "both sides have shot equally" are different states, and
    # collapsing them would file every goalless opening into the balanced cell.
    shot_dominance = round(home_shots / total_shots, 4) if total_shots > 0 else None
    sot_dominance = round(home_sot / total_sot, 4) if total_sot > 0 else None

    # A real EVENT RATE, which only soccer can offer here.
    shots_per_minute = round(total_shots / match_minute, 4) if match_minute > 0 else None

    shape: dict[str, Any] = {
        "shape_version": SHAPE_VERSION,
        "sport": "soccer",
        "valid": True,
        # --- clock ---
        "half": half,
        "clock_remaining_seconds": clock_remaining,
        "match_minute": match_minute,
        "minutes_remaining_regulation": round(
            max(0.0, (_SOCCER_REGULATION_SECONDS - elapsed_seconds) / 60.0), 3
        ),
        "game_pct_complete": round(elapsed_seconds / _SOCCER_REGULATION_SECONDS, 4),
        "clock_saturated": clock_saturated,
        # --- score, oriented home-positive ---
        "score_home": score_home,
        "score_away": score_away,
        "home_margin": score_home - score_away,
        "total_goals": score_home + score_away,
        # --- EVENTS: the half no other sport in this module has ---
        "home_red_cards": home_reds,
        "away_red_cards": away_reds,
        "red_card_diff": home_reds - away_reds,
        "home_shots": home_shots,
        "away_shots": away_shots,
        "home_shots_on_target": home_sot,
        "away_shots_on_target": away_sot,
        "home_corners": home_corners,
        "away_corners": away_corners,
        "total_shots": total_shots,
        "total_shots_on_target": total_sot,
        # --- shape: who is actually on top, and how fast ---
        "shot_dominance": shot_dominance,
        "sot_dominance": sot_dominance,
        "shots_per_minute": shots_per_minute,
        # Stated so a consumer never has to infer it from absence.
        "possession_available": False,
        "xg_available": False,
    }
    shape["bucket"] = soccer_shape_bucket(shape)
    return shape


def soccer_phase(shape: Any) -> str:
    if not isinstance(shape, Mapping) or not shape.get("valid"):
        return _UNKNOWN_BUCKET
    half = _as_int(shape.get("half"))
    if half is None:
        return _UNKNOWN_BUCKET
    if half == 1:
        return "first_half"
    remaining = _as_float(shape.get("clock_remaining_seconds"))
    if remaining is not None and remaining <= _SOCCER_CLOSING_SECONDS:
        return "closing"
    return "second_half"


def soccer_margin_band(shape: Any) -> str:
    """Bands in GOALS -- a fourth distinct scale.

    A two-goal soccer lead is closer to a three-score football lead than to a
    two-point basketball one. Goals are scarce enough that the bands have to be
    this tight or every match lands in one cell.
    """
    if not isinstance(shape, Mapping) or not shape.get("valid"):
        return _UNKNOWN_BUCKET
    margin = _as_float(shape.get("home_margin"))
    if margin is None:
        return _UNKNOWN_BUCKET
    gap = abs(margin)
    if gap == 0:
        return "level"
    if gap == 1:
        return "one_goal"
    if gap == 2:
        return "two_goal"
    return "comfortable"


def soccer_shape_bucket(shape: Any) -> str:
    """At most 13 labels (3 phases x 4 margin bands, plus `unknown`).

    `red_card_diff` is deliberately NOT in the bucket even though it is one of
    the strongest state variables in the sport -- it would double the space.
    It stays on the record as the obvious first re-cut once a sample exists.
    """
    phase = soccer_phase(shape)
    if phase == _UNKNOWN_BUCKET:
        return _UNKNOWN_BUCKET
    band = soccer_margin_band(shape)
    if band == _UNKNOWN_BUCKET:
        return _UNKNOWN_BUCKET
    return f"{phase}|{band}"


def bucket_distribution(shapes: Any) -> dict[str, int]:
    """Count shapes per bucket. The denominator half of any rate built on these.

    Invalid shapes are counted under `"unknown"` rather than dropped: a bucket
    table that silently omits its failures reads as full coverage.
    """
    counts: dict[str, int] = {}
    if not isinstance(shapes, (list, tuple)):
        return counts
    for item in shapes:
        if isinstance(item, Mapping):
            label = str(item.get("bucket") or _UNKNOWN_BUCKET)
        else:
            label = _UNKNOWN_BUCKET
        counts[label] = counts.get(label, 0) + 1
    return counts
