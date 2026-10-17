#!/usr/bin/env python
"""MLB same-game-parlay leg correlations from game logs (lane `basketball-sgp-builder`, 2026-10-17).

The MLB cheat sheet's SGPs need the joint probability of two legs. It is measured here, never assumed, with the
estimator of `scripts/build_nfl_sgp_correlations.py` (`fit_rho`, `shrink_cells`, `clustered_se`, `four_cell`) and the
pair / lookup machinery of `scripts/build_nhl_sgp_correlations.py` (`build_pairs`, `lookup_rho`, `attach_marginals`,
`consensus_legs`, ...) -- both IMPORTED from those scripts, not copied, so a cell means the same thing to
`syndicate.features.nfl.sgp.rho_for` whichever sport fitted it.

  1. PLAYER-GAMES from the statsapi game logs (`derived/mlb_player_game_log_<season>_{hitting,pitching}.csv`),
     REGULAR SEASON only (game_type R; the postseason is a different population). A hitter needs >= `--min-pa` (2)
     plate appearances -- the STARTED proxy: a book posts props for the announced lineup, and pa 0 (a defensive sub or
     pinch runner) and pa 1 (overwhelmingly a pinch hit) are not that population. Pitchers: STARTERS only.
  2. NO ROLES. The runtime types every MLB leg `MARKET|UNK`, so only MARKET cells are fitted and published
     (`cells.type` is empty and `rho_for` falls through to `cells.market`). Market keys follow `rho_for`'s order --
     the two `market|UNK` strings sorted -- which puts `batter_hits_runs_rbis` BEFORE `batter_hits` ('_' < '|').
  3. LEGS, one per (game, player, market), from the player's EARLIER games this season (>= MIN_PRIOR of them; a
     pitcher's earlier STARTS) at a proxy book line: the prior median rounded to x.5 (an integer median goes up when
     the prior mean is above it, else down; the NHL study's rule), snapped to the market's line range.
     MARGINAL P(over), both leak-free for the holdout (the NHL study's `attach_marginals`):
       role   -- the TRAIN seasons' over-rate per (market, line) (role is UNK for every leg);
       player -- the player's own prior over-rate at that line, shrunk to it with SHRINK_K pseudo-games.
  4. PAIRS within a game: same_player / teammate / opponent (starting pitcher x opposing batters is `opponent`).
  5. rho per market cell from the concordance moment with within-cell marginal recalibration and a game-clustered SE
     (`fit_rho`), shrunk empirical-Bayes per relation (`shrink_cells`, which shrinks toward 0 with tau^2 taken from
     the cells' spread about their MEAN -- the defect the NHL study states; kept as is, the second-moment variant is
     run beside it as a diagnostic).
  6. OUT OF SAMPLE, four-cell log loss, copula vs independence on the SAME marginals, game-clustered SE:
       A. proxy cells fit on the train seasons, scored on the holdout season's proxy legs (the requested test);
       B. proxy cells fit on train + holdout, scored on the REAL pregame book lines of `--real` (2026: batter hits,
          total bases and pitcher strikeouts, ~10 min before first pitch) at their de-vigged consensus;
       C. real-line cells fit on `--real` before `--real-split`, scored after it.
     PRE-STATED FALSIFICATION: a relation whose test-A gain (shrunk cells, the published marginal) is not below zero
     at |z| >= 2 is reported as "no measured correlation" and its published cells are set to 0. Same-player is judged
     on NON-nested pairs only -- the runtime never prices a nested pair.
  7. ENGINE READ: coverage of the game logs per season, where books set the real lines against the proxy rule, and
     the books' de-vigged fair against the realised over-rate.

Run on the fleet at idle priority (it shares the host with production):
  nice -n 19 python scripts/build_mlb_sgp_correlations.py --data-root /home/amyn/syndicate-prod/data --out /tmp/mlb_sgp
"""
from __future__ import annotations

import argparse
import collections
import copy
import glob
import importlib.util
import json
import math
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.nfl.sgp import joint_over, rho_for  # noqa: E402 -- the consumer's own lookup


def _script(name: str):
    """A sibling study script loaded as a module -- its functions are used AS IS."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_nfl = _script("build_nfl_sgp_correlations")
fit_rho = _nfl.fit_rho
shrink_cells = _nfl.shrink_cells
clustered_se = _nfl.clustered_se
four_cell = _nfl.four_cell

_nhl = _script("build_nhl_sgp_correlations")
build_pairs = _nhl.build_pairs
concat_pairs = _nhl.concat_pairs
subset_pairs = _nhl.subset_pairs
lookup_rho = _nhl.lookup_rho
role_rates = _nhl.role_rates
attach_marginals = _nhl.attach_marginals
consensus_legs = _nhl.consensus_legs
shrink_second_moment = _nhl.shrink_second_moment
strip_cells = _nhl.strip_cells
name_key = _nhl._key                  # first initial + last name, accents folded
_groups = _nhl._groups
_cell_name = _nhl._cell_name
REL = _nhl.REL                        # ("same_player", "teammate", "opponent")

# The cheat sheet's market names (`build_cheat_sheets.MLB_PITCHER_MARKETS`: the board names pitcher markets bare).
BATTER_STAT = {"batter_hits": "h", "batter_total_bases": "tb", "batter_home_runs": "hr", "batter_rbis": "rbi",
               "batter_runs_scored": "r", "batter_hits_runs_rbis": None, "batter_strikeouts": "so"}
PITCHER_STAT = {"strikeouts": "k", "hits_allowed": "h", "earned_runs": "er", "outs": "outs"}
BATTER_MARKETS = tuple(BATTER_STAT)
PITCHER_MARKETS = tuple(PITCHER_STAT)
MARKETS = BATTER_MARKETS + PITCHER_MARKETS
KIND = {**{m: "B" for m in BATTER_MARKETS}, **{m: "P" for m in PITCHER_MARKETS}}
ODDS_KEYS = {**{m: m for m in BATTER_MARKETS}, "pitcher_strikeouts": "strikeouts",
             "pitcher_hits_allowed": "hits_allowed", "pitcher_earned_runs": "earned_runs", "pitcher_outs": "outs"}


def _halves(lo: int, hi: int) -> tuple[float, ...]:
    return tuple(k + 0.5 for k in range(lo, hi + 1))


TYPICAL_LINES = {"batter_hits": _halves(0, 2), "batter_total_bases": _halves(0, 3), "batter_home_runs": (0.5,),
                 "batter_rbis": _halves(0, 1), "batter_runs_scored": _halves(0, 1),
                 "batter_hits_runs_rbis": _halves(0, 3), "batter_strikeouts": _halves(0, 2),
                 "strikeouts": _halves(0, 12), "hits_allowed": _halves(0, 10), "earned_runs": _halves(0, 6),
                 "outs": _halves(0, 23)}
MIN_PRIOR = 5             # earlier games (starts for a pitcher) a leg needs before its proxy line exists
MIN_PA = 2                # the STARTED proxy for a hitter (see the docstring, step 1)
MIN_CELL = 300            # as the NFL and NHL studies
SHRINK_K = 20.0           # pseudo-games pulling a player's prior over-rate to the market's
ROLE = "UNK"
# Same player, one stat contains the other: one leg (nearly) implies the other -- never a parlay. A home run is a
# run, an RBI and four total bases; a hit is a total base and an H+R+RBI.
NESTED_PAIRS = (("batter_hits", "batter_total_bases"), ("batter_hits", "batter_hits_runs_rbis"),
                ("batter_rbis", "batter_hits_runs_rbis"), ("batter_runs_scored", "batter_hits_runs_rbis"),
                ("batter_home_runs", "batter_total_bases"), ("batter_home_runs", "batter_rbis"),
                ("batter_home_runs", "batter_runs_scored"), ("batter_home_runs", "batter_hits_runs_rbis"))


def cell_key(market_a: str, market_b: str, relation: str) -> str:
    """The market-cell key `rho_for` builds for two `market|UNK` legs."""
    ta, tb = sorted((f"{market_a}|{ROLE}", f"{market_b}|{ROLE}"))
    return f"{ta.split('|')[0]}~{tb.split('|')[0]}~{relation}"


NESTED_SAME_PLAYER = tuple(cell_key(a, b, "same_player") for a, b in NESTED_PAIRS)


# ------------------------------------------------------------------------------------------------ game logs
def player_games(hit: pd.DataFrame, pit: pd.DataFrame, min_pa: int = MIN_PA) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """One row per started hitter-game and per starting-pitcher game, REGULAR SEASON only, every market a column.
    Also the regular-season hitter rows dropped by `min_pa` (a book voids or never lists them) and an audit."""
    hit = hit[hit.game_type == "R"]
    pit = pit[pit.game_type == "R"]
    audit = {"games": int(pd.concat([hit.game_pk, pit.game_pk]).nunique()), "hitter_rows": int(len(hit)),
             "hitter_rows_pa0": int((hit.pa == 0).sum()),
             "hitter_rows_below_min_pa_with_pa": int(((hit.pa > 0) & (hit.pa < min_pa)).sum())}
    bench = hit[hit.pa < min_pa]
    hit = hit[hit.pa >= min_pa]
    sp = pit[pit.is_starter == 1]
    b = pd.DataFrame({"game_id": hit.game_pk.astype(int).values, "date": hit.date.astype(str).values,
                      "pid": hit.player_id.astype(int).values, "name": hit.player_name.values,
                      "team": hit.team.values, "opp": hit.opponent.values, "kind": "B", "pa": hit.pa.values})
    for m, col in BATTER_STAT.items():
        b[m] = (hit.h + hit.r + hit.rbi).values if m == "batter_hits_runs_rbis" else hit[col].values
    p = pd.DataFrame({"game_id": sp.game_pk.astype(int).values, "date": sp.date.astype(str).values,
                      "pid": sp.player_id.astype(int).values, "name": sp.player_name.values,
                      "team": sp.team.values, "opp": sp.opponent.values, "kind": "P", "pa": 0})
    for m, col in PITCHER_STAT.items():
        p[m] = sp[col].values
    pg = pd.concat([b, p], ignore_index=True).sort_values(["date", "game_id", "team", "kind", "pid"], kind="mergesort")
    per_game = pg.groupby("game_id")
    audit.update({"hitter_games_kept": int(len(b)), "starter_games": int(len(p)),
                  "hitters_per_team_game": round(len(b) / max(1, 2 * pg.game_id.nunique()), 2),
                  "starters_per_game": round(len(p) / max(1, pg.game_id.nunique()), 3),
                  "games_with_two_teams": int((per_game.team.nunique() == 2).sum()),
                  "first_date": str(pg.date.min()), "last_date": str(pg.date.max())})
    bench = pd.DataFrame({"game_id": bench.game_pk.astype(int).values, "pid": bench.player_id.astype(int).values,
                          "name": bench.player_name.values, "pa": bench.pa.values})
    return pg.reset_index(drop=True), bench, audit


def load_season(data_root: Path, season: int, min_pa: int = MIN_PA,
                limit_games: int = 0) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    derived = data_root / "mlb_source" / "source_artifacts" / "data" / "derived"
    hit = pd.read_csv(derived / f"mlb_player_game_log_{season}_hitting.csv")
    pit = pd.read_csv(derived / f"mlb_player_game_log_{season}_pitching.csv")
    if limit_games:
        keep = hit[hit.game_type == "R"].sort_values(["date", "game_pk"]).game_pk.drop_duplicates().head(limit_games)
        hit, pit = hit[hit.game_pk.isin(keep)], pit[pit.game_pk.isin(keep)]
    pg, bench, audit = player_games(hit, pit, min_pa)
    return pg, bench, dict(audit, season=season)


# ------------------------------------------------------------------------------------------------ legs
def proxy_line(past: list[float], market: str) -> float:
    """A book-like line from a player's EARLIER games: the median rounded to x.5 (an integer median goes up when the
    mean is above it, else down), snapped to the nearest line in the market's range -- the NHL study's rule."""
    med = float(statistics.median(past))
    if med != math.floor(med):
        line = med
    else:
        line = med + 0.5 if float(np.mean(past)) > med else med - 0.5
    lines = TYPICAL_LINES[market]
    return min(lines, key=lambda x: (abs(x - line), x))


def season_history(pg: pd.DataFrame, min_prior: int = MIN_PRIOR) -> pd.DataFrame:
    """Per player-game, from his EARLIER games this season only (a pitcher's: earlier STARTS; a two-way player's bat
    and arm are separate histories): games, and per market the proxy line, how often he cleared it, and his mean.
    Current-game stats are appended AFTER the read."""
    hist: dict[tuple[int, str], dict[str, list[float]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    recs = []
    for r in pg.itertuples(index=False):
        h = hist[(r.pid, r.kind)]
        markets = BATTER_MARKETS if r.kind == "B" else PITCHER_MARKETS
        n = len(h[markets[0]])
        rec: dict[str, Any] = {"game_id": r.game_id, "pid": r.pid, "kind": r.kind, "prior_n": n}
        if n >= min_prior:
            for m in markets:
                past = h[m]
                line = proxy_line(past, m)
                rec[f"line_{m}"] = line
                rec[f"overs_{m}"] = int(sum(v > line for v in past))
                rec[f"mean_{m}"] = float(np.mean(past))
        for m in markets:
            h[m].append(float(getattr(r, m)))
        recs.append(rec)
    return pd.DataFrame(recs)


def proxy_legs(pg: pd.DataFrame, history: pd.DataFrame, season: int, min_prior: int = MIN_PRIOR) -> pd.DataFrame:
    """One leg per (game, player, market) at the proxy line; over = stat > line (x.5, so no push)."""
    d = pg.merge(history, on=["game_id", "pid", "kind"], how="left")
    d = d[d.prior_n >= min_prior]
    rows = []
    for m in MARKETS:
        if f"line_{m}" not in d:
            continue
        sub = d[(d.kind == KIND[m]) & d[f"line_{m}"].notna()]
        rows.append(pd.DataFrame({
            "game_id": sub.game_id.values, "date": sub.date.values, "team": sub.team.values, "pid": sub.pid.values,
            "market": m, "line": sub[f"line_{m}"].values, "actual": sub[m].values.astype(float),
            "prior_n": sub.prior_n.values, "prior_overs": sub[f"overs_{m}"].values}))
    legs = pd.concat(rows, ignore_index=True)
    legs["over"] = (legs.actual > legs.line).astype(np.int8)
    legs["role"] = ROLE
    legs["type"] = legs.market + "|" + ROLE
    legs["season"] = season
    return legs.reset_index(drop=True)


# ------------------------------------------------------------------------------------------------ real book lines
def snapshot_quotes(snap: Mapping[str, Any]) -> dict[tuple[str, str, float], dict[str, dict[str, float]]]:
    """(market, player, line) -> book -> {over, under} American price, from one OddsAPI event snapshot."""
    quotes: dict = collections.defaultdict(lambda: collections.defaultdict(dict))
    for book in (snap.get("bookmakers") or []):
        for mk in book.get("markets") or []:
            market = ODDS_KEYS.get(str(mk.get("key") or ""))
            if market is None:
                continue
            for o in mk.get("outcomes") or []:
                side = str(o.get("name") or "").lower()
                if side not in ("over", "under") or o.get("point") is None or o.get("price") is None:
                    continue
                quotes[(market, str(o.get("description") or ""), float(o["point"]))][book["key"]][side] = float(o["price"])
    return quotes


def book_legs(files_by_game: Mapping[int, list[str]], pg: pd.DataFrame, season: int,
              bench: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Real pregame consensus legs for the games' logs. A listed hitter who did not start (below `min_pa`) or is
    absent from the log is void (dropped, counted apart); a pitcher leg needs the game's STARTER."""
    audit: collections.Counter = collections.Counter()
    played = {gid: g for gid, g in pg.groupby("game_id")}
    bench_keys =({gid: {name_key(n) for n in g.name} for gid, g in bench.groupby("game_id")}
                  if bench is not None and len(bench) else {})
    markets_seen: collections.Counter = collections.Counter()
    rows = []
    for gid, paths in sorted(files_by_game.items()):
        quotes: dict = collections.defaultdict(lambda: collections.defaultdict(dict))
        for path in paths:
            try:
                with open(path, encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError):
                audit["file_unreadable"] += 1
                continue
            snap = doc.get("snap") or {}
            data = snap.get("data") or {}
            if str(snap.get("timestamp") or "") >= str(data.get("commence_time") or "~"):
                audit["snapshot_not_pregame"] += 1
                continue
            for k, books in snapshot_quotes(data).items():
                for b, s in books.items():
                    quotes[k][b].update(s)
        g = played.get(gid)
        if g is None:
            audit["game_without_log"] += 1
            continue
        keys: dict[tuple[tuple[str, str] | None, str], set] = collections.defaultdict(set)
        for pid, name, kind in zip(g.pid, g.name, g.kind):
            keys[(name_key(name), kind)].add(pid)
        by_pid = {(r.pid, r.kind): r for r in g.itertuples(index=False)}
        for leg in consensus_legs(quotes):
            audit["legs_quoted"] += 1
            markets_seen[leg["market"]] += 1
            kind = KIND[leg["market"]]
            k = name_key(leg["player"])
            pids = keys.get((k, kind), set())
            if len(pids) != 1:
                if pids:
                    audit["legs_ambiguous_name"] += 1
                elif kind == "B" and k in bench_keys.get(gid, set()):
                    audit["legs_hitter_below_min_pa_void"] += 1
                elif kind == "P":
                    audit["legs_pitcher_not_starter_or_unmatched"] += 1
                else:
                    audit["legs_void_or_unmatched"] += 1
                continue
            pid = next(iter(pids))
            r = by_pid[(pid, kind)]
            actual = float(getattr(r, leg["market"]))
            if actual == leg["line"]:
                audit["legs_push"] += 1
                continue
            rows.append(dict(leg, game_id=gid, date=r.date, team=r.team, pid=pid, role=ROLE, actual=actual,
                             over=int(actual > leg["line"]), season=season))
    audit["legs_quoted_by_market"] = dict(markets_seen)
    legs = pd.DataFrame(rows)
    if legs.empty:
        return legs, dict(audit)
    before = len(legs)
    legs = legs.sort_values("n_books", ascending=False, kind="mergesort").drop_duplicates(["game_id", "pid", "market"])
    audit["legs_duplicate_spelling_dropped"] = before - len(legs)
    legs["type"] = legs.market + "|" + ROLE
    legs["p_fair"] = legs.fair.clip(0.02, 0.98)
    audit["legs_graded"] = len(legs)
    audit["legs_graded_by_market"] = {k: int(v) for k, v in legs.market.value_counts().items()}
    audit["games_graded"] = int(legs.game_id.nunique())
    return legs.sort_values(["game_id", "type", "pid"]).reset_index(drop=True), dict(audit)


def odds_files(data_root: Path, season: int) -> dict[int, list[str]]:
    """`backfill/mlb_props_<season>/odds/<game_pk>.json`: one pregame OddsAPI snapshot per game."""
    out: dict[int, list[str]] = collections.defaultdict(list)
    for path in glob.glob(str(data_root / "backfill" / f"mlb_props_{season}" / "odds" / "*.json")):
        stem = Path(path).stem
        if stem.isdigit():
            out[int(stem)].append(path)
    return out


# ------------------------------------------------------------------------------------------------ cells
def fit_cells(pairs: Mapping[str, Any] | list[Mapping[str, Any]], pcol: str,
              min_cell: int = MIN_CELL) -> dict[str, dict[str, dict[str, float]]]:
    """`fit_rho` per MARKET cell with >= `min_cell` pairs. No role level: every MLB leg is `market|UNK`.
    A LIST of pair sets (one per season) is fitted as their union WITHOUT concatenating them: only one cell's pairs
    are gathered at a time. An MLB season is ~2 x 10^7 pairs and the fleet shares its memory with production."""
    parts = pairs if isinstance(pairs, list) else [pairs]
    index: dict[str, list[tuple[int, np.ndarray]]] = collections.defaultdict(list)
    for n, part in enumerate(parts):
        order, uniq, start, count, names = _groups(part, "market")
        for k, s, c in zip(uniq, start, count):
            index[_cell_name(k, names)].append((n, order[s:s + c]))
    cells: dict[str, dict[str, dict[str, float]]] = {"type": {}, "market": {}}
    for name in sorted(index):
        slices = index[name]
        if sum(len(idx) for _, idx in slices) < min_cell:
            continue

        def col(c: str, dtype=np.float64) -> np.ndarray:
            return np.concatenate([parts[n][c][idx] for n, idx in slices]).astype(dtype)
        cells["market"][name] = fit_rho(col(f"{pcol}_a"), col(f"{pcol}_b"), col("o_a"), col("o_b"),
                                        col("game", np.int64))
    return cells


def falsification(summary: Mapping[str, Any]) -> dict[str, Any]:
    """The pre-stated test, per relation: MEASURED only if the out-of-sample gain is below zero at z <= -2.
    Same-player is judged on its non-nested pairs (nested pairs are never priced)."""
    out = {}
    for rel in REL:
        row = summary.get("relation=same_player_not_nested" if rel == "same_player" else f"relation={rel}") or {}
        diff, z = row.get("diff"), row.get("z")
        measured = diff is not None and z is not None and diff < 0 and z <= -2.0
        out[rel] = {"diff": diff, "z": z, "pairs": row.get("pairs"),
                    "verdict": "measured" if measured else "no measured correlation"}
    return out


def apply_falsification(cells: dict[str, dict[str, dict[str, float]]], verdict: Mapping[str, Any]) -> int:
    """Set every cell of a falsified relation to 0 (the shrunk value is kept as `rho_before_falsification`)."""
    n = 0
    for group in cells.values():
        for key, cell in group.items():
            rel = key.rsplit("~", 1)[1]
            if verdict.get(rel, {}).get("verdict") != "measured":
                cell["rho_before_falsification"] = cell["rho"]
                cell["rho"] = 0.0
                cell["falsified"] = True
                n += 1
    return n


# ------------------------------------------------------------------------------------------------ scoring
def score_pairs(pairs: Mapping[str, Any], cells: Mapping[str, Any], pcol: str,
                chunk: int = 2_000_000) -> dict[str, np.ndarray]:
    """Per pair, through the CONSUMER's lookup (`rho_for`): rho used, lookup level, copula minus independence log
    loss (four-cell, the same marginals), and the predicted / independent both-over probability."""
    rho, level = lookup_rho(pairs, cells)
    lvl = np.where(level == "role", 0, np.where(level == "market", 1, 2)).astype(np.int8)
    del level
    n = len(rho)
    diff, cop = np.empty(n), np.empty(n, np.float32)
    both_pred, indep = np.empty(n, np.float32), np.empty(n, np.float32)
    for s in range(0, n, chunk):                       # chunked: a season is ~10^7 pairs on a shared host
        e = min(n, s + chunk)
        p_a = pairs[f"{pcol}_a"][s:e].astype(np.float64)
        p_b = pairs[f"{pcol}_b"][s:e].astype(np.float64)
        obs = (1 - pairs["o_a"][s:e].astype(np.int64)) * 2 + (1 - pairs["o_b"][s:e].astype(np.int64))
        rows = np.arange(e - s)
        c = -np.log(four_cell(p_a, p_b, rho[s:e])[rows, obs])
        i = -np.log(four_cell(p_a, p_b, 0.0)[rows, obs])
        diff[s:e], cop[s:e] = c - i, c
        both_pred[s:e] = joint_over(p_a, p_b, rho[s:e])
        indep[s:e] = p_a * p_b
    return {"rho": rho.astype(np.float32), "level": lvl, "diff": diff, "cop": cop, "both_pred": both_pred,
            "indep": indep}


def pair_masks(pairs: Mapping[str, Any]) -> list[tuple[str, np.ndarray]]:
    """Relation, nested / not-nested same-player, batter / pitcher class within each relation, lookup level."""
    markets = pairs["markets"]
    is_p = np.array([m in PITCHER_STAT for m in markets])
    cls = is_p[pairs["ma"]].astype(np.int8) + is_p[pairs["mb"]].astype(np.int8)
    nested_codes = {(markets.index(a), markets.index(b)) for a, b in NESTED_PAIRS if a in markets and b in markets}
    nested_codes |= {(b, a) for a, b in nested_codes}
    code = pairs["ma"].astype(np.int32) * 256 + pairs["mb"]
    nested = (pairs["rel"] == 0) & np.isin(code, [a * 256 + b for a, b in nested_codes])
    out = [("all", np.ones(len(code), bool))]
    out += [(f"relation={r}", pairs["rel"] == i) for i, r in enumerate(REL)]
    out += [("relation=same_player_not_nested", (pairs["rel"] == 0) & ~nested),
            ("relation=same_player_nested", nested)]
    for i, r in enumerate(REL):
        for c, name in enumerate(("batter_batter", "pitcher_batter", "pitcher_pitcher")):
            out.append((f"{r}:{name}", (pairs["rel"] == i) & (cls == c)))
    return out


def summarise(pairs: Mapping[str, Any], sc: Mapping[str, np.ndarray], by_cell: bool = False,
              min_cell_pairs: int = 2000) -> dict[str, Any]:
    both = (pairs["o_a"] == 1) & (pairs["o_b"] == 1)
    masks = pair_masks(pairs) + [(f"level={lv}", sc["level"] == i) for i, lv in enumerate(("role", "market", "none"))]
    out: dict[str, Any] = {}
    for name, mask in masks:
        if not mask.any():
            continue
        d = sc["diff"][mask]
        se = clustered_se(d, pairs["game"][mask])
        dm = float(d.mean())
        cop = float(sc["cop"][mask].astype(np.float64).mean())
        out[name] = {"pairs": int(mask.sum()), "games": int(len(np.unique(pairs["game"][mask]))),
                     "logloss_copula": round(cop, 6), "logloss_indep": round(cop - dm, 6),
                     "diff": round(dm, 6), "diff_se_game_clustered": round(float(se), 6),
                     "z": round(dm / se, 2) if se else None,
                     "mean_abs_rho_used": round(float(np.abs(sc["rho"][mask]).mean()), 4),
                     "both_over_predicted": round(float(sc["both_pred"][mask].mean()), 4),
                     "both_over_realised": round(float(both[mask].mean()), 4),
                     "both_over_independent": round(float(sc["indep"][mask].mean()), 4)}
    if by_cell:
        order, uniq, start, count, names = _groups(pairs, "market")
        cell_out = {}
        for k, s, c in zip(uniq, start, count):
            if c < min_cell_pairs:
                continue
            idx = order[s:s + c]
            se = clustered_se(sc["diff"][idx], pairs["game"][idx])
            d = float(sc["diff"][idx].mean())
            cell_out[_cell_name(k, names)] = {
                "pairs": int(c), "diff": round(d, 6), "z": round(d / se, 2) if se else None,
                "mean_rho_used": round(float(sc["rho"][idx].mean()), 4),
                "both_over_predicted": round(float(sc["both_pred"][idx].mean()), 4),
                "both_over_realised": round(float(both[idx].mean()), 4),
                "both_over_independent": round(float(sc["indep"][idx].mean()), 4)}
        out["by_market_cell"] = cell_out
    return out


def evaluate(pairs: Mapping[str, Any], cells: Mapping[str, Any], pcol: str, by_cell: bool = False) -> dict[str, Any]:
    return summarise(pairs, score_pairs(pairs, cells, pcol), by_cell=by_cell)


# ------------------------------------------------------------------------------------------------ engine read
def line_read(real: pd.DataFrame, history: pd.DataFrame, pg: pd.DataFrame) -> dict[str, Any]:
    """Real book lines against the proxy rule run on the same player's earlier games, and the books' de-vigged fair
    against the realised over-rate (game-clustered SE)."""
    h = history.merge(pg[["game_id", "pid", "kind"] + list(MARKETS)], on=["game_id", "pid", "kind"])
    out = {}
    for m in sorted(real.market.unique()):
        b = real[real.market == m]
        if f"line_{m}" not in h:              # no player reached MIN_PRIOR games in this market (a smoke run)
            continue
        hk = h[(h.kind == KIND[m]) & h[f"line_{m}"].notna()]
        j = b.merge(hk[["game_id", "pid", "prior_n", f"line_{m}", f"mean_{m}"]], on=["game_id", "pid"], how="left")
        j = j[j[f"line_{m}"].notna()]
        diff = j.line - j[f"line_{m}"]
        resid = (b.over - b.p_fair).to_numpy(np.float64)
        rec = {"book_legs": int(len(b)),
               "book_line_top": {f"{k:g}": int(v) for k, v in b.line.value_counts().head(6).items()},
               "book_fair_over_mean": round(float(b.p_fair.mean()), 4),
               "book_line_over_realised": round(float(b.over.mean()), 4),
               "realised_minus_fair": round(float(resid.mean()), 4),
               "realised_minus_fair_se_game_clustered": round(float(clustered_se(resid, b.game_id.to_numpy())), 4),
               "matched_to_proxy": int(len(j)),
               "proxy_equals_book": round(float((diff == 0).mean()), 4) if len(j) else None,
               "book_minus_proxy_mean": round(float(diff.mean()), 3) if len(j) else None,
               "book_above_proxy": round(float((diff > 0).mean()), 4) if len(j) else None,
               "book_below_proxy": round(float((diff < 0).mean()), 4) if len(j) else None,
               "book_line_minus_prior_mean": round(float((j.line - j[f"mean_{m}"]).mean()), 3) if len(j) else None,
               "proxy_line_over_realised_all_players": round(float((hk[m] > hk[f"line_{m}"]).mean()), 4),
               "proxy_line_legs_all_players": int(len(hk))}
        out[m] = rec
    return out


def _calibration(legs: pd.DataFrame, pcols: Iterable[str]) -> dict[str, Any]:
    out = {}
    for m, g in legs.groupby("market"):
        out[m] = {"legs": int(len(g)), "over_rate": round(float(g.over.mean()), 4),
                  **{f"mean_{c}": round(float(g[c].mean()), 4) for c in pcols},
                  "lines": {f"{k:g}": int(v) for k, v in g.line.value_counts().head(5).items()}}
    return out


def _z(table: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v.get("z") for k, v in table.items() if k != "by_market_cell"}


def _peak_mb() -> float | None:
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)   # Linux: KB
    except (ImportError, AttributeError):
        return None


# ------------------------------------------------------------------------------------------------ driver
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--train", default="2023,2024")
    ap.add_argument("--holdout", default="2025")
    ap.add_argument("--real", default="2026", help="season with real pregame book lines ('' to skip)")
    ap.add_argument("--real-split", default="", help="C's train/holdout date (default <real season>-07-01)")
    ap.add_argument("--marginal", default="player", choices=("player", "role"),
                    help="the marginal the published cells are fitted with (both are evaluated)")
    ap.add_argument("--min-pa", type=int, default=MIN_PA)
    ap.add_argument("--limit-games", type=int, default=0, help="smoke runs: the first N games of each season")
    ap.add_argument("--out", type=Path, default=Path("/tmp/mlb_sgp"))
    args = ap.parse_args()
    t_start = time.time()
    args.out.mkdir(parents=True, exist_ok=True)
    train = [int(s) for s in args.train.split(",") if s]
    hold = [int(s) for s in args.holdout.split(",") if s]
    real_seasons = [int(s) for s in args.real.split(",") if s]
    pcols = ("p_role", "p_player")
    pub = f"p_{args.marginal}"

    frames: dict[int, dict[str, Any]] = {}
    for season in sorted(set(train + hold + real_seasons)):
        pg, bench, audit = load_season(args.data_root, season, args.min_pa, args.limit_games)
        history = season_history(pg)
        legs = proxy_legs(pg, history, season)
        audit.update({"legs": int(len(legs)), "legs_by_market": {k: int(v) for k, v in legs.market.value_counts().items()},
                      "games_with_legs": int(legs.game_id.nunique()),
                      "legs_per_game": round(len(legs) / max(1, legs.game_id.nunique()), 1)})
        frames[season] = {"pg": pg, "bench": bench, "history": history, "legs": legs, "audit": audit}
        print("SEASON", json.dumps(audit), f"t={time.time() - t_start:.0f}s", flush=True)

    rates = role_rates(pd.concat([frames[s]["legs"] for s in train], ignore_index=True))
    for s in frames:
        frames[s]["legs"] = attach_marginals(frames[s]["legs"], rates)
    calib = {str(s): _calibration(frames[s]["legs"], pcols) for s in frames}

    # A. the requested test: proxy cells fit on train, scored on the holdout's proxy legs. Pairs stay one set per
    # season (fit_cells takes the list); only the scored holdout is ever one array.
    train_pairs = [build_pairs(frames[s].pop("legs"), pcols) for s in train]
    hold_parts = [build_pairs(frames[s].pop("legs"), pcols) for s in hold]
    hold_pairs = hold_parts[0] if len(hold_parts) == 1 else concat_pairs(hold_parts)
    del hold_parts
    for s in list(frames):
        frames[s].pop("legs", None)                      # the real season's proxy legs: audit and calibration only
        if s not in real_seasons:
            frames[s].pop("history", None)
            frames[s].pop("pg", None)
            frames[s].pop("bench", None)
    n_pairs = {"train": int(sum(len(p["game"]) for p in train_pairs)), "holdout": int(len(hold_pairs["game"]))}
    print("PAIRS", json.dumps(n_pairs), f"t={time.time() - t_start:.0f}s", f"rss_peak_mb={_peak_mb()}", flush=True)
    oos_a: dict[str, Any] = {}
    for pc in pcols:
        cells = fit_cells(train_pairs, pc)
        raw = evaluate(hold_pairs, cells, pc)
        alt = copy.deepcopy(cells)
        alt_priors = shrink_second_moment(alt)
        priors = shrink_cells(cells)
        shrunk = evaluate(hold_pairs, cells, pc, by_cell=True)
        second = evaluate(hold_pairs, alt, pc)
        oos_a[pc] = {"cells_fitted": len(cells["market"]), "shrinkage": priors, "logloss_raw": raw,
                     "logloss": shrunk, "logloss_second_moment_shrink": second, "second_moment_priors": alt_priors}
        print("OOS_A", pc, "raw", json.dumps(_z(raw)), "shrunk", json.dumps(_z(shrunk)), "second_moment",
              json.dumps(_z(second)), f"t={time.time() - t_start:.0f}s", flush=True)
    verdict = falsification(oos_a[pub]["logloss"])
    print("FALSIFICATION", json.dumps(verdict), flush=True)

    # Refit on train + holdout for the published cells (both marginals, for B) -- the seasons as parts, never one copy.
    all_pairs = train_pairs + [hold_pairs]
    del train_pairs, hold_pairs
    n_pairs["published_fit"] = int(sum(len(p["game"]) for p in all_pairs))
    published: dict[str, Any] = {}
    unshrunk: dict[str, Any] = {}
    for pc in pcols:
        cells = fit_cells(all_pairs, pc)
        unshrunk[pc] = copy.deepcopy(cells)
        priors = shrink_cells(cells)
        zeroed = apply_falsification(cells, verdict)
        published[pc] = (cells, priors, zeroed)
        print("REFIT", pc, "market cells", len(cells["market"]), "falsified to 0", zeroed,
              f"t={time.time() - t_start:.0f}s", flush=True)
    del all_pairs

    oos_b: dict[str, Any] = {}
    oos_c: dict[str, Any] = {}
    engine: dict[str, Any] = {"coverage": {str(s): frames[s]["audit"] for s in sorted(frames)}}
    real_audit: dict[str, Any] = {}
    for season in real_seasons:
        f = frames[season]
        real, real_audit = book_legs(odds_files(args.data_root, season), f["pg"], season, f["bench"])
        print("REAL", json.dumps(real_audit), flush=True)
        if real.empty:
            continue
        split = args.real_split or f"{season}-07-01"
        rp = build_pairs(real, ("p_fair",))
        late = np.isin(rp["game"], real.loc[real.date >= split, "game_id"].unique())
        print("REAL_PAIRS", len(rp["game"]), "late", int(late.sum()), flush=True)
        rp_late = subset_pairs(rp, late)
        for pc in pcols:
            cells, _, _ = published[pc]
            alt = copy.deepcopy(unshrunk[pc])
            shrink_second_moment(alt)
            oos_b[pc] = {"all": evaluate(rp, cells, "p_fair", by_cell=True),
                         "from_" + split: evaluate(rp_late, cells, "p_fair"),
                         "all_raw": evaluate(rp, unshrunk[pc], "p_fair"),
                         "all_second_moment_shrink": evaluate(rp, alt, "p_fair")}
            print("OOS_B", pc, json.dumps(_z(oos_b[pc]["all"])), "raw", json.dumps(_z(oos_b[pc]["all_raw"])),
                  "second_moment", json.dumps(_z(oos_b[pc]["all_second_moment_shrink"])), flush=True)
        c_h1 = fit_cells(subset_pairs(rp, ~late), "p_fair")
        raw = evaluate(rp_late, c_h1, "p_fair")
        alt = copy.deepcopy(c_h1)
        shrink_second_moment(alt)
        shrink_cells(c_h1)
        oos_c = {"train": f"{season} regular season before {split}", "holdout": f"from {split}",
                 "logloss_raw": raw, "logloss": evaluate(rp_late, c_h1, "p_fair", by_cell=True),
                 "logloss_second_moment_shrink": evaluate(rp_late, alt, "p_fair"),
                 "cells_h1": strip_cells(c_h1)}
        print("OOS_C", json.dumps(_z(oos_c["logloss"])), "raw", json.dumps(_z(raw)), "second_moment",
              json.dumps(_z(oos_c["logloss_second_moment_shrink"])), flush=True)
        real_cells = fit_cells(rp, "p_fair")
        real_priors = shrink_cells(real_cells)
        engine["lines"] = {"season": season, **line_read(real, f["history"], f["pg"])}
        real_payload = {"schema": "mlb_sgp_correlations_v1",
                        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "seasons": [season], "season_type": "REG",
                        "source": "real pregame consensus lines (OddsAPI snapshot ~10 min before first pitch; "
                                  "batter hits, total bases, pitcher strikeouts only)",
                        "method": "gaussian copula on (over_a, over_b); rho from the concordance moment at real "
                                  "de-vigged consensus lines; game-clustered SE (build_nfl_sgp_correlations.fit_rho)",
                        "roles": "none -- every leg is MARKET|UNK; market cells only",
                        "min_cell_pairs": MIN_CELL, "min_pa": args.min_pa, "audit": real_audit,
                        "marginal_calibration": _calibration(real, ("p_fair",)), "shrinkage": real_priors,
                        "nested_same_player": list(NESTED_SAME_PLAYER),
                        "out_of_sample": {"split": {k: v for k, v in oos_c.items() if k != "cells_h1"}},
                        "cells": strip_cells(real_cells)}
        (args.out / "mlb_sgp_correlations_real_lines.json").write_text(json.dumps(real_payload, indent=1),
                                                                         encoding="utf-8")
        print("WROTE", args.out / "mlb_sgp_correlations_real_lines.json", flush=True)

    cells, priors, zeroed = published[pub]
    run = {"seconds": round(time.time() - t_start, 1), "peak_rss_mb": _peak_mb(), "pairs": n_pairs}
    payload = {"schema": "mlb_sgp_correlations_v1", "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "seasons": train + hold, "season_type": "REG",
               "method": "gaussian copula on (over_a, over_b) at PROXY lines (player's prior median -> x.5); rho from "
                         "the concordance moment with within-cell marginal recalibration; game-clustered SE "
                         "(build_nfl_sgp_correlations.fit_rho / shrink_cells); pairs and lookup from "
                         "build_nhl_sgp_correlations",
               "marginal": args.marginal,
               "roles": "none -- every leg is MARKET|UNK; market cells only (cells.type is empty, rho_for falls "
                        "through to cells.market)",
               "min_cell_pairs": MIN_CELL, "min_prior_games": MIN_PRIOR, "min_pa": args.min_pa, "shrink_k": SHRINK_K,
               "nested_same_player": list(NESTED_SAME_PLAYER),
               "falsification": {"rule": "a relation whose test-A gain (shrunk cells, published marginal) is not "
                                         "below zero at z <= -2 is 'no measured correlation' and its cells are 0; "
                                         "same_player judged on non-nested pairs",
                                 "verdict": verdict, "cells_zeroed": zeroed},
               "audit": {"seasons": [frames[s]["audit"] for s in sorted(frames)], "real_lines": real_audit,
                         "run": run},
               "marginal_calibration": calib, "shrinkage": priors,
               "out_of_sample": {"A_proxy": {"train": train, "holdout": hold, **oos_a},
                                 "B_proxy_cells_on_real_lines": oos_b, "C_real_line_cells": oos_c},
               "engine_read": engine, "cells": strip_cells(cells),
               "cells_other_marginal": {k: strip_cells(v[0]) for k, v in published.items() if k != pub}}
    (args.out / "mlb_sgp_correlations.json").write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print("WROTE", args.out / "mlb_sgp_correlations.json", "market cells", len(cells["market"]), json.dumps(run),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
