from __future__ import annotations

import csv
import ast
import json
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs


def _artifact_path(root: Path, filename: str) -> Path:
    return root / filename


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except Exception:
        return []
    return rows


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [row for row in csv.DictReader(handle) if isinstance(row, dict)]
    except Exception:
        return []


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, (list, dict)):
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


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _number(value: Any) -> float | None:
    number = _safe_float(value)
    if number is None:
        return None
    return float(number)


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _norm_player_name(value: str) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _canon_gid10(game_id: Any) -> str:
    text = str(game_id or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 10:
        return digits.zfill(10)
    return digits


def _parse_ymd(value: str) -> date | None:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_window(params: dict[str, list[str]], *, default_days: int = 14, allow_date_single: bool = False) -> list[str]:
    date_value = str((params.get("date") or [""])[0]).strip()
    if allow_date_single and date_value:
        return [date_value]

    start_value = str((params.get("start") or params.get("since") or [""])[0]).strip()
    end_value = str((params.get("end") or params.get("until") or [""])[0]).strip()
    if start_value and end_value:
        start_date = _parse_ymd(start_value)
        end_date = _parse_ymd(end_value)
        if start_date is None or end_date is None:
            return []
    else:
        try:
            days = max(1, min(120, int(float(str((params.get("days") or [str(default_days)])[0]).strip()))))
        except Exception:
            days = int(default_days)
        end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
        start_date = end_date - timedelta(days=days - 1)

    if end_date < start_date:
        start_date, end_date = end_date, start_date
    dates: list[str] = []
    current = start_date
    while current <= end_date:
        dates.append(current.isoformat())
        current = current + timedelta(days=1)
    return dates


def _parse_single_or_window(params: dict[str, list[str]], *, default_days: int = 30) -> list[str]:
    date_value = str((params.get("date") or [""])[0]).strip()
    if date_value:
        return [date_value]
    return _parse_window(params, default_days=default_days, allow_date_single=False)


def _stat_key(value: Any) -> str:
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


def _signal_ts(obj: dict[str, Any], idx: int) -> tuple[float, int]:
    for key in ("received_at", "ts", "created_at"):
        value = str(obj.get(key) or "").strip()
        if not value:
            continue
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized).timestamp(), idx
        except Exception:
            continue
    return float(idx), idx


def _dedup_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], tuple[int, dict[str, Any]]] = {}

    for idx, row in enumerate(rows):
        market = str(row.get("market") or "").strip().lower()
        gid = _canon_gid10(row.get("game_id_canon") or row.get("game_id"))
        horizon = str(row.get("horizon") or "").strip().lower() or None
        if market == "player_prop":
            name_key = _norm_player_name(str(row.get("name_key") or row.get("player") or ""))
            stat_key = _stat_key(row.get("stat"))
            side = str(row.get("side") or "").strip().upper() or None
            if not gid or not name_key or not stat_key or not side:
                continue
            key = (market, gid, name_key, stat_key, side)
        elif market in {"total", "half_total", "quarter_total"}:
            side = str(row.get("side") or "").strip().upper() or None
            if not gid or not side:
                continue
            key = (market, gid, horizon, side)
        elif market == "ats":
            side = str(row.get("side") or "").strip().upper() or None
            if not gid or not side:
                continue
            key = (market, gid, side)
        else:
            continue
        current = grouped.get(key)
        if current is None or _signal_ts(row, idx) < _signal_ts(current[1], current[0]):
            grouped[key] = (idx, row)

    return [row for _, row in sorted(grouped.values(), key=lambda item: item[0])]


def _profit_units(price: float, result: str | None) -> float | None:
    outcome = str(result or "").strip().lower()
    if outcome not in {"win", "loss", "push"}:
        return None
    if outcome == "push":
        return 0.0
    if outcome == "loss":
        return -1.0
    if price > 0:
        return float(price / 100.0)
    return float(100.0 / abs(price))


def _canonical_tag(tag: str) -> str:
    text = str(tag or "").strip().lower()
    if not text:
        return ""
    if ":" not in text:
        return text
    return text.split(":", 1)[0] + ":*"


def _tag_type(tag: str) -> str:
    text = str(tag or "").strip().lower()
    if not text:
        return ""
    if ":" not in text:
        return text
    return text.split(":", 1)[0]


def _driver_from_type(tag_type: str) -> str:
    text = str(tag_type or "").strip().lower()
    mapping = {
        "injury": "injury",
        "rot": "rotation",
        "rot_off": "rotation",
        "pf": "foul_trouble",
        "proj_min": "minutes",
        "rem_min": "minutes",
        "mp": "minutes",
        "sim": "sim",
        "risk": "adjustment",
        "support": "adjustment",
        "line_src": "market_quality",
        "line_age": "market_quality",
        "books": "market_quality",
        "market_span": "market_quality",
        "hold": "market_quality",
        "bettable": "market_quality",
        "bet_score": "market_quality",
        "gate": "market_quality",
        "edge_sigma": "signal_strength",
        "pace_mult": "player_adjustment",
        "role_mult": "player_adjustment",
        "hot": "player_adjustment",
        "foul_adj": "player_adjustment",
        "shrink": "shrink",
        "interval_drift": "interval_drift",
        "interval_drift_mag": "interval_drift",
        "recent_window": "recent_window",
        "recent_window_w": "recent_window",
        "endgame_foul": "endgame_foul",
        "endgame_foul_mag": "endgame_foul",
        "time": "time",
        "mgn": "margin",
        "pace": "pace_eff",
        "poss": "pace_eff",
        "ppp": "pace_eff",
        "spr": "spread",
        "ats_side": "spread",
        "ctx": "context",
        "scope": "context",
    }
    return mapping.get(text, text)


def _american_to_decimal(price: Any) -> float | None:
    number = _safe_float(price)
    if number is None or number == 0:
        return None
    if number > 0:
        return 1.0 + (number / 100.0)
    return 1.0 + (100.0 / abs(number))


def _init_accuracy_bucket() -> dict[str, Any]:
    return {
        "bets": 0,
        "resolved": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "stake_total": 0.0,
        "profit_total": 0.0,
    }


def _finalize_accuracy_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    resolved = int(bucket.get("resolved") or 0)
    wins = int(bucket.get("wins") or 0)
    stake_total = float(bucket.get("stake_total") or 0.0)
    profit_total = float(bucket.get("profit_total") or 0.0)
    accuracy = (float(wins) / float(resolved)) if resolved > 0 else None
    roi = (profit_total / stake_total) if stake_total > 0 else None
    payload = dict(bucket)
    payload["accuracy"] = accuracy
    payload["accuracy_pct"] = (round(100.0 * accuracy, 3) if accuracy is not None else None)
    payload["roi"] = roi
    payload["roi_pct"] = (round(100.0 * roi, 3) if roi is not None else None)
    return payload


def _apply_accuracy_result(bucket: dict[str, Any], result: str | None, price: Any) -> None:
    bucket["bets"] += 1
    if not result:
        return
    bucket["resolved"] += 1
    stake = 1.0
    decimal_price = _american_to_decimal(price) or 1.909090909
    profit = 0.0
    if result == "push":
        bucket["pushes"] += 1
    elif result == "win":
        bucket["wins"] += 1
        profit = (float(decimal_price) - 1.0) * stake
    elif result == "loss":
        bucket["losses"] += 1
        profit = -stake
    bucket["stake_total"] += stake
    bucket["profit_total"] += float(profit)


def _score_market_games_day(root: Path, date_str: str) -> dict[str, Any]:
    rec_rows = _read_csv_rows(_artifact_path(root, f"recommendations_{date_str}.csv"))
    if not rec_rows:
        rec_rows = _read_csv_rows(_artifact_path(root, f"recommendations_sim_{date_str}.csv"))
    recon_rows = _read_csv_rows(_artifact_path(root, f"recon_games_{date_str}.csv"))
    if not rec_rows or not recon_rows:
        return {"available": False}

    finals: dict[tuple[str, str], tuple[float, float]] = {}
    for row in recon_rows:
        home = _norm_text(row.get("home_team"))
        away = _norm_text(row.get("visitor_team"))
        home_pts = _number(row.get("home_pts"))
        away_pts = _number(row.get("visitor_pts"))
        if home and away and home_pts is not None and away_pts is not None:
            finals[(home, away)] = (home_pts, away_pts)

    overall = _init_accuracy_bucket()
    by_market: dict[str, dict[str, Any]] = {}
    for row in rec_rows:
        market = str(row.get("market") or "").strip().upper()
        side = str(row.get("side") or "").strip()
        home = _norm_text(row.get("home"))
        away = _norm_text(row.get("away"))
        price = row.get("price")
        line = _number(row.get("line"))
        if not market or not home or not away:
            continue
        scores = finals.get((home, away))
        if scores is None:
            scores = finals.get((away, home))
            if scores is not None:
                scores = (scores[1], scores[0])
        if scores is None:
            _apply_accuracy_result(overall, None, price)
            continue
        home_pts, away_pts = scores
        result = None
        if market == "TOTAL" and line is not None:
            actual_total = float(home_pts) + float(away_pts)
            if abs(actual_total - float(line)) < 1e-9:
                result = "push"
            else:
                normalized_side = side.lower()
                if normalized_side.startswith("o"):
                    result = "win" if actual_total > float(line) else "loss"
                elif normalized_side.startswith("u"):
                    result = "win" if actual_total < float(line) else "loss"
        elif market == "ATS" and line is not None:
            normalized_side = _norm_text(side)
            margin = float(home_pts) - float(away_pts)
            diff = None
            if normalized_side == home:
                diff = margin + float(line)
            elif normalized_side == away:
                diff = (float(away_pts) - float(home_pts)) + float(line)
            if diff is not None:
                if abs(diff) < 1e-9:
                    result = "push"
                else:
                    result = "win" if diff > 0 else "loss"
        elif market == "ML":
            normalized_side = _norm_text(side)
            if home_pts != away_pts:
                if normalized_side == home:
                    result = "win" if home_pts > away_pts else "loss"
                elif normalized_side == away:
                    result = "win" if away_pts > home_pts else "loss"

        if market not in by_market:
            by_market[market] = _init_accuracy_bucket()
        _apply_accuracy_result(overall, result, price)
        _apply_accuracy_result(by_market[market], result, price)

    return {
        "available": True,
        "overall": _finalize_accuracy_bucket(overall),
        "by_market": {key: _finalize_accuracy_bucket(bucket) for key, bucket in by_market.items()},
    }


def _actual_for_prop_market(stats: dict[str, Any], market: str) -> float | None:
    market_key = str(market or "").strip().lower()
    if not stats:
        return None
    if market_key in {"pts", "reb", "ast", "threes", "stl", "blk", "tov", "pra", "pr", "pa", "ra"}:
        return _number(stats.get(market_key))
    return None


def _pick_top_play(plays: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not plays:
        return None

    def _regular_price(play: dict[str, Any]) -> bool:
        price = _safe_float(play.get("price"))
        return price is not None and price >= -150.0 and price <= 150.0

    def _regular_market(play: dict[str, Any]) -> bool:
        market = str(play.get("market") or "").strip().lower()
        return market not in {"dd", "td"}

    regular = [play for play in plays if _regular_market(play) and _regular_price(play)]
    candidates = regular if regular else plays

    def _score(play: dict[str, Any]) -> float:
        ev_pct = _safe_float(play.get("ev_pct"))
        if ev_pct is not None:
            return ev_pct
        ev = _safe_float(play.get("ev"))
        return (ev * 100.0) if ev is not None else -1e18

    candidates = sorted(candidates, key=_score, reverse=True)
    return candidates[0] if candidates else None


def _score_market_props_day(root: Path, date_str: str) -> dict[str, Any]:
    props_rows = _read_csv_rows(_artifact_path(root, f"props_recommendations_{date_str}.csv"))
    recon_rows = _read_csv_rows(_artifact_path(root, f"recon_props_{date_str}.csv"))
    if not props_rows or not recon_rows:
        return {"available": False}

    recon_index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in recon_rows:
        player = _norm_text(row.get("player_name") or row.get("player"))
        team = str(row.get("team_abbr") or row.get("team") or "").strip().upper()
        if not player or not team:
            continue
        numeric = dict(row)
        for key in ("pts", "reb", "ast", "threes", "stl", "blk", "tov", "pra", "pr", "pa", "ra"):
            numeric[key] = _number(row.get(key))
        if numeric.get("pr") is None and numeric.get("pts") is not None and numeric.get("reb") is not None:
            numeric["pr"] = float(numeric["pts"]) + float(numeric["reb"])
        if numeric.get("pa") is None and numeric.get("pts") is not None and numeric.get("ast") is not None:
            numeric["pa"] = float(numeric["pts"]) + float(numeric["ast"])
        if numeric.get("ra") is None and numeric.get("reb") is not None and numeric.get("ast") is not None:
            numeric["ra"] = float(numeric["reb"]) + float(numeric["ast"])
        recon_index[(player, team)] = numeric

    overall = _init_accuracy_bucket()
    by_market: dict[str, dict[str, Any]] = {}
    for row in props_rows:
        plays = _parse_jsonish(row.get("plays") or row.get("_plays_list"))
        plays_list = plays if isinstance(plays, list) else []
        top_play = _pick_top_play([play for play in plays_list if isinstance(play, dict)])
        if not isinstance(top_play, dict):
            continue
        market = str(top_play.get("market") or "").strip().lower()
        side = str(top_play.get("side") or "").strip().upper()
        line = _number(top_play.get("line"))
        price = top_play.get("price")
        if not market or not side or line is None:
            _apply_accuracy_result(overall, None, price)
            continue
        player = _norm_text(row.get("player"))
        team = str(row.get("team") or "").strip().upper()
        stats = recon_index.get((player, team), {})
        actual = _actual_for_prop_market(stats, market)
        result = None
        if actual is not None:
            if abs(float(actual) - float(line)) < 1e-9:
                result = "push"
            elif side == "OVER":
                result = "win" if float(actual) > float(line) else "loss"
            elif side == "UNDER":
                result = "win" if float(actual) < float(line) else "loss"
        if market not in by_market:
            by_market[market] = _init_accuracy_bucket()
        _apply_accuracy_result(overall, result, price)
        _apply_accuracy_result(by_market[market], result, price)

    return {
        "available": True,
        "overall": _finalize_accuracy_bucket(overall),
        "by_market": {key: _finalize_accuracy_bucket(bucket) for key, bucket in by_market.items()},
    }


def build_local_market_accuracy_payload(query_string: str, artifact_root: Path) -> dict[str, Any] | None:
    params = parse_qs(query_string or "", keep_blank_values=True)
    date_list = _parse_single_or_window(params, default_days=30)
    if not date_list:
        return None

    any_available = False
    rows: list[dict[str, Any]] = []
    games_total = _init_accuracy_bucket()
    props_total = _init_accuracy_bucket()

    for date_str in date_list:
        games = _score_market_games_day(artifact_root, date_str)
        props = _score_market_props_day(artifact_root, date_str)
        games_overall = games.get("overall") if isinstance(games, dict) else None
        props_overall = props.get("overall") if isinstance(props, dict) else None
        if isinstance(games_overall, dict):
            any_available = True
            for key in games_total.keys():
                games_total[key] += float(games_overall.get(key) or 0.0) if key in {"stake_total", "profit_total"} else int(games_overall.get(key) or 0)
        if isinstance(props_overall, dict):
            any_available = True
            for key in props_total.keys():
                props_total[key] += float(props_overall.get(key) or 0.0) if key in {"stake_total", "profit_total"} else int(props_overall.get(key) or 0)

        combined = _init_accuracy_bucket()
        for source_overall in (games_overall, props_overall):
            if not isinstance(source_overall, dict):
                continue
            for key in combined.keys():
                combined[key] += float(source_overall.get(key) or 0.0) if key in {"stake_total", "profit_total"} else int(source_overall.get(key) or 0)

        rows.append(
            {
                "date": date_str,
                "games": games,
                "props": props,
                "combined": {
                    "available": bool(games.get("available") or props.get("available")) if isinstance(games, dict) and isinstance(props, dict) else False,
                    "overall": _finalize_accuracy_bucket(combined),
                },
            }
        )

    if not any_available:
        return None

    combined_total = _init_accuracy_bucket()
    for key in combined_total.keys():
        combined_total[key] = games_total[key] + props_total[key]

    return {
        "ok": True,
        "version": "accuracy-market-v1",
        "window": {"since": date_list[0], "until": date_list[-1]},
        "days": rows,
        "summary": {
            "games": {"available": True, "overall": _finalize_accuracy_bucket(games_total)},
            "props": {"available": True, "overall": _finalize_accuracy_bucket(props_total)},
            "combined": {"available": True, "overall": _finalize_accuracy_bucket(combined_total)},
        },
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def build_empty_market_accuracy_payload(query_string: str) -> dict[str, Any] | None:
    params = parse_qs(query_string or "", keep_blank_values=True)
    date_list = _parse_single_or_window(params, default_days=30)
    if not date_list:
        return None

    empty_bucket = _finalize_accuracy_bucket(_init_accuracy_bucket())
    rows = []
    for date_str in date_list:
        rows.append(
            {
                "date": date_str,
                "games": {"available": False},
                "props": {"available": False},
                "combined": {
                    "available": False,
                    "overall": dict(empty_bucket),
                },
            }
        )

    return {
        "ok": True,
        "version": "accuracy-market-v1",
        "window": {"since": date_list[0], "until": date_list[-1]},
        "days": rows,
        "summary": {
            "games": {"available": False, "overall": dict(empty_bucket)},
            "props": {"available": False, "overall": dict(empty_bucket)},
            "combined": {"available": False, "overall": dict(empty_bucket)},
        },
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def _load_recon_indexes(root: Path, date_str: str) -> dict[str, Any]:
    games_rows = _read_csv_rows(_artifact_path(root, f"recon_games_{date_str}.csv"))
    quarters_rows = _read_csv_rows(_artifact_path(root, f"recon_quarters_{date_str}.csv"))
    props_rows = _read_csv_rows(_artifact_path(root, f"recon_props_{date_str}.csv"))

    games_by_gid: dict[str, dict[str, Any]] = {}
    quarters_by_gid: dict[str, dict[str, Any]] = {}
    props_by_gid_name: dict[tuple[str, str], dict[str, Any]] = {}

    for row in games_rows:
        gid = _canon_gid10(row.get("game_id"))
        if gid and gid not in games_by_gid:
            games_by_gid[gid] = row

    for row in quarters_rows:
        gid = _canon_gid10(row.get("game_id"))
        if gid and gid not in quarters_by_gid:
            quarters_by_gid[gid] = row

    for row in props_rows:
        gid = _canon_gid10(row.get("game_id"))
        name_key = _norm_player_name(str(row.get("player_name") or row.get("player") or ""))
        if not gid or not name_key:
            continue
        numeric_row: dict[str, Any] = dict(row)
        for key in ("pts", "reb", "ast", "threes", "stl", "blk", "tov", "pra", "pr", "pa", "ra"):
            numeric_row[key] = _number(row.get(key))
        if numeric_row.get("pr") is None and numeric_row.get("pts") is not None and numeric_row.get("reb") is not None:
            numeric_row["pr"] = float(numeric_row["pts"]) + float(numeric_row["reb"])
        if numeric_row.get("pa") is None and numeric_row.get("pts") is not None and numeric_row.get("ast") is not None:
            numeric_row["pa"] = float(numeric_row["pts"]) + float(numeric_row["ast"])
        if numeric_row.get("ra") is None and numeric_row.get("reb") is not None and numeric_row.get("ast") is not None:
            numeric_row["ra"] = float(numeric_row["reb"]) + float(numeric_row["ast"])
        if numeric_row.get("pra") is None and numeric_row.get("pts") is not None and numeric_row.get("reb") is not None and numeric_row.get("ast") is not None:
            numeric_row["pra"] = float(numeric_row["pts"]) + float(numeric_row["reb"]) + float(numeric_row["ast"])
        props_by_gid_name[(gid, name_key)] = numeric_row

    return {
        "games": games_by_gid,
        "quarters": quarters_by_gid,
        "props": props_by_gid_name,
        "games_ok": bool(games_by_gid),
        "quarters_ok": bool(quarters_by_gid),
        "props_ok": bool(props_by_gid_name),
    }


def _actual_total(indexes: dict[str, Any], gid: str, market: str, horizon: str | None) -> float | None:
    if market == "total":
        return _number((indexes.get("games") or {}).get(gid, {}).get("total_actual"))
    if market == "half_total":
        key = "actual_h1_total" if horizon == "h1" else "actual_h2_total" if horizon == "h2" else ""
        return _number((indexes.get("quarters") or {}).get(gid, {}).get(key)) if key else None
    if market == "quarter_total" and horizon in {"q1", "q2", "q3", "q4"}:
        return _number((indexes.get("quarters") or {}).get(gid, {}).get(f"actual_{horizon}_total"))
    return None


def _actual_ats_margin_home(indexes: dict[str, Any], gid: str) -> float | None:
    row = (indexes.get("games") or {}).get(gid, {})
    home_pts = _number(row.get("home_pts"))
    away_pts = _number(row.get("visitor_pts"))
    if home_pts is None or away_pts is None:
        return None
    return float(home_pts) - float(away_pts)


def _actual_prop(indexes: dict[str, Any], gid: str, name_key: str, stat_key: str) -> float | None:
    row = (indexes.get("props") or {}).get((gid, name_key), {})
    return _number(row.get(stat_key))


def _settle_over_under(actual: float | None, line: float | None, side: str | None) -> str | None:
    selection = str(side or "").strip().upper()
    if actual is None or line is None or selection not in {"OVER", "UNDER"}:
        return None
    if float(actual) == float(line):
        return "push"
    if selection == "OVER":
        return "win" if float(actual) > float(line) else "loss"
    return "win" if float(actual) < float(line) else "loss"


def _settle_ats(margin_home: float | None, line: float | None, side: str | None, home: str | None) -> str | None:
    if margin_home is None or line is None or not side or not home:
        return None
    side_key = str(side).strip().upper()
    home_key = str(home).strip().upper()
    diff = float(margin_home) + float(line) if side_key == home_key else (-float(margin_home)) + float(line)
    if abs(diff) < 1e-9:
        return "push"
    return "win" if diff > 0 else "loss"


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [row for row in rows if str(row.get("result") or "") in {"win", "loss", "push"}]
    wins = sum(1 for row in settled if row.get("result") == "win")
    losses = sum(1 for row in settled if row.get("result") == "loss")
    pushes = sum(1 for row in settled if row.get("result") == "push")
    total = wins + losses + pushes
    profit_total = sum(float(_safe_float(row.get("profit_units")) or 0.0) for row in settled)
    return {
        "status": "ok" if total > 0 else "empty",
        "n_settled": total,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": (float(wins) / float(wins + losses)) if (wins + losses) > 0 else None,
        "roi_units_per_bet": (profit_total / float(total)) if total > 0 else None,
        "profit_units": profit_total if total > 0 else 0.0,
    }


def _group_stats(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        if str(row.get("result") or "") not in {"win", "loss", "push"}:
            continue
        key = tuple(str(row.get(name) or "") for name in keys)
        grouped.setdefault(key, []).append(row)
    items: list[dict[str, Any]] = []
    for key, group_rows in grouped.items():
        summary = _summary(group_rows)
        item = {name: value for name, value in zip(keys, key)}
        item.update(
            {
                "n": int(summary.get("n_settled") or 0),
                "wins": int(summary.get("wins") or 0),
                "losses": int(summary.get("losses") or 0),
                "pushes": int(summary.get("pushes") or 0),
                "win_rate": summary.get("win_rate"),
                "roi_units_per_bet": summary.get("roi_units_per_bet"),
            }
        )
        items.append(item)
    items.sort(key=lambda row: tuple([-(row.get("n") or 0)] + [str(row.get(name) or "") for name in keys]))
    return items


def _tags_from_row(row: dict[str, Any]) -> list[str]:
    value = row.get("driver_tags")
    if not isinstance(value, list):
        value = row.get("tags")
    if not isinstance(value, list):
        value = []
    return [str(tag) for tag in value if str(tag).strip()]


def _attach_breakdowns(summary: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    payload = dict(summary)
    payload["by_lens_side"] = _group_stats(rows, ["lens", "side"])

    tag_rows: list[dict[str, Any]] = []
    tagset_rows: list[dict[str, Any]] = []
    canonical_rows: list[dict[str, Any]] = []
    type_rows: list[dict[str, Any]] = []
    driver_rows: list[dict[str, Any]] = []
    for row in rows:
        tags = _tags_from_row(row)
        if tags:
            tagset_rows.append({**row, "tagset": "|".join(sorted(set(tags))[:4])})
        for tag in tags:
            tag_rows.append({**row, "tag": tag})
            canonical = _canonical_tag(tag)
            if canonical:
                canonical_rows.append({**row, "tag": canonical})
            tag_type = _tag_type(tag)
            if tag_type:
                type_rows.append({**row, "type": tag_type})
                driver = _driver_from_type(tag_type)
                if driver:
                    driver_rows.append({**row, "driver": driver})
    payload["by_driver_tag"] = _group_stats(tag_rows, ["tag"])
    payload["by_driver_tagset"] = _group_stats([row for row in tagset_rows if row.get("tagset")], ["tagset"])
    payload["by_driver_tag_canonical"] = _group_stats(canonical_rows, ["tag"])
    payload["by_driver_tag_type"] = _group_stats(type_rows, ["type"])
    payload["by_driver"] = _group_stats(driver_rows, ["driver"])
    return payload


def _hit_summary_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "wins": 0, "losses": 0, "pushes": 0, "hit_rate": None}
    settled = [row for row in rows if str(row.get("result") or "") in {"win", "loss", "push"}]
    if not settled:
        return {"n": len(rows), "wins": 0, "losses": 0, "pushes": 0, "hit_rate": None}
    wins = sum(1 for row in settled if row.get("result") == "win")
    losses = sum(1 for row in settled if row.get("result") == "loss")
    pushes = sum(1 for row in settled if row.get("result") == "push")
    denom = wins + losses
    hit_rate = (float(wins) / float(denom)) if denom > 0 else None
    return {
        "n": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate": hit_rate,
        "hit_rate_pct": (round(100.0 * hit_rate, 3) if hit_rate is not None else None),
    }


def _group_hit_rows(rows: list[dict[str, Any]], key: str, *, label_key: str = "key") -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = str(row.get(key) or "") or "(blank)"
        grouped.setdefault(label, []).append(row)
    items = [{label_key: label, **_hit_summary_rows(group_rows)} for label, group_rows in grouped.items()]
    items.sort(key=lambda row: (-(row.get("n") or 0), str(row.get(label_key) or "")))
    return items


def _group_hit_tags(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tagged_rows: list[dict[str, Any]] = []
    for row in rows:
        for tag in _tags_from_row(row):
            tagged_rows.append({**row, "tag": tag})
    return _group_hit_rows(tagged_rows, "tag", label_key="tag")


def _score_day(root: Path, date_str: str, *, allowed_markets: set[str], assume_price: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    signal_path = _artifact_path(root, f"live_lens_signals_{date_str}.jsonl")
    raw_rows = _read_jsonl(signal_path)
    if not raw_rows:
        return [], {"signals": {"exists": False, "raw": 0, "filtered": 0, "dedup": 0, "path": str(signal_path)}}

    filtered: list[dict[str, Any]] = []
    for row in raw_rows:
        market = str(row.get("market") or "").strip().lower()
        if market not in allowed_markets:
            continue
        if str(row.get("klass") or "").strip().upper() != "BET":
            continue
        if market == "player_prop" and str(row.get("line_source") or "").strip().lower() == "model":
            continue
        filtered.append(dict(row))

    deduped = _dedup_first(filtered)
    indexes = _load_recon_indexes(root, date_str)
    scored: list[dict[str, Any]] = []
    for row in deduped:
        market = str(row.get("market") or "").strip().lower()
        gid = _canon_gid10(row.get("game_id_canon") or row.get("game_id"))
        if not gid:
            continue
        home = str(row.get("home") or "").strip().upper() or None
        away = str(row.get("away") or "").strip().upper() or None
        side = str(row.get("side") or "").strip().upper() or None
        horizon = str(row.get("horizon") or "").strip().lower() or None
        live_line = _number(row.get("line")) if market == "player_prop" else _number(row.get("live_line"))
        if live_line is None:
            live_line = _number(row.get("live_line"))
        result = None
        player = None
        stat_key = None
        name_key = None
        if market in {"total", "half_total", "quarter_total"}:
            result = _settle_over_under(_actual_total(indexes, gid, market, horizon), live_line, side)
        elif market == "ats":
            result = _settle_ats(_actual_ats_margin_home(indexes, gid), live_line, side, home)
        elif market == "player_prop":
            player = str(row.get("player") or "").strip() or None
            stat_key = _stat_key(row.get("stat"))
            name_key = _norm_player_name(str(row.get("name_key") or player or "")) or None
            result = _settle_over_under(_actual_prop(indexes, gid, name_key or "", stat_key), live_line, side)

        tags = _tags_from_row(row)
        scored.append(
            {
                "date": date_str,
                "market": market,
                "horizon": horizon,
                "game_id": gid,
                "home": home,
                "away": away,
                "player": player,
                "name_key": name_key,
                "stat": stat_key,
                "side": side,
                "elapsed": _number(row.get("elapsed")),
                "remaining": _number(row.get("remaining")),
                "live_line": live_line,
                "edge": _number(row.get("edge_adj") if row.get("edge_adj") is not None else row.get("edge")),
                "result": result,
                "profit_units": _profit_units(assume_price, result),
                "lens": stat_key if market == "player_prop" else str(horizon or ""),
                "driver": _driver_from_type(_tag_type(tags[0])) if tags else "",
                "driver_tags": tags,
            }
        )

    return scored, {
        "signals": {"exists": True, "raw": len(raw_rows), "filtered": len(filtered), "dedup": len(deduped), "path": str(signal_path)},
        "recon": {"games": bool(indexes.get("games_ok")), "quarters": bool(indexes.get("quarters_ok")), "props": bool(indexes.get("props_ok"))},
    }


def build_local_live_accuracy_payload(query_string: str, artifact_root: Path, *, mode: str) -> dict[str, Any] | None:
    params = parse_qs(query_string or "", keep_blank_values=True)
    date_list = _parse_window(params, default_days=14, allow_date_single=False)
    if not date_list:
        return None
    include_rows = str((params.get("include_rows") or [""])[0]).strip().lower() in {"1", "true", "yes"}
    full_game_only = str((params.get("full_game_only") or [""])[0]).strip().lower() in {"1", "true", "yes"}
    try:
        max_rows = max(100, min(20000, int(float(str((params.get("max_rows") or ["2000"])[0]).strip()))))
    except Exception:
        max_rows = 2000
    try:
        assume_price = float(str((params.get("assume_price") or ["-110"])[0]).strip())
    except Exception:
        assume_price = -110.0
    if assume_price > 0:
        assume_price = -abs(assume_price)

    mode_key = str(mode or "").strip().lower()
    allowed_markets = {"player_prop"} if mode_key == "prop" else {"total", "half_total", "quarter_total", "ats"}
    any_signal_files = False
    all_rows: list[dict[str, Any]] = []
    per_day: list[dict[str, Any]] = []
    debug_days: list[dict[str, Any]] = []
    for date_str in date_list:
        rows, meta = _score_day(artifact_root, date_str, allowed_markets=allowed_markets, assume_price=assume_price)
        if meta.get("signals", {}).get("exists"):
            any_signal_files = True
        if mode_key == "game":
            if full_game_only:
                rows = [row for row in rows if row.get("market") in {"total", "ats"}]
            totals_rows = [row for row in rows if row.get("market") in {"total", "half_total", "quarter_total"}]
            if full_game_only:
                totals_rows = [row for row in totals_rows if row.get("market") == "total"]
            ats_rows = [row for row in rows if row.get("market") == "ats"]
            all_rows.extend(rows)
            per_day.append({"date": date_str, "totals": _summary(totals_rows), "ats": _summary(ats_rows)})
        else:
            all_rows.extend(rows)
            per_day.append({"date": date_str, "props": _summary(rows)})
        debug_days.append({"date": date_str, **meta})

    if not any_signal_files:
        return None

    history = None
    if include_rows and all_rows:
        sort_keys = ("date", "market", "game_id", "player", "stat") if mode_key == "prop" else ("date", "market", "game_id")
        history_rows = sorted(all_rows, key=lambda row: tuple(str(row.get(key) or "") for key in sort_keys), reverse=True)[:max_rows]
        history = {"rows": history_rows}

    if mode_key == "game":
        totals_rows = [row for row in all_rows if row.get("market") in {"total", "half_total", "quarter_total"}]
        if full_game_only:
            totals_rows = [row for row in totals_rows if row.get("market") == "total"]
        ats_rows = [row for row in all_rows if row.get("market") == "ats"]
        overall = {"totals": _attach_breakdowns(_summary(totals_rows), totals_rows), "ats": _attach_breakdowns(_summary(ats_rows), ats_rows)}
        payload: dict[str, Any] = {
            "ok": True,
            "status": "ok" if (overall["totals"].get("n_settled") or 0) > 0 or (overall["ats"].get("n_settled") or 0) > 0 else "empty",
            "meta": {"start": date_list[0], "end": date_list[-1], "days": len(date_list), "assume_price": assume_price, "full_game_only": full_game_only, "include_rows": include_rows, "max_rows": max_rows, "source": "local_mirror"},
            "overall": overall,
            "per_day": per_day,
            "history": history,
            "debug": {"days": debug_days},
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        if payload["status"] == "empty":
            payload["message"] = "No settled BET rows (missing signals and/or recon outputs)."
        return payload

    props_overall = _attach_breakdowns(_summary(all_rows), all_rows)
    payload = {
        "ok": True,
        "status": "ok" if (props_overall.get("n_settled") or 0) > 0 else "empty",
        "meta": {"start": date_list[0], "end": date_list[-1], "days": len(date_list), "assume_price": assume_price, "include_rows": include_rows, "max_rows": max_rows, "source": "local_mirror"},
        "overall": {"props": props_overall},
        "per_day": per_day,
        "history": history,
        "debug": {"days": debug_days},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    if payload["status"] == "empty":
        payload["message"] = "No settled BET player-prop rows (missing signals and/or recon outputs)."
    return payload


def build_empty_live_accuracy_payload(query_string: str, *, mode: str) -> dict[str, Any] | None:
    params = parse_qs(query_string or "", keep_blank_values=True)
    date_list = _parse_window(params, default_days=14, allow_date_single=False)
    if not date_list:
        return None
    include_rows = str((params.get("include_rows") or [""])[0]).strip().lower() in {"1", "true", "yes"}
    full_game_only = str((params.get("full_game_only") or [""])[0]).strip().lower() in {"1", "true", "yes"}
    try:
        max_rows = max(100, min(20000, int(float(str((params.get("max_rows") or ["2000"])[0]).strip()))))
    except Exception:
        max_rows = 2000
    try:
        assume_price = float(str((params.get("assume_price") or ["-110"])[0]).strip())
    except Exception:
        assume_price = -110.0
    if assume_price > 0:
        assume_price = -abs(assume_price)

    mode_key = str(mode or "").strip().lower()
    debug_days = [{"date": date_str, "signals": {"exists": False}} for date_str in date_list]
    if mode_key == "game":
        totals_summary = _attach_breakdowns(_summary([]), [])
        ats_summary = _attach_breakdowns(_summary([]), [])
        return {
            "ok": True,
            "status": "empty",
            "message": "No settled BET rows (missing signals and/or recon outputs).",
            "meta": {
                "start": date_list[0],
                "end": date_list[-1],
                "days": len(date_list),
                "assume_price": assume_price,
                "full_game_only": full_game_only,
                "include_rows": include_rows,
                "max_rows": max_rows,
                "source": "local_mirror",
            },
            "overall": {"totals": totals_summary, "ats": ats_summary},
            "per_day": [{"date": date_str, "totals": _summary([]), "ats": _summary([])} for date_str in date_list],
            "history": None,
            "debug": {"days": debug_days},
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }

    props_summary = _attach_breakdowns(_summary([]), [])
    return {
        "ok": True,
        "status": "empty",
        "message": "No settled BET player-prop rows (missing signals and/or recon outputs).",
        "meta": {
            "start": date_list[0],
            "end": date_list[-1],
            "days": len(date_list),
            "assume_price": assume_price,
            "include_rows": include_rows,
            "max_rows": max_rows,
            "source": "local_mirror",
        },
        "overall": {"props": props_summary},
        "per_day": [{"date": date_str, "props": _summary([])} for date_str in date_list],
        "history": None,
        "debug": {"days": debug_days},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def build_local_live_lens_daily_accuracy_payload(query_string: str, artifact_root: Path) -> dict[str, Any] | None:
    params = parse_qs(query_string or "", keep_blank_values=True)
    date_list = _parse_window(params, default_days=7, allow_date_single=True)
    if not date_list:
        return None

    allowed_markets = {"total", "half_total", "quarter_total", "ats", "player_prop"}
    any_signal_files = False
    all_rows: list[dict[str, Any]] = []
    days: list[dict[str, Any]] = []

    for date_str in date_list:
        rows, meta = _score_day(artifact_root, date_str, allowed_markets=allowed_markets, assume_price=-110.0)
        signal_info = dict(meta.get("signals") or {}) if isinstance(meta, dict) else {}
        if signal_info.get("exists"):
            any_signal_files = True
        warnings: list[str] = []
        try:
            if signal_info.get("exists") and int(signal_info.get("raw") or 0) < 500:
                warnings.append("signals_file_small")
        except Exception:
            pass
        days.append(
            {
                "date": date_str,
                "available": bool(rows),
                "signals": signal_info,
                "warnings": warnings,
                "summary": _hit_summary_rows(rows),
                "by_market": _group_hit_rows(rows, "market"),
                "by_horizon": _group_hit_rows(rows, "horizon"),
                "by_klass": _group_hit_rows(rows, "klass"),
                "by_stat": _group_hit_rows(rows, "stat"),
                "by_tag": _group_hit_tags(rows),
            }
        )
        all_rows.extend(rows)

    if not any_signal_files:
        return None

    return {
        "ok": True,
        "version": "live-lens-accuracy-v1",
        "artifacts_dir": {
            "path": str(artifact_root),
            "env_configured": False,
            "running_on_render": False,
            "warnings": [],
        },
        "window": {"since": date_list[0], "until": date_list[-1]},
        "days": days,
        "summary": {
            "available": bool(all_rows),
            "summary": _hit_summary_rows(all_rows),
            "by_market": _group_hit_rows(all_rows, "market"),
            "by_horizon": _group_hit_rows(all_rows, "horizon"),
            "by_klass": _group_hit_rows(all_rows, "klass"),
            "by_stat": _group_hit_rows(all_rows, "stat"),
            "by_tag": _group_hit_tags(all_rows),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def build_empty_live_lens_daily_accuracy_payload(query_string: str, artifact_root: Path) -> dict[str, Any] | None:
    params = parse_qs(query_string or "", keep_blank_values=True)
    date_list = _parse_window(params, default_days=7, allow_date_single=True)
    if not date_list:
        return None

    days = []
    for date_str in date_list:
        signal_path = _artifact_path(artifact_root, f"live_lens_signals_{date_str}.jsonl")
        days.append(
            {
                "date": date_str,
                "available": False,
                "signals": {"exists": False, "path": str(signal_path)},
                "warnings": [],
                "summary": _hit_summary_rows([]),
                "by_market": _group_hit_rows([], "market"),
                "by_horizon": _group_hit_rows([], "horizon"),
                "by_klass": _group_hit_rows([], "klass"),
                "by_stat": _group_hit_rows([], "stat"),
                "by_tag": _group_hit_tags([]),
            }
        )

    return {
        "ok": True,
        "version": "live-lens-accuracy-v1",
        "artifacts_dir": {
            "path": str(artifact_root),
            "env_configured": False,
            "running_on_render": False,
            "warnings": [],
        },
        "window": {"since": date_list[0], "until": date_list[-1]},
        "days": days,
        "summary": {
            "available": False,
            "summary": _hit_summary_rows([]),
            "by_market": _group_hit_rows([], "market"),
            "by_horizon": _group_hit_rows([], "horizon"),
            "by_klass": _group_hit_rows([], "klass"),
            "by_stat": _group_hit_rows([], "stat"),
            "by_tag": _group_hit_tags([]),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def _projection_latest(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], tuple[int, dict[str, Any]]] = {}
    for idx, row in enumerate(rows):
        if str(row.get("market") or "").strip().lower() != "player_prop":
            continue
        gid = _canon_gid10(row.get("game_id_canon") or row.get("game_id"))
        name_key = _norm_player_name(str(row.get("name_key") or row.get("player") or ""))
        stat_key = _stat_key(row.get("stat"))
        if not gid or not name_key or not stat_key:
            continue
        key = (gid, name_key, stat_key)
        current = grouped.get(key)
        if current is None or _signal_ts(row, idx) < _signal_ts(current[1], current[0]):
            grouped[key] = (idx, row)
    return [row for _, row in sorted(grouped.values(), key=lambda item: item[0])]


def _projection_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "mae_proj": None,
            "mae_raw": None,
            "mae_adjusted": None,
            "rmse_proj": None,
            "rmse_raw": None,
            "rmse_adjusted": None,
            "adjusted_beats_raw_rate": None,
            "proj_beats_adjusted_rate": None,
            "mean_adjustment": None,
            "mean_team_ratio": None,
            "mean_game_ratio": None,
        }
    def _values(key: str) -> list[float]:
        return [float(row[key]) for row in rows if _safe_float(row.get(key)) is not None]
    def _abs_mean(key: str) -> float | None:
        values = [abs(value) for value in _values(key)]
        return (sum(values) / len(values)) if values else None
    def _rmse(key: str) -> float | None:
        values = _values(key)
        return ((sum(value * value for value in values) / len(values)) ** 0.5) if values else None
    def _mean(key: str) -> float | None:
        values = _values(key)
        return (sum(values) / len(values)) if values else None
    return {
        "n": len(rows),
        "mae_proj": _abs_mean("err_proj"),
        "mae_raw": _abs_mean("err_raw"),
        "mae_adjusted": _abs_mean("err_adjusted"),
        "rmse_proj": _rmse("err_proj"),
        "rmse_raw": _rmse("err_raw"),
        "rmse_adjusted": _rmse("err_adjusted"),
        "adjusted_beats_raw_rate": _mean("adjusted_beats_raw"),
        "proj_beats_adjusted_rate": _mean("proj_beats_adjusted"),
        "mean_adjustment": _mean("adjustment_delta"),
        "mean_team_ratio": _mean("pregame_team_total_ratio"),
        "mean_game_ratio": _mean("pregame_game_total_ratio"),
    }


def _projection_rows_by_key(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = str(row.get(key) or "unknown")
        grouped.setdefault(label, []).append(row)
    items = [{key: label, **_projection_summary(group_rows)} for label, group_rows in grouped.items()]
    items.sort(key=lambda row: (-(row.get("n") or 0), str(row.get(key) or "")))
    return items


def build_local_projection_audit_payload(query_string: str, artifact_root: Path) -> dict[str, Any] | None:
    params = parse_qs(query_string or "", keep_blank_values=True)
    date_list = _parse_window(params, default_days=14, allow_date_single=True)
    if not date_list:
        return None
    include_rows = str((params.get("include_rows") or [""])[0]).strip().lower() in {"1", "true", "yes"}
    try:
        max_rows = max(100, min(20000, int(float(str((params.get("max_rows") or ["1000"])[0]).strip()))))
    except Exception:
        max_rows = 1000

    any_projection_files = False
    all_rows: list[dict[str, Any]] = []
    per_day: list[dict[str, Any]] = []
    debug_days: list[dict[str, Any]] = []
    for date_str in date_list:
        projection_path = _artifact_path(artifact_root, f"live_lens_projections_{date_str}.jsonl")
        raw_rows = _read_jsonl(projection_path)
        if raw_rows:
            any_projection_files = True
        latest_rows = _projection_latest(raw_rows)
        indexes = _load_recon_indexes(artifact_root, date_str)
        audit_rows: list[dict[str, Any]] = []
        for row in latest_rows:
            gid = _canon_gid10(row.get("game_id_canon") or row.get("game_id"))
            player = str(row.get("player") or "").strip() or None
            name_key = _norm_player_name(str(row.get("name_key") or player or ""))
            stat_key = _stat_key(row.get("stat"))
            actual = _actual_prop(indexes, gid, name_key, stat_key)
            if actual is None:
                continue
            proj = _number(row.get("proj"))
            sim_raw = _number(row.get("sim_mu"))
            sim_adjusted = _number(row.get("sim_mu_adjusted"))
            if proj is None and sim_raw is None and sim_adjusted is None:
                continue
            context = row.get("context") if isinstance(row.get("context"), dict) else {}
            entry: dict[str, Any] = {
                "date": date_str,
                "game_id": gid,
                "event_id": row.get("event_id"),
                "home": row.get("home"),
                "away": row.get("away"),
                "player": player,
                "name_key": name_key,
                "team_tri": row.get("team_tri"),
                "stat": stat_key,
                "line": _number(row.get("line")),
                "actual": _number(actual),
                "proj": proj,
                "proj_original": _number(row.get("proj_original")),
                "sim_mu": sim_raw,
                "sim_mu_adjusted": sim_adjusted,
                "sim_mu_adjusted_original": _number(row.get("sim_mu_adjusted_original")),
                "elapsed": _number(row.get("elapsed")),
                "strength": _number(row.get("strength")),
                "pregame_team_total_ratio": _number(context.get("pregame_team_total_ratio")),
                "pregame_game_total_ratio": _number(context.get("pregame_game_total_ratio")),
                "pregame_margin_blended": _number(context.get("pregame_margin_blended")),
                "pregame_stat_multiplier": _number(context.get("pregame_stat_multiplier")),
                "pregame_stat_multiplier_original": _number(context.get("pregame_stat_multiplier_original")),
                "sim_vs_line": _number(context.get("sim_vs_line")),
                "sim_vs_line_adjusted": _number(context.get("sim_vs_line_adjusted")),
            }
            actual_num = _number(actual)
            if actual_num is not None and proj is not None:
                entry["err_proj"] = float(proj) - float(actual_num)
            if actual_num is not None and sim_raw is not None:
                entry["err_raw"] = float(sim_raw) - float(actual_num)
            if actual_num is not None and sim_adjusted is not None:
                entry["err_adjusted"] = float(sim_adjusted) - float(actual_num)
            if sim_raw is not None and sim_adjusted is not None:
                entry["adjustment_delta"] = float(sim_adjusted) - float(sim_raw)
            if entry.get("err_adjusted") is not None and entry.get("err_raw") is not None:
                entry["adjusted_beats_raw"] = 1.0 if abs(float(entry["err_adjusted"])) < abs(float(entry["err_raw"])) else 0.0
            if entry.get("err_proj") is not None and entry.get("err_adjusted") is not None:
                entry["proj_beats_adjusted"] = 1.0 if abs(float(entry["err_proj"])) < abs(float(entry["err_adjusted"])) else 0.0
            elapsed = _number(entry.get("elapsed"))
            if elapsed is None:
                entry["elapsed_bucket"] = "unknown"
            elif elapsed < 12:
                entry["elapsed_bucket"] = "Q1"
            elif elapsed < 24:
                entry["elapsed_bucket"] = "Q2"
            elif elapsed < 36:
                entry["elapsed_bucket"] = "Q3"
            else:
                entry["elapsed_bucket"] = "Q4+"
            team_ratio = _number(entry.get("pregame_team_total_ratio"))
            if team_ratio is None:
                entry["team_ratio_bucket"] = "unknown"
            elif team_ratio < 0.97:
                entry["team_ratio_bucket"] = "downshift"
            elif team_ratio > 1.03:
                entry["team_ratio_bucket"] = "upshift"
            else:
                entry["team_ratio_bucket"] = "flat"
            audit_rows.append(entry)

        all_rows.extend(audit_rows)
        per_day.append({"date": date_str, "summary": _projection_summary(audit_rows)})
        debug_days.append({"date": date_str, "projection_path": str(projection_path), "raw_rows": len(raw_rows), "latest_rows": len(latest_rows), "settled_rows": len(audit_rows)})

    if not any_projection_files:
        return None

    history = None
    if include_rows and all_rows:
        history_rows = sorted(all_rows, key=lambda row: (str(row.get("date") or ""), _safe_float(row.get("elapsed")) or 0.0, str(row.get("player") or ""), str(row.get("stat") or "")), reverse=True)[:max_rows]
        history = {"rows": history_rows}

    payload: dict[str, Any] = {
        "ok": True,
        "status": "ok" if all_rows else "empty",
        "meta": {"start": date_list[0], "end": date_list[-1], "days": len(date_list), "include_rows": include_rows, "max_rows": max_rows, "source": "local_mirror"},
        "overall": _projection_summary(all_rows),
        "by_stat": _projection_rows_by_key(all_rows, "stat"),
        "by_elapsed_bucket": _projection_rows_by_key(all_rows, "elapsed_bucket"),
        "by_team_ratio_bucket": _projection_rows_by_key(all_rows, "team_ratio_bucket"),
        "per_day": per_day,
        "history": history,
        "debug": {"days": debug_days},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    if payload["status"] == "empty":
        payload["message"] = "No settled live player-prop projection rows were available for the requested window."
    return payload


def build_empty_projection_audit_payload(query_string: str, artifact_root: Path) -> dict[str, Any] | None:
    params = parse_qs(query_string or "", keep_blank_values=True)
    date_list = _parse_window(params, default_days=14, allow_date_single=True)
    if not date_list:
        return None
    include_rows = str((params.get("include_rows") or [""])[0]).strip().lower() in {"1", "true", "yes"}
    try:
        max_rows = max(100, min(20000, int(float(str((params.get("max_rows") or ["1000"])[0]).strip()))))
    except Exception:
        max_rows = 1000

    per_day = []
    debug_days = []
    for date_str in date_list:
        projection_path = _artifact_path(artifact_root, f"live_lens_projections_{date_str}.jsonl")
        per_day.append({"date": date_str, "summary": _projection_summary([])})
        debug_days.append({"date": date_str, "projection_path": str(projection_path), "raw_rows": 0, "latest_rows": 0, "settled_rows": 0})

    payload: dict[str, Any] = {
        "ok": True,
        "status": "empty",
        "meta": {"start": date_list[0], "end": date_list[-1], "days": len(date_list), "include_rows": include_rows, "max_rows": max_rows, "source": "local_mirror"},
        "overall": _projection_summary([]),
        "by_stat": [],
        "by_elapsed_bucket": [],
        "by_team_ratio_bucket": [],
        "per_day": per_day,
        "history": None,
        "debug": {"days": debug_days},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "message": "No settled live player-prop projection rows were available for the requested window.",
    }
    return payload