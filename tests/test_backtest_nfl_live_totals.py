"""The ruler before the thing it measures -- NFL's turn, and its failures.

`nfl/live_resim.py` returns `margin_dist` / `total_dist` and `build_game_lens`
deliberately does not publish them, so `live_gameline_join` still refuses a live
NFL total or spread BY NAME. Opening that gate is a separate decision, and these
tests pin the parts of the harness that decide whether the number it produces
means anything:

  * THE PUSH RULE, because a discrete total or margin has real mass on an
    integer line, and one unparseable key must VOID the histogram rather than
    reweight it.
  * THE POWER FLOOR, because the WORST bucket is the headline and an n=5 cell
    must never become it.
  * A DELIBERATELY MISCALIBRATED FIXTURE, because a harness that cannot fail is
    not a measurement.
  * THE MARGIN ANCHOR, because anchoring on the model's own centre makes the
    calibration structurally invariant to the bias it exists to measure --
    measured on NCAAF as 0.1036 -> 0.1036.
  * THE BOOTSTRAP BEING OVER GAMES, because three cutoffs from one game are one
    observation wearing three hats.
  * THE REFUSAL TO SUBSTITUTE A RATING, because 0.0 is the engine's average team.
  * PROVENANCE, because NCAAF's withdrawn correction was fitted on a 22-day-stale
    ratings file whose staleness the harness printed every run.

The ESPN fetch is NOT tested here -- it is network -- but it was exercised while
writing this: 2026-09-27, season 2026 seasontype 2, weeks 1 and 2 return 16
completed games each with full four-quarter linescores, week 3 returns 1.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import backtest_nfl_live_totals as bt  # noqa: E402


def _rows(dist, actual, n, *, at=0, projected=44.0, market="total", event_prefix=""):
    """n rows, each its OWN game, so game-level and row-level counts agree."""
    key = "margin_dist" if market == "margin" else "total_dist"
    return [
        {
            "actual_total": actual, "actual_margin": actual,
            "total_at_cutoff": at, "score_at_cutoff": [0, at],
            "projected_total": projected, "projected_margin": projected,
            key: dist, ("total_dist" if market == "margin" else "margin_dist"): {},
            "possession_unknown": False,
            "event_id": f"{event_prefix}{i}",
        }
        for i in range(n)
    ]


# --------------------------------------------------------------------------
# the push rule
# --------------------------------------------------------------------------

def test_p_over_is_strictly_greater_and_excludes_the_push():
    assert bt._p_over({"38": 100, "44": 100, "50": 100}, 44.0) == pytest.approx(0.5)


def test_p_over_refuses_when_every_draw_lands_on_the_line():
    """0.0 and 0.5 would both be inventions."""
    assert bt._p_over({"44": 120}, 44.0) is None


def test_p_over_voids_on_an_unparseable_key():
    """Skipping one key silently reweights the distribution."""
    assert bt._p_over({"38": 100, "oops": 50}, 44.0) is None


def test_a_push_outcome_is_not_scored():
    """A game landing exactly on the line settles as a refund, so it is
    evidence about neither side."""
    assert bt.score(_rows({"55": 90, "35": 10}, 44, 40), lines=[44.0])["calibration"] == []


# --------------------------------------------------------------------------
# calibration, and the power floor
# --------------------------------------------------------------------------

def test_a_calibrated_sample_reports_a_small_worst_gap():
    rows = (_rows({"55": 90, "35": 10}, 60, 40, event_prefix="a")
            + _rows({"55": 10, "35": 90}, 30, 40, event_prefix="b"))
    result = bt.score(rows, lines=[44.5])
    assert result["worst_powered_bucket_gap"] == pytest.approx(0.1, abs=1e-9)


def test_a_DELIBERATELY_MISCALIBRATED_sample_is_caught_at_the_confident_end():
    """Says 90% over and the total goes under every time. The headline must be
    the CONFIDENT cell, because that is the cell that gets bet."""
    result = bt.score(_rows({"55": 90, "35": 10}, 30, 40), lines=[44.5])
    assert result["worst_powered_bucket"] == "0.9-1.0"
    assert result["worst_powered_bucket_gap"] == pytest.approx(0.9, abs=1e-9)


def test_an_underpowered_bucket_is_reported_but_NEVER_the_headline():
    """The negative control. An n=5 cell with a 0.9 gap must not be the number."""
    result = bt.score(_rows({"55": 90, "35": 10}, 30, 5), lines=[44.5])
    assert result["worst_powered_bucket"] is None, "an n=5 cell became the headline"
    assert result["worst_powered_bucket_gap"] is None
    assert result["calibration"], "...but it must still be visible"
    assert result["calibration"][0]["powered"] is False
    assert result["calibration"][0]["gap"] == pytest.approx(0.9, abs=1e-9)
    assert result["powered_buckets"] == 0


def test_the_power_floor_is_stated_in_the_output():
    """A reader must not have to guess why a bucket was excluded."""
    assert bt.score(_rows({"55": 90}, 60, 5), lines=[44.5])["min_bucket_n"] == bt.MIN_BUCKET_N


def test_the_direction_count_is_reported_across_buckets():
    """Realised above predicted in most buckets is systematic, not noise, even
    when the worst gap looks acceptable."""
    # One cell over-delivers (predicted 0.9, realised 1.0) and one
    # under-delivers (predicted 0.1, realised 0.0), so the count is 1 of 2.
    rows = (_rows({"55": 90, "35": 10}, 60, 40, event_prefix="a")
            + _rows({"55": 10, "35": 90}, 30, 40, event_prefix="b"))
    result = bt.score(rows, lines=[44.5])
    assert result["buckets_reported"] == 2
    assert result["buckets_realised_above_predicted"] == 1

    # And when BOTH cells over-deliver it says 2 of 2 -- the systematic case.
    both = (_rows({"55": 90, "35": 10}, 60, 40, event_prefix="c")
            + _rows({"55": 10, "35": 90}, 60, 40, event_prefix="d"))
    assert bt.score(both, lines=[44.5])["buckets_realised_above_predicted"] == 2


# --------------------------------------------------------------------------
# the hostile baseline
# --------------------------------------------------------------------------

def test_the_frozen_baseline_is_reported_beside_the_projection():
    """`frozen` = nobody scores again. Free to anyone watching."""
    result = bt.score(_rows({"55": 90, "35": 10}, 55, 10, at=20), lines=[44.5])
    assert result["mae_frozen"] == pytest.approx(35.0)      # |20 - 55|
    assert result["mae_projection"] == pytest.approx(11.0)  # |44 - 55|
    assert result["beats_frozen"] is True


def test_a_projection_WORSE_than_frozen_says_so():
    """The point of a hostile baseline is that it can win."""
    result = bt.score(_rows({"55": 90}, 46, 10, at=45), lines=[44.5])
    assert result["beats_frozen"] is False


def test_the_signed_bias_keeps_its_direction_where_MAE_would_not():
    """Projected below actual must read NEGATIVE, so "too low" and "too narrow"
    stay distinguishable."""
    result = bt.score(_rows({"55": 90}, 55, 10), lines=[44.5], market="total")
    assert result["mae_projection"] == pytest.approx(11.0)
    assert result["bias_projection"] == pytest.approx(-11.0)


# --------------------------------------------------------------------------
# the margin anchor: frozen score, never the model
# --------------------------------------------------------------------------

def test_margin_lines_are_anchored_on_the_FROZEN_score_not_the_model():
    row = {"score_at_cutoff": [10, 17]}  # away 10, home 17 -> frozen +7
    assert bt.margin_lines_for(row) == [7 - 14 + 0.5, 7 - 7 + 0.5, 7 - 3 + 0.5,
                                        7 + 0.5, 7 + 3 + 0.5, 7 + 7 + 0.5, 7 + 14 + 0.5]


def test_every_margin_line_is_a_half_point_so_nothing_can_push():
    lines = bt.margin_lines_for({"score_at_cutoff": [3, 10]})
    assert all(abs(line % 1) == 0.5 for line in lines)


def test_a_MODEL_SHIFT_MOVES_the_margin_calibration():
    """The invariance trap, pinned.

    NCAAF anchored its margin ladder on the model's own median, which produced a
    healthy spread of probabilities and was STRUCTURALLY BLIND to a location
    shift: distribution and anchor move together, so the worst bucket came back
    0.1036 -> 0.1036 at a shift that demonstrably moved the signed bias. With
    the frozen anchor a shift MUST change the predicted probabilities.
    """
    rows = _rows({"0": 50, "14": 50}, 7, 40, market="margin", projected=7.0)
    base = bt.score(rows, lines=[], market="margin")
    shifted = bt.score(rows, lines=[], market="margin", shift=10.0)
    assert base["calibration"] != shifted["calibration"], (
        "the margin calibration did not move under a location shift -- the ladder "
        "is anchored on the model and measures nothing"
    )


# --------------------------------------------------------------------------
# the bootstrap is over GAMES
# --------------------------------------------------------------------------

def _clustered_rows():
    """10 games x 3 cutoffs. Every cutoff of a game carries the same error,
    which is what a shared final score does."""
    rows = []
    for game in range(10):
        for period in (1, 2, 3):
            rows.append({
                "event_id": f"g{game}", "cutoff_period": period,
                "actual_total": 40 + game * 4, "actual_margin": 0,
                "projected_total": 44.0, "projected_margin": 0.0,
                "total_at_cutoff": 10, "score_at_cutoff": [5, 5],
                "total_dist": {}, "margin_dist": {}, "possession_unknown": False,
            })
    return rows


def test_the_bootstrap_ignores_row_multiplicity_within_a_game():
    """Duplicating every row inside its own game must not change the interval.
    A row-resampling bootstrap would narrow it."""
    rows = _clustered_rows()
    ci = bt.bootstrap_bias_ci(rows, market="total")
    doubled = bt.bootstrap_bias_ci(rows + [dict(r) for r in rows], market="total")
    assert ci == doubled


def test_a_ROW_level_bootstrap_would_be_too_tight():
    """The negative control for the clustering itself, so the choice is measured
    rather than asserted in a comment."""
    rows = _clustered_rows()
    clustered = bt.bootstrap_bias_ci(rows, market="total")
    row_level = bt.bootstrap_bias_ci(rows, market="total", cluster=False)
    assert (clustered[1] - clustered[0]) > (row_level[1] - row_level[0])


def test_the_bootstrap_refuses_on_a_single_game():
    assert bt.bootstrap_bias_ci(_rows({"55": 90}, 55, 1), market="total") is None


def test_the_reported_bias_CI_is_the_clustered_one():
    rows = _clustered_rows()
    assert bt.score(rows, lines=[44.5])["bias_ci_over_games"] == \
        bt.bootstrap_bias_ci(rows, market="total")


# --------------------------------------------------------------------------
# ratings: production's, or refuse -- never substitute
# --------------------------------------------------------------------------

def test_a_missing_team_is_REFUSED_not_rated_neutral():
    """`build_live_lens_snapshot` substitutes (0.0, 0.0) -- the engine's AVERAGE
    team. A grade must not."""
    ratings = {"PHI": (0.2, -0.1)}
    assert bt.ratings_pair(ratings, "PHI") == (0.2, -0.1)
    assert bt.ratings_pair(ratings, "DAL") is None


def test_the_two_ESPN_abbreviations_the_artifact_spells_differently_resolve():
    """Measured on the first real run as `unrated_team:LAR` x2 / `WSH` x2: the
    ratings artifact is keyed the nflverse way. A named map, so a team with no
    rating at all is still a counted refusal rather than a fuzzy match."""
    ratings = {"LA": (0.1, 0.2), "WAS": (0.3, 0.4)}
    assert bt.ratings_pair(ratings, "LAR") == (0.1, 0.2)
    assert bt.ratings_pair(ratings, "WSH") == (0.3, 0.4)
    assert bt.ratings_pair(ratings, "XYZ") is None


def test_a_ratings_artifact_is_read_the_way_production_reads_it(tmp_path):
    path = tmp_path / "smartsim2_ratings_2026_wk3.json"
    path.write_text(json.dumps({
        "season": 2026, "week": 3, "generated_at": "2026-09-26T16:10:07+00:00",
        "teams": {
            "PHI": {"offense": 0.31, "defense": -0.12, "rating_source": "current_season_blend"},
            "DAL": {"offense": -0.2, "defense": 0.05, "rating_source": "current_season_blend"},
            "XXX": {"offense": "junk", "rating_source": "current_season_blend"},
        },
    }), encoding="utf-8")
    ratings, provenance = bt.load_ratings_artifact(path)
    assert ratings["PHI"] == (0.31, -0.12)
    assert "XXX" not in ratings, "a malformed entry must be skipped, not coerced"
    assert provenance["teams"] == 2
    assert provenance["rating_sources"] == {"current_season_blend": 2}


def test_an_empty_ratings_artifact_RAISES_rather_than_grading_nothing(tmp_path):
    """Production returns {} here and refuses each game by name. A grade that
    returned {} would score zero cells and report a pass."""
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"teams": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        bt.load_ratings_artifact(path)


def test_an_artifact_of_junk_entries_RAISES(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"teams": {"PHI": "not a pair"}}), encoding="utf-8")
    with pytest.raises(ValueError):
        bt.load_ratings_artifact(path)


# --------------------------------------------------------------------------
# provenance: absent is STALE, and ratings that postdate the games are flagged
# --------------------------------------------------------------------------

NOW = _dt.datetime(2026, 9, 27, 12, 0, tzinfo=_dt.timezone.utc)


def test_absent_provenance_is_STALE_not_fresh():
    verdict = bt.rating_freshness({}, kickoffs=["2026-09-20T17:00Z"], now=NOW)
    assert verdict["verdict"] == "STALE_NO_PROVENANCE"
    assert verdict["age_days"] is None


def test_ratings_written_before_the_games_are_POINT_IN_TIME():
    verdict = bt.rating_freshness(
        {"generated_at": "2026-09-19T12:00:00+00:00",
         "rating_sources": {"current_season_blend": 32}},
        kickoffs=["2026-09-20T17:00:00+00:00"], now=NOW)
    assert verdict["verdict"] == "POINT_IN_TIME"
    assert verdict["age_days"] == pytest.approx(8.0, abs=0.01)


def test_ratings_written_AFTER_the_games_are_flagged_as_leakage():
    """This is the real shape of the 2026 NFL artifacts, so it must be visible
    rather than inferred."""
    verdict = bt.rating_freshness(
        {"generated_at": "2026-09-26T16:10:00+00:00",
         "rating_sources": {"current_season_blend": 32}},
        kickoffs=["2026-09-20T17:00:00+00:00"], now=NOW)
    assert verdict["verdict"] == "LEAKAGE_RISK_RATINGS_POSTDATE_GAMES"


def test_prior_season_only_ratings_are_content_clean_despite_a_late_stamp():
    """A file of `prior_season_fallback` ratings cannot contain this season's
    results whatever its stamp says. Recorded, not assumed."""
    verdict = bt.rating_freshness(
        {"generated_at": "2026-09-17T23:21:50+00:00",
         "rating_sources": {"prior_season_fallback": 32}},
        kickoffs=["2026-09-10T00:20:00+00:00"], now=NOW)
    assert verdict["verdict"] == "CONTENT_CLEAN_PRIOR_SEASON_ONLY"


# --------------------------------------------------------------------------
# the shipped function, and the two gates in front of it
# --------------------------------------------------------------------------

def test_the_harness_grades_the_SHIPPED_function_through_its_env_parameter():
    """Reachability before correctness: with the flag absent the producer
    refuses, so a harness that did not pass it would grade an empty sample and
    call it a clean run."""
    from syndicate.features.nfl.live_resim import NflLiveGameState, resim_live_game

    state = NflLiveGameState(away_team="DAL", home_team="PHI", period=3,
                             clock_seconds=0, home_score=24, away_score=3)
    refused = resim_live_game(state, home_offense=0.3, home_defense=-0.1,
                              away_offense=-0.4, away_defense=0.1, sims=8, env={})
    assert getattr(refused, "reason", None) == "nfl_live_resim_disabled"
    allowed = resim_live_game(state, home_offense=0.3, home_defense=-0.1,
                              away_offense=-0.4, away_defense=0.1, sims=8,
                              env=bt.RESIM_ENV)
    assert isinstance(allowed, dict), "the harness's env does not reach the producer"
    assert allowed["total_dist"] and allowed["margin_dist"]


def test_the_band_bypass_is_restored_and_never_leaks(monkeypatch):
    """`--band bypass` is a diagnostic. It must not leave the module's constant
    changed for anything else that imports it, and its rows must be labelled."""
    from syndicate.features.nfl import live_resim as lr

    original = lr.UNINFORMATIVE_BAND
    game = {
        "event_id": "1", "week": 3, "date": "2026-09-25", "kickoff": "2026-09-25T00:15Z",
        "home_team": "PHI", "away_team": "DAL",
        "home_line": [7, 7, 7, 7], "away_line": [0, 3, 0, 0],
        "home_final": 28, "away_final": 3,
    }
    rows, _ = bt.replay_game(game, ratings={"PHI": (0.3, -0.1), "DAL": (-0.4, 0.1)},
                             sims=8, band="bypass")
    assert lr.UNINFORMATIVE_BAND == original, "the bypass leaked into the module"
    assert rows and all(r["band_bypassed"] for r in rows)


def test_an_unrated_game_is_REFUSED_and_COUNTED():
    game = {
        "event_id": "2", "week": 3, "date": "2026-09-25", "kickoff": "2026-09-25T00:15Z",
        "home_team": "PHI", "away_team": "NOPE",
        "home_line": [7, 7, 7, 7], "away_line": [0, 3, 0, 0],
        "home_final": 28, "away_final": 3,
    }
    rows, refusals = bt.replay_game(game, ratings={"PHI": (0.3, -0.1)}, sims=8)
    assert rows == []
    assert sum(refusals.values()) == 1
    assert "NOPE" in "".join(refusals)


def test_the_cutoffs_are_the_three_quarter_boundaries():
    """Q4 has no rest of game to simulate, and a cutoff inside a quarter would
    need play-by-play the scoreboard does not carry."""
    assert bt.CUTOFF_PERIODS == (1, 2, 3)


def test_the_lens_still_publishes_NEITHER_distribution():
    """The gate this harness exists to inform is still SHUT.

    If a future reader opens it, they must do it deliberately and on the
    strength of a measured number -- NCAAF's shipped on a grade fitted to
    22-day-stale ratings and was withdrawn hours later.
    """
    from syndicate.features.nfl.live_resim import NflLiveGameState, build_game_lens

    state = NflLiveGameState(away_team="DAL", home_team="PHI", period=3,
                             clock_seconds=0, home_score=24, away_score=3)
    lane = build_game_lens(state, {
        "model_home_win_prob": 0.97, "sims_run": 120, "margin_mean": 18.0,
        "total_mean": 41.0, "possession_marginalised": True,
        "margin_dist": {"18": 120}, "total_dist": {"41": 120},
    }, live_state_as_of="2026-09-27")[0]
    assert "totalRunsDist" not in lane
    assert "marginDist" not in lane
