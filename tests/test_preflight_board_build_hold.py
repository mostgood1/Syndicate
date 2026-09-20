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


def test_completion_is_board_build_timing_not_the_shortlist(safety, monkeypatch):
    """The shortlist write is mid-build. Reading it as done is what made the
    16:04:54Z window look safe."""
    asked: list[str] = []

    def fake_logs(key, text, minutes=0):
        asked.append(text)
        return [{"timestamp": "2026-09-19T16:00:00Z"}] if text == "BUILD_SPAN_ENTER" else [{"timestamp": "2026-09-19T15:30:00Z"}]

    monkeypatch.setattr(safety, "_load_render_key", lambda: "k")
    monkeypatch.setattr(safety, "_render_logs", fake_logs)
    monkeypatch.setattr(safety, "_expected_build_seconds", lambda key: 600.0)
    in_flight, facts = safety.board_build_state()
    assert "BOARD_BUILD_TIMING" in asked, "completion must be read from the build's own timing line"
    assert "LAYER2_SHORTLIST" not in asked
    assert in_flight is True
    assert facts["newest_build_complete"] == "2026-09-19T15:30:00Z"


def test_a_completed_build_reads_idle(safety, monkeypatch):
    monkeypatch.setattr(safety, "_load_render_key", lambda: "k")
    monkeypatch.setattr(safety, "_render_logs", lambda key, text, minutes=0: [
        {"timestamp": "2026-09-19T16:00:00Z" if text == "BUILD_SPAN_ENTER" else "2026-09-19T16:09:00Z"}])
    monkeypatch.setattr(safety, "_expected_build_seconds", lambda key: 600.0)
    in_flight, _ = safety.board_build_state()
    assert in_flight is False


def test_no_render_key_is_unknown(safety, monkeypatch):
    monkeypatch.setattr(safety, "_load_render_key", lambda: "")
    in_flight, facts = safety.board_build_state()
    assert in_flight is None and "RENDER_API_KEY" in str(facts.get("reason"))


def test_no_api_key_is_not_applicable_rather_than_a_block(preflight, safety, monkeypatch):
    """"Cannot ask" is not "cannot tell".

    Without RENDER_API_KEY this shell cannot read the worker -- and cannot
    deploy either, since `render_deploy.py` reads the same key. Blocking here
    would fail offline runs (this tool's own suite among them) while guarding
    nothing. Every other unreadable state still blocks, which the test above pins.
    """
    monkeypatch.setattr(safety, "_load_render_key", lambda: "")
    in_flight, facts = safety.board_build_state()
    assert in_flight is None and facts.get("missing_api_key") is True, "the case must be NAMED, not inferred from prose"
    assert preflight.board_build_verdict("refresh-worker", False, (in_flight, facts)) is None
    # ... while an unreadable WORKER (key present, logs unhelpful) still blocks.
    assert preflight.board_build_verdict("refresh-worker", False, (None, {"reason": "no BUILD_SPAN_ENTER in the lookback window"}))[0] == "UNKNOWN"
