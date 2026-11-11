"""A card the serve-time scoreboard join restates LIVE gets the build's live-edge rule (lane restate-live-edge-withhold).

Measured on the served board 2026-11-11 00:41:23Z: 24 live NHL props on FLA @ CBJ (puck drop 00:40:00Z) carried a
`model_edge_pct` of 1.81-6.89 from the 00:38Z build, which priced them while the game was still pregame. The build's
`board_enrichment._enforce_live_edge_policy` clears the edge on every live row whose projection is not live-aware;
`pipeline.intelligence_state._refresh_layer2_live_state` turned these cards live afterwards and never re-applied it.
It also withheld the pregame probability from a stale copy of the build's sport set ({nfl, ncaaf}), missing the
NCAAB / WNCAAB the build added on 2026-11-03.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from pipeline import intelligence_state as st
from syndicate.features.shared.board_enrichment import LIVE_PROBABILITY_WITHHELD_SPORTS

MODULE = "syndicate.features.shared.game_chip_scoreboard.build_game_chips"
DATE = "2026-11-10"


@pytest.fixture(autouse=True)
def _no_published_chips(monkeypatch):
    # The chip artifact on disk (if any) stays out; every test hands its chips to the inline build.
    monkeypatch.setattr(st, "read_game_chips", lambda _date: None)


def _chip(sport, state, away="away club", home="home club"):
    return {"sport": sport, "state": state,
            "away": {"name": away, "key": away, "score": 1}, "home": {"name": home, "key": home, "score": 0}}


def _card(sport="nhl", **extra):
    """The measured row, FLA @ CBJ ASSISTS under 0.5, as the 00:38Z build wrote it (pregame)."""
    card = {
        "sport": sport, "candidate_type": "prop", "market": "ASSISTS", "side": "under", "line": 0.5, "segment": "full",
        "player_name": "Some Player", "away_team": "Away Club", "home_team": "Home Club",
        "away_key": "away club", "home_key": "home club", "game_date": DATE,
        "lane": "pregame", "market_state": "pregame", "is_live": False,
        "model_edge_pct": 4.91, "model_ev_pct": 5.2, "model_probability": 0.5769,
        "ev_pct": 4.5732, "score": 1.23, "sim_view": "agrees", "sim_projection": 0.55,
    }
    card.update(extra)
    return card


def _restate(cards, state="live", sport=None):
    sport = sport or cards[0]["sport"]
    with patch(MODULE, return_value=[_chip(sport, state)]):
        return st._refresh_layer2_live_state(cards, [DATE], attach_actual=False)


def test_the_measured_nhl_card_loses_its_pregame_edge_when_restated_live():
    cards = [_card()]
    assert _restate(cards) == 1
    card = cards[0]
    assert card["is_live"] is True and card["market_state"] == "live"  # the restate itself still happens
    assert card["model_edge_pct"] is None and card["sim_model_edge_pct"] == 4.91
    assert card["model_ev_pct"] is None and card["sim_model_ev_pct"] == 5.2
    assert "pregame projection cannot be priced against a live market" in card["model_edge_withheld_reason"]
    assert card["sim_view"] == "unpriced" and card["sim_unpriced_reason"] == "live"
    # The market EV, the score, and the projection are not the model's live opinion and stay as built.
    assert card["ev_pct"] == 4.5732 and card["score"] == 1.23 and card["sim_projection"] == 0.55
    # NHL is not in the build's probability set: the probability stays, and no "pregame proj" label.
    assert card["model_probability"] == 0.5769 and "pregame_on_live" not in card


def test_off_is_not_on_a_card_whose_chip_is_still_pregame_keeps_its_edge():
    """Reachability: the withhold fires only on the restate, never on a pregame card."""
    cards = [_card()]
    assert _restate(cards, state="pregame") == 0
    assert cards[0]["model_edge_pct"] == 4.91 and "sim_model_edge_pct" not in cards[0]
    assert cards[0]["sim_view"] == "agrees" and "model_edge_withheld_reason" not in cards[0]


@pytest.mark.parametrize("sport", ["nhl", "nba", "ncaab", "wncaab", "nfl", "ncaaf", "soccer", "wnba"])
def test_every_sport_loses_a_pregame_edge_on_a_live_card(sport):
    cards = [_card(sport)]
    assert _restate(cards) == 1
    assert cards[0]["model_edge_pct"] is None and cards[0]["sim_model_edge_pct"] == 4.91


@pytest.mark.parametrize("extra", [{"live_aware": True}, {"projection": {"live_aware": True}}])
def test_a_live_resim_card_keeps_its_edge(extra):
    cards = [_card(**extra)]
    assert _restate(cards) == 1
    assert cards[0]["model_edge_pct"] == 4.91 and cards[0]["sim_view"] == "agrees"
    assert "sim_model_edge_pct" not in cards[0]


@pytest.mark.parametrize("sport", ["ncaab", "wncaab"])
def test_college_basketball_restated_live_loses_its_pregame_probability_too(sport):
    """The stale {nfl, ncaaf} copy missed the 2026-11-03 decision ("Yes, blank it") the build applies."""
    cards = [_card(sport)]
    assert _restate(cards) == 1
    assert cards[0]["model_probability"] is None and cards[0]["sim_model_probability"] == 0.5769
    assert cards[0]["pregame_on_live"] is True


def test_the_probability_set_is_the_builds_own():
    assert st._probability_withheld_sports() == LIVE_PROBABILITY_WITHHELD_SPORTS


def test_a_card_restated_final_loses_its_edge_as_the_build_does():
    cards = [_card()]
    assert _restate(cards, state="final") == 1
    card = cards[0]
    assert card["market_state"] == "final" and card["model_edge_pct"] is None
    assert card["model_edge_withheld_reason"].startswith("game is final")
    assert card["sim_view"] == "unpriced" and card["sim_unpriced_reason"] == "other"


def test_restating_twice_keeps_the_original_pregame_edge():
    cards = [_card()]
    _restate(cards)
    _restate(cards)
    assert cards[0]["model_edge_pct"] is None and cards[0]["sim_model_edge_pct"] == 4.91


def test_a_card_with_no_edge_gains_nothing():
    cards = [_card(model_edge_pct=None, model_ev_pct=None, sim_view="none")]
    assert _restate(cards) == 1
    assert "model_edge_withheld_reason" not in cards[0] and "sim_model_edge_pct" not in cards[0]
    assert cards[0]["sim_view"] == "none"


def test_a_contradiction_verdict_is_not_kept_on_a_live_line():
    cards = [_card(sim_view="disagrees", sim_disagreement_pct=-4.0, sim_view_basis="model_edge")]
    _restate(cards)
    assert cards[0]["sim_view"] == "unpriced"
    assert "sim_disagreement_pct" not in cards[0] and "sim_view_basis" not in cards[0]
