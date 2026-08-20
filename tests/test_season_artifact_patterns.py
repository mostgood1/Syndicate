"""The season-artifact pull patterns must actually MATCH. `#440`.

MEASURED 2026-08-20. `_SEASON_ARTIFACT_PATTERNS` held bare filename globs
(`arsenal_*.json`). The export endpoint matches with
`fnmatch(relative_path, pattern)` (`ops.py:1349`) where `relative_path` is the
FULL path, and fnmatch anchors at both ends -- so every pattern matched NOTHING.
All five requests returned zero files, `pull_season_artifacts()` returned 0, and
every season-scoped sim input was absent from the refresh-worker's disk.

Downstream that read as `pitch_type_whiff_mult`, `conditional_arsenal` and
`statcast_splits_*` sitting at 0.0% in production while the artifacts were
built, allowlisted, published, schema-valid on web, and their consumers provably
reached. It cost four wrong hypotheses to find, because the diagnostic line that
would have said `written=0` prints to a disk file Render's log API cannot serve.

These tests assert against REAL relative paths, and one of them asserts the
BROKEN form is still broken -- so the bug cannot be reintroduced by "tidying"
the leading `*` away.
"""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.shared.artifact_publisher import (  # noqa: E402
    _SEASON_ARTIFACT_PATTERNS, HOT_ARTIFACT_PATTERNS)

# The paths the publisher actually writes, verbatim.
REAL_PATHS = {
    "arsenal": "mlb_source/source_artifacts/data/arsenal/arsenal_2026.json",
    "quality": "mlb_source/source_artifacts/data/quality/quality_2026.json",
    "batted_ball": "mlb_source/source_artifacts/data/batted_ball/batted_ball_2026.json",
    "pitch_splits": "mlb_source/source_artifacts/data/pitch_splits/pitch_splits_2026.json",
    "conditional_mix": "mlb_source/source_artifacts/data/conditional_mix/conditional_mix_2026.json",
}


@pytest.mark.parametrize("name,rel", sorted(REAL_PATHS.items()))
def test_every_season_input_is_matched_by_some_pattern(name, rel):
    """The whole point: a pattern that matches nothing pulls nothing, silently."""
    hits = [p for p in _SEASON_ARTIFACT_PATTERNS if fnmatch.fnmatch(rel, p)]
    assert hits, (
        f"{name}: NO pattern in _SEASON_ARTIFACT_PATTERNS matches {rel!r}. "
        "pull_season_artifacts() will return 0 and the input will be absent "
        "from the worker -- which reads downstream as a 0.0% field, not an error."
    )


@pytest.mark.parametrize("name,rel", sorted(REAL_PATHS.items()))
def test_the_bare_filename_form_is_still_broken(name, rel):
    """Pin the actual bug so the leading `*` cannot be 'tidied' away.

    If this ever fails, fnmatch semantics changed and the guidance in the
    comment above _SEASON_ARTIFACT_PATTERNS needs revisiting.
    """
    bare = rel.rsplit("/", 1)[-1].replace("2026", "*")
    assert not fnmatch.fnmatch(rel, bare), (
        f"bare form {bare!r} unexpectedly matches {rel!r} -- the documented "
        "reason for the leading '*' no longer holds"
    )


def test_patterns_are_anchored_enough_to_not_sweep_everything():
    """A leading `*` fixes the anchor; `*` alone would pull the whole tree."""
    for p in _SEASON_ARTIFACT_PATTERNS:
        assert p not in ("*", "*.json"), f"{p!r} is too broad"
        assert p.endswith(".json")


@pytest.mark.parametrize("name,rel", sorted(REAL_PATHS.items()))
def test_the_input_is_also_allowlisted_for_export(name, rel):
    """Matching the pull pattern is not sufficient -- the export endpoint gates
    on HOT_ARTIFACT_PATTERNS too. Both must hold or the pull still gets zero."""
    assert any(fnmatch.fnmatch(rel, p) for p in HOT_ARTIFACT_PATTERNS), (
        f"{name}: {rel} is not allowlisted, so export will refuse it even "
        "though the pull pattern matches"
    )
