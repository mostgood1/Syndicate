from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared.basketball_props_smart_sim import _smart_sim_run_date_local


def _fake_worker_run(job: dict) -> dict:
    return {"status": "wrote", "home": job.get("home_tri"), "away": job.get("away_tri")}


class SmartSimRunDateLocalOnlyMatchupsTests(unittest.TestCase):
    def _seed_predictions(self, processed_root: Path, date_str: str) -> None:
        processed_root.mkdir(parents=True, exist_ok=True)
        (processed_root / f"predictions_{date_str}.csv").write_text(
            "home_team,visitor_team,totals,spread_margin\n"
            "LVA,NYL,160,4\n"
            "SEA,CHI,158,-2\n",
            encoding="utf-8",
        )
        (processed_root / f"props_predictions_{date_str}.csv").write_text(
            "player,team\n",
            encoding="utf-8",
        )

    def _seed_adequate_artifact(self, processed_root: Path, date_str: str, home: str, away: str) -> Path:
        path = processed_root / f"smart_sim_{date_str}_{home}_{away}.json"
        path.write_text(
            json.dumps({"players": {"home": [{"player": "A"}], "away": [{"player": "B"}]}}),
            encoding="utf-8",
        )
        return path

    def test_only_matchups_force_rebuilds_targeted_game_leaves_others_adequate_untouched(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            processed_root = root / "processed"
            raw_root = root / "raw"
            date_str = "2026-07-22"
            self._seed_predictions(processed_root, date_str)
            targeted_path = self._seed_adequate_artifact(processed_root, date_str, "LVA", "NYL")
            untargeted_path = self._seed_adequate_artifact(processed_root, date_str, "SEA", "CHI")
            untargeted_original_bytes = untargeted_path.read_bytes()

            with patch(
                "syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_run_local",
                side_effect=_fake_worker_run,
            ), patch(
                "syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_init_local",
                return_value=None,
            ):
                result = _smart_sim_run_date_local(
                    processed_root=processed_root,
                    raw_root=raw_root,
                    date_str=date_str,
                    n_sims=10,
                    seed=None,
                    max_games=None,
                    overwrite=False,
                    workers=1,
                    league_code="wnba",
                    only_matchups={("LVA", "NYL")},
                )

            # Targeted game: existing adequate artifact was force-invalidated
            # (unlinked) and counted as a real rebuild, not a skip.
            self.assertEqual(result["wrote"], 1)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["scoped_matchups"], [("LVA", "NYL")])
            # Untargeted game's adequate artifact is byte-for-byte untouched.
            self.assertTrue(untargeted_path.exists())
            self.assertEqual(untargeted_path.read_bytes(), untargeted_original_bytes)

    def test_only_matchups_none_leaves_default_skip_if_adequate_behavior_unchanged(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            processed_root = root / "processed"
            raw_root = root / "raw"
            date_str = "2026-07-22"
            self._seed_predictions(processed_root, date_str)
            targeted_path = self._seed_adequate_artifact(processed_root, date_str, "LVA", "NYL")
            other_path = self._seed_adequate_artifact(processed_root, date_str, "SEA", "CHI")
            original_bytes = targeted_path.read_bytes()
            other_original_bytes = other_path.read_bytes()

            with patch(
                "syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_run_local",
                side_effect=_fake_worker_run,
            ), patch(
                "syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_init_local",
                return_value=None,
            ):
                result = _smart_sim_run_date_local(
                    processed_root=processed_root,
                    raw_root=raw_root,
                    date_str=date_str,
                    n_sims=10,
                    seed=None,
                    max_games=None,
                    overwrite=False,
                    workers=1,
                    league_code="wnba",
                    only_matchups=None,
                )

            self.assertEqual(result["wrote"], 0)
            self.assertEqual(result["skipped"], 2)
            self.assertIsNone(result["scoped_matchups"])
            self.assertTrue(targeted_path.exists())
            self.assertEqual(targeted_path.read_bytes(), original_bytes)
            self.assertTrue(other_path.exists())
            self.assertEqual(other_path.read_bytes(), other_original_bytes)

    def test_only_matchups_fails_open_for_untargeted_game_with_inadequate_artifact(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            processed_root = root / "processed"
            raw_root = root / "raw"
            date_str = "2026-07-22"
            self._seed_predictions(processed_root, date_str)
            self._seed_adequate_artifact(processed_root, date_str, "LVA", "NYL")
            # Untargeted game's artifact has no player data -- inadequate,
            # must still be simmed even though it isn't in only_matchups.
            inadequate_path = processed_root / f"smart_sim_{date_str}_SEA_CHI.json"
            inadequate_path.write_text(json.dumps({"players": {"home": [], "away": []}}), encoding="utf-8")

            with patch(
                "syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_run_local",
                side_effect=_fake_worker_run,
            ), patch(
                "syndicate.features.shared.basketball_props_smart_sim._smart_sim_worker_init_local",
                return_value=None,
            ):
                result = _smart_sim_run_date_local(
                    processed_root=processed_root,
                    raw_root=raw_root,
                    date_str=date_str,
                    n_sims=10,
                    seed=None,
                    max_games=None,
                    overwrite=False,
                    workers=1,
                    league_code="wnba",
                    only_matchups={("LVA", "NYL")},
                )

            # LVA-NYL forced (targeted), SEA-CHI simmed anyway (inadequate,
            # fails open) -- both counted as writes, nothing skipped.
            self.assertEqual(result["wrote"], 2)
            self.assertEqual(result["skipped"], 0)


if __name__ == "__main__":
    unittest.main()
