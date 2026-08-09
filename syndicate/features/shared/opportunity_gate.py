"""ONE place that decides whether a row belongs on the board (#245).

WHY THIS EXISTS
---------------
Ten consecutive fixes (#235-#244) each corrected a real defect and each landed
in a DIFFERENT layer: a producer (#236), the transport (#237, #239), enrichment
(#238), a cache (#241), the template (#240, #242), lane logic (#243, #244).
Nothing anywhere answered the question "is this row fit to show?", so every new
symptom needed a new guard in a new place -- and the guards could not even agree
with each other, to the point that #244's staleness rule had to be written twice,
once in Python and once in JavaScript, because the Python one could not be
trusted to have run.

That is the actual bug. This module is the fix: every eligibility rule, named,
in one function, returning an explicit verdict with its reasons. Callers do not
re-derive any of it -- not the enrichment, not the API, and above all not the
template.

DESIGN RULES, so this does not rot back into the same shape
-----------------------------------------------------------
1. PURE. A row, its quote, and a clock in; a verdict out. No I/O, no artifact
   reads, no imports from the feature tree. That is what makes it cheap enough
   to run at SERVE time as well as build time -- which is what removes the need
   for a client-side copy, which is what killed the last version.
2. EXPLICIT REASONS. Never a bare boolean. A row excluded for a reason nobody
   can read is how "the board looks empty" becomes a week of archaeology.
3. NOTHING IS DROPPED SILENTLY. Every row lands in a lane, including the bad
   ones. A board that hides its rejects lies in the opposite direction from one
   that shows junk, and is harder to debug.
4. JUDGED ON THE BOOK CLOCK, never our capture clock. We may have looked a
   second ago; what matters is whether the book has moved the number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

# A book re-prices a LIVE market every few minutes. Past this, on a game that is
# actually in progress, the market is suspended or already settled. Measured
# 2026-08-06: the board served Luis Arraez and J.T. Realmuto at is_live=True
# with a book age of 30,556s (8.5 hours), naming pitchers pulled hours earlier.
LIVE_MARKET_MAX_AGE_SECONDS = 900.0

# Pregame prices are allowed to sit still -- books post early and leave numbers
# alone. This is only a ceiling against a price so old the slate has moved on.
PREGAME_MARKET_MAX_AGE_SECONDS = 86_400.0

# `game_state` is not normalised across sports. Production carries "live",
# "In Progress", "scheduled", "Pre-Game", a bare clock ("3:39"), and a score
# line ("66-65 | 3:39 - 4th"). Only the pregame and final words are reliably
# identifiable, so those are matched explicitly and anything else with is_live
# set is treated as in progress.
_PREGAME_TOKENS = frozenset({"", "scheduled", "pre-game", "pregame", "upcoming", "not started", "warmup", "delayed"})
_FINAL_TOKENS = frozenset({"final", "finished", "completed", "game over", "postponed", "cancelled", "canceled", "suspended"})

LANE_OPPORTUNITY = "opportunity"
LANE_WATCHLIST = "watchlist"
LANE_DEAD = "dead"
LANE_REJECTED = "rejected"


@dataclass(frozen=True)
class GateVerdict:
    """Why a row is where it is. Serialised onto the row; never recomputed."""

    lane: str
    market_state: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    book_age_seconds: float | None = None
    fair_method: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane,
            "market_state": self.market_state,
            "reasons": list(self.reasons),
            "book_age_seconds": self.book_age_seconds,
            "fair_method": self.fair_method,
        }


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed  # NaN


def game_state_of(row: Mapping[str, Any]) -> str:
    """`pregame` / `live` / `final`, from whatever this sport calls it."""
    state = _text(row.get("game_state") or row.get("status_display") or row.get("status_context"))
    if state in _FINAL_TOKENS or any(token in state for token in ("final", "postponed")):
        return "final"
    if state in _PREGAME_TOKENS:
        return "pregame"
    # is_live is the only cross-sport boolean, but it is set on rows whose
    # game_state still says "scheduled" -- so the state text wins when it is a
    # word we recognise, and is_live only decides the ambiguous rest.
    return "live" if row.get("is_live") else "pregame"


def _unknown_state_demotion_enabled() -> bool:
    """Off-switch for #298's rule. Read per call, never cached.

    Three reasons this exists rather than the rule being unconditional:

    1. It is the pattern its neighbours already use
       (SYNDICATE_SHORTLIST_STALE_KICKOFF_SECONDS and friends), and a rule that
       behaves differently from the ones beside it is a trap for the next reader.
    2. It is the only time-dependent rule in an otherwise total function, so
       tests that pin a fixture to a fixed date would silently start failing on
       a later calendar day -- the exact wall-clock time-bomb documented in
       `test_layer2_shortlist_wiring.py` ("a wiring test must not depend on the
       day it is run"), which this rule reintroduced one file away.
    3. It can DROP rows from the opportunity lane. A new rule that removes
       production rows should be disableable without a deploy.

    Defaults ON: absent means enabled, because the defect it prevents (a market
    for an already-started game ranking as pregame) is live and measured, and
    an off-by-default guard is not a guard. `0`/`false`/`no`/`off` disable it.
    """
    import os

    raw = str(os.environ.get("SYNDICATE_GATE_DEMOTE_UNKNOWN_GAME_STATE") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _kickoff_has_passed(row: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """Does this row's OWN clock say the game has started? #298/#300.

    Only ever used to decide whether an absent game state is a contradiction.
    Unparseable or missing `commence_time` returns **False** — the conservative
    answer, because this gates a demotion and an unreadable clock is not
    evidence that a game is under way.
    """
    raw = str(row.get("commence_time") or "").strip()
    if not raw:
        return False
    try:
        kickoff = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) >= kickoff


def has_game_state(row: Mapping[str, Any]) -> bool:
    """Did anything actually TELL us this game's state? #298/#300.

    `game_state_of` must return one of three words, so its last line resolves
    the ambiguous rest to `pregame` — which means a row nothing matched is
    indistinguishable from a row confirmed not to have started. That is the
    permissive branch, and it is the one an unmatched row lands in.

    The cost is not hypothetical. `build_layer2_rows` sets `game_state`/
    `is_live` only inside `if game:`, so a row whose team names never matched a
    chip carries neither, reads as `pregame`, and is **exempted from the
    staleness floor rather than failing it** — the guard cannot reject what it
    cannot see. Measured 2026-08-09 15:29Z: 12 of 200 displayed rows (6.0%,
    all soccer, all one match) had no game state, and all 12 were for a match
    already 48 minutes old, four of them `player_first_goal_scorer` — a market
    that a single goal settles or reprices violently.

    Resolving the alias gap fixes today; this fixes the mechanism, which
    otherwise grants a free pass to every future unmatched team in any sport.
    The rate is not stable; the mechanism is.
    """
    if _text(row.get("game_state") or row.get("status_display") or row.get("status_context")):
        return True
    # `is_live` is only affirmative when True. False/None is the same silence,
    # because nothing distinguishes "told us it is not live" from "never set".
    if row.get("is_live") is True:
        return True
    return isinstance(row.get("game"), Mapping) and bool(row.get("game"))


def has_identity(row: Mapping[str, Any]) -> bool:
    """Can this row ever be joined to a price?

    A prop needs a player; a game market needs an event or a team pair. Without
    one it can never be priced no matter how healthy the pipeline is, so it is
    rejected rather than left to look like a coverage gap.
    """
    entity = _text(row.get("player_name") or row.get("entity_name") or row.get("entity"))
    event = _text(row.get("event_id") or row.get("game_pk") or row.get("game_id"))
    teams = _text(row.get("home_team")) and _text(row.get("away_team"))
    return bool(entity or event or teams)


def evaluate(
    row: Mapping[str, Any],
    quote: Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> GateVerdict:
    """The single eligibility decision. Cheap and total.

    Total in the mathematical sense: every row gets a lane, including rejects.

    `now` is injectable so the one time-dependent rule (#298's kickoff check)
    stays deterministic under test. Defaulting it here rather than at the call
    sites keeps every existing caller unchanged.
    """
    reasons: list[str] = []
    quote = quote if isinstance(quote, Mapping) else (row.get("quote") if isinstance(row.get("quote"), Mapping) else None)
    state = game_state_of(row)

    if not has_identity(row):
        return GateVerdict(lane=LANE_REJECTED, market_state=state, reasons=("no_identity",))

    if state == "final":
        return GateVerdict(lane=LANE_DEAD, market_state=state, reasons=("game_final",))

    # #298/#300. UNKNOWN MUST NOT INHERIT THE PERMISSIVE BRANCH -- but only
    # where "unknown" is actually a contradiction. `game_state_of` resolves the
    # ambiguous rest to `pregame`, and for a fixture 16 days out with no chip
    # yet that is CORRECT: it really has not started. Demoting those would
    # delete the largest legitimate population on the board (146 of 230 rows
    # were far-out Serie A steam) to fix twelve.
    #
    # The contradiction is a row with no confirmed state whose own kickoff has
    # PASSED. Then `pregame` is not a default, it is a false claim, and every
    # staleness rule below reads it. Measured 2026-08-09: all 12 such rows were
    # for a match 48 minutes old, four of them `player_first_goal_scorer`.
    #
    # Watchlist, not rejected: the row has identity and a posted price, it is
    # UNVERIFIABLE rather than invalid -- the same category as
    # `no_market_posted` below. What must not happen is it ranking as an
    # opportunity, and what must happen is that it is COUNTABLE (#306) --
    # `no_game_state` distinguishes "the guard dropped it" from "the guard
    # never saw it", which otherwise render as the same zero.
    if _unknown_state_demotion_enabled() and not has_game_state(row) and _kickoff_has_passed(row, now=now):
        return GateVerdict(lane=LANE_WATCHLIST, market_state="unknown", reasons=("no_game_state",))

    price = _number(quote.get("price")) if quote else None
    if quote is None or price is None:
        # Not a defect: a fixture whose books have not posted yet is a real
        # thing to watch, and 63% of the board was in exactly this state.
        return GateVerdict(lane=LANE_WATCHLIST, market_state=state, reasons=("no_market_posted",))

    book_age = _number(quote.get("book_age_seconds"))
    fair_method = _text(quote.get("fair_method")) or ("two_sided" if quote.get("fair_probability") is not None else None)

    if state == "live":
        if book_age is None:
            # No book clock on an in-progress game is not evidence of life.
            reasons.append("live_no_book_clock")
            return GateVerdict(LANE_DEAD, state, tuple(reasons), book_age, fair_method)
        if book_age > LIVE_MARKET_MAX_AGE_SECONDS:
            reasons.append("live_market_stale")
            return GateVerdict(LANE_DEAD, state, tuple(reasons), book_age, fair_method)
    elif book_age is not None and book_age > PREGAME_MARKET_MAX_AGE_SECONDS:
        reasons.append("pregame_market_stale")
        return GateVerdict(LANE_DEAD, state, tuple(reasons), book_age, fair_method)

    if fair_method is None:
        # Priced but not de-viggable (a one-sided market). Still an
        # opportunity -- a book is quoting it right now -- but flagged so the
        # board can say WHY the fair column is empty instead of showing a blank.
        reasons.append("fair_unavailable")
    return GateVerdict(LANE_OPPORTUNITY, state, tuple(reasons), book_age, fair_method)


def annotate(row: dict[str, Any], quote: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Stamp the verdict onto a row. The ONLY way lanes get set.

    Never raises: a gate that can break the board is worse than no gate.
    """
    try:
        verdict = evaluate(row, quote)
        row["board_lane"] = verdict.lane
        row["market_state"] = verdict.market_state
        row["gate"] = verdict.to_dict()
    except Exception:
        row.setdefault("board_lane", LANE_WATCHLIST)
    return row
