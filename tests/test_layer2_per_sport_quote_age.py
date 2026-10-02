"""The 1h freshness rule, applied per sport (lane `layer2-freshness-1h`, 2026-10-02).

User: "Last polled <=1h" across all sports, sport by sport as each one's pregame
sweep gets fast enough; "build the per-sport gate". NHL and WNBA sweep every
30/35 min since 2026-10-02 17:46Z, so they move to 1h first; every other sport
keeps the global 14h ceiling until its cadence is done.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import layer2_board
from syndicate.features.shared.layer2_board import select_shortlist

_NOW = datetime(2026, 10, 2, 19, 0, tzinfo=timezone.utc)


def _row(*, sport, seen, ev=1.0):
    return {
        "sport": sport,
        "kind": "game",
        "ev_pct": ev,
        "commence_time": (_NOW + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
        "quote": {"quote_seen_age_seconds": seen, "book_age_seconds": seen},
        "score": {"score": ev},
    }


@pytest.fixture(autouse=True)
def _no_overrides(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("SYNDICATE_SHORTLIST_MAX_QUOTE_AGE_SECONDS"):
            monkeypatch.delenv(key, raising=False)


def test_reachability_nhl_and_wnba_are_gated_at_one_hour_while_nfl_keeps_fourteen():
    two_hours = 7200.0
    rows = [_row(sport="nhl", seen=two_hours), _row(sport="wnba", seen=two_hours), _row(sport="nfl", seen=two_hours)]
    out = select_shortlist(rows, now=_NOW)
    assert [r["sport"] for r in out["rows"]] == ["nfl"]
    assert out["rows_beyond_quote_age"] == 2
    assert out["rows_beyond_quote_age_by_sport"] == {"nhl": 1, "wnba": 1}
    assert out["max_quote_age_seconds_by_sport"] == {"nhl": 3600.0, "wnba": 3600.0}
    assert out["max_quote_age_seconds"] == 14 * 3600


def test_a_quote_polled_within_the_hour_survives():
    out = select_shortlist([_row(sport="nhl", seen=55 * 60.0), _row(sport="wnba", seen=30 * 60.0)], now=_NOW)
    assert sorted(r["sport"] for r in out["rows"]) == ["nhl", "wnba"]
    assert out["rows_beyond_quote_age"] == 0


def test_a_sport_moves_to_one_hour_by_config(monkeypatch):
    monkeypatch.setenv("SYNDICATE_SHORTLIST_MAX_QUOTE_AGE_SECONDS_NFL", "3600")
    out = select_shortlist([_row(sport="nfl", seen=7200.0)], now=_NOW)
    assert out["rows"] == []
    assert out["rows_beyond_quote_age_by_sport"] == {"nfl": 1}
    assert out["max_quote_age_seconds_by_sport"]["nfl"] == 3600.0


def test_an_explicit_ceiling_still_applies_to_every_sport():
    out = select_shortlist([_row(sport="nhl", seen=7200.0)], now=_NOW, max_quote_age_seconds=14 * 3600)
    assert [r["sport"] for r in out["rows"]] == ["nhl"]
    assert out["max_quote_age_seconds_by_sport"] == {}


def test_an_unknown_age_is_still_not_excluded():
    row = _row(sport="nhl", seen=None)
    row["quote"] = {}
    out = select_shortlist([row], now=_NOW)
    assert len(out["rows"]) == 1


def test_the_table_is_what_the_lane_measured():
    assert layer2_board.SHORTLIST_MAX_QUOTE_AGE_BY_SPORT == {"nhl": 3600.0, "wnba": 3600.0}
