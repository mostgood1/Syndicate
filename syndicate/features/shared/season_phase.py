"""Which season phase a sport is in on a slate date: preseason / regular / postseason.

`learnings.md` (season-phase models): preseason, regular season and playoffs are
different populations -- rotations, minutes and motivation all change -- so no
fit, grade or threshold may pool them. Anything that LEARNS from settled bets
(`min_ev_tuner`) keys its cells on this.

**UNKNOWN IS `None`, NEVER "regular".** A date outside every listed window (the
off-season, or a season nobody has entered yet) returns None, and a caller must
treat that as "do not learn from / do not apply to this", not as the regular
season. Defaulting an unknown to the permissive branch is the shape
`learnings.md` keeps forbidding.

Calendar, not a feed: the windows are the leagues' published dates. Extend each
season here. `scripts/build_cheat_sheets.py::SEASON_PHASES` carries the same
regular/postseason windows (without preseason) for the cheat sheets.
"""

from __future__ import annotations

PRESEASON = "preseason"
REGULAR = "regular"
POSTSEASON = "postseason"

# Sports with no phases to separate: domestic soccer leagues run all year.
ALL_YEAR_SPORTS = frozenset({"soccer"})

# (start, end, phase), inclusive ISO dates. A sport in neither table is UNKNOWN.
SEASON_WINDOWS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "nfl": (
        ("2026-08-06", "2026-08-30", PRESEASON),
        ("2026-09-10", "2027-01-10", REGULAR),
        ("2027-01-16", "2027-02-14", POSTSEASON),
    ),
    "ncaaf": (
        ("2026-08-29", "2026-12-12", REGULAR),
        ("2026-12-13", "2027-01-20", POSTSEASON),
    ),
    "nhl": (
        ("2026-09-20", "2026-10-05", PRESEASON),
        ("2026-10-06", "2027-04-17", REGULAR),
        ("2027-04-18", "2027-06-25", POSTSEASON),
    ),
    "nba": (
        ("2026-10-02", "2026-10-19", PRESEASON),
        ("2026-10-20", "2027-04-11", REGULAR),
        ("2027-04-14", "2027-06-25", POSTSEASON),
    ),
    "ncaab": (
        ("2026-11-02", "2027-03-15", REGULAR),
        ("2027-03-16", "2027-04-06", POSTSEASON),
    ),
    "wnba": (
        ("2026-05-08", "2026-09-14", REGULAR),
        ("2026-09-15", "2026-10-31", POSTSEASON),
        ("2027-05-01", "2027-05-13", PRESEASON),
        ("2027-05-14", "2027-09-12", REGULAR),
        ("2027-09-13", "2027-10-25", POSTSEASON),
    ),
    "mlb": (
        ("2026-03-26", "2026-09-28", REGULAR),
        ("2026-09-29", "2026-11-05", POSTSEASON),
        ("2027-02-20", "2027-03-24", PRESEASON),
        ("2027-03-25", "2027-09-26", REGULAR),
        ("2027-09-27", "2027-11-05", POSTSEASON),
    ),
}


def season_phase(sport: object, day: object) -> str | None:
    """The phase of `sport` on ISO date `day`, or None when it is not known."""
    sport_key = str(sport or "").strip().lower()
    day_key = str(day or "").strip()[:10]
    if not sport_key or len(day_key) != 10:
        return None
    if sport_key in ALL_YEAR_SPORTS:
        return REGULAR
    windows = SEASON_WINDOWS.get(sport_key)
    if windows is None:
        return None
    return next((phase for start, end, phase in windows if start <= day_key <= end), None)
