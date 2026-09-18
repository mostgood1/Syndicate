"""`/ncaaf` with no `?week=` opens on the schedule's target week.

MEASURED 2026-09-18 on production: web's `week_state` artifact targeted week 3
(`unplayed_kickoffs["3"].last = 2026-09-20T03:00Z`) and
`/api/ops/ncaaf/season-weeks` resolved `[1, 2, 3]`, yet `/ncaaf` rendered
"2026 week 1". `default_week()` only returned the target when it was IN the
legacy recommendations_summary index, and web's copy of that index tracked six
weeks with only week 1 populated -- so a stale index vetoed the real week.
"""
from __future__ import annotations

from flask import Flask

from syndicate.features.ncaaf import sources


def _pin(monkeypatch, *, legacy_weeks, target):
    monkeypatch.setattr(sources, "available_weeks", lambda: list(legacy_weeks))
    monkeypatch.setattr(sources, "default_season", lambda: 2026)
    monkeypatch.setattr(sources, "ncaaf_target_week", lambda season: target)


def test_a_stale_legacy_index_does_not_veto_the_target_week(monkeypatch):
    _pin(monkeypatch, legacy_weeks=[1], target=3)
    assert sources.default_week() == 3


def test_the_target_wins_over_an_empty_index_too(monkeypatch):
    _pin(monkeypatch, legacy_weeks=[], target=3)
    assert sources.default_week() == 3


def test_without_a_target_the_legacy_fallback_is_unchanged(monkeypatch):
    _pin(monkeypatch, legacy_weeks=[1, 2], target=None)
    assert sources.default_week() == 2
    _pin(monkeypatch, legacy_weeks=[], target=None)
    assert sources.default_week() == 1


def test_the_bare_ncaaf_route_asks_default_week(monkeypatch):
    """Reachability: the blueprint's `_selected_week()` is what `/ncaaf` and
    `/ncaaf/cards` pass to the page builder, and it reads the same function."""
    from syndicate.blueprints import ncaaf as ncaaf_blueprint

    monkeypatch.setattr(ncaaf_blueprint, "default_week", lambda: 3)
    with Flask(__name__).test_request_context("/ncaaf"):
        assert ncaaf_blueprint._selected_week() == 3
    with Flask(__name__).test_request_context("/ncaaf?week=2"):
        assert ncaaf_blueprint._selected_week() == 2
