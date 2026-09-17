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
