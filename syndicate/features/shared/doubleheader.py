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
from typing import Any, Callable, Iterable, Mapping, TypeVar

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
# A timed candidate matching the target to within the separation window, chosen
# over candidates that carry no start at all. Named apart from `NEAREST_START`
# so a payload can show how much of the board rests on it.
NEAREST_START_OVER_UNTIMED = "nearest_start_over_untimed"


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
        # AN UNTIMED CANDIDATE CANNOT VETO A NEAR-EXACT TIME MATCH, and the
        # first version of this rule said it could. Measured on production
        # 2026-09-23 00:2xZ, MLB Layer 2: **rows_matched 0, ambiguous 3,533**,
        # no live MLB opportunities on the board at all, while soccer, ncaaf,
        # wnba and nhl were 0 ambiguous. MLB is the sport that plays SERIES, so
        # every pair has a chip on today's date AND tomorrow's -- and
        # tomorrow's starts are not published yet: **16 of 16 chips for
        # 2026-09-23 carried `start_time_utc: None`, against 0 of 16 for
        # 09-22**, so 15 of 15 team pairs held at least one untimed candidate
        # and this branch refused every row.
        #
        # A start that matches the target to within the separation window IS
        # that game -- the odds `commence_time` and StatsAPI's start agree to
        # the minute (TB @ NYY: 17:06Z against 17:05Z). An unknown cannot
        # displace it, so the veto is kept only where it does real work: the
        # winner must ALSO be clear of the runner-up by that same window, which
        # is exactly the doubleheader case. A row whose own half is the untimed
        # one still finds no near match -- the other half is hours away -- and
        # is still refused rather than handed its sibling's numbers.
        best_gap = timed[0][0]
        clear_of_runner_up = (
            len(timed) == 1
            or (timed[1][0] - best_gap) >= float(min_separation_seconds)
        )
        if best_gap <= float(min_separation_seconds) and clear_of_runner_up:
            return timed[0][2], NEAREST_START_OVER_UNTIMED
        return None, AMBIGUOUS_NO_CANDIDATE_TIME
    best_gap = timed[0][0]
    runner_up_gap = timed[1][0]
    if runner_up_gap - best_gap < float(min_separation_seconds):
        return None, AMBIGUOUS_NOT_SEPARABLE
    if max_gap_seconds is not None and best_gap > float(max_gap_seconds):
        return None, BEYOND_MAX_GAP
    return timed[0][2], NEAREST_START


def eastern_date_of(epoch: float) -> str:
    """The game's Eastern calendar date -- the date the venues name a game by."""
    from zoneinfo import ZoneInfo

    return datetime.fromtimestamp(epoch, tz=ZoneInfo("America/New_York")).date().isoformat()


def doubleheader_event_ranks(
    rows: Iterable[Any],
    *,
    fixture_of: Callable[[Any], Any],
) -> tuple[dict[str, int], set[str]]:
    """Which half of a doubleheader each board row's event is: ``({event_id: n}, unrankable)``.

    Rows are grouped by ``fixture_of(row)`` (the club pair, however the caller
    spells it) and the Eastern date of their `commence_time`. A group holding
    two or more DISTINCT `event_id`s is a doubleheader; its events are ranked
    1, 2, ... by their earliest start. Ranked by EVENT, not by start, so one
    event whose rows disagree on the minute cannot read as two games.

    Readable only when both halves are in `rows`: a lone half cannot be told
    from an ordinary game, and it is simply absent from the map -- callers
    that need a half number must then refuse, never assume game 1. Events that
    share a start with another event of the group are returned in
    `unrankable`.
    """
    groups: dict[tuple[Any, str], dict[str, float]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        event_id = str(row.get("event_id") or "").strip()
        start = start_epoch(row.get("commence_time"))
        fixture = fixture_of(row)
        if not event_id or start is None or not fixture:
            continue
        events = groups.setdefault((fixture, eastern_date_of(start)), {})
        known = events.get(event_id)
        events[event_id] = start if known is None else min(known, start)
    ranks: dict[str, int] = {}
    unrankable: set[str] = set()
    for events in groups.values():
        if len(events) < 2:
            continue
        ordered = sorted(events.items(), key=lambda item: item[1])
        starts = [start for _, start in ordered]
        for position, (event_id, start) in enumerate(ordered, start=1):
            if starts.count(start) > 1:
                unrankable.add(event_id)
            else:
                ranks[event_id] = position
    return ranks, unrankable
