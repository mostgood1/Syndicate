"""Layer 1 market/odds inventory board, shared by NBA and WNBA.

NBA's and WNBA's `cards.py` assemble a genuinely identical per-game shape
for this purpose -- a `betting` dict (home_ml/away_ml/home_spread/
away_spread/total/p_home_win/p_away_win/p_home_cover/p_away_cover/
p_total_over/p_total_under, plus book-price fields that exist on both but
are always None in the current artifact pipeline for WNBA's spread/total
and always None for NBA's spread/total too) and a `prop_recommendations`
dict (`{"away": [...], "home": [...]}` of player/market/side/line/price/
edge/p_win entries). Only the VALUES differ per sport (confirmed via
direct research 2026-07-23), never the keys a reader needs to check, so
one row-builder serves both rather than duplicating it per sport the way
NBA/WNBA's live-hydration code already has (a divergence that has already
caused drift -- see wnba/cards.py's `_estimated_live_projection` picking
up a garbage-time factor NBA's copy never got).
"""

from __future__ import annotations

from typing import Any

from syndicate.features.shared.market_inventory import join_odds_to_sim

_PROP_MARKET_LABELS: dict[str, str] = {
    "pts": "Points",
    "reb": "Rebounds",
    "ast": "Assists",
    "threes": "Threes",
    "stl": "Steals",
    "blk": "Blocks",
    "tov": "Turnovers",
    "pra": "Pts+Reb+Ast",
    "pr": "Pts+Reb",
    "pa": "Pts+Ast",
    "ra": "Reb+Ast",
    "dd": "Double-Double",
    "td": "Triple-Double",
}

# The raw OddsAPI feed (scripts/fetch_basketball_oddsapi_props_local.py's
# DEFAULT_MARKETS, e.g. "player_points") uses full words; the
# recommendation engine's own prop_recommendations entries already use the
# short codes above (confirmed via direct research 2026-07-23). Map one to
# the other so both sources produce the same label for the same stat.
_ODDSAPI_STAT_ALIASES: dict[str, str] = {
    "points": "pts",
    "rebounds": "reb",
    "assists": "ast",
    "threes": "threes",
    "steals": "stl",
    "blocks": "blk",
    "turnovers": "tov",
    "points_rebounds_assists": "pra",
    "points_rebounds": "pr",
    "points_assists": "pa",
    "rebounds_assists": "ra",
    "double_double": "dd",
    "triple_double": "td",
}

_DISPLAY_LABELS: dict[str, str] = {
    "moneyline_home": "Moneyline",
    "moneyline_away": "Moneyline",
    "spread_home": "Spread",
    "spread_away": "Spread",
    "total": "Total",
}


def _canonical_stat_code(market: Any) -> str:
    """Normalizes either vocabulary (recommendation-engine short codes like
    "pts", or the raw OddsAPI feed's full words like "points") to the SAME
    short code, so dedup/coverage comparisons between the two sources
    actually match on the same real-world stat.
    """
    key = str(market or "").strip().lower()
    return _ODDSAPI_STAT_ALIASES.get(key, key)


def _prop_display_market(market: Any) -> str:
    key = _canonical_stat_code(market)
    if key in _PROP_MARKET_LABELS:
        return _PROP_MARKET_LABELS[key]
    tokens = [token.capitalize() for token in key.replace("_", " ").split()]
    return " ".join(tokens) or "Prop"


def _prop_join_market_key(market_label: str, normalized_entity: str) -> str:
    """Disambiguates the JOIN key by player identity -- basketball props
    have no reliable single-slot concept the way MLB's starting pitcher
    does, so every player gets their own slot. Without this, two different
    players sharing a stat (e.g. both have a Points prop) would falsely
    trigger market_inventory's needs-resim cross-entity check the moment an
    independent raw odds source is joined against the recommendation
    engine's sim rows -- confirmed as a real bug for MLB's equivalent hitter
    props this session (56 false positives on one real slate) before this
    same fix was applied there.
    """
    return f"{market_label}::{normalized_entity}"


def parse_raw_basketball_player_props_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """Aggregate the raw OddsAPI player-props feed
    (scripts/fetch_basketball_oddsapi_props_local.py's flat CSV -- one row
    per bookmaker/market/Over-or-Under outcome: player_name/market/
    outcome_name/point/price) into the same {normalized_player: {stat:
    {line, over_odds, under_odds}}} shape MLB's raw pitcher/hitter props
    artifacts already use, so the same merge logic in
    basketball_market_board_rows_for_game serves both sports.

    Multiple bookmakers may quote the same (player, market) -- this takes
    the first Over/Under price seen per group rather than reconciling a
    bookmaker consensus, a deliberate simplification for this first pass.
    """
    aggregated: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        player_name = str(row.get("player_name") or "").strip()
        if not player_name:
            continue
        normalized = _canonical_player_key(player_name)
        market_key = str(row.get("market") or "").strip().lower()
        stat = market_key[len("player_"):] if market_key.startswith("player_") else market_key
        if not stat:
            continue
        outcome = str(row.get("outcome_name") or "").strip().lower()
        if outcome not in ("over", "under"):
            continue
        entry = aggregated.setdefault(normalized, {}).setdefault(stat, {"line": None, "over_odds": None, "under_odds": None})
        point = row.get("point")
        if entry["line"] is None and point is not None:
            entry["line"] = point
        if outcome == "over" and entry["over_odds"] is None:
            entry["over_odds"] = row.get("price")
        elif outcome == "under" and entry["under_odds"] is None:
            entry["under_odds"] = row.get("price")
    return aggregated


def basketball_game_state(game: dict[str, Any]) -> str:
    """NBA's `status` is a bare string ("Final"/"Live"/"Scheduled");
    WNBA's is a dict carrying the same vocabulary under "status". Handle
    both without needing to know which sport produced the row.
    """
    status = game.get("status") if isinstance(game, dict) else None
    if isinstance(status, dict):
        status_text = str(status.get("status") or status.get("abstract") or status.get("detail") or "").strip().lower()
    else:
        status_text = str(status or "").strip().lower()
    if status_text == "final":
        return "final"
    if status_text == "live":
        return "live"
    return "pregame"


def basketball_market_board_rows_for_game(
    *,
    game_pk: Any,
    betting: dict[str, Any] | None,
    prop_recommendations: dict[str, Any] | None,
    raw_player_props: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    odds_rows: list[dict[str, Any]] = []
    sim_rows: list[dict[str, Any]] = []
    betting = betting if isinstance(betting, dict) else {}

    home_ml = betting.get("home_ml")
    away_ml = betting.get("away_ml")
    p_home_win = betting.get("p_home_win")
    p_away_win = betting.get("p_away_win")
    if away_ml is not None:
        odds_rows.append({"game_id": game_pk, "market": "moneyline_away", "period": "full_game", "entity": None, "side": "away", "odds": away_ml, "market_type": "game"})
    if home_ml is not None:
        odds_rows.append({"game_id": game_pk, "market": "moneyline_home", "period": "full_game", "entity": None, "side": "home", "odds": home_ml, "market_type": "game"})
    if p_away_win is not None:
        sim_rows.append({"game_id": game_pk, "market": "moneyline_away", "period": "full_game", "entity": None, "sim_projection": p_away_win, "sim_source": "basketball_sim"})
    if p_home_win is not None:
        sim_rows.append({"game_id": game_pk, "market": "moneyline_home", "period": "full_game", "entity": None, "sim_projection": p_home_win, "sim_source": "basketball_sim"})

    # Spread/total book prices are always None in the current artifact
    # pipeline for both sports (confirmed via direct research 2026-07-23:
    # game_cards_{date}.csv never carries them) -- only add a row when a
    # real price shows up, rather than fabricating standard juice.
    home_spread = betting.get("home_spread")
    away_spread = betting.get("away_spread")
    home_spread_price = betting.get("home_spread_price")
    away_spread_price = betting.get("away_spread_price")
    p_home_cover = betting.get("p_home_cover")
    p_away_cover = betting.get("p_away_cover")
    if away_spread_price is not None:
        odds_rows.append({"game_id": game_pk, "market": "spread_away", "period": "full_game", "entity": None, "side": "away", "line": away_spread, "odds": away_spread_price, "market_type": "game"})
    if home_spread_price is not None:
        odds_rows.append({"game_id": game_pk, "market": "spread_home", "period": "full_game", "entity": None, "side": "home", "line": home_spread, "odds": home_spread_price, "market_type": "game"})
    if away_spread_price is not None and p_away_cover is not None:
        sim_rows.append({"game_id": game_pk, "market": "spread_away", "period": "full_game", "entity": None, "sim_projection": p_away_cover, "sim_source": "basketball_sim"})
    if home_spread_price is not None and p_home_cover is not None:
        sim_rows.append({"game_id": game_pk, "market": "spread_home", "period": "full_game", "entity": None, "sim_projection": p_home_cover, "sim_source": "basketball_sim"})

    total = betting.get("total")
    over_price = betting.get("total_over_price")
    under_price = betting.get("total_under_price")
    p_over = betting.get("p_total_over")
    p_under = betting.get("p_total_under")
    if over_price is not None:
        odds_rows.append({"game_id": game_pk, "market": "total", "period": "full_game", "entity": None, "side": "over", "line": total, "odds": over_price, "market_type": "game"})
    if under_price is not None:
        odds_rows.append({"game_id": game_pk, "market": "total", "period": "full_game", "entity": None, "side": "under", "line": total, "odds": under_price, "market_type": "game"})
    if over_price is not None and p_over is not None:
        sim_rows.append({"game_id": game_pk, "market": "total", "period": "full_game", "entity": None, "sim_projection": p_over, "sim_source": "basketball_sim"})
    if under_price is not None and p_under is not None:
        sim_rows.append({"game_id": game_pk, "market": "total", "period": "full_game", "entity": None, "sim_projection": p_under, "sim_source": "basketball_sim"})

    # "market" on prop rows is the disambiguated join key
    # (_prop_join_market_key) -- build_basketball_market_board relabels it
    # back to the clean display label after join_odds_to_sim runs.
    raw_player_props = raw_player_props if isinstance(raw_player_props, dict) else {}
    prop_recommendations = prop_recommendations if isinstance(prop_recommendations, dict) else {}
    recommended_props_by_entity: dict[str, dict[str, dict[str, Any]]] = {}
    for entries in (prop_recommendations.get("away"), prop_recommendations.get("home")):
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            player = str(entry.get("player") or "").strip()
            selection = str(entry.get("side") or "").strip().lower()
            if not player or selection not in ("over", "under"):
                continue
            market_label = _prop_display_market(entry.get("market"))
            line = entry.get("line")
            odds = entry.get("price")
            # No official/candidate tier split exists in this feed (its
            # "tier" field is a confidence label like "High", not
            # official-vs-extra) and, like MLB props, odds and model
            # confidence come from the same recommendation row -- so
            # p_win (model win prob for the picked side) is the best
            # available "sim" signal, falling back to edge if p_win is
            # absent.
            confidence = entry.get("p_win") if entry.get("p_win") is not None else entry.get("edge")
            normalized_entity = _canonical_player_key(player)

            recommended_props_by_entity.setdefault(player, {})[_canonical_stat_code(entry.get("market"))] = {
                "market_label": market_label,
                "line": line,
                "odds": odds,
                "side": selection,
            }
            if confidence is not None:
                sim_rows.append(
                    {
                        "game_id": game_pk,
                        "market": _prop_join_market_key(market_label, normalized_entity),
                        "period": "full_game",
                        "entity": player,
                        "sim_projection": confidence,
                        "sim_source": "basketball_recommendation_engine",
                    }
                )

    # Raw OddsAPI feed -- the true book-odds source, when we can attribute
    # a player to this game. Basketball has no "probable pitcher"
    # equivalent, so attribution is purely via existing recommendation
    # coverage: a player with genuinely zero recommendation-engine coverage
    # today has no roster signal to attribute them by, so they're not
    # surfaced yet -- the same bounded limitation MLB's hitter props have.
    covered_entity_stats: set[tuple[str, str]] = set()
    for player in recommended_props_by_entity:
        normalized_entity = _canonical_player_key(player)
        player_markets = raw_player_props.get(normalized_entity)
        if not isinstance(player_markets, dict):
            continue
        for stat_key, market in player_markets.items():
            if not isinstance(market, dict):
                continue
            line = market.get("line")
            over_odds = market.get("over_odds")
            under_odds = market.get("under_odds")
            market_label = _prop_display_market(stat_key)
            join_key = _prop_join_market_key(market_label, normalized_entity)
            if over_odds is not None:
                odds_rows.append({"game_id": game_pk, "market": join_key, "period": "full_game", "entity": player, "side": "over", "line": line, "odds": over_odds, "market_type": "prop"})
            if under_odds is not None:
                odds_rows.append({"game_id": game_pk, "market": join_key, "period": "full_game", "entity": player, "side": "under", "line": line, "odds": under_odds, "market_type": "prop"})
            covered_entity_stats.add((normalized_entity, _canonical_stat_code(stat_key)))

    for player, props in recommended_props_by_entity.items():
        normalized_entity = _canonical_player_key(player)
        for stat_key, info in props.items():
            if (normalized_entity, stat_key) in covered_entity_stats:
                continue
            odds_rows.append(
                {
                    "game_id": game_pk,
                    "market": _prop_join_market_key(info["market_label"], normalized_entity),
                    "period": "full_game",
                    "entity": player,
                    "side": info["side"],
                    "line": info["line"],
                    "odds": info["odds"],
                    "market_type": "prop",
                }
            )

    return odds_rows, sim_rows


def _canonical_player_key(value: Any) -> str:
    return str(value or "").strip().casefold()


def _live_prop_key(player: Any, market_label: Any) -> tuple[str, str]:
    return (_canonical_player_key(player), str(market_label or "").strip().casefold())


def live_rows_by_event_id(live_player_lens_payload: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Reshape a `/api/live_player_lens`-style payload
    (`{"games": [{"event_id", "rows": [...]}]}`) into `{event_id: rows}`
    for O(1) lookup while building the board."""
    result: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(live_player_lens_payload, dict):
        return result
    games = live_player_lens_payload.get("games")
    if not isinstance(games, list):
        return result
    for game in games:
        if not isinstance(game, dict):
            continue
        event_id = str(game.get("event_id") or "").strip()
        rows = game.get("rows")
        if event_id and isinstance(rows, list):
            result[event_id] = rows
    return result


def hydrate_live_prop_rows(inventory: list[dict[str, Any]], live_rows: list[dict[str, Any]] | None) -> None:
    """Overlay live_projection/live_actual onto this game's already-joined
    prop rows in place, matched by (player, stat). NBA/WNBA's
    live_player_lens rows already carry a stable per-event stat code
    (unlike MLB's market/line fuzzy match), so an exact (player, display
    label) match is enough -- no need to fuzzy-match names or lines.
    """
    if not live_rows:
        return
    live_index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in live_rows:
        if not isinstance(row, dict):
            continue
        player = row.get("player")
        if not player:
            continue
        stat_label = _prop_display_market(row.get("stat"))
        live_index[_live_prop_key(player, stat_label)] = row

    for row in inventory:
        if row.get("market_type") != "prop":
            continue
        match = live_index.get(_live_prop_key(row.get("entity"), row.get("market")))
        if match is None:
            continue
        live_projection = match.get("live_projection")
        if live_projection is None:
            live_projection = match.get("liveProjection")
        actual = match.get("actual")
        if live_projection is not None:
            row["live_projection"] = live_projection
        if actual is not None:
            row["live_actual"] = actual


def build_basketball_market_board(
    *,
    sport_slug: str,
    selected_date: str,
    games: list[dict[str, Any]],
    live_player_lens_payload: dict[str, Any] | None = None,
    raw_player_props: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    live_by_event = live_rows_by_event_id(live_player_lens_payload)
    board_games: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        game_pk = game.get("gamePk") or game.get("game_id")
        event_id = str(game.get("event_id") or game_pk or "").strip()
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        away_abbr = str(away.get("abbr") or game.get("away_tri") or "AWY").strip().upper()
        home_abbr = str(home.get("abbr") or game.get("home_tri") or "HME").strip().upper()
        betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
        prop_recommendations = game.get("prop_recommendations") if isinstance(game.get("prop_recommendations"), dict) else {}

        odds_rows, sim_rows = basketball_market_board_rows_for_game(
            game_pk=game_pk, betting=betting, prop_recommendations=prop_recommendations, raw_player_props=raw_player_props
        )
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        for row in inventory:
            market = row.get("market")
            if row.get("market_type") == "prop" and isinstance(market, str) and "::" in market:
                # Prop rows carry a disambiguated join key
                # (_prop_join_market_key) so needs-resim detection can't
                # misfire across different players who share a stat --
                # strip it back to the clean label for display.
                market = market.split("::", 1)[0]
            row["market"] = _DISPLAY_LABELS.get(market, market)
        if event_id in live_by_event:
            hydrate_live_prop_rows(inventory, live_by_event[event_id])

        board_games.append(
            {
                "gamePk": game_pk,
                "event_id": event_id,
                "matchup": f"{away_abbr} @ {home_abbr}",
                "away_abbr": away_abbr,
                "home_abbr": home_abbr,
                "game_state": basketball_game_state(game),
                "detail": game.get("detail"),
                "startTime": game.get("startTime") or game.get("start_time"),
                "rows": inventory,
            }
        )

    return {"sport": sport_slug, "date": selected_date, "games": board_games}
