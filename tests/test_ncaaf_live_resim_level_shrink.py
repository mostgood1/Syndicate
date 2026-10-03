"""The live re-sim applies the pregame total-level shrink from the same module,
with a live-only override, and exempts market-implied FCS ratings."""
from __future__ import annotations

import pytest

from syndicate.features.ncaaf import live_resim, total_level


def _clear(monkeypatch):
    monkeypatch.delenv(total_level.PREGAME_ENV, raising=False)
    monkeypatch.delenv(total_level.LIVE_ENV, raising=False)


def test_live_is_held_at_one_and_independent_of_pregame(monkeypatch):
    """User decision 2026-10-03: live stays at 1.0 until its own grade passes."""
    _clear(monkeypatch)
    assert total_level.NCAAF_LIVE_TOTAL_LEVEL_SHRINK == 1.0
    assert total_level.live_total_level_shrink() == 1.0
    # tonight's fit sets the PREGAME constant; live must not move
    monkeypatch.setattr(total_level, "NCAAF_TOTAL_LEVEL_SHRINK", 0.3)
    assert total_level.total_level_shrink() == 0.3
    assert total_level.live_total_level_shrink() == 1.0
    # nor does the pregame env var reach live
    monkeypatch.setenv(total_level.PREGAME_ENV, "0.4")
    assert total_level.live_total_level_shrink() == 1.0
    # the live env var is how the live grade runs a candidate
    monkeypatch.setenv(total_level.LIVE_ENV, "0.5")
    assert total_level.live_total_level_shrink() == 0.5
    assert total_level.total_level_shrink() == 0.4               # pregame untouched by it
    monkeypatch.setenv(total_level.LIVE_ENV, "garbage")
    assert total_level.live_total_level_shrink() == 1.0          # unparseable -> the live constant


def _state():
    return live_resim.NcaafLiveGameState(
        home_team="Alpha", away_team="Beta", period=2, clock_seconds=300,
        home_score=14, away_score=10, possession_owner="home", field_position=40,
        down=1, distance=10, as_of="2026-10-03T19:00:00Z",
    )


def _resim(**kw):
    # high-level teams on both sides, so a level shrink must move the total
    return live_resim.resim_live_game(_state(), home_offense=0.45, home_defense=-0.25,
                                      away_offense=0.40, away_defense=-0.20, sims=8, **kw)


def test_on_differs_from_off_and_reports_its_lambda(monkeypatch):
    _clear(monkeypatch)
    off = _resim(level_shrink=1.0)
    on = _resim(level_shrink=0.3)
    assert off["level_shrink"] == 1.0 and on["level_shrink"] == 0.3
    assert on["total_mean_uncalibrated"] != off["total_mean_uncalibrated"]


def test_kill_switch_is_exact(monkeypatch):
    _clear(monkeypatch)
    a = _resim(level_shrink=1.0)
    monkeypatch.setenv(total_level.LIVE_ENV, "1")
    b = _resim()
    assert a == b


def test_default_reads_the_live_setting_only(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv(total_level.PREGAME_ENV, "0.3")
    assert _resim()["level_shrink"] == 1.0                   # pregame never reaches the re-sim
    monkeypatch.setenv(total_level.LIVE_ENV, "0.3")
    assert _resim()["level_shrink"] == 0.3
    assert _resim(level_shrink=1.0)["level_shrink"] == 1.0   # an explicit caller value wins


def test_market_implied_games_are_exempt(monkeypatch):
    """The snapshot builder passes 1.0 when the game carries market-implied provenance."""
    import inspect

    src = inspect.getsource(live_resim.build_live_lens_snapshot)
    assert 'level_shrink=1.0 if isinstance(names.get("provenance"), Mapping) else None' in src
