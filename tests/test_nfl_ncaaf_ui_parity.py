"""NFL and NCAAF must render the SAME board surfaces -- compact card, main
card, live lens.

WHY THIS FILE EXISTS. NCAAF's board was rebuilt over 2026-08 and NFL was not,
and nothing anywhere failed. Measured on production 2026-09-07 (web
`81213a32`), both boards served from the SAME dispatchers on the same
afternoon:

    surface                        NCAAF                    NFL
    card_variant                   ncaaf_main x51           shared_default x16
    compact card height            181px, uniform x51       643-1085px, 16 of 16
                                                             cards a different height
    crest <img> in the strip       102                      0
    shared_predictions home_cover  51/51                    0/16
    shared_predictions total_over  51/51                    0/16
    ESPN status on a started game  "Final" / "14:40 - 3rd"  never written

A uniform height is direct evidence nothing wraps; SIXTEEN DISTINCT HEIGHTS ON
SIXTEEN CARDS is direct evidence each card was sized by a different-length
paragraph of prose. Every NFL test was green throughout, because no test asked
which PARTIAL a variant reaches -- `card_variant` is a plain string and the
branch that reads it lives in a template.

WHAT THIS FILE PINS, and it is deliberately the JOIN rather than either half:
the producer emits a football variant, the dispatcher routes that variant to
the football partial, and the partial reads the key the producer actually sets.
A test on any one of those three passes while the chain is broken -- which is
exactly what happened.

DATA-INDEPENDENT ON PURPOSE. Every fixture here is synthetic, so this runs in a
`session_worktree` with no `data/` and in CI, where ~92 tests fail for that
absence alone and a data-dependent parity test would be indistinguishable from
them.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import cards as nfl_cards  # noqa: E402
from syndicate.features.nfl import live_lens as nfl_live_lens  # noqa: E402
from syndicate.features.nfl import preseason_cards as nfl_preseason_cards  # noqa: E402
from syndicate.features.nfl.live_game_state import attach_nfl_live_game_state  # noqa: E402
from syndicate.features.shared.team_aliases import canonical_team  # noqa: E402
from syndicate.features.shared.football_cards import (  # noqa: E402
    cover_probability,
    football_market_tiles,
    football_shared_predictions,
    format_kickoff_label,
)

TEMPLATE_ROOT = REPO_ROOT / "syndicate" / "templates"
FOOTBALL_VARIANTS = ("ncaaf_main", "nfl_main")


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATE_ROOT)), autoescape=True)


class _Projection:
    """The four fields both football engines publish, and nothing else.

    A stand-in rather than a real `SmartSimNflProjection`/`SmartSimNcaafProjection`
    precisely because `football_shared_predictions` reads by `getattr` and must
    work for both -- a fixture typed as one sport's dataclass would pass while
    the other sport's shape silently failed.
    """

    def __init__(self, **kwargs):
        self.home_score_mean = kwargs.get("home_score_mean", 24.0)
        self.away_score_mean = kwargs.get("away_score_mean", 20.0)
        self.margin_mean = kwargs.get("margin_mean", 4.0)
        self.total_mean = kwargs.get("total_mean", 44.0)
        self.margin_stdev = kwargs.get("margin_stdev", 13.0)
        self.total_stdev = kwargs.get("total_stdev", 11.0)
        self.home_win_rate = kwargs.get("home_win_rate", 0.62)


def _nfl_game(**overrides) -> dict:
    game = {
        "gamePk": "2026_01_NE_SEA",
        "card_variant": "nfl_main",
        "status": "Week 1",
        "detail": "SmartSim 2.0",
        "summary": "SmartSim 2.0 projects Seattle 22.1 - 21.8 New England.",
        "href": "/nfl/game/2026_01_NE_SEA",
        "href_label": "Open NFL game detail",
        "away": {"abbr": "NE", "name": "New England Patriots", "logo_url": "https://x/ne.png"},
        "home": {"abbr": "SEA", "name": "Seattle Seahawks", "logo_url": "https://x/sea.png"},
        "metrics": [{"label": "Home mean", "value": 22.1}],
        "market_tiles": [{"label": "Spread", "title": "SEA -3.5", "sub": "Model SEA -0.3"}],
        "markets": {"spread": {"home": -3.5}, "total": {"line": 44.5}},
        "panels": [{"eyebrow": "SmartSim 2.0", "title": "Projection", "body": "b", "items": []}],
        "nfl_card": {
            "version": 1,
            "sport_label": "NFL",
            "summary": {"publication_ready": True, "ready_label": "Publication ready", "coverage_score": None,
                        "coverage_tier": "projection_only", "publication_status": "publishable",
                        "publication_priority": None, "tier_badges": []},
            "teams": {"home": {"abbreviation": "SEA"}, "away": {"abbreviation": "NE"}},
            "scoreboard": {
                "home_points": 22.1,
                "away_points": 21.8,
                "total_points": 43.9,
                "spread_label": "Seattle Seahawks by 0.3",
                "spread_label_short": "SEA by 0.3",
                "win_probability": "50.7%",
                "source_label": "SmartSim 2.0",
                "kickoff": "2026-09-10T00:20:00Z",
                "kickoff_label": "Wed Sep 9, 7:20 PM CDT",
                "venue": "Lumen Field",
            },
            "scoreboard_header": {"away": {}, "home": {}},
            "team_context": {"items": [], "summary": "s"},
            "matchup_context": {"items": [], "summary": "s"},
            "smartsim_reasons": [],
            "context_sections": [],
        },
    }
    game.update(overrides)
    return game


# --------------------------------------------------------------- the dispatch


def test_both_football_variants_reach_the_football_partials():
    """The whole defect in one assertion, on both dispatchers.

    NFL's cards carried a full projection, real crests and a real market line
    and STILL rendered the generic partials, because the branch is
    `card_variant` and nothing else reads the payload.
    """
    for name in ("shared/_game_card.html", "shared/_scoreboard_strip.html"):
        source = (TEMPLATE_ROOT / name).read_text(encoding="utf-8")
        for variant in FOOTBALL_VARIANTS:
            assert f"'{variant}'" in source, f"{name} does not route {variant}"
        # BRANCH lines only. Both files name the variants in their header
        # comment too, and a comment routes nothing.
        football_branch = [
            line
            for line in source.splitlines()
            if "ncaaf_main" in line and ("{% if" in line or "{% elif" in line)
        ]
        assert football_branch, f"{name} has no branch naming ncaaf_main"
        assert all("nfl_main" in line for line in football_branch), (
            f"{name} routes ncaaf_main and nfl_main on different branches -- "
            "they must share one, or the two codes drift again"
        )


def test_the_football_partials_read_either_sports_card_block():
    """The third link in the chain. A dispatcher that routes `nfl_main` to a
    partial reading only `ncaaf_card` renders an EMPTY football card, which is
    a different failure and looks like missing data."""
    for name in ("shared/_game_card_ncaaf.html", "shared/_scoreboard_strip_ncaaf.html"):
        source = (TEMPLATE_ROOT / name).read_text(encoding="utf-8")
        assert "game.nfl_card" in source, f"{name} cannot see an NFL card block"
        assert "game.ncaaf_card" in source, f"{name} lost the NCAAF card block"


def test_every_nfl_card_builder_emits_the_football_variant():
    """ALL THREE builders, not just the one serving the current season.

    `_game_from_snapshot_bundle` serves every stored 2025 week,
    `_game_from_smartsim_projection` serves 2026, and
    `preseason_cards._game_from_preseason_projection` serves August. A board
    whose shape depends on which artifact backed it -- or on the phase -- is
    the same class of defect as one that never changes shape at all.

    Scanned as SOURCE rather than by calling the builders, because each needs a
    different real artifact on disk and this file must run in a worktree with
    no `data/`. A literal is what the dispatcher reads, so a literal is what
    this checks.
    """
    modules = [nfl_cards.__file__, nfl_preseason_cards.__file__]
    for path in modules:
        source = Path(path).read_text(encoding="utf-8-sig")
        variants = re.findall(r'"card_variant": "([a-z_0-9]+)"', source)
        assert variants, f"{path}: no card_variant literals -- has the key been renamed?"
        assert set(variants) == {"nfl_main"}, (path, variants)


def test_the_nfl_card_renders_the_football_partial_not_the_generic_one():
    html = _env().get_template("shared/_game_card_ncaaf.html").render(game=_nfl_game())
    assert "cards-tabs-rail" in html
    assert "Lumen Field" in html
    assert "Wed Sep 9, 7:20 PM CDT" in html
    # Sport-specific copy must follow the sport, not the file name.
    assert "No NCAAF team context" not in html
    assert "No NFL team context" in html
    # NCAAF's legacy engine name must never appear on an NFL card: a card that
    # claims engine involvement that did not happen is a disclosure defect.
    assert "Enhanced Totals Engine" not in html
    assert "SmartSim 2.0" in html


def test_the_nfl_compact_card_carries_crests_and_a_kickoff_and_no_prose():
    """The 643-1085px generic strip in one assertion.

    `cards-strip-live` and `cards-strip-lens` are the two unconditional prose
    blocks that sized every NFL card differently -- `game.summary` and the
    first panel's title/body, both repeating the card directly below.
    """
    html = _env().get_template("shared/_scoreboard_strip_ncaaf.html").render(
        games=[_nfl_game()], empty_text="none"
    )
    assert html.count("cards-strip-pregame-crest") >= 2
    assert "cards-strip-pregame-head" in html
    assert "Wed Sep 9, 7:20 PM CDT" in html
    assert "cards-strip-live" not in html
    assert "cards-strip-lens" not in html
    # The chip CLIPS with no wrap and no ellipsis, so the short label wins.
    assert "SEA by 0.3" in html
    assert "Seattle Seahawks by 0.3" not in html


def test_an_ncaaf_card_still_renders_unchanged_through_the_shared_partials():
    """The control. Every assertion above is about NFL reaching NCAAF's
    surfaces; this one is that NCAAF still reaches its own."""
    game = _nfl_game()
    ncaaf_card = game.pop("nfl_card")
    ncaaf_card.pop("sport_label")
    ncaaf_card["scoreboard"].pop("spread_label_short")
    ncaaf_card["teams"] = {
        "home": {"abbreviation": "TCU", "school_name": "TCU", "conference_short_name": "Big 12", "rank": 17},
        "away": {"abbreviation": "NC", "school_name": "North Carolina", "conference_short_name": "ACC"},
    }
    game["ncaaf_card"] = ncaaf_card
    game["card_variant"] = "ncaaf_main"
    html = _env().get_template("shared/_game_card_ncaaf.html").render(game=game)
    assert "No NCAAF team context" in html
    assert "Big 12" in html
    assert "Home rank" in html
    # An NCAAF producer sets no short label; the chip falls back to the long one.
    strip = _env().get_template("shared/_scoreboard_strip_ncaaf.html").render(games=[game], empty_text="none")
    assert "Seattle Seahawks by 0.3" in strip


def test_a_football_variant_without_a_card_block_falls_back_rather_than_rendering_empty():
    game = _nfl_game()
    game.pop("nfl_card")
    html = _env().get_template("shared/_game_card_ncaaf.html").render(game=game)
    assert "cards-game-card" in html
    assert "Lumen Field" not in html


def test_every_nfl_team_resolves_to_a_crest_through_the_canonical_alias_map():
    """THE SNAPSHOT AND THE PROJECTION SPEAK DIFFERENT VOCABULARIES.

    `nfl_team_branding.csv` is keyed the way ESPN writes abbreviations (`LAR`,
    `WSH`); the smartsim2 projection artifact carries nflverse's (`LA`, `WAS`).
    All 32 teams were in the file and two were unreachable by the name the card
    asks with -- measured on the served `/nfl/cards` compact strip 2026-09-08 as
    **30 of 32** crest rows, the misses being exactly `LA` and `WAS`, with zero
    broken image URLs. NCAAF is 102/102 on the same surface.

    Pinned through the PUBLIC resolver, not a private copy: `canonical_team` is
    the one map and it already knew all four spellings -- the branding call site
    simply never went through it.
    """
    for code, expected in (("LA", "los angeles rams"), ("WAS", "washington commanders"),
                           ("LAR", "los angeles rams"), ("WSH", "washington commanders")):
        assert canonical_team("nfl", code) == expected, code


def test_the_crest_fallback_does_not_print_the_abbreviation_twice():
    """A team with no crest rendered "LA LA 25.1" -- the fallback span and the
    team span both printed `abbr`. Latent in NCAAF, which has never lacked a
    crest; the fallback still has to be right the next time one does."""
    game = _nfl_game()
    game["away"] = {"abbr": "LA", "name": "Los Angeles Rams", "logo_url": None}
    html = _env().get_template("shared/_scoreboard_strip_ncaaf.html").render(
        games=[game], empty_text="none"
    )
    row = [line for line in html.splitlines() if "cards-strip-pregame-team" in line]
    assert row, "no team row rendered"
    # The abbreviation appears once per row, not twice.
    assert html.count(">LA<") == 1, html.count(">LA<")
    assert 'aria-hidden="true"' in html, "the spacer must be hidden from screen readers"


# ------------------------------------------------------- the projection block


def test_the_market_line_is_converted_from_book_spread_to_home_margin():
    """THE SIGN, which `state.md` records costing a whole NFL analysis.

    A book's home spread is NEGATIVE when the home side is favoured; every
    football card helper takes a HOME MARGIN, positive when home is favoured.
    Skipping the negation produces entirely plausible numbers pointing at the
    wrong team, and nothing downstream can detect it.
    """
    margin, total = nfl_cards._nfl_market_margin_and_total(
        {"run_line": {"home": -3.5}, "total_runs": {"line": 44.5}}
    )
    assert margin == 3.5
    assert total == 44.5
    assert nfl_cards._nfl_market_margin_and_total({}) == (None, None)
    assert nfl_cards._nfl_market_margin_and_total(None) == (None, None)


def test_cover_and_over_publish_only_when_a_real_line_and_a_real_stdev_exist():
    projection = _Projection()
    with_line = football_shared_predictions(projection, market_margin=3.5, market_total=44.5)
    assert with_line["probabilities"]["home_cover"] is not None
    assert with_line["probabilities"]["total_over"] is not None
    # Complements, not two independent estimates.
    assert round(with_line["probabilities"]["home_cover"] + with_line["probabilities"]["away_cover"], 6) == 1.0

    without_line = football_shared_predictions(projection)
    assert without_line["home_mean"] == 24.0, "the means must publish without a line"
    assert without_line["probabilities"]["home_cover"] is None, "absent must stay absent, never 0.5"
    assert without_line["probabilities"]["total_over"] is None

    no_stdev = football_shared_predictions(
        _Projection(margin_stdev=None, total_stdev=None), market_margin=3.5, market_total=44.5
    )
    assert no_stdev["probabilities"]["home_cover"] is None, (
        "a point estimate is not a distribution and must never become a percentage"
    )


def test_cover_probability_points_the_right_way():
    # Home projected to win by 4; a -1 line (home margin 1) should be likelier
    # to cover than a +10 one.
    easy = cover_probability(line=1.0, mean=4.0, stdev=13.0)
    hard = cover_probability(line=10.0, mean=4.0, stdev=13.0)
    assert easy > 0.5 > hard


def test_the_market_tiles_show_the_book_against_the_model():
    tiles = football_market_tiles(
        home_team="SEA",
        away_team="NE",
        market_margin=3.5,
        market_total=44.5,
        model_margin=0.3,
        model_total=43.9,
        home_win_rate=0.507,
    )
    labels = [tile["label"] for tile in tiles]
    assert labels == ["Spread", "Total", "Win probability", "Books"]
    assert tiles[0]["title"] == "SEA -3.5"
    assert "vs market" in tiles[0]["sub"]
    assert "vs market" in tiles[1]["sub"]
    # NFL's old tiles were Home mean / Away mean / Projected spread / Win
    # probability -- byte-identical to the card's own `metrics` list.
    assert "Home mean" not in labels and "Away mean" not in labels


def test_a_missing_line_says_so_rather_than_showing_a_dash():
    tiles = football_market_tiles(home_team="SEA", away_team="NE", model_margin=0.3, model_total=43.9)
    assert tiles[0]["title"] == "No line"
    assert tiles[1]["title"] == "No line"


def test_kickoff_labels_are_central_and_windows_portable():
    # 00:20Z on the 10th is 19:20 CDT on the 9th.
    assert format_kickoff_label("2026-09-10T00:20:00Z") == "Wed Sep 9, 7:20 PM CDT"
    assert format_kickoff_label("") == ""
    assert format_kickoff_label("not a timestamp") == "not a timestamp"


# ------------------------------------------------------------- the live state


def _espn_state(**overrides) -> dict:
    state = {
        "event_id": "401873271",
        "away_abbr": "NE",
        "home_abbr": "SEA",
        "in_progress": False,
        "final": False,
        "status": "9/9 - 8:20 PM EDT",
        "period": None,
        "clock": "",
        "away_pts": None,
        "home_pts": None,
        "start_time": "2026-09-10T00:20Z",
    }
    state.update(overrides)
    return state


def test_a_started_nfl_game_takes_espns_status_and_a_pregame_one_does_not():
    """The latent half of the parity gap, and the reason it had to be found
    before kickoff rather than during it.

    NCAAF has stamped `status` since 2026-08-29 and NFL did not, so on
    2026-09-07 the two served payloads read `"Final"`/`"14:40 - 3rd"` and
    `"Week 1" x16`. NFL's slate was genuinely pregame that day -- the defect
    was invisible and would have surfaced as a live card whose header said
    "Week 1" while the clock ran.
    """
    live = {"gamePk": "g", "status": "Week 1", "away": {"abbr": "NE"}, "home": {"abbr": "SEA"}}
    index = {"g": _espn_state(in_progress=True, status="14:55 - 2nd", period=2, clock="14:55",
                              away_pts=7, home_pts=3)}
    coverage = attach_nfl_live_game_state([live], index)
    assert coverage["live"] == 1
    assert live["status"] == "14:55 - 2nd"
    assert live["away"]["score"] == 7

    final = {"gamePk": "g", "status": "Week 1", "away": {"abbr": "NE"}, "home": {"abbr": "SEA"}}
    attach_nfl_live_game_state([final], {"g": _espn_state(final=True, status="Final",
                                                          away_pts=17, home_pts=24)})
    assert final["status"] == "Final"

    pregame = {"gamePk": "g", "status": "Week 1", "away": {"abbr": "NE"}, "home": {"abbr": "SEA"}}
    attach_nfl_live_game_state([pregame], {"g": _espn_state()})
    assert pregame["status"] == "Week 1", (
        "a pregame card keeps its week label -- ESPN's pregame shortDetail is a "
        "date string and the strip already shows a formatted kickoff"
    )


def test_the_live_lens_eyebrow_says_what_the_game_is_doing():
    live = {"live_state": {"in_progress": True, "period": 3, "clock": "4:12"}}
    assert nfl_live_lens._game_state_label(live) == ("Q3 · 4:12", "live")

    final = {"live_state": {"final": True}}
    assert nfl_live_lens._game_state_label(final) == ("Final", "final")

    pregame = {"nfl_card": {"scoreboard": {"kickoff_label": "Wed Sep 9, 7:20 PM CDT"}}, "status": "Week 1"}
    assert nfl_live_lens._game_state_label(pregame) == ("Wed Sep 9, 7:20 PM CDT", "pregame")


def test_the_live_lens_reads_the_fresh_live_state_not_the_stale_shared_block():
    """`apply_game_board_contract` derives `shared_game_state` when the CARDS
    context is built; `_apply_live_state_to_game` overlays fresh ESPN state
    afterwards and does not re-derive it. Reading the shared block first would
    make the label most wrong on exactly the rows that just went live."""
    game = {
        "live_state": {"in_progress": True, "period": 3, "clock": "4:12"},
        "shared_game_state": {"live": False, "final": False, "status": "Week 1"},
    }
    assert nfl_live_lens._game_state_label(game)[1] == "live"


def test_the_live_lens_counts_the_slate_by_phase():
    games = [
        {"live_state": {"in_progress": True, "period": 1, "clock": "9:00"}},
        {"live_state": {"final": True}},
        {"live_state": {"final": True}},
        {"status": "Week 1"},
    ]
    assert nfl_live_lens._phase_counts(games) == {"live": 1, "final": 2, "pregame": 1}


# ------------------------------------------- box score + props on the football card


def _game_with_shared_sections(**overrides):
    game = _nfl_game()
    game["shared_box_sections"] = [
        {"title": "Projected box", "body": "Simulated drive totals.",
         "columns": ["Team", "Pts"], "table_rows": [["NE", "21.8"], ["SEA", "22.0"]]},
    ]
    game["shared_prop_rows"] = [
        {"name": "A.J. Brown — Receiving Yards", "detail": "Over 68.5 (-110)"},
    ]
    game["shared_prop_status_rows"] = game["shared_prop_rows"]
    game.update(overrides)
    return game


def test_the_football_card_renders_a_box_score_and_a_props_panel():
    """THE REGRESSION THIS PINS WAS MINE, and it shipped for several hours.

    Moving NFL onto the football partial dropped two tabs the GENERIC partial
    had been rendering. Measured on the same served NFL game, both partials:

        generic   panels = game, boxscore, props, panels
        football  panels = identity, context, coverage, details

    The data was never missing: `shared_prop_rows`, `shared_box_sections` and
    `shared_period_rows` were all 16/16 non-empty on the served NFL payload.
    I measured card HEIGHTS, crests and prose blocks when making that switch and
    never enumerated the PANELS I was trading away -- a parity check that
    compares presentation and not capability.
    """
    html = _env().get_template("shared/_game_card_ncaaf.html").render(
        game=_game_with_shared_sections()
    )
    assert 'data-panel-id="boxscore"' in html
    assert 'data-panel-id="props"' in html
    assert 'data-tab-target="boxscore"' in html
    assert 'data-tab-target="props"' in html
    assert "A.J. Brown" in html


def test_a_panel_exists_iff_a_tab_addresses_it_on_both_sports():
    """This card's own rule, and the first cut of the port broke it: the TABS
    were gated on `box_sections`/`prop_rows` and the PANELS were not, so an
    NCAAF game with no props rendered an orphan `props` panel -- markup shipped
    to the browser that nothing can reach. Same defect this file's header
    records collapsing a card on 2026-08-14."""
    import re

    for game in (
        _game_with_shared_sections(),                      # both sections
        _game_with_shared_sections(shared_prop_rows=[]),   # box only
        _game_with_shared_sections(shared_box_sections=[], shared_prop_rows=[]),  # neither
    ):
        html = _env().get_template("shared/_game_card_ncaaf.html").render(game=game)
        tabs = set(re.findall(r'data-tab-target="([a-z-]+)"', html))
        panels = set(re.findall(r'data-panel-id="([a-z-]+)"', html))
        assert tabs == panels, f"orphans: tabs-only={tabs - panels} panels-only={panels - tabs}"


def test_the_sections_are_contract_based_not_mlb_shaped():
    """One port serves both football codes because it reads the CROSS-SPORT
    keys, not MLB's. MLB's own panels read `actual_box`'s batting/pitching
    columns and an R/H/E linescore -- football has none of those, and copying
    them would have produced a card that renders nothing."""
    source = (TEMPLATE_ROOT / "shared" / "_game_card_ncaaf.html").read_text(encoding="utf-8")
    for key in ("shared_box_sections", "shared_prop_rows", "shared_prop_status_rows"):
        assert key in source, key
    for mlb_only in ("batting_columns", "pitching_columns", "cards-linescore"):
        assert mlb_only not in source, f"MLB-shaped markup leaked in: {mlb_only}"
