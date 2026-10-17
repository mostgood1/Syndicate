#!/usr/bin/env python
"""NHL same-game-parlay leg correlations from box scores (lane `nhl-sgp-builder`, 2026-10-16).

The NHL cheat sheet's SGPs need the joint probability of two legs. It is measured here, never assumed, with the
estimator of `scripts/build_nfl_sgp_correlations.py` -- imported from that script, not copied, so the two sports'
cells mean the same thing to `syndicate.features.nfl.sgp.rho_for`.

  1. PLAYER-GAMES from api-web box scores, REGULAR SEASON only (gameType 2; playoffs are a different population).
     Field handling is the repo's: `boxscore_log.rows_from_boxscore` (sog / goals / assists / saves, zero kept as 0)
     and `lineups._toi_to_min` / `_canonical_pos`. A player with no ice time is dropped, as a book voids him.
  2. ROLE = the NHL engine's `line_slot`, rebuilt leak-free: the team's last 8 EARLIER regular-season games give each
     player an average TOI over the games he played in them; tonight's dressed forwards ranked by it fill L1..L4
     (3 per line), defensemen D1..D3 (2 per pair) -- `lineups.infer_lines`' rule. A dressed player absent from the
     window is UNK. G = the game's starting goalie (the box score's `starter` flag; most TOI only if it is absent).
     Box scores carry NO line combinations: a same-slot teammate pair (L1 x L1) is the LINEMATE PROXY, by TOI rank.
  3. LEGS, one per (game, player, market), from the player's EARLIER games this season (>= 5 of them):
       SOG / SAVES at a proxy book line -- the prior median rounded to x.5 (an integer median goes up when the prior
       mean is above it, else down), snapped to a typical market line; POINTS the same over {0.5, 1.5};
       GOALS 0.5; ASSISTS 0.5. Saves history counts STARTS only.
     MARGINAL P(over), two variants, both leak-free for the holdout:
       role   -- the TRAIN seasons' over-rate per (market, role, line);
       player -- the player's own prior over-rate at that line, shrunk to the role rate with SHRINK_K pseudo-games.
  4. PAIRS within a game: same_player / teammate / opponent; cell = (type_a, type_b, relation), types sorted, where a
     type is market|role -- the NFL schema.
  5. rho per cell from the concordance moment with within-cell marginal recalibration and a game-clustered SE
     (`fit_rho`), shrunk empirical-Bayes per level x relation (`shrink_cells`) -- both the NFL script's own.
  6. OUT OF SAMPLE, four-cell log loss, copula vs independence on the SAME marginals, game-clustered SE:
       A. proxy cells fit on the train season, scored on the holdout season's proxy legs (the requested test);
       B. proxy cells fit on all box-score seasons, scored on 2025-26 REAL pregame book lines at their de-vigged
          consensus -- the population the sheet applies them to;
       C. real-line cells fit on 2025-26 before 2026-01-01, scored on 2025-26 from 2026-01-01 (with B on the same
          half, for a like-for-like comparison).
  7. ENGINE READ: where books set 2025-26 lines against the proxy rule, and the realised over-rates at each.

Run on the fleet at idle priority (it shares the host with production):
  nice -n 19 python scripts/build_nhl_sgp_correlations.py --data-root /home/amyn/syndicate-prod/data --out /tmp/nhl_sgp
"""
from __future__ import annotations

import argparse
import ast
import collections
import copy
import glob
import gzip
import importlib.util
import json
import math
import statistics
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.nfl.sgp import joint_over, name_key, rho_for  # noqa: E402 -- the consumer's own lookup
from syndicate.features.nhl.boxscore_log import _text as _box_text  # noqa: E402
from syndicate.features.nhl.boxscore_log import rows_from_boxscore  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.ingestion.lineups import _canonical_pos, _toi_to_min  # noqa: E402
from syndicate.features.shared.opportunity_signals import implied_probability  # noqa: E402


def _nfl_builder():
    """The NFL study's module: `fit_rho`, `shrink_cells`, `clustered_se`, `four_cell` are used AS IS."""
    spec = importlib.util.spec_from_file_location("build_nfl_sgp_correlations",
                                                  ROOT / "scripts" / "build_nfl_sgp_correlations.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_nfl = _nfl_builder()
fit_rho = _nfl.fit_rho
shrink_cells = _nfl.shrink_cells
clustered_se = _nfl.clustered_se
four_cell = _nfl.four_cell

SKATER_MARKETS = ("SOG", "POINTS", "GOALS", "ASSISTS")
MARKETS = SKATER_MARKETS + ("SAVES",)
STAT = {"SOG": "shots", "POINTS": "points", "GOALS": "goals", "ASSISTS": "assists", "SAVES": "saves"}
ODDS_KEYS = {"player_shots_on_goal": "SOG", "player_points": "POINTS", "player_goals": "GOALS",
             "player_assists": "ASSISTS", "player_total_saves": "SAVES"}
TYPICAL_LINES = {"SOG": (0.5, 1.5, 2.5, 3.5, 4.5, 5.5), "POINTS": (0.5, 1.5), "GOALS": (0.5,), "ASSISTS": (0.5,),
                 "SAVES": tuple(k + 0.5 for k in range(15, 40))}
FORWARD_SLOTS = ("L1", "L2", "L3", "L4")
DEFENSE_SLOTS = ("D1", "D2", "D3")
ROLE_WINDOW = 8           # `lineups.build_team_usage` n_games
MIN_PRIOR = 5             # earlier games (starts for a goalie) a leg needs before its proxy line exists
MIN_CELL = 300            # as the NFL study
SHRINK_K = 20.0           # pseudo-games pulling a player's prior over-rate to his role's
REL = ("same_player", "teammate", "opponent")
# Same player at 0.5: a goal IS a point, an assist IS a point -- one leg implies the other, not a parlay.
NESTED_SAME_PLAYER = ("ASSISTS~POINTS~same_player", "GOALS~POINTS~same_player")
REAL_SPLIT = "2026-01-01"


# ------------------------------------------------------------------------------------------------ box scores
def _key(name: Any) -> tuple[str, str] | None:
    """`name_key` after folding accents: the box score says 'T. Stützle', the books 'Tim Stutzle'."""
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")
    return name_key(text)


def player_rows(box: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row per player who PLAYED a finished regular-season game (toi > 0)."""
    if int(box.get("gameType") or 0) != 2 or str(box.get("gameState") or "") not in {"OFF", "FINAL"}:
        return []
    side_of: dict[str, tuple[str, str]] = {}
    abbr = {}
    for side in ("homeTeam", "awayTeam"):
        blk = box.get(side) or {}
        full = " ".join(p for p in (_box_text(blk.get("placeName")), _box_text(blk.get("commonName"))) if p)
        abbr[side] = str(blk.get("abbrev") or "").upper()
        side_of[full] = (abbr[side], side)
    starter = {}
    for side in ("homeTeam", "awayTeam"):
        for g in ((box.get("playerByGameStats") or {}).get(side) or {}).get("goalies") or []:
            if g.get("playerId") is not None and "starter" in g:
                starter[int(g["playerId"])] = bool(g["starter"])
    out = []
    for r in rows_from_boxscore(box):
        team, side = side_of.get(r["team"], ("", ""))
        toi = _toi_to_min(r["timeOnIce"])
        if not team or toi <= 0:
            continue
        pid = int(r["player_id"])
        try:
            name = ast.literal_eval(r["player"]).get("default")
        except (ValueError, SyntaxError):
            name = None
        num = lambda c: int(float(r[c])) if r[c] not in ("", None) else 0  # noqa: E731
        goalie = r["role"] == "goalie"
        out.append({"game_id": int(r["gamePk"]), "start": r["date"], "team": team,
                    "opp": abbr["awayTeam" if side == "homeTeam" else "homeTeam"], "pid": pid, "name": name,
                    "pos": "G" if goalie else _canonical_pos(r["primary_position"]), "toi": toi,
                    "shots": 0 if goalie else num("shots"), "goals": 0 if goalie else num("goals"),
                    "assists": 0 if goalie else num("assists"),
                    "points": 0 if goalie else num("goals") + num("assists"),
                    "saves": num("saves") if goalie else 0, "starter": starter.get(pid) if goalie else None})
    if out:
        # A goalie row with no `starter` flag: the one with the most ice time on his side started.
        for team in {r["team"] for r in out}:
            gs = [r for r in out if r["team"] == team and r["pos"] == "G"]
            if gs and all(r["starter"] is None for r in gs):
                top = max(gs, key=lambda r: r["toi"])
                for r in gs:
                    r["starter"] = r is top
    return out


def load_boxscores(paths: Iterable[str]) -> pd.DataFrame:
    rows = []
    for path in sorted(paths):
        try:
            with open(path, encoding="utf-8") as fh:
                rows += player_rows(json.load(fh))
        except (OSError, ValueError):
            continue
    pg = pd.DataFrame(rows)
    pg["starter"] = pg["starter"].astype(object)
    return pg.sort_values(["start", "game_id", "team", "pid"]).reset_index(drop=True)


# ------------------------------------------------------------------------------------------------ roles
def line_slots(pg: pd.DataFrame, window: int = ROLE_WINDOW) -> dict[tuple[int, int], str]:
    """(game_id, pid) -> L1..L4 / D1..D3 / G / UNK, from the team's EARLIER games only (see the docstring, step 2).
    Tonight's dressed lineup is used to RANK (lineups are known before puck drop); tonight's ice time never is."""
    out: dict[tuple[int, int], str] = {}
    for _team, g in pg.groupby("team", sort=False):
        order = g[["game_id", "start"]].drop_duplicates().sort_values(["start", "game_id"]).game_id.tolist()
        by_game = {gid: rows for gid, rows in g.groupby("game_id")}
        past: collections.deque = collections.deque(maxlen=window)
        for gid in order:
            tot: dict[int, float] = collections.defaultdict(float)
            cnt: dict[int, int] = collections.defaultdict(int)
            for game in past:
                for pid, toi in game.items():
                    tot[pid] += toi
                    cnt[pid] += 1
            avg = {pid: tot[pid] / cnt[pid] for pid in tot}
            rows = by_game[gid]
            for pos, slots, size in (("F", FORWARD_SLOTS, 3), ("D", DEFENSE_SLOTS, 2)):
                dressed = rows[rows.pos == pos].pid.tolist()
                ranked = sorted((p for p in dressed if p in avg), key=lambda p: (-avg[p], p))
                for i, pid in enumerate(ranked):
                    out[(gid, pid)] = slots[min(i // size, len(slots) - 1)]
                for pid in dressed:
                    out.setdefault((gid, pid), "UNK")
            for r in rows[rows.pos == "G"].itertuples():
                out[(gid, r.pid)] = "G" if r.starter else "G_RELIEF"
            past.append(dict(zip(rows.pid, rows.toi)))
    return out


# ------------------------------------------------------------------------------------------------ legs
def proxy_line(past: list[float], market: str) -> float:
    """A book-like line from a player's EARLIER games: the median rounded to x.5 (an integer median goes up when the
    mean is above it, else down), snapped to the nearest typical line for the market."""
    med = float(statistics.median(past))
    if med != math.floor(med):
        line = med
    else:
        line = med + 0.5 if float(np.mean(past)) > med else med - 0.5
    lines = TYPICAL_LINES[market]
    return min(lines, key=lambda x: (abs(x - line), x))


def season_history(pg: pd.DataFrame) -> pd.DataFrame:
    """Per player-game, from his EARLIER games this season only (a goalie's: earlier STARTS): games, and for each
    market the proxy line, how often he cleared it, and his mean. Current-game stats are appended AFTER the read."""
    hist: dict[int, dict[str, list[float]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    recs = []
    for r in pg.itertuples(index=False):
        h = hist[r.pid]
        rec: dict[str, Any] = {"game_id": r.game_id, "pid": r.pid}
        markets = ("SAVES",) if r.pos == "G" else SKATER_MARKETS
        if r.pos == "G" and not r.starter:
            recs.append(dict(rec, prior_n=0))
            continue
        n = len(h[markets[0]])
        rec["prior_n"] = n
        for m in markets:
            past = h[m]
            if n >= MIN_PRIOR:
                line = proxy_line(past, m)
                rec[f"line_{m}"] = line
                rec[f"overs_{m}"] = int(sum(v > line for v in past))
                rec[f"mean_{m}"] = float(np.mean(past))
        for m in markets:
            h[m].append(float(getattr(r, STAT[m])))
        recs.append(rec)
    return pd.DataFrame(recs)


def proxy_legs(pg: pd.DataFrame, history: pd.DataFrame, roles: Mapping[tuple[int, int], str],
               season: int) -> pd.DataFrame:
    """One leg per (game, player, market) at the proxy line; over = stat > line (x.5, so no push)."""
    d = pg.merge(history, on=["game_id", "pid"], how="left")
    d = d[d.prior_n >= MIN_PRIOR]
    rows = []
    for m in MARKETS:
        if f"line_{m}" not in d:
            continue
        sub = d[(d.pos == "G") if m == "SAVES" else (d.pos != "G")]
        sub = sub[sub[f"line_{m}"].notna()]
        rows.append(pd.DataFrame({
            "game_id": sub.game_id.values, "start": sub.start.values, "team": sub.team.values, "pid": sub.pid.values,
            "market": m, "line": sub[f"line_{m}"].values, "actual": sub[STAT[m]].values,
            "prior_n": sub.prior_n.values, "prior_overs": sub[f"overs_{m}"].values}))
    legs = pd.concat(rows, ignore_index=True)
    legs["over"] = (legs.actual > legs.line).astype(np.int8)
    legs["role"] = [roles.get((g, p), "UNK") for g, p in zip(legs.game_id, legs.pid)]
    legs = legs[legs.role != "G_RELIEF"].copy()
    legs["type"] = legs.market + "|" + legs.role
    legs["season"] = season
    return legs.reset_index(drop=True)


def role_rates(legs: pd.DataFrame) -> dict[str, dict]:
    """Over-rate tables from the reference (train) legs: (market, role, line), (market, line), market."""
    out = {}
    for name, cols in (("mrl", ["market", "role", "line"]), ("ml", ["market", "line"]), ("m", ["market"])):
        g = legs.groupby(cols).over.agg(["sum", "count"])
        out[name] = {k if isinstance(k, tuple) else (k,): (float(s), int(c)) for k, (s, c) in g.iterrows()}
    return out


def attach_marginals(legs: pd.DataFrame, rates: Mapping[str, dict], k: float = SHRINK_K,
                     min_n: int = 30) -> pd.DataFrame:
    """p_role: the reference over-rate at the finest level with >= `min_n` legs (Laplace-smoothed);
    p_player: the player's prior overs at that line shrunk to p_role with `k` pseudo-games."""
    p_role = []
    for m, r, line in zip(legs.market, legs.role, legs.line):
        for name, key in (("mrl", (m, r, line)), ("ml", (m, line)), ("m", (m,))):
            hit = rates[name].get(key)
            if hit and hit[1] >= min_n:
                p_role.append((hit[0] + 1.0) / (hit[1] + 2.0))
                break
        else:
            p_role.append(0.5)
    legs = legs.copy()
    legs["p_role"] = np.clip(np.array(p_role), 0.02, 0.98)
    legs["p_player"] = np.clip((legs.prior_overs + k * legs.p_role) / (legs.prior_n + k), 0.02, 0.98)
    return legs


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


def consensus_legs(quotes: Mapping[tuple[str, str, float], Mapping[str, Mapping[str, float]]]) -> list[dict[str, Any]]:
    """One leg per (market, player): the line the most books quote both sides of (ties: nearest the median line),
    fair P(over) = median across books of the two-way de-vigged price -- the NFL study's rule."""
    by_leg: dict[tuple[str, str], list] = collections.defaultdict(list)
    for (market, player, line), books in quotes.items():
        two_way = {b: s for b, s in books.items() if "over" in s and "under" in s}
        if two_way:
            by_leg[(market, player)].append((line, two_way))
    out = []
    for (market, player), options in by_leg.items():
        mid = float(np.median([o[0] for o in options]))
        line, books = max(options, key=lambda x: (len(x[1]), -abs(x[0] - mid)))
        qo = np.array([implied_probability(s["over"]) for s in books.values()])
        qu = np.array([implied_probability(s["under"]) for s in books.values()])
        out.append({"market": market, "player": player, "line": float(line), "n_books": len(books),
                    "fair": float(np.median(qo / (qo + qu))), "q_over": float(np.median(qo)),
                    "q_under": float(np.median(qu))})
    return out


def book_legs(files_by_game: Mapping[int, list[str]], pg: pd.DataFrame, roles: Mapping[tuple[int, int], str],
              season: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Real pregame consensus legs for the games' box scores; a listed player who did not play is void (dropped)."""
    audit = collections.Counter()
    played = {gid: g for gid, g in pg.groupby("game_id")}
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
            snap = (doc.get("snap") or {})
            data = snap.get("data") or {}
            if str(snap.get("timestamp") or "") >= str(data.get("commence_time") or "~"):
                audit["snapshot_not_pregame"] += 1
                continue
            for k, books in snapshot_quotes(data).items():
                for b, s in books.items():
                    quotes[k][b].update(s)
        g = played.get(gid)
        if g is None:
            audit["game_without_boxscore"] += 1
            continue
        keys: dict[tuple[str, str], set] = collections.defaultdict(set)
        for pid, name in zip(g.pid, g.name):
            k = _key(name)
            if k:
                keys[k].add(pid)
        by_pid = {r.pid: r for r in g.itertuples(index=False)}
        for leg in consensus_legs(quotes):
            audit["legs_quoted"] += 1
            pids = keys.get(_key(leg["player"]) or ("", ""), set())
            if len(pids) != 1:
                audit["legs_void_or_unmatched" if not pids else "legs_ambiguous_name"] += 1
                continue
            pid = next(iter(pids))
            r = by_pid[pid]
            if (leg["market"] == "SAVES") != (r.pos == "G"):
                audit["legs_market_position_mismatch"] += 1
                continue
            role = roles.get((gid, pid), "UNK")
            if leg["market"] == "SAVES" and role != "G":
                audit["legs_saves_not_starter"] += 1
                continue
            actual = float(getattr(r, STAT[leg["market"]]))
            if actual == leg["line"]:
                audit["legs_push"] += 1
                continue
            rows.append(dict(leg, game_id=gid, start=r.start, team=r.team, pid=pid, role=role, actual=actual,
                             over=int(actual > leg["line"]), season=season))
    legs = pd.DataFrame(rows)
    before = len(legs)
    legs = legs.sort_values("n_books", ascending=False).drop_duplicates(["game_id", "pid", "market"])
    audit["legs_duplicate_spelling_dropped"] = before - len(legs)
    legs["type"] = legs.market + "|" + legs.role
    legs["p_fair"] = legs.fair.clip(0.02, 0.98)
    audit["legs_graded"] = len(legs)
    audit["games_graded"] = int(legs.game_id.nunique())
    return legs.reset_index(drop=True), dict(audit)


# ------------------------------------------------------------------------------------------------ pairs and cells
def build_pairs(legs: pd.DataFrame, pcols: Iterable[str]) -> dict[str, Any]:
    """Every within-game pair as numpy arrays (a season is ~10^7 pairs, too many for a DataFrame of strings).
    Legs are sorted by type inside a game, so type_a <= type_b -- the key order `rho_for` builds."""
    pcols = list(pcols)
    legs = legs.sort_values(["game_id", "type", "pid"], kind="mergesort").reset_index(drop=True)
    types = sorted(legs["type"].unique())
    markets = sorted(legs["market"].unique())
    tcode = legs["type"].map({t: i for i, t in enumerate(types)}).to_numpy(np.int16)
    mcode = legs["market"].map({m: i for i, m in enumerate(markets)}).to_numpy(np.int8)
    team = pd.factorize(legs["team"])[0]
    pid = legs["pid"].to_numpy(np.int64)
    game = legs["game_id"].to_numpy(np.int32)          # NHL game ids (2025021312) fit in int32
    cut = np.flatnonzero(np.diff(game)) + 1
    ii, jj = [], []
    for s, e in zip(np.r_[0, cut], np.r_[cut, len(game)]):
        if e - s < 2:
            continue
        i, j = np.triu_indices(e - s, k=1)
        ii.append(i + s)
        jj.append(j + s)
    i = np.concatenate(ii) if ii else np.zeros(0, np.int64)
    j = np.concatenate(jj) if jj else np.zeros(0, np.int64)
    out = {"types": types, "markets": markets, "game": game[i], "ta": tcode[i], "tb": tcode[j],
           "ma": mcode[i], "mb": mcode[j],
           "rel": np.where(pid[i] == pid[j], 0, np.where(team[i] == team[j], 1, 2)).astype(np.int8),
           "o_a": legs["over"].to_numpy(np.int8)[i], "o_b": legs["over"].to_numpy(np.int8)[j]}
    for c in pcols:
        p = legs[c].to_numpy(np.float32)
        out[f"{c}_a"], out[f"{c}_b"] = p[i], p[j]
    return out


def concat_pairs(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Pairs from several frames, re-coded onto one type / market vocabulary."""
    types = sorted({t for p in parts for t in p["types"]})
    markets = sorted({m for p in parts for m in p["markets"]})
    out: dict[str, Any] = {"types": types, "markets": markets}
    for p in parts:
        tmap = np.array([types.index(t) for t in p["types"]], np.int16)
        mmap = np.array([markets.index(m) for m in p["markets"]], np.int8)
        p = dict(p, ta=tmap[p["ta"]], tb=tmap[p["tb"]], ma=mmap[p["ma"]], mb=mmap[p["mb"]])
        for k, v in p.items():
            if isinstance(v, np.ndarray):
                out.setdefault(k, []).append(v)
    return {k: (np.concatenate(v) if isinstance(v, list) and k not in ("types", "markets") else v)
            for k, v in out.items()}


def subset_pairs(pairs: Mapping[str, Any], mask: np.ndarray) -> dict[str, Any]:
    return {k: (v[mask] if isinstance(v, np.ndarray) else v) for k, v in pairs.items()}


def _groups(pairs: Mapping[str, Any], level: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    a, b, names = ("ta", "tb", pairs["types"]) if level == "type" else ("ma", "mb", pairs["markets"])
    key = (pairs[a].astype(np.int64) * len(names) + pairs[b]) * 3 + pairs["rel"]
    order = np.argsort(key, kind="stable")
    uniq, start, count = np.unique(key[order], return_index=True, return_counts=True)
    return order, uniq, start, count, names


def _cell_name(k: int, names: list[str]) -> str:
    rel, ab = int(k % 3), int(k // 3)
    return f"{names[ab // len(names)]}~{names[ab % len(names)]}~{REL[rel]}"


def fit_cells(pairs: Mapping[str, Any], pcol: str, min_cell: int = MIN_CELL) -> dict[str, dict[str, dict[str, float]]]:
    """`fit_rho` per type cell and per market cell with >= `min_cell` pairs (the NFL study's levels)."""
    cells: dict[str, dict[str, dict[str, float]]] = {"type": {}, "market": {}}
    for level in ("type", "market"):
        order, uniq, start, count, names = _groups(pairs, level)
        for k, s, c in zip(uniq, start, count):
            if c < min_cell:
                continue
            idx = order[s:s + c]
            cells[level][_cell_name(k, names)] = fit_rho(
                pairs[f"{pcol}_a"][idx].astype(np.float64), pairs[f"{pcol}_b"][idx].astype(np.float64),
                pairs["o_a"][idx].astype(np.float64), pairs["o_b"][idx].astype(np.float64), pairs["game"][idx])
    return cells


def lookup_rho(pairs: Mapping[str, Any], cells: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """rho and level per pair through the CONSUMER's lookup (`rho_for`): role cell, else market cell, else 0."""
    types = pairs["types"]
    key = (pairs["ta"].astype(np.int64) * len(types) + pairs["tb"]) * 3 + pairs["rel"]
    uniq, inv = np.unique(key, return_inverse=True)
    rho_u, lvl_u = np.zeros(len(uniq)), np.empty(len(uniq), dtype=object)
    payload = {"cells": cells}
    for n, k in enumerate(uniq):
        ta, tb, rel = _cell_name(k, types).split("~")
        rho_u[n], lvl_u[n] = rho_for(payload, ta, tb, rel)
    return rho_u[inv], lvl_u[inv]


def evaluate(pairs: Mapping[str, Any], cells: Mapping[str, Any], pcol: str, chunk: int = 2_000_000,
             by_cell: bool = False) -> dict[str, Any]:
    """Four-cell log loss, copula vs independence on the same marginals, game-clustered SE -- per relation and per
    lookup level; plus predicted vs realised both-over rate (the copula's calibration)."""
    rho, level = lookup_rho(pairs, cells)
    n = len(rho)
    cop, ind, both_pred, indep = (np.empty(n) for _ in range(4))
    for s in range(0, n, chunk):                       # chunked: a season is ~10^7 pairs on a shared host
        e = min(n, s + chunk)
        p_a = pairs[f"{pcol}_a"][s:e].astype(np.float64)
        p_b = pairs[f"{pcol}_b"][s:e].astype(np.float64)
        obs = (1 - pairs["o_a"][s:e].astype(np.int64)) * 2 + (1 - pairs["o_b"][s:e].astype(np.int64))
        rows = np.arange(e - s)
        cop[s:e] = -np.log(four_cell(p_a, p_b, rho[s:e])[rows, obs])
        ind[s:e] = -np.log(four_cell(p_a, p_b, 0.0)[rows, obs])
        both_pred[s:e] = joint_over(p_a, p_b, rho[s:e])
        indep[s:e] = p_a * p_b
    diff = cop - ind
    both = ((pairs["o_a"] == 1) & (pairs["o_b"] == 1)).astype(np.float64)
    out = {}
    masks = [("all", np.ones(len(diff), bool))]
    masks += [(f"relation={r}", pairs["rel"] == i) for i, r in enumerate(REL)]
    masks += [(f"level={lv}", level == lv) for lv in ("role", "market", "none")]
    for name, mask in masks:
        if not mask.any():
            continue
        se = clustered_se(diff[mask], pairs["game"][mask])
        d = float(diff[mask].mean())
        out[name] = {"pairs": int(mask.sum()), "games": int(len(np.unique(pairs["game"][mask]))),
                     "logloss_copula": round(float(cop[mask].mean()), 6), "logloss_indep": round(float(ind[mask].mean()), 6),
                     "diff": round(d, 6), "diff_se_game_clustered": round(float(se), 6),
                     "z": round(d / se, 2) if se else None,
                     "mean_abs_rho_used": round(float(np.abs(rho[mask]).mean()), 4),
                     "both_over_predicted": round(float(both_pred[mask].mean()), 4),
                     "both_over_realised": round(float(both[mask].mean()), 4),
                     "both_over_independent": round(float(indep[mask].mean()), 4)}
    if by_cell:
        # Which market x market x relation cells carry the gain (or the loss) -- cells with >= 2,000 pairs.
        order, uniq, start, count, names = _groups(pairs, "market")
        cell_out = {}
        for k, s, c in zip(uniq, start, count):
            if c < 2000:
                continue
            idx = order[s:s + c]
            se = clustered_se(diff[idx], pairs["game"][idx])
            d = float(diff[idx].mean())
            cell_out[_cell_name(k, names)] = {"pairs": int(c), "diff": round(d, 6), "z": round(d / se, 2) if se else None,
                                              "mean_rho_used": round(float(rho[idx].mean()), 4),
                                              "both_over_predicted": round(float(both_pred[idx].mean()), 4),
                                              "both_over_realised": round(float(both[idx].mean()), 4),
                                              "both_over_independent": round(float(indep[idx].mean()), 4)}
        out["by_market_cell"] = cell_out
    return out


def shrink_second_moment(cells: dict[str, dict[str, dict[str, float]]]) -> dict[str, Any]:
    """DIAGNOSTIC ONLY -- never the published cells. `shrink_cells` with tau^2 = mean(rho^2) - mean(se^2), the
    method-of-moments variance of the N(0, tau^2) prior it shrinks toward. `shrink_cells` uses var(rho), the spread
    about the cells' MEAN, while shrinking toward 0: a relation whose cells share one non-zero level (all mildly
    positive) has a small spread, so it is over-shrunk -- to exactly 0 when the spread is below the noise."""
    priors: dict[str, Any] = {}
    for level, group in cells.items():
        by_rel: dict[str, list[str]] = collections.defaultdict(list)
        for key in group:
            by_rel[key.rsplit("~", 1)[1]].append(key)
        for rel, keys in by_rel.items():
            rho = np.array([group[k]["rho"] for k in keys])
            se2 = np.array([group[k]["se"] ** 2 for k in keys])
            tau2 = max(float((rho ** 2).mean() - se2.mean()), 0.0)
            priors[f"{level}~{rel}"] = {"cells": len(keys), "tau": round(math.sqrt(tau2), 4)}
            for k, v in zip(keys, se2):
                group[k]["rho_raw"] = group[k]["rho"]
                group[k]["rho"] = round(group[k]["rho_raw"] * (tau2 / (tau2 + v) if tau2 > 0 else 0.0), 4)
    return priors


def strip_cells(cells: Mapping[str, Any]) -> dict[str, Any]:
    """The schema's per-cell fields (rho, rho_raw, se, n, games) plus the diagnostic rates."""
    return {lvl: {k: dict(v) for k, v in sorted(group.items())} for lvl, group in cells.items()}


# ------------------------------------------------------------------------------------------------ engine read
def line_read(real: pd.DataFrame, history: pd.DataFrame, pg: pd.DataFrame,
              rates: Mapping[str, dict]) -> dict[str, Any]:
    """Real 2025-26 book lines against the proxy rule run on the same player's earlier 2025-26 games."""
    h = history.merge(pg[["game_id", "pid", "pos"] + list(STAT.values())], on=["game_id", "pid"])
    out = {}
    for m in MARKETS:
        b = real[real.market == m]
        if b.empty:
            continue
        j = b.merge(h[["game_id", "pid", "prior_n", f"line_{m}", f"mean_{m}"]], on=["game_id", "pid"], how="left")
        j = j[j[f"line_{m}"].notna()]
        hp = h[h[f"line_{m}"].notna() & ((h.pos == "G") if m == "SAVES" else (h.pos != "G"))]
        proxy_over = (hp[STAT[m]] > hp[f"line_{m}"]).mean()
        diff = j.line - j[f"line_{m}"]
        rec = {"book_legs": int(len(b)), "book_line_top": {f"{k:g}": int(v) for k, v in b.line.value_counts().head(6).items()},
               "book_fair_over_mean": round(float(b.fair.mean()), 4),
               "book_line_over_realised": round(float(b.over.mean()), 4),
               "book_line_over_se_iid": round(float(math.sqrt(b.over.mean() * (1 - b.over.mean()) / len(b))), 4),
               "matched_to_proxy": int(len(j)),
               "proxy_equals_book": round(float((diff == 0).mean()), 4) if len(j) else None,
               "book_minus_proxy_mean": round(float(diff.mean()), 3) if len(j) else None,
               "book_above_proxy": round(float((diff > 0).mean()), 4) if len(j) else None,
               "book_below_proxy": round(float((diff < 0).mean()), 4) if len(j) else None,
               "proxy_line_over_realised_all_players": round(float(proxy_over), 4),
               "proxy_line_legs_all_players": int(len(hp))}
        if m == "SAVES" and len(j):
            rec["book_line_minus_prior_mean"] = round(float((j.line - j[f"mean_{m}"]).mean()), 3)
        out[m] = rec
    return out


def captured_read(quote_dir: Path, first_day: str) -> dict[str, Any]:
    """Current-season captured lines (book_quotes change log): the last pregame quote per book, the NFL consensus
    rule per (event, market, player). Only to compare line placement and fair P(over) with 2025-26."""
    last: dict[tuple, tuple[str, float]] = {}
    days = 0
    for path in sorted(glob.glob(str(quote_dir / "*.jsonl*"))):
        day = Path(path).name[:10]
        if day < first_day:
            continue
        days += 1
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("market") not in MARKETS or r.get("price") is None or r.get("line") is None:
                    continue
                if str(r.get("captured_at") or "") >= str(r.get("commence_time") or ""):
                    continue
                side = str(r.get("selection") or "").lower()
                if side not in ("over", "under"):
                    continue
                k = (r["event_id"], r["market"], r.get("player_name"), float(r["line"]), r["bookmaker"], side)
                if k not in last or r["captured_at"] >= last[k][0]:
                    last[k] = (r["captured_at"], float(r["price"]))
    by_event: dict[str, dict] = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(dict)))
    for (ev, market, player, line, book, side), (_, price) in last.items():
        by_event[ev][(market, str(player), line)][book][side] = price
    legs = [dict(leg, event=ev) for ev, q in by_event.items() for leg in consensus_legs(q)]
    out: dict[str, Any] = {"days": days, "events": len(by_event), "first_day": first_day}
    df = pd.DataFrame(legs)
    for m in MARKETS:
        b = df[df.market == m] if len(df) else df
        if b.empty:
            continue
        out[m] = {"legs": int(len(b)), "line_top": {f"{k:g}": int(v) for k, v in b.line.value_counts().head(6).items()},
                  "fair_over_mean": round(float(b.fair.mean()), 4), "books_median": float(b.n_books.median())}
    return out


# ------------------------------------------------------------------------------------------------ driver
def _season_paths(data_root: Path, season: int) -> list[str]:
    nl = data_root / "backfill" / "nhl_lines_2025_26" / f"boxscore_{season}"
    if nl.is_dir():
        return glob.glob(str(nl / "*.json"))
    return glob.glob(str(data_root / "backfill" / "nhl_source_dev" / "ingestion_cache" / f"boxscore_{season}02*.json"))


def _odds_files(data_root: Path, season: int) -> dict[int, list[str]]:
    base = data_root / "backfill" / f"nhl_lines_{season}_{(season + 1) % 100:02d}"
    out: dict[int, list[str]] = collections.defaultdict(list)
    for sub in ("odds_skater_props", "odds_saves", "odds_saves_rest"):
        for path in glob.glob(str(base / sub / f"{season}02*.json")):
            out[int(Path(path).stem)].append(path)
    return out


def _season_audit(season: int, pg: pd.DataFrame, legs: pd.DataFrame) -> dict[str, Any]:
    sk = pg[pg.pos != "G"]
    return {"season": season, "games": int(pg.game_id.nunique()), "player_games": int(len(pg)),
            "skater_games": int(len(sk)), "goalie_starts": int((pg.starter == True).sum()),  # noqa: E712
            "legs": int(len(legs)), "legs_by_market": {k: int(v) for k, v in legs.market.value_counts().items()},
            "legs_by_role": {k: int(v) for k, v in legs.role.value_counts().items()},
            "games_with_legs": int(legs.game_id.nunique())}


def _calibration(legs: pd.DataFrame, pcols: Iterable[str]) -> dict[str, Any]:
    out = {}
    for (m, r), g in legs.groupby(["market", "role"]):
        out[f"{m}|{r}"] = {"legs": int(len(g)), "over_rate": round(float(g.over.mean()), 4),
                           **{f"mean_{c}": round(float(g[c].mean()), 4) for c in pcols},
                           "lines": {f"{k:g}": int(v) for k, v in g.line.value_counts().head(4).items()}}
    return out


def _z(table: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v.get("z") for k, v in table.items() if k != "by_market_cell"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--train", default="2023")
    ap.add_argument("--holdout", default="2024")
    ap.add_argument("--real", default="2025", help="season with real pregame book lines ('' to skip)")
    ap.add_argument("--marginal", default="player", choices=("player", "role"),
                    help="the marginal the published cells are fitted with (both are evaluated)")
    ap.add_argument("--limit-games", type=int, default=0, help="smoke runs: the first N games of each season")
    ap.add_argument("--out", type=Path, default=Path("/tmp/nhl_sgp"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    train = [int(s) for s in args.train.split(",") if s]
    hold = [int(s) for s in args.holdout.split(",") if s]
    real_seasons = [int(s) for s in args.real.split(",") if s]
    pcols = ("p_role", "p_player")

    frames: dict[int, dict[str, Any]] = {}
    for season in sorted(set(train + hold + real_seasons)):
        paths = sorted(_season_paths(args.data_root, season))
        if args.limit_games:
            paths = paths[:args.limit_games]
        pg = load_boxscores(paths)
        history = season_history(pg)
        roles = line_slots(pg)
        legs = proxy_legs(pg, history, roles, season)
        frames[season] = {"pg": pg, "history": history, "roles": roles, "legs": legs}
        print("SEASON", json.dumps(_season_audit(season, pg, legs)), flush=True)

    rates = role_rates(pd.concat([frames[s]["legs"] for s in train], ignore_index=True))
    for s in frames:
        frames[s]["legs"] = attach_marginals(frames[s]["legs"], rates)
    calib = {str(s): _calibration(frames[s]["legs"], pcols) for s in frames}

    # A. the requested test: proxy cells fit on train, scored on the holdout's proxy legs.
    train_pairs = concat_pairs([build_pairs(frames[s]["legs"], pcols) for s in train])
    hold_pairs = concat_pairs([build_pairs(frames[s]["legs"], pcols) for s in hold])
    print("PAIRS train", len(train_pairs["game"]), "holdout", len(hold_pairs["game"]), flush=True)
    oos_a: dict[str, Any] = {}
    for pc in pcols:
        cells = fit_cells(train_pairs, pc)
        raw = evaluate(hold_pairs, cells, pc)
        alt = copy.deepcopy(cells)
        alt_priors = shrink_second_moment(alt)
        shrink_cells(cells)
        shrunk = evaluate(hold_pairs, cells, pc, by_cell=True)
        second = evaluate(hold_pairs, alt, pc)
        oos_a[pc] = {"logloss_raw": raw, "logloss": shrunk, "logloss_second_moment_shrink": second,
                     "second_moment_priors": alt_priors}
        print("OOS_A", pc, "raw", json.dumps(_z(raw)), "shrunk", json.dumps(_z(shrunk)), "second_moment",
              json.dumps(_z(second)), flush=True)

    # Refit on every box-score season for the published cells (both marginals, for B).
    all_pairs = concat_pairs([train_pairs, hold_pairs])
    del train_pairs, hold_pairs
    published: dict[str, Any] = {}
    unshrunk: dict[str, Any] = {}
    for pc in pcols:
        cells = fit_cells(all_pairs, pc)
        unshrunk[pc] = copy.deepcopy(cells)
        priors = shrink_cells(cells)
        published[pc] = (cells, priors)
        print("REFIT", pc, "cells type", len(cells["type"]), "market", len(cells["market"]), flush=True)
    del all_pairs

    oos_b: dict[str, Any] = {}
    oos_c: dict[str, Any] = {}
    engine: dict[str, Any] = {}
    real_cells = None
    real_audit = {}
    for season in real_seasons:
        f = frames[season]
        real, real_audit = book_legs(_odds_files(args.data_root, season), f["pg"], f["roles"], season)
        print("REAL", json.dumps(real_audit), flush=True)
        if real.empty:
            continue
        rp = build_pairs(real, ("p_fair",))
        late = np.isin(rp["game"], real.loc[real.start >= REAL_SPLIT, "game_id"].unique())
        print("REAL_PAIRS", len(rp["game"]), "h2", int(late.sum()), flush=True)
        rp_late = subset_pairs(rp, late)
        for pc in pcols:
            cells, _ = published[pc]
            alt = copy.deepcopy(unshrunk[pc])
            shrink_second_moment(alt)
            oos_b[pc] = {"all": evaluate(rp, cells, "p_fair", by_cell=True),
                         "from_" + REAL_SPLIT: evaluate(rp_late, cells, "p_fair"),
                         "all_raw": evaluate(rp, unshrunk[pc], "p_fair"),
                         "all_second_moment_shrink": evaluate(rp, alt, "p_fair")}
            print("OOS_B", pc, json.dumps(_z(oos_b[pc]["all"])), "raw", json.dumps(_z(oos_b[pc]["all_raw"])),
                  "second_moment", json.dumps(_z(oos_b[pc]["all_second_moment_shrink"])), flush=True)
        c_h1 = fit_cells(subset_pairs(rp, ~late), "p_fair")
        raw = evaluate(rp_late, c_h1, "p_fair")
        alt = copy.deepcopy(c_h1)
        shrink_second_moment(alt)
        shrink_cells(c_h1)
        oos_c = {"train": f"{season} regular season before {REAL_SPLIT}", "holdout": f"from {REAL_SPLIT}",
                 "logloss_raw": raw, "logloss": evaluate(rp_late, c_h1, "p_fair", by_cell=True),
                 "logloss_second_moment_shrink": evaluate(rp_late, alt, "p_fair")}
        print("OOS_C", json.dumps(_z(oos_c["logloss"])), "raw", json.dumps(_z(raw)), "second_moment",
              json.dumps(_z(oos_c["logloss_second_moment_shrink"])), flush=True)
        real_cells = fit_cells(rp, "p_fair")
        real_priors = shrink_cells(real_cells)
        real_calib = _calibration(real.assign(p_fair=real.p_fair), ("p_fair",))
        engine = {"season": season, "lines": line_read(real, f["history"], f["pg"], rates)}
        real_payload = {"schema": "nhl_sgp_correlations_v1", "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "seasons": [season], "season_type": "REG", "source": "real pregame consensus lines (OddsAPI snapshot ~15 min before start)",
                        "method": "gaussian copula on (over_a, over_b); rho from the concordance moment at real de-vigged "
                                  "consensus lines; game-clustered SE (build_nfl_sgp_correlations.fit_rho)",
                        "min_cell_pairs": MIN_CELL, "audit": real_audit, "marginal_calibration": real_calib,
                        "shrinkage": real_priors, "nested_same_player": list(NESTED_SAME_PLAYER),
                        "out_of_sample": {"split": oos_c}, "cells": strip_cells(real_cells)}
        (args.out / "nhl_sgp_correlations_real_lines.json").write_text(json.dumps(real_payload, indent=1), encoding="utf-8")
        print("WROTE", args.out / "nhl_sgp_correlations_real_lines.json", flush=True)

    try:
        stats_csv = args.data_root / "nhl_source" / "source_artifacts" / "data" / "raw" / "player_game_stats.csv"
        gl = pd.read_csv(stats_csv, usecols=["gamePk", "date"])
        first = str(gl[gl.gamePk.astype(str).str.startswith("202602")].date.min())[:10]
        engine["captured_2026_27"] = captured_read(args.data_root / "nhl_source" / "tracking" / "book_quotes", first)
    except (OSError, ValueError, KeyError) as exc:
        engine["captured_2026_27"] = {"error": str(exc)}

    cells, priors = published[f"p_{args.marginal}"]
    payload = {"schema": "nhl_sgp_correlations_v1", "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "seasons": train + hold, "season_type": "REG",
               "method": "gaussian copula on (over_a, over_b) at PROXY lines (player's prior median -> x.5); rho from "
                         "the concordance moment with within-cell marginal recalibration; game-clustered SE "
                         "(build_nfl_sgp_correlations.fit_rho / shrink_cells)",
               "marginal": args.marginal, "roles": "line_slot L1-L4 / D1-D3 by TOI over the team's last 8 earlier games; "
                                                  "G = starter; UNK = no game in the window",
               "linemates": "box scores carry no line combinations: a same-slot teammate pair is the linemate proxy",
               "min_cell_pairs": MIN_CELL, "min_prior_games": MIN_PRIOR, "shrink_k": SHRINK_K,
               "nested_same_player": list(NESTED_SAME_PLAYER),
               "audit": {"seasons": [_season_audit(s, frames[s]["pg"], frames[s]["legs"]) for s in sorted(frames)],
                         "real_lines": real_audit},
               "marginal_calibration": calib, "shrinkage": priors,
               "out_of_sample": {"A_proxy": {"train": train, "holdout": hold, **oos_a},
                                 "B_proxy_cells_on_real_lines": oos_b, "C_real_line_cells": oos_c},
               "engine_read": engine, "cells": strip_cells(cells),
               "cells_other_marginal": {k: strip_cells(v[0]) for k, v in published.items() if k != f"p_{args.marginal}"}}
    (args.out / "nhl_sgp_correlations.json").write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print("WROTE", args.out / "nhl_sgp_correlations.json", "cells type", len(cells["type"]), "market",
          len(cells["market"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
