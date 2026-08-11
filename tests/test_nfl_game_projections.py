"""`#365` -- NFL had no projection path at all, and its sim disagrees with every price.

Measured live 2026-08-11: 171 rows across 16 games at **0.0% coverage**. Identity,
line and odds complete; the model column empty on every row. `attach_projections`
had branches for wnba, soccer and mlb and fell through for NFL.

Two things here are worth more than the wiring.

WEEK RESOLUTION IS NOT USED. Preseason and regular season both number weeks from
1 in separate file series, and `current_week.json` reads `season 2026, week 1`
while the board's games are PRESEASON week 2. Joining on week would silently
return another fixture's projection -- a real number against the wrong game. The
join uses (game date, home, away) and never asks what week it is.

THE SLATE-BIAS DETECTOR. On the day this shipped, 16 of 16 preseason totals
projected OVER the market, mean +6.47, range +1.4 to +10.1. Preseason starters
play a fraction of the snaps, so real totals run far below regular-season levels,
and `nfl_preseason_v1` was emitting regular-season-shaped means (41.9-47.6)
against a market pricing 36.0-40.5. Unqualified that renders as sixteen green
+6.5 edges and reads as a goldmine. A model that disagrees with every price on
the board in the same direction is miscalibrated, not profitable.
"""

from __future__ import annotations

from syndicate.features.shared.nfl_game_projections import (
    NflGameProjectionIndex,
    attach_nfl_game_projections,
)

DATE = "2026-08-13"
HOME, AWAY = "Cincinnati Bengals", "Detroit Lions"


def _index(**over) -> NflGameProjectionIndex:
    index = NflGameProjectionIndex()
    entry = {
        "margin_mean": -0.035,
        "total_mean": 46.275,
        "margin_stdev": 24.466,
        "total_stdev": 22.554,
        "home_win_rate": 0.53,
        "generated_at": "2026-08-05T17:17:40+00:00",
    }
    entry.update(over)
    index.by_date_teams[(DATE, "cin", "det")] = entry
    index.games = 1
    return index


def _row(market: str, *, line=None, segment: str = "full", kind: str = "game", date: str = DATE) -> dict:
    return {
        "kind": kind,
        "market": market,
        "segment": segment,
        "line": line,
        "commence_time": f"{date}T23:00:00Z",
        "home_team": HOME,
        "away_team": AWAY,
    }


def test_full_names_join_to_tri_codes():
    # The board carries "Cincinnati Bengals"; the sim carries "CIN".
    row = _row("h2h")
    coverage = attach_nfl_game_projections([row], _index())
    assert coverage["rows_with_projection"] == 1
    assert row["projection"]["source"] == "nfl_smartsim2"


def test_a_projection_never_crosses_dates():
    # The date is the safeguard against a pair that meets twice in a season.
    row = _row("h2h", date="2026-09-20")
    coverage = attach_nfl_game_projections([row], _index())
    assert row.get("projection") is None
    assert coverage["unmatched_game_rows"] == 1


def test_totals_get_a_real_probability_from_the_sims_own_dispersion():
    # Unlike WNBA (means only), SmartSim2 ships stdev, so P(over) is derived and
    # not assumed. Over means total > line -- no side convention required.
    row = _row("totals", line=37.5)
    attach_nfl_game_projections([row], _index())
    projection = row["projection"]
    assert projection["model_prob_over"] is not None
    assert 0.5 < projection["model_prob_over"] < 1.0, "sim total is far above the line, so P(over) must exceed 0.5"
    assert projection["edge_vs_line"] == round(46.275 - 37.5, 3)


def test_a_total_with_no_dispersion_stays_probability_free():
    row = _row("totals", line=37.5)
    attach_nfl_game_projections([row], _index(total_stdev=None))
    assert row["projection"]["model_prob_over"] is None
    assert row["projection"]["edge_vs_line"] is not None


def test_spreads_refuse_a_probability_they_cannot_ground():
    # The row carries `line: 6.5` and `sides: ["away","home"]` with nothing
    # saying which side owns the number. A guessed sign inverts the edge.
    row = _row("spreads", line=6.5)
    attach_nfl_game_projections([row], _index())
    projection = row["projection"]
    assert projection["model_prob_over"] is None
    assert "which side" in projection["probability_unavailable_reason"]
    assert projection["projected"] == -0.035


def test_period_markets_never_get_a_full_game_mean():
    rows = [_row("totals", line=20.5, segment="q1"), _row("spreads", line=3.5, segment="h1")]
    coverage = attach_nfl_game_projections(rows, _index())
    assert all(r.get("projection") is None for r in rows)
    assert coverage["non_full_segment_rows"] == 2


def test_a_unanimous_slate_is_flagged_as_bias():
    index = NflGameProjectionIndex()
    grid = []
    for n in range(8):
        home, away = f"team{n}h", f"team{n}a"
        index.by_date_teams[(DATE, home, away)] = {
            "margin_mean": 1.0, "total_mean": 46.0, "margin_stdev": 10.0,
            "total_stdev": 10.0, "home_win_rate": 0.5, "generated_at": "",
        }
        row = _row("totals", line=38.0)
        row["home_team"], row["away_team"] = home, away
        grid.append(row)
    index.games = len(index.by_date_teams)
    coverage = attach_nfl_game_projections(grid, index)
    warning = coverage.get("calibration_warning")
    assert warning, "eight totals all projecting over the market must be flagged"
    assert warning["direction"] == "over"
    assert warning["games"] == 8


def test_alternate_lines_cannot_manufacture_unanimity():
    # Eight alternate totals on ONE game must count as one game, not eight --
    # otherwise the detector invents the pattern it exists to find.
    index = _index()
    grid = [_row("totals", line=30.0 + n) for n in range(8)]
    coverage = attach_nfl_game_projections(grid, index)
    assert coverage.get("calibration_warning") is None


def test_a_mixed_slate_is_not_flagged():
    index = NflGameProjectionIndex()
    grid = []
    for n in range(8):
        home, away = f"team{n}h", f"team{n}a"
        # Alternating above/below the market line.
        total = 46.0 if n % 2 == 0 else 30.0
        index.by_date_teams[(DATE, home, away)] = {
            "margin_mean": 1.0, "total_mean": total, "margin_stdev": 10.0,
            "total_stdev": 10.0, "home_win_rate": 0.5, "generated_at": "",
        }
        row = _row("totals", line=38.0)
        row["home_team"], row["away_team"] = home, away
        grid.append(row)
    index.games = len(index.by_date_teams)
    coverage = attach_nfl_game_projections(grid, index)
    assert coverage.get("calibration_warning") is None, "a genuinely mixed slate must not be flagged"
