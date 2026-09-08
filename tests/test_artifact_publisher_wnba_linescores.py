"""The WNBA per-quarter linescore sidecar is allowlisted under the SAME spelling
the producer and the grader share -- a glob aimed at a path nothing writes is
the inert-allowlist shape this repo has paid for (smartsim2_projections)."""

from __future__ import annotations

import fnmatch

from syndicate.features.shared.artifact_publisher import HOT_ARTIFACT_PATTERNS
from syndicate.features.shared.bet_status_wnba import linescores_relative_path


def test_the_linescore_sidecar_matches_a_hot_pattern() -> None:
    path = linescores_relative_path("2026-09-08")
    assert any(fnmatch.fnmatch(path, pattern) for pattern in HOT_ARTIFACT_PATTERNS), path


def test_the_history_shaped_name_does_not_match() -> None:
    assert not any(
        fnmatch.fnmatch("wnba_source/data/processed/linescores_history.json", pattern)
        for pattern in HOT_ARTIFACT_PATTERNS
        if "linescores" in pattern
    )
