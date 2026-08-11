from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from syndicate.features.shared.candidate_slate_filter import (
    DROP_NO_MATCH,
    DROP_NO_SLATE,
    DROP_NOT_TODAY,
    stamp_and_filter_candidates_to_slate,
)

TODAY = "2026-08-11"


def _chip(away_abbr, home_abbr, start_utc):
    return {
        "away": {"abbr": away_abbr, "name": away_abbr},
        "home": {"abbr": home_abbr, "name": home_abbr},
        "start_time_utc": start_utc,
        "game_key": f"{away_abbr}-{home_abbr}-{start_utc}",
    }


class CandidateSlateFilterTests(unittest.TestCase):
    """Layer 2 is today only; Layer 1 may carry future days (`#353`)."""

    def test_a_todays_game_is_kept_and_stamped(self):
        cands = [{"sport_slug": "mlb", "matchup": "CIN @ CWS"}]
        chips = {"mlb": [_chip("CIN", "CWS", "2026-08-11T22:40:00+00:00")]}
        kept, cov = stamp_and_filter_candidates_to_slate(cands, selected_date=TODAY, chips_by_sport=chips)
        self.assertEqual(cov["kept"], 1)
        self.assertEqual(kept[0]["game_date"], TODAY)
        self.assertEqual(kept[0]["game_date_source"], "game_chip_team_pair")

    def test_a_future_game_is_dropped_as_not_today(self):
        # The 91 soccer candidates for 08-15..08-24 that made the board useless.
        cands = [{"sport_slug": "soccer", "matchup": "NE @ TOR"}]
        chips = {"soccer": [_chip("NE", "TOR", "2026-08-15T23:30:00+00:00")]}
        kept, cov = stamp_and_filter_candidates_to_slate(cands, selected_date=TODAY, chips_by_sport=chips)
        self.assertEqual(kept, [])
        self.assertEqual(cov["dropped"][DROP_NOT_TODAY], 1)
        self.assertEqual(cov["dropped"][DROP_NO_MATCH], 0)

    def test_a_late_start_still_counts_as_today_in_central(self):
        # An MLB slate spans two UTC dates: 02:10Z is the previous evening in
        # Central. A UTC test would cut every slate in half.
        cands = [{"sport_slug": "mlb", "matchup": "KC @ LAD"}]
        chips = {"mlb": [_chip("KC", "LAD", "2026-08-12T02:10:00+00:00")]}
        kept, _ = stamp_and_filter_candidates_to_slate(cands, selected_date=TODAY, chips_by_sport=chips)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["game_date"], TODAY)

    def test_a_sport_with_no_slate_is_dropped_quietly(self):
        cands = [{"sport_slug": "nfl", "matchup": "TEN @ SF"}]
        kept, cov = stamp_and_filter_candidates_to_slate(cands, selected_date=TODAY, chips_by_sport={"nfl": []})
        self.assertEqual(kept, [])
        self.assertEqual(cov["dropped"][DROP_NO_SLATE], 1)
        self.assertEqual(cov["dropped"][DROP_NO_MATCH], 0)

    def test_an_alias_gap_is_the_only_reason_that_reports_a_defect(self):
        # Chips exist and this candidate matched none -- indistinguishable from a
        # correct exclusion at the count level, which is why it is separated.
        cands = [{"sport_slug": "soccer", "matchup": "LEE @ MTL"}]
        chips = {"soccer": [_chip("NE", "TOR", "2026-08-11T23:30:00+00:00")]}
        kept, cov = stamp_and_filter_candidates_to_slate(cands, selected_date=TODAY, chips_by_sport=chips)
        self.assertEqual(kept, [])
        self.assertEqual(cov["dropped"][DROP_NO_MATCH], 1)
        self.assertTrue(cov["unmatched_samples"])
        self.assertEqual(cov["unmatched_samples"][0]["matchup"], "LEE @ MTL")

    def test_a_sport_losing_every_candidate_to_alias_gaps_is_LOUD(self):
        # The guard against a sport silently vanishing: MLB going 5 -> 0 with
        # chips present must not look like a correct date exclusion.
        cands = [{"sport_slug": "mlb", "matchup": "ZZZ @ YYY"}]
        chips = {"mlb": [_chip("CIN", "CWS", "2026-08-11T22:40:00+00:00")]}
        buf = io.StringIO()
        with redirect_stdout(buf):
            stamp_and_filter_candidates_to_slate(cands, selected_date=TODAY, chips_by_sport=chips)
        out = buf.getvalue()
        self.assertIn("SPORT_LOST_ALL_CANDIDATES", out)
        self.assertIn("sport=mlb", out)

    def test_losing_every_candidate_to_DATES_is_not_an_alarm(self):
        # Soccer having no games today is correct, not a defect. Alarming on it
        # would make the signal untrustworthy.
        cands = [{"sport_slug": "soccer", "matchup": "NE @ TOR"}]
        chips = {"soccer": [_chip("NE", "TOR", "2026-08-15T23:30:00+00:00")]}
        buf = io.StringIO()
        with redirect_stdout(buf):
            stamp_and_filter_candidates_to_slate(cands, selected_date=TODAY, chips_by_sport=chips)
        self.assertNotIn("SPORT_LOST_ALL_CANDIDATES", buf.getvalue())

    def test_a_candidate_with_no_matchup_cannot_be_dated(self):
        cands = [{"sport_slug": "mlb", "matchup": None}]
        chips = {"mlb": [_chip("CIN", "CWS", "2026-08-11T22:40:00+00:00")]}
        kept, cov = stamp_and_filter_candidates_to_slate(cands, selected_date=TODAY, chips_by_sport=chips)
        self.assertEqual(kept, [])
        self.assertEqual(cov["dropped"][DROP_NO_MATCH], 1)
