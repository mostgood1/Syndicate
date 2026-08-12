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


def test_no_skill_margin_projection_is_suppressed_not_published():
    """`#377`. The board rendered `1.0` in a PROJECTED column for EVERY NFL game
    -- Colts/Patriots, Lions/Bengals, Packers/Steelers alike -- because
    `margin_mean` really is 0.96 for all of them. That is what a model collapsed
    to the league average produces, and `MEASURED_SKILL["margins"]` already
    records it: correlation **-0.047** over 146 games, "no measured skill".

    `#367` kept the PROBABILITY visible with its skill attached, which is right:
    a probability has somewhere to carry a caveat. `projected` does not -- it
    lands in a bare numeric column -- so on that surface the only honest value is
    none.

    Measured live before the fix: 13 of 33 NFL rows carried
    `basis=smartsim2_margin_mean` with `model_skill=False`, because the SPREADS
    branch never called `skill_note` at all. Only h2h was guarded.
    """
    from syndicate.features.shared.nfl_game_projections import (
        NflGameProjectionIndex, attach_nfl_game_projections, _norm)

    entry = {"margin_mean": 0.96, "total_mean": 38.76, "home_win_rate": 0.53,
             "total_stdev": 10.0, "generated_at": "t", "profile": "nfl_preseason_v1"}
    index = NflGameProjectionIndex(
        by_date_teams={("2026-08-13", _norm("New England Patriots"), _norm("Indianapolis Colts")): entry},
        games=1,
    )
    base = dict(kind="game", segment="full", sport="nfl", event_id="e1",
                home_team="New England Patriots", away_team="Indianapolis Colts",
                commence_time="2026-08-13T23:00:00Z", game_date="2026-08-13")
    rows = [dict(base, market=m, line=l) for m, l in (("h2h", None), ("spreads", -3.0), ("totals", 39.5))]
    attach_nfl_game_projections(rows, index)
    by_market = {r["market"]: (r.get("projection") or {}) for r in rows}

    # BOTH margin branches suppress -- h2h was already guarded, spreads was not.
    for market in ("h2h", "spreads"):
        assert by_market[market]["projected"] is None, f"{market} still publishes a no-skill margin"
        assert by_market[market]["model_skill"], f"{market} suppressed without saying why"
        assert "no measured skill" in by_market[market]["projection_unavailable_reason"]

    # TOTALS is NOT suppressed: corr 0.269 and calibrated MAE 8.26 beats the
    # 8.48 constant baseline, so it carries information the margins do not.
    assert by_market["totals"]["projected"] is not None

    # `edge_vs_line` deliberately survives -- a derived diagnostic, not a headline
    # projection. Dropping it silently would hide the input from an auditor.
    assert by_market["spreads"]["edge_vs_line"] is not None


def test_regular_season_projections_are_untouched():
    """The suppression is keyed on the PRESEASON profile whitelist. A fix that
    blanked the regular season would be far worse than the bug."""
    from syndicate.features.shared.nfl_game_projections import (
        NflGameProjectionIndex, attach_nfl_game_projections, _norm)

    entry = {"margin_mean": 0.96, "total_mean": 38.76, "home_win_rate": 0.53,
             "total_stdev": 10.0, "generated_at": "t", "profile": "nfl_regular_v1"}
    index = NflGameProjectionIndex(
        by_date_teams={("2026-08-13", _norm("H"), _norm("A")): entry}, games=1)
    rows = [dict(kind="game", segment="full", sport="nfl", event_id="e1",
                 home_team="H", away_team="A", market=m, line=l,
                 commence_time="2026-08-13T23:00:00Z", game_date="2026-08-13")
            for m, l in (("h2h", None), ("spreads", -3.0))]
    attach_nfl_game_projections(rows, index)
    for r in rows:
        assert (r.get("projection") or {}).get("projected") == 0.96
