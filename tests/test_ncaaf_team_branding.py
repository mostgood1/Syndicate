from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.ncaaf.cards import _team_context
from syndicate.features.shared.team_branding import TeamBranding


def _branding(**overrides) -> TeamBranding:
    base = dict(
        team_id="103",
        abbreviation="ABC",
        location="Somewhere",
        display_name="Somewhere Tigers",
        primary_color="#123456",
        secondary_color="#abcdef",
        logo_url="https://a.espncdn.com/i/teamlogos/ncaa/500/103.png",
        source_snapshot_date="2026-07-20",
    )
    base.update(overrides)
    return TeamBranding(**base)


class TeamContextBrandingTests(unittest.TestCase):
    def test_team_context_includes_branding_fields_when_resolved(self) -> None:
        with patch("syndicate.features.ncaaf.cards._resolve_team", return_value={"team_id": "103", "school_name": "Somewhere"}), patch(
            "syndicate.features.ncaaf.cards._resolve_branding", return_value=_branding()
        ):
            context = _team_context("Somewhere", 2025)
        self.assertEqual(context["logo_url"], "https://a.espncdn.com/i/teamlogos/ncaa/500/103.png")
        self.assertEqual(context["primary_color"], "#123456")
        self.assertEqual(context["secondary_color"], "#abcdef")

    def test_team_context_branding_fields_none_when_unresolved(self) -> None:
        with patch("syndicate.features.ncaaf.cards._resolve_team", return_value=None), patch(
            "syndicate.features.ncaaf.cards._resolve_branding", return_value=None
        ):
            context = _team_context("Unknown Team", 2025)
        self.assertIsNone(context["logo_url"])
        self.assertIsNone(context["primary_color"])
        self.assertIsNone(context["secondary_color"])


if __name__ == "__main__":
    unittest.main()
