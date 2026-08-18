"""Regression tests for the conditional pitch mix consumer. `#440`.

**These are REACHABILITY tests before they are correctness tests.** Four features
in this lane were built, believed shipped, and were inert -- `.get(key, 1.0)`
defaults make an unfed field indistinguishable from a working one at every level
except the data. So the load-bearing assertion here is `off != on`, not "the
number is plausible".

The round-trip test is the other half: `roster_artifact` serialises an EXPLICIT
list of fields, not a `dataclasses.fields()` walk, and the worker reads roster
artifacts (`--use-roster-artifacts` defaults on). A field that survives in memory
and vanishes through the artifact is invisible locally and dead in production.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "vendor" / "mlb_bettingv2"))

from sim_engine.models import PitchType  # noqa: E402
from sim_engine.simulate import (  # noqa: E402
    _build_weight_cdf,
    _conditional_cdf,
    _sample_weight_cdf,
)


class _Pitcher:
    """Only the three attributes `_conditional_cdf` touches."""

    def __init__(self, cells=None, buckets=None):
        self.conditional_arsenal = cells or {}
        self.count_bucket_map = buckets or {}


SEASON = {PitchType.FF: 0.60, PitchType.SL: 0.40}
BUCKETS = {"3-0": "3-0", "0-2": "0-2|1-2", "1-2": "0-2|1-2"}
CELLS = {
    "3-0|R": {PitchType.FF: 0.95, PitchType.SL: 0.05},
    "0-2|1-2|R": {PitchType.FF: 0.30, PitchType.SL: 0.70},
}


def _ff_share(entry, n=20000, seed=7):
    types, cdf, total = entry
    rng = random.Random(seed)
    hits = sum(1 for _ in range(n)
               if _sample_weight_cdf(rng, types, cdf, total, PitchType.FF) is PitchType.FF)
    return hits / n


@pytest.fixture()
def fallback():
    return _build_weight_cdf(SEASON)


def test_no_artifact_degrades_to_the_season_cdf(fallback):
    """A missing artifact must return the SAME OBJECT, not an empty mix.

    An empty mix would not raise -- `_sample_weight_cdf` would fall through to
    its `default` and the pitcher would throw 100% four-seamers, which reads as
    a plausible simulation rather than as a failure.
    """
    assert _conditional_cdf(_Pitcher(), 3, 0, "R", fallback) is fallback


def test_unknown_count_and_uncovered_hand_fall_back(fallback):
    p = _Pitcher(CELLS, BUCKETS)
    assert _conditional_cdf(p, 2, 1, "R", fallback) is fallback   # count not bucketed
    assert _conditional_cdf(p, 3, 0, "L", fallback) is fallback   # hand not covered


def test_reachability_off_differs_from_on(fallback):
    """THE gate. If these are equal the wiring is decorative."""
    off = _conditional_cdf(_Pitcher(), 3, 0, "R", fallback)
    on = _conditional_cdf(_Pitcher(CELLS, BUCKETS), 3, 0, "R", fallback)
    assert off != on


def test_same_pitcher_throws_a_different_mix_by_count(fallback):
    """The whole point: one pitcher, two counts, two mixes."""
    p = _Pitcher(CELLS, BUCKETS)
    behind = _ff_share(_conditional_cdf(p, 3, 0, "R", fallback))
    ahead = _ff_share(_conditional_cdf(p, 0, 2, "R", fallback))
    assert behind == pytest.approx(0.95, abs=0.02)
    assert ahead == pytest.approx(0.30, abs=0.02)
    assert behind - ahead > 0.50


def test_counts_sharing_a_bucket_agree(fallback):
    p = _Pitcher(CELLS, BUCKETS)
    assert _conditional_cdf(p, 0, 2, "R", fallback) == _conditional_cdf(p, 1, 2, "R", fallback)


def test_canonical_collision_sums_probability_mass(tmp_path, monkeypatch):
    """ST and SL both canonicalise to SL. These are PROBABILITIES, so the mass
    adds -- unlike `arsenal.py`, where the values are multipliers and the merge
    is a usage-weighted mean. Getting this backwards would silently halve a
    sweeper-first pitcher's breaking-ball usage."""
    from sim_engine.data import conditional_mix as cm

    art = {
        "count_to_bucket": {"0-2": "0-2"},
        "pitchers": {"111": {"0-2|R": {"SL": 0.30, "ST": 0.45, "FF": 0.25}}},
    }
    d = tmp_path / "mlb_source" / "source_artifacts" / "data" / "conditional_mix"
    d.mkdir(parents=True)
    (d / "conditional_mix_2026.json").write_text(json.dumps(art), encoding="utf-8")
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    cm._CACHE.clear()

    class _Player:
        mlbam_id = 111

    class _P:
        player = _Player()

    prof = _P()
    assert cm.apply_conditional_mix_to_pitcher(prof, season=2026) is True
    mix = prof.conditional_arsenal["0-2|R"]
    assert set(mix) == {PitchType.SL, PitchType.FF}
    assert mix[PitchType.SL] == pytest.approx(0.75, abs=1e-6)   # 0.30 + 0.45
    cm._CACHE.clear()


def test_survives_the_roster_artifact_round_trip():
    """The worker reads roster artifacts. Serialisation there is an explicit
    field list, so a field omitted from it is dead in production while looking
    perfectly healthy in memory."""
    from sim_engine.data import roster_artifact as ra

    src = inspect_src = Path(ra.__file__).read_text(encoding="utf-8")
    assert '"conditional_arsenal"' in src, "not serialised -- would vanish on the worker"
    assert '"count_bucket_map"' in src, "bucket map not serialised -- cells unreachable"
    assert 'p.get("conditional_arsenal")' in src, "not deserialised"
    assert "conditional_arsenal_source" in src, "provenance not carried"
