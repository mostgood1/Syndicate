"""Layer 1 market/odds inventory for soccer -- one board per league, built
the same way as syndicate/features/mlb/cards.py's build_mlb_market_board:
raw odds rows joined against SoccerSim's projections via the shared
market_inventory.join_odds_to_sim contract, so every quoted line shows up
regardless of whether SoccerSim has coverage for it.

Soccer's board is WEEK-scoped, not single-date-scoped like MLB/NBA/WNBA
(2026-07-24 fix -- soccer's own cards/props pages already think in game
weeks, and its raw odds feed is a single rolling "current odds" file that
captures every upcoming event across the whole week at once, days ahead of
kickoff, not one day at a time). A single `selected_date`'s own
recommendations_{date}.json snapshot can legitimately be empty/stale even
when an adjacent date's snapshot already has real data for that same
match (confirmed in production: recommendations_2026-07-23.json had 0
matches while recommendations_2026-07-22.json's own snapshot already
covered both 07-22 and 07-23 kickoffs) -- so matches are aggregated across
every available snapshot date in a window around selected_date, not read
from a single file.

Kept as its own module rather than folded into cards.py: cards.py's
week-scoped context-building already re-derives week/season from a
schedule artifact for its own (different) rendering needs; this module
only needs recommendations_payload's per-match sim fields
(win_probability/total_distribution/top_props), which is simpler to
aggregate directly across dates than to route through cards.py's
week-object machinery.
"""

from __future__ import annotations

from datetime import date, timedelta
import unicodedata
from typing import Any

from syndicate.features.shared.market_inventory import join_odds_to_sim
from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport
from syndicate.features.shared.odds_control_plane import resolve_current_shard_key
from syndicate.features.soccer.sources import available_dates
from syndicate.features.soccer.sources import default_season
from syndicate.features.soccer.sources import game_odds_rows
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.soccer.sources import props_odds_rows
from syndicate.features.soccer.sources import recommendations_payload
from syndicate.features.soccer.sources import roster_rows
from syndicate.features.soccer.sources import team_by_name


# How many days around the selected date to aggregate matches/props from --
# wide enough to comfortably cover a full MLS game week (typically 3-4
# match days) plus some lookahead for "odds days ahead of kickoff", without
# scanning a league's entire season history on every board request.
_WEEK_LOOKBACK_DAYS = 3
_WEEK_LOOKAHEAD_DAYS = 10


def _soccer_relevant_dates(league: str, selected_date: str) -> list[str]:
    try:
        base = date.fromisoformat(selected_date)
    except ValueError:
        return [selected_date]
    window = {
        (base + timedelta(days=offset)).isoformat()
        for offset in range(-_WEEK_LOOKBACK_DAYS, _WEEK_LOOKAHEAD_DAYS + 1)
    }
    available = set(available_dates(league))
    relevant = sorted(window & available)
    return relevant or [selected_date]


def _soccer_week_matches(league: str, selected_date: str) -> list[dict[str, Any]]:
    """Every match known across recommendations snapshots near
    selected_date, deduped by event_id. Dates are scanned oldest-to-newest
    so a later (fresher) snapshot's version of a match overwrites an
    earlier one rather than the reverse.
    """
    matches_by_event: dict[str, dict[str, Any]] = {}
    for date_str in _soccer_relevant_dates(league, selected_date):
        payload = recommendations_payload(league, date_str) or {}
        matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
        for match in matches:
            if not isinstance(match, dict):
                continue
            event_id = str(match.get("event_id") or match.get("match_id") or "").strip()
            if event_id:
                matches_by_event[event_id] = match
    return list(matches_by_event.values())


def _soccer_week_props_rows(league: str, selected_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for date_str in _soccer_relevant_dates(league, selected_date):
        rows.extend(dict(row) for row in props_odds_rows(league, date_str))
    return rows


_GAME_STATE_BY_STATUS = {"pre": "pregame", "in": "live", "post": "final"}

# Only markets where SoccerSim exposes a genuine 0-1 probability (not a raw
# projected count) are wired to sim_projection -- the board's frontend
# formats sim_projection as a percentage uniformly across every sport, so a
# raw expected-count value (e.g. expected_shots_on_target) would render as
# a nonsensical percentage. Shots/shots-on-target props still appear on the
# board as real quoted lines, just correctly flagged as unmodeled
# (no_sim_coverage) rather than mis-rendered.
_PROP_MARKET_KEY_TO_TOP_PROPS_FIELD = {
    "player_goal_scorer_anytime": "anytime_scorer_probability",
}


def _normalize_soccer_name(value: Any) -> str:
    text = " ".join(str(value or "").strip().lower().split())
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _soccer_odds_history_key(row: dict[str, Any]) -> str:
    # Mirrors odds_refresh_tracking._odds_history_market_key's field order
    # exactly (event_id, home_team, away_team, market, side, book) for the
    # subset of columns a soccer game-odds row actually carries -- values
    # are NOT case-folded, matching the write side, which stores them
    # exactly as they appear in the raw CSV.
    parts: list[str] = []
    for key in ("event_id", "home_team", "away_team", "market", "side", "book"):
        value = str(row.get(key) or "").strip()
        if value:
            parts.append(f"{key}={value}")
    return "|".join(parts)


def _soccer_market_board_game_rows_for_match(
    *, event_id: str, game_odds_rows_all: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    """Raw game-market (h2h/totals/spreads) odds rows for one match.

    Multiple bookmakers quote the same market -- the first one encountered
    per (market, side) is kept (matching how build_mlb_market_board
    surfaces one representative price per market rather than every book),
    and the picked row is returned alongside so its exact "book" value can
    be reused to look up line movement for that same quote.
    """
    odds_rows: list[dict[str, Any]] = []
    picked_by_market_side: dict[tuple[str, str], dict[str, Any]] = {}
    for row in game_odds_rows_all:
        if str(row.get("event_id") or "").strip() != event_id:
            continue
        market = str(row.get("market") or "").strip().lower()
        side = str(row.get("side") or "").strip().lower()
        price = _safe_float(row.get("price"))
        if price is None:
            continue
        line = _safe_float(row.get("line"))

        if market == "h2h":
            if side not in ("home", "draw", "away"):
                continue
            board_key = ("h2h", side)
            if board_key in picked_by_market_side:
                continue
            picked_by_market_side[board_key] = row
            odds_rows.append(
                {
                    "game_id": event_id,
                    "market": f"moneyline_{side}",
                    "period": "full_game",
                    "entity": None,
                    "side": side,
                    "odds": price,
                    "market_type": "game",
                }
            )
        elif market == "totals":
            if side not in ("over", "under"):
                continue
            board_key = ("totals", side)
            if board_key in picked_by_market_side:
                continue
            picked_by_market_side[board_key] = row
            odds_rows.append(
                {
                    "game_id": event_id,
                    "market": "total",
                    "period": "full_game",
                    "entity": None,
                    "side": side,
                    "line": line,
                    "odds": price,
                    "market_type": "game",
                }
            )
        elif market == "spreads":
            if side not in ("home", "away"):
                continue
            board_key = ("spreads", side)
            if board_key in picked_by_market_side:
                continue
            picked_by_market_side[board_key] = row
            odds_rows.append(
                {
                    "game_id": event_id,
                    "market": "spread",
                    "period": "full_game",
                    "entity": None,
                    "side": side,
                    "line": line,
                    "odds": price,
                    "market_type": "game",
                }
            )
    return odds_rows, picked_by_market_side


def _soccer_market_board_sim_rows_for_match(*, event_id: str, match: dict[str, Any]) -> list[dict[str, Any]]:
    sim_rows: list[dict[str, Any]] = []
    win_probability = match.get("win_probability") if isinstance(match.get("win_probability"), dict) else {}
    for side in ("home", "draw", "away"):
        probability = win_probability.get(side)
        if probability is not None:
            sim_rows.append(
                {
                    "game_id": event_id,
                    "market": f"moneyline_{side}",
                    "period": "full_game",
                    "entity": None,
                    "sim_projection": probability,
                    "sim_source": "soccersim",
                }
            )
    total_distribution = match.get("total_distribution") if isinstance(match.get("total_distribution"), dict) else {}
    over_probability = total_distribution.get("over_2_5_probability")
    if over_probability is not None:
        sim_rows.append(
            {
                "game_id": event_id,
                "market": "total",
                "period": "full_game",
                "entity": None,
                "sim_projection": over_probability,
                "sim_source": "soccersim",
            }
        )
    return sim_rows


def _soccer_market_board_prop_rows_for_match(
    *, event_id: str, match: dict[str, Any], props_rows_all: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    odds_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in props_rows_all:
        if str(row.get("event_id") or "").strip() != event_id:
            continue
        player = str(row.get("player") or "").strip()
        market_label = str(row.get("market") or "").strip()
        if not player or not market_label:
            continue
        line = _safe_float(row.get("line"))
        over_price = _safe_float(row.get("over_price"))
        under_price = _safe_float(row.get("under_price"))
        dedupe_key = (player, market_label, str(row.get("market_key") or ""))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        if over_price is not None:
            odds_rows.append(
                {
                    "game_id": event_id,
                    "market": market_label,
                    "period": "full_game",
                    "entity": player,
                    "side": "over",
                    "line": line,
                    "odds": over_price,
                    "market_type": "prop",
                }
            )
        if under_price is not None:
            odds_rows.append(
                {
                    "game_id": event_id,
                    "market": market_label,
                    "period": "full_game",
                    "entity": player,
                    "side": "under",
                    "line": line,
                    "odds": under_price,
                    "market_type": "prop",
                }
            )

    sim_rows: list[dict[str, Any]] = []
    top_props = match.get("top_props") if isinstance(match.get("top_props"), list) else []
    for prop_row in top_props:
        if not isinstance(prop_row, dict):
            continue
        market_key = str(prop_row.get("market_key") or "").strip()
        # top_props doesn't carry the raw feed's market_key today -- the
        # only currently-wired mapping (anytime goalscorer) is looked up by
        # a dedicated probability field instead of a market_key match, so
        # this loop covers that one case explicitly rather than a generic
        # per-market_key scan.
        player_name = str(prop_row.get("player_name") or "").strip()
        if not player_name:
            continue
        anytime_probability = prop_row.get("anytime_scorer_probability")
        if anytime_probability is not None:
            sim_rows.append(
                {
                    "game_id": event_id,
                    "market": "Anytime Goalscorer",
                    "period": "full_game",
                    "entity": player_name,
                    "sim_projection": anytime_probability,
                    "sim_source": "soccersim",
                }
            )
    return odds_rows, sim_rows


def _soccer_headshot_lookup(league: str) -> dict[str, str]:
    season = default_season(league)
    lookup: dict[str, str] = {}
    for row in roster_rows(league, season):
        headshot_url = str(row.get("headshot_url") or "").strip()
        player_name = row.get("player_name")
        if headshot_url and player_name:
            lookup[_normalize_soccer_name(player_name)] = headshot_url
    return lookup


def _soccer_odds_history_payload(selected_date: str) -> dict[str, Any]:
    shard_key = resolve_current_shard_key("soccer", selected_date)
    payload = load_odds_history_payload_for_sport("soccer", shard_key)
    return payload if isinstance(payload, dict) else {}


def _soccer_hydrate_market_board_line_movement(row: dict[str, Any], entry: dict[str, Any] | None) -> None:
    if not isinstance(entry, dict):
        return
    last_line = entry.get("last_line")
    previous_line = entry.get("previous_line")
    if last_line is None and previous_line is None:
        return
    row["line_last"] = last_line
    row["line_previous"] = previous_line
    delta = entry.get("delta")
    if delta is None and last_line is not None and previous_line is not None:
        try:
            delta = float(last_line) - float(previous_line)
        except (TypeError, ValueError):
            delta = None
    row["line_delta"] = delta
    row["line_trend"] = entry.get("movement") or "flat"


def build_soccer_market_board(league: str, selected_date: str) -> dict[str, Any]:
    """Layer 1 market/odds inventory for one soccer league's current game
    week (see module docstring for why this is week- rather than
    single-date-scoped) -- game markets (moneyline/total/spread) and player
    props, joined against SoccerSim's per-match projections, sportsbook-
    style.
    """
    league = normalize_league(league)
    matches = _soccer_week_matches(league, selected_date)
    game_odds_rows_all = [dict(row) for row in game_odds_rows(league)]
    props_rows_all = _soccer_week_props_rows(league, selected_date)
    headshot_lookup = _soccer_headshot_lookup(league)
    odds_history = _soccer_odds_history_payload(selected_date)
    odds_history_markets = odds_history.get("markets") if isinstance(odds_history.get("markets"), dict) else {}

    board_games: list[dict[str, Any]] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        event_id = str(match.get("event_id") or match.get("match_id") or "").strip()
        if not event_id:
            continue
        matchup = match.get("matchup") if isinstance(match.get("matchup"), dict) else {}
        home_team = str(matchup.get("home_team") or "").strip()
        away_team = str(matchup.get("away_team") or "").strip()
        status_state = str(match.get("status_state") or "pre").strip().lower()
        game_state = _GAME_STATE_BY_STATUS.get(status_state, "pregame")

        game_odds, picked_game_rows = _soccer_market_board_game_rows_for_match(
            event_id=event_id, game_odds_rows_all=game_odds_rows_all
        )
        game_sim = _soccer_market_board_sim_rows_for_match(event_id=event_id, match=match)
        prop_odds, prop_sim = _soccer_market_board_prop_rows_for_match(
            event_id=event_id, match=match, props_rows_all=props_rows_all
        )
        inventory = join_odds_to_sim(game_odds + prop_odds, game_sim + prop_sim)

        for row in inventory:
            if row.get("market_type") == "prop":
                entity_name = row.get("entity")
                if entity_name:
                    headshot_url = headshot_lookup.get(_normalize_soccer_name(entity_name))
                    if headshot_url:
                        row["headshot_url"] = headshot_url
            elif row.get("market_type") == "game" and odds_history_markets:
                raw_market = row.get("market")
                side = row.get("side")
                market_label = {"moneyline_home": "h2h", "moneyline_draw": "h2h", "moneyline_away": "h2h", "total": "totals", "spread": "spreads"}.get(raw_market, raw_market)
                picked_row = picked_game_rows.get((market_label, side)) if market_label and side else None
                if picked_row is not None:
                    key = _soccer_odds_history_key(picked_row)
                    entry = odds_history_markets.get(key) if key else None
                    _soccer_hydrate_market_board_line_movement(row, entry)
            if row.get("market") in ("moneyline_home", "moneyline_draw", "moneyline_away"):
                row["market"] = "Moneyline"
            elif row.get("market") == "total":
                row["market"] = "Total"
            elif row.get("market") == "spread":
                row["market"] = "Spread"

        away_logo = None
        home_logo = None
        if away_team:
            away_directory = team_by_name(league, away_team)
            away_logo = str(away_directory.get("logo_url") or "").strip() or None if away_directory else None
        if home_team:
            home_directory = team_by_name(league, home_team)
            home_logo = str(home_directory.get("logo_url") or "").strip() or None if home_directory else None

        board_games.append(
            {
                "gamePk": event_id,
                "matchup": f"{away_team} @ {home_team}" if away_team and home_team else event_id,
                "away_abbr": away_team,
                "home_abbr": home_team,
                "away_logo": away_logo,
                "home_logo": home_logo,
                "game_state": game_state,
                "startTime": match.get("kickoff"),
                "rows": inventory,
            }
        )

    return {
        "date": selected_date,
        "league": league,
        "games": board_games,
    }
