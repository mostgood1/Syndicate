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


def _v2(price, fair, bookmaker=None, venue_ref=None, **rest):
    """The production path: fee from `layer2_board`, arithmetic from `opportunity_signals`."""
    return layer2_board._shadow_score_v2(price=price, fair_prob=fair, bookmaker=bookmaker,
                                         venue_ref=venue_ref, **rest)


def test_kalshi_fee_is_read_per_series_and_nets_the_ev():
    # The served #1 row of 2026-09-21: +113 on Kalshi (P = 0.4695) against fair 0.4935.
    gross = OS.expected_value_pct(113, 0.4935)
    full = _v2(113, 0.4935, "kalshi", "KXWNBATOTAL-26SEP22X-179")
    P = _p(113)
    assert full["fee_basis"] == "kalshi_series" and full["fee_is_upper_bound"] is False
    assert full["fee_per_contract"] == pytest.approx(0.07 * 1.0 * P * (1 - P), abs=1e-6)
    assert full["ev_net_pct"] == pytest.approx(100 * (0.4935 / (P + 0.07 * P * (1 - P)) - 1), abs=1e-3)
    assert gross > 5.0 > full["ev_net_pct"] + 3.0  # a 5.1% headline is ~1.3% after the fee

    half = _v2(113, 0.4935, "kalshi", "KXMLBTOTAL-26SEP22X-8")
    assert half["fee_per_contract"] == pytest.approx(0.07 * 0.5 * P * (1 - P), abs=1e-6)
    assert half["ev_net_pct"] > full["ev_net_pct"]


def test_an_unknown_kalshi_series_is_charged_the_full_rate_and_says_so():
    row = _v2(113, 0.4935, "kalshi", None)
    assert row["fee_basis"] == "kalshi_assumed_full_rate"
    assert row["fee_is_upper_bound"] is True


def test_polymarket_fee_is_flat_per_contract_and_sportsbooks_pay_none():
    poly = _v2(113, 0.4935, "polymarket")
    assert poly["fee_per_contract"] == pytest.approx(0.015)
    book = _v2(113, 0.4935, "draftkings")
    assert book["fee_per_contract"] == 0.0 and book["fee_basis"] == "none"
    assert book["ev_net_pct"] == pytest.approx(OS.expected_value_pct(113, 0.4935), abs=1e-3)


def test_at_equal_edge_the_likelier_bet_ranks_higher():
    # +4% EV both: an even-money shot and a +400 longshot, same book breadth and age.
    common = dict(books_quoting=8, book_age_seconds=60, quote_seen_age_seconds=60)
    even = OS.score_v2(price=100, fair_prob=0.52, **common)
    longshot = OS.score_v2(price=400, fair_prob=0.208, **common)
    assert even["basis"] == longshot["basis"] == "kelly_growth_bp"
    assert even["score_v2"] > longshot["score_v2"] > 0


def test_negative_ev_ranks_on_its_ev_below_every_sizable_row_and_is_never_promoted():
    common = dict(books_quoting=1, book_age_seconds=50_000)  # min reliability
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


def test_a_negative_fee_is_refused_not_turned_into_edge():
    assert OS.score_v2(price=-110, fair_prob=0.5, fee_per_contract=-0.01) is None


def _kalshi_grid_row():
    row = _grid_row()
    row["best"] = {
        "over": {"price": 113, "bookmaker": "kalshi", "age_seconds": 30.0, "books_quoting": 6},
        "under": {"price": -130, "bookmaker": "kalshi", "age_seconds": 30.0, "books_quoting": 6},
    }
    return row


def _by_side(result):
    rows = result["opportunities"] if isinstance(result, dict) else result
    return {r["side"]: r for r in rows}


def test_fee_net_switch_off_leaves_the_score_byte_identical(monkeypatch):
    monkeypatch.setattr(OS, "SCORE_FEE_NET_ENABLED", False)
    rows = _by_side(build_layer2_rows([_kalshi_grid_row()]))
    assert rows, "fixture produced no opportunities"
    for row in rows.values():
        assert "score_fee_net" not in row
        assert row["score"]["ev_component"] == pytest.approx(row["ev_pct"], abs=1e-3)


def test_fee_net_switch_on_moves_only_the_value_term_and_only_at_a_fee_venue(monkeypatch):
    monkeypatch.setattr(OS, "SCORE_FEE_NET_ENABLED", True)
    rows = _by_side(build_layer2_rows([_kalshi_grid_row()]))
    assert rows, "fixture produced no opportunities"
    for row in rows.values():
        assert row.get("score_fee_net") is True
        # the displayed EV stays GROSS (portfolio_commit rebuilds the fair from it) ...
        assert row["score"]["ev_component"] == pytest.approx(row["score_v2"]["ev_net_pct"], abs=1e-3)
        assert row["score"]["ev_component"] < row["ev_pct"]
    # ... and a sportsbook row is untouched even with the switch on.
    book_rows = _by_side(build_layer2_rows([_grid_row()]))
    for row in book_rows.values():
        assert "score_fee_net" not in row
        assert row["score"]["ev_component"] == pytest.approx(row["ev_pct"], abs=1e-3)


def test_the_kalshi_ticker_is_read_from_the_priced_side_so_mlb_pays_its_half_rate(monkeypatch):
    """At build time the ticker is on `side_best` (venue fan-in), not the row. Reading only
    the row charged all 96 MLB Kalshi rows the assumed x1.0 on 2026-09-21."""
    monkeypatch.setattr(OS, "SCORE_FEE_NET_ENABLED", True)
    row = _kalshi_grid_row()
    row["best"]["over"]["venue_ref"] = "KXMLBTOTAL-26SEP21STLCOL-8"
    row["best"]["under"]["venue_ref"] = "KXMLBTOTAL-26SEP21STLCOL-8"
    rows = _by_side(build_layer2_rows([row]))
    assert rows, "fixture produced no opportunities"
    for scored in rows.values():
        v2 = scored["score_v2"]
        assert v2["fee_basis"] == "kalshi_series" and v2["fee_is_upper_bound"] is False
        P = _p(scored["quote"]["price"]) if isinstance(scored.get("quote"), dict) else None
        if P is not None:
            assert v2["fee_per_contract"] == pytest.approx(0.07 * 0.5 * P * (1 - P), abs=1e-6)
    # Without a ticker, an MLB full-game total resolves its series from the market ...
    bare = _by_side(build_layer2_rows([_kalshi_grid_row()]))
    assert all(r["score_v2"]["fee_basis"] == "kalshi_series_from_market" for r in bare.values())
    # ... and an UNMAPPED sport/market stays the flagged full-rate bound.
    nfl = _kalshi_grid_row()
    nfl["sport"] = "nfl"
    nfl_rows = _by_side(build_layer2_rows([nfl]))
    assert nfl_rows and all(r["score_v2"]["fee_basis"] == "kalshi_assumed_full_rate"
                            and r["score_v2"]["fee_is_upper_bound"] for r in nfl_rows.values())


def test_market_inference_names_the_series_and_the_measured_table_sets_the_rate():
    """At scoring time a Kalshi price carries NO ticker (the venue restamp runs after
    `build_layer2_rows`); 82 of 82 MLB Kalshi rows paid the assumed x1.0 on 2026-09-21."""
    P = 0.47
    half = 0.07 * 0.5 * P * (1 - P)
    full = 0.07 * 1.0 * P * (1 - P)
    cases = [
        (("mlb", "batter_hits", "full"), half),
        (("mlb", "strikeouts", "full"), half),
        (("mlb", "totals_alt", "first5"), half),     # KXMLBF5TOTAL
        (("mlb", "spreads_alt", "first5"), half),    # KXMLBF5SPREAD
        (("mlb", "earned_runs", "full"), full),      # KXMLBERA is x1.0 in the measured table
        (("mlb", "hits_allowed", "full"), full),     # KXMLBHA
    ]
    for (sport, market, segment), expected in cases:
        fee, basis, bound = layer2_board.venue_fee_per_contract(
            "kalshi", P, sport=sport, market=market, segment=segment)
        assert basis == "kalshi_series_from_market" and bound is False, (market, basis)
        assert fee == pytest.approx(expected, abs=1e-9), market
    # a ticker, when present, wins over the market
    fee, basis, _ = layer2_board.venue_fee_per_contract(
        "kalshi", P, venue_ref="KXMLBERA-26SEP21X-2", sport="mlb", market="batter_hits", segment="full")
    assert basis == "kalshi_series" and fee == pytest.approx(full, abs=1e-9)
    # first inning is NOT mapped (its series is x1.0 and unverified here): the flagged bound
    fee, basis, bound = layer2_board.venue_fee_per_contract("kalshi", P, sport="mlb", market="totals", segment="first1")
    assert basis == "kalshi_assumed_full_rate" and bound is True
