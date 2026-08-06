"""Season resolution for the HR Targets board's Statcast matchup context.

`player_features_latest.json` is not reliably the latest season. Confirmed on
2026-08-05 that both copies under data/mlb_source/ (the plain root and
source_artifacts/) were season 2025 -- window 2025-03-01..2025-11-30, generated
2026-05-12 -- while a real 2026 feature set existed alongside them. The board
was therefore decorating 2026 matchups with 2025 barrel/xwOBA/launch-angle
numbers presented as current form.

These lock in: season-specific filenames are preferred over the `_latest`
alias, and a payload whose season does not match the requested date is treated
as UNAVAILABLE rather than silently rendered as this season's read.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.mlb import hr_targets


@pytest.fixture(autouse=True)
def _clear_feature_cache():
    # _load_json_path is lru_cached by path string; these tests write different
    # payloads to the same tmp paths across cases.
    hr_targets._load_json_path.cache_clear()
    yield
    hr_targets._load_json_path.cache_clear()


def _write_features(root, name, season, batters):
    target = root / "data" / "statcast" / "features" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"meta": {"season": season}, "batters": batters, "pitchers": {}}),
        encoding="utf-8",
    )
    return target


@pytest.fixture
def source_root(tmp_path, monkeypatch):
    root = tmp_path / "mlb_source"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(hr_targets, "_source_roots", lambda: [root])
    return root


class TestSeasonForDate:
    def test_parses_leading_year(self):
        assert hr_targets._season_for_date("2026-07-10") == 2026

    @pytest.mark.parametrize("value", ["", None, "not-a-date", "26-07-10"])
    def test_rejects_non_year(self, value):
        assert hr_targets._season_for_date(value) is None


class TestCandidateOrdering:
    def test_season_specific_precedes_latest_alias(self, source_root):
        names = [p.name for p in hr_targets._statcast_features_candidates(2026)]
        assert names.index("player_features_2026.json") < names.index("player_features_latest.json")

    def test_without_a_season_only_the_alias_is_tried(self, source_root):
        names = [p.name for p in hr_targets._statcast_features_candidates(None)]
        assert names == ["player_features_latest.json"]


class TestLoadStatcastFeatures:
    def test_prefers_season_specific_over_a_stale_latest(self, source_root):
        # The exact production shape: `_latest` is last season, and the real
        # current-season file sits next to it.
        _write_features(source_root, "player_features_latest.json", 2025, {"1": {"overall": {"xwoba": 0.250}}})
        _write_features(source_root, "player_features_2026.json", 2026, {"1": {"overall": {"xwoba": 0.400}}})

        payload = hr_targets._load_statcast_features(2026)

        assert payload["meta"]["season"] == 2026
        assert payload["batters"]["1"]["overall"]["xwoba"] == 0.400

    def test_wrong_season_alias_is_unavailable_not_substituted(self, source_root):
        # Only a 2025 file exists. Returning it for a 2026 date would render
        # last season's barrel rate as this season's form.
        _write_features(source_root, "player_features_latest.json", 2025, {"1": {"overall": {"xwoba": 0.250}}})

        assert hr_targets._load_statcast_features(2026) == {}

    def test_alias_is_used_when_its_season_matches(self, source_root):
        _write_features(source_root, "player_features_latest.json", 2026, {"1": {"overall": {"xwoba": 0.400}}})

        payload = hr_targets._load_statcast_features(2026)

        assert payload["meta"]["season"] == 2026

    def test_missing_files_degrade_to_empty(self, source_root):
        assert hr_targets._load_statcast_features(2026) == {}

    def test_unknown_season_accepts_whatever_is_present(self, source_root):
        # No date to match against -- the caller can't do better than the alias.
        _write_features(source_root, "player_features_latest.json", 2025, {"1": {"overall": {"xwoba": 0.250}}})

        assert hr_targets._load_statcast_features(None)["meta"]["season"] == 2025

    def test_payload_without_meta_season_is_not_treated_as_matching(self, source_root):
        target = source_root / "data" / "statcast" / "features" / "player_features_latest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"batters": {}, "pitchers": {}}), encoding="utf-8")

        assert hr_targets._load_statcast_features(2026) == {}


class TestPitchMixContextDegradation:
    def test_no_statcast_yields_no_context_rather_than_raising(self, source_root, monkeypatch):
        # The board must render with an empty matchup block, not 500, when the
        # season-matched feature set is absent.
        monkeypatch.setattr(hr_targets, "_load_roster_game_payload", lambda *a, **k: {})

        assert hr_targets._pitch_mix_context("2026-07-10", {"game_pk": 1, "batter_id": 2}) == {}


class TestAnalyticsCallouts:
    """The advanced metrics behind the HR Top 10 ranking.

    Before this, these numbers were computed per row (_apply_pitch_mix_context
    merges them into hr_target_metrics) and reached the UI only as prose, or
    were folded into an opaque "Support" score. The board now names them with
    their league reference so a reader can size the edge.
    """

    BASELINES = {
        "batter_barrel": 0.086,
        "batter_hardhit": 0.412,
        "batter_xwoba": 0.320,
        "batter_la": 12.0,
        "pitcher_barrel": 0.086,
        "pitcher_xwoba": 0.320,
    }

    def _target(self, **metrics):
        return {
            "player_name": "Test Hitter",
            "probability": "18.0%",
            "pa_mean": 4.3,
            "lineup_order": 3,
            "hr_target_metrics": metrics,
            "source_row": {},
        }

    def test_elite_batted_ball_reads_as_boost(self):
        target = self._target(batter_barrel_rate=0.161, batter_hardhit_rate=0.520)
        callouts = hr_targets._hr_analytics_callouts(target, self.BASELINES)
        barrel = next(c for c in callouts if c["label"] == "Barrel rate")
        assert barrel["tone"] == "boost"
        assert "8.6%" in barrel["detail"]  # league reference is shown

    def test_below_average_reads_as_drag_not_hidden(self):
        # A top-10 hitter facing a suppressing matchup is still top-10; hiding
        # the negative would overstate the case.
        target = self._target(batter_barrel_rate=0.030)
        callouts = hr_targets._hr_analytics_callouts(target, self.BASELINES)
        assert next(c for c in callouts if c["label"] == "Barrel rate")["tone"] == "drag"

    def test_strongest_deviation_ranks_first(self):
        target = self._target(batter_barrel_rate=0.200, batter_launch_angle_mean=12.2)
        callouts = hr_targets._hr_analytics_callouts(target, self.BASELINES)
        assert callouts[0]["label"] == "Barrel rate"

    def test_missing_metrics_are_omitted_not_zero_filled(self):
        callouts = hr_targets._hr_analytics_callouts(self._target(), self.BASELINES)
        assert all(c["label"] != "Barrel rate" for c in callouts)

    def test_callouts_are_capped(self):
        target = self._target(
            batter_barrel_rate=0.20, batter_hardhit_rate=0.55, batter_xwoba=0.44,
            batter_launch_angle_mean=22.0, pitch_mix_score=1.30, pitcher_barrel_rate=0.14,
        )
        assert len(hr_targets._hr_analytics_callouts(target, self.BASELINES)) <= 6

    def test_rationale_names_the_supporting_metrics(self):
        target = self._target(batter_barrel_rate=0.161, batter_xwoba=0.44)
        callouts = hr_targets._hr_analytics_callouts(target, self.BASELINES)
        text = hr_targets._hr_selection_rationale(target, callouts)
        assert "Test Hitter" in text and "18.0%" in text
        assert "barrel rate" in text.lower()

    def test_rationale_is_honest_when_nothing_stands_out(self):
        callouts = hr_targets._hr_analytics_callouts(self._target(), self.BASELINES)
        text = hr_targets._hr_selection_rationale(self._target(), callouts)
        assert "without a standout" in text


class TestSettlementSurfaceGuard:
    """HR picks have no market line, so settlement must not send them down the
    line-comparison path. That branch used to string-match the literal display
    label, so renaming the surface would have silently mis-graded every HR row.
    """

    def test_accepts_both_old_and_new_surface_labels(self):
        from syndicate.blueprints.home import _is_hr_target_surface

        assert _is_hr_target_surface("HR targets")
        assert _is_hr_target_surface("HR Top 10")
        assert _is_hr_target_surface("  hr top 10  ")

    def test_rejects_lined_prop_surfaces(self):
        from syndicate.blueprints.home import _is_hr_target_surface

        for other in ("Hits", "Pitcher ladders", "Total bases", "", None):
            assert not _is_hr_target_surface(other)
