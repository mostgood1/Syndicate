from __future__ import annotations

import csv
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.wnba.sources import available_dates
from syndicate.features.wnba.sources import build_module_links
from syndicate.features.wnba.sources import format_moneyline
from syndicate.features.wnba.sources import format_num
from syndicate.features.wnba.sources import format_signed_num
from syndicate.features.wnba.sources import load_json
from syndicate.features.wnba.sources import live_snapshot_path
from syndicate.features.wnba.sources import market_label
from syndicate.features.wnba.sources import parse_iso_date
from syndicate.features.wnba.sources import processed_path


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


def _recommendation_index(summary: dict[str, Any] | None) -> dict[tuple[str, str], list[dict[str, Any]]]:
    per_game = summary.get("per_game") if isinstance((summary or {}).get("per_game"), list) else []
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in per_game:
        if not isinstance(item, dict):
            continue
        away = str(item.get("away") or "").strip().upper()
        home = str(item.get("home") or "").strip().upper()
        picks = item.get("picks") if isinstance(item.get("picks"), list) else []
        if away and home:
            index[(away, home)] = [pick for pick in picks if isinstance(pick, dict)]
    return index


def _artifact_games_index(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    payload = load_json(path)
    games = payload.get("games") if isinstance((payload or {}).get("games"), list) else []
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for game in games:
        if not isinstance(game, dict):
            continue
        away = str(game.get("away_tri") or "").strip().upper()
        home = str(game.get("home_tri") or "").strip().upper()
        if away and home:
            index[(away, home)] = game
    return index


def _nearest_available_cards_date(selected_date: str) -> str | None:
    dates = available_dates()
    if not dates:
        return None
    if selected_date in dates:
        return selected_date
    parsed_selected = parse_iso_date(selected_date)
    dated_values = sorted((parse_iso_date(value), value) for value in dates)
    for parsed_value, value in dated_values:
        if parsed_value >= parsed_selected:
            return value
    return dated_values[-1][1]


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _format_pct_100(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    return f"{number:.1f}%"


def _top_pick_items(picks: list[dict[str, Any]], *, limit: int = 4) -> tuple[list[str], list[dict[str, Any]]]:
    valid_picks = [pick for pick in picks if isinstance(pick, dict)]
    items = [str(pick.get("display_pick") or "").strip() for pick in valid_picks[:limit] if str(pick.get("display_pick") or "").strip()]
    rows = []
    for pick in valid_picks[:limit]:
        label = str(pick.get("player") or pick.get("display_pick") or "").strip()
        if not label:
            continue
        detail_bits = []
        market = market_label(pick.get("market"))
        line = format_num(pick.get("line"))
        side = str(pick.get("side") or pick.get("selection") or "").strip().upper()
        if market != "-" and line != "-":
            detail_bits.append(f"{side} {line} {market}".strip())
        ev_pct = _safe_float(pick.get("ev_pct"))
        if ev_pct is not None:
            detail_bits.append(f"EV {ev_pct:.1f}%")
        win_prob = _safe_float(pick.get("p_win"))
        value = f"{win_prob * 100:.1f}% win" if win_prob is not None else str(pick.get("tier") or "Top play")
        rows.append({"name": label, "detail": " | ".join(detail_bits), "value": value})
    return items, rows


def _sim_table_groups(sim_game: dict[str, Any] | None, away_tri: str, home_tri: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not isinstance(sim_game, dict):
        return [], []
    sim = sim_game.get("sim") if isinstance(sim_game.get("sim"), dict) else {}
    summary = sim.get("players_summary") if isinstance(sim.get("players_summary"), dict) else {}
    stats = [
        {"label": "Away sims", "value": str(summary.get("away") or "-")},
        {"label": "Home sims", "value": str(summary.get("home") or "-")},
        {"label": "Missing", "value": f"{summary.get('missing_away') or 0}/{summary.get('missing_home') or 0}"},
        {"label": "Injured", "value": f"{summary.get('injured_away') or 0}/{summary.get('injured_home') or 0}"},
    ]
    table_groups = []
    players = sim.get("players") if isinstance(sim.get("players"), dict) else {}
    for side_key, label in (("away", away_tri), ("home", home_tri)):
        rows = players.get(side_key) if isinstance(players.get(side_key), list) else []
        top_rows = sorted(
            [row for row in rows if isinstance(row, dict)],
            key=lambda row: (_safe_float(row.get("pra_mean")) or 0.0, _safe_float(row.get("pts_mean")) or 0.0),
            reverse=True,
        )[:4]
        if not top_rows:
            continue
        table_groups.append(
            {
                "heading": f"{label} sim leaders",
                "rows": [
                    {
                        "name": str(row.get("player_name") or "Player").strip() or "Player",
                        "detail": (
                            f"PTS {format_num(row.get('pts_mean'))} | REB {format_num(row.get('reb_mean'))} | AST {format_num(row.get('ast_mean'))}"
                        ),
                        "value": f"PRA {format_num(row.get('pra_mean'))}",
                    }
                    for row in top_rows
                ],
            }
        )
    return table_groups, stats


def _props_table_groups(props_game: dict[str, Any] | None, away_tri: str, home_tri: str) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(props_game, dict):
        return [], []
    prop_recommendations = props_game.get("prop_recommendations") if isinstance(props_game.get("prop_recommendations"), dict) else {}
    table_groups = []
    items: list[str] = []
    for side_key, label in (("away", away_tri), ("home", home_tri)):
        rows = prop_recommendations.get(side_key) if isinstance(prop_recommendations.get(side_key), list) else []
        side_items, side_rows = _top_pick_items(rows)
        items.extend(side_items)
        if side_rows:
            table_groups.append({"heading": f"{label} props", "rows": side_rows})
    return table_groups, items[:4]


def _artifact_paths(selected_date: str) -> dict[str, Path]:
    return {
        "cards": processed_path(f"game_cards_{selected_date}.csv"),
        "recommendations": processed_path(f"recommendations_slate_{selected_date}.json"),
        "sim": processed_path(f"cards_sim_detail_{selected_date}.json"),
        "props": processed_path(f"cards_props_snapshot_{selected_date}.json"),
    }


def _artifact_bundle(selected_date: str) -> dict[str, Any]:
    paths = _artifact_paths(selected_date)
    rows = _load_csv_rows(paths["cards"])
    rec_summary = load_json(paths["recommendations"])
    return {
        "paths": paths,
        "rows": rows,
        "recommendations": _recommendation_index(rec_summary),
        "sim": _artifact_games_index(paths["sim"]),
        "props": _artifact_games_index(paths["props"]),
    }


def _source_logo_url(team_tri: str) -> str:
    return f"/wnba/api/source/team-logo/{str(team_tri or '').strip().upper()}"


def _source_market_label(value: Any) -> str:
    code = str(value or "").strip().lower()
    return {
        "pts": "Points",
        "reb": "Rebounds",
        "ast": "Assists",
        "pra": "PRA",
        "pa": "PTS+AST",
        "pr": "PTS+REB",
        "ra": "REB+AST",
        "threes": "3PM",
        "blk": "Blocks",
        "stl": "Steals",
        "bs": "BLK+STL",
    }.get(code, market_label(value))


def _source_game_market_recommendations(picks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        rows.append(
            {
                "market_label": _source_market_label(pick.get("market")),
                "display_pick": str(pick.get("display_pick") or pick.get("selection") or "").strip() or None,
                "selection": str(pick.get("selection") or pick.get("side") or "").strip().upper() or None,
                "p_win": _safe_float(pick.get("p_win") or pick.get("win_prob")),
                "ev_pct": _safe_float(pick.get("ev_pct")),
                "basketball_summary": str(pick.get("basketball_summary") or "").strip() or None,
                "why_explain": str(pick.get("basketball_summary") or pick.get("display_pick") or "").strip() or None,
                "card_bucket": "playable",
                "recommendation_priority_score": _safe_float(pick.get("recommendation_priority_score") or pick.get("basketball_priority_score") or pick.get("score")),
                "score": _safe_float(pick.get("score") or pick.get("ev_pct")),
                "stake_amount": None,
                "stake_units": None,
                "portfolio_rank": None,
                "portfolio_score": None,
            }
        )
    return rows


def _source_betting(row: dict[str, str]) -> dict[str, Any]:
    home_ml = _safe_float(row.get("home_ml"))
    away_ml = _safe_float(row.get("away_ml"))
    home_spread = _safe_float(row.get("home_spread"))
    total = _safe_float(row.get("total"))
    return {
        "home_ml": home_ml,
        "away_ml": away_ml,
        "home_spread": home_spread,
        "total": total,
        "home_ml_ev": None,
        "away_ml_ev": None,
        "home_spread_ev": None,
        "away_spread_ev": None,
        "over_ev": None,
        "under_ev": None,
        "p_home_win": None,
        "p_away_win": None,
        "p_home_cover": None,
        "p_away_cover": None,
        "p_total_over": None,
        "p_total_under": None,
    }


def _source_sim_stub(game_id: str, sim_game: dict[str, Any] | None, row: dict[str, str]) -> dict[str, Any]:
    players_summary = dict((sim_game or {}).get("players_summary") or {}) if isinstance(sim_game, dict) else {}
    return {
        "game_id": game_id,
        "players_loaded": False,
        "players_summary": {
            "away": int(players_summary.get("away") or 0),
            "home": int(players_summary.get("home") or 0),
            "missing_away": int(players_summary.get("missing_away") or 0),
            "missing_home": int(players_summary.get("missing_home") or 0),
            "injured_away": int(players_summary.get("injured_away") or 0),
            "injured_home": int(players_summary.get("injured_home") or 0),
        },
        "players": {"away": [], "home": []},
        "missing_prop_players": {"away": [], "home": []},
        "injuries": {"away": [], "home": []},
        "score": {
            "away_mean": None,
            "home_mean": None,
            "total_mean": _safe_float(row.get("total")),
            "margin_mean": None,
        },
        "market": {
            "market_home_spread": _safe_float(row.get("home_spread")),
            "market_total": _safe_float(row.get("total")),
        },
    }


def _source_game_from_row(
    row: dict[str, str],
    *,
    idx: int,
    selected_date: str,
    rec_index: dict[tuple[str, str], list[dict[str, Any]]],
    sim_index: dict[tuple[str, str], dict[str, Any]],
    props_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    away_name = str(row.get("visitor_team") or "Away").strip() or "Away"
    home_name = str(row.get("home_team") or "Home").strip() or "Home"
    away_tri = str(row.get("away_tri") or away_name[:3]).strip().upper() or "AWY"
    home_tri = str(row.get("home_tri") or home_name[:3]).strip().upper() or "HOM"
    picks = rec_index.get((away_tri, home_tri), [])
    sim_game = sim_index.get((away_tri, home_tri))
    props_game = props_index.get((away_tri, home_tri)) if isinstance(props_index.get((away_tri, home_tri)), dict) else {}
    game_id = str(row.get("game_id") or idx)
    return {
        "game_id": game_id,
        "gamePk": game_id,
        "away_tri": away_tri,
        "away_name": away_name,
        "home_tri": home_tri,
        "home_name": home_name,
        "away": away_tri,
        "home": home_tri,
        "away_logo": _source_logo_url(away_tri),
        "home_logo": _source_logo_url(home_tri),
        "start_time": str(row.get("commence_time") or "").strip() or None,
        "odds": {"commence_time": str(row.get("commence_time") or "").strip() or None},
        "status": {"detailed": str(row.get("commence_time") or "Scheduled").strip() or "Scheduled"},
        "summary": f"{row.get('bookmaker') or 'Consensus'} market snapshot",
        "betting": _source_betting(row),
        "sim": _source_sim_stub(game_id, sim_game, row),
        "prop_recommendations": dict((props_game or {}).get("prop_recommendations") or {"away": [], "home": []}),
        "game_market_recommendations": _source_game_market_recommendations(picks),
        "live_state": None,
        "warnings": [],
    }


def build_source_cards_payload(selected_date: str) -> dict[str, Any]:
    requested_date = str(selected_date or "").strip() or parse_iso_date(selected_date).isoformat()
    resolved_date = requested_date
    bundle = _artifact_bundle(resolved_date)
    if not bundle["rows"]:
        fallback_date = _nearest_available_cards_date(resolved_date)
        if fallback_date and fallback_date != resolved_date:
            resolved_date = fallback_date
            bundle = _artifact_bundle(resolved_date)
    rows = bundle["rows"]
    rec_index = bundle["recommendations"]
    sim_index = bundle["sim"]
    props_index = bundle["props"]
    games = [
        _source_game_from_row(
            row,
            idx=idx,
            selected_date=resolved_date,
            rec_index=rec_index,
            sim_index=sim_index,
            props_index=props_index,
        )
        for idx, row in enumerate(rows, start=1)
    ]
    return {
        "date": resolved_date,
        "requested_date": requested_date,
        "lookahead_applied": bool(resolved_date != requested_date),
        "players_included": False,
        "pregame_portfolio": {"enabled": False, "selected": 0, "candidates": 0},
        "games": games,
    }


def build_source_cards_sim_detail_payload(selected_date: str, away_tri: str, home_tri: str) -> dict[str, Any]:
    away_key = str(away_tri or "").strip().upper()
    home_key = str(home_tri or "").strip().upper()
    bundle = _artifact_bundle(selected_date)
    sim_detail = bundle.get("sim", {}).get((away_key, home_key)) if isinstance(bundle.get("sim"), dict) else None
    if isinstance(sim_detail, dict):
        return {
            "date": selected_date,
            "requested_date": selected_date,
            "players_included": True,
            "games": [
                {
                    "home_tri": home_key,
                    "away_tri": away_key,
                    "sim": {
                        "players_loaded": True,
                        "players_summary": dict(sim_detail.get("players_summary") or {}),
                        "players": {
                            "home": [dict(item) for item in ((sim_detail.get("sim") or {}).get("players", {}).get("home") or sim_detail.get("players", {}).get("home") or []) if isinstance(item, dict)],
                            "away": [dict(item) for item in ((sim_detail.get("sim") or {}).get("players", {}).get("away") or sim_detail.get("players", {}).get("away") or []) if isinstance(item, dict)],
                        },
                        "missing_prop_players": {
                            "home": [dict(item) for item in ((sim_detail.get("sim") or {}).get("missing_prop_players", {}).get("home") or sim_detail.get("missing_prop_players", {}).get("home") or []) if isinstance(item, dict)],
                            "away": [dict(item) for item in ((sim_detail.get("sim") or {}).get("missing_prop_players", {}).get("away") or sim_detail.get("missing_prop_players", {}).get("away") or []) if isinstance(item, dict)],
                        },
                        "injuries": {
                            "home": [dict(item) for item in ((sim_detail.get("sim") or {}).get("injuries", {}).get("home") or sim_detail.get("injuries", {}).get("home") or []) if isinstance(item, dict)],
                            "away": [dict(item) for item in ((sim_detail.get("sim") or {}).get("injuries", {}).get("away") or sim_detail.get("injuries", {}).get("away") or []) if isinstance(item, dict)],
                        },
                    },
                }
            ],
        }

    fallback = build_source_cards_payload(selected_date)
    game = next(
        (
            item
            for item in (fallback.get("games") or [])
            if isinstance(item, dict)
            and str(item.get("away_tri") or "").strip().upper() == away_key
            and str(item.get("home_tri") or "").strip().upper() == home_key
        ),
        None,
    )
    return {
        "date": selected_date,
        "requested_date": selected_date,
        "players_included": False,
        "games": [dict(game)] if isinstance(game, dict) else [],
    }


def build_source_cards_props_strip_payload(selected_date: str, *, limit: int = 24, per_game_limit: int = 8) -> dict[str, Any]:
    bundle = _artifact_bundle(selected_date)
    items: list[dict[str, Any]] = []
    for key, game in (bundle.get("props") or {}).items():
        if not isinstance(key, tuple) or not isinstance(game, dict):
            continue
        away_tri, home_tri = key
        prop_recommendations = game.get("prop_recommendations") if isinstance(game.get("prop_recommendations"), dict) else {}
        game_key = f"{away_tri}@{home_tri}"
        for side_key, team_tri in (("away", away_tri), ("home", home_tri)):
            rows = prop_recommendations.get(side_key) if isinstance(prop_recommendations.get(side_key), list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                picks = row.get("picks") if isinstance(row.get("picks"), list) else []
                base_picks = picks if picks else ([row.get("best")] if isinstance(row.get("best"), dict) else [])
                for pick in base_picks:
                    if not isinstance(pick, dict):
                        continue
                    items.append(
                        {
                            "game_key": game_key,
                            "away_tri": away_tri,
                            "home_tri": home_tri,
                            "team_tri": team_tri,
                            "opponent_tri": home_tri if side_key == "away" else away_tri,
                            "player": str(row.get("player") or pick.get("player") or "").strip(),
                            "player_id": row.get("player_id") or pick.get("player_id"),
                            "photo": row.get("player_photo") or row.get("photo"),
                            "market": str(pick.get("market") or row.get("market") or "").strip().lower(),
                            "side": str(pick.get("side") or row.get("side") or "").strip().upper(),
                            "line": _safe_float(pick.get("line") or row.get("line")),
                            "price": _safe_float(pick.get("price") or row.get("price")),
                            "edge": _safe_float(pick.get("edge") or row.get("edge")),
                            "ev": _safe_float(pick.get("ev") or row.get("ev")),
                            "ev_pct": _safe_float(pick.get("ev_pct") or row.get("ev_pct")),
                            "prob_calib": _safe_float(pick.get("prob_calib") or row.get("prob_calib") or row.get("p_win")),
                            "book": pick.get("book") or row.get("book"),
                            "score": _safe_float(row.get("score") or row.get("locked_policy_score") or row.get("ev_pct")),
                            "score_adj": _safe_float(row.get("recommendation_priority_score") or row.get("basketball_priority_score") or row.get("score") or row.get("ev_pct")),
                            "tier": row.get("tier"),
                            "opponent": row.get("opponent") or (home_tri if side_key == "away" else away_tri),
                            "event_id": None,
                            "game_id": game.get("game_id"),
                        }
                    )

    items.sort(
        key=lambda item: (
            float(item.get("ev_pct") or float("-inf")),
            float(item.get("edge") or float("-inf")),
            float(item.get("score_adj") or item.get("score") or float("-inf")),
        ),
        reverse=True,
    )

    selected_items: list[dict[str, Any]] = []
    by_game_counts: dict[str, int] = {}
    for item in items:
        game_key = str(item.get("game_key") or "")
        if game_key and by_game_counts.get(game_key, 0) >= per_game_limit:
            continue
        selected_items.append(item)
        if game_key:
            by_game_counts[game_key] = int(by_game_counts.get(game_key, 0) + 1)
        if len(selected_items) >= limit:
            break

    return {
        "ok": True,
        "mode": "pregame",
        "date": selected_date,
        "title": "Pregame prop movement",
        "subtitle": "Top same-day prop cards from the saved cards props snapshot.",
        "items": selected_items,
        "rows": len(selected_items),
        "source": "cards_props_snapshot",
    }


def _game_from_row(
    row: dict[str, str],
    *,
    idx: int,
    selected_date: str,
    rec_index: dict[tuple[str, str], list[dict[str, Any]]],
    sim_index: dict[tuple[str, str], dict[str, Any]],
    props_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    away_name = str(row.get("visitor_team") or "Away").strip() or "Away"
    home_name = str(row.get("home_team") or "Home").strip() or "Home"
    away_tri = str(row.get("away_tri") or away_name[:3]).strip().upper() or "AWY"
    home_tri = str(row.get("home_tri") or home_name[:3]).strip().upper() or "HOM"
    picks = rec_index.get((away_tri, home_tri), [])
    sim_game = sim_index.get((away_tri, home_tri))
    props_game = props_index.get((away_tri, home_tri))
    top_picks, pick_rows = _top_pick_items(picks)
    sim_groups, sim_stats = _sim_table_groups(sim_game, away_tri, home_tri)
    props_groups, prop_items = _props_table_groups(props_game, away_tri, home_tri)
    game_id = str(row.get("game_id") or idx)
    return {
        "gamePk": game_id,
        "away": {"abbr": away_tri, "name": away_name},
        "home": {"abbr": home_tri, "name": home_name},
        "status": "Processed artifact",
        "detail": str(row.get("commence_time") or "Scheduled").strip() or "Scheduled",
        "summary": f"{row.get('bookmaker') or 'Consensus'} market snapshot",
        "metrics": [
            {"label": "Away ML", "value": format_moneyline(row.get("away_ml"))},
            {"label": "Home ML", "value": format_moneyline(row.get("home_ml"))},
            {"label": "Spread", "value": f"{home_tri} {format_signed_num(row.get('home_spread'))}"},
            {"label": "Total", "value": format_num(row.get("total"))},
            {"label": "Books", "value": str(row.get("books_count") or "-")},
            {"label": "Tip win", "value": format_num(float(row.get("prob_home_tip") or 0) * 100) + "%"},
            {"label": "Early 3s", "value": _format_pct_100((_safe_float(row.get("early_threes_prob_ge_1")) or 0.0) * 100)},
        ],
        "href": f"/wnba/game/{game_id}?date={selected_date}",
        "href_label": "Open WNBA game",
        "panels": [
            {
                "eyebrow": "Market snapshot",
                "title": f"{row.get('bookmaker') or 'Consensus'} lines",
                "body": f"Spread {home_tri} {format_signed_num(row.get('home_spread'))} | total {format_num(row.get('total'))}.",
                "summary_stats": [
                    {"label": "Away ML", "value": format_moneyline(row.get("away_ml"))},
                    {"label": "Home ML", "value": format_moneyline(row.get("home_ml"))},
                    {"label": "Books", "value": str(row.get("books_count") or "-")},
                    {"label": "Tip", "value": format_num(float(row.get("prob_home_tip") or 0) * 100) + "%"},
                ],
            },
            {
                "eyebrow": "Top recommendations",
                "title": "Per-game playable looks",
                "body": "Top picks are pulled from the processed WNBA recommendation slate artifact.",
                "items": top_picks or ["No linked recommendations found for this matchup."],
                "table_groups": ([{"heading": "Top plays", "rows": pick_rows}] if pick_rows else None),
            },
            {
                "eyebrow": "Sim detail",
                "title": "Top player outcomes",
                "body": "SmartSim detail artifacts provide player-level median and mean expectation for this matchup.",
                "summary_stats": sim_stats or None,
                "table_groups": sim_groups or None,
                "items": [f"Game id {game_id}"] if not sim_groups else None,
            },
            {
                "eyebrow": "Props snapshot",
                "title": "Best available props",
                "body": "Cards props snapshots surface the strongest team-side recommendations saved for the board.",
                "table_groups": props_groups or None,
                "items": prop_items or ["No props snapshot was linked for this matchup."],
            },
        ],
    }


def _game_by_id_from_artifacts(selected_date: str, game_pk: str | int) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    bundle = _artifact_bundle(selected_date)
    wanted = str(game_pk).strip()
    for idx, row in enumerate(bundle["rows"], start=1):
        if str(row.get("game_id") or idx).strip() != wanted:
            continue
        return (
            _game_from_row(
                row,
                idx=idx,
                selected_date=selected_date,
                rec_index=bundle["recommendations"],
                sim_index=bundle["sim"],
                props_index=bundle["props"],
            ),
            bundle,
        )
    return None, bundle


def _games_from_artifacts(selected_date: str) -> tuple[list[dict[str, Any]], str, str]:
    bundle = _artifact_bundle(selected_date)
    rows = bundle["rows"]
    rec_index = bundle["recommendations"]
    sim_index = bundle["sim"]
    props_index = bundle["props"]
    games = [
        _game_from_row(
            row,
            idx=idx,
            selected_date=selected_date,
            rec_index=rec_index,
            sim_index=sim_index,
            props_index=props_index,
        )
        for idx, row in enumerate(rows, start=1)
    ]
    return games, str(bundle["paths"]["cards"]), str(bundle["paths"]["recommendations"])


def build_cards_page_context(selected_date: str, *, allow_stored_date_fallback: bool = True) -> dict[str, Any]:
    requested_date = str(selected_date or "").strip() or parse_iso_date(selected_date).isoformat()
    resolved_date = requested_date
    parsed_date = parse_iso_date(resolved_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()

    games, cards_path, recs_path = _games_from_artifacts(resolved_date)
    if not games and allow_stored_date_fallback:
        fallback_date = _nearest_available_cards_date(resolved_date)
        if fallback_date and fallback_date != resolved_date:
            resolved_date = fallback_date
            games, cards_path, recs_path = _games_from_artifacts(resolved_date)

    parsed_date = parse_iso_date(resolved_date)
    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()
    using_sample_data = False

    scoreboard_items = [
        {
            "target_id": f"game-{game['gamePk']}",
            "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
            "status": game["detail"],
        }
        for game in games
    ]

    return apply_game_board_contract(
        {
            "date": resolved_date,
            "requested_date": requested_date,
            "lookahead_applied": bool(resolved_date != requested_date),
            "prev_date": prev_date,
            "next_date": next_date,
            "games": games,
            "scoreboard_items": scoreboard_items,
            "using_sample_data": using_sample_data,
            "source_path": cards_path,
            "source_title": "WNBA processed game cards" if games else "WNBA cards unavailable",
            "empty_state": {
                "eyebrow": "WNBA cards",
                "title": "No game cards were available for this date",
                "body": "The cards board only renders saved WNBA processed artifact rows, and none were available for the requested date.",
                "list_items": [
                    f"Requested date: {requested_date}",
                    "Choose another stored WNBA date from the date control.",
                ],
            } if not games else None,
            "header_stats": [
                {"label": "Games", "value": str(len(games))},
                {"label": "Recommendations", "value": recs_path.split("\\")[-1] if games else "No data"},
            ],
            "route_path": "/wnba/cards",
            "intro_title": "WNBA Cards",
            "intro_body": "This is the first non-MLB Syndicate module, mapped into the shared game-card shell from committed WNBA processed artifacts.",
            "cards_control_links": [
                {"label": "Betting Card", "href": f"/wnba/season/{parse_iso_date(resolved_date).year}/betting-card?date={resolved_date}"},
                {"label": "Props", "href": f"/wnba/props?date={resolved_date}"},
                {"label": "Live Lens", "href": f"/wnba/live-lens?date={resolved_date}"},
            ],
            "cards_grid_class": "wnba-cards-grid",
            "cards_stylesheet": "wnba/cards.css",
            "teaser": {
                "label": "WNBA picks",
                "body": "Use the dedicated picks module for the strongest processed recommendation slate cards.",
                "href": f"/wnba/picks?date={resolved_date}",
                "cta": "Open WNBA picks",
            },
            "module_links": build_module_links(resolved_date, "Cards"),
            "active_sport_name": "WNBA",
        },
        sport="wnba",
        module="cards",
        source_kind="artifact_backed",
        live_lens_integrated=True,
    )


@lru_cache(maxsize=64)
def _local_live_state_payload(selected_date: str) -> dict[str, Any] | None:
    try:
        path = live_snapshot_path(f"live_state_{selected_date}.jsonl")
    except FileNotFoundError:
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        raw = str(line or "").strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except Exception:
            continue
        payload = record.get("payload") if isinstance(record, dict) and isinstance(record.get("payload"), dict) else None
        if isinstance(payload, dict):
            return payload
        if isinstance(record, dict) and isinstance(record.get("games"), list):
            return record
    return None


@lru_cache(maxsize=256)
def _local_live_snapshot_payload(kind: str, selected_date: str) -> dict[str, Any] | None:
    resolved_date = str(selected_date or "").strip()
    if not resolved_date:
        return None
    try:
        path = live_snapshot_path(f"{kind}_{resolved_date}.jsonl")
    except FileNotFoundError:
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        raw = str(line or "").strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except Exception:
            continue
        payload = record.get("payload") if isinstance(record, dict) and isinstance(record.get("payload"), dict) else None
        if isinstance(payload, dict):
            return payload
        if isinstance(record, dict) and isinstance(record.get("games"), list):
            return record
    return None


def _filtered_local_live_snapshot_payload(kind: str, selected_date: str, event_ids: list[str]) -> dict[str, Any] | None:
    payload = _local_live_snapshot_payload(kind, selected_date)
    if not isinstance(payload, dict):
        return None
    games = payload.get("games") if isinstance(payload.get("games"), list) else None
    if games is None:
        return None
    cleaned = {str(item).strip() for item in event_ids if str(item).strip()}
    if not cleaned:
        return payload
    filtered_payload = dict(payload)
    filtered_payload["games"] = [
        game
        for game in games
        if isinstance(game, dict) and str(game.get("event_id") or "").strip() in cleaned
    ]
    if selected_date and "date" not in filtered_payload:
        filtered_payload["date"] = selected_date
    return filtered_payload


def build_live_state_payload(selected_date: str, ttl: int = 12) -> dict[str, Any]:
    local_payload = _local_live_state_payload(selected_date)
    if isinstance(local_payload, dict) and isinstance(local_payload.get("games"), list):
        return local_payload

    context = build_cards_page_context(selected_date)
    games = context.get("games") if isinstance(context.get("games"), list) else []
    out_games = []
    for game in games:
        if not isinstance(game, dict):
            continue
        status_text = str(game.get("status") or "").strip()
        detail_text = str(game.get("detail") or "").strip()
        status_lower = f"{status_text} {detail_text}".lower()
        in_progress = any(token in status_lower for token in ("live", "in progress", "q1", "q2", "q3", "q4", "ot", "halftime"))
        final = any(token in status_lower for token in ("final", "finished", "complete"))
        away_info = game.get("away") if isinstance(game.get("away"), dict) else {}
        home_info = game.get("home") if isinstance(game.get("home"), dict) else {}
        out_games.append(
            {
                "game_id": game.get("gamePk"),
                "event_id": game.get("event_id"),
                "home": game.get("home_tri") or home_info.get("abbr"),
                "away": game.get("away_tri") or away_info.get("abbr"),
                "home_pts": None,
                "away_pts": None,
                "status_id": None,
                "status": detail_text or status_text,
                "period": None,
                "clock": "",
                "in_progress": bool(in_progress and not final),
                "final": bool(final),
                "periods": [],
            }
        )

    return {
        "date": selected_date,
        "ttl": int(ttl),
        "source": "syndicate_cards_fallback",
        "games": out_games,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def build_live_player_boxscore_payload(selected_date: str, event_ids: list[str], ttl: int = 20) -> dict[str, Any]:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    local_payload = _filtered_local_live_snapshot_payload("live_player_boxscore", selected_date, normalized_event_ids)
    if isinstance(local_payload, dict) and isinstance(local_payload.get("games"), list):
        return local_payload
    return {
        "ok": True,
        "ttl": int(ttl),
        "date": selected_date or None,
        "games": [{"event_id": event_id, "players": []} for event_id in normalized_event_ids],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def build_live_player_lens_payload(selected_date: str, event_ids: list[str], ttl: int = 20) -> dict[str, Any]:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    local_payload = _filtered_local_live_snapshot_payload("live_player_lens", selected_date, normalized_event_ids)
    if isinstance(local_payload, dict) and isinstance(local_payload.get("games"), list):
        return local_payload
    return {
        "ok": True,
        "ttl": int(ttl),
        "date": selected_date or None,
        "games": [
            {
                "event_id": event_id,
                "game_id": None,
                "home": None,
                "away": None,
                "status": {"in_progress": False, "final": False, "period": None, "clock": ""},
                "rows": [],
            }
            for event_id in normalized_event_ids
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def build_live_lines_payload(selected_date: str, event_ids: list[str], ttl: int = 20, include_period_totals: bool = False) -> dict[str, Any]:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    local_payload = _filtered_local_live_snapshot_payload("live_lines", selected_date, normalized_event_ids)
    if isinstance(local_payload, dict) and isinstance(local_payload.get("games"), list):
        return local_payload
    return {
        "ok": True,
        "ttl": int(ttl),
        "date": selected_date,
        "include_period_totals": bool(include_period_totals),
        "games": [{"event_id": event_id, "found": False} for event_id in normalized_event_ids],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def build_live_pbp_stats_payload(selected_date: str, event_ids: list[str], ttl: int = 20) -> dict[str, Any]:
    normalized_event_ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
    local_payload = _filtered_local_live_snapshot_payload("live_pbp_stats", selected_date, normalized_event_ids)
    if isinstance(local_payload, dict) and isinstance(local_payload.get("games"), list):
        return local_payload
    return {
        "ok": True,
        "ttl": int(ttl),
        "date": selected_date or None,
        "games": [
            {
                "event_id": event_id,
                "game_id": None,
                "home": None,
                "away": None,
                "pbp_attempts": {"home": {}, "away": {}, "unknown": {}, "total": {}},
                "pbp_attempts_periods": {},
                "pbp_possessions": {"home": {}, "away": {}, "unknown": {}, "total": {}},
                "pbp_possessions_periods": {},
                "pbp_quarters": {"q_totals": {"q1": None, "q2": None, "q3": None, "q4": None}, "current": {"period": None, "q_total": None}},
                "pbp_recent": {"window_sec": 180, "points_total": None, "attempts": None, "possessions": None, "current_scoring_run": {"team": None, "points": None}, "seconds_since_score": None},
            }
            for event_id in normalized_event_ids
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def build_live_lens_tuning_payload(ttl: int = 300) -> dict[str, Any]:
    return {
        "ok": True,
        "ttl": int(ttl),
        "round_live_line_to_half": True,
        "logging": {"mode": "bet", "min_interval_sec": 60},
        "markets": {
            "total": {"watch": 3.0, "bet": 6.0},
            "half_total": {"watch": 3.0, "bet": 6.0},
            "quarter_total": {"watch": 2.0, "bet": 4.0},
            "ats": {"watch": 2.0, "bet": 4.0},
            "player_prop": {"watch": 2.0, "bet": 4.0},
        },
    }