#!/usr/bin/env python
"""Basketball (WNBA, NBA) same-game-parlay leg correlations from box scores (lane `basketball-sgp-builder`, 2026-10-17).

The basketball cheat sheets' SGPs need the joint probability of two legs. It is measured here, never assumed, with the
NFL study's estimator (`fit_rho`, `shrink_cells`, `clustered_se`, `four_cell`) and the NHL study's pair machinery
(`build_pairs`, `fit_cells`, `evaluate`, `consensus_legs`, ...) -- both IMPORTED from those scripts, never copied, so a
cell means the same thing to `syndicate.features.nfl.sgp.rho_for` whichever sport fitted it.

  1. PLAYER-GAMES from the ESPN player game logs (`<sport>_source/data/processed/player_game_log_<season>.csv`),
     REGULAR SEASON only (playoffs are a different population). A row with no minutes is dropped, as a book voids him.
     All-Star games are labelled regular there (USA / WNBASTARS, CLA / COL, COOP / SPO; CAN / CHK / KEN / SHQ,
     STARS / STRIPES / WORLD): a game with a team the repo's registry (`team_aliases.canonical_team`) cannot resolve is
     an exhibition and is dropped. Combos: PRA = PTS+REB+AST, PR, PA, RA.
  2. ROLE, tonight-style and leak-free: a player's average minutes over the games he played among the team's last 8
     EARLIER games; tonight's players ranked by it fill S1..S5 then B1..B3; the rest -- and anyone absent from the
     window -- are UNK. (The NHL `line_slot` rule with basketball slots; tonight's minutes never enter.)
  3. PROXY LEGS, one per (game, player, market), roles S1..B3 only, from the player's EARLIER games this season
     (>= 5): the prior median rounded to x.5 (an integer median goes up when the prior mean is above it, else down),
     floored at the book's 1st-percentile line for the market (PTS 4.5, PRA 9.5, ...). Every book line in the data is
     x.5, so there are no pushes. MARGINALS: role = the TRAIN seasons' over-rate per (market, role, line); player =
     his own prior over-rate shrunk to the role rate with SHRINK_K pseudo-games (the NHL study's two variants).
  4. REAL LEGS: pregame OddsAPI snapshots -- WNBA 2026 (`backfill/wnba_props_2026/odds/<espn game>.json`, ~14 min
     before the start) and NBA 2025-26 (`backfill/nba_props_2025_26/asof/props_odds_hist/<date>.csv`, ~49 min before;
     events matched to ESPN games by local date and home team). One leg per (game, player, market) at the line the
     most books quote two-way, fair P(over) = median de-vigged price (the NFL / NHL rule). A listed player who did not
     play is void (dropped). Names: the full accent-folded name first, then first initial + last name, each only when
     unique in the game (OKC carries a Jalen and a Jaylin Williams).
  5. PAIRS within a game: same_player / teammate / opponent; cell = (type_a, type_b, relation), types sorted, where a
     type is MARKET|ROLE -- the NFL schema `rho_for` reads. NESTED same-player pairs (one stat contains the other:
     PTS x PRA, PR x PRA, ...) are listed in `nested_same_player` and EXCLUDED from every fit and every test: the runtime
     never prices them, and their rho ~0.9 would both inflate the same-player gain and loosen the shrinkage prior.
  6. rho per cell (`fit_rho`, >= 300 pairs, game-clustered SE), shrunk per level x relation (`shrink_cells` -- KNOWN
     DEFECT, kept for consistency with NFL / NHL: tau^2 is the spread about the cells' MEAN but the shrinkage is toward
     0, so a relation whose cells share one non-zero level is over-shrunk; `shrink_second_moment` is reported beside it).
  7. OUT OF SAMPLE (four-cell log loss, copula vs independence on the SAME marginals, game-clustered SE):
       A. proxy cells fit on the earlier season(s), scored on the latest full regular season's proxy legs;
       B. those TRAIN-season proxy cells scored on the latest season's REAL lines at their de-vigged consensus;
       C. real-line cells fit on the latest season before --real-split, scored on it from --real-split.
     Each also with MARKET CELLS ONLY (an ablation: a role cell shrunk to exactly 0 hides its market cell from
     `rho_for`; `masking` counts those cells in every published file).
  8. FALSIFICATION, stated before the run: a relation whose out-of-sample gain is not below zero at |z| >= 2 is reported
     as "no measured correlation" and every one of its cells, role and market level, is set to rho 0 (the runtime then
     prices it as independent; `rho_fitted` keeps the value). The test that governs each published file is its own
     estimator's: A (published marginal, shrunk) for `<sport>_sgp_correlations_proxy.json`, C (shrunk) for
     `<sport>_sgp_correlations.json`, the real-line fit -- the file the runtime should read, as for NHL.
  9. ENGINE READ: residual correlations (actual - the player's prior mean) of minutes and the box-score stats by
     relation, all games and regulation-only; where books set lines against the median proxy and how they realise.

Run on the fleet at idle priority (it shares the host with production):
  nice -n 19 python scripts/build_basketball_sgp_correlations.py --sport wnba --data-root /home/amyn/syndicate-prod/data
"""
from __future__ import annotations

import argparse
import collections
import copy
import glob
import importlib.util
import json
import math
import re
import statistics
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.basketball_engine.orchestrator.player_names import normalize_player_name_key  # noqa: E402
from syndicate.features.nfl.sgp import name_key  # noqa: E402 -- the consumer's own name rule
from syndicate.features.shared.team_aliases import canonical_team  # noqa: E402


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The NHL study's module, which itself loads the NFL study's: one estimator instance for everything below.
_nhl = _load("build_nhl_sgp_correlations")
_nfl = _nhl._nfl
fit_rho = _nfl.fit_rho
shrink_cells = _nfl.shrink_cells
clustered_se = _nfl.clustered_se
four_cell = _nfl.four_cell
build_pairs = _nhl.build_pairs
concat_pairs = _nhl.concat_pairs
subset_pairs = _nhl.subset_pairs
fit_cells = _nhl.fit_cells
evaluate = _nhl.evaluate
shrink_second_moment = _nhl.shrink_second_moment
strip_cells = _nhl.strip_cells
role_rates = _nhl.role_rates
attach_marginals = _nhl.attach_marginals
consensus_legs = _nhl.consensus_legs
REL = _nhl.REL                       # ("same_player", "teammate", "opponent") -- the order `build_pairs` codes

BASE = ("PTS", "REB", "AST", "FG3M", "STL", "BLK")
COMBOS = {"PRA": ("PTS", "REB", "AST"), "PR": ("PTS", "REB"), "PA": ("PTS", "AST"), "RA": ("REB", "AST")}
MARKETS = BASE + tuple(COMBOS)
ODDS_KEYS = {"player_points": "PTS", "player_rebounds": "REB", "player_assists": "AST", "player_threes": "FG3M",
             "player_steals": "STL", "player_blocks": "BLK", "player_points_rebounds_assists": "PRA",
             "player_points_rebounds": "PR", "player_points_assists": "PA", "player_rebounds_assists": "RA"}
# The 1st-percentile book line per market (NBA 2025-26 and WNBA 2026 pregame snapshots, measured 2026-10-17).
LINE_FLOOR = {"PTS": 4.5, "REB": 1.5, "AST": 0.5, "FG3M": 0.5, "STL": 0.5, "BLK": 0.5, "PRA": 9.5, "PR": 7.5,
              "PA": 7.5, "RA": 3.5}
SLOTS = ("S1", "S2", "S3", "S4", "S5", "B1", "B2", "B3")
ROLE_WINDOW = 8
MIN_PRIOR = 5
MIN_CELL = 300
SHRINK_K = 20.0
Z_LINE = 2.0
_SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}

SPORTS: dict[str, dict[str, Any]] = {
    "wnba": {"seasons": {2024: "2024", 2025: "2025", 2026: "2026"}, "train": "2024,2025", "holdout": "2026",
             "real": "2026", "real_split": "2026-07-10",
             "real_source": ("snapshot_json", "backfill/wnba_props_2026/odds"),
             "regulation_minutes": 200},
    "nba": {"seasons": {2024: "2024-25", 2025: "2025-26"}, "train": "2024", "holdout": "2025",
            "real": "2025", "real_split": "2026-01-01",
            "real_source": ("oddsapi_csv", "backfill/nba_props_2025_26/asof/props_odds_hist"),
            "regulation_minutes": 240},
}


def _components(market: str) -> frozenset[str]:
    return frozenset(COMBOS.get(market, (market,)))


def _type_order(a: str, b: str) -> tuple[str, str]:
    """Two markets in the order `rho_for` keys them: by TYPE string ('PRA|S1' < 'PR|B1', since '|' sorts after 'A')."""
    return (a, b) if f"{a}|" <= f"{b}|" else (b, a)


# Same player, one stat contained in the other: one leg implies most of the other -- not a parlay. The runtime excludes
# them (`nhl.sgp.suggest` reads this list as frozensets); keys are in the market-cell order `rho_for` builds.
NESTED_SAME_PLAYER = tuple(sorted(
    "{}~{}~same_player".format(*_type_order(a, b))
    for i, a in enumerate(MARKETS) for b in MARKETS[i + 1:]
    if _components(a) < _components(b) or _components(b) < _components(a)))
NESTED_SETS = frozenset(frozenset(k.split("~")[:2]) for k in NESTED_SAME_PLAYER)


# ------------------------------------------------------------------------------------------------ box scores
def load_game_log(path: Path, sport: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Regular-season player-games who played, exhibitions dropped, combos added (see the docstring, step 1)."""
    raw = pd.read_csv(path)
    audit: dict[str, Any] = {"rows": int(len(raw)),
                             "season_type_rows": {str(k): int(v) for k, v in raw.season_type.value_counts().items()}}
    g = raw[raw.season_type.astype(str).str.lower() == "regular"].copy()
    teams = sorted(g.TEAM_ABBREVIATION.astype(str).unique())
    unknown = [t for t in teams if not canonical_team(sport, t)]
    exhibition = set(g.loc[g.TEAM_ABBREVIATION.astype(str).isin(unknown), "game_id"])
    audit["exhibition_teams"] = unknown
    audit["exhibition_games_dropped"] = len(exhibition)
    g = g[~g.game_id.isin(exhibition)]
    minutes = pd.to_numeric(g.MIN, errors="coerce").fillna(0.0)
    audit["rows_no_minutes_dropped"] = int((minutes <= 0).sum())
    g, minutes = g[minutes > 0], minutes[minutes > 0]
    pg = pd.DataFrame({"game_id": g.game_id.astype(np.int64).values, "start": g.date.astype(str).str[:10].values,
                       "team": g.TEAM_ABBREVIATION.astype(str).values, "opp": g.opponent.astype(str).values,
                       "home": (g.home_away.astype(str).str.lower() == "home").values,
                       "pid": g.PLAYER_ID.astype(np.int64).values, "name": g.PLAYER_NAME.astype(str).values,
                       "starter": pd.to_numeric(g.starter, errors="coerce").fillna(0).astype(int).values,
                       "MIN": minutes.astype(float).values})
    for s in BASE:
        pg[s] = pd.to_numeric(g[s], errors="coerce").fillna(0.0).astype(float).values
    for c, parts in COMBOS.items():
        pg[c] = pg[list(parts)].sum(axis=1)
    pg = pg.sort_values(["start", "game_id", "team", "pid"]).reset_index(drop=True)
    audit["games"] = int(pg.game_id.nunique())
    audit["player_games"] = int(len(pg))
    audit["dates"] = [str(pg.start.min()), str(pg.start.max())] if len(pg) else []
    return pg, audit


# ------------------------------------------------------------------------------------------------ roles
def rotation_roles(pg: pd.DataFrame, window: int = ROLE_WINDOW) -> dict[tuple[int, int], str]:
    """(game_id, pid) -> S1..S5 / B1..B3 / UNK from the team's EARLIER games only (docstring, step 2). Tonight's
    players are RANKED (actives are known before tip); tonight's minutes never are."""
    out: dict[tuple[int, int], str] = {}
    for _team, g in pg.groupby("team", sort=False):
        order = g[["game_id", "start"]].drop_duplicates().sort_values(["start", "game_id"]).game_id.tolist()
        by_game = {gid: rows for gid, rows in g.groupby("game_id")}
        past: collections.deque = collections.deque(maxlen=window)
        for gid in order:
            tot: dict[int, float] = collections.defaultdict(float)
            cnt: dict[int, int] = collections.defaultdict(int)
            for game in past:
                for pid, mins in game.items():
                    tot[pid] += mins
                    cnt[pid] += 1
            avg = {pid: tot[pid] / cnt[pid] for pid in tot}
            rows = by_game[gid]
            ranked = sorted((p for p in rows.pid if p in avg), key=lambda p: (-avg[p], p))
            for i, pid in enumerate(ranked):
                out[(gid, pid)] = SLOTS[i] if i < len(SLOTS) else "UNK"
            for pid in rows.pid:
                out.setdefault((gid, pid), "UNK")
            past.append(dict(zip(rows.pid, rows.MIN)))
    return out


# ------------------------------------------------------------------------------------------------ proxy legs
def proxy_line(past: list[float], market: str) -> float:
    """A book-like line from a player's EARLIER games: the median rounded to x.5 (an integer median goes up when the
    mean is above it, else down), floored at the market's 1st-percentile book line."""
    med = float(statistics.median(past))
    if med != math.floor(med):
        line = med
    else:
        line = med + 0.5 if float(np.mean(past)) > med else med - 0.5
    return max(line, LINE_FLOOR[market])


def season_history(pg: pd.DataFrame) -> pd.DataFrame:
    """Per player-game, from his EARLIER games this season only: games, and per market the proxy line, how often he
    cleared it and his mean (plus his mean minutes). The current game is appended AFTER the read."""
    hist: dict[int, dict[str, list[float]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    cols = {m: pg[m].to_numpy(float) for m in MARKETS + ("MIN",)}
    recs = []
    for i, (gid, pid) in enumerate(zip(pg.game_id.to_numpy(), pg.pid.to_numpy())):
        h = hist[pid]
        n = len(h["MIN"])
        rec: dict[str, Any] = {"game_id": gid, "pid": pid, "prior_n": n}
        if n >= MIN_PRIOR:
            for m in MARKETS:
                past = h[m]
                line = proxy_line(past, m)
                rec[f"line_{m}"] = line
                rec[f"overs_{m}"] = int(sum(v > line for v in past))
                rec[f"mean_{m}"] = float(np.mean(past))
            rec["mean_MIN"] = float(np.mean(h["MIN"]))
        for m in cols:
            h[m].append(float(cols[m][i]))
        recs.append(rec)
    return pd.DataFrame(recs)


def proxy_legs(pg: pd.DataFrame, history: pd.DataFrame, roles: Mapping[tuple[int, int], str],
               season: int) -> pd.DataFrame:
    """One leg per (game, rotation player, market) at the proxy line; over = stat > line (x.5, so no push)."""
    d = pg.merge(history, on=["game_id", "pid"], how="left")
    d["role"] = [roles.get((g, p), "UNK") for g, p in zip(d.game_id, d.pid)]
    d = d[(d.prior_n >= MIN_PRIOR) & d.role.isin(SLOTS)]
    rows = []
    for m in MARKETS:
        if f"line_{m}" not in d:
            continue
        sub = d[d[f"line_{m}"].notna()]
        rows.append(pd.DataFrame({
            "game_id": sub.game_id.values, "start": sub.start.values, "team": sub.team.values, "pid": sub.pid.values,
            "role": sub.role.values, "market": m, "line": sub[f"line_{m}"].values, "actual": sub[m].values,
            "prior_n": sub.prior_n.values, "prior_overs": sub[f"overs_{m}"].values}))
    cols = ["game_id", "start", "team", "pid", "role", "market", "line", "actual", "prior_n", "prior_overs"]
    legs = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=cols)
    legs["over"] = (legs.actual > legs.line).astype(np.int8)
    legs["type"] = legs.market + "|" + legs.role
    legs["season"] = season
    return legs.reset_index(drop=True)


# ------------------------------------------------------------------------------------------------ names
def _fold(name: Any) -> str:
    return unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")


def full_key(name: Any) -> str | None:
    """The whole name through the basketball engine's registered normalizer (accents folded, suffixes dropped, its
    alias table: the books' 'Carlton Carrington' is ESPN's 'Bub Carrington'), compacted: 'P.J. Washington Jr.' =
    'pjwashington'."""
    key = re.sub(r"[^a-z]", "", normalize_player_name_key(name, case="lower"))
    return key or None


def short_key(name: Any) -> tuple[str, str] | None:
    """`name_key` (first initial + last name, the NFL / NHL rule) after folding accents."""
    return name_key(_fold(name))


def hyphen_key(name: Any) -> tuple[str, str] | None:
    """First initial + the FIRST part of a hyphenated last name: the books' 'Skylar Diggins-Smith' is ESPN's 'Skylar
    Diggins' (measured 2026-10-17: 137 WNBA 2026 legs lost without it)."""
    parts = [p for p in re.split(r"[\s.]+", _fold(name).lower().replace("'", "")) if p and p not in _SUFFIX]
    if len(parts) < 2:
        return None
    last = re.sub(r"[^a-z]", "", parts[-1].split("-")[0])
    return (parts[0][0], last) if last else None


_NAME_KEYS = (("full", full_key), ("short", short_key), ("hyphen", hyphen_key))


def name_index(pids: Iterable[int], names: Iterable[Any]) -> dict[str, dict[Any, set]]:
    idx: dict[str, dict[Any, set]] = {kind: collections.defaultdict(set) for kind, _ in _NAME_KEYS}
    for pid, name in zip(pids, names):
        for kind, fn in _NAME_KEYS:
            k = fn(name)
            if k:
                idx[kind][k].add(pid)
    return idx


def match_name(idx: Mapping[str, Mapping[Any, set]], name: Any) -> tuple[Any, str]:
    """(pid, how): the full name when it names exactly one player, else first initial + last name when THAT does, else
    first initial + the first part of a hyphenated last name. A key naming two players stops the search: a looser key
    never breaks a tie a stricter one could not."""
    for kind, fn in _NAME_KEYS:
        key = fn(name)
        hit = idx[kind].get(key, set()) if key else set()
        if len(hit) == 1:
            return next(iter(hit)), kind
        if len(hit) > 1:
            return None, "ambiguous"
    return None, "unmatched"


def match_leg(game_idx: Mapping[str, Mapping[Any, set]], season_idx: Mapping[str, Mapping[Any, set]], name: Any,
              game_pids: set) -> tuple[Any, str]:
    """`match_name` within the game, except that a looser key never lands on a namesake: when the book's FULL name
    names one season player who did not play tonight, the leg is his and void (OKC: Jalen Williams out, Jaylin
    Williams in -- both 'J. Williams')."""
    pid, how = match_name(game_idx, name)
    if pid is not None and how != "full":
        named = season_idx["full"].get(full_key(name) or "", set())
        if len(named) == 1 and next(iter(named)) not in game_pids:
            return None, "void_namesake"
    return pid, how


# ------------------------------------------------------------------------------------------------ real book lines
Quotes = dict  # (market, player, line) -> book -> {"over": price, "under": price}


def snapshot_quotes(snap: Mapping[str, Any]) -> Quotes:
    """One OddsAPI event snapshot -> quotes, basketball markets only."""
    quotes: Quotes = collections.defaultdict(lambda: collections.defaultdict(dict))
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


def snapshot_json_quotes(odds_dir: Path) -> tuple[dict[int, Quotes], dict[str, Any]]:
    """WNBA: one file per ESPN game id, `{"game", "snap": {"timestamp", "data": <event>}}`; pregame snapshots only."""
    audit: collections.Counter = collections.Counter()
    out: dict[int, Quotes] = {}
    for path in sorted(glob.glob(str(odds_dir / "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            audit["file_unreadable"] += 1
            continue
        snap = doc.get("snap") or {}
        data = snap.get("data") or {}
        if not _pregame(snap.get("timestamp"), data.get("commence_time")):
            audit["snapshot_not_pregame"] += 1
            continue
        audit["games_with_pregame_snapshot"] += 1
        out[int(doc.get("game") or Path(path).stem)] = snapshot_quotes(data)
    return out, dict(audit)


def _pregame(ts: Any, commence: Any) -> bool:
    try:
        return pd.Timestamp(str(ts)) < pd.Timestamp(str(commence))
    except (ValueError, TypeError):
        return False


def oddsapi_csv_quotes(hist_dir: Path, pg: pd.DataFrame, sport: str) -> tuple[dict[int, Quotes], dict[str, Any]]:
    """NBA: per-date CSVs of OddsAPI historical snapshots. The latest PREGAME snapshot per event, matched to its ESPN
    game (`match_events`); rows of a post-start snapshot are dropped."""
    audit: collections.Counter = collections.Counter()
    best: dict[str, tuple[pd.Timestamp, Quotes]] = {}
    meta: dict[str, tuple[str, str, str]] = {}
    cols = ["snapshot_ts", "event_id", "commence_time", "bookmaker", "market", "outcome_name", "player_name", "point",
            "price", "home_team", "away_team"]
    for path in sorted(glob.glob(str(hist_dir / "*.csv"))):
        try:
            df = pd.read_csv(path, usecols=cols)
        except (OSError, ValueError):
            audit["file_unreadable"] += 1
            continue
        audit["rows"] += len(df)
        df = df[df.market.isin(list(ODDS_KEYS)) & df.point.notna() & df.price.notna()]
        ts = pd.to_datetime(df.snapshot_ts, utc=True, format="ISO8601")
        ct = pd.to_datetime(df.commence_time, utc=True, format="ISO8601")
        late = ts >= ct
        audit["rows_not_pregame"] += int(late.sum())
        df = df[~late].assign(_ts=ts[~late])
        for eid, ev in df.groupby("event_id"):
            last = ev._ts.max()
            if eid in best and best[eid][0] >= last:
                continue
            ev = ev[ev._ts == last]
            quotes: Quotes = collections.defaultdict(lambda: collections.defaultdict(dict))
            for r in ev.itertuples(index=False):
                side = str(r.outcome_name).lower()
                if side in ("over", "under"):
                    quotes[(ODDS_KEYS[r.market], str(r.player_name), float(r.point))][r.bookmaker][side] = float(r.price)
            best[eid] = (last, quotes)
            meta[eid] = (str(ev.home_team.iloc[0]), str(ev.away_team.iloc[0]), str(ev.commence_time.iloc[0]))
    games, how = match_events(meta, pg, sport)
    audit.update(how)
    out: dict[int, Quotes] = {}
    for eid, gid in games.items():
        if gid is not None:
            out[gid] = best[eid][1]
    audit["events_pregame"] = len(best)
    return out, dict(audit)


def local_day(commence: Any) -> str:
    """An OddsAPI commence time (UTC) -> the US local date ESPN files the game under (UTC - 6h: a 10:30 PM ET tip is
    02:30Z the next day; the NFL study's rule)."""
    return (pd.Timestamp(str(commence)).tz_convert("UTC") - pd.Timedelta(hours=6)).strftime("%Y-%m-%d")


def match_events(meta: Mapping[str, tuple[str, str, str]], pg: pd.DataFrame,
                 sport: str) -> tuple[dict[str, int | None], dict[str, int]]:
    """event_id -> ESPN game_id by (home team, local date) through `canonical_team`; a neutral-site game whose home and
    away are swapped matches on the other team; then the adjacent dates."""
    by_team_day: dict[tuple[str, str], set] = collections.defaultdict(set)
    for gid, team, day in pg[["game_id", "team", "start"]].drop_duplicates().itertuples(index=False):
        by_team_day[(canonical_team(sport, team), day)].add(int(gid))
    how: collections.Counter = collections.Counter()
    out: dict[str, int | None] = {}
    for eid, (home, away, commence) in meta.items():
        day = local_day(commence)
        h, a = canonical_team(sport, home), canonical_team(sport, away)
        hit = None
        for label, d in (("same_day", day), ("adjacent_day", _shift(day, -1)), ("adjacent_day", _shift(day, 1))):
            both = by_team_day.get((h, d), set()) & by_team_day.get((a, d), set())
            if len(both) == 1:
                hit = next(iter(both))
                how[f"events_matched_{label}"] += 1
                break
        if hit is None:
            how["events_unmatched"] += 1
        out[eid] = hit
    return out, dict(how)


def _shift(day: str, days: int) -> str:
    return (pd.Timestamp(day) + pd.Timedelta(days=days)).strftime("%Y-%m-%d")


def book_legs(quotes_by_game: Mapping[int, Quotes], pg: pd.DataFrame, roles: Mapping[tuple[int, int], str],
              season: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Real pregame consensus legs for the season's regular-season games; a listed player who did not play is void."""
    audit: collections.Counter = collections.Counter()
    played = {gid: g for gid, g in pg.groupby("game_id")}
    season_idx = name_index(pg.pid, pg.name)
    rows = []
    for gid, quotes in sorted(quotes_by_game.items()):
        g = played.get(gid)
        if g is None:
            audit["games_not_regular_season_or_no_boxscore"] += 1
            continue
        idx = name_index(g.pid, g.name)
        by_pid = {r.pid: r for r in g.itertuples(index=False)}
        for leg in consensus_legs(quotes):
            audit["legs_quoted"] += 1
            pid, how = match_leg(idx, season_idx, leg["player"], set(by_pid))
            if pid is None:
                if how == "void_namesake":
                    audit["legs_void_did_not_play_namesake_played"] += 1
                elif how == "ambiguous":
                    audit["legs_ambiguous_name"] += 1
                elif match_name(season_idx, leg["player"])[0] is not None:
                    audit["legs_void_did_not_play"] += 1
                else:
                    audit["legs_unmatched_name"] += 1
                continue
            audit[f"legs_matched_{how}_name"] += 1
            r = by_pid[pid]
            actual = float(getattr(r, leg["market"]))
            if actual == leg["line"]:
                audit["legs_push"] += 1
                continue
            rows.append(dict(leg, game_id=gid, start=r.start, team=r.team, pid=pid, role=roles.get((gid, pid), "UNK"),
                             actual=actual, over=int(actual > leg["line"]), season=season))
    cols = ["market", "player", "line", "n_books", "fair", "q_over", "q_under", "game_id", "start", "team", "pid",
            "role", "actual", "over", "season"]
    legs = pd.DataFrame(rows, columns=cols)
    before = len(legs)
    legs = legs.sort_values("n_books", ascending=False).drop_duplicates(["game_id", "pid", "market"])
    audit["legs_duplicate_spelling_dropped"] = before - len(legs)
    legs["type"] = legs.market + "|" + legs.role
    legs["p_fair"] = legs.fair.astype(float).clip(0.02, 0.98)
    audit["legs_graded"] = int(len(legs))
    audit["games_graded"] = int(legs.game_id.nunique())
    audit["legs_by_role"] = {k: int(v) for k, v in legs.role.value_counts().items()}
    audit["legs_by_market"] = {k: int(v) for k, v in legs.market.value_counts().items()}
    return legs.sort_values(["game_id", "pid", "market"]).reset_index(drop=True), dict(audit)


# ------------------------------------------------------------------------------------------------ pairs, cells, verdicts
def nested_mask(pairs: Mapping[str, Any]) -> np.ndarray:
    """Same-player pairs whose two markets nest (PTS x PRA, ...)."""
    names = pairs["markets"]
    codes = [i * len(names) + j for i, a in enumerate(names) for j, b in enumerate(names)
             if frozenset((a, b)) in NESTED_SETS]
    key = pairs["ma"].astype(np.int64) * len(names) + pairs["mb"]
    return (pairs["rel"] == 0) & np.isin(key, codes)


def split_nested(pairs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    mask = nested_mask(pairs)
    return subset_pairs(pairs, ~mask), subset_pairs(pairs, mask)


def falsify(cells: dict[str, dict[str, dict[str, float]]], oos: Mapping[str, Any], test: str,
            z_line: float = Z_LINE) -> dict[str, Any]:
    """The pre-stated line (docstring, step 8): a relation is MEASURED only when its out-of-sample gain is below zero
    at |z| >= z_line; otherwise every cell of it, both levels, is set to rho 0 and `rho_fitted` keeps the fit."""
    verdict: dict[str, Any] = {"test": test, "z_line": z_line}
    for rel in REL:
        row = oos.get(f"relation={rel}") or {}
        diff, z = row.get("diff"), row.get("z")
        measured = diff is not None and z is not None and diff < 0 and abs(z) >= z_line
        zeroed = 0
        if not measured:
            for group in cells.values():
                for key, cell in group.items():
                    if key.rsplit("~", 1)[1] == rel:
                        cell["rho_fitted"] = cell["rho"]
                        cell["rho"] = 0.0
                        cell["falsified"] = True
                        zeroed += 1
        verdict[rel] = {"verdict": "measured" if measured else "no measured correlation", "diff": diff, "z": z,
                        "pairs": row.get("pairs"), "cells_zeroed": zeroed}
    return verdict


def market_only(cells: Mapping[str, Any]) -> dict[str, Any]:
    """The ablation: no role cells, so every pair reaches its market cell through `rho_for`."""
    return {"type": {}, "market": dict(cells.get("market") or {})}


def masking(cells: Mapping[str, Any]) -> dict[str, Any]:
    """Role cells that `shrink_cells` took to exactly 0 while their market cell is not 0. `rho_for` returns the role cell
    first, so each of them prices its pairs as independent and HIDES the market cell (the NHL findings' follow-up 2).
    Falsified cells are not counted -- there the whole relation is 0 by design."""
    out: dict[str, Any] = {}
    market = cells.get("market") or {}
    for rel in REL:
        role = [(k, c) for k, c in (cells.get("type") or {}).items() if k.endswith("~" + rel) and not c.get("falsified")]
        masked = []
        for key, c in role:
            ta, tb, _ = key.split("~")
            m = market.get(f"{ta.split('|')[0]}~{tb.split('|')[0]}~{rel}")
            if c["rho"] == 0 and m is not None and m["rho"] != 0:
                masked.append((c, m))
        out[rel] = {"role_cells": len(role), "role_cell_pairs": int(sum(c["n"] for _, c in role)),
                    "masked_cells": len(masked), "masked_pairs": int(sum(c["n"] for c, _ in masked)),
                    "masked_market_rho_mean_abs": round(float(np.mean([abs(m["rho"]) for _, m in masked])), 4)
                    if masked else None}
    return out


def strongest(cells: Mapping[str, Any], level: str, k: int = 12) -> dict[str, list]:
    """Top cells by |rho| per relation (published values), for the findings."""
    out: dict[str, list] = {}
    for rel in REL:
        group = [(key, c) for key, c in (cells.get(level) or {}).items() if key.endswith("~" + rel)]
        group.sort(key=lambda kc: -abs(kc[1]["rho"]))
        out[rel] = [{"cell": key, "rho": c["rho"], "rho_raw": c.get("rho_raw"), "se": c.get("se"), "n": c.get("n")}
                    for key, c in group[:k]]
    return out


# ------------------------------------------------------------------------------------------------ engine read
ENGINE_STATS = ("MIN",) + BASE


def residual_read(pg: pd.DataFrame, history: pd.DataFrame, roles: Mapping[tuple[int, int], str],
                  regulation_minutes: int) -> dict[str, Any]:
    """Pearson correlation of (actual - the player's prior mean) between legs in a game, per stat pair x relation,
    rotation players (S1..B3) with >= MIN_PRIOR earlier games; all games, and games with no overtime (team minutes
    at most regulation + 5)."""
    d = pg.merge(history, on=["game_id", "pid"], how="inner")
    d["role"] = [roles.get((g, p), "UNK") for g, p in zip(d.game_id, d.pid)]
    d = d[(d.prior_n >= MIN_PRIOR) & d.role.isin(SLOTS)]
    team_min = pg.groupby(["game_id", "team"]).MIN.sum().groupby("game_id").max()
    ot_games = set(team_min[team_min > regulation_minutes + 5].index)
    rows = []
    for s in ENGINE_STATS:
        rows.append(pd.DataFrame({"game_id": d.game_id.values, "team": d.team.values, "pid": d.pid.values,
                                  "market": s, "role": d.role.values, "resid": (d[s] - d[f"mean_{s}"]).values,
                                  "over": 0}))
    legs = pd.concat(rows, ignore_index=True)
    legs["type"] = legs.market + "|" + legs.role
    out: dict[str, Any] = {"games": int(legs.game_id.nunique()), "overtime_games": int(len(ot_games & set(legs.game_id))),
                           "overtime_share": round(len(ot_games & set(legs.game_id)) / max(legs.game_id.nunique(), 1), 4)}
    for label, frame in (("all_games", legs), ("regulation_only", legs[~legs.game_id.isin(ot_games)])):
        pairs = build_pairs(frame, ("resid",))
        order, uniq, start, count, names = _nhl._groups(pairs, "market")
        cells = {}
        for k, s, c in zip(uniq, start, count):
            idx = order[s:s + c]
            a, b = pairs["resid_a"][idx].astype(np.float64), pairs["resid_b"][idx].astype(np.float64)
            if c < 200 or a.std() == 0 or b.std() == 0:
                continue
            cells[_nhl._cell_name(k, names)] = {"r": round(float(np.corrcoef(a, b)[0, 1]), 4), "pairs": int(c)}
        out[label] = cells
        del pairs
    return out


def line_read(real: pd.DataFrame, history: pd.DataFrame, pg: pd.DataFrame) -> dict[str, Any]:
    """Real book lines against the proxy rule run on the same player's earlier games, and how each realised."""
    h = history.merge(pg[["game_id", "pid"] + list(MARKETS)], on=["game_id", "pid"])
    out = {}
    for m in MARKETS:
        b = real[real.market == m]
        if b.empty:
            continue
        j = b.merge(h[["game_id", "pid", f"line_{m}", f"mean_{m}"]], on=["game_id", "pid"], how="left")
        j = j[j[f"line_{m}"].notna()]
        diff = j.line - j[f"line_{m}"]
        hp = h[h[f"line_{m}"].notna()]
        p = float(b.over.mean())
        out[m] = {"book_legs": int(len(b)), "book_fair_over_mean": round(float(b.fair.mean()), 4),
                  "book_line_over_realised": round(p, 4),
                  "book_line_over_se_game_clustered": round(clustered_se(b.over.to_numpy(float), b.game_id.to_numpy()), 4),
                  "matched_to_proxy": int(len(j)),
                  "proxy_equals_book": round(float((diff == 0).mean()), 4) if len(j) else None,
                  "book_minus_proxy_mean": round(float(diff.mean()), 3) if len(j) else None,
                  "book_minus_prior_mean": round(float((j.line - j[f"mean_{m}"]).mean()), 3) if len(j) else None,
                  "proxy_line_over_realised_all_players": round(float((hp[m] > hp[f"line_{m}"]).mean()), 4)}
    return out


# ------------------------------------------------------------------------------------------------ driver
def _z(table: Mapping[str, Any]) -> dict[str, Any]:
    return {k: (v.get("diff"), v.get("z")) for k, v in table.items() if k.startswith("relation=")}


def _rss_mb() -> float | None:
    try:
        import resource

        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)   # Linux: KiB
    except ImportError:
        return None


def season_frame(data_root: Path, sport: str, season: int, limit_games: int = 0) -> dict[str, Any]:
    path = data_root / f"{sport}_source" / "data" / "processed" / f"player_game_log_{season}.csv"
    pg, audit = load_game_log(path, sport)
    if limit_games:
        keep = pg.drop_duplicates("game_id").game_id.head(limit_games)
        pg = pg[pg.game_id.isin(keep)].reset_index(drop=True)
    history = season_history(pg)
    roles = rotation_roles(pg)
    legs = proxy_legs(pg, history, roles, season)
    s_roles = [roles.get((g, p)) for g, p in zip(pg.game_id, pg.pid)]
    started = pg.starter.to_numpy()
    in_s = np.array([r in SLOTS[:5] for r in s_roles])
    audit.update({"season": season, "legs": int(len(legs)), "games_with_legs": int(legs.game_id.nunique()),
                  "legs_by_market": {k: int(v) for k, v in legs.market.value_counts().items()},
                  "legs_by_role": {k: int(v) for k, v in legs.role.value_counts().items()},
                  "s_role_started_share": round(float(started[in_s].mean()), 4) if in_s.any() else None,
                  "starters_with_s_role_share": round(float(in_s[started == 1].mean()), 4) if (started == 1).any() else None,
                  "team_games_not_5_starters": int((pg.groupby(["game_id", "team"]).starter.sum() != 5).sum())})
    return {"pg": pg, "history": history, "roles": roles, "legs": legs, "audit": audit}


def real_quotes(data_root: Path, sport: str, pg: pd.DataFrame) -> tuple[dict[int, Quotes], dict[str, Any]]:
    kind, rel = SPORTS[sport]["real_source"]
    if kind == "snapshot_json":
        return snapshot_json_quotes(data_root / rel)
    return oddsapi_csv_quotes(data_root / rel, pg, sport)


def payload(sport: str, kind: str, cells: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    return {"schema": f"{sport}_sgp_correlations_v1", "sport": sport, "kind": kind,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "season_type": "REG",
            "roles": "S1-S5 / B1-B3 = tonight's players ranked by average minutes over the team's last 8 EARLIER games "
                     "(games each played); UNK = beyond the top 8 or no game in the window",
            "markets": list(MARKETS), "min_cell_pairs": MIN_CELL, "nested_same_player": list(NESTED_SAME_PLAYER),
            **extra, "cells": strip_cells(cells)}


def main(argv: list[str] | None = None) -> int:
    t0 = time.time()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sport", required=True, choices=sorted(SPORTS))
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--train", default=None)
    ap.add_argument("--holdout", default=None)
    ap.add_argument("--real", default=None, help="season with real pregame book lines ('' to skip)")
    ap.add_argument("--real-split", default=None)
    ap.add_argument("--marginal", default="player", choices=("player", "role"),
                    help="the marginal the published proxy cells are fitted with (both are evaluated)")
    ap.add_argument("--limit-games", type=int, default=0, help="smoke runs: the first N games of each season")
    ap.add_argument("--out", type=Path, default=None, help="default /tmp/basketball_sgp/<sport>")
    args = ap.parse_args(argv)
    cfg = SPORTS[args.sport]
    out_dir = args.out or Path("/tmp/basketball_sgp") / args.sport
    out_dir.mkdir(parents=True, exist_ok=True)
    seasons = lambda s, d: [int(x) for x in (d if s is None else s).split(",") if x]  # noqa: E731
    train, hold = seasons(args.train, cfg["train"]), seasons(args.holdout, cfg["holdout"])
    real_seasons = seasons(args.real, cfg["real"])
    split = args.real_split or cfg["real_split"]
    pcols = ("p_role", "p_player")
    pub = f"p_{args.marginal}"

    frames: dict[int, dict[str, Any]] = {}
    for season in sorted(set(train + hold + real_seasons)):
        frames[season] = season_frame(args.data_root, args.sport, season, args.limit_games)
        print("SEASON", json.dumps(frames[season]["audit"]), flush=True)
    rates = role_rates(pd.concat([frames[s]["legs"] for s in train], ignore_index=True))
    for s in frames:
        frames[s]["legs"] = attach_marginals(frames[s]["legs"], rates)
    calib = {str(s): _nhl._calibration(frames[s]["legs"], pcols) for s in frames}

    # A. proxy cells fit on the train seasons, scored on the holdout season's proxy legs.
    train_pairs, train_nested = split_nested(concat_pairs([build_pairs(frames[s]["legs"], pcols) for s in train]))
    hold_pairs, hold_nested = split_nested(concat_pairs([build_pairs(frames[s]["legs"], pcols) for s in hold]))
    print("PAIRS train", len(train_pairs["game"]), "holdout", len(hold_pairs["game"]), "nested excluded",
          len(train_nested["game"]) + len(hold_nested["game"]), "rss_mb", _rss_mb(), flush=True)
    oos_a: dict[str, Any] = {}
    cells_a: dict[str, Any] = {}
    for pc in pcols:
        cells = fit_cells(train_pairs, pc)
        raw = evaluate(hold_pairs, cells, pc)
        alt = copy.deepcopy(cells)
        alt_priors = shrink_second_moment(alt)
        priors = shrink_cells(cells)
        shrunk = evaluate(hold_pairs, cells, pc, by_cell=True)
        second = evaluate(hold_pairs, alt, pc)
        mkt = evaluate(hold_pairs, market_only(cells), pc)
        cells_a[pc] = cells
        oos_a[pc] = {"logloss_raw": raw, "logloss": shrunk, "logloss_second_moment_shrink": second,
                     "logloss_market_cells_only": mkt, "shrinkage": priors, "second_moment_priors": alt_priors,
                     "cells_fitted": {lvl: len(g) for lvl, g in cells.items()}, "masking": masking(cells)}
        print("OOS_A", pc, "raw", json.dumps(_z(raw)), "shrunk", json.dumps(_z(shrunk)), "second_moment",
              json.dumps(_z(second)), "market_only", json.dumps(_z(mkt)), "rss_mb", _rss_mb(), flush=True)
    nested_cells = strip_cells(fit_cells(concat_pairs([train_nested, hold_nested]), pub))
    del train_nested, hold_nested

    # The published proxy cells: refit on every box-score season, shrunk, then the pre-stated falsification from A.
    all_pairs = concat_pairs([train_pairs, hold_pairs])
    del train_pairs, hold_pairs
    proxy_cells = fit_cells(all_pairs, pub)
    proxy_priors = shrink_cells(proxy_cells)
    del all_pairs
    proxy_verdict = falsify(proxy_cells, oos_a[pub]["logloss"], f"A: proxy {train} -> {hold}, {pub}, shrunk")
    print("VERDICT proxy", json.dumps({r: proxy_verdict[r]["verdict"] for r in REL}), flush=True)

    oos_b: dict[str, Any] = {}
    oos_c: dict[str, Any] = {}
    engine: dict[str, Any] = {}
    real_audit: dict[str, Any] = {}
    for season in real_seasons:
        f = frames[season]
        quotes, q_audit = real_quotes(args.data_root, args.sport, f["pg"])
        real, real_audit = book_legs(quotes, f["pg"], f["roles"], season)
        real_audit = {**q_audit, **real_audit}
        print("REAL", json.dumps(real_audit), flush=True)
        if real.empty:
            continue
        rp, rp_nested = split_nested(build_pairs(real, ("p_fair",)))
        late = np.isin(rp["game"], real.loc[real.start >= split, "game_id"].unique())
        print("REAL_PAIRS", len(rp["game"]), "from", split, int(late.sum()), "nested excluded", len(rp_nested["game"]),
              flush=True)
        rp_late, rp_early = subset_pairs(rp, late), subset_pairs(rp, ~late)
        # B. the TRAIN-season proxy cells (never fit on this season) on real lines at the de-vigged consensus.
        for pc in pcols:
            oos_b[pc] = {"all": evaluate(rp, cells_a[pc], "p_fair", by_cell=True),
                         "from_" + split: evaluate(rp_late, cells_a[pc], "p_fair"),
                         "all_market_cells_only": evaluate(rp, market_only(cells_a[pc]), "p_fair")}
            print("OOS_B", pc, json.dumps(_z(oos_b[pc]["all"])), "market_only",
                  json.dumps(_z(oos_b[pc]["all_market_cells_only"])), flush=True)
        # C. real-line cells fit before the split, scored after it.
        c_early = fit_cells(rp_early, "p_fair")
        raw = evaluate(rp_late, c_early, "p_fair")
        alt = copy.deepcopy(c_early)
        shrink_second_moment(alt)
        c_priors = shrink_cells(c_early)
        oos_c = {"train": f"{season} regular season before {split}", "holdout": f"from {split}",
                 "pairs_train": int(len(rp_early["game"])), "pairs_holdout": int(len(rp_late["game"])),
                 "logloss_raw": raw, "logloss": evaluate(rp_late, c_early, "p_fair", by_cell=True),
                 "logloss_second_moment_shrink": evaluate(rp_late, alt, "p_fair"),
                 "logloss_market_cells_only": evaluate(rp_late, market_only(c_early), "p_fair"), "shrinkage": c_priors,
                 "cells_fitted": {lvl: len(g) for lvl, g in c_early.items()}, "masking": masking(c_early)}
        print("OOS_C", json.dumps(_z(oos_c["logloss"])), "raw", json.dumps(_z(raw)), "second_moment",
              json.dumps(_z(oos_c["logloss_second_moment_shrink"])), "market_only",
              json.dumps(_z(oos_c["logloss_market_cells_only"])), flush=True)
        real_cells = fit_cells(rp, "p_fair")
        real_priors = shrink_cells(real_cells)
        real_verdict = falsify(real_cells, oos_c["logloss"], f"C: real lines before {split} -> from {split}, shrunk")
        print("VERDICT real", json.dumps({r: real_verdict[r]["verdict"] for r in REL}), flush=True)
        real_nested = strip_cells(fit_cells(rp_nested, "p_fair"))
        engine["lines"] = line_read(real, f["history"], f["pg"])
        real_calib = _nhl._calibration(real, ("p_fair",))
        doc = payload(args.sport, "real_lines", real_cells, seasons=[season],
                      source=f"real pregame consensus lines ({SPORTS[args.sport]['real_source'][1]})",
                      method="gaussian copula on (over_a, over_b); rho from the concordance moment at real de-vigged "
                             "consensus lines with within-cell marginal recalibration; game-clustered SE "
                             "(build_nfl_sgp_correlations.fit_rho / shrink_cells -- shrinks toward 0, see the NHL "
                             "findings' follow-up 1)",
                      audit=real_audit, marginal_calibration=real_calib, shrinkage=real_priors,
                      falsification=real_verdict, role_cells_masking_market=masking(real_cells),
                      out_of_sample={"C_real_line_cells": oos_c, "B_train_proxy_cells_on_real_lines": oos_b},
                      strongest={"type": strongest(real_cells, "type"), "market": strongest(real_cells, "market")},
                      nested_cells_diagnostic=real_nested)
        (out_dir / f"{args.sport}_sgp_correlations.json").write_text(json.dumps(doc, indent=1, default=str),
                                                                      encoding="utf-8")
        print("WROTE", out_dir / f"{args.sport}_sgp_correlations.json", "cells type", len(real_cells["type"]),
              "market", len(real_cells["market"]), flush=True)
        del rp, rp_late, rp_early, rp_nested

    h = frames[hold[-1]]
    engine["residuals"] = residual_read(h["pg"], h["history"], h["roles"], SPORTS[args.sport]["regulation_minutes"])
    engine["residuals_season"] = hold[-1]
    doc = payload(args.sport, "proxy", proxy_cells, seasons=train + hold,
                  method="gaussian copula on (over_a, over_b) at PROXY lines (player's prior median -> x.5); rho from "
                         "the concordance moment with within-cell marginal recalibration; game-clustered SE "
                         "(build_nfl_sgp_correlations.fit_rho / shrink_cells -- shrinks toward 0)",
                  marginal=args.marginal, min_prior_games=MIN_PRIOR, shrink_k=SHRINK_K, line_floor=LINE_FLOOR,
                  audit={"seasons": [frames[s]["audit"] for s in sorted(frames)], "real_lines": real_audit},
                  marginal_calibration=calib, shrinkage=proxy_priors, falsification=proxy_verdict,
                  role_cells_masking_market=masking(proxy_cells),
                  out_of_sample={"A_proxy": {"train": train, "holdout": hold, **oos_a},
                                 "B_train_proxy_cells_on_real_lines": oos_b, "C_real_line_cells": oos_c},
                  strongest={"type": strongest(proxy_cells, "type"), "market": strongest(proxy_cells, "market")},
                  nested_cells_diagnostic=nested_cells, engine_read=engine,
                  run={"seconds": round(time.time() - t0, 1), "peak_rss_mb": _rss_mb()})
    path = out_dir / f"{args.sport}_sgp_correlations_proxy.json"
    path.write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    print("WROTE", path, "cells type", len(proxy_cells["type"]), "market", len(proxy_cells["market"]),
          "seconds", round(time.time() - t0, 1), "peak_rss_mb", _rss_mb(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
