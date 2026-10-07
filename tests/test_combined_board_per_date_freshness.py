"""The combined board judges each window date against its own cadence (lane `web-restart-healthz`).

Fleet 2026-10-07 morning: 11 board saves/hour, yet the board read "stale" ~45 of every
60 minutes, because the verdict compared the window's OLDEST input -- a next-day
shortlist rebuilt hourly by design (SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS
3600) -- against the 15-minute limit. User decision: "Judge each date fairly".

Pinned:
  * the window's FIRST date keeps SYNDICATE_INTELLIGENCE_BOARD_STALE_AFTER_SECONDS (900);
  * later dates get SYNDICATE_INTELLIGENCE_BOARD_NEXT_DAY_STALE_AFTER_SECONDS (4500);
  * `computed_at` stays the oldest stamp;
  * `#334`'s serve-time recompute (age from `computed_at` vs `freshness_sla_seconds`)
    reaches the same verdict at write time AND at later reads (the clock advances);
  * no clock-relative ("today") key is introduced.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import intelligence_state as state

TODAY = "2026-10-07"
TOMORROW = "2026-10-08"


def _stamp(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _shortlist(written_at: str) -> dict:
    return {"written_at": written_at, "cards": [{"sport": "mlb", "selection": "row"}]}


def _meta(today_age: float, tomorrow_age: float) -> dict:
    shortlists = {TODAY: _shortlist(_stamp(today_age)), TOMORROW: _shortlist(_stamp(tomorrow_age))}
    state._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
    with patch.dict(os.environ, {}, clear=False), \
         patch.object(state, "read_layer2_shortlist", side_effect=lambda d: shortlists.get(str(d))), \
         patch.object(state, "_read_single_date_response_for_combining", return_value=None), \
         patch.object(state, "board_l2a_fallback_enabled", return_value=True):
        os.environ.pop("SYNDICATE_INTELLIGENCE_BOARD_STALE_AFTER_SECONDS", None)
        os.environ.pop("SYNDICATE_INTELLIGENCE_BOARD_NEXT_DAY_STALE_AFTER_SECONDS", None)
        return state.read_combined_intelligence_response(dates=[TODAY, TOMORROW])["state_meta"]


class PerDateVerdict(unittest.TestCase):
    def test_the_10_07_morning_shape_is_fresh(self):
        meta = _meta(today_age=1200 - 900, tomorrow_age=3840)   # today 5 min, tomorrow 64 min
        self.assertEqual(meta["freshness_status"], "fresh")
        self.assertTrue(meta["is_fresh"])
        self.assertEqual(meta["window_oldest_date"], TOMORROW)
        self.assertEqual(meta["computed_at"], meta["dates"][TOMORROW]["written_at"])   # unchanged meaning
        self.assertEqual(meta["freshness_limits_seconds"], {"first_date": 900.0, "later_dates": 4500.0})

    def test_a_stale_FIRST_date_is_still_stale_even_when_tomorrow_is_fresh(self):
        meta = _meta(today_age=1300, tomorrow_age=600)
        self.assertEqual(meta["freshness_status"], "stale")
        self.assertEqual(meta["freshness_binding_date"], TODAY)

    def test_a_next_day_input_past_its_own_limit_is_stale(self):
        meta = _meta(today_age=60, tomorrow_age=4700)
        self.assertEqual(meta["freshness_status"], "stale")
        self.assertEqual(meta["freshness_binding_date"], TOMORROW)

    def test_the_serve_time_recompute_agrees_now_and_later(self):
        meta = _meta(today_age=600, tomorrow_age=3000)   # fresh now; today crosses 900 in 300 s
        rebuilt = state._apply_freshness_recompute({"state_meta": dict(meta)})["state_meta"]
        self.assertEqual(rebuilt["freshness_status"], "fresh")
        later = datetime.now(timezone.utc) + timedelta(seconds=400)
        with patch.object(state, "_timestamp_age_seconds",
                          side_effect=lambda s: (later - datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() if s else None):
            rebuilt_later = state._apply_freshness_recompute({"state_meta": dict(meta)})["state_meta"]
        self.assertEqual(rebuilt_later["freshness_status"], "stale")   # today is now 1000 s > 900

    def test_no_today_key_is_served(self):
        meta = _meta(today_age=60, tomorrow_age=60)
        self.assertFalse([key for key in meta if key.startswith("today")])


if __name__ == "__main__":
    unittest.main()
