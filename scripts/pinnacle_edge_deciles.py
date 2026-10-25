"""Test B, step 1: settled ROI by decile of edge over Pinnacle at the decision instant, x Pinnacle quote age.

Lane `live-cell-scorecard`. USER DECISION 2026-10-24 (relayed by the coordinator 332cb014): "B: Edge-over-Pinnacle
deciles". Design: lane pm-trader-strategies, `.syndicate/findings_2026-10-24_pm_trader_strategies.md` (Whelan's
NBA CLV deciles: only the top decile pays). Read-only.

COVERAGE, MEASURED FIRST (2026-10-25 00:00Z, every October `book_quotes` shard on the fleet): Pinnacle is captured
for NCAAF (33,061 quotes / 18 dates), NHL (27,577 / 24) and MLB (13,164 / 19) ONLY -- 0 for NBA, NFL, soccer and
WNBA. So this tests those three sports and says nothing about the others.

DEFINITIONS
- Population: settled, filled orders priced AT A VENUE -- live kalshi/polymarket, paper:<venue> and
  paper:<venue>:ladder -- with an event_id, a side and a market, in a Pinnacle-captured sport. `book` is kept as a
  column, never silently pooled away.
- Pinnacle at the decision: per side, the LAST Pinnacle quote with `captured_at <= submitted_at` on our selection
  and line, and on the opposite selection at the opposite line (spreads) / same line (totals). No two-way quote at
  our line -> age bucket `absent`.
- Fair: multiplicative de-vig of that two-way quote. Cost: the contract price we paid plus the fee per contract
  (`fees_dollars / contracts`). EDGE = 100 * (fair - cost), in probability points, net of fee.
- Age: submit minus the OLDER side's `book_updated_at` (else `captured_at`) -- the fair is no fresher than its
  stalest leg. Buckets <=2 min / 2-15 min / >15 min / absent.
- Close edge: the same, with the last Pinnacle two-way quote before `commence_time` (CLV recomputed here: the
  ledger's live `closing_mark.clv_pct` is not used).
- ROI: flat, pnl/stake (pnl_dollars is net of fees). CI: game-clustered bootstrap 90%, seeded
  (`live_cell_gate.flat_ci`).

    # FLEET (WSL, fleet venv, refresh-worker state env, nice 19): join the Pinnacle quotes -> --out
    python scripts/pinnacle_edge_deciles.py quotes --ledger /mnt/c/tmp/lcs/ledger.json --out /mnt/c/tmp/lcs/pin_join.json
    # anywhere
    py -3 scripts/pinnacle_edge_deciles.py report --join C:/tmp/lcs/pin_join.json [--out-md PATH]
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.live_cell_gate import family_of, flat_ci, game_of, parse_ts  # noqa: E402

# Every sport: the consensus arm needs no Pinnacle; the Pinnacle arm reads None where Pinnacle is not captured.
SPORTS = ("ncaaf", "nhl", "mlb", "nba", "nfl", "soccer", "wnba", "ncaab")
OPPOSITE = {"home": "away", "away": "home", "over": "under", "under": "over"}
BOOKS = {"kalshi": "live", "polymarket": "live", "paper:kalshi": "paper", "paper:polymarket": "paper",
         "paper:kalshi:ladder": "ladder", "paper:polymarket:ladder": "ladder"}
AGE_BUCKETS = ((120, "<=2m"), (900, "2-15m"), (float("inf"), ">15m"))


def contract_price(price: Any) -> float | None:
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if 0 < p < 1:
        return p
    if p >= 100:
        return 100.0 / (p + 100.0)
    if p <= -100:
        return -p / (-p + 100.0)
    return None


def implied(american: Any) -> float | None:
    return contract_price(american) if american is not None and abs(float(american)) >= 100 else None


def devig(p_us: float, p_them: float) -> float:
    return p_us / (p_us + p_them)


def eligible(order: Mapping[str, Any]) -> bool:
    return (str(order.get("venue")) in BOOKS and str(order.get("sport") or "").lower() in SPORTS
            and order.get("status") == "filled" and order.get("outcome") in ("won", "lost")
            and bool(order.get("event_id")) and str(order.get("side") or "").lower() in OPPOSITE
            and bool(order.get("market")) and float(order.get("fill_stake_dollars") or 0) > 0
            # soccer h2h is THREE-way (draw): a two-way de-vig of home vs away would be wrong
            and not (str(order.get("sport") or "").lower() == "soccer" and "h2h" in str(order.get("market") or "").lower()))


def _line(value: Any) -> float | None:
    return None if value is None else round(float(value), 3)


def quote_key(event_id: Any, market: Any, segment: Any, player: Any) -> tuple:
    return (str(event_id), str(market or "").lower(), str(segment or "full").lower() or "full",
            str(player or "").strip().casefold())


SELF_VENUES = frozenset({"kalshi", "polymarket"})   # never in the consensus: they are what we trade against


def _book_two_way(series: list, at: datetime, book: str, ours: tuple, theirs: tuple) -> dict[str, Any] | None:
    """One book's last quote <= at on each side of OUR line, de-vigged; `fresh` = still its latest capture."""
    last: dict[str, tuple] = {}
    latest = None
    for captured, updated, bk, selection, line, price in series:
        if captured is None or captured > at:
            break
        if bk != book:
            continue
        latest = captured
        if (selection, line) == ours:
            last["us"] = (price, updated or captured, captured)
        elif (selection, line) == theirs:
            last["them"] = (price, updated or captured, captured)
    if "us" not in last or "them" not in last:
        return None
    p_us, p_them = implied(last["us"][0]), implied(last["them"][0])
    if not p_us or not p_them:
        return None
    oldest = min(last["us"][1], last["them"][1])
    newest_capture = max(last["us"][2], last["them"][2])
    return {"fair": devig(p_us, p_them), "age_s": max(0.0, (at - oldest).total_seconds()),
            "fresh": latest is not None and (latest - newest_capture).total_seconds() <= 1.0}


def two_way(series: list, at: datetime, ours: tuple, theirs: tuple, book: str = "pinnacle") -> dict[str, Any] | None:
    """Pinnacle's (or `book`'s) two-way at OUR line as of `at`; None without both sides."""
    return _book_two_way(series, at, book, ours, theirs)


def consensus(series: list, at: datetime, ours: tuple, theirs: tuple) -> dict[str, Any] | None:
    """Median de-vigged fair over every non-venue book with a two-way at OUR line as of `at`."""
    books = sorted({row[2] for row in series if row[2] not in SELF_VENUES})
    reads = [r for r in (_book_two_way(series, at, bk, ours, theirs) for bk in books) if r is not None]
    if not reads:
        return None
    fairs = sorted(r["fair"] for r in reads)
    mid = len(fairs) // 2
    median = fairs[mid] if len(fairs) % 2 else (fairs[mid - 1] + fairs[mid]) / 2
    return {"fair": median, "books": len(reads), "fresh_books": sum(r["fresh"] for r in reads),
            "age_s": max(r["age_s"] for r in reads)}


def join_order(order: Mapping[str, Any], quotes: Mapping[tuple, list]) -> dict[str, Any]:
    """One order's Pinnacle and consensus readings at submit and at kickoff. Pure."""
    market = str(order.get("market") or "").lower()
    line = _line(order.get("line"))
    side = str(order["side"]).lower()
    opposite_line = (-line if line is not None else None) if "spread" in market else line
    key = quote_key(order.get("event_id"), market, order.get("segment"), order.get("player_name"))
    series = quotes.get(key) or []
    sub, ko = parse_ts(order.get("submitted_at")), parse_ts(order.get("commence_time"))
    ours, theirs = (side, line), (OPPOSITE[side], opposite_line)
    return {"at_submit": two_way(series, sub, ours, theirs) if sub else None,
            "at_close": two_way(series, ko, ours, theirs) if ko else None,
            "cons_submit": consensus(series, sub, ours, theirs) if sub else None,
            "cons_close": consensus(series, ko, ours, theirs) if ko else None}


def load_quotes(orders: Iterable[Mapping[str, Any]]) -> dict[tuple, list]:
    """Fleet: stream the book_quotes shards of the wanted events; keep every book, only the wanted keys."""
    from syndicate.features.shared.odds_book_quotes import kickoff_shard_date, resolve_book_quotes_path

    want: dict[tuple, set] = defaultdict(set)
    keys: set = set()
    for o in orders:
        ko = parse_ts(o.get("commence_time"))
        days = {kickoff_shard_date({"commence_time": o.get("commence_time")}), ko.date().isoformat() if ko else None}
        for day in days - {None}:
            want[(str(o["sport"]).lower(), day)].add(str(o["event_id"]))
        keys.add(quote_key(o.get("event_id"), o.get("market"), o.get("segment"), o.get("player_name")))
    event_re = re.compile(r'"event_id"\s*:\s*"([^"]*)"')
    quotes: dict[tuple, list] = defaultdict(list)
    for (sport, day), events in sorted(want.items()):
        path = resolve_book_quotes_path(sport, day)
        if not path.is_file():
            continue
        opener = gzip.open if str(path).endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                m = event_re.search(raw)
                if not m or m.group(1) not in events:
                    continue
                try:
                    q = json.loads(raw)
                except ValueError:
                    continue
                key = quote_key(q.get("event_id"), q.get("market"), q.get("segment"), q.get("player_name"))
                if key not in keys:
                    continue
                quotes[key].append((parse_ts(q.get("captured_at")), parse_ts(q.get("book_updated_at")),
                                    str(q.get("bookmaker") or "").lower(), str(q.get("selection") or "").lower(),
                                    _line(q.get("line")), q.get("price")))
    for series in quotes.values():
        series.sort(key=lambda item: item[0] or datetime.min.replace(tzinfo=timezone.utc))
    return quotes


def _fresh_bucket(n: int | None) -> str:
    return "none" if not n else ("1-2" if n <= 2 else "3+")


def _age_bucket(age_s: float | None) -> str:
    return "absent" if age_s is None else next(name for limit, name in AGE_BUCKETS if age_s <= limit)


def order_row(order: Mapping[str, Any], joined: Mapping[str, Any]) -> dict[str, Any]:
    stake = float(order["fill_stake_dollars"])
    price = contract_price(order.get("fill_price") if order.get("fill_price") not in (None, 0) else order.get("venue_avg_price"))
    contracts = stake / price if price else None
    fee_per = float(order.get("fees_dollars") or 0.0) / contracts if contracts else 0.0
    cost = (price + fee_per) if price else None
    sub, close = joined.get("at_submit"), joined.get("at_close")
    cons, cons_close = joined.get("cons_submit"), joined.get("cons_close")
    return {"book": BOOKS[str(order["venue"])], "venue": "kalshi" if "kalshi" in str(order["venue"]) else "polymarket",
            "sport": str(order["sport"]).lower(), "family": family_of(order), "game": game_of(order),
            "date": str(order.get("selected_date")), "stake": stake, "pnl": float(order["pnl_dollars"]),
            "ret": float(order["pnl_dollars"]) / stake, "cost": cost,
            "edge": 100 * (sub["fair"] - cost) if sub and cost else None,
            "close_edge": 100 * (close["fair"] - cost) if close and cost else None,
            "age": _age_bucket(sub["age_s"] if sub else None), "age_s": None if not sub else round(sub["age_s"], 1),
            "cons_edge": 100 * (cons["fair"] - cost) if cons and cost else None,
            "cons_close_edge": 100 * (cons_close["fair"] - cost) if cons_close and cost else None,
            "cons_books": cons["books"] if cons else 0, "cons_fresh": _fresh_bucket(cons["fresh_books"] if cons else 0),
            "cons_age": _age_bucket(cons["age_s"] if cons else None)}


def deciles(rows: list[dict]) -> list[float]:
    edges = sorted(r["edge"] for r in rows if r["edge"] is not None)
    if len(edges) < 10:
        return []
    return [edges[int(len(edges) * k / 10)] for k in range(1, 10)]


def decile_of(edge: float | None, cuts: list[float]) -> str:
    if edge is None or not cuts:
        return "none"
    return f"D{1 + sum(edge >= c for c in cuts):02d}"


def summarise(rows: list[dict]) -> dict[str, Any]:
    n = len(rows)
    ci = flat_ci([{"game": r["game"], "ret": r["ret"]} for r in rows], 0.90) if n else None
    edges = [r["edge"] for r in rows if r["edge"] is not None]
    closes = [r["close_edge"] for r in rows if r["close_edge"] is not None]
    return {"n": n, "games": len({r["game"] for r in rows}), "staked": round(sum(r["stake"] for r in rows), 2),
            "pnl": round(sum(r["pnl"] for r in rows), 2),
            "roi_flat": round(100 * sum(r["ret"] for r in rows) / n, 1) if n else None,
            "ci90": None if not ci else [round(100 * ci[0], 1), round(100 * ci[1], 1)],
            "edge_mean_pp": round(sum(edges) / len(edges), 2) if edges else None,
            "close_edge_mean_pp": round(sum(closes) / len(closes), 2) if closes else None, "close_n": len(closes)}


def consensus_view(rows: list[dict]) -> list[dict]:
    """The same orders seen through the CONSENSUS arm: its edge, close edge and age, plus its fresh-book count."""
    return [{**r, "edge": r.get("cons_edge"), "close_edge": r.get("cons_close_edge"), "age": r.get("cons_age", "absent"),
             "fresh": r.get("cons_fresh", "none")} for r in rows]


def build_report(rows: list[dict], *, arm: str = "pinnacle") -> dict[str, Any]:
    cuts = deciles(rows)
    for r in rows:
        r["decile"] = decile_of(r["edge"], cuts)
    sections = [("coverage", lambda r: f"{r['sport']}|{r['book']}|{'joined' if r['edge'] is not None else 'absent'}"),
                ("by_decile", lambda r: r["decile"]), ("by_age", lambda r: r["age"]),
                ("by_decile_age", lambda r: f"{r['decile']}|{r['age']}"),
                ("by_book_decile", lambda r: f"{r['book']}|{r['decile']}"),
                ("by_sport_decile", lambda r: f"{r['sport']}|{r['decile']}")]
    if arm == "consensus":
        sections += [("by_fresh", lambda r: r["fresh"]), ("by_decile_fresh", lambda r: f"{r['decile']}|{r['fresh']}")]
    out: dict[str, Any] = {"arm": arm, "n": len(rows), "decile_cuts_pp": [round(c, 2) for c in cuts]}
    for key, fn in sections:
        groups: dict[str, list] = defaultdict(list)
        for r in rows:
            groups[fn(r)].append(r)
        out[key] = {k: summarise(v) for k, v in sorted(groups.items())}
    return out


def markdown(report: Mapping[str, Any]) -> str:
    lines = [f"# Test B step 1 -- arm {report['arm']}: edge deciles (n {report['n']})", "",
             f"decile cuts (pp, net of fee): {report['decile_cuts_pp']}", ""]
    for section in [k for k in report if k.startswith(("coverage", "by_"))]:
        lines += [f"## {section}", "", "| key | n | games | staked | pnl | ROI flat | CI90 | edge pp | close edge pp (n) |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for k, s in report[section].items():
            lines.append(f"| {k} | {s['n']} | {s['games']} | {s['staked']} | {s['pnl']:+} | {s['roi_flat']}% | {s['ci90']} |"
                         f" {s['edge_mean_pp']} | {s['close_edge_mean_pp']} ({s['close_n']}) |")
        lines.append("")
    return "\n".join(lines)


def cmd_quotes(args) -> int:
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass
    raw = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    orders = [o for o in (raw.get("orders", []) if isinstance(raw, Mapping) else raw) if eligible(o)]
    quotes = load_quotes(orders)
    rows = [order_row(o, join_order(o, quotes)) for o in orders]
    Path(args.out).write_text(json.dumps(rows), encoding="utf-8")
    print(f"PINNACLE_JOIN orders={len(orders)} pinnacle_series={len(quotes)} "
          f"pinnacle_at_submit={sum(r['edge'] is not None for r in rows)} "
          f"consensus_at_submit={sum(r['cons_edge'] is not None for r in rows)} -> {args.out}", flush=True)
    return 0


def cmd_report(args) -> int:
    rows = json.loads(Path(args.join).read_text(encoding="utf-8"))
    md = markdown(build_report([dict(r) for r in rows], arm="pinnacle")) + "\n\n" + markdown(
        build_report(consensus_view(rows), arm="consensus"))
    if args.out_md:
        Path(args.out_md).write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("quotes")
    q.add_argument("--ledger", required=True)
    q.add_argument("--out", required=True)
    r = sub.add_parser("report")
    r.add_argument("--join", required=True)
    r.add_argument("--out-md", default=None)
    args = parser.parse_args(argv)
    return cmd_quotes(args) if args.cmd == "quotes" else cmd_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
