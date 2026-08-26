"""`#563` -- the board must be able to REPORT that it is stale.

WHY THIS FILE EXISTS. `read_combined_intelligence_response` hard-coded
`state_meta = {"age_seconds": 0.0, "is_fresh": True}` on a function whose own
docstring says it "NEVER calls _build_candidate_pool ... It only reads what ...
has already built". So the age was of the READ, not of the data, and a board
assembled entirely from hour-old artifacts reported itself perfectly fresh --
every time, by construction.

THE COST, measured 2026-08-25/26 on production. refresh-worker took 15 deploys
in 6h15m, each SIGTERMing the build in flight; median instance uptime 1202 s
against a 21-minute boot-to-first-publish. The artifacts under this board went
20-54 minutes without moving and the board rendered them as current throughout.
The only thing that noticed was a person watching the odds-refresh timestamps
stop changing.

These tests pin the DIRECTION, not just the plumbing: restoring the literal
`0.0`/`True` turns `test_stale_shortlist_is_reported_stale` red, which is the
reachability property `model_engine_standard.md` requires of anything that
could otherwise be inert.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import intelligence_state as state


def _stamp(seconds_ago: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class ReusedAgeHelperTests(unittest.TestCase):
    """The age helper is the repo's EXISTING one, not a second copy.

    The first draft of this fix added `_artifact_age_seconds` beside
    `_timestamp_age_seconds`, which already did the same job -- a parallel
    contract that could disagree with `_recomputed_freshness_block`, the pass
    that rebuilds exactly these fields on the served payload. This pins the
    reuse so it cannot drift back.
    """

    def test_there_is_exactly_one_age_helper(self):
        self.assertFalse(
            hasattr(state, "_artifact_age_seconds"),
            "a second age helper is a parallel contract -- use _timestamp_age_seconds",
        )

    def test_it_reads_the_writers_own_stamp_format(self):
        age = state._timestamp_age_seconds(_stamp(600))
        self.assertIsNotNone(age)
        self.assertAlmostEqual(age, 600, delta=5)

    def test_unreadable_stamp_is_NONE_and_never_zero(self):
        # THE PROPERTY THE FIX RESTS ON. Substituting 0.0 for "I cannot tell"
        # would reintroduce the asserted-freshness bug one layer down.
        for bad in ("", None, "not a date", "  "):
            with self.subTest(bad=bad):
                self.assertIsNone(state._timestamp_age_seconds(bad))

    def test_future_stamp_clamps_to_zero_rather_than_going_negative(self):
        ahead = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(state._timestamp_age_seconds(ahead), 0.0)


class CombinedBoardStateMetaTests(unittest.TestCase):
    """`state_meta` must be derived from the artifacts it actually read."""

    def _read(self, shortlists, dates=("2026-08-25",)):
        def fake_shortlist(selected_date):
            return shortlists.get(str(selected_date))

        state._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
        with patch.object(state, "read_layer2_shortlist", side_effect=fake_shortlist), \
             patch.object(state, "_read_single_date_response_for_combining", return_value=None), \
             patch.object(state, "board_l2a_fallback_enabled", return_value=True):
            return state.read_combined_intelligence_response(dates=list(dates))

    def test_fresh_shortlist_is_reported_fresh_with_a_real_age(self):
        out = self._read({"2026-08-25": {"written_at": _stamp(45), "cards": [{"sport": "mlb"}]}})
        meta = out["state_meta"]
        self.assertTrue(meta["is_fresh"])
        self.assertEqual(meta["freshness_status"], "fresh")
        self.assertAlmostEqual(meta["age_seconds"], 45, delta=10)
        self.assertEqual(meta["artifacts_dated"], 1)

    def test_stale_shortlist_is_reported_stale(self):
        # THE REGRESSION GUARD. This is the exact production shape: the board
        # still has rows, the read still succeeds, and the data is 40 minutes
        # old because the producer was killed mid-build. Restoring the literal
        # `"is_fresh": True` fails here and nowhere else.
        out = self._read({"2026-08-25": {"written_at": _stamp(2400), "cards": [{"sport": "mlb"}]}})
        meta = out["state_meta"]
        self.assertFalse(meta["is_fresh"])
        self.assertEqual(meta["freshness_status"], "stale")
        self.assertGreater(meta["age_seconds"], 900)

    def test_age_is_the_OLDEST_input_and_newest_is_reported_beside_it(self):
        # Two numbers, because either alone is unattributable: `age_seconds`
        # says how stale the worst row could be, `newest_age_seconds` says when
        # the board last changed AT ALL -- and it is the second that goes flat
        # when the producer dies.
        out = self._read(
            {
                "2026-08-25": {"written_at": _stamp(3000), "cards": [{"sport": "mlb"}]},
                "2026-08-26": {"written_at": _stamp(60), "cards": [{"sport": "nfl"}]},
            },
            dates=("2026-08-25", "2026-08-26"),
        )
        meta = out["state_meta"]
        self.assertAlmostEqual(meta["age_seconds"], 3000, delta=15)
        self.assertAlmostEqual(meta["newest_age_seconds"], 60, delta=15)
        self.assertEqual(meta["artifacts_dated"], 2)
        # The verdict follows the OLDEST -- a board is only as current as its
        # most stale part.
        self.assertFalse(meta["is_fresh"])

    def test_undateable_artifacts_give_is_fresh_NONE_not_False(self):
        # "We could not tell" and "we checked and it is stale" are different
        # facts and need different people. Collapsing them into False would make
        # a missing stamp indistinguishable from a measured outage.
        out = self._read({"2026-08-25": {"cards": [{"sport": "mlb"}]}})
        meta = out["state_meta"]
        self.assertIsNone(meta["is_fresh"])
        self.assertIsNone(meta["age_seconds"])
        self.assertEqual(meta["freshness_status"], "unknown")
        self.assertEqual(meta["artifacts_dated"], 0)
        # `computed_at` None is what makes `_apply_freshness_recompute` SKIP
        # this block, which is what lets the None survive to the client instead
        # of being flattened to False.
        self.assertIsNone(meta["computed_at"])

    def test_threshold_is_configurable_and_named_on_the_payload(self):
        with patch.dict(os.environ, {"SYNDICATE_INTELLIGENCE_BOARD_STALE_AFTER_SECONDS": "60"}):
            out = self._read({"2026-08-25": {"written_at": _stamp(300), "cards": [{"sport": "mlb"}]}})
        meta = out["state_meta"]
        self.assertEqual(meta["freshness_sla_seconds"], 60)
        self.assertFalse(meta["is_fresh"])


class RecomputePassIdempotenceTests(unittest.TestCase):
    """`_apply_freshness_recompute` must not be able to undo this fix.

    `#334` rebuilds `age_seconds`/`freshness_status`/`is_fresh` FROM
    `computed_at` on every served payload, exactly so a verdict computed at
    write time cannot lie at read time. The first draft of this fix put the READ
    MOMENT in `computed_at` -- so that pass would have recomputed the age as ~0
    and handed back `is_fresh: True`, silently reverting the whole change on the
    way out. `#334`'s own comment records three previous patches that missed a
    path; this is the test that stops this being the fourth.
    """

    def _meta(self, seconds_ago):
        state._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
        shortlist = {"written_at": _stamp(seconds_ago), "cards": [{"sport": "mlb"}]}
        with patch.object(state, "read_layer2_shortlist", return_value=shortlist), \
             patch.object(state, "_read_single_date_response_for_combining", return_value=None), \
             patch.object(state, "board_l2a_fallback_enabled", return_value=True):
            out = state.read_combined_intelligence_response(dates=["2026-08-25"])
        return out["state_meta"]

    def test_the_recompute_pass_reaches_the_same_verdict(self):
        meta = self._meta(2400)
        rebuilt = state._apply_freshness_recompute({"state_meta": dict(meta)})["state_meta"]
        self.assertEqual(rebuilt["freshness_status"], meta["freshness_status"])
        self.assertEqual(rebuilt["is_fresh"], meta["is_fresh"])
        self.assertAlmostEqual(rebuilt["age_seconds"], meta["age_seconds"], delta=5)

    def test_a_stale_board_survives_the_recompute_as_stale(self):
        # THE REGRESSION GUARD. Putting the read moment back in `computed_at`
        # turns this red and nothing else does.
        meta = self._meta(2400)
        rebuilt = state._apply_freshness_recompute({"state_meta": dict(meta)})["state_meta"]
        self.assertFalse(rebuilt["is_fresh"])
        self.assertGreater(rebuilt["age_seconds"], 900)

    def test_the_boards_own_sla_is_carried_not_the_30s_default(self):
        # The recompute prefers the block's own `freshness_sla_seconds`. Without
        # it this board would be judged against the 30-second intelligence
        # refresh interval and read "stale" on every normal cycle.
        meta = self._meta(120)
        self.assertEqual(meta["freshness_sla_seconds"], 900)
        rebuilt = state._apply_freshness_recompute({"state_meta": dict(meta)})["state_meta"]
        self.assertTrue(rebuilt["is_fresh"])


class Layer2FallbackVintageTests(unittest.TestCase):
    def test_vintages_are_recorded_without_a_second_read(self):
        # An OUT PARAMETER, because the shortlist measured 5,166,721 bytes on
        # 2026-08-26 and re-reading it to date it would cost more than the
        # staleness it reports.
        reads: list[str] = []

        def fake_shortlist(selected_date):
            reads.append(str(selected_date))
            return {"written_at": "2026-08-26T01:06:20Z", "cards": [{"sport": "mlb"}]}

        vintages: list[str] = []
        with patch.object(state, "read_layer2_shortlist", side_effect=fake_shortlist):
            cards = state._layer2_fallback_recommendations(["2026-08-25"], vintages=vintages)
        self.assertEqual(vintages, ["2026-08-26T01:06:20Z"])
        self.assertEqual(len(cards), 1)
        self.assertEqual(reads, ["2026-08-25"], "the artifact must be read exactly once")

    def test_the_out_parameter_is_optional_so_existing_callers_are_untouched(self):
        with patch.object(state, "read_layer2_shortlist", return_value={"cards": [{"sport": "mlb"}]}):
            self.assertEqual(len(state._layer2_fallback_recommendations(["2026-08-25"])), 1)


if __name__ == "__main__":
    unittest.main()
