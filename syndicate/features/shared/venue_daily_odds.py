"""Dated, venue-native daily odds -- the capture-first layer.

WHY THIS EXISTS
--------------------------------------------------------------------------

Both venues' durable artifacts are by-products of the JOIN. `kalshi_markets.json`
is the merged set of series we chose to fetch; `polymarket_us_games.json` is a
single undated current slate. So no artifact anywhere answers the question a
CLV or line-movement model actually asks:

    what did this venue offer, at what price, at what time, on this date?

Worse, the join decides what survives. A market family we cannot yet parse is
INVISIBLE -- not refused, not counted, not stored -- so the only way to notice
it is for a human to see it on the venue's website. That is the mechanism
behind "whack-a-mole": coverage grows one hand-written rule at a time and
nothing measures what is still missing.

Measured 2026-08-25, both venues:

    kalshi      883 markets stored, 4 joined, `unreadable_title` 216
    polymarket  12,897 fetched, 4,794 indexed, 73 joined

This module inverts the dependency. The venue's book is recorded first, whole
and dated; the join becomes a CONSUMER of that record rather than its
gatekeeper. An unparsed family becomes a counted row carrying its raw title,
so tomorrow's grammar is written from real strings -- which matters because
three grammars written from imagined strings matched none of production and
left 302 markets unreadable.

WHAT IS INHERITED FROM `kalshi_board.record_snapshot`
--------------------------------------------------------------------------

That recorder already solved the hard parts and this generalises it rather
than inventing a second one:

* THE OPENING IS CAPTURED ON FIRST SIGHT, not on the first board build. On a
  lookahead market that is days before the game, which is the only opening
  worth measuring CLV against.
* A POINT IS APPENDED ONLY WHEN THE PRICE MOVED. A point per fetch recording
  that nothing happened would push real moves out of a bounded window.
* EVERY COUNTER IS RETURNED, INCLUDING ZEROES -- a counter that appears only
  when it fires cannot distinguish "ran and nothing changed" from "never ran".

WHAT IS NEW HERE
--------------------------------------------------------------------------

* DATED AND SPLIT PER SPORT. One file per (venue, sport, date). The keyvalue
  store refuses at 8MB and `layer2_shortlist` already occupies 5.0MB of that
  budget (`KEYVALUE_WRITE_LARGE size_bytes=5047682`), so a single whole-book
  document is a write that starts failing silently one sport from now.
* UNPARSED MARKETS ARE STORED, not dropped. `market=None` with `raw_title`
  kept. This is the whole point of the module.
* COVERAGE IS REPORTED per write: listed, parsed, and unparsed BY FAMILY.

THE DATE TOKEN AND THE TTL
--------------------------------------------------------------------------

`_default_keyvalue_ttl_seconds` gives any path containing a date token a
10-day TTL. That is ACCEPTABLE here and deliberately chosen: this file is the
day's odds, and ten days is longer than any intraday movement question needs.
It is NOT acceptable for the opening line used to settle CLV weeks later, which
is why openings continue to live in the undated `clv_opening_ledger` and this
module does not attempt to replace it.

THE DATE IS THE GAME DATE
--------------------------------------------------------------------------

Never `close_time`. Kalshi closes a market days after the event so late
settlement data can land, and a join that compared `close_time[:10]` against
the board's date once refused 100% of a slate on every build for hours. The
caller supplies the game date it read from the ticker or slug; a row without
one is counted `undated` and skipped rather than filed under today.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

__all__ = [
    "daily_odds_path",
    "record_daily_odds",
    "record_venue_book",
    "in_scope_sports",
    "kalshi_daily_rows",
    "polymarket_daily_rows",
    "MAX_POINTS_PER_MARKET",
    "MAX_MARKETS_PER_FILE",
]

# Same bound `kalshi_board` uses, and for the same reason: enough points to see
# a day's movement, few enough that one market cannot dominate the document.
MAX_POINTS_PER_MARKET = 48

# Per (venue, sport, date). Chosen against the 8MB keyvalue ceiling with
# `layer2_shortlist` already at 5.0MB: a compact row is ~150 bytes plus its
# points, so 8,000 markets is comfortably inside a per-sport budget while
# still holding a whole sport's book including every ladder rung.
MAX_MARKETS_PER_FILE = 8000


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_float(value: Any) -> float | None:
    """A tradeable probability price, or None.

    ZERO AND ONE ARE NOT PRICES. `yes_ask_dollars = 0.0` means there is NO ASK
    -- an empty side of the book -- and 1.0 is a settled market or the same
    emptiness on the other leg. Recording either as a price manufactures
    movement that never happened.

    MEASURED 2026-08-25T17:43:05Z, and it is exactly the failure this guard
    prevents:

        MOVER KXMLBKS-26AUG251907KCTOR-TORMSCHERZER31-2
              open=0.0 now=0.93 move_pts=93.0 n=4

    A 93-point "move" from a market that simply had no offer when we first
    looked. As an OPENING that is worse than useless: CLV is measured against
    it, so every bet on that market would score a 93-point beat it never got.
    A missing opening is a known unknown; a fabricated one is a wrong number
    that looks like a signal.

    Returned as None so the row counts `unpriced` -- "nobody is making a price
    right now" -- which is a real and separate fact from "the venue does not
    offer this".
    """
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    # Strictly inside (0, 1). A probability price at either bound is not one.
    if parsed <= 0.0 or parsed >= 1.0:
        return None
    return parsed


def daily_odds_path(venue: str, sport: str, game_date: str):
    """`reports/intelligence/venue_odds/<venue>__<sport>__<YYYY_MM_DD>.json`.

    Underscored date token, matching the convention `layer2_shortlist` uses --
    and note it IS a date token, so this path takes the 10-day TTL. See the
    module docstring for why that is the right trade here and wrong for
    openings.
    """
    from syndicate.features.shared.refresh_state_store import reports_root

    stamp = str(game_date or "").strip()[:10].replace("-", "_")
    slug = f"{_slug(venue)}__{_slug(sport)}__{stamp}.json"
    return reports_root() / "intelligence" / "venue_odds" / slug


def _slug(value: Any) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value or "").strip().lower())


def record_daily_odds(
    venue: str,
    sport: str,
    game_date: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """Append today's price points for one venue and sport. Never raises.

    `rows` are VENUE-NATIVE and already carry the venue's own identifiers. A
    row needs `id` and at least one of `yes`/`no`; everything else is optional,
    INCLUDING `market`. A row whose market we cannot name is stored with its
    `raw_title` so the family can be counted and, later, parsed.
    """
    from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

    stamp = now or _utc_now()
    path = daily_odds_path(venue, sport, game_date)
    try:
        state = read_json_file(path) or {}
    except Exception:
        state = {}
    markets: dict[str, Any] = state.get("markets") or {}

    opened = appended = unchanged = unpriced = skipped = trimmed_points = 0
    parsed = 0
    unparsed_by_family: dict[str, int] = {}

    for row in rows:
        market_id = str((row or {}).get("id") or "").strip()
        if not market_id:
            skipped += 1
            continue
        yes = _as_float(row.get("yes"))
        no = _as_float(row.get("no"))
        if yes is None and no is None:
            # COUNTED, NOT DROPPED SILENTLY. A market the venue lists but does
            # not currently quote is a real fact about coverage -- it is the
            # difference between "they do not offer this" and "nobody is
            # making a price right now".
            unpriced += 1
            continue

        family = str(row.get("family") or "").strip() or "unknown"
        if row.get("market"):
            parsed += 1
        else:
            unparsed_by_family[family] = unparsed_by_family.get(family, 0) + 1

        entry = markets.get(market_id)
        if entry is None:
            # FIRST SIGHT IS THE OPENING. Days before the game on a lookahead
            # market, which is the only opening CLV can be measured against.
            # Written once and never rewritten.
            entry = {
                "market": row.get("market"),
                "family": family,
                "line": row.get("line"),
                "side": row.get("side"),
                "event": row.get("event"),
                "player": row.get("player"),
                # Kept even when the market IS parsed: it is what a future
                # grammar change is checked against.
                "raw_title": row.get("raw_title"),
                "opened_at": stamp,
                "opening_yes": yes,
                "opening_no": no,
                "points": [],
            }
            markets[market_id] = entry
            opened += 1
        elif row.get("market") and not entry.get("market"):
            # A grammar landed since this row was first seen. The market name
            # updates; the OPENING never does.
            entry["market"] = row.get("market")
            entry["line"] = row.get("line")
            entry["side"] = row.get("side")

        points = entry.setdefault("points", [])
        if points and points[-1].get("yes") == yes and points[-1].get("no") == no:
            unchanged += 1
            entry["last_seen"] = stamp
            continue
        points.append({"ts": stamp, "yes": yes, "no": no})
        entry["last_seen"] = stamp
        appended += 1
        if len(points) > MAX_POINTS_PER_MARKET:
            dropped = len(points) - MAX_POINTS_PER_MARKET
            # OLDEST out, and counted. Safe for the movement number only
            # because the opening lives in `opening_yes`, never in `points[0]`.
            entry["points"] = points[-MAX_POINTS_PER_MARKET:]
            trimmed_points += dropped

    trimmed_markets = 0
    if len(markets) > MAX_MARKETS_PER_FILE:
        ordered = sorted(
            markets.items(),
            key=lambda kv: str(kv[1].get("last_seen") or kv[1].get("opened_at") or ""),
            reverse=True,
        )
        trimmed_markets = len(markets) - MAX_MARKETS_PER_FILE
        markets = dict(ordered[:MAX_MARKETS_PER_FILE])

    state["markets"] = markets
    state["venue"] = venue
    state["sport"] = sport
    state["game_date"] = str(game_date or "")[:10]
    state["updated_at"] = stamp
    try:
        write_json_file(path, state)
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}

    # EVERY COUNTER, INCLUDING THE ZEROES. See the module docstring.
    return {
        "status": "ok",
        "venue": venue,
        "sport": sport,
        "game_date": state["game_date"],
        "listed": len(rows),
        "markets": len(markets),
        "opened": opened,
        "appended": appended,
        "unchanged": unchanged,
        "unpriced": unpriced,
        "skipped_no_id": skipped,
        "parsed": parsed,
        # THE COVERAGE GAP, BY FAMILY -- the number that makes the next grammar
        # writable. Empty means every market this venue listed for this sport
        # was named, which has never yet been true.
        "unparsed_by_family": dict(
            sorted(unparsed_by_family.items(), key=lambda kv: -kv[1])
        ),
        "trimmed_points": trimmed_points,
        "trimmed_markets": trimmed_markets,
    }


def kalshi_daily_rows(markets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Kalshi markets -> the common row shape, WITHOUT dropping anything.

    The classifier is consulted for the market name, and a refusal is recorded
    rather than acted on: `market` stays None and `raw_title` carries the
    string. That is the inversion -- the join refuses these, the record keeps
    them.
    """
    from syndicate.features.shared.kalshi_catalogue import (
        classify_market,
        game_date_from_ticker,
        sport_for_series,
    )

    out: list[dict[str, Any]] = []
    for market in markets or []:
        ticker = str(market.get("ticker") or "").strip()
        if not ticker:
            continue
        try:
            verdict = classify_market(market)
        except Exception:
            verdict = {"status": "error", "reason": "classify_raised"}
        ok = verdict.get("status") == "ok"
        out.append({
            "id": ticker,
            "market": verdict.get("market") if ok else None,
            "line": verdict.get("line") if ok else None,
            "side": verdict.get("side") if ok else None,
            "player": verdict.get("subject") if ok else None,
            # The refusal reason IS the family for an unparsed row: it names
            # why we could not read it, which is what a grammar is written
            # against.
            "family": str(market.get("series") or "") if ok else str(verdict.get("reason") or "unknown"),
            "event": market.get("event_ticker"),
            "raw_title": market.get("title"),
            "game_date": game_date_from_ticker(ticker),
            "sport": sport_for_series(market.get("series")),
            "yes": market.get("yes_ask_dollars"),
            "no": market.get("no_ask_dollars"),
        })
    return out


def polymarket_daily_rows(markets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Polymarket markets -> the common row shape, WITHOUT dropping anything.

    Includes the `PROP` and segment rows the join refuses. Measured
    2026-08-25: 6,838 and 1,064 of them respectively, fetched every cycle and
    discarded. `SPORTS_MARKET_TYPE_PROP` is a mixed bucket -- it holds League
    of Legends map winners as well as anything else -- so the venue TYPE is
    recorded as the family and nothing is inferred from it here.
    """
    from syndicate.features.shared.polymarket_board_join import (
        MARKET_TYPE_TO_BOARD,
        parse_slug,
    )

    out: list[dict[str, Any]] = []
    for row in markets or []:
        slug = str(row.get("slug") or "").strip()
        if not slug:
            continue
        parsed = parse_slug(slug)
        venue_type = str(row.get("sportsMarketTypeV2") or "").upper()
        board_market = MARKET_TYPE_TO_BOARD.get(venue_type)
        prices = _outcome_prices(row)
        out.append({
            "id": slug,
            "market": board_market,
            "line": None if parsed is None else _line_of(parsed),
            "side": None,
            "player": None,
            "family": venue_type or "unknown",
            "event": None if parsed is None else f"{parsed['away']}-{parsed['home']}",
            "raw_title": row.get("question"),
            "game_date": None if parsed is None else parsed["date"],
            "sport": None if parsed is None else parsed["league"],
            "yes": prices[0],
            "no": prices[1],
        })
    return out


def _line_of(parsed: Mapping[str, Any]) -> float | None:
    from syndicate.features.shared.polymarket_board_join import _line_from_modifiers

    try:
        return _line_from_modifiers(parsed.get("modifiers") or [])
    except Exception:
        return None


def _outcome_prices(row: Mapping[str, Any]) -> tuple[Any, Any]:
    """`outcomePrices` is a JSON string of two prices, or fewer.

    A ONE-SIDED quote is real on this venue (`outcomes` of two with `prices` of
    one -- 209 rows on 2026-08-25) and is recorded as the side it has rather
    than discarded: half a quote is still a price the venue showed.
    """
    import json

    raw = row.get("outcomePrices")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return (None, None)
    if not isinstance(raw, list) or not raw:
        return (None, None)
    first = raw[0] if len(raw) > 0 else None
    second = raw[1] if len(raw) > 1 else None
    return (first, second)


def in_scope_sports() -> frozenset[str]:
    """Which sports get a daily odds file. SPORTS SYNDICATE ACTUALLY MODELS.

    MEASURED 2026-08-25T17:34:36Z, the first run without this filter:

        POLYMARKET_DAILY_BOOK files=211 listed=12893
          detail=[{'sport': 'alsv'...}, {'sport': 'arg2'...},
                  {'sport': 'atbl'...}, {'sport': 'atp', 'markets': 940}]

    211 files -- Argentine second division, tennis, table tennis, esports --
    written to the keyvalue store every 180 seconds for leagues no Syndicate
    module models. Capture-first does not mean capture-everything: a market we
    have no sim, no board and no grader for cannot be priced, and paying
    storage and write bandwidth for it crowds out the sports that can.

    SOCCER IS THE OPEN EDGE, and it is left open deliberately. Syndicate models
    ten soccer leagues (`epl`, `la_liga`, `bundesliga`, ...) but Polymarket
    names leagues in its own vocabulary and the mapping between the two has
    never been read. Guessing it would either drop every soccer market or
    invent a league. So out-of-scope rows are COUNTED BY LEAGUE rather than
    discarded silently, and the codes become addable from data -- which is the
    same discipline that turned `unreadable_title` into a work list.

    Extendable without a deploy: `SYNDICATE_VENUE_ODDS_SPORTS` replaces the
    set, which is how a soccer code goes in the minute it is identified.
    """
    import os

    from syndicate.features.shared.artifact_manifests import SUPPORTED_SPORT_SLUGS

    raw = str(os.environ.get("SYNDICATE_VENUE_ODDS_SPORTS") or "").strip()
    if raw:
        chosen = {part.strip().lower() for part in raw.split(",") if part.strip()}
        if chosen:
            return frozenset(chosen)
    return frozenset(set(SUPPORTED_SPORT_SLUGS) | {"soccer"})


def record_venue_book(venue: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Group a venue's whole book by (sport, game date) and record each file.

    THE CALLER STAYS THIN ON PURPOSE. Grouping is the only place the per-sport
    split is decided, and that split exists for a hard reason -- the keyvalue
    store refuses at 8MB and `layer2_shortlist` already holds 5.0MB of it. A
    caller that grouped its own way could quietly reintroduce the single
    whole-book document this is written to avoid.

    A row with no readable sport or game date is COUNTED, never filed under
    today. Filing an undated market under the current date is how a stale
    market becomes tomorrow's opening line, and `game_date_from_ticker`
    returning None is a real outcome -- `26FEB30` is a date shape that is not a
    date.
    """
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    undated = 0
    wanted = in_scope_sports()
    skipped_by_sport: dict[str, int] = {}
    for row in rows or []:
        sport = str((row or {}).get("sport") or "").strip().lower()
        game_date = str((row or {}).get("game_date") or "").strip()[:10]
        if not sport or not game_date:
            undated += 1
            continue
        if sport not in wanted:
            # COUNTED, NEVER SILENT. This is where Polymarket's soccer league
            # codes will surface -- they are real markets in a sport we model,
            # under names we have not yet read.
            skipped_by_sport[sport] = skipped_by_sport.get(sport, 0) + 1
            continue
        grouped.setdefault((sport, game_date), []).append(row)

    files: list[dict[str, Any]] = []
    errors = 0
    listed = parsed = opened = appended = 0
    unparsed_by_family: dict[str, int] = {}
    for (sport, game_date), group in sorted(grouped.items()):
        result = record_daily_odds(venue, sport, game_date, group)
        if result.get("status") != "ok":
            errors += 1
            files.append({"sport": sport, "date": game_date, "error": result.get("reason")})
            continue
        listed += int(result.get("listed") or 0)
        parsed += int(result.get("parsed") or 0)
        opened += int(result.get("opened") or 0)
        appended += int(result.get("appended") or 0)
        for family, count in (result.get("unparsed_by_family") or {}).items():
            unparsed_by_family[family] = unparsed_by_family.get(family, 0) + count
        files.append({
            "sport": sport, "date": game_date,
            "markets": result.get("markets"), "appended": result.get("appended"),
        })

    return {
        "status": "ok" if not errors else "partial",
        "venue": venue,
        "files": len(files),
        "file_errors": errors,
        "listed": listed,
        "parsed": parsed,
        "opened": opened,
        "appended": appended,
        # A row we could not place in a day. Counted rather than filed under
        # today, and reported so it cannot become a silent gap.
        "undated": undated,
        # Out of scope by SPORT, by name and count. The top entries here are
        # the candidate soccer leagues; everything else is a sport Syndicate
        # does not model and correctly does not store.
        "skipped_by_sport": dict(
            sorted(skipped_by_sport.items(), key=lambda kv: -kv[1])[:20]
        ),
        "skipped_total": sum(skipped_by_sport.values()),
        "unparsed_by_family": dict(
            sorted(unparsed_by_family.items(), key=lambda kv: -kv[1])
        ),
        "detail": files[:12],
    }
