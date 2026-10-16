"""Hermetic tests for the UEFA close-backtest join, close and blend (todo #699 step 3). No network."""

from __future__ import annotations

import math

import pytest

from syndicate.features.soccer import uefa_close_backtest as ucb


def _ev(home, away, commence="2023-10-03T19:00:00Z", books=None):
    if books is None:
        books = {"pinnacle": (2.0, 3.6, 4.0)}
    return {"home_team": home, "away_team": away, "commence_time": commence,
            "bookmakers": [{"key": k, "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": h}, {"name": "Draw", "price": d}, {"name": away, "price": a}]}]}
                for k, (h, d, a) in books.items()]}


def test_normalise_strips_accents_punctuation_and_club_tokens():
    assert ucb.normalise_name("Atlético Madrid") == "atletico madrid"
    assert ucb.normalise_name("F.C. København") == "kobenhavn"
    assert ucb.normalise_name("SSC Napoli") == ucb.normalise_name("Napoli")
    assert ucb.name_score("Paris Saint-Germain", "Paris Saint Germain") == 1.0
    assert ucb.name_score("", "Napoli") == 0.0


def test_join_picks_the_right_event_in_window_and_detects_swapped_orientation():
    events = [_ev("Napoli", "Real Madrid"), _ev("RC Lens", "Arsenal"),
              _ev("Celtic", "SS Lazio", commence="2023-10-04T19:00:00Z")]
    r = ucb.join_event("Napoli", "Real Madrid", "2023-10-03T19:00Z", events)
    assert r.reason == "ok" and r.event["home_team"] == "Napoli" and not r.swapped
    s = ucb.join_event("Arsenal", "Lens", "2023-10-03T19:00Z", events)
    assert s.reason == "ok" and s.swapped
    # Celtic's event is a day away: outside the 60-minute window
    assert ucb.join_event("Celtic", "Lazio", "2023-10-03T19:00Z", events).reason == "low_score"
    assert ucb.join_event("Celtic", "Lazio", "2023-10-05T19:00Z", events).reason == "no_candidate"


def test_join_refuses_an_ambiguous_pair():
    events = [_ev("Dinamo Zagreb", "Dynamo Kyiv"), _ev("Dinamo Zagreb", "Dinamo Kiev")]
    assert ucb.join_event("Dinamo Zagreb", "Dynamo Kyiv", "2023-10-03T19:00Z", events).reason in ("ok", "ambiguous")
    twins = [_ev("Inter", "Milan"), _ev("Inter", "Milan")]
    assert ucb.join_event("Inter", "Milan", "2023-10-03T19:00Z", twins).reason == "ambiguous"


def test_close_prefers_pinnacle_and_otherwise_averages_devigged_books():
    ev = _ev("A", "B", books={"pinnacle": (2.0, 4.0, 4.0), "bet365": (1.5, 5.0, 8.0)})
    probs, source, n = ucb.close_1x2(ev, swapped=False)
    assert source == "pinnacle" and n == 2
    assert probs == pytest.approx((0.5, 0.25, 0.25))
    ev2 = _ev("A", "B", books={"b1": (2.0, 4.0, 4.0), "b2": (4.0, 4.0, 2.0)})
    probs2, source2, _ = ucb.close_1x2(ev2, swapped=False)
    assert source2 == "average" and probs2 == pytest.approx((0.375, 0.25, 0.375))
    assert sum(probs2) == pytest.approx(1.0)


def test_close_swaps_back_to_espn_orientation_and_skips_incomplete_books():
    ev = _ev("B", "A", books={"pinnacle": (2.0, 4.0, 4.0)})
    probs, _, _ = ucb.close_1x2(ev, swapped=True)
    assert probs == pytest.approx((0.25, 0.25, 0.5))  # ESPN home = OddsAPI away
    broken = _ev("A", "B", books={"pinnacle": (2.0, 1.0, 4.0)})  # a price <= 1 is not a quote
    assert ucb.close_1x2(broken, swapped=False) is None


def test_blend_and_weight_choice():
    assert ucb.blend((0.6, 0.2, 0.2), (0.4, 0.3, 0.3), 0.5) == pytest.approx((0.5, 0.25, 0.25))
    assert ucb.choose_weight([]) == 0.0
    # The model is always right and confident; the close is flat -> w goes to 1.
    hist = [((0.9, 0.05, 0.05), (1 / 3, 1 / 3, 1 / 3), 0)] * 20
    assert ucb.choose_weight(hist) == 1.0
    # The model is confidently wrong -> w goes to 0.
    bad = [((0.05, 0.05, 0.9), (0.5, 0.3, 0.2), 0)] * 20
    assert ucb.choose_weight(bad) == 0.0
    # Identical model and close: every w ties, so the smaller wins.
    same = [((0.5, 0.3, 0.2), (0.5, 0.3, 0.2), 1)] * 5
    assert ucb.choose_weight(same) == 0.0
    assert ucb.log_loss((0.5, 0.25, 0.25), 1) == pytest.approx(-math.log(0.25))
