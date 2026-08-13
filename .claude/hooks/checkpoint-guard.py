#!/usr/bin/env python3
"""Stop hook - warns when THIS session's work is not checkpointed.

Replaces checkpoint-guard.sh, which was structurally incapable of passing.
Measured 2026-08-13: 28 Stop-hook records across 5 sessions, exitCode 1 on all
28, zero exit 0. Two independent reasons, both fixed here:

  1. It required `.syndicate/.last-checkpoint` to exist, and nothing created
     that file until `/checkpoint` step 7 was added. `[ -f "$MARKER" ]` was
     always false, so the pass branch was unreachable. A guard whose success
     path cannot execute is not a guard.

  2. Its denominator was the WHOLE worktree. On this repo background artifact
     writes and parallel sessions dirty files continuously - 67 files at the
     time of measurement, of which exactly one belonged to the session being
     warned. The newest of those 67 was 80s after a checkpoint written
     seconds earlier, so `MARK >= NEWEST` was false even immediately after a
     correct checkpoint. Fixing (1) alone left it warning 100% of the time.

The denominator is now the files THIS session actually edited, read from its
own transcript. A warning that fires every time carries no information, which
is how the original ended up being scrolled past.

Known gap, stated rather than papered over: only the file tools (Edit, Write,
MultiEdit, NotebookEdit) are counted. A session that writes exclusively
through Bash redirection reads as clean here, the same blind spot lane-guard
has. Closing it means parsing shell commands, which fails open far more often
than it catches anything.

Non-blocking by design: exit 1, never 2. HOOKS.md is explicit that this warns
and does not trap a session, and exit 2 on Stop would prevent stopping.
Fails open: any error exits 0 and the session proceeds.
"""
import json, os, re, subprocess, sys

FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
SHELL_TOOLS = ("Bash", "PowerShell")
LOG_RE = re.compile(r"^\.syndicate/log/[^/]+\.md$")
LOG_HINT_RE = re.compile(r"\.syndicate/log/[^\s'\"]+\.md")
MAX_LISTED = 6


def _norm(root, path):
    """Repo-relative, forward-slashed, or None if outside the repo."""
    try:
        rel = os.path.relpath(os.path.abspath(path), root)
    except Exception:
        return None
    rel = rel.replace("\\", "/")
    if rel.startswith("../"):
        return None
    return rel


def _scan_transcript(transcript_path, root):
    """(paths this session wrote, whether it appended to a .syndicate/log entry).

    The log flag is the second checkpoint witness. It is deliberately scoped to
    THIS session: `.syndicate/log/<date>.md` is appended by every session, so
    treating any recent write to it as proof would let one session's checkpoint
    silence another's warning. In a repo with five sessions live that turns the
    guard from always-warning into always-passing, which is the same defect
    facing the other way.

    Bash/PowerShell commands are inspected for the log path only. That is not
    general shell parsing - it is one substring test against one known
    filename, because `/checkpoint` step 2 is normally a `cat >>` heredoc and
    would otherwise be invisible here (this guard's own author checkpointed
    that way).
    """
    touched = set()
    wrote_log = False
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or '"tool_use"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                content = (entry.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    name = block.get("name")
                    inp = block.get("input") or {}
                    if name in FILE_TOOLS:
                        fp = inp.get("file_path")
                        if not fp:
                            continue
                        rel = _norm(root, fp)
                        if rel:
                            touched.add(rel)
                            if LOG_RE.match(rel):
                                wrote_log = True
                    elif name in SHELL_TOOLS:
                        cmd = inp.get("command") or ""
                        if isinstance(cmd, str) and LOG_HINT_RE.search(cmd.replace("\\", "/")):
                            wrote_log = True
    except Exception:
        return None, False
    return touched, wrote_log


def _dirty(root):
    """Repo-relative paths git reports as changed."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    paths = set()
    for line in out.stdout.splitlines():
        if len(line) < 4:
            continue
        p = line[3:].strip().strip('"')
        # Renames read as "old -> new"; the new path is what is on disk.
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        paths.add(p.replace("\\", "/"))
    return paths


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    root = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    root = os.path.abspath(root)
    if not os.path.isdir(os.path.join(root, ".syndicate")):
        return 0

    transcript = payload.get("transcript_path")
    if not transcript or not os.path.exists(transcript):
        return 0

    touched, wrote_log = _scan_transcript(transcript, root)
    if not touched:
        return 0

    dirty = _dirty(root)
    if dirty is None:
        return 0

    mine = sorted(touched & dirty)
    if not mine:
        return 0  # everything this session wrote is committed

    # Baseline = the NEWER of two independent witnesses. The marker is the
    # explicit signal; a log append by this session is the fallback, so that
    # forgetting `/checkpoint` step 7 does not report a session that did
    # checkpoint as having lost its work. Both absent is reported as "no
    # baseline" rather than as a forgotten touch, because those are different
    # facts and only one of them is the session's fault.
    baseline = 0.0
    witness = None

    marker = os.path.join(root, ".syndicate", ".last-checkpoint")
    if os.path.exists(marker):
        try:
            baseline = os.path.getmtime(marker)
            witness = "marker"
        except Exception:
            baseline = 0.0

    if wrote_log:
        log_dir = os.path.join(root, ".syndicate", "log")
        try:
            for name in os.listdir(log_dir):
                if not name.endswith(".md"):
                    continue
                m = os.path.getmtime(os.path.join(log_dir, name))
                if m > baseline:
                    baseline, witness = m, "log append"
        except Exception:
            pass
    mark_mtime = baseline

    newest = 0.0
    newest_file = None
    for rel in mine:
        try:
            m = os.path.getmtime(os.path.join(root, rel))
        except Exception:
            continue
        if m > newest:
            newest, newest_file = m, rel

    if mark_mtime and newest and mark_mtime >= newest:
        return 0

    shown = mine[:MAX_LISTED]
    more = len(mine) - len(shown)
    sys.stderr.write(
        "UNCHECKPOINTED WORK: %d file(s) this session changed are not committed "
        "and postdate the last /checkpoint.\n" % len(mine)
    )
    for rel in shown:
        sys.stderr.write("  %s\n" % rel)
    if more > 0:
        sys.stderr.write("  ... and %d more\n" % more)
    if not baseline:
        sys.stderr.write(
            "No baseline: no .syndicate/.last-checkpoint, and this session has not "
            "appended to .syndicate/log/. It has never checkpointed.\n"
        )
    elif newest_file:
        sys.stderr.write(
            "Newest change (%s) postdates the last checkpoint (witness: %s).\n"
            % (newest_file, witness)
        )
    sys.stderr.write("Run /checkpoint before ending, or this session's findings do not survive it.\n")
    return 1


sys.exit(main())
