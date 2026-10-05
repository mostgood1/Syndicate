"""Fit and validate `nba_prop_calibration.json` (lane `nba-prop-calibration`).

Data: the as-of 2025-26 smart-sim output and actuals collected by `scripts/backtest_nba_lines_props.py`
(run it first; this reads its `--out` cache). Each row is one smart-sim player-game that played, with the sim's
per-stat mean / sd / minutes, the actual box line, and the player's season-to-date rate from games strictly
before the date -- the same quantities `nba_prop_calibration.own_rates` builds from `boxscores_history.csv`.

Method (every transform goes through `syndicate.features.shared.nba_prop_calibration`'s own functions):
  1. TRAIN = smart-sim regular-season dates < --split; TEST = later regular-season dates + playoffs.
  2. Fit w_s (rate shrink, grid over W_BOUNDS) by test-free MAE on TRAIN; players with < MIN_GAMES prior
     games keep the sim mean, exactly as the module does.
  2b. Fit b_s (season-average blend weight on the shrunk mean, grid over B_BOUNDS) by MAE on TRAIN, after w.
  3. Fit k_s (sd scale, grid over K_BOUNDS) by CRPS on TRAIN over the whole predictive distribution, with the
     FINAL mean -- so k is fit for the mean it will be paired with. (A log-loss fit at one book-like line runs to
     the grid edge; see fit().)
  The previous estimator (no blend) is fit and scored beside it, so the blend's increment is measured, not assumed.
  4. Score TEST with the TRAIN constants: MAE vs the served sim and vs the own average; Brier vs the served
     Normal and vs the own-average distribution; game-clustered 95% CIs. pr/pa/ra are scored through
     `combo_scale` (the edges' independence sigma).
  5. Refit on ALL rows -> the production constants written by --write.

Usage:
  py -3 scripts/fit_nba_prop_calibration.py --bt-out C:/tmp/nba_bt/out --write C:/tmp/nba_bt/nba_prop_calibration.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import nba_prop_calibration as cal  # noqa: E402

COMBOS = {"pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")}


def _load_bt():
    spec = importlib.util.spec_from_file_location("_bt_nba", REPO / "scripts" / "backtest_nba_lines_props.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def collect(bt, out: Path) -> List[Dict]:
    class A:  # the harness's args shape
        pass
    a = A()
    a.out = out
    dates = bt._dates(bt.RS_START, bt.PO_END)
    sb = bt.fetch_scoreboards(a, dates)  # cached
    phase_of = {}
    from collections import Counter
    for d, gs in sb.items():
        st = Counter(g["season_type"] for g in gs).most_common(1)[0][0]
        phase_of[d] = "regular" if st == 2 and d <= bt.RS_END else ("playoff" if st == 3 else f"type{st}")
    manifest = json.loads((out / "asof_manifest.json").read_text(encoding="utf-8"))
    hist = bt.History(bt.fetch_player_logs(a))
    rows, counts = bt._collect_sim_players(a, manifest, hist, phase_of)
    print(f"collected {len(rows)} player-games; {dict(counts)}", flush=True)
    return rows


def mean_after(r: Dict, s: str, w: Dict[str, float], b: Dict[str, float] = None) -> float:
    """Final mean via the module's own estimator: rate shrink (w), then season-average blend (b); pra moves by
    the pts+reb+ast deltas; pr/pa/ra are sums. Players with < MIN_GAMES prior games keep the sim mean."""
    b = b or {}
    if s in COMBOS:
        if s != "pra":
            return sum(mean_after(r, p, w, b) for p in COMBOS[s])
        if all(p in w or p in b for p in COMBOS["pra"]):
            return r["mean"]["pra"] + sum(mean_after(r, p, w, b) - r["mean"][p] for p in COMBOS["pra"])
        return r["mean"]["pra"]
    m = r["mean"][s]
    if (s not in w and s not in b) or r["proj_min"] <= 0 or r["n_prior"] < cal.MIN_GAMES:
        return m
    t = cal.shrink_mean(m, r["proj_min"], r["per_min"][s], w[s]) if s in w else m
    return cal.blend_mean(t, r["base"][s], b[s]) if s in b else t


def sd_after(r: Dict, s: str, k: Dict[str, float], scaled: bool = True) -> float:
    if s in COMBOS and s != "pra":
        sds = {p: r["sd"][p] for p in COMBOS[s]}
        base = math.sqrt(sum(v ** 2 for v in sds.values()))
        if not scaled:
            return base
        kk = cal.combo_scale(COMBOS[s], sds, k)
        return base * (kk if kk is not None else 1.0)
    sd = r["sd"][s]
    return sd * (k.get(s, 1.0) if scaled else 1.0)


def actual(r: Dict, s: str) -> float:
    return sum(r["act"][p] for p in COMBOS[s]) if s in COMBOS and s != "pra" else r["act"][s]


def own_avg(r: Dict, s: str) -> float:
    return sum(r["base"][p] for p in COMBOS[s]) if s in COMBOS and s != "pra" else r["base"][s]


def p_over(line: float, mu: float, sd: float) -> float:
    return 1 - 0.5 * (1 + math.erf((line - mu) / (sd * math.sqrt(2))))


def _ll(p: float, y: int) -> float:
    p = min(1 - 1e-3, max(1e-3, p))
    return -(math.log(p) if y else math.log(1 - p))


def _usable(r: Dict, s: str) -> bool:
    parts = COMBOS[s] if s in COMBOS and s != "pra" else (s,)
    return all((r["sd"].get(p) or 0) > 0.05 for p in parts)


def fit(rows: List[Dict], use_blend: bool = True) -> Dict[str, Dict[str, float]]:
    wgrid = [round(i * 0.05, 2) for i in range(int(cal.W_BOUNDS[1] / 0.05) + 1)]
    kgrid = [round(cal.K_BOUNDS[0] + i * 0.05, 2) for i in range(int((cal.K_BOUNDS[1] - cal.K_BOUNDS[0]) / 0.05) + 1)]
    w: Dict[str, float] = {}
    for s in cal.RATE_STATS:
        w[s] = min(wgrid, key=lambda x: sum(abs(mean_after(r, s, {s: x}) - actual(r, s)) for r in rows))
    # season-average blend, fit AFTER w on the shrunk mean (b = weight kept on the shrunk sim mean)
    b: Dict[str, float] = {}
    if use_blend:
        bgrid = [round(i * 0.05, 2) for i in range(int(cal.B_BOUNDS[1] / 0.05) + 1)]
        for s in cal.RATE_STATS:
            b[s] = min(bgrid, key=lambda x: sum(abs(mean_after(r, s, w, {s: x}) - actual(r, s)) for r in rows))
    # k by CRPS over the WHOLE predictive distribution. A log-loss fit at one book-like line runs to the grid
    # edge (k = 3.0 measured): near that line the mean has little resolution, so flattening every probability
    # toward 0.5 wins there while ruining every alternate line -- the same trap lane wnba-prop-dispersion hit.
    k: Dict[str, float] = {}
    for s in cal.SD_STATS:
        q = [r for r in rows if _usable(r, s)]
        pre = [(mean_after(r, s, w, b), sd_after(r, s, {}, scaled=False), actual(r, s)) for r in q]
        k[s] = min(kgrid, key=lambda x: sum(crps_normal(mu, sd * x, y) for mu, sd, y in pre))
    return {"w": w, "b": b, "k": k}


def crps_normal(mu: float, sd: float, y: float) -> float:
    """Closed-form CRPS of N(mu, sd) at y (lower is better; a proper score for the whole distribution)."""
    z = (y - mu) / sd
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    cdf = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return sd * (z * (2 * cdf - 1) + 2 * pdf - 1 / math.sqrt(math.pi))


def evaluate(bt, rows: List[Dict], c: Dict[str, Dict[str, float]]) -> Dict:
    w, b, k = c["w"], c.get("b") or {}, c["k"]
    res = {}

    def ci(v):
        p, lo, hi = bt._boot_ci(v)
        return {"point": round(p, 5), "ci95": [round(lo, 5), round(hi, 5)]}
    for s in list(cal.SD_STATS) + ["pr", "pa", "ra"]:
        q = [r for r in rows if _usable(r, s)]
        if not q:
            continue
        e_cal = [(r["gid"], abs(mean_after(r, s, w, b) - actual(r, s)) - abs(mean_after(r, s, {}) - actual(r, s))) for r in q]
        e_avg = [(r["gid"], abs(mean_after(r, s, w, b) - actual(r, s)) - abs(own_avg(r, s) - actual(r, s))) for r in q]
        b_srv, b_avg = [], []
        for r in q:
            L = math.floor(own_avg(r, s)) + 0.5
            y = int(actual(r, s) > L)
            p_cal = p_over(L, mean_after(r, s, w, b), sd_after(r, s, k))
            p_srv = p_over(L, mean_after(r, s, {}), sd_after(r, s, k, scaled=False))
            p_own = p_over(L, own_avg(r, s), sd_after(r, s, k))
            b_srv.append((r["gid"], (p_cal - y) ** 2 - (p_srv - y) ** 2))
            b_avg.append((r["gid"], (p_cal - y) ** 2 - (p_own - y) ** 2))

        c_d = [(r["gid"], crps_normal(mean_after(r, s, w, b), sd_after(r, s, k), actual(r, s))
                - crps_normal(mean_after(r, s, {}), sd_after(r, s, k, scaled=False), actual(r, s))) for r in q]
        res[s] = {"n": len(q), "games": len({r["gid"] for r in q}), "dCRPS_vs_served": ci(c_d),
                  "dMAE_vs_served": ci(e_cal), "dMAE_vs_own_avg": ci(e_avg),
                  "dBrier_vs_served": ci(b_srv), "dBrier_vs_own_avg_dist": ci(b_avg)}
    return res


def prior_season_test(bt, rows: List[Dict], split: str, out: Path) -> Dict:
    """PRIOR-SEASON FALLBACK, measured before it ships (user decision 2026-10-04, "build + measure it first").

    In production a player has no current-season games on opening night, so the in-season shrink/blend is idle
    until his 3rd game; the module then uses his PREVIOUS regular season (player_logs.csv) with the
    `prior_season` constants. Proxy: every row's season-to-date rate/average is REPLACED by his 2024-25
    regular-season rate/average (a year stale by Jan-Jun -- harsher than opening night's ~4 months); w_p / b_p
    are fit on TRAIN and TEST is scored vs the served sim and vs the in-season (current) own average. Players
    without a 2024-25 season (rookies) keep the sim mean, as the module does.
    """
    data = json.loads((out / "cache" / "statsnba" / "playergamelogs_2024-25_Regular_Season.json").read_text(encoding="utf-8"))
    rs = data["resultSets"][0]
    hdr = rs["headers"]
    tot: Dict[int, Dict[str, float]] = {}
    cols = {"pts": "PTS", "reb": "REB", "ast": "AST", "threes": "FG3M", "stl": "STL", "blk": "BLK", "tov": "TOV"}
    for rr in rs["rowSet"]:
        r = dict(zip(hdr, rr))
        mins = float(r.get("MIN") or 0)
        if mins <= 0:
            continue
        t = tot.setdefault(int(r["PLAYER_ID"]), {"min": 0.0, "g": 0, **{k: 0.0 for k in cols}})
        t["min"] += mins
        t["g"] += 1
        for k, c in cols.items():
            t[k] += float(r.get(c) or 0)
    prior_rows = []
    for r in rows:
        t = tot.get(r["pid"])
        q = dict(r)
        if t and t["g"] >= cal.MIN_GAMES and t["min"] > 0:
            q["per_min"] = {**r["per_min"], **{k: t[k] / t["min"] for k in cols}}
            q["base"] = {**r["base"], **{k: t[k] / t["g"] for k in cols}}
            q["base"]["pra"] = q["base"]["pts"] + q["base"]["reb"] + q["base"]["ast"]
            q["n_prior"] = cal.MIN_GAMES  # the fallback applies
        else:
            q["n_prior"] = 0  # rookie / no prior season: untouched
        q["base_current"] = r["base"]
        prior_rows.append(q)
    cover = sum(1 for q in prior_rows if q["n_prior"]) / max(1, len(prior_rows))
    tr = [r for r in prior_rows if r["phase"] == "regular" and r["date"] < split]
    te = [r for r in prior_rows if (r["phase"] == "regular" and r["date"] >= split) or r["phase"] == "playoff"]
    c_p = fit(tr)
    res = evaluate(bt, te, c_p)

    def ci(v):
        p_, lo, hi = bt._boot_ci(v)
        return {"point": round(p_, 5), "ci95": [round(lo, 5), round(hi, 5)]}
    for s_ in list(cal.SD_STATS) + ["pr", "pa", "ra"]:
        q = [r for r in te if _usable(r, s_)]
        if not q or s_ not in res:
            continue
        cur = (lambda r: sum(r["base_current"][p] for p in COMBOS[s_]) if s_ in COMBOS and s_ != "pra" else r["base_current"][s_])
        res[s_]["dMAE_vs_current_own_avg"] = ci([(r["gid"], abs(mean_after(r, s_, c_p["w"], c_p["b"]) - actual(r, s_))
                                                  - abs(cur(r) - actual(r, s_))) for r in q])
    return {"coverage_with_prior_season": round(cover, 4), "constants_train": c_p, "oos": res,
            "constants_all": fit(prior_rows)}


HIST_MARKETS = {"player_points": "pts", "player_rebounds": "reb", "player_assists": "ast", "player_threes": "threes",
                "player_points_rebounds_assists": "pra", "player_points_rebounds": "pr", "player_points_assists": "pa",
                "player_rebounds_assists": "ra", "player_steals": "stl", "player_blocks": "blk"}


def _book_recs(bt, rows: List[Dict], c: Dict[str, Dict[str, float]], out: Path):
    """Join every two-sided, non-integer backfilled book line to a scored row; one record per (line, book)."""
    from collections import Counter, defaultdict
    from syndicate.features.shared.basketball_props_edges import _norm_name
    w, b, k = c["w"], c.get("b") or {}, c["k"]
    stats = Counter()
    idx: Dict = {}
    for r in rows:
        key = (r["date"], _norm_name(r.get("name") or ""))
        idx[key] = None if key in idx else r          # same name twice on a date -> ambiguous
    recs = []
    for d in sorted({r["date"] for r in rows}):
        src = out / "cache" / "oddsapi_hist" / "props" / d
        if not src.exists():
            stats["dates_without_backfill"] += 1
            continue
        for f in sorted(src.glob("*.json")):
            ev = (json.loads(f.read_text(encoding="utf-8")) or {}).get("data") or {}
            commence = str(ev.get("commence_time") or "")
            quotes: Dict = defaultdict(dict)
            for bk in ev.get("bookmakers") or []:
                for mk in bk.get("markets") or []:
                    stat = HIST_MARKETS.get(mk.get("key"))
                    if not stat:
                        continue
                    upd = str(mk.get("last_update") or bk.get("last_update") or "")
                    if upd and commence and upd >= commence:
                        stats["quote_after_tip_excluded"] += 1
                        continue
                    for oc in mk.get("outcomes") or []:
                        side = str(oc.get("name") or "").upper()
                        if side in ("OVER", "UNDER") and oc.get("point") is not None:
                            quotes[(_norm_name(oc.get("description")), stat, float(oc["point"]), bk.get("key"))][side] = oc.get("price")
            for (nk, stat, line, book), sides in quotes.items():
                stats["lines"] += 1
                if "OVER" not in sides or "UNDER" not in sides:
                    stats["one_sided"] += 1
                    continue
                if abs(line - round(line)) < 1e-9:
                    stats["integer_line"] += 1
                    continue
                p_book = bt._devig(sides["OVER"], sides["UNDER"])
                if p_book is None:
                    stats["unquotable_price"] += 1
                    continue
                key = (d, nk)
                if key not in idx:
                    stats["no_sim_player_that_date"] += 1
                    continue
                r = idx[key]
                if r is None:
                    stats["ambiguous_name"] += 1
                    continue
                if not _usable(r, stat):
                    stats["no_sd"] += 1
                    continue
                y = int(actual(r, stat) > line)
                recs.append({"gid": r["gid"], "phase": r["phase"], "mk": stat, "yb": y, "p_book": p_book,
                             "p_cal": p_over(line, mean_after(r, stat, w, b), sd_after(r, stat, k)),
                             "p_raw": p_over(line, mean_after(r, stat, {}), sd_after(r, stat, k, scaled=False)),
                             "p_own": p_over(line, own_avg(r, stat), sd_after(r, stat, k)),
                             "dec_o": bt._american_to_dec(sides["OVER"]), "dec_u": bt._american_to_dec(sides["UNDER"])})
    return recs, stats


def vs_book(bt, rows: List[Dict], c: Dict[str, Dict[str, float]], out: Path) -> Dict:
    """THE CALIBRATED MODEL vs THE DE-VIGGED BOOK, line by line (OddsAPI historical backfill, one pre-tip snapshot per
    game, every US book). For each two-sided, non-integer line on a scored row: Brier/log-loss of the calibrated
    probability (the given constants), the raw served probability and the player's own-average probability, against
    the proportionally de-vigged book; game-clustered CIs; flat-stake ROI of the calibrated model's +EV side."""
    from collections import defaultdict
    recs, stats = _book_recs(bt, rows, c, out)

    def ci(v):
        p_, lo, hi = bt._boot_ci(v)
        return {"point": round(p_, 5), "ci95": [round(lo, 5), round(hi, 5)]}
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for r in recs:
        groups[r["mk"]].append(r)
        groups["ALL"].append(r)
    res: Dict = {"filters": dict(stats), "rows": len(recs), "games": len({r["gid"] for r in recs}), "by_market": {}}
    for mk, rr in sorted(groups.items()):
        n = len(rr)
        e = {"n": n, "games": len({r["gid"] for r in rr}), "over_rate": round(sum(r["yb"] for r in rr) / n, 4)}
        for key in ("p_book", "p_cal", "p_raw", "p_own"):
            e[key] = {"brier": round(sum((r[key] - r["yb"]) ** 2 for r in rr) / n, 5),
                      "logloss": round(sum(_ll(r[key], r["yb"]) for r in rr) / n, 5)}
        for key in ("p_cal", "p_raw", "p_own"):
            e[f"dBrier_{key}_vs_book"] = ci([(r["gid"], (r[key] - r["yb"]) ** 2 - (r["p_book"] - r["yb"]) ** 2) for r in rr])
        bets = []
        for r in rr:
            if r["dec_o"] is None or r["dec_u"] is None:
                continue
            ev_o, ev_u = r["p_cal"] * r["dec_o"] - 1, (1 - r["p_cal"]) * r["dec_u"] - 1
            if max(ev_o, ev_u) <= 0:
                continue
            win = (r["yb"] == 1) if ev_o >= ev_u else (r["yb"] == 0)
            dec = r["dec_o"] if ev_o >= ev_u else r["dec_u"]
            bets.append((r["gid"], (dec - 1) if win else -1.0, win))
        if bets:
            e["ev_bets_cal"] = {"n": len(bets), "hit": round(sum(x[2] for x in bets) / len(bets), 4),
                                "roi": ci([(g, pnl) for g, pnl, _ in bets])}
        res["by_market"][mk] = e
    return res


def _logit(p: float) -> float:
    p = min(1 - 1e-4, max(1e-4, p))
    return math.log(p / (1 - p))


def blend_p(p_book: float, p_model: float, w: float, space: str = "logit") -> float:
    """p = book + w (model - book), in logit (default) or probability space. w = 0 is the book; w = 1 the model."""
    if space == "prob":
        return p_book + w * (p_model - p_book)
    z = _logit(p_book) + w * (_logit(p_model) - _logit(p_book))
    return 1 / (1 + math.exp(-z))


def book_blend(bt, train_rows: List[Dict], test_rows: List[Dict], c: Dict[str, Dict[str, float]], out: Path) -> Dict:
    """OUT-OF-SAMPLE BOOK-BLEND WEIGHT. The calibrated model loses to the de-vigged book in every market (vs_book), so
    the question is how much weight its departure from the book deserves. w is fit on TRAIN book lines (Brier, grid
    0..1 step 0.05; per market and pooled; logit and probability space) and scored on TEST: Brier vs the book with a
    game-clustered CI, and the flat-stake ROI of the blended +EV side. w = 0 means the model adds nothing to the line."""
    from collections import defaultdict
    tr, tr_stats = _book_recs(bt, train_rows, c, out)
    te, te_stats = _book_recs(bt, test_rows, c, out)
    grid = [round(i * 0.05, 2) for i in range(21)]

    def brier(rr, w, space):
        return sum((blend_p(r["p_book"], r["p_cal"], w, space) - r["yb"]) ** 2 for r in rr) / max(1, len(rr))

    def ci(v):
        p_, lo, hi = bt._boot_ci(v)
        return {"point": round(p_, 5), "ci95": [round(lo, 5), round(hi, 5)]}

    g_tr, g_te = defaultdict(list), defaultdict(list)
    for r in tr:
        g_tr[r["mk"]].append(r)
        g_tr["ALL"].append(r)
    for r in te:
        g_te[r["mk"]].append(r)
        g_te["ALL"].append(r)
    res: Dict = {"train": {"rows": len(tr), "games": len({r["gid"] for r in tr}), "filters": dict(tr_stats)},
                 "test": {"rows": len(te), "games": len({r["gid"] for r in te}), "filters": dict(te_stats)}, "by_market": {}}
    for mk in sorted(g_te):
        rr_tr, rr_te = g_tr.get(mk) or g_tr["ALL"], g_te[mk]
        e: Dict = {"train_n": len(g_tr.get(mk) or []), "test_n": len(rr_te), "test_games": len({r["gid"] for r in rr_te})}
        for space in ("logit", "prob"):
            w = min(grid, key=lambda x: brier(rr_tr, x, space))
            d = ci([(r["gid"], (blend_p(r["p_book"], r["p_cal"], w, space) - r["yb"]) ** 2 - (r["p_book"] - r["yb"]) ** 2)
                    for r in rr_te])
            bets = []
            for r in rr_te:
                if r["dec_o"] is None or r["dec_u"] is None:
                    continue
                pb = blend_p(r["p_book"], r["p_cal"], w, space)
                ev_o, ev_u = pb * r["dec_o"] - 1, (1 - pb) * r["dec_u"] - 1
                if max(ev_o, ev_u) <= 0:
                    continue
                win = (r["yb"] == 1) if ev_o >= ev_u else (r["yb"] == 0)
                bets.append((r["gid"], ((r["dec_o"] if ev_o >= ev_u else r["dec_u"]) - 1) if win else -1.0, win))
            e[space] = {"w_fit_on_train": w, "dBrier_blend_vs_book_test": d,
                        "ev_bets": ({"n": len(bets), "hit": round(sum(x[2] for x in bets) / len(bets), 4),
                                     "roi": ci([(g, pnl) for g, pnl, _ in bets])} if bets else {"n": 0})}
        res["by_market"][mk] = e
    # SERVING WEIGHTS: refit on ALL lines (train + test). The OOS run above is the evidence that the PROCEDURE ties the
    # book; these are the constants it produces with every line. logit space (it was never worse than prob space).
    allr = tr + te
    g_all: Dict = defaultdict(list)
    for r in allr:
        g_all[r["mk"]].append(r)
    w_all = {mk: min(grid, key=lambda x: brier(rr, x, "logit")) for mk, rr in sorted(g_all.items())}
    res["serving"] = {"space": "logit", "w": w_all, "w_pooled": min(grid, key=lambda x: brier(allr, x, "logit")),
                      "lines": len(allr), "games": len({r["gid"] for r in allr})}
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bt-out", type=Path, default=Path(r"C:\tmp\nba_bt\out"))
    ap.add_argument("--split", default="2026-03-01")
    ap.add_argument("--write", type=Path, default=None, help="write the production factor file (fit on ALL rows)")
    ap.add_argument("--prior-season-test", action="store_true", help="measure the prior-season fallback (2024-25 rates)")
    ap.add_argument("--vs-book", action="store_true", help="calibrated model vs the de-vigged book (needs --fetch-odds cache)")
    ap.add_argument("--book-blend", action="store_true", help="fit the book-blend weight on train book lines, score it on test")
    args = ap.parse_args()
    bt = _load_bt()
    rows = collect(bt, args.bt_out)
    if args.book_blend:
        train = [r for r in rows if r["phase"] == "regular" and r["date"] < args.split]
        test = [r for r in rows if (r["phase"] == "regular" and r["date"] >= args.split) or r["phase"] == "playoff"]
        c_train = fit(train)
        rep_bb = {"constants_train": c_train, "blend": book_blend(bt, train, test, c_train, args.bt_out)}
        if args.write:
            sv = rep_bb["blend"]["serving"]
            doc = {"space": sv["space"], "w": sv["w"],
                   "provenance": {"script": "scripts/fit_nba_prop_calibration.py --book-blend",
                                  "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                  "lines": sv["lines"], "games": sv["games"],
                                  "evidence": "OOS (train-fit w, 249,884 test lines / 400 games): ties the de-vigged book",
                                  "meaning": "p_served = sigmoid(logit(p_book) + w * (logit(p_model) - logit(p_book)))"}}
            args.write.write_text(json.dumps(doc, indent=1), encoding="utf-8")
            print(f"wrote {args.write}", flush=True)
        (args.bt_out / "fit_nba_prop_calibration_book_blend.json").write_text(json.dumps(rep_bb, indent=1), encoding="utf-8")
        print(json.dumps({k: v for k, v in rep_bb["blend"].items() if k != "by_market"}), flush=True)
        return 0
    if args.vs_book:
        train = [r for r in rows if r["phase"] == "regular" and r["date"] < args.split]
        test = [r for r in rows if (r["phase"] == "regular" and r["date"] >= args.split) or r["phase"] == "playoff"]
        c_train = fit(train)
        rep_b = {"constants_train": c_train, "test": vs_book(bt, test, c_train, args.bt_out)}
        (args.bt_out / "fit_nba_prop_calibration_vs_book.json").write_text(json.dumps(rep_b, indent=1), encoding="utf-8")
        print(json.dumps({"filters": rep_b["test"]["filters"], "rows": rep_b["test"]["rows"], "games": rep_b["test"]["games"]}), flush=True)
        return 0
    if args.prior_season_test:
        rep_p = prior_season_test(bt, rows, args.split, args.bt_out)
        (args.bt_out / "fit_nba_prop_calibration_prior.json").write_text(json.dumps(rep_p, indent=1), encoding="utf-8")
        print(json.dumps({k: v for k, v in rep_p.items() if k != "oos"}, indent=1), flush=True)
        return 0
    train = [r for r in rows if r["phase"] == "regular" and r["date"] < args.split]
    test = [r for r in rows if (r["phase"] == "regular" and r["date"] >= args.split) or r["phase"] == "playoff"]
    print(f"train {len(train)} rows / {len({r['gid'] for r in train})} games; test {len(test)} rows / "
          f"{len({r['gid'] for r in test})} games", flush=True)
    c_train = fit(train)
    oos = evaluate(bt, test, c_train)
    c_train_nb = fit(train, use_blend=False)          # the previous (shrink + width only) estimator, for the increment
    oos_nb = evaluate(bt, test, c_train_nb)
    c_all = fit(rows)
    report = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "split": args.split,
              "train": {"rows": len(train), "games": len({r["gid"] for r in train})},
              "test": {"rows": len(test), "games": len({r["gid"] for r in test})},
              "constants_train": c_train, "oos_with_train_constants": oos,
              "constants_train_no_blend": c_train_nb, "oos_no_blend": oos_nb, "constants_all": c_all}
    print(json.dumps(report, indent=1), flush=True)
    (args.bt_out / "fit_nba_prop_calibration.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    if args.write:
        doc = {"w": c_all["w"], "blend": c_all["b"], "sd_scale": c_all["k"],
               "provenance": {"script": "scripts/fit_nba_prop_calibration.py", "generated_at": report["generated_at"],
                              "rows": len(rows), "games": len({r["gid"] for r in rows}),
                              "season": "2025-26 smart-sim (2026-01-21..2026-06-13), pre-tip committed output",
                              "oos_split": args.split}}
        args.write.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        print(f"wrote {args.write}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
