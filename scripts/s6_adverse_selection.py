"""Study S6 of the profit learning program: an entry-time adverse-selection filter in front of the trigger.

Lane `s6-adverse-selection` (2026-11-19). Plan: `.syndicate/plan_2026-11-18_profit_learning_program.md`, study S6.
Pre-registration and results: `.syndicate/findings_2026-11-19_s6_adverse_selection.md`. READ-ONLY.

QUESTION. Can a filter built from features known at submit, fitted on earlier orders, pick out the orders that lose,
so that dropping them raises fee-net flat ROI out of sample against the champion (all orders) on the same dates?

It reuses S1's instrument (`scripts/s1_freshness_study.py`, unmodified): the population (pregame, settled, filled,
staked venue orders: live + paper twin + ladder, paper deduplicated per position), the reference capture ages
(Pinnacle and sportsbook consensus, from the F0 fetch heartbeat), flat fee-net ROI and the event-clustered interval.
From Test B (`scripts/pinnacle_edge_deciles.py`, unmodified): `load_quotes`, `quote_key`, `implied`, `devig`,
`contract_price`.

FEATURES (all known at submit; a missing value is imputed at the FIT mean, i.e. contributes nothing; no sport or
market term, learnings 2026-10-05 PRIME DIRECTIVE: a gate is a property of the LINE)
  pin_age   log1p(Pinnacle capture age, minutes)
  cons_age  log1p(sportsbook-consensus capture age, minutes)
  n_books   sportsbooks (non-venue) with a two-way quote at OUR line in book_quotes as of submit
  disp      range of those books' de-vigged fairs, pp (>= 2 books)
  t_start   log1p(hours from submit to commence)
  price     logit(the requested contract price)
  vmove     our venue's own logged quote on our side, from the reference fetch to submit: +1 toward the reference fair,
            -1 away, 0 flat (S1's exploratory definition; reference fetch = Pinnacle capture, else consensus capture;
            reference fair = Pinnacle's two-way at submit, else the consensus median)
  ev        the trigger's own ev_pct, clipped to [-10, 30]

MODEL. L2 logistic regression of won (pushes excluded) with offset logit(breakeven at submit), breakeven = requested
contract price + fee per contract; standardized features (FIT mean / SD, clipped to +-4). Penalty lambda from
{1, 10, 100, 1000, 10000, 100000} by 5-fold event-grouped, time-ordered CV log loss on FIT. Score = predicted flat return
sigma(offset + theta.x) / breakeven - 1. Keep share q from {0.5..0.9} maximising the FIT out-of-fold
D = ROI(kept) - ROI(all); the score cut is the (1 - q) quantile of the final model's FIT scores.

    # FLEET (WSL, fleet venv, refresh-worker state env, nice 19)
    python scripts/live_cell_scorecard.py dump --out /mnt/c/tmp/s6adv/ledger.json
    python scripts/s6_adverse_selection.py join --ledger /mnt/c/tmp/s6adv/ledger.json --out /mnt/c/tmp/s6adv/rows.json
    # anywhere: coverage prints counts only (no outcome); report / forward print counts and percentages, never dollars
    py -3 scripts/s6_adverse_selection.py coverage --rows C:/tmp/s6adv/rows.json
    py -3 scripts/s6_adverse_selection.py report --rows C:/tmp/s6adv/rows.json --out-md PATH --out-model PATH
    py -3 scripts/s6_adverse_selection.py forward --rows ROWS --model-from .syndicate/findings_2026-11-19_s6_adverse_selection.md
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import pinnacle_edge_deciles as pe  # noqa: E402
from scripts import s1_freshness_study as s1  # noqa: E402
from syndicate.features.shared.live_cell_gate import parse_ts  # noqa: E402

FIT_END = "2026-11-08T00:00:00Z"
TEST_END = "2026-11-19T00:00:00Z"
FORWARD_START = "2026-11-20T00:00:00Z"
FORWARD_EVENTS = 150
LAMBDAS = (1.0, 10.0, 100.0, 1000.0, 10000.0, 100000.0)
KEEP_GRID = (0.5, 0.6, 0.7, 0.8, 0.9)
CV_FOLDS = 5
CLIP_Z = 4.0
FEATURES = ("pin_age", "cons_age", "n_books", "disp", "t_start", "price", "vmove", "ev")
MODEL_MARKER = "S6_MODEL_JSON"
SLICES = s1.SLICES
MOVE_NAME = {1: "toward", -1: "away", 0: "flat"}


# --------------------------------------------------------------------------- join (fleet)

def quote_eligible(order: Mapping[str, Any]) -> bool:
    """A side the two-way join can flip; soccer h2h is three-way, so a two-way de-vig would be wrong."""
    side = str(order.get("side") or "").lower()
    market = str(order.get("market") or "").lower()
    return side in pe.OPPOSITE and not (str(order.get("sport") or "").lower() == "soccer" and "h2h" in market)


def _implied(price: Any) -> float | None:
    try:
        return pe.implied(price)
    except (TypeError, ValueError):
        return None


def quote_features(order: Mapping[str, Any], series: Sequence[tuple], ages: Mapping[str, Any]) -> dict[str, Any]:
    """One pass over the order's book_quotes series up to submit: per-book two-way fairs at OUR line (n_books, disp,
    consensus median, Pinnacle) and our venue's own quote on our side at the reference fetch and at submit. Pure."""
    sub = parse_ts(order.get("submitted_at"))
    market = str(order.get("market") or "").lower()
    side = str(order.get("side") or "").lower()
    line = pe._line(order.get("line"))
    opp_line = (-line if line is not None else None) if "spread" in market else line
    ours, theirs = (side, line), (pe.OPPOSITE.get(side), opp_line)
    age = ages.get("pin_age_s") if ages.get("pin_age_s") is not None else ages.get("cons_age_s")
    ref_kind = "pin" if ages.get("pin_age_s") is not None else ("cons" if age is not None else None)
    ref_at = sub - timedelta(seconds=float(age)) if (sub is not None and age is not None) else None
    venue = "kalshi" if "kalshi" in str(order.get("venue")) else "polymarket"
    last: dict[str, dict[str, Any]] = {}
    v_ref = v_sub = None
    for captured, _updated, bk, sel, ln, price in series:
        if captured is None:
            continue
        if sub is None or captured > sub:
            break
        if bk == venue and sel == side and ln == line:
            v_sub = pe.contract_price(price)
            if ref_at is not None and captured <= ref_at:
                v_ref = pe.contract_price(price)
        if bk in pe.SELF_VENUES:
            continue
        if (sel, ln) == ours:
            last.setdefault(bk, {})["us"] = price
        elif (sel, ln) == theirs:
            last.setdefault(bk, {})["them"] = price
    fairs: dict[str, float] = {}
    for bk, d in last.items():
        if "us" in d and "them" in d:
            p_us, p_them = _implied(d["us"]), _implied(d["them"])
            if p_us and p_them:
                fairs[bk] = pe.devig(p_us, p_them)
    vals = sorted(fairs.values())
    mid = len(vals) // 2
    cons_fair = None if not vals else (vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2)
    pin_fair = fairs.get("pinnacle")
    ref_fair = pin_fair if pin_fair is not None else cons_fair
    vmove = None
    if ref_at is not None and ref_fair is not None and v_ref is not None and v_sub is not None:
        if abs(v_sub - v_ref) < 1e-9:
            vmove = 0
        else:
            vmove = 1 if (v_sub - v_ref) * (ref_fair - v_ref) > 0 else -1
    return {"n_books": len(fairs), "disp_pp": 100 * (vals[-1] - vals[0]) if len(vals) >= 2 else None,
            "cons_fair": cons_fair, "pin_fair": pin_fair, "vmove": vmove,
            "vmove_ref": ref_kind if vmove is not None else None}


def price_terms(order: Mapping[str, Any]) -> dict[str, Any]:
    """Requested contract price, fee per contract and the breakeven known at submit."""
    stake = float(order["fill_stake_dollars"])
    raw_fill = order.get("fill_price") if order.get("fill_price") not in (None, 0) else order.get("venue_avg_price")
    fill = pe.contract_price(raw_fill)
    req = pe.contract_price(order.get("requested_price")) or fill
    contracts = stake / fill if fill else None
    fee_per = (s1._num(order.get("fees_dollars")) or 0.0) / contracts if contracts else 0.0
    be = (req + fee_per) if req else None
    return {"req_p": req, "fee_per": fee_per, "be": be}


def study_row(order: Mapping[str, Any], ages: Mapping[str, Any], qf: Mapping[str, Any] | None,
              shard_ok: bool) -> dict[str, Any]:
    row = s1.study_row(order, ages, None)
    row.pop("move", None)
    sub, ko = parse_ts(order.get("submitted_at")), parse_ts(order.get("commence_time"))
    row.update(price_terms(order))
    outcome = order.get("outcome")
    row.update({"hours_to_start": (ko - sub).total_seconds() / 3600.0 if sub and ko else None,
                "won": 1 if outcome == "won" else (0 if outcome == "lost" else None),
                "quote_eligible": quote_eligible(order), "shard_ok": shard_ok})
    qf = qf or {}
    row.update({"n_books": qf.get("n_books") if (shard_ok and qf) else None, "disp_pp": qf.get("disp_pp"),
                "vmove": qf.get("vmove"), "vmove_ref": qf.get("vmove_ref")})
    return row


def cmd_join(args) -> int:
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass
    from syndicate.features.shared.odds_book_quotes import kickoff_shard_date, resolve_book_quotes_path

    raw = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    orders, drops = s1.population(raw.get("orders", []) if isinstance(raw, Mapping) else raw)
    del raw
    beats = pe.load_heartbeats(orders)
    indexed = s1.index_beats(beats)
    stamps = [parse_ts(b.get("captured_at")) for lines in beats.values() for b in lines]
    stamps = [s for s in stamps if s is not None]
    ages = [s1.reference_ages(o, indexed) for o in orders]
    del beats, indexed
    print(f"S6_JOIN ages done orders={len(orders)}", flush=True)
    meta: dict[str, Any] = {"drops": drops, "first_heartbeat_at": min(stamps).isoformat() if stamps else None,
                            "shard_days": {}}
    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, o in enumerate(orders):
        groups[(str(o.get("sport") or "").lower(),
                str(kickoff_shard_date({"commence_time": o.get("commence_time")})))].append(i)
    feats: list[dict | None] = [None] * len(orders)
    shard_ok = [False] * len(orders)
    for n_group, ((sport, day), idx) in enumerate(sorted(groups.items())):
        for i in idx:
            ko = parse_ts(orders[i].get("commence_time"))
            days = {day, ko.date().isoformat() if ko else None} - {None, "None"}
            have = [d for d in sorted(days) if resolve_book_quotes_path(sport, d).is_file()]
            shard_ok[i] = bool(have)
            for d in have:
                if d not in meta["shard_days"].setdefault(sport, []):
                    meta["shard_days"][sport].append(d)
        subset = [orders[i] for i in idx if quote_eligible(orders[i])]
        if not subset:
            continue
        quotes = pe.load_quotes(subset)
        for i in idx:
            o = orders[i]
            if not quote_eligible(o):
                continue
            key = pe.quote_key(o.get("event_id"), o.get("market"), o.get("segment"), o.get("player_name"))
            feats[i] = quote_features(o, quotes.get(key) or [], ages[i])
        del quotes
        if n_group % 25 == 0:
            print(f"S6_JOIN group {n_group + 1}/{len(groups)} {sport} {day}", flush=True)
    rows = [study_row(o, a, f, ok) for o, a, f, ok in zip(orders, ages, feats, shard_ok)]
    Path(args.out).write_text(json.dumps({"meta": meta, "rows": rows}), encoding="utf-8")
    print(f"S6_JOIN orders={len(orders)} pin_known={sum(a['pin_age_s'] is not None for a in ages)} "
          f"cons_known={sum(a['cons_age_s'] is not None for a in ages)} "
          f"books_known={sum(r['n_books'] is not None for r in rows)} "
          f"vmove_known={sum(r['vmove'] is not None for r in rows)} -> {args.out}", flush=True)
    return 0


# --------------------------------------------------------------------------- windows and features

def window_of(row: Mapping[str, Any], first_beat: str | None) -> str:
    sub = parse_ts(row.get("submitted"))
    if sub is None:
        return "none"
    if first_beat and sub < parse_ts(first_beat):
        return "pre_heartbeat"
    if sub < parse_ts(FIT_END):
        return "FIT"
    if sub < parse_ts(TEST_END):
        return "TEST"
    if sub < parse_ts(FORWARD_START):
        return "gap"
    return "FORWARD"


def _logit(p: float) -> float:
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


def _log1p_scaled(value: Any, scale: float = 1.0) -> float | None:
    return None if value is None else math.log1p(max(0.0, float(value)) / scale)


def raw_features(row: Mapping[str, Any]) -> dict[str, float | None]:
    ev = row.get("ev_pct")
    return {"pin_age": _log1p_scaled(row.get("pin_age_s"), 60.0),
            "cons_age": _log1p_scaled(row.get("cons_age_s"), 60.0),
            "n_books": None if row.get("n_books") is None else float(row["n_books"]),
            "disp": row.get("disp_pp"),
            "t_start": _log1p_scaled(row.get("hours_to_start")),
            "price": None if not row.get("req_p") else _logit(float(row["req_p"])),
            "vmove": None if row.get("vmove") is None else float(row["vmove"]),
            "ev": None if ev is None else min(max(float(ev), -10.0), 30.0)}


def fit_scaler(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """FIT mean / SD per feature over non-missing values. A feature with < 30 values or SD 0 is dropped (None)."""
    out: dict[str, Any] = {}
    feats = [raw_features(r) for r in rows]
    for name in FEATURES:
        vals = [f[name] for f in feats if f[name] is not None]
        if len(vals) < 30:
            out[name] = None
            continue
        mean = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))
        out[name] = None if sd <= 0 else {"mean": mean, "sd": sd, "n": len(vals)}
    return out


def design(rows: Sequence[Mapping[str, Any]], scaler: Mapping[str, Any]):
    import numpy as np

    X = np.zeros((len(rows), 1 + len(FEATURES)))
    X[:, 0] = 1.0
    for i, r in enumerate(rows):
        f = raw_features(r)
        for j, name in enumerate(FEATURES, start=1):
            s = scaler.get(name)
            if s is None or f[name] is None:
                continue
            X[i, j] = min(max((f[name] - s["mean"]) / s["sd"], -CLIP_Z), CLIP_Z)
    offset = np.array([_logit(float(r["be"])) if r.get("be") else 0.0 for r in rows])
    return X, offset


# --------------------------------------------------------------------------- model

def fit_logistic(X, y, offset, lam: float, iters: int = 50):
    """Newton-Raphson for the L2 logistic with an offset; the intercept (column 0) is unpenalized."""
    import numpy as np

    theta = np.zeros(X.shape[1])
    pen = np.full(X.shape[1], float(lam))
    pen[0] = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-(offset + X @ theta)))
        g = X.T @ (p - y) + pen * theta
        H = (X * (p * (1 - p))[:, None]).T @ X + np.diag(pen) + 1e-9 * np.eye(X.shape[1])
        step = np.linalg.solve(H, g)
        theta = theta - step
        if float(np.max(np.abs(step))) < 1e-8:
            break
    return theta


def log_loss(X, y, offset, theta) -> float:
    import numpy as np

    p = np.clip(1.0 / (1.0 + np.exp(-(offset + X @ theta))), 1e-12, 1 - 1e-12)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def scores(rows: Sequence[Mapping[str, Any]], X, offset, theta) -> list[float]:
    """Predicted flat return per order: P(won) / breakeven - 1."""
    import numpy as np

    p = 1.0 / (1.0 + np.exp(-(offset + X @ np.asarray(theta))))
    return [float(p[i] / r["be"] - 1.0) if r.get("be") else 0.0 for i, r in enumerate(rows)]


def time_folds(rows: Sequence[Mapping[str, Any]], k: int = CV_FOLDS) -> list[int]:
    """Fold per row: events ordered by their first submit, cut into k contiguous blocks of equal event count."""
    first: dict[str, str] = {}
    for r in rows:
        s = str(r.get("submitted") or "")
        if r["game"] not in first or s < first[r["game"]]:
            first[r["game"]] = s
    order = sorted(first, key=lambda g: (first[g], g))
    fold_of = {g: min(k - 1, i * k // len(order)) for i, g in enumerate(order)}
    return [fold_of[r["game"]] for r in rows]


def quantile_cut(values: Sequence[float], keep: float) -> float:
    """The score cut that keeps the top `keep` share: sorted ascending, the value at floor((1 - keep) * n)."""
    s = sorted(values)
    return s[min(len(s) - 1, int(math.floor((1.0 - keep) * len(s))))]


def fit_stage(fit_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    import numpy as np

    scaler = fit_scaler(fit_rows)
    X, off = design(fit_rows, scaler)
    y = np.array([float(r["won"]) if r.get("won") is not None else -1.0 for r in fit_rows])
    lab = y >= 0
    folds = np.array(time_folds(fit_rows))
    cv: list[dict[str, Any]] = []
    oof_by_lam: dict[float, list[float]] = {}
    for lam in LAMBDAS:
        loss_sum, n_tot = 0.0, 0
        oof = [0.0] * len(fit_rows)
        for k in range(CV_FOLDS):
            tr = (folds != k) & lab
            te = folds == k
            th = fit_logistic(X[tr], y[tr], off[tr], lam)
            te_lab = te & lab
            if te_lab.any():
                loss_sum += log_loss(X[te_lab], y[te_lab], off[te_lab], th) * int(te_lab.sum())
                n_tot += int(te_lab.sum())
            idx = np.where(te)[0]
            for i, s in zip(idx, scores([fit_rows[i] for i in idx], X[te], off[te], th)):
                oof[int(i)] = s
        cv.append({"lambda": lam, "oof_log_loss": loss_sum / n_tot if n_tot else None})
        oof_by_lam[lam] = oof
    best = min(cv, key=lambda c: (round(c["oof_log_loss"], 6), -c["lambda"]))
    lam = best["lambda"]
    oof = oof_by_lam[lam]
    keep_table = []
    for q in KEEP_GRID:
        cut = quantile_cut(oof, q)
        kept = [r for r, s in zip(fit_rows, oof) if s >= cut]
        keep_table.append({"keep": q, "kept": s1.flat(kept), "diff": s1.clustered_diff(kept, fit_rows)})
    positive = [t for t in keep_table if t["diff"]["d"] is not None and t["diff"]["d"] > 0]
    chosen = max(positive, key=lambda t: (round(t["diff"]["d"], 9), t["keep"]))["keep"] if positive else None
    theta = fit_logistic(X[lab], y[lab], off[lab], lam)
    in_sample = scores(fit_rows, X, off, theta)
    return {"scaler": scaler, "cv": cv, "lambda": lam, "keep_table": keep_table, "keep": chosen,
            "all": s1.flat(fit_rows), "theta": [float(t) for t in theta],
            "cut": quantile_cut(in_sample, chosen) if chosen is not None else None,
            "in_sample_scores": in_sample, "fit_n": len(fit_rows), "fit_labelled": int(lab.sum())}


def apply_model(rows: Sequence[Mapping[str, Any]], model: Mapping[str, Any]) -> list[float]:
    X, off = design(rows, model["scaler"])
    return scores(rows, X, off, model["theta"])


def judge(rows: Sequence[Mapping[str, Any]], model: Mapping[str, Any]) -> dict[str, Any]:
    """Kept (score >= the FIT cut) vs all on a judged set: D with its clustered 95% interval, plus a bootstrap check."""
    sc = apply_model(rows, model) if rows else []
    kept = [r for r, s in zip(rows, sc) if s >= model["cut"]]
    dropped = [r for r, s in zip(rows, sc) if s < model["cut"]]
    kept_ids = {id(r) for r in kept}
    boot = s1.bootstrap_diff([(r["game"], r["ret"], id(r) in kept_ids) for r in rows]) if kept else None
    return {"all": s1.flat(rows), "kept": s1.flat(kept), "dropped": s1.flat(dropped),
            "diff": s1.clustered_diff(kept, rows), "kept_minus_dropped": s1.clustered_diff(kept, dropped),
            "bootstrap_check": boot, "keep_share_pct": 100 * len(kept) / len(rows) if rows else None}


def verdict(fit: Mapping[str, Any], test: Mapping[str, Any] | None) -> str:
    if fit.get("keep") is None:
        return "NO CHALLENGER (no keep share gains on FIT out of fold)"
    hi = ((test or {}).get("diff") or {}).get("hi")
    if hi is not None and hi < 0:
        return "KILL (TEST D's 95% upper bound < 0)"
    return ("FORWARD TEST (no early kill; orders submitted from 2026-11-20 decide at 150 events, "
            "GO iff the 95% lower bound > 0)")


def model_doc(fit: Mapping[str, Any], keep: float | None = None, cut: float | None = None) -> dict[str, Any]:
    return {"features": list(FEATURES), "scaler": fit["scaler"], "theta": fit["theta"], "lambda": fit["lambda"],
            "keep": fit["keep"] if keep is None else keep, "cut": fit["cut"] if cut is None else cut,
            "clip_z": CLIP_Z, "fit_end": FIT_END, "test_end": TEST_END, "forward_start": FORWARD_START,
            "forward_events": FORWARD_EVENTS}


def report(rows: Sequence[Mapping[str, Any]], meta: Mapping[str, Any]) -> dict[str, Any]:
    first_beat = meta.get("first_heartbeat_at")
    win: dict[str, list] = defaultdict(list)
    for r in rows:
        win[window_of(r, first_beat)].append(r)
    fit_rows, test_rows = win["FIT"], win["TEST"]
    fit = fit_stage(fit_rows)
    out: dict[str, Any] = {"windows": {k: len(v) for k, v in sorted(win.items())},
                           "fit": {k: v for k, v in fit.items() if k != "in_sample_scores"}}
    if fit["keep"] is None:
        # Nothing to test. TEST is reported at the keep share with the largest FIT D, deciding nothing.
        best = max(fit["keep_table"], key=lambda t: t["diff"]["d"] if t["diff"]["d"] is not None else -1e9)
        desc = model_doc(fit, keep=best["keep"], cut=quantile_cut(fit["in_sample_scores"], best["keep"]))
        out.update({"model": desc, "test_descriptive": judge(test_rows, desc), "verdict": verdict(fit, None)})
        return out
    model = model_doc(fit)
    out["model"] = model
    out["test"] = judge(test_rows, model)
    out["test_slices"] = {name: judge([r for r in test_rows if pred(r)], model) for name, pred in SLICES}
    out["verdict"] = verdict(fit, out["test"])
    return out


def forward(rows: Sequence[Mapping[str, Any]], meta: Mapping[str, Any], model: Mapping[str, Any]) -> dict[str, Any]:
    """The registered forward test: settled population orders submitted >= FORWARD_START, on the first 150 events
    by their first submit time. GO iff D's 95% lower bound > 0."""
    need = int(model.get("forward_events", FORWARD_EVENTS))
    fwd = [r for r in rows if window_of(r, meta.get("first_heartbeat_at")) == "FORWARD"]
    first: dict[str, str] = {}
    for r in fwd:
        if r["game"] not in first or r["submitted"] < first[r["game"]]:
            first[r["game"]] = r["submitted"]
    events = sorted(first, key=lambda g: (first[g], g))
    if len(events) < need:
        return {"events": len(events), "orders": len(fwd), "verdict": f"NOT YET ({len(events)} of {need} events)"}
    take = set(events[:need])
    part = [r for r in fwd if r["game"] in take]
    res = judge(part, model)
    lo = res["diff"]["lo"]
    res.update({"events": len(take), "orders": len(part),
                "slices": {name: judge([r for r in part if pred(r)], model) for name, pred in SLICES},
                "verdict": "GO" if lo is not None and lo > 0 else "NO-GO"})
    return res


# --------------------------------------------------------------------------- coverage (counts only, no outcome)

def coverage(rows: Sequence[Mapping[str, Any]], meta: Mapping[str, Any]) -> dict[str, Any]:
    first_beat = meta.get("first_heartbeat_at")
    by_win: dict[str, Counter] = defaultdict(Counter)
    by_day: dict[str, Counter] = defaultdict(Counter)
    vm: dict[str, Counter] = defaultdict(Counter)
    events: dict[str, set] = defaultdict(set)
    for r in rows:
        w = window_of(r, first_beat)
        f = raw_features(r)
        for c in (by_win[f"{w}|{r['book']}"], by_win[w]):
            c["n"] += 1
            c["won/lost"] += r.get("won") is not None
            c["be"] += bool(r.get("be"))
            c["quote_eligible"] += bool(r.get("quote_eligible"))
            c["shard_ok"] += bool(r.get("shard_ok"))
            for name in FEATURES:
                c[name] += f[name] is not None
            c["n_books>=1"] += (r.get("n_books") or 0) >= 1
        events[w].add(r["game"])
        if w in ("FIT", "TEST"):
            d = by_day[f"{r['day']}|{w}"]
            d["n"] += 1
            for name in FEATURES:
                d[name] += f[name] is not None
            if r.get("vmove") is not None:
                vm[w][f"{MOVE_NAME[int(r['vmove'])]}|{r.get('vmove_ref')}"] += 1
    days_all = {r["day"] for r in rows if r.get("day")}
    fam_sets = {"orders with a consensus capture age": {r["day"] for r in rows if r.get("cons_age_s") is not None},
                "orders with n_books >= 1": {r["day"] for r in rows if (r.get("n_books") or 0) >= 1},
                "orders with a venue move": {r["day"] for r in rows if r.get("vmove") is not None}}
    fam = {"orders": s1._dates_summary(days_all),
           "book_quotes shards read": s1._dates_summary({d for v in (meta.get("shard_days") or {}).values() for d in v})}
    fam.update({k: s1._dates_summary(v) for k, v in fam_sets.items()})
    inter = set(days_all)
    for v in fam_sets.values():
        inter &= v
    return {"families": fam, "intersection": s1._dates_summary(inter), "first_heartbeat_at": first_beat,
            "by_window": {k: dict(v) for k, v in sorted(by_win.items())},
            "events": {k: len(v) for k, v in sorted(events.items())},
            "by_day": {k: dict(v) for k, v in sorted(by_day.items())},
            "vmove_classes": {k: dict(v) for k, v in sorted(vm.items())}, "drops": meta.get("drops")}


# --------------------------------------------------------------------------- rendering (counts and % only)

def _pct(v: float | None, digits: int = 2) -> str:
    return "n/a" if v is None else f"{v:+.{digits}f}"


def _ci(s: Mapping[str, Any]) -> str:
    return "n/a" if s.get("lo") is None else f"[{s['lo']:+.2f}, {s['hi']:+.2f}]"


def _flat_cells(s: Mapping[str, Any]) -> str:
    return f"{s['n']} / {s['events']} | {_pct(s['roi'])}% | {_ci(s)}"


def _boot(b: Sequence[float] | None) -> str:
    return "n/a" if not b else f"[{b[0]:+.2f}, {b[1]:+.2f}]"


def render_coverage(cov: Mapping[str, Any]) -> str:
    cols = ["n", "won/lost", "be", "quote_eligible", "shard_ok"] + list(FEATURES) + ["n_books>=1"]
    lines = ["# S6 coverage (counts only, no outcome)", "", "| family | dates | first | last | gaps |",
             "|---|---|---|---|---|"]
    for name, s in cov["families"].items():
        lines.append(f"| {name} | {s['dates']} | {s['first']} | {s['last']} | {', '.join(s['gaps']) or 'none'} |")
    i = cov["intersection"]
    lines += ["", f"Intersection (orders, consensus age, n_books >= 1, venue move): {i['dates']} dates "
              f"({i['first']}..{i['last']}); first heartbeat {cov['first_heartbeat_at']}", "",
              f"events per window: {cov['events']}", "",
              "| window / book | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for k, c in cov["by_window"].items():
        lines.append(f"| {k} | " + " | ".join(str(c.get(x, 0)) for x in cols) + " |")
    dcols = ["n"] + list(FEATURES)
    lines += ["", "| submit day / window | " + " | ".join(dcols) + " |", "|---" * (len(dcols) + 1) + "|"]
    for k, c in cov["by_day"].items():
        lines.append(f"| {k} | " + " | ".join(str(c.get(x, 0)) for x in dcols) + " |")
    lines += ["", f"venue-move classes (feature values, not outcomes): {cov['vmove_classes']}", "",
              f"drops: {cov['drops']}"]
    return "\n".join(lines)


def render_report(rep: Mapping[str, Any]) -> str:
    fit = rep["fit"]
    lines = ["# S6 report (flat fee-net ROI per order, %, event-clustered 95%)", "", f"windows: {rep['windows']}", "",
             f"FIT: {fit['fit_n']} orders ({fit['fit_labelled']} won/lost); all: {_flat_cells(fit['all'])}", "",
             "## FIT: penalty by 5-fold event-grouped time-ordered CV", "", "| lambda | OOF log loss |", "|---|---|"]
    for c in fit["cv"]:
        lines.append(f"| {c['lambda']:g} | {c['oof_log_loss']:.6f} |")
    lines += ["", f"chosen lambda = {fit['lambda']:g}", "", "## FIT: keep share on out-of-fold scores", "",
              "| keep | kept n / events | kept ROI | D = kept - all [95%] |", "|---|---|---|---|"]
    for t in fit["keep_table"]:
        lines.append(f"| {t['keep']:.1f} | {t['kept']['n']} / {t['kept']['events']} | {_pct(t['kept']['roi'])}% |"
                     f" {_pct(t['diff']['d'])} {_ci(t['diff'])} |")
    lines += ["", f"chosen keep share = {fit['keep']}; score cut = {fit['cut']}", "",
              "## Final model (standardized coefficients: logit shift per +1 SD; intercept first)", "",
              "| term | coef | FIT mean | FIT sd | n known |", "|---|---|---|---|---|",
              f"| intercept | {fit['theta'][0]:+.4f} | | | |"]
    for name, coef in zip(FEATURES, fit["theta"][1:]):
        s = fit["scaler"].get(name)
        cells = "dropped | | " if not s else f"{s['mean']:.4f} | {s['sd']:.4f} | {s['n']}"
        lines.append(f"| {name} | {coef:+.4f} | {cells} |")
    test = rep.get("test") or rep.get("test_descriptive")
    label = "TEST (registered)" if rep.get("test") else "TEST (descriptive only: no challenger from FIT)"
    d, kd = test["diff"], test["kept_minus_dropped"]
    lines += ["", f"## {label}", "", "| set | n / events | ROI | 95% |", "|---|---|---|---|",
              f"| all | {_flat_cells(test['all'])} |", f"| kept | {_flat_cells(test['kept'])} |",
              f"| dropped | {_flat_cells(test['dropped'])} |", "",
              f"**D = kept - all: {_pct(d['d'])} pp {_ci(d)} (se {_pct(d['se'])})**; kept - dropped {_pct(kd['d'])} "
              f"{_ci(kd)}; keep share {_pct(test['keep_share_pct'], 1)}%; bootstrap check of D (seeded, not "
              f"registered): {_boot(test['bootstrap_check'])}", "", f"**verdict: {rep['verdict']}**", ""]
    if rep.get("test_slices"):
        lines += ["| TEST slice (descriptive) | all n / events | all ROI | kept n / events | kept ROI | D [95%] |",
                  "|---|---|---|---|---|---|"]
        for name, s in rep["test_slices"].items():
            lines.append(f"| {name} | {s['all']['n']} / {s['all']['events']} | {_pct(s['all']['roi'])}% |"
                         f" {s['kept']['n']} / {s['kept']['events']} | {_pct(s['kept']['roi'])}% |"
                         f" {_pct(s['diff']['d'])} {_ci(s['diff'])} |")
    return "\n".join(lines)


def render_forward(res: Mapping[str, Any]) -> str:
    if "diff" not in res:
        return f"S6 FORWARD: {res['verdict']} (orders {res['orders']})"
    lines = [f"# S6 forward test (orders submitted >= {FORWARD_START}, first {res['events']} events)", "",
             "| set | n / events | ROI | 95% |", "|---|---|---|---|", f"| all | {_flat_cells(res['all'])} |",
             f"| kept | {_flat_cells(res['kept'])} |", f"| dropped | {_flat_cells(res['dropped'])} |", "",
             f"**D = kept - all: {_pct(res['diff']['d'])} pp {_ci(res['diff'])}**; keep share "
             f"{_pct(res['keep_share_pct'], 1)}%", "", f"**verdict: {res['verdict']}**", "",
             "| slice (descriptive) | all n / events | all ROI | kept ROI | D [95%] |", "|---|---|---|---|---|"]
    for name, s in res["slices"].items():
        lines.append(f"| {name} | {s['all']['n']} / {s['all']['events']} | {_pct(s['all']['roi'])}% |"
                     f" {_pct(s['kept']['roi'])}% | {_pct(s['diff']['d'])} {_ci(s['diff'])} |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- commands

def _load_rows(path: str) -> tuple[list[dict], dict]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return doc["rows"], doc["meta"]


def load_model_from(path: str) -> dict[str, Any]:
    """The frozen model: a JSON file, or the fenced json block after the S6_MODEL_JSON marker in the findings."""
    text = Path(path).read_text(encoding="utf-8")
    if path.endswith(".json"):
        return json.loads(text)
    m = re.search(MODEL_MARKER + r".*?```json\s*(\{.*?\})\s*```", text, re.S)
    if not m:
        raise SystemExit(f"no {MODEL_MARKER} block in {path}")
    return json.loads(m.group(1))


def cmd_coverage(args) -> int:
    rows, meta = _load_rows(args.rows)
    sys.stdout.write(render_coverage(coverage(rows, meta)) + "\n")
    return 0


def cmd_report(args) -> int:
    rows, meta = _load_rows(args.rows)
    rep = report(rows, meta)
    md = render_report(rep)
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    if args.out_model:
        Path(args.out_model).write_text(json.dumps(rep["model"], indent=1), encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(md, encoding="utf-8")
    sys.stdout.write(md + "\n")
    return 0


def cmd_forward(args) -> int:
    rows, meta = _load_rows(args.rows)
    sys.stdout.write(render_forward(forward(rows, meta, load_model_from(args.model_from))) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("join")
    j.add_argument("--ledger", required=True)
    j.add_argument("--out", required=True)
    c = sub.add_parser("coverage")
    c.add_argument("--rows", required=True)
    r = sub.add_parser("report")
    r.add_argument("--rows", required=True)
    r.add_argument("--out-md", default=None)
    r.add_argument("--out-json", default=None)
    r.add_argument("--out-model", default=None)
    f = sub.add_parser("forward")
    f.add_argument("--rows", required=True)
    f.add_argument("--model-from", required=True)
    args = parser.parse_args(argv)
    return {"join": cmd_join, "coverage": cmd_coverage, "report": cmd_report, "forward": cmd_forward}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
