"""Does momentum LEAD goals, or only record them?

THE ONLY QUESTION THAT MATTERS BEFORE WIRING MOMENTUM INTO THE SIM.

Vendor momentum panels (FotMob, AiScore) are built from shots, attacks and
possession location -- and a goal is itself such an event. So a chart that
counts goals spikes AT the goal marker and correlates with goals BY
CONSTRUCTION, while carrying no predictive content whatsoever. Eyeballing a
chart cannot separate those two cases; this can.

METHOD. For every goal at time T, measure momentum at T - `lead_seconds`,
signed IN FAVOUR OF THE TEAM THAT SCORED. Compare that against the same
measurement taken at CONTROL instants -- times that were NOT followed by a goal
within the horizon -- signed in favour of each side in turn so the control is
not accidentally biased toward the stronger team.

If the two distributions do not separate, momentum is a NARRATOR, not a
PREDICTOR: still useful to a human reading a match, worthless as a sim input.

GOALS ARE EXCLUDED FROM THE MOMENTUM SERIES ITSELF (`include_goals=False`), and
`momentum_at` is strictly causal, so a value at T - lead cannot see the goal it
is being asked to predict. Without both, this test passes trivially and means
nothing.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.soccer.features.momentum import (
    DEFAULT_HALF_LIFE_SECONDS,
    momentum_at,
    momentum_events,
)
from syndicate.features.soccer.ingestion.espn_lineups import (
    fetch_events,
    fetch_match_summary,
)


def _goals(summary: dict[str, Any], home_team: str) -> list[tuple[float, float]]:
    """(clock_seconds, sign) for each goal -- sign +1 if the HOME team scored."""
    out: list[tuple[float, float]] = []
    for entry in summary.get("commentary") or []:
        play = entry.get("play") or {}
        type_key = str((play.get("type") or {}).get("type") or "").lower()
        if not type_key.startswith("goal"):
            continue
        if "cancelled" in type_key or "disallowed" in type_key:
            continue
        clock = play.get("clock") or {}
        try:
            seconds = float(clock.get("value"))
        except (TypeError, ValueError):
            continue
        team = str((play.get("team") or {}).get("displayName") or "").strip()
        if not team:
            continue
        out.append((seconds, 1.0 if team == home_team else -1.0))
    return out


def analyse(
    league: str,
    event_id: str,
    *,
    lead_seconds: float,
    horizon_seconds: float,
    half_life: float,
    control_step: float = 300.0,
) -> dict[str, Any]:
    summary = fetch_match_summary(league, event_id)
    rosters = summary.get("rosters") or []
    home_team = ""
    for team in rosters:
        if str(team.get("homeAway") or "") == "home":
            home_team = str((team.get("team") or {}).get("displayName") or "")
    if not home_team:
        return {"event_id": event_id, "skipped": "no home team"}

    events = momentum_events(summary, home_team=home_team, include_goals=False)
    if not events:
        return {"event_id": event_id, "skipped": "no pressure events"}
    goals = _goals(summary, home_team)

    pre_goal: list[float] = []
    for t, sign in goals:
        probe = t - lead_seconds
        if probe < 0:
            continue
        # Signed IN FAVOUR OF THE SCORER: a positive value means the side that
        # went on to score was the one on top beforehand.
        pre_goal.append(sign * momentum_at(events, probe, half_life_seconds=half_life))

    control: list[float] = []
    t = lead_seconds
    while t <= 5400.0:
        # A control instant is one where NEITHER side scored inside the horizon.
        if not any(t <= gt <= t + horizon_seconds for gt, _ in goals):
            value = momentum_at(events, t, half_life_seconds=half_life)
            # Both orientations, so the control cannot inherit a bias toward
            # whichever team happened to dominate this match.
            control.append(value)
            control.append(-value)
        t += control_step

    return {
        "event_id": event_id,
        "league": league,
        "home_team": home_team,
        "goals": len(goals),
        "pre_goal": pre_goal,
        "control": control,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--leagues", required=True)
    ap.add_argument("--window", required=True, help="semicolon-separated YYYYMMDD-YYYYMMDD")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--lead-seconds", type=float, default=120.0,
                    help="how far BEFORE the goal to sample momentum")
    ap.add_argument("--horizon-seconds", type=float, default=600.0,
                    help="a control instant must have no goal within this horizon")
    ap.add_argument("--half-life", type=float, default=DEFAULT_HALF_LIFE_SECONDS)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    leagues = [x.strip() for x in args.leagues.split(",") if x.strip()]
    windows = [w.strip() for w in args.window.split(";") if w.strip()]

    pairs: list[tuple[str, str]] = []
    for league in leagues:
        for w in windows:
            try:
                for e in fetch_events(league, date_windows=[w], statuses={"post"}):
                    if e.get("event_id"):
                        pairs.append((league, str(e["event_id"])))
            except Exception as exc:
                print(f"  discovery failed {league} {w}: {type(exc).__name__}: {exc}")
    seen: set[str] = set()
    pairs = [(lg, eid) for lg, eid in pairs if not (eid in seen or seen.add(eid))][: args.limit]

    pre_goal: list[float] = []
    control: list[float] = []
    matches = 0
    for league, event_id in pairs:
        try:
            r = analyse(league, event_id, lead_seconds=args.lead_seconds,
                        horizon_seconds=args.horizon_seconds, half_life=args.half_life)
        except Exception as exc:
            print(f"  failed {league} {event_id}: {type(exc).__name__}: {exc}")
            continue
        if r.get("skipped"):
            continue
        matches += 1
        pre_goal.extend(r["pre_goal"])
        control.extend(r["control"])

    def _stats(xs):
        if not xs:
            return {"n": 0}
        return {
            "n": len(xs),
            "mean": round(statistics.mean(xs), 4),
            "median": round(statistics.median(xs), 4),
            "stdev": round(statistics.pstdev(xs), 4) if len(xs) > 1 else 0.0,
            "pct_positive": round(sum(1 for x in xs if x > 0) / len(xs), 4),
        }

    pg, ct = _stats(pre_goal), _stats(control)
    print(f"matches {matches}   lead {args.lead_seconds:.0f}s   horizon {args.horizon_seconds:.0f}s"
          f"   half-life {args.half_life:.0f}s")
    print()
    print(f"{'':14}{'n':>6}{'mean':>10}{'median':>10}{'stdev':>10}{'% positive':>12}")
    for label, st in (("PRE-GOAL", pg), ("CONTROL", ct)):
        if st["n"]:
            print(f"{label:14}{st['n']:>6}{st['mean']:>10.3f}{st['median']:>10.3f}"
                  f"{st['stdev']:>10.3f}{st['pct_positive']:>12.3f}")
    print()
    if pg["n"] and ct["n"] and pg["stdev"]:
        # Effect size in pooled standard deviations -- a difference of means is
        # unreadable without the spread it sits in.
        pooled = ((pg["stdev"] ** 2 + ct["stdev"] ** 2) / 2) ** 0.5 or 1.0
        d = (pg["mean"] - ct["mean"]) / pooled
        print(f"separation: pre-goal mean - control mean = {pg['mean'] - ct['mean']:+.3f}"
              f"   Cohen's d = {d:+.3f}")
        if abs(d) < 0.2:
            print("VERDICT: NO MEANINGFUL SEPARATION -- momentum is a NARRATOR, not a predictor.")
            print("         Do not wire it into the sim on this evidence.")
        else:
            print("VERDICT: momentum BEFORE a goal is measurably elevated for the side that")
            print("         scores. Worth pursuing -- next step is whether it beats the")
            print("         cutoff-harness baseline, not just whether it separates.")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(
            {"matches": matches, "lead_seconds": args.lead_seconds,
             "horizon_seconds": args.horizon_seconds, "half_life": args.half_life,
             "pre_goal": pg, "control": ct}, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
