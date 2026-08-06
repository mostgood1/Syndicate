from __future__ import annotations

import ast
import csv
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as _futures_wait
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging
import os
import socket
from pathlib import Path
import re
import subprocess
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import json

from flask import Blueprint, current_app, has_app_context, jsonify, render_template, request

from syndicate.features.mlb.game_state import mlb_status_is_final as _mlb_status_is_final
from syndicate.features.mlb.game_state import mlb_status_is_live as _mlb_status_is_live
from syndicate.features.mlb.ladders_common import build_module_links as build_mlb_module_links
from syndicate.features.mlb.sources import available_daily_summary_dates
from syndicate.features.mlb.sources import daily_top_props_path
from syndicate.features.mlb.sources import load_json_or_gz_file
from syndicate.features.mlb.sources import raw_feed_live_path
from syndicate.features.nba.sources import available_dates as nba_available_dates
from syndicate.features.nba.sources import build_module_links as build_nba_module_links
from syndicate.features.nhl.sources import build_module_links as build_nhl_module_links
from syndicate.features.nhl.sources import scoreboard_snapshot_path
from syndicate.features.nhl.sources import slate_summaries as nhl_slate_summaries
from syndicate.features.wnba.sources import available_dates as wnba_available_dates
from syndicate.features.wnba.sources import build_module_links as build_wnba_module_links
from syndicate.features.wnba.cards import get_wnba_overview
from syndicate.features.nfl.sources import build_module_links as build_nfl_module_links
from syndicate.features.nfl.sources import build_preseason_module_links
from syndicate.features.nfl.sources import default_week as nfl_default_week
from syndicate.features.nfl.sources import latest_season as nfl_latest_season
from syndicate.features.nfl.sources import preseason_target_week
from syndicate.features.nfl.sources import tracked_week as nfl_tracked_week
from syndicate.features.nfl.sources import week_summaries as nfl_week_summaries
from syndicate.features.ncaaf.sources import build_module_links as build_ncaaf_module_links
from syndicate.features.ncaaf.sources import default_season as ncaaf_default_season
from syndicate.features.ncaaf.sources import default_week as ncaaf_default_week
from syndicate.features.ncaaf.sources import week_summaries as ncaaf_week_summaries
from syndicate.features.ncaab.sources import available_dates as ncaab_available_dates
from syndicate.features.ncaab.sources import build_module_links as build_ncaab_module_links
from syndicate.features.ncaab.sources import latest_date as ncaab_latest_date
from syndicate.features.ncaab.sources import season_for_date as ncaab_season_for_date
from syndicate.features.wnba.sources import has_games_for_date as wnba_has_games_for_date
from syndicate.features.shared.timezone import central_datetime_from_epoch
from syndicate.features.shared.timezone import CENTRAL_TIMEZONE
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.shared.timezone import central_year
from syndicate.features.shared.sport_data_provider import SportContext
from syndicate.features.shared.sport_data_provider import artifact_signature
from syndicate.features.shared.sport_data_provider import get_sport_data_provider
from syndicate.features.shared.sport_data_provider import register_sport_data_provider
from syndicate.features.shared.sport_data_provider import sport_manifest_signature


home_bp = Blueprint("syndicate_home", __name__)
_LOGGER = logging.getLogger(__name__)

_HOME_OVERVIEW_TTL_SEC = 10.0

# These two were plain dicts that were only ever READ FROM and WRITTEN TO --
# nothing ever removed an entry. The 10s TTL above reads like a bound but is
# not one: it only decides whether a cached entry may be *served*. An expired
# entry was left in place and a fresh one written alongside it, so the dicts
# grew monotonically for the life of the process, keyed by (sport, date) plus
# a ":skip_hydration" variant.
#
# Each retained value is a fully hydrated sport overview -- the same payload
# _build_sport_overview's docstring describes as "large enough to exceed the
# container's 2GB memory limit within one call". That is the shape seen in
# production on 2026-07-25: a worker that idled ~700MB early and spiked past
# 1479MB later in the day, degrading as it ran rather than failing outright.
#
# OrderedDict + explicit pruning so the TTL now actually reclaims, and a hard
# ceiling caps the worst case. Sized generously: 7 sports x 2 hydration
# variants is 14 live keys, so 32 leaves room for a date rollover in flight
# without ever being unbounded.
_HOME_CACHE_MAX_ENTRIES = 32
_HOME_OVERVIEW_CACHE: "OrderedDict[str, tuple[float, dict[str, Any]]]" = OrderedDict()
_HOME_PAYLOAD_CACHE: "OrderedDict[str, tuple[float, dict[str, Any]]]" = OrderedDict()

# Deliberately NOT bounded: keyed by sport slug and only ever populated for
# nba/wnba, so it tops out at two entries and is intentionally permanent (no
# TTL) -- it is an ID lookup index, not hydrated game state.
_BASKETBALL_PLAYER_ID_CACHE: dict[str, dict[tuple[str, str], int]] = {}


def _prune_home_cache(
    cache: "OrderedDict[str, tuple[float, dict[str, Any]]]",
    *,
    now: float,
    ttl: float = _HOME_OVERVIEW_TTL_SEC,
    max_entries: int = _HOME_CACHE_MAX_ENTRIES,
) -> None:
    """Drop expired entries, then oldest-first down to the ceiling.

    Called on write rather than on read: a key that stops being requested
    (yesterday's date, a sport that went out of season) would never be read
    again, so a read-time-only sweep could never reclaim exactly the entries
    that leak.
    """
    for key in [key for key, (stamp, _) in cache.items() if (now - stamp) >= ttl]:
        cache.pop(key, None)
    while len(cache) > max_entries:
        cache.popitem(last=False)


def _home_selected_date(selected_date: str | None = None) -> str:
    value = str(selected_date or "").strip()
    return value or central_today_iso()


def _render_web_dyno() -> bool:
    return bool(
        str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}
        or str(os.environ.get("RENDER_EXTERNAL_URL") or "").strip()
        or str(os.environ.get("RENDER_SERVICE_ID") or "").strip()
    )


def _allow_stored_date_fallback() -> bool:
    return False


def _public_version_payload() -> dict[str, str] | None:
    commit = str(
        os.environ.get("RENDER_GIT_COMMIT")
        or os.environ.get("GIT_COMMIT")
        or os.environ.get("SOURCE_VERSION")
        or ""
    ).strip()
    branch = str(
        os.environ.get("RENDER_GIT_BRANCH")
        or os.environ.get("GIT_BRANCH")
        or ""
    ).strip()
    if not commit and not branch:
        return None
    payload: dict[str, str] = {}
    if commit:
        payload["commit"] = commit
    if branch:
        payload["branch"] = branch
    return payload


def _git_value(repo_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    value = (completed.stdout or "").strip()
    return value or None


def _public_detailed_version_payload() -> dict[str, Any]:
    repo_root = Path(current_app.root_path).resolve().parent
    env_commit = str(
        os.environ.get("RENDER_GIT_COMMIT")
        or os.environ.get("GIT_COMMIT")
        or os.environ.get("SOURCE_VERSION")
        or ""
    ).strip() or None
    env_branch = str(
        os.environ.get("RENDER_GIT_BRANCH")
        or os.environ.get("GIT_BRANCH")
        or ""
    ).strip() or None
    git_commit = _git_value(repo_root, "rev-parse", "HEAD")
    git_branch = _git_value(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    hostname = socket.gethostname()
    pid = os.getpid()
    served_at = time.time()
    commit = env_commit or git_commit
    branch = env_branch or git_branch
    branch_matches_checkout = None
    if env_branch and git_branch and git_branch not in {"HEAD", "DETACHED"}:
        branch_matches_checkout = env_branch == git_branch
    return {
        "service": "syndicate",
        "commit": commit,
        "branch": branch,
        "env_commit": env_commit,
        "git_commit": git_commit,
        "env_branch": env_branch,
        "git_branch": git_branch,
        "commit_source": "env" if env_commit else "git" if git_commit else "unknown",
        "branch_source": "env" if env_branch else "git" if git_branch else "unknown",
        "commit_matches_checkout": bool(env_commit and git_commit and env_commit == git_commit) if env_commit or git_commit else None,
        "branch_matches_checkout": branch_matches_checkout,
        "render_service_name": str(os.environ.get("RENDER_SERVICE_NAME") or "").strip() or None,
        "render_instance_id": str(os.environ.get("RENDER_INSTANCE_ID") or "").strip() or None,
        "render_external_url": str(os.environ.get("RENDER_EXTERNAL_URL") or "").strip() or None,
        "hostname": hostname,
        "pid": pid,
        "served_at": served_at,
        "syndicate_data_root": str(current_app.config.get("SYNDICATE_DATA_ROOT") or os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() or None,
        "syndicate_reports_root": str(current_app.config.get("SYNDICATE_REPORTS_ROOT") or os.environ.get("SYNDICATE_REPORTS_ROOT") or "").strip() or None,
    }


def _public_health_version_payload() -> dict[str, str] | None:
    version = _public_detailed_version_payload()
    payload: dict[str, str] = {}
    commit = str(version.get("commit") or "").strip()
    branch = str(version.get("branch") or "").strip()
    if commit:
        payload["commit"] = commit
    if branch:
        payload["branch"] = branch
    return payload or None


@home_bp.get("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "syndicate"})


@home_bp.get("/api/health")
def api_health():
    return healthz()


@home_bp.get("/versionz")
def versionz():
    return jsonify({"ok": True, "version": _public_detailed_version_payload()})


def _safe_text(value: Any, fallback: str = "-", *fallbacks: Any) -> str:
    text = str(value or "").strip()
    if text:
        return text
    for candidate in (fallback, *fallbacks):
        candidate_text = str(candidate or "").strip()
        if candidate_text:
            return candidate_text
    return ""


def _sport_matchup(game: dict[str, Any]) -> str:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    away_label = str(away.get("abbr") or game.get("away_tri") or game.get("away_name") or "Away").strip()
    home_label = str(home.get("abbr") or game.get("home_tri") or game.get("home_name") or "Home").strip()
    return f"{away_label} @ {home_label}"


def _game_team_label(game: dict[str, Any], side: str) -> str | None:
    payload = game.get(side) if isinstance(game.get(side), dict) else {}
    value = (
        payload.get("abbr")
        or payload.get("name")
        or game.get(f"{side}_tri")
        or game.get(f"{side}_name")
        or game.get(side)
    )
    text = str(value or "").strip()
    return text or None


def _team_identifiers(game: dict[str, Any], side: str) -> set[str]:
    payload = game.get(side) if isinstance(game.get(side), dict) else {}
    values = (
        _game_team_label(game, side),
        payload.get("abbr"),
        payload.get("name"),
        game.get(f"{side}_tri"),
        game.get(f"{side}_name"),
    )
    return {str(value).strip().lower() for value in values if str(value or "").strip()}


def _team_for_side_hint(game: dict[str, Any], hint: Any) -> str | None:
    """Resolve a side keyword ("home"/"away") or a selection string naming one
    of this game's two teams into that team's display label. Only matched
    against this game's own known team identifiers -- never open-ended text
    parsing of arbitrary strings."""
    text = str(hint or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"home", "h"}:
        return _game_team_label(game, "home")
    if lowered in {"away", "a"}:
        return _game_team_label(game, "away")
    away_label = _game_team_label(game, "away")
    home_label = _game_team_label(game, "home")
    for label, identifiers in ((away_label, _team_identifiers(game, "away")), (home_label, _team_identifiers(game, "home"))):
        if not label:
            continue
        if lowered in identifiers or any(identifier and identifier in lowered for identifier in identifiers):
            return label
    return None


def _score_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except Exception:
        return text
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _numeric_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _extract_numeric_tail(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*$", text)
    if not match:
        match = re.search(r"([+-]?\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _metric_or_tile_value(game: dict[str, Any], labels: list[str]) -> float | None:
    wanted = {label.strip().lower() for label in labels if label.strip()}
    market_tiles = game.get("market_tiles") if isinstance(game.get("market_tiles"), list) else []
    for tile in market_tiles:
        if not isinstance(tile, dict):
            continue
        label = str(tile.get("label") or "").strip().lower()
        if label in wanted:
            value = _numeric_value(tile.get("value"))
            if value is not None:
                return value
            value = _extract_numeric_tail(tile.get("title"))
            if value is not None:
                return value
    metrics = game.get("metrics") if isinstance(game.get("metrics"), list) else []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        label = str(metric.get("label") or "").strip().lower()
        if label in wanted:
            value = _numeric_value(metric.get("value"))
            if value is not None:
                return value
            value = _extract_numeric_tail(metric.get("value"))
            if value is not None:
                return value
    return None


def _is_liveish(status_badge: Any, status_line: Any) -> bool:
    text = f"{status_badge or ''} {status_line or ''}".strip().lower()
    return any(token in text for token in ("live", "in progress", "top ", "bot ", "q1", "q2", "q3", "q4", "ot", "halftime"))


def _game_identifier(game: dict[str, Any]) -> str | None:
    for field in ("game_id", "gamePk", "game_pk", "event_id"):
        text = _safe_text(game.get(field), "")
        if text:
            return text
    return None


def _game_status_text(game: dict[str, Any]) -> str:
    status = game.get("status") if isinstance(game.get("status"), dict) else {}
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    return " ".join(
        _safe_text(value, "")
        for value in (
            game.get("status_badge"),
            game.get("status_line"),
            game.get("status_display"),
            game.get("status_context"),
            game.get("game_state"),
            game.get("detail"),
            game.get("summary"),
            status.get("abstract"),
            status.get("detailed"),
            status.get("status"),
            live_state.get("status"),
        )
    ).strip().lower()


def _game_status_state(game: dict[str, Any]) -> str:
    status_text = _game_status_text(game)
    if not status_text:
        return ""
    status = game.get("status") if isinstance(game.get("status"), dict) else {}
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    # The board contract's own structured state. Soccer carries `status` as a
    # display STRING ("Sat, Jul 25 - 7:30 PM CT"), so the `status` dict above is
    # empty for it and live_state is absent entirely -- leaving the loose
    # `shared_is_live` boolean as the only signal, which is how yesterday's
    # finished MLS fixtures reached the Layer 2 board flagged live on
    # 2026-07-26. Their shared_game_state said {"live": false, "clock": "",
    # "period": null} in the same payload, so the payload contradicted itself
    # and the wrong half won.
    shared_state = game.get("shared_game_state") if isinstance(game.get("shared_game_state"), dict) else {}
    in_progress = status.get("in_progress")
    if in_progress is None:
        in_progress = live_state.get("in_progress")
    if in_progress is None and isinstance(shared_state.get("live"), bool):
        in_progress = shared_state.get("live")
    if (
        bool(status.get("final"))
        or bool(status.get("is_final"))
        or bool(live_state.get("final"))
        or bool(shared_state.get("final"))
        or _looks_terminal_status_text(status_text)
        or any(token in status_text for token in ("final", "closed", "postponed", "suspended", "canceled", "cancelled"))
    ):
        return "final"
    # `shared_is_live` is a derived convenience flag; an explicit in_progress
    # is evidence. When they disagree, the evidence wins -- same principle as
    # the in_progress=False case documented below, which was already fixed once
    # for WNBA and then reintroduced through this flag for soccer. Note this
    # only changes behaviour where a structured source actually contradicts:
    # with no in_progress anywhere, shared_is_live still decides.
    if bool(in_progress) or (bool(game.get("shared_is_live")) and in_progress is not False):
        return "live"
    # Only fall back to the loose live-token text heuristic when this
    # game's own structured status/live_state says nothing at all about
    # in_progress. Real bug found in production: this used to run
    # unconditionally, so a definitive in_progress=False got silently
    # overridden whenever unrelated text (e.g. game.get("summary") ==
    # "Consensus market snapshot") happened to contain one of these
    # tokens as a substring -- "snapshot" contains "ot" -- forcing hours-
    # from-tip WNBA games to read as live.
    #
    # "ot" also needs a word boundary, not a bare substring check: some
    # game objects (e.g. odds-sourced rows without a real status dict at
    # all) leave in_progress as None permanently, so this fallback is the
    # ONLY signal for them -- and a plain substring match still hits
    # "snapshot"/"not"/"shot"/etc. every time. The other tokens are long
    # enough that this isn't a practical risk.
    if in_progress is None and (
        any(token in status_text for token in ("live", "in progress", "quarter", "period", "inning", "halftime", "intermission"))
        or re.search(r"(?<![a-z])ot(?![a-z])", status_text)
    ):
        return "live"
    if any(token in status_text for token in ("scheduled", "preview", "pregame", "warmup")):
        return "scheduled"
    # #150. A structured source that explicitly says "not in progress" (and
    # we already know from the checks above it isn't final either) is real
    # evidence of "upcoming", even when nothing in status_text spells out
    # one of the scheduled/preview/pregame/warmup tokens. Soccer's card
    # payload is the confirmed case: `status` is a display STRING, not a
    # dict, so `status_badge`/`status_line`/etc (what status_text is built
    # from) are never populated for it, and its narrative `detail`/`summary`
    # text never contains those tokens either -- only `shared_game_state`
    # carries the real signal (`live: False, final: False`). Without this,
    # every soccer game with in_progress explicitly False fell through to
    # "" and get_active_games() (which only keeps "scheduled"/"live")
    # dropped every upcoming fixture, zeroing out dashboard_games/home_rails
    # for the whole sport until kickoff. Confirmed live 2026-07-30: a real
    # upcoming MLS fixture's shared_game_state was exactly
    # {"live": False, "final": False, ...} and _game_status_state returned ""
    # for it.
    if in_progress is False:
        return "scheduled"
    return ""


def get_active_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active_games: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        if _game_status_state(game) in {"scheduled", "live"}:
            active_games.append(game)
    return active_games


def _game_identity_set(items: list[dict[str, Any]] | None) -> set[str]:
    identifiers: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        identifier = _game_identifier(item)
        if identifier:
            identifiers.add(identifier)
    return identifiers


def _active_sport_slugs() -> set[str]:
    try:
        configured = current_app.config.get("SYNDICATE_ACTIVE_SPORTS", ["mlb", "wnba"])
    except RuntimeError:
        configured = os.environ.get("SYNDICATE_ACTIVE_SPORTS", "mlb,wnba")
    if isinstance(configured, str):
        configured = [configured]
    return {str(slug).strip().lower() for slug in configured if str(slug).strip()}


def _live_odds_backed_live_flag(identifier: str, live_odds_game_ids: set[str] | None, fallback_flag: bool) -> bool:
    if not identifier or not isinstance(live_odds_game_ids, set):
        return bool(fallback_flag)
    return bool(fallback_flag) and identifier in live_odds_game_ids


def _central_scheduled_datetime(game: dict[str, Any]) -> datetime | None:
    candidates = [
        game.get("scheduled_start_utc"),
        game.get("start_time_utc"),
        game.get("gameDate"),
        game.get("game_date"),
        game.get("scheduled"),
        game.get("scheduled_start"),
        game.get("commence_time"),
        game.get("detail"),
    ]
    for value in candidates:
        text = str(value or "").strip()
        if not text or "T" not in text:
            continue
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except Exception:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(CENTRAL_TIMEZONE)
    return None


def _scheduled_status_line(game: dict[str, Any], fallback: str) -> str:
    scheduled_dt = _central_scheduled_datetime(game)
    if scheduled_dt is not None:
        time_text = scheduled_dt.strftime("%I:%M %p").lstrip("0")
        if scheduled_dt.date().isoformat() == central_today_iso():
            return f"{time_text} CT"
        return f"{scheduled_dt.strftime('%b')} {scheduled_dt.day} {time_text} CT"
    fallback_text = str(fallback or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", fallback_text):
        if fallback_text == central_today_iso():
            return "Scheduled today"
        return f"Scheduled {fallback_text}"
    if fallback_text.upper() in {"FUT", "PRE"}:
        return "Scheduled"
    return fallback_text or "Board update pending"


def _looks_terminal_status_text(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return any(
        token in lowered
        for token in (
            "final",
            "finished",
            "complete",
            "full time",
            "ft",
            "postponed",
            "cancelled",
            "canceled",
            "suspended",
        )
    )


def _nba_live_state_games(selected_date: str) -> list[dict[str, Any]]:
    try:
        from syndicate.features.nba.cards import build_live_state_payload

        payload = build_live_state_payload(selected_date, ttl=12, allow_stored_date_fallback=False)
    except Exception:
        return []
    rows = payload.get("games") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    games: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        away_label = _safe_text(row.get("away"), "Away")
        home_label = _safe_text(row.get("home"), "Home")
        event_id = row.get("event_id")
        games.append(
            {
                "gamePk": str(row.get("game_id") or "").strip() or f"{away_label}@{home_label}",
                "away": {"abbr": away_label, "name": away_label, "score": row.get("away_pts")},
                "home": {"abbr": home_label, "name": home_label, "score": row.get("home_pts")},
                "status": {
                    "abstract": str(row.get("status") or "").strip() or "Scheduled",
                    "detailed": str(row.get("status") or "").strip() or "Scheduled",
                    "in_progress": bool(row.get("in_progress")),
                    "final": bool(row.get("final")),
                },
                "live_state": dict(row),
                "detail": str(row.get("status") or "").strip() or selected_date,
                "summary": "NBA live-state fallback",
                "href": f"/nba/cards?date={selected_date}",
                "event_id": event_id,
            }
        )
    return games


def _nba_has_live_games(selected_date: str) -> bool:
    return len(_nba_live_state_games(selected_date)) > 0


def _wnba_live_state_games(selected_date: str) -> list[dict[str, Any]]:
    try:
        from syndicate.features.wnba.cards import build_live_state_payload

        payload = build_live_state_payload(selected_date, ttl=12, allow_stored_date_fallback=False)
    except Exception:
        return []
    rows = payload.get("games") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    games: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        away_label = _safe_text(row.get("away"), "Away")
        home_label = _safe_text(row.get("home"), "Home")
        event_id = row.get("event_id")
        game_id = str(row.get("game_id") or event_id or f"{away_label}@{home_label}").strip() or f"{away_label}@{home_label}"
        games.append(
            {
                "game_id": game_id,
                "gamePk": game_id,
                "event_id": event_id,
                "away": {"abbr": away_label, "name": away_label, "score": row.get("away_pts")},
                "home": {"abbr": home_label, "name": home_label, "score": row.get("home_pts")},
                "status": {
                    "abstract": str(row.get("status") or "").strip() or "Scheduled",
                    "detailed": str(row.get("status") or "").strip() or "Scheduled",
                    "in_progress": bool(row.get("in_progress")),
                    "final": bool(row.get("final")),
                },
                "live_state": dict(row),
                "detail": str(row.get("status") or "").strip() or selected_date,
                "summary": "WNBA live-state fallback",
                "href": f"/wnba/cards?date={selected_date}",
            }
        )
    return games


def _wnba_has_live_games(selected_date: str) -> bool:
    # Must check in_progress specifically, not just "a live-state row exists"
    # -- a stale/leftover snapshot for a long-since-final game on some other
    # date would otherwise read as "live" forever, which is exactly the kind
    # of stale-signal false positive this function exists to rule out.
    return any(bool((game.get("status") or {}).get("in_progress")) for game in _wnba_live_state_games(selected_date))


def _mlb_schedule_fallback_games(selected_date: str) -> list[dict[str, Any]]:
    try:
        with urlopen(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={selected_date}", timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    dates = payload.get("dates") if isinstance(payload, dict) else []
    if not isinstance(dates, list) or not dates:
        return []
    events = dates[0].get("games") if isinstance(dates[0], dict) else []
    if not isinstance(events, list):
        return []
    games: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        teams = event.get("teams") if isinstance(event.get("teams"), dict) else {}
        away = teams.get("away") if isinstance(teams.get("away"), dict) else {}
        home = teams.get("home") if isinstance(teams.get("home"), dict) else {}
        away_team = away.get("team") if isinstance(away.get("team"), dict) else {}
        home_team = home.get("team") if isinstance(home.get("team"), dict) else {}
        away_abbr = _safe_text(away_team.get("abbreviation") or away_team.get("name"), "Away")
        home_abbr = _safe_text(home_team.get("abbreviation") or home_team.get("name"), "Home")
        game_pk = int(event.get("gamePk") or 0)
        status = event.get("status") if isinstance(event.get("status"), dict) else {}
        games.append(
            {
                "gamePk": game_pk,
                "away": {
                    "abbr": away_abbr,
                    "name": _safe_text(away_team.get("name"), away_abbr),
                    "score": away.get("score"),
                },
                "home": {
                    "abbr": home_abbr,
                    "name": _safe_text(home_team.get("name"), home_abbr),
                    "score": home.get("score"),
                },
                "status": {
                    "abstract": _safe_text(status.get("abstractGameState"), "Scheduled"),
                    "detailed": _safe_text(status.get("detailedState"), "Scheduled"),
                },
                "scheduled_start_utc": event.get("gameDate"),
                "detail": _safe_text(status.get("detailedState"), selected_date),
                "summary": "MLB schedule fallback",
                "href": f"/mlb/game/{game_pk}?date={selected_date}" if game_pk else f"/mlb/cards?date={selected_date}",
                "href_label": "Open MLB game",
            }
        )
    return games


def _scoreboard_state(game: dict[str, Any]) -> dict[str, Any]:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    status = game.get("status") if isinstance(game.get("status"), dict) else {}
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    score = status.get("score") if isinstance(status.get("score"), dict) else {}

    away_label = str(away.get("abbr") or game.get("away_tri") or game.get("away_name") or "Away").strip() or "Away"
    home_label = str(home.get("abbr") or game.get("home_tri") or game.get("home_name") or "Home").strip() or "Home"

    away_score = (
        _score_value(away.get("score"))
        or _score_value(status.get("away_score"))
        or _score_value(score.get("away"))
        or _score_value(live_state.get("away_pts"))
    )
    home_score = (
        _score_value(home.get("score"))
        or _score_value(status.get("home_score"))
        or _score_value(score.get("home"))
        or _score_value(live_state.get("home_pts"))
    )

    is_live = bool(game.get("shared_is_live") or status.get("is_live") or status.get("in_progress") or live_state.get("in_progress"))
    is_final = bool(status.get("is_final") or status.get("final") or live_state.get("final"))
    suppress_zero_zero = not is_live and not is_final and away_score == "0" and home_score == "0"
    has_scores = bool(away_score and home_score and not suppress_zero_zero)

    raw_status_badge = str(
        status.get("abstract")
        or status.get("status")
        or game.get("status_badge")
        or ("Live" if is_live else "Final" if is_final else "Scheduled")
    ).strip()
    raw_status_line = str(
        status.get("detailed")
        or live_state.get("status")
        or game.get("detail")
        or game.get("summary")
        or "Board update pending"
    ).strip()

    # If the game start is well in the past but source status is still a placeholder,
    # force terminal handling so home cards do not remain stuck on "Scheduled".
    scheduled_dt = _central_scheduled_datetime(game)
    if not is_live and not is_final and scheduled_dt is not None and not _looks_terminal_status_text(raw_status_line):
        now_central = datetime.now(CENTRAL_TIMEZONE)
        if scheduled_dt <= now_central - timedelta(hours=3):
            is_final = True

    status_badge = raw_status_badge
    status_line = raw_status_line
    if not is_live and not is_final:
        if raw_status_badge.lower() in {"processed artifact", "tracked", "stored slate lens"}:
            status_badge = "Scheduled"
        status_line = _scheduled_status_line(game, raw_status_line)
    elif is_final and not _looks_terminal_status_text(raw_status_line):
        status_badge = "Final"
        status_line = "Final update pending"
    return {
        "away_label": away_label,
        "home_label": home_label,
        "away_score": away_score if has_scores else None,
        "home_score": home_score if has_scores else None,
        "has_scores": has_scores,
        "score_kind": "Live score" if is_live else "Final score" if is_final else None,
        "status_badge": status_badge or "Scheduled",
        "status_line": status_line or "Board update pending",
    }


def _team_logo(game: dict[str, Any], side: str) -> str | None:
    container = game.get(side) if isinstance(game.get(side), dict) else {}
    matchup = game.get("matchup") if isinstance(game.get("matchup"), dict) else {}
    matchup_side = matchup.get(side) if isinstance(matchup.get(side), dict) else {}
    for value in [
        game.get(f"{side}_logo"),
        container.get("logo"),
        container.get("logo_url"),
        container.get("badge"),
        matchup_side.get("logo"),
        matchup_side.get("logo_url"),
        matchup_side.get("badge"),
    ]:
        text = str(value or "").strip()
        if text:
            return text
    return None

def _pct_text(value: Any) -> str | None:
    number = _numeric_value(value)
    if number is None:
        return None
    if abs(number) <= 1.0:
        number *= 100.0
    return f"{number:.1f}%"


def _game_market_recommendation_strings(game: dict[str, Any], *, limit: int = 3) -> list[str]:
    rows = game.get("game_market_recommendations") if isinstance(game.get("game_market_recommendations"), list) else []
    values: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pick = _safe_text(row.get("display_pick") or row.get("selection") or row.get("market_label"), "Market")
        parts = [pick]
        ev_pct = _pct_text(row.get("ev_pct"))
        p_win = _pct_text(row.get("p_win"))
        if ev_pct:
            parts.append(f"EV {ev_pct}")
        if p_win:
            parts.append(f"Win {p_win}")
        values.append(" | ".join(parts))
        if len(values) >= limit:
            break
    return values


def _betting_signal_strings(game: dict[str, Any], *, limit: int = 3) -> list[str]:
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    values: list[str] = []
    for label, field_names in [
        ("ML", ["ml_pick", "moneyline_pick", "moneyline"]),
        ("Spread", ["spread_pick", "spread"]),
        ("Total", ["total_pick", "total"]),
    ]:
        text = ""
        for field_name in field_names:
            text = str(betting.get(field_name) or "").strip()
            if text:
                break
        if not text:
            continue
        values.append(f"{label}: {text}")
        if len(values) >= limit:
            break
    return values


def _market_chip_strings(game: dict[str, Any], *, limit: int = 3) -> list[str]:
    chips: list[str] = []
    game_recs = game.get("game_market_recommendations") if isinstance(game.get("game_market_recommendations"), list) else []
    prop_recs = game.get("prop_recommendations") if isinstance(game.get("prop_recommendations"), list) else []
    if game_recs:
        chips.append(f"{len(game_recs)} game looks")
    if prop_recs:
        chips.append(f"{len(prop_recs)} prop looks")
    live_status = str(game.get("live_status") or "").strip()
    if live_status:
        chips.append(live_status)
    return chips[:limit]


def _summary_text(game: dict[str, Any]) -> str:
    for value in [game.get("writeup"), game.get("summary")]:
        text = str(value or "").strip()
        if text:
            return text
    return "No market summary available yet."


def _edge_text(value: Any) -> str | None:
    number = _numeric_value(value)
    if number is None:
        return None
    if abs(number) <= 1.0:
        return _pct_text(number)
    text = _score_value(number)
    if text is None:
        return None
    return text if str(text).startswith("-") else f"+{text}"


def _mlb_live_game_signal_strings(game: dict[str, Any], *, limit: int = 3) -> list[str]:
    values: list[str] = []
    lenses = game.get("gameLens") if isinstance(game.get("gameLens"), list) else []
    for lens in lenses:
        if not isinstance(lens, dict) or bool(lens.get("closed")):
            continue
        lens_label = _safe_text(lens.get("label"), "Live")
        markets = lens.get("markets") if isinstance(lens.get("markets"), dict) else {}
        for market_key, market_label in [("moneyline", "ML"), ("spread", "SPR"), ("total", "TOT")]:
            market = markets.get(market_key) if isinstance(markets.get(market_key), dict) else {}
            pick = str(market.get("pick") or "").strip()
            if not pick:
                continue
            edge = _edge_text(market.get("edge"))
            line = _score_value(market.get("line") if market_key == "total" else market.get("homeLine"))
            parts = [f"{lens_label} {market_label}", pick.upper()]
            if line and market_key in {"spread", "total"}:
                parts.append(f"Line {line}")
            if edge:
                parts.append(f"Edge {edge}")
            values.append(" | ".join(parts))
            if len(values) >= limit:
                return values
    return values


def _sort_compact_game_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _is_completed(item: dict[str, Any]) -> bool:
        text = f"{item.get('status_badge') or ''} {item.get('detail') or ''} {item.get('score_kind') or ''}".lower()
        return any(token in text for token in ("final", "game over", "completed", "off"))

    ordered = sorted(enumerate(items), key=lambda pair: (_is_completed(pair[1]), pair[0]))
    return [item for _, item in ordered]


def _prop_metric_text(value: Any) -> str | None:
    text = _score_value(value)
    if text is not None:
        return text
    raw = str(value or "").strip()
    return raw or None


def _metric_value(metrics: list[dict[str, Any]], labels: list[str]) -> str | None:
    wanted = [label.strip().lower() for label in labels if label.strip()]
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        label = str(metric.get("label") or "").strip().lower()
        if not label:
            continue
        if any(label == item or item in label for item in wanted):
            value = _prop_metric_text(metric.get("value"))
            if value:
                return value
    return None


def _split_matchup_labels(value: Any) -> tuple[str | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    parts = re.split(r"\s+(?:@|vs\.?|v|at)\s+", text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return None, None
    away_label = parts[0].strip() or None
    home_label = parts[1].strip() or None
    return away_label, home_label


def _logo_from_team_label(slug: str, team_label: str | None) -> str | None:
    text = str(team_label or "").strip()
    if not text:
        return None
    try:
        if slug == "nba":
            from syndicate.features.nba.cards import _nba_logo_url

            return _nba_logo_url(text.upper())
        if slug == "wnba":
            from syndicate.features.wnba.cards import _source_logo_url

            logo = _source_logo_url(text.upper())
            return str(logo or "").strip() or None
        if slug == "nhl":
            from syndicate.features.nhl.sources import team_logo_url

            return team_logo_url(text.upper())
        if slug == "mlb":
            from syndicate.features.mlb.cards import _MLB_TEAM_META_BY_ABBR
            from syndicate.features.mlb.cards import _mlb_logo_url

            meta = _MLB_TEAM_META_BY_ABBR.get(text.upper()) or {}
            team_id = meta.get("team_id") if meta.get("team_id") is not None else meta.get("id")
            if team_id is None:
                return None
            return _mlb_logo_url(int(team_id))
    except Exception:
        return None
    return None


def _pill_value_text(value: Any) -> str | None:
    text = _prop_metric_text(value)
    if not text:
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?%)", text)
    if match:
        return match.group(1)
    return text


def _is_placeholder_team_label(value: Any) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return text in {"opp", "opponent", "home", "away", "team", "unknown"}


def _normalized_prop_lookup_key(*parts: Any) -> str:
    values = [re.sub(r"\s+", " ", str(part or "").strip().lower()) for part in parts]
    return "|".join(value for value in values if value)


def _home_prop_game_index(home_games: list[dict[str, Any]] | None) -> dict[str, dict[Any, dict[str, Any]]]:
    by_pk: dict[Any, dict[str, Any]] = {}
    by_labels: dict[Any, dict[str, Any]] = {}
    by_team: dict[Any, dict[str, Any]] = {}
    for game in home_games or []:
        if not isinstance(game, dict):
            continue
        game_pk = _int_or_none(game.get("gamePk") or game.get("game_pk") or game.get("game_id"))
        if game_pk is not None:
            by_pk[game_pk] = game
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        away_label = str(away.get("abbr") or away.get("name") or game.get("away_tri") or game.get("away_name") or "").strip()
        home_label = str(home.get("abbr") or home.get("name") or game.get("home_tri") or game.get("home_name") or "").strip()
        if away_label or home_label:
            by_labels[_normalized_prop_lookup_key(away_label, home_label)] = game
        for team_label in (away_label, home_label):
            if not team_label or _is_placeholder_team_label(team_label):
                continue
            by_team.setdefault(_normalized_prop_lookup_key(team_label), game)
        matchup = str(game.get("matchup") or _sport_matchup(game)).strip()
        if matchup:
            parsed_away, parsed_home = _split_matchup_labels(matchup)
            by_labels[_normalized_prop_lookup_key(parsed_away, parsed_home)] = game
            for team_label in (parsed_away, parsed_home):
                if not team_label or _is_placeholder_team_label(team_label):
                    continue
                by_team.setdefault(_normalized_prop_lookup_key(team_label), game)
    return {"by_pk": by_pk, "by_labels": by_labels, "by_team": by_team}


def _home_prop_matched_game(item: dict[str, Any], game_index: dict[str, dict[Any, dict[str, Any]]]) -> dict[str, Any] | None:
    game_pk = _int_or_none(item.get("game_pk") or item.get("gamePk") or item.get("game_id"))
    if game_pk is not None:
        matched = (game_index.get("by_pk") or {}).get(game_pk)
        if isinstance(matched, dict):
            return matched
    away_label = str(item.get("away_label") or item.get("team") or "").strip()
    home_label = str(item.get("home_label") or item.get("opponent") or "").strip()
    if away_label or home_label:
        matched = (game_index.get("by_labels") or {}).get(_normalized_prop_lookup_key(away_label, home_label))
        if isinstance(matched, dict):
            return matched
    matchup = str(item.get("matchup") or "").strip()
    parsed_away, parsed_home = _split_matchup_labels(matchup)
    if parsed_away or parsed_home:
        matched = (game_index.get("by_labels") or {}).get(_normalized_prop_lookup_key(parsed_away, parsed_home))
        if isinstance(matched, dict):
            return matched
    for team_label in [
        item.get("team"),
        item.get("opponent"),
        item.get("away_label"),
        item.get("home_label"),
        parsed_away,
        parsed_home,
    ]:
        if _is_placeholder_team_label(team_label):
            continue
        matched = (game_index.get("by_team") or {}).get(_normalized_prop_lookup_key(team_label))
        if isinstance(matched, dict):
            return matched
    return None


def _display_prop_market_label(value: Any) -> str:
    raw_text = re.sub(r"[_/]+", " ", str(value or "").strip())
    raw_text = re.sub(r"\s+", " ", raw_text).strip()
    lowered = raw_text.lower()
    while True:
        stripped = False
        for prefix in ("batter ", "hitter ", "pitcher ", "player "):
            if lowered.startswith(prefix):
                raw_text = raw_text[len(prefix):].strip()
                lowered = raw_text.lower()
                stripped = True
                break
        if not stripped:
            break
    replacements = {
        "batter hits": "Hits",
        "batter total bases": "Total Bases",
        "batter runs scored": "Runs Scored",
        "batter rbi": "RBI",
        "batter rbis": "RBI",
        "hits": "Hits",
        "total bases": "Total Bases",
        "runs scored": "Runs Scored",
        "rbis": "RBI",
        "rbi": "RBI",
        "outs": "Outs",
        "strikeouts": "Strikeouts",
        "hits allowed": "Hits Allowed",
        "walks allowed": "Walks Allowed",
        "earned runs": "Earned Runs",
        "pts": "PTS",
        "points": "Points",
        "reb": "REB",
        "rebounds": "Rebounds",
        "ast": "AST",
        "assists": "Assists",
        "pra": "PRA",
        "pr": "PTS+REB",
        "pa": "PTS+AST",
        "ra": "REB+AST",
        "threes": "3PM",
        "points rebounds assists": "Points + Rebounds + Assists",
        "points rebounds": "Points + Rebounds",
        "points assists": "Points + Assists",
        "rebounds assists": "Rebounds + Assists",
        "three pointers made": "3PT Made",
        "threes made": "3PT Made",
        "shots on goal": "Shots on Goal",
        "saves": "Saves",
    }
    if lowered in replacements:
        return replacements[lowered]
    tokens: list[str] = []
    for token in raw_text.split():
        upper = token.upper()
        if upper in {"RBI", "PRA", "PTS", "REB", "AST", "3PT", "3PM", "SOG"}:
            tokens.append(upper)
        else:
            tokens.append(token.capitalize())
    return " ".join(tokens) or "Prop"


def _display_prop_title_parts(name: Any, market_label: str) -> tuple[str, str]:
    raw_name = re.sub(r"\s+", " ", str(name or "").strip()) or "Prop"
    player_name = raw_name
    market_suffix = re.search(r"^(?P<player>.+?)\s+(?:Batter|Hitter|Pitcher|Player)[ _].+$", raw_name)
    if market_suffix:
        player_name = market_suffix.group("player").strip() or raw_name
    title = player_name
    if market_label and market_label.lower() not in title.lower():
        title = f"{title} {market_label}".strip()
    return player_name, title


def _home_prop_status_display(item: dict[str, Any], matched_game: dict[str, Any] | None) -> str | None:
    if isinstance(matched_game, dict):
        scoreboard = _scoreboard_state(matched_game)
        liveish = _is_liveish(scoreboard.get("status_badge"), scoreboard.get("status_line"))
        if scoreboard.get("has_scores"):
            score_text = f"{scoreboard.get('away_score')}-{scoreboard.get('home_score')}"
            if liveish:
                return f"{score_text} | {scoreboard.get('status_line')}"
            if str(scoreboard.get("status_badge") or "").strip().lower() == "final":
                return f"{score_text} | Final"
        return _safe_text(scoreboard.get("status_line"), None)
    return _safe_text(item.get("game_state"), None)


def _home_prop_live_total(item: dict[str, Any], matched_game: dict[str, Any] | None) -> str | None:
    liveish = bool(item.get("is_live"))
    finalish = False
    if isinstance(matched_game, dict):
        scoreboard = _scoreboard_state(matched_game)
        liveish = liveish or _is_liveish(scoreboard.get("status_badge"), scoreboard.get("status_line"))
        finalish = str(scoreboard.get("status_badge") or "").strip().lower() == "final"
    if not liveish and not finalish:
        return None
    actual_total = _prop_metric_text(
        item.get("actual")
        if item.get("actual") not in {None, "", "-"}
        else (item.get("actual_value") if item.get("actual_value") not in {None, "", "-"} else item.get("actual_so_far"))
    )
    if actual_total and actual_total != "-":
        return actual_total
    return None


def _home_prop_stat_suffix(market_label: str | None) -> str | None:
    lowered = str(market_label or "").strip().lower()
    if not lowered:
        return None
    mapping = {
        "hits allowed": "H",
        "hits": "H",
        "total bases": "TB",
        "runs scored": "R",
        "rbi": "RBI",
        "outs": "Outs",
        "strikeouts": "K",
        "walks allowed": "BB",
        "earned runs": "ER",
        "home runs": "HR",
        "points rebounds assists": "PRA",
        "points rebounds": "PR",
        "points assists": "PA",
        "rebounds assists": "RA",
        "points": "Pts",
        "rebounds": "Reb",
        "assists": "Ast",
        "three pointers made": "3PM",
        "threes made": "3PM",
        "3pt made": "3PM",
        "shots on goal": "SOG",
        "saves": "Saves",
        "goals": "Goals",
        "blocks": "Blk",
        "steals": "Stl",
    }
    return mapping.get(lowered, market_label)


def _home_prop_metric_line(raw_value: Any, market_label: str | None) -> str | None:
    metric = _prop_metric_text(raw_value)
    if not metric or metric == "-":
        return None
    if re.search(r"[A-Za-z]", metric):
        return metric
    suffix = _home_prop_stat_suffix(market_label)
    return f"{metric} {suffix}".strip() if suffix else metric


def _home_prop_hero_metrics(item: dict[str, Any]) -> tuple[str | None, str | None]:
    market_label = _safe_text(item.get("market_display") or item.get("market"), None)
    live_box = _home_prop_metric_line(item.get("actual"), market_label)
    if not live_box:
        live_box = _home_prop_metric_line(item.get("live_total"), market_label)

    sim_box = _home_prop_metric_line(
        item.get("sim_projection")
        if item.get("sim_projection") not in {None, "", "-"}
        else item.get("sim_mu")
        if item.get("sim_mu") not in {None, "", "-"}
        else item.get("sim_box")
        if item.get("sim_box") not in {None, "", "-"}
        else item.get("projected"),
        market_label,
    )
    if not sim_box:
        sim_box = _home_prop_metric_line(item.get("line") or item.get("market_line"), market_label)
    return live_box, sim_box


def _home_prop_writeup(item: dict[str, Any], *, player_name: str, market_label: str) -> str:
    raw_writeup = str(item.get("writeup") or "").strip()
    if raw_writeup and "_" not in raw_writeup:
        return raw_writeup
    pick = _safe_text(item.get("pick") or item.get("selection"), "Play")
    line = _prop_metric_text(item.get("line") or item.get("market_line"))
    base_sentence = f"{'Live lean' if item.get('is_live') else 'Recommended'} {pick} for {player_name} {market_label}".strip()
    if line and line != "-":
        base_sentence = f"{base_sentence} at {line}."
    else:
        base_sentence = f"{base_sentence}."
    detail = str(item.get("detail") or item.get("summary") or "").strip()
    detail_tail = detail.split("|", 1)[1].strip() if "|" in detail else ""
    if detail_tail:
        return f"{base_sentence} {detail_tail.rstrip('.')} .".replace(" .", ".")
    confidence = _safe_text(item.get("confidence"), None)
    raw_value = _safe_text(item.get("value"), None)
    edge = _safe_text(item.get("edge"), None)
    if not edge and raw_value and "win" not in raw_value.lower():
        edge = raw_value
    if confidence and edge:
        return f"{base_sentence} Model gives {confidence} win probability with {edge} edge."
    if confidence:
        return f"{base_sentence} Model gives {confidence} win probability."
    return base_sentence


def _home_prop_ladder_groups(item: dict[str, Any]) -> list[dict[str, Any]]:
    groups = item.get("ladder_groups") if isinstance(item.get("ladder_groups"), list) else []
    normalized: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        label = str(group.get("short_label") or group.get("label") or group.get("stat") or "").strip()
        targets = [int(total) for total in (group.get("targets") or []) if _int_or_none(total) is not None]
        if not label or not targets:
            continue
        normalized.append({"label": label, "targets": sorted(dict.fromkeys(targets))})
    return normalized


def _home_prop_display_pills(item: dict[str, Any], *, live_total: str | None) -> list[str]:
    live_flag = bool(item.get("is_live")) or _is_liveish(item.get("heading"), item.get("status_display"))
    values: list[str] = []
    market_label = _safe_text(item.get("market_display") or item.get("market"), None)
    stat_suffix = _home_prop_stat_suffix(market_label)
    for label, raw_value in [
        ("Line", item.get("line")),
        ("Odds", item.get("odds")),
        ("Sim%", item.get("confidence") or item.get("value")),
        (f"Pregame {stat_suffix or 'Proj'} Proj", _home_prop_metric_line(item.get("projected"), market_label)),
        (f"Live {stat_suffix or 'Total'} Total", _home_prop_metric_line(live_total, market_label) if live_flag else None),
        (f"Live {stat_suffix or 'Proj'} Proj", _home_prop_metric_line(item.get("live_projection"), market_label) if live_flag else None),
    ]:
        value = _pill_value_text(raw_value)
        if value and value != "-":
            values.append(f"{label} {value}")
    for group in _home_prop_ladder_groups(item):
        target_label = "/".join(str(total) for total in (group.get("targets") or []))
        if target_label:
            values.append(f"Ladder {group.get('label')} {target_label}")
    return values


def _finalize_home_prop_rows(rows: list[dict[str, Any]], *, slug: str, context_label: str | None = None, home_games: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    # #222 step 2: measure the identity gap BEFORE this function coerces it away.
    # Recorded on the way IN, so the numbers describe what producers actually
    # emit rather than what this function managed to patch up.
    try:
        from syndicate.features.shared import opportunity_contract_metrics

        opportunity_contract_metrics.record_rows(rows, sport=slug, lane="prop_source_in", date_str=context_label)
    except Exception:
        pass
    finalized: list[dict[str, Any]] = []
    actual_cache: dict[int, dict[str, Any] | None] = {}
    game_index = _home_prop_game_index(home_games)
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        game_pk = _int_or_none(item.get("game_pk") or item.get("gamePk") or item.get("game_id"))
        matchup = str(item.get("matchup") or "").strip()
        away_label = str(item.get("away_label") or "").strip() or None
        home_label = str(item.get("home_label") or "").strip() or None
        away_label = away_label or _safe_text(item.get("team"), None)
        home_label = home_label or _safe_text(item.get("opponent"), None)
        parsed_away, parsed_home = _split_matchup_labels(matchup)
        away_label = away_label or parsed_away
        home_label = home_label or parsed_home
        matched_game = _home_prop_matched_game(item, game_index)
        if isinstance(matched_game, dict):
            matched_away = matched_game.get("away") if isinstance(matched_game.get("away"), dict) else {}
            matched_home = matched_game.get("home") if isinstance(matched_game.get("home"), dict) else {}
            matched_away_label = str(matched_away.get("abbr") or matched_away.get("name") or matched_game.get("away_tri") or matched_game.get("away_name") or "").strip() or None
            matched_home_label = str(matched_home.get("abbr") or matched_home.get("name") or matched_game.get("home_tri") or matched_game.get("home_name") or "").strip() or None
            if matched_away_label and matched_home_label:
                away_label = matched_away_label
                home_label = matched_home_label
            if game_pk is None:
                matched_game_pk = _int_or_none(matched_game.get("gamePk") or matched_game.get("game_pk") or matched_game.get("game_id"))
                if matched_game_pk is not None:
                    item["gamePk"] = matched_game_pk
                    item["game_pk"] = matched_game_pk
            if not item.get("game_id"):
                matched_game_id = str(matched_game.get("game_id") or matched_game.get("gamePk") or matched_game.get("game_pk") or "").strip()
                if matched_game_id:
                    item["game_id"] = matched_game_id
            if not item.get("event_id") and matched_game.get("event_id") is not None:
                item["event_id"] = matched_game.get("event_id")
            # Confirmed live 2026-08-05: soccer prop candidates (e.g. "Anytime
            # Goalscorer") carried NO date field of their own at all, so
            # resolve_candidate_game_date (intelligence_contracts.py --
            # checks commence_time/start_time_utc/game_time_utc/game_date,
            # in that order) always fell through to its fallback, which is
            # the BOARD's context date, not the fixture's real date. Three
            # real candidates for an Aug 8 MLS match all carried game_date
            # Aug 5 (today) as a result -- silently pointing the odds_history
            # join at the wrong shard, with no exception or empty-state to
            # notice. Soccer's own dashboard game dicts (cards.py's
            # _match_to_game/_unsimulated_game) DO carry the real kickoff,
            # just under a different key ("scheduled_start_utc", read
            # directly by game-chip rendering) that resolve_candidate_game_date
            # doesn't check. This is the same "copy matched_game's real
            # identity onto the prop item" pattern already used above for
            # team labels/gamePk/game_id/event_id, filling the one field
            # that pattern was missing. setdefault, not overwrite: an item
            # that already carries its own accurate date is left alone.
            if not item.get("commence_time") and matched_game.get("scheduled_start_utc"):
                item["commence_time"] = matched_game.get("scheduled_start_utc")
        away_logo = str(item.get("away_logo") or item.get("team_logo_url") or "").strip() or None
        home_logo = str(item.get("home_logo") or item.get("opponent_logo_url") or "").strip() or None
        if isinstance(matched_game, dict):
            away_logo = away_logo or _team_logo(matched_game, "away")
            home_logo = home_logo or _team_logo(matched_game, "home")
        away_logo = away_logo or _logo_from_team_label(slug, away_label)
        home_logo = home_logo or _logo_from_team_label(slug, home_label)
        if not isinstance(item.get("pills"), list):
            pills: list[dict[str, str]] = []
            for label, raw_value in [
                ("Line", item.get("line")),
                ("Sim", item.get("confidence")),
                ("Odds", item.get("odds")),
            ]:
                value = _pill_value_text(raw_value)
                if value:
                    pills.append({"label": label, "value": value})
            item["pills"] = pills
        if not item.get("writeup"):
            item["writeup"] = _safe_text(item.get("detail") or item.get("summary"), "No prop summary available.")
        if not item.get("headshot_url") and slug in {"nba", "wnba"}:
            resolved_player_id = _basketball_resolve_player_id(
                slug,
                player_name=item.get("player_name") or item.get("name"),
                team_tri=item.get("team") or away_label or home_label,
                player_id=item.get("player_id"),
            )
            headshot_url = _basketball_best_headshot_url(player_id=resolved_player_id, photo=item.get("photo"))
            if headshot_url:
                item["headshot_url"] = headshot_url
                item["photo"] = headshot_url
        item["away_label"] = away_label
        item["home_label"] = home_label
        item["away_logo"] = away_logo
        item["home_logo"] = home_logo

        market_label = _display_prop_market_label(item.get("market") or item.get("name"))
        player_name, display_name = _display_prop_title_parts(item.get("name"), market_label)
        team_label = str(item.get("team") or away_label or "").strip()
        if player_name and team_label and player_name.strip().lower() == team_label.lower():
            # Diagnostic only (2026-07-23): catches the upstream row-builder that
            # emits the team abbreviation into "name" instead of a player, which
            # produces mis-attributed prop candidates and blank Projected values.
            _LOGGER.warning(
                "home_prop_row_name_equals_team slug=%s market=%s team=%s game_pk=%s",
                slug,
                market_label,
                team_label,
                game_pk,
            )
        item["name"] = display_name
        item["market_display"] = market_label
        item["player_name"] = player_name
        item["meta_line"] = _safe_text(
            " ".join(part for part in [str(item.get("pick") or "").strip().upper(), _prop_metric_text(item.get("line") or item.get("market_line")) or ""] if part).strip(),
            _safe_text(item.get("detail"), None),
        )
        item["status_display"] = _home_prop_status_display(item, matched_game)
        if isinstance(matched_game, dict):
            scoreboard = _scoreboard_state(matched_game)
            item["is_live"] = bool(item.get("is_live")) or _is_liveish(scoreboard.get("status_badge"), scoreboard.get("status_line"))

        if slug == "mlb" and game_pk is not None and context_label:
            actual_payload = _mlb_actual_payload_for_game(context_label, int(game_pk), actual_cache)
            if not item.get("headshot_url"):
                headshot_url = _mlb_headshot_from_actual_payload(item.get("player_name") or item.get("name"), actual_payload)
                if headshot_url:
                    item["headshot_url"] = headshot_url
                    item["photo"] = headshot_url
            final_state = _mlb_actual_payload_is_final(actual_payload)
            actual_value = _mlb_prop_actual_value(item, actual_payload)
            if actual_value is not None:
                item["actual"] = _score_value(actual_value)
            selection = str(item.get("pick") or item.get("selection") or "").strip().lower()
            line_value = _numeric_value(item.get("line") or item.get("market_line"))
            state = _mlb_prop_result_state(
                actual_value=actual_value,
                line_value=line_value,
                selection=selection,
                final_state=final_state,
                is_hr_target=_is_hr_target_surface(item.get("heading")),
            )
            if state:
                item["outcome_state"] = state
                item["outcome_label"] = _mlb_prop_result_label(state)
            if actual_payload:
                live_total = _mlb_live_total_text(actual_payload)
                if live_total:
                    item["live_total"] = live_total
        item["live_total"] = _home_prop_live_total(item, matched_game) or _safe_text(item.get("live_total"), None)
        item["writeup"] = _home_prop_writeup(item, player_name=player_name, market_label=market_label)
        item["display_pills"] = _home_prop_display_pills(item, live_total=item.get("live_total"))
        matchup_summary = " at ".join(part for part in [away_label, home_label] if part)
        item["matchup_summary"] = matchup_summary or _safe_text(item.get("matchup"), None)
        status_context = _safe_text(item.get("status_display"), None)
        if status_context and status_context == item.get("matchup_summary"):
            status_context = None
        item["status_context"] = status_context
        hero_live_box, hero_sim_box = _home_prop_hero_metrics(item)
        item["hero_live_box"] = hero_live_box
        item["hero_sim_box"] = hero_sim_box
        finalized.append(item)
    return finalized


def _pct_number(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", text)
    if match:
        try:
            return float(match.group(1))
        except Exception:
            return None
    numeric = _numeric_value(value)
    if numeric is None:
        return None
    if abs(numeric) <= 1.0:
        numeric *= 100.0
    return float(numeric)


def _format_home_timestamp(epoch: float | None) -> str:
    try:
        if not epoch:
            return "-"
        return central_datetime_from_epoch(float(epoch)).strftime("%I:%M %p").lstrip("0")
    except Exception:
        return "-"


def _first_present_text(*values: Any) -> str | None:
    # #100: str(value or "") is truthiness-based, so a legitimate numeric 0
    # (e.g. a projected total of 0, a model mean of 0.0) silently fell through
    # to a later, lower-priority field instead of winning the scan -- the same
    # bug class #68 fixed in _candidate_value_is_present. Every caller here
    # scans either pure text (market/pick labels, which never carry 0) or
    # numeric-capable fields (odds/projected/mean/model), so isinstance-first
    # fixes the latter without changing behavior for the former.
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value or "").strip()
        if text:
            return text
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _mlb_actual_payload_for_game(context_label: str, game_pk: int, cache: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    # #168: this used to read ONLY the cached raw_feed_live_path file, which
    # is written by the vendor daily-update's prior-day reconciliation step
    # (vendor/mlb_bettingv2/tools/daily_update.py:_refresh_feed_live_cache_for_date,
    # called with date_str=prior_date -- confirmed via direct read, it never
    # runs for TODAY's date at all) -- so for a currently-live game, this file
    # structurally does not exist yet; it only gets backfilled the day after
    # the game goes final, once it's moot for live-status purposes. That left
    # _apply_live_state_context_to_candidates' correction pass silently
    # inert for live games while /mlb/api/live-lens stayed correct, because
    # that page's own status refresh (_refresh_current_date_live_statuses,
    # mlb/live_lens.py) does a real HTTP fetch instead of only reading this
    # cache. _mlb_feed_live_payload (below) already does exactly that same
    # cache-then-live-fetch-for-today fallback for a different caller
    # (_mlb_feed_live_state) -- reuse it here instead of a second, narrower
    # copy that only had the file-read half.
    if game_pk in cache:
        return cache[game_pk]
    try:
        payload = _mlb_feed_live_payload(context_label, int(game_pk))
    except Exception:
        payload = None
    cache[game_pk] = payload if isinstance(payload, dict) else None
    return cache[game_pk]


def _mlb_actual_payload_is_final(actual_payload: dict[str, Any] | None) -> bool:
    if not isinstance(actual_payload, dict):
        return False
    status = (actual_payload.get("gameData") or {}).get("status") if isinstance(actual_payload.get("gameData"), dict) else {}
    abstract = str((status or {}).get("abstractGameState") or "").strip().lower()
    detailed = str((status or {}).get("detailedState") or "").strip().lower()
    return abstract == "final" or detailed in {"final", "game over", "completed"}


def _mlb_name_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def _mlb_headshot_from_actual_payload(player_name: Any, actual_payload: dict[str, Any] | None) -> str | None:
    target_name = _mlb_name_key(player_name)
    if not target_name or not isinstance(actual_payload, dict):
        return None
    try:
        from syndicate.features.mlb.cards import _mlb_headshot_url
    except Exception:
        return None

    boxscore = (actual_payload.get("liveData") or {}).get("boxscore") if isinstance(actual_payload.get("liveData"), dict) else {}
    teams = boxscore.get("teams") if isinstance(boxscore, dict) else {}
    for side in ("away", "home"):
        team = teams.get(side) if isinstance(teams, dict) else {}
        players = team.get("players") if isinstance(team, dict) else {}
        if not isinstance(players, dict):
            continue
        for player_obj in players.values():
            if not isinstance(player_obj, dict):
                continue
            person = player_obj.get("person") if isinstance(player_obj.get("person"), dict) else {}
            if _mlb_name_key(person.get("fullName")) != target_name:
                continue
            return _mlb_headshot_url(_int_or_none(person.get("id")))
    return None


def _basketball_headshot_url(player_id: Any) -> str | None:
    pid = _int_or_none(player_id)
    if pid is None:
        return None
    return f"https://cdn.nba.com/headshots/nba/latest/1040x760/{pid}.png"


def _basketball_espn_headshot_url(player_id: Any) -> str | None:
    pid = _int_or_none(player_id)
    if pid is None:
        return None
    return f"https://a.espncdn.com/i/headshots/nba/players/full/{pid}.png"


def _basketball_best_headshot_url(*, player_id: Any = None, photo: Any = None) -> str | None:
    photo_url = str(photo or "").strip() or None
    return _basketball_headshot_url(player_id) or photo_url or _basketball_espn_headshot_url(player_id)


def _basketball_canonical_team(sport_slug: str, team_tri: Any) -> str:
    raw_value = str(team_tri or "").strip().upper()
    if not raw_value:
        return ""
    try:
        if sport_slug == "nba":
            from syndicate.features.nba.cards import _canonical_nba_tri

            return _canonical_nba_tri(raw_value)
        if sport_slug == "wnba":
            from syndicate.features.wnba.cards import _canonical_wnba_tri

            return _canonical_wnba_tri(raw_value)
    except Exception:
        return raw_value
    return raw_value


def _basketball_player_id_index(sport_slug: str) -> dict[tuple[str, str], int]:
    cached = _BASKETBALL_PLAYER_ID_CACHE.get(sport_slug)
    if cached is not None:
        return cached

    index: dict[tuple[str, str], int] = {}
    try:
        if sport_slug == "nba":
            from syndicate.features.nba.sources import processed_path

            player_ids_path = processed_path("player_ids.csv")
            if player_ids_path.exists():
                with player_ids_path.open("r", encoding="utf-8", newline="") as handle:
                    for row in csv.DictReader(handle):
                        name_key = _mlb_name_key(row.get("player_name") or row.get("PLAYER_NAME"))
                        player_id = _int_or_none(row.get("player_id") or row.get("PLAYER_ID"))
                        team_key = _basketball_canonical_team(sport_slug, row.get("team") or row.get("TEAM_ABBREVIATION"))
                        if not name_key or player_id is None:
                            continue
                        if team_key:
                            index[(team_key, name_key)] = player_id
                        index.setdefault(("", name_key), player_id)
        elif sport_slug == "wnba":
            from syndicate.features.wnba.sources import _source_roots

            for root in _source_roots():
                processed_root = root / "data" / "processed"
                for boxscore_path in sorted(processed_root.glob("boxscores_*.csv"), reverse=True):
                    with boxscore_path.open("r", encoding="utf-8", newline="") as handle:
                        for row in csv.DictReader(handle):
                            name_key = _mlb_name_key(row.get("player_name") or row.get("PLAYER_NAME"))
                            player_id = _int_or_none(row.get("player_id") or row.get("PLAYER_ID"))
                            team_key = _basketball_canonical_team(sport_slug, row.get("team") or row.get("TEAM_ABBREVIATION"))
                            if not name_key or player_id is None:
                                continue
                            if team_key:
                                index.setdefault((team_key, name_key), player_id)
                            index.setdefault(("", name_key), player_id)
    except Exception:
        index = {}

    _BASKETBALL_PLAYER_ID_CACHE[sport_slug] = index
    return index


def _basketball_resolve_player_id(sport_slug: str, *, player_name: Any, team_tri: Any = None, player_id: Any = None) -> int | None:
    resolved_player_id = _int_or_none(player_id)
    if resolved_player_id is not None:
        return resolved_player_id
    name_key = _mlb_name_key(player_name)
    if not name_key:
        return None
    team_key = _basketball_canonical_team(sport_slug, team_tri)
    index = _basketball_player_id_index(sport_slug)
    if team_key:
        by_team = index.get((team_key, name_key))
        if by_team is not None:
            return by_team
    return index.get(("", name_key))


def _player_name_from_prop_title(title: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(title or "").strip())
    if not text:
        return None
    match = re.match(r"^(?P<player>.+?)\s+(?:Over|Under)\s+[+-]?\d", text, flags=re.IGNORECASE)
    if match:
        return match.group("player").strip() or None
    return None


def _mlb_prop_result_state(*, actual_value: float | None, line_value: float | None, selection: str, final_state: bool, is_hr_target: bool = False) -> str | None:
    if actual_value is None:
        return None
    if is_hr_target:
        if float(actual_value) >= 1.0:
            return "hit"
        return "miss" if final_state else None
    if line_value is None:
        return "hit" if float(actual_value) > 0.0 and final_state else None
    pick = str(selection or "").strip().lower()
    if pick == "over":
        if float(actual_value) > float(line_value):
            return "hit"
        return "miss" if final_state and float(actual_value) < float(line_value) else None
    if pick == "under":
        if float(actual_value) < float(line_value):
            return "hit"
        return "miss" if final_state and float(actual_value) > float(line_value) else None
    if final_state:
        return "hit" if float(actual_value) > float(line_value) else "miss"
    return None


def _mlb_prop_result_label(state: str | None) -> str | None:
    if state == "hit":
        return "Hit"
    if state == "miss":
        return "Miss"
    return None


def _mlb_prop_actual_value(item: dict[str, Any], actual_payload: dict[str, Any] | None) -> float | None:
    if not isinstance(item, dict) or not isinstance(actual_payload, dict):
        return None
    try:
        from syndicate.features.mlb.cards import _actual_batting_context_by_name
        from syndicate.features.mlb.cards import _actual_hitter_stat_value
        from syndicate.features.mlb.cards import _actual_pitcher_stat_value
    except Exception:
        return None

    batting_rows = _actual_batting_context_by_name(actual_payload)
    pitching_rows = None
    name = _mlb_name_key(item.get("name") or item.get("player_name") or item.get("playerName"))
    if not name:
        return None

    market_text = " ".join(
        str(value or "").lower()
        for value in [item.get("market"), item.get("heading"), item.get("market_label"), item.get("detail")]
    )
    prop_key = None
    pitcher_mode = False
    if "outs" in market_text:
        prop_key = "outs"
        pitcher_mode = True
    elif "strikeout" in market_text or market_text.startswith("k"):
        prop_key = "strikeouts"
        pitcher_mode = True
    elif "hits allowed" in market_text:
        prop_key = "hits_allowed"
        pitcher_mode = True
    elif "walk" in market_text:
        prop_key = "walks_allowed"
        pitcher_mode = True
    elif "earned run" in market_text:
        prop_key = "earned_runs"
        pitcher_mode = True
    elif "home run" in market_text or str(item.get("heading") or "").strip().lower() == "hr targets":
        prop_key = "home_runs"
    elif "total base" in market_text:
        prop_key = "total_bases"
    elif "run scored" in market_text:
        prop_key = "runs_scored"
    elif "rbi" in market_text:
        prop_key = "rbis"
    elif "hit" in market_text:
        prop_key = "hits"

    actual_row = batting_rows.get(name)
    if actual_row and not pitcher_mode:
        return _actual_hitter_stat_value(actual_row.get("stats") if isinstance(actual_row, dict) else None, prop_key or "hits")

    try:
        from syndicate.features.mlb.cards import _actual_pitching_context_by_name
    except Exception:
        return None
    pitching_rows = _actual_pitching_context_by_name(actual_payload)
    actual_row = pitching_rows.get(name)
    if actual_row and pitcher_mode:
        return _actual_pitcher_stat_value(actual_row.get("stats") if isinstance(actual_row, dict) else None, prop_key or "outs")
    return None


def _mlb_live_total_text(actual_payload: dict[str, Any] | None) -> str | None:
    if not isinstance(actual_payload, dict):
        return None
    linescore = ((actual_payload.get("liveData") or {}).get("linescore")) if isinstance(actual_payload.get("liveData"), dict) else {}
    teams = (linescore or {}).get("teams") if isinstance(linescore, dict) else {}
    away_runs = _numeric_value(((teams or {}).get("away") or {}).get("runs"))
    home_runs = _numeric_value(((teams or {}).get("home") or {}).get("runs"))
    if away_runs is None or home_runs is None:
        return None
    return _score_value(float(away_runs) + float(home_runs))


_PROP_PICK_SELECTION_PREFIX_RE = re.compile(r"^(?:over|under)\s+(.+)$", re.IGNORECASE)
# Phase C (Layer 2 task): WNBA's recommendations_slate PROPS picks use the
# opposite word order from MLB's panels -- "Kelsey Mitchell OVER 1.5", name
# first -- confirmed via a direct read of a real recommendations_slate_*.json
# artifact (every PROPS entry's display_pick follows this shape, and carries
# no separate player/player_id field at all). The prefix regex above never
# matches this shape (it requires over/under to lead), so this was silently
# returning None for every WNBA/NBA prop candidate built from this path --
# not a name-formatting bug, a total non-match.
_PROP_PICK_SELECTION_SUFFIX_RE = re.compile(r"^(.+?)\s+(?:over|under)\s+[\d.,+-]+\s*$", re.IGNORECASE)


def _player_name_from_prop_pick_text(pick_text: str) -> str | None:
    # game["shared_top_play_rows"] (game_board_contract.py's _build_top_play_rows)
    # is a generic display-panel highlights list -- title becomes "market",
    # each item's free text becomes "pick" -- with no dedicated player field
    # at all. For MLB hitter/pitcher stat panels that text is consistently
    # "OVER/UNDER <Player Name>" (confirmed live 2026-07-23: every one of
    # these rows sampled matched), so the player identity is present, just
    # never extracted into a structured field. Without this, every hitter/
    # pitcher candidate built from this path showed a blank entity and a
    # blank Projected value, and (worse) looked identical to a genuinely
    # entity-less duplicate from another pipeline.
    text = str(pick_text or "").strip()
    match = _PROP_PICK_SELECTION_PREFIX_RE.match(text)
    if match:
        name = match.group(1).strip()
        if not name or re.fullmatch(r"[\d.,+-]+", name):
            # Other callers use this same "Over <line>" convention for the pick
            # text (e.g. game_market_recommendations rows), where the remainder
            # is a numeric line, not a player name -- never mistake one for the
            # other.
            return None
        return name
    # WNBA/NBA convention ("<Player Name> OVER/UNDER <line>") -- see the
    # regex's own comment above.
    suffix_match = _PROP_PICK_SELECTION_SUFFIX_RE.match(text)
    if suffix_match:
        name = suffix_match.group(1).strip()
        if name:
            return name
    return None


def _market_label_from_pick_text(text: str) -> str:
    lowered = text.lower()
    if "total" in lowered or lowered.startswith("over") or lowered.startswith("under"):
        return "Total"
    if "+1.5" in lowered or "-1.5" in lowered or "spread" in lowered or "puck" in lowered:
        return "Spread"
    if "moneyline" in lowered or lowered.startswith("ml"):
        return "Moneyline"
    if "first 10" in lowered:
        return "First 10"
    return "Game bet"


def _game_row_updated_epoch(game: dict[str, Any], fallback_epoch: float) -> float:
    for value in [
        game.get("updated_at"),
        game.get("updatedAt"),
        game.get("generatedAt"),
        game.get("generated_at"),
        game.get("lastSeenAt"),
        game.get("last_seen_at"),
    ]:
        parsed = _parse_timestamp_epoch(value)
        if parsed > 0:
            return parsed
    return fallback_epoch


def _game_full_period_row(game: dict[str, Any]) -> dict[str, Any] | None:
    """The same "full game" (or last available period) row from
    shared_period_rows that _game_sim_vs_line_reasoning reads -- split out
    so _game_bet_narrative below can reuse the row lookup (main/market/
    best_edge) without duplicating it or changing
    _game_sim_vs_line_reasoning's own return shape, which existing tests
    pin exactly."""
    period_rows = game.get("shared_period_rows") if isinstance(game.get("shared_period_rows"), list) else []
    row = next(
        (item for item in period_rows if isinstance(item, dict) and _safe_text(item.get("label"), "").strip().lower() == "full game"),
        None,
    )
    if row is None and period_rows and isinstance(period_rows[-1], dict):
        row = period_rows[-1]
    return row if isinstance(row, dict) else None


def _game_sim_vs_line_reasoning(game: dict[str, Any]) -> str | None:
    """Surface the sim-vs-market-line comparison game_board_contract.py
    already computes (shared_period_rows' "main"/"market"/"best_edge") --
    it sits right there on the same game dict _game_bet_candidates_from_game
    already has in scope, but never got read, so ATS/Total/Moneyline
    candidates never carried the same sim-vs-line context the sport pages
    show for the same game."""
    row = _game_full_period_row(game)
    if row is None:
        return None
    parts: list[str] = []
    main = _safe_text(row.get("main"), "")
    if main:
        parts.append(f"Sim: {main}")
    market_text = _safe_text(row.get("market"), "")
    if market_text and market_text != "-":
        parts.append(f"Market: {market_text}")
    best_edge = _safe_text(row.get("best_edge"), "")
    if best_edge and best_edge != "-":
        parts.append(f"Model edge vs. line: {best_edge}")
    return " | ".join(parts) if parts else None


_LOW_INFORMATION_GAME_DETAIL_PHRASES = ("oddsapi_consensus market snapshot", "no game-bet summary available.")


def _is_low_information_game_detail(text: str) -> bool:
    """True for a "detail" string that carries no real per-pick analysis --
    either of the two known internal placeholder sentinels, or MLB
    cards.py's own real-but-generic "{starter} vs {starter} | N official
    pick(s)" summary (game.get("summary")'s literal shape there -- a real,
    non-placeholder string, so the exact-placeholder check alone doesn't
    catch it, but reported live 2026-08-04 as exactly the kind of "terse
    pitcher-matchup metadata" that isn't the actual analysis being asked
    for either). Checked via a specific, identifiable substring
    ("official pick(") rather than a general "vs" scan, which would
    false-positive on a genuine analytical sentence that happens to
    compare two things."""
    normalized = text.strip().lower()
    if normalized in _LOW_INFORMATION_GAME_DETAIL_PHRASES:
        return True
    return "official pick(" in normalized


def _game_bet_narrative_subject(*, team_text: str | None, pick_text: str | None) -> str:
    # Found live 2026-08-04: _team_for_side_hint resolves correctly, but
    # some sports' own team dicts (confirmed for WNBA) carry an abbreviated
    # code ("NYL") rather than a full display name in the same field
    # _game_team_label reads -- "The model favors NYL for the ats" instead
    # of the full team name. Fixing that data gap per-sport is out of
    # scope here; picking whichever candidate string is more descriptive
    # sidesteps it without depending on any one sport's naming being
    # correct -- an abbreviation is always short, a real team name or a
    # full selection string ("New York Liberty -9.5") never is.
    candidates = [text for text in (team_text, pick_text) if text and text != "-"]
    return max(candidates, key=len) if candidates else "this pick"


def _game_bet_narrative(*, market: str, subject: str, model_probability_pct: float | None, odds: Any, edge_pct: float | None, game: dict[str, Any]) -> str | None:
    """Real analysis prose for a moneyline/spread/total candidate, mirroring
    the player-prop generator's shape (model probability vs. a real
    market-implied probability, edge, sim projection) instead of the raw
    "Sim: X | Market: Y" pipe-joined label _game_sim_vs_line_reasoning
    produces, or the internal "oddsapi_consensus market snapshot"
    placeholder game.get("summary") sometimes carries (found live
    2026-08-04, filtered at Ask's own read layer by dc4b9553 -- this is
    the actual upstream fix: generate real prose instead of relying on a
    downstream filter to hide the absence of any).

    Every number here is real (already computed by this same candidate
    builder, or the actual posted odds) -- returns None rather than a
    templated sentence with nothing behind it when there isn't enough
    real data to say something specific.
    """
    if model_probability_pct is None:
        return None
    try:
        from syndicate.features.shared.odds_lifecycle import _implied_probability_from_american_odds
    except Exception:
        _implied_probability_from_american_odds = None  # type: ignore[assignment]

    market_probability_pct = None
    if _implied_probability_from_american_odds is not None and odds is not None:
        implied = _implied_probability_from_american_odds(odds)
        if implied is not None:
            market_probability_pct = implied * 100.0

    sentence = f"The model favors {subject} for the {market.lower()}, projecting a {model_probability_pct:.1f}% chance"
    if market_probability_pct is not None:
        sentence += f" against a market price near {market_probability_pct:.1f}%"
    sentence += "."
    if edge_pct is not None:
        sentence += f" Model edge vs. the market: {edge_pct:.1f}%."
    row = _game_full_period_row(game)
    main = _safe_text(row.get("main"), "") if row else ""
    # game_board_contract.py's own "main" falls back to game.get("summary")
    # when there's no real projected score (see its docstring reference) --
    # the same placeholder this whole function exists to replace can leak
    # back in right here otherwise. Found live 2026-08-04: "Model projects
    # oddsapi_consensus market snapshot." on several real candidates.
    if main and not _is_low_information_game_detail(main):
        sentence += f" Model projects {main}."
    return sentence


def _looks_like_badge_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if re.match(r"^[+-]?\d+(?:\.\d+)?\s*%", text):
        return True
    return text.lower().endswith("ev") and "%" in text


def _candidate_pick_text(item: dict[str, Any]) -> str:
    # player_name/name/pick/selection are frequently duplicates of the same
    # string, but on "prop"-typed candidates name/pick/selection sometimes
    # leak a bare "36.2% EV" badge instead of the real pick text while
    # player_name stays clean -- so player_name is checked first, matching
    # the same guard intelligence.html's board JS already applies.
    for key in ("player_name", "name", "pick", "selection"):
        text = str(item.get(key) or "").strip()
        if text and text.lower() not in {"-", "—", "n/a", "unknown"} and not _looks_like_badge_text(text):
            return text
    return "-"


def _candidate_edge_fraction(item: dict[str, Any]) -> float:
    # Mirrors intelligence.html's edgeValue() precedence exactly (edge ??
    # adjusted_edge ?? expected_value ?? ev_current ?? 0) so the home page
    # and the board never disagree about which number is "the edge" for the
    # same candidate -- an `or` chain would wrongly skip a real 0.0/-0.0 edge.
    for key in ("edge", "adjusted_edge", "expected_value", "ev_current"):
        value = _numeric_value(item.get(key))
        if value is not None:
            return value
    return 0.0


def _board_candidate_rows(selected_date: str, *, limit: int = 12) -> list[dict[str, Any]]:
    """Read-only reuse of whatever the /intelligence board already has cached
    for this date, instead of re-deriving a second, much narrower candidate
    list from raw per-sport dashboard artifacts. force_refresh is always
    False here -- the home page must never trigger a live board recompute
    just to render its top-edges rail (Render web/worker headroom is tight).

    Plan item 1F ("one contract, not one pipeline per surface"): this used
    to hand-roll its own two-layer read (worker state, then board snapshot),
    a parallel path that predated -- and so never benefited from -- the
    canonical-board-state-first cascade in
    _cached_intelligence_response_with_source (which also carries the
    analysis_views/headline promotion fix and the same staleness checks).
    Calling that shared function directly means Home and the Board can no
    longer silently disagree about what "cached" means for the same date.
    """
    try:
        from syndicate.blueprints.intelligence import _intelligence_page_payload
        from syndicate.blueprints.intelligence import _cached_intelligence_response_with_source
    except Exception:
        return []

    try:
        payload = _intelligence_page_payload(selected_date, force_refresh=False)
        response, _source = _cached_intelligence_response_with_source(payload, force_refresh=False)
    except Exception:
        return []
    if not isinstance(response, dict):
        return []

    nested = response.get("response") if isinstance(response.get("response"), dict) else {}
    analysis = response.get("analysis") if isinstance(response.get("analysis"), dict) else (nested.get("analysis") if isinstance(nested.get("analysis"), dict) else {})
    candidates = (
        response.get("recommendations")
        or nested.get("recommendations")
        or response.get("top_opportunities")
        or nested.get("top_opportunities")
        or analysis.get("recommendations")
        or []
    )
    if not isinstance(candidates, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        edge_fraction = _candidate_edge_fraction(item)
        rows.append(
            {
                "sport": _safe_text(item.get("sport"), str(item.get("sport_slug") or "").upper()),
                "sport_slug": _safe_text(item.get("sport_slug"), "sport").lower(),
                "matchup": _safe_text(item.get("matchup"), "-"),
                "market": _safe_text(item.get("market_type") or item.get("market") or item.get("candidate_type"), "-"),
                "pick": _candidate_pick_text(item),
                "edge": f"{edge_fraction * 100:.1f}%",
                "confidence": _safe_text(item.get("confidence"), "-"),
                "is_live": bool(item.get("is_live")),
                "href": str(item.get("href") or "").strip() or None,
                "score": abs(edge_fraction) * 150.0,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _game_current_combined_score(game: dict[str, Any]) -> float | None:
    # The board's Live column was empty for every Moneyline/Spread/Total
    # candidate built from the plain "betting" dict (the common case) --
    # none of those call sites ever passed live_projection, so
    # _append_game_bet_candidate always fell back to its "-" default
    # regardless of whether the game was actually live. This is the one
    # signal that's meaningful across all three market types (current
    # combined score, directly comparable to a Total line): try the
    # normalized away/home score fields first, then live_state's away_pts/
    # home_pts (same shape WNBA/NBA live-state builders already use), then
    # flat away_score/home_score as a last resort.
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    away_score = _numeric_value(away.get("score"))
    if away_score is None:
        away_score = _numeric_value(live_state.get("away_pts"))
    if away_score is None:
        away_score = _numeric_value(game.get("away_score"))
    home_score = _numeric_value(home.get("score"))
    if home_score is None:
        home_score = _numeric_value(live_state.get("home_pts"))
    if home_score is None:
        home_score = _numeric_value(game.get("home_score"))
    if away_score is None or home_score is None:
        return None
    return away_score + home_score


def _game_current_scoreline(game: dict[str, Any]) -> str | None:
    # Board-alignment audit, found live 2026-08-01 against a real live WNBA
    # game: _game_current_combined_score's away+home sum is the right
    # "actual" for a Total candidate (directly comparable to the total
    # line) but was ALSO being used, unchanged, for Moneyline/Spread/ATS
    # candidates -- every game-level market for the same live game showed
    # the identical combined number (e.g. "120") regardless of market,
    # which tells a Moneyline/ATS bettor nothing about which side is
    # actually ahead. Same score-field fallback chain as
    # _game_current_combined_score, just returned as "away-home" instead
    # of summed.
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    away_score = _numeric_value(away.get("score"))
    if away_score is None:
        away_score = _numeric_value(live_state.get("away_pts"))
    if away_score is None:
        away_score = _numeric_value(game.get("away_score"))
    home_score = _numeric_value(home.get("score"))
    if home_score is None:
        home_score = _numeric_value(live_state.get("home_pts"))
    if home_score is None:
        home_score = _numeric_value(game.get("home_score"))
    if away_score is None or home_score is None:
        return None
    return f"{away_score:.0f}-{home_score:.0f}"


def _gamelens_matching_pregame_value(candidates: list[dict[str, Any]], *, market_family: str, pick_text: str, field: str = "projected") -> Any:
    # A gameLens segment never carries a genuine PREGAME value of its own --
    # everything on it (segment_projection, per-market overrides) reflects
    # live/current-segment state. The only place a real pregame projection
    # exists for the same market+side is the plain betting-dict candidate
    # _game_bet_candidates_from_game already appended earlier in this same
    # `candidates` list for this game (the plain block and the gameLens
    # block both run unconditionally, back to back, into the same list --
    # additive, not alternative sources -- so it's always there by the time
    # this runs, for a live game with a real pregame market to begin with).
    side_key = str(pick_text or "").strip().split(" ", 1)[0].strip().lower()
    if not side_key:
        return None
    for existing in candidates:
        if _safe_text(existing.get("market"), "") != market_family:
            continue
        existing_side = str(existing.get("pick") or "").strip().split(" ", 1)[0].strip().lower()
        if existing_side != side_key:
            continue
        value = existing.get(field)
        if value not in (None, "-"):
            return value
    return None


def _gamelens_segment_actual_value(lens: dict[str, Any], *, market_key: str, pick_text: str) -> float | None:
    # lens["actualSegment"] (real box-score segment totals, {"home","away"})
    # passes through verbatim from the vendored live-lens payload into
    # game["gameLens"] but was never read anywhere in this codebase before --
    # every gameLens candidate's "actual" silently stayed unset/"-".
    segment = lens.get("actualSegment") if isinstance(lens.get("actualSegment"), dict) else {}
    home_actual = _numeric_value(segment.get("home"))
    away_actual = _numeric_value(segment.get("away"))
    if home_actual is None or away_actual is None:
        return None
    if market_key == "total":
        return home_actual + away_actual
    side = str(pick_text or "").strip().split(" ", 1)[0].strip().lower()
    margin = home_actual - away_actual
    if side == "home":
        return margin
    if side == "away":
        return -margin
    return margin


# Maps a recommendation prop row's canonical `prop` key to the stat-specific
# `*_mean` field that holds its real projected value. Necessary because a
# hitter prop row carries several means (e.g. batter_hits has ab_mean, pa_mean
# AND h_mean) -- grabbing the first `*_mean` would show plate appearances,
# not hits. Mirrors the pitcher/hitter market specs in
# syndicate/features/mlb/cards.py (ALL_*_MARKET_SPECS mean_key).
_MLB_PROP_MEAN_KEY_BY_PROP = {
    "outs": "outs_mean",
    "strikeouts": "so_mean",
    "hits_allowed": "hits_mean",
    "walks_allowed": "walks_mean",
    "earned_runs": "er_mean",
    "pitches": "pitches_mean",
    "batter_hits": "h_mean",
    "batter_total_bases": "tb_mean",
    "batter_runs_scored": "r_mean",
    "batter_rbis": "rbi_mean",
    "batter_home_runs": "hr_mean",
}


def _mlb_prop_projected_value(prop_row: dict[str, Any]) -> float | None:
    # The real projected stat count (e.g. 20.7 outs) lives under the row's
    # stat-specific `*_mean` key -- the generic projection/mean/model keys the
    # game-bet builder normally reads are absent on these recommendation-engine
    # prop rows, which is why the board showed a blank projection. Prefer the
    # market-specific key; fall back to a lone `*_mean` only when unambiguous.
    stat_key = str(prop_row.get("prop") or "").strip().lower()
    mean_key = _MLB_PROP_MEAN_KEY_BY_PROP.get(stat_key)
    if mean_key is not None:
        value = _numeric_value(prop_row.get(mean_key))
        if value is not None:
            return value
    mean_keys = [
        key
        for key in prop_row
        if isinstance(key, str) and key.endswith("_mean") and key != "mean_support"
    ]
    if len(mean_keys) == 1:
        return _numeric_value(prop_row.get(mean_keys[0]))
    return None


def _mlb_prop_player_id(prop_row: dict[str, Any]) -> int | None:
    for key in ("pitcher_id", "batter_id", "player_id"):
        value = _int_or_none(prop_row.get(key))
        if value is not None:
            return value
    return None


def _append_game_bet_candidate(candidates: list[dict[str, Any]], *, sport: dict[str, Any], game: dict[str, Any], market: str, pick: str, line: Any = None, odds: Any = None, edge: Any = None, confidence: Any = None, projected: Any = None, live_projection: Any = None, actual: Any = None, detail: str | None = None, fallback_epoch: float, live_odds_game_ids: set[str] | None = None, team: Any = None, sim_context: str | None = None, player_id: Any = None, headshot_url: str | None = None, quote: dict[str, Any] | None = None, price_improvement_pct: Any = None) -> None:
    pick_text = _safe_text(pick, "-")
    if pick_text == "-":
        return
    line_text = _prop_metric_text(line) if line is not None else None
    odds_text = _prop_metric_text(odds) if odds is not None else None
    edge_text = _pct_text(edge) if edge is not None and _numeric_value(edge) is not None else _safe_text(edge, "-") if edge is not None else "-"
    confidence_text = _pct_text(confidence) if confidence is not None and _numeric_value(confidence) is not None else _safe_text(confidence, "-") if confidence is not None else "-"
    projected_text = _prop_metric_text(projected) if projected is not None else "-"
    team_text = _safe_text(team, "-") if team is not None else "-"
    game_state = _game_status_state(game)
    # Used to be _is_liveish(game.get("status"), game.get("detail")) --
    # _is_liveish expects TEXT (it string-matches for "in progress", etc.),
    # but game.get("status") is a dict on every normalized game shape here.
    # str()-ing that dict happened to contain "in_progress" (underscore),
    # never the space-separated "in progress" _is_liveish actually looks
    # for, so this never detected a live game on its own -- it only worked
    # at all when game.get("shared_is_live") was already true. Reuse the
    # already-reliable _game_status_state() instead of re-deriving liveness
    # from raw status text.
    #
    # NOTE: do NOT also check "live" in market text here. The gameLens loop
    # below labels every market it emits with lens.get("label", "Live") --
    # a decorative section name, not evidence the game has actually started
    # -- so an open-but-pregame lens entry produced a "Live Moneyline"
    # candidate that was force-flipped live while the same game's Spread
    # candidate (built from the plain "betting" dict, no "Live" prefix)
    # correctly stayed pregame. game_state/shared_is_live are the real signal.
    # Was `shared_is_live or game_state == "live"`, which re-introduced the
    # exact bug _game_status_state was just taught to resolve: that function
    # already folds shared_is_live in, and now refuses it when a structured
    # in_progress/live says otherwise -- so OR-ing the raw flag back in here
    # let the contradicted value win anyway. Confirmed 2026-07-26: yesterday's
    # finished MLS fixtures published as LIVE picks off this line.
    fallback_live = game_state == "live"
    is_live = _live_odds_backed_live_flag(_game_identifier(game), live_odds_game_ids, fallback_live)
    # Real regression found 2026-07-23: this function also builds per-game
    # PLAYER PROP candidates (market == f"Hitter {prop_type}"/f"Pitcher
    # {prop_type}", mixed in alongside genuine Moneyline/Spread/Total by the
    # gameLens loop below), none of which pass an explicit actual value --
    # the combined-score fallback was applying the GAME's total score to
    # every hitter/pitcher prop candidate for that game regardless of stat
    # type, so completely different props (total bases, hits, for different
    # players) all showed the identical number. The combined score is only
    # meaningful for genuine game-level markets.
    #
    # Phase C (Layer 2 task), found live 2026-07-31: this used to be a local
    # "starts with Hitter /Pitcher " check -- an MLB-only naming convention.
    # WNBA/NBA player props are labeled by short stat code ("PTS", "REB",
    # "PRA", ...) or the generic "PROPS", none of which start with "Hitter "/
    # "Pitcher ", so this check misclassified every non-MLB player prop as a
    # GAME-level market: it suppressed player_name extraction below AND
    # stamped the game's combined score as "actual" on real player props
    # (e.g. a WNBA points prop candidate showing the game's total score
    # instead of "-"/the real per-player stat) -- the exact bug class the
    # comment above already documents, just not caught for other sports.
    # intelligence.py's own `_is_game_level_market` already gets this right
    # (a keyword allowlist -- moneyline/spread/total/etc -- rather than an
    # MLB-specific denylist), so reuse it here instead of a second,
    # narrower copy that only worked for MLB. Deferred import: intelligence.py
    # imports from this module already, so a module-level import here would
    # be circular.
    market_text_lower = _safe_text(market, "").strip().lower()
    try:
        from syndicate.features.intelligence import _is_game_level_market as _shared_is_game_level_market

        is_game_level_market = _shared_is_game_level_market(market_text_lower)
    except Exception:
        is_game_level_market = not (market_text_lower.startswith("hitter ") or market_text_lower.startswith("pitcher "))
    live_projection_text = _prop_metric_text(live_projection) if live_projection is not None else "-"
    # The current combined score is real, live GAME STATE -- not a
    # projection of anything -- so it belongs in "actual", never as a
    # stand-in for a missing live_projection (that used to conflate the two
    # under one label, implying a sim result that was actually just the
    # scoreboard).
    if actual is None and is_live and is_game_level_market:
        # Total is the one market genuinely comparable to a combined
        # away+home number -- every other game-level market (Moneyline,
        # Spread/ATS) gets the actual scoreline instead, so "actual" means
        # something for the side that market is actually about.
        if "total" in market_text_lower:
            actual = _game_current_combined_score(game)
        else:
            actual = _game_current_scoreline(game)
    actual_text = _prop_metric_text(actual) if actual is not None else "-"
    player_name = None if is_game_level_market else _player_name_from_prop_pick_text(pick_text)
    edge_value = _pct_number(edge_text)
    confidence_value = _pct_number(confidence_text)
    # #98/#100. MLB's game-market translation (_mlb_game_market_recommendation_rows)
    # only ever carries a win probability under "confidence" -- it never sets
    # projected/projection/model/mean -- so every MLB pregame moneyline/total
    # candidate classified as missing_projection_or_odds even though real
    # model data was present: normalize_candidate's projection scan checks
    # model_probability (a raw 0-1 fraction), never confidence (percent-
    # formatted display text). Stamping the raw fraction here, at the single
    # choke point every sport's game-level candidate passes through, is the
    # correct semantic slot for a model probability -- same reasoning as
    # #92's hr_probability fix -- and only takes effect when nothing higher
    # in the scan order (projected/edge/etc.) is already present.
    model_probability = _numeric_value(confidence) if confidence is not None else None
    if model_probability is not None and abs(model_probability) > 1.0:
        model_probability = model_probability / 100.0
    updated_epoch = _game_row_updated_epoch(game, fallback_epoch)
    href = str(game.get("href") or sport.get("hub_href") or sport.get("primary_href") or "").strip() or None
    base_detail = _safe_text(detail or game.get("summary") or game.get("detail"), "No game-bet summary available.")
    # Found live 2026-08-04 (dc4b9553): "detail" here was frequently the
    # internal "oddsapi_consensus market snapshot" sentinel (meaning "no
    # real sim summary yet") rather than real analysis -- previously only
    # filtered downstream, at Ask's own read layer. Generate real prose
    # from the same real inputs this candidate already carries (model
    # probability, actual posted odds, edge, sim projection) whenever the
    # upstream detail is that placeholder or genuinely absent, rather than
    # relying on a downstream filter to hide the absence of real analysis.
    # Scoped to game-level markets only -- player props already carry real
    # generated prose from the vendored sim pipeline in "detail". Also
    # catches MLB cards.py's real-but-generic "{starter} vs {starter} | N
    # official pick(s)" summary, not just the two internal sentinels --
    # reported live 2026-08-04 as exactly the "terse pitcher-matchup
    # metadata" that isn't real analysis either.
    narrative = (
        _game_bet_narrative(
            market=_safe_text(market, "market"),
            subject=_game_bet_narrative_subject(team_text=team_text, pick_text=pick_text),
            model_probability_pct=confidence_value,
            odds=odds,
            edge_pct=edge_value,
            game=game,
        )
        if is_game_level_market and _is_low_information_game_detail(base_detail)
        else None
    )
    if narrative:
        detail_text = narrative
    else:
        detail_text = base_detail
        if sim_context and sim_context not in base_detail:
            detail_text = f"{base_detail} {sim_context}".strip() if base_detail and base_detail != "No game-bet summary available." else sim_context
    candidates.append(
        {
            "game_id": _game_identifier(game),
            "gamePk": game.get("gamePk") or game.get("game_pk") or game.get("game_id"),
            "event_id": game.get("event_id"),
            # #162: soccer covers several leagues (MLS, La Liga, ...) but
            # "sport" for it was always the generic family label "Soccer" --
            # every game/board card badge read "SOCCER" regardless of which
            # league the match was actually in. game.get("league_display")
            # is only ever set by soccer's own game builders
            # (soccer/cards.py), so this is a no-op for every other sport;
            # sport_slug below stays the family slug either way, so
            # sport-tab filtering and game-chip id-matching (both keyed on
            # sport_slug, not this display field) are unaffected.
            "sport": _safe_text(game.get("league_display"), "") or _safe_text(sport.get("name"), str(sport.get("slug") or "").upper()),
            "sport_slug": _safe_text(sport.get("slug"), "sport").lower(),
            "matchup": _sport_matchup(game),
            "market": _safe_text(market, _market_label_from_pick_text(pick_text)),
            "pick": pick_text,
            "team": team_text,
            "entity": player_name,
            "player_name": player_name,
            "player_id": _int_or_none(player_id),
            "headshot_url": (str(headshot_url).strip() or None) if headshot_url else None,
            "is_live": is_live,
            "is_final": game_state == "final",
            "game_state": game_state or None,
            "line": line_text or "-",
            "odds": odds_text or "-",
            "edge": edge_text,
            "confidence": confidence_text,
            "model_probability": model_probability,
            "projected": projected_text,
            "live_projection": live_projection_text,
            "actual": actual_text,
            "updated_at": _format_home_timestamp(updated_epoch),
            "updated_epoch": updated_epoch,
            "detail": detail_text,
            "sim_context": sim_context,
            "href": href,
            "href_label": _safe_text(game.get("href_label"), "Open game"),
            "score": float((edge_value or 0.0) * 1.8 + (confidence_value or 0.0) + (20.0 if odds_text and odds_text != "-" else 0.0)),
            # #215 -- the price context the row contract never had. Flattened
            # alongside the full quote because the template renders chips from
            # scalars and the nested object is for the drill-in / API consumers.
            "quote": dict(quote) if isinstance(quote, dict) else None,
            "book": (quote or {}).get("bookmaker"),
            "best_book": (quote or {}).get("best_bookmaker"),
            "best_price": (quote or {}).get("best_price"),
            "books_quoting": (quote or {}).get("books_quoting"),
            "price_rank": (quote or {}).get("price_rank"),
            "consensus_price": (quote or {}).get("consensus_price"),
            "price_improvement_pct": price_improvement_pct,
            # TWO CLOCKS. book_age is how long since the BOOK moved this number;
            # capture_age is how long since we looked. A row with a 4-hour book
            # age and a 30-second capture age is a dead market, and the single
            # `updated_at` above -- which is loop time -- renders it as fresh.
            "book_age_seconds": (quote or {}).get("book_age_seconds"),
            "capture_age_seconds": (quote or {}).get("capture_age_seconds"),
            "book_updated_at": (quote or {}).get("book_updated_at"),
        }
    )


def _game_bet_candidates_from_game(sport: dict[str, Any], game: dict[str, Any], *, fallback_epoch: float, live_odds_game_ids: set[str] | None = None) -> list[dict[str, Any]]:
    # #77. A "not yet simulated" placeholder is a page-level empty state, not a
    # bettable game, and must never become a candidate. Gated here rather than
    # at either caller because both _game_candidates_for_sport and
    # _collect_candidates walk dashboard_games, and this is the one function
    # they share.
    #
    # Confirmed in production 2026-07-26: soccer placeholders reached the
    # Layer 2 board flagged live, with the operator instruction
    # "Run scripts/build_soccer_artifacts.py --league mls --date ..." rendered
    # as the pick, and null odds/line/edge behind it.
    #
    # Keyed on the explicit marker the producer sets, deliberately not on the
    # placeholder prose -- matching that text would break the moment the copy
    # is reworded, and would silently start passing these through again.
    if bool(game.get("is_unsimulated_placeholder")):
        return []
    candidates: list[dict[str, Any]] = []
    game_sim_context = _game_sim_vs_line_reasoning(game)
    game_recs = game.get("game_market_recommendations") if isinstance(game.get("game_market_recommendations"), list) else []
    # #215: the single funnel every sport's recommendation rows pass through, so
    # per-book price context is attached once here rather than in each of the
    # five builders. This also RE-RANKS: ev_pct is recomputed against the best
    # available price where a model probability exists, which changes which
    # candidates surface -- #211 measured 140 bets clearing a 3% threshold under
    # best price and 0 the other way, since best price is never worse.
    try:
        from syndicate.features.shared.quote_enrichment import enrich_recommendation_rows

        enrich_recommendation_rows(game, game_recs, sport_slug=str(sport.get("slug") or "").lower())
    except Exception:
        # A board that renders without price context is degraded; a board that
        # 500s because the odds log was mid-write is an outage.
        pass
    for row in game_recs:
        if not isinstance(row, dict):
            continue
        row_market_text = _first_present_text(row.get("market_label"), row.get("market"), row.get("label")) or "Game bet"
        row_line = row.get("line") if row.get("line") is not None else row.get("market_line")
        row_odds = _first_present_text(row.get("odds"), row.get("price"), row.get("american_odds"))
        row_projected = (
            row.get("projected")
            if row.get("projected") is not None
            else row.get("projection") if row.get("projection") is not None else row.get("model") if row.get("model") is not None else row.get("mean")
        )
        # Board audit follow-up, found live 2026-07-31: a game_market_
        # recommendations pick with no real line, no real odds, and no real
        # model projection has nothing bettable to show -- confirmed live: a
        # WNBA bench-player pick whose upstream recommendation never had a
        # priced market surfaced as "Courtney Vandersloot OVER -" (market
        # "PROP" -- a fallback placeholder from wnba/sources.py's
        # market_label(), since the raw pick had no real market code
        # either). Scoped to non-game-level rows only via the SAME shared
        # classifier _append_game_bet_candidate itself uses below (not a
        # second, disagreeing copy) -- game-level Moneyline/Spread/Total
        # rows can legitimately lack a "line" (a Moneyline pick has none),
        # and other loops in this function (shared_top_play_rows, gameLens)
        # intentionally omit line/projected too, relying on their OWN
        # upstream validity gates instead -- this check is scoped to just
        # this one loop's rows, not a blanket rule inside
        # _append_game_bet_candidate itself, which broke those other loops
        # when tried.
        try:
            from syndicate.features.intelligence import _is_game_level_market as _shared_is_game_level_market_for_row

            row_is_game_level = _shared_is_game_level_market_for_row(row_market_text.strip().lower())
        except Exception:
            row_is_game_level = not (row_market_text.strip().lower().startswith("hitter ") or row_market_text.strip().lower().startswith("pitcher "))
        if not row_is_game_level and row_line is None and not row_odds and row_projected is None:
            continue
        _append_game_bet_candidate(
            candidates,
            sport=sport,
            game=game,
            market=row_market_text,
            pick=_first_present_text(row.get("display_pick"), row.get("selection"), row.get("pick")) or "-",
            line=row_line,
            odds=row_odds,
            edge=row.get("ev_pct") if row.get("ev_pct") is not None else row.get("edge"),
            confidence=row.get("p_win") if row.get("p_win") is not None else row.get("confidence"),
            projected=row_projected,
            live_projection=row.get("live_projection") if row.get("live_projection") is not None else row.get("liveProjection") if row.get("liveProjection") is not None else row.get("live_proj") if row.get("live_proj") is not None else row.get("projected_live"),
            detail=_first_present_text(row.get("summary"), row.get("reason"), game.get("summary")),
            fallback_epoch=fallback_epoch,
            live_odds_game_ids=live_odds_game_ids,
            team=_team_for_side_hint(game, row.get("team_side") or row.get("side") or row.get("selection") or row.get("display_pick")),
            sim_context=game_sim_context,
            quote=row.get("quote"),
            price_improvement_pct=row.get("price_improvement_pct"),
        )
    if not candidates:
        game_markets = game.get("gameMarkets") if isinstance(game.get("gameMarkets"), dict) else {}
        total_market = game_markets.get("total") if isinstance(game_markets.get("total"), dict) else {}
        total_line = total_market.get("line") if isinstance(total_market.get("line"), (int, float, str)) else None
        total_pick = _first_present_text(total_market.get("pick"), total_market.get("selection"), total_market.get("side"))
        if total_line is not None:
            _append_game_bet_candidate(
                candidates,
                sport=sport,
                game=game,
                market="Total",
                pick=total_pick or f"Total { _prop_metric_text(total_line) or '-' }",
                line=total_line,
                projected=total_line,
                detail=_first_present_text(total_market.get("reason"), game.get("summary"), game.get("detail")),
                fallback_epoch=fallback_epoch,
                live_odds_game_ids=live_odds_game_ids,
            )
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    if betting:
        # Moneyline has no separate "projected line" -- the win probability
        # itself IS the projection, same reasoning as MLB's equivalent fix in
        # _mlb_game_market_recommendation_rows. Neither Moneyline call passed
        # projected= at all before, so every betting-sourced Moneyline
        # candidate (any sport whose betting dict lacks its own richer
        # "projected"-shaped fields) showed "-" on the board regardless of
        # how real p_away_win/p_home_win were.
        away_win_prob = betting.get("p_away_win")
        home_win_prob = betting.get("p_home_win")
        _append_game_bet_candidate(candidates, sport=sport, game=game, market="Moneyline", pick=f"Away ML", odds=betting.get("away_ml"), edge=betting.get("away_ml_ev"), confidence=away_win_prob, projected=f"{away_win_prob * 100.0:.1f}%" if isinstance(away_win_prob, (int, float)) else None, detail=game.get("summary"), fallback_epoch=fallback_epoch, live_odds_game_ids=live_odds_game_ids, team=_game_team_label(game, "away"), sim_context=game_sim_context)
        _append_game_bet_candidate(candidates, sport=sport, game=game, market="Moneyline", pick=f"Home ML", odds=betting.get("home_ml"), edge=betting.get("home_ml_ev"), confidence=home_win_prob, projected=f"{home_win_prob * 100.0:.1f}%" if isinstance(home_win_prob, (int, float)) else None, detail=game.get("summary"), fallback_epoch=fallback_epoch, live_odds_game_ids=live_odds_game_ids, team=_game_team_label(game, "home"), sim_context=game_sim_context)
        if betting.get("total") is not None:
            # projected_total (wnba/cards.py's _source_betting, and any other
            # sport's betting-dict builder that adopts the same field name) is
            # the real model total -- prefer it over the older, generic
            # projected/projection/model/mean scan, which nothing in this
            # repo's betting-dict builders actually populates.
            total_projected = _first_present_text(betting.get("projected_total"), betting.get("projected"), betting.get("projection"), betting.get("model"), betting.get("mean"))
            total_odds = _first_present_text(betting.get("odds"), betting.get("price"), betting.get("american_odds"))
            if _safe_text(sport.get("slug"), "").lower() != "wnba" or (total_projected and total_odds):
                _append_game_bet_candidate(candidates, sport=sport, game=game, market="Total", pick=f"Over { _prop_metric_text(betting.get('total')) or '-' }", line=betting.get("total"), odds=total_odds, projected=total_projected or _prop_metric_text(betting.get("total")), edge=betting.get("over_ev"), confidence=betting.get("p_total_over"), detail=game.get("summary"), fallback_epoch=fallback_epoch, live_odds_game_ids=live_odds_game_ids, sim_context=game_sim_context)
                _append_game_bet_candidate(candidates, sport=sport, game=game, market="Total", pick=f"Under { _prop_metric_text(betting.get('total')) or '-' }", line=betting.get("total"), odds=total_odds, projected=total_projected or _prop_metric_text(betting.get("total")), edge=betting.get("under_ev"), confidence=betting.get("p_total_under"), detail=game.get("summary"), fallback_epoch=fallback_epoch, live_odds_game_ids=live_odds_game_ids, sim_context=game_sim_context)
        if betting.get("home_puck_line") is not None or betting.get("away_puck_line") is not None:
            home_spread_projected = _numeric_value(betting.get("home_spread"))
            away_spread_projected = -home_spread_projected if home_spread_projected is not None else None
            _append_game_bet_candidate(candidates, sport=sport, game=game, market="Spread", pick=f"Away { _prop_metric_text(betting.get('away_puck_line')) or '' }".strip(), line=betting.get("away_puck_line"), edge=betting.get("away_spread_ev"), confidence=betting.get("p_away_cover"), projected=away_spread_projected, detail=game.get("summary"), fallback_epoch=fallback_epoch, live_odds_game_ids=live_odds_game_ids, team=_game_team_label(game, "away"), sim_context=game_sim_context)
            _append_game_bet_candidate(candidates, sport=sport, game=game, market="Spread", pick=f"Home { _prop_metric_text(betting.get('home_puck_line')) or '' }".strip(), line=betting.get("home_puck_line"), edge=betting.get("home_spread_ev"), confidence=betting.get("p_home_cover"), projected=home_spread_projected, detail=game.get("summary"), fallback_epoch=fallback_epoch, live_odds_game_ids=live_odds_game_ids, team=_game_team_label(game, "home"), sim_context=game_sim_context)
    top_rows = game.get("shared_top_play_rows") if isinstance(game.get("shared_top_play_rows"), list) else []
    for row in top_rows:
        if not isinstance(row, dict):
            continue
        name = _safe_text(row.get("name"), "-")
        if name == "-":
            continue
        edge_match = re.search(r"([+-]?\d+(?:\.\d+)?)%", name)
        odds_match = re.search(r"at\s+([+-]?\d+(?:\.\d+)?)", name, re.IGNORECASE)
        # #77/#68. shared_top_play_rows is a DISPLAY panel, and only some of
        # its rows are bets. This loop scrapes a price and an edge out of the
        # row's prose, and when it finds neither it still emitted a candidate
        # -- so narrative rows became picks. Confirmed against production
        # 2026-07-26 by running this function over /soccer/mls/api/cards:
        # every one of the 32 MLS game candidates came from here, with picks
        # reading "Projected score: New England Revolution 1.4 - CF Montreal
        # 2.1", "Margin: 0.80 (home perspective)", "Shots: ... 10.1 | ... 14.8"
        # and, literally, "Simulations: 400".
        #
        # Those 32 are currently pruned, but only by accident: they carry
        # live_projection "0" (the combined score of a scoreless live game),
        # and classify_candidate's presence test is truthiness-based so 0 reads
        # as absent. Fixing that test -- which is a real bug, see
        # _classify_candidate_with_reason -- would publish all of this as live
        # picks. #77 fixed the placeholder half of exactly this and left the
        # narrative half live.
        #
        # There is nothing structural to test: _build_top_play_rows
        # ([game_board_contract.py](../features/shared/game_board_contract.py))
        # builds each row as {heading: panel title, name: panel item text,
        # detail: panel body} out of a display panel's free-text items -- no
        # price, no line, no market, unlike _build_prop_rows right below it,
        # which carries pick/market/line/odds/confidence/projected. So every
        # candidate from here is scraped, and the only honest test is whether
        # the text describes a wager at all.
        #
        # A wager needs a SIDE. MLB's panels read "OVER Brooks Lee" /
        # "UNDER Gerrit Cole" / "OVER 8.5" and are real (see the 2026-07-23
        # tests below); MLS's read "Projected score: ...", "Margin: 0.80 (home
        # perspective)", "Shots: ... 10.1 | ... 14.8" and "Simulations: 400",
        # and are not. A scraped price or edge counts too, for moneyline-style
        # rows that name a price instead of a side.
        #
        # Deliberately a side/price/edge test rather than a prose blocklist:
        # the same "match the copy and it breaks on a reword" trap #77 called
        # out applies here.
        if odds_match is None and edge_match is None and not re.search(r"\b(?:over|under)\b", name, re.IGNORECASE):
            continue
        _append_game_bet_candidate(
            candidates,
            sport=sport,
            game=game,
            market=_safe_text(row.get("heading"), _market_label_from_pick_text(name)),
            pick=name,
            odds=odds_match.group(1) if odds_match else None,
            edge=edge_match.group(1) if edge_match else None,
            detail=row.get("detail"),
            fallback_epoch=fallback_epoch,
            live_odds_game_ids=live_odds_game_ids,
            team=_team_for_side_hint(game, row.get("team_side") or row.get("side") or name),
        )
    lenses = game.get("gameLens") if isinstance(game.get("gameLens"), list) else []
    for lens in lenses:
        if not isinstance(lens, dict) or bool(lens.get("closed")):
            continue
        lens_label = _safe_text(lens.get("label"), "Live")
        markets = lens.get("markets") if isinstance(lens.get("markets"), dict) else {}
        # The segment's real LIVE re-sim projection (total runs / home
        # margin) lives as a sibling of "markets", not inside any individual
        # market dict -- see mlb/live_lens.py's _live_lens_segments_from_card,
        # which sets segment["projection"] = {"total": ..., "homeMargin": ...}
        # alongside segment["markets"]. This is genuinely live/current-segment
        # data, never a true pregame value, so it feeds live_projection=
        # below (fallback_projected), not projected=.
        segment_projection = lens.get("projection") if isinstance(lens.get("projection"), dict) else {}
        for market_key, market_label in [("moneyline", "Moneyline"), ("spread", "Spread"), ("total", "Total")]:
            market = markets.get(market_key) if isinstance(markets.get(market_key), dict) else {}
            pick = _first_present_text(market.get("pick"), market.get("selection"))
            if not pick:
                continue
            fallback_projected = (
                segment_projection.get("total")
                if market_key == "total"
                else segment_projection.get("homeMargin")
                if market_key == "spread"
                else f"{market.get('p_win') * 100.0:.1f}%" if isinstance(market.get("p_win"), (int, float)) else None
            )
            # Everything that used to feed "projected" here (the per-market
            # override chain AND fallback_projected/segment_projection) is
            # a genuinely PREGAME-shaped explicit override on `market` itself
            # (projected/projection/model/mean, e.g. a market builder that
            # sets both this AND its own live_projection as siblings) still
            # wins for `projected=` -- only when the market carries none of
            # those does this fall back to cross-referencing the plain
            # betting-dict candidate for the same market+side (the only
            # other legitimate source of a true pregame value). The segment-
            # level fallback (fallback_projected, derived from
            # segment_projection -- always live/current-segment data, never
            # a pregame value on its own) now feeds `live_projection=`
            # instead, as its OWN last resort after any explicit
            # live-projection-shaped key on `market`.
            _append_game_bet_candidate(
                candidates,
                sport=sport,
                game=game,
                market=f"{lens_label} {market_label}",
                pick=pick,
                line=market.get("line") if market_key == "total" else market.get("homeLine"),
                odds=_first_present_text(market.get("odds"), market.get("price")),
                edge=market.get("edge"),
                confidence=market.get("p_win"),
                projected=(
                    market.get("projected") if market.get("projected") is not None
                    else market.get("projection") if market.get("projection") is not None
                    else market.get("model") if market.get("model") is not None
                    else market.get("mean") if market.get("mean") is not None
                    else _gamelens_matching_pregame_value(candidates, market_family=market_label, pick_text=pick)
                ),
                live_projection=(
                    market.get("live_projection") if market.get("live_projection") is not None
                    else market.get("liveProjection") if market.get("liveProjection") is not None
                    else market.get("live_proj") if market.get("live_proj") is not None
                    else market.get("projected_live") if market.get("projected_live") is not None
                    else fallback_projected
                ),
                actual=_gamelens_segment_actual_value(lens, market_key=market_key, pick_text=pick),
                detail=game.get("summary"),
                fallback_epoch=fallback_epoch,
                live_odds_game_ids=live_odds_game_ids,
                team=_team_for_side_hint(game, market.get("selection") or pick) if market_key != "total" else None,
            )
    if _safe_text(sport.get("slug"), "").lower() == "mlb":
        try:
            from syndicate.features.mlb.cards import _mlb_headshot_url
        except Exception:
            _mlb_headshot_url = lambda _pid: None  # noqa: E731 - safe no-op fallback
        markets = game.get("markets") if isinstance(game.get("markets"), dict) else {}
        for prop_key, market_prefix, name_key in [
            ("pitcherProps", "Pitcher", "pitcher_name"),
            ("extraPitcherProps", "Pitcher", "pitcher_name"),
            ("hitterProps", "Hitter", "player_name"),
            ("extraHitterProps", "Hitter", "player_name"),
        ]:
            prop_rows = markets.get(prop_key) if isinstance(markets.get(prop_key), list) else []
            for prop in prop_rows:
                if not isinstance(prop, dict):
                    continue
                player_name = _safe_text(prop.get(name_key) or prop.get("player_name") or prop.get("pitcher_name") or prop.get("name"), "")
                if not player_name:
                    continue
                market_label = _display_prop_market_label(prop.get("market_label") or prop.get("prop") or prop.get("prop_market_key") or prop.get("market"))
                selection = _safe_text(prop.get("selection"), "").upper()
                pick = f"{selection} {player_name}".strip() if selection else player_name
                detail = _first_present_text(prop.get("reason_summary"), prop.get("summary"), prop.get("explanation_diagnostic"), game.get("summary"))
                confidence = prop.get("model_prob")
                if confidence is None:
                    confidence = prop.get("selected_side_model_prob")
                    if confidence is None and selection:
                        confidence = prop.get("model_prob_over") if selection == "OVER" else prop.get("model_prob_under")
                # Prefer the row's stat-specific sim mean (e.g. outs_mean) --
                # the generic keys below are absent on these recommendation
                # prop rows, so without this the projection column stays blank.
                projected = _mlb_prop_projected_value(prop)
                if projected is None:
                    projected = _first_present_text(prop.get("projection"), prop.get("mean"), prop.get("modelMean"), prop.get("sim_mean"), prop.get("projected"), prop.get("baseline"))
                live_projection = _first_present_text(prop.get("live_projection"), prop.get("liveProjection"), prop.get("live_proj"), prop.get("projected_live"))
                prop_player_id = _mlb_prop_player_id(prop)
                _append_game_bet_candidate(
                    candidates,
                    sport=sport,
                    game=game,
                    market=f"{market_prefix} {market_label}".strip(),
                    pick=pick,
                    line=prop.get("market_line"),
                    odds=_first_present_text(prop.get("odds"), prop.get("price")),
                    edge=prop.get("edge"),
                    confidence=confidence,
                    projected=projected,
                    live_projection=live_projection,
                    detail=detail,
                    fallback_epoch=fallback_epoch,
                    live_odds_game_ids=live_odds_game_ids,
                    team=_team_for_side_hint(game, prop.get("team_side") or prop.get("teamSide")),
                    player_id=prop_player_id,
                    headshot_url=_mlb_headshot_url(prop_player_id) if prop_player_id else None,
                )
    # #219: enrich the ASSEMBLED list, not just the game_market_recommendations
    # rows. This function builds candidates in several loops (gameLens, the
    # plain betting dict, shared_top_play_rows, the per-game prop loop) and only
    # the first was enriched -- measured live: 3-7 of 46 MLB candidates carried
    # a quote, every one of them Moneyline/Total, because the player props come
    # from the other loops. Before the sort, so best-price ev_pct can influence
    # ordering rather than arriving after it.
    try:
        from syndicate.features.shared.quote_enrichment import enrich_candidate_rows

        enrich_candidate_rows(game, candidates, sport_slug=str(sport.get("slug") or "").lower())
    except Exception:
        # A board without price context is degraded; a board that 500s because
        # the odds log was mid-write is an outage.
        pass
    try:
        from syndicate.features.shared import opportunity_contract_metrics

        opportunity_contract_metrics.record_rows(
            candidates, sport=sport.get("slug"), lane="game_candidate",
            date_str=game.get("gameDate") or game.get("officialDate") or game.get("game_date"),
        )
    except Exception:
        pass
    filtered = [row for row in candidates if row.get("edge") not in {"-", None} or row.get("confidence") not in {"-", None}]
    return sorted(filtered or candidates, key=lambda row: row.get("score", 0.0), reverse=True)


def _dashboard_prop_count(sport: dict[str, Any]) -> int:
    home_rails = sport.get("home_rails") if isinstance(sport.get("home_rails"), dict) else {}
    pregame_items = (home_rails.get("pregame") or {}).get("items") if isinstance(home_rails.get("pregame"), dict) else []
    live_items = (home_rails.get("live") or {}).get("items") if isinstance(home_rails.get("live"), dict) else []
    rails_count = 0
    if isinstance(pregame_items, list):
        rails_count += len(pregame_items)
    if isinstance(live_items, list):
        rails_count += len(live_items)
    props_bar = sport.get("props_bar") if isinstance(sport.get("props_bar"), dict) else {}
    base_count = len(props_bar.get("items") or []) if isinstance(props_bar.get("items"), list) else 0
    if rails_count:
        return max(base_count, rails_count)
    if str(sport.get("slug") or "").strip().lower() != "mlb":
        return base_count
    mlb_home = sport.get("mlb_home") if isinstance(sport.get("mlb_home"), dict) else {}
    counts = [
        base_count,
        len(mlb_home.get("live_props_items") or []) if isinstance(mlb_home.get("live_props_items"), list) else 0,
        len(mlb_home.get("pregame_props_items") or []) if isinstance(mlb_home.get("pregame_props_items"), list) else 0,
        len(mlb_home.get("hr_targets_items") or []) if isinstance(mlb_home.get("hr_targets_items"), list) else 0,
    ]
    return max(counts)


def _build_game_watch_row(sport: dict[str, Any], item: dict[str, Any], *, live_odds_game_ids: set[str] | None = None) -> dict[str, Any]:
    status_badge = _safe_text(item.get("status_badge"), "Tracked")
    detail = _safe_text(item.get("detail"), "Board update pending")
    signals = [str(value).strip() for value in (item.get("signals") or []) if str(value).strip()]
    chips = [str(value).strip() for value in (item.get("market_chips") or []) if str(value).strip()]
    primary_signal = signals[0] if signals else (chips[0] if chips else "No market signal surfaced")
    confidence = _pct_number(primary_signal)
    live_flag = _live_odds_backed_live_flag(_game_identifier(item), live_odds_game_ids, _is_liveish(status_badge, detail))
    return {
        "game_id": _game_identifier(item),
        "gamePk": item.get("gamePk") or item.get("game_pk") or item.get("game_id"),
        "event_id": item.get("event_id"),
        "sport": _safe_text(sport.get("name"), str(sport.get("slug") or "").upper()),
        "sport_slug": _safe_text(sport.get("slug"), "sport").lower(),
        "matchup": _safe_text(item.get("matchup"), "Game"),
        "status": status_badge,
        "detail": detail,
        "signal": primary_signal,
        "summary": _safe_text(item.get("summary"), "No board read surfaced."),
        "href": str(item.get("href") or sport.get("hub_href") or "").strip() or None,
        "href_label": _safe_text(item.get("href_label"), "Open board"),
        "is_live": live_flag,
        "score": (80.0 if live_flag else 25.0) + float(len(signals) * 8 + len(chips) * 4) + float(confidence or 0.0),
    }


def _build_prop_dashboard_row(sport: dict[str, Any], item: dict[str, Any], *, default_surface: str, live_odds_game_ids: set[str] | None = None) -> dict[str, Any]:
    heading = _safe_text(item.get("heading"), default_surface)
    detail = _safe_text(item.get("detail"), "No prop summary available.")
    confidence = _safe_text(item.get("confidence") or item.get("value"), "-")
    edge = _safe_text(item.get("edge"), "-")
    explicit_live = item.get("is_live")
    if isinstance(explicit_live, bool):
        live_flag = explicit_live
    else:
        live_tokens = [
            heading.lower(),
            str(default_surface or "").strip().lower(),
            detail.lower(),
        ]
        live_flag = any(
            token
            for token in live_tokens
            if any(marker in token for marker in ["live props", "prop live", "live lens", "in-game", "live audit"])
        )
    live_flag = _live_odds_backed_live_flag(_game_identifier(item), live_odds_game_ids, live_flag)
    confidence_value = _pct_number(confidence)
    edge_value = _pct_number(edge)
    score = float((confidence_value or 0.0) + (edge_value or 0.0) * 1.5 + (55.0 if live_flag else 20.0))
    outcome_state = _safe_text(item.get("outcome_state"), None)
    if not outcome_state:
        actual_value = _numeric_value(item.get("actual"))
        line_value = _numeric_value(item.get("line") or item.get("market_line"))
        selection = str(item.get("pick") or item.get("selection") or "").strip().lower()
        if actual_value is not None and line_value is not None:
            if selection == "under":
                outcome_state = "hit" if float(actual_value) < float(line_value) else "miss"
            elif selection == "over":
                outcome_state = "hit" if float(actual_value) > float(line_value) else "miss"
            elif str(item.get("heading") or "").strip().lower() == "hr targets":
                outcome_state = "hit" if float(actual_value) >= 1.0 else "miss"
    outcome_label = _safe_text(item.get("outcome_label"), None)
    if not outcome_label and outcome_state:
        outcome_label = "Hit" if outcome_state == "hit" else "Miss" if outcome_state == "miss" else None
    live_total = _prop_metric_text(item.get("live_total"))
    if not live_total:
        live_total = _score_value(item.get("live_total_line") or item.get("live_line_total") or item.get("total_goals"))
    return {
        "game_id": _game_identifier(item),
        "gamePk": item.get("gamePk") or item.get("game_pk") or item.get("game_id"),
        "event_id": item.get("event_id"),
        # Traced live 2026-08-05: this function reconstructs a brand new
        # dict from `item` rather than passing it through, and used to drop
        # commence_time entirely -- confirmed via a persisted diagnostic
        # that _finalize_home_prop_rows's own commence_time fix (30a7067e)
        # WAS setting item["commence_time"] correctly (matched_game found by
        # game_pk, scheduled_start_utc populated), yet the served board
        # still showed the board's context date. resolve_candidate_game_date
        # (intelligence_contracts.py) checks commence_time/start_time_utc/
        # game_time_utc/game_date in that order; none of those existed on
        # the dict THIS function actually returns, so it always fell
        # through to the fallback. The upstream fix was correct and
        # necessary but not sufficient without this.
        "commence_time": item.get("commence_time"),
        "sport": _safe_text(sport.get("name"), str(sport.get("slug") or "").upper()),
        "sport_slug": _safe_text(sport.get("slug"), "sport").lower(),
        "surface": heading,
        "name": _safe_text(item.get("name"), "Prop"),
        # IDENTITY, not display. This function reconstructs a new dict rather
        # than passing `item` through, and dropped these -- exactly the failure
        # the commence_time comment above records, one field-set later.
        # Verified live 2026-08-06: MLB rail items carry a correct
        # player_name ("Ryan Johnson") and player_id, and every row this
        # function produced had player_name: null, which is why 0 of 14
        # top_props rows could be joined to a price. `name` is the display
        # label ("Ryan Johnson Walks Allowed") and is not a substitute.
        "player_name": _safe_text(item.get("player_name") or item.get("player") or item.get("entity"), None),
        "player_id": item.get("player_id"),
        # The canonical, sport-agnostic market key where the source has one
        # (MLB prop rows carry prop="batter_total_bases"). `market` below is a
        # display string ("Walks Allowed") and must never be used as a key.
        "market_key": _safe_text(item.get("market_key") or item.get("prop") or item.get("prop_market_key") or item.get("stat"), None),
        "headshot_url": _safe_text(item.get("headshot_url") or item.get("photo"), None),
        "market": _safe_text(item.get("market"), heading),
        "pick": _safe_text(item.get("pick"), detail.split("|")[0].strip() if detail else heading),
        "matchup": _safe_text(item.get("matchup"), "-"),
        "actual": _prop_metric_text(item.get("actual")) or "-",
        "projected": _prop_metric_text(item.get("projected")) or "-",
        "live_projection": _prop_metric_text(item.get("live_projection")) or "-",
        "line": _prop_metric_text(item.get("line")) or "-",
        "odds": _prop_metric_text(item.get("odds")) or "-",
        "edge": edge,
        "confidence": confidence,
        "detail": detail,
        "href": str(item.get("href") or sport.get("hub_href") or "").strip() or None,
        "is_live": live_flag,
        "game_state": _safe_text(item.get("game_state"), None),
        "outcome_state": outcome_state,
        "outcome_label": outcome_label,
        "live_total": live_total,
        "score": score,
    }


def _mlb_top_prop_lane_counts(context_label: str) -> dict[str, int]:
    summary = load_json_or_gz_file(daily_top_props_path(context_label))
    if not isinstance(summary, dict):
        return {"pitcher_count": 0, "hitter_count": 0}
    pitcher_rows = _mlb_top_prop_rows_from_group(
        summary,
        group_key="pitcher",
        fallback_href=f"/mlb/pitcher-top-props?date={context_label}",
        limit=999,
    )
    hitter_rows = _mlb_top_prop_rows_from_group(
        summary,
        group_key="hitter",
        fallback_href=f"/mlb/hitter-top-props?date={context_label}",
        limit=999,
    )
    return {"pitcher_count": len(pitcher_rows), "hitter_count": len(hitter_rows)}


def _sport_availability_reason(
    sport: dict[str, Any],
    *,
    active_today: bool,
    games_count: int,
    props_count: int,
    mlb_top_prop_counts: dict[str, int] | None = None,
) -> dict[str, str | None]:
    slug = _safe_text(sport.get("slug"), "sport").lower()
    sport_name = _safe_text(sport.get("name"), slug.upper())
    counts = mlb_top_prop_counts or {}
    pitcher_count = int(counts.get("pitcher_count") or 0)
    hitter_count = int(counts.get("hitter_count") or 0)

    game_reason: str | None = None
    props_reason: str | None = None

    if games_count <= 0:
        if slug == "wnba" and active_today:
            game_reason = "WNBA live-state feed returned no event IDs or game rows for this slate."
        elif slug == "mlb" and active_today:
            game_reason = "MLB game rows were not surfaced from the live board snapshot for this slate."
        elif active_today:
            game_reason = f"{sport_name} game rows were not surfaced from the current board snapshot."
        else:
            game_reason = f"{sport_name} is not active for the selected slate, so game rows are hidden."

    if props_count <= 0:
        if slug == "mlb" and active_today:
            if pitcher_count and not hitter_count:
                props_reason = "MLB pitcher rows surfaced, but the hitter top-props lane was empty in the current daily artifact."
            elif hitter_count and not pitcher_count:
                props_reason = "MLB hitter rows surfaced, but the pitcher top-props lane was empty in the current daily artifact."
            elif pitcher_count or hitter_count:
                props_reason = "MLB top-props rows surfaced, but the combined home board did not produce any prop rows for display."
            else:
                props_reason = "MLB top-props artifact returned no pitcher or hitter rows for this slate."
        elif slug == "wnba" and active_today:
            props_reason = "WNBA prop rows were not surfaced from the betting-card payload for this slate."
        elif active_today:
            props_reason = f"{sport_name} prop rows were not surfaced from the current board snapshot."
        else:
            props_reason = f"{sport_name} prop rows are hidden until the slate is active."
    elif slug == "mlb" and active_today:
        if pitcher_count and not hitter_count:
            props_reason = "MLB pitcher rows surfaced; hitter top-props rows were not present in the daily top-props artifact."
        elif hitter_count and not pitcher_count:
            props_reason = "MLB hitter rows surfaced; pitcher top-props rows were not present in the daily top-props artifact."
        elif pitcher_count and hitter_count:
            props_reason = "MLB pitcher and hitter top-props rows are both present in the daily artifact."

    availability_reason = props_reason or game_reason
    return {
        "availability_reason": availability_reason,
        "game_availability_reason": game_reason,
        "props_availability_reason": props_reason,
    }


def _build_home_dashboard(overview: list[dict[str, Any]], *, selected_date: str, polled_at: float) -> dict[str, Any]:
    live_watch: list[dict[str, Any]] = []
    game_bets: list[dict[str, Any]] = []
    prop_rows: list[dict[str, Any]] = []
    sport_summaries: list[dict[str, Any]] = []
    for sport in overview:
        if not isinstance(sport, dict):
            continue
        game_bar = sport.get("game_bar") if isinstance(sport.get("game_bar"), dict) else {}
        props_bar = sport.get("props_bar") if isinstance(sport.get("props_bar"), dict) else {}
        home_rails = sport.get("home_rails") if isinstance(sport.get("home_rails"), dict) else {}
        game_items = game_bar.get("items") if isinstance(game_bar.get("items"), list) else []
        dashboard_games = sport.get("dashboard_games") if isinstance(sport.get("dashboard_games"), list) else []
        prop_items = []
        if isinstance((home_rails.get("pregame") or {}).get("items"), list):
            prop_items.extend((home_rails.get("pregame") or {}).get("items") or [])
        if isinstance((home_rails.get("live") or {}).get("items"), list):
            prop_items.extend((home_rails.get("live") or {}).get("items") or [])
        if not prop_items:
            prop_items = props_bar.get("items") if isinstance(props_bar.get("items"), list) else []
        for item in game_items:
            if isinstance(item, dict):
                live_watch.append(_build_game_watch_row(sport, item))
        for game in dashboard_games:
            if isinstance(game, dict):
                game_bets.extend(_game_bet_candidates_from_game(sport, game, fallback_epoch=polled_at)[:3])
        for item in prop_items:
            if isinstance(item, dict):
                prop_rows.append(_build_prop_dashboard_row(sport, item, default_surface=_safe_text(props_bar.get("title"), "Props")))
        if not home_rails and str(sport.get("slug") or "").strip().lower() == "mlb":
            mlb_home = sport.get("mlb_home") if isinstance(sport.get("mlb_home"), dict) else {}
            for item in mlb_home.get("live_props_items") if isinstance(mlb_home.get("live_props_items"), list) else []:
                if isinstance(item, dict):
                    prop_rows.append(_build_prop_dashboard_row(sport, item, default_surface="Live props"))
            for item in mlb_home.get("pregame_props_items") if isinstance(mlb_home.get("pregame_props_items"), list) else []:
                if isinstance(item, dict):
                    prop_rows.append(_build_prop_dashboard_row(sport, item, default_surface="Pregame props"))
            for item in mlb_home.get("hr_targets_items") if isinstance(mlb_home.get("hr_targets_items"), list) else []:
                if isinstance(item, dict):
                    prop_rows.append(_build_prop_dashboard_row(sport, item, default_surface="HR Top 10"))
        sport_slug = _safe_text(sport.get("slug"), "").lower()
        try:
            from syndicate.features.shared import opportunity_contract_metrics

            opportunity_contract_metrics.record_rows(
                [row for row in prop_rows if row.get("sport_slug") == sport_slug],
                sport=sport_slug, lane="prop_dashboard_row", date_str=selected_date,
            )
        except Exception:
            pass
        # #220: props are a SEPARATE lane from game bets -- _build_prop_dashboard_row
        # over home_rails/props_bar items, which never passes through
        # _game_bet_candidates_from_game where enrichment lives. Traced live:
        # top_game_bets had 5 of 12 quotes, top_props 0 of 14. These rows carry
        # no game dict, but they do carry player_name, which is a full identity
        # signal on its own.
        try:
            from syndicate.features.shared.quote_enrichment import enrich_prop_rows

            enrich_prop_rows(prop_rows, date_str=str(selected_date)[:10])
        except Exception:
            pass
        mlb_top_prop_counts = _mlb_top_prop_lane_counts(_safe_text(sport.get("context_label"), selected_date)) if sport_slug == "mlb" else None
        availability_reasons = _sport_availability_reason(
            sport,
            active_today=bool(sport.get("active_today")),
            games_count=len(game_items),
            props_count=_dashboard_prop_count(sport),
            mlb_top_prop_counts=mlb_top_prop_counts,
        )
        summary_signals = next((row.get("signal") for row in live_watch if row.get("sport_slug") == sport_slug), "-")
        top_game_bet = next((row for row in game_bets if row.get("sport_slug") == sport_slug), None)
        top_prop = next((row for row in prop_rows if row.get("sport_slug") == _safe_text(sport.get("slug"), "").lower()), None)
        sport_summaries.append(
            {
                "sport": _safe_text(sport.get("name"), str(sport.get("slug") or "").upper()),
                "sport_slug": _safe_text(sport.get("slug"), "sport").lower(),
                "context": _safe_text(sport.get("context_label"), selected_date),
                "status": _safe_text(sport.get("status"), "Tracked"),
                "is_live": bool(sport.get("active_today")),
                "games": len(game_items),
                "props": _dashboard_prop_count(sport),
                "best_signal": summary_signals,
                "top_game_bet": top_game_bet.get("pick") if isinstance(top_game_bet, dict) else "-",
                "top_prop": top_prop.get("name") if isinstance(top_prop, dict) else "-",
                "hub_href": str(sport.get("hub_href") or sport.get("primary_href") or "").strip() or None,
                "availability_reason": availability_reasons.get("availability_reason"),
                "game_availability_reason": availability_reasons.get("game_availability_reason"),
                "props_availability_reason": availability_reasons.get("props_availability_reason"),
            }
        )

    live_watch = sorted(live_watch, key=lambda row: row.get("score", 0.0), reverse=True)
    game_bets = sorted(game_bets, key=lambda row: row.get("score", 0.0), reverse=True)
    prop_rows = sorted(prop_rows, key=lambda row: row.get("score", 0.0), reverse=True)
    live_props = [row for row in prop_rows if bool(row.get("is_live"))]
    live_sports = sum(1 for sport in overview if bool((sport or {}).get("active_today")))
    # Command-bar "top edges" rail: game bets and props both already carry a
    # comparable edge/confidence text shape (_append_game_bet_candidate and
    # _build_prop_dashboard_row), so they can be merged and ranked by edge
    # magnitude directly instead of building a third parallel candidate list.
    # Also merged in: the /intelligence board's own cached candidates
    # (_board_candidate_rows) -- home.py's per-sport artifact scan above is
    # meaningfully narrower than the board's real candidate-generation path
    # (it can find zero game bets/props on slates where the board finds
    # several), so relying on it alone understates what's actually on offer.
    top_edges = sorted(
        [*game_bets, *prop_rows, *_board_candidate_rows(selected_date, limit=16)],
        key=lambda row: _pct_number(row.get("edge")) or 0.0,
        reverse=True,
    )[:12]
    summary_cards = [
        {"label": "Board date", "value": selected_date, "meta": f"Polled {_format_home_timestamp(polled_at)}"},
        {"label": "Live sports", "value": str(live_sports), "meta": f"{len(live_watch)} game reads surfaced"},
        {"label": "Game bets", "value": str(len(game_bets)), "meta": "Structured sides and totals surfaced"},
        {"label": "Props surfaced", "value": str(len(prop_rows)), "meta": f"{len(live_props)} live props in focus"},
        {"label": "Sports tracked", "value": str(len(overview)), "meta": "Cross-sport board"},
    ]
    # One flush per dashboard build -- the lanes above accumulate in-process, so
    # a lane that runs per game does not write per game.
    try:
        from syndicate.features.shared import opportunity_contract_metrics

        opportunity_contract_metrics.flush()
    except Exception:
        pass
    return {
        "summary_cards": summary_cards,
        "top_game_bets": game_bets[:12],
        "live_watch": live_watch[:10],
        "top_props": prop_rows[:14],
        "top_edges": top_edges,
        "sport_summaries": sport_summaries,
    }


def _build_home_command_center_contract(
    dashboard: dict[str, Any],
    *,
    selected_date: str,
    polled_at: float,
) -> dict[str, Any]:
    summary_cards = dashboard.get("summary_cards") if isinstance(dashboard.get("summary_cards"), list) else []
    live_watch = dashboard.get("live_watch") if isinstance(dashboard.get("live_watch"), list) else []
    top_props = dashboard.get("top_props") if isinstance(dashboard.get("top_props"), list) else []
    top_game_bets = dashboard.get("top_game_bets") if isinstance(dashboard.get("top_game_bets"), list) else []
    sport_summaries = dashboard.get("sport_summaries") if isinstance(dashboard.get("sport_summaries"), list) else []
    return {
        "schema": "home_command_center_v1",
        "headline": "Syndicate main page",
        "lede": "One hub for the day across all sports, with games, live game updates, pregame props, live props, and the highest-value actions surfaced first.",
        "selected_date": selected_date,
        "polled_at": polled_at,
        "summary_cards": summary_cards,
        "live_watch": live_watch,
        "top_props": top_props,
        "top_game_bets": top_game_bets,
        "sport_summaries": sport_summaries,
        "shortcuts": [
            {"label": "Live games", "href": "#home-live-lane"},
            {"label": "Pregame props", "href": "#home-pregame-lane"},
            {"label": "Game bets", "href": "#home-game-bets-lane"},
            {"label": "All sports", "href": "#syndicate-home-sport-stack"},
        ],
    }


def _parse_timestamp_epoch(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return 0.0


def _mlb_prop_state_rank(game: dict[str, Any], prop: dict[str, Any]) -> int:
    status = game.get("status") if isinstance(game.get("status"), dict) else {}
    detail_text = " ".join(
        str(value or "").strip().lower()
        for value in [status.get("detailed"), status.get("abstract"), game.get("detail"), game.get("summary"), prop.get("status")]
        if str(value or "").strip()
    )
    if any(token in detail_text for token in ("final", "game over", "completed")):
        return 0
    if any(token in detail_text for token in ("delayed", "suspended", "challenge", "review")):
        return 1
    if any(token in detail_text for token in ("live", "in progress", "top ", "bot ")):
        return 3
    return 2


def _fetch_mlb_feed_live(game_pk: int) -> dict[str, Any] | None:
    try:
        with urlopen(f"https://statsapi.mlb.com/api/v1.1/game/{int(game_pk)}/feed/live", timeout=5) as response:
            if int(getattr(response, "status", 200) or 200) >= 400:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, URLError):
        return None


def _mlb_feed_live_payload(selected_date: str, game_pk: int) -> dict[str, Any] | None:
    payload = load_json_or_gz_file(raw_feed_live_path(selected_date, int(game_pk)))
    if isinstance(payload, dict):
        return payload
    if selected_date == central_today_iso():
        return _fetch_mlb_feed_live(game_pk)
    return None


def _mlb_feed_live_state(selected_date: str, game_pk: int) -> dict[str, Any] | None:
    payload = _mlb_feed_live_payload(selected_date, game_pk)
    if not isinstance(payload, dict):
        return None
    game_data = payload.get("gameData") if isinstance(payload.get("gameData"), dict) else {}
    live_data = payload.get("liveData") if isinstance(payload.get("liveData"), dict) else {}
    status = game_data.get("status") if isinstance(game_data.get("status"), dict) else {}
    linescore = live_data.get("linescore") if isinstance(live_data.get("linescore"), dict) else {}
    teams = linescore.get("teams") if isinstance(linescore.get("teams"), dict) else {}
    away_score = ((teams.get("away") or {}) if isinstance(teams.get("away"), dict) else {}).get("runs")
    home_score = ((teams.get("home") or {}) if isinstance(teams.get("home"), dict) else {}).get("runs")
    abstract = str(status.get("abstractGameState") or "").strip()
    detailed = str(status.get("detailedState") or "").strip()
    inning = linescore.get("currentInningOrdinal") or linescore.get("currentInning")
    half = str(linescore.get("inningHalf") or "").strip().lower()
    outs = linescore.get("outs")
    status_bits = [bit for bit in [detailed, f"{half.title()} {inning}".strip() if inning and half else None, f"{outs} out" if outs == 1 else f"{outs} outs" if outs not in {None, ''} else None] if bit]
    # #98/#100: was abstract.lower() == "live"/"final" alone -- MLB StatsAPI
    # reports abstractGameState "Live" during warmup, before the game has
    # actually started, so this fed a false "live" board-wide for every
    # warming-up game (confirmed real production data: BAL @ DET). Delegates
    # to the shared canonical predicate (syndicate.features.mlb.game_state),
    # which requires detailedState to agree.
    return {
        "away_pts": away_score,
        "home_pts": home_score,
        "in_progress": _mlb_status_is_live(abstract, detailed),
        "final": _mlb_status_is_final(abstract, detailed),
        "status": " | ".join(status_bits) if status_bits else detailed or abstract or None,
    }


def _mlb_feed_live_states(game_pks: list[int], selected_date: str, *, overall_timeout: float = 8.0) -> dict[int, dict[str, Any] | None]:
    # Each _mlb_feed_live_state() call can fall through to a real network
    # call (_fetch_mlb_feed_live -> statsapi.mlb.com, 5s socket timeout) when
    # no local raw-feed artifact exists yet for that game. Running them one
    # thread per game (instead of the previous sequential loop) already
    # bounds a well-behaved batch to roughly one game's worst case (~5s)
    # instead of the sum (a full 15-game slate run sequentially could total
    # 70s+ of blocking I/O in a single request -- comfortably past
    # gunicorn's 60s worker timeout in production, per render.yaml's
    # GUNICORN_TIMEOUT=60). But per-call timeouts aren't always honored by
    # the underlying socket for every failure mode (observed: some cold
    # /api/home calls still took 90s+ even after parallelizing, with no
    # single sub-step accounting for it in direct profiling -- consistent
    # with a connection that accepts but never sends, which can outlast a
    # read timeout). So this also enforces its own hard wall-clock budget:
    # whatever hasn't finished by `overall_timeout` is abandoned rather than
    # blocking the request further. shutdown(wait=False) lets those
    # straggler threads resolve (or hit their own 5s timeout) in the
    # background instead of forcing this request to wait on them -- the
    # request's latency is bounded no matter what the external API does.
    results: dict[int, dict[str, Any] | None] = {pk: None for pk in game_pks}
    if not game_pks:
        return results
    executor = ThreadPoolExecutor(max_workers=min(len(game_pks), 16))
    futures = {executor.submit(_mlb_feed_live_state, selected_date, pk): pk for pk in game_pks}
    done, _not_done = _futures_wait(futures, timeout=overall_timeout)
    for future in done:
        pk = futures[future]
        try:
            results[pk] = future.result()
        except Exception:
            results[pk] = None
    executor.shutdown(wait=False)
    return results


def _apply_mlb_live_scores(games: list[dict[str, Any]], selected_date: str) -> list[dict[str, Any]]:
    game_pks: list[int] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        try:
            game_pk = int(game.get("gamePk") or 0)
        except (TypeError, ValueError):
            continue
        if game_pk:
            game_pks.append(game_pk)
    live_states = _mlb_feed_live_states(game_pks, selected_date)

    enriched: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        game_pk = int(game.get("gamePk") or 0)
        live_state = live_states.get(game_pk) if game_pk else None
        if not live_state:
            enriched.append(game)
            continue
        updated = dict(game)
        away = dict(game.get("away") or {}) if isinstance(game.get("away"), dict) else {}
        home = dict(game.get("home") or {}) if isinstance(game.get("home"), dict) else {}
        # A live or final game always has a real (possibly 0) cumulative run
        # total per side -- MLB StatsAPI's linescore.teams.<side>.runs can
        # still come back null for one side while the other has a real
        # number (confirmed in production: one side rendered as "-" on both
        # live and final games while its opponent showed a real score). Once
        # the game state itself confirms live/final, treat a missing runs
        # value as 0 rather than leaving that side's score unset -- an
        # actually-unknown score only makes sense pregame.
        in_progress_or_final = bool(live_state.get("in_progress") or live_state.get("final"))
        away_pts = live_state.get("away_pts")
        home_pts = live_state.get("home_pts")
        if away_pts is not None:
            away["score"] = away_pts
        elif in_progress_or_final:
            away["score"] = 0
        if home_pts is not None:
            home["score"] = home_pts
        elif in_progress_or_final:
            home["score"] = 0
        updated["away"] = away
        updated["home"] = home
        status = dict(game.get("status") or {}) if isinstance(game.get("status"), dict) else {}
        status["away_score"] = away.get("score", status.get("away_score"))
        status["home_score"] = home.get("score", status.get("home_score"))
        status["is_live"] = bool(live_state.get("in_progress"))
        status["in_progress"] = bool(live_state.get("in_progress"))
        status["is_final"] = bool(live_state.get("final"))
        status["final"] = bool(live_state.get("final"))
        if live_state.get("in_progress"):
            status["abstract"] = "Live"
        elif live_state.get("final"):
            status["abstract"] = "Final"
        if live_state.get("status"):
            status["detailed"] = live_state.get("status")
        updated["status"] = status
        updated["live_state"] = live_state
        enriched.append(updated)
    return enriched


def _mlb_game_market_recommendation_rows(game: dict[str, Any]) -> list[dict[str, Any]]:
    # MLB's own cards.py builds its moneyline/totals picks under
    # game["markets"]["ml"/"totals"] (a shape private to the MLB hub page's
    # own tiles, see mlb/cards.py's _market_tiles) -- a completely different
    # shape than the game_market_recommendations list every OTHER sport's
    # cards.py emits, which is the only shape _game_bet_candidates_from_game
    # actually knows how to read. Without this translation, MLB pregame
    # Moneyline/Total candidates never reached the board at all (confirmed
    # 2026-07-23: the board's only MLB "game" candidates were in-game
    # period-lens markets like "f7 moneyline", and only for whichever single
    # game happened to be live -- every pregame MLB game showed zero).
    markets = game.get("markets") if isinstance(game.get("markets"), dict) else {}
    # #100 follow-up, 2026-07-27: model_prob/selection on markets["ml"/"totals"]
    # only exists for games the recommendation engine happened to flag --
    # confirmed in production the same night as the confidence-field fix
    # above: of 9 non-final MLB games, only 2 had a reco-engine pick, so the
    # other 7 (including all 3 genuinely pregame ones) produced zero game
    # candidates even though the sim's own predictions.full carried real,
    # non-degenerate win probabilities for every one of them. Mirrors the
    # Layer 1 market board's fix for the identical gap
    # (_mlb_market_board_rows_for_game in mlb/cards.py, whose own docstring
    # says this outright): fall back to the sim's unconditional win
    # probability/total-runs distribution when no recommendation is attached,
    # rather than leaving the game with no candidate at all. Downstream
    # scoring/tiering (not candidate existence) is where edge-worthiness
    # should be judged, per this file's own "no candidate dropped solely for
    # missing source" rule.
    from syndicate.features.mlb.cards import _dist_prob_over_line

    full_predictions = (game.get("predictions") or {}).get("full") if isinstance(game.get("predictions"), dict) else None
    full_predictions = full_predictions if isinstance(full_predictions, dict) else {}
    sim_home_prob = _numeric_value(full_predictions.get("home_win_prob"))
    sim_away_prob = _numeric_value(full_predictions.get("away_win_prob"))
    total_runs_dist = full_predictions.get("total_runs_dist")
    rows: list[dict[str, Any]] = []
    # #108 follow-up, confirmed live 2026-07-27: refresh-worker's own
    # dashboard_games carries markets["ml"] as entirely ABSENT for every MLB
    # game (not merely lacking selection/model_prob, which the block below
    # already handled) -- while predictions.full is reliably present, since
    # the sim runs on refresh-worker itself. A moneyline pick needs no book
    # line to exist (unlike totals, just below, which does), so this no
    # longer requires markets["ml"] to be a dict at all -- an empty fallback
    # lets the sim-derived branch fire purely off predictions.full. odds
    # stays None in that case, which is fine: classification accepts
    # projection OR odds, same reasoning as the HR-targets precedent (#92).
    moneyline = markets.get("ml") if isinstance(markets.get("ml"), dict) else {}
    side = str(moneyline.get("selection") or "").strip().lower()
    model_prob = moneyline.get("model_prob")
    odds = moneyline.get("odds") or moneyline.get("price")
    if side not in ("home", "away") and sim_home_prob is not None and sim_away_prob is not None:
        side = "home" if sim_home_prob >= sim_away_prob else "away"
        model_prob = sim_home_prob if side == "home" else sim_away_prob
        odds = moneyline.get("home_odds") if side == "home" else moneyline.get("away_odds")
    pick_label = {"home": "Home ML", "away": "Away ML"}.get(side)
    if pick_label:
        rows.append(
            {
                "market_label": "Moneyline",
                "display_pick": pick_label,
                "selection": side,
                "odds": odds,
                "confidence": model_prob,
                # A moneyline has no separate "projected line" concept the way
                # totals/spreads do -- the sim's own win probability IS the
                # projection. Without this, _game_bet_candidates_from_game's
                # projected= scan (row.get("projected")/"projection"/"model"/
                # "mean") always came back empty for every MLB Moneyline
                # candidate, confirmed live: board showed projected="-" for
                # every one despite real predictions.full data existing.
                "projected": f"{model_prob * 100.0:.1f}%" if isinstance(model_prob, (int, float)) else None,
                "summary": moneyline.get("reason") or moneyline.get("summary"),
            }
        )
    totals = markets.get("totals") if isinstance(markets.get("totals"), dict) else None
    if isinstance(totals, dict):
        selection = str(totals.get("selection") or "").strip().lower()
        line = totals.get("market_line") if totals.get("market_line") is not None else totals.get("line")
        model_prob = totals.get("model_prob")
        odds = totals.get("odds") or totals.get("price")
        if selection not in ("over", "under") and line is not None:
            line_value = _numeric_value(line)
            model_prob_over = _dist_prob_over_line(total_runs_dist, line_value) if line_value is not None else None
            if model_prob_over is not None:
                selection = "over" if model_prob_over >= 0.5 else "under"
                model_prob = model_prob_over if selection == "over" else 1.0 - model_prob_over
                odds = totals.get("over_odds") if selection == "over" else totals.get("under_odds")
        display_selection = selection.title()
        if display_selection and line is not None:
            # The sim's own projected total (away_runs_mean + home_runs_mean)
            # was sitting in full_predictions the whole time -- mlb/cards.py
            # already sums these two for its own "Full total" display tile --
            # but this function never carried it through, so the Total row's
            # "projected" field always fell back to "-" even though a real
            # model total existed for every game with predictions.full.
            away_runs_mean = _numeric_value(full_predictions.get("away_runs_mean"))
            home_runs_mean = _numeric_value(full_predictions.get("home_runs_mean"))
            projected_total = away_runs_mean + home_runs_mean if away_runs_mean is not None and home_runs_mean is not None else None
            rows.append(
                {
                    "market_label": "Total",
                    "display_pick": f"{display_selection} {line}".strip(),
                    "line": line,
                    "odds": odds,
                    "confidence": model_prob,
                    "projected": projected_total,
                    "summary": totals.get("reason") or totals.get("summary"),
                }
            )
    # #100/#108 follow-up, 2026-07-27: production traces show MLB's real
    # candidate-pool build never produces game-type candidates (prop-only
    # every cycle), while WNBA correctly produces both from the same
    # architecture -- and a production /mlb/api/cards fetch proves the
    # underlying markets.ml/totals + predictions.full data supports game
    # candidates right now. This print settles whether refresh-worker's own
    # dashboard_games (built from ITS OWN artifact mirror, a separate Render
    # disk from web's -- see #68's precedent for this exact class of gap)
    # actually has the same markets/predictions data web serves, or whether
    # it's missing here specifically. Bounded by construction: called once
    # per game per cycle (~12 for MLB), not in a hot loop.
    print(
        f"[home] MLB_GAME_MARKET_ROWS_DIAG game_pk={game.get('gamePk')} "
        f"has_markets_ml={isinstance(markets.get('ml'), dict)} has_markets_totals={isinstance(markets.get('totals'), dict)} "
        f"has_predictions_full={bool(full_predictions)} home_win_prob={full_predictions.get('home_win_prob')} "
        f"rows_returned={len(rows)}",
        flush=True,
    )
    return rows


def _nfl_game_market_recommendation_rows(game_id: Any, board_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # NFL never reached the cross-sport Layer 2 opportunity feed at all --
    # neither regular season nor preseason -- because nfl/cards.py and
    # nfl/preseason_cards.py never set game_market_recommendations, the
    # only shape _game_bet_candidates_from_game reads. Mirrors
    # _mlb_game_market_recommendation_rows just above: the same class of
    # gap, the same fix pattern (translate an existing, already-computed
    # data shape at read time, no new artifact, no new autorun).
    #
    # ``board_rows`` is one game's Layer 1 market-inventory rows --
    # join_odds_to_sim's output as build_nfl_market_board /
    # build_nfl_preseason_market_board produce it (nfl/cards.py), with
    # each row's "market" already remapped from the internal
    # "moneyline_home"/"spread_away"/"total" keys to the display labels
    # "Moneyline"/"Spread"/"Total" (see _NFL_MARKET_BOARD_DISPLAY_LABELS).
    # Every game-level odds row in that inventory carries market_type
    # "game" (as opposed to "prop"), a "side" ("home"/"away" for
    # moneyline/spread, "over"/"under" for total), and -- when a sim row
    # joined -- a "model_side" naming whichever side the model itself
    # favors, stamped identically on every sibling row of that market (see
    # market_inventory.join_odds_to_sim's docstring).
    rows: list[dict[str, Any]] = []
    game_id_text = str(game_id or "")
    for market_label in ("Moneyline", "Spread", "Total"):
        market_rows = [
            row
            for row in board_rows
            if isinstance(row, dict)
            and row.get("market_type") == "game"
            and row.get("market") == market_label
            and str(row.get("game_id") or "") == game_id_text
        ]
        if not market_rows:
            continue
        model_side = next((row.get("model_side") for row in market_rows if row.get("model_side")), None)
        if not model_side:
            # No sim coverage for this market at all (join_status
            # unmatched_no_sim_coverage on every sibling row) -- the model
            # has no opinion, so there's nothing to recommend. Mirrors
            # MLB's own "don't fabricate a pick" rule above.
            continue
        picked = next((row for row in market_rows if row.get("side") == model_side), None)
        if picked is None or picked.get("odds") is None:
            # The model favors a side the book hasn't actually priced --
            # no real odds coverage to show a bettable pick against.
            continue
        side = str(picked.get("side") or "")
        line = picked.get("line")
        if market_label == "Moneyline":
            display_pick = "Home ML" if side == "home" else "Away ML" if side == "away" else None
        elif market_label == "Spread":
            side_label = "Home" if side == "home" else "Away" if side == "away" else side.title()
            display_pick = f"{side_label} {line}".strip() if line is not None else None
        else:  # Total
            display_pick = f"{side.title()} {line}".strip() if line is not None else None
        if not display_pick:
            continue
        sim_projection = picked.get("sim_projection")
        projected_value = picked.get("projected_value")
        if projected_value is not None:
            # Spread/Total carry a real projected magnitude (model margin /
            # model total) distinct from the side's win/cover probability --
            # kept as a raw number, matching MLB's own Total projected field.
            projected: Any = projected_value
        elif isinstance(sim_projection, (int, float)):
            # Moneyline has no separate "projected line" concept -- the
            # model's own win probability IS the projection, same reasoning
            # as MLB's Moneyline projected field just above.
            projected = f"{sim_projection * 100.0:.1f}%"
        else:
            projected = None
        rows.append(
            {
                "market_label": market_label,
                "display_pick": display_pick,
                "selection": picked.get("side"),
                "odds": picked.get("odds"),
                "confidence": sim_projection,
                "projected": projected,
                "summary": picked.get("join_note"),
            }
        )
    return rows


def _ncaaf_game_market_recommendation_rows(game_id: Any, board_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Same class of gap NFL had (see _nfl_game_market_recommendation_rows
    # just above, which this mirrors closely): NCAAF never set
    # game_market_recommendations, so it never reached the cross-sport Layer
    # 2 opportunity feed. ``board_rows`` is one game's Layer 1 inventory as
    # build_ncaaf_market_board (ncaaf/cards.py) produces it via
    # join_odds_to_sim, with "market" already remapped to the display labels
    # "Moneyline"/"Spread"/"Total" (_NCAAF_MARKET_BOARD_DISPLAY_LABELS).
    #
    # Unlike NFL, NCAAF's real market-line data (CFBD) carries no per-side
    # price for Spread/Total today -- _ncaaf_market_board_rows_for_game only
    # ever attaches a real "line" for those two markets, never an "odds"
    # price on either side. The "picked.get('odds') is None -> skip" check
    # below (same discipline NFL uses: never recommend a side the book
    # hasn't actually priced) means only Moneyline recommendations surface
    # for NCAAF in practice right now -- expected given current real data,
    # not a bug.
    rows: list[dict[str, Any]] = []
    game_id_text = str(game_id or "")
    for market_label in ("Moneyline", "Spread", "Total"):
        market_rows = [
            row
            for row in board_rows
            if isinstance(row, dict)
            and row.get("market_type") == "game"
            and row.get("market") == market_label
            and str(row.get("game_id") or "") == game_id_text
        ]
        if not market_rows:
            continue
        model_side = next((row.get("model_side") for row in market_rows if row.get("model_side")), None)
        if not model_side:
            continue
        picked = next((row for row in market_rows if row.get("side") == model_side), None)
        if picked is None or picked.get("odds") is None:
            continue
        side = str(picked.get("side") or "")
        line = picked.get("line")
        if market_label == "Moneyline":
            display_pick = "Home ML" if side == "home" else "Away ML" if side == "away" else None
        elif market_label == "Spread":
            side_label = "Home" if side == "home" else "Away" if side == "away" else side.title()
            display_pick = f"{side_label} {line}".strip() if line is not None else None
        else:  # Total
            display_pick = f"{side.title()} {line}".strip() if line is not None else None
        if not display_pick:
            continue
        sim_projection = picked.get("sim_projection")
        projected_value = picked.get("projected_value")
        if projected_value is not None:
            projected: Any = projected_value
        elif isinstance(sim_projection, (int, float)):
            projected = f"{sim_projection * 100.0:.1f}%"
        else:
            projected = None
        rows.append(
            {
                "market_label": market_label,
                "display_pick": display_pick,
                "selection": picked.get("side"),
                "odds": picked.get("odds"),
                "confidence": sim_projection,
                "projected": projected,
                "summary": picked.get("join_note"),
            }
        )
    return rows


def _apply_nba_live_scores(games: list[dict[str, Any]], selected_date: str) -> list[dict[str, Any]]:
    try:
        from syndicate.features.nba.cards import _games_from_live_state_fallback
    except Exception:
        return games

    live_games, _ = _games_from_live_state_fallback(selected_date)
    if not live_games:
        return games

    keyed_live: dict[tuple[str, str], dict[str, Any]] = {}
    for game in live_games:
        if not isinstance(game, dict):
            continue
        away_key = str(game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "")).strip().upper()
        home_key = str(game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "")).strip().upper()
        if away_key and home_key:
            keyed_live[(away_key, home_key)] = game

    enriched: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for game in games:
        if not isinstance(game, dict):
            continue
        away_key = str(game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "")).strip().upper()
        home_key = str(game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "")).strip().upper()
        live_game = keyed_live.get((away_key, home_key)) if away_key and home_key else None
        if not live_game:
            enriched.append(game)
            continue
        seen.add((away_key, home_key))
        updated = dict(game)
        away = dict(game.get("away") or {}) if isinstance(game.get("away"), dict) else {}
        home = dict(game.get("home") or {}) if isinstance(game.get("home"), dict) else {}
        live_state = dict(live_game.get("live_state") or {}) if isinstance(live_game.get("live_state"), dict) else {}
        if live_state.get("away_pts") is not None:
            away["score"] = live_state.get("away_pts")
        if live_state.get("home_pts") is not None:
            home["score"] = live_state.get("home_pts")
        updated["away"] = away
        updated["home"] = home
        status = dict(game.get("status") or {}) if isinstance(game.get("status"), dict) else {}
        if live_state.get("away_pts") is not None:
            status["away_score"] = live_state.get("away_pts")
        if live_state.get("home_pts") is not None:
            status["home_score"] = live_state.get("home_pts")
        status["is_live"] = bool(live_state.get("in_progress"))
        status["in_progress"] = bool(live_state.get("in_progress"))
        status["is_final"] = bool(live_state.get("final"))
        status["final"] = bool(live_state.get("final"))
        if live_state.get("in_progress"):
            status["abstract"] = "Live"
        elif live_state.get("final"):
            status["abstract"] = "Final"
        detail_text = str(live_state.get("status") or live_game.get("detail") or "").strip()
        if detail_text:
            status["detailed"] = detail_text
        updated["status"] = status
        updated["live_state"] = live_state
        enriched.append(updated)

    for key, live_game in keyed_live.items():
        if key not in seen:
            enriched.append(live_game)
    return enriched


def _apply_wnba_live_scores(games: list[dict[str, Any]], selected_date: str) -> list[dict[str, Any]]:
    try:
        from syndicate.features.wnba.cards import build_live_state_payload
    except Exception:
        return games

    payload = build_live_state_payload(selected_date, ttl=12, allow_stored_date_fallback=False)
    rows = payload.get("games") if isinstance(payload, dict) else []
    if not isinstance(rows, list) or not rows:
        return games

    keyed_live: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        away_key = str(row.get("away_tri") or row.get("away") or "").strip().upper()
        home_key = str(row.get("home_tri") or row.get("home") or "").strip().upper()
        if away_key and home_key:
            keyed_live[(away_key, home_key)] = row

    enriched: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        away_key = str(game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "")).strip().upper()
        home_key = str(game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "")).strip().upper()
        live_row = keyed_live.get((away_key, home_key)) if away_key and home_key else None
        if not live_row:
            enriched.append(game)
            continue

        updated = dict(game)
        away = dict(game.get("away") or {}) if isinstance(game.get("away"), dict) else {}
        home = dict(game.get("home") or {}) if isinstance(game.get("home"), dict) else {}
        live_state = {
            "away_pts": live_row.get("away_pts"),
            "home_pts": live_row.get("home_pts"),
            "in_progress": bool(live_row.get("in_progress")),
            "final": bool(live_row.get("final")),
            "status": str(live_row.get("status") or "").strip(),
        }

        # cards.py's live-state row falls back to the SmartSim *projected*
        # point total for away_pts/home_pts whenever no real ESPN boxscore
        # row has matched yet (the normal state for any game that hasn't
        # tipped off) -- that's a legitimate pregame projection elsewhere,
        # but "score" fields must only ever hold a real observed score.
        # Without this in_progress/final gate, a pregame WNBA game showed a
        # fabricated decimal "score" like 91.81-91.17 on the board's
        # game-chip strip (#160).
        is_game_underway = bool(live_state.get("in_progress")) or bool(live_state.get("final"))
        live_away_pts = live_state.get("away_pts") if is_game_underway else None
        live_home_pts = live_state.get("home_pts") if is_game_underway else None
        if live_away_pts is not None:
            away["score"] = live_away_pts
        if live_home_pts is not None:
            home["score"] = live_home_pts
        updated["away"] = away
        updated["home"] = home

        status = dict(game.get("status") or {}) if isinstance(game.get("status"), dict) else {"abstract": str(game.get("status") or "").strip()}
        if live_away_pts is not None:
            status["away_score"] = live_away_pts
        if live_home_pts is not None:
            status["home_score"] = live_home_pts
        status["is_live"] = bool(live_state.get("in_progress"))
        status["in_progress"] = bool(live_state.get("in_progress"))
        status["is_final"] = bool(live_state.get("final"))
        status["final"] = bool(live_state.get("final"))
        if live_state.get("in_progress"):
            status["abstract"] = "Live"
        elif live_state.get("final"):
            status["abstract"] = "Final"
        detail_text = str(live_state.get("status") or game.get("detail") or "").strip()
        if detail_text:
            status["detailed"] = detail_text
        updated["status"] = status
        updated["live_state"] = live_state
        enriched.append(updated)
    return enriched


def _load_nhl_scoreboard_rows(selected_date: str) -> list[dict[str, Any]]:
    if selected_date == central_today_iso():
        try:
            from syndicate.local_nhl_odds import NhlWebClient

            rows = NhlWebClient().scoreboard_day(selected_date)
            if rows:
                def _coalesce_score(*values: Any) -> Any:
                    for value in values:
                        if value is None:
                            continue
                        if isinstance(value, str) and not value.strip():
                            continue
                        return value
                    return None

                return [
                    {
                        "gamePk": row.get("gamePk") or row.get("game_id"),
                        "away": row.get("away") or row.get("away_team"),
                        "home": row.get("home") or row.get("home_team"),
                        "away_abbr": row.get("away_abbr") or row.get("away_tri"),
                        "home_abbr": row.get("home_abbr") or row.get("home_tri"),
                        "away_goals": _coalesce_score(row.get("away_goals"), row.get("awayScore"), row.get("away_score")),
                        "home_goals": _coalesce_score(row.get("home_goals"), row.get("homeScore"), row.get("home_score")),
                        "gameState": row.get("gameState") or row.get("game_state") or row.get("state"),
                        "period": row.get("period") or row.get("web_period"),
                        "clock": row.get("clock") or row.get("web_clock"),
                    }
                    for row in rows
                    if isinstance(row, dict)
                ]
        except Exception:
            pass

    path = scoreboard_snapshot_path(selected_date)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "gamePk": row.get("gamePk") or row.get("game_id"),
                "away": row.get("away") or row.get("away_team"),
                "home": row.get("home") or row.get("home_team"),
                "away_abbr": row.get("away_abbr") or row.get("away_tri"),
                "home_abbr": row.get("home_abbr") or row.get("home_tri"),
                "away_goals": row.get("away_goals") or row.get("awayScore") or row.get("away_score"),
                "home_goals": row.get("home_goals") or row.get("homeScore") or row.get("home_score"),
                "gameState": row.get("gameState") or row.get("game_state") or row.get("state"),
                "period": row.get("period") or row.get("web_period"),
                "clock": row.get("clock") or row.get("web_clock"),
            }
        )
    return out


def _apply_nhl_live_scores(games: list[dict[str, Any]], selected_date: str) -> list[dict[str, Any]]:
    rows = _load_nhl_scoreboard_rows(selected_date)
    if not rows:
        return games

    keyed_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        row_keys = {
            (
                str(row.get("away_abbr") or "").strip().upper(),
                str(row.get("home_abbr") or "").strip().upper(),
            ),
            (
                str(row.get("away") or "").strip().upper(),
                str(row.get("home") or "").strip().upper(),
            ),
        }
        for key in row_keys:
            if key[0] and key[1]:
                keyed_rows[key] = row

    enriched: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        game_keys = [
            (
                str(game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "")).strip().upper(),
                str(game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "")).strip().upper(),
            ),
            (
                str(game.get("away_name") or ((game.get("away") or {}).get("name") if isinstance(game.get("away"), dict) else "")).strip().upper(),
                str(game.get("home_name") or ((game.get("home") or {}).get("name") if isinstance(game.get("home"), dict) else "")).strip().upper(),
            ),
        ]
        row = next((keyed_rows.get(key) for key in game_keys if key[0] and key[1] and keyed_rows.get(key)), None)
        if not row:
            enriched.append(game)
            continue
        updated = dict(game)
        away = dict(game.get("away") or {}) if isinstance(game.get("away"), dict) else {}
        home = dict(game.get("home") or {}) if isinstance(game.get("home"), dict) else {}
        away_goals = _numeric_value(row.get("away_goals"))
        home_goals = _numeric_value(row.get("home_goals"))
        if away_goals is not None:
            away["score"] = away_goals
        if home_goals is not None:
            home["score"] = home_goals
        updated["away"] = away
        updated["home"] = home
        state = str(row.get("gameState") or "").strip().upper()
        period = str(row.get("period") or "").strip()
        clock = str(row.get("clock") or "").strip()
        detail_bits = [bit for bit in [state, f"P{period}" if period else None, clock or None] if bit]
        live_state = {
            "away_pts": away_goals,
            "home_pts": home_goals,
            "in_progress": state in {"LIVE", "CRIT"},
            "final": state == "OFF",
            "status": " | ".join(detail_bits) if detail_bits else selected_date,
        }
        status = dict(game.get("status") or {}) if isinstance(game.get("status"), dict) else {}
        if away_goals is not None:
            status["away_score"] = away_goals
        if home_goals is not None:
            status["home_score"] = home_goals
        status["is_live"] = bool(live_state["in_progress"])
        status["in_progress"] = bool(live_state["in_progress"])
        status["is_final"] = bool(live_state["final"])
        status["final"] = bool(live_state["final"])
        if live_state["in_progress"]:
            status["abstract"] = "Live"
        elif live_state["final"]:
            status["abstract"] = "Final"
        status["detailed"] = live_state["status"]
        updated["status"] = status
        updated["live_state"] = live_state
        updated["shared_is_live"] = bool(live_state["in_progress"])
        enriched.append(updated)
    return enriched


def _market_based_projected_scores(game: dict[str, Any]) -> tuple[str | None, str | None]:
    total = _metric_or_tile_value(game, ["total", "full total", "model total"])
    home_line = _metric_or_tile_value(game, ["spread", "home spread"])
    if total is None or home_line is None:
        return None, None
    margin = -home_line
    home_score = (total + margin) / 2.0
    away_score = total - home_score
    away_text = _score_value(away_score)
    home_text = _score_value(home_score)
    if away_text and home_text:
        return away_text, home_text
    return None, None


def _projected_scores(game: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    predictions = game.get("predictions") if isinstance(game.get("predictions"), dict) else {}
    full = predictions.get("full") if isinstance(predictions.get("full"), dict) else predictions
    away_mean = full.get("away_runs_mean") if isinstance(full, dict) else None
    home_mean = full.get("home_runs_mean") if isinstance(full, dict) else None
    if away_mean is None or home_mean is None:
        sim = game.get("sim") if isinstance(game.get("sim"), dict) else {}
        score = sim.get("score") if isinstance(sim.get("score"), dict) else sim
        if isinstance(score, dict):
            away_mean = score.get("away_mean", away_mean)
            home_mean = score.get("home_mean", home_mean)
    away_score = _score_value(away_mean)
    home_score = _score_value(home_mean)
    if away_score and home_score:
        return away_score, home_score, "Projection"
    market_away, market_home = _market_based_projected_scores(game)
    if market_away and market_home:
        return market_away, market_home, "Market projection"
    return None, None, None


def _prop_item_from_rank_card(
    card: dict[str, Any],
    *,
    sport_slug: str | None = None,
    fallback_href: str | None = None,
    heading_override: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(card, dict):
        return None
    title = _safe_text(card.get("title"), "Prop")
    meta = _safe_text(card.get("meta"), "Props board")
    # Rank cards across sports (wnba/nhl/nfl/ncaaf/ncaab picks.py) carry up
    # to 4 real reasoning bullets in "list_items" (e.g. WNBA's
    # top_play_reasons) alongside the one-line "summary" -- this was never
    # read here, so the actual evidence behind a pick disappeared the
    # moment it became a Betting Board candidate, leaving only a generic
    # one-liner (or nothing at all).
    summary_text = _safe_text(card.get("summary"), "")
    list_items = [str(item).strip() for item in (card.get("list_items") or []) if str(item).strip()]
    detail = " ".join(part for part in [summary_text, *list_items] if part) or "No prop summary available."
    badge = str(card.get("badge") or "").strip()
    metrics = card.get("metrics") if isinstance(card.get("metrics"), list) else []
    value = badge or _safe_text((((card.get("metrics") or [None])[0] or {}).get("value") if isinstance(card.get("metrics"), list) else None), "Top play")
    href = str(card.get("href") or fallback_href or "").strip() or None
    away_label, home_label = _split_matchup_labels(meta if meta != "Props board" else title)
    team_value = _metric_value(metrics, ["team", "team_tri", "team_abbr", "side"])
    if not team_value:
        # Rank-card builders across sports (e.g. wnba/picks.py, nba/picks.py
        # _card_from_pick) put the pick's team abbreviation in "eyebrow"
        # (falling back to the market label when no team is known) -- check
        # it against this card's own known matchup labels before falling
        # back to a broader text search, since eyebrow is otherwise never
        # read here and every rank-card-sourced prop lost its team.
        haystack = f"{title} {badge} {detail} {card.get('eyebrow', '')}".lower()
        for candidate_label in (away_label, home_label):
            if candidate_label and candidate_label.lower() in haystack:
                team_value = candidate_label
                break
    # Board-alignment audit, found live 2026-08-01 against a real live WNBA
    # game: this row never carried its own "player_name" field -- only
    # "name" (== title, the full pick text, e.g. "Alyssa Thomas UNDER 8.5").
    # _prop_candidate_from_item (intelligence.py) falls back to "name" when
    # "player_name" is missing, so the pick text ended up AS the subject
    # used by _merge_duplicate_prop_candidates' dedup key -- a
    # rank-card-sourced pregame duplicate for the same player+market
    # ("Alyssa Thomas UNDER 8.5 AST", subject "Alyssa Thomas UNDER 8.5 AST")
    # never matched its correctly-live-wired twin ("Alyssa Thomas AST",
    # subject "Alyssa Thomas") produced by a different pipeline, so they
    # never merged and the pregame duplicate stayed permanently stuck with
    # no live_projection/actual even once its own game went live. Computed
    # unconditionally now (not just when resolving a missing headshot) and
    # stamped onto the row so dedup can find the real subject.
    player_name = _player_name_from_prop_title(title) or _safe_text(card.get("summary"), None)
    headshot_url = card.get("headshot_url") or card.get("photo") or card.get("player_photo")
    if not headshot_url and sport_slug in {"nba", "wnba"}:
        resolved_player_id = _basketball_resolve_player_id(sport_slug, player_name=player_name, team_tri=away_label)
        headshot_url = _basketball_best_headshot_url(player_id=resolved_player_id)
    return {
        "matchup": meta,
        "heading": _safe_text(heading_override or card.get("eyebrow"), "Props"),
        "name": title,
        "player_name": player_name,
        "detail": detail,
        "value": value,
        "photo": headshot_url,
        "headshot_url": headshot_url,
        "is_live": False,
        # Rank-card builders (e.g. wnba/picks.py's _card_from_pick) put the
        # stat category in the card's own top-level "market" field, never in
        # "metrics" -- the metrics scan alone always came back empty, so this
        # always fell through to the generic "Props"/"Betting Card" heading
        # regardless of what stat the prop was actually on.
        "market": _metric_value(metrics, ["market", "stat"]) or _safe_text(card.get("market"), None),
        # badge is an EV/confidence percentage (e.g. "20.4% EV") -- it is
        # never a valid "pick" value. It used to be checked first here, and
        # since format_num() always produces a truthy string, it always won,
        # so every rank-card-sourced prop's pick/selection ended up as a
        # bare percentage instead of the actual selection. Real WNBA/NBA
        # rank cards (_card_from_pick) never label a metric "pick"/"lean"/
        # "selection"/"side" either, so title (the actual display_pick
        # text, e.g. "Gabby Williams OVER 1.5") is the real fallback.
        "pick": _metric_value(metrics, ["pick", "lean", "selection", "side"]) or title,
        "actual": _metric_value(metrics, ["actual"]),
        "projected": _metric_value(metrics, ["projected", "projection", "model", "mean", "median"]),
        "live_projection": _metric_value(metrics, ["live projection", "live_proj"]),
        "line": _metric_value(metrics, ["line", "market line", "threshold"]),
        "odds": _metric_value(metrics, ["odds", "price"]),
        "price": _metric_value(metrics, ["price", "odds"]),
        "edge": _metric_value(metrics, ["edge", "ev"]),
        "confidence": _metric_value(metrics, ["confidence", "win prob", "probability", "hit rate"]),
        "game_state": _metric_value(metrics, ["game state", "state", "status"]),
        "team": team_value or None,
        "away_label": away_label,
        "home_label": home_label,
        "away_logo": _safe_text(card.get("away_logo"), None),
        "home_logo": _safe_text(card.get("home_logo"), None),
        "href": href,
    }


def _rank_card_score_values(card: dict[str, Any]) -> tuple[str | None, str | None]:
    metrics = card.get("metrics") if isinstance(card.get("metrics"), list) else []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        label = str(metric.get("label") or "").strip().lower()
        value = str(metric.get("value") or "").strip()
        if label != "score" or "-" not in value:
            continue
        away_text, home_text = [part.strip() for part in value.split("-", 1)]
        return away_text or None, home_text or None
    return None, None


def _compact_game_items_from_rank_cards(cards: list[dict[str, Any]], *, fallback_href: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        title = _safe_text(card.get("title"), "Lens card")
        if " @ " in title:
            away_label, home_label = [part.strip() or "-" for part in title.split(" @ ", 1)]
        else:
            away_label, home_label = title, "-"
        away_score, home_score = _rank_card_score_values(card)
        items.append(
            {
                "matchup": title,
                "detail": _safe_text(card.get("meta"), "Live lens"),
                "status_badge": _safe_text(card.get("eyebrow"), "Live lens"),
                "away_label": away_label,
                "away_logo": _safe_text(card.get("away_logo"), None),
                "home_label": home_label,
                "home_logo": _safe_text(card.get("home_logo"), None),
                "away_score": away_score,
                "home_score": home_score,
                "has_scores": bool(away_score and home_score),
                "score_kind": "Live score" if away_score and home_score else "Live lens",
                "is_projected_score": False,
                "summary": _safe_text(card.get("summary"), "No live-lens summary available."),
                "signals": [
                    _safe_text(card.get("badge"), "Watch")
                ] + [
                    f"{_safe_text(metric.get('label'))}: {_safe_text(metric.get('value'))}"
                    for metric in (card.get("metrics") if isinstance(card.get("metrics"), list) else [])[:3]
                    if isinstance(metric, dict)
                ],
                "href": str(card.get("href") or fallback_href or "").strip() or None,
                "href_label": str(card.get("href_label") or "Open live lens").strip() or "Open live lens",
            }
        )
        if limit is not None and len(items) >= limit:
            break
    return items


def _load_home_game_items(
    slug: str,
    *,
    context_label: str,
    season: int | None = None,
    week: int | None = None,
    is_active_today: bool,
) -> tuple[list[dict[str, Any]], int]:
    home_games = _load_home_games(slug, context_label=context_label, season=season, week=week, is_active_today=is_active_today) if is_active_today else []
    if slug == "mlb" and home_games:
        home_games = _apply_mlb_live_scores(home_games, context_label)
    if not is_active_today:
        return [], len(home_games)
    try:
        if slug == "mlb":
            from syndicate.features.mlb.live_lens import read_latest_live_lens_page_context

            live_games = list(read_latest_live_lens_page_context(context_label).get("games") or [])
            if home_games:
                return _compact_game_cards(home_games), len(home_games)
            if live_games:
                live_games = _apply_mlb_live_scores(live_games, context_label)
                return _compact_game_cards(live_games), len(live_games)
        if slug == "nba":
            if home_games:
                return _compact_game_cards(home_games), len(home_games)
        if slug == "wnba":
            if home_games:
                return _compact_game_cards(home_games), len(home_games)
        if slug == "nhl":
            if home_games:
                return _compact_game_cards(home_games), len(home_games)
        if slug == "ncaab":
            from syndicate.features.ncaab.live_lens import build_live_lens_page_context

            context = build_live_lens_page_context(context_label)
            cards = list(context.get("rank_cards") or [])
            if cards:
                return _compact_game_items_from_rank_cards(cards, fallback_href=f"/ncaab/live-lens?date={context_label}"), len(cards)
        if slug == "nfl" and week is not None:
            from syndicate.features.nfl.live_lens import build_live_lens_page_context

            context = build_live_lens_page_context(week, season=int(season or central_year()))
            cards = list(context.get("rank_cards") or [])
            if cards:
                return _compact_game_items_from_rank_cards(cards, fallback_href=f"/nfl/live-lens?season={int(season or central_year())}&week={week}"), len(cards)
        if slug == "ncaaf" and week is not None:
            from syndicate.features.ncaaf.live_lens import build_live_lens_page_context

            context = build_live_lens_page_context(week)
            cards = list(context.get("rank_cards") or [])
            if cards:
                return _compact_game_items_from_rank_cards(cards, fallback_href=f"/ncaaf/live-lens?week={week}"), len(cards)
    except Exception:
        pass
    return _compact_game_cards(home_games), len(home_games)


def _prop_rows_from_rank_cards(
    cards: list[dict[str, Any]],
    *,
    sport_slug: str | None = None,
    fallback_href: str | None = None,
    limit: int = 18,
    heading_override: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        item = _prop_item_from_rank_card(
            card,
            sport_slug=sport_slug,
            fallback_href=fallback_href,
            heading_override=heading_override,
        )
        if not item:
            continue
        rows.append(item)
        if len(rows) >= limit:
            break
    return rows


def _betting_card_rank_cards(slug: str, *, context_label: str, season: int | None = None, week: int | None = None) -> tuple[list[dict[str, Any]], str | None, str | None]:
    if slug == "mlb":
        from syndicate.features.mlb.betting_card import build_betting_card_page_context

        resolved_season = _int_or_none(str(context_label)[:4]) or central_year()
        context = build_betting_card_page_context(int(resolved_season), context_label)
        return list(context.get("rank_cards") or []), context.get("route_path"), context.get("date")
    if slug == "nba":
        from syndicate.features.nba.betting_card import build_season_betting_card_day_payload

        resolved_season = _int_or_none(str(context_label)[:4]) or central_year()
        payload = build_season_betting_card_day_payload(int(resolved_season), context_label, "retuned") or {}
        return list(payload.get("rank_cards") or []), payload.get("route_path"), payload.get("date")
    if slug == "wnba":
        from syndicate.features.wnba.picks import build_betting_card_page_context

        resolved_season = _int_or_none(str(context_label)[:4]) or central_year()
        context = build_betting_card_page_context(int(resolved_season), context_label)
        return list(context.get("rank_cards") or []), context.get("route_path"), context.get("date")
    if slug == "nhl":
        from syndicate.features.nhl.picks import build_betting_card_page_context

        resolved_season = int(season or (_int_or_none(str(context_label)[:4]) or central_year()))
        context = build_betting_card_page_context(resolved_season, context_label)
        return list(context.get("rank_cards") or []), context.get("route_path"), context.get("date")
    if slug == "nfl" and week is not None and season is not None:
        from syndicate.features.nfl.picks import build_betting_card_page_context

        context = build_betting_card_page_context(int(season), int(week))
        return list(context.get("rank_cards") or []), context.get("route_path"), context.get("date")
    if slug == "ncaaf" and week is not None and season is not None:
        from syndicate.features.ncaaf.picks import build_betting_card_page_context

        context = build_betting_card_page_context(int(season), int(week))
        return list(context.get("rank_cards") or []), context.get("route_path"), context.get("date")
    if slug == "ncaab" and season is not None:
        from syndicate.features.ncaab.season import build_season_betting_card_page_context

        context = build_season_betting_card_page_context(int(season), context_label)
        return list(context.get("rank_cards") or []), context.get("route_path"), context.get("date")
    return [], None, None


def _pregame_prop_rows_from_mlb_recommendations(
    context_label: str,
    *,
    limit: int = 18,
    fallback_href: str | None = None,
) -> list[dict[str, Any]]:
    """Extract MLB player prop recommendations and convert to prop rows.
    
    Only includes pitcher and hitter props (no totals/ML).
    Formats with writeup and pills (line, sim mean, odds) similar to HR targets.
    """
    try:
        from syndicate.features.mlb.cards import _cards_recommendation_payload_by_game
        from syndicate.features.mlb.cards import _mlb_headshot_url
        from syndicate.features.mlb.cards import _mlb_logo_url

        recos_by_game = _cards_recommendation_payload_by_game(context_label)
        rows: list[dict[str, Any]] = []
        
        for game_pk, game_data in recos_by_game.items():
            if not isinstance(game_data, dict):
                continue
            
            markets = game_data.get("markets", {}) if isinstance(game_data.get("markets"), dict) else {}
            matchup_data = game_data.get("matchup") if isinstance(game_data.get("matchup"), dict) else {}
            away = game_data.get("away") if isinstance(game_data.get("away"), dict) else matchup_data.get("away") if isinstance(matchup_data.get("away"), dict) else {}
            home = game_data.get("home") if isinstance(game_data.get("home"), dict) else matchup_data.get("home") if isinstance(matchup_data.get("home"), dict) else {}
            away_label = str(away.get("abbr") or away.get("teamAbbr") or away.get("name") or away.get("teamName") or "").strip() or None
            home_label = str(home.get("abbr") or home.get("teamAbbr") or home.get("name") or home.get("teamName") or "").strip() or None
            away_logo = str(away.get("logo") or away.get("logo_url") or away.get("teamLogo") or "").strip() or None
            home_logo = str(home.get("logo") or home.get("logo_url") or home.get("teamLogo") or "").strip() or None
            fallback_matchup = " @ ".join(part for part in [away_label, home_label] if part) or f"Game {game_pk}"
            
            # Add pitcher props
            pitcher_props = [
                *([row for row in (markets.get("pitcherProps") or []) if isinstance(row, dict)]),
                *([row for row in (markets.get("extraPitcherProps") or []) if isinstance(row, dict)]),
            ]
            if isinstance(pitcher_props, list):
                for prop in pitcher_props:
                    if not isinstance(prop, dict):
                        continue
                    pitcher = str(prop.get("pitcher_name") or prop.get("player_name") or "Pitcher").strip()
                    prop_type = str(prop.get("prop") or "strikeouts").strip().title()
                    line_val = _score_value(prop.get("market_line")) or str(prop.get("market_line") or "-")
                    selection = str(prop.get("selection") or "").strip().upper()
                    matchup_text = str(prop.get("matchup") or "").strip()
                    if not matchup_text or re.fullmatch(r"Game\s+\d+", matchup_text, flags=re.IGNORECASE):
                        matchup_text = fallback_matchup
                    edge = _numeric_value(prop.get("edge"))
                    edge_text = f"{edge * 100:.1f}% EV" if edge is not None else "-"
                    model_prob = _numeric_value(prop.get("model_prob"))
                    if model_prob is None:
                        model_prob = _numeric_value(prop.get("model_prob_over") if selection == "OVER" else prop.get("model_prob_under"))
                    sim_mean_text = f"{model_prob * 100:.1f}%" if model_prob is not None else "-"
                    projected_text = _prop_metric_text(
                        prop.get("projection")
                        if prop.get("projection") is not None
                        else prop.get("mean")
                        if prop.get("mean") is not None
                        else prop.get("modelMean")
                        if prop.get("modelMean") is not None
                        else prop.get("sim_mean")
                        if prop.get("sim_mean") is not None
                        else prop.get("projected")
                        if prop.get("projected") is not None
                        else prop.get("baseline")
                    )
                    odds_text = _prop_metric_text(prop.get("odds") or prop.get("price"))
                    ladder_groups = []
                    for badge in (prop.get("pregameLadderBadges") or prop.get("ladderBadges") or []):
                        if not isinstance(badge, dict):
                            continue
                        targets = [int(total) for total in (badge.get("targets") or []) if _int_or_none(total) is not None]
                        if not targets:
                            continue
                        ladder_groups.append({
                            "short_label": str(badge.get("short_label") or badge.get("label") or prop_type).strip() or prop_type,
                            "targets": targets,
                        })
                    player_id = _int_or_none(prop.get("pitcher_id") or prop.get("player_id"))
                    row_away_label = away_label or str(prop.get("away_abbr") or prop.get("away") or "").strip() or None
                    row_home_label = home_label or str(prop.get("home_abbr") or prop.get("home") or "").strip() or None
                    row_matchup = " @ ".join(part for part in [row_away_label, row_home_label] if part) or fallback_matchup
                    row_away_logo = away_logo
                    row_home_logo = home_logo
                    if not row_away_logo:
                        row_away_logo = _mlb_logo_url(_int_or_none(away.get("team_id") or away.get("teamId")))
                    if not row_home_logo:
                        row_home_logo = _mlb_logo_url(_int_or_none(home.get("team_id") or home.get("teamId")))
                    
                    writeup = f"Recommended {selection} for {pitcher} {prop_type} at {line_val}. Model gives {sim_mean_text} win probability with {edge_text} edge."
                    pills = [
                        {"label": "Line", "value": line_val},
                        {"label": "Sim", "value": sim_mean_text},
                        {"label": "Odds", "value": odds_text},
                    ]
                    
                    pitcher_team_side = str(prop.get("team_side") or "").strip().lower()
                    pitcher_team = row_home_label if pitcher_team_side == "home" else row_away_label if pitcher_team_side == "away" else None
                    rows.append({
                        "game_pk": _int_or_none(game_pk),
                        "matchup": row_matchup if re.fullmatch(r"Game\s+\d+", matchup_text, flags=re.IGNORECASE) else matchup_text,
                        "heading": "Betting Card",
                        "name": pitcher,
                        "player_name": pitcher,
                        "team": pitcher_team,
                        "detail": f"{selection} {line_val}",
                        "value": edge_text,
                        "is_live": False,
                        "market": f"Pitcher {prop_type}",
                        "pick": selection,
                        "line": line_val,
                        "projected": projected_text,
                        "odds": odds_text,
                        "edge": edge_text,
                        "confidence": _pct_text(model_prob),
                        "writeup": writeup,
                        "pills": pills,
                        "away_label": row_away_label,
                        "home_label": row_home_label,
                        "away_logo": row_away_logo,
                        "home_logo": row_home_logo,
                        "headshot_url": _mlb_headshot_url(player_id),
                        "ladder_groups": ladder_groups,
                        "href": fallback_href,
                    })
                    if len(rows) >= limit:
                        return rows[:limit]
            
            # Add hitter props
            hitter_props = [
                *([row for row in (markets.get("hitterProps") or []) if isinstance(row, dict)]),
                *([row for row in (markets.get("extraHitterProps") or []) if isinstance(row, dict)]),
            ]
            if isinstance(hitter_props, list):
                for prop in hitter_props:
                    if not isinstance(prop, dict):
                        continue
                    hitter = str(prop.get("player_name") or "Hitter").strip()
                    prop_type = str(prop.get("prop") or "hits").strip().title()
                    line_val = _score_value(prop.get("market_line")) or str(prop.get("market_line") or "-")
                    selection = str(prop.get("selection") or "").strip().upper()
                    matchup_text = str(prop.get("matchup") or "").strip()
                    if not matchup_text or re.fullmatch(r"Game\s+\d+", matchup_text, flags=re.IGNORECASE):
                        matchup_text = fallback_matchup
                    edge = _numeric_value(prop.get("edge"))
                    edge_text = f"{edge * 100:.1f}% EV" if edge is not None else "-"
                    model_prob = _numeric_value(prop.get("model_prob"))
                    if model_prob is None:
                        model_prob = _numeric_value(prop.get("model_prob_over") if selection == "OVER" else prop.get("model_prob_under"))
                    sim_mean_text = f"{model_prob * 100:.1f}%" if model_prob is not None else "-"
                    projected_text = _prop_metric_text(
                        prop.get("projection")
                        if prop.get("projection") is not None
                        else prop.get("mean")
                        if prop.get("mean") is not None
                        else prop.get("modelMean")
                        if prop.get("modelMean") is not None
                        else prop.get("sim_mean")
                        if prop.get("sim_mean") is not None
                        else prop.get("projected")
                        if prop.get("projected") is not None
                        else prop.get("baseline")
                    )
                    odds_text = _prop_metric_text(prop.get("odds") or prop.get("price"))
                    ladder_groups = []
                    for badge in (prop.get("pregameLadderBadges") or prop.get("ladderBadges") or []):
                        if not isinstance(badge, dict):
                            continue
                        targets = [int(total) for total in (badge.get("targets") or []) if _int_or_none(total) is not None]
                        if not targets:
                            continue
                        ladder_groups.append({
                            "short_label": str(badge.get("short_label") or badge.get("label") or prop_type).strip() or prop_type,
                            "targets": targets,
                        })
                    player_id = _int_or_none(prop.get("batter_id") or prop.get("player_id"))
                    row_away_label = away_label or str(prop.get("away_abbr") or prop.get("away") or "").strip() or None
                    row_home_label = home_label or str(prop.get("home_abbr") or prop.get("home") or "").strip() or None
                    row_matchup = " @ ".join(part for part in [row_away_label, row_home_label] if part) or fallback_matchup
                    row_away_logo = away_logo
                    row_home_logo = home_logo
                    team_id = _int_or_none(prop.get("team_id"))
                    opponent_team_id = _int_or_none(prop.get("opponent_team_id"))
                    team_label = str(prop.get("team") or "").strip() or None
                    opponent_label = str(prop.get("opponent") or "").strip() or None
                    if team_label and opponent_label:
                        if row_away_label is None and row_home_label is None:
                            row_away_label = team_label
                            row_home_label = opponent_label
                        if row_away_label == opponent_label and row_home_label == team_label:
                            row_away_logo = row_away_logo or _mlb_logo_url(opponent_team_id)
                            row_home_logo = row_home_logo or _mlb_logo_url(team_id)
                        else:
                            row_away_logo = row_away_logo or _mlb_logo_url(team_id)
                            row_home_logo = row_home_logo or _mlb_logo_url(opponent_team_id)
                    
                    writeup = f"Recommended {selection} for {hitter} {prop_type} at {line_val}. Model gives {sim_mean_text} win probability with {edge_text} edge."
                    pills = [
                        {"label": "Line", "value": line_val},
                        {"label": "Sim", "value": sim_mean_text},
                        {"label": "Odds", "value": odds_text},
                    ]
                    
                    rows.append({
                        "game_pk": _int_or_none(game_pk),
                        "matchup": row_matchup if re.fullmatch(r"Game\s+\d+", matchup_text, flags=re.IGNORECASE) else matchup_text,
                        "heading": "Betting Card",
                        "name": hitter,
                        "player_name": hitter,
                        "team": team_label,
                        "detail": f"{selection} {line_val}",
                        "value": edge_text,
                        "is_live": False,
                        "market": f"Hitter {prop_type}",
                        "pick": selection,
                        "line": line_val,
                        "projected": projected_text,
                        "odds": odds_text,
                        "edge": edge_text,
                        "confidence": _pct_text(model_prob),
                        "writeup": writeup,
                        "pills": pills,
                        "away_label": row_away_label,
                        "home_label": row_home_label,
                        "away_logo": row_away_logo,
                        "home_logo": row_home_logo,
                        "headshot_url": _mlb_headshot_url(player_id),
                        "ladder_groups": ladder_groups,
                        "href": fallback_href,
                    })
                    if len(rows) >= limit:
                        return rows[:limit]
        
        return rows
    except Exception:
        return []


_GAME_LEVEL_RANK_CARD_MARKET_KEYWORDS = ("moneyline", "spread", "total", "puck line", "puck_line", "run line", "run_line", "game bet")


def _is_game_level_rank_card_market(market_text: Any) -> bool:
    # A rank card's raw "market" code -- "ats"/"total"/"moneyline" for a
    # team-level game bet vs. a stat code ("pts"/"reb"/...) for a real
    # player prop. Mirrors intelligence.py's _is_game_level_market, kept as
    # a local copy rather than imported to avoid a circular import
    # (intelligence.py already imports from this module).
    lowered = str(market_text or "").strip().lower()
    if not lowered:
        return False
    if lowered == "ats":
        return True
    return any(keyword in lowered for keyword in _GAME_LEVEL_RANK_CARD_MARKET_KEYWORDS)


# #164: confirmed live -- WNBA's rank-card-sourced pregame props
# (_card_from_pick, wnba/picks.py) carry no game_id/gamePk/event_id at all
# (only "matchup"/"away_label"/"home_label" text), so _game_identifier()
# always returned None for them. _build_sport_overview's hydration step
# (home_games) then filters pregame_prop_items down to
# `_game_identifier(item) in hydrated_game_ids` -- with no id to match,
# EVERY real WNBA prop for today's slate was silently dropped, even though
# the underlying picks were real (recommendations_slate_<date>.json had 15
# real picks across all 3 of today's games). Backfill the real gamePk via
# team-abbreviation match against home_games, the same pattern already used
# for soccer's steam candidates (game_id_by_team_abbrs, intelligence.py).
def _backfill_prop_row_game_id(rows: list[dict[str, Any]], home_games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Confirmed live 2026-08-01 against a real live WNBA game: a game dict
    # can carry game_id (the odds-pipeline hash) and event_id (ESPN's
    # numeric scoreboard id) as genuinely distinct fields at once (see
    # wnba/cards.py's own game-contract builders, which set both
    # independently). This used to collapse them -- stamping
    # row["event_id"] with _game_identifier(game)'s single result, which
    # prefers game_id over event_id -- so a backfilled row's event_id
    # became the odds hash instead of the real ESPN id. Every downstream
    # live-actual/live-projection lookup that matches candidates against
    # live_state by event_id (ESPN-keyed) then silently failed for these
    # rows, leaving live_projection/actual stuck at "-" even while the row
    # correctly showed is_live=True and a real status_display. Track and
    # stamp game_id and event_id separately so each keeps its own real
    # value instead of one clobbering the other.
    ids_by_abbrs: dict[str, tuple[str, str]] = {}
    for game in home_games:
        if not isinstance(game, dict):
            continue
        game_id = _game_identifier(game)
        if not game_id:
            continue
        event_id = _safe_text(game.get("event_id"), "") or game_id
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        away_abbr = _safe_text(game.get("away_tri") or away.get("abbr"), "").upper()
        home_abbr = _safe_text(game.get("home_tri") or home.get("abbr"), "").upper()
        if away_abbr and home_abbr:
            ids_by_abbrs[f"{away_abbr}|{home_abbr}"] = (game_id, event_id)
    if not ids_by_abbrs:
        return rows
    for row in rows:
        if not isinstance(row, dict) or _game_identifier(row):
            continue
        away_abbr = _safe_text(row.get("away_label"), "").upper()
        home_abbr = _safe_text(row.get("home_label"), "").upper()
        ids = ids_by_abbrs.get(f"{away_abbr}|{home_abbr}")
        if ids:
            game_id, event_id = ids
            row["game_id"] = game_id
            row["gamePk"] = game_id
            row["event_id"] = event_id
    return rows


def _pregame_prop_rows_from_betting_card(
    slug: str,
    *,
    context_label: str,
    season: int | None = None,
    week: int | None = None,
    limit: int = 18,
) -> list[dict[str, Any]]:
    if slug == "mlb":
        return []

    # For other sports, use rank_cards from betting card
    cards, route_path, resolved_date = _betting_card_rank_cards(slug, context_label=context_label, season=season, week=week)
    if not cards:
        return []
    # Team-level game bets (ats/total/moneyline) reach this same rank-card
    # list alongside real player props -- they're already correctly
    # represented as "game" candidates via game_market_recommendations, so
    # forcing them through here too (as a fake "prop" labeled "Betting
    # Card") duplicated every game-level pick on the board. Confirmed live
    # 2026-07-27: WNBA's ATS and Total picks each appeared twice, once
    # correctly typed and once as a "betting card" prop with the team/line
    # text wrongly standing in for a player name. Cards whose market is
    # unknown (no "market" field, e.g. sports whose card builder hasn't
    # been updated to expose it) pass through unfiltered -- unchanged,
    # pre-existing behavior for them.
    cards = [card for card in cards if not _is_game_level_rank_card_market(card.get("market"))]
    if not cards:
        return []
    fallback_href = None
    if route_path:
        if slug in {"nfl", "ncaaf"} and week is not None:
            fallback_href = f"{route_path}?week={int(week)}"
        elif resolved_date:
            fallback_href = f"{route_path}?date={resolved_date}"
        else:
            fallback_href = route_path
    return _prop_rows_from_rank_cards(cards, sport_slug=slug, fallback_href=fallback_href, limit=limit, heading_override="Betting Card")


def _interleave_rows(*groups: list[dict[str, Any]], limit: int = 18) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    positions = [0 for _ in groups]
    while len(merged) < limit:
        advanced = False
        for index, group in enumerate(groups):
            if positions[index] >= len(group):
                continue
            merged.append(group[positions[index]])
            positions[index] += 1
            advanced = True
            if len(merged) >= limit:
                break
        if not advanced:
            break
    return merged


def _prop_rows_from_nhl_cards(cards: list[dict[str, Any]], *, fallback_href: str | None = None, limit: int = 18) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        player = _safe_text(card.get("player"), "NHL prop")
        side = _safe_text(card.get("side"), "Play")
        line = _score_value(card.get("line")) or _safe_text(card.get("line"), "-")
        market = _safe_text(card.get("market"), "Market")
        team = _safe_text(card.get("team"), "Team")
        opp = _safe_text(card.get("opp"), "Opp")
        prob = _numeric_value(card.get("prob"))
        prob_text = f"{prob * 100:.1f}% win" if prob is not None else _safe_text(card.get("tracking_note"), "Tracked")
        rows.append(
            {
                "matchup": f"{team} vs {opp}",
                "heading": "Live props",
                "name": player,
                "photo": str(card.get("headshot_url") or "").strip() or None,
                "headshot_url": str(card.get("headshot_url") or "").strip() or None,
                "is_live": True,
                "market": market,
                "pick": side,
                "detail": f"{side} {line} {market} | {_safe_text(card.get('reason_summary'), 'No stored prop summary available.')}",
                "value": prob_text,
                "projected": _prop_metric_text(card.get("projection") if card.get("projection") is not None else card.get("mean")),
                "line": line,
                "odds": _prop_metric_text(card.get("odds") if card.get("odds") is not None else card.get("price")),
                "edge": _pct_text(card.get("edge") if card.get("edge") is not None else card.get("ev")),
                "confidence": prob_text,
                "away_label": team,
                "home_label": opp,
                "away_logo": str(card.get("team_logo") or "").strip() or None,
                "home_logo": str(card.get("opp_logo") or "").strip() or None,
                "href": fallback_href,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _prop_rows_from_mlb_live_games(games: list[dict[str, Any]], *, limit: int = 18) -> list[dict[str, Any]]:
    from syndicate.features.mlb.cards import _mlb_headshot_url

    candidates: list[tuple[tuple[int, float, float], dict[str, Any]]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        matchup = _sport_matchup(game)
        href = str(game.get("href") or "").strip() or None
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        live_props = game.get("liveProps") if isinstance(game.get("liveProps"), list) else []
        archived_props = game.get("archivedLiveProps") if isinstance(game.get("archivedLiveProps"), list) else []
        for prop in [value for value in [*live_props, *archived_props] if isinstance(value, dict)]:
            selection = str(prop.get("selection") or "").strip().title()
            line = _score_value(prop.get("line")) or _safe_text(prop.get("line"), "-")
            market = _safe_text(prop.get("marketLabel") or prop.get("market"), "Market")
            player = _safe_text(prop.get("playerName"), "MLB prop")
            player_id = _int_or_none(
                prop.get("playerId")
                or prop.get("player_id")
                or prop.get("batterId")
                or prop.get("batter_id")
                or prop.get("pitcherId")
                or prop.get("pitcher_id")
            )
            headshot_url = prop.get("headshotUrl") or prop.get("headshot_url") or prop.get("playerPhoto") or prop.get("photo") or _mlb_headshot_url(player_id)
            probability = _numeric_value(prop.get("estimatedWinProb"))
            if probability is None and str(prop.get("selection") or "").strip().lower() == "over":
                probability = _numeric_value(prop.get("modelProbOver"))
            value = f"{probability * 100:.1f}% win" if probability is not None else _safe_text(prop.get("odds"), "Live")
            row = {
                "game_pk": _int_or_none(game.get("gamePk") or game.get("game_pk")),
                "matchup": matchup,
                "heading": "Live props",
                "name": player,
                "player_name": player,
                "player_id": player_id,
                "photo": headshot_url,
                "headshot_url": headshot_url,
                "is_live": True,
                "market": market,
                "pick": selection,
                "detail": f"{selection} {line} {market}",
                "value": value,
                "actual": _prop_metric_text(prop.get("actual") if prop.get("actual") is not None else prop.get("actual_value") if prop.get("actual_value") is not None else prop.get("actualValue")),
                "projected": _prop_metric_text(prop.get("modelMean") if prop.get("modelMean") is not None else prop.get("liveProjection")),
                "live_projection": _prop_metric_text(prop.get("liveProjection") if prop.get("liveProjection") is not None else prop.get("modelMean")),
                "line": _prop_metric_text(prop.get("line")),
                "odds": _prop_metric_text(prop.get("odds")),
                "edge": _pct_text(prop.get("estimatedEdge") if prop.get("estimatedEdge") is not None else prop.get("ev")),
                "confidence": _pct_text(probability),
                "game_state": _safe_text(prop.get("status") or prop.get("gameState") or game.get("status"), None),
                "away_label": _safe_text(away.get("abbr") or away.get("name"), None),
                "home_label": _safe_text(home.get("abbr") or home.get("name"), None),
                "away_logo": _safe_text(away.get("logo") or away.get("teamLogo"), None),
                "home_logo": _safe_text(home.get("logo") or home.get("teamLogo"), None),
                "href": href,
            }
            rank = (
                _mlb_prop_state_rank(game, prop),
                _parse_timestamp_epoch(prop.get("lastSeenAt") or prop.get("firstSeenAt")),
                float(probability or 0.0),
            )
            candidates.append((rank, row))
    rows = [row for _, row in sorted(candidates, key=lambda item: item[0], reverse=True)[:limit]]
    return rows


def _prop_rows_from_nba_live_lens(
    games: list[dict[str, Any]],
    *,
    sport_slug: str,
    fallback_href: str | None = None,
    limit: int = 18,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidates: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        status = game.get("status") if isinstance(game.get("status"), dict) else {}
        away_label = _game_team_label(game, "away") or "Away"
        home_label = _game_team_label(game, "home") or "Home"
        matchup = f"{away_label} @ {home_label}"
        for row in game.get("rows") if isinstance(game.get("rows"), list) else []:
            if not isinstance(row, dict):
                continue
            score = _numeric_value(row.get("recommendation_priority_score"))
            if score is None:
                score = _numeric_value(row.get("bettable_score"))
                if score is not None:
                    score *= 100.0
            if score is None:
                score = _numeric_value(row.get("strength")) or 0.0
            payload = dict(row)
            payload["__matchup"] = matchup
            payload["__status"] = status
            candidates.append((score, game, payload))
    for _, game, row in sorted(candidates, key=lambda item: item[0], reverse=True):
        status = row.get("__status") if isinstance(row.get("__status"), dict) else {}
        status_bits = []
        period = status.get("period")
        clock = str(status.get("clock") or "").strip()
        if period not in {None, ""}:
            status_bits.append(f"Q{period}")
        if clock:
            status_bits.append(clock)
        heading = " | ".join(status_bits) if status_bits else "Live props"
        # Was hardcoded True on every row this function returns, regardless
        # of the period/clock/in_progress evidence computed just above --
        # confirmed live 2026-07-22 on WNBA: a pregame prop row (its own
        # feed hadn't picked up the game going live yet) still claimed
        # is_live=True, which then let its pregame scheduled-tip status
        # text ("6:30 PM CT"/"7/22 - 7:30 PM EDT") pass straight through as
        # if it were live game state. Only claim live when the underlying
        # status evidence actually says so.
        row_is_live = bool(status.get("in_progress")) or bool(status_bits)
        player = _safe_text(row.get("player"), "NBA prop")
        team = _safe_text(row.get("team_tri"), "Team")
        away_label = _game_team_label(game, "away") or "Away"
        home_label = _game_team_label(game, "home") or "Home"
        opponent = _safe_text(row.get("opponent_tri"), None)
        market_label = _display_prop_market_label(row.get("stat"))
        resolved_player_id = _basketball_resolve_player_id(
            sport_slug,
            player_name=player,
            team_tri=team,
            player_id=row.get("player_id"),
        )
        headshot_url = _basketball_best_headshot_url(
            player_id=resolved_player_id,
            photo=row.get("player_photo") or row.get("photo") or row.get("headshot_url"),
        )
        side = _safe_text(row.get("lean") or row.get("ev_side"), "Watch")
        line = _score_value(row.get("line_live") if row.get("line_live") is not None else row.get("line")) or _safe_text(row.get("line"), "-")
        market = _safe_text(row.get("stat"), "Market")
        probability = _pct_text(row.get("win_prob") or row.get("live_rank_probability"))
        ev_pct = _pct_text(row.get("ev"))
        value = probability or (f"EV {ev_pct}" if ev_pct else _safe_text(row.get("klass"), "Watch"))
        projected = _prop_metric_text(row.get("sim_mu") if row.get("sim_mu") is not None else row.get("sim_mu_adjusted"))
        live_projection = _prop_metric_text(
            row.get("live_projection")
            if row.get("live_projection") is not None
            else (row.get("liveProjection") if row.get("liveProjection") is not None else row.get("sim_mu_adjusted") if row.get("sim_mu_adjusted") is not None else row.get("sim_mu"))
        )
        rows.append(
            {
                "matchup": str(row.get("__matchup") or "").strip() or _sport_matchup(game),
                "heading": heading,
                "name": player,
                "player_name": player,
                "is_live": row_is_live,
                "market": market,
                "pick": side,
                "detail": f"{side} {line} {market_label} | {_safe_text(row.get('basketball_summary') or row.get('shape_summary'), 'Live prop signal')}",
                "value": value,
                "actual": _prop_metric_text(row.get("actual")),
                "projected": projected,
                "live_projection": live_projection,
                "line": _prop_metric_text(row.get("line_live") if row.get("line_live") is not None else row.get("line")),
                "odds": _prop_metric_text(
                    row.get("odds_live")
                    if row.get("odds_live") is not None
                    else (row.get("price") if row.get("price") is not None else row.get("odds"))
                ),
                "edge": _pct_text(
                    row.get("live_edge")
                    if row.get("live_edge") is not None
                    else (row.get("liveEdge") if row.get("liveEdge") is not None else row.get("ev") if row.get("ev") is not None else row.get("edge"))
                ),
                "confidence": probability,
                # Was `... else row.get("status_label") or "Live"` -- when
                # there's no real period/clock, status_label is often just
                # a pregame scheduled-tip string (see row_is_live above),
                # and the "Live" literal fallback was misleading for a row
                # that isn't actually live. Only ever show real live text
                # (status_bits) or the row's own status_label when we know
                # this row is genuinely live; otherwise leave it unset.
                "game_state": (
                    _safe_text(status_bits[-1] if status_bits else row.get("status_label"), None)
                    if row_is_live
                    else None
                ),
                "team": team,
                "opponent": opponent,
                "away_label": away_label,
                "home_label": home_label,
                "away_logo": _logo_from_team_label(sport_slug, away_label),
                "home_logo": _logo_from_team_label(sport_slug, home_label),
                "player_id": resolved_player_id,
                "photo": headshot_url,
                "headshot_url": headshot_url,
                "href": fallback_href or (str(game.get("href") or "").strip() or None),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _opponent_abbr_by_team(home_games: list[dict[str, Any]] | None) -> dict[str, str]:
    # The props_recommendations CSV has no opponent column at all (confirmed
    # live 2026-08-02: its header is player/team/plays/ladders/.../top_play*,
    # no "opponent"/"opp" field on any row or inside the parsed top_play
    # dict) -- so _prop_rows_from_props_recommendations_csv's rows could
    # never populate "home_label", which _backfill_prop_row_game_id requires
    # alongside "away_label" to stamp a real game_id/event_id onto a CSV
    # row. Derive it the same way home_games itself is already keyed
    # (away_tri/home_tri or away.abbr/home.abbr) rather than trusting a
    # column that doesn't exist in this artifact.
    mapping: dict[str, str] = {}
    for game in home_games or []:
        if not isinstance(game, dict):
            continue
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        away_abbr = _safe_text(game.get("away_tri") or away.get("abbr"), "").upper()
        home_abbr = _safe_text(game.get("home_tri") or home.get("abbr"), "").upper()
        if away_abbr and home_abbr:
            mapping[away_abbr] = home_abbr
            mapping[home_abbr] = away_abbr
    return mapping


def _prop_rows_from_props_recommendations_csv(
    slug: str,
    *,
    context_label: str,
    fallback_href: str | None = None,
    limit: int = 18,
    home_games: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    sport_slug = str(slug or "").strip().lower()
    if sport_slug not in {"nba", "wnba"}:
        return []
    opponent_by_team = _opponent_abbr_by_team(home_games)

    try:
        if sport_slug == "nba":
            from syndicate.features.nba.sources import processed_path
        else:
            from syndicate.features.wnba.sources import processed_path

        csv_path = processed_path(f"props_recommendations_{context_label}.csv")
    except Exception:
        return []

    if not csv_path.exists():
        return []

    rows: list[dict[str, Any]] = []
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                if not isinstance(raw, dict):
                    continue
                player = _safe_text(raw.get("player"), "Prop")
                if player == "Prop":
                    continue
                team = _safe_text(raw.get("team"), "Team")
                top_play_raw = str(raw.get("top_play") or "").strip()
                if not top_play_raw:
                    continue
                try:
                    top_play = ast.literal_eval(top_play_raw)
                except Exception:
                    continue
                if not isinstance(top_play, dict):
                    continue
                market = _safe_text(top_play.get("market"), "Market").upper()
                side = _safe_text(top_play.get("side"), "Watch")
                line_text = _prop_metric_text(top_play.get("line"))
                summary = _safe_text(raw.get("top_play_explain") or raw.get("top_play_baseline"), "Top prop recommendation")
                ev_pct = _numeric_value(top_play.get("ev_pct"))
                edge_text = _pct_text(top_play.get("ev") if top_play.get("ev") is not None else top_play.get("edge"))
                opponent_abbr = opponent_by_team.get(team.upper(), "")
                rows.append(
                    {
                        "team": team,
                        "opponent": _safe_text(raw.get("opponent") or raw.get("opp"), "") or opponent_abbr,
                        "away_label": team,
                        "home_label": opponent_abbr,
                        "matchup": _safe_text(raw.get("matchup") or team, team),
                        "heading": "Props",
                        "name": f"{player} ({team})",
                        "is_live": False,
                        "market": market,
                        "pick": side,
                        "detail": f"{side} {line_text} {market} | {summary}",
                        "value": f"EV {ev_pct:.1f}%" if ev_pct is not None else edge_text,
                        "projected": _prop_metric_text(raw.get("top_play_baseline")),
                        "line": line_text,
                        "odds": _prop_metric_text(top_play.get("price")),
                        "edge": edge_text,
                        "confidence": _safe_text(raw.get("top_play_consensus"), "Model"),
                        "href": fallback_href or f"/{sport_slug}/props?date={context_label}",
                    }
                )
                if len(rows) >= limit:
                    break
    except Exception:
        return []

    return rows


def _compact_game_items_from_nhl_live_payload(games: list[dict[str, Any]], *, selected_date: str, limit: int | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        score = game.get("score") if isinstance(game.get("score"), dict) else {}
        guidance = game.get("guidance") if isinstance(game.get("guidance"), dict) else {}
        signals = game.get("signals") if isinstance(game.get("signals"), list) else []
        state = str(game.get("gameState") or "").strip().upper()
        period = game.get("period")
        clock = str(game.get("clock") or "").strip()
        detail_bits = []
        if state:
            detail_bits.append(state)
        if period not in {None, ""}:
            detail_bits.append(f"P{period}")
        if clock:
            detail_bits.append(clock)
        signal_values: list[str] = []
        for signal in signals[:3]:
            if not isinstance(signal, dict):
                continue
            label = _safe_text(signal.get("label"), "Signal")
            action = str(signal.get("action") or "").strip()
            market = str(signal.get("market") or "").strip().replace("_", " ").title()
            parts = [label]
            if action:
                parts.append(action)
            if market:
                parts.append(market)
            signal_values.append(" | ".join(parts))
        chip_values: list[str] = []
        lean_total = str(guidance.get("lean_total") or "").strip().lower()
        if lean_total and lean_total != "neutral":
            chip_values.append(f"Total lean {lean_total.title()}")
        live_total_line = _score_value(guidance.get("live_total_line"))
        if live_total_line:
            chip_values.append(f"Live total {live_total_line}")
        total_goals = _score_value(guidance.get("total_goals"))
        if total_goals:
            chip_values.append(f"Goals {total_goals}")
        away_score = _score_value(score.get("away"))
        home_score = _score_value(score.get("home"))
        items.append(
            {
                "matchup": f"{_safe_text(game.get('away'), 'Away')} @ {_safe_text(game.get('home'), 'Home')}",
                "detail": " | ".join(detail_bits) if detail_bits else selected_date,
                "status_badge": "Live" if state in {"LIVE", "CRIT"} else "Final" if state == "OFF" else "Tracked",
                "away_label": _safe_text(game.get("away"), "Away"),
                "home_label": _safe_text(game.get("home"), "Home"),
                "away_score": away_score,
                "home_score": home_score,
                "has_scores": bool(away_score and home_score),
                "score_kind": "Live score" if state in {"LIVE", "CRIT"} else "Final score" if state == "OFF" else None,
                "is_projected_score": False,
                "summary": _safe_text((guidance.get("notes") or [None])[0], "No live lens summary available."),
                "signals": signal_values,
                "market_chips": chip_values,
                "href": f"/nhl/game/{str(game.get('gamePk') or '').strip()}?date={selected_date}" if str(game.get("gamePk") or "").strip() else f"/nhl/live-lens?date={selected_date}",
                "href_label": "Open game detail",
            }
        )
        if limit is not None and len(items) >= limit:
            break
    return items


def _home_games_have_live_action(home_games: list[dict[str, Any]] | None) -> bool:
    for game in home_games or []:
        if not isinstance(game, dict):
            continue
        scoreboard = _scoreboard_state(game)
        if _is_liveish(scoreboard.get("status_badge"), scoreboard.get("status_line")):
            return True
    return False


def _load_home_pregame_prop_items(
    slug: str,
    *,
    context_label: str,
    home_games: list[dict[str, Any]],
    season: int | None = None,
    week: int | None = None,
    is_active_today: bool,
) -> list[dict[str, Any]]:
    provider = get_sport_data_provider(slug)
    if provider is None:
        return []
    context = provider.resolve_context(requested_date=context_label, season=season, week=week)
    try:
        return provider.pregame_props(context, home_games, is_active_today=is_active_today)
    except Exception:
        return []


# Sports with a real live-prop data source below (mlb/nhl/nba/wnba). NFL/
# NCAAF/NCAAB have no branch here (falls through to []) so their
# live_odds_game_ids must never be built from live_prop_items -- an empty
# set from a sport with no source at all is indistinguishable from "checked,
# nothing live right now," and treating it as the latter forces is_live to
# False for every genuinely-live game of those three sports. See
# _live_odds_backed_live_flag()'s None-vs-empty-set handling.
_LIVE_PROP_SOURCED_SPORTS = {"mlb", "nba", "nhl", "wnba"}


def _load_home_live_prop_items(
    slug: str,
    *,
    context_label: str,
    home_games: list[dict[str, Any]],
    season: int | None = None,
    week: int | None = None,
    is_active_today: bool,
) -> list[dict[str, Any]]:
    provider = get_sport_data_provider(slug)
    if provider is None:
        return []
    context = provider.resolve_context(requested_date=context_label, season=season, week=week)
    try:
        return provider.live_props(context, home_games, is_active_today=is_active_today)
    except Exception:
        return []


class _HomeSportDataProviderBase:
    """Shared, uniform bits of SportDataProvider every home.py adapter
    below reuses verbatim -- date/week packaging and the manifest-backed
    data_sources() diagnostic. See syndicate/features/shared/sport_data_provider.py
    for the protocol these implement (duck-typed, not subclassed from it)."""

    slug: str = ""

    def resolve_context(
        self,
        *,
        requested_date: str | None = None,
        season: int | None = None,
        week: int | None = None,
    ) -> SportContext:
        return SportContext(slug=self.slug, context_label=str(requested_date or ""), season=season, week=week)

    def data_sources(self, context: SportContext) -> dict[str, Any]:
        return {"manifest": sport_manifest_signature(self.slug)}


class _MLBDataProvider(_HomeSportDataProviderBase):
    slug = "mlb"

    def is_active(self, *, today_value: str, context_label: str) -> bool:
        return context_label == today_value

    def games(self, context: SportContext, *, is_active_today: bool) -> list[dict[str, Any]]:
        from syndicate.features.mlb.cards import build_cards_page_context
        from syndicate.features.mlb.cards import _enrich_games_with_tracked_market_lines

        payload = build_cards_page_context(context.context_label)
        games = list(payload.get("games") or [])
        # Board audit, found live 2026-07-31: without this, markets["ml"/
        # "totals"] only ever carries real odds for games the recommendation
        # engine happened to flag -- every other game's Layer 2 Moneyline/
        # Total candidate showed odds=null despite real market odds existing
        # in production right now. Layer 1's market board already backfills
        # from this same odds artifact (source_cards_api_payload); this is
        # that identical enrichment, reused rather than duplicated inline.
        games = _enrich_games_with_tracked_market_lines(games, context.context_label)
        for game in games:
            if isinstance(game, dict) and not game.get("game_market_recommendations"):
                rows = _mlb_game_market_recommendation_rows(game)
                if rows:
                    game["game_market_recommendations"] = rows
        return _apply_mlb_live_scores(games, context.context_label) if is_active_today else games

    def pregame_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        mlb_rows = _pregame_prop_rows_from_betting_card("mlb", context_label=context.context_label, season=context.season, week=context.week)
        if not mlb_rows:
            mlb_rows = _load_mlb_home_top_prop_items(context.context_label)
        if not mlb_rows:
            mlb_rows = _compact_prop_rows(home_games)
        # _load_mlb_home_hr_target_items was a complete, working home-page
        # HR-targets adapter that nothing ever called -- dead code, so HR
        # targets never reached the board despite the artifact existing and
        # being current. HR targets are a distinct market from whatever's
        # already in mlb_rows above (betting-card props, top props, or the
        # compact fallback), so they're additive here, not another rung in
        # the same fallback chain.
        hr_target_rows = _load_mlb_home_hr_target_items(context.context_label)
        if hr_target_rows:
            return list(mlb_rows) + hr_target_rows
        return mlb_rows

    def live_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        if not is_active_today:
            return []
        from syndicate.features.mlb.live_lens import read_latest_live_lens_page_context

        live_games = list(read_latest_live_lens_page_context(context.context_label).get("games") or [])
        live_games = [game for game in live_games if isinstance(game, dict)]
        if not live_games:
            return []
        liveish_games = [
            game
            for game in live_games
            if _is_liveish(*(_scoreboard_state(game).get(key) for key in ["status_badge", "status_line"]))
        ]
        prop_backed_games = [
            game
            for game in (liveish_games or live_games)
            if isinstance(game.get("liveProps"), list) or isinstance(game.get("archivedLiveProps"), list)
        ]
        return _prop_rows_from_mlb_live_games(prop_backed_games)


class _NBADataProvider(_HomeSportDataProviderBase):
    slug = "nba"

    def is_active(self, *, today_value: str, context_label: str) -> bool:
        return context_label == today_value

    def games(self, context: SportContext, *, is_active_today: bool) -> list[dict[str, Any]]:
        from syndicate.features.nba.cards import build_cards_page_context

        payload = build_cards_page_context(context.context_label, allow_stored_date_fallback=_allow_stored_date_fallback())
        games = list(payload.get("games") or [])
        if is_active_today and not games:
            games = _nba_live_state_games(context.context_label)
        return _apply_nba_live_scores(games, context.context_label) if is_active_today else games

    def pregame_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        nba_rows = _pregame_prop_rows_from_betting_card("nba", context_label=context.context_label, season=context.season, week=context.week)
        if nba_rows:
            return nba_rows
        csv_rows = _prop_rows_from_props_recommendations_csv(
            "nba", context_label=context.context_label, fallback_href=f"/nba/cards?date={context.context_label}", home_games=home_games
        )
        if csv_rows:
            return _backfill_prop_row_game_id(csv_rows, home_games)
        return _compact_prop_rows(home_games)

    def live_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        if not is_active_today:
            return []
        if not _home_games_have_live_action(home_games):
            return []
        from syndicate.features.nba.cards import build_live_player_lens_payload
        from syndicate.features.nba.cards import build_live_state_payload

        live_state = build_live_state_payload(context.context_label, ttl=12)
        event_ids = [
            str((game or {}).get("event_id") or "").strip()
            for game in (live_state.get("games") if isinstance(live_state.get("games"), list) else [])
            if str((game or {}).get("event_id") or "").strip()
        ]
        if not event_ids:
            return []
        payload = build_live_player_lens_payload(context.context_label, event_ids, ttl=20)
        return _prop_rows_from_nba_live_lens(
            list(payload.get("games") or []),
            sport_slug="nba",
            fallback_href=f"/nba/live-lens?date={context.context_label}",
        )


class _WNBADataProvider(_HomeSportDataProviderBase):
    slug = "wnba"

    def is_active(self, *, today_value: str, context_label: str) -> bool:
        return context_label == today_value

    def games(self, context: SportContext, *, is_active_today: bool) -> list[dict[str, Any]]:
        from syndicate.features.wnba.cards import build_cards_page_context

        payload = build_cards_page_context(context.context_label, allow_stored_date_fallback=False)
        source_title = _safe_text(payload.get("source_title"), "")
        source_path = _safe_text(payload.get("source_path"), "")
        games = list(payload.get("games") or [])
        if is_active_today and not get_active_games(games):
            live_games = _wnba_live_state_games(context.context_label)
            if live_games:
                games = live_games
                source_title = "WNBA live-state artifact fallback"
                source_path = f"live_state_{context.context_label}.jsonl"
        if has_app_context():
            current_app.logger.info(
                "WNBA cards payload for %s: source_title=%s source_path=%s games=%s requested_date=%s date=%s",
                context.context_label,
                source_title or "<empty>",
                source_path or "<empty>",
                len(games),
                _safe_text(payload.get("requested_date"), ""),
                _safe_text(payload.get("date"), ""),
            )
        return _apply_wnba_live_scores(games, context.context_label) if is_active_today else games

    def pregame_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        wnba_rows = _pregame_prop_rows_from_betting_card("wnba", context_label=context.context_label, season=context.season, week=context.week)
        if wnba_rows:
            return _backfill_prop_row_game_id(wnba_rows, home_games)
        csv_rows = _prop_rows_from_props_recommendations_csv(
            "wnba", context_label=context.context_label, fallback_href=f"/wnba/cards?date={context.context_label}", home_games=home_games
        )
        if csv_rows:
            return _backfill_prop_row_game_id(csv_rows, home_games)
        return _compact_prop_rows(home_games)

    def live_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        if not is_active_today:
            return []
        if not _home_games_have_live_action(home_games):
            return []
        from syndicate.features.wnba.cards import build_live_player_lens_payload
        from syndicate.features.wnba.cards import build_live_state_payload

        live_state = build_live_state_payload(context.context_label, ttl=12)
        event_ids = [
            str((game or {}).get("event_id") or "").strip()
            for game in (live_state.get("games") if isinstance(live_state.get("games"), list) else [])
            if str((game or {}).get("event_id") or "").strip()
        ]
        if not event_ids:
            return []
        payload = build_live_player_lens_payload(context.context_label, event_ids, ttl=20)
        return _prop_rows_from_nba_live_lens(
            list(payload.get("games") or []),
            sport_slug="wnba",
            fallback_href=f"/wnba/live-lens?date={context.context_label}",
        )


class _NHLDataProvider(_HomeSportDataProviderBase):
    slug = "nhl"

    def is_active(self, *, today_value: str, context_label: str) -> bool:
        return context_label == today_value

    def games(self, context: SportContext, *, is_active_today: bool) -> list[dict[str, Any]]:
        from syndicate.features.nhl.cards import build_cards_page_context

        payload = build_cards_page_context(context.context_label)
        if (
            str(payload.get("requested_date") or context.context_label).strip() == str(context.context_label).strip()
            and str(payload.get("date") or context.context_label).strip() != str(context.context_label).strip()
        ):
            return []
        games = list(payload.get("games") or [])
        return _apply_nhl_live_scores(games, context.context_label) if is_active_today else games

    def pregame_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        betting_rows = _pregame_prop_rows_from_betting_card("nhl", context_label=context.context_label, season=context.season, week=context.week)
        if betting_rows:
            return betting_rows
        return _compact_prop_rows(home_games)

    def live_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        if not is_active_today:
            return []
        if not _home_games_have_live_action(home_games):
            return []
        # NOTE: this is still static pregame player-prop data, cosmetically
        # labeled "live" whenever a game happens to be in progress -- a
        # real, known bug (see the "Betting Board Reinvention" project
        # notes). nhl/live_lens.py's build_live_lens_page_context looked
        # like the fix (same rank_cards shape every other live-lens path
        # uses) but its cards are per-GAME analysis (moneyline/total/margin
        # for the matchup, consumed elsewhere via
        # _compact_game_items_from_rank_cards) -- not per-player props, so
        # routing them through _prop_rows_from_rank_cards (which expects a
        # player name/team/market/line) would mislabel game data as player
        # picks, the exact "inconsistent labeling" bug this migration is
        # trying to reduce, not add to. Left as the original source until
        # NHL has a genuine live player-prop feed to wire in instead.
        from syndicate.features.nhl.cards import build_props_cards_payload

        payload = build_props_cards_payload(context.context_label, top=18)
        return _prop_rows_from_nhl_cards(
            list(payload.get("cards") or []),
            fallback_href=f"/nhl/cards?date={payload.get('date') or context.context_label}",
        )


class _NCAABDataProvider(_HomeSportDataProviderBase):
    slug = "ncaab"

    def is_active(self, *, today_value: str, context_label: str) -> bool:
        return context_label == today_value

    def games(self, context: SportContext, *, is_active_today: bool) -> list[dict[str, Any]]:
        from syndicate.features.ncaab.cards import build_cards_page_context

        payload = build_cards_page_context(context.context_label)
        if (
            str(payload.get("requested_date") or context.context_label).strip() == str(context.context_label).strip()
            and str(payload.get("date") or context.context_label).strip() != str(context.context_label).strip()
        ):
            return []
        return list(payload.get("games") or [])

    def pregame_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        betting_rows = _pregame_prop_rows_from_betting_card("ncaab", context_label=context.context_label, season=context.season, week=context.week)
        if betting_rows:
            return betting_rows
        return _compact_prop_rows(home_games)

    def live_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        # No branch here has ever existed. _load_home_game_items already
        # reads ncaab/live_lens.py's build_live_lens_page_context for the
        # compact GAME rail, but its rank_cards are per-game analysis
        # (moneyline/total/margin for the matchup), not per-player props --
        # routing them through _prop_rows_from_rank_cards would mislabel
        # game data as player picks. NCAAB has no genuine live player-prop
        # feed to wire in here yet.
        return []


class _NFLDataProvider(_HomeSportDataProviderBase):
    slug = "nfl"

    def is_active(self, *, today_value: str, context_label: str) -> bool:
        return _football_in_season(today_value)

    def games(self, context: SportContext, *, is_active_today: bool) -> list[dict[str, Any]]:
        # Regular season and preseason never overlap on the calendar, so
        # this gates on season phase and returns ONE or the other, never a
        # merge of both -- merging two different schedules' games into one
        # list risks game_id collisions / card-shape mismatches. Also
        # stamps game_market_recommendations from the real Layer 1 market
        # board (build_nfl_market_board / build_nfl_preseason_market_board)
        # onto each game, the same read-time translation
        # _MLBDataProvider.games() already does for MLB below -- without
        # it, neither regular-season nor preseason NFL games ever reached
        # the cross-sport Layer 2 opportunity feed.
        def _stamp_market_recommendations(games_list: list[dict[str, Any]], board_games: list[dict[str, Any]]) -> list[dict[str, Any]]:
            rows_by_game_id = {str(board_game.get("gamePk") or ""): board_game.get("rows") or [] for board_game in board_games if isinstance(board_game, dict)}
            for game in games_list:
                if isinstance(game, dict) and not game.get("game_market_recommendations"):
                    game_id = str(game.get("gamePk") or "")
                    board_rows = rows_by_game_id.get(game_id)
                    if board_rows:
                        rows = _nfl_game_market_recommendation_rows(game_id, board_rows)
                        if rows:
                            game["game_market_recommendations"] = rows
            return games_list

        if context.week is not None:
            from syndicate.features.nfl.cards import build_cards_page_context
            from syndicate.features.nfl.cards import build_nfl_market_board

            week = int(context.week)
            season = int(context.season) if context.season is not None else nfl_latest_season()
            games = list(build_cards_page_context(week, season=context.season).get("games") or [])
            try:
                board_games = list(build_nfl_market_board(season, week).get("games") or [])
            except Exception:
                board_games = []
            return _stamp_market_recommendations(games, board_games)

        from syndicate.features.nfl.preseason_cards import build_nfl_preseason_market_board
        from syndicate.features.nfl.preseason_cards import build_preseason_cards_page_context
        from syndicate.features.nfl.sources import preseason_target_week

        season = int(context.season) if context.season is not None else nfl_latest_season()
        target_week = preseason_target_week(season)
        if target_week is None:
            return []
        games = list(build_preseason_cards_page_context(target_week, season=season).get("games") or [])
        try:
            board_games = list(build_nfl_preseason_market_board(season, target_week).get("games") or [])
        except Exception:
            board_games = []
        return _stamp_market_recommendations(games, board_games)

    def pregame_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        if not is_active_today:
            return []
        betting_rows = _pregame_prop_rows_from_betting_card("nfl", context_label=context.context_label, season=context.season, week=context.week)
        if betting_rows:
            return betting_rows
        return _compact_prop_rows(home_games)

    def live_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        # No branch here has ever existed. Same reasoning as NCAAB's
        # live_props: nfl/live_lens.py's build_live_lens_page_context is a
        # real live source, but its rank_cards are per-game analysis, not
        # per-player props -- no genuine live player-prop feed to wire in
        # here yet without mislabeling game data as picks.
        return []


class _NCAAFDataProvider(_HomeSportDataProviderBase):
    slug = "ncaaf"

    def is_active(self, *, today_value: str, context_label: str) -> bool:
        return _football_in_season(today_value)

    def games(self, context: SportContext, *, is_active_today: bool) -> list[dict[str, Any]]:
        # Layer 2 fix, mirrors _NFLDataProvider.games(): switched from
        # build_cards_page_context (a stale/historical saved-summary
        # snapshot path) to build_smartsim_cards_page_context, the real
        # current-slate path /ncaaf/cards itself renders through --
        # build_ncaaf_market_board internally uses the same
        # build_smartsim_cards_page_context path, and the two pipelines
        # (saved summary vs. real current slate) produce different gamePk
        # values in practice, so a join against the old source would have
        # silently produced zero recommendations. Also stamps
        # game_market_recommendations from the real Layer 1 market board,
        # the same read-time translation _NFLDataProvider.games() already
        # does for NFL. Single always-regular-season path: NCAAF has no
        # preseason concept, so no phase branch is needed here (unlike
        # NFL's regular-season/preseason split above).
        if context.week is None:
            return []
        from syndicate.features.ncaaf.cards import build_ncaaf_market_board
        from syndicate.features.ncaaf.cards import build_smartsim_cards_page_context

        games = list(build_smartsim_cards_page_context(context.week).get("games") or [])
        try:
            board_games = list(build_ncaaf_market_board(context.week).get("games") or [])
        except Exception:
            board_games = []
        rows_by_game_id = {str(board_game.get("gamePk") or ""): board_game.get("rows") or [] for board_game in board_games if isinstance(board_game, dict)}
        for game in games:
            if isinstance(game, dict) and not game.get("game_market_recommendations"):
                game_id = str(game.get("gamePk") or "")
                board_rows = rows_by_game_id.get(game_id)
                if board_rows:
                    rows = _ncaaf_game_market_recommendation_rows(game_id, board_rows)
                    if rows:
                        game["game_market_recommendations"] = rows
        return games

    def pregame_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        if not is_active_today:
            return []
        betting_rows = _pregame_prop_rows_from_betting_card("ncaaf", context_label=context.context_label, season=context.season, week=context.week)
        if betting_rows:
            return betting_rows
        return _compact_prop_rows(home_games)

    def live_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        # No branch here has ever existed. Same reasoning as NCAAB's
        # live_props: ncaaf/live_lens.py's build_live_lens_page_context is
        # a real live source, but its rank_cards are per-game analysis, not
        # per-player props -- no genuine live player-prop feed to wire in
        # here yet without mislabeling game data as picks.
        return []


class _SoccerDataProvider(_HomeSportDataProviderBase):
    """Soccer is week-keyed per league (like NFL/NCAAF), not date-keyed like
    mlb/nba/nhl/wnba/ncaab, and tracks several leagues at once. games() and
    pregame_props() fan out across EVERY calendar-active league (each with
    its own season/week resolution) -- the earlier single-league resolution
    ("resolve ONE active league per call, preferring MLS") was a deliberate
    migration shortcut, but from 2026-08-14 the European leagues come back
    and five leagues can be live on the same Saturday; a one-league
    provider would silently drop the other four from the Layer 2 board
    (flagged as the highest-severity international-launch gap in the
    2026-08-02 end-to-end assessment). The steam and live-lens paths
    already fan out across active_leagues_for_date; this brings the
    pregame games/props path in line. SportContext still carries a single
    primary league (MLS first, else first active) for labels/links only."""

    slug = "soccer"

    def _active_leagues(self, requested_date: str) -> list[str]:
        from syndicate.features.soccer.sources import DEFAULT_LEAGUE
        from syndicate.features.soccer.sources import active_leagues_for_date

        active = [str(league).strip() for league in active_leagues_for_date(requested_date or central_today_iso()) if str(league).strip()]
        if not active:
            return [DEFAULT_LEAGUE]
        if "mls" in active:
            active.remove("mls")
            active.insert(0, "mls")
        return active

    def _resolve_league(self, requested_date: str) -> str:
        return self._active_leagues(requested_date)[0]

    def _league_season_week(self, league: str, context: SportContext, today: str) -> tuple[int, int]:
        from syndicate.features.soccer.sources import default_season
        from syndicate.features.soccer.sources import default_week

        if league == context.league:
            return int(context.season), int(context.week)
        season = default_season(league)
        return int(season), int(default_week(league, season, reference_date=today))

    def resolve_context(self, *, requested_date: str | None = None, season: int | None = None, week: int | None = None) -> SportContext:
        from syndicate.features.soccer.sources import default_season
        from syndicate.features.soccer.sources import default_week
        from syndicate.features.soccer.sources import league_display_name

        today = str(requested_date or central_today_iso())
        league = self._resolve_league(today)
        resolved_season = int(season) if season else default_season(league)
        resolved_week = int(week) if week else default_week(league, resolved_season, reference_date=today)
        return SportContext(
            slug=self.slug,
            context_label=f"{league_display_name(league)} {resolved_season} Week {resolved_week}",
            season=resolved_season,
            week=resolved_week,
            league=league,
        )

    def is_active(self, *, today_value: str, context_label: str) -> bool:
        from syndicate.features.soccer.sources import active_leagues_for_date

        return bool(active_leagues_for_date(today_value))

    def games(self, context: SportContext, *, is_active_today: bool) -> list[dict[str, Any]]:
        from syndicate.features.soccer.cards import build_cards_page_context

        today = central_today_iso()
        games: list[dict[str, Any]] = []
        for league in self._active_leagues(today):
            # One broken league (missing schedule artifact, bad season roll)
            # must not empty the whole sport -- each league is best-effort.
            try:
                season, week = self._league_season_week(league, context, today)
                payload = build_cards_page_context(league, week, season)
            except Exception as exc:
                print(f"[home] SOCCER_LEAGUE_GAMES_FAILED league={league} error={exc}", flush=True)
                continue
            for game in payload.get("games") or []:
                if isinstance(game, dict):
                    game.setdefault("league", league)
                    games.append(game)
        return games

    def pregame_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        from syndicate.features.soccer.props import build_props_page_context

        today = central_today_iso()
        rows: list[dict[str, Any]] = []
        for league in self._active_leagues(today):
            try:
                season, week = self._league_season_week(league, context, today)
                payload = build_props_page_context(league, week, season)
            except Exception as exc:
                print(f"[home] SOCCER_LEAGUE_PROPS_FAILED league={league} error={exc}", flush=True)
                continue
            cards = list(payload.get("rank_cards") or [])
            if not cards:
                continue
            league_rows = _prop_rows_from_rank_cards(
                cards,
                sport_slug="soccer",
                fallback_href=f"/soccer/{league}/props?week={week}&season={season}",
            )
            # _prop_rows_from_rank_cards never skips a valid dict card (see
            # _prop_item_from_rank_card), so this zip is a true 1:1, order-
            # preserved pairing even when the [:limit] truncation below it
            # kicks in -- see props.py's _prop_rank_card for why match_id is
            # needed at all (soccer's rank-card "meta" carries no away/home
            # matchup text for the usual team-label match to key off of).
            for card, row in zip(cards, league_rows):
                match_id = str(card.get("match_id") or "").strip()
                if match_id:
                    row.setdefault("game_id", match_id)
                    row.setdefault("gamePk", match_id)
                row.setdefault("league", league)
            rows.extend(league_rows)
        if not rows:
            return _compact_prop_rows(home_games)
        return rows

    def live_props(self, context: SportContext, home_games: list[dict[str, Any]], *, is_active_today: bool) -> list[dict[str, Any]]:
        return []

    def data_sources(self, context: SportContext) -> dict[str, Any]:
        sources = super().data_sources(context)
        sources["league"] = context.league
        sources["keying"] = "week-keyed per league, not date-keyed"
        return sources


for _provider in (
    _MLBDataProvider(),
    _NBADataProvider(),
    _WNBADataProvider(),
    _NHLDataProvider(),
    _NCAABDataProvider(),
    _NFLDataProvider(),
    _NCAAFDataProvider(),
    _SoccerDataProvider(),
):
    register_sport_data_provider(_provider)
del _provider


def _mlb_top_prop_rows_from_group(
    summary: dict[str, Any],
    *,
    group_key: str,
    fallback_href: str,
    limit: int,
) -> list[dict[str, Any]]:
    groups = summary.get("groups") if isinstance(summary.get("groups"), dict) else {}
    group = groups.get(group_key) if isinstance(groups.get(group_key), dict) else {}
    sections = group.get("sections") if isinstance(group.get("sections"), list) else []
    heading = "Pitcher top props" if group_key == "pitcher" else "Hitter top props"
    candidates: list[tuple[float, dict[str, Any]]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        values = section.get("rows") if isinstance(section.get("rows"), list) else []
        for value in values:
            if not isinstance(value, dict):
                continue
            probability = _numeric_value(value.get("simProb"))
            edge = _numeric_value(value.get("rawEdge"))
            matchup = _safe_text(value.get("matchup"), "-")
            away_label, home_label = _split_matchup_labels(matchup)
            team_label = str(value.get("team") or "").strip()
            opponent_label = str(value.get("opponent") or "").strip()
            team_logo = str(value.get("teamLogoUrl") or "").strip() or None
            opponent_logo = str(value.get("opponentLogoUrl") or "").strip() or None
            odds_value = _numeric_value(value.get("odds"))
            odds_text = None
            if odds_value is not None:
                odds_int = int(odds_value)
                odds_text = f"+{odds_int}" if odds_int > 0 else str(odds_int)
            selection = _safe_text(value.get("selectionLabel") or value.get("selection"), "Play")
            target_label = str(value.get("targetLabel") or "").strip()
            market = _safe_text(value.get("statLabel") or value.get("stat"), "Market")
            pick = f"{selection} {target_label}".strip()
            candidates.append(
                (
                    float(edge or probability or 0.0),
                    {
                        "game_pk": _int_or_none(value.get("gamePk")),
                        "matchup": matchup,
                        "heading": heading,
                        "name": _safe_text(value.get("playerName") or value.get("ownerName"), "MLB prop"),
                        "player_name": _safe_text(value.get("playerName") or value.get("ownerName"), "MLB prop"),
                        "player_id": _int_or_none(value.get("ownerId") or value.get("playerId")),
                        "photo": str(value.get("headshotUrl") or "").strip() or None,
                        "headshot_url": str(value.get("headshotUrl") or "").strip() or None,
                        "is_live": False,
                        "market": market,
                        "pick": pick,
                        "detail": f"{pick} {market} | {heading}".strip(),
                        "value": f"{probability * 100:.1f}% win" if probability is not None else heading,
                        # 2026-08-01 board audit: team_label/opponent_label
                        # were computed above (used for away_logo/home_logo
                        # matching) but never actually put on the row --
                        # confirmed live, every home-rails prop candidate
                        # downstream (_prop_candidate_from_item reads
                        # item.get("team")/item.get("opponent")) showed a
                        # blank team on the Layer 2 board regardless of a
                        # real team being known right here.
                        "team": team_label or None,
                        "opponent": opponent_label or None,
                        "projected": _prop_metric_text(value.get("mean")),
                        "sim_projection": _prop_metric_text(value.get("mean")),
                        "line": _prop_metric_text(value.get("line")) or _safe_text(value.get("line"), "-"),
                        "odds": odds_text or _prop_metric_text(value.get("odds")),
                        "edge": _pct_text(edge),
                        "confidence": _pct_text(probability),
                        "away_label": away_label,
                        "home_label": home_label,
                        "away_logo": opponent_logo if away_label == opponent_label else team_logo if away_label == team_label else None,
                        "home_logo": team_logo if home_label == team_label else opponent_logo if home_label == opponent_label else None,
                        "href": fallback_href,
                    },
                )
            )
    return [row for _, row in sorted(candidates, key=lambda item: item[0], reverse=True)[:limit]]


def _load_mlb_home_top_prop_items(context_label: str, *, limit: int = 18) -> list[dict[str, Any]]:
    summary = load_json_or_gz_file(daily_top_props_path(context_label))
    if not isinstance(summary, dict):
        return []
    per_group_limit = max(1, limit // 2)
    pitcher_rows = _mlb_top_prop_rows_from_group(
        summary,
        group_key="pitcher",
        fallback_href=f"/mlb/pitcher-top-props?date={context_label}",
        limit=per_group_limit,
    )
    hitter_rows = _mlb_top_prop_rows_from_group(
        summary,
        group_key="hitter",
        fallback_href=f"/mlb/hitter-top-props?date={context_label}",
        limit=per_group_limit,
    )
    return _interleave_rows(pitcher_rows, hitter_rows, limit=limit)


def _load_home_prop_items(
    slug: str,
    *,
    context_label: str,
    home_games: list[dict[str, Any]],
    season: int | None = None,
    week: int | None = None,
    is_active_today: bool,
    lane: str = "combined",
) -> list[dict[str, Any]]:
    lane_key = str(lane or "combined").strip().lower()
    if lane_key == "pregame":
        return _load_home_pregame_prop_items(
            slug,
            context_label=context_label,
            home_games=home_games,
            season=season,
            week=week,
            is_active_today=is_active_today,
        )
    if lane_key == "live":
        return _load_home_live_prop_items(
            slug,
            context_label=context_label,
            home_games=home_games,
            season=season,
            week=week,
            is_active_today=is_active_today,
        )
    if slug in {"nfl", "ncaaf"} and not is_active_today:
        return []
    try:
        live_rows = _load_home_live_prop_items(
            slug,
            context_label=context_label,
            home_games=home_games,
            season=season,
            week=week,
            is_active_today=is_active_today,
        )
        if live_rows:
            return live_rows
        pregame_rows = _load_home_pregame_prop_items(
            slug,
            context_label=context_label,
            home_games=home_games,
            season=season,
            week=week,
            is_active_today=is_active_today,
        )
        if pregame_rows:
            return pregame_rows
    except Exception:
        pass
    rows = _compact_prop_rows(home_games)
    if rows:
        return rows
    return []


_HR_TARGET_SURFACE_LABELS = {"hr targets", "hr target", "hr top 10"}


def _is_hr_target_surface(heading: Any) -> bool:
    """Is this row an HR-propensity pick rather than a lined over/under?

    Settlement branches on this (`_mlb_prop_result_state`): an HR pick has no
    market line at all -- it grades on "did he homer", not against a number --
    so it cannot go through the line-comparison path. This used to be an
    inline equality test against the literal display label "HR targets", which
    meant renaming that surface would silently reroute HR rows into
    line-based settlement and mis-grade every one of them. Matching a set of
    accepted labels keeps the display name free to change.
    """
    return str(heading or "").strip().lower() in _HR_TARGET_SURFACE_LABELS


def _load_mlb_home_hr_target_items(context_label: str, *, limit: int = 10) -> list[dict[str, Any]]:
    try:
        from syndicate.features.mlb.hr_targets import build_hr_targets_page_context

        context = build_hr_targets_page_context(context_label)
        targets = list(context.get("targets") or [])
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for target in targets[:limit]:
        if not isinstance(target, dict):
            continue
        # HR Top 10: lead with the advanced metrics that earned the ranking.
        # `analytics_callouts` is built by hr_targets._hr_analytics_callouts and
        # already sorted strongest-signal-first, with each metric carrying its
        # league/neutral reference; fall back to the old free-text reasons when
        # a row has no Statcast coverage.
        callouts = [c for c in (target.get("analytics_callouts") or []) if isinstance(c, dict)]
        callout_lines = [
            f"{c.get('label')}: {c.get('value')} ({c.get('detail')})" if c.get("detail") else f"{c.get('label')}: {c.get('value')}"
            for c in callouts
        ]
        reasons = callout_lines or [str(item).strip() for item in (target.get("reasons") or []) if str(item).strip()]
        # The single-line `detail` is the rail's one-glance "why him". Take the
        # strongest BOOST rather than the strongest signal outright -- callouts
        # rank by absolute deviation, so a hitter whose biggest mover is a
        # negative would otherwise lead with an argument against his own pick.
        # The full list (drags included) still renders in the expanded row.
        lead = next((c for c in callouts if c.get("tone") == "boost"), None)
        lead_line = (
            (f"{lead.get('label')}: {lead.get('value')} ({lead.get('detail')})" if lead.get("detail")
             else f"{lead.get('label')}: {lead.get('value')}")
            if lead else None
        )
        writeup = str(
            target.get("selection_rationale") or target.get("writeup") or target.get("summary") or ""
        ).strip()
        rank = target.get("hr_rank")
        matchup = _safe_text(target.get("matchup"), "-")
        away_label, home_label = _split_matchup_labels(matchup)
        team_label = _safe_text(target.get("team"), None)
        opponent_label = _safe_text(target.get("opponent"), None)
        team_logo = str(target.get("team_logo_url") or "").strip() or None
        opponent_logo = str(target.get("opponent_logo_url") or "").strip() or None
        away_logo = None
        home_logo = None
        if away_label and home_label and team_label and opponent_label:
            if away_label == team_label and home_label == opponent_label:
                away_logo = team_logo
                home_logo = opponent_logo
            elif away_label == opponent_label and home_label == team_label:
                away_logo = opponent_logo
                home_logo = team_logo
        rows.append(
            {
                "game_pk": _int_or_none(target.get("game_pk") or target.get("gamePk")),
                "heading": _safe_text(target.get("team"), "HR target"),
                "name": _safe_text(target.get("player_name"), "Unknown hitter"),
                "hr_rank": _int_or_none(rank),
                "rank_label": (f"#{int(rank)}" if _int_or_none(rank) else None),
                "analytics_callouts": callouts,
                "value": _safe_text(target.get("probability"), "-"),
                "matchup": matchup,
                "detail": lead_line or (reasons[0] if reasons else _safe_text(target.get("summary"), "No HR-target summary available.")),
                "writeup": writeup or _safe_text(target.get("summary"), "No HR-target summary available."),
                # Board audit follow-up, found live 2026-07-31: "support" is
                # hr_targets.py's own model support/confidence score
                # (_support_score_display, hr_targets.py:533) -- an unrelated
                # metric, not a betting line -- but stuffing it into "line"
                # made an HR-target narrative row LOOK like it had a real
                # numeric line (e.g. 106.0) to _prop_candidate_from_item's
                # completeness guard, letting a non-bettable narrative pick
                # ("His underlying HR-quality profile is running above
                # baseline.") slip onto the Layer 2 board as a fake "prop"
                # even after that guard shipped. HR-target picks have no
                # real market line at all (they're a probability-of-a-HR
                # pick, not an over/under), so this key should stay genuinely
                # empty rather than borrow an unrelated number.
                "line": "-",
                "team": _safe_text(target.get("team"), "-"),
                "opponent": _safe_text(target.get("opponent"), "-"),
                "away_label": away_label,
                "home_label": home_label,
                "headshot_url": str(target.get("headshot_url") or "").strip() or None,
                "away_logo": away_logo,
                "home_logo": home_logo,
                "team_logo_url": team_logo,
                "opponent_logo_url": opponent_logo,
                "href": f"/mlb/hr-targets?date={context_label}",
            }
        )
    return rows


def _tile_strings(game: dict[str, Any], *, limit: int = 3) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for display in _game_market_recommendation_strings(game, limit=limit):
        if display not in seen:
            seen.add(display)
            values.append(display)
        if len(values) >= limit:
            return values
    market_tiles = game.get("market_tiles") if isinstance(game.get("market_tiles"), list) else []
    for tile in market_tiles:
        if not isinstance(tile, dict):
            continue
        label = str(tile.get("label") or "").strip()
        title = str(tile.get("title") or tile.get("value") or "").strip()
        if not label and not title:
            continue
        display = f"{label}: {title}" if label and title else (label or title)
        if display not in seen:
            seen.add(display)
            values.append(display)
        if len(values) >= limit:
            return values
    top_rows = game.get("shared_top_play_rows") if isinstance(game.get("shared_top_play_rows"), list) else []
    for row in top_rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        value = str(row.get("value") or "").strip()
        detail = str(row.get("detail") or "").strip()
        display = name or detail
        if value and display:
            display = f"{display} | {value}"
        if display and display not in seen:
            seen.add(display)
            values.append(display)
        if len(values) >= limit:
            return values
    for display in _betting_signal_strings(game, limit=limit):
        if display and display not in seen:
            seen.add(display)
            values.append(display)
        if len(values) >= limit:
            return values
    for display in _mlb_live_game_signal_strings(game, limit=limit):
        if display and display not in seen:
            seen.add(display)
            values.append(display)
        if len(values) >= limit:
            return values
    return values


def _compact_game_cards(games: list[dict[str, Any]], *, limit: int | None = None) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        scoreboard = _scoreboard_state(game)
        projected_away, projected_home, projected_kind = _projected_scores(game)
        if scoreboard.get("away_score") and scoreboard.get("home_score"):
            display_away = scoreboard.get("away_score")
            display_home = scoreboard.get("home_score")
            display_kind = scoreboard.get("score_kind")
        elif _is_liveish(scoreboard.get("status_badge"), scoreboard.get("status_line")):
            display_away = None
            display_home = None
            display_kind = None
        else:
            display_away = projected_away
            display_home = projected_home
            display_kind = projected_kind if projected_away and projected_home else None
        cards.append(
            {
                "game_id": _game_identifier(game),
                "gamePk": game.get("gamePk") or game.get("game_pk") or game.get("game_id"),
                "event_id": game.get("event_id"),
                "matchup": _sport_matchup(game),
                "detail": _safe_text(scoreboard.get("status_line"), "Board update pending"),
                "status_badge": _safe_text(scoreboard.get("status_badge"), "Scheduled"),
                "away_label": scoreboard.get("away_label"),
                "away_logo": _team_logo(game, "away"),
                "home_label": scoreboard.get("home_label"),
                "home_logo": _team_logo(game, "home"),
                "away_score": display_away,
                "home_score": display_home,
                "has_scores": bool(display_away and display_home),
                "score_kind": display_kind,
                "is_projected_score": bool(display_kind == "Projection"),
                "summary": _summary_text(game),
                "signals": _tile_strings(game),
                "market_chips": _market_chip_strings(game),
                "href": str(game.get("href") or "").strip() or None,
                "href_label": str(game.get("href_label") or "Open game").strip() or "Open game",
            }
        )
        if limit is not None and len(cards) >= limit:
            break
    return _sort_compact_game_items(cards)


def _compact_prop_rows(games: list[dict[str, Any]], *, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for game in games:
        if not isinstance(game, dict):
            continue
        matchup = _sport_matchup(game)
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        prop_rows = game.get("shared_prop_rows") if isinstance(game.get("shared_prop_rows"), list) else []
        for row in prop_rows:
            if not isinstance(row, dict):
                continue
            name = _safe_text(row.get("name"), "Prop")
            detail = _safe_text(row.get("detail"), "")
            value = _safe_text(row.get("value"), "-")
            key = (matchup, name, value)
            if key in seen:
                continue
            seen.add(key)
            live_heading = _safe_text(row.get("heading"), "Props")
            if bool(game.get("shared_is_live")) or _is_liveish(game.get("status"), game.get("detail")):
                live_heading = "Live props"
            rows.append(
                {
                    "game_id": _game_identifier(game),
                    "gamePk": game.get("gamePk") or game.get("game_pk") or game.get("game_id"),
                    "event_id": game.get("event_id"),
                    "matchup": matchup,
                    "heading": live_heading,
                    "name": name,
                    "detail": detail,
                    "value": value,
                    "team": _safe_text(row.get("team"), None),
                    "photo": row.get("photo"),
                    "headshot_url": row.get("headshot_url") or row.get("photo"),
                    "away_label": _safe_text(away.get("abbr") or away.get("name"), None),
                    "home_label": _safe_text(home.get("abbr") or home.get("name"), None),
                    "away_logo": _team_logo(game, "away"),
                    "home_logo": _team_logo(game, "home"),
                    "pick": _safe_text(row.get("pick"), ""),
                    "market": _safe_text(row.get("market"), ""),
                    "line": row.get("line"),
                    "market_line": row.get("market_line") or row.get("line"),
                    "actual": row.get("actual"),
                    "projected": row.get("projected"),
                    "live_projection": row.get("live_projection"),
                    "odds": row.get("odds"),
                    "confidence": row.get("confidence"),
                    "selection": _safe_text(row.get("selection"), ""),
                    "game_state": _safe_text(row.get("game_state"), None),
                    "live_total": row.get("live_total") or row.get("live_total_line"),
                    "outcome_state": _safe_text(row.get("outcome_state"), None),
                    "outcome_label": _safe_text(row.get("outcome_label"), None),
                    "href": str(game.get("href") or "").strip() or None,
                }
            )
            if limit is not None and len(rows) >= limit:
                return rows
    return rows


def _load_home_games(slug: str, *, context_label: str, season: int | None = None, week: int | None = None, is_active_today: bool = False) -> list[dict[str, Any]]:
    provider = get_sport_data_provider(slug)
    if provider is None:
        return []
    context = provider.resolve_context(requested_date=context_label, season=season, week=week)
    try:
        return provider.games(context, is_active_today=is_active_today)
    except Exception:
        return []


def _prefer_today_or_latest(values: list[str], today_value: str, *, preserve_requested: bool = False) -> str:
    if preserve_requested:
        return today_value
    normalized_values = [str(value).strip() for value in values if str(value).strip()]
    if today_value in normalized_values:
        return today_value
    if normalized_values:
        return max(normalized_values)
    return today_value


def _link_lookup(links: list[dict[str, Any]], label: str) -> str | None:
    for link in links:
        if str(link.get("label") or "").strip().lower() == label.strip().lower():
            href = str(link.get("href") or "").strip()
            if href:
                return href
    return None


def _link_lookup_any(links: list[dict[str, Any]], labels: list[str]) -> tuple[str | None, str | None]:
    targets = [label.strip().lower() for label in labels if label.strip()]
    for link in links:
        label = str(link.get("label") or "").strip()
        href = str(link.get("href") or "").strip()
        if href and label.lower() in targets:
            return href, label
    return None, None


def _secondary_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    excluded = {"cards", "betting card", "hub"}
    return [link for link in links if str(link.get("label") or "").strip().lower() not in excluded]


def _rail_links(*candidates: tuple[str | None, str | None]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for href, label in candidates:
        href_text = str(href or "").strip()
        label_text = str(label or "").strip()
        if not href_text or not label_text:
            continue
        key = (href_text, label_text)
        if key in seen:
            continue
        seen.add(key)
        links.append({"href": href_text, "label": label_text})
    return links


def _football_in_season(today_value: str) -> bool:
    month = int(today_value[5:7]) if len(today_value) >= 7 and today_value[5:7].isdigit() else 0
    return month in {1, 8, 9, 10, 11, 12}


def _is_active_today(slug: str, today_value: str, context_label: str) -> bool:
    provider = get_sport_data_provider(slug)
    if provider is None:
        return False
    return provider.is_active(today_value=today_value, context_label=context_label)


def _sport_cache_key(slug: str, today_value: str) -> str:
    return f"{slug}:{today_value}"


def _choose_game_bar(links: list[dict[str, Any]], *, is_active_today: bool, fallback_href: str, fallback_label: str) -> dict[str, str | None]:
    live_href, _ = _link_lookup_any(links, ["Live Lens", "Live Prop Audit"])
    cards_href, cards_label = _link_lookup_any(links, ["Cards"])
    betting_href, betting_label = _link_lookup_any(links, ["Betting Card"])

    primary_href = live_href if is_active_today and live_href else (cards_href or fallback_href)
    primary_label = "Open Live Lens" if is_active_today and live_href else (f"Open {cards_label}" if cards_label else fallback_label)
    secondary_href = betting_href or cards_href or fallback_href
    secondary_label = f"Open {betting_label}" if betting_label else (f"Open {cards_label}" if cards_label else fallback_label)
    status_label = "Live lanes on" if is_active_today and live_href else "Pregame board"
    return {
        "eyebrow": "Game board",
        "title": "Live market view" if is_active_today and live_href else "Main card lane",
        "kicker": "Active games route through Live Lens" if is_active_today and live_href else "Pregame slate route",
        "summary": "Route active games through Live Lens first, then fall back to the main cards board for the full slate context."
        if is_active_today and live_href
        else "Lead with the main cards board, then use the betting-card lane for the pregame market read.",
        "status_label": status_label,
        "opportunity_tags": ["Live Lens", "Moneyline", "Spread", "Total"] if is_active_today and live_href else ["Cards", "Betting Card", "Moneyline", "Spread", "Total"],
        "primary_href": primary_href,
        "primary_label": primary_label,
        "secondary_href": secondary_href,
        "secondary_label": secondary_label,
        "items": [],
    }


def _choose_props_bar(links: list[dict[str, Any]], *, is_active_today: bool) -> dict[str, str | None]:
    live_href, _ = _link_lookup_any(links, ["Live Lens", "Live Prop Audit"])
    props_href, props_label = _link_lookup_any(links, ["Props", "Top props", "Prop Ladders", "Pitcher ladders", "Hitter ladders", "HR targets"])
    betting_href, betting_label = _link_lookup_any(links, ["Betting Card"])
    fallback_href, fallback_label = _link_lookup_any(links, ["Picks", "Season Review", "Betting Card", "Hub"])

    if props_href:
        extra_links: list[dict[str, str]] = []
        if live_href and live_href != props_href:
            extra_links.append({"href": live_href, "label": "Open Prop Live Lens" if is_active_today else "Open Live Lens"})
        if betting_href and betting_href != props_href:
            extra_links.append({"href": betting_href, "label": f"Open {betting_label}" if betting_label else "Open Betting Card"})
        return {
            "eyebrow": "Props board",
            "title": props_label or "Props",
            "kicker": "Pregame props route",
            "summary": "Start from the sport's local props board when one exists, then use adjacent boards only when you need broader context.",
            "status_label": "Pregame props",
            "opportunity_tags": [str(props_label or "Props"), "Pregame props"] + (["Live Lens"] if live_href else []),
            "primary_href": props_href,
            "primary_label": f"Open {props_label}" if props_label else "Open Props",
            "secondary_href": betting_href or fallback_href,
            "secondary_label": f"Open {betting_label}" if betting_href and betting_label else (f"Open {fallback_label}" if fallback_label else None),
            "extra_links": extra_links,
            "items": [],
        }

    if betting_href:
        extra_links: list[dict[str, str]] = []
        if live_href and live_href != betting_href:
            extra_links.append({"href": live_href, "label": "Open Prop Live Lens" if is_active_today else "Open Live Lens"})
        return {
            "eyebrow": "Props board",
            "title": betting_label or "Betting Card",
            "kicker": "Pregame betting-card route",
            "summary": "Pregame prop rows on the home board now come from the same ranked recommendation payload used by the sport's betting card.",
            "status_label": "Betting-card props",
            "opportunity_tags": [str(betting_label or "Betting Card"), "Pregame props"] + (["Live Lens"] if live_href else []),
            "primary_href": betting_href,
            "primary_label": f"Open {betting_label}" if betting_label else "Open Betting Card",
            "secondary_href": fallback_href if fallback_href and fallback_href != betting_href else None,
            "secondary_label": f"Open {fallback_label}" if fallback_href and fallback_href != betting_href and fallback_label else None,
            "extra_links": extra_links,
            "items": [],
        }

    return {
        "eyebrow": "Props board",
        "title": "Props migration gap",
        "kicker": "Fallback route until props parity lands",
        "summary": "This sport still needs a first-class props lane in Syndicate. Use the nearest migrated board for now.",
        "status_label": "Needs props lane",
        "opportunity_tags": ["Props gap", "Fallback lane"],
        "primary_href": fallback_href,
        "primary_label": f"Open {fallback_label}" if fallback_label else "Open Hub",
        "secondary_href": _link_lookup(links, "Hub") or fallback_href,
        "secondary_label": "Open Hub",
        "extra_links": [],
        "items": [],
    }


def _build_sport_overview(
    sport: dict[str, Any],
    today_value: str,
    *,
    force_refresh: bool = False,
    preserve_requested_date: bool = False,
    skip_game_hydration: bool = False,
) -> dict[str, Any]:
    # Root-caused 2026-07-24 OOM incident: this function backs the home
    # page's display cards (game_bar/props_bar/dashboard_games/home_rails,
    # including today's headshot/live-scoreboard/freshness additions), but
    # is also called from pipeline/intelligence_state.py's worker-side
    # candidate-collection path via build_intelligence_overview ->
    # build_intelligence_status -> _source_state_fingerprint, which only
    # ever reads plain sport metadata (slug/context_label/data_health) off
    # the returned dict -- never game_bar/dashboard_games/home_rails. That
    # path was paying the full cost of _load_home_game_items/
    # _load_home_games/_load_home_prop_items (pregame AND live lanes) on
    # every single cycle, confirmed via production diagnostics to be large
    # enough to exceed the container's 2GB memory limit within one call.
    # skip_game_hydration=True substitutes empty game/prop lists instead of
    # calling those loaders -- the rest of this function already handles
    # empty lists correctly (the exact same shape as "no games today").
    # Keyed into the cache separately from the normal (skip=False) result so
    # the two can never serve stale/wrong data to each other.
    slug = str(sport.get("slug") or "").strip().lower()
    cache_key = _sport_cache_key(slug, today_value)
    if skip_game_hydration:
        cache_key = f"{cache_key}:skip_hydration"
    now = time.monotonic()
    cached = _HOME_OVERVIEW_CACHE.get(cache_key)
    if cached and not force_refresh and (now - cached[0]) < _HOME_OVERVIEW_TTL_SEC:
        return dict(cached[1])

    links: list[dict[str, Any]] = []
    context_label = today_value
    overview_stats: list[dict[str, str]] = []
    primary_href = str(sport.get("primary_href") or f"/{slug}")
    hub_href = f"/{slug}/hub"
    season: int | None = None
    selected_week: int | None = None
    wnba_available_date_set: set[str] = set()

    if slug == "mlb":
        dates = available_daily_summary_dates()
        selected_date = _prefer_today_or_latest(dates, today_value, preserve_requested=preserve_requested_date)
        links = build_mlb_module_links(selected_date, "Cards")
        context_label = selected_date
        primary_href = f"/mlb?date={selected_date}"
        overview_stats = [
            {"label": "Active date", "value": selected_date},
            {"label": "Tracked dates", "value": str(len(dates))},
            {"label": "Focus", "value": "Cards + betting"},
        ]
    elif slug == "nba":
        dates = nba_available_dates()
        selected_date = _prefer_today_or_latest(dates, today_value, preserve_requested=preserve_requested_date)
        if selected_date != today_value and _nba_has_live_games(today_value):
            selected_date = today_value
        links = build_nba_module_links(selected_date, "Cards")
        context_label = selected_date
        primary_href = f"/nba?date={selected_date}"
        overview_stats = [
            {"label": "Active date", "value": selected_date},
            {"label": "Tracked dates", "value": str(len(dates))},
            {"label": "Focus", "value": "Cards + betting"},
        ]
    elif slug == "nhl":
        slates = nhl_slate_summaries()
        dates = [str(item.get("date") or "").strip() for item in slates if str(item.get("date") or "").strip()]
        selected_date = _prefer_today_or_latest(dates, today_value, preserve_requested=preserve_requested_date)
        links = build_nhl_module_links(selected_date, "Cards")
        context_label = selected_date
        primary_href = f"/nhl?date={selected_date}"
        overview_stats = [
            {"label": "Active date", "value": selected_date},
            {"label": "Tracked slates", "value": str(len(slates))},
            {"label": "Focus", "value": "Cards + betting"},
        ]
    elif slug == "wnba":
        dates = wnba_available_dates()
        wnba_available_date_set = {str(date_value).strip() for date_value in dates if str(date_value).strip()}
        selected_date = _prefer_today_or_latest(dates, today_value, preserve_requested=preserve_requested_date)
        if selected_date != today_value and _wnba_has_live_games(today_value):
            selected_date = today_value
        links = build_wnba_module_links(selected_date, "Cards")
        context_label = selected_date
        primary_href = f"/wnba?date={selected_date}"
        overview_stats = [
            {"label": "Active date", "value": selected_date},
            {"label": "Tracked dates", "value": str(len(dates))},
            {"label": "Focus", "value": "Cards + betting"},
        ]
    elif slug == "nfl":
        season = nfl_latest_season()
        # default_week()/nfl_target_week() both say "week 1" as soon as the
        # regular season is next up -- true even while we're still
        # genuinely in preseason (no regular-season game has been played
        # yet either way), so week number alone can't distinguish the two.
        # preseason_target_week() is the real signal: non-None means there
        # is still a real, unplayed preseason game on the schedule, so
        # preseason is the CURRENT phase, not "week 1 imminent." Confirmed
        # live: without this, this branch always fell through to week 1
        # regardless of season phase, which set context.week to a non-None
        # regular-season value everywhere downstream (this dict's own
        # nav/context_label AND, critically, _NFLDataProvider.games()'s own
        # context.week is None gate for real preseason games) -- so
        # preseason games never reached the Layer 2 board even once
        # everything else (odds, resim autorun, the translator itself) was
        # wired and confirmed working in isolation.
        preseason_week = preseason_target_week(season)
        if preseason_week is not None:
            selected_week = None
            links = build_preseason_module_links(preseason_week, "Preseason Cards", season=season)
            context_label = f"{season} Preseason"
            primary_href = f"/nfl/preseason/cards?season={season}&week={preseason_week}"
            overview_stats = [
                {"label": "Season", "value": str(season)},
                {"label": "Phase", "value": "Preseason"},
                {"label": "Snapshots", "value": str(len(nfl_week_summaries()))},
            ]
        else:
            tracked = nfl_tracked_week() or {}
            # Schedule-driven default_week() outranks the tracked
            # current_week.json: the tracked file is rewritten by the odds
            # refresh itself, so preferring it pinned the Layer 2 NFL context
            # to whatever week the file last held (a week-1 fixed point at
            # season start). The tracked value is only a last resort when the
            # schedule/projection artifacts are absent entirely.
            selected_week = int(nfl_default_week(season) or tracked.get("week") or 1)
            links = build_nfl_module_links(selected_week, "Cards", season=season)
            context_label = f"{season} Week {selected_week}"
            primary_href = f"/nfl?season={season}&week={selected_week}"
            overview_stats = [
                {"label": "Season", "value": str(season)},
                {"label": "Week", "value": str(selected_week)},
                {"label": "Snapshots", "value": str(len(nfl_week_summaries()))},
            ]
    elif slug == "ncaaf":
        season = ncaaf_default_season()
        selected_week = ncaaf_default_week()
        weeks = [week for week in ncaaf_week_summaries() if bool(week.get("has_data"))]
        links = build_ncaaf_module_links(selected_week, "Cards", season=season)
        context_label = f"{season} Week {selected_week}"
        primary_href = f"/ncaaf?week={selected_week}"
        overview_stats = [
            {"label": "Season", "value": str(season)},
            {"label": "Week", "value": str(selected_week)},
            {"label": "Tracked weeks", "value": str(len(weeks))},
        ]
    elif slug == "ncaab":
        dates = ncaab_available_dates()
        selected_date = _prefer_today_or_latest(
            dates,
            today_value if preserve_requested_date else (ncaab_latest_date() or today_value),
            preserve_requested=preserve_requested_date,
        )
        links = build_ncaab_module_links(selected_date, "Cards")
        context_label = selected_date
        primary_href = f"/ncaab?date={selected_date}"
        overview_stats = [
            {"label": "Active date", "value": selected_date},
            {"label": "Season", "value": str(ncaab_season_for_date(selected_date))},
            {"label": "Tracked dates", "value": str(len(dates))},
        ]

    active_today = _is_active_today(slug, today_value, context_label)
    game_bar = _choose_game_bar(
        links,
        is_active_today=active_today,
        fallback_href=primary_href,
        fallback_label=str(sport.get("primary_label") or f"Open {sport.get('name') or slug.upper()} cards"),
    )
    props_bar = _choose_props_bar(links, is_active_today=active_today)
    if slug == "mlb":
        pitcher_top_props_href = _link_lookup(links, "Pitcher top props")
        hitter_top_props_href = _link_lookup(links, "Hitter top props")
        if active_today:
            if pitcher_top_props_href:
                props_bar["secondary_href"] = pitcher_top_props_href
                props_bar["secondary_label"] = "Open Pitcher Top Props"
            if hitter_top_props_href:
                props_bar["extra_links"] = [{"href": hitter_top_props_href, "label": "Open Hitter Top Props"}]
            props_bar["title"] = "Live props + top props"
            props_bar["summary"] = "Use Live Lens for in-game MLB props, then jump directly into the pitcher and hitter top-props lanes that mirror the standalone app's module split."
            props_bar["opportunity_tags"] = ["Live props", "Pitcher top props", "Hitter top props"]
        else:
            if pitcher_top_props_href:
                props_bar["primary_href"] = pitcher_top_props_href
                props_bar["primary_label"] = "Open Pitcher Top Props"
            if hitter_top_props_href:
                props_bar["secondary_href"] = hitter_top_props_href
                props_bar["secondary_label"] = "Open Hitter Top Props"
            props_bar["title"] = "Pitcher + hitter top props"
            props_bar["summary"] = "Mirror the standalone MLB pregame props structure by keeping pitcher and hitter top-props lanes distinct on the main Syndicate page."
            props_bar["opportunity_tags"] = ["Pitcher top props", "Hitter top props", "Pregame props"]
    if skip_game_hydration:
        active_today = False
        game_items = []
        game_count = 0
        home_games = []
        pregame_prop_items = []
        live_prop_items = []
    elif slug == "wnba":
        # A real, uncached live-state read for this exact date is the
        # authoritative signal for whether WNBA is active right now -- both
        # "no games" checks below (has_games_for_date()'s ESPN-scoreboard
        # fallback, and get_wnba_overview()'s own copy of the same check) can
        # return a stale or transiently-wrong negative, and has_games_for_date
        # used to cache that forever. Confirmed live 2026-07-22: a false
        # negative here alone zeroed out every WNBA board candidate for the
        # rest of the process's life despite games actively being live.
        wnba_live_now = _wnba_has_live_games(context_label)
        wnba_has_games_today = wnba_has_games_for_date(context_label)
        wnba_no_games_today = wnba_has_games_today is False or (wnba_has_games_today is None and context_label not in wnba_available_date_set)
        if wnba_no_games_today and wnba_live_now:
            wnba_no_games_today = False
        if wnba_no_games_today:
            active_today = False
            game_items = []
            game_count = 0
            home_games = []
            pregame_prop_items = []
            live_prop_items = []
            source_title = "WNBA cards unavailable"
            source_path = ""
        else:
            wnba_overview = get_wnba_overview(context_label)
            if wnba_overview.get("status") == "no_games" and not wnba_live_now:
                active_today = False
                game_items = []
                game_count = 0
                home_games = []
                pregame_prop_items = []
                live_prop_items = []
                source_title = str(wnba_overview.get("source_title") or "WNBA cards unavailable").strip()
                source_path = str(wnba_overview.get("source_path") or "").strip()
            else:
                home_games = list(wnba_overview.get("games") or [])
                game_items = _compact_game_cards(home_games)
                game_count = len(game_items)
                wnba_prop_rows = list(wnba_overview.get("prop_rows") or [])
                if not wnba_prop_rows:
                    wnba_prop_rows = _load_home_pregame_prop_items(
                        slug,
                        context_label=context_label,
                        home_games=home_games,
                        season=season,
                        week=selected_week,
                        is_active_today=active_today,
                    )
                pregame_prop_items = _finalize_home_prop_rows(
                    wnba_prop_rows,
                    slug=slug,
                    context_label=context_label,
                    home_games=home_games,
                )
                # Was `list(pregame_prop_items)` -- a literal copy, not an
                # independent live source, so the Live Props rail always
                # mirrored pregame even with no game live. The real WNBA
                # live-lens path (same helper NBA uses) already exists in
                # _load_home_live_prop_items; this just wires it in.
                live_prop_items = _finalize_home_prop_rows(
                    _load_home_prop_items(
                        slug,
                        context_label=context_label,
                        home_games=home_games,
                        season=season,
                        week=selected_week,
                        is_active_today=active_today,
                        lane="live",
                    ),
                    slug=slug,
                    context_label=context_label,
                    home_games=home_games,
                )
                source_title = str(wnba_overview.get("source_title") or "WNBA cards").strip()
                source_path = str(wnba_overview.get("source_path") or "").strip()
    else:
        game_items, game_count = _load_home_game_items(
            slug,
            context_label=context_label,
            season=season,
            week=selected_week,
            is_active_today=active_today,
        )
        home_games = _load_home_games(slug, context_label=context_label, season=season, week=selected_week, is_active_today=active_today) if active_today else []
        pregame_prop_items = _finalize_home_prop_rows(
            _load_home_prop_items(
                slug,
                context_label=context_label,
                home_games=home_games,
                season=season,
                week=selected_week,
                is_active_today=active_today,
                lane="pregame",
            ),
            slug=slug,
            context_label=context_label,
            home_games=home_games,
        )
        live_prop_items = _finalize_home_prop_rows(
            _load_home_prop_items(
                slug,
                context_label=context_label,
                home_games=home_games,
                season=season,
                week=selected_week,
                is_active_today=active_today,
                lane="live",
            ),
            slug=slug,
            context_label=context_label,
            home_games=home_games,
        )
    live_href, live_label = _link_lookup_any(links, ["Live Lens", "Live Prop Audit"])
    cards_href, cards_label = _link_lookup_any(links, ["Cards"])
    props_href, props_label = _link_lookup_any(links, ["Props", "Top props", "Prop Ladders", "Pitcher top props", "Hitter top props", "Pitcher ladders", "Hitter ladders"])
    betting_href, betting_label = _link_lookup_any(links, ["Betting Card"])
    picks_href, picks_label = _link_lookup_any(links, ["Picks", "Season Review"])
    game_bar["items"] = game_items
    # Used to be _game_identity_set(live_prop_items) -- i.e. "this game
    # counts as live only if the (separate, narrower) live player-prop lens
    # happened to return rows for it." That conflated two unrelated things:
    # a game genuinely being in progress, and a specific sub-feature (live
    # player props) having data for it. A live game with no live prop rows
    # right now (artifact gap, no active props for this matchup, an
    # event-id mismatch in that one lookup) was getting every one of its
    # OTHER candidates (moneyline/spread/total) wrongly marked not-live too,
    # since an empty set here forces is_live=False for every game not in
    # it (see _live_odds_backed_live_flag's None-vs-empty-set handling).
    # Build the set from the same reliable in-progress signal
    # get_active_games/_game_status_state already use instead.
    live_odds_game_ids = (
        _game_identity_set([game for game in home_games if isinstance(game, dict) and _game_status_state(game) == "live"])
        if slug in _LIVE_PROP_SOURCED_SPORTS
        else None
    )
    props_bar["items"] = list(pregame_prop_items)
    if game_bar["items"]:
        overview_stats = [{"label": "Games", "value": str(game_count)}] + overview_stats[1:]
    if pregame_prop_items:
        props_bar["summary"] = f"{len(pregame_prop_items)} pregame props surfaced from the {sport.get('name') or slug.upper()} betting card payload."
    else:
        props_bar["summary"] = "No pregame prop rows were available from the sport betting card payload for this slate."

    active_games = get_active_games(home_games)
    active_game_ids = _game_identity_set(active_games)
    game_item_ids = _game_identity_set(game_items)
    prop_item_ids = _game_identity_set(list(pregame_prop_items) + list(live_prop_items))
    artifact_home_games = list(home_games)
    hydrated_game_ids = {identifier for identifier in active_game_ids if identifier in game_item_ids}
    if slug == "wnba" and not hydrated_game_ids and home_games:
        hydrated_game_ids = _game_identity_set(home_games)
    if active_today and not hydrated_game_ids and active_game_ids and prop_item_ids:
        hydrated_game_ids = {identifier for identifier in active_game_ids if identifier in prop_item_ids}
    if active_today and not hydrated_game_ids and active_game_ids:
        hydrated_game_ids = {identifier for identifier in active_game_ids if identifier in game_item_ids}
    game_items = [item for item in game_items if _game_identifier(item) in hydrated_game_ids]
    pregame_prop_items = [item for item in pregame_prop_items if _game_identifier(item) in hydrated_game_ids]
    live_prop_items = [item for item in live_prop_items if _game_identifier(item) in hydrated_game_ids]
    home_games = [game for game in active_games if _game_identifier(game) in hydrated_game_ids]
    if slug == "wnba" and not home_games and artifact_home_games and hydrated_game_ids:
        home_games = [game for game in artifact_home_games if _game_identifier(game) in hydrated_game_ids]
    for item in game_items:
        item["is_live"] = _live_odds_backed_live_flag(_game_identifier(item), live_odds_game_ids, bool(item.get("is_live")))
    for item in pregame_prop_items:
        item["is_live"] = _live_odds_backed_live_flag(_game_identifier(item), live_odds_game_ids, bool(item.get("is_live")))
    for item in live_prop_items:
        item["is_live"] = _live_odds_backed_live_flag(_game_identifier(item), live_odds_game_ids, bool(item.get("is_live")))
    for game in home_games:
        game["is_live"] = _live_odds_backed_live_flag(_game_identifier(game), live_odds_game_ids, bool(game.get("is_live")))
    active_game_count = len(active_games)
    hydrated_game_count = len(hydrated_game_ids)
    props_count = len(game_items) + len(pregame_prop_items) + len(live_prop_items)
    game_bar["items"] = game_items
    props_bar["items"] = list(pregame_prop_items)

    games_count = len(game_items)
    overview = {
        **sport,
        "primary_href": primary_href,
        "hub_href": hub_href,
        "betting_href": _link_lookup(links, "Betting Card"),
        "context_label": context_label,
        "slate_label": "Live today" if active_today else "Scheduled board",
        "overview_stats": overview_stats,
        "feature_links": _secondary_links(links),
        "active_today": active_today,
        "show_on_home": bool(active_game_count or hydrated_game_count or props_count),
        "game_bar": game_bar,
        "props_bar": props_bar,
        "dashboard_games": home_games,
        "home_anchor": f"home-sport-{slug}",
        "games_count": games_count,
        "active_game_count": active_game_count,
        "hydrated_game_count": hydrated_game_count,
        "home_rails": {
            "compact": {
                "title": "Compact game rail",
                "items": game_items,
                "links": _rail_links(
                    (live_href or cards_href or primary_href, f"Open {live_label}" if live_href and live_label else (f"Open {cards_label}" if cards_href and cards_label else "Open Cards")),
                    (betting_href or cards_href or primary_href, f"Open {betting_label}" if betting_href and betting_label else (f"Open {cards_label}" if cards_href and cards_label else "Open Board")),
                    (hub_href, f"Open {sport.get('name') or slug.upper()} Hub"),
                ),
                "empty_summary": f"No compact game cards were surfaced for {context_label}.",
            },
            "pregame": {
                "title": "Pregame props",
                "items": pregame_prop_items,
                "links": _rail_links(
                    (betting_href or props_href or primary_href, f"Open {betting_label}" if betting_href and betting_label else (f"Open {props_label}" if props_href and props_label else "Open Betting Card")),
                    (props_href if props_href != betting_href else picks_href, f"Open {props_label}" if props_href and props_href != betting_href and props_label else (f"Open {picks_label}" if picks_href and picks_label else None)),
                    (hub_href, f"Open {sport.get('name') or slug.upper()} Hub"),
                ),
                "empty_summary": "No pregame prop rows were available from the sport betting card payload for this slate.",
            },
            "live": {
                "title": "Top Live Props",
                "items": live_prop_items,
                "links": _rail_links(
                    (live_href or primary_href, f"Open {live_label}" if live_href and live_label else "Open Live Lens"),
                    (betting_href or props_href or hub_href, f"Open {betting_label}" if betting_href and betting_label else (f"Open {props_label}" if props_href and props_label else f"Open {sport.get('name') or slug.upper()} Hub")),
                ),
                "empty_summary": "Top live props only appear when games are in progress." if not live_prop_items else f"No live prop rows were available for {context_label}.",
            },
        },
    }
    props_count = _dashboard_prop_count(overview)
    overview["props_count"] = props_count
    overview["show_on_home"] = bool(active_game_count or hydrated_game_count or props_count)
    data_warnings: list[str] = []
    wnba_no_games_today = slug == "wnba" and not bool(home_games)
    if active_today and active_game_count <= 0 and not wnba_no_games_today:
        data_warnings.append("No game rows surfaced")
    if active_today and hydrated_game_count <= 0 and not wnba_no_games_today:
        data_warnings.append("Active games did not fully hydrate")
    if props_count <= 0 and not wnba_no_games_today:
        data_warnings.append("No prop rows surfaced")
    if active_today and slug == "wnba" and active_game_count <= 0 and not wnba_no_games_today:
        _LOGGER.warning(
            "WNBA overview source missing for %s: games=%s pregame=%s live=%s dashboard_games=%s",
            context_label,
            active_game_count,
            len(pregame_prop_items),
            len(live_prop_items),
            len(home_games),
        )
    overview["data_warnings"] = data_warnings
    overview["data_health"] = "healthy" if not data_warnings else ("stale" if active_today and active_game_count <= 0 else "partial")
    stamped_at = time.monotonic()
    _HOME_OVERVIEW_CACHE[cache_key] = (stamped_at, overview)
    _HOME_OVERVIEW_CACHE.move_to_end(cache_key)
    _prune_home_cache(_HOME_OVERVIEW_CACHE, now=stamped_at)
    return dict(overview)


def build_home_overview(
    sports: list[dict[str, Any]],
    *,
    selected_date: str | None = None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    today_value = _home_selected_date(selected_date)
    preserve_requested_date = selected_date is not None
    active_sports = _active_sport_slugs()
    sport_items = [sport for sport in sports if isinstance(sport, dict) and _safe_text(sport.get("slug"), "").lower() in active_sports]
    if len(sport_items) <= 1:
        overview = [
            _build_sport_overview(
                sport,
                today_value,
                force_refresh=force_refresh,
                preserve_requested_date=preserve_requested_date,
            )
            for sport in sport_items
        ]
    else:
        overview: list[dict[str, Any] | None] = [None] * len(sport_items)
        max_workers = min(4, len(sport_items))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _build_sport_overview,
                    sport,
                    today_value,
                    force_refresh=force_refresh,
                    preserve_requested_date=preserve_requested_date,
                ): index
                for index, sport in enumerate(sport_items)
            }
            for future, index in futures.items():
                try:
                    overview[index] = future.result()
                except Exception:
                    overview[index] = _build_sport_overview(
                        sport_items[index],
                        today_value,
                        force_refresh=force_refresh,
                        preserve_requested_date=preserve_requested_date,
                    )
        overview = [sport for sport in overview if isinstance(sport, dict)]
    active = [sport for sport in overview if bool(sport.get("show_on_home"))]
    active_sports = _active_sport_slugs()
    if active_sports:
        active = [sport for sport in active if _safe_text(sport.get("slug"), "").lower() in active_sports]
    _LOGGER.debug("ACTIVE SPORTS: %s", [str(sport.get("slug") or "").strip().lower() for sport in active])
    _LOGGER.debug("ACTIVE GAMES: %s", sum(int(sport.get("active_game_count") or 0) for sport in active))
    _LOGGER.debug("HYDRATED GAMES: %s", sum(int(sport.get("hydrated_game_count") or 0) for sport in active))
    return active


def _home_payload(*, selected_date: str | None = None, cached_only: bool = False, force_refresh: bool = False) -> dict[str, Any]:
    effective_date = _home_selected_date(selected_date)
    cache_key = effective_date
    now = time.monotonic()
    cached = _HOME_PAYLOAD_CACHE.get(cache_key)
    if cached and not force_refresh and (cached_only or (now - cached[0]) < _HOME_OVERVIEW_TTL_SEC):
        return dict(cached[1])
    if cached_only:
        sports: list[dict[str, Any]] = []
        return {
            "sports": sports,
            "html": render_template("shared/_home_sport_stack.html", sports=sports),
            "polled_at": time.time(),
        }
    if _render_web_dyno():
        overview = _build_light_home_sports(effective_date)
    else:
        sports = current_app.config["SYNDICATE_SPORTS"]
        overview = build_home_overview(sports, selected_date=effective_date, force_refresh=force_refresh)
    polled_at = time.time()
    polled_label = _format_home_timestamp(polled_at)
    for sport in overview:
        if not isinstance(sport, dict):
            continue
        sport["freshness_label"] = f"Live \u00b7 {polled_label}" if bool(sport.get("active_today")) else "Stored slate"
    dashboard = _build_home_dashboard(overview, selected_date=effective_date, polled_at=polled_at)
    command_center = _build_home_command_center_contract(dashboard, selected_date=effective_date, polled_at=polled_at)
    payload = {
        "sports": overview,
        "dashboard": dashboard,
        "command_center": command_center,
        "selected_date": effective_date,
        "html": render_template("shared/_home_dashboard.html", sports=overview, dashboard=dashboard),
        "polled_at": polled_at,
    }
    stamped_at = time.monotonic()
    _HOME_PAYLOAD_CACHE[cache_key] = (stamped_at, payload)
    _HOME_PAYLOAD_CACHE.move_to_end(cache_key)
    _prune_home_cache(_HOME_PAYLOAD_CACHE, now=stamped_at)
    return dict(payload)


def _build_light_home_sports(selected_date: str | None = None) -> list[dict[str, Any]]:
    context_label = _home_selected_date(selected_date)
    try:
        sports = build_home_overview(
            current_app.config.get("SYNDICATE_SPORTS", []),
            selected_date=context_label,
            force_refresh=context_label == central_today_iso(),
        )
    except Exception:
        return []
    return [sport for sport in sports if isinstance(sport, dict) and _safe_text(sport.get("slug"), "").lower() in _active_sport_slugs()]


@home_bp.get("/")
def home():
    # Nav/IA change 2026-07-24: the curated Betting Board (Layer 2) is now
    # the homepage -- "Betting Board" in nav instead points to the new
    # Layer 1 market-board hub (see market_board_hub() below). The old
    # per-sport dashboard this route used to render (home.html) is
    # retired from nav; its code is left in place, just unreachable, per
    # the user's explicit call not to delete it outright.
    from syndicate.blueprints.intelligence import intelligence_home

    return intelligence_home()


_MARKET_BOARD_HUB_SPORTS: tuple[dict[str, str], ...] = (
    {"slug": "mlb", "name": "MLB", "description": "Every quoted moneyline, total, and player prop -- live games today."},
    {"slug": "nba", "name": "NBA", "description": "Full market inventory once the season resumes."},
    {"slug": "wnba", "name": "WNBA", "description": "Full market inventory once the season resumes."},
    {"slug": "nfl", "name": "NFL", "description": "Every quoted moneyline, spread, and total, joined against a real SmartSim 2.0 projection."},
    # slug "nfl/preseason" (not a real sport slug) relies on the template's
    # href pattern `/{{ sport.slug }}/market-board` resolving to the real
    # /nfl/preseason/market-board route -- this tile was previously
    # orphaned, reachable only by typing the URL directly.
    {"slug": "nfl/preseason", "name": "NFL Preseason", "description": "Every quoted preseason moneyline, spread, and total, joined against a shrinkage-adjusted SmartSim 2.0 projection."},
    {"slug": "ncaaf", "name": "NCAAF", "description": "Every quoted spread, total, and moneyline -- current week's games."},
)


def _market_board_hub_soccer_sports(nav_date: str) -> list[dict[str, str]]:
    # Every soccer league gets its own board (same generic /soccer/<league>/
    # market-board route works for all 10) -- only the ones actually in
    # season for this date are shown, same gating _active_sports_for_date()
    # already uses for the refresh dispatcher.
    from syndicate.features.soccer.sources import active_leagues_for_date
    from syndicate.features.soccer.sources import league_display_name

    active = active_leagues_for_date(nav_date)
    return [
        {
            "slug": f"soccer/{league}",
            "name": league_display_name(league),
            "description": "Every quoted moneyline, total, spread, and player prop for this league's current game week.",
        }
        for league in sorted(active)
    ]


@home_bp.get("/market-board")
def market_board_hub():
    # Nav/IA change 2026-07-24: "Betting Board" in nav now lands here
    # rather than on a single sport's Layer 1 board directly -- Layer 1 is
    # per-sport only today (no unified cross-sport inventory yet), so this
    # is a lightweight picker until Phase 6 covers enough sports to justify
    # something richer.
    nav_date = _home_selected_date(request.args.get("date"))
    sports = list(_MARKET_BOARD_HUB_SPORTS) + _market_board_hub_soccer_sports(nav_date)
    return render_template(
        "market_board_hub.html",
        sports=sports,
        nav_date=nav_date,
    )


@home_bp.get("/syndicate")
def syndicate():
    return render_template("syndicate.html")


@home_bp.get("/api/home")
def api_home():
    refresh_requested = str(request.args.get("refresh") or "").strip().lower() in {"1", "true", "yes", "on"}
    selected_date = _home_selected_date(request.args.get("date"))
    payload = _home_payload(selected_date=selected_date, force_refresh=refresh_requested or selected_date == central_today_iso())
    return jsonify(
        {
            "ok": True,
            "sports": payload["sports"],
            "dashboard": payload.get("dashboard"),
            "command_center": payload.get("command_center"),
            "selected_date": payload.get("selected_date"),
            "html": payload["html"],
            "polled_at": payload["polled_at"],
        }
    )