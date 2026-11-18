"""Understat outage: what does FROZEN big-5 team history cost, and do the in-repo fallbacks beat it?

Lane `understat-fallback-backtest` (2026-11-18). Pre-registered in `.syndicate/lanes.md` (`13d4bb9f2`)
before any arm was scored. Research only: reads copies of the fleet's inputs, writes to `--out-dir`.

WHY. understat.com has served a maintenance page since 2026-11-03, so `teams_2026.csv` for the big 5
(epl, la_liga, bundesliga, serie_a, ligue_1) ends on 2026-10-31 and `build_soccer_artifacts.
_load_team_ratings` keeps pricing on it (last 45 Understat xG rows per team, no freshness check).

STAGE A (this script): a CROSS-FITTED Poisson link on every eligible match. For each arm the
production rating code builds each club's (attack_rating, defense_rating) as of the match day --
`compute_team_ratings`, then production's `_fill_promoted` + `_gate_few_match` with the fleet's
`SYNDICATE_SOCCER_CURRENT_HISTORY=1` and RATING V2 off (read from the running roles 2026-11-18) --
and a per-league link `log lam_home = mu + eta + k*(att_h - def_a)`, `log lam_away = mu + k*(att_a -
def_h)` is fitted on the OTHER half of match days (2-fold by day parity) and scored on this half.
Re-fitting mu/eta/k per arm is the "re-fit what was absorbing it" of the model engine standard: it
asks how much INFORMATION each rating input carries once its level and dispersion are re-fitted. Stage
B (`understat_staleness_simcheck.py`) checks on a sample that the real SoccerSim moves its
probabilities the way the link does, because a link result once flipped in the sim (RATING V2,
findings 2026-10-19).

ARMS (each a ratings source as of match day d):
- U<k>: Understat rows dated before the freeze cutoff c_k(d), window 45 (production's path). c_k(d)
  is the date of the (k * N/2)-th most recent league match before d, so at least k league rounds
  are missing. U0 is "current".
- G<W>: production's goals path (`team_rows_from_match_history` on football-data matches +
  espn_match_stats), window W; G90 is the window the four goals-rated leagues use. GR = W picked on the
  training fold from {45, 60, 90, 120}.
- S<k>: Understat rows before c_k(d) plus, for each match in [c_k(d), d), a goals-as-xG row carrying
  ONLY the fields Understat rows carry that the engine reads (xg_for/xg_against = goals, goals_for/
  goals_against, points), so no new metric enters the engine. Window 45.

POPULATIONS: hist = big-5 matches 2025-09-15..2026-06-30 and 2026-09-15..2026-10-31 (Understat
current exists); now = matches from 2026-11-01 (Understat frozen at 10-31 in every U arm; the arms
that differ are G and S).
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date as dt_date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# The fleet's values, read from the running roles' env on 2026-11-18 (refresh-worker, live-odds-worker, web).
os.environ["SYNDICATE_SOCCER_CURRENT_HISTORY"] = "1"
os.environ.pop("SYNDICATE_SOCCER_RATING_V2", None)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.build_soccer_artifacts import _fill_promoted, _gate_few_match  # noqa: E402
from syndicate.features.soccer.features.loaders import (  # noqa: E402
    _as_iso_day,
    _rating_for,
    compute_team_ratings,
    team_rows_from_match_history,
)
from syndicate.features.soccer.features.team_names import match_team_name  # noqa: E402
from syndicate.features.soccer.ingestion.match_history import normalize_match_history  # noqa: E402

LEAGUES = ("epl", "la_liga", "bundesliga", "serie_a", "ligue_1")
FD_CODES = {"epl": "E0", "la_liga": "SP1", "bundesliga": "D1", "serie_a": "I1", "ligue_1": "F1"}
U_KS = (0, 1, 2, 3, 4, 6, 8)
S_KS = (1, 2, 3, 4, 6, 8)
G_WINDOWS = (45, 60, 90, 120)
G_ARMS = tuple(f"G{w}" for w in G_WINDOWS)
HIST_WINDOWS = (("2025-09-15", "2026-06-30"), ("2026-09-15", "2026-10-31"))
NOW_FROM = "2026-11-01"
OUTCOMES = ("home", "draw", "away")


# ----------------------------------------------------------------------------------------------- data

def _read_csvs(paths: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(pd.read_csv(path).to_dict("records"))
    return rows


def _devig(prices: list[Any]) -> list[float] | None:
    try:
        vals = [float(p) for p in prices]
    except (TypeError, ValueError):
        return None
    if any(math.isnan(v) or v <= 1.0 for v in vals):
        return None
    inv = [1.0 / v for v in vals]
    s = sum(inv)
    return [v / s for v in inv]


def load_league(league: str, src: Path, fd_raw: Path) -> dict[str, Any]:
    us_rows = _read_csvs(sorted(glob.glob(str(src / league / "team_history" / "teams_*.csv"))))
    fd_hist = _read_csvs(sorted(glob.glob(str(src / league / "history" / "matches_*.csv"))))
    raw_2627 = (fd_raw / "2627" / f"{FD_CODES[league]}.csv").read_text(encoding="latin-1")
    fd_2627 = normalize_match_history(raw_2627, league=league, season=2026)
    fd_rows = fd_hist + fd_2627
    espn_path = src / league / "history" / "espn_match_stats.json"
    espn_stats = json.loads(espn_path.read_text(encoding="utf-8")) if espn_path.exists() else []

    # TRUE closing odds (AvgC*) from the raw season files; the normalized history carries pre-close Avg*.
    close: dict[tuple[str, str, str], dict[str, Any]] = {}
    for season in ("2526", "2627"):
        frame = pd.read_csv(fd_raw / season / f"{FD_CODES[league]}.csv", encoding="latin-1")
        frame.columns = [str(c).replace("\ufeff", "").replace("ï»¿", "") for c in frame.columns]
        for raw in frame.to_dict("records"):
            day = _as_iso_day(raw.get("Date"))
            if not day:
                continue
            close[(day, str(raw.get("HomeTeam")), str(raw.get("AwayTeam")))] = {
                "x2": _devig([raw.get("AvgCH"), raw.get("AvgCD"), raw.get("AvgCA")]),
                "ou": _devig([raw.get("AvgC>2.5"), raw.get("AvgC<2.5")]),
                "x2_pre": _devig([raw.get("AvgH"), raw.get("AvgD"), raw.get("AvgA")]),
            }

    # One calendar of league matches (football-data), deduplicated, with each season's club count.
    calendar: list[tuple[str, str, str, float, float]] = []
    seen = set()
    teams_by_season: dict[int, set[str]] = defaultdict(set)
    for row in fd_rows:
        day = _as_iso_day(row.get("date"))
        if not day:
            continue
        key = (day, str(row["home_team"]), str(row["away_team"]))
        if key in seen:
            continue
        seen.add(key)
        try:
            hg, ag = float(row["home_goals"]), float(row["away_goals"])
        except (TypeError, ValueError):
            continue
        if math.isnan(hg) or math.isnan(ag):
            continue
        calendar.append((day, str(row["home_team"]), str(row["away_team"]), hg, ag))
        teams_by_season[int(row.get("season"))].update({str(row["home_team"]), str(row["away_team"])})
    calendar.sort()
    return {
        "league": league, "us_rows": us_rows, "fd_rows": fd_rows, "espn_stats": espn_stats, "close": close,
        "calendar": calendar, "teams_by_season": {s: sorted(t) for s, t in teams_by_season.items()},
        "us_last_day": max(d for d in (_as_iso_day(r.get("date")) for r in us_rows) if d),
    }


def season_of(day: str) -> int:
    y, m = int(day[:4]), int(day[5:7])
    return y if m >= 7 else y - 1


def freeze_cutoff(calendar: list[tuple], day: str, k: int, clubs: int) -> str:
    """Date c such that rows dated >= c are dropped: the (k * clubs/2)-th most recent match before `day`."""
    if k <= 0:
        return day
    prior = [c[0] for c in calendar if c[0] < day]
    need = int(round(k * clubs / 2))
    if not prior:
        return day
    return prior[-min(need, len(prior))]


# ------------------------------------------------------------------------------------------- name map

#: football-data spellings production's matcher does not resolve to Understat's (audited 2026-11-18 over every
#: club in the population: without these, Athletic Club, Borussia M.Gladbach and FC Cologne were priced on the
#: promoted-club prior in every Understat arm). Production itself joins ESPN names, which resolve (the splice's
#: own audit line on the fleet copies: 0 unresolved in all five leagues).
FD_TO_UNDERSTAT_ALIASES = {
    "Ath Bilbao": "Athletic Club",
    "M'gladbach": "Borussia M.Gladbach",
    "FC Koln": "FC Cologne",
    "La Coruna": "Deportivo La Coruna",
}


def build_name_map(fd_names: list[str], us_names: list[str]) -> dict[str, str | None]:
    """football-data club name -> Understat club name: the alias table, else production's own matcher."""
    return {name: FD_TO_UNDERSTAT_ALIASES.get(name) or match_team_name(name, us_names) for name in fd_names}


def fixture_name(arm: str, name: str, fd_to_us: dict[str, str | None]) -> str:
    """The name a fixture carries into an arm: Understat's for the U/S arms (their ratings are keyed by it),
    football-data's for the G arms (rated from football-data rows)."""
    return (fd_to_us.get(name) or name) if arm[0] in "US" else name


# --------------------------------------------------------------------------------------------- ratings

def _resolve(ratings: dict, name: str) -> dict[str, float]:
    entry, _ = _rating_for(ratings, name)
    return entry


def production_finish(ratings: dict, fixtures: list[tuple[str, str]], league: str) -> tuple[dict, list[str], list[str]]:
    names = [h for h, _ in fixtures] + [a for _, a in fixtures]
    promoted = _fill_promoted(ratings, names, league)
    gated = _gate_few_match(ratings, names, league)
    return ratings, promoted, gated


def splice_rows(calendar: list[tuple], lo: str, hi: str, fd_to_us: dict[str, str | None], league: str) -> list[dict]:
    """Goals-as-xG rows for matches in [lo, hi), keyed by the Understat club name, Understat's field set."""
    out: list[dict] = []
    for day, home, away, hg, ag in calendar:
        if not (lo <= day < hi):
            continue
        for team, gf, ga in ((home, hg, ag), (away, ag, hg)):
            us_name = fd_to_us.get(team) or team
            pts = 3.0 if gf > ga else (1.0 if gf == ga else 0.0)
            out.append({"league": league, "season": season_of(day), "team": us_name, "date": day,
                        "xg_for": gf, "xg_against": ga, "goals_for": gf, "goals_against": ga, "points": pts,
                        "splice": True})
    return out


def arm_ratings(data: dict, arm: str, day: str, fixtures: list[tuple[str, str]], fd_to_us: dict) -> tuple[dict, dict]:
    league = data["league"]
    clubs = len(data["teams_by_season"].get(season_of(day), [])) or 20
    meta: dict[str, Any] = {}
    if arm.startswith("U"):
        k = int(arm[1:])
        cut = freeze_cutoff(data["calendar"], day, k, clubs)
        meta["cutoff"] = cut
        ratings = compute_team_ratings(data["us_rows"], as_of=cut, window=45)
    elif arm.startswith("S"):
        # SA = the ACTUAL outage splice: every Understat row (they end at the outage) + goals rows after it.
        k = None if arm == "SA" else int(arm[1:])
        cut = (data["us_last_day"][:10] + "~") if k is None else freeze_cutoff(data["calendar"], day, k, clubs)
        meta["cutoff"] = cut
        us_keep = [r for r in data["us_rows"] if (_as_iso_day(r.get("date")) or "9999") < cut]
        lo = cut if k is not None else data["us_last_day"][:10] + "~"
        rows = us_keep + splice_rows(data["calendar"], lo, day, fd_to_us, league)
        ratings = compute_team_ratings(rows, as_of=day, window=45)
    elif arm.startswith("G"):
        window = int(arm[1:])
        rows = data.setdefault("_goal_rows", team_rows_from_match_history(data["fd_rows"], espn_stats=data["espn_stats"]))
        ratings = compute_team_ratings(rows, as_of=day, window=window)
    else:
        raise ValueError(arm)
    fixtures = [(fixture_name(arm, h, fd_to_us), fixture_name(arm, a, fd_to_us)) for h, a in fixtures]
    ratings, promoted, gated = production_finish(ratings, fixtures, league)
    meta["promoted"] = promoted
    meta["gated"] = gated
    return ratings, meta


# ------------------------------------------------------------------------------------------------- link

def fit_link(xh: np.ndarray, xa: np.ndarray, hg: np.ndarray, ag: np.ndarray) -> np.ndarray:
    """Poisson GLM, design [1, home, x], by Newton-Raphson. Returns (mu, eta, k)."""
    X = np.vstack([np.column_stack([np.ones_like(xh), np.ones_like(xh), xh]),
                   np.column_stack([np.ones_like(xa), np.zeros_like(xa), xa])])
    y = np.concatenate([hg, ag])
    beta = np.array([math.log(max(y.mean(), 0.1)), 0.0, 1.0])
    for _ in range(50):
        lam = np.exp(X @ beta)
        grad = X.T @ (y - lam)
        hess = X.T @ (X * lam[:, None])
        step = np.linalg.solve(hess, grad)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return beta


_GOALS = np.arange(0, 11)
_LOGFACT = np.array([math.lgamma(g + 1) for g in _GOALS])


def _pois(lam: float) -> np.ndarray:
    p = np.exp(_GOALS * math.log(max(lam, 1e-9)) - lam - _LOGFACT)
    return p / p.sum()


def link_probs(beta: np.ndarray, xh: float, xa: float) -> tuple[dict[str, float], float, float, float]:
    mu, eta, k = beta
    lh, la = math.exp(mu + eta + k * xh), math.exp(mu + k * xa)
    ph, pa = _pois(lh), _pois(la)
    joint = np.outer(ph, pa)
    home = float(np.tril(joint, -1).sum())
    draw = float(np.trace(joint))
    away = float(np.triu(joint, 1).sum())
    pt = _pois(lh + la)
    over = float(1.0 - pt[:3].sum())
    return {"home": home, "draw": draw, "away": away}, over, lh, la


def ll_1x2(p: dict[str, float], actual: str) -> float:
    return -math.log(max(p[actual], 1e-12))


def brier(p: dict[str, float], actual: str) -> float:
    return sum((p[o] - (1.0 if o == actual else 0.0)) ** 2 for o in OUTCOMES)


def ll_bin(p: float, hit: bool) -> float:
    p = min(max(p, 1e-12), 1 - 1e-12)
    return -math.log(p if hit else 1.0 - p)


# ------------------------------------------------------------------------------------------------ build

def build_rows(data: dict, arms: list[str], audit: dict) -> list[dict]:
    league = data["league"]
    us_names = sorted({str(r["team"]) for r in data["us_rows"]})
    fd_names = sorted({c[1] for c in data["calendar"]} | {c[2] for c in data["calendar"]})
    fd_to_us = build_name_map(fd_names, us_names)
    audit.setdefault("name_map", {})[league] = {k: v for k, v in fd_to_us.items() if v != k}
    pop_names = {n for c in data["calendar"] if c[0] >= HIST_WINDOWS[0][0] for n in (c[1], c[2])}
    audit.setdefault("unresolved_in_population", {})[league] = sorted(n for n in pop_names if fd_to_us.get(n) is None)
    by_day: dict[str, list[tuple]] = defaultdict(list)
    for c in data["calendar"]:
        day = c[0]
        if any(lo <= day <= hi for lo, hi in HIST_WINDOWS) or day >= NOW_FROM:
            by_day[day].append(c)
    out: list[dict] = []
    for day in sorted(by_day):
        fixtures = [(c[1], c[2]) for c in by_day[day]]
        seg = "now" if day >= NOW_FROM else ("hist2627" if day >= "2026-07-01" else "hist2526")
        per_arm: dict[str, tuple[dict, dict]] = {}
        for arm in arms:
            if seg == "now" and arm[0] in "US" and arm != "U0":
                continue  # every U arm is already frozen at 10-31 on these days; SA below is their splice
            per_arm[arm] = arm_ratings(data, arm, day, fixtures, fd_to_us)
        if seg == "now":
            per_arm["SA"] = arm_ratings(data, "SA", day, fixtures, fd_to_us)
        for day_, home, away, hg, ag in by_day[day]:
            actual = "home" if hg > ag else ("away" if ag > hg else "draw")
            close = data["close"].get((day, home, away)) or {}
            row = {"league": league, "date": day, "segment": seg, "home": home, "away": away,
                   "hg": hg, "ag": ag, "actual": actual,
                   "close_x2": close.get("x2"), "close_ou": close.get("ou"), "pre_x2": close.get("x2_pre"),
                   "arms": {}}
            for arm, (ratings, meta) in per_arm.items():
                rh = _resolve(ratings, fixture_name(arm, home, fd_to_us))
                ra = _resolve(ratings, fixture_name(arm, away, fd_to_us))
                row["arms"][arm] = {
                    "ha": rh.get("attack_rating", 0.0), "hd": rh.get("defense_rating", 0.0),
                    "aa": ra.get("attack_rating", 0.0), "ad": ra.get("defense_rating", 0.0),
                    "hn": rh.get("matches", 0.0), "an": ra.get("matches", 0.0),
                    "cut": meta.get("cutoff"),
                    # On the prior: production's gate (1..9 rows) or fill (no row) priced this side at PROMOTED_TEAM_RATING.
                    "hgate": float(rh.get("matches", 0.0) or 0.0) < 10,
                    "agate": float(ra.get("matches", 0.0) or 0.0) < 10,
                }
            out.append(row)
    return out


def score(rows: list[dict], arms: list[str]) -> list[dict]:
    """Cross-fit the link per league x arm (fold = day ordinal parity) and attach probabilities + scores."""
    def fold(day: str) -> int:
        return dt_date.fromisoformat(day).toordinal() % 2

    all_fits: dict = {}
    train_ll: dict = {}
    u0_fold_fits: dict = {}

    present = sorted({r["league"] for r in rows})
    for league in present:
        lrows = [r for r in rows if r["league"] == league]
        hist = [r for r in lrows if r["segment"] != "now"]
        for arm in arms + ["SA"]:
            def xs(rr):
                a = rr["arms"][arm]
                return a["ha"] - a["ad"], a["aa"] - a["hd"]
            fits = {}
            for f in (0, 1):
                train = [r for r in hist if fold(r["date"]) != f and arm in r["arms"]]
                if len(train) < 50:
                    continue
                xh, xa = zip(*(xs(r) for r in train))
                fits[f] = fit_link(np.array(xh), np.array(xa), np.array([r["hg"] for r in train]), np.array([r["ag"] for r in train]))
            full = [r for r in hist if arm in r["arms"]]
            if full:
                xh, xa = zip(*(xs(r) for r in full))
                fits["all"] = fit_link(np.array(xh), np.array(xa), np.array([r["hg"] for r in full]), np.array([r["ag"] for r in full]))
            elif arm == "SA":
                fits["all"] = all_fits[(league, "S2")]
            all_fits[(league, arm)] = fits["all"]
            if arm == "U0":
                for f in (0, 1):
                    u0_fold_fits[(league, f)] = fits.get(f)
            if arm in G_ARMS:
                for f in (0, 1):
                    train = [r for r in hist if fold(r["date"]) != f and arm in r["arms"]]
                    tot = 0.0
                    for r in train:
                        xh_, xa_ = xs(r)
                        tot += ll_1x2(link_probs(fits[f], xh_, xa_)[0], r["actual"])
                    train_ll[(league, f, arm)] = tot
            for r in lrows:
                if arm not in r["arms"]:
                    continue
                beta = fits["all"] if r["segment"] == "now" else fits.get(fold(r["date"]))
                if beta is None:
                    continue
                xh_, xa_ = xs(r)
                p, over, lh, la = link_probs(beta, xh_, xa_)
                a = r["arms"][arm]
                a.update({"p": p, "over": over, "lh": lh, "la": la, "k": float(beta[2]),
                          "ll": ll_1x2(p, r["actual"]), "br": brier(p, r["actual"]),
                          "ll_ou": ll_bin(over, (r["hg"] + r["ag"]) > 2.5)})
                # FIXED MAP: U0's link for this fold (or U0's full fit on `now`), applied to this arm's ratings.
                fx = all_fits[(league, "U0")] if r["segment"] == "now" else u0_fold_fits.get((league, fold(r["date"])))
                if fx is not None:
                    pf, of, _, _ = link_probs(fx, xh_, xa_)
                    a.update({"p_fx": pf, "over_fx": of, "ll_fx": ll_1x2(pf, r["actual"]), "br_fx": brier(pf, r["actual"]),
                              "ll_ou_fx": ll_bin(of, (r["hg"] + r["ag"]) > 2.5)})
    # GR: per fold, the G window with the lowest TRAIN log loss in that league, scored on the other fold.
    audit_gr: dict = {}
    for league in present:
        hist = [r for r in rows if r["league"] == league and r["segment"] != "now"]
        for f in (0, 1):
            train = [r for r in hist if fold(r["date"]) != f]
            # Fit on the train fold (fits[1-f] is fitted on rows with fold != (1-f), i.e. NOT the train fold),
            # so use the in-sample LL of fits[f] -- fitted on fold != f, the train fold -- over those same rows.
            best = min(G_WINDOWS, key=lambda w: train_ll[(league, f, f"G{w}")])
            audit_gr.setdefault(league, {})[f] = best
            for r in hist:
                if fold(r["date"]) == f and f"G{best}" in r["arms"]:
                    r["arms"]["GR"] = dict(r["arms"][f"G{best}"], window=best)
    score.audit_gr = audit_gr
    return rows


def boot(diffs: list[float], n: int = 2000, seed: int = 1118) -> tuple[float, float, float]:
    """Mean and 95% percentile CI of the mean, 2,000 resamples over matches."""
    if not diffs:
        return (float("nan"),) * 3
    arr = np.asarray(diffs, dtype=float)
    rng = np.random.default_rng(seed)
    means = arr[rng.integers(0, len(arr), size=(n, len(arr)))].mean(axis=1)
    return float(arr.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def summarize(rows: list[dict], arms: list[str]) -> dict:
    out: dict[str, Any] = {}
    for seg_name, pred in (("hist", lambda r: r["segment"] != "now"), ("hist2526", lambda r: r["segment"] == "hist2526"),
                           ("hist2627", lambda r: r["segment"] == "hist2627"), ("now", lambda r: r["segment"] == "now")):
        seg_rows = [r for r in rows if pred(r)]
        base_arm = "U0"
        block: dict[str, Any] = {"n_matches": len(seg_rows),
                                 "dates": [min((r["date"] for r in seg_rows), default=None), max((r["date"] for r in seg_rows), default=None)]}
        for arm in arms + ["GR", "SA"]:
            both = [r for r in seg_rows if "ll" in (r["arms"].get(arm) or {}) and "ll" in (r["arms"].get(base_arm) or {})]
            if not both:
                continue
            d_ll = [r["arms"][arm]["ll"] - r["arms"][base_arm]["ll"] for r in both]
            d_br = [r["arms"][arm]["br"] - r["arms"][base_arm]["br"] for r in both]
            d_ou = [r["arms"][arm]["ll_ou"] - r["arms"][base_arm]["ll_ou"] for r in both]
            with_close = [r for r in both if r.get("close_x2")]
            close_ll = [ll_1x2(dict(zip(OUTCOMES, r["close_x2"])), r["actual"]) for r in with_close]
            arm_ll_c = [r["arms"][arm]["ll"] for r in with_close]
            fx_both = [r for r in both if "ll_fx" in r["arms"][arm] and "ll_fx" in r["arms"][base_arm]]
            d_ll_fx = [r["arms"][arm]["ll_fx"] - r["arms"][base_arm]["ll_fx"] for r in fx_both]
            d_ou_fx = [r["arms"][arm]["ll_ou_fx"] - r["arms"][base_arm]["ll_ou_fx"] for r in fx_both]
            block[arm] = {
                "d_ll_vs_U0_fixed_map": [round(x, 5) for x in boot(d_ll_fx)],
                "d_ll_ou25_vs_U0_fixed_map": [round(x, 5) for x in boot(d_ou_fx)],
                "n": len(both),
                "ll": round(sum(r["arms"][arm]["ll"] for r in both) / len(both), 5),
                "d_ll_vs_U0": [round(x, 5) for x in boot(d_ll)],
                "d_brier_vs_U0": [round(x, 5) for x in boot(d_br)],
                "d_ll_ou25_vs_U0": [round(x, 5) for x in boot(d_ou)],
                "n_with_close": len(with_close),
                "ll_minus_close": round((sum(arm_ll_c) - sum(close_ll)) / len(with_close), 5) if with_close else None,
                "k_mean": round(sum(r["arms"][arm]["k"] for r in both) / len(both), 4),
                "sd_ph_minus_pa": round(float(np.std([r["arms"][arm]["p"]["home"] - r["arms"][arm]["p"]["away"] for r in both])), 4),
            }
        out[seg_name] = block
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=Path(r"C:\tmp\ustale_1118\fleet_src"))
    ap.add_argument("--fd-raw", type=Path, default=Path(r"C:\tmp\ustale_1118\fd_raw"))
    ap.add_argument("--out-dir", type=Path, default=Path(r"C:\tmp\ustale_1118\stageA"))
    ap.add_argument("--leagues", default=",".join(LEAGUES))
    ap.add_argument("--merge", nargs="*", type=Path, default=None,
                    help="summarize the scored rows.jsonl of these per-league out dirs (pooled) instead of building")
    args = ap.parse_args()
    try:
        import psutil
        psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS)
    except Exception:  # noqa: BLE001 -- non-Windows / no psutil: run at the default priority
        pass
    arms = [f"U{k}" for k in U_KS] + [f"S{k}" for k in S_KS] + [f"G{w}" for w in G_WINDOWS]
    if args.merge:
        rows = []
        audit = {"merged_from": [str(d) for d in args.merge], "per_league_audit": {}}
        for d in args.merge:
            rows.extend(json.loads(line) for line in (d / "rows.jsonl").open(encoding="utf-8"))
            audit["per_league_audit"][d.name] = json.loads((d / "summary.json").read_text(encoding="utf-8")).get("audit")
        summary = summarize(rows, arms)
        summary["audit"] = audit
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
        print(json.dumps({k: v for k, v in summary.items() if k != "audit"}, default=str)[:2000])
        return 0
    args.out_dir.mkdir(parents=True, exist_ok=True)
    audit: dict[str, Any] = {"arms": arms}
    rows: list[dict] = []
    for league in [x for x in args.leagues.split(",") if x]:
        data = load_league(league, args.src, args.fd_raw)
        audit.setdefault("coverage", {})[league] = {
            "understat_rows": len(data["us_rows"]), "understat_last_day": data["us_last_day"],
            "fd_matches": len(data["calendar"]), "fd_first": data["calendar"][0][0], "fd_last": data["calendar"][-1][0],
            "clubs_by_season": {s: len(t) for s, t in data["teams_by_season"].items()},
            "close_rows": len(data["close"]),
        }
        lrows = build_rows(data, arms, audit)
        print(f"{league}: {len(lrows)} matches built", flush=True)
        rows.extend(lrows)
    rows = score(rows, arms)
    summary = summarize(rows, arms)
    audit["gr_window_by_fold"] = getattr(score, "audit_gr", {})
    summary["audit"] = audit
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    with (args.out_dir / "rows.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for r in rows:
            handle.write(json.dumps(r, default=str) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "audit"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
