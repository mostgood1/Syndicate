"""NHL goalie SAVES: production-form projection vs the de-vigged book (lane `nhl-saves-skill-registry`).

The board's skill registry (`measured_market_skill`) only takes a measurement against the de-vigged market, and no
NHL saves line was ever captured before 2026-10-05. This buys the historical closes and scores them.

  pull   OddsAPI historical per-event `player_total_saves` at the game's other closes' snapshot time (3 min before
         start), for every game on the props-harness dates. 10 credits per event. Dry run unless --execute; one probe
         call first (status + cost only); failed calls are never cached; stops after 5 consecutive failures.
  score  Per (game, goalie, line): book over/under de-vigged per book (proportional, two-sided only), averaged over
         books = the market's P(over). Model P(over) = production's price, Poisson at the line from the SAVES
         `proj_lambda` of the props-harness arm `prior_dfo` (current engine + Daily Faceoff confirmed starters).
         Population = what production prices: the sim's starter (`sim_starter`), who actually played. Brier
         model - market with a GAME-clustered bootstrap 95% CI.

Usage:
  py -3 scripts/nhl_saves_vs_book.py pull            # dry run: events, estimate
  ODDS_API_KEY= py -3 scripts/nhl_saves_vs_book.py pull --execute --max-credits 5000
  py -3 scripts/nhl_saves_vs_book.py score
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import pickle
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
_spec = importlib.util.spec_from_file_location("_bgl", REPO / "scripts" / "backtest_nhl_game_lines.py")
BGL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BGL)

MARKET = "player_total_saves"


def sim_games(sims: Path) -> Dict[str, Dict]:
    """gid -> {date, goalies: [{pid, name, team, lam, sim_starter}]} from the harness arm's sim files."""
    out = {}
    for f in sorted(sims.glob("regular_*.json")):
        res = json.loads(f.read_text(encoding="utf-8"))
        for g in res.get("games") or []:
            gl = []
            for p in g.get("players") or []:
                if p.get("pos") == "G":
                    lam = ((p.get("m") or {}).get("SAVES") or {}).get("lam")
                    gl.append({"pid": int(p["pid"]), "name": p.get("name"), "team": p.get("team"),
                               "lam": lam, "sim_starter": bool(p.get("sim_starter"))})
            out[str(g["gid"])] = {"date": res["date"], "goalies": gl}
    return out


def cmd_pull(a) -> int:
    out = Path(a.out)
    act = json.loads((out / "actuals.json").read_text(encoding="utf-8"))
    games = sim_games(Path(a.sims))
    cache = out / "odds_saves"
    todo, cached, unmatched = [], 0, 0
    for gid in sorted(games):
        if gid not in act:
            unmatched += 1
            continue
        if (cache / f"{gid}.json").exists():
            cached += 1
            continue
        hit = BGL._event_for(act, gid, out)
        if hit is None:
            unmatched += 1
            continue
        todo.append((gid, *hit))
    print(f"pull: {len(games)} harness games, {len(todo)} to fetch, {cached} cached, {unmatched} unmatched; "
          f"estimate {len(todo) * 10} credits", flush=True)
    if not a.execute or not todo:
        print("dry run -- pass --execute to spend" if not a.execute else "nothing to fetch")
        return 0
    key, budget = BGL._api_key(), BGL.Budget(a.max_credits)
    cache.mkdir(parents=True, exist_ok=True)
    fails = 0
    try:
        for i, (gid, start, sport, ev) in enumerate(todo):
            d = BGL._odds_get(f"/historical/sports/{sport}/events/{ev['id']}/odds",
                              {"regions": "us", "markets": MARKET, "oddsFormat": "american", "date": BGL._snap_time(start)},
                              key, budget)
            if i == 0:
                print(f"probe: {'ok' if d is not None else 'FAILED'}; spent {budget.spent} after 1 call", flush=True)
            if d is None:
                fails += 1
                if fails >= 5:
                    raise SystemExit(f"pull: {fails} consecutive failed calls -- stopped (dead key?)")
                continue
            fails = 0
            (cache / f"{gid}.json").write_text(json.dumps({"start": start, "event": ev["id"], "snap": d}), encoding="utf-8")
            if i % 100 == 0:
                print(f"  {i}/{len(todo)} spent={budget.spent}", flush=True)
    finally:
        print(f"pull: spent {budget.spent} credits over {budget.calls} calls; header remaining={budget.remaining}", flush=True)
    return 0


def _p_over(line: float, lam: float) -> float:
    lam = max(0.0, float(lam))
    return max(0.0, min(1.0, 1.0 - sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(int(math.floor(line)) + 1))))


def book_lines(snap: Optional[Dict]) -> Dict[Tuple[str, float], List[float]]:
    """(player, line) -> [de-vigged P(over) per book quoting both sides]."""
    from syndicate.features.nhl.sim_engine.hockeysim.adapters import american_to_implied
    per = defaultdict(list)
    for b in ((snap or {}).get("data") or {}).get("bookmakers") or []:
        for m in b.get("markets") or []:
            if m.get("key") != MARKET:
                continue
            sides = defaultdict(dict)
            for o in m.get("outcomes") or []:
                if o.get("point") is None or o.get("price") is None:
                    continue
                sides[(str(o.get("description") or ""), float(o["point"]))][str(o.get("name") or "").lower()] = o["price"]
            for k, s in sides.items():
                if "over" in s and "under" in s:
                    io, iu = american_to_implied(s["over"]), american_to_implied(s["under"])
                    if io + iu > 0:
                        per[k].append(io / (io + iu))
    return per


def cmd_score(a) -> int:
    from syndicate.features.nhl.confirmed_goalies import name_key
    out = Path(a.out)
    games = sim_games(Path(a.sims))
    acts = pickle.load(open(a.records, "rb"))["actuals"]
    rows, why = [], Counter()
    for gid, g in games.items():
        f = out / "odds_saves" / f"{gid}.json"
        if not f.exists():
            why["no_odds_file"] += 1
            continue
        lines = book_lines(json.loads(f.read_text(encoding="utf-8")).get("snap"))
        if not lines:
            why["game_without_saves_lines"] += 1
            continue
        played = {p["pid"]: p for p in (acts.get(gid) or {}).get("players", []) if p["pos"] == "G" and p["toi"] > 0}
        for (player, line), ps in lines.items():
            hits = [x for x in g["goalies"] if name_key(x["name"]) == name_key(player)]
            if len(hits) != 1:
                why["name_unmatched"] += 1
                continue
            gk = hits[0]
            if not gk["sim_starter"] or gk["lam"] is None:
                why["not_sim_starter (production refuses)"] += 1
                continue
            if gk["pid"] not in played:
                why["did_not_play (book voids)"] += 1
                continue
            y = 1 if played[gk["pid"]]["sv"] > line else 0
            pm, pk = _p_over(line, gk["lam"]), sum(ps) / len(ps)
            rows.append({"gid": gid, "date": g["date"], "line": line, "y": y, "pm": pm, "pk": pk, "books": len(ps)})
            why["scored"] += 1
    n = len(rows)
    print(f"score: {dict(why)}")
    if n < 100:
        print(f"REFUSED: only {n} player-game-lines joined (< 100)")
        return 1
    bm = sum((r["pm"] - r["y"]) ** 2 for r in rows) / n
    bk = sum((r["pk"] - r["y"]) ** 2 for r in rows) / n
    by_game = defaultdict(list)
    for r in rows:
        by_game[r["gid"]].append((r["pm"] - r["y"]) ** 2 - (r["pk"] - r["y"]) ** 2)
    gids = sorted(by_game)
    rng = random.Random(17)
    boots = []
    for _ in range(4000):
        s = c = 0
        for gid in (rng.choice(gids) for _ in gids):
            s += sum(by_game[gid]); c += len(by_game[gid])
        boots.append(s / c)
    boots.sort()
    lo, hi = boots[100], boots[3899]
    verdict_class = "beats_market" if hi < 0 else ("loses_to_market" if lo > 0 else "parity")
    res = {"n": n, "games": len(gids), "dates": len({r["date"] for r in rows}), "brier_model": round(bm, 5),
           "brier_market": round(bk, 5), "diff": round(bm - bk, 5), "ci95": [round(lo, 5), round(hi, 5)],
           "verdict_class": verdict_class, "mean_books": round(sum(r["books"] for r in rows) / n, 2),
           "over_rate": round(sum(r["y"] for r in rows) / n, 4), "mean_pm": round(sum(r["pm"] for r in rows) / n, 4),
           "mean_pk": round(sum(r["pk"] for r in rows) / n, 4), "exclusions": dict(why)}
    (out / "saves_vs_book.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pull", "score"])
    ap.add_argument("--out", default="C:/tmp/nhllines")
    ap.add_argument("--sims", default="C:/tmp/nhllines/props_ab_v2/prior_dfo/sim")
    ap.add_argument("--records", default="C:/tmp/nhlprops/bt_lqp_0.5/records.pkl")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--max-credits", type=int, default=5000)
    a = ap.parse_args()
    return {"pull": cmd_pull, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
