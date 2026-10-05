"""Fuzzy name matching must not join two different clubs.

Measured 2026-10-05 (lane `soccer-xg-totals-bias`): ESPN "Le Mans" (promoted to
Ligue 1, absent from the Understat ratings) resolved to "Lens" at 0.727 and was
priced with Lens's rating instead of `PROMOTED_TEAM_RATING`. The harness's
football-data short forms hit the same failure: "Ath Madrid" -> Real Madrid,
"Paris SG" -> Paris FC.
"""

from scripts.build_soccer_artifacts import PROMOTED_TEAM_RATING, _fill_promoted
from syndicate.features.soccer.features.loaders import _rating_for
from syndicate.features.soccer.features.team_names import match_team_name

# Understat rating keys for Ligue 1 2025-26 / La Liga, as production holds them.
LIGUE_1 = ["Lens", "Le Havre", "Paris Saint Germain", "Paris FC", "Rennes", "Lorient", "Nice"]
LA_LIGA = ["Real Madrid", "Atletico Madrid", "Real Sociedad", "Real Betis"]


def test_le_mans_does_not_resolve_to_lens():
    assert match_team_name("Le Mans", LIGUE_1) is None


def test_lens_still_resolves():
    assert match_team_name("Lens", LIGUE_1) == "Lens"
    assert match_team_name("RC Lens", LIGUE_1) == "Lens"


def test_le_mans_still_matches_itself_once_rated():
    assert match_team_name("Le Mans", LIGUE_1 + ["Le Mans"]) == "Le Mans"
    assert match_team_name("Le Mans FC", LIGUE_1 + ["Le Mans"]) == "Le Mans"


def test_football_data_short_forms_resolve_to_the_right_club():
    assert match_team_name("Ath Madrid", LA_LIGA) == "Atletico Madrid"
    assert match_team_name("Paris SG", LIGUE_1) == "Paris Saint Germain"
    assert match_team_name("Paris FC", LIGUE_1) == "Paris FC"
    assert match_team_name("Real Madrid", LA_LIGA) == "Real Madrid"


def test_le_mans_reaches_the_promoted_rating_in_production():
    """REACHABILITY: the production build path, not just the matcher."""
    ratings = {name: {"attack_rating": 0.2, "defense_rating": 0.09, "matches": 45.0} for name in LIGUE_1}
    filled = _fill_promoted(ratings, ["Le Mans", "Lens", "Paris Saint-Germain"])
    assert filled == ["Le Mans"]
    rating, matched = _rating_for(ratings, "Le Mans")
    assert matched is True
    assert rating == PROMOTED_TEAM_RATING
