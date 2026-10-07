"""NCAAF data step, part 2 (lane `football-sim-player-attribution`): historical NCAAF player-prop quotes.

User approved the pull 2026-10-07 ("approve the NCAAF props pull"), sized by a pre-registered
11-credit probe (2024 archive confirmed; <= ~91k credits estimated for 2024 + 2025).

REUSES `backfill_nfl_historical_props`'s measured client (Budget ceiling, retries, quota
attribution) re-pointed at `americanfootball_ncaaf`. Differences, all deliberate:
  * credits are attributed to sport "ncaaf" in the quota ledger (the NFL module hard-codes "nfl");
  * games = CFBD FBS-vs-FBS REGULAR season, snapshot at kickoff - 10 min (the NFL convention);
  * output goes to a PRIVATE root, never the shared `data/ncaaf_source` mirror;
  * DRY RUN by default; `--execute` spends, `--max-credits` aborts mid-run, progress is
    checkpointed per event so a re-run never re-buys a snapshot.

    py -3 scripts/fetch_ncaaf_historical_props.py --seasons 2024,2025                    # dry run: plan + cost
    py -3 scripts/fetch_ncaaf_historical_props.py --seasons 2024,2025 --execute --max-credits 95000
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import backfill_nfl_historical_props as B  # noqa: E402

TRUTH = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\data\ncaaf_source\historical_truth")
OUT = Path(r"C:\tmp\football_scenarios\ncaaf_props")
ENV = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\.env")
OFFSET_MIN = 10
# The NCAAF markets books actually post (2026 wk1 capture: Anytime TD, Receiving Yards, Receptions,
# Rushing Yards, Passing Yards, Passing TDs) plus rush attempts; 7 x 10 credits per event.
NCAAF_MARKETS = ["player_pass_yds", "player_pass_tds", "player_rush_yds", "player_rush_attempts",
                 "player_reception_yds", "player_receptions", "player_anytime_td"]


def _configure() -> None:
    B.SPORT = "americanfootball_ncaaf"
    B.PLAYER_MARKETS = list(NCAAF_MARKETS)

    def _record(headers: Dict[str, str], *, endpoint: str) -> None:
        try:
            from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota
            record_oddsapi_quota(headers, sport="ncaaf", endpoint=endpoint)
        except Exception:  # noqa: BLE001 -- instrumentation never breaks the fetch
            pass
    B._record_quota = _record


def _api_key() -> Optional[str]:
    # The .env key works; a shell-exported ODDS_API_KEY is known dead (2026-10-05), so .env wins here.
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("ODDS_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def games(seasons: List[int]) -> List[Dict[str, Any]]:
    out = []
    for season in seasons:
        for g in json.load(gzip.open(TRUTH / f"games_{season}.json.gz", "rt", encoding="utf-8")):
            if g.get("seasonType") != "regular" or g.get("homeClassification") != "fbs" \
                    or g.get("awayClassification") != "fbs" or not g.get("startDate"):
                continue
            ko = datetime.fromisoformat(str(g["startDate"]).replace("Z", "+00:00"))
            out.append({"season": season, "week": int(g.get("week") or 0), "game_id": int(g["id"]),
                        "home": g["homeTeam"], "away": g["awayTeam"], "kickoff": ko,
                        "snapshot": B._snapshot_for(ko, OFFSET_MIN)})
    return out


def _match(event: Dict[str, Any], g: Dict[str, Any]) -> bool:
    ct = B._parse_iso(event.get("commence_time"))
    if ct is None or abs((ct - g["kickoff"]).total_seconds()) > 3 * 3600:
        return False
    h = str(event.get("home_team") or "").lower()
    a = str(event.get("away_team") or "").lower()
    return h.startswith(g["home"].lower()) and a.startswith(g["away"].lower())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", required=True)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--max-credits", type=int, default=0)
    args = ap.parse_args()
    from scripts.football_scenario_rates import idle_self
    idle_self()   # fleet shares this machine
    seasons = [int(s) for s in args.seasons.split(",")]
    _configure()
    gl = games(seasons)
    snaps = defaultdict(list)
    for g in gl:
        snaps[g["snapshot"]].append(g)
    per_game = len(NCAAF_MARKETS) * B.CREDITS_PER_MARKET_REGION
    OUT.mkdir(parents=True, exist_ok=True)
    state_path = OUT / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"done": {}, "snapshots": {}}
    todo_games = [g for g in gl if str(g["game_id"]) not in state["done"]]
    print(f"NCAAF FBS-vs-FBS REG games {len(gl)} ({', '.join(str(s) + ': ' + str(sum(1 for g in gl if g['season'] == s)) for s in seasons)}), "
          f"{len(snaps)} distinct snapshots, {len(todo_games)} not yet fetched")
    print(f"upper bound: {len(snaps)} event-list calls x 1 + {len(todo_games)} games x {per_game} = "
          f"{len(snaps) + len(todo_games) * per_game:,} credits (games without props cost less)")
    if not args.execute:
        print("DRY RUN -- nothing spent. Add --execute --max-credits N to fetch.")
        return 0
    key = _api_key()
    if not key:
        print("ERROR: no ODDS_API_KEY in .env")
        return 2
    budget = B.Budget(args.max_credits)
    n_events = n_quotes = n_unmatched = 0
    try:
        for snap, gs in sorted(snaps.items()):
            pending = [g for g in gs if str(g["game_id"]) not in state["done"]]
            if not pending:
                continue
            events = B._events_at(snap, api_key=key, budget=budget)
            for g in pending:
                ev = next((e for e in events if _match(e, g)), None)
                if ev is None:
                    state["done"][str(g["game_id"])] = {"status": "no_event_match"}
                    n_unmatched += 1
                    continue
                data = B._event_props(str(ev["id"]), snap, api_key=key, budget=budget)
                quotes = []
                if data:
                    _rows, quotes = B.rows_from_event(data)
                    for q in quotes:
                        q.update(sport="ncaaf", season=g["season"], week=g["week"], cfbd_game_id=g["game_id"],
                                 snapshot_ts=snap)
                    with (OUT / f"quotes_{g['season']}_wk{g['week']:02d}.jsonl").open("a", encoding="utf-8") as fh:
                        for q in quotes:
                            fh.write(json.dumps(q) + "\n")
                state["done"][str(g["game_id"])] = {"status": "ok" if quotes else "no_props", "quotes": len(quotes),
                                                    "event_id": ev["id"]}
                n_events += 1
                n_quotes += len(quotes)
            state_path.write_text(json.dumps(state), encoding="utf-8")
            if budget.calls % 50 == 0:
                print(f"  ... spent {budget.spent:,} credits, {n_events} events, {n_quotes:,} quotes, "
                      f"remaining {budget.remaining_reported}", flush=True)
    except B.CreditCeiling as exc:
        print(f"STOPPED: {exc}")
    finally:
        state_path.write_text(json.dumps(state), encoding="utf-8")
    with_props = sum(1 for v in state["done"].values() if v.get("status") == "ok")
    print(f"done: spent {budget.spent:,} credits in {budget.calls} calls; events {n_events}, quotes {n_quotes:,}, "
          f"unmatched {n_unmatched}; games with props (all runs) {with_props}; remaining {budget.remaining_reported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
