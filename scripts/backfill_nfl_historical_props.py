#!/usr/bin/env python3
"""Backfill NFL CLOSING player-prop lines from OddsAPI's historical endpoints.

WHY. `docs/ai_context/todo.md` `#471` backtested the NFL player-prop rate model
across 152,919 (player, week, stat) observations and found real, out-of-sample
skill in 8 of 9 markets -- but graded every one of them against OUTCOMES only.
Its Section 3, the one that grades against what a book actually quoted, matched
**0 rows**, and it stayed 0 because nothing had ever captured an NFL player-prop
line. Measured 2026-08-20 on production: 13 of 14 weekly prop CSVs were 5-byte
stubs and 101MB of NFL book_quotes held zero player rows (root cause fixed in
scripts/fetch_nfl_oddsapi_props_local.py -- wrong endpoint plus two invalid
market keys). That fix captures the FUTURE. This captures the past, which is
the only way to price a model that already has four seasons of predictions.

Without a quoted line there is no hit rate, no CLV and no ROI -- only "the mean
was close". This script is what turns the existing backtest into a priced one.

WHAT IT WRITES. Exactly the artifact the pipeline already reads:

    data/nfl_source/oddsapi_player_props_<season>_wk<week>.csv

with the columns `syndicate/features/nfl/props.py::_nfl_raw_player_props`
expects, so `backtest_nfl_props.py` Section 3 picks it up with NO code change.
Every book's price also goes to the shared quote log
(`nfl_source/tracking/book_quotes/<season>_wk<week>.jsonl`) so a best-price /
CLV pass never has to re-buy the same snapshot -- the CSV keeps its one-row-per
(player, market) contract, the quote log keeps the full book set.

BILLING, MEASURED 2026-08-20 rather than assumed (`x-requests-last`, because a
concurrent production worker makes credit DELTAS unattributable):

    /v4/historical/sports/{sport}/events            1 credit  per call
    /v4/historical/sports/{sport}/events/{id}/odds 10 credits per market-region

A 9-market single-region snapshot of one game therefore costs 90 credits, and
one closing snapshot per game over 2023-2025 REG (816 games) is ~73,400
credits, ~1.5% of the 4.93M remaining on the 5M cap.

CLOSING LINES ONLY, and that is the cost story. Line-movement history would be
many snapshots per game at 90 credits each; one capture just before kickoff is
one snapshot per game.

COVERAGE BOUND: OddsAPI's additional-markets (player prop) archive begins
2023-05-03, so 2022 is NOT available and is refused rather than silently
returning empty weeks.

DRY RUN BY DEFAULT. Spending needs `--execute`. `--max-credits` aborts mid-run
rather than after, and progress is checkpointed so a re-run resumes instead of
re-buying.

Usage:
    py -3 scripts/backfill_nfl_historical_props.py --seasons 2023,2024,2025
    py -3 scripts/backfill_nfl_historical_props.py --seasons 2025 --execute --max-credits 30000
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"
REGIONS = "us"

# Verified live 2026-08-20; `player_rec_yds` / `player_interceptions` are NOT
# valid keys and 422 (the defect that kept NFL prop capture at zero).
PLAYER_MARKETS = [
    "player_pass_yds",
    "player_pass_tds",
    "player_pass_attempts",
    "player_pass_interceptions",
    "player_rush_yds",
    "player_rush_attempts",
    "player_reception_yds",
    "player_receptions",
    "player_anytime_td",
]

# Same standard names the live fetcher and props.py already agree on.
MARKET_STD_MAP: dict[str, str] = {
    "player_reception_yds": "Receiving Yards",
    "player_receptions": "Receptions",
    "player_rush_yds": "Rushing Yards",
    "player_rush_attempts": "Rushing Attempts",
    "player_pass_yds": "Passing Yards",
    "player_pass_tds": "Passing TDs",
    "player_pass_attempts": "Passing Attempts",
    "player_pass_interceptions": "Interceptions",
    "player_anytime_td": "Anytime TD",
}

CREDITS_PER_MARKET_REGION = 10
# OddsAPI's additional-markets archive start. 2022 predates it.
PROPS_ARCHIVE_FIRST_SEASON = 2023
EASTERN = ZoneInfo("America/New_York")

CSV_COLUMNS = [
    "player", "team", "market", "line", "over_price", "under_price",
    "book", "event", "game_time", "home_team", "away_team", "is_ladder",
]


class CreditCeiling(RuntimeError):
    pass


class Budget:
    def __init__(self, max_credits: int) -> None:
        self.max_credits = int(max_credits)
        self.spent = 0
        self.calls = 0
        self.remaining_reported: int | None = None

    def charge(self, headers: dict[str, str]) -> None:
        self.calls += 1
        try:
            self.spent += int(headers.get("x-requests-last") or 0)
        except Exception:
            pass
        try:
            self.remaining_reported = int(headers.get("x-requests-remaining") or 0)
        except Exception:
            pass
        if self.max_credits and self.spent > self.max_credits:
            raise CreditCeiling(
                f"credit ceiling hit: spent {self.spent} > --max-credits {self.max_credits}. "
                f"Progress is checkpointed; re-run to continue."
            )


def _record_quota(headers: dict[str, str], *, endpoint: str) -> None:
    """Attribute every call in the platform quota ledger.

    Non-negotiable, and not boilerplate: an earlier MLB backfill spent 115,739
    credits through an unrecorded seam, and a concurrent session monitoring
    burn saw most of an interval's charges unattributed and opened an
    investigation into phantom spend. An unattributed call is indistinguishable
    from a leak.
    """
    try:
        from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota

        record_oddsapi_quota(headers, sport="nfl", endpoint=endpoint)
    except Exception:
        # Instrumentation must never break the thing it measures.
        pass


def _get(path: str, params: dict[str, Any], *, api_key: str, budget: Budget, retries: int = 3) -> Any:
    query = dict(params)
    query["apiKey"] = api_key
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(query)}"
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as response:
                headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
                budget.charge(headers)
                _record_quota(headers, endpoint=f"historical{path}")
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            headers = {str(k).lower(): str(v) for k, v in (exc.headers or {}).items()}
            budget.charge(headers)
            _record_quota(headers, endpoint=f"historical{path}")
            if exc.code in (404, 422):
                # No snapshot at that instant, or a market this event never
                # offered. Both ordinary; must not abort the run.
                return None
            last_error = exc
        except CreditCeiling:
            raise
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(1.5 * (attempt + 1))
    print(f"  ! giving up on {path} after {retries} attempts: {last_error}", flush=True)
    return None


# ---------------------------------------------------------------------------
# schedule -> the real REG game list, with kickoff instants and week numbers
# ---------------------------------------------------------------------------

def _schedule_path() -> Path:
    from syndicate.features.nfl.sources import default_nfl_source_root

    return default_nfl_source_root() / "tracking" / "nflverse" / "schedules_games.csv"


def load_reg_games(seasons: list[int]) -> list[dict[str, Any]]:
    """Real REG games from the nflverse schedule -- the ground truth for which
    (season, week) a kickoff belongs to.

    Mapping a snapshot to a week BY DATE rather than by team name is deliberate:
    OddsAPI says "New England Patriots" where nflverse says "NE", and a calendar
    date belongs to exactly one REG week, so the date is both sufficient and
    free of a name-matching failure mode.
    """
    path = _schedule_path()
    if not path.exists():
        raise SystemExit(f"schedule not found: {path}")
    wanted = {int(s) for s in seasons}
    games: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                season = int(row.get("season") or 0)
            except Exception:
                continue
            if season not in wanted or str(row.get("game_type") or "").strip() != "REG":
                continue
            gameday = str(row.get("gameday") or "").strip()
            gametime = str(row.get("gametime") or "").strip()
            if not gameday or not gametime:
                continue
            try:
                naive = datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M")
            except Exception:
                continue
            kickoff = naive.replace(tzinfo=EASTERN).astimezone(timezone.utc)
            games.append({
                "game_id": str(row.get("game_id") or ""),
                "season": season,
                "week": int(row.get("week") or 0),
                "kickoff_utc": kickoff,
                "away_team": str(row.get("away_team") or ""),
                "home_team": str(row.get("home_team") or ""),
            })
    return sorted(games, key=lambda g: g["kickoff_utc"])


def _snapshot_for(kickoff: datetime, offset_minutes: int) -> str:
    """Round to the 5-minute grid OddsAPI snapshots on, just before kickoff."""
    stamp = kickoff - timedelta(minutes=offset_minutes)
    stamp = stamp.replace(second=0, microsecond=0)
    stamp -= timedelta(minutes=stamp.minute % 5)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def _events_at(snapshot: str, *, api_key: str, budget: Budget) -> list[dict[str, Any]]:
    payload = _get(f"/historical/sports/{SPORT}/events", {"date": snapshot}, api_key=api_key, budget=budget)
    if not isinstance(payload, dict):
        return []
    return payload.get("data") or []


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _event_props(event_id: str, snapshot: str, *, api_key: str, budget: Budget) -> dict[str, Any] | None:
    payload = _get(
        f"/historical/sports/{SPORT}/events/{event_id}/odds",
        {"date": snapshot, "regions": REGIONS, "oddsFormat": "american",
         "markets": ",".join(PLAYER_MARKETS)},
        api_key=api_key, budget=budget,
    )
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------

def _american(value: Any) -> int | None:
    try:
        return int(str(value).replace("+", "").strip())
    except Exception:
        return None


def _better(a: int | None, b: int | None) -> int | None:
    """Best price for a bettor: higher American odds always pay more."""
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def rows_from_event(event: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(csv_rows, quote_rows).

    csv_rows collapse every book to ONE row per (player, market, line) at the
    BEST available price on each side -- the CSV's one-row-per-selection shape
    is what props.py and Section 3 expect, and writing every book there would
    silently multiply the denominator. quote_rows keep every book so a
    single-book or CLV pass never re-buys the snapshot.
    """
    away = str(event.get("away_team") or "")
    home = str(event.get("home_team") or "")
    commence = str(event.get("commence_time") or "")
    event_desc = f"{away} @ {home}"

    best: dict[tuple[str, str, Any], dict[str, Any]] = {}
    quotes: list[dict[str, Any]] = []

    for book in event.get("bookmakers") or []:
        book_key = str(book.get("key") or "").strip()
        for market in book.get("markets") or []:
            std = MARKET_STD_MAP.get(str(market.get("key") or "").strip())
            if not std:
                continue
            for outcome in market.get("outcomes") or []:
                player = str(outcome.get("description") or "").strip()
                if not player:
                    continue
                side = str(outcome.get("name") or "").strip().lower()
                price = _american(outcome.get("price"))
                point = outcome.get("point")
                try:
                    line = float(point) if point is not None and str(point) != "" else None
                except Exception:
                    line = None

                quotes.append({
                    "sport": "nfl", "kind": "prop", "event_id": str(event.get("id") or ""),
                    "commence_time": commence, "home_team": home, "away_team": away,
                    "bookmaker": book_key, "market": std, "segment": "full",
                    "selection": side, "player_name": player, "line": line, "price": price,
                })

                key = (player, std, line)
                record = best.get(key)
                if record is None:
                    record = {"player": player, "team": "", "market": std, "line": line,
                              "over_price": None, "under_price": None, "book": book_key,
                              "event": event_desc, "game_time": commence,
                              "home_team": home, "away_team": away, "is_ladder": False}
                    best[key] = record
                if side == "under":
                    record["under_price"] = _better(record["under_price"], price)
                else:
                    # "Over", and Anytime TD's "Yes", both settle as the over.
                    record["over_price"] = _better(record["over_price"], price)
    return list(best.values()), quotes


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def _out_dir() -> Path:
    from syndicate.features.nfl.sources import default_nfl_source_root

    return default_nfl_source_root()


def write_week_csv(season: int, week: int, rows: list[dict[str, Any]], *, out_dir: Path) -> Path:
    from syndicate.features.shared.atomic_artifact_write import atomic_write_csv

    import pandas as pd

    path = out_dir / f"oddsapi_player_props_{season}_wk{week}.csv"
    frame = pd.DataFrame(rows, columns=CSV_COLUMNS) if rows else pd.DataFrame(columns=CSV_COLUMNS)
    frame = frame.sort_values(["market", "player", "line"], kind="mergesort").reset_index(drop=True)
    atomic_write_csv(path, frame)
    return path


def append_quotes(season: int, week: int, quotes: list[dict[str, Any]]) -> None:
    if not quotes:
        return
    try:
        from syndicate.features.shared.odds_book_quotes import append_book_quotes

        append_book_quotes(
            sport="nfl",
            date_str=f"{int(season)}_wk{int(week)}",
            rows=quotes,
            captured_at=datetime.now(tz=timezone.utc).isoformat(),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ! book_quotes append failed: {type(exc).__name__}: {exc}", flush=True)


def _state_path(out_dir: Path) -> Path:
    return out_dir / "historical_props_backfill_state.json"


def _load_state(out_dir: Path) -> dict[str, Any]:
    path = _state_path(out_dir)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done_events": {}, "credits_spent": 0}


def _save_state(out_dir: Path, state: dict[str, Any]) -> None:
    path = _state_path(out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill NFL historical player-prop closing lines")
    parser.add_argument("--seasons", default="2023,2024,2025")
    parser.add_argument("--weeks", default="", help="optional comma list to restrict weeks")
    parser.add_argument("--offset-minutes", type=int, default=10,
                        help="how long before kickoff to snapshot (closing line)")
    parser.add_argument("--max-credits", type=int, default=120_000)
    parser.add_argument("--execute", action="store_true", help="actually spend credits")
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    seasons = [int(s) for s in str(args.seasons).split(",") if s.strip()]
    too_old = [s for s in seasons if s < PROPS_ARCHIVE_FIRST_SEASON]
    if too_old:
        print(f"ERROR: OddsAPI's player-prop archive starts 2023-05-03; {too_old} predates it.")
        print("       Refusing rather than spending credits on guaranteed-empty snapshots.")
        return 2
    week_filter = {int(w) for w in str(args.weeks).split(",") if w.strip()} if args.weeks else None

    out_dir = Path(args.out_dir) if args.out_dir else _out_dir()
    games = load_reg_games(seasons)
    if week_filter:
        games = [g for g in games if g["week"] in week_filter]
    if not games:
        print("no REG games matched")
        return 1

    per_game = len(PLAYER_MARKETS) * CREDITS_PER_MARKET_REGION
    windows = sorted({_snapshot_for(g["kickoff_utc"], args.offset_minutes) for g in games})
    estimate = len(games) * per_game + len(windows)

    print(f"NFL historical player-prop backfill")
    print(f"  seasons        : {seasons}")
    print(f"  REG games      : {len(games):,}")
    print(f"  kickoff windows: {len(windows):,}  (phase A, 1 credit each)")
    print(f"  markets        : {len(PLAYER_MARKETS)} x {REGIONS} = {per_game} credits/game (phase B)")
    print(f"  ESTIMATE       : ~{estimate:,} credits   (ceiling --max-credits={args.max_credits:,})")
    if not args.execute:
        print("\nDRY RUN -- nothing fetched, nothing spent. Re-run with --execute to spend.")
        return 0

    import os

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERROR: ODDS_API_KEY not set")
        return 2

    state = _load_state(out_dir)
    done: dict[str, Any] = state.get("done_events") or {}
    budget = Budget(args.max_credits)

    # phase A: kickoff window -> OddsAPI event ids, matched back to a real game
    by_window: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for game in games:
        by_window[_snapshot_for(game["kickoff_utc"], args.offset_minutes)].append(game)

    week_rows: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    week_quotes: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    matched = unmatched = skipped = 0

    try:
        for window in sorted(by_window):
            slate = by_window[window]
            season = slate[0]["season"]
            week = slate[0]["week"]
            kickoffs = {g["kickoff_utc"] for g in slate}
            events = _events_at(window, api_key=api_key, budget=budget)
            wanted = []
            for event in events:
                commence = _parse_iso(event.get("commence_time"))
                if commence is None:
                    continue
                # Same kickoff instant (to the minute) as a real REG game in
                # this window. Time, not team name -- see load_reg_games.
                if any(abs((commence - k).total_seconds()) <= 90 for k in kickoffs):
                    wanted.append(event)
            print(f"{window}  s{season} wk{week}: {len(slate)} scheduled, {len(wanted)} matched in snapshot "
                  f"(spent {budget.spent:,})", flush=True)

            for event in wanted:
                event_id = str(event.get("id") or "")
                if not event_id:
                    continue
                if event_id in done:
                    skipped += 1
                    continue
                payload = _event_props(event_id, window, api_key=api_key, budget=budget)
                if not payload:
                    unmatched += 1
                    done[event_id] = {"rows": 0, "window": window}
                    continue
                rows, quotes = rows_from_event(payload)
                week_rows[(season, week)].extend(rows)
                week_quotes[(season, week)].extend(quotes)
                done[event_id] = {"rows": len(rows), "window": window}
                matched += 1
    except CreditCeiling as exc:
        print(f"\n{exc}")
    finally:
        for (season, week), rows in sorted(week_rows.items()):
            path = write_week_csv(season, week, rows, out_dir=out_dir)
            append_quotes(season, week, week_quotes[(season, week)])
            print(f"  wrote {path.name}: {len(rows):,} rows, {len(week_quotes[(season, week)]):,} quotes")
        state["done_events"] = done
        state["credits_spent"] = int(state.get("credits_spent") or 0) + budget.spent
        _save_state(out_dir, state)

    print(f"\nevents with props: {matched:,}   empty snapshots: {unmatched:,}   already done: {skipped:,}")
    print(f"credits spent this run: {budget.spent:,}   API reports remaining: {budget.remaining_reported:,}"
          if budget.remaining_reported is not None else f"credits spent this run: {budget.spent:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
