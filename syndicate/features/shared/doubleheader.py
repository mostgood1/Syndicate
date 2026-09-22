"""Pick ONE game when a team-pair join finds several — the doubleheader rule.

WHY THIS EXISTS -- measured on production 2026-09-22
----------------------------------------------------
TB @ NYY played a split doubleheader: gamePk 823543 at 17:05Z and 823494 at
23:05Z, quoted by the books as two OddsAPI events (17:06Z and 23:06Z). Every
join that keyed a game on its TEAM PAIR (plus date) found both games and kept
whichever one its loop happened to reach first or last:

  * the Layer 2 game block: game 2's rows read game 1's chip (`12:05P CT`);
  * the Layer 2 game-line projection: game 1's moneyline read game 2's sim
    (home 0.531, where game 1's own sim says 0.606);
  * game 2's prop rows read game 1's player projections AND game 1's Kalshi
    ticker (`...26SEP221305TBNYYG1...`) -- the ticker the order path trades;
  * the MLB cards: game 1's card carried game 2's odds (`commence 23:06Z`).

A team pair is not a game identity on any day with a doubleheader, and on a
multi-day board it is not one across a series either (the same pair plays on
consecutive days). The discriminator both sides of every one of those joins
already carry is the START TIME: OddsAPI's `commence_time` against StatsAPI's
`gameDate` (or a chip's `start_time_utc`, or a sim's `commence_time`). The two
halves of a doubleheader are ~3-6 h apart; a book's commence time sits within
minutes of the scheduled first pitch.

THE RULE. One candidate: it is the game (callers keep their own date scoping).
Several: the one whose start is nearest the target start wins, but only if it
is clearly nearer than the runner-up. Anything else is AMBIGUOUS and returns
None with a named reason -- a join that cannot tell the halves apart must
attach NOTHING rather than the other game's price, projection or ticker
(`learnings.md`: unknown must not default permissive).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")

#: The runner-up must be at least this much FARTHER from the target than the
#: winner. Doubleheader halves are >= ~3 h apart and a book's commence time is
#: within minutes of first pitch, so a real pair clears this by hours; two
#: candidates inside it cannot be told apart on time and are refused.
MIN_SEPARATION_SECONDS = 45 * 60

# Reasons, stable strings -- callers count them.
SINGLE = "single"
NEAREST_START = "nearest_start"
NO_CANDIDATES = "no_candidates"
AMBIGUOUS_NO_TARGET_TIME = "ambiguous_no_target_time"
AMBIGUOUS_NO_CANDIDATE_TIME = "ambiguous_no_candidate_time"
AMBIGUOUS_NOT_SEPARABLE = "ambiguous_not_separable"


def start_epoch(value: Any) -> float | None:
    """ISO-8601 string (``Z`` or offset), epoch number or datetime -> epoch seconds.

    A naive datetime or ISO string without an offset is read as UTC, which is
    what every producer here writes (`commence_time`, `gameDate`,
    `start_time_utc`). Anything unparseable is None, never 0.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def central_clock_start_epoch(slate_date: Any, clock_text: Any) -> float | None:
    """``("2026-09-22", "12:05 PM")`` -> epoch of 12:05 America/Chicago that day.

    The MLB live-lens snapshot carries a game's start ONLY as the Central clock
    string its cards display (`startTime`), plus the slate date -- no ISO
    `gameDate`. Anything that is not an ``H:MM AM/PM`` clock ("TBD",
    "Postponed", a status word) is None.
    """
    from zoneinfo import ZoneInfo

    date_text = str(slate_date or "").strip()[:10]
    clock = str(clock_text or "").strip().upper().replace(".", "")
    if len(date_text) != 10 or not clock:
        return None
    for fmt in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %I:%M%p"):
        try:
            naive = datetime.strptime(f"{date_text} {clock}", fmt)
        except ValueError:
            continue
        return naive.replace(tzinfo=ZoneInfo("America/Chicago")).timestamp()
    return None


#: Two starts further apart than this are two DIFFERENT DAYS' games, never one
#: game quoted early: an MLB series plays the same pair on consecutive days
#: (~24 h apart) while a book's commence time sits within minutes of first
#: pitch. Used by callers whose both clocks are precise (MLB).
MAX_SAME_GAME_GAP_SECONDS = 12 * 3600

BEYOND_MAX_GAP = "beyond_max_gap"


def pick_by_start_time(
    candidates: Iterable[T],
    target_start: Any,
    *,
    start_of: Callable[[T], Any],
    min_separation_seconds: float = MIN_SEPARATION_SECONDS,
    max_gap_seconds: float | None = None,
) -> tuple[T | None, str]:
    """Return ``(candidate, reason)`` -- the one game a team-pair join means.

    ``start_of(candidate)`` returns that candidate's start (any form
    `start_epoch` reads). ``target_start`` is the row's own start
    (`commence_time`). Candidates that are the same object or share one start
    are NOT deduplicated here: two distinct games at one start are not
    separable, and the caller must say so rather than pick one.

    ``max_gap_seconds``, when given, also refuses the chosen candidate -- a
    SINGLE one included -- whose start is further than that from the target:
    the only candidate for a pair can still be another day's game. It is
    applied only when both times are known; an untimed single candidate keeps
    the legacy answer, because nothing can rule it out.
    """
    pool = list(candidates)
    if not pool:
        return None, NO_CANDIDATES
    target = start_epoch(target_start)
    if len(pool) == 1:
        if max_gap_seconds is not None and target is not None:
            try:
                only_start = start_epoch(start_of(pool[0]))
            except Exception:
                only_start = None
            if only_start is not None and abs(only_start - target) > float(max_gap_seconds):
                return None, BEYOND_MAX_GAP
        return pool[0], SINGLE
    if target is None:
        return None, AMBIGUOUS_NO_TARGET_TIME
    timed: list[tuple[float, int, T]] = []
    for index, candidate in enumerate(pool):
        try:
            start = start_epoch(start_of(candidate))
        except Exception:
            start = None
        if start is not None:
            timed.append((abs(start - target), index, candidate))
    if not timed:
        return None, AMBIGUOUS_NO_CANDIDATE_TIME
    timed.sort(key=lambda item: (item[0], item[1]))
    if len(timed) < len(pool):
        # An untimed candidate could be the nearer game; it cannot be ruled out.
        return None, AMBIGUOUS_NO_CANDIDATE_TIME
    best_gap = timed[0][0]
    runner_up_gap = timed[1][0]
    if runner_up_gap - best_gap < float(min_separation_seconds):
        return None, AMBIGUOUS_NOT_SEPARABLE
    if max_gap_seconds is not None and best_gap > float(max_gap_seconds):
        return None, BEYOND_MAX_GAP
    return timed[0][2], NEAREST_START
