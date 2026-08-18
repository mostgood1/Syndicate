#!/usr/bin/env python3
"""Backfill NFL CLOSING lines from OddsAPI's historical endpoints.

WHY. `docs/ai_context/nfl_feature_payload_preregistration.md` needs a
market-relative arm. Features exist for 2022-2025 (1,139 games, verified by
calling `load_nflverse_rows`), but `real_betting_lines_*.json` starts
**2025-09-01**, so anything market-relative rests on ~285 games and ATS is
untestable (SE 2.96 pts, needing ~6 pts of edge). Backfilling 2022-2024 lifts
that arm to ~1,139 and ATS SE to ~1.48.

CLOSING LINES ONLY, AND THAT IS THE WHOLE COST STORY. Line-movement history
would mean many snapshots per game; one capture just before kickoff means one
snapshot per KICKOFF WINDOW, and the NFL has ~5 a week (Thu / Sun early / Sun
late / Sun night / Mon). That is what makes this ~10k credits instead of the
115,739 a 30-day MLB backfill measured -- MLB plays ~2,430 games a season across
~180 slate days, the NFL ~285 across ~55.

Billing, from `backfill_mlb_historical_odds.py` which measured it:

    /v4/historical/sports/{sport}/events    1 credit  per call
    /v4/historical/sports/{sport}/odds     10 credits per market-region

So the run is deliberately two-phase:

  PHASE A  discover kickoff times   1 credit  per slate date   (~165 total)
  PHASE B  one odds snapshot per
           distinct kickoff window  30 credits (3 markets x us) (~350 total)

Phase A exists to make phase B cheap. Guessing kickoff windows from a calendar
would either miss games (international 09:30 ET, Saturday December slates, the
Christmas/Thanksgiving specials) or over-sample to be safe, and over-sampling is
charged at 30 credits a time.

DRY RUN BY DEFAULT. Spending needs `--execute`. `--max-credits` aborts mid-run
rather than after. Both mirror the MLB script, including the lesson recorded in
its `_record_quota` docstring: an earlier run spent 115,739 credits WITHOUT
attributing them to the platform quota ledger. Every call here is attributed.

Usage:
    py -3 scripts/backfill_nfl_historical_odds.py --seasons 2022,2023,2024
    py -3 scripts/backfill_nfl_historical_odds.py --seasons 2022 --execute --max-credits 5000
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"
MARKETS = ("h2h", "spreads", "totals")
REGIONS = "us"
PBP_DIR = REPO / "data/nfl_source/tracking/nflverse/pbp"
OUT_DIR = REPO / "data/nfl_source/historical_odds"

CREDITS_EVENTS_CALL = 1
CREDITS_ODDS_CALL = 10 * len(MARKETS)  # per market-region; one region


class Budget:
    """Charges from the response headers, never from an assumption.

    `x-requests-last` is what the API actually billed. The estimate below is
    what this script PREDICTS; if the two diverge, the header wins and the
    ceiling still binds.
    """

    def __init__(self, max_credits: int) -> None:
        self.max_credits = int(max_credits or 0)
        self.spent = 0
        self.calls = 0
        self.remaining_reported: int | None = None

    def charge(self, headers: dict[str, str]) -> None:
        self.calls += 1
        try:
            self.spent += int(float(headers.get("x-requests-last") or 0))
        except Exception:
            pass
        try:
            self.remaining_reported = int(float(headers.get("x-requests-remaining")))
        except Exception:
            pass
        if self.max_credits and self.spent > self.max_credits:
            raise SystemExit(
                "ABORTED: spent %d credits > --max-credits %d. Nothing further requested."
                % (self.spent, self.max_credits)
            )


def _api_key() -> str:
    for name in ("ODDS_API_KEY", "ODDSAPI_KEY", "THE_ODDS_API_KEY"):
        v = os.environ.get(name)
        if v:
            return v.strip()
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            for name in ("ODDS_API_KEY", "ODDSAPI_KEY", "THE_ODDS_API_KEY"):
                if line.strip().startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("No OddsAPI key found (ODDS_API_KEY / ODDSAPI_KEY / THE_ODDS_API_KEY).")


def _record_quota(headers: dict[str, str], *, endpoint: str) -> None:
    try:
        from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota

        record_oddsapi_quota(headers, sport="nfl", endpoint=endpoint)
    except Exception:
        pass


def _get(path: str, params: dict[str, Any], *, api_key: str, budget: Budget, retries: int = 3) -> Any:
    query = dict(params)
    query["apiKey"] = api_key
    url = "%s%s?%s" % (API_BASE, path, urllib.parse.urlencode(query))
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as resp:
                h = {str(k).lower(): str(v) for k, v in resp.headers.items()}
                budget.charge(h)
                _record_quota(h, endpoint="historical" + path)
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            h = {str(k).lower(): str(v) for k, v in (exc.headers or {}).items()}
            budget.charge(h)
            _record_quota(h, endpoint="historical" + path)
            if exc.code in (404, 422):
                # No snapshot at that instant, or a market never offered.
                # Ordinary; must not abort a multi-season run.
                return None
            last = exc
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(1.5 * (attempt + 1))
    print("  ! giving up on %s: %s" % (path, last), flush=True)
    return None


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def slate_dates(season: int) -> list[str]:
    """Distinct game dates for a season, from the pbp mirror.

    Local is correct here: this is offline backtest scaffolding, not a
    production claim (`model_engine_standard.md` §3b).
    """
    path = PBP_DIR / ("pbp_%d.csv" % season)
    if not path.is_file():
        return []
    dates: set[str] = set()
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh):
            d = str(row.get("game_date") or "").strip()
            if len(d) == 10:
                dates.add(d)
    return sorted(dates)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", default="2022,2023,2024")
    ap.add_argument("--execute", action="store_true", help="actually spend; omit for a dry run")
    ap.add_argument("--max-credits", type=int, default=20000)
    ap.add_argument("--lead-minutes", type=int, default=5, help="snapshot this long before kickoff")
    args = ap.parse_args()

    seasons = [int(s) for s in str(args.seasons).split(",") if s.strip()]
    plan = {s: slate_dates(s) for s in seasons}

    print("=" * 74)
    print("NFL HISTORICAL CLOSING-LINE BACKFILL  --  %s" % ("EXECUTE" if args.execute else "DRY RUN"))
    print("=" * 74)
    total_dates = 0
    for s in seasons:
        print("  %d: %d slate dates" % (s, len(plan[s])))
        total_dates += len(plan[s])
    if not total_dates:
        print("\nNo pbp slate dates found -- nothing to plan. Is data/nfl_source/tracking/nflverse/pbp populated?")
        return 2

    est_a = total_dates * CREDITS_EVENTS_CALL
    # Windows per slate date VARIES BY SEASON far more than expected, so this
    # is the observed WORST case, not the mean. Measured over the full run:
    #     2022  134 windows / 61 dates = 2.2
    #     2023  301 / 63             = 4.8
    #     2024  224 / 65             = 3.4
    # I guessed 1.7, then "corrected" to 2.2 from 2022 alone -- and 2.2 was
    # still low for both later seasons. Total came in at 19,959 credits against
    # a ~9,819 prediction, a 2x overrun. Anchoring to ONE season did not
    # generalise, so this now uses the high end: for a SPEND APPROVAL an
    # estimate that reads low is the harmful direction.
    est_windows = int(round(total_dates * 4.8))
    est_b = est_windows * CREDITS_ODDS_CALL
    print("\nESTIMATE (prediction, not a bill -- headers are authoritative):")
    print("  phase A  %5d events calls  x %2d = %7d credits" % (total_dates, CREDITS_EVENTS_CALL, est_a))
    print("  phase B  ~%4d odds snapshots x %2d = %7d credits" % (est_windows, CREDITS_ODDS_CALL, est_b))
    print("  TOTAL                                ~%7d credits" % (est_a + est_b))
    print("  ceiling  --max-credits                %7d" % args.max_credits)

    if not args.execute:
        print("\nDRY RUN -- nothing requested, nothing spent.")
        print("Re-run with --execute (and keep --max-credits) to spend.")
        return 0

    api_key = _api_key()
    budget = Budget(args.max_credits)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for season in seasons:
        out_path = OUT_DIR / ("closing_lines_%d.json" % season)
        captured: dict[str, Any] = {}
        windows: set[str] = set()

        # PHASE A -- learn real kickoff times (1 credit each).
        print("\n[%d] phase A: discovering kickoff windows over %d dates" % (season, len(plan[season])))
        for date_str in plan[season]:
            payload = _get("/historical/sports/%s/events" % SPORT,
                           {"date": "%sT12:00:00Z" % date_str},
                           api_key=api_key, budget=budget)
            data = (payload or {}).get("data") if isinstance(payload, dict) else payload
            for ev in data or []:
                ct = _parse_iso(ev.get("commence_time"))
                if ct:
                    windows.add(ct.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        print("  %d distinct kickoff windows  (spent so far: %d credits)" % (len(windows), budget.spent))

        # PHASE B -- one closing snapshot per window (30 credits each).
        print("[%d] phase B: one closing snapshot per window" % season)
        for i, window in enumerate(sorted(windows), 1):
            kickoff = _parse_iso(window)
            if kickoff is None:
                continue
            at = (kickoff - timedelta(minutes=args.lead_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
            payload = _get("/historical/sports/%s/odds" % SPORT,
                           {"date": at, "regions": REGIONS, "markets": ",".join(MARKETS),
                            "oddsFormat": "american"},
                           api_key=api_key, budget=budget)
            data = (payload or {}).get("data") if isinstance(payload, dict) else payload
            for ev in data or []:
                ct = _parse_iso(ev.get("commence_time"))
                # Keep only games kicking off in THIS window -- a snapshot also
                # carries later games, whose lines are not yet closing.
                if not ct or abs((ct - kickoff).total_seconds()) > 600:
                    continue
                # REJECT A SNAPSHOT THAT LANDS AFTER KICKOFF. Measured on the
                # first full run: 1 row in 2023 and 1 in 2024 (2 of 852) had
                # `snapshot_at` LATER than `commence_time`. A post-kickoff price
                # is not a closing line -- it can already carry in-game
                # information, which would leak the outcome into a backtest that
                # exists to measure a pregame model. 0.23% is small enough to
                # discard and far too contaminated to keep.
                if _parse_iso(at) and ct and _parse_iso(at) > ct:
                    print("    ! skipping post-kickoff snapshot for %s (%s > %s)"
                          % (ev.get("id"), at, ev.get("commence_time")), flush=True)
                    continue
                captured[str(ev.get("id"))] = {"snapshot_at": at, **ev}
            if i % 20 == 0:
                print("    %d/%d windows, %d games, %d credits" % (i, len(windows), len(captured), budget.spent))

        out_path.write_text(json.dumps({
            "season": season, "sport": SPORT, "markets": list(MARKETS), "regions": REGIONS,
            "lead_minutes": args.lead_minutes, "windows": len(windows),
            "games": len(captured), "events": captured,
        }, indent=2), encoding="utf-8")
        print("  wrote %s  (%d games, %d windows)" % (out_path, len(captured), len(windows)))

    print("\n" + "=" * 74)
    print("SPENT %d credits over %d calls." % (budget.spent, budget.calls))
    if budget.remaining_reported is not None:
        print("API reports %d remaining (header, at the last call)." % budget.remaining_reported)
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
