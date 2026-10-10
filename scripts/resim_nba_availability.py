"""As-of NBA SmartSim re-run, base vs availability rule, PAIRED (lane `nba-prop-calibration`, 2026-10-05).

WHY. On the committed pre-tip sims, NBA's SmartSim gives 44.5 of every 240 team minutes to players who did not play
(findings_2026-10-02_nba_lines_props_backtest.md, "NBA sim availability"). WNBA's K=1 rule drops too many real NBA
players; "missed the team's last 2 games" (K=2) was train-selected and test-confirmed on minutes alone. The prop
EFFECT needs the engine's own re-allocation, so this re-runs TODAY's engine per date, twice, identical except for
the rule:

  arm `base`  : SYNDICATE_WNBA_SIM_AVAILABILITY=0
  arm `avail` : SYNDICATE_WNBA_SIM_AVAILABILITY=1, ..._MISSED_GAMES=2

THE CODE IS A SCRATCH COPY (--code), patched by `patch_code` so the availability module also runs for NBA and reads
the NBA regular-season history (`player_logs.csv`; NBA's `boxscores_history.csv` holds only the playoffs). Nothing
here changes production code.

AS-OF, per date D, on a scratch copy of the NBA data root (--pristine, a COPY of the fleet's nba_source/data):
  * history files truncated to rows strictly before D (player_logs, features, games_nba_api, boxscores_history);
  * every full-season fit / postgame artifact removed (REMOVE_ALWAYS), every dated output removed;
  * D's pregame inputs: production's committed `predictions_D.csv` and `game_odds_D.csv` (pre-tip, the as-of
    archive), and D's prop snapshot rebuilt from the OddsAPI historical backfill (45 min before each tip);
  * roster mode FORCED to "pregame" -- production ran D on the day (pregame_safe), but the resolver maps a past
    date to "historical", which lets ESPN/processed BOX SCORES fill a thin pool (a leak of who played).
NOT AS-OF, stated in the findings: the season roster file (rosters_2025-26.csv, end-of-season), model weights, and
TODAY's code. ABSENT: pregame injuries (no NBA injury history before 2026-09-30) -- so both arms measure the
no-injury-feed case.

Usage (WSL, from the code copy):
  python scripts/resim_nba_availability.py prepare --code ~/nba_resim/code
  python scripts/resim_nba_availability.py run --arm base  --dates 2026-03-01..2026-04-12 --n-sims 500 ...
  python scripts/resim_nba_availability.py run --arm avail --dates ... (same args)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

HISTORY_FILES = {
    "processed/player_logs.csv": "GAME_DATE",
    "processed/features.csv": "date",
    "processed/boxscores_history.csv": "date",
    "raw/games_nba_api.csv": "date",
}
REMOVE_ALWAYS = ("processed/features.parquet", "raw/games_nba_api.parquet", "processed/team_period_shares.csv",
                 "processed/home_court_advantage.json", "processed/lineup_player_baselines.parquet",
                 "processed/lineup_teammate_effects.parquet", "raw/injuries.csv",
                 "processed/rotation_stints_history.csv", "processed/rotation_stints_history.parquet",
                 "processed/pbp_espn_history.csv", "processed/pbp_espn_history.parquet",
                 "processed/pair_minutes_history.csv", "processed/pair_minutes_history.parquet",
                 "processed/play_context_history.csv", "processed/play_context_history.parquet",
                 "processed/player_stat_calibration.json", "processed/quarters_blend_weights.json",
                 "processed/nba_prop_book_blend.json")
DATED_RE = re.compile(r"(20\d\d-\d\d-\d\d)")
ARM_ENV = {
    "base": {"SYNDICATE_WNBA_SIM_AVAILABILITY": "0"},
    "avail": {"SYNDICATE_WNBA_SIM_AVAILABILITY": "1", "SYNDICATE_WNBA_SIM_AVAILABILITY_MISSED_GAMES": "2"},
}


def _date_of(name: str) -> Optional[str]:
    m = DATED_RE.search(name)
    return m.group(1) if m else None


def patch_code(code: Path) -> Dict[str, int]:
    """Let the availability module run for NBA, reading NBA's regular-season history. Scratch copy only."""
    p = code / "syndicate" / "features" / "shared" / "wnba_sim_availability.py"
    s = p.read_text(encoding="utf-8")
    gate = 'if str(league_code or "").strip().lower() != "wnba":'
    hist = "by_team, seen, reason = _read_history(Path(processed_root) / HISTORY_FILE, str(date_str)[:10])"
    n = {"gate": s.count(gate), "hist": s.count(hist)}
    if n == {"gate": 1, "hist": 1}:
        s = s.replace(gate, 'if str(league_code or "").strip().lower() not in {"wnba", "nba"}:')
        s = s.replace(hist, "by_team, seen, reason = _read_history(Path(processed_root) / ("
                            "'player_logs.csv' if (Path(processed_root) / 'player_logs.csv').is_file() and "
                            "'nba_source' in str(processed_root) else HISTORY_FILE), str(date_str)[:10])")
        p.write_text(s, encoding="utf-8")
    elif "not in {\"wnba\", \"nba\"}" not in s:
        raise SystemExit(f"patch_code: unexpected module shape {n}; re-derive the patch")
    return n


def _truncate_csv(src: Path, dst: Path, col: str, cutoff: str) -> int:
    import pandas as pd
    df = pd.read_csv(src, low_memory=False)
    d = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
    out = df[d < cutoff]
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dst, index=False)
    return len(out)


def prepare_scratch(pristine: Path, scratch: Path, d: str, asof: Path, props_csv: Path) -> Dict:
    pdata, sdata = pristine / "nba_source" / "data", scratch / "nba_source" / "data"
    if sdata.exists():
        shutil.rmtree(sdata)
    info: Dict = {"date": d}
    for sub in ("raw", "processed"):
        (sdata / sub).mkdir(parents=True, exist_ok=True)
        for p in (pdata / sub).iterdir():
            if p.is_file() and not _date_of(p.name) and f"{sub}/{p.name}" not in HISTORY_FILES:
                shutil.copy2(p, sdata / sub / p.name)
    for p in (pdata / "processed").glob("schedule_*"):
        shutil.copy2(p, sdata / "processed" / p.name)
    # ESPN box starters (P2 rotation_stints/player_checks_<date>.csv) feed the #473 NBA starter flags. Dated and in a
    # sub-directory, so the loop above never copied them: every replay ran with starters unfed (probe 2026-10-10:
    # 0/18 engine calls). As-of: only dates strictly BEFORE the slate.
    pc_src = pdata / "processed" / "rotation_stints"
    if pc_src.is_dir():
        (sdata / "processed" / "rotation_stints").mkdir(parents=True, exist_ok=True)
        n_pc = 0
        for p in pc_src.glob("player_checks_*.csv"):
            pd_ = _date_of(p.name)
            if pd_ and pd_ < d:
                shutil.copy2(p, sdata / "processed" / "rotation_stints" / p.name)
                n_pc += 1
        info["player_checks_files"] = n_pc
    for rel, col in HISTORY_FILES.items():
        if (pdata / rel).exists():
            info[rel] = _truncate_csv(pdata / rel, sdata / rel, col, d)
    for rel in REMOVE_ALWAYS:
        (sdata / rel).unlink(missing_ok=True)
    for fam, name in (("predictions", f"predictions_{d}.csv"), ("game_odds", f"game_odds_{d}.csv")):
        src = asof / fam / f"{d}.csv"
        if src.exists():
            shutil.copy2(src, sdata / "processed" / name)
            info[fam] = True
    shutil.copy2(props_csv, sdata / "processed" / f"oddsapi_player_props_{d}.csv")
    shutil.copy2(props_csv, sdata / "raw" / f"odds_nba_player_props_{d}.csv")
    return info


def _dates(spec: str, asof: Path) -> List[str]:
    lo, hi = spec.split("..")
    have = sorted({_date_of(p.name) for p in (asof / "predictions").glob("*.csv")} - {None})
    return [d for d in have if lo <= d <= hi]


def run(args) -> int:
    code, pristine, asof = Path(args.code), Path(args.pristine), Path(args.asof)
    archive = Path(args.archive) / args.arm
    scratch = Path(args.scratch) / f"{args.arm}_w{args.worker}"
    sys.path[:0] = [str(code / "scripts"), str(code), str(code / "vendor" / "nba_betting_repo" / "src")]
    import backtest_nba_lines_props as bt

    class BtArgs:
        out = Path(args.bt_out)

    env = {"SYNDICATE_DATA_ROOT": str(scratch), "SYNDICATE_NBA_SOURCE_ROOT": str(scratch / "nba_source"),
           "NBA_BETTING_DATA_ROOT": str(scratch / "nba_source" / "data"), "OMP_NUM_THREADS": "1",
           "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONUNBUFFERED": "1", **ARM_ENV[args.arm]}
    for k in ("ODDS_API_KEY", "ODDSAPI_KEY"):
        os.environ.pop(k, None)
    os.environ.update(env)
    from syndicate.features.shared import basketball_props_smart_sim as bpss
    bpss._resolve_smart_sim_roster_mode_local = lambda **_k: "pregame"  # see module docstring: no box-score leak
    from syndicate.features.shared.basketball_props_predictions import export_props_predictions_local

    dates = [d for i, d in enumerate(_dates(args.dates, asof)) if i % args.workers == args.worker]
    for d in dates:
        out = archive / d
        if (out / "phase_sim.json").exists():
            continue
        out.mkdir(parents=True, exist_ok=True)
        t0 = datetime.now()
        props_csv = bt.hist_props_csv(BtArgs, d)
        if props_csv is None:
            (out / "phase_sim.json").write_text(json.dumps({"date": d, "error": "no backfilled props snapshot"}))
            continue
        info = prepare_scratch(pristine, scratch, d, asof, props_csv)
        src_root = scratch / "nba_source"
        pred_fp = src_root / "data" / "processed" / f"props_predictions_{d}.csv"
        try:
            rows, _ = export_props_predictions_local(
                source_root=src_root, date_str=d, out_path=pred_fp, calib_window=7, calibrate_player=True,
                player_calib_window=30, player_min_pairs=6, player_shrink_k=8, use_smart_sim=True,
                smart_sim_n_sims=args.n_sims, smart_sim_pbp=True, smart_sim_workers=1, smart_sim_overwrite=True,
                log_file=out / "phase_sim.log")
            info["rows"] = rows
        except Exception as exc:  # noqa: BLE001
            info["error"] = repr(exc)[:500]
        for p in (src_root / "data" / "processed").glob(f"*{d}*"):
            if p.name.startswith(("props_predictions_", "smart_sim_", "cards_sim_detail_")):
                shutil.copy2(p, out / p.name)
        log = (out / "phase_sim.log").read_text(encoding="utf-8", errors="replace") if (out / "phase_sim.log").exists() else ""
        info["availability_lines"] = [ln for ln in log.splitlines() if "SIM_AVAILABILITY" in ln or "wnba_sim_availability" in ln][:5]
        info.update(arm=args.arm, n_sims=args.n_sims, seconds=round((datetime.now() - t0).total_seconds(), 1),
                    sims=len(list(out.glob("smart_sim_*.json"))))
        (out / "phase_sim.json").write_text(json.dumps(info), encoding="utf-8")
        print("SIM", json.dumps(info), flush=True)
    return 0


HIST_MARKETS = {"player_points": "pts", "player_rebounds": "reb", "player_assists": "ast", "player_threes": "threes",
                "player_points_rebounds_assists": "pra", "player_points_rebounds": "pr", "player_points_assists": "pa",
                "player_rebounds_assists": "ra", "player_steals": "stl", "player_blocks": "blk"}
SCORE_STATS = ("pts", "reb", "ast", "threes", "pra")


def _load_arm(archive: Path, arm: str) -> Dict:
    """{(date, game_file, norm_name): {"team", "min", stat_mean.., stat_sd..}} for one arm."""
    from syndicate.features.shared.basketball_props_edges import _norm_name
    out: Dict = {}
    for f in sorted((archive / arm).glob("*/smart_sim_*.json")):
        d = f.parent.name
        sim = json.loads(f.read_text(encoding="utf-8"))
        for side in ("home", "away"):
            for pl in (sim.get("players") or {}).get(side) or []:
                nk = _norm_name(str(pl.get("player_name") or ""))
                if not nk:
                    continue
                rec = {"team": str(sim.get(side) or ""), "min": float(pl.get("min_mean") or 0.0)}
                for s in SCORE_STATS + ("pr", "pa", "ra", "stl", "blk"):
                    if pl.get(f"{s}_mean") is not None:
                        rec[s] = float(pl[f"{s}_mean"])
                        rec[f"{s}_sd"] = float(pl.get(f"{s}_sd") or 0.0)
                out[(d, f.name, nk)] = rec
    return out


def score(args) -> int:
    """Paired base-vs-avail scoring on the dates BOTH arms finished."""
    from collections import Counter, defaultdict
    code = Path(args.code)
    sys.path[:0] = [str(code / "scripts"), str(code)]
    import backtest_nba_lines_props as bt
    from syndicate.features.shared.basketball_props_edges import _norm_name

    class BtArgs:
        out = Path(args.bt_out)

    archive = Path(args.archive)
    A, B = _load_arm(archive, "base"), _load_arm(archive, "avail")
    dates = sorted({k[0] for k in A} & {k[0] for k in B})
    logs = [r for r in bt.fetch_player_logs(BtArgs) if r["date"] in set(dates)]
    act: Dict = {}
    amb = Counter()
    for r in logs:
        key = (r["date"], _norm_name(r["name"]))
        if key in act:
            amb["same_name_twice"] += 1
        act[key] = r
    rep: Dict = {"dates": len(dates), "date_range": [dates[0], dates[-1]] if dates else None,
                 "games": len({(k[0], k[1]) for k in A if k[0] in dates})}

    def team_minutes(arm):  # minutes per team-game handed to players with no log that day
        tg: Dict = defaultdict(lambda: [0.0, 0.0])
        for (d, g, nk), r in arm.items():
            if d not in dates:
                continue
            played = (d, nk) in act and act[(d, nk)]["min"] > 0
            tg[(d, g, r["team"])][0 if played else 1] += r["min"]
        n = len(tg)
        return {"team_games": n, "to_players": round(sum(v[0] for v in tg.values()) / max(1, n), 2),
                "to_non_players": round(sum(v[1] for v in tg.values()) / max(1, n), 2)}

    rep["minutes_split"] = {"base": team_minutes(A), "avail": team_minutes(B)}
    paired = [(k, A[k], B[k]) for k in A if k in B and k[0] in dates and (k[0], k[2]) in act and act[(k[0], k[2])]["min"] > 0]
    rep["paired_played_rows"] = len(paired)

    def cmp(metric_rows):  # rows: (game, base_value, avail_value); returns both means + paired diff CI
        if not metric_rows:
            return {"n": 0}
        b = bt._boot_ci([(g, x) for g, x, _ in metric_rows])
        v = bt._boot_ci([(g, y) for g, _, y in metric_rows])
        dlt = bt._boot_ci([(g, y - x) for g, x, y in metric_rows])
        return {"n": len(metric_rows), "base": round(b[0], 4), "avail": round(v[0], 4),
                "diff": [round(x, 4) for x in dlt]}

    mins = [(f"{k[0]}|{k[1]}", ra["min"] - act[(k[0], k[2])]["min"], rb["min"] - act[(k[0], k[2])]["min"]) for k, ra, rb in paired]
    rep["minutes_bias"] = cmp(mins)
    rep["minutes_mae"] = cmp([(g, abs(x), abs(y)) for g, x, y in mins])
    rep["prop_mae"] = {}
    for s in SCORE_STATS:
        rows = [(f"{k[0]}|{k[1]}", abs(ra[s] - act[(k[0], k[2])][s]), abs(rb[s] - act[(k[0], k[2])][s]))
                for k, ra, rb in paired if s in ra and s in rb]
        rep["prop_mae"][s] = cmp(rows)
    # coverage: who is in one arm's pool but not the other's
    cov = Counter()
    for arm_a, arm_b, tag in ((A, B, "dropped_by_avail"), (B, A, "added_by_avail")):
        for k, r in arm_a.items():
            if k[0] in dates and k not in arm_b:
                played = (k[0], k[2]) in act and act[(k[0], k[2])]["min"] > 0
                cov[f"{tag}_{'played' if played else 'did_not_play'}"] += 1
                if played:
                    cov[f"{tag}_played_actual_minutes"] += act[(k[0], k[2])]["min"]
    rep["coverage"] = dict(cov)
    # Brier at the de-vigged two-sided book line (backfill, pre-tip quotes only)
    idx = {(k[0], k[2]): (k, ra, rb) for k, ra, rb in paired}
    brier: Dict = defaultdict(list)
    bstats = Counter()
    for d in dates:
        src = Path(args.bt_out) / "cache" / "oddsapi_hist" / "props" / d
        for f in sorted(src.glob("*.json")) if src.exists() else []:
            ev = (json.loads(f.read_text(encoding="utf-8")) or {}).get("data") or {}
            commence = str(ev.get("commence_time") or "")
            quotes: Dict = defaultdict(dict)
            for bk in ev.get("bookmakers") or []:
                for mk in bk.get("markets") or []:
                    s = HIST_MARKETS.get(mk.get("key"))
                    upd = str(mk.get("last_update") or bk.get("last_update") or "")
                    if not s or (upd and commence and upd >= commence):
                        continue
                    for oc in mk.get("outcomes") or []:
                        side = str(oc.get("name") or "").upper()
                        if side in ("OVER", "UNDER") and oc.get("point") is not None:
                            quotes[(_norm_name(oc.get("description")), s, float(oc["point"]), bk.get("key"))][side] = oc.get("price")
            for (nk, s, line, _book), sides in quotes.items():
                if "OVER" not in sides or "UNDER" not in sides or abs(line - round(line)) < 1e-9:
                    continue
                hit = idx.get((d, nk))
                if not hit or s not in hit[1] or s not in hit[2]:
                    bstats["line_without_paired_player"] += 1
                    continue
                p_book = bt._devig(sides["OVER"], sides["UNDER"])
                if p_book is None:
                    continue
                k, ra, rb = hit
                y = 1.0 if act[(d, nk)][s] > line else 0.0

                def p_over(r):
                    sd = max(r[f"{s}_sd"], 1e-6)
                    return 1.0 - bt._ncdf((line - r[s]) / sd)

                g = f"{k[0]}|{k[1]}"
                brier[s].append((g, (p_over(ra) - y) ** 2, (p_over(rb) - y) ** 2, (p_book - y) ** 2))
                bstats["lines"] += 1
    rep["book_line_brier"] = {}
    for s, rows in sorted(brier.items()):
        r = cmp([(g, x, y) for g, x, y, _ in rows])
        r["book"] = round(sum(z for *_, z in rows) / len(rows), 4)
        r["avail_minus_book"] = [round(x, 4) for x in bt._boot_ci([(g, y - z) for g, _, y, z in rows])]
        rep["book_line_brier"][s] = r
    rep["book_line_counts"] = dict(bstats)
    rep["join"] = dict(amb)
    text = json.dumps(rep, indent=1)
    print(text)
    if args.out_json:
        Path(args.out_json).write_text(text, encoding="utf-8")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=("prepare", "run", "score"))
    ap.add_argument("--code", required=True)
    ap.add_argument("--pristine", default="")
    ap.add_argument("--scratch", default="")
    ap.add_argument("--archive", default="")
    ap.add_argument("--asof", default="/mnt/c/tmp/nba_bt/out/asof")
    ap.add_argument("--bt-out", default="/mnt/c/tmp/nba_bt/out")
    ap.add_argument("--arm", choices=tuple(ARM_ENV), default="base")
    ap.add_argument("--dates", default="2026-03-01..2026-04-12")
    ap.add_argument("--n-sims", type=int, default=500)
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out-json", default="")
    args = ap.parse_args(argv)
    if args.phase == "prepare":
        print("PATCH", json.dumps(patch_code(Path(args.code))))
        return 0
    return score(args) if args.phase == "score" else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
