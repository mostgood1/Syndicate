"""Does every upcoming ESPN fixture join to a FotMob match id? A respelling detector.

WHY THIS EXISTS. The live soccer poller (`scripts/poll_soccer_live_state.py`)
joins each in-play ESPN match to FotMob through `resolve_fotmob_match_id`, and a
miss is SILENT: the match's `momentum` block reads `supported: False`, reason
`fotmob match id unresolved`, and the card hides the panel. The join depends on
names. `_ESPN_NAME_ALIASES` is keyed to exact ESPN spellings ("stade rennais",
"fc cologne"), and the strict and loose passes depend on how both vendors write a
club. A respelling on either side, or a club neither rule bridges, surfaces only
after kickoff, in one game's live file.

Adding aliases for spellings nobody has seen is guessing (`learnings.md`
2026-09-06: FORBIDDEN, a refusal keyed to ONE spelling of a value that has
synonyms). Both vendors publish fixtures days ahead, so this checker resolves
them BEFORE match day and names every miss.

PRODUCTION'S INPUTS, exactly. For each Central date D and tracked league:
`espn_lineups.fetch_events(league, date_windows=["YYYYMMDD"])`, the poller's
single-date window, then `resolve_fotmob_match_id(league=..., home_team=event
["home_team"], away_team=event["away_team"], iso_date=D)`. The poller asks only
about `in` matches; this asks about every state, which is the point.

FotMob's per-date listing is fetched ONCE per date and handed to the resolver
through its `_fetch`. The resolver reads the same three dates for every fixture
on a date, so this changes how often the listing is downloaded, not which rows
the resolver sees. The listings are fetched here first rather than inside the
resolver, because the resolver swallows a fetch error into None and a failed
download would otherwise read as a respelling.

EXIT CODES
  0  every fixture resolved
  1  at least one fixture UNRESOLVED (a respelling, an alias gap, or FotMob not
     listing it). Each is printed beside FotMob's unclaimed fixtures in that
     league and window, so the new spelling is visible.
  2  no fixture unresolved, but some league/date could not be fetched, so its
     coverage is UNKNOWN. Unknown is not clear.

    py -3 scripts/check_fotmob_join_coverage.py                 # today (Central) + 6 days
    py -3 scripts/check_fotmob_join_coverage.py --start 2026-09-19 --days 2 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS, fetch_events  # noqa: E402
from syndicate.features.soccer.ingestion.fotmob_match_id import (  # noqa: E402
    FOTMOB_LEAGUES,
    fotmob_league_slug,
    resolve_fotmob_match_id,
)
from syndicate.features.soccer.ingestion.fotmob_shots import matches_for_date  # noqa: E402


def _central_today() -> date_cls:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:  # no tz database: the UTC date is off by at most one evening
        return datetime.now(timezone.utc).date()


def _window(iso: str) -> list[str]:
    d = date_cls.fromisoformat(iso)
    return [date_cls.fromordinal(d.toordinal() + off).strftime("%Y%m%d") for off in (0, -1, 1)]


def check(
    dates: list[str],
    leagues: list[str],
    *,
    espn_fetch: Callable[..., list[dict[str, Any]]] = fetch_events,
    fotmob_fetch: Callable[[str], list[dict[str, Any]]] = matches_for_date,
) -> dict[str, Any]:
    """Resolve every ESPN fixture on `dates` (ISO, Central) for `leagues`."""
    listings: dict[str, list[dict[str, Any]]] = {}
    listing_errors: dict[str, str] = {}

    def listing(compact: str) -> list[dict[str, Any]]:
        if compact not in listings and compact not in listing_errors:
            try:
                listings[compact] = list(fotmob_fetch(compact))
            except Exception as exc:
                listing_errors[compact] = f"{type(exc).__name__}: {exc}"
        if compact in listing_errors:
            raise RuntimeError(listing_errors[compact])
        return listings[compact]

    fixtures: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for iso in dates:
        compact = iso.replace("-", "")
        failed = [c for c in _window(iso) if not _try(listing, c)]
        for league in leagues:
            try:
                events = espn_fetch(league, date_windows=[compact])
            except Exception as exc:
                unknown.append({"league": league, "date": iso, "source": "espn", "error": f"{type(exc).__name__}: {exc}"})
                continue
            if failed and events:
                unknown.append({"league": league, "date": iso, "source": "fotmob",
                                "error": "; ".join(f"{c}: {listing_errors[c]}" for c in failed)})
                continue
            for event in events:
                home, away = event.get("home_team"), event.get("away_team")
                mid = resolve_fotmob_match_id(league=league, home_team=home, away_team=away, iso_date=iso, _fetch=listing)
                fixtures.append({
                    "league": league, "date": iso, "event_id": event.get("event_id"), "kickoff": event.get("date"),
                    "state": event.get("status_state"), "espn_home": home, "espn_away": away, "fotmob_match_id": mid,
                })

    claimed = {f["fotmob_match_id"] for f in fixtures if f["fotmob_match_id"] is not None}
    unresolved = []
    for f in fixtures:
        if f["fotmob_match_id"] is not None:
            continue
        rows = [r for c in _window(f["date"]) for r in listings.get(c, []) if fotmob_league_slug(r) == f["league"]]
        seen: set[int] = set()
        candidates = []
        for r in rows:
            mid = r.get("match_id")
            if mid is None or int(mid) in claimed or int(mid) in seen:
                continue
            seen.add(int(mid))
            candidates.append({"match_id": int(mid), "home": r.get("home"), "away": r.get("away"), "time": r.get("time")})
        unresolved.append({**f, "fotmob_unclaimed_in_league_window": candidates})

    per_league: dict[str, dict[str, int]] = {}
    for f in fixtures:
        row = per_league.setdefault(f["league"], {"fixtures": 0, "resolved": 0})
        row["fixtures"] += 1
        row["resolved"] += f["fotmob_match_id"] is not None
    exit_code = 1 if unresolved else (2 if unknown else 0)
    return {
        "dates": dates, "leagues": leagues, "fixtures": len(fixtures),
        "resolved": sum(1 for f in fixtures if f["fotmob_match_id"] is not None),
        "unresolved": unresolved, "unknown": unknown, "per_league": per_league, "exit_code": exit_code,
    }


def _try(fn: Callable[[str], Any], arg: str) -> bool:
    try:
        fn(arg)
        return True
    except Exception:
        return False


def _print_report(report: dict[str, Any]) -> None:
    print(f"dates {report['dates'][0]}..{report['dates'][-1]} ({len(report['dates'])}), leagues {len(report['leagues'])}", flush=True)
    for league in report["leagues"]:
        row = report["per_league"].get(league, {"fixtures": 0, "resolved": 0})
        print(f"  {league:<20} {row['resolved']}/{row['fixtures']}", flush=True)
    for f in report["unresolved"]:
        print(f"UNRESOLVED {f['league']} {f['date']} event {f['event_id']} ({f['state']}, {f['kickoff']}): "
              f"ESPN {f['espn_home']!r} v {f['espn_away']!r}", flush=True)
        for c in f["fotmob_unclaimed_in_league_window"]:
            print(f"    FotMob unclaimed: {c['match_id']} {c['home']!r} v {c['away']!r} ({c['time']})", flush=True)
    for u in report["unknown"]:
        print(f"UNKNOWN {u['league']} {u['date']} {u['source']}: {u['error']}", flush=True)
    print(f"FOTMOB_JOIN_COVERAGE resolved={report['resolved']}/{report['fixtures']} "
          f"unresolved={len(report['unresolved'])} unknown={len(report['unknown'])} exit={report['exit_code']}", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", help="first Central date, YYYY-MM-DD (default: today, Central)")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--leagues", help="comma-separated league slugs (default: every tracked league)")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = ap.parse_args(argv)

    start = date_cls.fromisoformat(args.start) if args.start else _central_today()
    dates = [(start + timedelta(days=i)).isoformat() for i in range(max(1, args.days))]
    tracked = [slug for slug in FOTMOB_LEAGUES if slug in LEAGUE_ESPN_SLUGS]
    leagues = [s.strip() for s in args.leagues.split(",")] if args.leagues else tracked
    bad = [s for s in leagues if s not in tracked]
    if bad:
        print(f"unknown league(s): {bad}; tracked: {tracked}", flush=True)
        return 2
    report = check(dates, leagues)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1), flush=True)
    else:
        _print_report(report)
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
