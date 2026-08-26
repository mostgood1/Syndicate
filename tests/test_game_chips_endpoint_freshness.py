"""`#564` -- the compact scoreboard must update every 60 s again.

THE REGRESSION, reported by the user: "the compact cards used to be updated
every 60s". They did. Before `#545` the endpoint called `build_game_chips`
inline, and that call holds a 30-second TTL cache, so the page's 60-second poll
always got a scoreboard at most 30 seconds old. `#545` replaced it with an
unconditional read of the worker's artifact, which is written once per
`build_layer2_shortlist`.

MEASURED 2026-08-25 in a window with NO DEPLOYS (22:36:13Z -> 23:48:19Z),
consecutive `GAME_CHIPS_PUBLISHED` gaps were 4m58s, 3m23s, 5m19s, 18m55s, 7m20s,
5m02s, 3m30s. A 60-second scoreboard became a ~5-minute one on a quiet evening.

AND `#545` NEVER REMOVED THE FAN-OUT IT WAS WRITTEN FOR: web still builds chips
inline several times a minute for the L2-A live restate. The cost moved nowhere;
only the benefit did.

These tests pin the DIRECTION. Making the artifact unconditionally authoritative
again (`#545`'s behaviour) turns `test_a_stale_artifact_is_rebuilt_inline` red,
which is the `off != on` property.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from syndicate.blueprints import intelligence as bp


def _stamp(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _artifact(seconds_ago, sports=("mlb",)):
    return {
        "written_at": _stamp(seconds_ago),
        "chips": [{"sport": s, "game_key": f"artifact-{s}"} for s in sports],
    }


class ChipEndpointFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.app = bp.intelligence_bp
        from flask import Flask

        self.flask = Flask(__name__)
        self.flask.register_blueprint(self.app)
        self.client = self.flask.test_client()

    def _get(self, artifact, *, inline=None, inline_raises=False, env=None):
        built = {"called": False}

        def fake_build(selected_date, sports):
            built["called"] = True
            if inline_raises:
                raise RuntimeError("provider exploded")
            return list(inline if inline is not None else [{"sport": "mlb", "game_key": "inline"}])

        with patch.object(bp, "read_game_chips", create=True, return_value=artifact), \
             patch("pipeline.intelligence_state.read_game_chips", return_value=artifact), \
             patch.object(bp, "build_game_chips", side_effect=fake_build), \
             patch.dict(os.environ, env or {}):
            resp = self.client.get("/api/board/game-chips?date=2026-08-25&sports=mlb")
        return resp.get_json(), built["called"]

    def test_a_fresh_artifact_is_served_without_building(self):
        # The worker keeping up must still be authoritative -- that is `#545`'s
        # goal and this fix does not abandon it.
        body, built = self._get(_artifact(30))
        self.assertEqual(body["source"], "worker_artifact")
        self.assertFalse(built, "a fresh artifact must not trigger a rebuild")
        self.assertEqual(body["chips"][0]["game_key"], "artifact-mlb")

    def test_a_stale_artifact_is_rebuilt_inline(self):
        # THE REGRESSION GUARD. 5 minutes is the MEDIAN publish gap measured on a
        # no-deploy evening, so this is the ordinary case, not an edge case.
        body, built = self._get(_artifact(300))
        self.assertEqual(body["source"], "inline_artifact_stale")
        self.assertTrue(built, "a stale artifact must be rebuilt, not served")
        self.assertEqual(body["chips"][0]["game_key"], "inline")

    def test_the_boundary_is_the_two_poll_allowance(self):
        self.assertFalse(self._get(_artifact(110))[1], "110s is inside 120s")
        self.assertTrue(self._get(_artifact(130))[1], "130s is outside 120s")

    def test_a_missing_artifact_still_builds_inline(self):
        body, built = self._get(None)
        self.assertEqual(body["source"], "inline_artifact_missing")
        self.assertTrue(built)

    def test_an_undateable_artifact_counts_as_stale(self):
        # An unreadable stamp is not evidence of freshness. The pessimistic
        # branch here is cheap and always correct, just slower.
        body, built = self._get({"chips": [{"sport": "mlb"}]})
        self.assertEqual(body["source"], "inline_artifact_stale")
        self.assertTrue(built)

    def test_a_stale_artifact_beats_a_FAILED_inline_build(self):
        # Before this, a failed inline build returned [] and blanked every
        # sport's strip. Degraded beats empty, and `source` says which happened.
        body, _built = self._get(_artifact(600), inline_raises=True)
        self.assertEqual(body["source"], "stale_artifact_after_inline_failure")
        self.assertEqual(body["chips"][0]["game_key"], "artifact-mlb")

    def test_with_no_artifact_and_a_failed_build_it_says_unavailable(self):
        body, _built = self._get(None, inline_raises=True)
        self.assertEqual(body["source"], "unavailable")
        self.assertEqual(body["chips"], [])

    def test_the_artifact_age_is_reported_even_when_serving_inline(self):
        # So a reader can see how far behind the worker is without diffing two
        # payloads -- the same reason `chip_count` is stamped on the artifact.
        body, _ = self._get(_artifact(300))
        self.assertIsNotNone(body["artifact_age_seconds"])
        self.assertGreater(body["artifact_age_seconds"], 120)
        self.assertEqual(body["artifact_max_age_seconds"], 120.0)

    def test_published_at_is_always_the_artifacts_stamp(self):
        # The page keys its staleness badge on `source == "worker_artifact"`, so
        # an inline serve must show no badge -- the scoreboard IS fresh.
        body, _ = self._get(_artifact(300))
        self.assertTrue(body["published_at"])
        self.assertNotEqual(body["source"], "worker_artifact")

    def test_the_threshold_is_configurable(self):
        # Setting it very high restores `#545`'s always-read-the-artifact
        # behaviour exactly, which is the documented way to back this out
        # without a deploy.
        _body, built = self._get(_artifact(3000), env={"SYNDICATE_GAME_CHIP_ARTIFACT_MAX_AGE_SECONDS": "99999"})
        self.assertFalse(built)

    def test_a_malformed_threshold_falls_back_rather_than_raising(self):
        _body, built = self._get(_artifact(30), env={"SYNDICATE_GAME_CHIP_ARTIFACT_MAX_AGE_SECONDS": "banana"})
        self.assertFalse(built)


if __name__ == "__main__":
    unittest.main()
