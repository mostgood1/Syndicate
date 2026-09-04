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

WHY BLOCKING IS DEFENSIBLE HERE, when `lane-postwrite-check` deliberately only
warns: this command is precisely parseable. There is no guessing what
`git checkout -- <path>` does, unlike predicting a write from an arbitrary shell
string, so a false block needs a genuinely odd invocation rather than an
unlucky one. It also fails OPEN on every ambiguity, and the override is printed.

Override: `SYNDICATE_ALLOW_DISCARD=1 git checkout ...` (as a prefix on the
command itself), or `SYNDICATE_DISCARD_GUARD=off` to disable entirely.
"""
import json
import os
import re
import subprocess
import sys

OFF_ENV = "SYNDICATE_DISCARD_GUARD"
ALLOW_ENV = "SYNDICATE_ALLOW_DISCARD"

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


def _git(root, *args):
    """git stdout as UTF-8 text, or None.

    NO `text=True`. On Windows that decodes with the LOCALE codepage (cp1252
    here), and this ledger is full of em-dashes: `e2 80 94` comes back as
    `c3 a2 e2 82 ac`, which still LOOKS like a dash. Lines then fail to match
    their own committed copies and every comparison in this file inflates --
    measured while writing it, 16 genuinely-uncommitted lines reported as 431.
    `learnings.md` carries this as FORBIDDEN; the guard had it anyway.
    """
    try:
        r = subprocess.run(["git", "-C", root] + list(args),
                           capture_output=True, timeout=20)
        if r.returncode != 0:
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
    doomed = {}
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
        if gone:
            doomed[rel] = sorted(gone)

    if not doomed:
        return 0

    nl = chr(10)
    sys.stderr.write(
        "BLOCKED: this would DISCARD content that exists nowhere else." + nl + nl)
    for rel, gone in doomed.items():
        sys.stderr.write("%s  --  %d uncommitted line(s), on none of %s:%s"
                         % (rel, len(gone), ", ".join(revs), nl))
        for l in gone[:4]:
            sys.stderr.write("    " + l[:100] + nl)
        if len(gone) > 4:
            sys.stderr.write("    ... and %d more%s" % (len(gone) - 4, nl))
        sys.stderr.write(nl)
    sys.stderr.write(nl.join([
        "This tree is SHARED. Those lines may be another session's mid-edit work.",
        "They are on none of the revs listed above -- including origin/main, so",
        "being merely BEHIND does not explain them -- and a checkout does not",
        "archive them, it deletes them.",
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
