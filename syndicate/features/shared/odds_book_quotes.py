"""Per-book, per-timestamp odds quotes -- the record CLV and best-price work needs.

WHY THIS IS A SEPARATE ARTIFACT FAMILY (#208/#209)
--------------------------------------------------
Every sport's OddsAPI call already returns 5-8 US books per market. Most of our
fetchers then keep exactly one and throw the rest away (#209 Class A), and the
one basketball fetcher that keeps them all writes to a file `odds_history` never
reads (#209 Class B). The consequence measured 2026-08-05: every ROI number in
#186-#204 was graded against one arbitrarily-chosen bookmaker, and closing-line
capture sat at 2.13% (MLB) / 6.85% (WNBA), game markets only.

The obvious fix -- add a `bookmaker` dimension to `odds_history` -- was measured
and rejected. That shard is already 54MB at 3,682 MLB market keys (~14.7KB/key
at 20 history entries); restoring ~5 books to the 3,437 prop keys would put it
near 250MB, written AND published every cycle on 2GB services. Worse, four
existing consumers assume one book per game and would silently pick an arbitrary
one instead of breaking loudly:
  - mlb/cards.py `_tracked_game_lines_index` keys on the team pair only, and its
    commence_time tiebreak ties for every book of the same game;
  - odds_refresh_tracking `_flatten_mlb_game_lines` omits book from `key_cols`,
    so `.first()`/`.last()` in `_persist_tracking_snapshot` would land on
    different books and report a cross-book spread as a line MOVE;
  - live_refresh_loop `_mlb_sim_input_fingerprint_by_game` would fold every
    book's line into one game's hash, so any single book twitching triggers a
    resim -- a resim storm, on the 4GB worker;
  - mlb/cards.py's odds-history movement badges take `next(...)` first-match.

So `odds_history` keeps its current single-book, display-oriented shape, and the
per-book truth lives here instead: one flat JSONL row per (event, book, market,
selection, price) observation, append-only, published cross-service.

WHAT THIS BUYS
--------------
Closing lines stop needing a stamp. `odds_refresh_tracking.py:1599` can only
stamp a close on a pregame->live transition, which it detects from
`commence_time` or live text markers -- and MLB prop keys carry neither (they
are literally `player_name=...|market=...|selection=...`), which is why prop
closing capture is structurally zero rather than merely low. Every row here
carries `commence_time`, so the closing line is simply the last observation
before it: a lookup, not an inference, and correct retroactively for any row
already written.

Dedupe is against the LAST value seen for a quote key, not against the whole
file -- so an unchanged price is not re-appended every 60-second cycle, but a
line that moves away and comes back is still recorded both times. The last-value
map lives in a small sidecar rather than by re-reading the JSONL, because
re-reading a tens-of-MB file every cycle on the odds worker is the same class of
mistake this module exists to avoid.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.shared.refresh_state_store import data_root

# Kept deliberately flat and uniform across sports. A consumer that can read
# MLB's rows can read WNBA's without a per-sport branch -- the thing the current
# odds_history snapshot-path routing (one bespoke file list per sport) does not
# give us.
QUOTE_FIELDS: tuple[str, ...] = (
    "captured_at",
    "snapshot_ts",
    # TWO CLOCKS, NEVER CONFLATED.
    #
    # `captured_at` is when OUR loop looked. `book_updated_at` is when the BOOK
    # last moved this number, straight from OddsAPI's per-market `last_update`.
    # They fail independently and the difference is the diagnostic: a price
    # whose book last moved four hours ago but which we polled 30 seconds ago is
    # a DEAD MARKET, and every surface in this repo currently renders it as
    # fresh, because loop time was the only clock available.
    #
    # Deliberately None when the source did not give us one -- NOT defaulted to
    # captured_at. `snapshot_ts` above does fall back to captured_at and is kept
    # only for the consumers written against it; anything reasoning about
    # freshness must read this field and treat None as unknown. Falling back
    # here would silently recreate the exact conflation this exists to remove.
    "book_updated_at",
    "sport",
    "date",
    "kind",
    "event_id",
    "commence_time",
    "home_team",
    "away_team",
    "bookmaker",
    "market",
    "segment",
    "selection",
    "player_name",
    "line",
    "price",
)

# Identity of a quote across time. Everything that distinguishes one price from
# another EXCEPT the price and line themselves, which are what we watch move.
_KEY_FIELDS: tuple[str, ...] = (
    "sport",
    "kind",
    "event_id",
    "bookmaker",
    "segment",
    "market",
    "selection",
    "player_name",
)


def book_quotes_path(sport: str, date_str: str) -> Path:
    slug = str(sport or "").strip().lower()
    return data_root() / f"{slug}_source" / "tracking" / "book_quotes" / f"{str(date_str).strip()}.jsonl"


def _state_path(sport: str, date_str: str) -> Path:
    return book_quotes_path(sport, date_str).with_suffix(".state.json")


def _coerce_price(value: Any) -> int | None:
    """American odds as an int. MLB's fetcher stores them as strings ("+410"),
    basketball's as ints, soccer's as floats -- normalise so a cross-sport
    consumer never has to care."""
    if value is None:
        return None
    text = str(value).strip().replace("+", "")
    if not text:
        return None
    try:
        return int(round(float(text)))
    except Exception:
        return None


def _coerce_line(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _normalize(row: Mapping[str, Any], *, sport: str, date_str: str, captured_at: str) -> dict[str, Any] | None:
    bookmaker = str(row.get("bookmaker") or row.get("book") or "").strip().lower()
    market = str(row.get("market") or "").strip()
    if not bookmaker or not market:
        return None
    price = _coerce_price(row.get("price") if "price" in row else row.get("odds"))
    line = _coerce_line(row.get("line") if "line" in row else row.get("point"))
    # A row with neither a price nor a line records nothing about the market.
    if price is None and line is None:
        return None
    player = str(row.get("player_name") or row.get("player") or "").strip()
    # See QUOTE_FIELDS: this one stays None when the source has no book clock.
    book_updated_at = str(
        row.get("book_updated_at") or row.get("last_update") or row.get("snapshot_ts") or ""
    ).strip() or None
    out = {
        "captured_at": captured_at,
        "snapshot_ts": str(row.get("snapshot_ts") or row.get("last_update") or captured_at),
        "book_updated_at": book_updated_at,
        "sport": str(sport or "").strip().lower(),
        "date": str(date_str).strip(),
        "kind": str(row.get("kind") or ("prop" if player else "game")),
        "event_id": str(row.get("event_id") or "").strip() or None,
        "commence_time": str(row.get("commence_time") or "").strip() or None,
        "home_team": str(row.get("home_team") or "").strip() or None,
        "away_team": str(row.get("away_team") or "").strip() or None,
        "bookmaker": bookmaker,
        "market": market,
        "segment": str(row.get("segment") or "full").strip() or "full",
        "selection": str(row.get("selection") or row.get("side") or row.get("outcome_name") or "").strip() or None,
        "player_name": player or None,
        "line": line,
        "price": price,
    }
    return out


def _quote_key(row: Mapping[str, Any]) -> str:
    return "|".join(str(row.get(field) or "") for field in _KEY_FIELDS)


def _load_state(path: Path) -> dict[str, list[Any]]:
    try:
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return {str(key): list(value) for key, value in loaded.items() if isinstance(value, (list, tuple))}
    except Exception:
        pass
    return {}


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def append_book_quotes(
    *,
    sport: str,
    date_str: str,
    rows: Iterable[Mapping[str, Any]],
    captured_at: str,
    publish: bool = True,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append every quote whose (line, price) differs from that key's last
    observation. Never raises: a quotes-log failure must not fail an odds
    refresh, exactly as the #207 diagnostic must not.

    `extra` stamps constant fields onto every row -- soccer's `league`, which is
    the one dimension a single `sport` slug cannot express, since all eight
    leagues share the `soccer_source` tree.
    """
    try:
        path = book_quotes_path(sport, date_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        state_path = _state_path(sport, date_str)
        state = _load_state(state_path)

        appended: list[dict[str, Any]] = []
        seen_this_call: set[str] = set()
        considered = 0
        for raw in rows or ():
            if not isinstance(raw, Mapping):
                continue
            considered += 1
            normalized = _normalize(raw, sport=sport, date_str=date_str, captured_at=captured_at)
            if normalized is None:
                continue
            for field, value in (extra or {}).items():
                normalized.setdefault(str(field), value)
            key = _quote_key(normalized)
            # Two books can legitimately post the same key twice in one payload
            # (alternate lines arrive as separate outcomes); keep the first.
            if key in seen_this_call:
                continue
            seen_this_call.add(key)
            current = [normalized.get("line"), normalized.get("price")]
            if state.get(key) == current:
                continue
            state[key] = current
            appended.append(normalized)

        if appended:
            with path.open("a", encoding="utf-8") as handle:
                for row in appended:
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            _write_state(state_path, state)

        result = {
            "path": str(path),
            "considered": int(considered),
            "appended": int(len(appended)),
            "tracked_keys": int(len(state)),
            "books": sorted({str(row.get("bookmaker")) for row in appended}),
        }
        published = None
        if publish and appended:
            try:
                from syndicate.features.shared.artifact_publisher import publish_hot_artifact

                published = publish_hot_artifact(path)
            except Exception as exc:
                published = f"failed {type(exc).__name__}: {exc}"
        result["published"] = published
        print(f"[odds_book_quotes] {json.dumps(result, sort_keys=True)}", flush=True)
        return result
    except Exception as exc:
        print(f"[odds_book_quotes] FAILED sport={sport} date={date_str} error={type(exc).__name__}: {exc}", flush=True)
        return {"error": f"{type(exc).__name__}: {exc}", "appended": 0}


def quote_rows_from_oddsapi_events(
    events: Iterable[Mapping[str, Any]],
    *,
    market_map: Mapping[str, str] | None = None,
    segment: str = "full",
) -> list[dict[str, Any]]:
    """Flatten the standard OddsAPI `event -> bookmakers -> markets -> outcomes`
    nesting into quote rows, keeping EVERY book.

    Shared by the fetchers whose only book-handling code is a
    `_choose_bookmaker` that returns one book and drops the rest -- NFL props,
    NFL team odds and NCAAF props all carry a byte-identical copy of that
    function (#209 Class A). They keep their single-book CSV; this gives the
    quote log the other four-to-seven books the same paid-for response already
    contained.

    `market_map` restricts and renames markets (the caller's own canonical
    names); omit it to keep every market under its raw OddsAPI key.
    """
    rows: list[dict[str, Any]] = []
    for event in events or ():
        if not isinstance(event, Mapping):
            continue
        home_team = str(event.get("home_team") or "").strip()
        away_team = str(event.get("away_team") or "").strip()
        event_id = str(event.get("id") or event.get("event_id") or "").strip() or None
        commence_time = event.get("commence_time")
        for bookmaker in (event.get("bookmakers") or []):
            if not isinstance(bookmaker, Mapping):
                continue
            book_key = str(bookmaker.get("key") or bookmaker.get("title") or "").strip()
            if not book_key:
                continue
            for market in (bookmaker.get("markets") or []):
                if not isinstance(market, Mapping):
                    continue
                raw_key = str(market.get("key") or "").strip()
                if market_map is not None:
                    if raw_key not in market_map:
                        continue
                    market_name = str(market_map[raw_key])
                else:
                    market_name = raw_key
                if not market_name:
                    continue
                for outcome in (market.get("outcomes") or []):
                    if not isinstance(outcome, Mapping):
                        continue
                    name = str(outcome.get("name") or "").strip()
                    description = str(outcome.get("description") or "").strip()
                    lowered = name.lower()
                    if lowered.startswith("over"):
                        selection = "over"
                    elif lowered.startswith("under"):
                        selection = "under"
                    elif home_team and name == home_team:
                        selection = "home"
                    elif away_team and name == away_team:
                        selection = "away"
                    else:
                        selection = lowered or None
                    # For player markets OddsAPI puts the player in
                    # `description` and the side in `name`; for team markets
                    # `description` is absent and `name` IS the team.
                    player = description if description and description not in {home_team, away_team} else ""
                    rows.append(
                        {
                            "kind": "prop" if player else "game",
                            "event_id": event_id,
                            "commence_time": commence_time,
                            "home_team": home_team or None,
                            "away_team": away_team or None,
                            "bookmaker": book_key,
                            "market": market_name,
                            "segment": segment,
                            "selection": selection,
                            "player_name": player or None,
                            "line": outcome.get("point"),
                            "price": outcome.get("price"),
                            "snapshot_ts": market.get("last_update") or bookmaker.get("last_update"),
                        }
                    )
    return rows


def read_book_quotes(sport: str, date_str: str) -> list[dict[str, Any]]:
    path = book_quotes_path(sport, date_str)
    rows: list[dict[str, Any]] = []
    try:
        if not path.is_file():
            return rows
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
    except Exception:
        return rows
    return rows


def closing_quotes(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """The last observation of each quote key strictly before its own
    commence_time -- the textbook closing line, as a lookup rather than the
    transition-stamp inference `odds_refresh_tracking` has to make.

    Rows whose commence_time is missing or unparseable are skipped rather than
    guessed at: #82's rule, and the reason the existing stamp deliberately
    leaves closing_line unset instead of recording an in-play number.
    """
    best: dict[str, dict[str, Any]] = {}
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        commence = str(row.get("commence_time") or "").strip()
        observed = str(row.get("snapshot_ts") or row.get("captured_at") or "").strip()
        if not commence or not observed:
            continue
        if observed >= commence:
            continue
        key = _quote_key(row)
        previous = best.get(key)
        if previous is None or observed > str(previous.get("snapshot_ts") or previous.get("captured_at") or ""):
            best[key] = dict(row)
    return best


def best_price_by_market(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Best available American price per (event, market, segment, selection,
    player, line), across books -- the join #206 wanted for re-grading and could
    not do while only one book survived capture.

    "Best" is the highest payout for the bettor: for positive American odds the
    larger number, for negative the one closer to zero. Comparing raw ints gets
    that right in both cases, which is the one thing worth stating explicitly
    since it looks like it should need a branch.
    """
    best: dict[str, dict[str, Any]] = {}
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        price = row.get("price")
        if price is None:
            continue
        key = "|".join(
            str(row.get(field) or "")
            for field in ("sport", "kind", "event_id", "segment", "market", "selection", "player_name", "line")
        )
        previous = best.get(key)
        if previous is None or int(price) > int(previous.get("price") or -10**9):
            best[key] = dict(row)
    return best


def market_key_for_quote(row: Mapping[str, Any]) -> str:
    """The cross-book identity of a market: everything except which book quoted
    it. Same key `best_price_by_market` groups on, exposed so callers can look a
    market up without reimplementing (and drifting from) the field list."""
    return "|".join(
        str(row.get(field) or "")
        for field in ("sport", "kind", "event_id", "segment", "market", "selection", "player_name", "line")
    )


def _age_seconds(timestamp: Any, *, now: datetime) -> int | None:
    text = str(timestamp or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int((now - parsed).total_seconds()))


def _implied_probability(price: int) -> float:
    return (100.0 / (price + 100.0)) if price > 0 else (abs(price) / (abs(price) + 100.0))


def quote_ref(
    quotes_for_market: Iterable[Mapping[str, Any]],
    *,
    chosen_bookmaker: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """The board/ledger-facing description of a price: which book, what number,
    when that book moved it, and how it compares to everyone else quoting it.

    This is the object the read path never had. A Layer 2 candidate row is built
    from display_pick/ev_pct/p_win/market_label/selection and carries no price,
    no book and no timestamp -- which is why "which book has the edge" had
    nowhere to live and CLV had no opening price to record.

    `consensus_price` is here on purpose and matters as much as `price`. A best
    price 40 points clear of every other book is usually a stale or erroneous
    line rather than an edge; `price_rank: 1` alone is not evidence, and
    `price_rank: 1` against a tight consensus of six books is. Surfacing rank
    without consensus would invite exactly the wrong read.

    Pass `chosen_bookmaker` to describe a price we actually took (a logged bet);
    omit it to describe the best available.
    """
    rows = [row for row in (quotes_for_market or ()) if isinstance(row, Mapping) and row.get("price") is not None]
    if not rows:
        return None
    now = now or datetime.now(timezone.utc)

    ranked = sorted(rows, key=lambda row: int(row["price"]), reverse=True)
    chosen = None
    if chosen_bookmaker:
        wanted = str(chosen_bookmaker).strip().lower()
        chosen = next((row for row in ranked if str(row.get("bookmaker") or "").lower() == wanted), None)
    if chosen is None:
        chosen = ranked[0]

    price = int(chosen["price"])
    # Mean implied probability across books, converted back to a price-like
    # number. Averaging American odds directly is meaningless (the scale is
    # discontinuous at +/-100); averaging implied probability is not.
    mean_implied = sum(_implied_probability(int(row["price"])) for row in ranked) / len(ranked)
    consensus_price = (
        int(round(-100.0 * mean_implied / (1.0 - mean_implied))) if mean_implied >= 0.5
        else int(round(100.0 * (1.0 - mean_implied) / mean_implied))
    )

    return {
        "bookmaker": chosen.get("bookmaker"),
        "price": price,
        "line": chosen.get("line"),
        "book_updated_at": chosen.get("book_updated_at"),
        "captured_at": chosen.get("captured_at"),
        "book_age_seconds": _age_seconds(chosen.get("book_updated_at"), now=now),
        "capture_age_seconds": _age_seconds(chosen.get("captured_at"), now=now),
        "price_rank": ranked.index(chosen) + 1,
        "books_quoting": len(ranked),
        "best_price": int(ranked[0]["price"]),
        "best_bookmaker": ranked[0].get("bookmaker"),
        "consensus_price": consensus_price,
        "edge_vs_consensus_pct": round((_implied_probability(consensus_price) - _implied_probability(price)) * 100, 2),
        "alternatives": [
            {"bookmaker": row.get("bookmaker"), "price": int(row["price"]), "line": row.get("line")}
            for row in ranked
        ],
    }


def quotes_by_market(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group quote rows by cross-book market identity, keeping only the freshest
    observation per book so `quote_ref` compares one price per book rather than
    every price each book has posted today."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows or ():
        if not isinstance(row, Mapping) or row.get("price") is None:
            continue
        key = (market_key_for_quote(row), str(row.get("bookmaker") or ""))
        observed = str(row.get("book_updated_at") or row.get("snapshot_ts") or row.get("captured_at") or "")
        previous = latest.get(key)
        if previous is None or observed >= str(
            previous.get("book_updated_at") or previous.get("snapshot_ts") or previous.get("captured_at") or ""
        ):
            latest[key] = dict(row)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for (market, _book), row in latest.items():
        grouped.setdefault(market, []).append(row)
    return grouped
