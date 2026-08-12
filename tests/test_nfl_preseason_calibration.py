"""`#367` -- the preseason total model was biased +5.6, and has almost no skill.

BACKTESTED on 146 completed preseason games (2023-2025), joining
`smartsim2_preseason_projections_*` to actual scores in `schedule_preseason_*`
by `game_id`. Same profile and rating_source in all four seasons including 2026,
so the error transfers.

    TOTALS   mean error +5.018, median +5.623, 71.9% projecting high
             MAE 9.62 raw -> 8.26 calibrated
             corr(projection, actual) = +0.269
             projection stdev 1.77 vs actual stdev 10.87
             MAE of ALWAYS predicting 38.5 = 8.48

    MARGINS  corr(projection, actual) = -0.047
             MAE 10.54 raw

Two findings, and the second outranks the first. The level bias is real and
fixed. But the corrected total model is only marginally better than a constant,
and the MARGIN model is indistinguishable from noise -- which matters because
`home_win_rate` derives from it, so preseason moneyline probabilities carry no
information either. I had called those numbers "sane" before measuring them.

An offset cannot manufacture skill. So the correction ships WITH the measured
skill attached to every projection, and the raw model output stays visible next
to the corrected one -- a calibration that hides what it changed is
indistinguishable from a model that was always right.
"""

from __future__ import annotations

from syndicate.features.shared.nfl_game_projections import (
    NflGameProjectionIndex,
    attach_nfl_game_projections,
)
from syndicate.features.shared.nfl_preseason_calibration import (
    TOTAL_BIAS_POINTS,
    calibrated_total,
    is_preseason_profile,
)

DATE = "2026-08-13"
HOME, AWAY = "Cincinnati Bengals", "Detroit Lions"


def _index(profile: str = "nfl_preseason_v1", total: float = 46.275) -> NflGameProjectionIndex:
    index = NflGameProjectionIndex()
    index.by_date_teams[(DATE, "cin", "det")] = {
        "margin_mean": -0.035,
        "total_mean": total,
        "margin_stdev": 24.466,
        "total_stdev": 22.554,
        "home_win_rate": 0.53,
        "generated_at": "2026-08-05T17:17:40+00:00",
        "profile": profile,
    }
    index.games = 1
    return index


def _row(market: str, *, line=None) -> dict:
    return {
        "kind": "game", "market": market, "segment": "full", "line": line,
        "commence_time": f"{DATE}T23:00:00Z", "home_team": HOME, "away_team": AWAY,
    }


def test_the_measured_bias_is_removed_from_preseason_totals():
    row = _row("totals", line=37.5)
    attach_nfl_game_projections([row], _index())
    projection = row["projection"]
    assert projection["projected"] == round(46.275 - TOTAL_BIAS_POINTS, 3)
    assert projection["edge_vs_line"] == round(46.275 - TOTAL_BIAS_POINTS - 37.5, 3)
    # The live slate's +8.775 edge on this exact game becomes ~+3.2.
    assert projection["edge_vs_line"] < 4.0


def test_the_raw_model_output_stays_visible():
    # A calibration that hides what it changed cannot be audited later.
    row = _row("totals", line=37.5)
    attach_nfl_game_projections([row], _index())
    projection = row["projection"]
    assert projection["projected_raw"] == 46.275
    assert projection["calibrated"] is True
    assert projection["calibration_points"] == TOTAL_BIAS_POINTS


def test_regular_season_projections_are_not_touched():
    # The bias was measured on PRESEASON games. Applying it to a model that was
    # never tested for it would be inventing a correction.
    row = _row("totals", line=44.0)
    attach_nfl_game_projections([row], _index(profile="nfl_v1"))
    projection = row["projection"]
    assert projection["projected"] == 46.275
    assert "calibrated" not in projection
    assert projection.get("model_skill") is None
    assert calibrated_total(46.275, "nfl_v1") == 46.275
    assert not is_preseason_profile("nfl_v1")


def test_totals_carry_their_measured_skill():
    row = _row("totals", line=37.5)
    attach_nfl_game_projections([row], _index())
    skill = row["projection"]["model_skill"]
    assert skill["sample_games"] == 146
    assert skill["correlation"] == 0.269
    assert "historical mean" in skill["verdict"]


def test_moneyline_says_it_has_no_measured_skill():
    # corr = -0.047 over 146 games. A bare 0.53 reads as a real view on the
    # game; shown with its skill it reads as what it is.
    row = _row("h2h")
    attach_nfl_game_projections([row], _index())
    skill = row["projection"]["model_skill"]
    assert skill["correlation"] == -0.047
    assert "no measured skill" in skill["verdict"]


def test_calibration_dissolves_the_unanimous_slate_warning():
    # The point of the exercise: 16 of 16 totals projecting over becomes a
    # genuinely mixed slate once the level bias is gone.
    index = NflGameProjectionIndex()
    grid = []
    for n in range(8):
        home, away = f"team{n}h", f"team{n}a"
        index.by_date_teams[(DATE, home, away)] = {
            "margin_mean": 1.0, "total_mean": 43.0, "margin_stdev": 10.0,
            "total_stdev": 10.0, "home_win_rate": 0.5, "generated_at": "",
            "profile": "nfl_preseason_v1",
        }
        row = _row("totals", line=38.0)
        row["home_team"], row["away_team"] = home, away
        grid.append(row)
    index.games = len(index.by_date_teams)
    coverage = attach_nfl_game_projections(grid, index)
    # 43.0 - 5.62 = 37.38, just BELOW a 38.0 line, so the slate flips direction
    # rather than staying unanimously over.
    assert all(r["projection"]["edge_vs_line"] < 0 for r in grid)
    warning = coverage.get("calibration_warning")
    assert warning is None or warning["direction"] == "under"


def test_a_missing_total_is_still_a_blank():
    row = _row("totals", line=37.5)
    attach_nfl_game_projections([row], _index(total=None))
    assert row.get("projection") is None
