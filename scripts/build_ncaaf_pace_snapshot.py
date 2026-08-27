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


PERIOD_SECONDS = 15 * 60

# No real drive averages more than a minute of game clock per play. This is a
# PHYSICAL bound, applied after either source wins, so a data artifact cannot
# enter the aggregate through whichever field happened to be plausible.
MAX_SECONDS_PER_PLAY = 60.0


def _clock(value: object) -> int | None:
    """Game clock -> seconds remaining, or None when the clock is ABSENT.

    ABSENT MUST NOT READ AS 0:00. The first version returned 0 for an empty or
    partial dict, so a drive with a missing `endTime` derived
    `start - 0 = start` and inflated to as much as a full period -- fabricating
    precisely the outliers this derivation exists to remove. A missing value
    that lands on a legal-looking number is worse than a crash.
    """
    if not isinstance(value, dict):
        return None
    if value.get("minutes") is None and value.get("seconds") is None:
        return None
    try:
        return int(value.get("minutes") or 0) * 60 + int(value.get("seconds") or 0)
    except (TypeError, ValueError):
        return None


def _reported_seconds(drive: dict) -> int | None:
    elapsed = drive.get("elapsed")
    if not isinstance(elapsed, dict):
        return None
    try:
        return int(elapsed.get("minutes") or 0) * 60 + int(elapsed.get("seconds") or 0)
    except (TypeError, ValueError):
        return None


def _derived_seconds(drive: dict) -> int | None:
    """Elapsed reconstructed from the game clock. Within a period the clock
    counts DOWN, so elapsed = start - end, plus a full period per boundary."""
    start_period, end_period = drive.get("startPeriod"), drive.get("endPeriod")
    start, end = _clock(drive.get("startTime")), _clock(drive.get("endTime"))
    if start is None or end is None or start_period is None or end_period is None:
        return None
    try:
        sp, ep = int(start_period), int(end_period)
    except (TypeError, ValueError):
        return None
    # Period 0 appears in the data and is not a real period; college overtime
    # (5+) has no game clock at all, so a P4->P5 drive would derive `start+900`
    # and read as very slow rather than as a different clock regime.
    if not (1 <= sp <= 4) or not (1 <= ep <= 4) or ep < sp:
        return None
    seconds = start - end + (ep - sp) * PERIOD_SECONDS
    if seconds <= 0 or seconds > PERIOD_SECONDS:
        return None
    return seconds


def _drive_seconds(drive: dict) -> int | None:
    """Drive duration in seconds, or None when neither source is plausible.

    NEITHER FIELD IS TRUSTWORTHY ALONE, AND THEY FAIL IN OPPOSITE SEASONS.
    Measured on the cached drives (20,672 in 2024 / 20,666 in 2025):

      2024  reported `elapsed` is IMPOSSIBLE (>15 min) on 1.39% of drives, and
            internally contradicts the drive's own clock:
              start 8:10 -> end 6:27, period 1->1   true 1:43   reported 51:00
            Each bad row carries ~50x a real drive's weight, which put Texas
            State at 74,464 s of offence in a season (20.7 HOURS against a
            ~3,600s shared clock) and clamped 13.3% of the league.

      2025  reported is impossible on 0.00%, yet the two disagree on 16.5% --
            and there the DERIVED value is the wrong one:
              P1->1 start 15:00 end 0:00 plays=3  reported 86s  derived 900s
            `endTime` 0:00 is a MISSING-DATA SENTINEL, not a real clock, so
            deriving turns a 3-play drive into a 15-minute one.

    So: prefer `elapsed` while it is plausible, fall back to the clock only
    when it is not, and drop the drive when neither survives. A first version
    of this derived ALWAYS and would have replaced good 2025 data with
    fabricated slow drives -- the 2024 defect does not generalise.
    """
    reported = _reported_seconds(drive)
    derived = _derived_seconds(drive)
    plays = drive.get("plays")
    try:
        plays = int(plays) if plays is not None else None
    except (TypeError, ValueError):
        plays = None

    chosen = None
    if reported is not None and 0 < reported <= PERIOD_SECONDS:
        chosen = reported
    elif derived is not None:
        chosen = derived
    if chosen is None:
        return None

    # PHYSICAL GUARD, independent of which source won. No drive averages more
    # than a minute of clock per play; a value that does is a data artifact
    # whichever field produced it.
    if plays and chosen / plays > MAX_SECONDS_PER_PLAY:
        return None
    return chosen


def _load_cached_drives(cache_path: Path) -> list[dict]:
    """Read a `drives_<season>.json.gz` cache instead of the live endpoint.

    PREFERRED OVER THE API WHEREVER IT EXISTS. The live path is rate-limited --
    CFBD returned HTTP 429 to every request after a few full-season pulls,
    including the historical-truth loader's own `/games` call -- and a cache
    makes the snapshot reproducible instead of dependent on a quota. The
    `historical_truth` loader already maintains these files.
    """
    import gzip
    import json

    with gzip.open(cache_path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, list) else (payload.get("data") or [])


def build_pace_rows(
    client: CfbdClient | None,
    *,
    season: int,
    drives_cache: Path | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Aggregate `/drives` into per-team seconds-per-play. Returns (rows, report)."""
    agg: dict[str, list[int]] = {}
    drives_seen = 0
    drives_dropped = 0
    weeks_ok = 0
    weeks_failed: list[int] = []

    if drives_cache is not None:
        weeks = [(0, _load_cached_drives(drives_cache))]
        weeks_ok = 1
    else:
        weeks = []
    for week in ([] if drives_cache is not None else range(1, MAX_WEEK + 1)):
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
        weeks.append((week, payload or []))

    for _week, payload in weeks:
        for drive in payload or []:
            offense = drive.get("offense")
            plays = drive.get("plays")
            seconds = _drive_seconds(drive)
            if seconds is None:
                drives_dropped += 1
                continue
            if not offense or not plays or plays <= 0:
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
        "drives_dropped_bad_clock": drives_dropped,
        "drives_dropped_pct": (
            round(100.0 * drives_dropped / (drives_seen + drives_dropped), 2)
            if (drives_seen + drives_dropped) else None
        ),
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
    parser.add_argument("--drives-cache", type=Path, default=None,
                        help="Read drives from a `drives_<season>.json.gz` cache instead of the "
                             "live endpoint. Preferred: the API is rate-limited and a cache makes "
                             "the snapshot reproducible.")
    parser.add_argument("--base-url", type=str, default="https://api.collegefootballdata.com")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    client = None if args.drives_cache else CfbdClient.from_env(base_url=args.base_url, timeout=args.timeout)
    rows, report = build_pace_rows(client, season=args.season, drives_cache=args.drives_cache)

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
