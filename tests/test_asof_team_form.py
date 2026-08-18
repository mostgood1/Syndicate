"""The as-of feature builder must never see the game it is describing.

This file exists because the ORIGINAL football feature builder did.
`build_nflverse_game_metrics` computes EPA from the game being predicted, and
measured over 285 games of 2023 its EPA differential correlates **r = 0.988**
with the final margin. Nothing else in this repo could see that: a leaked field
is 100% populated by construction, so the input checklist passed it as FED, the
reachability test passed, and the unit tests passed.

So these tests assert the WINDOW, not the values.
"""
from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from syndicate.features.football.features import asof_team_form as af

COLUMNS = [
    "game_id", "season", "week", "home_team", "away_team", "posteam", "defteam",
    "epa", "success", "pass", "yards_gained", "yardline_100", "touchdown",
    "play_type", "pass_oe", "home_score", "away_score",
]


def _row(**kw):
    base = {c: "" for c in COLUMNS}
    base.update(kw)
    return base


def _write(dirpath: Path, season: int, rows: list[dict]) -> None:
    p = dirpath / ("pbp_%d.csv" % season)
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _plays(season, week, gid, home, away, epa, n=120):
    """n plays for `home` in one game, with a fixed EPA so leakage is visible."""
    return [
        _row(game_id=gid, season=season, week=week, home_team=home, away_team=away,
             posteam=home, defteam=away, epa=str(epa), success="1", **{"pass": "1"},
             yards_gained="8", play_type="pass", home_score="20", away_score="17")
        for _ in range(n)
    ]


class AsOfWindowTest(unittest.TestCase):
    def test_target_week_rows_are_never_read(self) -> None:
        """The defining property. Week 3 form must not move when week 3's own
        result changes — that is exactly what leakage would look like."""
        with TemporaryDirectory() as td:
            d = Path(td)
            early = _plays(2023, 1, "g1", "KC", "BUF", 0.10) + _plays(2023, 2, "g2", "KC", "DEN", 0.10)
            _write(d, 2023, early + _plays(2023, 3, "g3", "KC", "LV", 9.99))
            form_a = af.team_form_asof(2023, 3, pbp_dir=d, allow_prior_season=False)["KC"]

            _write(d, 2023, early + _plays(2023, 3, "g3", "KC", "LV", -9.99))
            form_b = af.team_form_asof(2023, 3, pbp_dir=d, allow_prior_season=False)["KC"]

        self.assertAlmostEqual(form_a.offensive_epa, 0.10, places=6)
        self.assertEqual(form_a.offensive_epa, form_b.offensive_epa,
                         "week-3 form changed when week 3's own EPA changed — the target week leaked in")

    def test_later_weeks_are_excluded_too(self) -> None:
        """`week < target`, not `week != target`. A future game is as much a
        leak as the present one."""
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, 2023, _plays(2023, 1, "g1", "KC", "BUF", 0.10)
                   + _plays(2023, 9, "g9", "KC", "LV", 5.00))
            form = af.team_form_asof(2023, 2, pbp_dir=d, allow_prior_season=False)["KC"]
        self.assertAlmostEqual(form.offensive_epa, 0.10, places=6)

    def test_thin_history_is_unfed_not_averaged(self) -> None:
        """A neutral default would make 'no data' indistinguishable from
        'average team' — §4.2's silent no-op."""
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, 2023, _plays(2023, 1, "g1", "KC", "BUF", 0.10, n=5))
            form = af.team_form_asof(2023, 2, pbp_dir=d, allow_prior_season=False)["KC"]
        self.assertFalse(form.is_fed)
        self.assertLess(form.plays, af.MIN_PLAYS_FOR_FORM)

    def test_week_one_falls_back_to_prior_season(self) -> None:
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, 2022, _plays(2022, 5, "p1", "KC", "BUF", 0.22))
            _write(d, 2023, _plays(2023, 1, "g1", "KC", "BUF", 0.99))
            form = af.team_form_asof(2023, 1, pbp_dir=d)["KC"]
        self.assertAlmostEqual(form.offensive_epa, 0.22, places=6)
        self.assertIn("prior_fallback", form.source)

    def test_payload_omits_missing_terms_rather_than_zeroing(self) -> None:
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, 2023, _plays(2023, 1, "g1", "KC", "BUF", 0.10)
                   + _plays(2023, 1, "g1", "BUF", "KC", 0.05))
            forms = af.team_form_asof(2023, 2, pbp_dir=d, allow_prior_season=False)
            payload = af.build_payload("KC", "BUF", season=2023, week=2, forms=forms)
        self.assertIn("offensive_metrics", payload)
        self.assertIn("asof", payload)
        self.assertEqual(payload["asof"]["before_week"], 2)
        # `def_pressure_avg` has no nflverse source and must stay absent.
        self.assertNotIn("def_pressure_avg", payload.get("advanced_metrics", {}))

    def test_payload_is_empty_when_either_team_is_unfed(self) -> None:
        """Half a payload is worse than none — the engine would silently
        neutral-default the missing side and quietly favour the fed one."""
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, 2023, _plays(2023, 1, "g1", "KC", "BUF", 0.10))
            forms = af.team_form_asof(2023, 2, pbp_dir=d, allow_prior_season=False)
            payload = af.build_payload("KC", "BUF", season=2023, week=2, forms=forms)
        self.assertEqual(payload, {})

    def test_leakage_ceiling_is_below_the_measured_in_game_value(self) -> None:
        """0.988 was the in-game reading. A ceiling at or above it would
        certify the very bug this module replaces."""
        self.assertLess(af.LEAKAGE_CEILING_R, 0.988)
        self.assertGreaterEqual(af.LEAKAGE_CEILING_R, 0.5,
                                "too tight and honest prior-form signal would fail certification")


class LeakageCertificationTest(unittest.TestCase):
    """Runs against the REAL 2023 mirror when present. Skipped, never silently
    passed, when it is not — a certification that vanishes with its data is
    worse than one that says it did not run."""

    def test_real_season_certifies_below_ceiling(self) -> None:
        if not af._pbp_path(2023).is_file():
            self.skipTest("pbp_2023.csv not present in this checkout")
        r = af.assert_no_leakage(2023)
        self.assertLess(abs(r), af.LEAKAGE_CEILING_R)
        self.assertGreater(abs(r), 0.05, "near-zero correlation would mean the features carry no signal at all")


if __name__ == "__main__":
    unittest.main()
