from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from requests.exceptions import HTTPError
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.atomic_artifact_write import atomic_write_csv
from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota




DEFAULT_PLAYER_MARKETS = [
    "player_rec_yds",
    "player_receptions",
    "player_rush_yds",
    "player_rush_attempts",
    "player_pass_yds",
    "player_pass_tds",
    "player_pass_attempts",
    "player_interceptions",
    "player_anytime_td",
]

MARKET_STD_MAP: dict[str, str] = {
    "player_rec_yds": "Receiving Yards",
    "player_receptions": "Receptions",
    "player_rush_yds": "Rushing Yards",
    "player_rush_attempts": "Rushing Attempts",
    "player_pass_yds": "Passing Yards",
    "player_pass_tds": "Passing TDs",
    "player_pass_attempts": "Passing Attempts",
    "player_interceptions": "Interceptions",
    "player_anytime_td": "Anytime TD",
}


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv()


def _norm_team(value: str | None) -> str:
    return str(value or "").strip()


def _get_base_url() -> str:
    return os.environ.get("ODDS_API_BASE", "https://api.the-odds-api.com/v4")


def _preferred_books() -> list[str]:
    raw = os.environ.get("ODDS_API_BOOKS", "draftkings,fanduel,betmgm,pointsbetus,caesars") or ""
    return [book.strip().lower() for book in raw.split(",") if book.strip()]


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _stable_props_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=df.columns if df is not None else None)

    out = df.copy()
    for col in ["player", "team", "market", "book", "event", "game_time", "home_team", "away_team"]:
        if col in out.columns:
            out[col] = out[col].astype("string").str.strip()

    for col in ["line", "over_price", "under_price"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    if "is_ladder" in out.columns:
        try:
            out["is_ladder"] = out["is_ladder"].fillna(False).astype(bool)
        except Exception:
            pass

    dedupe_cols = [
        col
        for col in [
            "player",
            "team",
            "market",
            "line",
            "over_price",
            "under_price",
            "book",
            "event",
            "game_time",
            "home_team",
            "away_team",
            "is_ladder",
        ]
        if col in out.columns
    ]
    if dedupe_cols:
        out = out.drop_duplicates(subset=dedupe_cols, keep="first")

    sort_cols = [col for col in ["market", "player", "team", "line", "book", "event"] if col in out.columns]
    if sort_cols:
        out = out.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
    return out


def _player_markets() -> list[str]:
    raw = os.environ.get("ODDS_API_PLAYER_MARKETS")
    if raw:
        return [market.strip() for market in raw.split(",") if market.strip()]
    return list(DEFAULT_PLAYER_MARKETS)


def _choose_bookmaker(bookmakers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not bookmakers:
        return None
    by_name = {str(bookmaker.get("key") or "").lower(): bookmaker for bookmaker in bookmakers}
    for preferred in _preferred_books():
        if preferred in by_name:
            return by_name[preferred]
    return bookmakers[0]


def _is_side_str(value: str) -> bool:
    return value.strip().lower() in ("over", "under", "yes", "no")


def _side_key(value: str) -> str | None:
    lowered = value.strip().lower()
    if lowered in ("over", "yes"):
        return "over"
    if lowered in ("under", "no"):
        return "under"
    return None


def _pick_player_from_outcome(outcome: dict[str, Any]) -> str | None:
    for field_name in ("name", "description", "participant", "competitor"):
        value = outcome.get(field_name)
        if not value:
            continue
        text = str(value).strip()
        if not text or _is_side_str(text):
            continue
        return text
    return None


def fetch_player_props(api_key: str, *, sport_key: str = "americanfootball_nfl", region: str = "us", markets: list[str] | None = None) -> list[dict[str, Any]]:
    url = f"{_get_base_url()}/sports/{sport_key}/odds"
    response = requests.get(
        url,
        params={
            "apiKey": api_key,
            "regions": region,
            "markets": ",".join(markets or _player_markets()),
            "oddsFormat": "american",
        },
        timeout=20,
    )
    # response.url, not url: the markets= the attribution buckets read live in
    # params, and the recorder redacts apiKey before persisting.
    record_oddsapi_quota(response.headers, sport="nfl", endpoint=response.url)
    response.raise_for_status()
    return response.json()


def fetch_player_props_chunked(api_key: str, *, sport_key: str = "americanfootball_nfl", region: str = "us", markets: list[str] | None = None) -> list[dict[str, Any]]:
    aggregated: list[dict[str, Any]] = []
    for market in markets or _player_markets():
        try:
            aggregated.extend(fetch_player_props(api_key, sport_key=sport_key, region=region, markets=[market]))
        except HTTPError as exc:
            if getattr(getattr(exc, "response", None), "status_code", None) == 422:
                print(f"WARNING: OddsAPI returned 422 for market '{market}'. Skipping this market.")
                continue
            raise
        except Exception as exc:
            print(f"WARNING: Failed fetching market '{market}': {exc}")
            continue
    return aggregated


def parse_events_to_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        try:
            raw_away = event.get("away_team") or event.get("awayTeam") or (event.get("teams") or [None, None])[0]
            raw_home = event.get("home_team") or event.get("homeTeam") or (event.get("teams") or [None, None])[1]
            if not raw_away or not raw_home:
                continue
            away = _norm_team(raw_away)
            home = _norm_team(raw_home)
            start_time = event.get("commence_time") or event.get("commenceTime")
            if isinstance(start_time, str):
                game_time = start_time
            else:
                try:
                    timestamp = float(start_time)
                    if timestamp > 1e12:
                        timestamp = timestamp / 1000.0
                    game_time = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
                except Exception:
                    game_time = None
            event_desc = f"{away} @ {home}"

            bookmaker = _choose_bookmaker(event.get("bookmakers") or [])
            if not bookmaker:
                continue
            book_key = str(bookmaker.get("key") or "").strip() or "oddsapi"

            for market in bookmaker.get("markets") or []:
                market_key = str(market.get("key") or "").strip()
                std_market = MARKET_STD_MAP.get(market_key)
                if not std_market:
                    continue
                aggregated: dict[str, dict[str, Any]] = {}
                for outcome in market.get("outcomes") or []:
                    side = _side_key(str(outcome.get("name") or outcome.get("description") or ""))
                    if side is None:
                        side = _side_key(str(outcome.get("description") or outcome.get("name") or ""))
                    player = _pick_player_from_outcome(outcome)
                    if not player:
                        continue
                    try:
                        line_value = float(outcome.get("point")) if outcome.get("point") is not None and str(outcome.get("point")) != "" else np.nan
                    except Exception:
                        line_value = np.nan
                    try:
                        american = int(str(outcome.get("price")).replace("+", "")) if outcome.get("price") is not None and str(outcome.get("price")) != "" else np.nan
                    except Exception:
                        american = np.nan

                    record = aggregated.get(player)
                    if record is None:
                        record = {
                            "player": player,
                            "market": std_market,
                            "line": np.nan,
                            "over_price": np.nan,
                            "under_price": np.nan,
                        }
                        aggregated[player] = record

                    if std_market != "Anytime TD":
                        if not pd.notna(record.get("line")) and pd.notna(line_value):
                            record["line"] = float(line_value)
                        elif pd.notna(line_value) and pd.isna(record.get("line")):
                            record["line"] = float(line_value)

                    if side == "over":
                        record["over_price"] = american
                    elif side == "under":
                        record["under_price"] = american
                    else:
                        record["over_price"] = american

                for record in aggregated.values():
                    rows.append(
                        {
                            **record,
                            "book": book_key,
                            "event": event_desc,
                            "game_time": game_time,
                            "home_team": home,
                            "away_team": away,
                            "is_ladder": False,
                        }
                    )
        except Exception:
            continue
    return rows


def _append_nfl_book_quotes(events: list[dict[str, Any]], *, season: int, week: int) -> None:
    """Every book's price for every tracked market, into the shared quote log.

    Sharded by `{season}_wk{week}` rather than a date, matching how NFL's own
    props CSV and odds_history snapshot paths are scoped -- an NFL week is the
    unit here, not a slate day.

    Never raises: a quote-log failure must not fail an odds fetch.
    """
    try:
        if not isinstance(events, list) or not events:
            return
        from syndicate.features.shared.odds_book_quotes import append_book_quotes, quote_rows_from_oddsapi_events

        rows = quote_rows_from_oddsapi_events(events, market_map=MARKET_STD_MAP)
        append_book_quotes(
            sport="nfl",
            date_str=f"{int(season)}_wk{int(week)}",
            rows=rows,
            captured_at=datetime.now(tz=timezone.utc).isoformat(),
        )
    except Exception as exc:
        print(f"[odds_book_quotes] nfl append FAILED {type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch NFL player props from The Odds API to CSV")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--out", type=str, required=True)
    parser.add_argument("--mode", type=str, default=os.environ.get("ODDSAPI_PROPS_MODE", "per_market"), choices=["per_market", "combined"])
    parser.add_argument("--keep-existing-on-empty", action="store_true", default=True)
    parser.add_argument("--no-keep-existing-on-empty", action="store_false", dest="keep_existing_on_empty")
    parser.add_argument("--save-raw", action="store_true", default=True)
    parser.add_argument("--no-save-raw", action="store_false", dest="save_raw")
    args = parser.parse_args(argv)

    _load_env()
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERROR: Missing ODDS_API_KEY; set in environment or .env")
        return 2
    masked = f"***{api_key[-6:]}" if len(api_key) >= 6 else "(set)"
    print(f"Using OddsAPI key: {masked}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = out_path.with_name(out_path.stem + "_raw.json")
    region = os.environ.get("ODDS_API_REGION", "us")

    try:
        if args.mode == "combined":
            events = fetch_player_props(api_key, region=region)
        else:
            events = fetch_player_props_chunked(api_key, region=region)
    except HTTPError as exc:
        if getattr(getattr(exc, "response", None), "status_code", None) == 422:
            try:
                events = fetch_player_props_chunked(api_key, region=region)
            except Exception as retry_exc:
                print(f"ERROR fetching OddsAPI player props (chunked) after 422: {retry_exc}")
                return 2
        else:
            print(f"ERROR fetching OddsAPI player props: HTTP {getattr(getattr(exc, 'response', None), 'status_code', None)} {exc}")
            return 2
    except Exception as exc:
        print(f"ERROR fetching OddsAPI player props: {exc}")
        return 2

    if args.save_raw:
        try:
            _write_text_atomic(
                raw_path,
                json.dumps(
                    {
                        "fetched_utc": datetime.now(tz=timezone.utc).isoformat(),
                        "region": region,
                        "markets": _player_markets(),
                        "events_count": len(events) if isinstance(events, list) else None,
                        "events": events,
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:
            print(f"WARNING: Failed writing raw OddsAPI payload sidecar: {exc}")

    rows = parse_events_to_rows(events)
    if not rows:
        print("WARNING: No player prop rows parsed from OddsAPI payload.")

    # #209 Class A: parse_events_to_rows keeps ONE book per event
    # (_choose_bookmaker) and discards the rest of a response we have already
    # paid for. The CSV keeps its single-book shape -- every downstream consumer
    # depends on it -- while the quote log keeps all of them, which is what CLV
    # and best-price grading need.
    _append_nfl_book_quotes(events, season=int(args.season), week=int(args.week))

    df = pd.DataFrame(rows)
    columns = [
        "player",
        "team",
        "market",
        "line",
        "over_price",
        "under_price",
        "book",
        "event",
        "game_time",
        "home_team",
        "away_team",
        "is_ladder",
    ]
    if "team" not in df.columns:
        df["team"] = np.nan
    out_df = _stable_props_df(df[[column for column in columns if column in df.columns]].copy())

    if len(out_df) == 0 and args.keep_existing_on_empty and out_path.exists():
        try:
            previous = pd.read_csv(out_path)
            if previous is not None and not previous.empty:
                print(f"WARNING: Parsed 0 rows; keeping existing {out_path} with {len(previous)} rows.")
                return 0
        except Exception:
            pass

    atomic_write_csv(out_path, out_df)
    print(f"Wrote {out_path} with {len(out_df)} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())