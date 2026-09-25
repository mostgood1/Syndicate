from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota


ODDS_API_BASE = "https://api.the-odds-api.com/v4"
NHLE_BASE = (os.getenv("NHLE_BASE_URL", "https://api-web.nhle.com/v1") or "https://api-web.nhle.com/v1").rstrip("/")

TEAM_NAME_TO_ABBR = {
    "anaheim ducks": "ANA",
    "utah mammoth": "UTA",
    "utah hockey club": "UTA",
    "utah hc": "UTA",
    "arizona coyotes": "ARI",
    "boston bruins": "BOS",
    "buffalo sabres": "BUF",
    "carolina hurricanes": "CAR",
    "columbus blue jackets": "CBJ",
    "calgary flames": "CGY",
    "chicago blackhawks": "CHI",
    "colorado avalanche": "COL",
    "dallas stars": "DAL",
    "detroit red wings": "DET",
    "edmonton oilers": "EDM",
    "florida panthers": "FLA",
    "los angeles kings": "LAK",
    "minnesota wild": "MIN",
    "montreal canadiens": "MTL",
    "new jersey devils": "NJD",
    "nashville predators": "NSH",
    "new york islanders": "NYI",
    "new york rangers": "NYR",
    "ottawa senators": "OTT",
    "philadelphia flyers": "PHI",
    "pittsburgh penguins": "PIT",
    "san jose sharks": "SJS",
    "seattle kraken": "SEA",
    "st. louis blues": "STL",
    "st louis blues": "STL",
    "tampa bay lightning": "TBL",
    "toronto maple leafs": "TOR",
    "vancouver canucks": "VAN",
    "vegas golden knights": "VGK",
    "winnipeg jets": "WPG",
    "washington capitals": "WSH",
}

TEAM_ABBRS = [
    "ANA", "ARI", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL", "DAL", "DET", "EDM", "FLA", "LAK",
    "MIN", "MTL", "NJD", "NSH", "NYI", "NYR", "OTT", "PHI", "PIT", "SJS", "SEA", "STL", "TBL", "TOR",
    "UTA", "VAN", "VGK", "WPG", "WSH",
]


def _norm_team_name(value: object) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().lower()


def _team_abbr(value: object) -> Optional[str]:
    normalized = _norm_team_name(value)
    if normalized in TEAM_NAME_TO_ABBR:
        return TEAM_NAME_TO_ABBR[normalized]
    raw = str(value or "").strip().upper()
    return raw if raw in set(TEAM_NAME_TO_ABBR.values()) else None


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _market_id_token(value: object) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text.lower()


def _market_id_line_token(value: object) -> str:
    if value in (None, "", "-"):
        return "na"
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.notna(number):
        number_value = float(number)
        if number_value.is_integer():
            return str(int(number_value))
        return format(number_value, "g")
    token = _market_id_token(value)
    return token or "na"


def _nhl_market_id(*, date: str, away_team: object, home_team: object, market_type: object, entity: object, line: object) -> str:
    return "NHL:{date}:{away}@{home}:{market_type}:{entity}:{line}".format(
        date=str(date or "").strip(),
        away=_team_abbr(away_team) or _market_id_token(away_team).upper() or "AWAY",
        home=_team_abbr(home_team) or _market_id_token(home_team).upper() or "HOME",
        market_type=_market_id_token(market_type) or "market",
        entity=_market_id_token(entity) or "entity",
        line=_market_id_line_token(line),
    )


def _nhl_team_market_type(market: object, outcome_name: object) -> str:
    market_key = _market_id_token(market)
    outcome_key = _market_id_token(outcome_name)
    if market_key == "h2h":
        return f"moneyline_{outcome_key or 'team'}"
    if market_key in {"spreads", "spread"}:
        return f"spread_{outcome_key or 'team'}"
    if market_key in {"totals", "total"}:
        return f"total_{outcome_key or 'team'}"
    return market_key or "team_odds"


def _nhl_team_market_line(market: object, outcome_price: object, outcome_point: object) -> object:
    market_key = _market_id_token(market)
    if market_key == "h2h":
        return outcome_price
    return outcome_point if outcome_point not in (None, "") else outcome_price


def _nhl_scoreboard_line(home_goals: object, away_goals: object) -> object:
    home = pd.to_numeric(pd.Series([home_goals]), errors="coerce").iloc[0]
    away = pd.to_numeric(pd.Series([away_goals]), errors="coerce").iloc[0]
    if pd.isna(home) and pd.isna(away):
        return None
    home_value = float(home) if pd.notna(home) else 0.0
    away_value = float(away) if pd.notna(away) else 0.0
    return home_value + away_value


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    try:
        if path.exists() and path.is_file():
            return pd.read_csv(path)
    except Exception:
        pass
    return pd.DataFrame()


class OddsApiClient:
    def __init__(self, api_key: str | None = None, *, rate_limit_per_sec: float = 6.0, timeout: float = 40.0) -> None:
        self.api_key = str(api_key or os.getenv("ODDS_API_KEY") or "").strip()
        if not self.api_key:
            raise RuntimeError("Set ODDS_API_KEY env var or pass api_key to OddsApiClient.")
        self.sleep = 1.0 / max(rate_limit_per_sec, 0.1)
        self.timeout = float(timeout)

    def _get(self, path: str, params: Dict[str, object]) -> Tuple[object, Dict[str, str]]:
        time.sleep(self.sleep)
        response = requests.get(f"{ODDS_API_BASE}{path}", params=params, timeout=self.timeout)
        headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        # Recorded before raise_for_status: a failed call may still be billed,
        # and dropping it would bias measured burn downward (#14).
        # response.url, not path: the markets= the attribution buckets read
        # live in params, and the recorder redacts apiKey before persisting.
        record_oddsapi_quota(headers, sport="nhl", endpoint=str(getattr(response, "url", "") or path))
        try:
            response.raise_for_status()
        except requests.HTTPError:
            safe_url = re.sub(r"(apiKey=)[^&]+", r"\1REDACTED", str(getattr(response, "url", "")))
            raise RuntimeError(f"TheOddsAPI request failed ({response.status_code}) for {safe_url}") from None
        return response.json(), headers

    def list_events(self, sport: str, *, commence_from_iso: str | None = None, commence_to_iso: str | None = None) -> Tuple[List[Dict], Dict[str, str]]:
        params: Dict[str, object] = {"apiKey": self.api_key, "dateFormat": "iso"}
        if commence_from_iso:
            params["commenceTimeFrom"] = commence_from_iso
        if commence_to_iso:
            params["commenceTimeTo"] = commence_to_iso
        payload, headers = self._get(f"/sports/{sport}/events", params)
        return (list(payload) if isinstance(payload, list) else []), headers

    def event_odds(
        self,
        sport: str,
        event_id: str,
        *,
        markets: str,
        regions: str = "us",
        bookmakers: str | None = None,
    ) -> Tuple[Dict, Dict[str, str]]:
        params: Dict[str, object] = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "american",
            "dateFormat": "iso",
        }
        if bookmakers:
            params["bookmakers"] = bookmakers
        payload, headers = self._get(f"/sports/{sport}/events/{event_id}/odds", params)
        if isinstance(payload, dict):
            return payload, headers
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return payload[0], headers
        return {}, headers

    def historical_list_events(self, sport: str, *, snapshot_iso: str) -> Tuple[Dict, Dict[str, str]]:
        return self._get(
            f"/historical/sports/{sport}/events",
            {"apiKey": self.api_key, "date": snapshot_iso, "dateFormat": "iso"},
        )

    def historical_event_odds(
        self,
        sport: str,
        event_id: str,
        *,
        markets: str,
        snapshot_iso: str,
        regions: str = "us",
        bookmakers: str | None = None,
    ) -> Tuple[Dict, Dict[str, str]]:
        params: Dict[str, object] = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "american",
            "dateFormat": "iso",
            "date": snapshot_iso,
        }
        if bookmakers:
            params["bookmakers"] = bookmakers
        payload, headers = self._get(f"/historical/sports/{sport}/events/{event_id}/odds", params)
        if isinstance(payload, dict):
            return payload, headers
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return payload[0], headers
        return {}, headers


# TheOddsAPI lists NHL preseason games under their OWN sport key, and a request to
# `icehockey_nhl` never returns them. Measured 2026-09-19: all 7 preseason games
# generated `anchor_state=no_market` with every odds column blank. Both keys are
# listed on every fetch; out of season the preseason key lists nothing. (The events
# listing itself does not draw on the usage quota.)
NHL_REGULAR_SPORT_KEY = "icehockey_nhl"
NHL_PRESEASON_SPORT_KEY = "icehockey_nhl_preseason"
NHL_SPORT_KEYS: Tuple[str, ...] = (NHL_REGULAR_SPORT_KEY, NHL_PRESEASON_SPORT_KEY)
# Preseason markets are thinner. When a request for the full market list fails on a
# preseason event, it is retried with the core three.
NHL_CORE_TEAM_MARKETS: Tuple[str, ...] = ("h2h", "spreads", "totals")


def _event_sport_key(event: Dict, default: str = NHL_REGULAR_SPORT_KEY) -> str:
    return str(event.get("sport_key") or default).strip() or default


def list_nhl_events(client: "OddsApiClient", *, commence_from_iso: str, commence_to_iso: str) -> List[Dict]:
    """Events for the window across the regular AND preseason keys, each tagged with its own `sport_key`."""
    events: List[Dict] = []
    seen: set[str] = set()
    for sport_key in NHL_SPORT_KEYS:
        try:
            listed, _ = client.list_events(sport_key, commence_from_iso=commence_from_iso, commence_to_iso=commence_to_iso)
        except Exception as exc:
            # The regular key is the season's backbone, so its failure still propagates.
            # A failure on the preseason key must not cost the regular season its board.
            if sport_key == NHL_REGULAR_SPORT_KEY:
                raise
            print(f"[local_nhl_odds] NHL_EVENTS_LIST_FAILED sport_key={sport_key} error={type(exc).__name__}: {exc}", flush=True)
            continue
        for event in listed or []:
            event_id = str(event.get("id") or "")
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            events.append({**event, "sport_key": _event_sport_key(event, sport_key)})
    by_key: Dict[str, int] = {}
    for event in events:
        by_key[event["sport_key"]] = by_key.get(event["sport_key"], 0) + 1
    print(f"[local_nhl_odds] NHL_EVENTS window={commence_from_iso}..{commence_to_iso} by_sport_key={by_key}", flush=True)
    return events


class NhlWebClient:
    def __init__(self, *, rate_limit_per_sec: float = 3.0, timeout: float = 30.0) -> None:
        self.sleep = 1.0 / max(rate_limit_per_sec, 0.1)
        self.timeout = float(timeout)
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": "syndicate-nhl/1.0"})

    def _get(self, path: str) -> Dict:
        time.sleep(self.sleep)
        response = self.session.get(f"{NHLE_BASE}{path if path.startswith('/') else '/' + path}", timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _team_name(team: Dict) -> str:
        place = (team.get("placeName") or {}).get("default") if isinstance(team.get("placeName"), dict) else team.get("placeName")
        common = (team.get("commonName") or {}).get("default") if isinstance(team.get("commonName"), dict) else team.get("commonName")
        return " ".join(f"{place or ''} {common or ''}".split())

    def scoreboard_day(self, date: str) -> List[dict]:
        data = self._get(f"/schedule/{date}")
        rows: List[dict] = []
        for week in data.get("gameWeek", []) or []:
            if week.get("date") != date:
                continue
            for game in week.get("games", []) or []:
                clock = game.get("clock")
                clock_value = None
                if isinstance(clock, dict):
                    clock_value = clock.get("timeRemaining") or clock.get("timeRemainingInPeriod") or clock.get("displayValue")
                elif isinstance(clock, str):
                    clock_value = clock
                period_descriptor = game.get("periodDescriptor") or {}
                rows.append(
                    {
                        "gamePk": int(game.get("id")) if game.get("id") is not None else None,
                        "gameDate": game.get("startTimeUTC") or f"{date}T00:00:00Z",
                        "home": self._team_name(game.get("homeTeam", {})),
                        "away": self._team_name(game.get("awayTeam", {})),
                        # The tri-codes, so a consumer can join on the code
                        # when the display names drift (e.g. a franchise
                        # rename) -- `_apply_nhl_live_scores` keys on both.
                        "home_abbr": (game.get("homeTeam") or {}).get("abbrev"),
                        "away_abbr": (game.get("awayTeam") or {}).get("abbrev"),
                        "home_goals": game.get("homeTeam", {}).get("score"),
                        "away_goals": game.get("awayTeam", {}).get("score"),
                        "gameState": game.get("gameState"),
                        "period": period_descriptor.get("number") or period_descriptor.get("period") or game.get("period"),
                        "clock": clock_value,
                    }
                )
        return rows


def write_scoreboard_snapshot(*, artifact_root: Path, date: str) -> Path:
    out_path = artifact_root / "data" / "odds" / "games" / f"date={date}" / "scoreboard.csv"
    _ensure_parent(out_path)
    client = NhlWebClient()
    rows = client.scoreboard_day(date)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["home_team"] = frame.get("home")
        frame["away_team"] = frame.get("away")
        frame["market_type"] = "scoreboard"
        frame["entity"] = "GAME"
        frame["line"] = frame.apply(lambda row: _nhl_scoreboard_line(row.get("home_goals"), row.get("away_goals")), axis=1)
        frame["market_id"] = frame.apply(
            lambda row: _nhl_market_id(
                date=date,
                away_team=row.get("away_team"),
                home_team=row.get("home_team"),
                market_type=row.get("market_type"),
                entity=row.get("entity"),
                line=row.get("line"),
            ),
            axis=1,
        )
    if out_path.exists():
        existing = _read_csv_if_exists(out_path)
        if not existing.empty and "gamePk" in existing.columns and "gamePk" in frame.columns:
            frame = pd.concat([existing, frame], ignore_index=True).drop_duplicates(subset=["gamePk"], keep="last")
    frame.to_csv(out_path, index=False)
    return out_path


def _date_range_utc(day: datetime) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return (start - timedelta(hours=8), end + timedelta(hours=8))


def _flatten_team_odds(event: dict, bookmaker: dict, market: dict) -> List[dict]:
    rows: List[dict] = []
    for outcome in market.get("outcomes") or []:
        selection = str(outcome.get("name") or "").strip().lower()
        line_value = _nhl_team_market_line(market.get("key"), outcome.get("price"), outcome.get("point"))
        market_type = _nhl_team_market_type(market.get("key"), outcome.get("name"))
        rows.append(
            {
                "event_id": event.get("id"),
                "commence_time": event.get("commence_time"),
                "home": str(event.get("home_team") or "").strip(),
                "away": str(event.get("away_team") or "").strip(),
                "home_team": str(event.get("home_team") or "").strip(),
                "away_team": str(event.get("away_team") or "").strip(),
                "bookmaker_key": bookmaker.get("key"),
                "bookmaker": bookmaker.get("title"),
                "book_last_update": bookmaker.get("last_update"),
                "market": market.get("key"),
                "market_type": market_type,
                "entity": "TEAM" if market.get("key") == "h2h" else selection or "TEAM",
                "outcome_name": outcome.get("name"),
                "outcome_price": outcome.get("price"),
                "outcome_point": outcome.get("point"),
                "line": line_value,
                "market_id": _nhl_market_id(
                    date=str(event.get("commence_time") or "")[:10] or "",
                    away_team=event.get("away_team"),
                    home_team=event.get("home_team"),
                    market_type=market_type,
                    entity=("TEAM" if market.get("key") == "h2h" else selection or "TEAM"),
                    line=line_value,
                ),
            }
        )
    return rows


def collect_oddsapi_team_odds(date: str, *, markets: Optional[Iterable[str]] = None) -> pd.DataFrame:
    client = OddsApiClient()
    day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_utc, end_utc = _date_range_utc(day)
    market_list = list(markets) if markets is not None else [m.strip() for m in os.getenv("TEAM_ODDS_MARKETS", "h2h,spreads,totals").split(",") if m.strip()]
    # `#343`: hockey plays THREE periods, so p1/p2/p3 -- not quarters or halves.
    # Appended rather than replacing, so an env override still caps cost.
    if markets is None:
        from syndicate.features.shared.market_segments import segment_market_keys

        market_list.extend(key for key in segment_market_keys("nhl") if key not in market_list)
    events = list_nhl_events(
        client,
        commence_from_iso=start_utc.isoformat().replace("+00:00", "Z"),
        commence_to_iso=end_utc.isoformat().replace("+00:00", "Z"),
    )
    rows: List[dict] = []
    core_markets = [key for key in market_list if key in NHL_CORE_TEAM_MARKETS]
    for event in events or []:
        sport_key = _event_sport_key(event)
        try:
            odds, _ = client.event_odds(sport_key, str(event.get("id")), markets=",".join(market_list))
        except Exception as exc:
            if sport_key != NHL_PRESEASON_SPORT_KEY or not core_markets or core_markets == market_list:
                raise
            print(
                f"[local_nhl_odds] NHL_PRESEASON_MARKETS_RETRY event_id={event.get('id')} "
                f"error={type(exc).__name__} retry_markets={','.join(core_markets)}",
                flush=True,
            )
            odds, _ = client.event_odds(sport_key, str(event.get("id")), markets=",".join(core_markets))
        for bookmaker in odds.get("bookmakers", []) or []:
            for market in bookmaker.get("markets", []) or []:
                rows.extend(_flatten_team_odds(event, bookmaker, market))
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["date"] = date
        if "market_id" not in frame.columns:
            frame["market_id"] = None
    return frame


def write_team_odds(df: pd.DataFrame, *, artifact_root: Path, date: str, source: str = "oddsapi") -> dict:
    out_dir = artifact_root / "data" / "odds" / "team" / f"date={date}"
    csv_path = out_dir / f"{source}.csv"
    parquet_path = out_dir / f"{source}.parquet"
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = _read_csv_if_exists(csv_path)
    keys = ["market_id"] if "market_id" in existing.columns or (df is not None and not df.empty and "market_id" in df.columns) else ["event_id", "bookmaker_key", "market", "outcome_name", "outcome_point"]
    if existing.empty:
        merged = df.copy()
    elif df.empty:
        merged = existing.copy()
    else:
        merged = pd.concat([existing, df], ignore_index=True)
        if "book_last_update" in merged.columns:
            merged = merged.sort_values("book_last_update").drop_duplicates(subset=keys, keep="last")
        else:
            merged = merged.drop_duplicates(subset=keys, keep="last")
    merged.to_csv(csv_path, index=False)
    try:
        merged.to_parquet(parquet_path, index=False)
    except Exception:
        pass
    return {
        "input_rows": int(len(df.index)) if df is not None else 0,
        "output_rows": int(len(merged.index)) if merged is not None else 0,
        "csv_path": str(csv_path),
        "parquet_path": str(parquet_path),
    }


@dataclass
class RosterPlayer:
    player_id: int
    full_name: str
    position: str
    team_id: int | None


def _current_season_code() -> int:
    today = datetime.utcnow()
    start_year = today.year if today.month >= 7 else (today.year - 1)
    return int(f"{start_year}{start_year + 1}")


def _alias_team_abbr(team_abbr: str) -> str:
    team = str(team_abbr or "").upper()
    if team == "ARI" and _current_season_code() >= 20252026:
        return "UTA"
    return team


def list_teams() -> List[Dict]:
    client = NhlWebClient()
    try:
        payload = client._get("/teams")
        teams = payload.get("teams") if isinstance(payload, dict) else None
        rows: List[Dict] = []
        for team in teams or []:
            name = team.get("name") or team.get("fullName") or team.get("commonName")
            if isinstance(name, dict):
                name = name.get("default")
            rows.append({"id": team.get("id") or team.get("teamId"), "abbreviation": str(team.get("abbrev") or team.get("abbreviation") or "").upper(), "name": name})
        if rows:
            return rows
    except Exception:
        pass
    return [{"id": None, "abbreviation": abbr, "name": abbr} for abbr in TEAM_ABBRS]


def fetch_current_roster(team_abbr: str) -> List[RosterPlayer]:
    client = NhlWebClient()
    payload = client._get(f"/roster/{_alias_team_abbr(team_abbr)}/current")
    rows: List[RosterPlayer] = []
    for key, value in (payload or {}).items():
        if not isinstance(value, list):
            continue
        for player in value:
            first_name = player.get("firstName")
            last_name = player.get("lastName")
            first = first_name.get("default") if isinstance(first_name, dict) else first_name
            last = last_name.get("default") if isinstance(last_name, dict) else last_name
            full_name = " ".join(str(part or "").strip() for part in (first, last)).strip()
            if not player.get("playerId") or not full_name:
                continue
            lower_key = key.lower()
            position = "F" if "forward" in lower_key else "D" if "defen" in lower_key else "G" if "goal" in lower_key else ""
            rows.append(RosterPlayer(player_id=int(player.get("playerId")), full_name=full_name, position=position, team_id=None))
    return rows


def build_all_team_roster_snapshots() -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    seen: set[str] = set()
    for team_abbr in TEAM_ABBRS:
        alias = _alias_team_abbr(team_abbr)
        if alias in seen:
            continue
        seen.add(alias)
        try:
            players = fetch_current_roster(alias)
        except Exception:
            continue
        if not players:
            continue
        frame = pd.DataFrame(
            [{"full_name": player.full_name, "player_id": player.player_id, "team": alias, "position": player.position, "team_id": player.team_id} for player in players]
        )
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["full_name", "player_id", "team", "position", "team_id"])
    combined = pd.concat(frames, ignore_index=True)
    if "team_id" not in combined.columns:
        combined["team_id"] = None
    return combined


def _clean_name_key(value: object) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().lower()


def _board_tz_name() -> str:
    """The timezone the BOARD scopes dates in, read from the board's own env var.

    Hard-coding "America/Chicago" here would be correct today and silently wrong
    the day someone sets `SYNDICATE_BOARD_TZ`. The consumer is
    `layer1_board._BOARD_TZ`; this reads the same variable with the same default
    so the producer and the consumer cannot disagree.
    """
    return os.environ.get("SYNDICATE_BOARD_TZ", "America/Chicago")


def _commence_date_board(commence_time_iso: Optional[str]) -> Optional[str]:
    """The game's calendar date IN THE BOARD'S TIMEZONE, or None.

    NOT `commence_time[:10]` (that is the UTC date, and an evening-Central game
    is the NEXT UTC day) and NOT the collector's run date -- see
    `_append_nhl_book_quotes` for what filing by run date cost.
    """
    if not commence_time_iso:
        return None
    try:
        parsed = datetime.fromisoformat(str(commence_time_iso).replace("Z", "+00:00"))
        return parsed.astimezone(ZoneInfo(_board_tz_name())).strftime("%Y-%m-%d")
    except Exception:
        return None


def _commence_date_et(commence_time_iso: Optional[str]) -> Optional[str]:
    if not commence_time_iso:
        return None
    try:
        parsed = datetime.fromisoformat(str(commence_time_iso).replace("Z", "+00:00"))
        return parsed.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except Exception:
        return None


def collect_oddsapi_props(date: str) -> pd.DataFrame:
    rows: List[Dict] = []
    client = OddsApiClient(rate_limit_per_sec=10.0)
    bookmakers = os.getenv("PROPS_ODDSAPI_BOOKMAKERS", "fanduel,draftkings,pinnacle").strip() or None
    regions = os.getenv("PROPS_ODDSAPI_REGIONS", "us").strip() or "us"
    max_workers = max(1, int(os.getenv("PROPS_ODDSAPI_WORKERS", "6") or "6"))
    markets = "player_points,player_assists,player_goals,player_shots_on_goal"
    market_map = {
        "player_shots_on_goal": "SOG",
        "player_shots_on_goal_alternate": "SOG",
        "shots_on_goal": "SOG",
        "player_shots": "SOG",
        "player_goals": "GOALS",
        "player_goals_alternate": "GOALS",
        "player_assists": "ASSISTS",
        "player_assists_alternate": "ASSISTS",
        "player_points": "POINTS",
        "player_points_alternate": "POINTS",
        "player_saves": "SAVES",
        "goalie_saves": "SAVES",
        "player_blocks": "BLOCKS",
        "player_blocked_shots": "BLOCKS",
    }

    def parse_event_markets(event_obj: Dict) -> None:
        event_id = event_obj.get("id")
        commence_time = event_obj.get("commence_time")
        home_team = event_obj.get("home_team")
        away_team = event_obj.get("away_team")
        commence_date = _commence_date_et(commence_time)
        for bookmaker in event_obj.get("bookmakers", []) or []:
            book_key = bookmaker.get("key") or "oddsapi"
            for market in bookmaker.get("markets", []) or []:
                canonical_market = market_map.get(str(market.get("key") or ""))
                if not canonical_market:
                    continue
                for outcome in market.get("outcomes", []) or []:
                    side = str(outcome.get("name") or "").strip().upper()
                    player = outcome.get("description") or outcome.get("participant") or outcome.get("player_name") or outcome.get("player") or ""
                    try:
                        line = float(outcome.get("point")) if outcome.get("point") is not None else None
                    except Exception:
                        line = None
                    odds = outcome.get("price")
                    if not player or line is None or odds is None or side not in {"OVER", "UNDER"}:
                        continue
                    rows.append(
                        {
                            "market": canonical_market,
                            "player": player,
                            "line": line,
                            "odds": odds,
                            "side": side,
                            "book": book_key,
                            "date": date,
                            "event_id": event_id,
                            "commence_time": commence_time,
                            "commence_date_et": commence_date,
                            "home_team": home_team,
                            "away_team": away_team,
                            "collected_at": _utc_now_iso(),
                        }
                    )

    start_et = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=ZoneInfo("America/New_York"))
    from_dt = start_et.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_dt = (start_et + timedelta(days=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = list_nhl_events(client, commence_from_iso=from_dt, commence_to_iso=to_dt)
    events = [event for event in (events or []) if _commence_date_et(event.get("commence_time")) == date]
    sport_key_by_event = {str(event.get("id")): _event_sport_key(event) for event in events if event.get("id")}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch_event(event_id: str) -> Optional[Dict]:
        use_keys = [key.strip() for key in markets.split(",") if key.strip()]
        sport_key = sport_key_by_event.get(event_id, NHL_REGULAR_SPORT_KEY)
        try:
            event_odds, _ = client.event_odds(sport_key, event_id, markets=",".join(use_keys), regions=regions, bookmakers=bookmakers)
            if isinstance(event_odds, dict) and event_odds.get("bookmakers"):
                return event_odds
        except Exception:
            pass
        try:
            event_odds, _ = client.event_odds(sport_key, event_id, markets=",".join(use_keys), regions=regions, bookmakers=None)
            if isinstance(event_odds, dict) and event_odds.get("bookmakers"):
                return event_odds
        except Exception:
            pass
        for single_market in use_keys:
            try:
                event_odds, _ = client.event_odds(sport_key, event_id, markets=single_market, regions=regions, bookmakers=None)
                if isinstance(event_odds, dict) and event_odds.get("bookmakers"):
                    return event_odds
            except Exception:
                continue
        return None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(fetch_event, str(event.get("id"))): event for event in events if event.get("id")}
        for future in as_completed(future_map):
            payload = future.result()
            if isinstance(payload, dict) and payload.get("bookmakers"):
                parse_event_markets(payload)

    if rows:
        return pd.DataFrame(rows)

    try:
        base_snapshot = f"{date}T17:00:00Z"
        # Regular key only, deliberately: this fallback fires whenever live props come
        # back empty, which is the normal state in preseason. Listing the preseason key
        # here would add a paid historical odds pull to every preseason sweep.
        snapshot_events, _ = client.historical_list_events(NHL_REGULAR_SPORT_KEY, snapshot_iso=base_snapshot)
        historical = snapshot_events.get("data", []) if isinstance(snapshot_events, dict) else []
        for event in [event for event in historical if _commence_date_et(event.get("commence_time")) == date]:
            if not event.get("id"):
                continue
            for snapshot_iso in [base_snapshot, f"{date}T19:00:00Z", f"{date}T22:00:00Z"]:
                try:
                    event_odds, _ = client.historical_event_odds(
                        NHL_REGULAR_SPORT_KEY,
                        str(event.get("id")),
                        markets=markets,
                        snapshot_iso=snapshot_iso,
                        regions=regions,
                        bookmakers=bookmakers,
                    )
                    if isinstance(event_odds, dict) and event_odds.get("bookmakers"):
                        parse_event_markets(event_odds)
                except Exception:
                    continue
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(rows)


def _load_cached_roster_enrichment() -> Optional[pd.DataFrame]:
    try:
        models_root = Path(os.getenv("SYNDICATE_DATA_ROOT") or "data") / "nhl_source" / "data" / "models"
        snapshots = sorted(models_root.glob("roster_snapshot_*.json"))
        if snapshots:
            frame = pd.read_json(snapshots[-1])
            if not frame.empty:
                return frame
    except Exception:
        pass
    return None


def normalize_player_names(raw: pd.DataFrame, roster_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if raw.empty:
        raw = raw.copy()
        raw["player_id"] = None
        raw["team"] = None
        return raw
    frame = raw.copy()
    frame["player_clean"] = frame["player"].map(_clean_name_key)
    frame["player_squash"] = frame["player_clean"].map(lambda value: re.sub(r"[^a-z0-9]", "", str(value or "").lower()))
    if roster_df is None or roster_df.empty:
        frame["player_id"] = None
        frame["team"] = None
        return frame

    roster = roster_df.copy()
    roster["full_name"] = roster["full_name"].astype(str)
    roster["full_name_clean"] = roster["full_name"].map(_clean_name_key)
    roster["full_name_squash"] = roster["full_name_clean"].map(lambda value: re.sub(r"[^a-z0-9]", "", str(value or "").lower()))

    def initials_key(value: str) -> set[str]:
        parts = [part for part in str(value or "").split(" ") if part]
        if len(parts) < 2:
            return set()
        first = parts[0]
        last = parts[-1]
        compact = re.split(r"[-\s]+", first)
        initials = "".join(part[0] for part in compact if part)
        keys = {f"{first[0]} {last}", f"{first[0]}{last}", re.sub(r"[^a-z0-9]", "", f"{first[0]} {last}")}
        if initials and initials != first[:1]:
            keys.update({f"{initials} {last}", f"{initials}{last}", re.sub(r"[^a-z0-9]", "", f"{initials} {last}")})
        return {key for key in keys if key}

    exact = dict(zip(roster["full_name_clean"], roster["player_id"]))
    squash = dict(zip(roster["full_name_squash"], roster["player_id"]))
    team_exact = dict(zip(roster["full_name_clean"], roster.get("team", pd.Series([None] * len(roster)))))
    variant_map: Dict[str, object] = {}
    for _, row in roster.iterrows():
        for key in initials_key(str(row.get("full_name_clean") or "")):
            variant_map.setdefault(key, row.get("player_id"))

    player_ids = frame["player_clean"].map(exact).fillna(frame["player_squash"].map(squash))
    missing_mask = player_ids.isna()
    if missing_mask.any():
        player_ids.loc[missing_mask] = frame.loc[missing_mask, "player_clean"].map(
            lambda value: next((variant_map.get(key) for key in initials_key(str(value or "")) if variant_map.get(key) is not None), None)
        )
    frame["player_id"] = player_ids
    frame["team"] = frame["player_clean"].map(team_exact).map(_team_abbr)
    return frame


def combine_over_under(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "player_id", "player_name", "team", "home_team", "away_team", "market", "market_type", "entity", "line", "over_price", "under_price", "book", "first_seen_at", "last_seen_at", "is_current"])
    working = df[df["market"].isin(["SOG", "GOALS", "SAVES", "ASSISTS", "POINTS", "BLOCKS"])].copy()
    for column in ["player_id", "home_team", "away_team"]:
        if column not in working.columns:
            working[column] = None
    grouped_rows: List[Dict] = []
    now_iso = _utc_now_iso()

    def player_key(row: pd.Series) -> Optional[str]:
        player_id = row.get("player_id")
        if pd.notna(player_id):
            return f"id::{player_id}"
        player_name = str(row.get("player") or "").strip().lower()
        return f"name::{player_name}" if player_name else None

    working["player_key"] = working.apply(player_key, axis=1)
    working = working[working["player_key"].notna()].copy()
    for (date, player_key_value, market, line, book), group in working.groupby(["date", "player_key", "market", "line", "book"], dropna=False):
        over_row = group[group["side"] == "OVER"].sort_values("collected_at").tail(1)
        under_row = group[group["side"] == "UNDER"].sort_values("collected_at").tail(1)
        grouped_rows.append(
            {
                "date": date,
                "player_id": over_row["player_id"].dropna().iloc[0] if not over_row.empty and over_row["player_id"].dropna().shape[0] else (under_row["player_id"].dropna().iloc[0] if not under_row.empty and under_row["player_id"].dropna().shape[0] else None),
                "player_name": (over_row["player"].iloc[0] if not over_row.empty else (under_row["player"].iloc[0] if not under_row.empty else None)),
                "team": (over_row["team"].iloc[0] if not over_row.empty else (under_row["team"].iloc[0] if not under_row.empty else None)),
                "home_team": (over_row["home_team"].iloc[0] if not over_row.empty and "home_team" in over_row.columns else (under_row["home_team"].iloc[0] if not under_row.empty and "home_team" in under_row.columns else None)),
                "away_team": (over_row["away_team"].iloc[0] if not over_row.empty and "away_team" in over_row.columns else (under_row["away_team"].iloc[0] if not under_row.empty and "away_team" in under_row.columns else None)),
                "market": market,
                "market_type": _market_id_token(market),
                "entity": _market_id_token(over_row["player"].iloc[0] if not over_row.empty else (under_row["player"].iloc[0] if not under_row.empty else None)),
                "line": line,
                "over_price": int(over_row["odds"].iloc[0]) if not over_row.empty and pd.notna(over_row["odds"].iloc[0]) else None,
                "under_price": int(under_row["odds"].iloc[0]) if not under_row.empty and pd.notna(under_row["odds"].iloc[0]) else None,
                "book": book,
                "first_seen_at": over_row["collected_at"].iloc[0] if not over_row.empty else (under_row["collected_at"].iloc[0] if not under_row.empty else now_iso),
                "last_seen_at": now_iso,
                "is_current": True,
                "market_id": _nhl_market_id(
                    date=date,
                    away_team=(over_row["away_team"].iloc[0] if not over_row.empty and "away_team" in over_row.columns else (under_row["away_team"].iloc[0] if not under_row.empty and "away_team" in under_row.columns else None)),
                    home_team=(over_row["home_team"].iloc[0] if not over_row.empty and "home_team" in over_row.columns else (under_row["home_team"].iloc[0] if not under_row.empty and "home_team" in under_row.columns else None)),
                    market_type=_market_id_token(market),
                    entity=_market_id_token(over_row["player"].iloc[0] if not over_row.empty else (under_row["player"].iloc[0] if not under_row.empty else None)),
                    line=line,
                ),
            }
        )
    return pd.DataFrame(grouped_rows)


def write_props(df: pd.DataFrame, *, artifact_root: Path, date: str, source: str = "oddsapi") -> str:
    out_dir = artifact_root / "data" / "props" / "player_props_lines" / f"date={date}"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{source}.csv"
    parquet_path = out_dir / f"{source}.parquet"
    existing = _read_csv_if_exists(csv_path)
    if (df is None or df.empty) and not existing.empty:
        if not csv_path.exists():
            existing.to_csv(csv_path, index=False)
        return str(parquet_path if parquet_path.exists() else csv_path)
    working = df.copy() if df is not None else pd.DataFrame()
    for column in ["date", "player_id", "player_name", "team", "home_team", "away_team", "market", "market_type", "entity", "line", "over_price", "under_price", "book", "first_seen_at", "last_seen_at", "is_current", "market_id"]:
        if column not in working.columns:
            working[column] = None
        if column not in existing.columns:
            existing[column] = None
    def key_row(row: pd.Series) -> Optional[str]:
        player_id = row.get("player_id")
        if pd.notna(player_id):
            return f"id::{player_id}"
        player_name = str(row.get("player_name") or "").strip().lower()
        return f"name::{player_name}" if player_name else None
    existing = existing.copy()
    working = working.copy()
    existing["_merge_key"] = existing.apply(key_row, axis=1)
    working["_merge_key"] = working.apply(key_row, axis=1)
    existing["is_current"] = False
    working["is_current"] = True
    subset = ["date", "_merge_key", "market", "line", "book"]
    merged = pd.concat([existing, working], ignore_index=True)
    merged.sort_values(["date", "last_seen_at"], inplace=True)
    merged = merged.drop_duplicates(subset=["market_id"] if "market_id" in merged.columns else subset, keep="last")
    current_keys = working[subset].drop_duplicates().copy()
    current_keys["__cur"] = True
    merged = merged.merge(current_keys, on=subset, how="left")
    merged["is_current"] = merged["__cur"].fillna(False)
    if "__cur" in merged.columns:
        merged.drop(columns=["__cur"], inplace=True)
    try:
        merged.to_parquet(parquet_path, index=False, engine="pyarrow")
    except Exception:
        pass
    merged.to_csv(csv_path, index=False)
    return str(parquet_path if parquet_path.exists() else csv_path)


def _nhl_segment_of(raw_market: object) -> tuple[str, str]:
    """`#343`: (segment, canonical market) for an NHL market key.

    Hockey plays three PERIODS -- p1/p2/p3. Both values come from one map so a
    key this module requested cannot be written under the wrong interval: a
    `totals_p2` tagged `full` would show a second-period total as a full-game
    line, which is worse than never asking for it.
    """
    from syndicate.features.shared.market_segments import full_game_market_keys, segment_market_keys

    key = str(raw_market or "")
    mapped = {**full_game_market_keys(), **segment_market_keys("nhl")}.get(key)
    return mapped if mapped else ("full", key)


def _append_nhl_book_quotes(frame, *, date: str, kind: str) -> dict:
    """Route NHL's already-multi-book frames into the shared quote log.

    Like soccer and NCAAB, NHL was never a Class A capture defect -- both
    collectors loop every bookmaker. What it lacked was the SHARED SHAPE, so
    cross-sport CLV/best-price work had to know NHL's column names
    (`bookmaker_key`, `outcome_price`, `outcome_name`) to read it at all.

    Team odds carry `book_last_update`, a real book clock. Props do not -- the
    props flattener never kept `last_update` -- so those rows get
    `book_updated_at: None`, which is deliberately NOT backfilled with loop time
    (see QUOTE_FIELDS). Unknown must stay unknown.

    Never raises: a logging side-effect must not fail an odds collection.
    """
    try:
        if frame is None or getattr(frame, "empty", True):
            return
        from syndicate.features.shared.odds_book_quotes import append_book_quotes

        rows: List[dict] = []
        for record in frame.to_dict("records"):
            if kind == "prop":
                side = str(record.get("side") or "").strip().lower()
                rows.append(
                    {
                        "kind": "prop",
                        "event_id": record.get("event_id"),
                        "commence_time": record.get("commence_time"),
                        "home_team": record.get("home_team"),
                        "away_team": record.get("away_team"),
                        "bookmaker": record.get("book"),
                        "market": _nhl_segment_of(record.get("market"))[1],
                        "segment": _nhl_segment_of(record.get("market"))[0],
                        "selection": side or None,
                        "player_name": record.get("player"),
                        "line": record.get("line"),
                        "price": record.get("odds"),
                        "book_updated_at": None,
                    }
                )
            else:
                outcome = str(record.get("outcome_name") or "").strip()
                home = str(record.get("home_team") or "").strip()
                away = str(record.get("away_team") or "").strip()
                lowered = outcome.lower()
                if lowered.startswith("over"):
                    selection = "over"
                elif lowered.startswith("under"):
                    selection = "under"
                elif outcome and outcome == home:
                    selection = "home"
                elif outcome and outcome == away:
                    selection = "away"
                else:
                    selection = lowered or None
                rows.append(
                    {
                        "kind": "game",
                        "event_id": record.get("event_id"),
                        "commence_time": record.get("commence_time"),
                        "home_team": home,
                        "away_team": away,
                        "bookmaker": record.get("bookmaker_key") or record.get("bookmaker"),
                        "market": _nhl_segment_of(record.get("market"))[1],
                        "segment": _nhl_segment_of(record.get("market"))[0],
                        "selection": selection,
                        "player_name": None,
                        "line": record.get("outcome_point") if record.get("outcome_point") is not None else record.get("line"),
                        "price": record.get("outcome_price"),
                        "book_updated_at": record.get("book_last_update"),
                    }
                )
        # SHARDED BY THE GAME'S DATE, NOT THE COLLECTOR'S RUN DATE.
        #
        # This filed EVERY row under `date` -- the run/partition date. The fetch
        # window is deliberately +/-8h (`_date_range_utc`), so a run for
        # 2026-09-25 sweeps up the previous evening's Central games and filed
        # them as 09-25. Measured on production 2026-09-25: the NHL board grid
        # for 09-25 held 18 rows and Layer 1 dropped ALL 18 as
        # `rows_other_dates {2026-09-24: 18}`, so NHL had ZERO board rows on a
        # night it had four games -- and the live re-sim, whose whole chain was
        # fixed the same day, had nothing to join to.
        #
        # A row's own `commence_time` is the only authority on which slate it
        # belongs to. Rows that carry none fall back to the run date and are
        # COUNTED, never silently merged.
        buckets: dict[str, list[dict]] = {}
        undated = 0
        for row in rows:
            bucket = _commence_date_board(row.get("commence_time"))
            if bucket is None:
                bucket = str(date)
                undated += 1
            buckets.setdefault(bucket, []).append(row)
        for bucket_date, bucket_rows in sorted(buckets.items()):
            append_book_quotes(
                sport="nhl",
                date_str=bucket_date,
                rows=bucket_rows,
                captured_at=_utc_now_iso(),
            )
        # OBSERVABLE ON PURPOSE. The failure above was invisible for days because
        # nothing ever said which slate the captured rows landed on.
        distribution = {
            "kind": kind,
            "run_date": str(date),
            "by_game_date": {k: len(v) for k, v in sorted(buckets.items())},
            "undated": int(undated),
            "tz": _board_tz_name(),
        }
        # THE PRINT IS FOR A HUMAN RUNNING THIS LOCALLY AND NOTHING ELSE.
        # `refresh_odds_sources._run_command` runs every producer under
        # `subprocess.run(capture_output=True)` and DISCARDS a successful step's
        # stdout, so gating a deploy on this line is gating on silence -- which
        # is exactly what was done on 2026-09-25 and had to be retracted. The
        # RETURN VALUE is the emitter production can hear; the caller writes it
        # beside the other artifacts, where the publisher sweeps it and
        # `/api/ops/artifacts/stream` can read it.
        print(
            f"[local_nhl_odds] NHL_QUOTE_SHARDS {json.dumps(distribution, sort_keys=True)}",
            flush=True,
        )
        return distribution
    except Exception as exc:  # noqa: BLE001
        print(f"[odds_book_quotes] nhl {kind} append FAILED {type(exc).__name__}: {exc}")
        # A FAILURE IS A READING TOO. Returning None here would make "the append
        # blew up" indistinguishable from "nothing was captured" in the artifact.
        return {
            "kind": kind,
            "run_date": str(date),
            "by_game_date": {},
            "undated": 0,
            "tz": _board_tz_name(),
            "error": f"{type(exc).__name__}: {exc}",
        }


def collect_and_write_player_props(*, artifact_root: Path, date: str, source: str = "oddsapi") -> Dict:
    if str(source or "oddsapi").strip().lower() != "oddsapi":
        raise RuntimeError("Syndicate-owned NHL runner currently supports props-source=oddsapi only.")
    roster_df = _load_cached_roster_enrichment()
    if roster_df is None or roster_df.empty:
        roster_df = build_all_team_roster_snapshots()
    raw = collect_oddsapi_props(date)
    _append_nhl_book_quotes(raw, date=date, kind="prop")
    normalized = normalize_player_names(raw, roster_df)
    combined = combine_over_under(normalized)
    output_path = write_props(combined, artifact_root=artifact_root, date=date, source="oddsapi")
    return {"raw_count": int(len(raw.index)), "combined_count": int(len(combined.index)), "output_path": output_path}


def _write_quote_shard_report(*, artifact_root: Path, date: str, distribution: dict | None) -> Optional[Path]:
    """Put the shard distribution where PRODUCTION can read it.

    Under the artifact root, so the publisher's sweep carries it and
    `/api/ops/artifacts/stream?path=nhl_source/data/odds/quote_shards/<date>.json`
    serves it -- the same route that already serves this sport's odds history.
    A `print` cannot do this job: the orchestrator discards a successful step's
    stdout, so the line exists only for a local run.
    """
    if not isinstance(distribution, dict):
        return None
    try:
        out_dir = Path(artifact_root) / "data" / "odds" / "quote_shards"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{date}.json"
        payload = dict(distribution)
        payload["written_at"] = _utc_now_iso()
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path
    except Exception as exc:  # noqa: BLE001
        print(f"[local_nhl_odds] NHL_QUOTE_SHARD_REPORT_FAILED {type(exc).__name__}: {exc}", flush=True)
        return None


def collect_and_write_team_odds(*, artifact_root: Path, date: str, markets: str = "h2h,spreads,totals") -> Dict:
    market_list = [market.strip() for market in str(markets or "h2h,spreads,totals").split(",") if market.strip()]
    frame = collect_oddsapi_team_odds(date, markets=market_list if market_list else None)
    shards = _append_nhl_book_quotes(frame, date=date, kind="game")
    _write_quote_shard_report(artifact_root=artifact_root, date=date, distribution=shards)
    result = write_team_odds(frame, artifact_root=artifact_root, date=date, source="oddsapi")
    if isinstance(result, dict):
        result["quote_shards"] = shards
    return result
