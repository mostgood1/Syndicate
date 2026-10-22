"""The stage-2 score/time baseline (scripts/inplay_fair_score.py): its math, not its data."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inplay_fair_score as fs  # noqa: E402


def test_time_remaining_per_sport():
    assert fs.time_remaining("nba", 1, "12:00") == (1.0, False)
    assert fs.time_remaining("nba", 4, "0.0") == (0.0, False)
    assert fs.time_remaining("nhl", 2, "10:00") == pytest.approx((0.5, False))
    assert fs.time_remaining("nfl", 2, "0:00") == pytest.approx((0.5, False))
    tau, ot = fs.time_remaining("nba", 5, "2:24")
    assert ot and tau == pytest.approx(144 / 2880)
    assert fs.time_remaining("nba", 0, "12:00") is None


def test_brownian_reproduces_the_pregame_anchor_at_tip():
    for p0 in (0.3, 0.5, 0.72):
        assert fs.brownian_prob("GAME", "nba", p0, 220, 0, 0, 1.0, True, None) == pytest.approx(p0, abs=1e-3)


def test_brownian_moves_with_score_and_time():
    lead_early = fs.brownian_prob("GAME", "nba", 0.5, 220, 10, 100, 0.5, True, None)
    lead_late = fs.brownian_prob("GAME", "nba", 0.5, 220, 10, 200, 0.05, True, None)
    assert 0.5 < lead_early < lead_late < 1.0
    # spread "home wins by over L" vs "away wins by over L" at the same state
    home_cover = fs.brownian_prob("SPREAD", "nba", 0.5, 220, 3, 100, 0.5, True, 5.5)
    away_cover = fs.brownian_prob("SPREAD", "nba", 0.5, 220, 3, 100, 0.5, False, 5.5)
    assert home_cover > away_cover
    # total: on pace for exactly the line -> ~0.5
    assert fs.brownian_prob("TOTAL", "nba", 0.5, 220, 0, 110, 0.5, True, 220) == pytest.approx(0.5, abs=1e-6)
    assert fs.brownian_prob("TOTAL", "nba", 0.5, None, 0, 110, 0.5, True, 220) is None


def test_nhl_share_reproduces_the_anchor():
    for p0 in (0.35, 0.5, 0.65):
        h = fs.nhl_share(p0)
        assert fs.nhl_prob("GAME", h, 0, 1.0, False, 1, True, None) == pytest.approx(p0, abs=1e-3)


def test_nhl_ot_and_spreads():
    h = fs.nhl_share(0.6)
    assert fs.nhl_prob("GAME", h, 0, 0.1, True, 4, True, None) == pytest.approx(h)
    assert fs.nhl_prob("GAME", h, 0, 0.0, True, 5, True, None) == 0.5
    assert fs.nhl_prob("SPREAD", h, 0, 0.1, True, 4, True, 1.5) == 0.0
    # up 2 with 1 min left: home -1.5 very likely, away +... "away wins by over 1.5" ~ 0
    assert fs.nhl_prob("SPREAD", h, 2, 1 / 60, False, 3, True, 1.5) > 0.9
    assert fs.nhl_prob("SPREAD", h, 2, 1 / 60, False, 3, False, 1.5) < 0.01


def test_ladder_half():
    assert fs.ladder_half([(210.5, 0.8), (220.5, 0.5), (230.5, 0.2)]) == pytest.approx(220.5)
    assert fs.ladder_half([(215.5, 0.6), (225.5, 0.4)]) == pytest.approx(220.5)
    assert fs.ladder_half([(215.5, 0.3), (225.5, 0.2)]) is None


def test_sport_and_kind_of_family():
    assert fs.sport_of("KXNCAAFSPREAD") == "ncaaf"
    assert fs.sport_of("KXNFLGAME") == "nfl"
    assert fs.kind_of("KXNHLSPREAD") == "SPREAD"
    assert fs.sport_of("KXWNBAGAME") is None
