"""NHL skater signals K1-K5 on the BOUGHT 2025-26 skater prop closes -- the discovery season (lane `signal-engine-nhl`).

Registered in the lane block ("NHL v2 PRE-REGISTERED") before any of these closes was joined to an outcome. Same
signals and thresholds as the forward family (`matchup_signals_nhl.THRESHOLDS`, set from 2025-26 game-log FEATURES).

  lines     `<props-dir>/<gamePk>.json`: OddsAPI historical event odds at start - 10 min (`nhl_skater_props_pull.py`),
            US books; ONE main line per (player, market) = most two-sided books (tie -> Shin p nearest 0.5);
            fair = median per-book Shin (no Pinnacle in this history -- the forward fair adds it)
  outcome   the player's row in `player_game_log_20252026.csv` for that game (first initial + surname within the game);
            none -> void; push -> void
  features  `AsOf` over the 2025-26 regular season, games before the day
  windows   discover game day < 2026-01-04 <= confirm (the schedule's median game day)
  bar       K1-K4: confirm fired residual 95% CI > 0 AND discover > 0, BH q = 0.10 over K1-K4; K5 (every line, UNDER):
            the H6 bar. Reported: hit-rate lift vs the eligible baseline, ROI of under-side bets at the best / median book.

    python3 scripts/nhl_skater_history_lift.py --data-root ~/syndicate-prod/data \\
        --props-dir ~/syndicate-prod/data/backfill/nhl_lines_2025_26/odds_skater_props --out k_hist.json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nba_unders_test import roi_stats  # noqa: E402
from syndicate.features.shared.matchup_signals import bh_adjust, residual_stats  # noqa: E402
from syndicate.features.shared.matchup_signals_nhl import (  # noqa: E402
    NHL_MARKET_STATS,
    NHL_REGISTRY,
    AsOf,
    load_game_log,
    name_key,
    skater_eligible,
    skater_fires,
)
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

SEASON = "2025"
SPLIT_DATE = "2026-01-04"
SIGNALS = {"K1": "nhl.toi_up", "K2": "nhl.toi_down", "K3": "nhl.opp_allows_shots", "K4": "nhl.opp_suppresses_shots"}
SIGNAL_STATS = {"K1": ("shots", "points"), "K2": ("shots", "points"), "K3": ("shots",), "K4": ("shots",)}
SKATER_STATS = ("shots", "points", "assists", "goals")


def decimal(price: float) -> float:
    return 1.0 + price / 100.0 if price > 0 else 1.0 + 100.0 / -price


def snapshot_main_lines(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = (snapshot.get("snap") or {}).get("data") or {}
    by_point: dict[tuple, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for book in data.get("bookmakers") or []:
        for market in book.get("markets") or []:
            stat = NHL_MARKET_STATS.get(market.get("key") or "")
            if stat not in SKATER_STATS:
                continue
            for o in market.get("outcomes") or []:
                side = str(o.get("name") or "").strip().lower()
                try:
                    point, price = float(o.get("point")), float(o.get("price"))
                except (TypeError, ValueError):
                    continue
                if side in ("over", "under") and o.get("description"):
                    by_point[(o["description"], stat, point)][book.get("key") or ""][side] = price
    cands: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for (player, stat, point), books in by_point.items():
        two = [s for s in books.values() if "over" in s and "under" in s]
        fairs = [f[0] for f in (devig([s["over"], s["under"]], method="shin") for s in two) if f]
        if fairs:
            unders = [decimal(s["under"]) for s in two]
            cands[(player, stat)].append({"player": player, "stat": stat, "point": point, "books": len(fairs),
                                          "p_over": statistics.median(fairs), "under_dec_best": max(unders),
                                          "under_dec_median": statistics.median(unders)})
    out = []
    for c in cands.values():
        c.sort(key=lambda x: (-x["books"], abs(x["p_over"] - 0.5)))
        out.append(c[0])
    return out


def collect(root: Path, props_dir: Path, counts: dict[str, int]) -> list[dict[str, Any]]:
    log = load_game_log([root / "nhl_source" / "source_artifacts" / "data" / "raw" / "player_game_log_20252026.csv"])
    asof = AsOf(log)
    by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    teams_in: dict[str, set[str]] = defaultdict(set)
    for r in asof.rows:
        by_key[(r["game"], r["key"])].append(r)
        teams_in[r["game"]].add(r["team"])
    records = []
    for path in sorted(props_dir.glob("*.json")):
        game = path.stem
        if game[4:6] != "02" or game not in teams_in:
            counts["game_not_in_log"] += 1
            continue
        for line in snapshot_main_lines(json.loads(path.read_text(encoding="utf-8"))):
            counts["main_lines"] += 1
            match = [r for r in by_key.get((game, name_key(line["player"])), []) if r["role"] != "goalie"]
            if len(match) != 1:
                counts["void_no_outcome_or_ambiguous"] += 1
                continue
            row = match[0]
            value = float(row[line["stat"]])
            if value == line["point"]:
                counts["void_push"] += 1
                continue
            day = row["date"]
            sk = asof.skater(row["player_id"], SEASON, day) or {}
            opp = next((t for t in teams_in[game] if t != row["team"]), None)
            opp_f = asof.team(opp, SEASON, day) if opp else None
            records.append({"window": "confirm" if day >= SPLIT_DATE else "discover", "game": game, "stat": line["stat"],
                            "y_over": 1.0 if value > line["point"] else 0.0, "p_over": line["p_over"],
                            "under_dec_best": line["under_dec_best"], "under_dec_median": line["under_dec_median"],
                            "feats": {"toi_trend": sk.get("toi_trend"), "opp_sa_pg": (opp_f or {}).get("sa_pg")}})
            counts["graded"] += 1
    return records


def evaluate(records: list[dict[str, Any]]) -> dict[str, Any]:
    fired: dict[tuple, list] = defaultdict(list)
    base: dict[tuple, list] = defaultdict(list)
    unders: dict[tuple, list] = defaultdict(list)
    for r in records:
        under = {"y": 1.0 - r["y_over"], "p": 1.0 - r["p_over"], "game": r["game"],
                 "under_dec_best": r["under_dec_best"], "under_dec_median": r["under_dec_median"]}
        unders[("all", r["window"])].append(under)
        unders[(r["stat"], r["window"])].append(under)
        fires = set(skater_fires(r["feats"]))
        for k, name in SIGNALS.items():
            if r["stat"] not in SIGNAL_STATS[k] or not skater_eligible(name, r["feats"]):
                continue
            side = NHL_REGISTRY[name].side
            rec = {"y": r["y_over"] if side == "over" else 1.0 - r["y_over"],
                   "p": r["p_over"] if side == "over" else 1.0 - r["p_over"], "game": r["game"],
                   "under_dec_best": r["under_dec_best"], "under_dec_median": r["under_dec_median"]}
            (fired if name in fires else base)[(k, r["window"])].append(rec)
    report: dict[str, Any] = {"signals": {}, "K5_unders": {}}
    confirm_p = {}
    for k, name in SIGNALS.items():
        side = NHL_REGISTRY[name].side
        e: dict[str, Any] = {"signal": name, "side": side, "markets": SIGNAL_STATS[k]}
        for w in ("discover", "confirm"):
            f, b = residual_stats(fired[(k, w)], B=2000), residual_stats(base[(k, w)], B=300)
            e[w] = {"fired": f, "baseline": b,
                    "hit_lift_vs_baseline": None if not f.get("n") or not b.get("n") else round(f["hit_rate"] - b["hit_rate"], 4)}
            if side == "under" and fired[(k, w)]:
                e[w]["roi_best_price"] = roi_stats(fired[(k, w)], "under_dec_best", B=600)
        d, c = e["discover"]["fired"], e["confirm"]["fired"]
        confirm_p[k] = c.get("p_one_sided")
        e["verdict"] = "SUPPORTED" if c.get("ci95") and c["ci95"][0] > 0 and (d.get("residual") or 0) > 0 else "NOT SUPPORTED"
        report["signals"][k] = e
    for k, keep in bh_adjust(confirm_p, q=0.10).items():
        report["signals"][k]["bh_q10_confirm"] = keep
    for stat in ("all",) + SKATER_STATS:
        e = {}
        for w in ("discover", "confirm"):
            rs = unders[(stat, w)]
            e[w] = {"residual": residual_stats(rs, B=2000 if stat == "all" else 600),
                    "roi_best_price": roi_stats(rs, "under_dec_best", B=600) if rs else {},
                    "roi_median_price": roi_stats(rs, "under_dec_median", B=600) if rs else {}}
        d, c = e["discover"]["residual"], e["confirm"]["residual"]
        e["verdict"] = "SUPPORTED" if c.get("ci95") and c["ci95"][0] > 0 and (d.get("residual") or 0) > 0 else "NOT SUPPORTED"
        report["K5_unders"][stat] = e
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--props-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    counts: dict[str, int] = defaultdict(int)
    records = collect(Path(os.path.expanduser(args.data_root)), Path(os.path.expanduser(args.props_dir)), counts)
    report = {"counts": dict(counts), "split_date": SPLIT_DATE,
              "graded_by_window": {w: sum(1 for r in records if r["window"] == w) for w in ("discover", "confirm")},
              "games_by_window": {w: len({r["game"] for r in records if r["window"] == w}) for w in ("discover", "confirm")},
              **evaluate(records)}
    Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("counts", "graded_by_window", "games_by_window")}), flush=True)
    for k, e in report["signals"].items():
        for w in ("discover", "confirm"):
            f, b = e[w]["fired"], e[w]["baseline"]
            print(f"  {k} {e['signal']:24s} {w:8s} fired n={f.get('n')} g={f.get('games')} hit={f.get('hit_rate')} "
                  f"p={f.get('mean_p')} resid={f.get('residual')} ci={f.get('ci95')} | base n={b.get('n')} "
                  f"resid={b.get('residual')} | lift={e[w]['hit_lift_vs_baseline']} "
                  f"ROI={(e[w].get('roi_best_price') or {}).get('roi_pct')}", flush=True)
        print(f"  {k} VERDICT {e['verdict']}  BH={e['bh_q10_confirm']}", flush=True)
    for stat, e in report["K5_unders"].items():
        for w in ("discover", "confirm"):
            s, rb = e[w]["residual"], e[w]["roi_best_price"]
            print(f"  K5 unders {stat:8s} {w:8s} n={s.get('n')} g={s.get('games')} resid={s.get('residual')} "
                  f"ci={s.get('ci95')} ROI best={rb.get('roi_pct')} median={e[w]['roi_median_price'].get('roi_pct')}",
                  flush=True)
        print(f"  K5 unders {stat:8s} VERDICT {e['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
