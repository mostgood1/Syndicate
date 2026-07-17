from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.ncaaf.cards import _runtime_scoreboard_projection
from syndicate.features.ncaaf.picks import _diagnostic_source_list_items
from syndicate.features.ncaaf.smartsim2_blend import LARGE_MISMATCH_MARGIN_THRESHOLD
from syndicate.features.ncaaf.smartsim2_blend import blend_total
from syndicate.features.ncaaf.smartsim2_blend import compute_blend
from syndicate.features.ncaaf.smartsim2_projection import CONSENSUS_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_projection import LEGACY_ENGINE_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SMARTSIM2_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SmartSimNcaafProjection


def _row(**overrides):
    base = {
        "week": "8",
        "home_team": "Sam Houston",
        "away_team": "UNLV",
        "predicted_home_points": "34.2",
        "predicted_away_points": "24.1",
        "predicted_total_points": "58.3",
        "predicted_win_margin": "10.1",
        "model_home_win_prob": "0.731",
        "start_date": "2025-10-25T19:00:00Z",
        "venue": "Test Stadium",
    }
    base.update(overrides)
    return base


def _projection(**overrides) -> SmartSimNcaafProjection:
    base = dict(
        game_id="401700000",
        season=2025,
        week=8,
        home_team="Sam Houston",
        away_team="UNLV",
        home_score_mean=30.0,
        away_score_mean=27.0,
        margin_mean=3.0,
        total_mean=57.0,
        margin_stdev=12.0,
        total_stdev=14.0,
        home_win_rate=0.62,
        seeds_used=300,
        profile_name="ncaaf_v2",
        rating_source="cfbd_ppa_season_2025",
        generated_at="2026-07-16T00:00:00+00:00",
    )
    base.update(overrides)
    return SmartSimNcaafProjection(**base)


class SmartSim2ShadowIntegrationTests(unittest.TestCase):
    def test_existing_fields_unchanged_when_no_projection_available(self) -> None:
        with patch("syndicate.features.ncaaf.cards._smartsim2_projection_index", return_value={}):
            scoreboard = _runtime_scoreboard_projection(_row(), 8)

        # Legacy fields (Enhanced Totals Engine, post Phase 2A rename) unaffected by shadow-mode availability.
        self.assertEqual(scoreboard["home_points"], "34.2")
        self.assertEqual(scoreboard["away_points"], "24.1")
        self.assertEqual(scoreboard["total_points"], "58.3")
        self.assertEqual(scoreboard["spread_label"], "Sam Houston by 10.1")
        self.assertEqual(scoreboard["source_label"], "Enhanced Totals Engine")
        self.assertFalse(scoreboard["smartsim2_available"])
        self.assertNotIn("smartsim2_home_points", scoreboard)
        self.assertNotIn("blend_margin", scoreboard)

    def test_additive_fields_present_when_projection_available(self) -> None:
        index = {("sam houston", "unlv"): _projection()}
        row = _row(predicted_win_margin="6.0")  # agrees in sign with the projection's 3.0 margin
        with patch("syndicate.features.ncaaf.cards._smartsim2_projection_index", return_value=index):
            scoreboard = _runtime_scoreboard_projection(row, 8)

        # Legacy fields still byte-identical.
        self.assertEqual(scoreboard["home_points"], "34.2")
        self.assertEqual(scoreboard["away_points"], "24.1")
        self.assertEqual(scoreboard["total_points"], "58.3")
        self.assertEqual(scoreboard["source_label"], "Enhanced Totals Engine")

        # New shadow fields present and correct.
        self.assertTrue(scoreboard["smartsim2_available"])
        self.assertEqual(scoreboard["smartsim2_source_label"], SMARTSIM2_SOURCE_LABEL)
        self.assertEqual(scoreboard["smartsim2_home_points"], 30.0)
        self.assertEqual(scoreboard["smartsim2_margin"], 3.0)
        self.assertEqual(scoreboard["smartsim2_total_points"], 57.0)
        # ATS policy: engine and SmartSim agree on side (both positive) -- Engine's margin is used.
        self.assertAlmostEqual(scoreboard["blend_margin"], 6.0)
        self.assertAlmostEqual(scoreboard["blend_total"], blend_total(58.3, 57.0))
        self.assertFalse(scoreboard["blend_margin_applied"])  # agreement -- SmartSim's margin was not used

    def test_no_crash_when_engine_fields_missing(self) -> None:
        index = {("sam houston", "unlv"): _projection()}
        row = _row(predicted_home_points="", predicted_away_points="", predicted_win_margin="")
        with patch("syndicate.features.ncaaf.cards._smartsim2_projection_index", return_value=index):
            scoreboard = _runtime_scoreboard_projection(row, 8)
        self.assertTrue(scoreboard["smartsim2_available"])
        self.assertNotIn("blend_margin", scoreboard)


class SmartSim2BlendTests(unittest.TestCase):
    def test_agreement_uses_engine_margin(self) -> None:
        # ATS policy (smartsim_ats_policy_implementation_report.md): Engine and
        # SmartSim agree on side (both positive) -- Engine's margin is used.
        result = compute_blend(engine_margin=4.0, smartsim_margin=6.0, engine_total=50.0, smartsim_total=60.0)
        self.assertFalse(result.smartsim_margin_used)
        self.assertEqual(result.margin, 4.0)

    def test_disagreement_uses_smartsim_margin(self) -> None:
        # Engine and SmartSim pick opposite sides -- SmartSim's margin is used,
        # regardless of magnitude (large-mismatch magnitude no longer matters).
        result = compute_blend(
            engine_margin=LARGE_MISMATCH_MARGIN_THRESHOLD + 5.0,
            smartsim_margin=-2.0,
            engine_total=50.0,
            smartsim_total=60.0,
        )
        self.assertTrue(result.smartsim_margin_used)
        self.assertEqual(result.margin, -2.0)

    def test_large_engine_margin_alone_does_not_trigger_smartsim_override(self) -> None:
        # A big Engine margin used to trigger the large-mismatch override; it
        # no longer does anything on its own -- only a side disagreement does.
        result = compute_blend(
            engine_margin=LARGE_MISMATCH_MARGIN_THRESHOLD + 5.0,
            smartsim_margin=6.0,
            engine_total=50.0,
            smartsim_total=60.0,
        )
        self.assertFalse(result.smartsim_margin_used)
        self.assertEqual(result.margin, LARGE_MISMATCH_MARGIN_THRESHOLD + 5.0)

    def test_total_is_always_blended_and_bias_corrected(self) -> None:
        result = compute_blend(engine_margin=1.0, smartsim_margin=1.0, engine_total=50.0, smartsim_total=60.0)
        self.assertTrue(result.total_blended)
        self.assertAlmostEqual(result.total, blend_total(50.0, 60.0))


class BlendTrialDiagnosticsTests(unittest.TestCase):
    def test_diagnostics_flag_defaults_off(self) -> None:
        from syndicate.features.ncaaf.cards import _blend_trial_diagnostics_enabled

        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(_blend_trial_diagnostics_enabled())

    def test_diagnostics_flag_recognizes_truthy_values(self) -> None:
        from syndicate.features.ncaaf.cards import _blend_trial_diagnostics_enabled

        for value in ("1", "true", "True", "yes", "YES"):
            with patch.dict("os.environ", {"SMARTSIM_BLEND_TRIAL_DIAGNOSTICS": value}):
                self.assertTrue(_blend_trial_diagnostics_enabled(), msg=f"value={value!r}")
        for value in ("0", "false", "", "no"):
            with patch.dict("os.environ", {"SMARTSIM_BLEND_TRIAL_DIAGNOSTICS": value}):
                self.assertFalse(_blend_trial_diagnostics_enabled(), msg=f"value={value!r}")

    def test_projection_sources_absent_by_default(self) -> None:
        index = {("sam houston", "unlv"): _projection()}
        row = _row(predicted_win_margin="6.0")
        with patch("syndicate.features.ncaaf.cards._smartsim2_projection_index", return_value=index), patch(
            "syndicate.features.ncaaf.cards._blend_trial_diagnostics_enabled", return_value=False
        ):
            scoreboard = _runtime_scoreboard_projection(row, 8)
        self.assertNotIn("projection_sources", scoreboard)

    def test_projection_sources_present_when_diagnostics_enabled(self) -> None:
        index = {("sam houston", "unlv"): _projection()}
        row = _row(predicted_win_margin="6.0")
        with patch("syndicate.features.ncaaf.cards._smartsim2_projection_index", return_value=index), patch.dict(
            "os.environ", {"SMARTSIM_BLEND_TRIAL_DIAGNOSTICS": "1"}
        ):
            scoreboard = _runtime_scoreboard_projection(row, 8)

        sources = scoreboard["projection_sources"]
        self.assertEqual(set(sources), {"enhanced_totals_engine", "smartsim2", "consensus_projection"})

        engine = sources["enhanced_totals_engine"]
        self.assertEqual(engine["label"], LEGACY_ENGINE_SOURCE_LABEL)
        self.assertEqual(engine["margin"], 6.0)
        self.assertEqual(engine["total"], 58.3)

        smartsim2 = sources["smartsim2"]
        self.assertEqual(smartsim2["label"], SMARTSIM2_SOURCE_LABEL)
        self.assertEqual(smartsim2["margin"], 3.0)
        self.assertEqual(smartsim2["total"], 57.0)
        self.assertTrue(smartsim2["available"])

        consensus = sources["consensus_projection"]
        self.assertEqual(consensus["label"], CONSENSUS_SOURCE_LABEL)
        # Engine (6.0) and SmartSim (3.0) agree on side -- Engine's margin is used.
        self.assertAlmostEqual(consensus["margin"], 6.0)
        self.assertAlmostEqual(consensus["total"], blend_total(58.3, 57.0))

        # Existing published fields remain byte-identical alongside the new diagnostic block.
        self.assertEqual(scoreboard["home_points"], "34.2")
        self.assertEqual(scoreboard["source_label"], "Enhanced Totals Engine")

    def test_projection_sources_absent_when_smartsim_unavailable_even_with_diagnostics_enabled(self) -> None:
        with patch("syndicate.features.ncaaf.cards._smartsim2_projection_index", return_value={}), patch.dict(
            "os.environ", {"SMARTSIM_BLEND_TRIAL_DIAGNOSTICS": "1"}
        ):
            scoreboard = _runtime_scoreboard_projection(_row(), 8)
        self.assertNotIn("projection_sources", scoreboard)

    def test_picks_diagnostic_list_items_empty_without_projection_sources(self) -> None:
        self.assertEqual(_diagnostic_source_list_items({}), [])

    def test_picks_diagnostic_list_items_present_with_projection_sources(self) -> None:
        scoreboard = {
            "projection_sources": {
                "enhanced_totals_engine": {"label": LEGACY_ENGINE_SOURCE_LABEL, "margin": 6.0, "total": 58.3},
                "smartsim2": {"label": SMARTSIM2_SOURCE_LABEL, "margin": 3.0, "total": 57.0},
                "consensus_projection": {"label": CONSENSUS_SOURCE_LABEL, "margin": 5.4, "total": 57.4},
            }
        }
        items = _diagnostic_source_list_items(scoreboard)
        self.assertEqual(len(items), 4)
        self.assertTrue(any(LEGACY_ENGINE_SOURCE_LABEL in item for item in items))
        self.assertTrue(any(SMARTSIM2_SOURCE_LABEL in item for item in items))
        self.assertTrue(any(CONSENSUS_SOURCE_LABEL in item for item in items))


if __name__ == "__main__":
    unittest.main()
