#!/usr/bin/env python3
r"""Keep the shared PRIMARY checkout on origin/main: a guarded fast-forward that refuses rather than risk a file.

WHY THIS EXISTS. Every Claude Code session here loads its hooks from the primary checkout, not from its own
worktree. That covers the Claude hooks (`$CLAUDE_PROJECT_DIR/.claude/hooks/`), the git hooks
(`core.hooksPath` = the primary tree's `.githooks`), lane-guard's local claims and the session-start
digest. Sessions work in worktrees and land by rebase, so nothing ever moves the primary checkout: it
drifts, silently, and looks like a normal checkout while it does.
  * A hook landed on main is NOT LIVE until this tree moves (learnings 2026-10-14: a pre-commit fix sat inert
    on main while the tree was 891 commits behind).
  * The digest reads stale LEDGER content and prints facts main has already fixed (2026-10-05: "LEDGER OVER
    BUDGET" for trims already on main; 2026-11-13: "TREE 416 BEHIND" and "LANE ARCHIVE OWED: 21").
  * It was fast-forwarded BY HAND 12 times between 2026-09-15 and 2026-11-13, at 190-2,539 commits behind.
    The recipe is in auto-memory `project_primary_tree_fast_forward_recipe.md`; this script is its strict
    core, made safe to run with nobody watching.

WHY A PLAIN `git pull` IS NOT ENOUGH. The tree always holds OTHER sessions' uncommitted work: 5 modified +
594 untracked files on 2026-11-13, plus a scheduled writer on `reports/live_gameline_accuracy/history.jsonl`.
`git merge --ff-only` refuses when a modified file is in the way, which is safe but leaves the tree stuck. It
also OVERWRITES an IGNORED file the target adds, without asking. And `stash` / `reset --hard` are forbidden
here (the stash stack is shared by every worktree).

WHAT IT DOES, in order. Any refusal leaves HEAD and every file exactly as they were.
  1. The tree must be the MAIN worktree, on `main`, with no merge / rebase / cherry-pick / bisect in progress
     and no `index.lock`.
  2. `git fetch origin`. The target is origin/main as a full SHA, or `--target`, which must be on origin/main.
     HEAD must be an ancestor of the target. A HEAD with commits of its own is refused, never rewritten.
  3. 0 staged paths and 0 unmerged paths.
  4. BLOCKERS: locally modified files that the target also changes. Each must already hold the target's
     content (byte-equal, or equal once CRLF is read as LF), so resetting it loses nothing. Anything else is
     a unique local edit: REFUSED. A modified file the target deletes, or one deleted locally, is REFUSED.
  5. COLLISIONS: a path the target ADDS that already exists on disk, untracked or ignored. It must hold the
     target's content (the ff recreates it). Anything else is REFUSED; for an ignored file, git would
     otherwise overwrite it silently. So is a FILE where the target needs a directory, a directory where it
     adds a file, and a case-only rename (Windows reads both names as one file).
  6. --apply only:
     * re-check HEAD, staged and every blocker's and collision's sha256 immediately before acting;
     * back up the blockers and collisions, plus `git diff HEAD --binary` and the status, under
       `<git-common-dir>/syndicate/primary_tree_ff/backups/<stamp>/`, and re-hash the copies;
     * `git checkout HEAD -- <blockers>`, move the collisions into the backup, then `git merge --ff-only`;
     * ROLL BACK from the backup if anything fails.
  7. Verify: HEAD == target, 0 staged, each blocker equal to the target, every other modified file
     byte-identical, every untracked entry still present.

EVERY --apply RUN is recorded in `<git-common-dir>/syndicate/primary_tree_ff/status.json` (the latest) and
`runs.jsonl` (all of them). That directory is shared by every worktree and is never tracked. `--digest` reads
it and prints ONE line, only when a human is needed: the last run refused or failed, or no run for 24 h. A
dry run writes nothing.

USAGE
  py -3 scripts/primary_tree_ff.py              # dry run: what it would do, or why it refuses
  py -3 scripts/primary_tree_ff.py --apply      # do it
  py -3 scripts/primary_tree_ff.py --digest     # the session-start line (silent when nothing is owed)
  py -3 scripts/primary_tree_ff.py --spawn      # start a detached, Idle-priority --apply and return at once

Off switch: SYNDICATE_PRIMARY_FF=off. Every mode then exits 0 and does nothing.
Exit codes: 0 current / fast-forwarded / dry run clear; 3 refused; 4 skipped (off, locked, throttled);
5 failed (rolled back).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

OFF_ENV = "SYNDICATE_PRIMARY_FF"
LOCK_STALE_S = 15 * 60       # a run takes ~10-20 s on the real tree; a lock this old is a dead process
SPAWN_MIN_GAP_S = 10 * 60    # --spawn does nothing if a run STARTED this recently (bursts of session starts)
STALE_DIGEST_H = 24          # --digest speaks when the newest run is older than this
KEEP_BACKUPS = 30
BRANCH = "refs/heads/main"
REMOTE_REF = "refs/remotes/origin/main"

EXIT_OK, EXIT_REFUSED, EXIT_SKIPPED, EXIT_FAILED = 0, 3, 4, 5


class Refused(Exception):
    def __init__(self, reasons, info=None):
        super().__init__("; ".join(reasons))
        self.reasons = list(reasons)
        self.info = dict(info or {})   # head / target / behind, when known, so a refusal still says how far


class GitError(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------
# git and file helpers
# ---------------------------------------------------------------------------------------------------------
def _git(tree, *args, binary=False, ok=(0,), timeout=300):
    r = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, timeout=timeout,
                       stdin=subprocess.DEVNULL)
    if r.returncode not in ok:
        raise GitError("git %s -> rc %d: %s" % (" ".join(args[:3]), r.returncode,
                                                r.stderr.decode("utf-8", "replace").strip()[:300]))
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def _rc(tree, *args):
    return subprocess.run(["git", "-C", str(tree), *args], capture_output=True, timeout=120,
                          stdin=subprocess.DEVNULL).returncode


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def same_content(disk, blob):
    """Equal bytes, or equal once CRLF is read as LF (core.autocrlf checks text out as CRLF)."""
    return disk == blob or disk.replace(b"\r\n", b"\n") == blob.replace(b"\r\n", b"\n")


def _abs_git_path(tree, flag):
    out = _git(tree, "rev-parse", "--path-format=absolute", flag).strip()
    return Path(out)


def _norm(p):
    return os.path.normcase(os.path.realpath(str(p)))


def _common_dir(tree):
    """The git common dir WITHOUT a subprocess when it can be read off disk: `--digest` runs on every
    session start, and `git rev-parse` there cost ~300 of 400 ms on the primary tree (measured 11-13)."""
    dotgit = Path(tree) / ".git"
    if dotgit.is_dir():
        return dotgit
    try:
        text = dotgit.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            gd = Path(text[len("gitdir:"):].strip())
            gd = gd if gd.is_absolute() else (Path(tree) / gd)
            rel = (gd / "commondir").read_text(encoding="utf-8").strip()
            cd = Path(rel) if Path(rel).is_absolute() else (gd / rel)
            return cd.resolve()
    except OSError:
        pass
    return _abs_git_path(tree, "--git-common-dir")


def state_dir_for(tree):
    return _common_dir(tree) / "syndicate" / "primary_tree_ff"


def default_tree():
    here = Path(__file__).resolve().parents[1]
    if (here / ".git").is_dir():      # this copy IS the main checkout (the session-start case): no git call
        return here
    sys.path.insert(0, str(here))
    try:
        from scripts._primary_tree import primary_tree
        return Path(primary_tree(here))
    except Exception:  # noqa: BLE001
        return here


def _utc(now=None):
    return (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------------------------------------
# reading the tree
# ---------------------------------------------------------------------------------------------------------
def dirty(tree):
    """{staged, modified, untracked, unmerged}: lists of repo-relative paths, from ONE porcelain call."""
    out = _git(tree, "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=normal",
               "--ignore-submodules=all", binary=True)
    res = {"staged": [], "modified": [], "untracked": [], "unmerged": []}
    for ent in out.split(b"\0"):
        if len(ent) < 4:
            continue
        x, y, path = chr(ent[0]), chr(ent[1]), ent[3:].decode("utf-8", "surrogateescape")
        if x == "?":
            res["untracked"].append(path)
        elif x == "!":
            continue
        elif "U" in (x, y) or (x, y) in (("A", "A"), ("D", "D")):
            res["unmerged"].append(path)
        else:
            if x != " ":
                res["staged"].append(path)
            if y != " ":
                res["modified"].append(path)
    return res


def delta(tree, head, target):
    """{path: status letter} for every path the fast-forward changes (no rename detection)."""
    out = _git(tree, "diff", "--name-status", "-z", "--no-renames", head, target, binary=True)
    parts = out.split(b"\0")
    res = {}
    i = 0
    while i + 1 < len(parts):
        st = parts[i].decode("ascii", "replace")
        if not st:
            i += 1
            continue
        res[parts[i + 1].decode("utf-8", "surrogateescape")] = st[0]
        i += 2
    return res


def _blob(tree, target, path):
    return _git(tree, "show", "%s:%s" % (target, path), binary=True)


def _in_progress(git_dir):
    names = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply",
             "index.lock")
    return [n for n in names if (git_dir / n).exists()]


# ---------------------------------------------------------------------------------------------------------
# the plan
# ---------------------------------------------------------------------------------------------------------
def plan(tree, target=None, fetch=True):
    """Every guard, read-only. Returns the plan dict, or raises Refused with every reason found."""
    tree = Path(tree)
    t0 = time.time()
    git_dir = _abs_git_path(tree, "--git-dir")
    common = _abs_git_path(tree, "--git-common-dir")
    if _norm(git_dir) != _norm(common):
        raise Refused(["%s is a LINKED worktree, not the main checkout" % tree])
    branch = _git(tree, "symbolic-ref", "-q", "HEAD", ok=(0, 1)).strip()
    if branch != BRANCH:
        raise Refused(["the main checkout is on %r, not %s" % (branch or "a detached HEAD", BRANCH)])
    busy = _in_progress(git_dir)
    if busy:
        raise Refused(["a git operation is in progress there: %s" % ", ".join(busy)])

    fetch_ok = None
    if fetch:
        fetch_ok = _rc(tree, "fetch", "-q", "origin") == 0
    origin = _git(tree, "rev-parse", "--verify", "-q", REMOTE_REF, ok=(0, 1)).strip()
    if not origin:
        raise Refused(["no %s to fast-forward to" % REMOTE_REF])
    if target:
        target = _git(tree, "rev-parse", "--verify", "-q", target + "^{commit}", ok=(0, 1)).strip()
        if not target:
            raise Refused(["--target does not name a commit"])
        if _rc(tree, "merge-base", "--is-ancestor", target, origin) != 0:
            raise Refused(["--target %s is not on origin/main" % target[:9]])
    else:
        target = origin
    head = _git(tree, "rev-parse", "HEAD").strip()

    p = {"tree": str(tree), "head": head, "target": target, "fetch_ok": fetch_ok, "behind": 0,
         "blockers": [], "collisions": [], "keep_modified": [], "untracked": [], "hashes": {},
         "delta_paths": 0}
    if head == target:
        p["elapsed_s"] = round(time.time() - t0, 1)
        return p
    if _rc(tree, "merge-base", "--is-ancestor", head, target) != 0:
        raise Refused(["HEAD %s has commits that are not on origin/main: not a fast-forward" % head[:9]],
                      info={"head": head, "target": target})
    p["behind"] = int(_git(tree, "rev-list", "--count", "%s..%s" % (head, target)).strip() or 0)

    d = dirty(tree)
    reasons = []
    if d["staged"]:
        reasons.append("%d staged path(s), e.g. %s" % (len(d["staged"]), d["staged"][0]))
    if d["unmerged"]:
        reasons.append("%d unmerged path(s), e.g. %s" % (len(d["unmerged"]), d["unmerged"][0]))

    ch = delta(tree, head, target)
    p["delta_paths"] = len(ch)
    modified = set(d["modified"])
    for path in sorted(modified & set(ch)):
        fp = tree / path
        if ch[path] == "D":
            reasons.append("the target deletes %s, which has local edits" % path)
            continue
        if not fp.is_file():
            reasons.append("%s is deleted (or not a file) locally and the target changes it" % path)
            continue
        if same_content(fp.read_bytes(), _blob(tree, target, path)):
            p["blockers"].append(path)
            p["hashes"][path] = _sha(fp)
        else:
            reasons.append("%s has local edits the target does not carry" % path)

    added = sorted(path for path, st in ch.items() if st == "A")
    deleted_low = {path.lower() for path, st in ch.items() if st == "D"}
    for path in added:
        if path.lower() in deleted_low:
            reasons.append("case-only rename to %s: do it by hand (Windows reads both names as one file)" % path)
            continue
        parts = path.split("/")
        # A file where the target needs a directory -- unless the target itself deletes that file (a tracked
        # file becoming a directory is the target's own change, and git handles it).
        clash = next(("/".join(parts[:i]) for i in range(1, len(parts))
                      if os.path.lexists(tree.joinpath(*parts[:i])) and not tree.joinpath(*parts[:i]).is_dir()
                      and ch.get("/".join(parts[:i])) != "D"),
                     None)
        if clash:
            reasons.append("a FILE sits at %s, where the target needs a directory" % clash)
            continue
        fp = tree.joinpath(*parts)
        if not os.path.lexists(fp):
            continue
        if fp.is_dir() or fp.is_symlink():
            reasons.append("a directory or link sits at %s, where the target adds a file" % path)
            continue
        if same_content(fp.read_bytes(), _blob(tree, target, path)):
            p["collisions"].append(path)
            p["hashes"][path] = _sha(fp)
        else:
            reasons.append("%s is on disk (untracked or IGNORED) and differs from the file the target adds" % path)

    if reasons:
        raise Refused(reasons, info={"head": head, "target": target, "behind": p["behind"],
                                     "delta_paths": len(ch)})
    p["keep_modified"] = sorted(modified - set(p["blockers"]))
    for path in p["keep_modified"]:
        fp = tree / path
        p["hashes"][path] = _sha(fp) if fp.is_file() else None
    p["untracked"] = d["untracked"]
    p["elapsed_s"] = round(time.time() - t0, 1)
    return p


# ---------------------------------------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------------------------------------
def _default_merge(tree, target):
    _git(tree, "merge", "--ff-only", "-q", target)


def _prune(backups):
    try:
        dirs = sorted(d for d in backups.iterdir() if d.is_dir())
    except OSError:
        return
    for d in dirs[:-KEEP_BACKUPS]:
        shutil.rmtree(d, ignore_errors=True)


def apply(p, state, merge=None):
    """Act on a plan. Raises Refused (nothing touched) or GitError/OSError (rolled back)."""
    tree = Path(p["tree"])
    merge = merge or _default_merge
    if p["head"] == p["target"]:
        return {}
    # Re-check immediately before acting: a scheduled writer or another session may have moved something
    # during the plan (history.jsonl has one).
    late = []
    if _git(tree, "rev-parse", "HEAD").strip() != p["head"]:
        late.append("HEAD moved during the plan")
    if _git(tree, "diff", "--cached", "--name-only"):
        late.append("something was staged during the plan")
    for path in p["blockers"] + p["collisions"]:
        fp = tree / path
        if not fp.is_file() or _sha(fp) != p["hashes"][path]:
            late.append("%s changed during the plan" % path)
    if late:
        raise Refused(late)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bdir = state / "backups" / ("%s_%s" % (stamp, p["head"][:9]))
    bdir.mkdir(parents=True, exist_ok=False)
    manifest = {"head": p["head"], "target": p["target"], "files": {}}
    for path in p["blockers"] + p["collisions"]:
        dst = bdir / "files" / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tree / path, dst)
        manifest["files"][path] = p["hashes"][path]
    (bdir / "diff_HEAD_binary.patch").write_bytes(_git(tree, "diff", "HEAD", "--binary", binary=True))
    (bdir / "status_porcelain.txt").write_bytes(_git(tree, "status", "--porcelain=v1", binary=True))
    (bdir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    bad = [path for path, h in manifest["files"].items() if _sha(bdir / "files" / path) != h]
    if bad:
        raise Refused(["backup copy does not re-hash: %s" % bad[:3]])

    moved = []
    try:
        if p["blockers"]:
            _git(tree, "checkout", "HEAD", "--", *p["blockers"])
        for path in p["collisions"]:
            os.remove(tree / path)
            moved.append(path)
        merge(tree, p["target"])
    except Exception:
        # ROLL BACK. Restoring a blocker only matters while HEAD has not moved; restoring a moved collision
        # is always right (the ff either did not run, or recreated the identical file).
        if _git(tree, "rev-parse", "HEAD").strip() == p["head"]:
            for path in p["blockers"]:
                shutil.copy2(bdir / "files" / path, tree / path)
        for path in moved:
            if not os.path.lexists(tree / path):
                shutil.copy2(bdir / "files" / path, tree / path)
        raise
    finally:
        _prune(state / "backups")
    return {"backup": str(bdir)}


def verify(p):
    tree = Path(p["tree"])
    problems = []
    head = _git(tree, "rev-parse", "HEAD").strip()
    if head != p["target"]:
        problems.append("HEAD is %s, not the target %s" % (head[:9], p["target"][:9]))
    if _git(tree, "diff", "--cached", "--name-only").strip():
        problems.append("paths are staged after the ff")
    for path in p["blockers"]:
        fp = tree / path
        if not fp.is_file() or not same_content(fp.read_bytes(), _blob(tree, p["target"], path)):
            problems.append("%s does not equal the target after the ff" % path)
    for path in p["keep_modified"]:
        fp = tree / path
        now = _sha(fp) if fp.is_file() else None
        if now != p["hashes"][path]:
            problems.append("%s CHANGED during the ff (it should be untouched)" % path)
    for path in p["untracked"]:
        if not os.path.lexists(tree / path.rstrip("/")):
            problems.append("untracked %s is gone after the ff" % path)
    return problems


# ---------------------------------------------------------------------------------------------------------
# lock, status, run
# ---------------------------------------------------------------------------------------------------------
def _lock(state):
    state.mkdir(parents=True, exist_ok=True)
    lp = state / "lock"
    for _ in range(2):
        try:
            fd = os.open(str(lp), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lp.stat().st_mtime > LOCK_STALE_S:
                    lp.unlink()
                    continue
            except OSError:
                pass
            return None
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps({"pid": os.getpid(), "at": _utc()}))
        return lp
    return None


def _write_status(state, rec):
    state.mkdir(parents=True, exist_ok=True)
    tmp = state / ("status.json.%d.tmp" % os.getpid())
    tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    os.replace(tmp, state / "status.json")
    with open(state / "runs.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def run(tree, do_apply=False, target=None, fetch=True, merge=None, state=None):
    """One run. Returns (exit_code, record). Only an --apply run that got past the lock writes status."""
    tree = Path(tree)
    if os.environ.get(OFF_ENV, "").strip().lower() == "off":
        return EXIT_SKIPPED, {"result": "skipped", "reasons": ["%s=off" % OFF_ENV]}
    state = Path(state) if state else state_dir_for(tree)
    rec = {"at": _utc(), "tree": str(tree), "mode": "apply" if do_apply else "dry_run"}
    lock = None
    if do_apply:
        lock = _lock(state)
        if lock is None:
            return EXIT_SKIPPED, dict(rec, result="skipped", reasons=["another run holds the lock"])
        (state / "last_attempt").write_text(rec["at"], encoding="utf-8")
    t0 = time.time()
    code = EXIT_OK
    try:
        try:
            p = plan(tree, target=target, fetch=fetch)
        except Refused as e:
            rec.update(e.info)
            rec.update(result="refused", reasons=e.reasons)
            code = EXIT_REFUSED
            return code, rec
        rec.update({k: p[k] for k in ("head", "target", "behind", "blockers", "collisions", "fetch_ok",
                                      "delta_paths")})
        if p["head"] == p["target"]:
            rec["result"] = "current"
            return code, rec
        if not do_apply:
            rec["result"] = "clear"
            return code, rec
        try:
            rec.update(apply(p, state, merge=merge))
        except Refused as e:
            rec.update(result="refused", reasons=e.reasons)
            code = EXIT_REFUSED
            return code, rec
        except Exception as e:  # noqa: BLE001  rolled back inside apply()
            rec.update(result="failed", reasons=["%s: %s (rolled back)" % (type(e).__name__, e)])
            code = EXIT_FAILED
            return code, rec
        problems = verify(p)
        if problems:
            rec.update(result="failed", reasons=["VERIFY: " + x for x in problems])
            code = EXIT_FAILED
        else:
            rec["result"] = "ff"
        return code, rec
    except Exception as e:  # noqa: BLE001  a git error or an unreadable file: record it, never crash a hook
        rec.update(result="failed", reasons=["%s: %s" % (type(e).__name__, e)])
        code = EXIT_FAILED
        return code, rec
    finally:
        rec["elapsed_s"] = round(time.time() - t0, 1)
        if lock is not None:
            try:
                _write_status(state, rec)
            finally:
                try:
                    lock.unlink()
                except OSError:
                    pass


def digest_line(state, now=None):
    """One line for the session-start digest, or "" when nothing needs a human."""
    try:
        rec = json.loads((Path(state) / "status.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  never ran: lane_census's "TREE N BEHIND" already covers drift
        return ""
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        at = dt.datetime.strptime(rec["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        age_h = (now - at).total_seconds() / 3600.0
    except Exception:  # noqa: BLE001
        age_h = None
    age = "?" if age_h is None else ("%dm" % (age_h * 60) if age_h < 2 else "%.0fh" % age_h)
    if rec.get("result") in ("refused", "failed"):
        why = (rec.get("reasons") or ["?"])[0][:150]
        more = len(rec.get("reasons") or []) - 1
        return ("PRIMARY TREE NOT AUTO-UPDATED (%s %s ago, %s behind): %s%s -- py -3 scripts/primary_tree_ff.py"
                % (rec["result"], age, rec.get("behind", "?"), why, " (+%d more)" % more if more > 0 else ""))
    if age_h is not None and age_h > STALE_DIGEST_H:
        return "PRIMARY-TREE AUTO-FF last ran %s ago (%s) -- is its trigger still running?" % (age, rec.get("result"))
    return ""


def spawn(tree, delay, popen=None):
    """Start a detached, low-priority --apply after `delay` seconds; return at once. Throttled."""
    popen = popen or subprocess.Popen
    state = state_dir_for(tree)
    try:
        if time.time() - (state / "last_attempt").stat().st_mtime < SPAWN_MIN_GAP_S:
            return False
    except OSError:
        pass
    args = [sys.executable, str(Path(__file__).resolve()), "--apply", "--quiet", "--delay", str(delay),
            "--tree", str(tree)]
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
          "close_fds": True, "cwd": str(tree)}
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | IDLE_PRIORITY_CLASS: no console, survives the hook,
        # and yields the CPU to the fleet that shares this host.
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x00000040
    else:
        kw["start_new_session"] = True
    popen(args, **kw)
    return True


def _print(rec, as_json):
    if as_json:
        print(json.dumps(rec, indent=1))
        return
    head = "%s -> %s" % ((rec.get("head") or "?")[:9], (rec.get("target") or "?")[:9])
    print("primary_tree_ff: %s  [%s]  %s  behind %s  delta %s paths  %.1fs" % (
        rec.get("result", "?").upper(), rec.get("mode", "?"), head, rec.get("behind", "?"),
        rec.get("delta_paths", "?"), rec.get("elapsed_s") or 0.0))
    for k in ("blockers", "collisions"):
        if rec.get(k):
            print("  %s (identical to the target, reset/moved, backed up): %s" % (k, rec[k]))
    for r in rec.get("reasons") or []:
        print("  - " + r)
    if rec.get("fetch_ok") is False:
        print("  (fetch failed: used origin/main as last fetched)")
    if rec.get("backup"):
        print("  backup: " + rec["backup"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="fast-forward (default: dry run)")
    ap.add_argument("--target", help="an exact commit on origin/main (default: origin/main)")
    ap.add_argument("--tree", help="the main checkout (default: resolved like scripts/_primary_tree.py)")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--digest", action="store_true", help="print the session-start line, if any")
    ap.add_argument("--spawn", action="store_true", help="start a detached --apply and return")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds to wait before starting")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if os.environ.get(OFF_ENV, "").strip().lower() == "off":
        return EXIT_SKIPPED if not a.digest else EXIT_OK
    tree = Path(a.tree) if a.tree else default_tree()
    if a.digest:
        try:
            line = digest_line(state_dir_for(tree))
        except Exception:  # noqa: BLE001  fail open on the session-start path
            line = ""
        if line:
            print(line)
        return EXIT_OK
    if a.spawn:
        try:
            spawn(tree, a.delay or 20.0)
        except Exception:  # noqa: BLE001
            pass
        return EXIT_OK
    if a.delay:
        time.sleep(a.delay)
    code, rec = run(tree, do_apply=a.apply, target=a.target, fetch=not a.no_fetch)
    if not a.quiet:
        _print(rec, a.json)
    return code


if __name__ == "__main__":
    sys.exit(main())
