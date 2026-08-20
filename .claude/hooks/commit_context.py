"""Where a `git` `commit` will RUN, and what env it will see -- shared by hooks.

WHY THIS IS A MODULE AND NOT A COPY. Both facts below were learned once, in
`commit-guard.py`, each after a measured false block; `ledger-commit-guard.py`
was written later and had NEITHER, so it re-made both mistakes. The same
reasoning `ledger_invariants.py` states for predicates applies here: two guards
disagreeing about which repo a commit belongs to is worse than one guard, and a
third copy would drift again. This file is not a hook -- no `main()`, no side
effects on import -- so importing it is safe.

THE TWO FACTS:

  WHICH TREE.  A PreToolUse hook is handed `CLAUDE_PROJECT_DIR`, the PRIMARY
               checkout, but the commit runs wherever the shell is -- and this
               repo's documented recipe (`scripts/session_worktree.py`) puts
               every session in its OWN linked worktree with its own index and
               its own HEAD. A guard resolving against `CLAUDE_PROJECT_DIR` is
               not a weaker guard, it is a guard answering a different question:
               it cries wolf about another tree's file and stays silent about
               the one actually being committed.

               Measured 2026-08-16 (`commit-guard`): a session committing from
               `/c/tmp/lgl-ck` blocked three times over reverts staged in the
               MAIN index. Measured 2026-08-20 (`ledger-commit-guard`): a
               session in `C:/tmp/syndicate-sessions/soccer-board-mlb-parity`
               blocked over duplicate lane blocks that exist ONLY in the primary
               tree -- its own `lanes.md` had exactly one block per slug, and
               `check_lane_invariants.py` said INVARIANTS HOLD in that worktree.

  WHICH ENV.   A PreToolUse hook runs BEFORE the shell, so `VAR=1 git commit`
               and `export VAR=1; git commit` are both still just text. Reading
               `os.environ` alone makes every documented `VAR=1 git commit ...`
               override UNREACHABLE -- a session that does exactly what the
               refusal message prints is refused again by the same guard.

Deliberate remaining gap: `--git-dir` / `--work-tree`, where index and tree can
be decoupled and there is no single correct base. Callers detect that case
themselves and decide whether to keep guarding.
"""
from __future__ import annotations

import os
import re
import subprocess

_DASH_C_RE = re.compile(r"(?:^|\s)-C(?:\s+|=)(\"[^\"]*\"|'[^']*'|\S+)")
# `cd DIR`, with the shell quoting forms that actually appear in this repo's
# commands. Options (`cd -P`) are stepped over; a bare `cd` (to $HOME) is not
# matched, which is correct -- it is never followed by a repo-relative commit.
_CD_RE = re.compile(
    r"(?:^|[;&|]|\s)cd\s+(?:-[A-Za-z]+\s+)*(\"[^\"]*\"|'[^']*'|[^\s;&|]+)")


def _unquote(token):
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def command_cwd(cmd, commit_pos, payload):
    """The directory the git invocation will actually run in.

    Resolution order:
      1. the payload's `cwd` (the Bash tool's persistent working directory),
         then `CLAUDE_PROJECT_DIR`, then `os.getcwd()`
      2. any `cd` in the command that precedes the git invocation
      3. `-C <dir>` on the invocation itself -- git applies it last
    """
    base = None
    for candidate in (((payload or {}).get("cwd") or "").strip(),
                      os.environ.get("CLAUDE_PROJECT_DIR") or "",
                      os.getcwd()):
        if candidate and os.path.isdir(candidate):
            base = candidate
            break
    if base is None:
        return None

    # `cd a && cd b && git ...` lands in b, and a relative second hop resolves
    # against the first.
    for m in _CD_RE.finditer(cmd):
        if m.start() >= commit_pos:
            break
        target = _unquote(m.group(1))
        if not target or target.startswith("-"):
            continue
        base = target if os.path.isabs(target) else os.path.join(base, target)

    prefix = cmd[commit_pos:]
    m = _DASH_C_RE.search(prefix.split("commit", 1)[0])
    if m:
        target = _unquote(m.group(1))
        if target:
            base = target if os.path.isabs(target) else os.path.join(base, target)

    return base if os.path.isdir(base) else None


def worktree_root(cwd):
    """The top level of the worktree containing `cwd`, or None.

    Repo-relative paths are joined onto this, so it must be the tree the commit
    belongs to, not the main one.
    """
    try:
        p = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                           capture_output=True, timeout=20)
    except Exception:
        return None
    if p.returncode != 0:
        return None
    root = p.stdout.decode("utf-8", "replace").strip()
    return root if root and os.path.isdir(root) else None


def env_set_for_command(cmd, before, name):
    """Will `name` be set for the git this command runs?

    THE HOOK'S OWN ENV IS ONLY HALF THE ANSWER -- see the module docstring.
    Matches `export VAR=v`, a bare `VAR=v`, and the `VAR=v git ...` prefix.
    Last write before the invocation wins, so an intervening `unset` counts. An
    empty value is NOT set, which matches `os.environ.get()` being falsy for "".
    """
    if os.environ.get(name):
        return True
    head = cmd[:before]
    events = []
    assign = re.compile(r"(?:^|[;&|(]|\s)(?:export\s+)?" + re.escape(name)
                        + r"=(\"[^\"]*\"|'[^']*'|[^\s;&|)]*)")
    for m in assign.finditer(head):
        events.append((m.start(), bool(_unquote(m.group(1)))))
    unset = re.compile(r"(?:^|[;&|(]|\s)unset\s+(?:-v\s+)?"
                       r"(?:[A-Za-z_][A-Za-z0-9_]*\s+)*" + re.escape(name)
                       + r"(?![A-Za-z0-9_])")
    for m in unset.finditer(head):
        events.append((m.start(), False))
    if not events:
        return False
    events.sort()
    return events[-1][1]
