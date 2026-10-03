"""Fit: does an as-of USAGE mean give the NFL prop probability information at the line?

Lane `nfl-prop-mean-inputs` (2026-10-03). Measurement only: production files are not edited.

WHY. Lane `nfl-prop-predictive-spread` showed the PRODUCTION prop probability has a calibration slope ~0
at the line in all six continuous markets (book ~1). Its opinion is noise there, and no reshaping of the
spread changes that. The market-anchored mean closed 86-97% of the gap, so the information is in the
line. This asks whether pbp-derivable USAGE recovers any of it.

MEAN ARMS (each x production's game-context multiplier, priced through production's own
`_nfl_prop_model_probability` with production's sd, n and line, so only the MEAN differs):
  prod       production's season-to-date mean (control: must reproduce the served p on every row)
  ewma       recency-weighted mean of the stat over the player's prior games, half-life h
  share      EWMA share of team volume x team EWMA volume x EWMA efficiency shrunk to the league
             (receptions: targets x catch rate; receiving_yards: targets x yds/target; rushing_*:
             rushes [x ypc]; passing_*: pass attempts [x ypa])
  share_inj  share, with the shares of teammates listed Out/Doubtful on THIS week's injury report
             redistributed proportionally to the rest
AS-OF: features use games with week < the game's week in its season, falling back to the whole prior
season when the current one has < 2 games (production's rule). Team volume is the player's most recent
team. The injury report is the game week's official designation (`date_modified` after gameday: 1 of
~5,400 status rows in 2023-24; 2025-26 carry no date_modified).
KNOWN GAP: player game logs exist only for games with a qualifying play (the same denominator issue
production's zero-week imputation handles), so shares are conditional on involvement.

SCORING (fit 2023-24 by Brier, report 2025 holdout and 2026 wk2):
  * calibration slope b of logistic(y ~ a + b*logit p), with a GAME-clustered bootstrap CI (200 reps).
    The lane bar is b > 0 with the CI excluding 0 for receptions AND receiving_yards.
  * Brier vs production and vs the de-vigged book, paired game-clustered CIs.
  * information beyond the line: corr(mean - line, actual - line) over unique player-games at each
    game's main line (the median of each book's most balanced line), with a CI. If the mean adds
    nothing the line lacks, this is ~0.
  * point MAE vs actual: arm vs production vs the book line.

Usage:
  py -3 scripts/fit_nfl_prop_mean_inputs.py --root C:/tmp/nflbt/root/nfl_source \\
      --rows C:/tmp/nflbt/spread/prop_rows.pkl --out C:/tmp/nflbt/meaninputs
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pickle
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("bt_lines_props", REPO / "scripts" / "backtest_nfl_lines_props.py")
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)  # type: ignore[union-attr]
_spec2 = importlib.util.spec_from_file_location("fit_spread", REPO / "scripts" / "fit_nfl_prop_predictive_spread.py")
fs = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(fs)  # type: ignore[union-attr]

CONTINUOUS = ("receptions", "receiving_yards", "rushing_yards", "rushing_attempts", "passing_yards", "passing_attempts")
# stat -> (unit, efficiency numerator or None, league-prior weight in units)
USAGE = {
    "receptions": ("targets", "receptions", 20.0),
    "receiving_yards": ("targets", "receiving_yards", 20.0),
    "rushing_attempts": ("rushes", None, 0.0),
    "rushing_yards": ("rushes", "rushing_yards", 40.0),
    "passing_attempts": ("pass_att", None, 0.0),
    "passing_yards": ("pass_att", "passing_yards", 100.0),
}
H_GRID = (1.5, 3.0, 6.0, 12.0)
FIT, HOLDOUT, CURRENT = (2023, 2024), (2025,), (2026,)
OUT_STATUSES = {"Out", "Doubtful"}
# the game-log KEY each stat is stored under in `Usage.pg` (the first run read `g["rushing_attempts"]`,
# a key that is never written, so the defaultdict returned 0 and the ewma mean was 0 for both attempts markets)
GAME_KEY = {"receptions": "receptions", "receiving_yards": "receiving_yards", "rushing_yards": "rushing_yards",
            "rushing_attempts": "rushes", "passing_yards": "passing_yards", "passing_attempts": "pass_att"}
# an Out teammate only frees volume he was ACTUALLY taking: he must have played for this team in the
# current season within this many team weeks, and the freed mass is capped. The first run let a backup
# QB's prior-season share count, up to 0.9, which multiplied a starter's share by as much as 10.
INJ_RECENT_WEEKS = 3
INJ_MASS_CAP = 0.5


# ---------------------------------------------------------------------------
# as-of usage tables from pbp
# ---------------------------------------------------------------------------

def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


class Usage:
    """Per-player and per-team game counts for one season, from production's own play loader."""

    def __init__(self, season: int) -> None:
        from syndicate.features.nfl import player_stats as ps
        self.season = season
        self.pg: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)   # pid -> game_id -> counts
        self.tg: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(lambda: defaultdict(float))  # (team, game) -> totals
        for p in ps.load_player_plays(season):
            gid, wk, team = p["game_id"], int(p["week"]), p.get("posteam") or ""
            if not team:
                continue
            T = self.tg[(team, gid)]
            T["week"] = wk
            pa = p.get("pass_attempt") == "1"
            rec = p.get("receiver_player_id") or ""
            rush = p.get("rush_attempt") == "1"
            if pa:
                T["pass_att"] += 1
                if rec:
                    T["targets"] += 1
            if rush:
                T["rushes"] += 1
            for pid, role in ((p.get("passer_player_id"), "passer"), (rec, "receiver"), (p.get("rusher_player_id"), "rusher")):
                if not pid:
                    continue
                g = self.pg[pid].setdefault(gid, defaultdict(float, {"week": wk, "team": team}))
                if role == "passer" and pa:
                    g["pass_att"] += 1
                    g["passing_yards"] += _f(p.get("passing_yards"))
                if role == "receiver" and pa:
                    g["targets"] += 1
                    g["receptions"] += 1 if p.get("complete_pass") == "1" else 0
                    g["receiving_yards"] += _f(p.get("receiving_yards"))
                if role == "rusher" and rush:
                    g["rushes"] += 1
                    g["rushing_yards"] += _f(p.get("rushing_yards"))
        self.tw: Dict[Tuple[str, int], Dict[str, float]] = {(tm, int(t["week"])): t for (tm, _g), t in self.tg.items()}
        self.by_team: Dict[str, List[Dict[str, float]]] = defaultdict(list)
        for (tm, _g), t in self.tg.items():
            self.by_team[tm].append(t)
        for v in self.by_team.values():
            v.sort(key=lambda t: t["week"])
        self.league_eff: Dict[str, float] = {}
        for stat, (unit, num, _m) in USAGE.items():
            if num:
                u = sum(g[unit] for gs in self.pg.values() for g in gs.values())
                n = sum(g[num] for gs in self.pg.values() for g in gs.values())
                self.league_eff[stat] = n / u if u else 0.0

    def player_games(self, pid: str, before_week: int) -> List[Dict[str, Any]]:
        return sorted((g for g in self.pg.get(pid, {}).values() if g["week"] < before_week), key=lambda g: g["week"])

    def team_games(self, team: str, before_week: int) -> List[Dict[str, float]]:
        return [t for t in self.by_team.get(team, []) if t["week"] < before_week]

    def team_game_of(self, team: str, week: int) -> Optional[Dict[str, float]]:
        return self.tw.get((team, int(week)))


def ewma(vals: List[float], h: float) -> Optional[float]:
    if not vals:
        return None
    k = len(vals)
    ws = [0.5 ** ((k - 1 - i) / h) for i in range(k)]
    return sum(w * v for w, v in zip(ws, vals)) / sum(ws)


class Features:
    def __init__(self, seasons: List[int], injuries: Dict[Tuple[int, int, str], set]) -> None:
        self.U = {s: Usage(s) for s in seasons}
        self.inj = injuries

    def _window(self, season: int, week: int, pid: str):
        U = self.U.get(season)
        games = U.player_games(pid, week) if U else []
        if len(games) >= 2:
            return U, games, week
        P = self.U.get(season - 1)
        if P is None:
            return None, [], week
        return P, P.player_games(pid, 99), 99

    def ewma_mean(self, stat: str, season: int, week: int, pid: str, h: float) -> Optional[float]:
        _U, games, _w = self._window(season, week, pid)
        if len(games) < 2:
            return None
        key = GAME_KEY[stat]
        assert all(key in g for g in games), f"{stat}: game log has no {key!r}"
        return ewma([g[key] for g in games], h)

    def _share(self, U, games, wk, unit: str, h: float, pid: str) -> Tuple[Optional[float], Optional[str]]:
        shares = []
        for g in games:
            tg = U.tw.get((g["team"], int(g["week"])))
            if tg and tg[unit] > 0:
                shares.append(g[unit] / tg[unit])
        return ewma(shares, h), (games[-1]["team"] if games else None)

    def share_mean(self, stat: str, season: int, week: int, pid: str, h: float, injury: bool = False) -> Optional[float]:
        unit, num, m = USAGE[stat]
        U, games, wk = self._window(season, week, pid)
        if U is None or len(games) < 2:
            return None
        share, team = self._share(U, games, wk, unit, h, pid)
        if share is None or team is None:
            return None
        tgs = U.team_games(team, wk)
        vol = ewma([t[unit] for t in tgs], h)
        if vol is None:
            return None
        if injury:
            out = self.inj.get((season, week, team), set())
            if pid in out:
                return None
            Ucur = self.U.get(season)
            if out and Ucur is not None:
                # as-of shares of the teammates listed Out, removed and redistributed -- only players
                # active for THIS team in THIS season within the last INJ_RECENT_WEEKS team weeks
                mass = 0.0
                for oid in out:
                    if oid == pid:
                        continue
                    og = [g for g in Ucur.player_games(oid, week) if g["team"] == team]
                    if og and og[-1]["week"] >= week - INJ_RECENT_WEEKS:
                        s_, _ = self._share(Ucur, og, week, unit, h, oid)
                        mass += s_ or 0.0
                share = share / (1.0 - min(mass, INJ_MASS_CAP))
        mean = share * vol
        if num:
            units = sum(g[unit] for g in games)
            made = sum(g[num] for g in games)
            prior = U.league_eff.get(stat, 0.0)
            eff = (made + m * prior) / (units + m) if (units + m) > 0 else prior
            mean *= eff
        return mean


PRACTICE_CATEGORY = {"Full Participation in Practice": "full", "Limited Participation in Practice": "limited",
                     "Did Not Participate In Practice": "dnp"}


def load_practice(root: Path, seasons: List[int]) -> Dict[Tuple[int, int, str], str]:
    """(season, week, gsis_id) -> full / limited / dnp, from the game week's official injury report.
    A player absent from the report is `none` (not on it: healthy, or not reported)."""
    out: Dict[Tuple[int, int, str], str] = {}
    for s in seasons:
        p = root / "tracking" / "nflverse" / "injuries" / f"injuries_{s}.csv"
        if not p.exists():
            continue
        with p.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if (r.get("game_type") or "REG") != "REG" or not r.get("gsis_id"):
                    continue
                c = PRACTICE_CATEGORY.get((r.get("practice_status") or "").strip())
                if c:
                    out[(int(r["season"]), int(r["week"]), r["gsis_id"])] = c
    return out


def load_injuries(root: Path, seasons: List[int]) -> Dict[Tuple[int, int, str], set]:
    out: Dict[Tuple[int, int, str], set] = defaultdict(set)
    for s in seasons:
        p = root / "tracking" / "nflverse" / "injuries" / f"injuries_{s}.csv"
        if not p.exists():
            continue
        with p.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if (r.get("game_type") or "REG") != "REG":
                    continue
                if r.get("report_status") in OUT_STATUSES and r.get("gsis_id"):
                    out[(int(r["season"]), int(r["week"]), r["team"])].add(r["gsis_id"])
    return out


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def slope_ci(ps: List[float], rows: List[Dict[str, Any]], reps: int = 200, seed: int = 5) -> Dict[str, Any]:
    ys = [r["y"] for r in rows]
    a, b = fs.calibration_slope(ps, ys)
    by: Dict[str, List[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by[r["gid"]].append(i)
    keys = list(by)
    rng = random.Random(seed)
    bs = []
    for _ in range(reps):
        idx = [i for _k in range(len(keys)) for i in by[keys[rng.randrange(len(keys))]]]
        _a, bb = fs.calibration_slope([ps[i] for i in idx], [ys[i] for i in idx])
        if bb is not None:
            bs.append(bb)
    bs.sort()
    ci = [round(bs[int(0.025 * len(bs))], 4), round(bs[int(0.975 * len(bs)) - 1], 4)] if len(bs) >= 20 else None
    return {"slope": b, "intercept": a, "ci95": ci, "reps_ok": len(bs)}


def info_beyond_line(rows: List[Dict[str, Any]], means: List[float]) -> Dict[str, Any]:
    """corr(mean - line, actual - line) over unique player-games at the main line."""
    per: Dict[Tuple[str, str], Dict[str, Any]] = {}
    lines: Dict[Tuple[str, str], Dict[str, Tuple[float, float]]] = defaultdict(dict)
    for r, m in zip(rows, means):
        k = (r["gid"], r["player"])
        per[k] = {"gid": r["gid"], "mean": m, "actual": r["actual"]}
        cur = lines[k].get(r["book"])
        d = abs(r["p_book"] - 0.5)
        if cur is None or d < cur[0]:
            lines[k][r["book"]] = (d, r["line"])
    xs, ys, gs = [], [], []
    for k, v in per.items():
        ln = statistics.median(t[1] for t in lines[k].values())
        xs.append(v["mean"] - ln)
        ys.append(v["actual"] - ln)
        gs.append(v["gid"])
    c = fs_corr(xs, ys)
    by: Dict[str, List[int]] = defaultdict(list)
    for i, g in enumerate(gs):
        by[g].append(i)
    keys = list(by)
    rng = random.Random(9)
    cs = []
    for _ in range(300):
        idx = [i for _k in range(len(keys)) for i in by[keys[rng.randrange(len(keys))]]]
        cc = fs_corr([xs[i] for i in idx], [ys[i] for i in idx])
        if cc is not None:
            cs.append(cc)
    cs.sort()
    return {"n_player_games": len(xs), "corr": c,
            "ci95": [round(cs[int(0.025 * len(cs))], 4), round(cs[int(0.975 * len(cs)) - 1], 4)] if cs else None,
            "mae_mean": round(statistics.fmean(abs(x - y) for x, y in zip(xs, ys)), 4),
            "mae_line": round(statistics.fmean(abs(y) for y in ys), 4)}


def fs_corr(xs: List[float], ys: List[float]) -> Optional[float]:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return round(num / (dx * dy), 4) if dx and dy else None


def run_market(stat: str, rows: List[Dict[str, Any]], F: Features, arm_names: Tuple[str, ...]) -> Dict[str, Any]:
    from syndicate.features.nfl import props as P

    def p_of(r, mean):
        if mean is None:
            return None
        return P._nfl_prop_model_probability(stat=stat, mean=mean * r["ctx"], stdev=r["sd"], n=r["n"], line=r["line"])

    # control: production's mean reproduces the served probability
    worst = max((abs(p_of(r, r["mean"] / r["ctx"]) - r["p_model"]) for r in rows if r["ctx"]), default=0.0)
    assert worst < 1e-9, f"{stat}: control failed {worst}"

    cache: Dict[Tuple, Optional[float]] = {}

    def mean_for(arm, h, r):
        k = (arm, h, r["season"], r["week"], r["pid"])
        if k not in cache:
            if arm == "ewma":
                cache[k] = F.ewma_mean(stat, r["season"], r["week"], r["pid"], h)
            elif arm == "share":
                cache[k] = F.share_mean(stat, r["season"], r["week"], r["pid"], h)
            elif arm == "practice":
                cache[k] = (r["mean"] / r["ctx"]) * practice_factor[practice_cat(r)]
            else:
                cache[k] = F.share_mean(stat, r["season"], r["week"], r["pid"], h, injury=True)
        return cache[k]

    def practice_cat(r):
        return F.practice.get((r["season"], r["week"], r["pid"]), "none")

    # per-status factor = sum(actual) / sum(production mean incl. context), unique player-games, FIT seasons
    acc: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0, 0])
    seen = set()
    for r in rows:
        k = (r["gid"], r["pid"])
        if r["season"] not in FIT or k in seen:
            continue
        seen.add(k)
        a = acc[practice_cat(r)]
        a[0] += r["actual"]
        a[1] += r["mean"]
        a[2] += 1
    practice_factor = defaultdict(lambda: 1.0)
    for c, (act, mn, _n) in acc.items():
        practice_factor[c] = min(1.5, max(0.5, act / mn)) if mn > 0 else 1.0

    Fit = bt._sub([r for r in rows if r["season"] in FIT], cap=20000)
    out: Dict[str, Any] = {"control_max_abs_diff": worst, "arms": {},
                           "practice_factor": {c: round(practice_factor[c], 4) for c in acc},
                           "practice_fit_n": {c: v[2] for c, v in acc.items()}}
    arms = [("prod", None)]
    if "practice" in arm_names:
        arms.append(("practice", None))
    for arm in [x for x in ("ewma", "share", "share_inj") if x in arm_names]:
        def fb(h, arm=arm):
            tot = cnt = 0
            for r in Fit:
                p = p_of(r, mean_for(arm, h, r))
                if p is None:
                    continue
                tot += (bt._clip(p) - r["y"]) ** 2
                cnt += 1
            return tot / cnt if cnt else float("inf")
        arms.append((arm, min(H_GRID, key=fb)))
    for arm, h in arms:
        A: Dict[str, Any] = {"h": h}
        for label, seasons in (("2025 holdout", HOLDOUT), ("2026 in-season", CURRENT)):
            T = [r for r in rows if r["season"] in seasons]
            means = [r["mean"] / r["ctx"] if arm == "prod" else mean_for(arm, h, r) for r in T]
            keep = [i for i, m in enumerate(means) if m is not None]
            TT = [T[i] for i in keep]
            if len(TT) < 50:
                A[label] = {"n": len(TT), "status": "INSUFFICIENT_N"}
                continue
            ps = [p_of(T[i], means[i]) for i in keep]
            pp = [T[i]["p_model"] for i in keep]
            ev = fs.evaluate(TT, ps, pp)
            ev["coverage_of_rows"] = round(len(TT) / len(T), 4)
            ev["slope_ci"] = slope_ci(ps, TT)
            ev["info_beyond_line"] = info_beyond_line(TT, [means[i] * T[i]["ctx"] for i in keep])
            sub = [j for j, i in enumerate(keep) if practice_cat(T[i]) in ("limited", "dnp")]
            if len(sub) >= 50:
                S = [TT[j] for j in sub]
                sev = fs.evaluate(S, [ps[j] for j in sub], [pp[j] for j in sub])
                sev["slope_ci"] = slope_ci([ps[j] for j in sub], S)
                sev["info_beyond_line"] = info_beyond_line(S, [means[keep[j]] * TT[j]["ctx"] for j in sub])
                ev["subgroup_limited_dnp"] = sev
            else:
                ev["subgroup_limited_dnp"] = {"n": len(sub), "status": "INSUFFICIENT_N"}
            A[label] = ev
        out["arms"][arm] = A
    return out


def write_md(rep: Dict[str, Any], path: Path) -> None:
    L = ["# NFL prop mean-inputs fit", "", f"generated {rep['generated_at']}; fit {list(FIT)} by Brier; scored 2025 holdout + 2026 wk2", "",
         f"**lane bar** (slope > 0, CI excluding 0, receptions AND receiving_yards, 2025): `{json.dumps(rep.get('verdict'))}`", ""]
    for stat, M in rep["markets"].items():
        L += [f"## {stat} (control max|diff| {M['control_max_abs_diff']:.1e})", "",
              "| arm | h | 2025 n (cov) | slope [CI] | Brier | prod | book | d vs prod [CI] | d vs book [CI] | corr(mean-line, actual-line) [CI] | MAE mean / line | 2026 slope [CI] | 2026 corr |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for arm, A in M["arms"].items():
            h, c = A["2025 holdout"], A.get("2026 in-season", {})
            if "brier" not in h:
                continue
            ib, ic = h["info_beyond_line"], c.get("info_beyond_line", {})
            L.append(f"| {arm} | {A['h']} | {h['n']} ({h['coverage_of_rows']}) | {h['slope_ci']['slope']} {h['slope_ci']['ci95']} | {h['brier']} | {h['brier_prod']} | {h['brier_book']} | "
                     f"{bt._fmt_ci(h['dbrier_vs_prod'])} | {bt._fmt_ci(h['dbrier_vs_book'])} | {ib['corr']} {ib['ci95']} | {ib['mae_mean']} / {ib['mae_line']} | "
                     f"{c.get('slope_ci', {}).get('slope', '')} {c.get('slope_ci', {}).get('ci95', '')} | {ic.get('corr', '')} |")
        L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


def verdict(markets: Dict[str, Any]) -> Dict[str, Any]:
    res = {}
    for s in ("receptions", "receiving_yards"):
        best = None
        for arm, A in markets.get(s, {}).get("arms", {}).items():
            h = A.get("2025 holdout", {})
            ci = (h.get("slope_ci") or {}).get("ci95")
            if arm != "prod" and ci and ci[0] > 0 and h["dbrier_vs_prod"]["ci95"][1] < 0:
                best = arm
        res[s] = best
    worse = [s for s, M in markets.items() for arm, A in M["arms"].items()
             if arm != "prod" and A.get("2025 holdout", {}).get("dbrier_vs_prod", {}).get("ci95", [0])[0] > 0]
    return {"passing_arm": res, "arms_worse_than_prod": worse,
            "LANE_BAR": "MET" if all(res.values()) else "NOT MET"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--rows", type=Path, required=True, help="prop_rows.pkl from fit_nfl_prop_predictive_spread.py")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--markets", default=",".join(CONTINUOUS))
    ap.add_argument("--arms", default="ewma,share,share_inj,practice")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    env = bt.configure_env(a.root.resolve())
    bt._patch_game_log_cache()
    with a.rows.open("rb") as fh:
        rows = pickle.load(fh)
    seasons = [2022, 2023, 2024, 2025, 2026]
    F = Features(seasons, load_injuries(a.root.resolve(), seasons))
    F.practice = load_practice(a.root.resolve(), seasons)
    rep: Dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(), "env": env, "markets": {}}
    for m in [x for x in a.markets.split(",") if x]:
        print(f"[mean] {m}: {len(rows[m])} rows", flush=True)
        rep["markets"][m] = run_market(m, rows[m], F, tuple(x for x in a.arms.split(",") if x))
        (a.out / "fit_nfl_prop_mean_inputs.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    rep["verdict"] = verdict(rep["markets"])
    (a.out / "fit_nfl_prop_mean_inputs.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    write_md(rep, a.out / "fit_nfl_prop_mean_inputs.md")
    print(json.dumps(rep["verdict"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
