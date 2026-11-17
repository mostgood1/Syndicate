#!/usr/bin/env python3
"""Run the session-start hook's python checks CONCURRENTLY and hand back each one's result.

Lane `session-start-hook-runtime`, 2026-11-16. `.claude/hooks/session-start.sh` used to run its nine
python calls one after another. Measured on the PRIMARY tree that day (5 untraced runs): the hook
took 16.1-25.1 s, median 19.3, against the 20 s SessionStart timeout in `.claude/settings.json`,
so 3 of 5 runs went over, and a killed hook delivers NO digest at all. The serial python calls
were ~8 s of that (the five coherence checkers alone 5.5-14 s; `check_lane_invariants.py` 2.7-6.8 s,
CPU-bound in `lane_claims.sections_are_disjoint`). Run side by side, they cost the SLOWEST check
instead of the sum, and every check still runs: nothing is dropped, sampled or cached.

Usage, from the hook (cwd = the repo root):

    python scripts/session_start_jobs.py [--deadline S] 'KEY|CAP|scripts/x.py [arg ...]' ...

Each job runs as `<this python> scripts/x.py [arg ...]`, stdin and stderr closed, all of them
started at once. When all have ended (or the deadline passes) this prints, in argument order:

    KEY <TAB> STATUS <TAB> OUTPUT
    ...
    @@END <TAB> <number of jobs>

STATUS is the child's exit code; or `missing` (the script file is absent: the hook skips the job,
exactly as its old `[ -f scripts/x.py ]` guard did); `timeout` (still running at the deadline, so
killed; the hook says so in DIGEST NOTES rather than reading it as a pass); or `error` (it could not
be started).

OUTPUT is the child's stdout made byte-identical to what the hook's old `X=$(python ... | head -c CAP)`
assigned: cut to CAP bytes (CAP 0 = no cap), NULs dropped, then trailing "\\n" and "\\r\\n" stripped
the way MSYS bash's command substitution strips them (measured in Git Bash 5.2.37: it strips both,
and keeps a lone trailing "\\r"). It is then escaped (backslash, newline, CR, tab) to fit on one
line; the hook decodes it with `printf -v VAR '%b'`, which turns exactly those four back. CAP -1
discards stdout: the coherence checkers' exit code is all the hook ever read from them.

The `@@END` line is the contract. If it is missing, this runner died part-way, and the hook reports
that rather than treating the absent results as clean ones. Never prints a traceback; any failure
here exits 1 with no `@@END`.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

# Bounded so a hung check cannot carry the hook past its 20 s SessionStart timeout, which would cost
# the WHOLE digest. The slowest check took 6.8 s in the worst of the 2026-11-16 baseline runs.
DEFAULT_DEADLINE_S = 13.0


def parse_job(spec: str) -> tuple[str, int, list[str]]:
    """'KEY|CAP|scripts/x.py arg ...' -> (key, cap, argv). Raises ValueError on a malformed spec."""
    key, cap, cmd = spec.split("|", 2)
    argv = cmd.split()
    if not key or "\t" in key or "\n" in key or not argv:
        raise ValueError("bad job spec: %r" % spec)
    return key, int(cap), argv


def as_command_substitution(out: bytes, cap: int) -> bytes:
    """What `$(... | head -c CAP)` leaves in the variable under MSYS bash."""
    if cap > 0:
        out = out[:cap]
    out = out.replace(b"\0", b"")
    while out.endswith(b"\n"):
        out = out[:-1]
        if out.endswith(b"\r"):
            out = out[:-1]
    return out


def escape(out: bytes) -> bytes:
    """One line, decodable by bash `printf '%b'`: every backslash doubled, so no other escape exists."""
    return (out.replace(b"\\", b"\\\\").replace(b"\n", b"\\n")
            .replace(b"\r", b"\\r").replace(b"\t", b"\\t"))


def run(jobs, deadline_s: float = DEFAULT_DEADLINE_S, python: str = sys.executable):
    """Start every job at once, wait for all within the deadline. -> [(key, status, output_bytes)]."""
    started = []
    for key, cap, argv in jobs:
        if not os.path.isfile(argv[0]):
            started.append((key, cap, None, "missing"))
            continue
        try:
            proc = subprocess.Popen(
                [python] + argv, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL if cap < 0 else subprocess.PIPE)
        except (OSError, ValueError):
            started.append((key, cap, None, "error"))
            continue
        started.append((key, cap, proc, None))

    # One reader thread per piped child, so a chatty one can never block on a full pipe while
    # this waits on another.
    captured: dict[int, bytes] = {}

    def drain(idx, proc):
        try:
            captured[idx] = proc.stdout.read()
        except (OSError, ValueError):
            captured[idx] = b""

    readers = []
    for idx, (_key, _cap, proc, _status) in enumerate(started):
        if proc is not None and proc.stdout is not None:
            t = threading.Thread(target=drain, args=(idx, proc), daemon=True)
            t.start()
            readers.append((idx, t))

    end = time.monotonic() + deadline_s
    results = []
    for idx, (key, cap, proc, status) in enumerate(started):
        if proc is None:
            results.append((key, status, b""))
            continue
        try:
            proc.wait(timeout=max(0.0, end - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            results.append((key, "timeout", b""))
            continue
        out = b""
        for ridx, t in readers:
            if ridx == idx:
                t.join(timeout=max(0.0, end - time.monotonic()) + 1.0)
                out = captured.get(idx, b"")
        results.append((key, str(proc.returncode), as_command_substitution(out, cap)))
    return results


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    deadline = DEFAULT_DEADLINE_S
    if len(args) >= 2 and args[0] == "--deadline":
        deadline = float(args[1])
        args = args[2:]
    jobs = [parse_job(spec) for spec in args]
    results = run(jobs, deadline)
    out = sys.stdout.buffer
    for key, status, text in results:
        out.write(key.encode("utf-8") + b"\t" + status.encode("ascii") + b"\t" + escape(text) + b"\n")
    out.write(b"@@END\t%d\n" % len(results))
    out.flush()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001  -- the hook reads a missing @@END as "did not run"
        sys.exit(1)
