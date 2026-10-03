"""Measure: do NFL market-only (consensus-fair) edges REALIZE at the price that claims them?

Lane `nfl-off-market-edge` (2026-10-03). Measurement only.

WHAT EXISTS. Every Layer 2 row already carries a market-only `ev_pct`: the best bettable price vs the
multi-book de-vigged MEDIAN (`opportunity_signals.consensus_fair_probability`, multiplicative de-vig per
book, median, renormalised). The quoting book is INSIDE its own median (not leave-one-out), and stale
books enter it. Nothing has measured whether, for NFL, a positive `ev_pct` actually earns it.

WHAT THIS DOES, on as-of closing snapshots (kickoff - 10 min props, kickoff - 5 min game lines):
  for every (game, market, [player], line) and side: best price across books, and three fairs --
    board   consensus over ALL two-sided books (the board's own function, unmodified)
    loo     consensus over the OTHER books (the best-price book left out)
    fresh   game lines only: board consensus after dropping books whose last_update is > 900 s
            before the snapshot (the board's own `stale` threshold, book_grid.py:143); best price
            also restricted to fresh books
  A bet is taken on a side when its claimed EV > 0 under that definition, settled flat 1u at the best
  price, pushes void. Reported by claimed-EV band: n, games, mean claimed EV, realized ROI with a
  GAME-clustered bootstrap CI, and the realized-on-claimed slope (1 = edges are real; 0 = noise).

SPORTSBOOKS AS A PROXY. The 2023-25 history has no Kalshi/Polymarket quotes, so "the best price" is a
sportsbook's. That measures whether consensus-beating prices are real at the close; it is not a
measurement of exchange fills (those are forward-only, fleet capture since 2026-09-30).

Usage:
  py -3 scripts/measure_nfl_off_market_edge.py --root C:/tmp/nflbt/root/nfl_source \\
      --odds-dir C:/Users/.../data/nfl_source/historical_odds --out C:/tmp/nflbt/offmarket
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date as _date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("bt_lines_props", REPO / "scripts" / "backtest_nfl_lines_props.py")
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)  # type: ignore[union-attr]

BANDS = ((0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 10.0), (10.0, 1e9))
STALE_SECONDS = 900
MIN_BOOKS = 3   # two-sided books needed for a board consensus; loo then rests on >= 2 others


def _dec(price: Any) -> Optional[float]:
    return bt.american_to_dec(price)


def evaluate_group(prices_by_book: Dict[str, Dict[str, float]], *, outcome_side: Optional[str],
                   gid: str, kind: str, meta: Dict[str, Any], stale_books: Optional[set] = None) -> List[Dict[str, Any]]:
    """One line's bets under each definition. prices_by_book: {book: {side: american}}, two-sided books only."""
    from syndicate.features.shared.opportunity_signals import consensus_fair_probability, expected_value_pct
    out: List[Dict[str, Any]] = []
    books = [b for b, p in prices_by_book.items() if len(p) == 2]
    if len(books) < MIN_BOOKS or outcome_side is None:
        return out
    sides = sorted({s for b in books for s in prices_by_book[b]})
    if len(sides) != 2:
        return out
    full = {b: prices_by_book[b] for b in books}
    board = consensus_fair_probability(full)
    defs: List[Tuple[str, Dict[str, Dict[str, float]]]] = [("board", full)]
    if stale_books is not None:
        fresh = {b: p for b, p in full.items() if b not in stale_books}
        defs.append(("fresh", fresh))
    for side in sides:
        for name, pool in defs + [("loo", full)]:
            cand = {b: p for b, p in pool.items()}
            if len(cand) < (MIN_BOOKS if name != "loo" else MIN_BOOKS):
                continue
            best_book = max(cand, key=lambda b: (_dec(cand[b][side]) or 0.0))
            price = cand[best_book][side]
            if name == "loo":
                others = {b: p for b, p in cand.items() if b != best_book}
                fair = consensus_fair_probability(others) if len(others) >= MIN_BOOKS - 1 else None
            elif name == "fresh":
                fair = consensus_fair_probability(cand)
            else:
                fair = board
            if not fair or side not in fair:
                continue
            ev = expected_value_pct(price, fair[side])
            dec = _dec(price)
            if ev is None or dec is None or ev <= 0:
                continue
            won = outcome_side == side
            out.append({"gid": gid, "kind": kind, "def": name, "side": side, "book": best_book, "price": price,
                        "fair": fair[side], "ev": float(ev), "pnl": (dec - 1.0) if won else -1.0, "won": won,
                        "best_stale": (best_book in stale_books) if stale_books is not None else None, **meta})
    return out


# ---------------------------------------------------------------------------
# props
# ---------------------------------------------------------------------------

def prop_bets(root: Path, sched: Dict[str, Dict[str, Any]], seasons: List[int]) -> Tuple[List[Dict[str, Any]], Counter]:
    bt._patch_game_log_cache()
    from syndicate.features.nfl import player_stats as ps
    from syndicate.features.nfl import props as P
    from syndicate.features.shared.team_aliases import canonical_team

    quotes, _src = bt.load_quotes(root, [s for s in seasons if s <= 2025])
    ev_map, miss = bt.map_events(quotes, sched)
    drops = Counter({f"event_{k}": v for k, v in miss.items()})
    groups: Dict[Tuple, Dict[str, Dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for q in quotes:
        gid = ev_map.get((q["home"], q["away"], q["commence"]))
        if gid is None or not sched[gid]["completed"]:
            continue
        if q["market"] == "Anytime TD":
            drops["anytime_td_one_sided_skipped"] += 1
            continue
        if q["line"] is None or q["sel"] not in ("over", "under"):
            continue
        groups[(gid, q["market"], q["player"], q["line"])][q["book"]][q["sel"]] = q["price"]

    actual_cache: Dict[Tuple[str, str, str], Optional[float]] = {}

    def actual(gid: str, name: str, stat: str) -> Optional[float]:
        """Production's own identity path (resolve_player_id_with_prior + the team check), then the pbp value."""
        k = (gid, name, stat)
        if k in actual_cache:
            return actual_cache[k]
        g = sched[gid]
        season, week = g["season_i"], g["week_i"]
        val = None
        pid, _src2 = ps.resolve_player_id_with_prior(season, name)
        if pid is None:
            drops["player_unresolved"] += 1
        else:
            team, _ = ps.player_team_with_prior(season, week, pid)
            canon = canonical_team("nfl", team) if team else None
            if canon is None or canon not in {canonical_team("nfl", g["home_team"]), canonical_team("nfl", g["away_team"])}:
                drops["player_team_refused"] += 1
            else:
                val = ps.final_stat_value(season, gid, pid, stat)
                if val is None:
                    drops["no_pbp_line_void"] += 1
        actual_cache[k] = val
        return val

    bets: List[Dict[str, Any]] = []
    for (gid, market, player, line), by_book in groups.items():
        stat = P._NFL_PROP_MARKET_TO_STAT.get(market)
        if stat is None:
            continue
        a = actual(gid, player, stat)
        if a is None:
            continue
        if a == line:
            drops["push_void"] += 1
            continue
        side = "over" if a > line else "under"
        bets += evaluate_group(by_book, outcome_side=side, gid=gid, kind="prop",
                               meta={"season": sched[gid]["season_i"], "market": stat})
    drops["prop_lines_scored"] = len(groups)
    return bets, drops


# ---------------------------------------------------------------------------
# game lines
# ---------------------------------------------------------------------------

def game_bets(odds_dir: Path, sched: Dict[str, Dict[str, Any]], seasons: List[int]) -> Tuple[List[Dict[str, Any]], Counter]:
    from syndicate.features.shared.team_aliases import canonical_team
    drops = Counter()
    idx: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for g in sched.values():
        idx[(canonical_team("nfl", g["home_team"]), canonical_team("nfl", g["away_team"]))].append(g)
    bets: List[Dict[str, Any]] = []
    stale_counts = Counter()
    for s in seasons:
        p = odds_dir / f"closing_lines_{s}.json"
        if not p.exists():
            drops[f"no_closing_file_{s}"] += 1
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        events = doc.get("events") or doc.get("data") or []
        if isinstance(events, dict):          # the backfill writes {event_id: event}
            events = list(events.values())
        for ev in events:
            try:
                d = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).date()
                snap = datetime.fromisoformat(str(ev.get("snapshot_at") or ev["commence_time"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                drops["bad_event"] += 1
                continue
            home, away = ev.get("home_team"), ev.get("away_team")
            cands = [g for g in idx.get((canonical_team("nfl", home), canonical_team("nfl", away)), [])
                     if abs((_date.fromisoformat(g["gameday"]) - d).days) <= 1 and g["game_type"] == "REG"]
            if len(cands) != 1:
                drops["event_unmapped"] += 1
                continue
            g = cands[0]
            if not g["completed"]:
                continue
            hs, as_ = float(g["home_score"]), float(g["away_score"])
            groups: Dict[Tuple, Dict[str, Dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
            stale: set = set()
            for bk in ev.get("bookmakers") or []:
                key = bk.get("key")
                for mk in bk.get("markets") or []:
                    lu = mk.get("last_update") or bk.get("last_update")
                    try:
                        age = (snap - datetime.fromisoformat(str(lu).replace("Z", "+00:00"))).total_seconds()
                    except ValueError:
                        age = None
                    if age is not None and age > STALE_SECONDS:
                        stale.add((mk["key"], key))
                    for o in mk.get("outcomes") or []:
                        name, price, point = o.get("name"), o.get("price"), o.get("point")
                        if mk["key"] == "h2h":
                            side = "home" if canonical_team("nfl", name) == canonical_team("nfl", home) else "away"
                            groups[("h2h", None)][key][side] = price
                        elif mk["key"] == "spreads":
                            if point is None:
                                continue
                            side = "home" if canonical_team("nfl", name) == canonical_team("nfl", home) else "away"
                            home_pt = point if side == "home" else -point     # the line in HOME terms
                            groups[("spreads", home_pt)][key][side] = price
                        elif mk["key"] == "totals":
                            if point is None:
                                continue
                            groups[("totals", point)][key][str(name).lower()] = price
            for (mkey, line), by_book in groups.items():
                if mkey == "h2h":
                    side = None if hs == as_ else ("home" if hs > as_ else "away")
                elif mkey == "spreads":
                    margin = hs + line - as_                     # home covers when margin + home_pt > 0
                    side = None if margin == 0 else ("home" if margin > 0 else "away")
                else:
                    tot = hs + as_
                    side = None if tot == line else ("over" if tot > line else "under")
                if side is None:
                    drops[f"{mkey}_push_void"] += 1
                    continue
                st = {b for (m, b) in stale if m == mkey}
                stale_counts[mkey] += len(st)
                bets += evaluate_group(by_book, outcome_side=side, gid=g["game_id"], kind="game",
                                       meta={"season": g["season_i"], "market": mkey}, stale_books=st)
    drops.update({f"stale_book_markets_{k}": v for k, v in stale_counts.items()})
    return bets, drops


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def slope_ci(rows: List[Dict[str, Any]], reps: int = 300) -> Dict[str, Any]:
    """OLS slope of realized pnl on claimed EV (as a fraction), game-clustered bootstrap."""
    import random

    def slope(rr):
        xs = [r["ev"] / 100.0 for r in rr]
        ys = [r["pnl"] for r in rr]
        if len(xs) < 30:
            return None
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else None
    b = slope(rows)
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r["gid"]].append(r)
    keys = list(by)
    rng = random.Random(13)
    bs = []
    for _ in range(reps):
        rr = [r for _k in range(len(keys)) for r in by[keys[rng.randrange(len(keys))]]]
        v = slope(rr)
        if v is not None:
            bs.append(v)
    bs.sort()
    return {"slope": None if b is None else round(b, 3),
            "ci95": [round(bs[int(0.025 * len(bs))], 3), round(bs[int(0.975 * len(bs)) - 1], 3)] if len(bs) >= 30 else None}


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"n": 0}
    roi = bt.boot_ci([(r["gid"], r["pnl"]) for r in rows])
    return {"n": len(rows), "games": len({r["gid"] for r in rows}),
            "mean_claimed_ev_pct": round(statistics.fmean(r["ev"] for r in rows), 3),
            "roi_pct": round(100 * roi[0], 3), "roi_ci95": [round(100 * roi[1], 3), round(100 * roi[2], 3)],
            "hit_rate": round(statistics.fmean(1.0 if r["won"] else 0.0 for r in rows), 4),
            "mean_fair": round(statistics.fmean(r["fair"] for r in rows), 4)}


def report(bets: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for kind in ("prop", "game"):
        K = [b for b in bets if b["kind"] == kind]
        for d in sorted({b["def"] for b in K}):
            D = [b for b in K if b["def"] == d]
            key = f"{kind}:{d}"
            out[key] = {"all": summarize(D), "slope_realized_on_claimed": slope_ci(D), "bands": {}, "by_season": {},
                        "by_market": {}}
            for lo, hi in BANDS:
                out[key]["bands"][f"{lo:g}-{hi:g}%" if hi < 1e8 else f">={lo:g}%"] = summarize([b for b in D if lo < b["ev"] <= hi])
            for s in sorted({b["season"] for b in D}):
                out[key]["by_season"][str(s)] = summarize([b for b in D if b["season"] == s])
            for m in sorted({b["market"] for b in D}):
                out[key]["by_market"][m] = summarize([b for b in D if b["market"] == m])
            if kind == "game" and d == "board":
                out[key]["best_book_stale"] = summarize([b for b in D if b["best_stale"]])
                out[key]["best_book_fresh"] = summarize([b for b in D if b["best_stale"] is False])
            books = Counter(b["book"] for b in D)
            out[key]["top_best_books"] = books.most_common(6)
    return out


def write_md(rep: Dict[str, Any], path: Path) -> None:
    L = ["# NFL off-market (consensus-fair) edge: does it realize?", "", f"generated {rep['generated_at']}", "",
         f"drops `{json.dumps(rep['drops'])}`", ""]
    for key, R in rep["results"].items():
        a, s = R["all"], R["slope_realized_on_claimed"]
        L += [f"## {key}", "", f"all: n {a.get('n')}, games {a.get('games')}, mean claimed EV {a.get('mean_claimed_ev_pct')}%, "
              f"realized ROI {a.get('roi_pct')}% {a.get('roi_ci95')}, slope realized-on-claimed {s['slope']} {s['ci95']}; "
              f"top best-price books {R['top_best_books']}", "",
              "| claimed EV band | n | games | mean claimed EV % | realized ROI % [CI] | hit | mean fair |", "|---|---|---|---|---|---|---|"]
        for b, v in R["bands"].items():
            if v.get("n"):
                L.append(f"| {b} | {v['n']} | {v['games']} | {v['mean_claimed_ev_pct']} | {v['roi_pct']} {v['roi_ci95']} | {v['hit_rate']} | {v['mean_fair']} |")
        L += ["", "| by season / market | n | mean claimed EV % | realized ROI % [CI] |", "|---|---|---|---|"]
        for grp in ("by_season", "by_market"):
            for k, v in R[grp].items():
                if v.get("n"):
                    L.append(f"| {k} | {v['n']} | {v['mean_claimed_ev_pct']} | {v['roi_pct']} {v['roi_ci95']} |")
        for k in ("best_book_stale", "best_book_fresh"):
            if k in R and R[k].get("n"):
                v = R[k]
                L.append(f"| {k} | {v['n']} | {v['mean_claimed_ev_pct']} | {v['roi_pct']} {v['roi_ci95']} |")
        L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--odds-dir", type=Path, required=True, help="dir holding closing_lines_<season>.json")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--prop-seasons", default="2023,2024,2025")
    ap.add_argument("--game-seasons", default="2022,2023,2024")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    env = bt.configure_env(a.root.resolve())
    sched = bt.load_schedule(a.root.resolve())
    pb, pd = prop_bets(a.root.resolve(), sched, [int(x) for x in a.prop_seasons.split(",") if x])
    gb, gd = game_bets(a.odds_dir, sched, [int(x) for x in a.game_seasons.split(",") if x])
    drops = Counter(pd)
    drops.update(gd)
    rep = {"generated_at": datetime.now(timezone.utc).isoformat(), "env": env, "drops": dict(drops),
           "n_bets": len(pb) + len(gb), "results": report(pb + gb)}
    (a.out / "nfl_off_market_edge.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    write_md(rep, a.out / "nfl_off_market_edge.md")
    print(json.dumps({k: {"n": v["all"].get("n"), "ev": v["all"].get("mean_claimed_ev_pct"), "roi": v["all"].get("roi_pct"),
                          "ci": v["all"].get("roi_ci95"), "slope": v["slope_realized_on_claimed"]} for k, v in rep["results"].items()}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
