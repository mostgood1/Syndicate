#!/usr/bin/env python3
"""Rebuild a day's pregame game-line freeze from the `book_quotes` shard.

WHY THIS EXISTS. `refresh_mlb_oddsapi._freeze_oddsapi_pregame_markets` seals the
pregame lines so a finished slate keeps them, but that freeze was unreachable
until 2026-08-08 (its guard was `mode == "live" -> skip` and every writer stamps
`mode: live`). While it could not fire, the LIVE game-lines file was rewritten
each pass with only the events still in progress, so an overnight slate collapsed
to its last West-Coast game.

Measured consequence on production, 2026-08-11:

    date        pregame freeze   live file   payload games / slate
    2026-08-05      ABSENT          1,754        1 of 13
    2026-08-07      ABSENT          2,561        3 of 16
    2026-08-08      56,864          1,824        2 of 13
    2026-08-10      38,279         23,350       10 of 10

`build_season_betting_cards_manifest` joins the day's card against that file and
warns `Missing game-line match` for every game that vanished -- then DROPS the
game, its props included. So a full slate graded a handful of rows, settlement
matched almost nothing, and the ledger stayed pending.

WHY `book_quotes` CAN REPAIR IT. The shard is an append-only capture log. It was
never rewritten, so it still holds every game's pregame quotes from every book.
Verified on the first 6 MB of the 329 MB 2026-08-07 shard: 15 distinct events,
6,210 `kind=game` rows, `draftkings` present on 15 of 15.

WHAT THIS RECONSTRUCTS, AND WHAT IT CANNOT
------------------------------------------
It rebuilds the game-line freeze -- `h2h`, `spreads`, `totals` -- which is the
join key the grader needs. It does NOT invent outcomes: grading still reads
actual results from the day's card. This repairs the JOIN, not the truth.

**It cannot reach most of the gap.** Shards exist only from 2026-08-06; every
date from 2026-07-09 to 2026-08-05 has no shard, so those days are
unrecoverable by this route and this script will say so rather than write a
thin file that looks repaired.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The freeze carries the three game-line families the grader joins on. Alt
# ladders (`spreads_alt`, `totals_alt`) are deliberately excluded: the live
# writer's own `alternates: []` shape is what the consumer expects, and
# inventing populated ladders here would make a reconstructed file structurally
# different from a natural one in a way nothing downstream asked for.
_MARKETS = ("h2h", "spreads", "totals")

# Preference order, then "most complete". draftkings first because the natural
# freeze files sampled on 2026-08-08 use it, so a reconstructed file matches
# what a real one looks like for the same slate.
_BOOK_PREFERENCE = ("draftkings", "fanduel", "betmgm", "caesars", "bovada")


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _central_date(moment: datetime) -> str:
    """The slate date a kickoff belongs to, in the clock this repo uses."""
    try:
        from zoneinfo import ZoneInfo

        return moment.astimezone(ZoneInfo("America/Chicago")).date().isoformat()
    except Exception:
        # Never let a tz lookup silently reclassify every game: falling back to
        # UTC would split a slate at midnight, so say so by returning UTC and
        # letting the count look wrong rather than wrong-but-plausible.
        return moment.astimezone(timezone.utc).date().isoformat()


def _price_text(value: Any) -> str | None:
    """American odds as the freeze writes them: '+138' / '-148'."""
    try:
        price = int(value)
    except (TypeError, ValueError):
        return None
    return f"+{price}" if price > 0 else str(price)


def collect_pregame_quotes(sport: str, date_str: str) -> dict[str, dict[str, Any]]:
    """Freshest PREGAME quote per (event, book, market, selection).

    The pregame test is each GAME's own clock -- `captured_at < commence_time`
    for that event -- not a slate-wide cutoff and not a mode string. That is the
    same rule `_freeze_oddsapi_pregame_markets` settled on, and it is what makes
    a late West-Coast start keep its own pregame line while an afternoon game
    that has already finished keeps its.

    Streams via `iter_book_quotes` (`#331`): these shards reach 329 MB and
    holding every parsed row costs ~6.3x resident.
    """
    from syndicate.features.shared.odds_book_quotes import iter_book_quotes

    events: dict[str, dict[str, Any]] = {}
    scanned = 0
    kept = 0
    for row in iter_book_quotes(sport, date_str):
        scanned += 1
        if row.get("kind") != "game" or row.get("segment") != "full":
            continue
        market = str(row.get("market") or "")
        if market not in _MARKETS:
            continue
        event_id = str(row.get("event_id") or "")
        book = str(row.get("bookmaker") or "")
        selection = str(row.get("selection") or "").strip().lower()
        if not event_id or not book or not selection:
            continue

        commence = _parse_ts(row.get("commence_time"))
        captured = _parse_ts(row.get("captured_at"))
        if commence is None or captured is None or captured >= commence:
            continue  # not pregame for THIS game

        # A SHARD IS KEYED BY CAPTURE DATE, NOT SLATE DATE. Measured on the
        # 2026-07-20 shard: 5 events commence 07-19, 8 on 07-20, 14 on 07-21,
        # 5 on 07-22 -- look-ahead quotes for games days out. Without this
        # filter the freeze for a 13-game slate carried 28-48 games, which is
        # the same capture-vs-game date confusion that puts NFL's September
        # fixtures in an August book-grid artifact.
        #
        # CENTRAL, not UTC: an MLB slate spans two UTC dates (2026-08-10 ran
        # 23:07Z through 02:10Z the next day), so a UTC test would cut a slate
        # in half. `central_today_iso` is the slate clock everywhere else here.
        if _central_date(commence) != date_str:
            continue

        entry = events.setdefault(
            event_id,
            {
                "event_id": event_id,
                "commence_time": row.get("commence_time"),
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "books": {},
            },
        )
        slot = entry["books"].setdefault(book, {})
        key = (market, selection)
        current = slot.get(key)
        # Freshest pregame quote wins -- the closing pregame line, not the first
        # one seen. A first-seen rule would freeze a line captured a day early.
        if current is None or captured > current["_captured"]:
            slot[key] = {
                "_captured": captured,
                "price": row.get("price"),
                "line": row.get("line"),
            }
            kept += 1
    return {"events": events, "scanned": scanned, "kept": kept}


def _markets_for_book(quotes: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any] | None:
    """Shape one book's quotes into the freeze's `markets` block."""
    markets: dict[str, Any] = {}

    h2h_home = quotes.get(("h2h", "home"))
    h2h_away = quotes.get(("h2h", "away"))
    if h2h_home and h2h_away:
        markets["h2h"] = {
            "home_odds": _price_text(h2h_home["price"]),
            "away_odds": _price_text(h2h_away["price"]),
        }

    sp_home = quotes.get(("spreads", "home"))
    sp_away = quotes.get(("spreads", "away"))
    if sp_home and sp_away:
        markets["spreads"] = {
            "home_line": sp_home.get("line"),
            "home_odds": _price_text(sp_home["price"]),
            "away_line": sp_away.get("line"),
            "away_odds": _price_text(sp_away["price"]),
            "_src": "book_quotes_backfill",
            "alternates": [],
        }

    tot_over = quotes.get(("totals", "over"))
    tot_under = quotes.get(("totals", "under"))
    if tot_over and tot_under:
        markets["totals"] = {
            "line": tot_over.get("line"),
            "over_odds": _price_text(tot_over["price"]),
            "under_odds": _price_text(tot_under["price"]),
            "_src": "book_quotes_backfill",
            "alternates": [],
        }

    if not markets:
        return None
    # The live writer nests the same block under `segments.full`; consumers read
    # either, so emit both rather than betting on which one a reader picked.
    markets["segments"] = {"full": {k: v for k, v in markets.items() if k in _MARKETS}}
    return markets


def build_freeze_document(sport: str, date_str: str) -> dict[str, Any]:
    collected = collect_pregame_quotes(sport, date_str)
    events = collected["events"]
    games: list[dict[str, Any]] = []
    skipped_no_markets: list[str] = []

    for event_id, entry in events.items():
        books = entry["books"]
        chosen_book = None
        chosen_markets = None
        # Preference first, then the book yielding the most complete block. A
        # game with only an obscure book is still better than a dropped game --
        # a dropped game is what this whole exercise exists to prevent.
        ordered = [b for b in _BOOK_PREFERENCE if b in books] + sorted(
            b for b in books if b not in _BOOK_PREFERENCE
        )
        best_size = -1
        for book in ordered:
            shaped = _markets_for_book(books[book])
            if shaped is None:
                continue
            size = len([k for k in shaped if k in _MARKETS])
            if book in _BOOK_PREFERENCE and size == len(_MARKETS):
                chosen_book, chosen_markets = book, shaped
                break
            if size > best_size:
                best_size, chosen_book, chosen_markets = size, book, shaped
        if chosen_markets is None:
            skipped_no_markets.append(event_id)
            continue
        games.append(
            {
                "event_id": event_id,
                "commence_time": entry["commence_time"],
                "home_team": entry["home_team"],
                "away_team": entry["away_team"],
                "bookmaker": chosen_book,
                "markets": chosen_markets,
            }
        )

    games.sort(key=lambda g: str(g.get("commence_time") or ""))
    return {
        "date": date_str,
        # `mode` matches what every real writer stamps; the reconstruction is
        # declared in `meta`, not by lying about mode, so a reader that keys on
        # mode behaves identically on a natural and a rebuilt file.
        "mode": "live",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "games": games,
        "meta": {
            "source": "book_quotes_backfill",
            "script": Path(__file__).name,
            "quote_rows_scanned": collected["scanned"],
            "pregame_quotes_kept": collected["kept"],
            "events_seen": len(events),
            "games_written": len(games),
            "events_without_complete_market": skipped_no_markets,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="slate date, YYYY-MM-DD")
    parser.add_argument("--sport", default="mlb")
    parser.add_argument("--write", action="store_true", help="persist; default is a dry run")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing freeze (refused by default -- a natural freeze outranks a rebuild)",
    )
    args = parser.parse_args()

    from syndicate.features.mlb.sources import daily_snapshot_oddsapi_game_lines_pregame_path
    from syndicate.features.shared.odds_book_quotes import book_quotes_path

    shard = book_quotes_path(args.sport, args.date)
    if not shard.is_file():
        # Stated loudly: for 2026-07-09..2026-08-05 there is no shard, and this
        # is the honest answer rather than an empty file that looks repaired.
        print(f"NO_SHARD sport={args.sport} date={args.date} path={shard}", flush=True)
        print("  This date cannot be repaired from book_quotes.", flush=True)
        return 2

    target = daily_snapshot_oddsapi_game_lines_pregame_path(args.date)
    if target.is_file() and not args.overwrite:
        print(f"FREEZE_EXISTS date={args.date} bytes={target.stat().st_size} path={target}", flush=True)
        print("  Refusing to replace a natural freeze. Pass --overwrite to force.", flush=True)
        return 3

    doc = build_freeze_document(args.sport, args.date)
    meta = doc["meta"]
    print(
        f"BACKFILL_PREGAME date={args.date} scanned={meta['quote_rows_scanned']} "
        f"kept={meta['pregame_quotes_kept']} events={meta['events_seen']} "
        f"games={meta['games_written']} incomplete={len(meta['events_without_complete_market'])}",
        flush=True,
    )
    for game in doc["games"]:
        print(
            f"   {game['away_team']} @ {game['home_team']}  book={game['bookmaker']}  "
            f"markets={sorted(k for k in game['markets'] if k in _MARKETS)}",
            flush=True,
        )

    if not args.write:
        print("DRY RUN -- nothing written. Pass --write to persist.", flush=True)
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, default=str)
    tmp.replace(target)
    print(f"WROTE {target} bytes={target.stat().st_size}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
