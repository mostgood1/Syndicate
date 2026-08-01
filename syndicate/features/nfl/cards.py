from __future__ import annotations

import csv
import glob
import json
import os
import re
import statistics
from functools import lru_cache
from typing import Any

from syndicate.features.nfl.smartsim2_projection import read_projection_artifact
from syndicate.features.nfl.sources import available_weeks
from syndicate.features.nfl.sources import build_module_links
from syndicate.features.nfl.sources import default_nfl_source_root
from syndicate.features.nfl.sources import default_week
from syndicate.features.nfl.sources import latest_season
from syndicate.features.nfl.sources import recommendation_path
from syndicate.features.shared.discrete_nav import neighboring_values
from syndicate.features.shared.discrete_nav import resolve_selected_value
from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.shared.market_inventory import join_odds_to_sim
from syndicate.features.shared.team_branding import read_team_branding_snapshot


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _format_num(value: Any, digits: int = 1) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}"


def _format_signed(value: Any, digits: int = 1) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:+.{digits}f}"


def _format_pct(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number * 100:.1f}%"


def _format_moneyline(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    rounded = int(round(number))
    return f"+{rounded}" if rounded > 0 else str(rounded)


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _format_ev_pct(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:.1f}%"


def _confidence_rank(value: Any) -> int:
    label = _safe_text(value).lower()
    if label == "high":
        return 3
    if label == "medium":
        return 2
    if label == "low":
        return 1
    return 0


def _team_abbr(team_name: str) -> str:
    tokens = [token for token in team_name.replace(".", " ").split() if token]
    initials = "".join(token[0] for token in tokens if token and token[0].isalpha()).upper()
    if len(initials) >= 2:
        return initials[:3]
    letters = "".join(char for char in team_name.upper() if char.isalpha())
    return (letters[:3] or "TEAM")


def _normalize_branding_key(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


@lru_cache(maxsize=1)
def _team_branding_index() -> dict[str, Any]:
    path = default_nfl_source_root() / "source_artifacts" / "data" / "processed" / "team_branding" / "nfl_team_branding.csv"
    rows = read_team_branding_snapshot(path)
    index: dict[str, Any] = {}
    for row in rows:
        for key in (row.display_name, row.location, row.abbreviation):
            normalized = _normalize_branding_key(key)
            if normalized:
                index.setdefault(normalized, row)
    return index


def _resolve_branding(team_name: str) -> Any | None:
    return _team_branding_index().get(_normalize_branding_key(team_name))


def _format_game_date(value: Any) -> str:
    raw = _safe_text(value, "TBD")
    return raw[:10] if len(raw) >= 10 else raw


@lru_cache(maxsize=64)
def _read_snapshot_rows(season: int, week: int) -> tuple[dict[str, Any], ...]:
    path = recommendation_path(week, season=season)
    if not path.exists():
        return ()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return tuple(row for row in csv.DictReader(handle) if isinstance(row, dict))
    except Exception:
        return ()


def _snapshot_source_path(season: int, week: int) -> str:
    return str(recommendation_path(week, season=season))


def _row_sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
    ev_pct = _safe_float(row.get("ev_pct"))
    return (
        _confidence_rank(row.get("confidence")),
        ev_pct if ev_pct is not None else float("-inf"),
        _safe_text(row.get("type")).upper(),
    )


def _group_snapshot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        away_team = _safe_text(row.get("away_team"), "Away")
        home_team = _safe_text(row.get("home_team"), "Home")
        game_date = _format_game_date(row.get("game_date"))
        grouped.setdefault((game_date, away_team, home_team), []).append(row)

    bundles: list[dict[str, Any]] = []
    for (game_date, away_team, home_team), matchup_rows in grouped.items():
        ordered_rows = sorted(matchup_rows, key=_row_sort_key, reverse=True)
        top_row = ordered_rows[0] if ordered_rows else {}
        confidence = _safe_text(top_row.get("confidence"), "Snapshot")
        top_ev = _safe_float(top_row.get("ev_pct"))
        type_scores: dict[str, float] = {}
        for row in ordered_rows:
            type_name = _safe_text(row.get("type"), "Recommendation").upper()
            ev_pct = _safe_float(row.get("ev_pct"))
            if type_name not in type_scores or ((ev_pct if ev_pct is not None else float("-inf")) > type_scores[type_name]):
                type_scores[type_name] = ev_pct if ev_pct is not None else float("-inf")
        bundles.append(
            {
                "game_date": game_date,
                "away_team": away_team,
                "home_team": home_team,
                "rows": ordered_rows,
                "top_row": top_row,
                "top_ev": top_ev,
                "confidence": confidence,
                "moneyline_ev": type_scores.get("MONEYLINE"),
                "spread_ev": type_scores.get("SPREAD"),
                "total_ev": type_scores.get("TOTAL"),
            }
        )
    return bundles


def _official_items(rows: list[dict[str, Any]]) -> list[str]:
    items: list[str] = []
    for row in rows[:3]:
        rec_type = _safe_text(row.get("type"), "Recommendation").title()
        ev_pct = _format_ev_pct(row.get("ev_pct"))
        confidence = _safe_text(row.get("confidence"), "Unranked").title()
        odds = _format_moneyline(row.get("odds"))
        items.append(f"{rec_type}: {ev_pct} EV | {confidence} | Odds {odds}")
    if not items:
        items.append("No stored recommendation rows were available for this matchup.")
    return items


def _top_play_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    top_rows: list[dict[str, str]] = []
    for row in rows[:4]:
        confidence = _safe_text(row.get("confidence"), "Unranked").title()
        odds = _format_moneyline(row.get("odds"))
        top_rows.append(
            {
                "name": _safe_text(row.get("type"), "Recommendation").title(),
                "value": _format_ev_pct(row.get("ev_pct")),
                "detail": f"{confidence} | Odds {odds}",
            }
        )
    return top_rows


def _sort_bundles(bundles: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    normalized_sort = _safe_text(sort, "date").lower()

    def _metric(bundle: dict[str, Any], key: str) -> float:
        value = _safe_float(bundle.get(key))
        return value if value is not None else float("-inf")

    if normalized_sort == "winner":
        return sorted(bundles, key=lambda bundle: (_metric(bundle, "moneyline_ev"), _metric(bundle, "top_ev")), reverse=True)
    if normalized_sort == "ats":
        return sorted(bundles, key=lambda bundle: (_metric(bundle, "spread_ev"), _metric(bundle, "top_ev")), reverse=True)
    if normalized_sort == "total":
        return sorted(bundles, key=lambda bundle: (_metric(bundle, "total_ev"), _metric(bundle, "top_ev")), reverse=True)
    return sorted(bundles, key=lambda bundle: (bundle.get("game_date") or "", -_metric(bundle, "top_ev")))


def _available_card_weeks(season: int | None = None) -> list[int]:
    resolved_season = int(season or latest_season())
    return sorted(week for week in available_weeks(resolved_season) if int(week) > 0)


def _resolved_week(selected_week: int, *, season: int | None = None) -> int:
    resolved_season = int(season or latest_season())
    try:
        requested_week = int(selected_week)
    except Exception:
        requested_week = int(default_week(resolved_season))
    return resolve_selected_value(requested_week, _available_card_weeks(resolved_season), default_week(resolved_season))


def _game_from_snapshot_bundle(bundle: dict[str, Any], season: int, week: int) -> dict[str, Any]:
    away_team = _safe_text(bundle.get("away_team"), "Away")
    home_team = _safe_text(bundle.get("home_team"), "Home")
    away_abbr = _team_abbr(away_team)
    home_abbr = _team_abbr(home_team)
    away_branding = _resolve_branding(away_team)
    home_branding = _resolve_branding(home_team)
    game_date = _safe_text(bundle.get("game_date"), "TBD")
    ordered_rows = bundle.get("rows") if isinstance(bundle.get("rows"), list) else []
    top_row = bundle.get("top_row") if isinstance(bundle.get("top_row"), dict) else {}
    top_ev = _safe_float(bundle.get("top_ev"))
    top_type = _safe_text(top_row.get("type"), "Recommendation").title()
    confidence = _safe_text(bundle.get("confidence"), "Snapshot").title()
    game_pk = f"{season}-{week}-{game_date}-{away_abbr}-{home_abbr}".replace(" ", "-")
    summary = (
        f"Stored weekly recommendation rows for {away_team} at {home_team}. "
        f"Top signal: {top_type} at {_format_ev_pct(top_ev)} EV."
    )
    return {
        "gamePk": game_pk,
        "card_variant": "shared_default",
        "away": {
            "abbr": away_abbr,
            "name": away_team,
            "logo_url": away_branding.logo_url if away_branding else None,
            "primary_color": away_branding.primary_color if away_branding else None,
            "secondary_color": away_branding.secondary_color if away_branding else None,
        },
        "home": {
            "abbr": home_abbr,
            "name": home_team,
            "logo_url": home_branding.logo_url if home_branding else None,
            "primary_color": home_branding.primary_color if home_branding else None,
            "secondary_color": home_branding.secondary_color if home_branding else None,
        },
        "href": f"/nfl/game/{game_pk}?season={season}&week={week}",
        "href_label": "Open NFL game detail",
        "status": f"Week {week}",
        "detail": game_date,
        "summary": summary,
        "metrics": [
            {"label": "Kickoff", "value": game_date},
            {"label": "Signals", "value": str(len(ordered_rows))},
            {"label": "Top EV", "value": _format_ev_pct(top_ev)},
            {"label": "Best signal", "value": top_type},
        ],
        "shared_top_play_rows": _top_play_rows(ordered_rows),
        "panels": [
            {
                "eyebrow": "Weekly snapshot",
                "title": confidence,
                "body": "NFL cards now summarize the stored weekly recommendation snapshot for this matchup instead of proxying the sibling source app.",
                "items": _official_items(ordered_rows),
            },
            {
                "eyebrow": "Signal mix",
                "title": f"Top EV {_format_ev_pct(top_ev)} | {len(ordered_rows)} stored rows",
                "body": "Snapshot rows are grouped by matchup so cards, game detail, and live lens can share the same local weekly artifact lane.",
                "items": [
                    f"Moneyline rows: {sum(1 for row in ordered_rows if _safe_text(row.get('type')).upper() == 'MONEYLINE')}",
                    f"Spread rows: {sum(1 for row in ordered_rows if _safe_text(row.get('type')).upper() == 'SPREAD')}",
                    f"Total rows: {sum(1 for row in ordered_rows if _safe_text(row.get('type')).upper() == 'TOTAL')}",
                ],
            },
            {
                "eyebrow": "Game context",
                "title": f"{season} Week {week}",
                "body": f"{away_team} at {home_team} on {game_date}.",
                "items": [
                    f"Teams: {away_team} at {home_team}",
                    f"Snapshot-backed game key: {game_pk}",
                    "Pick-side fields are not preserved in the weekly snapshot, so this board summarizes stored signal types and EV instead of full source-card parity.",
                ],
            },
        ],
    }


def build_cards_page_context(selected_week: int, *, season: int | None = None, sort: str = "date") -> dict[str, Any]:
    resolved_season = int(season or latest_season())
    resolved_week = _resolved_week(selected_week or default_week(resolved_season), season=resolved_season)
    season = resolved_season
    rows = list(_read_snapshot_rows(season, resolved_week))
    bundles = _sort_bundles(_group_snapshot_rows(rows), sort)
    games = [_game_from_snapshot_bundle(bundle, season, resolved_week) for bundle in bundles]
    using_sample_data = False

    weeks = _available_card_weeks(season)
    prev_week, next_week = neighboring_values(weeks, resolved_week, fallback=resolved_week)
    scoreboard_items = [
        {
            "target_id": f"game-{game['gamePk']}",
            "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
            "status": game["status"],
        }
        for game in games
    ]
    source_path = _snapshot_source_path(season, resolved_week)
    return apply_game_board_contract(
        {
            "date": f"{season} Week {resolved_week}",
            "requested_date": f"{season} Week {selected_week}",
            "prev_date": str(prev_week),
            "next_date": str(next_week),
            "control_action": "/nfl/cards",
            "controls_prev_href": f"/nfl/cards?season={season}&week={prev_week}",
            "controls_next_href": f"/nfl/cards?season={season}&week={next_week}",
            "control_label": "Week",
            "control_type": "number",
            "control_name": "week",
            "control_value": str(resolved_week),
            "hidden_fields": [{"name": "season", "value": str(season)}],
            "module_links": build_module_links(resolved_week, "Cards", season=season),
            "games": games,
            "scoreboard_items": scoreboard_items,
            "source_path": source_path,
            "source_title": "NFL weekly recommendation snapshot" if games else "NFL cards unavailable",
            "empty_state": {
                "eyebrow": "NFL cards",
                "title": "No game cards were available for this week",
                "body": "The cards board only renders stored NFL weekly recommendation snapshots, and none were available for the requested season and week.",
                "list_items": [
                    f"Season: {season}",
                    f"Week: {selected_week}",
                ],
            } if not games else None,
            "using_sample_data": using_sample_data,
            "route_path": "/nfl/cards",
            "intro_title": "NFL Cards",
            "intro_body": "NFL cards now aggregate stored weekly recommendation snapshots into a shared matchup board, so cards, game detail, and live lens can run from the local mirror lane.",
            "cards_control_links": [
                {"label": "Betting Card", "href": f"/nfl/season/{season}/betting-card?week={resolved_week}"},
                {"label": "Picks", "href": f"/nfl/picks?season={season}&week={resolved_week}"},
                {"label": "Live Lens", "href": f"/nfl/live-lens?season={season}&week={resolved_week}"},
            ],
            "header_stats": [
                {"label": "Games", "value": str(len(games))},
                {"label": "Season", "value": str(season)},
                {"label": "Week", "value": str(resolved_week)},
                {"label": "Source", "value": "Snapshot" if games else "No data"},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "active_sport_name": "NFL",
        },
        sport="nfl",
        module="cards",
        source_kind="local_artifact",
        live_lens_integrated=False,
    )


# ---------------------------------------------------------------------------
# Market board (Layer 1) -- real market odds joined against real SmartSim 2.0
# projections (syndicate/features/nfl/smartsim2_projection.py, generated by
# scripts/generate_smartsim2_nfl_projections.py). Independent of the
# recs-snapshot-based build_cards_page_context above -- that page's data
# source and this one aren't related, deliberately not touched here.
# ---------------------------------------------------------------------------


def nfl_projection_available_weeks(season: int) -> list[int]:
    """Weeks that actually have a generated smartsim2_projections_{season}_wk*.csv
    artifact -- NOT syndicate.features.nfl.sources.available_weeks(), which
    tracks the unrelated upcoming_recs_*.csv snapshot (only weeks 17/19/21
    exist there for season 2025) and would silently break market-board
    week navigation for any week this session generated projections for."""
    pattern = str(default_nfl_source_root() / f"smartsim2_projections_{season}_wk*.csv")
    weeks: list[int] = []
    for path in glob.glob(pattern):
        match = re.search(r"_wk(\d+)\.csv$", path)
        if match:
            weeks.append(int(match.group(1)))
    return sorted(set(weeks))


@lru_cache(maxsize=8)
def _nfl_real_lines_index(season: int) -> dict[str, dict[str, Any]]:
    """Every real quoted line for a season, keyed by "{away} @ {home}" full
    team names -- merges every daily real_betting_lines_{season}_*.json
    file's "lines" dict. A team pair meeting twice in a season (rare, e.g.
    a divisional rematch) would have the later file's entry win; accepted
    simplification for a first pass."""
    index: dict[str, dict[str, Any]] = {}
    pattern = os.path.join(str(default_nfl_source_root()), f"real_betting_lines_{season}_*.json")
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            continue
        lines = payload.get("lines") if isinstance(payload, dict) else None
        if isinstance(lines, dict):
            index.update(lines)
    return index


def _nfl_real_lines_for_matchup(season: int, *, away_full_name: str, home_full_name: str) -> dict[str, Any] | None:
    return _nfl_real_lines_index(season).get(f"{away_full_name} @ {home_full_name}")


def _nfl_cover_probability(*, line: float, mean: float | None, stdev: float | None) -> float | None:
    """P(actual > line) under a Normal(mean, stdev) model -- mirrors
    syndicate.features.ncaaf.cards._ncaaf_cover_probability exactly (same
    reasoning: a raw margin/total point estimate is not a probability and
    must never be dropped into a field the board renders as a percentage;
    None when there's no stdev to draw a real probability from)."""
    if mean is None or stdev is None or stdev <= 0:
        return None
    return 1.0 - statistics.NormalDist(mean, stdev).cdf(line)


_NFL_MARKET_BOARD_DISPLAY_LABELS = {
    "moneyline_home": "Moneyline",
    "moneyline_away": "Moneyline",
    "spread": "Spread",
    "total": "Total",
}


def _nfl_market_board_rows_for_game(
    *,
    game_id: Any,
    home_moneyline: Any,
    away_moneyline: Any,
    spread_line: Any,
    total_line: Any,
    model_margin: Any,
    model_total: Any,
    model_margin_stdev: Any,
    model_total_stdev: Any,
    home_win_probability: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Raw odds + sim rows for one NFL game's moneyline/spread/total
    markets -- mirrors syndicate.features.ncaaf.cards._ncaaf_market_board_rows_for_game.
    No player-prop rows: no props pipeline exists for NFL yet."""
    odds_rows: list[dict[str, Any]] = []
    sim_rows: list[dict[str, Any]] = []

    home_prob = None
    try:
        home_prob = float(home_win_probability) if home_win_probability is not None else None
    except (TypeError, ValueError):
        home_prob = None
    if home_moneyline is not None and away_moneyline is not None:
        odds_rows.append({"game_id": game_id, "market": "moneyline_home", "period": "full_game", "entity": None, "side": "home", "odds": home_moneyline, "market_type": "game"})
        odds_rows.append({"game_id": game_id, "market": "moneyline_away", "period": "full_game", "entity": None, "side": "away", "odds": away_moneyline, "market_type": "game"})
        if home_prob is not None:
            model_side = "home" if home_prob >= 0.5 else "away"
            sim_rows.append({"game_id": game_id, "market": "moneyline_home", "period": "full_game", "entity": None, "sim_projection": home_prob, "model_side": model_side, "sim_source": "nfl_model"})
            sim_rows.append({"game_id": game_id, "market": "moneyline_away", "period": "full_game", "entity": None, "sim_projection": 1.0 - home_prob, "model_side": model_side, "sim_source": "nfl_model"})

    try:
        margin_line = float(spread_line) if spread_line is not None else None
    except (TypeError, ValueError):
        margin_line = None
    if margin_line is not None:
        odds_rows.append({"game_id": game_id, "market": "spread", "period": "full_game", "entity": None, "side": "home", "line": margin_line, "market_type": "game"})
        if model_margin is not None:
            cover_prob = _nfl_cover_probability(line=margin_line, mean=model_margin, stdev=model_margin_stdev)
            sim_rows.append({"game_id": game_id, "market": "spread", "period": "full_game", "entity": None, "sim_projection": cover_prob, "projected_value": model_margin, "sim_source": "nfl_model"})

    try:
        total_line_value = float(total_line) if total_line is not None else None
    except (TypeError, ValueError):
        total_line_value = None
    if total_line_value is not None:
        odds_rows.append({"game_id": game_id, "market": "total", "period": "full_game", "entity": None, "side": "over", "line": total_line_value, "market_type": "game"})
        if model_total is not None:
            over_prob = _nfl_cover_probability(line=total_line_value, mean=model_total, stdev=model_total_stdev)
            sim_rows.append({"game_id": game_id, "market": "total", "period": "full_game", "entity": None, "sim_projection": over_prob, "projected_value": model_total, "sim_source": "nfl_model"})

    return odds_rows, sim_rows


def build_nfl_market_board(season: int, week: int) -> dict[str, Any]:
    """Layer 1 market/odds inventory for NFL game markets (moneyline,
    spread, total) -- mirrors syndicate.features.ncaaf.cards.build_ncaaf_market_board.
    Games and the model signal both come from the real SmartSim 2.0
    projection artifact for this (season, week) -- see
    scripts/generate_smartsim2_nfl_projections.py; real market lines come
    from _nfl_real_lines_index. No player props."""
    projections = read_projection_artifact(season=season, week=week, data_root=default_nfl_source_root())
    weeks = nfl_projection_available_weeks(season)

    board_games: list[dict[str, Any]] = []
    for projection in projections:
        home_branding = _resolve_branding(projection.home_team)
        away_branding = _resolve_branding(projection.away_team)
        home_full_name = home_branding.display_name if home_branding else projection.home_team
        away_full_name = away_branding.display_name if away_branding else projection.away_team
        home_abbr = home_branding.abbreviation if home_branding else _team_abbr(projection.home_team)
        away_abbr = away_branding.abbreviation if away_branding else _team_abbr(projection.away_team)

        lines_entry = _nfl_real_lines_for_matchup(season, away_full_name=away_full_name, home_full_name=home_full_name)
        moneyline = (lines_entry or {}).get("moneyline") or {}
        run_line = (lines_entry or {}).get("run_line") or {}
        total_runs = (lines_entry or {}).get("total_runs") or {}

        odds_rows, sim_rows = _nfl_market_board_rows_for_game(
            game_id=projection.game_id,
            home_moneyline=moneyline.get("home"),
            away_moneyline=moneyline.get("away"),
            spread_line=run_line.get("home"),
            total_line=total_runs.get("line"),
            model_margin=projection.margin_mean,
            model_total=projection.total_mean,
            model_margin_stdev=projection.margin_stdev,
            model_total_stdev=projection.total_stdev,
            home_win_probability=projection.home_win_rate,
        )
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        for row in inventory:
            row["market"] = _NFL_MARKET_BOARD_DISPLAY_LABELS.get(row.get("market"), row.get("market"))

        board_games.append(
            {
                "gamePk": projection.game_id,
                "matchup": f"{away_abbr} @ {home_abbr}",
                "away_abbr": away_abbr,
                "home_abbr": home_abbr,
                "away_logo": away_branding.logo_url if away_branding else None,
                "home_logo": home_branding.logo_url if home_branding else None,
                "game_state": "pregame",
                "rows": inventory,
            }
        )

    return {
        "season": season,
        "week": week,
        "available_weeks": weeks,
        "games": board_games,
        "using_sample_data": False,
        "source_path": str(default_nfl_source_root() / f"smartsim2_projections_{season}_wk{week}.csv"),
    }