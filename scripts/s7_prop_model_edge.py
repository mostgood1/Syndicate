"""S7 arm B: does a per-line PLAYER-PROP rule -- the sim's probability minus the venue's own breakeven -- beat breakeven?

Study S7 of the profit learning program (`.syndicate/plan_2026-11-18_profit_learning_program.md`), lane
`s7-combos-props`. PRE-REGISTERED in `.syndicate/findings_2026-11-19_s7_combos_props.md`, pushed to main before any
outcome number was computed. READ-ONLY: it reads a ledger dump (`live_cell_scorecard.py dump`) and nothing else.

POPULATION. S1's population (`s1_freshness_study.population`: pregame, filled, settled, staked venue orders with an
event at kalshi / polymarket, live + paper twin + ladder, paper deduplicated per (venue, position_key), first submit
kept), restricted to PLAYER PROPS (`live_cell_gate.family_of == "prop"`), with a model probability known at submit:

    q       = the requested contract price (S6 `price_terms`)
    fair    = q * (1 + ev_pct/100)          (ev_pct is GROSS at the venue's price: `venue_scope.scope_rows_to_venue`)
    p_model = fair + model_edge_pct/100     (the sizer's own reconstruction, `portfolio_commit`)
    be      = q + fee per contract           (S6 `price_terms`)
    edge_pp = 100 * (p_model - be)          the sim's edge against the venue's breakeven, fee included

RULE. Keep an order iff edge_pp >= T. T from T_GRID, chosen on FIT (submits before 2026-11-08): the largest FIT flat
ROI among T keeping >= 200 orders and >= 50 events; ties go to the smaller T.

METRIC. Flat fee-net ROI of the kept orders (mean pnl / stake, percent) -- the benchmark is breakeven, 0 -- with an
event-clustered 95% interval (S1 `flat`). Beside it, deciding nothing: kept - all (S1 `clustered_diff`), the edge
band table, the slope of return on edge_pp, and slices.

    py -3 scripts/s7_prop_model_edge.py coverage --ledger LEDGER.json          # counts only, no outcome
    py -3 scripts/s7_prop_model_edge.py report   --ledger LEDGER.json          # the registered test
    py -3 scripts/s7_prop_model_edge.py forward  --ledger LEDGER.json --rule-from .syndicate/findings_2026-11-19_s7_combos_props.md
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import s1_freshness_study as s1  # noqa: E402
from scripts import s6_adverse_selection as s6  # noqa: E402
from syndicate.features.shared.live_cell_gate import family_of, parse_ts  # noqa: E402

FIT_END = "2026-11-08T00:00:00Z"
TEST_END = "2026-11-19T00:00:00Z"
FORWARD_START = "2026-11-20T00:00:00Z"
FORWARD_EVENTS = 150
T_GRID = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0)
MIN_FIT_ORDERS, MIN_FIT_EVENTS = 200, 50
EDGE_BANDS = ((-math.inf, 0.0, "<0"), (0.0, 2.0, "0-2"), (2.0, 4.0, "2-4"), (4.0, 6.0, "4-6"),
              (6.0, 10.0, "6-10"), (10.0, math.inf, ">=10"))
RULE_MARKER = "S7_RULE_JSON"
BOOT_REPS, BOOT_SEED = 2000, 20261119
Z95 = s1.Z95


# --------------------------------------------------------------------------- rows (known at submit)

def model_terms(order: Mapping[str, Any]) -> dict[str, Any]:
    """p_model, breakeven and edge_pp for one order, or the reason it cannot be priced. Uses no outcome."""
    pt = s6.price_terms(order)
    q = pt["req_p"]
    if q is None or not 0.0 < q < 1.0:
        return {"why": "no_price"}
    ev = s1._num(order.get("ev_pct"))
    if ev is None:
        return {"why": "no_ev_pct"}
    me = s1._num(order.get("model_edge_pct"))
    if me is None:
        return {"why": "no_model_edge"}
    fair = q * (1.0 + ev / 100.0)
    if not 0.0 < fair < 1.0:
        return {"why": "fair_out_of_range"}
    p_model = fair + me / 100.0
    if not 0.0 < p_model < 1.0:
        return {"why": "model_out_of_range"}
    be = pt["be"]
    return {"why": None, "q": q, "fair": fair, "p_model": p_model, "be": be, "fee_per": pt["fee_per"],
            "me": me, "ev": ev, "edge_pp": 100.0 * (p_model - be)}


def window_of(submitted: str | None) -> str:
    sub = parse_ts(submitted)
    if sub is None:
        return "none"
    if sub < parse_ts(FIT_END):
        return "FIT"
    if sub < parse_ts(TEST_END):
        return "TEST"
    if sub < parse_ts(FORWARD_START):
        return "GAP"
    return "FORWARD"


def build_rows(orders: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    pop, drops = s1.population(orders)
    drops = Counter(drops)
    rows: list[dict[str, Any]] = []
    for o in pop:
        if family_of(o) != "prop":
            drops["not_prop"] += 1
            continue
        mt = model_terms(o)
        if mt["why"]:
            drops[f"prop:{mt['why']}"] += 1
            continue
        r = s1.study_row(o, {}, None)
        r.pop("move", None)
        r.pop("pin_age_s", None)
        r.pop("cons_age_s", None)
        r.update({k: v for k, v in mt.items() if k != "why"})
        r["market"] = str(o.get("market") or "").lower()
        r["window"] = window_of(r["submitted"])
        rows.append(r)
    return rows, dict(sorted(drops.items()))


def load_ledger(path: str) -> list[Mapping[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return raw.get("orders", []) if isinstance(raw, Mapping) else raw


# --------------------------------------------------------------------------- statistics (outcome)

def kept_of(rows: Sequence[Mapping[str, Any]], t: float) -> list[Mapping[str, Any]]:
    return [r for r in rows if r["edge_pp"] >= t]


def choose_t(fit: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """T maximising FIT flat ROI(kept) among T with >= MIN_FIT_ORDERS orders and >= MIN_FIT_EVENTS events; ties to
    the smaller T. `stop` is True when no T is eligible or the best kept ROI is <= 0 (NO CHALLENGER)."""
    table = []
    for t in T_GRID:
        k = kept_of(fit, t)
        f = s1.flat(k)
        table.append({"t": t, **f, "eligible": f["n"] >= MIN_FIT_ORDERS and f["events"] >= MIN_FIT_EVENTS,
                      "d_all": s1.clustered_diff(k, fit) if k else None})
    best = None
    for row in table:
        if row["eligible"] and (best is None or row["roi"] > best["roi"] + 1e-12):
            best = row
    if best is None:
        anyrow = [r for r in table if r["n"]]
        best_any = max(anyrow, key=lambda r: r["roi"]) if anyrow else None
        return {"table": table, "t": best_any["t"] if best_any else None, "stop": True, "why": "no_eligible_t"}
    return {"table": table, "t": best["t"], "stop": best["roi"] <= 0.0,
            "why": "best_fit_roi_not_above_breakeven" if best["roi"] <= 0.0 else None}


def boot_mean(rows: Sequence[Mapping[str, Any]], reps: int = BOOT_REPS, seed: int = BOOT_SEED) -> tuple | None:
    """Seeded event-cluster bootstrap 95% interval of the flat ROI (a CHECK, not the registered interval)."""
    by: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by[r["game"]].append(r["ret"])
    games = [(sum(v), len(v)) for v in by.values()]
    if len(games) < 2:
        return None
    rng = random.Random(seed)
    out = []
    for _ in range(reps):
        s = n = 0.0
        for _g in range(len(games)):
            a, b = games[rng.randrange(len(games))]
            s, n = s + a, n + b
        out.append(100.0 * s / n)
    out.sort()
    return out[int(reps * 0.025)], out[int(reps * 0.975) - 1]


def slope(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """OLS of return on edge_pp, event-clustered SE: return change per +1 pp of edge, in pp."""
    n = len(rows)
    if n < 3:
        return {"b": None}
    mx = sum(r["edge_pp"] for r in rows) / n
    my = sum(r["ret"] for r in rows) / n
    sxx = sum((r["edge_pp"] - mx) ** 2 for r in rows)
    if sxx <= 0:
        return {"b": None}
    b = sum((r["edge_pp"] - mx) * (r["ret"] - my) for r in rows) / sxx
    a = my - b * mx
    u: dict[str, float] = defaultdict(float)
    for r in rows:
        u[r["game"]] += (r["edge_pp"] - mx) * (r["ret"] - a - b * r["edge_pp"])
    se = math.sqrt(sum(v * v for v in u.values())) / sxx
    return {"b": 100 * b, "se": 100 * se, "lo": 100 * (b - Z95 * se), "hi": 100 * (b + Z95 * se), "n": n,
            "events": len(u)}


def band_table(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for lo, hi, label in EDGE_BANDS:
        b = [r for r in rows if lo <= r["edge_pp"] < hi]
        f = s1.flat(b)
        mean_edge = sum(r["edge_pp"] for r in b) / len(b) if b else None
        out.append({"band": label, **f, "mean_edge_pp": mean_edge})
    return out


def verdict_test(kept_flat: Mapping[str, Any], stop: bool) -> str:
    if stop:
        return "NO CHALLENGER (FIT stop)"
    if kept_flat.get("hi") is not None and kept_flat["hi"] < 0:
        return "KILL (TEST upper bound < 0)"
    return "FORWARD TEST owed"


def report(rows: Sequence[Mapping[str, Any]], drops: Mapping[str, int]) -> dict[str, Any]:
    fit = [r for r in rows if r["window"] == "FIT"]
    test = [r for r in rows if r["window"] == "TEST"]
    ch = choose_t(fit)
    t = ch["t"]
    kept = kept_of(test, t) if t is not None else []
    dropped = [r for r in test if t is not None and r["edge_pp"] < t]
    kept_flat = s1.flat(kept)
    slices = {}
    for name, pred in s1.SLICES:
        a = [r for r in test if pred(r)]
        k = [r for r in kept if pred(r)]
        slices[name] = {"all": s1.flat(a), "kept": s1.flat(k), "d_all": s1.clustered_diff(k, a)}
    sports = {}
    for sp in sorted({r["sport"] for r in test}):
        a = [r for r in test if r["sport"] == sp]
        k = [r for r in kept if r["sport"] == sp]
        sports[sp] = {"all": s1.flat(a), "kept": s1.flat(k)}
    return {
        "drops": dict(drops), "fit_all": s1.flat(fit), "choose": ch, "t": t,
        "test_all": s1.flat(test), "test_kept": kept_flat, "test_dropped": s1.flat(dropped),
        "test_kept_boot": boot_mean(kept), "test_d_all": s1.clustered_diff(kept, test) if kept else None,
        "test_kept_minus_dropped": s1.clustered_diff(kept, dropped) if kept and dropped else None,
        "share_kept_test": len(kept) / len(test) if test else None,
        "bands_fit": band_table(fit), "bands_test": band_table(test),
        "slope_fit": slope(fit), "slope_test": slope(test),
        "slices_test": slices, "sports_test": sports,
        "verdict": verdict_test(kept_flat, ch["stop"]),
        "rule": {"t_pp": t, "fit_end": FIT_END, "test_end": TEST_END, "forward_start": FORWARD_START,
                 "forward_events": FORWARD_EVENTS},
    }


def forward(rows: Sequence[Mapping[str, Any]], rule: Mapping[str, Any]) -> dict[str, Any]:
    """The registered forward reading: kept orders submitted from FORWARD_START on; the decision set is the kept
    orders on the first `forward_events` events by first submit. GO iff the flat ROI's 95% lower bound > 0."""
    t = float(rule["t_pp"])
    need = int(rule.get("forward_events", FORWARD_EVENTS))
    start = parse_ts(rule.get("forward_start", FORWARD_START))
    fwd = [r for r in rows if parse_ts(r["submitted"]) and parse_ts(r["submitted"]) >= start]
    kept = kept_of(fwd, t)
    first: dict[str, str] = {}
    for r in sorted(kept, key=lambda r: r["submitted"]):
        first.setdefault(r["game"], r["submitted"])
    events = sorted(first, key=lambda g: first[g])
    out = {"t_pp": t, "forward_orders": len(fwd), "kept_orders": len(kept), "kept_events": len(events),
           "need": need, "all_forward": s1.flat(fwd)}
    if len(events) < need:
        out["verdict"] = f"NOT YET ({len(events)} of {need} events)"
        return out
    chosen = set(events[:need])
    dec = [r for r in kept if r["game"] in chosen]
    f = s1.flat(dec)
    out.update({"decision": f, "decision_boot": boot_mean(dec),
                "decision_all": s1.flat([r for r in fwd if r["game"] in chosen]),
                "verdict": "GO" if f["lo"] is not None and f["lo"] > 0 else "NO-GO"})
    return out


# --------------------------------------------------------------------------- coverage (no outcome)

def coverage(rows: Sequence[Mapping[str, Any]], drops: Mapping[str, int]) -> dict[str, Any]:
    by_win: dict[str, Counter] = defaultdict(Counter)
    ev_by_win: dict[str, set] = defaultdict(set)
    by_sport_stat: dict[tuple, Counter] = defaultdict(Counter)
    by_date: dict[str, Counter] = defaultdict(Counter)
    by_book: dict[tuple, Counter] = defaultdict(Counter)
    t_counts: dict[str, dict] = defaultdict(dict)
    for r in rows:
        w = r["window"]
        by_win[w]["orders"] += 1
        ev_by_win[w].add(r["game"])
        by_sport_stat[(r["sport"], r["market"])][w] += 1
        by_date[r["day"]][r["book"]] += 1
        by_book[(w, r["book"], r["venue"])]["orders"] += 1
    for w in ("FIT", "TEST"):
        ws = [r for r in rows if r["window"] == w]
        for t in T_GRID:
            k = kept_of(ws, t)
            t_counts[w][t] = (len(k), len({r["game"] for r in k}))
    edges = {w: sorted(r["edge_pp"] for r in rows if r["window"] == w) for w in ("FIT", "TEST")}
    q = {w: ([round(e[int(p * (len(e) - 1))], 2) for p in (0.1, 0.25, 0.5, 0.75, 0.9)] if e else None)
         for w, e in edges.items()}
    dates = sorted(by_date)
    return {"drops": dict(drops),
            "windows": {w: {"orders": c["orders"], "events": len(ev_by_win[w])} for w, c in by_win.items()},
            "by_sport_stat": {f"{s}|{m}": dict(c) for (s, m), c in sorted(by_sport_stat.items())},
            "by_date": {d: dict(by_date[d]) for d in dates},
            "by_book": {f"{w}|{b}|{v}": c["orders"] for (w, b, v), c in sorted(by_book.items())},
            "t_counts": {w: {str(t): v for t, v in d.items()} for w, d in t_counts.items()},
            "edge_quantiles_p10_25_50_75_90": q,
            "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None,
            "n_dates": len(dates)}


# --------------------------------------------------------------------------- rendering

def _p(v: Any, d: int = 2) -> str:
    return "n/a" if v is None else f"{v:+.{d}f}"


def _flat(f: Mapping[str, Any] | None) -> str:
    if not f or not f.get("n"):
        return "0 orders"
    return f"{f['n']:,} / {f['events']:,}, {_p(f['roi'])}% [{_p(f['lo'])}, {_p(f['hi'])}]"


def _diff(d: Mapping[str, Any] | None) -> str:
    if not d or d.get("d") is None:
        return "n/a"
    return f"{_p(d['d'])} pp [{_p(d['lo'])}, {_p(d['hi'])}]"


def render_report(rep: Mapping[str, Any]) -> str:
    L = [f"S7B_VERDICT {rep['verdict']}", f"T* = {rep['t']} pp", f"FIT all: {_flat(rep['fit_all'])}",
         "FIT T table (t: kept orders / events, ROI [95%], eligible, D vs all):"]
    for r in rep["choose"]["table"]:
        L.append(f"  {r['t']}: {_flat(r)} elig={r['eligible']} D_all={_diff(r['d_all'])}")
    L += [f"TEST all: {_flat(rep['test_all'])}", f"TEST kept: {_flat(rep['test_kept'])} boot={rep['test_kept_boot']}",
          f"TEST dropped: {_flat(rep['test_dropped'])}", f"TEST kept - all: {_diff(rep['test_d_all'])}",
          f"TEST kept - dropped: {_diff(rep['test_kept_minus_dropped'])}", f"share kept TEST: {rep['share_kept_test']}"]
    for w in ("fit", "test"):
        L.append(f"bands {w.upper()}:")
        for b in rep[f"bands_{w}"]:
            L.append(f"  {b['band']}: {_flat(b)} mean_edge={_p(b['mean_edge_pp'])}")
        s = rep[f"slope_{w}"]
        L.append(f"  slope {w.upper()}: " + ("n/a" if s.get("b") is None else
                 f"{_p(s['b'], 3)} pp per pp [{_p(s['lo'], 3)}, {_p(s['hi'], 3)}] ({s['n']} / {s['events']})"))
    L.append("slices TEST (all | kept | D):")
    for k, v in rep["slices_test"].items():
        L.append(f"  {k}: {_flat(v['all'])} | {_flat(v['kept'])} | {_diff(v['d_all'])}")
    L.append("sports TEST (all | kept):")
    for k, v in rep["sports_test"].items():
        L.append(f"  {k}: {_flat(v['all'])} | {_flat(v['kept'])}")
    L.append(RULE_MARKER + " " + json.dumps(rep["rule"]))
    return "\n".join(L)


def load_rule_from(path: str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    if path.endswith(".json"):
        return json.loads(text)
    m = re.search(RULE_MARKER + r".*?```json\s*(\{.*?\})\s*```", text, re.S)
    if not m:
        raise SystemExit(f"no {RULE_MARKER} block in {path}")
    return json.loads(m.group(1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("coverage", "report", "forward"):
        p = sub.add_parser(name)
        p.add_argument("--ledger", required=True)
        p.add_argument("--json-out", default=None)
        if name == "forward":
            p.add_argument("--rule-from", required=True)
    args = ap.parse_args(argv)
    rows, drops = build_rows(load_ledger(args.ledger))
    if args.cmd == "coverage":
        out = coverage(rows, drops)
        text = json.dumps(out, indent=1)
    elif args.cmd == "report":
        out = report(rows, drops)
        text = render_report(out)
    else:
        out = forward(rows, load_rule_from(args.rule_from))
        text = json.dumps(out, indent=1, default=str)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
