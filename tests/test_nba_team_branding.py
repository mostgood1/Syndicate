from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.nba.cards import _nba_logo_url
from syndicate.features.nba.cards import _nba_primary_color
from syndicate.features.nba.cards import _nba_secondary_color
from syndicate.features.shared.team_branding import TeamBranding


def _branding(**overrides) -> TeamBranding:
    base = dict(
        team_id="9",
        abbreviation="GS",
        location="Golden State",
        display_name="Golden State Warriors",
        primary_color="#fdb927",
        secondary_color="#1d428a",
        logo_url="https://a.espncdn.com/i/teamlogos/nba/500/gs.png",
        source_snapshot_date="2026-07-20",
    )
    base.update(overrides)
    return TeamBranding(**base)


class NbaBrandingTests(unittest.TestCase):
    def test_logo_url_uses_snapshot_when_available(self) -> None:
        with patch("syndicate.features.nba.cards._nba_branding", return_value=_branding()):
            self.assertEqual(_nba_logo_url("GSW"), "https://a.espncdn.com/i/teamlogos/nba/500/gs.png")

    def test_logo_url_falls_back_to_cdn_guess_when_snapshot_missing(self) -> None:
        with patch("syndicate.features.nba.cards._nba_branding", return_value=None):
            self.assertEqual(_nba_logo_url("GSW"), "https://a.espncdn.com/i/teamlogos/nba/500/gs.png")

    def test_colors_populated_from_snapshot(self) -> None:
        with patch("syndicate.features.nba.cards._nba_branding", return_value=_branding()):
            self.assertEqual(_nba_primary_color("GSW"), "#fdb927")
            self.assertEqual(_nba_secondary_color("GSW"), "#1d428a")

    def test_colors_none_when_snapshot_missing(self) -> None:
        with patch("syndicate.features.nba.cards._nba_branding", return_value=None):
            self.assertIsNone(_nba_primary_color("GSW"))
            self.assertIsNone(_nba_secondary_color("GSW"))


if __name__ == "__main__":
    unittest.main()
