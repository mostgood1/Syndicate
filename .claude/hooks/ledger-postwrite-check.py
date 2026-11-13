#!/usr/bin/env python3
"""PostToolUse hook - surfaces a broken LEDGER FILE at WRITE time.

Generalises `lanes-postwrite-check.py`, which this replaces, from `lanes.md` to
all three files the ledger's invariants are defined over: `lanes.md`, `state.md`
and `learnings.md`. The predicates live in `ledger_invariants.py` so the
commit-boundary guard enforces exactly the same set.

THE GAP IT FILLS. `ledger-append-guard.py` (PreToolUse) sees only
`Edit|Write|MultiEdit`, so a Bash write is invisible to it. `ledger-commit-guard.py`
catches the same damage but only when someone COMMITS, which can be an hour
later. `check_lane_invariants.py` / `state_key_check.py` run at session start,
far too late. In between, a broken file sits in the SHARED tree being read by
every other session.

IT WARNS, IT CANNOT BLOCK -- PostToolUse runs after the write. The damage exists
either way; the point is that nobody builds on top of it for an hour.

~FREE ON EVERY CALL, because it runs after EVERY Bash command: it stats the
tracked files first and parses NOTHING unless a (mtime, size) changed. State
lives in the OS temp dir keyed by repo path, never in the repo -- a hook that
littered the tree it guards would be caught by its own siblings.

That budget is why the tree is found by a FILESYSTEM WALK and not by
`git rev-parse --show-toplevel`, which is what the sibling guards use: measured
on Windows, the git subprocess is 41ms per Bash call against 0.0ms for the walk,
for the identical answer. Watching two trees instead of one costs ~6ms total on
top of interpreter startup (106ms measured end-to-end, ~100ms of it Python
booting). `commit-guard.py` records the same lesson from the other direction --
5.3s of per-path subprocesses, batched down to 3 spawns -- because a slow guard
gets switched off, which `learnings.md` calls a quieter way of crying wolf.

REPORTS ON TRANSITION, NOT ON STATE. Firing on every call while a file is broken
is the "a warning that always fires is ignored" failure `session-start.sh`
already documents. It speaks when a file BECOMES broken, or breaks again after
changing, and is silent otherwise -- including when the breakage is another
session's and has already been reported once.

IT CHECKS EVERY TREE THIS SESSION COULD HAVE WRITTEN -- the worktree the command
ran in AND the primary checkout -- fixed 2026-08-20. It previously resolved only
`CLAUDE_PROJECT_DIR`, which is the PRIMARY tree, while the Bash command it is
reacting to runs in the session's own linked worktree
(`scripts/session_worktree.py`). Both halves of that were wrong:

  IT WAS BLIND WHERE IT WAS MOST NEEDED. A Bash write is the ONLY thing this
  hook exists to catch, and a worktree session's Bash writes land in the
  worktree's `.syndicate/`. Those files were never stat'ed, so a session could
  break its own `lanes.md` from Bash and hear nothing from any of the three
  guards -- `ledger-append-guard` does not see Bash, this did not see the
  worktree, and `ledger-commit-guard` only speaks at commit time.

  IT BLAMED THE WRONG SESSION. Watching only the shared primary tree means the
  file changes under sessions that did not touch it, and every one of them
  reported "BROKEN by a write just now". Observed 2026-08-20: this fired at a
  session whose command was a `grep`, about duplicate lane blocks another
  session had written earlier. The wording asserted a causal link the hook
  cannot establish -- it sees a (mtime, size) change, never an author -- so it
  now says a file CHANGED AND IS BROKEN, and names the tree.

State is per-tree (`_state_path` keys on the absolute root), so the worktree and
the primary tree dedupe independently and one cannot silence the other.

FAILS OPEN on anything unexpected. Override: `SYNDICATE_LEDGER_POSTCHECK=off`.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from ledger_invariants import TRACKED, violations
except Exception:
    sys.exit(0)
try:
    from ledger_bytes import LEDGER_DIRS, REMEDY, describe, introduced
except Exception:
    LEDGER_DIRS = None

OFF_ENV = "SYNDICATE_LEDGER_POSTCHECK"


def _state_path(root):
    key = hashlib.sha1(os.path.abspath(root).encode("utf-8")).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), f"syndicate-ledger-check-{key}.json")


# `_ledger_root` / `_roots` MOVED TO `hook_trees.py` 2026-09-03, verbatim, when
# `lane-postwrite-check.py` needed the identical answer. The docstring above
# still describes their behaviour because it is unchanged -- including the two
# measurements that shaped them (the 41 ms git subprocess this walk replaces,
# and `realpath` over `abspath` for the 8.3-short-name dedupe). They are shared
# rather than copied because `learnings.md` 2026-08-20 says a defect in what all
# the guards share must be fixed in a shared module or the next guard re-makes
# it, and WHICH TREE is the defect every hook in this directory has had.
#
# Aliased back to the private names so nothing else in this file changed.
from hook_trees import ledger_root as _ledger_root, roots as _roots


# ESCAPE DAMAGE (`ledger_bytes.py`, added 2026-11-13) is checked over EVERY
# ledger markdown file, not just TRACKED: the 11-13 repair found damaged paths
# in 36 files, most of them daily logs and findings files TRACKED never names.
#
# Same budget rules as above. The tree is walked with `os.scandir`, whose
# entries carry (mtime, size) without a stat call per file on Windows: 6.2 ms
# for 597 files, measured 11-13. Only a file whose (mtime, size) moved is read,
# and only then is HEAD's copy fetched (one `git show`) so that damage already
# COMMITTED never reports -- the same rule the commit guard applies.
#
# TWO CASES ARE SEEDED, NOT CHECKED, both to keep a single call bounded:
#   * the first sighting of a tree (no state yet) -- 597 reads + 597 `git show`
#     would be ~25 s on one Bash call;
#   * more than _BYTES_MAX_CHANGED files moving in one call, which is a
#     checkout, a fast-forward or a rebase, not a hand-written append.
# Damage that lands in either window is still refused at commit.
_BYTES_KEY = "__escape_damage__"
_BYTES_MAX_CHANGED = 20


def _ledger_files(root):
    """{rel: [mtime_ns, size]} for every markdown file under LEDGER_DIRS."""
    out = {}

    def walk(path, rel):
        try:
            it = os.scandir(path)
        except OSError:
            return
        with it:
            for e in it:
                r = rel + "/" + e.name
                try:
                    if e.is_dir(follow_symlinks=False):
                        walk(e.path, r)
                    elif e.name.endswith(".md"):
                        st = e.stat(follow_symlinks=False)
                        out[r] = [int(st.st_mtime_ns), st.st_size]
                except OSError:
                    continue

    for d in LEDGER_DIRS:
        walk(os.path.join(root, *d.split("/")), d)
    return out


def _head_blob(root, rel):
    try:
        r = subprocess.run(["git", "-C", root, "show", f"HEAD:{rel}"],
                           capture_output=True, timeout=10)
        return r.stdout if r.returncode == 0 else b""
    except Exception:
        return b""


def _scan_bytes(root, prev):
    """(report, state) -- report is [(rel, [(what, how)])] like `violations`.

    State is {rel: [mtime_ns, size, digest]}; digest is "" for clean, None for
    seeded-but-unread, else a hash of the introduced findings, so the same
    damage reports once and a CHANGE in the damage reports again.
    """
    now = _ledger_files(root)
    if not isinstance(prev, dict):
        return [], {r: s + [None] for r, s in now.items()}
    state, changed = {}, []
    for r, s in now.items():
        old = prev.get(r)
        if isinstance(old, list) and len(old) == 3 and old[:2] == s:
            state[r] = old
        else:
            changed.append(r)
            state[r] = s + [None]
    if len(changed) > _BYTES_MAX_CHANGED:
        return [], state
    report = []
    for r in changed:
        try:
            with open(os.path.join(root, *r.split("/")), "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        bad = introduced(data, _head_blob(root, r))
        digest = ""
        if bad:
            keys = repr(sorted((f.kind, f.line) for f in bad))
            digest = hashlib.sha1(keys.encode("utf-8", "replace")).hexdigest()[:16]
        before = prev.get(r)
        state[r][2] = digest
        if bad and not (isinstance(before, list) and len(before) == 3 and before[2] == digest):
            shown = "\n".join("    " + describe(f) for f in bad[:8])
            more = f"\n    ... and {len(bad) - 8} more" if len(bad) > 8 else ""
            report.append((r, [(f"{len(bad)} NEW escape-damaged character(s), not in "
                                f"HEAD's copy:\n{shown}{more}", REMEDY)]))
    return report, state


def _scan(root):
    """(violations, state_written) for one tree. Never raises."""
    spath = _state_path(root)
    try:
        with open(spath, encoding="utf-8") as fh:
            prev = json.load(fh)
    except Exception:
        prev = {}
    if not isinstance(prev, dict):
        prev = {}

    report, new_state = [], dict(prev)
    for rel in TRACKED:
        path = os.path.join(root, *rel.split("/"))
        try:
            st = os.stat(path)
            sig = [int(st.st_mtime_ns), st.st_size]
        except OSError:
            continue
        # THE CHEAP EXIT: this file did not change, so do not read it.
        if prev.get(rel, {}).get("sig") == sig:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                bad = violations(rel, fh.read())
        except Exception:
            continue
        new_state[rel] = {"sig": sig, "ok": not bad}
        if bad:
            report.append((rel, bad))

    if LEDGER_DIRS is not None:
        try:
            dmg, new_state[_BYTES_KEY] = _scan_bytes(root, prev.get(_BYTES_KEY))
            report.extend(dmg)
        except Exception:
            pass

    if new_state != prev:
        try:
            with open(spath, "w", encoding="utf-8") as fh:
                json.dump(new_state, fh)
        except Exception:
            pass
    return report


def main():
    if os.environ.get(OFF_ENV, "").lower() == "off":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name", "") not in ("Bash", "PowerShell"):
        return 0

    findings = []
    for root in _roots(payload):
        try:
            for rel, bad in _scan(root):
                findings.append((root, rel, bad))
        except Exception:
            continue

    if not findings:
        return 0

    # NOT "a write just now": this hook sees a (mtime, size) change, never an
    # author. On the shared primary tree the writer is very often another
    # session, and claiming otherwise sent people looking through their own
    # command for a write that was not there.
    sys.stderr.write("LEDGER FILE BROKEN -- a ledger file CHANGED and now "
                     "fails its invariants or carries\nnew escape damage. "
                     "The write already happened; this is a "
                     "warning, not a block. It may have\nbeen another session: the "
                     "check sees the change, not who made it.\n\n")
    for root, rel, bad in findings:
        sys.stderr.write(f"{rel}   (in {root})\n")
        for what, how in bad:
            sys.stderr.write(f"  * {what}\n{how}\n")
        sys.stderr.write("\n")
    sys.stderr.write(
        "These files are read by every other session and the lane system's\n"
        "exclusivity rests on lanes.md, so this is worth fixing before anything else.\n"
        "Fix it in the tree named above -- running a cleanup in the WRONG tree\n"
        "rewrites another session's ledger.\n"
        "A commit touching the affected file will be refused until it is clean.\n"
        f"Silence: {OFF_ENV}=off\n")
    return 2


sys.exit(main())
