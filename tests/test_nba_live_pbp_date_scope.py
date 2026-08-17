"""`#456` — NBA live pbp must not serve a snapshot from another day.

MEASURED IN PRODUCTION 2026-08-16, which is what these pin:

    /nba/api/live_pbp_stats?date=2026-08-16 -> payload date 2026-06-13
    /nba/api/live_pbp_stats?date=2026-03-01 -> payload date 2026-06-13
    /nba/api/live_pbp_stats?date=2025-12-25 -> payload date 2026-06-13

The snapshot lives at ONE undated path, so every request got the same two-month
-stale payload under whatever date was asked for. It looked harmless only
because the offseason snapshot carries no games; in season the identical path
returns one day's games labelled with another day's date.
"""

from __future__ import annotations

from typing import Any

import pytest

from syndicate.features.nba import live_lens


def _payload(date: str, *event_ids: str) -> dict[str, Any]:
    return {
        "ok": True,
        "ttl": 20,
        "date": date,
        "games": [{"event_id": eid, "game_id": eid, "pbp_quarters": {"current": {"period": 2}}}
                  for eid in event_ids],
    }


@pytest.fixture
def stub_snapshot(monkeypatch):
    """Install a snapshot payload as if it were the single stored file."""

    def install(payload):
        monkeypatch.setattr(live_lens, "read_latest_live_lens_snapshot", lambda: {"x": 1})
        monkeypatch.setattr(live_lens, "_coerce_snapshot_payload", lambda *a, **k: payload)

    return install


# --------------------------------------------------------------------------
# the predicate
# --------------------------------------------------------------------------


def test_snapshot_date_matches_is_exact():
    assert live_lens._snapshot_date_matches(_payload("2026-06-13"), "2026-06-13") == (True, "2026-06-13")
    assert live_lens._snapshot_date_matches(_payload("2026-06-13"), "2026-08-16") == (False, "2026-06-13")


def test_an_absent_date_on_either_side_cannot_be_compared_and_is_not_a_mismatch():
    """Nothing to compare is not the same as a mismatch.

    Turning "unknown" into a refusal would empty the endpoint for every caller
    that does not pass a date.
    """
    assert live_lens._snapshot_date_matches(_payload(""), "2026-08-16")[0] is True
    assert live_lens._snapshot_date_matches(_payload("2026-06-13"), "")[0] is True


def test_snapshot_date_matches_never_raises():
    for bad in (None, "", 0, [], object()):
        assert live_lens._snapshot_date_matches(bad, "2026-08-16") == (False, None)


# --------------------------------------------------------------------------
# the fix, on the path the endpoint actually uses
# --------------------------------------------------------------------------


def test_a_stale_snapshot_is_refused_when_fallback_is_off(stub_snapshot):
    """THE PRODUCTION CASE. `nba.py:_allow_stored_date_fallback()` returns False,
    so this is the branch the live endpoint takes."""
    stub_snapshot(_payload("2026-06-13", "401", "402"))
    out = live_lens.read_latest_live_pbp_stats_payload(
        "2026-08-16", [], ttl=20, allow_stored_date_fallback=False
    )
    assert out["games"] == []
    assert out["empty_reason"] == "snapshot_date_mismatch"
    assert out["snapshot_date"] == "2026-06-13"
    assert out["date"] == "2026-08-16"


def test_the_stale_games_are_not_leaked_under_the_requested_date(stub_snapshot):
    """The dangerous in-season case: the June snapshot HAS games.

    Before the fix these two event ids came back labelled 2026-08-16.
    """
    stub_snapshot(_payload("2026-06-13", "401", "402"))
    out = live_lens.read_latest_live_pbp_stats_payload(
        "2026-08-16", [], ttl=20, allow_stored_date_fallback=False
    )
    assert [g.get("event_id") for g in out["games"]] == []


def test_a_matching_snapshot_is_served_unchanged(stub_snapshot):
    """Guards against the fix emptying the endpoint on the healthy path."""
    stub_snapshot(_payload("2026-08-16", "401", "402"))
    out = live_lens.read_latest_live_pbp_stats_payload(
        "2026-08-16", [], ttl=20, allow_stored_date_fallback=False
    )
    assert [g["event_id"] for g in out["games"]] == ["401", "402"]
    assert "empty_reason" not in out
    assert out.get("stored_date_fallback") is None


def test_fallback_true_still_serves_but_marks_it(stub_snapshot):
    """`allow_stored_date_fallback` used to be discarded outright.

    Honouring it means a caller that WANTS the latest stored slate still gets
    it -- but the payload says so, so a reader can tell a fallback from a match.
    """
    stub_snapshot(_payload("2026-06-13", "401"))
    out = live_lens.read_latest_live_pbp_stats_payload(
        "2026-03-01", [], ttl=20, allow_stored_date_fallback=True
    )
    assert [g["event_id"] for g in out["games"]] == ["401"]
    assert out["stored_date_fallback"] is True
    assert out["snapshot_date"] == "2026-06-13"
    assert out["requested_date"] == "2026-03-01"


def test_absent_snapshot_still_returns_the_empty_payload(monkeypatch):
    monkeypatch.setattr(live_lens, "read_latest_live_lens_snapshot", lambda: None)
    out = live_lens.read_latest_live_pbp_stats_payload("2026-08-16", ["401"], ttl=20)
    assert out["ok"] is True
    assert len(out["games"]) == 1
    assert out["games"][0]["pbp_quarters"]["current"]["period"] is None


def test_event_id_filtering_still_works_on_a_matching_snapshot(stub_snapshot):
    stub_snapshot(_payload("2026-08-16", "401", "402", "403"))
    out = live_lens.read_latest_live_pbp_stats_payload(
        "2026-08-16", ["402"], ttl=20, allow_stored_date_fallback=False
    )
    assert [g["event_id"] for g in out["games"]] == ["402"]
