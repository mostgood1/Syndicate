"""`shared/rank_board.html` must render the stats every builder is forced to compute.

THE DEFECT, measured on production 2026-08-27. `header_stats` is a REQUIRED
argument of `build_rank_page_context` -- no default, 31 call sites across 23
files -- and this template read it NOWHERE. It rendered `summary_panel.
summary_stats` instead, and `summary_panel` is optional. So every builder that
supplied only the mandatory argument computed a slate summary that was
discarded silently.

Sweep of all 21 reachable rank_board routes on production that day:

    renders slate stats        1   /ncaaf/live-lens (fixed hours earlier)
    HAS CARDS, renders none   14   all 7 MLB board routes, /ncaab/results,
                                   /ncaab/archive, /ncaaf/archive, /nfl/archive,
                                   /nfl/live-lens, /soccer/epl/archive,
                                   /soccer/epl/props
    correctly wired, no data   1   /nfl/picks (summary_panel if rows else None)
    out of season, unknown     5

WHY IT SURVIVED: 11 sport-specific templates (nba/archive.html,
wnba/picks.html, nhl/betting_card.html, ...) DO loop over `header_stats`. The
argument is load-bearing on those routes and inert here, so "mandatory but
ignored" never looked wrong from either end.

These tests render the real template through the real app, because the bug that
started this chain was invisible to payload assertions: the API carried correct
stats while the page came back byte-identical.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.app import app

PILL = re.compile(
    r'feature-summary-pill__label">([^<]*)</div>\s*<div class="feature-summary-pill__value">([^<]*)<'
)

_STATS = [
    {"label": "Games", "value": "51"},
    {"label": "Live", "value": "3"},
    {"label": "Pregame", "value": "48"},
]


def _render(**overrides):
    from flask import render_template

    context = {
        "date": "2026-08-27",
        "intro_title": "Board",
        "intro_body": "body",
        "aria_label": "board",
        "route_path": "/ncaaf/archive",
        "rank_cards": [],
        "header_stats": [],
        "module_links": [],
        "control_value": "1",
    }
    context.update(overrides)
    with app.test_request_context("/"):
        return render_template("shared/rank_board.html", **context)


def _pills(html):
    return {label: value for label, value in PILL.findall(html)}


def test_HEADER_STATS_NOW_RENDER(html=None):
    """THE FIX. A builder supplying only the mandatory argument gets a strip."""
    got = _pills(_render(header_stats=_STATS))
    assert got == {"Games": "51", "Live": "3", "Pregame": "48"}


def test_a_summary_panel_still_wins_and_does_not_double_render():
    """A builder that supplies its own panel keeps control. Rendering BOTH
    would stack the same numbers twice -- which is the failure mode that made
    /ncaaf/live-lens drop its warning-panel list_items in the first place."""
    html = _render(
        header_stats=_STATS,
        summary_panel={
            "eyebrow": "Slate state",
            "title": "2026 Week 1",
            "body": "b",
            "summary_stats": [{"label": "Games", "value": "51"}],
        },
    )
    pills = PILL.findall(html)
    assert len(pills) == 1, f"expected the panel's single pill, got {pills}"
    assert pills[0] == ("Games", "51")


def test_an_empty_header_stats_renders_no_empty_strip():
    """`header_stats=[]` is legal and common. An empty bordered container is
    worse than nothing."""
    html = _render(header_stats=[])
    assert "feature-summary-strip" not in html


def test_no_stats_and_no_panel_renders_nothing():
    html = _render()
    assert "feature-summary-strip" not in html
    assert "feature-summary-pill" not in html


def test_the_strip_carries_no_empty_heading():
    """Rendered as a bare strip, not through _content_panel.html, which emits
    <h3> and <p> unconditionally -- these routes have no title or body."""
    html = _render(header_stats=_STATS)
    strip = html[html.index("feature-summary-strip") - 400 : html.index("feature-summary-strip") + 100]
    assert "<h3></h3>" not in strip
    assert "<p></p>" not in strip


def test_the_values_are_escaped_not_injected():
    """These come from builders, but the rule is cheap to hold."""
    html = _render(header_stats=[{"label": "X", "value": "<script>alert(1)</script>"}])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize("n", [1, 7, 20])
def test_every_stat_supplied_is_rendered(n):
    stats = [{"label": f"L{i}", "value": str(i)} for i in range(n)]
    assert len(PILL.findall(_render(header_stats=stats))) == n
