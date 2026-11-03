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
    # the PRE-REGISTERED forward test (findings_2026-10-25_test_b_preregistration.md): arms P1/P2/C1/C2 since REG
    py -3 scripts/pinnacle_edge_deciles.py testb --join C:/tmp/lcs/pin_join.json [--as-of ISO] [--out-md PATH]
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
            "cons_age": _age_bucket(cons["age_s"] if cons else None),
            "submitted": order.get("submitted_at")}


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


# ---------------------------------------------------------------------------
# CAPTURE AGE: the prereg's secondary split (P1 by capture age <= 2 min / > 2 min).
# ---------------------------------------------------------------------------
# "Pinnacle age" above is time since Pinnacle's price last CHANGED (book_quotes dedupes unchanged prices). How stale
# OUR copy was is the gap since our last fetch that SAW Pinnacle on this event: the F0 fetch heartbeat
# (`odds_book_quotes.read_fetch_heartbeats`, one line per fetch, live from ~18:36Z 2026-10-25). Orders submitted
# before the first heartbeat of their sport read `unknown`, never "fresh" or "stale".

CAPTURE_SPLIT_S = 120.0


def capture_age(order: Mapping[str, Any], heartbeats: Iterable[Mapping[str, Any]], *,
                key: str = "pinnacle_events") -> float | None:
    """Seconds from the last heartbeat <= submit whose `key` lists the order's event, to submit. None if none."""
    sub, event = parse_ts(order.get("submitted_at")), str(order.get("event_id") or "")
    if sub is None or not event:
        return None
    best = None
    for beat in heartbeats:
        at = parse_ts(beat.get("captured_at"))
        if at is None or at > sub or event not in (beat.get(key) or ()):
            continue
        if best is None or at > best:
            best = at
    return None if best is None else round((sub - best).total_seconds(), 1)


def capture_bucket(age_s: float | None) -> str:
    return "unknown" if age_s is None else ("<=2m" if age_s <= CAPTURE_SPLIT_S else ">2m")


def heartbeat_dates(order: Mapping[str, Any]) -> set[str]:
    """Heartbeats are keyed by the SHARD date: kickoff (Central) for most writers, the capture UTC date for NFL game
    lines. So read the kickoff Central/UTC dates and the submit UTC date."""
    from syndicate.features.shared.odds_book_quotes import kickoff_shard_date

    ko, sub = parse_ts(order.get("commence_time")), parse_ts(order.get("submitted_at"))
    days = {kickoff_shard_date({"commence_time": order.get("commence_time")}),
            ko.date().isoformat() if ko else None, sub.date().isoformat() if sub else None}
    return {d for d in days if d}


def load_heartbeats(orders: Iterable[Mapping[str, Any]]) -> dict[tuple, list]:
    """Fleet: (sport, date) -> heartbeat lines, for every date any order can need."""
    from syndicate.features.shared.odds_book_quotes import read_fetch_heartbeats

    out: dict[tuple, list] = {}
    for o in orders:
        sport = str(o.get("sport") or "").lower()
        for day in heartbeat_dates(o):
            if (sport, day) not in out:
                out[(sport, day)] = read_fetch_heartbeats(sport, day)
    return out


def order_capture(order: Mapping[str, Any], beats: Mapping[tuple, list]) -> dict[str, Any]:
    sport = str(order.get("sport") or "").lower()
    lines = [b for day in sorted(heartbeat_dates(order)) for b in beats.get((sport, day), [])]
    pin, any_book = capture_age(order, lines), capture_age(order, lines, key="events")
    return {"capture_age_s": pin, "capture": capture_bucket(pin), "event_capture_age_s": any_book,
            "heartbeat_lines": len(lines)}


# ---------------------------------------------------------------------------
# TEST B, FORWARD: the frozen arms and bar of findings_2026-10-25_test_b_preregistration.md
# ---------------------------------------------------------------------------

REG = "2026-10-25T15:38:15Z"     # the prereg file's commit time on origin/main (80ee76dd)
EDGE_MIN_PP = 0.4
BAR = {"bets": 150, "games": 40, "days": 14}
FUTILITY_CLOSE_PP = -0.5


def arm_summary(rows: list[dict], *, as_of: datetime) -> dict[str, Any]:
    n = len(rows)
    ci = flat_ci([{"game": r["game"], "ret": r["ret"]} for r in rows], 0.95) if n else None
    closes = [r["close_edge"] for r in rows if r.get("close_edge") is not None]
    close_mean = sum(closes) / len(closes) if closes else None
    games = len({r["game"] for r in rows})
    days = (as_of - parse_ts(REG)).total_seconds() / 86400.0
    sized = n >= BAR["bets"] and games >= BAR["games"] and days >= BAR["days"]
    lo, hi = (None, None) if not ci else (100 * ci[0], 100 * ci[1])
    return {"n": n, "games": games, "days_since_reg": round(days, 1),
            "staked": round(sum(r["stake"] for r in rows), 2), "pnl": round(sum(r["pnl"] for r in rows), 2),
            "roi_flat": round(100 * sum(r["ret"] for r in rows) / n, 1) if n else None,
            "ci95": None if ci is None else [round(lo, 1), round(hi, 1)],
            "close_edge_mean_pp": None if close_mean is None else round(close_mean, 2), "close_n": len(closes),
            "bar_sized": sized,
            "pass": bool(sized and lo is not None and lo > 0 and close_mean is not None and close_mean > 0),
            "futility": bool(n >= BAR["bets"] and ((hi is not None and hi < 0)
                                                  or (close_mean is not None and close_mean < FUTILITY_CLOSE_PP))),
            "confirmed_negative": bool(n >= BAR["bets"] and games >= BAR["games"] and hi is not None and hi < 0)}


def testb_report(rows: list[dict], *, as_of: datetime) -> dict[str, Any]:
    reg = parse_ts(REG)
    # A look counts orders submitted in [REG, as_of): a later order is the NEXT look's, even if it settled already.
    since = [r for r in rows if parse_ts(r.get("submitted")) is not None and reg <= parse_ts(r["submitted"]) < as_of]
    p1 = [r for r in since if r.get("edge") is not None and r["edge"] >= EDGE_MIN_PP]
    p2 = [r for r in since if r.get("edge") is not None and r["edge"] < 0]
    c1 = [r for r in since if r.get("cons_edge") is not None and r["cons_edge"] >= EDGE_MIN_PP]
    p1_ids = {id(r) for r in p1}
    c1_only = [r for r in c1 if id(r) not in p1_ids]
    c1_view = [{**r, "close_edge": r.get("cons_close_edge")} for r in c1]
    arms = {"population": arm_summary(since, as_of=as_of), "P1": arm_summary(p1, as_of=as_of),
            "P2": arm_summary(p2, as_of=as_of), "C1": arm_summary(c1_view, as_of=as_of),
            "C1_only": arm_summary([{**r, "close_edge": r.get("cons_close_edge")} for r in c1_only], as_of=as_of)}
    for name, s in arms.items():       # the prereg defines futility for P1 only and confirmation for P2 only
        s["futility"] = s["futility"] if name == "P1" else None
        s["confirmed_negative"] = s["confirmed_negative"] if name == "P2" else None
    a, b = arms["P1"]["roi_flat"], arms["C1_only"]["roi_flat"]
    arms["C2_diff_pp"] = None if a is None or b is None else round(a - b, 1)
    split: dict[str, Any] = {}
    for bucket in ("<=2m", ">2m", "unknown"):
        part = [r for r in p1 if r.get("capture", "unknown") == bucket]
        split[bucket] = arm_summary(part, as_of=as_of)
    coverage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in since:
        c = coverage[f"{r['sport']}|{r['book']}"]
        c["n"] += 1
        c["pinnacle"] += r.get("edge") is not None
        c["consensus"] += r.get("cons_edge") is not None
        c["capture_known"] += r.get("capture", "unknown") != "unknown"
    return {"reg": REG, "as_of": as_of.isoformat(timespec="seconds"), "orders_since_reg": len(since),
            "arms": arms, "p1_by_capture": split,
            "coverage": {k: dict(v) for k, v in sorted(coverage.items())}}


def testb_markdown(rep: Mapping[str, Any]) -> str:
    lines = [f"# Test B forward look -- as of {rep['as_of']} (REG {rep['reg']}, {rep['orders_since_reg']} settled orders)",
             "", "| arm | n | games | staked | pnl | ROI flat | CI95 | close edge pp (n) | bar sized | P1 PASS | P1 futility | P2 confirmed |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, s in rep["arms"].items():
        if not isinstance(s, Mapping):
            continue
        lines.append(f"| {name} | {s['n']} | {s['games']} | {s['staked']} | {s['pnl']:+} | {s['roi_flat']}% | {s['ci95']} |"
                     f" {s['close_edge_mean_pp']} ({s['close_n']}) | {s['bar_sized']} | {s['pass'] if name == 'P1' else ''} |"
                     f" {'' if s['futility'] is None else s['futility']} |"
                     f" {'' if s['confirmed_negative'] is None else s['confirmed_negative']} |")
    lines += ["", f"C2 (P1 ROI minus C1-only ROI): {rep['arms']['C2_diff_pp']} pp", "",
              "## P1 by capture age (secondary, not a pass criterion)", "",
              "| capture | n | games | pnl | ROI flat | CI95 |", "|---|---|---|---|---|---|"]
    for name, s in rep["p1_by_capture"].items():
        lines.append(f"| {name} | {s['n']} | {s['games']} | {s['pnl']:+} | {s['roi_flat']}% | {s['ci95']} |")
    lines += ["", "## Coverage (orders since REG)", "", "| sport/book | n | pinnacle | consensus | capture known |",
              "|---|---|---|---|---|"]
    for k, c in rep["coverage"].items():
        lines.append(f"| {k} | {c.get('n', 0)} | {c.get('pinnacle', 0)} | {c.get('consensus', 0)} | {c.get('capture_known', 0)} |")
    return "\n".join(lines)


def cmd_testb(args) -> int:
    rows = json.loads(Path(args.join).read_text(encoding="utf-8"))
    as_of = parse_ts(args.as_of) if args.as_of else datetime.now(timezone.utc)
    rep = testb_report(rows, as_of=as_of)
    md = testb_markdown(rep)
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md + "\n")
    return 0


def cmd_quotes(args) -> int:
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass
    raw = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    orders = [o for o in (raw.get("orders", []) if isinstance(raw, Mapping) else raw) if eligible(o)]
    quotes = load_quotes(orders)
    beats = load_heartbeats(orders)
    rows = [{**order_row(o, join_order(o, quotes)), **order_capture(o, beats)} for o in orders]
    Path(args.out).write_text(json.dumps(rows), encoding="utf-8")
    print(f"PINNACLE_JOIN orders={len(orders)} pinnacle_series={len(quotes)} "
          f"pinnacle_at_submit={sum(r['edge'] is not None for r in rows)} "
          f"consensus_at_submit={sum(r['cons_edge'] is not None for r in rows)} "
          f"capture_known={sum(r['capture'] != 'unknown' for r in rows)} -> {args.out}", flush=True)
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
    t = sub.add_parser("testb")
    t.add_argument("--join", required=True)
    t.add_argument("--as-of", default=None)
    t.add_argument("--out-md", default=None)
    t.add_argument("--out-json", default=None)
    args = parser.parse_args(argv)
    return {"quotes": cmd_quotes, "report": cmd_report, "testb": cmd_testb}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
