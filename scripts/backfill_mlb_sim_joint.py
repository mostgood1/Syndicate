"""Backfill the sim JOINT for the 13 dates that have BOTH graded outcomes and rosters.

WHY A BACKFILL AT ALL. The joint producer deployed 2026-09-04T23:26Z and writes
prospectively, so exactly one date carries a joint. Graded prop outcomes, in
turn, only start 2026-06-29. The intersection of "has a joint" and "has
outcomes" is therefore ONE date, 6 game-clusters -- too few for the bootstrap
that has to carry the result.

Re-running the sim on historical rosters manufactures the missing side. Both
inputs are GIT-TRACKED and local:
  * roster_objs      689 files, 2026-06-15..07-12  (27 dates)
  * daily_top_props  graded from 2026-06-29        (June before that is 0% graded)
Intersection: 13 consecutive dates, 2026-06-29..07-11, ~8,096 graded legs.

No `/api/ops/artifacts/export`, no StatsAPI. That matters twice over: the export
endpoint reads artifacts WHOLE into a 2 GB web process with a known retention
problem (it returned 502 on me once already tonight), and `build_mlb_actuals`
is unreplayable past 2026-06-25 anyway.

RESUMABLE BY DESIGN, and that is not decoration -- two agents and two sessions
died mid-task tonight. Each game writes its own small file and is skipped if
present, so a kill costs one game, not the run.

STORES THE JOINT, NOT THE SIM. A full artifact is ~375 KB; the joint plus the
marginals the measurement needs is a fraction of that, and nothing downstream
wants the rest.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import traceback

REPO = pathlib.Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor" / "mlb_bettingv2"
for extra in (str(VENDOR), str(VENDOR / "tools"), str(REPO)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

OUT = pathlib.Path(os.environ.get("SYNDICATE_JOINT_BACKFILL")
                   or (REPO / "reports" / "joint_backfill"))
SNAP = REPO / "data" / "mlb_source" / "source_artifacts" / "data" / "daily" / "snapshots"
DATES = [
    "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03",
    "2026-07-04", "2026-07-05", "2026-07-06", "2026-07-07", "2026-07-08",
    "2026-07-09", "2026-07-10", "2026-07-11",
]
SIMS = int(os.environ.get("BACKFILL_SIMS", "1000"))
WORKERS = int(os.environ.get("BACKFILL_WORKERS", "1"))
SEED = 4242


def main() -> int:
    from sim_engine.data.roster_artifact import roster_from_dict
    from daily_update import _sim_many

    OUT.mkdir(parents=True, exist_ok=True)
    done = failed = skipped = 0
    t0 = time.time()
    for date in DATES:
        rdir = SNAP / date / "roster_objs"
        if not rdir.is_dir():
            print(f"{date}: NO roster_objs dir", flush=True)
            continue
        files = sorted(rdir.glob("roster_obj_*.json"))
        ddir = OUT / date
        ddir.mkdir(parents=True, exist_ok=True)
        for f in files:
            dest = ddir / (f.stem.replace("roster_obj_", "joint_") + ".json")
            if dest.exists() and dest.stat().st_size > 200:
                skipped += 1
                continue
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
                away = roster_from_dict(doc["away"])
                home = roster_from_dict(doc["home"])
                out = _sim_many(
                    away_roster=away, home_roster=home,
                    sims=SIMS, seed=SEED, workers=WORKERS,
                    hitter_props_top_n=24,
                )
                joint = out.get("joint")
                if not joint:
                    print(f"  {date} {f.name}: NO JOINT EMITTED", flush=True)
                    failed += 1
                    continue
                # Only what the measurement reads: the joint, and the marginals
                # it holds fixed across arms.
                props = {}
                for pid, prof in (out.get("hitter_props") or {}).items():
                    if not isinstance(prof, dict):
                        continue
                    props[str(pid)] = {
                        "name": prof.get("name"), "team": prof.get("team"),
                        "is_lineup_batter": prof.get("is_lineup_batter"),
                        "pa_mean": prof.get("pa_mean"),
                        "hits_dist": prof.get("hits_dist"),
                        "home_runs_dist": prof.get("home_runs_dist"),
                        "total_bases_dist": prof.get("total_bases_dist"),
                        "rbi_dist": prof.get("rbi_dist"),
                    }
                dest.write_text(json.dumps(
                    {"date": date, "source": f.name, "sims": SIMS,
                     "joint": joint, "hitter_props": props}), encoding="utf-8")
                done += 1
                print("  %s %-46s %6.1f KB  (%.0fs elapsed)" % (
                    date, dest.name, dest.stat().st_size / 1024, time.time() - t0), flush=True)
            except Exception:
                failed += 1
                print(f"  {date} {f.name}: FAILED\n{traceback.format_exc()[-600:]}", flush=True)
        print("%s done. cumulative: %d written, %d skipped, %d failed, %.0fs"
              % (date, done, skipped, failed, time.time() - t0), flush=True)
    print("\nBACKFILL COMPLETE: %d written, %d skipped, %d failed in %.0fs"
          % (done, skipped, failed, time.time() - t0), flush=True)
    return 0 if done or skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
