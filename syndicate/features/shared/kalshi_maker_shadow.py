"""PAPER-ONLY Kalshi maker (resting-bid) shadow. It never places an order.

Pre-registration: `.syndicate/findings_2026-10-20_kalshi_maker_shadow_preregistration.md` (on main at
023f3978, committed before this module existed). The rule is the one the 10-19 study measured
(`findings_2026-10-19_kalshi_maker_entry_paper.md`), scoped to the two cells whose fills were NOT
adversely selected there -- soccer totals/spreads and NCAAF quarter/half totals on `quadratic` series --
and graded on SETTLED OUTCOMES, because that study showed CLV against the close is blind for maker fills
(passing at +3.75% while filled orders won 5.37pp below the close).

NO ORDER PATH, BY CONSTRUCTION. This module imports nothing that can sign, submit or size an order, and
its only network calls are unauthenticated GETs to Kalshi's public market-data endpoints, made through
`public_get_json` below. `tests/test_kalshi_maker_shadow.py` parses this file and both scripts and fails
on any other import or HTTP verb. There is deliberately no flag that changes this.

Worker-owned: `scripts/run_kalshi_maker_shadow.py` runs hourly as a fleet supervisor job and
`scripts/evaluate_kalshi_maker_shadow.py` daily. Nothing on the request path reads the store.
"""
from __future__ import annotations

import bisect
import collections
import datetime as dt
import json
import math
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

RULE_VERSION = "maker-shadow-v1"
WIN_START_S = 24 * 3600  # decision window opens at commence - 24h
WIN_END_S = 10 * 60  # ... and closes at commence - 10 min
CLOSE_DELAY_S = 15 * 60  # an order is closed (fills read, close fair taken) this long after commence
EDGE_FLOOR = 0.02  # b <= floor_cent(fair / 1.02)
MIN_BID, MAX_BID = 0.03, 0.97
MIN_BOOKS = 2
SPORTS = ("soccer", "ncaaf")
QUADRATIC = "quadratic"
STORE_SUBDIR = ("reports", "intelligence", "kalshi_maker_shadow")
KALSHI_PUBLIC = "https://api.elections.kalshi.com/trade-api/v2"
FEE_CACHE_MAX_AGE_S = 7 * 86400
SETTLE_LOOKBACK_DAYS = 21
EXCHANGES = frozenset({
    "kalshi", "polymarket", "prophetx", "novig", "smarkets", "matchbook", "betfair", "betfair_ex_us",
    "betfair_ex_uk", "betfair_ex_eu", "betfair_ex_au", "betfair_sb_uk", "polymarket_us", "kalshi_us",
    "sporttrade", "rebet", "fliff",
})
# Board rows the join is fed: the game lines only. Props are most of the quote log (60k of 90k NCAAF rows
# in a week) and can never pair to an in-scope series.
BOARD_MARKETS = frozenset({"h2h", "totals", "spreads"})

# ------------------------------------------------------------------ evaluation constants (pre-registered)
CELLS = ("soccer:totals", "soccer:spreads", "ncaaf:segment_totals")
LOOKS = (200, 400, 600)
LOOK_CI = {200: 0.99, 400: 0.99, 600: 0.95}
FUTILITY_CI = 0.95
FINAL_CI = 0.95
GO_WIN_LB = -0.01
MIN_EVENTS = 50
CALENDAR_STOP = "2027-01-31"
BOOT_DRAWS = 2000
BOOT_SEED = 20261020
MISPAIR_GAP = 0.10
MISPAIR_MIN_ORDERS = 5
WOMEN_TITLE_RE = re.compile(r"women|femminile|frauen|f[eé]minine?|\(w\)", re.IGNORECASE)


# ------------------------------------------------------------------ small helpers
def ts(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()


def iso(value: float | None) -> str | None:
    if value is None:
        return None
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def floor_cent(value: float) -> float:
    return math.floor(value * 100 + 1e-9) / 100.0


def american_to_prob(price: Any) -> float | None:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value == 0 or value != value:
        return None
    return 100.0 / (value + 100.0) if value > 0 else (-value) / (-value + 100.0)


def prob_to_american(p: Any) -> int | None:
    if not num(p) or not 0 < p < 1:
        return None
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def cell_for(sport: str, market: Any, segment: Any) -> str | None:
    """The pre-registered cell of a joined leg, or None when out of scope."""
    market = str(market or "").strip().lower()
    segment = str(segment or "full").strip().lower() or "full"
    if sport == "soccer" and market in ("totals", "spreads"):
        return f"soccer:{market}"
    if sport == "ncaaf" and market == "totals" and segment != "full":
        return "ncaaf:segment_totals"
    return None


# ------------------------------------------------------------------ the rule
def maker_bid(fair: float | None, ask: Any, bid: Any) -> tuple[float, bool] | None:
    """`b = min(best_bid + 0.01, floor_cent(fair / 1.02), ask - 0.01)`, placed iff 0.03 <= b <= 0.97.

    Returns `(b, improved)`, where `improved` says b sits above the best bid (we set the new best bid)
    rather than joining a queue at it -- fill model B treats the two differently.
    """
    if not num(fair) or not 0 < fair < 1:
        return None
    ask_v = ask if num(ask) and 0 < ask < 1 else None
    bid_v = bid if num(bid) and bid > 0 else 0.0
    candidates = [floor_cent(fair / (1 + EDGE_FLOOR)), round(bid_v + 0.01, 2)]
    if ask_v is not None:
        candidates.append(round(ask_v - 0.01, 2))
    b = round(min(candidates), 2)
    if not MIN_BID - 1e-9 <= b <= MAX_BID + 1e-9:
        return None
    if fair / b - 1 < EDGE_FLOOR - 1e-12:  # unreachable while b <= floor(fair/1.02); kept as the stated gate
        return None
    return b, b > bid_v + 1e-9


def leg_fields(leg: str) -> tuple[str, str]:
    return ("yes", "yes_bid") if leg == "yes" else ("no", "no_bid")


def sorted_points(points: Iterable[Mapping[str, Any]]) -> list[tuple[float, Mapping[str, Any]]]:
    out = [(ts(p.get("ts")), p) for p in points or [] if isinstance(p, Mapping)]
    return sorted(((t, p) for t, p in out if t is not None), key=lambda item: item[0])


def scan_for_placement(
    points: Sequence[tuple[float, Mapping[str, Any]]],
    leg: str,
    commence: float,
    fair_at: Callable[[float], tuple[float | None, int]],
    *,
    after: float | None,
    now: float,
) -> tuple[dict[str, Any] | None, float | None, int]:
    """Evaluate the gate at each recorded point NEWER than `after`, in order; the first pass is the order.

    Only points inside [commence - 24h, commence - 10 min] and at or before `now` are decision instants.
    Returns (order or None, the newest instant scanned, how many instants were scanned).
    """
    ask_f, bid_f = leg_fields(leg)
    lo, hi = commence - WIN_START_S, commence - WIN_END_S
    scanned_through, n = after, 0
    for t, p in points:
        if after is not None and t <= after:
            continue
        if t < lo or t > hi or t > now:
            continue
        n += 1
        scanned_through = t
        fair, books = fair_at(t)
        placed = maker_bid(fair, p.get(ask_f), p.get(bid_f))
        if placed is None:
            continue
        b, improved = placed
        ask, bid = p.get(ask_f), p.get(bid_f)
        mid = (ask + bid) / 2 if num(ask) and num(bid) and 0 < ask < 1 and bid > 0 else None
        return ({"t": t, "b": b, "improved": improved, "ask": ask if num(ask) else None,
                 "bid": bid if num(bid) else None, "kalshi_mid": mid, "fair": fair, "books": books},
                scanned_through, n)
    return None, scanned_through, n


def fill_by_asks(
    points: Sequence[tuple[float, Mapping[str, Any]]], leg: str, order_t: float, b: float, commence: float,
    *, after: float | None,
) -> tuple[float | None, float | None]:
    """Model A: the first recorded point after placement and before commence whose ask on our leg is <= b.

    Incremental (`after`): the 48-point cap drops old points, so each run scans what is new.
    Returns (fill instant or None, newest point scanned).
    """
    ask_f, _ = leg_fields(leg)
    scanned = after
    for t, p in points:
        if t <= order_t or t >= commence or (after is not None and t <= after):
            continue
        scanned = t
        ask = p.get(ask_f)
        if num(ask) and 0 < ask <= b + 1e-9:
            return t, scanned
    return None, scanned


def fill_by_prints(
    prints: Sequence[Mapping[str, Any]], leg: str, order_t: float, b: float, improved: bool, commence: float,
) -> float | None:
    """Model B (PRIMARY): the first venue trade print after placement and before commence in which a taker
    SOLD our leg at <= b; strictly < b when we joined the queue rather than improving the bid."""
    for tr in sorted(prints, key=lambda r: r.get("t") or 0.0):
        t = tr.get("t")
        if not num(t) or t <= order_t or t >= commence:
            continue
        if leg == "yes":
            ok, px = tr.get("taker_side") == "no", tr.get("yes")
        else:
            ok, px = tr.get("taker_side") == "yes", tr.get("no")
        if not ok or not num(px):
            continue
        if (improved and px <= b + 1e-9) or (not improved and px < b - 1e-9):
            return float(t)
    return None


# ------------------------------------------------------------------ consensus fair
def complements(key: tuple, three_way: bool = False) -> list[tuple]:
    """The other outcome(s) of the same bet, for de-vig. Key: (event, market, player, line, side, segment)."""
    ev, mkt, pl, line, side, seg = key
    if side in ("over", "under"):
        return [(ev, mkt, pl, line, "under" if side == "over" else "over", seg)]
    if side in ("yes", "no"):
        return [(ev, mkt, pl, line, "no" if side == "yes" else "yes", seg)]
    if side in ("home", "away", "draw"):
        if line not in (None, 0.0):
            return [(ev, mkt, pl, -line, "away" if side == "home" else "home", seg)]
        outs = ["home", "away"] + (["draw"] if three_way else [])
        return [(ev, mkt, pl, line, o, seg) for o in outs if o != side]
    return []


class QuoteBook:
    """Per bet key, per sportsbook, the (captured_at, implied p) history -- last value carried forward."""

    def __init__(self) -> None:
        self.series: dict[tuple, dict[str, list[tuple[float, float]]]] = collections.defaultdict(
            lambda: collections.defaultdict(list))

    def add(self, key: tuple, book: str, t: float, p: float) -> None:
        self.series[key][book].append((t, p))

    def finish(self) -> None:
        for books in self.series.values():
            for arr in books.values():
                arr.sort()

    def fair(self, key: tuple, t: float, three_way: bool = False) -> tuple[float | None, int]:
        outs = [key] + complements(key, three_way)
        if len(outs) < 2:
            return None, 0
        books = set(self.series.get(key, {}).keys())
        for other in outs[1:]:
            books &= set(self.series.get(other, {}).keys())
        vals = []
        for book in books:
            ps = []
            for o in outs:
                arr = self.series[o][book]
                i = bisect.bisect_right(arr, (t, 2.0)) - 1
                if i < 0:
                    break
                ps.append(arr[i][1])
            if len(ps) != len(outs):
                continue
            total = sum(ps)
            if total > 0:
                vals.append(ps[0] / total)
        if len(vals) < MIN_BOOKS:
            return None, len(vals)
        return sum(vals) / len(vals), len(vals)


# ------------------------------------------------------------------ public market-data GETs (no auth)
def public_get_json(path: str, params: Mapping[str, Any] | None = None, *, timeout: float = 30.0,
                    attempts: int = 4) -> dict[str, Any] | None:
    """GET one PUBLIC Kalshi market-data endpoint. Unauthenticated, read-only; None when unreadable."""
    url = KALSHI_PUBLIC + path + ("?" + urllib.parse.urlencode(params) if params else "")
    request = urllib.request.Request(url, method="GET",
                                     headers={"Accept": "application/json", "User-Agent": "syndicate-maker-shadow"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            time.sleep(min(2 ** attempt, 8))
        except (urllib.error.URLError, ValueError, OSError):
            time.sleep(min(2 ** attempt, 8))
    return None


def read_series_fee(series: str, get: Callable = public_get_json) -> dict[str, Any] | None:
    doc = get(f"/series/{urllib.parse.quote(series)}")
    row = (doc or {}).get("series") if isinstance((doc or {}).get("series"), dict) else None
    if not row or not row.get("fee_type"):
        return None
    return {"fee_type": row.get("fee_type"), "fee_multiplier": row.get("fee_multiplier"),
            "title": row.get("title")}


def _price(trade: Mapping[str, Any], side: str) -> float | None:
    dollars = trade.get(f"{side}_price_dollars")
    if dollars not in (None, ""):
        try:
            return float(dollars)
        except (TypeError, ValueError):
            return None
    cents = trade.get(f"{side}_price")
    return cents / 100.0 if num(cents) else None


def read_trade_prints(ticker: str, lo: float, hi: float, get: Callable = public_get_json,
                      pause: float = 0.12) -> list[dict[str, Any]] | None:
    """Every public trade print on `ticker` in [lo, hi]; None if any page could not be read."""
    prints, cursor = [], None
    for _ in range(60):
        params = {"ticker": ticker, "min_ts": int(lo) - 1, "max_ts": int(hi) + 1, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        doc = get("/markets/trades", params)
        if doc is None:
            return None
        for tr in doc.get("trades") or []:
            t = ts(tr.get("created_time"))
            if t is None:
                continue
            prints.append({"t": t, "taker_side": tr.get("taker_side"), "yes": _price(tr, "yes"),
                           "no": _price(tr, "no"), "count": tr.get("count_fp", tr.get("count"))})
        cursor = doc.get("cursor")
        if pause:
            time.sleep(pause)
        if not cursor or not doc.get("trades"):
            break
    prints.sort(key=lambda r: r["t"])
    return prints


def read_market_result(ticker: str, get: Callable = public_get_json) -> dict[str, Any] | None:
    doc = get(f"/markets/{urllib.parse.quote(ticker)}")
    market = (doc or {}).get("market")
    if not isinstance(market, dict):
        return None
    return {"result": market.get("result"), "status": market.get("status")}


# ------------------------------------------------------------------ store
def store_dir(root: Path) -> Path:
    return Path(root).joinpath(*STORE_SUBDIR)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def orders_path(root: Path, game_date: str) -> Path:
    return store_dir(root) / f"orders_{game_date}.json"


def iter_order_files(root: Path) -> list[Path]:
    return sorted(store_dir(root).glob("orders_*.json"))


# ------------------------------------------------------------------ evaluation (pre-registered)
def _bootstrap(rows: Sequence[Mapping[str, Any]], value: Callable[[Mapping[str, Any]], float],
               draws: int = BOOT_DRAWS, seed: int = BOOT_SEED) -> dict[str, Any] | None:
    by_event: dict[str, list[float]] = collections.defaultdict(list)
    for row in rows:
        by_event[str(row.get("event_id"))].append(value(row))
    if not by_event:
        return None
    sums = [sum(v) for v in by_event.values()]
    counts = [len(v) for v in by_event.values()]
    mean = sum(sums) / sum(counts)
    rng = random.Random(seed)
    k = len(sums)
    stats = []
    for _ in range(draws):
        s = c = 0.0
        for _ in range(k):
            j = rng.randrange(k)
            s += sums[j]
            c += counts[j]
        stats.append(s / c)
    stats.sort()

    def q(p: float) -> float:
        return stats[min(len(stats) - 1, max(0, int(round(p * (len(stats) - 1)))))]

    return {"mean": mean, "n": sum(counts), "events": k,
            "ci95": [q(0.025), q(0.975)], "ci99": [q(0.005), q(0.995)]}


def mispaired_series(orders: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Series excluded by the pre-registered rule (pre-outcome information only), with the reason."""
    out: dict[str, str] = {}
    gaps: dict[str, list[bool]] = collections.defaultdict(list)
    for rec in orders:
        series = str(rec.get("series") or "")
        if WOMEN_TITLE_RE.search(str(rec.get("series_title") or "")):
            out[series] = "women_title"
        order = rec.get("order") or {}
        if num(order.get("kalshi_mid")) and num(order.get("fair")):
            gaps[series].append(abs(order["fair"] - order["kalshi_mid"]) > MISPAIR_GAP)
    for series, flags in gaps.items():
        if series not in out and len(flags) >= MISPAIR_MIN_ORDERS and sum(flags) / len(flags) > 0.5:
            out[series] = f"fair_vs_kalshi_mid_gt_{int(MISPAIR_GAP * 100)}pp_on_{sum(flags)}_of_{len(flags)}"
    return out


def counted_population(records: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Placed orders that meet the pre-registered population rule, each with `win`, and the exclusion counts."""
    placed = [r for r in records if r.get("order")]
    excluded = collections.Counter()
    bad_series = mispaired_series(placed)
    rows = []
    for rec in placed:
        order, closed, settle = rec["order"], rec.get("closed") or {}, rec.get("settlement") or {}
        if not closed:
            excluded["not_closed_yet"] += 1
            continue
        if order.get("late_observed"):
            excluded["late_observed"] += 1
            continue
        if closed.get("void_reason"):
            excluded[str(closed["void_reason"])] += 1
            continue
        if rec.get("series") in bad_series:
            excluded["mispaired_series"] += 1
            continue
        if settle.get("result") not in ("yes", "no"):
            excluded["unsettled_or_void_result"] += 1
            continue
        if not num(closed.get("fair_close")):
            excluded["no_close_fair"] += 1
            continue
        b = order["b"]
        win = 1.0 if settle["result"] == rec["leg"] else 0.0
        rows.append({
            "cell": rec.get("cell"), "series": rec.get("series"), "event_id": rec.get("event_id"),
            "ticker": rec.get("ticker"), "leg": rec.get("leg"), "b": b, "win": win,
            "fair_place": order.get("fair"), "fair_close": closed["fair_close"],
            "filled_a": closed.get("fill_a_t") is not None, "filled_b": closed.get("fill_b_t") is not None,
            "fill_b_known": closed.get("fill_b_status") == "ok",
            "fair_fill_a": closed.get("fair_at_fill_a"), "fair_fill_b": closed.get("fair_at_fill_b"),
        })
    return rows, {"excluded": dict(excluded), "mispaired_series": bad_series}


def cell_stats(rows: Sequence[Mapping[str, Any]], model: str) -> dict[str, Any]:
    flag = "filled_b" if model == "B" else "filled_a"
    usable = [r for r in rows if model == "A" or r["fill_b_known"]]
    filled = [r for r in usable if r[flag]]
    unfilled = [r for r in usable if not r[flag]]
    fair_fill = "fair_fill_b" if model == "B" else "fair_fill_a"
    adverse = [r for r in filled if num(r.get(fair_fill)) and num(r.get("fair_place"))]
    return {
        "placed": len(usable), "filled": len(filled),
        "fill_rate": len(filled) / len(usable) if usable else None,
        "events_filled": len({r["event_id"] for r in filled}),
        "filled_win_minus_close": _bootstrap(filled, lambda r: r["win"] - r["fair_close"]),
        "unfilled_win_minus_close": _bootstrap(unfilled, lambda r: r["win"] - r["fair_close"]),
        "filled_roi": _bootstrap(filled, lambda r: r["win"] / r["b"] - 1.0),
        "adverse_selection_fair_fill_minus_place": (
            sum(r[fair_fill] - r["fair_place"] for r in adverse) / len(adverse) if adverse else None),
        "fair_drift_to_close_filled": (
            sum(r["fair_close"] - r["fair_place"] for r in filled if num(r.get("fair_place"))) / len(filled)
            if filled else None),
        "fair_drift_to_close_unfilled": (
            sum(r["fair_close"] - r["fair_place"] for r in unfilled if num(r.get("fair_place"))) / len(unfilled)
            if unfilled else None),
    }


def _ci(stat: Mapping[str, Any] | None, level: float) -> tuple[float, float] | None:
    if not stat:
        return None
    lo, hi = stat["ci99"] if level >= 0.99 else stat["ci95"]
    return lo, hi


def judge_look(stats_b: Mapping[str, Any], level: float, final: bool) -> str:
    """GO / NO-GO / CONTINUE at one look, by the pre-registered bars."""
    win, roi = stats_b.get("filled_win_minus_close"), stats_b.get("filled_roi")
    if not win or not roi:
        return "NO-GO" if final else "CONTINUE"
    win95, roi95 = _ci(win, FUTILITY_CI), _ci(roi, FUTILITY_CI)
    if roi95[1] < 0 or win95[1] < GO_WIN_LB:
        return "NO-GO"
    win_l, roi_l = _ci(win, level), _ci(roi, level)
    if win_l[0] > GO_WIN_LB and roi_l[0] > 0 and stats_b.get("events_filled", 0) >= MIN_EVENTS:
        return "GO"
    return "NO-GO" if final else "CONTINUE"


def take_looks(looks: dict[str, Any], per_cell_b: Mapping[str, Mapping[str, Any]], today: str) -> dict[str, Any]:
    """Advance `looks` (the frozen record) with any look reached today. Mutates and returns it."""
    for cell in CELLS:
        entry = looks.setdefault(cell, {"status": "CONTINUE", "looks": []})
        if entry["status"] in ("GO", "NO-GO", "INSUFFICIENT"):
            continue
        stats_b = per_cell_b.get(cell) or {}
        n = stats_b.get("filled", 0)
        taken = {lk["threshold"] for lk in entry["looks"] if isinstance(lk.get("threshold"), int)}
        crossed = [th for th in LOOKS if n >= th and th not in taken and th > max(taken, default=0)]
        calendar = today >= CALENDAR_STOP
        if crossed:
            th = max(crossed)
            final = th == LOOKS[-1]
            level = LOOK_CI[th]
        elif calendar:
            if n < LOOKS[0]:
                entry["status"] = "INSUFFICIENT"
                entry["looks"].append({"threshold": "calendar", "taken_on": today, "n": n,
                                       "verdict": "INSUFFICIENT"})
                continue
            th, final, level = "calendar", True, FINAL_CI
        else:
            continue
        verdict = judge_look(stats_b, level, final)
        entry["looks"].append({
            "threshold": th, "taken_on": today, "n": n, "events": stats_b.get("events_filled"),
            "ci_level": level, "win_minus_close": stats_b.get("filled_win_minus_close"),
            "roi": stats_b.get("filled_roi"), "verdict": verdict,
        })
        entry["status"] = verdict if verdict != "CONTINUE" else "CONTINUE"
    return looks
