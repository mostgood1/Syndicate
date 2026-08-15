from __future__ import annotations

import unittest

from syndicate.features.shared.game_board_contract import NULL_PLACEHOLDER, _normalize_game


class GameBoardContractPropTeamTests(unittest.TestCase):
    def test_preserves_a_sports_own_shared_top_play_rows_instead_of_clobbering(self) -> None:
        # Real bug found 2026-07-23: this used to unconditionally overwrite
        # shared_top_play_rows with the generic panels-derived version, even
        # when the sport's own cards.py already built a real one from
        # structured data. NFL's cards.py builds genuine EV/odds/confidence
        # rows here, which were silently discarded on every request and
        # replaced by free-text scraped off display panels -- the only
        # escape hatch was the card_variant == "mlb_main" early-return,
        # which NFL doesn't use (card_variant: "shared_default").
        real_rows = [{"heading": "Moneyline", "name": "NYJ ML", "detail": "Confident | Odds -110", "value": "+4.2%"}]
        game = {
            "card_variant": "shared_default",
            "away": {"abbr": "NYJ"},
            "home": {"abbr": "BUF"},
            "shared_top_play_rows": real_rows,
        }

        normalized = _normalize_game(game)

        self.assertEqual(normalized.get("shared_top_play_rows"), real_rows)

    def test_computes_generic_top_play_rows_when_sport_provides_none(self) -> None:
        game = {
            "card_variant": "shared_default",
            "away": {"abbr": "NYJ"},
            "home": {"abbr": "BUF"},
            "panels": [{"title": "Highlights", "items": ["Something happened"]}],
        }

        normalized = _normalize_game(game)

        rows = normalized.get("shared_top_play_rows")
        self.assertTrue(rows)
        self.assertEqual(rows[0]["name"], "Something happened")

    def test_shared_prop_rows_carry_team_abbreviation(self) -> None:
        # _build_prop_rows iterates ("away", away_abbr) / ("home", home_abbr)
        # -- it already knows which team each prop row belongs to, but never
        # stored it, so every downstream consumer (_compact_prop_rows in
        # home.py, and from there _prop_candidate_from_item in
        # intelligence.py) had no way to attribute a team to these props.
        game = {
            "away": {"abbr": "BOS"},
            "home": {"abbr": "NYK"},
            "prop_recommendations": {
                "away": [{"player": "Jayson Tatum", "display_pick": "Over 28.5", "market": "points"}],
                "home": [{"player": "Julius Randle", "display_pick": "Over 24.5", "market": "points"}],
            },
        }

        normalized = _normalize_game(game)
        prop_rows = normalized.get("shared_prop_rows") or []

        self.assertEqual(len(prop_rows), 2)
        by_name = {row.get("name"): row for row in prop_rows}
        self.assertEqual(by_name["Jayson Tatum"]["team"], "BOS")
        self.assertEqual(by_name["Julius Randle"]["team"], "NYK")

    def test_period_rows_do_not_compare_quarter_sim_to_full_game_market_line(self) -> None:
        # Real bug: betting_total/betting_home_spread are the game's ONE
        # full-game market line, but this used to get compared against
        # EVERY individual period's sim projection (e.g. WNBA's q1-q4),
        # producing a nonsensical "edge" every time -- a ~40-point quarter
        # total diffed against a ~165-point full-game line. Every quarter
        # row should carry the market comparison, since a genuine quarter
        # sim projection can't be judged against a full-game line -- only a
        # summed "Full Game" aggregate row should.
        game = {
            "away": {"abbr": "AWY"},
            "home": {"abbr": "HME"},
            "betting": {"total": 165.5, "home_spread": -3.5},
            "sim": {
                "periods": {
                    "q1": {"away_mean": 20.0, "home_mean": 22.0, "p_home_win": 0.55},
                    "q2": {"away_mean": 21.0, "home_mean": 20.0, "p_home_win": 0.48},
                    "q3": {"away_mean": 19.0, "home_mean": 23.0, "p_home_win": 0.6},
                    "q4": {"away_mean": 22.0, "home_mean": 21.0, "p_home_win": 0.49},
                }
            },
        }

        normalized = _normalize_game(game)
        period_rows = normalized.get("shared_period_rows") or []

        quarter_rows = [row for row in period_rows if row.get("label") != "Full Game"]
        self.assertEqual(len(quarter_rows), 4)
        for row in quarter_rows:
            # Was a literal "-". `a86eb4ed` made NULL_PLACEHOLDER an em dash
            # platform-wide and left this assertion behind, so this test was
            # red on `main` and on `origin/main` (reproduced against a clean
            # HEAD worktree, 2026-08-15) until it was updated here. Assert the
            # CONSTANT, not the glyph, so the next placeholder change cannot
            # break the test it is supposed to be verified by.
            self.assertEqual(row["market"], NULL_PLACEHOLDER)
            self.assertEqual(row["best_edge"], NULL_PLACEHOLDER)

        full_game_rows = [row for row in period_rows if row.get("label") == "Full Game"]
        self.assertEqual(len(full_game_rows), 1)
        full_game = full_game_rows[0]
        self.assertNotEqual(full_game["market"], NULL_PLACEHOLDER)
        self.assertIn("165.5", full_game["market"])
        self.assertNotEqual(full_game["best_edge"], NULL_PLACEHOLDER)
        # away totals 82, home totals 86 -> full-game total 168, margin 4
        self.assertIn("168", full_game["subtitle"])

    def test_single_period_still_gets_market_comparison(self) -> None:
        # A sport/game with only one period entry effectively IS the full
        # game -- it should still get a real market comparison, not "-".
        game = {
            "away": {"abbr": "AWY"},
            "home": {"abbr": "HME"},
            "betting": {"total": 165.5, "home_spread": -3.5},
            "sim": {"periods": {"full_game": {"away_mean": 80.0, "home_mean": 85.0, "p_home_win": 0.6}}},
        }

        normalized = _normalize_game(game)
        period_rows = normalized.get("shared_period_rows") or []

        self.assertEqual(len(period_rows), 1)
        self.assertNotEqual(period_rows[0]["market"], "-")
        self.assertIn("165.5", period_rows[0]["market"])


if __name__ == "__main__":
    unittest.main()
