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

A LIVE ROW IS GRADED ONLY IF ITS OWN BOOK WAS STILL QUOTING IT (`nhl/2`, todo #848, 2026-11-18). The board can
carry a book's last PREGAME quote into a live row: BetRivers never returned an NHL goals quote after puck drop on
10-20 or 11-10, yet its pregame "2+ goals" prices were the live best price, because the in-play window is read
on the market's newest capture, not per book. Graded on the final, those rows were wins at prices no book was
offering: 780 of the 782 live `goals` rows at EV >= 10% (10-14..11-18 board dates) had a quote its book never
returned after the game started, and they made NHL's ev10+ bands read +153%. So a live row whose book quote was
last seen more than `LIVE_QUOTE_SEEN_MAX_SECONDS` before the row was sighted (the book quote store's last-seen
sidecar, `nhl_source/tracking/book_quotes/<date>.state.json`) is VOID, per line: `live_quote_unseen_at_sighting`.
A row the sidecar has no entry for, or a view without `sighted_at` / `bookmaker`, is graded as before and
COUNTED (`counters["live_quote_unknown:<why>"]`); an unknown is never read as stale. DEFAULT-OFF: only with
`SYNDICATE_SCORECARD_848_GRADING` on (version `nhl/2`); absent, no sidecar is read and `nhl/1` grades as before.

REASONS a published scorecard will show (each a different job):
    permanent   live_quote_unseen_at_sighting,
                unmapped_market, nhl_prop_market_not_mapped, nhl_prop_needs_full_game,
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
import json
import math
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

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
from syndicate.features.shared.population_outcomes_soccer import grading_848_on

__all__ = ["GRADER_VERSION", "SPORTS", "NhlPopulationSettler"]

# nhl/2 (todo #848, 2026-11-18): a live row whose own book quote was not seen at its sighting is void -- ONLY with
# `SYNDICATE_SCORECARD_848_GRADING` on (`population_outcomes_soccer.grading_848_on`, the one key for both #848
# fixes). Absent grades exactly as `nhl/1`; the reason it ships default-off is written beside that function.
GRADER_VERSION = "nhl/2" if grading_848_on() else "nhl/1"
SPORTS = frozenset({"nhl"})

R_NO_COMMENCE = "no_commence_time"
R_NOT_STARTED = "not_started"
R_GAME_NOT_FINAL = "game_not_final"
R_SEGMENT_NOT_FINAL = "segment_not_final"
R_UNSETTLEABLE = "unsettleable_side_or_line"
R_LIVE_QUOTE_UNSEEN = "live_quote_unseen_at_sighting"

# The board's own in-play freshness window for NHL props (`SYNDICATE_INPLAY_OVERLAY_MAX_PRICE_AGE_SECONDS`
# default, `book_grid_artifact.is_inplay_fresh_row`), applied here to the row's OWN book quote.
LIVE_QUOTE_SEEN_MAX_SECONDS = 300.0
QUOTE_STATE_PATH_TEMPLATE = "nhl_source/tracking/book_quotes/{date}.state.json"
_CENTRAL = ZoneInfo("America/Chicago")

_RESULTS = {STATUS_WON: "win", STATUS_LOST: "loss", STATUS_LIVE_TIED: "push"}


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.replace(".", " ").replace("-", " ").split())


def _line_key(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _quote_identity(event_id: Any, book: Any, segment: Any, market: Any, side: Any, player: Any,
                    line: Any) -> tuple[Any, ...]:
    """One quote's identity, folded so the recorder's spelling meets the book quote store's.

    The store keys a quote `nhl|<kind>|<event>|<book>|<segment>|<MARKET>|<selection>|<Player Name>|<line>`
    (`odds_book_quotes._quote_key`); the recorder carries the same event id, a lower-cased market and a
    normalised player name, and `None` where the store writes `nan`.
    """
    return (str(event_id or ""), _fold(book), _fold(segment) or "full", _fold(market), _fold(side), _fold(player),
            _line_key(line))


def parse_quote_state(text: str | None) -> dict[tuple[Any, ...], str]:
    """`<date>.state.json` -> {quote identity: last-seen ISO}. Entries without a last-seen are left out."""
    out: dict[tuple[Any, ...], str] = {}
    if not text:
        return out
    try:
        payload = json.loads(text)
    except ValueError:
        return out
    if not isinstance(payload, Mapping):
        return out
    for key, value in payload.items():
        parts = str(key).split("|")
        if len(parts) < 9 or not isinstance(value, (list, tuple)) or len(value) < 3 or not value[2]:
            continue
        identity = _quote_identity(parts[2], parts[3], parts[4], parts[5], parts[6], parts[7], parts[8])
        out[identity] = str(value[2])
    return out


def _local_fetch_export(relative_path: str) -> str | None:
    from syndicate.features.shared.refresh_state_store import data_root

    try:
        return (data_root() / Path(relative_path)).read_text(encoding="utf-8")
    except (OSError, RuntimeError):
        return None


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

    def __init__(self, *, fetch_json: Callable[[str], Any] | None = None, cache_dir: Path | str | None = None,
                 fetch_export: Callable[[str], str | None] | None = None) -> None:
        self.feed = NhlFeed(fetch_json=fetch_json, cache_dir=cache_dir)
        self.counters: collections.Counter[str] = collections.Counter()
        # `fetch_export(relative_path) -> text | None`: the scorecard hands its web-export reader; the default
        # reads this service's own data root.
        self._fetch_export = fetch_export or _local_fetch_export
        self._quote_states: dict[str, dict[tuple[Any, ...], str]] = {}

    def __call__(self, shaped: Mapping[str, Any], view: Mapping[str, Any] | None = None) -> tuple[str | None, str | None] | None:
        if not self.handles(shaped):
            return None
        result, reason = self.settle(shaped)
        if result is None or not grading_848_on():
            return result, reason
        # Only a GRADED row is checked: a game still pending keeps its transient reason, and a void is final.
        if self.live_quote_unseen(shaped, view):
            return None, R_LIVE_QUOTE_UNSEEN
        return result, reason

    def handles(self, shaped: Mapping[str, Any]) -> bool:
        return isinstance(shaped, Mapping) and " ".join(str(shaped.get("sport") or "").lower().split()) in SPORTS

    def _quote_state(self, day: str) -> dict[tuple[Any, ...], str]:
        if day not in self._quote_states:
            text = self._fetch_export(QUOTE_STATE_PATH_TEMPLATE.format(date=day))
            self._quote_states[day] = parse_quote_state(text)
            self.counters["quote_state_read" if text else "quote_state_missing"] += 1
        return self._quote_states[day]

    def live_quote_unseen(self, shaped: Mapping[str, Any], view: Mapping[str, Any] | None) -> bool:
        """True when a LIVE row's own book quote was last seen more than the window before the row was sighted.

        The sidecar is end-of-day, so `last_seen < sighted - window` means the book returned that quote neither
        in the window before the sighting nor at any time after it. A later sighting (`last_seen >= sighted`)
        keeps the row: the book was still quoting.
        """
        view = view or {}
        if str(view.get("phase") or "").strip().lower() != "live":
            return False
        sighted, book = _parse_utc(view.get("sighted_at")), str(view.get("bookmaker") or "").strip()
        kickoff = _parse_utc(shaped.get("commence_time"))
        if sighted is None or not book or kickoff is None:
            self.counters["live_quote_unknown:no_view_fields"] += 1
            return False
        identity = _quote_identity(shaped.get("event_id"), book, shaped.get("segment"), shaped.get("market"),
                                   shaped.get("side"), shaped.get("player_name"), shaped.get("line"))
        days = []
        for moment in (kickoff.astimezone(_CENTRAL), kickoff, kickoff.astimezone(_CENTRAL) - timedelta(days=1)):
            day = moment.date().isoformat()
            if day not in days:
                days.append(day)
        last_seen = None
        for day in days:
            last_seen = self._quote_state(day).get(identity)
            if last_seen:
                break
        seen = _parse_utc(last_seen) if last_seen else None
        if seen is None:
            self.counters["live_quote_unknown:no_state_entry"] += 1
            return False
        if seen < sighted - timedelta(seconds=LIVE_QUOTE_SEEN_MAX_SECONDS):
            self.counters["live_quote_unseen"] += 1
            return True
        self.counters["live_quote_seen"] += 1
        return False

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
