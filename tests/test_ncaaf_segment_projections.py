"""NCAAF segment rows get the sim's per-segment distribution, not an invention.

THE GAP, measured on the served board 2026-09-26T18:51Z mid-slate:

    full   686 / 898  = 76%     h1  0/351   q1  0/282   q3  0/260
                                q4  0/260   q2  0/232   h2  0/213

1,598 rows -- 64% of every NCAAF game row -- carried a PRICE and no model, while
`smartsim2_segment_distributions_2026_wk4.json` sat published and current (58
games, regenerated 16:20:22Z the same afternoon) with nothing consuming it.

WHAT THESE TESTS PROTECT, in the order the failures would hurt:

1. THE SIGN. The board line is the AWAY line, `margin_dist` is HOME-POSITIVE,
   and home covers STRICTLY PAST it. `margin > -line` is "the inversion that
   once put 0.74 on MLB underdogs".
2. THE PUSH. A discrete empirical distribution has real mass exactly on an
   integer line, unlike the continuous full-game path where a push has measure
   zero. Folding pushes into either side silently inflates the favourite.
3. THE LUMPINESS, which is why this is empirical at all. VERIFIED AGAINST
   PRODUCTION: South Alabama @ Kentucky q1 spreads line 6.5, margin mean 4.89,
   yet P(cover) = 0.5233 -- because 77 of 300 sims land on exactly +7, one
   touchdown. A normal approximation with that mean would have said BELOW 0.5.
   The mean sitting under the line while P(over) exceeds 0.5 is CORRECT here,
   and a test that "fixed" it would reintroduce the error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf import segment_projections as sp  # noqa: E402

FUTURE = "2099-01-01T00:00:00Z"


def _block(**segs) -> dict:
    return {"sims": 300, "segments": segs or {"q1": _seg()}}


def _seg(home=9.0, away=3.0, margin=None, total=None) -> dict:
    return {
        "home_points_mean": home,
        "away_points_mean": away,
        "margin_dist": margin if margin is not None else {"-7": 100, "0": 100, "7": 100},
        "total_points_dist": total if total is not None else {"0": 100, "10": 100, "20": 100},
    }


def _row(market: str, segment: str = "q1", line=None) -> dict:
    return {
        "market": market,
        "segment": segment,
        "line": line,
        "kind": "game",
        "home_team": "Kentucky Wildcats",
        "away_team": "South Alabama Jaguars",
        "commence_time": FUTURE,
    }


# --------------------------------------------------------------------------
# 1. the sign
# --------------------------------------------------------------------------

def test_home_covers_STRICTLY_PAST_the_away_line():
    """Away +6.5 means home -6.5; home covers on margin > 6.5, not > -6.5."""
    seg = _seg(margin={"-10": 100, "3": 100, "20": 100})
    proj = sp.segment_projection(_row("spreads", line=6.5), market="spreads", segment="q1",
                                 block=_block(q1=seg))
    # Only the +20 bucket clears 6.5.
    assert proj["model_prob_over"] == pytest.approx(1 / 3, abs=1e-4)
    # The inversion would have counted -10 and 3 as covers and returned 2/3.
    assert proj["model_prob_over"] < 0.5


def test_a_negative_line_is_still_read_in_the_same_frame():
    seg = _seg(margin={"-10": 100, "-3": 100, "20": 100})
    proj = sp.segment_projection(_row("spreads", line=-6.5), market="spreads", segment="q1",
                                 block=_block(q1=seg))
    # -3 and 20 clear -6.5; -10 does not.
    assert proj["model_prob_over"] == pytest.approx(2 / 3, abs=1e-4)


def test_h2h_is_winning_the_SEGMENT_which_is_margin_above_zero():
    seg = _seg(margin={"-7": 100, "0": 50, "7": 150})
    proj = sp.segment_projection(_row("h2h"), market="h2h", segment="q1", block=_block(q1=seg))
    # Level (0) is a push, excluded from both sides: 150 / (150 + 100).
    assert proj["model_prob_over"] == pytest.approx(150 / 250, abs=1e-4)
    assert proj["push_probability"] == pytest.approx(50 / 300, abs=1e-4)
    assert proj["projected"] is None, "a win probability is not a projected stat"


# --------------------------------------------------------------------------
# 2. the push
# --------------------------------------------------------------------------

def test_a_push_is_excluded_from_BOTH_sides_not_given_to_one():
    hist = {"40": 100, "45": 100, "50": 100}
    prob, push = sp.probability_above(hist, 45.0)
    assert prob == pytest.approx(0.5, abs=1e-9), "100 over / 100 under, the push is not a loss"
    assert push == pytest.approx(1 / 3, abs=1e-9)


def test_a_line_that_can_only_push_publishes_NO_probability():
    """0.0 and 0.5 would both be inventions."""
    prob, push = sp.probability_above({"45": 300}, 45.0)
    assert prob is None
    assert push == pytest.approx(1.0)


def test_a_half_point_line_has_no_push():
    prob, push = sp.probability_above({"40": 100, "50": 200}, 45.5)
    assert push == 0.0
    assert prob == pytest.approx(2 / 3, abs=1e-9)


def test_the_push_probability_travels_on_the_projection():
    seg = _seg(total={"40": 100, "45": 100, "50": 100})
    proj = sp.segment_projection(_row("totals", line=45.0), market="totals", segment="q1",
                                 block=_block(q1=seg))
    assert proj["push_probability"] == pytest.approx(1 / 3, abs=1e-4)
    assert proj["model_prob_over"] == pytest.approx(0.5, abs=1e-4)


# --------------------------------------------------------------------------
# 3. the lumpiness -- the production case, pinned
# --------------------------------------------------------------------------

def test_the_mean_may_sit_UNDER_the_line_while_P_over_exceeds_half():
    """South Alabama @ Kentucky, q1 spreads 6.5, VERIFIED on production:
    margin mean 4.89, P(cover) 0.5233, because 77 of 300 sims land on +7.
    A normal with that mean would have said below 0.5. Do not 'fix' this."""
    hist = {"-7": 77, "0": 66, "7": 157}
    mean = sum(float(k) * v for k, v in hist.items()) / 300
    prob, _ = sp.probability_above(hist, 6.5)
    assert mean < 6.5, "precondition: the mean is under the line"
    assert prob > 0.5, "and the probability is still above a half -- that is the point"


# --------------------------------------------------------------------------
# refusals, and what is NOT invented
# --------------------------------------------------------------------------

def test_a_segment_the_sim_did_not_publish_yields_no_projection():
    assert sp.segment_projection(_row("totals", segment="q3", line=10.0),
                                 market="totals", segment="q3", block=_block(q1=_seg())) is None


def test_an_unparseable_histogram_key_voids_the_WHOLE_histogram():
    """Skipping one bad key would quietly reweight the distribution."""
    assert sp._histogram({"d": {"7": 100, "oops": 50}}, "d") is None


def test_a_missing_distribution_still_publishes_the_PROJECTION():
    seg = {"home_points_mean": 9.0, "away_points_mean": 3.0}
    proj = sp.segment_projection(_row("totals", line=10.0), market="totals", segment="q1",
                                 block=_block(q1=seg))
    assert proj["projected"] == pytest.approx(12.0)
    assert proj["model_prob_over"] is None
    assert "no usable total_points_dist" in proj["probability_unavailable_reason"]


def test_full_is_NOT_handled_here():
    """Two producers writing one row is how a board stops being able to say
    which model it is showing. `full` belongs to `game_projections`."""
    assert "full" not in sp.SEGMENTS


def test_the_source_names_the_segment_model_not_the_full_game_one():
    proj = sp.segment_projection(_row("h2h"), market="h2h", segment="q1", block=_block(q1=_seg()))
    assert proj["source"] == "ncaaf_smartsim2_segment"
    assert proj["segment"] == "q1"


def test_skill_reports_the_GAME_level_loss_and_says_that_is_what_it_is():
    proj = sp.segment_projection(_row("h2h"), market="h2h", segment="q1", block=_block(q1=_seg()))
    skill = proj["model_skill"]
    assert skill["state"] == "measured_loss"
    assert "No per-segment skill measurement exists" in skill["note"]


# --------------------------------------------------------------------------
# the attach loop
# --------------------------------------------------------------------------

def _ids():
    from syndicate.features.ncaaf.game_projections import _norm
    return {(_norm("Kentucky Wildcats"), _norm("South Alabama Jaguars")): "gid1"}


def test_rows_are_attached_and_counted(monkeypatch):
    monkeypatch.setattr("syndicate.features.ncaaf.oddsapi_lines.resolve_team", lambda n: n)
    grid = [_row("totals", line=10.0), _row("spreads", line=1.5), _row("h2h")]
    cov = sp.attach_ncaaf_segment_projections(
        grid, blocks={"gid1": _block(q1=_seg())}, game_id_by_pair=_ids(), selected_date="2099-01-01"
    )
    assert cov["segment_rows_considered"] == 3
    assert cov["segment_rows_with_projection"] == 3
    assert all(r.get("projection") for r in grid)


def test_a_full_game_row_is_left_for_the_other_join(monkeypatch):
    monkeypatch.setattr("syndicate.features.ncaaf.oddsapi_lines.resolve_team", lambda n: n)
    grid = [_row("totals", segment="full", line=50.0)]
    cov = sp.attach_ncaaf_segment_projections(
        grid, blocks={"gid1": _block(q1=_seg())}, game_id_by_pair=_ids(), selected_date="2099-01-01"
    )
    assert cov["segment_rows_considered"] == 0
    assert "projection" not in grid[0]


def test_an_unbridged_game_is_COUNTED_not_silently_dropped(monkeypatch):
    """317 of 1,751 rows on 2026-09-26 -- the FBS-vs-FCS games the model cannot
    rate. A silent drop would read the same as a broken join."""
    monkeypatch.setattr("syndicate.features.ncaaf.oddsapi_lines.resolve_team", lambda n: n)
    grid = [_row("h2h")]
    cov = sp.attach_ncaaf_segment_projections(
        grid, blocks={"gid1": _block(q1=_seg())}, game_id_by_pair={}, selected_date="2099-01-01"
    )
    assert cov["segment_rows_unmatched_game"] == 1
    assert cov["segment_rows_with_projection"] == 0


def test_rows_from_another_date_are_not_counted(monkeypatch):
    monkeypatch.setattr("syndicate.features.ncaaf.oddsapi_lines.resolve_team", lambda n: n)
    row = _row("h2h")
    row["commence_time"] = "2098-01-01T00:00:00Z"
    cov = sp.attach_ncaaf_segment_projections(
        [row], blocks={"gid1": _block(q1=_seg())}, game_id_by_pair=_ids(), selected_date="2099-01-01"
    )
    assert cov["segment_rows_considered"] == 0


def test_absent_inputs_return_empty_rather_than_raising(monkeypatch):
    """The artifact is optional by construction: its producer is behind a flag
    that defaults OFF, so absent must never break the join beside it.

    The index is STUBBED rather than really loaded. The real loader reaches for
    a CFBD schedule, which in a data-excluded worktree tries to populate a cache
    under the git-tracked `data/` mirror -- `conftest` rightly refuses that, and
    the test then ERRORS in a full run while passing in isolation. Stubbing
    keeps this a test of THIS function.
    """
    class _Empty:
        sources: list = []

    monkeypatch.setattr(
        "syndicate.features.ncaaf.game_projections.load_ncaaf_game_projections",
        lambda _d: _Empty(),
    )
    blocks, ids = sp.load_ncaaf_segment_inputs("2099-01-01")
    assert blocks == {} and ids == {}


def test_the_loader_BODY_actually_runs_with_a_real_source(monkeypatch, tmp_path):
    """THE TEST THAT WAS MISSING, and its absence shipped a NameError.

    The stub above returns EMPTY `sources`, so the for-loop body never executes
    -- and the body referenced `Path` without importing it. Every test passed,
    the module imported cleanly, and production raised
    `BOOK_GRID_SEGMENT_PROJECTION_FAILURE` on the first real build. Exercising
    a function is not exercising its LINES.
    """
    csv_path = tmp_path / "smartsim2_projections_2026_wk4.csv"
    csv_path.write_text(
        "game_id,home_team,away_team" + chr(10) + "401869941,Coastal Carolina,Liberty" + chr(10),
        encoding="utf-8",
    )
    (tmp_path / "smartsim2_segment_distributions_2026_wk4.json").write_text(
        json.dumps({"schema_version": 1, "games": {"401869941": _block(q1=_seg())}}),
        encoding="utf-8",
    )

    class _Index:
        sources = [str(csv_path)]

    monkeypatch.setattr(
        "syndicate.features.ncaaf.game_projections.load_ncaaf_game_projections",
        lambda _d: _Index(),
    )
    blocks, ids = sp.load_ncaaf_segment_inputs("2026-09-26")
    assert "401869941" in blocks, "the artifact beside the CSV was not read"
    from syndicate.features.ncaaf.game_projections import _norm
    assert ids[(_norm("Coastal Carolina"), _norm("Liberty"))] == "401869941"


def test_a_raising_index_is_swallowed_into_empty(monkeypatch):
    """NEGATIVE CONTROL for the guard above: it must not merely be untested."""
    def _boom(_d):
        raise RuntimeError("no CFBD key")

    monkeypatch.setattr(
        "syndicate.features.ncaaf.game_projections.load_ncaaf_game_projections", _boom
    )
    assert sp.load_ncaaf_segment_inputs("2099-01-01") == ({}, {})


def test_probability_above_accepts_the_RAW_artifact_shape():
    """JSON object keys arrive as strings, and that is the most natural thing
    to hand this function -- it used to TypeError on exactly that."""
    prob, push = sp.probability_above({"40": 100, "50": 200}, 45.5)
    assert prob == pytest.approx(2 / 3, abs=1e-9) and push == 0.0


def test_probability_above_is_STRICT_about_a_bad_key():
    """Skipping the bad bucket would reweight the distribution silently, which
    is the same hazard `_histogram` refuses."""
    prob, push = sp.probability_above({"40": 100, "oops": 200}, 45.5)
    assert prob is None and push == 0.0
