"""Join a recorded opening to the market's close, and produce `clv_pct`.

The other half of audit §7 ranked fix #1. `clv_opening_ledger` records what we
published; this resolves what the market closed at and pairs them. **No
dependency on grading, outcomes, `settle_result`, or the 367 MB chunk path** --
which is the entire point: CLV is knowable hours before any game settles, and
the settlement path has produced `matched: 0` on 8,276 records.

THE JOIN, MEASURED 2026-08-14 RATHER THAN ASSUMED. Odds history stores two
different key shapes and they need different handling:

    props (n=3374)  player_name=<lower>|market=<market>|selection=<over|under>
    game  (n=75)    event_id=<id>|home_team=<h>|away_team=<a>|market=<m>|bookmaker=<b>

Consequences that are easy to get wrong, each checked against the real payload:

- **Prop keys carry NO bookmaker.** One series per player+market+selection, so
  a prop close is book-agnostic. Our opening is at a specific book, so that
  pairing compares a book price to a market-wide close. It is still a valid CLV
  signal but it is NOT same-book, and it is labelled `book_agnostic_close`
  rather than silently averaged in.
- **Game keys carry NO side** -- `entity` names one team. It looked like only
  one side's close was recoverable, which would have made away-side CLV
  impossible. It is not: the history point's `line` dict carries BOTH, as
  `{"away_odds": "+118", "home_odds": "-150"}`. Reading that instead of
  `last_odds` is what makes both sides joinable.
- **`current_odds` is None on every point in both shapes** (6748/6748 and
  150/150). The price lives in `last_odds` and in `line`. A joiner written
  against `current_odds` would have produced zero rows and looked like a data
  outage.

THE CLOSE, and why two sources are labelled apart. `odds_refresh_tracking`
stamps `closing_line` only on an OBSERVED pregame->live transition -- measured
on mlb 2026-08-13, **18 of 1074 markets (1.7%)**. But `history_points > 0` on
**100%**, so the last pregame observation is available for essentially every
market. Those are different measurements: one is the real close, the other is
the last thing we saw before kickoff, which at a 2h pregame sweep cadence can
be well before it. Mixing them silently is the `book_margin_model` mistake --
so every row carries `close_source` and `close_age_seconds`, and a caller that
wants only gold data can filter on them.

NOTHING IS GUESSED. Every row that cannot be resolved carries a named reason
and is counted. The settlement join failed exactly here -- 4,560 `no_key_match`
of 8,276 with no per-reason breakdown deeper than the name -- so an unresolved
row here is a datum, not a silent drop.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

__all__ = ["compute_clv_for_date", "resolve_close", "clv_pct_from_prices"]


def clv_pct_from_prices(original_price: Any, closing_price: Any) -> float | None:
    """Reuses the ledger's convention rather than inventing a second one.

    Probability points, POSITIVE means we beat the close. Taking -110 on a side
    that closes -130 is +4.1 points: the market moved toward us. Two
    conventions for one quantity is how a dashboard ends up disagreeing with a
    ledger, so this delegates.
    """
    from syndicate.features.prediction_ledger import _clv_pct_from_prices

    return _clv_pct_from_prices(original_price, closing_price)


def _as_float(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.strip().replace("+", "")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _history_key(opening: Mapping[str, Any]) -> str | None:
    """The odds-history key this opening should be looked up under."""
    market = str(opening.get("market") or "").strip().lower()
    if not market:
        return None
    player = str(opening.get("player_name") or "").strip().lower()
    if player:
        side = str(opening.get("side") or "").strip().lower()
        return f"player_name={player}|market={market}|selection={side}"
    event_id = str(opening.get("event_id") or "").strip()
    home = str(opening.get("home_team") or "").strip()
    away = str(opening.get("away_team") or "").strip()
    book = str(opening.get("bookmaker") or "").strip().lower()
    if not event_id:
        return None
    return f"event_id={event_id}|home_team={home}|away_team={away}|market={market}|bookmaker={book}"


def _price_for_side(point: Mapping[str, Any], opening: Mapping[str, Any]) -> tuple[float | None, str | None]:
    """The closing price for THIS opening's side, out of one history point.

    Order matters and is not arbitrary. The `line` dict is preferred because it
    is the only place both sides of a game market exist; `last_odds` is the
    fallback and belongs to `entity` alone, so it is used only when the entity
    IS this row's side. Reading `last_odds` first would silently hand the home
    team's price to the away row -- a wrong number rather than a missing one.
    """
    side = str(opening.get("side") or "").strip().lower()
    line_block = point.get("line") if isinstance(point.get("line"), Mapping) else {}

    if side in {"home", "away"}:
        price = _as_float((line_block or {}).get(f"{side}_odds"))
        if price is not None:
            return price, "line_block_side"
    if side in {"over", "under"}:
        for candidate in (f"{side}_odds", "price"):
            price = _as_float((line_block or {}).get(candidate))
            if price is not None:
                return price, "line_block_side" if candidate.endswith("_odds") else "line_block_price"

    # `last_odds` names whatever `entity` is. Only safe when that is us.
    entity = str(point.get("entity") or "").strip().lower()
    if side in {"home", "away"}:
        team = str(opening.get(f"{side}_team") or "").strip().lower()
        if team and entity == team:
            price = _as_float(point.get("last_odds"))
            if price is not None:
                return price, "last_odds_entity_match"
        return None, "entity_side_mismatch"

    player = str(opening.get("player_name") or "").strip().lower()
    if player:
        if entity and entity != player:
            return None, "entity_player_mismatch"
        price = _as_float(point.get("last_odds"))
        if price is not None:
            return price, "last_odds_player"
    return None, "no_price_on_point"


def resolve_close(
    opening: Mapping[str, Any],
    market_state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The close for one opening, with its provenance and its age."""
    out: dict[str, Any] = {
        "close_price": None,
        "close_source": None,
        "close_captured_at": None,
        "close_age_seconds": None,
        "unresolved_reason": None,
    }
    if not isinstance(market_state, Mapping):
        out["unresolved_reason"] = "no_market_in_history"
        return out

    commence = _parse_ts(opening.get("commence_time"))
    is_prop = bool(str(opening.get("player_name") or "").strip())

    # 1. The real close, where the transition was actually observed.
    stamped = _as_float(market_state.get("closing_price"))
    if stamped is None:
        stamped = _as_float(market_state.get("closing_line"))
    if stamped is not None and not is_prop:
        # Only trusted for game markets: `closing_line` for a prop is the LINE
        # (e.g. 1.5), not a price, and treating it as one would fabricate a
        # closing price of +150 out of a 1.5 total-bases line.
        captured = market_state.get("closing_captured_at")
        out.update(
            close_price=stamped,
            close_source="observed_transition",
            close_captured_at=captured,
        )
        stamp_ts = _parse_ts(captured)
        if commence and stamp_ts:
            out["close_age_seconds"] = round((commence - stamp_ts).total_seconds(), 1)
        return out

    # 2. Otherwise the last observation strictly BEFORE kickoff.
    history = market_state.get("history")
    if not isinstance(history, list) or not history:
        out["unresolved_reason"] = "no_history_points"
        return out

    best: tuple[datetime, Mapping[str, Any]] | None = None
    for point in history:
        if not isinstance(point, Mapping):
            continue
        stamp = _parse_ts(point.get("captured_at")) or _parse_ts(point.get("snapshot_ts"))
        if stamp is None:
            continue
        if commence is not None and stamp >= commence:
            continue
        if best is None or stamp > best[0]:
            best = (stamp, point)

    if best is None:
        # Every observation was at or after kickoff. That is not a close.
        out["unresolved_reason"] = "no_pregame_observation"
        return out

    stamp, point = best
    price, how = _price_for_side(point, opening)
    if price is None:
        out["unresolved_reason"] = how or "no_price_on_point"
        return out
    out.update(
        close_price=price,
        close_source="last_pregame_quote",
        close_captured_at=stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        close_price_field=how,
    )
    if commence:
        out["close_age_seconds"] = round((commence - stamp).total_seconds(), 1)
    if str(opening.get("player_name") or "").strip():
        # Prop history has no bookmaker, so this close is market-wide while the
        # opening is one book's. Stated on the row, never averaged in silently.
        out["close_book_scope"] = "book_agnostic_close"
    else:
        out["close_book_scope"] = "same_book"
    return out


def compute_clv_for_date(
    date: str,
    sport: str,
    *,
    root: Any = None,
    history_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Pair every recorded opening for `sport` on `date` with its close."""
    from syndicate.features.shared.clv_opening_ledger import load_openings

    openings = [
        record
        for record in load_openings(date, root=root)
        if str(record.get("sport") or "").strip().lower() == str(sport).strip().lower()
    ]

    markets: Mapping[str, Any] = {}
    if history_payload is not None:
        candidate = history_payload.get("markets")
        markets = candidate if isinstance(candidate, Mapping) else {}
    else:
        try:
            from syndicate.features.shared.odds_control_plane import (
                load_odds_history_payload_for_sport,
            )

            payload = load_odds_history_payload_for_sport(sport, date)
            candidate = (payload or {}).get("markets") if isinstance(payload, Mapping) else None
            markets = candidate if isinstance(candidate, Mapping) else {}
        except Exception as exc:  # pragma: no cover - environment dependent
            return {
                "date": date,
                "sport": sport,
                "rows": [],
                "openings": len(openings),
                "error": f"{type(exc).__name__}: {exc}",
            }

    # SAME-EVENT, SAME-MARKET, DIFFERENT BOOK -- an index for the fallback below.
    #
    # MEASURED 2026-08-14 on 78 real mlb openings: all 28 props matched, and all
    # 50 misses were game markets. 32 of those 50 were `spreads`/`totals`/`h2h`
    # where the MARKET was in history but OUR BOOK was not -- because the board
    # publishes the BEST price, which is routinely `polymarket`, `prophetx` or
    # `betfair_ex`, while odds history tracks a handful of mainstream books.
    #
    # Discarding those would throw away 41% of the openings for a reason that
    # has nothing to do with the bet. Taking another book's close is a real CLV
    # signal -- it is what the MARKET did -- but it is not a same-book
    # comparison, so it is labelled exactly like the prop case rather than
    # blended in. The remaining 18 misses are market families absent from
    # history entirely (`h2h_lay`, `totals_alt`, `h2h_3_way`, `spreads_alt`);
    # those are a capture-side gap and stay unresolved by name.
    by_event_market: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for market_key, state in markets.items():
        if not isinstance(state, Mapping) or not str(market_key).startswith("event_id="):
            continue
        parts = dict(
            part.split("=", 1) for part in str(market_key).split("|") if "=" in part
        )
        event_id = str(parts.get("event_id") or "").strip()
        market_name = str(parts.get("market") or "").strip().lower()
        if event_id and market_name:
            by_event_market.setdefault((event_id, market_name), []).append(state)

    rows: list[dict[str, Any]] = []
    unresolved: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for opening in openings:
        key = _history_key(opening)
        state = markets.get(key) if key else None
        resolved = resolve_close(opening, state if isinstance(state, Mapping) else None)

        if (
            resolved.get("close_price") is None
            and not str(opening.get("player_name") or "").strip()
            and str(opening.get("event_id") or "").strip()
        ):
            event_key = (
                str(opening.get("event_id")).strip(),
                str(opening.get("market") or "").strip().lower(),
            )
            for alternate in by_event_market.get(event_key, []):
                if alternate is state:
                    continue
                candidate = resolve_close(opening, alternate)
                if candidate.get("close_price") is not None:
                    candidate["close_book_scope"] = "different_book_close"
                    resolved = candidate
                    break

        if key is None:
            resolved["unresolved_reason"] = "unkeyable_opening"
        reason = resolved.get("unresolved_reason")
        if reason:
            unresolved[reason] = unresolved.get(reason, 0) + 1
            continue
        clv = clv_pct_from_prices(opening.get("price"), resolved.get("close_price"))
        if clv is None:
            unresolved["clv_uncomputable"] = unresolved.get("clv_uncomputable", 0) + 1
            continue
        source = str(resolved.get("close_source") or "unknown")
        by_source[source] = by_source.get(source, 0) + 1
        rows.append(
            {
                "key": opening.get("key"),
                "sport": opening.get("sport"),
                "market": opening.get("market"),
                "side": opening.get("side"),
                "player_name": opening.get("player_name"),
                "line": opening.get("line"),
                "bookmaker": opening.get("bookmaker"),
                "open_price": opening.get("price"),
                "open_captured_at": opening.get("captured_at"),
                "close_price": resolved.get("close_price"),
                "close_source": resolved.get("close_source"),
                "close_captured_at": resolved.get("close_captured_at"),
                "close_age_seconds": resolved.get("close_age_seconds"),
                "close_book_scope": resolved.get("close_book_scope"),
                "clv_pct": clv,
                "beat_close": clv > 0,
                # Carried through so CLV can be split by whether a model had a
                # view -- §4's open question, and the reason to measure at all.
                "model_edge_pct": opening.get("model_edge_pct"),
                "ev_pct": opening.get("ev_pct"),
            }
        )

    resolved_count = len(rows)

    # THE HEADLINE NUMBER IS SAME-BOOK ONLY, AND IT IS USUALLY None. THAT IS
    # CORRECT, NOT A BUG.
    #
    # The board publishes the BEST price across books by construction. Pairing
    # that opening with a close from SOME OTHER book compares a best-of-N draw
    # against a single draw, which is biased upward no matter how good or bad
    # the bet was. Measured on 150 real openings 2026-08-14:
    #
    #     scope                  n    avg_clv    beat_close
    #     different_book_close   32    +6.206      29/32  (91%)
    #     book_agnostic_close    27    +2.716      18/27  (67%)
    #     same_book               0        --         --
    #
    # A +6.2-point average with a 91% beat rate is not skill, it is the
    # selection effect. Publishing it as "our CLV" would be the most flattering
    # wrong number this repo could produce, and CLV is meant to be the honest
    # instrument that outcome-ROI is not (`#211`).
    #
    # So `avg_clv_pct` counts ONLY same-book rows, and the biased scopes are
    # reported beside it under their own names, never blended in. Today that
    # makes the headline None on real data -- the truthful answer to "what is
    # our CLV" is currently "not yet measurable without book bias".
    same_book = [row for row in rows if row.get("close_book_scope") == "same_book"]
    biased = [row for row in rows if row.get("close_book_scope") != "same_book"]

    def _stats(subset: list[dict[str, Any]]) -> dict[str, Any]:
        if not subset:
            return {"n": 0, "avg_clv_pct": None, "beat_close_count": 0, "beat_close_rate": None}
        beat_n = sum(1 for row in subset if row["beat_close"])
        return {
            "n": len(subset),
            "avg_clv_pct": round(sum(row["clv_pct"] for row in subset) / len(subset), 4),
            "beat_close_count": beat_n,
            "beat_close_rate": round(beat_n / len(subset), 4),
        }

    by_scope: dict[str, dict[str, Any]] = {}
    for scope in sorted({str(row.get("close_book_scope")) for row in rows}):
        by_scope[scope] = _stats([row for row in rows if row.get("close_book_scope") == scope])

    headline = _stats(same_book)
    report = {
        "date": str(date),
        "sport": str(sport),
        "openings": len(openings),
        "resolved": resolved_count,
        "unresolved_reasons": unresolved,
        "by_close_source": by_source,
        # Same-book only. None means no unbiased comparison was available.
        "avg_clv_pct": headline["avg_clv_pct"],
        "beat_close_count": headline["beat_close_count"],
        "beat_close_rate": headline["beat_close_rate"],
        "same_book_n": headline["n"],
        "book_biased_n": len(biased),
        "by_book_scope": by_scope,
        "bias_note": (
            "avg_clv_pct counts same_book rows only. The opening is a best-of-N "
            "book price, so pairing it with another book's close is biased upward."
        ),
        "rows": rows,
    }
    print(
        "[clv_join] CLV date=%s sport=%s openings=%d resolved=%d same_book=%d "
        "avg_clv_pct=%s beat_close=%s/%s book_biased=%d by_scope=%s unresolved=%s"
        % (date, sport, len(openings), resolved_count, headline["n"],
           headline["avg_clv_pct"], headline["beat_close_count"], headline["n"],
           len(biased), by_scope, unresolved),
        flush=True,
    )
    return report
