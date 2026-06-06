from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _canonical_game_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return digits.lstrip("0") or "0"
    return text.upper()


def _canonical_tri(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_name(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _canonical_stat(value: Any) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "points": "pts",
        "point": "pts",
        "pts": "pts",
        "rebounds": "reb",
        "rebound": "reb",
        "reb": "reb",
        "assists": "ast",
        "assist": "ast",
        "ast": "ast",
        "3pm": "threes",
        "3pt": "threes",
        "threes": "threes",
        "steals": "stl",
        "stl": "stl",
        "blocks": "blk",
        "blk": "blk",
        "turnovers": "tov",
        "tov": "tov",
        "pra": "pra",
        "pr": "pr",
        "pa": "pa",
        "ra": "ra",
    }
    return mapping.get(raw, raw)


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = str(line or "").strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except Exception:
        return []
    return rows


def _generated_at_for(paths: list[Path]) -> str:
    mtimes: list[float] = []
    for path in paths:
        try:
            mtimes.append(float(path.stat().st_mtime))
        except Exception:
            continue
    if not mtimes:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _matchup_from_game(game: dict[str, Any]) -> tuple[str, str]:
    away = _canonical_tri(
        game.get("away_tri")
        or ((game.get("away") or {}).get("abbr") if isinstance(game.get("away"), dict) else "")
        or game.get("away")
    )
    home = _canonical_tri(
        game.get("home_tri")
        or ((game.get("home") or {}).get("abbr") if isinstance(game.get("home"), dict) else "")
        or game.get("home")
    )
    return away, home


def _build_event_index(event_games: dict[str, dict[str, Any]]) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    id_index: dict[str, str] = {}
    matchup_index: dict[tuple[str, str], str] = {}
    for event_id, game in event_games.items():
        identifiers = {
            str(event_id or "").strip(),
            str(game.get("event_id") or "").strip(),
            str(game.get("gamePk") or "").strip(),
            str(game.get("game_id") or "").strip(),
        }
        for identifier in identifiers:
            if not identifier:
                continue
            id_index[identifier] = event_id
            canonical = _canonical_game_id(identifier)
            if canonical:
                id_index[canonical] = event_id
        away, home = _matchup_from_game(game)
        if away and home:
            matchup_index[(away, home)] = event_id
    return id_index, matchup_index


def _event_id_for_row(
    row: dict[str, Any],
    *,
    id_index: dict[str, str],
    matchup_index: dict[tuple[str, str], str],
) -> str:
    for key in ("event_id", "game_id", "game_id_canon"):
        raw = str(row.get(key) or "").strip()
        if raw and raw in id_index:
            return id_index[raw]
        canonical = _canonical_game_id(raw)
        if canonical and canonical in id_index:
            return id_index[canonical]

    away = _canonical_tri(row.get("away"))
    home = _canonical_tri(row.get("home"))
    if not away or not home:
        team = _canonical_tri(row.get("team") or row.get("team_tri"))
        opponent = _canonical_tri(row.get("opponent") or row.get("opponent_tri"))
        home_flag = str(row.get("home") or "").strip().lower()
        if team and opponent and home_flag in {"0", "1", "true", "false"}:
            is_home = home_flag in {"1", "true"}
            home = team if is_home else opponent
            away = opponent if is_home else team
    if away and home:
        return matchup_index.get((away, home), "")
    return ""


def _latest_projection_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        if str(row.get("market") or "").strip().lower() != "player_prop":
            continue
        name_key = _normalize_name(row.get("name_key") or row.get("player"))
        stat_key = _canonical_stat(row.get("stat"))
        game_key = _canonical_game_id(row.get("game_id_canon") or row.get("game_id") or row.get("event_id"))
        if not name_key or not stat_key or not game_key:
            continue
        grouped[(game_key, name_key, stat_key)] = row
    return list(grouped.values())


def build_live_player_lens_payload_from_artifacts(
    *,
    processed_root: Path,
    date_str: str,
    event_games: dict[str, dict[str, Any]],
    source: str,
) -> dict[str, Any] | None:
    projection_path = processed_root / f"live_lens_projections_{date_str}.jsonl"
    rows = _latest_projection_rows(_read_jsonl_rows(projection_path))
    if not rows or not event_games:
        return None

    id_index, matchup_index = _build_event_index(event_games)
    grouped_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        event_id = _event_id_for_row(row, id_index=id_index, matchup_index=matchup_index)
        if not event_id:
            continue
        game = event_games.get(event_id) or {}
        team_tri = _canonical_tri(row.get("team") or row.get("team_tri"))
        opponent_tri = _canonical_tri(row.get("opponent") or row.get("opponent_tri"))
        if not team_tri or not opponent_tri:
            away_tri, home_tri = _matchup_from_game(game)
            home_flag = str(row.get("home") or "").strip().lower()
            if home_flag in {"0", "1", "true", "false"}:
                is_home = home_flag in {"1", "true"}
                team_tri = home_tri if is_home else away_tri
                opponent_tri = away_tri if is_home else home_tri
        stat = _canonical_stat(row.get("stat"))
        line_value = _safe_float(row.get("line") if row.get("line") is not None else row.get("live_line"))
        price_over = _safe_float(row.get("price_over"))
        price_under = _safe_float(row.get("price_under"))
        price_value = _safe_float(row.get("price"))
        if line_value is not None and abs(line_value) < 0.001 and not any(
            value is not None and abs(value) > 0.001 for value in (price_over, price_under, price_value)
        ):
            continue
        live_projection = _safe_float(
            row.get("live_projection")
            if row.get("live_projection") is not None
            else (row.get("proj") if row.get("proj") is not None else row.get("pred"))
        )
        sim_mu = _safe_float(
            row.get("sim_mu_adjusted")
            if row.get("sim_mu_adjusted") is not None
            else row.get("sim_mu")
        )
        rendered_row: dict[str, Any] = {
            "player": str(row.get("player") or row.get("name_key") or "").strip(),
            "player_id": row.get("player_id"),
            "team_tri": team_tri or None,
            "opponent_tri": opponent_tri or None,
            "event_id": event_id,
            "stat": stat,
            "line": line_value,
            "line_live": line_value,
            "line_source": "live_lens_projection_artifact",
            "lean": str(row.get("side") or row.get("selection") or "").strip().upper() or None,
            "ev_side": str(row.get("side") or row.get("selection") or "").strip().upper() or None,
            "price_over": price_over,
            "price_under": price_under,
            "price": price_value,
            "ev": _safe_float(row.get("ev")),
            "win_prob": _safe_float(row.get("win_prob") if row.get("win_prob") is not None else row.get("p_win")),
            "recommendation_priority_score": _safe_float(
                row.get("recommendation_priority_score") if row.get("recommendation_priority_score") is not None else row.get("edge")
            ),
            "klass": str(row.get("klass") or "WATCH").strip().upper() or "WATCH",
            "actual": _safe_float(row.get("actual")),
            "pace_proj": _safe_float(row.get("pace_proj") if row.get("pace_proj") is not None else live_projection),
            "pace_vs_line": None,
            "sim_mu": sim_mu,
            "sim_mu_adjusted": sim_mu,
            "live_projection": live_projection,
            "liveProjection": live_projection,
        }
        if line_value is not None and live_projection is not None:
            live_edge = round(live_projection - line_value, 3)
            rendered_row["live_edge"] = live_edge
            rendered_row["liveEdge"] = live_edge
            rendered_row["pace_vs_line"] = live_edge
        if line_value is not None and sim_mu is not None:
            sim_vs_line = round(sim_mu - line_value, 3)
            rendered_row["sim_vs_line"] = sim_vs_line
            rendered_row["sim_vs_line_adjusted"] = sim_vs_line
        grouped_rows.setdefault(event_id, []).append(rendered_row)

    if not grouped_rows:
        return None

    games: list[dict[str, Any]] = []
    for event_id, rows_for_event in grouped_rows.items():
        game = event_games.get(event_id) or {}
        away_tri, home_tri = _matchup_from_game(game)
        rows_for_event.sort(
            key=lambda row: (
                -abs(_safe_float(row.get("recommendation_priority_score")) or 0.0),
                -abs(_safe_float(row.get("live_edge")) or 0.0),
                str(row.get("player") or ""),
            )
        )
        games.append(
            {
                "event_id": event_id,
                "game_id": game.get("gamePk") or game.get("game_id"),
                "home": home_tri or None,
                "away": away_tri or None,
                "status": game.get("status") if isinstance(game.get("status"), dict) else {},
                "rows": rows_for_event,
            }
        )

    return {
        "ok": True,
        "date": date_str,
        "requested_date": date_str,
        "lookahead_applied": False,
        "source": source,
        "games": games,
        "generated_at": _generated_at_for([projection_path]),
    }


def build_live_lines_payload_from_artifacts(
    *,
    processed_root: Path,
    date_str: str,
    event_games: dict[str, dict[str, Any]],
    include_period_totals: bool,
    source: str,
) -> dict[str, Any] | None:
    signal_path = processed_root / f"live_lens_signals_{date_str}.jsonl"
    rows = _read_jsonl_rows(signal_path)
    if not rows or not event_games:
        return None

    id_index, matchup_index = _build_event_index(event_games)
    games_out: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_id = _event_id_for_row(row, id_index=id_index, matchup_index=matchup_index)
        if not event_id:
            continue
        market = str(row.get("market") or "").strip().lower()
        line_value = _safe_float(row.get("live_line") if row.get("live_line") is not None else row.get("line"))
        if line_value is None:
            continue
        current = games_out.setdefault(
            event_id,
            {
                "event_id": event_id,
                "found": False,
                "total": None,
                "home_spread": None,
                "away_spread": None,
                "home_ml": None,
                "away_ml": None,
                "lines": {
                    "total": None,
                    "home_spread": None,
                    "away_spread": None,
                    "home_ml": None,
                    "away_ml": None,
                    "period_totals": {},
                    "period_spreads": {},
                },
            },
        )
        lines = current["lines"] if isinstance(current.get("lines"), dict) else {}
        if market == "total":
            current["found"] = True
            current["total"] = line_value
            lines["total"] = line_value
        elif market in {"spread", "home_spread", "away_spread"}:
            current["found"] = True
            side = str(row.get("side") or row.get("selection") or "").strip().upper()
            if market == "away_spread" or side == "AWAY":
                current["away_spread"] = line_value
                lines["away_spread"] = line_value
                current["home_spread"] = -line_value
                lines["home_spread"] = -line_value
            else:
                current["home_spread"] = line_value
                lines["home_spread"] = line_value
                current["away_spread"] = -line_value
                lines["away_spread"] = -line_value
        elif market in {"moneyline", "home_ml", "away_ml"}:
            current["found"] = True
            side = str(row.get("side") or row.get("selection") or "").strip().upper()
            if market == "away_ml" or side == "AWAY":
                current["away_ml"] = line_value
                lines["away_ml"] = line_value
            else:
                current["home_ml"] = line_value
                lines["home_ml"] = line_value
        elif include_period_totals and market in {"quarter_total", "period_total", "q_total"}:
            horizon = str(row.get("horizon") or row.get("period") or "").strip().lower()
            if horizon:
                current["found"] = True
                period_totals = lines.get("period_totals") if isinstance(lines.get("period_totals"), dict) else {}
                period_totals[horizon] = line_value
                lines["period_totals"] = period_totals

    games = [game for game in games_out.values() if bool(game.get("found"))]
    if not games:
        return None

    return {
        "ok": True,
        "date": date_str,
        "requested_date": date_str,
        "lookahead_applied": False,
        "include_period_totals": bool(include_period_totals),
        "source": source,
        "games": games,
        "generated_at": _generated_at_for([signal_path]),
    }