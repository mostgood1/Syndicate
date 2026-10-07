"""Today's Layer 2 on its own cadence; Kalshi off the board build's critical path.

Lane `web-restart-healthz` `[2026-10-07]`, user decisions "go ahead with #1" and "Approve
both". Fleet measurements that day: today's shortlist was written only mid-way through
each full build (10-80 min) and around the hourly next-day build; the build also spent
37-115 s in `kalshi_odds_refresh` + 10-100 s in `kalshi_board_join` after the shortlist,
work `venue_odds_loop` already owns. The join's side effects (Kalshi quotes ->
`book_quotes`, board demand) must keep happening -- now from the venue loop.

Reachability first (model-engine standard): each switch is shown to change behaviour.
"""

from __future__ import annotations

import threading
import time

import pytest

import pipeline.intelligence_state as ist
import pipeline.venue_odds_loop as vol
from pipeline.intelligence_state import IntelligenceStateService


@pytest.fixture
def svc(monkeypatch):
    s = object.__new__(IntelligenceStateService)
    s._layer2_fast_refresh_at = {}
    s._execution_guard = threading.Lock()
    calls = []

    def fake_fast(date):
        calls.append(date)
        s._mark_layer2_fast_refresh(date, time.time())
        return {"rows": [1]}

    s._refresh_layer2_shortlist_only = fake_fast
    s.calls = calls
    monkeypatch.setattr(ist, "central_today_iso", lambda: "2026-10-07")
    monkeypatch.setattr(ist, "_mlb_sim_subprocess_running", lambda: False)
    monkeypatch.delenv("SYNDICATE_LAYER2_TODAY_REFRESH_SECONDS", raising=False)
    return s


# ---- #1: today's cadence -------------------------------------------------------

def test_on_vs_off_reachability(svc, monkeypatch):
    assert svc._refresh_today_layer2_on_cadence() == "yes"           # never refreshed -> runs
    assert svc.calls == ["2026-10-07"]
    svc._layer2_fast_refresh_at = {}
    monkeypatch.setenv("SYNDICATE_LAYER2_TODAY_REFRESH_SECONDS", "0")
    assert svc._refresh_today_layer2_on_cadence() == "disabled"
    assert svc.calls == ["2026-10-07"]                               # off != on


def test_fresh_today_is_left_alone_and_stale_is_refreshed(svc):
    svc._mark_layer2_fast_refresh("2026-10-07", time.time() - 60)
    assert svc._refresh_today_layer2_on_cadence() == "fresh"
    svc._mark_layer2_fast_refresh("2026-10-07", time.time() - 400)     # default limit 300 s
    assert svc._refresh_today_layer2_on_cadence() == "yes"


def test_a_build_in_flight_wins_the_guard(svc):
    svc._execution_guard.acquire()
    try:
        assert svc._refresh_today_layer2_on_cadence() == "held:board_build_in_flight"
    finally:
        svc._execution_guard.release()
    assert svc.calls == []


def test_a_resident_mlb_sim_holds_it(svc, monkeypatch):
    monkeypatch.setattr(ist, "_mlb_sim_subprocess_running", lambda: True)
    assert svc._refresh_today_layer2_on_cadence() == "held:sim_subprocess_resident"
    assert not svc._execution_guard.locked()


def test_the_loop_tick_calls_it():
    import inspect

    assert "self._refresh_today_layer2_on_cadence()" in inspect.getsource(IntelligenceStateService._background_loop)


# ---- Kalshi off the critical path ---------------------------------------------

@pytest.mark.parametrize("env,running,expected", [
    ("1", True, True), ("0", False, False),
    (None, True, False),   # loop alive -> the build skips Kalshi
    (None, False, True),   # loop NOT alive -> nothing else would refresh it: inline
])
def test_kalshi_inline_gate(monkeypatch, env, running, expected):
    if env is None:
        monkeypatch.delenv("SYNDICATE_BOARD_BUILD_KALSHI_INLINE", raising=False)
    else:
        monkeypatch.setenv("SYNDICATE_BOARD_BUILD_KALSHI_INLINE", env)
    monkeypatch.setattr(vol, "venue_odds_loop_running", lambda: running)
    assert ist._board_build_kalshi_inline() is expected


def test_venue_loop_joins_today_and_next_two_days_interval_gated(monkeypatch):
    joined = []
    import pipeline.kalshi_odds_refresh as kor
    import syndicate.features.shared.timezone as tz

    shortlists = {"2026-10-07": {"rows": [{"a": 1}]}, "2026-10-08": {"rows": [{"b": 2}]}, "2026-10-09": None}
    monkeypatch.setattr(ist, "read_layer2_shortlist", lambda d: shortlists.get(d))
    monkeypatch.setattr(kor, "join_to_board", lambda m, r, selected_date=None: joined.append((selected_date, len(r))))
    monkeypatch.setattr(tz, "central_today_iso", lambda: "2026-10-07")
    monkeypatch.setattr(vol, "_LAST_KALSHI_COVERAGE_AT", [float("-inf")])
    monkeypatch.delenv("SYNDICATE_KALSHI_BOARD_COVERAGE_SECONDS", raising=False)

    vol._maybe_kalshi_board_coverage({"markets": [{"m": 1}]})
    assert joined == [("2026-10-07", 1), ("2026-10-08", 1)]           # 10-09 has no shortlist
    vol._maybe_kalshi_board_coverage({"markets": [{"m": 1}]})
    assert len(joined) == 2                                            # 600 s gate holds
    monkeypatch.setenv("SYNDICATE_KALSHI_BOARD_COVERAGE_SECONDS", "0")
    vol._LAST_KALSHI_COVERAGE_AT[0] = float("-inf")
    vol._maybe_kalshi_board_coverage({"markets": [{"m": 1}]})
    assert len(joined) == 2                                            # 0 = off


def test_venue_loop_coverage_never_raises(monkeypatch):
    monkeypatch.setattr(vol, "_LAST_KALSHI_COVERAGE_AT", [float("-inf")])
    monkeypatch.setattr(ist, "read_layer2_shortlist", lambda d: (_ for _ in ()).throw(RuntimeError("boom")))
    vol._maybe_kalshi_board_coverage({"markets": [{"m": 1}]})          # logged, not raised
