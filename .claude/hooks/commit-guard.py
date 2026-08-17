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

PREDICATE 1 (whole-file), near-zero false positive: refuse when the index stages
the DELETION of a path that still EXISTS on disk. That combination is almost
never intended -- a real deletion removes the file too. The legitimate exception
is `git rm --cached` (deliberately untracking a file that stays on disk), which
is rare and is named in the refusal message so the author can re-run with the
documented override.

PREDICATE 2 (content), added 2026-08-16 after FOUR MORE OCCURRENCES that this
guard was structurally blind to:

  3-6. The same shared index staged CONTENT REVERTS, not file deletions:
     `.syndicate/lanes.md` at 122 insertions / 147 deletions -- byte-identical
     to that file at `HEAD^`, i.e. the exact inverse of the commit that had just
     landed; `.syndicate/deploys.md` at HEAD-34 against a worktree of HEAD+119;
     and worst, `syndicate/features/shared/book_grid_artifact.py` at 0
     insertions / 17 DELETIONS, whose staged blob was exactly `f8ca54e1^` --
     those 17 lines being the Drop 3 hook EXECUTING on refresh-worker at that
     moment. A bare `git commit` would have stripped live production code with
     the working tree clean and this guard green.

  Every one of those is status `M`, not `D`. A content revert never changes a
  file's presence on disk, so `--name-status` reports `M` and predicate 1
  returns 0. The guard had never once fired, which read as "no problem" and
  actually meant "blind to this problem".

  **The observable was wrong.** The hazard is a stale BLOB; a check that looks
  at PATHS cannot see it. So predicate 2 compares content:

      refuse when the staged blob DROPS lines that are present in BOTH `HEAD`
      AND the working tree.

  That is the shape a stale index makes and the shape a real edit cannot. If you
  genuinely delete a line, it is gone from the working tree too, so it fails the
  "and the working tree" half and is NOT flagged. Normal edits stay silent --
  which is what keeps this guard from crying wolf and being turned off, the
  failure mode `learnings.md` already records.

  The strongest case is called out by name when it holds: staged blob ==
  `git ls-tree HEAD^ -- <path>`, a pure revert-in-waiting.

WHICH INDEX IT READS, fixed 2026-08-16 after THREE FALSE POSITIVES IN ONE
SESSION -- and the same bug is a FALSE NEGATIVE in the other direction:

  Both predicates were evaluated against `CLAUDE_PROJECT_DIR`, the MAIN
  worktree. But the commit runs wherever the shell is, and this repo's own
  documented recipe for a contended tree is `git worktree add` + commit from
  there. A linked worktree has its OWN index and its OWN HEAD.

  So the guard was answering a question nobody asked. Measured 2026-08-16: a
  session committing from `/c/tmp/lgl-ck` was blocked three times over reverts
  staged in the MAIN index, while its own index held exactly its four intended
  appends. Each block named real danger -- in the wrong tree.

  **The false negative is the half that matters.** A stale index in the worktree
  being committed from was never examined at all, so the guard would pass it
  silently. "It has its own index" was the reason the old code skipped scoped
  calls; having your own index is not the same as having a FRESH one, and that
  conflation is precisely what this guard exists to catch.

  Resolution order for the directory git will actually run in:
    1. any `cd` in the command that precedes the `git ... commit`
    2. `-C <dir>` on the commit invocation itself
    3. the payload's `cwd` (the Bash tool's persistent working directory)
    4. `CLAUDE_PROJECT_DIR`, then `os.getcwd()`
  then `git rev-parse --show-toplevel` from there, so on-disk path joins are
  relative to the right worktree.

  Still skipped, deliberately and now named as a GAP rather than as safety:
  `--git-dir` / `--work-tree`, where the index and the tree can be decoupled and
  the on-disk half of predicate 1 has no single correct base.

WHAT THE COMMIT ACTUALLY COMMITS, fixed 2026-08-17 after the guard blocked a
session for following the guard's own printed instructions. Both halves are the
same defect: the guard read a PROXY for the commit instead of the commit.

  (a) EVERY OVERRIDE THIS FILE DOCUMENTS WAS UNREACHABLE. All three exemptions
      were `os.environ.get(...)` -- the HOOK's process env, inherited from Claude
      Code. But a PreToolUse hook runs BEFORE the shell does, so the `export`
      in the recipe printed below, and the `VAR=1 git commit ...` prefix printed
      as the override, are both in a command string that has not run yet. The
      hook could never see them. The documented escape hatch from this guard
      did not exist, and a session that did exactly what the refusal message
      said was refused again.

      So the assignments are now parsed OUT OF THE COMMAND STRING (`export
      VAR=v`, a bare `VAR=v` statement, or the `VAR=v git commit` prefix),
      last-write-wins against an intervening `unset`, for all three variables.
      No new sentinel spelling was added: the recipe already had a name, and a
      second way to say it is a second thing to get wrong.

  (b) A PATHSPEC-LIMITED COMMIT CANNOT CARRY A STALE INDEX ENTRY, and the guard
      flagged one anyway. `git commit -- <paths>` was blocked over a staged
      revert of `.syndicate/lanes.md` belonging to another session -- a path the
      commit was structurally incapable of including.

      MEASURED 2026-08-17, index holding a revert of `A.txt` plus a `D` of
      `C.txt` that was still on disk:

        git commit -m x -- C.txt     tree kept A.txt at HEAD content, kept
                                     C.txt; --stat = 1 file.   IMMUNE
        git commit --pathspec-from-file=LIST -m x              IMMUNE
        git commit --amend -m x -- C.txt                       IMMUNE
        git commit -i -m x -- C.txt  A.txt LOST its line       NOT immune
        git commit -a -m x           A.txt kept its line, but the DELETION of
                                     C.txt was committed      NOT immune

      A partial commit builds its tree from HEAD plus the WORKING TREE content
      of the named paths, so the index is not consulted for anything -- not even
      for the named paths. That is why the exemption is whole-commit rather than
      a filter over which paths get evaluated: there is no path left to
      evaluate. `learnings.md` 2026-08-14 already said "prefer the pathspec
      form, which makes the index state irrelevant"; this is that sentence
      measured.

      `-i`/`--include` is exactly the option that re-admits the index, and it
      is excluded by name. A pathspec-LESS commit keeps every bit of today's
      behaviour.

      `-a` is NOT exempt, and is a KNOWN REMAINING FALSE POSITIVE rather than a
      decision that came out clean. It re-stages worktree content for tracked
      files, so predicate 2 cannot bite under it -- yet the guard still fires on
      predicate 2 there. It was left alone because the exemption is not sound as
      measured: `-a` does not refresh `skip-worktree` or `assume-unchanged`
      paths, and that case has not been measured. Predicate 1 IS live under
      `-a`: a `git rm --cached` path is no longer tracked, so `-a` does not
      re-add it and the deletion was committed.

      An option this parser does not recognise makes it answer "not pathspec
      limited", i.e. it keeps guarding. The failure direction is a false
      positive, never a false negative.

  Named as a GAP rather than as safety, in both halves: an isolated
  `GIT_INDEX_FILE` is exempted, never examined. If it names a literal, stable
  path (which `learnings.md` 2026-08-15 REQUIRES) and the command does not
  `read-tree` into it first, it can be as stale as the shared one. That hole
  predates this change -- the env-var check always had it -- and closing it
  means evaluating the predicates against that index file, not skipping it.

Overrides -- these now work as written, from inside the command:
    SYNDICATE_ALLOW_STAGED_DELETES=1 git commit ...   # disables BOTH predicates
    SYNDICATE_ALLOW_STAGED_REVERTS=1 git commit ...   # disables predicate 2 only
"""
import json
import os
import re
import subprocess
import sys

ALLOW_ENV = "SYNDICATE_ALLOW_STAGED_DELETES"
REVERT_ALLOW_ENV = "SYNDICATE_ALLOW_STAGED_REVERTS"
# A hook runs in front of every Bash call, so predicate 2 is bounded rather than
# thorough. These caps are backstops against a pathological tree, not budgets:
# a normal staged set is a handful of text files.
_MAX_PATHS = 120
_MAX_BLOB_BYTES = 4 * 1024 * 1024
# `git commit` but not `git commit-tree`. The whole invocation prefix is
# captured so `-C <dir>` can be read off it: the commit's own index is the one
# to check, wherever it lives.
_GIT_OPT = r"(?:-c|-C)(?:\s+|=)\S+\s+"
COMMIT_RE = re.compile(
    r"(?:^|[;&|]|\s)(git\s+(?:" + _GIT_OPT + r")*commit(?![\w-]))")
# Index and working tree can be decoupled here, so predicate 1's "does it still
# exist on disk" question has no single correct base. Skipped, and named as a
# gap in the docstring rather than passed off as safe.
DECOUPLED_RE = re.compile(r"(?:^|\s)git\s[^;&|]*?--(?:git-dir|work-tree)(?:=|\s)")
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


# --------------------------------------------------------------------------
# Reading the COMMAND, not a proxy for it. See docstring section (a) and (b):
# the hook runs before the shell, so anything the command sets or scopes is
# visible only by parsing the command text.
# --------------------------------------------------------------------------
_SEPARATORS = ";&|\n"


def shell_words(text):
    """`text` split into words, stopping at the first UNQUOTED separator.

    Only as much shell as this repo's commands actually use. Returns None when
    the quoting does not close -- an unparsed command must fall through to
    "keep guarding", never to "exempt".
    """
    words, cur, started, depth = [], [], False, 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            if i + 1 >= n:
                return None
            cur.append(text[i + 1])
            started = True
            i += 2
            continue
        if ch == "'":
            j = text.find("'", i + 1)
            if j < 0:
                return None
            cur.append(text[i + 1:j])
            started = True
            i = j + 1
            continue
        if ch == '"':
            j, buf = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            if j >= n:
                return None
            cur.append("".join(buf))
            started = True
            i = j + 1
            continue
        # A separator inside `$(...)` belongs to the substitution, not to us.
        if ch == "$" and text.startswith("$(", i):
            depth += 1
            cur.append("$(")
            started = True
            i += 2
            continue
        if ch == ")":
            if depth:
                depth -= 1
                cur.append(")")
                i += 1
                continue
            break                      # closing subshell: the command ends here
        if not depth and ch in _SEPARATORS:
            break
        if ch in " \t":
            if started:
                words.append("".join(cur))
                cur, started = [], False
            i += 1
            continue
        cur.append(ch)
        started = True
        i += 1
    if started:
        words.append("".join(cur))
    return words


def env_set_for_command(cmd, before, name):
    """Will `name` be set for the git this command runs?

    THE HOOK'S OWN ENV IS ONLY HALF THE ANSWER. A PreToolUse hook runs before
    the shell, so `export GIT_INDEX_FILE=...` -- the literal recipe this file
    prints in its refusal -- is invisible to `os.environ`. Every override this
    guard documented was therefore unreachable, and the session that followed
    the printed instructions was blocked by the same guard that printed them.

    Matches `export VAR=v`, a bare `VAR=v`, and the `VAR=v git commit` prefix.
    Last write before the commit wins, so an intervening `unset` counts. An
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


# `git commit` options that consume a SEPARATE following word. Options whose
# value can only be ATTACHED (`-S<keyid>`, `-u<mode>`, `--long=form`) are not
# here on purpose: git does not eat the next word for those, so listing them
# would swallow a real pathspec and silence the guard.
_VALUE_OPTS = {
    "-m", "--message", "-F", "--file", "-c", "--reedit-message",
    "-C", "--reuse-message", "-t", "--template", "--author", "--date",
    "--cleanup", "--fixup", "--squash", "--trailer", "--pathspec-from-file",
}
_FLAG_OPTS = {
    "-a", "--all", "-i", "--include", "-o", "--only", "-e", "--edit",
    "--no-edit", "-n", "--no-verify", "--verify", "--no-signoff", "-q",
    "--quiet", "-v", "--verbose", "-s", "--signoff", "--amend", "--dry-run",
    "--allow-empty", "--allow-empty-message", "--reset-author", "--short",
    "--branch", "--no-branch", "--porcelain", "--long", "-z", "--null",
    "--status", "--no-status", "--no-post-rewrite", "--pathspec-file-nul",
    "-S", "--gpg-sign", "--no-gpg-sign", "-u", "--untracked-files",
    "--no-rename", "--no-renames",
}
_SHORT_VALUE = set("mFcCt")          # eats the rest of the cluster, or the next word
_SHORT_OPTARG = set("Su")            # optional value, ATTACHED only
_SHORT_FLAG = set("aioenqvszSu")


def pathspec_limited(words):
    """Does this `git commit` name a pathspec, so only those paths are committed?

    MEASURED 2026-08-17 (see docstring): a partial commit builds its tree from
    HEAD plus the WORKING TREE content of the named paths and never consults
    the index -- not even for the named paths -- so a stale index entry cannot
    reach the commit. `-i`/`--include` is the option that re-admits the index
    and is excluded by name.

    `words` are the shell words AFTER `commit`. Returns False on anything this
    cannot parse: the safe direction is to keep guarding.
    """
    include, from_file, paths = False, False, []
    i, n = 0, len(words)
    while i < n:
        word = words[i]
        if word == "--":
            paths += [w for w in words[i + 1:] if w]
            break
        if not word.startswith("-") or word == "-":
            paths.append(word)         # git permutes, so keep reading options
            i += 1
            continue

        name = word.split("=", 1)[0]
        if name in ("-i", "--include"):
            include = True
        if name == "--pathspec-from-file":
            from_file = True

        if word.startswith("--"):
            if "=" in word:
                if name not in _VALUE_OPTS and name not in _FLAG_OPTS:
                    return False
                i += 1
            elif name in _VALUE_OPTS:
                i += 2
            elif name in _FLAG_OPTS:
                i += 1
            else:
                return False
            continue

        chars, eats_next = word[1:], False
        for k, ch in enumerate(chars):
            if ch in _SHORT_VALUE:
                eats_next = (k == len(chars) - 1)   # else the value is attached
                break
            if ch in _SHORT_OPTARG and k < len(chars) - 1:
                break                               # `-S<keyid>`: rest is the value
            if ch not in _SHORT_FLAG:
                return False
        i += 2 if eats_next else 1

    if include:
        return False                   # measured: --include carried the revert
    return bool(from_file or paths)


def command_cwd(cmd, commit_pos, payload):
    """The directory `git commit` will actually run in.

    A guard that reads a different tree than the command touches is not a
    weaker guard, it is a guard answering a different question -- it both cries
    wolf about someone else's index and stays silent about the one at risk.
    """
    base = None
    for candidate in ((payload.get("cwd") or "").strip(),
                      os.environ.get("CLAUDE_PROJECT_DIR") or "",
                      os.getcwd()):
        if candidate and os.path.isdir(candidate):
            base = candidate
            break
    if base is None:
        return None

    # Apply every `cd` that precedes the commit, in order: `cd a && cd b && git
    # commit` lands in b, and a relative second hop resolves against the first.
    for m in _CD_RE.finditer(cmd):
        if m.start() >= commit_pos:
            break
        target = _unquote(m.group(1))
        if not target or target.startswith("-"):
            continue
        base = target if os.path.isabs(target) else os.path.join(base, target)

    # `-C` on the commit invocation itself wins: git applies it last.
    prefix = cmd[commit_pos:]
    m = _DASH_C_RE.search(prefix.split("commit", 1)[0])
    if m:
        target = _unquote(m.group(1))
        if target:
            base = target if os.path.isabs(target) else os.path.join(base, target)

    return base if os.path.isdir(base) else None


def worktree_root(cwd):
    """The top level of the worktree containing `cwd`.

    Predicate 1 joins repo-relative paths onto this to ask "is it still on
    disk", so it must be the tree the commit belongs to, not the main one.
    """
    out = _git(cwd, "rev-parse", "--show-toplevel")
    if not out:
        return None
    root = out.decode("utf-8", "replace").strip()
    return root if root and os.path.isdir(root) else None


def _git(root, *args):
    """stdout of a git call as BYTES, or None. Never raises."""
    try:
        p = subprocess.run(["git"] + list(args), cwd=root,
                           capture_output=True, timeout=20)
        return p.stdout if p.returncode == 0 else None
    except Exception:
        return None


# Everything below is BATCHED on purpose. The per-path version cost 5.3s on 27
# staged paths (~108 subprocess spawns on Windows at ~50ms each). A guard that
# adds five seconds to every commit gets switched off, which is the exact
# failure mode `learnings.md` records for guards that cry wolf -- slow is just a
# quieter way of crying wolf. Batched, the same work is 3 spawns.
def _z_fields(data):
    """NUL-separated git output -> list of fields. `-z` avoids the path-quoting
    git applies to non-ASCII names in its human-readable formats."""
    if not data:
        return []
    return data.decode("utf-8", "replace").split("\0")


def _staged_and_head_shas(root, paths):
    """{path: idx_sha}, {path: head_sha} in two calls rather than 2N."""
    idx, head = {}, {}
    args = ["ls-files", "-s", "-z", "--"] + paths
    for ent in _z_fields(_git(root, *args)):
        if not ent:
            continue
        meta, _, path = ent.partition("\t")
        bits = meta.split()
        if len(bits) >= 2 and path:
            idx[path] = bits[1]
    args = ["ls-tree", "-r", "-z", "HEAD", "--"] + paths
    for ent in _z_fields(_git(root, *args)):
        if not ent:
            continue
        meta, _, path = ent.partition("\t")
        bits = meta.split()
        if len(bits) >= 3 and path:
            head[path] = bits[2]
    return idx, head


def _batch_blobs(root, shas):
    """{sha: bytes} for many blobs in ONE `git cat-file --batch` process."""
    out = {}
    shas = [s for s in dict.fromkeys(shas) if s]
    if not shas:
        return out
    try:
        p = subprocess.run(["git", "cat-file", "--batch"], cwd=root,
                           input=("\n".join(shas) + "\n").encode(),
                           capture_output=True, timeout=60)
        data = p.stdout
    except Exception:
        return out
    pos = 0
    while pos < len(data):
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        header = data[pos:nl].decode("utf-8", "replace").split()
        pos = nl + 1
        if len(header) < 3 or header[1] != "blob":
            continue          # "<sha> missing" -- skip, do not guess
        try:
            size = int(header[2])
        except ValueError:
            break
        out[header[0]] = data[pos:pos + size]
        pos += size + 1       # blob payload, then git's trailing newline
    return out


def _lines(data):
    """Non-blank lines of a blob/file as a set. Blank lines carry no content and
    would make reflows look like reverts."""
    if data is None:
        return None
    if b"\0" in data[:8000]:  # binary: line comparison is meaningless
        return None
    if len(data) > _MAX_BLOB_BYTES:
        return None
    return {l for l in data.decode("utf-8", "replace").splitlines() if l.strip()}


def staged_reverts(root, name_status):
    """Paths whose STAGED blob drops content present in BOTH HEAD and the worktree.

    That is the signature of a stale index and NOT of a real edit: deleting a
    line for real removes it from the working tree too, which fails the second
    half of the conjunction. Returns [(path, n_dropped, is_exact_prior_blob)].
    """
    # Re-read the diff with -z: the human-readable form quotes non-ASCII paths,
    # and a path this cannot parse is a path this cannot protect.
    fields = _z_fields(_git(root, "diff", "--cached", "--name-status", "-z",
                            "--no-renames"))
    paths, i = [], 0
    while i + 1 < len(fields):
        status, path = fields[i], fields[i + 1]
        i += 2
        if status.startswith("M") and path:
            paths.append(path)
    paths = paths[:_MAX_PATHS]
    if not paths:
        return []

    idx_map, head_map = _staged_and_head_shas(root, paths)
    candidates = [p for p in paths
                  if idx_map.get(p) and head_map.get(p)
                  and idx_map[p] != head_map[p]]
    if not candidates:
        return []
    blobs = _batch_blobs(
        root, [idx_map[p] for p in candidates] + [head_map[p] for p in candidates])

    out = []
    for path in candidates:
        idx_lines = _lines(blobs.get(idx_map[path]))
        head_lines = _lines(blobs.get(head_map[path]))
        if idx_lines is None or head_lines is None:
            continue
        try:
            with open(os.path.join(root, path), "rb") as fh:
                work_lines = _lines(fh.read())
        except OSError:
            continue
        if work_lines is None:
            continue
        # Present in HEAD *and* still on disk, yet missing from what would be
        # committed. Nobody removed these -- the index simply predates them.
        dropped = (head_lines & work_lines) - idx_lines
        if dropped:
            out.append((path, len(dropped), idx_map[path]))

    # HEAD^ only for the few that already flagged, so the common case pays nothing.
    if out:
        prior = {}
        for ent in _z_fields(_git(root, "ls-tree", "-r", "-z", "HEAD^", "--",
                                  *[p for p, _, _ in out])):
            if not ent:
                continue
            meta, _, path = ent.partition("\t")
            bits = meta.split()
            if len(bits) >= 3 and path:
                prior[path] = bits[2]
        out = [(p, n, prior.get(p) == sha) for p, n, sha in out]
    return out


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("tool_name") != "Bash":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    m = COMMIT_RE.search(cmd)
    if not m:
        return 0
    if DECOUPLED_RE.search(cmd):
        return 0
    # Both of these read the COMMAND as well as the hook's env. Reading only the
    # env made every documented override unreachable, because a PreToolUse hook
    # runs before the shell that would set it.
    if env_set_for_command(cmd, m.start(1), ALLOW_ENV):
        return 0
    if env_set_for_command(cmd, m.start(1), "GIT_INDEX_FILE"):
        # Isolated index: this is the safe recipe. Exempted, not examined --
        # named as a gap in the docstring.
        return 0

    # A pathspec commits HEAD + the WORKING TREE content of the named paths and
    # never consults the index, so there is nothing here for either predicate to
    # find. Measured 2026-08-17; `-i`/`--include` excluded, pathspec-less
    # unchanged.
    words = shell_words(cmd[m.end(1):])
    if words is not None and pathspec_limited(words):
        return 0

    # THE INDEX THE COMMIT WILL USE, not the main worktree's. Reading the wrong
    # one blocked three clean commits in one session while leaving the index
    # actually at risk unexamined.
    cwd = command_cwd(cmd, m.start(1), payload)
    root = worktree_root(cwd) if cwd else None
    if root is None:
        # Cannot tell which tree this commit belongs to. A guard that cannot
        # read must not block work -- the same rule the read below follows.
        return 0
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

    reverts = ([] if env_set_for_command(cmd, m.start(1), REVERT_ALLOW_ENV)
               else staged_reverts(root, out))

    if not doomed and not reverts:
        return 0

    lines = [
        "BLOCKED: this commit would silently discard committed work.",
        "",
        "The shared git index is visible to every session in this worktree, so a",
        "`git add` in another session lands in YOUR commit. Sessions here commit",
        "through isolated GIT_INDEX_FILEs, which never advance the shared index --",
        "so it is stale CONTINUOUSLY, not occasionally.",
        "",
    ]

    if doomed:
        lines += [
            "(1) STAGED DELETION of %d file(s) that still exist on disk:" % len(doomed),
            "",
        ]
        for path, size in doomed[:20]:
            lines.append("  D  %s  (%s bytes ON DISK)" % (path, size))
        if len(doomed) > 20:
            lines.append("  ... and %d more" % (len(doomed) - 20))
        lines.append("")

    if reverts:
        lines += [
            "(2) STAGED CONTENT REVERT in %d file(s) -- the staged blob DROPS lines"
            % len(reverts),
            "    that are present in BOTH HEAD and the working tree. Nobody removed",
            "    them; the index simply predates them. This shape stripped a hook that",
            "    was executing in production on 2026-08-16 (book_grid_artifact.py,",
            "    0 insertions / 17 deletions) while this guard read green.",
            "",
        ]
        for path, n, exact in reverts[:20]:
            flag = "  <-- staged blob IS the HEAD^ blob: a pure revert" if exact else ""
            lines.append("  M  %s  (drops %d committed line(s))%s" % (path, n, flag))
        if len(reverts) > 20:
            lines.append("  ... and %d more" % (len(reverts) - 20))
        lines.append("")

    affected = [p for p, _ in doomed] + [p for p, _, _ in reverts]
    lines += [
        "FIRST CHOICE -- name your paths. A pathspec commit takes HEAD plus the",
        "WORKING TREE content of those paths and never reads the index, so none",
        "of the above can reach it (measured 2026-08-17). It needs no adjudication",
        "of staged work that may not be yours:",
        "  git commit -m \"<msg>\" -- <your paths>          # -m BEFORE the --",
        "",
        "Or commit through an ISOLATED index -- one Bash call, and a LITERAL",
        "stable path (`learnings.md` 2026-08-15: an interpolated one differs per",
        "shell, and an absent index file is an EMPTY one, not an error):",
        "  export GIT_INDEX_FILE=C:/tmp/idx-<your-lane>",
        "  git read-tree HEAD && git add -- <your paths> \\",
        "    && git diff --cached --stat && git commit -m \"<msg>\"",
        "",
        "Repairing the shared index is a THIRD option and it is not free: these",
        "blobs may be another session's staged work. Confirm each path is in HEAD",
        "and on disk before clearing it, and re-read `git diff --cached` after --",
        "this list has been incomplete before:",
        "  git restore --staged " + " ".join(affected[:8])
        + ("   # ... AND %d MORE, see above" % (len(affected) - 8)
           if len(affected) > 8 else ""),
        "",
        "Overrides, if you genuinely mean it (as a prefix on the command itself):",
        "  %s=1 git commit ...   # untracking a file that stays" % ALLOW_ENV,
        "  %s   # on disk (`git rm --cached`)" % (" " * len(ALLOW_ENV)),
        "  %s=1 git commit ...   # a deliberate partial revert" % REVERT_ALLOW_ENV,
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
