"""Compact per-game scoreboard chips for the betting-board mini game cards.

Layer 1 (per-sport market board) and Layer 2 (curated betting board) both
render a strip of mini game cards, but until now those cards only showed
matchup text and an opportunity count. This module hydrates them with real
game state -- team abbreviations, live scores, an inning/quarter/clock (or
scheduled-start) status token, and which side currently leads -- sourced
from the same per-sport provider game payloads the home page rails already
read. Serving happens through one shared endpoint so both layers poll a
single, artifact-backed source instead of each re-deriving game state.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from syndicate.features.shared.timezone import CENTRAL_TIMEZONE, central_today_iso

_BASKETBALL_SPORTS = {"nba", "wnba", "ncaab"}
_FOOTBALL_SPORTS = {"nfl", "ncaaf"}

_CACHE_TTL_SECONDS = 30.0
_cache_lock = threading.Lock()
_cache: dict[tuple[str, tuple[str, ...]], tuple[float, list[dict[str, Any]]]] = {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _score_value(value: Any) -> str | None:
    text = _text(value)
    if not text or text in {"-", "None"}:
        return None
    try:
        number = float(text)
    except Exception:
        return None
    if number.is_integer():
        return str(int(number))
    return text


def _side_label(game: dict[str, Any], side: str) -> str:
    container = game.get(side) if isinstance(game.get(side), dict) else {}
    fallback = "Away" if side == "away" else "Home"
    return (
        _text(container.get("abbr"))
        or _text(game.get(f"{side}_tri"))
        or _text(game.get(f"{side}_abbr"))
        or _text(game.get(f"{side}_label"))
        or _text(container.get("name"))
        or _text(game.get(f"{side}_name"))
        or _text(game.get(side) if isinstance(game.get(side), str) else "")
        or fallback
    )


def _side_name(game: dict[str, Any], side: str) -> str:
    """The FULL club name, where the provider's game carries one.

    The chip's `abbr` is a display label and is not always a usable join key:
    soccer tri-codes collide across leagues (`STL` is both Standard Liege and
    St. Louis CITY SC), so `team_aliases` correctly refuses to resolve them and
    a board row joined on abbr alone cannot be matched. Every sport's card
    builder already has the full name in the same dict -- carrying it on the
    chip costs nothing and gives the join an unambiguous key. Empty when the
    provider has only a label, in which case the join falls back to `abbr`
    exactly as before.
    """
    container = game.get(side) if isinstance(game.get(side), dict) else {}
    return _text(container.get("name")) or _text(game.get(f"{side}_name"))


def _side_score(game: dict[str, Any], side: str) -> str | None:
    container = game.get(side) if isinstance(game.get(side), dict) else {}
    status = game.get("status") if isinstance(game.get("status"), dict) else {}
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    status_score = status.get("score") if isinstance(status.get("score"), dict) else {}
    plain_score = game.get("score") if isinstance(game.get("score"), dict) else {}
    for candidate in (
        container.get("score"),
        status.get(f"{side}_score"),
        status_score.get(side),
        plain_score.get(side),
        game.get(f"{side}_score"),
        live_state.get(f"{side}_pts"),
        live_state.get(f"{side}_score"),
    ):
        value = _score_value(candidate)
        if value is not None:
            return value
    return None


def _game_flags(game: dict[str, Any]) -> tuple[bool, bool]:
    status = game.get("status") if isinstance(game.get("status"), dict) else {}
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    state_text = _text(game.get("gameState")).upper()
    status_texts = " ".join(
        _text(value).lower()
        for value in (status.get("abstract"), status.get("detailed"), status.get("status"), live_state.get("status"), game.get("status_badge"))
    )
    is_live = bool(
        game.get("shared_is_live")
        or status.get("is_live")
        or status.get("in_progress")
        or live_state.get("in_progress")
        or state_text in {"LIVE", "CRIT"}
        or "in progress" in status_texts
        or status_texts.startswith("live")
        or " live" in status_texts
    )
    is_final = bool(
        status.get("is_final")
        or status.get("final")
        or live_state.get("final")
        or state_text in {"OFF", "FINAL"}
        or "final" in status_texts
    )
    if is_final:
        is_live = False
    return is_live, is_final


_INNING_TEXT_RE = re.compile(r"\b(top|bottom|bot|middle|mid|end)\b[^0-9]{0,12}(\d{1,2})", re.IGNORECASE)
_PERIOD_CLOCK_RE = re.compile(r"\b(?:Q|P)(\d)\b[\s|·-]*(\d{1,2}:\d{2})?", re.IGNORECASE)
_ORDINAL_INNING_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b")

_HALF_TOKENS = {"top": "TOP", "bottom": "BOT", "bot": "BOT", "middle": "MID", "mid": "MID", "end": "END"}


def _live_status_token(sport: str, game: dict[str, Any]) -> str | None:
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    status = game.get("status") if isinstance(game.get("status"), dict) else {}

    if sport == "mlb":
        half = _text(live_state.get("half") or live_state.get("inning_state") or live_state.get("inning_half")).lower()
        inning = _text(live_state.get("inning") or live_state.get("current_inning"))
        if half in _HALF_TOKENS and inning.isdigit():
            return f"{_HALF_TOKENS[half]} {inning}"
        for source in (live_state.get("status"), status.get("detailed"), game.get("detail"), game.get("summary")):
            text = _text(source)
            if not text:
                continue
            match = _INNING_TEXT_RE.search(text)
            if match:
                return f"{_HALF_TOKENS[match.group(1).lower()]} {match.group(2)}"
            ordinal = _ORDINAL_INNING_RE.search(text)
            if ordinal and ("inning" in text.lower() or "top" in text.lower() or "bot" in text.lower()):
                return f"INN {ordinal.group(1)}"
        return None

    prefix = "Q" if sport in _BASKETBALL_SPORTS or sport in _FOOTBALL_SPORTS else "P"
    period = _text(live_state.get("period") or game.get("period") or live_state.get("quarter"))
    clock = _text(live_state.get("clock") or game.get("clock") or live_state.get("game_clock"))
    if period.isdigit():
        return f"{prefix}{period} {clock}".strip()
    for source in (live_state.get("status"), status.get("detailed"), game.get("detail")):
        text = _text(source)
        if not text:
            continue
        match = _PERIOD_CLOCK_RE.search(text)
        if match:
            token = f"{prefix}{match.group(1)}"
            if match.group(2):
                token = f"{token} {match.group(2)}"
            return token
    return None


_CLOCK_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*([AP])\.?M?\.?$", re.IGNORECASE)


def _scheduled_status_token(game: dict[str, Any]) -> str | None:
    candidates = [
        game.get("scheduled_start_utc"),
        game.get("start_time_utc"),
        # WNBA's own game-list builder (wnba/cards.py) stamps the real ISO
        # commence timestamp onto "startTime" (camelCase) -- confirmed via
        # its own test suite (test_source_cards_payload_uses_live_supplement
        # _for_today asserts first_game["startTime"] == an ISO string).
        # Missing this key meant every WNBA chip's status_token/start_time_utc
        # came back None, which then also broke Games-strip start-time
        # sorting for WNBA specifically (#160 follow-up).
        game.get("startTime"),
        game.get("gameDate"),
        game.get("game_date"),
        game.get("scheduled"),
        game.get("scheduled_start"),
        game.get("commence_time"),
        (game.get("odds") or {}).get("commence_time") if isinstance(game.get("odds"), dict) else None,
    ]
    for value in candidates:
        text = _text(value)
        if not text or "T" not in text:
            continue
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except Exception:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        local_dt = parsed.astimezone(CENTRAL_TIMEZONE)
        hour_minute = local_dt.strftime("%I:%M").lstrip("0")
        meridiem = "P" if local_dt.strftime("%p") == "PM" else "A"
        time_token = f"{hour_minute}{meridiem} CT"
        # Mirrors home.py's _scheduled_status_line: a chip strip can span
        # several days at once (soccer's week-keyed schedule is the clearest
        # case, but a "today" filter that slips can mix days for any sport),
        # so a time-only token is ambiguous about which day it's for. Only
        # tag the date on when it isn't today, to keep the common case terse.
        if local_dt.date().isoformat() != central_today_iso():
            return f"{local_dt.strftime('%a')} {local_dt.strftime('%b')} {local_dt.strftime('%d').lstrip('0')} · {time_token}"
        return time_token
    # Some cards payloads (e.g. MLB's) carry only a pre-formatted local
    # display time like "3:10 PM" with no ISO timestamp, so the loop above
    # never runs and this game's date silently disappears -- a "Tomorrow"
    # tab game read identically to a same-day one. The calendar date is
    # usually still available as a plain "YYYY-MM-DD" string (game_date/
    # gameDate) even without a full ISO timestamp; resolve the day-prefix
    # from that instead of skipping it.
    game_date = _text(game.get("game_date") or game.get("gameDate"))
    day_prefix = None
    if game_date:
        try:
            parsed_date = datetime.strptime(game_date[:10], "%Y-%m-%d").date()
        except Exception:
            parsed_date = None
        if parsed_date is not None and parsed_date.isoformat() != central_today_iso():
            day_prefix = f"{parsed_date.strftime('%a')} {parsed_date.strftime('%b')} {parsed_date.strftime('%d').lstrip('0')}"
    for value in (game.get("startTime"), game.get("start_time"), game.get("start_time_local")):
        text = _text(value)
        match = _CLOCK_TIME_RE.match(text)
        if match:
            time_token = f"{int(match.group(1))}:{match.group(2)}{match.group(3).upper()} CT"
            return f"{day_prefix} · {time_token}" if day_prefix else time_token
    return None


_START_TIME_ISO_FIELDS = (
    "scheduled_start_utc",
    "start_time_utc",
    # WNBA's own game-list builder stamps the real ISO commence timestamp
    # onto "startTime" (camelCase) -- without this key, every WNBA chip's
    # start_time_utc came back None, so it sorted last on the Games strip
    # and showed no date/time at all, making a real game indistinguishable
    # from a phantom one (#160 follow-up).
    "startTime",
    "gameDate",
    "game_date",
    "scheduled",
    "scheduled_start",
    "commence_time",
)


def _resolve_scheduled_start_utc(game: dict[str, Any]) -> datetime | None:
    # A game's ORIGINAL scheduled start, independent of its current
    # live/final/pregame state -- used to order the Games mini-card strip
    # by kickoff time (requested: live games front of the rail sorted by
    # when they started, pregame games in start-time order) rather than by
    # opportunity count, which had no relationship to chronology at all.
    for key in _START_TIME_ISO_FIELDS:
        text = _text(game.get(key))
        if not text or "T" not in text:
            continue
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except Exception:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    nested_commence = (game.get("odds") or {}).get("commence_time") if isinstance(game.get("odds"), dict) else None
    nested_text = _text(nested_commence)
    if nested_text and "T" in nested_text:
        try:
            parsed = datetime.fromisoformat(nested_text.replace("Z", "+00:00"))
        except Exception:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    # No ISO timestamp -- same plain-date-plus-formatted-clock fallback as
    # _scheduled_status_token's own fallback (MLB's cards payload shape).
    date_text = _text(game.get("game_date") or game.get("gameDate"))
    if not date_text:
        return None
    try:
        date_value = datetime.strptime(date_text[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    clock_text = _text(game.get("startTime") or game.get("start_time") or game.get("start_time_local"))
    match = _CLOCK_TIME_RE.match(clock_text)
    hour, minute = 12, 0
    if match:
        hour = int(match.group(1)) % 12
        minute = int(match.group(2))
        if match.group(3).upper() == "P":
            hour += 12
    local_dt = datetime(date_value.year, date_value.month, date_value.day, hour, minute, tzinfo=CENTRAL_TIMEZONE)
    return local_dt.astimezone(timezone.utc)


def _game_key(game: dict[str, Any]) -> str:
    for key in ("gamePk", "game_id", "event_id", "game_pk", "id"):
        value = _text(game.get(key))
        if value:
            return value
    return ""


def _matchup_text(game: dict[str, Any]) -> str:
    matchup = game.get("matchup")
    if isinstance(matchup, str) and matchup.strip():
        return matchup.strip()
    away = _side_label(game, "away")
    home = _side_label(game, "home")
    return f"{away} @ {home}"


def build_game_chip(sport: str, game: dict[str, Any]) -> dict[str, Any]:
    sport_slug = _text(sport).lower()
    is_live, is_final = _game_flags(game)
    away_score = _side_score(game, "away")
    home_score = _side_score(game, "home")
    # A 0-0 score on a game that is neither live nor final is a schedule
    # placeholder, not a real score.
    if not is_live and not is_final and away_score == "0" and home_score == "0":
        away_score = None
        home_score = None

    if is_final:
        state = "final"
        status_token = "FINAL"
    elif is_live:
        state = "live"
        status_token = _live_status_token(sport_slug, game) or "LIVE"
    else:
        state = "pregame"
        status_token = _scheduled_status_token(game)

    leader: str | None = None
    if state in {"live", "final"} and away_score is not None and home_score is not None:
        try:
            away_n, home_n = float(away_score), float(home_score)
            if away_n > home_n:
                leader = "away"
            elif home_n > away_n:
                leader = "home"
        except Exception:
            leader = None

    start_time_utc = _resolve_scheduled_start_utc(game)
    return {
        "sport": sport_slug,
        # #162: only ever set by soccer's own game builders
        # (soccer/cards.py) -- "MLS"/"La Liga" etc., so a consumer can show
        # the specific league instead of the generic sport label. None for
        # every other sport.
        "league": _text(game.get("league")) or None,
        "league_display": _text(game.get("league_display")) or None,
        "game_key": _game_key(game),
        "matchup": _matchup_text(game),
        "away": {"abbr": _side_label(game, "away"), "name": _side_name(game, "away"), "score": away_score},
        "home": {"abbr": _side_label(game, "home"), "name": _side_name(game, "home"), "score": home_score},
        "state": state,
        "status_token": status_token,
        "leader": leader,
        "start_time_utc": start_time_utc.isoformat() if start_time_utc else None,
    }


def _ensure_sport_data_providers() -> None:
    """Populate the provider registry if nothing has populated it yet.

    DEFENSIVE ONLY. This fixes no known live defect, and an earlier version of
    this docstring claimed it did -- that claim was WRONG and the correction is
    the useful part of this comment.

    The registry is a side effect of importing a Flask blueprint: every
    provider is defined in `syndicate/blueprints/home.py` and registers itself
    at module scope (home.py:5882). Nothing on the worker imports that module
    *deliberately* -- but `scripts/run_refresh_worker.py` imports
    `pipeline.intelligence_state`, which reaches `blueprints.home`
    transitively, so in practice all 8 providers ARE registered there.
    Verified 2026-08-08 by replaying the worker entrypoint's exact import list:
    registry size 8, and `attach_game_state` matched 300/300 soccer rows.

    The false alarm came from testing `import pipeline.layer2_shortlist`
    ALONE, which is not how the worker starts. That graph does show registry 0
    -- an artificial condition no process actually runs in.

    What remains true, and why this stays: the dependency is an accident of
    import order in an unrelated module. Anyone pruning
    `intelligence_state`'s imports, or calling `build_game_chips` from a
    genuinely narrower entrypoint, silently gets 0 chips for every sport -- and
    zero chips is indistinguishable from a slate with no games. This makes the
    requirement explicit and costs nothing when it is already satisfied.

    Lazy and inside the function on purpose: at module scope it would be a
    circular import, since home.py imports this module's callers.
    """
    from syndicate.features.shared.sport_data_provider import SPORT_DATA_PROVIDERS

    if SPORT_DATA_PROVIDERS:
        return
    try:
        import syndicate.blueprints.home  # noqa: F401  -- registers providers on import
    except Exception as exc:
        print(f"[game_chips] SPORT_PROVIDER_REGISTRATION_FAILED error={exc}", flush=True)


def build_game_chips(selected_date: str, sports: list[str]) -> list[dict[str, Any]]:
    from syndicate.features.shared.sport_data_provider import get_sport_data_provider

    _ensure_sport_data_providers()
    date_value = _text(selected_date) or central_today_iso()
    normalized_sports = tuple(sorted({_text(slug).lower() for slug in sports if _text(slug)}))
    cache_key = (date_value, normalized_sports)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
            return list(cached[1])

    today_value = central_today_iso()
    chips: list[dict[str, Any]] = []
    for slug in normalized_sports:
        provider = get_sport_data_provider(slug)
        if provider is None:
            continue
        try:
            context = provider.resolve_context(requested_date=date_value)
            is_active_today = provider.is_active(today_value=today_value, context_label=context.context_label)
            games = provider.games(context, is_active_today=is_active_today)
        except Exception:
            continue
        for game in games or []:
            if isinstance(game, dict):
                chips.append(build_game_chip(slug, game))

    with _cache_lock:
        _cache[cache_key] = (now, chips)
        if len(_cache) > 32:
            oldest_key = min(_cache, key=lambda key: _cache[key][0])
            _cache.pop(oldest_key, None)
    return list(chips)
