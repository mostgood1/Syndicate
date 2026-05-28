from __future__ import annotations

from datetime import datetime
from typing import Any

from syndicate.features.mlb.cards import build_cards_page_context
from syndicate.features.shared.game_board_contract import apply_game_board_contract
from syndicate.features.mlb.ladders_common import build_module_links
from syndicate.features.mlb.ladders_common import format_num
from syndicate.features.mlb.ladders_common import format_pct
from syndicate.features.mlb.ladders_common import parse_iso_date
from syndicate.features.mlb.sources import live_lens_report_path
from syndicate.features.mlb.sources import load_json_file


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
    if not abstract:
        if any(token in lowered for token in ("live", "in progress", "manager challenge", "warmup")):
            abstract = "Live"
        elif any(token in lowered for token in ("final", "game over", "completed early")):
            abstract = "Final"
        elif detailed:
            abstract = detailed
        else:
            abstract = "Pregame"
    if not detailed:
        detailed = abstract or fallback_date
    return {
        "abstract": abstract,
        "detailed": detailed,
    }


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


def _game_from_report_row(row: dict[str, Any], *, report_date: str, generated_at: str) -> dict[str, Any]:
    matchup = row.get("matchup") if isinstance(row.get("matchup"), dict) else {}
    away = matchup.get("away") if isinstance(matchup.get("away"), dict) else {}
    home = matchup.get("home") if isinstance(matchup.get("home"), dict) else {}
    status = _structured_status(row, fallback_date=report_date)
    summary = str(matchup.get("liveText") or "Live-lens snapshot loaded from artifact.").strip() or "Live-lens snapshot loaded from artifact."
    live_props = row.get("liveProps") if isinstance(row.get("liveProps"), list) else []
    return {
        "archivedLiveProps": row.get("archivedLiveProps") if isinstance(row.get("archivedLiveProps"), list) else [],
        "gameLens": _lens_rows(row),
        "gameMarkets": row.get("gameMarkets") if isinstance(row.get("gameMarkets"), dict) else {},
        "gamePk": int(row.get("gamePk") or 0),
        "liveProps": live_props,
        "matchup": matchup,
        "predictions": row.get("predictions") if isinstance(row.get("predictions"), dict) else {},
        "props": row.get("props") if isinstance(row.get("props"), list) else [],
        "simContextAvailable": bool(row.get("simContextAvailable")),
        "snapshotAvailable": bool(row.get("snapshotAvailable")),
        "startTime": str(row.get("startTime") or report_date).strip() or report_date,
        "trackedProps": row.get("trackedProps") if isinstance(row.get("trackedProps"), list) else [],
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


def build_live_lens_page_context(selected_date: str, *, season: int | None = None) -> dict[str, Any]:
    parsed_date = parse_iso_date(selected_date)
    prev_date = parsed_date.fromordinal(parsed_date.toordinal() - 1).isoformat()
    next_date = parsed_date.fromordinal(parsed_date.toordinal() + 1).isoformat()

    report_path = live_lens_report_path(selected_date)
    report = load_json_file(report_path)
    generated_at = str((report or {}).get("generatedAt") or datetime.now().astimezone().isoformat(timespec="seconds")).strip() or selected_date
    rows = (report or {}).get("games") if isinstance((report or {}).get("games"), list) else []
    games = [_game_from_report_row(row, report_date=selected_date, generated_at=generated_at) for row in rows if isinstance(row, dict)]
    fallback_cards_context: dict[str, Any] = {}
    fallback_from_cards = False
    if not games:
        fallback_cards_context = build_cards_page_context(selected_date)
        fallback_games = fallback_cards_context.get("games") if isinstance(fallback_cards_context.get("games"), list) else []
        if fallback_games:
            games = [game for game in fallback_games if isinstance(game, dict)]
            fallback_from_cards = True
    using_sample_data = False

    if fallback_from_cards:
        scoreboard_items = [
            item
            for item in (fallback_cards_context.get("scoreboard_items") or [])
            if isinstance(item, dict)
        ]
    else:
        scoreboard_items = [
            {
                "target_id": f"game-{game.get('gamePk')}",
                "label": f"{((game.get('away') or {}).get('abbr') or 'AWY')} @ {((game.get('home') or {}).get('abbr') or 'HOM')}",
                "status": game.get("status"),
            }
            for game in games
            if isinstance(game, dict)
        ]

    counts = (report or {}).get("counts") if isinstance((report or {}).get("counts"), dict) else {
        "archivedLiveProps": 0,
        "final": 0,
        "games": 0,
        "live": 0,
        "pregame": 0,
        "props": 0,
    }
    if fallback_from_cards:
        live_count = 0
        final_count = 0
        pregame_count = 0
        for game in games:
            status = game.get("status")
            if isinstance(status, dict):
                status_text = str(status.get("abstract") or status.get("detailed") or "").strip().lower()
            else:
                status_text = str(status or game.get("detail") or "").strip().lower()
            if any(token in status_text for token in ("live", "in progress", "warmup")):
                live_count += 1
            elif any(token in status_text for token in ("final", "game over", "completed")):
                final_count += 1
            else:
                pregame_count += 1
        counts = {
            "archivedLiveProps": 0,
            "final": final_count,
            "games": len(games),
            "live": live_count,
            "pregame": pregame_count,
            "props": 0,
        }
    data_root = (report or {}).get("dataRoot") or "data"
    live_lens_dir = (report or {}).get("liveLensDir") or "data/live_lens"
    route_path = f"/mlb/season/{int(season)}/live-lens" if season is not None else "/mlb/live-lens"
    intro_title = f"MLB {int(season)} Live Lens" if season is not None else "MLB Live Lens"
    intro_body = (
        "This first Syndicate live-lens pass reads the committed MLB live-lens report artifact and turns each game snapshot into the shared game-card surface, instead of leaving the old MLB live monitor outside the migration path."
    )
    teaser_href = f"/mlb/season/{int(season)}/betting-card?date={selected_date}" if season is not None else f"/mlb/cards?date={selected_date}"
    teaser_cta = "Open betting card" if season is not None else "Open cards"
    teaser_body = "Use the betting-card board for the official pregame slate, then compare it against the intraday live-lens monitor for the same date." if season is not None else "Use the MLB cards board to compare the pregame slate against this live-lens snapshot."

    return apply_game_board_contract({
        "season": season,
        "date": selected_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "module_links": build_module_links(selected_date, "Live lens"),
        "games": games,
        "scoreboard_items": scoreboard_items,
        "source_path": str(fallback_cards_context.get("source_path") or report_path) if fallback_from_cards else str(report_path),
        "using_sample_data": using_sample_data,
        "source_title": "MLB cards fallback lens" if fallback_from_cards else ("MLB live-lens report artifact" if games else "MLB live lens unavailable"),
        "generatedAt": generated_at,
        "counts": counts,
        "app": (report or {}).get("app") if isinstance((report or {}).get("app"), dict) else {},
        "dataRoot": data_root,
        "liveLensDir": live_lens_dir,
        "optimizationRegime": (report or {}).get("optimizationRegime"),
        "performance": (report or {}).get("performance") if isinstance((report or {}).get("performance"), dict) else {},
        "header_stats": [
            {"label": "Games", "value": str(counts.get("games") or len(games))},
            {"label": "Live", "value": str(counts.get("live") or 0)},
            {"label": "Final", "value": str(counts.get("final") or 0)},
            {"label": "Props", "value": str(counts.get("props") or 0)},
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
        "route_path": route_path,
        "intro_title": intro_title,
        "intro_body": intro_body,
        "cards_grid_class": "mlb-cards-grid",
        "cards_stylesheet": "mlb/cards.css",
        "teaser": {
            "label": "Related MLB board",
            "body": teaser_body,
            "href": teaser_href,
            "cta": teaser_cta,
        },
    }, sport="mlb", module="live_lens")


def build_live_lens_api_payload(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": context.get("date"),
        "requested_date": context.get("requested_date", context.get("date")),
        "season": context.get("season"),
        "games": context.get("games") if isinstance(context.get("games"), list) else [],
        "counts": context.get("counts") if isinstance(context.get("counts"), dict) else {},
        "generatedAt": context.get("generatedAt"),
        "dataRoot": context.get("dataRoot"),
        "liveLensDir": context.get("liveLensDir"),
        "source_path": context.get("source_path"),
        "source_title": context.get("source_title"),
        "using_sample_data": bool(context.get("using_sample_data", False)),
    }