"""NHL goalie SAVES signals on the 2025-26 saves closes (lane `signal-engine-nhl`).

Lines: `backfill/nhl_lines_2025_26/odds_saves/<gamePk>.json` -- one OddsAPI historical snapshot ~5 min before the
scheduled start, 449 regular-season games 2025-10-08..2026-02-01, 1-6 US books. One MAIN line per goalie (the point
quoted two-sided by the most books; tie -> median Shin p_over nearest 0.5); fair = median per-book Shin.
Outcome + team: the goalie's row in `player_game_log_20252026.csv` for that game (no row -> void: he did not play).
Features: `matchup_signals_nhl.AsOf` -- regular-season games before the game day.

  --mode distributions   the date split + feature quantiles on DISCOVER lines; reads no saves value
  --mode lift            each signal's fired residual vs the eligible baseline; the pooled saves-UNDER test

    python3 scripts/nhl_saves_lift.py --data-root ~/syndicate-prod/data --mode distributions --out d.json
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
    NHL_REGISTRY,
    THRESHOLDS,
    AsOf,
    load_game_log,
    name_key,
    saves_eligible,
    saves_fires,
)
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

SEASON = "2025"
SPLIT_DATE = "2025-12-09"  # registered (the median game day of the joined lines): on or after -> CONFIRM
SAVES_SIGNALS = ("nhl.saves_opp_volume_high", "nhl.saves_opp_volume_low", "nhl.saves_team_leaky", "nhl.saves_team_b2b")


def decimal(price: float) -> float:
    return 1.0 + price / 100.0 if price > 0 else 1.0 + 100.0 / -price


def saves_main_lines(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = (snapshot.get("snap") or {}).get("data") or {}
    by_point: dict[tuple, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for book in data.get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") != "player_total_saves":
                continue
            for o in market.get("outcomes") or []:
                side = str(o.get("name") or "").strip().lower()
                try:
                    point, price = float(o.get("point")), float(o.get("price"))
                except (TypeError, ValueError):
                    continue
                if side in ("over", "under") and o.get("description"):
                    by_point[(o["description"], point)][book.get("key") or ""][side] = price
    cands: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (goalie, point), books in by_point.items():
        two = [s for s in books.values() if "over" in s and "under" in s]
        fairs = [f[0] for f in (devig([s["over"], s["under"]], method="shin") for s in two) if f]
        if fairs:
            cands[goalie].append({"goalie": goalie, "point": point, "books": len(fairs), "p_over": statistics.median(fairs),
                                  "under_dec_best": max(decimal(s["under"]) for s in two),
                                  "under_dec_median": statistics.median(decimal(s["under"]) for s in two)})
    out = []
    for c in cands.values():
        c.sort(key=lambda x: (-x["books"], abs(x["p_over"] - 0.5)))
        out.append(c[0])
    return out


def collect(root: Path, dirs: tuple[str, ...] = ("odds_saves",)) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Joined lines {game, date, goalie, team, opp, point, p_over, prices, feats, saves(row)} -- no grading here."""
    log = load_game_log([root / "nhl_source" / "source_artifacts" / "data" / "raw" / "player_game_log_20252026.csv"])
    asof = AsOf(log)
    goalies_in: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in log:
        if r["role"] == "goalie" and r["gtype"] == "02":
            goalies_in[r["game"]].append(r)
    counts: dict[str, int] = defaultdict(int)
    out = []
    paths = [(d, p) for d in dirs for p in sorted((root / "backfill" / "nhl_lines_2025_26" / d).glob("*.json"))]
    for source, path in paths:
        game = path.stem
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        for line in saves_main_lines(snapshot):
            counts["main_lines"] += 1
            match = [g for g in goalies_in.get(game, []) if g["key"] == name_key(line["goalie"])]
            if len(match) != 1:
                counts["goalie_did_not_play_or_ambiguous"] += 1
                continue
            g = match[0]
            team = asof.team(g["team"], SEASON, g["date"]) or {}
            opp_team = next((x["team"] for x in goalies_in[game] if x["team"] != g["team"]), None)
            opp = asof.team(opp_team, SEASON, g["date"]) if opp_team else None
            feats = {"opp_sf_pg": (opp or {}).get("sf_pg"), "team_sa_trend": team.get("sa_trend"),
                     "team_rest_days": team.get("rest_days"), "team_sa_pg": team.get("sa_pg")}
            out.append({**line, "game": game, "date": g["date"], "team": g["team"], "opp": opp_team, "feats": feats,
                        "_row": g, "source": source})
            counts["joined"] += 1
    return out, dict(counts)


def _q(values: list[float]) -> dict[str, Any]:
    v = sorted(values)
    if not v:
        return {"n": 0}
    pick = lambda q: round(v[min(len(v) - 1, int(q * len(v)))], 3)  # noqa: E731
    return {"n": len(v), "p10": pick(0.10), "p50": pick(0.50), "p90": pick(0.90)}


def distributions(lines: list[dict[str, Any]]) -> dict[str, Any]:
    days = sorted(l["date"] for l in lines)
    split = days[len(days) // 2] if days else None
    disc = [l for l in lines if split and l["date"] < split]
    return {"split_date_median": split, "discover_lines": len(disc), "confirm_lines": len(lines) - len(disc),
            "opp_sf_pg": _q([l["feats"]["opp_sf_pg"] for l in disc if l["feats"]["opp_sf_pg"] is not None]),
            "team_sa_trend": _q([l["feats"]["team_sa_trend"] for l in disc if l["feats"]["team_sa_trend"] is not None]),
            "team_b2b_share": round(sum(1 for l in disc if l["feats"]["team_rest_days"] == 1) / max(1, len(disc)), 3)}


def grade(lines: list[dict[str, Any]], counts: dict[str, int]) -> list[dict[str, Any]]:
    graded = []
    for l in lines:
        saves = l["_row"]["saves"]
        if saves == l["point"]:
            counts["void_push"] += 1
            continue
        graded.append({**l, "window": "confirm" if l["date"] >= SPLIT_DATE else "discover",
                       "y_over": 1.0 if saves > l["point"] else 0.0})
    return graded


def lift(graded: list[dict[str, Any]]) -> dict[str, Any]:
    fired: dict[tuple[str, str], list] = defaultdict(list)
    base: dict[tuple[str, str], list] = defaultdict(list)
    unders: dict[str, list] = defaultdict(list)
    for r in graded:
        unders[r["window"]].append({"y": 1.0 - r["y_over"], "p": 1.0 - r["p_over"], "game": r["game"],
                                    "under_dec_best": r["under_dec_best"], "under_dec_median": r["under_dec_median"]})
        fires = set(saves_fires(r["feats"]))
        for name in SAVES_SIGNALS:
            if not saves_eligible(name, r["feats"]):
                continue
            side = NHL_REGISTRY[name].side
            rec = {"y": r["y_over"] if side == "over" else 1.0 - r["y_over"],
                   "p": r["p_over"] if side == "over" else 1.0 - r["p_over"], "game": r["game"]}
            (fired if name in fires else base)[(name, r["window"])].append(rec)
    report: dict[str, Any] = {"signals": {}}
    confirm_p = {}
    for name in SAVES_SIGNALS:
        e: dict[str, Any] = {"side": NHL_REGISTRY[name].side, "rule": NHL_REGISTRY[name].rule}
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
    hu: dict[str, Any] = {}
    for w in ("discover", "confirm"):
        hu[w] = {"residual": residual_stats(unders[w], B=2000), "roi_best_price": roi_stats(unders[w], "under_dec_best", B=600),
                 "roi_median_price": roi_stats(unders[w], "under_dec_median", B=600)}
    d, c = hu["discover"]["residual"], hu["confirm"]["residual"]
    hu["verdict"] = "SUPPORTED" if c.get("ci95") and c["ci95"][0] > 0 and (d.get("residual") or 0) > 0 else "NOT SUPPORTED"
    report["saves_under_bias"] = hu
    return report


# ---- v3 (lane block "NHL v3 PRE-REGISTERED"): the two v1 over-side leads on the games bought AFTER v1 -------------
V3_LEADS = ("nhl.saves_team_leaky", "nhl.saves_opp_volume_high")
V3_SEED, V3_B, V3_ALPHA = 20261014, 2000, 0.025


def lift_new(graded: list[dict[str, Any]]) -> dict[str, Any]:
    """PRIMARY: each lead's fired residual on the NEW games (`odds_saves_rest`), Holm over the two at one-sided 0.025.
    SECONDARY: the other signals and the pooled UNDER on the new games; every signal on the full season (v1 + new)."""
    from grade_h7_nba_unders import holm

    def stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in SAVES_SIGNALS:
            side = NHL_REGISTRY[name].side
            fired, base = [], []
            for r in rows:
                if not saves_eligible(name, r["feats"]):
                    continue
                rec = {"y": r["y_over"] if side == "over" else 1.0 - r["y_over"],
                       "p": r["p_over"] if side == "over" else 1.0 - r["p_over"], "game": r["game"]}
                (fired if name in saves_fires(r["feats"]) else base).append(rec)
            f, b = residual_stats(fired, B=V3_B, seed=V3_SEED), residual_stats(base, B=300)
            out[name] = {"side": side, "fired": f, "baseline": b,
                         "hit_lift_vs_baseline": None if not f.get("n") or not b.get("n") else round(f["hit_rate"] - b["hit_rate"], 4)}
        unders = [{"y": 1.0 - r["y_over"], "p": 1.0 - r["p_over"], "game": r["game"], "under_dec_best": r["under_dec_best"],
                   "under_dec_median": r["under_dec_median"]} for r in rows]
        out["nhl.saves_under_bias"] = {"residual": residual_stats(unders, B=V3_B, seed=V3_SEED),
                                       "roi_best_price": roi_stats(unders, "under_dec_best", B=600) if unders else {}}
        return out

    new = [r for r in graded if r["source"] == "odds_saves_rest"]
    report = {"new_games": stats(new), "full_season": stats(graded),
              "graded": {"new": len(new), "full_season": len(graded)},
              "games": {"new": len({r["game"] for r in new}), "full_season": len({r["game"] for r in graded})}}
    pvals = {name: report["new_games"][name]["fired"].get("p_one_sided") for name in V3_LEADS}
    report["holm_primary"] = holm(pvals, alpha=V3_ALPHA)
    report["verdicts"] = {name: "SUPPORTED" if report["holm_primary"][name] else "NOT SUPPORTED" for name in V3_LEADS}
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--mode", choices=("distributions", "lift", "lift-new"), required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    if args.mode == "lift" and (not SPLIT_DATE or not all(THRESHOLDS[k] for k in ("saves_opp_sf_high", "saves_opp_sf_low",
                                                                                   "saves_sa_trend_up"))):
        print("REFUSING: split date / saves thresholds are not registered yet", flush=True)
        return 3
    if args.mode == "lift-new":
        lines, counts = collect(Path(os.path.expanduser(args.data_root)), ("odds_saves", "odds_saves_rest"))
        rep = {"counts": counts, **lift_new(grade(lines, counts))}
        Path(args.out).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
        print(json.dumps({k: rep[k] for k in ("counts", "graded", "games", "holm_primary", "verdicts")}), flush=True)
        for scope in ("new_games", "full_season"):
            for name, e in rep[scope].items():
                f = e.get("fired") or e.get("residual") or {}
                print(f"  {scope:11s} {name:26s} n={f.get('n')} g={f.get('games')} hit={f.get('hit_rate')} "
                      f"p={f.get('mean_p')} resid={f.get('residual')} ci={f.get('ci95')} p1={f.get('p_one_sided')} "
                      f"| base resid={(e.get('baseline') or {}).get('residual')} "
                      f"ROI={(e.get('roi_best_price') or {}).get('roi_pct')}", flush=True)
        return 0
    lines, counts = collect(Path(os.path.expanduser(args.data_root)))
    if args.mode == "distributions":
        report: dict[str, Any] = {"counts": counts, "distributions": distributions(lines)}
    else:
        graded = grade(lines, counts)
        report = {"counts": counts, "split_date": SPLIT_DATE,
                  "graded_by_window": {w: sum(1 for g in graded if g["window"] == w) for w in ("discover", "confirm")},
                  **lift(graded), "thresholds": {k: v for k, v in THRESHOLDS.items() if k.startswith("saves")}}
    Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("signals", "saves_under_bias")}, default=str), flush=True)
    for name, e in (report.get("signals") or {}).items():
        for w in ("discover", "confirm"):
            f, b = e[w]["fired"], e[w]["baseline"]
            print(f"  {name:26s} {w:8s} fired n={f.get('n')} g={f.get('games')} hit={f.get('hit_rate')} p={f.get('mean_p')} "
                  f"resid={f.get('residual')} ci={f.get('ci95')} | base n={b.get('n')} resid={b.get('residual')} "
                  f"| hit_lift={e[w]['hit_lift_vs_baseline']}", flush=True)
        print(f"  {name:26s} VERDICT {e['verdict']}  BH={e['bh_q10_confirm']}", flush=True)
    if "saves_under_bias" in report:
        hu = report["saves_under_bias"]
        for w in ("discover", "confirm"):
            s, rb = hu[w]["residual"], hu[w]["roi_best_price"]
            print(f"  saves_under_bias {w:8s} n={s.get('n')} g={s.get('games')} resid={s.get('residual')} ci={s.get('ci95')} "
                  f"ROI best={rb.get('roi_pct')} {rb.get('ci95')} median={hu[w]['roi_median_price'].get('roi_pct')}", flush=True)
        print(f"  saves_under_bias VERDICT {hu['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
