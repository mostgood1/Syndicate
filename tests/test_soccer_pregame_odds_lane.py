"""A future-dated pregame run simulates its own date's soccer fixtures, not 7 days (lane `soccer-pregame-odds-lane`).

Measured on the fleet 2026-11-18 (manifests + role logs, 11-13..11-18): the ~46-min
soccer pregame holds are refresh-worker's LOOK-AHEAD (`warm_next_day_slate`), which
launches every sport for TOMORROW, hourly. Its soccer step is week-scoped from today
with refresh-worker's `SYNDICATE_SOCCER_SIM_HORIZON_DAYS=7` -- a value set for the
weekly autorun's unit list -- so each look-ahead re-simulated every fixture in the next
7 days: 16 s per match, 50-62 matches, run hold p50 1,201 s / max 3,035 s. The look-ahead
is the only launcher of future-dated soccer pregame runs (86 of 86; 0 of 170 elsewhere).

The switch is `SYNDICATE_SOCCER_LOOKAHEAD_DATE_ANCHOR` (absent = on). The `off != on`
test drives the REAL `_build_summary` over the REAL soccer registry entry in dry-run, and
reads the commands the run would have launched.
"""
from __future__ import annotations

import argparse
from datetime import date

import pytest

from scripts import refresh_odds_sources as ros

SWITCH = "SYNDICATE_SOCCER_LOOKAHEAD_DATE_ANCHOR"
TODAY = date(2026, 11, 18)
TOMORROW = "2026-11-19"
# The week of TOMORROW differs from the current week on purpose: a date in the next
# matchweek must resolve to ITS week, which the unanchored scope cannot reach.
CURRENT_WEEK, TOMORROW_WEEK = 14, 15


@pytest.fixture(autouse=True)
def _soccer_world(monkeypatch, tmp_path):
    for name in ("_log_memory", "_dump_child_runtime_state", "log_runtime_memory", "log_all_process_memory", "_record_step_in_sim_ledger"):
        monkeypatch.setattr(ros, name, lambda *a, **k: None)
    monkeypatch.delenv(SWITCH, raising=False)
    monkeypatch.setenv("SYNDICATE_SERIAL_SPORT_REFRESH", "true")
    monkeypatch.setattr(ros, "central_today", lambda: TODAY)
    monkeypatch.setattr(ros, "_SOCCER_SIM_HORIZON_DAYS", 7)
    monkeypatch.setattr(ros, "soccer_active_leagues_for_date", lambda d: ["epl", "mls"])
    monkeypatch.setattr(ros, "soccer_league_has_sim", lambda league: True)
    monkeypatch.setattr(ros, "soccer_default_season", lambda league: 2026)
    weeks_asked: list = []

    def default_week(league, season, *, reference_date=None):
        weeks_asked.append((league, reference_date))
        return TOMORROW_WEEK if reference_date == TOMORROW else CURRENT_WEEK

    monkeypatch.setattr(ros, "soccer_default_week", default_week)
    monkeypatch.setattr(ros, "soccer_week_date_list", lambda league, season, week: ["2026-11-19", "2026-11-21"])
    monkeypatch.setattr(ros, "_soccer_live_scope", lambda d: {})
    monkeypatch.setattr(ros, "_local_source_bundle_root", lambda slug: tmp_path)
    for name in ("_soccer_history_step", "_soccer_current_history_step", "_soccer_players_step",
                 "_soccer_rosters_step", "_soccer_uefa_branding_step"):
        monkeypatch.setattr(ros, name, lambda *a, **k: None)
    monkeypatch.setattr(ros, "_soccer_schedule_full_rebuild_leagues", lambda leagues, root: set())
    monkeypatch.setattr(ros, "publish_sport_manifest", lambda **kw: {"path": f"reports/manifests/{kw['sport']}.json"})
    monkeypatch.setattr(ros, "build_publish_parity_summary", lambda **kw: {})
    monkeypatch.setattr(ros, "_build_odds_coverage_audit", lambda **kw: {})
    monkeypatch.setattr(ros, "_step_requires_source_root", lambda step: False)
    return weeks_asked


def _args(*, run_date=TOMORROW, phase="pregame", soccer_date="", sports="soccer"):
    return argparse.Namespace(
        date=run_date, sports=sports, phase=phase, mode="full", regions="us", bookmakers="", markets="",
        season=None, week=None, skip_mirror=True, execution_mode="source", mirror_only=False,
        continue_on_error=True, dry_run=True, json=False, list=False, force_refresh=False,
        soccer_date=soccer_date, soccer_leagues=None,
    )


def _sim_commands(summary) -> dict[str, list[str]]:
    """{step name: command} for every soccer artifacts/picks step the run launched."""
    soccer = next(r for r in summary["results"] if r["sport"] == "soccer")
    return {
        s["name"]: list(s["command"])
        for s in soccer["refresh_steps"]
        if s["name"].endswith(("_artifacts", "_picks"))
    }


def _scope(command: list[str]) -> list[str]:
    return command[command.index("--league") + 2: command.index("--source-root")]


# --- the reachability test: off != on, through the real run loop ---------------------------

def test_reachability_the_look_ahead_run_simulates_its_own_date_on_and_7_days_off(monkeypatch, _soccer_world):
    on = _sim_commands(ros._build_summary(_args()))
    assert set(on) == {"soccer_epl_artifacts", "soccer_mls_artifacts", "soccer_epl_picks", "soccer_mls_picks"}
    for name, command in on.items():
        assert _scope(command) == ["--week", str(TOMORROW_WEEK), "--season", "2026", "--horizon-days", "0", "--date", TOMORROW], name
    assert ("epl", TOMORROW) in _soccer_world, "the week must be resolved from the run's own date"

    monkeypatch.setenv(SWITCH, "off")
    off = _sim_commands(ros._build_summary(_args()))
    assert set(off) == set(on)
    for name, command in off.items():
        assert _scope(command) == ["--week", str(CURRENT_WEEK), "--season", "2026", "--horizon-days", "7"], name
    assert off != on


def test_a_today_dated_run_is_unchanged_with_the_switch_on(monkeypatch):
    """The soccer-pregame lane and the live sweeps launch for TODAY: not touched."""
    on = _sim_commands(ros._build_summary(_args(run_date=TODAY.isoformat())))
    monkeypatch.setenv(SWITCH, "off")
    off = _sim_commands(ros._build_summary(_args(run_date=TODAY.isoformat())))
    assert on == off
    assert on and all(
        _scope(c) == ["--week", str(CURRENT_WEEK), "--season", "2026", "--horizon-days", "7"] for c in on.values()
    )


def test_a_pinned_unit_keeps_its_pinned_date():
    """The weekly autorun pins (league, date) with `--soccer-date`; the anchor never overrides it."""
    on = _sim_commands(ros._build_summary(_args(soccer_date="2026-11-21", phase="live")))
    assert on and all(_scope(c) == ["--date", "2026-11-21"] for c in on.values())


def test_the_steps_and_their_order_are_unchanged(monkeypatch):
    """No step added, dropped or reordered -- so no added OddsAPI call."""
    def names(summary):
        soccer = next(r for r in summary["results"] if r["sport"] == "soccer")
        return [s["name"] for s in soccer["refresh_steps"]]

    on = names(ros._build_summary(_args()))
    monkeypatch.setenv(SWITCH, "off")
    assert names(ros._build_summary(_args())) == on


# --- the decision, unit by unit -------------------------------------------------------------

@pytest.mark.parametrize(
    "run_date, phase, soccer_date, expected",
    [
        (TOMORROW, "pregame", "", TOMORROW),           # the look-ahead, day 1
        ("2026-11-20", "pregame", "", "2026-11-20"),   # the look-ahead, day 2
        (TODAY.isoformat(), "pregame", "", ""),        # today: unchanged
        ("2026-11-17", "pregame", "", ""),             # the past: unchanged
        (TOMORROW, "live", "", ""),                    # not pregame
        (TOMORROW, "all", "", ""),
        (TOMORROW, "pregame", "2026-11-21", ""),       # a pinned unit wins
        ("not-a-date", "pregame", "", ""),
        ("", "pregame", "", ""),
    ],
)
def test_anchor_decision(run_date, phase, soccer_date, expected):
    args = argparse.Namespace(date=run_date, phase=phase, soccer_date=soccer_date)
    assert ros._soccer_lookahead_anchor_date(args) == expected


@pytest.mark.parametrize("value", ["off", "0", "false", "no", "OFF"])
def test_switch_off_values(monkeypatch, value):
    monkeypatch.setenv(SWITCH, value)
    assert ros._soccer_lookahead_date_anchor_enabled() is False
    assert ros._soccer_lookahead_anchor_date(argparse.Namespace(date=TOMORROW, phase="pregame", soccer_date="")) == ""


@pytest.mark.parametrize("value", [None, "", "1", "on", "true", "yes"])
def test_switch_on_values(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(SWITCH, raising=False)
    else:
        monkeypatch.setenv(SWITCH, value)
    assert ros._soccer_lookahead_date_anchor_enabled() is True


def test_an_unresolvable_week_falls_back_to_the_single_date(monkeypatch):
    """Same fallback the unanchored scope takes (fresh disk, no schedule)."""
    monkeypatch.setattr(ros, "soccer_week_date_list", lambda league, season, week: [])
    assert ros._soccer_artifact_scope_args("epl", TOMORROW, anchor_date=TOMORROW) == ("--date", TOMORROW)

    def boom(league):
        raise OSError("schedule unreadable")

    monkeypatch.setattr(ros, "soccer_default_season", boom)
    assert ros._soccer_artifact_scope_args("epl", TOMORROW, anchor_date=TOMORROW) == ("--date", TOMORROW)


def test_pinned_date_beats_the_anchor_in_the_scope_helper():
    assert ros._soccer_artifact_scope_args("epl", TOMORROW, pinned_date="2026-11-21", anchor_date=TOMORROW) == ("--date", "2026-11-21")
