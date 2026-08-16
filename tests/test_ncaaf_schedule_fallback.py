"""`#445` — an absent engine schedule must reach the CFBD fallback, not raise.

The fallback was already written, already documented, and already called by
`main` on an empty result. It was unreachable because `load_engine_schedule`
opened the path unguarded, so an absent file raised `FileNotFoundError` and
killed the run first.

Measured 2026-08-16 on refresh-worker: every `season=2026 week=1` launch died on
`college_football_schedule_2025_predicted_totals_enhanced.csv`, and the staleness
gate relaunched it indefinitely. All 278 of those files in the checkout are
season 2025; no 2026 file exists and nothing writes one.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scripts.generate_smartsim2_ncaaf_projections as gen


class AbsentEngineScheduleFallsBack(unittest.TestCase):
    def test_absent_file_returns_empty_instead_of_raising(self):
        """THE BUG. Raising here made the CFBD fallback unreachable."""
        missing = Path(tempfile.gettempdir()) / "definitely-not-here-445.csv"
        self.assertFalse(missing.exists())
        with patch.object(gen, "ENHANCED_CSV", missing):
            rows = gen.load_engine_schedule(2026, 1)
        self.assertEqual(rows, [])

    def test_present_file_still_filters_by_season_and_week(self):
        """The fix must not weaken the normal path.

        The filter is season-aware even though the FILENAME is pinned to 2025 --
        so a 2025 file must not leak 2025 rows into a 2026 request.
        """
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "enhanced.csv"
            csv_path.write_text(
                "season,week,home_team,away_team\n"
                "2025,1,Alabama,Georgia\n"
                "2025,2,Ohio State,Michigan\n"
                "2026,1,Texas,Oklahoma\n",
                encoding="utf-8",
            )
            with patch.object(gen, "ENHANCED_CSV", csv_path):
                self.assertEqual(
                    [r["home_team"] for r in gen.load_engine_schedule(2025, 1)], ["Alabama"]
                )
                self.assertEqual(
                    [r["home_team"] for r in gen.load_engine_schedule(2026, 1)], ["Texas"]
                )
                # a season the file does not cover -> empty -> fallback, not a crash
                self.assertEqual(gen.load_engine_schedule(2027, 1), [])

    def test_absence_is_announced(self):
        """Silent absence is the `#443` shape; this one says which path was missing."""
        missing = Path(tempfile.gettempdir()) / "definitely-not-here-445b.csv"
        with patch.object(gen, "ENHANCED_CSV", missing), patch("builtins.print") as printer:
            gen.load_engine_schedule(2026, 1)
        printed = " ".join(str(c.args[0]) for c in printer.call_args_list if c.args)
        self.assertIn("ENGINE_SCHEDULE_ABSENT", printed)
        self.assertIn(str(missing), printed)


class TheFallbackItselfIsStillSound(unittest.TestCase):
    def test_cfbd_fallback_keeps_only_fbs_vs_fbs(self):
        """Guards the thing the fallback is for: it must not widen the slate.

        If this ever admitted FCS opponents, `#445`'s fix would quietly change
        which games get projected rather than just keeping the run alive.
        """
        games = {
            ("a", "b"): {"homeClassification": "fbs", "awayClassification": "fbs",
                         "homeTeam": "Texas", "awayTeam": "Oklahoma"},
            ("c", "d"): {"homeClassification": "fbs", "awayClassification": "fcs",
                         "homeTeam": "Alabama", "awayTeam": "Mercer"},
        }
        rows = gen.games_from_cfbd_when_engine_schedule_empty(games)
        self.assertEqual(rows, [{"home_team": "Texas", "away_team": "Oklahoma"}])

    def test_fallback_skips_rows_missing_a_team(self):
        games = {("a", "b"): {"homeClassification": "fbs", "awayClassification": "fbs",
                              "homeTeam": "", "awayTeam": "Oklahoma"}}
        self.assertEqual(gen.games_from_cfbd_when_engine_schedule_empty(games), [])


if __name__ == "__main__":
    unittest.main()
