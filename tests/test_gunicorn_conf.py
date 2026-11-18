"""`gunicorn.conf.py` -- the web memory guard (lane `web-memory-guard`, 2026-09-17).

The load-bearing tests: the guard recycles a worker over its limit (off != on), never one
under it or too young, staggers two workers that cross together unless one is over the hard
limit, is disabled by its switch, and never raises into gunicorn. `post_fork` applies the
arena cap before the worker loads the app.
"""

from __future__ import annotations

import importlib.util
import json
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


def test_two_workers_crossing_together_are_staggered_unless_one_is_over_the_hard_limit(tmp_path, capsys):
    stamp = str(tmp_path / "stamp")
    first, second, hard = _worker(), _worker(), _worker()
    assert conf.decide_recycle(first, now=1000.0, anon_mb_reader=lambda: 660.0, stamp_path=stamp) == "recycled"
    assert conf.decide_recycle(second, now=1001.0, anon_mb_reader=lambda: 660.0, stamp_path=stamp) == "deferred"
    assert second.alive, "a soft crossing waits for the other worker's replacement"
    assert conf.decide_recycle(hard, now=1002.0, anon_mb_reader=lambda: 650.0 + conf.hard_margin_mb() + 1,
                               stamp_path=stamp) == "recycled"
    assert len(_lines(capsys, "WEB_WORKER_MEMORY_RECYCLE_DEFERRED")) == 1


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
