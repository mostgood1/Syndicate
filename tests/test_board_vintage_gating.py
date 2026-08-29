"""`#603`: a date sets the board's age only if it put rows on it. `[2026-08-29]`

THE BUG. `state_meta.computed_at` is the OLDEST contributing artifact stamp, and
it was collected for every date that had a stored payload -- including one the
BUILDER had correctly decided not to build. Measured 2026-08-29:
`SCHEDULE_RECONCILE_CHECK date=2026-08-30 scheduled_games=0` and
`BETTING_PAYLOAD_READ date=2026-08-30 exists=False`, so tomorrow was never built,
while the read side ("deliberately does NOT filter") kept feeding tomorrow's
hours-old stamp to `computed_at`. The displayed age was pinned by a date carrying
NO ROWS, which is why three config changes and two verified performance fixes
never moved it.

WHY NOT AN AVAILABILITY FILTER. Filtering requested dates by
`_supported_intelligence_dates()` is the obvious fix and regresses a known case:
WNBA's 2026-07-28 board built 36 real candidates while `wnba_available_dates()`
did not list that date. Gating on ROWS keeps that board and its vintage, while an
empty date -- which shows the user nothing -- can no longer make the board stale.
"""

from __future__ import annotations

import pytest

from pipeline import intelligence_state as S


def _payload(stamp: str, rows_by_sport: dict) -> dict:
    # `state_last_updated` is the first key `_state_payload_timestamp` reads.
    # `computed_at` is NOT one of them -- using it produced a null stamp and a
    # test that failed for a fixture reason, not a code reason.
    return {"state_last_updated": stamp, "by_sport": rows_by_sport}


def _row(sport: str = "mlb"):
    return {"sport": sport, "market": "h2h", "selection": "X"}


@pytest.fixture
def combined(monkeypatch):
    """Drive read_combined_intelligence_response over fabricated per-date state."""
    store: dict[str, dict] = {}
    # THE RESPONSE CACHE IS KEYED ON (dates, sport, limit) AND WOULD HAND TEST 2
    # TEST 1's ANSWER. Cleared per test rather than varying the dates, because
    # the dates are part of what is under test.
    S._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
    monkeypatch.setattr(S, "_read_single_date_response_for_combining", lambda d: store.get(d))
    monkeypatch.setattr(S, "_layer2_fallback_recommendations", lambda dates, vintages=None: [])
    monkeypatch.setattr(S, "board_l2a_fallback_enabled", lambda: False)
    return store


OLD = "2026-08-29T10:00:00Z"
NEW = "2026-08-29T17:45:00Z"


def test_an_empty_future_date_no_longer_pins_the_age(combined, monkeypatch):
    """THE REGRESSION TEST FOR THE REPORTED SYMPTOM."""
    combined["2026-08-29"] = _payload(NEW, {"mlb": [_row()]})
    combined["2026-08-30"] = _payload(OLD, {})          # built long ago, no rows
    out = S.read_combined_intelligence_response(dates=["2026-08-29", "2026-08-30"], sport="all")
    assert out["state_meta"]["computed_at"] == NEW, out["state_meta"]
    assert out["state_meta"]["artifacts_dated"] == 1


def test_a_stale_date_that_IS_showing_rows_still_counts(combined):
    """Not a miss -- the honest reading. The board really is showing old rows."""
    combined["2026-08-29"] = _payload(NEW, {"mlb": [_row()]})
    combined["2026-08-30"] = _payload(OLD, {"mlb": [_row()]})
    out = S.read_combined_intelligence_response(dates=["2026-08-29", "2026-08-30"], sport="all")
    assert out["state_meta"]["computed_at"] == OLD, out["state_meta"]
    assert out["state_meta"]["artifacts_dated"] == 2


def test_the_wnba_case_keeps_both_its_rows_and_its_vintage(combined):
    """A date absent from availability but carrying real candidates is a real
    board. Gating on rows -- not on availability -- is what preserves it."""
    combined["2026-08-29"] = _payload(NEW, {"wnba": [_row("wnba") for _ in range(36)]})
    out = S.read_combined_intelligence_response(dates=["2026-08-29"], sport="all")
    assert out["state_meta"]["computed_at"] == NEW
    assert out["state_meta"]["artifacts_dated"] == 1


def test_all_dates_empty_leaves_the_verdict_unknown_not_fresh(combined):
    """`is_fresh` must stay None when nothing could be dated -- "we could not
    tell" and "we checked and it is fine" are different facts."""
    combined["2026-08-29"] = _payload(NEW, {})
    out = S.read_combined_intelligence_response(dates=["2026-08-29"], sport="all")
    assert out["state_meta"]["computed_at"] is None
    assert out["state_meta"]["is_fresh"] is None
    assert out["state_meta"]["artifacts_dated"] == 0


def test_rows_from_the_empty_date_are_still_merged_when_it_has_any(combined):
    combined["2026-08-29"] = _payload(NEW, {"mlb": [_row()]})
    combined["2026-08-30"] = _payload(OLD, {"nfl": [_row("nfl")]})
    out = S.read_combined_intelligence_response(dates=["2026-08-29", "2026-08-30"], sport="all")
    assert out["by_date"]["2026-08-30"]["candidate_count"] == 1
