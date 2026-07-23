from __future__ import annotations

import logging
from functools import lru_cache
from datetime import date
from datetime import datetime
import json
from pathlib import Path
from typing import Any
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from syndicate.features.shared.odds_control_plane import current_odds_root_for_sport
from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.source_roots import preferred_source_roots
from syndicate.features.shared.timezone import central_today
from syndicate.features.shared.timezone import central_today_iso
_LOG = logging.getLogger(__name__)


def _source_roots() -> list[Path]:
    return preferred_artifact_roots(
        __file__,
        env_var="SYNDICATE_WNBA_SOURCE_ROOT",
        local_dir_name="wnba_source",
    )


def default_wnba_source_root() -> Path:
    return preferred_source_roots(
        __file__,
        env_var="SYNDICATE_WNBA_SOURCE_ROOT",
        local_dir_name="wnba_source",
    )[0]


def processed_root() -> Path:
    return current_odds_root_for_sport("wnba")


def _strict_artifact_path(filename: str, subdir: tuple[str, ...]) -> Path:
    roots = _source_roots()
    for root in roots:
        candidate = root.joinpath("data", "processed", *subdir, filename)
        try:
            if candidate.exists() and candidate.is_file():
                return candidate
        except OSError:
            continue

    missing_path = processed_root().joinpath(*subdir, filename)
    _LOG.error("Missing WNBA artifact: %s", missing_path)
    raise FileNotFoundError(f"Missing WNBA artifact: {missing_path}")


_HAS_GAMES_CONFIRMED_TRUE_CACHE: set[str] = set()


def has_games_for_date(date_str: str) -> bool | None:
    selected_date = str(date_str or "").strip()
    if not selected_date:
        return None

    if selected_date in _HAS_GAMES_CONFIRMED_TRUE_CACHE:
        return True
    # Trusting "some per-date artifact exists" as proof of real games is
    # safe for a PAST date -- it's immutable, and the artifact was built
    # when the slate was genuinely being tracked. It is NOT safe for TODAY:
    # this session traced a chain of stale same-day artifacts
    # (game_cards_{date}.csv, recommendations_slate_{date}.json) that can
    # persist from a prior real slate day's build even once today is
    # confirmed empty (e.g. an All-Star break), which made this shortcut
    # return True without ever checking the actual schedule -- the root
    # cause of a board that kept showing a stale slate under today's date
    # no matter how thoroughly the game_cards artifact itself got fixed.
    # Always fall through to a real ESPN check for today specifically.
    if selected_date != central_today_iso() and selected_date in available_dates():
        _HAS_GAMES_CONFIRMED_TRUE_CACHE.add(selected_date)
        return True

    # No lru_cache here: a False/None verdict is only ever a snapshot of one
    # ESPN scoreboard call and can flip true later the same day (games not
    # yet listed, or a transient request failure) -- caching it would
    # silently freeze "no games today" for the rest of the process's life.
    # A confirmed True is stable and safe to remember above.
    score_date = selected_date.replace("-", "")
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={score_date}"
    request = urllib_request.Request(url, headers={"User-Agent": "Syndicate-WNBA/1.0"})
    try:
        with urllib_request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    events = payload.get("events") if isinstance(payload, dict) else []
    if not isinstance(events, list):
        return None
    result = bool(events)
    if result:
        _HAS_GAMES_CONFIRMED_TRUE_CACHE.add(selected_date)
    return result


def processed_path(filename: str) -> Path:
    return _strict_artifact_path(filename, ())


def processed_path_or_default(filename: str) -> Path:
    # Same lookup as processed_path, but for callers that need *a* path to
    # display or probe with .exists() rather than one guaranteed to already
    # hold real content -- e.g. an archive/picks page rendering an empty
    # state for a date with no published artifacts still needs a source_path
    # string to show, and shouldn't 500 just because that path doesn't
    # resolve to a real file yet.
    try:
        return _strict_artifact_path(filename, ())
    except FileNotFoundError:
        return processed_root() / filename


def live_snapshot_path(filename: str) -> Path:
    return _strict_artifact_path(filename, ("live_snapshots",))


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return central_today()


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def available_dates() -> list[str]:
    return list(_available_dates_cached(_source_roots_signature()))


def default_date() -> str:
    return central_today_iso()


def default_date_for_season(season: int) -> str:
    today_value = central_today_iso()
    if today_value.startswith(f"{int(season)}-"):
        return today_value
    season_str = str(int(season))
    season_dates = [value for value in available_dates() if str(value).startswith(f"{season_str}-")]
    if season_dates:
        return season_dates[-1]
    return default_date()


def _source_roots_signature() -> tuple[tuple[str, int], ...]:
    signature: list[tuple[str, int]] = []
    for root in _source_roots():
        processed_dir = root / "data" / "processed"
        try:
            mtime_ns = int(processed_dir.stat().st_mtime_ns) if processed_dir.exists() else 0
        except OSError:
            mtime_ns = 0
        signature.append((str(processed_dir).lower(), mtime_ns))
    return tuple(signature)


@lru_cache(maxsize=8)
def _available_dates_cached(signature: tuple[tuple[str, int], ...]) -> tuple[str, ...]:
    dates: set[str] = set()
    for root in _source_roots():
        processed_dir = root / "data" / "processed"
        if not processed_dir.exists():
            continue
        for pattern in ("game_cards_*.csv", "recommendations_slate_*.json"):
            for path in sorted(processed_dir.glob(pattern)):
                if path.stem.startswith("game_cards_"):
                    dates.add(path.stem.replace("game_cards_", "", 1))
                elif path.stem.startswith("recommendations_slate_"):
                    dates.add(path.stem.replace("recommendations_slate_", "", 1))
    return tuple(sorted(dates))


def format_num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    return f"{number:.1f}".rstrip("0").rstrip(".")


def format_pct(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    return f"{number * 100:.1f}%"


def format_signed_num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    prefix = "+" if number > 0 else ""
    return f"{prefix}{format_num(number)}"


def format_moneyline(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    rounded = int(round(number))
    return f"+{rounded}" if rounded > 0 else str(rounded)


def market_label(value: Any) -> str:
    code = str(value or "").strip().lower()
    labels = {
        "pts": "PTS",
        "reb": "REB",
        "ast": "AST",
        "pra": "PRA",
        "pa": "PTS+AST",
        "pr": "PTS+REB",
        "ra": "REB+AST",
        "threes": "3PM",
        "blk": "BLK",
        "stl": "STL",
        "bs": "BLK+STL",
    }
    return labels.get(code, code.upper() or "PROP")


def build_module_links(selected_date: str, active_label: str, *, season: int | None = None) -> list[dict[str, Any]]:
    resolved_season = int(season) if season is not None else parse_iso_date(selected_date).year
    links = [
        ("Cards", f"/wnba/cards?date={selected_date}"),
        ("Betting Card", f"/wnba/season/{resolved_season}/betting-card?date={selected_date}"),
        ("Picks", f"/wnba/picks?date={selected_date}"),
        ("Props", f"/wnba/props?date={selected_date}"),
        ("Live Lens", f"/wnba/live-lens?date={selected_date}"),
        ("Daily Archive", f"/wnba/archive?date={selected_date}"),
        ("Hub", "/wnba/hub"),
    ]
    return [{"label": label, "href": href, "active": label == active_label} for label, href in links]
