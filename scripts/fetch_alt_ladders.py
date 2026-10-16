#!/usr/bin/env python
"""Player ALTERNATE-line ladders for the cheat sheet's games, once per game, late pregame (lane `alt-ladders`).

User 2026-10-16: "fetch alt lines, but we need to understand cost implications of this", then "proceed with option c"
(`.syndicate/findings_2026-10-16_alt_line_cost.md`): one call per cheat-sheet game asking ONLY the alternate keys,
with the sport's 10-book prop list (billed as one region), once, ~60-90 minutes before the start. ~210 credits/day,
0.13% of the 5M cap -- against +19-33K/day for adding the keys to every fetch, which is why they are NOT added to the
main market lists.

The key names were VERIFIED on 2026-10-16 with one `/markets` call per sport (1 credit each): NFL, MLB, NHL and NBA
books post player alternates (NFL yards at 9 of the 10 books, MLB hits / strikeouts at 10); NCAAF books post NONE
(two team totals at FanDuel only), so NCAAF is not fetched. Soccer's ladders are already free under the main keys.

Writes `<data root>/<sport>_source/tracking/alt_ladders/<date>.jsonl` (one row per book x player x side x line) and
`<date>.state.json` (events fetched + credits billed, from `x-requests-last`). A SEPARATE family on purpose: the
main `book_quotes` stream assumes one line per book per market, and a ladder in it would move consensus lines and
book counts on every consumer. Every call is also recorded through `record_oddsapi_quota`, so the account's
per-sport ledger sees it.

Run every 15 minutes (it only spends on a game entering the window, once):
  nice -n 19 python scripts/fetch_alt_ladders.py --data-root /home/amyn/syndicate-prod/data
  python scripts/fetch_alt_ladders.py --data-root ... --dry-run      # the due games and the worst-case credits
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BASE = "https://api.the-odds-api.com/v4"
CENTRAL = ZoneInfo("America/Chicago")
SPORT_KEYS = {"nfl": "americanfootball_nfl", "mlb": "baseball_mlb", "nhl": "icehockey_nhl", "nba": "basketball_nba"}
# One alternate key per MAIN stat each fetcher already asks for, and only keys a book was seen posting (2026-10-16).
ALT_MARKETS = {
    "nfl": ("player_pass_yds_alternate", "player_pass_tds_alternate", "player_pass_attempts_alternate",
            "player_pass_interceptions_alternate", "player_rush_yds_alternate", "player_rush_attempts_alternate",
            "player_reception_yds_alternate", "player_receptions_alternate"),
    "mlb": ("batter_hits_alternate", "batter_total_bases_alternate", "batter_home_runs_alternate",
            "batter_rbis_alternate", "batter_runs_scored_alternate", "batter_hits_runs_rbis_alternate",
            "batter_strikeouts_alternate", "pitcher_strikeouts_alternate", "pitcher_hits_allowed_alternate",
            "pitcher_earned_runs_alternate"),
    "nhl": ("player_points_alternate", "player_assists_alternate", "player_goals_alternate",
            "player_shots_on_goal_alternate", "player_total_saves_alternate"),
    "nba": ("player_points_alternate", "player_rebounds_alternate", "player_assists_alternate",
            "player_threes_alternate", "player_points_rebounds_assists_alternate", "player_points_rebounds_alternate",
            "player_points_assists_alternate", "player_rebounds_assists_alternate", "player_steals_alternate",
            "player_blocks_alternate", "player_double_double_alternate"),
}
WINDOW_MINUTES = (20, 90)          # fetch the first time a game is 20-90 minutes from its start (every-15-min runs)
DAILY_CREDIT_CAP = 400             # all sports, per Central day; SYNDICATE_ALT_LADDER_DAILY_CAP overrides
NHL_FALLBACK_BOOKS = "draftkings,fanduel,betmgm,williamhill_us,betrivers,fanatics,espnbet,hardrockbet,pinnacle,betonlineag"


def central_day(moment: datetime) -> str:
    return moment.astimezone(CENTRAL).date().isoformat()


def bookmakers_for(sport: str) -> str:
    """The sport's prop list (<= 10 books = one region). NHL keeps its own list (Pinnacle on it)."""
    if sport == "nhl":
        try:
            from syndicate.local_nhl_odds import NHL_PROP_BOOKMAKERS

            return NHL_PROP_BOOKMAKERS
        except Exception:  # noqa: BLE001
            return NHL_FALLBACK_BOOKS
    from syndicate.features.shared.odds_regions import PROP_BOOKMAKERS

    return PROP_BOOKMAKERS[sport]


def _parse_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def due_games(sheet: dict[str, Any], state: dict[str, Any], now: datetime,
              window: tuple[int, int] = WINDOW_MINUTES) -> list[dict[str, Any]]:
    """The sheet's games starting within the window that have not been fetched (one fetch per game, ever)."""
    done = set((state.get("events") or {}).keys())
    out = []
    for game in sheet.get("games") or []:
        start = _parse_ts(game.get("commence_time"))
        event_id = str(game.get("event_id") or "")
        if not start or not event_id or event_id in done:
            continue
        minutes = (start - now).total_seconds() / 60.0
        if window[0] <= minutes <= window[1]:
            out.append(dict(game, minutes_to_start=round(minutes, 1)))
    return out


def ladder_rows(payload: dict[str, Any], *, sport: str, captured_at: str) -> list[dict[str, Any]]:
    """One row per book x market x player x side x line. `description` is the player in OddsAPI's prop outcomes."""
    rows = []
    for book in payload.get("bookmakers") or []:
        for market in book.get("markets") or []:
            key = str(market.get("key") or "")
            for o in market.get("outcomes") or []:
                player = o.get("description") or o.get("participant")
                if not player or o.get("price") is None:
                    continue
                rows.append({"captured_at": captured_at, "sport": sport, "event_id": payload.get("id"),
                             "commence_time": payload.get("commence_time"), "home_team": payload.get("home_team"),
                             "away_team": payload.get("away_team"), "bookmaker": book.get("key"),
                             "book_updated_at": market.get("last_update") or book.get("last_update"),
                             "market_key": key, "base_market": key.removesuffix("_alternate"),
                             "player": player, "side": str(o.get("name") or "").lower(), "line": o.get("point"),
                             "price": o.get("price")})
    return rows


def http_get(url: str) -> tuple[int, Any, dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "Syndicate alt-ladders"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.load(resp), {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        return exc.code, None, {k.lower(): v for k, v in (exc.headers or {}).items()}


def fetch_event(sport: str, event_id: str, markets: tuple[str, ...], *, api_key: str,
                get: Callable[[str], tuple[int, Any, dict[str, str]]] = http_get) -> tuple[dict[str, Any] | None, int, str]:
    """One combined call; a 422 (one key the book side rejects for this event) falls back to one call per key.
    Returns (payload with every market merged, credits billed per x-requests-last, status)."""
    from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota

    def call(keys: tuple[str, ...]) -> tuple[int, Any, int]:
        params = {"apiKey": api_key, "regions": "us", "markets": ",".join(keys), "oddsFormat": "american",
                  "dateFormat": "iso", "bookmakers": bookmakers_for(sport)}
        url = f"{BASE}/sports/{SPORT_KEYS[sport]}/events/{event_id}/odds?{urllib.parse.urlencode(params)}"
        status, body, headers = get(url)
        public = url.split("?", 1)[0] + "?" + urllib.parse.urlencode({k: v for k, v in params.items() if k != "apiKey"})
        record_oddsapi_quota(headers, sport=sport, endpoint=public)
        try:
            cost = int(float(headers.get("x-requests-last") or 0))
        except ValueError:
            cost = 0
        return status, body, cost

    status, body, cost = call(markets)
    if status == 200 and isinstance(body, dict):
        return body, cost, "ok"
    if status != 422:
        return None, cost, f"http_{status}"
    merged: dict[str, Any] | None = None
    for key in markets:
        s, b, c = call((key,))
        cost += c
        if s == 200 and isinstance(b, dict):
            if merged is None:
                merged = dict(b, bookmakers=[])
            by_book = {bk.get("key"): bk for bk in merged["bookmakers"]}
            for bk in b.get("bookmakers") or []:
                if bk.get("key") in by_book:
                    by_book[bk["key"]].setdefault("markets", []).extend(bk.get("markets") or [])
                else:
                    merged["bookmakers"].append(dict(bk))
    return merged, cost, "ok_per_market" if merged else "http_422"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def credits_today(data_root: Path, day: str) -> int:
    return sum(int(_read_json(data_root / f"{s}_source" / "tracking" / "alt_ladders" / f"{day}.state.json")
                   .get("credits") or 0) for s in SPORT_KEYS)


def run(data_root: Path, sports: list[str], *, now: datetime, api_key: str, cap: int, dry_run: bool = False,
        get: Callable[[str], tuple[int, Any, dict[str, str]]] = http_get) -> dict[str, Any]:
    day = central_day(now)
    totals: dict[str, Any] = {"due": 0, "fetched": 0, "rows": 0, "credits": 0, "skipped_cap": 0, "errors": 0}
    spent = credits_today(data_root, day)
    for sport in sports:
        if sport not in SPORT_KEYS:
            print(f"ALT_LADDERS {sport} skipped: no player alternates fetched for this sport", flush=True)
            continue
        sheet = _read_json(data_root / "cheatsheets" / sport / f"{day}.json")
        out_dir = data_root / f"{sport}_source" / "tracking" / "alt_ladders"
        state_path = out_dir / f"{day}.state.json"
        state = _read_json(state_path) or {"date": day, "sport": sport, "events": {}, "credits": 0}
        games = due_games(sheet, state, now)
        totals["due"] += len(games)
        for game in games:
            worst = len(ALT_MARKETS[sport])
            label = f"{game.get('away_team')} @ {game.get('home_team')} in {game['minutes_to_start']} min"
            if dry_run:
                print(f"ALT_LADDERS {sport} DUE {label} -- up to {worst} credits", flush=True)
                continue
            if spent + worst > cap:
                totals["skipped_cap"] += 1
                print(f"ALT_LADDERS {sport} SKIPPED {label}: today's alt credits {spent} + {worst} > cap {cap}", flush=True)
                continue
            payload, cost, status = fetch_event(sport, str(game["event_id"]), ALT_MARKETS[sport], api_key=api_key, get=get)
            spent += cost
            captured = now.astimezone(timezone.utc).isoformat(timespec="seconds")
            rows = ladder_rows(payload, sport=sport, captured_at=captured) if payload else []
            if rows:
                out_dir.mkdir(parents=True, exist_ok=True)
                with open(out_dir / f"{day}.jsonl", "a", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(json.dumps(row) + "\n")
            players = len({r["player"] for r in rows})
            markets = sorted({r["market_key"] for r in rows})
            state["events"][str(game["event_id"])] = {"fetched_at": captured, "status": status, "credits": cost,
                                                      "rows": len(rows), "players": players, "markets": markets,
                                                      "matchup": f"{game.get('away_team')} @ {game.get('home_team')}"}
            state["credits"] = int(state.get("credits") or 0) + cost
            _write_json(state_path, state)
            totals["fetched"] += 1
            totals["rows"] += len(rows)
            totals["credits"] += cost
            totals["errors"] += status not in ("ok", "ok_per_market")
            print(f"ALT_LADDERS {sport} {label}: status={status} credits={cost} rows={len(rows)} players={players} "
                  f"markets={len(markets)}", flush=True)
    totals["credits_today"] = spent
    return totals


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--sports", default="nfl,mlb,nhl,nba")
    ap.add_argument("--dry-run", action="store_true", help="list the due games and their worst-case credits; no calls")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:  # noqa: BLE001
        pass
    api_key = os.environ.get("ODDS_API_KEY") or ""
    if not api_key and not args.dry_run:
        print("ALT_LADDERS refusing: no ODDS_API_KEY", flush=True)
        return 2
    try:
        cap = int(os.environ.get("SYNDICATE_ALT_LADDER_DAILY_CAP") or DAILY_CREDIT_CAP)
    except ValueError:
        cap = DAILY_CREDIT_CAP
    started = time.monotonic()
    totals = run(Path(os.path.expanduser(args.data_root)), [s.strip() for s in args.sports.split(",") if s.strip()],
                 now=datetime.now(timezone.utc), api_key=api_key, cap=cap, dry_run=args.dry_run)
    print(f"ALT_LADDERS done {json.dumps(totals)} cap={cap} secs={time.monotonic() - started:.1f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
