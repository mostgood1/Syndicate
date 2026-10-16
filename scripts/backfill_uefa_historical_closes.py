#!/usr/bin/env python3
"""Backfill UEFA main-draw CLOSING 1X2 snapshots from OddsAPI's historical endpoint (todo #699 step 3).

RESEARCH ONLY. One snapshot per distinct ESPN kickoff minute per competition, requested at
kickoff - 5 minutes (`regions=eu`, `markets=h2h`: 10 credits a call). The ESPN kickoffs come from
the research root of `fit_uefa_league_offsets.py`. Raw snapshots are cached under
`<out>/raw/<competition>/<YYYYMMDDTHHMM>.json` and never re-requested. The registration is
`.syndicate/findings_2026-10-16_uefa_close_backtest.md` section 1.

DRY RUN BY DEFAULT: it prints the window count and the credit estimate. Spending needs `--execute`.
`--max-credits` aborts mid-run, counted from `x-requests-last`. Three consecutive failures abort
(a dead key otherwise looks like a slow run). The key is read from the environment, else from
`--env-file`; it is never printed.

    py -3 scripts/backfill_uefa_historical_closes.py --uefa-root C:/tmp/uefa-offsets --out C:/tmp/uefa-closes
    ODDS_API_KEY= py -3 scripts/backfill_uefa_historical_closes.py ... --execute --max-credits 12000 \
        --env-file C:/Users/tempadmin/OneDrive/Coding/Syndicate/.env
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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

API = "https://api.the-odds-api.com/v4/historical/sports/{sport}/odds"
SPORT_KEYS = {"ucl": "soccer_uefa_champs_league", "uel": "soccer_uefa_europa_league",
              "uecl": "soccer_uefa_europa_conference_league"}
FIRST_DAY = "2020-06-06"
LEAD = timedelta(minutes=5)
CREDITS_PER_CALL = 10


def windows(uefa_root: Path) -> dict[str, list[datetime]]:
    """{competition: sorted distinct ESPN main-draw kickoff minutes on or after FIRST_DAY}."""
    out: dict[str, set[datetime]] = {c: set() for c in SPORT_KEYS}
    for comp in SPORT_KEYS:
        for path in sorted((uefa_root / "uefa" / comp / "history").glob("uefa_results_*.csv")):
            with path.open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    if row["stage"] == "qualifying" or row["date"][:10] < FIRST_DAY:
                        continue
                    ko = datetime.fromisoformat(row["date"].replace("Z", "+00:00")).replace(second=0, microsecond=0)
                    out[comp].add(ko)
    return {c: sorted(v) for c, v in out.items()}


def snapshot_path(out: Path, comp: str, ko: datetime) -> Path:
    return out / "raw" / comp / f"{ko.strftime('%Y%m%dT%H%M')}.json"


def _key(env_file: str | None) -> str:
    for name in ("ODDS_API_KEY", "ODDSAPI_KEY", "THE_ODDS_API_KEY"):
        if os.environ.get(name):
            return os.environ[name].strip()
    if env_file and Path(env_file).exists():
        for line in Path(env_file).read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("ODDS_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no OddsAPI key (environment or --env-file)")


def _record_quota(headers: dict[str, str]) -> None:
    try:
        from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota

        record_oddsapi_quota(headers, sport="soccer", endpoint="historical/odds")
    except Exception:
        pass


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--uefa-root", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--max-credits", type=int, default=12000)
    p.add_argument("--env-file")
    p.add_argument("--pause", type=float, default=0.3)
    args = p.parse_args(argv)
    out = Path(args.out)
    wins = windows(Path(args.uefa_root))
    todo = [(c, ko) for c, kos in wins.items() for ko in kos if not snapshot_path(out, c, ko).exists()]
    print(f"WINDOWS {sum(len(v) for v in wins.values())} " + " ".join(f"{c}={len(v)}" for c, v in wins.items())
          + f" | to fetch {len(todo)} | estimate {len(todo) * CREDITS_PER_CALL} credits", flush=True)
    if not args.execute:
        print("DRY RUN: nothing requested (pass --execute)", flush=True)
        return 0
    key = _key(args.env_file)
    spent = calls = fails = empty = 0
    for i, (comp, ko) in enumerate(todo):
        at = (ko - LEAD).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        q = urllib.parse.urlencode({"apiKey": key, "regions": "eu", "markets": "h2h", "date": at,
                                    "oddsFormat": "decimal"})
        try:
            with urllib.request.urlopen(f"{API.format(sport=SPORT_KEYS[comp])}?{q}", timeout=90) as resp:
                headers = {k.lower(): v for k, v in resp.headers.items()}
                payload = json.loads(resp.read())
            fails = 0
        except urllib.error.HTTPError as exc:
            headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
            payload = None
            if exc.code not in (404, 422):
                fails += 1
            print(f"HTTP {exc.code} {comp} {at}", flush=True)
        except Exception as exc:  # noqa: BLE001
            headers, payload = {}, None
            fails += 1
            print(f"ERROR {comp} {at} {type(exc).__name__}", flush=True)
        calls += 1
        spent += int(float(headers.get("x-requests-last") or 0))
        _record_quota(headers)
        if payload is not None:
            path = snapshot_path(out, comp, ko)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, path)
            empty += not (payload.get("data") or [])
        if fails >= 3:
            print(f"ABORT: 3 consecutive failures after {calls} calls, {spent} credits", flush=True)
            return 2
        if spent > args.max_credits:
            print(f"ABORT: spent {spent} > --max-credits {args.max_credits}", flush=True)
            return 3
        if i % 50 == 0:
            print(f"PROGRESS {i + 1}/{len(todo)} credits={spent} empty={empty}", flush=True)
        time.sleep(args.pause)
    print(f"DONE calls={calls} credits={spent} empty_snapshots={empty} "
          f"remaining_reported={headers.get('x-requests-remaining')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
