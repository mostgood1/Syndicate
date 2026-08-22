"""Two full seasons of shot-level data for the TEN LEAGUES SYNDICATE TRACKS.

WHY THIS EXISTS. Every negative result in the 2026-08-22 analysis died the same
way: a promising number in a tail cell at n<300, which reversed on a fresh
sample. Momentum's 40.2%, xG's +0.1028, and the xG-over-count ranking all
failed to replicate. At n~90 per time-bucket-decile the standard error is ~0.05,
so a +0.10 "effect" is one standard error of noise. No modelling change fixes
that -- only sample size does.

LEAGUE IDS ARE PINNED BY (NAME **AND** COUNTRY), and that is not pedantry.
Matching on name alone returned `Premier League` = 9986 (CANADA) and `Serie A`
= 268 (BRAZIL). Both would have harvested silently and been analysed as English
and Italian top-flight football. The ids below were verified against ccode:

    epl 47/ENG   la_liga 87/ESP   bundesliga 54/GER   serie_a 55/ITA
    ligue_1 53/FRA   mls 913550/USA   eredivisie 900368/NED
    primeira_liga 61/POR   championship 900638/ENG   belgian_pro_league 900433/BEL

RESUMABLE ON PURPOSE. A 750-day walk is ~8k HTTP calls; losing it to one
transient failure at hour two is not acceptable. Already-harvested match ids are
skipped, and the cache is flushed to disk periodically, so re-running continues
rather than restarts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.ingestion.fotmob_shots import matches_for_date, shots_for_match

_IDS = Path("reports/soccer_backtest/fotmob_league_ids.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2024-08-01")
    ap.add_argument("--end", default="2026-08-22")
    ap.add_argument("--out", default="reports/soccer_backtest/fotmob_2y.json")
    ap.add_argument("--flush-every", type=int, default=150)
    ap.add_argument("--sleep", type=float, default=0.0)
    # Per-match fetch is latency-bound (~1.5s/match serial), so a 750-day walk
    # runs ~3 hours single-threaded. A small pool cuts that to well under an
    # hour. Kept deliberately small: this is someone else's API, and a
    # rate-limit ban costs far more than the time saved. Failure rate is
    # reported per date so a throttle shows up as missing shotmaps rather than
    # being silently absorbed.
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    league_ids = json.loads(_IDS.read_text(encoding="utf-8"))
    id_to_slug = {int(v): k for k, v in league_ids.items()}
    out = Path(args.out)

    got: list[dict] = []
    have: set[str] = set()
    done_dates: set[str] = set()
    if out.exists():
        prev = json.loads(out.read_text(encoding="utf-8"))
        got = prev.get("matches", [])
        have = {str(m["match_id"]) for m in got}
        done_dates = set(prev.get("done_dates", []))
        print(f"resuming: {len(got)} matches, {len(done_dates)} dates already walked", flush=True)

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    days = (end - start).days + 1
    print(f"walking {days} dates, {len(id_to_slug)} leagues -> {out}", flush=True)

    def flush() -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps({"matches": got, "done_dates": sorted(done_dates),
                                   "league_ids": league_ids}), encoding="utf-8")
        tmp.replace(out)

    since_flush = 0
    for i in range(days):
        d = start + dt.timedelta(days=i)
        key = d.strftime("%Y%m%d")
        if key in done_dates:
            continue
        try:
            fixtures = matches_for_date(key)
        except Exception as exc:
            print(f"  {key} LIST FAILED {type(exc).__name__} -- not marking done", flush=True)
            continue
        mine = [f for f in fixtures
                if f.get("finished") and f.get("league_id") in id_to_slug
                and str(f.get("match_id")) not in have]
        kept = 0
        if mine:
            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
                fetched = list(pool.map(lambda f: (f, shots_for_match(f["match_id"])), mine))
            for f, row in fetched:
                if row and row["shots"]:
                    row["league"] = id_to_slug[f["league_id"]]
                    row["league_name"] = f.get("league")
                    row["date"] = d.isoformat()
                    got.append(row)
                    have.add(str(f["match_id"]))
                    kept += 1
                    since_flush += 1
            if args.sleep:
                time.sleep(args.sleep)
        done_dates.add(key)
        if mine or kept:
            print(f"  {d} {kept}/{len(mine)} shotmaps   total {len(got)}", flush=True)
        if since_flush >= args.flush_every:
            flush()
            since_flush = 0
            print(f"  ... flushed at {len(got)}", flush=True)

    flush()
    by: dict[str, int] = {}
    for m in got:
        by[m["league"]] = by.get(m["league"], 0) + 1
    print(f"\nDONE {len(got)} matches", flush=True)
    for k, v in sorted(by.items(), key=lambda x: -x[1]):
        print(f"  {k:<22}{v:>6}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
