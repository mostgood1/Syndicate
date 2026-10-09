"""Game-situation TARGETS measured from real play-by-play (P3 of docs/ai_context/basketball_live_native_plan.md,
lane `nba-native-live-resim`).

Each P3 mechanism (score-effect reversion, asymmetric garbage time, end-of-game fouling / clock management,
foul trouble, bench-rotation intervals) must reproduce a number measured HERE, on real games, per population
(preseason / regular / postseason never pooled), with n and a game-resampled 95% CI. A mechanism whose target
is not distinguishable from zero is not added (lane falsification rule).

All rates are SECONDS-WEIGHTED between consecutive pbp rows and attributed to the state (margin, leader,
on-floor fives) holding at the START of each interval. Scoring is credited to the scoring side from the
cumulative score delta, so And-1s and FT trips need no special-casing.

On-floor fives are inferred from pbp (period starters = players who act before they are subbed in, topped
up from the previous period's closing five, Q1 from the box-score starters). The inference is VALIDATED
against official box-score minutes and the report carries that error, so a target resting on it says how
good its input was.

Usage:
  py -3 scripts/basketball_live_situation_targets.py --games C:/tmp/nba_live_bt/games_nba.jsonl \
      --lines-cache C:/tmp/nba_bt/out/cache/oddsapi_hist/games --out C:/tmp/nba_live_bt/targets
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import basketball_live_checkpoint_backtest as bt  # noqa: E402

SEED = 20261009


# ----------------------------------------------------------------------------------------------- on-floor inference

@dataclasses.dataclass
class Interval:
    """[t0, t1) in elapsed game seconds, with the state at t0."""

    t0: float
    t1: float
    period: int
    clock_s: float  # clock at t0
    home: int
    away: int
    floor: Dict[str, Set[str]]

    @property
    def dt(self) -> float:
        return self.t1 - self.t0


def infer_floor(game: bt.PbpGame) -> Tuple[List[Interval], Dict[str, Any]]:
    """Walk the pbp, maintaining each side's five. Returns intervals plus inference quality."""
    side = game.athlete_side
    plays = game.plays
    periods = sorted({p.period for p in plays})
    prev_close: Dict[str, Set[str]] = {s: set(game.starters.get(s, [])) for s in ("home", "away")}
    period_starters: Dict[int, Dict[str, Set[str]]] = {}
    for q in periods:
        rows = [p for p in plays if p.period == q]
        start: Dict[str, Set[str]] = {"home": set(), "away": set()}
        entered: Set[str] = set()
        for p in rows:
            if p.kind == "sub":
                if p.p2 and p.p2 not in entered and p.p2 in side:
                    start[side[p.p2]].add(p.p2)
                if p.p1:
                    entered.add(p.p1)
                continue
            for pid in (p.p1, p.p2):
                if pid and pid not in entered and pid in side:
                    start[side[pid]].add(pid)
        for s in ("home", "away"):
            if q == 1 and len(game.starters.get(s, [])) == 5:
                start[s] = set(game.starters[s])
            if len(start[s]) < 5:
                for pid in sorted(prev_close[s]):
                    if len(start[s]) >= 5:
                        break
                    if pid not in entered:
                        start[s].add(pid)
        period_starters[q] = {s: set(v) for s, v in start.items()}
        cur = {s: set(v) for s, v in start.items()}
        for p in rows:
            if p.kind == "sub" and p.team in cur:
                cur[p.team].discard(p.p2)
                if p.p1:
                    cur[p.team].add(p.p1)
        prev_close = cur

    intervals: List[Interval] = []
    cur = {s: set(v) for s, v in period_starters[periods[0]].items()}
    last_period = periods[0]
    home = away = 0
    for i, p in enumerate(plays):
        if p.period != last_period:
            cur = {s: set(v) for s, v in period_starters[p.period].items()}
            last_period = p.period
        nxt_t = plays[i + 1].elapsed_s if i + 1 < len(plays) and plays[i + 1].period == p.period else None
        if p.kind == "sub" and p.team in cur:
            cur[p.team].discard(p.p2)
            if p.p1:
                cur[p.team].add(p.p1)
        home, away = p.home, p.away
        t1 = nxt_t
        if t1 is None:
            rules = bt.LEAGUES[game.league]
            t1 = bt.elapsed_seconds(rules, p.period, 0.0)
        if t1 > p.elapsed_s:
            intervals.append(Interval(p.elapsed_s, t1, p.period, p.clock_s, home, away, {s: set(v) for s, v in cur.items()}))

    secs: Dict[str, float] = defaultdict(float)
    bad_fives = 0
    for iv in intervals:
        for s in ("home", "away"):
            if len(iv.floor[s]) != 5:
                bad_fives += 1
            for pid in iv.floor[s]:
                secs[pid] += iv.dt
    errs = [abs(secs.get(pid, 0.0) / 60.0 - m) for pid, m in game.box_minutes.items()]
    quality = {
        "minutes_mae": statistics.fmean(errs) if errs else None,
        "minutes_max_err": max(errs) if errs else None,
        "intervals": len(intervals),
        "intervals_not_five": bad_fives,
    }
    return intervals, quality


# ----------------------------------------------------------------------------------------------- stats helpers

def ols_slope(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def boot(units: Sequence[Any], stat: Callable[[Sequence[Any]], Optional[float]], reps: int = 1000,
         seed: int = SEED) -> Dict[str, Any]:
    """Point estimate + percentile 95% CI, resampling GAMES (units)."""
    est = stat(units)
    if est is None or not units:
        return {"n": len(units), "est": None, "ci95": None}
    rng = random.Random(seed)
    n = len(units)
    vals = []
    for _ in range(reps):
        v = stat([units[rng.randrange(n)] for _ in range(n)])
        if v is not None and math.isfinite(v):
            vals.append(v)
    vals.sort()
    if not vals:
        return {"n": n, "est": est, "ci95": None}
    return {"n": n, "est": est, "ci95": [vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]]}


def _ratio(num_key: str, den_key: str, scale: float = 1.0) -> Callable[[Sequence[Dict[str, float]]], Optional[float]]:
    def f(units: Sequence[Dict[str, float]]) -> Optional[float]:
        den = sum(u.get(den_key, 0.0) for u in units)
        return None if den <= 0 else scale * sum(u.get(num_key, 0.0) for u in units) / den
    return f


def _diff(a: Callable, b: Callable) -> Callable:
    def f(units):
        x, y = a(units), b(units)
        return None if x is None or y is None else x - y
    return f


# ----------------------------------------------------------------------------------------------- A. score effects

def score_effect(games: Sequence[bt.PbpGame], spreads: Dict[str, float]) -> Dict[str, Any]:
    """Line-adjusted reversion. Each segment's margin minus its pro-rata share of the expected margin (-spread).

    Slopes reported:
      h2_on_h1           regulation H2 margin on H1 margin (the plan's -0.174 reference)
      q4_on_thru_q3      Q4 margin on the margin entering Q4
      rest_on_now@cp     rest-of-REGULATION margin on margin at each live checkpoint (what a live model needs)
      total_rest_on_now@cp  same for TOTAL points vs the pregame total (pace persistence; positive = persists)
    """
    out: Dict[str, Any] = {}
    rows = []
    for g in games:
        sp = spreads.get(g.event_id)
        if sp is None or len(g.period_points) < 4:
            continue
        exp_m = -sp
        q = [h - a for h, a in g.period_points[:4]]
        rows.append({"h1": q[0] + q[1] - 0.5 * exp_m, "h2": q[2] + q[3] - 0.5 * exp_m,
                     "thru3": q[0] + q[1] + q[2] - 0.75 * exp_m, "q4": q[3] - 0.25 * exp_m})

    def slope(xk, yk):
        return lambda us: ols_slope([u[xk] for u in us], [u[yk] for u in us])

    out["h2_on_h1"] = boot(rows, slope("h1", "h2"))
    out["q4_on_thru_q3"] = boot(rows, slope("thru3", "q4"))
    return out


def checkpoint_reversion(games: Sequence[bt.PbpGame], pregame: Dict[str, Tuple[Optional[float], Optional[float]]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for cp in bt.CHECKPOINTS:
        mrows, trows = [], []
        for g in games:
            sp, tot = pregame.get(g.event_id, (None, None))
            st = bt.state_at(g, cp)
            if st is None or not bt.state_is_consistent(g, st):
                continue
            rules = bt.LEAGUES[g.league]
            f_now = st.elapsed_s / rules.regulation_seconds
            reg = g.period_points[: rules.periods]
            reg_h, reg_a = sum(h for h, _ in reg), sum(a for _, a in reg)
            if sp is not None:
                exp_m = -sp
                mrows.append({"x": st.margin - f_now * exp_m, "y": (reg_h - reg_a - st.margin) - (1 - f_now) * exp_m})
            if tot is not None:
                trows.append({"x": st.total - f_now * tot, "y": (reg_h + reg_a - st.total) - (1 - f_now) * tot})
        sl = lambda us: ols_slope([u["x"] for u in us], [u["y"] for u in us])  # noqa: E731
        out[f"margin_rest_on_now@{cp}"] = boot(mrows, sl)
        out[f"total_rest_on_now@{cp}"] = boot(trows, sl)
    return out


# ----------------------------------------------------------------------------------------------- B/C. Q4 situations

MARGIN_BUCKETS = ((0, 5, "0-5"), (6, 10, "6-10"), (11, 15, "11-15"), (16, 20, "16-20"), (21, 999, "21+"))
TRAIL_BUCKETS = ((0, 0, "tied"), (1, 3, "1-3"), (4, 6, "4-6"), (7, 10, "7-10"), (11, 999, "11+"))


def _bucket(m: int, buckets) -> Optional[str]:
    for lo, hi, name in buckets:
        if lo <= m <= hi:
            return name
    return None


def q4_units(game: bt.PbpGame, intervals: List[Interval]) -> Dict[str, Dict[str, float]]:
    """Per game, per (window, |margin| bucket): seconds, leader/trailer starters-seconds, points, poss parts, fouls."""
    rules = bt.LEAGUES[game.league]
    starters = {s: set(game.starters.get(s, [])) for s in ("home", "away")}
    acc: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    q4 = rules.periods

    def window(period: int, clock: float) -> Optional[str]:
        if period != q4:
            return None
        if clock <= 120:
            return "q4_last2"
        if clock <= 360:
            return "q4_6to2"
        return "q4_early"

    for iv in intervals:
        w = window(iv.period, iv.clock_s)
        if w is None:
            continue
        m = iv.home - iv.away
        lead = "home" if m > 0 else "away" if m < 0 else None
        b = _bucket(abs(m), MARGIN_BUCKETS)
        key = f"{w}|{b}"
        a = acc[key]
        a["sec"] += iv.dt
        if lead:
            trail = "away" if lead == "home" else "home"
            a["sec_led"] += iv.dt
            a["lead_starters_sec"] += iv.dt * len(iv.floor[lead] & starters[lead])
            a["trail_starters_sec"] += iv.dt * len(iv.floor[trail] & starters[trail])
    # events, attributed to the state BEFORE the play
    prev = (0, 0)
    for p in game.plays:
        if p.period == q4:
            w = window(p.period, p.clock_s)
            m = prev[0] - prev[1]
            lead = "home" if m > 0 else "away" if m < 0 else None
            for keyset in ((f"{w}|{_bucket(abs(m), MARGIN_BUCKETS)}", MARGIN_BUCKETS),):
                key = keyset[0]
                a = acc[key]
                dh, da = p.home - prev[0], p.away - prev[1]
                if lead:
                    trail = "away" if lead == "home" else "home"
                    a["lead_pts"] += dh if lead == "home" else da
                    a["trail_pts"] += da if lead == "home" else dh
                    role = "lead" if p.team == lead else "trail" if p.team == trail else None
                    if role:
                        if p.kind == "shot" or (p.kind != "ft" and p.made and p.points >= 2):
                            a[f"{role}_fga"] += 1
                        elif p.kind == "ft":
                            a[f"{role}_fta"] += 1
                        elif p.kind == "turnover":
                            a[f"{role}_tov"] += 1
                        elif p.kind == "rebound_o":
                            a[f"{role}_oreb"] += 1
                        elif p.kind == "foul":
                            a[f"{role}_fouls"] += 1
                else:
                    a["tied_pts"] += dh + da
                    if p.kind == "foul":
                        a["tied_fouls"] += 1
            # last-2:00 trailing-margin view (tied separate): fouls BY the trailing team
            if w == "q4_last2" or w == "q4_6to2":
                tb = _bucket(abs(m), TRAIL_BUCKETS)
                key = f"{w}|trail_{tb}"
                a = acc[key]
                if p.kind == "foul":
                    if lead is None:
                        a["fouls_any"] += 1
                    elif p.team != lead:
                        a["trail_fouls"] += 1
                    else:
                        a["lead_fouls"] += 1
                if p.kind == "ft":
                    a["fta"] += 1
                a["pts"] += (p.home - prev[0]) + (p.away - prev[1])
        prev = (p.home, p.away)
    for iv in intervals:
        w = window(iv.period, iv.clock_s)
        if w in ("q4_last2", "q4_6to2"):
            tb = _bucket(abs(iv.home - iv.away), TRAIL_BUCKETS)
            acc[f"{w}|trail_{tb}"]["sec"] += iv.dt
    return {k: dict(v) for k, v in acc.items()}


def _poss(units, role):
    def f(us):
        sec = sum(u.get("sec_led", 0.0) for u in us)
        if sec <= 0:
            return None
        poss = sum(u.get(f"{role}_fga", 0) + 0.44 * u.get(f"{role}_fta", 0) + u.get(f"{role}_tov", 0)
                   - u.get(f"{role}_oreb", 0) for u in us)
        return 2880.0 * poss / sec
    return f


def garbage_and_endgame(per_game: List[Dict[str, Dict[str, float]]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"garbage_time": {}, "end_game": {}}
    for w in ("q4_early", "q4_6to2", "q4_last2"):
        for _, _, b in MARGIN_BUCKETS:
            key = f"{w}|{b}"
            units = [g[key] for g in per_game if key in g and g[key].get("sec_led", 0) > 0]
            if not units:
                continue
            out["garbage_time"][key] = {
                "games": len(units),
                "minutes": sum(u.get("sec", 0) for u in units) / 60.0,
                "lead_starters_on_floor": boot(units, _ratio("lead_starters_sec", "sec_led")),
                "trail_starters_on_floor": boot(units, _ratio("trail_starters_sec", "sec_led")),
                "starters_gap_trail_minus_lead": boot(units, _diff(_ratio("trail_starters_sec", "sec_led"),
                                                                   _ratio("lead_starters_sec", "sec_led"))),
                "lead_pts_per48": boot(units, _ratio("lead_pts", "sec_led", 2880.0)),
                "trail_pts_per48": boot(units, _ratio("trail_pts", "sec_led", 2880.0)),
                "lead_poss_per48": boot(units, _poss(units, "lead")),
                "trail_poss_per48": boot(units, _poss(units, "trail")),
            }
    for w in ("q4_6to2", "q4_last2"):
        for _, _, b in TRAIL_BUCKETS:
            key = f"{w}|trail_{b}"
            units = [g[key] for g in per_game if key in g and g[key].get("sec", 0) > 0]
            if not units:
                continue
            fouls_key = "fouls_any" if b == "tied" else "trail_fouls"
            out["end_game"][key] = {
                "games": len(units),
                "minutes": sum(u.get("sec", 0) for u in units) / 60.0,
                "fouls_by_trailer_per_min": boot(units, _ratio(fouls_key, "sec", 60.0)),
                "fouls_by_leader_per_min": boot(units, _ratio("lead_fouls", "sec", 60.0)),
                "fta_per_min": boot(units, _ratio("fta", "sec", 60.0)),
                "pts_per_min": boot(units, _ratio("pts", "sec", 60.0)),
            }
    return out


# ----------------------------------------------------------------------------------------------- D. foul trouble

FOUL_TROUBLE = (  # (period, fouls reached, minimum clock remaining at the moment) -> name
    (1, 2, 180.0, "2pf_in_q1"),
    (2, 3, 180.0, "3pf_in_q2"),
    (3, 4, 180.0, "4pf_in_q3"),
    (4, 5, 240.0, "5pf_in_q4"),
)


def foul_trouble(game: bt.PbpGame, intervals: List[Interval]) -> Dict[str, Dict[str, float]]:
    """For STARTERS: share of the rest of the period on the floor after reaching the foul count (event), vs
    the same share for starters who had NOT reached it at that clock (control, same game, same clock)."""
    rules = bt.LEAGUES[game.league]
    starters = set(game.starters.get("home", [])) | set(game.starters.get("away", []))
    out: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    pf: Dict[str, int] = defaultdict(int)
    for p in game.plays:
        if p.kind not in ("foul", "ofoul") or not p.p1:
            continue
        pf[p.p1] += 1
        for period, n, min_clock, name in FOUL_TROUBLE:
            if p.period != period or pf[p.p1] != n or p.clock_s < min_clock or p.p1 not in starters:
                continue
            t0 = p.elapsed_s
            t1 = bt.elapsed_seconds(rules, period, 0.0)
            on_ev = _on_share(intervals, p.p1, t0, t1)
            ctrl = [c for c in starters if c != p.p1 and pf[c] < n - 1]
            ctrl_share = [_on_share(intervals, c, t0, t1) for c in ctrl]
            if on_ev is None or not ctrl_share:
                continue
            o = out[name]
            o["events"] += 1
            o["event_on_share_sum"] += on_ev
            o["control_on_share_sum"] += statistics.fmean([c for c in ctrl_share if c is not None] or [0.0])
    return {k: dict(v) for k, v in out.items()}


def _on_share(intervals: List[Interval], pid: str, t0: float, t1: float) -> Optional[float]:
    tot = on = 0.0
    for iv in intervals:
        a, b = max(iv.t0, t0), min(iv.t1, t1)
        if b <= a:
            continue
        tot += b - a
        if pid in iv.floor["home"] or pid in iv.floor["away"]:
            on += b - a
    return None if tot <= 0 else on / tot


# ----------------------------------------------------------------------------------------------- E. rotation shape

def rotation_shape(game: bt.PbpGame, intervals: List[Interval]) -> Dict[str, List[float]]:
    """Starters on floor (0..5) per regulation minute, per side, labelled by final |margin| class."""
    rules = bt.LEAGUES[game.league]
    n_min = rules.regulation_seconds // 60
    starters = {s: set(game.starters.get(s, [])) for s in ("home", "away")}
    sec = [0.0] * n_min
    st_sec = [0.0] * n_min
    for iv in intervals:
        t = iv.t0
        while t < iv.t1 and t < rules.regulation_seconds:
            m = int(t // 60)
            e = min(iv.t1, (m + 1) * 60.0)
            for s in ("home", "away"):
                sec[m] += (e - t)
                st_sec[m] += (e - t) * len(iv.floor[s] & starters[s])
            t = e
    return {"sec": sec, "st_sec": st_sec}


# ----------------------------------------------------------------------------------------------- driver

def measure(games: Sequence[bt.PbpGame], lines: Dict[Tuple[str, str, str], Dict[str, float]]) -> Dict[str, Any]:
    by_pop: Dict[str, List[bt.PbpGame]] = defaultdict(list)
    for g in games:
        by_pop[g.population].append(g)
    report: Dict[str, Any] = {}
    for pop, gs in sorted(by_pop.items()):
        pre = {g.event_id: bt.pregame_for(g, lines, {}) for g in gs}
        spreads = {k: v.spread_home for k, v in pre.items() if v.spread_home is not None}
        pregame = {k: (v.spread_home, v.total) for k, v in pre.items()}
        quality, per_game_q4, ft_units = [], [], []
        shape_close = {"sec": [0.0] * 48, "st_sec": [0.0] * 48}
        shape_blow = {"sec": [0.0] * 48, "st_sec": [0.0] * 48}
        n_close = n_blow = 0
        for g in gs:
            ivs, q = infer_floor(g)
            quality.append(q)
            per_game_q4.append(q4_units(g, ivs))
            ft_units.append(foul_trouble(g, ivs))
            rs = rotation_shape(g, ivs)
            fm = abs(g.final_home - g.final_away)
            tgt = shape_close if fm <= 10 else shape_blow if fm >= 20 else None
            if tgt is not None and len(rs["sec"]) == 48:
                n_close += fm <= 10
                n_blow += fm >= 20
                for i in range(48):
                    tgt["sec"][i] += rs["sec"][i]
                    tgt["st_sec"][i] += rs["st_sec"][i]
        mae = [q["minutes_mae"] for q in quality if q["minutes_mae"] is not None]
        ft_report = {}
        for _, _, _, name in FOUL_TROUBLE:
            units = [u[name] for u in ft_units if name in u]
            if units:
                ft_report[name] = {
                    "events": int(sum(u["events"] for u in units)),
                    "event_on_share": boot(units, _ratio("event_on_share_sum", "events")),
                    "control_on_share": boot(units, _ratio("control_on_share_sum", "events")),
                    "gap": boot(units, _diff(_ratio("event_on_share_sum", "events"), _ratio("control_on_share_sum", "events"))),
                }
        report[pop] = {
            "games": len(gs),
            "games_with_spread": len(spreads),
            "pregame_sources": dict(sorted(_count(v.source for v in pre.values()).items())),
            "floor_inference": {
                "minutes_mae_median": statistics.median(mae) if mae else None,
                "minutes_mae_mean": statistics.fmean(mae) if mae else None,
                "share_games_mae_le_0_5": (sum(1 for x in mae if x <= 0.5) / len(mae)) if mae else None,
                "intervals_not_five_share": (sum(q["intervals_not_five"] for q in quality)
                                             / max(1, 2 * sum(q["intervals"] for q in quality))),
            },
            "score_effect": score_effect(gs, spreads),
            "checkpoint_reversion": checkpoint_reversion(gs, pregame),
            **garbage_and_endgame(per_game_q4),
            "foul_trouble": ft_report,
            "rotation_starters_on_floor_by_minute": {
                "close_final_le_10": {"games": n_close, "curve": [round(s / x, 3) if x else None for s, x in zip(shape_close["st_sec"], shape_close["sec"])]},
                "blowout_final_ge_20": {"games": n_blow, "curve": [round(s / x, 3) if x else None for s, x in zip(shape_blow["st_sec"], shape_blow["sec"])]},
            },
        }
    return report


def _count(it):
    c: Dict[str, int] = defaultdict(int)
    for x in it:
        c[x] += 1
    return c


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", required=True)
    ap.add_argument("--lines-cache")
    ap.add_argument("--population", action="append")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    games = bt.load_games(Path(args.games))
    if args.population:
        games = [g for g in games if g.population in set(args.population)]
    lines = bt.load_pregame_lines(Path(args.lines_cache)) if args.lines_cache else {}
    rep = measure(games, lines)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "targets.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print("TARGETS " + " ".join(f"{p}={v['games']}" for p, v in rep.items()) + f" out={out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
