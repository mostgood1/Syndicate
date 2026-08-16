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

NEVER RAISES. An unparseable situation returns `valid: False` with a `reason`,
mirroring `model_scoring`'s philosophy that a bad record should cost one
observation rather than the whole batch. **An invalid shape buckets to
`"unknown"` and never to a real label** -- an unknown that defaults onto a
permissive branch turns a failed parse into a confident wrong segment.
"""

from __future__ import annotations

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
