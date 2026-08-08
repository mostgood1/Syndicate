"""Pick the DIAGNOSTIC part of a refresh child's output, not the last N bytes.

Every failure window in the odds-refresh pipeline was a raw ``text[-N:]`` tail,
and every one of them was measured empty of signal on 2026-08-08.

The refresh child (``scripts/refresh_odds_sources.py``) writes a large atexit
diagnostic dump to stderr on the way out -- ``PROCESS_TREE_MEMORY``,
``CONTAINER_MEMORY``, ``RUNTIME_SNAPSHOT``, ``THREADS``, ``MAIN_THREAD_STACK``.
Measured on refresh-worker at 2026-08-08T21:40:55Z, a soccer run that exited
``return_code=1`` produced ``STDERR_LENGTH length=2130057`` whose final lines
were entirely that dump, and a SINGLE ``PROCESS_TREE_MEMORY`` line was over
3,000 characters on its own. So:

    _FAILED_STEP_STDERR_TAIL_CHARS = 1600   (run manifest, refresh_odds_sources)
    stderr_tail[-1600:]                     (failure summary, run_refresh_odds_job)
    stderr_text[-4000:]                     (stdout echo, run_refresh_odds_job)

could not contain a traceback even in principle -- the 1600-char windows could
not hold one line of the dump, let alone reach past it. That is why seven days
of refresh-worker logs carried zero ``Traceback`` lines while steps were
failing: not a missing print, and not the DEVNULL the comments blamed. The
signal was written, captured, echoed, and then windowed out.

The ratio, measured by re-running the real child locally and profiling its
actual 503,266-char stderr by first token:

    ALL_PROCESS_MEMORY      4 lines    493,457 chars    98.05%
    MAIN_THREAD_STACK       4 lines      2,524 chars
    PROCESS_ENUM_DEBUG      4 lines      1,556 chars
    STEP_START/STEP_END     2 lines      1,069 chars     0.21%   <- the signal

Four lines are 98% of the stream. Any tail measured in kilobytes lands inside
them; that is a property of the data, not of the budget, which is why raising
the budget was never the fix.

Two rules, in order:

1. Drop the known high-volume diagnostic lines. They are re-derivable from the
   memory endpoints and they are what crowds the window.
2. If a traceback survives, anchor the window at the LAST one, so the exception
   type and message -- which come at the END of a traceback -- are never the
   part that gets cut.

Deliberately a filter, not a parser: an unrecognised line is KEPT. A tail that
silently dropped an unfamiliar error would be a worse failure than the one this
replaces, so the drop list names only lines this repo emits itself.
"""

from __future__ import annotations

# First token of the lines that are pure volume. Matched after stripping the
# optional "[refresh_odds_sources] " emitter prefix, so both the bare and the
# prefixed spelling are covered by one entry.
_NOISE_TOKENS: frozenset[str] = frozenset(
    {
        # Memory/runtime sampling. High frequency and very long lines -- the
        # PROCESS_TREE_MEMORY line measured above embeds every process's full
        # cmdline, so one line can exceed the whole tail budget.
        "PROCESS_TREE_MEMORY",
        "CONTAINER_MEMORY",
        "ALL_PROCESS_MEMORY",
        "LIVE_ODDS_WORKER_MEMORY",
        "RUNTIME_SNAPSHOT",
        "MAIN_THREAD_STACK",
        "PROCESS_ENUM_DEBUG",
        "CHILD_PROCESSES",
        "THREADS",
        # Lifecycle bookkeeping. Useful in sequence, worthless in a tail: they
        # say a step happened, never why it failed.
        "CHILD_PROCESS_EXIT",
        "CHILD_PROCESS_STARTED",
        "CHILD_JSON_WRITE_BEGIN",
        "CHILD_JSON_WRITE_END",
        "CHILD_JSON_RETURN",
        "PRE_STEP_LOG",
        "POST_STEP_LOG",
        "WRAPPER_WAIT_BEGIN",
        "WRAPPER_WAIT_POLL",
        "SAFE_WRITE_BEGIN",
        "SAFE_WRITE_SUCCESS",
    }
)

_EMITTER_PREFIX = "[refresh_odds_sources] "
_TRACEBACK_MARKER = "Traceback (most recent call last):"


def _is_noise(line: str) -> bool:
    candidate = line.strip()
    if not candidate:
        return False
    if candidate.startswith(_EMITTER_PREFIX):
        candidate = candidate[len(_EMITTER_PREFIX) :].lstrip()
    token = candidate.split(" ", 1)[0].split("=", 1)[0]
    return token in _NOISE_TOKENS


def diagnostic_tail(text: str | None, *, limit: int) -> str:
    """The last ``limit`` characters worth of DIAGNOSTIC output from ``text``.

    Never raises and never returns more than ``limit`` characters: both
    call sites persist the result (one through the shared keyvalue store, which
    was at 194MB of a 256MB ceiling when this was written), so the budget is a
    hard bound, not a hint.
    """
    if not isinstance(text, str) or not text.strip() or limit <= 0:
        return ""
    try:
        kept = [line for line in text.splitlines() if not _is_noise(line)]
        if not kept:
            # Everything was noise. The raw tail is still better than nothing --
            # it at least shows the run got far enough to dump state.
            return text[-limit:]
        # Anchor on the LAST traceback. A traceback's most useful line (the
        # exception type and message) is its last, so a plain tail truncates
        # from the wrong end whenever the traceback is longer than the budget.
        for index in range(len(kept) - 1, -1, -1):
            if _TRACEBACK_MARKER in kept[index]:
                anchored = "\n".join(kept[index:])
                # Still bounded: a very long traceback keeps its tail, which is
                # the exception itself.
                return anchored[-limit:]
        return "\n".join(kept)[-limit:]
    except Exception:
        # This runs on the failure path of a failure handler. It must never be
        # the reason a diagnostic is lost.
        return text[-limit:]
