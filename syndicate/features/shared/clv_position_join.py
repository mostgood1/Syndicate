"""Pair a COMMITTED position with the opening price recorded for its market.

WHY THIS EXISTS, and why it is being built on day 1 of paper trading rather
than at the end of the window.

Stage C's gate is CLV -- a market gets real money only when its paper orders
beat the closing line. `clv_opening_ledger` already records the opening for
every board row (3,105 records on 2026-08-22, `unkeyable=0`), and `clv_join`
already resolves a close. The piece that has never existed is the one in the
middle: **nothing connects a position we committed to the opening recorded for
the market we committed it in.** Stage A and Stage B carry no reference to
`clv_opening_ledger` at all.

That gap is invisible while it accumulates. Every day of paper trading looks
productive and produces orders that may or may not be joinable, and the way
you find out is at the end, when the analysis returns nothing. This repo has
already paid for that exact shape twice: the settlement join keyed on an id
that changed whenever the price moved, and reported **4,560 `no_key_match` of
8,276** with no per-reason breakdown. `_opening_key`'s own docstring hands the
problem forward -- "the mapping ... must be measured against real data before
any CLV number is published". This measures it.

**TWO PATHS ON PURPOSE, and the comparison between them IS the measurement.**

  stamped   `commit_portfolio` calls `opening_key_for_row` on the SAME row, in
            the SAME run, a few lines after `record_openings` wrote that row's
            opening. Exact by construction; it cannot drift because there is
            nothing between the two calls to drift.
  derived   `opening_key_for_position` rebuilds the key from the STORED
            position. This is the path every already-placed order needs, and
            the path that fails silently if any field is transformed on its way
            into the position.

Implementing only the stamp would fix the future and teach us nothing about the
orders already on disk -- and worse, it would make the derivation permanently
untested, because nothing would ever exercise it. Running both over the same
plan turns the derivation into a checkable claim: `derivation_agrees` should
equal the number of keyable positions, and any disagreement names a field.

**THE DERIVED PATH CALLS `_opening_key` RATHER THAN REIMPLEMENTING IT.** Every
normalisation the ledger applies -- lowercasing `side` and `market`, coercing
`line` through `float` -- is shared by construction, so case and format drift
are impossible rather than tested for. What remains hand-written is exactly one
step: the position stores the book as `book`, and the ledger reads it from
`quote.bookmaker`. That remap is the only place a bug can live, which is why it
is the only thing this module does by hand.

Nothing here is guessed. Every position that does not resolve carries a named
reason and is counted, on the same principle as `clv_join`: an unresolved row
is a datum, not a silent drop.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "opening_key_for_row",
    "opening_key_for_position",
    "join_positions_to_openings",
    "join_report_line",
]


def opening_key_for_row(row: Mapping[str, Any]) -> str | None:
    """The opening ledger's key for a BOARD row, as the ledger itself computes it."""
    from syndicate.features.shared.clv_opening_ledger import _opening_key

    return _opening_key(row)


def opening_key_for_position(position: Mapping[str, Any]) -> str | None:
    """The opening ledger's key for a STORED position.

    Reshapes the position back into the row shape `_opening_key` reads, then
    defers to it. The reshape is one field: `book` -> `quote.bookmaker`.

    Returns None when the position cannot be keyed at all -- no `event_id` or no
    `market` -- which is the ledger's own rule and not a separate one, so a row
    the ledger refused to record is a position this refuses to key, for the
    same reason and by the same code.
    """
    from syndicate.features.shared.clv_opening_ledger import _opening_key

    return _opening_key(
        {
            "event_id": position.get("event_id"),
            "market": position.get("market"),
            "player_name": position.get("player_name"),
            "segment": position.get("segment"),
            "side": position.get("side"),
            "line": position.get("line"),
            # THE ONE HAND-WRITTEN STEP. `commit_portfolio` flattens
            # `quote.bookmaker` onto the position as `book`; the ledger reads it
            # nested. If the join ever reports `no_key_match` on rows that
            # plainly exist in the ledger, look here first.
            "quote": {"bookmaker": position.get("book")},
        }
    )


def join_positions_to_openings(
    positions: Sequence[Mapping[str, Any]],
    *,
    date: str,
    root: Any = None,
    openings: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Match each position to its recorded opening. Counters, then rows.

    `openings` is injectable so a caller that already loaded them (or a test)
    does not re-read the file; absent, they are loaded for `date`.

    Every counter is returned on every call, including when it is zero. A
    counter that only appears when it fires cannot distinguish "ran and matched
    nothing" from "never ran" -- the lesson `#373`, `#381`, `#397` and `#400`
    each learned separately, and the one `record_openings` states in its own
    docstring.
    """
    from syndicate.features.shared.clv_opening_ledger import load_openings

    records = list(openings) if openings is not None else load_openings(date, root=root)
    by_key: dict[str, Mapping[str, Any]] = {}
    for record in records:
        key = record.get("key")
        if isinstance(key, str) and key:
            # First wins, matching the ledger's own first-sighting-only contract.
            by_key.setdefault(key, record)

    joined: list[dict[str, Any]] = []
    unkeyable = 0
    no_key_match = 0
    stamped_present = 0
    stamped_matched = 0
    derived_matched = 0
    derivation_agrees = 0
    derivation_disagrees = 0
    disagreement_examples: list[dict[str, Any]] = []

    for position in positions:
        stamped = position.get("opening_key")
        stamped = stamped if isinstance(stamped, str) and stamped else None
        derived = opening_key_for_position(position)

        if stamped is not None:
            stamped_present += 1
            if stamped in by_key:
                stamped_matched += 1
        if derived is not None and derived in by_key:
            derived_matched += 1

        # The comparison this module exists to make. Only meaningful where both
        # keys exist -- a position with no stamp is not a disagreement, it is an
        # older position.
        if stamped is not None and derived is not None:
            if stamped == derived:
                derivation_agrees += 1
            else:
                derivation_disagrees += 1
                # Carry a bounded sample rather than a count alone: a count says
                # the derivation is wrong, an example says WHICH FIELD is wrong,
                # and the second is the only one anybody can act on.
                if len(disagreement_examples) < 5:
                    disagreement_examples.append(
                        {
                            "position_key": position.get("position_key"),
                            "stamped": stamped,
                            "derived": derived,
                        }
                    )

        key = stamped or derived
        if key is None:
            unkeyable += 1
            joined.append({**position, "opening": None, "join_reason": "unkeyable"})
            continue
        opening = by_key.get(key)
        if opening is None:
            no_key_match += 1
            joined.append({**position, "opening": None, "join_reason": "no_key_match"})
            continue
        joined.append(
            {
                **position,
                "opening": {
                    "key": key,
                    "price": opening.get("price"),
                    "bookmaker": opening.get("bookmaker"),
                    "captured_at": opening.get("captured_at"),
                    "book_prices": opening.get("book_prices"),
                },
                "join_reason": "matched",
            }
        )

    matched = sum(1 for row in joined if row["join_reason"] == "matched")
    return {
        "date": date,
        "positions": len(positions),
        "openings_loaded": len(records),
        "openings_distinct_keys": len(by_key),
        "matched": matched,
        "no_key_match": no_key_match,
        "unkeyable": unkeyable,
        "match_rate": round(matched / len(positions), 4) if positions else None,
        # The derivation's report card. `stamped_present` being 0 on a plan
        # means it predates stamping, and then `derived_matched` is the ONLY
        # evidence about whether those orders are joinable at all.
        "stamped_present": stamped_present,
        "stamped_matched": stamped_matched,
        "derived_matched": derived_matched,
        "derivation_agrees": derivation_agrees,
        "derivation_disagrees": derivation_disagrees,
        "disagreement_examples": disagreement_examples,
        "rows": joined,
    }


def join_report_line(report: Mapping[str, Any]) -> str:
    """One log line. `logger.info` never reaches Render's collector -- print this."""
    return (
        "[clv_position_join] CLV_POSITION_JOIN"
        f" date={report.get('date')}"
        f" positions={report.get('positions')}"
        f" openings={report.get('openings_loaded')}"
        f" matched={report.get('matched')}"
        f" no_key_match={report.get('no_key_match')}"
        f" unkeyable={report.get('unkeyable')}"
        f" match_rate={report.get('match_rate')}"
        f" stamped={report.get('stamped_present')}"
        f" stamped_matched={report.get('stamped_matched')}"
        f" derived_matched={report.get('derived_matched')}"
        f" derivation_agrees={report.get('derivation_agrees')}"
        f" derivation_disagrees={report.get('derivation_disagrees')}"
    )
