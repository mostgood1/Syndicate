#!/usr/bin/env python
"""NFL same-game-parlay leg correlations, measured at REAL closing lines (lane `nfl-sgp-builder`, 2026-10-16).

The user asked for SGP suggestions on the NFL cheat sheet, priced at an ASSUMED book discount because no SGP
price source exists. The joint probability of the legs is the one number Syndicate can measure itself, so it is
measured here and never assumed:

  1. ONE LEG per (event, player, market): the consensus close line (the line most books quote), fair P(over) =
     median across books of the two-way de-vigged price at that line. Anytime TD is one-sided, so its fair is the
     median implied price times `k_atd`, fitted on the TRAIN seasons as hits / implied (never on the holdout).
  2. OUTCOME from nflverse play-by-play, regular season only (playoffs are a different population). A player absent
     from his game's play-by-play is DROPPED, as a book voids a player who does not play -- which also drops a played
     zero-touch game; that bias is stated, not hidden. A push is dropped.
  3. ROLE from season-to-date usage BEFORE that week -- no hindsight: QB by dropbacks; ground players (carries >=
     targets) RB1/RB2 by carries; pass catchers R1/R2/R3 by targets. A player with no prior usage is UNK.
  4. PAIRS within an event: same player / teammates / opponents. A cell is (leg type a, leg type b, relation),
     unordered, where a leg type is market|role.
  5. Per cell, rho of a Gaussian copula on (over_a, over_b), from the CONCORDANCE moment (both over or both under):
     E[c] = 1 - p_a - p_b + 2 U(t_a, t_b, rho) with each leg's own fair marginal. Concordance is first-order
     insensitive to a marginal that is off by the same small amount for both legs near 0.5, which the both-over count
     is not. SE is game-clustered: sqrt(sum_g (sum_i c_i - E_i)^2) / sum_i 2 phi2(t_a, t_b, rho) (Plackett).
  6. OUT OF SAMPLE: fit on the train seasons, score every holdout pair's four-cell outcome by log loss, copula vs
     independence on the SAME marginals, so the difference is the correlation and nothing else; game-clustered SE.
  7. What the price has to be: for each holdout pair, the orientation with the most joint probability per unit of
     the book's own leg prices, its joint, the product of the vigged leg prices, and the MAX book haircut at which
     the SGP is still +EV (1 - prod(q) / p_joint). Realised ROI at a set of ASSUMED haircuts is exploratory and NOT
     a pre-registered test (#621: no edge label until one passes).

Run on the fleet at idle priority (it shares the host with production):
  nice -n 19 python scripts/build_nfl_sgp_correlations.py --data-root /home/amyn/syndicate-prod/data
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import ndtr, ndtri, owens_t

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.shared.box_usage import _nfl_key  # noqa: E402
from syndicate.features.shared.team_aliases import _NFL_ALIAS_TO_NAME  # noqa: E402

MARKETS = {"Passing Yards": "pass_yds", "Passing Attempts": "pass_att", "Passing TDs": "pass_td",
           "Interceptions": "ints", "Rushing Yards": "rush_yds", "Rushing Attempts": "rush_att",
           "Receiving Yards": "rec_yds", "Receptions": "rec", "Anytime TD": "atd"}
MIN_CELL = 300            # pairs a cell needs before its own rho is used; else the market-pair level; else 0
PBP_CODES = {"ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX",
             "KC", "LV", "LAC", "LA", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SF", "SEA", "TB", "TEN",
             "WAS"}
NAME_TO_CODE = {name: code.upper() for code, name in _NFL_ALIAS_TO_NAME.items() if code.upper() in PBP_CODES}


# ------------------------------------------------------------------------------------------------ bivariate normal
def bvn_lower(h: np.ndarray, k: np.ndarray, rho: np.ndarray | float) -> np.ndarray:
    """Phi2(h, k; rho) via Owen's T (vectorised). h or k at exactly 0 is nudged; the formula divides by them."""
    h = np.where(np.abs(h) < 1e-9, 1e-9, h)
    k = np.where(np.abs(k) < 1e-9, 1e-9, k)
    rho = np.clip(rho, -0.999999, 0.999999)
    s = np.sqrt(1.0 - rho * rho)
    beta = np.where(h * k > 0, 0.0, 0.5)
    return 0.5 * ndtr(h) + 0.5 * ndtr(k) - owens_t(h, (k - rho * h) / (h * s)) - owens_t(k, (h - rho * k) / (k * s)) - beta


def bvn_upper(h: np.ndarray, k: np.ndarray, rho: np.ndarray | float) -> np.ndarray:
    """P(X > h, Y > k)."""
    return 1.0 - ndtr(h) - ndtr(k) + bvn_lower(h, k, rho)


def bvn_pdf(h: np.ndarray, k: np.ndarray, rho: float) -> np.ndarray:
    s2 = 1.0 - rho * rho
    return np.exp(-(h * h - 2 * rho * h * k + k * k) / (2 * s2)) / (2 * math.pi * math.sqrt(s2))


def joint_over(p_a: np.ndarray, p_b: np.ndarray, rho: np.ndarray | float) -> np.ndarray:
    """P(a over AND b over) under a Gaussian copula with each leg's own P(over)."""
    return bvn_upper(ndtri(1.0 - p_a), ndtri(1.0 - p_b), rho)


# ------------------------------------------------------------------------------------------------ outcomes
def load_pbp(data_root: Path, season: int) -> pd.DataFrame:
    cols = ["game_id", "season", "season_type", "week", "game_date", "home_team", "away_team", "posteam",
            "two_point_attempt", "play_type", "pass_attempt", "rush_attempt", "sack", "qb_dropback", "complete_pass",
            "interception", "pass_touchdown", "touchdown", "passing_yards", "rushing_yards", "receiving_yards",
            "passer_player_id", "passer_player_name", "rusher_player_id", "rusher_player_name",
            "receiver_player_id", "receiver_player_name", "td_player_id", "td_player_name"]
    path = data_root / "nfl_source" / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"
    d = pd.read_csv(path, usecols=cols, low_memory=False)
    return d[(d.season_type == "REG") & (d.two_point_attempt.fillna(0) != 1)].copy()


def player_games(pbp: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, dict[tuple[str, str], str]]]:
    """(game_id, pid) -> stat line + team; and per game: name key -> pid, ambiguous keys dropped."""
    f = lambda s: s.fillna(0)  # noqa: E731
    parts = []
    pa = pbp[pbp.passer_player_id.notna()]
    parts.append(pd.DataFrame({"game_id": pa.game_id, "pid": pa.passer_player_id, "name": pa.passer_player_name,
                               "team": pa.posteam, "pass_att": ((f(pa.pass_attempt) == 1) & (f(pa.sack) != 1)).astype(int),
                               "pass_yds": f(pa.passing_yards), "pass_td": f(pa.pass_touchdown),
                               "ints": f(pa.interception), "dropbacks": f(pa.qb_dropback)}))
    ru = pbp[pbp.rusher_player_id.notna() & (f(pbp.rush_attempt) == 1)]
    parts.append(pd.DataFrame({"game_id": ru.game_id, "pid": ru.rusher_player_id, "name": ru.rusher_player_name,
                               "team": ru.posteam, "rush_att": 1, "rush_yds": f(ru.rushing_yards)}))
    rc = pbp[pbp.receiver_player_id.notna() & (f(pbp.pass_attempt) == 1) & (f(pbp.sack) != 1)]
    parts.append(pd.DataFrame({"game_id": rc.game_id, "pid": rc.receiver_player_id, "name": rc.receiver_player_name,
                               "team": rc.posteam, "targets": 1, "rec": f(rc.complete_pass),
                               "rec_yds": f(rc.receiving_yards)}))
    td = pbp[pbp.td_player_id.notna() & (f(pbp.touchdown) == 1)]
    parts.append(pd.DataFrame({"game_id": td.game_id, "pid": td.td_player_id, "name": td.td_player_name,
                               "team": None, "atd": 1}))
    rows = pd.concat(parts, ignore_index=True)
    stat_cols = ["pass_att", "pass_yds", "pass_td", "ints", "dropbacks", "rush_att", "rush_yds", "targets", "rec",
                 "rec_yds", "atd"]
    for c in stat_cols:
        rows[c] = rows[c].fillna(0) if c in rows else 0
    team = rows.dropna(subset=["team"]).groupby(["game_id", "pid"]).team.agg(lambda s: s.mode().iloc[0])
    lines = rows.groupby(["game_id", "pid"])[stat_cols].sum()
    lines["atd"] = (lines["atd"] > 0).astype(int)
    lines = lines.join(team).reset_index()
    names: dict[str, dict[tuple[str, str], set]] = collections.defaultdict(lambda: collections.defaultdict(set))
    for g, pid, name in rows[["game_id", "pid", "name"]].dropna().itertuples(index=False):
        key = _nfl_key(name)
        if key:
            names[g][key].add(pid)
    index = {g: {k: next(iter(v)) for k, v in m.items() if len(v) == 1} for g, m in names.items()}
    return lines, index


def roles(lines: pd.DataFrame, games: pd.DataFrame) -> dict[tuple[str, str], str]:
    """(game_id, pid) -> role from usage in the team's EARLIER games that season (no hindsight)."""
    lines = lines.merge(games[["game_id", "week"]], on="game_id")
    out: dict[tuple[str, str], str] = {}
    for team, g in lines.dropna(subset=["team"]).groupby("team"):
        for week in sorted(g.week.unique()):
            prior = g[g.week < week].groupby("pid")[["dropbacks", "rush_att", "targets"]].sum()
            now = g[g.week == week]
            if prior.empty:
                for gid, pid in now[["game_id", "pid"]].itertuples(index=False):
                    out[(gid, pid)] = "UNK"
                continue
            qb = prior.dropbacks.idxmax() if prior.dropbacks.max() >= 20 else None
            other = prior.drop(index=[qb]) if qb is not None else prior
            other = other[other.dropbacks < (other.rush_att + other.targets)]
            ground = other[other.rush_att >= other.targets].sort_values("rush_att", ascending=False).index.tolist()
            air = other[other.rush_att < other.targets].sort_values("targets", ascending=False).index.tolist()
            rank = {}
            if qb is not None:
                rank[qb] = "QB"
            for i, pid in enumerate(ground):
                rank[pid] = "RB1" if i == 0 else "RB2"
            for i, pid in enumerate(air):
                rank[pid] = ("R1", "R2", "R3")[min(i, 2)]
            for gid, pid in now[["game_id", "pid"]].itertuples(index=False):
                out[(gid, pid)] = rank.get(pid, "UNK")
    return out


# ------------------------------------------------------------------------------------------------ legs
def american_to_prob(price: float) -> float:
    price = float(price)
    return 100.0 / (price + 100.0) if price > 0 else -price / (-price + 100.0)


def load_legs(data_root: Path, season: int) -> pd.DataFrame:
    """One leg per (event, player, market) at the consensus close line."""
    quotes: dict[tuple, dict[str, dict[str, float]]] = collections.defaultdict(lambda: collections.defaultdict(dict))
    meta: dict[str, tuple] = {}
    for path in sorted(glob.glob(str(data_root / "backfill" / "nfl_prop_closes_2023_25" / f"{season}_wk*.jsonl"))):
        week = int(Path(path).stem.split("_wk")[1])
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if r.get("market") not in MARKETS or r.get("price") is None:
                    continue
                meta[r["event_id"]] = (r["home_team"], r["away_team"], r["commence_time"], week)
                key = (r["event_id"], r["market"], r["player_name"], r.get("line"))
                quotes[key][r["bookmaker"]][str(r["selection"]).lower()] = float(r["price"])
    by_leg: dict[tuple, list] = collections.defaultdict(list)
    for (eid, market, player, line), books in quotes.items():
        by_leg[(eid, market, player)].append((line, books))
    rows = []
    for (eid, market, player), options in by_leg.items():
        if market == "Anytime TD":
            books = {b: s for _, bk in options for b, s in bk.items() if "yes" in s}
            if not books:
                continue
            implied = [american_to_prob(s["yes"]) for s in books.values()]
            rows.append({"event_id": eid, "market": market, "player": player, "line": None, "n_books": len(books),
                         "implied_over": float(np.median(implied)), "fair_raw": float(np.median(implied)),
                         "q_over": float(np.median(implied)), "q_under": np.nan})
            continue
        two_way = [(line, {b: s for b, s in bk.items() if "over" in s and "under" in s}) for line, bk in options]
        two_way = [(line, bk) for line, bk in two_way if bk and line is not None]
        if not two_way:
            continue
        line, books = max(two_way, key=lambda x: (len(x[1]), -abs(x[0] - float(np.median([o[0] for o in two_way])))))
        qo = np.array([american_to_prob(s["over"]) for s in books.values()])
        qu = np.array([american_to_prob(s["under"]) for s in books.values()])
        rows.append({"event_id": eid, "market": market, "player": player, "line": float(line), "n_books": len(books),
                     "implied_over": float(np.median(qo)), "fair_raw": float(np.median(qo / (qo + qu))),
                     "q_over": float(np.median(qo)), "q_under": float(np.median(qu))})
    legs = pd.DataFrame(rows)
    ev = pd.DataFrame([(e, *m) for e, m in meta.items()], columns=["event_id", "home", "away", "commence", "week"])
    return legs.merge(ev, on="event_id", how="left")


def match_games(legs: pd.DataFrame, pbp: pd.DataFrame) -> pd.DataFrame:
    games = pbp.groupby("game_id").agg(home_team=("home_team", "first"), away_team=("away_team", "first"),
                                       game_date=("game_date", "first")).reset_index()
    idx = {(r.home_team, r.game_date): r.game_id for r in games.itertuples()}
    idx.update({(r.away_team, r.game_date) + ("swap",): r.game_id for r in games.itertuples()})
    ev = legs[["event_id", "home", "away", "commence"]].drop_duplicates("event_id")
    out = {}
    for r in ev.itertuples():
        home = NAME_TO_CODE.get(str(r.home).lower())
        when = datetime.fromisoformat(str(r.commence).replace("Z", "+00:00")).astimezone(timezone.utc) - timedelta(hours=6)
        day = when.strftime("%Y-%m-%d")
        out[r.event_id] = idx.get((home, day)) or idx.get((home, day, "swap"))
    return legs.assign(game_id=legs.event_id.map(out))


# ------------------------------------------------------------------------------------------------ build
def season_frame(data_root: Path, season: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    pbp = load_pbp(data_root, season)
    lines, names = player_games(pbp)
    games = pbp.groupby("game_id").agg(week=("week", "first")).reset_index()
    role = roles(lines, games)
    legs = match_games(load_legs(data_root, season), pbp)
    audit = {"season": season, "legs": len(legs), "events": int(legs.event_id.nunique()),
             "events_matched": int(legs.dropna(subset=["game_id"]).event_id.nunique())}
    legs = legs.dropna(subset=["game_id"]).copy()
    legs["pid"] = [names.get(g, {}).get(_nfl_key(p) or ("", "")) for g, p in zip(legs.game_id, legs.player)]
    audit["legs_player_matched"] = int(legs.pid.notna().sum())
    legs = legs.dropna(subset=["pid"]).merge(lines, on=["game_id", "pid"], how="left")
    # PLAYED = an offensive touch (dropback, carry or target). Books list every defender for Anytime TD (2023 wk1-3: 961
    # of 1,007 unmatched legs were Anytime TD on defenders and D/ST), and a defender is in the play-by-play only when he
    # scores. His td-only row carries no team, so the team filter already drops him -- measured: legs_played is
    # identical with and without `touched`. Kept explicit so a future team source cannot re-admit only his winners.
    touched = (legs.dropbacks.fillna(0) + legs.rush_att.fillna(0) + legs.targets.fillna(0)) > 0
    audit["legs_played"] = int((legs.team.notna() & touched).sum())
    legs = legs[legs.team.notna() & touched].copy()
    # One leg per player per market: books spell a name two ways ("Equanimeous St Brown" / "St. Brown") and both reach
    # the same player id -- measured as 475 "Anytime TD x Anytime TD, same player" pairs (rho 0.95), which is one bet
    # paired with itself, not a parlay. Keep the spelling more books quote.
    before = len(legs)
    legs = legs.sort_values("n_books", ascending=False).drop_duplicates(["game_id", "pid", "market"]).copy()
    audit["legs_duplicate_spelling_dropped"] = before - len(legs)
    legs["actual"] = np.nan
    for market, col in MARKETS.items():
        legs.loc[legs.market == market, "actual"] = legs.loc[legs.market == market, col]
    legs["over"] = np.where(legs.market == "Anytime TD", legs.actual > 0,
                            np.where(legs.actual > legs.line, 1.0, np.where(legs.actual < legs.line, 0.0, np.nan)))
    legs = legs.dropna(subset=["over"]).copy()
    legs["role"] = [role.get((g, p), "UNK") for g, p in zip(legs.game_id, legs.pid)]
    legs["leg_type"] = legs.market + "|" + legs.role
    legs["season"] = season
    audit["legs_graded"] = len(legs)
    audit["roles"] = dict(collections.Counter(legs.role))
    return legs, audit


def pairs_of(legs: pd.DataFrame) -> pd.DataFrame:
    out = []
    for gid, g in legs.groupby("game_id"):
        g = g.sort_values("leg_type").reset_index(drop=True)
        n = len(g)
        if n < 2:
            continue
        i, j = np.triu_indices(n, k=1)
        a, b = g.iloc[i].reset_index(drop=True), g.iloc[j].reset_index(drop=True)
        rel = np.where(a.pid.values == b.pid.values, "same_player",
                       np.where(a.team.values == b.team.values, "teammate", "opponent"))
        out.append(pd.DataFrame({
            "game_id": gid, "season": a.season.values, "relation": rel,
            "type_a": a.leg_type.values, "type_b": b.leg_type.values, "mkt_a": a.market.values, "mkt_b": b.market.values,
            "p_a": a.fair.values, "p_b": b.fair.values, "o_a": a.over.values, "o_b": b.over.values,
            "qo_a": a.q_over.values, "qu_a": a.q_under.values, "qo_b": b.q_over.values, "qu_b": b.q_under.values}))
    return pd.concat(out, ignore_index=True)


def _recalibrated(t: np.ndarray, hits: np.ndarray) -> np.ndarray:
    """t + d, where d makes mean(P(over)) equal the observed over rate (bisection; P(over) falls as d rises)."""
    target = float(np.clip(hits.mean(), 0.005, 0.995))
    lo, hi = -3.0, 3.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if (1.0 - ndtr(t + mid)).mean() > target:
            lo = mid
        else:
            hi = mid
    return t + 0.5 * (lo + hi)


def fit_rho(p_a: np.ndarray, p_b: np.ndarray, o_a: np.ndarray, o_b: np.ndarray, games: np.ndarray) -> dict[str, float]:
    """Concordance moment estimator with a game-clustered SE (see the module docstring, step 5).

    The marginals are first RECALIBRATED within the cell: one latent-threshold shift per side so the mean fair P(over)
    equals the cell's hit rate. Concordance is insensitive to a marginal error only near 0.5; for an Anytime TD leg
    (p ~ 0.2) a 0.05 error moves rho by ~0.1 -- measured 2026-10-16 as a cell with rho +0.56 whose both-over rate
    (0.090) sat BELOW independence (0.095). The shift removes the marginal's level, not its per-leg variation."""
    t_a, t_b = _recalibrated(ndtri(1.0 - p_a), o_a), _recalibrated(ndtri(1.0 - p_b), o_b)
    p_a, p_b = 1.0 - ndtr(t_a), 1.0 - ndtr(t_b)
    conc = (o_a == o_b).astype(float)
    base = 1.0 - p_a - p_b
    target = conc.sum()

    def expected(r):
        return (base + 2.0 * bvn_upper(t_a, t_b, r)).sum()

    lo, hi = -0.95, 0.95
    if target <= expected(lo):
        rho = lo
    elif target >= expected(hi):
        rho = hi
    else:
        for _ in range(28):
            mid = 0.5 * (lo + hi)
            if expected(mid) < target:
                lo = mid
            else:
                hi = mid
        rho = 0.5 * (lo + hi)
    resid = conc - (base + 2.0 * bvn_upper(t_a, t_b, rho))
    per_game = pd.Series(resid).groupby(games).sum().to_numpy()
    deriv = float((2.0 * bvn_pdf(t_a, t_b, rho)).sum())
    se = float(math.sqrt((per_game ** 2).sum()) / deriv) if deriv > 0 else float("nan")
    both = (o_a == 1) & (o_b == 1)
    return {"rho": round(float(rho), 4), "se": round(se, 4), "n": int(len(p_a)), "games": int(len(per_game)),
            "both_over": round(float(both.mean()), 4), "both_over_indep": round(float((p_a * p_b).mean()), 4),
            "concordance": round(float(conc.mean()), 4),
            "concordance_indep": round(float((base + 2 * p_a * p_b).mean()), 4)}


def clustered_se(values: np.ndarray, groups: np.ndarray) -> float:
    """SE of the mean of `values`, clustered by `groups` (a game's pairs share the game)."""
    n = len(values)
    if n == 0:
        return float("nan")
    per = pd.Series(values - values.mean()).groupby(groups).sum().to_numpy()
    g = len(per)
    return float(math.sqrt((per ** 2).sum() * g / max(g - 1, 1)) / n)


def fit_cells(pairs: pd.DataFrame) -> dict[str, dict[str, dict[str, float]]]:
    cells: dict[str, dict[str, dict[str, float]]] = {"type": {}, "market": {}}
    for level, cols in (("type", ["type_a", "type_b", "relation"]), ("market", ["mkt_a", "mkt_b", "relation"])):
        for key, g in pairs.groupby(cols):
            if len(g) < MIN_CELL:
                continue
            cells[level]["~".join(key)] = fit_rho(g.p_a.values, g.p_b.values, g.o_a.values, g.o_b.values,
                                                  g.game_id.values)
    return cells


def shrink_cells(cells: dict[str, dict[str, dict[str, float]]]) -> dict[str, Any]:
    """Empirical-Bayes shrinkage toward 0, per level and relation: tau^2 = var(rho_hat) - mean(se^2) across the cells
    (method of moments), and each cell keeps rho * tau^2 / (tau^2 + se^2). Measured 2026-10-16 on the raw cells: fitted
    on 2023-24 and scored on 2025, teammate and opponent pairs were WORSE than independence (+0.0005 and +0.0022 nats,
    the latter ~6 SE) while same-player pairs gained 0.041 -- a cell with n = 300 has an SE near 0.08, and applying that
    noise as if it were signal costs more than the small true correlations earn."""
    priors: dict[str, Any] = {}
    for level, group in cells.items():
        by_rel: dict[str, list[str]] = collections.defaultdict(list)
        for key in group:
            by_rel[key.rsplit("~", 1)[1]].append(key)
        for rel, keys in by_rel.items():
            rho = np.array([group[k]["rho"] for k in keys])
            se2 = np.array([group[k]["se"] ** 2 for k in keys])
            tau2 = max(float(rho.var() - se2.mean()), 0.0)
            priors[f"{level}~{rel}"] = {"cells": len(keys), "tau": round(math.sqrt(tau2), 4),
                                        "mean_se": round(float(np.sqrt(se2).mean()), 4)}
            for k, v in zip(keys, se2):
                group[k]["rho_raw"] = group[k]["rho"]
                group[k]["rho"] = round(group[k]["rho_raw"] * (tau2 / (tau2 + v) if tau2 > 0 else 0.0), 4)
    return priors


def lookup(cells: dict, row: Any) -> tuple[float, str]:
    for level, key in (("type", f"{row.type_a}~{row.type_b}~{row.relation}"),
                       ("market", f"{row.mkt_a}~{row.mkt_b}~{row.relation}")):
        c = cells[level].get(key)
        if c is not None:
            return c["rho"], level
    return 0.0, "none"


def four_cell(p_a, p_b, rho):
    oo = joint_over(p_a, p_b, rho)
    probs = np.stack([oo, p_a - oo, p_b - oo, 1.0 - p_a - p_b + oo], axis=1)
    return np.clip(probs, 1e-6, 1.0)


def evaluate(pairs: pd.DataFrame, cells: dict) -> dict[str, Any]:
    looked = [lookup(cells, r) for r in pairs[["type_a", "type_b", "mkt_a", "mkt_b", "relation"]].itertuples()]
    rho = np.array([x[0] for x in looked])
    level = np.array([x[1] for x in looked])
    obs = (1 - pairs.o_a.values) * 2 + (1 - pairs.o_b.values)        # 0 oo, 1 ou, 2 uo, 3 uu
    obs = obs.astype(int)
    cop = -np.log(four_cell(pairs.p_a.values, pairs.p_b.values, rho)[np.arange(len(obs)), obs])
    ind = -np.log(four_cell(pairs.p_a.values, pairs.p_b.values, 0.0)[np.arange(len(obs)), obs])
    diff = cop - ind
    out = {}
    for name, mask in [("all", np.ones(len(diff), bool))] + [(f"relation={r}", pairs.relation.values == r)
                                                             for r in ("same_player", "teammate", "opponent")] + \
                      [(f"level={lv}", level == lv) for lv in ("type", "market", "none")]:
        if mask.sum() == 0:
            continue
        se = clustered_se(diff[mask], pairs.game_id.values[mask])
        out[name] = {"pairs": int(mask.sum()), "games": int(len(set(pairs.game_id.values[mask]))),
                     "logloss_copula": float(cop[mask].mean()), "logloss_indep": float(ind[mask].mean()),
                     "diff": float(diff[mask].mean()), "diff_se_game_clustered": float(se),
                     "mean_abs_rho_used": float(np.abs(rho[mask]).mean())}
    return out, rho, level


def price_study(pairs: pd.DataFrame, rho: np.ndarray, haircuts=(0.0, 0.10, 0.185, 0.25, 0.30)) -> dict[str, Any]:
    """Two-leg SGPs on the holdout, at the orientation with the most joint per unit of the book's own leg prices.
    EXPLORATORY: no SGP price exists, so the payout is ASSUMED = product of the vigged leg prices x (1 - haircut)."""
    p = pairs.reset_index(drop=True)
    r = rho
    pa, pb = p.p_a.values, p.p_b.values
    oo = joint_over(pa, pb, r)
    joints = {"oo": oo, "ou": pa - oo, "uo": pb - oo, "uu": 1 - pa - pb + oo}
    prices = {"oo": p.qo_a * p.qo_b, "ou": p.qo_a * p.qu_b, "uo": p.qu_a * p.qo_b, "uu": p.qu_a * p.qu_b}
    wins = {"oo": (p.o_a == 1) & (p.o_b == 1), "ou": (p.o_a == 1) & (p.o_b == 0),
            "uo": (p.o_a == 0) & (p.o_b == 1), "uu": (p.o_a == 0) & (p.o_b == 0)}
    # Anytime TD has no "no" price: an orientation that needs one is not a ticket (NaN -> never picked).
    ratio = np.nan_to_num(np.stack([joints[k] / prices[k].values for k in ("oo", "ou", "uo", "uu")], axis=1), nan=-np.inf)
    pick = ratio.argmax(axis=1)
    keys = np.array(["oo", "ou", "uo", "uu"])[pick]
    q = np.array([prices[k].values[i] for i, k in enumerate(keys)])
    pj = np.array([joints[k][i] for i, k in enumerate(keys)])
    won = np.array([bool(wins[k].values[i]) for i, k in enumerate(keys)])
    max_haircut = 1.0 - q / pj
    out = {"pairs": int(len(p)), "max_haircut_pct": {f"p{x}": float(np.percentile(max_haircut, x) * 100)
                                                     for x in (50, 75, 90, 95, 99)},
           "by_haircut": []}
    for h in haircuts:
        bet = max_haircut > h
        payout = (1.0 - h) / q[bet]
        roi = float((won[bet] * payout).sum() / bet.sum() - 1.0) if bet.sum() else float("nan")
        se = clustered_se(won[bet] * payout - 1.0, p.game_id.values[bet])
        out["by_haircut"].append({"assumed_haircut_pct": h * 100, "sgps_plus_ev_at_assumption": int(bet.sum()),
                                  "share_of_pairs": float(bet.mean()), "hit_rate": float(won[bet].mean()) if bet.sum() else None,
                                  "predicted_hit_rate": float(pj[bet].mean()) if bet.sum() else None,
                                  "realised_roi": roi, "roi_se_game_clustered": float(se),
                                  "relations": dict(collections.Counter(p.relation.values[bet]))})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--train", default="2023,2024")
    ap.add_argument("--holdout", default="2025")
    ap.add_argument("--out", type=Path, default=None, help="default <data-root>/nfl_source/sgp")
    args = ap.parse_args()
    out_dir = args.out or args.data_root / "nfl_source" / "sgp"
    out_dir.mkdir(parents=True, exist_ok=True)
    train_seasons = [int(s) for s in args.train.split(",") if s]
    holdout = [int(s) for s in args.holdout.split(",") if s]
    frames, audits = {}, []
    for season in train_seasons + holdout:
        legs, audit = season_frame(args.data_root, season)
        frames[season] = legs
        audits.append(audit)
        print("SEASON", json.dumps(audit), flush=True)
    train_legs = pd.concat([frames[s] for s in train_seasons], ignore_index=True)
    atd = train_legs.market == "Anytime TD"
    k_atd = float(train_legs.over[atd].sum() / train_legs.implied_over[atd].sum()) if atd.any() else 1.0
    for legs in frames.values():
        legs["fair"] = np.where(legs.market == "Anytime TD", np.clip(legs.fair_raw * k_atd, 0.01, 0.99), legs.fair_raw)
        legs["fair"] = legs["fair"].clip(0.02, 0.98)
    calib = {m: {"legs": int(len(g)), "fair_over": float(g.fair.mean()), "hit_over": float(g.over.mean())}
             for m, g in pd.concat(frames.values()).groupby("market")}
    train_pairs = pd.concat([pairs_of(frames[s]) for s in train_seasons], ignore_index=True)
    hold_pairs = pd.concat([pairs_of(frames[s]) for s in holdout], ignore_index=True)
    print("PAIRS train", len(train_pairs), "holdout", len(hold_pairs), flush=True)
    cells_train = fit_cells(train_pairs)
    oos_raw, _rho_raw, _ = evaluate(hold_pairs, cells_train)
    print("OOS_RAW", json.dumps({k: round(v["diff"] / v["diff_se_game_clustered"], 2) if v["diff_se_game_clustered"] else None
                                 for k, v in oos_raw.items()}), flush=True)
    shrink_cells(cells_train)
    oos, rho_hold, _level = evaluate(hold_pairs, cells_train)
    print("OOS_SHRUNK", json.dumps({k: round(v["diff"] / v["diff_se_game_clustered"], 2) if v["diff_se_game_clustered"] else None
                                    for k, v in oos.items()}), flush=True)
    print("OOS", json.dumps(oos["all"]), flush=True)
    price = price_study(hold_pairs, rho_hold)
    print("PRICE", json.dumps(price["max_haircut_pct"]), flush=True)
    all_pairs = pd.concat([train_pairs, hold_pairs], ignore_index=True)
    cells_all = fit_cells(all_pairs)
    priors = shrink_cells(cells_all)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {"schema": "nfl_sgp_correlations_v1", "built_at": stamp, "seasons": train_seasons + holdout,
               "season_type": "REG", "method": "gaussian copula on (over_a, over_b); rho from the concordance moment "
                                                "at real consensus close lines; game-clustered SE",
               "min_cell_pairs": MIN_CELL, "k_atd": k_atd, "audit": audits, "marginal_calibration": calib,
               "shrinkage": priors,
               "out_of_sample": {"train": train_seasons, "holdout": holdout, "logloss_raw": oos_raw, "logloss": oos,
                                 "price_study": price},
               "cells": cells_all}
    (out_dir / "nfl_sgp_correlations.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print("WROTE", out_dir / "nfl_sgp_correlations.json", "cells type", len(cells_all["type"]), "market",
          len(cells_all["market"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
