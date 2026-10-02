"""The WNBA game-total calibration must be allowlisted (model_engine_standard.md Sec3).

`calibration_totals_<date>.json` is written by the WNBA refresh
(scripts/build_wnba_totals_calibration.py) and read by the smart sim. Without
an allowlist entry it is unobservable through `/api/ops/artifacts/*` and could
never cross from a worker disk to web. Checked through the REAL predicates
against the path the fleet actually wrote on 2026-10-01.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import artifact_publisher as ap

WRITTEN = (
    "wnba_source/data/processed/calibration_totals_2026-09-30.json",
    "wnba_source/source_artifacts/data/processed/calibration_totals_2026-09-30.json",
)


@pytest.mark.parametrize("rel", WRITTEN)
def test_calibration_totals_is_hot_and_exportable(rel):
    assert ap.is_hot_artifact_relative_path(rel)
    assert ap.is_exportable_artifact_relative_path(rel)


def test_pattern_does_not_widen_to_other_sports_or_files():
    assert not ap.is_hot_artifact_relative_path("nba_source/data/processed/calibration_totals_2026-09-30.json")
    assert not ap.is_hot_artifact_relative_path("wnba_source/data/processed/calibration_totals_2026-09-30.csv")
