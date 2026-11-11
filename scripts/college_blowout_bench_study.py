"""What happens when the bench comes in during a college blowout -- measured from our own archived play-by-play.

Lane `college-pbp-blowout-bench`, todo #787. User 2026-11-11: "are we saving game shape data? 3 games today have
already been wrong badly ..." and "the pbp should be looked at...and tendencies for when bench players come into a
blowout". READ-ONLY: it reads the nightly `basketball-rotation-stints` tables (per-team lineup stints with points,
starters from the box score) and, for Q3, the live re-sim's evidence log. It writes nothing but its own report.

  Q1  WHEN: starters on the floor (duration-weighted) for the LEADING and the TRAILING team, by lead x minutes left.
  Q2  EFFECT: both teams' scoring rate in a stint, as a ratio to that game's own rate over the first 30 minutes
      (controls for pace), by lead x the leading team's bench level (<= 1 starter on vs >= 3).
  Q3  OUR MODEL: the live re-sim's remaining-points error (actual - projected) on ticks with < 10 min left, by lead,
      split by whether the leading team's bench was on the floor at the tick (needs `live_evidence/` + stints).

Intervals are game-clustered: a cell's per-game means, mean +- 1.96 sd / sqrt(n_games). Regulation only (40 min);
overtime stints are dropped. Games whose play-by-play does not reproduce the official score are excluded.

    python scripts/college_blowout_bench_study.py --league ncaab --start 2025-11-01 --end 2026-04-15
    python scripts/college_blowout_bench_study.py --league ncaab --start 2026-11-01 --end 2026-11-10 --evidence
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

GAME_SECONDS = 2400.0  # 40 minutes, men's (2 x 20) and women's (4 x 10) alike
PERIOD_SECONDS = {"ncaab": 1200.0, "wncaab": 600.0}
BASELINE_SECONDS = 1800.0  # a game's own pace: its first 30 minutes

LEAD_BUCKETS = (("<10", 0, 10), ("10-14", 10, 15), ("15-19", 15, 20), ("20-24", 20, 25), ("25+", 25, 10_000))
LEFT_BUCKETS = (("10-8", 480, 600), ("8-6", 360, 480), ("6-4", 240, 360), ("4-2", 120, 240), ("2-0", 0, 120))


def _bucket(value: float, buckets) -> str | None:
    for name, lo, hi in buckets:
        if lo <= value < hi:
            return name
    return None


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _dates(start: dt.date, end: dt.date) -> Iterable[str]:
    day = start
    while day <= end:
        yield day.isoformat()
        day += dt.timedelta(days=1)


def load_team_stints(root: Path, league: str, days: Iterable[str]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """{event_id: {team: [stint, ...]}} for score-matched games, each stint carrying the team's margin at its start,
    starters on the floor, and both teams' points in it. Regulation only."""
    base = root / f"{league}_source" / "data" / "processed" / "rotation_stints"
    games: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for day in days:
        matched = {r["event_id"] for r in _rows(base / f"games_{day}.csv") if str(r.get("score_match")) in ("1", "True", "true")}
        if not matched:
            continue
        starters: dict[tuple[str, str], set[str]] = defaultdict(set)
        for r in _rows(base / f"player_checks_{day}.csv"):
            if r.get("event_id") in matched and str(r.get("starter")) in ("1", "True", "true"):
                starters[(r["event_id"], r["team"])].add(str(r["player_id"]))
        by_team: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for r in _rows(base / f"stints_{day}.csv"):
            if r.get("event_id") in matched:
                by_team[(r["event_id"], r["team"])].append(r)
        for (event_id, team), rows in by_team.items():
            five = starters.get((event_id, team))
            if not five or len(five) < 5:
                continue
            margin = 0.0
            out = []
            for r in sorted(rows, key=lambda x: float(x["start_sec"])):
                start, end = float(r["start_sec"]), float(r["end_sec"])
                pf, pa = float(r["pts_for"] or 0), float(r["pts_against"] or 0)
                if start < GAME_SECONDS and end > start:
                    on = {p for p in str(r["lineup_player_ids"] or "").split(";") if p}
                    out.append({"start": start, "end": min(end, GAME_SECONDS), "margin": margin,
                                "starters_on": len(on & five), "points": pf + pa, "dur": min(end, GAME_SECONDS) - start})
                margin += pf - pa
            if out:
                games.setdefault(event_id, {})[team] = out
    return games


def _ci(values: list[float]) -> tuple[float | None, float | None, int]:
    if not values:
        return None, None, 0
    mean = statistics.fmean(values)
    half = 1.96 * statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else float("nan")
    return round(mean, 3), (round(half, 3) if half == half else None), len(values)


def q1_when(games) -> dict[str, Any]:
    """Duration-weighted starters on the floor, leader vs trailer, by |lead| x minutes left at stint start."""
    acc: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for teams in games.values():
        for stints in teams.values():
            for s in stints:
                if s["margin"] == 0:
                    continue
                role = "leader" if s["margin"] > 0 else "trailer"
                lead = _bucket(abs(s["margin"]), LEAD_BUCKETS)
                left = _bucket(GAME_SECONDS - s["start"], LEFT_BUCKETS)
                if lead and left:
                    cell = acc[(role, lead, left)]
                    cell[0] += s["starters_on"] * s["dur"]
                    cell[1] += s["dur"]
    return {f"{role}|{lead}|{left}": round(v[0] / v[1], 2) for (role, lead, left), v in sorted(acc.items()) if v[1] > 0}


def q2_effect(games) -> dict[str, Any]:
    """Scoring-rate ratio (stint points/min over the game's own first-30-min rate), leader's stints, by lead x bench."""
    per_game: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for event_id, teams in games.items():
        any_team = next(iter(teams.values()))
        base_pts = sum(s["points"] * max(0.0, min(s["end"], BASELINE_SECONDS) - s["start"]) / s["dur"]
                       for s in any_team if s["start"] < BASELINE_SECONDS)
        base_rate = base_pts / (BASELINE_SECONDS / 60.0)
        if base_rate <= 0:
            continue
        for stints in teams.values():
            for s in stints:
                if s["margin"] <= 0 or GAME_SECONDS - s["start"] > 600:
                    continue  # the leading team's stints, last 10 minutes
                lead = _bucket(s["margin"], LEAD_BUCKETS)
                bench = "bench<=1" if s["starters_on"] <= 1 else "starters>=3" if s["starters_on"] >= 3 else "mixed2"
                cell = per_game[(lead, bench)][event_id]
                cell[0] += s["points"]
                cell[1] += s["dur"] / 60.0 * base_rate
    out = {}
    for (lead, bench), by_game in sorted(per_game.items()):
        ratios = [pts / expected for pts, expected in by_game.values() if expected > 0]
        mean, half, n = _ci(ratios)
        out[f"{lead}|{bench}"] = {"ratio": mean, "ci95": half, "games": n}
    return out


def q3_model(games, root: Path, league: str, days: Iterable[str]) -> dict[str, Any]:
    """Live re-sim remaining-points error on ticks with < 10 min left, by lead x the leader's bench at the tick."""
    period_len = PERIOD_SECONDS[league]
    nper = int(GAME_SECONDS // period_len)
    cells: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for day in days:
        ev = root / "live_evidence" / league / f"{day}.jsonl"
        sb = root / f"{league}_source" / "data" / "scoreboard" / f"scoreboard_{day}.json"
        if not (ev.is_file() and sb.is_file()):
            continue
        board = json.loads(sb.read_text(encoding="utf-8"))
        finals, abbr = {}, {}
        for g in (board.get("games") if isinstance(board, dict) else board) or []:
            if (g.get("live_state") or {}).get("final"):
                h, a = (g.get("home") or {}), (g.get("away") or {})
                if isinstance(h.get("score"), (int, float)) and isinstance(a.get("score"), (int, float)):
                    finals[str(g.get("event_id"))] = h["score"] + a["score"]
        with ev.open(encoding="utf-8") as handle:
            for line in handle:
                r = json.loads(line)
                eid = str(r.get("event_id"))
                if r.get("source") != "live_resim" or r.get("refusal") or eid not in finals or eid not in games:
                    continue
                s, p = r.get("state") or {}, r.get("proj") or {}
                h, a, per, clk, tot = s.get("homeScore"), s.get("awayScore"), s.get("period"), s.get("clockSeconds"), p.get("total")
                if None in (h, a, per, clk, tot) or per > nper:
                    continue
                elapsed = (per - 1) * period_len + (period_len - clk)
                if GAME_SECONDS - elapsed >= 600:
                    continue
                lead = abs(h - a)
                leader_stints = None
                for stints in games[eid].values():
                    cover = next((x for x in stints if x["start"] <= elapsed < x["end"]), None)
                    if cover and cover["margin"] > 0:
                        leader_stints = cover
                bench = "close" if lead < 10 or leader_stints is None else (
                    "bench<=1" if leader_stints["starters_on"] <= 1 else "starters>=3" if leader_stints["starters_on"] >= 3 else "mixed2")
                err = (finals[eid] - (h + a)) - (tot - (h + a))
                cells[(_bucket(lead, LEAD_BUCKETS) or "?", bench)][eid].append(err)
    out = {}
    for (lead, bench), by_game in sorted(cells.items()):
        mean, half, n = _ci([statistics.fmean(v) for v in by_game.values()])
        out[f"{lead}|{bench}"] = {"error": mean, "ci95": half, "games": n, "ticks": sum(len(v) for v in by_game.values())}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--league", choices=("ncaab", "wncaab"), required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT", ""))
    ap.add_argument("--evidence", action="store_true", help="also Q3 (live re-sim error), from live_evidence/")
    args = ap.parse_args(argv)
    root = Path(args.data_root)
    days = list(_dates(dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)))
    games = load_team_stints(root, args.league, days)
    report: dict[str, Any] = {"league": args.league, "start": args.start, "end": args.end, "games": len(games),
                              "q1_starters_on_floor": q1_when(games), "q2_scoring_rate_ratio": q2_effect(games)}
    if args.evidence:
        report["q3_live_resim_remaining_error"] = q3_model(games, root, args.league, days)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
