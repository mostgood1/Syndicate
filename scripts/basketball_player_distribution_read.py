"""Phase 1 read of lane basketball-player-distribution (pre-registered 6507de9d,
.syndicate/findings_2026-10-26_basketball_player_distribution.md).

Raw engine PLAYER outcome distributions against real player boxes. Input: a scenario-harness sim directory run with
`--record-player-draws` (per draw, per player [pts, reb, ast, threes, on-floor possessions]) plus the ESPN summary
cache for the truth.

Per stat: randomised PIT u = P(X < y) + U.P(X = y) over the draws; tail shares P(u < .1), P(u > .9) (nominal .10 each);
central-80% miss = their sum (nominal .20); width ratio = sd(y - sim mean) / rms(sim sd); bias = mean(y - sim mean).
CIs: game-clustered bootstrap. Splits: starters (top-5 by input minutes) / bench; close (final |margin| <= 10) /
blowout (>= 20). Decomposition: a MINUTES-ORACLE arm rescales each draw's stat by actual min / that draw's sim min.

Usage:
    py -3 scripts/basketball_player_distribution_read.py --sim DIR --cache DIR [--json-out FILE]
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

STATS = ("pts", "reb", "ast", "threes")
TRI = {"GS": "GSW", "UTAH": "UTA", "SA": "SAS", "WSH": "WAS", "NO": "NOP", "NY": "NYK"}


def tri(t: str) -> str:
    return TRI.get(str(t), str(t))


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def pit(draws: Sequence[float], y: float, u: float) -> float:
    """Randomised PIT of y under the empirical distribution of `draws` (u ~ U(0,1) supplied by the caller)."""
    x = np.asarray(draws, dtype=float)
    n = len(x)
    if n == 0:
        return float("nan")
    return float(((x < y).sum() + u * (x == y).sum()) / n)


def cell_summary(rows: List[Dict[str, Any]], rng: np.random.Generator, n_boot: int = 2000) -> Dict[str, Any]:
    """rows: dicts with game, u (PIT), err (y - sim mean), sd (sim sd). Game-clustered bootstrap for the miss."""
    if not rows:
        return {"n": 0}
    u = np.array([r["u"] for r in rows], float)
    err = np.array([r["err"] for r in rows], float)
    sd = np.array([r["sd"] for r in rows], float)
    lo, hi = float((u < 0.1).mean()), float((u > 0.9).mean())
    games = sorted({r["game"] for r in rows})
    gi = {g: i for i, g in enumerate(games)}
    miss_g = np.zeros(len(games)); n_g = np.zeros(len(games))
    for r in rows:
        k = gi[r["game"]]
        miss_g[k] += float(r["u"] < 0.1 or r["u"] > 0.9); n_g[k] += 1
    bs = []
    for _ in range(n_boot):
        ix = rng.integers(0, len(games), len(games))
        bs.append(miss_g[ix].sum() / max(1.0, n_g[ix].sum()))
    rms_sd = float(np.sqrt(np.mean(sd ** 2)))
    return {"n": len(rows), "games": len(games), "bias": float(err.mean()), "p_lo": lo, "p_hi": hi, "miss": lo + hi,
            "miss_ci": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
            "width_ratio": float(err.std(ddof=1) / rms_sd) if rms_sd > 0 and len(err) > 1 else float("nan")}


def flagged(cell: Dict[str, Any]) -> bool:
    """Pre-registered: miss outside [.15, .25] with its CI excluding .20."""
    if not cell.get("n"):
        return False
    lo, hi = cell["miss_ci"]
    return (cell["miss"] < 0.15 or cell["miss"] > 0.25) and not (lo <= 0.20 <= hi)


def actual_players(cache: Path, eid: str) -> Dict[str, Tuple[float, ...]]:
    f = cache / f"summary_{eid}.json.gz"
    if not f.exists():
        return {}
    d = json.load(gzip.open(f))
    out: Dict[str, Tuple[float, ...]] = {}
    for t in (d.get("boxscore") or {}).get("players") or []:
        st = (t.get("statistics") or [{}])[0]
        names = st.get("names") or st.get("labels") or []
        ix = {n: i for i, n in enumerate(names)}
        if not {"MIN", "PTS", "REB", "AST", "3PT"} <= set(ix):
            continue
        for a in st.get("athletes") or []:
            v = a.get("stats") or []
            if not v:
                continue
            try:
                mn = float(v[ix["MIN"]])
            except (TypeError, ValueError):
                continue
            if mn <= 0:
                continue
            tpm = str(v[ix["3PT"]]).split("-")[0]
            out[norm((a.get("athlete") or {}).get("displayName"))] = (mn, float(v[ix["PTS"]]), float(v[ix["REB"]]),
                                                                       float(v[ix["AST"]]), float(tpm))
    return out


def player_games(sim_dir: Path, cache: Path) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """One record per (game, player) that the sim simulated AND who played; counts of the excluded populations."""
    real = {}
    for ln in open(sim_dir / "real_nba.jsonl", encoding="utf-8"):
        x = json.loads(ln)
        if x.get("season_type") == 2:
            real[(x["date"], tri(x["home"]), tri(x["away"]))] = x
    out: List[Dict[str, Any]] = []
    counts = defaultdict(int)
    for f in sorted((sim_dir / "sim_nba").glob("*.jsonl")):
        for ln in open(f, encoding="utf-8"):
            g = json.loads(ln)
            draws = g.get("draws") or []
            if not draws or "pl" not in draws[0] or not g.get("pnames"):
                continue
            key = (g["date"], tri(g["home"]), tri(g["away"]))
            r = real.get(key)
            if r is None:
                counts["game_no_real"] += 1
                continue
            act = actual_players(cache, str(r["event_id"]))
            if not act:
                counts["game_no_box"] += 1
                continue
            counts["games"] += 1
            margin = abs(float(r["home_pts"]) - float(r["away_pts"]))
            inp = {s: {str(n): float(m) for n, m in (g.get("minutes") or {}).get(full, [])}
                   for s, full in (("h", "home"), ("a", "away"))}
            seen = set()
            for s in ("h", "a"):
                names = g["pnames"][s]
                top5 = set(sorted(names, key=lambda n: -inp[s].get(n, 0.0))[:5])
                for j, n in enumerate(names):
                    nn = norm(n)
                    seen.add(nn)
                    if nn not in act:
                        counts["sim_only_dnp"] += 1
                        continue
                    lines = np.array([d["pl"][s][j] for d in draws], float)            # draws x 5
                    game_min = np.array([48.0 + 5.0 * float(d.get("otn", 0)) for d in draws])
                    on_n = np.array([float(d.get("on_n", -1)) for d in draws])
                    sim_min = np.where((lines[:, 4] >= 0) & (on_n > 0), game_min * lines[:, 4] / np.maximum(on_n, 1), np.nan)
                    out.append({"game": key, "player": n, "starter": n in top5, "margin": margin,
                                "input_min": inp[s].get(n, float("nan")), "actual": act[nn],
                                "draws": lines[:, :4], "sim_min": sim_min})
            counts["real_only"] += sum(1 for nn in act if nn not in seen)
    return out, dict(counts)


def read(pg: List[Dict[str, Any]], seed: int = 0) -> Dict[str, Any]:
    rng = np.random.default_rng(seed)
    cells: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in pg:
        y_min = r["actual"][0]
        splits = ["all", "starter" if r["starter"] else "bench"]
        if r["margin"] <= 10:
            splits.append("close")
        elif r["margin"] >= 20:
            splits.append("blowout")
        sm = r["sim_min"]
        if np.isfinite(sm).any():
            x = sm[np.isfinite(sm)]
            row = {"game": r["game"], "u": pit(x, y_min, rng.random()), "err": y_min - float(x.mean()), "sd": float(x.std())}
            for sp in splits:
                cells[f"min|{sp}"].append(row)
        cells["min_input_bias|all"].append({"game": r["game"], "u": 0.5, "err": y_min - r["input_min"], "sd": 0.0})
        for k, st in enumerate(STATS):
            x = r["draws"][:, k]
            y = r["actual"][k + 1]
            row = {"game": r["game"], "u": pit(x, y, rng.random()), "err": y - float(x.mean()), "sd": float(x.std())}
            for sp in splits:
                cells[f"{st}|{sp}"].append(row)
            ok = np.isfinite(sm) & (sm > 0)
            if ok.sum() >= 20:
                xo = x[ok] * (y_min / sm[ok])
                cells[f"{st}_oracle|all"].append({"game": r["game"], "u": pit(xo, y, rng.random()),
                                                  "err": y - float(xo.mean()), "sd": float(xo.std())})
    out = {k: cell_summary(v, rng) for k, v in sorted(cells.items())}
    for k, c in out.items():
        c["flagged"] = flagged(c) if not k.startswith("min_input_bias") else False
    return out


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim", required=True, type=Path)
    ap.add_argument("--cache", required=True, type=Path)
    ap.add_argument("--json-out", type=Path)
    a = ap.parse_args(list(argv) if argv is not None else None)
    pg, counts = player_games(a.sim, a.cache)
    res = read(pg)
    print("population", json.dumps(counts), "player-games", len(pg))
    for k, c in res.items():
        if not c.get("n"):
            continue
        print(f"{k:22s} n={c['n']:6d} bias {c['bias']:+.3f} width {c['width_ratio']:.3f} lo {c['p_lo']:.3f} hi {c['p_hi']:.3f} "
              f"miss {c['miss']:.3f} [{c['miss_ci'][0]:.3f},{c['miss_ci'][1]:.3f}]{'  FLAG' if c['flagged'] else ''}")
    if a.json_out:
        a.json_out.write_text(json.dumps({"population": counts, "player_games": len(pg), "cells": res}, indent=1, default=str),
                              encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
