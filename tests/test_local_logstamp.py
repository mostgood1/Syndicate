"""scripts/local_logstamp: the fleet's per-line UTC stamp, applied inside the role."""

from __future__ import annotations

import datetime as dt
import io
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAMP_DIR = REPO / "scripts" / "local_logstamp"
sys.path.insert(0, str(REPO / "scripts"))

from local_logstamp.sitecustomize import StampedStream  # noqa: E402

import render_logs  # noqa: E402

FIXED = dt.datetime(2026, 10, 2, 14, 36, 49, 123456, tzinfo=dt.timezone.utc)


def _stream():
    sink = io.StringIO()
    return sink, StampedStream(sink, clock=lambda: FIXED)


def test_stamps_each_line_once_even_across_partial_writes() -> None:
    sink, out = _stream()
    out.write("a\nb")
    out.write("c\n")
    out.write("")
    out.write("d\n\n")
    stamp = "2026-10-02T14:36:49.123Z "
    assert sink.getvalue() == f"{stamp}a\n{stamp}bc\n{stamp}d\n{stamp}\n"


def test_stamp_is_the_prefix_render_logs_reads_as_exact(tmp_path: Path) -> None:
    sink, out = _stream()
    print("ORDER_PATH venue=kalshi status=ok", file=out)
    (tmp_path / "live-odds-worker.log").write_text(sink.getvalue(), encoding="utf-8")
    lines, info = render_logs.fetch_local_window(
        service="live-odds-worker", text="ORDER_PATH", start="2026-10-02T00:00:00Z", log_dir=tmp_path)
    assert lines == [("2026-10-02T14:36:49.123Z", "ORDER_PATH venue=kalshi status=ok")]
    assert info["exact"] == 1


def _run_child(env_extra: dict[str, str]) -> str:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(STAMP_DIR), env.get("PYTHONPATH", "")])
    env.update(env_extra)
    code = "import sys, logging; print('hello'); logging.basicConfig(); logging.warning('warned')"
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    return proc.stdout + proc.stderr


def test_child_python_is_stamped_via_pythonpath() -> None:
    output = _run_child({})
    assert render_logs._PREFIX.match(output.splitlines()[0])
    assert all(render_logs._PREFIX.match(line) for line in output.splitlines())


def test_off_switch_leaves_output_raw() -> None:
    output = _run_child({"SYNDICATE_LOCAL_LOG_TIMESTAMPS": "0"})
    assert "hello" in output.splitlines()
    assert not any(render_logs._PREFIX.match(line) for line in output.splitlines())


def test_supervisor_role_env_carries_the_stamp_dir_unless_disabled(tmp_path: Path) -> None:
    from scripts import local_production as lp

    settings = lp.Settings(home=tmp_path / "home", port=12345)
    blueprint = lp.load_blueprint()
    for role in lp.ROLE_ORDER:
        env, _ = lp.derive_role_env(role, blueprint, {}, settings, base_env={})
        assert env["PYTHONPATH"].split(os.pathsep)[:2] == [str(STAMP_DIR), str(REPO)]
    env, _ = lp.derive_role_env("refresh-worker", blueprint, {}, settings,
                                base_env={"SYNDICATE_LOCAL_LOG_TIMESTAMPS": "0"})
    assert str(STAMP_DIR) not in env["PYTHONPATH"].split(os.pathsep)
