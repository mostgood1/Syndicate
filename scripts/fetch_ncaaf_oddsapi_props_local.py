"""Fetch NCAAF player-prop odds from The Odds API into a local CSV.

NCAAF analog of ``fetch_nfl_oddsapi_props_local.py`` -- same request shape,
same market set (american-football player props use the same OddsAPI
market keys for both ``americanfootball_nfl`` and ``americanfootball_ncaaf``),
same parsing/aggregation, same output columns. Deliberately built as a
straight mirror rather than a fresh design so the two stay easy to compare.

NOT WIRED to any props page or board yet -- this is intentional, not an
oversight. A live check on 2026-08-05 found zero real NCAAF player-prop
markets ~24 days before the season, but a control check against NFL's own
Hall of Fame Game (2 days from kickoff, a sport CONFIRMED to eventually get
real player props) also showed zero markets at that point -- OddsAPI
evidently posts player props very close to kickoff for both sports, not
weeks ahead. The "no coverage" result for NCAAF earlier this session was a
timing artifact, not proof of unavailability, so it isn't a reason to
delay building this fetch script -- only a reason to defer the join. Once
real market coverage is confirmed closer to the season (~2026-08-23 to
2026-08-30), the future join mirrors ``syndicate/features/nfl/props.py``:
a Layer-1 market-inventory contribution folded into
``build_ncaaf_market_board``, and a Layer-2 ranked "props ladder" page,
both built on real season-to-date player rates from
``syndicate.features.ncaaf.player_stats`` (this session's Part A) rather
than a trained model -- see that module's docstring. Until that join
exists, this script's only job is to populate
``data/ncaaf_source/oddsapi_player_props_{season}_wk{week}.csv``
(header-only when OddsAPI has no real markets yet) so the data is already
there once the join is built.

Real player-prop ODDS are expected to be populated for very few weeks
until the season is imminent -- this script must degrade gracefully to an
empty/header-only CSV whenever OddsAPI returns no real markets for a
game, exactly like ``fetch_nfl_oddsapi_props_local.py``'s own docstring
describes for NFL's sparse-weeks case. An empty real response is never
treated as an error.

Usage:
    python scripts/fetch_ncaaf_oddsapi_props_local.py --season 2026 --week 1 --out data/ncaaf_source/oddsapi_player_props_2026_wk1.csv

Requires ODDS_API_KEY in the environment (or .env). Sport key defaults to
americanfootball_ncaaf (overridable via ODDS_API_SPORT, matching the
convention already used by scripts/refresh_ncaaf_oddsapi.py).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
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


DEFAULT_SPORT_KEY = "americanfootball_ncaaf"

# OddsAPI market keys, verified against the live americanfootball_ncaaf
# endpoint 2026-08-20 (HTTP 200, no INVALID_MARKET). Two were wrong here for
# the same reason and with the same effect as in the NFL analog this file was
# copied from -- see scripts/fetch_nfl_oddsapi_props_local.py:
#
#   player_rec_yds        -> player_reception_yds       (INVALID_MARKET)
#   player_interceptions  -> player_pass_interceptions  (INVALID_MARKET)
DEFAULT_PLAYER_MARKETS = [
    "player_reception_yds",
    "player_receptions",
    "player_rush_yds",
    "player_rush_attempts",
    "player_pass_yds",
    "player_pass_tds",
    "player_pass_attempts",
    "player_pass_interceptions",
    "player_anytime_td",
]

# Standard names are the downstream contract and are unchanged; only the
# API-side keys above moved.
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


def _get_sport_key() -> str:
    return os.environ.get("ODDS_API_SPORT", DEFAULT_SPORT_KEY)


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


class InvalidMarketError(RuntimeError):
    """Every requested market was rejected by the API as an invalid key.

    Distinct from "the books have not posted this market yet", which is a 200
    with no such market in the payload.
    """


def fetch_events(api_key: str, *, sport_key: str | None = None) -> list[dict[str, Any]]:
    """The scheduled events. Costs 0-1 credits and carries no odds."""
    resolved_sport_key = sport_key or _get_sport_key()
    url = f"{_get_base_url()}/sports/{resolved_sport_key}/events"
    response = requests.get(url, params={"apiKey": api_key}, timeout=20)
    record_oddsapi_quota(response.headers, sport="ncaaf", endpoint=response.url)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def _event_window_days() -> float:
    try:
        return float(os.environ.get("ODDS_API_EVENT_WINDOW_DAYS", "8") or 8)
    except Exception:
        return 8.0


def events_in_scope(events: list[dict[str, Any]], *, window_days: float | None = None) -> list[dict[str, Any]]:
    """The next slate only -- events kicking off within `window_days` of the
    earliest upcoming kickoff.

    NCAAF lists far more games than NFL (~130 FBS a week), and props are billed
    per event per market RETURNED, so an unbounded sweep is the difference
    between a week's slate and a season's. At the 6h WEEKLY_SPORTS refresh
    cadence a bounded in-season sweep costs ~1,170 credits, ~4,700/day.
    """
    window = float(window_days if window_days is not None else _event_window_days())
    now = datetime.now(tz=timezone.utc)
    dated: list[tuple[datetime, dict[str, Any]]] = []
    for event in events or []:
        raw = event.get("commence_time") or event.get("commenceTime")
        if not raw:
            continue
        try:
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when < now:
            continue
        dated.append((when, event))
    if not dated:
        return []
    dated.sort(key=lambda pair: pair[0])
    cutoff = dated[0][0] + timedelta(days=window)
    return [event for when, event in dated if when <= cutoff]


def fetch_event_odds(
    api_key: str,
    event_id: str,
    *,
    sport_key: str | None = None,
    region: str = "us",
    markets: list[str] | None = None,
) -> dict[str, Any] | None:
    """Player props for ONE event.

    The bulk `/sports/{key}/odds` endpoint this file used to call serves only
    the featured markets (h2h/spreads/totals); every additional market, player
    props included, is per-event and 422s INVALID_MARKET on the bulk route.
    Verified live 2026-08-20 on the NFL analog, and the corrected market keys
    verified 200 against americanfootball_ncaaf the same day.
    """
    resolved_sport_key = sport_key or _get_sport_key()
    url = f"{_get_base_url()}/sports/{resolved_sport_key}/events/{event_id}/odds"
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
    record_oddsapi_quota(response.headers, sport="ncaaf", endpoint=response.url)
    if response.status_code == 422:
        raise HTTPError(response.text, response=response)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else None


def fetch_player_props(
    api_key: str,
    *,
    sport_key: str | None = None,
    region: str = "us",
    markets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Every in-scope event's props, all markets in one request per event.

    Returns the same list-of-events-carrying-bookmakers shape the bulk endpoint
    returned, so parse_events_to_rows is unchanged.
    """
    resolved_sport_key = sport_key or _get_sport_key()
    requested = list(markets or _player_markets())
    events = fetch_events(api_key, sport_key=resolved_sport_key)
    scoped = events_in_scope(events)
    print(
        f"OddsAPI events: {len(events)} listed, {len(scoped)} in the next slate "
        f"(window {_event_window_days()}d); requesting {len(requested)} markets each.",
        flush=True,
    )
    collected: list[dict[str, Any]] = []
    invalid_market_events = 0
    for event in scoped:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        try:
            payload = fetch_event_odds(
                api_key, event_id, sport_key=resolved_sport_key, region=region, markets=requested
            )
        except HTTPError as exc:
            if getattr(getattr(exc, "response", None), "status_code", None) == 422:
                invalid_market_events += 1
                print(f"WARNING: 422 INVALID_MARKET for event {event_id}: {exc}", flush=True)
                continue
            raise
        if payload and (payload.get("bookmakers") or []):
            collected.append(payload)
    if scoped and invalid_market_events == len(scoped):
        raise InvalidMarketError(
            f"all {len(scoped)} events returned 422 INVALID_MARKET for "
            f"markets={','.join(requested)} -- these keys are not valid for {resolved_sport_key}."
        )
    print(f"OddsAPI props: {len(collected)} of {len(scoped)} events returned bookmakers.", flush=True)
    return collected


def fetch_player_props_chunked(
    api_key: str,
    *,
    sport_key: str | None = None,
    region: str = "us",
    markets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """One request per market per event -- resilience fallback for a bad key
    poisoning a combined request. Same credits, 9x the HTTP calls.

    A market set that fails everywhere is REPORTED rather than returned as an
    empty list.
    """
    resolved_sport_key = sport_key or _get_sport_key()
    requested = list(markets or _player_markets())
    events = fetch_events(api_key, sport_key=resolved_sport_key)
    scoped = events_in_scope(events)
    merged: dict[str, dict[str, Any]] = {}
    failed_markets: set[str] = set()
    for market in requested:
        for event in scoped:
            event_id = str(event.get("id") or "").strip()
            if not event_id:
                continue
            try:
                payload = fetch_event_odds(
                    api_key, event_id, sport_key=resolved_sport_key, region=region, markets=[market]
                )
            except HTTPError as exc:
                if getattr(getattr(exc, "response", None), "status_code", None) == 422:
                    print(f"WARNING: OddsAPI returned 422 for market '{market}'. Skipping.", flush=True)
                    failed_markets.add(market)
                    break
                raise
            except Exception as exc:
                print(f"WARNING: Failed fetching '{market}' for event {event_id}: {exc}", flush=True)
                continue
            if not payload:
                continue
            existing = merged.get(event_id)
            if existing is None:
                merged[event_id] = payload
            else:
                existing.setdefault("bookmakers", [])
                existing["bookmakers"].extend(payload.get("bookmakers") or [])
    if requested and failed_markets == set(requested):
        raise InvalidMarketError(
            f"every requested market 422'd as INVALID_MARKET: {','.join(sorted(failed_markets))}"
        )
    return [payload for payload in merged.values() if payload.get("bookmakers")]


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


def _append_ncaaf_book_quotes(events: list[dict[str, Any]], *, season: int, week: int) -> None:
    """Every book's price for every tracked market, into the shared quote log.

    Same #209 Class A defect and same fix as NFL: `_choose_bookmaker` keeps one
    book out of a response that already contains several. Sharded by
    `{season}_wk{week}` to match how NCAAF props are scoped everywhere else.

    Never raises: a quote-log failure must not fail an odds fetch.
    """
    try:
        if not isinstance(events, list) or not events:
            return
        from syndicate.features.shared.odds_book_quotes import append_book_quotes, quote_rows_from_oddsapi_events

        rows = quote_rows_from_oddsapi_events(events, market_map=MARKET_STD_MAP)
        append_book_quotes(
            sport="ncaaf",
            date_str=f"{int(season)}_wk{int(week)}",
            rows=rows,
            captured_at=datetime.now(tz=timezone.utc).isoformat(),
        )
    except Exception as exc:
        print(f"[odds_book_quotes] ncaaf append FAILED {type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch NCAAF player props from The Odds API to CSV")
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

    sport_key = _get_sport_key()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = out_path.with_name(out_path.stem + "_raw.json")
    region = os.environ.get("ODDS_API_REGION", "us")

    try:
        if args.mode == "combined":
            events = fetch_player_props(api_key, sport_key=sport_key, region=region)
        else:
            events = fetch_player_props_chunked(api_key, sport_key=sport_key, region=region)
    except HTTPError as exc:
        if getattr(getattr(exc, "response", None), "status_code", None) == 422:
            try:
                events = fetch_player_props_chunked(api_key, sport_key=sport_key, region=region)
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
                        "sport_key": sport_key,
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
    # #209 Class A: parse_events_to_rows keeps ONE book per event and drops
    # the rest of an already-paid-for response. The CSV keeps its single-book
    # shape; the quote log keeps every book.
    _append_ncaaf_book_quotes(events, season=int(args.season), week=int(args.week))
    if not rows:
        # Confirmed live 2026-08-05: OddsAPI returns zero real player-prop
        # markets for NCAAF games weeks out (and for NFL games days out --
        # see this script's module docstring), so an empty result here is
        # the expected, non-error steady state until kickoff is close.
        print("WARNING: No player prop rows parsed from OddsAPI payload (expected until close to kickoff -- see module docstring).")

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
