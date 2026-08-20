"""`nfl-team-abbr-az-alias` lane -- `canonical_team_abbr` must recognize
every team code the real nflverse feeds actually use, not just the codes
this repo's own fixtures happen to use.

THE FALSIFICATION CASE (`test_az_resolves_to_ari`): the exact production
crash, reproduced at the root cause. `NFL_ROSTER_SNAPSHOT_LAUNCHING` fired
on `dep-da3g2mj7uimc73ajjtig` (2026-08-20, refresh-worker) and immediately
crashed with `ValueError: Roster snapshot validation failed: row 91 has
invalid team AZ; ...` across ~90 rows -- every Arizona Cardinals player in
the real roster_2026.csv release. Confirmed against the LIVE feed the same
day: of the 32 distinct team codes nflverse actually publishes, `AZ` was
the only one this table didn't already recognize.
"""
from __future__ import annotations

import unittest

from syndicate.features.football.features.team_identity import canonical_team_abbr
from syndicate.features.football.features.team_identity import canonical_team_metadata
from syndicate.features.football.features.team_identity import canonical_team_name


class ArizonaAzAlias(unittest.TestCase):
    def test_az_resolves_to_ari(self) -> None:
        """THE FALSIFICATION CASE. Pre-fix this returns 'AZ' unchanged --
        `canonical_team_abbr` falls through `_TEAM_IDENTITY_BY_ABBR`
        (keyed ARI) and `_TEAM_IDENTITY_BY_ALIAS` (no AZ entry), landing
        on the `len(normalized) <= 3` passthrough branch."""
        self.assertEqual(canonical_team_abbr("AZ"), "ARI")

    def test_az_is_case_insensitive(self) -> None:
        self.assertEqual(canonical_team_abbr("az"), "ARI")

    def test_ari_still_resolves_directly(self) -> None:
        """The fix must not have disturbed the already-working code path."""
        self.assertEqual(canonical_team_abbr("ARI"), "ARI")

    def test_full_name_still_resolves(self) -> None:
        self.assertEqual(canonical_team_abbr("Arizona Cardinals"), "ARI")

    def test_az_resolves_to_the_real_team_name(self) -> None:
        self.assertEqual(canonical_team_name("AZ"), "Arizona Cardinals")

    def test_az_metadata_uses_the_real_identity_table_not_the_fallback(self) -> None:
        """Pre-fix, an unrecognized code falls back to
        `identity_source='fallback_normalized'` -- confirms the fix routes
        through the real table, not just that the abbreviation happens to
        look right."""
        metadata = canonical_team_metadata("AZ")
        self.assertEqual(metadata["identity_source"], "nfl_team_identity_table")
        self.assertEqual(metadata["team_abbr"], "ARI")


class OtherRealNflverseCodesAlreadyResolve(unittest.TestCase):
    """Confirmed live against nflverse's real roster_2026.csv release,
    2026-08-20: of the 32 distinct team codes actually published, AZ was
    the only gap. Pinning the rest here so a future table edit can't
    reintroduce a code silently."""

    def test_every_real_nflverse_code_resolves_to_a_known_team(self) -> None:
        real_nflverse_codes = (
            "ATL", "AZ", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
            "GB", "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO",
            "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
        )
        for code in real_nflverse_codes:
            with self.subTest(code=code):
                resolved = canonical_team_abbr(code)
                metadata = canonical_team_metadata(resolved)
                self.assertEqual(
                    metadata["identity_source"], "nfl_team_identity_table",
                    f"{code!r} -> {resolved!r} did not resolve through the real table",
                )


if __name__ == "__main__":
    unittest.main()
