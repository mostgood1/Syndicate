from __future__ import annotations

from typing import Any


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _safe_text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _metric_lookup(metrics: list[dict[str, Any]], label: str) -> str | None:
    wanted = label.strip().lower()
    for metric in metrics:
        current = str(metric.get("label") or "").strip().lower()
        if current == wanted:
            return str(metric.get("value") or "").strip() or None
    return None


def _infer_live_state(game: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            str(game.get("status") or ""),
            str(game.get("detail") or ""),
            str(game.get("summary") or ""),
        ]
    ).lower()
    live_tokens = ("live", "in progress", "in-progress", "quarter", "period", "inning", "ot", "halftime", "intermission")
    final_tokens = ("final", "closed", "scheduled", "preview", "pregame", "historical", "processed artifact")
    if any(token in haystack for token in final_tokens):
        return False
    return any(token in haystack for token in live_tokens)


def _format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def _format_num(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}"


def _period_label(key: str) -> str:
    normalized = str(key or "").strip().lower()
    mapping = {
        "q1": "First 1",
        "q2": "First 2",
        "q3": "First 3",
        "q4": "First 4",
        "p1": "Period 1",
        "p2": "Period 2",
        "p3": "Period 3",
        "f1": "First 1",
        "f3": "First 3",
        "f5": "First 5",
        "f7": "First 7",
        "full": "Full Game",
    }
    return mapping.get(normalized, str(key or "Period").upper())


def _build_period_rows(game: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sim = game.get("sim") if isinstance(game.get("sim"), dict) else {}
    periods = sim.get("periods") if isinstance(sim.get("periods"), dict) else {}
    for key, value in periods.items():
        if not isinstance(value, dict):
            continue
        away_mean = _safe_float(value.get("away_mean"))
        home_mean = _safe_float(value.get("home_mean"))
        total_mean = _safe_float(value.get("total_mean"))
        margin_mean = _safe_float(value.get("margin_mean"))
        if (away_mean is None or home_mean is None) and total_mean is not None and margin_mean is not None:
            away_mean = round((total_mean - margin_mean) / 2.0, 3)
            home_mean = round((total_mean + margin_mean) / 2.0, 3)
        if total_mean is None and away_mean is not None and home_mean is not None:
            total_mean = away_mean + home_mean
        total = (away_mean or 0.0) + (home_mean or 0.0)
        away_pct = ((away_mean or 0.0) / total * 100.0) if total > 0 else 50.0
        home_pct = ((home_mean or 0.0) / total * 100.0) if total > 0 else 50.0
        p_home_win = _safe_float(value.get("p_home_win"))
        rows.append(
            {
                "label": _period_label(str(key)),
                "main": f"{game.get('away', {}).get('abbr', 'AWY')} {_format_num(away_mean)} - {game.get('home', {}).get('abbr', 'HME')} {_format_num(home_mean)}",
                "subtitle": f"Projected total {_format_num(total_mean)}",
                "away_pct": away_pct,
                "home_pct": home_pct,
                "home_win": _format_pct(p_home_win),
                "market": _metric_lookup(game.get("metrics", []), "Spread") or _metric_lookup(game.get("metrics", []), "Total") or "-",
                "best_edge": _metric_lookup(game.get("metrics", []), "Edge") or "-",
            }
        )
    if not rows:
        away_score = _metric_lookup(game.get("metrics", []), "Pred score") or game.get("summary")
        rows.append(
            {
                "label": "Full Game",
                "main": away_score or game.get("summary") or "Game outlook unavailable",
                "subtitle": game.get("detail") or game.get("status") or "-",
                "away_pct": 50.0,
                "home_pct": 50.0,
                "home_win": _metric_lookup(game.get("metrics", []), "Home win") or _metric_lookup(game.get("metrics", []), "Win prob") or "-",
                "market": _metric_lookup(game.get("metrics", []), "Spread") or _metric_lookup(game.get("metrics", []), "Total") or "-",
                "best_edge": _metric_lookup(game.get("metrics", []), "Edge") or "-",
            }
        )
    return rows


def _build_probability_rows(game: dict[str, Any], period_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = game.get("probability_rows") if isinstance(game.get("probability_rows"), list) else []
    rows: list[dict[str, Any]] = []
    for row in existing:
        if not isinstance(row, dict):
            continue
        away_pct = _safe_float(row.get("away_pct")) or 50.0
        home_pct = _safe_float(row.get("home_pct")) or max(0.0, 100.0 - away_pct)
        rows.append(
            {
                "label": _safe_text(row.get("label"), "Full Game"),
                "away_pct": away_pct,
                "home_pct": home_pct,
                "summary": _safe_text(row.get("summary"), "Probability split unavailable"),
            }
        )
    if rows:
        return rows
    fallback: list[dict[str, Any]] = []
    for row in period_rows:
        fallback.append(
            {
                "label": row.get("label") or "Full Game",
                "away_pct": float(row.get("away_pct") or 50.0),
                "home_pct": float(row.get("home_pct") or 50.0),
                "summary": f"Home win {row.get('home_win') or '-'}",
            }
        )
    return fallback[:5]


def _build_total_rows(period_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    numeric_totals = []
    for row in period_rows:
        subtitle = str(row.get("subtitle") or "")
        marker = subtitle.lower().split("projected total ")
        total = _safe_float(marker[-1]) if marker else None
        numeric_totals.append(total or 0.0)
    max_total = max(numeric_totals) if numeric_totals else 0.0
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(period_rows):
        total = numeric_totals[idx] if idx < len(numeric_totals) else 0.0
        width = (total / max_total * 100.0) if max_total > 0 else 0.0
        out.append(
            {
                "label": row.get("label") or "Full Game",
                "summary": row.get("subtitle") or "Projected total unavailable",
                "bins": [{"width": width, "total": _format_num(total), "pct": f"{width:.1f}"}] if width > 0 else [],
            }
        )
    return out


def _rows_from_table_groups(table_groups: list[dict[str, Any]], *, limit: int = 6) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for group in table_groups:
        if not isinstance(group, dict):
            continue
        heading = _safe_text(group.get("heading"), "Board")
        for row in group.get("rows") or []:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "heading": heading,
                    "name": _safe_text(row.get("name"), "Play"),
                    "detail": _safe_text(row.get("detail"), ""),
                    "value": _safe_text(row.get("value"), "-"),
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def _build_top_play_rows(game: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for panel in game.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        heading = _safe_text(panel.get("title"), panel.get("eyebrow") or "Top plays")
        rows.extend(_rows_from_table_groups(panel.get("table_groups") or [], limit=max(0, 6 - len(rows))))
        if len(rows) >= 6:
            break
        for item in panel.get("items") or []:
            item_text = _safe_text(item, "")
            if not item_text:
                continue
            rows.append({"heading": heading, "name": item_text, "detail": _safe_text(panel.get("body"), ""), "value": heading})
            if len(rows) >= 6:
                break
        if len(rows) >= 6:
            break
    return rows


def _build_prop_rows(game: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    prop_recs = game.get("prop_recommendations") if isinstance(game.get("prop_recommendations"), dict) else {}
    for side_key, heading in (("away", game.get("away", {}).get("abbr", "Away")), ("home", game.get("home", {}).get("abbr", "Home"))):
        for row in prop_recs.get(side_key) or []:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "heading": f"{heading} props",
                    "name": _safe_text(row.get("player") or row.get("display_pick"), "Prop"),
                    "detail": _safe_text(row.get("display_pick") or row.get("market"), ""),
                    "value": _safe_text(row.get("tier") or row.get("line") or row.get("price"), "-"),
                    "photo": row.get("photo") or row.get("player_photo") or row.get("headshot_url"),
                    "headshot_url": row.get("headshot_url") or row.get("photo") or row.get("player_photo"),
                    "pick": _safe_text(row.get("display_pick") or row.get("pick") or row.get("selection"), ""),
                    "market": _safe_text(row.get("market") or row.get("market_label") or row.get("type_label"), ""),
                    "line": row.get("line"),
                    "market_line": row.get("market_line") or row.get("line"),
                    "actual": row.get("actual") or row.get("actual_value") or row.get("actual_total"),
                    "projected": row.get("projected") or row.get("projection") or row.get("model_mean"),
                    "live_projection": row.get("live_projection") or row.get("liveProjection") or row.get("projection_live"),
                    "odds": row.get("price") or row.get("odds") or row.get("price_american"),
                    "confidence": row.get("confidence") or row.get("prob") or row.get("win_prob"),
                    "selection": row.get("selection") or row.get("side"),
                    "game_state": row.get("game_state") or row.get("state") or row.get("status") or row.get("status_label"),
                    "live_total": row.get("live_total") or row.get("live_total_line"),
                    "live_total_line": row.get("live_total_line") or row.get("live_line_total"),
                    "outcome_state": row.get("outcome_state") or row.get("actual_result") or row.get("result"),
                    "outcome_label": row.get("outcome_label"),
                }
            )
            if len(rows) >= 8:
                return rows
    if rows:
        return rows
    for panel in game.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        title = f"{str(panel.get('eyebrow') or '')} {str(panel.get('title') or '')}".lower()
        if "prop" not in title:
            continue
        rows.extend(_rows_from_table_groups(panel.get("table_groups") or [], limit=max(0, 8 - len(rows))))
        for item in panel.get("items") or []:
            item_text = _safe_text(item, "")
            if not item_text:
                continue
            rows.append({"heading": _safe_text(panel.get("title"), "Props"), "name": item_text, "detail": _safe_text(panel.get("body"), ""), "value": _safe_text(panel.get("eyebrow"), "Props")})
            if len(rows) >= 8:
                return rows
    return rows


def _build_box_sections(game: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    sim = game.get("sim") if isinstance(game.get("sim"), dict) else {}
    score = sim.get("score") if isinstance(sim.get("score"), dict) else {}
    away_abbr = _safe_text(game.get("away", {}).get("abbr"), "AWY")
    home_abbr = _safe_text(game.get("home", {}).get("abbr"), "HME")
    away_mean = _safe_float(score.get("away_mean"))
    home_mean = _safe_float(score.get("home_mean"))
    if away_mean is not None or home_mean is not None:
        sections.append(
            {
                "title": "Sim game box",
                "body": "Pregame and in-play sim scoring expectations stay pinned in the box score tab.",
                "rows": [
                    {"name": away_abbr, "detail": game.get("away", {}).get("name") or away_abbr, "value": _format_num(away_mean)},
                    {"name": home_abbr, "detail": game.get("home", {}).get("name") or home_abbr, "value": _format_num(home_mean)},
                ],
            }
        )
    for panel in game.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        title = f"{str(panel.get('eyebrow') or '')} {str(panel.get('title') or '')}".lower()
        if "sim" not in title and "box" not in title and "player outcome" not in title:
            continue
        rows = _rows_from_table_groups(panel.get("table_groups") or [], limit=6)
        if rows:
            sections.append(
                {
                    "title": _safe_text(panel.get("title"), "Sim detail"),
                    "body": _safe_text(panel.get("body"), ""),
                    "rows": rows,
                }
            )
        if len(sections) >= 2:
            break
    if not sections:
        sections.append(
            {
                "title": "Box score unavailable",
                "body": "This sport has not shipped a live box-score lane into the shared board yet, so only the game summary is currently available.",
                "rows": [],
            }
        )
    return sections


def _normalize_game(game: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(game, dict):
        return game
    if str(game.get("card_variant") or "") == "mlb_main":
        return game
    normalized = dict(game)
    metrics = normalized.get("metrics") if isinstance(normalized.get("metrics"), list) else []
    period_rows = _build_period_rows(normalized)
    normalized.setdefault("market_tiles", [{"label": metric.get("label"), "title": metric.get("value"), "sub": f"{normalized.get('away', {}).get('abbr', 'AWY')} @ {normalized.get('home', {}).get('abbr', 'HME')}"} for metric in metrics[:4]])
    normalized["shared_is_live"] = _infer_live_state(normalized)
    normalized["shared_period_rows"] = period_rows
    normalized["shared_probability_rows"] = _build_probability_rows(normalized, period_rows)
    normalized["shared_total_rows"] = _build_total_rows(period_rows)
    normalized["shared_box_sections"] = _build_box_sections(normalized)
    normalized["shared_prop_rows"] = _build_prop_rows(normalized)
    normalized["shared_top_play_rows"] = _build_top_play_rows(normalized)
    normalized["shared_tab_game_title"] = "Live game lens" if normalized["shared_is_live"] else "Period odds and game lens"
    normalized["shared_tab_props_title"] = "Live props" if normalized["shared_is_live"] else "Official and playable props"
    return normalized


def _normalize_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_normalize_game(game) for game in games if isinstance(game, dict)]


def apply_game_board_contract(
    context: dict[str, Any],
    *,
    sport: str,
    module: str,
    surface: str | None = None,
    schema: str = "game_board_v1",
    source_kind: str = "artifact_backed",
    live_lens_integrated: bool = True,
) -> dict[str, Any]:
    out = dict(context)
    games = out.get("games") if isinstance(out.get("games"), list) else []
    out["games"] = _normalize_games(games)
    normalized_sport = str(sport or "sport").strip().lower() or "sport"
    out.setdefault("show_app_header", False)
    out.setdefault("show_standalone_cards_header", str(module or "").strip().lower() == "cards")
    out.setdefault("active_sport_slug", normalized_sport)
    out.setdefault("active_sport_name", normalized_sport.upper())
    out.setdefault("show_intro", False)
    out.setdefault("show_source_summary", False)
    if not out.get("control_action"):
        out["control_action"] = out.get("route_path")
    if not out.get("control_value"):
        out["control_value"] = out.get("date")
    if not out.get("control_label"):
        out["control_label"] = "Date"
    if not out.get("control_type"):
        out["control_type"] = "date"
    if not out.get("control_name"):
        out["control_name"] = "date"
    out.setdefault("page_body_class", f"cards-body syndicate-{normalized_sport}-cards-page")
    out.setdefault("page_shell_class", f"syndicate-{normalized_sport}-cards-shell")
    out.setdefault("cards_grid_class", "mlb-cards-grid")
    out.setdefault("cards_stylesheet", f"{normalized_sport}/cards.css")
    resolved_surface = str(surface or f"{normalized_sport}_dense_board_v1").strip() or f"{normalized_sport}_dense_board_v1"
    out["board_contract"] = {
        "schema": schema,
        "surface": resolved_surface,
        "sport": normalized_sport,
        "module": str(module or "board").strip().lower() or "board",
        "source_kind": source_kind,
        "live_lens_integrated": bool(live_lens_integrated),
    }
    return out


def build_game_board_api_payload(context: dict[str, Any]) -> dict[str, Any]:
    games = context.get("games", [])
    using_sample_data = context.get("using_sample_data", False)
    source_path = context.get("source_path")
    requested_date = context.get("requested_date", context["date"])
    pregame_portfolio = context.get("pregame_portfolio")
    if not isinstance(pregame_portfolio, dict):
        pregame_portfolio = {"enabled": False, "selected": 0, "candidates": 0}
    payload = {
        "date": context["date"],
        "requested_date": requested_date,
        "lookahead_applied": bool(context.get("lookahead_applied", False)),
        "pregame_portfolio": pregame_portfolio,
        "games": games,
        "cards": games,
        "scoreboard": context.get("scoreboard_items", []),
        "using_sample_data": using_sample_data,
        "usingSampleData": using_sample_data,
        "hasSampleData": not bool(using_sample_data),
        "hasArtifactData": not bool(using_sample_data),
        "source_path": source_path,
        "sourcePath": source_path,
        "board_contract": context.get("board_contract", {}),
    }
    if "prev_date" in context or "next_date" in context:
        payload["nav"] = {
            "prevDate": context.get("prev_date"),
            "nextDate": context.get("next_date"),
        }
    optional_keys = (
        "header_stats",
        "source_title",
        "empty_state",
        "has_games_on_slate",
        "route_path",
        "module_links",
        "teaser",
        "control_action",
        "controls_prev_href",
        "controls_next_href",
        "control_value",
        "control_label",
        "control_type",
        "control_name",
        "hidden_fields",
        "generatedAt",
        "counts",
        "app",
        "dataRoot",
        "liveLensDir",
        "optimizationRegime",
        "performance",
    )
    for key in optional_keys:
        if key in context:
            payload[key] = context.get(key)
    return payload


def build_single_game_board_context(
    *,
    selected_date: str,
    prev_date: str,
    next_date: str,
    game: dict[str, Any],
    game_pk: str | int,
    module_links: list[dict[str, Any]],
    source_path: str,
    source_title: str,
    using_sample_data: bool,
    route_path: str,
    intro_title: str,
    intro_body: str,
    teaser: dict[str, Any],
    cards_grid_class: str,
    cards_stylesheet: str,
    sport: str,
    module: str,
    header_stats: list[dict[str, str]] | None = None,
    control_action: str | None = None,
    controls_prev_href: str | None = None,
    controls_next_href: str | None = None,
    control_value: str | None = None,
    control_label: str | None = None,
    control_type: str | None = None,
    control_name: str | None = None,
    hidden_fields: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    scoreboard_items = [
        {
            "target_id": f"game-{game['gamePk']}",
            "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
            "status": game["detail"],
        }
    ]
    return apply_game_board_contract(
        {
            "date": selected_date,
            "prev_date": prev_date,
            "next_date": next_date,
            "module_links": module_links,
            "games": [game],
            "scoreboard_items": scoreboard_items,
            "source_path": source_path,
            "using_sample_data": using_sample_data,
            "source_title": source_title,
            "header_stats": header_stats
            or [
                {"label": "Game", "value": str(game_pk)},
                {"label": "Away", "value": game["away"]["abbr"]},
                {"label": "Home", "value": game["home"]["abbr"]},
            ],
            "route_path": route_path,
            "intro_title": intro_title,
            "intro_body": intro_body,
            "cards_grid_class": cards_grid_class,
            "cards_stylesheet": cards_stylesheet,
            "teaser": teaser,
            "control_action": control_action,
            "controls_prev_href": controls_prev_href,
            "controls_next_href": controls_next_href,
            "control_value": control_value,
            "control_label": control_label,
            "control_type": control_type,
            "control_name": control_name,
            "hidden_fields": list(hidden_fields or []),
        },
        sport=sport,
        module=module,
    )