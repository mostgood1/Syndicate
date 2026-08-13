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

WITNESS (2026-08-13). The denominator above is this session's; the witness now
is too. `.syndicate/.last-checkpoint` is repo-global and untracked, so on a
tree with concurrent sessions it was answering the wrong question:

  - FALSE PASS, the dangerous direction. Session A checkpoints at 15:10 and
    touches the shared marker. Session B edited code at 15:05 and stops
    without checkpointing. B's newest work predates the marker, so B passed
    silently - the exact loss this hook exists to prevent, caused by another
    session doing the right thing.
  - FALSE WARN: a session that wrote the ledger but forgot `/checkpoint`
    step 7 was warned anyway, and its own ledger writes were counted as
    unpersisted work.

The witness is now the newest of THIS session's signals, read from its own
transcript: the `/checkpoint` invocation timestamp, and any `.syndicate/**`
write by a file tool. Both are needed - ledger appends written with `cat >>`
leave no file-tool record, and a `/checkpoint` that ran leaves a command
record even then. The global marker is consulted ONLY when the session has no
signal of its own, so it can no longer be satisfied by a different session.

`.syndicate/**` no longer counts as work. It is the persistence, not the thing
at risk, and counting it warned about the very writes that discharge the
obligation.

Non-blocking by design: exit 1, never 2. HOOKS.md is explicit that this warns
and does not trap a session, and exit 2 on Stop would prevent stopping.
Fails open: any error exits 0 and the session proceeds.
"""
import datetime, json, os, re, subprocess, sys

FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
SHELL_TOOLS = ("Bash", "PowerShell")
LEDGER_PREFIX = ".syndicate/"
LEDGER_HINT_RE = re.compile(
    r"\.syndicate/(log/[^\s'\"]+\.md|state\.md|lanes\.md|learnings\.md|\.last-checkpoint)"
)
CHECKPOINT_CMD_RE = re.compile(r"<command-name>/?checkpoint</command-name>")
MAX_LISTED = 6


def _epoch(stamp):
    """ISO-8601 transcript timestamp -> epoch seconds, or 0.0."""
    if not isinstance(stamp, str):
        return 0.0
    try:
        return datetime.datetime.fromisoformat(
            stamp.replace("Z", "+00:00")
        ).timestamp()
    except Exception:
        return 0.0


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
    """(paths this session wrote, epoch of its most recent checkpoint signal).

    The witness is deliberately scoped to THIS session and taken from the
    TRANSCRIPT's own timestamps, never from a file's mtime. Every ledger file
    is written by every session, so any mtime read off disk answers "did
    somebody checkpoint", not "did I". With five sessions live that turns the
    guard from always-warning into always-passing - the same defect facing the
    other way, and the more dangerous direction, because the warning it
    suppresses is the one that had something to say.

    Three signals count, all from this session:
      - a `/checkpoint` invocation (a user entry carrying <command-name>);
      - a file-tool write to `.syndicate/**`;
      - a shell command naming a ledger file, because `/checkpoint` step 2 is
        normally a `cat >>` heredoc and leaves no file-tool record (this
        guard's own author checkpointed that way). That is one substring test
        against known filenames, not general shell parsing.
    """
    touched = set()
    checkpoint_ts = 0.0
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                has_tool = '"tool_use"' in line
                has_cmd = "<command-name>" in line
                if not has_tool and not has_cmd:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                stamp = _epoch(entry.get("timestamp"))
                content = (entry.get("message") or {}).get("content")

                if isinstance(content, str):
                    if CHECKPOINT_CMD_RE.search(content) and stamp > checkpoint_ts:
                        checkpoint_ts = stamp
                    continue
                if not isinstance(content, list):
                    continue

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        text = block.get("text") or ""
                        if CHECKPOINT_CMD_RE.search(text) and stamp > checkpoint_ts:
                            checkpoint_ts = stamp
                        continue
                    if block.get("type") != "tool_use":
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
                            if rel.startswith(LEDGER_PREFIX) and stamp > checkpoint_ts:
                                checkpoint_ts = stamp
                    elif name in SHELL_TOOLS:
                        cmd = inp.get("command") or ""
                        if (
                            isinstance(cmd, str)
                            and LEDGER_HINT_RE.search(cmd.replace("\\", "/"))
                            and stamp > checkpoint_ts
                        ):
                            checkpoint_ts = stamp
    except Exception:
        return None, 0.0
    return touched, checkpoint_ts


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

    touched, checkpoint_ts = _scan_transcript(transcript, root)
    if not touched:
        return 0

    dirty = _dirty(root)
    if dirty is None:
        return 0

    # `.syndicate/**` is the persistence, not the thing at risk. Counting it as
    # work warned about the very writes that discharge the obligation.
    mine = sorted(
        p for p in (touched & dirty) if not p.startswith(LEDGER_PREFIX)
    )
    if not mine:
        return 0  # nothing at risk: committed, or ledger-only

    # Baseline: this session's own checkpoint, from its own transcript.
    #
    # `.syndicate/.last-checkpoint`'s MTIME is deliberately never read. It is
    # repo-global, so a session that has never checkpointed would be silenced
    # by any other session touching it - and "never checkpointed with work
    # outstanding" is the exact case this hook exists to catch. Step 7 still
    # counts, but as a SIGNAL rather than a timestamp: the Bash `touch` naming
    # it is matched in this session's transcript like any other ledger write.
    # No session signal means no baseline, which warns. That is the safe
    # direction.
    baseline = checkpoint_ts
    witness = "this session's checkpoint" if baseline else None

    newest = 0.0
    newest_file = None
    for rel in mine:
        try:
            m = os.path.getmtime(os.path.join(root, rel))
        except Exception:
            continue
        if m > newest:
            newest, newest_file = m, rel

    if baseline and newest and baseline >= newest:
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
            "No baseline: this session has never checkpointed. A shared "
            ".syndicate/.last-checkpoint, if one exists, is another session's "
            "and is not evidence about this one.\n"
        )
    elif newest_file:
        sys.stderr.write(
            "Newest change (%s) postdates the last checkpoint (witness: %s).\n"
            % (newest_file, witness)
        )
    sys.stderr.write("Run /checkpoint before ending, or this session's findings do not survive it.\n")
    return 1


sys.exit(main())
