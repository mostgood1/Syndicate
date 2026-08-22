"""Fetch soccer player-prop odds from The Odds API into a local CSV.

Soccer analog of ``fetch_nfl_oddsapi_props_local.py``. Player-prop markets
are only served from the per-event endpoint, so this fetches the league's
event list first and then each event's player markets.

Usage:
    python scripts/fetch_soccer_oddsapi_props_local.py --league epl --out data/soccer_source/epl/props/latest.csv

Requires ODDS_API_KEY in the environment (or .env).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota
import requests
from requests.exceptions import HTTPError

LEAGUE_SPORT_KEYS: dict[str, str] = {
    "epl": "soccer_epl",
    "la_liga": "soccer_spain_la_liga",
    "bundesliga": "soccer_germany_bundesliga",
    "serie_a": "soccer_italy_serie_a",
    "ligue_1": "soccer_france_ligue_one",
    "mls": "soccer_usa_mls",
    "ucl": "soccer_uefa_champs_league",
    "eredivisie": "soccer_netherlands_eredivisie",
    "primeira_liga": "soccer_portugal_primeira_liga",
    "championship": "soccer_efl_champ",
    "belgian_pro_league": "soccer_belgium_first_div",
}

DEFAULT_PLAYER_MARKETS = [
    "player_goal_scorer_anytime",
    "player_first_goal_scorer",
    "player_last_goal_scorer",
    "player_shots_on_target",
    "player_shots",
    "player_assists",
    "player_to_receive_card",
    "player_to_receive_red_card",
]

# GAME-LEVEL markets that are ONLY served from the PER-EVENT endpoint, not the
# bulk one. `fetch_soccer_oddsapi_odds_local.py` previously recorded these as
# "confirmed unavailable (HTTP 422)"; that read a bare status code and missed
# that `INVALID_MARKET` carries two different messages --
# "Markets NOT SUPPORTED BY THIS ENDPOINT" (valid key, wrong endpoint) vs
# "INVALID markets" (no such key). These are the former.
#
# They ride the per-event request THIS module already makes, comma-joined into
# the same `markets=` param, so capturing them costs NO ADDITIONAL CALLS --
# only the per-market-per-region billing.
#
# REGION `us` BY EXPLICIT USER DECISION [2026-08-22]. Measured book coverage on
# soccer_epl, Manchester United @ Hull City:
#     us            btts= 7  corners= 7      <- chosen, 2 units/event
#     uk            btts=11  corners= 4
#     eu            btts= 4  corners= 1
#     us,uk,eu,au   btts=29  corners=18      (8 units/event)
DEFAULT_GAME_EVENT_MARKETS = ["btts", "alternate_totals_corners"]

MARKET_STD_MAP: dict[str, str] = {
    "player_goal_scorer_anytime": "Anytime Goalscorer",
    "player_first_goal_scorer": "First Goalscorer",
    "player_last_goal_scorer": "Last Goalscorer",
    "player_shots_on_target": "Shots On Target",
    "player_shots": "Shots",
    "player_assists": "Assists",
    "player_to_receive_card": "To Receive Card",
    "player_to_receive_red_card": "To Receive Red Card",
}

# Markets priced as a single yes-price per player rather than over/under.
YES_PRICE_MARKETS = {
    "player_goal_scorer_anytime",
    "player_first_goal_scorer",
    "player_last_goal_scorer",
    "player_to_receive_card",
    "player_to_receive_red_card",
}


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


def _player_markets() -> list[str]:
    raw = os.environ.get("ODDS_API_SOCCER_PLAYER_MARKETS")
    if raw:
        return [market.strip() for market in raw.split(",") if market.strip()]
    return list(DEFAULT_PLAYER_MARKETS)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _ordered_bookmakers(bookmakers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """All bookmakers, preferred books first.

    Not every book posts every player market, so parsing sweeps all of them
    and keeps the first-seen (most preferred) row per player/market/line.
    """
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


def _side_key(value: str) -> str | None:
    lowered = value.strip().lower()
    if lowered in ("over", "yes"):
        return "over"
    if lowered in ("under", "no"):
        return "under"
    return None


def _pick_player_from_outcome(outcome: dict[str, Any]) -> str | None:
    # Soccer prop outcomes carry the player either in `description` (with
    # name = Over/Under/Yes) or directly in `name`.
    for field_name in ("description", "name", "participant", "competitor"):
        value = outcome.get(field_name)
        if not value:
            continue
        text = str(value).strip()
        if not text or _side_key(text) is not None:
            continue
        return text
    return None


def fetch_events(api_key: str, *, sport_key: str, region: str) -> list[dict[str, Any]]:
    url = f"{_get_base_url()}/sports/{sport_key}/events"
    response = requests.get(url, params={"apiKey": api_key, "regions": region}, timeout=20)
    record_oddsapi_quota(response.headers, sport="soccer", endpoint=response.url)
    response.raise_for_status()
    return response.json()


def fetch_event_player_props(
    api_key: str,
    *,
    sport_key: str,
    event_id: str,
    region: str,
    markets: list[str],
) -> dict[str, Any] | None:
    url = f"{_get_base_url()}/sports/{sport_key}/events/{event_id}/odds"
    try:
        response = requests.get(
            url,
            params={
                "apiKey": api_key,
                "regions": region,
                "markets": ",".join(markets),
                "oddsFormat": "american",
            },
            timeout=20,
        )
        # response.url, not url: the markets= the attribution buckets read
        # live in params, and the recorder redacts apiKey before persisting.
        record_oddsapi_quota(response.headers, sport="soccer", endpoint=response.url)
        response.raise_for_status()
        return response.json()
    except HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in (404, 422):
            print(f"WARNING: OddsAPI returned {status_code} for event {event_id}. Skipping.")
            return None
        raise


def _game_time(event: dict[str, Any]) -> str | None:
    start_time = event.get("commence_time") or event.get("commenceTime")
    if isinstance(start_time, str):
        return start_time
    try:
        timestamp = float(start_time)
        if timestamp > 1e12:
            timestamp = timestamp / 1000.0
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    except Exception:
        return None


def parse_event_to_rows(event: dict[str, Any], *, league: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    home = str(event.get("home_team") or "").strip()
    away = str(event.get("away_team") or "").strip()
    if not home or not away:
        return rows
    event_desc = f"{away} @ {home}"
    game_time = _game_time(event)

    seen_market_rows: set[tuple[str, str, float | None]] = set()
    for bookmaker in _ordered_bookmakers(event.get("bookmakers") or []):
        book_key = str(bookmaker.get("key") or "").strip() or "oddsapi"
        rows.extend(
            _parse_bookmaker_markets(
                bookmaker,
                book_key=book_key,
                league=league,
                event=event,
                event_desc=event_desc,
                game_time=game_time,
                home=home,
                away=away,
                seen_market_rows=seen_market_rows,
            )
        )
    return rows


def _parse_bookmaker_markets(
    bookmaker: dict[str, Any],
    *,
    book_key: str,
    league: str,
    event: dict[str, Any],
    event_desc: str,
    game_time: str | None,
    home: str,
    away: str,
    seen_market_rows: set[tuple[str, str, float | None]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for market in bookmaker.get("markets") or []:
        market_key = str(market.get("key") or "").strip()
        std_market = MARKET_STD_MAP.get(market_key)
        if not std_market:
            continue
        aggregated: dict[tuple[str, float | None], dict[str, Any]] = {}
        for outcome in market.get("outcomes") or []:
            player = _pick_player_from_outcome(outcome)
            if not player:
                continue
            try:
                line_value = (
                    float(outcome.get("point"))
                    if outcome.get("point") is not None and str(outcome.get("point")) != ""
                    else np.nan
                )
            except Exception:
                line_value = np.nan
            try:
                price = (
                    int(str(outcome.get("price")).replace("+", ""))
                    if outcome.get("price") is not None and str(outcome.get("price")) != ""
                    else np.nan
                )
            except Exception:
                price = np.nan

            key = (player, None if np.isnan(line_value) else line_value)
            record = aggregated.setdefault(
                key,
                {
                    "league": league,
                    "player": player,
                    "market": std_market,
                    "market_key": market_key,
                    "line": line_value,
                    "over_price": np.nan,
                    "under_price": np.nan,
                    "book": book_key,
                    "event": event_desc,
                    "event_id": str(event.get("id") or ""),
                    "game_time": game_time,
                    "home_team": home,
                    "away_team": away,
                },
            )
            if market_key in YES_PRICE_MARKETS:
                record["over_price"] = price
                continue
            side = _side_key(str(outcome.get("name") or "")) or _side_key(str(outcome.get("description") or ""))
            if side == "under":
                record["under_price"] = price
            else:
                record["over_price"] = price
        for (player, line_key), record in aggregated.items():
            dedupe_key = (market_key, player, line_key)
            if dedupe_key in seen_market_rows:
                continue
            seen_market_rows.add(dedupe_key)
            rows.append(record)
    return rows


def parse_event_to_game_rows(event: dict[str, Any], *, league: str) -> list[dict[str, Any]]:
    """GAME-level rows (btts, corners) from a per-event payload.

    A SEPARATE SHAPE FROM `parse_event_to_rows`, deliberately. That one is
    player-keyed (`player`, `over_price`, `under_price`) and BTTS outcomes are
    "Yes"/"No" with no player at all -- routing them through it would file
    "Yes" as a footballer's name and quietly corrupt a props artifact.

    One row per (market, side, line, book): flat, so a caller can pick a best
    price without re-deriving which outcome was which.
    """
    home = str(event.get("home_team") or "")
    away = str(event.get("away_team") or "")
    game_time = str(event.get("commence_time") or "")
    event_id = str(event.get("id") or "")
    out: list[dict[str, Any]] = []
    for bookmaker in _ordered_bookmakers(event.get("bookmakers") or []):
        book_key = str(bookmaker.get("key") or "")
        for market in bookmaker.get("markets") or []:
            market_key = str(market.get("key") or "")
            if market_key not in set(DEFAULT_GAME_EVENT_MARKETS):
                continue
            for outcome in market.get("outcomes") or []:
                price = outcome.get("price")
                if price is None:
                    continue
                # `point` is the corner line; BTTS has none, and None is kept
                # rather than defaulted so "no line" stays distinguishable from
                # "line 0".
                point = outcome.get("point")
                out.append({
                    "league": league,
                    "market_key": market_key,
                    "side": str(outcome.get("name") or "").strip().lower(),
                    "line": float(point) if point is not None else None,
                    "price": price,
                    "book": book_key,
                    "event_id": event_id,
                    "home_team": home,
                    "away_team": away,
                    "game_time": game_time,
                })
    return out


def _stable_props_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=df.columns if df is not None else None)
    out = df.copy()
    for col in ["league", "player", "market", "market_key", "book", "event", "event_id", "game_time", "home_team", "away_team"]:
        if col in out.columns:
            out[col] = out[col].astype("string").str.strip()
    for col in ["line", "over_price", "under_price"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    dedupe_cols = [col for col in ["player", "market", "line", "over_price", "under_price", "book", "event_id"] if col in out.columns]
    if dedupe_cols:
        out = out.drop_duplicates(subset=dedupe_cols, keep="first")
    sort_cols = [col for col in ["market", "player", "line", "event"] if col in out.columns]
    if sort_cols:
        out = out.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
    return out


def _append_soccer_prop_book_quotes(*, league: str, payloads: list[dict[str, Any]]) -> None:
    """Soccer player props into the shared quote log, one row per book.

    `parse_event_to_rows` above AGGREGATES: it folds over/under into a single
    record keyed by (player, line) and stamps whichever `book_key` it saw last,
    so the CSV carries one book per player-line even though `_ordered_bookmakers`
    swept them all. That is fine for the board, which wants one row to render,
    but it means the CSV cannot answer "who has the best price" -- so the log
    takes the raw payload rather than the parsed rows.

    Never raises: a logging side-effect must not fail an odds fetch.
    """
    try:
        from syndicate.features.shared.odds_book_quotes import append_book_quotes
        from syndicate.features.shared.odds_book_quotes import quote_rows_from_oddsapi_events

        rows = quote_rows_from_oddsapi_events(payloads)
        if not rows:
            return
        now = datetime.now(timezone.utc)
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
        print(f"[odds_book_quotes] soccer props append FAILED {type(exc).__name__}: {exc}")


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", type=str, default="epl", choices=sorted(LEAGUE_SPORT_KEYS))
    parser.add_argument("--sport-key", type=str, default=None, help="Override the Odds API sport key directly")
    parser.add_argument("--region", type=str, default=os.environ.get("ODDS_API_REGION", "us"))
    parser.add_argument("--markets", type=str, default=None, help="Comma-separated market keys")
    parser.add_argument("--max-events", type=int, default=int(os.environ.get("ODDS_API_MAX_EVENTS", "30")))
    parser.add_argument("--event-ids", type=str, default=None,
                        help="Comma-separated OddsAPI event ids. Player props cost ONE CALL "
                             "PER EVENT, so a 60s live refresh over a whole slate is the "
                             "expensive shape: ~90 fixtures/tick is ~130k calls/day. Scoped "
                             "to the matches actually in play it is a handful per tick.")
    parser.add_argument("--out", type=str, required=True)
    parser.add_argument("--game-out", type=str, default=None,
                        help="where to write the per-event GAME markets (btts, corners). "
                             "Defaults beside --out.")
    parser.add_argument("--no-game-markets", action="store_true",
                        help="skip btts/corners; player props only")
    args = parser.parse_args()

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERROR: ODDS_API_KEY is not set")
        return 2

    sport_key = args.sport_key or LEAGUE_SPORT_KEYS[args.league]
    markets = [m.strip() for m in args.markets.split(",")] if args.markets else _player_markets()
    game_markets = [] if args.no_game_markets else list(DEFAULT_GAME_EVENT_MARKETS)
    # ONE request carries both. Splitting them would double the per-event call
    # count for no benefit -- the endpoint is identical.
    request_markets = markets + game_markets

    events = fetch_events(api_key, sport_key=sport_key, region=args.region)
    print(f"Fetched {len(events)} events for {sport_key}")
    if args.event_ids:
        wanted = {e.strip() for e in args.event_ids.split(",") if e.strip()}
        before = len(events)
        events = [e for e in events if str(e.get("id") or "") in wanted]
        # Counted, and NAMED when it drops to zero: an empty scope must not look
        # like an empty slate. The event-list call has already been spent either
        # way, so reporting the miss is free and its absence would be a silent
        # zero of exactly the kind this repo keeps paying for.
        print(f"Scoped to {len(events)} of {before} events by --event-ids "
              f"({len(wanted)} requested)", flush=True)
        if not events:
            print("PROPS_SCOPE_EMPTY: none of the requested event ids are in this "
                  "sport key's current event list -- no per-event calls made", flush=True)

    rows: list[dict[str, Any]] = []
    game_rows: list[dict[str, Any]] = []
    prop_payloads: list[dict[str, Any]] = []
    for event in events[: max(1, args.max_events)]:
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        payload = fetch_event_player_props(
            api_key, sport_key=sport_key, event_id=event_id, region=args.region, markets=request_markets
        )
        if payload is None:
            continue
        rows.extend(parse_event_to_rows(payload, league=args.league))
        game_rows.extend(parse_event_to_game_rows(payload, league=args.league))
        prop_payloads.append(payload)

    _append_soccer_prop_book_quotes(league=str(args.league), payloads=prop_payloads)

    if game_rows:
        # Beside --out, i.e. under `soccer_source/<league>/props/`, which
        # `artifact_publisher.HOT_ARTIFACT_PATTERNS` already allowlists as
        # `soccer_source/*/props/*.csv`. A new directory would need its own
        # allowlist entry and would be invisible to web until it got one --
        # the exact failure that made live_state unreadable there.
        # DATE-SCOPED, matching picks/props convention, so a stale file cannot
        # answer for today.
        game_out = (
            Path(args.game_out)
            if args.game_out
            else Path(args.out).with_name(f"game_markets_{Path(args.out).stem}.csv")
        )
        game_df = pd.DataFrame(game_rows)
        # THE FEED DUPLICATES (book, market, side, line) WITH DIFFERENT PRICES.
        # Measured 2026-08-22, fanduel `alternate_totals_corners`: 50 outcomes
        # for 15 lines, with Over 4.5 at BOTH -7000 and -8000 (and Under 4.5 at
        # 2000 and 1400). The pairs are internally consistent, so these look
        # like two corner variants collapsed under one key upstream -- and the
        # outcome objects carry only `name`/`point`/`price`, with `description`
        # None on all 50, so THERE IS NO FIELD TO TELL THEM APART.
        #
        # Keep the bettor-favourable price (consistent with the price-shopping
        # result this repo already measured) and REPORT the collapse. Silently
        # taking whichever row sorted first would make a downstream "best price"
        # arbitrary, and hide that the feed is ambiguous here at all.
        keys = ["event_id", "market_key", "side", "line", "book"]
        before = len(game_df)
        game_df = (
            game_df.sort_values("price", ascending=False, kind="stable")
            .drop_duplicates(subset=keys, keep="first")
            .sort_values(keys, kind="stable")
        )
        collapsed = before - len(game_df)
        if collapsed:
            print(f"GAME_MARKET_DUPLICATE_QUOTES collapsed={collapsed} of {before} "
                  "(same book/market/side/line, different price; feed carries no "
                  "field distinguishing them -- kept the better price)", flush=True)
        _write_text_atomic(game_out, game_df.to_csv(index=False))
        print(f"Wrote {len(game_df)} game-market rows to {game_out}", flush=True)
    else:
        # Named, not silent: these markets are thin at some books and an empty
        # file must not read as "not captured".
        print("NO_GAME_MARKET_ROWS: btts/corners returned no priced outcomes "
              f"for {len(events)} event(s) in region {args.region}", flush=True)

    df = _stable_props_df(pd.DataFrame(rows))
    out_path = Path(args.out)
    _write_text_atomic(out_path, df.to_csv(index=False))
    print(f"Wrote {len(df)} prop rows to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
