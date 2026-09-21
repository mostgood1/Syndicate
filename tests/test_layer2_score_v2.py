"""`score_v2`: the fee-net, fractional-Kelly, reliability-discounted SHADOW rank.

Lane `layer2-score-outcome-calibration` (findings_2026-09-21_layer2_score_outcomes.md).
Pins the fee arithmetic per venue, the risk-adjusted ordering, the negative-row rule,
and -- the one that matters most for a shadow field -- that it reaches real built rows
while leaving the ranking `score` drives untouched.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import layer2_board, opportunity_signals as OS
from syndicate.features.shared.layer2_board import build_layer2_rows


def _p(american):
    return 100 / (american + 100) if american > 0 else -american / (-american + 100)


def test_kalshi_fee_is_read_per_series_and_nets_the_ev():
    # The served #1 row of 2026-09-21: +113 on Kalshi (P = 0.4695) against fair 0.4935.
    gross = OS.expected_value_pct(113, 0.4935)
    full = OS.score_v2(price=113, fair_prob=0.4935, bookmaker="kalshi", venue_ref="KXWNBATOTAL-26SEP22X-179")
    P = _p(113)
    assert full["fee_basis"] == "kalshi_series" and full["fee_is_upper_bound"] is False
    assert full["fee_per_contract"] == pytest.approx(0.07 * 1.0 * P * (1 - P), abs=1e-6)
    assert full["ev_net_pct"] == pytest.approx(100 * (0.4935 / (P + 0.07 * P * (1 - P)) - 1), abs=1e-3)
    assert gross > 5.0 > full["ev_net_pct"] + 3.0  # a 5.1% headline is ~1.3% after the fee

    half = OS.score_v2(price=113, fair_prob=0.4935, bookmaker="kalshi", venue_ref="KXMLBTOTAL-26SEP22X-8")
    assert half["fee_per_contract"] == pytest.approx(0.07 * 0.5 * P * (1 - P), abs=1e-6)
    assert half["ev_net_pct"] > full["ev_net_pct"]


def test_an_unknown_kalshi_series_is_charged_the_full_rate_and_says_so():
    row = OS.score_v2(price=113, fair_prob=0.4935, bookmaker="kalshi", venue_ref=None)
    assert row["fee_basis"] == "kalshi_assumed_full_rate"
    assert row["fee_is_upper_bound"] is True


def test_polymarket_fee_is_flat_per_contract_and_sportsbooks_pay_none():
    poly = OS.score_v2(price=113, fair_prob=0.4935, bookmaker="polymarket")
    assert poly["fee_per_contract"] == pytest.approx(0.015)
    book = OS.score_v2(price=113, fair_prob=0.4935, bookmaker="draftkings")
    assert book["fee_per_contract"] == 0.0 and book["fee_basis"] == "none"
    assert book["ev_net_pct"] == pytest.approx(OS.expected_value_pct(113, 0.4935), abs=1e-3)


def test_at_equal_edge_the_likelier_bet_ranks_higher():
    # +4% EV both: an even-money shot and a +400 longshot, same book breadth and age.
    common = dict(bookmaker="draftkings", books_quoting=8, book_age_seconds=60, quote_seen_age_seconds=60)
    even = OS.score_v2(price=100, fair_prob=0.52, **common)
    longshot = OS.score_v2(price=400, fair_prob=0.208, **common)
    assert even["basis"] == longshot["basis"] == "kelly_growth_bp"
    assert even["score_v2"] > longshot["score_v2"] > 0


def test_negative_ev_ranks_on_its_ev_below_every_sizable_row_and_is_never_promoted():
    common = dict(bookmaker="draftkings", books_quoting=1, book_age_seconds=50_000)  # min reliability
    bad = OS.score_v2(price=-110, fair_prob=0.49, **common)
    worse = OS.score_v2(price=-110, fair_prob=0.45, **common)
    tiny = OS.score_v2(price=100, fair_prob=0.505, **common)
    assert bad["basis"] == "ev_net_pct" and bad["kelly_growth_bp"] is None
    assert bad["score_v2"] == pytest.approx(bad["ev_net_pct"], abs=1e-4)  # discount NOT applied
    assert bad["reliability_applied"] is False
    assert worse["score_v2"] < bad["score_v2"] < 0 < tiny["score_v2"]


def test_no_price_or_fair_is_nothing_to_rank():
    assert OS.score_v2(price=None, fair_prob=0.5) is None
    assert OS.score_v2(price=-110, fair_prob=None) is None
    assert OS.score_v2(price=-110, fair_prob=1.0) is None


def test_the_off_switch_returns_none(monkeypatch):
    monkeypatch.setattr(OS, "_SCORE_V2_ENABLED", False)
    assert OS.score_v2(price=-110, fair_prob=0.55) is None


def _grid_row(**overrides):
    row = {
        "sport": "mlb", "event_id": "evt1", "kind": "game", "market": "totals", "segment": "full",
        "line": 8.5, "player_name": None, "home_team": "St. Louis Cardinals",
        "away_team": "Colorado Rockies", "commence_time": "2026-08-08T00:15:00Z",
        "sides": ["over", "under"], "books_quoting": 11,
        "game": {"state": "pregame", "status_token": "7:15P CT"},
        "best": {
            "over": {"price": -110, "bookmaker": "draftkings", "age_seconds": 52.0, "books_quoting": 9},
            "under": {"price": -105, "bookmaker": "draftkings", "age_seconds": 60.0, "books_quoting": 9},
        },
    }
    row.update(overrides)
    return row


def test_reachability_every_scored_candidate_carries_score_v2():
    result = build_layer2_rows([_grid_row()])
    rows = result["opportunities"] if isinstance(result, dict) else result
    assert rows, "fixture produced no opportunities -- the test would prove nothing"
    for row in rows:
        v2 = row.get("score_v2")
        assert v2 is not None and v2["version"] == OS.SCORE_V2_VERSION
        assert v2["fee_basis"] == "none"  # draftkings


def test_the_shadow_cannot_move_the_ranking_or_break_the_build(monkeypatch):
    baseline = build_layer2_rows([_grid_row()])
    base_rows = baseline["opportunities"] if isinstance(baseline, dict) else baseline

    def boom(**_):
        raise RuntimeError("shadow scorer blew up")

    monkeypatch.setattr(OS, "score_v2", boom)
    broken = build_layer2_rows([_grid_row()])
    broken_rows = broken["opportunities"] if isinstance(broken, dict) else broken
    assert [(r["side"], r["score"]["score"]) for r in broken_rows] == [
        (r["side"], r["score"]["score"]) for r in base_rows]
    assert all(r.get("score_v2") is None for r in broken_rows)
    assert layer2_board._shadow_score_v2(price=-110, fair_prob=0.5) is None
