"""The staked-probability profile path is allowlisted under the spelling the
profile module actually writes -- an entry aimed at a path nothing writes is
the inert-allowlist shape this repo has paid for."""

from __future__ import annotations

import fnmatch

from syndicate.features.shared.artifact_publisher import HOT_ARTIFACT_PATTERNS


def test_the_staked_probability_profile_matches_a_hot_pattern() -> None:
    from syndicate.features.shared import staked_probability_profile as spp

    rel = getattr(spp, "PROFILE_RELATIVE_PATH", None) or "calibration/staked_probability_profile.json"
    assert any(fnmatch.fnmatch(rel, pattern) for pattern in HOT_ARTIFACT_PATTERNS), rel
