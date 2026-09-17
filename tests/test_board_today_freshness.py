"""The combined board must say WHICH DATE is stale, not only that one is.

WHY THIS FILE EXISTS (lane `board-today-freshness`). `state_meta.computed_at` is
the OLDEST dated input across the whole window (`#563`), and the board chip
rendered "as of" that one stamp. Measured on web 2026-09-17 17:05Z, same
instant: today's shortlist `written_at` 16:52:10Z (813.6 s old), tomorrow's
16:17:19Z (2904.8 s); the served board carried `computed_at` 16:17:19Z,
`freshness_status` "stale", and `by_date` with no stamp at all. Since the
next-day floor went to 3600 s that morning, tomorrow is the oldest input most
of the time, so the chip reported TOMORROW's age as the board's.

WHAT IS PINNED, and the direction of each:
  * `state_meta.dates[<date>].written_at` is that date's own stamp, and equals
    the shortlist's `written_at` for a shortlist-only date (the value
    `/api/board/layer2-shortlist?date=` serves).
  * The window-level keys are unchanged, and `computed_at` is always
    `dates[window_oldest_date].written_at`.
  * `#334`'s recompute leaves the new keys alone and reaches the same verdict.
  * NO clock-relative key is served. The payload is cached, and a "today" or a
    per-date age frozen into it outlives the clock it was computed against
    (learnings 2026-09-15, FORBIDDEN). The chip derives both itself.
  * `_layer2_fallback_recommendations(dated_vintages=None)` is byte-identical to
    the old call (session 0f5b256e's condition for the keyword).

On the pre-change code, every test here that reads `dates`,
`window_oldest_date` or `dated_vintages` fails.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import intelligence_state as state

TODAY = "2026-09-17"
TOMORROW = "2026-09-18"


def _stamp(seconds_ago: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _shortlist(written_at: str, cards: int = 1) -> dict:
    return {"written_at": written_at, "cards": [{"sport": "mlb", "selection": f"row {i}"} for i in range(cards)]}


class FallbackDatedVintagesTests(unittest.TestCase):
    """The additive keyword, and 0f5b256e's byte-identical condition."""

    SHORTLISTS = {
        TODAY: _shortlist("2026-09-17T16:52:10Z", cards=2),
        TOMORROW: _shortlist("2026-09-18T16:17:19Z", cards=1),
        # A shortlist that exists but put nothing on the board. It must not set
        # a date's age, on either path (`#603`).
        "2026-09-19": _shortlist("2026-09-17T09:00:00Z", cards=0),
    }

    def _call(self, **kwargs):
        with patch.object(state, "read_layer2_shortlist", side_effect=lambda d: self.SHORTLISTS.get(str(d))), \
             patch.object(state, "_refresh_layer2_live_state", return_value=0):
            return state._layer2_fallback_recommendations([TODAY, TOMORROW, "2026-09-19"], **kwargs)

    def test_dated_vintages_None_leaves_cards_and_vintages_byte_identical(self):
        baseline_vintages: list[str] = []
        baseline = self._call(vintages=baseline_vintages)
        for label, extra in (("explicit None", {"dated_vintages": None}), ("a map", {"dated_vintages": {}})):
            with self.subTest(label):
                vintages: list[str] = []
                cards = self._call(vintages=vintages, **extra)
                self.assertEqual(json.dumps(cards, sort_keys=True), json.dumps(baseline, sort_keys=True))
                self.assertEqual(json.dumps(vintages), json.dumps(baseline_vintages))

    def test_each_stamp_is_kept_under_its_date(self):
        dated: dict[str, str] = {}
        self._call(dated_vintages=dated)
        self.assertEqual(dated, {TODAY: "2026-09-17T16:52:10Z", TOMORROW: "2026-09-18T16:17:19Z"})

    def test_a_date_that_put_no_cards_on_the_board_is_not_dated(self):
        dated: dict[str, str] = {}
        self._call(dated_vintages=dated)
        self.assertNotIn("2026-09-19", dated)

    def test_the_keyword_works_without_vintages(self):
        dated: dict[str, str] = {}
        self._call(dated_vintages=dated)
        self.assertEqual(len(dated), 2)

    def test_the_artifact_is_still_read_once_per_date(self):
        reads: list[str] = []

        def fake(d):
            reads.append(str(d))
            return self.SHORTLISTS.get(str(d))

        with patch.object(state, "read_layer2_shortlist", side_effect=fake), \
             patch.object(state, "_refresh_layer2_live_state", return_value=0):
            state._layer2_fallback_recommendations([TODAY, TOMORROW], vintages=[], dated_vintages={})
        self.assertEqual(reads, [TODAY, TOMORROW])


class CombinedBoardPerDateStampTests(unittest.TestCase):
    """`state_meta.dates` on the served combined board."""

    def _read(self, shortlists, state_payloads=None, dates=(TODAY, TOMORROW)):
        state_payloads = state_payloads or {}
        state._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
        with patch.object(state, "read_layer2_shortlist", side_effect=lambda d: shortlists.get(str(d))), \
             patch.object(state, "_read_single_date_response_for_combining", side_effect=lambda d: state_payloads.get(str(d))), \
             patch.object(state, "board_l2a_fallback_enabled", return_value=True):
            return state.read_combined_intelligence_response(dates=list(dates))

    def test_the_production_shape_today_fresh_tomorrow_stale(self):
        # The 2026-09-17 17:05Z reading, as ages.
        today_stamp, tomorrow_stamp = _stamp(814), _stamp(2905)
        meta = self._read({TODAY: _shortlist(today_stamp), TOMORROW: _shortlist(tomorrow_stamp)})["state_meta"]

        # Each date carries its OWN stamp: the value the shortlist route serves.
        self.assertEqual(meta["dates"][TODAY]["written_at"], today_stamp)
        self.assertEqual(meta["dates"][TOMORROW]["written_at"], tomorrow_stamp)
        self.assertEqual(meta["dates"][TODAY]["written_at_source"], "layer2_shortlist")

        # The window-level verdict is unchanged: still the oldest input, still stale.
        self.assertEqual(meta["computed_at"], tomorrow_stamp)
        self.assertEqual(meta["freshness_status"], "stale")
        self.assertFalse(meta["is_fresh"])
        self.assertEqual(meta["window_oldest_date"], TOMORROW)

    def test_computed_at_is_always_the_window_oldest_dates_stamp(self):
        cases = {
            "today older": ({TODAY: _shortlist(_stamp(3000)), TOMORROW: _shortlist(_stamp(60))}, TODAY),
            "tomorrow older": ({TODAY: _shortlist(_stamp(60)), TOMORROW: _shortlist(_stamp(3000))}, TOMORROW),
        }
        for label, (shortlists, oldest_date) in cases.items():
            with self.subTest(label):
                meta = self._read(shortlists)["state_meta"]
                self.assertEqual(meta["window_oldest_date"], oldest_date)
                self.assertEqual(meta["computed_at"], meta["dates"][meta["window_oldest_date"]]["written_at"])

    def test_a_date_with_both_sources_takes_the_older_and_names_both(self):
        state_stamp, shortlist_stamp = _stamp(1500), _stamp(300)
        payloads = {TODAY: {"state_last_updated": state_stamp, "by_sport": {"mlb": [{"selection": "legacy row"}]}}}
        meta = self._read({TODAY: _shortlist(shortlist_stamp)}, state_payloads=payloads, dates=(TODAY,))["state_meta"]
        entry = meta["dates"][TODAY]
        self.assertEqual(entry["written_at"], state_stamp)
        self.assertEqual(entry["written_at_source"], "state")
        self.assertEqual(entry["sources"], {"state": state_stamp, "layer2_shortlist": shortlist_stamp})
        # Same rule as the window, so the two cannot disagree.
        self.assertEqual(meta["computed_at"], state_stamp)

    def test_a_state_payload_with_no_rows_does_not_date_its_date(self):
        payloads = {TODAY: {"state_last_updated": _stamp(5000), "by_sport": {"mlb": []}}}
        shortlist_stamp = _stamp(120)
        meta = self._read({TODAY: _shortlist(shortlist_stamp)}, state_payloads=payloads, dates=(TODAY,))["state_meta"]
        self.assertEqual(meta["dates"][TODAY]["sources"], {"layer2_shortlist": shortlist_stamp})

    def test_an_undated_date_is_absent_not_null(self):
        meta = self._read({TODAY: _shortlist(_stamp(60)), TOMORROW: _shortlist("not a date")})["state_meta"]
        self.assertIn(TODAY, meta["dates"])
        self.assertNotIn(TOMORROW, meta["dates"])

    def test_nothing_dated_gives_an_empty_map_and_no_oldest_date(self):
        meta = self._read({})["state_meta"]
        self.assertEqual(meta["dates"], {})
        self.assertIsNone(meta["window_oldest_date"])
        self.assertIsNone(meta["computed_at"])

    def test_no_clock_relative_key_is_served(self):
        # THE DESIGN DECISION, PINNED. This payload is cached, so "which date is
        # today" and "how old is it" would be frozen at build time. Stamps only.
        meta = self._read({TODAY: _shortlist(_stamp(60)), TOMORROW: _shortlist(_stamp(3000))})["state_meta"]
        self.assertFalse([key for key in meta if key.startswith("today")], meta.keys())
        for day, entry in meta["dates"].items():
            with self.subTest(day):
                self.assertEqual(set(entry), {"written_at", "written_at_source", "sources"})


class RecomputeLeavesPerDateStampsAloneTests(unittest.TestCase):
    """`#334` rebuilds age/status/is_fresh from `computed_at` on every served payload."""

    def test_the_recompute_keeps_the_new_keys_and_the_same_verdict(self):
        state._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
        shortlists = {TODAY: _shortlist(_stamp(60)), TOMORROW: _shortlist(_stamp(3000))}
        with patch.object(state, "read_layer2_shortlist", side_effect=lambda d: shortlists.get(str(d))), \
             patch.object(state, "_read_single_date_response_for_combining", return_value=None), \
             patch.object(state, "board_l2a_fallback_enabled", return_value=True):
            meta = state.read_combined_intelligence_response(dates=[TODAY, TOMORROW])["state_meta"]
        before = json.loads(json.dumps(meta))
        for container in ({"state_meta": dict(meta)}, {"response": {"state_meta": dict(meta)}}):
            rebuilt = state._apply_freshness_recompute(container)
            block = rebuilt.get("state_meta") or rebuilt["response"]["state_meta"]
            with self.subTest(nested="response" in rebuilt):
                self.assertEqual(block["dates"], before["dates"])
                self.assertEqual(block["window_oldest_date"], before["window_oldest_date"])
                self.assertEqual(block["computed_at"], before["computed_at"])
                self.assertEqual(block["freshness_status"], before["freshness_status"])
                self.assertEqual(block["is_fresh"], before["is_fresh"])


if __name__ == "__main__":
    unittest.main()
