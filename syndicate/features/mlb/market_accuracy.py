from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs

from syndicate.features.mlb.sources import load_json_file
from syndicate.features.mlb.sources import season_betting_card_day_path


_GAME_MARKETS: tuple[tuple[str, str], ...] = (
    ("ml", "Moneyline"),
    ("totals", "Totals"),
)

_PROP_MARKETS: tuple[tuple[str, str], ...] = (
    ("pitcher_props", "Pitcher Props"),
    ("hitter_props", "Hitter Props"),
    ("hitter_hits", "Hitter Hits"),
    ("hitter_total_bases", "Hitter Total Bases"),
    ("hitter_runs", "Hitter Runs"),
    ("hitter_rbis", "Hitter RBIs"),
    ("hitter_home_runs", "Hitter Home Runs"),
    ("hitter_hits_runs_rbis", "Hitter Hits+Runs+RBIs"),
)

_PROP_OVERALL_KEYS: tuple[str, ...] = ("pitcher_props", "hitter_props")
_PROP_DETAIL_KEYS: tuple[str, ...] = tuple(key for key, _ in _PROP_MARKETS if key not in _PROP_OVERALL_KEYS)
_ROW_SETS: tuple[tuple[str, str], ...] = (
    ("settled_rows", "official"),
    ("playable_settled_rows", "playable"),
    ("all_settled_rows", "all"),
)


def _parse_ymd(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d")
    except Exception:
        return None


def _date_window(query_string: str, *, default_days: int = 30) -> tuple[str | None, str | None, list[str]]:
    params = parse_qs(query_string or "", keep_blank_values=True)
    date_value = str((params.get("date") or [""])[0]).strip()
    if date_value:
        return date_value, date_value, [date_value]

    start_value = str((params.get("since") or params.get("start") or [""])[0]).strip()
    end_value = str((params.get("until") or params.get("end") or [""])[0]).strip()
    if start_value and end_value:
        start_dt = _parse_ymd(start_value)
        end_dt = _parse_ymd(end_value)
        if start_dt is None or end_dt is None:
            return None, None, []
    else:
        try:
            days = max(1, min(120, int(float(str((params.get("days") or [str(default_days)])[0]).strip()))))
        except Exception:
            days = default_days
        end_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        start_dt = end_dt - timedelta(days=days - 1)

    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt

    dates: list[str] = []
    current = start_dt
    while current <= end_dt:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"), dates


def _init_bucket() -> dict[str, Any]:
    return {
        "bets": 0,
        "resolved": 0,
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "stake_total": 0.0,
        "profit_total": 0.0,
    }


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
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


def _result_bucket(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    bets = int(result.get("n") or 0)
    wins = int(result.get("wins") or 0)
    losses = int(result.get("losses") or 0)
    pushes = max(0, bets - wins - losses)
    return _finalize_bucket(
        {
            "bets": bets,
            "resolved": wins + losses + pushes,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "stake_total": float(result.get("stake_u") or 0.0),
            "profit_total": float(result.get("profit_u") or 0.0),
        }
    )


def _merge_bucket(target: dict[str, Any], bucket: dict[str, Any] | None) -> None:
    if not isinstance(bucket, dict):
        return
    for key in ("bets", "resolved", "wins", "losses", "pushes"):
        target[key] += int(bucket.get(key) or 0)
    for key in ("stake_total", "profit_total"):
        target[key] += float(bucket.get(key) or 0.0)


def _combine_buckets(buckets: list[dict[str, Any] | None]) -> dict[str, Any]:
    combined = _init_bucket()
    for bucket in buckets:
        _merge_bucket(combined, bucket)
    return _finalize_bucket(combined)


def _available_from_results(results: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(isinstance(results.get(key), dict) for key in keys)


def _section(results: dict[str, Any], markets: tuple[tuple[str, str], ...], *, overall_keys: tuple[str, ...] | None = None) -> dict[str, Any]:
    by_market: dict[str, dict[str, Any]] = {}
    for key, label in markets:
        bucket = _result_bucket(results.get(key))
        if bucket is not None:
            by_market[label] = bucket

    aggregate_keys = overall_keys or tuple(key for key, _ in markets)
    overall_buckets = [_result_bucket(results.get(key)) for key in aggregate_keys if isinstance(results.get(key), dict)]
    if not overall_buckets and overall_keys == _PROP_OVERALL_KEYS:
        overall_buckets = [_result_bucket(results.get(key)) for key in _PROP_DETAIL_KEYS if isinstance(results.get(key), dict)]
    available = bool(by_market) or bool(overall_buckets)
    return {
        "available": available,
        "overall": _combine_buckets(overall_buckets) if available else _finalize_bucket(_init_bucket()),
        "by_market": by_market,
    }


def _matchup(game_payload: dict[str, Any]) -> str:
    markets = game_payload.get("markets") if isinstance(game_payload.get("markets"), dict) else {}
    ml = markets.get("ml") if isinstance(markets.get("ml"), dict) else None
    totals = markets.get("totals") if isinstance(markets.get("totals"), dict) else None
    source = ml or totals or {}
    away = str(source.get("away_abbr") or source.get("away") or "AWY").strip() or "AWY"
    home = str(source.get("home_abbr") or source.get("home") or "HOM").strip() or "HOM"
    return f"{away} @ {home}"


def _row_title(row: dict[str, Any], matchup: str) -> str:
    player_name = str(row.get("player_name") or row.get("pitcher_name") or "").strip()
    selection = str(row.get("selection") or "pick").strip().title()
    line = row.get("market_line")
    market = str(row.get("market") or row.get("prop") or "bet").strip().replace("_", " ").title()
    if player_name:
        line_piece = f" {line:g}" if isinstance(line, (int, float)) else (f" {str(line).strip()}" if line not in {None, ""} else "")
        return f"{player_name} {selection}{line_piece} {market}".strip()
    return f"{matchup} {selection} {market}".strip()


def _specific_market(row: dict[str, Any]) -> str:
    """The row's market, made specific enough to canonicalise.

    Hitter rows already carry a specific market (`hitter_hits` ->
    `batter_hits`), but every pitcher row carries the generic BUCKET
    `pitcher_props` and keeps which prop it actually is in `prop`. That is
    unresolvable downstream: `canonical_market_key("mlb", "pitcher_props")`
    returns `pitcher_props`, while the ledger's own label for the same bet
    ("outs recorded") returns `outs`, so `_markets_compatible` vetoes the
    match. Measured on 2026-07-08: 64 records whose player key matched a
    graded row exactly were rejected on this alone, and it was the ONLY
    market pair failing that check.

    `pitcher_outs` and `pitcher_strikeouts` both canonicalise to the same key
    as the ledger's labels, so promoting the bucket to `pitcher_<prop>`
    closes it. `_row_title` already falls back to `prop` this way.
    """
    market = str(row.get("market") or "").strip()
    prop = str(row.get("prop") or "").strip()
    if prop and market in {"pitcher_props", "hitter_props"}:
        return f"{market.split('_')[0]}_{prop}"
    return market


def _normalized_rows(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    games = payload.get("games") if isinstance(payload.get("games"), dict) else {}
    rows_by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for _, kind in _ROW_SETS}
    for game_pk, game_payload in games.items():
        if not isinstance(game_payload, dict):
            continue
        matchup = _matchup(game_payload)
        for field_name, kind in _ROW_SETS:
            rows = game_payload.get(field_name) if isinstance(game_payload.get(field_name), list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                normalized = {
                    "game_pk": int(row.get("game_pk") or game_pk or 0) or None,
                    "matchup": matchup,
                    "market": _specific_market(row),
                    "title": _row_title(row, matchup),
                    "player_name": str(row.get("player_name") or row.get("pitcher_name") or "").strip() or None,
                    "team": str(row.get("team") or "").strip() or None,
                    "selection": str(row.get("selection") or "").strip() or None,
                    "line": row.get("market_line"),
                    "actual": row.get("actual"),
                    "odds": str(row.get("odds") or "").strip() or None,
                    "stake_u": float(row.get("stake_u") or 0.0),
                    "profit_u": float(row.get("profit_u") or 0.0),
                    "result": str(row.get("result") or "").strip().lower() or None,
                    "tier": str(row.get("recommendation_tier") or kind).strip() or kind,
                }
                rows_by_kind[kind].append(normalized)
    for kind in rows_by_kind:
        rows_by_kind[kind].sort(
            key=lambda row: (
                str(row.get("market") or ""),
                str(row.get("title") or ""),
            )
        )
    return rows_by_kind


def _day_payload(date_str: str, payload: dict[str, Any], source_path: str) -> dict[str, Any] | None:
    results = payload.get("results") if isinstance(payload.get("results"), dict) else {}
    if not results:
        return None
    games = _section(results, _GAME_MARKETS)
    props = _section(results, _PROP_MARKETS, overall_keys=_PROP_OVERALL_KEYS)
    combined_bucket = _result_bucket(results.get("combined"))
    combined = {
        "available": combined_bucket is not None or games["available"] or props["available"],
        "overall": combined_bucket if combined_bucket is not None else _combine_buckets([games.get("overall"), props.get("overall")]),
    }
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    detail_rows = _normalized_rows(payload)
    return {
        "date": date_str,
        "profile": str(payload.get("profile") or "retuned").strip() or "retuned",
        "source_path": source_path,
        "games": games,
        "props": props,
        "combined": combined,
        "rows": detail_rows,
        "selected_counts": payload.get("selected_counts") if isinstance(payload.get("selected_counts"), dict) else {},
        "warnings": summary.get("warnings") if isinstance(summary.get("warnings"), list) else [],
    }


def _summarize(days: list[dict[str, Any]]) -> dict[str, Any]:
    def combine_section(section_key: str) -> dict[str, Any]:
        overall = _init_bucket()
        by_market: dict[str, dict[str, Any]] = {}
        available = False
        for day in days:
            section = day.get(section_key) if isinstance(day.get(section_key), dict) else {}
            if section.get("available"):
                available = True
            _merge_bucket(overall, section.get("overall") if isinstance(section.get("overall"), dict) else None)
            market_rows = section.get("by_market") if isinstance(section.get("by_market"), dict) else {}
            for label, bucket in market_rows.items():
                by_market.setdefault(label, _init_bucket())
                _merge_bucket(by_market[label], bucket if isinstance(bucket, dict) else None)
        return {
            "available": available,
            "overall": _finalize_bucket(overall),
            "by_market": {label: _finalize_bucket(bucket) for label, bucket in by_market.items()},
        }

    games = combine_section("games")
    props = combine_section("props")
    combined_bucket = _init_bucket()
    combined_available = False
    for day in days:
        section = day.get("combined") if isinstance(day.get("combined"), dict) else {}
        if section.get("available"):
            combined_available = True
        _merge_bucket(combined_bucket, section.get("overall") if isinstance(section.get("overall"), dict) else None)
    return {
        "games": games,
        "props": props,
        "combined": {
            "available": combined_available,
            "overall": _finalize_bucket(combined_bucket),
        },
    }


@lru_cache(maxsize=64)
def build_market_accuracy_payload(query_string: str) -> dict[str, Any]:
    since, until, dates = _date_window(query_string, default_days=30)
    days: list[dict[str, Any]] = []
    for date_str in dates:
        season = int(date_str[:4]) if len(date_str) >= 4 and date_str[:4].isdigit() else datetime.now(timezone.utc).year
        path = season_betting_card_day_path(season, date_str, profile="retuned")
        payload = load_json_file(path)
        if not isinstance(payload, dict):
            continue
        day = _day_payload(date_str, payload, str(path))
        if day is not None:
            days.append(day)

    return {
        "ok": True,
        "status": "ok" if days else "empty",
        "version": "accuracy-market-v1",
        "source_kind": "season_betting_day_payloads",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "window": {
            "since": since,
            "until": until,
        },
        "days": days,
        "summary": _summarize(days),
    }