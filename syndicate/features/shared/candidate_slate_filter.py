"""Layer 2 candidates are TODAY's games only. Layer 1 may carry future days.

THE RULE, and it is the user's: a shard is keyed by CAPTURE date, so odds quoted
today for a fixture next week land in today's data. Layer 1 boards may show that
-- forward fixtures and their sims are legitimate there. **Layer 2 must not**: a
candidate is a bet recommendation, and a board built to surface today's best
opportunities cannot contain a game four days out.

Measured on the served board 2026-08-11, before this existed:

    selected_date = 2026-08-11
    mls      08-15 x24  08-16 x25  08-17 x8
    serie a  08-22 x15  08-23 x15  08-24 x2
    mlb/nfl/wnba/championship: no date at all
    total 123 -- not_today 91, no_date 32, TODAY: 0

**Not one candidate on the board was for a game that day.**

WHY THERE WAS NOTHING TO FILTER ON
----------------------------------
A candidate carries 107-125 fields and none of them said when the game is played.
`event_id`, `game_id`, `gamePk`, `matchup`, `game_state`, `is_live`, `is_final` --
every identifier for WHICH game, nothing for WHEN. The only dates were
`book_updated_at`, `last_updated` and `sport_manifest_last_updated`, all about our
own pipeline. `selected_date` was threaded through the collector and never
applied, because there was no field it could be applied to.

THE JOIN IS THE ONE LAYER 1 ALREADY PROVED
------------------------------------------
`attach_game_state` joins grid rows to `build_game_chips` on the TEAM PAIR through
`team_aliases`, and matched 2,800 of 2,800 rows on the same day this was written.
Chips carry `start_time_utc` on 100% of rows for every sport that has games.

Deliberately NOT joined on `event_id`: the id spaces do not line up across sports
(MLB StatsAPI game PKs `824563`, WNBA/NFL ESPN ids `401857136`, soccer `761714`)
and chips carry no `event_id` at all. The team pair is the only key that spans
them -- and `#218` established a naive string match cannot do it, because "chc" is
neither a prefix of "chicago" nor the initials of "chicago cubs".

EXCLUSION IS THE DEFAULT, AND THAT DEVIATES FROM `live_edge_policy` ON PURPOSE
-----------------------------------------------------------------------------
There, an unknown game state ALLOWS the edge, because blanking the edge column on
the days the join degrades would destroy the board's purpose. Here the asymmetry
runs the other way: an undated candidate on a today-only board IS the pollution
being removed, a wrong inclusion is an actionable bet on a game that may be days
away, and it RANKS. A wrong inclusion costs money; a wrong exclusion costs
visibility, and visibility is recoverable.

So every drop is counted, and the three reasons are kept apart because they mean
different things and only one is a defect.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)

# A chip's slate date, in the clock the rest of this repo uses. An MLB slate
# spans two UTC dates (2026-08-11 ran 22:40Z through 02:10Z the next day), so a
# UTC test would cut every slate in half.
_SLATE_TZ = "America/Chicago"

# Same bound and reasoning as `attach_game_state`'s `_MAX_GAME_STATE_DATES`: each
# date is a scoreboard call, so the horizon is a per-build cost multiplier. 7 days
# covers NFL's Thu-Mon slate and soccer's week, which is what the measured misfile
# needed (MLS fixtures 5 days out were being called alias gaps).
_CHIP_WINDOW_DAYS = 7

DROP_NO_SLATE = "no_slate_for_sport"
DROP_NOT_TODAY = "joined_not_today"
DROP_NO_MATCH = "chips_present_no_match"


def _slate_date(stamp: Any) -> str | None:
    text = str(stamp or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        return moment.astimezone(ZoneInfo(_SLATE_TZ)).date().isoformat()
    except Exception:
        return moment.astimezone(timezone.utc).date().isoformat()


def _matchup_sides(candidate: Mapping[str, Any]) -> tuple[str, str] | None:
    """Split `AWAY @ HOME`, and `AWAY at HOME`, which is also in use.

    BOTH FORMS ARE REAL. Production candidates sampled 2026-08-11 all used `@`
    (`CIN @ CWS`, `NE @ TOR`), so an `@`-only parser looked complete -- and
    `tests/test_intelligence.py` immediately produced `NYY at BOS`. A candidate
    whose matchup will not parse is undatable, so it lands in the one drop reason
    that is supposed to signal a DEFECT, turning a format gap into a false alias
    alarm.

    ` at ` is required to be space-delimited: an unspaced `at` appears inside
    plenty of club names (Atlanta, Athletic) and splitting on it would invent
    sides that do not exist.
    """
    text = str(candidate.get("matchup") or "").strip()
    for separator in ("@", " at "):
        if separator in text:
            away, home = text.split(separator, 1)
            away, home = away.strip(), home.strip()
            return (away, home) if away and home else None
    return None


def _chip_side_matches(sport: str, token: str, chip_side: Any) -> bool:
    if not isinstance(chip_side, Mapping):
        return False
    try:
        from syndicate.features.shared.team_aliases import teams_match
    except Exception:
        return False
    # Name first, abbr as fallback -- the same order and reasoning as
    # `attach_game_state`: soccer tri-codes collide across leagues, so
    # `team_aliases` refuses to resolve them and an abbr-only join misses those
    # rows entirely.
    for key in ("name", "abbr"):
        value = chip_side.get(key)
        if value and teams_match(sport, token, value):
            return True
    return False


def stamp_and_filter_candidates_to_slate(
    candidates: Sequence[Mapping[str, Any]],
    *,
    selected_date: str,
    chips_by_sport: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(kept, coverage). Stamps `game_date` on what it can, drops the rest.

    `chips_by_sport` is injectable so callers that already hold chips do not
    re-fetch, and so this is testable without a scoreboard.
    """
    # Whether WE loaded the chips matters. An injected mapping is the caller
    # stating the slate explicitly and must be trusted -- including an empty one
    # for a sport genuinely out of season. Only a load WE performed can fail.
    loaded_here = chips_by_sport is None
    if loaded_here:
        chips_by_sport = _load_chips(candidates, selected_date=selected_date)

    # SCOREBOARD UNAVAILABLE IS NOT AN EMPTY SLATE. If a load we performed
    # returned nothing for every sport, the scoreboard could not be reached --
    # and dropping every candidate then blanks the board on exactly the outage
    # where a stale board beats none.
    #
    # Caught by `tests/test_intelligence.py`, which builds candidates with no
    # scoreboard: 42 tests went red because every candidate fell into
    # `no_slate_for_sport`. That is the production failure mode too, not a
    # fixture artifact -- the caller's try/except only covers exceptions, and
    # this path raises nothing.
    #
    # Gated on `loaded_here` because a single sport with no games is the NORMAL
    # case this filter enforces (NFL in August), and it is indistinguishable
    # from an outage by row count alone.
    if loaded_here and candidates and not any(chips_by_sport.get(s) for s in chips_by_sport):
        print(
            "[candidate_slate] SCOREBOARD_UNAVAILABLE date="
            f"{selected_date} sports={sorted(chips_by_sport)} "
            "-- passing candidates through UNFILTERED rather than emptying the board",
            flush=True,
        )
        return (
            [dict(c) for c in candidates if isinstance(c, Mapping)],
            {
                "selected_date": selected_date,
                "considered": len(candidates),
                "kept": len(candidates),
                "dropped": {DROP_NO_SLATE: 0, DROP_NOT_TODAY: 0, DROP_NO_MATCH: 0},
                "per_sport": {},
                "unmatched_samples": [],
                "unfiltered_reason": "scoreboard_unavailable",
            },
        )
    kept: list[dict[str, Any]] = []
    dropped: dict[str, int] = {DROP_NO_SLATE: 0, DROP_NOT_TODAY: 0, DROP_NO_MATCH: 0}
    per_sport: dict[str, dict[str, int]] = {}
    unmatched_samples: list[dict[str, Any]] = []

    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        sport = str(candidate.get("sport_slug") or "").strip().lower()
        stats = per_sport.setdefault(sport or "unknown", {"kept": 0, DROP_NO_SLATE: 0, DROP_NOT_TODAY: 0, DROP_NO_MATCH: 0})
        chips = list(chips_by_sport.get(sport) or ())

        if not chips:
            # The sport has no games today at all, so nothing it carries can be
            # for today. Arithmetic, not a judgement -- silent beyond the count.
            dropped[DROP_NO_SLATE] += 1
            stats[DROP_NO_SLATE] += 1
            continue

        sides = _matchup_sides(candidate)
        matched_chip = None
        if sides:
            away, home = sides
            for chip in chips:
                if _chip_side_matches(sport, away, chip.get("away")) and _chip_side_matches(
                    sport, home, chip.get("home")
                ):
                    matched_chip = chip
                    break

        if matched_chip is None:
            # THE ONLY DEFECT OF THE THREE. Chips exist for this sport today and
            # this candidate matched none of them -- an alias gap, not a filter
            # outcome, and indistinguishable from a correct exclusion at the
            # count level. `#218` is the precedent that cost two sessions.
            dropped[DROP_NO_MATCH] += 1
            stats[DROP_NO_MATCH] += 1
            if len(unmatched_samples) < 8:
                unmatched_samples.append(
                    {"sport": sport, "matchup": candidate.get("matchup"), "chips_available": len(chips)}
                )
            continue

        game_date = _slate_date(matched_chip.get("start_time_utc"))
        if game_date != selected_date:
            dropped[DROP_NOT_TODAY] += 1
            stats[DROP_NOT_TODAY] += 1
            continue

        row = dict(candidate)
        row["game_date"] = game_date
        row["game_date_source"] = "game_chip_team_pair"
        kept.append(row)
        stats["kept"] += 1

    coverage = {
        "selected_date": selected_date,
        "considered": len(candidates),
        "kept": len(kept),
        "dropped": dropped,
        "per_sport": per_sport,
        "unmatched_samples": unmatched_samples,
    }
    _warn_on_total_loss(per_sport, chips_by_sport)
    return kept, coverage


def _warn_on_total_loss(
    per_sport: Mapping[str, Mapping[str, int]],
    chips_by_sport: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    """A sport losing EVERY candidate to alias gaps is an alarm, not a quiet zero.

    The failure this guards is a sport silently vanishing from the board while
    the filter reports success -- MLB going 5 -> 0 with 15 chips present looks
    identical to a correct exclusion unless someone says otherwise.
    """
    for sport, stats in per_sport.items():
        if stats.get("kept"):
            continue
        no_match = int(stats.get(DROP_NO_MATCH) or 0)
        if no_match and chips_by_sport.get(sport):
            print(
                f"[candidate_slate] SPORT_LOST_ALL_CANDIDATES sport={sport} "
                f"no_match={no_match} chips={len(chips_by_sport.get(sport) or ())} "
                "-- alias gap, NOT a date exclusion",
                flush=True,
            )


def _load_chips(
    candidates: Sequence[Mapping[str, Any]], *, selected_date: str
) -> dict[str, list[dict[str, Any]]]:
    """Chips across a WINDOW, not one date. The window is what makes the three
    drop reasons mean what they say.

    MEASURED FAILURE OF THE SINGLE-DATE VERSION, on this filter's first real run:
    47 soccer candidates were reported `chips_present_no_match` -- a loud alias-gap
    alarm -- and 29 of them were MLS fixtures on 2026-08-16 that a 2026-08-11 chip
    query simply cannot see. They were correct exclusions misfiled as a defect.
    The genuine gap was 16, of which one token (`LEE`) accounts for 7.

    Without the window, ANY fixture beyond the chip horizon is indistinguishable
    from a broken alias. That turns the one reason that is supposed to be a defect
    signal into noise, which is worse than not having it -- an alarm nobody can
    trust is an alarm nobody reads.

    Bounded and ordered exactly as `attach_game_state` bounds its own version
    (`_MAX_GAME_STATE_DATES`): each date is a scoreboard call, so an unbounded
    horizon is a per-build cost multiplier. Nearest dates first.
    """
    sports = sorted(
        {
            str(c.get("sport_slug") or "").strip().lower()
            for c in candidates
            if isinstance(c, Mapping) and str(c.get("sport_slug") or "").strip()
        }
    )
    out: dict[str, list[dict[str, Any]]] = {}
    if not sports:
        return out
    try:
        from datetime import date as _date, timedelta

        from syndicate.features.shared.game_chip_scoreboard import build_game_chips
    except Exception:
        _LOGGER.exception("CANDIDATE_SLATE_CHIPS_IMPORT_FAILURE")
        return out

    try:
        base = _date.fromisoformat(str(selected_date))
    except ValueError:
        _LOGGER.exception("CANDIDATE_SLATE_BAD_DATE date=%s", selected_date)
        return out
    window = [(base + timedelta(days=offset)).isoformat() for offset in range(_CHIP_WINDOW_DAYS + 1)]

    for sport in sports:
        collected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for query_date in window:
            try:
                chips = build_game_chips(query_date, [sport]) or []
            except Exception:
                # One bad date must not cost the others their slate.
                _LOGGER.exception("CANDIDATE_SLATE_CHIPS_FAILURE sport=%s date=%s", sport, query_date)
                continue
            for chip in chips:
                if not isinstance(chip, Mapping):
                    continue
                # A single-date query already returns forward fixtures, so the
                # window overlaps heavily -- dedupe or the same game is compared
                # many times per candidate.
                key = str(chip.get("game_key") or "") or f"{chip.get('matchup')}|{chip.get('start_time_utc')}"
                if key in seen:
                    continue
                seen.add(key)
                collected.append(dict(chip))
        out[sport] = collected
    return out
