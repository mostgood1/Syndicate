"""Maker vs taker on our own LIVE picks: a shadow counterfactual. NO ORDER PATH.

Pre-registration: `.syndicate/findings_2026-10-24_maker_vs_taker_shadow.md` (committed
`cda4cfc6` before any maker fill, P&L or CLV was computed). Lane `maker-vs-taker-shadow`.

For every live Kalshi / Polymarket US taker fill in the execution ledger, ask: had we
POSTED a resting bid on the same contract at the same instant instead of taking the ask,
would it have filled, and would the position have made more money?

    taker  = the fill we actually got (hold to settlement, real fee)
    maker  = bid b at t0 (one tick inside / join), resting until min(t0 + rest, kickoff);
             filled only if the venue's own prints trade THROUGH b (strictly below it);
             unfilled -> no position, P&L 0

READ-ONLY. This file imports no order, execution or credential code and sends only
unauthenticated GETs to Kalshi's PUBLIC endpoints (`/markets/trades`, `/historical/trades`,
candlesticks, `/series`). Polymarket US publishes no trade history, so its fills are read off
the fleet's own recorded quotes (`venue_odds/polymarket__*`), a weaker model reported apart.

Two commands, both run on the fleet at nice 19:

    dump      execution_ledger.full_history_orders() -> live fills JSON (needs keyvalue env)
    simulate  live fills JSON + venue history -> per-cell report (JSON + markdown)
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
SPLIT_AT = "2026-10-01T00:00:00Z"          # DISCOVER before, CONFIRM on/after (pre-registered)
SEED = 20261024
REPS = 2000
LEVEL = 0.90
MIN_CONFIRM_GAMES = 10
TICK = 0.01
KALSHI_MAKER_FRACTION = 0.25               # 0.0175 / 0.07; third-party figure, flagged in the report
POLY_TAKER_THETA = 0.0695

# Rest windows, minutes. The first of each is PRIMARY (pre-registered); None = until kickoff.
PREGAME_RESTS = (60, 15, None)
INGAME_RESTS = (2, 10)
POLICIES = ("inside", "join")              # "inside" is PRIMARY
FILL_MODELS = ("through", "touch")         # "through" is PRIMARY

# --- cell axes: copied from scripts/live_cell_scorecard.py (lane live-cell-scorecard) so the two
# reports key the same cells. Reuse, not a second definition: change them there first.
BUCKETS = ((0.0, 0.40, "<40c"), (0.40, 0.55, "40-55c"), (0.55, 0.75, "55-75c"), (0.75, 1.01, "75c+"))
KALSHI_SPORT = (
    ("KXWNBA", "wnba"), ("KXNBA", "nba"), ("KXMLB", "mlb"), ("KXNFL", "nfl"), ("KXNCAAF", "ncaaf"),
    ("KXNCAAB", "ncaab"), ("KXNHL", "nhl"), ("KXATP", "tennis"), ("KXWTA", "tennis"), ("KXITF", "tennis"),
    ("KXCOD", "esports"), ("KXMVE", "parlay"), ("KXMLS", "soccer"), ("KXBUNDESLIGA", "soccer"),
    ("KXEREDIVISIE", "soccer"), ("KXLALIGA", "soccer"), ("KXLIGUE1", "soccer"), ("KXSERIEA", "soccer"),
    ("KXEPL", "soccer"), ("KXUCL", "soccer"),
)
PAPER_VENUES = ("paper:kalshi", "paper:polymarket")
PM_FAMILY = {"aec": "h2h", "atc": "h2h", "asc": "spread", "tsc": "total", "astatc": "prop"}


def ts(value: Any) -> datetime | None:
    text = re.sub(r"(\.\d{6})\d+", r"\1", str(value or "").replace("Z", "+00:00"))
    try:
        out = datetime.fromisoformat(text)
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def bucket(p: float | None) -> str:
    for lo, hi, name in BUCKETS:
        if p is not None and lo <= p < hi:
            return name
    return "?"


def _kalshi_sport_series(ticker: str) -> tuple[str, str]:
    series = ticker.split("-")[0].upper()
    for prefix, sport in KALSHI_SPORT:
        if series.startswith(prefix):
            return sport, series[len(prefix):]
    return "other", series


def family_of(r: Mapping[str, Any]) -> str:
    market = str(r.get("market") or "").lower()
    if market:
        if str(r.get("player_name") or "").strip() or market.startswith(("player_", "batter_", "pitcher_")) \
                or market in ("strikeouts", "outs", "receptions"):
            return "prop"
        for key, fam in (("total", "total"), ("spread", "spread"), ("h2h", "h2h")):
            if key in market:
                return fam
        return "other"
    ticker = str(r.get("venue_ticker") or "")
    if r.get("venue") == "polymarket" or ticker[:3] in ("aec", "atc", "asc", "tsc", "ast"):
        return PM_FAMILY.get(ticker.split("-")[0].lower(), "other")
    sport, rest = _kalshi_sport_series(ticker)
    if sport == "parlay":
        return "parlay"
    if rest in ("GAME", "MATCH", "WMATCH", "DOUBLES") or rest.endswith("GAME"):
        return "h2h"
    if "SPREAD" in rest:
        return "spread"
    if "TOTAL" in rest:
        return "total"
    return "prop" if rest else "other"


def sport_of(r: Mapping[str, Any]) -> str:
    sport = str(r.get("sport") or "").lower().strip()
    if sport and sport != "none":
        return sport
    ticker = str(r.get("venue_ticker") or "")
    if ticker.upper().startswith("KX"):
        return _kalshi_sport_series(ticker)[0]
    parts = ticker.split("-")
    return parts[1].lower() if len(parts) > 1 else "?"


def game_of(r: Mapping[str, Any]) -> str:
    if r.get("event_id"):
        return str(r["event_id"])
    ticker = str(r.get("venue_ticker") or "")
    parts = ticker.split("-")
    if ticker.upper().startswith("KX") and len(parts) > 1:
        return "k:" + parts[1]
    m = re.match(r"^[a-z]+-(.+?-\d{4}-\d{2}-\d{2})", ticker)
    return "p:" + (m.group(1) if m else ticker)


def phase_of(r: Mapping[str, Any]) -> str:
    return "in_game" if r.get("source") != "venue_rebuild" and r.get("ev_pct") is None else "pregame"


# --------------------------------------------------------------------------- fees

def ceil_cent(x: float) -> float:
    return math.ceil(round(x * 100.0, 9)) / 100.0


def kalshi_maker_fee(contracts: float, price: float, fee_type: str, multiplier: float) -> float:
    if fee_type == "quadratic":
        return 0.0
    return ceil_cent(0.07 * KALSHI_MAKER_FRACTION * multiplier * contracts * price * (1.0 - price))


def kalshi_taker_fee(contracts: float, price: float, multiplier: float) -> float:
    return ceil_cent(0.07 * multiplier * contracts * price * (1.0 - price))


def poly_taker_fee(contracts: float, price: float) -> float:
    return round(POLY_TAKER_THETA * contracts * price * (1.0 - price), 2)


# --------------------------------------------------------------------------- Kalshi public history

class KalshiPublic:
    """Unauthenticated GETs with an on-disk cache. Nothing here can place or cancel an order."""

    def __init__(self, cache_dir: Path, pause: float = 0.12):
        self.cache = cache_dir
        self.cache.mkdir(parents=True, exist_ok=True)
        self.pause = pause
        self.calls = 0
        self.failures = 0
        self._cutoff: datetime | None = None

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        url = KALSHI + path + ("?" + urllib.parse.urlencode(params) if params else "")
        key = self.cache / (hashlib.sha1(url.encode()).hexdigest() + ".json")
        if key.exists():
            return json.loads(key.read_text())
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "syndicate-research"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = json.loads(resp.read())
                self.calls += 1
                time.sleep(self.pause)
                key.write_text(json.dumps(body))
                return body
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    key.write_text(json.dumps({"__status": 404}))
                    return {"__status": 404}
                if exc.code == 429:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                self.failures += 1
                return {"__status": exc.code}
            except Exception:  # noqa: BLE001 -- a network blip is retried, then counted
                time.sleep(1.0 * (attempt + 1))
        self.failures += 1
        return {"__status": "error"}

    def cutoff(self) -> datetime:
        if self._cutoff is None:
            body = self.get("/historical/cutoff")
            self._cutoff = ts(body.get("trades_created_ts")) or datetime(2026, 8, 25, tzinfo=timezone.utc)
        return self._cutoff

    def series(self, series: str) -> tuple[str | None, float]:
        body = self.get(f"/series/{series}")
        s = body.get("series") if isinstance(body, dict) else None
        if not s:
            return None, 1.0
        try:
            mult = float(s.get("fee_multiplier") or 1.0)
        except (TypeError, ValueError):
            mult = 1.0
        return s.get("fee_type"), mult

    def candles(self, ticker: str, start: datetime, end: datetime) -> list[dict]:
        series = ticker.split("-")[0]
        params = {"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()), "period_interval": 1}
        out: list[dict] = []
        for path in (f"/series/{series}/markets/{ticker}/candlesticks", f"/historical/markets/{ticker}/candlesticks"):
            body = self.get(path, params)
            if isinstance(body, dict) and body.get("candlesticks"):
                out = body["candlesticks"]
                break
        return out

    def trades(self, ticker: str, start: datetime, end: datetime) -> list[dict]:
        path = "/historical/trades" if start < self.cutoff() else "/markets/trades"
        out: list[dict] = []
        cursor = ""
        for _ in range(50):
            params: dict[str, Any] = {"ticker": ticker, "min_ts": int(start.timestamp()),
                                      "max_ts": int(end.timestamp()) + 1, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            body = self.get(path, params)
            if not isinstance(body, dict) or "trades" not in body:
                break
            out.extend(body["trades"])
            cursor = body.get("cursor") or ""
            if not cursor:
                break
        if not out and path == "/markets/trades" and start < self.cutoff() + timedelta(days=2):
            return self.trades_historical(ticker, start, end)
        return out

    def trades_historical(self, ticker: str, start: datetime, end: datetime) -> list[dict]:
        body = self.get("/historical/trades", {"ticker": ticker, "min_ts": int(start.timestamp()),
                                               "max_ts": int(end.timestamp()) + 1, "limit": 1000})
        return body.get("trades", []) if isinstance(body, dict) else []


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _close(side: Any) -> float | None:
    side = side or {}
    return _f(side.get("close_dollars", side.get("close")))


def kalshi_quote(candles: list[dict], at: datetime, leg: str) -> tuple[float | None, float | None]:
    """(bid_leg, ask_leg) from the last 1-minute candle that ENDED at or before `at`."""
    best = None
    for c in candles:
        end = c.get("end_period_ts")
        if end is not None and int(end) <= at.timestamp():
            if best is None or int(end) > int(best["end_period_ts"]):
                best = c
    if best is None:
        return None, None
    ybid = _close(best.get("yes_bid"))
    yask = _close(best.get("yes_ask"))
    if leg == "yes":
        return ybid, yask
    return (None if yask is None else round(1.0 - yask, 4)), (None if ybid is None else round(1.0 - ybid, 4))


def leg_print_price(trade: Mapping[str, Any], leg: str) -> float | None:
    if leg == "yes":
        p = _f(trade.get("yes_price_dollars"))
        if p is None:
            q = _f(trade.get("no_price_dollars"))
            p = None if q is None else 1.0 - q
        return p
    p = _f(trade.get("no_price_dollars"))
    if p is None:
        q = _f(trade.get("yes_price_dollars"))
        p = None if q is None else 1.0 - q
    return p


def kalshi_fill(trades: list[dict], leg: str, b: float, improved: bool, start: datetime, end: datetime,
                contracts: float, model: str) -> datetime | None:
    """First instant cumulative SELL-our-leg volume through `b` reaches our size, else None.

    A taker sells our leg by buying the other one: leg yes <- taker_side == "no"; leg no <- "yes".
    THROUGH: printed strictly below b. TOUCH: <= b when we improved the bid, < b when we joined.
    """
    seller = "no" if leg == "yes" else "yes"
    hits = []
    for t in trades:
        when = ts(t.get("created_time"))
        if when is None or not (start < when <= end):
            continue
        if str(t.get("taker_side") or t.get("taker_outcome_side") or "").lower() != seller:
            continue
        price = leg_print_price(t, leg)
        if price is None:
            continue
        through = price < b - 1e-9
        touch = through or (improved and abs(price - b) < 1e-9)
        if (through if model == "through" else touch):
            hits.append((when, _f(t.get("count_fp")) or _f(t.get("count")) or 0.0))
    total = 0.0
    for when, count in sorted(hits):
        total += count
        if total + 1e-9 >= contracts:
            return when
    return None


# --------------------------------------------------------------------------- Polymarket recorded quotes

def load_poly_points(venue_odds_dir: Path) -> dict[str, list[tuple[datetime, float | None, float | None]]]:
    """slug -> sorted [(ts, long_ask, short_ask)] merged across every recorded file."""
    out: dict[str, dict[str, tuple]] = defaultdict(dict)
    for path in sorted(glob.glob(str(venue_odds_dir / "polymarket__*.json"))):
        try:
            doc = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            continue
        for slug, m in (doc.get("markets") or {}).items():
            for p in m.get("points") or []:
                when = ts(p.get("ts"))
                if when is not None:
                    out[slug][p["ts"]] = (when, _f(p.get("yes")), _f(p.get("no")))
    return {slug: sorted(v.values()) for slug, v in out.items()}


def poly_quote(points: list[tuple], at: datetime, leg: str) -> tuple[float | None, float | None]:
    last = None
    for p in points:
        if p[0] <= at:
            last = p
        else:
            break
    if last is None:
        return None, None
    long_ask, short_ask = last[1], last[2]
    if leg == "yes":
        return (None if short_ask is None else round(1.0 - short_ask, 4)), long_ask
    return (None if long_ask is None else round(1.0 - long_ask, 4)), short_ask


def poly_fill(points: list[tuple], leg: str, b: float, improved: bool, start: datetime, end: datetime,
              model: str) -> datetime | None:
    for p in points:
        if not (start < p[0] <= end):
            continue
        ask = p[1] if leg == "yes" else p[2]
        if ask is None:
            continue
        if ask < b - 1e-9 or (model == "touch" and improved and abs(ask - b) < 1e-9):
            return p[0]
    return None


# --------------------------------------------------------------------------- the counterfactual

def leg_of(r: Mapping[str, Any]) -> str | None:
    pk = str(r.get("position_key") or "")
    if pk.startswith("ingame:") and pk.rsplit(":", 1)[-1] in ("yes", "no"):
        return pk.rsplit(":", 1)[-1]
    side = str(r.get("side") or "").lower()
    if side in ("yes", "no"):
        return side
    if r.get("venue") == "polymarket":
        return {"long": "yes", "short": "no", "over": "yes", "under": "no"}.get(side)
    if side in ("home", "away"):
        return None
    try:
        from syndicate.features.shared.execution_ledger import venue_leg_of
        leg = venue_leg_of("kalshi", r.get("side"), r.get("market"), r.get("line"))
    except Exception:  # noqa: BLE001
        return None
    return leg if leg in ("yes", "no") else None


def price_of(r: Mapping[str, Any]) -> float | None:
    """The price paid: `fill_price`, else the venue's average (early Polymarket rows carry only that)."""
    for key in ("fill_price", "venue_avg_price"):
        p = _f(r.get(key))
        if p is not None and 0.0 < p < 1.0:
            return p
        if p is not None and abs(p) >= 100:
            # paper plan rows price in American odds (live-cell-scorecard's contract_price does the same)
            profit = p / 100.0 if p > 0 else 100.0 / -p
            return round(1.0 / (1.0 + profit), 4)
    return None


def contracts_of(r: Mapping[str, Any]) -> float:
    c = _f(r.get("contracts"))
    if c and c > 0:
        return c
    p, stake = price_of(r), _f(r.get("fill_stake_dollars"))
    return stake / p if p and stake else 0.0


def infer_leg(leg: str | None, quote, price: float) -> tuple[str | None, str]:
    """The stated leg when there is one; else the leg whose ask at t0 is within 2c of what we paid.

    Team / over-under labels on later Kalshi rows and long/short-free Polymarket rows have no leg
    of their own. Matching the ask we actually hit is a reading, not a guess: a leg whose ask is
    far from our fill could not have been the one we bought. Both within 2c -> unresolved.
    """
    if leg in ("yes", "no"):
        return leg, "stated"
    near = [lg for lg in ("yes", "no") if (quote(lg)[1] is not None and abs(quote(lg)[1] - price) <= 0.02)]
    return (near[0], "ask_match") if len(near) == 1 else (None, "unresolved")


def taker_hold_pnl(r: Mapping[str, Any]) -> tuple[float, float]:
    """(hold-to-settlement P&L with the real fee, staked dollars)."""
    c = contracts_of(r)
    p = price_of(r)
    win = r["outcome"] == "won"
    fee = float(r.get("fees_dollars") or 0.0)
    return c * ((1.0 - p) if win else -p) - fee, c * p


def simulate_order(r: Mapping[str, Any], *, kalshi: KalshiPublic | None, poly_points: Mapping[str, list],
                   fee_cache: dict) -> dict[str, Any]:
    venue = str(r["venue"]).split(":")[-1] if str(r["venue"]).startswith("paper:") else r["venue"]
    r = {**r, "venue": venue}
    ticker = str(r.get("venue_ticker") or "")
    t0, ko = ts(r.get("submitted_at")), ts(r.get("commence_time"))
    p = price_of(r)
    c = contracts_of(r)
    base = {
        "venue": venue, "sport": sport_of(r), "family": family_of(r), "bucket": bucket(p),
        "phase": phase_of(r), "game": game_of(r), "date": str(r.get("selected_date") or ""),
        "submitted_at": r.get("submitted_at"), "split": None,
        "ticker": ticker, "fill_price": p, "contracts": c, "win": r["outcome"] == "won",
    }
    taker_pnl, stake = taker_hold_pnl(r)
    base.update(taker_pnl=taker_pnl, taker_stake=stake, ledger_pnl=_f(r.get("pnl_dollars")))
    leg = leg_of(r)
    if t0 is None or c <= 0:
        return {**base, "drop": "no_size_or_instant"}
    timed_pregame = ko is not None and t0 < ko
    base["timed_phase"] = "pregame" if timed_pregame else "in_game"
    rests = PREGAME_RESTS if timed_pregame else INGAME_RESTS
    horizon_end = max(t0 + timedelta(minutes=max(x for x in rests if x is not None)),
                      ko if (timed_pregame and ko) else t0)

    if venue == "kalshi":
        series = ticker.split("-")[0]
        if series not in fee_cache:
            fee_cache[series] = kalshi.series(series)
        fee_type, mult = fee_cache[series]
        base.update(fee_type=fee_type, fee_multiplier=mult)
        candles = kalshi.candles(ticker, t0 - timedelta(minutes=10), t0 + timedelta(minutes=1))
        leg, base["leg_source"] = infer_leg(leg, lambda lg: kalshi_quote(candles, t0, lg), p)
        if leg is None:
            return {**base, "drop": "leg_unresolved"}
        bid, ask = kalshi_quote(candles, t0, leg)
        if bid is None:
            return {**base, "drop": "no_quote"}
        trades = kalshi.trades(ticker, t0, horizon_end)
        close_mid = None
        if timed_pregame and ko is not None:
            cc = kalshi.candles(ticker, ko - timedelta(minutes=10), ko)
            cb, ca = kalshi_quote(cc, ko, leg)
            if cb is not None and ca is not None:
                close_mid = (cb + ca) / 2.0
    else:
        pts = poly_points.get(ticker) or []
        leg, base["leg_source"] = infer_leg(leg, lambda lg: poly_quote(pts, t0, lg), p)
        if leg is None:
            return {**base, "drop": "leg_unresolved"}
        bid, ask = poly_quote(pts, t0, leg)
        base.update(fee_type="polymarket_maker_assumed_0", fee_multiplier=None)
        if bid is None:
            return {**base, "drop": "no_quote"}
        trades = None
        close_mid = None
        if timed_pregame and ko is not None:
            cb, ca = poly_quote(pts, ko, leg)
            if cb is not None and ca is not None:
                close_mid = (cb + ca) / 2.0
    if ask is None or abs(ask - p) > 0.02 + 1e-9:
        return {**base, "bid0": bid, "ask0": ask, "drop": "instant_quote_mismatch"}
    mid0 = (bid + ask) / 2.0
    base.update(bid0=bid, ask0=ask, mid0=mid0, close_mid=close_mid,
                ask_mismatch=None if ask is None else round(p - ask, 4))

    sims: dict[str, dict] = {}
    for policy in POLICIES:
        b = round(min(bid + TICK, p - TICK), 2) if policy == "inside" else round(bid, 2)
        improved = b > bid + 1e-9
        if not (0.01 <= b < p - 1e-9):
            for rest in rests:
                for model in FILL_MODELS:
                    sims[f"{policy}|{rest}|{model}"] = {"placed": False, "filled": False, "maker_pnl": 0.0,
                                                        "b": b}
            continue
        for rest in rests:
            end = ko if rest is None else t0 + timedelta(minutes=rest)
            if timed_pregame and ko is not None:
                end = min(end, ko)
            for model in FILL_MODELS:
                if venue == "kalshi":
                    when = kalshi_fill(trades, leg, b, improved, t0, end, c, model)
                    fee = kalshi_maker_fee(c, b, fee_type or "unknown", mult) if when else 0.0
                else:
                    when = poly_fill(poly_points.get(ticker) or [], leg, b, improved, t0, end, model)
                    fee = 0.0
                win = base["win"]
                pnl = (c * ((1.0 - b) if win else -b) - fee) if when else 0.0
                sim = {"placed": True, "filled": when is not None, "b": b, "maker_fee": fee,
                       "maker_pnl": pnl, "maker_stake": c * b if when else 0.0,
                       "fill_at": when.isoformat() if when else None}
                if venue == "kalshi" and not when and timed_pregame and policy == "inside" and model == "through":
                    hb, ha = kalshi_quote(kalshi.candles(ticker, end - timedelta(minutes=10), end), end, leg)
                    if ha is not None and 0.0 < ha < 1.0:
                        sim["hybrid_pnl"] = c * ((1.0 - ha) if win else -ha) - kalshi_taker_fee(c, ha, mult)
                        sim["hybrid_ask"] = ha
                sims[f"{policy}|{rest}|{model}"] = sim
    return {**base, "sims": sims, "primary": f"inside|{rests[0]}|through"}


# --------------------------------------------------------------------------- statistics

def clustered(rows: list[dict], stat, reps: int = REPS, seed: int = SEED, level: float = LEVEL):
    by_game: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_game[r["game"]].append(r)
    games = list(by_game.values())
    point = stat(rows)
    if len(games) < 2 or point is None:
        return point, None, None
    rng = random.Random(seed)
    draws = []
    for _ in range(reps):
        sample = [r for _g in range(len(games)) for r in games[rng.randrange(len(games))]]
        v = stat(sample)
        if v is not None:
            draws.append(v)
    draws.sort()
    if not draws:
        return point, None, None
    lo = draws[int(len(draws) * (1 - level) / 2)]
    hi = draws[min(len(draws) - 1, int(len(draws) * (1 + level) / 2))]
    return point, lo, hi


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def apply_split(sims: list[dict]) -> str:
    """Deviation D1 item 4: DISCOVER/CONFIRM at 10-01, unless DISCOVER would hold < 30% of the
    simulated positions; then at the first date D (00:00Z) with >= 50% of positions before it.
    Computed from submission dates alone."""
    ok = [s for s in sims if "sims" in s]
    split = SPLIT_AT
    if ok and sum(1 for s in ok if str(s["submitted_at"]) < SPLIT_AT) < 0.30 * len(ok):
        dates = sorted(str(s["submitted_at"])[:10] for s in ok)
        for d in sorted(set(dates)):
            if sum(1 for x in dates if x < d) >= 0.5 * len(dates):
                split = d + "T00:00:00Z"
                break
    for s in sims:
        s["split"] = "confirm" if str(s.get("submitted_at")) >= split else "discover"
    return split


def summarise(rows: list[dict], key: str) -> dict[str, Any]:
    """`key` names the sim configuration (policy|rest|model)."""
    rows = [r for r in rows if key in r.get("sims", {})]
    if not rows:
        return {"n": 0}
    sim = lambda r: r["sims"][key]  # noqa: E731
    placed = [r for r in rows if sim(r)["placed"]]
    filled = [r for r in rows if sim(r)["filled"]]
    unfilled = [r for r in placed if not sim(r)["filled"]]
    delta = lambda rs: _mean([sim(r)["maker_pnl"] - r["taker_pnl"] for r in rs])  # noqa: E731
    taker_unit = lambda rs: _mean([(1.0 if r["win"] else 0.0) - r["fill_price"] for r in rs])  # noqa: E731
    adverse = lambda rs: (lambda f, u: None if f is None or u is None else f - u)(  # noqa: E731
        taker_unit([r for r in rs if sim(r)["filled"]]), taker_unit([r for r in rs if sim(r)["placed"] and not sim(r)["filled"]]))
    taker_pnl = sum(r["taker_pnl"] for r in rows)
    taker_stake = sum(r["taker_stake"] for r in rows)
    maker_pnl = sum(sim(r)["maker_pnl"] for r in rows)
    maker_stake = sum(sim(r).get("maker_stake", 0.0) for r in rows)
    d = clustered(rows, delta)
    a = clustered(placed, adverse)
    out = {
        "n": len(rows), "games": len({r["game"] for r in rows}), "placed": len(placed),
        "filled": len(filled), "fill_rate": len(filled) / len(placed) if placed else None,
        "taker_pnl": round(taker_pnl, 2), "taker_stake": round(taker_stake, 2),
        "taker_roi": taker_pnl / taker_stake if taker_stake else None,
        "maker_pnl": round(maker_pnl, 2), "maker_stake": round(maker_stake, 2),
        "maker_roi": maker_pnl / maker_stake if maker_stake else None,
        "delta_per_pos": d,
        "taker_unit_filled": taker_unit(filled), "taker_unit_unfilled": taker_unit(unfilled),
        "adverse_filled_minus_unfilled": a,
        "maker_win_minus_mid0": _mean([(1.0 if r["win"] else 0.0) - r["mid0"] for r in filled if r.get("mid0") is not None]),
        "taker_win_minus_mid0": _mean([(1.0 if r["win"] else 0.0) - r["mid0"] for r in rows if r.get("mid0") is not None]),
        "clv_taker": _mean([r["close_mid"] - r["fill_price"] for r in rows if r.get("close_mid") is not None]),
        "clv_maker_fills": _mean([r["close_mid"] - sim(r)["b"] for r in filled if r.get("close_mid") is not None]),
        "clv_taker_on_fills": _mean([r["close_mid"] - r["fill_price"] for r in filled if r.get("close_mid") is not None]),
    }
    hyb = [r for r in rows if "hybrid_pnl" in sim(r) or sim(r)["filled"]]
    if hyb and any("hybrid_pnl" in sim(r) for r in rows):
        hpnl = lambda r: sim(r)["maker_pnl"] if sim(r)["filled"] else sim(r).get("hybrid_pnl", 0.0)  # noqa: E731
        out["hybrid_delta_per_pos"] = clustered(rows, lambda rs: _mean([hpnl(r) - r["taker_pnl"] for r in rs]))
    return out


def verdict(confirm: Mapping[str, Any], discover: Mapping[str, Any]) -> str:
    d = confirm.get("delta_per_pos") or (None, None, None)
    if not confirm.get("n") or confirm.get("games", 0) < MIN_CONFIRM_GAMES or d[1] is None:
        return "INSUFFICIENT"
    if d[2] is not None and d[2] <= 0:
        return "FALSIFIED (maker does not beat taker)"
    dd = (discover.get("delta_per_pos") or (None,))[0]
    if d[1] > 0 and dd is not None and dd > 0:
        return "MAKER BEATS TAKER"
    return "NOT SHOWN (CI spans 0)"


CELL_KEYS = (("venue",), ("venue", "phase"), ("venue", "sport"), ("venue", "family"), ("venue", "bucket"),
             ("venue", "sport", "family", "bucket", "phase"))


def build_report(sim_rows: list[dict], drops: Mapping[str, int]) -> dict[str, Any]:
    ok = [r for r in sim_rows if "sims" in r]
    dates = sorted({r["date"] for r in ok})
    configs = sorted({k for r in ok for k in r["sims"]})
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "preregistration": ".syndicate/findings_2026-10-24_maker_vs_taker_shadow.md (cda4cfc6)",
        "drops": dict(drops), "n_simulated": len(ok),
        "coverage": {
            v: {"dates": len({r['date'] for r in ok if r['venue'] == v}),
                "first": min((r['date'] for r in ok if r['venue'] == v), default=None),
                "last": max((r['date'] for r in ok if r['venue'] == v), default=None),
                "positions": sum(1 for r in ok if r['venue'] == v),
                "games": len({r['game'] for r in ok if r['venue'] == v}),
                "discover": sum(1 for r in ok if r['venue'] == v and r['split'] == 'discover'),
                "confirm": sum(1 for r in ok if r['venue'] == v and r['split'] == 'confirm')}
            for v in ("kalshi", "polymarket")
        },
        "dates": dates,
        "quote_sanity": {
            "ask_mismatch_abs_le_1c": sum(1 for r in ok if r.get("ask_mismatch") is not None and abs(r["ask_mismatch"]) <= 0.011),
            "ask_mismatch_known": sum(1 for r in ok if r.get("ask_mismatch") is not None),
            "fee_types": dict(sorted(_count(r.get("fee_type") or "?" for r in ok).items())),
            "ledger_vs_hold_pnl_abs_gt_5c": sum(1 for r in ok if r.get("ledger_pnl") is not None and abs(r["ledger_pnl"] - r["taker_pnl"]) > 0.05),
        },
        "cells": {},
    }
    for keys in CELL_KEYS:
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in ok:
            groups[tuple(r[k] for k in keys)].append(r)
        table = []
        for gkey, rows in sorted(groups.items()):
            entry: dict[str, Any] = {"cell": dict(zip(keys, gkey))}
            prim = {r["primary"] for r in rows}
            for split in ("all", "discover", "confirm"):
                sub = rows if split == "all" else [r for r in rows if r["split"] == split]
                entry[split] = {p: summarise([r for r in sub if r["primary"] == p], p) for p in prim}
            entry["verdict"] = {p: verdict(entry["confirm"][p], entry["discover"][p]) for p in prim}
            if keys == ("venue",) or keys == ("venue", "phase"):
                entry["sensitivity_all"] = {c: summarise(rows, c) for c in configs}
            table.append(entry)
        report["cells"]["x".join(keys)] = table
    return report


def _count(it: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for x in it:
        out[x] += 1
    return out


def _ci(t) -> str:
    if not t or t[0] is None:
        return "-"
    if t[1] is None:
        return f"{t[0]:+.3f}"
    return f"{t[0]:+.3f} [{t[1]:+.3f}, {t[2]:+.3f}]"


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:+.1f}%"


def _rate(x) -> str:
    return "-" if x is None else f"{100 * x:.0f}%"


def _num(x) -> str:
    return "-" if x is None else f"{x:+.3f}"


def markdown(report: Mapping[str, Any]) -> str:
    lines = [f"# Maker vs taker shadow -- generated {report['generated_at']}", "",
             f"Pre-registration: {report['preregistration']}. Population: {report.get('population')}. "
             f"Split (D1): {report.get('split_at')}. Simulated positions: {report['n_simulated']}.",
             f"Drops: {json.dumps(report['drops'])}", "", "## Coverage", ""]
    for v, c in report["coverage"].items():
        lines.append(f"- {v}: {c['positions']} positions / {c['games']} games on {c['dates']} dates "
                     f"({c['first']}..{c['last']}); discover {c['discover']}, confirm {c['confirm']}")
    lines += ["", f"Quote sanity: {json.dumps(report['quote_sanity'])}", ""]
    for name, table in report["cells"].items():
        lines += [f"## Cells by {name} (primary config per phase)", "",
                  "| cell | split | n | games | fill | taker ROI | maker ROI | delta $/pos [90% CI] | adverse (fill-unfill) | CLV taker / maker | verdict |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for e in table:
            for p, verdict_text in e["verdict"].items():
                for split in ("all", "discover", "confirm"):
                    s = e[split].get(p) or {}
                    if not s.get("n"):
                        continue
                    cell = "/".join(str(x) for x in e["cell"].values())
                    lines.append(
                        f"| {cell} ({p}) | {split} | {s['n']} | {s['games']} | "
                        f"{_rate(s['fill_rate'])} | {_pct(s['taker_roi'])} | "
                        f"{_pct(s['maker_roi'])} | {_ci(s['delta_per_pos'])} | {_ci(s['adverse_filled_minus_unfilled'])} | "
                        f"{_num(s['clv_taker'])} / {_num(s['clv_maker_fills'])} | "
                        f"{verdict_text if split == 'confirm' else ''} |")
        lines.append("")
        if table and "sensitivity_all" in table[0]:
            lines += [f"### Sensitivity by {name} (all dates)", "",
                      "| cell | config | n | fill | maker $ | taker $ | delta $/pos [90% CI] | hybrid delta |",
                      "|---|---|---|---|---|---|---|---|"]
            for e in table:
                for cfg, s in sorted(e["sensitivity_all"].items()):
                    if not s.get("n"):
                        continue
                    cell = "/".join(str(x) for x in e["cell"].values())
                    lines.append(f"| {cell} | {cfg} | {s['n']} | "
                                 f"{_rate(s['fill_rate'])} | "
                                 f"{s['maker_pnl']:+.2f} | {s['taker_pnl']:+.2f} | {_ci(s['delta_per_pos'])} | "
                                 f"{_ci(s.get('hybrid_delta_per_pos'))} |")
            lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- commands

def cmd_dump(args) -> int:
    from syndicate.features.shared.execution_ledger import full_history_orders  # read-only loader
    every = full_history_orders()
    rows = [r for r in every if r.get("mode") == "live"]
    Path(args.out).write_text(json.dumps(rows, default=str))
    paper = [r for r in every if r.get("venue") in PAPER_VENUES]
    Path(args.paper_out).write_text(json.dumps(paper, default=str))
    print(f"live rows {len(rows)} -> {args.out}; paper plan rows {len(paper)} -> {args.paper_out}", flush=True)
    return 0


def cmd_simulate(args) -> int:
    orders = json.loads(Path(args.orders).read_text())
    drops: dict[str, int] = defaultdict(int)
    todo = []
    seen: set = set()
    venues = ("kalshi", "polymarket") if args.population == "live" else PAPER_VENUES
    for r in sorted(orders, key=lambda o: str(o.get("submitted_at") or "")):
        if r.get("venue") not in venues or (args.population == "live" and r.get("mode") != "live"):
            continue
        if args.population == "paper":
            key = (r.get("venue"), r.get("position_key") or r.get("idempotency_key"))
            if key in seen:
                drops["paper_duplicate_position"] += 1
                continue
            seen.add(key)
        if r.get("source") == "venue_rebuild":
            drops["venue_rebuild_no_order_instant"] += 1
        elif not r.get("commence_time"):
            drops["no_commence_time"] += 1
        elif not r.get("venue_ticker"):
            drops["no_venue_ticker"] += 1
        elif r.get("status") != "filled":
            drops["not_filled"] += 1
        elif r.get("outcome") not in ("won", "lost"):
            drops[f"outcome_{r.get('outcome')}"] += 1
        elif str(r.get("venue_ticker") or "").upper().startswith("KXMVE"):
            drops["kalshi_combo_kxmve"] += 1
        elif price_of(r) is None:
            drops["fill_price_unreadable"] += 1
        else:
            todo.append(r)
    kalshi = KalshiPublic(Path(args.cache))
    poly = load_poly_points(Path(args.venue_odds))
    fee_cache: dict = {}
    sims = []
    for i, r in enumerate(todo):
        s = simulate_order(r, kalshi=kalshi, poly_points=poly, fee_cache=fee_cache)
        if "drop" in s:
            drops[f"{s['venue']}:{s['drop']}"] += 1
        sims.append(s)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(todo)} simulated, kalshi calls {kalshi.calls}, failures {kalshi.failures}", flush=True)
    split_at = apply_split(sims)
    Path(args.rows_out).write_text(json.dumps(sims, default=str))
    report = build_report(sims, drops)
    report["population"] = args.population
    report["split_at"] = split_at
    report["kalshi_http"] = {"calls": kalshi.calls, "failures": kalshi.failures}
    Path(args.out).write_text(json.dumps(report, indent=1, default=str))
    Path(args.md).write_text(markdown(report))
    print(f"simulated {sum(1 for s in sims if 'sims' in s)} / {len(todo)}; drops {dict(drops)} -> {args.out}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--out", required=True)
    d.add_argument("--paper-out", required=True)
    s = sub.add_parser("simulate")
    s.add_argument("--orders", required=True)
    s.add_argument("--population", choices=("live", "paper"), default="live")
    s.add_argument("--cache", default=os.path.expanduser("~/maker_vs_taker_cache"))
    s.add_argument("--venue-odds", default=os.path.expanduser("~/syndicate-prod/data/reports/intelligence/venue_odds"))
    s.add_argument("--rows-out", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--md", required=True)
    args = ap.parse_args(argv)
    return cmd_dump(args) if args.cmd == "dump" else cmd_simulate(args)


if __name__ == "__main__":
    sys.exit(main())
