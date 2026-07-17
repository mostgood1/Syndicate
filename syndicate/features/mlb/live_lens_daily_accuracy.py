from __future__ import annotations

from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import lru_cache
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from syndicate.features.mlb.sources import load_json_or_gz_file
from syndicate.features.mlb.sources import live_prop_registry_path
from syndicate.features.mlb.sources import load_json_file
from syndicate.features.mlb.sources import raw_feed_live_path


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _normalize_live_name(value: Any) -> str:
    text = " ".join(str(value or "").strip().lower().split())
    normalized = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped


def _parse_iso_date(value: str | None) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_window(query_string: str, *, default_days: int = 30) -> list[str]:
    params = parse_qs(query_string or "", keep_blank_values=True)
    selected_date = _parse_iso_date((params.get("date") or [""])[0])
    if selected_date is not None:
        return [selected_date.isoformat()]

    try:
        days = int(float(str((params.get("days") or [str(default_days)])[0]).strip() or default_days))
    except Exception:
        days = default_days
    days = max(1, min(days, 60))

    until_date = _parse_iso_date((params.get("until") or [""])[0]) or date.today()
    since_date = _parse_iso_date((params.get("since") or [""])[0])
    if since_date is None:
        since_date = until_date - timedelta(days=days - 1)
    if since_date > until_date:
        since_date, until_date = until_date, since_date
    span = (until_date - since_date).days
    if span > 60:
        since_date = until_date - timedelta(days=60)

    return [(since_date + timedelta(days=offset)).isoformat() for offset in range((until_date - since_date).days + 1)]


def _settle_pick(actual: float | None, line: float | None, selection: str | None) -> str | None:
    if actual is None or line is None:
        return None
    side = str(selection or "").strip().lower()
    if side == "over":
        if actual > line:
            return "win"
        if actual < line:
            return "loss"
        return "push"
    if side == "under":
        if actual < line:
            return "win"
        if actual > line:
            return "loss"
        return "push"
    return None


def _iter_team_players(feed: dict[str, Any], side: str) -> list[dict[str, Any]]:
    box = (feed.get("liveData") or {}).get("boxscore") if isinstance(feed.get("liveData"), dict) else {}
    teams = box.get("teams") if isinstance(box, dict) else {}
    team = teams.get(side) if isinstance(teams, dict) else {}
    players = team.get("players") if isinstance(team, dict) else {}
    if not isinstance(players, dict):
        return []
    return [player for player in players.values() if isinstance(player, dict)]


def _feed_stat_indexes(
    feed: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    batting_index: dict[str, dict[str, Any]] = {}
    pitching_index: dict[str, dict[str, Any]] = {}
    batting_by_id: dict[int, dict[str, Any]] = {}
    pitching_by_id: dict[int, dict[str, Any]] = {}
    if not isinstance(feed, dict):
        return batting_index, pitching_index, batting_by_id, pitching_by_id
    for side in ("away", "home"):
        for player_obj in _iter_team_players(feed, side):
            person = player_obj.get("person") if isinstance(player_obj.get("person"), dict) else {}
            name = _normalize_live_name((person or {}).get("fullName"))
            try:
                person_id = int((person or {}).get("id") or 0)
            except (TypeError, ValueError):
                person_id = 0
            stats = player_obj.get("stats") if isinstance(player_obj.get("stats"), dict) else {}
            batting = stats.get("batting") if isinstance(stats.get("batting"), dict) else None
            pitching = stats.get("pitching") if isinstance(stats.get("pitching"), dict) else None
            if isinstance(batting, dict) and batting:
                if name:
                    batting_index[name] = batting
                if person_id > 0:
                    batting_by_id[person_id] = batting
            if isinstance(pitching, dict) and pitching:
                if name:
                    pitching_index[name] = pitching
                if person_id > 0:
                    pitching_by_id[person_id] = pitching
    return batting_index, pitching_index, batting_by_id, pitching_by_id


def _actual_from_feed(feed: dict[str, Any] | None, owner: Any, market: Any, prop: Any, *, player_id: int | None = None) -> float | None:
    batting_index, pitching_index, batting_by_id, pitching_by_id = _feed_stat_indexes(feed)
    name = _normalize_live_name(owner)
    pid = int(player_id or 0)
    market_key = str(market or "").strip().lower()
    prop_key = str(prop or "").strip().lower()
    if market_key == "pitcher_props":
        # MLBAM id match first; normalized-name only as fallback (accents,
        # suffixes, and Jr./Sr. variants silently miss on name matching).
        stats = (pitching_by_id.get(pid) if pid > 0 else None) or pitching_index.get(name) or {}
        if prop_key == "strikeouts":
            return _safe_float(stats.get("strikeOuts"))
        return None
    stats = (batting_by_id.get(pid) if pid > 0 else None) or batting_index.get(name) or {}
    stat_map = {
        "hits": "hits",
        "runs": "runs",
        "runs_scored": "runs",
        "rbi": "rbi",
        "rbis": "rbi",
        "total_bases": "totalBases",
        "home_runs": "homeRuns",
    }
    stat_key = stat_map.get(prop_key)
    if not stat_key:
        return None
    return _safe_float(stats.get(stat_key))


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(1 for row in rows if row.get("result") == "win")
    losses = sum(1 for row in rows if row.get("result") == "loss")
    pushes = sum(1 for row in rows if row.get("result") == "push")
    settled = wins + losses + pushes
    hit_rate = (wins / (wins + losses)) if (wins + losses) else None
    hit_rate_pct = (hit_rate * 100.0) if hit_rate is not None else None
    return {
        "n": settled,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "hit_rate": hit_rate,
        "hit_rate_pct": hit_rate_pct,
    }


def _group_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = str(row.get(key) or "unknown").strip() or "unknown"
        grouped.setdefault(label, []).append(row)
    items = [{"key": label, **_summary(group_rows)} for label, group_rows in grouped.items()]
    items.sort(key=lambda item: (-(item.get("n") or 0), str(item.get("key") or "")))
    return items


def _registry_rows(path: Path, selected_date: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = load_json_file(path)
    entries = payload.get("entries") if isinstance(payload, dict) and isinstance(payload.get("entries"), dict) else {}
    rows: list[dict[str, Any]] = []
    pending = 0
    unsupported = 0
    feed_cache: dict[int, dict[str, Any] | None] = {}
    feed_resolved = 0
    registry_fallback = 0
    feed_miss = 0
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        first_seen = entry.get("firstSeenSnapshot") if isinstance(entry.get("firstSeenSnapshot"), dict) else {}
        last_seen = entry.get("lastSeenSnapshot") if isinstance(entry.get("lastSeenSnapshot"), dict) else {}
        owner = str(entry.get("owner") or "").strip()
        market = str(entry.get("market") or "unknown").strip() or "unknown"
        prop = str(entry.get("prop") or "unknown").strip() or "unknown"
        selection = str(entry.get("selection") or first_seen.get("selection") or last_seen.get("selection") or "").strip().lower()
        line = _safe_float(entry.get("marketLine"))
        if line is None:
            line = _safe_float(last_seen.get("marketLine"))
        if line is None:
            line = _safe_float(first_seen.get("marketLine"))
        game_pk = entry.get("gamePk")
        try:
            game_pk_int = int(game_pk or 0)
        except Exception:
            game_pk_int = 0
        try:
            entry_player_id = int(entry.get("playerId") or 0)
        except Exception:
            entry_player_id = 0
        if game_pk_int > 0 and game_pk_int not in feed_cache:
            feed_cache[game_pk_int] = load_json_or_gz_file(raw_feed_live_path(selected_date, game_pk_int))
        actual = (
            _actual_from_feed(feed_cache.get(game_pk_int), owner, market, prop, player_id=entry_player_id)
            if game_pk_int > 0
            else None
        )
        actual_from_feed = actual is not None
        if actual is not None:
            feed_resolved += 1
        else:
            if game_pk_int > 0:
                feed_miss += 1
            actual = _safe_float(last_seen.get("actual"))
            if actual is None:
                actual = _safe_float(first_seen.get("actual"))
            if actual is not None:
                registry_fallback += 1
        result = _settle_pick(actual, line, selection)
        if actual is None:
            pending += 1
            continue
        if result is None:
            unsupported += 1
            continue
        rows.append(
            {
                "date": selected_date,
                "market": market,
                "klass": selection or "unknown",
                "stat": prop,
                "player": owner or None,
                "gamePk": game_pk,
                "selection": selection,
                "line": line,
                "actual": actual,
                "result": result,
                "first_seen_at": entry.get("firstSeenAt"),
                "last_seen_at": entry.get("lastSeenAt"),
                "actual_source": "feed_live" if actual_from_feed else "registry",
            }
        )

    warnings: list[str] = []
    if pending:
        warnings.append(f"pending_actuals:{pending}")
    if unsupported:
        warnings.append(f"unsupported_picks:{unsupported}")
    if feed_miss:
        warnings.append(f"feed_live_miss:{feed_miss}")
    signal_info = {
        "exists": path.exists(),
        "lines": len(entries),
        "raw": len(entries),
        "bytes": path.stat().st_size if path.exists() else 0,
        "feedResolved": feed_resolved,
        "registryFallback": registry_fallback,
    }
    return rows, {"signals": signal_info, "warnings": warnings}


@lru_cache(maxsize=256)
def build_live_lens_daily_accuracy_payload(query_string: str) -> dict[str, Any] | None:
    date_list = _parse_window(query_string, default_days=30)
    if not date_list:
        return None

    any_signal_files = False
    all_rows: list[dict[str, Any]] = []
    days: list[dict[str, Any]] = []
    for selected_date in date_list:
        registry_path = live_prop_registry_path(selected_date)
        rows, meta = _registry_rows(registry_path, selected_date)
        signals = dict(meta.get("signals") or {}) if isinstance(meta, dict) else {}
        warnings = list(meta.get("warnings") or []) if isinstance(meta, dict) else []
        if signals.get("exists"):
            any_signal_files = True
        days.append(
            {
                "date": selected_date,
                "available": bool(rows),
                "signals": signals,
                "warnings": warnings,
                "summary": _summary(rows),
                "by_market": _group_rows(rows, "market"),
                "by_horizon": [],
                "by_klass": _group_rows(rows, "klass"),
                "by_stat": _group_rows(rows, "stat"),
                "by_tag": [],
            }
        )
        all_rows.extend(rows)

    if not any_signal_files:
        return None

    return {
        "ok": True,
        "version": "live-lens-accuracy-v1",
        "window": {"since": date_list[0], "until": date_list[-1]},
        "days": days,
        "summary": {
            "available": bool(all_rows),
            "summary": _summary(all_rows),
            "by_market": _group_rows(all_rows, "market"),
            "by_horizon": [],
            "by_klass": _group_rows(all_rows, "klass"),
            "by_stat": _group_rows(all_rows, "stat"),
            "by_tag": [],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }