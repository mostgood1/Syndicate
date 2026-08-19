"""`nfl-injuries-fetcher` lane — the injuries READ path had the exact same
root-resolution bug `#441` already found and fixed for pbp, applied here
before it ever shipped broken (unlike pbp, this was caught in review, not
in production).

Mirrors `test_smartsim2_nfl_pbp_root.py`'s shape exactly, because
`nfl_injuries_path` and `nfl_pbp_path` now share one resolver
(`_resolve_nfl_tracking_path`) -- these tests exist to prove the injuries
call site actually goes through it, not just that the shared helper works
(the helper's own correctness is already covered by the pbp suite).

THE FALSIFICATION CASE FIRST (`test_injured_players_for_team...`): reproduces
`#441`'s exact production shape but for `_injured_players_for_team` --
before the fix, this call went straight through
`default_nfl_source_root() / "tracking" / ...`, which is exactly the
selector `#441` proved picks the checkout over the mounted disk. Written to
fail against the pre-fix code path (verified below) so the fix is
demonstrated, not assumed.
"""
from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from syndicate.features.nfl import injury_adjustment, sources


def _make_root(base: Path, name: str, *, with_upcoming_recs: bool, with_injuries_season: int | None) -> Path:
    root = base / name / "nfl_source"
    root.mkdir(parents=True, exist_ok=True)
    if with_upcoming_recs:
        (root / "upcoming_recs_2025_wk17.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    if with_injuries_season is not None:
        injuries_dir = root / "tracking" / "nflverse" / "injuries"
        injuries_dir.mkdir(parents=True, exist_ok=True)
        path = injuries_dir / f"injuries_{with_injuries_season}.csv"
        fieldnames = ["season", "season_type", "team", "week", "gsis_id", "position", "full_name", "report_status"]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow({
                "season": with_injuries_season, "season_type": "REG", "team": "KC", "week": 1,
                "gsis_id": "00-0000001", "position": "WR", "full_name": "Test Player",
                "report_status": "Out",
            })
    return root


class NflInjuriesPathResolution(unittest.TestCase):
    def test_injuries_found_on_a_later_root_when_the_first_only_has_upcoming_recs(self):
        """`#441`'s exact production shape, reproduced for injuries.

        Candidate 1 = the checkout: has `upcoming_recs_*.csv`, no injuries.
        Candidate 2 = the mounted disk: has the injuries file, no `upcoming_recs`.
        `default_nfl_source_root()` picks candidate 1; the real file is on 2.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            checkout = _make_root(base, "src_data", with_upcoming_recs=True, with_injuries_season=None)
            disk = _make_root(base, "data", with_upcoming_recs=False, with_injuries_season=2026)
            with patch.object(sources, "_source_roots", return_value=[checkout, disk]):
                self.assertEqual(sources.default_nfl_source_root(), checkout)
                resolved = sources.nfl_injuries_path(2026)
            self.assertEqual(resolved, disk / "tracking" / "nflverse" / "injuries" / "injuries_2026.csv")
            self.assertTrue(resolved.is_file())

    def test_prefers_the_earlier_root_when_both_have_the_injuries_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = _make_root(base, "first", with_upcoming_recs=False, with_injuries_season=2026)
            second = _make_root(base, "second", with_upcoming_recs=True, with_injuries_season=2026)
            with patch.object(sources, "_source_roots", return_value=[first, second]):
                resolved = sources.nfl_injuries_path(2026)
            self.assertEqual(resolved, first / "tracking" / "nflverse" / "injuries" / "injuries_2026.csv")

    def test_missing_everywhere_still_names_a_concrete_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            only = _make_root(base, "only", with_upcoming_recs=True, with_injuries_season=None)
            with patch.object(sources, "_source_roots", return_value=[only]):
                resolved = sources.nfl_injuries_path(2026)
            self.assertEqual(resolved.name, "injuries_2026.csv")
            self.assertFalse(resolved.is_file())


class InjuryAdjustmentUsesTheResolver(unittest.TestCase):
    """THE FALSIFICATION TEST. Reproduces `#441`'s production shape one call
    site further down, at `_injured_players_for_team` -- the actual consumer.
    """

    def test_injured_players_for_team_finds_the_file_on_the_mounted_disk_root(self):
        """Pre-fix, this call built the path as
        `default_nfl_source_root() / "tracking" / "nflverse" / "injuries" /
        ...` directly -- which resolves to `checkout` here, exactly as
        `#441` proved for pbp -- and would have read zero rows even though
        the real file exists on `disk`. Post-fix it goes through
        `nfl_injuries_path`, which finds it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            checkout = _make_root(base, "src_data", with_upcoming_recs=True, with_injuries_season=None)
            disk = _make_root(base, "data", with_upcoming_recs=False, with_injuries_season=2026)
            with patch.object(sources, "_source_roots", return_value=[checkout, disk]):
                # Confirm the trap is real in this fixture, same discipline as
                # the pbp suite: the selector really does pick the wrong root.
                self.assertEqual(sources.default_nfl_source_root(), checkout)
                players = injury_adjustment._injured_players_for_team(2026, 1, "KC")
            self.assertEqual(len(players), 1)
            self.assertEqual(players[0]["full_name"], "Test Player")

    def test_falsifies_against_the_pre_fix_direct_join(self):
        """Proves the fix matters: the OLD expression (unfixed root join)
        against this exact fixture resolves to a path with no file on it,
        which is the bug this lane exists to close.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            checkout = _make_root(base, "src_data", with_upcoming_recs=True, with_injuries_season=None)
            disk = _make_root(base, "data", with_upcoming_recs=False, with_injuries_season=2026)
            with patch.object(sources, "_source_roots", return_value=[checkout, disk]):
                old_style_path = sources.default_nfl_source_root() / "tracking" / "nflverse" / "injuries" / "injuries_2026.csv"
                self.assertFalse(old_style_path.is_file(), "the pre-fix path must miss -- that IS the bug")
                # And the fixed resolver used by the real call site must hit.
                self.assertTrue(sources.nfl_injuries_path(2026).is_file())


if __name__ == "__main__":
    unittest.main()
