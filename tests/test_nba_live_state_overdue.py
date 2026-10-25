"""A started NBA game is never held at pregame by a stale live-state snapshot (lane `nba-live-state-overdue`, 2026-10-23).

10-23: the snapshot written at 6:09 PM CT held the six 6 PM games as "7:00 PM EDT", not started, while CHI @ MIL read
Final. Final counts as progress, so for 20 minutes `_best_live_state_payload` trusted the snapshot, never asked ESPN, and
every 6 PM chip and board row stayed pregame until ~6:34 PM.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from syndicate.features.nba import cards as c


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def _snapshot(now: datetime, *, tip_offset_min: float) -> dict:
    """Tonight's shape: an early game Final, a later game not started per the snapshot, written 5 minutes ago."""
    return {"date": now.date().isoformat(), "source": "espn_live_fetch", "generated_at": _iso(now - timedelta(minutes=5)),
            "games": [
                {"away": "CHI", "home": "MIL", "status": "Final", "status_id": 3, "in_progress": False, "final": True},
                {"away": "NY", "home": "BOS", "status": "later", "status_id": 1, "in_progress": False, "final": False,
                 "start_time": _iso(now + timedelta(minutes=tip_offset_min))},
            ]}


def _espn(now: datetime) -> dict:
    return {"date": now.date().isoformat(), "source": "espn_live_fetch", "generated_at": _iso(now),
            "games": [{"away": "NY", "home": "BOS", "status": "4:30 - 1st", "status_id": 2, "in_progress": True,
                       "final": False}]}


def test_a_started_game_still_pregame_in_a_fresh_snapshot_goes_to_espn(monkeypatch):
    now = datetime.now(timezone.utc)
    asked = []
    monkeypatch.setattr(c, "_espn_live_state_payload", lambda day: asked.append(day) or _espn(now))
    # The tip passed 10 minutes ago; the snapshot is 5 minutes old and has progress (the Final).
    monkeypatch.setattr(c, "_local_live_state_payload", lambda day: _snapshot(now, tip_offset_min=-10))
    best = c._best_live_state_payload(now.date().isoformat())
    assert asked and best["games"][0]["in_progress"] is True


def test_a_fresh_snapshot_whose_games_have_not_started_is_kept():
    now = datetime.now(timezone.utc)
    snap = _snapshot(now, tip_offset_min=+30)
    assert c._payload_has_overdue_pregame(snap, now) is False                    # off: nothing overdue
    assert c._payload_has_overdue_pregame(_snapshot(now, tip_offset_min=-1), now) is True   # on


def test_the_fresh_snapshot_is_returned_without_asking_espn_when_nothing_is_overdue(monkeypatch):
    now = datetime.now(timezone.utc)
    asked = []
    monkeypatch.setattr(c, "_espn_live_state_payload", lambda day: asked.append(day) or _espn(now))
    snap = _snapshot(now, tip_offset_min=+30)
    monkeypatch.setattr(c, "_local_live_state_payload", lambda day: snap)
    assert c._best_live_state_payload(now.date().isoformat()) is snap and asked == []


def test_a_snapshot_written_before_start_time_was_stamped_reads_the_status_text():
    # ESPN's scheduled shortDetail: 7:00 PM EDT on 10/23 is 23:00Z; EST in winter is UTC-5.
    assert c._snapshot_game_start({"status": "10/23 - 7:00 PM EDT"}, 2026) == datetime(2026, 10, 23, 23, 0, tzinfo=timezone.utc)
    assert c._snapshot_game_start({"status": "1/5 - 10:30 PM EST"}, 2027) == datetime(2027, 1, 6, 3, 30, tzinfo=timezone.utc)
    assert c._snapshot_game_start({"status": "Final"}, 2026) is None
    after_tip = datetime(2026, 10, 23, 23, 20, tzinfo=timezone.utc)
    snap = {"date": "2026-10-23", "games": [
        {"away": "CHI", "home": "MIL", "status": "Final", "status_id": 3, "final": True},
        {"away": "NY", "home": "BOS", "status": "10/23 - 7:00 PM EDT", "status_id": 1, "in_progress": False, "final": False}]}
    assert c._payload_has_overdue_pregame(snap, after_tip) is True
    assert c._payload_has_overdue_pregame(snap, datetime(2026, 10, 23, 22, 50, tzinfo=timezone.utc)) is False


def test_espn_rows_carry_their_scheduled_start(monkeypatch):
    import io
    import json

    body = {"events": [{"id": "1", "date": "2026-10-23T23:00Z", "competitions": [{
        "status": {"type": {"state": "pre", "shortDetail": "10/23 - 7:00 PM EDT"}},
        "competitors": [{"homeAway": "home", "team": {"abbreviation": "BOS"}, "score": "0"},
                        {"homeAway": "away", "team": {"abbreviation": "NY"}, "score": "0"}]}]}]}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(c.urllib_request, "urlopen", lambda req, timeout=5: _Resp(json.dumps(body).encode()))
    payload = c._espn_live_state_payload("2026-10-23")
    assert payload["games"][0]["start_time"] == "2026-10-23T23:00Z"


def test_the_bypass_is_logged_once_per_snapshot_and_says_when_it_decided(monkeypatch, capsys):
    now = datetime.now(timezone.utc)
    c._OVERDUE_NOTED.clear()
    monkeypatch.setattr(c, "_espn_live_state_payload", lambda day: _espn(now))
    snap = _snapshot(now, tip_offset_min=-10)                         # fresh, has progress, a started game pregame
    monkeypatch.setattr(c, "_local_live_state_payload", lambda day: snap)
    c._best_live_state_payload(now.date().isoformat())
    c._best_live_state_payload(now.date().isoformat())
    lines = [l for l in capsys.readouterr().out.splitlines() if "LIVE_STATE_OVERDUE_BYPASS" in l]
    assert len(lines) == 1 and "decided_by_overdue=True" in lines[0]
