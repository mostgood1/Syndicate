"""Tests for `syndicate.features.soccer.ingestion.fotmob_momentum`.

Every failure path must return `{"supported": False, "reason": ...}` rather
than raise -- one match's FotMob join or fetch failure must never take down a
whole league's live-state poll. Every success path must return `current` and
`series` clock-bounded to `as_of_seconds`, matching the retired ESPN
`_momentum_block`'s contract exactly, so `cards.py` needed no shape changes.
"""

from __future__ import annotations

from syndicate.features.soccer.ingestion.fotmob_momentum import fotmob_momentum_block

_SAMPLE_PAYLOAD = {
    "content": {
        "momentum": {
            "main": {
                "data": [
                    {"minute": 0, "value": 0.0},
                    {"minute": 10, "value": 12.0},
                    {"minute": 20, "value": -8.0},
                    {"minute": 30, "value": 45.0},
                    {"minute": 40, "value": 62.0},
                    {"minute": 50, "value": -30.0},
                ]
            }
        }
    }
}


def _resolve_ok(**_kwargs):
    return 4193843


def _resolve_none(**_kwargs):
    return None


def _fetch_sample(_url: str):
    return _SAMPLE_PAYLOAD


def test_unresolved_match_returns_unsupported_with_reason():
    out = fotmob_momentum_block(
        league="epl", home_team="A", away_team="B", iso_date="2026-08-22",
        as_of_seconds=1800.0, _resolve=_resolve_none,
    )
    assert out["supported"] is False
    assert "unresolved" in out["reason"]
    assert out["current"] is None
    assert out["series"] == []


def test_resolved_match_clock_bounds_series_to_as_of_seconds():
    # as_of = 25 min = 1500s: samples at 0, 10, 20 min are visible; 30/40/50 are not.
    out = fotmob_momentum_block(
        league="epl", home_team="A", away_team="B", iso_date="2026-08-22",
        as_of_seconds=1500.0, _resolve=_resolve_ok, _fetch=_fetch_sample,
    )
    assert out["supported"] is True
    assert out["source"] == "fotmob"
    assert out["fotmob_match_id"] == 4193843
    assert [p["t"] for p in out["series"]] == [0, 600, 1200]
    assert out["current"] == -8.0, "current must be the LAST sample at-or-before the clock"


def test_current_never_reads_past_the_live_clock():
    # This is the leakage guard: an implementation that used the final series
    # value regardless of `as_of_seconds` would show pressure from AFTER the
    # instant the card claims to describe.
    out = fotmob_momentum_block(
        league="epl", home_team="A", away_team="B", iso_date="2026-08-22",
        as_of_seconds=600.0, _resolve=_resolve_ok, _fetch=_fetch_sample,
    )
    assert out["current"] == 12.0
    assert all(p["t"] <= 600 for p in out["series"])


def test_no_as_of_seconds_falls_back_to_full_series():
    out = fotmob_momentum_block(
        league="epl", home_team="A", away_team="B", iso_date="2026-08-22",
        as_of_seconds=None, _resolve=_resolve_ok, _fetch=_fetch_sample,
    )
    assert out["supported"] is True
    assert out["current"] == -30.0
    assert len(out["series"]) == 6


def test_empty_momentum_payload_is_unsupported_not_a_crash():
    def fetch_empty(_url: str):
        return {"content": {"momentum": {"main": {"data": []}}}}

    out = fotmob_momentum_block(
        league="epl", home_team="A", away_team="B", iso_date="2026-08-22",
        as_of_seconds=1000.0, _resolve=_resolve_ok, _fetch=fetch_empty,
    )
    assert out["supported"] is False
    assert "empty" in out["reason"]


def test_fetch_exception_is_swallowed_not_raised():
    def fetch_raises(_url: str):
        raise RuntimeError("simulated FotMob 500")

    out = fotmob_momentum_block(
        league="epl", home_team="A", away_team="B", iso_date="2026-08-22",
        as_of_seconds=1000.0, _resolve=_resolve_ok, _fetch=fetch_raises,
    )
    assert out["supported"] is False
    assert "RuntimeError" in out["reason"]


def test_as_of_before_any_sample_is_supported_but_empty():
    out = fotmob_momentum_block(
        league="epl", home_team="A", away_team="B", iso_date="2026-08-22",
        as_of_seconds=-5.0, _resolve=_resolve_ok, _fetch=_fetch_sample,
    )
    assert out["supported"] is True
    assert out["current"] == 0.0
    assert out["series"] == []
