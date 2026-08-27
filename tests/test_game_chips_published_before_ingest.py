"""`#563` -- the scoreboard artifact must be written BEFORE the slate is ingested.

WHY THIS FILE EXISTS. `write_game_chips` used to be called at the BOTTOM of
`build_layer2_shortlist`, beside the chip-join telemetry that genuinely needs
`cards`. Measured on production 2026-08-25/26 that put the only write of the
artifact the WEB serves ~21 minutes after boot: instance `-fzb6v` booted
00:45:38Z and printed its first `GAME_CHIPS_PUBLISHED` at 01:06:19Z.

Over the same evening refresh-worker took 15 deploys and logged 15 SIGTERM
shutdowns with a MEDIAN UPTIME OF 1202 s (20.0 min), five of them under eight
minutes. So the median instance died within a minute of its first publish and
five published nothing at all -- the user-visible result being a compact
scoreboard frozen for ~20 minutes at a time.

The chips depend on NONE of the work that follows them: they are built from the
per-sport provider payloads, not from the grid, the candidates or the cards. So
those 21 minutes bought nothing, and this test is what stops them coming back.

ORDERING IS THE ASSERTION, not merely "was it called". A test that only checked
the call would pass with the publish back at the bottom, which is precisely the
bug.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import layer2_shortlist


class ChipPublishOrderingTests(unittest.TestCase):
    def _run(self, *, chips=None, chip_error=None, publish_error=None):
        """Drive `build_layer2_shortlist` far enough to observe the publish.

        The sport loop is left to fail on its own (no artifacts in the test
        environment): the function never raises by contract, and what is under
        test is what happens BEFORE that loop.
        """
        trace: list[str] = []

        def fake_build_game_chips(selected_date, sports):
            trace.append("build_chips")
            if chip_error is not None:
                raise chip_error
            return list(chips if chips is not None else [{"sport": "mlb", "game_key": "1"}])

        def fake_write_game_chips(selected_date, payload):
            trace.append("write_chips")
            if publish_error is not None:
                raise publish_error
            return {"chip_count": len(payload or [])}

        def fake_load_openings(selected_date):
            trace.append("load_openings")
            return []

        def fake_select_shortlist(*args, **kwargs):
            trace.append("select_shortlist")
            raise RuntimeError("no slate in the test environment")

        with patch(
            "syndicate.features.shared.game_chip_scoreboard.build_game_chips",
            side_effect=fake_build_game_chips,
        ), patch(
            "pipeline.intelligence_state.write_game_chips",
            side_effect=fake_write_game_chips,
        ), patch(
            "syndicate.features.shared.clv_opening_ledger.load_openings",
            side_effect=fake_load_openings,
        ), patch(
            "syndicate.features.shared.layer2_board.select_shortlist",
            side_effect=fake_select_shortlist,
        ):
            out = layer2_shortlist.build_layer2_shortlist("2026-08-25", ["mlb"])
        return out, trace

    def test_chips_are_published_before_any_sport_is_ingested(self):
        _out, trace = self._run()
        self.assertIn("write_chips", trace, "the scoreboard artifact was never written")
        # `load_openings` is the first real work in the function and it runs
        # before the sport loop, so it is the honest fence to measure against.
        self.assertLess(
            trace.index("write_chips"),
            trace.index("select_shortlist") if "select_shortlist" in trace else len(trace),
            "chips must be published before the slate is ingested",
        )

    def test_build_precedes_write(self):
        _out, trace = self._run()
        self.assertLess(trace.index("build_chips"), trace.index("write_chips"))

    def test_the_publish_is_attempted_exactly_once_per_build(self):
        # It used to be built at the bottom and published there. If both sites
        # ever exist again this catches it: `build_game_chips` holds a 30s TTL
        # cache and the two sites are ~20 minutes apart, so a second publish
        # would overwrite the served artifact with a DIFFERENT set of chips
        # from the ones measured by the coverage line.
        #
        # ASSERTED ON THE WRITE, NOT THE BUILD, and the first draft of this test
        # got that wrong -- it asserted one build and measured two. The second
        # is `attach_game_state` (board_enrichment.py), a legitimate and
        # unrelated consumer of the same builder inside the sport loop. Counting
        # builds would therefore fail on correct code and, worse, would go green
        # again if somebody deleted the wrong one. The publish is the thing that
        # must be unique, because the publish is what web reads.
        _out, trace = self._run()
        self.assertEqual(trace.count("write_chips"), 1)

    def test_a_chip_build_failure_never_takes_the_board_down(self):
        out, trace = self._run(chip_error=RuntimeError("provider exploded"))
        self.assertNotIn("write_chips", trace)
        self.assertIsInstance(out, dict)

    def test_a_publish_failure_never_takes_the_board_down(self):
        out, trace = self._run(publish_error=RuntimeError("keyvalue refused"))
        self.assertIn("write_chips", trace)
        self.assertIsInstance(out, dict)

    def test_chips_are_built_for_the_full_default_sport_list(self):
        # `#545`: scoping to the board's sports would mean a sport with no rows
        # today loses its scoreboard strip entirely, and a chip-less strip is
        # indistinguishable from a sport with no games.
        from syndicate.features.shared.game_chip_scoreboard import GAME_CHIP_DEFAULT_SPORTS

        seen: list[list[str]] = []

        def capture(selected_date, sports):
            seen.append(list(sports))
            return []

        with patch(
            "syndicate.features.shared.game_chip_scoreboard.build_game_chips",
            side_effect=capture,
        ), patch(
            "pipeline.intelligence_state.write_game_chips", return_value={}
        ), patch(
            "syndicate.features.shared.clv_opening_ledger.load_openings", return_value=[]
        ):
            layer2_shortlist.build_layer2_shortlist("2026-08-25", ["mlb"])

        self.assertTrue(seen, "build_game_chips was never called")
        self.assertEqual(sorted(seen[0]), sorted(set(GAME_CHIP_DEFAULT_SPORTS)))

    def test_sport_slugs_is_not_consumed_by_the_chip_build(self):
        # `sport_slugs` is an Iterable and is consumed by the loop below. If the
        # chip block ever drains it to widen its sport set, the board silently
        # loses every sport -- a generator can only be read once.
        observed: list[str] = []

        def fake_select_shortlist(*args, **kwargs):
            raise RuntimeError("stop here")

        def tracking_slugs():
            for slug in ("mlb", "nfl"):
                observed.append(slug)
                yield slug

        with patch(
            "syndicate.features.shared.game_chip_scoreboard.build_game_chips", return_value=[]
        ), patch(
            "pipeline.intelligence_state.write_game_chips", return_value={}
        ), patch(
            "syndicate.features.shared.clv_opening_ledger.load_openings", return_value=[]
        ), patch(
            "syndicate.features.shared.layer2_board.select_shortlist",
            side_effect=fake_select_shortlist,
        ):
            layer2_shortlist.build_layer2_shortlist("2026-08-25", tracking_slugs())

        self.assertEqual(observed, ["mlb", "nfl"], "the sport list reached the ingest loop intact")


if __name__ == "__main__":
    unittest.main()
