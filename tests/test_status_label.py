"""Card status badges render a label, never a raw status dict (lane card-status-dict-label).

/wnba/cards?client=board printed `{"status": "scheduled", "detail": "8:00 PM CT",
"startTime": ..., "in_progress": false, ...}` in the badge (2026-10-01): WNBA's
board context carries the source API's status CONTRACT dict, and the shared
templates did `{{ game.status }}`.
"""
from __future__ import annotations

import pytest

CONTRACT = {"status": "scheduled", "detail": "8:00 PM CT", "startTime": "2026-10-02T01:00:00Z",
            "in_progress": False, "final": False, "period": None, "clock": ""}


def _label(value):
    from syndicate.features.shared.status_label import status_label

    return status_label(value)


@pytest.mark.parametrize("value, expected", [
    (CONTRACT, "scheduled"),
    ({**CONTRACT, "status": ""}, "8:00 PM CT"),
    ({**CONTRACT, "in_progress": True, "period": 3, "clock": "4:12"}, "Q3 4:12"),
    ({**CONTRACT, "in_progress": True, "detail": "Halftime"}, "Halftime"),
    ({**CONTRACT, "in_progress": True, "detail": ""}, "Live"),
    ({**CONTRACT, "final": True, "in_progress": False}, "Final"),
    ("Final", "Final"),          # every other sport passes a string: unchanged
    ("In Progress", "In Progress"),
    (None, ""),
])
def test_status_label(value, expected):
    assert _label(value) == expected


def _render(template_name, **context):
    from jinja2 import ChainableUndefined

    from syndicate.app import app

    env = app.jinja_env.overlay(undefined=ChainableUndefined)
    with app.test_request_context("/"):
        return env.get_template(template_name).render(**context)


def test_generic_card_badge_shows_a_label_not_the_dict():
    html = _render("shared/_game_card_generic.html", game={"status": CONTRACT}, card_dom_id="t")
    assert "startTime" not in html and "in_progress" not in html
    assert '<span class="cards-status-badge">scheduled</span>' in html


def test_generic_scoreboard_strip_badge_shows_a_label_not_the_dict():
    html = _render("shared/_scoreboard_strip_generic.html", games=[{"status": CONTRACT}], game={"status": CONTRACT})
    assert "startTime" not in html and "in_progress" not in html
