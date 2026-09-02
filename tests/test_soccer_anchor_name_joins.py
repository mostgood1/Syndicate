"""Both of the anchor's team-name joins, which resolved by EXACT string and
silently lost most of the mechanism.

Measured against production on 2026-09-02, 10 leagues over the live 7-day
horizon, before the fix:

  fixture -> priced event  (attach_market_odds)        66 of 136 fixtures
  fixture -> ratings key   (anchor_ratings_to_market) 138 of 214 team slots

The second failure was invisible: the anchored value was written back under the
FIXTURE's name, creating a second entry that `loaders._rating_for` never reads
(it resolves with `match_team_name`, which finds the real key first, because the
spurious one is appended after it). So the anchor did nothing while the call
site's `teams_changed` counter reported it as a success.

Every test here fails against the pre-fix code. The refusal tests matter as much
as the recovery tests: a WRONG join feeds a wrong market price into a ratings
anchor, which is worse than no join at all.
"""

from syndicate.features.soccer.features.market_anchoring import anchor_ratings_to_market
from syndicate.features.soccer.features.market_odds import attach_market_odds

# `_ratings_key_for` is imported inside its own test rather than here on purpose:
# a module-level import of a symbol the fix introduces makes the whole file
# uncollectable against the pre-fix code, and then the mutation check ("do these
# tests actually fail without the fix?") cannot report per-test outcomes -- it
# reports one collection error, which is not the same evidence.

RATINGS = {
    "Bournemouth": {"attack_rating": 0.0751, "defense_rating": 0.0158},
    "Brighton": {"attack_rating": 0.0400, "defense_rating": 0.0200},
    "Arsenal": {"attack_rating": 0.1959, "defense_rating": 0.1932},
}


def _priced(home, away, probability=0.5):
    return {"home_win_probability": probability, "home_team": home, "away_team": away,
            "books": 6, "refused_prices": 0, "overround": 1.05}


# --------------------------------------------------------------------------
# JOIN 1 -- fixture -> priced event
# --------------------------------------------------------------------------

def test_fuzzy_join_recovers_a_differently_named_fixture():
    """`AFC Bournemouth` (ESPN) vs `Bournemouth` (OddsAPI). Pre-fix: skipped."""
    fixtures = [{"match_id": "espn-1", "home_team": "AFC Bournemouth", "away_team": "Brighton & Hove Albion"}]
    probabilities = {"oddsapi-9": _priced("Bournemouth", "Brighton", 0.61)}

    audit = attach_market_odds(fixtures, probabilities)

    assert audit["attached"] == 1
    assert audit["by_stage"]["fuzzy"] == 1
    assert fixtures[0]["market_odds"] == {"home_win_probability": 0.61}


def test_event_id_and_exact_pair_still_win_and_are_attributed_separately():
    """The cheap stages must not be bypassed, and each must be countable on its
    own -- a single `attached` total cannot show one of them regressing."""
    fixtures = [
        {"match_id": "shared-id", "home_team": "Whatever", "away_team": "Ignored"},
        {"match_id": "no-such-id", "home_team": "Bournemouth", "away_team": "Arsenal"},
    ]
    probabilities = {
        "shared-id": _priced("Bournemouth", "Arsenal", 0.33),
        "other-id": _priced("Bournemouth", "Arsenal", 0.44),
    }

    audit = attach_market_odds(fixtures, probabilities)

    assert audit["by_stage"]["event_id"] == 1
    assert audit["by_stage"]["exact_pair"] == 1
    assert audit["by_stage"]["fuzzy"] == 0
    assert fixtures[0]["market_odds"] == {"home_win_probability": 0.33}


def test_ambiguous_fuzzy_match_is_refused_and_counted_not_guessed():
    """Two priced events carrying the same resolved pair. A coin flip here puts
    the wrong market price into a ratings anchor, so it must refuse."""
    fixtures = [{"match_id": "espn-1", "home_team": "AFC Bournemouth", "away_team": "Arsenal FC"}]
    probabilities = {
        "a": _priced("Bournemouth", "Arsenal", 0.20),
        "b": _priced("Bournemouth", "Arsenal", 0.80),
    }

    audit = attach_market_odds(fixtures, probabilities)

    assert audit["attached"] == 0
    assert audit["skipped_reasons"] == {"ambiguous_name_match": 1}
    assert "market_odds" not in fixtures[0]


def test_two_sides_matching_different_fixtures_is_refused():
    """Both clubs appear in the feed, but never against each other. Resolving
    each side independently and pairing them would invent a fixture."""
    fixtures = [{"match_id": "espn-1", "home_team": "AFC Bournemouth", "away_team": "Arsenal FC"}]
    probabilities = {
        "a": _priced("Bournemouth", "Brighton", 0.55),
        "b": _priced("Brighton", "Arsenal", 0.45),
    }

    audit = attach_market_odds(fixtures, probabilities)

    assert audit["attached"] == 0
    assert audit["skipped_reasons"] == {"name_match_pair_disagreed": 1}


def test_a_genuinely_unpriced_fixture_is_still_skipped():
    """The fuzzy stage must not manufacture a join out of nothing -- 14 of the
    70 production skips were real, and they have to stay skips."""
    fixtures = [{"match_id": "espn-1", "home_team": "Chesterfield", "away_team": "Barrow"}]
    probabilities = {"a": _priced("Bournemouth", "Arsenal", 0.55)}

    audit = attach_market_odds(fixtures, probabilities)

    assert audit["attached"] == 0
    assert audit["skipped_reasons"] == {"no_name_match": 1}


# --------------------------------------------------------------------------
# JOIN 2 -- fixture -> ratings key
# --------------------------------------------------------------------------

def test_ratings_key_resolution_prefers_exact_then_falls_back():
    from syndicate.features.soccer.features.market_anchoring import _ratings_key_for

    assert _ratings_key_for("Bournemouth", RATINGS) == "Bournemouth"
    assert _ratings_key_for("AFC Bournemouth", RATINGS) == "Bournemouth"
    assert _ratings_key_for("Not A Club At All", RATINGS) is None
    assert _ratings_key_for("", RATINGS) is None


def test_anchor_writes_to_the_key_the_sim_reads_and_creates_no_spurious_entry():
    """THE ORIGINAL DEFECT. Pre-fix this added an `AFC Bournemouth` key holding a
    rating derived from a 0.0/0.0 default, while `Bournemouth` -- the entry the
    sim resolves to -- was left untouched."""
    fixtures = [{"match_id": "1", "home_team": "AFC Bournemouth", "away_team": "Arsenal FC",
                 "market_odds": {"home_win_probability": 0.6}}]

    anchored = anchor_ratings_to_market(dict(RATINGS), fixtures, weight=0.5, simulations=2)

    assert set(anchored) == set(RATINGS), "no key may be created for a team that resolves"
    assert anchored["Bournemouth"]["attack_rating"] != RATINGS["Bournemouth"]["attack_rating"]
    assert anchored["Bournemouth"]["defense_rating"] == RATINGS["Bournemouth"]["defense_rating"]
    assert "market_shift_applied" in anchored["Bournemouth"]


def test_audit_counts_resolution_which_teams_changed_cannot():
    """`teams_changed` at the call site counts entries differing from the input
    dict, so a spurious key reads as a success. This counter cannot."""
    fixtures = [
        {"match_id": "1", "home_team": "AFC Bournemouth", "away_team": "Arsenal FC",
         "market_odds": {"home_win_probability": 0.6}},
        {"match_id": "2", "home_team": "Some Unknown FC", "away_team": "Brighton",
         "market_odds": {"home_win_probability": 0.5}},
    ]
    audit: dict = {}

    anchor_ratings_to_market(dict(RATINGS), fixtures, weight=0.0, simulations=2, audit=audit)

    assert audit["fixtures_priced"] == 2
    assert audit["teams_resolved"] == 3
    assert audit["teams_unresolved"] == 1
    assert audit["unresolved_examples"] == ["Some Unknown FC"]


def test_an_unresolvable_team_keeps_the_old_behaviour():
    """The fix must not turn a miss into a crash or drop the fixture -- it only
    has to make the miss countable."""
    fixtures = [{"match_id": "1", "home_team": "Some Unknown FC", "away_team": "Arsenal",
                 "market_odds": {"home_win_probability": 0.5}}]

    anchored = anchor_ratings_to_market(dict(RATINGS), fixtures, weight=0.5, simulations=2)

    assert "Some Unknown FC" in anchored
    assert anchored["Arsenal"]["attack_rating"] != RATINGS["Arsenal"]["attack_rating"]


def test_weight_zero_still_leaves_every_rating_untouched():
    """`off != on` is what makes the weight knob meaningful, and the resolution
    change must not have quietly armed anything."""
    fixtures = [{"match_id": "1", "home_team": "AFC Bournemouth", "away_team": "Arsenal FC",
                 "market_odds": {"home_win_probability": 0.9}}]

    anchored = anchor_ratings_to_market(dict(RATINGS), fixtures, weight=0.0, simulations=2)

    for team, rating in RATINGS.items():
        assert anchored[team]["attack_rating"] == rating["attack_rating"]
        assert anchored[team]["defense_rating"] == rating["defense_rating"]


def test_input_ratings_are_not_mutated():
    original = {team: dict(rating) for team, rating in RATINGS.items()}
    fixtures = [{"match_id": "1", "home_team": "AFC Bournemouth", "away_team": "Arsenal FC",
                 "market_odds": {"home_win_probability": 0.6}}]

    anchor_ratings_to_market(original, fixtures, weight=0.5, simulations=2)

    assert original == RATINGS
