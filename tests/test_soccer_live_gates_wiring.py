"""Gates 2 and 3 for soccer: reachability first, then behaviour.

`off != on` is asserted before anything else, because the whole failure class
here is silent: an unwired sport and a wired-but-indexing-nothing sport both
render as a blank live column.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import board_enrichment


def _projection():
    return {
        "simulations": 400,
        "home_win_probability": 0.62,
        "draw_probability": 0.23,
        "away_win_probability": 0.15,
        "projected_final_home_goals": 1.9,
        "projected_final_away_goals": 1.1,
        "projected_final_total": 3.0,
        "over_2_5_probability": 0.58,
        "both_teams_scored_probability": 0.61,
        "home_red_card_applied": False,
        "away_red_card_applied": False,
    }


def _write_live(root, *, with_props=True, games=None):
    d = root / "soccer_source" / "epl" / "api" / "live_state"
    d.mkdir(parents=True, exist_ok=True)
    game = {
        "home_team": "Arsenal",
        "away_team": "Coventry City",
        "score_home": 1,
        "score_away": 0,
        "status_display_clock": "58'",
        "projection": _projection(),
    }
    if with_props:
        game["live_player_props"] = [{
            "player_id": "p1",
            "player_name": "Kai Havertz",
            "side": "home",
            "shots_so_far": 2,
            "projected_final_shots": 3.4,
            "shots_over_probabilities": {"0.5": 0.97, "1.5": 0.82, "2.5": 0.61, "3.5": 0.38},
        }]
    (d / "live_state_2026-08-21.json").write_text(
        json.dumps({
            "league": "epl", "date": "2026-08-21",
            "generated_at": "2026-08-21T19:20:00+00:00",
            "count": 1, "games": games if games is not None else {"401879301": game},
            "match_box": {},
        }),
        encoding="utf-8",
    )


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.data_root", lambda: tmp_path
    )
    return tmp_path


def _live_h2h_row():
    # `age_seconds` IS REQUIRED, and its absence is a REFUSAL, not a default.
    #
    # This file predates the staleness gate at the join choke point
    # (`quote_age_verdict`, shipped 2026-09-01): an age that is absent or
    # non-numeric returns `REASON_QUOTE_AGE_ABSENT` and the row is counted and
    # skipped. That is deliberate -- "unknown must not take the permissive
    # branch" -- so a row with no age is CORRECTLY never priced, and these
    # gate-3 tests were asserting the old contract.
    #
    # The failure was loud in the right way: `index_size == 1` passed while
    # `rows[0]["live_gameline"]` stayed absent, i.e. the artifact LOADED and the
    # JOIN refused -- which is what this file exists to tell apart.
    #
    # Fresh on purpose: the subject here is off-vs-on wiring, not staleness.
    # The gate has its own tests; this one must not silently become a second,
    # weaker copy of them.
    return {
        "sport": "soccer", "kind": "game", "market": "h2h", "segment": "full",
        "home_team": "Arsenal", "away_team": "Coventry City",
        "game": {"state": "live"},
        "age_seconds": 30.0,
        "projection": {"market_fair_prob_over": 0.55, "side": "home"},
    }


def _live_prop_row():
    return {
        "sport": "soccer", "kind": "prop", "market": "player_shots",
        "player_name": "Kai Havertz", "line": 2.5, "side": "over",
        "game": {"state": "live"},
        "projection": {},
    }


# ---------------------------------------------------------------- reachability

def test_gate3_unwired_sport_still_fails_closed():
    out = board_enrichment.attach_live_gamelines_for_sport(
        [], sport="nhl", selected_date="2026-08-21")
    assert out["supported"] is False
    assert "nhl" in out["reason"]


def test_gate2_unwired_sport_still_fails_closed():
    out = board_enrichment.attach_live_projections_for_sport(
        [], sport="nhl", selected_date="2026-08-21")
    assert out["supported"] is False


def test_gate3_soccer_off_vs_on(root):
    """OFF (no artifact) names its zero; ON prices the row."""
    off = board_enrichment.attach_live_gamelines_for_sport(
        [_live_h2h_row()], sport="soccer", selected_date="2026-08-21")
    assert off["supported"] is True
    assert off["rows_live_gameline_edged"] == 0
    assert "no soccer match in play" in off["reason"]

    _write_live(root)
    rows = [_live_h2h_row()]
    on = board_enrichment.attach_live_gamelines_for_sport(
        rows, sport="soccer", selected_date="2026-08-21")
    assert on["supported"] is True
    assert on.get("index_size") == 1, on
    assert rows[0].get("live_gameline") is not None, "row was never touched"


def test_gate2_soccer_off_vs_on(root):
    off = board_enrichment.attach_live_projections_for_sport(
        [_live_prop_row()], sport="soccer", selected_date="2026-08-21")
    assert off["supported"] is True
    assert off["rows_live_projected"] == 0
    assert "no soccer live player props" in off["reason"]

    _write_live(root)
    rows = [_live_prop_row()]
    on = board_enrichment.attach_live_projections_for_sport(
        rows, sport="soccer", selected_date="2026-08-21")
    assert on["supported"] is True
    assert on.get("rows_live_edged", 0) or on.get("rows_live_considered", 0), on


# ---------------------------------------------------------------- behaviour

def test_gate3_prices_off_soccers_real_sim_count(root):
    """Soccer has a genuine n, unlike WNBA, so it must be PRICED rather than
    withheld by REASON_UNUSABLE_SIMS."""
    _write_live(root)
    rows = [_live_h2h_row()]
    board_enrichment.attach_live_gamelines_for_sport(
        rows, sport="soccer", selected_date="2026-08-21")
    block = rows[0]["live_gameline"]
    assert block["sims_run"] == 400
    assert block["model_prob"] == 0.62
    assert block["priceable"] is True, block.get("withheld_reason")


def test_gate3_home_framing_matches_the_market_term(root):
    """`market_fair_prob_over` is the de-vigged HOME probability on an h2h row,
    so the model term must be P(home) -- not the row's own side. Verified
    against production: a `side: draw` row carries `projection.side: home`."""
    _write_live(root)
    rows = [_live_h2h_row()]
    rows[0]["side"] = "draw"
    board_enrichment.attach_live_gamelines_for_sport(
        rows, sport="soccer", selected_date="2026-08-21")
    assert rows[0]["live_gameline"]["model_prob"] == 0.62


def test_gate3_live_games_only_no_pregame_leak(root):
    _write_live(root)
    row = _live_h2h_row()
    row["game"] = {"state": "pregame"}
    rows = [row]
    board_enrichment.attach_live_gamelines_for_sport(
        rows, sport="soccer", selected_date="2026-08-21")
    assert "live_gameline" not in rows[0]


def test_gate2_reports_the_producers_12_player_cap(root):
    """A capped-out player has no live row and is indistinguishable from one the
    re-sim never projected unless the bound travels with the count."""
    _write_live(root)
    out = board_enrichment.attach_live_projections_for_sport(
        [_live_prop_row()], sport="soccer", selected_date="2026-08-21")
    assert out["producer_player_cap"] == 12
    assert "players_at_producer_cap" in out


def test_gate2_empty_games_names_its_zero_with_counters(root):
    """`live_games 0` is 'no match in play'; `live_games > 0, rows 0' is a
    producer or join failure. They must not render identically."""
    _write_live(root, games={})
    out = board_enrichment.attach_live_projections_for_sport(
        [_live_prop_row()], sport="soccer", selected_date="2026-08-21")
    assert out["live_games"] == 0
    assert out["rows_live_projected"] == 0
