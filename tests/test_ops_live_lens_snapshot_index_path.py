"""`/api/ops/live-lens/snapshot-index` must read the file the JOIN reads.

The game-line join resolves its snapshot through
`board_enrichment._LIVE_GAMELINE_SNAPSHOT_PATHS`: for `nfl` that is the live
re-sim, `nfl_live_resim.json`, not the pregame-carried `nfl_live_lens.json` the
live-lens page reads. The endpoint hard-coded `<sport>_live_lens.json`, so for
NFL the diagnostic built to show "what the join ACTUALLY sees" read a different
file from the join -- the same wrong-call-site class as `3887fdd6`.

The prop join still reads `<sport>_live_lens.json`, so `prop_index` must keep
reading that file; both paths are reported.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch


def _snap(source: str) -> dict:
    return {
        "date": "2026-09-28",
        "games": [{
            "away_name": "Chicago Bears", "home_name": "Green Bay Packers", "gamePk": "n1",
            "gameLens": [{"source": source, "key": "live", "modelHomeWinProb": 0.6}],
        }],
    }


class SnapshotIndexReadsTheJoinsFile(unittest.TestCase):
    def setUp(self) -> None:
        self._prev = os.environ.get("ADMIN_TOKEN")
        os.environ["ADMIN_TOKEN"] = "t0ken"
        from syndicate.app import app

        self.client = app.test_client()
        self.reads: list[str] = []

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("ADMIN_TOKEN", None)
        else:
            os.environ["ADMIN_TOKEN"] = self._prev

    def _get(self, sport: str, files: dict[str, dict]):
        def fake_read(path, *args, **kwargs):
            name = Path(path).name
            self.reads.append(name)
            return files.get(name)

        with patch("syndicate.features.shared.refresh_state_store.read_json_file", side_effect=fake_read):
            return self.client.get(
                f"/api/ops/live-lens/snapshot-index?sport={sport}",
                headers={"X-Admin-Token": "t0ken"},
            ).get_json()

    def test_nfl_reads_the_live_resim_not_the_lens(self) -> None:
        payload = self._get("nfl", {
            "nfl_live_resim.json": _snap("live_resim"),
            "nfl_live_lens.json": _snap("pregame"),
        })
        self.assertTrue(payload["snapshot_present"])
        self.assertEqual(Path(payload["path"]).name, "nfl_live_resim.json")
        self.assertEqual(Path(payload["prop_path"]).name, "nfl_live_lens.json")
        # The game-line half describes the RE-SIM's bytes, not the lens's.
        self.assertEqual(payload["games"][0]["lanes"][0]["source"], "live_resim")
        self.assertEqual(self.reads[0], "nfl_live_resim.json")
        self.assertIn("nfl_live_lens.json", self.reads)

    def test_nfl_absent_resim_is_reported_even_when_the_lens_exists(self) -> None:
        """The old endpoint would have said `snapshot_present: True` here,
        while the join read nothing."""
        payload = self._get("nfl", {"nfl_live_lens.json": _snap("pregame")})
        self.assertFalse(payload["snapshot_present"])
        self.assertEqual(Path(payload["path"]).name, "nfl_live_resim.json")

    def test_the_map_is_the_one_the_join_uses(self) -> None:
        from syndicate.features.shared.board_enrichment import _LIVE_GAMELINE_SNAPSHOT_PATHS

        with patch.dict(_LIVE_GAMELINE_SNAPSHOT_PATHS, {"wnba": "wnba_probe.json"}):
            payload = self._get("wnba", {"wnba_probe.json": _snap("live_projection")})
        self.assertEqual(Path(payload["path"]).name, "wnba_probe.json")

    def test_other_sports_read_one_file(self) -> None:
        payload = self._get("wnba", {"wnba_live_lens.json": _snap("live_projection")})
        self.assertEqual(Path(payload["path"]).name, "wnba_live_lens.json")
        self.assertEqual(payload["path"], payload["prop_path"])
        self.assertEqual(self.reads, ["wnba_live_lens.json"])


if __name__ == "__main__":
    unittest.main()
