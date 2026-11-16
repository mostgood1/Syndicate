"""A refresh-worker deploy must not throw away an in-flight board build.

WHY THIS FILE EXISTS (lane `preflight-board-build-hold`). `deploy_preflight`
reads the PROCESS TABLE, and the board build is a THREAD inside the long-lived
`run_refresh_worker.py` process. So the preflight was blind to the most
expensive thing a deploy can destroy, and said CLEAR while a build ran.

MEASURED 2026-09-19: preflight returned CLEAR at 16:04:54Z, a deploy fired on
it, and the SIGTERM at ~16:09Z threw away a today board that had written its
shortlist at 16:05:23Z and had not published. The board was then 45 minutes
stale during a live NCAAF slate -- the complaint this whole thread started from
("Its 11:19 and last board update for today was 10:49").

The second defect is the marker: `board_build_state()` read `LAYER2_SHORTLIST`
as "build complete", but the kalshi join, `portfolio_commit`, paper execution
and the publish all run after it. The kill landed in exactly that tail, which is
why the window looked safe. Completion is `BOARD_BUILD_TIMING`.

Every test here fails on the pre-change code.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def preflight():
    return _load("test_preflight_bbh", "deploy_preflight.py")


@pytest.fixture(scope="module")
def safety():
    return _load("test_safety_bbh", "check_deploy_safety.py")


# --- the verdict ------------------------------------------------------------------


def test_a_build_in_flight_holds_refresh_worker(preflight):
    facts = {"newest_build_start": "2026-09-19T16:00:00Z", "build_age_seconds": 290, "estimated_seconds_remaining": 310}
    verdict, code, reason = preflight.board_build_verdict("refresh-worker", False, (True, facts))
    assert (verdict, code) == ("HOLD", preflight.EXIT_HOLD)
    assert "board build is in flight" in reason and "throws it away" in reason
    # The operator is told how to GET a window, not merely that they cannot have one.
    assert "BOARD_BUILD_TIMING" in reason and "--drain" in reason and "--allow-mid-build" in reason


def test_unreadable_is_unknown_not_clear(preflight):
    verdict, code, reason = preflight.board_build_verdict(
        "refresh-worker", False, (None, {"reason": "no BUILD_SPAN_ENTER in the lookback window"}))
    assert (verdict, code) == ("UNKNOWN", preflight.EXIT_UNKNOWN)
    assert "not evidence of a quiet worker" in reason
    assert "no BUILD_SPAN_ENTER in the lookback window" in reason, "the operator must see WHY it is unreadable"


def test_an_idle_worker_does_not_hold(preflight):
    assert preflight.board_build_verdict("refresh-worker", False, (False, {})) is None


def test_only_refresh_worker_is_gated(preflight):
    for service in ("web", "live-odds-worker", "model-scorecard"):
        assert preflight.board_build_verdict(service, False, (True, {"newest_build_start": "x"})) is None, service


def test_allow_mid_build_is_the_escape_hatch(preflight):
    state = (True, {"newest_build_start": "2026-09-19T16:00:00Z"})
    assert preflight.board_build_verdict("refresh-worker", False, state) is not None
    assert preflight.board_build_verdict("refresh-worker", True, state) is None, "off != on"
    # ... and it must not leave an UNKNOWN blocking either, once the operator has said why.
    assert preflight.board_build_verdict("refresh-worker", True, (None, {"reason": "x"})) is None


def test_the_reader_returns_unknown_rather_than_raising(preflight, monkeypatch):
    """Any failure reading the state must read as UNKNOWN, which blocks."""
    monkeypatch.setattr(preflight, "Path", None)  # breaks read_board_build_state's own body
    in_flight, facts = preflight.read_board_build_state()
    assert in_flight is None and facts.get("reason")


# --- the marker -------------------------------------------------------------------
#
# These tests read Render's logs API until 2026-11-15 (lane render-retirement). The
# fleet's refresh-worker log is now the only source, and the same two properties are
# pinned on it: the shortlist write is NOT completion, and an idle worker reads idle.


def test_completion_is_not_the_shortlist(safety):
    """The shortlist write is mid-build. Reading it as done is what made the
    16:04:54Z window look safe."""
    lines = [
        "[intelligence_state] BUILD_SPAN_ENTER stage=pull_hot_artifacts date=2026-09-19",
        "[intelligence] LAYER2_SHORTLIST rows=120 considered=900",
    ]
    in_flight, facts = safety._fleet_board_build_state(lines)
    assert in_flight is True, "a written shortlist must not read as a finished build"
    assert facts["newest_build_complete"] == "(none in tail)"


def test_a_completed_build_reads_idle(safety):
    lines = [
        "[intelligence_state] BUILD_SPAN_ENTER stage=pull_hot_artifacts date=2026-09-19",
        "[intelligence] LAYER2_SHORTLIST rows=120 considered=900",
        "[intelligence_state] BOARD_BUILD_TIMING wall_s=540.0 ok=True",
        "[intelligence_state] LOOP_ITERATION pending_keys=0",
    ]
    in_flight, facts = safety._fleet_board_build_state(lines)
    assert in_flight is False
    assert facts["typical_build_seconds"] == 540


def test_a_missing_render_key_no_longer_opens_the_gate(preflight, safety):
    """Until 2026-11-15 `missing_api_key` (no RENDER_API_KEY in this shell) was "not
    applicable" rather than a block, because that shell could not deploy to Render
    either. Every fleet deploy runs from such a shell, so the escape is gone: any
    unreadable board-build state blocks."""
    for name in ("_load_render_key", "_render_logs", "_main_worktree_root"):
        assert not hasattr(safety, name), name
    verdict = preflight.board_build_verdict("refresh-worker", False, (None, {"missing_api_key": True, "reason": "x"}))
    assert verdict is not None and verdict[0] == "UNKNOWN"
