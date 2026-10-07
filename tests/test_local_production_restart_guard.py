"""Refresh-worker restarts must be covered by a deploy claim (lane `web-restart-healthz`, 2026-10-07).

Five unannounced refresh-worker restarts in one afternoon each killed the in-flight board
build and paid a ~20 min cold rebuild. The supervisor cannot stop an external `kill`, so it
RECORDS every signal death as claimed or unclaimed; `down`, which it does control, refuses
without a claim (systemd shutdown excepted).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from scripts import local_production as lp


@pytest.fixture()
def fleet(tmp_path: Path):
    settings = lp.Settings(home=tmp_path / "home", port=12345)
    claims = tmp_path / "claims"
    claims.mkdir()
    local = {"SYNDICATE_DEPLOY_CLAIM_DIR": str(claims)}
    return settings, local, claims


def _claim(claims: Path, *, age: float = 60, ttl: float = 2700, holder: str = "some-lane") -> None:
    (claims / "refresh-worker.json").write_text(
        json.dumps({"holder": holder, "acquired_at": time.time() - age, "ttl_seconds": ttl}), encoding="utf-8"
    )


def _events(settings) -> list[dict]:
    path = settings.logs_dir / lp.ROLE_RESTARTS_LOG
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_claim_dir_comes_from_the_env_file(fleet):
    _, local, claims = fleet
    assert lp.deploy_claim_dir(local) == claims


@pytest.mark.parametrize("age,ttl,expected", [(60, 2700, True), (3000, 2700, False)])
def test_expired_claim_does_not_cover(fleet, age, ttl, expected):
    _, _, claims = fleet
    _claim(claims, age=age, ttl=ttl)
    assert (lp.active_role_claim(claims, "refresh-worker") is not None) is expected


def test_unreadable_claim_is_unclaimed_not_permissive(fleet):
    _, _, claims = fleet
    (claims / "refresh-worker.json").write_text("{not json", encoding="utf-8")
    assert lp.active_role_claim(claims, "refresh-worker") is None


@pytest.mark.parametrize("code,name", [(-15, "SIGTERM"), (-9, "SIGKILL"), (143, "SIGTERM"), (137, "SIGKILL"),
                                       (0, None), (1, None), (None, None)])
def test_signal_name(code, name):
    if name and not hasattr(lp.signal, name):
        pytest.skip(f"{name} not on this platform")
    assert lp._signal_name(code) == name


def test_unclaimed_term_is_announced_and_logged(fleet):
    settings, local, _ = fleet
    verdict = lp.note_role_exit(settings, local, "refresh-worker", -15, 812.4)
    assert verdict and verdict.startswith("UNCLAIMED_RESTART signal=SIGTERM")
    [event] = _events(settings)
    assert event["event"] == "signal_exit" and event["claimed"] is False and event["ran_s"] == 812


def test_claimed_term_names_the_holder(fleet):
    settings, local, claims = fleet
    _claim(claims, holder="web-restart-healthz")
    verdict = lp.note_role_exit(settings, local, "refresh-worker", -15, 30)
    assert verdict == "CLAIMED_RESTART signal=SIGTERM holder=web-restart-healthz"
    assert _events(settings)[0]["holder"] == "web-restart-healthz"


@pytest.mark.parametrize("role,code", [("refresh-worker", 1), ("refresh-worker", 0), ("web", -15)])
def test_crashes_and_unguarded_roles_are_not_restart_events(fleet, role, code):
    settings, local, _ = fleet
    assert lp.note_role_exit(settings, local, role, code, 5) is None
    assert _events(settings) == []


def _down_args(settings, **extra):
    argv = ["--home", str(settings.home), "down", "--timeout", "1"]
    for key, value in extra.items():
        argv += [f"--{key.replace('_', '-')}", value]
    return lp.parse_args(argv)


def _running_supervisor(settings, local):
    settings.run_dir.mkdir(parents=True, exist_ok=True)
    (settings.run_dir / lp.PIDFILE_NAME).write_text(json.dumps({"supervisor_pid": os.getpid(), "roles": {}}), encoding="utf-8")
    settings.env_file.parent.mkdir(parents=True, exist_ok=True)
    settings.env_file.write_text("".join(f"{k}={v}\n" for k, v in local.items()), encoding="utf-8")


def test_down_without_a_claim_is_refused_and_sends_no_stop(fleet, monkeypatch, capsys):
    settings, local, _ = fleet
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    _running_supervisor(settings, local)
    assert lp.cmd_down(_down_args(settings)) == 3
    assert "REFUSED" in capsys.readouterr().out
    assert not (settings.run_dir / "stop").exists()
    assert (settings.run_dir / lp.PIDFILE_NAME).exists()
    assert _events(settings)[0]["event"] == "down_refused"


@pytest.mark.parametrize("mode", ["claim", "override", "systemd"])
def test_down_proceeds_with_a_claim_an_override_or_under_systemd(fleet, monkeypatch, mode):
    settings, local, claims = fleet
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    _running_supervisor(settings, local)
    extra = {}
    if mode == "claim":
        _claim(claims)
    elif mode == "override":
        extra["unclaimed_ok"] = "host reboot"
    else:
        monkeypatch.setenv("INVOCATION_ID", "abc")
    sent = {}
    real_write = Path.write_text

    def spy(self, data, *a, **k):
        if self.name == "stop":
            sent["stop"] = True
            raise _Stop()
        return real_write(self, data, *a, **k)

    monkeypatch.setattr(Path, "write_text", spy)
    with pytest.raises(_Stop):
        lp.cmd_down(_down_args(settings, **extra))
    assert sent.get("stop")
    event = _events(settings)[0]
    assert event["event"] == "down"
    assert event["via"] == ("systemd" if mode == "systemd" else "cli")
    assert event["claimed"] is (mode == "claim")


class _Stop(Exception):
    """Raised at the stop-file write: the guard let `down` through. Stops the test from
    actually waiting on (or killing) the test process it recorded as the supervisor."""
