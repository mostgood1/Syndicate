"""The lens snapshot read that the live-gameline join actually depends on.

WHY IT EXISTS. Measured 2026-08-21 with three WNBA games live: the board said
`live_gamelines.index_size: 1` with 165 rows withheld `no_live_gameline_projection`,
while `/wnba/api/live-lens` showed all three games carrying a `live_projection`
lane. Both cannot describe the same bytes, and NEITHER reads the file the join
reads -- the snapshot is keyvalue-routed (so `/api/ops/artifacts/export`, a disk
read, returns empty) and the live-lens API may rebuild from a published artifact
rather than return the stored snapshot.

Four hypotheses were eliminated by measuring things ADJACENT to that file (the
pull, the loop, the headroom gate, the builder). This endpoint reads the file
itself, through the same keyvalue-aware reader the join uses, and reports the
join's verdict per game.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch


def _snapshot():
    return {
        "date": "2026-08-20",
        "generated_at": "2026-08-21T02:19:08Z",
        "games": [
            {
                "away_name": "Indiana Fever", "home_name": "Dallas Wings", "gamePk": "g1",
                "away": {"name": "Indiana Fever"}, "home": {"name": "Dallas Wings"},
                "gameLens": [{
                    "source": "live_projection", "key": "live", "modelHomeWinProb": 0.91,
                    "projection": {"homeMargin": 6.0, "total": 160.0},
                    "markets": {"spread": {"homeLine": 3.5, "p_win": 0.7, "selection": "home"}},
                }],
            },
            {
                # The production symptom: a live game whose lane fell back to
                # `pregame` because the snapshot's cards context carried no live
                # status. It is NOT indexed, and the reason must be visible.
                "away_name": "Atlanta Dream", "home_name": "Los Angeles Sparks", "gamePk": "g2",
                "gameLens": [{"source": "pregame", "key": "live", "modelHomeWinProb": 0.27}],
            },
        ],
    }


class LiveLensSnapshotIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev = os.environ.get("ADMIN_TOKEN")
        os.environ["ADMIN_TOKEN"] = "t0ken"
        from syndicate.app import app

        self.client = app.test_client()

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("ADMIN_TOKEN", None)
        else:
            os.environ["ADMIN_TOKEN"] = self._prev

    def _get(self, snapshot):
        with patch(
            "syndicate.features.shared.refresh_state_store.read_json_file",
            return_value=snapshot,
        ):
            return self.client.get(
                "/api/ops/live-lens/snapshot-index?sport=wnba",
                headers={"X-Admin-Token": "t0ken"},
            )

    def test_reports_the_joins_verdict_per_game(self) -> None:
        payload = self._get(_snapshot()).get_json()
        self.assertEqual(payload["snapshot_game_count"], 2)
        self.assertEqual(payload["index_size"], 1)
        by_team = {g["away_name"]: g for g in payload["games"]}
        self.assertTrue(by_team["Indiana Fever"]["join_accepts"])
        self.assertFalse(by_team["Atlanta Dream"]["join_accepts"])

    def test_names_WHY_a_game_was_rejected(self) -> None:
        """A count of 1 is useless without the reason. The lane's source and
        whether it was accepted must both be readable."""
        payload = self._get(_snapshot()).get_json()
        rejected = next(g for g in payload["games"] if g["away_name"] == "Atlanta Dream")
        lane = rejected["lanes"][0]
        self.assertEqual(lane["source"], "pregame")
        self.assertFalse(lane["accepted_source"])
        self.assertEqual(payload["accepted_lens_sources"], ["live_projection"])

    def test_key_candidates_expose_a_failed_join_key(self) -> None:
        """The other way a game vanishes is an unbuildable (away, home) key."""
        snap = _snapshot()
        snap["games"][0].pop("away_name")
        snap["games"][0].pop("away")
        payload = self._get(snap).get_json()
        game = next(g for g in payload["games"] if g["home_name"] == "Dallas Wings")
        self.assertFalse(any(c["usable"] for c in game["key_candidates"]))
        self.assertEqual(payload["index_size"], 0)

    def test_absent_snapshot_is_its_own_answer(self) -> None:
        """'No snapshot' must not read as 'no games' -- different defect."""
        payload = self._get(None).get_json()
        self.assertFalse(payload["snapshot_present"])
        self.assertEqual(payload["reason"], "no_snapshot_at_path")

    def test_requires_the_admin_token(self) -> None:
        with patch(
            "syndicate.features.shared.refresh_state_store.read_json_file",
            return_value=_snapshot(),
        ):
            unauth = self.client.get("/api/ops/live-lens/snapshot-index?sport=wnba")
        self.assertNotEqual(unauth.status_code, 200)


if __name__ == "__main__":
    unittest.main()
