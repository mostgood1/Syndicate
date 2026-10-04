"""Measure forward: do Kalshi NFL prop asks that beat the sportsbook consensus at quote time earn it?

Lane `nfl-kalshi-forward-clv` (2026-10-03). Measurement only.

WHY. Lane `nfl-off-market-edge` showed consensus-fair edges are NOT earned at the CLOSE (2023-25: props
+0.30% realized on +1.88% claimed). If price shopping pays, it pays through TIMING: taking a price before
the market moves to it. The fleet has captured Kalshi's own asks for NFL props since 2026-09-30
(`tracking/book_quotes/*.jsonl[.gz]`, `bookmaker=kalshi`, `source=venue_direct`), next to 4-8
sportsbooks, snapshot by snapshot.

FOR EACH KALSHI ASK (prop, pregame):
  * liquid only: implied in [0.05, 0.95], and when the other side was quoted in the same snapshot, the
    two asks' implied sum <= 1.15 (empty-book asks like -1567/-4900 excluded and counted);
  * entry fair = production `consensus_fair_probability` over the sportsbooks' latest two-sided quotes
    on the same (game, market, player, line) within LOOKBACK before the ask (>= 3 books);
  * fee = production `venue_fees.taker_fee_per_contract("kalshi", p, sport="nfl", market=...)` (NFL prop
    series are unmapped, so it is charged at the full rate and flagged an upper bound: conservative);
  * entry EV (fee-net) = fair / (p + fee) - 1;
  * close fair = the same consensus from the latest quotes within LOOKBACK before kickoff;
  * fee-net CLV = close fair / (p + fee) - 1.
BET RULE: per (line, side), the FIRST snapshot whose fee-net entry EV > 0, at least 5 min before kickoff,
i.e. the first moment the platform could have acted. CONTROL: per (line, side), the first liquid ask
regardless of EV. Optional realized grading with production's player identity path, where pbp has the
game.

Usage:
  py -3 scripts/measure_nfl_kalshi_forward_clv.py --quotes-dir C:/tmp/nflbt/kalshi_quotes \\
      --root C:/tmp/nflbt/root/nfl_source --out C:/tmp/nflbt/kalshi_clv [--grade]
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import statistics
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("bt_lines_props", REPO / "scripts" / "backtest_nfl_lines_props.py")
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)  # type: ignore[union-attr]

# Sportsbook capture is SLOW: median 54 min to the freshest prior pair, p90 6.6 h (measured on the
# 2026-10-03 copy). A 90-min window rejected 2,098 of 2,691 asks, so the window is 6 h and every row
# records the age of the oldest quote its consensus used; CLV is reported split by that age.
LOOKBACK = timedelta(hours=6)
FRESH_MIN = 90
MIN_LEAD = timedelta(minutes=5)
MIN_BOOKS = 3
EXCHANGES = {"kalshi", "polymarket"}


def ts(s: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def norm_name(n: Any) -> str:
    from syndicate.features.nfl.props import _normalized_player_name
    return _normalized_player_name(n)


def load_quotes(qdir: Path) -> List[Dict[str, Any]]:
    out = []
    for f in sorted(glob.glob(str(qdir / "*.jsonl"))) + sorted(glob.glob(str(qdir / "*.jsonl.gz"))):
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    q = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if q.get("sport") == "nfl" and q.get("kind") == "prop" and (q.get("segment") or "full") == "full":
                    out.append(q)
    return out


def key_of(q: Dict[str, Any]) -> Tuple:
    return (q.get("home_team"), q.get("commence_time"), q.get("market"), norm_name(q.get("player_name")),
            float(q["line"]) if q.get("line") is not None else None)


PAIR_TOLERANCE = timedelta(seconds=120)


class BookIndex:
    """Per line key, book and side: (time, price) sorted by time.

    SIDES ARE PAIRED BY TIME, NOT BY IDENTICAL TIMESTAMP. The ledger writes a book's over and under a
    second or so apart (23:08:06 / 23:08:07), so the first version, which required both sides at the
    same snapshot_ts, found an entry consensus for 593 of 2,691 Kalshi asks while all 266 line keys
    joined. A book's pair is its latest over and latest under within LOOKBACK of `at`, no more than
    PAIR_TOLERANCE apart."""

    def __init__(self, quotes: List[Dict[str, Any]]) -> None:
        idx: Dict[Tuple, Dict[str, Dict[str, List[Tuple[datetime, Any]]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for q in quotes:
            if q.get("bookmaker") in EXCHANGES:
                continue
            t = ts(q.get("snapshot_ts") or q.get("captured_at"))
            if t is None or q.get("line") is None or q.get("selection") not in ("over", "under"):
                continue
            idx[key_of(q)][q["bookmaker"]][q["selection"]].append((t, q["price"]))
        for books in idx.values():
            for sides in books.values():
                for v in sides.values():
                    v.sort(key=lambda x: x[0])
        self.idx = idx

    @staticmethod
    def _latest(v: List[Tuple[datetime, Any]], at: datetime) -> Optional[Tuple[datetime, Any]]:
        i = bisect_right([t for t, _ in v], at) - 1
        return v[i] if i >= 0 and v[i][0] >= at - LOOKBACK else None

    def consensus(self, key: Tuple, at: datetime) -> Tuple[Optional[Dict[str, float]], int, Optional[float]]:
        """(fair by side, books used, age in minutes of the OLDEST quote used)."""
        from syndicate.features.shared.opportunity_signals import consensus_fair_probability
        books = self.idx.get(key)
        if not books:
            return None, 0, None
        pool: Dict[str, Dict[str, Any]] = {}
        oldest: Optional[datetime] = None
        for b, sides in books.items():
            o, u = self._latest(sides.get("over", []), at), self._latest(sides.get("under", []), at)
            if o and u and abs((o[0] - u[0]).total_seconds()) <= PAIR_TOLERANCE.total_seconds():
                pool[b] = {"over": o[1], "under": u[1]}
                first = min(o[0], u[0])
                oldest = first if oldest is None or first < oldest else oldest
        if len(pool) < MIN_BOOKS:
            return None, len(pool), None
        return consensus_fair_probability(pool), len(pool), round((at - oldest).total_seconds() / 60, 1)


def measure(quotes: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Counter]:
    from syndicate.features.shared.opportunity_signals import implied_probability
    from syndicate.features.shared.venue_fees import taker_fee_per_contract
    idx = BookIndex(quotes)
    drops = Counter()
    kal = [q for q in quotes if q.get("bookmaker") == "kalshi"]
    drops["kalshi_quotes"] = len(kal)
    by_snap: Dict[Tuple, Dict[str, Any]] = defaultdict(dict)
    for q in kal:
        by_snap[(key_of(q), q.get("snapshot_ts"))][q["selection"]] = q["price"]
    seen_bet, seen_ctl = set(), set()
    bets, ctl = [], []
    for q in sorted(kal, key=lambda x: str(x.get("snapshot_ts"))):
        k, side = key_of(q), q.get("selection")
        t, ko = ts(q.get("snapshot_ts")), ts(q.get("commence_time"))
        if t is None or ko is None or side not in ("over", "under") or k[4] is None:
            drops["unparseable"] += 1
            continue
        if t > ko - MIN_LEAD:
            drops["not_pregame"] += 1
            continue
        p = implied_probability(q["price"])
        if p is None or not (0.05 <= p <= 0.95):
            drops["illiquid_price"] += 1
            continue
        other = by_snap[(k, q.get("snapshot_ts"))].get("under" if side == "over" else "over")
        po = implied_probability(other) if other is not None else None
        if po is not None and p + po > 1.15:
            drops["illiquid_pair"] += 1
            continue
        fair_e, nb_e, age_e = idx.consensus(k, t)
        if not fair_e or side not in fair_e:
            drops["no_entry_consensus"] += 1
            continue
        fee, basis, upper = taker_fee_per_contract("kalshi", p, sport="nfl", market=q.get("market"))
        ev = fair_e[side] / (p + fee) - 1.0
        row = {"gid": f"{k[0]}|{k[1]}", "key": list(map(str, k)), "side": side, "t": q["snapshot_ts"], "ko": q["commence_time"],
               "lead_min": round((ko - t).total_seconds() / 60, 1), "p": p, "fee": fee, "fee_basis": basis, "fee_upper": upper,
               "fair_entry": fair_e[side], "books_entry": nb_e, "entry_consensus_age_min": age_e, "ev_entry": ev, "market": q.get("market"),
               "player": q.get("player_name"), "line": k[4]}
        fair_c, nb_c, age_c = idx.consensus(k, ko)
        if fair_c and side in fair_c:
            row.update({"fair_close": fair_c[side], "books_close": nb_c, "close_consensus_age_min": age_c,
                        "clv": fair_c[side] / (p + fee) - 1.0})
        if (k, side) not in seen_ctl:
            seen_ctl.add((k, side))
            ctl.append(row)
        if ev > 0 and (k, side) not in seen_bet:
            seen_bet.add((k, side))
            bets.append(row)
    return bets, ctl, drops


def grade(rows: List[Dict[str, Any]], root: Path, drops: Counter) -> None:
    """Realized outcome via production's identity path, where pbp holds the game (in place)."""
    bt._patch_game_log_cache()
    from syndicate.features.nfl import player_stats as ps
    from syndicate.features.nfl import props as P
    from syndicate.features.shared.team_aliases import canonical_team
    sched = bt.load_schedule(root)
    idx = defaultdict(list)
    for g in sched.values():
        idx[canonical_team("nfl", g["home_team"])].append(g)
    for r in rows:
        home, ko = r["key"][0], ts(r["ko"])
        g = next((g for g in idx.get(canonical_team("nfl", home), [])
                  if abs((datetime.fromisoformat(g["gameday"]).date() - ko.date()).days) <= 1), None)
        if g is None or not g["completed"]:
            drops["grade_game_not_completed"] += 1
            continue
        stat = P._NFL_PROP_MARKET_TO_STAT.get(r["market"])
        pid, _ = ps.resolve_player_id_with_prior(g["season_i"], r["player"])
        if stat is None or pid is None:
            drops["grade_unresolved"] += 1
            continue
        a = ps.final_stat_value(g["season_i"], g["game_id"], pid, stat)
        if a is None:
            drops["grade_no_pbp_line"] += 1
            continue
        line = float(r["line"])
        if a == line:
            drops["grade_push"] += 1
            continue
        won = (a > line) if r["side"] == "over" else (a < line)
        r["won"] = won
        r["pnl"] = (1.0 / (r["p"] + r["fee"]) - 1.0) if won else -1.0   # per $1 risked, fee included


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"n": 0}
    out: Dict[str, Any] = {"n": len(rows), "games": len({r["gid"] for r in rows}),
                           "mean_ev_entry_pct": round(100 * statistics.fmean(r["ev_entry"] for r in rows), 3),
                           "median_lead_min": statistics.median(r["lead_min"] for r in rows),
                           "fee_upper_bound_share": round(statistics.fmean(1.0 if r["fee_upper"] else 0.0 for r in rows), 3)}
    c = [r for r in rows if "clv" in r]
    out["n_with_close"] = len(c)
    if c:
        m = bt.boot_ci([(r["gid"], r["clv"]) for r in c])
        out["mean_clv_feenet_pct"] = round(100 * m[0], 3)
        out["clv_ci95_pct"] = [round(100 * m[1], 3), round(100 * m[2], 3)]
        out["share_clv_positive"] = round(statistics.fmean(1.0 if r["clv"] > 0 else 0.0 for r in c), 3)
        xs, ys = [r["ev_entry"] for r in c], [r["clv"] for r in c]
        if len(c) >= 30:
            mx, my = statistics.fmean(xs), statistics.fmean(ys)
            sxx = sum((x - mx) ** 2 for x in xs)
            out["slope_clv_on_entry_ev"] = round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx, 3) if sxx else None
    g = [r for r in rows if "pnl" in r]
    out["n_graded"] = len(g)
    if g:
        m = bt.boot_ci([(r["gid"], r["pnl"]) for r in g])
        out["realized_roi_pct"] = round(100 * m[0], 3)
        out["realized_roi_ci95_pct"] = [round(100 * m[1], 3), round(100 * m[2], 3)]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quotes-dir", type=Path, required=True)
    ap.add_argument("--root", type=Path, required=True, help="nfl_source root (for --grade: schedule + pbp)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--grade", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    env = bt.configure_env(a.root.resolve())
    quotes = load_quotes(a.quotes_dir)
    bets, ctl, drops = measure(quotes)
    if a.grade:
        grade(bets, a.root.resolve(), drops)
        grade(ctl, a.root.resolve(), Counter())
    rep = {"generated_at": datetime.now(timezone.utc).isoformat(), "env": env, "drops": dict(drops),
           "n_quotes_loaded": len(quotes),
           "kalshi_commence_dates": dict(Counter(q["commence_time"][:10] for q in quotes if q.get("bookmaker") == "kalshi")),
           "bets_positive_entry_ev": summarize(bets), "control_first_sighting": summarize(ctl),
           "bets_entry_consensus_fresh": summarize([r for r in bets if (r["entry_consensus_age_min"] or 1e9) <= FRESH_MIN]),
           "bets_entry_consensus_older": summarize([r for r in bets if (r["entry_consensus_age_min"] or 1e9) > FRESH_MIN]),
           "bets_by_market": {m: summarize([r for r in bets if r["market"] == m]) for m in sorted({r["market"] for r in bets})},
           "bets_by_entry_ev_band": {f"{lo}-{hi}%": summarize([r for r in bets if lo <= 100 * r["ev_entry"] < hi])
                                     for lo, hi in ((0, 2), (2, 5), (5, 10), (10, 1000))}}
    (a.out / "nfl_kalshi_forward_clv.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    (a.out / "bets.jsonl").write_text("\n".join(json.dumps(r, default=str) for r in bets), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("drops", "bets_positive_entry_ev", "control_first_sighting")}, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
