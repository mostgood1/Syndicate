"""Few-match ratings gate (lane `soccer-team-history-current-season`, measured 2026-10-07).

With current-season history on, a promoted club a few matches in would be rated from those few rows; on n 461
leak-free matches that was WORSE on 1X2 than keeping PROMOTED_TEAM_RATING (+0.0166 [+0.0015, +0.0321]). The gate
keeps the default below 10 rated rows, and only when `SYNDICATE_SOCCER_CURRENT_HISTORY` is on.
"""

from scripts.build_soccer_artifacts import PROMOTED_TEAM_RATING, _fill_promoted, _gate_few_match
from syndicate.features.soccer.features.loaders import _rating_for


def _ratings():
    return {
        "Le Mans": {"attack_rating": 0.25, "defense_rating": 0.10, "matches": 5.0},
        "Lens": {"attack_rating": 0.20, "defense_rating": 0.09, "matches": 45.0},
        "Lorient": {"attack_rating": -0.05, "defense_rating": 0.02, "matches": 12.0},
    }


def test_off_by_default_changes_nothing(monkeypatch):
    monkeypatch.delenv("SYNDICATE_SOCCER_CURRENT_HISTORY", raising=False)
    ratings = _ratings()
    before = {k: dict(v) for k, v in ratings.items()}
    assert _gate_few_match(ratings, ["Le Mans", "Lens", "Lorient"]) == []
    assert ratings == before


def test_on_gates_only_teams_under_ten_rows(monkeypatch):
    monkeypatch.setenv("SYNDICATE_SOCCER_CURRENT_HISTORY", "1")
    ratings = _ratings()
    assert _gate_few_match(ratings, ["Le Mans", "Lens", "Lorient"]) == ["Le Mans"]
    assert ratings["Le Mans"]["attack_rating"] == PROMOTED_TEAM_RATING["attack_rating"]
    assert ratings["Le Mans"]["defense_rating"] == PROMOTED_TEAM_RATING["defense_rating"]
    assert ratings["Le Mans"]["matches"] == 5.0, "the thin sample stays visible"
    assert ratings["Lens"]["attack_rating"] == 0.20
    assert ratings["Lorient"]["attack_rating"] == -0.05, "10+ rows keep their own rating"


def test_reaches_the_rating_the_sim_reads(monkeypatch):
    """REACHABILITY (on != off) through the production order: _fill_promoted, then the gate, then _rating_for."""
    for flag, expect in (("0", 0.25), ("1", PROMOTED_TEAM_RATING["attack_rating"])):
        monkeypatch.setenv("SYNDICATE_SOCCER_CURRENT_HISTORY", flag)
        ratings = _ratings()
        teams = ["Le Mans", "Lorient", "Paris FC"]
        assert _fill_promoted(ratings, teams) == ["Paris FC"]
        _gate_few_match(ratings, teams)
        rating, matched = _rating_for(ratings, "Le Mans")
        assert matched and rating["attack_rating"] == expect, f"flag={flag}"


def test_espn_name_resolves_to_the_rating_key(monkeypatch):
    monkeypatch.setenv("SYNDICATE_SOCCER_CURRENT_HISTORY", "1")
    ratings = {"Paris Saint Germain": {"attack_rating": 0.4, "defense_rating": 0.3, "matches": 4.0}}
    assert _gate_few_match(ratings, ["Paris Saint-Germain"]) == ["Paris Saint Germain"]
