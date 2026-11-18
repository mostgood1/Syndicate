"""Read-only research: does FOLLOWING selected Polymarket sports traders pay after entry delay? (lane trader-following-study)

Our own version of the idea behind OddsJam "Prediction Traders" (`.syndicate/scope_2026-11-17_trader_following.md`),
tested before anything is built. Polymarket (international) publishes every trade with its wallet; Kalshi does not.

THE TEST (pre-registered in the lane before any data was pulled):
  * Universe: wallets on Polymarket's sports leaderboard (PNL and VOLUME boards, month and all-time).
  * A BET is a wallet's first BUY of one outcome in one market (repeat buys fold in, size-weighted). Only the sports
    we trade (`SPORT_PREFIXES`), only markets that resolved 0/1.
  * Wallets are SELECTED on in-sample bets placed before `SPLIT`: >= `MIN_BETS` bets, ROI lower 95% bound > 0
    (clustered by event), one-sided (never bought both outcomes of a market), and not high-frequency (history not
    capped by the page limit).
  * Their OUT-OF-SAMPLE bets (placed on or after `SPLIT`) are FOLLOWED at the market's own price `delay` seconds after
    their fill: the first taker BUY of the same outcome at or after t + delay, within `MAX_WAIT_S`. $1 flat per bet.
  * Reported per delay: ROI, event-clustered SE and lower 95% bound, n bets, n events; the same for the UNSELECTED
    baseline (every universe wallet's out-of-sample bets).
  * Falsified if, at 60 s, the selected wallets' lower bound <= 0 or their ROI is not above the baseline's.

Fees are not modelled (most Polymarket sports markets charged none in the window); the result is gross of fees and
says so. Calls only Polymarket's public data and gamma APIs (no key, no account), cached under --cache-dir.

Usage:  py -3 scripts/trader_follow_study.py [--cache-dir C:\\tmp\\pfmon\\trader_study] [--universe 300]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

DATA_API = "https://data-api.polymarket.com/v2"
GAMMA_API = "https://gamma-api.polymarket.com"
# The sports this system trades, as Polymarket slug prefixes (gamma `/sports`, 2026-11-17).
SPORT_PREFIXES = frozenset({
    "nfl", "nba", "wnba", "nhl", "mlb", "cfb", "cbb", "cwbb",
    "epl", "ucl", "uel", "lal", "bun", "sea", "fl1", "mls",
})
T0 = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)
SPLIT = dt.datetime(2026, 10, 17, tzinfo=dt.timezone.utc)
END = dt.datetime(2026, 11, 17, tzinfo=dt.timezone.utc)
DELAYS = (0, 60, 300)
MAX_WAIT_S = 1800
MIN_BETS = 100
MAX_TAPE_PAGES = 30     # a market tape deeper than 30k trades back to the bet is counted unfollowable
BASELINE_SAMPLE = 3000  # unselected test bets followed, a seeded random sample
MAX_PAGES = 10          # 10 x 1000 trades; a wallet that fills them in the window is treated as high-frequency
USER_AGENT = "syndicate-research/1.0"


# ---------------------------------------------------------------------------------------------- pure functions


def sport_of(slug: str | None) -> str | None:
    head = str(slug or "").split("-", 1)[0].lower()
    return head if head in SPORT_PREFIXES else None


@dataclass
class Bet:
    wallet: str
    condition_id: str
    outcome_index: int
    outcome: str
    slug: str
    event: str
    first_ts: int
    shares: float = 0.0
    cost: float = 0.0

    @property
    def price(self) -> float:
        return self.cost / self.shares if self.shares else float("nan")


def bets_from_trades(wallet: str, trades: Iterable[Mapping[str, Any]]) -> tuple[list[Bet], set[str]]:
    """BUYs grouped by (market, outcome): first time, size-weighted price. Also the markets where the wallet bought
    more than one outcome (two-sided: market making, arbitrage or hedging, none of which a follower can copy)."""
    by_key: dict[tuple[str, int], Bet] = {}
    outcomes_by_market: dict[str, set[int]] = defaultdict(set)
    for t in sorted(trades, key=lambda r: int(r.get("timestamp") or 0)):
        if str(t.get("side") or "").upper() != "BUY" or not sport_of(t.get("slug")):
            continue
        try:
            size, price, idx = float(t["size"]), float(t["price"]), int(t["outcome_index"])
        except (KeyError, TypeError, ValueError):
            continue
        if size <= 0 or not 0 < price < 1:
            continue
        cid = str(t.get("condition_id") or "")
        outcomes_by_market[cid].add(idx)
        key = (cid, idx)
        bet = by_key.get(key)
        if bet is None:
            bet = Bet(wallet=wallet, condition_id=cid, outcome_index=idx, outcome=str(t.get("outcome") or ""),
                      slug=str(t.get("slug") or ""), event=str(t.get("event_slug") or t.get("slug") or ""),
                      first_ts=int(t.get("timestamp") or 0))
            by_key[key] = bet
        bet.shares += size
        bet.cost += size * price
    two_sided = {cid for cid, idxs in outcomes_by_market.items() if len(idxs) > 1}
    return list(by_key.values()), two_sided


def settle(outcome_index: int, market: Mapping[str, Any] | None) -> bool | None:
    """True / False when the market resolved 0/1, else None (unresolved, voided or unknown)."""
    if not market or not market.get("closed"):
        return None
    try:
        prices = json.loads(market.get("outcomePrices") or "[]")
        p = float(prices[outcome_index])
    except (ValueError, TypeError, IndexError):
        return None
    if p >= 0.99:
        return True
    if p <= 0.01:
        return False
    return None


def ret_per_dollar(price: float, won: bool) -> float:
    return (1.0 - price) / price if won else -1.0


def follow_price(tape: Sequence[Mapping[str, Any]], outcome_index: int, t: int, delay: int,
                 max_wait: int = MAX_WAIT_S) -> float | None:
    """The first taker BUY of the same outcome at or after t + delay (and within max_wait of t): the price a follower
    reacting after `delay` seconds would have paid. None when nobody bought it in the window."""
    lo, hi = t + delay, t + max_wait
    best = None
    for row in tape:
        try:
            ts, idx, price = int(row["timestamp"]), int(row["outcome_index"]), float(row["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if idx != outcome_index or str(row.get("side") or "").upper() != "BUY" or not lo <= ts <= hi:
            continue
        if not 0 < price < 1:
            continue
        if best is None or ts < best[0]:
            best = (ts, price)
    return None if best is None else best[1]


def clustered(results: Sequence[tuple[str, float]]) -> dict[str, Any]:
    """Mean return per $1 with an event-clustered SE (bets on one event are not independent)."""
    n = len(results)
    if n == 0:
        return {"n": 0, "events": 0, "roi_pct": None, "se_pct": None, "lo95_pct": None}
    mean = sum(r for _, r in results) / n
    by_event: dict[str, float] = defaultdict(float)
    for event, r in results:
        by_event[event] += r - mean
    g = len(by_event)
    var = sum(v * v for v in by_event.values()) / (n * n) * (g / (g - 1) if g > 1 else 1.0)
    se = math.sqrt(var)
    return {"n": n, "events": g, "roi_pct": round(100 * mean, 2), "se_pct": round(100 * se, 2),
            "lo95_pct": round(100 * (mean - 1.96 * se), 2)}


def select_wallets(train: Mapping[str, Sequence[tuple[str, float]]], two_sided: Mapping[str, set],
                   capped: set[str], min_bets: int = MIN_BETS) -> dict[str, dict[str, Any]]:
    """The pre-registered rule: >= min_bets in-sample, lower 95% bound > 0, one-sided, not high-frequency."""
    chosen = {}
    for wallet, results in train.items():
        if wallet in capped or two_sided.get(wallet) or len(results) < min_bets:
            continue
        stats = clustered(results)
        if stats["lo95_pct"] is not None and stats["lo95_pct"] > 0:
            chosen[wallet] = stats
    return chosen


# ---------------------------------------------------------------------------------------------- I/O


class Api:
    def __init__(self, cache_dir: Path, pause: float = 0.04):
        self.cache = cache_dir
        self.cache.mkdir(parents=True, exist_ok=True)
        self.pause = pause
        self.calls = 0

    def get(self, url: str, params: Mapping[str, Any] | Sequence[tuple[str, Any]], cache: bool = True) -> Any:
        query = urllib.parse.urlencode(params, doseq=True)
        full = f"{url}?{query}"
        path = self.cache / (hashlib.sha1(full.encode()).hexdigest() + ".json")
        if cache and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        for attempt in range(5):
            req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=45) as r:
                    body = json.loads(r.read())
                self.calls += 1
                time.sleep(self.pause)
                if cache:
                    path.write_text(json.dumps(body), encoding="utf-8")
                return body
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(float(e.headers.get("Retry-After") or 2 ** attempt))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError):
                time.sleep(2 ** attempt)
        raise RuntimeError(f"gave up: {full}")


def universe(api: Api, size: int) -> list[str]:
    wallets: dict[str, None] = {}
    for period in ("month", "all"):
        for board in ("PNL", "VOLUME"):
            cursor, got = None, 0
            while got < size:
                params = {"time_period": period, "sort_by": board, "category": "sports", "limit": 100}
                if cursor:
                    params = {**params, "cursor": cursor}
                page = api.get(f"{DATA_API}/leaderboard", params)
                rows = page.get("data") or []
                for row in rows:
                    wallets.setdefault(str(row.get("user_id")), None)
                got += len(rows)
                cursor = (page.get("pagination") or {}).get("next_cursor")
                if not rows or not cursor:
                    break
    return [w for w in wallets if w.startswith("0x")]


def wallet_trades(api: Api, wallet: str) -> tuple[list[dict], bool]:
    rows, cursor = [], None
    for _ in range(MAX_PAGES):
        params = {"user": wallet, "start": int(T0.timestamp()), "end": int(END.timestamp()), "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        page = api.get(f"{DATA_API}/trades", params)
        rows.extend(page.get("data") or [])
        cursor = (page.get("pagination") or {}).get("next_cursor")
        if not cursor:
            return rows, False
    return rows, True  # capped: treated as high-frequency


def markets(api: Api, condition_ids: Sequence[str]) -> dict[str, dict]:
    """Resolved markets only. Gamma's `/markets` serves OPEN markets unless `closed=true` is passed, even when
    `condition_ids` names closed ones (measured 2026-11-18: 0 of 40 by default, 40 of 40 with closed=true), and an
    open market cannot settle a bet anyway."""
    out: dict[str, dict] = {}
    ids = sorted(set(condition_ids))
    for i in range(0, len(ids), 40):
        chunk = ids[i:i + 40]
        rows = api.get(f"{GAMMA_API}/markets",
                       [("condition_ids", c) for c in chunk] + [("closed", "true"), ("limit", 100)])
        for m in rows or []:
            out[str(m.get("conditionId") or "").lower()] = m
    return out


def market_tape(api: Api, condition_id: str, since_ts: int) -> tuple[list[dict], bool]:
    """A market's taker trades back to `since_ts`. The condition shape ignores start/end (honored on the `user`
    shape only) and serves newest first, so page back until a page reaches `since_ts`. Returns (rows, reached)."""
    rows, cursor = [], None
    for _ in range(MAX_TAPE_PAGES):
        params = {"condition": condition_id, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        page = api.get(f"{DATA_API}/trades", params)
        data = page.get("data") or []
        rows.extend(data)
        cursor = (page.get("pagination") or {}).get("next_cursor")
        oldest = min((int(r.get("timestamp") or 0) for r in data), default=0)
        if not data or not cursor or oldest <= since_ts:
            return rows, (not data) or oldest <= since_ts or not cursor
    return rows, False


# ---------------------------------------------------------------------------------------------- the run


def run(cache_dir: Path, universe_size: int, out_dir: Path) -> dict[str, Any]:
    api = Api(cache_dir)
    counts: dict[str, Any] = {}
    wallets = universe(api, universe_size)
    counts["universe_wallets"] = len(wallets)
    all_bets: dict[str, list[Bet]] = {}
    two_sided: dict[str, set] = {}
    capped: set[str] = set()
    for i, w in enumerate(wallets):
        trades, was_capped = wallet_trades(api, w)
        if was_capped:
            capped.add(w)
        bets, ts = bets_from_trades(w, trades)
        all_bets[w], two_sided[w] = bets, ts
        if (i + 1) % 50 == 0:
            print(f"  wallets {i + 1}/{len(wallets)} (api calls {api.calls})", flush=True)
    counts["capped_high_frequency"] = len(capped)
    counts["two_sided_wallets"] = sum(1 for v in two_sided.values() if v)
    flat = [b for bets in all_bets.values() for b in bets]
    counts["sport_bets"] = len(flat)
    meta = markets(api, [b.condition_id for b in flat])
    counts["markets"] = len(meta)

    train: dict[str, list[tuple[str, float]]] = defaultdict(list)
    test_bets: list[tuple[Bet, bool]] = []
    for b in flat:
        won = settle(b.outcome_index, meta.get(b.condition_id.lower()))
        if won is None:
            continue
        when = dt.datetime.fromtimestamp(b.first_ts, dt.timezone.utc)
        if when < SPLIT:
            train[b.wallet].append((b.event, ret_per_dollar(b.price, won)))
        elif when < END:
            test_bets.append((b, won))
    counts["resolved_train_bets"] = sum(len(v) for v in train.values())
    counts["resolved_test_bets"] = len(test_bets)
    chosen = select_wallets(train, two_sided, capped)
    counts["selected_wallets"] = len(chosen)

    results: dict[str, dict[str, list[tuple[str, float]]]] = {"selected": defaultdict(list), "baseline": defaultdict(list)}
    no_follow: dict[str, dict[int, int]] = {"selected": defaultdict(int), "baseline": defaultdict(int)}
    # Every selected bet is followed; the unselected baseline is a seeded random sample (an unbiased read of "follow
    # anyone on the board" at bounded API cost). The baseline's at-own-price ROI uses all its test bets.
    rng = random.Random(20261117)
    baseline_sample = set(rng.sample(range(len(test_bets)), min(BASELINE_SAMPLE, len(test_bets))))
    need: dict[str, int] = {}
    for i, (b, _won) in enumerate(test_bets):
        if b.wallet in chosen or i in baseline_sample:
            need[b.condition_id] = min(need.get(b.condition_id, b.first_ts), b.first_ts)
    tapes: dict[str, tuple[list[dict], bool]] = {}
    for j, (cid, since) in enumerate(sorted(need.items())):
        tapes[cid] = market_tape(api, cid, since - 60)
        if (j + 1) % 200 == 0:
            print(f"  tapes {j + 1}/{len(need)} (api calls {api.calls})", flush=True)
    counts["tapes"] = len(tapes)
    counts["tapes_not_reached"] = sum(1 for _rows, ok in tapes.values() if not ok)
    for i, (b, won) in enumerate(test_bets):
        follow_groups = (["selected"] if b.wallet in chosen else []) + (["baseline"] if i in baseline_sample else [])
        results["baseline"]["own"].append((b.event, ret_per_dollar(b.price, won)))
        if b.wallet in chosen:
            results["selected"]["own"].append((b.event, ret_per_dollar(b.price, won)))
        if not follow_groups:
            continue
        tape, _reached = tapes.get(b.condition_id, ([], False))
        for delay in DELAYS:
            p = follow_price(tape, b.outcome_index, b.first_ts, delay)
            for g in follow_groups:
                if p is None:
                    no_follow[g][delay] += 1
                else:
                    results[g][f"{delay}s"].append((b.event, ret_per_dollar(p, won)))
    counts["baseline_followed_sample"] = len(baseline_sample)
    counts["api_calls"] = api.calls

    summary = {
        "counts": counts,
        "window": {"t0": T0.date().isoformat(), "split": SPLIT.date().isoformat(), "end": END.date().isoformat()},
        "rule": {"min_bets": MIN_BETS, "delays_s": list(DELAYS), "max_wait_s": MAX_WAIT_S},
        "selected": {k: clustered(v) for k, v in results["selected"].items()},
        "baseline": {k: clustered(v) for k, v in results["baseline"].items()},
        "unfollowable": {g: dict(v) for g, v in no_follow.items()},
        "selected_wallets": chosen,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--cache-dir", default=r"C:\tmp\pfmon\trader_study\cache")
    ap.add_argument("--out-dir", default=r"C:\tmp\pfmon\trader_study")
    ap.add_argument("--universe", type=int, default=300, help="wallets per leaderboard board (4 boards, de-duplicated)")
    args = ap.parse_args(argv)
    s = run(Path(args.cache_dir), args.universe, Path(args.out_dir))
    print(json.dumps({k: s[k] for k in ("counts", "selected", "baseline", "unfollowable")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
