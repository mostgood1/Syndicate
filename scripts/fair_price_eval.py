"""Which FAIR PRICE is closest to the truth?  Score de-vig methods against outcomes, from the quote logs.

Lane `fair-price-v2` (2026-10-13). The board's fair (`layer2_board._resolve_fair`, consensus chain) is the MEDIAN of
per-book MULTIPLICATIVE de-vigs. Measured on the 2026-10-10/11 weekend (18,814 pregame lines,
`findings_2026-10-13_layer2_edge_deep_dive.md` §2a) a POWER de-vig was better calibrated (Brier 0.22391 vs 0.22431)
and the multiplicative fair over-rated longshots (0.0-0.1 bucket: fair 6.9% vs hit 3.2%). One weekend decides
nothing; this script is the repeatable measurement the lane's FLIP CRITERION is read from.

INPUTS
  --graded    graded rows from `score_ranking_backtest.py pull` (each: game "sport|event_id", market, segment, side,
              line, player, px, t, y, pnl). Pregame rows only are scored.
  --data-root the fleet data root; quotes are `<root>/<sport>_source/tracking/book_quotes/<YYYY-MM-DD>.jsonl[.gz]`,
              one row per (event, book, market, selection, line) price CHANGE.

WHAT IS SCORED
  For each graded line and each METHOD, the fair probability of the row's side from every book's latest quote at or
  before the row's sighting time `t` (quotes older than --max-age-h dropped), and again at the CLOSE (each book's last
  quote before commence, dropped if older than --max-stale-h). Methods:
    mult        per-book multiplicative de-vig, median across books  (TODAY'S BOARD)
    power       per-book power de-vig (fair_i = imp_i ** k, sum 1), median
    shin        per-book Shin de-vig, median
    power_dedup power, with books that share an origination feed collapsed to one vote (clusters below)
  A book needs every outcome of the market quoted (both sides; three for a soccer 1X2) and a hold in [0.90, 1.35].

  Shared feeds are DETECTED, not assumed: two books whose last pregame prices are identical on >= --dup-threshold of
  the line-sides both quote are one cluster (union-find).

OUTPUT (JSON to --out, summary to stdout)
  per method x {sighting, close}: n, log loss, Brier, calibration intercept/slope (logistic of y on logit(p));
  paired differences vs `mult` with 95% CIs bootstrapped over GAMES; the same by sport, by kind (game/prop) and by
  price bucket; and the selection test -- rows at EV >= 2 by each method at sighting, valued at the POWER close and
  by realized ROI.

Read-only. Run where the quote logs live (the fleet: inside WSL with SYNDICATE_DATA_ROOT, at low priority):
    nice -n 19 python3 scripts/fair_price_eval.py --graded graded.jsonl --data-root ~/syndicate-prod/data --out eval.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import random
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

METHODS = ("mult", "power", "shin", "power_dedup")
_EVENT_RE = re.compile(r'"event_id"\s*:\s*"([^"]*)"')


# ----------------------------------------------------------------------------- de-vig


def implied(price: Any) -> float | None:
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if p == 0 or p != p:
        return None
    return 100.0 / (p + 100.0) if p > 0 else -p / (-p + 100.0)


def decimal_odds(price: Any) -> float | None:
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if p == 0:
        return None
    return 1.0 + p / 100.0 if p > 0 else 1.0 + 100.0 / -p


def devig_mult(imps: Mapping[str, float]) -> dict[str, float]:
    total = sum(imps.values())
    return {k: v / total for k, v in imps.items()}


def devig_power(imps: Mapping[str, float]) -> dict[str, float]:
    """fair_i = imp_i ** k with sum 1. k > 1 when the book is overround (removes more from longshots)."""
    lo, hi = 0.2, 5.0
    for _ in range(80):
        k = (lo + hi) / 2.0
        if sum(v ** k for v in imps.values()) > 1.0:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2.0
    out = {s: v ** k for s, v in imps.items()}
    total = sum(out.values())
    return {s: v / total for s, v in out.items()}


def devig_shin(imps: Mapping[str, float]) -> dict[str, float]:
    """Shin (1993): insider-trading share z solved so the implied fairs sum to 1."""
    total = sum(imps.values())
    if total <= 1.0:
        return devig_mult(imps)

    def fairs(z: float) -> dict[str, float]:
        return {
            s: (math.sqrt(z * z + 4.0 * (1.0 - z) * (q * q) / total) - z) / (2.0 * (1.0 - z))
            for s, q in imps.items()
        }

    lo, hi = 0.0, 0.4
    for _ in range(80):
        z = (lo + hi) / 2.0
        if sum(fairs(z).values()) > 1.0:
            lo = z
        else:
            hi = z
    out = fairs((lo + hi) / 2.0)
    t = sum(out.values())
    return {s: v / t for s, v in out.items()}


_DEVIG = {"mult": devig_mult, "power": devig_power, "shin": devig_shin, "power_dedup": devig_power}


# ----------------------------------------------------------------------------- identity


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def group_key(event: Any, market: Any, segment: Any, player: Any, side: Any, line: Any) -> tuple:
    """Both sides of one bet share a key; spreads are framed on the HOME line."""
    m = str(market or "").strip().lower()
    seg = str(segment or "full").strip().lower() or "full"
    pl = str(player or "").strip().casefold()
    sd = str(side or "").strip().lower()
    ln = _f(line)
    if ln is not None and ("spread" in m or "handicap" in m) and sd == "away":
        ln = -ln
    return (str(event), m, seg, pl, None if ln is None else round(ln, 3))


def outcome_set(sides: Iterable[str]) -> set[str] | None:
    s = set(sides)
    if s & {"over", "under"}:
        return {"over", "under"}
    if s & {"yes", "no"}:
        return {"yes", "no"}
    if s & {"home", "away"}:
        return {"home", "away"} | ({"draw"} if "draw" in s else set())
    return None


def ts(v: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ----------------------------------------------------------------------------- shared feeds


def feed_clusters(last_prices: Mapping[tuple, Mapping[str, Any]], threshold: float, min_overlap: int = 200) -> dict[str, str]:
    """book -> cluster representative. `last_prices[(group, side)] = {book: price}`."""
    same: dict[tuple[str, str], int] = defaultdict(int)
    both: dict[tuple[str, str], int] = defaultdict(int)
    for by_book in last_prices.values():
        books = sorted(by_book)
        for i, a in enumerate(books):
            for b in books[i + 1:]:
                both[(a, b)] += 1
                if by_book[a] == by_book[b]:
                    same[(a, b)] += 1
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for (a, b), n in both.items():
        find(a), find(b)
        if n >= min_overlap and same[(a, b)] / n >= threshold:
            parent[find(a)] = find(b)
    return {book: find(book) for book in parent}


# ----------------------------------------------------------------------------- fair at a moment


def fair_for(per_book: Mapping[str, Mapping[str, Any]], side: str, method: str,
             clusters: Mapping[str, str] | None = None) -> tuple[float | None, int]:
    """Median across books of `method`'s de-vigged probability for `side`; (fair, books_used)."""
    votes: dict[str, list[float]] = defaultdict(list)
    for book, sides in per_book.items():
        if side not in sides:
            continue
        need = outcome_set(sides)
        if not need or not need <= set(sides) or side not in need:
            continue
        imps = {s: implied(sides[s]) for s in need}
        if any(v is None for v in imps.values()):
            continue
        hold = sum(imps.values())
        if hold < 0.90 or hold > 1.35:
            continue
        p = _DEVIG[method](imps)[side]
        key = (clusters or {}).get(book, book) if method == "power_dedup" else book
        votes[key].append(p)
    if not votes:
        return None, 0
    per_vote = [statistics.median(v) for v in votes.values()]
    return statistics.median(per_vote), len(per_vote)


# ----------------------------------------------------------------------------- scoring


def log_loss(p: float, y: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def calibration(ps: list[float], ys: list[float]) -> tuple[float, float] | None:
    """Logistic regression y ~ a + b * logit(p) by Newton-Raphson; (a, b). A calibrated fair is (0, 1)."""
    xs = [math.log(min(max(p, 1e-6), 1 - 1e-6) / (1 - min(max(p, 1e-6), 1 - 1e-6))) for p in ps]
    a, b = 0.0, 1.0
    for _ in range(50):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            mu = 1.0 / (1.0 + math.exp(-(a + b * x)))
            w = mu * (1 - mu)
            g0 += y - mu
            g1 += (y - mu) * x
            h00 += w
            h01 += w * x
            h11 += w * x * x
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            return None
        da = (h11 * g0 - h01 * g1) / det
        db = (-h01 * g0 + h00 * g1) / det
        a, b = a + da, b + db
        if abs(da) + abs(db) < 1e-9:
            break
    return a, b


def boot_ci(rows: list[dict], stat, B: int = 400, seed: int = 20261013) -> tuple[float, float]:
    games: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        games[r["game"]].append(r)
    keys = list(games)
    if len(keys) < 5:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    vals = []
    for _ in range(B):
        sample = [r for _ in keys for r in games[rng.choice(keys)]]
        v = stat(sample)
        if v is not None:
            vals.append(v)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def summarize(rows: list[dict], when: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    base = [r for r in rows if all(r.get(f"{when}_{m}") is not None for m in METHODS)]
    out["n"] = len(base)
    out["games"] = len({r["game"] for r in base})
    for m in METHODS:
        ps = [r[f"{when}_{m}"] for r in base]
        ys = [r["y"] for r in base]
        if not ps:
            continue
        ll = sum(log_loss(p, y) for p, y in zip(ps, ys)) / len(ps)
        br = sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)
        cal = calibration(ps, ys)
        entry: dict[str, Any] = {"log_loss": round(ll, 6), "brier": round(br, 6),
                                 "cal_intercept": None if cal is None else round(cal[0], 4),
                                 "cal_slope": None if cal is None else round(cal[1], 4)}
        if m != "mult":
            def diff(s, m=m):
                if not s:
                    return None
                return sum(log_loss(r[f"{when}_{m}"], r["y"]) - log_loss(r[f"{when}_mult"], r["y"]) for r in s) / len(s)
            d = diff(base)
            lo, hi = boot_ci(base, diff)
            entry["log_loss_minus_mult"] = round(d, 6)
            entry["ci95"] = [round(lo, 6), round(hi, 6)]
        out[m] = entry
    return out


def selection_test(rows: list[dict], threshold: float = 0.02) -> dict[str, Any]:
    out = {}
    for m in METHODS:
        sel = [r for r in rows if r.get(f"sight_{m}") is not None and r.get("close_power") is not None
               and r.get("dec") and r[f"sight_{m}"] * r["dec"] - 1 >= threshold
               and r[f"sight_{m}"] * r["dec"] - 1 <= 0.0526]
        if not sel:
            out[m] = {"n": 0}
            continue

        def ev_close(s):
            return 100 * sum(r["close_power"] * r["dec"] - 1 for r in s) / len(s) if s else None

        def roi(s):
            return 100 * sum(r["pnl"] for r in s) / len(s) if s else None
        out[m] = {"n": len(sel), "games": len({r["game"] for r in sel}),
                  "plus_money_share": round(sum(1 for r in sel if r["dec"] > 2.0) / len(sel), 3),
                  "ev_at_power_close_pct": round(ev_close(sel), 3), "ev_ci95": [round(x, 3) for x in boot_ci(sel, ev_close)],
                  "roi_pct": round(roi(sel), 2), "roi_ci95": [round(x, 2) for x in boot_ci(sel, roi)]}
    return out


# ----------------------------------------------------------------------------- driver


def load_graded(path: Path) -> list[dict]:
    rows = []
    for line in path.open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("phase") != "pregame" or r.get("px") is None or r.get("y") is None or not r.get("t"):
            continue
        sport, _, event = str(r.get("game") or "").partition("|")
        if not event:
            continue
        r["sport"], r["event_id"] = sport, event
        r["gkey"] = group_key(event, r.get("market"), r.get("segment"), r.get("player"), r.get("side"), r.get("line"))
        r["sd"] = str(r.get("side") or "").strip().lower()
        r["dec"] = decimal_odds(r["px"])
        rows.append(r)
    return rows


def read_quotes(data_root: Path, sport: str, events: set[str], groups: set[tuple]) -> dict[tuple, list[tuple]]:
    """(group, book, side) -> [(captured_at, price, commence_time)] for the wanted groups."""
    hist: dict[tuple, list[tuple]] = defaultdict(list)
    directory = data_root / f"{sport}_source" / "tracking" / "book_quotes"
    for path in sorted(directory.glob("*.jsonl*")):
        opener = gzip.open if path.suffix == ".gz" else open
        try:
            with opener(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    m = _EVENT_RE.search(line)
                    if not m or m.group(1) not in events:
                        continue
                    q = json.loads(line)
                    side = str(q.get("selection") or "").strip().lower()
                    g = group_key(q.get("event_id"), q.get("market"), q.get("segment"), q.get("player_name"), side, q.get("line"))
                    if g not in groups:
                        continue
                    cap, ct = ts(q.get("captured_at")), ts(q.get("commence_time"))
                    if cap is None or ct is None or cap >= ct:
                        continue
                    hist[(g, str(q.get("bookmaker") or "").lower(), side)].append((cap, q.get("price"), ct))
        except (OSError, EOFError) as exc:
            print(f"READ_ERROR {path} {type(exc).__name__}", flush=True)
    return hist


def evaluate(rows: list[dict], hist: Mapping[tuple, list[tuple]], *, max_age_h: float, max_stale_h: float,
             dup_threshold: float) -> dict[str, Any]:
    by_group: dict[tuple, list[tuple[str, str, list[tuple]]]] = defaultdict(list)
    for (g, book, side), h in hist.items():
        h.sort(key=lambda x: x[0])
        by_group[g].append((book, side, h))
    # shared feeds, from last pregame prices
    last_prices: dict[tuple, dict[str, Any]] = defaultdict(dict)
    for g, items in by_group.items():
        for book, side, h in items:
            last_prices[(g, side)][book] = h[-1][1]
    clusters = feed_clusters(last_prices, dup_threshold)
    for r in rows:
        items = by_group.get(r["gkey"], ())
        t = ts(r["t"])
        sight: dict[str, dict[str, Any]] = defaultdict(dict)
        close: dict[str, dict[str, Any]] = defaultdict(dict)
        for book, side, h in items:
            prior = [x for x in h if x[0] <= t and t - x[0] <= timedelta(hours=max_age_h)] if t else []
            if prior:
                sight[book][side] = prior[-1][1]
            last = h[-1]
            if last[2] - last[0] <= timedelta(hours=max_stale_h):
                close[book][side] = last[1]
        for m in METHODS:
            r[f"sight_{m}"], r[f"sight_books_{m}"] = fair_for(sight, r["sd"], m, clusters)
            r[f"close_{m}"], _ = fair_for(close, r["sd"], m, clusters)
    scored = [r for r in rows if r.get("sight_mult") is not None]
    report: dict[str, Any] = {
        "rows_graded_pregame": len(rows), "rows_with_sighting_fair": len(scored),
        "feed_clusters": {rep: sorted(b for b, c in clusters.items() if c == rep)
                          for rep in sorted(set(clusters.values())) if sum(1 for c in clusters.values() if c == rep) > 1},
        "pooled": {"sighting": summarize(scored, "sight"), "close": summarize(scored, "close")},
        "by_sport": {}, "by_kind": {}, "by_price": {},
        "selection_ev2": selection_test(scored),
    }
    for sport in sorted({r["sport"] for r in scored}):
        report["by_sport"][sport] = summarize([r for r in scored if r["sport"] == sport], "sight")
    for kind in ("game", "prop"):
        report["by_kind"][kind] = summarize([r for r in scored if bool(r.get("player")) == (kind == "prop")], "sight")
    for lbl, lo, hi in (("fav <-200", 1.0, 1.5), ("-200..-110", 1.5, 1.91), ("-110..+150", 1.91, 2.5),
                        ("+150..+400", 2.5, 5.0), ("+400 or longer", 5.0, 1e9)):
        report["by_price"][lbl] = summarize([r for r in scored if r["dec"] and lo <= r["dec"] < hi], "sight")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--graded", required=True)
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-age-h", type=float, default=12.0)
    ap.add_argument("--max-stale-h", type=float, default=6.0)
    ap.add_argument("--dup-threshold", type=float, default=0.9)
    args = ap.parse_args(argv)
    root = Path(os.path.expanduser(args.data_root))
    rows = load_graded(Path(args.graded))
    hist: dict[tuple, list[tuple]] = {}
    for sport in sorted({r["sport"] for r in rows}):
        sub = [r for r in rows if r["sport"] == sport]
        got = read_quotes(root, sport, {r["event_id"] for r in sub}, {r["gkey"] for r in sub})
        print(f"QUOTES {sport} rows={len(sub)} keys={len(got)}", flush=True)
        hist.update(got)
    report = evaluate(rows, hist, max_age_h=args.max_age_h, max_stale_h=args.max_stale_h, dup_threshold=args.dup_threshold)
    Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    pooled = report["pooled"]["sighting"]
    print(f"ROWS graded_pregame={report['rows_graded_pregame']} with_fair={report['rows_with_sighting_fair']} "
          f"n_all_methods={pooled.get('n')} games={pooled.get('games')}")
    for m in METHODS:
        e = pooled.get(m) or {}
        print(f"  {m:12s} logloss={e.get('log_loss')} brier={e.get('brier')} cal=({e.get('cal_intercept')},{e.get('cal_slope')})"
              f" vs_mult={e.get('log_loss_minus_mult')} ci={e.get('ci95')}")
    print("FEED_CLUSTERS", json.dumps(report["feed_clusters"]))
    print("SELECTION_EV2", json.dumps(report["selection_ev2"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
