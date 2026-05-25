from __future__ import annotations

import csv
import datetime as dt
import math
import unicodedata
from pathlib import Path


OUTPUT_COLUMNS = [
    "player",
    "team",
    "plays",
    "ladders",
    "sim_ladders",
    "model",
    "_plays_list",
    "top_play",
    "top_play_explain",
    "top_play_baseline",
    "top_play_reasons",
    "top_play_consensus",
    "top_play_line_adv",
]


def _normalize_player_name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "(" in text:
        text = text.split("(", 1)[0]
    text = text.replace("-", " ")
    text = text.replace(".", "").replace("'", "").replace(",", " ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = " ".join(text.upper().split())
    text = {
        "HERB JONES": "HERBERT JONES",
        "MOE WAGNER": "MORITZ WAGNER",
        "NIC CLAXTON": "NICOLAS CLAXTON",
    }.get(text, text)
    return text.lower()


def _safe_float(value: object) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        number = float(value)
        if math.isnan(number):
            return None
        return number
    except Exception:
        return None


def _read_csv_rows(path: Path) -> list[dict[str, object]]:
    if not path.exists() or not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in OUTPUT_COLUMNS})


def _canonical_standard_plays(plays: object) -> list[dict]:
    if not isinstance(plays, list) or not plays:
        return []
    out: list[dict] = []
    buckets: dict[tuple[str, str], list[dict]] = {}
    for play in plays:
        if not isinstance(play, dict):
            continue
        market = str(play.get("market") or "").strip().lower()
        side = str(play.get("side") or "").strip().upper()
        line = _safe_float(play.get("line"))
        if not market or not side or line is None:
            continue
        buckets.setdefault((market, side), []).append(play)

    def _score(play: dict) -> float:
        ev_pct = _safe_float(play.get("ev_pct"))
        if ev_pct is not None:
            return ev_pct
        ev = _safe_float(play.get("ev"))
        return (ev * 100.0) if ev is not None else -1e18

    for bucket in buckets.values():
        counts: dict[float, int] = {}
        for play in bucket:
            line = _safe_float(play.get("line"))
            if line is None:
                continue
            counts[line] = counts.get(line, 0) + 1
        if not counts:
            continue
        max_count = max(counts.values())
        mode_lines = sorted(line for line, count in counts.items() if count == max_count)
        chosen_line = mode_lines[len(mode_lines) // 2]
        candidates = [play for play in bucket if _safe_float(play.get("line")) == chosen_line] or list(bucket)
        candidates.sort(key=_score, reverse=True)
        out.append(dict(candidates[0]))
    out.sort(key=_score, reverse=True)
    return out


def _build_model_map(predictions_rows: list[dict[str, object]]) -> dict[tuple[str, str], dict[str, float]]:
    model_map: dict[tuple[str, str], dict[str, float]] = {}
    for row in predictions_rows:
        stats: dict[str, float] = {}
        for column_group, key in [
            (("mean_pts", "pred_pts"), "pts"),
            (("mean_reb", "pred_reb"), "reb"),
            (("mean_ast", "pred_ast"), "ast"),
            (("mean_threes", "pred_threes"), "threes"),
            (("mean_stl", "pred_stl"), "stl"),
            (("mean_blk", "pred_blk"), "blk"),
            (("mean_tov", "pred_tov"), "tov"),
            (("mean_pra", "pred_pra"), "pra"),
        ]:
            for column in column_group:
                value = _safe_float(row.get(column))
                if value is not None:
                    stats[key] = value
                    break
        pts = stats.get("pts")
        reb = stats.get("reb")
        ast_val = stats.get("ast")
        if pts is not None and reb is not None:
            stats["pr"] = pts + reb
        if pts is not None and ast_val is not None:
            stats["pa"] = pts + ast_val
        if reb is not None and ast_val is not None:
            stats["ra"] = reb + ast_val
        model_map[(_normalize_player_name(row.get("player_name")), str(row.get("team") or "").strip().upper())] = stats
    return model_map


def _is_regular_price(price: object, *, max_plus_odds: float) -> bool:
    value = _safe_float(price)
    if value is None:
        return False
    upper = 1e9 if max_plus_odds <= 0 else max_plus_odds
    return value >= -150.0 and value <= upper


def _pick_top_play(plays: list[dict], *, max_plus_odds: float) -> dict | None:
    if not plays:
        return None
    regular = [
        play
        for play in plays
        if str(play.get("market") or "").strip().lower() not in {"dd", "td"}
        and _is_regular_price(play.get("price"), max_plus_odds=max_plus_odds)
    ]
    candidates = regular if regular else plays

    def _score(play: dict) -> float:
        ev_pct = _safe_float(play.get("ev_pct"))
        if ev_pct is not None:
            return ev_pct
        ev = _safe_float(play.get("ev"))
        return (ev * 100.0) if ev is not None else -1e18

    ordered = sorted(candidates, key=_score, reverse=True)
    return dict(ordered[0]) if ordered else None


def _top_play_explain(row: dict[str, object], model_map: dict[tuple[str, str], dict[str, float]]) -> str:
    top_play = row.get("top_play")
    if not isinstance(top_play, dict) or not top_play:
        return ""
    player = _normalize_player_name(row.get("player"))
    team = str(row.get("team") or "").strip().upper()
    baseline = model_map.get((player, team), {}).get(str(top_play.get("market") or "").lower())
    line = _safe_float(top_play.get("line"))
    if baseline is None or line is None:
        return ""
    delta = baseline - line
    sign = "+" if delta >= 0 else ""
    return f"model {baseline:.1f} vs line {line:.1f} ({sign}{delta:.1f})"


def _top_play_consensus_and_reasons(row: dict[str, object], *, max_plus_odds: float) -> tuple[list[str], float, float]:
    top_play = row.get("top_play") or {}
    plays = row.get("plays") or row.get("_plays_list") or []
    if not isinstance(top_play, dict) or not isinstance(plays, list):
        return [], 0.0, 0.0

    reasons: list[str] = []
    ev_pct = _safe_float(top_play.get("ev_pct"))
    ev = _safe_float(top_play.get("ev"))
    if ev_pct is not None:
        reasons.append(f"EV {ev_pct:.1f}%")
    elif ev is not None:
        reasons.append(f"EV +{ev:.2f}")
    if _is_regular_price(top_play.get("price"), max_plus_odds=max_plus_odds):
        reasons.append("Regular price range (-150 to +150)")

    market = str(top_play.get("market") or "").strip().lower()
    side = str(top_play.get("side") or "").strip().upper()
    same_all = [
        play for play in plays
        if str(play.get("market") or "").strip().lower() == market
        and str(play.get("side") or "").strip().upper() == side
    ]
    same_regular = [play for play in same_all if _is_regular_price(play.get("price"), max_plus_odds=max_plus_odds)]
    same = same_regular if same_regular else same_all
    books = sorted({str(play.get("book") or "").strip().lower() for play in same if str(play.get("book") or "").strip()})
    books_count = len(books)
    if books_count >= 3:
        reasons.append(f"Consensus: {books_count} books aligned")
    consensus = max(0.0, min(1.0, (books_count - 1) / 4.0))

    line_adv = 0.0
    lines = [_safe_float(play.get("line")) for play in same]
    lines = [line for line in lines if line is not None]
    top_line = _safe_float(top_play.get("line"))
    if top_line is not None and lines:
        if side == "OVER" and top_line <= min(lines) + 1e-9:
            reasons.append("Best line available")
            line_adv = 1.0
        elif side == "UNDER" and top_line >= max(lines) - 1e-9:
            reasons.append("Best line available")
            line_adv = 1.0
    return reasons, consensus, line_adv


def export_props_recommendations_local(
    *,
    processed_root: Path,
    date_str: str,
    max_plus_odds: float = 125.0,
) -> tuple[int, Path]:
    dt.date.fromisoformat(date_str)

    edges_rows = _read_csv_rows(processed_root / f"props_edges_{date_str}.csv")
    predictions_rows = _read_csv_rows(processed_root / f"props_predictions_{date_str}.csv")
    out_path = processed_root / f"props_recommendations_{date_str}.csv"
    model_map = _build_model_map(predictions_rows)

    cards: list[dict[str, object]] = []
    if not edges_rows:
        seen: set[tuple[str, str]] = set()
        for row in predictions_rows:
            key = (str(row.get("player_name") or ""), str(row.get("team") or ""))
            if key in seen:
                continue
            seen.add(key)
            model = model_map.get((_normalize_player_name(key[0]), str(key[1]).strip().upper()), {})
            cards.append(
                {
                    "player": key[0],
                    "team": key[1],
                    "plays": [],
                    "ladders": [],
                    "sim_ladders": [],
                    "model": model,
                }
            )
    else:
        groups: dict[tuple[str, str], list[dict[str, object]]] = {}
        for row in edges_rows:
            groups.setdefault((str(row.get("player_name") or ""), str(row.get("team") or "")), []).append(row)

        for (player, team), group_rows in groups.items():
            plays: list[dict[str, object]] = []
            for row in group_rows:
                market = str(row.get("stat") or row.get("market") or "").strip().lower()
                side = str(row.get("side") or "").strip().upper()
                line = _safe_float(row.get("line"))
                price = _safe_float(row.get("price"))
                edge = _safe_float(row.get("edge"))
                ev = _safe_float(row.get("ev"))
                if market in {"dd", "td"} or side not in {"OVER", "UNDER"}:
                    continue
                if not _is_regular_price(price, max_plus_odds=max_plus_odds):
                    continue
                if line is None or edge is None or edge <= 0.0 or ev is None or ev <= 0.0:
                    continue
                if market in {"pts", "pra"} and abs(edge) < 0.15:
                    continue
                plays.append(
                    {
                        "market": row.get("stat") or row.get("market"),
                        "side": row.get("side"),
                        "line": line,
                        "price": price,
                        "edge": edge,
                        "ev": ev,
                        "ev_pct": ev * 100.0,
                        "book": row.get("bookmaker") or row.get("book"),
                    }
                )
            model = model_map.get((_normalize_player_name(player), str(team).strip().upper()), {})
            if plays or model:
                cards.append(
                    {
                        "player": player,
                        "team": team,
                        "plays": plays,
                        "ladders": [],
                        "sim_ladders": [],
                        "model": model,
                    }
                )

    rows: list[dict[str, object]] = []
    for card in cards:
        row = dict(card)
        row["_plays_list"] = _canonical_standard_plays(list(row.get("plays") or []))
        row["top_play"] = _pick_top_play(row["_plays_list"], max_plus_odds=max_plus_odds)
        row["top_play_explain"] = _top_play_explain(row, model_map)
        top_play = row.get("top_play")
        if isinstance(top_play, dict):
            row["top_play_baseline"] = model_map.get(
                (_normalize_player_name(row.get("player")), str(row.get("team") or "").strip().upper()),
                {},
            ).get(str(top_play.get("market") or "").lower())
        else:
            row["top_play_baseline"] = ""
        reasons, consensus, line_adv = _top_play_consensus_and_reasons(row, max_plus_odds=max_plus_odds)
        row["top_play_reasons"] = reasons
        row["top_play_consensus"] = consensus
        row["top_play_line_adv"] = line_adv
        rows.append(row)

    _write_csv_rows(out_path, rows)
    return len(rows), out_path