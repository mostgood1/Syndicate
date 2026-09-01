"""Soccer gets per-fixture closing sweeps — `#626`(f), Phase 0.

`#82` Phase 3 guarantees a full sweep at ~T-75m and ~T-10m per game, but only
for sports with a commence-time provider. Until 2026-09-01 that was MLB and
WNBA — 2 of 8 sports — so every other sport's "closing line" was whichever
drift point happened to land, and CLV's close is defined as the last pregame
price. Soccer is the worst case and the one the pregame-cadence comment names:
its drift interval is **8h**, so a close could miss kickoff by nearly four
hours.

The behavioural tests here pin the provider itself. `TWindowSweepSchedulerTests`
in `test_live_refresh_loop.py` already pins the window arithmetic that consumes
it, and is deliberately not duplicated.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared import live_refresh_loop

CSV_HEADER = "league,event_id,home_team,away_team,commence_time,market,side,line,price,book\n"


def _row(event_id: str, commence: str, *, market: str = "h2h", book: str = "draftkings") -> str:
    return f"epl,{event_id},Home FC,Away FC,{commence},{market},Home FC,,{-110},{book}\n"


class SoccerCommenceTimeProviderTests(unittest.TestCase):
    def _write(self, root: Path, league: str, body: str) -> None:
        path = root / "soccer_source" / league / "api" / "odds" / "game_odds_current.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def _times(self, leagues, files: dict[str, str]):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for league, body in files.items():
                self._write(root, league, body)
            with patch.object(live_refresh_loop, "data_root", return_value=root):
                with patch("syndicate.features.soccer.sources.active_leagues_for_date", return_value=leagues):
                    return live_refresh_loop._soccer_commence_times("2026-09-01")

    def test_returns_one_entry_per_fixture_not_per_row(self) -> None:
        """The CSV is one row per (market, side, book); the provider returns fixtures."""
        body = CSV_HEADER + "".join(
            _row("evt-1", "2026-09-01T18:30:00Z", market=m, book=b)
            for m in ("h2h", "totals", "spreads")
            for b in ("draftkings", "fanduel")
        )
        times = self._times(["epl"], {"epl": body})
        self.assertEqual(len(times), 1, "six rows for one fixture must collapse to one entry")
        self.assertEqual(times[0][0], "evt-1")

    def test_parses_the_kickoff_and_sorts_by_it(self) -> None:
        body = CSV_HEADER + _row("late", "2026-09-01T20:00:00Z") + _row("early", "2026-09-01T18:30:00Z")
        times = self._times(["epl"], {"epl": body})
        self.assertEqual([event for event, _ in times], ["early", "late"])
        self.assertLess(times[0][1], times[1][1])

    def test_reads_every_league_in_season(self) -> None:
        times = self._times(
            ["epl", "la_liga"],
            {
                "epl": CSV_HEADER + _row("evt-epl", "2026-09-01T18:30:00Z"),
                "la_liga": CSV_HEADER + _row("evt-liga", "2026-09-01T19:00:00Z"),
            },
        )
        self.assertEqual({event for event, _ in times}, {"evt-epl", "evt-liga"})

    def test_a_league_out_of_season_is_not_read(self) -> None:
        """Scoping is `active_leagues_for_date`, the same spelling the live
        checker and the refresh orchestrator use."""
        times = self._times(
            ["epl"],
            {
                "epl": CSV_HEADER + _row("evt-epl", "2026-09-01T18:30:00Z"),
                "mls": CSV_HEADER + _row("evt-mls", "2026-09-01T23:00:00Z"),
            },
        )
        self.assertEqual([event for event, _ in times], ["evt-epl"])

    def test_fixtures_on_a_later_date_are_kept(self) -> None:
        """NOT date-filtered, deliberately: the window arithmetic admits only
        events inside 75 minutes, and a date filter would drop a late kickoff
        landing on the next Central date."""
        times = self._times(["epl"], {"epl": CSV_HEADER + _row("evt-next", "2026-09-03T18:30:00Z")})
        self.assertEqual([event for event, _ in times], ["evt-next"])

    def test_unparseable_and_empty_values_are_skipped_not_fatal(self) -> None:
        body = (
            CSV_HEADER
            + _row("", "2026-09-01T18:30:00Z")
            + _row("no-time", "")
            + _row("bad-time", "not-a-timestamp")
            + _row("good", "2026-09-01T18:30:00Z")
        )
        times = self._times(["epl"], {"epl": body})
        self.assertEqual([event for event, _ in times], ["good"])

    def test_missing_bundle_fails_open_to_empty(self) -> None:
        """A missing artifact costs precision, never a sweep storm."""
        self.assertEqual(self._times(["epl"], {}), [])

    def test_unresolvable_leagues_fail_open_to_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            with patch.object(live_refresh_loop, "data_root", return_value=Path(tmp)):
                with patch(
                    "syndicate.features.soccer.sources.active_leagues_for_date",
                    side_effect=RuntimeError("boom"),
                ):
                    self.assertEqual(live_refresh_loop._soccer_commence_times("2026-09-01"), [])


class SoccerTWindowRegistrationTests(unittest.TestCase):
    """Presence is not reachability: the provider must be REGISTERED, and the
    sport must have a live-status checker or it is never skipped while live."""

    def test_soccer_is_registered_as_a_commence_time_provider(self) -> None:
        self.assertIs(
            live_refresh_loop._T_WINDOW_COMMENCE_PROVIDERS.get("soccer"),
            live_refresh_loop._soccer_commence_times,
        )

    def test_every_registered_sport_has_a_live_status_checker(self) -> None:
        missing = [
            sport
            for sport in live_refresh_loop._T_WINDOW_COMMENCE_PROVIDERS
            if sport not in live_refresh_loop._LIVE_STATUS_CHECKERS
        ]
        self.assertEqual(missing, [], "a sport with no checker is never skipped while live")

    def test_a_due_soccer_fixture_schedules_a_ramp_sweep(self) -> None:
        """End to end through `_t_window_due_sports`, with nothing live."""
        checkers = {"soccer": lambda _date: False}
        times = {"soccer": [("evt-1", 1000.0 + 70 * 60)]}
        with patch.object(live_refresh_loop, "_LIVE_STATUS_CHECKERS", checkers):
            with patch.object(
                live_refresh_loop,
                "_commence_times_cached",
                side_effect=lambda sport, d, now_epoch: times.get(sport, []),
            ):
                with patch.object(live_refresh_loop, "_read_t_window_markers", return_value={}):
                    due = live_refresh_loop._t_window_due_sports(now_epoch=1000.0, date_str="2026-09-01")
        self.assertEqual(due, {"soccer": {"soccer:ramp:evt-1": 1000.0}})

    def test_a_live_soccer_slate_schedules_nothing(self) -> None:
        """Off-is-not-on for the skip: once anything is live the 60s cadence
        sweeps the whole slate, pregame fixtures included."""
        checkers = {"soccer": lambda _date: True}
        times = {"soccer": [("evt-1", 1000.0 + 70 * 60)]}
        with patch.object(live_refresh_loop, "_LIVE_STATUS_CHECKERS", checkers):
            with patch.object(
                live_refresh_loop,
                "_commence_times_cached",
                side_effect=lambda sport, d, now_epoch: times.get(sport, []),
            ):
                with patch.object(live_refresh_loop, "_read_t_window_markers", return_value={}):
                    due = live_refresh_loop._t_window_due_sports(now_epoch=1000.0, date_str="2026-09-01")
        self.assertEqual(due, {})

    def test_simultaneous_kickoffs_are_one_sport_entry(self) -> None:
        """Cost bound worth pinning: 6 fixtures at the same kickoff produce 6
        MARKERS under ONE sport key, and the caller sweeps per SPORT — so a
        crowded 3pm slate is one sweep, not six."""
        checkers = {"soccer": lambda _date: False}
        times = {"soccer": [(f"evt-{i}", 1000.0 + 70 * 60) for i in range(6)]}
        with patch.object(live_refresh_loop, "_LIVE_STATUS_CHECKERS", checkers):
            with patch.object(
                live_refresh_loop,
                "_commence_times_cached",
                side_effect=lambda sport, d, now_epoch: times.get(sport, []),
            ):
                with patch.object(live_refresh_loop, "_read_t_window_markers", return_value={}):
                    due = live_refresh_loop._t_window_due_sports(now_epoch=1000.0, date_str="2026-09-01")
        self.assertEqual(list(due), ["soccer"])
        self.assertEqual(len(due["soccer"]), 6)


if __name__ == "__main__":
    unittest.main()
