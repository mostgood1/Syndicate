from __future__ import annotations

from pathlib import Path
import unittest


class UnifiedDailyUpdateActiveSportsTests(unittest.TestCase):
    def test_unified_daily_update_accepts_active_sports_gate(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "unified_daily_update.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("[string[]]$ActiveSports,", content)
        for sport in ("MLB", "NBA", "WNBA", "NHL", "NFL", "NCAAF", "NCAAB"):
            self.assertIn(f"if (Test-SportEnabled '{sport}') {{", content)


if __name__ == "__main__":
    unittest.main()