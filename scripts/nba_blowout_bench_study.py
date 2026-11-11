"""What happens when the bench comes in during an NBA blowout -- measured from our own archived play-by-play.

Lane `nba-pbp-blowout-bench`, todo #788: the college study (#787, `scripts/college_blowout_bench_study.py`) done for
NBA. READ-ONLY: it reads the nightly `basketball-rotation-stints` tables (per-team lineup stints with points,
starters from the box score, official final scores) and, for Q3, the NBA live re-sim's own tick history
(`nba_source/data/processed/live_resim_history/<date>.jsonl`, kept since 2026-10-16). It writes nothing but its
report.

  Q1  WHEN: starters on the floor (duration-weighted) for the LEADING and the TRAILING team, by lead x minutes left
      in the 4th quarter.
  Q2  EFFECT: both teams' scoring rate in the leading team's 4th-quarter stints, as a ratio to that game's own rate
      over its first 36 minutes (controls for pace), by lead x the leading team's bench level.
  Q3  OUR MODEL: the live re-sim's remaining-points error (actual final total - projected total) on 4th-quarter
      ticks, by lead x the leader's lineup at the tick; by the engine's OWN blowout flag x minutes left; and, for
      scale, every regulation tick by period (a level bias shows in all of them, a blowout miss only late).
  Q4  OVERTIME (todo #789): the re-sim's expected overtime points and, on rows that carry it, its own P(overtime),
      against the game's real overtime, by |lead| x minutes left in the 4th (`q4_overtime`).

NBA geometry: 4 x 12 min = 48. The college study's windows are the game's last quarter of time (10 of 40) against
the rest (30); here that is the 4th quarter (12 of 48) against the first 36 minutes.

The engine's blowout flag (`basketball_engine/engine.py`, set at each period start and at a resume from the live
margin): period >= 3 and |margin| >= `EventSimConfig.blowout_margin` (18), or period >= 4 and |margin| >=
`blowout_q4_margin` (15). Under it the engine scales turnovers by `garbage_time_pace_scale` (0.94) and shot
efficiency by `garbage_time_eff_scale` (0.96); `blowout_bench_rest` (the leader's bench) is OFF in production.

Intervals are game-clustered: a cell's per-game means, mean +- 1.96 sd / sqrt(n_games). Regulation only (48 min);
overtime stints and overtime ticks are dropped, but the final total includes overtime, as the projected total does.
Games whose play-by-play does not reproduce the official score are excluded. Season types default to the ones the
model is graded on (regular, play-in, playoffs): preseason rotations are not game rotations.

    python scripts/nba_blowout_bench_study.py --start 2025-10-21 --end 2026-06-30
    python scripts/nba_blowout_bench_study.py --start 2026-10-20 --end 2026-11-10 --evidence
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

try:  # the college study's helpers: buckets, CSV rows, date range, game-clustered interval
    from scripts.college_blowout_bench_study import LEAD_BUCKETS, _bucket, _ci, _dates, _rows
except ImportError:  # run as a file: scripts/ itself is on sys.path
    from college_blowout_bench_study import LEAD_BUCKETS, _bucket, _ci, _dates, _rows

LEAGUE = "nba"
PERIOD_SECONDS = 720.0
N_PERIODS = 4
GAME_SECONDS = PERIOD_SECONDS * N_PERIODS  # 2880
LATE_SECONDS = PERIOD_SECONDS  # the 4th quarter
BASELINE_SECONDS = GAME_SECONDS - LATE_SECONDS  # a game's own pace: its first 36 minutes

LEFT_BUCKETS = (("12-10", 600, 720), ("10-8", 480, 600), ("8-6", 360, 480), ("6-4", 240, 360), ("4-2", 120, 240),
                ("2-0", 0, 120))
HALF_BUCKETS = (("12-6", 360, 720), ("6-0", 0, 360))
OT_LEAD_BUCKETS = (("0-2", 0, 3), ("3-5", 3, 6), ("6-9", 6, 10), ("10+", 10, 10_000))
# History rows' `h2` segment carries every overtime only from `3d376da7c` (#762), loaded on live-odds-worker at
# 2026-11-06 15:51:30Z (deploys.md). Before it `h2` was regulation-only, so `h2 - q3 - q4` read 0 on every row
# (measured on the fleet: 0 of 578 rows on 11-04/11-05 above 0; 256 of 403 on 11-06).
H2_CARRIES_OT_SINCE = dt.datetime(2026, 11, 6, 15, 51, 30, tzinfo=dt.timezone.utc)

# basketball_engine/engine.py EventSimConfig defaults; tests/test_nba_blowout_bench_study.py pins them to the engine.
ENGINE_BLOWOUT_MARGIN = 18  # from the 3rd period (LeagueParams.second_half_first_period)
ENGINE_BLOWOUT_Q4_MARGIN = 15
ENGINE_SECOND_HALF_FIRST_PERIOD = 3

DEFAULT_SEASON_TYPES = ("regular", "play-in", "playoffs")
_TRUE = ("1", "True", "true")


def engine_blowout(period: int, margin: float) -> bool:
    """The flag the engine's resumed period runs with, from the live margin at the tick."""
    lead = abs(margin)
    return (period >= N_PERIODS and lead >= ENGINE_BLOWOUT_Q4_MARGIN) or (
        period >= ENGINE_SECOND_HALF_FIRST_PERIOD and lead >= ENGINE_BLOWOUT_MARGIN)


def _bench_level(starters_on: int) -> str:
    return "bench<=1" if starters_on <= 1 else "starters>=3" if starters_on >= 3 else "mixed2"


def load_team_stints(root: Path, days: Iterable[str], season_types: Iterable[str] = DEFAULT_SEASON_TYPES):
    """({event_id: {team: [stint, ...]}}, {event_id: final total incl. OT}) for score-matched games of the given
    season types. Each stint carries the team's margin at its start, its starters on the floor, and both teams'
    points in it. Regulation only."""
    base = root / f"{LEAGUE}_source" / "data" / "processed" / "rotation_stints"
    wanted = set(season_types)
    games: dict[str, dict[str, list[dict[str, Any]]]] = {}
    finals: dict[str, float] = {}
    for day in days:
        matched: set[str] = set()
        for r in _rows(base / f"games_{day}.csv"):
            if str(r.get("score_match")) not in _TRUE or r.get("season_type") not in wanted:
                continue
            try:
                total = float(r["official_home"]) + float(r["official_away"])
            except (KeyError, TypeError, ValueError):
                continue
            matched.add(r["event_id"])
            finals[r["event_id"]] = total
        if not matched:
            continue
        starters: dict[tuple[str, str], set[str]] = defaultdict(set)
        for r in _rows(base / f"player_checks_{day}.csv"):
            if r.get("event_id") in matched and str(r.get("starter")) in _TRUE:
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
                    stop = min(end, GAME_SECONDS)
                    out.append({"start": start, "end": stop, "margin": margin, "starters_on": len(on & five),
                                "points": pf + pa, "dur": stop - start})
                margin += pf - pa
            if out:
                games.setdefault(event_id, {})[team] = out
    finals = {k: v for k, v in finals.items() if k in games}
    return games, finals


def q1_when(games) -> dict[str, float]:
    """Starters on the floor, leader vs trailer, by |lead| at stint start x minutes left, weighted by the seconds of
    each stint INSIDE each minutes-left bucket. (The college study files a whole stint under its start; NBA stints
    are cut at every period, so a 4th-quarter stint starts at exactly 12:00 left, which that rule would drop.)"""
    acc: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for teams in games.values():
        for stints in teams.values():
            for s in stints:
                if s["margin"] == 0:
                    continue
                role = "leader" if s["margin"] > 0 else "trailer"
                lead = _bucket(abs(s["margin"]), LEAD_BUCKETS)
                if not lead:
                    continue
                for left, lo, hi in LEFT_BUCKETS:
                    overlap = min(s["end"], GAME_SECONDS - lo) - max(s["start"], GAME_SECONDS - hi)
                    if overlap > 0:
                        cell = acc[(role, lead, left)]
                        cell[0] += s["starters_on"] * overlap
                        cell[1] += overlap
    return {f"{role}|{lead}|{left}": round(v[0] / v[1], 2) for (role, lead, left), v in sorted(acc.items()) if v[1] > 0}


def q2_effect(games) -> dict[str, Any]:
    """Scoring-rate ratio (stint points/min over the game's own first-36-min rate), the leader's 4th-quarter stints,
    by lead x bench."""
    per_game: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for event_id, teams in games.items():
        any_team = next(iter(teams.values()))  # one team's stints carry every point (pts_for + pts_against)
        base_pts = sum(s["points"] * max(0.0, min(s["end"], BASELINE_SECONDS) - s["start"]) / s["dur"]
                       for s in any_team if s["start"] < BASELINE_SECONDS)
        base_rate = base_pts / (BASELINE_SECONDS / 60.0)
        if base_rate <= 0:
            continue
        for stints in teams.values():
            for s in stints:
                if s["margin"] <= 0 or GAME_SECONDS - s["start"] > LATE_SECONDS:
                    continue
                cell = per_game[(_bucket(s["margin"], LEAD_BUCKETS), _bench_level(s["starters_on"]))][event_id]
                cell[0] += s["points"]
                cell[1] += s["dur"] / 60.0 * base_rate
    out = {}
    for (lead, bench), by_game in sorted(per_game.items()):
        mean, half, n = _ci([pts / expected for pts, expected in by_game.values() if expected > 0])
        out[f"{lead}|{bench}"] = {"ratio": mean, "ci95": half, "games": n}
    return out


def history_ticks(root: Path, days: Iterable[str]) -> Iterable[dict[str, Any]]:
    """Fresh live re-sim rows: carried lanes and refusals are not measurements."""
    base = root / f"{LEAGUE}_source" / "data" / "processed" / "live_resim_history"
    for day in days:
        path = base / f"{day}.jsonl"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("source") == "live_resim" and not r.get("refusal") and not r.get("carried_forward"):
                    yield r


def _cells_out(cells) -> dict[str, Any]:
    out = {}
    for key, by_game in sorted(cells.items()):
        mean, half, n = _ci([statistics.fmean(v) for v in by_game.values()])
        out["|".join(key)] = {"error": mean, "ci95": half, "games": n, "ticks": sum(len(v) for v in by_game.values())}
    return out


def q3_model(games, finals, ticks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Live re-sim remaining-points error (actual - projected) by lead x the leader's lineup (4th quarter), by the
    engine's blowout flag x minutes left (4th quarter), and by period (every regulation tick)."""
    by_bench: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    by_flag: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    by_period: dict[tuple[str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in ticks:
        eid = str(r.get("event_id"))
        if eid not in finals or eid not in games:
            continue
        h, a, per, clk, tot = r.get("home_score"), r.get("away_score"), r.get("period"), r.get("clock_s"), r.get("total")
        if None in (h, a, per, clk, tot) or not 1 <= int(per) <= N_PERIODS:
            continue
        err = finals[eid] - float(tot)  # (actual remaining) - (projected remaining): the score so far cancels
        by_period[(f"Q{int(per)}",)][eid].append(err)
        elapsed = (int(per) - 1) * PERIOD_SECONDS + (PERIOD_SECONDS - float(clk))
        left = GAME_SECONDS - elapsed
        if left >= LATE_SECONDS or left < 0:
            continue
        lead = abs(h - a)
        leader = None
        for stints in games[eid].values():
            cover = next((x for x in stints if x["start"] <= elapsed < x["end"]), None)
            if cover and cover["margin"] > 0:
                leader = cover
        bench = "close" if lead < 10 or leader is None else _bench_level(leader["starters_on"])
        by_bench[(_bucket(lead, LEAD_BUCKETS) or "?", bench)][eid].append(err)
        flag = "engine_blowout" if engine_blowout(int(per), h - a) else "no_flag"
        by_flag[(flag, _bucket(left, HALF_BUCKETS) or "?")][eid].append(err)
    return {"by_lead_bench": _cells_out(by_bench), "by_engine_flag": _cells_out(by_flag),
            "by_period_all_ticks": _cells_out(by_period)}


def _regulation_total(teams) -> float:
    any_team = next(iter(teams.values()))  # one team's stints carry every point (pts_for + pts_against)
    return sum(s["points"] for s in any_team)


def _overtime_cell(r: dict[str, Any], per: int, left: float) -> tuple[str, str]:
    if per < N_PERIODS:
        return ("Q1-Q3", "all")
    lead = abs(float(r["home_score"]) - float(r["away_score"]))
    # A tick AT the 4th-quarter tip has exactly 12:00 left, the top bucket's open end: it belongs to 12-6.
    return (_bucket(lead, OT_LEAD_BUCKETS) or "?", _bucket(min(left, LATE_SECONDS - 1e-6), HALF_BUCKETS) or "?")


def _tick_time(r: dict[str, Any]) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(str(r.get("t")).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


def q4_overtime(games, finals, ticks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Does the re-sim give overtime the right weight? (todo #789; #788 found its whole late close-game miss was the
    8 overtime games of 160.) Two readings per regulation tick, game-clustered, by |lead| x minutes left in the 4th
    (earlier ticks in one cell for scale):

      expected_ot_points  the re-sim's expected overtime points, `h2 - q3 - q4` of the row's segment means (h2 is
                          q3 + q4 + every overtime, over the same draws), against the game's real overtime points
                          (official final - the play-by-play's regulation total). Rows since H2_CARRIES_OT_SINCE only.
      p_ot                the re-sim's own P(overtime) (`p_ot`, the share of draws level after regulation), against
                          whether the game went to overtime. Rows carrying `p_ot` only (#789's field).
    `error` is actual - expected: positive = the re-sim under-weights overtime."""
    pts: dict[tuple[str, str], dict[str, list[tuple[float, float]]]] = defaultdict(lambda: defaultdict(list))
    prob: dict[tuple[str, str], dict[str, list[tuple[float, float]]]] = defaultdict(lambda: defaultdict(list))
    for r in ticks:
        eid = str(r.get("event_id"))
        if eid not in finals or eid not in games:
            continue
        per, clk = r.get("period"), r.get("clock_s")
        if None in (per, clk, r.get("home_score"), r.get("away_score")) or not 1 <= int(per) <= N_PERIODS:
            continue
        left = GAME_SECONDS - ((int(per) - 1) * PERIOD_SECONDS + (PERIOD_SECONDS - float(clk)))
        if not 0 <= left <= GAME_SECONDS:
            continue
        cell = _overtime_cell(r, int(per), left)
        actual = finals[eid] - _regulation_total(games[eid])
        seg = r.get("segments") or {}
        when = _tick_time(r)
        if when is not None and when >= H2_CARRIES_OT_SINCE and all(seg.get(k) is not None for k in ("h2", "q3", "q4")):
            pts[cell][eid].append((float(seg["h2"]) - float(seg["q3"]) - float(seg["q4"]), actual))
        if r.get("p_ot") is not None:
            prob[cell][eid].append((float(r["p_ot"]), 1.0 if actual > 0 else 0.0))

    def out(cells, label: str) -> dict[str, Any]:
        res = {}
        for key, by_game in sorted(cells.items()):
            exp = [statistics.fmean(e for e, _ in v) for v in by_game.values()]
            act = [v[0][1] for v in by_game.values()]
            mean, half, n = _ci([a - e for a, e in zip(act, exp)])
            res["|".join(key)] = {label: round(statistics.fmean(exp), 3), "actual": round(statistics.fmean(act), 3),
                                  "error": mean, "ci95": half, "games": n,
                                  "ot_games": sum(1 for a in act if a > 0),
                                  "ticks": sum(len(v) for v in by_game.values())}
        return res

    return {"expected_ot_points": out(pts, "expected"), "p_ot": out(prob, "p_ot")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT", ""))
    ap.add_argument("--season-types", default=",".join(DEFAULT_SEASON_TYPES))
    ap.add_argument("--evidence", action="store_true", help="also Q3 (live re-sim error), from live_resim_history/")
    args = ap.parse_args(argv)
    root = Path(args.data_root)
    start, end = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    days = list(_dates(start, end))
    games, finals = load_team_stints(root, days, [s for s in args.season_types.split(",") if s])
    report: dict[str, Any] = {"league": LEAGUE, "start": args.start, "end": args.end, "games": len(games),
                              "q1_starters_on_floor": q1_when(games), "q2_scoring_rate_ratio": q2_effect(games)}
    if args.evidence:
        # A game still live at midnight Central has its post-roll ticks in the NEXT date's file (#776).
        history_days = list(_dates(start, end + dt.timedelta(days=1)))
        ticks = list(history_ticks(root, history_days))
        report["q3_live_resim_remaining_error"] = q3_model(games, finals, ticks)
        report["q4_overtime"] = q4_overtime(games, finals, ticks)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
