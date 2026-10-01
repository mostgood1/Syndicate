"""`build_intelligence_overview(sports=...)` hydrates only the named sports.

Added for the admin candidate-trace route (2026-10-01): a `?sport=mlb` trace
used to build every configured sport in the web request. These assert which
sports actually reach `_build_sport_overview` -- the branch -- not the length of
the returned list, which a stub could satisfy either way.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import syndicate.features.intelligence as intelligence

_CONFIGURED = [{"slug": "mlb"}, {"slug": "nba"}, {"slug": "NHL"}, {"slug": "nfl"}]


class OverviewSportFilterTests(unittest.TestCase):
    def _built_slugs(self, **kwargs) -> tuple[list[str], list[dict]]:
        built: list[str] = []

        def fake_build(sport, _date, **_kw):
            built.append(sport["slug"])
            return {"slug": sport["slug"]}

        with patch.object(intelligence, "_configured_syndicate_sports", return_value=[dict(s) for s in _CONFIGURED]), patch.object(
            intelligence, "_build_sport_overview", side_effect=fake_build
        ), patch.object(intelligence, "_log_overview_sport_counts"), patch.object(intelligence, "log_container_memory"):
            rows = intelligence.build_intelligence_overview(
                selected_date="2026-10-01", skip_game_hydration=True, **kwargs
            )
        return built, rows

    def test_default_builds_every_configured_sport(self) -> None:
        built, rows = self._built_slugs()
        self.assertEqual(built, ["mlb", "nba", "NHL", "nfl"])
        self.assertEqual(len(rows), 4)

    def test_filter_builds_only_the_named_sport(self) -> None:
        built, rows = self._built_slugs(sports=["nba"])
        self.assertEqual(built, ["nba"])
        self.assertEqual([row["slug"] for row in rows], ["nba"])

    def test_filter_matches_case_and_whitespace_insensitively(self) -> None:
        built, _rows = self._built_slugs(sports=[" nhl ", "MLB"])
        self.assertEqual(built, ["mlb", "NHL"])

    def test_unknown_sport_builds_nothing(self) -> None:
        built, rows = self._built_slugs(sports=["cricket"])
        self.assertEqual(built, [])
        self.assertEqual(rows, [])

    def test_empty_filter_builds_nothing_rather_than_everything(self) -> None:
        # An empty list is an explicit "none", not None's "all".
        built, _rows = self._built_slugs(sports=[])
        self.assertEqual(built, [])


if __name__ == "__main__":
    unittest.main()
