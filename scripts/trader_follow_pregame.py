"""Read-only research: does FOLLOWING selected Polymarket sports traders on PREGAME bets pay? (lane trader-following-pregame-study)

The rerun of `trader_follow_study.py` (lane trader-following-study, CLOSED). That study's selection rule picked late-game
"certainty buyers" (entry p50 0.999, 282 of 289 buys after kickoff), and its follow price was the next taker buy, which
conditions on a later trade existing (a look-ahead). This version, pre-registered in the lane before any data was
pulled (`788e08fa2`), changes exactly those things:

  * A QUALIFYING BUY is a BUY on one of our sports, entry price 0.10-0.90 (`PRICE_LO`..`PRICE_HI`), placed BEFORE the
    market's gamma `gameStartTime`. A BET folds one wallet's qualifying buys of one market outcome (size-weighted;
    first time = first qualifying buy). Two-sided wallets are still judged on ALL their sports buys.
  * The FOLLOW PRICE at delay d is the CLOB `prices-history` midpoint (fidelity 1 min) of the bought outcome's token:
    the latest point at or before first_time + d, no older than `MAX_STALE_S`, plus `TAKER_COST` (a stand-in for half
    the spread). Unfollowable when there is no such point, when first_time + d is at or after the game start (the
    follow must still be pregame), or when the price is outside (0, 1). Nothing after first_time + d is read.
  * Universe, windows, selection rule, delays and the seeded baseline are the first study's.

VERDICT (pre-registered): NO-GO if 0 wallets are selected; NO-GO if the selected 60 s lower 95% bound is <= 0 or the
selected 60 s ROI is not above the baseline's 60 s ROI; otherwise GO for a paper shadow only. Gross of venue fees.

Usage:  py -3 scripts/trader_follow_pregame.py [--cache-dir C:\\tmp\\pfmon\\trader_study\\cache] [--universe 300]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trader_follow_study as tf  # noqa: E402  (the closed study's tested helpers, reused unchanged)

CLOB_API = "https://clob.polymarket.com"
PRICE_LO, PRICE_HI = 0.10, 0.90
TAKER_COST = 0.01
MAX_STALE_S = 300
DELAYS = (0, 60, 300)
REGISTERED_DELAY = 60
BASELINE_SAMPLE = 3000
BASELINE_SEED = 20261118
HISTORY_BEFORE_S = 600          # one prices-history call per bet covers [first - 600 s, first + 300 s + 60 s]


# ---------------------------------------------------------------------------------------------- pure functions


def parse_start(market: Mapping[str, Any] | None) -> int | None:
    """gamma `gameStartTime` ("2026-08-20 01:30:00+00", sometimes ISO with T/Z) as epoch seconds, else None."""
    raw = str((market or {}).get("gameStartTime") or "").strip()
    if not raw:
        return None
    text = raw.replace("T", " ").replace("Z", "+00:00")
    if text.endswith("+00"):
        text += ":00"
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return int(when.timestamp())


def token_for(market: Mapping[str, Any] | None, outcome_index: int) -> str | None:
    try:
        tokens = json.loads((market or {}).get("clobTokenIds") or "[]")
        return str(tokens[outcome_index])
    except (ValueError, TypeError, IndexError):
        return None


def qualifies(trade: Mapping[str, Any], start_ts: int | None) -> bool:
    """A pregame, in-band BUY on one of our sports."""
    if str(trade.get("side") or "").upper() != "BUY" or not tf.sport_of(trade.get("slug")) or start_ts is None:
        return False
    try:
        price, size, ts = float(trade["price"]), float(trade["size"]), int(trade["timestamp"])
    except (KeyError, TypeError, ValueError):
        return False
    return size > 0 and PRICE_LO <= price <= PRICE_HI and ts < start_ts


def pregame_bets(wallet: str, trades: Iterable[Mapping[str, Any]],
                 starts: Mapping[str, int | None]) -> list[tf.Bet]:
    """Qualifying buys folded per (market, outcome), size-weighted, first time = first qualifying buy."""
    by_key: dict[tuple[str, int], tf.Bet] = {}
    for t in sorted(trades, key=lambda r: int(r.get("timestamp") or 0)):
        cid = str(t.get("condition_id") or "")
        if not qualifies(t, starts.get(cid.lower())):
            continue
        idx = int(t["outcome_index"])
        bet = by_key.get((cid, idx))
        if bet is None:
            bet = tf.Bet(wallet=wallet, condition_id=cid, outcome_index=idx, outcome=str(t.get("outcome") or ""),
                         slug=str(t.get("slug") or ""), event=str(t.get("event_slug") or t.get("slug") or ""),
                         first_ts=int(t["timestamp"]))
            by_key[(cid, idx)] = bet
        bet.shares += float(t["size"])
        bet.cost += float(t["size"]) * float(t["price"])
    return list(by_key.values())


def book_follow_price(history: Sequence[Mapping[str, Any]], first_ts: int, delay: int, start_ts: int,
                      max_stale: int = MAX_STALE_S, cost: float = TAKER_COST) -> float | None:
    """The midpoint a follower sees at first_ts + delay (latest point at or before it, at most `max_stale` old), plus
    the taker cost. Reads nothing after first_ts + delay. None when unfollowable."""
    target = first_ts + delay
    if target >= start_ts:
        return None
    best = None
    for point in history:
        try:
            pt, p = int(point["t"]), float(point["p"])
        except (KeyError, TypeError, ValueError):
            continue
        if pt <= target and (best is None or pt > best[0]):
            best = (pt, p)
    if best is None or target - best[0] > max_stale:
        return None
    price = best[1] + cost
    return price if 0 < price < 1 else None


def quantiles(values: Sequence[float], qs: Sequence[float] = (0.1, 0.5, 0.9)) -> list[float] | None:
    v = sorted(values)
    if not v:
        return None
    return [round(v[min(len(v) - 1, int(q * len(v)))], 3) for q in qs]


def verdict(selected: Mapping[str, Any], baseline: Mapping[str, Any], n_selected: int) -> dict[str, Any]:
    """The pre-registered rule, applied mechanically."""
    key = f"{REGISTERED_DELAY}s"
    s, b = selected.get(key) or {}, baseline.get(key) or {}
    if n_selected == 0:
        return {"verdict": "NO-GO", "reason": "0 wallets selected"}
    if s.get("lo95_pct") is None or s["lo95_pct"] <= 0:
        return {"verdict": "NO-GO", "reason": f"selected {key} lower 95% {s.get('lo95_pct')} <= 0"}
    if b.get("roi_pct") is not None and s["roi_pct"] <= b["roi_pct"]:
        return {"verdict": "NO-GO", "reason": f"selected {key} ROI {s['roi_pct']} not above baseline {b['roi_pct']}"}
    return {"verdict": "GO (paper shadow only)", "reason": f"selected {key} ROI {s['roi_pct']}, lower 95% "
                                                           f"{s['lo95_pct']} > 0, above baseline {b.get('roi_pct')}"}


# ---------------------------------------------------------------------------------------------- I/O


def price_history(api: tf.Api, token: str, first_ts: int) -> list[dict]:
    body = api.get(f"{CLOB_API}/prices-history",
                   {"market": token, "startTs": first_ts - HISTORY_BEFORE_S, "endTs": first_ts + max(DELAYS) + 60,
                    "fidelity": 1})
    return list((body or {}).get("history") or []) if isinstance(body, dict) else list(body or [])


# ---------------------------------------------------------------------------------------------- the run


def run(cache_dir: Path, universe_size: int, out_dir: Path) -> dict[str, Any]:
    api = tf.Api(cache_dir)
    counts: dict[str, Any] = {}
    wallets = tf.universe(api, universe_size)
    counts["universe_wallets"] = len(wallets)
    compact: dict[str, list[dict]] = {}
    two_sided: dict[str, set] = {}
    capped: set[str] = set()
    all_cids: list[str] = []
    for i, w in enumerate(wallets):
        trades, was_capped = tf.wallet_trades(api, w)
        if was_capped:
            capped.add(w)
        all_bets, ts_set = tf.bets_from_trades(w, trades)      # two-sided on ALL sports buys, as registered
        two_sided[w] = ts_set
        all_cids.extend(b.condition_id for b in all_bets)       # the first study's market set: its meta is cached
        compact[w] = [{k: t.get(k) for k in ("side", "slug", "event_slug", "condition_id", "outcome_index", "outcome",
                                               "price", "size", "timestamp")}
                      for t in trades if str(t.get("side") or "").upper() == "BUY" and tf.sport_of(t.get("slug"))
                      and t.get("price") is not None and PRICE_LO <= float(t["price"]) <= PRICE_HI]
        if (i + 1) % 100 == 0:
            print(f"  wallets {i + 1}/{len(wallets)} (api calls {api.calls})", flush=True)
    counts["capped_high_frequency"] = len(capped)
    counts["two_sided_wallets"] = sum(1 for v in two_sided.values() if v)
    counts["in_band_sports_buys"] = sum(len(v) for v in compact.values())
    meta = tf.markets(api, all_cids)
    counts["resolved_markets"] = len(meta)
    starts = {cid: parse_start(m) for cid, m in meta.items()}
    counts["resolved_markets_with_start"] = sum(1 for v in starts.values() if v)

    train: dict[str, list[tuple[str, float]]] = defaultdict(list)
    test_bets: list[tuple[tf.Bet, bool]] = []
    n_bets = 0
    for w, trades in compact.items():
        for b in pregame_bets(w, trades, starts):
            n_bets += 1
            won = tf.settle(b.outcome_index, meta.get(b.condition_id.lower()))
            if won is None:
                continue
            when = dt.datetime.fromtimestamp(b.first_ts, dt.timezone.utc)
            if when < tf.SPLIT:
                train[w].append((b.event, tf.ret_per_dollar(b.price, won)))
            elif when < tf.END:
                test_bets.append((b, won))
    counts["pregame_bets"] = n_bets
    counts["resolved_train_bets"] = sum(len(v) for v in train.values())
    counts["resolved_test_bets"] = len(test_bets)
    counts["wallets_with_100_train_bets"] = sum(1 for v in train.values() if len(v) >= tf.MIN_BETS)
    chosen = tf.select_wallets(train, two_sided, capped)
    counts["selected_wallets"] = len(chosen)
    print(f"  selected {len(chosen)} of {len(train)} wallets with resolved in-sample bets", flush=True)

    rng = random.Random(BASELINE_SEED)
    sample = set(rng.sample(range(len(test_bets)), min(BASELINE_SAMPLE, len(test_bets))))
    results = {g: defaultdict(list) for g in ("selected", "baseline")}
    unfollowable = {g: defaultdict(int) for g in ("selected", "baseline")}
    subset_own = {g: defaultdict(list) for g in ("selected", "baseline")}   # exploratory: own price on followable
    diag = {"selected_entry": [], "selected_min_before": [], "baseline_entry": [], "baseline_min_before": []}
    fetched = 0
    for i, (b, won) in enumerate(test_bets):
        groups = (["selected"] if b.wallet in chosen else []) + (["baseline"] if i in sample else [])
        own = (b.event, tf.ret_per_dollar(b.price, won))
        results["baseline"]["own_all"].append(own)
        if b.wallet in chosen:
            results["selected"]["own_all"].append(own)
        if not groups:
            continue
        m = meta.get(b.condition_id.lower())
        start, token = starts.get(b.condition_id.lower()), token_for(m, b.outcome_index)
        for g in groups:
            results[g]["own"].append(own)
            diag[f"{g}_entry"].append(b.price)
            diag[f"{g}_min_before"].append((start - b.first_ts) / 60.0)
        history = price_history(api, token, b.first_ts) if token else []
        fetched += 1
        if fetched % 250 == 0:
            print(f"  price histories {fetched} (api calls {api.calls})", flush=True)
        for delay in DELAYS:
            p = book_follow_price(history, b.first_ts, delay, start) if start else None
            for g in groups:
                if p is None:
                    unfollowable[g][delay] += 1
                else:
                    results[g][f"{delay}s"].append((b.event, tf.ret_per_dollar(p, won)))
                    subset_own[g][f"{delay}s"].append(own)
    counts["price_histories"] = fetched
    counts["baseline_sample"] = len(sample)
    counts["api_calls"] = api.calls

    selected = {k: tf.clustered(v) for k, v in results["selected"].items()}
    baseline = {k: tf.clustered(v) for k, v in results["baseline"].items()}
    summary = {
        "counts": counts,
        "rule": {"price_band": [PRICE_LO, PRICE_HI], "taker_cost": TAKER_COST, "max_stale_s": MAX_STALE_S,
                 "delays_s": list(DELAYS), "registered_delay_s": REGISTERED_DELAY, "min_bets": tf.MIN_BETS,
                 "baseline_seed": BASELINE_SEED},
        "window": {"t0": tf.T0.date().isoformat(), "split": tf.SPLIT.date().isoformat(), "end": tf.END.date().isoformat()},
        "selected": selected,
        "baseline": baseline,
        "verdict": verdict(selected, baseline, len(chosen)),
        "unfollowable": {g: dict(v) for g, v in unfollowable.items()},
        "exploratory_own_price_on_followable": {g: {k: tf.clustered(v) for k, v in d.items()}
                                                for g, d in subset_own.items()},
        "diagnostics": {k: quantiles(v) for k, v in diag.items()},
        "selected_wallets": chosen,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--cache-dir", default=r"C:\tmp\pfmon\trader_study\cache")
    ap.add_argument("--out-dir", default=r"C:\tmp\pfmon\trader_study\pregame")
    ap.add_argument("--universe", type=int, default=300, help="wallets per leaderboard board (4 boards, de-duplicated)")
    args = ap.parse_args(argv)
    s = run(Path(args.cache_dir), args.universe, Path(args.out_dir))
    print(json.dumps({k: s[k] for k in ("counts", "verdict", "selected", "baseline", "unfollowable")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
