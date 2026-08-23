"""`live_event_ids` and the state breakdown that says WHY nothing was captured.

**`events_total=4 live_events=0` HAS THREE DIFFERENT MEANINGS AND ONE
RENDERING.** It reads identically for "none have tipped yet" (wait), "all four
have finished" (nothing wrong), and "ESPN never advanced the state off `pre`"
(a bug). On 2026-08-23 the WNBA slate logged exactly that line from mid-afternoon
to evening and there was no way to tell which of the three it was without another
deploy.

That is the same ambiguity `events_total` was added to remove one level up --
it separated "none tipped" from "the scoreboard call returned nothing", and
thereby surfaced a 403 that had been silent. `SCOREBOARD_STATES` removes the
next one down.
"""

from __future__ import annotations

import pytest

import scripts.poll_basketball_momentum as poller


def _event(event_id: str, state: str | None) -> dict:
    status_type: dict = {} if state is None else {"state": state}
    return {"id": event_id, "status": {"type": status_type}}


@pytest.fixture
def scoreboard(monkeypatch):
    """Install a scoreboard payload and capture the URL it was asked for."""
    def _install(events):
        seen: dict = {}

        def _fake_get_json(url, **kwargs):
            seen["url"] = url
            return {"events": events}

        monkeypatch.setattr(poller, "_get_json", _fake_get_json)
        return seen
    return _install


def test_only_in_progress_games_are_returned(scoreboard, capsys) -> None:
    """A FINAL game has a complete feed and would render as though it were still
    being played. A SCHEDULED one has nothing. Only `in` may pass."""
    scoreboard([_event("1", "pre"), _event("2", "in"),
                _event("3", "post"), _event("4", "in")])
    assert poller.live_event_ids("wnba", "2026-08-23") == ["2", "4"]


def test_state_breakdown_separates_not_tipped_from_all_finished(scoreboard, capsys) -> None:
    """**THE POINT OF THE LINE.** Both slates return zero live events. They must
    not log the same thing."""
    scoreboard([_event(str(i), "pre") for i in range(4)])
    assert poller.live_event_ids("wnba", "2026-08-23") == []
    not_tipped = capsys.readouterr().out
    assert "SCOREBOARD_STATES" in not_tipped
    assert "pre=4" in not_tipped, not_tipped

    scoreboard([_event(str(i), "post") for i in range(4)])
    assert poller.live_event_ids("wnba", "2026-08-23") == []
    finished = capsys.readouterr().out
    assert "post=4" in finished, finished

    assert not_tipped != finished, (
        "four scheduled games and four finished games must not render identically "
        "-- that indistinguishability is the entire reason this line exists")


def test_a_mixed_slate_reports_every_state(scoreboard, capsys) -> None:
    scoreboard([_event("1", "pre"), _event("2", "in"),
                _event("3", "post"), _event("4", "post")])
    poller.live_event_ids("wnba", "2026-08-23")
    out = capsys.readouterr().out
    assert "pre=1" in out and "in=1" in out and "post=2" in out, out


def test_a_missing_state_is_named_not_silently_skipped(scoreboard, capsys) -> None:
    """An event whose status carries no state is a feed change, not a scheduled
    game. Bucketing it into `pre` would hide exactly that."""
    scoreboard([_event("1", None), _event("2", "in")])
    assert poller.live_event_ids("wnba", "2026-08-23") == ["2"]
    out = capsys.readouterr().out
    assert "ABSENT=1" in out, out


def test_an_empty_scoreboard_logs_the_total_and_no_state_line(scoreboard, capsys) -> None:
    """With no events there are no states to break down, and printing an empty
    breakdown would read as a successful call that found nothing -- which is the
    ambiguity `events_total` already covers."""
    scoreboard([])
    assert poller.live_event_ids("wnba", "2026-08-23") == []
    out = capsys.readouterr().out
    assert "events_total=0" in out
    assert "SCOREBOARD_STATES" not in out, out


def test_absent_events_key_is_reported_as_absent_not_zero(scoreboard, monkeypatch, capsys) -> None:
    """`events_total=0` and a payload with no `events` key at all are different
    failures -- the second one is what a 403 looked like."""
    monkeypatch.setattr(poller, "_get_json", lambda url, **kw: {})
    assert poller.live_event_ids("wnba", "2026-08-23") == []
    assert "events_total=ABSENT" in capsys.readouterr().out


def test_it_asks_the_shared_scoreboard_url(scoreboard) -> None:
    """The URL is built in one place because building it twice produced
    `/sports/sports/` and HTTP 400 on every date of a season pull."""
    seen = scoreboard([_event("1", "in")])
    poller.live_event_ids("wnba", "2026-08-23")
    assert seen["url"] == poller.scoreboard_url("wnba", "2026-08-23")
    assert "/sports/sports/" not in seen["url"]
