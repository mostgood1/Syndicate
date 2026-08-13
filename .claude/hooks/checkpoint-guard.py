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
import json, os, subprocess, sys

FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
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


def _session_files(transcript_path, root):
    """Repo-relative paths this session wrote, from its own transcript."""
    touched = set()
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
                    if block.get("name") not in FILE_TOOLS:
                        continue
                    fp = (block.get("input") or {}).get("file_path")
                    if not fp:
                        continue
                    rel = _norm(root, fp)
                    if rel:
                        touched.add(rel)
    except Exception:
        return None
    return touched


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

    touched = _session_files(transcript, root)
    if not touched:
        return 0

    dirty = _dirty(root)
    if dirty is None:
        return 0

    mine = sorted(touched & dirty)
    if not mine:
        return 0  # everything this session wrote is committed

    marker = os.path.join(root, ".syndicate", ".last-checkpoint")
    mark_mtime = 0.0
    if os.path.exists(marker):
        try:
            mark_mtime = os.path.getmtime(marker)
        except Exception:
            mark_mtime = 0.0

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
    if not mark_mtime:
        sys.stderr.write("No .syndicate/.last-checkpoint exists - this session has never checkpointed.\n")
    elif newest_file:
        sys.stderr.write("Newest change (%s) postdates the checkpoint marker.\n" % newest_file)
    sys.stderr.write("Run /checkpoint before ending, or this session's findings do not survive it.\n")
    return 1


sys.exit(main())
