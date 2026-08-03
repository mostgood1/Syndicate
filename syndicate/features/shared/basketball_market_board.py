"""Layer 1 market/odds inventory board, shared by NBA and WNBA.

NBA's and WNBA's `cards.py` assemble a genuinely identical per-game shape
for this purpose -- a `betting` dict (home_ml/away_ml/home_spread/
away_spread/total/p_home_win/p_away_win/p_home_cover/p_away_cover/
p_total_over/p_total_under, plus book-price fields: real per-side
spread/total quotes for WNBA since 2026-08-02, still always None for NBA
until its game_cards CSV grows the same columns) and a `prop_recommendations`
dict (`{"away": [...], "home": [...]}` of player/market/side/line/price/
edge/p_win entries). Only the VALUES differ per sport (confirmed via
direct research 2026-07-23), never the keys a reader needs to check, so
one row-builder serves both rather than duplicating it per sport the way
NBA/WNBA's live-hydration code already has (a divergence that has already
caused drift -- see wnba/cards.py's `_estimated_live_projection` picking
up a garbage-time factor NBA's copy never got).
"""

from __future__ import annotations

import math
from typing import Any

from syndicate.features.shared.market_inventory import join_odds_to_sim
from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport
from syndicate.features.shared.odds_control_plane import resolve_current_shard_key

# Internal join-key market names (basketball_market_board_rows_for_game's
# own vocabulary) -> the odds_history market vocabulary
# _flatten_basketball_game_cards writes (matching MLB's h2h/spreads/totals
# convention -- see that function's own docstring in
# odds_refresh_tracking.py). Mirrors MLB cards.py's
# _MLB_MARKET_BOARD_TO_ODDS_HISTORY_MARKET.
_BASKETBALL_MARKET_BOARD_TO_ODDS_HISTORY_MARKET: dict[str, str] = {
    "moneyline_home": "h2h",
    "moneyline_away": "h2h",
    "spread_home": "spreads",
    "spread_away": "spreads",
    "total": "totals",
}

# Stat codes the sim artifact actually carries a mean/sd pair for (confirmed
# 2026-07-27 against real cards_sim_detail_<date>.json for both NBA and
# WNBA: every player row carries {stat}_mean/{stat}_sd for exactly these
# eight; combo/streak markets like pr/pa/ra/dd/td are display-only labels
# for recommendation-engine picks and never get their own sim distribution).
_DIST_STAT_CODES: tuple[str, ...] = ("pts", "reb", "ast", "threes", "stl", "blk", "tov", "pra")

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


def _prob_over(mean: float, sd: float, line: float) -> float | None:
    """P(actual stat > line) under a normal approximation of the player's
    own simulated distribution -- the same formula the vendored WNBA sim
    engine already uses internally for its own live-tick probability
    (vendor/wnba_betting_repo/app.py's `_prob_over`, confirmed identical
    2026-07-27), reimplemented locally so this module has no vendor
    dependency for a two-line computation.
    """
    try:
        mean_v, sd_v, line_v = float(mean), float(sd), float(line)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(mean_v) and math.isfinite(sd_v) and math.isfinite(line_v)):
        return None
    if sd_v <= 1e-9:
        return 1.0 if mean_v > line_v else 0.0
    z = (line_v - mean_v) / sd_v
    return max(0.0, min(1.0, 1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))))


def player_stat_distributions_from_sim(sim_players: dict[str, Any] | None) -> tuple[dict[str, dict[str, tuple[float, float]]], dict[str, str]]:
    """Reads the sim artifact's own per-player {stat}_mean/{stat}_sd fields
    (confirmed present for both NBA and WNBA's cards_sim_detail_<date>.json,
    2026-07-27) into {normalized_player: {stat_code: (mean, sd)}}, plus a
    normalized->display-name map. This is real sim coverage independent of
    whether the recommendation engine picked a side for that stat -- the
    #101 gap this closes.
    """
    dist: dict[str, dict[str, tuple[float, float]]] = {}
    display_names: dict[str, str] = {}
    if not isinstance(sim_players, dict):
        return dist, display_names
    for side in ("away", "home"):
        rows = sim_players.get(side)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            player = str(row.get("player_name") or row.get("player") or "").strip()
            if not player:
                continue
            normalized = _canonical_player_key(player)
            display_names.setdefault(normalized, player)
            stats: dict[str, tuple[float, float]] = {}
            for stat_code in _DIST_STAT_CODES:
                mean = row.get(f"{stat_code}_mean")
                sd = row.get(f"{stat_code}_sd")
                if mean is None or sd is None:
                    continue
                try:
                    stats[stat_code] = (float(mean), float(sd))
                except (TypeError, ValueError):
                    continue
            if stats:
                dist[normalized] = stats
    return dist, display_names


def basketball_market_board_rows_for_game(
    *,
    game_pk: Any,
    betting: dict[str, Any] | None,
    prop_recommendations: dict[str, Any] | None,
    raw_player_props: dict[str, dict[str, dict[str, Any]]] | None = None,
    sim_players: dict[str, Any] | None = None,
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

    # Only add a spread/total row when a real book price shows up, rather
    # than fabricating standard juice. WNBA's game_cards_{date}.csv carries
    # real per-side prices since 2026-08-02 (end-to-end assessment fix:
    # refresh_wnba_oddsapi_props.py now writes home_spread_price/
    # away_spread_price/total_over_price/total_under_price and wnba/cards.py
    # threads them into this betting dict); NBA's CSV does not yet, so its
    # rows keep degrading exactly as before -- absent columns leave the
    # prices None and the rows are dropped, never invented.
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
    player_stat_dist, sim_display_names = player_stat_distributions_from_sim(sim_players)
    recommended_props_by_entity: dict[str, dict[str, dict[str, Any]]] = {}
    entity_stats_with_sim_row: set[tuple[str, str]] = set()
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
            # confidence come from the same recommendation row. p_win (model
            # win probability for the picked side) is a genuine two-sided
            # probability -- when present, convert it to model_prob_over
            # (P(Over)) so join_odds_to_sim derives the complementary Under
            # side itself instead of both sides sharing the picked side's
            # raw number (the #101 bug: "the one row with a Model % showed
            # the SAME number for both Over and Under -- impossible for real
            # win probabilities", fixed for MLB's own market board via the
            # same join_odds_to_sim mechanism). edge is not a probability
            # and can't be complemented this way, so it stays a plain
            # single-sided sim_projection, matching prior behavior.
            p_win = entry.get("p_win")
            edge = entry.get("edge")
            normalized_entity = _canonical_player_key(player)
            stat_code = _canonical_stat_code(entry.get("market"))

            recommended_props_by_entity.setdefault(player, {})[stat_code] = {
                "market_label": market_label,
                "line": line,
                "odds": odds,
                "side": selection,
            }
            if p_win is not None:
                try:
                    p_win_value = max(0.0, min(1.0, float(p_win)))
                except (TypeError, ValueError):
                    p_win_value = None
                if p_win_value is not None:
                    model_prob_over = p_win_value if selection == "over" else 1.0 - p_win_value
                    sim_rows.append(
                        {
                            "game_id": game_pk,
                            "market": _prop_join_market_key(market_label, normalized_entity),
                            "period": "full_game",
                            "entity": player,
                            "model_prob_over": model_prob_over,
                            "sim_source": "basketball_recommendation_engine",
                        }
                    )
                    entity_stats_with_sim_row.add((normalized_entity, stat_code))
            elif edge is not None:
                sim_rows.append(
                    {
                        "game_id": game_pk,
                        "market": _prop_join_market_key(market_label, normalized_entity),
                        "period": "full_game",
                        "entity": player,
                        "sim_projection": edge,
                        "sim_source": "basketball_recommendation_engine",
                    }
                )
                entity_stats_with_sim_row.add((normalized_entity, stat_code))

    # Raw OddsAPI feed -- the true book-odds source, when we can attribute a
    # player to this game. Basketball has no "probable pitcher" equivalent,
    # so attribution used to be purely via recommendation-engine coverage --
    # a player with zero recommendation-engine coverage had no roster signal
    # to attribute them by. The sim artifact's own per-player rows ARE a
    # real roster signal (confirmed 2026-07-27: cards_sim_detail_<date>.json
    # carries every rostered player with sim coverage, independent of
    # whether the recommendation engine picked anything for them), so a
    # player with sim coverage but no recommendation now also gets
    # attributed -- this is what lets a quoted line with zero
    # recommendation-engine coverage get a genuine model view instead of
    # staying blank (the #101 gap: MLB's fix covers every market-quoted
    # stat with sim coverage, not just recommended ones; this closes the
    # same gap for basketball).
    attributed_players: dict[str, str] = {_canonical_player_key(player): player for player in recommended_props_by_entity}
    for normalized_entity, display_name in sim_display_names.items():
        attributed_players.setdefault(normalized_entity, display_name)

    covered_entity_stats: set[tuple[str, str]] = set()
    for normalized_entity, player in attributed_players.items():
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

            stat_code = _canonical_stat_code(stat_key)
            if (normalized_entity, stat_code) in entity_stats_with_sim_row:
                continue
            if line is None:
                continue
            dist = player_stat_dist.get(normalized_entity, {}).get(stat_code)
            if dist is None:
                continue
            model_prob_over = _prob_over(dist[0], dist[1], line)
            if model_prob_over is None:
                continue
            sim_rows.append(
                {
                    "game_id": game_pk,
                    "market": join_key,
                    "period": "full_game",
                    "entity": player,
                    "model_prob_over": model_prob_over,
                    "sim_source": "basketball_sim_distribution",
                }
            )
            entity_stats_with_sim_row.add((normalized_entity, stat_code))

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


def basketball_odds_history_payload(sport_slug: str, selected_date: str) -> dict[str, Any]:
    """Mirrors MLB cards.py's `_mlb_odds_history_payload` -- the shard-based
    odds-history control-plane artifact, keyed generically by sport slug
    (`odds_control_plane.py` has no MLB-specific handling, confirmed
    2026-07-31), so this works unchanged for "nba"/"wnba".
    """
    shard_key = resolve_current_shard_key(sport_slug, selected_date)
    payload = load_odds_history_payload_for_sport(sport_slug, shard_key)
    return payload if isinstance(payload, dict) else {}


def _basketball_parse_odds_history_market_key(market_key: Any) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in str(market_key or "").split("|"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[key.strip().lower()] = value.strip().lower()
    return parsed


def _basketball_odds_history_entries_for_teams(odds_history: dict[str, Any], away_team: str, home_team: str, history_market_type: str) -> list[dict[str, Any]]:
    """Every tracked entry for this exact game + market type -- mirrors
    MLB cards.py's `_mlb_odds_history_entries_for_teams` exactly (same
    key=value|key=value market-key shape, same equality-match approach,
    since _flatten_basketball_game_cards writes home_team/away_team as
    full team names, matching what the board's own game data carries in
    away.get("name")/home.get("name") -- confirmed both derive from the
    same "home_team"/"visitor_team" source columns, 2026-07-31).
    """
    markets = odds_history.get("markets") if isinstance(odds_history.get("markets"), dict) else {}
    away_key = str(away_team or "").strip().lower()
    home_key = str(home_team or "").strip().lower()
    if not isinstance(markets, dict) or not markets or not away_key or not home_key:
        return []
    entries: list[dict[str, Any]] = []
    for market_key, state in markets.items():
        if not isinstance(state, dict):
            continue
        parsed = _basketball_parse_odds_history_market_key(market_key)
        if parsed.get("market") != history_market_type:
            continue
        if parsed.get("away_team") != away_key or parsed.get("home_team") != home_key:
            continue
        entries.append(state)
    return entries


def _basketball_hydrate_market_board_line_movement(row: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    entry = next((candidate for candidate in entries if candidate.get("last_line") is not None or candidate.get("previous_line") is not None), None)
    if entry is None:
        return
    last_line = entry.get("last_line")
    previous_line = entry.get("previous_line")
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
    # Stamped once at the market's real pregame->live transition
    # (odds_refresh_tracking.py) -- see MLB cards.py's matching comment.
    row["closing_line"] = entry.get("closing_line")
    row["closing_price"] = entry.get("closing_price")


def _basketball_odds_history_entries_for_player(odds_history: dict[str, Any], player_name: str, stat_code: str) -> list[dict[str, Any]]:
    """Player-prop equivalent of _basketball_odds_history_entries_for_teams
    -- matched by player + stat CODE (e.g. "pts"/"pra"), not the display
    label, since the raw feed's own market key carries "stat" as a short
    code (confirmed against real production live-lens rows, 2026-07-31),
    the same vocabulary _canonical_stat_code already produces/consumes.
    """
    markets = odds_history.get("markets") if isinstance(odds_history.get("markets"), dict) else {}
    player_key = _canonical_player_key(player_name)
    stat_key = str(stat_code or "").strip().lower()
    if not isinstance(markets, dict) or not markets or not player_key or not stat_key:
        return []
    entries: list[dict[str, Any]] = []
    for market_key, state in markets.items():
        if not isinstance(state, dict):
            continue
        parsed = _basketball_parse_odds_history_market_key(market_key)
        row_player = _canonical_player_key(parsed.get("player") or parsed.get("player_name") or parsed.get("entity") or "")
        if not row_player or row_player != player_key:
            continue
        if str(parsed.get("stat") or "").strip().lower() != stat_key:
            continue
        entries.append(state)
    return entries


def _basketball_hydrate_market_board_prop_movement(row: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    # Unlike MLB's prop hydration, entries aren't filtered by over/under
    # side here -- the raw live-lens feed's own side/selection field isn't
    # consistently present across every basketball prop source (confirmed
    # research 2026-07-31), and a market's line/closing_line don't differ
    # by side anyway (only which side a given price applies to would), so
    # this is a deliberate simplification, not an oversight.
    if not entries:
        return
    entry = next((candidate for candidate in entries if candidate.get("last_line") is not None or candidate.get("previous_line") is not None), None)
    if entry is None:
        return
    row["line_last"] = entry.get("last_line")
    row["line_previous"] = entry.get("previous_line")
    row["closing_line"] = entry.get("closing_line")
    row["closing_price"] = entry.get("closing_price")


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
    odds_history: dict[str, Any] | None = None,
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
        # Full team names -- what _flatten_basketball_game_cards stores as
        # home_team/away_team in the odds-history market key (both derive
        # from the same home_team/visitor_team source columns, confirmed
        # 2026-07-31), so this is what closing-line matching keys off.
        away_name = str(away.get("name") or away_abbr).strip()
        home_name = str(home.get("name") or home_abbr).strip()
        betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
        prop_recommendations = game.get("prop_recommendations") if isinstance(game.get("prop_recommendations"), dict) else {}
        sim = game.get("sim") if isinstance(game.get("sim"), dict) else {}
        sim_players = sim.get("players") if isinstance(sim.get("players"), dict) else None

        odds_rows, sim_rows = basketball_market_board_rows_for_game(
            game_pk=game_pk,
            betting=betting,
            prop_recommendations=prop_recommendations,
            raw_player_props=raw_player_props,
            sim_players=sim_players,
        )
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        for row in inventory:
            market = row.get("market")
            raw_market_key = market if isinstance(market, str) else None
            if row.get("market_type") == "prop" and isinstance(market, str) and "::" in market:
                # Prop rows carry a disambiguated join key
                # (_prop_join_market_key) so needs-resim detection can't
                # misfire across different players who share a stat --
                # strip it back to the clean label for display.
                market = market.split("::", 1)[0]
            row["market"] = _DISPLAY_LABELS.get(market, market)
            if odds_history:
                if row.get("market_type") == "prop":
                    entity_name = row.get("entity")
                    if entity_name:
                        stat_code = _canonical_stat_code(row.get("market"))
                        entries = _basketball_odds_history_entries_for_player(odds_history, entity_name, stat_code)
                        _basketball_hydrate_market_board_prop_movement(row, entries)
                elif row.get("market_type") == "game":
                    history_market_type = _BASKETBALL_MARKET_BOARD_TO_ODDS_HISTORY_MARKET.get(raw_market_key or "")
                    if history_market_type:
                        entries = _basketball_odds_history_entries_for_teams(odds_history, away_name, home_name, history_market_type)
                        _basketball_hydrate_market_board_line_movement(row, entries)
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
