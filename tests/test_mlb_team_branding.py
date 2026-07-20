from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.mlb.cards import _mlb_logo_url
from syndicate.features.mlb.cards import _mlb_primary_color
from syndicate.features.mlb.cards import _mlb_secondary_color
from syndicate.features.mlb.cards import _team_display
from syndicate.features.shared.team_branding import TeamBranding


def _branding(**overrides) -> TeamBranding:
    base = dict(
        team_id="10",
        abbreviation="NYY",
        location="New York",
        display_name="New York Yankees",
        primary_color="#132448",
        secondary_color="#c4ced4",
        logo_url="https://a.espncdn.com/i/teamlogos/mlb/500/nyy.png",
        source_snapshot_date="2026-07-20",
    )
    base.update(overrides)
    return TeamBranding(**base)


class MlbBrandingTests(unittest.TestCase):
    def test_logo_url_uses_snapshot_when_available(self) -> None:
        with patch("syndicate.features.mlb.cards._mlb_branding", return_value=_branding()):
            self.assertEqual(_mlb_logo_url(147), "https://a.espncdn.com/i/teamlogos/mlb/500/nyy.png")

    def test_logo_url_falls_back_to_mlbstatic_when_snapshot_missing(self) -> None:
        with patch("syndicate.features.mlb.cards._mlb_branding", return_value=None):
            self.assertEqual(_mlb_logo_url(147), "https://www.mlbstatic.com/team-logos/147.svg")

    def test_logo_url_none_when_no_team_id(self) -> None:
        self.assertIsNone(_mlb_logo_url(None))
        self.assertIsNone(_mlb_logo_url(0))

    def test_colors_populated_from_snapshot(self) -> None:
        with patch("syndicate.features.mlb.cards._mlb_branding", return_value=_branding()):
            self.assertEqual(_mlb_primary_color(147), "#132448")
            self.assertEqual(_mlb_secondary_color(147), "#c4ced4")

    def test_colors_none_when_snapshot_missing(self) -> None:
        with patch("syndicate.features.mlb.cards._mlb_branding", return_value=None):
            self.assertIsNone(_mlb_primary_color(147))
            self.assertIsNone(_mlb_secondary_color(147))

    def test_team_display_includes_branding_fields(self) -> None:
        with patch("syndicate.features.mlb.cards._mlb_branding", return_value=_branding()):
            result = _team_display("NYY")
        self.assertEqual(result["logo"], "https://a.espncdn.com/i/teamlogos/mlb/500/nyy.png")
        self.assertEqual(result["primary_color"], "#132448")
        self.assertEqual(result["secondary_color"], "#c4ced4")

    def test_id_to_abbr_reverse_lookup_matches_known_team(self) -> None:
        from syndicate.features.mlb.cards import _mlb_abbr_by_team_id

        self.assertEqual(_mlb_abbr_by_team_id().get(147), "NYY")
        self.assertEqual(_mlb_abbr_by_team_id().get(119), "LAD")


if __name__ == "__main__":
    unittest.main()
