"""`#385` -- the empty-pool fallback refilled a pool nobody serves.

`collect_candidates_with_fallback_merge` calls `collect_all_recommendations`
when the primary pool comes back empty. That fallback exists to REFILL the
legacy pool. When Layer 2 is primary the legacy pool is not what gets served,
so the refill buys nothing.

MEASURED on refresh-worker 2026-08-12 from `#376`'s BUILD_SPAN timings --
`candidate_collection_with_fallback` was 1,425 of 1,427 seconds attributed
across every stage:

    16:54-17:41   0.01s x 13 builds   (pool non-empty, fallback idle)
    17:06:20      321.40s
    17:56:21      521.30s
    18:16:09      582.38s

Served-board contribution the same day: `legacy_candidate_count = 0`,
`ranked_all` 127/127 from the Layer 2 shortlist.
"""

from __future__ import annotations

from unittest.mock import patch

import syndicate.features.intelligence as intel


def _no_candidates(*args, **kwargs):
    return []


def test_the_fallback_is_skipped_when_layer2_is_primary():
    called = []

    def _fallback(*args, **kwargs):
        called.append(1)
        return [{"id": "expensive"}]

    with patch.object(intel, "collect_candidates", _no_candidates), patch.object(
        intel, "collect_all_recommendations", _fallback
    ):
        out = intel.collect_candidates_with_fallback_merge(
            [], {}, None, selected_date="2026-08-12", apply_empty_pool_fallback=False
        )
    assert called == [], "the 580s fallback ran while Layer 2 owned the board"
    assert out == []


def test_the_fallback_still_runs_when_layer2_is_not_primary():
    """The gate must be a gate, not a deletion. If Layer 2 stops being primary
    the legacy pool is served again and the fallback has to come back."""
    called = []

    def _fallback(*args, **kwargs):
        called.append(1)
        return [{"id": "recovered"}]

    with patch.object(intel, "collect_candidates", _no_candidates), patch.object(
        intel, "collect_all_recommendations", _fallback
    ):
        out = intel.collect_candidates_with_fallback_merge(
            [], {}, None, selected_date="2026-08-12", apply_empty_pool_fallback=True,
            # Isolate the EMPTY-pool branch. Left on, the 1-row result trips the
            # thin-pool merge and calls the fallback a second time -- correct
            # behaviour, but it would make this test about the wrong branch.
            apply_thin_pool_merge=False,
        )
    assert called == [1], "the fallback was removed rather than gated"
    assert out == [{"id": "recovered"}]


def test_the_default_preserves_the_old_behaviour():
    # Callers that never opt in (run_intelligence_query, the ops candidate
    # trace) must be unaffected by this change.
    called = []

    def _fallback(*args, **kwargs):
        called.append(1)
        return [{"id": "recovered"}]

    with patch.object(intel, "collect_candidates", _no_candidates), patch.object(
        intel, "collect_all_recommendations", _fallback
    ):
        intel.collect_candidates_with_fallback_merge(
            [], {}, None, selected_date="2026-08-12", apply_thin_pool_merge=False
        )
    assert called == [1], "an unrelated caller silently lost its fallback"


def test_a_non_empty_pool_never_reaches_either_branch():
    def _some(*args, **kwargs):
        return [{"id": "a"}, {"id": "b"}]

    def _fallback(*args, **kwargs):
        raise AssertionError("fallback ran on a non-empty pool")

    with patch.object(intel, "collect_candidates", _some), patch.object(
        intel, "collect_all_recommendations", _fallback
    ):
        out = intel.collect_candidates_with_fallback_merge(
            [], {}, None, selected_date="2026-08-12",
            apply_empty_pool_fallback=False, apply_edge_filter=False,
            apply_thin_pool_merge=False,
        )
    assert len(out) == 2
