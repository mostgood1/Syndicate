"""NCAAF live re-sim: the leader eases off in a blowout (todo #852, lane ncaaf-live-endgame-surplus). DEFAULT OFF.

WHAT IS WRONG WITHOUT IT. Resumed from a live state, smartsim2 plays the rest of an NCAAF game at the same scoring rate
whatever the margin. A team ahead by 28 with ten minutes left keeps scoring as it did at 0-0, and real leaders do not.
Measured (`.syndicate/findings_2026-11-19_ncaaf_live_endgame_surplus.md`):
- On the live ledger's finals at 75-95% of game time, engine minus actual rest-of-game is +2.12 (se 0.94) at a 17-24
  margin and +2.86 (0.96) at 25+, against -0.30 at one score.
- Resumed at real 2024 Q4 states, the 17+ surplus is the LEADER's (+2.2 points at Q4 15:00). The trailer is right.
- The late mean cancels against one-score games, which run under, so the cost shows in the calibration slope, not the
  mean.

WHAT THIS IS. Not new mechanism code. #686 already put a leader-only damping in the engine
(`play_simulator.blowout_damping_factor`, `CalibrationProfile.blowout_damping_*`, default strength 0.0 = an exact no-op).
It scales the possessing team's touchdown / field-goal / explosive weights when that team leads by more than a
threshold, ramping with the lead and from the start of Q3 to the end of Q4. This module arms it for the NCAAF LIVE
re-sim only, at the values fitted for it. Pregame and every other caller are untouched.

HOW IT REACHES PRODUCTION. `ncaaf.live_resim.resim_live_game` resolves its profile here when the caller passes none.
Every production caller passes none: the tick's `build_live_lens_snapshot`, #835's kickoff total (E0, so the anchor
sees the same engine) and the cutoff-replay harness. An explicit `profile=` is honoured as given.

OFF IS THE SAME OBJECT. With the switch absent `resolve` returns `NCAAF_CALIBRATION_PROFILE` itself, so the re-sim is
byte-identical (test-pinned through the tick). Turning it on changes NCAAF live totals and margins, so it is a BETTING
CHANGE: load only in a betting-change window, on the user's yes, together with #835's switch.
"""
from __future__ import annotations

import dataclasses
import math
import os
from typing import Any, Mapping

SWITCH_ENV = "SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING"
STRENGTH_ENV = SWITCH_ENV + "_STRENGTH"
THRESHOLD_ENV = SWITCH_ENV + "_THRESHOLD"
SPAN_ENV = SWITCH_ENV + "_SPAN"

# THE FITTED VALUES. Pre-registered re-fit (main `57fcb392e`; findings "## FIX -- RESULTS"), 2024 FIT: 150 games x
# Q3 7:30 / Q4 15:00 / 7:30 / 3:00 real states, common-line log loss against the real final, a 1-SE noise floor:
# - stage 1, threshold at strength 0.9: 17 beat the incumbent 14 by -0.0019 (se 0.0018);
# - stage 2, strength at threshold 17: 1.0 beat 0.9 by -0.0017 (se 0.0012).
# Against production: -0.0186 (se 0.0070); one-score states +0.0000 (0.0012).
# `strength` in (0, 1] is the share of the leader's scoring weight removed at full lead and full lateness. The damping
# starts above `lead_threshold` points and reaches full strength `lead_span` points later.
DEFAULT_STRENGTH = 1.0
DEFAULT_LEAD_THRESHOLD = 17.0
DEFAULT_LEAD_SPAN = 14.0

_ON_VALUES = frozenset({"1", "on", "true", "yes"})
_ANNOUNCED: dict[str, bool] = {}


def enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Only an explicit on value switches it on. Absent, empty, `off` or a typo is OFF: arming an engine mechanism
    from an unrecognised value would be the permissive reading of an unknown."""
    env = os.environ if environ is None else environ
    return str(env.get(SWITCH_ENV) or "").strip().lower() in _ON_VALUES


def _knob(env: Mapping[str, str], name: str, default: float, lo: float, hi: float) -> float:
    """A knob in (lo, hi]. A typo, a non-finite or an out-of-range value falls back to the FITTED default, never to
    "no damping": with the switch on, a bad knob must not silently turn the fix off."""
    raw = str(env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if not math.isfinite(value) or not lo < value <= hi:
        return default
    return value


def settings(environ: Mapping[str, str] | None = None) -> dict[str, float]:
    env = os.environ if environ is None else environ
    return {
        "strength": _knob(env, STRENGTH_ENV, DEFAULT_STRENGTH, 0.0, 1.0),
        "lead_threshold": _knob(env, THRESHOLD_ENV, DEFAULT_LEAD_THRESHOLD, 0.0, 60.0),
        "lead_span": _knob(env, SPAN_ENV, DEFAULT_LEAD_SPAN, 0.0, 60.0),
    }


def resolve(base: Any, environ: Mapping[str, str] | None = None) -> tuple[Any, dict[str, Any] | None]:
    """(profile, block). OFF: `(base, None)` -- `base` itself, unchanged. ON: `base` with the damping fields set, and
    the block the re-sim result carries (`{"on": True, "strength": .., "lead_threshold": .., "lead_span": ..}`)."""
    if not enabled(environ):
        return base, None
    knobs = settings(environ)
    profile = dataclasses.replace(
        base,
        blowout_damping_strength=knobs["strength"],
        blowout_damping_lead_threshold=knobs["lead_threshold"],
        blowout_damping_lead_span=knobs["lead_span"],
    )
    block = {"on": True, **knobs}
    key = repr(sorted(knobs.items()))
    if not _ANNOUNCED.get(key):
        _ANNOUNCED[key] = True
        # print, not logger: the fleet's role logs are read back from stdout (CLAUDE.md).
        print(
            f"NCAAF_LIVE_BLOWOUT_DAMPING on strength={knobs['strength']} lead_threshold={knobs['lead_threshold']}"
            f" lead_span={knobs['lead_span']} profile={getattr(base, 'name', '?')}",
            flush=True,
        )
    return profile, block


__all__ = [
    "DEFAULT_LEAD_SPAN",
    "DEFAULT_LEAD_THRESHOLD",
    "DEFAULT_STRENGTH",
    "SPAN_ENV",
    "STRENGTH_ENV",
    "SWITCH_ENV",
    "THRESHOLD_ENV",
    "enabled",
    "resolve",
    "settings",
]
