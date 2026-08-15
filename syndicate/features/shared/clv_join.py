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

    # THE LINE MUST MATCH, OR IT IS NOT THE SAME BET.
    #
    # The history key carries no line, and the point's `line` block does:
    # `{"away_line": 1.5, "away_odds": "-235", "home_line": -1.5,
    # "home_odds": "+180"}`. Ignoring it compared a board row at `home -5.0`
    # against a close at `home -1.5` and called the difference CLV.
    #
    # MEASURED: that produced same-book rows like `spreads home open=-122
    # close=+162` (clv -16.8) and `open=-238 close=+135` (clv -27.9). A spread
    # does not move 28 probability points; those are two different bets
    # subtracted from each other. It is the same class of error as omitting
    # `player_name` from the opening key, one level down, and it is why the
    # first same-book average read -5.01.
    #
    # An UNVERIFIABLE line is refused, not accepted. When the opening has a
    # line and the point publishes none, we cannot show they are the same bet,
    # and `learnings.md` is explicit that unknown must not fall to the
    # permissive branch. h2h has no line on either side and is unaffected.
    opening_line = _as_float(opening.get("line"))
    if opening_line is not None and side in {"home", "away", "over", "under"}:
        point_line = _as_float(line_block.get(f"{side}_line"))
        if point_line is None:
            point_line = _as_float(line_block.get("line"))
        if point_line is None:
            return None, "line_unverifiable"
        if abs(point_line - opening_line) > 1e-6:
            return None, "line_mismatch"

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


def _stamped_close_side(
    market_state: Mapping[str, Any], opening: Mapping[str, Any]
) -> str | None:
    """Which side the scalar `closing_price` belongs to, or None if unknowable.

    **THE STAMP IS ENTITY-SCOPED AND CARRIES NO SIDE.**
    `odds_refresh_tracking.py:1602` writes `closing_price = previous_odds`, and
    `previous_odds` is the price of `entity` — one team, not both. Measured on
    mlb 2026-08-15 across every market carrying a stamp: **`entity ==
    home_team` on 18 of 18**, so in practice the stamp is the HOME price.

    That is the whole defect this exists to close. Read as a side-blind scalar,
    an away-side opening was differenced against the home close: event
    `dbbb481a…` (Yankees @ Blue Jays) opened away `-186` and was paired with
    `+168`, which is TORONTO's price — a `-27.72` that is not CLV at all.

    Returned as a side rather than a bool so the caller can say WHY it refused.
    None means the entity could not be identified, which is refused rather than
    assumed: `learnings.md` is explicit that unknown must not take the
    permissive branch, and this is the exact shape of that rule.
    """
    entity = str(market_state.get("entity") or "").strip()
    if not entity:
        for point in market_state.get("history") or ():
            if isinstance(point, Mapping) and str(point.get("entity") or "").strip():
                entity = str(point["entity"]).strip()
                break
    if not entity:
        return None
    home = str(opening.get("home_team") or "").strip()
    away = str(opening.get("away_team") or "").strip()
    if home and entity.casefold() == home.casefold():
        return "home"
    if away and entity.casefold() == away.casefold():
        return "away"
    return None


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
    # THE STAMP IS ONLY USABLE FOR THE SIDE IT BELONGS TO.
    #
    # Unlike a history point, the stamp has no `line` block, so there is nothing
    # to resolve the other side from — `_price_for_side` cannot help here. The
    # only sound move is to use it when this opening IS the entity's side and
    # otherwise fall through to `last_pregame_quote`, which reads the `line`
    # block and is side-aware by construction. That fallback is not a
    # degradation: it is the path that was already producing every correct row
    # (measured 100%/100% — every contaminated row was `observed_transition`,
    # every clean one `last_pregame_quote`).
    #
    # Falling through rather than refusing outright matters: a home-side opening
    # keeps its real observed close, and an away-side one gets a correct
    # side-aware close instead of a wrong number. Nothing is fabricated either way.
    stamped_side = _stamped_close_side(market_state, opening) if stamped is not None else None
    opening_side = str(opening.get("side") or "").strip().lower()
    if stamped is not None and (stamped_side is None or stamped_side != opening_side):
        # Counted by name on the row so the fallback is visible rather than
        # silent. `totals` lands here by design: its sides are over/under while
        # the entity is a team, so the stamp can never be attributed to a side.
        out["stamped_close_skipped"] = (
            "stamped_close_entity_unknown" if stamped_side is None
            else f"stamped_close_is_{stamped_side}_side"
        )
        stamped = None

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
            # PREFER A GENUINE SAME-BOOK PAIR BEFORE FALLING BACK.
            #
            # The opening now carries OUR price at every book that quoted the
            # side, so when the best book's close is missing we can still make
            # an UNBIASED comparison: take our price at some book history did
            # record, against that same book's close. That is the only pairing
            # free of the best-of-N selection effect, and it is why
            # `book_prices` is recorded at all.
            #
            # Tried before the different-book fallback, deliberately: falling
            # back first would produce a number, and a biased number that looks
            # fine is worse than an honest gap.
            book_prices = opening.get("book_prices")
            if isinstance(book_prices, Mapping) and book_prices:
                for market_key, alternate in markets.items():
                    if not isinstance(alternate, Mapping):
                        continue
                    parts = dict(
                        part.split("=", 1) for part in str(market_key).split("|") if "=" in part
                    )
                    if (
                        str(parts.get("event_id") or "").strip() != event_key[0]
                        or str(parts.get("market") or "").strip().lower() != event_key[1]
                    ):
                        continue
                    book = str(parts.get("bookmaker") or "").strip().lower()
                    our_price = book_prices.get(book)
                    if our_price is None:
                        continue
                    candidate = resolve_close(opening, alternate)
                    if candidate.get("close_price") is None:
                        continue
                    candidate["close_book_scope"] = "same_book"
                    candidate["matched_bookmaker"] = book
                    candidate["open_price_override"] = our_price
                    resolved = candidate
                    break

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
        # When a same-book pair was found, CLV must use OUR price at THAT book,
        # not the best-book headline price -- otherwise the comparison is
        # same-book in name only and carries the same bias it exists to remove.
        # A CLOSE THAT PRECEDES THE OPENING IS NOT A CLOSE.
        #
        # Nothing enforced the arrow of time here, and the pairing looks
        # perfectly well-formed without it: same event, same market, same book,
        # same line, a real price at each end. MEASURED 2026-08-14 — on the
        # first same-book run **25 of 25 rows had a close captured BEFORE the
        # opening** (openings at 00:46:53Z against "closes" from 22:12–23:16 the
        # evening before), producing a confident-looking `avg_clv_pct = -5.215`
        # that was pure subtraction of unrelated instants. Two of those rows
        # were `spreads home -1.5` moving -122 -> +162 and -238 -> +135, which
        # is what prompted the check: a spread does not move 28 probability
        # points.
        #
        # This is a PRODUCTION condition, not only a backfill artifact: it fires
        # whenever a market is first published later than the last pregame
        # observation of it. Refused by name rather than clamped to zero —
        # "no valid close" and "the price did not move" are different facts and
        # must not share a number.
        open_at = _parse_ts(opening.get("captured_at"))
        close_at = _parse_ts(resolved.get("close_captured_at"))
        if open_at and close_at and close_at <= open_at:
            unresolved["close_precedes_open"] = unresolved.get("close_precedes_open", 0) + 1
            continue

        open_price = resolved.get("open_price_override")
        if open_price is None:
            open_price = opening.get("price")
        clv = clv_pct_from_prices(open_price, resolved.get("close_price"))
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
                "open_price": open_price,
                "open_price_best_book": opening.get("price"),
                "matched_bookmaker": resolved.get("matched_bookmaker") or opening.get("bookmaker"),
                "open_captured_at": opening.get("captured_at"),
                "close_price": resolved.get("close_price"),
                "close_source": resolved.get("close_source"),
                # Present when the entity-scoped stamp was refused for this
                # side and the side-aware fallback was used instead.
                "stamped_close_skipped": resolved.get("stamped_close_skipped"),
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
    # THE SECOND WAY THIS NUMBER GOES WRONG, and it is not the book scope.
    #
    # `close_age_seconds` is `(commence - stamp)`, so a NEGATIVE value means the
    # "close" was observed AFTER first pitch -- an in-play price, not a close.
    # An in-play moneyline reprices on the game state, not on the market's
    # pregame view, so differencing it against an opening is not CLV at all.
    #
    # MEASURED on mlb 2026-08-15: **37 of 172 same-book rows (21.5%) were
    # post-commence, and they carried 60% of the entire loss.** The worst four
    # were one event -- opened `-186`, "closed" `+168` stamped 86 minutes into
    # the game, which is a team going behind early. Excluding them moved the
    # headline from `-0.672` to `-0.346` and reversed the book attribution
    # entirely: FanDuel h2h `-0.616` vs DraftKings h2h `-1.378`, the opposite of
    # what the contaminated numbers said.
    #
    # The docstring above already promised "a caller that wants only gold data
    # can filter on them" -- the headline IS that caller, and it was not
    # filtering. Same treatment as the book scopes: excluded from the headline,
    # reported beside it under its own name, never silently dropped.
    #
    # UNKNOWN TIMING DOES NOT COUNT AS PREGAME. A missing `close_age_seconds`
    # means we cannot tell which side of first pitch the close came from, and a
    # guard that maps absent onto its permissive branch is how this class of bug
    # survives -- so it gets its own bucket rather than the benefit of the doubt.
    def _close_timing(row: Mapping[str, Any]) -> str:
        age = row.get("close_age_seconds")
        if not isinstance(age, (int, float)):
            return "unknown"
        return "pregame" if age >= 0 else "in_play"

    for row in rows:
        row["close_timing"] = _close_timing(row)

    same_book_all = [row for row in rows if row.get("close_book_scope") == "same_book"]
    same_book = [row for row in same_book_all if row.get("close_timing") == "pregame"]
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

    _skipped_counts: dict[str, int] = {}
    for row in rows:
        reason = row.get("stamped_close_skipped")
        if reason:
            _skipped_counts[str(reason)] = _skipped_counts.get(str(reason), 0) + 1

    by_scope: dict[str, dict[str, Any]] = {}
    for scope in sorted({str(row.get("close_book_scope")) for row in rows}):
        by_scope[scope] = _stats([row for row in rows if row.get("close_book_scope") == scope])

    # Over same-book rows only, so the timing split is not itself confounded by
    # book bias -- the whole point is to compare like with like.
    by_timing: dict[str, dict[str, Any]] = {}
    for timing in ("pregame", "in_play", "unknown"):
        subset = [row for row in same_book_all if row.get("close_timing") == timing]
        if subset:
            by_timing[timing] = _stats(subset)

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
        # Stated so a reader can see what the headline dropped and why, rather
        # than wondering why `same_book_n` is smaller than the same_book row
        # count they can see in `rows`.
        "same_book_all_n": len(same_book_all),
        "in_play_excluded_n": sum(
            1 for row in same_book_all if row.get("close_timing") == "in_play"
        ),
        "unknown_timing_excluded_n": sum(
            1 for row in same_book_all if row.get("close_timing") == "unknown"
        ),
        "by_close_timing": by_timing,
        # How often the entity-scoped stamp was refused for this row's side.
        # Expected to be LARGE and that is the fix working: before this, every
        # away-side opening on a stamped market was silently differenced against
        # the home team's closing price.
        "stamped_close_skipped": _skipped_counts,
        "bias_note": (
            "avg_clv_pct counts same_book rows whose close was observed BEFORE "
            "first pitch. The opening is a best-of-N book price, so pairing it "
            "with another book's close is biased upward; and a close stamped "
            "after commence is an in-play price repricing on the game state, "
            "which is not CLV. Both are reported beside the headline, never in it."
        ),
        "rows": rows,
    }
    print(
        "[clv_join] CLV date=%s sport=%s openings=%d resolved=%d same_book=%d "
        "avg_clv_pct=%s beat_close=%s/%s book_biased=%d in_play_excluded=%d "
        "unknown_timing_excluded=%d by_scope=%s by_timing=%s unresolved=%s"
        % (date, sport, len(openings), resolved_count, headline["n"],
           headline["avg_clv_pct"], headline["beat_close_count"], headline["n"],
           len(biased), report["in_play_excluded_n"],
           report["unknown_timing_excluded_n"], by_scope, by_timing, unresolved),
        flush=True,
    )
    return report
