"""The NCAAF card template must RENDER, and every tab must address a real panel.

WHY THIS FILE EXISTS. The template already carried this rule as a comment:

    "a panel exists iff a tab addresses it. `card_tabs` below is that rule,
     written once and used to render both halves, so the two cannot drift
     apart again."

It was a comment, not a test, and it drifted apart again on 2026-08-27. Moving
the tab rail above the panels left an orphaned fragment behind -- two surplus
`</div>` closers that ended the card early, so the `details` SECTION fell
outside it. Measured on production:

    tabTargets : identity, context, coverage, details
    panelIds   : identity, context, coverage
    clicking "Details" -> activePanels: []   visiblePanels: []

The card collapsed to nothing, which is the SAME failure the template's comment
records from 2026-08-14. Everything else passed: jinja parsed, the payload
tests were green, the API served correct JSON, and the deploy went live clean.
A payload check cannot see a template defect -- only rendering can.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TEMPLATE = "shared/_game_card_ncaaf.html"


def _game(**overrides):
    game = {
        "gamePk": "g1",
        "status": "Week 1",
        "href": "/ncaaf/game/g1",
        "href_label": "Open game detail",
        "away": {"abbr": "NC", "name": "North Carolina", "logo_url": None, "primary_color": None},
        "home": {"abbr": "TCU", "name": "TCU", "logo_url": None, "primary_color": None},
        "metrics": [
            {"label": "Market spread", "value": "-9.2"},
            {"label": "Market total", "value": "46.9"},
            {"label": "Projected total", "value": 50.3},
            {"label": "Projected spread", "value": "TCU by 10.3"},
        ],
        "market_tiles": [
            {"label": "Spread", "title": "TCU -9.2", "sub": "Model TCU -10.3 · +1.1 vs market"},
            {"label": "Total", "title": "46.9", "sub": "Model 50.3 · +3.5 vs market"},
            {"label": "Win probability", "title": "TCU 80%", "sub": "Model win probability"},
            {"label": "Books", "title": "11", "sub": "oddsapi_book_quotes"},
        ],
        "ncaaf_card": {
            "summary": {},
            "teams": {"away": {"school_name": "North Carolina"}, "home": {"school_name": "TCU"}},
            "scoreboard": {
                "kickoff_label": "Sat Aug 29, 11:00 AM CDT",
                "venue": "Aviva Stadium",
                "total_points": 50.3,
                "spread_label": "TCU by 10.3",
                "win_probability": "80.0%",
                "home_points": 30.3,
                "away_points": 20.0,
                "source_label": "SmartSim 2.0",
            },
            "scoreboard_header": {"away": {}, "home": {}},
            "context_sections": [],
        },
    }
    game.update(overrides)
    return game


def _render(game=None) -> str:
    env = Environment(loader=FileSystemLoader(str(REPO_ROOT / "syndicate" / "templates")))
    return env.get_template(TEMPLATE).render(game=game or _game(), show_matchup_context=False)


def test_every_tab_addresses_a_panel_that_exists():
    """THE MEASURED FAILURE. An orphan tab collapses the card to nothing."""
    html = _render()
    tabs = re.findall(r'data-tab-target="([^"]+)"', html)
    panels = re.findall(r'data-panel-id="([^"]+)"', html)
    assert tabs, "no tabs rendered"
    orphans = [t for t in tabs if t not in panels]
    assert not orphans, (
        f"tabs addressing no panel: {orphans}. Clicking one turns every panel off "
        f"and none back on. panels={panels}"
    )


def test_every_panel_is_addressed_by_a_tab():
    """The other half of the same rule: a panel with no tab ships unreachable."""
    html = _render()
    tabs = re.findall(r'data-tab-target="([^"]+)"', html)
    panels = re.findall(r'data-panel-id="([^"]+)"', html)
    unreachable = [p for p in panels if p not in tabs]
    assert not unreachable, f"panels no tab can reach: {unreachable}"


def test_the_markup_is_balanced():
    """Surplus closers end the card early and evict whatever follows.

    This is what actually broke: two extra `</div>` left by an edit, which
    jinja parsed happily because unbalanced HTML is still valid TEMPLATE text.
    """
    html = _render()
    opens = len(re.findall(r"<div\b", html))
    closes = len(re.findall(r"</div>", html))
    assert opens == closes, f"<div> {opens} vs </div> {closes} -- delta {opens - closes}"


def test_the_compact_header_renders_in_mlb_order():
    """Score ribbon, then market row, then the tab rail -- above the panels."""
    html = _render()
    ribbon = html.index("cards-score-ribbon")
    market = html.index("cards-market-row")
    rail = html.index("cards-tabs-rail")
    first_panel = html.index('class="cards-panel')
    assert ribbon < market < rail < first_panel, (
        "compact header out of order or below the panels "
        f"(ribbon={ribbon} market={market} rail={rail} panel={first_panel})"
    )


def test_market_tiles_render_one_tile_each():
    html = _render()
    assert html.count("cards-market-tile") == 4
    assert "Model TCU -10.3" in html and "Model 50.3" in html


def test_a_card_with_no_projection_still_renders_and_stays_balanced():
    """The empty state must not produce a broken card.

    A card with no scoreboard numbers should simply omit the ribbon, not
    render a half-open one.
    """
    game = _game()
    game["ncaaf_card"]["scoreboard"] = {"kickoff_label": "Sat", "venue": "V"}
    game["market_tiles"] = []
    game["metrics"] = []
    html = _render(game)
    assert "cards-score-ribbon" not in html
    assert "cards-market-row" not in html
    opens = len(re.findall(r"<div\b", html))
    closes = len(re.findall(r"</div>", html))
    assert opens == closes, f"empty-state card unbalanced: {opens} vs {closes}"
    tabs = re.findall(r'data-tab-target="([^"]+)"', html)
    panels = re.findall(r'data-panel-id="([^"]+)"', html)
    assert [t for t in tabs if t not in panels] == []
