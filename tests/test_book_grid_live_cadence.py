"""`#340` — the book-grid rebuild speeds up while a game is live.

The artifact rebuilt every 600s, which made it the binding constraint on live
freshness: capture runs at 60s and the board page polls at 60s, and a 10-minute
artifact between them throws away nearly all of both. A live board could be nine
minutes behind the market with every other component healthy.

Not a standing 5x, which is `#241` (worker periodic work is never free -- that
lane caused a production restart loop). Measured 2026-08-11 00:0xZ the worker sat
at 3,211MB of 4,096, so the fast cadence is tied to live games and the slate ends
it.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "_rrw_cadence", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py"
)


@pytest.fixture()
def worker(monkeypatch):
    monkeypatch.delenv("SYNDICATE_BOOK_GRID_REFRESH_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("SYNDICATE_BOOK_GRID_LIVE_REFRESH_INTERVAL_SECONDS", raising=False)
    mod = importlib.util.module_from_spec(_SPEC)
    sys.modules["_rrw_cadence"] = mod
    _SPEC.loader.exec_module(mod)
    mod._BOOK_GRID_LAST_RUN.clear()
    return mod


def test_idle_slate_keeps_the_ten_minute_cadence(worker):
    worker._BOOK_GRID_LAST_RUN["any_live"] = False
    assert worker._book_grid_refresh_interval_seconds() == 600


def test_a_live_game_speeds_the_rebuild_to_two_minutes(worker):
    worker._BOOK_GRID_LAST_RUN["any_live"] = True
    assert worker._book_grid_refresh_interval_seconds() == 120


def test_an_explicit_override_disables_the_adaptive_path(worker, monkeypatch):
    # Someone pinning this value is answering the cadence question by hand.
    # Speeding up underneath that would make the setting a lie.
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_REFRESH_INTERVAL_SECONDS", "900")
    worker._BOOK_GRID_LAST_RUN["any_live"] = True
    assert worker._book_grid_refresh_interval_seconds() == 900


def test_the_live_interval_is_tunable_without_a_deploy(worker, monkeypatch):
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_LIVE_REFRESH_INTERVAL_SECONDS", "180")
    worker._BOOK_GRID_LAST_RUN["any_live"] = True
    assert worker._book_grid_refresh_interval_seconds() == 180


def test_absent_flag_is_treated_as_not_live(worker):
    # A fresh process has never built a grid, so it cannot know. Defaulting to
    # the SLOW cadence is the conservative direction: the cost of being wrong is
    # one late board, not a restart loop on a 4GB worker already at 3.2GB.
    assert "any_live" not in worker._BOOK_GRID_LAST_RUN
    assert worker._book_grid_refresh_interval_seconds() == 600
