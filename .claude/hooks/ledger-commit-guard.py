#!/usr/bin/env python3
"""PreToolUse hook - refuses to COMMIT a LEDGER FILE whose invariants fail.

Covers `lanes.md`, `state.md` and `learnings.md`. The predicates live in
`ledger_invariants.py` so the write-time hook enforces exactly the same set --
two guards disagreeing about what "broken" means is worse than one guard.

WHY THIS EXISTS, and why the PreToolUse file-tool guard was not enough.
`ledger-append-guard.py` blocks the two ways `lanes.md` goes wrong, but it matches
`Edit|Write|MultiEdit` and is therefore BLIND TO BASH. That is not an edge case
here: this repo's own ledger tooling -- `trim_lane_blocks.py`,
`hoist_open_lanes.py`, `compact_learnings.py`, `archive_released_lanes.py` --
all write ledger files from Bash by design, and so does any `sed`/`python`
one-liner. Measured 2026-08-19: a lane block landed below the archive marker
fourteen minutes AFTER that guard went live.

Another PreToolUse matcher cannot close it -- a Bash command is an opaque string
and deciding what it will write means running it. The COMMIT is the choke point:
a Bash write has to pass through here to become durable, whoever made it and
however. Catching it at the commit is later than catching it at the write, but
it is the last place it is still cheap.

THE TWO PREDICATES, both measured failures and both currently CLEAN (0 and 0), so
neither blocks the file's legitimate present state:

  OPEN LANE BELOW THE ARCHIVE MARKER  `lane-guard` reads `lanes.md` and NOTHING
                                      else, so the next archive pass moves that
                                      block to `lanes_closed.md` and its file
                                      claims stop being enforced SILENTLY. #466.
  A SLUG WITH MORE THAN ONE BLOCK     the append-instead-of-edit failure that
                                      took this file to 2.12x its cap with one
                                      lane holding 16 blocks / 44,905 B.

IT CHECKS THE CONTENT THAT WOULD ACTUALLY BE COMMITTED, which is not always the
working tree: a pathspec commit takes the working file, a plain `git commit`
takes the STAGED blob, and those differ precisely when someone has staged one
version and edited another. Guessing wrong here would either miss the defect or
block a clean commit.

WHICH TREE, and WHICH ENV -- both fixed 2026-08-20, both re-made here after
`commit-guard.py` had already learned them. Details and the measurements live in
`commit_context.py`; the short version:

  (a) THE GUARD READ A DIFFERENT REPO THAN THE ONE BEING COMMITTED. `root` was
      `CLAUDE_PROJECT_DIR`, the PRIMARY tree, while this repo's own protocol
      puts every session in its own worktree. Measured from
      `C:/tmp/syndicate-sessions/soccer-board-mlb-parity`: blocked over
      `layer2-board-chip-race` and `mlb-pregame-ladder-schema` having two blocks
      each -- in the PRIMARY tree. The worktree's `lanes.md`, the file the
      commit would actually record, had exactly one block per slug and
      `check_lane_invariants.py` returned INVARIANTS HOLD there.

      The message below claimed it "Checked the content each commit would
      actually record ... not merely the file on disk". That was false in the
      worktree case in the way that matters most: not merely a stale file, a
      DIFFERENT REPOSITORY. And the remedy it printed --
      `trim_lane_blocks.py --apply` -- would, run in the tree the guard was
      complaining about, rewrite TWO OTHER SESSIONS' lane blocks to satisfy a
      check about a file the committing session never touched. A guard that
      prints a destructive remedy for someone else's file is worse than no
      guard. The refusal now names the tree it read and only suggests the trim
      when that tree is the one being committed from.

  (b) THE DOCUMENTED OVERRIDE WAS UNREACHABLE. `SYNDICATE_ALLOW_LEDGER_COMMIT=1
      git commit ...` as an inline prefix is still just text when a PreToolUse
      hook runs -- the shell has not assigned it yet -- so `os.environ.get`
      never saw it and the escape hatch this file printed did not exist. Same
      defect `commit-guard.py` fixed 2026-08-17; same fix, shared code.

FAILS OPEN on anything it cannot determine -- no git, no file, an unparseable
command -- like every other guard here. A guard that blocks real work is one
people rip out. Override: `SYNDICATE_ALLOW_LEDGER_COMMIT=1 git commit ...`
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from ledger_invariants import TRACKED, violations
    from commit_context import command_cwd, env_set_for_command, worktree_root
except Exception:
    sys.exit(0)

ALLOW_ENV = "SYNDICATE_ALLOW_LEDGER_COMMIT"
# The lane/archive regexes that used to live here were dead: the predicates
# moved to `ledger_invariants.py` and nothing re-read them. A second copy of a
# predicate in the file that enforces it is exactly the drift that module exists
# to prevent, so they are gone rather than kept "for reference".
# `git commit`, allowing `git -C x commit` and `git --no-pager commit`.
COMMIT_RE = re.compile(r"\bgit\b(?:\s+-{1,2}[^\s]+(?:\s+[^\s]+)?)*\s+commit\b")


def _git(root, *args):
    try:
        r = subprocess.run(["git", "-C", root, *args],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def _content_to_be_committed(root, command, rel):
    """The lanes.md text this commit would record, or None if it records none.

    Three cases, and they genuinely differ:
      - an explicit pathspec naming lanes.md  -> the WORKING TREE file
      - `-a` / `--all` with lanes.md modified -> the WORKING TREE file
      - otherwise, if lanes.md is staged      -> the STAGED blob (`:path`)
    """
    names_path = os.path.basename(rel) in command
    all_flag = bool(re.search(r"\s-(?:[a-zA-Z]*a[a-zA-Z]*)\b|\s--all\b", command))

    if names_path or all_flag:
        modified = _git(root, "status", "--porcelain", "--", rel)
        if names_path or (modified or "").strip():
            try:
                with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except OSError:
                return None

    staged = _git(root, "diff", "--cached", "--name-only", "--", rel)
    if staged and staged.strip():
        return _git(root, "show", f":{rel}")
    return None



def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name", "") not in ("Bash", "PowerShell"):
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    m = COMMIT_RE.search(command)
    if not m:
        return 0

    # The override, read from the COMMAND as well as the environment: an inline
    # `VAR=1 git commit ...` prefix has not been assigned yet when this runs.
    if env_set_for_command(command, m.start(), ALLOW_ENV):
        return 0

    # The tree the commit will actually be recorded in -- NOT CLAUDE_PROJECT_DIR,
    # which is the primary checkout and is a different repository whenever the
    # session is in its own worktree. See `commit_context.py`.
    cwd = command_cwd(command, m.start(), payload)
    root = (worktree_root(cwd) if cwd else None) or cwd
    if not root:
        return 0

    report = []
    for rel in TRACKED:
        try:
            text = _content_to_be_committed(root, command, rel)
        except Exception:
            continue
        if not text:
            continue
        bad = violations(rel, text, root)
        if bad:
            report.append((rel, bad))
    if not report:
        return 0

    sys.stderr.write("BLOCKED: this commit would record a ledger file that fails its invariants.\n\n")
    for rel, bad in report:
        sys.stderr.write(f"{rel}\n")
        for what, how in bad:
            sys.stderr.write(f"  * {what}\n{how}\n")
        sys.stderr.write("\n")
    sys.stderr.write(
        f"Tree read:   {root}\n"
        "             (the worktree this commit runs in -- resolved from the\n"
        "             command's cwd, not from CLAUDE_PROJECT_DIR. Any cleanup\n"
        "             suggested above applies to THIS tree. If that path is not\n"
        "             where you are working, say so -- it is a guard bug, and\n"
        "             running the cleanup would rewrite another tree's file.)\n"
        "Checked the content each commit would actually record (staged blob for a\n"
        "plain commit, working file for a pathspec or -a commit) -- not merely the\n"
        "file on disk.\n"
        f"Verify with: cd {root} && py -3 scripts/check_lane_invariants.py\n"
        f"             cd {root} && py -3 scripts/state_key_check.py\n"
        f"Override:    {ALLOW_ENV}=1 git commit ...   (as a prefix on the command\n"
        "             itself; `export` on a preceding line works too)\n")
    return 2


sys.exit(main())
