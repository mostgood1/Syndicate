"""Build the NCAAF pace snapshot: per-team offensive seconds-per-play, from CFBD `/drives`.

WHY THIS EXISTS. `state.md` listed `pace` as one of three payload blocks that
were NULL AT SOURCE. The reality is worse than null, and it is the whole reason
this is worth building: with no `pace` block, `drive_priors._pace_index` falls
through to a hardcoded **24.0 s/play**, so

    pace_index = clamp((28.0 - 24.0) / 10.0, -1, 1) = +0.400

for EVERY NCAAF game, on every build. Measured against the engine directly
(`build_drive_priors`, 2026-08-27):

    no pace block (today)   pace_index +0.400   6.31 plays/drive   151.6 s/drive
    26.56 (league mean)     pace_index +0.144   6.76 plays/drive   179.5 s/drive

The average team is simulated ~18% faster than it plays. Faster drives fit more
drives into a game, which inflates possessions and totals -- and TOTALS are the
surface this engine is known to get wrong (`state.md`: margins calibrated,
totals not; 1.94x over-dispersed on the live slate). `drive_success_probability`
is IDENTICAL across the whole pace range (0.3270), so the effect is isolated to
play count and clock rather than smeared across scoring rates.

THE METRIC. Offensive seconds per play = sum(drive elapsed) / sum(drive plays)
over a team's offensive drives. `/drives` carries `offense`, `plays` and
`elapsed{minutes,seconds}` per drive, so this needs no second endpoint.

WHY RAW VALUES ARE SAFE TO FEED, and this was CHECKED rather than assumed --
`sp_offense_defense_rating`'s docstring is emphatic that centring is not
cosmetic, so the same question had to be asked here. Over 2025 (266 teams with
>= 200 plays, 37,263 drives): mean 26.56, sd 2.08, min 21.01, max 33.39.
Through the engine's own transform that is pace_index -0.539..+0.699 with
**0% of teams at a clamp bound**, so the engine's 28.0 pivot already spans the
real distribution. It does not need re-centring; it needs to stop being a
constant.

    py -3 scripts/build_ncaaf_pace_snapshot.py --season 2025
    py -3 scripts/build_ncaaf_pace_snapshot.py --season 2025 --output-path X.csv

Exit 0 = wrote a snapshot, 1 = wrote nothing usable.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

# The sibling `build_ncaaf_*_snapshot.py` scripts omit this and CANNOT be run
# directly -- `py -3 scripts/build_ncaaf_returning_production_snapshot.py`
# raises ModuleNotFoundError, because Python puts the SCRIPT's directory on
# sys.path, never the repo root. Following the pattern that works
# (`refit_ncaaf_smartsim2_payload.py`) rather than the one that is merely
# common here.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf.cfbd import CfbdClient
from syndicate.features.ncaaf.sources import pace_snapshot_path

# A team below this many offensive plays in a season is not a pace estimate, it
# is noise. The share excluded is reported as a RATE against teams seen, never
# as a bare count -- a count hides its own denominator.
MIN_PLAYS = 200

# Regular season only. Postseason drives are a different clock regime AND a
# biased subset of teams, so they are not mixed in silently.
SEASON_TYPE = "regular"
MAX_WEEK = 16


def _elapsed_seconds(elapsed: object) -> int:
    if not isinstance(elapsed, dict):
        return 0
    try:
        return int(elapsed.get("minutes") or 0) * 60 + int(elapsed.get("seconds") or 0)
    except (TypeError, ValueError):
        return 0


def build_pace_rows(client: CfbdClient, *, season: int) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Aggregate `/drives` into per-team seconds-per-play. Returns (rows, report)."""
    agg: dict[str, list[int]] = {}
    drives_seen = 0
    weeks_ok = 0
    weeks_failed: list[int] = []
    for week in range(1, MAX_WEEK + 1):
        try:
            payload = client._get_json(
                "/drives", params={"year": season, "week": week, "seasonType": SEASON_TYPE}
            )
        except Exception as exc:
            # A failed WEEK is silent data loss, so it is counted and printed
            # rather than swallowed. `weeks_failed` reaching the report is the
            # difference between "this team plays slowly" and "we missed
            # three of its games".
            weeks_failed.append(week)
            print(f"[ncaaf_pace] week={week} FETCH_FAILED {type(exc).__name__}: {exc}", flush=True)
            continue
        weeks_ok += 1
        for drive in payload or []:
            offense = drive.get("offense")
            plays = drive.get("plays")
            seconds = _elapsed_seconds(drive.get("elapsed"))
            if not offense or not plays or plays <= 0 or seconds <= 0:
                continue
            bucket = agg.setdefault(str(offense), [0, 0, 0])
            bucket[0] += seconds
            bucket[1] += int(plays)
            bucket[2] += 1
            drives_seen += 1

    rows: list[dict[str, object]] = []
    for team, (seconds, plays, drives) in sorted(agg.items()):
        if plays < MIN_PLAYS:
            continue
        rows.append(
            {
                "team": team,
                "season": season,
                "offensive_plays": plays,
                "offensive_drives": drives,
                "offensive_seconds": seconds,
                "seconds_per_play": round(seconds / plays, 4),
                "plays_per_drive": round(plays / drives, 4),
            }
        )

    values = [float(r["seconds_per_play"]) for r in rows]
    report: dict[str, object] = {
        "season": season,
        "weeks_fetched": weeks_ok,
        "weeks_failed": weeks_failed,
        "drives_aggregated": drives_seen,
        "teams_seen": len(agg),
        "teams_kept": len(rows),
        "teams_below_min_plays_pct": (
            round(100.0 * (len(agg) - len(rows)) / len(agg), 1) if agg else None
        ),
        "seconds_per_play_mean": round(statistics.mean(values), 3) if values else None,
        "seconds_per_play_sd": round(statistics.pstdev(values), 3) if values else None,
        "seconds_per_play_min": round(min(values), 3) if values else None,
        "seconds_per_play_max": round(max(values), 3) if values else None,
    }
    if values:
        idx = [max(-1.0, min(1.0, (28.0 - v) / 10.0)) for v in values]
        # If this is ever non-zero the engine's 28.0 pivot no longer spans the
        # real distribution, and feeding raw values would silently flatten the
        # tail teams onto one number. Reported EVERY run, not checked once.
        report["pace_index_at_clamp_pct"] = round(
            100.0 * sum(1 for i in idx if abs(i) >= 0.999) / len(idx), 1
        )
        report["pace_index_min"] = round(min(idx), 3)
        report["pace_index_max"] = round(max(idx), 3)
    return rows, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the NCAAF pace snapshot from CFBD /drives.")
    parser.add_argument("--season", type=int, required=True, help="Season year to aggregate.")
    parser.add_argument("--output-path", type=Path, default=None, help="Optional pace CSV output path.")
    parser.add_argument("--base-url", type=str, default="https://api.collegefootballdata.com")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    client = CfbdClient.from_env(base_url=args.base_url, timeout=args.timeout)
    rows, report = build_pace_rows(client, season=args.season)

    for key, value in report.items():
        print(f"  {key:<28} {value}")

    if not rows:
        print("[ncaaf_pace] NO ROWS -- wrote nothing.", flush=True)
        return 1

    out = args.output_path or pace_snapshot_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[ncaaf_pace] wrote {len(rows)} rows -> {out}", flush=True)

    # PUBLISHING IS NOT OPTIONAL. A local checkout cannot reach Render, so an
    # input that is written but not published is inert in production no matter
    # how correct it is here.
    try:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        published = bool(publish_hot_artifact(out))
    except Exception as exc:
        published = False
        print(f"[ncaaf_pace] PUBLISH_FAILED {type(exc).__name__}: {exc}", flush=True)
    print(f"[ncaaf_pace] published={published}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
