"""Settle every NHL row in the priced population, from the NHL's own API.

`scripts/bucket_search.py::grade_population` has no NHL grader of its own for props, periods
or the alternate / three-way markets, and its full-game path depends on a scoreboard chip
nobody has verified for NHL. This is the `extra_settler(shaped, view)` it consults first:

    None                  not an NHL record; `grade_population` carries on as before
    (result, reason)      result 'win' | 'loss' | 'push', or None with a NAMED reason

WHAT IT HANDLES: EVERY NHL record -- h2h / spreads / totals (and `_alt`), `h2h_3_way`
(regulation), periods p1..p3, and player props (points, goals, assists, shots on goal, blocked
shots, saves, anytime goal scorer). Unlike `population_outcomes_espn`, full-game h2h / spreads
/ totals do NOT pass through: one source (the NHL API's final, shootout credit included) grades
every NHL line, so a moneyline and its puck line cannot be settled from two different scores.

ONE IMPLEMENTATION. Reading, game matching, market classification and the hockey rules are
`bet_status_nhl`'s -- the same code paper settlement grades orders with. This module adds only
what the scorecard needs on top: a kickoff check before any read, `not_final` reasons where
paper settlement would report "not decided yet", and the win / loss / push mapping through
`bet_status.resolve_bet_status`, the one grader.

REASONS a published scorecard will show (each a different job):
    permanent   unmapped_market, nhl_prop_market_not_mapped, nhl_prop_needs_full_game,
                unsupported_segment:<seg>, team_totals_needs_a_per_team_score,
                nhl_team_unresolved, game_not_in_nhl_schedule, nhl_game_ambiguous,
                nhl_game_start_time_mismatch, home_away_disagree_between_sources,
                nhl_game_postponed_or_cancelled, dnp_void, nhl_player_name_unmatched,
                nhl_stat_not_in_box, nhl_limited_scoring_game
    transient   not_started, game_not_final, segment_not_final, and every `*_unavailable`
                (`model_scorecard.NOT_FINAL_MARKERS` holds a date open on those)
"""

from __future__ import annotations

import collections
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from syndicate.features.shared.bet_status import (
    FULL_GAME_SEGMENT,
    STATUS_LIVE_TIED,
    STATUS_LOST,
    STATUS_WON,
    resolve_bet_status,
)
from syndicate.features.shared.bet_status_nhl import (
    NhlFeed,
    classify_nhl_order,
    resolve_classified,
)

__all__ = ["GRADER_VERSION", "SPORTS", "NhlPopulationSettler"]

GRADER_VERSION = "nhl/1"
SPORTS = frozenset({"nhl"})

R_NO_COMMENCE = "no_commence_time"
R_NOT_STARTED = "not_started"
R_GAME_NOT_FINAL = "game_not_final"
R_SEGMENT_NOT_FINAL = "segment_not_final"
R_UNSETTLEABLE = "unsettleable_side_or_line"

_RESULTS = {STATUS_WON: "win", STATUS_LOST: "loss", STATUS_LIVE_TIED: "push"}


def _utcnow() -> datetime:
    """A seam for tests; the clock is read only to skip games that have not started."""
    return datetime.now(timezone.utc)


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if len(text) <= 10:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class NhlPopulationSettler:
    """`grade_population`'s `extra_settler` for NHL. `counters` records reads and sources."""

    def __init__(self, *, fetch_json: Callable[[str], Any] | None = None, cache_dir: Path | str | None = None) -> None:
        self.feed = NhlFeed(fetch_json=fetch_json, cache_dir=cache_dir)
        self.counters: collections.Counter[str] = collections.Counter()

    def __call__(self, shaped: Mapping[str, Any], view: Mapping[str, Any] | None = None) -> tuple[str | None, str | None] | None:
        if not self.handles(shaped):
            return None
        return self.settle(shaped)

    def handles(self, shaped: Mapping[str, Any]) -> bool:
        return isinstance(shaped, Mapping) and " ".join(str(shaped.get("sport") or "").lower().split()) in SPORTS

    def settle(self, shaped: Mapping[str, Any]) -> tuple[str | None, str | None]:
        # PERMANENT BEFORE TRANSIENT: nothing is read for a row that can never grade.
        classified = classify_nhl_order(shaped)
        if classified.get("unavailable_reason"):
            return None, str(classified["unavailable_reason"])

        kickoff = _parse_utc(shaped.get("commence_time"))
        if kickoff is None:
            return None, R_NO_COMMENCE
        if kickoff > _utcnow():
            return None, R_NOT_STARTED

        resolved = resolve_classified(shaped, classified, self.feed, None)
        if resolved.get("unavailable_reason"):
            return None, str(resolved["unavailable_reason"])
        if not resolved.get("started", True):
            return None, R_NOT_STARTED
        if not resolved.get("is_final"):
            segment_bet = classified["segment"] != FULL_GAME_SEGMENT or classified["market"] == "h2h_3_way"
            return None, R_SEGMENT_NOT_FINAL if segment_bet else R_GAME_NOT_FINAL

        status = resolve_bet_status(
            market=classified["market"],
            side=resolved.get("side", shaped.get("side")),
            line=resolved.get("line", shaped.get("line")),
            current_value=resolved.get("current_value"),
            is_final=True,
        )
        result = _RESULTS.get(status.get("status"))
        if result is None:
            return None, str(status.get("unavailable_reason") or R_UNSETTLEABLE)
        source = str(resolved.get("source") or "nhl_api")
        self.counters[f"graded_from:{source}"] += 1
        return result, source
