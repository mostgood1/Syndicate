"""Venue price refresh runs on the VENUE's cadence, not the board build's.

Every test here fails against the code as it stood before
`pipeline/venue_odds_loop.py` existed -- either because the module was absent,
or, for the stage-timing test, because the line it asserts on was emitted
through `logger.info` and never reached stdout at all.
"""

from __future__ import annotations

import time

import pytest

from pipeline import venue_odds_loop


@pytest.fixture(autouse=True)
def _stop_loop_between_tests():
    """The loop is module-level state; a leaked thread would poison the next test."""
    yield
    venue_odds_loop.stop_venue_odds_loop(timeout=2.0)


def test_disabled_by_default_so_a_deploy_cannot_silently_add_periodic_work(monkeypatch, capfd):
    """OFF unless asked. This worker has 110 OOM kills and `#241` restart-looped it.

    The refusal is also NAMED -- a loop that is off and says nothing is
    indistinguishable from a loop that failed to start.
    """
    monkeypatch.delenv("SYNDICATE_VENUE_ODDS_LOOP_ENABLED", raising=False)
    assert venue_odds_loop.venue_odds_loop_enabled() is False
    assert venue_odds_loop.start_venue_odds_loop() is False
    assert "DISABLED" in capfd.readouterr().out


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
def test_enable_flag_accepts_the_usual_truthy_spellings(monkeypatch, raw):
    monkeypatch.setenv("SYNDICATE_VENUE_ODDS_LOOP_ENABLED", raw)
    assert venue_odds_loop.venue_odds_loop_enabled() is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "", "  "])
def test_anything_else_is_off_including_empty(monkeypatch, raw):
    monkeypatch.setenv("SYNDICATE_VENUE_ODDS_LOOP_ENABLED", raw)
    assert venue_odds_loop.venue_odds_loop_enabled() is False


def test_a_venue_refreshes_on_its_own_interval_not_once_per_tick(monkeypatch, capfd):
    """THE POINT OF THE LANE, as a test.

    A venue whose interval is far longer than the tick must be called ONCE
    across many ticks. Without the per-venue clock the loop would call it every
    tick and the venue's configured interval would mean nothing -- which is the
    same defect this module exists to fix, just relocated.
    """
    calls: list[float] = []

    def _refresh():
        calls.append(time.monotonic())
        return {"status": "ok", "count": 7}

    monkeypatch.setattr(venue_odds_loop, "_TICK_SECONDS", 0.01)
    monkeypatch.setattr(
        venue_odds_loop, "_venues", lambda: [("kalshi", _refresh, lambda: 3600.0)]
    )
    monkeypatch.setenv("SYNDICATE_VENUE_ODDS_LOOP_ENABLED", "1")

    assert venue_odds_loop.start_venue_odds_loop() is True
    time.sleep(0.35)  # ~35 ticks at the patched tick
    venue_odds_loop.stop_venue_odds_loop(timeout=2.0)

    assert len(calls) == 1, f"expected one refresh across many ticks, got {len(calls)}"
    out = capfd.readouterr().out
    assert "REFRESH venue=kalshi status=ok count=7" in out


def test_a_short_interval_venue_refreshes_repeatedly(monkeypatch):
    """The complement, so the test above cannot pass by never refreshing at all.

    Without this, a loop that called the venue exactly once and then wedged
    would satisfy `len(calls) == 1` and look correct.
    """
    calls: list[float] = []

    def _refresh():
        calls.append(time.monotonic())
        return {"status": "ok", "count": 1}

    monkeypatch.setattr(venue_odds_loop, "_TICK_SECONDS", 0.01)
    monkeypatch.setattr(
        venue_odds_loop, "_venues", lambda: [("kalshi", _refresh, lambda: 0.02)]
    )
    monkeypatch.setenv("SYNDICATE_VENUE_ODDS_LOOP_ENABLED", "1")

    venue_odds_loop.start_venue_odds_loop()
    time.sleep(0.35)
    venue_odds_loop.stop_venue_odds_loop(timeout=2.0)

    assert len(calls) > 3, f"a 0.02s interval should refresh repeatedly, got {len(calls)}"


def test_one_venue_failing_does_not_stop_the_loop_or_the_other_venue(monkeypatch, capfd):
    """A venue being unreachable is a NAMED refusal, not the end of the loop."""
    good: list[int] = []

    def _bad():
        raise RuntimeError("venue unreachable")

    def _good():
        good.append(1)
        return {"status": "ok", "count": 2}

    monkeypatch.setattr(venue_odds_loop, "_TICK_SECONDS", 0.01)
    monkeypatch.setattr(
        venue_odds_loop,
        "_venues",
        lambda: [("kalshi", _bad, lambda: 0.02), ("polymarket", _good, lambda: 0.02)],
    )
    monkeypatch.setenv("SYNDICATE_VENUE_ODDS_LOOP_ENABLED", "1")

    venue_odds_loop.start_venue_odds_loop()
    time.sleep(0.3)
    venue_odds_loop.stop_venue_odds_loop(timeout=2.0)

    out = capfd.readouterr().out
    assert "REFRESH_FAILED venue=kalshi" in out
    assert "RuntimeError" in out
    assert good, "the healthy venue must still refresh when its sibling raises"


def test_the_loop_retains_no_markets_between_ticks(monkeypatch):
    """MEMORY IS THE RISK ON THIS SERVICE, so it gets a test rather than a comment.

    The refresh functions RETURN their market list. If the loop held any
    reference to it the payload would survive the tick; this asserts the
    returned object is released once the refresh reports.
    """
    import gc
    import weakref

    holder: dict[str, object] = {}

    class _Payload(dict):
        """A dict subclass purely so it can be weak-referenced; plain dicts cannot."""

    def _refresh():
        markets = [{"ticker": f"T{i}"} for i in range(50)]
        payload = _Payload(status="ok", count=len(markets), markets=markets)
        holder["ref"] = weakref.ref(payload)
        return payload

    monkeypatch.setattr(venue_odds_loop, "_TICK_SECONDS", 0.01)
    monkeypatch.setattr(
        venue_odds_loop, "_venues", lambda: [("kalshi", _refresh, lambda: 3600.0)]
    )
    monkeypatch.setenv("SYNDICATE_VENUE_ODDS_LOOP_ENABLED", "1")

    venue_odds_loop.start_venue_odds_loop()
    time.sleep(0.2)
    venue_odds_loop.stop_venue_odds_loop(timeout=2.0)

    gc.collect()
    assert holder["ref"]() is None, "the loop is holding the refresh payload alive"


def test_starting_twice_does_not_double_the_request_rate(monkeypatch):
    """Two loops on one venue would double the venue's request rate silently."""
    monkeypatch.setattr(venue_odds_loop, "_TICK_SECONDS", 0.05)
    monkeypatch.setattr(
        venue_odds_loop,
        "_venues",
        lambda: [("kalshi", lambda: {"status": "cached"}, lambda: 3600.0)],
    )
    monkeypatch.setenv("SYNDICATE_VENUE_ODDS_LOOP_ENABLED", "1")

    assert venue_odds_loop.start_venue_odds_loop() is True
    assert venue_odds_loop.start_venue_odds_loop() is False


def test_stage_timing_reaches_stdout_not_just_the_logger(capfd):
    """`_log_stage_timing` was `logger.info`, which never reaches Render.

    VERIFIED IN PRODUCTION 2026-08-27 before changing it: a Render logs search
    for `duration_ms` returned only `[INTEL_TRACE]` lines and one for
    `board_publication` returned only the print-based CALLING/READY/RETURNED
    lines. This function's own payload appeared zero times.

    This test FAILS against the previous implementation -- `capfd` captures
    stdout, and the old body wrote nothing to it.
    """
    from pipeline.intelligence_state import _log_stage_timing

    _log_stage_timing("board_publication", 1234.5678)
    out = capfd.readouterr().out
    assert "[intelligence_state] STAGE_TIMING" in out
    assert "stage=board_publication" in out
    assert "duration_ms=1234.568" in out


def test_stage_timing_never_raises_on_a_bad_duration(capfd):
    """A timing line must not be able to kill the build it measures."""
    from pipeline.intelligence_state import _log_stage_timing

    _log_stage_timing("board_publication", float("nan"))
    _log_stage_timing("weird", "not-a-number")  # type: ignore[arg-type]
