"""#810 (lane college-live-pull-60s; user "fix the stale quote problem so flags can fire"): the NCAAB / WNCAAB
in-play lane pulls live full-game lines every 60 s, and the per-game half / quarter markets keep their own
240 s segment clock, so only the 3-credit bulk call repeats every minute.

Measured 11-15 before the change: the lane ran at interval_s=240, and once the pregame sweeps stopped at tip
that was the only OddsAPI look at a live college game -- 1 of 40 served live rows was priced on a quote
<= 120 s (the rail's MODEL != LINE rule), against 11 of 23 while the pregame sweep still looked every 40-90 s.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 11, 15, 18, 30, tzinfo=dt.timezone.utc)
MARKETS = "h2h,spreads,totals,spreads_h1,totals_h1,spreads_h2,totals_h2"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "refresh_ncaab_odds_history.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Adapter:
    def __init__(self, commence: dict[str, dt.datetime]):
        self.commence = commence
        self.calls: list[tuple] = []

    def iter_current_odds_expanded(self, *, markets, date_iso, bookmakers=None):
        self.calls.append(("bulk", markets))
        return [{"event_id": eid, "commence_time": ct, "period": "full_game", "market": "totals"} for eid, ct in self.commence.items()]

    def iter_event_odds(self, event_id, *, markets, bookmakers=None, fallback_full_game=True):
        self.calls.append(("event", event_id, markets))
        return [{"event_id": event_id, "period": "2h", "market": "totals"}]

    def event_calls(self) -> list[tuple]:
        return [c for c in self.calls if c[0] == "event"]


@pytest.fixture
def module(monkeypatch):
    for league in ("NCAAB", "WNCAAB"):
        monkeypatch.delenv(f"SYNDICATE_{league}_IN_PLAY_SEGMENT_INTERVAL_SECONDS", raising=False)
    return _load("ncaab_odds_cadence_810")


@pytest.fixture
def clock(module, monkeypatch):
    """An in-memory segment clock, one slot per league; `writes` records every advance."""
    state: dict[str, float] = {}
    writes: list[tuple[str, float]] = []
    monkeypatch.setattr(module, "_read_segment_clock", lambda league: state.get(league))

    def _write(league, moment):
        state[league] = moment.timestamp()
        writes.append((league, moment.timestamp()))

    monkeypatch.setattr(module, "_write_segment_clock", _write)
    return state, writes


def _pull(module, adapter, at, *, league="ncaab", segment_clock=True):
    return module._fetch_in_play_rows(adapter=adapter, markets=MARKETS, bookmakers=None, now=at, league=league,
                                      segment_clock=segment_clock)


def _live_adapter():
    return _Adapter({"live": NOW - dt.timedelta(minutes=20), "soon": NOW + dt.timedelta(minutes=10)})


# --- the lane's cadence -------------------------------------------------------------------------------------

@pytest.mark.parametrize("league", ["ncaab", "wncaab"])
def test_lane_interval_defaults_to_60_s_and_the_env_key_still_wins(league, monkeypatch):
    from syndicate.features.ncaab import inplay_lane

    key = f"SYNDICATE_{league.upper()}_LIVE_REFRESH_INTERVAL_SECONDS"
    monkeypatch.delenv(key, raising=False)
    assert inplay_lane.ncaab_live_refresh_interval_seconds(league) == 60
    monkeypatch.setenv(key, "240")   # off != on: the old cadence is one env key away
    assert inplay_lane.ncaab_live_refresh_interval_seconds(league) == 240
    monkeypatch.setenv(key, "30")    # the 60 s floor is unchanged
    assert inplay_lane.ncaab_live_refresh_interval_seconds(league) == 60
    monkeypatch.setenv(key, "garbage")
    assert inplay_lane.ncaab_live_refresh_interval_seconds(league) == 60


# --- the segment clock --------------------------------------------------------------------------------------

def test_a_60_s_lane_asks_segments_every_240_s_and_full_game_lines_every_pull(module, clock):
    state, writes = clock
    adapter = _live_adapter()
    asked_at = []
    for offset in (0, 60, 120, 180, 240, 300):
        before = len(adapter.event_calls())
        rows = _pull(module, adapter, NOW + dt.timedelta(seconds=offset))
        if len(adapter.event_calls()) > before:
            asked_at.append(offset)
        # every pull carries the live game's full-game row, and only started games
        assert [r["event_id"] for r in rows if r.get("period") == "full_game"] == ["live"]
    assert [c for c in adapter.calls if c[0] == "bulk"] == [("bulk", "h2h,spreads,totals")] * 6
    assert asked_at == [0, 240]
    assert [w[1] - NOW.timestamp() for w in writes] == [0.0, 240.0]


def test_a_pull_landing_a_few_seconds_early_still_counts(module, clock):
    adapter = _live_adapter()
    _pull(module, adapter, NOW)
    _pull(module, adapter, NOW + dt.timedelta(seconds=225))   # 225 + 20 s slack >= 240
    assert len(adapter.event_calls()) == 2
    _pull(module, adapter, NOW + dt.timedelta(seconds=300))   # 75 s after the last pass: skipped
    assert len(adapter.event_calls()) == 2


def test_a_skipped_pull_keeps_no_segment_rows(module, clock):
    adapter = _live_adapter()
    first = _pull(module, adapter, NOW)
    second = _pull(module, adapter, NOW + dt.timedelta(seconds=60))
    assert any(r.get("period") == "2h" for r in first)
    assert not any(r.get("period") == "2h" for r in second)


def test_zero_turns_the_clock_off_and_every_pull_asks(module, clock, monkeypatch):
    monkeypatch.setenv("SYNDICATE_NCAAB_IN_PLAY_SEGMENT_INTERVAL_SECONDS", "0")
    adapter = _live_adapter()
    for offset in (0, 60, 120):
        _pull(module, adapter, NOW + dt.timedelta(seconds=offset))
    assert len(adapter.event_calls()) == 3    # off != on: the pre-#810 behaviour


def test_without_the_clock_flag_every_call_asks_and_the_clock_is_never_touched(module, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("segment clock touched")

    monkeypatch.setattr(module, "_read_segment_clock", _boom)
    monkeypatch.setattr(module, "_write_segment_clock", _boom)
    adapter = _live_adapter()
    for offset in (0, 60):
        _pull(module, adapter, NOW + dt.timedelta(seconds=offset), segment_clock=False)
    assert len(adapter.event_calls()) == 2


def test_each_league_has_its_own_clock(module, clock):
    adapter = _live_adapter()
    _pull(module, adapter, NOW, league="ncaab")
    _pull(module, adapter, NOW + dt.timedelta(seconds=30), league="wncaab")
    assert len(adapter.event_calls()) == 2
    state, _ = clock
    assert set(state) == {"ncaab", "wncaab"}


def test_no_started_game_leaves_the_clock_alone(module, clock):
    state, writes = clock
    adapter = _Adapter({"soon": NOW + dt.timedelta(minutes=10)})
    _pull(module, adapter, NOW)
    assert writes == [] and adapter.event_calls() == []
    # so a game that tips a minute later gets its half lines on its first in-play pull
    adapter.commence["soon"] = NOW
    _pull(module, adapter, NOW + dt.timedelta(seconds=60))
    assert len(adapter.event_calls()) == 1


def test_a_clock_in_the_future_or_unreadable_asks(module, monkeypatch):
    adapter = _live_adapter()
    monkeypatch.setattr(module, "_write_segment_clock", lambda league, moment: None)
    monkeypatch.setattr(module, "_read_segment_clock", lambda league: NOW.timestamp() + 600)
    _pull(module, adapter, NOW)
    monkeypatch.setattr(module, "_read_segment_clock", lambda league: None)
    _pull(module, adapter, NOW)
    assert len(adapter.event_calls()) == 2


def test_a_failed_segment_pass_does_not_advance_the_clock(module, clock, monkeypatch):
    state, writes = clock

    def _fail(*args, **kwargs):
        raise RuntimeError("segment pass died")

    monkeypatch.setattr(module, "_append_half_lines", _fail)
    with pytest.raises(RuntimeError):
        _pull(module, _live_adapter(), NOW)
    assert writes == []


def test_the_clock_round_trips_through_the_state_store(module, tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    assert module._read_segment_clock("ncaab") is None
    module._write_segment_clock("ncaab", NOW)
    assert module._read_segment_clock("ncaab") == NOW.timestamp()
    assert module._read_segment_clock("wncaab") is None
    assert REPO not in module._segment_clock_path("ncaab").parents   # conftest isolates the reports root


def test_the_lanes_run_uses_the_clock(module, tmp_path, monkeypatch):
    """main() --in-play-only is the lane's run: two back-to-back runs ask segments once."""
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path / "data_root"))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    started = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)
    made: list[_Adapter] = []

    class _Client(_Adapter):
        def __init__(self, region="us", api_key=None):
            super().__init__({"live": started})
            made.append(self)

    monkeypatch.setattr(module, "_load_source_adapter", lambda root: _Client)
    out = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["x", "--date", "2026-11-15", "--out-dir", str(out), "--in-play-only"])
    assert module.main() == 0
    assert module.main() == 0
    assert [len(a.event_calls()) for a in made] == [1, 0]
    assert [c for c in made[1].calls if c[0] == "bulk"] == [("bulk", "h2h,spreads,totals")]
