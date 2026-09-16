"""ESPN refuses some scoreboard DATE RANGES with HTTP 400; single dates still answer.

Measured 2026-09-15 against the live endpoint (lane `soccer-player-substrate`):
  - `20260801-20260815` returned 400 on eng.2, ned.1 and usa.1;
  - the one-day range `20260815-20260815` returned 400 on all four slugs tried;
  - `20260915-20260915` returned 200;
  - every bare `YYYYMMDD` returned 200.
So the refusal depends on the dates, and it used to raise out of every caller.
`aggregate_season_player_stats` walks a season from 1 August in ranges, and died
on its first window.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from syndicate.features.soccer.ingestion import espn_lineups as el


def _payload(event_id: str, state: str = "post") -> dict:
    return {
        "events": [
            {
                "id": event_id,
                "date": "2026-08-15T14:00Z",
                "competitions": [
                    {
                        "status": {"type": {"state": state}},
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Home FC"}},
                            {"homeAway": "away", "team": {"displayName": "Away FC"}},
                        ],
                    }
                ],
            }
        ]
    }


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=response)


def _refuse_ranges(calls: list[str], *, state: str = "post"):
    def fake(league, *, date_range=None, timeout=20):
        calls.append(date_range)
        if date_range and "-" in date_range:
            raise _http_error(400)
        return _payload(f"e{date_range}", state=state)

    return fake


def test_a_REFUSED_range_is_retried_one_date_at_a_time():
    calls: list[str] = []
    with patch.object(el, "fetch_espn_scoreboard", side_effect=_refuse_ranges(calls)):
        events = el.fetch_events("championship", date_windows=["20260814-20260816"])
    assert calls == ["20260814-20260816", "20260814", "20260815", "20260816"]
    assert sorted(event["event_id"] for event in events) == ["e20260814", "e20260815", "e20260816"]


# RENAMED 2026-09-16: the artifact builder no longer sends a one-day range -- it
# sends the bare date, because ESPN now 400s every range (lane
# `soccer-espn-window-validation`). The BEHAVIOUR under test is unchanged and still
# matters: any caller that does send a one-day range pays exactly one retry.
def test_a_ONE_DAY_range_costs_one_retry():
    """`build_soccer_artifacts._fetch_fixtures` sends `YYYYMMDD-YYYYMMDD` for a
    single day. That exact shape returned 400 on 2026-08-15 for all four slugs
    tried, and a refusal was a failed build."""
    calls: list[str] = []
    with patch.object(el, "fetch_espn_scoreboard", side_effect=_refuse_ranges(calls)):
        events = el.fetch_events("epl", date_windows=["20260815-20260815"])
    assert calls == ["20260815-20260815", "20260815"]
    assert [event["event_id"] for event in events] == ["e20260815"]


def test_REACHABILITY_an_accepted_range_is_NOT_split():
    """`off != on`: on a date ESPN accepts, exactly the old single request."""
    calls: list[str] = []

    def fake(league, *, date_range=None, timeout=20):
        calls.append(date_range)
        return _payload("e1")

    with patch.object(el, "fetch_espn_scoreboard", side_effect=fake):
        el.fetch_events("epl", date_windows=["20260901-20260915"])
    assert calls == ["20260901-20260915"]


def test_a_NON_400_error_still_raises_and_is_not_split():
    """A 5xx is a different failure, and splitting it would multiply the load on
    a struggling endpoint."""
    calls: list[str] = []

    def fake(league, *, date_range=None, timeout=20):
        calls.append(date_range)
        raise _http_error(503)

    with patch.object(el, "fetch_espn_scoreboard", side_effect=fake):
        with pytest.raises(requests.HTTPError):
            el.fetch_events("epl", date_windows=["20260801-20260815"])
    assert calls == ["20260801-20260815"]


@pytest.mark.parametrize("window", ["garbage", "20260815", "20260816-20260801", "20260101-20261231"])
def test_a_400_on_something_that_is_not_a_bounded_range_still_raises(window):
    """Unknown must not default permissive: no guessing at dates for a
    malformed, reversed or implausibly wide window."""
    with patch.object(el, "fetch_espn_scoreboard", side_effect=lambda *a, **k: (_ for _ in ()).throw(_http_error(400))):
        with pytest.raises(requests.HTTPError):
            el.fetch_events("epl", date_windows=[window])


def test_the_status_filter_still_applies_to_fallback_results():
    calls: list[str] = []
    with patch.object(el, "fetch_espn_scoreboard", side_effect=_refuse_ranges(calls, state="pre")):
        assert el.fetch_events("epl", date_windows=["20260814-20260815"], statuses={"post"}) == []
        assert len(el.fetch_events("epl", date_windows=["20260814-20260815"], statuses={"pre"})) == 2
