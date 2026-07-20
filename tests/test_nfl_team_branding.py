from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.nfl.cards import _game_from_snapshot_bundle
from syndicate.features.nfl.cards import _normalize_branding_key
from syndicate.features.shared.team_branding import TeamBranding


def _branding(**overrides) -> TeamBranding:
    base = dict(
        team_id="12",
        abbreviation="KC",
        location="Kansas City",
        display_name="Kansas City Chiefs",
        primary_color="#e31837",
        secondary_color="#ffb612",
        logo_url="https://a.espncdn.com/i/teamlogos/nfl/500/kc.png",
        source_snapshot_date="2026-07-20",
    )
    base.update(overrides)
    return TeamBranding(**base)


def _bundle(**overrides) -> dict:
    base = dict(
        away_team="Kansas City Chiefs",
        home_team="Buffalo Bills",
        game_date="2026-09-10",
        rows=[],
        top_row={},
        top_ev=None,
        confidence="snapshot",
    )
    base.update(overrides)
    return base


class NormalizeBrandingKeyTests(unittest.TestCase):
    def test_lowercases_and_strips_non_alphanumeric(self) -> None:
        self.assertEqual(_normalize_branding_key("Kansas City Chiefs"), "kansascitychiefs")
        self.assertEqual(_normalize_branding_key("KC"), "kc")

    def test_blank_input_is_blank(self) -> None:
        self.assertEqual(_normalize_branding_key(None), "")
        self.assertEqual(_normalize_branding_key(""), "")


class GameFromSnapshotBundleBrandingTests(unittest.TestCase):
    def test_branding_fields_populated_when_resolved(self) -> None:
        chiefs = _branding()
        bills = _branding(team_id="2", abbreviation="BUF", location="Buffalo", display_name="Buffalo Bills", primary_color="#00338d", secondary_color="#c60c30", logo_url="https://a.espncdn.com/i/teamlogos/nfl/500/buf.png")

        def fake_resolve(team_name: str):
            return {"kansascitychiefs": chiefs, "buffalobills": bills}.get(_normalize_branding_key(team_name))

        with patch("syndicate.features.nfl.cards._resolve_branding", side_effect=fake_resolve):
            game = _game_from_snapshot_bundle(_bundle(), season=2026, week=1)

        self.assertEqual(game["away"]["logo_url"], "https://a.espncdn.com/i/teamlogos/nfl/500/kc.png")
        self.assertEqual(game["away"]["primary_color"], "#e31837")
        self.assertEqual(game["home"]["logo_url"], "https://a.espncdn.com/i/teamlogos/nfl/500/buf.png")
        self.assertEqual(game["home"]["secondary_color"], "#c60c30")

    def test_branding_fields_none_when_unresolved(self) -> None:
        with patch("syndicate.features.nfl.cards._resolve_branding", return_value=None):
            game = _game_from_snapshot_bundle(_bundle(), season=2026, week=1)
        self.assertIsNone(game["away"]["logo_url"])
        self.assertIsNone(game["home"]["primary_color"])

    def test_abbreviation_still_computed_independently_of_branding(self) -> None:
        with patch("syndicate.features.nfl.cards._resolve_branding", return_value=None):
            game = _game_from_snapshot_bundle(_bundle(), season=2026, week=1)
        self.assertEqual(game["away"]["abbr"], "KCC")
        self.assertEqual(game["home"]["abbr"], "BB")


if __name__ == "__main__":
    unittest.main()
