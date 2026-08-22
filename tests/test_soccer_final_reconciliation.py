"""`_compact_final_reconciliation` -- grading the pregame read against
the actual result on the FINAL compact card.

The rule tested most here: a fact GRADES (hit True/False) only when a real
market line was captured. A model-only "3.1 proj" read gets reported
alongside the actual number with `hit: None` -- there was no line to have
hit or missed, and inventing a grading criterion the market never offered
would misrepresent what was actually tested pregame.
"""

from __future__ import annotations

from syndicate.features.soccer.cards import _compact_final_reconciliation

_PREGAME_WITH_LINES = {
    "away_total": "1.4", "home_total": "1.7",
    "btts": "Yes", "goals": "o2.5", "corners": "o9.5",
    "top_score": {"text": "AWY 1 - HME 1", "pct": "13.5%", "home_goals": 1, "away_goals": 1},
    "_goals_line": 2.5, "_corners_line": 9.5,
}

_MATCH_BOX = {"teams": {
    "home": {"stats": {"Corners": "6"}},
    "away": {"stats": {"Corners": "4"}},
}}


def test_no_pregame_facts_returns_none():
    assert _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=1, home_score=1,
        match_box=_MATCH_BOX, pregame_facts=None,
    ) is None


def test_missing_score_returns_none():
    assert _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=None, home_score=1,
        match_box=_MATCH_BOX, pregame_facts=_PREGAME_WITH_LINES,
    ) is None


def test_btts_hit_when_both_teams_actually_scored():
    out = _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=1, home_score=1,
        match_box=_MATCH_BOX, pregame_facts=_PREGAME_WITH_LINES,
    )
    btts = next(f for f in out["facts"] if f["label"] == "BTTS")
    assert btts == {"label": "BTTS", "projected": "Yes", "actual": "Yes", "hit": True}


def test_btts_miss_when_only_one_side_scored():
    out = _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=0, home_score=2,
        match_box=_MATCH_BOX, pregame_facts=_PREGAME_WITH_LINES,
    )
    btts = next(f for f in out["facts"] if f["label"] == "BTTS")
    assert btts["actual"] == "No"
    assert btts["hit"] is False


def test_goals_over_line_grades_hit_for_an_over_projection():
    # projected "o2.5", actual total = 1+1 = 2 -> UNDER the line -> miss.
    out = _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=1, home_score=1,
        match_box=_MATCH_BOX, pregame_facts=_PREGAME_WITH_LINES,
    )
    goals = next(f for f in out["facts"] if f["label"] == "Goals")
    assert goals["actual"] == "2 total"
    assert goals["hit"] is False


def test_goals_over_line_grades_hit_when_total_clears_the_line():
    out = _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=2, home_score=1,
        match_box=_MATCH_BOX, pregame_facts=_PREGAME_WITH_LINES,
    )
    goals = next(f for f in out["facts"] if f["label"] == "Goals")
    assert goals["actual"] == "3 total"
    assert goals["hit"] is True


def test_under_projection_grades_correctly_too():
    pregame = dict(_PREGAME_WITH_LINES, goals="u2.5")
    out = _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=1, home_score=0,
        match_box=_MATCH_BOX, pregame_facts=pregame,
    )
    goals = next(f for f in out["facts"] if f["label"] == "Goals")
    assert goals["actual"] == "1 total"
    assert goals["hit"] is True


def test_model_only_goals_projection_reports_but_does_not_grade():
    pregame = dict(_PREGAME_WITH_LINES, goals="3.1 proj", _goals_line=None)
    out = _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=1, home_score=1,
        match_box=_MATCH_BOX, pregame_facts=pregame,
    )
    goals = next(f for f in out["facts"] if f["label"] == "Goals")
    assert goals["projected"] == "3.1 proj"
    assert goals["actual"] == "2 total"
    assert goals["hit"] is None


def test_corners_grades_against_the_real_box_score_total():
    # match box: home 6 + away 4 = 10 total, line 9.5 -> OVER hits.
    out = _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=1, home_score=1,
        match_box=_MATCH_BOX, pregame_facts=_PREGAME_WITH_LINES,
    )
    corners = next(f for f in out["facts"] if f["label"] == "Corners")
    assert corners["actual"] == "10 total"
    assert corners["hit"] is True


def test_corners_absent_from_box_score_is_omitted_not_faked():
    out = _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=1, home_score=1,
        match_box={"teams": {}}, pregame_facts=_PREGAME_WITH_LINES,
    )
    labels = [f["label"] for f in out["facts"]]
    assert "Corners" not in labels


def test_top_sim_score_hit_on_exact_match():
    out = _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=1, home_score=1,
        match_box=_MATCH_BOX, pregame_facts=_PREGAME_WITH_LINES,
    )
    top = next(f for f in out["facts"] if f["label"] == "Top sim score")
    assert top["hit"] is True
    assert top["actual"] == "AWY 1 - HME 1"


def test_top_sim_score_miss_on_different_scoreline():
    out = _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=2, home_score=0,
        match_box=_MATCH_BOX, pregame_facts=_PREGAME_WITH_LINES,
    )
    top = next(f for f in out["facts"] if f["label"] == "Top sim score")
    assert top["hit"] is False
    assert top["projected"] == "AWY 1 - HME 1 (13.5%)"


def test_hit_and_graded_counts_exclude_ungraded_facts():
    pregame = dict(_PREGAME_WITH_LINES, goals="3.1 proj", _goals_line=None)
    out = _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=1, home_score=1,
        match_box=_MATCH_BOX, pregame_facts=pregame,
    )
    # BTTS hit, Goals ungraded, Corners hit, Top score hit -> graded=3, hits=3
    assert out["graded"] == 3
    assert out["hits"] == 3


def test_nothing_to_reconcile_returns_none():
    assert _compact_final_reconciliation(
        away_abbr="AWY", home_abbr="HME", away_score=1, home_score=1,
        match_box={"teams": {}},
        pregame_facts={"away_total": None, "home_total": None, "btts": None,
                       "goals": None, "corners": None, "top_score": None,
                       "_goals_line": None, "_corners_line": None},
    ) is None
