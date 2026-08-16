"""`#440` Phase 1b -- fixture-aware pregame sweep cadence.

The premise, measured in `#440` Phase 0/H1 (`reports/kickoff_census/latest.json`):
9 European soccer leagues, n=200, **0.0%** of kickoffs in the 18:00-01:00 CT band
and none at any hour after 14:00 -- while an elapsed-time cadence sweeps them in
every hour, MLB's evening peak included.

These tests pin the three properties that make the gate safe rather than merely
present:

  1. it is OFF by default (dark launch),
  2. an explicit env override still wins over the gate,
  3. an UNRESOLVED fixture does not fall to the permissive branch, and says why.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from syndicate.features.shared import live_refresh_loop as loop


HOUR = 3600.0
NOW = 1_760_000_000.0


class FixtureAwareCadenceTests(unittest.TestCase):
    def setUp(self) -> None:
        loop._NEXT_FIXTURE_CACHE.clear()
        self.addCleanup(loop._NEXT_FIXTURE_CACHE.clear)

    # ---- 1. dark launch -------------------------------------------------

    def test_disabled_by_default_leaves_baseline_untouched(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(loop._fixture_aware_cadence_enabled())
            # soccer's 8h baseline and the 2h fallback both survive.
            self.assertEqual(loop._pregame_sweep_interval_for_tick("soccer", now_epoch=NOW), 8 * 3600)
            self.assertEqual(loop._pregame_sweep_interval_for_tick("mlb", now_epoch=NOW), 2 * 3600)

    def test_enabled_flag_is_read(self):
        with patch.dict(os.environ, {"SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE": "true"}, clear=True):
            self.assertTrue(loop._fixture_aware_cadence_enabled())

    # ---- 2. the tiers ---------------------------------------------------

    def _interval_with_fixture_in(self, hours: float | None, sport: str = "mlb") -> int:
        target = None if hours is None else NOW + hours * HOUR
        with patch.dict(os.environ, {"SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE": "true"}, clear=True):
            with patch.object(loop, "_next_fixture_epoch", return_value=target):
                return loop._pregame_sweep_interval_for_tick(sport, now_epoch=NOW)

    def test_far_fixture_drops_to_daily_heartbeat(self):
        # An idle single-league sport days from its next game must not keep
        # sweeping every 2h. (Soccer motivated the change but is EXCLUDED at
        # sport granularity -- see SoccerIsExcludedUntilPerLeagueScoping.)
        self.assertEqual(self._interval_with_fixture_in(72), 24 * 3600)

    def test_mid_fixture_gets_eight_hours(self):
        self.assertEqual(self._interval_with_fixture_in(24), 8 * 3600)

    def test_near_fixture_gets_two_hours(self):
        self.assertEqual(self._interval_with_fixture_in(6), 2 * 3600)

    def test_imminent_fixture_defers_to_the_t_window_ramp(self):
        # Inside 3h the T-75/T-10 ramp owns cadence, so the gate must fall back
        # to the baseline rather than inventing a competing number.
        self.assertEqual(self._interval_with_fixture_in(1), loop._PREGAME_SWEEP_INTERVAL_FALLBACK)

    def test_mls_is_protected_by_the_soccer_exclusion(self):
        # MLS kicks off in the US evening -- 94.6% of 111 fixtures -- and a
        # clock-based rule would throttle it. Today it is protected by soccer
        # being excluded outright, so its cadence is the 8h baseline whatever
        # the fixture clock says. WHEN 1c LANDS AND THE EXCLUSION IS REMOVED,
        # this test must be rewritten to assert MLS keeps a FAST tier near its
        # own kickoff -- do not simply delete it.
        self.assertEqual(self._interval_with_fixture_in(2, sport="soccer"), 8 * 3600)
        self.assertEqual(self._interval_with_fixture_in(5, sport="soccer"), 8 * 3600)

    # ---- 3. unknown must not default permissive -------------------------

    def test_unresolved_fixture_returns_middle_tier_with_a_reason(self):
        interval, reason = None, None
        with patch.dict(os.environ, {"SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE": "true"}, clear=True):
            with patch.object(loop, "_next_fixture_epoch", return_value=None):
                interval, reason = loop._fixture_aware_interval_seconds("soccer", now_epoch=NOW)
        self.assertEqual(interval, loop._PREGAME_SWEEP_INTERVAL_FALLBACK)
        self.assertIn("unresolved", reason)

    def test_resolver_exception_is_attributable_not_silent(self):
        with patch.dict(os.environ, {"SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE": "true"}, clear=True):
            with patch.object(loop, "_next_fixture_epoch", side_effect=RuntimeError("boom")):
                interval, reason = loop._fixture_aware_interval_seconds("soccer", now_epoch=NOW)
        self.assertEqual(interval, loop._PREGAME_SWEEP_INTERVAL_FALLBACK)
        self.assertIn("RuntimeError", reason)

    def test_fixture_in_progress_defers_to_the_live_path(self):
        with patch.dict(os.environ, {"SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE": "true"}, clear=True):
            with patch.object(loop, "_next_fixture_epoch", return_value=NOW - 600):
                interval, reason = loop._fixture_aware_interval_seconds("soccer", now_epoch=NOW)
        self.assertIsNone(interval)
        self.assertEqual(reason, "fixture_in_progress")

    # ---- 4. the override must outrank the gate --------------------------

    def test_explicit_per_sport_env_override_beats_the_gate(self):
        env = {
            "SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE": "true",
            "SYNDICATE_PREGAME_SWEEP_INTERVAL_SECONDS_SOCCER": "300",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(loop, "_next_fixture_epoch", return_value=NOW + 72 * HOUR):
                # Without the override this would be 24h; the escape hatch wins.
                self.assertEqual(loop._pregame_sweep_interval_for_tick("soccer", now_epoch=NOW), 300)

    # ---- 5. the staleness-ceiling coupling must stay severed ------------

    def test_baseline_function_is_untouched_by_the_gate(self):
        """`recommendation_engine` multiplies the BASELINE by 3 for a staleness
        ceiling. If the gate leaked into it, a far-out sport's 24h heartbeat
        would silently make a 72h-old recommendation read as fresh."""
        # Uses mlb, not soccer: soccer is excluded from the gate, so it could
        # not show the divergence this test exists to prove.
        env = {"SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE": "true"}
        with patch.dict(os.environ, env, clear=True):
            with patch.object(loop, "_next_fixture_epoch", return_value=NOW + 72 * HOUR):
                self.assertEqual(loop._pregame_sweep_interval_seconds("mlb"), 2 * 3600)
                self.assertEqual(loop._pregame_sweep_interval_for_tick("mlb", now_epoch=NOW), 24 * 3600)


class NextFixtureResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        loop._NEXT_FIXTURE_CACHE.clear()
        self.addCleanup(loop._NEXT_FIXTURE_CACHE.clear)

    def test_short_circuits_on_the_first_date_with_a_future_fixture(self):
        class _Event:
            def __init__(self, epoch): self._epoch = epoch
            def start_time_epoch(self): return self._epoch

        calls: list[str] = []

        def _fake(sport, date_str, **kwargs):
            calls.append(date_str)
            return [_Event(NOW + 5 * HOUR)]

        with patch.object(loop, "fetch_schedule_for_date", _fake):
            found = loop._next_fixture_epoch("soccer", now_epoch=NOW)
        self.assertEqual(found, NOW + 5 * HOUR)
        self.assertEqual(len(calls), 1, "must stop scanning once a future fixture is found")

    def test_past_fixtures_are_ignored(self):
        class _Event:
            def __init__(self, epoch): self._epoch = epoch
            def start_time_epoch(self): return self._epoch

        def _fake(sport, date_str, **kwargs):
            return [_Event(NOW - HOUR), _Event(NOW + 2 * HOUR)]

        with patch.object(loop, "fetch_schedule_for_date", _fake):
            self.assertEqual(loop._next_fixture_epoch("mlb", now_epoch=NOW), NOW + 2 * HOUR)

    def test_absent_schedule_yields_none_not_an_exception(self):
        with patch.object(loop, "fetch_schedule_for_date", side_effect=RuntimeError("no adapter")):
            self.assertIsNone(loop._next_fixture_epoch("ncaab", now_epoch=NOW))


class SoccerIsExcludedUntilPerLeagueScoping(unittest.TestCase):
    """Soccer must NOT ride the fixture gate at sport granularity.

    Modelled against the real 2026 fixture lists over 336 hours: soccer's
    sport-level clock is the MINIMUM gap across ten leagues, so the 24h tier is
    reached in 0.0% of hours and the gate yields 5.08 sweeps/day against 3.00
    today -- a 69% INCREASE, in both call volume and the MLB-peak overlap the
    lane exists to remove. The benefit is entirely in per-league scoping (1c).

    These tests exist so the exclusion cannot be dropped silently when 1c lands:
    removing it must break a test that says why.
    """

    def test_soccer_ignores_the_gate_even_when_enabled(self):
        with patch.dict(os.environ, {"SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE": "true"}, clear=False):
            with patch.object(loop, "_next_fixture_epoch", return_value=NOW + 100 * HOUR) as spy:
                # A 100h gap would be the 24h tier for any other sport.
                self.assertEqual(loop._pregame_sweep_interval_for_tick("soccer", now_epoch=NOW), 8 * 3600)
                spy.assert_not_called()

    def test_a_single_league_sport_still_gets_the_gate(self):
        # The control: same conditions, different sport, gate applies. Without
        # this, a bug that disabled the gate entirely would pass the test above.
        with patch.dict(os.environ, {"SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE": "true"}, clear=False):
            with patch.object(loop, "_next_fixture_epoch", return_value=NOW + 100 * HOUR):
                self.assertEqual(loop._pregame_sweep_interval_for_tick("mlb", now_epoch=NOW), 24 * 3600)

    def test_soccer_baseline_interval_is_unchanged(self):
        self.assertEqual(loop._pregame_sweep_interval_seconds("soccer"), 8 * 3600)


if __name__ == "__main__":
    unittest.main()
