from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.shared.team_branding import TeamBranding
from syndicate.features.wnba.cards import _wnba_primary_color
from syndicate.features.wnba.cards import _wnba_secondary_color


def _branding(**overrides) -> TeamBranding:
    base = dict(
        team_id="20",
        abbreviation="LA",
        location="Los Angeles",
        display_name="Los Angeles Sparks",
        primary_color="#552583",
        secondary_color="#fdb927",
        logo_url="https://a.espncdn.com/i/teamlogos/wnba/500/la.png",
        source_snapshot_date="2026-07-20",
    )
    base.update(overrides)
    return TeamBranding(**base)


class WnbaBrandingTests(unittest.TestCase):
    def test_colors_populated_from_snapshot(self) -> None:
        with patch("syndicate.features.wnba.cards._wnba_branding", return_value=_branding()):
            self.assertEqual(_wnba_primary_color("LAS"), "#552583")
            self.assertEqual(_wnba_secondary_color("LAS"), "#fdb927")

    def test_colors_none_when_snapshot_missing(self) -> None:
        with patch("syndicate.features.wnba.cards._wnba_branding", return_value=None):
            self.assertIsNone(_wnba_primary_color("LAS"))
            self.assertIsNone(_wnba_secondary_color("LAS"))

    def test_canonical_alias_map_covers_known_mismatches(self) -> None:
        from syndicate.features.wnba.cards import _ESPN_BRANDING_ABBR_ALIASES

        self.assertEqual(_ESPN_BRANDING_ABBR_ALIASES.get("LAS"), "LA")
        self.assertEqual(_ESPN_BRANDING_ABBR_ALIASES.get("LVA"), "LV")
        self.assertEqual(_ESPN_BRANDING_ABBR_ALIASES.get("GSV"), "GS")
        self.assertEqual(_ESPN_BRANDING_ABBR_ALIASES.get("NYL"), "NY")


if __name__ == "__main__":
    unittest.main()
