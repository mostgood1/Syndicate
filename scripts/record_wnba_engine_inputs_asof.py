"""Record AS-OF pregame engine inputs for the 2026 WNBA season (lane `wnba-native-live-cutover`, P5).

P5's verification resumes the native engine from P2's live state at in-game checkpoints, on the SAME engine
kwargs the production pregame sim would have handed the engine that day (player frames, lineups and weights,
`EventSimConfig`, team adjustments, quarter targets). Production persists none of them for 2026 WNBA dates.
This is the WNBA twin of P3's `scripts/record_nba_engine_inputs_asof.py`: it re-runs today's production
pregame path as of each date on a SCRATCH data root and intercepts the first engine call of every game.

THE SCRATCH RECIPE IS THE `wnba-lines-props-backtest` LANE'S (`backtest_wnba_lines_props.prepare_scratch`,
imported, not copied): history truncated to games strictly before D, D's pregame odds and that lane's
phase-1 outputs (game model predictions, totals calibration) restored from its archive. Then
`export_props_predictions_local` with production's arguments (`run_sim_phase`).

PRODUCTION'S WNBA FILE SWITCHES ARE COPIED IN, READ-ONLY. Measured 2026-10-12: production's WNBA processed root
carries `wnba_sim_availability.json`, `wnba_sim_rate_shrink.json`, `wnba_prop_dispersion.json` and
`wnba_prop_shape.json`, all `enabled: true` (since 2026-10-04/05); the pristine copy carries NONE. Without them
the as-of engine would run with availability and rate shrink OFF -- not the engine production runs, and not
the one P5 cuts over to. Each switch's presence is printed per date.

WRITTEN THROUGH `live_resim.persist_engine_inputs(..., league="wnba")` (P3 made it league-parametric
2026-10-12 at this lane's request), so the format the WNBA live resume reads can never drift from what is
written here. Record with the code you will resume with: resume runs on `_engine_for_league_local("wnba")`.

ROTATION INPUTS AS OF D: see `add_rotation_inputs`.

Only the kwargs are kept; the few draws the run makes are discarded (`--n-sims` small: inputs do not depend on
n_sims). Run in WSL with the fleet venv, at nice 19, never against the production data root:

  nice -n 19 ~/.venvs/syndicate/bin/python scripts/record_wnba_engine_inputs_asof.py \\
      --code /mnt/c/tmp/syndicate-sessions/wnba-native-live-cutover --pristine ~/wnba_bt/pristine \\
      --scratch ~/wnba_live_bt/scratch --archive ~/wnba_bt/archive --out-root ~/wnba_live_bt/engine_inputs_asof \\
      --start 2026-05-08 --end 2026-10-07 [--worker 0 --workers 2]
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

LEAGUE = "wnba"
SWITCH_FILES = ("wnba_sim_availability.json", "wnba_sim_rate_shrink.json", "wnba_prop_dispersion.json",
                "wnba_prop_shape.json")


def copy_switches(live_processed: Path, dst: Path) -> Dict[str, bool]:
    """Production's WNBA file switches into the scratch processed root. Read-only on the source."""
    out: Dict[str, bool] = {}
    for name in SWITCH_FILES:
        src = live_processed / name
        out[name] = src.exists()
        if src.exists():
            shutil.copy2(src, dst / name)
    return out


def add_rotation_inputs(live_processed: Path, dst: Path, d: str) -> Dict[str, int]:
    """P2's WNBA rotation inputs, AS OF D, into the scratch processed root. Read-only on the source.

    The scratch recipe deletes `rotation_stints_history` (season-wide => future games), which left every as-of
    game with ZERO lineup pools (smoke 2026-08-12: 3/3 games `home_lineups`/`away_lineups` empty) while
    production's WNBA sim has had P2's history since 2026-10-09. The history carries a `date` column, so it is
    copied TRUNCATED to date < D (the sim also filters < D; this is the second guard). The player-checks name map
    reads files dated <= D, and D's own file only exists after the game, so only files dated < D are copied."""
    import pandas as pd

    out = {"stints_rows": 0, "player_checks": 0}
    src_csv = live_processed / "rotation_stints_history.csv"
    if src_csv.exists():
        df = pd.read_csv(src_csv, low_memory=False)
        df = df[pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d") < d]
        df.to_csv(dst / "rotation_stints_history.csv", index=False)
        df.to_parquet(dst / "rotation_stints_history.parquet", index=False)
        out["stints_rows"] = len(df)
    checks = dst / "rotation_stints"
    checks.mkdir(parents=True, exist_ok=True)
    for f in sorted((live_processed / "rotation_stints").glob("player_checks_*.csv")):
        if f.stem[len("player_checks_"):] < d:
            shutil.copy2(f, checks / f.name)
            out["player_checks"] += 1
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", required=True)
    ap.add_argument("--pristine", required=True)
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--archive", required=True, help="the wnba-lines-props-backtest as-of archive (phase-1 outputs)")
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--n-sims", type=int, default=2)
    ap.add_argument("--live-processed", default="~/syndicate-prod/data/wnba_source/data/processed",
                    help="READ-ONLY source of production's WNBA file switches")
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args(argv)

    code, pristine = Path(args.code), Path(args.pristine).expanduser()
    archive, out_root = Path(args.archive).expanduser(), Path(args.out_root).expanduser()
    scratch = Path(args.scratch).expanduser() / f"rec_w{args.worker}"
    live_processed = Path(args.live_processed).expanduser()
    prod = Path("~/syndicate-prod/data").expanduser().resolve()
    for p in (scratch, out_root):
        if str(p.resolve()).startswith(str(prod)):
            raise SystemExit(f"REFUSED: {p} is inside the production data root")

    sys.path[:0] = [str(code / "scripts"), str(code)]
    import backtest_wnba_lines_props as bt  # noqa: E402

    dates = sorted(p.name for p in archive.iterdir()
                   if p.is_dir() and args.start <= p.name <= args.end and (p / "phase_game.json").exists()
                   and (p / f"predictions_{p.name}.csv").exists())
    dates = [d for i, d in enumerate(dates) if i % args.workers == args.worker]
    bt.prepare_scratch(pristine, scratch, dates[0] if dates else "2026-01-01", None, False)
    for k, v in bt._env_for(scratch, code).items():
        os.environ[k] = v
    for k in [k for k in os.environ if any(m in k.upper() for m in ("KEYVALUE", "REDIS", "VALKEY", "ODDS_API", "ODDSAPI"))]:
        os.environ.pop(k, None)
    os.environ["SYNDICATE_REFRESH_STATE_BACKEND"] = "file"

    from syndicate.features.nba import live_resim as lr
    from syndicate.features.shared import basketball_props_smart_sim as bpss
    from syndicate.features.shared.basketball_props_predictions import export_props_predictions_local

    seen: Dict[Any, bool] = {}
    written = {"n": 0}
    cur = {"date": ""}
    orig = bpss._simulate_pbp_game_boxscore_local

    def recording(**kw):
        body = {k: v for k, v in kw.items() if k not in ("rng", "league_code")}
        key = tuple((k, id(v)) for k, v in sorted(body.items()))
        if kw.get("league_code", LEAGUE) == LEAGUE and key not in seen:
            seen[key] = True
            try:
                h = str(body["home_players"]["team"].iloc[0]).upper()
                a = str(body["away_players"]["team"].iloc[0]).upper()
                lr.persist_engine_inputs(cur["date"], h, a, body, root=out_root, league=LEAGUE)
                written["n"] += 1
            except Exception as exc:  # noqa: BLE001
                print(f"PERSIST_FAIL {cur['date']} {type(exc).__name__}: {exc}"[:300], flush=True)
        return orig(**kw)

    bpss._simulate_pbp_game_boxscore_local = recording
    for d in dates:
        done_dir = lr.engine_inputs_dir(d, root=out_root, league=LEAGUE)
        if done_dir.exists() and any(done_dir.glob("*.pkl")):
            continue
        bt.prepare_scratch(pristine, scratch, d, archive, restore_upto_incl=True)
        src_root = scratch / "wnba_source"
        switches = copy_switches(live_processed, src_root / "data" / "processed")
        print(f"SWITCHES {d} " + " ".join(f"{k}={'on' if v else 'MISSING'}" for k, v in switches.items()), flush=True)
        rot = add_rotation_inputs(live_processed, src_root / "data" / "processed", d)
        print(f"ROTATION {d} stints_rows_before_D={rot['stints_rows']} player_checks_before_D={rot['player_checks']}", flush=True)
        cur["date"] = d
        seen.clear()
        before = written["n"]
        try:
            export_props_predictions_local(
                source_root=src_root, date_str=d, out_path=src_root / "data" / "processed" / f"props_predictions_{d}.csv",
                calib_window=7, calibrate_player=True, player_calib_window=30, player_min_pairs=6, player_shrink_k=8,
                use_smart_sim=True, smart_sim_n_sims=args.n_sims, smart_sim_pbp=True, smart_sim_workers=1,
                smart_sim_overwrite=True, log_file=out_root / f"rec_{d}.log")
        except Exception as exc:  # noqa: BLE001
            print(f"REC_FAIL {d} {exc!r}"[:300], flush=True)
        print(f"REC {d} games={written['n'] - before}", flush=True)
    print(f"REC_DONE worker={args.worker} dates={len(dates)} games={written['n']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
