"""`ncaaf-live-cadence`. NCAAF's game-line capture, isolated from its prop sweep.

WHY THIS EXISTS, measured on production 2026-09-03 rather than reasoned:

  * `ODDS_SWEEP_LAUNCHED` on live-odds-worker fires every ~90s and reads
    `sports=mlb,soccer` on essentially every tick. NCAAF appeared in exactly ONE
    launch between 17:09Z and 20:07Z (`sports=mlb,ncaaf,soccer`, 18:43:22Z).
  * `PREGAME_CADENCE_DETAIL` names the gate and its number:
    `ncaaf:marker_age_s=7042/interval_s=7200`, the fixture-aware "near" tier.
  * The NCAAF quote state read back from production jumps
    **18:43:39Z -> 22:16:37Z (3h33m)** -- worse than the 2h interval, because a
    launch at 20:43 stamped NCAAF's marker (`marker_age_s=89` one tick later)
    and produced no capture. Markers are stamped BEFORE the launch by `#25`, so
    one lost run costs a full interval.
  * The served board at 22:20:12Z: 4,644 of 5,928 NCAAF rows at
    `quote_seen_age_seconds` 12,948s, scored `freshness_factor: 0.25`.

The fix borrows the WNBA live autorun's SHAPE (`test_wnba_live_refresh_autorun.py`)
and not its diagnosis. WNBA's problem was a combined run colliding with itself.
NCAAF's is that its cheap step is hostage to its expensive one: one 9-credit
game-line request sits in the same sport leg as a per-event-per-market prop sweep
that made 113,843 calls this window. `mode="fast"` is what separates them, and it
is the single assertion in this file that must never be relaxed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "live_odds_worker_ncaaf_under_test", _REPO / "scripts" / "run_live_odds_refresh_worker.py"
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules["live_odds_worker_ncaaf_under_test"] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for key in (
        "SYNDICATE_ENABLE_NCAAF_LINES_REFRESH_AUTORUN",
        "SYNDICATE_NCAAF_LINES_REFRESH_INTERVAL_SECONDS",
        "SYNDICATE_NCAAF_LINES_REFRESH_HORIZON_DAYS",
        "SYNDICATE_NCAAF_LINES_REFRESH_LANE",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _armed(mod, monkeypatch, tmp_path, *, status=None):
    """Every gate open except the one under test."""
    monkeypatch.setenv("SYNDICATE_ENABLE_NCAAF_LINES_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_ncaaf_active_for_date", lambda d: True)
    monkeypatch.setattr(mod, "_ncaaf_has_games_within_horizon", lambda d: True)
    monkeypatch.setattr(mod, "_ncaaf_lines_autorun_status_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(mod, "read_json_file", lambda p: dict(status or {}))
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: None)


# --------------------------------------------------------------------------
# Safety properties. These matter more than the happy path.
# --------------------------------------------------------------------------


def test_it_is_OFF_unless_explicitly_enabled(mod, monkeypatch):
    """DEFAULT OFF. New periodic worker work is never free (`#241` caused a
    production restart loop), and live-odds-worker read 96% of its 2,048MB with
    81MB headroom on 2026-09-03T22:24Z."""
    assert mod._ncaaf_lines_refresh_enabled() is False
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw))
    mod._launch_autorun_ncaaf_lines_refresh()
    assert called == [], "a disabled autorun must not launch anything"


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
def test_the_enable_flag_accepts_the_same_spellings_as_the_other_autoruns(mod, monkeypatch, value):
    monkeypatch.setenv("SYNDICATE_ENABLE_NCAAF_LINES_REFRESH_AUTORUN", value)
    assert mod._ncaaf_lines_refresh_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  "])
def test_anything_else_is_off(mod, monkeypatch, value):
    monkeypatch.setenv("SYNDICATE_ENABLE_NCAAF_LINES_REFRESH_AUTORUN", value)
    assert mod._ncaaf_lines_refresh_enabled() is False


def test_it_does_nothing_out_of_season(mod, monkeypatch, tmp_path):
    _armed(mod, monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_ncaaf_active_for_date", lambda d: False)
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw))
    mod._launch_autorun_ncaaf_lines_refresh()
    assert called == []


def test_it_does_nothing_when_no_game_is_inside_the_horizon(mod, monkeypatch, tmp_path):
    """The game-day gate. NCAAF plays a handful of days a week, and a capture on
    a Tuesday buys nothing the 2h combined sweep does not already buy."""
    _armed(mod, monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_ncaaf_has_games_within_horizon", lambda d: False)
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw))
    mod._launch_autorun_ncaaf_lines_refresh()
    assert called == []


def test_an_unreadable_schedule_over_captures_rather_than_going_dark(mod, monkeypatch):
    """`unknown_means_yes`, inherited from `sport_has_games_within` and
    load-bearing: `fetch_schedule_for_date` returns [] for a swallowed timeout
    exactly as it does for "no games". Treating that as authoritative would make
    this autorun silently stop during precisely the outage it exists to fix, and
    the failure would look like a quiet week. Over-capturing costs 9 credits."""

    def _boom(*a, **kw):
        raise RuntimeError("schedule source down")

    monkeypatch.setattr(
        "syndicate.features.shared.schedule_adapter.sport_has_games_within", _boom, raising=False
    )
    assert mod._ncaaf_has_games_within_horizon("2026-09-03") is True


def test_it_requests_LIVE_phase_ncaaf_only_FAST_mode_and_its_OWN_lane(mod, monkeypatch, tmp_path):
    """THE MOST IMPORTANT ASSERTION IN THIS FILE.

      - sports="ncaaf": widening recreates the combined sweep this routes around.
      - mode="fast": THE cost control. `full` drags in
        `ncaaf_player_props_oddsapi`, billed per EVENT per MARKET over ~130
        events x 9 markets. Production `/api/ops/oddsapi/quota` 2026-09-03T22:50Z
        recorded ncaaf at 113,843 calls for 9,495 credits -- cheap only because
        OddsAPI returns nothing for most college events right now. Once the books
        post college props, a 5-minute `full` cadence is ~1,170 credits a run.
      - lane=<distinct>: without it this contends with the combined sweep's lane.
      - skip_mirror: the mirror is a local convenience, never on this path.
    """
    _armed(mod, monkeypatch, tmp_path)
    seen = {}
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: seen.update(kw) or {})
    mod._launch_autorun_ncaaf_lines_refresh()
    assert seen.get("phase") == "live"
    assert seen.get("sports") == "ncaaf", "must not widen to other sports"
    assert seen.get("mode") == "fast", "full mode drags in the per-event prop sweep on every repeat"
    assert seen.get("skip_mirror") is True
    lane = seen.get("lane")
    assert lane, "must pass an explicit lane -- default/unscoped would contend with the combined sweep"
    assert lane != "global", "must not collapse onto the legacy shared lane"


def test_the_lane_is_stable_across_calls_and_overridable(mod, monkeypatch):
    default_lane = mod._ncaaf_lines_refresh_lane()
    assert default_lane == mod._ncaaf_lines_refresh_lane(), "must be deterministic, not random per call"
    assert default_lane != mod._wnba_live_refresh_lane(), "two isolated autoruns cannot share one lane"
    monkeypatch.setenv("SYNDICATE_NCAAF_LINES_REFRESH_LANE", "custom-lane")
    assert mod._ncaaf_lines_refresh_lane() == "custom-lane"


def test_the_interval_default_and_override(mod, monkeypatch):
    assert mod._ncaaf_lines_refresh_interval_seconds() == 300
    monkeypatch.setenv("SYNDICATE_NCAAF_LINES_REFRESH_INTERVAL_SECONDS", "120")
    assert mod._ncaaf_lines_refresh_interval_seconds() == 120
    monkeypatch.setenv("SYNDICATE_NCAAF_LINES_REFRESH_INTERVAL_SECONDS", "not-a-number")
    assert mod._ncaaf_lines_refresh_interval_seconds() == 300, "a bad value falls back, never to 0"


def test_the_horizon_default_and_override(mod, monkeypatch):
    assert mod._ncaaf_lines_refresh_horizon_days() == 1
    monkeypatch.setenv("SYNDICATE_NCAAF_LINES_REFRESH_HORIZON_DAYS", "3")
    assert mod._ncaaf_lines_refresh_horizon_days() == 3
    monkeypatch.setenv("SYNDICATE_NCAAF_LINES_REFRESH_HORIZON_DAYS", "junk")
    assert mod._ncaaf_lines_refresh_horizon_days() == 1


def test_the_cadence_gate_suppresses_a_second_launch(mod, monkeypatch, tmp_path):
    _armed(mod, monkeypatch, tmp_path, status={"epoch": mod.time.time() - 1.0, "reported": True})
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw))
    mod._launch_autorun_ncaaf_lines_refresh()
    assert called == [], "inside the interval, it must not relaunch"


def test_a_stale_marker_allows_the_next_launch(mod, monkeypatch, tmp_path):
    _armed(mod, monkeypatch, tmp_path, status={"epoch": mod.time.time() - 99999.0, "reported": True})
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw) or {})
    mod._launch_autorun_ncaaf_lines_refresh()
    assert len(called) == 1


def test_a_launch_failure_is_recorded_and_reported_not_swallowed(mod, monkeypatch, tmp_path, capsys):
    """`#433`: the launch is detached with stdout to DEVNULL, so a failure that
    is not printed here is a failure nobody can see."""
    _armed(mod, monkeypatch, tmp_path)
    written = {}
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: written.update(v))

    def _boom(**kw):
        raise RuntimeError("launch exploded")

    monkeypatch.setattr(mod, "launch_refresh_run", _boom)
    mod._launch_autorun_ncaaf_lines_refresh()
    assert "RuntimeError" in str(written.get("error")), "the failure must persist"
    assert "NCAAF_LINES_AUTORUN_FAILED" in capsys.readouterr().out, "and must be visible"


def test_a_contention_error_preserves_the_original_epoch(mod, monkeypatch, tmp_path):
    """`#472`'s fix, and it matters more here than anywhere else in this file:
    the 3h33m hole this autorun exists to remove was itself one lost run charged
    at a full interval."""
    original_epoch = mod.time.time() - 99999.0
    _armed(mod, monkeypatch, tmp_path, status={"epoch": original_epoch, "reported": True})
    written = {}
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: written.update(v))

    def _contended(**kw):
        raise ValueError("A refresh run is already active (pid=1). Cancel it before starting a new run.")

    monkeypatch.setattr(mod, "launch_refresh_run", _contended)
    mod._launch_autorun_ncaaf_lines_refresh()
    assert written.get("epoch") == original_epoch, "contention must not reset the cadence clock"


def test_the_previous_run_is_reported_BEFORE_the_cadence_gate(mod, monkeypatch, tmp_path, capsys):
    """The gate returns on most ticks, so reporting after it would surface the
    previous run's outcome up to a full interval late."""
    _armed(
        mod,
        monkeypatch,
        tmp_path,
        status={"epoch": mod.time.time() - 1.0, "error": "ValueError: nope", "reported": False},
    )
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw))
    mod._launch_autorun_ncaaf_lines_refresh()
    out = capsys.readouterr().out
    assert called == [], "this call must be gated by the cadence"
    assert "NCAAF_LINES_AUTORUN_PREV" in out and "FAILED" in out


def test_the_tick_calls_it_and_an_exception_cannot_take_down_the_tick(mod, monkeypatch, capsys):
    """Its own try/except, same as the three autoruns beside it. An NCAAF fault
    must never cost the WNBA autoruns or the general sweep."""
    monkeypatch.setattr(mod, "_launch_autorun_soccer_pregame_refresh", lambda: None)
    monkeypatch.setattr(mod, "_launch_autorun_wnba_pregame_refresh", lambda: None)
    monkeypatch.setattr(mod, "_launch_autorun_wnba_live_refresh", lambda: None)
    reached = []
    monkeypatch.setattr(mod, "_log_worker_memory", lambda *a, **kw: reached.append("tick"))
    monkeypatch.setattr(mod, "_run_live_refresh_tick", lambda: {"ok": True})

    def _boom():
        raise RuntimeError("ncaaf autorun exploded")

    monkeypatch.setattr(mod, "_launch_autorun_ncaaf_lines_refresh", _boom)
    mod._run_tick()
    assert "NCAAF_LINES_AUTORUN_ERROR" in capsys.readouterr().out
    assert reached, "the general tick must still run"
