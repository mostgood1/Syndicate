"""`#425` — a projection collapsed to ONE value must be reported, for EVERY sport.

THE FAILURE THIS EXISTS FOR. On 2026-08-13 the NFL board served
`margin 0.96 / total 44.38 / home_win 0.5267` on ALL 16 preseason games across
FOUR dates and **nothing anywhere reported it**. It was found by a human
noticing every card looked the same. The nflverse play-by-play was absent from
the root the generator resolved, so every club rated neutral and 300 seeds ran
over two identical league-average teams.

A BACKTESTED SKILL NOTE CANNOT CATCH THAT, which is why `#425` is not "wire
`skill_note` into the other six builders". `skill_note` asks whether a model
predicted well HISTORICALLY; a model with genuine skill still emits a constant
today if today's input went missing. Skill is a property of the MODEL, this is
a property of the RUN.

THE FALSIFICATION TESTS MATTER MORE THAN THE POSITIVE ONES. A false positive
BLANKS a real projection, which is worse than the gap being closed. The tests
that must pass are the ones where the detector stays SILENT.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.board_enrichment import (
    _MIN_GAMES_FOR_DEGENERACY_VERDICT,
    detect_degenerate_projections,
)


def _row(game, value, *, market="totals", kind="game", segment="full", raw=None, player=None):
    projection = {"projected": value}
    if raw is not None:
        projection["projected_raw"] = raw
    row = {
        "kind": kind, "market": market, "segment": segment,
        "event_id": f"g{game}", "home_team": f"H{game}", "away_team": f"A{game}",
        "projection": projection,
    }
    if player:
        row["player_name"] = player
    return row


# --------------------------------------------------------------------------
# the real failure
# --------------------------------------------------------------------------


def test_the_2026_08_13_nfl_slate_is_flagged():
    grid = [_row(i, 38.76, raw=44.38) for i in range(16)]
    out = detect_degenerate_projections(grid, sport="nfl")
    assert out["degenerate_projection_groups"] == 1
    finding = out["degenerate_projections"][0]
    assert finding["sport"] == "nfl"
    assert finding["games"] == 16
    # Reads projected_raw, the MODEL's output, not the calibrated 38.76.
    assert finding["value"] == 44.38


def test_flagged_rows_carry_an_attributable_reason():
    grid = [_row(i, 44.38) for i in range(16)]
    detect_degenerate_projections(grid, sport="nfl")
    projection = grid[0]["projection"]
    assert projection["degenerate"] is True
    assert "single constant" in projection["projection_unavailable_reason"]
    assert "16 games" in projection["projection_unavailable_reason"]


def test_an_existing_reason_is_not_overwritten():
    """`#377`/`#367` already suppress the NFL margin with a skill reason. That
    reason is more specific than ours and must survive."""
    grid = [_row(i, 0.96) for i in range(16)]
    for row in grid:
        row["projection"]["projection_unavailable_reason"] = "margin model has no measured skill"
    detect_degenerate_projections(grid, sport="nfl")
    assert grid[0]["projection"]["projection_unavailable_reason"] == "margin model has no measured skill"
    assert grid[0]["projection"]["degenerate"] is True


# --------------------------------------------------------------------------
# FALSIFICATION — the detector must stay silent
# --------------------------------------------------------------------------


def test_a_varying_slate_is_not_flagged():
    grid = [_row(i, 40.0 + i * 0.25) for i in range(16)]
    assert detect_degenerate_projections(grid, sport="nfl") == {}
    assert "degenerate" not in grid[0]["projection"]


def test_a_slate_below_the_game_threshold_is_not_flagged():
    """Two or three games can tie by coincidence. Four independent games
    agreeing to full float precision cannot happen to a working model."""
    grid = [_row(i, 44.38) for i in range(_MIN_GAMES_FOR_DEGENERACY_VERDICT - 1)]
    assert detect_degenerate_projections(grid, sport="mlb") == {}


def test_exactly_at_the_threshold_is_flagged():
    """Pins the boundary in both directions -- the test above alone would pass
    against a detector that never fires."""
    grid = [_row(i, 44.38) for i in range(_MIN_GAMES_FOR_DEGENERACY_VERDICT)]
    assert detect_degenerate_projections(grid, sport="mlb")["degenerate_projection_groups"] == 1


def test_many_alt_line_rows_on_few_games_are_not_flagged():
    """THE FALSE POSITIVE THIS DESIGN EXISTS TO AVOID. Alt lines put many rows
    on one game -- the 2026-08-13 NFL board carried 117 rows on a single game.
    A row-based count would call a 3-game slate a 60-unit constant."""
    grid = []
    for game in range(3):
        for _ in range(20):
            grid.append(_row(game, 44.38, market="spreads_alt"))
    assert detect_degenerate_projections(grid, sport="nfl") == {}


def test_a_board_with_no_projections_is_not_flagged():
    grid = [{"kind": "game", "market": "totals", "segment": "full", "event_id": f"g{i}"} for i in range(16)]
    assert detect_degenerate_projections(grid, sport="ncaaf") == {}


def test_null_projected_values_are_ignored_not_treated_as_one_value():
    """A slate where every projection is absent is a COVERAGE gap, not a
    degenerate model, and reporting it here would double-count a known state."""
    grid = [_row(i, None) for i in range(16)]
    assert detect_degenerate_projections(grid, sport="nfl") == {}


def test_markets_are_scored_independently():
    """A constant total must not be masked by a varying spread, and vice versa."""
    grid = [_row(i, 44.38, market="totals") for i in range(16)]
    grid += [_row(i, -3.0 + i, market="spreads") for i in range(16)]
    out = detect_degenerate_projections(grid, sport="nfl")
    assert out["degenerate_projection_groups"] == 1
    assert out["degenerate_projections"][0]["market"] == "totals"


def test_props_are_keyed_by_player_within_a_game():
    """One prop model emitting one number for every player is the same defect,
    and a game-only key would see a single unit per game and never fire."""
    grid = [
        _row(game, 0.5, kind="prop", market="batter_home_runs", player=f"p{p}")
        for game in range(2)
        for p in range(6)
    ]
    out = detect_degenerate_projections(grid, sport="mlb")
    assert out["degenerate_projection_groups"] == 1
    assert out["degenerate_projections"][0]["games"] == 12


# --------------------------------------------------------------------------
# the wrapper: every sport, every return path, zero call sites
# --------------------------------------------------------------------------


def test_wrapper_runs_the_check_for_a_sport_with_no_projection_source(monkeypatch):
    """An unwired sport returns `{"supported": False, ...}` from one of the 13
    return sites. The wrapper must still have run, and must not corrupt it."""
    import syndicate.features.shared.board_enrichment as mod

    coverage = mod.attach_projections([], sport="nhl", selected_date="2026-08-13")
    assert coverage["supported"] is False
    assert "degenerate_projection_groups" not in coverage


def test_wrapper_merges_findings_into_whatever_the_sport_returned(monkeypatch):
    import syndicate.features.shared.board_enrichment as mod

    grid = [_row(i, 44.38) for i in range(16)]
    monkeypatch.setattr(
        mod, "_attach_projections_by_sport",
        lambda g, *, sport, selected_date: {"supported": True, "rows_with_projection": len(g)},
    )
    coverage = mod.attach_projections(grid, sport="soccer", selected_date="2026-08-13")
    assert coverage["rows_with_projection"] == 16, "the sport's own coverage must survive"
    assert coverage["degenerate_projection_groups"] == 1
    assert coverage["degenerate_projections"][0]["sport"] == "soccer"


def test_a_scan_failure_cannot_break_the_join(monkeypatch):
    """A reporting check must never be able to take down the thing it reports
    on -- the board is more important than the warning."""
    import syndicate.features.shared.board_enrichment as mod

    def _boom(*args, **kwargs):
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(
        mod, "_attach_projections_by_sport",
        lambda g, *, sport, selected_date: {"supported": True, "rows_with_projection": 3},
    )
    monkeypatch.setattr(mod, "detect_degenerate_projections", _boom)
    coverage = mod.attach_projections([], sport="mlb", selected_date="2026-08-13")
    # The sport's own coverage survives the exploding scan, untouched.
    assert coverage["supported"] is True
    assert coverage["rows_with_projection"] == 3
    # And the scan that exploded contributed NOTHING -- this is the half that
    # actually tests the try/except, and an exact-equality assertion used to
    # carry it. That broke the moment `attach_projections` gained another
    # unconditional coverage field (`live_edge_enforced_rows`, 2026-08-16),
    # which is a real addition and not a regression. Naming the absent keys
    # keeps the guarantee while letting the payload grow.
    assert "degenerate_projection_groups" not in coverage
    assert "degenerate_projections" not in coverage


@pytest.mark.parametrize("sport", ["mlb", "nfl", "wnba", "soccer", "nhl", "nba", "ncaaf", "ncaab"])
def test_every_sport_goes_through_the_wrapper(sport, monkeypatch):
    """The point of `#425`: coverage is by CONSTRUCTION, not by remembering to
    wire each producer. A sport added later is covered without being touched."""
    import syndicate.features.shared.board_enrichment as mod

    grid = [_row(i, 7.0) for i in range(8)]
    monkeypatch.setattr(
        mod, "_attach_projections_by_sport",
        lambda g, *, sport, selected_date: {"supported": True},
    )
    coverage = mod.attach_projections(grid, sport=sport, selected_date="2026-08-13")
    assert coverage["degenerate_projections"][0]["sport"] == sport
