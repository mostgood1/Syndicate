"""NFL was the sport `live_edge_policy`'s centralisation was supposed to catch.

MEASURED on the served shortlist 2026-08-15T02:37Z, before this fix: 105 rows,
51 with `market_state: live`, and **5 of them carrying a `model_edge_pct`** --
all NFL, all `basis: smartsim2_total_normal`, on games at `Q4 4:53` and
`Q4 2:52`, with edges +2.70 / +2.47 / -2.47 / -4.53 / -7.03 against full-game
totals of 34.5-39.5. MLB's 31 live rows on the same board were correctly blank,
carrying `live_edge_policy`'s own reason string.

The rule was written in `prop_projections`, copied into `soccer_projections`,
missed by WNBA (128 of 128 live rows edged, 2026-08-10), then extracted into
`live_edge_policy` so that -- in its own words -- "every sport's projection
attach can depend on it without depending on each other". NFL never took the
dependency, so the extraction fixed three sports and left the fourth untouched.

WHY THE GUARD IS AT THE STAMP POINT AND NOT IN THE TOTALS BRANCH. Totals is the
only branch that currently computes an edge, so guarding it there would pass
every test below and be missed by the next branch that learns to compute one --
which is the exact failure mode this file exists to prevent. `test_choke_point_*`
pins that: h2h and spreads rows on a live game must also come back with the
stated reason, even though neither produces an edge today.

REACHABILITY, so this is not an inert fix: the shortlist's `model_edge_pct` is
`_model_edge_for` (`layer2_board.py:767`) reading `projection.edge_vs_market_pct`
and nothing else, then `candidate["model_edge_pct"] = model_edge` (line 917).
Setting the field to None here is what removes the row's edge from the board.

MUTATION-PINNED. Deleting the `live_reason` block in
`attach_nfl_game_projections` must turn `test_live_totals_row_loses_its_edge`,
`test_final_row_loses_its_edge` and both `test_choke_point_*` RED while
`test_pregame_row_keeps_its_edge`, `test_unknown_state_keeps_its_edge` and
`test_edge_value_is_unchanged_when_allowed` stay GREEN. That split is the
correct discrimination: the last three must hold with or without the guard, so
they are the regression net rather than evidence the guard works.
"""

from __future__ import annotations

from syndicate.features.shared.nfl_game_projections import (
    NflGameProjectionIndex,
    attach_nfl_game_projections,
)

DATE = "2026-08-13"
HOME, AWAY = "Cincinnati Bengals", "Detroit Lions"

LIVE_REASON = "game is live: a pregame projection cannot be priced against a live market"
FINAL_REASON = "game is final: the market is settled, so there is no price to beat"


def _index() -> NflGameProjectionIndex:
    index = NflGameProjectionIndex()
    index.by_date_teams[(DATE, "cin", "det")] = {
        "margin_mean": -0.035,
        "total_mean": 46.275,
        "margin_stdev": 24.466,
        "total_stdev": 22.554,
        "home_win_rate": 0.53,
        "generated_at": "2026-08-05T17:17:40+00:00",
    }
    index.games = 1
    return index


def _row(market: str = "totals", *, line=38.5, state: str | None = None) -> dict:
    """A row shaped like the board's, two-sided so a de-vig is possible.

    `sides` + `consensus` are what `_no_vig_over_probability` needs; without
    both, the totals branch short-circuits on "market is one-sided" and the test
    would pass for the wrong reason.
    """
    row: dict = {
        "kind": "game",
        "market": market,
        "segment": "full",
        "line": line,
        "commence_time": f"{DATE}T23:00:00Z",
        "home_team": HOME,
        "away_team": AWAY,
        "sides": ["over", "under"],
        "consensus": {"over": -110, "under": -110},
    }
    if state is not None:
        row["game"] = {"state": state}
    return row


def _attach(row: dict) -> dict:
    attach_nfl_game_projections([row], _index())
    return row.get("projection") or {}


# --- the guard itself -------------------------------------------------------


def test_pregame_row_keeps_its_edge():
    projection = _attach(_row(state="pregame"))
    assert projection["edge_vs_market_pct"] is not None
    assert "edge_unavailable_reason" not in projection


def test_live_totals_row_loses_its_edge():
    """The measured defect: this is the shape of all 5 rows on the 02:37Z board."""
    projection = _attach(_row(state="live"))
    assert projection["basis"] == "smartsim2_total_normal"  # same branch as production
    assert projection["edge_vs_market_pct"] is None
    assert projection["edge_unavailable_reason"] == LIVE_REASON


def test_in_progress_is_treated_as_live():
    projection = _attach(_row(state="in_progress"))
    assert projection["edge_vs_market_pct"] is None
    assert projection["edge_unavailable_reason"] == (
        "game is in_progress: a pregame projection cannot be priced against a live market"
    )


def test_final_row_loses_its_edge():
    """A settled market is worse than a live one, not safer -- no price to beat."""
    projection = _attach(_row(state="final"))
    assert projection["edge_vs_market_pct"] is None
    assert projection["edge_unavailable_reason"] == FINAL_REASON


def test_unknown_state_keeps_its_edge():
    """Fail-open is deliberate and load-bearing.

    A row whose game-state join has a gap is overwhelmingly pregame. Suppressing
    those would blank the edge column on exactly the days enrichment degrades --
    turning a join gap into a silent loss of the board's purpose. Pinned here so
    nobody "tightens" it into a default-deny without reading why.
    """
    assert _attach(_row())["edge_vs_market_pct"] is not None
    assert _attach(_row(state=""))["edge_vs_market_pct"] is not None


# --- the projection is still SHOWN, only the edge is withheld ---------------


def test_live_row_keeps_its_projection_and_probability():
    """Withhold the number that RANKS, not the research.

    A researcher comparing a pregame model against a live line is a legitimate
    thing to want; what is unsafe is giving it an edge that sorts to the top.
    """
    projection = _attach(_row(state="live"))
    assert projection["projected"] is not None
    assert projection["model_prob_over"] is not None
    assert projection["source"] == "nfl_smartsim2"


# --- the guard is at the choke point, not in one branch ---------------------


def test_choke_point_h2h_live_row_gets_the_reason():
    projection = _attach(_row("h2h", line=None, state="live"))
    assert projection["basis"] == "smartsim2_home_win_rate"
    assert projection["edge_vs_market_pct"] is None
    assert projection["edge_unavailable_reason"] == LIVE_REASON


def test_choke_point_spreads_live_row_gets_the_reason():
    projection = _attach(_row("spreads", line=-3.5, state="live"))
    assert projection["basis"] == "smartsim2_margin_mean"
    assert projection["edge_vs_market_pct"] is None
    assert projection["edge_unavailable_reason"] == LIVE_REASON


# --- the allowed path is untouched, value for value ------------------------


def test_edge_value_is_unchanged_when_allowed():
    """The guard must not perturb the arithmetic on rows it permits."""
    pregame = _attach(_row(state="pregame"))
    unknown = _attach(_row())
    assert pregame["edge_vs_market_pct"] == unknown["edge_vs_market_pct"]
    assert pregame["market_fair_prob_over"] == unknown["market_fair_prob_over"]
    assert pregame["model_prob_over"] == unknown["model_prob_over"]


def test_coverage_still_counts_a_suppressed_row_as_attached():
    """Suppression withholds an edge; it does not un-attach a projection.

    `rows_with_projection` is the coverage metric read when diagnosing "this
    sport has no model". A live row still HAS a projection, so counting it as
    missing would make a live slate look like a broken join.
    """
    live, pregame = _row(state="live"), _row(state="pregame")
    coverage = attach_nfl_game_projections([live, pregame], _index())
    assert coverage["rows_with_projection"] == 2
    assert coverage["rows_considered"] == 2
