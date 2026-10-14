"""Buy the 2026 MLB REGULAR-SEASON prop closes from OddsAPI history (lane `signal-engine-mlb`).

User 2026-10-14: "Hits + TB + K" -- batter_hits, batter_total_bases, pitcher_strikeouts, one probe game first. The fleet
holds no multi-book 2026 regular-season MLB prop close (its quote logs start 2026-09-30; older snapshots kept one book).

  games    the hitting game log `mlb_player_game_log_2026_hitting.csv`, game_type R. DOUBLEHEADERS ARE EXCLUDED: two games
           share the date and the team pair, so a quote cannot be tied to its game by teams + date (the join that broke
           every doubleheader before, state [mlb-doubleheader-joins]); they are counted, not bought.
  events   one GET /historical/sports/baseball_mlb/events per game day at 12:00Z; a game joins the event with the same two
           canonical clubs whose commence_time falls between 12:00Z on its date and 12:00Z the next day.
  props    GET /historical/sports/baseball_mlb/events/<id>/odds, regions=us, 3 markets, at first pitch - 10 min:
           30 credits per game.
  safety   dry run unless --execute; --probe buys one day's events + one game's props and stops; --max-credits is a hard
           ceiling; 5 consecutive failures stop the run; failed calls are never cached; a re-run resumes. Quota headers
           are recorded under sport `mlb`.

    py -3 scripts/mlb_props_pull.py --game-log C:/tmp/mlb_props_2026/mlb_player_game_log_2026_hitting.csv            # dry run
    ODDS_API_KEY= py -3 scripts/mlb_props_pull.py --game-log ... --execute --probe
    ODDS_API_KEY= py -3 scripts/mlb_props_pull.py --game-log ... --execute --max-credits 76000
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import wnba_props_pull as W  # noqa: E402  -- the same OddsAPI getter and summary

SPORT = "baseball_mlb"
MARKETS = ("batter_hits", "batter_total_bases", "pitcher_strikeouts")
CREDITS_PER_GAME = 10 * len(MARKETS)
CLOSE_MINUTES = 10


def regular_season_games(game_log: Path) -> tuple[dict[str, dict[str, Any]], int]:
    """(game_pk -> {date, teams}, doubleheader games excluded) for regular-season games between two MLB clubs."""
    from syndicate.features.shared.team_aliases import canonical_team

    games: dict[str, dict[str, Any]] = {}
    with game_log.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("game_type") or "").strip().upper() != "R":
                continue
            teams = frozenset({canonical_team("mlb", r.get("team")), canonical_team("mlb", r.get("opponent"))})
            games.setdefault(str(r["game_pk"]), {"date": str(r["date"])[:10], "teams": teams})
    games = {g: v for g, v in games.items() if None not in v["teams"] and len(v["teams"]) == 2}
    per_day_pair = Counter((v["date"], v["teams"]) for v in games.values())
    doubleheaders = {g for g, v in games.items() if per_day_pair[(v["date"], v["teams"])] > 1}
    return {g: v for g, v in games.items() if g not in doubleheaders}, len(doubleheaders)


def match_event(game: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
    from syndicate.features.shared.team_aliases import canonical_team

    lo = datetime.fromisoformat(f"{game['date']}T12:00:00+00:00")
    hi = lo + timedelta(days=1)
    hits = []
    for ev in events:
        teams = frozenset({canonical_team("mlb", ev.get("home_team")), canonical_team("mlb", ev.get("away_team"))})
        try:
            start = datetime.fromisoformat(str(ev["commence_time"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if teams == game["teams"] and lo <= start < hi:
            hits.append(ev)
    return hits[0] if len(hits) == 1 else None  # two events for one pair in the window = an unlisted doubleheader: refuse


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game-log", required=True)
    ap.add_argument("--out", default="C:/tmp/mlb_props_2026")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--max-credits", type=int, default=76000)
    args = ap.parse_args(argv)
    out = Path(args.out)
    games, dh = regular_season_games(Path(args.game_log))
    by_day: dict[str, list[str]] = defaultdict(list)
    for gid, g in games.items():
        by_day[g["date"]].append(gid)
    todo = [gid for gid in sorted(games, key=lambda g: (games[g]["date"], g)) if not (out / "odds" / f"{gid}.json").exists()]
    days_needed = sorted({games[g]["date"] for g in todo if not (out / "events" / f"{games[g]['date']}.json").exists()})
    print(f"mlb 2026 regular season: {len(games)} games over {len(by_day)} days ({dh} doubleheader games excluded); "
          f"to fetch {len(todo)}; estimate {len(todo) * CREDITS_PER_GAME} props credits + ~{len(days_needed)} event calls",
          flush=True)
    if not args.execute or not todo:
        print("dry run -- pass --execute to spend" if not args.execute else "nothing to fetch", flush=True)
        return 0
    if args.probe:
        todo = [sorted(by_day[sorted(by_day)[len(by_day) // 2]])[0]]
    cap = min(args.max_credits, CREDITS_PER_GAME * 2 + 10) if args.probe else args.max_credits
    key, budget = W.BGL._api_key(), W.BGL.Budget(cap)
    (out / "events").mkdir(parents=True, exist_ok=True)
    (out / "odds").mkdir(parents=True, exist_ok=True)
    fails, no_event = 0, 0
    try:
        for i, gid in enumerate(todo):
            game = games[gid]
            ev_path = out / "events" / f"{game['date']}.json"
            if not ev_path.exists():
                evs = W._get(f"/historical/sports/{SPORT}/events", {"date": f"{game['date']}T12:00:00Z"}, key, budget, sport="mlb")
                if evs is None:
                    fails += 1
                    if fails >= 5:
                        raise SystemExit("stopped: 5 consecutive failed calls (dead key?)")
                    continue
                ev_path.write_text(json.dumps(evs), encoding="utf-8")
            ev = match_event(game, (json.loads(ev_path.read_text(encoding="utf-8")) or {}).get("data") or [])
            if ev is None:
                no_event += 1
                continue
            start = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            snap_at = (start - timedelta(minutes=CLOSE_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
            d = W._get(f"/historical/sports/{SPORT}/events/{ev['id']}/odds",
                       {"regions": "us", "markets": ",".join(MARKETS), "oddsFormat": "american", "date": snap_at},
                       key, budget, sport="mlb")
            if args.probe:
                print(f"PROBE game={gid} date={game['date']} event={ev['id']} ok={d is not None} credits_so_far={budget.spent} "
                      f"summary={json.dumps(W.summarize(d)) if d else None}", flush=True)
            if d is None:
                fails += 1
                if fails >= 5:
                    raise SystemExit("stopped: 5 consecutive failed calls (dead key?)")
                continue
            fails = 0
            (out / "odds" / f"{gid}.json").write_text(json.dumps({"game": gid, "date": game["date"],
                                                                  "start": ev["commence_time"], "event": ev["id"], "snap": d}),
                                                      encoding="utf-8")
            if i and i % 100 == 0:
                print(f"  {i}/{len(todo)} spent={budget.spent}", flush=True)
    finally:
        print(f"pull: spent {budget.spent} credits over {budget.calls} calls; games without a single event={no_event}; "
              f"header remaining present={budget.remaining is not None}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
