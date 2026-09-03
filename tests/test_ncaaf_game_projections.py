"""`#555` -- SmartSim 2.0 on the NCAAF Layer 1 board, with its measurement attached.

The point of these tests is not that a number appears. It is that the number
appears WITH the caveat the measurement requires, and in the one field the board
can actually show, because this model is recorded as losing to the closing line.
"""

from __future__ import annotations

import pytest

from syndicate.features.ncaaf import game_projections as gp


# --------------------------------------------------------------------------
# the measurement itself
# --------------------------------------------------------------------------

def test_skill_note_is_never_absent():
    """NFL's equivalent returns None for profiles it has not measured. This one
    must not: `pick_gate.py`'s whole argument is that an absent measurement is
    indistinguishable from an unmeasured loss, so there is no "this one is fine"
    branch to fall through."""
    for market in ("h2h", "spreads", "totals", "", None, "anything"):
        note = gp.skill_note(market)
        assert note, market
        assert note["sample_games"] == 2233
        assert note["verdict"]


def test_margin_note_carries_the_measured_loss():
    note = gp.skill_note("spreads")
    assert note["model_mae"] == 15.775
    assert note["market_mae"] == 12.212
    assert note["delta_mae"] == 3.563
    assert note["model_mae"] > note["market_mae"], "the model is the WORSE of the two"


def test_totals_note_reports_dispersion_not_a_correlation():
    """There is no totals correlation to report -- NCAAF totals were never
    scored against the close. Claiming one would be inventing a measurement."""
    note = gp.skill_note("totals")
    assert "correlation" not in note
    assert note["dispersion_ratio"] == 1.67
    assert note["model_sd"] > note["market_sd"]


# --------------------------------------------------------------------------
# the index
# --------------------------------------------------------------------------

def _index(entry=None):
    idx = gp.NcaafGameProjectionIndex()
    idx.by_date_teams[("2026-08-29", "tcu", "north carolina")] = entry or {
        "margin_mean": 10.263,
        "margin_stdev": 13.291,
        "total_mean": 50.337,
        "total_stdev": 11.719,
        "home_win_rate": 0.80,
        "profile": "ncaaf_v2",
        "generated_at": "2026-08-19T22:00:39Z",
    }
    idx.games = 1
    return idx


def test_lookup_resolves_the_boards_oddsapi_names():
    """The grid carries OddsAPI names with mascots; the sim carries CFBD names.
    Without the resolver these never meet."""
    idx = _index()
    assert idx.lookup("2026-08-29", "TCU Horned Frogs", "North Carolina Tar Heels") is not None


def test_lookup_refuses_an_unresolvable_team_rather_than_guessing():
    idx = _index()
    assert idx.lookup("2026-08-29", "Bulldogs", "North Carolina Tar Heels") is None
    assert idx.lookup("2026-08-29", "TCU Horned Frogs", "Not A Real School") is None


def test_lookup_is_date_scoped():
    """A week spans ten days; a projection must not leak onto another day's row."""
    idx = _index()
    assert idx.lookup("2026-09-05", "TCU Horned Frogs", "North Carolina Tar Heels") is None


@pytest.mark.parametrize(
    "date_str,expected",
    [("2026-08-29", 2026), ("2026-12-31", 2026), ("2027-01-08", 2026), ("2027-02-01", 2026), ("", None)],
)
def test_season_for_date_keeps_january_with_the_season_that_started_it(date_str, expected):
    """Bowls and the playoff fall in January. Reading 2027-01-08 as season 2027
    would look for a week that does not exist and silently return nothing."""
    assert gp._season_for_date(date_str) == expected


# --------------------------------------------------------------------------
# the attach -- what the board actually receives
# --------------------------------------------------------------------------

def _grid():
    base = {
        "kind": "game",
        "segment": "full",
        "commence_time": "2026-08-29T16:00:00Z",
        "home_team": "TCU Horned Frogs",
        "away_team": "North Carolina Tar Heels",
    }
    return [
        {**base, "market": "h2h", "side": "home", "price": -320},
        {**base, "market": "spreads", "side": "home", "line": -15.0, "price": -110},
        {**base, "market": "totals", "side": "over", "line": 43.0, "price": -110},
    ]


def test_every_projection_is_labelled_ncaaf_not_nfl():
    """`nfl_game_projections` hardcodes `source: nfl_smartsim2` three times.
    Routing NCAAF through it would stamp NFL's provenance onto these rows --
    learnings.md 2026-08-21, a value published under another quantity's name."""
    grid = _grid()
    gp.attach_ncaaf_game_projections(grid, _index())
    for row in grid:
        assert row["projection"]["source"] == "ncaaf_smartsim2"


def test_every_projection_carries_its_measurement():
    grid = _grid()
    coverage = gp.attach_ncaaf_game_projections(grid, _index())
    assert coverage["rows_with_projection"] == 3
    for row in grid:
        assert row["projection"]["model_skill"], row["market"]
    # And on the coverage payload too, so a consumer reading only the summary
    # cannot treat these as ordinary edges.
    assert coverage["model_skill"]["margins"]["delta_mae"] == 3.563


def test_margin_backed_markets_publish_no_bare_projection():
    """A bare number in a column headed PROJECTED has nowhere to carry a caveat,
    so where the model has no measured skill the honest value is none. Same
    resolution `#377` reached for NFL."""
    grid = _grid()
    gp.attach_ncaaf_game_projections(grid, _index())
    by_market = {r["market"]: r["projection"] for r in grid}
    assert by_market["h2h"]["projected"] is None
    assert by_market["spreads"]["projected"] is None
    # The PROBABILITY survives -- it has somewhere to carry the caveat, and
    # pick_gate.py needs the model visible for the measurement that lifts it.
    assert by_market["h2h"]["model_prob_over"] == pytest.approx(0.80)


def test_the_caveat_rides_on_the_field_the_board_can_show():
    """THE FIELD NAME IS THE WHOLE FIX.

    `layer1_board.html` renders the EDGE cell with a hover title when
    `edge_unavailable_reason` is set. The PROJ cell has no tooltip channel and
    `model_skill` is rendered nowhere, so a reason placed anywhere else is
    payload-only -- a stated refusal nobody can read. Verified against the real
    board: 12 elements carried the tooltip.
    """
    grid = _grid()
    gp.attach_ncaaf_game_projections(grid, _index())
    for row in grid:
        reason = row["projection"].get("edge_unavailable_reason")
        assert reason, row["market"]
        assert "closing line" in reason or "over-dispersed" in reason


def test_totals_keep_the_mean_but_publish_no_percentage_edge():
    """The mean is the model's own statement and is not itself inflated. The
    EDGE derived from it is: pricing a line against a 1.67x over-dispersed
    distribution manufactures conviction."""
    grid = _grid()
    gp.attach_ncaaf_game_projections(grid, _index())
    totals = next(r["projection"] for r in grid if r["market"] == "totals")
    assert totals["projected"] == pytest.approx(50.337)
    assert totals["edge_vs_market_pct"] is None
    assert "over-dispersed" in totals["edge_unavailable_reason"]
    # The raw diagnostic survives so an auditor can still see the input.
    assert totals["edge_vs_line"] == pytest.approx(7.337)


def test_non_full_segments_are_skipped():
    """A first-quarter total is a different bet from a full-game mean."""
    grid = [dict(_grid()[2], segment="q1")]
    coverage = gp.attach_ncaaf_game_projections(grid, _index())
    assert coverage["rows_with_projection"] == 0
    assert coverage["rows_non_full_segment"] == 1


def test_props_and_unmatched_games_are_left_alone():
    grid = [
        dict(_grid()[0], kind="prop"),
        dict(_grid()[0], home_team="Some Unknown Academy"),
    ]
    coverage = gp.attach_ncaaf_game_projections(grid, _index())
    assert coverage["rows_with_projection"] == 0
    assert coverage["rows_unmatched"] == 1


def test_board_enrichment_routes_ncaaf_here_rather_than_reporting_no_source():
    """Reachability: the dispatch used to fall through to
    `no_projection_source_for_sport`, which is what left Proj/Edge dead."""
    from syndicate.features.shared import board_enrichment

    coverage = board_enrichment._attach_projections_by_sport(
        [], sport="ncaaf", selected_date="2026-08-29"
    )
    assert coverage.get("supported") is True
    assert coverage.get("reason") != "no projection source wired for ncaaf"


# --------------------------------------------------------------------------
# Layer 2 -- does the priced board actually generate candidates?
# --------------------------------------------------------------------------

def _priced_card():
    """The shape `_game_bet_candidates_from_game` reads, as the NCAAF card now
    emits it."""
    return {
        "gamePk": "1_North_Carolina_TCU",
        "summary": "TCU vs North Carolina",
        "home": {"name": "TCU", "abbr": "TCU"},
        "away": {"name": "North Carolina", "abbr": "NC"},
        "betting": {
            "home_ml": -320,
            "away_ml": 260,
            "home_spread": -14.875,
            "away_spread": 14.875,
            "total": 43.75,
            "p_home_win": 0.80,
            "p_away_win": 0.20,
            "p_home_cover": 0.364,
            "p_away_cover": 0.636,
            "p_total_over": 0.713,
            "p_total_under": 0.287,
        },
    }


def test_the_betting_block_generates_layer2_candidates():
    """REACHABILITY, and the reason this block exists at all.

    Production measured `GAME_CANDIDATES_EXIT sport=ncaaf rows=0` with
    `game_candidate_inputs blocks={betting: 0, ...}` -- the card emitted no
    `betting` block, so the moneyline and total branches of
    `_game_bet_candidates_from_game` had nothing to read and Layer 2 produced
    nothing for NCAAF at all.
    """
    from syndicate.blueprints.home import _game_bet_candidates_from_game

    sport = {"slug": "ncaaf", "name": "NCAAF"}
    rows = _game_bet_candidates_from_game(sport, _priced_card(), fallback_epoch=0.0)
    markets = sorted({r.get("market") for r in rows})
    assert "Moneyline" in markets
    assert "Total" in markets
    assert len(rows) >= 4, rows

    # OFF: strip the block and the same card yields nothing.
    bare = _priced_card()
    bare.pop("betting")
    assert _game_bet_candidates_from_game(sport, bare, fallback_epoch=0.0) == []


def test_no_ev_is_fabricated_from_a_model_that_loses_to_the_close():
    """`_append_game_bet_candidate` takes `edge=betting.get("*_ev")`. Those
    fields are deliberately NOT emitted.

    An EV computed from a model measured at 15.775 MAE against the market's
    12.212 would be a manufactured number, and Layer 2 ranks on edge. The model
    PROBABILITY is carried instead, which is the same treatment Layer 1 gives it
    -- visible, with its measurement, and not presented as a tradeable edge.
    `pipeline/layer2_shortlist.py` refuses such rows downstream with
    `no_model_edge_pct`, so they show on the board and cannot be traded.
    """
    card = _priced_card()
    for key in card["betting"]:
        assert not key.endswith("_ev"), key


def test_spread_candidates_need_a_key_this_card_deliberately_does_not_set():
    """A FINDING PINNED AS A TEST, not a fix.

    `_game_bet_candidates_from_game` gates its Spread branch on
    `betting["home_puck_line"]`/`["away_puck_line"]` -- the MARKET line -- while
    reading `betting["home_spread"]` as the model's PROJECTED spread. But
    `publication_adapter._shared_markets` reads that same `home_spread` as the
    MARKET spread, and that is what makes the cards board's market block
    correct.

    One key, two meanings, two consumers. Setting `*_puck_line` here would
    generate Spread rows whose `projected` was the market line wearing the
    model's label. Resolving that collision is a shared-contract change across
    every sport, so this asserts the current, honest state instead: no Spread
    candidate rather than a mislabelled one.
    """
    from syndicate.blueprints.home import _game_bet_candidates_from_game

    card = _priced_card()
    assert "home_puck_line" not in card["betting"]
    rows = _game_bet_candidates_from_game({"slug": "ncaaf"}, card, fallback_epoch=0.0)
    assert "Spread" not in {r.get("market") for r in rows}


def _grid_on(date_iso: str):
    """`_grid()` shifted to another kickoff date, same fixture."""
    return [{**row, "commence_time": date_iso + "T16:00:00Z"} for row in _grid()]


def test_rows_from_ANOTHER_DATE_do_not_inflate_considered() -> None:
    """The counting bug that made a 47% join read as 9.3%.

    `_attach_projections_over_window` calls this once per date in NCAAF's 7-day
    window with the SAME unfiltered grid, and the wrapper SUMS `rows_considered`.
    A row from another date can never match this date's index, so counting it
    here inflates the denominator on every pass while `rows_with_projection`
    stays honest. Measured 2026-09-03: `considered=3625`, and 3625 / 5 non-empty
    dates = 725 -- exactly the shared grid's size.
    """
    grid = _grid() + _grid_on("2026-09-05")
    coverage = gp.attach_ncaaf_game_projections(
        grid, _index(), selected_date="2026-08-29"
    )
    assert coverage["rows_considered"] == 3, "only this date's rows are in scope"
    assert coverage["rows_with_projection"] == 3


def test_without_selected_date_the_old_behaviour_is_UNCHANGED() -> None:
    """The scoping is opt-in, so no existing caller silently changes meaning.
    `board_enrichment`'s NCAAF branch -- the one production caller -- passes it."""
    grid = _grid() + _grid_on("2026-09-05")
    coverage = gp.attach_ncaaf_game_projections(grid, _index())
    assert coverage["rows_considered"] == 6


def test_scoping_moves_the_COUNTERS_and_not_the_ATTACHMENT() -> None:
    """A skipped row would have failed `index.lookup` on this date anyway, so no
    row gains or loses a projection because of this change."""
    unscoped = _grid() + _grid_on("2026-09-05")
    scoped = _grid() + _grid_on("2026-09-05")
    gp.attach_ncaaf_game_projections(unscoped, _index())
    gp.attach_ncaaf_game_projections(scoped, _index(), selected_date="2026-08-29")
    assert [("projection" in r) for r in unscoped] == [("projection" in r) for r in scoped]
