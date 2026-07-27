"""#84. Park weather for MLB from the National Weather Service.

Wind and temperature are the one genuinely missing MODEL INPUT among the
event-feed candidates surveyed 2026-07-27: totals and HR likelihoods move with
wind in a way lineups don't capture, park factors already exist as the join
point, and NWS is free, keyless, and reliable. This script only FETCHES AND
STORES -- joining the artifact into the sim is the open half of #84, so until
then this is context for the board and a trigger input, not a model feature.

Scope note: general news/social watchers were considered and rejected in the
same survey -- by the time news is public the line has moved, and the steam
detector (#83) reads that movement directly. Weather is different: it is
forecastable ahead of the market's full adjustment and machine-readable.

NWS etiquette: a real User-Agent, one points lookup + one hourly forecast per
park with a game today, designed to run at most hourly (the loop gates it).
Every park fails open independently -- a missing forecast costs that park's
context, never the run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.refresh_state_store import data_root  # noqa: E402

_USER_AGENT = "syndicate-mlb-weather/1.0 (ops@syndicate.local)"
_HOURS_KEPT = 14

# Team name (as OddsAPI's game-lines snapshot spells home_team) -> park coords.
# Roofed/retractable parks are still fetched: "roof=True" is carried so the
# consumer can discount wind, which beats silently omitting the park.
STADIUM_COORDS: dict[str, dict[str, object]] = {
    "Arizona Diamondbacks": {"lat": 33.4453, "lon": -112.0667, "roof": True},
    "Atlanta Braves": {"lat": 33.8907, "lon": -84.4677, "roof": False},
    "Baltimore Orioles": {"lat": 39.2839, "lon": -76.6217, "roof": False},
    "Boston Red Sox": {"lat": 42.3467, "lon": -71.0972, "roof": False},
    "Chicago Cubs": {"lat": 41.9484, "lon": -87.6553, "roof": False},
    "Chicago White Sox": {"lat": 41.8300, "lon": -87.6339, "roof": False},
    "Cincinnati Reds": {"lat": 39.0975, "lon": -84.5066, "roof": False},
    "Cleveland Guardians": {"lat": 41.4962, "lon": -81.6852, "roof": False},
    "Colorado Rockies": {"lat": 39.7559, "lon": -104.9942, "roof": False},
    "Detroit Tigers": {"lat": 42.3390, "lon": -83.0485, "roof": False},
    "Houston Astros": {"lat": 29.7573, "lon": -95.3555, "roof": True},
    "Kansas City Royals": {"lat": 39.0517, "lon": -94.4803, "roof": False},
    "Los Angeles Angels": {"lat": 33.8003, "lon": -117.8827, "roof": False},
    "Los Angeles Dodgers": {"lat": 34.0739, "lon": -118.2400, "roof": False},
    "Miami Marlins": {"lat": 25.7781, "lon": -80.2196, "roof": True},
    "Milwaukee Brewers": {"lat": 43.0280, "lon": -87.9712, "roof": True},
    "Minnesota Twins": {"lat": 44.9817, "lon": -93.2776, "roof": False},
    "New York Mets": {"lat": 40.7571, "lon": -73.8458, "roof": False},
    "New York Yankees": {"lat": 40.8296, "lon": -73.9262, "roof": False},
    # Sacramento interim park; update on relocation.
    "Athletics": {"lat": 38.5804, "lon": -121.5133, "roof": False},
    "Oakland Athletics": {"lat": 38.5804, "lon": -121.5133, "roof": False},
    "Philadelphia Phillies": {"lat": 39.9061, "lon": -75.1665, "roof": False},
    "Pittsburgh Pirates": {"lat": 40.4469, "lon": -80.0057, "roof": False},
    "San Diego Padres": {"lat": 32.7076, "lon": -117.1570, "roof": False},
    "San Francisco Giants": {"lat": 37.7786, "lon": -122.3893, "roof": False},
    "Seattle Mariners": {"lat": 47.5914, "lon": -122.3325, "roof": True},
    "St. Louis Cardinals": {"lat": 38.6226, "lon": -90.1928, "roof": False},
    "Tampa Bay Rays": {"lat": 27.7683, "lon": -82.6534, "roof": True},
    "Texas Rangers": {"lat": 32.7473, "lon": -97.0824, "roof": True},
    "Toronto Blue Jays": {"lat": 43.6414, "lon": -79.3894, "roof": True},
    "Washington Nationals": {"lat": 38.8730, "lon": -77.0074, "roof": True},
}


def _get_json(url: str, *, timeout: float = 20.0) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/geo+json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_wind_mph(value: object) -> float | None:
    """NWS reports windSpeed as text like "10 mph" or "5 to 10 mph"."""
    text = str(value or "").strip().lower().replace("mph", "").strip()
    if not text:
        return None
    parts = [piece.strip() for piece in text.split("to")]
    try:
        numbers = [float(piece) for piece in parts if piece]
    except ValueError:
        return None
    return max(numbers) if numbers else None


def trim_hourly_periods(periods: list, *, now_epoch: float, hours: int = _HOURS_KEPT) -> list[dict]:
    """The next `hours` of hourly periods, normalized to what the sim/board
    consume: start time, temp F, wind mph, wind direction."""
    out: list[dict] = []
    horizon = now_epoch + hours * 3600
    for period in periods or []:
        if not isinstance(period, dict):
            continue
        try:
            start = datetime.fromisoformat(str(period.get("startTime") or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if start.tzinfo is None:
            continue
        epoch = start.timestamp()
        if epoch < now_epoch - 3600 or epoch > horizon:
            continue
        out.append(
            {
                "t": start.isoformat(timespec="minutes"),
                "temp_f": period.get("temperature") if isinstance(period.get("temperature"), (int, float)) else None,
                "wind_mph": parse_wind_mph(period.get("windSpeed")),
                "wind_dir": str(period.get("windDirection") or "").strip() or None,
            }
        )
    return out


def _todays_home_teams(date_str: str) -> list[str]:
    token = date_str.replace("-", "_")
    candidates = (
        data_root() / "mlb_source" / "source_artifacts" / "data" / "daily" / "snapshots" / date_str / "oddsapi_game_lines.json",
        data_root() / "mlb_source" / "source_artifacts" / "data" / "market" / "oddsapi" / f"oddsapi_game_lines_{token}.json",
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        games = payload.get("games") if isinstance(payload, dict) else None
        if not isinstance(games, list):
            continue
        teams = sorted({str(g.get("home_team") or "").strip() for g in games if isinstance(g, dict) and str(g.get("home_team") or "").strip()})
        if teams:
            return teams
    return []


def fetch_weather_for_date(date_str: str) -> dict:
    now_epoch = datetime.now(timezone.utc).timestamp()
    teams = _todays_home_teams(date_str)
    parks: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for team in teams:
        coords = STADIUM_COORDS.get(team)
        if not coords:
            errors[team] = "no_stadium_coords"
            continue
        try:
            points = _get_json(f"https://api.weather.gov/points/{coords['lat']},{coords['lon']}")
            forecast_url = str(((points.get("properties") or {}).get("forecastHourly")) or "")
            if not forecast_url:
                errors[team] = "no_forecast_url"
                continue
            forecast = _get_json(forecast_url)
            periods = (forecast.get("properties") or {}).get("periods") or []
            parks[team] = {
                "lat": coords["lat"],
                "lon": coords["lon"],
                "roof": bool(coords.get("roof")),
                "hourly": trim_hourly_periods(periods, now_epoch=now_epoch),
            }
        except Exception as exc:  # per-park fail-open
            errors[team] = f"{type(exc).__name__}: {exc}"
    return {
        "date": date_str,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "parks": parks,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch NWS park weather for today's MLB slate.")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    document = fetch_weather_for_date(args.date)
    out_path = data_root() / "mlb_source" / "source_artifacts" / "data" / "weather" / f"weather_{args.date}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.parent / f"{out_path.name}.{os.getpid()}.tmp"
    temp_path.write_text(json.dumps(document, indent=None, separators=(",", ":")), encoding="utf-8")
    os.replace(temp_path, out_path)
    print(
        f"[mlb_weather] WEATHER_WRITTEN date={args.date} parks={len(document['parks'])} "
        f"errors={len(document['errors'])} path={out_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
