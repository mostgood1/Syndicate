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
            "regions": region,
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


def _append_nfl_team_book_quotes(events: list[dict[str, Any]]) -> None:
    """Every book's game-market price into the shared quote log.

    Sharded by the UTC date this ran rather than by week: unlike the props
    fetchers this one has no season/week argument to key on, and team odds are
    refreshed on a daily cadence. Never raises.
    """
    try:
        if not isinstance(events, list) or not events:
            return
        from syndicate.features.shared.odds_book_quotes import append_book_quotes, quote_rows_from_oddsapi_events

        now = datetime.now(tz=timezone.utc)
        rows = quote_rows_from_oddsapi_events(events, market_map=_nfl_segment_market_map())
        append_book_quotes(
            sport="nfl",
            date_str=now.date().isoformat(),
            rows=rows,
            captured_at=now.isoformat(),
        )
    except Exception as exc:
        print(f"[odds_book_quotes] nfl team odds append FAILED {type(exc).__name__}: {exc}")


def _nfl_segment_market_map() -> dict[str, tuple[str, str]]:
    """`#343`: full-game + Q1-Q4/H1-H2 from the shared vocabulary, used both to
    REQUEST the keys and to TAG the returned quotes so the two cannot drift."""
    from syndicate.features.shared.market_segments import full_game_market_keys, segment_market_keys

    return {**full_game_market_keys(), **segment_market_keys("nfl")}


def main(*, data_dir: Path | None = None) -> Path:
    api_key = _env("ODDS_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ODDS_API_KEY environment variable")
    region = _env("ODDS_API_REGION", "us") or "us"
    events = fetch_odds(api_key=api_key, region=region)
    # #209 Class A: build_unified_lines keeps ONE book per event
    # (choose_bookmaker) out of a response that already carries several. The
    # unified single-book payload below is unchanged -- the quote log keeps the
    # rest, which is what CLV and best-price grading need.
    _append_nfl_team_book_quotes(events)
    payload = build_unified_lines(events)
    return write_daily_lines(payload, data_dir=data_dir or Path(__file__).resolve().parents[1] / "data")


if __name__ == "__main__":
    out = main()
    print(f"Saved real odds to {out}")