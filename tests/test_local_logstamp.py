"""scripts/local_logstamp: the fleet's per-line UTC stamp, applied inside the role."""

from __future__ import annotations

import datetime as dt
import io
import json
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


def _child_env(env_extra: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(STAMP_DIR), env.get("PYTHONPATH", "")])
    env.update(env_extra)
    return env


CHILD_CODE = "import sys, logging; print('hello'); logging.basicConfig(); logging.warning('warned')"


def _run_child_to_file(env_extra: dict[str, str], tmp_path: Path) -> str:
    """A role's shape: stdout/stderr go to a log FILE the parent opened."""
    log = tmp_path / "role.log"
    with log.open("w", encoding="utf-8") as handle:
        subprocess.run([sys.executable, "-c", CHILD_CODE], env=_child_env(env_extra), stdout=handle,
                       stderr=subprocess.STDOUT, timeout=60)
    return log.read_text(encoding="utf-8")


def test_child_python_writing_to_a_file_is_stamped_via_pythonpath(tmp_path: Path) -> None:
    output = _run_child_to_file({}, tmp_path)
    assert output.splitlines() and all(render_logs._PREFIX.match(line) for line in output.splitlines())


def test_off_switch_leaves_output_raw(tmp_path: Path) -> None:
    output = _run_child_to_file({"SYNDICATE_LOCAL_LOG_TIMESTAMPS": "0"}, tmp_path)
    assert "hello" in output.splitlines()
    assert not any(render_logs._PREFIX.match(line) for line in output.splitlines())


def test_a_child_whose_stdout_a_parent_captures_is_not_stamped() -> None:
    """2026-10-02: live_refresh_loop's MLB live probe logged
    bad_json:'2026-10-02T21:32:52.433Z {"live_game_pks": []}' 79 times. A pipe is
    DATA for the parent, so the stamp must not touch it."""
    code = "import json; print(json.dumps({'live_game_pks': [1, 2]}))"
    proc = subprocess.run([sys.executable, "-c", code], env=_child_env({}), capture_output=True, text=True, timeout=60)
    assert json.loads(proc.stdout) == {"live_game_pks": [1, 2]}


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
