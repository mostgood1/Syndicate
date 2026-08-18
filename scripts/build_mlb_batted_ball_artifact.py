"""Publish per-batter BATTED-BALL quality as an artifact. `#440`.

Measured 2026-08-17, leak-free (all predictors from the first half only, n=218):

    predictor              vs future HR/PA   vs future TB/AB
    hr_rate (sim's input)        0.312             0.126
    barrel%                      0.387             0.178
    hard-hit% (EV>=95)           0.363             0.235

**Barrel% out-predicts the sim's own `hr_rate` on home runs, and hard-hit%
out-predicts it on total bases by ~1.9x.** That is the predictive gate
pitch-type splits were never subjected to, and batted-ball data cleared it.

THIS IS AN ESTIMATOR SOURCE, NOT A MECHANISM — and the distinction is
load-bearing. The 2x2 factorial showed that adding MECHANISMS (substitution,
pitch splits) to a calibrated engine produces a NEGATIVE interaction, because
the fitted rates already absorb their average effect. Batted-ball data does not
add a mechanism: it estimates `hr_rate` / `inplay_hit_rate` BETTER. Blending a
better estimator of an existing parameter does not double-count anything, so it
is not expected to interfere the way the mechanisms did — **and the factorial is
how that expectation gets checked rather than assumed.**

Same shape as `build_mlb_pitch_splits_artifact.py`: one document keyed by player
id, on the mounted disk via `SYNDICATE_DATA_ROOT`, publishable and inspectable —
NOT a hash-keyed cache.

Usage:
  py -3 scripts/build_mlb_batted_ball_artifact.py --season 2026
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REL_OUT = "mlb_source/source_artifacts/data/batted_ball"


def _data_root() -> Path:
    override = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(override).expanduser().resolve() if override else (REPO_ROOT / "data")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--min-bbe", type=int, default=50,
                    help="batted-ball events floor; below this a rate is noise")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    try:
        import pybaseball as pb
    except Exception as exc:
        print(f"pybaseball unavailable ({type(exc).__name__}). Run under the x64 venv:")
        print(r"  vendor\mlb_bettingv2\.venv_x64\Scripts\python.exe " + __file__)
        return 1

    df = pb.statcast_batter_exitvelo_barrels(args.season, minBBE=args.min_bbe)
    print(f"leaderboard rows at minBBE={args.min_bbe}: {len(df)}")

    players: dict[str, dict] = {}
    skipped = 0
    for _, r in df.iterrows():
        try:
            pid = int(r["player_id"])
            attempts = int(r["attempts"])
        except Exception:
            skipped += 1
            continue
        if pid <= 0 or attempts < args.min_bbe:
            skipped += 1
            continue

        def f(col):
            try:
                v = float(r[col])
                return None if v != v else v      # drop NaN
            except Exception:
                return None

        entry = {
            "bbe": attempts,
            "barrel_pct": f("brl_percent"),
            "hard_hit_pct": f("ev95percent"),
            "avg_exit_velo": f("avg_hit_speed"),
            "avg_launch_angle": f("avg_hit_angle"),
            "sweet_spot_pct": f("anglesweetspotpercent"),
            "avg_distance": f("avg_distance"),
            # THE GB/FB SPLIT the research doc wrongly listed as unavailable --
            # it ships in this same one-call leaderboard.
            "gb": f("gb"),
            "fbld": f("fbld"),
        }
        if entry["barrel_pct"] is None and entry["hard_hit_pct"] is None:
            skipped += 1
            continue
        players[str(pid)] = entry

    if not players:
        print(f"REFUSED: {len(df)} leaderboard rows produced ZERO usable players "
              f"(skipped {skipped}). Not writing an empty artifact.")
        return 1

    # ground-ball share, where both halves are present -- this is what lets a
    # park's HR factor apply differently to a fly-ball hitter than a worm-burner
    with_gb = 0
    for e in players.values():
        gb, fbld = e.get("gb"), e.get("fbld")
        if gb is not None and fbld is not None and (gb + fbld) > 0:
            e["gb_share"] = round(gb / (gb + fbld), 4)
            with_gb += 1

    artifact = {
        "schema_version": 1,
        "season": args.season,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "statcast batter exit-velo/barrels leaderboard (pybaseball)",
        "min_bbe": args.min_bbe,
        "counts": {"players": len(players), "leaderboard_rows": len(df),
                   "skipped": skipped, "with_gb_share": with_gb},
        "players": players,
    }

    out = args.out or (_data_root() / REL_OUT / f"batted_ball_{args.season}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    print("=" * 80)
    print("MLB BATTED-BALL ARTIFACT")
    print("=" * 80)
    print(f"\n  players published   {len(players)}")
    print(f"  with gb_share       {with_gb}")
    print(f"  skipped             {skipped}")
    sample = next(iter(players.items()))
    print(f"\n  sample {sample[0]}: {json.dumps(sample[1])[:170]}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
