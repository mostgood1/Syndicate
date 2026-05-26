from __future__ import annotations

import csv
import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from syndicate.features.nba.sources import build_module_links
from syndicate.features.nba.sources import format_moneyline
from syndicate.features.nba.sources import format_num
from syndicate.features.nba.sources import format_signed_num
from syndicate.features.nba.sources import load_json
from syndicate.features.nba.sources import market_label
from syndicate.features.nba.sources import parse_iso_date
from syndicate.features.nba.sources import processed_path
from syndicate.features.nba.sources import live_snapshot_path
from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.shared.game_board_contract import build_game_board_api_payload


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
        home = str(item.get("home") or "").strip().upper()
        away = str(item.get("away") or "").strip().upper()
        picks = item.get("picks") if isinstance(item.get("picks"), list) else []
        if home and away:
            index[(home, away)] = [pick for pick in picks if isinstance(pick, dict)]
    return index


def _artifact_games_index(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    payload = load_json(path)
    games = payload.get("games") if isinstance((payload or {}).get("games"), list) else []
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for game in games:
        if not isinstance(game, dict):
            continue
        home = str(game.get("home_tri") or "").strip().upper()
        away = str(game.get("away_tri") or "").strip().upper()
        if home and away:
            index[(home, away)] = game
    return index


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _implied_prob_from_american(value: Any) -> float | None:
    number = _safe_float(value)
    if number is None or number == 0:
        return None
    if number > 0:
        return 100.0 / (number + 100.0)
    return abs(number) / (abs(number) + 100.0)


def _normalize_two_way(first: Any, second: Any) -> tuple[float, float]:
    left = _safe_float(first)
    right = _safe_float(second)
    if left is not None and right is not None and (left + right) > 0:
        total = left + right
        return left / total, right / total
    if left is not None:
        clamped = max(0.0, min(1.0, left))
        return clamped, 1.0 - clamped
    if right is not None:
        clamped = max(0.0, min(1.0, right))
        return 1.0 - clamped, clamped
    return 0.5, 0.5


def _default_segment(total_mean: float | None, margin_mean: float | None, win_prob: float) -> dict[str, Any]:
    return {
        "total_mean": total_mean,
        "margin_mean": margin_mean,
        "p_home_win": win_prob,
    }


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
    sim = sim_game.get("sim") if isinstance(sim_game.get("sim"), dict) else sim_game
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
    prop_recommendations = props_game.get("prop_recommendations") if isinstance(props_game.get("prop_recommendations"), dict) else props_game
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


def _next_available_cards_date(selected_date: str, *, max_ahead_days: int = 14) -> str | None:
    parsed_date = parse_iso_date(selected_date)
    for offset in range(1, max_ahead_days + 1):
        candidate = (parsed_date + timedelta(days=offset)).isoformat()
        rows = _load_csv_rows(processed_path(f"game_cards_{candidate}.csv"))
        if rows:
            return candidate
    for offset in range(1, max_ahead_days + 1):
        candidate = (parsed_date - timedelta(days=offset)).isoformat()
        rows = _load_csv_rows(processed_path(f"game_cards_{candidate}.csv"))
        if rows:
            return candidate
    return None


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


def _games_from_live_state_fallback(selected_date: str, ttl: int = 12) -> tuple[list[dict[str, Any]], str]:
    payload = _local_live_state_payload(selected_date)
    source_path = None
    if isinstance(payload, dict):
        try:
            source_path = str(live_snapshot_path(f"live_state_{selected_date}.jsonl"))
        except FileNotFoundError:
            source_path = None
    rows = payload.get("games") if isinstance((payload or {}).get("games"), list) else []
    games: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        away_tri = str(row.get("away") or "").strip().upper()
        home_tri = str(row.get("home") or "").strip().upper()
        if not away_tri or not home_tri:
            continue
        away_pts = _safe_float(row.get("away_pts"))
        home_pts = _safe_float(row.get("home_pts"))
        total_mean = (away_pts + home_pts) if away_pts is not None and home_pts is not None else None
        margin_mean = (home_pts - away_pts) if away_pts is not None and home_pts is not None else None
        status_text = str(row.get("status") or "").strip()
        in_progress = bool(row.get("in_progress"))
        final = bool(row.get("final"))
        games.append(
            {
                "gamePk": str(row.get("game_id") or f"{away_tri}@{home_tri}"),
                "event_id": row.get("event_id"),
                "game_id": str(row.get("game_id") or f"{away_tri}@{home_tri}"),
                "away_tri": away_tri,
                "away_name": away_tri,
                "home_tri": home_tri,
                "home_name": home_tri,
                "away": {"abbr": away_tri, "name": away_tri},
                "home": {"abbr": home_tri, "name": home_tri},
                "status": "Final" if final else ("Live" if in_progress else "Scheduled"),
                "detail": status_text or ("Final" if final else ("Live" if in_progress else "Scheduled")),
                "summary": "Live scoreboard fallback",
                "gameType": "Live",
                "betting": {},
                "prop_recommendations": {"away": [], "home": []},
                "live_state": dict(row),
                "sim": {
                    "game_id": str(row.get("game_id") or f"{away_tri}@{home_tri}"),
                    "score": {
                        "away_mean": away_pts,
                        "home_mean": home_pts,
                        "total_mean": total_mean,
                        "margin_mean": margin_mean,
                    },
                    "market": {},
                    "players_summary": {
                        "away": 0,
                        "home": 0,
                        "missing_away": 0,
                        "missing_home": 0,
                        "injured_away": 0,
                        "injured_home": 0,
                    },
                    "players": {"away": [], "home": []},
                    "missing_prop_players": {"away": [], "home": []},
                    "injuries": {"away": [], "home": []},
                },
            }
        )
    return games, str(source_path or f"live_state_{selected_date}.jsonl")


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


def _normalize_source_game(game: dict[str, Any], *, idx: int, selected_date: str) -> dict[str, Any]:
    away_tri = str(game.get("away_tri") or "AWY").strip().upper() or "AWY"
    home_tri = str(game.get("home_tri") or "HOM").strip().upper() or "HOM"
    away_name = str(game.get("away_name") or away_tri).strip() or away_tri
    home_name = str(game.get("home_name") or home_tri).strip() or home_tri
    game_id = str((((game.get("sim") or {}) if isinstance(game.get("sim"), dict) else {}).get("game_id") or idx)).strip()
    betting = dict(game.get("betting") or {}) if isinstance(game.get("betting"), dict) else {}
    odds = dict(game.get("odds") or {}) if isinstance(game.get("odds"), dict) else {}
    sim = dict(game.get("sim") or {}) if isinstance(game.get("sim"), dict) else {}
    props = dict(game.get("prop_recommendations") or {}) if isinstance(game.get("prop_recommendations"), dict) else {"away": [], "home": []}
    game_recs = [row for row in (game.get("game_market_recommendations") or []) if isinstance(row, dict)]
    score = sim.get("score") if isinstance(sim.get("score"), dict) else {}
    return {
        **game,
        "gamePk": game_id,
        "away_tri": away_tri,
        "away_name": away_name,
        "home_tri": home_tri,
        "home_name": home_name,
        "away": {"abbr": away_tri, "name": away_name},
        "home": {"abbr": home_tri, "name": home_name},
        "status": str(game.get("live_status") or game.get("date") or "Source API").strip() or "Source API",
        "detail": str(game.get("date") or game.get("live_status") or "Scheduled").strip() or "Scheduled",
        "summary": str(game.get("writeup") or "Source API snapshot").strip() or "Source API snapshot",
        "gameType": "NBA",
        "odds": odds,
        "betting": betting,
        "sim": sim,
        "prop_recommendations": {
            "away": props.get("away") if isinstance(props.get("away"), list) else [],
            "home": props.get("home") if isinstance(props.get("home"), list) else [],
        },
        "game_market_recommendations": game_recs,
        "metrics": [
            {"label": "Away pts", "value": format_num(score.get("away_mean"))},
            {"label": "Home pts", "value": format_num(score.get("home_mean"))},
            {"label": "Away win", "value": _format_pct_100((_safe_float(betting.get("p_away_win")) or 0.0) * 100)},
            {"label": "Home win", "value": _format_pct_100((_safe_float(betting.get("p_home_win")) or 0.0) * 100)},
        ],
        "href": f"/nba/game/{game_id}?date={selected_date}",
        "href_label": "Open NBA game",
    }


def _game_by_id_from_artifacts(selected_date: str, game_pk: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    bundle = _artifact_bundle(selected_date)
    rows = bundle["rows"]
    rec_index = bundle["recommendations"]
    sim_index = bundle["sim"]
    props_index = bundle["props"]
    target = str(game_pk).strip()
    for idx, row in enumerate(rows, start=1):
        current_id = str(row.get("game_id") or idx).strip()
        if current_id != target:
            continue
        return (
            _game_from_row(
                row,
                idx=idx,
                selected_date=selected_date,
                rec_index=rec_index,
                sim_index=sim_index,
                props_index=props_index,
            ),
            bundle,
        )
    return None, bundle


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
    picks = rec_index.get((home_tri, away_tri), [])
    sim_game = sim_index.get((home_tri, away_tri))
    props_game = props_index.get((home_tri, away_tri))
    top_picks, pick_rows = _top_pick_items(picks)
    sim_groups, sim_stats = _sim_table_groups(sim_game, away_tri, home_tri)
    props_groups, prop_items = _props_table_groups(props_game, away_tri, home_tri)
    game_id = str(row.get("game_id") or idx)
    home_ml = _safe_float(row.get("home_ml"))
    away_ml = _safe_float(row.get("away_ml"))
    home_spread = _safe_float(row.get("home_spread"))
    away_spread = _safe_float(row.get("away_spread"))
    total = _safe_float(row.get("total"))
    home_spread_price = _safe_float(row.get("home_spread_price"))
    away_spread_price = _safe_float(row.get("away_spread_price"))
    total_over_price = _safe_float(row.get("total_over_price"))
    total_under_price = _safe_float(row.get("total_under_price"))
    p_home_win, p_away_win = _normalize_two_way(
        _implied_prob_from_american(home_ml),
        _implied_prob_from_american(away_ml),
    )
    market_home_margin = -home_spread if home_spread is not None else None
    home_score_mean = ((total + market_home_margin) / 2.0) if total is not None and market_home_margin is not None else None
    away_score_mean = ((total - market_home_margin) / 2.0) if total is not None and market_home_margin is not None else None
    segment_total = (total / 4.0) if total is not None else None
    segment_margin = (market_home_margin / 4.0) if market_home_margin is not None else None
    sim_payload = sim_game.get("sim") if isinstance(sim_game, dict) and isinstance(sim_game.get("sim"), dict) else (sim_game if isinstance(sim_game, dict) else {})
    props_payload = props_game.get("prop_recommendations") if isinstance(props_game, dict) and isinstance(props_game.get("prop_recommendations"), dict) else (
        props_game if isinstance(props_game, dict) else {}
    )
    score_payload = sim_payload.get("score") if isinstance(sim_payload.get("score"), dict) else {}
    market_payload = sim_payload.get("market") if isinstance(sim_payload.get("market"), dict) else {}
    context_payload = sim_payload.get("context") if isinstance(sim_payload.get("context"), dict) else {}
    periods_payload = sim_payload.get("periods") if isinstance(sim_payload.get("periods"), dict) else {}
    players_payload = sim_payload.get("players") if isinstance(sim_payload.get("players"), dict) else {"away": [], "home": []}
    missing_players_payload = sim_payload.get("missing_prop_players") if isinstance(sim_payload.get("missing_prop_players"), dict) else {"away": [], "home": []}
    injuries_payload = sim_payload.get("injuries") if isinstance(sim_payload.get("injuries"), dict) else {"away": [], "home": []}
    players_summary_payload = sim_payload.get("players_summary") if isinstance(sim_payload.get("players_summary"), dict) else {}
    periods = {
        "q1": periods_payload.get("q1") if isinstance(periods_payload.get("q1"), dict) else _default_segment(segment_total, segment_margin, p_home_win),
        "q2": periods_payload.get("q2") if isinstance(periods_payload.get("q2"), dict) else _default_segment(segment_total, segment_margin, p_home_win),
        "q3": periods_payload.get("q3") if isinstance(periods_payload.get("q3"), dict) else _default_segment(segment_total, segment_margin, p_home_win),
        "q4": periods_payload.get("q4") if isinstance(periods_payload.get("q4"), dict) else _default_segment(segment_total, segment_margin, p_home_win),
    }
    return {
        "gamePk": game_id,
        "away_tri": away_tri,
        "away_name": away_name,
        "home_tri": home_tri,
        "home_name": home_name,
        "away": {"abbr": away_tri, "name": away_name},
        "home": {"abbr": home_tri, "name": home_name},
        "status": "Processed artifact",
        "detail": str(row.get("commence_time") or "Scheduled").strip() or "Scheduled",
        "summary": f"{row.get('bookmaker') or 'Consensus'} market snapshot",
        "gameType": "NBA",
        "odds": {
            "commence_time": str(row.get("commence_time") or "").strip() or None,
            "bookmaker": str(row.get("bookmaker") or "").strip() or None,
        },
        "betting": {
            "home_ml": home_ml,
            "away_ml": away_ml,
            "home_spread": home_spread,
            "away_spread": away_spread,
            "home_spread_price": home_spread_price,
            "away_spread_price": away_spread_price,
            "total": total,
            "total_over_price": total_over_price,
            "total_under_price": total_under_price,
            "p_home_win": p_home_win,
            "p_away_win": p_away_win,
            "p_home_cover": 0.5,
            "p_away_cover": 0.5,
            "p_total_over": 0.5,
            "p_total_under": 0.5,
            "home_ml_ev": 0.0,
            "away_ml_ev": 0.0,
            "home_spread_ev": 0.0,
            "away_spread_ev": 0.0,
            "over_ev": 0.0,
            "under_ev": 0.0,
        },
        "sim": {
            "game_id": game_id,
            "score": {
                "away_mean": score_payload.get("away_mean", away_score_mean),
                "home_mean": score_payload.get("home_mean", home_score_mean),
                "total_mean": score_payload.get("total_mean", total),
                "margin_mean": score_payload.get("margin_mean", market_home_margin),
            },
            "market": {
                "market_home_spread": market_payload.get("market_home_spread", home_spread),
            },
            "context": {
                "away_pace": context_payload.get("away_pace", 99.0),
                "home_pace": context_payload.get("home_pace", 99.0),
            },
            "periods": periods,
            "players": players_payload,
            "missing_prop_players": missing_players_payload,
            "injuries": injuries_payload,
            "players_summary": {
                "away": players_summary_payload.get("away", len(players_payload.get("away") or [])),
                "home": players_summary_payload.get("home", len(players_payload.get("home") or [])),
                "missing_away": players_summary_payload.get("missing_away", len(missing_players_payload.get("away") or [])),
                "missing_home": players_summary_payload.get("missing_home", len(missing_players_payload.get("home") or [])),
                "injured_away": players_summary_payload.get("injured_away", len(injuries_payload.get("away") or [])),
                "injured_home": players_summary_payload.get("injured_home", len(injuries_payload.get("home") or [])),
            },
        },
        "prop_recommendations": {
            "away": props_payload.get("away") if isinstance(props_payload.get("away"), list) else [],
            "home": props_payload.get("home") if isinstance(props_payload.get("home"), list) else [],
        },
        "game_market_recommendations": [],
        "metrics": [
            {"label": "Away ML", "value": format_moneyline(row.get("away_ml"))},
            {"label": "Home ML", "value": format_moneyline(row.get("home_ml"))},
            {"label": "Spread", "value": f"{home_tri} {format_signed_num(row.get('home_spread'))}"},
            {"label": "Total", "value": format_num(row.get("total"))},
            {"label": "Books", "value": str(row.get("books_count") or "-")},
            {"label": "Tip win", "value": format_num(float(row.get("prob_home_tip") or 0) * 100) + "%"},
            {"label": "Early 3s", "value": _format_pct_100((_safe_float(row.get("early_threes_prob_ge_1")) or 0.0) * 100)},
        ],
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
                "body": "Top picks are pulled from the processed NBA recommendation slate artifact.",
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
                "body": "Cards props snapshots surface the strongest team-side recommendations saved for the board when available.",
                "table_groups": props_groups or None,
                "items": prop_items or ["No props snapshot was linked for this matchup."],
            },
        ],
        "href": f"/nba/game/{game_id}?date={selected_date}",
        "href_label": "Open NBA game",
    }


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


def _game_has_actionable_data(game: dict[str, Any]) -> bool:
    betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
    sim_score = ((game.get("sim") or {}).get("score") or {}) if isinstance(game.get("sim"), dict) else {}
    game_recs = game.get("game_market_recommendations") if isinstance(game.get("game_market_recommendations"), list) else []
    prop_recs = game.get("prop_recommendations") if isinstance(game.get("prop_recommendations"), dict) else {}

    has_market = any(betting.get(key) is not None for key in ("home_ml", "away_ml", "home_spread", "total"))
    has_sim = any(sim_score.get(key) is not None for key in ("away_mean", "home_mean", "total_mean", "margin_mean"))
    has_game_recs = bool(game_recs)
    has_prop_recs = bool(prop_recs.get("away")) or bool(prop_recs.get("home"))
    return bool(has_market or has_sim or has_game_recs or has_prop_recs)


def _games_have_actionable_data(games: list[dict[str, Any]]) -> bool:
    return any(_game_has_actionable_data(game) for game in games if isinstance(game, dict))


def _next_available_actionable_cards_date(selected_date: str, *, max_days: int = 30) -> str | None:
    parsed_date = parse_iso_date(selected_date)
    for offset in range(1, max_days + 1):
        candidate = (parsed_date + timedelta(days=offset)).isoformat()
        games, _, _ = _games_from_artifacts(candidate)
        if games and _games_have_actionable_data(games):
            return candidate
    for offset in range(1, max_days + 1):
        candidate = (parsed_date - timedelta(days=offset)).isoformat()
        games, _, _ = _games_from_artifacts(candidate)
        if games and _games_have_actionable_data(games):
            return candidate
    return None


def build_cards_page_context(selected_date: str) -> dict[str, Any]:
    requested_date = str(selected_date or "").strip() or parse_iso_date(selected_date).isoformat()
    resolved_date = requested_date
    source_title = "NBA processed game cards"
    parsed_date = parse_iso_date(resolved_date)
    games, cards_path, recs_path = _games_from_artifacts(resolved_date)
    has_actionable_data = _games_have_actionable_data(games)
    if games and not has_actionable_data:
        next_available_date = _next_available_actionable_cards_date(resolved_date)
        if next_available_date:
            resolved_date = next_available_date
            games, cards_path, recs_path = _games_from_artifacts(resolved_date)
            has_actionable_data = _games_have_actionable_data(games)
    if not games:
        live_games, live_source_path = _games_from_live_state_fallback(resolved_date)
        if live_games:
            games = live_games
            cards_path = live_source_path
            recs_path = live_source_path
            source_title = "NBA live scoreboard fallback"
    if not games:
        next_available_date = _next_available_cards_date(resolved_date)
        if next_available_date:
            resolved_date = next_available_date
            games, cards_path, recs_path = _games_from_artifacts(resolved_date)
            has_actionable_data = _games_have_actionable_data(games)

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

    context = {
        "date": resolved_date,
        "requested_date": requested_date,
        "lookahead_applied": bool(resolved_date != requested_date),
        "prev_date": prev_date,
        "next_date": next_date,
        "games": games,
        "scoreboard_items": scoreboard_items,
        "using_sample_data": using_sample_data,
        "source_path": cards_path,
        "source_title": source_title if games else "NBA cards unavailable",
        "empty_state": {
            "eyebrow": "NBA cards",
            "title": "No game cards were available for this date",
            "body": "The cards board only renders saved NBA source, processed, or live fallback rows, and none were available for the requested date.",
            "list_items": [
                f"Requested date: {requested_date}",
                "Choose another stored NBA date from the date control.",
            ],
        } if not games else None,
        "header_stats": [
            {"label": "Games", "value": str(len(games))},
            {"label": "Recommendations", "value": recs_path.split("\\")[-1] if games else "No data"},
            *([
                {"label": "Data", "value": "Placeholder fallback"},
            ] if games and not has_actionable_data else []),
        ],
        "route_path": "/nba/cards",
        "intro_title": "NBA Cards",
        "intro_body": "This first NBA Syndicate pass maps committed processed game-card, slate, and SmartSim artifacts into the shared board shell instead of leaving NBA behind the generic placeholder route.",
        "cards_control_links": [
            {"label": "Betting Card", "href": f"/nba/season/{parse_iso_date(resolved_date).year}/betting-card?date={resolved_date}"},
            {"label": "Picks", "href": f"/nba/picks?date={resolved_date}"},
            {"label": "Prop Ladders", "href": f"/nba/prop-ladders?date={resolved_date}"},
            {"label": "Live Prop Audit", "href": f"/nba/live-player-props-audit?date={resolved_date}"},
        ],
        "cards_grid_class": "wnba-cards-grid",
        "cards_stylesheet": "nba/cards.css",
        "pregame_portfolio": {"enabled": False, "selected": 0, "candidates": 0},
        "teaser": {
            "label": "NBA module rollout",
            "body": "This is the first live NBA surface inside Syndicate. Picks, props, and deeper drill-ins come next after the shared board contract settles.",
            "href": "/nba",
            "cta": "Open NBA hub",
        },
        "module_links": build_module_links(resolved_date, "Cards"),
        "active_sport_name": "NBA",
    }
    return apply_game_board_contract(context, sport="nba", module="cards")


def build_cards_api_payload(selected_date: str) -> dict[str, Any]:
    return build_game_board_api_payload(build_cards_page_context(selected_date))


def build_cards_sim_detail_payload(selected_date: str, away_tri: str, home_tri: str) -> dict[str, Any]:
    away_key = str(away_tri or "").strip().upper()
    home_key = str(home_tri or "").strip().upper()
    bundle = _artifact_bundle(selected_date)
    sim_detail = bundle.get("sim", {}).get((home_key, away_key)) if isinstance(bundle.get("sim"), dict) else None
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
                            "home": [dict(row) for row in (sim_detail.get("players", {}).get("home") or []) if isinstance(row, dict)],
                            "away": [dict(row) for row in (sim_detail.get("players", {}).get("away") or []) if isinstance(row, dict)],
                        },
                        "missing_prop_players": {
                            "home": [dict(row) for row in (sim_detail.get("missing_prop_players", {}).get("home") or []) if isinstance(row, dict)],
                            "away": [dict(row) for row in (sim_detail.get("missing_prop_players", {}).get("away") or []) if isinstance(row, dict)],
                        },
                        "injuries": {
                            "home": [dict(row) for row in (sim_detail.get("injuries", {}).get("home") or []) if isinstance(row, dict)],
                            "away": [dict(row) for row in (sim_detail.get("injuries", {}).get("away") or []) if isinstance(row, dict)],
                        },
                    },
                }
            ],
        }

    context = build_cards_page_context(selected_date)
    games = context.get("games") if isinstance(context.get("games"), list) else []
    game = next(
        (
            item
            for item in games
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
        out_games.append(
            {
                "game_id": game.get("gamePk"),
                "event_id": None,
                "home": game.get("home_tri") or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else None),
                "away": game.get("away_tri") or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else None),
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
