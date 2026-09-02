"""NBA carries none of the WNBA integrity defects — the `#626`(c) ports.

The WNBA accuracy assessment (2026-08-31) measured four defect classes on
production cards; each was fixed for WNBA and left live for NBA (unread, because
NBA is off-season). These tests pin the ports:

- consensus prices averaged in probability space, never on the American scale
  (the 43%-impossible-prices class);
- no ``p_win = implied + ev`` anywhere — a return fraction added to a
  probability (the p_win=1.000 / EV 2264.8% class);
- probabilities clamped to [0.01, 0.99] with the certainty counter;
- implausible EV refused, not printed;
- the totals knob exists, with the OPPOSITE default to WNBA's (NBA totals are
  UNMEASURED, not proven-bad — absent means SERVE).

`test_additive_inversion_is_gone_from_both_refresh_scripts` is the tripwire: it
pins the exact defect expression at zero occurrences in BOTH basketball refresh
scripts, so a copy-paste regression cannot quietly restore it in either.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.refresh_nba_oddsapi_props import (
    _WIN_PROB_STATS,
    _american_to_probability,
    _clamp_probability,
    _consensus_price_or_none,
    _mean_or_none,
    _nba_totals_recommendations_enabled,
    _plausible_ev_pct,
    _probability_to_american,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------- reachability
def test_arithmetic_mean_produces_an_impossible_price():
    """Two real, valid book prices; the old rule returns a value that is not a price."""
    books = [-110.0, 105.0]
    old = _mean_or_none(books)
    assert -100.0 < old < 100.0, "fixture must reproduce the defect"
    assert _american_to_probability(old) is None


def test_consensus_of_the_same_books_is_a_real_price():
    price = _consensus_price_or_none([-110.0, 105.0])
    assert price is not None
    assert not (-100.0 < price < 100.0)


def test_single_book_round_trips():
    assert _consensus_price_or_none([-140.0]) == pytest.approx(-140.0, abs=0.01)


def test_values_inside_the_hole_are_rejected_not_coerced():
    assert _american_to_probability(-89.125) is None
    assert _consensus_price_or_none([-89.125, -94.375]) is None


def test_even_money_is_canonical_plus_100():
    assert _probability_to_american(0.5) == pytest.approx(100.0)


# ------------------------------------------------------------------ the clamp
def test_clamp_refuses_certainty_and_counts_it():
    before = _WIN_PROB_STATS.get("certainty_clamped", 0)
    assert _clamp_probability(0.9999) == pytest.approx(0.99)
    assert _clamp_probability(0.0001) == pytest.approx(0.01)
    assert _WIN_PROB_STATS.get("certainty_clamped", 0) == before + 2


def test_clamp_passes_ordinary_probabilities_and_none():
    assert _clamp_probability(0.5) == pytest.approx(0.5)
    assert _clamp_probability(None) is None


def test_implausible_ev_is_refused_not_printed():
    before = _WIN_PROB_STATS.get("ev_refused_implausible", 0)
    assert _plausible_ev_pct(2264.8) is None
    assert _WIN_PROB_STATS.get("ev_refused_implausible", 0) == before + 1
    assert _plausible_ev_pct(22.7) == pytest.approx(22.7)
    assert _plausible_ev_pct(None) is None


# ------------------------------------------------------------ the totals knob
def test_totals_knob_defaults_to_serve(monkeypatch):
    """UNMEASURED is not proven-bad: absent means SERVE — the opposite of
    WNBA's measured-bad withhold. Silently changing served behaviour without a
    measurement is its own defect class."""
    monkeypatch.delenv("SYNDICATE_NBA_TOTALS_RECOMMENDATIONS", raising=False)
    assert _nba_totals_recommendations_enabled() is True


def test_totals_knob_can_withhold(monkeypatch):
    monkeypatch.setenv("SYNDICATE_NBA_TOTALS_RECOMMENDATIONS", "off")
    assert _nba_totals_recommendations_enabled() is False
    monkeypatch.setenv("SYNDICATE_NBA_TOTALS_RECOMMENDATIONS", "on")
    assert _nba_totals_recommendations_enabled() is True


# ------------------------------------------------------------------- tripwire
def test_additive_inversion_is_gone_from_both_refresh_scripts():
    """The defect expression itself, pinned at zero in BOTH files.

    For a bet at implied probability p with true probability q, EV per unit is
    q/p - 1, so the inversion is q = p * (1 + ev) — never p + ev. The additive
    form survived `bef61c33` at two WNBA sites and all three NBA sites; this
    pins the whole family."""
    for name in ("refresh_nba_oddsapi_props.py", "refresh_wnba_oddsapi_props.py"):
        source = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8-sig")
        assert "_clamp_probability(implied_prob + (" not in source, name


def test_ev_pct_routes_through_plausibility_in_both_refresh_scripts():
    for name in ("refresh_nba_oddsapi_props.py", "refresh_wnba_oddsapi_props.py"):
        source = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8-sig")
        assert '_plausible_ev_pct(_float_or_none(top_play.get("ev_pct")))' in source, name
