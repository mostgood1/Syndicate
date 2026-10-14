"""Buy the 2025-26 NHL regular-season SKATER prop closes from OddsAPI history (lane `signal-engine-nhl`).

User 2026-10-14: "yes buy the 2025-26 skater props, probe one game first". The discovery season for the K1-K5 skater
signals (the fleet holds no skater prop price before 2026-27).

  per game   GET /historical/sports/icehockey_nhl/events/<id>/odds, regions=us, markets = shots on goal, points,
             assists, goals (O/U), at start - 10 min -- the same close the forward grader (`grade_nhl_forward.py`) uses.
             OddsAPI bills historical event odds at 10 credits per market per region: 40 per game.
  events     from the closing game-line snapshots already bought (`<out>/odds/<start>.json`) via
             `backtest_nhl_game_lines._event_for` -- no events call is spent.
  safety     dry run unless --execute; --probe buys exactly ONE game and stops; --max-credits is a hard ceiling
             (`Budget` raises past it); 5 consecutive failures stop the run; failed calls are never cached; cached
             games are never re-bought, so a re-run resumes. Quota is recorded per call (`record_oddsapi_quota`).

    py -3 scripts/nhl_skater_props_pull.py                                  # dry run: games, estimate
    ODDS_API_KEY= py -3 scripts/nhl_skater_props_pull.py --execute --probe  # one game
    ODDS_API_KEY= py -3 scripts/nhl_skater_props_pull.py --execute --max-credits 55000
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
_spec = importlib.util.spec_from_file_location("_bgl", REPO / "scripts" / "backtest_nhl_game_lines.py")
BGL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BGL)

MARKETS = ("player_shots_on_goal", "player_points", "player_assists", "player_goals")
CREDITS_PER_GAME = 10 * len(MARKETS)
CLOSE_MINUTES = 10


def todo_games(out: Path) -> tuple[list[tuple], dict[str, int]]:
    act = json.loads((out / "actuals.json").read_text(encoding="utf-8"))
    cache = out / "odds_skater_props"
    todo, counts = [], Counter()
    for gid in sorted(act):
        if act[gid].get("arm") != "regular" or not str(gid).startswith("202502"):
            continue
        counts["regular_season_games"] += 1
        if (cache / f"{gid}.json").exists():
            counts["cached"] += 1
            continue
        hit = BGL._event_for(act, gid, out)
        if hit is None:
            counts["no_event"] += 1
            continue
        todo.append((gid, *hit))
    return todo, dict(counts)


def summarize(snap: dict) -> dict:
    data = (snap or {}).get("data") or {}
    books, outcomes = set(), Counter()
    for b in data.get("bookmakers") or []:
        for m in b.get("markets") or []:
            books.add(b.get("key"))
            outcomes[m.get("key")] += len(m.get("outcomes") or [])
    return {"timestamp": (snap or {}).get("timestamp"), "books": sorted(books), "outcomes_by_market": dict(outcomes)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="C:/tmp/nhllines")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--probe", action="store_true", help="buy exactly one game, report, stop")
    ap.add_argument("--max-credits", type=int, default=55000)
    args = ap.parse_args(argv)
    out = Path(args.out)
    todo, counts = todo_games(out)
    print(f"skater props: {counts}; to fetch {len(todo)}; estimate {len(todo) * CREDITS_PER_GAME} credits "
          f"({len(MARKETS)} markets x 1 region x 10)", flush=True)
    if not args.execute or not todo:
        print("dry run -- pass --execute to spend" if not args.execute else "nothing to fetch", flush=True)
        return 0
    if args.probe:
        todo = todo[len(todo) // 2: len(todo) // 2 + 1]  # one mid-season game
    cap = min(args.max_credits, CREDITS_PER_GAME * 2) if args.probe else args.max_credits
    key, budget = BGL._api_key(), BGL.Budget(cap)
    cache = out / "odds_skater_props"
    cache.mkdir(parents=True, exist_ok=True)
    fails = 0
    try:
        for i, (gid, start, sport, ev) in enumerate(todo):
            d = BGL._odds_get(f"/historical/sports/{sport}/events/{ev['id']}/odds",
                              {"regions": "us", "markets": ",".join(MARKETS), "oddsFormat": "american",
                               "date": BGL._snap_time(start, minutes=CLOSE_MINUTES)}, key, budget)
            if args.probe:
                print(f"PROBE game={gid} start={start} event={ev['id']} ok={d is not None} "
                      f"credits_this_call={budget.spent} summary={json.dumps(summarize(d)) if d else None}", flush=True)
            if d is None:
                fails += 1
                if fails >= 5:
                    raise SystemExit(f"stopped: {fails} consecutive failed calls (dead key?)")
                continue
            fails = 0
            (cache / f"{gid}.json").write_text(json.dumps({"start": start, "event": ev["id"], "snap": d}), encoding="utf-8")
            if i and i % 100 == 0:
                print(f"  {i}/{len(todo)} spent={budget.spent}", flush=True)
    finally:
        print(f"pull: spent {budget.spent} credits over {budget.calls} calls; header remaining present="
              f"{budget.remaining is not None}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
