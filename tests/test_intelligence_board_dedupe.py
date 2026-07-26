"""Regression tests for #29 -- cross-type duplicate candidates.

The same underlying pick reaches the board in two shapes: the full candidate
(~100 keys, carries recommendation_id, confidence as a "38%" string) and a
reduced blotter/ranked row (~35 keys, no recommendation_id, no line, confidence
as 38.0). `_recommendation_sources` concatenates several response keys, so both
land in one list and every pick rendered twice.

Two independent defects had to be fixed for dedup to work at all, and each one
alone changed nothing:

1. The key joined id/name/market parts with `if part`, which DROPPED empty
   components rather than holding their position -- so the two shapes produced
   keys of different arity ("<recid>|over 0.5|hitter home runs" versus
   "over 0.5|hitter home runs") and could never collide. The same broken key
   existed in a second copy in pipeline/intelligence_state.py.
2. `_recommendation_sources` had two early returns that handed back the raw
   list, skipping the dedup entirely whenever an upstream key was already
   populated -- which is the common case.

The general lesson these encode, and what most of these tests pin: a field only
ONE representation carries is unusable as a hard key component. That is true of
recommendation_id, and it is equally true of `line` -- an intermediate fix that
put line in the tuple failed for exactly the same reason ('0.5' versus ''), so
line is compared as a wildcard instead.
"""

from __future__ import annotations

from syndicate.features.intelligence_board import dedupe_recommendation_items


def _full_candidate(**overrides):
    """The shape produced by the candidate pipeline."""
    base = {
        "recommendation_id": "reco_abc123",
        "name": "Aaron Judge Over 0.5 Home Runs",
        "player_name": "Aaron Judge Over 0.5 Home Runs",
        "selection": "Over 0.5",
        "pick": "Over 0.5",
        "market": "hitter home runs",
        "matchup": "NYY at BOS",
        "sport_slug": "mlb",
        "line": 0.5,
        "confidence": "38%",
        "surface_key": "pregame",
    }
    base.update(overrides)
    return base


def _reduced_row(**overrides):
    """The shape produced by the ranking/blotter path: no id, no line."""
    base = {
        "name": "Over 0.5",
        "player_name": "Aaron Judge Over 0.5 Home Runs",
        "selection": "Over 0.5",
        "pick": "Over 0.5",
        "market": "hitter home runs",
        "matchup": "NYY at BOS",
        "sport_slug": "mlb",
        "confidence": 38.0,
        "ev_open": 0.12,
        "odds_open": "+320",
    }
    base.update(overrides)
    return base


class TestCollapsesAcrossShapes:
    def test_full_and_reduced_shapes_of_one_pick_collapse(self):
        deduped = dedupe_recommendation_items([_full_candidate(), _reduced_row()])
        assert len(deduped) == 1

    def test_the_full_candidate_is_the_survivor(self):
        """Order matters: the richer row arrives first and must be the one kept.

        Keeping the reduced row would silently drop recommendation_id and the
        human-readable name from the board.
        """
        deduped = dedupe_recommendation_items([_full_candidate(), _reduced_row()])
        assert deduped[0].get("recommendation_id") == "reco_abc123"
        assert deduped[0].get("name") == "Aaron Judge Over 0.5 Home Runs"

    def test_missing_line_does_not_defeat_the_match(self):
        """The bug one field over: '0.5' vs '' must not read as two picks."""
        deduped = dedupe_recommendation_items([
            _full_candidate(line=0.5),
            _reduced_row(),  # no "line" key at all
        ])
        assert len(deduped) == 1

    def test_match_holds_regardless_of_arrival_order(self):
        assert len(dedupe_recommendation_items([_reduced_row(), _full_candidate()])) == 1


class TestKeepsGenuinelyDistinctPicks:
    def test_over_and_under_stay_distinct(self):
        deduped = dedupe_recommendation_items([
            _full_candidate(selection="Over 0.5", pick="Over 0.5"),
            _full_candidate(recommendation_id="reco_other", selection="Under 0.5", pick="Under 0.5"),
        ])
        assert len(deduped) == 2

    def test_two_lines_on_the_same_player_and_market_stay_distinct(self):
        deduped = dedupe_recommendation_items([
            _full_candidate(selection="Over 0.5", pick="Over 0.5", line=0.5),
            _full_candidate(recommendation_id="reco_other", selection="Over 1.5", pick="Over 1.5", line=1.5),
        ])
        assert len(deduped) == 2

    def test_different_players_stay_distinct(self):
        deduped = dedupe_recommendation_items([
            _full_candidate(),
            _full_candidate(
                recommendation_id="reco_other",
                name="Freddie Freeman Over 1.5 Total Bases",
                player_name="Freddie Freeman Over 1.5 Total Bases",
                selection="Over 1.5",
                pick="Over 1.5",
                market="hitter total bases",
                matchup="LAD at SD",
                line=1.5,
            ),
        ])
        assert len(deduped) == 2

    def test_same_pick_in_different_sports_stays_distinct(self):
        deduped = dedupe_recommendation_items([
            _full_candidate(sport_slug="mlb"),
            _full_candidate(recommendation_id="reco_other", sport_slug="nba"),
        ])
        assert len(deduped) == 2

    def test_line_numeric_and_string_forms_are_treated_as_equal(self):
        """0.5 and "0.5" are the same line; a str/float split must not duplicate."""
        deduped = dedupe_recommendation_items([
            _full_candidate(line=0.5),
            _full_candidate(recommendation_id="reco_other", line="0.5"),
        ])
        assert len(deduped) == 1


class TestExplicitIds:
    def test_repeated_recommendation_id_collapses(self):
        deduped = dedupe_recommendation_items([
            _full_candidate(),
            _full_candidate(matchup="different", market="different", name="different", player_name="different"),
        ])
        assert len(deduped) == 1

    def test_candidate_id_is_honoured_too(self):
        deduped = dedupe_recommendation_items([
            {"candidate_id": "cand_1", "name": "A", "selection": "Over 1.5"},
            {"candidate_id": "cand_1", "name": "B", "selection": "Under 2.5"},
        ])
        assert len(deduped) == 1


class TestDegenerateInput:
    def test_empty_input(self):
        assert dedupe_recommendation_items([]) == []

    def test_non_mappings_are_dropped(self):
        assert dedupe_recommendation_items(["nope", None, 7, _full_candidate()]) == [_full_candidate()]

    def test_items_with_no_identity_at_all_are_all_kept(self):
        """Empty rows carry no identity, so they must not collapse into one."""
        deduped = dedupe_recommendation_items([{}, {}, {}])
        assert len(deduped) == 3
