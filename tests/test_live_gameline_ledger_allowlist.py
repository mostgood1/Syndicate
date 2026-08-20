"""The live-gameline ledger must be READABLE OFF-WORKER. `#440`.

WHY. 3,748 rows were recorded on 2026-08-17 and not one has been evaluated,
because the file lives on the refresh-worker's disk and
`/api/ops/artifacts/stream` returned `403 path is not an allowed hot artifact`
-- no allowlist pattern matched. Re-verified 2026-08-18 and again 2026-08-20.
An unreadable measurement is the same as no measurement.

BOTH MATCHERS ARE ASSERTED, and that is the point. `is_hot_artifact_relative_path`
uses `fnmatch`, where `*` CROSSES `/`; the publish sweep uses `Path.glob`, where
it does NOT. On 2026-08-20 that difference hid a bug for hours: patterns that
"matched the allowlist" pulled nothing, because the two disagree.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.shared.artifact_publisher import (  # noqa: E402
    HOT_ARTIFACT_PATTERNS, is_hot_artifact_relative_path)

LEDGERS = [
    "mlb_source/data/live_gameline_ledger/live_gameline_ledger_2026-08-17.jsonl",
    "mlb_source/source_artifacts/data/live_gameline_ledger/live_gameline_ledger_2026-08-20.jsonl",
    "nba_source/data/live_gameline_ledger/live_gameline_ledger_2026-01-02.jsonl",
]


def _glob_like(path: str, pattern: str) -> bool:
    """Path.glob semantics: `*` does NOT cross a directory separator."""
    return re.match("^" + re.escape(pattern).replace(r"\*", "[^/]*") + "$", path) is not None


@pytest.mark.parametrize("rel", LEDGERS)
def test_read_path_allows_the_ledger(rel):
    """Without this the ops endpoints answer 403 and the rows stay unreadable."""
    assert is_hot_artifact_relative_path(rel), (
        f"{rel} is not allowlisted -- /api/ops/artifacts/stream will 403 and the "
        "recorded rows remain unevaluable"
    )


@pytest.mark.parametrize("rel", LEDGERS)
def test_sweep_semantics_also_match(rel):
    """fnmatch matching is NOT sufficient: the publisher walks with Path.glob,
    where `*` does not cross `/`. A pattern that satisfies only fnmatch reads as
    allowlisted while publishing nothing."""
    pats = [p for p in HOT_ARTIFACT_PATTERNS if "live_gameline_ledger" in p]
    assert pats, "no live_gameline_ledger pattern registered at all"
    assert any(_glob_like(rel, p) for p in pats), (
        f"{rel} matches fnmatch but NOT glob -- the sweep would never publish it"
    )


def test_a_non_ledger_jsonl_is_not_swept_in():
    """The pattern must not be so broad it drags unrelated .jsonl files across."""
    assert not any(
        _glob_like("mlb_source/data/live_gameline_ledger/notes.txt", p)
        for p in HOT_ARTIFACT_PATTERNS if "live_gameline_ledger" in p)
