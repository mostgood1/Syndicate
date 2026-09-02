"""`#626`(h) -- `_project_evaluation_record`, and the equivalence that makes it
safe.

WHY THE PROJECTION EXISTS. Peak for the accuracy summary's ledger load was
**4.014 resident bytes per file byte** (R2 0.999998, intercept zero), because
`_latest_by_recommendation_id` retains every parsed record and production
records average 37,632 B -- they embed `artifact_metadata.manifest_summary`.
Measured on an 831,038,410 B corpus: **3,181.1 MiB**, against a 4,096 MiB worker
already peaking at anon ~1,877 MiB. It OOM-killed refresh-worker.

The statistics read about twenty scalars per record. Projecting to those as the
stream runs drops the same load to **42.2 MiB / 8 dates** -- 75x better than the
baseline and 8x better than a 90MB byte budget that carried ONE date.

WHY THE EQUIVALENCE TEST IS THE POINT. The alternative design -- fold-as-you-go
accumulators -- would be O(segments + dates) instead of O(records), and would
require a SECOND implementation of `_win_rate`, `_roi`, `_price_clv`, `_clv`,
`_calibration` and `binary_calibration_metrics`. `_roi`'s stake rule alone
(absent counts as 1.0, non-numeric is excluded, none-at-all falls back to
one-per-record) is exactly the kind of detail a re-derivation gets subtly wrong
with every test still green.

The projection keeps ONE implementation and moves the risk somewhere a test can
see it: if it drops a field any statistic reads, the summaries diverge and these
tests fail. That is the whole safety argument, so it is asserted on the REAL
builders over REAL records, per sport, not on a fixture.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import intelligence_evaluation as ie


SPORTS = [None, "mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"]


@pytest.fixture(scope="module")
def record_sets():
    """Real local ledger records, raw and projected."""
    raw = ie._latest_by_recommendation_id(ie._stream_record_payloads(ledger_path=None))
    if not raw:
        pytest.skip("no local evaluation ledger chunks to compare against")
    projected = [ie._project_evaluation_record(record) for record in raw]
    return raw, projected


def _fingerprint(rows, sport):
    return json.dumps(
        {
            "metrics": ie.compute_metrics(records=rows, sport=sport),
            "segmented": ie.build_segmented_reliability_profile(records=rows, sport=sport),
        },
        sort_keys=True,
        default=str,
    )


@pytest.mark.parametrize("sport", SPORTS)
def test_projected_records_produce_identical_statistics(record_sets, sport):
    """The load-bearing assertion. A field the projection drops shows up here as
    a divergence rather than as a wrong number on a board."""
    raw, projected = record_sets
    assert _fingerprint(raw, sport) == _fingerprint(projected, sport), (
        "projection changed the statistics for sport=%r -- a field the "
        "statistics read is missing from _PROJECTED_* " % sport
    )


def test_projection_actually_shrinks_the_working_set(record_sets):
    """Off != on. A projection that copied everything would pass the
    equivalence test perfectly and be worthless."""
    import pickle

    raw, projected = record_sets
    raw_size = len(pickle.dumps(raw))
    projected_size = len(pickle.dumps(projected))
    assert projected_size * 4 < raw_size, (
        "projection is not shrinking the working set (%d -> %d)" % (raw_size, projected_size)
    )


def test_dedup_identity_survives_projection(record_sets):
    """`_latest_by_recommendation_id` runs AFTER the projection in
    `build_accuracy_summary`, so record_type / recommendation_id / prediction_id
    must survive it or the reduction silently changes shape."""
    raw, projected = record_sets
    assert len(ie._latest_by_recommendation_id(projected)) == len(
        ie._latest_by_recommendation_id(raw)
    )


def test_recommendation_source_fallback_is_preserved():
    """`_recommendation_source` branches on `if recommendation:` and falls back
    to the WHOLE record when it is empty. A projection that emptied a non-empty
    recommendation would flip that branch, so a truthy source must stay truthy."""
    record = {
        "recommendation_id": "r1",
        "result": "win",
        "recommendation": {"totally_unused_field": 1},
    }
    slim = ie._project_evaluation_record(record)
    assert slim.get("recommendation"), "a truthy recommendation must project truthy"

    bare = ie._project_evaluation_record({"recommendation_id": "r2", "result": "win"})
    assert "recommendation" not in bare, "must not invent a recommendation"


def test_absent_and_malformed_inputs_do_not_raise():
    assert ie._project_evaluation_record({}) == {}
    assert ie._project_evaluation_record(None) == {}
    weird = ie._project_evaluation_record(
        {"recommendation": "not-a-mapping", "artifact_metadata": [], "result": "loss"}
    )
    assert weird["result"] == "loss"
    assert "recommendation" not in weird
    assert "artifact_metadata" not in weird


def test_full_summary_matches_between_projected_and_raw(record_sets, monkeypatch):
    """End to end through `build_accuracy_summary`'s own output shape, with the
    volatile fields removed."""
    raw, projected = record_sets

    def _stable(summary):
        out = dict(summary)
        out.pop("generated_at", None)
        out.pop("ledger_coverage", None)
        return json.dumps(out, sort_keys=True, default=str)

    for sport in ("mlb", "wnba", None):
        a = _stable(ie.build_accuracy_summary(records=raw, sport=sport))
        b = _stable(ie.build_accuracy_summary(records=projected, sport=sport))
        assert a == b, "build_accuracy_summary diverged for sport=%r" % sport
