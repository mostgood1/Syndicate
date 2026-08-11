"""`#358` -- the failure tail must carry the CAUSE, not the last lines written.

MEASURED. `#357` shipped the right idea (the worker reads its own stderr and
prints it, since only the reader was ever on the wrong disk) and the first real
firing still could not answer the question:

    SOCCER_RUN_FAILED exit_code=1 run_stamp=20260811_213249
      tail=MAIN_THREAD_STACK label=json_after_write ... _dump_main_thread_stack
         | MAIN_RETURN ts=2026-08-11T21:32:59+00:00 pid=4232 ppid=4231
         | MAIN_THREAD_STACK label=main_return ...

Three shutdown frames, zero cause. `refresh_odds_sources` writes those on EVERY
run, success or failure, and they are the LAST thing in the file -- so a
six-line tail is guaranteed to show them and nothing else. The `SystemExit`
that actually killed the run (`no team history under <dir>`, from
`build_soccer_artifacts._load_team_ratings`) sat further up and was dropped.

The fix is not "add two more names to the blocklist". That is whack-a-mole: the
next heartbeat marker refills the window and pushes the cause out again, and it
is discovered during the NEXT incident. Causal lines are selected first,
wherever they sit in the file.

These tests are built from the real captured lines, so they fail if the
selection regresses to a plain tail.
"""

from __future__ import annotations

from scripts.run_refresh_worker import _is_stderr_noise, _stderr_failure_tail

# Verbatim shapes from the 2026-08-11 production stderr.
_CAUSE = "no team history under /opt/render/project/data/soccer_source/la_liga/team_history; run fetch_soccer_history_local.py --kind teams first"
_SHUTDOWN = [
    '[refresh_odds_sources] MAIN_THREAD_STACK label=json_after_write ts=2026-08-11T21:32:59+00:00 pid=4232 frame={"file": "...", "line": 421}',
    "MAIN_RETURN ts=2026-08-11T21:32:59+00:00 pid=4232 ppid=4231",
    "[refresh_odds_sources] MAIN_THREAD_STACK label=main_return ts=2026-08-11T21:32:59+00:00",
]
_HEARTBEAT = [
    'ALL_PROCESS_MEMORY {"accounted_rss_mb": 279.031}',
    'CONTAINER_MEMORY {"memory_anon_mb": 677.613}',
    'PROCESS_TREE_MEMORY {"child_count": 0}',
    'PROCESS_ENUM_DEBUG {"error_count": 0}',
    "[refresh_odds_sources] THREADS label=step_start data=[]",
    "[refresh_odds_sources] RUNTIME_SNAPSHOT label=step_end pid=4232",
    "[refresh_odds_sources] CHILD_PROCESSES label=step_end data=[]",
]


def _stderr(*, cause_at_depth: int) -> str:
    """A realistic file: cause buried under `cause_at_depth` noise lines, then shutdown."""
    return "\n".join(
        ["STEP_START name=soccer_la_liga_artifacts", _CAUSE]
        + _HEARTBEAT * cause_at_depth
        + _SHUTDOWN
    )


def test_the_measured_regression_does_not_recur():
    # The exact failure: shutdown frames last, cause far above them.
    tail = _stderr_failure_tail(_stderr(cause_at_depth=40))
    assert _CAUSE in tail, "the SystemExit naming the empty directory was dropped again"
    assert "team_history" in tail, "the tail must name the directory that was empty"


def test_a_plain_tail_would_have_failed_this():
    # Proves the fixture actually reproduces the problem -- otherwise the test
    # above passes for the wrong reason and guards nothing.
    text = _stderr(cause_at_depth=40)
    naive = [ln for ln in text.splitlines() if ln.strip()][-6:]
    assert _CAUSE not in naive, "the fixture no longer reproduces the naive-tail failure"


def test_shutdown_and_heartbeat_noise_is_excluded():
    tail = _stderr_failure_tail(_stderr(cause_at_depth=5))
    for noisy in _HEARTBEAT:
        assert noisy not in tail
    assert "MAIN_RETURN" not in tail, "MAIN_RETURN is the marker that filled the window"
    assert "MAIN_THREAD_STACK" not in tail


def test_noise_predicate_is_not_over_broad():
    # It must not eat a real error that merely mentions memory or a process.
    assert not _is_stderr_noise("MemoryError: cannot allocate 2GB for the sim")
    assert not _is_stderr_noise("SystemExit: no match history under /data/eredivisie/history")
    assert _is_stderr_noise('ALL_PROCESS_MEMORY {"accounted_rss_mb": 1.0}')
    assert _is_stderr_noise("[refresh_odds_sources] THREADS label=x data=[]")


def test_output_is_in_file_order():
    text = "\n".join(["Traceback (most recent call last):", "  File x, line 1", "SystemExit: boom"] + _SHUTDOWN)
    tail = _stderr_failure_tail(text)
    assert tail.index("Traceback") < tail.index("SystemExit"), "a trace printed bottom-up is unreadable"


def test_empty_and_all_noise_do_not_crash():
    assert _stderr_failure_tail("") == ""
    assert _stderr_failure_tail("\n".join(_HEARTBEAT)) == ""
    # A file with no causal marker still returns its tail rather than nothing --
    # "no recognised error" must not render as "no output".
    plain = _stderr_failure_tail("\n".join(["step one", "step two", "step three"]))
    assert "step three" in plain
