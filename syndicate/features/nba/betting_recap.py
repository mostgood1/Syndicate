from __future__ import annotations

import ast
import csv
import json
from datetime import datetime
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from syndicate.features.nba.sources import _artifact_roots


def _artifact_root() -> Path:
    roots = _artifact_roots()
    base_root = roots[0] if roots else (Path(__file__).resolve().parents[3] / "data" / "nba_source")
    return (base_root / "data" / "processed").resolve()


def _read_rows(path: Any) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [row for row in csv.DictReader(handle) if isinstance(row, dict)]
    except Exception:
        return []


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d")
    except Exception:
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _coerce_result(row: dict[str, str]) -> tuple[float | None, float | None]:
    home_pts = _coerce_float(row.get("home_pts"))
    away_pts = _coerce_float(row.get("visitor_pts"))
    return home_pts, away_pts


def _window_dates(query_string: str, available_dates: list[str]) -> tuple[list[str], str, str]:
    params = parse_qs(query_string or "", keep_blank_values=True)
    date_value = str((params.get("date") or [""])[0]).strip()
    if date_value:
        return [date_value], date_value, date_value

    since_value = str((params.get("since") or params.get("start") or [""])[0]).strip()
    until_value = str((params.get("until") or params.get("end") or [""])[0]).strip()
    if not since_value or not until_value:
        try:
            days = max(1, min(90, int(float(str((params.get("days") or ["14"])[0]).strip()))))
        except Exception:
            days = 14
        anchor = available_dates[-1] if available_dates else datetime.utcnow().strftime("%Y-%m-%d")
        anchor_dt = _parse_date(anchor) or datetime.utcnow()
        since_dt = anchor_dt - timedelta(days=days - 1)
        since_value = since_value or since_dt.strftime("%Y-%m-%d")
        until_value = until_value or anchor_dt.strftime("%Y-%m-%d")

    since_dt = _parse_date(since_value)
    until_dt = _parse_date(until_value)
    if since_dt is None or until_dt is None:
        return [], since_value, until_value
    if until_dt < since_dt:
        since_dt, until_dt = until_dt, since_dt
    out: list[str] = []
    current = since_dt
    while current <= until_dt:
        out.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return out, since_dt.strftime("%Y-%m-%d"), until_dt.strftime("%Y-%m-%d")


def _empty_bucket() -> dict[str, Any]:
    return {
        "total": 0,
        "resolved": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "stake_total": 0.0,
        "profit_total": 0.0,
        "accuracy_pct": None,
        "roi_pct": None,
    }


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    resolved = int(bucket.get("resolved") or 0)
    wins = int(bucket.get("wins") or 0)
    stake_total = float(bucket.get("stake_total") or 0.0)
    profit_total = float(bucket.get("profit_total") or 0.0)
    accuracy_pct = (100.0 * wins / resolved) if resolved > 0 else None
    roi_pct = (100.0 * profit_total / stake_total) if stake_total > 0 else None
    return {
        **bucket,
        "accuracy_pct": round(accuracy_pct, 1) if accuracy_pct is not None else None,
        "roi_pct": round(roi_pct, 1) if roi_pct is not None else None,
    }


def _tier_for_game(row: dict[str, str]) -> str:
    tier = str(row.get("tier") or "").strip().title()
    if tier in {"High", "Medium", "Low"}:
        return tier
    market = str(row.get("market") or "").strip().upper()
    ev_value = _coerce_float(row.get("ev"))
    edge_value = _coerce_float(row.get("edge"))
    if market == "ML":
        if ev_value is None:
            return "Low"
        if ev_value >= 0.04:
            return "High"
        if ev_value >= 0.02:
            return "Medium"
        return "Low"
    if edge_value is None:
        return "Low"
    abs_edge = abs(edge_value)
    if abs_edge >= 4.0:
        return "High"
    if abs_edge >= 2.0:
        return "Medium"
    return "Low"


def _settle_game_pick(row: dict[str, str], recon_row: dict[str, str] | None) -> tuple[bool, bool, bool, float]:
    if recon_row is None:
        return False, False, False, 0.0
    home_pts, away_pts = _coerce_result(recon_row)
    if home_pts is None or away_pts is None:
        return False, False, False, 0.0

    market = str(row.get("market") or "").strip().upper()
    side = str(row.get("side") or "").strip()
    home = str(row.get("home") or "").strip()
    away = str(row.get("away") or "").strip()
    line = _coerce_float(row.get("line"))
    price = _coerce_float(row.get("price"))
    margin = home_pts - away_pts
    total = home_pts + away_pts
    stake = 1.0

    def _decimal_price(american: float | None) -> float:
        if american is None or american == 0:
            return 2.0
        if american > 0:
            return 1.0 + (american / 100.0)
        return 1.0 + (100.0 / abs(american))

    resolved = False
    is_win = False
    is_push = False
    if market == "ML":
        resolved = True
        pick_home = side == home
        home_won = home_pts > away_pts
        is_win = pick_home == home_won
    elif market == "ATS" and line is not None:
        resolved = True
        if side == home:
            diff = margin + line
        elif side == away:
            diff = -margin - line
        else:
            diff = None
        if diff is None:
            resolved = False
        else:
            is_push = abs(diff) < 1e-9
            is_win = diff > 0
    elif market == "TOTAL" and line is not None:
        resolved = True
        diff = (total - line) if side.upper().startswith("O") else (line - total)
        is_push = abs(diff) < 1e-9
        is_win = diff > 0

    if not resolved:
        return False, False, False, 0.0
    if is_push:
        return True, False, True, 0.0
    if is_win:
        return True, True, False, (_decimal_price(price) - 1.0) * stake
    return True, False, False, -stake


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if text in {"", "None", "nan"}:
        return None
    try:
        return json.loads(text)
    except Exception:
        try:
            return ast.literal_eval(text)
        except Exception:
            return None


def _top_play(row: dict[str, str]) -> dict[str, Any] | None:
    top_play = _parse_jsonish(row.get("top_play"))
    if isinstance(top_play, dict) and top_play:
        return top_play
    plays = _parse_jsonish(row.get("plays"))
    if not isinstance(plays, list) or not plays:
        return None

    def _rank(play: Any) -> tuple[float, float]:
        if not isinstance(play, dict):
            return (-1e9, -1e9)
        ev_pct = _coerce_float(play.get("ev_pct"))
        ev_value = _coerce_float(play.get("ev"))
        edge_value = _coerce_float(play.get("edge"))
        primary = ev_pct if ev_pct is not None else ((ev_value or -1e9) * 100.0)
        secondary = abs(edge_value) if edge_value is not None else -1e9
        return (primary, secondary)

    ranked = sorted((play for play in plays if isinstance(play, dict)), key=_rank, reverse=True)
    return ranked[0] if ranked else None


def _tier_for_prop(row: dict[str, str], play: dict[str, Any] | None) -> str:
    tier = str(row.get("tier") or "").strip().title()
    if tier in {"High", "Medium", "Low"}:
        return tier
    ev_pct = _coerce_float((play or {}).get("ev_pct"))
    if ev_pct is None:
        ev_value = _coerce_float((play or {}).get("ev"))
        ev_pct = (ev_value * 100.0) if ev_value is not None else None
    if ev_pct is None:
        return "Low"
    if ev_pct >= 10.0:
        return "High"
    if ev_pct >= 5.0:
        return "Medium"
    return "Low"


def _recon_prop_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, float]]:
    index: dict[tuple[str, str], dict[str, float]] = {}
    for row in rows:
        key = (str(row.get("player_name") or "").strip().lower(), str(row.get("team_abbr") or "").strip().upper())
        index[key] = {
            "pts": _coerce_float(row.get("pts")) or 0.0,
            "reb": _coerce_float(row.get("reb")) or 0.0,
            "ast": _coerce_float(row.get("ast")) or 0.0,
            "threes": _coerce_float(row.get("threes")) or 0.0,
            "pra": _coerce_float(row.get("pra")) or 0.0,
        }
    return index


def _settle_prop_pick(row: dict[str, str], play: dict[str, Any] | None, recon_stats: dict[str, float] | None) -> tuple[bool, bool, bool, float, float | None]:
    if not play or recon_stats is None:
        return False, False, False, 0.0, None
    market = str(play.get("market") or "").strip().lower()
    side = str(play.get("side") or "").strip().upper()
    line = _coerce_float(play.get("line"))
    if line is None:
        return False, False, False, 0.0, None
    if market == "pts":
        actual = recon_stats.get("pts")
    elif market == "reb":
        actual = recon_stats.get("reb")
    elif market == "ast":
        actual = recon_stats.get("ast")
    elif market in {"3pt", "threes"}:
        actual = recon_stats.get("threes")
    elif market == "pra":
        actual = recon_stats.get("pra")
    elif market == "pr":
        actual = recon_stats.get("pts", 0.0) + recon_stats.get("reb", 0.0)
    elif market == "pa":
        actual = recon_stats.get("pts", 0.0) + recon_stats.get("ast", 0.0)
    elif market == "ra":
        actual = recon_stats.get("reb", 0.0) + recon_stats.get("ast", 0.0)
    else:
        return False, False, False, 0.0, None

    price = _coerce_float(play.get("price"))
    if price is None or price == 0:
        decimal = 1.909090909
    elif price > 0:
        decimal = 1.0 + (price / 100.0)
    else:
        decimal = 1.0 + (100.0 / abs(price))
    if abs(actual - line) < 1e-9:
        return True, False, True, 0.0, float(actual)
    is_win = (actual > line) if side == "OVER" else (actual < line)
    if is_win:
        return True, True, False, decimal - 1.0, float(actual)
    return True, False, False, -1.0, float(actual)


def _aggregate(items: list[dict[str, Any]], key: str) -> dict[str, Any]:
    buckets = {name: _empty_bucket() for name in ("Overall", "High", "Medium", "Low")}
    for item in items:
        section = item.get(key) if isinstance(item, dict) else None
        section_buckets = section.get("buckets") if isinstance(section, dict) else None
        if not isinstance(section_buckets, dict):
            continue
        for bucket_name, bucket in section_buckets.items():
            if bucket_name not in buckets or not isinstance(bucket, dict):
                continue
            for field in ("total", "resolved", "wins", "losses", "pushes"):
                buckets[bucket_name][field] += int(bucket.get(field) or 0)
            for field in ("stake_total", "profit_total"):
                buckets[bucket_name][field] += float(bucket.get(field) or 0.0)
    return {"buckets": {name: _finalize_bucket(bucket) for name, bucket in buckets.items()}}


@lru_cache(maxsize=256)
def build_betting_recap_payload(query_string: str) -> dict[str, Any] | None:
    artifact_root = _artifact_root()
    available_dates = sorted(
        {
            path.stem.replace("recommendations_", "")
            for path in artifact_root.glob("recommendations_*.csv")
            if len(path.stem.replace("recommendations_", "")) == 10
        }
    )
    dates, since_value, until_value = _window_dates(query_string, available_dates)
    items: list[dict[str, Any]] = []

    for date_value in dates:
        game_rows = _read_rows(artifact_root / f"recommendations_{date_value}.csv")
        recon_games = _read_rows(artifact_root / f"recon_games_{date_value}.csv")
        props_rows = _read_rows(artifact_root / f"props_recommendations_{date_value}.csv")
        recon_props = _read_rows(artifact_root / f"recon_props_{date_value}.csv")
        if not game_rows and not props_rows:
            continue

        recon_game_index = {
            (str(row.get("home_team") or "").strip(), str(row.get("visitor_team") or "").strip()): row
            for row in recon_games
        }
        recon_prop_index = _recon_prop_index(recon_props)

        game_buckets = {name: _empty_bucket() for name in ("Overall", "High", "Medium", "Low")}
        game_picks: list[dict[str, Any]] = []
        for row in game_rows:
            tier = _tier_for_game(row)
            for bucket_name in ("Overall", tier):
                game_buckets[bucket_name]["total"] += 1
            recon_row = recon_game_index.get((str(row.get("home") or "").strip(), str(row.get("away") or "").strip()))
            resolved, is_win, is_push, profit = _settle_game_pick(row, recon_row)
            if resolved:
                for bucket_name in ("Overall", tier):
                    bucket = game_buckets[bucket_name]
                    bucket["resolved"] += 1
                    if is_push:
                        bucket["pushes"] += 1
                    elif is_win:
                        bucket["wins"] += 1
                    else:
                        bucket["losses"] += 1
                    bucket["stake_total"] += 1.0
                    bucket["profit_total"] += profit
            home_pts, away_pts = _coerce_result(recon_row) if recon_row else (None, None)
            game_picks.append({
                "market": str(row.get("market") or "").strip().upper(),
                "home": row.get("home"),
                "away": row.get("away"),
                "side": row.get("side"),
                "line": _coerce_float(row.get("line")),
                "price": _coerce_float(row.get("price")),
                "ev": _coerce_float(row.get("ev")),
                "edge": _coerce_float(row.get("edge")),
                "tier": tier,
                "resolved": resolved,
                "result": "Push" if (resolved and is_push) else ("Win" if (resolved and is_win) else ("Loss" if resolved else None)),
                "profit": profit if resolved else None,
                "home_pts": home_pts,
                "away_pts": away_pts,
            })

        prop_buckets = {name: _empty_bucket() for name in ("Overall", "High", "Medium", "Low")}
        prop_picks: list[dict[str, Any]] = []
        for row in props_rows:
            play = _top_play(row)
            tier = _tier_for_prop(row, play)
            for bucket_name in ("Overall", tier):
                prop_buckets[bucket_name]["total"] += 1
            player = str(row.get("player") or "").strip()
            team = str(row.get("team") or "").strip().upper()
            recon_stats = recon_prop_index.get((player.lower(), team))
            resolved, is_win, is_push, profit, actual = _settle_prop_pick(row, play, recon_stats)
            if resolved:
                for bucket_name in ("Overall", tier):
                    bucket = prop_buckets[bucket_name]
                    bucket["resolved"] += 1
                    if is_push:
                        bucket["pushes"] += 1
                    elif is_win:
                        bucket["wins"] += 1
                    else:
                        bucket["losses"] += 1
                    bucket["stake_total"] += 1.0
                    bucket["profit_total"] += profit
            prop_picks.append({
                "player": player,
                "team": team,
                "market": (play or {}).get("market"),
                "side": (play or {}).get("side"),
                "line": _coerce_float((play or {}).get("line")),
                "price": _coerce_float((play or {}).get("price")),
                "ev": _coerce_float((play or {}).get("ev")),
                "edge": _coerce_float((play or {}).get("edge")),
                "tier": tier,
                "resolved": resolved,
                "actual": actual,
                "result": "Push" if (resolved and is_push) else ("Win" if (resolved and is_win) else ("Loss" if resolved else None)),
                "profit": profit if resolved else None,
            })

        items.append({
            "date": date_value,
            "games": {
                "available": bool(game_rows),
                "recon_available": bool(recon_games),
                "snapshot_used": False,
                "buckets": {name: _finalize_bucket(bucket) for name, bucket in game_buckets.items()},
                "picks": game_picks,
            },
            "props": {
                "available": bool(props_rows),
                "recon_available": bool(recon_props),
                "snapshot_used": False,
                "buckets": {name: _finalize_bucket(bucket) for name, bucket in prop_buckets.items()},
                "picks": prop_picks,
            },
        })

    return {
        "version": "recaps-v1",
        "window": {"since": since_value, "until": until_value},
        "items": sorted(items, key=lambda item: str(item.get("date") or ""), reverse=True),
        "summary": {
            "games": _aggregate(items, "games"),
            "props": _aggregate(items, "props"),
        },
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }