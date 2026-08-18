"""Pitch-type splits must load from a disk ARTIFACT, not only from a DiskCache.

`#440`. The sim consumes `pitch_type_whiff_mult` / `vs_pitch_type` as
`.get(pitch_type, 1.0)`, and they were empty on 449/449 production pitchers, so
a slider and a fastball were interchangeable.

The data existed, in a `DiskCache` under `vendor/mlb_bettingv2/data/cache/` —
which is **gitignored** AND inside the **ephemeral repo checkout** on Render. It
could never ship with a deploy and anything written there is discarded by the
next one (the `#389` shape). So on the worker the cache was always empty, the
cache-only loader always returned None, and every multiplier silently resolved
to 1.0.

THE TEST THAT MATTERS is the last class: **an EMPTY cache must still yield real
splits when the artifact is present**, because that is exactly the worker's
situation. A test that passes only with a warm local cache would prove nothing
about production.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from vendor.mlb_bettingv2.sim_engine.data import statcast_pitch_splits as sps
from vendor.mlb_bettingv2.sim_engine.data.disk_cache import DiskCache
from vendor.mlb_bettingv2.sim_engine.models import PitchType

SEASON = 2026
PID = 999001


def _artifact(tmp: Path, *, n_pitches: int = 2000) -> Path:
    out = tmp / "mlb_source/source_artifacts/data/pitch_splits"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"pitch_splits_{SEASON}.json"
    path.write_text(json.dumps({
        "schema_version": 1, "season": SEASON,
        "pitchers": {str(PID): {
            "n_pitches": n_pitches,
            "pitch_mix": {"FF": 0.5, "SL": 0.3, "CH": 0.2},
            "whiff_mult": {"FF": 0.65, "SL": 1.55, "CH": 1.40},
            "inplay_mult": {"FF": 0.88, "SL": 0.71, "CH": 1.03},
            "source": "test",
        }},
    }), encoding="utf-8")
    return path


class ArtifactLoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        sps._ARTIFACT_CACHE.clear()   # memoised per season

    def tearDown(self) -> None:
        sps._ARTIFACT_CACHE.clear()

    def test_empty_cache_still_yields_splits_from_the_artifact(self) -> None:
        """THE WORKER CASE. The DiskCache cannot exist on Render."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _artifact(root)
            empty_cache = DiskCache(root_dir=root / "cache", default_ttl_seconds=3600)
            with mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": str(root)}):
                sps._ARTIFACT_CACHE.clear()
                got = sps.fetch_pitcher_pitch_splits(
                    cache=empty_cache, pitcher_id=PID, season=SEASON)
        self.assertIsNotNone(got, "artifact was not read with an empty cache")
        self.assertEqual(got.n_pitches, 2000)
        self.assertAlmostEqual(got.whiff_mult[PitchType.SL], 1.55)
        self.assertAlmostEqual(got.whiff_mult[PitchType.FF], 0.65)

    def test_the_multipliers_actually_differ_by_pitch_type(self) -> None:
        """If every pitch resolved to the same multiplier the feature is inert."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _artifact(root)
            cache = DiskCache(root_dir=root / "cache", default_ttl_seconds=3600)
            with mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": str(root)}):
                sps._ARTIFACT_CACHE.clear()
                got = sps.fetch_pitcher_pitch_splits(
                    cache=cache, pitcher_id=PID, season=SEASON)
        vals = set(got.whiff_mult.values())
        self.assertGreater(len(vals), 1, "all pitch types share one multiplier")
        self.assertNotIn(1.0, vals, "a 1.0 multiplier is the inert default")

    def test_absent_artifact_falls_back_rather_than_raising(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = DiskCache(root_dir=root / "cache", default_ttl_seconds=3600)
            with mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": str(root)}):
                sps._ARTIFACT_CACHE.clear()
                got = sps.fetch_pitcher_pitch_splits(
                    cache=cache, pitcher_id=PID, season=SEASON)
        self.assertIsNone(got, "absent artifact + empty cache must be None, not an error")

    def test_unknown_pitcher_is_none_not_a_default(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _artifact(root)
            cache = DiskCache(root_dir=root / "cache", default_ttl_seconds=3600)
            with mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": str(root)}):
                sps._ARTIFACT_CACHE.clear()
                got = sps.fetch_pitcher_pitch_splits(
                    cache=cache, pitcher_id=PID + 12345, season=SEASON)
        self.assertIsNone(got)

    def test_a_thin_sample_in_the_artifact_is_still_honoured_but_marked(self) -> None:
        # The BUILDER drops thin samples (--min-pitches); the LOADER does not
        # second-guess a published artifact. Asserted so the two responsibilities
        # stay where they are.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _artifact(root, n_pitches=5)
            cache = DiskCache(root_dir=root / "cache", default_ttl_seconds=3600)
            with mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": str(root)}):
                sps._ARTIFACT_CACHE.clear()
                got = sps.fetch_pitcher_pitch_splits(
                    cache=cache, pitcher_id=PID, season=SEASON)
        self.assertIsNotNone(got)
        self.assertEqual(got.n_pitches, 5)


if __name__ == "__main__":
    unittest.main()
