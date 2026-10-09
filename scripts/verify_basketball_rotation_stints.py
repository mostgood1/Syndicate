"""Grade the rotation-stints producer against the official box score, per league.

Reads the dated `games_<date>.csv` / `player_checks_<date>.csv` that `build_basketball_rotation_stints.py`
writes and reports, per league and phase:
  * games whose play-by-play score (sum of scoring plays) equals ESPN's official final;
  * player-games whose stint minutes are within 1 minute of the box minutes (ESPN reports whole minutes);
  * play-by-play personal fouls equal to the box PF;
and lists every miss. Games with no play-by-play at all are reported separately, never as matches.

Exit 1 when a gate fails: any score mismatch among games with plays, or < 95% of player-games within 1 min.

    python scripts/verify_basketball_rotation_stints.py --league nba,wnba,ncaab
    python scripts/verify_basketball_rotation_stints.py --league nba --start 2026-04-01 --end 2026-06-30 --json out.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.build_basketball_rotation_stints import LEAGUES, stints_dir  # noqa: E402

MINUTES_GATE = 0.95


def _rows(paths: list[Path]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for path in paths:
        with path.open(newline="", encoding="utf-8") as handle:
            out.extend(csv.DictReader(handle))
    return out


def _in_range(path: Path, start: str, end: str) -> bool:
    date = path.stem.rsplit("_", 1)[-1]
    return (not start or date >= start) and (not end or date <= end)


def grade(league: str, *, start: str = "", end: str = "", max_misses: int = 40) -> dict[str, Any]:
    base = stints_dir(league)
    games = _rows([p for p in sorted(base.glob("games_*.csv")) if _in_range(p, start, end)])
    checks = _rows([p for p in sorted(base.glob("player_checks_*.csv")) if _in_range(p, start, end)])
    by_phase: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(int))
    score_misses, minute_misses, pf_misses = [], [], []
    no_plays = []
    played = {g["event_id"] for g in games if int(g.get("plays") or 0) > 0}
    for g in games:
        ph = by_phase[g["season_type"]]
        if int(g.get("plays") or 0) == 0:
            ph["games_no_pbp"] += 1
            no_plays.append(g["event_id"])
            continue
        ph["games"] += 1
        if g["score_match"] == "1":
            ph["score_match"] += 1
        else:
            score_misses.append({k: g[k] for k in ("date", "event_id", "home", "away", "official_home", "official_away", "pbp_home", "pbp_away", "anomalies")})
        ph["anomaly_games"] += int(int(g.get("anomalies") or 0) > 0)
    for c in checks:
        if c["event_id"] not in played or c.get("within_1", "") == "":
            continue
        ph = by_phase[c["season_type"]]
        ph["player_games"] += 1
        if c["within_1"] == "1":
            ph["within_1"] += 1
        else:
            minute_misses.append({k: c[k] for k in ("date", "event_id", "team", "player_name", "starter", "box_minutes", "stint_minutes", "minutes_diff")})
        if c.get("box_pf") not in ("", None):
            ph["pf_checked"] += 1
            if str(c["box_pf"]) == str(c["pbp_pf"]):
                ph["pf_match"] += 1
            else:
                pf_misses.append({k: c[k] for k in ("date", "event_id", "team", "player_name", "box_pf", "pbp_pf")})
    totals: dict[str, int] = defaultdict(int)
    for ph in by_phase.values():
        for k, v in ph.items():
            totals[k] += v
    rate = (totals["within_1"] / totals["player_games"]) if totals["player_games"] else None
    gates = {
        "score_all_match": totals["games"] > 0 and totals["score_match"] == totals["games"],
        "minutes_within_1_ge_95pct": rate is not None and rate >= MINUTES_GATE,
    }
    minute_misses.sort(key=lambda r: -abs(float(r["minutes_diff"] or 0)))
    return {
        "league": league, "range": [start or None, end or None],
        "totals": dict(totals), "by_phase": {k: dict(v) for k, v in sorted(by_phase.items())},
        "minutes_within_1_rate": round(rate, 4) if rate is not None else None,
        "pf_match_rate": round(totals["pf_match"] / totals["pf_checked"], 4) if totals["pf_checked"] else None,
        "gates": gates, "score_misses": score_misses[:max_misses], "minute_misses": minute_misses[:max_misses],
        "minute_misses_n": len(minute_misses), "pf_misses_n": len(pf_misses), "pf_misses": pf_misses[:10],
        "no_pbp_events": no_plays[:max_misses], "no_pbp_n": len(no_plays),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--league", default=",".join(LEAGUES))
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    ap.add_argument("--json", default="", help="write the full report here")
    args = ap.parse_args(argv)
    reports = [grade(lg.strip(), start=args.start, end=args.end) for lg in args.league.split(",") if lg.strip()]
    for r in reports:
        t = r["totals"]
        print(f"{r['league']}: games {t.get('games', 0)} score_match {t.get('score_match', 0)} | player-games {t.get('player_games', 0)} "
              f"within_1 {t.get('within_1', 0)} ({r['minutes_within_1_rate']}) | pf {r['pf_match_rate']} | no_pbp {r['no_pbp_n']} | gates {r['gates']}")
        for phase, ph in r["by_phase"].items():
            print(f"    {phase}: {ph}")
    if args.json:
        Path(args.json).write_text(json.dumps(reports, indent=1), encoding="utf-8")
    return 0 if all(all(r["gates"].values()) for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
