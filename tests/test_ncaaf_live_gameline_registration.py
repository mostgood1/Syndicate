"""The interlock, end to end: a live NCAAF edge exists ONLY on a live probability.

`presence != reachability`. The re-sim can be correct and the join can accept its
stamp while the board still suppresses every row, because the release is
`live_edge_policy`'s and it keys on `projection.live_aware` -- a field only
`_apply_verdict` sets. This walks the whole chain with the real functions:

    live_resim.build_game_lens
      -> build_live_gameline_index      (does the stamp index?)
      -> attach_live_gamelines          (does the row get priced?)
      -> live_edge_policy               (is the edge released?)

and asserts the OPPOSITE outcome for a refused game, which is the half that
`#414` got wrong.
"""
from __future__ import annotations

from syndicate.features.ncaaf import live_resim as lr
from syndicate.features.shared.board_enrichment import _LIVE_GAMELINE_SPORTS
from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason
from syndicate.features.shared.live_gameline_join import (
    attach_live_gamelines,
    build_live_gameline_index,
    lens_sources_for_sport,
)

AWAY, HOME = "Boise State", "Oregon"


def _grid_row(*, state="live", age_seconds=30.0):
    """One live h2h row shaped like the board's, with a de-vigged market prob.

    `market_fair_prob_over` is the de-vigged HOME probability on an h2h row --
    read, not recomputed, exactly as `attach_live_gamelines` does.

    `age_seconds` IS NOT OPTIONAL FURNITURE. The staleness gate sits above the
    market branch and refuses `quote_age_absent` outright, so a row without it
    is never priced -- which is how the first version of this test "passed" the
    refusal cases for a reason that had nothing to do with the re-sim.
    """
    return {
        "kind": "game",
        "market": "h2h",
        "segment": "full",
        "away_team": AWAY,
        "home_team": HOME,
        "age_seconds": age_seconds,
        "game": {"state": state},
        "projection": {
            "model_prob_over": 0.977,          # the PREGAME number, kept readable
            "market_fair_prob_over": 0.310,    # the market has re-priced on the score
            "basis": "smartsim2_home_win_rate",
        },
    }


def _snapshot(lanes):
    return {"games": [{"away_name": AWAY, "home_name": HOME, "gameLens": lanes}]}


def _index(lanes):
    return build_live_gameline_index(
        _snapshot(lanes), sources=lens_sources_for_sport("ncaaf"), sport="ncaaf"
    )


def _priced_lanes(sims=200):
    """A decided game, so the probability is 1.0 and the interval is ~0.

    Deliberately a blowout rather than a coin flip: `PRICEABLE_SIGMA` is a real
    gate and a mid-game 50/50 at n=200 would be refused as noise, which would
    make this test pass for the wrong reason.
    """
    state = lr.NcaafLiveGameState(away_team=AWAY, home_team=HOME, period=4,
                                  clock_seconds=20, home_score=45, away_score=10,
                                  possession_owner="home")
    result = lr.resim_live_game(state, home_offense=0.0, home_defense=0.0,
                                away_offense=0.0, away_defense=0.0, sims=sims)
    return lr.build_game_lens(state, result)


def test_the_board_gate_lists_ncaaf():
    """Without this, every test below is testing an unreachable code path."""
    assert "ncaaf" in _LIVE_GAMELINE_SPORTS


def test_the_pregame_row_alone_is_suppressed_which_is_the_correct_status_quo():
    """`#340`. This is what the board serves today, and it is right."""
    row = _grid_row()
    reason = live_edge_unavailable_reason(row)
    assert reason is not None
    assert "pregame projection cannot be priced against a live market" in reason


def test_a_live_resim_lane_indexes_prices_and_releases_the_edge():
    lanes = _priced_lanes()
    index = _index(lanes)
    assert len(index) == 1, "the live_resim stamp must index for ncaaf"

    row = _grid_row()
    coverage = attach_live_gamelines([row], index)
    assert coverage["index_size"] == 1

    projection = row["projection"]
    assert projection["live_aware"] is True
    assert projection["edge_vs_market_pct"] is not None
    # THE EDGE IS COMPUTED FROM THE LIVE PROBABILITY. 1.0 against a market still
    # saying 0.310 is 69.0 points; the pregame pairing (0.977 - 0.310) would be
    # 66.7 and is NOT what came out. This is the assertion that proves the live
    # number reached the price rather than merely being published beside it.
    assert round(projection["edge_vs_market_pct"], 1) == 69.0
    assert row["live_gameline"]["home_win_prob"] == 1.0
    assert projection["model_prob_over"] == 0.977, "the pregame number stays readable"

    # **FIXED 2026-09-05, and this assertion is the mutation check.** It used to
    # read `== "pregame"` and said so: `_apply_verdict` set
    # `edge_basis = "live" if live_projected is not None else "pregame"`, and the
    # MONEYLINE branch calls it WITHOUT `live_projected`, so the edge computed
    # from the live probability three lines up was labelled `pregame`.
    #
    # The label now comes from `verdict["model_prob"]` -- the probability the
    # edge was actually computed from -- rather than from `live_projected`,
    # which only ever decided whether to PUBLISH that probability. The moneyline
    # branch still publishes nothing (see the comment there), so this row
    # carries no `live_model_prob_over`; that is deliberate and is asserted
    # below rather than left as an accident.
    assert projection["edge_basis"] == "live"
    assert "live_model_prob_over" not in projection

    # And only now does the policy allow the edge through at all.
    assert live_edge_unavailable_reason(row) is None


def test_a_refused_lane_indexes_nothing_and_the_edge_stays_suppressed():
    """The half `#414` got wrong: no live probability must mean NO edge.

    The refusal lane carries the game's real identity and a stated reason, so
    the diagnostic can still see it -- and carries no probability at all, so
    there is nothing for the join to price.
    """
    lanes = lr.build_game_lens(None, lr.NcaafResimRefusal("no_pregame_ratings", "x"))
    assert _index(lanes) == {}

    row = _grid_row()
    coverage = attach_live_gamelines([row], _index(lanes))
    assert coverage["index_size"] == 0
    assert "live_aware" not in row["projection"]
    assert row["projection"]["model_prob_over"] == 0.977
    assert live_edge_unavailable_reason(row) is not None


def test_a_final_game_refuses_even_with_a_live_aware_projection():
    """A settled market has no price to beat, and freshness does not rescue it."""
    row = _grid_row(state="final")
    attach_live_gamelines([row], _index(_priced_lanes()))
    reason = live_edge_unavailable_reason(row)
    assert reason is not None
    assert "the market is settled" in reason


def test_the_refused_lane_is_still_visible_to_the_index_diagnostics():
    """"The producer never ran" and "it ran and refused" must not look alike."""
    diagnostics: dict = {}
    build_live_gameline_index(
        _snapshot(lr.build_game_lens(None, lr.NcaafResimRefusal("no_period", "y"))),
        sources=lens_sources_for_sport("ncaaf"),
        sport="ncaaf",
        diagnostics=diagnostics,
    )
    assert diagnostics["games_in_snapshot"] == 1
    assert diagnostics["sources_seen"] == {"pregame": 1}
    assert diagnostics["accepted_sources"] == ["live_resim"]


def test_the_staleness_gate_applies_to_ncaaf_too():
    """A dead quote is refused before any model reaches it, live probability or not.

    The gate is deliberately ABOVE the market branch, so registering a new sport
    cannot route around it. Both failure modes: absent, and simply too old.
    """
    index = _index(_priced_lanes())

    absent = _grid_row(age_seconds=None)
    attach_live_gamelines([absent], index)
    assert "live_aware" not in absent["projection"]
    assert live_edge_unavailable_reason(absent) is not None

    old_quote = _grid_row(age_seconds=99_999.0)
    attach_live_gamelines([old_quote], index)
    assert "live_aware" not in old_quote["projection"]
    assert live_edge_unavailable_reason(old_quote) is not None


# --- THE JOIN KEY ITSELF, which every test above takes on faith -----------------
#
# ADDED 2026-09-05 by lane `edge-basis-moneyline`, after lane `ncaaf-live-resim-wire`
# pointed out the shape and PRODUCTION proved it. Every test above builds BOTH
# sides of the join from the single `AWAY, HOME` pair (`_grid_row` at the
# `away_team`/`home_team` keys, `_snapshot` at `away_name`/`home_name`), so the
# key match is a tautology and this file's "end to end" claim never covered the
# one hop where the two sides come from DIFFERENT producers.
#
# What that hid, measured on production 2026-09-05 23:17:39Z: **257 of 257 rows
# missed** with a perfect index (`index_size 8`, `skipped_no_team_names 0`). The
# lens is keyed from the CFBD projections artifact and the grid from the ODDS
# source, and they spell teams differently -- `('baylor','auburn')` against
# `('baylor bears','auburn tigers')`. 18 green tests and a five-way mutation
# check did not see it, because no fixture ever let the two sides disagree.
#
# These two are a PAIR and only the pair means anything (`off != on`): the same
# grid row, joined against two lenses that differ ONLY in naming convention.

GRID_NAMES = ("Baylor Bears", "Auburn Tigers")   # how the ODDS source spells them
LENS_SHORT = ("Baylor", "Auburn")                # how the CFBD artifact spelled them


def _named_row(away, home):
    row = _grid_row()
    row["away_team"], row["home_team"] = away, home
    return row


def _named_index(away, home):
    snapshot = {"games": [{"away_name": away, "home_name": home,
                           "gameLens": _priced_lanes()}]}
    return build_live_gameline_index(
        snapshot, sources=lens_sources_for_sport("ncaaf"), sport="ncaaf"
    )


def test_a_naming_convention_mismatch_is_VISIBLE_and_never_a_silent_zero():
    """The producer ran, the join missed, and the counters MUST separate the two.

    This does not assert that short and long names match -- they must not, and
    nothing here fuzzy-matches. It asserts the failure is DIAGNOSABLE: an index
    that is non-empty next to zero edges and a named refusal is the signature
    that distinguishes "no producer" from "producer fine, key wrong". That
    distinction is what was missing while 257 of 257 rows missed in silence.
    """
    index = _named_index(*LENS_SHORT)
    assert len(index) == 1, "the producer ran -- this is not an empty-index case"

    row = _named_row(*GRID_NAMES)
    coverage = attach_live_gamelines([row], index)

    assert coverage["index_size"] == 1
    assert coverage["rows_live_gameline_edged"] == 0
    assert coverage["withheld_by_reason"]["no_live_gameline_projection"] == 1
    assert "live_aware" not in row["projection"], "a key miss must not fabricate a live row"
    assert "live_gameline" not in row


def test_and_the_same_row_DOES_join_when_the_lens_uses_the_grids_convention():
    """`off != on`. Without this the test above passes on a broken join too."""
    index = _named_index(*GRID_NAMES)
    row = _named_row(*GRID_NAMES)
    coverage = attach_live_gamelines([row], index)

    assert coverage["index_size"] == 1
    assert coverage["rows_live_gameline_edged"] == 1
    assert row["projection"]["live_aware"] is True
    # and the label this lane fixed is correct on the joined row
    assert row["projection"]["edge_basis"] == "live"
