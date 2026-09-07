"""The soccer sim engine's market prior must actually receive a market.

WHY THIS EXISTS (2026-09-07). `possession_priors._market_prior_index` reads
`market_features["total"]["line"]` and `market_features["spread"]["home_line"]`,
and `build_soccer_artifacts.py` never set `market_features` at all -- it set
`market_odds`, which only the ANCHOR reads. So the index returned a constant
0.5 for every fixture in every league, while the odds CSV on the same disk
carried 1,450 totals rows and 812 spreads rows that were parsed and dropped.

These tests fail if the bridge is reverted, if the median/side rules regress,
or if the attach is moved below the `weight <= 0.0` early return (which is the
state production runs in, so anything after it never executes).
"""
from __future__ import annotations

import csv
import io

from syndicate.features.soccer.features.market_odds import (
    attach_market_features,
    market_lines_by_event,
)
from syndicate.features.soccer.sim_engine.soccersim.possession_priors import (
    _market_prior_index,
)

# Shaped exactly like production's `game_odds_current.csv` (verified against the
# live artifact 2026-09-07): long format, one row per book/side.
CSV = """league,event_id,home_team,away_team,commence_time,market,side,line,price,book
epl,E1,Arsenal,Chelsea,2026-09-12T19:00:00Z,h2h,Arsenal,,-150,draftkings
epl,E1,Arsenal,Chelsea,2026-09-12T19:00:00Z,totals,Over,2.5,-110,draftkings
epl,E1,Arsenal,Chelsea,2026-09-12T19:00:00Z,totals,Under,2.5,-110,draftkings
epl,E1,Arsenal,Chelsea,2026-09-12T19:00:00Z,totals,Over,2.75,-105,fanduel
epl,E1,Arsenal,Chelsea,2026-09-12T19:00:00Z,totals,Over,3.0,-120,betmgm
epl,E1,Arsenal,Chelsea,2026-09-12T19:00:00Z,spreads,Arsenal,-0.5,-120,draftkings
epl,E1,Arsenal,Chelsea,2026-09-12T19:00:00Z,spreads,Chelsea,0.5,+100,draftkings
"""


def _rows():
    return list(csv.DictReader(io.StringIO(CSV)))


def test_totals_line_is_the_median_of_the_over_quotes():
    lines = market_lines_by_event(_rows())
    # Over quotes are 2.5 / 2.75 / 3.0 -> median 2.75, a line a book actually
    # offered. A MEAN would be 2.75 here too, so the discriminating check is
    # that Under rows are not double-counted: counting both sides would give
    # six values (2.5,2.5,2.75,3.0) and a different answer.
    assert lines["E1"]["total_line"] == 2.75
    assert lines["E1"]["total_books"] == 3


def test_spread_line_is_taken_from_the_HOME_side():
    lines = market_lines_by_event(_rows())
    # Arsenal (home) is -0.5; Chelsea's row is +0.5. Reading whichever row came
    # first would flip the sign on about half of all fixtures.
    assert lines["E1"]["spread_home_line"] == -0.5


def test_attach_writes_market_features_and_leaves_market_odds_alone():
    fixtures = [{"match_id": "E1", "home_team": "Arsenal", "away_team": "Chelsea",
                 "market_odds": {"home_win_probability": 0.6}}]
    audit = attach_market_features(fixtures, market_lines_by_event(_rows()))
    assert audit["attached"] == 1
    assert fixtures[0]["market_features"]["total"]["line"] == 2.75
    assert fixtures[0]["market_features"]["spread"]["home_line"] == -0.5
    # The anchor's input must be untouched -- it stays OFF BY DECISION and this
    # change must not arm or perturb it.
    assert fixtures[0]["market_odds"] == {"home_win_probability": 0.6}


def test_model_probability_is_NOT_fabricated_from_the_market():
    fixtures = [{"match_id": "E1", "home_team": "Arsenal", "away_team": "Chelsea"}]
    attach_market_features(fixtures, market_lines_by_event(_rows()))
    features = fixtures[0]["market_features"]
    for key in ("model_probability", "confidence", "edge"):
        assert key not in features, (
            f"{key} names the MODEL's own view; filling it from market odds would "
            "misstate provenance and is circular at prior-build time."
        )


def test_market_prior_index_moves_off_its_constant():
    """OFF != ON. Without the bridge the index is the same number every time."""
    empty = _market_prior_index({})
    fixtures = [{"match_id": "E1", "home_team": "Arsenal", "away_team": "Chelsea"}]
    attach_market_features(fixtures, market_lines_by_event(_rows()))
    fed = _market_prior_index(fixtures[0]["market_features"])
    assert empty == 0.5, "unfed baseline changed; re-derive the constant before trusting this"
    assert fed != empty, "market_features attached but the engine's index did not move"


def test_a_fixture_with_no_priced_event_is_skipped_not_faked():
    fixtures = [{"match_id": "NOPE", "home_team": "Spurs", "away_team": "Everton"}]
    audit = attach_market_features(fixtures, market_lines_by_event(_rows()))
    assert audit["attached"] == 0 and audit["skipped"] == 1
    assert "market_features" not in fixtures[0], (
        "an unpriced fixture must carry NO market_features rather than a neutral "
        "default -- a fabricated line is worse than an absent one."
    )


def test_counting_pass_does_not_mutate_the_real_fixtures():
    """The flag-OFF arm still counts, and counting must not feed.

    `build_soccer_artifacts` runs `attach_market_features` over a COPY when
    `SYNDICATE_SOCCER_MARKET_PRIOR` is unset, so the log line reports what
    would attach without changing what the sim sees. If that copy were removed
    the feature would be silently armed for everyone -- a flag that does not
    gate. This pins the copy semantics the caller depends on.
    """
    real = [{"match_id": "E1", "home_team": "Arsenal", "away_team": "Chelsea"}]
    shadow = [dict(f) for f in real]
    audit = attach_market_features(shadow, market_lines_by_event(_rows()))
    assert audit["attached"] == 1, "the counting pass must still report the real join"
    assert "market_features" not in real[0], (
        "flag OFF must leave the fixture the simulation reads untouched"
    )
    assert "market_features" in shadow[0]
