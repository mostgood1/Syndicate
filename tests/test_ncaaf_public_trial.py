from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.features.ncaaf.cards import _public_trial_master_enabled
from syndicate.features.ncaaf.cards import _public_trial_visible_for_request
from syndicate.features.ncaaf.cards import _runtime_scoreboard_projection
from syndicate.features.ncaaf.smartsim2_projection import SMARTSIM2_PUBLIC_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SMARTSIM2_SOURCE_LABEL
from syndicate.features.ncaaf.smartsim2_projection import SmartSimNcaafProjection

_APP = create_app()


def _row(**overrides):
    base = {
        "week": "8",
        "home_team": "Sam Houston",
        "away_team": "UNLV",
        "predicted_home_points": "34.2",
        "predicted_away_points": "24.1",
        "predicted_total_points": "58.3",
        "predicted_win_margin": "6.0",
        "model_home_win_prob": "0.731",
        "start_date": "2025-09-01T19:00:00Z",
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


class PublicTrialMasterSwitchTests(unittest.TestCase):
    def test_defaults_off(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(_public_trial_master_enabled())

    def test_recognizes_truthy_values(self) -> None:
        for value in ("1", "true", "yes"):
            with patch.dict("os.environ", {"SMARTSIM_PUBLIC_TRIAL_ENABLED": value}):
                self.assertTrue(_public_trial_master_enabled())
        for value in ("0", "false", ""):
            with patch.dict("os.environ", {"SMARTSIM_PUBLIC_TRIAL_ENABLED": value}):
                self.assertFalse(_public_trial_master_enabled())


class PublicTrialRequestGateTests(unittest.TestCase):
    def test_false_outside_request_context(self) -> None:
        with patch.dict(
            "os.environ",
            {"SMARTSIM_PUBLIC_TRIAL_ENABLED": "1", "SMARTSIM_PUBLIC_TRIAL_TOKENS": "tester-alpha"},
        ):
            self.assertFalse(_public_trial_visible_for_request())

    def test_false_when_master_off_even_with_valid_token(self) -> None:
        with patch.dict(
            "os.environ",
            {"SMARTSIM_PUBLIC_TRIAL_ENABLED": "0", "SMARTSIM_PUBLIC_TRIAL_TOKENS": "tester-alpha"},
        ):
            with _APP.test_request_context("/ncaaf/cards?smartsim_trial=tester-alpha"):
                self.assertFalse(_public_trial_visible_for_request())

    def test_false_when_master_on_but_no_allowlists_configured(self) -> None:
        with patch.dict("os.environ", {"SMARTSIM_PUBLIC_TRIAL_ENABLED": "1"}, clear=False):
            for key in ("SMARTSIM_PUBLIC_TRIAL_TOKENS", "SMARTSIM_PUBLIC_TRIAL_IP_ALLOWLIST"):
                import os

                os.environ.pop(key, None)
            with _APP.test_request_context("/ncaaf/cards"):
                self.assertFalse(_public_trial_visible_for_request())

    def test_true_with_matching_query_token(self) -> None:
        with patch.dict(
            "os.environ",
            {"SMARTSIM_PUBLIC_TRIAL_ENABLED": "1", "SMARTSIM_PUBLIC_TRIAL_TOKENS": "tester-alpha,tester-beta"},
        ):
            with _APP.test_request_context("/ncaaf/cards?smartsim_trial=tester-beta"):
                self.assertTrue(_public_trial_visible_for_request())

    def test_false_with_unrecognized_token(self) -> None:
        with patch.dict(
            "os.environ",
            {"SMARTSIM_PUBLIC_TRIAL_ENABLED": "1", "SMARTSIM_PUBLIC_TRIAL_TOKENS": "tester-alpha"},
        ):
            with _APP.test_request_context("/ncaaf/cards?smartsim_trial=someone-random"):
                self.assertFalse(_public_trial_visible_for_request())

    def test_true_with_matching_cookie_token(self) -> None:
        with patch.dict(
            "os.environ",
            {"SMARTSIM_PUBLIC_TRIAL_ENABLED": "1", "SMARTSIM_PUBLIC_TRIAL_TOKENS": "tester-alpha"},
        ):
            with _APP.test_request_context("/ncaaf/cards", headers={"Cookie": "smartsim_trial=tester-alpha"}):
                self.assertTrue(_public_trial_visible_for_request())

    def test_true_with_matching_ip_allowlist(self) -> None:
        with patch.dict(
            "os.environ",
            {"SMARTSIM_PUBLIC_TRIAL_ENABLED": "1", "SMARTSIM_PUBLIC_TRIAL_IP_ALLOWLIST": "127.0.0.1"},
        ):
            with _APP.test_request_context("/ncaaf/cards", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
                self.assertTrue(_public_trial_visible_for_request())

    def test_false_with_non_matching_ip(self) -> None:
        with patch.dict(
            "os.environ",
            {"SMARTSIM_PUBLIC_TRIAL_ENABLED": "1", "SMARTSIM_PUBLIC_TRIAL_IP_ALLOWLIST": "10.0.0.5"},
        ):
            with _APP.test_request_context("/ncaaf/cards", environ_base={"REMOTE_ADDR": "203.0.113.9"}):
                self.assertFalse(_public_trial_visible_for_request())


class PublicTrialEndToEndTests(unittest.TestCase):
    def test_projection_sources_uses_public_label_and_mode_in_trial(self) -> None:
        index = {("sam houston", "unlv"): _projection()}
        with patch("syndicate.features.ncaaf.cards._smartsim2_projection_index", return_value=index), patch.dict(
            "os.environ",
            {"SMARTSIM_PUBLIC_TRIAL_ENABLED": "1", "SMARTSIM_PUBLIC_TRIAL_TOKENS": "tester-alpha"},
        ):
            with _APP.test_request_context("/ncaaf/cards?smartsim_trial=tester-alpha"):
                scoreboard = _runtime_scoreboard_projection(_row(), 8)

        self.assertEqual(scoreboard["projection_sources_mode"], "public_trial")
        self.assertEqual(scoreboard["projection_sources"]["smartsim2"]["label"], SMARTSIM2_PUBLIC_LABEL)
        # Existing published fields still untouched.
        self.assertEqual(scoreboard["home_points"], "34.2")
        self.assertEqual(scoreboard["source_label"], "Enhanced Totals Engine")

    def test_internal_diagnostic_mode_unaffected_and_uses_internal_label(self) -> None:
        index = {("sam houston", "unlv"): _projection()}
        with patch("syndicate.features.ncaaf.cards._smartsim2_projection_index", return_value=index), patch.dict(
            "os.environ", {"SMARTSIM_BLEND_TRIAL_DIAGNOSTICS": "1"}, clear=True
        ):
            scoreboard = _runtime_scoreboard_projection(_row(), 8)

        self.assertEqual(scoreboard["projection_sources_mode"], "internal_diagnostic")
        self.assertEqual(scoreboard["projection_sources"]["smartsim2"]["label"], SMARTSIM2_SOURCE_LABEL)

    def test_public_trial_takes_precedence_when_both_active(self) -> None:
        index = {("sam houston", "unlv"): _projection()}
        with patch("syndicate.features.ncaaf.cards._smartsim2_projection_index", return_value=index), patch.dict(
            "os.environ",
            {
                "SMARTSIM_BLEND_TRIAL_DIAGNOSTICS": "1",
                "SMARTSIM_PUBLIC_TRIAL_ENABLED": "1",
                "SMARTSIM_PUBLIC_TRIAL_TOKENS": "tester-alpha",
            },
        ):
            with _APP.test_request_context("/ncaaf/cards?smartsim_trial=tester-alpha"):
                scoreboard = _runtime_scoreboard_projection(_row(), 8)
        self.assertEqual(scoreboard["projection_sources_mode"], "public_trial")

    def test_no_leak_when_nothing_enabled(self) -> None:
        index = {("sam houston", "unlv"): _projection()}
        with patch("syndicate.features.ncaaf.cards._smartsim2_projection_index", return_value=index), patch.dict(
            "os.environ", {}, clear=True
        ):
            with _APP.test_request_context("/ncaaf/cards"):
                scoreboard = _runtime_scoreboard_projection(_row(), 8)
        self.assertNotIn("projection_sources", scoreboard)
        self.assertNotIn("projection_sources_mode", scoreboard)


if __name__ == "__main__":
    unittest.main()
