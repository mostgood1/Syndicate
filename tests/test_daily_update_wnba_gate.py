from __future__ import annotations

from pathlib import Path
import unittest


class WnbaDailyUpdateGateTests(unittest.TestCase):
    def test_wnba_gate_requires_smartsim_only_for_nonzero_slates(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "unified_daily_update.ps1"
        script_text = script_path.read_text(encoding="utf-8")

        self.assertIn("$scheduledGameCount = if ($scheduleCheck.known -and $null -ne $scheduleCheck.count) { [int]$scheduleCheck.count } else { $null }", script_text)
        self.assertIn("$requireSmartSimArtifacts = ($null -eq $scheduledGameCount) -or ($scheduledGameCount -gt 0)", script_text)
        self.assertIn("if ($requireSmartSimArtifacts) {", script_text)
        self.assertIn("Write-Host \"WNBA advanced-data gate warning: missing smart_sim artifacts for $DateValue; continuing with core WNBA outputs\" -ForegroundColor Yellow", script_text)
        self.assertIn("return", script_text)


if __name__ == "__main__":
    unittest.main()