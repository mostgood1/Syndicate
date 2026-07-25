"""Fetch soccer game-level odds (h2h/totals/spreads) from The Odds API into a
local CSV.

Unlike player-prop markets (see fetch_soccer_oddsapi_props_local.py, which
must hit the per-event endpoint), game-level markets are served in bulk from
the sport-level /odds endpoint -- one request covers every event in the
league, no per-event fan-out needed.

Usage:
    python scripts/fetch_soccer_oddsapi_odds_local.py --league mls --out data/soccer_source/mls/api/odds/game_odds_2026-07-22.csv

Requires ODDS_API_KEY in the environment (or .env).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota


# Kept as an independent copy rather than imported from
# fetch_soccer_oddsapi_props_local.py -- every OddsAPI fetcher script in this
# repo (refresh_mlb_oddsapi.py, refresh_nba_oddsapi_props.py, etc.) is a
# standalone subprocess-boundary CLI with no cross-script imports, so a bug
# in one can't take another down.
LEAGUE_SPORT_KEYS: dict[str, str] = {
    "epl": "soccer_epl",
    "la_liga": "soccer_spain_la_liga",
    "bundesliga": "soccer_germany_bundesliga",
    "serie_a": "soccer_italy_serie_a",
    "ligue_1": "soccer_france_ligue_one",
    "mls": "soccer_usa_mls",
    "eredivisie": "soccer_netherlands_eredivisie",
    "primeira_liga": "soccer_portugal_primeira_liga",
    "championship": "soccer_efl_champ",
    "belgian_pro_league": "soccer_belgium_first_div",
}

# btts/draw_no_bet/double_chance confirmed unavailable (HTTP 422) against the
# live API on the current plan/region as of 2026-07-21 -- not attempted here.
DEFAULT_GAME_MARKETS = ["h2h", "totals", "spreads"]


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv()


def _get_base_url() -> str:
    return os.environ.get("ODDS_API_BASE", "https://api.the-odds-api.com/v4")


def _preferred_books() -> list[str]:
    raw = os.environ.get("ODDS_API_BOOKS", "draftkings,fanduel,betmgm,pointsbetus,caesars") or ""
    return [book.strip().lower() for book in raw.split(",") if book.strip()]


def _game_markets() -> list[str]:
    raw = os.environ.get("ODDS_API_SOCCER_GAME_MARKETS")
    if raw:
        return [market.strip() for market in raw.split(",") if market.strip()]
    return list(DEFAULT_GAME_MARKETS)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _ordered_bookmakers(bookmakers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not bookmakers:
        return []
    by_name = {str(bookmaker.get("key") or "").lower(): bookmaker for bookmaker in bookmakers}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for preferred in _preferred_books():
        if preferred in by_name:
            ordered.append(by_name[preferred])
            seen.add(preferred)
    for bookmaker in bookmakers:
        key = str(bookmaker.get("key") or "").lower()
        if key not in seen:
            ordered.append(bookmaker)
            seen.add(key)
    return ordered


def fetch_game_odds(api_key: str, *, sport_key: str, region: str, markets: list[str]) -> list[dict[str, Any]]:
    url = f"{_get_base_url()}/sports/{sport_key}/odds"
    response = requests.get(
        url,
        params={"apiKey": api_key, "regions": region, "markets": ",".join(markets), "oddsFormat": "american"},
        timeout=20,
    )
    record_oddsapi_quota(response.headers, sport="soccer", endpoint=url)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def parse_event_to_rows(event: dict[str, Any], *, league: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    home = str(event.get("home_team") or "").strip()
    away = str(event.get("away_team") or "").strip()
    event_id = str(event.get("id") or "").strip()
    commence_time = event.get("commence_time")
    if not home or not away or not event_id:
        return rows

    seen: set[tuple[str, str, str, float | None]] = set()
    for bookmaker in _ordered_bookmakers(event.get("bookmakers") or []):
        book_key = str(bookmaker.get("key") or "").strip() or "oddsapi"
        for market in bookmaker.get("markets") or []:
            market_key = str(market.get("key") or "").strip()
            if market_key not in DEFAULT_GAME_MARKETS:
                continue
            for outcome in market.get("outcomes") or []:
                side = str(outcome.get("name") or "").strip()
                if not side:
                    continue
                try:
                    price = int(str(outcome.get("price")).replace("+", "")) if outcome.get("price") is not None else None
                except Exception:
                    price = None
                point = outcome.get("point")
                try:
                    line = float(point) if point is not None and str(point) != "" else None
                except Exception:
                    line = None
                dedupe_key = (market_key, side, book_key, line)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                rows.append(
                    {
                        "league": league,
                        "event_id": event_id,
                        "home_team": home,
                        "away_team": away,
                        "commence_time": commence_time,
                        "market": market_key,
                        "side": side,
                        "line": line,
                        "price": price,
                        "book": book_key,
                    }
                )
    return rows


def _stable_odds_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(
            columns=["league", "event_id", "home_team", "away_team", "commence_time", "market", "side", "line", "price", "book"]
        )
    out = df.copy()
    for col in ["league", "event_id", "home_team", "away_team", "commence_time", "market", "side", "book"]:
        if col in out.columns:
            out[col] = out[col].astype("string").str.strip()
    for col in ["line", "price"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    dedupe_cols = [col for col in ["event_id", "market", "side", "line", "book"] if col in out.columns]
    if dedupe_cols:
        out = out.drop_duplicates(subset=dedupe_cols, keep="first")
    sort_cols = [col for col in ["event_id", "market", "side"] if col in out.columns]
    if sort_cols:
        out = out.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
    return out


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", type=str, default="epl", choices=sorted(LEAGUE_SPORT_KEYS))
    parser.add_argument("--sport-key", type=str, default=None, help="Override the Odds API sport key directly")
    parser.add_argument("--region", type=str, default=os.environ.get("ODDS_API_REGION", "us"))
    parser.add_argument("--markets", type=str, default=None, help="Comma-separated market keys")
    parser.add_argument("--out", type=str, required=True)
    args = parser.parse_args()

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERROR: ODDS_API_KEY is not set")
        return 2

    sport_key = args.sport_key or LEAGUE_SPORT_KEYS[args.league]
    markets = [m.strip() for m in args.markets.split(",")] if args.markets else _game_markets()

    try:
        events = fetch_game_odds(api_key, sport_key=sport_key, region=args.region, markets=markets)
    except requests.exceptions.HTTPError as exc:
        print(f"ERROR: OddsAPI request failed for {sport_key}: {exc}")
        return 1
    print(f"Fetched {len(events)} events for {sport_key}")

    rows: list[dict[str, Any]] = []
    for event in events:
        rows.extend(parse_event_to_rows(event, league=args.league))

    df = _stable_odds_df(pd.DataFrame(rows))
    out_path = Path(args.out)
    _write_text_atomic(out_path, df.to_csv(index=False))
    print(f"Wrote {len(df)} odds rows to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
