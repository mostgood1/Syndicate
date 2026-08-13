"""`#414` -- the indexed identity join must answer exactly as the full scan did.

The identity scan WAS the MLB board-build cost. Eight production samples fit
`total_s = 19.86s per million rows walked` (intercept -1.07s, R^2 = 0.918) and
every call walked the whole shard, because identity was decided by a linear
pass with no early exit.

Replacing that with an index is only safe if it is answer-preserving, and this
join is one whose wrong answers are SILENT: `quote_ref_for_bet`'s own docstring
records that a fallback which returned some other game's price is "strictly
worse than returning nothing", because a wrong quote misprices the card and
poisons CLV once #213 records it at bet time. A performance win that changed
one row in a thousand would not announce itself.

So these are differential tests, not spot checks. The reference implementation
is the OLD behaviour, produced by forcing the candidate union to every row --
which is what the pre-#414 code did by construction -- and the assertion is
that both paths return the same quote, over a grid of query shapes built to
exercise each identity signal and each way of missing.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import odds_book_quotes as obq
from syndicate.features.shared.odds_book_quotes import (
    append_book_quotes,
    quote_ref_for_bet,
    read_book_quotes,
)

DATE = "2026-08-06"
CAPTURED = "2026-08-06T18:59:30Z"

GAMES = [
    # (event_id, home, away, tri-code matchup the board would send)
    ("evt-nyy-bos", "New York Yankees", "Boston Red Sox", "BOS @ NYY"),
    ("evt-chc-lad", "Chicago Cubs", "Los Angeles Dodgers", "LAD @ CHC"),
    ("evt-bal-laa", "Baltimore Orioles", "Los Angeles Angels", "LAA @ BAL"),
]
PLAYERS = ["Aaron Judge", "Rafael Devers", "Seiya Suzuki", "Shohei Ohtani"]


def _row(*, event_id, home, away, market, selection, price, player=None, line=None, book="fanduel"):
    row = {
        "sport": "mlb",
        "event_id": event_id,
        "home_team": home,
        "away_team": away,
        "market": market,
        "selection": selection,
        "bookmaker": book,
        "price": price,
        "captured_at": CAPTURED,
    }
    if player is not None:
        row["player_name"] = player
    if line is not None:
        row["line"] = line
    return row


class _EverythingBucket(dict):
    """A bucket whose lookup returns EVERY row position.

    Forcing the union to all rows reproduces the pre-`#414` full scan exactly:
    the loop then applies the same three predicates, in the same order, to the
    same rows, in shard order. That makes the reference the real old code path
    rather than a paraphrase of it.
    """

    def __init__(self, count: int) -> None:
        super().__init__()
        self._all = list(range(count))

    def get(self, key, default=()):  # noqa: D102 - dict override
        return self._all


class QuoteJoinIndexEquivalence(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(obq, "data_root", lambda: Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        obq._BOOK_QUOTES_CACHE.clear()
        obq._BOOK_QUOTES_INDEX_CACHE.clear()

        rows = []
        for event_id, home, away, _matchup in GAMES:
            for market, selection in (("h2h", home), ("h2h", away), ("totals", "Over")):
                for book, price in (("fanduel", -110), ("draftkings", -105), ("betmgm", -120)):
                    rows.append(_row(event_id=event_id, home=home, away=away,
                                     market=market, selection=selection, price=price, book=book))
            for player in PLAYERS:
                for book, price in (("fanduel", -115), ("draftkings", 100)):
                    rows.append(_row(event_id=event_id, home=home, away=away,
                                     market="player_hits", selection="Over", price=price,
                                     player=player, line=1.5, book=book))
        append_book_quotes(sport="mlb", date_str=DATE, rows=rows, captured_at=CAPTURED, publish=False)
        self.assertGreater(len(read_book_quotes("mlb", DATE)), 40, "fixture did not persist")

    def _full_scan_result(self, **kwargs):
        """The same call with the candidate union forced to every row."""
        real = obq._quote_shard_index

        def everything(rows, cache_key):
            index = real(rows, cache_key)
            return {
                "by_event": _EverythingBucket(len(rows)),
                "by_player": _EverythingBucket(len(rows)),
                "team_groups": index["team_groups"],
            }

        with patch.object(obq, "_quote_shard_index", everything):
            return quote_ref_for_bet(**kwargs)

    def _queries(self):
        for event_id, home, away, matchup in GAMES:
            base = dict(sport="mlb", date_str=DATE)
            # by event_id
            yield {**base, "event_id": event_id, "market": "h2h", "selection": home}
            yield {**base, "event_id": event_id, "market": "totals", "selection": "Over"}
            # by player, no event -- the prop lane's join
            for player in PLAYERS:
                yield {**base, "player_name": player, "market": "player_hits", "selection": "Over", "line": 1.5}
            # by teams only, full names and tri-code matchup (the alias path)
            yield {**base, "home_team": home, "away_team": away, "market": "h2h", "selection": home}
            yield {**base, "matchup": matchup, "market": "h2h", "selection": away}
            # event id that does not exist, teams that do -- the #414 fallthrough
            yield {**base, "event_id": "gamepk-824804", "home_team": home, "away_team": away,
                   "market": "h2h", "selection": home}
            # nothing identifiable: must return None on BOTH paths
            yield {**base, "event_id": "nope", "market": "h2h", "selection": home}

    def test_indexed_join_matches_the_full_scan_on_every_query_shape(self) -> None:
        checked = 0
        for query in self._queries():
            with self.subTest(query=query):
                obq._BOOK_QUOTES_INDEX_CACHE.clear()
                indexed = quote_ref_for_bet(**query)
                obq._BOOK_QUOTES_INDEX_CACHE.clear()
                scanned = self._full_scan_result(**query)
                self.assertEqual(indexed, scanned)
                checked += 1
        # Guards against a generator that silently yields nothing -- an
        # all-passing loop over zero cases is the shape #288 left behind.
        self.assertGreaterEqual(checked, 30)

    def test_the_grid_actually_exercises_every_identity_signal(self) -> None:
        """A differential test proves equality, not coverage. If every query
        resolved by event_id, the team and player paths would be unverified and
        the suite would still be green."""
        reasons = set()
        for query in self._queries():
            obq._QUOTE_JOIN_STATS.clear()
            obq._BOOK_QUOTES_INDEX_CACHE.clear()
            quote_ref_for_bet(**query)
            reasons.update(k for k in obq._QUOTE_JOIN_STATS if k in
                           {"by_event", "by_player", "by_teams_fallthrough", "no_identity"})
        self.assertIn("by_event", reasons)
        self.assertIn("by_player", reasons)
        self.assertIn("by_teams_fallthrough", reasons)
        self.assertIn("no_identity", reasons)

    def test_the_index_actually_narrows(self) -> None:
        """The point of the change. `rows_walked` must fall well below the shard
        size -- if it does not, the index is present but inert, which would look
        exactly like success in the logs."""
        obq._QUOTE_JOIN_STATS.clear()
        obq._BOOK_QUOTES_INDEX_CACHE.clear()
        quote_ref_for_bet(sport="mlb", date_str=DATE, event_id=GAMES[0][0],
                          market="h2h", selection=GAMES[0][1])
        walked = obq._QUOTE_JOIN_STATS.get("rows_walked", 0)
        shard = obq._QUOTE_JOIN_STATS.get("shard_rows", 0)
        self.assertGreater(shard, 0)
        self.assertLess(walked, shard, "index did not narrow the candidate set")

    def test_a_stale_index_can_never_be_served(self) -> None:
        """The index is keyed by the rows cache key, so new rows for the same
        sport/date must not be answered from the old index."""
        obq._BOOK_QUOTES_INDEX_CACHE.clear()
        before = quote_ref_for_bet(sport="mlb", date_str=DATE, player_name="Aaron Judge",
                                   market="player_hits", selection="Over", line=1.5)
        self.assertIsNotNone(before)
        append_book_quotes(
            sport="mlb", date_str=DATE,
            rows=[_row(event_id=GAMES[0][0], home=GAMES[0][1], away=GAMES[0][2],
                       market="player_hits", selection="Over", price=-101,
                       player="Brand New Player", line=1.5)],
            captured_at="2026-08-06T19:30:00Z", publish=False,
        )
        after = quote_ref_for_bet(sport="mlb", date_str=DATE, player_name="Brand New Player",
                                  market="player_hits", selection="Over", line=1.5)
        self.assertIsNotNone(after, "a row appended after the index was built was invisible")


if __name__ == "__main__":
    unittest.main()
