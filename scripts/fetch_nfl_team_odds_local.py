from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota
from syndicate.features.shared.odds_regions import sport_game_line_regions



TEAM_NAME_MAP: dict[str, str] = {
    "dallas": "Dallas Cowboys",
    "cowboys": "Dallas Cowboys",
    "ny giants": "New York Giants",
    "new york giants": "New York Giants",
    "giants": "New York Giants",
    "philadelphia eagles": "Philadelphia Eagles",
    "eagles": "Philadelphia Eagles",
    "washington commanders": "Washington Commanders",
    "washington": "Washington Commanders",
    "commanders": "Washington Commanders",
    "green bay packers": "Green Bay Packers",
    "packers": "Green Bay Packers",
    "chicago bears": "Chicago Bears",
    "bears": "Chicago Bears",
    "minnesota vikings": "Minnesota Vikings",
    "vikings": "Minnesota Vikings",
    "detroit lions": "Detroit Lions",
    "lions": "Detroit Lions",
    "tampa bay buccaneers": "Tampa Bay Buccaneers",
    "buccaneers": "Tampa Bay Buccaneers",
    "carolina panthers": "Carolina Panthers",
    "panthers": "Carolina Panthers",
    "new orleans saints": "New Orleans Saints",
    "saints": "New Orleans Saints",
    "atlanta falcons": "Atlanta Falcons",
    "falcons": "Atlanta Falcons",
    "san francisco 49ers": "San Francisco 49ers",
    "49ers": "San Francisco 49ers",
    "sf": "San Francisco 49ers",
    "seattle seahawks": "Seattle Seahawks",
    "seahawks": "Seattle Seahawks",
    "los angeles rams": "Los Angeles Rams",
    "rams": "Los Angeles Rams",
    "lar": "Los Angeles Rams",
    "la": "Los Angeles Rams",
    "arizona cardinals": "Arizona Cardinals",
    "cardinals": "Arizona Cardinals",
    "new england patriots": "New England Patriots",
    "patriots": "New England Patriots",
    "ne": "New England Patriots",
    "buffalo bills": "Buffalo Bills",
    "bills": "Buffalo Bills",
    "buf": "Buffalo Bills",
    "miami dolphins": "Miami Dolphins",
    "dolphins": "Miami Dolphins",
    "mia": "Miami Dolphins",
    "new york jets": "New York Jets",
    "ny jets": "New York Jets",
    "jets": "New York Jets",
    "nyj": "New York Jets",
    "baltimore ravens": "Baltimore Ravens",
    "ravens": "Baltimore Ravens",
    "bal": "Baltimore Ravens",
    "pittsburgh steelers": "Pittsburgh Steelers",
    "steelers": "Pittsburgh Steelers",
    "pit": "Pittsburgh Steelers",
    "cleveland browns": "Cleveland Browns",
    "browns": "Cleveland Browns",
    "cle": "Cleveland Browns",
    "cincinnati bengals": "Cincinnati Bengals",
    "bengals": "Cincinnati Bengals",
    "cin": "Cincinnati Bengals",
    "tennessee titans": "Tennessee Titans",
    "titans": "Tennessee Titans",
    "ten": "Tennessee Titans",
    "indianapolis colts": "Indianapolis Colts",
    "colts": "Indianapolis Colts",
    "ind": "Indianapolis Colts",
    "jacksonville jaguars": "Jacksonville Jaguars",
    "jaguars": "Jacksonville Jaguars",
    "jax": "Jacksonville Jaguars",
    "houston texans": "Houston Texans",
    "texans": "Houston Texans",
    "hou": "Houston Texans",
    "kansas city chiefs": "Kansas City Chiefs",
    "chiefs": "Kansas City Chiefs",
    "kc": "Kansas City Chiefs",
    "los angeles chargers": "Los Angeles Chargers",
    "la chargers": "Los Angeles Chargers",
    "chargers": "Los Angeles Chargers",
    "lac": "Los Angeles Chargers",
    "las vegas raiders": "Las Vegas Raiders",
    "raiders": "Las Vegas Raiders",
    "lv": "Las Vegas Raiders",
    "denver broncos": "Denver Broncos",
    "broncos": "Denver Broncos",
    "den": "Denver Broncos",
    "dal": "Dallas Cowboys",
    "nyg": "New York Giants",
    "phi": "Philadelphia Eagles",
    "was": "Washington Commanders",
    "gb": "Green Bay Packers",
    "chi": "Chicago Bears",
    "min": "Minnesota Vikings",
    "det": "Detroit Lions",
    "tb": "Tampa Bay Buccaneers",
    "car": "Carolina Panthers",
    "no": "New Orleans Saints",
    "atl": "Atlanta Falcons",
    "sea": "Seattle Seahawks",
    "ari": "Arizona Cardinals",
}


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    _load_env()
    value = os.environ.get(name)
    return value if value is not None else default


def normalize_team_name(name: str) -> str:
    if not name:
        return ""
    key = name.replace("_", " ").strip().lower()
    return TEAM_NAME_MAP.get(key, name.strip())


def get_base_url() -> str:
    return _env("ODDS_API_BASE", "https://api.the-odds-api.com/v4") or "https://api.the-odds-api.com/v4"


def preferred_books() -> list[str]:
    raw = _env("ODDS_API_BOOKS", "draftkings,fanduel,betmgm,pointsbetus,caesars") or ""
    return [book.strip().lower() for book in raw.split(",") if book.strip()]


def fetch_odds(
    api_key: str,
    *,
    sport_key: str = "americanfootball_nfl",
    region: str = "us",
    markets: str = "h2h,spreads,totals",
    odds_format: str = "american",
) -> list[dict[str, Any]]:
    response = requests.get(
        f"{get_base_url()}/sports/{sport_key}/odds",
        params={
            "apiKey": api_key,
            # `SYNDICATE_NFL_GAME_LINE_REGIONS` (e.g. `eu` = Pinnacle) widens; unset = `region` as before.
            "regions": sport_game_line_regions("nfl", region),
            "markets": markets,
            "oddsFormat": odds_format,
        },
        timeout=20,
    )
    # response.url, not the rebuilt path: the markets= the attribution buckets
    # read live in params, and the recorder redacts apiKey before persisting.
    record_oddsapi_quota(response.headers, sport="nfl", endpoint=response.url)
    response.raise_for_status()
    return response.json()


def choose_bookmaker(bookmakers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not bookmakers:
        return None
    by_name = {str(bookmaker.get("key") or "").lower(): bookmaker for bookmaker in bookmakers}
    for preferred in preferred_books():
        if preferred in by_name:
            return by_name[preferred]
    return bookmakers[0]


def extract_markets(bookmaker: dict[str, Any]) -> dict[str, Any]:
    markets: list[dict[str, Any]] = []
    total_runs = None
    run_line = None

    for market in bookmaker.get("markets", []) or []:
        key = market.get("key")
        outcomes = market.get("outcomes", []) or []
        markets.append({"key": key, "outcomes": outcomes})

        if key in ("totals", "total") and outcomes:
            point = next((outcome.get("point") for outcome in outcomes if outcome.get("point") is not None), None)
            over = next((outcome.get("price") for outcome in outcomes if str(outcome.get("name", "")).lower().startswith("over")), None)
            under = next((outcome.get("price") for outcome in outcomes if str(outcome.get("name", "")).lower().startswith("under")), None)
            total_runs = {"line": point, "over": over, "under": under}

    return {"markets": markets, "moneyline": None, "total_runs": total_runs, "run_line": run_line}


def compose_key(away: str, home: str) -> str:
    return f"{away} @ {home}"


def build_unified_lines(events: list[dict[str, Any]]) -> dict[str, Any]:
    lines: dict[str, Any] = {}
    for event in events:
        try:
            raw_away = event.get("away_team") or event.get("awayTeam") or (event.get("teams") or [None, None])[0]
            raw_home = event.get("home_team") or event.get("homeTeam") or (event.get("teams") or [None, None])[1]
            if not raw_away or not raw_home:
                continue
            away = normalize_team_name(raw_away)
            home = normalize_team_name(raw_home)

            bookmaker = choose_bookmaker(event.get("bookmakers") or [])
            if not bookmaker:
                continue
            extracted = extract_markets(bookmaker)

            moneyline_home = None
            moneyline_away = None
            spread_home = None

            for market in bookmaker.get("markets") or []:
                key = market.get("key")
                outcomes = market.get("outcomes", []) or []
                if key in ("h2h", "moneyline"):
                    for outcome in outcomes:
                        team_name = normalize_team_name(outcome.get("name", ""))
                        if team_name.lower() == home.lower():
                            moneyline_home = outcome.get("price")
                        elif team_name.lower() == away.lower():
                            moneyline_away = outcome.get("price")
                elif key in ("spreads", "spread"):
                    for outcome in outcomes:
                        team_name = normalize_team_name(outcome.get("name", ""))
                        if team_name.lower() == home.lower():
                            spread_home = outcome.get("point")

            unified = {
                "moneyline": {"home": moneyline_home, "away": moneyline_away} if (moneyline_home is not None or moneyline_away is not None) else None,
                "total_runs": extracted.get("total_runs"),
                "run_line": extracted.get("run_line"),
                "markets": extracted.get("markets", []),
            }
            if spread_home is not None:
                unified["run_line"] = {"home": spread_home}

            lines[compose_key(away, home)] = unified
        except Exception:
            continue

    return {"lines": lines, "source": "odds_api", "fetched_at": datetime.now(timezone.utc).isoformat()}


def write_daily_lines(payload: dict[str, Any], *, data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    output = data_dir / f"real_betting_lines_{datetime.now().strftime('%Y_%m_%d')}.json"
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output


def _nfl_gameline_kickoff_shard_enabled() -> bool:
    """File NFL game-line quotes by CENTRAL KICKOFF date (default) or by the UTC capture date (off).

    Off switch: `SYNDICATE_NFL_GAMELINE_QUOTES_KICKOFF_SHARD=0` (also false/no/off) restores the old
    single write under the UTC date of the capture. Default ON, because this file runs as a child of
    `refresh_nfl_oddsapi.py`, which takes its env from the worker that launched it, and the fleet builds
    that env only at `up`: a default-off switch could not be turned on without a full down/up.
    """
    raw = str(os.environ.get("SYNDICATE_NFL_GAMELINE_QUOTES_KICKOFF_SHARD") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _append_nfl_team_book_quotes(
    events: list[dict[str, Any]], *, now: datetime | None = None
) -> dict[str, Any] | None:
    """Every book's game-market price (full game + quarters/halves) into the shared quote log.

    FILED BY THE GAME'S CENTRAL KICKOFF DATE (`odds_book_quotes.kickoff_shard_date`), like the NFL
    and NCAAF prop writers and the NCAAF game-line writer, and like every board reader asks for it.

    THIS USED TO BE THE UTC DATE THE FETCH RAN (`now.date()`), so from 00:00Z -- 6 PM CST -- every
    NFL game-market quote went into TOMORROW's shard. Measured on the fleet 2026-11-15 (lane
    layer2-rail-monitor): Sunday Night Football (PIT @ CIN, kickoff 01:22Z = 7:20 PM CST) had all
    of its in-play game lines in `2026-11-16.jsonl` (1,470 full-game + 376 quarter/half rows) and
    none in `2026-11-15.jsonl` after 23:58:52Z. The 11-15 in-play overlay and `/api/board/live-rail`
    read only the 11-15 grid, so the Games Rail showed SNF with stale pre-game prices all night.
    Every night game is hit: SNF, MNF (7:15 PM CST) and TNF.

    A game's pre-game lines now land in its OWN kickoff date's shard all week instead of being
    spread over every capture day. Every reader already covers that: the board's window reads
    each date's grid (`layer1_board.artifact_read_dates`), the Layer 2 shortlist reads every
    window date's shard, the refresh-worker builds the forward dates of NFL's 7-day window,
    CLV asks the Central date first (`clv_join._candidate_shard_dates`) and the `#802`
    market-gone drop asks the Central kickoff-date file. Lane nfl-gameline-kickoff-shard
    names each reader in its findings file.

    A row with no parseable kickoff is NOT filed under today: an unknown kickoff filed as today's
    is indistinguishable from a real one (`kickoff_shard_date`'s own rule). It is counted, and its
    events are named, on the always-printed `NFL_GAMELINE_QUOTE_SHARD` line.

    Off switch: see `_nfl_gameline_kickoff_shard_enabled`. Returns what was written, for tests and
    callers that want it; never raises -- a quote-log failure must not fail the odds fetch.
    """
    try:
        if not isinstance(events, list) or not events:
            return None
        from syndicate.features.shared.odds_book_quotes import (
            append_book_quotes,
            bucket_quote_rows_by_kickoff_date,
            quote_rows_from_oddsapi_events,
        )

        moment = now or datetime.now(tz=timezone.utc)
        # ONE clock read for every shard: `append_book_quotes` stamps it on each row and into the
        # last-seen state, so two readings would make one observation look like two.
        captured_at = moment.isoformat()
        rows = quote_rows_from_oddsapi_events(events, market_map=_nfl_segment_market_map())
        if not _nfl_gameline_kickoff_shard_enabled():
            capture_date = moment.astimezone(timezone.utc).date().isoformat()
            append_book_quotes(sport="nfl", date_str=capture_date, rows=rows, captured_at=captured_at)
            summary: dict[str, Any] = {
                "basis": "utc_capture",
                "rows": len(rows),
                "shards": {capture_date: len(rows)},
                "unfiled_no_commence_time": 0,
                "unfiled_events": [],
            }
        else:
            buckets, unfiled = bucket_quote_rows_by_kickoff_date(rows)
            for shard_date in sorted(buckets):
                append_book_quotes(sport="nfl", date_str=shard_date, rows=buckets[shard_date], captured_at=captured_at)
            summary = {
                "basis": "kickoff_central",
                "rows": len(rows),
                "shards": {shard_date: len(buckets[shard_date]) for shard_date in sorted(buckets)},
                "unfiled_no_commence_time": len(unfiled),
                "unfiled_events": sorted({str(row.get("event_id") or "?") for row in unfiled}),
            }
        # ALWAYS PRINTED: the branch-ran instrument. `basis` says which filing ran, `shards` where
        # this capture went, and a non-zero `unfiled_no_commence_time` is the count of rows not filed.
        shards_text = ",".join(f"{day}:{count}" for day, count in summary["shards"].items()) or "-"
        print(
            "[odds_book_quotes] NFL_GAMELINE_QUOTE_SHARD"
            f" basis={summary['basis']} captured_at={captured_at} rows={summary['rows']}"
            f" shards={shards_text}"
            f" unfiled_no_commence_time={summary['unfiled_no_commence_time']}"
            f" unfiled_events={','.join(summary['unfiled_events'][:10]) or '-'}",
            flush=True,
        )
        return summary
    except Exception as exc:
        # The token makes this line survive refresh_odds_sources' stdout blanking
        # (_STEP_STDOUT_MARKERS), so a failed append is readable on the fleet.
        print(f"[odds_book_quotes] nfl team odds append FAILED NFL_GAMELINE_QUOTE_SHARD {type(exc).__name__}: {exc}", flush=True)
        return None


def _nfl_segment_market_map() -> dict[str, tuple[str, str]]:
    """Full-game + Q1-Q4/H1-H2 from the shared vocabulary, for TAGGING.

    **THE DOCSTRING THIS REPLACES WAS FALSE, and it is worth saying how.** It
    claimed these keys were used *"both to REQUEST the keys and to TAG the
    returned quotes so the two cannot drift"*. They were only ever tagged with.
    `main()` calls `fetch_odds(api_key=..., region=...)` and never passes
    `markets=`, so the literal default `"h2h,spreads,totals"` went out and the
    36 segment keys reached `quote_rows_from_oddsapi_events` alone -- where a
    key that never arrived can never be tagged.

    The result was dead code that read as alive at every level: the map is
    built, it is passed, `tests/test_all_sports_segment_wiring.py` asserted the
    token `segment_market_keys("nfl")` was present in this file and PASSED, and
    production NFL shards carried zero segment rows. A token is not a request --
    `learnings.md`: presence is not reachability.

    Requesting is now `_fetch_nfl_segments()` below, on the PER-EVENT endpoint,
    because the bulk route this function's map was aimed at 422s
    `INVALID_MARKET` on every one of these keys.
    """
    from syndicate.features.shared.market_segments import full_game_market_keys, segment_market_keys

    return {**full_game_market_keys(), **segment_market_keys("nfl")}


def _fetch_nfl_segments(api_key: str, events: list[dict[str, Any]], *, sport_key: str = "americanfootball_nfl") -> list[dict[str, Any]]:
    """Half/quarter prices for the in-window events, via the PER-EVENT route.

    Same shared implementation NCAAF uses (`shared/segment_odds_fetch.py`), on
    purpose: this file and the preseason one already carried two near-identical
    copies of the segment map, and `learnings.md` records a THIRD instance of
    the same two-copy failure -- *"a comment asking a human to remember is not a
    control"*.

    **Absent means OFF.** With `SYNDICATE_NFL_SEGMENT_MARKETS` unset this makes
    no call and spends no credit.
    """
    from syndicate.features.shared.segment_odds_fetch import fetch_event_segments

    payloads, _stats = fetch_event_segments(
        api_key=api_key,
        sport="nfl",
        sport_key=sport_key,
        base_url=get_base_url(),
        events=events,
        log_prefix="[nfl_odds]",
    )
    return payloads


def main(*, data_dir: Path | None = None) -> Path:
    api_key = _env("ODDS_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ODDS_API_KEY environment variable")
    region = _env("ODDS_API_REGION", "us") or "us"
    events = fetch_odds(api_key=api_key, region=region)
    # The segment pass, on the per-event endpoint. Default OFF; see
    # `_fetch_nfl_segments`. Concatenated rather than merged: `_KEY_FIELDS` in
    # `odds_book_quotes` carries `segment`, so a full-game row and an `h1` row
    # on the same event/book/market are distinct keys.
    segment_payloads = _fetch_nfl_segments(api_key, events)
    # #209 Class A: build_unified_lines keeps ONE book per event
    # (choose_bookmaker) out of a response that already carries several. The
    # unified single-book payload below is unchanged -- the quote log keeps the
    # rest, which is what CLV and best-price grading need.
    _append_nfl_team_book_quotes(events + segment_payloads)
    payload = build_unified_lines(events)
    return write_daily_lines(payload, data_dir=data_dir or Path(__file__).resolve().parents[1] / "data")


if __name__ == "__main__":
    out = main()
    print(f"Saved real odds to {out}")