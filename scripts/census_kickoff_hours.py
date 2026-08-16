"""Kickoff-hour census: when does each sport/league actually start, in local time?

Phase 0/H1 of `.syndicate/plan_2026-08-16_sim_scheduling.md`. The plan's Phase 1
replaces elapsed-time refresh cadence with fixture-relative cadence, and the
band table it implies must come from measurement rather than belief. This script
produces that table.

WHAT IT DELIBERATELY DOES NOT DO. It does not read `commence_time` off odds
snapshots. Those exist only for dates the mirror happens to hold (measured: 3
MLB snapshot dates locally), which is the exact "analysis silently collapses to
the intersection" trap CLAUDE.md documents. It reads SCHEDULE artifacts, which
carry the whole season, and it prints the coverage it actually got so a thin
result cannot be mistaken for a broad one.

Sources, and their honesty:
  * soccer  -- data/soccer_source/<league>/api/schedule/schedule_2026.json (ESPN).
              Full season. Carries its own `generated_at`, which is REPORTED --
              a schedule mirrored weeks ago is fine for an hour histogram
              (kickoff times are structural) but the vintage must be visible.
  * wnba    -- vendor/wnba_betting_repo/data/processed/schedule_2026.json
  * nfl     -- data/nfl_source/schedule_2026.csv + schedule_preseason_2026.csv
  * mlb     -- statsapi.mlb.com live, NOT the local mirror. Authoritative and
              free; the mirror is too sparse to histogram.
  * nba/nhl/ncaab/ncaaf -- REPORTED AS GAPS, not silently omitted. Their 2026-27
              schedules are not in the checkout. An absent sport must be
              distinguishable from a sport with no games.

Usage:
    py -3 scripts/census_kickoff_hours.py
    py -3 scripts/census_kickoff_hours.py --back 30 --ahead 14 --tz America/Chicago
    py -3 scripts/census_kickoff_hours.py --json reports/kickoff_census.json
"""
from __future__ import annotations

import argparse
import csv
import json
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]

SOCCER_LEAGUES = (
    "epl", "la_liga", "bundesliga", "serie_a", "ligue_1",
    "mls", "championship", "eredivisie", "primeira_liga", "belgian_pro_league",
)

# The band Phase 1 is trying to protect: the US evening, when MLB/NBA/NHL/NFL
# run live and refresh-worker peaks. Half-open [start, end) in local hours,
# wrapping midnight.
US_EVENING_START = 18
US_EVENING_END = 1


def _parse_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        stamp = None
        for fmt in ("%Y-%m-%dT%H:%M%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                stamp = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if stamp is None:
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _in_evening(hour: int) -> bool:
    if US_EVENING_START <= US_EVENING_END:
        return US_EVENING_START <= hour < US_EVENING_END
    return hour >= US_EVENING_START or hour < US_EVENING_END


class Series:
    """One sport or league's kickoffs, plus the provenance of where they came from."""

    def __init__(self, key: str, source: str, vintage: str | None = None):
        self.key = key
        self.source = source
        self.vintage = vintage
        self.kickoffs: list[datetime] = []   # local tz
        self.error: str | None = None

    def add(self, stamp_utc: datetime, tz: ZoneInfo) -> None:
        self.kickoffs.append(stamp_utc.astimezone(tz))

    def summary(self) -> dict:
        hours = Counter(k.hour for k in self.kickoffs)
        n = len(self.kickoffs)
        evening = sum(c for h, c in hours.items() if _in_evening(h))
        ordered = sorted(k.hour for k in self.kickoffs)
        return {
            "key": self.key,
            "source": self.source,
            "vintage": self.vintage,
            "error": self.error,
            "n": n,
            "date_span": (
                f"{min(self.kickoffs).date()}..{max(self.kickoffs).date()}" if self.kickoffs else None
            ),
            "median_local_hour": (ordered[n // 2] if n else None),
            "hour_histogram": {str(h): hours.get(h, 0) for h in range(24)},
            "pct_in_us_evening": (round(100.0 * evening / n, 1) if n else None),
        }


def _load_soccer(tz: ZoneInfo, lo: date, hi: date) -> list[Series]:
    out: list[Series] = []
    for league in SOCCER_LEAGUES:
        path = REPO_ROOT / "data" / "soccer_source" / league / "api" / "schedule" / "schedule_2026.json"
        series = Series(f"soccer:{league}", str(path.relative_to(REPO_ROOT)))
        if not path.is_file():
            series.error = "schedule artifact absent"
            out.append(series)
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            series.error = f"unreadable: {type(exc).__name__}"
            out.append(series)
            continue
        series.vintage = str(payload.get("generated_at") or "")[:19] or None
        for row in payload.get("matches") or []:
            stamp = _parse_utc(row.get("date"))
            if stamp is None:
                continue
            if lo <= stamp.astimezone(tz).date() <= hi:
                series.add(stamp, tz)
        out.append(series)
    return out


def _load_wnba(tz: ZoneInfo, lo: date, hi: date) -> Series:
    path = REPO_ROOT / "vendor" / "wnba_betting_repo" / "data" / "processed" / "schedule_2026.json"
    series = Series("wnba", str(path.relative_to(REPO_ROOT)))
    if not path.is_file():
        series.error = "schedule artifact absent"
        return series
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else (payload.get("games") or [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp = _parse_utc(row.get("datetime_utc") or row.get("date_utc"))
        if stamp is None:
            continue
        if lo <= stamp.astimezone(tz).date() <= hi:
            series.add(stamp, tz)
    return series


def _load_nfl(tz: ZoneInfo, lo: date, hi: date) -> list[Series]:
    out: list[Series] = []
    for label, name in (("nfl", "schedule_2026.csv"), ("nfl_preseason", "schedule_preseason_2026.csv")):
        path = REPO_ROOT / "data" / "nfl_source" / name
        series = Series(label, str(path.relative_to(REPO_ROOT)))
        if not path.is_file():
            series.error = "schedule artifact absent"
            out.append(series)
            continue
        parsed_any = False
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    raw = (
                        row.get("gameday_utc") or row.get("datetime_utc") or row.get("start_time")
                        or row.get("gametime_utc") or row.get("commence_time") or row.get("kickoff")
                    )
                    stamp = _parse_utc(raw or "")
                    if stamp is None:
                        # nflverse shape: `gameday` (YYYY-MM-DD) and `gametime`
                        # (HH:MM) as SEPARATE columns.
                        #
                        # `gametime` IS UTC IN THIS FILE, and I assumed Eastern
                        # first. VERIFIED against two known fixtures rather than
                        # assumed: 2026-08-07 `00:00` is the Hall of Fame Game
                        # (20:00 ET Thu = 00:00 UTC Fri), and DET@CIN 2026-08-13
                        # `23:00` = 18:00 CT, the standard preseason slot. Reading
                        # it as Eastern shifted every kickoff +5h and produced a
                        # median of 22:00 CT, which is what exposed the error --
                        # a band nobody plays in.
                        day = str(row.get("gameday") or "").strip()
                        clock = str(row.get("gametime") or "").strip()
                        if day and clock:
                            try:
                                naive = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M")
                                stamp = naive.replace(tzinfo=timezone.utc)
                            except ValueError:
                                stamp = None
                    if stamp is None:
                        continue
                    parsed_any = True
                    if lo <= stamp.astimezone(tz).date() <= hi:
                        series.add(stamp, tz)
            if not series.kickoffs and not series.error:
                # THREE outcomes here, and they must not share a spelling:
                # a schema miss (nothing parsed at all), an empty window (rows
                # parsed but none fall inside it), and a genuinely empty file.
                # Collapsing the middle one onto "no UTC kickoff column" is what
                # made the regular-season NFL row read as a parser failure when
                # its season simply starts after the window ends.
                if not parsed_any:
                    with path.open(encoding="utf-8", newline="") as handle:
                        cols = (csv.DictReader(handle).fieldnames or [])
                    series.error = f"no parseable kickoff column; columns={cols[:12]}"
                else:
                    series.error = f"parsed OK, but no fixtures inside {lo}..{hi}"
        except Exception as exc:
            series.error = f"unreadable: {type(exc).__name__}: {exc}"
        out.append(series)
    return out


def _load_mlb(tz: ZoneInfo, lo: date, hi: date) -> Series:
    url = (
        "https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&startDate={lo.isoformat()}&endDate={hi.isoformat()}"
    )
    series = Series("mlb", "statsapi.mlb.com/api/v1/schedule (live)")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = json.load(response)
    except Exception as exc:
        series.error = f"statsapi unreachable: {type(exc).__name__}: {exc}"
        return series
    series.vintage = "live"
    for day in payload.get("dates") or []:
        for game in day.get("games") or []:
            stamp = _parse_utc(game.get("gameDate"))
            if stamp is not None:
                series.add(stamp, tz)
    return series


def _sparkline(histogram: dict[str, int]) -> str:
    blocks = " .:-=+*#%"
    counts = [histogram[str(h)] for h in range(24)]
    peak = max(counts) or 1
    return "".join(blocks[min(8, round(8 * c / peak))] for c in counts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--back", type=int, default=30, help="days back from today")
    parser.add_argument("--ahead", type=int, default=14, help="days ahead of today")
    parser.add_argument("--tz", default="America/Chicago")
    parser.add_argument("--json", type=Path, default=None, help="also write the full result as JSON")
    args = parser.parse_args()

    tz = ZoneInfo(args.tz)
    today = datetime.now(tz).date()
    lo, hi = today - timedelta(days=args.back), today + timedelta(days=args.ahead)

    series: list[Series] = []
    series.extend(_load_soccer(tz, lo, hi))
    series.append(_load_wnba(tz, lo, hi))
    series.extend(_load_nfl(tz, lo, hi))
    series.append(_load_mlb(tz, lo, hi))

    gaps = {
        "nba": "no 2026-27 schedule in the checkout (season starts Oct)",
        "nhl": "no 2026-27 schedule in the checkout (season starts Oct)",
        "ncaab": "no 2026-27 schedule in the checkout (season starts Nov)",
        "ncaaf": "only 2025 schedule files present; 2026 season opens Aug 29",
    }

    print(f"KICKOFF-HOUR CENSUS   tz={args.tz}   window={lo}..{hi}   (today {today})")
    print("Hours are LOCAL. US evening band = "
          f"[{US_EVENING_START:02d}:00, {US_EVENING_END:02d}:00) -- the window Phase 1 protects.")
    print()

    header = f"{'series':<28}{'n':>5}  {'med':>4}  {'%eve':>5}  0h----------------------23h"
    print(header)
    print("-" * len(header))
    results = []
    for item in sorted(series, key=lambda s: s.key):
        summary = item.summary()
        results.append(summary)
        if summary["error"]:
            print(f"{summary['key']:<28}{'-':>5}  {'-':>4}  {'-':>5}  ERROR: {summary['error']}")
            continue
        if not summary["n"]:
            print(f"{summary['key']:<28}{0:>5}  {'-':>4}  {'-':>5}  (no fixtures in window)")
            continue
        print(
            f"{summary['key']:<28}{summary['n']:>5}  {summary['median_local_hour']:>4}  "
            f"{summary['pct_in_us_evening']:>5}  {_sparkline(summary['hour_histogram'])}"
        )

    print()
    print("PROVENANCE (a stale mirror is fine for an hour histogram; the vintage must still be visible)")
    for item in sorted(series, key=lambda s: s.key):
        summary = item.summary()
        if summary["n"]:
            print(f"  {summary['key']:<28} n={summary['n']:<5} span={summary['date_span']}  "
                  f"vintage={summary['vintage'] or 'n/a'}  src={summary['source']}")

    print()
    print("GAPS -- named, not silently omitted:")
    for sport, why in gaps.items():
        print(f"  {sport:<8} {why}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "tz": args.tz,
                    "window": {"from": lo.isoformat(), "to": hi.isoformat()},
                    "us_evening_band": [US_EVENING_START, US_EVENING_END],
                    "series": results,
                    "gaps": gaps,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
