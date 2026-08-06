from __future__ import annotations

import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from syndicate.features.nfl.cards import build_cards_page_context
from syndicate.features.nfl.preseason_cards import _available_preseason_weeks
from syndicate.features.nfl.preseason_cards import build_preseason_cards_page_context
from syndicate.features.nfl.sources import available_weeks
from syndicate.features.nfl.sources import build_module_links
from syndicate.features.nfl.sources import build_preseason_module_links
from syndicate.features.nfl.sources import default_week
from syndicate.features.nfl.sources import latest_season
from syndicate.features.nfl.sources import preseason_target_week
from syndicate.features.shared.live_lens_contract import attach_live_lens_contract
from syndicate.features.shared.rank_board import build_rank_api_payload
from syndicate.features.shared.rank_board import build_rank_page_context
from syndicate.features.shared.refresh_state_store import data_root
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.request_path_guard import warn_if_compute_in_request_path
from syndicate.features.shared.schedule_adapter import _fetch_espn_football_live_state
from syndicate.features.shared.timezone import central_today_iso


def live_lens_snapshot_path() -> Path:
    # A single, always-overwritten file -- not week-scoped -- matching the
    # real MLB/NBA/WNBA/soccer convention (none of those are date-scoped at
    # the *path* level either; the snapshot's own "date"/"week"/"season"
    # fields, not the filename, carry which slate it covers). NFL's live-lens
    # loop tick always rebuilds for the currently tracked week/season, so one
    # file is enough.
    return data_root() / "live" / "nfl_live_lens.json"


def _safe_text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _safe_number(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except Exception:
        return None


def _team_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _game_matchup_keys(game: dict[str, Any]) -> list[tuple[str, str]]:
    # Tries the full team-name pair first, then the abbreviation pair as a
    # fallback -- both are probed (not just whichever is non-empty) so a
    # real-world name mismatch between this game's own team text and ESPN's
    # displayName (e.g. a stale/alternate name in the branding CSV) still
    # resolves via a matching abbreviation, mirroring
    # _live_row_matchup_keys's own multi-key shape below.
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    keys: list[tuple[str, str]] = []
    name_key = (_team_key(away.get("name")), _team_key(home.get("name")))
    if all(name_key):
        keys.append(name_key)
    abbr_key = (_team_key(away.get("abbr")), _team_key(home.get("abbr")))
    if all(abbr_key) and abbr_key not in keys:
        keys.append(abbr_key)
    return keys


def _live_row_matchup_keys(row: dict[str, Any]) -> list[tuple[str, str]]:
    # NFL game dicts carry no shared event_id with ESPN's scoreboard (unlike
    # WNBA's game_cards rows, which at least sometimes share ESPN's own
    # numeric id) -- match on normalized team identity instead, trying the
    # full display name first and the abbreviation as a fallback, mirroring
    # wnba/cards.py's _live_state_matchup_key's own name/tricode fallback
    # shape for the same "no shared id" problem.
    keys: list[tuple[str, str]] = []
    name_key = (_team_key(row.get("away")), _team_key(row.get("home")))
    if all(name_key):
        keys.append(name_key)
    abbr_key = (_team_key(row.get("away_abbr")), _team_key(row.get("home_abbr")))
    if all(abbr_key) and abbr_key not in keys:
        keys.append(abbr_key)
    return keys


def _index_live_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in _live_row_matchup_keys(row):
            index.setdefault(key, row)
    return index


def _apply_live_state_to_game(game: dict[str, Any], live_row: dict[str, Any]) -> dict[str, Any]:
    """Overlay real ESPN live status/score/clock onto a pregame game dict.

    Only ever called for a live_row whose state is "in" or "post"/completed
    (see build_live_lens_snapshot) -- a "pre" state match is left completely
    untouched so a not-yet-started game keeps its original pregame status
    string instead of gaining a fabricated "Live"/"Scheduled" label.
    """
    final = bool(live_row.get("completed")) or _safe_text(live_row.get("state"), "").lower() == "post"
    period = live_row.get("period")
    clock = _safe_text(live_row.get("display_clock"), "")
    espn_detail = _safe_text(live_row.get("status_detail"), "")

    if final:
        status_label = "Final"
        detail_text = espn_detail or "Final"
    else:
        status_label = "Live"
        if period and clock:
            detail_text = f"Q{period} {clock}"
        else:
            detail_text = espn_detail or "Live"

    # game["status"] becomes the same period/clock-bearing contract dict
    # WNBA's own live-merged game dicts use (wnba/cards.py's
    # _source_status_contract / _status_fields_from_value shape) -- NFL cards
    # normally carries a flat "Week N" string here instead, but that's a
    # pregame-only shape; the live-lens snapshot is the one place NFL adopts
    # the richer dict so real period/clock have somewhere real to live.
    game["status"] = {
        "status": status_label,
        "detail": detail_text,
        "in_progress": bool(not final),
        "final": bool(final),
        "period": period,
        "clock": clock,
    }
    game["detail"] = detail_text

    away_pts = _safe_number(live_row.get("away_score"))
    home_pts = _safe_number(live_row.get("home_score"))
    game["live_state"] = {
        "in_progress": bool(not final),
        "final": bool(final),
        "status": detail_text,
        "period": period,
        "clock": clock,
        "away_pts": away_pts,
        "home_pts": home_pts,
        "event_id": live_row.get("event_id"),
    }
    if away_pts is not None and home_pts is not None:
        away_team = game.get("away") if isinstance(game.get("away"), dict) else {}
        home_team = game.get("home") if isinstance(game.get("home"), dict) else {}
        game["away"] = {**away_team, "score": away_pts}
        game["home"] = {**home_team, "score": home_pts}
    return game


def _value_has_non_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_value_has_non_finite_number(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_value_has_non_finite_number(item) for item in value)
    return False


def validate_live_lens_snapshot(snapshot: Any) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if not str(snapshot.get("date") or "").strip():
        return False
    if not isinstance(snapshot.get("games"), list):
        return False
    cards = snapshot.get("cards")
    if not isinstance(cards, list):
        return False
    if _value_has_non_finite_number(snapshot):
        return False
    return True


def _load_live_lens_snapshot() -> dict[str, Any] | None:
    payload = read_json_file(live_lens_snapshot_path())
    return payload if isinstance(payload, dict) else None


def _snapshot_matches_request(snapshot: dict[str, Any] | None, *, season: int, week: int) -> bool:
    if not validate_live_lens_snapshot(snapshot):
        return False
    if not snapshot.get("rank_cards"):
        return False
    try:
        if int(snapshot.get("season")) != int(season):
            return False
    except Exception:
        return False
    # preseason_target_week() is re-checked here too (not just inside
    # build_live_lens_snapshot itself) so a stored snapshot from one season
    # phase is never trusted as "current" once the real phase has flipped --
    # e.g. a leftover preseason snapshot (week 1-4 domain) surviving into
    # the regular season's own week 1, where the week NUMBER alone would
    # otherwise look like a match.
    current_preseason_week = preseason_target_week(int(season))
    is_preseason_now = current_preseason_week is not None
    if bool(snapshot.get("is_preseason")) != is_preseason_now:
        return False
    expected_week = current_preseason_week if is_preseason_now else week
    try:
        return int(snapshot.get("week")) == int(expected_week)
    except Exception:
        return False


def _score_line(game: dict[str, Any]) -> str | None:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    away_score = _safe_number(away.get("score"))
    home_score = _safe_number(home.get("score"))
    if away_score is None or home_score is None:
        return None
    away_abbr = _safe_text(away.get("abbr"), "AWY")
    home_abbr = _safe_text(home.get("abbr"), "HOM")
    return f"{away_abbr} {int(round(away_score))}-{int(round(home_score))} {home_abbr}"


def _status_eyebrow(game: dict[str, Any]) -> str:
    status = game.get("status")
    if isinstance(status, dict):
        return _safe_text(status.get("status"), "Live")
    return _safe_text(status, "Weekly board")


def _meta_text(game: dict[str, Any]) -> str:
    detail = _safe_text(game.get("detail"), "Week board")
    score_line = _score_line(game)
    if score_line:
        return f"{detail} | {score_line}" if detail and detail != "-" else score_line
    return detail


def _rank_card(game: dict[str, Any]) -> dict[str, Any]:
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    metrics = game.get("metrics") if isinstance(game.get("metrics"), list) else []
    top_rows = game.get("shared_top_play_rows") if isinstance(game.get("shared_top_play_rows"), list) else []
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    badge = _safe_text((((top_rows or [None])[0] or {}).get("value") if top_rows else None), "Watch")
    if live_state.get("final"):
        badge = "Final"
    elif live_state.get("in_progress"):
        badge = "Live"
    list_items = []
    for row in top_rows[:4]:
        if not isinstance(row, dict):
            continue
        list_items.append(
            " | ".join(
                part
                for part in [
                    _safe_text(row.get("name"), "Signal"),
                    _safe_text(row.get("value"), "-"),
                    _safe_text(row.get("detail"), ""),
                ]
                if part and part != "-"
            )
        )
    if not list_items:
        list_items = ["No stored live bet signals were available for this matchup."]
    return {
        "title": f"{_safe_text(away.get('abbr'), 'AWY')} @ {_safe_text(home.get('abbr'), 'HOM')}",
        "eyebrow": _status_eyebrow(game),
        "badge": badge,
        "meta": _meta_text(game),
        "metrics": [metric for metric in metrics[:4] if isinstance(metric, dict)],
        "summary": _safe_text(game.get("summary"), "NFL live lens row."),
        "list_items": list_items,
        "href": _safe_text(game.get("href"), "/nfl/cards"),
        "href_label": _safe_text(game.get("href_label"), "Open NFL game detail"),
    }


def build_live_lens_snapshot(week: int, season: int) -> dict[str, Any]:
    """Phase 1 (todo #119): layer real ESPN live status/score/clock onto the
    stored weekly cards snapshot. Deliberately no re-simulation here --
    pregame win-probability/edges from build_cards_page_context (or its
    preseason equivalent) pass through unchanged; only status/detail/score
    are ever overwritten, and only for a game ESPN actually reports as
    in-progress or final today.

    preseason_target_week() is re-derived internally here -- the same real
    "which phase is actually current" signal _build_sport_overview (home.py)
    and _NFLDataProvider.games() already use, rather than trusting the
    passed-in `week` -- because default_week()/nfl_target_week() both still
    say "week 1" as soon as the regular season is next up, even while still
    genuinely in preseason (no regular-season game has been played yet
    either way). A non-None preseason_target_week always wins and the passed
    `week` argument is ignored in that case: during preseason there is no
    real regular-season week to build live-lens for.
    """
    resolved_season = int(season)
    preseason_week = preseason_target_week(resolved_season)
    is_preseason = preseason_week is not None

    try:
        if is_preseason:
            cards_context = build_preseason_cards_page_context(preseason_week, season=resolved_season)
        else:
            cards_context = build_cards_page_context(week, season=resolved_season)
    except Exception:
        cards_context = {}
    fallback_week = preseason_week if is_preseason else (week or default_week(resolved_season))
    resolved_week = int(cards_context.get("week") or cards_context.get("control_value") or fallback_week)
    games = [deepcopy(game) for game in (cards_context.get("games") if isinstance(cards_context.get("games"), list) else []) if isinstance(game, dict)]

    try:
        live_rows = _fetch_espn_football_live_state("nfl", central_today_iso())
    except Exception:
        live_rows = []
    live_index = _index_live_rows(live_rows)

    merged_games: list[dict[str, Any]] = []
    matched_count = 0
    for game in games:
        live_row = None
        for key in _game_matchup_keys(game):
            live_row = live_index.get(key)
            if live_row is not None:
                break
        if isinstance(live_row, dict):
            state = _safe_text(live_row.get("state"), "").lower()
            if state in ("in", "post") or bool(live_row.get("completed")):
                game = _apply_live_state_to_game(game, live_row)
                matched_count += 1
        merged_games.append(game)

    rank_cards = [_rank_card(game) for game in merged_games]
    source_path = str(cards_context.get("source_path") or live_lens_snapshot_path())
    phase_label = "Preseason" if is_preseason else "Regular season"
    week_display = f"Preseason Week {resolved_week}" if is_preseason else f"Week {resolved_week}"
    date_label = f"{resolved_season} {week_display}"
    warning_panel = {
        "eyebrow": "Live-state overlay",
        "title": "NFL live lens now overlays real ESPN status/score/clock onto the stored weekly cards",
        "body": "This worker reads the stored NFL weekly cards snapshot and merges real live status, score, and clock from ESPN's public scoreboard for games playing today. Pregame win probability and edges are not re-simulated in this pass.",
        "list_items": [
            f"Phase: {phase_label}",
            f"Games surfaced: {len(merged_games)}",
            f"Games with a live-state match: {matched_count}",
        ],
    }
    empty_state = None
    if not rank_cards:
        warning_panel = {
            "eyebrow": "NFL live lens",
            "title": "No NFL live-lens rows were available for this week",
            "body": "The background worker reads the stored NFL weekly cards snapshot, and none was available for the requested season and week.",
            "list_items": [f"Season: {resolved_season}", f"Phase: {phase_label}", f"Week: {resolved_week}"],
        }
        empty_state = dict(warning_panel)

    if is_preseason:
        module_links = build_preseason_module_links(resolved_week, "Live Lens", season=resolved_season)
        available_weeks_list = _available_preseason_weeks(resolved_season)
    else:
        module_links = build_module_links(resolved_week, "Live Lens", season=resolved_season)
        available_weeks_list = available_weeks(resolved_season)

    context = build_rank_page_context(
        selected_date=date_label,
        route_path="/nfl/live-lens",
        intro_title="NFL Live Lens",
        intro_body="NFL live lens overlays real ESPN live status/score/clock onto the shared weekly cards snapshot. Win probability and edges stay pregame-computed in this pass.",
        aria_label="NFL live lens board",
        source_path=source_path,
        source_title="NFL live lens snapshot" if rank_cards else "NFL live lens unavailable",
        rank_cards=rank_cards,
        using_sample_data=False,
        header_stats=[
            {"label": "Games", "value": str(len(merged_games))},
            {"label": "Live matches", "value": str(matched_count)},
            {"label": "Season", "value": str(resolved_season)},
            {"label": "Phase", "value": phase_label},
            {"label": "Week", "value": str(resolved_week)},
        ],
        module_links=module_links,
        warning_panel=warning_panel,
        source_date_display=date_label,
        control_label="Preseason week" if is_preseason else "Week",
        control_type="number",
        control_name="week",
        control_value=str(resolved_week),
        hidden_fields=[{"name": "season", "value": str(resolved_season)}],
        prev_href=f"/nfl/live-lens?season={resolved_season}&week={cards_context.get('prev_date') or resolved_week}",
        next_href=f"/nfl/live-lens?season={resolved_season}&week={cards_context.get('next_date') or resolved_week}",
        reset_href=f"/nfl/live-lens?season={resolved_season}",
        empty_state=empty_state,
    )
    context["games"] = merged_games
    context["cards"] = [dict(card) for card in rank_cards]
    context["season"] = resolved_season
    context["week"] = resolved_week
    context["is_preseason"] = is_preseason
    context["available_weeks"] = available_weeks_list
    context["rows"] = len(rank_cards)
    context["data"] = [dict(card) for card in rank_cards]
    context["groups"] = {"Games": [dict(card) for card in rank_cards]}
    context["have_data"] = bool(rank_cards)
    context["source_path"] = source_path
    context["live_matches"] = matched_count
    context = attach_live_lens_contract(context, sport="nfl", module="live_lens")
    context["api_payload"] = build_rank_api_payload(context)
    return context


def build_live_lens_page_context(selected_week: int, *, season: int) -> dict[str, Any]:
    warn_if_compute_in_request_path("build_live_lens_page_context")
    resolved_season = int(season)
    snapshot = _load_live_lens_snapshot()
    if not _snapshot_matches_request(snapshot, season=resolved_season, week=selected_week):
        snapshot = build_live_lens_snapshot(selected_week, resolved_season)
    context = dict(snapshot) if isinstance(snapshot, dict) else build_live_lens_snapshot(selected_week, resolved_season)
    context["rank_cards"] = [dict(card) for card in (context.get("rank_cards") or []) if isinstance(card, dict)]
    context["cards"] = [dict(card) for card in (context.get("cards") or context.get("rank_cards") or []) if isinstance(card, dict)]
    context.setdefault("season", resolved_season)
    context.setdefault("week", selected_week)
    context.setdefault("is_preseason", preseason_target_week(resolved_season) is not None)
    context.setdefault(
        "available_weeks",
        _available_preseason_weeks(resolved_season) if context.get("is_preseason") else available_weeks(resolved_season),
    )
    context.setdefault("rows", len(context.get("rank_cards") or []))
    context.setdefault("data", context.get("cards"))
    context.setdefault("groups", {"Games": context.get("cards")})
    context.setdefault("have_data", bool(context.get("rank_cards")))
    return attach_live_lens_contract(context, sport="nfl", module="live_lens")
