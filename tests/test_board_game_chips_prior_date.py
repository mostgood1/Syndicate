"""After midnight CT, the Games rail's Today tab keeps a game from the evening before that is STILL LIVE.

THE GAP, measured by the rail monitor (findings 2026-11-26, R-L): at the midnight CT roll the Today rail moves to
the new date and a game still in play loses its card. 11-26: Baylor @ Gonzaga (tip 04:53Z) and Texas Tech @
Oregon (04:57Z) had 15 rows each at 11:43 PM CST and no card from 12:03 AM. The 12:43 AM reading held, for both:
0 chips in `/api/board/game-chips` (date 11-27), 0 board rows, 0 live-rail rows. The prior-date carryover kept
11-26 alive (11-26 chips republished every ~6.5 min to 07:03Z), so the scoreboard existed; only the Today feed
did not carry it.

`/api/board/game-chips?carry_prior_live=1` now adds the prior date's LIVE chips from that date's published
artifact. These tests pin each bound, and that the endpoint is unchanged without the opt-in (`off != on`).
"""

from __future__ import annotations

import functools
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from syndicate.blueprints import intelligence as bp

TODAY = "2026-11-27"
PRIOR = "2026-11-26"
# 12:43 AM CST 11-27, the reading at which both games were live and had no card.
NOW = datetime(2026, 11, 27, 6, 43, tzinfo=timezone.utc)


def _stamp(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _chip(key, start, state, sport="ncaab"):
    return {"sport": sport, "game_key": key, "matchup": f"{key} away @ {key} home", "state": state, "start_time_utc": start}


GONZAGA = _chip("bay-gonz", "2026-11-27T04:53:00Z", "live")          # Central 11-26 10:53 PM
OREGON = _chip("ttu-ore", "2026-11-27T04:57:00Z", "live")            # Central 11-26 10:57 PM
ENDED = _chip("ended", "2026-11-27T01:00:00Z", "final")              # 11-26, already final
TODAYS = _chip("todays", "2026-11-27T18:00:00Z", "live")             # Central 11-27: today's own game
OLDER = _chip("older", "2026-11-25T20:00:00Z", "live", sport="soccer")  # 11-25: not the prior date
OTHER_SPORT = _chip("nhl-late", "2026-11-27T04:00:00Z", "live", sport="nhl")


def _prior_artifact(seconds_ago=60, chips=None):
    return {"written_at": _stamp(seconds_ago), "chips": list(chips if chips is not None else [GONZAGA, OREGON, ENDED, TODAYS, OLDER, OTHER_SPORT])}


def _run(artifact, *, today_chips=(), sports=("ncaab", "soccer"), selected=TODAY, now=NOW, env=None):
    by_date = {PRIOR: artifact}
    with patch("pipeline.intelligence_state.read_game_chips", side_effect=lambda d: by_date.get(d)), \
         patch.dict(os.environ, env or {}):
        return bp._prior_date_live_chips(selected, list(sports), list(today_chips), today=TODAY, now=now)


class PriorDateLiveChipTests(unittest.TestCase):
    def test_the_11_26_late_games_are_carried_onto_today(self):
        carried, report = _run(_prior_artifact())
        self.assertEqual(report["reason"], "ok")
        self.assertEqual([c["game_key"] for c in carried], ["bay-gonz", "ttu-ore"])
        for chip in carried:
            self.assertEqual(chip["carried_from_date"], PRIOR)
            self.assertEqual(chip["carried_onto"], TODAY)
        self.assertEqual(report["added"], 2)
        # A COPY: the artifact's own chip is not tagged.
        self.assertNotIn("carried_onto", GONZAGA)

    def test_only_live_prior_dated_chips_of_the_wanted_sports(self):
        carried, _ = _run(_prior_artifact())
        keys = {c["game_key"] for c in carried}
        self.assertNotIn("ended", keys, "a final game is not carried")
        self.assertNotIn("todays", keys, "a chip dated today is today's own business")
        self.assertNotIn("older", keys, "a chip two days old is not the prior date's")
        self.assertNotIn("nhl-late", keys, "a sport the request did not ask for")

    def test_a_game_today_already_lists_is_not_added_twice(self):
        carried, _ = _run(_prior_artifact(), today_chips=[dict(GONZAGA)])
        self.assertEqual([c["game_key"] for c in carried], ["ttu-ore"])

    def test_not_today(self):
        carried, report = _run(_prior_artifact(), selected="2026-11-28")
        self.assertEqual((carried, report["reason"]), ([], "not_today"))

    def test_outside_the_carryover_window(self):
        # 7:00 AM CST, past the 6 h default: the carryover itself has stopped by then.
        carried, report = _run(_prior_artifact(), now=datetime(2026, 11, 27, 13, 0, tzinfo=timezone.utc))
        self.assertEqual((carried, report["reason"]), ([], "outside_window"))
        carried, report = _run(_prior_artifact(), env={"SYNDICATE_LAYER2_CARRYOVER_MAX_HOURS": "0"})
        self.assertEqual((carried, report["reason"]), ([], "outside_window"))

    def test_a_stale_prior_artifact_lends_nothing(self):
        # Once nothing is live the carryover stops republishing, and its last artifact can still say `live`.
        carried, report = _run(_prior_artifact(seconds_ago=1000))
        self.assertEqual((carried, report["reason"]), ([], "artifact_stale"))
        carried, report = _run(_prior_artifact(seconds_ago=1000), env={"SYNDICATE_RAIL_PRIOR_DATE_CHIP_MAX_AGE_SECONDS": "1200"})
        self.assertEqual(report["reason"], "ok")

    def test_no_prior_artifact(self):
        carried, report = _run(None)
        self.assertEqual((carried, report["reason"]), ([], "no_artifact"))

    def test_off_switch(self):
        carried, report = _run(_prior_artifact(), env={"SYNDICATE_RAIL_PRIOR_DATE_LIVE_CHIPS": "off"})
        self.assertEqual((carried, report["reason"]), ([], "off"))

    def test_it_never_builds_chips(self):
        with patch.object(bp, "build_game_chips", side_effect=AssertionError("must not build")):
            carried, _ = _run(_prior_artifact())
        self.assertEqual(len(carried), 2)


class GameChipsEndpointCarryTests(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        self.flask = Flask(__name__)
        self.flask.register_blueprint(bp.intelligence_bp)
        self.client = self.flask.test_client()

    def _get(self, query, env=None):
        today_artifact = {"written_at": _stamp(30), "chips": [dict(TODAYS)]}
        by_date = {TODAY: today_artifact, PRIOR: _prior_artifact()}
        pinned = functools.partial(bp._prior_date_live_chips, today=TODAY, now=NOW)
        with patch("pipeline.intelligence_state.read_game_chips", side_effect=lambda d: by_date.get(d)), \
             patch.object(bp, "_prior_date_live_chips", pinned), \
             patch.object(bp, "build_game_chips", side_effect=AssertionError("fresh artifact: no inline build")), \
             patch.dict(os.environ, env or {}):
            return self.client.get(f"/api/board/game-chips?date={TODAY}&sports=ncaab{query}").get_json()

    def test_opt_in_adds_the_prior_dates_live_games(self):
        body = self._get("&carry_prior_live=1")
        self.assertEqual([c["game_key"] for c in body["chips"]], ["todays", "bay-gonz", "ttu-ore"])
        self.assertEqual(body["prior_date_live"]["reason"], "ok")
        self.assertEqual(body["prior_date_live"]["added"], 2)

    def test_without_the_opt_in_the_response_is_unchanged(self):
        body = self._get("")
        self.assertEqual([c["game_key"] for c in body["chips"]], ["todays"])
        self.assertIsNone(body["prior_date_live"])

    def test_the_off_switch_holds_at_the_endpoint(self):
        body = self._get("&carry_prior_live=1", env={"SYNDICATE_RAIL_PRIOR_DATE_LIVE_CHIPS": "off"})
        self.assertEqual([c["game_key"] for c in body["chips"]], ["todays"])
        self.assertEqual(body["prior_date_live"]["reason"], "off")


if __name__ == "__main__":
    unittest.main()
