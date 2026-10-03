"""Backtest: do hockeysim's NHL GAME-LINE outputs beat a naive baseline AND the book?

Companion to lane `nhl-player-props-projection`'s `scripts/backtest_nhl_props.py` (props only). This
harness covers the game markets: moneyline, regulation 3-way, puck line +/-1.5, totals (over and
under scored separately), and the first period (P1) where the model projects it.

WHAT IT RUNS. The PRODUCTION game path, unmodified: `features.loaders.build_slate_features` over a
per-date as-of root -> closing market injected -> `scripts/build_nhl_artifacts.py::predict_game`
(raw sim on the un-anchored lambdas, then the served sim on lambdas anchored 0.35 toward the
moneyline, exactly as `_predictions_and_markets` does). A seed-exact replica of
`game_market_sim.simulate_from_period_lambdas` (default config: no overdispersion, no shared pace,
no empty-net) re-draws the SAME samples and is ASSERTED equal to production's p_home_ml / p_over /
p_home_pl per game, so the regulation 3-way, the away -1.5 side, the P1 markets and the
OT-corrected total are read off the distribution production itself drew.

AS-OF INPUTS. The per-date roots are the ones `backtest_nhl_props.py::run_date` wrote: season files
(`team_rates/team_xg/team_elo/team_special_teams/player_rates`) rebuilt from games STRICTLY BEFORE
the date with the producers' own aggregation, plus lineups/goalies from the production collector.
This harness never writes them; it reads `<roots>/roots/<date>/` and CHECKS them: every date's
`team_rates_2025-2026.csv` games total must equal 2x the regular-season games played before that
date (`leak_check`), and a date whose model totals are all identical is flagged `degenerate`
(the fleet's 5.9134 failure, deploys 2026-10-02 ~16:5xZ).

SETTLEMENT (the classic silent bug, made explicit):
  * moneyline, puck line, totals settle FULL GAME: final score, the shootout winner credited one
    goal (book convention). `game_market_sim` has no OT: ML splits a regulation tie 50/50, the
    puck line is the regulation margin (equivalent: an OT/SO win is by exactly 1), and p_over is
    computed on REGULATION goals -- scored here against the full-game total, as served, and
    alongside an OT-corrected diagnostic (a regulation tie adds one goal).
  * regulation 3-way settles on 60 minutes; P1 on the first period.

BASELINES (as-of, strictly before the date): (a) team goals-for/against -> multiplicative team
lambdas, split into periods by the as-of league period shares, pushed through the SAME replica sim,
so the baseline differs from the model only in its inputs; (b) moneyline only: points% log5 with
the as-of league home edge; (c) constant as-of home win rate.

BOOK. OddsAPI historical snapshots ~3 minutes before each start slot (`odds` subcommand, dry run
by default, `--execute` and `--max-credits` to spend; every call attributed `sport=nhl` in the
quota ledger). Per book proportional de-vig on two-way markets, consensus = mean of per-book fair
probabilities over books quoting BOTH sides at the modal line.

Subcommands:
  py -3 scripts/backtest_nhl_game_lines.py actuals
  py -3 scripts/backtest_nhl_game_lines.py odds [--execute --max-credits 30000]
  py -3 scripts/backtest_nhl_game_lines.py probe-periods --events 5 [--execute]
  py -3 scripts/backtest_nhl_game_lines.py sim [--workers 8]
  py -3 scripts/backtest_nhl_game_lines.py score --report docs/reports/<name>.md
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import random
import statistics
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

NHLE = "https://api-web.nhle.com/v1"
ODDS_BASE = "https://api.the-odds-api.com/v4"
ANCHOR_WEIGHT = 0.35  # production default (`resolve_anchor_weight`, env absent)
N_SIMS = 20000        # production default (`adapters._DEFAULT_GAME_SIMS`)
SEASON_PREV = 20252026
SEASON_CUR = 20262027
CLIP = 1e-4


def _main_worktree() -> Path:
    """The PRIMARY checkout (its untracked data/ mirror holds the raw boxscores), resolved via git,
    never `REPO` -- in a session worktree `REPO` is the worktree (learnings 2026-09-10)."""
    out = subprocess.run(["git", "-C", str(REPO), "worktree", "list", "--porcelain"],
                         capture_output=True, text=True, check=True).stdout
    return Path(out.splitlines()[0].split(" ", 1)[1].strip())


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"_gl_{name}", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _rj(path: Path) -> Optional[Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _http_json(url: str, cache: Path, allow_net: bool) -> Optional[Any]:
    got = _rj(cache)
    if got is not None or not allow_net:
        return got
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})  # urllib's UA gets 403
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
            return data
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def _arm(meta: Dict) -> Optional[str]:
    if meta["season"] == SEASON_PREV and meta["gtype"] == 2:
        return "regular"
    if meta["season"] == SEASON_PREV and meta["gtype"] == 3:
        return "playoff"
    if meta["season"] == SEASON_CUR:
        return "current_pre" if meta["gtype"] == 1 else "current_reg"
    return None


# ---------------------------------------------------------------------------
# 1. actuals: final / regulation / OT / SO / per period, from boxscore + landing
# ---------------------------------------------------------------------------

def cmd_actuals(a) -> int:
    out, roots, src = Path(a.out), Path(a.roots), Path(a.src)
    gi = json.loads((roots / "game_index.json").read_text(encoding="utf-8"))["index"]
    res: Dict[str, Dict] = {}
    bad = Counter()
    for gid, m in sorted(gi.items()):
        arm = _arm(m)
        if arm is None:
            continue
        box = None
        for p in (src / "data" / "ingestion_cache" / f"boxscore_{gid}.json", roots / "cache" / f"boxscore_{gid}.json"):
            box = _rj(p)
            if box:
                break
        land = _rj(src / "data" / "truth" / "raw" / f"landing_{gid}.json") or _http_json(
            f"{NHLE}/gamecenter/{gid}/landing", out / "cache" / f"landing_{gid}.json", not a.offline)
        if not box or not land:
            bad["no_box_or_landing"] += 1
            continue
        hs, as_ = int(box["homeTeam"]["score"]), int(box["awayTeam"]["score"])
        last = str((box.get("gameOutcome") or {}).get("lastPeriodType") or "")
        per = {1: [0, 0], 2: [0, 0], 3: [0, 0], "OT": [0, 0]}
        for blk in (land.get("summary") or {}).get("scoring") or []:
            pd = blk.get("periodDescriptor") or {}
            key = pd.get("number") if pd.get("periodType") == "REG" else ("OT" if pd.get("periodType") == "OT" else None)
            if key is None:
                continue
            for g in blk.get("goals") or []:
                ab = str((g.get("teamAbbrev") or {}).get("default") or g.get("teamAbbrev") or "").upper()
                side = 0 if ab == m["home"] else (1 if ab == m["away"] else None)
                if side is None:
                    bad["goal_team_unmatched"] += 1
                    continue
                if key == "OT":
                    per["OT"][side] += 1
                elif key in per:
                    per[key][side] += 1
        reg_h = per[1][0] + per[2][0] + per[3][0]
        reg_a = per[1][1] + per[2][1] + per[3][1]
        so_h = so_a = 0
        if last == "SO":
            so_h, so_a = (1, 0) if hs > as_ else (0, 1)
        # the identity that proves the parse: regulation + OT + the SO credit == the final score
        if (reg_h + per["OT"][0] + so_h, reg_a + per["OT"][1] + so_a) != (hs, as_):
            bad["score_identity_fail"] += 1
            continue
        res[gid] = {**m, "arm": arm, "final_h": hs, "final_a": as_, "last": last,
                    "reg_h": reg_h, "reg_a": reg_a, "p1_h": per[1][0], "p1_a": per[1][1],
                    "p2_h": per[2][0], "p2_a": per[2][1], "p3_h": per[3][0], "p3_a": per[3][1],
                    "ot_h": per["OT"][0], "ot_a": per["OT"][1], "so": last == "SO"}
    out.mkdir(parents=True, exist_ok=True)
    (out / "actuals.json").write_text(json.dumps(res), encoding="utf-8")
    by = Counter(r["arm"] for r in res.values())
    lp = Counter((r["arm"], r["last"]) for r in res.values())
    print(f"actuals: {dict(by)}  dropped: {dict(bad)}")
    print(f"  last period type: {dict(lp)}")
    return 0


# ---------------------------------------------------------------------------
# 2. book: OddsAPI historical closing snapshots per start slot
# ---------------------------------------------------------------------------

def _api_key() -> str:
    for name in ("ODDS_API_KEY", "ODDSAPI_KEY", "THE_ODDS_API_KEY"):
        if os.environ.get(name):
            return os.environ[name].strip()
    env = _main_worktree() / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            for name in ("ODDS_API_KEY", "ODDSAPI_KEY", "THE_ODDS_API_KEY"):
                if line.strip().startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no OddsAPI key")


class Budget:
    def __init__(self, cap: int):
        self.cap, self.spent, self.calls, self.remaining = int(cap), 0, 0, None

    def charge(self, h: Dict[str, str]) -> None:
        self.calls += 1
        try:
            self.spent += int(h.get("x-requests-last") or 0)
        except Exception:
            pass
        self.remaining = h.get("x-requests-remaining")
        if self.cap and self.spent > self.cap:
            raise RuntimeError(f"credit ceiling hit: {self.spent} > {self.cap}; checkpointed, re-run to continue")


def _odds_get(path: str, params: Dict, key: str, budget: Budget) -> Optional[Any]:
    q = dict(params, apiKey=key)
    url = f"{ODDS_BASE}{path}?{urllib.parse.urlencode(q)}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as r:
                h = {k.lower(): v for k, v in r.headers.items()}
                budget.charge(h)
                _record_quota(h, path)
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            h = {k.lower(): v for k, v in (exc.headers or {}).items()}
            budget.charge(h)
            _record_quota(h, path)
            if exc.code in (404, 422):
                return None
        except RuntimeError:
            raise
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def _record_quota(h: Dict[str, str], path: str) -> None:
    # every OddsAPI seam records, attributed to THIS sport (backfill_mlb_historical_odds._record_quota)
    try:
        from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota
        record_oddsapi_quota(h, sport="nhl", endpoint=f"historical{path}")
    except Exception:
        pass


def _slots(actuals: Dict[str, Dict]) -> Dict[str, List[str]]:
    slots: Dict[str, List[str]] = defaultdict(list)
    for gid, r in actuals.items():
        if r.get("start"):
            slots[r["start"]].append(gid)
    return slots


def _snap_time(start: str, minutes: int = 3) -> str:
    t = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - timedelta(minutes=minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_odds(a) -> int:
    out = Path(a.out)
    act = json.loads((out / "actuals.json").read_text(encoding="utf-8"))
    slots = _slots(act)
    todo = []
    for start, gids in sorted(slots.items()):
        if (out / "odds" / f"{start.replace(':', '')}.json").exists():
            continue
        pre = all(act[g]["arm"] == "current_pre" for g in gids)
        todo.append((start, "icehockey_nhl_preseason" if pre else "icehockey_nhl"))
    est = len(todo) * 3 * 10
    print(f"odds: {len(slots)} start slots, {len(slots) - len(todo)} cached, {len(todo)} to fetch, "
          f"estimate {est} credits (3 markets x 1 region x 10)")
    if not a.execute:
        print("dry run -- pass --execute to spend")
        return 0
    key, budget = _api_key(), Budget(a.max_credits)
    (out / "odds").mkdir(parents=True, exist_ok=True)
    try:
        for i, (start, sport) in enumerate(todo):
            d = _odds_get(f"/historical/sports/{sport}/odds",
                          {"regions": "us", "markets": "h2h,spreads,totals", "oddsFormat": "american",
                           "date": _snap_time(start)}, key, budget)
            (out / "odds" / f"{start.replace(':', '')}.json").write_text(
                json.dumps({"start": start, "sport": sport, "snap": d}), encoding="utf-8")
            if i % 50 == 0:
                print(f"  {i}/{len(todo)} spent={budget.spent} calls={budget.calls}", flush=True)
    finally:
        print(f"odds: spent {budget.spent} credits over {budget.calls} calls; header remaining={budget.remaining}")
    return 0


def cmd_probe(a) -> int:
    """Do OddsAPI historical snapshots carry regulation 3-way and P1 markets for NHL? A handful of
    events, per-event endpoint; reports which markets came back per book. Spends nothing without
    --execute."""
    out = Path(a.out)
    act = json.loads((out / "actuals.json").read_text(encoding="utf-8"))
    picks = []
    for f in sorted((out / "odds").glob("*.json"))[:: max(1, len(list((out / "odds").glob("*.json"))) // 10)]:
        blob = _rj(f) or {}
        data = ((blob.get("snap") or {}).get("data")) or []
        if data:
            picks.append((blob["start"], blob["sport"], data[0]["id"]))
        if len(picks) >= a.events:
            break
    mk = "h2h_3_way,h2h_p1,totals_p1,spreads_p1,h2h_3_way_p1"
    print(f"probe: {len(picks)} events x markets {mk}; worst case {len(picks) * 5 * 10} credits")
    if not a.execute:
        return 0
    key, budget = _api_key(), Budget(a.max_credits)
    rep = []
    for start, sport, eid in picks:
        d = _odds_get(f"/historical/sports/{sport}/events/{eid}/odds",
                      {"regions": "us", "markets": mk, "oddsFormat": "american", "date": _snap_time(start)}, key, budget)
        got = Counter()
        for b in ((d or {}).get("data") or {}).get("bookmakers") or []:
            for m in b.get("markets") or []:
                got[m["key"]] += 1
        rep.append({"start": start, "event": eid, "books_per_market": dict(got)})
        print(f"  {start} {eid}: {dict(got)}")
    (out / "probe_periods.json").write_text(json.dumps({"spent": budget.spent, "events": rep}), encoding="utf-8")
    print(f"probe spent {budget.spent} credits")
    return 0


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace(".", " ").split())


def _abbr_of(name: str) -> Optional[str]:
    from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import _team_abbr
    ab = _team_abbr(name)
    if ab:
        return ab.upper()
    n = _norm(name)
    special = {"utah hockey club": "UTA", "utah mammoth": "UTA", "st louis blues": "STL", "montreal canadiens": "MTL"}
    return special.get(n)


def _pair_fair(first_odds: float, second_odds: float) -> float:
    """Proportional fair probability of the FIRST side of a two-way market, using the production
    (differential-registered) American->probability converter rather than a private copy."""
    from syndicate.features.nhl.sim_engine.hockeysim.adapters import american_to_implied
    a, b = american_to_implied(first_odds), american_to_implied(second_odds)
    return a / (a + b)


def book_consensus(act: Dict[str, Dict], out: Path) -> Dict[str, Dict]:
    """{gid: {ml_home, total_line, p_over, pl_line_home, p_home_pl, books_ml, ...}} from the closing
    snapshot of the game's own start slot. Unmatched events and one-sided books are counted."""
    by_slot = _slots(act)
    res: Dict[str, Dict] = {}
    stats = Counter()
    for start, gids in by_slot.items():
        blob = _rj(out / "odds" / f"{start.replace(':', '')}.json")
        if not blob:
            stats["slot_not_fetched"] += len(gids)
            continue
        events = ((blob.get("snap") or {}).get("data")) or []
        snap_ts = (blob.get("snap") or {}).get("timestamp")
        idx = {}
        for ev in events:
            idx[(_abbr_of(ev.get("home_team", "")), _abbr_of(ev.get("away_team", "")))] = ev
        for gid in gids:
            r = act[gid]
            ev = idx.get((r["home"], r["away"]))
            if ev is None:
                stats["event_unmatched"] += 1
                continue
            if abs((datetime.strptime(ev["commence_time"], "%Y-%m-%dT%H:%M:%SZ")
                    - datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ")).total_seconds()) > 6 * 3600:
                stats["event_other_commence"] += 1
                continue
            home_n, away_n = _norm(ev["home_team"]), _norm(ev["away_team"])
            ml, tot, pl = [], defaultdict(list), defaultdict(list)
            for b in ev.get("bookmakers") or []:
                for m in b.get("markets") or []:
                    oc = {(_norm(o["name"]), o.get("point")): o["price"] for o in m.get("outcomes") or []}
                    if m["key"] == "h2h":
                        ph, pa = oc.get((home_n, None)), oc.get((away_n, None))
                        if ph is not None and pa is not None:
                            ml.append(_pair_fair(ph, pa))
                    elif m["key"] == "totals":
                        pts = {p for (_, p) in oc}
                        for p in pts:
                            po, pu = oc.get(("over", p)), oc.get(("under", p))
                            if po is not None and pu is not None:
                                tot[float(p)].append(_pair_fair(po, pu))
                    elif m["key"] == "spreads":
                        for (nm, p), price in oc.items():
                            if nm == home_n and p is not None and abs(abs(p) - 1.5) < 1e-9:
                                other = oc.get((away_n, -p))
                                if other is not None:
                                    pl[float(p)].append(_pair_fair(price, other))
            row: Dict[str, Any] = {"snap_ts": snap_ts, "commence": ev["commence_time"]}
            if ml:
                row.update(ml_home=statistics.fmean(ml), books_ml=len(ml))
            if tot:
                line = max(tot, key=lambda p: (len(tot[p]), -abs(p - 6.0)))
                row.update(total_line=line, p_over=statistics.fmean(tot[line]), books_total=len(tot[line]),
                           total_lines_seen=len(tot))
            if pl:
                line = max(pl, key=lambda p: len(pl[p]))
                row.update(pl_line_home=line, p_home_pl=statistics.fmean(pl[line]), books_pl=len(pl[line]))
            res[gid] = row
            stats["matched"] += 1
    return res, dict(stats)


def quote_log_close(act: Dict[str, Dict], qdir: Path) -> Tuple[Dict[str, Dict], Dict]:
    """Pregame close from the platform's own per-book quote log (`<sport>_source/tracking/
    book_quotes/<date>.jsonl[.gz]`, copied read-only from the fleet). Every row carries
    `captured_at`, so the close is PROVABLY pregame: per (book, market, selection, line) the last
    row with captured_at <= commence_time. Same de-vig/consensus as `book_consensus`.
    The `oddsapi.csv` captures are NOT used: they carry no timestamp (book_last_update empty on
    every row) and the fleet's 2026-10-02 file holds in-play totals, so they cannot prove a close."""
    import gzip
    last: Dict[Tuple, Tuple[str, float]] = {}
    ev_meta: Dict[str, Tuple[str, str, str]] = {}
    stats = Counter()
    for f in sorted(qdir.glob("*.jsonl*")):
        op = gzip.open if f.suffix == ".gz" else open
        with op(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line.replace("NaN", "null"))
                except Exception:
                    stats["bad_line"] += 1
                    continue
                if r.get("kind") != "game" or r.get("segment") != "full":
                    continue
                if not (r.get("captured_at") and r["captured_at"] <= r["commence_time"]):
                    stats["post_start_rows"] += 1
                    continue
                k = (r["event_id"], r["bookmaker"], r["market"], r["selection"], r.get("line"))
                if k not in last or r["captured_at"] >= last[k][0]:
                    last[k] = (r["captured_at"], float(r["price"]))
                ev_meta[r["event_id"]] = (r["home_team"], r["away_team"], r["commence_time"])
    per_ev: Dict[str, Dict[Tuple, float]] = defaultdict(dict)
    for (eid, bk, mk, sel, ln), (_ts, price) in last.items():
        per_ev[eid][(bk, mk, sel, ln)] = price
    idx = {}
    for eid, (h, a_, c) in ev_meta.items():
        idx[(_abbr_of(h), _abbr_of(a_))] = (eid, c)
    res: Dict[str, Dict] = {}
    for gid, r in act.items():
        hit = idx.get((r["home"], r["away"]))
        if hit is None:
            continue
        eid, c = hit
        if abs((datetime.strptime(c, "%Y-%m-%dT%H:%M:%SZ")
                - datetime.strptime(r["start"], "%Y-%m-%dT%H:%M:%SZ")).total_seconds()) > 6 * 3600:
            stats["other_commence"] += 1
            continue
        q = per_ev[eid]
        books = {k[0] for k in q}
        ml, tot, pl = [], defaultdict(list), defaultdict(list)
        for b in books:
            ph, pa = q.get((b, "h2h", "home", None)), q.get((b, "h2h", "away", None))
            if ph is not None and pa is not None:
                ml.append(_pair_fair(ph, pa))
            for (bb, mk, sel, ln), pr in q.items():
                if bb != b or ln is None:
                    continue
                if mk == "totals" and sel == "over" and (b, "totals", "under", ln) in q:
                    tot[float(ln)].append(_pair_fair(pr, q[(b, "totals", "under", ln)]))
                if mk == "spreads" and sel == "home" and abs(abs(ln) - 1.5) < 1e-9 and (b, "spreads", "away", -ln) in q:
                    pl[float(ln)].append(_pair_fair(pr, q[(b, "spreads", "away", -ln)]))
        row: Dict[str, Any] = {"source": "fleet_book_quotes", "commence": c}
        if ml:
            row.update(ml_home=statistics.fmean(ml), books_ml=len(ml))
        if tot:
            line = max(tot, key=lambda p: (len(tot[p]), -abs(p - 6.0)))
            row.update(total_line=line, p_over=statistics.fmean(tot[line]), books_total=len(tot[line]), total_lines_seen=len(tot))
        if pl:
            line = max(pl, key=lambda p: len(pl[p]))
            row.update(pl_line_home=line, p_home_pl=statistics.fmean(pl[line]), books_pl=len(pl[line]))
        res[gid] = row
        stats["matched"] += 1
    return res, dict(stats)


# ---------------------------------------------------------------------------
# 3. sim: production predict_game over the as-of roots + seed-exact replica
# ---------------------------------------------------------------------------

def replica(hp: List[float], ap: List[float], seed: int, n: int = N_SIMS) -> Tuple[np.ndarray, np.ndarray]:
    """`simulate_from_period_lambdas` default-config draws, call for call (same RNG sequence)."""
    g = np.random.default_rng(seed)
    shared = np.ones(n, dtype=np.float64)
    h = np.column_stack([g.poisson(lam=np.clip(max(0.0, float(hp[i])) * shared, 0.0, None), size=n) for i in range(3)])
    a = np.column_stack([g.poisson(lam=np.clip(max(0.0, float(ap[i])) * shared, 0.0, None), size=n) for i in range(3)])
    return h, a


def dist_probs(h: np.ndarray, a: np.ndarray, total_line: Optional[float], pl_line_home: Optional[float]) -> Dict[str, float]:
    hg, ag = h.sum(axis=1), a.sum(axis=1)
    d, t = hg - ag, hg + ag
    tie = d == 0
    out = {
        "p_home_ml": float(((d > 0).sum() + 0.5 * tie.sum()) / len(d)),
        "p_reg_home": float((d > 0).mean()), "p_reg_tie": float(tie.mean()), "p_reg_away": float((d < 0).mean()),
        "p_home_m15": float((d > 1.5).mean()), "p_away_m15": float((d < -1.5).mean()),
        "reg_total_mean": float(t.mean()), "margin_mean": float(d.mean()),
        "p1_total_mean": float((h[:, 0] + a[:, 0]).mean()),
        "p1_over05": float(((h[:, 0] + a[:, 0]) > 0.5).mean()), "p1_over15": float(((h[:, 0] + a[:, 0]) > 1.5).mean()),
        "p1_home": float((h[:, 0] > a[:, 0]).mean()), "p1_tie": float((h[:, 0] == a[:, 0]).mean()),
        "p1_away": float((h[:, 0] < a[:, 0]).mean()),
    }
    if total_line is not None:
        out["p_over_reg"] = float((t > total_line).mean())           # what production serves
        out["p_over_full"] = float(((t + tie) > total_line).mean())  # OT-corrected diagnostic
    for L in (5.5, 6.5):
        out[f"p_over_reg_{L}"] = float((t > L).mean())
        out[f"p_over_full_{L}"] = float(((t + tie) > L).mean())
    if pl_line_home is not None:
        # home side at the book's puck line: -1.5 => cover d > 1.5 ; +1.5 => d > -1.5
        out["p_home_pl"] = float((d > -pl_line_home).mean())
    return out


_W: Dict[str, Any] = {}


def _winit(roots: str, out: str) -> None:
    _W["roots"], _W["out"] = Path(roots), Path(out)
    _W["bna"] = _load_script("build_nhl_artifacts")
    _W["book"] = json.loads((Path(out) / "book.json").read_text(encoding="utf-8")) if (Path(out) / "book.json").exists() else {}
    _W["act"] = json.loads((Path(out) / "actuals.json").read_text(encoding="utf-8"))


def sim_date(date: str) -> Dict:
    from syndicate.features.nhl.sim_engine.hockeysim.adapters import game_seed
    from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyMarketLines
    from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import build_slate_features
    from syndicate.features.nhl.sim_engine.hockeysim.market_anchoring import anchor_game_features

    bna, book, act = _W["bna"], _W["book"], _W["act"]
    root = _W["roots"] / "roots" / date
    games = build_slate_features(date, root=root)
    rows = []
    for g in games:
        gid = str(g.game_pk)
        b = book.get(gid, {})
        ml = b.get("ml_home")
        # Inject the closing market the way the producer injects the collected one. Only the ML
        # feeds anchoring; total_line is the modal CLOSING line (production's own consensus picks a
        # median over every point it captured -- a separate defect, recorded in the findings).
        mkt = HockeyMarketLines(total_line=b.get("total_line"), puck_line=-1.5,
                                home_ml_odds=None, away_ml_odds=None,
                                home_win_probability=ml)
        gm = replace(g, market=mkt)
        pred = bna.predict_game(gm, anchor_weight=ANCHOR_WEIGHT)
        seed = game_seed(date, gid)
        hp_raw = [max(0.0, float(x)) for x in g.home.period_goal_lambdas][:3]
        ap_raw = [max(0.0, float(x)) for x in g.away.period_goal_lambdas][:3]
        hr, ar = replica(hp_raw, ap_raw, seed)
        raw = dist_probs(hr, ar, b.get("total_line"), b.get("pl_line_home"))
        # replica == production, asserted (the raw sim IS predict_game's raw run)
        assert abs(raw["p_home_ml"] - pred.p_home_ml_raw) < 1e-12, (date, gid, raw["p_home_ml"], pred.p_home_ml_raw)
        assert abs(raw["p_home_m15"] - pred.p_home_pl_minus_1_5_raw) < 1e-12, (date, gid)
        rec = {"gid": gid, "date": date, "anchor_state": pred.anchor_state,
               "hp": hp_raw, "ap": ap_raw, "model_total": pred.model_total if pred.anchor_state != "anchored" else float(sum(hp_raw) + sum(ap_raw)),
               "raw": raw}
        if pred.anchor_state == "anchored":
            ga = anchor_game_features(gm, weight=ANCHOR_WEIGHT)
            hpa = [max(0.0, float(x)) for x in ga.home.period_goal_lambdas][:3]
            apa = [max(0.0, float(x)) for x in ga.away.period_goal_lambdas][:3]
            ha, aa = replica(hpa, apa, seed)
            anc = dist_probs(ha, aa, b.get("total_line"), b.get("pl_line_home"))
            assert abs(anc["p_home_ml"] - pred.p_home_ml) < 1e-12, (date, gid, "anchored")
            if b.get("total_line") is not None:
                assert abs(anc["p_over_reg"] - pred.p_over) < 1e-12, (date, gid, "p_over")
            rec["served"] = anc
            rec["served_total"] = pred.model_total
        else:
            if b.get("total_line") is not None:
                assert abs(raw["p_over_reg"] - pred.p_over) < 1e-12, (date, gid, "p_over raw")
            rec["served"] = raw
            rec["served_total"] = pred.model_total
        rows.append(rec)
    totals = sorted({round(r["model_total"], 4) for r in rows})
    return {"date": date, "games": rows, "n_games_slate": len(games),
            "degenerate": len(rows) >= 3 and len(totals) == 1, "distinct_totals": len(totals)}


def leak_check(roots: Path, act: Dict[str, Dict], dates: List[str]) -> Dict[str, Any]:
    """team_rates_2025-2026 games total in each regular-season root == 2x regular games before it."""
    reg_dates = sorted(r["date"] for r in act.values() if r["arm"] == "regular")
    import bisect
    fails, checked = [], 0
    for d in dates:
        p = roots / "roots" / d / "data" / "processed" / "team_rates_2025-2026.csv"
        if not p.exists():
            continue
        tot = sum(int(float(r["games"])) for r in csv.DictReader(p.open(encoding="utf-8")))
        before = bisect.bisect_left(reg_dates, d)
        # regular-season roots must equal the strictly-before count; playoff/current roots carry the
        # full regular season (the producers' own regular-season filter), i.e. <= all of it
        checked += 1
        if d <= max(reg_dates):
            if tot != 2 * before:
                fails.append((d, tot, 2 * before))
        elif tot > 2 * len(reg_dates):
            fails.append((d, tot, 2 * len(reg_dates)))
    return {"checked": checked, "fails": fails[:20], "n_fail": len(fails)}


def cmd_sim(a) -> int:
    out, roots = Path(a.out), Path(a.roots)
    act = json.loads((out / "actuals.json").read_text(encoding="utf-8"))
    book, bstats = book_consensus(act, out)
    if a.quote_log:
        qbook, qstats = quote_log_close(act, Path(a.quote_log))
        bstats = {"oddsapi_historical": bstats, "fleet_book_quotes": qstats}
        for gid, row in qbook.items():
            book.setdefault(gid, row)  # an OddsAPI close, when present, wins
    (out / "book.json").write_text(json.dumps(book), encoding="utf-8")
    print(f"book: {bstats}")
    dates = sorted(p.name for p in (roots / "roots").iterdir() if p.is_dir())
    lk = leak_check(roots, act, dates)
    print(f"leak_check: {lk['checked']} roots checked, {lk['n_fail']} fail {lk['fails'][:5]}")
    (out / "sim").mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=a.workers, initializer=_winit, initargs=(str(roots), str(out))) as ex:
        futs = {ex.submit(sim_date, d): d for d in dates}
        for i, f in enumerate(as_completed(futs)):
            r = f.result()
            results.append(r)
            if i % 25 == 0:
                print(f"  sim {i}/{len(dates)} ({time.time() - t0:.0f}s)", flush=True)
    results.sort(key=lambda r: r["date"])
    (out / "sim" / "games.json").write_text(json.dumps({"dates": results, "leak_check": lk, "book_stats": bstats}), encoding="utf-8")
    print(f"sim: {sum(len(r['games']) for r in results)} games over {len(results)} dates, "
          f"degenerate dates {[r['date'] for r in results if r['degenerate']]} ({time.time() - t0:.0f}s)")
    return 0


# ---------------------------------------------------------------------------
# 4. baselines (as-of) + scoring
# ---------------------------------------------------------------------------

class AsOf:
    """Chronological team history; `state(date)` uses only games strictly before `date`.
    Regular-season arm: 2025-26 games before the date. Playoffs: regular season + earlier playoff
    games. 2026-27: the full 2025-26 season (the prior season, as the props harness does)."""

    def __init__(self, act: Dict[str, Dict]):
        self.games = sorted(act.values(), key=lambda r: (r["date"], r["gid"]))

    def state(self, date: str, arm: str) -> Dict[str, Any]:
        if arm.startswith("current"):
            pool = [g for g in self.games if g["season"] == SEASON_PREV]
        else:
            pool = [g for g in self.games if g["season"] == SEASON_PREV and g["date"] < date]
        t = defaultdict(lambda: {"gp": 0, "gf": 0, "ga": 0, "pts": 0})
        hw = n = 0
        p1 = reg = 0
        hgoals = agoals = 0
        for g in pool:
            # goals excluding the shootout credit (scoring-rate estimate, not settlement)
            fh, fa = g["reg_h"] + g["ot_h"], g["reg_a"] + g["ot_a"]
            for side, gf, ga, won in ((g["home"], fh, fa, g["final_h"] > g["final_a"]),
                                      (g["away"], fa, fh, g["final_a"] > g["final_h"])):
                s = t[side]
                s["gp"] += 1; s["gf"] += gf; s["ga"] += ga
                s["pts"] += 2 if won else (1 if g["last"] in ("OT", "SO") else 0)
            n += 1; hw += g["final_h"] > g["final_a"]
            hgoals += fh; agoals += fa
            p1 += g["p1_h"] + g["p1_a"]; reg += g["reg_h"] + g["reg_a"]
        return {"t": t, "n": n, "home_win": (hw / n) if n else 0.52,
                "lg_home": (hgoals / n) if n else 3.1, "lg_away": (agoals / n) if n else 2.9,
                "p1_share": (p1 / reg) if reg else 0.29}


def baseline_lams(st: Dict, home: str, away: str, k: float = 10.0) -> Optional[Tuple[float, float]]:
    t, n = st["t"], st["n"]
    if n < 50 or home not in t or away not in t:
        return None
    lg = (st["lg_home"] + st["lg_away"]) / 2.0

    def rate(s, key):  # shrink toward league per-team-game average
        return (s[key] + k * lg) / (s["gp"] + k)
    h, a = t[home], t[away]
    lh = st["lg_home"] * (rate(h, "gf") / lg) * (rate(a, "ga") / lg)
    la = st["lg_away"] * (rate(a, "gf") / lg) * (rate(h, "ga") / lg)
    return lh, la


def _periods(lam: float, p1_share: float) -> List[float]:
    rest = (1.0 - p1_share) / 2.0
    return [lam * p1_share, lam * rest, lam * rest]


def _clip(p: float) -> float:
    return min(1.0 - CLIP, max(CLIP, float(p)))


def _brier(p, y):
    return (p - y) ** 2


def _ll(p, y):
    p = _clip(p)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _boot_diff(rows: List[Tuple[str, float]], n_boot: int = 2000, seed: int = 11) -> Tuple[float, float, float]:
    """Mean of per-game differences with a DATE-clustered bootstrap 95% CI."""
    if not rows:
        return (float("nan"),) * 3
    by = defaultdict(list)
    for d, v in rows:
        by[d].append(v)
    keys = list(by)
    rng = random.Random(seed)
    est = statistics.fmean(v for _, v in rows)
    bs = []
    for _ in range(n_boot):
        s = c = 0.0
        for _k in range(len(keys)):
            vs = by[keys[rng.randrange(len(keys))]]
            s += sum(vs); c += len(vs)
        bs.append(s / c)
    bs.sort()
    return est, bs[int(0.025 * n_boot)], bs[int(0.975 * n_boot) - 1]


def _verdict(est, lo, hi, n, min_n, lower_is_better=True) -> str:
    if n < min_n:
        return f"NO VERDICT (n={n} < {min_n})"
    if math.isnan(lo):
        return "NO VERDICT"
    if hi < 0:
        return "MODEL BETTER" if lower_is_better else "MODEL WORSE"
    if lo > 0:
        return "MODEL WORSE" if lower_is_better else "MODEL BETTER"
    return "NO DIFFERENCE"


def cmd_score(a) -> int:
    out = Path(a.out)
    act = json.loads((out / "actuals.json").read_text(encoding="utf-8"))
    sim = json.loads((out / "sim" / "games.json").read_text(encoding="utf-8"))
    book = json.loads((out / "book.json").read_text(encoding="utf-8"))
    asof = AsOf(act)
    st_cache: Dict[Tuple[str, str], Dict] = {}
    degenerate = {r["date"] for r in sim["dates"] if r["degenerate"]}
    rows: List[Dict] = []
    drops = Counter()
    for dr in sim["dates"]:
        for g in dr["games"]:
            r = act.get(g["gid"])
            if r is None:
                drops["no_actual"] += 1
                continue
            if g["date"] in degenerate:
                drops["degenerate_date"] += 1
                continue
            key = (g["date"], r["arm"])
            if key not in st_cache:
                st_cache[key] = asof.state(*key)
            st = st_cache[key]
            bl = baseline_lams(st, r["home"], r["away"])
            if bl is None:
                drops["no_baseline"] += 1
                continue
            b = book.get(g["gid"], {})
            from syndicate.features.nhl.sim_engine.hockeysim.adapters import game_seed
            hb, ab_ = replica(_periods(bl[0], st["p1_share"]), _periods(bl[1], st["p1_share"]), game_seed(g["date"], g["gid"]) ^ 0x5bd1e995)
            base = dist_probs(hb, ab_, b.get("total_line"), b.get("pl_line_home"))
            th, ta = st["t"][r["home"]], st["t"][r["away"]]
            ph = (th["pts"] + 10) / (2 * th["gp"] + 20)
            pa = (ta["pts"] + 10) / (2 * ta["gp"] + 20)
            log5 = ph * (1 - pa) / (ph * (1 - pa) + pa * (1 - ph))
            lh = math.log(st["home_win"] / (1 - st["home_win"]))
            pts_ml = 1 / (1 + math.exp(-(math.log(log5 / (1 - log5)) + lh)))
            rows.append({"gid": g["gid"], "date": g["date"], "arm": r["arm"], "act": r, "m": g["raw"], "s": g["served"],
                         "anchored": g["anchor_state"] == "anchored", "mt": g["model_total"],
                         "b": base, "bt": bl[0] + bl[1], "bm": bl[0] - bl[1], "pts_ml": pts_ml,
                         "const_ml": st["home_win"], "book": b})
    report = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "drops": dict(drops), "degenerate_dates": sorted(degenerate),
              "leak_check": sim.get("leak_check"), "book_stats": sim.get("book_stats"), "arms": {}}
    for arm in ("regular", "playoff", "current_pre", "current_reg"):
        R = [x for x in rows if x["arm"] == arm]
        if R:
            report["arms"][arm] = score_arm(R, a.min_n)
    report["coverage"] = coverage(act, sim, book)
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    if a.report:
        write_md(report, Path(a.report))
    print(json.dumps({k: v for k, v in report.items() if k != "arms"}, indent=1)[:3000])
    for arm, rep in report["arms"].items():
        print(f"== {arm}: n_games={rep['n_games']}")
        for line in rep["lines"]:
            print("  " + line)
    return 0


def coverage(act, sim, book) -> Dict[str, Any]:
    proj = defaultdict(set)
    for dr in sim["dates"]:
        for g in dr["games"]:
            if g["gid"] in act:
                proj[act[g["gid"]]["arm"]].add(g["gid"])
    fin = defaultdict(set)
    for gid, r in act.items():
        fin[r["arm"]].add(gid)
    bk = defaultdict(set)
    for gid in book:
        if gid in act:
            bk[act[gid]["arm"]].add(gid)
    out = {}
    for arm in fin:
        d = lambda s: sorted({act[g]["date"] for g in s})
        inter = proj[arm] & fin[arm] & bk[arm]
        out[arm] = {"finals": [len(fin[arm]), len(d(fin[arm]))], "projections": [len(proj[arm]), len(d(proj[arm]))],
                    "book": [len(bk[arm]), len(d(bk[arm]))], "intersection": [len(inter), len(d(inter))],
                    "window": [min(d(fin[arm])), max(d(fin[arm]))]}
    return out


def score_arm(R: List[Dict], min_n: int) -> Dict:
    lines: List[str] = []
    res: Dict[str, Any] = {"n_games": len(R), "markets": {}}

    def point(name, pred_key, base_key, actual_fn):
        e_m = [(x["date"], pred_key(x) - actual_fn(x)) for x in R]
        e_b = [(x["date"], base_key(x) - actual_fn(x)) for x in R]
        mae_m = statistics.fmean(abs(v) for _, v in e_m)
        mae_b = statistics.fmean(abs(v) for _, v in e_b)
        bias_m = statistics.fmean(v for _, v in e_m)
        bias_b = statistics.fmean(v for _, v in e_b)
        d = _boot_diff([(x["date"], abs(pred_key(x) - actual_fn(x)) - abs(base_key(x) - actual_fn(x))) for x in R])
        bias_ci = _boot_diff(e_m)
        v = _verdict(*d, len(R), min_n)
        res["markets"][name] = {"n": len(R), "mae_model": mae_m, "mae_base": mae_b, "bias_model": bias_m,
                                "bias_model_ci": bias_ci[1:], "bias_base": bias_b, "dmae": d, "verdict": v}
        lines.append(f"{name:<34} n={len(R):5d} MAE {mae_m:.3f} vs base {mae_b:.3f}  dMAE {d[0]:+.4f} "
                     f"[{d[1]:+.4f},{d[2]:+.4f}]  bias {bias_m:+.3f} [{bias_ci[1]:+.3f},{bias_ci[2]:+.3f}] (base {bias_b:+.3f})  {v}")

    settled_total = lambda x: x["act"]["final_h"] + x["act"]["final_a"]
    reg_total = lambda x: x["act"]["reg_h"] + x["act"]["reg_a"]
    margin = lambda x: x["act"]["final_h"] - x["act"]["final_a"]
    point("total (settled, full game)", lambda x: x["mt"], lambda x: x["bt"], settled_total)
    point("total (regulation)", lambda x: x["mt"], lambda x: x["b"]["reg_total_mean"], reg_total)
    point("goal margin (full game)", lambda x: x["m"]["margin_mean"], lambda x: x["bm"], margin)
    point("P1 total goals", lambda x: x["m"]["p1_total_mean"], lambda x: x["b"]["p1_total_mean"],
          lambda x: x["act"]["p1_h"] + x["act"]["p1_a"])

    def prob(name, p_model, p_base, y_fn, p_book=None, extra_bases=None, filt=None):
        S = [x for x in R if (filt is None or filt(x)) and y_fn(x) is not None]
        if not S:
            return
        ent: Dict[str, Any] = {"n": len(S)}
        pm = [(x["date"], p_model(x), y_fn(x)) for x in S]
        ent["brier_model"] = statistics.fmean(_brier(p, y) for _, p, y in pm)
        ent["ll_model"] = statistics.fmean(_ll(p, y) for _, p, y in pm)
        ent["mean_p_model"] = statistics.fmean(p for _, p, _y in pm)
        ent["freq_y"] = statistics.fmean(y for _, _p, y in pm)
        bases = {"base_gfga": p_base}
        bases.update(extra_bases or {})
        msg = []
        for bn, fn in bases.items():
            d = _boot_diff([(x["date"], _brier(p_model(x), y_fn(x)) - _brier(fn(x), y_fn(x))) for x in S])
            dl = _boot_diff([(x["date"], _ll(p_model(x), y_fn(x)) - _ll(fn(x), y_fn(x))) for x in S])
            ent[f"vs_{bn}"] = {"brier": statistics.fmean(_brier(fn(x), y_fn(x)) for x in S), "d_brier": d, "d_ll": dl,
                                "verdict": _verdict(*d, len(S), min_n)}
            msg.append(f"vs {bn} dBrier {d[0]:+.4f} [{d[1]:+.4f},{d[2]:+.4f}] {ent[f'vs_{bn}']['verdict']}")
        if p_book is not None:
            SB = [x for x in S if p_book(x) is not None]
            ent["n_book"] = len(SB)
            if SB:
                d = _boot_diff([(x["date"], _brier(p_model(x), y_fn(x)) - _brier(p_book(x), y_fn(x))) for x in SB])
                dl = _boot_diff([(x["date"], _ll(p_model(x), y_fn(x)) - _ll(p_book(x), y_fn(x))) for x in SB])
                ent["vs_book"] = {"brier_model": statistics.fmean(_brier(p_model(x), y_fn(x)) for x in SB),
                                  "brier_book": statistics.fmean(_brier(p_book(x), y_fn(x)) for x in SB),
                                  "ll_model": statistics.fmean(_ll(p_model(x), y_fn(x)) for x in SB),
                                  "ll_book": statistics.fmean(_ll(p_book(x), y_fn(x)) for x in SB),
                                  "d_brier": d, "d_ll": dl, "verdict": _verdict(*d, len(SB), min_n)}
                msg.append(f"vs BOOK (n={len(SB)}) dBrier {d[0]:+.4f} [{d[1]:+.4f},{d[2]:+.4f}] dLL {dl[0]:+.4f} "
                           f"[{dl[1]:+.4f},{dl[2]:+.4f}] {ent['vs_book']['verdict']}")
        res["markets"][name] = ent
        lines.append(f"{name:<34} n={len(S):5d} Brier {ent['brier_model']:.4f} meanP {ent['mean_p_model']:.3f} freq {ent['freq_y']:.3f} | " + " | ".join(msg))

    hw = lambda x: 1 if x["act"]["final_h"] > x["act"]["final_a"] else 0
    bk = lambda key: (lambda x: x["book"].get(key))
    prob("ML home (raw model)", lambda x: x["m"]["p_home_ml"], lambda x: x["b"]["p_home_ml"], hw, bk("ml_home"),
         {"pts_log5": lambda x: x["pts_ml"], "const_home": lambda x: x["const_ml"]})
    prob("ML home (SERVED, anchored 0.35)", lambda x: x["s"]["p_home_ml"], lambda x: x["b"]["p_home_ml"], hw, bk("ml_home"),
         {"pts_log5": lambda x: x["pts_ml"]}, filt=lambda x: x["anchored"])
    reg = lambda side: (lambda x: 1 if ((x["act"]["reg_h"] > x["act"]["reg_a"]) if side == "h" else
                                        (x["act"]["reg_h"] == x["act"]["reg_a"]) if side == "t" else
                                        (x["act"]["reg_h"] < x["act"]["reg_a"])) else 0)
    prob("REG 3-way: home in 60", lambda x: x["m"]["p_reg_home"], lambda x: x["b"]["p_reg_home"], reg("h"))
    prob("REG 3-way: tie after 60", lambda x: x["m"]["p_reg_tie"], lambda x: x["b"]["p_reg_tie"], reg("t"))
    prob("REG 3-way: away in 60", lambda x: x["m"]["p_reg_away"], lambda x: x["b"]["p_reg_away"], reg("a"))
    for side, key in (("home", "p_home_m15"), ("away", "p_away_m15")):
        sgn = 1 if side == "home" else -1
        prob(f"PL {side} -1.5 (all games)", lambda x, k=key: x["m"][k], lambda x, k=key: x["b"][k],
             lambda x, s=sgn: 1 if s * (x["act"]["final_h"] - x["act"]["final_a"]) > 1.5 else 0)
    # puck line at the book's own number (home -1.5 or +1.5), model raw vs book
    prob("PL home @ book line", lambda x: x["m"].get("p_home_pl"), lambda x: x["b"].get("p_home_pl"),
         lambda x: (1 if (x["act"]["final_h"] - x["act"]["final_a"]) > -x["book"]["pl_line_home"] else 0),
         bk("p_home_pl"), filt=lambda x: x["book"].get("pl_line_home") is not None and x["m"].get("p_home_pl") is not None)
    # totals at the closing line: over and under scored SEPARATELY (bias per side); pushes excluded
    def tot_y(over):
        def f(x):
            L, t = x["book"]["total_line"], x["act"]["final_h"] + x["act"]["final_a"]
            if float(L).is_integer() and t == L:
                return None
            return int(t > L) if over else int(t < L)
        return f
    has_tl = lambda x: x["book"].get("total_line") is not None
    prob("OVER @ close (served: reg-only p)", lambda x: x["m"]["p_over_reg"], lambda x: x["b"]["p_over_full"],
         tot_y(True), bk("p_over"), filt=has_tl)
    prob("OVER @ close (OT-corrected p)", lambda x: x["m"]["p_over_full"], lambda x: x["b"]["p_over_full"],
         tot_y(True), bk("p_over"), filt=has_tl)
    prob("UNDER @ close (served: reg-only p)", lambda x: 1 - x["m"]["p_over_reg"], lambda x: 1 - x["b"]["p_over_full"],
         tot_y(False), (lambda x: None if x["book"].get("p_over") is None else 1 - x["book"]["p_over"]), filt=has_tl)
    for L in (5.5, 6.5):
        prob(f"OVER {L} (no book, reg-only p)", lambda x, L=L: x["m"][f"p_over_reg_{L}"], lambda x, L=L: x["b"][f"p_over_full_{L}"],
             lambda x, L=L: int(x["act"]["final_h"] + x["act"]["final_a"] > L))
        prob(f"OVER {L} (no book, OT-corrected p)", lambda x, L=L: x["m"][f"p_over_full_{L}"], lambda x, L=L: x["b"][f"p_over_full_{L}"],
             lambda x, L=L: int(x["act"]["final_h"] + x["act"]["final_a"] > L))
    prob("P1 over 0.5", lambda x: x["m"]["p1_over05"], lambda x: x["b"]["p1_over05"], lambda x: int(x["act"]["p1_h"] + x["act"]["p1_a"] > 0.5))
    prob("P1 over 1.5", lambda x: x["m"]["p1_over15"], lambda x: x["b"]["p1_over15"], lambda x: int(x["act"]["p1_h"] + x["act"]["p1_a"] > 1.5))
    prob("P1 3-way: tie", lambda x: x["m"]["p1_tie"], lambda x: x["b"]["p1_tie"], lambda x: int(x["act"]["p1_h"] == x["act"]["p1_a"]))
    # reliability of the served ML (deciles) for the report
    rel = defaultdict(lambda: [0, 0.0, 0])
    for x in R:
        p = x["m"]["p_home_ml"]
        bkt = min(9, int(p * 10))
        rel[bkt][0] += 1; rel[bkt][1] += p; rel[bkt][2] += hw(x)
    res["ml_raw_reliability"] = {k: {"n": v[0], "mean_p": v[1] / v[0], "freq": v[2] / v[0]} for k, v in sorted(rel.items())}
    res["reg_tie_rate"] = {"model_mean": statistics.fmean(x["m"]["p_reg_tie"] for x in R),
                           "actual": statistics.fmean(reg("t")(x) for x in R)}
    res["lines"] = lines
    return res


def write_md(rep: Dict, path: Path) -> None:
    L = ["# NHL game lines backtest (generated)", "", f"generated {rep['generated_utc']}", "",
         "## Coverage (per family, and the intersection each result rests on)", "",
         "| arm | finals (games/dates) | as-of projections | book closing | INTERSECTION | window |", "|---|---|---|---|---|---|"]
    for arm, c in rep["coverage"].items():
        L.append(f"| {arm} | {c['finals'][0]}/{c['finals'][1]} | {c['projections'][0]}/{c['projections'][1]} | "
                 f"{c['book'][0]}/{c['book'][1]} | {c['intersection'][0]}/{c['intersection'][1]} | {c['window'][0]}..{c['window'][1]} |")
    L += ["", f"drops: `{rep['drops']}`; degenerate dates: `{rep['degenerate_dates']}`; leak check: `{rep['leak_check']}`; "
          f"book join: `{rep['book_stats']}`", ""]
    for arm, r in rep["arms"].items():
        L += [f"## {arm} (n={r['n_games']} games)", "", "```"] + r["lines"] + ["```", "",
              f"regulation tie rate: model {r['reg_tie_rate']['model_mean']:.3f} vs actual {r['reg_tie_rate']['actual']:.3f}", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["actuals", "odds", "probe-periods", "sim", "score"])
    ap.add_argument("--out", default="C:/tmp/nhllines")
    ap.add_argument("--roots", default="C:/tmp/nhlprops/bt", help="backtest_nhl_props.py --out dir (as-of roots + game_index)")
    ap.add_argument("--src", default=None, help="<primary>/data/nhl_source (raw boxscores/landings); default via git")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--max-credits", type=int, default=30000)
    ap.add_argument("--events", type=int, default=5)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--min-n", type=int, default=100)
    ap.add_argument("--report", default=None)
    ap.add_argument("--quote-log", default=None, help="dir of fleet nhl book_quotes shards (read-only copy)")
    a = ap.parse_args()
    if a.src is None:
        a.src = str(_main_worktree() / "data" / "nhl_source")
    return {"actuals": cmd_actuals, "odds": cmd_odds, "probe-periods": cmd_probe, "sim": cmd_sim, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
