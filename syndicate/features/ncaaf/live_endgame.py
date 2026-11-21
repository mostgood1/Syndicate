"""NCAAF live re-sim: the end game as college teams play it (todo #859, lane ncaaf-margin-aware-endgame). DEFAULT OFF.

WHAT IS WRONG WITHOUT IT. Resumed from a live state, smartsim2 runs the clock in the last minutes as if neither side
cared about the margin:
- it has no end-of-half clock (no kneel-outs, no clock-stopping by need, no timeouts);
- a trailer of ANY deficit hurries (`trailing_urgency`, then the two-minute drill), so a team down 30 with five
  minutes left plays like a team down 3;
- overtime is NFL-shaped rather than college's alternating possessions.
Real trailers ease off only at a 25-point deficit or more (CFBD 2023-24: pass share 0.47, about 19 s a snap).
Measured: `.syndicate/findings_2026-11-20_ncaaf_margin_aware_endgame.md` (the rule), `..._endgame_clock.md` (#858, the
clock), `..._college_overtime.md` (#855).

WHAT THIS IS. Switches the engine already has, armed for the NCAAF LIVE re-sim only:
- #808's seven end-of-half clock switches (`END_OF_HALF_SWITCHES`);
- #859's `trailing_concede_deficit`: in regulation Q4 a trailer down this many points or more plays neutral offense;
- #855's `college_overtime`.
With #852's blowout damping also on (`ncaaf/live_blowout_damping.py`) and ESPN's timeouts left fed
(`NcaafLiveGameState.home_timeouts`), this is exactly the `v4a` arm that passed #859's pre-registered gate on 2024
(the built rule reproduces the harness arm on 12 of 12 real blowout states, findings "## BUILD").
Pregame and every other caller are untouched.

HOW IT REACHES PRODUCTION. `ncaaf.live_resim.resim_live_game` applies it after #852's damping when the caller passes no
profile. Every production caller passes none: the tick's `build_live_lens_snapshot`, #835's kickoff total (E0, so the
anchor sees the same engine) and the cutoff-replay harness. An explicit `profile=` is honoured as given.

OFF IS THE SAME OBJECT. With the switch absent `resolve` returns its `base` itself, so the re-sim is byte-identical
(test-pinned through the tick). Turning it on changes NCAAF live totals, margins and win probabilities, so it is a
BETTING CHANGE: load only in a betting-change window, on the user's yes. Before that, owed (findings "## OWED"): a
joint re-read of the damping shape with this on, and a hold-out with ESPN's real timeouts.
"""
from __future__ import annotations

import dataclasses
import os
from typing import Any, Mapping

SWITCH_ENV = "SYNDICATE_NCAAF_LIVE_ENDGAME"
CONCEDE_ENV = SWITCH_ENV + "_CONCEDE_DEFICIT"

# #808's end-of-half clock, all seven (`CalibrationProfile`; the set #858 and #859 were measured with).
END_OF_HALF_SWITCHES = (
    "halftime_kickoff",
    "q2_urgency_ignores_score",
    "end_of_half_clock",
    "end_of_half_kneel_out",
    "end_of_half_clock_by_need",
    "q4_kick_waits",
    "kneel_out_q4_only",
)

# THE PRE-REGISTERED VALUE (main `7b28b5f82`): CFBD 2023-24 trailers ease off at 25+, and `v4a` used 25 unfitted.
DEFAULT_CONCEDE_DEFICIT = 25
_CONCEDE_RANGE = (1, 60)

_ON_VALUES = frozenset({"1", "on", "true", "yes"})
_ANNOUNCED: dict[str, bool] = {}


def enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Only an explicit on value switches it on. Absent, empty, `off` or a typo is OFF: arming an engine mechanism
    from an unrecognised value would be the permissive reading of an unknown."""
    env = os.environ if environ is None else environ
    return str(env.get(SWITCH_ENV) or "").strip().lower() in _ON_VALUES


def concede_deficit(environ: Mapping[str, str] | None = None) -> int:
    """The deficit, a whole number of points in 1..60. A typo, a fraction or an out-of-range value falls back to the
    PRE-REGISTERED 25, never to "no concession": with the switch on, a bad knob must not silently change the rule."""
    env = os.environ if environ is None else environ
    raw = str(env.get(CONCEDE_ENV) or "").strip()
    if not raw.isdigit():
        return DEFAULT_CONCEDE_DEFICIT
    value = int(raw)
    lo, hi = _CONCEDE_RANGE
    return value if lo <= value <= hi else DEFAULT_CONCEDE_DEFICIT


def resolve(base: Any, environ: Mapping[str, str] | None = None) -> tuple[Any, dict[str, Any] | None]:
    """(profile, block). OFF: `(base, None)` -- `base` itself, unchanged. ON: `base` with the end-game set armed, and
    the block the re-sim result carries (`{"on": True, "concede_deficit": .., "end_of_half_clock": True,
    "college_overtime": True}`). Every other field of `base` (#852's damping among them) is kept as given."""
    if not enabled(environ):
        return base, None
    deficit = concede_deficit(environ)
    profile = dataclasses.replace(
        base,
        **{name: True for name in END_OF_HALF_SWITCHES},
        trailing_concede_deficit=deficit,
        college_overtime=True,
    )
    block = {"on": True, "concede_deficit": deficit, "end_of_half_clock": True, "college_overtime": True}
    key = f"{deficit}|{getattr(base, 'name', '?')}|{getattr(base, 'blowout_damping_strength', None)}"
    if not _ANNOUNCED.get(key):
        _ANNOUNCED[key] = True
        # print, not logger: the fleet's role logs are read back from stdout (CLAUDE.md).
        print(
            f"NCAAF_LIVE_ENDGAME on concede_deficit={deficit} end_of_half_clock=7/7 college_overtime=True"
            f" blowout_damping_strength={getattr(base, 'blowout_damping_strength', None)}"
            f" profile={getattr(base, 'name', '?')}",
            flush=True,
        )
    return profile, block


__all__ = [
    "CONCEDE_ENV",
    "DEFAULT_CONCEDE_DEFICIT",
    "END_OF_HALF_SWITCHES",
    "SWITCH_ENV",
    "concede_deficit",
    "enabled",
    "resolve",
]
