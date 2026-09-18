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
        # Each block carries the denominator it was measured on: margins the
        # 2024 backtest, totals the 2026 closes.
        assert note["sample_games"] == (100 if market == "totals" else 2233)
        assert note["verdict"]


def test_margin_note_carries_the_measured_loss():
    note = gp.skill_note("spreads")
    assert note["model_mae"] == 15.775
    assert note["market_mae"] == 12.212
    assert note["delta_mae"] == 3.563
    assert note["model_mae"] > note["market_mae"], "the model is the WORSE of the two"


def test_margin_note_carries_the_2026_season_and_the_tooltip_quotes_it():
    """The 2024 gap lies outside the 2026 CI, so the row leads with 2026."""
    note = gp.skill_note("spreads")
    assert note["delta_mae_2026"] == 1.75
    assert note["ci95_2026"][0] > 0, "the 2026 loss excludes zero"
    assert note["sample_games_2026"] == 100
    reason = gp._skill_reason(note)
    assert "1.75" in reason and "this season" in reason
    assert "3.563" in reason, "the backtest stays beside it"


def test_totals_note_carries_the_measured_loss_against_the_close():
    """`[2026-09-14]` totals were scored against the close for the first time.
    Still no correlation FIELD -- the measurement is MAE against the line."""
    note = gp.skill_note("totals")
    assert "correlation" not in note
    assert note["delta_mae"] == 2.864
    assert note["model_mae"] > note["market_mae"], "the model is the WORSE of the two"
    assert note["ci95"][0] > 0
    assert note["dispersion_ratio"] == 2.48
    assert "never scored" not in note["verdict"]


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


def _two_sided_grid():
    """Grid rows as `book_grid` builds them: canonical AWAY/OVER line, both
    sides quoted in `consensus`. TCU (home) -15 is away +15."""
    base = {
        "kind": "game",
        "segment": "full",
        "commence_time": "2026-08-29T16:00:00Z",
        "home_team": "TCU Horned Frogs",
        "away_team": "North Carolina Tar Heels",
        "sides": ["away", "home"],
    }
    return [
        {**base, "market": "h2h", "consensus": {"away": 260, "home": -320}},
        {**base, "market": "spreads", "line": 15.0, "consensus": {"away": -110, "home": -110}},
        {**base, "market": "totals", "line": 43.0, "sides": ["over", "under"], "consensus": {"over": -110, "under": -110}},
    ]


def test_every_market_publishes_its_projection_2026_09_18():
    """USER DECISION 2026-09-18: "they should be shown, period ... we shouldnt be
    hiding anything globally". Spreads used to publish `projected: None` while
    the sim held a margin -- 154 FBS spread rows read "no sim view" that day."""
    grid = _two_sided_grid()
    gp.attach_ncaaf_game_projections(grid, _index())
    by_market = {r["market"]: r["projection"] for r in grid}
    # Home minus away, the frame MLB and NFL spread rows already publish.
    assert by_market["spreads"]["projected"] == pytest.approx(10.263)
    assert by_market["totals"]["projected"] == pytest.approx(50.337)
    assert by_market["h2h"]["model_prob_over"] == pytest.approx(0.80)
    for projection in by_market.values():
        # The measurement still travels on every row -- it is what
        # `_apply_skill_reliability` demotes the score by.
        assert projection["model_skill"]
        assert projection.get("probability_unavailable_reason") is None


def test_spread_probability_is_home_covering_the_AWAY_FRAME_line():
    """`book_grid._canonical_line` states the away line. Away +15 means home
    -15, and home covers when margin > +15 -- NOT margin > -15, which is the
    inversion that once put 0.74 on MLB underdogs."""
    import math

    grid = _two_sided_grid()
    gp.attach_ncaaf_game_projections(grid, _index())
    spread = next(r["projection"] for r in grid if r["market"] == "spreads")
    expected = 0.5 * math.erfc(((15.0 - 10.263) / 13.291) / math.sqrt(2.0))
    assert spread["model_prob_over"] == pytest.approx(expected, abs=1e-4)
    assert spread["model_prob_over"] < 0.5, "a 10-point favourite does not cover 15 more often than not"
    assert spread["side"] == "TCU Horned Frogs"


def test_every_two_sided_pregame_row_carries_an_edge():
    """"Publish, skill-discounted" (2026-09-18). 0 of 938 NCAAF rows carried
    `model_edge_pct` on the served board that morning."""
    grid = _two_sided_grid()
    gp.attach_ncaaf_game_projections(grid, _index())
    for row in grid:
        projection = row["projection"]
        fair = projection["market_fair_prob_over"]
        assert fair is not None, row["market"]
        assert projection["edge_vs_market_pct"] == pytest.approx(
            (projection["model_prob_over"] - fair) * 100.0, abs=0.02
        )


def test_a_one_sided_row_names_why_it_has_no_edge():
    grid = _grid()  # no `sides`/`consensus`: nothing to de-vig
    gp.attach_ncaaf_game_projections(grid, _index())
    for row in grid:
        assert row["projection"]["edge_vs_market_pct"] is None
        assert "both sides" in row["projection"]["edge_unavailable_reason"]


def test_a_live_row_gets_no_pregame_edge():
    """`live_edge_policy`: a pregame projection priced against a market that has
    watched the game is the score, not an edge."""
    # `live_edge_policy.game_state_of` reads the chip block grid rows carry.
    grid = [dict(row, game={"state": "live"}) for row in _two_sided_grid()]
    gp.attach_ncaaf_game_projections(grid, _index())
    for row in grid:
        assert row["projection"]["edge_vs_market_pct"] is None
        assert row["projection"]["edge_unavailable_reason"]
        # The projection itself is still shown.
        assert row["projection"]["model_prob_over"] is not None


def test_totals_keep_the_line_diagnostic():
    grid = _two_sided_grid()
    gp.attach_ncaaf_game_projections(grid, _index())
    totals = next(r["projection"] for r in grid if r["market"] == "totals")
    assert totals["edge_vs_line"] == pytest.approx(7.337)
    assert totals["model_skill"]["verdict"].startswith("loses to the closing line")


# --------------------------------------------------------------------------
# the join -- neutral sites, moved kickoffs, games the schedule copy predates
# --------------------------------------------------------------------------

def test_a_neutral_site_game_listed_the_other_way_round_joins_FLIPPED():
    """MEASURED 2026-09-18: CFBD `Arizona State @ Kansas` (Wembley) and
    `West Virginia @ Virginia` (Charlotte), both `neutralSite: true`; OddsAPI
    lists both reversed, and both FBS games carried no model."""
    idx = _index()  # CFBD frame: TCU home, North Carolina away
    entry = idx.lookup("2026-08-29", "North Carolina Tar Heels", "TCU Horned Frogs")
    assert entry is not None
    assert entry["orientation_flipped"] is True
    assert entry["margin_mean"] == pytest.approx(-10.263)
    assert entry["home_win_rate"] == pytest.approx(0.20)

    grid = [
        {
            "kind": "game", "segment": "full", "market": "h2h",
            "commence_time": "2026-08-29T16:00:00Z",
            "home_team": "North Carolina Tar Heels", "away_team": "TCU Horned Frogs",
            "sides": ["away", "home"], "consensus": {"away": -320, "home": 260},
        }
    ]
    gp.attach_ncaaf_game_projections(grid, idx)
    projection = grid[0]["projection"]
    assert projection["model_prob_over"] == pytest.approx(0.20)
    assert projection["side"] == "North Carolina Tar Heels"
    assert projection["orientation_flipped"] is True


def test_a_kickoff_moved_by_a_day_still_joins_and_says_so():
    """North Texas @ Texas State: `2026-09-20T02:00Z` in the schedule copy the
    join reads, `2026-09-19T16:00Z` on the board."""
    idx = _index()
    entry = idx.lookup("2026-08-30", "TCU Horned Frogs", "North Carolina Tar Heels")
    assert entry is not None
    assert entry["kickoff_date_shifted"] is True
    exact = idx.lookup("2026-08-29", "TCU Horned Frogs", "North Carolina Tar Heels")
    assert exact["kickoff_date_shifted"] is False


def test_an_undated_projection_joins_on_the_pair():
    idx = gp.NcaafGameProjectionIndex()
    idx.undated[("tcu", "north carolina")] = {"margin_mean": 3.0, "home_win_rate": 0.6, "total_mean": 50.0}
    entry = idx.lookup("2026-08-29", "North Carolina Tar Heels", "TCU Horned Frogs")
    assert entry is not None and entry["margin_mean"] == pytest.approx(-3.0)


def _fake_schedule_and_csv(monkeypatch, tmp_path, schedule, csv_rows):
    import shutil

    from syndicate.features.football.sim_engine.smartsim2.historical_truth import ncaaf_historical_loader
    from syndicate.features.ncaaf import oddsapi_lines, sources

    # The team resolver reads its registry from the SAME source root, so the
    # fake root carries a copy of the real one -- and the resolver's caches are
    # cleared first, or this test would pass or fail on whichever test happened
    # to warm them (measured: it passed in the file and failed alone). What
    # they then cache is the same registry's content, so nothing leaks.
    registry = sources.team_registry_snapshot_path()
    fake_registry = tmp_path / registry.relative_to(sources.default_ncaaf_source_root())
    fake_registry.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(registry, fake_registry)
    for cached in (oddsapi_lines.fbs_canonical_names, oddsapi_lines._alias_map, oddsapi_lines._mascot_tails):
        cached.cache_clear()
    monkeypatch.setattr(ncaaf_historical_loader, "load_games_season", lambda season: schedule)
    monkeypatch.setattr(sources, "default_ncaaf_source_root", lambda: tmp_path)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    header = "game_id,season,week,home_team,away_team,margin_mean,total_mean,margin_stdev,total_stdev,home_win_rate,profile_name,generated_at"
    lines = [header] + [
        f"{i},2026,3,{home},{away},{m},50.0,13.0,11.0,{w},ncaaf_v2,2026-09-18T00:00:00Z"
        for i, (home, away, m, w) in enumerate(csv_rows)
    ]
    (tmp_path / "data" / "smartsim2_projections_2026_wk3.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _game(home, away, start, week=3, home_class="fbs", away_class="fbs"):
    return {
        "homeTeam": home, "awayTeam": away, "startDate": start, "week": week,
        "homeClassification": home_class, "awayClassification": away_class,
    }


def test_load_indexes_moved_swapped_and_unscheduled_games(monkeypatch, tmp_path):
    """The three shapes of 2026-09-18's 27 unjoined FBS rows, end to end
    through `load_ncaaf_game_projections`."""
    schedule = [
        _game("TCU", "Baylor", "2026-09-19T16:00:00.000Z"),           # anchors the week on the date
        _game("Texas State", "North Texas", "2026-09-20T02:00:00.000Z"),  # moved kickoff (stale copy)
        _game("Kansas", "Arizona State", "2026-09-19T16:00:00.000Z"),     # neutral site, CFBD frame
        _game("Oregon", "Portland State", "2026-09-19T20:00:00.000Z", away_class="fcs"),
    ]
    csv_rows = [
        ("TCU", "Baylor", 7.0, 0.7),
        ("Texas State", "North Texas", 2.0, 0.55),
        ("Kansas", "Arizona State", -4.0, 0.38),
        ("Fresno State", "San José State", 1.5, 0.52),  # absent from the stale schedule
    ]
    _fake_schedule_and_csv(monkeypatch, tmp_path, schedule, csv_rows)
    idx = gp.load_ncaaf_game_projections("2026-09-19")

    moved = idx.lookup("2026-09-19", "Texas State Bobcats", "North Texas Mean Green")
    assert moved is not None and moved["kickoff_date_shifted"] is True

    swapped = idx.lookup("2026-09-19", "Arizona State Sun Devils", "Kansas Jayhawks")
    assert swapped is not None and swapped["margin_mean"] == pytest.approx(4.0)

    unscheduled = idx.lookup("2026-09-19", "Fresno State Bulldogs", "San Jose State Spartans")
    assert unscheduled is not None and unscheduled["margin_mean"] == pytest.approx(1.5)

    # The FCS boundary is untouched, and explained in either orientation.
    assert idx.lookup("2026-09-19", "Portland State Vikings", "Oregon Ducks") is None
    assert "FCS" in (idx.unratable_reason("2026-09-19", "Portland State Vikings", "Oregon Ducks") or "")
    # Still a per-date rate: the moved game is keyed on the 20th.
    assert idx.unratable_games == 1


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
