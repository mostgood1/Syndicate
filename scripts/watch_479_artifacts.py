"""Watch for `#479`'s derived artifacts to actually appear in production.

WHY THIS CHECKS CONTENT AND NOT PRESENCE. On 2026-08-20 the export endpoint
started reporting `player_logs.csv` present (`count=1`) the moment `#482`
allowlisted it -- and it was tempting to call `#479` confirmed. It was not
that file: it is 85 days old, its data stops 2026-05-24, and it has NO
`MATCHUP` column. A pre-existing stale artifact and a freshly-built one are
indistinguishable by presence, so presence is the wrong signal.

`#477`'s builder is identified by two things the old file cannot have:
  * a `MATCHUP` column -- the whole point of `#477`, since
    `_player_split_rate_context_local` parses it via `_matchup_opponent` /
    `_matchup_home_flag` to derive opponent and home/away. Without it all
    three split mechanisms decline to fire.
  * substantially more rows (~3,132 measured locally vs the stale 1,603).

`home_court_advantage.json` needs no such test -- it has never existed, so
its appearance at all is the signal.

Exit codes: 0 both confirmed | 1 still waiting | 2 partial (one of two)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_BASE = "https://syndicate-an21.onrender.com"
_STALE_MAX_DATE = "2026-05-24"


def _token() -> str:
    env = REPO_ROOT / ".env"
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("ADMIN_TOKEN"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ADMIN_TOKEN not found")


def _ex(tok: str, **kw):
    url = _BASE + "/api/ops/artifacts/export?" + urllib.parse.urlencode({"admin_token": tok, **kw})
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="wnba")
    args = ap.parse_args()
    tok = _token()
    lg = args.league
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    print(f"[{dt.datetime.now(dt.timezone.utc).strftime('%H:%M:%SZ')}] checking {lg}")

    pl_ok = False
    try:
        d = _ex(tok, path=f"{lg}_source/data/processed/player_logs.csv")
        if d.get("count"):
            txt = list(d["artifacts"].values())[0]
            lines = txt.splitlines()
            cols = lines[0].split(",")
            rows = len(lines) - 1
            has_mu = "MATCHUP" in cols
            maxd = ""
            if "GAME_DATE" in cols:
                gi = cols.index("GAME_DATE")
                maxd = max((l.split(",")[gi] for l in lines[1:]), default="")
            print(f"  player_logs.csv rows={rows} MATCHUP={has_mu} max_date={maxd}")
            if has_mu and rows > 1603:
                pl_ok = True
                print("    -> #477 BUILD CONFIRMED (MATCHUP present, row count above the stale 1,603)")
            elif has_mu:
                pl_ok = True
                print("    -> MATCHUP present -- #477 build confirmed by column, row count low but decisive")
            else:
                print(f"    -> still the STALE pre-existing file (no MATCHUP; stale data ends {_STALE_MAX_DATE})")
        else:
            print("  player_logs.csv absent")
    except Exception as exc:
        print(f"  player_logs.csv check error: {type(exc).__name__}: {exc}")

    hca_ok = False
    try:
        d = _ex(tok, pattern=f"{lg}_source/*/processed/home_court_advantage.json", names_only="1")
        n = d.get("count") or 0
        print(f"  home_court_advantage.json instances={n}")
        if n:
            for p, m in d["artifacts"].items():
                print(f"    {p} age={(now - m['mtime'])/60:.1f}min {m['bytes']:,}B")
            hca_ok = True
            print("    -> #474 ARTIFACT CONFIRMED (never existed before)")
    except Exception as exc:
        print(f"  hca check error: {type(exc).__name__}: {exc}")

    if pl_ok and hca_ok:
        print("SIGNAL: BOTH confirmed -- #479's builders ran in production")
        return 0
    if pl_ok or hca_ok:
        print("PARTIAL: one of two confirmed")
        return 2
    print("WAITING: neither artifact shows a #479 build yet")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
