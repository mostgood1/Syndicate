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
import datetime as dt
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

# CORRECTED 2026-08-22. This block previously read "btts/draw_no_bet/
# double_chance confirmed unavailable (HTTP 422) ... on the current
# plan/region". THAT CONCLUSION WAS WRONG, and re-probing the live API shows
# why: `INVALID_MARKET` carries TWO DIFFERENT MESSAGES and only one means the
# market does not exist.
#
#     btts                -> "Markets NOT SUPPORTED BY THIS ENDPOINT: btts"
#     both_teams_to_score -> "INVALID markets: both_teams_to_score"
#
# The first is a VALID key on the wrong endpoint; the second is a key that does
# not exist. Read as a bare 422, they look identical -- and the region was not
# the variable either (422 on both `us` and `eu`).
#
# `btts` and `alternate_totals_corners` are served from the PER-EVENT endpoint,
# the same one player props use. Confirmed on the live API 2026-08-22 against
# soccer_epl, Manchester United @ Hull City:
#     btts                     -> 4 books
#     alternate_totals_corners -> 1 book
#     team_totals              -> valid key, 0 books pricing it
# See `fetch_soccer_oddsapi_props_local.py`, which already calls that endpoint.
#
# These stay OUT of this list because this module requests the BULK endpoint
# and they genuinely are not served there -- the capture belongs with the
# per-event fetcher, not here.
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


def _segment_market_map() -> dict[str, tuple[str, str]]:
    """`#343`: full-game + half markets, from the ONE shared vocabulary.

    Soccer plays halves, so `h1`/`h2` -- not quarters. Kept for TAGGING only
    (see `_append_soccer_book_quotes`) -- NOT for requesting, see `_game_markets`
    below. `market_segments.py`'s own docstring says why: "Each segment market
    is a distinct OddsAPI market key on a per-event request." This fetcher only
    ever calls the BULK `/sports/{sport}/odds` endpoint (see `fetch_game_odds`)
    -- unlike MLB's fetcher, which has a separate per-event path
    (`_event_wants_full_game_markets` in `fetch_mlb_oddsapi_local.py`) gated
    specifically for segment markets. Soccer never grew that second path, so
    tagging-only is the honest use of this map today: every quote this script
    actually receives is a full-game market, and `normalize_segment` already
    defaults an untagged key to `full` correctly.
    """
    from syndicate.features.shared.market_segments import full_game_market_keys, segment_market_keys

    return {**full_game_market_keys(), **segment_market_keys("soccer")}


def _game_markets() -> list[str]:
    """The markets to REQUEST from the bulk `/sports/{sport}/odds` endpoint.

    Must stay `DEFAULT_GAME_MARKETS` only (h2h/totals/spreads) unless the env
    override is set. `#343` (`77c0ee49`, 2026-08-10 21:17:39 -0500) merged
    `_segment_market_map()`'s h1/h2 + alternate-line keys into this list --
    those are valid OddsAPI market keys, but not on THIS endpoint, and the
    request sends every market as one comma-joined `markets=` param, so one
    unsupported key 422s the entire call, every league, every time:

        HTTP 422 {"error_code": "INVALID_MARKET", "message": "Markets not
        supported by this endpoint: alternate_spreads, ..., h2h_h1, h2h_h2,
        spreads_h1, spreads_h2, totals_h1, totals_h2"}

    Confirmed live against the production API 2026-08-19 for `mls` and
    `la_liga` -- both 422 with the full 18-key list, both 200 with real events
    (31 / 14) on `DEFAULT_GAME_MARKETS` alone. The regression date lines up
    exactly with the last good capture found anywhere in the book_quotes
    shard (2026-08-10/08-11): every soccer game-odds request has 422'd, for
    every league, since this landed. This is the SAME failure class the
    removed `btts`/`draw_no_bet`/`double_chance` markets already hit once
    (see the comment on `DEFAULT_GAME_MARKETS` below) -- `#343` reintroduced
    it with a bigger set nobody checked against this specific endpoint.
    """
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
    # response.url, not url: the markets= the attribution buckets read live in
    # params, and the recorder redacts apiKey before persisting.
    record_oddsapi_quota(response.headers, sport="soccer", endpoint=response.url)
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


def _append_soccer_book_quotes(*, league: str, events: list[dict[str, Any]]) -> None:
    """Route soccer's already-multi-book response into the shared quote log.

    Soccer was never a Class A capture defect -- `_ordered_bookmakers` sweeps
    every book and the CSV carries a `book` column -- so nothing is being
    recovered here. What it gains is a SHAPE: CLV, closing lines and best-price
    comparison read one flat format for all eight sports instead of a bespoke
    per-sport file list, which is the routing gap that left NBA/WNBA's six-book
    prop CSV unread for months (#209 Class B).

    It also gains the book clock. The CSV rows built by `parse_event_to_rows`
    carry no `last_update` at all, so soccer had only loop time; the shared
    flattener keeps OddsAPI's per-market `last_update`, which is what tells a
    dead market apart from a fresh one.

    Never raises: a logging side-effect must not be able to fail an odds fetch.
    """
    try:
        from syndicate.features.shared.odds_book_quotes import append_book_quotes
        from syndicate.features.shared.odds_book_quotes import quote_rows_from_oddsapi_events

        rows = quote_rows_from_oddsapi_events(events, market_map=_segment_market_map())
        if not rows:
            return
        now = dt.datetime.now(dt.timezone.utc)
        # Shard by the event's own kickoff date rather than "today": a Saturday
        # 20:00 UTC kickoff and a Sunday 00:30 UTC kickoff belong to different
        # slates, and bucketing both under the fetch date would put a match's
        # closing quotes in a shard nothing looks in.
        by_date: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            commence = str(row.get("commence_time") or "")[:10] or now.date().isoformat()
            by_date.setdefault(commence, []).append(row)
        for date_str, date_rows in by_date.items():
            append_book_quotes(
                sport="soccer",
                date_str=date_str,
                rows=date_rows,
                captured_at=now.isoformat(),
                extra={"league": str(league).strip().lower()},
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[odds_book_quotes] soccer append FAILED {type(exc).__name__}: {exc}")


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

    _append_soccer_book_quotes(league=str(args.league), events=events)

    df = _stable_odds_df(pd.DataFrame(rows))
    out_path = Path(args.out)
    _write_text_atomic(out_path, df.to_csv(index=False))
    print(f"Wrote {len(df)} odds rows to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
