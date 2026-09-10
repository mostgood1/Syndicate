"""`markets.segments` never reached the odds-history shard, and the key had no
`segment` term. Neither half does anything without the other.

MEASURED 2026-09-09 by running the real flattener over a real MLB snapshot
(`data/mlb_source/.../oddsapi_game_lines_*.json`, 15-game slate):

    before   45 rows out -- 15 each of h2h/spreads/totals, ZERO with a segment
    after   270 rows out -- 225 distinct keys, 180 of them segment-keyed

`_market_rows_from_mapping` descends `markets`, meets the key `segments`, sets
`market="segments"` from the container name and STOPS: the level below is
segment NAMES (`first5`), which is neither a recognised container nor a line
snapshot. The whole subtree was discarded silently. Adding `segment` to the key
alone would have shipped INERT, which is why this file tests the pair.

Confirmed on the shard side against production: 4,063 of 4,063 keys in the
2026-09-08 mlb shard carry no `segment` term, and its only game markets are
plain h2h/spreads/totals (102 each).

**THE INVARIANT THAT MATTERS MOST IS THE ONE ABOUT NOT CHANGING ANYTHING.**
Every entry in every existing shard was written without a segment term, and
these keys are compared verbatim. A full-game row must still produce the
byte-identical key it produces today, or the first write after deploy orphans
the entire store -- silently, because an orphaned key is indistinguishable from
a market nobody has quoted. Measured across the 47 game-line snapshots in the
mirror: 1,544 old keys -> 6,873 new, and **0 old keys lost**.
"""

from __future__ import annotations

import unittest

from syndicate.features.shared.odds_refresh_tracking import (
    _market_rows_from_mapping,
    _odds_history_market_key,
    _odds_history_segment_term,
)

# The real shape, copied from `oddsapi_game_lines_2026_06_02.json` rather than
# invented -- `fetch_mlb_oddsapi_local.py:431` mirrors `segments.full` up to the
# top-level markets, and that duplication is load-bearing below.
_GAME = {
    "event_id": "0aecf375a07f34755e00a1ba7fb63c16",
    "commence_time": "2026-06-02T22:41:00Z",
    "home_team": "Boston Red Sox",
    "away_team": "Baltimore Orioles",
    "bookmaker": "draftkings",
    "markets": {
        "h2h": {"home_odds": "+109", "away_odds": "-131"},
        "totals": {"line": 8.5, "over_odds": "-109", "under_odds": "-111"},
        "segments": {
            "full": {
                "h2h": {"home_odds": "+109", "away_odds": "-131"},
                "totals": {"line": 8.5, "over_odds": "-109", "under_odds": "-111"},
            },
            "first5": {
                "h2h": {"home_odds": "+104", "away_odds": "-124"},
                "totals": {"line": 4.5, "over_odds": "-120", "under_odds": "+100"},
            },
            "first3": {
                "totals": {"line": 2.5, "over_odds": "+135", "under_odds": "-165"},
            },
        },
    },
}

_FULL_H2H_KEY = ("event_id=0aecf375a07f34755e00a1ba7fb63c16|home_team=Boston Red Sox"
                 "|away_team=Baltimore Orioles|market=h2h|bookmaker=draftkings")


def _keys(payload):
    return [_odds_history_market_key(row) for row in _market_rows_from_mapping(payload)]


class TheSegmentSubtreeIsReached(unittest.TestCase):
    def test_segment_prices_become_rows_at_all(self) -> None:
        """The half that was inert. Before this, the `segments` subtree produced
        nothing and the key change would have had nothing to key."""
        rows = _market_rows_from_mapping(_GAME)
        segments = {str(row.get("segment")) for row in rows if row.get("segment")}
        self.assertEqual(segments, {"full", "first5", "first3"})

    def test_the_segment_name_is_not_mistaken_for_the_market(self) -> None:
        """The generic recursion stamped `market="segments"` from the container
        name. That is not a market, and it would have collapsed first-1,
        first-3 and first-5 into one entry -- the same defect, one level worse."""
        markets = {str(row.get("market")) for row in _market_rows_from_mapping(_GAME)}
        self.assertNotIn("segments", markets)
        self.assertEqual(markets, {"h2h", "totals"})

    def test_each_segment_and_market_gets_its_own_key(self) -> None:
        keys = {key for key in _keys(_GAME) if key}
        self.assertIn(_FULL_H2H_KEY, keys)
        self.assertIn(_FULL_H2H_KEY.replace("|market=h2h|", "|market=h2h|segment=first5|"), keys)
        self.assertIn(_FULL_H2H_KEY.replace("|market=h2h|", "|market=totals|segment=first3|"), keys)

    def test_a_first5_total_and_a_full_game_total_are_different_keys(self) -> None:
        """Over 4.5 through five innings and over 8.5 through nine are not the
        same bet. Sharing a key is how a first-5 opening took a nine-inning
        close in `clv_join` -- 19 of 2,007 resolved CLV rows on 2026-09-08."""
        keys = [key for key in _keys(_GAME) if key and "market=totals" in key]
        # FOUR rows, THREE keys: full-game, first5, first3 -- and full-game
        # twice, because `segments.full` is a mirror of the top-level block.
        # That collapse is asserted on its own in `FullGameKeysDoNotMove`.
        self.assertEqual(len(keys), 4)
        self.assertEqual(len(set(keys)), 3)
        self.assertEqual(len({key for key in keys if "segment=" not in key}), 1)


class FullGameKeysDoNotMove(unittest.TestCase):
    """The store is persisted and its keys are compared verbatim. Every one of
    them was written without a segment term."""

    def test_the_full_game_key_is_byte_identical(self) -> None:
        self.assertEqual(
            _odds_history_market_key({
                "event_id": "0aecf375a07f34755e00a1ba7fb63c16",
                "home_team": "Boston Red Sox", "away_team": "Baltimore Orioles",
                "market": "h2h", "bookmaker": "draftkings",
            }),
            _FULL_H2H_KEY,
        )

    def test_an_explicit_full_segment_keys_the_same_as_no_segment_at_all(self) -> None:
        """`segments.full` DUPLICATES the top-level markets -- the fetcher
        mirrors it up. Both must land on one key or every full-game market
        would exist twice in the shard under two spellings."""
        base = {"event_id": "0aecf375a07f34755e00a1ba7fb63c16",
                "home_team": "Boston Red Sox", "away_team": "Baltimore Orioles",
                "market": "h2h", "bookmaker": "draftkings"}
        for spelling in (None, "", "full", "FULL", " Full ", "game", "full_game"):
            self.assertEqual(_odds_history_market_key({**base, "segment": spelling}),
                             _FULL_H2H_KEY, spelling)

    def test_the_full_duplicate_collapses_to_one_key_end_to_end(self) -> None:
        """Not just the helper -- through the flattener, on the real shape.
        Two rows, one key; the write loop's `seen_current_snapshots` drops the
        second because line, price and snapshot are identical too."""
        rows = [row for row in _market_rows_from_mapping(_GAME)
                if str(row.get("market")) == "h2h"
                and _odds_history_segment_term(row.get("segment")) == ""]
        self.assertEqual(len(rows), 2)
        self.assertEqual({_odds_history_market_key(row) for row in rows}, {_FULL_H2H_KEY})
        self.assertEqual({row.get("home_odds") for row in rows}, {"+109"})

    def test_a_row_with_no_segments_block_is_untouched(self) -> None:
        """Every other sport. NCAAF, NFL and soccer route their segment prices
        to `book_quotes`, not to an odds-history snapshot, so no row of theirs
        carries a `segment` and no key of theirs may change. Measured on the
        mirror: nhl/nba/wnba produced 405 keys, 0 lost, 0 segment-keyed."""
        plain = {k: v for k, v in _GAME.items() if k != "markets"}
        plain["markets"] = {"h2h": {"home_odds": "+109", "away_odds": "-131"}}
        self.assertEqual([key for key in _keys(plain) if key], [_FULL_H2H_KEY])


class TheSegmentTermItself(unittest.TestCase):
    def test_full_game_spellings_produce_no_term(self) -> None:
        for spelling in (None, "", "full", "FULL", " Full ", "game", "fullgame", "full_game"):
            self.assertEqual(_odds_history_segment_term(spelling), "", spelling)

    def test_every_other_value_survives_normalised(self) -> None:
        for raw, expected in (("first5", "first5"), ("FIRST5", "first5"),
                              (" first3 ", "first3"), ("h1", "h1"), ("1q", "1q")):
            self.assertEqual(_odds_history_segment_term(raw), expected)

    def test_the_term_sits_immediately_after_the_market(self) -> None:
        """Position is part of the contract: these are pipe-joined strings
        compared verbatim, so a term in the wrong place matches nothing. The
        consumer (`clv_join._history_key`) emits it there."""
        key = _odds_history_market_key({
            "event_id": "e1", "home_team": "H", "away_team": "A",
            "market": "totals", "segment": "first5", "bookmaker": "fanduel",
        })
        self.assertEqual(key, "event_id=e1|home_team=H|away_team=A"
                              "|market=totals|segment=first5|bookmaker=fanduel")


class TheShardActuallyGetsThem(unittest.TestCase):
    """END TO END, through `_sync_odds_history_for_refresh` and onto disk.

    Everything above is the key builder and the flattener. This is the only
    test that proves a segment price survives the write gate, the dedupe and
    the shard merge -- which is where the previous version of this change would
    still have produced nothing, because the write loop de-dupes on
    `(market_key, line, odds, snapshot_ts)` and a collided key would have
    dropped every segment as a repeat of the full-game row."""

    def test_a_snapshot_with_segments_writes_segment_keyed_entries(self) -> None:
        import json
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from syndicate.features.shared.odds_refresh_tracking import (
            _sync_odds_history_for_refresh,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mlb_source"
            snapshot = root / "data" / "daily" / "snapshots" / "2026-06-02"
            snapshot.mkdir(parents=True)
            (snapshot / "oddsapi_game_lines_2026_06_02.json").write_text(
                json.dumps({"date": "2026-06-02",
                            "retrieved_at": "2026-06-02T18:00:00Z",
                            "games": [_GAME]}),
                encoding="utf-8",
            )
            # The sync also writes a shared copy under the reports root; point
            # that at the temp dir so the test leaves nothing behind.
            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(Path(tmp) / "reports"),
                                         "SYNDICATE_REFRESH_STATE_BACKEND": "file"}):
                result = _sync_odds_history_for_refresh(
                    sport="mlb", source_root=root, date_str="2026-06-02")

            self.assertTrue(result.get("ok"))
            shard = root / "tracking" / "odds_history" / "2026-06-02.json"
            markets = json.loads(shard.read_text(encoding="utf-8"))["markets"]

        # 5 keys: full h2h + full totals (byte-identical to today), plus
        # first5 h2h, first5 totals, first3 totals.
        self.assertEqual(len(markets), 5)
        self.assertIn(_FULL_H2H_KEY, markets)
        self.assertEqual(
            sorted(key.split("|segment=")[1].split("|")[0]
                   for key in markets if "|segment=" in key),
            ["first3", "first5", "first5"],
        )
        # ONE history point on the full-game key, not two: `segments.full`
        # duplicates the top-level block and the write loop de-dupes it.
        self.assertEqual(len(markets[_FULL_H2H_KEY]["history"]), 1)
        # And the segment entry carries the SEGMENT's price, not the game's.
        first5_h2h = _FULL_H2H_KEY.replace("|market=h2h|", "|market=h2h|segment=first5|")
        self.assertEqual(len(markets[first5_h2h]["history"]), 1)
        self.assertNotEqual(markets[first5_h2h]["history"][0],
                            markets[_FULL_H2H_KEY]["history"][0])


class TheConsumerAgrees(unittest.TestCase):
    """The producer and `clv_join` are two halves of one contract. They were
    written apart and must be checked together, or the CLV join keeps refusing
    segment bets while the shard quietly starts carrying them."""

    def test_the_two_key_builders_produce_the_same_string(self) -> None:
        from syndicate.features.shared.clv_join import _history_key

        opening = {"event_id": "e1", "home_team": "H", "away_team": "A",
                   "market": "totals", "segment": "first5", "bookmaker": "fanduel"}
        self.assertEqual(_history_key(opening), _odds_history_market_key(opening))

    def test_they_agree_on_full_game_too(self) -> None:
        from syndicate.features.shared.clv_join import _history_key

        opening = {"event_id": "e1", "home_team": "H", "away_team": "A",
                   "market": "totals", "bookmaker": "fanduel"}
        self.assertEqual(_history_key(opening), _odds_history_market_key(opening))
        self.assertNotIn("segment=", _history_key(opening))


if __name__ == "__main__":
    unittest.main()
