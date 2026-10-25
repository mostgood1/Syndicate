"""Test C: late-game in-play cells on Kalshi (lane in-game-trading). Read-only, paper/shadow.

PRE-REGISTERED in .syndicate/findings_2026-10-20_in_game_trading.md section 11 (locked 2026-10-24T23:55Z,
commit 03741657) from pm-trader-research's Test C. The rules below are that section's, verbatim in code:

  Window W, from ESPN's latest row at or before the quote: NHL period 3 clock <= 10:00, NBA period 4
  <= 6:00, NFL/NCAAF period 4 <= 8:00; any overtime period counts.
  C2 buy:  per (ticker, leg), FIRST quote in W with ask in [0.85, 0.97): won - ask - fee.
  C1 (a):  per (ticker, leg), FIRST quote in W with ask < 0.25: won - ask - fee (population buy check).
  C1 (b):  same quote, the EXIT value of holding it: (bid - fee(bid)) - won (positive = selling beats holding).
  C1 (c):  (b) restricted to legs we held live at that moment (`--held`, an export of filled Kalshi rows).
  fee = 0.07 * p * (1 - p) (the locked formula); a 1-contract round-up-to-the-cent fee is a sensitivity row.
  One mean per GAME; game-clustered bootstrap 95% CI (2,000 draws, seed 20261024).
  GO: pooled CI lower > 0 at >= 60 games AND mean > 0 in >= 2 of the 3 sports with >= 20 games.
  KILL: pooled CI upper < 0 at >= 60 games. C2 tail flag: a game loss > 10x the cell mean gain inside
  the first 60 games by date (reported, not decided on). < 60 games: INSUFFICIENT.

R3 (findings section 14, locked 2026-10-25, commit 679bd119; user decision via coordinator 332cb014): PAPER cell,
  95-99c in-play MONEYLINE favourites. In play = ESPN's latest row at or before the quote has state "in".
  ONE entry per game: the first quote across the game's KX*GAME tickers and legs with ask in [0.95, 0.99).
  Return = won - ask - fee (formula; 1-contract round-up as sensitivity). GO: >= 150 games, CI lower > 0,
  and CI lower > 0 with NFL excluded (NFL alone reported). KILL: CI upper < 0 or loss rate > 3% at >= 150 games.

Usage:  py -3 scripts/inplay_late_cells.py --nights C:/tmp/inplay_2026-10-2* [--held held.json] [--json-out x.json]
"""

from __future__ import annotations

import argparse
import bisect
import importlib.util
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("inplay_dip_study", ROOT / "scripts" / "inplay_dip_study.py")
dip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dip)

FINAL = {"nhl": (3, 600), "nba": (4, 360), "nfl": (4, 480), "ncaaf": (4, 480)}  # (final period, seconds left)
C2_BAND = (0.85, 0.97)
R3_BAND = (0.95, 0.99)
R3_MIN_GAMES = 150
R3_MAX_LOSS_RATE = 0.03
C1_MAX = 0.25
MIN_GAMES = 60
SPORT_MIN = 20
DRAWS = 2000
SEED = 20261024


def fee_formula(p: float) -> float:
    return 0.07 * p * (1 - p)


def fee_one_contract(p: float) -> float:
    return math.ceil(round(0.07 * p * (1 - p) * 100, 6)) / 100


def clock_s(raw) -> float | None:
    s = str(raw or "").strip()
    try:
        if ":" in s:
            m, sec = s.split(":", 1)
            return int(m) * 60 + float(sec)
        return float(s)
    except ValueError:
        return None


def espn_state(d: Path, sports):
    """(sport, abbr-set) -> sorted [(t, in_play)] over EVERY ESPN row (pre / in / post)."""
    out = defaultdict(list)
    for line in open(d / "espn.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("sport") not in sports:
            continue
        ab = tuple(sorted((x.get("abbr") or "") for x in r.get("teams") or []))
        out[(r["sport"], ab)].append((dip.ts(r["ts"]), r.get("state") == "in"))
    for k in out:
        out[k].sort()
    return out


def in_play(states, t) -> bool:
    if not states:
        return False
    i = bisect.bisect_right([x[0] for x in states], t) - 1
    return i >= 0 and states[i][1]


def r3_verdict(s: dict) -> str:
    p = s["pooled"]
    if p["games"] < R3_MIN_GAMES or p["ci95"] is None:
        return f"INSUFFICIENT ({p['games']}/{R3_MIN_GAMES} games)"
    if p["ci95"][1] < 0 or s.get("loss_rate", 0) > R3_MAX_LOSS_RATE:
        return f"KILL (CI upper {p['ci95'][1]:+.4f}, loss rate {s.get('loss_rate', 0):.3f})"
    ex = s.get("ex_nfl") or {}
    if p["ci95"][0] > 0 and ex.get("ci95") and ex["ci95"][0] > 0:
        return "GO (paper only)"
    return "NO-GO (CI spans 0, or not with NFL excluded)"


def espn_clock(d: Path, sports):
    """(sport, abbr-set) -> sorted [(t, period, seconds_left)] while in progress."""
    out = defaultdict(list)
    for line in open(d / "espn.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("sport") not in sports or r.get("state") != "in":
            continue
        ab = tuple(sorted((x.get("abbr") or "") for x in r.get("teams") or []))
        c = clock_s(r.get("clock"))
        try:
            p = int(r.get("period") or 0)
        except (TypeError, ValueError):
            continue
        if c is not None:
            out[(r["sport"], ab)].append((dip.ts(r["ts"]), p, c))
    for k in out:
        out[k].sort()
    return out


def in_window(clk, t, sport) -> bool:
    if not clk:
        return False
    i = bisect.bisect_right([x[0] for x in clk], t) - 1
    if i < 0:
        return False
    _, p, c = clk[i]
    final, left = FINAL[sport]
    return p > final or (p == final and c <= left)


def game_ci(game_means: list[float]):
    if len(game_means) < 2:
        return None
    rng = random.Random(SEED)
    n = len(game_means)
    boots = sorted(statistics.mean(rng.choices(game_means, k=n)) for _ in range(DRAWS))
    return boots[int(0.025 * DRAWS)], boots[int(0.975 * DRAWS) - 1]


def summarise(rows: list[dict], value: str) -> dict:
    """rows: one per entry with game, sport, date, and `value`. Returns pooled + per-sport per-game stats."""
    by_game = defaultdict(list)
    meta = {}
    for r in rows:
        by_game[r["game"]].append(r[value])
        meta[r["game"]] = (r["sport"], r["date"])
    means = {g: statistics.mean(v) for g, v in by_game.items()}

    def block(games):
        vals = [means[g] for g in games]
        ci = game_ci(vals)
        return {"games": len(vals), "entries": sum(len(by_game[g]) for g in games),
                "mean": round(statistics.mean(vals), 4) if vals else None,
                "ci95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
                "games_positive": sum(v > 0 for v in vals)}

    out = {"pooled": block(list(means)), "by_sport": {}}
    for sport in sorted({m[0] for m in meta.values()}):
        out["by_sport"][sport] = block([g for g in means if meta[g][0] == sport])
    out["_game_means_by_date"] = [means[g] for g in sorted(means, key=lambda g: (meta[g][1], g))]
    return out


def verdict(s: dict, tail_check: bool = False) -> str:
    p = s["pooled"]
    if p["games"] < MIN_GAMES or p["ci95"] is None:
        return f"INSUFFICIENT ({p['games']}/{MIN_GAMES} games)"
    if p["ci95"][1] < 0:
        v = "KILL (CI upper < 0)"
    else:
        sports_ok = [sp for sp, b in s["by_sport"].items() if b["games"] >= SPORT_MIN]
        positive = [sp for sp in sports_ok if (s["by_sport"][sp]["mean"] or 0) > 0]
        v = "GO" if p["ci95"][0] > 0 and len(positive) >= 2 else "NO-GO (CI spans 0 or < 2 sports positive)"
    if tail_check and p["mean"] and p["mean"] > 0:
        first = s["_game_means_by_date"][:MIN_GAMES]
        worst = min(first) if first else 0
        if worst < -10 * p["mean"]:
            v += f"; TAIL FLAG worst game {worst:+.3f} > 10x mean gain"
    return v


def idle() -> None:
    """Research job on a host the fleet shares: Idle priority (Windows) / nice 19."""
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x40)
    except (AttributeError, OSError):
        import os

        os.nice(19)


def main():
    idle()
    ap = argparse.ArgumentParser()
    ap.add_argument("--nights", nargs="+", required=True)
    ap.add_argument("--sports", default="nhl,nba,nfl,ncaaf")
    ap.add_argument("--held", help="JSON list of {ticker, leg, submitted_at} filled live Kalshi rows")
    ap.add_argument("--json-out")
    a = ap.parse_args()
    sports = [s for s in a.sports.split(",") if s]
    held = defaultdict(list)
    if a.held:
        for r in json.loads(Path(a.held).read_text(encoding="utf-8")):
            if r.get("leg") in ("yes", "no") and r.get("submitted_at"):
                held[(r["ticker"], r["leg"])].append(datetime.fromisoformat(r["submitted_at"].replace("Z", "+00:00")).timestamp())
    c2, c1, r3 = [], [], []
    nights = []
    for n in sorted(a.nights):
        d = Path(n)
        if not (d / "kalshi.jsonl").exists() or not (d / "espn.jsonl").exists():
            continue
        nights.append(d.name)
        clk = espn_clock(d, sports)
        states = espn_state(d, sports)
        r3_first: dict = {}
        for m in dip.load(d, sports):
            if m["res"] not in ("yes", "no"):
                continue
            key = next((k for k in clk if k[0] == m["sport"] and m["game"].endswith("|".join(k[1]))), None)
            if key is None:
                continue
            if m["fam"].endswith("GAME"):
                for leg in ("yes", "no"):
                    for t, mid, ask, bid in dip.leg_view(m["rows"], leg):
                        if R3_BAND[0] <= ask < R3_BAND[1] and in_play(states.get(key), t):
                            if m["game"] not in r3_first or t < r3_first[m["game"]][0]:
                                won = 1.0 if m["res"] == leg else 0.0
                                r3_first[m["game"]] = (t, {"game": m["game"], "sport": m["sport"], "date": d.name,
                                                           "ticker": m["ticker"], "leg": leg, "ask": ask, "won": won,
                                                           "ret": won - ask - fee_formula(ask),
                                                           "ret_1c": won - ask - fee_one_contract(ask)})
                            break
            for leg in ("yes", "no"):
                won = 1.0 if m["res"] == leg else 0.0
                got_c2 = got_c1 = False
                for t, mid, ask, bid in dip.leg_view(m["rows"], leg):
                    if got_c2 and got_c1:
                        break
                    if not (0 < ask < 1) or not in_window(clk[key], t, m["sport"]):
                        continue
                    base = {"game": m["game"], "sport": m["sport"], "date": d.name, "ticker": m["ticker"], "leg": leg}
                    if not got_c2 and C2_BAND[0] <= ask < C2_BAND[1]:
                        got_c2 = True
                        c2.append({**base, "ask": ask, "ret": won - ask - fee_formula(ask),
                                   "ret_1c": won - ask - fee_one_contract(ask)})
                    if not got_c1 and ask < C1_MAX:
                        got_c1 = True
                        b = bid if 0 < bid < 1 else None
                        was_held = any(s < t for s in held.get((m["ticker"], leg), []))
                        c1.append({**base, "ask": ask, "bid": b, "held": was_held,
                                   "buy": won - ask - fee_formula(ask),
                                   "exit": None if b is None else (b - fee_formula(b)) - won,
                                   "exit_1c": None if b is None else (b - fee_one_contract(b)) - won})
        r3.extend(row for _t, row in r3_first.values())
    c1x = [r for r in c1 if r["exit"] is not None]
    res = {
        "nights": nights,
        "C2_buy_85_97": summarise(c2, "ret"), "C2_buy_85_97_fee_1c": summarise(c2, "ret_1c"),
        "C1a_buy_under_25": summarise(c1, "buy"),
        "C1b_exit_under_25": summarise(c1x, "exit"), "C1b_exit_under_25_fee_1c": summarise(c1x, "exit_1c"),
        "C1c_exit_held": summarise([r for r in c1x if r["held"]], "exit"),
    }
    for name, value in (("R3_fav_95_99_ml", "ret"), ("R3_fav_95_99_ml_fee_1c", "ret_1c")):
        s3 = summarise(r3, value)
        s3["loss_rate"] = round(sum(r["won"] == 0 for r in r3) / len(r3), 4) if r3 else None
        s3["ex_nfl"] = summarise([r for r in r3 if r["sport"] != "nfl"], value)["pooled"]
        res[name] = s3
    print(f"Test C late-game cells (pre-registered, findings section 11). nights={nights}\n")
    for name, s in res.items():
        if name == "nights":
            continue
        p = s["pooled"]
        tail = name.startswith("C2")
        v = (r3_verdict(s) if name.startswith("R3") else verdict(s, tail)) if p["games"] else "no data"
        print(f"{name:28s} games={p['games']:3d} entries={p['entries']:4d} mean/game={p['mean']} ci95={p['ci95']}"
              f" games+={p['games_positive']}  -> {v}")
        if name.startswith("R3"):
            print(f"    loss_rate={s.get('loss_rate')}  ex-NFL: games={s['ex_nfl']['games']} mean={s['ex_nfl']['mean']}"
                  f" ci95={s['ex_nfl']['ci95']}")
        for sp, b in s["by_sport"].items():
            print(f"    {sp:6s} games={b['games']:3d} entries={b['entries']:4d} mean/game={b['mean']} ci95={b['ci95']} games+={b['games_positive']}")
    if a.json_out:
        for s in res.values():
            if isinstance(s, dict):
                s.pop("_game_means_by_date", None)
        Path(a.json_out).write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
