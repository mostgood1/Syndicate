from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _to_float(value: Any) -> float | None:
    try:
        text = str(value or "").strip()
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def _to_bool(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y"}


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lower = text.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    try:
        if "." in text or "e" in lower:
            return float(text)
        return int(text)
    except Exception:
        return text


def _format_spread(team: str, line: float | None) -> str:
    if line is None:
        return team
    return f"{team} {line:+.1f}"


def _american_to_probability(price: float | None) -> float | None:
    if price is None or price == 0:
        return None
    if price > 0:
        return 100.0 / (price + 100.0)
    return abs(price) / (abs(price) + 100.0)


def _price_or_default(value: float | None, default: float = -110.0) -> float:
    return value if value is not None else default


def _confidence_from_edge(edge: float | None, scale: float = 10.0) -> float:
    magnitude = abs(edge or 0.0)
    return max(0.5, min(0.95, 0.5 + (magnitude / scale) * 0.2))


def _priority_from_edge(edge: float | None, base: float = 55.0) -> float:
    return round(base + min(abs(edge or 0.0) * 6.0, 40.0), 1)


def _moneyline_probability_from_margin(pred_margin: float | None) -> float | None:
    if pred_margin is None:
        return None
    return 1.0 / (1.0 + math.exp(-pred_margin / 6.5))


def _latest_rows_by_key(rows: list[dict[str, str]], key: str, ts_key: str = "ts") -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for row in rows:
        item_key = str(row.get(key) or "").strip()
        if not item_key:
            continue
        if item_key not in latest:
            latest[item_key] = row
            continue
        current_ts = str(latest[item_key].get(ts_key) or "").strip()
        next_ts = str(row.get(ts_key) or "").strip()
        if next_ts >= current_ts:
            latest[item_key] = row
    return latest


def _truthy_number(value: Any) -> float | None:
    number = _to_float(value)
    if number is None:
        return None
    return number


def _ats_result(home_score: float | None, away_score: float | None, spread_home: float | None) -> str | None:
    if home_score is None or away_score is None or spread_home is None:
        return None
    result = (home_score + spread_home) - away_score
    if result > 0:
        return "Home Cover"
    if result < 0:
        return "Away Cover"
    return "Push"


def _ou_result(actual_total: float | None, market_total: float | None) -> str | None:
    if actual_total is None or market_total is None:
        return None
    if actual_total > market_total:
        return "Over"
    if actual_total < market_total:
        return "Under"
    return "Push"


def _pred_ats(pred_margin: float | None, spread_home: float | None) -> str | None:
    if pred_margin is None or spread_home is None:
        return None
    edge = pred_margin + spread_home
    if edge > 0:
        return "Home Cover"
    if edge < 0:
        return "Away Cover"
    return "Push"


def _pred_ou(pred_total: float | None, market_total: float | None) -> str | None:
    if pred_total is None or market_total is None:
        return None
    if pred_total > market_total:
        return "Over"
    if pred_total < market_total:
        return "Under"
    return "Push"


def _market_lookup(raw_root: Path, selected_date: str) -> dict[tuple[str, str], dict[str, str]]:
    by_game_market: dict[tuple[str, str], dict[str, str]] = {}
    games_with_odds_path = raw_root / "by_date" / selected_date / f"games_with_odds_{selected_date}.csv"
    for row in _read_csv_rows(games_with_odds_path):
        game_id = str(row.get("game_id") or "").strip()
        market = str(row.get("market") or "").strip().lower()
        if not game_id or not market:
            continue
        by_game_market.setdefault((game_id, market), row)
    return by_game_market


def _base_row(prediction: dict[str, str], *, book: str | None = None) -> dict[str, Any]:
    away_team = str(prediction.get("away_team") or "Away").strip() or "Away"
    home_team = str(prediction.get("home_team") or "Home").strip() or "Home"
    display_date = str(prediction.get("display_date") or prediction.get("date") or "").strip()
    display_time = str(prediction.get("display_time_str") or prediction.get("start_time_display") or "TBD").strip() or "TBD"
    return {
        "game_id": str(prediction.get("game_id") or "").strip(),
        "date": display_date or str(prediction.get("date") or "").strip() or None,
        "display_date": display_date,
        "display_time_str": display_time,
        "display_time_ampm": str(prediction.get("display_time_ampm") or "").strip() or None,
        "start_time": str(prediction.get("start_time") or "").strip() or None,
        "start_time_display": str(prediction.get("start_time_display") or display_time).strip() or display_time,
        "start_time_iso": str(prediction.get("start_time_iso") or "").strip() or None,
        "start_time_local": str(prediction.get("start_time_local") or "").strip() or None,
        "start_tz_abbr": str(prediction.get("start_tz_abbr") or "").strip() or None,
        "away_team": away_team,
        "home_team": home_team,
        "away_logo": str(prediction.get("away_logo") or "").strip() or None,
        "home_logo": str(prediction.get("home_logo") or "").strip() or None,
        "away_color": str(prediction.get("away_color") or "").strip() or None,
        "home_color": str(prediction.get("home_color") or "").strip() or None,
        "away_text_color": str(prediction.get("away_text_color") or "").strip() or None,
        "home_text_color": str(prediction.get("home_text_color") or "").strip() or None,
        "book": book or "Mirror model",
        "basketball_source": f"raw_outputs/by_date/{display_date or 'unknown'}",
        "basketball_matchup_score": round(abs(_to_float(prediction.get("edge_ats")) or _to_float(prediction.get("edge_total")) or 0.0), 2),
        "basketball_priority_score": 100.0,
    }


def build_recommendations_payload_from_raw(raw_root: Path, selected_date: str) -> dict[str, Any] | None:
    prediction_path = raw_root / "by_date" / selected_date / f"predictions_unified_enriched_{selected_date}.csv"
    if not prediction_path.exists():
        prediction_path = raw_root / "by_date" / selected_date / f"predictions_display_{selected_date}.csv"
    prediction_rows = _read_csv_rows(prediction_path)
    if not prediction_rows:
        return None

    lookup = _market_lookup(raw_root, selected_date)
    out_rows: list[dict[str, Any]] = []

    for prediction in prediction_rows:
        game_id = str(prediction.get("game_id") or "").strip()
        if not game_id:
            continue

        away_team = str(prediction.get("away_team") or "Away").strip() or "Away"
        home_team = str(prediction.get("home_team") or "Home").strip() or "Home"
        pred_margin = _to_float(prediction.get("pred_margin"))
        pred_total = _to_float(prediction.get("pred_total"))
        market_total = _to_float(prediction.get("market_total") or prediction.get("closing_total"))
        spread_home = _to_float(prediction.get("spread_home") or prediction.get("closing_spread_home"))
        ml_home = _to_float(prediction.get("ml_home") or prediction.get("closing_ml_home"))
        ml_away = _to_float(prediction.get("ml_away"))

        spread_market = lookup.get((game_id, "spreads"), {})
        totals_market = lookup.get((game_id, "totals"), {})
        ml_market = lookup.get((game_id, "h2h"), {})

        if pred_margin is not None and spread_home is not None:
            ats_edge = pred_margin + spread_home
            home_line = _to_float(spread_market.get("home_spread"))
            away_line = _to_float(spread_market.get("away_spread"))
            if ats_edge >= 0:
                selection = home_team
                line_value = home_line if home_line is not None else spread_home
                price = _price_or_default(_to_float(spread_market.get("home_spread_price")))
            else:
                selection = away_team
                fallback_away_line = abs(spread_home) if spread_home is not None else None
                line_value = away_line if away_line is not None else fallback_away_line
                price = _price_or_default(_to_float(spread_market.get("away_spread_price")))
            summary = f"Model margin is {pred_margin:.1f} against a market spread of {spread_home:.1f}, creating a {abs(ats_edge):.1f}-point ATS edge."
            out_rows.append(
                {
                    **_base_row(prediction, book=str(spread_market.get("book") or "Mirror model").strip() or "Mirror model"),
                    "abs_edge": round(abs(ats_edge), 6),
                    "edge": round(abs(ats_edge), 6),
                    "bet": _format_spread(selection, line_value),
                    "bet_label": _format_spread(selection, line_value),
                    "code": "ATS",
                    "confidence": _confidence_from_edge(ats_edge),
                    "line": line_value,
                    "line_value": line_value,
                    "market": "spreads",
                    "period": "full_game",
                    "pick": _format_spread(selection, line_value),
                    "pred_margin": pred_margin,
                    "predicted_value": pred_margin,
                    "price": price,
                    "rec_code": "ATS",
                    "rec_type": "Spread",
                    "recommendation_priority_score": _priority_from_edge(ats_edge, base=60.0),
                    "selection": selection,
                    "sim_support_score": round(min(abs(ats_edge) * 8.0, 100.0), 1),
                    "basketball_reasons": [summary],
                    "basketball_summary": summary,
                    "type": "ATS",
                    "type_label": "Spread",
                    "value_support_score": round(min(abs(ats_edge) * 10.0, 100.0), 1),
                }
            )

        if pred_total is not None and market_total is not None:
            total_edge = pred_total - market_total
            selection = "Over" if total_edge > 0 else "Under"
            price = _price_or_default(
                _to_float(totals_market.get("over_price" if selection == "Over" else "under_price"))
            )
            summary = f"Model total is {pred_total:.1f} against a market total of {market_total:.1f}, creating a {abs(total_edge):.1f}-point totals edge."
            out_rows.append(
                {
                    **_base_row(prediction, book=str(totals_market.get("book") or "Mirror model").strip() or "Mirror model"),
                    "abs_edge": round(abs(total_edge), 6),
                    "edge": round(abs(total_edge), 6),
                    "bet": f"{selection} {market_total:.1f}",
                    "bet_label": f"{selection} {market_total:.1f}",
                    "code": "OU",
                    "confidence": _confidence_from_edge(total_edge),
                    "line": market_total,
                    "line_value": market_total,
                    "market": "totals",
                    "market_total": market_total,
                    "period": "full_game",
                    "pick": f"{selection} {market_total:.1f}",
                    "pred_margin": pred_margin,
                    "pred_total": pred_total,
                    "price": price,
                    "rec_code": "OU",
                    "rec_type": "Totals",
                    "recommendation_priority_score": _priority_from_edge(total_edge, base=50.0),
                    "selection": selection,
                    "sim_support_score": round(min(abs(total_edge) * 8.0, 100.0), 1),
                    "basketball_reasons": [summary],
                    "basketball_summary": summary,
                    "type": "OU",
                    "type_label": "Totals",
                    "value_support_score": round(min(abs(total_edge) * 10.0, 100.0), 1),
                }
            )

        model_home_win = _moneyline_probability_from_margin(pred_margin)
        implied_home = _american_to_probability(_to_float(ml_market.get("moneyline_home")) or ml_home)
        implied_away = _american_to_probability(_to_float(ml_market.get("moneyline_away")) or ml_away)
        if model_home_win is not None and implied_home is not None and implied_away is not None:
            home_edge = model_home_win - implied_home
            away_edge = (1.0 - model_home_win) - implied_away
            if abs(home_edge) >= abs(away_edge):
                selection = home_team if home_edge >= 0 else away_team
                chosen_edge = home_edge if home_edge >= 0 else away_edge
                price = _to_float(ml_market.get("moneyline_home")) or ml_home if selection == home_team else _to_float(ml_market.get("moneyline_away")) or ml_away
            else:
                selection = away_team if away_edge >= 0 else home_team
                chosen_edge = away_edge if away_edge >= 0 else home_edge
                price = _to_float(ml_market.get("moneyline_away")) or ml_away if selection == away_team else _to_float(ml_market.get("moneyline_home")) or ml_home
            summary = f"Model moneyline lean favors {selection} with an implied edge of {abs(chosen_edge) * 100:.1f} percentage points."
            out_rows.append(
                {
                    **_base_row(prediction, book=str(ml_market.get("book") or "Mirror model").strip() or "Mirror model"),
                    "abs_edge": round(abs(chosen_edge), 6),
                    "edge": round(abs(chosen_edge), 6),
                    "bet": f"{selection} ML",
                    "bet_label": f"{selection} ML",
                    "code": "ML",
                    "confidence": max(model_home_win, 1.0 - model_home_win),
                    "line": None,
                    "line_value": None,
                    "market": "h2h",
                    "period": "full_game",
                    "pick": f"{selection} ML",
                    "pred_margin": pred_margin,
                    "pred_total": pred_total,
                    "price": price,
                    "prob": model_home_win if selection == home_team else 1.0 - model_home_win,
                    "rec_code": "ML",
                    "rec_type": "Moneyline",
                    "recommendation_priority_score": _priority_from_edge(chosen_edge, base=45.0),
                    "selection": selection,
                    "sim_support_score": round(min(abs(chosen_edge) * 200.0, 100.0), 1),
                    "basketball_reasons": [summary],
                    "basketball_summary": summary,
                    "type": "ML",
                    "type_label": "Moneyline",
                    "value_support_score": round(min(abs(chosen_edge) * 240.0, 100.0), 1),
                }
            )

    out_rows.sort(
        key=lambda row: (
            _to_float(row.get("recommendation_priority_score")) or 0.0,
            _to_float(row.get("abs_edge")) or 0.0,
        ),
        reverse=True,
    )
    cleaned_rows = [{key: _clean_value(value) for key, value in row.items()} for row in out_rows]
    return {
        "status": "ok",
        "date": selected_date,
        "rows": len(cleaned_rows),
        "data": cleaned_rows,
        "source": "local_raw_outputs",
    }


def build_results_payload_from_raw(raw_root: Path, selected_date: str) -> dict[str, Any] | None:
    live_features_path = raw_root / "by_date" / selected_date / f"live_features_{selected_date}.csv"
    prediction_path = raw_root / "by_date" / selected_date / f"predictions_{selected_date}.csv"
    metadata_path = raw_root / "by_date" / selected_date / f"predictions_unified_enriched_{selected_date}.csv"
    if not metadata_path.exists():
        metadata_path = raw_root / "by_date" / selected_date / f"predictions_display_{selected_date}.csv"

    live_rows = _read_csv_rows(live_features_path)
    prediction_rows = _read_csv_rows(prediction_path)
    metadata_rows = _read_csv_rows(metadata_path)
    if not live_rows or not prediction_rows:
        return None

    latest_live = _latest_rows_by_key(live_rows, "game_id")
    prediction_by_game = {
        str(row.get("game_id") or "").strip(): row
        for row in prediction_rows
        if str(row.get("game_id") or "").strip()
    }
    metadata_by_game = {
        str(row.get("game_id") or "").strip(): row
        for row in metadata_rows
        if str(row.get("game_id") or "").strip()
    }

    rows: list[dict[str, Any]] = []
    for game_id, live_row in latest_live.items():
        prediction = prediction_by_game.get(game_id)
        if not prediction:
            continue
        metadata = metadata_by_game.get(game_id, prediction)

        home_score = _truthy_number(live_row.get("home_score"))
        away_score = _truthy_number(live_row.get("away_score"))
        actual_total = _truthy_number(live_row.get("actual_total"))
        if actual_total is None and home_score is not None and away_score is not None:
            actual_total = home_score + away_score
        if home_score is None or away_score is None or actual_total is None or actual_total <= 0:
            continue

        pred_total = _to_float(prediction.get("pred_total"))
        pred_margin = _to_float(prediction.get("pred_margin"))
        market_total = _to_float(metadata.get("market_total") or metadata.get("closing_total"))
        spread_home = _to_float(metadata.get("spread_home") or metadata.get("closing_spread_home"))

        actual_ats = _ats_result(home_score, away_score, spread_home)
        actual_ou = _ou_result(actual_total, market_total)
        predicted_ats = _pred_ats(pred_margin, spread_home)
        predicted_ou = _pred_ou(pred_total, market_total)

        row = {
            "game_id": game_id,
            "date": str(metadata.get("display_date") or metadata.get("date") or selected_date).strip() or selected_date,
            "away_team": str(metadata.get("away_team") or prediction.get("away_team") or "Away").strip() or "Away",
            "home_team": str(metadata.get("home_team") or prediction.get("home_team") or "Home").strip() or "Home",
            "away_logo": _clean_value(metadata.get("away_logo")),
            "home_logo": _clean_value(metadata.get("home_logo")),
            "away_color": _clean_value(metadata.get("away_color")),
            "away_text": _clean_value(metadata.get("away_text_color")),
            "home_text": _clean_value(metadata.get("home_text_color")),
            "away_score": home_score is not None and away_score,
            "home_score": home_score,
            "actual_total": actual_total,
            "actual_margin": home_score - away_score,
            "market_total": market_total,
            "spread_home": spread_home,
            "pred_total": pred_total,
            "pred_margin": pred_margin,
            "actual_ats": actual_ats,
            "ats_result": actual_ats,
            "actual_ou": actual_ou,
            "ou_result_full": actual_ou,
            "pred_ats": predicted_ats,
            "pred_ou": predicted_ou,
            "ats_correct": predicted_ats == actual_ats if predicted_ats and actual_ats else None,
            "ou_correct": predicted_ou == actual_ou if predicted_ou and actual_ou else None,
        }
        rows.append({key: _clean_value(value) for key, value in row.items()})

    if not rows:
        return None

    ats_total = sum(1 for row in rows if row.get("ats_correct") is not None)
    ats_correct = sum(1 for row in rows if row.get("ats_correct") is True)
    totals_total = sum(1 for row in rows if row.get("ou_correct") is not None)
    totals_correct = sum(1 for row in rows if row.get("ou_correct") is True)
    summary = {
        "ats_correct": ats_correct,
        "ats_total": ats_total,
        "ats_accuracy": round((ats_correct / ats_total) * 100.0, 1) if ats_total else 0.0,
        "totals_correct": totals_correct,
        "totals_total": totals_total,
        "totals_accuracy": round((totals_correct / totals_total) * 100.0, 1) if totals_total else 0.0,
    }
    return {
        "date": selected_date,
        "count": len(rows),
        "rows": rows,
        "summary": summary,
        "source": "local_raw_outputs",
    }


def build_live_state_payload_from_raw(raw_root: Path, selected_date: str) -> dict[str, Any] | None:
    live_features_path = raw_root / "by_date" / selected_date / f"live_features_{selected_date}.csv"
    prediction_path = raw_root / "by_date" / selected_date / f"predictions_unified_enriched_{selected_date}.csv"
    if not prediction_path.exists():
        prediction_path = raw_root / "by_date" / selected_date / f"predictions_display_{selected_date}.csv"

    live_rows = _read_csv_rows(live_features_path)
    prediction_rows = _read_csv_rows(prediction_path)
    if not live_rows:
        return None

    latest_live = _latest_rows_by_key(live_rows, "game_id")
    latest_first_half: dict[str, dict[str, str]] = {}
    for row in live_rows:
        if str(row.get("period") or "").strip() != "1":
            continue
        game_id = str(row.get("game_id") or "").strip()
        if not game_id:
            continue
        current = latest_first_half.get(game_id)
        next_ts = str(row.get("ts") or "").strip()
        if current is None or next_ts >= str(current.get("ts") or "").strip():
            latest_first_half[game_id] = row

    prediction_by_game = {
        str(row.get("game_id") or "").strip(): row
        for row in prediction_rows
        if str(row.get("game_id") or "").strip()
    }

    games: dict[str, dict[str, Any]] = {}
    for game_id, live_row in latest_live.items():
        prediction = prediction_by_game.get(game_id, {})
        first_half = latest_first_half.get(game_id, {})
        away_score = _truthy_number(live_row.get("away_score"))
        home_score = _truthy_number(live_row.get("home_score"))
        total_points = _truthy_number(live_row.get("total_points"))
        remaining_min = _truthy_number(live_row.get("remaining_min"))
        period = _to_float(live_row.get("period"))
        is_final = bool(total_points and total_points > 0 and remaining_min is None and (_to_float(live_row.get("actual_total")) or total_points) == total_points)
        is_live = bool(not is_final and remaining_min is not None)
        state = "post" if is_final else ("live" if is_live else "pre")
        display_clock = "0:00" if is_final else (_clean_value(live_row.get("display_clock")) or "")
        games[game_id] = {
            "game_id": game_id,
            "event_id": game_id,
            "espn_event_id": game_id,
            "away_team": str(prediction.get("away_team") or "Away").strip() or "Away",
            "away_team_short": (str(prediction.get("away_team") or "Away").split() or ["Away"])[0],
            "home_team": str(prediction.get("home_team") or "Home").strip() or "Home",
            "home_team_short": (str(prediction.get("home_team") or "Home").split() or ["Home"])[0],
            "away_score": _clean_value(away_score),
            "home_score": _clean_value(home_score),
            "away_score_1h": _clean_value(_truthy_number(first_half.get("away_score"))),
            "home_score_1h": _clean_value(_truthy_number(first_half.get("home_score"))),
            "total_points": _clean_value(total_points),
            "total_points_1h": _clean_value(_truthy_number(first_half.get("total_points"))),
            "clock_seconds": 0 if is_final else None,
            "display_clock": display_clock,
            "period": int(period) if period is not None else None,
            "remaining_1h_seconds": int(round((_truthy_number(first_half.get("remaining_min")) or 0.0) * 60.0)) if first_half and _truthy_number(first_half.get("remaining_min")) is not None else None,
            "remaining_reg_seconds": int(round(remaining_min * 60.0)) if remaining_min is not None else None,
            "is_final": is_final,
            "is_live": is_live,
            "state": state,
        }

    if not games:
        return None
    return {
        "status": "ok",
        "date": selected_date,
        "count": len(games),
        "games": games,
        "refresh": False,
        "ttl": 0,
        "source": "local_raw_outputs",
    }


def build_live_lines_payload_from_raw(raw_root: Path, selected_date: str) -> dict[str, Any] | None:
    live_features_path = raw_root / "by_date" / selected_date / f"live_features_{selected_date}.csv"
    prediction_path = raw_root / "by_date" / selected_date / f"predictions_unified_enriched_{selected_date}.csv"
    if not prediction_path.exists():
        prediction_path = raw_root / "by_date" / selected_date / f"predictions_display_{selected_date}.csv"

    live_rows = _read_csv_rows(live_features_path)
    prediction_rows = _read_csv_rows(prediction_path)
    prediction_by_game = {
        str(row.get("game_id") or "").strip(): row
        for row in prediction_rows
        if str(row.get("game_id") or "").strip()
    }

    latest_features = _latest_rows_by_key(live_rows, "game_id")
    lines: dict[str, dict[str, Any]] = {}
    for event_id, feature_row in latest_features.items():
        prediction = prediction_by_game.get(event_id, {})
        total = _to_float(feature_row.get("live_line_total"))
        book = _clean_value(feature_row.get("live_line_book"))
        provider_event_id = _clean_value(feature_row.get("live_line_provider_event_id"))
        last_update = _clean_value(feature_row.get("live_line_last_update"))
        if total is None and not book and not provider_event_id and not last_update:
            continue
        lines[event_id] = {
            "event_id": event_id,
            "book": book,
            "provider_event_id": provider_event_id,
            "last_update": last_update,
            "total": _clean_value(total),
            "spread_home": _clean_value(prediction.get("spread_home") or prediction.get("closing_spread_home")),
            "spread_away": _clean_value(-_to_float(prediction.get("spread_home") or prediction.get("closing_spread_home"))) if _to_float(prediction.get("spread_home") or prediction.get("closing_spread_home")) is not None else None,
        }

    bookmakers = sorted(
        {
            str((row.get("live_line_book") or "")).strip().lower()
            for row in live_rows
            if str((row.get("live_line_book") or "")).strip()
        }
    )
    return {
        "status": "ok",
        "date": selected_date,
        "count": len(lines),
        "lines": lines,
        "bookmakers": ",".join(bookmakers),
        "source": "local_raw_outputs",
    }


def _dates_from_recommendation_dir(api_root: Path) -> set[str]:
    directory = api_root / "recommendations"
    if not directory.exists():
        return set()
    dates: set[str] = set()
    for candidate in directory.glob("recommendations_*.json"):
        suffix = candidate.stem.replace("recommendations_", "", 1).strip()
        if suffix:
            dates.add(suffix)
    return dates


def _dates_from_results_dir(api_root: Path) -> set[str]:
    directory = api_root / "results_by_date"
    if not directory.exists():
        return set()
    dates: set[str] = set()
    for candidate in directory.glob("results_*.json"):
        suffix = candidate.stem.replace("results_", "", 1).strip()
        if suffix:
            dates.add(suffix)
    return dates


def _dates_from_raw_dirs(raw_root: Path, filename_prefix: str) -> set[str]:
    root = raw_root / "by_date"
    if not root.exists():
        return set()
    dates: set[str] = set()
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        date_str = directory.name.strip()
        if (directory / f"{filename_prefix}_{date_str}.csv").exists() or (directory / f"{filename_prefix}_{date_str}.json").exists():
            dates.add(date_str)
    return dates


def export_api_bundle_from_raw(api_root: Path, raw_root: Path, selected_date: str) -> dict[str, Any]:
    api_root.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []

    existing_display_dates = set((_read_json(api_root / "display_prediction_dates.json") or {}).get("dates") or [])
    existing_schedule_dates = set((_read_json(api_root / "dates.json") or {}).get("dates") or [])
    existing_results_dates = set((_read_json(api_root / "results_dates.json") or {}).get("dates") or [])

    display_dates = sorted(
        {
            str(item).strip()
            for item in existing_display_dates | _dates_from_recommendation_dir(api_root) | _dates_from_raw_dirs(raw_root, "predictions_unified_enriched") | _dates_from_raw_dirs(raw_root, "predictions_display")
            if str(item).strip()
        }
    )
    schedule_dates = sorted(
        {
            str(item).strip()
            for item in existing_schedule_dates | _dates_from_raw_dirs(raw_root, "games") | _dates_from_raw_dirs(raw_root, "games_with_odds")
            if str(item).strip()
        }
    )
    local_results_payload = build_results_payload_from_raw(raw_root, selected_date)
    if local_results_payload is not None:
        _write_json(api_root / "results_by_date" / f"results_{selected_date}.json", local_results_payload)
        copied.append(f"api/results_by_date/results_{selected_date}.json")

    results_dates = sorted(
        {
            str(item).strip()
            for item in existing_results_dates | _dates_from_results_dir(api_root) | ({selected_date} if local_results_payload is not None else set())
            if str(item).strip()
        }
    )

    display_payload = {"dates": display_dates, "latest": display_dates[-1] if display_dates else None}
    schedule_payload = {"dates": schedule_dates, "latest": schedule_dates[-1] if schedule_dates else None}
    results_payload = {"dates": results_dates, "latest": results_dates[-1] if results_dates else None}
    _write_json(api_root / "display_prediction_dates.json", display_payload)
    _write_json(api_root / "dates.json", schedule_payload)
    _write_json(api_root / "results_dates.json", results_payload)

    config_tuning = _read_json(raw_root / "config" / "live_lens_tuning.json")
    if config_tuning is not None:
        _write_json(api_root / "live_lens_tuning.json", config_tuning)
        copied.append("api/live_lens_tuning.json")

    live_state_payload = build_live_state_payload_from_raw(raw_root, selected_date)
    if live_state_payload is not None:
        _write_json(api_root / "live_state" / f"live_state_{selected_date}.json", live_state_payload)
        copied.append(f"api/live_state/live_state_{selected_date}.json")

    live_lines_payload = build_live_lines_payload_from_raw(raw_root, selected_date)
    if live_lines_payload is not None:
        _write_json(api_root / "live_lines" / f"live_lines_{selected_date}.json", live_lines_payload)
        copied.append(f"api/live_lines/live_lines_{selected_date}.json")

    recommendations_payload = build_recommendations_payload_from_raw(raw_root, selected_date)
    if recommendations_payload is not None:
        _write_json(api_root / "recommendations" / f"recommendations_{selected_date}.json", recommendations_payload)
        copied.append(f"api/recommendations/recommendations_{selected_date}.json")

    manifest = {
        "date": selected_date,
        "display_dates": display_dates,
        "latest_display": display_payload.get("latest"),
        "results_dates": results_dates,
        "latest_results": results_payload.get("latest"),
        "copied_artifacts": copied,
        "source": "local_raw_outputs",
    }
    _write_json(api_root / "manifest.local_export.json", manifest)
    return manifest