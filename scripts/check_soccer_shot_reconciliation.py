# -*- coding: utf-8 -*-
"""GATING INSTRUMENT: does our extracted shot count equal ESPN's own, per match?

WHY THIS EXISTS, and why it is not `check_soccer_shot_capture.py`. That script
asks a LEAGUE-level question against an external benchmark ("is this league's
shots/match far below ~23.4, i.e. are outcomes missing?") over whatever matches
a local cache happens to hold. It is a screen, and a screen cannot say which
shots are missing or prove that none are.

This one asks the exact question, per match, against ESPN's OWN arithmetic:
`len(extract_shot_events(summary))` vs the sum of both teams' `totalShots` in
the same payload. Same feed, same request, no benchmark, no tolerance. A single
match that disagrees is a defect, and the exit code says so.

WHAT IT CAUGHT (lane `soccer-shot-woodwork-undercount`, 2026-09-17). Over 24
finished matches in epl/la_liga/serie_a/bundesliga, 09-01..09-17, the old
three-type allowlist reconciled 9 of 24 matches; every shortfall equalled that
match's count of `shot-hit-woodwork` (23) and `penalty---saved` (1) entries --
1.42 shots/match, 5.0 per 100 kept, invisible to every downstream total.
After counting those types: 24 of 24, no residual gap.

    py -3 scripts/check_soccer_shot_reconciliation.py                  # exits non-zero on any mismatch
    py -3 scripts/check_soccer_shot_reconciliation.py --baseline       # the pre-fix allowlist, to prove the number moved
    py -3 scripts/check_soccer_shot_reconciliation.py --per-league 10 --leagues epl,serie_a --json

ON TARGET IS REPORTED, NOT GATED, and that is deliberate: measured on the same
24 matches, treating a woodwork strike as OFF target reconciles ESPN's
`shotsOnTarget` in 15 of 24 and as ON target in 10 of 24, with residuals in both
directions -- so ESPN's on-target figure is not a function of these type keys.
Gating on a number we cannot yet derive would encode a guess as a requirement.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.getcwd())

from syndicate.features.soccer.ingestion import espn_shot_events as shots
from syndicate.features.soccer.ingestion.espn_lineups import fetch_completed_events, fetch_match_summary

# The allowlist as it stood before the fix, used ONLY by --baseline so a reader
# can watch the number move rather than taking this file's word for it.
_LEGACY_TYPES = {"shot-on-target", "shot-off-target", "shot-blocked"}
_DEFAULT_LEAGUES = ("epl", "la_liga", "serie_a", "bundesliga")
_ON_TARGET = {"goal", "saved"}


def _team_stat(team: dict, *names: str) -> int | None:
    for stat in team.get("statistics") or []:
        if str(stat.get("name") or "") in names:
            try:
                return int(float(stat.get("displayValue") or stat.get("value") or 0))
            except (TypeError, ValueError):
                return None
    return None


def _espn_totals(summary: dict) -> tuple[int | None, int | None]:
    """ESPN's own per-match shot totals, summed over both teams. None when absent
    -- a match that does not publish the stat is SKIPPED, never counted as agreeing."""
    teams = (summary.get("boxscore") or {}).get("teams") or []
    total = [_team_stat(t, "totalShots", "shotsTotal") for t in teams]
    on = [_team_stat(t, "shotsOnTarget", "onTargetShots", "shotsOnGoal") for t in teams]
    return (sum(v for v in total if v is not None) or None if any(v is not None for v in total) else None,
            sum(v for v in on if v is not None) or None if any(v is not None for v in on) else None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--leagues", default=",".join(_DEFAULT_LEAGUES))
    parser.add_argument("--window", default="20260901-20260917", help="ESPN date window, YYYYMMDD-YYYYMMDD")
    parser.add_argument("--per-league", type=int, default=6)
    parser.add_argument("--baseline", action="store_true", help="run with the pre-fix allowlist")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.baseline:
        shots._NON_GOAL_SHOT_TYPES = set(_LEGACY_TYPES)

    rows: list[dict] = []
    for league in [s.strip() for s in args.leagues.split(",") if s.strip()]:
        try:
            events = fetch_completed_events(league, date_windows=[args.window])
        except Exception as exc:
            print(f"{league}: cannot list matches ({type(exc).__name__}: {exc})", flush=True)
            continue
        for event in events[: args.per_league]:
            event_id = str(event.get("event_id") or "")
            try:
                summary = fetch_match_summary(league, event_id)
            except Exception as exc:
                print(f"  {league} {event_id}: summary unavailable ({type(exc).__name__})", flush=True)
                continue
            extracted = shots.extract_shot_events(summary, event_id=event_id)
            espn_total, espn_on = _espn_totals(summary)
            ours_on = sum(1 for r in extracted if r["outcome"] in _ON_TARGET)
            rows.append({
                "league": league,
                "event_id": event_id,
                "ours_total": len(extracted),
                "espn_total": espn_total,
                "ours_on_target": ours_on,
                "espn_on_target": espn_on,
            })

    gated = [r for r in rows if r["espn_total"] is not None]
    mismatched = [r for r in gated if r["ours_total"] != r["espn_total"]]
    on_rows = [r for r in rows if r["espn_on_target"] is not None]
    on_exact = sum(1 for r in on_rows if r["ours_on_target"] == r["espn_on_target"])

    if args.json:
        print(json.dumps({
            "mode": "baseline" if args.baseline else "current",
            "matches": len(rows), "gated": len(gated), "mismatched": len(mismatched),
            "on_target_exact": on_exact, "on_target_matches": len(on_rows), "rows": rows,
        }, indent=1))
    else:
        for r in rows:
            flag = "OK " if r["espn_total"] is not None and r["ours_total"] == r["espn_total"] else (
                "SKIP" if r["espn_total"] is None else "MISS")
            print(f"  {flag} {r['league']:<11} {r['event_id']:>10}  shots ours {r['ours_total']:>3} vs ESPN "
                  f"{str(r['espn_total']):>4}   on target ours {r['ours_on_target']:>3} vs ESPN {str(r['espn_on_target']):>4}",
                  flush=True)
        mode = "PRE-FIX allowlist" if args.baseline else "current allowlist"
        print(f"\n{mode}: total shots exact in {len(gated) - len(mismatched)}/{len(gated)} matches"
              f" ({len(rows) - len(gated)} skipped for no published total)")
        if mismatched:
            print("  mismatched: " + ", ".join(f"{r['event_id']} ({r['ours_total'] - r['espn_total']:+d})" for r in mismatched))
        print(f"on target (REPORTED, NOT GATED -- see the module docstring): exact in {on_exact}/{len(on_rows)}")

    if not gated:
        print("NO MATCH PUBLISHED A SHOT TOTAL -- this run proves nothing.", flush=True)
        return 2
    return 1 if mismatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
