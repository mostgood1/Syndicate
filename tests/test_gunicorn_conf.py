"""`gunicorn.conf.py` -- the web memory guard (lane `web-memory-guard`, 2026-09-17).

The load-bearing tests: the guard recycles a worker over its limit (off != on), never one
under it or too young, staggers two workers that cross together (a hard crossing for
`hard_recycle_spacing_seconds()`, re-checked on every request; only an emergency skips it --
lane `web-silent-worker-kills`, 2026-11-18), is disabled by its switch, and never raises into gunicorn. `post_fork` applies the
arena cap before the worker loads the app.
"""

from __future__ import annotations

import gc
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


@pytest.fixture(autouse=True)
def _restore_gc_thresholds():
    """`post_fork` tunes THIS process's collector; no test may leave it tuned for the next one."""
    saved = gc.get_threshold()
    yield
    gc.set_threshold(*saved)


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


# The GC tuning (lane `web-silent-worker-kills`, 2026-11-23: no automatic full collections in a web worker) is OFF by
# default since 2026-11-24: on its first day a tuned worker reached ~9.7 GB and the kernel OOM killer took it.
def test_post_fork_leaves_cpython_full_collections_by_default_and_says_so(monkeypatch, capsys):
    import syndicate.features.shared.memory_observability as mo

    monkeypatch.setattr(mo, "configure_malloc_arenas", lambda n: True)
    monkeypatch.delenv("SYNDICATE_WEB_GC_AUTO_FULL", raising=False)
    gc.set_threshold(700, 10, 10)
    worker = types.SimpleNamespace(alive=True)
    conf.post_fork(None, worker)
    assert gc.get_threshold() == (700, 10, 10)
    [tuned] = _lines(capsys, "WEB_GC_TUNED")
    assert tuned == {"pid": os.getpid(), "applied": False, "reason": "SYNDICATE_WEB_GC_AUTO_FULL",
                     "before": [700, 10, 10], "after": [700, 10, 10]}
    assert len(worker._syndicate_gc_at_fork) == 3, "the fast exit still counts collections from here"


def test_post_fork_applies_the_tuning_only_when_switched_off(monkeypatch, capsys):
    import syndicate.features.shared.memory_observability as mo

    monkeypatch.setattr(mo, "configure_malloc_arenas", lambda n: True)
    monkeypatch.setenv("SYNDICATE_WEB_GC_AUTO_FULL", "0")
    gc.set_threshold(700, 10, 10)
    conf.post_fork(None, types.SimpleNamespace(alive=True))
    assert gc.get_threshold() == (700, 10, conf.GC_FULL_THRESHOLD_OFF)
    [tuned] = _lines(capsys, "WEB_GC_TUNED")
    assert tuned == {"pid": os.getpid(), "applied": True, "before": [700, 10, 10], "after": [700, 10, 2**31 - 1]}


@pytest.mark.parametrize("on", [None, "", "1", "true", "ON", "yes", "garbage"])
@pytest.mark.parametrize("off", ["0", "false", "OFF", "no"])
def test_off_is_not_on_for_the_gc_tuning(monkeypatch, on, off):
    gc.set_threshold(700, 10, 10)
    if on is None:
        monkeypatch.delenv("SYNDICATE_WEB_GC_AUTO_FULL", raising=False)
    else:
        monkeypatch.setenv("SYNDICATE_WEB_GC_AUTO_FULL", on)
    assert conf.tune_gc()["applied"] is False and gc.get_threshold() == (700, 10, 10)
    monkeypatch.setenv("SYNDICATE_WEB_GC_AUTO_FULL", off)
    assert conf.tune_gc()["applied"] is True and gc.get_threshold() == (700, 10, conf.GC_FULL_THRESHOLD_OFF)


def test_a_growing_heap_gets_full_collections_by_default_and_none_once_tuned(monkeypatch):
    """Reachability on the real collector: the same growth runs full collections by default and none tuned."""
    monkeypatch.delenv("SYNDICATE_WEB_GC_AUTO_FULL", raising=False)

    def full_collections_while_the_heap_grows() -> int:
        gc.collect()  # sets the long-lived count the quarter rule compares against
        before = gc.get_stats()[2]["collections"]
        keep = [[] for _ in range(max(300_000, len(gc.get_objects())))]
        after = gc.get_stats()[2]["collections"]
        del keep
        return after - before

    gc.set_threshold(700, 10, 10)
    stock = full_collections_while_the_heap_grows()
    conf.tune_gc()  # the default: leaves CPython's own
    default = full_collections_while_the_heap_grows()
    monkeypatch.setenv("SYNDICATE_WEB_GC_AUTO_FULL", "0")
    conf.tune_gc()
    tuned = full_collections_while_the_heap_grows()
    assert stock >= 1, "the stock collector must run a full collection here, or this test proves nothing"
    assert default >= 1, "the default must keep CPython's full collections"
    assert tuned == 0


def test_young_collections_still_free_cycles_once_tuned(monkeypatch):
    monkeypatch.setenv("SYNDICATE_WEB_GC_AUTO_FULL", "0")
    conf.tune_gc()
    young_before = gc.get_stats()[0]["collected"] + gc.get_stats()[1]["collected"]
    for _ in range(5_000):
        a, b = [], []
        a.append(b)
        b.append(a)
    del a, b
    for _ in range(20_000):  # allocation pressure, so the young collections run
        [[]]
    assert gc.get_stats()[0]["collected"] + gc.get_stats()[1]["collected"] - young_before >= 9_000


def test_the_gc_tuning_never_raises_into_gunicorn(monkeypatch, capsys):
    import syndicate.features.shared.memory_observability as mo

    def boom(*a, **k):
        raise RuntimeError("no collector")

    monkeypatch.setattr(conf, "tune_gc", boom)
    monkeypatch.setattr(mo, "configure_malloc_arenas", lambda n: True)
    conf.post_fork(None, types.SimpleNamespace(alive=True))
    out = capsys.readouterr().out
    assert '"hook": "post_fork_gc"' in out and "WEB_MEMORY_GUARD_ARMED " in out, "the guard still arms"


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


def test_a_long_collection_is_queued_and_written_by_the_next_heartbeat(monkeypatch, capsys):
    monkeypatch.delenv("SYNDICATE_WEB_GC_PAUSE_LOG_SECONDS", raising=False)
    worker, beats = _beating_worker()
    hooks, clock, cpu, wall = [], _Clock(), _Cpu(), _Clock()
    assert conf.install_gc_pause_log(worker, now=clock, thread_cpu=cpu, callbacks=hooks, clock=wall) == "armed"
    [hook] = hooks
    hook("start", {"generation": 0})
    clock.t += 0.01
    hook("stop", {"generation": 0, "collected": 5, "uncollectable": 0})  # short: no line
    hook("start", {"generation": 2})
    clock.t += 3.5
    cpu.t += 3.4
    hook("stop", {"generation": 2, "collected": 12, "uncollectable": 0})
    hook("stop", None)  # a malformed call never raises
    assert _lines(capsys, "WEB_GC_PAUSE") == [], "the callback itself never writes"
    wall.t += 0.8
    worker.notify()
    assert beats == [1], "the original heartbeat still runs"
    [line] = _lines(capsys, "WEB_GC_PAUSE")
    assert line["generation"] == 2 and line["pause_s"] == 3.5 and line["thread_cpu_s"] == 3.4
    assert line["collected"] == 12 and line["thread"] and line["written_after_s"] == 0.8
    assert "_queued_at" not in line and "dropped_before" not in line
    worker.notify()
    assert _lines(capsys, "WEB_GC_PAUSE") == [], "written once"


def test_a_full_queue_drops_and_says_how_many(monkeypatch, capsys):
    monkeypatch.delenv("SYNDICATE_WEB_GC_PAUSE_LOG_SECONDS", raising=False)
    worker, _ = _beating_worker()
    hooks, clock = [], _Clock()
    conf.install_gc_pause_log(worker, now=clock, callbacks=hooks)
    [hook] = hooks
    for _ in range(conf.GC_PAUSE_QUEUE_CAP + 3):
        hook("start", {"generation": 2})
        clock.t += 1.0
        hook("stop", {"generation": 2, "collected": 0, "uncollectable": 0})
    worker.notify()
    lines = _lines(capsys, "WEB_GC_PAUSE")
    assert len(lines) == conf.GC_PAUSE_QUEUE_CAP and lines[0]["dropped_before"] == 3


def test_off_is_not_on_for_the_gc_pause_log(monkeypatch):
    monkeypatch.setenv("SYNDICATE_WEB_GC_PAUSE_LOG_SECONDS", "0")
    hooks = []
    assert conf.install_gc_pause_log(callbacks=hooks) == "disabled"
    assert hooks == []


def test_a_real_collection_reaches_the_gc_pause_log(monkeypatch, capsys):
    """Reachability: the hook in the REAL gc.callbacks, fired by a real full collection."""
    import gc

    monkeypatch.setenv("SYNDICATE_WEB_GC_PAUSE_LOG_SECONDS", "0.000000001")
    worker, _ = _beating_worker()
    before = list(gc.callbacks)
    try:
        assert conf.install_gc_pause_log(worker) == "armed"
        gc.collect()
    finally:
        gc.callbacks[:] = before
    worker.notify()
    lines = _lines(capsys, "WEB_GC_PAUSE")
    assert any(line["generation"] == 2 for line in lines)


def _stamped_stream_class(monkeypatch):
    """The fleet's real `StampedStream`, loaded by path with its import-time install switched off."""
    monkeypatch.setenv("SYNDICATE_LOCAL_LOG_TIMESTAMPS", "0")
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "local_logstamp" / "sitecustomize.py"
    spec = importlib.util.spec_from_file_location("_logstamp_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.StampedStream


def test_a_collection_inside_the_fleets_stamped_write_cannot_deadlock_the_writer(monkeypatch):
    """The 2026-11-20 20:01:56Z kill, reproduced with the real pieces: the fleet's `StampedStream` as stdout,
    the hook in the REAL gc.callbacks, and a real full collection fired from inside the stream's locked
    timestamp -- where the board warmer's print met a collection on the fleet. The first version of the hook
    printed from the callback, re-entered the non-reentrant lock on the same thread and never returned."""
    import gc
    import io
    import sys
    import threading

    stamped = _stamped_stream_class(monkeypatch)
    monkeypatch.setenv("SYNDICATE_WEB_GC_PAUSE_LOG_SECONDS", "0.000000001")
    sink = io.StringIO()
    fired = []

    def clock():
        import datetime as dt

        if not fired:
            fired.append(1)
            gc.collect()  # a full collection INSIDE `write`, under its lock
        return dt.datetime(2026, 11, 20, 20, 0, 54, tzinfo=dt.timezone.utc)

    stream = stamped(sink, clock=clock)
    monkeypatch.setattr(sys, "stdout", stream)
    worker, _ = _beating_worker()
    before = list(gc.callbacks)
    try:
        assert conf.install_gc_pause_log(worker) == "armed"
        writer = threading.Thread(
            target=lambda: print("[intelligence_state] STATE_DECODE_SKIPPED key=layer2_shortlist", flush=True),
            daemon=True)
        writer.start()
        writer.join(5.0)
        deadlocked = writer.is_alive()
    finally:
        gc.callbacks[:] = before
    assert fired == [1], "the collection really ran inside the locked write"
    assert not deadlocked, "the writer is stuck on the stream's own lock: the GC hook wrote from inside the callback"
    worker.notify()  # the main loop's heartbeat writes what the collection queued
    text = sink.getvalue()
    assert "STATE_DECODE_SKIPPED" in text
    gc_lines = [line for line in text.splitlines() if " WEB_GC_PAUSE " in line]
    assert gc_lines and all(line.startswith("2026-11-20T20:00:54.000Z ") for line in gc_lines), text


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


# --------------------------------------------------------------------------------------------
# `worker_exit` fast exit (2026-11-21): the 17:04:54Z dump was an EXITING worker ~55 s inside CPython's
# own shutdown (one thread, no Python frame). These pin: a worker whose loop returned with nothing in
# flight leaves through os._exit(0) after flushing stdio; one that never returned (boot error, a raise),
# still has a request running, or has the switch off takes the stock exit; the hook never raises into
# gunicorn; and gunicorn itself accepts it as `worker_exit`.
# --------------------------------------------------------------------------------------------


class _Future:
    def __init__(self, done):
        self._done = done

    def done(self):
        return self._done


class _Stream:
    def __init__(self, fail=False):
        self.flushed = 0
        self.fail = fail

    def flush(self):
        if self.fail:
            raise ValueError("I/O operation on closed file")
        self.flushed += 1


def _exiting_worker(returned_at=100.0, futures=()):
    worker = types.SimpleNamespace(futures=list(futures))
    if returned_at is not None:
        worker._syndicate_run_returned_at = returned_at
    return worker


def test_a_worker_whose_loop_returned_flushes_and_leaves_through_os_exit(monkeypatch, capsys):
    monkeypatch.delenv("SYNDICATE_WEB_WORKER_FAST_EXIT", raising=False)
    codes, streams = [], [_Stream(), _Stream()]
    worker = _exiting_worker(futures=[_Future(True)])
    assert conf.worker_exit(None, worker, exit_now=codes.append, streams=streams, clock=lambda: 100.25) == "exited"
    assert codes == [0]
    assert [s.flushed for s in streams] == [1, 1]
    [line] = _lines(capsys, "WEB_WORKER_FAST_EXIT")
    assert line == {"pid": os.getpid(), "after_loop_s": 0.25}


def test_the_fast_exit_counts_each_generations_collections_since_the_fork(monkeypatch, capsys):
    monkeypatch.delenv("SYNDICATE_WEB_WORKER_FAST_EXIT", raising=False)
    fake_gc = types.SimpleNamespace(get_stats=lambda: [{"collections": 950}, {"collections": 90}, {"collections": 4}])
    worker = _exiting_worker()
    worker._syndicate_gc_at_fork = [10, 1, 4]
    codes = []
    conf.worker_exit(None, worker, exit_now=codes.append, streams=[], clock=lambda: 100.0, gc_module=fake_gc)
    [line] = _lines(capsys, "WEB_WORKER_FAST_EXIT")
    assert line["gc_collections"] == [940, 89, 0] and codes == [0]


def test_a_worker_that_never_left_its_loop_takes_the_stock_exit(monkeypatch):
    """A boot error or a raise never sets the mark, so gunicorn's own exit codes (3 / 4 halt the arbiter) survive."""
    monkeypatch.delenv("SYNDICATE_WEB_WORKER_FAST_EXIT", raising=False)
    codes = []
    assert conf.worker_exit(None, _exiting_worker(returned_at=None), exit_now=codes.append, streams=[]) == "loop_did_not_return"
    assert conf.worker_exit(None, types.SimpleNamespace(), exit_now=codes.append, streams=[]) == "loop_did_not_return"
    assert codes == []


def test_a_request_still_running_takes_the_stock_exit_and_says_so(monkeypatch, capsys):
    monkeypatch.delenv("SYNDICATE_WEB_WORKER_FAST_EXIT", raising=False)
    codes = []
    worker = _exiting_worker(futures=[_Future(True), _Future(False)])
    assert conf.worker_exit(None, worker, exit_now=codes.append, streams=[]) == "request_running"
    assert codes == []
    [line] = _lines(capsys, "WEB_WORKER_STOCK_EXIT")
    assert line["reason"] == "request_running" and line["running"] == 1


@pytest.mark.parametrize("off", ["0", "false", "OFF", "no"])
def test_off_is_not_on_for_the_fast_exit(monkeypatch, off):
    monkeypatch.setenv("SYNDICATE_WEB_WORKER_FAST_EXIT", off)
    codes = []
    assert conf.worker_exit(None, _exiting_worker(), exit_now=codes.append, streams=[]) == "disabled"
    assert codes == []
    monkeypatch.setenv("SYNDICATE_WEB_WORKER_FAST_EXIT", "1")
    assert conf.worker_exit(None, _exiting_worker(), exit_now=codes.append, streams=[]) == "exited"
    assert codes == [0]


def test_a_stream_that_cannot_flush_does_not_keep_the_worker_in_shutdown(monkeypatch):
    monkeypatch.delenv("SYNDICATE_WEB_WORKER_FAST_EXIT", raising=False)
    codes, good = [], _Stream()
    assert conf.worker_exit(None, _exiting_worker(), exit_now=codes.append, streams=[_Stream(fail=True), good]) == "exited"
    assert codes == [0] and good.flushed == 1


def test_the_fast_exit_never_raises_into_gunicorn(monkeypatch, capsys):
    monkeypatch.delenv("SYNDICATE_WEB_WORKER_FAST_EXIT", raising=False)
    codes = []
    worker = _exiting_worker(returned_at="not a time")
    assert conf.worker_exit(None, worker, exit_now=codes.append, streams=[]) == "error"
    assert codes == []
    [line] = _lines(capsys, "WEB_WORKER_STOCK_EXIT")
    assert line["reason"] == "error"


def test_gunicorn_itself_accepts_the_worker_exit_hook():
    """Reachability: gunicorn validates a hook's positional arity; keyword-only test seams must not change it."""
    config = pytest.importorskip("gunicorn.config")
    cfg = config.Config()
    namespace = {}
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), namespace)
    cfg.set("worker_exit", namespace["worker_exit"])
    assert cfg.settings["worker_exit"].get() is namespace["worker_exit"]


# --------------------------------------------------------------------------------------------
# The quiet-worker memory watch (2026-11-24, user 11-23 "Yes, after the reading"). Worker 352017 reached ~9.7 GB
# 5 min after booting and the kernel OOM killer took it on 11-23: the guard reads memory only after every 5th
# request. These pin: off != on (default OFF until loaded alone); the timer reaches a quiet worker the request path
# cannot, under the guard's own rules; the abort fires on anon + swap at any age and while draining, and its
# switch turns it off; a real thread does it; and nothing raises into gunicorn or starts outside a guarded worker.
# --------------------------------------------------------------------------------------------


def _quiet_worker(limit=650.0, born=0.0):
    return _worker(limit=limit, born=born, requests=0)


@pytest.mark.parametrize("off", ["0", "0.0", "-1"])
def test_off_is_not_on_the_memory_watch_is_on_by_default_and_its_switch_turns_it_off(monkeypatch, off):
    monkeypatch.delenv("SYNDICATE_WEB_WORKER_MEMORY_WATCH_SECONDS", raising=False)
    worker = _quiet_worker()
    assert conf.memory_watch_seconds() == 5.0
    assert conf.install_memory_watch(worker, start=False) == "armed"
    assert worker._syndicate_memory_watch_thread.daemon is True
    monkeypatch.setenv("SYNDICATE_WEB_WORKER_MEMORY_WATCH_SECONDS", off)
    switched_off = _quiet_worker()
    assert conf.install_memory_watch(switched_off) == "disabled"
    assert not hasattr(switched_off, "_syndicate_memory_watch_thread")


def test_the_memory_watch_never_starts_outside_a_worker_post_fork_armed(monkeypatch):
    """A test (or any stray call) that runs `post_worker_init` in its own process must not get a thread that can
    `os._exit` that process at the abort ceiling."""
    monkeypatch.setenv("SYNDICATE_WEB_WORKER_MEMORY_WATCH_SECONDS", "5")
    assert conf.install_memory_watch(types.SimpleNamespace(alive=True)) == "not_armed"


def test_a_quiet_worker_over_its_limit_recycles_on_the_timer_where_the_request_path_cannot(tmp_path, capsys):
    """Reachability: the request path, between its 5-request checks, does not read memory at all."""
    by_request, by_timer = _quiet_worker(), _quiet_worker()
    stamp = str(tmp_path / "stamp")
    assert conf.decide_recycle(by_request, now=1000.0, anon_mb_reader=lambda: 1300.0, stamp_path=stamp) == "skipped"
    assert by_request.alive is True
    tick = conf.memory_watch_tick(by_timer, now=1000.0, reader=lambda: (1300.0, 0.0), stamp_path=stamp,
                                  exit_now=lambda code: pytest.fail("aborted below the ceiling"))
    assert tick == "recycled" and by_timer.alive is False
    [line] = _lines(capsys, "WEB_WORKER_MEMORY_RECYCLE")
    assert line["source"] == "timer" and line["requests"] == 0 and line["anon_mb"] == 1300.0


def test_the_timer_keeps_the_guards_rules(tmp_path):
    import time as _time

    stamp = str(tmp_path / "stamp")
    no_exit = {"exit_now": lambda code: pytest.fail("aborted below the ceiling")}
    assert conf.memory_watch_tick(_quiet_worker(), now=1000.0, reader=lambda: (600.0, 0.0), stamp_path=stamp,
                                  **no_exit) == "below_limit"
    assert conf.memory_watch_tick(_quiet_worker(born=990.0), now=1000.0, reader=lambda: (900.0, 0.0),
                                  stamp_path=stamp, **no_exit) == "too_young"
    conf._touch(stamp)  # another worker just recycled
    assert conf.memory_watch_tick(_quiet_worker(), now=_time.time(), reader=lambda: (660.0, 0.0),
                                  stamp_path=stamp, **no_exit) == "deferred"
    assert conf.memory_watch_tick(_quiet_worker(limit=0.0), now=1000.0, reader=lambda: (2000.0, 0.0),
                                  stamp_path=stamp, **no_exit) == "skipped"
    assert conf.memory_watch_tick(_quiet_worker(), now=1000.0, reader=lambda: (None, None), stamp_path=stamp,
                                  **no_exit) == "no_reading"


def test_the_abort_fires_on_anon_plus_swap_at_any_age_and_while_draining(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("SYNDICATE_WEB_WORKER_MEMORY_ABORT_MB", raising=False)
    exits = []
    draining_and_young = _worker(born=995.0, requests=3)
    draining_and_young.alive = False
    stamp = tmp_path / "stamp"
    tick = conf.memory_watch_tick(draining_and_young, now=1000.0, reader=lambda: (2000.0, 600.0),
                                  stamp_path=str(stamp), exit_now=exits.append, streams=[])
    assert tick == "aborted" and exits == [conf.MEMORY_ABORT_EXIT_CODE] and stamp.exists()
    [line] = _lines(capsys, "WEB_WORKER_MEMORY_ABORT")
    assert line == {"pid": os.getpid(), "anon_mb": 2000.0, "swap_mb": 600.0, "abort_mb": 2500, "alive": False,
                    "requests": 3, "age_s": 5.0, "exit_code": 70}
    # Resident memory alone under the ceiling, nothing swapped: no abort.
    assert conf.memory_watch_tick(_worker(born=995.0), now=1000.0, reader=lambda: (2400.0, 0.0),
                                  stamp_path=str(stamp), exit_now=exits.append, streams=[]) == "too_young"
    assert exits == [70]


def test_off_is_not_on_the_abort_switch(tmp_path, monkeypatch):
    exits = []
    draining = _worker()
    draining.alive = False
    monkeypatch.setenv("SYNDICATE_WEB_WORKER_MEMORY_ABORT_MB", "0")
    assert conf.memory_watch_tick(draining, now=1000.0, reader=lambda: (9000.0, 900.0), stamp_path=str(tmp_path / "s"),
                                  exit_now=exits.append, streams=[]) == "draining"
    monkeypatch.setenv("SYNDICATE_WEB_WORKER_MEMORY_ABORT_MB", "2500")
    assert conf.memory_watch_tick(draining, now=1000.0, reader=lambda: (9000.0, 900.0), stamp_path=str(tmp_path / "s"),
                                  exit_now=exits.append, streams=[]) == "aborted"
    assert exits == [70]


def test_the_abort_exit_code_does_not_halt_gunicorn():
    arbiter = pytest.importorskip("gunicorn.arbiter")
    assert conf.MEMORY_ABORT_EXIT_CODE not in (arbiter.Arbiter.WORKER_BOOT_ERROR, arbiter.Arbiter.APP_LOAD_ERROR)


def test_a_real_watch_thread_recycles_a_quiet_worker(tmp_path, capsys):
    import time as _time

    worker = _quiet_worker()
    assert conf.install_memory_watch(worker, interval=0.01, reader=lambda: (700.0, 0.0),
                                     stamp_path=str(tmp_path / "stamp"),
                                     exit_now=lambda code: pytest.fail("aborted below the ceiling")) == "armed"
    try:
        deadline = _time.monotonic() + 5.0
        while worker.alive and _time.monotonic() < deadline:
            _time.sleep(0.01)
    finally:
        worker._syndicate_memory_watch_stop.set()
        worker._syndicate_memory_watch_thread.join(2.0)
    assert worker.alive is False
    assert _lines(capsys, "WEB_WORKER_MEMORY_RECYCLE")[0]["source"] == "timer"


def test_the_watch_thread_never_raises_and_stays_quiet_after_three_errors(tmp_path, capsys):
    import time as _time

    calls = []

    def broken():
        calls.append(1)
        raise OSError("no /proc")

    worker = _quiet_worker()
    conf.install_memory_watch(worker, interval=0.005, reader=broken, stamp_path=str(tmp_path / "stamp"))
    try:
        deadline = _time.monotonic() + 5.0
        while len(calls) < 6 and _time.monotonic() < deadline:
            _time.sleep(0.01)
        assert worker._syndicate_memory_watch_thread.is_alive(), "an error must not end the watch"
    finally:
        worker._syndicate_memory_watch_stop.set()
        worker._syndicate_memory_watch_thread.join(2.0)
    errors = _lines(capsys, "WEB_MEMORY_GUARD_ERROR")
    assert len(calls) >= 6 and len(errors) == 3 and {e["hook"] for e in errors} == {"memory_watch"}


def test_rss_anon_swap_mb_reads_both_fields(tmp_path):
    status = tmp_path / "status"
    status.write_text("Name:\tpython\nRssAnon:\t 2097152 kB\nVmSwap:\t  524288 kB\n", encoding="ascii")
    assert conf.rss_anon_swap_mb(str(status)) == (2048.0, 512.0)
    assert conf.rss_anon_swap_mb(str(tmp_path / "missing")) == (None, None)


@pytest.mark.skipif(not os.path.exists("/proc/self/status"), reason="needs Linux /proc")
def test_rss_anon_swap_mb_reads_this_process():
    anon, swap = conf.rss_anon_swap_mb()
    assert anon is not None and anon > 0 and swap is not None and swap >= 0


def test_post_worker_init_logs_the_memory_watch_state(monkeypatch, capsys):
    """On by default, yet this process (no `post_fork` guard state) gets no thread that could `os._exit` it."""
    monkeypatch.delenv("SYNDICATE_WEB_WORKER_MEMORY_WATCH_SECONDS", raising=False)
    worker = types.SimpleNamespace()
    conf.post_worker_init(worker)
    [armed] = _lines(capsys, "WEB_MEMORY_WATCH_ARMED")
    assert armed["memory_watch"] == "not_armed" and armed["interval_s"] == 5.0 and armed["abort_mb"] == 2500
    assert not hasattr(worker, "_syndicate_memory_watch_thread")
