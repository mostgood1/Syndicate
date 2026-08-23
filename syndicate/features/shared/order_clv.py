"""Stage C's actual gate input: what OUR placed orders got, against the close.

The chain was one hop short. `clv_opening_ledger` records an opening,
`clv_join.compute_clv_for_date` pairs that opening with a close, and
`clv_position_join` connects a committed position to its opening. Nothing
connected a PLACED ORDER to a close, so the number Stage C gates on --
*did this bet beat the closing line* -- could not be computed for a single bet
we made.

**THIS COMPOSES RATHER THAN RE-RESOLVING.** `compute_clv_for_date` emits one row
per opening carrying `key`, and orders carry `opening_key`, so the join is a
dict lookup. Re-implementing close resolution here would mean a second copy of
the arrow-of-time check, the side-aware stamp logic and the different-book
fallback -- each of which cost a measurement to get right (25 of 25 rows once
paired a close captured BEFORE the opening and produced a confident `-5.215`
out of unrelated instants). One copy, reused.

**WHAT CHANGES vs THE OPENING'S CLV: the price.** `compute_clv_for_date` asks
what the market did from its first published price. This asks what WE got, from
the price actually filled. Those differ whenever we bet after the open, which is
almost always, and only the second one is evidence about the bettor.

**SCOPE IS NEVER POOLED.** `close_book_scope` distinguishes a same-book close
from a different book's, and the difference is not cosmetic -- measured
2026-08-14 across 150 openings: `different_book_close` +6.206 avg (29/32 beat),
`book_agnostic_close` +2.716 (18/27), `same_book` n=0. Pairing our book's entry
against another book's close compares a best-of-N draw to a single draw and is
biased upward regardless of whether the bet was good. So every aggregate here is
reported PER SCOPE, and the headline is same-book only. A single blended CLV
number would be exactly the flattering, wrong statistic Stage C exists to avoid.

**VENUE IS PART OF A BOOK'S IDENTITY AND IS ALWAYS IN THE GROUPING.** `paper2`
places its venue-restricted orders into the SAME ledger as the unrestricted
book, distinguished only by `venue` (`paper` vs `paper:kalshi`). Grouping by
market alone would drop a Kalshi bet and a DraftKings bet on the same market
into one bucket and average them -- destroying the exact comparison paper2
exists to produce, while still printing a confident per-market number. So
`venue` is forced into every aggregate on the same footing as
`close_book_scope`: both name WHICH BOOK OF BETS a number describes, and a
number that does not know which book it is about is not a measurement.

**AGGREGATED PER MARKET, NOT POOLED.** `_SAMPLE_SIZE_FOR_FULL_CREDIBILITY = 50`
is per market for a reason, and `learnings.md` 2026-08-20 records pooling
overstating significance 3.4x by counting rows as if they were bets. `n` rides
on every aggregate so a two-bet "market average" can never be mistaken for a
result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ["clv_for_orders", "order_clv_report_line"]

REASON_RESOLVED = "resolved"
REASON_UNKEYABLE = "unkeyable"
REASON_NO_CLOSE = "no_close_for_market"
REASON_NO_ENTRY_PRICE = "no_entry_price"
REASON_CLV_UNCOMPUTABLE = "clv_uncomputable"

SCOPE_SAME_BOOK = "same_book"


def _as_float(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.strip().replace("+", "")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _entry_price(order: Mapping[str, Any]) -> float | None:
    """What this bet actually got.

    `fill_price` over `requested_price`: the fill is what we hold. On a paper
    fill they are equal; on a live one they are not, and grading the request
    would credit us with slippage we never got.
    """
    filled = _as_float(order.get("fill_price"))
    return filled if filled is not None else _as_float(order.get("requested_price"))


def _scope_of(row: Mapping[str, Any]) -> str:
    """`close_book_scope` is absent on a genuine same-book pair -- it is only
    stamped when a FALLBACK was used. Absent therefore means same-book, and
    defaulting it to anything else would relabel the cleanest rows as the
    dirtiest."""
    return str(row.get("close_book_scope") or SCOPE_SAME_BOOK)


def clv_for_orders(
    orders: Sequence[Mapping[str, Any]],
    *,
    date: str,
    clv_rows: Sequence[Mapping[str, Any]] | None = None,
    unresolved_rows: Sequence[Mapping[str, Any]] | None = None,
    root: Any = None,
) -> dict[str, Any]:
    """Grade each order against the close. Per order, then per market, per scope.

    `clv_rows` is injectable so a caller that already ran `compute_clv_for_date`
    (or a test) does not recompute; absent, it is computed for every sport the
    orders touch.
    """
    from syndicate.features.shared.clv_join import clv_pct_from_prices
    from syndicate.features.shared.clv_position_join import opening_key_for_position

    if clv_rows is None:
        from syndicate.features.shared.clv_join import compute_clv_for_date

        sports = sorted(
            {
                str(order.get("sport") or "").strip().lower()
                for order in orders
                if str(order.get("sport") or "").strip()
            }
        )
        collected: list[Mapping[str, Any]] = []
        collected_unresolved: list[Mapping[str, Any]] = []
        for sport in sports:
            try:
                report = compute_clv_for_date(date, sport, root=root)
            except Exception:
                # One sport failing must not lose the others. The absence shows
                # up as `no_close_for_market` on that sport's orders, which is
                # the honest reading rather than a crash or a silent zero.
                continue
            collected.extend(report.get("rows") or [])
            # THE ATTRIBUTION, carried rather than discarded. An earlier version
            # of this function kept only `rows` and reported a flat
            # `no_close_for_market: 35` -- a number with no remedy attached,
            # while the reason for each of those 35 was already computed one
            # layer down. "Our book is absent from odds history" and "this
            # market family is not tracked at all" look identical under one name
            # and need completely different fixes.
            collected_unresolved.extend(report.get("unresolved_rows") or [])
        clv_rows = collected
        if unresolved_rows is None:
            unresolved_rows = collected_unresolved

    by_key: dict[str, Mapping[str, Any]] = {}
    for row in clv_rows or ():
        key = row.get("key")
        if isinstance(key, str) and key:
            by_key.setdefault(key, row)

    unresolved_by_key: dict[str, str] = {}
    for row in unresolved_rows or ():
        key = row.get("key")
        if isinstance(key, str) and key:
            unresolved_by_key.setdefault(key, str(row.get("reason") or ""))

    graded: list[dict[str, Any]] = []
    reasons: dict[str, int] = {}

    for order in orders:
        key = order.get("opening_key")
        key = key if isinstance(key, str) and key else opening_key_for_position(order)
        entry = _entry_price(order)

        def _row(reason: str, **extra: Any) -> None:
            reasons[reason] = reasons.get(reason, 0) + 1
            graded.append(
                {
                    "idempotency_key": order.get("idempotency_key"),
                    "position_key": order.get("position_key"),
                    "opening_key": key,
                    "sport": order.get("sport"),
                    "market": order.get("market"),
                    "side": order.get("side"),
                    "player_name": order.get("player_name"),
                    "book": order.get("book"),
                    # WHICH BOOK OF BETS this order belongs to -- `paper` for
                    # the unrestricted portfolio, `paper:kalshi` for paper2.
                    "venue": order.get("venue"),
                    "entry_price": entry,
                    "stake_dollars": _as_float(order.get("fill_stake_dollars"))
                    or _as_float(order.get("requested_stake_dollars")),
                    "reason": reason,
                    **extra,
                }
            )

        if entry is None:
            _row(REASON_NO_ENTRY_PRICE, close_price=None, clv_pct=None, close_book_scope=None)
            continue
        if key is None:
            _row(REASON_UNKEYABLE, close_price=None, clv_pct=None, close_book_scope=None)
            continue
        row = by_key.get(key)
        if row is None:
            # No close for this market -- and WHY, when the resolver told us.
            # `no_close_reason` distinguishes `no_market_in_history` (this
            # family is not tracked: h2h_lay, totals_alt, h2h_3_way,
            # spreads_alt) from `close_precedes_open` (a real close exists but
            # predates our opening) from an opening the resolver never saw at
            # all (None -- our book absent from the shard). Three different
            # problems; only the flat name made them look like one.
            _row(
                REASON_NO_CLOSE,
                close_price=None,
                clv_pct=None,
                close_book_scope=None,
                no_close_reason=unresolved_by_key.get(key),
            )
            continue

        close_price = row.get("close_price")
        clv = clv_pct_from_prices(entry, close_price)
        if clv is None:
            _row(REASON_CLV_UNCOMPUTABLE, close_price=close_price, clv_pct=None,
                 close_book_scope=_scope_of(row))
            continue

        _row(
            REASON_RESOLVED,
            close_price=close_price,
            close_source=row.get("close_source"),
            close_captured_at=row.get("close_captured_at"),
            close_book_scope=_scope_of(row),
            matched_bookmaker=row.get("matched_bookmaker"),
            clv_pct=clv,
            beat_close=clv > 0,
            # The opening's own CLV, carried alongside rather than replacing
            # ours. The gap between them is what our TIMING was worth, which is
            # a different question from whether the pick was right.
            open_clv_pct=row.get("clv_pct"),
        )

    resolved = [row for row in graded if row["reason"] == REASON_RESOLVED]
    return {
        "date": date,
        "orders": len(orders),
        "resolved": len(resolved),
        "reasons": dict(sorted(reasons.items())),
        # WHY the unresolved ones failed, counted. `None` means the resolver
        # produced no row for that key at all, which is our book being absent
        # from the shard rather than a named refusal.
        "no_close_reasons": _no_close_reasons(graded),
        "by_market": _aggregate(resolved, ("sport", "market")),
        "by_scope": _aggregate(resolved, ("close_book_scope",)),
        # The paper2 comparison, as its own top-level view rather than something
        # to reconstruct by filtering `by_market`.
        "by_venue": _aggregate(resolved, ("venue",)),
        "rows": graded,
    }


def _no_close_reasons(graded: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in graded:
        if row.get("reason") != REASON_NO_CLOSE:
            continue
        name = row.get("no_close_reason") or "opening_not_in_resolver"
        out[str(name)] = out.get(str(name), 0) + 1
    return dict(sorted(out.items()))


def _aggregate(rows: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> list[dict[str, Any]]:
    """Group, and report `n` on every group.

    Scope is ALWAYS part of the grouping even when it is not in `keys`: a market
    average that blends a same-book close with another book's is the biased
    number this module exists to keep separate.
    """
    # Both of these are forced into the bucket whether or not the caller asked
    # for them, because each names WHICH BOOK a number is about: `venue` says
    # which portfolio placed it, `close_book_scope` says what it was compared
    # against. Averaging across either produces a confident number describing
    # nothing in particular.
    forced = [key for key in ("venue", "close_book_scope") if key not in keys]
    buckets: dict[tuple, list[Mapping[str, Any]]] = {}
    for row in rows:
        bucket = tuple(str(row.get(key) or "") for key in keys)
        bucket = bucket + tuple(str(row.get(key) or "") for key in forced)
        buckets.setdefault(bucket, []).append(row)

    out: list[dict[str, Any]] = []
    labels = list(keys) + forced
    for bucket, group in sorted(buckets.items()):
        clvs = [row["clv_pct"] for row in group if row.get("clv_pct") is not None]
        beats = sum(1 for row in group if row.get("beat_close"))
        entry = {label: value for label, value in zip(labels, bucket)}
        entry.update(
            {
                # FIRST FIELD ON PURPOSE. Every number after it is meaningless
                # without it, and a market with n=2 must never read like a
                # result.
                "n": len(group),
                "avg_clv_pct": round(sum(clvs) / len(clvs), 4) if clvs else None,
                "beat_close": beats,
                "beat_close_rate": round(beats / len(group), 4) if group else None,
                "staked_dollars": round(
                    sum(row.get("stake_dollars") or 0.0 for row in group), 2
                ),
            }
        )
        out.append(entry)
    return out


def order_clv_report_line(report: Mapping[str, Any]) -> str:
    """One log line. `logger.info` never reaches Render's collector -- print this."""
    # The headline is the UNRESTRICTED book's same-book number. paper2 gets its
    # own field rather than being averaged in: they are two portfolios and one
    # average of them describes neither.
    scoped = report.get("by_scope") or []
    same_book = [e for e in scoped if e.get("close_book_scope") == SCOPE_SAME_BOOK]
    headline = next((e for e in same_book if ":" not in str(e.get("venue") or "")), {})
    paper2 = [e for e in same_book if ":" in str(e.get("venue") or "")]
    return (
        "[order_clv] ORDER_CLV"
        f" date={report.get('date')}"
        f" orders={report.get('orders')}"
        f" resolved={report.get('resolved')}"
        f" markets={len(report.get('by_market') or [])}"
        # SAME-BOOK ONLY, and `n` beside it. The blended number would be higher
        # and would not mean anything.
        f" same_book_n={headline.get('n', 0)}"
        f" same_book_avg_clv_pct={headline.get('avg_clv_pct')}"
        f" same_book_beat={headline.get('beat_close', 0)}"
        f" reasons={report.get('reasons')}"
        # The split that turns "35 unresolved" into something with a remedy.
        f" no_close={report.get('no_close_reasons')}"
        f" paper2={[(e.get('venue'), e.get('n'), e.get('avg_clv_pct')) for e in paper2]}"
    )
