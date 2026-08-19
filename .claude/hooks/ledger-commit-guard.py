#!/usr/bin/env python3
"""PreToolUse hook - refuses to COMMIT a LEDGER FILE whose invariants fail.

Covers `lanes.md`, `state.md` and `learnings.md`. The predicates live in
`ledger_invariants.py` so the write-time hook enforces exactly the same set --
two guards disagreeing about what "broken" means is worse than one guard.

WHY THIS EXISTS, and why the PreToolUse file-tool guard was not enough.
`lanes-append-guard.py` blocks the two ways `lanes.md` goes wrong, but it matches
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
except Exception:
    sys.exit(0)

LANES = ".syndicate/lanes.md"
ALLOW_ENV = "SYNDICATE_ALLOW_LEDGER_COMMIT"
HEADER_RE = re.compile(r"(?m)^###\s+(\S+)\s")
ARCHIVE_RE = re.compile(r"(?m)^## Archived lanes")
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
    if os.environ.get(ALLOW_ENV, "").strip() == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name", "") not in ("Bash", "PowerShell"):
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not COMMIT_RE.search(command):
        return 0

    root = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    report = []
    for rel in TRACKED:
        try:
            text = _content_to_be_committed(root, command, rel)
        except Exception:
            continue
        if not text:
            continue
        bad = violations(rel, text)
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
        "Checked the content each commit would actually record (staged blob for a\n"
        "plain commit, working file for a pathspec or -a commit) -- not merely the\n"
        "file on disk.\n"
        "Verify with: py -3 scripts/check_lane_invariants.py\n"
        "             py -3 scripts/state_key_check.py\n"
        f"Override:    {ALLOW_ENV}=1 git commit ...\n")
    return 2


sys.exit(main())
