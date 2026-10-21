"""What a no-history stand-in does to his TEAMMATES' simulation, and whether it was right (lane nba-no-history-admit).

Compares two scratch copies of the NBA processed tree simulated on identical inputs -- ``--off`` (stand-ins off) and
``--on`` (``SYNDICATE_NBA_NO_HISTORY_STANDINS=on``) -- and optionally a third ``--noise`` arm (off, another seed) that
measures how much the same numbers move from Monte Carlo alone.

For every side whose ``on`` sim carries ``context.no_history_standins``:
  * the stand-in's simulated minutes and points (from the context, never from ``players[]`` -- he is not there);
  * teammates (players in both arms' ``players[]``): sum and per-player change in ``min_mean`` / ``pts_mean``;
  * PRICED LINES MOVED: each teammate's posted main line (median over books of the latest pre-tip Over line for
    pts/reb/ast/threes, ``oddsapi_player_props_<D>.csv``) and the sim's P(over) from ``prop_distributions`` in each arm;
    a line "moved" when |P_on - P_off| >= ``--pp`` (default 3 pp). The same count off vs noise is the floor.

``--truth`` adds the pre-registered go/no-go reading (findings_2026-10-20_nba_no_history_admit.md): actual box minutes
and points from ``rotation_stints/player_checks_<D>.csv`` (regular season), paired absolute errors on/off for teammates
who played, 95% CI by cluster bootstrap over sides, and the stand-ins' minutes-prior error.

    python scripts/nba_standin_cost.py --date 2026-10-21 --off A/nba_source/data/processed \\
        --on B/nba_source/data/processed --noise A2/nba_source/data/processed [--truth <processed dir>] [--json out.json]

Read-only.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Mapping, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared.nba_current_rosters import name_key  # noqa: E402

MAIN_STATS = {"player_points": "pts", "player_rebounds": "reb", "player_assists": "ast", "player_threes": "threes"}


def load_sims(processed: Path, date_str: str) -> Dict[str, Dict[str, Any]]:
    out = {}
    for p in sorted(Path(processed).glob(f"smart_sim_{date_str}_*.json")):
        if p.stem.count("_") == 4:
            out[p.stem[len("smart_sim_") + 11:]] = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    return out


def side_rows(sim: Mapping[str, Any], side: str) -> Dict[str, Dict[str, Any]]:
    return {name_key(r.get("player_name")): r for r in ((sim.get("players") or {}).get(side) or []) if isinstance(r, dict)}


def main_lines(processed: Path, date_str: str) -> Dict[Tuple[str, str], float]:
    """{(name_key, stat): median over books of each book's latest pre-tip Over line}."""
    latest: Dict[Tuple[str, str, str], Tuple[str, float]] = {}
    path = Path(processed) / f"oddsapi_player_props_{date_str}.csv"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            stat = MAIN_STATS.get(str(r.get("market") or ""))
            if stat is None or str(r.get("outcome_name") or "").lower() != "over":
                continue
            snap, commence = str(r.get("snapshot_ts") or ""), str(r.get("commence_time") or "")
            if commence and snap[:19] >= commence[:19]:
                continue
            try:
                point = float(r.get("point"))
            except (TypeError, ValueError):
                continue
            slot = (name_key(r.get("player_name")), stat, str(r.get("bookmaker") or ""))
            if slot not in latest or snap >= latest[slot][0]:
                latest[slot] = (snap, point)
    pooled: Dict[Tuple[str, str], List[float]] = {}
    for (k, stat, _b), (_s, point) in latest.items():
        pooled.setdefault((k, stat), []).append(point)
    return {k: float(median(v)) for k, v in pooled.items()}


def p_over(row: Mapping[str, Any], stat: str, line: float) -> Optional[float]:
    dist = (((row.get("prop_distributions") or {}).get(stat) or {}).get("distribution")) or {}
    total = sum(int(c) for c in dist.values())
    if total <= 0:
        return None
    return sum(int(c) for v, c in dist.items() if float(v) > line) / total


def truth_box(processed: Path, date_str: str) -> Dict[Tuple[str, str], Dict[str, float]]:
    """{(team, name_key): {"min": box minutes}} for the date's regular-season games (ESPN box, P2 producer)."""
    out: Dict[Tuple[str, str], Dict[str, float]] = {}
    path = Path(processed) / "rotation_stints" / f"player_checks_{date_str}.csv"
    if not path.is_file():
        return out
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("season_type") or "").lower() != "regular":
                continue
            try:
                m = float(r.get("box_minutes") or 0.0)
            except ValueError:
                continue
            out[(str(r.get("team") or "").upper(), name_key(r.get("player_name")))] = {"min": m}
    return out


def truth_points(processed: Path, date_str: str) -> Dict[str, float]:
    """{name_key: points} from player_logs.csv rows of the date (present once the history refresh has run)."""
    out: Dict[str, float] = {}
    path = Path(processed) / "player_logs.csv"
    if not path.is_file():
        return out
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("GAME_DATE") or "")[:10] == date_str:
                try:
                    out[name_key(r.get("PLAYER_NAME"))] = float(r.get("PTS") or 0.0)
                except ValueError:
                    pass
    return out


def cluster_ci(pairs_by_side: Dict[str, List[float]], *, n_boot: int = 10000, seed: int = 7) -> Tuple[float, float, float, int]:
    sides = [v for v in pairs_by_side.values() if v]
    flat = [x for v in sides for x in v]
    if not flat:
        return float("nan"), float("nan"), float("nan"), 0
    mean = sum(flat) / len(flat)
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        pick = [sides[rng.randrange(len(sides))] for _ in sides]
        vals = [x for v in pick for x in v]
        boots.append(sum(vals) / len(vals))
    boots.sort()
    return mean, boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1], len(flat)


def recomputed_priors(on: Path, date_str: str) -> Dict[str, float]:
    """{name_key: minutes prior} rebuilt from the ON arm's own frozen inputs -- for sims written before the context
    recorded ``minutes_prior``. Same function, same files, so the same numbers the sim was given."""
    try:
        import pandas as pd

        from syndicate.features.shared import nba_no_history_standins as nhs
        from syndicate.features.shared.basketball_props_smart_sim import _to_tricode_local

        props = pd.read_csv(Path(on) / f"props_predictions_{date_str}.csv")
        to_tri = lambda v: str(_to_tricode_local(v) or str(v or "").strip().upper()).strip().upper()  # noqa: E731
        standins, _ = nhs.build_standins(processed_root=Path(on), date_str=date_str, props_df=props, name_key=name_key,
                                         to_tri=to_tri)
        return {name_key(s.player_name): s.minutes for s in standins}
    except Exception as exc:  # noqa: BLE001
        print(f"minutes priors not recomputable: {type(exc).__name__}: {exc}")
        return {}


def compare(date_str: str, off: Path, on: Path, noise: Optional[Path], pp: float,
            truth: Optional[Path] = None) -> Dict[str, Any]:
    sims_off, sims_on = load_sims(off, date_str), load_sims(on, date_str)
    priors_fallback: Optional[Dict[str, float]] = None
    sims_noise = load_sims(noise, date_str) if noise else {}
    lines = main_lines(on, date_str)
    box = truth_box(truth, date_str) if truth else {}
    pts_true = truth_points(truth, date_str) if truth else {}
    sides: List[Dict[str, Any]] = []
    moved = {"on_vs_off": 0, "noise_vs_off": 0, "lines": 0}
    err_min: Dict[str, List[float]] = {}
    err_pts: Dict[str, List[float]] = {}
    prior_err: List[float] = []
    for game, s_on in sorted(sims_on.items()):
        stand = ((s_on.get("context") or {}).get("no_history_standins")) or {}
        s_off = sims_off.get(game)
        if not stand or s_off is None:
            continue
        for side in ("home", "away"):
            tri = str(s_on.get(side) or "").upper()
            if tri not in stand:
                continue
            r_on, r_off = side_rows(s_on, side), side_rows(s_off, side)
            r_noise = side_rows(sims_noise[game], side) if game in sims_noise else {}
            mates = sorted(set(r_on) & set(r_off))
            per = []
            for k in mates:
                a, b = r_off[k], r_on[k]
                rec = {"player": b.get("player_name"),
                       "min_off": round(float(a.get("min_mean") or 0), 2), "min_on": round(float(b.get("min_mean") or 0), 2),
                       "pts_off": round(float(a.get("pts_mean") or 0), 2), "pts_on": round(float(b.get("pts_mean") or 0), 2)}
                if k in r_noise:
                    rec["min_noise"] = round(float(r_noise[k].get("min_mean") or 0), 2)
                    rec["pts_noise"] = round(float(r_noise[k].get("pts_mean") or 0), 2)
                for stat in MAIN_STATS.values():
                    line = lines.get((k, stat))
                    if line is None:
                        continue
                    po, pf = p_over(b, stat, line), p_over(a, stat, line)
                    if po is None or pf is None:
                        continue
                    moved["lines"] += 1
                    moved["on_vs_off"] += int(abs(po - pf) >= pp / 100.0)
                    if k in r_noise:
                        pn = p_over(r_noise[k], stat, line)
                        if pn is not None:
                            moved["noise_vs_off"] += int(abs(pn - pf) >= pp / 100.0)
                if box:
                    act = box.get((tri, k))
                    if act is not None and act["min"] > 0:
                        rec["min_actual"] = act["min"]
                        err_min.setdefault(f"{game}:{tri}", []).append(abs(rec["min_on"] - act["min"]) - abs(rec["min_off"] - act["min"]))
                        if k in pts_true:
                            rec["pts_actual"] = pts_true[k]
                            err_pts.setdefault(f"{game}:{tri}", []).append(abs(rec["pts_on"] - pts_true[k]) - abs(rec["pts_off"] - pts_true[k]))
                per.append(rec)
            st = stand[tri]
            for s in st:
                act = box.get((tri, name_key(s.get("player_name")))) if box else None
                if act is not None and act["min"] > 0:
                    s["min_actual"] = act["min"]
                    if s.get("minutes_prior") is None:
                        if priors_fallback is None:
                            priors_fallback = recomputed_priors(on, date_str)
                        s["minutes_prior"] = priors_fallback.get(name_key(s.get("player_name")))
                    if s.get("minutes_prior") is not None:
                        prior_err.append(abs(float(s["minutes_prior"]) - act["min"]))
            sides.append({
                "game": game, "team": tri, "standins": st,
                "teammates": len(mates),
                "d_min_teammates": round(sum(r["min_on"] - r["min_off"] for r in per), 2),
                "d_pts_teammates": round(sum(r["pts_on"] - r["pts_off"] for r in per), 2),
                "standin_min": round(sum(float(s.get("min_mean") or 0) for s in st), 2),
                "standin_pts": round(sum(float(s.get("pts_mean") or 0) for s in st), 2),
                "team_pts_off": round(float(((s_off.get("score") or {}).get(side) or {}).get("mean") or 0), 2) if isinstance((s_off.get("score") or {}).get(side), dict) else None,
                "players": per,
            })
    report: Dict[str, Any] = {"date": date_str, "sides": sides, "lines_moved": moved, "pp": pp}
    if truth:
        report["truth"] = {"minutes": cluster_ci(err_min), "points": cluster_ci(err_pts)}
        report["minutes_prior_mae"] = (sum(prior_err) / len(prior_err), len(prior_err)) if prior_err else (None, 0)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", required=True)
    ap.add_argument("--off", required=True, type=Path)
    ap.add_argument("--on", required=True, type=Path)
    ap.add_argument("--noise", type=Path)
    ap.add_argument("--truth", type=Path, help="processed dir holding rotation_stints/player_checks_<date>.csv")
    ap.add_argument("--pp", type=float, default=3.0)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    rep = compare(args.date, args.off, args.on, args.noise, args.pp, args.truth)
    for s in rep["sides"]:
        names = ", ".join(f"{x.get('player_name')} {float(x.get('min_mean') or 0):.1f}m {float(x.get('pts_mean') or 0):.1f}p" for x in s["standins"])
        print(f"{s['game']:<8} {s['team']}: stand-in {names} | teammates {s['teammates']}: "
              f"d_min {s['d_min_teammates']:+.1f} d_pts {s['d_pts_teammates']:+.1f}")
        for r in sorted(s["players"], key=lambda r: r["min_on"] - r["min_off"])[:4]:
            noise = f" (noise {r['min_noise'] - r['min_off']:+.1f}m {r['pts_noise'] - r['pts_off']:+.1f}p)" if "min_noise" in r else ""
            print(f"      {r['player']:<26} min {r['min_off']:5.1f} -> {r['min_on']:5.1f}  pts {r['pts_off']:5.1f} -> {r['pts_on']:5.1f}{noise}")
    m = rep["lines_moved"]
    print(f"PRICED MAIN LINES (teammates): {m['lines']}; moved >= {args.pp:g} pp on vs off: {m['on_vs_off']}; "
          f"noise vs off: {m['noise_vs_off']}")
    if "truth" in rep:
        for label, (mean, lo, hi, n) in rep["truth"].items():
            print(f"TRUTH {label}: paired |on-actual|-|off-actual| mean {mean:+.3f} 95% CI [{lo:+.3f}, {hi:+.3f}] n={n}")
        mae, n = rep["minutes_prior_mae"]
        print(f"STAND-IN minutes prior MAE vs actual: {mae if mae is None else round(mae, 2)} (n={n}; sanity bound 8.0)")
    if args.json:
        args.json.write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
