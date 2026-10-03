"""What does the WNBA prop book line know that the model does not? (lane `wnba-book-information`)

After fixes #2 (availability) and #3 (rate shrink) the model's prop mean ties the player's own average, yet the book
is still better at its own line and the model has no discrimination there for points. This measures WHERE the book's
remaining information lives. Rows: every player-game the model priced, with a two-sided book line, on the fix #2+#3
stack (as-of re-runs), regular season + playoffs separately.

    g  = book line - model mean                       (the book's disagreement, stat units)
    y - m = MIN_PART + RATE_PART                      (exact split)
        MIN_PART  = (m / M) * (A - M)                 model rate x the minutes surprise (A actual, M sim minutes)
        RATE_PART = y - (m / M) * A                   what the player did per minute beyond the model's rate

  1. WHO IS RIGHT when they disagree: rows bucketed by g; mean(y - m), mean(y - line), over-rate; and the OLS slope of
     (y - m) on g -- 1 = the book's disagreement is all information, 0 = it is all noise.
  2. WHICH CHANNEL: slopes of MIN_PART and RATE_PART on g (they sum to the total slope). The minutes share of the
     book's information = slope_min / slope_total.
  3. LATE OUTS: per team-game, the as-of season-average minutes of teammates who PLAYED the team's previous game and
     did not play today -- news no as-of history contains (it is in the pregame injury report). For players who did
     play: mean g and mean (y - m) by late-out minutes band.
  Every slope / mean difference carries a game-clustered bootstrap 95% CI.

Usage (WSL): python scripts/analyze_wnba_book_information.py --archive ~/wnba_bt/stack --espn-dir ... --box-dir ...
             --odds-dir ... --out ~/wnba_bt/book_info
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bt_wnba", REPO / "scripts" / "backtest_wnba_lines_props.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)  # type: ignore[union-attr]
_spec2 = importlib.util.spec_from_file_location("fit_avail", REPO / "scripts" / "fit_wnba_sim_availability.py")
AV = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(AV)  # type: ignore[union-attr]

MARKETS = {"player_points": ("pts",), "player_rebounds": ("reb",), "player_assists": ("ast",),
           "player_points_rebounds_assists": ("pts", "reb", "ast")}
COL = {"pts": "PTS", "reb": "REB", "ast": "AST"}


def ols_slope(x: List[float], y: List[float]) -> Optional[float]:
    if len(x) < 10:
        return None
    mx, my = statistics.fmean(x), statistics.fmean(y)
    vx = sum((a - mx) ** 2 for a in x)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / vx if vx else None


def boot_slope(rows: List[Tuple[str, float, float]], n_boot: int = 1000, seed: int = 7) -> Dict:
    """Game-clustered bootstrap CI for the OLS slope of y on x. rows = (gid, x, y)."""
    by: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    for g, x, y in rows:
        by[g].append((x, y))
    keys = list(by)
    pt = ols_slope([r[1] for r in rows], [r[2] for r in rows])
    if pt is None:
        return {"point": None, "ci95": [None, None]}
    rng = random.Random(seed)
    st = []
    for _ in range(n_boot):
        xs, ys = [], []
        for _j in range(len(keys)):
            for x, y in by[keys[rng.randrange(len(keys))]]:
                xs.append(x)
                ys.append(y)
        s = ols_slope(xs, ys)
        if s is not None:
            st.append(s)
    st.sort()
    return {"point": round(pt, 4), "ci95": [round(st[int(0.025 * len(st))], 4), round(st[int(0.975 * len(st)) - 1], 4)]}


def late_outs(games: Dict, box_all: Dict) -> Dict[Tuple[str, str], float]:
    """{(gid, team): season-avg minutes of players who played the team's previous game but not this one}."""
    by_team: Dict[str, List[Dict]] = defaultdict(list)
    for g in sorted(games.values(), key=lambda x: x["tip"]):
        if g["id"] in box_all:
            for t in (g["home"], g["away"]):
                by_team[t].append(g)
    out: Dict[Tuple[str, str], float] = {}
    for team, gl in by_team.items():
        mins: Dict[str, List[float]] = defaultdict(list)
        for i, g in enumerate(gl):
            today = {k for k, m in box_all[g["id"]].get(team, {}).items() if m > 0}
            if i > 0:
                prev = {k for k, m in box_all[gl[i - 1]["id"]].get(team, {}).items() if m > 0}
                out[(g["id"], team)] = sum(statistics.fmean(mins[k]) for k in prev - today if mins[k])
            for k, m in box_all[g["id"]].get(team, {}).items():
                if m > 0:
                    mins[k].append(m)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--espn-dir", required=True)
    ap.add_argument("--box-dir", required=True)
    ap.add_argument("--odds-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-boot", type=int, default=1000)
    args = ap.parse_args(argv)
    games = B.load_games(Path(args.espn_dir))
    box, _ = B.load_box(Path(args.box_dir), games)
    box_all = AV.load_box_all(Path(args.box_dir), games)
    book, _ = B.load_book(Path(args.odds_dir), games)
    lo = late_outs(games, box_all)
    idx = B._pair_index(games)
    rows: List[Dict] = []
    for p in sorted(Path(args.archive).glob("*/smart_sim_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        gid = B.match_game(idx, str(d.get("date")), str(d.get("home")).upper(), str(d.get("away")).upper())
        if not gid:
            continue
        g = games[gid]
        for side, team in (("home", g["home"]), ("away", g["away"])):
            for pl in (d.get("players") or {}).get(side) or []:
                pk = B.norm_name(pl.get("player_name"))
                a = box.get(gid, {}).get(pk)
                M = float(pl.get("min_mean") or 0)
                if not a or M <= 0:
                    continue
                for mk, parts in MARKETS.items():
                    b = (book.get(gid) or {}).get("props", {}).get((pk, mk))
                    if not b:
                        continue
                    try:
                        m = sum(float(pl[f"{s}_mean"]) for s in parts)
                    except (KeyError, TypeError, ValueError):
                        continue
                    y = sum(a[COL[s]] for s in parts)
                    A = a["MIN"]
                    min_part = (m / M) * (A - M)
                    rows.append({"gid": gid, "phase": g["phase"], "mk": mk, "g": b["line"] - m, "e": y - m,
                                 "e_line": y - b["line"], "over": int(y > b["line"]) if y != b["line"] else None,
                                 "min_part": min_part, "rate_part": y - (m / M) * A, "A": A, "M": M,
                                 "late_out_min": lo.get((gid, team), 0.0)})
    report: Dict = {"rows": len(rows), "markets": {}}
    for phase in ("regular", "playoff"):
        for mk in MARKETS:
            R = [r for r in rows if r["phase"] == phase and r["mk"] == mk]
            if len(R) < 30:
                continue
            ent: Dict = {"n": len(R), "games": len({r["gid"] for r in R})}
            ent["slope_total"] = boot_slope([(r["gid"], r["g"], r["e"]) for r in R], args.n_boot)
            ent["slope_minutes_part"] = boot_slope([(r["gid"], r["g"], r["min_part"]) for r in R], args.n_boot)
            ent["slope_rate_part"] = boot_slope([(r["gid"], r["g"], r["rate_part"]) for r in R], args.n_boot)
            ent["slope_minutes_surprise_on_g"] = boot_slope([(r["gid"], r["g"], r["A"] - r["M"]) for r in R], args.n_boot)
            qs = sorted(r["g"] for r in R)
            cuts = [qs[int(len(qs) * f)] for f in (0.2, 0.4, 0.6, 0.8)]
            buckets = []
            for lo_c, hi_c, name in ((-1e9, cuts[0], "book far below model"), (cuts[0], cuts[1], "below"),
                                     (cuts[1], cuts[2], "agree"), (cuts[2], cuts[3], "above"),
                                     (cuts[3], 1e9, "book far above model")):
                bb = [r for r in R if lo_c <= r["g"] < hi_c]
                if not bb:
                    continue
                ov = [r["over"] for r in bb if r["over"] is not None]
                buckets.append({"bucket": name, "n": len(bb), "mean_g": round(statistics.fmean(r["g"] for r in bb), 3),
                                "mean_actual_minus_model": round(statistics.fmean(r["e"] for r in bb), 3),
                                "mean_actual_minus_line": round(statistics.fmean(r["e_line"] for r in bb), 3),
                                "mean_minutes_surprise": round(statistics.fmean(r["A"] - r["M"] for r in bb), 2),
                                "over_rate": round(statistics.fmean(ov), 3) if ov else None})
            ent["buckets"] = buckets
            late = []
            for lo_c, hi_c, name in ((0, 0.001, "no late outs"), (0.001, 15, "late outs < 15 min"), (15, 999, "late outs >= 15 min")):
                bb = [r for r in R if lo_c <= r["late_out_min"] < hi_c]
                if bb:
                    late.append({"band": name, "n": len(bb), "games": len({r["gid"] for r in bb}),
                                 "mean_g": round(statistics.fmean(r["g"] for r in bb), 3),
                                 "mean_actual_minus_model": round(statistics.fmean(r["e"] for r in bb), 3),
                                 "mean_actual_minus_line": round(statistics.fmean(r["e_line"] for r in bb), 3),
                                 "mean_minutes_surprise": round(statistics.fmean(r["A"] - r["M"] for r in bb), 2)})
            ent["late_outs"] = late
            big = [r for r in R if r["late_out_min"] >= 15]
            none = [r for r in R if r["late_out_min"] < 0.001]
            if len(big) >= 30:
                ent["late_out_effect"] = {
                    "model_miss_d": B.boot_ci([(r["gid"], r["e"]) for r in big]),
                    "model_miss_baseline": B.boot_ci([(r["gid"], r["e"]) for r in none]),
                    "book_move_d": B.boot_ci([(r["gid"], r["g"]) for r in big]),
                    "book_move_baseline": B.boot_ci([(r["gid"], r["g"]) for r in none]),
                    "book_miss_d": B.boot_ci([(r["gid"], r["e_line"]) for r in big])}
            report["markets"][f"{phase}:{mk}"] = ent
            st, sm, sr = ent["slope_total"], ent["slope_minutes_part"], ent["slope_rate_part"]
            print(f"{phase:8s} {mk:32s} n={len(R)} slope total {st} | minutes {sm} | rate {sr}", flush=True)
            for b_ in buckets:
                print(f"     {b_}", flush=True)
            for l_ in late:
                print(f"     LATE {l_}", flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "book_information.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
