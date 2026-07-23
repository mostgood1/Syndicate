from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
import requests


API_BASE = "https://api.the-odds-api.com/v4"
DEFAULT_MARKETS = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_points_rebounds_assists",
    "player_threes",
    "player_steals",
    "player_blocks",
    "player_turnovers",
    "player_points_rebounds",
    "player_points_assists",
    "player_rebounds_assists",
    "player_double_double",
    "player_triple_double",
]
SPORT_KEYS = {
    "nba": "basketball_nba",
    "wnba": "basketball_wnba",
}
BOOKMAKER_ALIASES = {
    "fanduel": "fanduel",
    "fd": "fanduel",
    "draftkings": "draftkings",
    "dk": "draftkings",
    "betmgm": "betmgm",
    "mgm": "betmgm",
    "bet365": "bet365",
    "bet365us": "bet365",
}


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv()


def _headers() -> dict[str, str]:
    return {"Accept": "application/json", "User-Agent": "syndicate/1.0"}


def _normalize_bookmaker_key(book: object) -> str:
    try:
        raw = str(book or "").strip().lower()
    except Exception:
        return ""
    if not raw:
        return ""
    compact = raw.replace(" ", "").replace("-", "").replace("_", "")
    return BOOKMAKER_ALIASES.get(compact, raw)


def _resolve_bookmakers(raw: str | None) -> tuple[str, ...]:
    text = str(raw or "").strip()
    if not text:
        return tuple()
    if text.lower() in {"all", "none", "off", "0", "false", "no"}:
        return tuple()
    out: list[str] = []
    seen: set[str] = set()
    for part in text.split(","):
        key = _normalize_bookmaker_key(part)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return tuple(out)


def _bookmakers_csv(raw: str | None) -> str | None:
    values = _resolve_bookmakers(raw)
    return ",".join(values) if values else None


def _get(url: str, params: dict[str, object]) -> requests.Response:
    response = requests.get(url, params=params, headers=_headers(), timeout=45)
    response.raise_for_status()
    return response


def _event_et_date(iso_str: str):
    try:
        raw = pd.to_datetime(iso_str, utc=True)
    except Exception:
        return None
    for tz_name in ("America/New_York", "US/Eastern"):
        try:
            return raw.tz_convert(tz_name).date()
        except Exception:
            continue
    try:
        month = int(raw.month)
        offset_hours = 4 if 3 <= month <= 11 else 5
        return (raw - pd.Timedelta(hours=offset_hours)).date()
    except Exception:
        return raw.date()


def _flatten_bookmakers(event_obj: dict, snapshot_ts: str) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    event_id = event_obj.get("id")
    commence_time = event_obj.get("commence_time")
    home = str(event_obj.get("home_team") or "").strip()
    away = str(event_obj.get("away_team") or "").strip()
    for bookmaker in event_obj.get("bookmakers", []) or []:
        book_key = bookmaker.get("key")
        book_title = bookmaker.get("title")
        for market in bookmaker.get("markets", []) or []:
            market_key = market.get("key")
            last_update = market.get("last_update") or bookmaker.get("last_update")
            for outcome in market.get("outcomes", []) or []:
                player_name = outcome.get("description")
                if (not player_name) and isinstance(market_key, str) and market_key.startswith("player_"):
                    player_name = outcome.get("description") or outcome.get("participant") or outcome.get("name")
                out.append(
                    {
                        "snapshot_ts": snapshot_ts,
                        "event_id": event_id,
                        "commence_time": commence_time,
                        "bookmaker": book_key,
                        "bookmaker_title": book_title,
                        "market": market_key,
                        "outcome_name": str(outcome.get("name") or "").strip(),
                        "player_name": player_name,
                        "point": outcome.get("point"),
                        "price": outcome.get("price"),
                        "last_update": last_update,
                        "home_team": home,
                        "away_team": away,
                    }
                )
    return out


def _discover_event_markets(*, api_key: str, sport_key: str, event_id: str, regions: str, bookmakers: str | None) -> list[str]:
    try:
        params: dict[str, object] = {"apiKey": api_key, "regions": regions}
        if bookmakers:
            params["bookmakers"] = bookmakers
        response = _get(f"{API_BASE}/sports/{sport_key}/events/{event_id}/markets", params)
        event_obj = response.json()
        if not isinstance(event_obj, dict):
            return []
        keys: set[str] = set()
        for bookmaker in event_obj.get("bookmakers", []) or []:
            for market in bookmaker.get("markets", []) or []:
                key = market.get("key")
                if key:
                    keys.add(str(key))
        return sorted(keys)
    except Exception:
        return []


def fetch_player_props_current(*, api_key: str, league: str, date_str: str, regions: str, bookmakers: str | None, markets: list[str] | None) -> pd.DataFrame | None:
    """Returns an empty DataFrame when the fetch itself was inconclusive
    (network/API failure, malformed response) -- the caller may reasonably
    fall back to a recent prior snapshot in that case, same as before.
    Returns None specifically when the events list was fetched successfully
    and confirms zero real events for date_str -- e.g. an all-star break, or
    any other genuine no-games day. The caller must NOT paper over that with
    a different date's real schedule: confirmed live 2026-07-23, doing so
    left an all-star-break date permanently serving a byte-for-byte-matching
    prior day's slate (same commence_times, same matchups), since nothing
    downstream could tell "no games" apart from "fetch failed, reuse
    whatever's newest" before this distinction existed.
    """
    sport_key = SPORT_KEYS[str(league).strip().lower()]
    target_date = pd.to_datetime(date_str).date()
    desired_markets = list(markets or DEFAULT_MARKETS)

    try:
        response = _get(f"{API_BASE}/sports/{sport_key}/events", {"apiKey": api_key})
        events = response.json() or []
    except Exception:
        return pd.DataFrame()

    if not isinstance(events, list):
        return pd.DataFrame()

    day_events = []
    for event in events:
        try:
            if _event_et_date(str(event.get("commence_time") or "")) == target_date:
                day_events.append(event)
        except Exception:
            continue
    if not day_events:
        return None

    rows: list[dict[str, object]] = []
    snapshot_ts = pd.Timestamp.utcnow().isoformat()
    normalized_bookmakers = _bookmakers_csv(bookmakers)

    def _fetch_once(event_id: str, requested_markets: list[str]) -> bool:
        if not requested_markets:
            return False
        params: dict[str, object] = {
            "apiKey": api_key,
            "regions": regions,
            "markets": ",".join(requested_markets),
            "oddsFormat": "american",
        }
        if normalized_bookmakers:
            params["bookmakers"] = normalized_bookmakers
        try:
            response = _get(f"{API_BASE}/sports/{sport_key}/events/{event_id}/odds", params)
            event_obj = response.json()
            if not isinstance(event_obj, dict):
                return False
            rows.extend(_flatten_bookmakers(event_obj, snapshot_ts))
            return True
        except requests.HTTPError:
            return False
        except Exception:
            return False

    for event in day_events:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        discovered = _discover_event_markets(
            api_key=api_key,
            sport_key=sport_key,
            event_id=event_id,
            regions=regions,
            bookmakers=normalized_bookmakers,
        )
        requested = [market for market in discovered if market in set(desired_markets)] if discovered else []
        if requested and _fetch_once(event_id, requested):
            continue
        core = [
            "player_points",
            "player_rebounds",
            "player_assists",
            "player_threes",
            "player_points_rebounds_assists",
        ]
        if desired_markets:
            core = [market for market in core if market in desired_markets]
        if _fetch_once(event_id, core):
            continue
        probe_list = requested or desired_markets or core
        for market in probe_list:
            _fetch_once(event_id, [market])

    return pd.DataFrame(rows)


def _latest_existing_snapshot_path(*, out_path: Path, target_date: str) -> Path | None:
    target_value = pd.to_datetime(target_date, errors="coerce")
    if pd.isna(target_value):
        target_value = None
    candidates: list[tuple[pd.Timestamp, Path]] = []
    for candidate in sorted(out_path.parent.glob("odds_wnba_player_props_*.csv")):
        if not candidate.is_file():
            continue
        date_text = candidate.stem.replace("odds_wnba_player_props_", "", 1)
        parsed = pd.to_datetime(date_text, errors="coerce")
        if pd.isna(parsed):
            continue
        if target_value is not None and parsed > target_value:
            continue
        candidates.append((parsed, candidate))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch NBA/WNBA player props from OddsAPI to CSV")
    parser.add_argument("--league", type=str, choices=sorted(SPORT_KEYS.keys()), required=True)
    parser.add_argument("--date", type=str, required=True)
    parser.add_argument("--out", type=str, required=True)
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--regions", type=str, default="us")
    parser.add_argument("--bookmakers", type=str, default=None)
    parser.add_argument("--markets", type=str, default="")
    args = parser.parse_args(argv)

    _load_env()
    api_key = str(args.api_key or os.environ.get("ODDS_API_KEY") or "").strip()
    if not api_key:
        print("ERROR: Missing ODDS_API_KEY; set in environment or pass --api-key")
        return 2

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    market_list = [market.strip() for market in str(args.markets or "").split(",") if market.strip()]
    df = fetch_player_props_current(
        api_key=api_key,
        league=args.league,
        date_str=args.date,
        regions=str(args.regions or "us").strip() or "us",
        bookmakers=args.bookmakers,
        markets=(market_list or None),
    )

    if df is None:
        # Confirmed: the events list was fetched successfully and genuinely
        # has zero events for this date (an all-star break, a schedule gap,
        # etc.) -- never preserve an existing file or fall back to a
        # different date's snapshot here. Reusing a different day's real
        # schedule as a stand-in for a confirmed no-games day is actively
        # wrong, not a reasonable placeholder (confirmed live 2026-07-23: an
        # all-star-break date permanently inherited a prior day's full
        # slate this way). Write a genuine empty result so downstream
        # consumers correctly see "no games" instead.
        try:
            pd.DataFrame(columns=["event_id", "commence_time", "home_team", "away_team"]).to_csv(out_path, index=False)
        except Exception:
            pass
        print(f"No events scheduled for {args.date}; wrote empty snapshot at {out_path}")
        return 0

    existing_has_rows = False
    if out_path.exists():
        try:
            existing_has_rows = not pd.read_csv(out_path, nrows=1).empty
        except Exception:
            existing_has_rows = False

    if df.empty:
        if existing_has_rows:
            print(f"WARNING: No player props fetched for {args.date}; preserving existing snapshot at {out_path}")
            return 0
        fallback_path = _latest_existing_snapshot_path(out_path=out_path, target_date=args.date)
        if fallback_path is not None and fallback_path.exists():
            try:
                out_path.write_bytes(fallback_path.read_bytes())
            except Exception:
                pass
            try:
                copied_rows = len(pd.read_csv(out_path))
            except Exception:
                copied_rows = 0
            if copied_rows > 0:
                print(f"WARNING: No player props fetched for {args.date}; reusing latest snapshot at {fallback_path}")
                return 0
        print(f"ERROR: No player props fetched for {args.date} and no prior snapshot exists to preserve")
        return 2

    df.to_csv(out_path, index=False)
    print(f"Wrote {out_path} with {len(df)} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
