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
            reports_root = data_root / "reports"
            nba_root = data_root / "nba_source"
            (nba_root / "data" / "processed").mkdir(parents=True, exist_ok=True)
            (nba_root / "data" / "processed" / "recommendations_slate_2026-06-08.json").write_text("{}", encoding="utf-8")
            (nba_root / "data" / "processed" / "props_edges_2026-06-08.csv").write_text("player,edge\n", encoding="utf-8")
            (nba_root / "data" / "processed" / "props_recommendations_2026-06-08.csv").write_text("player,market\n", encoding="utf-8")
            (nba_root / "data" / "processed" / "live_snapshots").mkdir(parents=True, exist_ok=True)
            (nba_root / "data" / "processed" / "live_snapshots" / "live_state_2026-06-08.json").write_text("{}", encoding="utf-8")

            with patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": str(data_root), "SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False):
                manifest = load_artifact_manifest(sport_slug="nba", selected_date="2026-06-08")

        self.assertEqual(manifest.sport_slug, "nba")
        self.assertGreaterEqual(len(manifest.recommendations), 1)
        self.assertGreaterEqual(len(manifest.edges), 1)
        self.assertGreaterEqual(len(manifest.live_data), 1)

    def test_loader_prefers_published_reports_manifest_over_source_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            data_root = repo_root / "data"
            reports_root = repo_root / "reports"
            nba_root = data_root / "nba_source"
            published_manifest_path = reports_root / "manifests" / "nba.json"

            (nba_root / "source_artifacts" / "data" / "processed").mkdir(parents=True, exist_ok=True)
            (nba_root / "source_artifacts" / "data" / "processed" / "recommendations_slate_2026-06-29.json").write_text("{}", encoding="utf-8")
            (nba_root / "source_artifacts" / "data" / "processed" / "props_edges_2026-06-29.csv").write_text("player,edge\n", encoding="utf-8")
            published_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            published_manifest_path.write_text(
                "\n".join(
                    [
                        "{",
                        '  "sport": "nba",',
                        '  "date": "2026-07-03",',
                        '  "status": "complete",',
                        '  "artifact_paths": [',
                        '    "data/nba_source/source_artifacts/data/processed/recommendations_slate_2026-07-03.json",',
                        '    "data/nba_source/source_artifacts/data/processed/props_edges_2026-07-03.csv"',
                        "  ],",
                        '  "metadata": {"date": "2026-07-03", "execution_mode": "source"}',
                        "}",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(
                "os.environ",
                {
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                },
                clear=False,
            ):
                manifest = load_artifact_manifest(sport_slug="nba", selected_date="2026-07-03")

        self.assertEqual(manifest.selected_date, "2026-07-03")
        self.assertEqual(manifest.source_root, str(published_manifest_path.parent.resolve()))
        self.assertEqual(len(manifest.recommendations), 1)
        self.assertEqual(len(manifest.edges), 1)
        self.assertEqual(manifest.recommendations[0].date, "2026-07-03")

    def test_loader_aggregates_all_from_published_reports_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            data_root = repo_root / "data"
            reports_root = repo_root / "reports"
            for sport_slug in ("mlb", "nba"):
                sport_root = data_root / f"{sport_slug}_source" / "source_artifacts" / "data" / "processed"
                sport_root.mkdir(parents=True, exist_ok=True)
                (sport_root / f"recommendations_slate_2026-07-03.json").write_text("{}", encoding="utf-8")
                (sport_root / f"props_edges_2026-07-03.csv").write_text("player,edge\n", encoding="utf-8")
                (sport_root / f"live_state_2026-07-03.json").write_text("{}", encoding="utf-8")
                published_manifest_path = reports_root / "manifests" / f"{sport_slug}.json"
                published_manifest_path.parent.mkdir(parents=True, exist_ok=True)
                published_manifest_path.write_text(
                    "\n".join(
                        [
                            "{",
                            f'  "sport": "{sport_slug}",',
                            '  "date": "2026-07-03",',
                            '  "status": "complete",',
                            '  "artifact_paths": [',
                            f'    "{(sport_root / "recommendations_slate_2026-07-03.json").as_posix()}",',
                            f'    "{(sport_root / "props_edges_2026-07-03.csv").as_posix()}",',
                            f'    "{(sport_root / "live_state_2026-07-03.json").as_posix()}"',
                            "  ],",
                            '  "metadata": {"date": "2026-07-03", "execution_mode": "source"}',
                            "}",
                        ]
                    ),
                    encoding="utf-8",
                )

            with patch.dict(
                "os.environ",
                {
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                },
                clear=False,
            ):
                manifest = load_artifact_manifest(sport_slug="all", selected_date="2026-07-03")

        self.assertEqual(manifest.sport_slug, "all")
        self.assertEqual(manifest.selected_date, "2026-07-03")
        self.assertEqual(manifest.source_root, str((reports_root / "manifests").resolve()))
        self.assertGreaterEqual(len(manifest.recommendations), 2)
        self.assertGreaterEqual(len(manifest.edges), 2)
        self.assertGreaterEqual(len(manifest.live_data), 2)


if __name__ == "__main__":
    unittest.main()