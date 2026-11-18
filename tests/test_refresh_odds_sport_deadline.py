"""One sport's hung odds child must not take the whole live odds lane (lane `odds-lane-sport-deadline`).

Measured on the fleet 2026-11-18 (01:21-02:55Z): three live sweeps in a row ran
`refresh_nhl_oddsapi.py` in full mode; its lineup collection waited on the NHL stats
REST API (21-44 s per call, or HTTP 520) until the 1,800 s step timeout. The
`TimeoutExpired` escaped `_run_command` / `_run_sport_refresh` / `_build_summary`, so
every run died rc 1: the sports after NHL never ran and NBA's finished result was
dropped. The switch is `SYNDICATE_ODDS_LANE_STEP_DEADLINE` (absent = on).

The `off != on` tests run the REAL run loop over real child processes: a test that
mocks `_run_command` cannot see whether the timeout escapes it.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import refresh_odds_sources as ros

SWITCH = "SYNDICATE_ODDS_LANE_STEP_DEADLINE"
PREGAME_SWITCH = "SYNDICATE_NHL_PREGAME_GENERATION_SPLIT"
DATE = "2026-11-17"
PY = sys.executable


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    for name in ("_log_memory", "_dump_child_runtime_state", "log_runtime_memory", "log_all_process_memory", "_record_step_in_sim_ledger"):
        monkeypatch.setattr(ros, name, lambda *a, **k: None)
    monkeypatch.delenv(SWITCH, raising=False)
    monkeypatch.delenv("SYNDICATE_REFRESH_STEP_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("SYNDICATE_REFRESH_STEP_TIMEOUT_SECONDS__NHL", raising=False)
    monkeypatch.delenv("SYNDICATE_NHL_LIVE_FULL_GENERATION_SECONDS", raising=False)
    monkeypatch.delenv("SYNDICATE_NHL_LIVE_GENERATION_DEADLINE_SECONDS", raising=False)
    monkeypatch.delenv(PREGAME_SWITCH, raising=False)
    monkeypatch.delenv("SYNDICATE_NHL_PREGAME_GENERATION_DEADLINE_SECONDS", raising=False)
    monkeypatch.setenv("SYNDICATE_SERIAL_SPORT_REFRESH", "true")


def _step(name, code, **kw):
    return ros.RefreshStep(name=name, phases=("live",), cwd=ros.REPO_ROOT, command=(PY, "-c", code), **kw)


def _hang(name, *, marker=None, timeout=1.5):
    return _step(
        name,
        "import time; print('STAGE collect_slate_inputs', flush=True); time.sleep(60)",
        timeout_seconds=timeout,
        timeout_marker=marker,
    )


def _append(log: Path, label: str):
    return f"open({str(log)!r}, 'a').write({label!r} + chr(10))"


@pytest.fixture
def fake_sports(monkeypatch, tmp_path):
    """Two fake sports in a REAL registry slot each, so `_build_summary` runs unpatched."""

    def install(builders: dict):
        registry = {}
        for slug, builder in builders.items():
            registry[slug] = ros.SportSpec(
                slug=slug,
                source_repo_name=f"{slug}_source",
                mirror_script_name=f"refresh_{slug}_source_mirror.ps1",
                step_builder=builder,
                ingest_contract_kind="artifact_bundle_or_existing_mirror",
            )
        monkeypatch.setattr(ros, "REGISTRY", registry)
        monkeypatch.setattr(ros, "publish_sport_manifest", lambda **kw: {"path": f"reports/manifests/{kw['sport']}.json"})
        monkeypatch.setattr(ros, "build_publish_parity_summary", lambda **kw: {})
        monkeypatch.setattr(ros, "_build_odds_coverage_audit", lambda **kw: {})
        monkeypatch.setattr(ros, "_step_requires_source_root", lambda step: False)

    return install


def _args(sports, phase="live"):
    return argparse.Namespace(
        date=DATE, sports=sports, phase=phase, mode="full", regions="us", bookmakers="", markets="",
        season=None, week=None, skip_mirror=True, execution_mode="source", mirror_only=False,
        continue_on_error=True, dry_run=False, json=False, list=False, force_refresh=False,
    )


def _steps_by_sport(summary):
    return {r["sport"]: r for r in summary["results"]}


# --- the reachability test: off != on, through the real run loop ---------------------------

def test_reachability_a_hung_sport_no_longer_kills_the_run(fake_sports, tmp_path, monkeypatch):
    log = tmp_path / "ran.txt"
    fake_sports({
        "hangs": lambda args: [_hang("hangs_odds", timeout=None)],
        "after": lambda args: [_step("after_odds", _append(log, "after_odds"))],
    })
    # The SAME run-wide deadline both ways; only the switch differs.
    monkeypatch.setenv("SYNDICATE_REFRESH_STEP_TIMEOUT_SECONDS", "2")

    # ON (absent): the hung sport is a failed step and the next sport still runs.
    summary = ros._build_summary(_args("hangs,after"))
    by = _steps_by_sport(summary)
    assert summary["ok"] is False
    assert by["hangs"]["ok"] is False
    step = by["hangs"]["refresh_steps"][0]
    assert step["timed_out"] is True and step["status"] == "timeout" and step["return_code"] is None
    assert "STAGE collect_slate_inputs" in step["stdout_tail"], "the stage the child stalled in survives"
    assert by["after"]["ok"] is True
    assert log.read_text().split() == ["after_odds"]

    # OFF: today's behaviour -- the TimeoutExpired escapes and the next sport never runs.
    log.unlink()
    monkeypatch.setenv(SWITCH, "off")
    with pytest.raises(subprocess.TimeoutExpired):
        ros._build_summary(_args("hangs,after"))
    assert not log.exists()


def test_deferred_step_runs_after_every_sport_on_and_inline_off(fake_sports, tmp_path, monkeypatch):
    log = tmp_path / "order.txt"
    fake_sports({
        "first": lambda args: [
            _step("first_odds", _append(log, "first_odds")),
            _step("first_generation", _append(log, "first_generation"), deferred=True),
        ],
        "second": lambda args: [_step("second_odds", _append(log, "second_odds"))],
    })
    summary = ros._build_summary(_args("first,second"))
    assert log.read_text().split() == ["first_odds", "second_odds", "first_generation"]
    by = _steps_by_sport(summary)
    assert [s["name"] for s in by["first"]["refresh_steps"]] == ["first_odds", "first_generation"]
    assert summary["ok"] is True

    log.unlink()
    monkeypatch.setenv(SWITCH, "off")
    ros._build_summary(_args("first,second"))
    assert log.read_text().split() == ["first_odds", "first_generation", "second_odds"]


def test_a_deferred_step_past_its_deadline_fails_its_sport_and_writes_its_marker(fake_sports, tmp_path):
    marker = tmp_path / "processed" / ".timeout.json"
    fake_sports({
        "first": lambda args: [
            _step("first_odds", "print('ok')"),
            ros.replace(_hang("first_generation", marker=str(marker)), deferred=True),
        ],
        "second": lambda args: [_step("second_odds", "print('ok')")],
    })
    started = time.monotonic()
    summary = ros._build_summary(_args("first,second"))
    assert time.monotonic() - started < 30, "the step deadline, not the 1,800 s run-wide one"
    by = _steps_by_sport(summary)
    assert by["second"]["ok"] is True
    assert by["first"]["ok"] is False
    assert [s.get("timed_out", False) for s in by["first"]["refresh_steps"]] == [False, True]
    payload = json.loads(marker.read_text())
    assert payload["step"] == "first_generation" and payload["timeout_seconds"] == 1.5


# --- _run_command, the unit the timeout escaped -----------------------------------------------

def test_run_command_returns_a_failed_step_on_and_raises_off(monkeypatch):
    step = _hang("unit_hang", timeout=None)
    monkeypatch.setenv("SYNDICATE_REFRESH_STEP_TIMEOUT_SECONDS", "2")
    result = ros._run_command(step)
    assert result["ok"] is False and result["timed_out"] is True
    assert "STAGE collect_slate_inputs" in result["stdout"]
    monkeypatch.setenv(SWITCH, "off")
    with pytest.raises(subprocess.TimeoutExpired):
        ros._run_command(step)


@pytest.mark.parametrize("value", ["off", "0", "false", "no", "OFF"])
def test_switch_off_values(monkeypatch, value):
    monkeypatch.setenv(SWITCH, value)
    assert ros._odds_lane_step_deadline_enabled() is False


@pytest.mark.parametrize("value", ["", "on", "1", "true"])
def test_switch_on_values(monkeypatch, value):
    monkeypatch.setenv(SWITCH, value)
    assert ros._odds_lane_step_deadline_enabled() is True


def test_step_deadline_tightens_the_run_wide_one_only_while_on(monkeypatch):
    step = _step("x", "pass", timeout_seconds=900)
    assert ros._effective_step_timeout_seconds(step) == 900
    monkeypatch.setenv("SYNDICATE_REFRESH_STEP_TIMEOUT_SECONDS", "600")
    assert ros._effective_step_timeout_seconds(step) == 600, "the run-wide value stays the ceiling"
    monkeypatch.setenv(SWITCH, "off")
    assert ros._effective_step_timeout_seconds(step) == 600
    monkeypatch.delenv("SYNDICATE_REFRESH_STEP_TIMEOUT_SECONDS")
    assert ros._effective_step_timeout_seconds(step) == ros._DEFAULT_REFRESH_STEP_TIMEOUT_SECONDS


def test_per_sport_deadline_env(monkeypatch):
    args = _args("nhl")
    plain = _step("nhl_oddsapi_refresh", "pass")
    capped = _step("nhl_live_generation", "pass", timeout_seconds=900)
    assert ros._launch_step(args, "nhl", plain, "full").timeout_seconds is None
    monkeypatch.setenv("SYNDICATE_REFRESH_STEP_TIMEOUT_SECONDS__NHL", "300")
    assert ros._launch_step(args, "nhl", plain, "full").timeout_seconds == 300
    assert ros._launch_step(args, "nhl", capped, "full").timeout_seconds == 300
    assert ros._launch_step(args, "nba", plain, "full").timeout_seconds is None, "per sport, not global"
    monkeypatch.setenv(SWITCH, "off")
    assert ros._launch_step(args, "nhl", plain, "full").timeout_seconds is None


def test_launch_step_keeps_every_field(monkeypatch):
    step = _step("g", "pass", timeout_seconds=12, timeout_marker="/tmp/m", deferred=True, modes=("full",))
    launched = ros._launch_step(_args("nhl"), "nhl", step, "full")
    assert (launched.timeout_seconds, launched.timeout_marker, launched.deferred, launched.modes) == (12, "/tmp/m", True, ("full",))


# --- NHL: the split, the cooldown -------------------------------------------------------------

@pytest.fixture
def nhl_root(tmp_path, monkeypatch):
    monkeypatch.setattr(ros, "_local_source_artifact_root", lambda slug: tmp_path)
    return tmp_path


def _predictions(root, age_seconds):
    path = root / "data" / "processed" / f"predictions_{DATE}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n", encoding="utf-8")
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))


def _nhl(phase="live"):
    return ros._build_nhl_steps(argparse.Namespace(date=DATE, phase=phase))


def _mode(step):
    cmd = list(step.command)
    return cmd[cmd.index("--mode") + 1] if "--mode" in cmd else "full"


def test_nhl_live_generation_due_splits_on_and_stays_whole_off(nhl_root, monkeypatch):
    _predictions(nhl_root, age_seconds=2400)
    steps = _nhl()
    assert [(s.name, _mode(s), s.deferred) for s in steps] == [
        ("nhl_oddsapi_refresh", "fast", False),
        ("nhl_live_generation", "generate", True),
    ]
    gen = steps[1]
    assert gen.timeout_seconds == 900 and gen.modes == ("full",) and gen.phases == ("live",)
    assert gen.timeout_marker == str(nhl_root / "data" / "processed" / f".nhl_live_generation_timeout_{DATE}.json")
    monkeypatch.setenv(SWITCH, "off")
    assert [(s.name, _mode(s)) for s in _nhl()] == [("nhl_oddsapi_refresh", "full")]


def test_nhl_generation_not_due_is_one_fast_step_either_way(nhl_root, monkeypatch):
    _predictions(nhl_root, age_seconds=60)
    assert [(s.name, _mode(s)) for s in _nhl()] == [("nhl_oddsapi_refresh", "fast")]
    monkeypatch.setenv(SWITCH, "off")
    assert [(s.name, _mode(s)) for s in _nhl()] == [("nhl_oddsapi_refresh", "fast")]


# --- NHL pregame: the same split (2026-11-18, user "Yes, build it") ----------------------------

def test_nhl_pregame_splits_on_and_stays_whole_off(nhl_root, monkeypatch):
    _predictions(nhl_root, age_seconds=60)  # pregame ALWAYS generates, fresh predictions or not
    steps = _nhl("pregame")
    assert [(s.name, _mode(s), s.deferred) for s in steps] == [
        ("nhl_oddsapi_refresh", "fast", False),
        ("nhl_pregame_generation", "generate", True),
    ]
    gen = steps[1]
    assert gen.timeout_seconds == 900 and gen.modes == ("full",) and gen.phases == ("pregame",)
    assert gen.timeout_marker == str(ros._nhl_live_generation_timeout_marker(nhl_root, DATE)), "one marker, both phases"
    monkeypatch.setenv(PREGAME_SWITCH, "off")
    assert [(s.name, _mode(s)) for s in _nhl("pregame")] == [("nhl_oddsapi_refresh", "full")]
    monkeypatch.delenv(PREGAME_SWITCH)
    monkeypatch.setenv(SWITCH, "off")
    assert [(s.name, _mode(s)) for s in _nhl("pregame")] == [("nhl_oddsapi_refresh", "full")], "needs the lane switch too"


@pytest.mark.parametrize("value", ["off", "0", "false", "no", " OFF "])
def test_pregame_switch_off_values(monkeypatch, value):
    monkeypatch.setenv(PREGAME_SWITCH, value)
    assert ros._nhl_pregame_generation_split_enabled() is False


@pytest.mark.parametrize("value", [None, "", "on", "1", "true"])
def test_pregame_switch_on_values(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv(PREGAME_SWITCH, value)
    assert ros._nhl_pregame_generation_split_enabled() is True


def test_nhl_combined_phase_is_unchanged(nhl_root):
    _predictions(nhl_root, age_seconds=2400)
    assert [(s.name, _mode(s)) for s in _nhl("all")] == [("nhl_oddsapi_refresh", "full")]


def test_nhl_pregame_deadline_env_is_its_own(nhl_root, monkeypatch):
    monkeypatch.setenv("SYNDICATE_NHL_LIVE_GENERATION_DEADLINE_SECONDS", "450")
    assert _nhl("pregame")[1].timeout_seconds == 900, "the live deadline does not move pregame's"
    monkeypatch.setenv("SYNDICATE_NHL_PREGAME_GENERATION_DEADLINE_SECONDS", "600")
    assert _nhl("pregame")[1].timeout_seconds == 600
    monkeypatch.setenv("SYNDICATE_NHL_PREGAME_GENERATION_DEADLINE_SECONDS", "-5")
    assert _nhl("pregame")[1].timeout_seconds == 900


def test_nhl_pregame_cooldown_after_a_timeout_in_either_phase(nhl_root, monkeypatch, capsys):
    marker = ros._nhl_live_generation_timeout_marker(nhl_root, DATE)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}", encoding="utf-8")
    steps = _nhl("pregame")
    assert [(s.name, _mode(s)) for s in steps] == [("nhl_oddsapi_refresh", "fast")], "cooling down: odds only"
    assert "PREGAME FAST: odds only; generation cooling down" in steps[0].description
    assert f"NHL_PREGAME_GENERATION_COOLDOWN date={DATE}" in capsys.readouterr().out
    old = time.time() - 1900
    os.utime(marker, (old, old))
    assert [s.name for s in _nhl("pregame")] == ["nhl_oddsapi_refresh", "nhl_pregame_generation"], "cooldown over: retry"
    os.utime(marker, None)
    monkeypatch.setenv("SYNDICATE_NHL_LIVE_FULL_GENERATION_SECONDS", "0")
    assert [s.name for s in _nhl("pregame")] == ["nhl_oddsapi_refresh", "nhl_pregame_generation"], "cadence 0: no cooldown"
    monkeypatch.delenv("SYNDICATE_NHL_LIVE_FULL_GENERATION_SECONDS")
    monkeypatch.setenv(PREGAME_SWITCH, "off")
    assert [(s.name, _mode(s)) for s in _nhl("pregame")] == [("nhl_oddsapi_refresh", "full")], "off ignores the marker"


def test_pregame_run_level_filter_keeps_generation_in_full_and_drops_it_in_fast(nhl_root):
    assert [s.name for s in ros._filter_steps(_nhl("pregame"), "pregame", "full")] == [
        "nhl_oddsapi_refresh",
        "nhl_pregame_generation",
    ]
    assert [s.name for s in ros._filter_steps(_nhl("pregame"), "pregame", "fast")] == ["nhl_oddsapi_refresh"]


def _real_nhl_builder(log: Path, *, hang: bool = False):
    """The REAL `_build_nhl_steps` (names, phases, deferral, deadline, marker), each command
    swapped for one that logs `name:mode` -- the pregame generation optionally hangs instead."""

    def build(args):
        out = []
        for step in ros._build_nhl_steps(args):
            code = _append(log, f"{step.name}:{_mode(step)}")
            if hang and step.name == "nhl_pregame_generation":
                code = "import time; print('STAGE collect_slate_inputs', flush=True); time.sleep(60)"
            out.append(ros.replace(step, command=(PY, "-c", code), timeout_seconds=1.5 if step.timeout_seconds else None))
        return out

    return build


def _pregame_step(name, code):
    return ros.replace(_step(name, code), phases=("pregame",))


def test_reachability_pregame_generation_runs_after_every_sport_on_and_inline_off(nhl_root, fake_sports, tmp_path, monkeypatch):
    log = tmp_path / "order.txt"
    fake_sports({
        "nhl": _real_nhl_builder(log),
        "after": lambda args: [_pregame_step("after_odds", _append(log, "after_odds"))],
    })
    summary = ros._build_summary(_args("nhl,after", phase="pregame"))
    assert log.read_text().split() == ["nhl_oddsapi_refresh:fast", "after_odds", "nhl_pregame_generation:generate"]
    by = _steps_by_sport(summary)
    assert [s["name"] for s in by["nhl"]["refresh_steps"]] == ["nhl_oddsapi_refresh", "nhl_pregame_generation"]
    assert summary["ok"] is True

    # OFF: today's behaviour -- one full NHL step in NHL's turn.
    log.unlink()
    monkeypatch.setenv(PREGAME_SWITCH, "off")
    ros._build_summary(_args("nhl,after", phase="pregame"))
    assert log.read_text().split() == ["nhl_oddsapi_refresh:full", "after_odds"]


def test_a_pregame_generation_past_its_deadline_keeps_the_run_and_cools_the_next_sweeps(nhl_root, fake_sports, tmp_path):
    log = tmp_path / "order.txt"
    fake_sports({
        "nhl": _real_nhl_builder(log, hang=True),
        "after": lambda args: [_pregame_step("after_odds", _append(log, "after_odds"))],
    })
    started = time.monotonic()
    summary = ros._build_summary(_args("nhl,after", phase="pregame"))
    assert time.monotonic() - started < 30, "the generation deadline, not the 1,800 s run-wide one"
    by = _steps_by_sport(summary)
    assert by["after"]["ok"] is True and by["nhl"]["ok"] is False
    assert [s.get("timed_out", False) for s in by["nhl"]["refresh_steps"]] == [False, True]
    marker = ros._nhl_live_generation_timeout_marker(nhl_root, DATE)
    assert json.loads(marker.read_text())["step"] == "nhl_pregame_generation"
    # The next pregame AND live sweeps inside the cadence refresh NHL odds only.
    assert [(s.name, _mode(s)) for s in _nhl("pregame")] == [("nhl_oddsapi_refresh", "fast")]
    _predictions(nhl_root, age_seconds=7200)
    assert [(s.name, _mode(s)) for s in _nhl("live")] == [("nhl_oddsapi_refresh", "fast")]


def test_nhl_generation_deadline_env(nhl_root, monkeypatch):
    _predictions(nhl_root, age_seconds=2400)
    monkeypatch.setenv("SYNDICATE_NHL_LIVE_GENERATION_DEADLINE_SECONDS", "450")
    assert _nhl()[1].timeout_seconds == 450
    monkeypatch.setenv("SYNDICATE_NHL_LIVE_GENERATION_DEADLINE_SECONDS", "junk")
    assert _nhl()[1].timeout_seconds == 900


def test_nhl_timeout_cooldown_spaces_retries_on_and_is_ignored_off(nhl_root, monkeypatch):
    _predictions(nhl_root, age_seconds=7200)  # stale: a timed-out generation wrote none
    marker = ros._nhl_live_generation_timeout_marker(nhl_root, DATE)
    marker.write_text("{}", encoding="utf-8")
    assert [(s.name, _mode(s)) for s in _nhl()] == [("nhl_oddsapi_refresh", "fast")], "cooling down: odds only"
    old = time.time() - 1900
    os.utime(marker, (old, old))
    assert [s.name for s in _nhl()] == ["nhl_oddsapi_refresh", "nhl_live_generation"], "cooldown over: retry"
    os.utime(marker, None)
    monkeypatch.setenv(SWITCH, "off")
    assert [(s.name, _mode(s)) for s in _nhl()] == [("nhl_oddsapi_refresh", "full")], "off ignores the marker"


def test_nhl_cadence_zero_still_generates_every_sweep(nhl_root, monkeypatch):
    _predictions(nhl_root, age_seconds=10)
    ros._nhl_live_generation_timeout_marker(nhl_root, DATE).write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SYNDICATE_NHL_LIVE_FULL_GENERATION_SECONDS", "0")
    assert [s.name for s in _nhl()] == ["nhl_oddsapi_refresh", "nhl_live_generation"]


def test_run_level_filter_keeps_generation_in_full_and_drops_it_in_fast(nhl_root):
    _predictions(nhl_root, age_seconds=2400)
    assert [s.name for s in ros._filter_steps(_nhl(), "live", "full")] == ["nhl_oddsapi_refresh", "nhl_live_generation"]
    assert [s.name for s in ros._filter_steps(_nhl(), "live", "fast")] == ["nhl_oddsapi_refresh"]


# --- the NHL runner's generate mode makes no odds call ---------------------------------------

def _nhl_runner():
    spec = importlib.util.spec_from_file_location(
        "refresh_nhl_oddsapi_deadline_test", Path(__file__).resolve().parents[1] / "scripts" / "refresh_nhl_oddsapi.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "mode, collects, generates",
    [("fast", True, False), ("full", True, True), ("generate", False, True)],
)
def test_nhl_runner_modes(monkeypatch, tmp_path, capsys, mode, collects, generates):
    runner = _nhl_runner()
    calls = {"collect": 0, "generate": 0}
    monkeypatch.setattr(runner, "_collect_owned_nhl_artifacts", lambda **kw: calls.__setitem__("collect", calls["collect"] + 1))
    monkeypatch.setattr(runner, "_run_owned_generation", lambda **kw: calls.__setitem__("generate", calls["generate"] + 1))
    monkeypatch.setattr(runner, "_materialize_artifact_bundle", lambda **kw: {})
    monkeypatch.setattr(runner, "_materialize_collected_only_artifact_bundle", lambda **kw: {})
    monkeypatch.setattr(runner, "_write_smart_sim_bundle", lambda **kw: tmp_path / "smart_sim.json")
    monkeypatch.setattr(runner, "_missing_required_artifacts", lambda **kw: [])
    monkeypatch.setattr(runner, "_lineup_quality_issues", lambda **kw: [])
    monkeypatch.setattr(sys, "argv", ["refresh_nhl_oddsapi.py", "--date", DATE, "--days-ahead", "1",
                                      "--artifact-root", str(tmp_path), "--mode", mode])
    assert runner.main() == 0
    assert calls["collect"] == (2 if collects else 0), "one collection per target date, none in generate"
    assert calls["generate"] == (1 if generates else 0)
