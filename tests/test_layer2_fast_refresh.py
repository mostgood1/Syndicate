"""The Layer 2 shortlist must not be refused by the Layer 1 pool's memory floor.

WHY THESE TESTS EXIST. Measured on refresh-worker 2026-08-14, 11:39-14:39Z:
146 `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` against 5 completed
board builds -- 96.7% of board cycles refused before any work -- and a
104.7-minute stretch (12:44:20 -> 14:29:00Z) in which the Layer 2 shortlist was
never rebuilt, so the board kept serving rows for games that had already
started. That guard is sized for `build_intelligence_overview`, a stage the
shortlist does not run.

Its own file lives apart from `tests/test_intelligence_state.py` on purpose:
that file costs ~15 minutes (measured, `.syndicate/state.md`), and a guard whose
whole subject is refusal rate needs a check that can be run on every change.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pipeline.intelligence_state as intelligence_state_module
from pipeline.intelligence_state import IntelligenceStateService


def _headroom(*, sufficient: bool) -> dict:
    return {"sufficient": sufficient, "basis": "unreclaimable", "anon_mb": 2400.0}


class Layer2FastRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IntelligenceStateService()
        self.written: list[tuple[str, dict]] = []
        self.shortlists_built: list[tuple[str, list]] = []

    def _build_layer2(self, selected_date, sport_slugs):
        self.shortlists_built.append((selected_date, list(sport_slugs)))
        return {"rows": [{"id": "r1"}, {"id": "r2"}], "opportunities_considered": 1234}

    def _patched(self, *, layer2_floor_clear: bool):
        """Everything the fast path touches, stubbed at ITS import site.

        `build_layer2_shortlist` and `pull_hot_artifacts` are imported inside
        the method, so they are patched on their defining modules, not on
        `intelligence_state`. Getting this wrong is how a test passes while
        exercising nothing -- the ledger records exactly that failure.
        """

        def _snapshot(min_required_bytes: int):
            layer2_floor = intelligence_state_module._LAYER2_MIN_SAFE_HEADROOM_BYTES
            if min_required_bytes == layer2_floor:
                return _headroom(sufficient=layer2_floor_clear)
            # The Layer 1 / overview floor: always refusing, which is the
            # production condition these tests are about.
            return _headroom(sufficient=False)

        return [
            patch(
                "syndicate.features.shared.memory_observability.memory_headroom_snapshot",
                side_effect=_snapshot,
            ),
            patch("pipeline.layer2_shortlist.build_layer2_shortlist", side_effect=self._build_layer2),
            patch("syndicate.features.shared.artifact_publisher.pull_hot_artifacts", return_value=None),
            patch.object(
                IntelligenceStateService,
                "_available_sport_manifests",
                return_value={"mlb": {}, "wnba": {}},
            ),
            patch.object(
                intelligence_state_module,
                "write_layer2_shortlist",
                side_effect=lambda date, payload: self.written.append((date, payload)),
            ),
        ]

    def _run(self, *, layer2_floor_clear: bool = True):
        patches = self._patched(layer2_floor_clear=layer2_floor_clear)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return self.service._refresh_layer2_shortlist_only("2026-08-14")

    # -- the point of the change -------------------------------------------

    def test_shortlist_rebuilds_while_the_layer1_floor_is_refusing(self) -> None:
        result = self._run()
        self.assertIsNotNone(result, "fast path did not run while only the Layer 1 floor was crossed")
        self.assertEqual(len(self.written), 1)
        self.assertEqual(self.written[0][0], "2026-08-14")
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(self.shortlists_built, [("2026-08-14", ["mlb", "wnba"])])

    def test_fast_path_never_hydrates_an_overview(self) -> None:
        """Falsification: if this just relocates the expensive stage, it is not a fix.

        `_available_sport_manifests` is stubbed here, and it is the ONLY
        overview call on this path -- and it passes `skip_game_hydration=True`
        (~2s, a few MB) rather than the hydrated pass the guard protects.
        Asserting the hydrated call count is zero is what separates "cheap
        because scoped" from "cheap because mocked".
        """
        with patch.object(intelligence_state_module, "build_intelligence_overview") as overview:
            self._run()
        self.assertEqual(
            overview.call_count,
            0,
            "the fast path reached build_intelligence_overview outside the manifest lookup",
        )

    # -- its own guard, and the two failure modes staying distinguishable ---

    def test_its_own_floor_still_refuses(self) -> None:
        result = self._run(layer2_floor_clear=False)
        self.assertIsNone(result)
        self.assertEqual(self.written, [], "shortlist was written despite its own floor being crossed")

    def test_rate_limited_second_call_does_not_rebuild(self) -> None:
        self._run()
        self.assertEqual(len(self.written), 1)
        second = self.service._refresh_layer2_shortlist_only("2026-08-14")
        self.assertIsNone(second)
        self.assertEqual(len(self.written), 1, "rate limit did not hold within the interval")

    def test_layer2_refusal_does_not_emit_the_counted_MEMORY_GUARD_ABORT_token(self) -> None:
        """Cross-lane contract, not cosmetics.

        `#417`'s verification criterion is a bare count of `MEMORY_GUARD_ABORT`
        on refresh-worker ("aborts ~0 with the board still building = the fix
        holds"), and it was still open and unowned when this guard was added.
        A second guard emitting the same token under a different floor would
        have inflated that count and read as their fix failing worse.
        `scripts/diagnose_sim_pipeline.py` and
        `scripts/diagnose_betting_pipeline.py` match it the same way.
        """
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = self._run(layer2_floor_clear=False)
        emitted = buffer.getvalue()

        self.assertIsNone(result)
        # Positive control first: prove the guard actually spoke, so the
        # assertion below is a measured absence rather than a silent one.
        self.assertIn("LAYER2_GUARD_SKIP", emitted, "the Layer 2 guard emitted nothing at all")
        self.assertNotIn(
            "MEMORY_GUARD_ABORT",
            emitted,
            "the Layer 2 guard emitted the token #417's open verification counts",
        )

    def test_layer1_guard_still_emits_its_own_token(self) -> None:
        """The other half: narrowing the new guard must not have renamed the old
        one. Both directions in the same pass -- a guard fixed in one direction
        is where the other direction survives."""
        import io
        from contextlib import redirect_stdout

        with patch(
            "syndicate.features.shared.memory_observability.memory_headroom_snapshot",
            return_value=_headroom(sufficient=False),
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                refused = intelligence_state_module._abort_build_candidate_pool_if_memory_critical(
                    "pre_source_state_fingerprint"
                )
        emitted = buffer.getvalue()

        self.assertTrue(refused)
        self.assertIn("MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint", emitted)
        self.assertIn("floor_mb=1900", emitted)

    def test_refused_inside_a_hosted_web_request(self) -> None:
        """`_compute_board_publication_response` has two callers and one of them
        serves live web requests. Web is a 2GB container with an OOM history."""
        from flask import Flask

        app = Flask(__name__)
        with patch.dict("os.environ", {"RENDER": "true"}):
            with app.test_request_context("/"):
                result = self._run()
        self.assertIsNone(result)
        self.assertEqual(self.written, [], "the fast path computed inside a hosted web request")

    def test_disabled_by_env_flag(self) -> None:
        with patch.dict("os.environ", {"SYNDICATE_LAYER2_FAST_REFRESH_ENABLED": "false"}):
            result = self._run()
        self.assertIsNone(result)
        self.assertEqual(self.written, [])

    # -- the regression this change must never become -----------------------

    def test_neither_existing_memory_floor_moved(self) -> None:
        """`handoff_overview_hydration.md` do-not #1, pinned.

        A session measured the overview stage at 127MB on a mirror with no MLB
        games and nearly shipped a reduction of the 3000MB floor; that is the
        change that would restore the OOM loop. This change adds a THIRD,
        smaller floor in front of a different stage and must leave both
        existing ones exactly where they were.
        """
        from syndicate.features.intelligence import _OVERVIEW_MIN_SAFE_HEADROOM_BYTES

        self.assertEqual(_OVERVIEW_MIN_SAFE_HEADROOM_BYTES, 3000 * 1024 * 1024)
        self.assertEqual(
            intelligence_state_module._MIN_SAFE_MEMORY_HEADROOM_BYTES, 1900 * 1024 * 1024
        )
        self.assertLess(
            intelligence_state_module._LAYER2_MIN_SAFE_HEADROOM_BYTES,
            intelligence_state_module._MIN_SAFE_MEMORY_HEADROOM_BYTES,
            "the Layer 2 floor is only meaningful if it is cheaper than the one it bypasses",
        )


if __name__ == "__main__":
    unittest.main()
