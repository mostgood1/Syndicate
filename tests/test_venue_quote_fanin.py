"""Many odds sources in, one priced candidate out.

Every test here traces to a measured failure from 2026-08-24, when the board
carried 235 soccer rows while ten MLB games sat unpriced because their
candidates were 13.9 hours old against a 6-hour ceiling.
"""

from __future__ import annotations

import time

import pytest

from syndicate.features.shared import venue_quote_fanin as mod
from syndicate.features.shared.venue_quote_fanin import (
    Quote,
    SourceOutcome,
    collect_quotes,
    select_quote,
    stamp_candidate_freshness,
)


def _q(source, key="mlb|h2h|home", age=0.0, prob=0.55, now=None):
    base = now if now is not None else time.time()
    return Quote(key=key, source=source, sport="mlb", market="h2h", side="home",
                 probability=prob, american=-122, line=None, fetched_at=base - age,
                 venue_ref=f"{source}-ref")


# ==========================================================================
# RULE 1 -- a stale source must never shadow a fresh one
# ==========================================================================


def test_the_freshest_quote_wins_regardless_of_source_order():
    """`odds_control_plane`'s own docstring records 2026-08-04: a stale copy won
    on PATH PRECEDENCE and every MLB candidate silently read
    history_points=0. Ordering may only ever break a tie."""
    now = time.time()
    # oddsapi is LAST in SOURCES, and 1 second old; kalshi is FIRST and 6h old.
    stale_kalshi = _q("kalshi", age=6 * 3600, now=now)
    fresh_oddsapi = _q("oddsapi", age=1.0, now=now)
    assert select_quote([stale_kalshi, fresh_oddsapi], now=now).source == "oddsapi"


def test_source_order_breaks_a_TIE_only():
    now = time.time()
    a = _q("kalshi", age=10.0, now=now)
    b = _q("oddsapi", age=10.0, now=now)
    assert select_quote([b, a], now=now).source == "kalshi"


def test_no_quotes_selects_nothing_rather_than_raising():
    assert select_quote([], now=time.time()) is None


# ==========================================================================
# RULE 2 -- absence, failure and staleness are three different answers
# ==========================================================================


def test_a_disabled_source_is_not_an_error(monkeypatch):
    monkeypatch.setenv("SYNDICATE_ODDS_SOURCE_KALSHI_ENABLED", "0")
    result = collect_quotes("mlb", "2026-08-24", adapters={})
    assert result["by_source"]["kalshi"]["status"] == "disabled"


def test_a_refusal_is_not_an_error_and_carries_its_reason():
    """Novig's public tier CANNOT price a named bet -- a capability gap, not a
    broken feed. Rendering it as an error would send someone to debug a fetch
    that is working exactly as designed."""
    from syndicate.features.shared.venue_quote_adapters import novig_outcome

    outcome = novig_outcome("mlb", "2026-08-24")
    assert outcome.status == "refused"
    assert "anonymized" in outcome.reason


def test_an_adapter_that_raises_is_named_and_does_not_stop_the_others(monkeypatch):
    """One venue being unreachable must not cost the others' quotes -- the
    whole point is comparing across them."""
    def boom(_sport, _date):
        raise RuntimeError("connection reset")

    def good(_sport, _date):
        return SourceOutcome(source="oddsapi", status="ok", quotes=[_q("oddsapi")])

    monkeypatch.setenv("SYNDICATE_ODDS_SOURCE_NOVIG_ENABLED", "0")
    result = collect_quotes("mlb", "2026-08-24", adapters={
        "kalshi": boom, "polymarket_us": boom, "oddsapi": good,
    })
    assert result["by_source"]["kalshi"]["status"] == "error"
    assert "connection reset" in result["by_source"]["kalshi"]["reason"]
    assert result["by_source"]["oddsapi"]["status"] == "ok"
    assert result["keys"] == 1


# ==========================================================================
# RULE 3 -- zero rows is not success
# ==========================================================================


def test_a_source_returning_zero_quotes_reports_no_rows_not_ok():
    """The sporting=0 / games=0 family of misreadings all came from a zero that
    looked like a working feed."""
    def empty(_sport, _date):
        return SourceOutcome(source="kalshi", status="ok", quotes=[])

    result = collect_quotes("mlb", "2026-08-24", adapters={"kalshi": empty})
    assert result["by_source"]["kalshi"]["status"] == "no_rows"


# ==========================================================================
# RULE 4 -- every selection carries its source
# ==========================================================================


def test_the_winning_source_is_counted(monkeypatch):
    monkeypatch.setenv("SYNDICATE_ODDS_SOURCE_NOVIG_ENABLED", "0")
    now = time.time()
    result = collect_quotes("mlb", "2026-08-24", now=now, adapters={
        "kalshi": lambda *_a: SourceOutcome("kalshi", "ok", quotes=[_q("kalshi", key="a", age=1, now=now)]),
        "polymarket_us": lambda *_a: SourceOutcome("polymarket_us", "ok", quotes=[_q("polymarket_us", key="b", age=1, now=now)]),
        "oddsapi": lambda *_a: SourceOutcome("oddsapi", "ok", quotes=[_q("oddsapi", key="a", age=9999, now=now)]),
    })
    # key "a" contested: kalshi 1s beats oddsapi 9999s. key "b" uncontested.
    assert result["selected_by_source"] == {"kalshi": 1, "polymarket_us": 1}


# ==========================================================================
# THE CEILING -- the number that predicts the downstream rejection
# ==========================================================================


def test_quotes_beyond_the_ceiling_are_COUNTED_before_the_gate_drops_them(monkeypatch):
    """MEASURED 2026-08-24: 75 of 255 candidates rejected `stale_beyond_sla`,
    and nothing upstream said it was coming. mlb's ceiling is 6h; a 14h quote
    must be visible as doomed HERE, one stage before the rejection."""
    monkeypatch.setenv("SYNDICATE_ODDS_SOURCE_NOVIG_ENABLED", "0")
    now = time.time()
    result = collect_quotes("mlb", "2026-08-24", now=now, adapters={
        "kalshi": lambda *_a: SourceOutcome("kalshi", "ok", quotes=[
            _q("kalshi", key="fresh", age=60, now=now),
            _q("kalshi", key="stale", age=14 * 3600, now=now),
        ]),
    })
    assert result["ceiling_seconds"] == 6 * 3600
    assert result["within_ceiling"] == 1
    assert result["beyond_ceiling"] == 1


def test_the_ceiling_comes_from_the_engine_that_will_apply_it():
    """Reimplementing it here would let the two numbers drift apart silently --
    a fan-in emitting quotes the gate then rejects."""
    assert mod.freshness_ceiling_seconds("mlb") == 6 * 3600
    assert mod.freshness_ceiling_seconds("wnba") == 6 * 3600
    assert mod.freshness_ceiling_seconds("soccer") == 24 * 3600


# ==========================================================================
# THE SEAM -- stamping the field the gate actually reads
# ==========================================================================


def test_stamping_sets_the_field_the_freshness_gate_reads():
    """`_candidate_age_seconds` reads `last_updated` first, `updated_epoch`
    second. A candidate priced from a live quote but still carrying last
    night's timestamp is rejected while holding a price seconds old."""
    now = time.time()
    stamped = stamp_candidate_freshness(
        {"name": "Yankees", "last_updated": "2026-08-23T08:00:00Z"},
        _q("kalshi", age=5.0, now=now),
    )
    assert stamped["updated_epoch"] == pytest.approx(now - 5.0, abs=1.0)
    assert stamped["last_updated"].endswith("Z")
    assert stamped["price_source"] == "kalshi"
    assert stamped["venue_ref"] == "kalshi-ref"


def test_a_missing_quote_does_NOT_refresh_the_timestamp():
    """Stamping without a price would launder a stale candidate as fresh --
    worse than an honest stale one, because it defeats the gate rather than
    passing it."""
    original = {"name": "Yankees", "last_updated": "2026-08-23T08:00:00Z"}
    assert stamp_candidate_freshness(original, None) == original


def test_stamping_does_not_mutate_the_input():
    original = {"last_updated": "2026-08-23T08:00:00Z"}
    stamp_candidate_freshness(original, _q("kalshi"))
    assert original["last_updated"] == "2026-08-23T08:00:00Z"
