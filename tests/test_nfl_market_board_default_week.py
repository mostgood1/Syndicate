"""`/nfl/api/market-board` with no week must serve the CURRENT week.

Measured 2026-09-22: it served week 18 from the 2026-08-01 backfill while week 3
was being played, because the default was "the highest week with a projection
file" and web's disk holds the backfill for weeks 4-18.
"""

from __future__ import annotations

import pytest
from flask import Flask

import syndicate.blueprints.nfl as nfl

ALL_WEEKS = list(range(1, 19))


@pytest.fixture
def app():
    return Flask(__name__)


def _select(app, monkeypatch, *, query="", weeks=ALL_WEEKS, target=3):
    monkeypatch.setattr(nfl, "nfl_projection_available_weeks", lambda season: list(weeks))
    monkeypatch.setattr(nfl, "nfl_target_week", lambda season: target, raising=False)
    monkeypatch.setattr(nfl, "default_week", lambda season: 1)
    with app.test_request_context(f"/nfl/api/market-board{query}"):
        return nfl._selected_market_board_week(2026)


def test_default_is_the_target_week_not_the_last_file(app, monkeypatch):
    assert _select(app, monkeypatch) == 3


def test_an_explicit_week_is_still_honoured(app, monkeypatch):
    assert _select(app, monkeypatch, query="?week=18") == 18


def test_a_target_without_a_projection_file_falls_back_to_the_latest(app, monkeypatch):
    assert _select(app, monkeypatch, weeks=[1, 2], target=3) == 2


def test_a_finished_season_falls_back_to_the_latest(app, monkeypatch):
    # `nfl_target_week` is None once every game has a final score.
    assert _select(app, monkeypatch, target=None) == 18
