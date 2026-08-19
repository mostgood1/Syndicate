from __future__ import annotations

import os
import unittest
from unittest import mock

from scripts.fetch_soccer_oddsapi_odds_local import DEFAULT_GAME_MARKETS
from scripts.fetch_soccer_oddsapi_odds_local import _game_markets
from scripts.fetch_soccer_oddsapi_odds_local import _segment_market_map


class TestGameMarketsDoesNotRegressInvalidMarket422(unittest.TestCase):
    """Regression test for the `#343` bug (`77c0ee49`, 2026-08-10): appending
    `_segment_market_map()`'s h1/h2 + alternate-line keys into the REQUESTED
    market list for the bulk `/sports/{sport}/odds` endpoint. Confirmed live
    2026-08-19 that endpoint 422s (`INVALID_MARKET`) on that full key set for
    every soccer league -- the request is one comma-joined `markets=` param,
    so a single unsupported key fails the whole call, silently starving
    every league's game-odds capture since the regression landed.

    `_segment_market_map()` itself stays legitimate -- it is still the
    correct TAGGING map for whatever `_append_soccer_book_quotes` receives
    back (see that function's docstring). This test only pins what gets
    REQUESTED.
    """

    def test_default_requests_only_the_bulk_endpoint_supported_markets(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ODDS_API_SOCCER_GAME_MARKETS", None)
            markets = _game_markets()
        self.assertEqual(markets, list(DEFAULT_GAME_MARKETS))

    def test_default_excludes_every_key_the_live_endpoint_rejected(self):
        # The exact set OddsAPI's 422 named as unsupported on
        # /sports/{sport}/odds, confirmed live 2026-08-19 for mls/la_liga.
        rejected = {
            "alternate_spreads", "alternate_spreads_h1", "alternate_spreads_h2",
            "alternate_totals", "alternate_totals_h1", "alternate_totals_h2",
            "h2h_3_way", "h2h_3_way_h1", "h2h_3_way_h2",
            "h2h_h1", "h2h_h2",
            "spreads_h1", "spreads_h2",
            "totals_h1", "totals_h2",
        }
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ODDS_API_SOCCER_GAME_MARKETS", None)
            markets = set(_game_markets())
        self.assertFalse(markets & rejected, msg=f"requested a rejected market: {markets & rejected}")

    def test_env_override_still_wins_outright(self):
        with mock.patch.dict(os.environ, {"ODDS_API_SOCCER_GAME_MARKETS": "h2h, totals_h1"}, clear=False):
            markets = _game_markets()
        self.assertEqual(markets, ["h2h", "totals_h1"])

    def test_segment_market_map_still_covers_the_full_vocabulary_for_tagging(self):
        # Unchanged behaviour: the tagging map is still the full merged set --
        # only the REQUEST list was narrowed. If this ever starts returning an
        # empty/reduced map, `_append_soccer_book_quotes` silently mistags every
        # segment quote as `full` (or drops it), which is the OTHER failure
        # shape this fix must not reintroduce.
        tag_map = _segment_market_map()
        self.assertIn("h2h", tag_map)
        self.assertIn("totals_h1", tag_map)
        self.assertIn("spreads_h2", tag_map)


if __name__ == "__main__":
    unittest.main()
