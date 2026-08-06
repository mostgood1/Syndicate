"""#209 -- the per-book quote log, and the MLB extractors that feed it.

What these actually guard: every one of these assertions corresponds to a
measured production defect on 2026-08-05, not a hypothetical. Prop keys carried
no bookmaker (0 of 3,437), closing capture was 2.13% and game-markets-only, and
the game-lines snapshot held one book per game while the API response held 4-8.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import odds_book_quotes as quotes_module
from syndicate.features.shared.odds_book_quotes import (
    append_book_quotes,
    best_price_by_market,
    closing_quotes,
    read_book_quotes,
)


def _event_payload() -> dict:
    """Shaped like a real merged OddsAPI event payload: several books, each with
    core and segment markets."""
    return {
        "id": "evt-1",
        "commence_time": "2026-08-06T00:15:00Z",
        "home_team": "New York Yankees",
        "away_team": "St. Louis Cardinals",
        "bookmakers": [
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": "h2h",
                        "last_update": "2026-08-05T22:00:00Z",
                        "outcomes": [
                            {"name": "New York Yankees", "price": -700},
                            {"name": "St. Louis Cardinals", "price": 550},
                        ],
                    },
                    {
                        "key": "totals_1st_5_innings",
                        "outcomes": [
                            {"name": "Over", "price": -136, "point": 4.5},
                            {"name": "Under", "price": 102, "point": 4.5},
                        ],
                    },
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "New York Yankees", "price": -650},
                            {"name": "St. Louis Cardinals", "price": 500},
                        ],
                    }
                ],
            },
        ],
    }


def _prop_payload() -> dict:
    return {
        "id": "evt-1",
        "commence_time": "2026-08-06T00:15:00Z",
        "home_team": "New York Yankees",
        "away_team": "St. Louis Cardinals",
        "bookmakers": [
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": "batter_hits",
                        "outcomes": [
                            {"name": "Over", "description": "Jeremy Pena", "price": 410, "point": 0.5},
                            {"name": "Under", "description": "Jeremy Pena", "price": -700, "point": 0.5},
                        ],
                    }
                ],
            },
            {
                "key": "betmgm",
                "markets": [
                    {
                        "key": "batter_hits",
                        "outcomes": [
                            {"name": "Over", "description": "Jeremy Pena", "price": 395, "point": 0.5},
                        ],
                    },
                    {"key": "not_a_tracked_market", "outcomes": [{"name": "Over", "description": "X", "price": 100, "point": 1.5}]},
                ],
            },
        ],
    }


class MlbBookQuoteExtractorTests(unittest.TestCase):
    """The two collapse sites measured in #208: game lines kept 1 of 4-8 books,
    props kept 0 book identity at all."""

    def setUp(self) -> None:
        import scripts.fetch_mlb_oddsapi_local as fetcher

        self.fetcher = fetcher

    def test_game_quotes_keep_every_book_and_split_segments(self) -> None:
        rows = self.fetcher._game_line_book_quotes(
            _event_payload(),
            event={"id": "evt-1", "commence_time": "2026-08-06T00:15:00Z"},
            home_team="New York Yankees",
            away_team="St. Louis Cardinals",
        )
        self.assertEqual({row["bookmaker"] for row in rows}, {"fanduel", "draftkings"})
        h2h = [row for row in rows if row["market"] == "h2h"]
        # 2 books x 2 sides -- the whole point: _best_bookmaker_game_lines would
        # have returned one book's pair.
        self.assertEqual(len(h2h), 4)
        self.assertEqual({row["selection"] for row in h2h}, {"home", "away"})
        segment_rows = [row for row in rows if row["segment"] == "first5"]
        self.assertEqual(len(segment_rows), 2)
        self.assertEqual({row["market"] for row in segment_rows}, {"totals"})
        # Every row carries the event linkage that makes a closing line a lookup.
        for row in rows:
            self.assertEqual(row["commence_time"], "2026-08-06T00:15:00Z")
            self.assertEqual(row["event_id"], "evt-1")

    def test_segment_key_parsing(self) -> None:
        self.assertEqual(self.fetcher._segment_and_market_from_key("h2h"), ("full", "h2h"))
        self.assertEqual(self.fetcher._segment_and_market_from_key("spreads_1st_3_innings"), ("first3", "spreads"))
        self.assertEqual(
            self.fetcher._segment_and_market_from_key("alternate_totals_1st_1_innings"), ("first1", "totals_alt")
        )

    def test_prop_quotes_carry_bookmaker_and_event(self) -> None:
        rows = self.fetcher._prop_book_quotes(
            _prop_payload(),
            event={"id": "evt-1", "commence_time": "2026-08-06T00:15:00Z", "home_team": "New York Yankees", "away_team": "St. Louis Cardinals"},
            key_map={"batter_hits": "batter_hits"},
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["bookmaker"] for row in rows}, {"fanduel", "betmgm"})
        self.assertEqual({row["player_name"] for row in rows}, {"Jeremy Pena"})
        # The untracked market must not leak in.
        self.assertEqual({row["market"] for row in rows}, {"batter_hits"})
        for row in rows:
            self.assertEqual(row["kind"], "prop")
            self.assertEqual(row["commence_time"], "2026-08-06T00:15:00Z")


class AppendBookQuotesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        patcher = patch.object(quotes_module, "data_root", lambda: root)
        patcher.start()
        self.addCleanup(patcher.stop)
        # publish_hot_artifact reaches the network; the fixture owns that patch
        # so these tests cannot become order-dependent on whoever patched it
        # last (the #207 flake).
        publish = patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", return_value="PUBLISH_OK")
        publish.start()
        self.addCleanup(publish.stop)

    def _row(self, **overrides):
        row = {
            "kind": "prop",
            "event_id": "evt-1",
            "commence_time": "2026-08-06T00:15:00Z",
            "bookmaker": "fanduel",
            "market": "batter_hits",
            "selection": "over",
            "player_name": "Jeremy Pena",
            "line": 0.5,
            "price": "+410",
        }
        row.update(overrides)
        return row

    def test_appends_and_normalizes_price_strings(self) -> None:
        result = append_book_quotes(sport="mlb", date_str="2026-08-05", rows=[self._row()], captured_at="2026-08-05T22:00:00+00:00")
        self.assertEqual(result["appended"], 1)
        rows = read_book_quotes("mlb", "2026-08-05")
        self.assertEqual(len(rows), 1)
        # MLB stores "+410", basketball stores 410 -- consumers must not care.
        self.assertEqual(rows[0]["price"], 410)
        self.assertEqual(rows[0]["sport"], "mlb")

    def test_unchanged_quote_is_not_reappended(self) -> None:
        append_book_quotes(sport="mlb", date_str="2026-08-05", rows=[self._row()], captured_at="2026-08-05T22:00:00+00:00")
        second = append_book_quotes(sport="mlb", date_str="2026-08-05", rows=[self._row()], captured_at="2026-08-05T22:01:00+00:00")
        self.assertEqual(second["appended"], 0)
        self.assertEqual(len(read_book_quotes("mlb", "2026-08-05")), 1)

    def test_moved_price_is_appended_again(self) -> None:
        append_book_quotes(sport="mlb", date_str="2026-08-05", rows=[self._row()], captured_at="2026-08-05T22:00:00+00:00")
        append_book_quotes(sport="mlb", date_str="2026-08-05", rows=[self._row(price="+380")], captured_at="2026-08-05T22:01:00+00:00")
        # ... and a move BACK to the original price is a real second observation,
        # which a whole-file dedupe would have silently dropped.
        third = append_book_quotes(sport="mlb", date_str="2026-08-05", rows=[self._row()], captured_at="2026-08-05T22:02:00+00:00")
        self.assertEqual(third["appended"], 1)
        self.assertEqual([row["price"] for row in read_book_quotes("mlb", "2026-08-05")], [410, 380, 410])

    def test_different_books_are_distinct_quotes(self) -> None:
        result = append_book_quotes(
            sport="mlb",
            date_str="2026-08-05",
            rows=[self._row(), self._row(bookmaker="betmgm", price="+395")],
            captured_at="2026-08-05T22:00:00+00:00",
        )
        self.assertEqual(result["appended"], 2)
        self.assertEqual(sorted(result["books"]), ["betmgm", "fanduel"])

    def test_rows_without_price_or_line_are_dropped(self) -> None:
        result = append_book_quotes(
            sport="mlb",
            date_str="2026-08-05",
            rows=[self._row(price=None, line=None), {"bookmaker": "", "market": "h2h", "price": 100}],
            captured_at="2026-08-05T22:00:00+00:00",
        )
        self.assertEqual(result["appended"], 0)

    def test_failure_never_raises(self) -> None:
        with patch.object(quotes_module, "data_root", side_effect=RuntimeError("disk gone")):
            result = append_book_quotes(sport="mlb", date_str="2026-08-05", rows=[self._row()], captured_at="x")
        self.assertEqual(result["appended"], 0)
        self.assertIn("error", result)


class ClosingAndBestPriceTests(unittest.TestCase):
    """Closing lines become a lookup rather than a transition stamp -- the fix
    for prop closing capture being structurally zero, not merely low."""

    def _quote(self, **overrides):
        row = {
            "sport": "mlb",
            "kind": "prop",
            "event_id": "evt-1",
            "bookmaker": "fanduel",
            "segment": "full",
            "market": "batter_hits",
            "selection": "over",
            "player_name": "Jeremy Pena",
            "commence_time": "2026-08-06T00:15:00Z",
            "snapshot_ts": "2026-08-05T22:00:00Z",
            "line": 0.5,
            "price": 410,
        }
        row.update(overrides)
        return row

    def test_closing_is_last_quote_before_commence(self) -> None:
        rows = [
            self._quote(snapshot_ts="2026-08-05T20:00:00Z", price=430),
            self._quote(snapshot_ts="2026-08-06T00:10:00Z", price=395),
            # After first pitch: an in-play number, must never be the close.
            self._quote(snapshot_ts="2026-08-06T01:00:00Z", price=200),
        ]
        closing = closing_quotes(rows)
        self.assertEqual(len(closing), 1)
        self.assertEqual(next(iter(closing.values()))["price"], 395)

    def test_missing_commence_time_is_skipped_not_guessed(self) -> None:
        self.assertEqual(closing_quotes([self._quote(commence_time=None)]), {})

    def test_best_price_across_books_handles_the_sign_boundary(self) -> None:
        rows = [
            self._quote(bookmaker="fanduel", price=-120),
            self._quote(bookmaker="betmgm", price=-110),
            self._quote(bookmaker="draftkings", price=100),
        ]
        best = best_price_by_market(rows)
        self.assertEqual(len(best), 1)
        chosen = next(iter(best.values()))
        # +100 pays more than -110, which pays more than -120.
        self.assertEqual(chosen["price"], 100)
        self.assertEqual(chosen["bookmaker"], "draftkings")

    def test_best_price_separates_different_lines(self) -> None:
        rows = [self._quote(line=0.5, price=410), self._quote(line=1.5, price=900)]
        self.assertEqual(len(best_price_by_market(rows)), 2)


class MlbEndToEndQuoteLogTests(unittest.TestCase):
    """Proves the wiring, not just the extractors: the real
    fetch_and_write_live_odds_for_date entrypoint must land per-book quotes on
    disk AND leave the three snapshot artifacts shape-identical.

    The #207 lesson made concrete -- that diagnostic was correct code sitting on
    a call path nothing reached, and only a trace of the real chain found it.
    """

    def setUp(self) -> None:
        import scripts.fetch_mlb_oddsapi_local as fetcher

        self.fetcher = fetcher
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.out_dir = self.root / "snapshots"
        self.out_dir.mkdir(parents=True, exist_ok=True)

        patch.object(quotes_module, "data_root", lambda: self.root).start()
        self.addCleanup(patch.stopall)
        patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", return_value="PUBLISH_OK").start()
        patch.dict(os.environ, {"ODDS_API_KEY": "test-key"}, clear=False).start()
        # The provenance diagnostic reaches for real roots; it is out of scope
        # here and is documented as never able to fail a refresh.
        patch.object(self.fetcher, "diagnose_odds_history_provenance", lambda *a, **k: None).start()

    def _http_get(self, url: str, params: dict, timeout: int = 30):
        event = {
            "id": "evt-1",
            "commence_time": "2026-08-06T00:15:00Z",
            "home_team": "New York Yankees",
            "away_team": "St. Louis Cardinals",
        }
        # Order matters: the per-event props endpoint is
        # /sports/{sport}/events/{id}/odds, so it ALSO ends in "/odds" and must
        # be matched before the slate endpoint.
        if "/events/" in url:
            return {**event, **_prop_payload()}, {}
        if url.endswith("/events"):
            return [event], {}
        return [{**event, **_event_payload()}], {}

    def test_quotes_land_on_disk_and_snapshots_are_unchanged(self) -> None:
        patch.object(self.fetcher, "_http_get", self._http_get).start()
        result = self.fetcher.fetch_and_write_live_odds_for_date(
            "2026-08-05", out_dir=self.out_dir, hitter_markets=["batter_hits"]
        )
        self.assertIn(result["status"], {"ok", "warning"})

        rows = read_book_quotes("mlb", "2026-08-05")
        self.assertGreater(len(rows), 0, "no per-book quotes were written")
        # The defect this exists to fix: props with a bookmaker on them.
        prop_rows = [row for row in rows if row["kind"] == "prop"]
        self.assertGreater(len(prop_rows), 0)
        self.assertGreater(len({row["bookmaker"] for row in prop_rows}), 1, "props collapsed to one book again")
        # And event linkage, without which a closing line can never be looked up.
        for row in prop_rows:
            self.assertTrue(row["commence_time"])
            self.assertTrue(row["event_id"])
        game_rows = [row for row in rows if row["kind"] == "game"]
        self.assertGreater(len({row["bookmaker"] for row in game_rows}), 1, "game lines collapsed to one book again")

        # The three snapshot artifacts must not have grown a new key -- four
        # consumers read them and assume the current shape.
        for name in ("oddsapi_game_lines", "oddsapi_pitcher_props", "oddsapi_hitter_props"):
            doc = json.loads((self.out_dir / f"{name}_2026_08_05.json").read_text(encoding="utf-8"))
            self.assertNotIn("_book_quotes", doc, f"{name} leaked the internal quote carrier")


if __name__ == "__main__":
    unittest.main()
