"""The tick's sport list and the service's active-sports config never met.

`_LIVE_LENS_SPORTS` is the REGISTRY -- what has a builder, a validator and a
snapshot path. It was also being used as the answer to "what should this service
work on", which are different questions.

MEASURED 2026-08-08 on refresh-worker: `SYNDICATE_ACTIVE_SPORTS` is
`mlb,wnba,soccer,nfl`, and the loop built NBA every cycle anyway -- 1.6-42s and
up to +321MB container delta for a sport with no August slate, roughly 10% of
the long cycles (median 246s). `SYNDICATE_ACTIVE_SPORTS` was read in exactly two
places, `syndicate/app.py` and `blueprints/home.py`, both web navigation.

The risk in fixing it is larger than the fix: a background stage that stops for
a config reason and says nothing is precisely the defect this module keeps
shipping. So the resolution refuses to be silenced two ways (unset, and matches-
nothing) and names the skipped set on every tick.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from syndicate.features.shared import live_lens_loop


class ActiveSportsTests(unittest.TestCase):
    def test_the_registry_still_holds_every_implemented_sport(self) -> None:
        """Filtering must not be done by shrinking the registry. The dispatch
        tables are keyed off it, and a sport dropped from the tuple would look
        like a sport that was never implemented."""
        self.assertEqual(set(live_lens_loop._LIVE_LENS_SPORTS), set(live_lens_loop._LIVE_LENS_BUILDERS))
        self.assertIn("nba", live_lens_loop._LIVE_LENS_SPORTS)

    def test_refresh_workers_real_config_drops_nba(self) -> None:
        """The production value, verbatim, from the Render env-vars API."""
        with patch.dict(os.environ, {"SYNDICATE_ACTIVE_SPORTS": "mlb,wnba,soccer,nfl"}, clear=False):
            active = live_lens_loop._live_lens_active_sports()

        self.assertNotIn("nba", active)
        self.assertEqual(set(active), {"mlb", "wnba", "soccer", "nfl"})

    def test_unset_ticks_everything_rather_than_home_pys_two_sport_default(self) -> None:
        """`blueprints/home.py` defaults this variable to `"mlb,wnba"`. Inheriting
        that here would silently drop soccer, nfl AND nba from the tick on any
        service that forgot to set it -- turning a missing env var into three
        dead sports with no error anywhere."""
        env = {k: v for k, v in os.environ.items() if k != "SYNDICATE_ACTIVE_SPORTS"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(live_lens_loop._live_lens_active_sports(), live_lens_loop._LIVE_LENS_SPORTS)

    def test_a_value_matching_nothing_ticks_everything_not_nothing(self) -> None:
        """A typo or a renamed sport must not silence the entire loop. An empty
        intersection is far more likely to be a mistake than an intention."""
        with patch.dict(os.environ, {"SYNDICATE_ACTIVE_SPORTS": "cricket,kabaddi"}, clear=False):
            self.assertEqual(live_lens_loop._live_lens_active_sports(), live_lens_loop._LIVE_LENS_SPORTS)

    def test_whitespace_and_case_do_not_silently_drop_a_sport(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_ACTIVE_SPORTS": " MLB , WNBA "}, clear=False):
            self.assertEqual(set(live_lens_loop._live_lens_active_sports()), {"mlb", "wnba"})

    def test_the_skipped_set_is_named_on_every_tick(self) -> None:
        """A sport missing from `results` is indistinguishable from a sport
        whose tick never got that far. "Not configured for this service" and
        "failed" must not share a spelling."""
        with patch.dict(os.environ, {"SYNDICATE_ACTIVE_SPORTS": "mlb,wnba,soccer,nfl"}, clear=False), patch.object(
            live_lens_loop, "_run_live_lens_tick_for_sport", return_value={"ok": True}
        ) as mock_tick, patch.object(live_lens_loop, "write_json_file"):
            meta = live_lens_loop._run_live_lens_tick()

        self.assertEqual(meta["skippedSports"], ["nba"])
        self.assertEqual(set(meta["activeSports"]), {"mlb", "wnba", "soccer", "nfl"})
        self.assertNotIn("nba", meta["results"])
        self.assertNotIn("nba", [call.args[0] for call in mock_tick.call_args_list])

    def test_a_skipped_sport_does_not_make_the_tick_report_failure(self) -> None:
        """`ok` is computed over the sports this service actually owns. If a
        skipped sport counted as a failure, every tick would report not-ok
        forever and the flag would stop meaning anything."""
        with patch.dict(os.environ, {"SYNDICATE_ACTIVE_SPORTS": "mlb"}, clear=False), patch.object(
            live_lens_loop, "_run_live_lens_tick_for_sport", return_value={"ok": True}
        ), patch.object(live_lens_loop, "write_json_file"):
            meta = live_lens_loop._run_live_lens_tick()

        self.assertTrue(meta["ok"])
        self.assertEqual(sorted(meta["skippedSports"]), ["nba", "nfl", "soccer", "wnba"])


if __name__ == "__main__":
    unittest.main()
