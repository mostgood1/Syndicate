"""The step runner in `scripts/run_ci_suite.py`: its env scrub and its timeout.

WHY IT EXISTS. The `ci-suite` Render cron (`crn-dafg4h0u01pc73aavs6g`,
`0 8 * * *`) ran for 52 minutes on 2026-09-08 and reported one line:

      FAIL  pytest vs baseline    rc=124  3001.0s
      TIMEOUT after 3000s

That is the whole record. `run()` captures output rather than streaming it, so
the step is silent while it runs, and the timeout branch threw away
`TimeoutExpired.stdout` -- so there was no way to tell a suite that was 95%
done from one that hung on the third test. Both of those are now fixed here,
and they are separate bugs from the cap being too low.

The same run's archive step reported `failures=18, errors=21` for a commit that
is green everywhere else. That was the HOST: `RENDER` is injected on cron jobs
too, and the suite was measuring it. `_step_env()` scrubs it, which is the
third thing pinned below.

THREE THINGS THIS PINS THAT ARE EASY TO REGRESS:

1. **The partial output must survive the kill.** CPython builds
   `TimeoutExpired` with the RAW buffered bytes (`Popen._check_timeout` passes
   `output=b''.join(stdout_seq)`), bypassing the decoder that `text=True`
   installed -- and then `subprocess.run` OVERWRITES both attributes with a
   decoded `communicate()` *on Windows only*. So the attribute is `str` on a
   dev box and `bytes` on the Render cron. A fix tested only on the host where
   the step already passes would have shipped an empty print to the host where
   it times out.

2. **A timeout must not be summarised as a test failure.** `learnings.md`
   2026-08-20 makes reading a KILLED pytest run as a result FORBIDDEN: a
   12-failure report was invented from truncated output and used to argue for
   rolling back three verified deploys. rc=124 means "it reached here" and
   nothing else, so it gets its own verdict word.

3. **The scrub must reach the CHILD, not just the dict.** A correct
   `_step_env()` that `run()` forgets to pass is the inert-fix shape and looks
   identical from the outside, so one test spawns a real subprocess and reads
   `os.environ` inside it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def module():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location(
        "run_ci_suite", REPO / "scripts" / "run_ci_suite.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_as_text_handles_the_linux_bytes_path(module):
    """The branch this host cannot reach by running a subprocess.

    On Linux `TimeoutExpired.stdout` is bytes even under `text=True`. Tested
    directly because the end-to-end test below exercises the Windows `str`
    path when it runs on Windows, and the cron is Linux.
    """
    assert module._as_text(b"collected 40 items\n") == "collected 40 items\n"
    assert module._as_text("already text") == "already text"
    assert module._as_text(None) == ""
    # Undecodable bytes must degrade, not raise -- a killed run can be cut
    # mid-codepoint, and losing the whole tail to a UnicodeDecodeError would
    # reintroduce exactly the blindness this fixes.
    assert module._as_text(b"ok \xff\xfe") == "ok ��"


def test_a_killed_run_keeps_the_output_it_produced(module, capsys):
    """End-to-end against a REAL process that prints, then hangs."""
    prog = ("import time\n"
            "for i in range(5):\n"
            "    print(f'collected chunk {i}', flush=True)\n"
            "time.sleep(60)\n")
    result = module.run("hung step", ["-c", prog], timeout=3)

    assert result["rc"] == 124
    assert result["timed_out"] is True
    assert any("collected chunk 4" in line for line in result["tail"])

    printed = capsys.readouterr().out
    # The label is load-bearing, not decoration: it is what stops the lines
    # underneath being read as a pass/fail list.
    assert "PARTIAL OUTPUT FROM A KILLED RUN" in printed


def test_a_silent_hang_says_so_rather_than_printing_nothing(module, capsys):
    result = module.run("silent hang", ["-c", "import time; time.sleep(60)"], timeout=3)

    assert result["rc"] == 124 and result["timed_out"] is True
    assert result["tail"] == []
    assert "no output at all" in capsys.readouterr().out


def test_a_normal_failure_is_not_marked_as_a_timeout(module):
    """The discrimination that makes `timed_out` worth carrying at all."""
    result = module.run("ordinary failure", ["-c", "raise SystemExit(3)"], timeout=60)

    assert result["rc"] == 3
    assert result["timed_out"] is False


def test_a_pass_is_still_a_pass(module):
    result = module.run("ordinary pass", ["-c", "print('fine')"], timeout=60)

    assert result["rc"] == 0
    assert result["timed_out"] is False
    assert result["tail"] == ["fine"]


def test_the_pytest_cap_is_a_knob_with_a_raised_default(module):
    """The cap that a 3001s run hit, and the reason it must be overridable.

    Pinned as `> 3000` rather than `== 7200` so that replacing the guess with
    a measured number does not fail this test -- lowering it back under the
    value that already timed out should.
    """
    assert module.PYTEST_TIMEOUT_DEFAULT > 3000
    assert module.FAST_STEP_TIMEOUT == 900


def test_render_injected_vars_are_scrubbed_from_steps(module, monkeypatch):
    """The fix for the 18-failure/21-error cron run, at the choke point.

    Every step goes through `_step_env()`, so this is the one place that has to
    hold rather than nineteen call sites.
    """
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RENDER_SERVICE_NAME", "ci-suite")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "deadbeef")

    env = module._step_env()

    assert "RENDER" not in env
    assert "RENDER_SERVICE_NAME" not in env
    assert "RENDER_GIT_COMMIT" not in env


def test_the_user_secret_is_not_scrubbed(module, monkeypatch):
    """`RENDER_API_KEY` is user-set, not Render-injected.

    A `RENDER_*` wildcard would have taken it, which is why the list is an
    explicit allowlist of injected names.
    """
    monkeypatch.setenv("RENDER_API_KEY", "rnd_secret")
    monkeypatch.setenv("RENDER", "true")

    env = module._step_env()

    assert env["RENDER_API_KEY"] == "rnd_secret"
    assert "RENDER" not in env
    assert "RENDER_API_KEY" not in module.RENDER_INJECTED_ENV


def test_the_rest_of_the_environment_survives(module, monkeypatch):
    """Scrubbing must be surgical -- the steps still need PATH, tokens, etc."""
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", "/opt/render/project/src/data")

    env = module._step_env()

    assert env["SYNDICATE_DATA_ROOT"] == "/opt/render/project/src/data"
    assert "PATH" in env


def test_a_step_child_actually_sees_the_scrub(module, monkeypatch):
    """End-to-end: the child process, not just the dict.

    `run()` had to be wired to pass `env=`; a correct `_step_env()` that nothing
    calls is the inert-fix shape, and it would look identical from the dict.
    """
    monkeypatch.setenv("RENDER", "true")

    result = module.run(
        "env probe",
        ["-c", "import os; print('RENDER=' + repr(os.environ.get('RENDER')))"],
        timeout=60,
    )

    assert result["rc"] == 0
    assert result["tail"] == ["RENDER=None"]
