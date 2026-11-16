"""`scripts/_pipeline_diag.py` reads the FLEET, not Render (lane render-retirement, 2026-11-15).

Every fleet read goes through `fleet_shell`, which these tests stub, so nothing here
touches WSL or the live fleet.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import _pipeline_diag as diag  # noqa: E402


def test_no_render_api_left():
    source = (REPO_ROOT / "scripts" / "_pipeline_diag.py").read_text(encoding="utf-8")
    assert "api.render.com" not in source
    for name in ("render_json", "render_owner_id", "RENDER_API", "secret"):
        assert not hasattr(diag, name), name
    assert set(diag.SERVICES) == {"web", "refresh-worker", "live-odds-worker"}


def _stub_shell(monkeypatch, responses):
    calls = []

    def fake(command, *, timeout=120):
        calls.append(command)
        for needle, reply in responses:
            if needle in command:
                return reply
        return "", "unexpected command"

    monkeypatch.setattr(diag, "fleet_shell", fake)
    return calls


def test_fetch_logs_tails_the_role_log_and_parses_stamps(monkeypatch):
    text = (
        "Traceback before any stamp\n"
        "2026-11-15T10:00:00.123Z PUBLISH_OK path=a\n"
        "  continuation line\n"
        "2026-11-15T10:05:00Z LAYER2_SHORTLIST rows=3\n"
    )
    calls = _stub_shell(monkeypatch, [("refresh-worker.log", (text, ""))])
    logs, error = diag.fetch_logs("refresh-worker", limit=500)
    assert error == ""
    assert "tail -n 500" in calls[0] and "/refresh-worker.log" in calls[0]
    assert [row["timestamp"] for row in logs] == [
        "2026-11-15T10:00:00.123", "2026-11-15T10:00:00.123", "2026-11-15T10:05:00"]
    assert logs[1]["approximate"] is True and "approximate" not in logs[0]
    assert diag.log_window(logs)[2] == pytest.approx(4.998, abs=0.01)


def test_fetch_logs_failed_read_is_an_error_not_an_empty_log(monkeypatch):
    _stub_shell(monkeypatch, [("web.log", ("", "fleet shell rc 1: no such file"))])
    logs, error = diag.fetch_logs("web")
    assert logs == [] and "rc 1" in error
    assert diag.fetch_logs("nonsense")[1].startswith("unknown service")


def test_service_commits_reads_fleet_status(monkeypatch):
    status = {
        "web": {"pid": "1", "up": True, "live_commit": "abc12345"},
        "refresh-worker": {"pid": "2", "up": False, "live_commit": "abc12345"},
    }
    monkeypatch.setattr(diag, "_fleet_status", lambda: ("HEAD", status))
    assert diag.service_commits() == {
        "web": "abc12345",
        "refresh-worker": "?(role DOWN)",
        "live-odds-worker": "?(not in local_production.py status)",
    }


def test_service_commits_survives_a_failed_status(monkeypatch):
    def boom():
        raise RuntimeError("wsl gone")

    monkeypatch.setattr(diag, "_fleet_status", boom)
    assert all(value.startswith("?(") for value in diag.service_commits().values())


def test_oom_events_refresh_worker_reads_role_restarts(monkeypatch):
    rows = [
        {"at": "2026-11-15T01:00:00+00:00", "role": "refresh-worker", "event": "exit", "code": 0,
         "signal": None, "claimed": True},
        {"at": "2026-11-15T02:00:00+00:00", "role": "refresh-worker", "event": "exit", "code": -9,
         "signal": "SIGKILL", "claimed": False},
        {"at": "2026-11-15T03:00:00+00:00", "role": "web", "event": "exit", "code": 0, "signal": None},
    ]
    text = "\n".join(json.dumps(row) for row in rows) + "\nnot json\n"
    _stub_shell(monkeypatch, [("role_restarts.jsonl", (text, ""))])
    events = diag.oom_events("refresh-worker")
    assert events[0] == ("2026-11-15T02:00:00", "OOM KILLED? (SIGKILL: the kernel OOM killer or a kill -9) (UNCLAIMED)")
    assert events[1] == ("2026-11-15T01:00:00", "exit code=0 (claimed restart)")
    assert len(events) == 2


def test_oom_events_web_reads_gunicorn_kill_lines(monkeypatch):
    text = (
        "2026-11-15T04:00:00Z [ERROR] Worker (pid:12) was sent SIGKILL! Perhaps out of memory?\n"
        "2026-11-15T05:00:00Z [CRITICAL] WORKER TIMEOUT (pid:13)\n"
    )
    _stub_shell(monkeypatch, [("web.log", (text, ""))])
    events = diag.oom_events("web")
    assert events == [
        ("2026-11-15T05:00:00", "unhealthy: gunicorn WORKER TIMEOUT"),
        ("2026-11-15T04:00:00", "OOM KILLED? (gunicorn worker SIGKILL)"),
    ]


def test_oom_events_unrecorded_role_is_unknown_not_empty(monkeypatch):
    _stub_shell(monkeypatch, [])
    assert diag.oom_events("live-odds-worker") is None


def test_fleet_role_env_sends_only_named_keys(monkeypatch):
    monkeypatch.setattr(diag, "_fleet_status", lambda: ("HEAD", {"refresh-worker": {"pid": "4242"}}))
    calls = _stub_shell(monkeypatch, [("/proc/4242/environ", ("FLAG_A=true\nFLAG_B=60\nOTHER=x\n", ""))])
    values, error = diag.fleet_role_env("refresh-worker", ["FLAG_B", "FLAG_A"])
    assert error == "" and values == {"FLAG_A": "true", "FLAG_B": "60"}
    assert "^(FLAG_A|FLAG_B)=" in calls[0]


def test_fleet_role_env_refuses_anything_but_a_name(monkeypatch):
    monkeypatch.setattr(diag, "_fleet_status", lambda: pytest.fail("must refuse before reading"))
    values, error = diag.fleet_role_env("refresh-worker", ["OK_KEY", "x; cat /etc/passwd"])
    assert values == {} and "refusing" in error
