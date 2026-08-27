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




# OddsAPI market keys, verified against the live API 2026-08-20 -- NOT guessed
# from the standard-name column. Two of these were wrong for as long as this
# file has existed and each one 422s on its own:
#
#   player_rec_yds        -> player_reception_yds       (INVALID_MARKET)
#   player_interceptions  -> player_pass_interceptions  (INVALID_MARKET)
#
# A wrong key is indistinguishable from "the books have not posted this market
# yet" at every level except the HTTP status, which fetch_player_props_chunked
# used to swallow. See the endpoint note on fetch_player_props below for how
# that combination kept NFL prop capture at exactly zero rows.
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

# Standard names are the CONTRACT with syndicate/features/nfl/props.py and with
# the props CSV every downstream consumer reads -- they are unchanged. Only the
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
    with no such market in the payload. Conflating the two is what let this
    file silently write header-only CSVs for months (see fetch_event_odds).
    """


def fetch_events(api_key: str, *, sport_key: str = "americanfootball_nfl") -> list[dict[str, Any]]:
    """The season's scheduled events. Costs 1 credit and carries no odds."""
    url = f"{_get_base_url()}/sports/{sport_key}/events"
    response = requests.get(url, params={"apiKey": api_key}, timeout=20)
    record_oddsapi_quota(response.headers, sport="nfl", endpoint=response.url)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def _event_window_days() -> float:
    try:
        return float(os.environ.get("ODDS_API_EVENT_WINDOW_DAYS", "8") or 8)
    except Exception:
        return 8.0


def events_in_scope(events: list[dict[str, Any]], *, window_days: float | None = None) -> list[dict[str, Any]]:
    """The next slate only -- every event kicking off within `window_days` of
    the EARLIEST upcoming kickoff.

    `/events` returns the WHOLE season (measured 2026-08-20: 272 events), and
    props are billed per event per market-region. Fetching all of them would
    spend 272 x 9 = 2,448 credits a sweep to retrieve almost nothing, because
    books do not post player props for a game weeks out. An NFL week runs
    Thu -> Mon, so an 8-day window from the first upcoming kickoff is exactly
    one slate.

    Bounding on the earliest KICKOFF rather than on `--week` is deliberate: the
    live endpoint can only ever serve upcoming events, so the week number names
    the output shard -- it cannot widen what the API is willing to return.
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
    sport_key: str = "americanfootball_nfl",
    region: str = "us",
    markets: list[str] | None = None,
) -> dict[str, Any] | None:
    """Player props for ONE event.

    THE ENDPOINT IS THE WHOLE POINT. This used to call the bulk
    `/sports/{key}/odds` endpoint, which does not serve player props at all --
    verified against the live API 2026-08-20:

        GET /v4/sports/americanfootball_nfl/odds?markets=player_pass_yds
          -> HTTP 422 {"error_code": "INVALID_MARKET",
                       "message": "Markets not supported by this endpoint"}

        GET /v4/sports/americanfootball_nfl/events/{id}/odds?markets=player_pass_yds
          -> HTTP 200, real prices

    Bulk `/odds` serves only the featured markets (h2h/spreads/totals); every
    additional market, player props included, is per-event. That is why the
    basketball fetcher has always used this shape
    (scripts/fetch_basketball_oddsapi_props_local.py) and NFL never did.

    The cost of getting this wrong was total and silent: all 9 markets 422'd,
    the caller swallowed each one as a WARNING and returned [], and the run
    wrote a header-only CSV indistinguishable from "no props offered today".
    Measured 2026-08-20 on production: 13 of 14 weekly CSVs were 5-byte stubs,
    and 101MB of NFL book_quotes held zero player rows.
    """
    url = f"{_get_base_url()}/sports/{sport_key}/events/{event_id}/odds"
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
    record_oddsapi_quota(response.headers, sport="nfl", endpoint=response.url)
    if response.status_code == 422:
        raise HTTPError(response.text, response=response)
    if response.status_code == 404:
        # The event exists but has no odds published yet. Not an error.
        return None
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else None


def fetch_player_props(
    api_key: str,
    *,
    sport_key: str = "americanfootball_nfl",
    region: str = "us",
    markets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Every in-scope event's props, all markets in one request per event.

    Returns the same list-of-events-carrying-bookmakers shape the bulk endpoint
    used to return, so parse_events_to_rows and _append_nfl_book_quotes need no
    change.

    All markets go in ONE request per event because billing is per
    market-region either way -- one call is never more expensive than nine, and
    a market this event does not offer is simply absent from a 200 rather than
    an error (verified live 2026-08-20).
    """
    requested = list(markets or _player_markets())
    events = fetch_events(api_key, sport_key=sport_key)
    scoped = events_in_scope(events)
    print(
        f"OddsAPI events: {len(events)} in season, {len(scoped)} in the next slate "
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
                api_key, event_id, sport_key=sport_key, region=region, markets=requested
            )
        except HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 422:
                invalid_market_events += 1
                print(f"WARNING: 422 INVALID_MARKET for event {event_id}: {exc}", flush=True)
                continue
            raise
        if payload and (payload.get("bookmakers") or []):
            collected.append(payload)
    # A 422 on EVERY event is a bad market key, not an empty market. Say so
    # loudly rather than returning [] and letting the caller write a stub.
    if scoped and invalid_market_events == len(scoped):
        raise InvalidMarketError(
            f"all {len(scoped)} events returned 422 INVALID_MARKET for "
            f"markets={','.join(requested)} -- these keys are not valid for {sport_key}."
        )
    print(
        f"OddsAPI props: {len(collected)} of {len(scoped)} events returned bookmakers.",
        flush=True,
    )
    return collected


def fetch_player_props_chunked(
    api_key: str,
    *,
    sport_key: str = "americanfootball_nfl",
    region: str = "us",
    markets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """One request per market per event.

    Resilience fallback for the case where one bad market key would 422 an
    entire combined request. Same credit cost, 9x the HTTP calls, so it is the
    fallback and not the default.

    Unlike the version this replaces, a market set that fails everywhere is
    REPORTED: if every requested market 422'd, that raises instead of returning
    an empty list.
    """
    requested = list(markets or _player_markets())
    events = fetch_events(api_key, sport_key=sport_key)
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
                    api_key, event_id, sport_key=sport_key, region=region, markets=[market]
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
    """Every book, every player, every distinct line -- one row each.

    TWO DEFECTS FIXED HERE TOGETHER, both `#209` Class A, both measured against
    the real production capture on 2026-08-27 rather than inferred.

    1. ONE BOOK OUT OF N. This iterated `_choose_bookmaker(...)` alone and threw
       away the rest of a response we had ALREADY PAID FOR. Production's
       `oddsapi_player_props_2026_wk1.csv` was 294 rows, `{draftkings: 294}` --
       a single book across the whole week-1 market. Price shopping is the
       largest single lever measured on this platform (+2.95 ROI pts on NFL
       props specifically, controlled, identical bets) and cannot be run against
       a one-book file. Same API call, same credits, more rows.

    2. THE AGGREGATION KEY IGNORED `line`. `aggregated` was keyed on `player`
       alone, so when a market quoted a player at more than one line, every line
       after the first OVERWROTE the previous one and the row kept whichever
       arrived last -- silently, with no duplicate to notice. Keyed on
       (player, line) now, so an alternate ladder survives as distinct rows.

    `_choose_bookmaker` is deliberately left defined and unused so this fetcher
    and the NCAAF one stay easy to diff.

    WHAT THIS DOES NOT CHANGE: the one-row-per-selection contract downstream
    consumers rely on. `nfl_props_rows_for_week` now collapses to the BEST price
    per selection explicitly, so its callers (the market board, the props page,
    the ROI report and its 64,007-bet denominator) see exactly what they saw
    before. The books are gained by the file, not imposed on the consumers.
    """
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

            for bookmaker in event.get("bookmakers") or []:
                book_key = str(bookmaker.get("key") or "").strip() or "oddsapi"

                for market in bookmaker.get("markets") or []:
                    market_key = str(market.get("key") or "").strip()
                    std_market = MARKET_STD_MAP.get(market_key)
                    if not std_market:
                        continue
                    aggregated: dict[tuple[str, str], dict[str, Any]] = {}
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

                        # Anytime TD has no line, so every outcome for a player
                        # belongs to one record; every other market keys the
                        # line in, which is what stops an alternate ladder from
                        # collapsing onto its own last entry. Over and under of
                        # the SAME line must still meet in one record -- that is
                        # why the line, and not the side, is in the key.
                        line_key = "" if std_market == "Anytime TD" or not pd.notna(line_value) else f"{float(line_value):g}"
                        record = aggregated.get((player, line_key))
                        if record is None:
                            record = {
                                "player": player,
                                "market": std_market,
                                "line": np.nan,
                                "over_price": np.nan,
                                "under_price": np.nan,
                            }
                            aggregated[(player, line_key)] = record

                        if std_market != "Anytime TD" and pd.notna(line_value) and pd.isna(record.get("line")):
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
    # "combined" = one request per event carrying all markets. Billing is per
    # market-region either way, so combined is never dearer than per_market and
    # costs 1 HTTP call per event instead of 9. per_market survives as the
    # fallback for when a single bad key would 422 the whole batch.
    parser.add_argument("--mode", type=str, default=os.environ.get("ODDSAPI_PROPS_MODE", "combined"), choices=["per_market", "combined"])
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
    except InvalidMarketError as exc:
        # Do NOT fall through to the CSV write. A bad market key produces the
        # same zero rows as a quiet market, and writing the file anyway is
        # exactly how this stayed invisible: 13 header-only weekly stubs on
        # production and not one line of evidence that anything was wrong.
        print(f"ERROR: OddsAPI rejected every requested market: {exc}")
        return 2
    except HTTPError as exc:
        if getattr(getattr(exc, "response", None), "status_code", None) == 422:
            try:
                events = fetch_player_props_chunked(api_key, region=region)
            except InvalidMarketError as retry_exc:
                print(f"ERROR: OddsAPI rejected every requested market: {retry_exc}")
                return 2
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

    # `#209` Class A, now fixed on BOTH sides rather than one.
    # `parse_events_to_rows` used to keep ONE book per event
    # (`_choose_bookmaker`) and discard the rest of a response we had already
    # paid for; the quote log kept all of them, so CLV and best-price grading
    # worked while the CSV -- the file the board, the props page and the ROI
    # report actually read -- could not answer "who has the best price".
    #
    # The CSV now carries every book too. The claim that "every downstream
    # consumer depends on" the single-book shape was true, and is honoured
    # explicitly instead of by accident: `nfl_props_rows_for_week` collapses to
    # the best price per selection, so consumers still see one row per
    # selection. Throwing the data away at capture time was never what made
    # that contract hold -- it just made it unfixable.
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