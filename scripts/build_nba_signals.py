"""Build dated, as-of NBA matchup-signal tables (lane `signal-engine-nba`).

For every player-game, from games STRICTLY BEFORE that date: minutes trend (last 3 vs the 10 before), recent starts,
team rest days, and the pregame consensus |spread|. The registered firing rules
(`matchup_signals.nba_signal_fires`) are applied and stored with the features, one table per date under
`<data root>/nba_source/signals/<season>/<YYYY-MM-DD>.jsonl`.

SOURCES
  --logs-statsnba   stats.nba `playergamelogs` JSON (PLAYER_NAME, TEAM_NAME, GAME_ID, GAME_DATE, MIN). Regular season
                    only -- playoffs are a different population and are not mixed in.
  --logs-espn       ESPN-built player game log CSV (date, PLAYER_NAME, starter, MIN, TEAM_ABBREVIATION). Supplies the
                    start flags; with no stats.nba file it is also the minutes source (the forward 2026-27 path).
  --games-odds-dir  OddsAPI game snapshots `<dir>/<YYYY-MM-DD>.json` (spreads by full team name). Optional.

    # the 2025-26 backfill (discovery / confirmation set)
    python3 scripts/build_nba_signals.py --data-root ~/syndicate-prod/data --season 2025-26 \\
        --logs-statsnba ~/syndicate-prod/data/backfill/nba_props_2025_26/cache/statsnba/playergamelogs_2025-26_Regular_Season.json \\
        --logs-espn ~/syndicate-prod/data/nba_source/data/processed/player_game_log_2025.csv \\
        --games-odds-dir ~/syndicate-prod/data/backfill/nba_props_2025_26/cache/oddsapi_hist/games
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.matchup_signals import (  # noqa: E402
    minutes_features,
    nba_signal_fires,
    norm_player,
    start_features,
    team_rest_days,
    write_signal_table,
)


def _f(v: Any) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def load_statsnba(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rs = payload["resultSets"][0]
    idx = {h: i for i, h in enumerate(rs["headers"])}
    out = []
    for row in rs["rowSet"]:
        minutes = _f(row[idx["MIN"]])
        if minutes is None:
            continue
        out.append({"player": row[idx["PLAYER_NAME"]], "key": norm_player(row[idx["PLAYER_NAME"]]),
                    "team": row[idx["TEAM_NAME"]], "game_id": str(row[idx["GAME_ID"]]),
                    "date": str(row[idx["GAME_DATE"]])[:10], "min": minutes})
    return out


def load_espn(path: Path) -> tuple[list[dict[str, Any]], dict[tuple[str, str], int]]:
    logs, starts = [], {}
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("season_type") or "regular").lower() not in ("regular", "regular season", ""):
                continue
            key, day = norm_player(r.get("PLAYER_NAME")), str(r.get("date") or "")[:10]
            st = r.get("starter")
            if st not in (None, ""):
                starts[(key, day)] = 1 if str(st).strip() in ("1", "True", "true") else 0
            minutes = _f(r.get("MIN"))
            if minutes is not None:
                logs.append({"player": r.get("PLAYER_NAME"), "key": key, "team": r.get("TEAM_ABBREVIATION"),
                             "game_id": str(r.get("game_id") or ""), "date": day, "min": minutes})
    return logs, starts


def load_spreads(directory: Path | None) -> dict[tuple[str, str], float]:
    """(date, norm full team name) -> median |spread| across books at the snapshot."""
    out: dict[tuple[str, str], float] = {}
    if directory is None or not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        day = path.stem
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for game in payload.get("data") or []:
            pts: dict[str, list[float]] = defaultdict(list)
            for book in game.get("bookmakers") or []:
                for market in book.get("markets") or []:
                    if market.get("key") != "spreads":
                        continue
                    for o in market.get("outcomes") or []:
                        p = _f(o.get("point"))
                        if p is not None:
                            pts[norm_player(o.get("name"))].append(abs(p))
            for team, values in pts.items():
                out[(day, team)] = statistics.median(values)
    return out


def build(logs: list[dict[str, Any]], starts: dict[tuple[str, str], int],
          spreads: dict[tuple[str, str], float]) -> dict[str, list[dict[str, Any]]]:
    """date -> rows. Every feature reads only games strictly before the row's date."""
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    team_dates: dict[str, set[date]] = defaultdict(set)
    for g in logs:
        by_player[g["key"]].append(g)
        team_dates[g["team"]].add(date.fromisoformat(g["date"]))
    team_sorted = {t: sorted(ds) for t, ds in team_dates.items()}
    tables: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key, games in by_player.items():
        games.sort(key=lambda g: g["date"])
        for i, g in enumerate(games):
            prior = games[:i]
            day = date.fromisoformat(g["date"])
            feats: dict[str, Any] = {"date": g["date"], "player": g["player"], "player_key": key, "team": g["team"],
                                     "game_id": g["game_id"]}
            feats.update(minutes_features([p["min"] for p in prior]))
            feats.update(start_features([starts.get((key, p["date"])) for p in prior]))
            feats["rest_days"] = team_rest_days(team_sorted.get(g["team"], []), day)
            feats["spread_abs"] = spreads.get((g["date"], norm_player(g["team"])))
            feats["fires"] = nba_signal_fires(feats)
            tables[g["date"]].append(feats)
    return tables


def build_as_of(logs: list[dict[str, Any]], starts: dict[tuple[str, str], int],
                spreads: dict[tuple[str, str], float], day: str) -> list[dict[str, Any]]:
    """FORWARD mode: one row per player with history, features from games strictly before `day` -- written before
    `day`'s games so the board can read them pregame. A player whose team does not play on `day` simply joins no line."""
    target = date.fromisoformat(day)
    prior_logs = [g for g in logs if g["date"] < day]
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    team_dates: dict[str, set[date]] = defaultdict(set)
    for g in prior_logs:
        by_player[g["key"]].append(g)
        team_dates[g["team"]].add(date.fromisoformat(g["date"]))
    rows = []
    for key, games in by_player.items():
        games.sort(key=lambda g: g["date"])
        last = games[-1]
        feats: dict[str, Any] = {"date": day, "player": last["player"], "player_key": key, "team": last["team"],
                                 "game_id": None, "as_of": True}
        feats.update(minutes_features([p["min"] for p in games]))
        feats.update(start_features([starts.get((key, p["date"])) for p in games]))
        feats["rest_days"] = team_rest_days(sorted(team_dates.get(last["team"], [])), target)
        feats["spread_abs"] = spreads.get((day, norm_player(last["team"])))
        feats["fires"] = nba_signal_fires(feats)
        rows.append(feats)
    return rows


def _season_for(day: str) -> tuple[str, int]:
    d = date.fromisoformat(day)
    start = d.year if d.month >= 8 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}", start


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--season", default=None, help="e.g. 2025-26; derived from --as-of when omitted")
    ap.add_argument("--as-of", default=None, help="FORWARD mode: write ONE table for this date (YYYY-MM-DD, or 'today' = US Central date)")
    ap.add_argument("--logs-statsnba", default=None)
    ap.add_argument("--logs-espn", default=None)
    ap.add_argument("--games-odds-dir", default=None)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    if args.as_of:
        if args.as_of == "today":
            from datetime import datetime, timedelta, timezone
            args.as_of = (datetime.now(timezone.utc) - timedelta(hours=5)).date().isoformat()  # US Central (CDT)
        season, start_year = _season_for(args.as_of)
        args.season = args.season or season
        if not args.logs_espn and not args.logs_statsnba:
            args.logs_espn = str(Path(os.path.expanduser(args.data_root)) / "nba_source" / "data" / "processed"
                                 / f"player_game_log_{start_year}.csv")
    if not args.season:
        print("REFUSING: no --season and no --as-of", flush=True)
        return 2
    espn_logs, starts = load_espn(Path(os.path.expanduser(args.logs_espn))) if args.logs_espn else ([], {})
    logs = load_statsnba(Path(os.path.expanduser(args.logs_statsnba))) if args.logs_statsnba else espn_logs
    spreads = load_spreads(Path(os.path.expanduser(args.games_odds_dir)) if args.games_odds_dir else None)
    if args.as_of:
        rows = build_as_of(logs, starts, spreads, args.as_of)
        write_signal_table(os.path.expanduser(args.data_root), "nba", args.season, args.as_of, rows)
        fired_now: dict[str, int] = defaultdict(int)
        for r in rows:
            for name in r["fires"]:
                fired_now[name] += 1
        print(f"NBA_SIGNALS_AS_OF season={args.season} date={args.as_of} logs={len(logs)} players={len(rows)} "
              f"fired={dict(sorted(fired_now.items()))}", flush=True)
        return 0
    tables = build(logs, starts, spreads)
    fired: dict[str, int] = defaultdict(int)
    for day, rows in sorted(tables.items()):
        write_signal_table(os.path.expanduser(args.data_root), "nba", args.season, day, rows)
        for r in rows:
            for name in r["fires"]:
                fired[name] += 1
    rows_total = sum(len(v) for v in tables.values())
    with_start = sum(1 for v in tables.values() for r in v if r.get("started_last") is not None)
    with_spread = sum(1 for v in tables.values() for r in v if r.get("spread_abs") is not None)
    print(f"NBA_SIGNALS season={args.season} dates={len(tables)} rows={rows_total} start_known={with_start} "
          f"spread_known={with_spread} fired={dict(sorted(fired.items()))}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
