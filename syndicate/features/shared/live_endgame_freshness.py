"""A live re-sim number in the last 5% of a game is used only if its game state is <= 30 s old (todo `#836`).

Lane `live-resim-endgame-staleness`, 2026-11-18. Findings:
`.syndicate/findings_2026-11-18_live_resim_endgame_staleness.md`.

WHY. The engine read against Kalshi's in-play mid (dev slates 11-09..11-14 ex 11-12, 54,173 live full-game
line-instants, NBA / NCAAF / NHL; `.syndicate/brief_2026-11-17_engine_read_kalshi.md`) found the gap between the live
re-sim and Kalshi barely depends on the state's age before 95% of game time (+0.02 to +0.04 nats in every age bin),
and depends on it heavily after: in the last 5%, 767 of 829 line-instants (92.5%, 85 games) carried a state more than
30 s old and lost to Kalshi by +0.174 nats (se 0.053). Kalshi's mid at an instant has seen every play up to it; a
re-sim whose state is two minutes old has not, and at the end of a game two minutes is most of what is left.

The <= 30 s cell (-0.048, se 0.019) is 62 line-instants from 14 games, two NBA games carrying 38 of them, so it does
NOT establish that a fresh state beats Kalshi. This rule rests on the stale majority, not on the fresh minority.

WHAT SETS THE AGE (measured on the fleet's live evidence log, same dates): each producer's loop, not the evidence log.
New-state gap p50 / p90: NBA 151 / 186 s (a tick, then a 120 s wait: `nba/live_resim.py` `_interval_seconds`), NCAAF
154 / 342 s (refresh-worker's main-loop cycle gates a tick whose own floor is max(75 s, 6 x elapsed), on a live-state
record up to 120 s old), NHL 91 / 128 s (one step of the live-lens loop's serial all-sport sweep, then a 60 s wait).
No producer comes near 30 s, so on today's cadence this refuses about nine in ten late-game opinions.

THE RULE. `endgame_verdict` refuses when the state says the game is in its last `ENDGAME_SHARE` of regulation (or in
overtime) and the state is older than `MAX_STATE_AGE_SECONDS`. The age is `now - liveStateAsOf`: when the producer READ
the state, which is the information the number has. (The engine experts' `evidence_age_s` measures from the later of
the snapshot's tick and that time; for NBA the tick is stamped after every game's state is read, and NCAAF's state comes
from a record older than its tick, so that age understates.) In the end game an absent or unparseable state time
refuses by name (`unknown must not default permissive`). Outside the end game, and for a sport not in `GATED_SPORTS`,
it returns None and changes nothing.

OVERTIME is end game: every NBA / NHL overtime is inside the last five minutes of play by construction. Measured on
the same dates: 79 overtime line-instants (1 NBA, 7 NHL games), +0.096 (se 0.009) against Kalshi, 72 of them older
than 30 s.

MEASURED SPORTS ONLY: NBA, NCAAF and NHL, the three the engine read could price against Kalshi. NCAAB / WNCAAB / WNBA /
NFL lanes are not gated until a read covers them.

SWITCH `SYNDICATE_LIVE_ENDGAME_FRESHNESS`, read by each consumer: `shadow` (ABSENT) = the consumer prices exactly as
before and counts what this would refuse; anything else that is not off (`on`, or a typo) = refuse; `off` / `0` /
`false` / `no` = not even counted. Absent is shadow, not on, because refusing a live price changes the board and the
paper books, and that is the user's decision; a typo gates (`unknown must not default permissive`).
`SYNDICATE_LIVE_ENDGAME_MAX_STATE_AGE_SECONDS` overrides 30 s (a positive finite value; anything else is the default).

Pure: no I/O, no clock read (the caller passes `now`), no import of a consumer.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

MODE_ENV = "SYNDICATE_LIVE_ENDGAME_FRESHNESS"
MAX_AGE_ENV = "SYNDICATE_LIVE_ENDGAME_MAX_STATE_AGE_SECONDS"
MODE_ON, MODE_SHADOW, MODE_OFF = "on", "shadow", "off"

ENDGAME_SHARE = 0.95
MAX_STATE_AGE_SECONDS = 30.0

REASON_STALE = "live_state_stale_in_endgame"
REASON_TIME_ABSENT = "live_state_time_absent_in_endgame"

# (regulation periods, seconds per period) -- the engine experts' `SPORT_CLOCK` for the same sports, so "the last 5%"
# means here exactly what the engine read's 95-100 bucket meant. `tests/test_live_endgame_freshness.py` pins the two
# tables equal, so neither can drift alone.
GATED_SPORTS: dict[str, tuple[int, int]] = {
    "nba": (4, 720),
    "ncaaf": (4, 900),
    "nhl": (3, 1200),
}


def mode(env: Optional[Mapping[str, str]] = None) -> str:
    """`shadow` when absent, `off` for an explicit off, `on` for anything else (a typo gates)."""
    raw = str((env if env is not None else os.environ).get(MODE_ENV) or "").strip().lower()
    if raw in ("", MODE_SHADOW):
        return MODE_SHADOW
    if raw in (MODE_OFF, "0", "false", "no"):
        return MODE_OFF
    return MODE_ON


def max_state_age_seconds(env: Optional[Mapping[str, str]] = None) -> float:
    raw = str((env if env is not None else os.environ).get(MAX_AGE_ENV) or "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            value = 0.0
        if value > 0.0 and math.isfinite(value):
            return value
    return MAX_STATE_AGE_SECONDS


def _f(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def elapsed_share(sport: Any, period: Any, clock_seconds: Any) -> tuple[Optional[float], bool]:
    """(share of regulation elapsed, overtime?) from a live state; (None, False) when it cannot be read.

    The engine experts' `elapsed_share` formula: ((period - 1) * length + (length - clock)) / (periods * length),
    the clock clamped to the period. A period past regulation is overtime: (None, True)."""
    spec = GATED_SPORTS.get(str(sport or "").strip().lower())
    p, c = _f(period), _f(clock_seconds)
    if spec is None or p is None or c is None or p < 1:
        return None, False
    periods, length = spec
    if p > periods:
        return None, True
    c = min(max(c, 0.0), float(length))
    return ((p - 1.0) * length + (length - c)) / float(periods * length), False


def in_endgame(sport: Any, period: Any, clock_seconds: Any) -> bool:
    share, overtime = elapsed_share(sport, period, clock_seconds)
    return overtime or (share is not None and share >= ENDGAME_SHARE)


def _instant(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    else:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def state_age_seconds(as_of: Any, now: datetime) -> Optional[float]:
    """Seconds from the state's read time to `now`; None when absent or unparseable. A time ahead of `now` reads 0."""
    stamped = _instant(as_of)
    if stamped is None:
        return None
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return max(0.0, (current - stamped).total_seconds())


def endgame_verdict(sport: Any, period: Any, clock_seconds: Any, as_of: Any, now: datetime, *,
                    env: Optional[Mapping[str, str]] = None) -> Optional[dict[str, Any]]:
    """None = usable (not the end game, not a gated sport, or a state within the age bound). Otherwise a refusal
    shaped like `live_gameline_join`'s verdicts, plus what it judged (`state_age_s`, `elapsed_share`, `overtime`,
    `max_state_age_s`). The mode is the CALLER's to read: this always answers what the rule says."""
    share, overtime = elapsed_share(sport, period, clock_seconds)
    if not (overtime or (share is not None and share >= ENDGAME_SHARE)):
        return None
    limit = max_state_age_seconds(env)
    age = state_age_seconds(as_of, now)
    verdict: dict[str, Any] = {"priceable": False, "model_prob": None, "market_prob": None, "edge_pp": None,
                               "state_age_s": None if age is None else round(age, 1),
                               "elapsed_share": None if share is None else round(share, 4),
                               "overtime": overtime, "max_state_age_s": limit}
    if age is None:
        return {**verdict, "withheld_reason": REASON_TIME_ABSENT}
    if age > limit:
        return {**verdict, "withheld_reason": REASON_STALE}
    return None
