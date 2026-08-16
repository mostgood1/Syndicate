"""Read the `win_prob` null counter from production, and print the HISTORY.

WHY THIS EXISTS RATHER THAN A curl OR A THROWAWAY SNIPPET.

**The route's own headline erases the result you are looking for.**
`/api/ops/win-prob-null` summarises `readings[*].latest` only
(`win_prob_null_diag._summarize`), so the moment ANY later run reports
`rows=0` -- an out-of-season sport, a next-day build, a slate that computed
nothing -- the top level flips to:

    any_exercised: false
    rows: 0
    interpretation: "producers reported but computed no win_prob"

while the exercised runs sit untouched in `readings[*].recent` in the same
payload. Measured 2026-08-16T15:33:39Z: that headline said `any_exercised:
false` while the history held `rows=56, null_no_price=3` from 05:11:01Z. A
reader who trusted `interpretation` would have filed "still unexercised" on top
of the proof -- the same instrument-blindness `win_prob_null_diag` was written
to end, reintroduced one layer up. **This tool prints `recent` next to
`latest`, always, so the headline cannot be the whole reading.**

Also here because the secret must stay out of argv: `ADMIN_TOKEN` is read from
the gitignored `.env` the same way `check_deploy_safety` reads it, so this can
be permitted as exactly `Bash(python scripts/read_win_prob_null.py *)` rather
than opening up `curl`.

HOW TO READ THE OUTPUT -- per run, not per service:
    rows=0          -> ran, computed no win_prob. Says NOTHING about the fix.
                       Correct for out-of-season NBA and for next-day builds.
    rows>0, null=0  -> the `or 0.5` removal is holding AND exercised.
    null>0          -> the branch fired: that many rows had no price and
                       published None instead of a fabricated 0.5. That is the
                       fix WORKING, not a defect. Report it as a RATE.

    py -3 scripts/read_win_prob_null.py
    py -3 scripts/read_win_prob_null.py --json
    py -3 scripts/read_win_prob_null.py --base-url http://127.0.0.1:5000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://syndicate-an21.onrender.com"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _admin_token() -> str:
    """Same resolution order as `check_deploy_safety`, so there is one answer."""
    value = str(os.environ.get("ADMIN_TOKEN") or os.environ.get("SYNDICATE_ADMIN_TOKEN") or "").strip()
    if value:
        return value
    env_path = REPO_ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, raw = line.partition("=")
            if sep and key.strip() in {"ADMIN_TOKEN", "SYNDICATE_ADMIN_TOKEN"}:
                token = raw.strip().strip('"').strip("'")
                if token:
                    return token
    raise SystemExit("ADMIN_TOKEN not found in env or .env")


def fetch(base_url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/ops/win-prob-null",
        headers={"X-Admin-Token": _admin_token(), "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return {"status": response.status, "payload": json.loads(response.read().decode("utf-8"))}


def _runs(reading: dict[str, Any]) -> list[dict[str, Any]]:
    """Every run this key holds, newest first: `latest` then `recent`.

    The distinction that matters is NOT latest-vs-recent, it is rows>0 vs
    rows=0, and that cuts across both.
    """
    runs: list[dict[str, Any]] = []
    latest = reading.get("latest")
    if isinstance(latest, dict):
        runs.append(latest)
    recent = reading.get("recent")
    if isinstance(recent, list):
        runs.extend(item for item in recent if isinstance(item, dict))
    return runs


def render(result: dict[str, Any]) -> int:
    payload = result["payload"]
    readings = [item for item in (payload.get("readings") or []) if isinstance(item, dict)]
    probed = [item for item in (payload.get("probed") or []) if isinstance(item, dict)]

    print(f"HTTP {result['status']}   read_at {payload.get('generated_at')}")
    print(f"reports_root {payload.get('reports_root')}")
    print(
        f"probed {len(probed)} keys, {sum(1 for i in probed if i.get('present'))} present, "
        f"{sum(1 for i in probed if i.get('read_failed'))} read_failed"
    )
    # Printed, then immediately qualified -- it is latest-only by construction.
    summary = payload.get("summary") or {}
    print(f"route headline (LATEST-ONLY, not the whole story): any_exercised={payload.get('any_exercised')} "
          f"rows={summary.get('rows')} null={summary.get('null_no_price')}")

    exercised_runs: list[tuple[str, dict[str, Any]]] = []
    total_rows = 0
    total_nulls = 0

    for reading in readings:
        label = f"{reading.get('sport')}/{reading.get('service')}"
        runs = _runs(reading)
        print(f"\n{label}  runs_recorded={reading.get('runs_recorded')}  ({len(runs)} run(s) retained)")
        for index, run in enumerate(runs):
            rows = int(run.get("rows") or 0)
            nulls = int(run.get("null_no_price") or 0)
            total_rows += rows
            total_nulls += nulls
            marker = "  <- EXERCISED" if rows > 0 else ""
            if rows > 0:
                exercised_runs.append((label, run))
            tag = "latest" if index == 0 else f"prior[{index}]"
            print(
                f"  {tag:>9}  rows={rows:<5} null={nulls:<4} pct={run.get('pct')}  "
                f"date={run.get('date')}  at={run.get('generated_at')}"
                f"  commit={str(run.get('commit') or '')[:8]}{marker}"
            )

    print("\n=== ACROSS ALL RETAINED RUNS (this is the reading, not the headline) ===")
    if not readings:
        print("no producer has reported on any key -- a fact about the WRITER, not about the fix")
        return 0
    if total_rows == 0:
        print(f"{len(readings)} key(s) reported, every retained run rows=0 -- says NOTHING about the fix")
        return 0
    pct = 100.0 * total_nulls / total_rows
    print(f"rows={total_rows}  null_no_price={total_nulls}  pct={pct:.2f}%")
    print(f"the `or 0.5` removal IS exercised: {len(exercised_runs)} run(s) computed win_prob rows")
    if total_nulls:
        print(f"the null branch FIRED on {total_nulls} row(s) -- published None instead of a fabricated 0.5 (the fix WORKING)")
    else:
        print("no price-missing rows in the retained window -- fix holding, branch not fired here")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--json", action="store_true", help="raw payload, unsummarised")
    args = parser.parse_args(argv)

    try:
        result = fetch(args.base_url, args.timeout)
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code} from {args.base_url} -- the ROUTE failed; this is not a reading", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 -- a failed fetch must not look like "no readings"
        print(f"{type(exc).__name__}: {exc} -- fetch failed; this is not a reading", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result["payload"], indent=2))
        return 0
    return render(result)


if __name__ == "__main__":
    raise SystemExit(main())
