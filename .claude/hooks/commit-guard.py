#!/usr/bin/env python3
"""PreToolUse(Bash) — refuse a `git commit` that would silently destroy a file.

WHY THIS EXISTS (twice in one night, 2026-08-14/15):

  1. A complete revert of shipped `ask_the_syndicate` M1 work sat staged in the
     SHARED index -- 6 files, 4993 deletions -- while the working tree matched
     HEAD. A bare `git commit` from ANY session would have un-shipped it without
     touching one working-tree file.
  2. Hours later the same index staged a DELETION of
     `.syndicate/state_archive_2026-08-15.md` (129,704 B on disk, the only copy
     of the pre-collapse ledger) plus truncations of `learnings.md` (-537) and
     `log/2026-08-14.md` (-934). All four files existed on disk. Caught by
     inspection, not by any guard.

The mechanism: git's index is SHARED state across every session in this
worktree, and `git add` in one session is visible to `git commit` in another.
With 8 sessions live, the window between one session's `add` and its `commit`
is long enough for another session to stage or clear anything.

THE PREDICATE, chosen to be near-zero false positive: refuse when the index
stages the DELETION of a path that still EXISTS on disk. That combination is
almost never intended -- a real deletion removes the file too. The legitimate
exception is `git rm --cached` (deliberately untracking a file that stays on
disk), which is rare and is named in the refusal message so the author can
re-run with the documented override.

It deliberately does NOT police staged MODIFICATIONS. Those are the normal case,
and blocking them would make the guard fire constantly and be turned off -- the
failure mode `learnings.md` already records for guards that cry wolf.

Override, for the genuine `git rm --cached` case:
    SYNDICATE_ALLOW_STAGED_DELETES=1 git commit ...
"""
import json
import os
import re
import subprocess
import sys

ALLOW_ENV = "SYNDICATE_ALLOW_STAGED_DELETES"
# `git commit` but not `git commit-tree`, and not a commit inside another
# worktree via -C / --git-dir (those have their own index and are the
# documented safe recipe, so leave them alone).
COMMIT_RE = re.compile(r"(?:^|[;&|]|\s)git\s+(?:-c\s+\S+\s+)*commit(?![\w-])")
SCOPED_RE = re.compile(r"(?:^|\s)git\s+(?:-C\s+\S+|--git-dir(?:=|\s)\S+)")


def repo_root():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("tool_name") != "Bash":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if not COMMIT_RE.search(cmd):
        return 0
    # An explicitly scoped git call uses another repo/index -- not our problem,
    # and it is the recipe the ledger tells sessions to use.
    if SCOPED_RE.search(cmd):
        return 0
    if os.environ.get(ALLOW_ENV):
        return 0
    if os.environ.get("GIT_INDEX_FILE"):
        # Isolated index: this is the safe recipe, by construction.
        return 0

    root = repo_root()
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-status", "--no-renames"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except Exception:
        # A guard that cannot read must not block work.
        return 0

    doomed = []
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2 or not parts[0].startswith("D"):
            continue
        path = parts[1].strip()
        full = os.path.join(root, path)
        if os.path.exists(full):
            try:
                size = os.path.getsize(full)
            except OSError:
                size = -1
            doomed.append((path, size))

    if not doomed:
        return 0

    lines = [
        "BLOCKED: this commit would DELETE %d file(s) that still exist on disk."
        % len(doomed),
        "",
        "The shared git index is visible to every session in this worktree, so a",
        "`git add` in another session lands in YOUR commit. A staged deletion of a",
        "file that is still on disk is almost never what the committer intended --",
        "this exact shape has already cost shipped work twice (2026-08-14/15).",
        "",
    ]
    for path, size in doomed[:20]:
        lines.append("  D  %s  (%s bytes ON DISK)" % (path, size))
    if len(doomed) > 20:
        lines.append("  ... and %d more" % (len(doomed) - 20))
    lines += [
        "",
        "Fix (index-only, cannot disturb any session's working-tree edits):",
        "  git restore --staged " + " ".join(p for p, _ in doomed[:8]),
        "",
        "Then commit through an ISOLATED index so this cannot recur:",
        "  export GIT_INDEX_FILE=$(mktemp -u /tmp/idx.XXXX)",
        "  git read-tree HEAD && git add -- <your paths> && git diff --cached --stat",
        "",
        "If you genuinely mean to untrack a file that stays on disk",
        "(`git rm --cached`), re-run with %s=1." % ALLOW_ENV,
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
