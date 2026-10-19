"""MLB game status as a GRADER must read it -- one reader-side mapping.

StatsAPI's `abstractGameState` is a display bucket, not a result. It maps every
game that WILL NOT BE PLAYED as scheduled onto **"Final"**: postponed
(`codedGameState: "D"`), cancelled (`"C"`) and suspended (`"U"`), each with a
0-0 linescore. Any reader that asks "is it Final?" of that field alone grades a
rainout as a 0-0 final: every under wins, every moneyline is a tie.

Measured 2026-10-16/17, gamePk 849817 (TB @ CLE): the live lens logged it
`Preview -> Final` at 20:55 CT with a 0-0 score while the schedule said
`detailedState: "Postponed"`, `codedGameState: "D"`, `reason: "Rain"`.

A rescheduled game is the second trap. `feed/live` is keyed by gamePk, and once
StatsAPI reschedules, the SAME gamePk describes the NEW game: 849817's feed read
`Scheduled` with `officialDate: 2026-10-18` within a day, and `Final` (TB 3-1)
after it was played. A grader asking for date D's game reads date D+2's result
unless it checks `gameData.datetime.officialDate`.

So a game is gradable for slate date D only when it was PLAYED and it was played
ON D. Everything here is a refusal: an unrecognised state costs a missed
settlement, never an invented one. The generated live-lens port
(`live_lens_port/app_slice.py`) is not edited; readers in Syndicate code call
this instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# codedGameState -> the reason a game was not played. The coded state is the
# field that discriminates; text is the fallback for providers that drop it.
NOT_PLAYED_CODED = {"D": "postponed", "C": "cancelled", "U": "suspended"}
_NOT_PLAYED_WORDS = (
    ("postpon", "postponed"),
    ("cancel", "cancelled"),
    ("suspend", "suspended"),
)

REASON_NOT_PLAYED = "mlb_game_not_played"
REASON_RESCHEDULED = "mlb_game_rescheduled_off_slate_date"


def _text(value: Any) -> str:
    return str(value or "").strip()


def feed_status(feed_or_status: Any) -> Mapping[str, Any]:
    """The status block of a `feed/live` payload, a schedule game, or a status
    dict passed directly (raw StatsAPI keys or the lens's abstract/detailed)."""
    if not isinstance(feed_or_status, Mapping):
        return {}
    game_data = feed_or_status.get("gameData")
    if isinstance(game_data, Mapping) and isinstance(game_data.get("status"), Mapping):
        return game_data["status"]
    status = feed_or_status.get("status")
    if isinstance(status, Mapping):
        return status
    return feed_or_status


def not_played_reason(feed_or_status: Any) -> str | None:
    """`postponed` / `cancelled` / `suspended`, or None for a game being played."""
    status = feed_status(feed_or_status)
    coded = _text(status.get("codedGameState") or status.get("coded_game_state")).upper()
    if coded in NOT_PLAYED_CODED:
        return NOT_PLAYED_CODED[coded]
    detailed = _text(
        status.get("detailedState") or status.get("detailed_state") or status.get("detailed")
    ).lower()
    for needle, reason in _NOT_PLAYED_WORDS:
        if needle in detailed:
            return reason
    return None


def official_date(feed: Any) -> str | None:
    """`gameData.datetime.officialDate` (YYYY-MM-DD), or a schedule game's own
    `officialDate`; None when the payload does not carry one."""
    if not isinstance(feed, Mapping):
        return None
    game_data = feed.get("gameData")
    if isinstance(game_data, Mapping):
        dt = game_data.get("datetime")
        if isinstance(dt, Mapping) and _text(dt.get("officialDate")):
            return _text(dt.get("officialDate"))[:10]
    if _text(feed.get("officialDate")):
        return _text(feed.get("officialDate"))[:10]
    return None


def rescheduled_off(feed: Any, slate_date: Any) -> bool:
    """True when the payload describes a game whose official date is NOT the
    slate date asked about -- the gamePk now belongs to a rescheduled game.

    A payload with no `officialDate` is not refused here: every real StatsAPI
    `feed/live` carries one, and refusing on its absence would stop all MLB
    grading on a provider format change rather than on a rescheduled game.
    """
    slate = _text(slate_date)[:10]
    played_on = official_date(feed)
    return bool(slate and played_on and played_on != slate)


def is_final(feed_or_status: Any) -> bool:
    """Finished AND played: abstract or detailed says final, and the game is
    not postponed, cancelled or suspended."""
    if not_played_reason(feed_or_status):
        return False
    status = feed_status(feed_or_status)
    abstract = _text(status.get("abstractGameState") or status.get("abstract")).lower()
    detailed = _text(status.get("detailedState") or status.get("detailed")).lower()
    return abstract == "final" or detailed.startswith(("final", "game over", "completed early"))


def grading_refusal(feed: Any, slate_date: Any = None) -> str | None:
    """Why a feed must not grade a bet on `slate_date`, or None if it may.

    Not played comes first: a postponed game is refused whatever its date.
    """
    if not_played_reason(feed):
        return REASON_NOT_PLAYED
    if slate_date is not None and rescheduled_off(feed, slate_date):
        return REASON_RESCHEDULED
    return None


def display_state(feed_or_status: Any) -> str | None:
    """`Postponed` / `Cancelled` / `Suspended` for display, or None."""
    reason = not_played_reason(feed_or_status)
    return reason.capitalize() if reason else None
