from __future__ import annotations

from copy import deepcopy
import math
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from syndicate.features.mlb.cards import build_cards_page_context
from syndicate.features.mlb.ladders_common import build_module_links
from syndicate.features.mlb.ladders_common import format_num
from syndicate.features.mlb.ladders_common import format_pct
from syndicate.features.mlb.ladders_common import parse_iso_date
from syndicate.features.mlb.sources import live_lens_log_path
from syndicate.features.mlb.sources import live_lens_report_path
from syndicate.features.mlb.sources import load_json_file
from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.shared.live_lens_contract import attach_live_lens_contract
from syndicate.features.shared.refresh_state_store import data_root
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.timezone import central_today_iso


def live_lens_snapshot_path() -> Path:
    return data_root() / "live" / "mlb_live_lens.json"


_LIVE_LENS_REPORT_MAX_AGE_DEFAULT_SECONDS = 60


def _path_age_seconds(path: Path | None) -> float | None:
    if not isinstance(path, Path) or not path.exists() or not path.is_file():
        return None
    try:
        return max(0.0, float(time.time()) - float(path.stat().st_mtime))
    except Exception:
        return None


def _live_lens_report_max_age_seconds() -> int:
    raw = str(os.environ.get("MLB_LIVE_LENS_REPORT_MAX_AGE_SECONDS") or "").strip()
    try:
        value = int(raw or _LIVE_LENS_REPORT_MAX_AGE_DEFAULT_SECONDS)
    except Exception:
        value = _LIVE_LENS_REPORT_MAX_AGE_DEFAULT_SECONDS
    return max(1, value)


def _live_lens_report_needs_refresh(selected_date: str) -> bool:
    # #128: was `datetime.now().astimezone().date().isoformat()` -- the
    # server's system-local date, not the slate's own operating date. On
    # Render (system tz likely UTC) this silently went stale every night
    # once UTC crossed midnight while a US evening slate was still very
    # much "today" in the Central-time terms every other MLB date comparison
    # in this repo uses -- confirmed live: the whole live-lens refresh
    # pipeline froze in place for hours (every "needs refresh" check below
    # short-circuited False), masking every other #128 fix behind it.
    if str(selected_date).strip() != central_today_iso():
        return False
    report_path = live_lens_report_path(selected_date)
    report = load_json_file(report_path)
    if not isinstance(report, dict) or not isinstance(report.get("games"), list) or not report.get("games"):
        return True
    # #128: file mtime is the wrong freshness proxy now that live-odds-worker
    # also calls pull_hot_artifacts every tick (added this same session) --
    # the date-scoped incremental pull matches this exact file's own
    # filename pattern and re-fetches/re-writes it from web on every cycle
    # regardless of whether its CONTENT changed, which resets the mtime this
    # check used to rely on and made it look "fresh" (<max-age) forever,
    # permanently starving _persist_live_lens_report of ever running again.
    # Exactly the same failure mode _live_lens_snapshot_needs_refresh's own
    # comment already documented for a different caller (refresh-worker) --
    # same fix: trust the report's own generatedAt content field first, only
    # falling back to the file-mtime proxy when it doesn't carry one.
    content_age_seconds = _snapshot_generated_at_age_seconds(report)
    if content_age_seconds is not None:
        return content_age_seconds > float(_live_lens_report_max_age_seconds())
    report_age_seconds = _path_age_seconds(report_path)
    if report_age_seconds is None:
        return True
    return report_age_seconds > float(_live_lens_report_max_age_seconds())


def _load_vendor_live_frontend() -> tuple[Any | None, Any | None]:
    try:
        from vendor.mlb_bettingv2.tools.web.flask_frontend import _client as mlb_vendor_client
        from vendor.mlb_bettingv2.tools.web.flask_frontend import fetch_game_feed_live

        return mlb_vendor_client, fetch_game_feed_live
    except Exception:  # pragma: no cover - vendor import is best-effort in tests
        return None, None


def _format_signed_num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    prefix = "+" if number > 0 else ""
    return f"{prefix}{format_num(number)}"


def _score_text(row: dict[str, Any]) -> str:
    matchup = row.get("matchup") if isinstance(row.get("matchup"), dict) else {}
    score = matchup.get("score") if isinstance(matchup.get("score"), dict) else {}
    away = score.get("away")
    home = score.get("home")
    if away is None or home is None:
        return "-"
    return f"{away}-{home}"


def _structured_status(row: dict[str, Any], *, fallback_date: str) -> dict[str, str]:
    status = row.get("status") if isinstance(row.get("status"), dict) else {}
    abstract = str(status.get("abstract") or status.get("abstractGameState") or "").strip()
    detailed = str(status.get("detailed") or status.get("detailedState") or abstract or row.get("startTime") or fallback_date).strip()
    lowered = f"{abstract} {detailed}".strip().lower()
    if any(token in lowered for token in ("live", "in progress", "manager challenge", "warmup")):
        abstract = "Live"
    elif any(token in lowered for token in ("final", "game over", "completed early")):
        abstract = "Final"
    elif not abstract:
        if detailed:
            abstract = detailed
        else:
            abstract = "Pregame"
    if not detailed:
        detailed = abstract or fallback_date
    return {
        "abstract": abstract,
        "detailed": detailed,
    }


def _append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
        handle.write("\n")


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except Exception:
        return None


def _status_bucket_from_row(row: dict[str, Any]) -> str:
    status = row.get("status") if isinstance(row.get("status"), dict) else {}
    abstract = str(status.get("abstract") or status.get("abstractGameState") or "").strip().lower()
    detailed = str(status.get("detailed") or status.get("detailedState") or "").strip().lower()
    text = f"{abstract} {detailed}".strip()
    if any(token in text for token in ("live", "in progress", "manager challenge", "warmup")):
        return "live"
    if any(token in text for token in ("final", "game over", "completed early")):
        return "final"
    return "pregame"


def _refresh_current_date_live_statuses(games: list[dict[str, Any]], selected_date: str) -> None:
    if str(selected_date).strip() != central_today_iso():
        return
    mlb_vendor_client, fetch_game_feed_live = _load_vendor_live_frontend()
    if mlb_vendor_client is None or fetch_game_feed_live is None:
        return
    try:
        client = mlb_vendor_client()
    except Exception:
        return

    feed_cache: dict[int, dict[str, Any] | None] = {}
    for game in games:
        if not isinstance(game, dict):
            continue
        game_pk = int(game.get("gamePk") or 0)
        if game_pk <= 0:
            continue
        if game_pk not in feed_cache:
            try:
                feed_cache[game_pk] = fetch_game_feed_live(client, game_pk)
            except Exception:
                feed_cache[game_pk] = None
        feed = feed_cache.get(game_pk)
        if not isinstance(feed, dict) or not feed:
            continue

        feed_status = ((feed.get("gameData") or {}).get("status") or {}) if isinstance((feed.get("gameData") or {}), dict) else {}
        status = _structured_status(
            {
                "status": {
                    "abstract": str(feed_status.get("abstractGameState") or "").strip(),
                    "detailed": str(feed_status.get("detailedState") or "").strip(),
                }
            },
            fallback_date=selected_date,
        )
        if _status_bucket_from_row({"status": status}) not in {"live", "final"}:
            continue

        game["status"] = status
        game["detail"] = status.get("detailed") or game.get("detail")

        linescore = ((feed.get("liveData") or {}).get("linescore") or {}) if isinstance((feed.get("liveData") or {}), dict) else {}
        team_totals = linescore.get("teams") if isinstance(linescore, dict) else {}
        away_value = ((team_totals.get("away") or {}).get("runs")) if isinstance(team_totals, dict) else None
        home_value = ((team_totals.get("home") or {}).get("runs")) if isinstance(team_totals, dict) else None
        try:
            away_runs = int(away_value) if away_value is not None else None
        except Exception:
            away_runs = None
        try:
            home_runs = int(home_value) if home_value is not None else None
        except Exception:
            home_runs = None
        if away_runs is not None or home_runs is not None:
            score = {"away": away_runs, "home": home_runs}
            game["score"] = score
            matchup = game.get("matchup") if isinstance(game.get("matchup"), dict) else None
            if isinstance(matchup, dict):
                matchup["score"] = score


def _lens_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    values = row.get("gameLens") if isinstance(row.get("gameLens"), list) else []
    return [value for value in values if isinstance(value, dict)]


def _find_lens(row: dict[str, Any], key: str) -> dict[str, Any]:
    for lens in _lens_rows(row):
        if str(lens.get("key") or "").strip() == key:
            return lens
    return {}


def _segment_items(row: dict[str, Any], *, limit: int = 4) -> list[str]:
    order = ["live", "full", "first7", "first5", "first3", "first1"]
    items: list[str] = []
    for key in order:
        lens = _find_lens(row, key)
        if not lens:
            continue
        label = str(lens.get("label") or key).strip() or key
        markets = lens.get("markets") if isinstance(lens.get("markets"), dict) else {}
        projection = lens.get("projection") if isinstance(lens.get("projection"), dict) else {}
        total_market = markets.get("total") if isinstance(markets.get("total"), dict) else {}
        spread_market = markets.get("spread") if isinstance(markets.get("spread"), dict) else {}
        moneyline_market = markets.get("moneyline") if isinstance(markets.get("moneyline"), dict) else {}
        if total_market.get("pick") and total_market.get("line") is not None:
            items.append(
                f"{label}: {str(total_market.get('pick')).title()} {format_num(total_market.get('line'))} total, edge {_format_signed_num(total_market.get('edge'))}"
            )
        elif spread_market.get("pick") and spread_market.get("homeLine") is not None:
            items.append(
                f"{label}: {str(spread_market.get('pick')).title()} {format_num(spread_market.get('homeLine'))} spread, edge {_format_signed_num(spread_market.get('edge'))}"
            )
        elif moneyline_market.get("pick"):
            items.append(
                f"{label}: {str(moneyline_market.get('pick')).title()} moneyline, edge {_format_signed_num(moneyline_market.get('edge'))}"
            )
        elif projection.get("total") is not None or projection.get("homeMargin") is not None:
            items.append(
                f"{label}: projected total {format_num(projection.get('total'))}, home margin {_format_signed_num(projection.get('homeMargin'))}"
            )
        if len(items) >= limit:
            break
    return items


def _top_live_prop_items(row: dict[str, Any], *, limit: int = 4) -> list[str]:
    values = row.get("liveProps") if isinstance(row.get("liveProps"), list) else []
    props = [value for value in values if isinstance(value, dict)]
    props.sort(key=lambda value: float(value.get("rankingScore") or value.get("estimatedWinProb") or value.get("edge") or 0.0), reverse=True)
    items: list[str] = []
    for prop in props[:limit]:
        player = str(prop.get("playerName") or "Prop").strip() or "Prop"
        selection = str(prop.get("selection") or "").strip().title()
        market = str(prop.get("marketLabel") or prop.get("market") or "Market").strip() or "Market"
        line = format_num(prop.get("line")) if prop.get("line") is not None else "-"
        odds = prop.get("odds")
        odds_text = "-"
        if odds is not None:
            try:
                number = int(float(odds))
                odds_text = f"+{number}" if number > 0 else str(number)
            except Exception:
                odds_text = str(odds)
        prob = format_pct(prop.get("modelProbOver") if str(prop.get("selection") or "").strip().lower() == "over" else prop.get("estimatedWinProb"))
        items.append(f"{player} {selection} {line} {market} ({odds_text}, {prob})".strip())
    return items


def _game_panels(row: dict[str, Any], generated_at: str) -> list[dict[str, Any]]:
    matchup = row.get("matchup") if isinstance(row.get("matchup"), dict) else {}
    live_text = str(matchup.get("liveText") or row.get("startTime") or "Live state unavailable").strip() or "Live state unavailable"
    live_lens = _find_lens(row, "live") or _find_lens(row, "full")
    live_markets = live_lens.get("markets") if isinstance(live_lens.get("markets"), dict) else {}
    total_market = live_markets.get("total") if isinstance(live_markets.get("total"), dict) else {}
    summary_reason = str(total_market.get("reason") or "Segment-level reasons come directly from the live-lens report artifact.").strip()
    prop_items = _top_live_prop_items(row)
    return [
        {
            "eyebrow": "Live state",
            "title": live_text,
            "body": f"Report snapshot generated at {generated_at}. Current score is {_score_text(row)}.",
        },
        {
            "eyebrow": "Segment looks",
            "title": "Current segment board",
            "body": summary_reason,
            "items": _segment_items(row),
        },
        {
            "eyebrow": "Top live props",
            "title": "Best in-game prop edges",
            "body": "These props are the highest-ranked live looks available in the selected report snapshot.",
            "items": prop_items or ["No live props were surfaced for this game in the selected report."],
        },
    ]


def _game_metrics(row: dict[str, Any]) -> list[dict[str, str]]:
    full_lens = _find_lens(row, "full")
    live_lens = _find_lens(row, "live")
    live_props = row.get("liveProps") if isinstance(row.get("liveProps"), list) else []
    counts = [lens for lens in _lens_rows(row) if not bool(lens.get("closed"))]
    return [
        {"label": "Score", "value": _score_text(row)},
        {"label": "Full home", "value": format_pct(full_lens.get("modelHomeWinProb"))},
        {"label": "Live home", "value": format_pct(live_lens.get("modelHomeWinProb"))},
        {"label": "Open segments", "value": str(len(counts))},
        {"label": "Live props", "value": str(len(live_props))},
        {"label": "Snapshot", "value": "Yes" if row.get("snapshotAvailable") else "No"},
    ]


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _first_present(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in raw and raw.get(key) is not None:
            return raw.get(key)
    return None


def _live_prop_market_label(market: Any, prop: Any, market_label: Any) -> str:
    market_key = str(market or "").strip().lower()
    prop_key = str(prop or "").strip().lower()
    label = str(market_label or "").strip()
    if market_key == "pitcher_props":
        mapping = {
            "strikeouts": "Strikeouts",
            "outs": "Outs Recorded",
            "hits_allowed": "Hits Allowed",
            "walks_allowed": "Walks Allowed",
            "earned_runs": "Earned Runs",
        }
        if prop_key in mapping:
            return mapping[prop_key]
        if label and label.lower() not in {"pitcher props", "pitcher_props", market_key}:
            return label
        return "Pitcher Props"
    if label:
        return label
    if prop_key:
        return prop_key.replace("_", " ").title()
    return str(market_key or "Market").replace("_", " ").title() or "Market"


def _market_has_signal(market: dict[str, Any]) -> bool:
    if not isinstance(market, dict):
        return False
    return any(
        market.get(key) is not None
        for key in ("pick", "line", "selectedLine", "homeLine", "edge", "homeOdds", "awayOdds", "overOdds", "underOdds", "reason")
    )


def _normalize_game_market_entry(raw: dict[str, Any], *, kind: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    if kind == "moneyline":
        out = {
            "pick": _first_present(raw, ("pick", "selection", "side")),
            "edge": _coerce_float(_first_present(raw, ("edge", "edgePct", "winEdge"))),
            "homeOdds": _first_present(raw, ("homeOdds", "home_odds", "homePrice", "home_price", "homeAmerican", "home_american")),
            "awayOdds": _first_present(raw, ("awayOdds", "away_odds", "awayPrice", "away_price", "awayAmerican", "away_american")),
            "line": _coerce_float(_first_present(raw, ("line", "price", "ml"))),
            "reason": _first_present(raw, ("reason", "summary", "note")),
        }
    elif kind == "total":
        out = {
            "pick": _first_present(raw, ("pick", "selection", "side")),
            "edge": _coerce_float(_first_present(raw, ("edge", "edgePct", "winEdge"))),
            "line": _coerce_float(_first_present(raw, ("line", "total", "marketLine"))),
            "overOdds": _first_present(raw, ("overOdds", "over_odds", "overPrice", "over_price", "overAmerican", "over_american")),
            "underOdds": _first_present(raw, ("underOdds", "under_odds", "underPrice", "under_price", "underAmerican", "under_american")),
            "reason": _first_present(raw, ("reason", "summary", "note")),
        }
    else:
        out = {
            "pick": _first_present(raw, ("pick", "selection", "side")),
            "edge": _coerce_float(_first_present(raw, ("edge", "edgePct", "winEdge"))),
            "homeLine": _coerce_float(_first_present(raw, ("homeLine", "line", "spread", "runLine", "run_line"))),
            "selectedLine": _coerce_float(_first_present(raw, ("selectedLine", "line", "spread", "runLine", "run_line"))),
            "homeOdds": _first_present(raw, ("homeOdds", "home_odds", "homePrice", "home_price", "homeAmerican", "home_american")),
            "awayOdds": _first_present(raw, ("awayOdds", "away_odds", "awayPrice", "away_price", "awayAmerican", "away_american")),
            "reason": _first_present(raw, ("reason", "summary", "note")),
        }
    return {key: value for key, value in out.items() if value is not None}


def _normalized_game_markets(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("gameMarkets") if isinstance(row.get("gameMarkets"), dict) else {}
    totals_raw = raw.get("totals") if isinstance(raw.get("totals"), dict) else {}
    moneyline_raw = raw.get("ml") if isinstance(raw.get("ml"), dict) else {}
    spread_raw = raw.get("spread") if isinstance(raw.get("spread"), dict) else {}
    return {
        "moneyline": _normalize_game_market_entry(moneyline_raw, kind="moneyline"),
        "spread": _normalize_game_market_entry(spread_raw, kind="spread"),
        "total": _normalize_game_market_entry(totals_raw, kind="total"),
    }


def _with_market_fallback_lenses(row: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fallback_markets = _normalized_game_markets(row)
    lens_rows: list[dict[str, Any]] = []
    for lens in _lens_rows(row):
        current = lens.get("markets") if isinstance(lens.get("markets"), dict) else {}
        merged = {
            "moneyline": current.get("moneyline") if isinstance(current.get("moneyline"), dict) else {},
            "spread": current.get("spread") if isinstance(current.get("spread"), dict) else {},
            "total": current.get("total") if isinstance(current.get("total"), dict) else {},
        }
        for key in ("moneyline", "spread", "total"):
            if not _market_has_signal(merged[key]) and _market_has_signal(fallback_markets.get(key) if isinstance(fallback_markets.get(key), dict) else {}):
                merged[key] = dict(fallback_markets.get(key) or {})
        out_lens = dict(lens)
        out_lens["markets"] = merged
        lens_rows.append(out_lens)
    return lens_rows, fallback_markets


def _game_from_report_row(row: dict[str, Any], *, report_date: str, generated_at: str) -> dict[str, Any]:
    matchup = row.get("matchup") if isinstance(row.get("matchup"), dict) else {}
    away = matchup.get("away") if isinstance(matchup.get("away"), dict) else {}
    home = matchup.get("home") if isinstance(matchup.get("home"), dict) else {}
    status = _structured_status(row, fallback_date=report_date)
    summary = str(matchup.get("liveText") or "Live-lens snapshot loaded from artifact.").strip() or "Live-lens snapshot loaded from artifact."
    live_props = row.get("liveProps") if isinstance(row.get("liveProps"), list) else []
    lens_rows, fallback_markets = _with_market_fallback_lenses(row)
    live_lens = _find_lens({"gameLens": lens_rows}, "live") or _find_lens({"gameLens": lens_rows}, "full")
    top_level_markets = live_lens.get("markets") if isinstance(live_lens.get("markets"), dict) else {}
    if not any(_market_has_signal(top_level_markets.get(key) if isinstance(top_level_markets.get(key), dict) else {}) for key in ("moneyline", "spread", "total")):
        top_level_markets = fallback_markets
    return {
        "archivedLiveProps": row.get("archivedLiveProps") if isinstance(row.get("archivedLiveProps"), list) else [],
        "gameLens": lens_rows,
        "gameMarkets": row.get("gameMarkets") if isinstance(row.get("gameMarkets"), dict) else {},
        "markets": top_level_markets,
        "gamePk": int(row.get("gamePk") or 0),
        "prop_groups": row.get("prop_groups") if isinstance(row.get("prop_groups"), list) else [],
        "prop_lens": row.get("prop_lens") if isinstance(row.get("prop_lens"), dict) else {},
        "market_tiles": row.get("market_tiles") if isinstance(row.get("market_tiles"), list) else [],
        "liveProps": live_props,
        "matchup": matchup,
        "predictions": row.get("predictions") if isinstance(row.get("predictions"), dict) else {},
        "props": row.get("props") if isinstance(row.get("props"), list) else [],
        "simContextAvailable": bool(row.get("simContextAvailable")),
        "snapshotAvailable": bool(row.get("snapshotAvailable")),
        "startTime": str(row.get("startTime") or report_date).strip() or report_date,
        "trackedProps": row.get("trackedProps") if isinstance(row.get("trackedProps"), list) else [],
        "probable": row.get("probable") if isinstance(row.get("probable"), dict) else {},
        "actual_box_panel": row.get("actual_box_panel") if isinstance(row.get("actual_box_panel"), dict) else {},
        "first1BetSignal": row.get("first1BetSignal") if isinstance(row.get("first1BetSignal"), dict) else {},
        "card_variant": "mlb_main",
        "away": {
            "abbr": str(away.get("abbr") or "AWY").strip() or "AWY",
            "name": str(away.get("name") or away.get("abbr") or "Away").strip() or "Away",
        },
        "home": {
            "abbr": str(home.get("abbr") or "HOM").strip() or "HOM",
            "name": str(home.get("name") or home.get("abbr") or "Home").strip() or "Home",
        },
        "status": status,
        "detail": str(row.get("startTime") or report_date).strip() or report_date,
        "summary": summary,
        "status_badge": str(status.get("abstract") or "Live lens").strip() or "Live lens",
        "hero_note": f"{len(live_props)} live props | snapshot {'yes' if row.get('snapshotAvailable') else 'no'}",
        "metrics": _game_metrics(row),
        "panels": _game_panels(row, generated_at),
        "href": f"/mlb/game/{int(row.get('gamePk') or 0)}?date={report_date}",
        "href_label": "Open game detail",
    }


def _parse_number_text(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def _normalize_live_prop_row(row: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    raw_market = str(row.get("market") or row.get("marketGroup") or row.get("group") or "").strip()
    raw_prop = str(row.get("prop") or row.get("marketProp") or row.get("prop_key") or "").strip()
    market_label = _live_prop_market_label(
        raw_market,
        raw_prop,
        row.get("marketLabel") or row.get("market_label") or row.get("label") or row.get("market"),
    )
    selection = str(row.get("selection") or row.get("side") or row.get("betSide") or row.get("marketSide") or row.get("over_under") or "").strip().title()
    return {
        "playerName": str(row.get("playerName") or row.get("player_name") or row.get("batter_name") or row.get("pitcher_name") or row.get("name") or row.get("title") or "Prop").strip() or "Prop",
        "prop": raw_prop,
        "selection": selection,
        "marketLabel": market_label,
        "market": raw_market,
        "line": row.get("line") if row.get("line") is not None else row.get("threshold") if row.get("threshold") is not None else row.get("market_line"),
        "odds": row.get("odds") if row.get("odds") is not None else row.get("price") if row.get("price") is not None else row.get("americanOdds") if row.get("americanOdds") is not None else row.get("american_odds"),
        "modelProbOver": row.get("modelProbOver") if row.get("modelProbOver") is not None else row.get("model_prob_over") if row.get("model_prob_over") is not None else row.get("estimatedWinProb") if row.get("estimatedWinProb") is not None else row.get("estimated_win_prob"),
        "estimatedWinProb": row.get("estimatedWinProb") if row.get("estimatedWinProb") is not None else row.get("estimated_win_prob") if row.get("estimated_win_prob") is not None else row.get("modelProbOver") if row.get("modelProbOver") is not None else row.get("model_prob_over"),
        "rankingScore": row.get("rankingScore") if row.get("rankingScore") is not None else row.get("ranking_score") if row.get("ranking_score") is not None else row.get("edge") if row.get("edge") is not None else row.get("live_edge"),
        "actual": row.get("actual") if row.get("actual") is not None else row.get("actual_value") if row.get("actual_value") is not None else row.get("actualSoFar") if row.get("actualSoFar") is not None else row.get("actual_so_far"),
        "actualSoFar": row.get("actualSoFar") if row.get("actualSoFar") is not None else row.get("actual_so_far"),
        "actualValue": row.get("actualValue") if row.get("actualValue") is not None else row.get("actual_value"),
        "liveProjection": row.get("liveProjection") if row.get("liveProjection") is not None else row.get("live_projection") if row.get("live_projection") is not None else row.get("projection"),
        "liveEdge": row.get("liveEdge") if row.get("liveEdge") is not None else row.get("live_edge"),
        "projectionGap": row.get("projectionGap") if row.get("projectionGap") is not None else row.get("projection_gap"),
        "modelMean": row.get("modelMean") if row.get("modelMean") is not None else row.get("model_mean"),
        "outsMean": row.get("outsMean") if row.get("outsMean") is not None else row.get("outs_mean"),
        "outsRecorded": row.get("outsRecorded") if row.get("outsRecorded") is not None else row.get("outs_recorded"),
        "strikeoutRate": row.get("strikeoutRate") if row.get("strikeoutRate") is not None else row.get("strikeout_rate"),
        "strikeRate": row.get("strikeRate") if row.get("strikeRate") is not None else row.get("strike_rate"),
        "pitchCount": row.get("pitchCount") if row.get("pitchCount") is not None else row.get("pitch_count"),
        "pitchCountBuffer": row.get("pitchCountBuffer") if row.get("pitchCountBuffer") is not None else row.get("pitch_count_buffer"),
        "pitchesPerBatter": row.get("pitchesPerBatter") if row.get("pitchesPerBatter") is not None else row.get("pitches_per_batter"),
        "expectedPitchesPerBatter": row.get("expectedPitchesPerBatter") if row.get("expectedPitchesPerBatter") is not None else row.get("expected_pitches_per_batter"),
        "staminaPitches": row.get("staminaPitches") if row.get("staminaPitches") is not None else row.get("stamina_pitches"),
        "timesThroughOrder": row.get("timesThroughOrder") if row.get("timesThroughOrder") is not None else row.get("times_through_order"),
    }


def _live_props_from_card(card: dict[str, Any]) -> list[dict[str, Any]]:
    markets = card.get("markets") if isinstance(card.get("markets"), dict) else {}
    rows: list[dict[str, Any]] = []
    for key in ("extraHitterProps", "extraPitcherProps", "hitterProps", "pitcherProps"):
        values = markets.get(key) if isinstance(markets.get(key), list) else []
        for value in values:
            normalized = _normalize_live_prop_row(value)
            if normalized is not None:
                rows.append(normalized)
    if not rows:
        rows.extend(_live_props_from_prop_groups(card))
    rows.sort(
        key=lambda value: float(value.get("rankingScore") or value.get("estimatedWinProb") or value.get("modelProbOver") or value.get("odds") or 0.0),
        reverse=True,
    )
    return rows


def _live_props_from_game_detail(selected_date: str, game_pk: int) -> list[dict[str, Any]]:
    """Real live actuals for one live game: registry-tracked snapshots plus
    box-score-driven synthesis (mlb/cards.py's live_prop_rows_for_game --
    the same pipeline the game-detail sim panel already uses), not just the
    plain pregame-projection markets list. Involves a live box-score fetch
    per game, so this is hard-refused inside a web request (#124 follow-up
    (b)) -- it belongs on the live-lens worker tick; a web request falls
    back to the plain card props (still real, just without a live actual
    until the next tick fills it in).
    """
    if not game_pk:
        return []
    from syndicate.features.shared.request_path_guard import refuse_if_compute_in_request_path

    try:
        refuse_if_compute_in_request_path("mlb_live_lens_game_detail_props")
    except Exception:
        return []

    try:
        from syndicate.features.mlb.cards import live_prop_rows_for_game
    except Exception:
        return []

    try:
        raw_rows = live_prop_rows_for_game(selected_date, game_pk)
    except Exception:
        return []

    rows = [_normalize_live_prop_row(row) for row in raw_rows if isinstance(row, dict)]
    rows = [row for row in rows if row is not None]
    rows.sort(
        key=lambda value: float(value.get("rankingScore") or value.get("estimatedWinProb") or value.get("modelProbOver") or value.get("odds") or 0.0),
        reverse=True,
    )
    return rows


def _card_score_from_card(card: dict[str, Any]) -> dict[str, Any]:
    score = card.get("score") if isinstance(card.get("score"), dict) else {}
    if score:
        return dict(score)
    matchup = card.get("matchup") if isinstance(card.get("matchup"), dict) else {}
    score = matchup.get("score") if isinstance(matchup.get("score"), dict) else {}
    if score:
        return dict(score)
    actual_box_panel = card.get("actual_box_panel") if isinstance(card.get("actual_box_panel"), dict) else {}
    actual_box = actual_box_panel.get("actual_box") if isinstance(actual_box_panel.get("actual_box"), dict) else {}
    totals = actual_box.get("totals") if isinstance(actual_box.get("totals"), list) else []
    score_by_team: dict[str, Any] = {}
    for row in totals:
        if not isinstance(row, dict):
            continue
        team = str(row.get("team") or "").strip().lower()
        total_info = row.get("totals") if isinstance(row.get("totals"), dict) else {}
        runs = total_info.get("R") if isinstance(total_info, dict) else None
        if team in {"away", "home"} and runs is not None:
            score_by_team[team] = runs
    return {"away": score_by_team.get("away"), "home": score_by_team.get("home")} if score_by_team else {}


def _live_lens_segments_from_card(card: dict[str, Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    overview_rows = card.get("segment_overview_cards") if isinstance(card.get("segment_overview_cards"), list) else []
    probability_rows = card.get("probability_rows") if isinstance(card.get("probability_rows"), list) else []
    row_order = ["live", "full", "first7", "first5", "first3", "first1"]
    for index, row in enumerate(overview_rows):
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or row_order[index] if index < len(row_order) else f"segment{index + 1}").strip() or f"segment{index + 1}"
        key_text = label.lower()
        if "live" in key_text:
            key = "live"
        elif "7" in key_text:
            key = "first7"
        elif "5" in key_text:
            key = "first5"
        elif "3" in key_text:
            key = "first3"
        elif "1" in key_text:
            key = "first1"
        else:
            key = row_order[index] if index < len(row_order) else "full"
        subtitle = str(row.get("subtitle") or "").strip()
        projection_total = _parse_number_text(subtitle.split("|")[-1] if "|" in subtitle else subtitle)
        projection_margin = _parse_number_text(row.get("foot_right"))
        if projection_margin is None:
            projection_margin = _parse_number_text(row.get("best_edge"))
        if projection_margin is None:
            projection_margin = _parse_number_text(row.get("home_win"))
        reason = str(row.get("reason") or row.get("main") or subtitle).strip()
        segment = {
            "key": key,
            "label": label,
            "closed": False,
            "badge": str(row.get("badge") or "").strip(),
            "score": str(row.get("score") or "").strip(),
            "subtitle": subtitle,
            "reason": reason,
            "projection": {
                "total": projection_total,
                "homeMargin": projection_margin,
            },
            "markets": {
                "total": {
                    "pick": None if str(row.get("badge") or "").strip().lower() in {"", "no bet", "nobet"} else str(row.get("main") or row.get("badge") or "").strip() or None,
                    "line": projection_total,
                    "reason": reason,
                },
                "spread": {
                    "pick": None,
                    "homeLine": projection_margin,
                    "reason": reason,
                },
                "moneyline": {
                    "pick": None,
                    "reason": reason,
                },
            },
        }
        segments.append(segment)

    probability_keys = ["first1", "first3", "first5", "full"]
    for index, row in enumerate(probability_rows):
        if not isinstance(row, dict):
            continue
        key = probability_keys[index] if index < len(probability_keys) else f"first{index + 1}"
        summary = str(row.get("summary") or "").strip()
        if not summary:
            continue
        segments.append(
            {
                "key": key,
                "label": str(row.get("label") or key.replace("first", "First ").title()).strip() or key,
                "closed": False,
                "badge": "",
                "score": summary,
                "subtitle": summary,
                "reason": summary,
                "projection": {
                    "total": _parse_number_text(summary),
                    "homeMargin": _parse_number_text(row.get("home_pct")),
                },
                "markets": {
                    "total": {
                        "pick": None,
                        "line": _parse_number_text(summary),
                        "reason": summary,
                    },
                    "spread": {},
                    "moneyline": {},
                },
            }
        )
    return segments


def _lens_rows_have_projection_signal(values: Any) -> bool:
    if not isinstance(values, list):
        return False
    for lens in values:
        if not isinstance(lens, dict):
            continue
        projection = lens.get("projection") if isinstance(lens.get("projection"), dict) else {}
        if any(_parse_number_text(projection.get(key)) is not None for key in ("away", "home", "total", "homeMargin")):
            return True
        if _parse_number_text(lens.get("modelHomeWinProb")) is not None:
            return True
    return False


_CARD_PROP_TITLE_RE = re.compile(r"^(?P<player>.+?)\s+(?P<selection>Over|Under)\s+(?P<line>[-+]?\d+(?:\.\d+)?)\s+(?P<market>.+)$", re.IGNORECASE)


def _detail_edge_from_text(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"edge\s*([-+]?\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None
def _prop_row_from_card_item(item: dict[str, Any], *, group_variant: str, section_title: str) -> dict[str, Any] | None:
    title = str(item.get("title") or "").strip()
    match = _CARD_PROP_TITLE_RE.match(title)
    if not match:
        return None
    detail = str(item.get("detail") or "").strip()
    selection = str(match.group("selection") or "").strip().lower()
    market_label = str(match.group("market") or "").strip() or section_title or "Prop"
    line = _parse_number_text(match.group("line"))
    edge = _detail_edge_from_text(detail)
    odds = _parse_number_text(detail)
    return {
        "playerName": str(match.group("player") or "Prop").strip() or "Prop",
        "selection": selection,
        "marketLabel": market_label,
        "market": section_title.lower().replace(" ", "_") if section_title else "prop",
        "line": line,
        "odds": odds,
        "modelProbOver": None,
        "estimatedWinProb": None,
        "rankingScore": edge if edge is not None else line,
        "tier": "official" if group_variant == "official" else "playable",
        "status": "live" if group_variant == "official" else "tracked",
        "source": "cards_prop_groups",
        "reason_summary": detail or title,
        "reasons": [detail] if detail else [],
    }


def _live_props_from_prop_groups(card: dict[str, Any]) -> list[dict[str, Any]]:
    prop_groups = card.get("prop_groups") if isinstance(card.get("prop_groups"), list) else []
    rows: list[dict[str, Any]] = []
    for group in prop_groups:
        if not isinstance(group, dict):
            continue
        variant = str(group.get("variant") or "").strip().lower()
        sections = group.get("sections") if isinstance(group.get("sections"), list) else []
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_title = str(section.get("title") or "").strip()
            items = section.get("items") if isinstance(section.get("items"), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                normalized = _prop_row_from_card_item(item, group_variant=variant, section_title=section_title)
                if normalized is not None:
                    rows.append(normalized)
    rows.sort(
        key=lambda value: float(value.get("rankingScore") or value.get("estimatedWinProb") or value.get("modelProbOver") or value.get("odds") or 0.0),
        reverse=True,
    )
    return rows


def _merge_cards_context_into_live_row(row: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    merged = dict(row)
    card_props = _live_props_from_card(card)
    card_segments = _live_lens_segments_from_card(card)
    card_score = _card_score_from_card(card)
    existing_game_lens = row.get("gameLens") if isinstance(row.get("gameLens"), list) else []
    row_has_projection_signal = _lens_rows_have_projection_signal(existing_game_lens)
    card_has_projection_signal = _lens_rows_have_projection_signal(card_segments)
    row_status = row.get("status") if isinstance(row.get("status"), dict) else {}
    row_status_text = f"{str(row_status.get('abstract') or row_status.get('abstractGameState') or '').strip()} {str(row_status.get('detailed') or row_status.get('detailedState') or '').strip()}".strip().lower()
    row_is_live_or_final = any(token in row_status_text for token in ("live", "in progress", "warmup", "final", "game over", "completed"))
    should_replace_game_lens = (
        card_segments
        and (
            not existing_game_lens
            or not row_is_live_or_final
            or (card_has_projection_signal and not row_has_projection_signal)
        )
    )
    if should_replace_game_lens:
        merged["gameLens"] = card_segments
    if card_props:
        merged["liveProps"] = card_props
    if card_props:
        merged["props"] = card_props
    if card_props:
        merged["trackedProps"] = card_props
    matchup = merged.get("matchup") if isinstance(merged.get("matchup"), dict) else {}
    card_matchup = {"away": card.get("away") if isinstance(card.get("away"), dict) else {}, "home": card.get("home") if isinstance(card.get("home"), dict) else {}}
    if card_matchup["away"]:
        matchup["away"] = card_matchup["away"]
    if card_matchup["home"]:
        matchup["home"] = card_matchup["home"]
    if card_score:
        matchup["score"] = card_score
    matchup["liveText"] = str(card.get("summary") or card.get("detail") or matchup.get("liveText") or "Live-lens snapshot loaded from the MLB cards artifact.").strip() or "Live-lens snapshot loaded from the MLB cards artifact."
    merged["matchup"] = matchup
    if card_score:
        merged["score"] = card_score
    if isinstance(card.get("predictions"), dict) and card.get("predictions"):
        merged["predictions"] = card.get("predictions")
    if isinstance(card.get("markets"), dict) and card.get("markets"):
        merged["gameMarkets"] = card.get("markets")
    if isinstance(card.get("prop_groups"), list) and card.get("prop_groups"):
        merged["prop_groups"] = card.get("prop_groups")
    if isinstance(card.get("prop_lens"), dict) and card.get("prop_lens"):
        merged["prop_lens"] = card.get("prop_lens")
    if isinstance(card.get("market_tiles"), list) and card.get("market_tiles"):
        merged["market_tiles"] = card.get("market_tiles")
    if isinstance(card.get("probable"), dict) and card.get("probable"):
        merged["probable"] = card.get("probable")
    if isinstance(card.get("actual_box_panel"), dict) and card.get("actual_box_panel"):
        merged["actual_box_panel"] = card.get("actual_box_panel")
    if isinstance(card.get("first1BetSignal"), dict) and card.get("first1BetSignal"):
        merged["first1BetSignal"] = card.get("first1BetSignal")
    if not merged.get("markets") and isinstance(card.get("markets"), dict):
        merged["markets"] = card.get("markets")
    if isinstance(card.get("archivedLiveProps"), list) and card.get("archivedLiveProps"):
        merged["archivedLiveProps"] = [dict(prop) for prop in card.get("archivedLiveProps") if isinstance(prop, dict)]
    card_status = card.get("status") if isinstance(card.get("status"), dict) else {}
    if card_status:
        merged_status = merged.get("status") if isinstance(merged.get("status"), dict) else {}
        merged_status_text = f"{str(merged_status.get('abstract') or merged_status.get('abstractGameState') or '').strip()} {str(merged_status.get('detailed') or merged_status.get('detailedState') or '').strip()}".strip().lower()
        card_status_text = f"{str(card_status.get('abstract') or card_status.get('abstractGameState') or '').strip()} {str(card_status.get('detailed') or card_status.get('detailedState') or '').strip()}".strip().lower()
        merged_is_live_or_final = any(token in merged_status_text for token in ("live", "in progress", "warmup", "final", "game over", "completed"))
        card_is_live_or_final = any(token in card_status_text for token in ("live", "in progress", "warmup", "final", "game over", "completed"))
        if card_is_live_or_final or not merged_is_live_or_final:
            merged["status"] = {
                "abstract": str(card_status.get("abstract") or card_status.get("abstractGameState") or merged_status.get("abstract") or "Live lens").strip() or "Live lens",
                "detailed": str(card_status.get("detailed") or card_status.get("detailedState") or card.get("detail") or merged_status.get("detailed") or "Live lens").strip() or "Live lens",
            }
    merged["snapshotAvailable"] = bool(card.get("snapshotAvailable", merged.get("snapshotAvailable", False)))
    merged["simContextAvailable"] = bool(card.get("simContextAvailable", merged.get("simContextAvailable", False)))
    return merged


def _card_status_bucket(card: dict[str, Any]) -> str:
    status = card.get("status") if isinstance(card.get("status"), dict) else {}
    abstract = str(status.get("abstract") or status.get("abstractGameState") or "").strip().lower()
    detailed = str(status.get("detailed") or status.get("detailedState") or card.get("detail") or "").strip().lower()
    text = f"{abstract} {detailed}".strip()
    if any(token in text for token in ("live", "in progress", "warmup")):
        return "live"
    if any(token in text for token in ("final", "game over", "completed")):
        return "final"
    return "pregame"


def _card_to_live_lens_row(card: dict[str, Any], *, report_date: str) -> dict[str, Any]:
    away = card.get("away") if isinstance(card.get("away"), dict) else {}
    home = card.get("home") if isinstance(card.get("home"), dict) else {}
    score = _card_score_from_card(card)
    card_props = _live_props_from_card(card)
    if _card_status_bucket(card) == "live":
        # Plain card markets are pregame-only projections with no `actual`/
        # `liveProjection` fields at all -- the real live-actuals pipeline
        # (registry-tracked snapshots + box-score-driven synthesis) lives in
        # mlb/cards.py's game-detail sim panel. Prefer it here so the board's
        # live column shows genuine actuals instead of nothing.
        live_detail_props = _live_props_from_game_detail(report_date, int(card.get("gamePk") or 0))
        if live_detail_props:
            card_props = live_detail_props
    card_game_lens = card.get("gameLens") if isinstance(card.get("gameLens"), list) else []
    derived_segments = _live_lens_segments_from_card(card)
    return {
        "gamePk": int(card.get("gamePk") or 0),
        "status": card.get("status") if isinstance(card.get("status"), dict) else {"abstract": _card_status_bucket(card).title(), "detailed": str(card.get("detail") or report_date).strip() or report_date},
        "startTime": str(card.get("startTime") or card.get("gameDate") or card.get("detail") or report_date).strip() or report_date,
        "matchup": {
            "away": away,
            "home": home,
            "score": score if score else {"away": None, "home": None},
            "liveText": str(card.get("summary") or card.get("detail") or "Live-lens snapshot loaded from the MLB cards artifact.").strip() or "Live-lens snapshot loaded from the MLB cards artifact.",
        },
        "score": score,
        "predictions": card.get("predictions") if isinstance(card.get("predictions"), dict) else {},
        "gameMarkets": card.get("markets") if isinstance(card.get("markets"), dict) else {},
        "gameLens": card_game_lens if _lens_rows_have_projection_signal(card_game_lens) else derived_segments,
        "prop_groups": card.get("prop_groups") if isinstance(card.get("prop_groups"), list) else [],
        "prop_lens": card.get("prop_lens") if isinstance(card.get("prop_lens"), dict) else {},
        "market_tiles": card.get("market_tiles") if isinstance(card.get("market_tiles"), list) else [],
        "props": card_props if card_props else (card.get("props") if isinstance(card.get("props"), list) else []),
        "liveProps": card_props if card_props else (card.get("liveProps") if isinstance(card.get("liveProps"), list) else []),
        "archivedLiveProps": card.get("archivedLiveProps") if isinstance(card.get("archivedLiveProps"), list) else [],
        "trackedProps": card_props if card_props else (card.get("trackedProps") if isinstance(card.get("trackedProps"), list) else []),
        "probable": card.get("probable") if isinstance(card.get("probable"), dict) else {},
        "actual_box_panel": card.get("actual_box_panel") if isinstance(card.get("actual_box_panel"), dict) else {},
        "first1BetSignal": card.get("first1BetSignal") if isinstance(card.get("first1BetSignal"), dict) else {},
        "simContextAvailable": bool(card.get("simContextAvailable")),
        "snapshotAvailable": bool(card.get("snapshotAvailable")),
    }


def _cards_backed_live_lens_report(selected_date: str) -> dict[str, Any] | None:
    try:
        cards_context = build_cards_page_context(selected_date)
    except Exception as exc:
        # TEMPORARY diagnostic (todo.md #128 follow-up) -- remove once the
        # cards-primary path's worker-side failure mode is confirmed.
        import traceback

        print(
            f"[CARDS_BACKED_LIVE_LENS_DIAG] build_cards_page_context raised {type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            flush=True,
        )
        return None

    cards = cards_context.get("games") if isinstance(cards_context.get("games"), list) else []
    if not cards:
        # TEMPORARY diagnostic (todo.md #128 follow-up) -- remove once the
        # cards-primary path's worker-side failure mode is confirmed.
        print(
            f"[CARDS_BACKED_LIVE_LENS_DIAG] build_cards_page_context returned no games "
            f"is_dict={isinstance(cards_context, dict)} keys={sorted(cards_context.keys()) if isinstance(cards_context, dict) else None}",
            flush=True,
        )
        return None

    report_path = live_lens_report_path(selected_date)
    report_games = [_card_to_live_lens_row(card, report_date=selected_date) for card in cards if isinstance(card, dict)]
    live_count = 0
    final_count = 0
    pregame_count = 0
    prop_count = 0
    for card in report_games:
        bucket = _card_status_bucket(card)
        if bucket == "live":
            live_count += 1
        elif bucket == "final":
            final_count += 1
        else:
            pregame_count += 1
        prop_count += len(card.get("liveProps") or card.get("props") or card.get("trackedProps") or [])

    payload = {
        "date": str(selected_date),
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataRoot": str(report_path.parent.parent),
        "liveLensDir": str(report_path.parent),
        "optimizationRegime": None,
        "counts": {
            "games": len(report_games),
            "live": live_count,
            "final": final_count,
            "pregame": pregame_count,
            "props": prop_count,
            "archivedLiveProps": 0,
        },
        "performance": {
            "marketsRefreshed": False,
            "marketRefreshMs": 0.0,
            "totalMs": 0.0,
            "snapshotLoadMs": 0.0,
            "simContextLoadMs": 0.0,
            "propEvalMs": 0.0,
            "gameLensMs": 0.0,
            "gameCount": len(report_games),
            "liveGameCount": live_count,
            "feedFetchCount": 0,
            "cardsFallback": True,
        },
        "games": report_games,
        "source_title": str(cards_context.get("source_title") or "MLB Game Cards").strip() or "MLB Game Cards",
        "source_path": str(report_path),
        "using_sample_data": bool(cards_context.get("using_sample_data", False)),
    }
    return payload


def _merge_cards_context_into_report(report: dict[str, Any], selected_date: str) -> dict[str, Any]:
    try:
        cards_context = build_cards_page_context(selected_date)
    except Exception:
        return report

    cards = cards_context.get("games") if isinstance(cards_context.get("games"), list) else []
    if not cards:
        return report

    cards_by_game_pk = {int(card.get("gamePk") or 0): card for card in cards if isinstance(card, dict) and int(card.get("gamePk") or 0)}
    games = report.get("games") if isinstance(report.get("games"), list) else []
    merged_games: list[dict[str, Any]] = []
    for row in games:
        if not isinstance(row, dict):
            continue
        game_pk = int(row.get("gamePk") or 0)
        card = cards_by_game_pk.get(game_pk)
        merged_games.append(_merge_cards_context_into_live_row(row, card) if isinstance(card, dict) else row)
    merged_report = dict(report)
    if merged_games:
        merged_report["games"] = merged_games
    if not isinstance(merged_report.get("counts"), dict):
        merged_report["counts"] = {}
    merged_counts = dict(merged_report.get("counts") or {})
    merged_counts["games"] = len(merged_games) if merged_games else int(merged_counts.get("games") or 0)
    merged_counts["live"] = sum(1 for game in merged_games if str((game.get("status") or {}).get("abstract") or "").strip().lower() == "live")
    merged_counts["final"] = sum(1 for game in merged_games if str((game.get("status") or {}).get("abstract") or "").strip().lower() == "final")
    merged_counts["pregame"] = sum(1 for game in merged_games if str((game.get("status") or {}).get("abstract") or "").strip().lower() not in {"live", "final"})
    merged_counts["props"] = sum(len(game.get("liveProps") or game.get("props") or game.get("trackedProps") or []) for game in merged_games)
    merged_report["counts"] = merged_counts
    merged_report["source_title"] = str(cards_context.get("source_title") or merged_report.get("source_title") or "MLB Game Cards").strip() or "MLB Game Cards"
    return merged_report


def _enhance_card_row_with_live_projection(card_row: dict[str, Any], projection_row: dict[str, Any]) -> dict[str, Any]:
    """Overlay a Monte-Carlo-derived (or previously persisted) row's live
    projection signal onto a card-based row, WITHOUT touching the card
    row's props -- the card artifact is the reliable source for those (#124
    follow-up (a)); the projection row only ever adds gameLens/score/
    predictions signal the card path doesn't already have.
    """
    enhanced = dict(card_row)
    card_status = enhanced.get("status") if isinstance(enhanced.get("status"), dict) else {}
    projection_status = projection_row.get("status") if isinstance(projection_row.get("status"), dict) else {}
    card_status_text = f"{str(card_status.get('abstract') or '').strip()} {str(card_status.get('detailed') or '').strip()}".strip().lower()
    projection_status_text = f"{str(projection_status.get('abstract') or '').strip()} {str(projection_status.get('detailed') or '').strip()}".strip().lower()
    card_is_live_or_final = any(token in card_status_text for token in ("live", "in progress", "warmup", "final", "game over", "completed"))
    projection_is_live_or_final = any(token in projection_status_text for token in ("live", "in progress", "warmup", "final", "game over", "completed"))

    # gameLens: the projection row's segments reflect actual in-game state
    # (which segment is live right now); the card's own derived segments are
    # only a generic pregame list. Mirrors the pre-#124 merge direction's
    # should_replace_game_lens, roles swapped (card is base here, not row).
    projection_game_lens = projection_row.get("gameLens") if isinstance(projection_row.get("gameLens"), list) else []
    card_game_lens = enhanced.get("gameLens") if isinstance(enhanced.get("gameLens"), list) else []
    card_game_lens_has_signal = _lens_rows_have_projection_signal(card_game_lens)
    projection_game_lens_has_signal = _lens_rows_have_projection_signal(projection_game_lens)
    should_use_projection_lens = projection_game_lens and (
        not card_game_lens
        or not card_is_live_or_final
        or (projection_game_lens_has_signal and not card_game_lens_has_signal)
    )
    if should_use_projection_lens:
        enhanced["gameLens"] = projection_game_lens

    if projection_status and (projection_is_live_or_final or not card_is_live_or_final):
        enhanced["status"] = projection_status

    # Props: cards stay the reliable primary source (#124 follow-up (a)) --
    # never overwritten here -- but if the card artifact genuinely has none
    # for this game while the projection report does, fill the gap rather
    # than showing nothing.
    if not (enhanced.get("liveProps") or enhanced.get("props") or enhanced.get("trackedProps")):
        projection_props = (
            projection_row.get("liveProps")
            or projection_row.get("props")
            or projection_row.get("trackedProps")
        )
        if isinstance(projection_props, list) and projection_props:
            enhanced["liveProps"] = projection_props
            enhanced["props"] = projection_props
            enhanced["trackedProps"] = projection_props

    projection_matchup = projection_row.get("matchup") if isinstance(projection_row.get("matchup"), dict) else {}
    projection_score = projection_matchup.get("score") if isinstance(projection_matchup.get("score"), dict) else None
    if isinstance(projection_score, dict) and (projection_score.get("away") is not None or projection_score.get("home") is not None):
        matchup = dict(enhanced.get("matchup") or {})
        matchup["score"] = projection_score
        enhanced["matchup"] = matchup
        enhanced["score"] = projection_score
    if not enhanced.get("predictions") and isinstance(projection_row.get("predictions"), dict) and projection_row.get("predictions"):
        enhanced["predictions"] = projection_row.get("predictions")
    if not enhanced.get("archivedLiveProps") and isinstance(projection_row.get("archivedLiveProps"), list) and projection_row.get("archivedLiveProps"):
        enhanced["archivedLiveProps"] = projection_row.get("archivedLiveProps")
    return enhanced


def _enhance_cards_report_with_live_projection(cards_report: dict[str, Any], projection_report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(projection_report, dict):
        return cards_report
    projection_games = projection_report.get("games") if isinstance(projection_report.get("games"), list) else []
    projection_by_game_pk = {
        int(game.get("gamePk") or 0): game
        for game in projection_games
        if isinstance(game, dict) and int(game.get("gamePk") or 0)
    }
    if not projection_by_game_pk:
        return cards_report
    games = cards_report.get("games") if isinstance(cards_report.get("games"), list) else []
    enhanced_games: list[dict[str, Any]] = []
    for row in games:
        if not isinstance(row, dict):
            continue
        projection_row = projection_by_game_pk.get(int(row.get("gamePk") or 0))
        enhanced_games.append(
            _enhance_card_row_with_live_projection(row, projection_row) if isinstance(projection_row, dict) else row
        )
    enhanced_report = dict(cards_report)
    if enhanced_games:
        enhanced_report["games"] = enhanced_games
    return enhanced_report


def _live_projection_enhancement_payload(selected_date: str) -> dict[str, Any] | None:
    """Best-effort fetch of MLB's vendored 120-sim-per-live-game Monte Carlo
    live re-sim (#124 follow-up (a)): a real enhancement layer over the
    card-based primary source, never a requirement for props to appear.
    Hard-refused inside a real web request on hosted Render (#124 follow-up
    (b)) -- this is the one genuinely heavy piece of live-lens compute, and
    it belongs on live-odds-worker's own tick, not a request thread.
    """
    from syndicate.features.shared.request_path_guard import refuse_if_compute_in_request_path

    try:
        refuse_if_compute_in_request_path("mlb_live_lens_monte_carlo_resim")
    except Exception:
        return None

    try:
        from vendor.mlb_bettingv2.tools.web.flask_frontend import _live_lens_payload
    except Exception:
        return None

    try:
        payload = _live_lens_payload(selected_date, persist=True)
    except Exception:
        return None

    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list) or not payload.get("games"):
        return None
    return payload


def _persist_live_lens_report(selected_date: str) -> dict[str, Any] | None:
    report_path = live_lens_report_path(selected_date)
    log_path = live_lens_log_path(selected_date)

    payload = _cards_backed_live_lens_report(selected_date)
    mc_payload = _live_projection_enhancement_payload(selected_date)
    if isinstance(payload, dict) and payload.get("games"):
        payload = _enhance_cards_report_with_live_projection(payload, mc_payload)
    elif isinstance(mc_payload, dict):
        # Cards artifact entirely unavailable (rare) -- fall back to the MC
        # payload alone rather than losing the report outright.
        payload = mc_payload

    if not isinstance(payload, dict):
        return None

    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        return None

    games = payload.get("games") if isinstance(payload.get("games"), list) else []
    log_entry = {
        "recordedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "date": str(selected_date),
        "generatedAt": payload.get("generatedAt"),
        "oddsRefreshedAt": payload.get("oddsRefreshedAt") or payload.get("odds_refreshed_at"),
        "counts": payload.get("counts") if isinstance(payload.get("counts"), dict) else {},
        "performance": payload.get("performance") if isinstance(payload.get("performance"), dict) else {},
        "games": [
            {
                "gamePk": game.get("gamePk"),
                "status": ((game.get("status") or {}).get("abstract")),
                "score": ((game.get("matchup") or {}).get("score")),
                "liveText": ((game.get("matchup") or {}).get("liveText")),
                "propCount": len(game.get("liveProps") or game.get("props") or game.get("trackedProps") or []),
                "topProps": (game.get("liveProps") or game.get("props") or game.get("trackedProps") or [])[:5],
            }
            for game in games
            if isinstance(game, dict)
        ],
    }

    try:
        _append_jsonl(log_path, log_entry)
    except Exception:
        pass
    return payload


def _value_has_non_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_value_has_non_finite_number(item) for item in value.values())
    if isinstance(value, list):
        return any(_value_has_non_finite_number(item) for item in value)
    if isinstance(value, tuple):
        return any(_value_has_non_finite_number(item) for item in value)
    return False


def validate_live_lens_snapshot(snapshot: Any) -> bool:
    if not isinstance(snapshot, dict):
        return False
    games = snapshot.get("games")
    if not isinstance(games, list):
        return False
    if len(games) > 50:
        return False
    if _value_has_non_finite_number(snapshot):
        return False
    return True


def _snapshot_games(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    games = snapshot.get("games")
    if not isinstance(games, list):
        page_context = snapshot.get("page_context") if isinstance(snapshot.get("page_context"), dict) else {}
        games = page_context.get("games") if isinstance(page_context.get("games"), list) else []
    return [dict(game) for game in games if isinstance(game, dict)][:50]


def _snapshot_counts(games: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "archivedLiveProps": sum(len(game.get("archivedLiveProps") or []) for game in games),
        "final": sum(1 for game in games if _status_bucket_from_row(game) == "final"),
        "games": len(games),
        "live": sum(1 for game in games if _status_bucket_from_row(game) == "live"),
        "pregame": sum(1 for game in games if _status_bucket_from_row(game) == "pregame"),
        "props": sum(len(game.get("liveProps") or game.get("props") or game.get("trackedProps") or []) for game in games),
    }


def _snapshot_route_context(selected_date: str, *, season: int | None = None, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    route_path = f"/mlb/season/{int(season)}/live-lens" if season is not None else "/mlb/live-lens"
    report_path = live_lens_snapshot_path()
    base = dict(snapshot.get("page_context") if isinstance(snapshot, dict) and isinstance(snapshot.get("page_context"), dict) else snapshot or {})
    games = _snapshot_games(snapshot or {}) if isinstance(snapshot, dict) else []
    if not base:
        base = {
            "season": season,
            "date": selected_date,
            "prev_date": selected_date,
            "next_date": selected_date,
            "module_links": build_module_links(selected_date, "Live lens"),
            "games": [],
            "scoreboard_items": [],
            "source_path": str(report_path),
            "using_sample_data": False,
            "odds_refreshed_at": None,
            "oddsRefreshedAt": None,
            "source_title": "MLB live lens unavailable",
            "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "counts": {"archivedLiveProps": 0, "final": 0, "games": 0, "live": 0, "pregame": 0, "props": 0},
            "app": {},
            "dataRoot": str(report_path.parent.parent),
            "liveLensDir": str(report_path.parent),
            "optimizationRegime": None,
            "performance": {},
            "header_stats": [
                {"label": "Games", "value": "0"},
                {"label": "Live", "value": "0"},
                {"label": "Final", "value": "0"},
                {"label": "Props", "value": "0"},
            ],
            "empty_state": {
                "eyebrow": "MLB live lens",
                "title": "No live-lens games were available for this date",
                "body": "The live-lens snapshot for this date did not surface any tracked games or live props.",
                "list_items": [f"Requested date: {selected_date}", f"Snapshot artifact: {report_path.name}"],
            },
            "route_path": route_path,
            "intro_title": f"MLB {int(season)} Live Lens" if season is not None else "MLB Live Lens",
            "intro_body": "The MLB live lens now serves a stored snapshot artifact directly.",
            "cards_grid_class": "mlb-cards-grid",
            "cards_stylesheet": "mlb/cards.css",
            "teaser": {
                "label": "Related MLB board",
                "body": "Use the MLB cards board to compare the pregame slate against this live-lens snapshot.",
                "href": f"/mlb/cards?date={selected_date}",
                "cta": "Open cards",
            },
        }
    if games:
        base["games"] = games
        base["scoreboard_items"] = [
            {
                "target_id": f"game-{game.get('gamePk')}",
                "label": f"{((game.get('away') or {}).get('abbr') or 'AWY')} @ {((game.get('home') or {}).get('abbr') or 'HOM')}",
                "status": game.get("status"),
            }
            for game in games
        ]
        base["counts"] = _snapshot_counts(games)
        base["header_stats"] = [
            {"label": "Games", "value": str(len(games))},
            {"label": "Live", "value": str(base["counts"].get("live") or 0)},
            {"label": "Final", "value": str(base["counts"].get("final") or 0)},
            {"label": "Props", "value": str(base["counts"].get("props") or 0)},
        ]
        base["empty_state"] = None
        base["source_title"] = str(base.get("source_title") or "MLB live-lens report artifact").strip() or "MLB live-lens report artifact"
    base["route_path"] = route_path
    base["api_path"] = f"/mlb/api/season/{int(season)}/live-lens" if season is not None else "/mlb/api/live-lens"
    base["form_action"] = route_path
    base["show_app_header"] = False
    base["page_body_class"] = "cards-body syndicate-mlb-live-lens-page" + (" syndicate-mlb-live-lens-page--season" if season is not None else "")
    base["page_shell_class"] = "syndicate-mlb-live-lens-shell"
    return attach_live_lens_contract(apply_game_board_contract(base, sport="mlb", module="live_lens"), sport="mlb", module="live_lens")


def _snapshot_api_payload(selected_date: str, *, season: int | None = None, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    page_context = _snapshot_route_context(selected_date, season=season, snapshot=snapshot)
    games = _snapshot_games(snapshot or {}) if isinstance(snapshot, dict) else []
    counts = dict(page_context.get("counts") or {})
    refreshed_at = page_context.get("odds_refreshed_at") or page_context.get("oddsRefreshedAt") or page_context.get("generatedAt")
    return {
        "date": page_context.get("date") or selected_date,
        "requested_date": page_context.get("requested_date", page_context.get("date", selected_date)),
        "season": page_context.get("season", season),
        "games": games,
        "counts": counts,
        "generatedAt": page_context.get("generatedAt"),
        "odds_refreshed_at": refreshed_at,
        "oddsRefreshedAt": refreshed_at,
        "dataRoot": page_context.get("dataRoot"),
        "liveLensDir": page_context.get("liveLensDir"),
        "source_path": page_context.get("source_path"),
        "source_title": page_context.get("source_title"),
        "using_sample_data": bool(page_context.get("using_sample_data", False)),
    }


def read_latest_live_lens_snapshot() -> dict[str, Any] | None:
    snapshot = read_json_file(live_lens_snapshot_path())
    return dict(snapshot) if isinstance(snapshot, dict) else None


def _snapshot_generated_at_age_seconds(snapshot: dict[str, Any] | None) -> float | None:
    generated_at = str((snapshot or {}).get("generatedAt") or "").strip()
    if not generated_at:
        return None
    try:
        parsed = datetime.fromisoformat(generated_at)
    except Exception:
        return None
    try:
        now = datetime.now(parsed.tzinfo) if parsed.tzinfo is not None else datetime.now()
        return max(0.0, (now - parsed).total_seconds())
    except Exception:
        return None


def _live_lens_snapshot_needs_refresh(selected_date: str, snapshot: dict[str, Any] | None) -> bool:
    if str(selected_date).strip() != central_today_iso():
        return False
    if not bool(_snapshot_games(snapshot or {})):
        return True
    # 2026-07-29 (#124): this used to defer to _live_lens_report_needs_refresh
    # unconditionally, but that measures the REPORT FILE's own mtime on THIS
    # process's disk (reset every time pull_hot_artifacts re-fetches it), not
    # when the snapshot's own content was actually generated. With a 60s
    # max-age tighter than a refresh-worker candidate-pool cycle (measured
    # 60-90s+), that check evaluated stale on nearly every cycle, discarding
    # a snapshot that had just been read fresh from the shared keyvalue store
    # (written by live-odds-worker's dedicated live-lens loop, with real
    # liveProps) and replacing it with a from-scratch local recompute that
    # structurally carries the same liveProps/archivedLiveProps keys but
    # never actually populates them -- confirmed live: refresh-worker's
    # recompute had prop_row_counts=[0]*9 across 9 real live games while
    # web's own snapshot had 24/18/16 real rows for 3 of them, unchanged
    # even after fixing two other artifact-distribution gaps in the same
    # investigation. Trust the already-read snapshot's own generatedAt when
    # present -- it reflects when the actual source of truth (live-odds-
    # worker) generated it, not an unrelated file's local pull history --
    # and only fall back to the report-file proxy when the snapshot doesn't
    # carry one at all (e.g. an old cached shape from before this field
    # existed).
    content_age_seconds = _snapshot_generated_at_age_seconds(snapshot)
    if content_age_seconds is not None:
        return content_age_seconds > float(_live_lens_report_max_age_seconds())
    return _live_lens_report_needs_refresh(selected_date)


def read_latest_live_lens_page_context(selected_date: str, *, season: int | None = None) -> dict[str, Any]:
    snapshot = read_latest_live_lens_snapshot()
    if _live_lens_snapshot_needs_refresh(selected_date, snapshot):
        fresh_snapshot = build_live_lens_snapshot_internal(selected_date, season=season, persist=False)
        if isinstance(fresh_snapshot, dict):
            snapshot = fresh_snapshot
    if snapshot is None:
        return _snapshot_route_context(selected_date, season=season, snapshot=None)
    return _snapshot_route_context(selected_date, season=season, snapshot=snapshot)


def read_latest_live_lens_api_payload(selected_date: str, *, season: int | None = None) -> dict[str, Any]:
    snapshot = read_latest_live_lens_snapshot()
    if _live_lens_snapshot_needs_refresh(selected_date, snapshot):
        fresh_snapshot = build_live_lens_snapshot_internal(selected_date, season=season, persist=False)
        if isinstance(fresh_snapshot, dict):
            snapshot = fresh_snapshot
    if snapshot is None:
        return _snapshot_api_payload(selected_date, season=season, snapshot=None)
    api_payload = snapshot.get("api_payload") if isinstance(snapshot.get("api_payload"), dict) else None
    if api_payload is None:
        return _snapshot_api_payload(selected_date, season=season, snapshot=snapshot)
    payload = dict(api_payload)
    payload.setdefault("date", selected_date)
    payload.setdefault("requested_date", selected_date)
    payload.setdefault("season", season)
    payload.setdefault("games", [])
    payload.setdefault("counts", {})
    payload.setdefault("using_sample_data", False)
    return payload


def build_live_lens_snapshot_internal(selected_date: str, *, season: int | None = None, persist: bool = False) -> dict[str, Any]:
    # Intended as a worker-only compute function (live-odds-worker's
    # live_lens_loop tick), but reachable in-request as a cache-miss
    # fallback from read_latest_live_lens_page_context/api_payload -- same
    # shape as wnba/live_lens.py's build_live_lens_page_context. The one
    # genuinely heavy piece (the vendored Monte Carlo live re-sim) is hard-
    # refused inside a real web request via
    # _live_projection_enhancement_payload -> refuse_if_compute_in_request_path
    # (#124 follow-up (b)); this function's own remaining work is the cheap
    # card-artifact read, same cost class as WNBA's request-path fallback.
    from syndicate.features.shared.request_path_guard import warn_if_compute_in_request_path

    warn_if_compute_in_request_path("build_live_lens_snapshot_internal")
    parsed_date = parse_iso_date(selected_date)
    prev_date = parsed_date.fromordinal(parsed_date.toordinal() - 1).isoformat()
    next_date = parsed_date.fromordinal(parsed_date.toordinal() + 1).isoformat()

    report_path = live_lens_report_path(selected_date)
    should_refresh_report = bool(persist or _live_lens_report_needs_refresh(selected_date))
    # _persist_live_lens_report already builds cards-primary (#124 follow-up
    # (a)) with the vendor MC/rich-live-actuals enhancement layered on top
    # when it actually refreshes; a report loaded from disk (not stale, per
    # the max-age check above) was written by that same composition on a
    # prior call/tick, so no separate re-freshen pass is needed here -- one
    # was tried and reverted, since it would have overwritten the rich
    # per-prop actuals with a cheap plain-cards rebuild on every read.
    report = _persist_live_lens_report(selected_date) if should_refresh_report else load_json_file(report_path)
    if not isinstance(report, dict) or not isinstance(report.get("games"), list) or not report.get("games"):
        fallback_report = _cards_backed_live_lens_report(selected_date)
        if fallback_report is not None:
            report = fallback_report
    runtime_live_lens_dir = str(report_path.parent)
    runtime_data_root = str(report_path.parent.parent)
    generated_at = str((report or {}).get("generatedAt") or datetime.now().astimezone().isoformat(timespec="seconds")).strip() or selected_date
    rows = (report or {}).get("games") if isinstance((report or {}).get("games"), list) else []
    games = [_game_from_report_row(row, report_date=selected_date, generated_at=generated_at) for row in rows if isinstance(row, dict)]
    if games:
        games = [dict(game) for game in games if isinstance(game, dict)][:50]
    persisted_counts = {
        "games": len(games),
        "live": sum(1 for game in games if _status_bucket_from_row(game) == "live"),
        "final": sum(1 for game in games if _status_bucket_from_row(game) == "final"),
        "pregame": sum(1 for game in games if _status_bucket_from_row(game) == "pregame"),
        "props": sum(len(game.get("liveProps") or game.get("props") or game.get("trackedProps") or []) for game in games),
        "archivedLiveProps": 0,
    }
    if persist and games:
        persisted_games = [dict(game) for game in games if isinstance(game, dict)]
        persisted_report = dict(report or {})
        persisted_report.update({
            "date": str(selected_date),
            "generatedAt": generated_at,
            "oddsRefreshedAt": persisted_report.get("oddsRefreshedAt") or persisted_report.get("odds_refreshed_at"),
            "odds_refreshed_at": persisted_report.get("oddsRefreshedAt") or persisted_report.get("odds_refreshed_at"),
            "dataRoot": runtime_data_root,
            "liveLensDir": runtime_live_lens_dir,
            "counts": dict(persisted_counts),
            "games": persisted_games,
            "source_title": str((persisted_report.get("source_title") or "MLB live-lens report artifact")).strip() or "MLB live-lens report artifact",
            "source_path": str(report_path),
        })
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(persisted_report, indent=2), encoding="utf-8")
            report = persisted_report
        except Exception:
            pass
    page_context = apply_game_board_contract({
        "season": season,
        "date": selected_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "module_links": build_module_links(selected_date, "Live lens"),
        "games": games,
        "scoreboard_items": [
            {
                "target_id": f"game-{game.get('gamePk')}",
                "label": f"{((game.get('away') or {}).get('abbr') or 'AWY')} @ {((game.get('home') or {}).get('abbr') or 'HOM')}",
                "status": game.get("status"),
            }
            for game in games
            if isinstance(game, dict)
        ],
        "source_path": str(report_path),
        "using_sample_data": False,
        "odds_refreshed_at": (report or {}).get("oddsRefreshedAt") or (report or {}).get("odds_refreshed_at"),
        "oddsRefreshedAt": (report or {}).get("oddsRefreshedAt") or (report or {}).get("odds_refreshed_at"),
        "source_title": "MLB live-lens report artifact" if games else "MLB live lens unavailable",
        "generatedAt": generated_at,
        "counts": persisted_counts,
        "app": (report or {}).get("app") if isinstance((report or {}).get("app"), dict) else {},
        "dataRoot": runtime_data_root,
        "liveLensDir": runtime_live_lens_dir,
        "optimizationRegime": (report or {}).get("optimizationRegime"),
        "performance": (report or {}).get("performance") if isinstance((report or {}).get("performance"), dict) else {},
        "header_stats": [
            {"label": "Games", "value": str(persisted_counts.get("games") or len(games))},
            {"label": "Live", "value": str(persisted_counts.get("live") or 0)},
            {"label": "Final", "value": str(persisted_counts.get("final") or 0)},
            {"label": "Props", "value": str(persisted_counts.get("props") or 0)},
        ],
        "empty_state": {
            "eyebrow": "MLB live lens",
            "title": "No live-lens games were available for this date",
            "body": "The live-lens report for this date did not surface any tracked games or live props.",
            "list_items": [
                f"Requested date: {selected_date}",
                f"Report artifact: {report_path.name}",
            ],
        } if not games else None,
        "route_path": f"/mlb/season/{int(season)}/live-lens" if season is not None else "/mlb/live-lens",
        "intro_title": f"MLB {int(season)} Live Lens" if season is not None else "MLB Live Lens",
        "intro_body": (
            "This first Syndicate live-lens pass reads the committed MLB live-lens report artifact and turns each game snapshot into the shared game-card surface, instead of leaving the old MLB live monitor outside the migration path."
        ),
        "cards_grid_class": "mlb-cards-grid",
        "cards_stylesheet": "mlb/cards.css",
        "teaser": {
            "label": "Related MLB board",
            "body": "Use the MLB cards board to compare the pregame slate against this live-lens snapshot.",
            "href": f"/mlb/cards?date={selected_date}",
            "cta": "Open cards",
        },
    }, sport="mlb", module="live_lens")
    page_context = attach_live_lens_contract(page_context, sport="mlb", module="live_lens")
    games = [dict(game) for game in (page_context.get("games") if isinstance(page_context.get("games"), list) else []) if isinstance(game, dict)][:50]
    page_context = dict(page_context)
    page_context["games"] = games
    page_context["scoreboard_items"] = [dict(item) for item in (page_context.get("scoreboard_items") if isinstance(page_context.get("scoreboard_items"), list) else []) if isinstance(item, dict)][:50]
    page_context["counts"] = _snapshot_counts(games)
    page_context["header_stats"] = [
        {"label": "Games", "value": str(len(games))},
        {"label": "Live", "value": str(page_context["counts"].get("live") or 0)},
        {"label": "Final", "value": str(page_context["counts"].get("final") or 0)},
        {"label": "Props", "value": str(page_context["counts"].get("props") or 0)},
    ]
    api_payload = _snapshot_api_payload(selected_date, season=season, snapshot={"games": games, "page_context": page_context})
    snapshot = {
        "ok": True,
        "date": page_context.get("date") or selected_date,
        "requested_date": selected_date,
        "generatedAt": page_context.get("generatedAt") or datetime.now().astimezone().isoformat(timespec="seconds"),
        "odds_refreshed_at": page_context.get("odds_refreshed_at") or page_context.get("oddsRefreshedAt"),
        "source_path": page_context.get("source_path") or str(live_lens_snapshot_path()),
        "page_context": page_context,
        "api_payload": api_payload,
        "games": games,
        "scoreboard_items": [dict(item) for item in (page_context.get("scoreboard_items") if isinstance(page_context.get("scoreboard_items"), list) else []) if isinstance(item, dict)][:50],
        "counts": dict(page_context.get("counts") or {}),
        "source_title": page_context.get("source_title"),
        "dataRoot": page_context.get("dataRoot"),
        "liveLensDir": page_context.get("liveLensDir"),
    }
    return snapshot
