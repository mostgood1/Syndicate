from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared.artifact_manifests import ArtifactManifest
from syndicate.features.shared.artifact_manifests import ArtifactReference
from syndicate.features.shared.artifact_manifests import load_artifact_manifest


class ArtifactManifestTest(unittest.TestCase):
    def test_artifact_reference_to_dict_round_trips_core_fields(self) -> None:
        ref = ArtifactReference.from_path(
            Path("C:/tmp/data/nba_source/data/processed/props_recommendations_2026-06-08.csv"),
            category="recommendations",
            sport_slug="nba",
            date="2026-06-08",
            label="Props recommendations",
            source_kind="filesystem",
            source_name="nba_source",
            metadata={"matched_by": "path_scan"},
        )

        payload = ref.to_dict()
        self.assertEqual(payload["category"], "recommendations")
        self.assertEqual(payload["sport_slug"], "nba")
        self.assertEqual(payload["date"], "2026-06-08")
        self.assertEqual(payload["label"], "Props recommendations")

    def test_manifest_can_be_constructed_from_references(self) -> None:
        manifest = ArtifactManifest(
            sport_slug="mlb",
            selected_date="2026-06-08",
            predictions=(
                ArtifactReference.from_path(
                    Path("C:/tmp/data/mlb_source/data/daily/daily_summary_2026_06_08.json"),
                    category="predictions",
                    sport_slug="mlb",
                    date="2026-06-08",
                ),
            ),
            edges=(),
            recommendations=(),
            live_data=(),
        )

        payload = manifest.to_dict()
        self.assertEqual(payload["sport_slug"], "mlb")
        self.assertEqual(payload["selected_date"], "2026-06-08")
        self.assertEqual(payload["counts"]["predictions"], 1)

    def test_loader_discovers_sport_artifacts_from_existing_folder_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            nba_root = data_root / "nba_source"
            (nba_root / "data" / "processed").mkdir(parents=True, exist_ok=True)
            (nba_root / "data" / "processed" / "recommendations_slate_2026-06-08.json").write_text("{}", encoding="utf-8")
            (nba_root / "data" / "processed" / "props_edges_2026-06-08.csv").write_text("player,edge\n", encoding="utf-8")
            (nba_root / "data" / "processed" / "props_recommendations_2026-06-08.csv").write_text("player,market\n", encoding="utf-8")
            (nba_root / "data" / "processed" / "live_snapshots").mkdir(parents=True, exist_ok=True)
            (nba_root / "data" / "processed" / "live_snapshots" / "live_state_2026-06-08.json").write_text("{}", encoding="utf-8")

            with patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": str(data_root)}, clear=False):
                manifest = load_artifact_manifest(sport_slug="nba", selected_date="2026-06-08")

        self.assertEqual(manifest.sport_slug, "nba")
        self.assertGreaterEqual(len(manifest.recommendations), 1)
        self.assertGreaterEqual(len(manifest.edges), 1)
        self.assertGreaterEqual(len(manifest.live_data), 1)


if __name__ == "__main__":
    unittest.main()