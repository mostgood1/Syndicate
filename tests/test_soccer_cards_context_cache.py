"""`#565` -- memoising soccer's league-week context WITHOUT freezing live scores.

THE COST. On refresh-worker `-fzb6v` 2026-08-26, soccer emitted five
`board_contract_begin` lines in one 60-second window, 12-14 seconds apart --
**~12.5 s per league-week**. `_SoccerDataProvider.games()` runs 10 leagues x 2
matchdays = 20 of these PER DATE, and adjacent board-window dates resolve to the
same weeks, so it is largely the same 20 builds repeated. 13m25s of a 19m43s
board build.

THE TRAP, and it is why the first attempt was reverted. These payloads carry
`live_state`, and `game_chip_scoreboard._game_flags` reads it to set each chip's
live/final state. A plain TTL memo FREEZES LIVE SOCCER SCORES -- re-creating the
exact staleness `#564` was opened to fix, on the same surface, in the same week.

THE KEY INCLUDES THE THING THAT WOULD GO STALE: the live poller's own artifact.
If any match's status, clock or score moved, the fingerprint moves and the entry
misses. A cached context can therefore only be served while nothing live has
changed -- exactly when it is indistinguishable from a fresh build.

`test_a_live_score_change_invalidates` is the load-bearing one. If it ever goes
green with the vintage removed from the key, this cache has become the bug it
was written to avoid.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from syndicate.features.soccer import cards


def _live(status="in", clock="12'", home=1, away=0, event_id="e1"):
    return {"games": {event_id: {
        "status": status, "status_state": status,
        "status_display_clock": clock, "home_score": home, "away_score": away,
    }}}


class SoccerCardsContextCacheTests(unittest.TestCase):
    def setUp(self):
        cards.clear_soccer_cards_context_cache()
        cards.reset_soccer_cards_context_cache_stats()

    def _harness(self, live):
        calls = {"n": 0}

        def fake_build(league, week=None, season=None):
            calls["n"] += 1
            return {"games": [{"event_id": "e1", "league": league}], "build": calls["n"]}

        return calls, patch.multiple(
            cards,
            _build_cards_page_context_uncached=fake_build,
            live_state_payload=lambda league, date: live[0],
        )

    def test_the_same_league_week_is_built_once_while_nothing_live_moves(self):
        live = [_live()]
        calls, p = self._harness(live)
        with p:
            for _ in range(3):
                cards.build_cards_page_context("epl", 4, 2026)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(cards.soccer_cards_context_cache_stats()["hits"], 2)

    def test_a_live_score_change_invalidates(self):
        # THE LOAD-BEARING TEST. A goal must reach the chip strip immediately.
        live = [_live(home=1)]
        calls, p = self._harness(live)
        with p:
            cards.build_cards_page_context("epl", 4, 2026)
            live[0] = _live(home=2)          # somebody scored
            cards.build_cards_page_context("epl", 4, 2026)
        self.assertEqual(calls["n"], 2, "a score change MUST rebuild, not serve cache")

    def test_a_clock_change_invalidates(self):
        live = [_live(clock="12'")]
        calls, p = self._harness(live)
        with p:
            cards.build_cards_page_context("epl", 4, 2026)
            live[0] = _live(clock="13'")
            cards.build_cards_page_context("epl", 4, 2026)
        self.assertEqual(calls["n"], 2)

    def test_a_status_transition_invalidates(self):
        # pregame -> in -> post are the three the chip renders.
        live = [_live(status="pre")]
        calls, p = self._harness(live)
        with p:
            cards.build_cards_page_context("epl", 4, 2026)
            live[0] = _live(status="in")
            cards.build_cards_page_context("epl", 4, 2026)
            live[0] = _live(status="post")
            cards.build_cards_page_context("epl", 4, 2026)
        self.assertEqual(calls["n"], 3)

    def test_a_new_match_going_live_invalidates(self):
        live = [{"games": {}}]
        calls, p = self._harness(live)
        with p:
            cards.build_cards_page_context("epl", 4, 2026)
            live[0] = _live()
            cards.build_cards_page_context("epl", 4, 2026)
        self.assertEqual(calls["n"], 2)

    def test_an_unreadable_live_payload_is_its_own_vintage(self):
        # "I could not read live state" must not look like "same live state as
        # last time" -- that is the freeze this key exists to prevent.
        self.assertEqual(cards._live_vintage.__name__, "_live_vintage")
        with patch.object(cards, "live_state_payload", side_effect=RuntimeError("boom")):
            self.assertEqual(cards._live_vintage("epl"), "error")
        with patch.object(cards, "live_state_payload", return_value=None):
            self.assertEqual(cards._live_vintage("epl"), "absent")
        with patch.object(cards, "live_state_payload", return_value={"games": {}}):
            self.assertEqual(cards._live_vintage("epl"), "quiet")
        self.assertEqual(len({"error", "absent", "quiet"}), 3)

    def test_different_weeks_and_leagues_are_not_conflated(self):
        live = [_live()]
        calls, p = self._harness(live)
        with p:
            cards.build_cards_page_context("epl", 4, 2026)
            cards.build_cards_page_context("epl", 5, 2026)
            cards.build_cards_page_context("la_liga", 4, 2026)
        self.assertEqual(calls["n"], 3)

    def test_callers_cannot_mutate_each_others_context(self):
        live = [_live()]
        calls, p = self._harness(live)
        with p:
            first = cards.build_cards_page_context("epl", 4, 2026)
            first["games"][0]["event_id"] = "MUTATED"
            second = cards.build_cards_page_context("epl", 4, 2026)
        self.assertEqual(second["games"][0]["event_id"], "e1")

    def test_zero_ttl_disables_it_and_skips_the_vintage_read(self):
        # The switch that backs this out without a deploy. It must also not pay
        # for the fingerprint it is no longer using.
        live = [_live()]
        calls, p = self._harness(live)
        vintage_calls = {"n": 0}

        def counting_vintage(league):
            vintage_calls["n"] += 1
            return "x"

        with p, patch.object(cards, "_live_vintage", side_effect=counting_vintage), \
             patch.dict(os.environ, {"SYNDICATE_SOCCER_CARDS_CONTEXT_TTL_SECONDS": "0"}):
            for _ in range(3):
                cards.build_cards_page_context("epl", 4, 2026)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(vintage_calls["n"], 0)

    def test_the_cache_is_bounded(self):
        live = [_live()]
        calls, p = self._harness(live)
        with p:
            for week in range(120):
                cards.build_cards_page_context("epl", week, 2026)
        self.assertLessEqual(len(cards._CARDS_CONTEXT_CACHE), 96)


if __name__ == "__main__":
    unittest.main()
