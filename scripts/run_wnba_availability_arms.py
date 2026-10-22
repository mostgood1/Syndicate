"""Held-out ENGINE re-run of one WNBA availability-rule arm (lane `wnba-availability-recency-tune`).

User decision 2026-10-14: run the engine re-run for K=1 vs two tuned rules before deciding. One process = one arm
(`--rule`, exported as `SYNDICATE_WNBA_SIM_AVAILABILITY_RULE`) x one worker's share of the dates. Every arm runs TODAY's
code with PRODUCTION's configuration, so the arms differ only by the rule:

  * the as-of scratch is the `wnba-lines-props-backtest` recipe (`backtest_wnba_lines_props.prepare_scratch`), with
    that lane's phase-1 outputs (game model, totals calibration, odds) READ from `--phase1-archive` -- never written;
  * production's four WNBA file switches and P2's rotation inputs as of D are copied in by the SAME helpers the P5
    recorder uses (`record_wnba_engine_inputs_asof.copy_switches` / `add_rotation_inputs`, imported);
  * `export_props_predictions_local` with production's arguments at `--n-sims` (500, as the original lane's re-run).

Per date it writes `<out-root>/<date>/` = the sim outputs (`smart_sim_*`, `props_predictions_*`, calibration files)
plus `phase_sim.json` (rule, switches, rotation rows, seconds, and the `SIM_AVAILABILITY applied ... rule=` line the
module printed -- the reachability evidence that this arm's rule actually ran). `fit_wnba_sim_availability.py
--archive <k arm> --compare <variant arm>` scores a pair.

Run in WSL with the fleet venv at nice 19, from a FROZEN code copy (a land rebases the worktree under a running job):
  PYTHONHASHSEED=0 nice -n 19 ~/.venvs/syndicate/bin/python scripts/run_wnba_availability_arms.py --code <frozen> \\
      --pristine ~/wnba_bt/pristine --phase1-archive ~/wnba_bt/archive --scratch ~/wnba_avail_tune/scratch \\
      --out-root ~/wnba_avail_tune/arm_k --rule k --start 2026-08-01 --end 2026-10-31 --worker 0 --workers 2
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import List, Optional

OUTPUT_PREFIXES = ("props_predictions_", "smart_sim_", "props_calibration_", "props_player_calibration_used_")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", required=True)
    ap.add_argument("--pristine", required=True)
    ap.add_argument("--phase1-archive", required=True)
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--rule", required=True, choices=("k", "regular_k2_min20", "exempt_apps3of5"))
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--n-sims", type=int, default=500)
    ap.add_argument("--live-processed", default="~/syndicate-prod/data/wnba_source/data/processed",
                    help="READ-ONLY source of production's WNBA switches and P2 rotation inputs")
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args(argv)

    code, pristine = Path(args.code), Path(args.pristine).expanduser()
    phase1, out_root = Path(args.phase1_archive).expanduser(), Path(args.out_root).expanduser()
    scratch = Path(args.scratch).expanduser() / f"{args.rule}_w{args.worker}"
    live_processed = Path(args.live_processed).expanduser()
    prod = Path("~/syndicate-prod/data").expanduser().resolve()
    for p in (scratch, out_root):
        if str(p.resolve()).startswith(str(prod)):
            raise SystemExit(f"REFUSED: {p} is inside the production data root")
    if out_root.resolve() == phase1.resolve():
        raise SystemExit("REFUSED: --out-root is the phase-1 archive (it is read-only here)")

    sys.path[:0] = [str(code / "scripts"), str(code)]
    import backtest_wnba_lines_props as bt  # noqa: E402
    import record_wnba_engine_inputs_asof as rec  # noqa: E402

    dates = sorted(p.name for p in phase1.iterdir()
                   if p.is_dir() and args.start <= p.name <= args.end and (p / "phase_game.json").exists()
                   and (p / f"predictions_{p.name}.csv").exists())
    dates = [d for i, d in enumerate(dates) if i % args.workers == args.worker]
    bt.prepare_scratch(pristine, scratch, dates[0] if dates else "2026-01-01", None, False)
    for k, v in bt._env_for(scratch, code).items():
        os.environ[k] = v
    for k in [k for k in os.environ if any(m in k.upper() for m in ("KEYVALUE", "REDIS", "VALKEY", "ODDS_API", "ODDSAPI"))]:
        os.environ.pop(k, None)
    os.environ["SYNDICATE_REFRESH_STATE_BACKEND"] = "file"
    os.environ["SYNDICATE_WNBA_SIM_AVAILABILITY_RULE"] = args.rule

    from syndicate.features.shared.basketball_props_predictions import export_props_predictions_local

    for d in dates:
        out = out_root / d
        if (out / "phase_sim.json").exists():
            continue
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        bt.prepare_scratch(pristine, scratch, d, phase1, restore_upto_incl=True)
        src_root = scratch / "wnba_source"
        processed = src_root / "data" / "processed"
        info = {"date": d, "rule": args.rule, "n_sims": args.n_sims,
                "switches": rec.copy_switches(live_processed, processed),
                "rotation": rec.add_rotation_inputs(live_processed, processed, d)}
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rows, _ = export_props_predictions_local(
                    source_root=src_root, date_str=d, out_path=processed / f"props_predictions_{d}.csv",
                    calib_window=7, calibrate_player=True, player_calib_window=30, player_min_pairs=6,
                    player_shrink_k=8, use_smart_sim=True, smart_sim_n_sims=args.n_sims, smart_sim_pbp=True,
                    smart_sim_workers=1, smart_sim_overwrite=True, log_file=out / "phase_sim.log")
            info["rows"] = rows
        except Exception as exc:  # noqa: BLE001
            info["error"] = repr(exc)[:500]
        printed = buf.getvalue()
        sys.stdout.write(printed)
        # The module prints into the sim's log file (smoke 2026-10-14: stdout carried nothing), so read both.
        log_path = out / "phase_sim.log"
        logged = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        info["availability_lines"] = re.findall(r"SIM_AVAILABILITY (?:applied|skipped|rule_fallback)[^\n]*",
                                                printed + logged)[:4]
        for p in processed.glob(f"*{d}*"):
            if p.is_file() and p.name.startswith(OUTPUT_PREFIXES):
                shutil.copy2(p, out / p.name)
        info["seconds"] = round(time.time() - t0, 1)
        (out / "phase_sim.json").write_text(json.dumps(info), encoding="utf-8")
        print("ARM", json.dumps({k: info[k] for k in ("date", "rule", "seconds") if k in info},
                                ensure_ascii=False), info["availability_lines"][:1], flush=True)
    print(f"ARM_DONE rule={args.rule} worker={args.worker} dates={len(dates)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
