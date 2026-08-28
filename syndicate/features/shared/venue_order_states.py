"""One status vocabulary for every venue that can hold a live order.

WHY THIS IS SHARED RATHER THAN PER-VENUE.

`kalshi_orders` and `polymarket_us_orders` each grew their own copy of these
three sets, and they drifted. Measured 2026-08-27, before this module existed:

    concept   kalshi                              polymarket adds
    filled    executed filled matched closed      complete
    resting   resting pending open queued         live new
              accepted active
    dead      canceled cancelled expired          failed voided
              rejected

So the SAME venue status meant different things depending on which file read
it. A row coming back `complete` was a fill on Polymarket and `unknown` on
Kalshi; `failed` was dead on one and unmapped on the other. Neither venue
publishes a promise that it will never use the other's words, and both readers
feed the same reconciler and the same ledger.

WHY THE UNION, AND WHY THAT IS THE SAFE DIRECTION.

`unknown` is not a harmless default here. An unmapped status leaves the row
untouched, the row stays unreconciled, and an unreconciled order BLOCKS LIVE
EXECUTION ON EVERY VENUE -- measured 2026-08-25T16:40:00Z, when one resting
Polymarket order blocked both scopes at once. So a status that is unmapped
merely because it was written into the other file is a live outage waiting on
a word.

Widening to the union only ever moves a status OUT of `unknown` into a meaning
both files already agreed it had. It cannot silently re-map a status that was
previously mapped: the three sets are disjoint, which `test_venue_order_states`
asserts rather than assumes.

WHAT DOES NOT BELONG HERE. Anything a venue means only in its own dialect --
Polymarket's `ORDER_STATE_` enum prefixes, Kalshi's `_fp` count fields -- stays
in that venue's module. This is the shared vocabulary, not a shared parser.
"""

from __future__ import annotations


# THE TRADE HAPPENED. Note `closed` and `complete` are both here: they are the
# words an exchange uses for an order that is done, and "done" for an order
# that reached the book means filled.
VENUE_FILLED_STATUSES = frozenset(
    {"executed", "filled", "matched", "closed", "complete"}
)

# STILL WORKING. May yet trade, so reconciliation must leave the row alone and
# the page must keep showing it as live exposure.
VENUE_RESTING_STATUSES = frozenset(
    {"resting", "pending", "open", "queued", "accepted", "active", "live", "new"}
)

# WILL NEVER TRADE. Distinct from resting because the consequences are
# opposite: a dead order can be cleared, a resting one must not be.
VENUE_DEAD_STATUSES = frozenset(
    {"canceled", "cancelled", "expired", "rejected", "failed", "voided"}
)


def classify(raw_status: str) -> str:
    """A venue status word -> `filled` / `resting` / `dead` / `unknown`.

    CASE AND SURROUNDING WHITESPACE ONLY. Prefix stripping is the caller's job
    because it is venue dialect: Polymarket ships `ORDER_STATE_CANCELED` and
    Kalshi ships `canceled`, and the rule for taking a prefix off safely (whole
    known prefixes, never a split on the last underscore) belongs next to the
    venue that needs it. See `polymarket_us_orders.venue_order_view` for why
    the loose version is dangerous.

    RETURNS `unknown` FOR ANYTHING UNRECOGNISED, which is a real answer and the
    only one that makes reconciliation leave a row untouched. Never guess a
    direction here.
    """
    value = str(raw_status or "").strip().lower()
    if not value:
        return "unknown"
    if value in VENUE_FILLED_STATUSES:
        return "filled"
    if value in VENUE_RESTING_STATUSES:
        return "resting"
    if value in VENUE_DEAD_STATUSES:
        return "dead"
    return "unknown"
