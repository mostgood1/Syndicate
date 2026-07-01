from __future__ import annotations

from pathlib import Path
import unittest


class DailyUpdatePublishPathTests(unittest.TestCase):
    def test_unified_daily_update_includes_nba_wnba_basketball_publish_contract(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "unified_daily_update.ps1"
        script_text = script_path.read_text(encoding="utf-8")

        self.assertIn("Add-BasketballPublishPaths -SportRootRelative 'data/nba_source' -IncludeSeasonBettingCards", script_text)
        self.assertIn("Add-BasketballPublishPaths -SportRootRelative 'data/wnba_source' -IncludeSeasonBettingCards", script_text)
        self.assertIn("REFRESH_PLAYER_LOGS_FETCH_ON_MISS = '1'", script_text)
        self.assertIn("SYNDICATE_WNBA_SOURCE_APP_FALLBACK = '1'", script_text)
        self.assertIn("${rootRelative}/tracking/odds_history.json", script_text)
        self.assertIn("${rootRelative}/artifacts/${sportSlug}/odds_history.json", script_text)
        self.assertIn('Add-PathsUnderRoot -RelativeRoot "${rootRelative}/manifests"', script_text)
        self.assertIn('Add-PathsUnderRoot -RelativeRoot "${rootRelative}/source_artifacts/manifests"', script_text)


if __name__ == "__main__":
    unittest.main()
