"""Is there a usable NCAAF injury feed? Measure it, do not assume.

WHY THIS EXISTS AS A SCRIPT rather than a one-off answer. The decisive question
is whether ESPN populates COLLEGE injuries DURING THE SEASON, and that cannot be
answered in August -- NCAAF opens 2026-08-29. Measured 2026-08-20 it returned
**1 injury across 140 teams, and that one was dated 2020-11-21** (stale by six
years). An empty offseason feed and a permanently empty feed look identical
right now, and this session has already been burned twice by reading a null from
a query rather than from the world.

So: re-run this in-season. It answers the question in one command.

WHAT IT CHECKS

  1. A POSITIVE CONTROL on the NFL, whose season overlaps and whose feed is
     known-populated (220 injuries across 3 teams when this was written). If the
     control is empty the probe itself is broken and the CFB number means
     nothing -- that check is the whole reason a bare CFB count is not enough.
  2. CFB coverage: how many teams carry ANY injury, and how fresh the records
     are. Staleness matters as much as count; a 2020 record is not availability
     data.

WHAT NO FEED CAN FIX, and it should temper expectations either way:

**The NCAA has no mandatory injury report.** The NFL compels teams to file
official participation and game-status reports; college programs are under no
such obligation and many coaches deliberately withhold. So college injury data
is structurally thinner and less reliable than the NFL's -- this is a property
of the SPORT, not a gap in any one vendor. Expect any source, paid or free, to
be worse for CFB than for NFL.

AND EVEN A GOOD FEED IS NOT ENOUGH. NFL has excellent injury data and its
injury adjustment was backtested and **HURT** -- full-season win accuracy
60.98% -> 56.44% over 264 games with a modeled injury, because the impact
estimates were historical averages confounded by opponent strength and game
script. A feed is necessary and not sufficient; the causal estimation is the
hard part.

    py -3 scripts/probe_ncaaf_injury_feed.py
    py -3 scripts/probe_ncaaf_injury_feed.py --teams 60 --stale-days 30
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
UA = {"User-Agent": "Mozilla/5.0 (compatible; syndicate-injury-probe/1.0)"}


def get(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def team_ids(league: str, limit: int) -> list[str]:
    out: list[str] = []
    try:
        payload = get(f"{CORE}/{league}/teams?limit=400")
    except Exception:
        return out
    for item in (payload.get("items") or []):
        ref = str(item.get("$ref") or "")
        if "/teams/" in ref:
            out.append(ref.split("/teams/")[1].split("?")[0].rstrip("/"))
        if len(out) >= limit:
            break
    return out


def injuries_for(league: str, tid: str) -> tuple[str, int, list[str]]:
    """(team, count, ISO dates). count -1 marks a request failure, which is NOT
    the same as zero and is reported separately."""
    try:
        payload = get(f"{CORE}/{league}/teams/{tid}/injuries")
    except Exception:
        return (tid, -1, [])
    count = int(payload.get("count") or 0)
    dates: list[str] = []
    for item in (payload.get("items") or [])[:3]:
        ref = item.get("$ref")
        if not ref:
            continue
        try:
            dates.append(str(get(ref).get("date") or ""))
        except Exception:
            continue
    return (tid, count, dates)


def survey(league: str, label: str, limit: int, workers: int) -> dict:
    ids = team_ids(league, limit)
    total = teams_with = errors = 0
    all_dates: list[str] = []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for _tid, count, dates in ex.map(lambda t: injuries_for(league, t), ids):
            if count < 0:
                errors += 1
                continue
            total += count
            if count:
                teams_with += 1
            all_dates += [d for d in dates if d]
    return {"label": label, "teams": len(ids), "total": total,
            "teams_with": teams_with, "errors": errors, "dates": all_dates}


def show(r: dict, stale_days: int) -> None:
    print(f"  {r['label']:<22} teams={r['teams']:<4} injuries={r['total']:<5} "
          f"teams_with_any={r['teams_with']:<4} errors={r['errors']}")
    if r["dates"]:
        now = datetime.now(timezone.utc)
        ages = []
        for d in r["dates"]:
            try:
                dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
                ages.append((now - dt.astimezone(timezone.utc)).days)
            except Exception:
                continue
        if ages:
            fresh = sum(1 for a in ages if a <= stale_days)
            print(f"  {'':<22} sampled dates: {len(ages)}, "
                  f"fresh(<={stale_days}d): {fresh}, oldest: {max(ages)}d")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--teams", type=int, default=140)
    ap.add_argument("--stale-days", type=int, default=30)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    print("=" * 74)
    print("NCAAF INJURY FEED PROBE -- ESPN core API")
    print("=" * 74)

    nfl = survey("nfl", "NFL (control)", min(8, args.teams), args.workers)
    show(nfl, args.stale_days)
    cfb = survey("college-football", "college-football", args.teams, args.workers)
    show(cfb, args.stale_days)

    print()
    if nfl["total"] == 0:
        print("  POSITIVE CONTROL FAILED -- the NFL feed is empty too, so this probe")
        print("  is broken (blocked, rate-limited or the schema moved). The CFB")
        print("  number below means NOTHING. Fix the probe before concluding.")
        return 2

    print(f"  control OK: NFL returns {nfl['total']} injuries, so the probe works.")
    if cfb["total"] == 0:
        print("  CFB IS EMPTY. ESPN does not populate college injuries (at least now).")
    elif cfb["teams_with"] < cfb["teams"] * 0.25:
        print(f"  CFB IS SPARSE: only {cfb['teams_with']} of {cfb['teams']} teams carry any")
        print("  injury. Too thin to model with -- a per-game availability signal needs")
        print("  most teams covered, most weeks.")
    else:
        print(f"  CFB LOOKS USABLE: {cfb['teams_with']} of {cfb['teams']} teams covered.")
        print("  NEXT: start capturing DAILY snapshots. This endpoint is CURRENT-STATE")
        print("  only -- it cannot be backfilled, so a backtest is impossible until a")
        print("  season of snapshots has accrued. Collect first, model later.")
    print()
    print("  Remember: the NCAA has no mandatory injury report, so college data is")
    print("  structurally thinner than the NFL's. And NFL's own injury adjustment")
    print("  was backtested and HURT (60.98% -> 56.44%) -- a feed is necessary,")
    print("  not sufficient.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
