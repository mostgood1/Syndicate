"""The live placer on `live-odds-worker` — dark by default, on its own clock."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def worker(monkeypatch):
    mod = importlib.import_module("scripts.run_live_odds_refresh_worker")
    mod._LAST_EXECUTION_AT = None
    for name in (
        "SYNDICATE_EXECUTION_ENABLED",
        "SYNDICATE_EXECUTION_INTERVAL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    return mod


def test_it_is_dark_by_default(worker, monkeypatch):
    """With money in the account, this is the property that matters most."""
    def explode(*_a, **_k):
        raise AssertionError("run_execution was called with execution disabled")

    monkeypatch.setattr("pipeline.execute_portfolio.run_execution", explode)
    worker._run_execution_tick()


def test_enabling_it_places(worker, monkeypatch):
    calls = []
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setattr(
        "pipeline.execute_portfolio.run_execution",
        lambda date, **kw: calls.append((date, kw)) or {"status": "ok", "placed": 0},
    )
    worker._run_execution_tick()
    assert len(calls) == 1


def test_it_never_passes_inline(worker, monkeypatch):
    """`inline=True` makes run_execution refuse live mode STRUCTURALLY.

    Correct on refresh-worker, and it would make this function silently
    pointless here — enabled, armed, funded, and placing nothing.
    """
    calls = []
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setattr(
        "pipeline.execute_portfolio.run_execution",
        lambda date, **kw: calls.append(kw) or {"status": "ok"},
    )
    worker._run_execution_tick()
    assert calls[0].get("inline") is not True


def test_it_holds_its_own_interval_not_the_loops(worker, monkeypatch):
    """This worker ticks as fast as 60s once a game is live."""
    calls = []
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setattr(
        "pipeline.execute_portfolio.run_execution",
        lambda date, **kw: calls.append(date) or {"status": "ok"},
    )
    worker._run_execution_tick()
    worker._run_execution_tick()
    worker._run_execution_tick()
    assert len(calls) == 1, "the placer ran on every loop tick"


def test_a_bad_interval_falls_back_rather_than_to_zero(worker, monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_INTERVAL_SECONDS", "soon")
    assert worker._execution_interval_seconds() == 300
    monkeypatch.setenv("SYNDICATE_EXECUTION_INTERVAL_SECONDS", "0")
    # Zero would mean "place on every tick", which is not a thing anybody types
    # on purpose into an interval.
    assert worker._execution_interval_seconds() == 300


def test_a_raising_placer_does_not_take_down_the_odds_refresh(worker, monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")

    def boom(*_a, **_k):
        raise RuntimeError("venue unreachable")

    monkeypatch.setattr("pipeline.execute_portfolio.run_execution", boom)
    # This worker exists for the odds refresh; a placer is a passenger on it.
    worker._run_execution_tick()


def test_the_placer_runs_inside_the_loop(worker):
    """A function nothing calls is the failure this repo keeps rediscovering."""
    import inspect

    source = inspect.getsource(worker.main)
    assert "_run_execution_tick()" in source
