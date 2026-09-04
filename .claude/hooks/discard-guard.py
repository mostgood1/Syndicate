#!/usr/bin/env python3
"""PreToolUse(Bash) - refuse a git command that would DISCARD content existing nowhere else.

`git checkout <rev> -- <path>`, `git checkout -- <path>`, `git restore <path>`
and `git reset --hard` all overwrite the working file with a committed version.
Anything uncommitted in that file is gone, and gone from every session, because
this repo's primary tree is SHARED.

WHY THIS EXISTS, twice in one day on the same command and the same file:

  * 2026-09-03, session c38d3e5c: recovering an unrelated edit while their
    shell's cwd had silently reverted to the shared tree, they ran
    `git checkout -- scripts/pending_deploys.py .syndicate/lanes.md`. That
    destroyed this session's uncommitted lane block. It existed in NO commit on
    any branch (`git log --all -S` returned nothing) and no backup was newer.
    **They checked first**, and the check was the wrong shape: the diff read
    "0 deletions, all mine".
  * 2026-09-04, same command, recommended as the remedy for a stale `lanes.md`
    after a compaction. Caught by session cfcce46d BEFORE it ran. Measured in
    the shared tree at that moment: **16 uncommitted non-blank lines, all 16
    absent from `origin/main`'s `lanes.md` AND `lanes_history.md`** -- a live
    mid-edit claim transfer that exists nowhere else.

NOTHING GATED IT. Driven against every PreToolUse Bash hook in this repo on
2026-09-04, `git checkout origin/main -- .syndicate/lanes.md` was ALLOWED by
`commit-guard`, `ledger-commit-guard`, `deploy-guard` and `lane-postwrite-check`
alike. The guards here all watch what a commit RECORDS; none watches what a
command DESTROYS.

THE PREDICATE IS "EXISTS NOWHERE ELSE", NOT "HAS DELETIONS". A deletions count
answers "am I removing someone's existing lines" and is structurally blind to an
uncommitted ADDITION, which is what both incidents actually lost. So for every
path the command would overwrite, this compares the WORKING file against the
version the command installs AND against every rev in `_safe_revs`, and refuses
when a non-blank line is in the working file and in none of them.

"NOWHERE ELSE" MUST INCLUDE `origin/*`, NOT JUST `HEAD` -- a tree can be far
behind. Measured 2026-09-04 in the primary tree: it sat **183 commits behind
origin/main**, and `git restore --staged scripts/split_state.py` was BLOCKED
with "201 uncommitted line(s) in neither HEAD nor HEAD", while the working file
was the SAME BLOB as `origin/main` (`363b5528`) -- i.e. in a pushed commit that
had been verified an ancestor of origin/main minutes earlier. Nothing could have
been lost. This is the same over-reporting failure the `reset --hard` comment
below already records, and the same consequence: a guard that cries wolf on a
stale tree teaches sessions to override it reflexively, which is worse than
silence. So `HEAD` is only one entry in `_safe_revs`.

NOTE the check stays PER PATH (`<rev>:<path>`), so a line is only excused by a
copy of the SAME file elsewhere, never by a coincidental match in another one.

AND `_safe_revs` IS STILL ONLY FOUR REVS, SO A DEEP SWEEP BACKS IT. Content can
sit on a branch nobody named -- this repo has **610 refs**, ~170 of them stale
`origin/deploy/*`. `_deep_lines` searches EVERY committed version of the path
across ALL refs, newest first, and only for the lines `_safe_revs` could not
account for. Measured on this repo 2026-09-04:

    .syndicate/lanes.md    1,322 commits / 1,301 distinct blobs / 246 MB
    .syndicate/learnings.md   660 commits /   654 blobs / 177 MB
    an ordinary code file       3-4 commits

    exhaustive worst case (line really is nowhere)  11.6s / 13.4s
    both big ledger files in ONE command            18.7s, both exhaustive
    early exit (line found in history)               3.9s, 120 of 1301 blobs

The 30s budget is a REAL ceiling, not a soft one: every git call inside the
sweep takes its timeout from the time left on the shared deadline, so a slow
`rev-list` cannot push the total past it.

That is why the sweep is NOT unconditional: it runs only once the cheap revs
have failed, i.e. only when this hook is about to BLOCK anyway. The allow-path
costs exactly what it did before. Three git processes regardless of ref count --
`rev-list`, one `cat-file --batch-check` to map commits to blobs, then chunked
`cat-file --batch` reads that stop the moment every line is accounted for.

WHEN THE BUDGET RUNS OUT, IT BLOCKS AND SAYS THE SEARCH WAS TRUNCATED. It does
not silently downgrade to "nowhere else". `learnings.md`: an unknown must not
default onto the permissive branch -- and equally, a guard must not report a
partial search as an exhaustive one. The message says "all N committed
versions" only when it really read all of them.

WHY BLOCKING IS DEFENSIBLE HERE, when `lane-postwrite-check` deliberately only
warns: this command is precisely parseable. There is no guessing what
`git checkout -- <path>` does, unlike predicting a write from an arbitrary shell
string, so a false block needs a genuinely odd invocation rather than an
unlucky one. It also fails OPEN on every ambiguity, and the override is printed.

Override: `SYNDICATE_ALLOW_DISCARD=1 git checkout ...` (as a prefix on the
command itself), or `SYNDICATE_DISCARD_GUARD=off` to disable entirely.
`SYNDICATE_DISCARD_DEEP=off` skips the all-refs sweep (the guard then falls back
to `_safe_revs` alone and says so); `SYNDICATE_DISCARD_DEEP_BUDGET=<seconds>`
retunes it.
"""
import json
import os
import re
import subprocess
import sys
import time

OFF_ENV = "SYNDICATE_DISCARD_GUARD"
ALLOW_ENV = "SYNDICATE_ALLOW_DISCARD"
DEEP_ENV = "SYNDICATE_DISCARD_DEEP"
DEEP_BUDGET_ENV = "SYNDICATE_DISCARD_DEEP_BUDGET"

# Seconds for the all-refs sweep -- a TOTAL for the whole invocation, not per
# path. Per-path would let `git checkout HEAD -- a b c` cost three budgets; a
# hook that can stall a shell for an unbounded multiple of its own limit has no
# limit. Measured on this repo 2026-09-04, lanes.md (1,302 versions, 246 MB)
# exhaustive: 11.6s and 13.4s on two runs; both big ledger files in ONE command,
# 18.7s. 30 keeps this repo's worst real case EXHAUSTIVE with genuine headroom
# for growth -- at 20 it cleared by 1.3s, which is not headroom. Past the budget
# the sweep truncates and SAYS so, degrading honestly rather than silently.
# Only ever spent on a command otherwise about to be BLOCKED; the allow-path
# never enters here (measured 0.59s -> 0.60s across this whole change).
DEEP_BUDGET_S = 30.0
_CHUNK = 40                     # blobs per `cat-file --batch` round

# Only the discarding forms. `git checkout -b`, `git checkout <branch>` (no
# pathspec) and `git restore --staged` touch no working file content and are not
# matched.
#
# THAT LAST EXEMPTION USED TO BE DOCUMENTED AND NOT IMPLEMENTED. `_RESTORE`
# matched `git restore --staged` like any other restore, so an index-only
# command -- which cannot touch a working file at all -- was blocked as a
# discard. Measured 2026-09-04 in the primary tree. A docstring promising a
# behaviour the code lacks is worse than no docstring: it is read as evidence
# the case was handled. `_index_only()` implements it, and a test now makes it
# fire.
_CHECKOUT = re.compile(r"\bgit\s+(?:-[CcS]\s+\S+\s+)*checkout\b")
_RESTORE = re.compile(r"\bgit\s+(?:-[CcS]\s+\S+\s+)*restore\b")
_RESET_HARD = re.compile(r"\bgit\s+(?:-[CcS]\s+\S+\s+)*reset\b[^\n]*--hard\b")


def _git(root, *args, stdin=None, tolerant=False, timeout=30):
    """git stdout as UTF-8 text, or None.

    NO `text=True`. On Windows that decodes with the LOCALE codepage (cp1252
    here), and this ledger is full of em-dashes: `e2 80 94` comes back as
    `c3 a2 e2 82 ac`, which still LOOKS like a dash. Lines then fail to match
    their own committed copies and every comparison in this file inflates --
    measured while writing it, 16 genuinely-uncommitted lines reported as 431.
    `learnings.md` carries this as FORBIDDEN; the guard had it anyway.
    """
    try:
        if timeout is not None and timeout <= 0:
            return None                 # deadline already gone; do not start
        r = subprocess.run(["git", "-C", root] + list(args),
                           capture_output=True, timeout=timeout,
                           input=(stdin.encode("utf-8") if stdin else None))
        # `cat-file --batch*` exits non-zero when ANY spec is missing (a commit
        # where the path did not exist), while still emitting every line that
        # did resolve. Dropping that output would silently shrink the search.
        if r.returncode != 0 and not tolerant:
            return None
        return r.stdout.decode("utf-8", "replace")
    except Exception:
        return None


def _lines(text):
    return set(l.strip() for l in (text or "").splitlines() if l.strip())


# `git restore -S` / `-SW`; `-W` (or neither flag) means the working tree is
# touched and the command CAN discard.
_SHORT = re.compile(r"(?<!\S)-([A-Za-z]+)")


def _index_only(head):
    """True for a `git restore` that writes the INDEX and not the working tree.

    `--staged` alone is index-only. `--worktree`, `-W`, or neither flag given
    (restore defaults to --worktree) all reach the working file.
    """
    if not _RESTORE.search(head) or _CHECKOUT.search(head):
        return False
    body = head.split(" -- ", 1)[0]
    shorts = "".join(_SHORT.findall(body))
    staged = "--staged" in body or "S" in shorts
    worktree = "--worktree" in body or "W" in shorts
    return staged and not worktree


def _safe_revs(root, src):
    """Revs a line may live on and still not be "nowhere else", in order.

    `src` and `HEAD` are the minimum. `origin/main` and the branch's upstream
    are added because a shared tree runs BEHIND them routinely -- 183 commits
    behind, measured -- and content that is already pushed cannot be lost by
    overwriting a working file. Unresolvable revs are dropped, so this is
    offline-safe and never fetches; a hook must not touch the network.
    """
    out = []
    cands = [src, "HEAD", "origin/main"]
    up = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if up and up.strip():
        cands.append(up.strip())
    for rev in cands:
        if not rev or rev in out:
            continue
        if _git(root, "rev-parse", "--verify", "--quiet", rev + "^{commit}") is None:
            continue
        out.append(rev)
    return out


def _targets(head):
    """(source_rev, [paths]) the command would overwrite, or (None, []).

    Reads the INVOCATION LINE only. `command` is the whole Bash string with any
    heredoc body attached, and matching a path inside a commit message is a real
    bug this repo already paid for in `ledger-commit-guard`.
    """
    if _index_only(head):
        return (None, [])               # writes the index; no working file
    if _RESET_HARD.search(head):
        # THE SOURCE IS THE NAMED REV, NOT `HEAD`. `git reset --hard origin/main`
        # installs origin/main; comparing against HEAD instead made the message
        # read "in neither HEAD nor HEAD" and OVER-REPORTED -- it counted every
        # line HEAD lacks, including content that is safely on the very rev being
        # installed. Measured on its own author: 14 settings.json lines flagged
        # where the true figure against origin/main was 0. A guard that
        # over-reports trains people to override it, which is worse than silence.
        rest = head.split("reset", 1)[-1]
        revs = [t for t in rest.split()
                if t and not t.startswith('-') and t != '--']
        return ((revs[0] if revs else "HEAD"), None)
    if not (_CHECKOUT.search(head) or _RESTORE.search(head)):
        return (None, [])

    src = "HEAD"
    m = re.search(r"--source[= ](\S+)", head)
    if m:
        src = m.group(1)

    if " -- " in head:
        rest = head.split(" -- ", 1)[1]
        before = head.split(" -- ", 1)[0]
        # `git checkout origin/main -- path` names its source before the `--`.
        toks = [t for t in before.split() if t and not t.startswith("-")]
        if len(toks) >= 3 and toks[1] in ("checkout", "restore"):
            cand = toks[2]
            if _looks_like_rev(cand):
                src = cand
    else:
        # `git restore path` / `git checkout path` with no separator.
        rest = re.sub(r"\bgit\s+\S+", " ", head, count=1)
        rest = re.sub(r"(?<!\S)-\S+", " ", rest)
    paths = [t.strip("'\"") for t in rest.split()
             if t.strip("'\"") and not t.startswith("-")]
    return (src, paths)


def _looks_like_rev(tok):
    return bool(re.fullmatch(r"[0-9a-fA-F]{7,40}|HEAD[~^0-9]*|"
                             r"(?:origin/)?[A-Za-z0-9._/-]+", tok)) and "/" not in tok.rstrip("/") \
        or tok.startswith("origin/") or tok in ("HEAD",)


def _blob_ids(root, rel, deadline=None):
    """Distinct blob ids for `rel` across ALL refs, newest commit first.

    Two git processes, not one per ref: `rev-list --all -- <path>` gives the
    commits that touched it in reverse-chronological order, and a single
    `cat-file --batch-check` maps every `<commit>:<path>` to its blob. Dedup
    matters -- lanes.md has 1,322 commits but 1,301 distinct blobs, and the
    ledger files barely change in most of them.
    """
    # THE PER-CALL TIMEOUT MUST COME OFF THE SHARED DEADLINE, not be a fixed 30.
    # `rev-list --all` is the slowest single call here (3-5s measured, and it
    # grows with history), and it runs BEFORE the chunk loop's deadline check.
    # With a fixed timeout the true ceiling was budget + timeout, i.e. 60s for a
    # 30s budget -- exactly the "unbounded multiple of its own limit" this
    # module rejects one comment above. Now the deadline is the ceiling.
    left = (lambda: None) if deadline is None else (lambda: deadline - time.time())
    commits = (_git(root, "rev-list", "--all", "--", rel,
                    timeout=left()) or "").split()
    if not commits:
        return []
    out = _git(root, "cat-file", "--batch-check=%(objectname) %(objecttype)",
               stdin="".join("%s:%s\n" % (c, rel) for c in commits),
               tolerant=True, timeout=left()) or ""
    seen, ids = set(), []
    for line in out.splitlines():
        f = line.split()
        if len(f) == 2 and f[1] == "blob" and f[0] not in seen:
            seen.add(f[0])
            ids.append(f[0])
    return ids


def _deep_lines(root, rel, needed, deadline):
    """Account for `needed` against EVERY committed version of `rel`, all refs.

    `deadline` is an absolute time shared by every path in one invocation, so
    the whole hook is bounded rather than each path separately.

    Returns (still_missing, scanned, total, complete). `complete` is False when
    the deadline cut the search short -- the caller must not then claim the
    lines exist nowhere, only that it did not find them there.
    """
    if time.time() >= deadline:
        return set(needed), 0, 0, False
    ids = _blob_ids(root, rel, deadline)
    if not ids:
        # No versions found -- or the deadline killed the listing. Those are not
        # the same answer, and the permissive one must not stand in for the
        # unknown, so an expired deadline reports INCOMPLETE.
        return set(needed), 0, 0, time.time() < deadline
    missing, scanned = set(needed), 0
    for i in range(0, len(ids), _CHUNK):
        if time.time() >= deadline:
            return missing, scanned, len(ids), False
        part = ids[i:i + _CHUNK]
        body = _git(root, "cat-file", "--batch",
                    stdin="".join(b + "\n" for b in part), tolerant=True,
                    timeout=deadline - time.time())
        missing -= _lines(body)
        scanned += len(part)
        if not missing:
            break
    return missing, scanned, len(ids), True


def main():
    if os.environ.get(OFF_ENV, "").lower() == "off":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name", "") not in ("Bash", "PowerShell"):
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if os.environ.get(ALLOW_ENV) or ALLOW_ENV in command:
        return 0
    head = command.split(chr(10))[0]

    try:
        src, paths = _targets(head)
    except Exception:
        return 0                        # fail open on anything unparseable
    if src is None:
        return 0

    root = (payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR")
            or os.getcwd())
    if paths is None:
        out = _git(root, "diff", "--name-only")
        paths = [p for p in (out or "").split() if p]
    if not paths:
        return 0

    revs = _safe_revs(root, src)
    deep_on = os.environ.get(DEEP_ENV, "").lower() != "off"
    try:
        budget = float(os.environ.get(DEEP_BUDGET_ENV) or DEEP_BUDGET_S)
    except ValueError:
        budget = DEEP_BUDGET_S

    deadline = time.time() + budget
    doomed, scope = {}, {}
    for rel in paths:
        full = os.path.join(root, *rel.replace("\\", "/").split("/"))
        if not os.path.isfile(full):
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                working = _lines(fh.read())
        except OSError:
            continue
        gone = set(working)
        for rev in revs:
            gone -= _lines(_git(root, "show", "%s:%s" % (rev, rel)))
            if not gone:
                break
        if not gone:
            continue
        # Cheap revs could not account for these. Only NOW is the all-refs
        # sweep worth its seconds: we are otherwise about to block.
        if deep_on:
            gone, scanned, total, complete = _deep_lines(root, rel, gone, deadline)
            scope[rel] = ("all %d committed version(s) across every ref" % total
                          if complete else
                          "%d of %d committed version(s) -- SEARCH TRUNCATED, "
                          "raise %s" % (scanned, total, DEEP_BUDGET_ENV))
        else:
            scope[rel] = "%s only (%s=off)" % (", ".join(revs), DEEP_ENV)
        if gone:
            doomed[rel] = sorted(gone)

    if not doomed:
        return 0

    nl = chr(10)
    sys.stderr.write(
        "BLOCKED: this would DISCARD content that exists nowhere else." + nl + nl)
    for rel, gone in doomed.items():
        sys.stderr.write("%s  --  %d line(s) found in NO commit; searched %s:%s"
                         % (rel, len(gone), scope.get(rel, ", ".join(revs)), nl))
        for l in gone[:4]:
            sys.stderr.write("    " + l[:100] + nl)
        if len(gone) > 4:
            sys.stderr.write("    ... and %d more%s" % (len(gone) - 4, nl))
        sys.stderr.write(nl)
    sys.stderr.write(nl.join([
        "This tree is SHARED. Those lines may be another session's mid-edit work.",
        "Unless a search above says TRUNCATED, they are in no commit on any ref",
        "at all -- so being merely BEHIND origin/main does not explain them --",
        "and a checkout does not archive them, it deletes them.",
        "",
        "A DELETIONS COUNT WILL NOT SHOW THIS. The lines above are ADDITIONS; a",
        "diff reading '0 deletions, all mine' is the exact check that failed when",
        "this command destroyed a lane block on 2026-09-03.",
        "",
        "Preserve first, then re-run:",
        "  git stash push -- <path>        # keeps it, restorable",
        "  git diff HEAD -- <path> > /tmp/pending.patch",
        "or commit the work, or ask the session that owns it.",
        "",
        "Override once you have read the lines above:",
        "  " + ALLOW_ENV + "=1 <your command>",
        "Disable: " + OFF_ENV + "=off",
        "",
    ]))
    return 2


sys.exit(main())
