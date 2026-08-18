"""SIM ENGINE INPUT CHECKLIST — is every input the sim reads actually fed?

`#440`. This exists because FOUR separate features were found in one session that
were fully built, tested, consumed by the simulation, and **populated with
nothing** — each behaving as a silent no-op:

  * pitch-type effectiveness (`pitch_type_whiff_mult`) -> every pitch identical
  * batted-ball types (`bb_gb_rate`) -> every hitter identical
  * `statcast_quality_mult`, `vs_pitch_type`, and more

None raised an error. None failed a test. The sim ran, produced numbers, and
those numbers were identical to a build where the feature did not exist.

THE TWO RULES THIS ENCODES, both learned the hard way:

  1. **Never reason about a model's presence from a NAME SEARCH.** A grep for
     `ground_ball|fly_ball|launch_angle` produced the published claim "no
     batted-ball model". The fields are prefixed `bb_`. Enumerate
     `dataclasses.fields()` instead — vocabulary is not evidence.
  2. **A `.get(key, NEUTRAL)` default makes an unfed field invisible.** A
     multiplier defaulting to 1.0 is indistinguishable from a working feature at
     every level except the data.

So this cross-references TWO things per field:

    is it CONSUMED by the simulation?   (search the engine source for the name)
    is it POPULATED in real rosters?    (measure against artifacts)

**CONSUMED + UNPOPULATED is the alarm.** That combination is a feature which
cannot work, and it is invisible to every other check in this repo.

Exits 1 when any consumed field is unpopulated, so it can gate.

Usage:
  py -3 scripts/sim_input_checklist.py
  py -3 scripts/sim_input_checklist.py --games 60 --json reports/phase7/input_checklist.json
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import Counter
from dataclasses import fields
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor" / "mlb_bettingv2"
for _p in (str(REPO), str(VENDOR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ENGINE = VENDOR / "sim_engine"
SNAPSHOTS = REPO / "data/mlb_source/source_artifacts/data/daily_pitcher_props/snapshots"

# Fields that are legitimately sparse. Documented so a low number here is not
# mistaken for a defect -- anything NOT listed, and consumed, must be populated.
EXPECTED_SPARSE = {
    "availability_mult": "set only for pitchers with a known workload flag",
    "leverage_skill": "relievers with enough high-leverage sample",
    "sb_attempt_rate": "many hitters genuinely never attempt a steal",
    "sb_success_rate": "same population as sb_attempt_rate",
    "batted_ball_source": "provenance stamp, only when the blend is enabled",
    "batted_ball_bbe": "same",
    "batted_ball_weight": "same",
    # BVP is SPARSE BY NATURE, not by defect. A batter only has history against
    # starters he has actually faced, so ~14% coverage is the correct answer and
    # 100% would be impossible. Measured 13.9% after the 2026-08-18 cache fix.
    # Listing these matters: a checklist that flags correct behaviour as FAILURE
    # gets ignored, and then it misses the real ones.
    "vs_pitcher_hr_mult": "batter has history only vs starters actually faced",
    "vs_pitcher_k_mult": "same",
    "vs_pitcher_bb_mult": "same",
    "vs_pitcher_inplay_mult": "same",
    "vs_pitcher_history": "same",
}
SPARSE_FLOOR = 0.20
POPULATED_FLOOR = 0.50


def engine_source() -> str:
    parts = []
    for path in ENGINE.rglob("*.py"):
        try:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
    return "\n".join(parts)


def consumed(name: str, src: str) -> bool:
    """Does the engine READ this field anywhere?

    Matches attribute access (`.name`) and string reference (getattr / dict key).
    Deliberately broad: a false 'consumed' costs one harmless row, a false
    'unconsumed' hides the exact defect this script exists to find.
    """
    esc = re.escape(name)
    return bool(re.search(r"\." + esc + r"\b", src) or re.search(r"['\"]" + esc + r"['\"]", src))


def populated(value, default) -> bool:
    if value is None:
        return False
    if isinstance(value, (dict, list, tuple, set)):
        return len(value) > 0
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, bool):
        return value != default
    if isinstance(value, (int, float)):
        return value != default
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--warn-only", action="store_true",
                    help="report without failing, for exploratory runs")
    ap.add_argument("--simulate-rebuild", action="store_true",
                    help="apply the BUILD-TIME appliers before auditing. Without this the "
                         "checklist can only see what was SERIALISED -- i.e. history. Archived "
                         "rosters were written before any current wiring existed, so a plain run "
                         "reports the pre-wiring state forever and cannot validate a fix.")
    ap.add_argument("--publish", action="store_true",
                    help="write the report into the artifact tree so PRODUCTION can be audited. Roster objects are not allowlisted (hundreds of large files per date); the worker runs this and publishes the bounded result instead -- the book_grid pattern.")
    args = ap.parse_args()

    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.models import BatterProfile, PitcherProfile

    paths = sorted(glob.glob(str(SNAPSHOTS / "*/roster_objs/roster_obj_*.json")))[:args.games]
    if not paths:
        print(f"REFUSED: no roster artifacts under {SNAPSHOTS}")
        return 1

    src = engine_source()
    hits = {"batter": Counter(), "pitcher": Counter()}
    n = {"batter": 0, "pitcher": 0}
    bdef = {f.name: f.default for f in fields(BatterProfile)}
    pdef = {f.name: f.default for f in fields(PitcherProfile)}

    if args.simulate_rebuild:
        # Everything the real build applies, in the same order. BVP is applied by
        # `daily_update.py:7564` -- NOT by build_roster -- which is why it needs
        # its own call here; see the provenance table in
        # docs/ai_context/mlb_sim_engine_reference.md.
        from datetime import date as _date
        from sim_engine.data.batted_ball import (apply_batted_ball_to_batter,
                                                 apply_batted_ball_to_pitcher)
        from sim_engine.data.build_roster import _apply_cached_statcast_pitch_splits
        from sim_engine.data.statcast_bvp import (apply_starter_bvp_hr_multipliers,
                                                  default_bvp_cache)
        from sim_engine.data.statcast_pitch_splits import default_statcast_cache
        _sc, _bc = default_statcast_cache(), default_bvp_cache()

    for path in paths:
        try:
            roster = read_game_roster_artifact(Path(path))
        except Exception:
            continue
        if args.simulate_rebuild:
            for _bat, _pit in (("away", "home"), ("home", "away")):
                try:
                    apply_starter_bvp_hr_multipliers(
                        batting_roster=roster[_bat],
                        pitcher_id=int(roster[_pit].lineup.pitcher.player.mlbam_id),
                        season=2026, start_date=_date(2026, 3, 1),
                        end_date=_date(2026, 7, 30), cache=_bc)
                except Exception:
                    pass
            for _side in ("away", "home"):
                _lu = roster[_side].lineup
                for _b in list(_lu.batters) + list(_lu.bench or []):
                    try:
                        apply_batted_ball_to_batter(_b, season=2026, weight=0.35)
                    except Exception:
                        pass
                for _p in [_lu.pitcher] + list(_lu.bullpen or []):
                    try:
                        _apply_cached_statcast_pitch_splits(
                            _p, season=2026, statcast_cache=_sc, statcast_ttl_seconds=None)
                        apply_batted_ball_to_pitcher(_p, season=2026)
                    except Exception:
                        pass
        for side in ("away", "home"):
            lineup = roster[side].lineup
            for b in list(lineup.batters) + list(lineup.bench or []):
                n["batter"] += 1
                for f in fields(BatterProfile):
                    if f.name != "player" and populated(getattr(b, f.name, None), bdef.get(f.name)):
                        hits["batter"][f.name] += 1
            for p in [lineup.pitcher] + list(lineup.bullpen or []):
                n["pitcher"] += 1
                for f in fields(PitcherProfile):
                    if f.name != "player" and populated(getattr(p, f.name, None), pdef.get(f.name)):
                        hits["pitcher"][f.name] += 1

    print("=" * 88)
    print("SIM ENGINE INPUT CHECKLIST")
    print("=" * 88)
    print(f"\n  rosters {len(paths)}   batters {n['batter']}   pitchers {n['pitcher']}")
    print("  a field FAILS when the engine READS it and nothing FEEDS it\n")

    failures, warnings, rows = [], [], []
    for kind, model in (("batter", BatterProfile), ("pitcher", PitcherProfile)):
        print(f"\n--- {kind.upper()} " + "-" * (70 - len(kind)))
        entries = []
        for f in fields(model):
            if f.name == "player":
                continue
            pct = hits[kind].get(f.name, 0) / max(1, n[kind])
            entries.append((pct, f.name, consumed(f.name, src)))
        for pct, name, is_consumed in sorted(entries):
            sparse = name in EXPECTED_SPARSE
            bucket = None
            if is_consumed and pct == 0.0:
                # zero is a failure even for an expected-sparse field: "sometimes
                # absent" and "never present" are different claims.
                status, bucket = "FAIL  consumed but NEVER populated", failures
            elif is_consumed and pct < SPARSE_FLOOR and not sparse:
                status, bucket = "FAIL  consumed, almost never populated", failures
            elif is_consumed and pct < POPULATED_FLOOR and not sparse:
                status, bucket = "warn  consumed, thinly populated", warnings
            elif not is_consumed and pct == 0.0:
                status = "note  unread and unfed (dead field)"
            else:
                status = "ok"
            if bucket is not None:
                bucket.append((kind, name, pct))
            rows.append({"kind": kind, "field": name, "pct": round(pct, 4),
                         "consumed": is_consumed, "status": status.split()[0]})
            if status != "ok":
                mark = "*" if sparse else " "
                print(f"  {pct:6.1%} {mark} {name:32s} {status}")

    print("\n" + "=" * 88)
    if failures:
        print(f"FAILURES: {len(failures)} field(s) the engine READS and nothing FEEDS\n")
        for kind, name, pct in failures:
            print(f"    {kind:8s} {name:32s} {pct:.1%}")
        print("\n  Each is a silent no-op: the sim runs, produces numbers, and those")
        print("  numbers are identical to a build where the feature does not exist.")
    else:
        print("PASS: every field the engine reads is populated above its floor.")
    if warnings:
        print(f"\n  {len(warnings)} thin field(s) — not failing, worth a look:")
        for kind, name, pct in warnings:
            print(f"    {kind:8s} {name:32s} {pct:.1%}")
    print("  (* = documented as expected-sparse in EXPECTED_SPARSE)")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"rosters": len(paths), "counts": n, "failures": len(failures),
             "warnings": len(warnings), "rows": rows}, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    if args.publish:
        import os
        from datetime import datetime, timezone
        root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
        base = Path(root).expanduser().resolve() if root else (REPO / "data")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out = (base / "mlb_source/source_artifacts/data/sim_input_report"
               / f"sim_input_report_{stamp}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "host": "worker" if root else "local",
            "rosters": len(paths), "counts": n,
            "failures": [{"kind": k, "field": f, "pct": round(v, 4)} for k, f, v in failures],
            "warnings": [{"kind": k, "field": f, "pct": round(v, 4)} for k, f, v in warnings],
            "rows": rows,
        }, indent=2), encoding="utf-8")
        print("")
        print(f"published {out}")
        print("  This is the ONLY way the production population is readable: the")
        print("  artifacts endpoint gates on HOT_ARTIFACT_PATTERNS and roster_objs")
        print("  is deliberately not on it.")

    return 1 if (failures and not args.warn_only) else 0


if __name__ == "__main__":
    raise SystemExit(main())
