"""NHL game-line model experiments (lane `nhl-game-lines-model`).

`scripts/backtest_nhl_game_lines.py` showed every hockeysim game market TIES an as-of team GF/GA
baseline (2025-26, n=1,132). This harness tests WHY and WHAT FIXES IT, layering candidate changes
multiplicatively on the production lambdas that harness already produced (`<out>/sim/games.json`,
production `predict_game`, asserted equal) -- exactly the shape a production change would take.

VARIANTS (cumulative; each also reported singly where meaningful)
  V0  production raw: regulation-only sim, ties split 50/50, p_over on regulation goals
  V1  + full-game settlement: a regulation tie goes to OT/SO, home wins it w.p. q (as-of league
        OT/SO home share), and the settled total gets +1 (the OT goal or the SO credit)
  V2  + regulation scale: lambdas x s, s = as-of league REGULATION goals / as-of mean model total
        (H1: projection.py's 3.1269/60 is a FULL-GAME rate used as a regulation rate)
  V3  + tie mass: tie samples re-weighted 1+delta, delta fit as-of to the league tie rate (H3)
  V4  + empty net: a 1-goal regulation lead becomes 2 w.p. e, e fit as-of on the non-tie
        1-goal share (H4)
  V5  + starting goalie: the opponent's lambda x (1 - sv_g)/(1 - sv_lg), sv_g the PROJECTED
        starter's as-of save% shrunk with k shots (production collector's own projection,
        `starting_goalies_<date>.csv`, source hockeysim_toi)
  V6  + rest: back-to-back multipliers on a team's goals for/against, fit on games before the date
  V5o ORACLE: V5 with the ACTUAL starter -- NOT pregame-honest (identity known after puck drop);
        an upper bound on what confirmed-starter data would buy

BASELINES
  B0  the as-of GF/GA team baseline of backtest_nhl_game_lines (production machinery)
  B4  the same GF/GA lambdas pushed through V1..V4 machinery, fit the same way on ITS OWN
      predictions -- so "beats B4" means INFORMATION, not plumbing.

HONESTY
  * machinery parameters are walk-forward: fit on games strictly before the date;
  * information hyper-parameters (goalie shrink k, rest shrink) are tuned on games BEFORE
    2026-01-01 only and frozen; the headline window is 2026-01-01..2026-04-16 (out of sample);
  * common random numbers: every variant of a game re-uses the game's production seed;
  * CIs: date-clustered bootstrap, 2,000 reps.

Usage:
  py -3 scripts/nhl_game_lines_experiments.py --out C:/tmp/nhllines_after --roots C:/tmp/nhlprops/bt_after \
      --report docs/reports/nhl_game_lines_model_experiments_2026-10-02.md
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import random
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("_bgl", REPO / "scripts" / "backtest_nhl_game_lines.py")
BGL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BGL)  # type: ignore[union-attr]

EVAL_START = "2026-01-01"
BOOK: Dict[str, Dict] = {}  # gid -> closing consensus from backtest_nhl_game_lines (book.json)
REG_FULLGAME_BASE = 6.2538  # projection.py's calibration total (full game incl. OT + SO credit)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace(".", " ").replace("-", " ").split())


# ---------------------------------------------------------------------------
# data: goalie lines per game, projected starters, schedule
# ---------------------------------------------------------------------------

def goalie_lines(act: Dict[str, Dict], src: Path, roots: Path) -> Dict[str, Dict[str, List[Dict]]]:
    """{gid: {abbr: [ {pid, key, shots, ga, starter, toi} ]}} from boxscores."""
    out: Dict[str, Dict[str, List[Dict]]] = {}
    for gid, r in act.items():
        box = None
        for p in (src / "data" / "ingestion_cache" / f"boxscore_{gid}.json", roots / "cache" / f"boxscore_{gid}.json"):
            box = BGL._rj(p)
            if box:
                break
        if not box:
            continue
        per = {}
        for side, ab in (("homeTeam", r["home"]), ("awayTeam", r["away"])):
            gl = []
            for g in ((box.get("playerByGameStats") or {}).get(side) or {}).get("goalies") or []:
                nm = str((g.get("name") or {}).get("default") or "")
                gl.append({"pid": int(g["playerId"]), "key": _key_from_full(nm) or _norm(nm), "shots": int(g.get("shotsAgainst") or 0),
                           "ga": int(g.get("goalsAgainst") or 0), "starter": bool(g.get("starter"))})
            per[ab] = gl
        out[gid] = per
    return out


@__import__("functools").lru_cache(maxsize=None)
def projected_starters(roots: Path, date: str) -> Dict[str, str]:
    """{team abbr: 'j swayman'-style key} from the production collector's file."""
    p = roots / "roots" / date / "data" / "processed" / f"starting_goalies_{date}.csv"
    res = {}
    if not p.exists():
        return res
    for row in csv.DictReader(p.open(encoding="utf-8")):
        k = _key_from_full(row.get("goalie") or "")
        ab = BGL._abbr_of(row.get("team") or "")
        if k and ab:
            res[ab] = k
    return res


# ---------------------------------------------------------------------------
# sample machinery
# ---------------------------------------------------------------------------

def draws(hp, ap, seed):
    h, a = BGL.replica(hp, ap, seed)
    return h, a


def probs(h, a, *, q_ot=0.5, delta=0.0, e=0.0, seed=0, lines=(5.5, 6.5), full_settlement=True,
          close: Optional[float] = None) -> Dict[str, float]:
    """Market probabilities from regulation samples with the V1..V4 machinery applied."""
    hg, ag = h.sum(axis=1).astype(np.int64), a.sum(axis=1).astype(np.int64)
    if e > 0:
        rng = np.random.default_rng(seed ^ 0x9E3779B9)
        u = rng.random(len(hg))
        lead_h = (hg - ag) == 1
        lead_a = (ag - hg) == 1
        hg = hg + (lead_h & (u < e))
        ag = ag + (lead_a & (u < e))
    d, t = hg - ag, hg + ag
    tie = d == 0
    w = np.where(tie, 1.0 + delta, 1.0)
    W = w.sum()
    m = lambda mask: float((w * mask).sum() / W)
    p_tie = m(tie)
    out = {"p_reg_home": m(d > 0), "p_reg_tie": p_tie, "p_reg_away": m(d < 0),
           "p_home_ml": m(d > 0) + (q_ot if full_settlement else 0.5) * p_tie,
           "p_home_m15": m(d > 1.5), "p_away_m15": m(d < -1.5),
           "reg_total": float((w * t).sum() / W),
           "abs1_nontie": m(np.abs(d) == 1) / max(1e-9, 1 - p_tie)}
    settle = t + tie if full_settlement else t
    out["full_total"] = float((w * settle).sum() / W)
    out["margin"] = float((w * d).sum() / W) + (q_ot - 0.5) * p_tie * (2 if full_settlement else 0)
    for L in lines:
        out[f"over_{L}"] = m(settle > L)
    if close is not None:
        push = m(settle == close)
        out["over_close"] = m(settle > close) / max(1e-9, 1 - push)  # push-free, like the de-vigged book
    return out


# ---------------------------------------------------------------------------
# as-of parameter fits
# ---------------------------------------------------------------------------

class Fitter:
    """Walk-forward machinery fits from games strictly before a date."""

    def __init__(self, act: Dict[str, Dict], pred_reg_total: Dict[str, float], pred_tie: Dict[str, float],
                 pred_abs1: Dict[str, float]):
        self.g = sorted((r for r in act.values() if r["season"] == BGL.SEASON_PREV), key=lambda r: r["date"])
        self.dates = [r["date"] for r in self.g]
        self.prt, self.pt, self.pa1 = pred_reg_total, pred_tie, pred_abs1
        self._cache: Dict[str, Dict] = {}

    def at(self, date: str, arm: str) -> Dict[str, float]:
        key = date if not arm.startswith("current") else "9999"
        if key in self._cache:
            return self._cache[key]
        i = bisect.bisect_left(self.dates, date) if key != "9999" else len(self.g)
        prior = self.g[:i]
        n = len(prior)
        if n < 100:
            res = {"q_ot": 0.5, "s": 1.0 if not prior else 1.0, "delta": 0.0, "e": 0.0, "n": n}
            self._cache[key] = res
            return res
        reg = statistics.fmean(r["reg_h"] + r["reg_a"] for r in prior)
        ot = [r for r in prior if r["last"] in ("OT", "SO")]
        q = statistics.fmean(1.0 if r["final_h"] > r["final_a"] else 0.0 for r in ot) if ot else 0.5
        tie = len(ot) / n
        nontie = [r for r in prior if r["last"] == "REG"]
        o1 = statistics.fmean(1.0 if abs(r["reg_h"] - r["reg_a"]) == 1 else 0.0 for r in nontie)
        # model-side means over prior games that HAVE a model prediction
        mp = [r["gid"] for r in prior if r["gid"] in self.prt]
        if len(mp) >= 100:
            s = reg / statistics.fmean(self.prt[g] for g in mp)
            pbar = statistics.fmean(self.pt[g] for g in mp)
            m1 = statistics.fmean(self.pa1[g] for g in mp)
        else:  # model-free as-of anchor: the profile's full-game base rescaled to regulation
            s = reg / REG_FULLGAME_BASE
            pbar, m1 = 0.16, 0.42
        delta = max(0.0, tie * (1 - pbar) / (pbar * (1 - tie)) - 1.0)
        e = max(0.0, min(0.6, 1.0 - o1 / m1)) if m1 > 0 else 0.0
        res = {"q_ot": q, "s": s, "delta": delta, "e": e, "n": n, "tie": tie, "reg": reg}
        self._cache[key] = res
        return res


# ---------------------------------------------------------------------------
# information: goalie and rest
# ---------------------------------------------------------------------------

class GoalieHistory:
    def __init__(self, act, gl):
        rows = []
        for gid, per in gl.items():
            r = act[gid]
            if r["season"] != BGL.SEASON_PREV:
                continue
            for ab, lst in per.items():
                for g in lst:
                    if g["shots"] > 0:
                        rows.append((r["date"], ab, g["key"], g["pid"], g["shots"], g["ga"], g["starter"]))
        rows.sort()
        self.rows = rows
        self.dates = [x[0] for x in rows]

    def asof(self, date, arm):
        i = bisect.bisect_left(self.dates, date) if not arm.startswith("current") else len(self.rows)
        by_key = defaultdict(lambda: [0, 0, None])
        by_pid = defaultdict(lambda: [0, 0, None])
        S = G = 0
        for (_d, ab, key, pid, sh, ga, _st) in self.rows[:i]:
            for k_ in ((ab, key), ("*", key)):
                by_key[k_][0] += sh; by_key[k_][1] += ga; by_key[k_][2] = pid
            by_pid[pid][0] += sh; by_pid[pid][1] += ga; by_pid[pid][2] = pid
            S += sh; G += ga
        return by_key, by_pid, (1 - G / S) if S else 0.900


PRIOR_SEASON_PREFIX = "2024020"   # 2024-25 regular season game ids 2024020001..2024021312


def fetch_prior_pbp(out: Path, n_games: int = 1312, delay: float = 0.7) -> Dict[str, int]:
    """Cache 2024-25 regular-season play-by-play from api-web.nhle.com (free, public; browser UA,
    urllib's default UA is refused). Every game predates every 2025-26 date, so the whole season is
    an as-of input. A failed fetch is counted, never written as an empty game."""
    import time as _t
    d = out / "pbp_2024"
    d.mkdir(parents=True, exist_ok=True)
    st = Counter()
    for i in range(1, n_games + 1):
        gid = f"{PRIOR_SEASON_PREFIX}{i:03d}" if i < 1000 else f"202402{i:04d}"
        path = d / f"{gid}.json"
        if path.exists() and path.stat().st_size > 0:
            st["cached"] += 1
            continue
        got = BGL._http_json(f"{BGL.NHLE}/gamecenter/{gid}/play-by-play", path, True)
        st["fetched" if got else "failed"] += 1
        _t.sleep(delay)
        if (st["fetched"] + st["failed"]) % 200 == 0:
            print(f"  prior pbp: {dict(st)}", flush=True)
    return dict(st)


class GsaxHistory:
    """Goals saved above expected per goalie, AS-OF, from play-by-play shots scored by the PRODUCTION
    xG estimator (`shot_xg_model.featurize` + `LogisticRegression(max_iter=2000)`, as in
    `scripts/build_nhl_xg_artifact.py`) fit ONLY on shots from games before EVAL_START and frozen.
    Unblocked (Fenwick) shots with a goalie in net; empty-net shots excluded."""

    def __init__(self, act: Dict[str, Dict], src: Path):
        from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import shot_xg_model as X
        rows, feats, goals, fit_mask = [], [], [], []
        stats = Counter()
        for gid, r in act.items():
            if r["season"] != BGL.SEASON_PREV or r["gtype"] != 2:
                continue
            pbp = BGL._rj(src / "data" / "ingestion_cache" / f"playbyplay_{gid}.json")
            if not pbp:
                stats["no_pbp"] += 1
                continue
            shots = X.parse_play_by_play_shots(pbp)
            gids = self._goalies_in_order(pbp, X)
            if len(gids) != len(shots):
                stats["goalie_order_mismatch"] += 1
                continue
            home_id = int((pbp.get("homeTeam") or {}).get("id"))
            for s, gk in zip(shots, gids):
                if s.is_empty_net or gk is None:
                    continue
                defending = r["away"] if s.team_id == home_id else r["home"]
                rows.append((r["date"], defending, int(gk), int(s.is_goal)))
                feats.append(s)
                fit_mask.append(r["date"] < EVAL_START)
            stats["games"] += 1
        from sklearn.linear_model import LogisticRegression
        Xall = X.featurize(feats)
        Xfit = [x for x, m in zip(Xall, fit_mask) if m]
        yfit = [rw[3] for rw, m in zip(rows, fit_mask) if m]
        model = LogisticRegression(max_iter=2000).fit(Xfit, yfit)
        self.model, self._X = model, X
        xg = model.predict_proba(Xall)[:, 1]
        self.rows = sorted((d, ab, gk, float(x), g) for (d, ab, gk, g), x in zip(rows, xg))
        self.dates = [rw[0] for rw in self.rows]
        stats["shots"] = len(self.rows)
        stats["fit_shots_pre_eval"] = len(Xfit)
        self.stats = dict(stats)
        self._cache: Dict[Tuple[str, str], Any] = {}
        self.prior: Dict[int, List[float]] = {}

    def load_prior(self, pbp_dir: Path) -> Dict[str, int]:
        """2024-25 GSAx inputs per goalie, scored by the SAME frozen xG model (never refit)."""
        X = self._X
        feats, rows = [], []
        st = Counter()
        for f in sorted(pbp_dir.glob("*.json")):
            pbp = BGL._rj(f)
            if not pbp or not (pbp.get("plays")):
                st["empty"] += 1
                continue
            shots = X.parse_play_by_play_shots(pbp)
            gids = self._goalies_in_order(pbp, X)
            if len(gids) != len(shots):
                st["goalie_order_mismatch"] += 1
                continue
            for s, gk in zip(shots, gids):
                if s.is_empty_net or gk is None:
                    continue
                feats.append(s); rows.append((int(gk), int(s.is_goal)))
            st["games"] += 1
        if feats:
            xg = self.model.predict_proba(X.featurize(feats))[:, 1]
            for (gk, g), x in zip(rows, xg):
                e = self.prior.setdefault(gk, [0.0, 0.0])
                e[0] += float(x); e[1] += g
        st["shots"] = len(feats); st["goalies"] = len(self.prior)
        return dict(st)

    @staticmethod
    def _goalies_in_order(pbp, X) -> List[Optional[int]]:
        """goalieInNetId for exactly the plays `parse_play_by_play_shots` keeps, in the same order
        (same filters, re-applied); the caller asserts the counts match per game."""
        home_id = (pbp.get("homeTeam") or {}).get("id")
        out = []
        for pl in pbp.get("plays") or []:
            if pl.get("typeDescKey") not in X._FENWICK_TYPES:
                continue
            d = pl.get("details") or {}
            if d.get("eventOwnerTeamId") is None or d.get("xCoord") is None or d.get("yCoord") is None:
                continue
            try:
                float(d["xCoord"]); float(d["yCoord"]); tid = int(d["eventOwnerTeamId"])
            except (TypeError, ValueError):
                continue
            if X._situation_state(pl.get("situationCode"), shooter_is_home=(tid == home_id)) is None:
                continue
            out.append(d.get("goalieInNetId"))
        return out

    def asof(self, date: str, arm: str):
        key = (date, "cur" if arm.startswith("current") else "prev")
        if key in self._cache:
            return self._cache[key]
        i = bisect.bisect_left(self.dates, date) if not arm.startswith("current") else len(self.rows)
        by_pid = defaultdict(lambda: [0.0, 0.0])  # [xG faced, goals allowed]
        XG = G = 0.0
        for (_d, _ab, gk, x, g) in self.rows[:i]:
            by_pid[gk][0] += x; by_pid[gk][1] += g
            XG += x; G += g
        res = (by_pid, (G / XG) if XG else 1.0)
        self._cache[key] = res
        return res


class TeamXg:
    """Per-game team xGF / xGA for 2025-26 regular season, aggregated the way
    `scripts/build_nhl_xg_artifact.py` does (every Fenwick shot incl. empty-net, summed per game,
    rate = per game == "per 60"), scored by the SAME frozen xG model as `GsaxHistory`."""

    def __init__(self, act: Dict[str, Dict], src: Path, gsx: "GsaxHistory"):
        X = gsx._X
        feats, meta, leads = [], [], []
        self.score_walk = Counter()
        for gid, r in act.items():
            if r["season"] != BGL.SEASON_PREV or r["gtype"] != 2:
                continue
            pbp = BGL._rj(src / "data" / "ingestion_cache" / f"playbyplay_{gid}.json")
            if not pbp:
                continue
            home_id = int((pbp.get("homeTeam") or {}).get("id"))
            shots = X.parse_play_by_play_shots(pbp)
            states = self._home_lead_before_kept(pbp, X)
            ok = len(states) == len(shots)
            self.score_walk["games_ok" if ok else "games_mismatch"] += 1
            for k_, s in enumerate(shots):
                feats.append(s)
                meta.append((gid, r["home"] if s.team_id == home_id else r["away"],
                             r["away"] if s.team_id == home_id else r["home"]))
                hl = states[k_] if ok else None
                leads.append(None if hl is None else (hl if s.team_id == home_id else -hl))
        xg = gsx.model.predict_proba(X.featurize(feats))[:, 1]
        # score-state coefficients, fit on pre-EVAL_START shots only: w_d = 0.5 / share_d, where
        # share_d = xG by shooters leading by d / (that + xG by shooters trailing by d)
        by_d = defaultdict(float)
        for (gid, _sh, _df), x, ld in zip(meta, xg, leads):
            if ld is not None and act[gid]["date"] < EVAL_START:
                by_d[max(-3, min(3, ld))] += float(x)
        self.w = {}
        for d_ in range(-3, 4):
            num, den = by_d.get(d_, 0.0), by_d.get(d_, 0.0) + by_d.get(-d_, 0.0)
            self.w[d_] = (0.5 / (num / den)) if den > 0 and num > 0 else 1.0
        per = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))  # gid -> team -> [xgf, xga, adj_xgf, adj_xga]
        for (gid, sh, df), x, ld in zip(meta, xg, leads):
            wx = float(x) * (self.w[max(-3, min(3, ld))] if ld is not None else 1.0)
            e1, e2 = per[gid][sh], per[gid][df]
            e1[0] += float(x); e2[1] += float(x); e1[2] += wx; e2[3] += wx
        self.games = defaultdict(list)      # team -> [(date, xgf, xga)] sorted
        self.games_adj = defaultdict(list)  # same, score-adjusted
        for gid, teams in per.items():
            d = act[gid]["date"]
            for team in (act[gid]["home"], act[gid]["away"]):
                f, a_, fa, aa = teams.get(team, [0.0, 0.0, 0.0, 0.0])
                self.games[team].append((d, f, a_))
                self.games_adj[team].append((d, fa, aa))
        for k in self.games:
            self.games[k].sort(); self.games_adj[k].sort()
        self.n_shots = len(feats)
        self._cache: Dict[Tuple, Any] = {}

    @staticmethod
    def _home_lead_before_kept(pbp, X) -> List[int]:
        """Home lead BEFORE each Fenwick play the production parser keeps (same filters), walking
        every play and updating on goal events (which carry the score AFTER the goal)."""
        home_id = (pbp.get("homeTeam") or {}).get("id")
        hs = as_ = 0
        out = []
        for pl in pbp.get("plays") or []:
            d = pl.get("details") or {}
            kept = False
            if pl.get("typeDescKey") in X._FENWICK_TYPES and d.get("eventOwnerTeamId") is not None \
                    and d.get("xCoord") is not None and d.get("yCoord") is not None:
                try:
                    float(d["xCoord"]); float(d["yCoord"]); tid = int(d["eventOwnerTeamId"])
                    kept = X._situation_state(pl.get("situationCode"), shooter_is_home=(tid == home_id)) is not None
                except (TypeError, ValueError):
                    kept = False
            if kept:
                out.append(hs - as_)
            if pl.get("typeDescKey") == "goal" and d.get("homeScore") is not None:
                hs, as_ = int(d["homeScore"]), int(d["awayScore"])
        return out

    def rate(self, team: str, date: str, arm: str, half_life: Optional[float], adjusted: bool = False):
        """(xgf60, xga60) from the team's games strictly before `date` (all 2025-26 for the 2026-27
        arm), each weighted 0.5 ** (games_ago / half_life); half_life None = plain season average."""
        key = (team, date, arm, half_life, adjusted)
        if key in self._cache:
            return self._cache[key]
        g = (self.games_adj if adjusted else self.games).get(team, [])
        if not arm.startswith("current"):
            g = [x for x in g if x[0] < date]
        if not g:
            res = (None, None)
        else:
            n = len(g)
            w = [1.0 if half_life is None else 0.5 ** ((n - 1 - i) / half_life) for i in range(n)]
            W = sum(w)
            res = (sum(wi * x[1] for wi, x in zip(w, g)) / W, sum(wi * x[2] for wi, x in zip(w, g)) / W)
        self._cache[key] = res
        return res


def gsax_factor(pid: Optional[int], hist: "GsaxHistory", date: str, arm: str, k: float) -> Optional[float]:
    """Shrunk goals-allowed / xG-faced ratio of the goalie, relative to the as-of league ratio.
    k is in xG units (a goalie with k xG faced is halfway to his own ratio). >1 = worse goalie."""
    k, w = k if isinstance(k, tuple) else (k, 0.0)
    by_pid, lr = hist.asof(date, arm)
    if pid is None or pid not in by_pid:
        return None
    xg, ga = by_pid[pid]
    if w and pid in hist.prior:
        pxg, pga = hist.prior[pid]
        xg += w * pxg; ga += w * pga
    r = (ga + k * lr) / (xg + k)
    return r / lr


def _key_from_full(name: str) -> Optional[str]:
    """first initial + LAST token; the boxscore's 'U. Luukkonen' and Daily Faceoff's
    'Ukko-Pekka Luukkonen' must meet (hyphens normalize to spaces in `_norm`)."""
    parts = _norm(name).split()
    return f"{parts[0][0]} {parts[-1]}" if len(parts) >= 2 else None


def starter_picks(act, gl, lg_dates, dfo_dir: Path) -> Dict[str, Any]:
    """Pregame starter per (gid, team abbr) from two honest sources, with accuracy vs the actual:
      rotation -- most starts in the team's last 10 games, flipped to the next goalie on the second
                  night of a back-to-back when the top goalie started the night before (as-of);
      dfo      -- Daily Faceoff's starter IF its news was posted BEFORE puck drop and the status is
                  Confirmed or Likely; otherwise the rotation pick (counted as a fallback)."""
    hist = defaultdict(list)
    keyhist = defaultdict(list)   # team -> [(date, goalie key)] of every goalie who PLAYED (as-of use only)
    for gid, r in sorted(act.items(), key=lambda kv: (kv[1]["date"], kv[0])):
        if r["season"] != BGL.SEASON_PREV:
            continue
        for ab in (r["home"], r["away"]):
            st = [x["pid"] for x in gl.get(gid, {}).get(ab, []) if x["starter"]]
            if st:
                hist[ab].append((r["date"], st[0]))
            for x in gl.get(gid, {}).get(ab, []):
                if x["shots"] > 0:
                    keyhist[ab].append((r["date"], x["key"]))

    def known_before(ab, key, date, season):
        # a goalie this team used strictly before the date (any 2025-26 game for the 2026-27 arm)
        return any(k == key and (d < date or season != BGL.SEASON_PREV) for d, k in keyhist[ab])

    rot: Dict[Tuple[str, str], Any] = {}
    dfo: Dict[Tuple[str, str], Any] = {}
    stats = Counter()
    dfo_cache: Dict[str, Optional[Dict]] = {}
    for gid, r in act.items():
        for side, ab in (("home", r["home"]), ("away", r["away"])):
            opp = r["away"] if side == "home" else r["home"]
            osd = "away" if side == "home" else "home"
            h = hist[ab]
            if r["season"] == BGL.SEASON_PREV:
                i = bisect.bisect_left([d for d, _ in h], r["date"])
                prior = h[:i]
            else:
                prior = h
            pick = None
            if prior:
                last10 = Counter(p for _, p in prior[-10:])
                top = last10.most_common(1)[0][0]
                pick = top
                if is_b2b(ab, r["date"], lg_dates) and prior[-1][1] == top:
                    alts = [p for p, _ in last10.most_common() if p != top]
                    if alts:
                        pick = alts[0]
            rot[(gid, ab)] = pick
            if r["date"] not in dfo_cache:
                dfo_cache[r["date"]] = BGL._rj(dfo_dir / f"{r['date']}.json")
            page = dfo_cache[r["date"]]
            chosen, why = pick, "fallback_no_page"
            if page and page.get("games") is not None:
                why = "fallback_game_not_listed"
                for gm in page["games"]:
                    teams = {BGL._abbr_of(gm.get("home_team") or ""), BGL._abbr_of(gm.get("away_team") or "")}
                    if teams != {ab, opp}:
                        continue
                    # the page's goalie slot is NOT reliable per side (measured: 243 swaps); take the
                    # named goalie this team has used before the date, else the slot the page gives
                    cand = []
                    for s_ in ("home", "away"):
                        k = _key_from_full(gm.get(f"{s_}_goalie") or "")
                        if k and known_before(ab, k, r["date"], r["season"]):
                            cand.append(s_)
                    if len(cand) != 1:
                        # Measured: the ARCHIVED pages name goalies who dressed for neither team
                        # (2025-11-01 WPG-PIT lists Skinner, then an EDM goalie). A name this team has
                        # never used before the date cannot be verified as-of -> rotation fallback.
                        why = "fallback_dfo_unverifiable_name"
                        break
                    slot = cand[0]
                    status = str(gm.get(f"{slot}_status") or "")
                    at = str(gm.get(f"{slot}_news_at") or "")
                    if status not in ("Confirmed", "Likely"):
                        why = f"fallback_status_{status or 'none'}"
                    elif not at or at[:19] >= r["start"][:19]:
                        why = "fallback_posted_after_start"
                    else:
                        chosen, why = _key_from_full(gm.get(f"{slot}_goalie") or ""), f"dfo_{status.lower()}"
                    break
            dfo[(gid, ab)] = chosen
            stats[why] += 1
            if r["arm"] == "regular" and r["date"] >= "2025-11-01":
                actual = [x for x in gl.get(gid, {}).get(ab, []) if x["starter"]]
                if actual:
                    a0 = actual[0]
                    stats["acc_rotation_hit" if pick == a0["pid"] else "acc_rotation_miss"] += 1
                    hit = (chosen == a0["key"]) if isinstance(chosen, str) else (chosen == a0["pid"])
                    stats[f"acc_dfo_{'hit' if hit else 'miss'}"] += 1
                    if why.startswith("dfo_"):
                        stats[f"acc_{why}_{'hit' if hit else 'miss'}"] += 1
    return {"rotation": rot, "dfo": dfo, "stats": dict(stats)}


GOALIE_PRIOR: Dict[int, Tuple[float, float]] = {}  # pid -> (shots, ga), PRIOR season (2024-25), as-of for all of 2025-26


def load_goalie_prior(path: Path) -> None:
    d = BGL._rj(path) or {}
    for x in d.get("data") or []:
        GOALIE_PRIOR[int(x["playerId"])] = (float(x.get("shotsAgainst") or 0), float(x.get("goalsAgainst") or 0))


def goalie_factor(stats, sv_lg: float, kw) -> float:
    """kw = (k shrink shots, w prior-season weight). Current-season as-of shots/GA plus w x the
    goalie's 2024-25 shots/GA (NHL stats API), shrunk toward the as-of league save% with k shots."""
    k, w = kw if isinstance(kw, tuple) else (kw, 0.0)
    sh, ga = float(stats[0]), float(stats[1])
    pid = stats[2] if len(stats) > 2 else None
    if w and pid in GOALIE_PRIOR:
        psh, pga = GOALIE_PRIOR[pid]
        sh += w * psh; ga += w * pga
    sv = ((sh - ga) + k * sv_lg) / (sh + k)
    return (1 - sv) / (1 - sv_lg)


def last_game_dates(act):
    by = defaultdict(list)
    for r in act.values():
        by[r["home"]].append(r["date"]); by[r["away"]].append(r["date"])
    for k in by:
        by[k].sort()
    return by


def is_b2b(team, date, lg):
    from datetime import date as D
    lst = lg.get(team, [])
    i = bisect.bisect_left(lst, date)
    if i == 0:
        return False
    y, m, d = map(int, date.split("-")); y2, m2, d2 = map(int, lst[i - 1].split("-"))
    return (D(y, m, d) - D(y2, m2, d2)).days == 1


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="C:/tmp/nhllines_after")
    ap.add_argument("--roots", default="C:/tmp/nhlprops/bt_after")
    ap.add_argument("--src", default=None)
    ap.add_argument("--report", default=None)
    ap.add_argument("--min-n", type=int, default=100)
    ap.add_argument("--goalie-prior", default="C:/tmp/nhllines/goalie_prior/20242025.json")
    ap.add_argument("--fetch-prior-pbp", action="store_true", help="cache 2024-25 play-by-play into <out>/pbp_2024 and exit")
    ap.add_argument("--dfo", default=None, help="dir of fetch_nhl_confirmed_goalies.py outputs (default <out>/dfo)")
    a = ap.parse_args()
    out, roots = Path(a.out), Path(a.roots)
    src = Path(a.src) if a.src else BGL._main_worktree() / "data" / "nhl_source"
    if a.fetch_prior_pbp:
        print(f"prior pbp done: {fetch_prior_pbp(out)}")
        return 0
    act = json.loads((out / "actuals.json").read_text(encoding="utf-8"))
    sim = json.loads((out / "sim" / "games.json").read_text(encoding="utf-8"))
    BOOK.update(json.loads((out / "book.json").read_text(encoding="utf-8")) if (out / "book.json").exists() else {})
    print(f"book closes loaded: {len(BOOK)} games")
    from syndicate.features.nhl.sim_engine.hockeysim.adapters import game_seed

    games = [g for d in sim["dates"] for g in d["games"] if g["gid"] in act]
    games.sort(key=lambda g: (g["date"], g["gid"]))
    asof = BGL.AsOf(act)

    # pass 1: production-lambda summaries for the machinery fits (model and baseline separately)
    m_rt, m_tie, m_a1, b_rt, b_tie, b_a1 = {}, {}, {}, {}, {}, {}
    base_lams: Dict[str, Tuple[float, float, float]] = {}
    stc = {}
    for g in games:
        r = act[g["gid"]]
        seed = game_seed(g["date"], g["gid"])
        h, aa = draws(g["hp"], g["ap"], seed)
        p = probs(h, aa)
        m_rt[g["gid"]], m_tie[g["gid"]], m_a1[g["gid"]] = p["reg_total"], p["p_reg_tie"], p["abs1_nontie"]
        key = (g["date"], r["arm"])
        if key not in stc:
            stc[key] = asof.state(*key)
        st = stc[key]
        bl = BGL.baseline_lams(st, r["home"], r["away"])
        if bl is not None:
            base_lams[g["gid"]] = (bl[0], bl[1], st["p1_share"])
            hb, ab_ = draws(BGL._periods(bl[0], st["p1_share"]), BGL._periods(bl[1], st["p1_share"]), seed)
            pb = probs(hb, ab_)
            b_rt[g["gid"]], b_tie[g["gid"]], b_a1[g["gid"]] = pb["reg_total"], pb["p_reg_tie"], pb["abs1_nontie"]
    fit_m = Fitter(act, m_rt, m_tie, m_a1)
    fit_b = Fitter(act, b_rt, b_tie, b_a1)

    gl = goalie_lines(act, src, roots)
    gh = GoalieHistory(act, gl)
    lg_dates = last_game_dates(act)
    gh_cache: Dict[Tuple[str, str], Any] = {}

    # hyper-parameters tuned on games BEFORE EVAL_START only (grid; ML log-loss), then frozen
    picks = starter_picks(act, gl, lg_dates, Path(a.dfo) if a.dfo else out / "dfo")
    print(f"starter sources: {picks['stats']}")

    mach_cache: Dict[str, Dict] = {}

    def run(k_goalie, rest: Optional[Dict], source: str, window=None, metric: str = "sv"):
        rows = []
        miss = Counter()
        for g in games:
            if window and not window(g["date"]):
                continue
            r = act[g["gid"]]
            if g["gid"] not in base_lams:
                miss["no_baseline"] += 1
                continue
            seed = game_seed(g["date"], g["gid"])
            fm, fb = fit_m.at(g["date"], r["arm"]), fit_b.at(g["date"], r["arm"])
            hp, apl = list(g["hp"]), list(g["ap"])
            rec = {"gid": g["gid"], "date": g["date"], "arm": r["arm"], "act": r, "book": BOOK.get(g["gid"], {})}
            cl = rec["book"].get("total_line")
            s = fm["s"]
            if g["gid"] not in mach_cache:
                m_ = {}
                h0, a0 = draws(hp, apl, seed)
                m_["V0"] = probs(h0, a0, full_settlement=False, close=cl)
                m_["V1"] = probs(h0, a0, q_ot=fm["q_ot"], close=cl)
                hs, as_ = draws([x * s for x in hp], [x * s for x in apl], seed)
                m_["V2"] = probs(hs, as_, q_ot=fm["q_ot"], close=cl)
                m_["V3"] = probs(hs, as_, q_ot=fm["q_ot"], delta=fm["delta"], close=cl)
                m_["V4"] = probs(hs, as_, q_ot=fm["q_ot"], delta=fm["delta"], e=fm["e"], seed=seed, close=cl)
                # baselines
                bh, ba, p1s = base_lams[g["gid"]]
                hb, abb = draws(BGL._periods(bh, p1s), BGL._periods(ba, p1s), seed)
                m_["B0"] = probs(hb, abb, full_settlement=False, close=cl)
                sb = fb["s"]
                hb2, ab2 = draws(BGL._periods(bh * sb, p1s), BGL._periods(ba * sb, p1s), seed)
                m_["B4"] = probs(hb2, ab2, q_ot=fb["q_ot"], delta=fb["delta"], e=fb["e"], seed=seed, close=cl)
                mach_cache[g["gid"]] = m_
            rec.update(mach_cache[g["gid"]])
            # information layers
            if k_goalie is not None:
                ck = (g["date"], r["arm"])
                if ck not in gh_cache:
                    gh_cache[ck] = gh.asof(*ck)
                by_key, by_pid, sv_lg = gh_cache[ck]
                fac = {}
                for side, ab in (("home", r["home"]), ("away", r["away"])):
                    if source == "oracle":
                        st_ = [x for x in gl.get(g["gid"], {}).get(ab, []) if x["starter"]]
                        stats = by_pid.get(st_[0]["pid"]) if st_ else None
                    elif source == "proj":
                        starters = projected_starters(roots, g["date"])
                        key = starters.get(ab)
                        stats = (by_key.get((ab, key)) or by_key.get(("*", key))) if key else None
                    else:  # rotation | dfo (pregame-provable confirmed/likely, else rotation)
                        pk = picks[source].get((g["gid"], ab))
                        stats = by_pid.get(pk) if isinstance(pk, int) else (
                            (by_key.get((ab, pk)) or by_key.get(("*", pk))) if pk else None)
                    if metric == "gsax":
                        pid = None
                        if stats is not None and len(stats) > 2:
                            pid = stats[2]
                        f_ = gsax_factor(pid, gsx, g["date"], r["arm"], k_goalie) if gsx else None
                        if f_ is None:
                            miss[f"gsax_unmatched_{source}"] += 1
                            fac[side] = 1.0
                        else:
                            fac[side] = f_
                    elif stats is None:
                        miss[f"goalie_unmatched_{source}"] += 1
                        fac[side] = 1.0
                    else:
                        fac[side] = goalie_factor(stats, sv_lg, k_goalie)
                # the HOME goalie scales the AWAY lambda and vice versa
                rec["fac"] = dict(fac)
                hp5 = [x * s * fac["away"] for x in hp]
                ap5 = [x * s * fac["home"] for x in apl]
                if rest:
                    bh2b, ab2b = is_b2b(r["home"], g["date"], lg_dates), is_b2b(r["away"], g["date"], lg_dates)
                    hp5 = [x * (rest["gf"] if bh2b else 1) * (rest["ga"] if ab2b else 1) for x in hp5]
                    ap5 = [x * (rest["gf"] if ab2b else 1) * (rest["ga"] if bh2b else 1) for x in ap5]
                h5, a5 = draws(hp5, ap5, seed)
                rec["VX"] = probs(h5, a5, q_ot=fm["q_ot"], delta=fm["delta"], e=fm["e"], seed=seed, close=cl)
            rows.append(rec)
        return rows, miss

    def ll_ml(rows, key):
        return statistics.fmean(BGL._ll(x[key]["p_home_ml"], 1 if x["act"]["final_h"] > x["act"]["final_a"] else 0) for x in rows)

    pre = lambda d: d < EVAL_START
    post = lambda d: d >= EVAL_START
    tune = {}
    load_goalie_prior(Path(a.goalie_prior))
    print(f"goalie prior: {len(GOALIE_PRIOR)} goalies from {a.goalie_prior}")
    for k in (300.0, 1000.0, 3000.0, 10000.0):
        for w in (0.0, 0.5, 1.0):
            rows, _ = run((k, w), None, "dfo", window=pre)
            tune[(k, w)] = ll_ml(rows, "VX")
    k_best = min(tune, key=tune.get)
    # rest multipliers: residual ratio of B2B teams vs V4 expected goals, games before EVAL_START
    rows_pre, _ = run(k_best, None, "dfo", window=pre)
    gf_r, ga_r = [], []
    for x in rows_pre:
        r = x["act"]
        for side, opp, mine, theirs in (("home", "away", "reg_h", "reg_a"), ("away", "home", "reg_a", "reg_h")):
            team = r[side]
            if is_b2b(team, x["date"], lg_dates):
                gf_r.append((r[mine], None)); ga_r.append((r[theirs], None))
    # expected regulation goals per side under V4 are not stored per side; use league-relative ratio
    rest = None
    if gf_r:
        lg_side = statistics.fmean((x["act"]["reg_h"] + x["act"]["reg_a"]) / 2 for x in rows_pre)
        kk = 200.0
        n = len(gf_r)
        gf = (sum(v for v, _ in gf_r) + kk * lg_side) / (n + kk) / lg_side
        ga = (sum(v for v, _ in ga_r) + kk * lg_side) / (n + kk) / lg_side
        rest = {"gf": gf, "ga": ga, "n": n}
    print(f"tuned (pre-{EVAL_START}): goalie k={k_best} (ML log-loss by k: { {k: round(v, 5) for k, v in tune.items()} }); rest={rest}")

    results = {}
    gsx = GsaxHistory(act, src)
    print(f"gsax history: {gsx.stats}")
    prior_stats = gsx.load_prior(out / "pbp_2024")
    print(f"gsax prior (2024-25): {prior_stats}")
    tune_g = {}
    for kg in (2.0, 5.0, 10.0, 20.0, 40.0, 80.0):
        rows_, _ = run(kg, None, "dfo", window=pre, metric="gsax")
        tune_g[kg] = ll_ml(rows_, "VX")
    kg_best = min(tune_g, key=tune_g.get)
    print(f"tuned GSAx k (xG units, pre-{EVAL_START}): {kg_best}; ML log-loss by k: { {k: round(v, 5) for k, v in tune_g.items()} }")

    tune_p = {}
    for kg in (20.0, 40.0, 80.0, 160.0):
        for w in (0.25, 0.5, 1.0):
            rows_, _ = run((kg, w), None, "dfo", window=pre, metric="gsax")
            tune_p[(kg, w)] = ll_ml(rows_, "VX")
    kp_best = min(tune_p, key=tune_p.get)
    print(f"tuned GSAx+prior (k, w) pre-{EVAL_START}: {kp_best}; ML log-loss: { {str(k): round(v, 5) for k, v in tune_p.items()} }")

    for label, kw in (("V8", dict(k_goalie=kp_best, rest=None, source="dfo", metric="gsax")),
                      ("V8o", dict(k_goalie=kp_best, rest=None, source="oracle", metric="gsax")),
                      ("V7", dict(k_goalie=kg_best, rest=None, source="dfo", metric="gsax")),
                      ("V7o", dict(k_goalie=kg_best, rest=None, source="oracle", metric="gsax")),
                      ("V5", dict(k_goalie=k_best, rest=None, source="proj")),
                      ("V5r", dict(k_goalie=k_best, rest=None, source="rotation")),
                      ("V5c", dict(k_goalie=k_best, rest=None, source="dfo")),
                      ("V6", dict(k_goalie=k_best, rest=rest, source="dfo")),
                      ("V5o", dict(k_goalie=k_best, rest=None, source="oracle"))):
        rows, miss = run(**kw)
        results[label] = (rows, miss)

    # ---- recency-weighted xG (H8)
    from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyTeamFeatures as HTF
    from syndicate.features.nhl.sim_engine.hockeysim.projection import project_game
    txg = TeamXg(act, src, gsx)
    print(f"team xG: {txg.n_shots} Fenwick shots (incl. empty-net), {len(txg.games)} teams")

    print(f"score adjustment: walk {dict(txg.score_walk)}; w_d (lead d -> weight) { {d: round(v, 4) for d, v in txg.w.items()} }")

    def lam_source(half_life, adjusted=False):
        out_l = {}
        for g in games:
            r = act[g["gid"]]
            hf, ha = txg.rate(r["home"], g["date"], r["arm"], half_life, adjusted)
            af, aa = txg.rate(r["away"], g["date"], r["arm"], half_life, adjusted)
            pr = project_game(HTF(name=r["home"], xgf_per_60=hf, xga_per_60=ha),
                              HTF(name=r["away"], xgf_per_60=af, xga_per_60=aa))
            out_l[g["gid"]] = (list(pr.period_home_lambdas), list(pr.period_away_lambdas))
        return out_l

    def v4_from(lams, fac_by_gid=None, window=None):
        rt, ti, a1 = {}, {}, {}
        for g in games:
            hp_, ap_ = lams[g["gid"]]
            p_ = probs(*draws(hp_, ap_, game_seed(g["date"], g["gid"])))
            rt[g["gid"]], ti[g["gid"]], a1[g["gid"]] = p_["reg_total"], p_["p_reg_tie"], p_["abs1_nontie"]
        fit = Fitter(act, rt, ti, a1)
        res_ = {}
        for g in games:
            if window and not window(g["date"]):
                continue
            r = act[g["gid"]]
            f = fit.at(g["date"], r["arm"])
            hp_, ap_ = lams[g["gid"]]
            fa = (fac_by_gid or {}).get(g["gid"], {"home": 1.0, "away": 1.0})
            seed = game_seed(g["date"], g["gid"])
            h_, a_ = draws([x * f["s"] * fa["away"] for x in hp_], [x * f["s"] * fa["home"] for x in ap_], seed)
            res_[g["gid"]] = probs(h_, a_, q_ot=f["q_ot"], delta=f["delta"], e=f["e"], seed=seed,
                                   close=BOOK.get(g["gid"], {}).get("total_line"))
        return res_

    def ll_of(pmap):
        return statistics.fmean(BGL._ll(pmap[gid]["p_home_ml"], 1 if act[gid]["final_h"] > act[gid]["final_a"] else 0)
                                for gid in pmap)

    tune_h = {}
    for hl in (5.0, 10.0, 20.0, 40.0, None):
        tune_h[str(hl)] = ll_of(v4_from(lam_source(hl), window=pre))
    h_best_s = min(tune_h, key=tune_h.get)
    h_best = None if h_best_s == "None" else float(h_best_s)
    print(f"tuned recency half-life (games, pre-{EVAL_START}): {h_best_s}; ML log-loss: { {k: round(v, 5) for k, v in tune_h.items()} }")
    lam_ctrl = lam_source(None)
    lam_rec = lam_source(h_best if h_best is not None else 20.0)  # if the control wins, still score a recency arm
    v9c = v4_from(lam_ctrl)
    v9 = v4_from(lam_rec)
    fac8 = {x["gid"]: x.get("fac", {"home": 1.0, "away": 1.0}) for x in results["V8"][0]}
    v9g = v4_from(lam_rec, fac_by_gid=fac8)
    v10 = v4_from(lam_source(None, adjusted=True))
    v10r = v4_from(lam_source(h_best if h_best is not None else 20.0, adjusted=True))

    rows_all = results["V6"][0]
    others = {lab: {x["gid"]: x for x in results[lab][0]} for lab in ("V5", "V5r", "V5c", "V5o", "V7", "V7o", "V8", "V8o")}
    for x in rows_all:
        for lab, idx in others.items():
            x[lab] = idx[x["gid"]]["VX"]
        x["V6"] = x.pop("VX")
        x["V9c"], x["V9"], x["V9g"] = v9c[x["gid"]], v9[x["gid"]], v9g[x["gid"]]
        x["V10"], x["V10r"] = v10[x["gid"]], v10r[x["gid"]]

    report = {"score_adj_w": txg.w, "score_walk": dict(txg.score_walk), "recency_half_life": h_best_s, "recency_tune": tune_h,
              "gsax_prior_kw": kp_best, "gsax_prior_tune": {str(k): v for k, v in tune_p.items()}, "gsax_prior_stats": prior_stats,
              "k_goalie": k_best, "gsax_k": kg_best, "gsax_tune": tune_g, "gsax_stats": gsx.stats,
              "gsax_join": {k: dict(v[1]) for k, v in results.items() if k.startswith("V7")}, "tune": {str(k): v for k, v in tune.items()}, "rest": rest, "starter_sources": picks["stats"],
              "goalie_join": {k: dict(v[1]) for k, v in results.items()},
              "fits_sample": {d: fit_m.at(d, "regular") for d in ("2025-11-15", "2026-01-01", "2026-03-01")},
              "windows": {}}
    for wname, wf in (("EVAL 2026-01-01..04-16 (out of sample)", lambda x: x["arm"] == "regular" and x["date"] >= EVAL_START),
                      ("FULL regular 11-01..04-16", lambda x: x["arm"] == "regular"),
                      ("PLAYOFFS (holdout)", lambda x: x["arm"] == "playoff")):
        R = [x for x in rows_all if wf(x)]
        report["windows"][wname] = score(R, a.min_n)
    (out / "experiments.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    for w, rep in report["windows"].items():
        print(f"\n=== {w}: n={rep['n']}")
        for line in rep["lines"]:
            print("  " + line)
    if a.report:
        write_md(report, Path(a.report))
    return 0


VARIANTS = ["V0", "V1", "V2", "V3", "V4", "V5", "V5r", "V5c", "V6", "V5o", "V7", "V7o", "V8", "V8o", "V9c", "V9", "V9g", "V10", "V10r"]


def score(R: List[Dict], min_n: int) -> Dict:
    lines = []
    res = {"n": len(R), "markets": {}}
    if not R:
        return {"n": 0, "lines": [], "markets": {}}
    y = {
        "ML home": (lambda x: 1 if x["act"]["final_h"] > x["act"]["final_a"] else 0, "p_home_ml"),
        "REG tie": (lambda x: 1 if x["act"]["reg_h"] == x["act"]["reg_a"] else 0, "p_reg_tie"),
        "REG home": (lambda x: 1 if x["act"]["reg_h"] > x["act"]["reg_a"] else 0, "p_reg_home"),
        "PL home -1.5": (lambda x: 1 if x["act"]["final_h"] - x["act"]["final_a"] > 1.5 else 0, "p_home_m15"),
        "PL away -1.5": (lambda x: 1 if x["act"]["final_a"] - x["act"]["final_h"] > 1.5 else 0, "p_away_m15"),
        "OVER 5.5": (lambda x: 1 if x["act"]["final_h"] + x["act"]["final_a"] > 5.5 else 0, "over_5.5"),
        "OVER 6.5": (lambda x: 1 if x["act"]["final_h"] + x["act"]["final_a"] > 6.5 else 0, "over_6.5"),
    }
    for mk, (yf, pk) in y.items():
        ent = {}
        freq = statistics.fmean(yf(x) for x in R)
        for v in VARIANTS + ["B0", "B4"]:
            if v not in R[0]:
                continue
            br = statistics.fmean(BGL._brier(x[v][pk], yf(x)) for x in R)
            mp = statistics.fmean(x[v][pk] for x in R)
            e = {"brier": br, "mean_p": mp}
            for bn in ("B0", "B4"):
                if v.startswith("B"):
                    continue
                d = BGL._boot_diff([(x["date"], BGL._brier(x[v][pk], yf(x)) - BGL._brier(x[bn][pk], yf(x))) for x in R])
                e[f"d_{bn}"] = d
                e[f"verdict_{bn}"] = BGL._verdict(*d, len(R), min_n)
            ent[v] = e
        res["markets"][mk] = ent
        lines.append(f"{mk} (freq {freq:.3f}; B0 Brier {ent['B0']['brier']:.4f} meanP {ent['B0']['mean_p']:.3f}; "
                     f"B4 {ent['B4']['brier']:.4f} meanP {ent['B4']['mean_p']:.3f})")
        for v in VARIANTS:
            if v not in ent:
                continue
            e = ent[v]
            lines.append(f"   {v:<4} Brier {e['brier']:.4f} meanP {e['mean_p']:.3f} | vs B0 {e['d_B0'][0]:+.4f} "
                         f"[{e['d_B0'][1]:+.4f},{e['d_B0'][2]:+.4f}] {e['verdict_B0']:<14} | vs B4 {e['d_B4'][0]:+.4f} "
                         f"[{e['d_B4'][1]:+.4f},{e['d_B4'][2]:+.4f}] {e['verdict_B4']}")
    def pl_at_book(x, v):
        ln = x["book"].get("pl_line_home")
        if ln is None:
            return None
        return x[v]["p_home_m15"] if ln < 0 else 1.0 - x[v]["p_away_m15"]

    book_mk = {
        "ML vs BOOK": (lambda x: x["book"].get("ml_home"), lambda x, v: x[v]["p_home_ml"],
                       lambda x: 1 if x["act"]["final_h"] > x["act"]["final_a"] else 0),
        "PL home @book line vs BOOK": (lambda x: x["book"].get("p_home_pl"), pl_at_book,
                                       lambda x: None if x["book"].get("pl_line_home") is None else
                                       (1 if (x["act"]["final_h"] - x["act"]["final_a"]) > -x["book"]["pl_line_home"] else 0)),
        "OVER @close vs BOOK": (lambda x: x["book"].get("p_over"), lambda x, v: x[v].get("over_close"),
                                lambda x: None if x["book"].get("total_line") is None or (
                                    float(x["book"]["total_line"]).is_integer() and
                                    x["act"]["final_h"] + x["act"]["final_a"] == x["book"]["total_line"])
                                else int(x["act"]["final_h"] + x["act"]["final_a"] > x["book"]["total_line"])),
    }
    for mk, (pb, pm, yf) in book_mk.items():
        S = [x for x in R if pb(x) is not None and yf(x) is not None and pm(x, "V0") is not None]
        if not S:
            continue
        bb = statistics.fmean(BGL._brier(pb(x), yf(x)) for x in S)
        lines.append(f"{mk} (n={len(S)}; book Brier {bb:.4f})")
        for v in VARIANTS + ["B0", "B4"]:
            if v not in S[0]:
                continue
            d = BGL._boot_diff([(x["date"], BGL._brier(pm(x, v), yf(x)) - BGL._brier(pb(x), yf(x))) for x in S])
            dl = BGL._boot_diff([(x["date"], BGL._ll(pm(x, v), yf(x)) - BGL._ll(pb(x), yf(x))) for x in S])
            vd = BGL._verdict(*d, len(S), 100)
            res["markets"].setdefault(mk, {})[v] = {"n": len(S), "d_brier": d, "d_ll": dl, "verdict": vd}
            lines.append(f"   {v:<4} dBrier vs book {d[0]:+.4f} [{d[1]:+.4f},{d[2]:+.4f}] dLL {dl[0]:+.4f} [{dl[1]:+.4f},{dl[2]:+.4f}] {vd}")

    # paired head-to-heads the pre-written hypotheses name (H8: recency vs its control; H9: score
    # adjustment vs the unadjusted control, with and without recency)
    yml = lambda x: 1 if x["act"]["final_h"] > x["act"]["final_a"] else 0
    for a_, b_ in (("V9", "V9c"), ("V10", "V9c"), ("V10r", "V9"), ("V10r", "V8")):
        if a_ in R[0] and b_ in R[0]:
            d = BGL._boot_diff([(x["date"], BGL._brier(x[a_]["p_home_ml"], yml(x)) - BGL._brier(x[b_]["p_home_ml"], yml(x))) for x in R])
            vd = BGL._verdict(*d, len(R), min_n)
            res["markets"].setdefault("PAIRED ML", {})[f"{a_}-{b_}"] = {"d_brier": d, "verdict": vd}
            lines.append(f"PAIRED ML {a_} vs {b_}: dBrier {d[0]:+.4f} [{d[1]:+.4f},{d[2]:+.4f}] {vd}")

    # totals point accuracy (settled full game)
    tot = lambda x: x["act"]["final_h"] + x["act"]["final_a"]
    lines.append("TOTAL settled (MAE / bias)")
    for v in VARIANTS + ["B0", "B4"]:
        if v not in R[0]:
            continue
        err = [(x["date"], x[v]["full_total"] - tot(x)) for x in R]
        mae = statistics.fmean(abs(e) for _, e in err)
        bias = BGL._boot_diff(err)
        extra = ""
        if not v.startswith("B"):
            d = BGL._boot_diff([(x["date"], abs(x[v]["full_total"] - tot(x)) - abs(x["B4"]["full_total"] - tot(x))) for x in R])
            extra = f" | dMAE vs B4 {d[0]:+.4f} [{d[1]:+.4f},{d[2]:+.4f}]"
        lines.append(f"   {v:<4} MAE {mae:.3f} bias {bias[0]:+.3f} [{bias[1]:+.3f},{bias[2]:+.3f}]{extra}")
        res["markets"].setdefault("TOTAL", {})[v] = {"mae": mae, "bias": bias}
    res["lines"] = lines
    return res


def write_md(rep: Dict, path: Path) -> None:
    L = ["# NHL game-line model experiments (generated)", "",
         f"goalie shrink k (tuned before {EVAL_START}): {rep['k_goalie']}; rest multipliers: {rep['rest']}",
         f"goalie join misses: `{rep['goalie_join']}`", f"machinery fits (as-of samples): `{rep['fits_sample']}`", ""]
    for w, r in rep["windows"].items():
        L += [f"## {w} (n={r['n']})", "", "```"] + r["lines"] + ["```", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
