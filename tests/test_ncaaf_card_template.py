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


# ---------------------------------------------------------------------------
# THE SCOREBOARD STRIP, modelled on SOCCER'S pregame compact card.
#
# Two of my own attempts are pinned here because both shipped:
#   generic  435px, two unconditional PROSE blocks repeating the card below
#   mine     633px, WORSE -- the school name in a `cards-mini-copy` line, which
#            `dense_cards.css` gives `overflow-wrap: anywhere`, rendered 1px
#            wide and 226px tall in a 39px box
# and the crests were never rendered at all: `cards-strip-logo` printed the
# ABBREVIATION AS TEXT while `game.away.logo_url` sat unread.
# ---------------------------------------------------------------------------

def _strip(games):
    env = Environment(loader=FileSystemLoader(str(REPO_ROOT / "syndicate" / "templates")))
    return env.get_template("shared/_scoreboard_strip.html").render(games=games, empty_text="No games")


def _strip_game(**overrides):
    g = {
        "gamePk": "g1", "status": "Week 1", "detail": "Week 1", "card_variant": "ncaaf_main",
        "away": {"abbr": "NC", "name": "North Carolina", "logo_url": "https://cdn/nc.png"},
        "home": {"abbr": "TCU", "name": "TCU", "logo_url": "https://cdn/tcu.png"},
        "markets": {"spread": {"home": -9.18}, "total": {"line": 46.86}},
        "ncaaf_card": {"scoreboard": {
            "kickoff_label": "Sat Aug 29, 11:00 AM CDT", "spread_label": "TCU by 10.3",
            "win_probability": "80.0%", "home_points": 30.3, "away_points": 20.0,
            "total_points": 50.3,
        }},
    }
    g.update(overrides)
    return g


def test_the_strip_renders_team_crests():
    """THE REPORTED DEFECT. `logo_url` was on every game and never rendered."""
    html = _strip([_strip_game()])
    assert 'src="https://cdn/nc.png"' in html
    assert 'src="https://cdn/tcu.png"' in html
    assert html.count("cards-strip-pregame-crest") >= 2


def test_a_missing_crest_falls_back_to_text_not_a_broken_image():
    g = _strip_game()
    g["home"]["logo_url"] = None
    html = _strip([g])
    assert "cards-strip-pregame-crest--text" in html


def test_each_team_row_carries_that_side_s_projected_score():
    """Soccer's shape: crest, abbreviation, that side's number."""
    html = _strip([_strip_game()])
    assert html.count("cards-strip-pregame-total") == 2
    assert "30.3" in html and "20.0" in html


def test_the_strip_shows_model_against_market():
    html = _strip([_strip_game()])
    for label in ("Spread", "Total", "Market", "Mkt total", "Win prob"):
        assert label in html


def test_the_strip_uses_the_ncaaf_sizing_modifier():
    """Soccer's 15px crest reads small here; the bump must not touch soccer."""
    html = _strip([_strip_game()])
    assert "cards-strip-card--ncaaf" in html
    assert "cards-strip-card--soccer" not in html


def test_the_strip_shows_ABBREVIATIONS_ONLY_never_the_school_name():
    """My 633px regression: a long name has no safe home in a 39px box."""
    html = _strip([_strip_game()])
    assert ">NC<" in html
    assert "North Carolina" not in html


def test_the_head_becomes_the_clock_when_a_game_is_live():
    g = _strip_game(shared_is_live=True, shared_game_state={"live": True, "clock": "7:31"})
    assert "7:31" in _strip([g])


def test_a_final_game_says_final():
    g = _strip_game(shared_game_state={"final": True})
    assert "Final" in _strip([g])


def test_the_generic_strips_prose_blocks_are_gone():
    html = _strip([_strip_game()])
    assert "cards-strip-live" not in html
    assert "cards-strip-lens" not in html


def test_facts_are_omitted_when_their_number_is_absent():
    """A dash reads as a broken card; an absent fact just closes the gap."""
    g = _strip_game()
    g["ncaaf_card"]["scoreboard"] = {"kickoff_label": "Sat"}
    g["markets"] = {}
    html = _strip([g])
    assert "cards-strip-pregame-total" not in html
    assert "Win prob" not in html


def test_the_strip_markup_is_balanced():
    html = _strip([_strip_game(), _strip_game(gamePk="g2")])
    assert len(re.findall(r"<div\b", html)) == len(re.findall(r"</div>", html))
    assert len(re.findall(r"<a\b", html)) == len(re.findall(r"</a>", html))


def test_every_class_the_strip_uses_is_styled_by_the_sheet_this_board_loads():
    """THE `.cards-market-sub` LESSON, made structural.

    That class had a colour rule and NO font-size rule, so it inherited 16px
    body text. MLB's `cards-linescore*` have zero rules here. Soccer's
    `cards-strip-pregame-*` ARE global (only
    `.cards-strip-card--soccer .cards-head-team-name` is scoped), which is why
    they are safe to reuse -- checked, not assumed.
    """
    css = (REPO_ROOT / "syndicate" / "static" / "shared" / "dense_cards.css").read_text(encoding="utf-8")
    html = _strip([_strip_game()])
    used = set()
    for attr in re.findall(r'class="([^"]+)"', html):
        used.update(c for c in attr.split() if c.startswith("cards-"))
    missing = sorted(c for c in used if c not in css)
    assert not missing, f"classes with no rule in dense_cards.css: {missing}"
