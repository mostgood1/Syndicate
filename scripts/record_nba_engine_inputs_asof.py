"""Record AS-OF pregame engine inputs for historical NBA games (lane `nba-native-live-resim`, P3).

The P3 checkpoint backtest (`scripts/basketball_live_checkpoint_backtest.py --projectors native_resim`) needs, per
historical game, the engine kwargs the PRODUCTION pregame sim would have built that day: player frames, lineups
and weights, `EventSimConfig`, team adjustments, quarter targets. Production persists none of them for past
dates. This re-runs the production pregame path as of each date on a SCRATCH data root -- the same scratch
recipe `scripts/resim_nba_availability.py` and the basketball-scenario-calibration sim harness use (pristine copy,
history files truncated to the date, as-of predictions / game odds / props snapshots) -- and intercepts the first
engine call of every game, writing its kwargs with `syndicate.features.nba.live_resim.persist_engine_inputs`.
Writing through the production persist function is deliberate: the backtest then reads the exact format the
live tick will read.

#473 (a31ba2bf): the scratch also gets the player_checks and nba_sim_total_inputs.json that feed NBA team quality and
starter flags (`_add_473_inputs`); inputs recorded before 2026-10-10 15:06Z carry the team-neutral sim and are
superseded. Only the kwargs are kept; the handful of draws the run makes is discarded (`--n-sims` small: inputs do not depend
on n_sims). Run in WSL with the fleet venv, at nice 19, never against the production data root:

  nice -n 19 ~/.venvs/syndicate/bin/python scripts/record_nba_engine_inputs_asof.py \
      --code /mnt/c/tmp/syndicate-sessions/nba-native-live-resim --pristine ~/nba_resim/pristine \
      --scratch ~/nba_live_bt/scratch --asof /mnt/c/tmp/nba_bt/out/asof --bt-out /mnt/c/tmp/nba_bt/out \
      --out-root /mnt/c/tmp/nba_live_bt/engine_inputs_asof --start 2025-11-01 --end 2026-02-28
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict


def _add_473_inputs(live_processed: Path, dst: Path, d: str, *, total_inputs: bool = True) -> None:
    """#473 (a31ba2bf) feeds NBA team quality and starter flags. The scratch recipe copies only top-level processed
    files, so without this every as-of game would replay the PRE-#473 (team-neutral) sim:
      * `rotation_stints/player_checks_<date>.csv` dated BEFORE the slate (starter flags read date < slate);
      * `nba_sim_total_inputs.json` (skip_def_subtraction, a data switch since 2026-10-10 15:06Z).
    Team ratings need nothing extra: they are built from the scratch's date-truncated player_logs.csv."""
    import shutil

    stints = dst / "rotation_stints"
    stints.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted((live_processed / "rotation_stints").glob("player_checks_*.csv")):
        if f.stem[len("player_checks_"):] < d:
            shutil.copy2(f, stints / f.name)
            n += 1
    ti = live_processed / "nba_sim_total_inputs.json"
    if total_inputs and ti.exists():
        shutil.copy2(ti, dst / ti.name)
    elif not total_inputs:
        (dst / ti.name).unlink(missing_ok=True)  # --no-total-inputs: the default-subtraction path (#695 arm)
    # LINEUP POOLS. `resim_nba_availability.REMOVE_ALWAYS` deletes rotation_stints_history / pair_minutes_history from
    # every scratch (the old vendored builder leaked future games into them), so every replay hit
    # `no_rotation_stints_history` and recorded home/away_lineups = None on 2,588/2,588 sides (nba-lineup-pools,
    # 2026-10-12). P2's native producer writes them date-keyed; copy them TRUNCATED to date < slate (the sim also
    # filters [slate - 28 d, slate)). Non-dated aggregates REMOVE_ALWAYS drops stay out: they would only leak.
    import csv as _csv

    hist = {}
    for name in ("rotation_stints_history.csv", "pair_minutes_history.csv"):
        src = live_processed / name
        if not src.exists():
            hist[name] = "absent"
            continue
        # RAW-STRING filter, never a pandas round-trip: re-writing through a DataFrame turns an int column holding
        # any blank into floats ("1610612742.0"), and on 2026-01-15 that refused 3 more sides with
        # `rotation_minutes_conflict_with_current_signals` than the same history read in place (nba-lineup-pools).
        kept = 0
        with src.open(newline="", encoding="utf-8") as fin, (dst / name).open("w", newline="", encoding="utf-8") as fout:
            reader = _csv.reader(fin)
            writer = _csv.writer(fout, lineterminator="\n")
            header = next(reader)
            di = header.index("date")
            writer.writerow(header)
            for row in reader:
                if len(row) > di and row[di][:10] < d:
                    writer.writerow(row)
                    kept += 1
        hist[name] = kept
    print(f"INPUTS_473 {d} player_checks={n} total_inputs={'yes' if (dst / ti.name).exists() else 'NO'} history_rows={hist}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", required=True)
    ap.add_argument("--pristine", required=True)
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--asof", required=True)
    ap.add_argument("--bt-out", required=True)
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--n-sims", type=int, default=2)
    ap.add_argument("--live-processed", default="~/syndicate-prod/data/nba_source/data/processed",
                    help="READ-ONLY source of #473's inputs the pristine copy lacks (player_checks, total-inputs file)")
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--phase2-config", default=None,
                    help="calibration lane full-FIT config JSON (fit_f3_config.json): its env, engine module flags and data files "
                         "(nba_sim_total_inputs keys, availability/prop-calibration fleet copies, ALL walk-forward "
                         "calibration_totals files) are applied to every recorded date. The reader picks the latest file "
                         "dated <= D-1 and caches its index per processed root, so every file is copied up front.")
    ap.add_argument("--calfiles-dir", default=None, help="walk-forward calibration_totals_<date>.json directory (with --phase2-config)")
    ap.add_argument("--no-total-inputs", action="store_true",
                    help="leave nba_sim_total_inputs.json OUT of the scratch (skip_def_subtraction off) -- #695 A/B arm")
    args = ap.parse_args(argv)

    code, pristine, asof = Path(args.code), Path(args.pristine).expanduser(), Path(args.asof)
    scratch = Path(args.scratch).expanduser() / f"rec_w{args.worker}"
    out_root = Path(args.out_root)
    prod = Path("~/syndicate-prod/data").expanduser().resolve()
    if str(scratch.resolve()).startswith(str(prod)):
        raise SystemExit("REFUSED: scratch is inside the production data root")
    sys.path[:0] = [str(code / "scripts"), str(code)]  # vendored src entry removed (lane vendor-dead-paths-cleanup): vendor/ is empty
    os.environ.update({
        "SYNDICATE_DATA_ROOT": str(scratch), "SYNDICATE_NBA_SOURCE_ROOT": str(scratch / "nba_source"),
        "NBA_BETTING_DATA_ROOT": str(scratch / "nba_source" / "data"), "SYNDICATE_REFRESH_STATE_BACKEND": "file",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONUNBUFFERED": "1",
    })
    for k in [k for k in os.environ if any(m in k.upper() for m in ("KEYVALUE", "REDIS", "VALKEY", "ODDS_API", "ODDSAPI"))]:
        os.environ.pop(k, None)

    p2 = json.loads(Path(args.phase2_config).read_text(encoding="utf-8")) if args.phase2_config else None
    if p2:
        os.environ.update({k: str(v) for k, v in (p2.get("env") or {}).items()})
    import backtest_nba_lines_props as bt
    import resim_nba_availability as rs
    from syndicate.features.nba import live_resim as lr
    from syndicate.features.shared import basketball_props_smart_sim as bpss
    from syndicate.features.shared.basketball_props_predictions import export_props_predictions_local

    class BtArgs:
        out = Path(args.bt_out)

    # Same as the calibration harness: as-of runs use the PREGAME roster mode.
    bpss._resolve_smart_sim_roster_mode_local = lambda **_k: "pregame"
    if p2:
        eng = bpss._engine_for_league_local("nba")
        for name, val in (p2.get("engine_module_flags") or {}).items():
            if not hasattr(eng, name):
                raise SystemExit(f"PHASE2_FAIL engine flag {name} is not an attribute of the native engine object")
            setattr(eng, name, val)
        print(f"PHASE2_ENGINE_FLAGS {p2.get('engine_module_flags')}", flush=True)
    seen: Dict[Any, bool] = {}
    written = {"n": 0}
    orig = bpss._simulate_pbp_game_boxscore_local
    cur = {"date": ""}

    def recording(**kw):
        body = {k: v for k, v in kw.items() if k not in ("rng", "league_code")}
        key = tuple((k, id(v)) for k, v in sorted(body.items()))
        if key not in seen:
            seen[key] = True
            try:
                h = str(body["home_players"]["team"].iloc[0]).upper()
                a = str(body["away_players"]["team"].iloc[0]).upper()
                lr.persist_engine_inputs(cur["date"], h, a, body, root=out_root)
                written["n"] += 1
            except Exception as exc:  # noqa: BLE001
                print(f"PERSIST_FAIL {cur['date']} {type(exc).__name__}: {exc}"[:300], flush=True)
        return orig(**kw)

    bpss._simulate_pbp_game_boxscore_local = recording
    dates = [d for i, d in enumerate(rs._dates(f"{args.start}..{args.end}", asof)) if i % args.workers == args.worker]
    for d in dates:
        done_dir = lr.engine_inputs_dir(d, root=out_root)
        if done_dir.exists() and any(done_dir.glob("*.pkl")):
            continue
        existing = Path(args.bt_out) / "asof" / "props_odds_hist" / f"{d}.csv"
        props_csv = existing if existing.exists() and existing.stat().st_size > 1000 else bt.hist_props_csv(BtArgs, d)
        if props_csv is None:
            print(f"REC_SKIP {d} no props snapshot", flush=True)
            continue
        rs.prepare_scratch(pristine, scratch, d, asof, props_csv)
        _add_473_inputs(Path(args.live_processed).expanduser(), scratch / "nba_source" / "data" / "processed", d,
                        total_inputs=not args.no_total_inputs)
        if p2:
            proc = scratch / "nba_source" / "data" / "processed"
            files = p2.get("data_files_in_scratch_processed_root") or {}
            ti = files.get("nba_sim_total_inputs.json")
            if isinstance(ti, dict):
                (proc / "nba_sim_total_inputs.json").write_text(json.dumps(ti), encoding="utf-8")
            for name in ("nba_sim_availability.json", "nba_prop_calibration.json"):
                if name in files:
                    src = Path(args.live_processed).expanduser() / name
                    if not src.exists():
                        raise SystemExit(f"PHASE2_FAIL fleet copy missing: {src}")
                    shutil.copy2(src, proc / name)
            n_cal = 0
            for f in sorted(Path(args.calfiles_dir).glob("calibration_totals_*.json")):
                shutil.copy2(f, proc / f.name)
                n_cal += 1
            print(f"PHASE2_FILES {d} total_inputs={ti} calfiles={n_cal}", flush=True)
        cur["date"] = d
        seen.clear()
        before = written["n"]
        src_root = scratch / "nba_source"
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
