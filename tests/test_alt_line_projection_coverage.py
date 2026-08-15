"""Alternate lines are the same market at a different number, and both halves
of the board were dropping them.

Measured on the served board 2026-08-15 22:41:43Z:
  * 53 of 107 live GAME-LINE rows carried no projection at all -- every one of
    them `spreads_alt` (29) or `totals_alt` (24) -- because neither key was in
    `project_game_market`'s market sets.
  * 32 of 153 remaining live PROP misses were rows at a line the live snapshot
    had flattened away; production carries 113 `alternates` across 1,085
    (player, market) entries.
"""

from __future__ import annotations

import unittest

from syndicate.features.mlb.cards import _extract_hitter_market_lines
from syndicate.features.shared.prop_projections import project_game_market


class _Index:
    """Minimal stand-in for `PropProjectionIndex.game_payloads`."""

    def __init__(self, payload):
        self._payload = payload

    def game_payloads(self, *, sport, home_team, away_team):
        return {"full": self._payload}


def _game_index():
    return _Index(
        {
            "home_win_prob": 0.55,
            "away_win_prob": 0.45,
            # 8 runs half the time, 10 the other half -> P(total > 8.5) = 0.5
            "total_runs_dist": {"8": 50, "10": 50},
            # home by 1 half the time, home by 3 the other -> P(margin > 1.5) = 0.5
            "run_margin_dist": {"1": 50, "3": 50},
        }
    )


def _project(market, selection, line):
    return project_game_market(
        _game_index(),
        sport="mlb",
        home_team="Cincinnati Reds",
        away_team="Miami Marlins",
        market=market,
        selection=selection,
        line=line,
        segment="full",
    )


class AltGameMarketTests(unittest.TestCase):
    def test_totals_alt_is_priced(self):
        got = _project("totals_alt", "over", 8.5)
        self.assertIsNotNone(got)
        self.assertEqual(got["model_prob_over"], 0.5)
        self.assertEqual(got["source"], "game_simulation")

    def test_spreads_alt_is_priced(self):
        got = _project("spreads_alt", "away", 1.5)
        self.assertIsNotNone(got)
        self.assertIsNotNone(got["model_prob_over"])

    def test_alt_agrees_with_its_main_market_at_the_same_line(self):
        # An alternate is the SAME market at a different number. If the two ever
        # disagree at one line, one of them is walking the wrong distribution.
        for main, alt, side in (("totals", "totals_alt", "over"), ("spreads", "spreads_alt", "away")):
            with self.subTest(market=alt):
                self.assertEqual(
                    _project(main, side, 1.5 if main == "spreads" else 8.5),
                    _project(alt, side, 1.5 if main == "spreads" else 8.5),
                )

    def test_an_unknown_market_is_still_refused(self):
        # The fix must widen the gate, not remove it.
        self.assertIsNone(_project("player_shots_on_goal", "over", 1.5))


def _snapshot_doc(alternates):
    return {
        "hitter_props": {
            "Chandler Simpson": {
                "batter_hits_runs_rbis": {
                    "line": 1.5,
                    "over_odds": "-121",
                    "under_odds": "-110",
                    "alternates": alternates,
                }
            }
        }
    }


class HitterAlternateLineExtractionTests(unittest.TestCase):
    def test_alternates_become_lanes(self):
        out = _extract_hitter_market_lines(
            _snapshot_doc([{"line": 2.5, "over_odds": "+140", "under_odds": "-190"}])
        )
        lanes = out["chandler simpson"]["batter_hits_runs_rbis"]["lanes"]
        self.assertEqual([l["line"] for l in lanes], [1.5, 2.5])
        self.assertEqual(lanes[1]["over_odds"], "+140")

    def test_the_main_line_fields_are_untouched(self):
        # Additive by construction: the other consumer of this map reads only
        # `line`/`over_odds`/`under_odds` and must not change behaviour.
        market = _extract_hitter_market_lines(
            _snapshot_doc([{"line": 2.5, "over_odds": "+140", "under_odds": "-190"}])
        )["chandler simpson"]["batter_hits_runs_rbis"]
        self.assertEqual(market["line"], 1.5)
        self.assertEqual(market["over_odds"], "-121")
        self.assertEqual(market["under_odds"], "-110")

    def test_no_alternates_yields_a_single_lane(self):
        lanes = _extract_hitter_market_lines(_snapshot_doc([]))["chandler simpson"]["batter_hits_runs_rbis"]["lanes"]
        self.assertEqual([l["line"] for l in lanes], [1.5])

    def test_a_duplicate_alternate_line_is_not_emitted_twice(self):
        # Two rows at one line would double-count the market and, downstream,
        # collide on `_live_prop_signature`.
        lanes = _extract_hitter_market_lines(
            _snapshot_doc([{"line": 1.5, "over_odds": "-125", "under_odds": "-105"}])
        )["chandler simpson"]["batter_hits_runs_rbis"]["lanes"]
        self.assertEqual([l["line"] for l in lanes], [1.5])

    def test_a_malformed_alternate_is_skipped_not_fatal(self):
        lanes = _extract_hitter_market_lines(
            _snapshot_doc(["nonsense", {"over_odds": "+140"}, {"line": 2.5}])
        )["chandler simpson"]["batter_hits_runs_rbis"]["lanes"]
        self.assertEqual([l["line"] for l in lanes], [1.5, 2.5])


from unittest.mock import patch

from syndicate.features.mlb import cards
from syndicate.features.mlb.cards import _synth_live_hitter_prop_rows


def _sim():
    return {
        "hitter_props": {
            "1": {
                "name": "Chandler Simpson", "team_side": "home", "lineup_order": 1,
                "pa_mean": 4.4, "ab_mean": 4.0, "hrr_mean": 1.9,
                "hits_runs_rbis_dist": {"0": 20, "1": 25, "2": 25, "3": 30},
            }
        }
    }


def _actual():
    return {
        "gameData": {"teams": {"away": {"abbreviation": "MIA"}, "home": {"abbreviation": "CIN"}}},
        "liveData": {
            "linescore": {"currentInning": 3, "inningHalf": "top", "outs": 1},
            "boxscore": {"teams": {"away": {"players": {}}, "home": {"players": {
                "ID1": {"person": {"id": 1, "fullName": "Chandler Simpson"}, "battingOrder": "100",
                        "stats": {"batting": {"atBats": 1, "hits": 0, "runs": 0, "rbi": 0, "homeRuns": 0}}}}}}},
        },
    }


def _lines(lanes):
    return {"chandler simpson": {"batter_hits_runs_rbis": {
        "line": 1.5, "over_odds": "-121", "under_odds": "-110", "lanes": lanes}}}


class EmitsARowPerLaneTests(unittest.TestCase):
    def _rows(self, lanes):
        with patch.object(cards, "_hitter_snapshot_market_lines", return_value=_lines(lanes)):
            return _synth_live_hitter_prop_rows(
                "2026-08-15", 824480, _sim(), _actual(), [], include_projection_only=True)

    def test_one_row_per_captured_line(self):
        rows = self._rows([
            {"line": 1.5, "over_odds": "-121", "under_odds": "-110"},
            {"line": 2.5, "over_odds": "+140", "under_odds": "-190"},
        ])
        self.assertEqual(sorted(r["market_line"] for r in rows), [1.5, 2.5])

    def test_each_row_carries_its_own_lines_price(self):
        rows = {r["market_line"]: r for r in self._rows([
            {"line": 1.5, "over_odds": "-121", "under_odds": "-110"},
            {"line": 2.5, "over_odds": "+140", "under_odds": "-190"},
        ])}
        self.assertEqual(rows[2.5]["over_odds"], "+140")
        self.assertEqual(rows[1.5]["over_odds"], "-121")

    def test_the_probability_moves_with_the_line_and_the_projection_does_not(self):
        # The projection is per player-market; only P(over) is per line.
        rows = {r["market_line"]: r for r in self._rows([
            {"line": 1.5, "over_odds": "-121", "under_odds": "-110"},
            {"line": 2.5, "over_odds": "+140", "under_odds": "-190"},
        ])}
        self.assertGreater(rows[1.5]["model_prob_over"], rows[2.5]["model_prob_over"])
        self.assertEqual(rows[1.5]["live_projection"], rows[2.5]["live_projection"])

    def test_a_snapshot_without_lanes_still_emits_its_single_line(self):
        # Archived snapshots predate `lanes`; they must not go dark.
        with patch.object(cards, "_hitter_snapshot_market_lines", return_value={
            "chandler simpson": {"batter_hits_runs_rbis": {"line": 1.5, "over_odds": "-121", "under_odds": "-110"}}}):
            rows = _synth_live_hitter_prop_rows(
                "2026-08-15", 824480, _sim(), _actual(), [], include_projection_only=True)
        self.assertEqual([r["market_line"] for r in rows], [1.5])


if __name__ == "__main__":
    unittest.main()
