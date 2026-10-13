"""Off-vs-on A/B of the smart sim's lineup TEAMMATE EFFECTS on NBA regular-season pregame sims (lane
`basketball-pregame-teammate-effects`, step 3; protocol pre-registered in that lane before any run).

The mechanism (`orchestrator/connected_game._apply_lineup_teammate_effects_to_priors`) is OFF on every production
pregame sim: its own ESPN name map (connected_game.py:54) falls back only to `pbp_espn_history.csv`, which NBA does not
have. This measures what switching it on would do, against actual results, before anyone decides to fix or retire it.

Per date D, on a SCRATCH copy (never the production data root):
  * P3's scratch recipe (`resim_nba_availability.prepare_scratch` + `record_nba_engine_inputs_asof._add_473_inputs`);
  * rotation_stints_history / pair_minutes_history / play_context_history (the last from the dated
    `rotation_stints/play_context_<date>.parquet`) restricted to season_type == regular and date < D;
  * the lineup tables REBUILT as of D by the production builder (the vendored `build_lineup_teammate_effects`,
    start = first regular date, end = D-1, min_minutes_together as production). Production reads the tables whole,
    with no date filter, so they must be rebuilt per date or the replay leaks the future;
  * ESPN boxscores stripped at both summary readers (pregame), roster mode "pregame" (production's).
Arms, same scratch, same fixed seed, production's n_sims: OFF (production code), ON (connected_game's map routed to
the native bpss map -- the only change), OFF2 (OFF repeated: seed determinism). Each arm's smart_sim JSONs are
copied to --out/<arm>/<date>/.

Grading is a separate pass (`--grade`), against player_logs (MIN > 0) from the pristine copy.

  nice -n 19 ~/.venvs/syndicate/bin/python scripts/replay_basketball_teammate_effects.py \\
      --code /mnt/c/tmp/syndicate-sessions/basketball-pregame-teammate-effects --pristine ~/nba_resim/pristine \\
      --scratch ~/te_replay/scratch --asof /mnt/c/tmp/nba_bt/out/asof --out /mnt/c/tmp/te_replay \\
      --dates 2025-11-12,2025-11-13
  ... --grade   (reads --out, writes --out/grade.json)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

REG_START = "2025-10-21"  # first 2025-26 regular-season date (rotation_stints_history season_type, verified)
SEED = 20261012
STATS = {"pts": "PTS", "reb": "REB", "ast": "AST", "threes": "FG3M", "stl": "STL", "blk": "BLK", "tov": "TOV"}


def _strip_box(summary: Any) -> Any:
    if isinstance(summary, dict) and "boxscore" in summary:
        summary = dict(summary)
        summary.pop("boxscore", None)
    return summary


def _regular_before(df, d: str):
    import pandas as pd

    days = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    keep = days < d
    if "season_type" in df.columns:
        keep &= df["season_type"].astype(str) == "regular"
    return df[keep]


def _asof_inputs(live: Path, dst: Path, d: str) -> Dict[str, int]:
    import pandas as pd

    info: Dict[str, int] = {}
    for name in ("rotation_stints_history", "pair_minutes_history"):
        df = _regular_before(pd.read_parquet(live / f"{name}.parquet"), d)
        df.to_parquet(dst / f"{name}.parquet", index=False)
        (dst / f"{name}.csv").unlink(missing_ok=True)
        info[name] = int(len(df))
    frames = [pd.read_parquet(p) for p in sorted((live / "rotation_stints").glob("play_context_*.parquet"))
              if REG_START <= p.stem.rsplit("_", 1)[-1] < d]
    pc = _regular_before(pd.concat(frames, ignore_index=True), d) if frames else pd.DataFrame()
    pc.to_parquet(dst / "play_context_history.parquet", index=False)
    info["play_context_history"] = int(len(pc))
    return info


def _build_tables(code: Path, processed: Path, d: str) -> Dict[str, Any]:
    import datetime as dt
    from types import SimpleNamespace

    vsrc = str(code / "vendor" / "nba_betting_repo" / "src")
    if vsrc not in sys.path:
        sys.path.append(vsrc)
    from nba_betting import lineup_context_features as lcf  # vendored: the builder production runs

    lcf.paths = SimpleNamespace(data_processed=processed)
    end = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
    info = lcf.build_lineup_teammate_effects(start_date=REG_START, end_date=end)
    out: Dict[str, Any] = {k: v for k, v in (info or {}).items() if isinstance(v, (str, int, float))}
    try:
        import pandas as pd

        tm = pd.read_parquet(processed / "lineup_teammate_effects.parquet")
        base = pd.read_parquet(processed / "lineup_player_baselines.parquet")
        out.update(tm_rows=int(len(tm)), tm_teams=int(tm["team"].nunique()), base_rows=int(len(base)),
                   base_teams=int(base["team"].nunique()))
    except Exception as exc:  # noqa: BLE001
        out["tables_error"] = f"{type(exc).__name__}: {exc}"[:200]
    return out


def run(args) -> int:
    code, pristine, asof = Path(args.code), Path(args.pristine).expanduser(), Path(args.asof)
    scratch = Path(args.scratch).expanduser()
    live = Path(args.live_processed).expanduser()
    out_root = Path(args.out)
    prod = Path("~/syndicate-prod/data").expanduser().resolve()
    if str(scratch.resolve()).startswith(str(prod)):
        raise SystemExit("REFUSED: scratch is inside the production data root")
    sys.path[:0] = [str(code / "scripts"), str(code)]
    os.environ.update({
        "SYNDICATE_DATA_ROOT": str(scratch), "SYNDICATE_NBA_SOURCE_ROOT": str(scratch / "nba_source"),
        "NBA_BETTING_DATA_ROOT": str(scratch / "nba_source" / "data"), "SYNDICATE_REFRESH_STATE_BACKEND": "file",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONUNBUFFERED": "1",
    })
    for k in [k for k in os.environ if any(m in k.upper() for m in ("KEYVALUE", "REDIS", "VALKEY", "ODDS_API", "ODDSAPI"))]:
        os.environ.pop(k, None)

    import numpy as np

    import resim_nba_availability as rs
    from record_nba_engine_inputs_asof import _add_473_inputs
    from syndicate.features.basketball_engine.orchestrator import boxscores as ob
    try:
        from syndicate.features.basketball_engine.orchestrator import connected_game as cg
    except ImportError:  # retired 2026-10-13 by this A/B; the ON arm needs the code it ran on (5568ac6e)
        cg = None
        if any(a in ("ON",) for a in args.arms.split(",")):
            raise SystemExit("ON arm: teammate effects were retired after this A/B; run it from commit 5568ac6e")
    from syndicate.features.basketball_engine.orchestrator import hooks
    from syndicate.features.shared import basketball_props_smart_sim as bpss
    from syndicate.features.shared.basketball_props_predictions import export_props_predictions_local

    bpss._resolve_smart_sim_roster_mode_local = lambda **_k: "pregame"
    orig_bs = bpss._espn_summary_local
    bpss._espn_summary_local = lambda **kw: _strip_box(orig_bs(**kw))
    if hasattr(ob, "_espn_summary"):  # gone with the retired teammate-effects name map
        orig_os = ob._espn_summary
        ob._espn_summary = lambda *a, **kw: _strip_box(orig_os(*a, **kw))
        if cg is not None:
            cg._espn_summary = ob._espn_summary

    orig_run = bpss._smart_sim_run_date_local

    def seeded_run(**kw):
        kw["seed"] = SEED
        np.random.seed(SEED)
        random.seed(SEED)
        return orig_run(**kw)

    bpss._smart_sim_run_date_local = seeded_run

    off_map = cg._espn_name_to_id_map_for_game if cg is not None else None

    def on_map(date_str, home_tri, away_tri, event_id=None, *, orch):
        return hooks._espn_name_to_id_map_for_game(date_str, home_tri, away_tri, event_id, orch=orch)

    out_root.mkdir(parents=True, exist_ok=True)
    log = (out_root / "run.jsonl").open("a", encoding="utf-8")
    for d in [x.strip() for x in args.dates.split(",") if x.strip()]:
        props_csv = asof / "props_odds_hist" / f"{d}.csv"
        if not props_csv.exists() or props_csv.stat().st_size <= 1000:
            print(f"SKIP {d} no as-of props snapshot", flush=True)
            continue
        rs.prepare_scratch(pristine, scratch, d, asof, props_csv)
        processed = scratch / "nba_source" / "data" / "processed"
        _add_473_inputs(live, processed, d)
        inputs = _asof_inputs(live, processed, d)
        tables = _build_tables(code, processed, d)
        print(f"TABLES {d} {json.dumps(inputs)} {json.dumps(tables)}", flush=True)
        for arm in [a for a in args.arms.split(",") if a]:
            if cg is not None:
                cg._espn_name_to_id_map_for_game = on_map if arm == "ON" else off_map
            for f in processed.glob(f"smart_sim_{d}_*.json"):
                f.unlink()
            try:
                export_props_predictions_local(
                    source_root=scratch / "nba_source", date_str=d, out_path=processed / f"props_predictions_{d}.csv",
                    calib_window=7, calibrate_player=True, player_calib_window=30, player_min_pairs=6,
                    player_shrink_k=8, use_smart_sim=True, smart_sim_n_sims=args.n_sims, smart_sim_pbp=True,
                    smart_sim_workers=1, smart_sim_overwrite=True, log_file=out_root / f"export_{arm}_{d}.log")
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL {arm} {d} {exc!r}"[:300], flush=True)
            dst = out_root / arm / d
            dst.mkdir(parents=True, exist_ok=True)
            n_files = applied = sides = 0
            for f in processed.glob(f"smart_sim_{d}_*.json"):
                shutil.copy2(f, dst / f.name)
                n_files += 1
                le = (json.load(open(f)).get("lineup_effects") or {})
                for s in ("home", "away"):
                    sides += 1
                    applied += int(bool((le.get(s) or {}).get("applied")))
            print(f"ARM {arm} {d} games={n_files} lineup_effects_applied={applied}/{sides}", flush=True)
            log.write(json.dumps({"date": d, "arm": arm, "games": n_files, "applied": applied, "sides": sides,
                                  "inputs": inputs, "tables": tables}) + "\n")
            log.flush()
    shutil.rmtree(scratch / "nba_source", ignore_errors=True)
    print("REPLAY_DONE", flush=True)
    return 0


def grade(args) -> int:
    import numpy as np
    import pandas as pd

    out_root = Path(args.out)
    logs = pd.read_csv(Path(args.pristine).expanduser() / "nba_source" / "data" / "processed" / "player_logs.csv",
                       low_memory=False)
    logs["date"] = pd.to_datetime(logs["GAME_DATE"], errors="coerce").dt.strftime("%Y-%m-%d")
    logs["MIN"] = pd.to_numeric(logs["MIN"], errors="coerce")
    logs = logs[logs["MIN"] > 0]
    logs["pid"] = logs["PLAYER_ID"].astype(str)

    def frame(arm: str) -> pd.DataFrame:
        rows: List[Dict[str, Any]] = []
        for f in sorted((out_root / arm).glob("*/smart_sim_*.json")):
            d = json.load(open(f))
            game = f"{d.get('date')}_{d.get('home')}_{d.get('away')}"
            for side in ("home", "away"):
                for p in (d.get("players") or {}).get(side) or []:
                    r = {"game": game, "date": str(d.get("date")), "pid": str(p.get("player_id"))}
                    for s in STATS:
                        r[s] = p.get(f"{s}_mean")
                    rows.append(r)
        return pd.DataFrame(rows)

    off, on = frame("OFF"), frame("ON")
    off2 = frame("OFF2") if (out_root / "OFF2").exists() else None
    key = ["game", "date", "pid"]
    m = off.merge(on, on=key, suffixes=("_off", "_on"))
    act = logs[["date", "pid"] + list(STATS.values())].rename(columns={v: f"{k}_act" for k, v in STATS.items()})
    m = m.merge(act, on=["date", "pid"], how="inner")
    for arm in ("off", "on"):
        m[f"pra_{arm}"] = m[f"pts_{arm}"] + m[f"reb_{arm}"] + m[f"ast_{arm}"]
    m["pra_act"] = m["pts_act"] + m["reb_act"] + m["ast_act"]
    rng = np.random.default_rng(7)
    games = m["game"].unique()
    report: Dict[str, Any] = {"players": int(len(m)), "games": int(len(games)), "dates": sorted(m["date"].unique().tolist()),
                              "stats": {}}
    for s in list(STATS) + ["pra"]:
        e_off = (m[f"{s}_off"] - m[f"{s}_act"]).astype(float)
        e_on = (m[f"{s}_on"] - m[f"{s}_act"]).astype(float)
        diff = (e_on.abs() - e_off.abs())
        by_game = pd.DataFrame({"g": m["game"], "d": diff}).groupby("g")["d"].agg(["sum", "count"])
        boots = []
        for _ in range(2000):
            pick = by_game.loc[rng.choice(games, size=len(games), replace=True)]
            boots.append(float(pick["sum"].sum() / pick["count"].sum()))
        moved = (m[f"{s}_on"] - m[f"{s}_off"]).abs()
        report["stats"][s] = {
            "mae_off": float(e_off.abs().mean()), "mae_on": float(e_on.abs().mean()),
            "bias_off": float(e_off.mean()), "bias_on": float(e_on.mean()),
            "paired_dmae": float(diff.mean()), "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
            "mean_abs_on_minus_off": float(moved.mean()), "share_moved_gt_0.05": float((moved > 0.05).mean()),
        }
    if off2 is not None:
        mm = off.merge(off2, on=key, suffixes=("", "_2"))
        report["seed_determinism_max_abs_pts_diff"] = float((mm["pts"] - mm["pts_2"]).abs().max()) if len(mm) else None
    runlog = [json.loads(l) for l in open(out_root / "run.jsonl", encoding="utf-8")]
    report["arms"] = {a: {"applied": sum(r["applied"] for r in runlog if r["arm"] == a),
                          "sides": sum(r["sides"] for r in runlog if r["arm"] == a)} for a in {r["arm"] for r in runlog}}
    (out_root / "grade.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", required=True)
    ap.add_argument("--pristine", required=True)
    ap.add_argument("--scratch", default="~/te_replay/scratch")
    ap.add_argument("--asof", default="/mnt/c/tmp/nba_bt/out/asof")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dates", default="")
    ap.add_argument("--arms", default="OFF,ON,OFF2")
    ap.add_argument("--n-sims", type=int, default=500)
    ap.add_argument("--live-processed", default="~/syndicate-prod/data/nba_source/data/processed",
                    help="READ-ONLY source of the histories and #473's inputs")
    ap.add_argument("--grade", action="store_true")
    args = ap.parse_args(argv)
    return grade(args) if args.grade else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
