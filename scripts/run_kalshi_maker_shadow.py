"""Hourly PAPER Kalshi maker shadow (lane `kalshi-maker-shadow-paper`). Places NO orders.

Pre-registration: `.syndicate/findings_2026-10-20_kalshi_maker_shadow_preregistration.md`. Rule and
store: `syndicate/features/shared/kalshi_maker_shadow.py`.

Each run, per sport (soccer, NCAAF):
  1. reads the recorded Kalshi book (`reports/intelligence/venue_odds/kalshi__<sport>__<date>.json`) and
     the sportsbook quote log (`<sport>_source/tracking/book_quotes/<date>.jsonl[.gz]`);
  2. pairs them with the PRODUCTION join (`kalshi_board_join.join_kalshi_to_board`) and keeps the
     pre-registered cells on `quadratic` series (fee type read live from Kalshi `GET /series`);
  3. per ticker-leg, evaluates the bid rule at each recorded point NEWER than the last run scanned
     (venue_odds keeps only the last 48 points, so the scan is incremental and hourly) and freezes the
     first placement;
  4. after commence, closes the order: fill A (recorded asks), fill B (Kalshi public trade prints), the
     fair at placement / fills / close; later reads the Kalshi `result`.

Writes only `<data root>/reports/intelligence/kalshi_maker_shadow/`. Runs at nice 19.

Usage:
    python scripts/run_kalshi_maker_shadow.py                  # the hourly job
    python scripts/run_kalshi_maker_shadow.py --days-back 5    # catch up after downtime
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The join's game-line flags as the fleet's workers run them (read from their environ 2026-10-19 by the
# 10-19 study). setdefault: a value the job inherits from the supervisor wins.
for _key, _value in (("SYNDICATE_KALSHI_GAME_LINES", "1"),
                     ("SYNDICATE_KALSHI_FORWARD_DATE_SPORTS", "soccer,ncaaf,nfl"),
                     ("SYNDICATE_KALSHI_SOCCER_RESOLVERS", "1"),
                     ("SYNDICATE_KALSHI_JOIN_ALL_GAME_LINES", "1")):
    os.environ.setdefault(_key, _value)

from syndicate.features.shared import kalshi_maker_shadow as ms  # noqa: E402

DAY = 86400


def data_root() -> Path:
    override = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(override).expanduser().resolve() if override else REPO_ROOT / "data"


def rows_of(path: Path) -> Iterable[dict[str, Any]]:
    opener = gzip.open if str(path).endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    yield row
    except (OSError, EOFError):
        return


def date_range(center: dt.date, back: int, ahead: int) -> list[str]:
    return [(center + dt.timedelta(days=d)).isoformat() for d in range(-back, ahead + 1)]


# ------------------------------------------------------------------ inputs
def venue_markets(root: Path, sport: str, dates: Iterable[str]) -> dict[str, dict[str, dict[str, Any]]]:
    """{game_date: {ticker: entry}} for the totals/spreads families (the only ones a cell can come from)."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    base = root / "reports" / "intelligence" / "venue_odds"
    for date in dates:
        doc = ms.load_json(base / f"kalshi__{sport}__{date.replace('-', '_')}.json", None)
        if not isinstance(doc, dict):
            continue
        keep = {}
        for ticker, entry in (doc.get("markets") or {}).items():
            market = str((entry or {}).get("market") or "")
            if market.startswith("totals") or market.startswith("spreads"):
                keep[ticker] = entry
        if keep:
            out[date] = keep
    return out


# One sportsbook game-line quote as a tuple. The files are STREAMED twice (board, then quote book) rather
# than held: ~380k NCAAF rows as dicts peaked at 1.1 GB RSS on 10-20, as tuples 558 MB.
QUOTE_FIELDS = ("event_id", "kind", "market", "segment", "player_name", "selection", "line", "price", "bookmaker",
                "captured_at", "commence_time", "home_team", "away_team")


def quote_rows(root: Path, sport: str, dates: Iterable[str]) -> Iterable[tuple]:
    """Sportsbook GAME-line rows (h2h/totals/spreads, exchanges excluded) from the dated quote files, as
    tuples in `QUOTE_FIELDS` order. A generator: call it once per pass."""
    base = root / f"{sport}_source" / "tracking" / "book_quotes"
    for date in sorted(set(dates)):
        for name in (f"{date}.jsonl", f"{date}.jsonl.gz"):
            path = base / name
            if not path.is_file():
                continue
            for r in rows_of(path):
                if r.get("kind") == "prop" or str(r.get("market") or "") not in ms.BOARD_MARKETS:
                    continue
                book = str(r.get("bookmaker") or "").lower()
                if book in ms.EXCHANGES or not r.get("event_id"):
                    continue
                yield tuple(book if k == "bookmaker" else r.get(k) for k in QUOTE_FIELDS)


def board_from_quotes(sport: str, rows: Iterable[tuple]) -> tuple[dict[str, dict], list[dict], int]:
    """Events (LATEST-captured commence_time wins: OddsAPI revises college kickoffs) and one pseudo-board
    row per (event, market, segment, player, selection, line) -- the 10-19 study's construction."""
    events: dict[str, dict[str, Any]] = {}
    identities: dict[tuple, Any] = {}
    n = 0
    for (ev, kind, market, seg, player, sel, line, price, _book, captured, commence, home, away) in rows:
        ev = str(ev)
        cap = ms.ts(captured) or 0.0
        cur = events.get(ev)
        if cur is None or cap >= cur["_cap"]:
            events[ev] = {"home_team": home, "away_team": away, "commence_time": commence, "_cap": cap}
        identities.setdefault((ev, kind, market, seg, player, sel, line), price)
        n += 1
    board = []
    for (ev, kind, market, seg, player, sel, line), price in identities.items():
        e = events[ev]
        board.append({"sport": sport, "event_id": ev, "kind": kind, "market": market, "segment": seg,
                      "player_name": player, "side": sel, "selection": sel, "line": line, "price": price,
                      "home_team": e["home_team"], "away_team": e["away_team"],
                      "commence_time": e["commence_time"], "game_state": "pregame"})
    return events, board, n


def production_join(sport: str, kal_by_date: Mapping[str, Mapping[str, dict]],
                    board: list[dict]) -> tuple[dict[tuple[str, str], tuple[tuple, dict, str]], dict[str, int]]:
    """(ticker, leg) -> (bet key, match, game_date) through `join_kalshi_to_board`, per Kalshi date."""
    from syndicate.features.shared import kalshi_board_join as kbj

    by_day: dict[str, list[dict]] = collections.defaultdict(list)
    for row in board:
        c = ms.ts(row["commence_time"])
        if c is None:
            continue
        for off in (-1, 0, 1):
            by_day[dt.datetime.fromtimestamp(c + off * DAY, dt.timezone.utc).strftime("%Y-%m-%d")].append(row)
    legs: dict[tuple[str, str], tuple[tuple, dict, str]] = {}
    reasons: collections.Counter = collections.Counter()
    for date, markets in sorted(kal_by_date.items()):
        rows = by_day.get(date) or []
        if not rows or not markets:
            continue
        km = []
        for ticker, m in markets.items():
            valid = [p for p in (m.get("points") or [])
                     if ms.num(p.get("yes")) and ms.num(p.get("no")) and 0 < p["yes"] < 1 and 0 < p["no"] < 1]
            last = valid[-1] if valid else {}
            yes, no = last.get("yes"), last.get("no")
            km.append({"ticker": ticker, "title": m.get("raw_title"), "series": ticker.split("-")[0],
                       "event_ticker": m.get("event"), "yes_probability": yes, "no_probability": no,
                       "yes_american": ms.prob_to_american(yes), "no_american": ms.prob_to_american(no)})
        result = kbj.join_kalshi_to_board(km, rows, selected_date=date)
        for k, v in (result.get("reasons") or result.get("unmatched_reasons") or {}).items():
            if isinstance(v, int):
                reasons[k] += v
        for match in result.get("matches") or []:
            key = kbj._match_key(match)
            if key is None:
                continue
            legs.setdefault((str(match["ticker"]), str(match["kalshi_side"])), (key, dict(match), date))
    return legs, dict(reasons)


def canon_key(sport: str, row: tuple, cache: dict) -> tuple | None:
    """`kbj._row_key` for a quote row (memoised on its market spelling): the join's own bet identity."""
    from syndicate.features.shared import kalshi_board_join as kbj

    ev, _kind, market, segment, player, selection, line = row[:7]
    m = (market, segment)
    if m not in cache:
        probe = {"sport": sport, "market": m[0], "segment": m[1], "event_id": "x", "line": 0.0, "side": "s",
                 "player_name": None}
        k = kbj._row_key(probe)
        cache[m] = (k[1], k[5]) if k else None
    cm = cache[m]
    if cm is None:
        return None
    ok, line = kbj._key_line(line)
    if not ok:
        return None
    return (str(ev or ""), cm[0], kbj.normalize_person(player), line, str(selection or "").strip().lower(), cm[1])


def quote_book(sport: str, rows: Iterable[tuple], need: set) -> ms.QuoteBook:
    book, cache = ms.QuoteBook(), {}
    for r in rows:
        k = canon_key(sport, r, cache)
        if k is None or k not in need:
            continue
        t, p = ms.ts(r[9]), ms.american_to_prob(r[7])
        if t is not None and p is not None:
            book.add(k, r[8], t, p)
    book.finish()
    return book


# ------------------------------------------------------------------ fees
def series_fees(root: Path, series: Iterable[str], now: float, get: Callable) -> tuple[dict[str, dict], int]:
    path = ms.store_dir(root) / "series_fees.json"
    cache = ms.load_json(path, {})
    unread = 0
    changed = False
    for s in sorted(set(series)):
        row = cache.get(s)
        if row and now - (ms.ts(row.get("read_at")) or 0) < ms.FEE_CACHE_MAX_AGE_S:
            continue
        fresh = ms.read_series_fee(s, get)
        if fresh is None:
            unread += 1  # REPORTED, never defaulted: a series we cannot read is skipped this run
            continue
        cache[s] = dict(fresh, read_at=ms.iso(now))
        changed = True
    if changed:
        ms.save_json(path, cache)
    return cache, unread


# ------------------------------------------------------------------ one run
def run_once(root: Path, now: float, *, sports=ms.SPORTS, days_back: int = 2, get: Callable = ms.public_get_json,
             join: Callable = production_join, log: Callable = print) -> dict[str, Any]:
    started = time.time()
    today = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
    game_dates = date_range(today, days_back, 1)
    summary: dict[str, Any] = {"at": ms.iso(now), "rule_version": ms.RULE_VERSION, "sports": {}}
    files: dict[str, dict[str, Any]] = {}

    def orders_doc(date: str) -> dict[str, Any]:
        if date not in files:
            files[date] = ms.load_json(ms.orders_path(root, date), {"rule_version": ms.RULE_VERSION, "legs": {}})
        return files[date]

    for sport in sports:
        c: collections.Counter = collections.Counter()
        kal = venue_markets(root, sport, game_dates)
        c["venue_markets"] = sum(len(v) for v in kal.values())
        qdates = {d for g in game_dates for d in date_range(dt.date.fromisoformat(g), 1, 1)}
        events, board, c["quote_rows"] = board_from_quotes(sport, quote_rows(root, sport, qdates))
        legs, reasons = join(sport, kal, board)
        c["joined_legs"] = len(legs)
        scoped = {lk: v for lk, v in legs.items() if ms.cell_for(sport, v[0][1], v[0][5])}
        c["in_scope_legs"] = len(scoped)
        fees, c["fee_unread"] = series_fees(root, {lk[0].split("-")[0] for lk in scoped}, now, get)
        need = set()
        for key, _match, _date in scoped.values():
            need.add(key)
            need.update(ms.complements(key))
        book = quote_book(sport, quote_rows(root, sport, qdates), need)
        for (ticker, leg), (key, match, gdate) in sorted(scoped.items()):
            series = ticker.split("-")[0]
            fee = fees.get(series)
            if not fee:
                c["skipped_fee_unread"] += 1
                continue
            if fee.get("fee_type") != ms.QUADRATIC:
                c["skipped_not_quadratic"] += 1
                continue
            commence = ms.ts((events.get(key[0]) or {}).get("commence_time"))
            if commence is None:
                c["skipped_no_commence"] += 1
                continue
            c["quadratic_legs"] += 1
            doc = orders_doc(gdate)
            rid = f"{ticker}|{leg}"
            rec = doc["legs"].get(rid)
            if rec is None:
                rec = doc["legs"][rid] = {
                    "ticker": ticker, "leg": leg, "series": series, "sport": sport,
                    "cell": ms.cell_for(sport, key[1], key[5]), "event_id": key[0], "market": key[1],
                    "segment": key[5], "line": key[3], "board_side": key[4], "player": key[2],
                    "game_date": gdate, "fee_type": fee.get("fee_type"), "fee_multiplier": fee.get("fee_multiplier"),
                    "series_title": fee.get("title"), "first_seen_at": now, "commence_first_seen": commence,
                    "rule_version": ms.RULE_VERSION, "scanned_through": None, "instants_scanned": 0,
                    "order": None, "fill_a": {"scanned_through": None, "t": None}, "closed": None,
                    "settlement": None,
                }
                c["new_legs"] += 1
            rec["commence"] = commence
            if rec.get("closed"):
                continue
            points = ms.sorted_points((kal.get(gdate, {}).get(ticker) or {}).get("points"))

            def fair_at(t: float, _key=key) -> tuple[float | None, int]:
                return book.fair(_key, t)

            if rec.get("order") is None:
                # After commence this still scans (a catch-up run), but anything it places is flagged
                # `late_observed` and the evaluation excludes it: only a run BEFORE commence is forward.
                order, scanned, n = ms.scan_for_placement(points, leg, commence, fair_at,
                                                          after=rec.get("scanned_through"), now=now)
                rec["scanned_through"] = scanned
                rec["instants_scanned"] = rec.get("instants_scanned", 0) + n
                c["instants_scanned"] += n
                if order is not None:
                    order.update({"observed_at": now, "late_observed": now >= commence,
                                  "commence_at_placement": commence, "t_iso": ms.iso(order["t"])})
                    rec["order"] = order
                    c["new_orders"] += 1
                    log(f"[maker_shadow] PAPER ORDER {ticker} {leg} b={order['b']:.2f} fair={order['fair']:.3f} "
                        f"at {order['t_iso']} improved={order['improved']} cell={rec['cell']}", flush=True)
                continue
            order = rec["order"]
            fa = rec.setdefault("fill_a", {"scanned_through": None, "t": None})
            if fa.get("t") is None:
                t_fill, scanned = ms.fill_by_asks(points, leg, order["t"], order["b"], commence,
                                                  after=fa.get("scanned_through"))
                fa["scanned_through"] = scanned
                fa["t"] = t_fill
            if now < commence + ms.CLOSE_DELAY_S:
                continue
            prints = ms.read_trade_prints(ticker, order["t"], commence, get)
            if prints is None and now < commence + 3 * DAY:
                c["close_deferred_prints_unread"] += 1
                continue
            t_b = None if prints is None else ms.fill_by_prints(prints, leg, order["t"], order["b"],
                                                                bool(order.get("improved")), commence)
            fair_close, books_close = book.fair(key, commence)
            rec["closed"] = {
                "at": now, "commence_final": commence,
                "void_reason": "commence_revised" if order["t"] > commence - ms.WIN_END_S else None,
                "fair_close": fair_close, "books_close": books_close,
                "fill_a_t": fa.get("t"), "fill_b_t": t_b,
                "fill_b_status": "ok" if prints is not None else "fetch_failed",
                "n_prints": None if prints is None else len(prints),
                "fair_at_fill_a": book.fair(key, fa["t"])[0] if fa.get("t") else None,
                "fair_at_fill_b": book.fair(key, t_b)[0] if t_b else None,
            }
            c["closed"] += 1
        c["join_unmatched"] = sum(reasons.values())
        summary["sports"][sport] = dict(c)
        log(f"[maker_shadow] {sport} " + json.dumps(dict(c), sort_keys=True), flush=True)
        del board, book

    # ---------------------------------------------------------------- settlement (Kalshi `result`)
    reads = settled = 0
    cutoff = (today - dt.timedelta(days=ms.SETTLE_LOOKBACK_DAYS)).isoformat()
    for path in ms.iter_order_files(root):
        date = path.stem.replace("orders_", "")
        if date < cutoff:
            continue
        doc = orders_doc(date)
        for rec in doc["legs"].values():
            if not rec.get("closed") or (rec.get("settlement") or {}).get("result") in ("yes", "no"):
                continue
            if reads >= 500:
                break
            res = ms.read_market_result(rec["ticker"], get)
            reads += 1
            time.sleep(0.12)
            if res is None:
                continue
            final = res.get("result") in ("yes", "no") or str(res.get("status") or "") in ("finalized", "settled")
            if final:
                rec["settlement"] = dict(res, read_at=now)
                settled += 1
    summary["settlement"] = {"reads": reads, "settled": settled}

    for date, doc in files.items():
        doc["updated_at"] = ms.iso(now)
        ms.save_json(ms.orders_path(root, date), doc)
    summary["seconds"] = round(time.time() - started, 1)
    runs = ms.store_dir(root) / "runs.jsonl"
    runs.parent.mkdir(parents=True, exist_ok=True)
    with runs.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, sort_keys=True) + "\n")
    log(f"[maker_shadow] done {json.dumps({'settlement': summary['settlement'], 'seconds': summary['seconds']})}",
        flush=True)
    return summary


def _lock(root: Path):
    """One run at a time (the supervisor already serialises the job; this covers a manual run)."""
    try:
        import fcntl
    except ImportError:
        return True
    path = ms.store_dir(root) / ".run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return handle


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days-back", type=int, default=2, help="game dates before today to (re)visit")
    ap.add_argument("--sports", default=",".join(ms.SPORTS))
    args = ap.parse_args(argv)
    if hasattr(os, "nice"):
        try:
            os.nice(19)
        except OSError:
            pass
    root = data_root()
    handle = _lock(root)
    if handle is None:
        print("[maker_shadow] another run holds the lock; exiting", flush=True)
        return 0
    sports = tuple(s.strip() for s in args.sports.split(",") if s.strip() in ms.SPORTS)
    run_once(root, time.time(), sports=sports, days_back=args.days_back)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
