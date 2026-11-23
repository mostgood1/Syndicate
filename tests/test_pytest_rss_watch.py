"""The nightly ci-suite's per-test memory lines (`scripts/pytest_rss_watch.py`; lane board-split-memory-guard, #850,
findings section 19).

Off != on is measured on REAL pytest processes (Linux only: the plugin reads /proc), including one the test kills
with SIGKILL mid-climb, which is the case the plugin exists for: a runaway the kernel kills still has its name in the
log. The bookkeeping is also tested without /proc through injected readers, so it runs on Windows too.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts import pytest_baseline, run_ci_suite  # noqa: E402
from scripts import pytest_rss_watch as watch_mod  # noqa: E402

LINUX_PROC = Path("/proc/self/status").exists()
needs_proc = pytest.mark.skipif(not LINUX_PROC, reason="the plugin reads /proc/self/status (Linux)")


# ---------------------------------------------------------------- wiring
def test_the_nightly_step_loads_the_plugin_and_every_chunk_keeps_it():
    _label, argv = run_ci_suite._pytest_step("0", 8)
    i = argv.index("-p")
    assert argv[i + 1] == "scripts.pytest_rss_watch" == run_ci_suite.RSS_WATCH_PLUGIN
    pytest_args = argv[argv.index("--") + 1:]
    groups, flags = pytest_baseline._split_test_files(pytest_args, 8)
    assert len(groups) == 8 and all(g for g in groups)
    assert flags == ["-n", "0", "--dist=loadscope", "-p", "scripts.pytest_rss_watch"]
    assert not any(f == "scripts.pytest_rss_watch" or f.startswith("scripts/") for g in groups for f in g)


def test_github_ci_does_not_load_it():
    for name in ("ci.yml", "pytest-baseline-update.yml"):
        text = (REPO / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "pytest_rss_watch" not in text


# ---------------------------------------------------------------- knobs
@pytest.mark.parametrize("raw, expected", [(None, 256.0), ("", 256.0), ("junk", 256.0), ("0", 256.0),
                                           ("-5", 256.0), ("64", 64.0), (" 1.5 ", 1.5)])
def test_a_missing_junk_or_non_positive_knob_is_the_default(raw, expected):
    env = {} if raw is None else {"PYTEST_RSS_WATCH_JUMP_MB": raw}
    assert watch_mod.env_number("PYTEST_RSS_WATCH_JUMP_MB", env) == expected


def test_status_parse(tmp_path):
    p = tmp_path / "status"
    p.write_text("Name:\tpython\nVmHWM:\t  204800 kB\nVmRSS:\t  102400 kB\n", encoding="ascii")
    assert watch_mod.read_status_mb(str(p)) == {"VmHWM": 200.0, "VmRSS": 100.0}
    assert watch_mod.read_status_mb(str(tmp_path / "missing")) == {}


# ---------------------------------------------------------------- bookkeeping, with injected readers
class _Fake:
    def __init__(self, rss=100.0, hwm=None):
        self.rss, self.hwm, self.lines, self.resets = rss, hwm, [], 0

    def read(self):
        out = {"VmRSS": self.rss}
        if self.hwm is not None:
            out["VmHWM"] = self.hwm
        return out

    def reset(self):
        self.resets += 1
        self.hwm = self.rss
        return True


def _watch(fake, **env):
    base = {"PYTEST_RSS_WATCH_JUMP_MB": "100", "PYTEST_RSS_WATCH_CLIMB_FLOOR_MB": "1000",
            "PYTEST_RSS_WATCH_CLIMB_STEP_MB": "200", "PYTEST_RSS_WATCH_TOP": "3"}
    base.update(env)
    w = watch_mod.Watch(read=fake.read, reset=fake.reset, write=fake.lines.append, env=base)
    w.begin()
    return w


def test_begin_says_on_with_its_settings():
    fake = _Fake(hwm=100.0)
    _watch(fake)
    assert fake.lines[0].startswith("TEST_RSS_WATCH on pid=")
    assert "jump_mb=100 climb_floor_mb=1000 climb_step_mb=200 interval_s=2 hwm_reset=yes" in fake.lines[0]


def test_no_proc_says_off_once_and_stays_quiet():
    lines = []
    w = watch_mod.Watch(read=lambda: {}, reset=lambda: False, write=lines.append, env={})
    w.begin()
    w.start_test("t.py::a")
    w.sample()
    w.finish_test("t.py::a")
    w.summary()
    assert lines == ["TEST_RSS_WATCH off reason=no_proc"]


def test_a_test_that_peaks_writes_a_jump_and_one_under_the_threshold_does_not():
    fake = _Fake(rss=500.0, hwm=500.0)
    w = _watch(fake)
    w.start_test("tests/test_a.py::small")
    fake.rss, fake.hwm = 550.0, 580.0          # +80 MB peak: under 100
    w.finish_test("tests/test_a.py::small")
    w.start_test("tests/test_b.py::big")
    fake.hwm = 950.0                            # a transient peak the HWM saw, released by the end
    fake.rss = 560.0
    w.finish_test("tests/test_b.py::big")
    jumps = [ln for ln in fake.lines if ln.startswith("TEST_RSS_JUMP")]
    assert len(jumps) == 1
    assert jumps[0].startswith("TEST_RSS_JUMP nodeid=tests/test_b.py::big start_mb=550 peak_mb=950 end_mb=560")


def test_the_watchdog_names_a_climbing_test_at_each_step_and_not_a_plateau():
    fake = _Fake(rss=900.0, hwm=900.0)
    w = _watch(fake)
    w.start_test("tests/test_run.py::away")
    for rss in (950, 1050, 1150, 1250, 1300, 1460, 1500):
        fake.rss = float(rss)
        w.sample()
    climbs = [ln for ln in fake.lines if ln.startswith("TEST_RSS_CLIMB")]
    # 1150 is the first sample >= floor 1000 that has grown >= 200; then each further 200: 1460.
    assert [c.split()[2] for c in climbs] == ["rss_mb=1150", "rss_mb=1460"]
    assert all("nodeid=tests/test_run.py::away" in c and "start_mb=900" in c for c in climbs)
    w.finish_test("tests/test_run.py::away")
    # The next test starts on the plateau: no climb line for sitting there.
    w.start_test("tests/test_run.py::after")
    for _ in range(5):
        w.sample()
    assert len([ln for ln in fake.lines if ln.startswith("TEST_RSS_CLIMB")]) == 2


def test_the_sampled_peak_counts_when_the_kernel_cannot_reset_the_hwm():
    fake = _Fake(rss=300.0)
    lines = []
    w = watch_mod.Watch(read=lambda: {"VmRSS": fake.rss}, reset=lambda: False, write=lines.append,
                        env={"PYTEST_RSS_WATCH_JUMP_MB": "100"})
    w.begin()
    assert "hwm_reset=no" in lines[0]
    w.start_test("t.py::spike")
    fake.rss = 700.0
    w.sample()
    fake.rss = 320.0
    w.finish_test("t.py::spike")
    assert any(ln.startswith("TEST_RSS_JUMP nodeid=t.py::spike start_mb=300 peak_mb=700 end_mb=320") for ln in lines)


def test_the_summary_ranks_tests_files_and_growth():
    fake = _Fake(rss=100.0, hwm=100.0)
    w = _watch(fake)
    plan = [("tests/test_x.py::a", 150, 120), ("tests/test_x.py::b", 400, 300), ("tests/test_y.py::c", 900, 310),
            ("tests/test_z.py::d", 320, 320), ("tests/test_z.py::e", 330, 330)]
    for nodeid, peak, end in plan:
        w.start_test(nodeid)
        fake.hwm, fake.rss = float(peak), float(end)
        w.finish_test(nodeid)
    w.summary()
    top = [ln for ln in fake.lines if ln.startswith("TEST_RSS_TOP")]
    assert [ln.split()[2] for ln in top] == ["nodeid=tests/test_y.py::c", "nodeid=tests/test_x.py::b",
                                             "nodeid=tests/test_x.py::a"]
    files = [ln for ln in fake.lines if ln.startswith("TEST_RSS_FILE_TOP")]
    assert files[0].startswith("TEST_RSS_FILE_TOP rank=1 file=tests/test_y.py peak_mb=900 growth_mb=10 tests=1")
    growth = [ln for ln in fake.lines if ln.startswith("TEST_RSS_FILE_GROWTH_TOP")]
    assert growth[0].startswith("TEST_RSS_FILE_GROWTH_TOP rank=1 file=tests/test_x.py growth_mb=200")
    assert fake.lines[-1].startswith("TEST_RSS_SUMMARY tests=5 jumps=2 climbs=0 start_mb=100 session_peak_mb=900")


def test_an_error_writes_one_off_line_and_the_plugin_goes_quiet():
    lines = []
    state = {"n": 0}

    def read():
        state["n"] += 1
        if state["n"] == 3:
            raise RuntimeError("boom")
        return {"VmRSS": 100.0}

    w = watch_mod.Watch(read=read, reset=lambda: False, write=lines.append, env={})
    w.begin()
    w.start_test("t.py::a")
    watch_mod._WATCH, saved = w, watch_mod._WATCH
    try:
        watch_mod._guarded("finish_test", lambda: w.finish_test("t.py::a"))
        watch_mod._guarded("summary", w.summary)
    finally:
        watch_mod._WATCH = saved
    assert lines[-1] == "TEST_RSS_WATCH off reason=error where=finish_test error=RuntimeError"
    assert w.dead and not any(ln.startswith("TEST_RSS_SUMMARY") for ln in lines)


# ---------------------------------------------------------------- real pytest processes
_PROBE = textwrap.dedent("""
    import os, signal, time
    HELD = []

    def test_small():
        assert True

    def test_holds_96mb():
        HELD.append(bytearray(96 * 1024 * 1024))
        for i in range(0, len(HELD[-1]), 4096):
            HELD[-1][i] = 1

    def test_climbs_while_captured():
        print("captured output that pytest swallows")
        for _ in range(4):
            b = bytearray(48 * 1024 * 1024)
            for i in range(0, len(b), 4096):
                b[i] = 1
            HELD.append(b)
            time.sleep(0.4)

    def test_killed_mid_climb():
        if os.environ.get("PROBE_KILL") != "1":
            return
        for _ in range(4):
            b = bytearray(48 * 1024 * 1024)
            for i in range(0, len(b), 4096):
                b[i] = 1
            HELD.append(b)
            time.sleep(0.4)
        os.kill(os.getpid(), signal.SIGKILL)
""")


def _run_probe(tmp_path, *, plugin=True, kill=False, extra=()):
    probe = tmp_path / "test_probe_rss.py"
    probe.write_text(_PROBE, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "SYNDICATE_"))}
    env.update({"PYTEST_RSS_WATCH_JUMP_MB": "64", "PYTEST_RSS_WATCH_CLIMB_FLOOR_MB": "1",
                "PYTEST_RSS_WATCH_CLIMB_STEP_MB": "64", "PYTEST_RSS_WATCH_INTERVAL_S": "0.1",
                "PROBE_KILL": "1" if kill else "0", "PYTHONDONTWRITEBYTECODE": "1"})
    ini = tmp_path / "pytest.ini"
    ini.write_text("[pytest]\n", encoding="utf-8")
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(tmp_path),
           "-c", str(ini), *extra]
    if plugin:
        cmd += ["-p", "scripts.pytest_rss_watch"]
    cmd.append(str(probe))
    return subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=180)


@needs_proc
def test_a_real_run_off_is_not_on(tmp_path):
    off = _run_probe(tmp_path, plugin=False)
    on = _run_probe(tmp_path, plugin=True)
    assert off.returncode == 0 and on.returncode == 0, (off.stdout[-2000:], on.stdout[-2000:])
    assert "pytest_rss_watch" not in off.stdout
    out = on.stdout
    assert "[pytest_rss_watch] TEST_RSS_WATCH on pid=" in out and "hwm_reset=yes" in out
    assert "TEST_RSS_JUMP nodeid=" in out and "test_probe_rss.py::test_holds_96mb" in out
    # Written from the watchdog thread WHILE pytest captured that test's output: the import-time dup works.
    assert "TEST_RSS_CLIMB nodeid=" in out and any(
        "TEST_RSS_CLIMB" in ln and "test_climbs_while_captured" in ln for ln in out.splitlines())
    assert "captured output that pytest swallows" not in out
    assert "TEST_RSS_TOP rank=1 nodeid=" in out and "TEST_RSS_SUMMARY tests=4 " in out
    assert "4 passed" in out and "4 passed" in off.stdout
    # Every line starts with a UTC timestamp.
    stamped = re.compile(r"^20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ \[pytest_rss_watch\] TEST_RSS_")
    tagged = [ln for ln in out.splitlines() if "[pytest_rss_watch]" in ln]
    assert tagged and all(stamped.match(ln) for ln in tagged), tagged


@needs_proc
def test_a_test_the_kernel_kills_is_still_named(tmp_path):
    run = _run_probe(tmp_path, plugin=True, kill=True)
    assert run.returncode == -9
    lines = [ln for ln in run.stdout.splitlines() if "TEST_RSS_CLIMB" in ln and "test_killed_mid_climb" in ln]
    assert lines, run.stdout[-3000:]
    assert "TEST_RSS_SUMMARY" not in run.stdout  # the run never reached its end


def test_under_xdist_workers_it_stays_out_of_the_way(tmp_path):
    pytest.importorskip("xdist")
    run = _run_probe(tmp_path, plugin=True, extra=("-n", "1"))
    assert run.returncode == 0, run.stdout[-3000:]
    assert "4 passed" in run.stdout
    expected = "TEST_RSS_WATCH off reason=xdist_workers"
    assert expected in run.stdout
    assert "TEST_RSS_JUMP" not in run.stdout and "TEST_RSS_SUMMARY" not in run.stdout


@pytest.mark.skipif(LINUX_PROC, reason="the no-/proc path")
def test_without_proc_a_real_run_says_off_and_passes(tmp_path):
    run = _run_probe(tmp_path, plugin=True)
    assert run.returncode == 0, run.stdout[-3000:]
    assert "TEST_RSS_WATCH off reason=no_proc" in run.stdout and "TEST_RSS_JUMP" not in run.stdout
