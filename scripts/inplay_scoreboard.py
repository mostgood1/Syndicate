"""Nightly + cumulative stage-2 scoreboard (lane in-game-trading). Read-only.

Reads <root>/inplay_<date>/fair_rows.jsonl (scripts/inplay_fair_score.py) for
every recorded night, or only --nights, and prints / writes a markdown table per
(fair, sport, market):

  Brier   fair vs Kalshi's mid at the SAME instants and tickers, settled on the
          ticker's own Kalshi result. dBrier = Brier(fair) - Brier(mid);
          negative = the fair is better. 95% CI by bootstrap over GAMES (rows
          inside one game are repeated looks at one outcome, not independent).
  Markout every (row, side) the fair calls positive after the taker fee at
          Kalshi's ask: our leg's Kalshi mid +60/+300 s later minus ask and fee
          (10 contracts, the series' fee multiplier). Same game bootstrap.
          Also the settled P&L of those sides.
  Splits  near (<= 180 s after an ESPN score change) / away, and game phase
          (early / mid / late thirds of regulation, ot). Splits are DIAGNOSTIC:
          GO is decided on the whole cell only.

Pre-registered GO (findings_2026-10-20 §3, fixed 2026-10-20; not re-cut):
  >= 300 settled game-states from >= 20 games, dBrier 95% CI entirely < 0,
  AND markout +300 s 95% CI lower bound > 0. Calendar stop 2026-12-31.
A game-state is one (game, ESPN poll instant).

Watch cell (findings §6-7): book-consensus EPISODES on NHL spreads away from a
score (> 180 s), markout +300 s, from each night's edge_report.json
(scripts/inplay_edge_report.py --json-out), excluding episodes open at game
end. 10-20: +0.9c, CI -0.6..+2.4, n=270.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from syndicate.features.shared.venue_fees import kalshi_taker_fee_dollars  # noqa: E402

FAIRS = ("score_time", "nba_resim", "books")
GO_MIN_STATES, GO_MIN_GAMES = 300, 20
STOP = date(2026, 12, 31)
CONTRACTS = 10
B = 2000


def boot_ci(groups, rng):
    """groups: {game: (sum, n)} -> (mean, lo, hi) by bootstrap over games."""
    keys = [k for k, (_, n) in groups.items() if n]
    if not keys:
        return None, None, None
    tot = sum(groups[k][0] for k in keys) / sum(groups[k][1] for k in keys)
    if len(keys) < 2:
        return tot, None, None
    vals = []
    for _ in range(B):
        s = n = 0.0
        for _ in keys:
            k = keys[rng.randrange(len(keys))]
            s += groups[k][0]
            n += groups[k][1]
        vals.append(s / n)
    vals.sort()
    return tot, vals[int(0.025 * B)], vals[int(0.975 * B) - 1]


def fee(ask, mult):
    return kalshi_taker_fee_dollars(CONTRACTS, ask, fee_multiplier=mult or 1.0) / CONTRACTS


def cell_stats(rows, fair, rng):
    gb = defaultdict(lambda: [0.0, 0])
    states, games = set(), set()
    m = {h: defaultdict(lambda: [0.0, 0]) for h in ("m60", "m300", "settled")}
    nsides = 0
    for r in rows:
        p = r["fairs"].get(fair)
        if p is None:
            continue
        g = (r["night"], r["game"])
        gb[g][0] += (p - r["y"]) ** 2 - (r["mid"] - r["y"]) ** 2
        gb[g][1] += 1
        states.add((g, r["t"]))
        games.add(g)
        for side, ask, ps in (("yes", r["ya"], p), ("no", r["na"], 1 - p)):
            if ask is None or not (0 < ask < 1):
                continue
            fe = fee(ask, r.get("fee_mult"))
            if ps - ask - fe <= 0:
                continue
            nsides += 1
            for h in ("m60", "m300"):
                if r.get(h) is not None:
                    mid = r[h] if side == "yes" else 1 - r[h]
                    m[h][g][0] += mid - ask - fe
                    m[h][g][1] += 1
            won = r["y"] if side == "yes" else 1 - r["y"]
            m["settled"][g][0] += won - ask - fe
            m["settled"][g][1] += 1
    if not games:
        return None
    out = {"rows": sum(v[1] for v in gb.values()), "states": len(states), "games": len(games), "sides": nsides,
           "dbrier": boot_ci({k: tuple(v) for k, v in gb.items()}, rng)}
    for h in m:
        out[h] = boot_ci({k: tuple(v) for k, v in m[h].items()}, rng)
        out[h + "_n"] = sum(v[1] for v in m[h].values())
    return out


def verdict(s):
    if s is None:
        return "no data"
    short = []
    if s["states"] < GO_MIN_STATES:
        short.append(f"states {s['states']}<{GO_MIN_STATES}")
    if s["games"] < GO_MIN_GAMES:
        short.append(f"games {s['games']}<{GO_MIN_GAMES}")
    _, _, bhi = s["dbrier"]
    _, mlo, _ = s["m300"]
    brier_ok = bhi is not None and bhi < 0
    mark_ok = mlo is not None and mlo > 0
    if short:
        return "COLLECTING (" + ", ".join(short) + ")" + (" brier-CI<0 so far" if brier_ok else "") + (" markout-CI>0 so far" if mark_ok else "")
    if brier_ok and mark_ok:
        return "**GO**"
    return "NO-GO (" + ("" if brier_ok else "Brier CI not < 0") + ("" if mark_ok or brier_ok else "; ") + ("" if mark_ok else "markout CI not > 0") + ")"


def ci(t, scale=1.0, fmt="{:+.4f}"):
    m, lo, hi = t
    if m is None:
        return "-"
    s = fmt.format(m * scale)
    if lo is not None:
        s += " [" + fmt.format(lo * scale) + ", " + fmt.format(hi * scale) + "]"
    return s


def watch_cell(dirs, rng):
    groups, nights = defaultdict(lambda: [0.0, 0]), []
    for d in dirs:
        p = d / "edge_report.json"
        if not p.exists():
            continue
        nights.append(d.name.replace("inplay_", ""))
        for e in json.loads(p.read_text(encoding="utf-8")).get("episodes", []):
            if (e.get("family") == "KXNHLSPREAD" and e.get("ended_by") != "open_at_end"
                    and e.get("since_score") is not None and e["since_score"] > 180 and e.get("markout_300") is not None):
                g = (d.name, e["game"])
                groups[g][0] += e["markout_300"]
                groups[g][1] += 1
    n = sum(v[1] for v in groups.values())
    return nights, n, len(groups), boot_ci({k: tuple(v) for k, v in groups.items()}, rng)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="C:/tmp")
    ap.add_argument("--nights", help="comma list of YYYY-MM-DD (default: every inplay_* dir with fair_rows.jsonl)")
    ap.add_argument("--out", help="markdown output path")
    ap.add_argument("--json-out")
    ap.add_argument("--seed", type=int, default=20261020)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    root = Path(a.root)
    if a.nights:
        dirs = [root / f"inplay_{n.strip()}" for n in a.nights.split(",") if n.strip()]
    else:
        dirs = sorted(p.parent for p in root.glob("inplay_*/fair_rows.jsonl"))
    rows = []
    for d in dirs:
        p = d / "fair_rows.jsonl"
        if p.exists():
            with open(p, encoding="utf-8") as fh:
                rows += [json.loads(x) for x in fh if x.strip()]
    nights = sorted({r["night"] for r in rows})
    cells = defaultdict(list)
    for r in rows:
        cells[(r["sport"], r["kind"])].append(r)

    lines = [f"# In-game fair scoreboard (stage 2)",
             "",
             f"Nights: {', '.join(nights) or 'none'} ({len(nights)}). Rows: {len(rows)}. "
             f"Calendar stop {STOP.isoformat()} ({(STOP - date.today()).days} days left).",
             "",
             "dBrier = Brier(fair) - Brier(Kalshi mid), same instants; negative = fair better. "
             "Markouts in cents per contract after the taker fee, sides the fair calls positive. "
             "[95% CI, bootstrap over games]",
             "",
             "| fair | sport | market | games | states | rows | Brier mid | dBrier | sides | markout +60 s | markout +300 s | settled | verdict |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    js = {"nights": nights, "cells": []}
    splits = []
    for (sport, kind), rs in sorted(cells.items()):
        for fair in FAIRS:
            s = cell_stats(rs, fair, rng)
            if s is None:
                continue
            sub = [r for r in rs if fair in r["fairs"]]
            bmid = sum((r["mid"] - r["y"]) ** 2 for r in sub) / len(sub)
            v = verdict(s)
            lines.append(f"| {fair} | {sport} | {kind} | {s['games']} | {s['states']} | {s['rows']} | {bmid:.4f} | {ci(s['dbrier'])} | "
                         f"{s['sides']} | {ci(s['m60'], 100, '{:+.2f}')} | {ci(s['m300'], 100, '{:+.2f}')} | {ci(s['settled'], 100, '{:+.2f}')} | {v} |")
            js["cells"].append({"fair": fair, "sport": sport, "kind": kind, "brier_mid": bmid, "verdict": v, **s})
            for label, pred in (("near", lambda r: r["near"]), ("away", lambda r: not r["near"]),
                                ("early", lambda r: r["phase"] == "early"), ("mid", lambda r: r["phase"] == "mid"),
                                ("late", lambda r: r["phase"] == "late"), ("ot", lambda r: r["phase"] == "ot")):
                ss = cell_stats([r for r in rs if pred(r)], fair, rng)
                if ss:
                    splits.append(f"| {fair} | {sport} | {kind} | {label} | {ss['games']} | {ss['states']} | {ci(ss['dbrier'])} | "
                                  f"{ss['sides']} | {ci(ss['m60'], 100, '{:+.2f}')} | {ci(ss['m300'], 100, '{:+.2f}')} |")
    lines += ["", "## Splits (diagnostic only; GO is decided on the whole cell)", "",
              "| fair | sport | market | split | games | states | dBrier | sides | markout +60 s | markout +300 s |",
              "|---|---|---|---|---|---|---|---|---|---|"] + splits
    wn, wn_eps, wn_games, wci = watch_cell(dirs, rng)
    lines += ["", "## Watch cell: NHL spreads away from a score (book-consensus episodes, markout +300 s)", "",
              f"Nights with edge_report.json: {', '.join(wn) or 'none'}. Episodes {wn_eps} over {wn_games} games: "
              f"{ci(wci, 100, '{:+.2f}')} c. 10-20 baseline: +0.9c [-0.6, +2.4], n=270 (that CI was not clustered by game)."]
    js["watch_cell"] = {"nights": wn, "episodes": wn_eps, "games": wn_games, "markout_300": wci}
    text = "\n".join(lines) + "\n"
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(js, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
