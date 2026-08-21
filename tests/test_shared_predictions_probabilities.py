"""`predictions.probabilities` must carry the MODEL's view, or nothing.

Measured on production 2026-08-21: all six fields were null on all four soccer
fixtures while `sim.win_probability` sat on the same payload.
"""
from __future__ import annotations

from syndicate.features.shared.publication_adapter import _shared_predictions


def _soccer_game():
    return {
        "sim": {
            "score": {"home_mean": 2.6775, "away_mean": 0.81},
            "win_probability": {"home": 0.79, "draw": 0.14, "away": 0.07},
        },
        # The de-vigged MARKET view, deliberately different from the sim's.
        "betting": {"p_home_win": 0.7955, "p_away_win": 0.0682},
    }


def test_sim_win_probability_is_read():
    probs = _shared_predictions(_soccer_game())["probabilities"]
    assert probs["home_win"] == 0.79
    assert probs["away_win"] == 0.07


def test_market_is_never_published_as_the_model():
    """`betting.p_home_win` is the market's de-vigged probability. Publishing it
    under `predictions` would make every edge computed against it read zero."""
    probs = _shared_predictions(_soccer_game())["probabilities"]
    assert probs["home_win"] != 0.7955
    assert probs["away_win"] != 0.0682


def test_draw_is_emitted_for_three_way_sports():
    probs = _shared_predictions(_soccer_game())["probabilities"]
    assert probs["draw"] == 0.14
    # A three-way block should now span the outcome space.
    assert abs(probs["home_win"] + probs["draw"] + probs["away_win"] - 1.0) < 0.01


def test_two_way_sport_gains_no_null_draw_key():
    """Emitting `draw: null` for MLB would add a field that never has a value."""
    probs = _shared_predictions(
        {"sim": {"score": {"home_mean": 4.5, "away_mean": 3.2}}, "predictions": {"p_home_win": 0.55}}
    )["probabilities"]
    assert "draw" not in probs
    assert probs["home_win"] == 0.55


def test_explicit_producer_value_still_wins_over_the_sim():
    """The sim is a LAST resort. A producer that states its own probability must
    not be overwritten by a fallback added later."""
    game = _soccer_game()
    game["predictions"] = {"probabilities": {"home_win": 0.61, "draw": 0.2}}
    probs = _shared_predictions(game)["probabilities"]
    assert probs["home_win"] == 0.61
    assert probs["draw"] == 0.2


def test_cover_and_total_stay_null_rather_than_borrowing_the_market():
    """Soccer publishes no MODEL number for these on this payload. A null a
    reader can see beats a market number wearing the model's label."""
    probs = _shared_predictions(_soccer_game())["probabilities"]
    assert probs["home_cover"] is None
    assert probs["total_over"] is None
