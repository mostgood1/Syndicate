"""Why claimed EV above ~4% under-delivers on settled paper venue orders -- decomposition + forward test.

Lane `ev-overstatement-decomp` (2026-10-19). Findings: `.syndicate/findings_2026-10-19_ev_overstatement_decomp.md`.

Three FLEET steps (run inside WSL with the worker's state env, at nice 19 -- they read production state
read-only and write only to --out):

    python scripts/ev_overstatement_decomp.py dump    --out DIR   # execution_ledger.full_history_orders()
    python scripts/ev_overstatement_decomp.py openings --out DIR  # each order's clv_openings record(s)
    python scripts/ev_overstatement_decomp.py quotes  --out DIR   # every book, both sides, at submit + at kickoff

Then anywhere:

    python scripts/ev_overstatement_decomp.py report  --out DIR   # the tables in the findings file
    python scripts/ev_overstatement_decomp.py forward --out DIR --since 2026-10-20T00:00:00Z

`forward` is the pre-registered instrument of lane `sim-stake-unfitted-market-only`: the paired comparison of
the sim's ADDED dollars against the EV-only dollars on the same settled orders, plus the sim weight w fitted on
those orders. It needs no deploy -- every ledger row already carries `sim_share_of_stake`, the exact
counterfactual "same row with model_edge_pct = 0" (`portfolio_commit.stake_attribution`).

Conventions: flat ROI is one unit per order (push excluded); stake ROI is pnl / stake over dollars; the sim's
dollars are `stake * sim_share_of_stake` and their pnl is pro rata (pnl is linear in stake for one bet).
Every +- is one event-clustered standard error. A row's market fair is backed out of the stamp itself:
`p_fair = (1 + ev_pct/100) / decimal(requested_price)` -- the price the stamp was taken at, fill if absent.
Prices are American odds or, on a live venue row, a contract price in (0, 1); `decimal_odds` reads both.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import math
import os
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BANDS = ((-99.0, 2.0), (2.0, 3.0), (3.0, 4.0), (4.0, 5.0), (5.0, 99.0))
OPPOSITE = {"home": "away", "away": "home", "over": "under", "under": "over", "yes": "no", "no": "yes"}
# 2026-10-05 is when the sim began sizing paper stakes again (lane stop-market-withholding); before it the
# sim's share of dollars is 0.0 on every order. The two regimes are reported apart, never pooled silently.
SIM_SIZING_FROM = "2026-10-05"


# --------------------------------------------------------------------------- helpers

def _ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def decimal_odds(price) -> float:
    """Decimal odds from American odds OR a live venue contract price (0 < p < 1).

    The ledger holds both units in one `fill_price` column (todo #719); read as
    American, a live 0.65 fill is 1.0065. The unit rule is
    `paper_settlement.profit_per_dollar`'s.
    """
    from syndicate.features.shared.paper_settlement import profit_per_dollar

    profit = profit_per_dollar(price)
    if profit is None:
        raise ValueError(f"unusable price {price!r}")
    return 1.0 + profit


def _devig_pair(price_us, price_them) -> float:
    a, b = 1.0 / decimal_odds(price_us), 1.0 / decimal_odds(price_them)
    return a / (a + b)


def band_of(ev: float) -> str:
    for lo, hi in BANDS:
        if lo <= ev < hi:
            return f"[{lo:g},{hi:g})"
    return "?"


def settled_ev_orders(orders):
    return [o for o in orders if o.get("outcome") in ("won", "lost") and o.get("ev_pct") is not None]


def order_id(o) -> str:
    return f"{o.get('idempotency_key')}|{o.get('venue')}"


def clustered(rows, f):
    """Mean of f over rows and its event-clustered standard error."""
    n = len(rows)
    if not n:
        return float("nan"), float("nan")
    m = sum(f(r) for r in rows) / n
    groups = collections.defaultdict(float)
    for r in rows:
        groups[r["event_id"]] += f(r) - m
    return m, math.sqrt(sum(v * v for v in groups.values())) / n


def clustered_ratio(rows, weight):
    """Stake ROI (%) over `stake * weight(r)` dollars and its event-clustered standard error."""
    dollars = sum(r["_stake"] * weight(r) for r in rows)
    if dollars <= 0:
        return float("nan"), float("nan"), 0.0
    m = sum(r["_pnl"] * weight(r) for r in rows) / dollars
    groups = collections.defaultdict(float)
    for r in rows:
        groups[r["event_id"]] += (r["_pnl"] - m * r["_stake"]) * weight(r)
    return 100 * m, 100 * math.sqrt(sum(v * v for v in groups.values())) / dollars, dollars


def enrich(orders):
    rows = settled_ev_orders(orders)
    for r in rows:
        d = decimal_odds(r["fill_price"])
        r["_dec"] = d
        # The fair is backed out of the price `ev_pct` was STAMPED against -- the
        # plan's requested price. A paper fill copies it; a live fill is the venue
        # contract price and can differ by slippage. The return is at the fill.
        stamp = r.get("requested_price")
        r["_pf"] = (1 + r["ev_pct"] / 100) / (decimal_odds(stamp) if stamp is not None else d)
        r["_ret"] = d - 1 if r["outcome"] == "won" else -1.0
        r["_y"] = 1.0 if r["outcome"] == "won" else 0.0
        r["_band"] = band_of(r["ev_pct"])
        r["_stake"] = float(r.get("fill_stake_dollars") or 0.0)
        r["_pnl"] = float(r.get("pnl_dollars") or 0.0)
        r["_sim"] = float(r.get("sim_share_of_stake") or 0.0)
        sub, ko = _ts(r.get("submitted_at")), _ts(r.get("commence_time"))
        r["_live"] = None if not sub or not ko else sub >= ko
        r["_regime"] = "sim_sizing" if str(r.get("submitted_at") or "") >= SIM_SIZING_FROM else "sim_gated"
    return rows


def fit_sim_weight(rows, *, boots=400, seed=5):
    """Log-loss-optimal w in p = fair + w * model_edge, with an event bootstrap 95% interval."""
    import numpy as np

    rows = [r for r in rows if r.get("model_edge_pct") is not None]
    if not rows:
        return None
    events = {e: i for i, e in enumerate(sorted({r["event_id"] for r in rows}))}
    pf = np.array([r["_pf"] for r in rows])
    me = np.array([r["model_edge_pct"] / 100 for r in rows])
    y = np.array([r["_y"] for r in rows])
    g = np.array([events[r["event_id"]] for r in rows])
    grid = np.linspace(-1.0, 1.5, 101)

    def best(weights):
        p = np.clip(pf[None, :] + grid[:, None] * me[None, :], 1e-3, 1 - 1e-3)
        loss = -(weights[None, :] * (y * np.log(p) + (1 - y) * np.log(1 - p))).sum(1)
        return float(grid[loss.argmin()])

    rng = np.random.default_rng(seed)
    point = best(np.ones(len(rows)))
    draws = [best(np.bincount(rng.integers(0, len(events), len(events)), minlength=len(events))[g].astype(float))
             for _ in range(boots)]
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {"w": point, "lo": float(lo), "hi": float(hi), "n": len(rows), "events": len(events),
            "mean_edge_pp": float(100 * me.mean())}


# --------------------------------------------------------------------------- fleet steps

def cmd_dump(args) -> int:
    from syndicate.features.shared import execution_ledger

    orders = execution_ledger.full_history_orders()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ledger.json").write_text(json.dumps(orders, default=str), encoding="utf-8")
    print(f"rows {len(orders)} -> {out / 'ledger.json'}")
    return 0


def cmd_openings(args) -> int:
    from syndicate.features.shared.clv_opening_ledger import OPENING_LEDGER_SUBDIR, _reports_root

    out = Path(args.out)
    orders = json.loads((out / "ledger.json").read_text(encoding="utf-8"))
    want = {o["opening_key"] for o in settled_ev_orders(orders) if o.get("opening_key")}
    directory = _reports_root() / "intelligence" / OPENING_LEDGER_SUBDIR
    found: dict[str, list] = {}
    for path in sorted(directory.glob("2026-*.jsonl")):
        matched = 0
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                i = line.find('"key":"')
                if i < 0:
                    continue
                key = line[i + 7:line.find('"', i + 7)]
                if key in want:
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    found.setdefault(key, []).append(record)
                    matched += 1
        # A file at the 32 MiB tripwire is TRUNCATED: openings first sighted after the cut are absent.
        print(f"{path.name} {path.stat().st_size} matched {matched}")
    (out / "openings_joined.json").write_text(json.dumps(found), encoding="utf-8")
    print(f"keys found {len(found)} of {len(want)}")
    return 0


def cmd_quotes(args) -> int:
    from syndicate.features.shared.odds_book_quotes import kickoff_shard_date, resolve_book_quotes_path

    out = Path(args.out)
    orders = json.loads((out / "ledger.json").read_text(encoding="utf-8"))
    want: dict[tuple, set] = collections.defaultdict(set)
    todo = []
    for o in settled_ev_orders(orders):
        sub, ko = _ts(o.get("submitted_at")), _ts(o.get("commence_time"))
        if not sub or not ko or sub >= ko or str(o.get("side") or "").lower() not in OPPOSITE:
            continue
        sport = str(o.get("sport") or "").lower()
        for day in {kickoff_shard_date({"commence_time": o["commence_time"]}), ko.date().isoformat()}:
            if day:
                want[(sport, day)].add(o["event_id"])
        todo.append(o)
    event_re = re.compile(r'"event_id"\s*:\s*"([^"]*)"')
    quotes: dict[tuple, list] = collections.defaultdict(list)
    for (sport, day), events in sorted(want.items()):
        path = resolve_book_quotes_path(sport, day)
        if not path.is_file():
            print("missing", sport, day)
            continue
        opener = gzip.open if str(path).endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                m = event_re.search(line)
                if not m or m.group(1) not in events:
                    continue
                try:
                    q = json.loads(line)
                except ValueError:
                    continue
                key = (q.get("event_id"), str(q.get("market") or "").lower(),
                       str(q.get("segment") or "full").lower() or "full", str(q.get("player_name") or "").strip().casefold())
                line_value = None if q.get("line") is None else round(float(q["line"]), 3)
                quotes[key].append((_ts(q.get("captured_at")), str(q.get("bookmaker") or "").lower(),
                                    str(q.get("selection") or "").lower(), line_value, q.get("price")))
    for value in quotes.values():
        value.sort(key=lambda item: item[0] or datetime.min.replace(tzinfo=timezone.utc))

    def snapshot(key, at, ours, theirs):
        """Per book: the last price <= at on our side and the opposite side at OUR line, plus the last time it
        quoted ANY other line (a book that moved off the number must not vote with its dead price)."""
        out_: dict[str, dict] = collections.defaultdict(dict)
        for t, book, selection, line_value, price in quotes.get(key, ()):
            if t is None or t > at:
                break
            if (selection, line_value) == ours:
                out_[book]["us"] = (price, t.isoformat())
            elif (selection, line_value) == theirs:
                out_[book]["them"] = (price, t.isoformat())
            elif selection in (ours[0], theirs[0]):
                out_[book]["other_line_last"] = (line_value, t.isoformat())
        return out_

    result = {}
    for o in todo:
        market = str(o.get("market") or "").lower()
        line_value = None if o.get("line") is None else round(float(o["line"]), 3)
        opposite_line = (-line_value if line_value is not None else None) if "spread" in market else line_value
        side = o["side"].lower()
        key = (o["event_id"], market, str(o.get("segment") or "full").lower() or "full",
               str(o.get("player_name") or "").strip().casefold())
        if key not in quotes:
            result[order_id(o)] = {"status": "no_market"}
            continue
        ours, theirs = (side, line_value), (OPPOSITE[side], opposite_line)
        result[order_id(o)] = {
            "status": "ok",
            "at_submit": snapshot(key, _ts(o["submitted_at"]), ours, theirs),
            "at_close": snapshot(key, _ts(o["commence_time"]), ours, theirs),
        }
    (out / "quotes_recon.json").write_text(json.dumps(result), encoding="utf-8")
    print("done", collections.Counter(v["status"] for v in result.values()))
    return 0


# --------------------------------------------------------------------------- analysis

def per_book_fairs(snap):
    fairs = {}
    for book, v in (snap or {}).items():
        if "us" not in v or "them" not in v:
            continue
        other = v.get("other_line_last")
        if other and other[1] > max(v["us"][1], v["them"][1]):
            continue
        try:
            fairs[book] = _devig_pair(v["us"][0], v["them"][0])
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    return fairs


def attach_quotes(rows, recon):
    for r in rows:
        x = recon.get(order_id(r)) or {}
        fs, fc = per_book_fairs(x.get("at_submit")), per_book_fairs(x.get("at_close"))
        r["_cons_submit"] = statistics.median(fs.values()) if fs else None
        r["_cons_close"] = statistics.median(fc.values()) if fc else None
        r["_ev_close"] = 100 * (r["_cons_close"] * r["_dec"] - 1) if r["_cons_close"] is not None else None
        moved = sum(1 for v in (x.get("at_close") or {}).values()
                    if v.get("other_line_last") and v["other_line_last"][1] > max(
                        (v.get("us") or ("", ""))[1], (v.get("them") or ("", ""))[1]))
        r["_line_stable"] = len(fs) >= 2 and len(fc) >= 2 and moved <= max(1, 0.2 * (len(fc) + moved))


def band_lines(rows, title):
    print(f"== {title}")
    print("   band     n     events  claimEV  flatROI        stakeROI       EV-only$ ROI    sim-added$ ROI   "
          "EV@closeFair   hit-closeCons(pp)")
    for lo, hi in BANDS:
        sub = [r for r in rows if lo <= r["ev_pct"] < hi]
        if not sub:
            continue
        flat, fse = clustered(sub, lambda r: 100 * r["_ret"])
        stake, sse, _ = clustered_ratio(sub, lambda r: 1.0)
        evo, ese, evd = clustered_ratio(sub, lambda r: 1.0 - r["_sim"])
        sim, mse, simd = clustered_ratio(sub, lambda r: r["_sim"])
        closed = [r for r in sub if r.get("_ev_close") is not None]
        evc, cse = clustered(closed, lambda r: r["_ev_close"])
        hit, hse = clustered(closed, lambda r: 100 * (r["_y"] - r["_cons_close"]))
        print(f"   {band_of(lo):8s} {len(sub):5d} {len({r['event_id'] for r in sub}):5d}   {sum(r['ev_pct'] for r in sub) / len(sub):5.2f}"
              f"  {flat:+6.1f}+-{fse:4.1f}  {stake:+6.1f}+-{sse:4.1f}  {evo:+6.1f}+-{ese:4.1f} ${evd:6.0f}"
              f"  {sim:+6.1f}+-{mse:4.1f} ${simd:6.0f}  {evc:+5.2f}+-{cse:4.2f}  {hit:+5.1f}+-{hse:3.1f} (n{len(closed)})")


def cmd_report(args) -> int:
    out = Path(args.out)
    rows = enrich(json.loads((out / "ledger.json").read_text(encoding="utf-8")))
    recon_path = out / "quotes_recon.json"
    if recon_path.exists():
        attach_quotes(rows, json.loads(recon_path.read_text(encoding="utf-8")))
    dates = sorted({str(r.get("selected_date")) for r in rows})
    print(f"COVERAGE settled rows with ev_pct: {len(rows)}, events {len({r['event_id'] for r in rows})}, "
          f"selected dates {len(dates)} {dates[0]}..{dates[-1]}")
    for venue, n in collections.Counter(r["venue"] for r in rows).most_common():
        print(f"  {venue:18s} {n}")
    print(f"  pregame with a reconstructed close fair: {sum(1 for r in rows if r.get('_ev_close') is not None)}")
    band_lines(rows, "ALL settled rows")
    band_lines([r for r in rows if r["_live"] is False], "PREGAME")
    band_lines([r for r in rows if r["_live"] is False and r.get("_line_stable")], "PREGAME, line held to kickoff")
    for regime in ("sim_gated", "sim_sizing"):
        band_lines([r for r in rows if r["_regime"] == regime], f"REGIME {regime}")
    for view in (("agrees", "live_agrees"), ("unpriced", "none", "neutral"), ("disagrees", "contradicts", "live_disagrees")):
        band_lines([r for r in rows if r.get("sim_view") in view], f"sim_view in {view}")
    by_day = collections.defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        by_day[str(r["submitted_at"])[:10]][0] += r["_stake"]
        by_day[str(r["submitted_at"])[:10]][1] += r["_stake"] * r["_sim"]
    print("== sim share of dollars by submit date: " + ", ".join(
        f"{d[5:]} {v[1] / v[0]:.2f}" for d, v in sorted(by_day.items()) if v[0]))
    for label, cond in (("EV>=2", lambda r: r["ev_pct"] >= 2), ("EV 2-4", lambda r: 2 <= r["ev_pct"] < 4),
                        ("EV>=4", lambda r: r["ev_pct"] >= 4)):
        fit = fit_sim_weight([r for r in rows if cond(r)])
        if fit:
            print(f"== sim weight w ({label}): {fit['w']:+.2f} [{fit['lo']:+.2f}, {fit['hi']:+.2f}] "
                  f"n={fit['n']} events={fit['events']} mean model edge {fit['mean_edge_pp']:+.1f}pp (the sizer uses 1.0)")
    return 0


def cmd_forward(args) -> int:
    """The pre-registered paired reading (lane sim-stake-unfitted-market-only). Verdict rule in the lane."""
    out = Path(args.out)
    rows = [r for r in enrich(json.loads((out / "ledger.json").read_text(encoding="utf-8")))
            if str(r.get("submitted_at") or "") >= args.since and r["ev_pct"] >= 2.0]
    model_rows = [r for r in rows if r.get("model_edge_pct") is not None]
    events = len({r["event_id"] for r in model_rows})
    print(f"FORWARD since {args.since}: {len(rows)} settled EV>=2 orders, {len(model_rows)} with a model edge "
          f"over {events} events; dates {sorted({str(r.get('selected_date')) for r in rows})[:1]}..")
    sim, sse, simd = clustered_ratio(model_rows, lambda r: r["_sim"])
    evo, ese, evd = clustered_ratio(model_rows, lambda r: 1.0 - r["_sim"])
    # Paired: the same orders, two slices of their dollars. Linearised per event so the two ratios'
    # shared outcomes cancel in the standard error instead of adding.
    diff, dse = sim - evo, float("nan")
    if simd > 0 and evd > 0:
        rs, re_ = sim / 100, evo / 100
        influence = collections.defaultdict(float)
        for r in model_rows:
            influence[r["event_id"]] += (r["_pnl"] - rs * r["_stake"]) * r["_sim"] / simd \
                - (r["_pnl"] - re_ * r["_stake"]) * (1 - r["_sim"]) / evd
        dse = 100 * math.sqrt(sum(v * v for v in influence.values()))
    print(f"  sim-added dollars ${simd:,.0f}: ROI {sim:+.1f} +- {sse:.1f}")
    print(f"  EV-only dollars   ${evd:,.0f}: ROI {evo:+.1f} +- {ese:.1f}")
    print(f"  paired difference (sim - EV-only): {diff:+.1f} +- {dse:.1f}")
    fit = fit_sim_weight(model_rows)
    if fit:
        print(f"  fitted sim weight w = {fit['w']:+.2f} [{fit['lo']:+.2f}, {fit['hi']:+.2f}] (sizer applies 1.0)")
    # Decided on w alone. The paired dollar difference is reported, never decisive: on the 10-05..10-18
    # backtest it was +0.3 +- 4.3 with w = -0.30 [-0.88, +0.23], i.e. the sim's stake adds variance at no
    # measured mean gain, which is the case the fix exists for (Kelly on an uninformative signal is over-betting).
    if events < args.min_events:
        print(f"VERDICT: NOT YET -- {events} events < {args.min_events}")
    elif fit and fit["hi"] < 0.5:
        print("VERDICT: CONFIRMED -- the sim's added stake carries less than half the weight it is given")
    elif fit and fit["lo"] > 0.5:
        print("VERDICT: FALSIFIED -- the sim's added stake earns its weight")
    else:
        print("VERDICT: INCONCLUSIVE -- extend the window (pre-registered: once, to 2x the events)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("dump", "openings", "quotes", "report", "forward"):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True, help="working directory for the dumps")
        if name == "forward":
            p.add_argument("--since", required=True, help="ISO time; orders submitted at or after it")
            p.add_argument("--min-events", type=int, default=300)
    args = parser.parse_args(argv)
    return {"dump": cmd_dump, "openings": cmd_openings, "quotes": cmd_quotes,
            "report": cmd_report, "forward": cmd_forward}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
