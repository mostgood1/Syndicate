from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.nhl.sources import team_logo_url
from syndicate.features.nhl.sources import team_primary_color
from syndicate.features.nhl.sources import team_secondary_color
from syndicate.features.shared.team_branding import TeamBranding


def _branding(**overrides) -> TeamBranding:
    base = dict(
        team_id="14",
        abbreviation="TOR",
        location="Toronto",
        display_name="Toronto Maple Leafs",
        primary_color="#003e7e",
        secondary_color="#ffffff",
        logo_url="https://a.espncdn.com/i/teamlogos/nhl/500/tor.png",
        source_snapshot_date="2026-07-20",
    )
    base.update(overrides)
    return TeamBranding(**base)


class NhlBrandingTests(unittest.TestCase):
    def test_logo_url_uses_snapshot_when_available(self) -> None:
        with patch("syndicate.features.nhl.sources.team_branding", return_value=_branding()):
            self.assertEqual(team_logo_url("Toronto Maple Leafs"), "https://a.espncdn.com/i/teamlogos/nhl/500/tor.png")

    def test_logo_url_falls_back_to_nhle_cdn_when_snapshot_missing(self) -> None:
        with patch("syndicate.features.nhl.sources.team_branding", return_value=None):
            self.assertEqual(team_logo_url("Toronto Maple Leafs"), "https://assets.nhle.com/logos/nhl/svg/TOR_dark.svg")

    def test_colors_populated_from_snapshot(self) -> None:
        with patch("syndicate.features.nhl.sources.team_branding", return_value=_branding()):
            self.assertEqual(team_primary_color("Toronto Maple Leafs"), "#003e7e")
            self.assertEqual(team_secondary_color("Toronto Maple Leafs"), "#ffffff")

    def test_colors_none_when_snapshot_missing(self) -> None:
        with patch("syndicate.features.nhl.sources.team_branding", return_value=None):
            self.assertIsNone(team_primary_color("Toronto Maple Leafs"))
            self.assertIsNone(team_secondary_color("Toronto Maple Leafs"))

    def test_utah_alias_resolves_espn_utah_abbreviation(self) -> None:
        from syndicate.features.nhl.sources import _ESPN_BRANDING_ABBR_ALIASES

        self.assertEqual(_ESPN_BRANDING_ABBR_ALIASES.get("UTA"), "UTAH")


if __name__ == "__main__":
    unittest.main()
