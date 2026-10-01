"""Defects found by the 2026-10-01 local-production route audit (lane local-production-audit-fixes)."""
from __future__ import annotations

import pytest


@pytest.fixture()
def client():
    from syndicate.app import app

    app.config["TESTING"] = True
    return app.test_client()


def _render_generic_card(game):
    from jinja2 import ChainableUndefined

    from syndicate.app import app

    # Tolerate every card field these minimal fixtures leave out, so the only
    # thing that can fail is the panel loop. `panel['items']` still resolves to
    # the dict METHOD under ChainableUndefined, so the real defect reproduces.
    env = app.jinja_env.overlay(undefined=ChainableUndefined)
    template = env.get_template("shared/_game_card_generic.html")
    with app.test_request_context("/"):
        return template.render(game=game, card_dom_id="t")


def test_a_panel_without_items_renders():
    # `panel['items']` on a dict with no "items" key falls back in Jinja to the
    # dict's .items METHOD -- defined, truthy, and not iterable. /wnba/cards?client=board
    # returned 500 `TypeError: 'builtin_function_or_method' object is not iterable`.
    html = _render_generic_card({"panels": [{"eyebrow": "E", "title": "T", "body": "panel body"}]})
    assert "panel body" in html


def test_panel_items_still_render():
    html = _render_generic_card({"panels": [{"eyebrow": "E", "title": "T", "body": "b", "items": ["Edge: +2.1", "plain"]}]})
    assert "+2.1" in html and "plain" in html


def test_ncaaf_api_weeks_includes_real_smartsim2_weeks(client, monkeypatch):
    # /ncaaf/api/weeks read only the legacy recommendations_summary index, which no
    # longer exists, so it returned [] while the hub listed the real 2026 weeks.
    from syndicate.blueprints import ncaaf as ncaaf_bp

    monkeypatch.setattr(ncaaf_bp, "week_summaries", lambda: [])
    monkeypatch.setattr(ncaaf_bp, "_resolve_ncaaf_active_season_and_weeks", lambda: (2026, [1, 4, 5]))
    payload = client.get("/ncaaf/api/weeks").get_json()
    assert payload["available_weeks"] == [1, 4, 5]
    assert {(w["season"], w["week"]) for w in payload["weeks"]} == {(2026, 1), (2026, 4), (2026, 5)}


@pytest.mark.parametrize("path", [
    "/mlb/api/betting-card", "/mlb/api/betting-card/", "/mlb/betting-card/api",
    "/mlb/betting-card/api/", "/mlb/api/betting-card-api", "/mlb/betting-card-api",
])
def test_dead_mlb_betting_card_stub_is_gone(client, path):
    # A hard-coded `"rank_cards": []` stub from a June test fix; nothing called it.
    assert client.get(path).status_code == 404
