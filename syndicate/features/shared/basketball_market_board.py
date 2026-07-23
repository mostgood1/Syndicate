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
    "dd": "Double-Double",
    "td": "Triple-Double",
}

_DISPLAY_LABELS: dict[str, str] = {
    "moneyline_home": "Moneyline",
    "moneyline_away": "Moneyline",
    "spread_home": "Spread",
    "spread_away": "Spread",
    "total": "Total",
}


def _prop_display_market(market: Any) -> str:
    key = str(market or "").strip().lower()
    if key in _PROP_MARKET_LABELS:
        return _PROP_MARKET_LABELS[key]
    tokens = [token.capitalize() for token in key.replace("_", " ").split()]
    return " ".join(tokens) or "Prop"


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

    prop_recommendations = prop_recommendations if isinstance(prop_recommendations, dict) else {}
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

            odds_rows.append(
                {
                    "game_id": game_pk,
                    "market": market_label,
                    "period": "full_game",
                    "entity": player,
                    "side": selection,
                    "line": line,
                    "odds": odds,
                    "market_type": "prop",
                }
            )
            if confidence is not None:
                sim_rows.append(
                    {
                        "game_id": game_pk,
                        "market": market_label,
                        "period": "full_game",
                        "entity": player,
                        "sim_projection": confidence,
                        "sim_source": "basketball_recommendation_engine",
                    }
                )

    return odds_rows, sim_rows


def build_basketball_market_board(*, sport_slug: str, selected_date: str, games: list[dict[str, Any]]) -> dict[str, Any]:
    board_games: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        game_pk = game.get("gamePk") or game.get("game_id")
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        away_abbr = str(away.get("abbr") or game.get("away_tri") or "AWY").strip().upper()
        home_abbr = str(home.get("abbr") or game.get("home_tri") or "HME").strip().upper()
        betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
        prop_recommendations = game.get("prop_recommendations") if isinstance(game.get("prop_recommendations"), dict) else {}

        odds_rows, sim_rows = basketball_market_board_rows_for_game(game_pk=game_pk, betting=betting, prop_recommendations=prop_recommendations)
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        for row in inventory:
            row["market"] = _DISPLAY_LABELS.get(row.get("market"), row.get("market"))

        board_games.append(
            {
                "gamePk": game_pk,
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
