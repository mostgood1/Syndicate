"""Build the MLB ARSENAL artifact from two Statcast leaderboards. `#440`.

Supersedes `build_mlb_pitch_splits_artifact.py`, which drove a 309-call
per-pitcher pipeline (~80 min) to produce two multipliers for 305 pitchers.
These two leaderboard calls produce MORE metrics for 551 pitchers AND 450
batters -- both sides of the matchup:

    statcast_pitcher_arsenal_stats(season)   1,673 rows / 551 pitchers
    statcast_batter_pitch_arsenal(season)    1,999 rows / 450 batters
    columns: pitch_type, pitch_usage, whiff_percent, k_percent,
             ba, slg, est_ba, est_slg, woba, pa
    join:    player_id IS mlbam_id (301 of our 305 pitch-split pitchers overlap)

FIELDS THIS FILLS (5, three of which I had written off):
    pitcher.pitch_type_whiff_mult   <- whiff_percent
    pitcher.pitch_type_inplay_mult  <- est_ba (contact quality allowed)
    pitcher.pitch_type_hr_mult      <- est_slg   ** declared "not fixable" **
    batter.vs_pitch_type            <- est_ba    ** declared "no source" **
    batter.vs_pitch_type_hr         <- est_slg   ** declared "no source" **

THE NORMALISATION IS THE LOAD-BEARING DECISION, and it is NOT against the league.

Each multiplier is normalised against **that player's own usage-weighted mean**,
so his multipliers average ~1.0 across his arsenal. Normalising against the
league would encode the pitcher's OVERALL quality into every pitch multiplier --
and `k_rate` / `hr_rate` already carry that level. The result would be
double-counting, which is precisely the calibration-absorption failure measured
on 2026-08-17 (two mechanisms, interaction -0.00331, negative in 4 of 4).

**Normalised this way the multipliers are LEVEL-NEUTRAL by construction**: they
say only "this pitch is better or worse than this player's average pitch", which
is the one thing the summary rates cannot express.

`est_ba`/`est_slg` are preferred over `ba`/`slg` -- expected stats strip
defence and park from the observed outcome, which is what we want for a
matchup term.

Usage:
  vendor\\mlb_bettingv2\\.venv_x64\\Scripts\\python.exe scripts/build_mlb_arsenal_artifact.py --season 2026
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REL = "mlb_source/source_artifacts/data/arsenal"

CLAMP_LO, CLAMP_HI = 0.65, 1.55   # matches the incumbent pitch-splits bounds
MIN_PA = 10                        # per pitch type; below this a rate is noise


def _root() -> Path:
    o = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(o).expanduser().resolve() if o else (REPO / "data")


def _num(row, col):
    try:
        v = float(row[col])
        return None if v != v else v
    except Exception:
        return None


def _build_side(df, label: str) -> dict:
    """player_id -> {pitch_type -> {whiff_mult, inplay_mult, hr_mult, usage, pa}}"""
    by_player = defaultdict(list)
    for _, r in df.iterrows():
        try:
            pid = int(r["player_id"])
        except Exception:
            continue
        pt = str(r.get("pitch_type") or "").strip().upper()
        if not pt or pid <= 0:
            continue
        pa = _num(r, "pa") or 0.0
        if pa < MIN_PA:
            continue
        by_player[pid].append({
            "pitch_type": pt,
            "usage": _num(r, "pitch_usage") or 0.0,
            "pa": pa,
            "whiff": _num(r, "whiff_percent"),
            # expected stats strip defence and park from the observation
            "inplay": _num(r, "est_ba") if _num(r, "est_ba") is not None else _num(r, "ba"),
            "power": _num(r, "est_slg") if _num(r, "est_slg") is not None else _num(r, "slg"),
        })

    out: dict[str, dict] = {}
    thin = 0
    for pid, rows in by_player.items():
        if len(rows) < 2:
            # one pitch type gives no RELATIVE information -- every multiplier
            # would be exactly 1.0 by construction. Publishing that is noise
            # dressed as data.
            thin += 1
            continue
        entry: dict[str, dict] = {}
        for metric, key in (("whiff", "whiff_mult"), ("inplay", "inplay_mult"),
                            ("power", "hr_mult")):
            vals = [(x["pitch_type"], x[metric], x["usage"]) for x in rows
                    if isinstance(x[metric], (int, float))]
            wsum = sum(u for _, _, u in vals)
            if not vals or wsum <= 0:
                continue
            # the player's OWN usage-weighted mean -- see the module docstring
            mean = sum(v * u for _, v, u in vals) / wsum
            if mean <= 0:
                continue
            for pt, v, _u in vals:
                m = max(CLAMP_LO, min(CLAMP_HI, v / mean))
                entry.setdefault(pt, {})[key] = round(m, 4)
        for x in rows:
            if x["pitch_type"] in entry:
                entry[x["pitch_type"]]["usage"] = round(x["usage"], 3)
                entry[x["pitch_type"]]["pa"] = int(x["pa"])
        if entry:
            out[str(pid)] = entry
    print(f"  {label}: {len(out)} players published, {thin} skipped (single pitch type)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    try:
        import pybaseball as pb
    except Exception as exc:
        print(f"pybaseball unavailable ({type(exc).__name__}). Use the x64 venv.")
        return 1

    print("fetching arsenal leaderboards (2 calls, not 309)")
    pdf = pb.statcast_pitcher_arsenal_stats(args.season)
    bdf = pb.statcast_batter_pitch_arsenal(args.season)
    print(f"  pitcher rows {len(pdf)}   batter rows {len(bdf)}")

    pitchers = _build_side(pdf, "pitchers")
    batters = _build_side(bdf, "batters")

    if not pitchers and not batters:
        print("REFUSED: both sides empty, not writing an artifact")
        return 1

    artifact = {
        "schema_version": 1,
        "season": args.season,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "statcast_pitcher_arsenal_stats + statcast_batter_pitch_arsenal",
        "normalisation": "per-player usage-weighted mean; multipliers are level-neutral",
        "clamp": [CLAMP_LO, CLAMP_HI],
        "min_pa_per_pitch_type": MIN_PA,
        "counts": {"pitchers": len(pitchers), "batters": len(batters)},
        "pitchers": pitchers,
        "batters": batters,
    }
    out = args.out or (_root() / REL / f"arsenal_{args.season}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"  pitchers {len(pitchers)}   batters {len(batters)}")
    if pitchers:
        pid, e = next(iter(pitchers.items()))
        print(f"  sample pitcher {pid}: {json.dumps(e)[:190]}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
