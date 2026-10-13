"""Final scores for a PAST WNBA date's games-rail chips, from the settlement's own rows.

Reported 2026-10-13 (user board check, lane games-rail-full-detail): the WNBA
chips for 10-07 and 10-09 read `pregame` with no score, the morning after games
that had settled 2,822 picks. Two causes, both measured on the fleet:

* For a past date the WNBA provider builds games from the processed game-cards
  file and merges live status only for TODAY (`_live_status_merge_enabled`).
  The live-state snapshot that would have carried the final was last written
  before tip (10-09: 18:21 CT for an 8:37 PM tip) and the keyvalue copy had
  expired, so nothing ever flipped the game to final.
* The game-cards file held ONE of the two games each night; ATL @ NYL, with 355
  board plays on 10-09, had no chip at all.

The fix reads what the settlement already trusts: `settlement_sport_rows`'
WNBA score rows (recon_games, else a completed ESPN event, else box points
summed per team) -- disk only, no outbound call in the request path. A past
game that row says is final gets the final status and score; a final row with
no game gets a game built the WNBA cards module's own way.

Display only: nothing here changes a pick, a price or a settlement.
"""

from __future__ import annotations

from typing import Any

from syndicate.features.shared.timezone import central_today_iso


def _final_rows(date_value: str) -> list[dict[str, Any]]:
    from syndicate.features.shared.settlement_sport_rows import SCORE_ROW_MARKET, wnba_rows_for_date

    return [
        row
        for row in wnba_rows_for_date(date_value)
        if row.get("market") == SCORE_ROW_MARKET and row.get("segment") in (None, "", "full")
        and row.get("home_score") is not None and row.get("away_score") is not None
    ]


def apply_wnba_recorded_finals(games: list[dict[str, Any]], date_value: str) -> list[dict[str, Any]]:
    """`games` with recorded finals applied; unchanged for today or a future date."""
    if not date_value or str(date_value) >= central_today_iso():
        return games
    try:
        rows = _final_rows(str(date_value))
    except Exception:  # noqa: BLE001 -- a results line must never cost the scoreboard
        return games
    if not rows:
        return games
    from syndicate.features.wnba.cards import _canonical_wnba_tri, _game_from_row

    def key(away: Any, home: Any) -> tuple[str, str]:
        return _canonical_wnba_tri(str(away or "")), _canonical_wnba_tri(str(home or ""))

    by_matchup = {key(g.get("away_tri"), g.get("home_tri")): g for g in games if isinstance(g, dict)}
    out = list(games)
    for idx, row in enumerate(rows, start=1):
        away_pts, home_pts = float(row["away_score"]), float(row["home_score"])
        matchup = key(row.get("away"), row.get("home"))
        game = by_matchup.get(matchup)
        if game is None:
            away_tri, home_tri = matchup
            out.append(
                _game_from_row(
                    {
                        "event_id": row.get("game_id") or f"{away_tri}@{home_tri}",
                        "visitor_team": away_tri,
                        "home_team": home_tri,
                        "away_tri": away_tri,
                        "home_tri": home_tri,
                        "bookmaker": "ESPN",
                        "commence_time": str(date_value),
                        "status": "Final",
                        "in_progress": False,
                        "final": True,
                        "away_pts": away_pts,
                        "home_pts": home_pts,
                    },
                    idx=len(games) + idx,
                    selected_date=str(date_value),
                    rec_index={},
                    sim_index={},
                    props_index={},
                )
            )
            continue
        status = dict(game.get("status")) if isinstance(game.get("status"), dict) else {}
        if status.get("final"):
            continue
        status.update({"status": "Final", "detail": "Final", "final": True, "in_progress": False, "clock": ""})
        live_state = dict(game.get("live_state")) if isinstance(game.get("live_state"), dict) else {}
        live_state.update({"final": True, "in_progress": False, "status": "Final", "away_pts": away_pts, "home_pts": home_pts})
        game["status"] = status
        game["live_state"] = live_state
    return out
