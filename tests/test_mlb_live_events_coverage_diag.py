from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.fetch_mlb_oddsapi_local import _diagnose_live_events_coverage
from scripts.fetch_mlb_oddsapi_local import _fetch_live_events_for_date


def _schedule_fixture(games: list[dict]) -> list[dict]:
    return [
        {
            "gamePk": index + 1,
            "gameDate": game.get("game_date", "2026-08-05T18:00:00Z"),
            "status": {"abstractGameState": game["abstract"], "detailedState": game["detailed"]},
            "teams": {
                "away": {"team": {"name": game["away"]}},
                "home": {"team": {"name": game["home"]}},
            },
        }
        for index, game in enumerate(games)
    ]


class DiagnoseLiveEventsCoverageTests(unittest.TestCase):
    """Diagnostic for the pitcher live-lens investigation: the market-lines
    snapshot that gates _current_live_pitcher_prop_rows showed
    events_matched=1 while an earlier board read had shown 8 live games --
    but those two reads were ~3 hours apart, so the low count could equally
    mean OddsAPI's /events response was thin AT THAT MOMENT, or that most of
    the slate had simply finished by then. This writes a same-moment
    comparison (OddsAPI raw/filtered counts vs. MLB's own schedule-derived
    live count) so a future read during an actual live window answers the
    question directly instead of by inference across mismatched timestamps.
    """

    def test_writes_a_same_moment_comparison_and_never_raises(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fake_root = Path(tmp_dir) / "mlb_source"
            schedule_path = fake_root / "source_artifacts" / "data" / "daily" / "snapshots" / "2026-08-05" / "schedule_raw.json"
            schedule_path.parent.mkdir(parents=True, exist_ok=True)
            schedule_path.write_text(
                json.dumps(
                    _schedule_fixture(
                        [
                            {"away": "Seattle Mariners", "home": "Texas Rangers", "abstract": "Live", "detailed": "In Progress"},
                            {"away": "Boston Red Sox", "home": "New York Yankees", "abstract": "Live", "detailed": "In Progress"},
                            {"away": "Atlanta Braves", "home": "Miami Marlins", "abstract": "Final", "detailed": "Final"},
                        ]
                    )
                ),
                encoding="utf-8",
            )
            reports_dir = Path(tmp_dir) / "reports"
            raw_events = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
            matched_events = [{"id": "1"}]
            with patch("scripts.fetch_mlb_oddsapi_local.default_mlb_source_root", return_value=fake_root), patch(
                "syndicate.features.shared.refresh_state_store.reports_root", return_value=reports_dir
            ):
                _diagnose_live_events_coverage("2026-08-05", raw_events, matched_events)

            written = json.loads((reports_dir / "mlb_odds_diag" / "live_events_coverage_2026-08-05.json").read_text(encoding="utf-8"))

        self.assertEqual(written["oddsapi_raw_event_count"], 3)
        self.assertEqual(written["oddsapi_date_matched_count"], 1)
        self.assertEqual(written["mlb_schedule_live_count"], 2)
        self.assertEqual(written["mlb_schedule_total_count"], 3)

    def test_a_write_failure_never_raises_or_breaks_the_caller(self) -> None:
        # Best-effort by design: this must never take down the real fetch.
        with patch(
            "syndicate.features.shared.refresh_state_store.reports_root",
            side_effect=RuntimeError("disk unavailable"),
        ):
            _diagnose_live_events_coverage("2026-08-05", [{"id": "1"}], [{"id": "1"}])  # must not raise

    def test_fetch_live_events_for_date_still_returns_the_filtered_list(self) -> None:
        # The diagnostic is a side effect; the real return value must be
        # exactly what it was before instrumentation.
        raw_response = {
            "events": [
                {"id": "1", "commence_time": "2026-08-05T18:00:00Z"},
                {"id": "2", "commence_time": "2026-01-01T18:00:00Z"},
            ]
        }
        with patch("scripts.fetch_mlb_oddsapi_local._http_get", return_value=(raw_response, {})), patch(
            "scripts.fetch_mlb_oddsapi_local._diagnose_live_events_coverage"
        ) as mocked_diag:
            result = _fetch_live_events_for_date("fake-key", "2026-08-05")

        self.assertEqual([event["id"] for event in result], ["1"])
        mocked_diag.assert_called_once()
        call_args = mocked_diag.call_args.args
        self.assertEqual(call_args[0], "2026-08-05")
        self.assertEqual(len(call_args[1]), 2)  # raw, unfiltered
        self.assertEqual(len(call_args[2]), 1)  # date-matched


if __name__ == "__main__":
    unittest.main()
