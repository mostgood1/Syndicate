"""Phase 1 pilot: does the Layer 1 odds<->sim join hold up against real
MLB data, not just synthetic fixtures?

The five game rows below are copied verbatim from `/mlb/api/cards` for
2026-07-23, captured earlier this session while investigating why MLB
pregame game markets weren't reaching the board (see commit 4e2adf02).
They are real, not constructed: four games (SD@ATL, MIN@CLE, TB@TOR,
AZ@STL) have a bare `markets.ml` odds quote with no recommendation-engine
coverage at all; one game (KC@DET) has a full recommendation with a real
`model_prob`/`edge`/`selection`. That split is exactly the
matched-vs-no-coverage distinction Layer 1's join is meant to represent,
and it occurred naturally in production, not by construction.

This does not touch `syndicate/features/mlb/cards.py` or any production
code -- it's a pilot conversion, proving the join mechanics hold up against
a real shape before Phase 3/5 wire it into the actual pipeline.
"""

from __future__ import annotations

import unittest
from typing import Any

from syndicate.features.shared.market_inventory import (
    JOIN_STATUS_MATCHED,
    JOIN_STATUS_NO_SIM_COVERAGE,
    join_odds_to_sim,
)

# Captured verbatim from /mlb/api/cards?date=2026-07-23 this session.
_CAPTURED_MLB_GAMES: list[dict[str, Any]] = [
    {"gamePk": 824893, "away": "SD", "home": "ATL", "ml": {"away_odds": "+690", "home_odds": "-1520"}},
    {"gamePk": 824406, "away": "MIN", "home": "CLE", "ml": {"away_odds": "+250", "home_odds": "-350"}},
    {"gamePk": 822785, "away": "TB", "home": "TOR", "ml": {"away_odds": "-115", "home_odds": "-104"}},
    {"gamePk": 823042, "away": "AZ", "home": "STL", "ml": {"away_odds": "-105", "home_odds": "-115"}},
    {
        "gamePk": 824247,
        "away": "KC",
        "home": "DET",
        "ml": {
            "selection": "home",
            "model_prob": 0.695,
            "market_no_vig_prob": 0.6656300180905339,
            "edge": 0.029369981909466047,
            "odds": "-229",
        },
    },
]


def _pilot_ml_odds_rows(game: dict[str, Any]) -> list[dict[str, Any]]:
    """Minimal adapter: game['ml'] (whichever of the two real shapes it
    happens to be) -> Layer 1 odds rows. Deliberately not a general-purpose
    adapter -- Phase 3/5 is where a real one lives in mlb/cards.py."""
    ml = game.get("ml") or {}
    rows = []
    if "away_odds" in ml or "home_odds" in ml:
        if ml.get("away_odds") is not None:
            rows.append({"game_id": game["gamePk"], "market": "moneyline", "period": "full_game", "entity": None, "side": "away", "odds": ml.get("away_odds")})
        if ml.get("home_odds") is not None:
            rows.append({"game_id": game["gamePk"], "market": "moneyline", "period": "full_game", "entity": None, "side": "home", "odds": ml.get("home_odds")})
    elif ml.get("selection"):
        rows.append({"game_id": game["gamePk"], "market": "moneyline", "period": "full_game", "entity": None, "side": ml["selection"], "odds": ml.get("odds")})
    return rows


def _pilot_ml_sim_row(game: dict[str, Any]) -> dict[str, Any] | None:
    """The recommendation-engine's baked-in model_prob IS a sim projection
    -- just currently only exposed for games it decided to recommend on.
    That's precisely the "pre-filtered, not a full inventory" gap Layer 1
    is meant to close (Phase 3/5): here we only extract it because it
    happens to already be present for KC@DET."""
    ml = game.get("ml") or {}
    if ml.get("model_prob") is None:
        return None
    return {"game_id": game["gamePk"], "market": "moneyline", "period": "full_game", "entity": None, "sim_projection": ml.get("model_prob"), "sim_source": "mlb_locked_policy"}


class MlbGameMarketPilotTests(unittest.TestCase):
    def test_join_against_real_captured_mlb_slate(self) -> None:
        odds_rows: list[dict[str, Any]] = []
        sim_rows: list[dict[str, Any]] = []
        for game in _CAPTURED_MLB_GAMES:
            odds_rows.extend(_pilot_ml_odds_rows(game))
            sim_row = _pilot_ml_sim_row(game)
            if sim_row is not None:
                sim_rows.append(sim_row)

        inventory = join_odds_to_sim(odds_rows, sim_rows)
        by_game = {}
        for row in inventory:
            by_game.setdefault(row["game_id"], []).append(row)

        # The four games with a bare odds quote and no recommendation-engine
        # coverage: every quoted side should still show up (a sportsbook
        # shows the line whether or not a model has an opinion on it), just
        # unscored.
        for game_pk in (824893, 824406, 822785, 823042):
            rows = by_game[game_pk]
            self.assertEqual(len(rows), 2, f"expected both sides quoted for {game_pk}")
            for row in rows:
                self.assertEqual(row["join_status"], JOIN_STATUS_NO_SIM_COVERAGE)
                self.assertIsNone(row["sim_projection"])
                self.assertTrue(row["is_eligible"])

        # KC @ DET has a real recommendation-engine projection -- the join
        # should surface it as matched, not as a coverage gap.
        kc_det_rows = by_game[824247]
        self.assertEqual(len(kc_det_rows), 1)
        self.assertEqual(kc_det_rows[0]["join_status"], JOIN_STATUS_MATCHED)
        self.assertAlmostEqual(kc_det_rows[0]["sim_projection"], 0.695)
        self.assertEqual(kc_det_rows[0]["sim_source"], "mlb_locked_policy")

        # Total inventory size: 4 games * 2 sides + 1 game * 1 side.
        self.assertEqual(len(inventory), 9)


if __name__ == "__main__":
    unittest.main()
