"""WNBA signals v1 on the bought 2026 regular-season closes (lane `signal-engine-wnba`).

Registered in the lane block ("WNBA v1 PRE-REGISTERED") before any close was joined to an outcome.

  lines     `<odds-dir>/<game_id>.json` (`wnba_props_pull.py`): OddsAPI historical event odds at tip - 10 min, US books,
            8 markets. ONE main line per (player, market): most two-sided books (tie -> Shin p nearest 0.5); fair = median
            per-book Shin.
  outcome   the ESPN game log row for (game, player): PTS / REB / AST / FG3M and their combos; no row or MIN 0 -> void;
            push -> void.
  features  `build_nba_signals.build` on the same log -- regular season only, the All-Star game (COOP vs SPO) dropped --
            games strictly before the date.
  rules     the NBA v1 rules with every MINUTE threshold scaled to a 40-minute game (x 40/48): minutes_trend_up / down
            |last 3 - the 10 before| >= 3.3 (NBA 4.0); start_promotion as NBA; b2b rest 1 day and prior-10 MIN >= 23.3
            (NBA 28). blowout_risk is not tested (no game spreads in the bought snapshots).
  unders    W6a: every main line, UNDER (the NBA H6a twin); W6b: prior-10 MIN >= 25 (NBA H6b's 30 x 40/48).
  windows   discover game day < 2026-07-10 <= confirm (the schedule's median regular-season day)
  bar       signals: confirm fired residual 95% CI > 0 AND discover > 0, BH q = 0.10 across the four; W6a / W6b: the H6
            bar. Reported: hit-rate lift vs the eligible baseline; ROI of under-side bets at the best / median book.

    python3 scripts/wnba_signal_tests.py --game-log .../player_game_log_2026.csv --odds-dir .../wnba_props_2026/odds --out w.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from build_nba_signals import build, load_espn  # noqa: E402
from nba_unders_test import roi_stats  # noqa: E402
from syndicate.features.shared.matchup_signals import bh_adjust, norm_player, residual_stats  # noqa: E402
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

SPLIT_DATE = "2026-07-10"
SCALE = 40.0 / 48.0
TREND = round(4.0 * SCALE, 1)        # 3.3
B2B_MIN = round(28.0 * SCALE, 1)     # 23.3
HEAVY_MIN = round(30.0 * SCALE, 1)   # 25.0
MARKET_STATS = {
    "player_points": ("PTS",), "player_rebounds": ("REB",), "player_assists": ("AST",), "player_threes": ("FG3M",),
    "player_points_rebounds_assists": ("PTS", "REB", "AST"), "player_points_rebounds": ("PTS", "REB"),
    "player_points_assists": ("PTS", "AST"), "player_rebounds_assists": ("REB", "AST"),
}
SIGNALS = {  # name -> side
    "wnba.minutes_trend_up": "over", "wnba.minutes_trend_down": "under", "wnba.start_promotion": "over", "wnba.b2b": "under",
}


def decimal(price: float) -> float:
    return 1.0 + price / 100.0 if price > 0 else 1.0 + 100.0 / -price


def wnba_fires(f: Mapping[str, Any]) -> list[str]:
    fired = []
    trend, min10 = f.get("min_trend"), f.get("min_prior10")
    if trend is not None and trend >= TREND:
        fired.append("wnba.minutes_trend_up")
    if trend is not None and trend <= -TREND:
        fired.append("wnba.minutes_trend_down")
    if f.get("started_last") is True and f.get("starts_prior10_before_last") is not None and f["starts_prior10_before_last"] <= 3:
        fired.append("wnba.start_promotion")
    if f.get("rest_days") == 1 and min10 is not None and min10 >= B2B_MIN:
        fired.append("wnba.b2b")
    return fired


def eligible(name: str, f: Mapping[str, Any]) -> bool:
    if name in ("wnba.minutes_trend_up", "wnba.minutes_trend_down"):
        return f.get("min_trend") is not None
    if name == "wnba.start_promotion":
        return f.get("started_last") is not None
    if name == "wnba.b2b":
        return f.get("rest_days") is not None and (f.get("min_prior10") or 0) >= B2B_MIN
    return False


def main_lines(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = (snapshot.get("snap") or {}).get("data") or {}
    by_point: dict[tuple, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for book in data.get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") not in MARKET_STATS:
                continue
            for o in market.get("outcomes") or []:
                side = str(o.get("name") or "").strip().lower()
                try:
                    point, price = float(o.get("point")), float(o.get("price"))
                except (TypeError, ValueError):
                    continue
                if side in ("over", "under") and o.get("description"):
                    by_point[(norm_player(o["description"]), market["key"], point)][book.get("key") or ""][side] = price
    cands: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for (player, market, point), books in by_point.items():
        two = [s for s in books.values() if "over" in s and "under" in s]
        fairs = [f[0] for f in (devig([s["over"], s["under"]], method="shin") for s in two) if f]
        if fairs:
            unders = [decimal(s["under"]) for s in two]
            cands[(player, market)].append({"player_key": player, "market": market, "point": point, "books": len(fairs),
                                            "p_over": statistics.median(fairs), "under_dec_best": max(unders),
                                            "under_dec_median": statistics.median(unders)})
    out = []
    for c in cands.values():
        c.sort(key=lambda x: (-x["books"], abs(x["p_over"] - 0.5)))
        out.append(c[0])
    return out


def wnba_logs(game_log: Path) -> tuple[list[dict[str, Any]], dict, dict[tuple[str, str], dict[str, float]]]:
    """(minutes logs for features, start flags, outcomes keyed (game_id, player_key)) -- regular season, real clubs."""
    import csv

    from syndicate.features.shared.team_aliases import canonical_team

    logs, starts = load_espn(game_log)
    logs = [g for g in logs if canonical_team("wnba", g["team"])]
    outcomes: dict[tuple[str, str], dict[str, float]] = {}
    with game_log.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("season_type") or "").lower() not in ("regular", "regular season") or not canonical_team("wnba", r.get("TEAM_ABBREVIATION")):
                continue
            try:
                outcomes[(str(r["game_id"]), norm_player(r.get("PLAYER_NAME")))] = {k: float(r[k]) for k in ("PTS", "REB", "AST", "FG3M", "MIN")}
            except (TypeError, ValueError, KeyError):
                continue
    return logs, starts, outcomes


def collect(game_log: Path, odds_dir: Path, counts: dict[str, int]) -> list[dict[str, Any]]:
    logs, starts, outcomes = wnba_logs(game_log)
    tables = build(logs, starts, {})
    feats_by_day = {day: {r["player_key"]: r for r in rows} for day, rows in tables.items()}
    records = []
    for path in sorted(odds_dir.glob("*.json")):
        snap = json.loads(path.read_text(encoding="utf-8"))
        game, day = str(snap["game"]), str(snap["date"])
        for line in main_lines(snap):
            counts["main_lines"] += 1
            res = outcomes.get((game, line["player_key"]))
            if not res or res["MIN"] <= 0:
                counts["void_no_outcome_or_dnp"] += 1
                continue
            value = sum(res[s] for s in MARKET_STATS[line["market"]])
            if value == line["point"]:
                counts["void_push"] += 1
                continue
            records.append({**line, "game": game, "day": day, "window": "confirm" if day >= SPLIT_DATE else "discover",
                            "y_over": 1.0 if value > line["point"] else 0.0,
                            "feats": feats_by_day.get(day, {}).get(line["player_key"]) or {}})
            counts["graded"] += 1
    return records


def evaluate(records: list[dict[str, Any]]) -> dict[str, Any]:
    fired: dict[tuple, list] = defaultdict(list)
    base: dict[tuple, list] = defaultdict(list)
    unders: dict[tuple, list] = defaultdict(list)
    for r in records:
        u = {"y": 1.0 - r["y_over"], "p": 1.0 - r["p_over"], "game": r["game"], "under_dec_best": r["under_dec_best"],
             "under_dec_median": r["under_dec_median"]}
        unders[("W6a", r["window"])].append(u)
        unders[(r["market"], r["window"])].append(u)
        if (r["feats"].get("min_prior10") or 0) >= HEAVY_MIN:
            unders[("W6b", r["window"])].append(u)
        fires = set(wnba_fires(r["feats"]))
        for name, side in SIGNALS.items():
            if not eligible(name, r["feats"]):
                continue
            rec = {"y": r["y_over"] if side == "over" else 1.0 - r["y_over"],
                   "p": r["p_over"] if side == "over" else 1.0 - r["p_over"], "game": r["game"]}
            (fired if name in fires else base)[(name, r["window"])].append(rec)
    report: dict[str, Any] = {"signals": {}, "unders": {}}
    confirm_p = {}
    for name, side in SIGNALS.items():
        e: dict[str, Any] = {"side": side}
        for w in ("discover", "confirm"):
            f, b = residual_stats(fired[(name, w)], B=2000), residual_stats(base[(name, w)], B=300)
            e[w] = {"fired": f, "baseline": b,
                    "hit_lift_vs_baseline": None if not f.get("n") or not b.get("n") else round(f["hit_rate"] - b["hit_rate"], 4)}
        d, c = e["discover"]["fired"], e["confirm"]["fired"]
        confirm_p[name] = c.get("p_one_sided")
        e["verdict"] = "SUPPORTED" if c.get("ci95") and c["ci95"][0] > 0 and (d.get("residual") or 0) > 0 else "NOT SUPPORTED"
        report["signals"][name] = e
    for name, keep in bh_adjust(confirm_p, q=0.10).items():
        report["signals"][name]["bh_q10_confirm"] = keep
    for key in ("W6a", "W6b") + tuple(MARKET_STATS):
        e = {}
        for w in ("discover", "confirm"):
            rs = unders[(key, w)]
            e[w] = {"residual": residual_stats(rs, B=2000 if key in ("W6a", "W6b") else 600),
                    "roi_best_price": roi_stats(rs, "under_dec_best", B=600) if rs else {},
                    "roi_median_price": roi_stats(rs, "under_dec_median", B=600) if rs else {}}
        d, c = e["discover"]["residual"], e["confirm"]["residual"]
        e["verdict"] = "SUPPORTED" if c.get("ci95") and c["ci95"][0] > 0 and (d.get("residual") or 0) > 0 else "NOT SUPPORTED"
        report["unders"][key] = e
    pm = {m: report["unders"][m]["confirm"]["residual"].get("p_one_sided") for m in MARKET_STATS}
    for m, keep in bh_adjust(pm, q=0.10).items():
        report["unders"][m]["bh_q10_confirm"] = keep
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game-log", required=True)
    ap.add_argument("--odds-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    counts: dict[str, int] = defaultdict(int)
    records = collect(Path(args.game_log), Path(args.odds_dir), counts)
    report = {"counts": dict(counts), "split_date": SPLIT_DATE,
              "thresholds": {"trend": TREND, "b2b_min": B2B_MIN, "heavy_min": HEAVY_MIN},
              "graded_by_window": {w: sum(1 for r in records if r["window"] == w) for w in ("discover", "confirm")},
              "games_by_window": {w: len({r["game"] for r in records if r["window"] == w}) for w in ("discover", "confirm")},
              **evaluate(records)}
    Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("counts", "graded_by_window", "games_by_window", "thresholds")}), flush=True)
    for name, e in report["signals"].items():
        for w in ("discover", "confirm"):
            f, b = e[w]["fired"], e[w]["baseline"]
            print(f"  {name:24s} {w:8s} fired n={f.get('n')} g={f.get('games')} hit={f.get('hit_rate')} p={f.get('mean_p')} "
                  f"resid={f.get('residual')} ci={f.get('ci95')} | base n={b.get('n')} resid={b.get('residual')} "
                  f"| lift={e[w]['hit_lift_vs_baseline']}", flush=True)
        print(f"  {name:24s} VERDICT {e['verdict']}  BH={e['bh_q10_confirm']}", flush=True)
    for key, e in report["unders"].items():
        for w in ("discover", "confirm"):
            s, rb = e[w]["residual"], e[w]["roi_best_price"]
            print(f"  unders {key:32s} {w:8s} n={s.get('n')} g={s.get('games')} resid={s.get('residual')} ci={s.get('ci95')} "
                  f"ROI best={rb.get('roi_pct')} median={e[w]['roi_median_price'].get('roi_pct')}", flush=True)
        print(f"  unders {key:32s} VERDICT {e['verdict']}" + (f"  BH={e['bh_q10_confirm']}" if "bh_q10_confirm" in e else ""),
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
