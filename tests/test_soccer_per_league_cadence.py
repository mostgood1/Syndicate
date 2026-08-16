"""`#440` Phase 1c — per-league soccer pregame cadence.

Why this is its own file rather than more cases in
`test_pregame_cadence_fixture_aware.py`: that file pins the SPORT-level ladder,
and the whole point of 1c is that sport granularity gives the wrong answer for
soccer. Keeping them apart means a change to one cannot quietly satisfy the
other's assertions.

The measurement that motivates all of it: over 336 modelled hours against the
real 2026 fixture lists, the 24h tier was reached in **0.0% of sport-hours** and
**49.3% of league-hours**. At sport granularity the gate made soccer *worse*
(+69% sweeps/day), because `_next_fixture_epoch` returns the MINIMUM across ten
leagues and something always kicks off soon.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import syndicate.features.shared.live_refresh_loop as loop


HOUR = 3600.0
NOW = 1_787_000_000.0


class _Event:
    """Matches the real adapter's shape: league lives in `event_id`, not a field."""

    def __init__(self, event_id: str, epoch: float | None):
        self.event_id = event_id
        self._epoch = epoch

    def start_time_epoch(self):
        if self._epoch is None:
            raise ValueError("no start time")
        return self._epoch


def _schedule(mapping):
    """mapping: {date_offset_index: [_Event, ...]} -> a fetch_schedule_for_date stub."""

    calls = {"dates": []}

    def _fetch(sport, date_str):
        calls["dates"].append(date_str)
        return mapping.get(len(calls["dates"]) - 1, [])

    return _fetch, calls


class LeagueFromEventId(unittest.TestCase):
    def test_prefixed_id_yields_league(self):
        self.assertEqual(loop._league_from_event_id("la_liga:401882923"), "la_liga")
        self.assertEqual(loop._league_from_event_id("MLS:123"), "mls")

    def test_unprefixed_returns_none_rather_than_guessing(self):
        """THE DANGEROUS DEFAULT. Bucketing everything under one invented league
        reads as 'a league kicks off in 20 minutes' and pins the whole sport to
        the fastest tier -- the exact failure 1c exists to remove."""
        self.assertIsNone(loop._league_from_event_id("401882923"))
        self.assertIsNone(loop._league_from_event_id(""))
        self.assertIsNone(loop._league_from_event_id(None))
        self.assertIsNone(loop._league_from_event_id(":123"))


class NextFixtureByLeague(unittest.TestCase):
    def setUp(self):
        loop._NEXT_FIXTURE_BY_LEAGUE_CACHE.clear()

    def test_does_NOT_short_circuit_on_the_first_date_with_a_fixture(self):
        """THE BUG THIS FUNCTION IS SHAPED AROUND.

        `_next_fixture_epoch` (sport-level) stops at the first date that yields
        anything, which is correct when there is one clock. Here, MLS playing
        tonight says nothing about la_liga, and stopping early would leave
        la_liga ABSENT -- which the caller cannot distinguish from 'no fixture',
        the permissive answer that sweeps.
        """
        fetch, calls = _schedule({
            0: [_Event("mls:1", NOW + 2 * HOUR)],
            2: [_Event("la_liga:2", NOW + 50 * HOUR)],
        })
        with patch.object(loop, "fetch_schedule_for_date", fetch):
            out = loop._next_fixture_epoch_by_league("soccer", now_epoch=NOW)
        self.assertEqual(set(out), {"mls", "la_liga"})
        self.assertGreater(len(calls["dates"]), 1, "must keep scanning past the first hit")

    def test_keeps_the_earliest_fixture_per_league(self):
        fetch, _ = _schedule({
            0: [_Event("mls:late", NOW + 9 * HOUR), _Event("mls:early", NOW + 4 * HOUR)],
        })
        with patch.object(loop, "fetch_schedule_for_date", fetch):
            out = loop._next_fixture_epoch_by_league("soccer", now_epoch=NOW)
        self.assertEqual(out["mls"], NOW + 4 * HOUR)

    def test_past_fixtures_and_unreadable_events_are_ignored(self):
        fetch, _ = _schedule({
            0: [
                _Event("mls:past", NOW - HOUR),
                _Event("mls:broken", None),
                _Event("mls:ok", NOW + 6 * HOUR),
                _Event("unprefixed", NOW + HOUR),
            ],
        })
        with patch.object(loop, "fetch_schedule_for_date", fetch):
            out = loop._next_fixture_epoch_by_league("soccer", now_epoch=NOW)
        self.assertEqual(out, {"mls": NOW + 6 * HOUR})

    def test_one_unreadable_date_does_not_decide_the_whole_answer(self):
        def _fetch(sport, date_str):
            if date_str.endswith("-01"):
                raise OSError("artifact missing")
            return [_Event("mls:1", NOW + 30 * HOUR)]

        with patch.object(loop, "fetch_schedule_for_date", _fetch):
            out = loop._next_fixture_epoch_by_league("soccer", now_epoch=NOW)
        self.assertIn("mls", out)


class LeagueInterval(unittest.TestCase):
    def test_tiers_match_the_sport_level_ladder(self):
        for hours, expected in ((1, None), (6, 2 * 3600), (24, 8 * 3600), (72, 24 * 3600)):
            interval, reason = loop._league_interval_from_epoch(NOW + hours * HOUR, now_epoch=NOW)
            self.assertEqual(interval, expected, f"{hours}h out")
            self.assertTrue(reason, "every tier must name itself")

    def test_absent_fixture_is_the_MIDDLE_tier_and_says_so(self):
        """Unknown must not default permissive, and must not default silent."""
        interval, reason = loop._league_interval_from_epoch(None, now_epoch=NOW)
        self.assertEqual(interval, loop._PREGAME_SWEEP_INTERVAL_FALLBACK)
        self.assertIn("unresolved", reason)

    def test_kicked_off_defers_to_the_live_path(self):
        interval, reason = loop._league_interval_from_epoch(NOW - 60, now_epoch=NOW)
        self.assertIsNone(interval)
        self.assertEqual(reason, "fixture_in_progress")


class DueLeagues(unittest.TestCase):
    def setUp(self):
        loop._NEXT_FIXTURE_BY_LEAGUE_CACHE.clear()

    def _run(self, events, markers):
        fetch, _ = _schedule({0: events})
        with patch.object(loop, "fetch_schedule_for_date", fetch):
            return loop._due_leagues_for_sport("soccer", now_epoch=NOW, markers=markers)

    def test_THE_POINT_mls_sweeps_while_europe_rests(self):
        """The single outcome 1c exists to produce, on a US evening."""
        due, reasons = self._run(
            [_Event("mls:1", NOW + 2 * HOUR), _Event("la_liga:1", NOW + 60 * HOUR)],
            {loop._league_marker_key("soccer", "la_liga"): NOW - 600},
        )
        self.assertIn("mls", due)
        self.assertNotIn("la_liga", due)
        self.assertIn("skip", reasons["la_liga"])

    def test_no_marker_fails_open(self):
        due, reasons = self._run([_Event("la_liga:1", NOW + 60 * HOUR)], {})
        self.assertEqual(due, ["la_liga"])
        self.assertIn("no_marker", reasons["la_liga"])

    def test_swept_inside_its_interval_is_dropped(self):
        due, _ = self._run(
            [_Event("la_liga:1", NOW + 60 * HOUR)],
            {loop._league_marker_key("soccer", "la_liga"): NOW - 60},
        )
        self.assertEqual(due, [])

    def test_marker_older_than_the_interval_is_due_again(self):
        due, _ = self._run(
            [_Event("la_liga:1", NOW + 60 * HOUR)],
            {loop._league_marker_key("soccer", "la_liga"): NOW - (25 * HOUR)},
        )
        self.assertEqual(due, ["la_liga"])

    def test_unparseable_marker_fails_open(self):
        due, _ = self._run(
            [_Event("la_liga:1", NOW + 60 * HOUR)],
            {loop._league_marker_key("soccer", "la_liga"): "not-a-number"},
        )
        self.assertEqual(due, ["la_liga"])

    def test_every_league_gets_a_reason_even_when_skipped(self):
        """A league dropped silently is indistinguishable from a league that
        stopped having fixtures."""
        due, reasons = self._run(
            [_Event("mls:1", NOW + 2 * HOUR), _Event("la_liga:1", NOW + 60 * HOUR)],
            {loop._league_marker_key("soccer", "la_liga"): NOW - 60},
        )
        self.assertEqual(set(reasons), {"mls", "la_liga"})
        self.assertTrue(all(reasons.values()))

    def test_marker_key_is_namespaced_against_sport_slugs(self):
        self.assertEqual(loop._league_marker_key("soccer", "MLS"), "soccer:mls")
        self.assertNotEqual(loop._league_marker_key("soccer", "mls"), "mls")


class FilterIntegration(unittest.TestCase):
    """`_apply_pregame_sport_cadence` is where the decision actually lands."""

    def setUp(self):
        loop._NEXT_FIXTURE_BY_LEAGUE_CACHE.clear()

    def _apply(self, events, markers, *, enabled=True, live=False):
        fetch, _ = _schedule({0: events})
        with patch.object(loop, "fetch_schedule_for_date", fetch), \
             patch.object(loop, "_league_scoped_cadence_enabled", lambda: enabled), \
             patch.object(loop, "_read_pregame_sport_sweep_epochs", lambda: dict(markers)), \
             patch.object(loop, "central_today_iso", lambda: "2026-08-16"), \
             patch.dict(loop._LIVE_STATUS_CHECKERS, {"soccer": lambda d: live}, clear=False):
            return loop._apply_pregame_sport_cadence(
                ["soccer"], now_epoch=NOW, force_sports=set()
            )

    def test_soccer_is_SKIPPED_when_no_league_is_due(self):
        """The outcome that removes the MLB-peak overlap."""
        kept, skipped = self._apply(
            [_Event("la_liga:1", NOW + 60 * HOUR)],
            {loop._league_marker_key("soccer", "la_liga"): NOW - 60},
        )
        self.assertEqual(kept, [])
        self.assertEqual(skipped, ["soccer"])

    def test_soccer_is_KEPT_when_one_league_is_due(self):
        kept, skipped = self._apply(
            [_Event("mls:1", NOW + 2 * HOUR), _Event("la_liga:1", NOW + 60 * HOUR)],
            {loop._league_marker_key("soccer", "la_liga"): NOW - 60},
        )
        self.assertEqual(kept, ["soccer"])
        self.assertEqual(skipped, [])

    def test_a_live_match_sweeps_regardless_of_tiers(self):
        """Fail-open on liveness, same rule the per-sport path already had."""
        kept, _ = self._apply(
            [_Event("la_liga:1", NOW + 60 * HOUR)],
            {loop._league_marker_key("soccer", "la_liga"): NOW - 60},
            live=True,
        )
        self.assertEqual(kept, ["soccer"])

    def test_flag_off_does_NOT_take_the_league_path(self):
        """1c must be independently switchable; with it off, soccer keeps its
        prior behaviour and 1b is untouched."""
        with patch.object(loop, "_pregame_sweep_interval_for_tick", return_value=0) as spy:
            kept, _ = self._apply(
                [_Event("la_liga:1", NOW + 60 * HOUR)],
                {loop._league_marker_key("soccer", "la_liga"): NOW - 60},
                enabled=False,
            )
        spy.assert_called()
        self.assertEqual(kept, ["soccer"])


class MarkerStamping(unittest.TestCase):
    def setUp(self):
        loop._NEXT_FIXTURE_BY_LEAGUE_CACHE.clear()

    def test_due_leagues_are_stamped_or_the_gate_never_goes_quiet(self):
        """THE FAILURE THIS GUARDS: if only `soccer` were stamped, every league
        would read `no_marker` forever, fail open, and the gate would look
        enabled while changing nothing."""
        written = {}
        fetch, _ = _schedule({0: [_Event("mls:1", NOW + 20 * HOUR)]})
        with patch.object(loop, "fetch_schedule_for_date", fetch), \
             patch.object(loop, "_league_scoped_cadence_enabled", lambda: True), \
             patch.object(loop, "_read_pregame_sport_sweep_epochs", lambda: {}), \
             patch.object(loop, "write_json_file", lambda p, d: written.update(d)), \
             patch.object(loop, "_pregame_sport_sweep_epochs_path", lambda: "x.json"):
            loop._record_pregame_sport_sweep_epochs(NOW, ["soccer"])
        self.assertEqual(written.get("soccer"), NOW)
        self.assertEqual(written.get("soccer:mls"), NOW)

    def test_a_league_stamp_failure_does_not_lose_the_sport_stamp(self):
        written = {}
        with patch.object(loop, "_league_scoped_cadence_enabled", lambda: True), \
             patch.object(loop, "_read_pregame_sport_sweep_epochs", lambda: {}), \
             patch.object(loop, "_due_leagues_for_sport", side_effect=RuntimeError("boom")), \
             patch.object(loop, "write_json_file", lambda p, d: written.update(d)), \
             patch.object(loop, "_pregame_sport_sweep_epochs_path", lambda: "x.json"):
            loop._record_pregame_sport_sweep_epochs(NOW, ["soccer"])
        self.assertEqual(written.get("soccer"), NOW)


if __name__ == "__main__":
    unittest.main()
