"""`gunicorn.conf.py` -- the web memory guard (lane `web-memory-guard`, 2026-09-17).

The load-bearing tests: the guard recycles a worker over its limit (off != on), never one
under it or too young, staggers two workers that cross together (a hard crossing for
`hard_recycle_spacing_seconds()`, re-checked on every request; only an emergency skips it --
lane `web-silent-worker-kills`, 2026-11-18), is disabled by its switch, and never raises into gunicorn. `post_fork` applies the
arena cap before the worker loads the app.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import types

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "gunicorn.conf.py"
_spec = importlib.util.spec_from_file_location("gunicorn_conf", _SRC)
conf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conf)


def _worker(limit=650.0, born=0.0, requests=4):
    return types.SimpleNamespace(alive=True, _syndicate_limit_mb=limit, _syndicate_born=born,
                                 _syndicate_requests=requests)


def _lines(capsys, event):
    return [json.loads(line.split(" ", 1)[1]) for line in capsys.readouterr().out.splitlines()
            if line.startswith(event + " ")]


def test_a_worker_over_its_limit_recycles_and_says_so(tmp_path, capsys):
    worker = _worker()
    stamp = tmp_path / "stamp"
    assert conf.decide_recycle(worker, now=1000.0, anon_mb_reader=lambda: 670.0, stamp_path=str(stamp)) == "recycled"
    assert worker.alive is False and stamp.exists()
    [line] = _lines(capsys, "WEB_WORKER_MEMORY_RECYCLE")
    assert line["anon_mb"] == 670.0 and line["requests"] == 5 and line["hard"] is False


def test_off_is_not_on_the_switch_disables_the_guard(tmp_path):
    worker = _worker(limit=0.0)
    assert conf.decide_recycle(worker, now=1000.0, anon_mb_reader=lambda: 5000.0, stamp_path=str(tmp_path / "s")) == "skipped"
    assert worker.alive is True


def test_under_the_limit_or_between_checks_nothing_happens(tmp_path):
    under = _worker()
    assert conf.decide_recycle(under, now=1000.0, anon_mb_reader=lambda: 649.0, stamp_path=str(tmp_path / "s")) == "below_limit"
    between = _worker(requests=0)
    assert conf.decide_recycle(between, now=1000.0, anon_mb_reader=lambda: 9999.0, stamp_path=str(tmp_path / "s")) == "skipped"
    assert under.alive and between.alive


def test_a_young_worker_is_never_recycled(tmp_path):
    worker = _worker(born=1000.0 - 30)
    assert conf.decide_recycle(worker, now=1000.0, anon_mb_reader=lambda: 900.0, stamp_path=str(tmp_path / "s")) == "too_young"
    assert worker.alive


def _hard_mb(limit=650.0):
    return limit + conf.hard_margin_mb() + 1


def _emergency_mb(limit=650.0):
    return limit + conf.hard_margin_mb() + conf.emergency_margin_mb() + 1


def test_two_workers_crossing_together_are_staggered_and_only_an_emergency_skips_it(tmp_path, capsys):
    stamp = str(tmp_path / "stamp")
    first, second, hard, emergency = _worker(), _worker(), _worker(), _worker()
    assert conf.decide_recycle(first, now=1000.0, anon_mb_reader=lambda: 660.0, stamp_path=stamp) == "recycled"
    assert conf.decide_recycle(second, now=1001.0, anon_mb_reader=lambda: 660.0, stamp_path=stamp) == "deferred"
    assert second.alive, "a soft crossing waits for the other worker's replacement"
    assert conf.decide_recycle(hard, now=1002.0, anon_mb_reader=_hard_mb, stamp_path=stamp) == "deferred_hard"
    assert hard.alive, "a hard crossing waits too, briefly"
    assert conf.decide_recycle(emergency, now=1003.0, anon_mb_reader=_emergency_mb, stamp_path=stamp) == "recycled"
    deferred = _lines(capsys, "WEB_WORKER_MEMORY_RECYCLE_DEFERRED")
    assert [d["hard"] for d in deferred] == [False, True]
    assert deferred[1]["hard_spacing_s"] == conf.hard_recycle_spacing_seconds() == 30


def test_the_1848z_double_hard_recycle_is_staggered_by_the_hard_spacing(tmp_path, capsys):
    """2026-11-18: pid 209505 hard-recycled at 18:48:01.6Z (971 MB vs 641) and pid 206403 1.7 s later (994 vs
    632), leaving no booted worker. Now the second holds until the hard spacing has passed since the first."""
    import time as _time

    stamp = str(tmp_path / "stamp")
    t0 = float(int(_time.time()))  # the stamp carries the REAL clock, so the window is measured on it
    a, b = _worker(limit=641.0, born=t0 - 682), _worker(limit=632.0, born=t0 - 1210)
    assert conf.decide_recycle(a, now=t0, anon_mb_reader=lambda: 971.1, stamp_path=stamp) == "recycled"
    assert conf.decide_recycle(b, now=t0 + 1.7, anon_mb_reader=lambda: 994.4, stamp_path=stamp) == "deferred_hard"
    # The very next request is checked although it is not a 5th one, and it still holds inside the window ...
    assert conf.decide_recycle(b, now=t0 + 20.0, anon_mb_reader=lambda: 1001.0, stamp_path=stamp) == "deferred_hard"
    assert b._syndicate_requests % conf.CHECK_EVERY_REQUESTS != 0
    assert b.alive
    # ... and goes on the first request after it, saying how long it was held.
    assert conf.decide_recycle(b, now=t0 + 31.0, anon_mb_reader=lambda: 1003.0, stamp_path=stamp) == "recycled"
    assert b.alive is False
    recycles = _lines(capsys, "WEB_WORKER_MEMORY_RECYCLE")
    assert len(recycles) == 2 and recycles[1]["hard_deferred_s"] == 29.3
    assert "hard_deferred_s" not in recycles[0], "the first worker was never held"


def test_off_is_not_on_hard_spacing_zero_restores_the_immediate_hard_recycle(tmp_path, monkeypatch):
    stamp = str(tmp_path / "stamp")
    first, second = _worker(), _worker()
    assert conf.decide_recycle(first, now=1000.0, anon_mb_reader=_hard_mb, stamp_path=stamp) == "recycled"
    monkeypatch.setenv("SYNDICATE_WEB_WORKER_HARD_RECYCLE_SPACING_SECONDS", "0")
    assert conf.decide_recycle(second, now=1001.0, anon_mb_reader=_hard_mb, stamp_path=stamp) == "recycled"
    monkeypatch.delenv("SYNDICATE_WEB_WORKER_HARD_RECYCLE_SPACING_SECONDS")
    third = _worker()
    assert conf.decide_recycle(third, now=1002.0, anon_mb_reader=_hard_mb, stamp_path=stamp) == "deferred_hard"


def test_a_hard_worker_with_no_recent_recycle_goes_at_once(tmp_path):
    worker = _worker()
    assert conf.decide_recycle(worker, now=1000.0, anon_mb_reader=_hard_mb, stamp_path=str(tmp_path / "s")) == "recycled"
    old = tmp_path / "old"
    old.write_text("")
    os.utime(old, (1000.0 - 31, 1000.0 - 31))
    assert conf.decide_recycle(_worker(), now=1000.0, anon_mb_reader=_hard_mb, stamp_path=str(old)) == "recycled"


def test_a_held_worker_that_shrinks_stops_checking_every_request(tmp_path):
    stamp = str(tmp_path / "stamp")
    conf.decide_recycle(_worker(), now=1000.0, anon_mb_reader=_hard_mb, stamp_path=stamp)
    held = _worker()
    assert conf.decide_recycle(held, now=1001.0, anon_mb_reader=_hard_mb, stamp_path=stamp) == "deferred_hard"
    assert conf.decide_recycle(held, now=1002.0, anon_mb_reader=lambda: 100.0, stamp_path=stamp) == "below_limit"
    assert conf.decide_recycle(held, now=1003.0, anon_mb_reader=lambda: 9999.0, stamp_path=stamp) == "skipped"


def test_a_worker_held_again_after_a_dip_logs_the_new_hold_and_times_it_from_there(tmp_path, capsys):
    """Findings Reading 3 (2026-11-19): the below-limit branch cleared the pending flag but not the hold's start, so a
    worker that was held, dipped under its limit and was held again logged no second DEFERRED line, and its
    `hard_deferred_s` counted from the FIRST hold (here 1031.0 instead of 31.0)."""
    stamp = tmp_path / "stamp"
    stamp.write_text("")
    os.utime(stamp, (995.0, 995.0))
    held = _worker()
    assert conf.decide_recycle(held, now=1000.0, anon_mb_reader=_hard_mb, stamp_path=str(stamp)) == "deferred_hard"
    assert conf.decide_recycle(held, now=1001.0, anon_mb_reader=lambda: 100.0, stamp_path=str(stamp)) == "below_limit"
    os.utime(stamp, (1995.0, 1995.0))  # the other worker recycles much later
    held._syndicate_requests = 9  # the next request is a 5th one, so it is checked
    assert conf.decide_recycle(held, now=2000.0, anon_mb_reader=_hard_mb, stamp_path=str(stamp)) == "deferred_hard"
    assert conf.decide_recycle(held, now=2031.0, anon_mb_reader=_hard_mb, stamp_path=str(stamp)) == "recycled"
    out = capsys.readouterr().out.splitlines()
    deferred = [json.loads(x.split(" ", 1)[1]) for x in out if x.startswith("WEB_WORKER_MEMORY_RECYCLE_DEFERRED ")]
    [recycle] = [json.loads(x.split(" ", 1)[1]) for x in out if x.startswith("WEB_WORKER_MEMORY_RECYCLE ")]
    assert [d["last_recycle_age_s"] for d in deferred] == [5.0, 5.0], "each hold logs its own DEFERRED line"
    assert recycle["hard_deferred_s"] == 31.0, "the hold is timed from the second hold, not the first"


def test_a_hook_that_fails_never_raises_into_gunicorn(capsys, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("proc unreadable")

    monkeypatch.setattr(conf, "decide_recycle", boom)
    conf.post_request(_worker(), None, {}, None)
    assert _lines(capsys, "WEB_MEMORY_GUARD_ERROR")[0]["hook"] == "post_request"


def test_post_fork_applies_the_arena_cap_and_arms_the_guard(monkeypatch, capsys):
    calls = []
    import syndicate.features.shared.memory_observability as mo

    monkeypatch.setattr(mo, "configure_malloc_arenas", lambda n: calls.append(n) or True)
    monkeypatch.delenv("SYNDICATE_WEB_MALLOC_ARENA_MAX", raising=False)
    monkeypatch.delenv("SYNDICATE_WEB_WORKER_ANON_LIMIT_MB", raising=False)
    worker = types.SimpleNamespace(alive=True)
    conf.post_fork(None, worker)
    assert calls == [2]
    [armed] = _lines(capsys, "WEB_MEMORY_GUARD_ARMED")
    assert armed["arena_cap_applied"] is True and 617 <= armed["anon_limit_mb"] <= 650
    assert armed["hard_spacing_s"] == 30 and armed["emergency_margin_mb"] == 600
    assert worker._syndicate_requests == 0


def test_post_fork_respects_both_switches(monkeypatch, capsys):
    calls = []
    import syndicate.features.shared.memory_observability as mo

    monkeypatch.setattr(mo, "configure_malloc_arenas", lambda n: calls.append(n) or True)
    monkeypatch.setenv("SYNDICATE_WEB_MALLOC_ARENA_MAX", "0")
    monkeypatch.setenv("SYNDICATE_WEB_WORKER_ANON_LIMIT_MB", "0")
    worker = types.SimpleNamespace(alive=True)
    conf.post_fork(None, worker)
    assert calls == [] and worker._syndicate_limit_mb == 0.0
    [armed] = _lines(capsys, "WEB_MEMORY_GUARD_ARMED")
    assert armed["arena_cap_applied"] is None


@pytest.mark.parametrize("raw, expected", [("", 650), ("700", 700), ("garbage", 650), ("0", 0)])
def test_a_typo_in_the_limit_never_disables_the_guard(monkeypatch, raw, expected):
    monkeypatch.setenv("SYNDICATE_WEB_WORKER_ANON_LIMIT_MB", raw)
    assert conf.anon_limit_mb() == expected


@pytest.mark.parametrize("raw, spacing, margin", [("", 30, 600), ("45", 45, 45), ("garbage", 30, 600)])
def test_a_typo_in_the_hard_stagger_keeps_its_defaults(monkeypatch, raw, spacing, margin):
    monkeypatch.setenv("SYNDICATE_WEB_WORKER_HARD_RECYCLE_SPACING_SECONDS", raw)
    monkeypatch.setenv("SYNDICATE_WEB_WORKER_EMERGENCY_MARGIN_MB", raw)
    assert conf.hard_recycle_spacing_seconds() == spacing and conf.emergency_margin_mb() == margin


def test_rss_anon_reads_proc_status(tmp_path):
    status = tmp_path / "status"
    status.write_text("Name:\tgunicorn\nRssAnon:\t  716800 kB\nRssFile:\t 1024 kB\n", encoding="ascii")
    assert conf.rss_anon_mb(str(status)) == 700.0
    assert conf.rss_anon_mb(str(tmp_path / "missing")) is None


def test_gunicorn_itself_loads_the_hooks():
    """Reachability: the config file parses the way gunicorn reads it, and names the two hooks."""
    config = pytest.importorskip("gunicorn.config")
    cfg = config.Config()
    namespace = {}
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), namespace)
    for name in ("post_fork", "post_request"):
        cfg.set(name, namespace[name])
        assert cfg.settings[name].get() is namespace[name]


# --- the access log duration (lane `web-access-log-durations`, 2026-09-22) -------------

_DEFAULT_ACCESS_FORMAT = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'
_ATOMS = {"h": "10.228.18.171", "l": "-", "u": "-", "t": "[22/Sep/2026:11:11:01 -0500]",
          "r": "GET /healthz HTTP/1.1", "s": "200", "b": "34", "f": "-", "a": "Render/1.0", "M": 12}


def test_access_log_lines_end_with_the_request_duration():
    """Web's access lines could COUNT the requests holding its 8 slots during a flap but not
    rank them (lane `web-flap-0922`); gunicorn's `%(M)s` is request time in milliseconds."""
    line = conf.access_log_format % _ATOMS
    assert line.endswith('"Render/1.0" 12ms')
    # Everything gunicorn logged before is still there, in the same order.
    assert line.startswith(_DEFAULT_ACCESS_FORMAT % _ATOMS)


def test_gunicorn_itself_reads_the_access_log_format():
    """Reachability: gunicorn accepts the setting, and its logger supplies the `M` atom."""
    config = pytest.importorskip("gunicorn.config")
    glogging = pytest.importorskip("gunicorn.glogging")
    cfg = config.Config()
    namespace = {}
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), namespace)
    cfg.set("access_log_format", namespace["access_log_format"])
    assert cfg.access_log_format.endswith("%(M)sms")
    assert "'M':" in pathlib.Path(glogging.__file__).read_text(encoding="utf-8")


def test_loading_the_conf_drops_the_cached_worker_module(monkeypatch):
    """Lane `web-restart-healthz`: gunicorn re-executes this file on HUP and then
    re-resolves `worker_class`; without dropping the master's cached module, the new
    workers ran the OLD class (A/B on a real gunicorn 21.2.0 HUP, 2026-10-06: 0/3
    probes on the new code with the old conf, 3/3 with this one)."""
    import runpy
    import sys

    sentinel = types.ModuleType("syndicate.web_worker")
    monkeypatch.setitem(sys.modules, "syndicate.web_worker", sentinel)
    runpy.run_path(str(pathlib.Path(__file__).resolve().parents[1] / "gunicorn.conf.py"))
    assert sys.modules.get("syndicate.web_worker") is not sentinel


# --------------------------------------------------------------------------------------------
# The loop-stall black box -- lane `web-silent-worker-kills` [2026-11-18]. Each heartbeat re-arms a
# faulthandler stack dump; a loop that stops turning gets every thread's stack written BEFORE the
# master's 60 s kill. These pin: the wrapper still heartbeats, re-arms at most every 5 s, fires
# inside the kill timeout, is switchable, never raises into gunicorn, and really dumps (off != on).
# --------------------------------------------------------------------------------------------


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _beating_worker(timeout=60):
    calls = []
    worker = types.SimpleNamespace(cfg=types.SimpleNamespace(timeout=timeout), notify=lambda: calls.append(1))
    return worker, calls


def test_each_heartbeat_still_beats_and_rearms_the_dump_at_most_every_5_s(monkeypatch, capsys):
    monkeypatch.delenv("SYNDICATE_WEB_LOOP_STALL_DUMP_SECONDS", raising=False)
    worker, beats = _beating_worker()
    armed, clock = [], _Clock()
    out = object()
    assert conf.install_loop_stall_dump(worker, now=clock, dump_later=lambda *a, **k: armed.append((a, k)),
                                        stream=out) == "armed"
    worker.notify()
    clock.t += 1.0
    worker.notify()
    clock.t += 4.5
    worker.notify()
    assert len(beats) == 3, "the original heartbeat runs on every turn"
    assert len(armed) == 2, "armed at the first beat and again only once 5 s had passed"
    args, kwargs = armed[0]
    assert args == (40.0,) and kwargs == {"repeat": False, "file": out, "exit": False}
    [line] = _lines(capsys, "WEB_LOOP_STALL_DUMP_ARMED")
    assert line["dump_after_s"] == 40.0 and line["kill_timeout_s"] == 60.0


@pytest.mark.parametrize("raw, timeout, expected", [
    ("", 60, 40.0),          # default
    ("100", 60, 50.0),       # never later than 10 s before the master's kill
    ("abc", 60, 40.0),       # a typo keeps the default
    ("5", 3, 1.0),           # a tiny timeout still dumps, at 1 s
    ("0", 60, 0.0),          # off
    ("-1", 60, 0.0),
])
def test_the_dump_always_fires_before_the_kill(monkeypatch, raw, timeout, expected):
    monkeypatch.setenv("SYNDICATE_WEB_LOOP_STALL_DUMP_SECONDS", raw)
    assert conf.stall_dump_seconds(timeout) == expected


def test_off_leaves_the_heartbeat_untouched(monkeypatch):
    monkeypatch.setenv("SYNDICATE_WEB_LOOP_STALL_DUMP_SECONDS", "0")
    worker, _ = _beating_worker()
    original = worker.notify
    assert conf.install_loop_stall_dump(worker, dump_later=lambda *a, **k: pytest.fail("armed while off")) == "disabled"
    assert worker.notify is original


def test_post_worker_init_never_raises_into_gunicorn(capsys):
    conf.post_worker_init(types.SimpleNamespace())  # no cfg, no notify
    assert _lines(capsys, "WEB_LOOP_STALL_DUMP_ERROR")[0]["hook"] == "post_worker_init"


def test_a_loop_that_stops_turning_gets_every_threads_stack_dumped(monkeypatch, tmp_path):
    """Reachability: the real faulthandler watchdog, armed by one heartbeat and then starved."""
    import faulthandler
    import time as _time

    monkeypatch.setenv("SYNDICATE_WEB_LOOP_STALL_DUMP_SECONDS", "1")
    worker, _ = _beating_worker(timeout=3)  # dump at max(1, min(1, 3 - 10)) = 1 s
    path = tmp_path / "dump.txt"
    with open(path, "w+", encoding="utf-8") as fh:
        try:
            conf.install_loop_stall_dump(worker, stream=fh)
            worker.notify()  # the last turn of the loop
            _time.sleep(1.6)  # the loop is stuck
        finally:
            faulthandler.cancel_dump_traceback_later()
    text = path.read_text(encoding="utf-8", errors="replace")
    assert "Timeout (0:00:01)!" in text and "test_a_loop_that_stops_turning" in text


# --------------------------------------------------------------------------------------------
# `WEB_LOOP_STALL` / `WEB_GC_PAUSE` (2026-11-20): the 16:08:10Z dump named a request thread inside
# one `json.loads` holding the GIL 40+ s; these two lines separate a GC pause, the decode itself and
# a starved vCPU. They pin: the stall line carries the gap and the process CPU, the GC line carries
# the generation and the collecting thread's CPU, both are switchable, and a real gc.collect() and a
# real heartbeat reach them (off != on).
# --------------------------------------------------------------------------------------------


class _Cpu:
    def __init__(self):
        self.t = 10.0

    def __call__(self):
        return self.t


def test_a_heartbeat_after_a_long_gap_logs_the_gap_and_the_cpu_spent_in_it(monkeypatch, capsys):
    monkeypatch.delenv("SYNDICATE_WEB_LOOP_STALL_LOG_SECONDS", raising=False)
    worker, beats = _beating_worker()
    clock, cpu = _Clock(), _Cpu()
    assert conf.install_loop_stall_log(worker, now=clock, cpu=cpu) == "armed"
    clock.t += 1.0
    worker.notify()  # a normal turn: no line
    clock.t += 41.0
    cpu.t += 40.2  # one thread burned a full core through the gap
    worker.notify()
    assert len(beats) == 2, "the original heartbeat runs on every turn"
    [line] = _lines(capsys, "WEB_LOOP_STALL")
    assert line["gap_s"] == 41.0 and line["process_cpu_s"] == 40.2 and line["cpu_per_wall"] == 0.98


def test_off_is_not_on_for_the_stall_log(monkeypatch, capsys):
    monkeypatch.setenv("SYNDICATE_WEB_LOOP_STALL_LOG_SECONDS", "0")
    worker, _ = _beating_worker()
    original = worker.notify
    assert conf.install_loop_stall_log(worker) == "disabled"
    assert worker.notify is original


def test_a_long_collection_logs_its_generation_pause_and_cpu(monkeypatch, capsys):
    monkeypatch.delenv("SYNDICATE_WEB_GC_PAUSE_LOG_SECONDS", raising=False)
    hooks, clock, cpu = [], _Clock(), _Cpu()
    assert conf.install_gc_pause_log(now=clock, thread_cpu=cpu, callbacks=hooks) == "armed"
    [hook] = hooks
    hook("start", {"generation": 0})
    clock.t += 0.01
    hook("stop", {"generation": 0, "collected": 5, "uncollectable": 0})  # short: no line
    hook("start", {"generation": 2})
    clock.t += 3.5
    cpu.t += 3.4
    hook("stop", {"generation": 2, "collected": 12, "uncollectable": 0})
    hook("stop", None)  # a malformed call never raises
    [line] = _lines(capsys, "WEB_GC_PAUSE")
    assert line["generation"] == 2 and line["pause_s"] == 3.5 and line["thread_cpu_s"] == 3.4
    assert line["collected"] == 12 and line["thread"]


def test_off_is_not_on_for_the_gc_pause_log(monkeypatch):
    monkeypatch.setenv("SYNDICATE_WEB_GC_PAUSE_LOG_SECONDS", "0")
    hooks = []
    assert conf.install_gc_pause_log(callbacks=hooks) == "disabled"
    assert hooks == []


def test_a_real_collection_reaches_the_gc_pause_log(monkeypatch, capsys):
    """Reachability: the hook in the REAL gc.callbacks, fired by a real full collection."""
    import gc

    monkeypatch.setenv("SYNDICATE_WEB_GC_PAUSE_LOG_SECONDS", "0.000000001")
    before = list(gc.callbacks)
    try:
        assert conf.install_gc_pause_log() == "armed"
        gc.collect()
    finally:
        gc.callbacks[:] = before
    lines = _lines(capsys, "WEB_GC_PAUSE")
    assert any(line["generation"] == 2 for line in lines)


def test_post_worker_init_arms_both_instruments_on_a_real_heartbeat(monkeypatch, capsys):
    import faulthandler
    import gc

    for name in ("SYNDICATE_WEB_LOOP_STALL_DUMP_SECONDS", "SYNDICATE_WEB_LOOP_STALL_LOG_SECONDS",
                 "SYNDICATE_WEB_GC_PAUSE_LOG_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    worker, beats = _beating_worker()
    before = list(gc.callbacks)
    try:
        conf.post_worker_init(worker)
        worker.notify()
    finally:
        gc.callbacks[:] = before
        faulthandler.cancel_dump_traceback_later()
    assert beats == [1]
    [armed] = _lines(capsys, "WEB_STALL_INSTRUMENTS_ARMED")
    assert armed["loop_stall_log"] == "armed" and armed["gc_pause_log"] == "armed"
    assert armed["loop_stall_log_s"] == 5.0 and armed["gc_pause_log_s"] == 0.25
