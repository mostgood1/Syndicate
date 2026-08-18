"""One worktree per session, so `git add` stops being a global mutation.

THE PROBLEM THIS REMOVES. Every session shares one working tree and one git
index. `git add` writes that index for everybody, which is the root of a whole
family of incidents this repo has already paid for:

  * 4,993 staged deletions sat in the shared index while the working tree
    matched HEAD -- a bare `git commit` from ANY session would have un-shipped
    six files of `ask_the_syndicate` M1 work without touching one file on disk.
    `commit-guard.py` exists solely to catch this.
  * Hours later the same index staged the deletion of the ONLY copy of the
    pre-collapse ledger, plus truncations of two more files. Caught by
    inspection, not by any guard.
  * 2026-08-18: a working copy of `todo.md` would have dropped five open items
    (`#448`, `#449`, `#454`, `#455`, `#456`) to zero copies. Caught by a diff
    that was only run because something else looked odd.

Every one of those is the same bug: two sessions, one index. Git already solved
it -- `git worktree` gives each checkout its OWN index at
`.git/worktrees/<name>/index`. With a worktree per session, `git add -A` is
safe, cross-session staging accidents are structurally impossible rather than
caught by review, and `commit-guard.py` becomes belt-and-braces instead of the
only thing standing between a tidy and a silent revert.

THE COST, MEASURED, AND WHY IT IS SMALLER THAN IT LOOKS. Worktrees SHARE the
object store: the 1.83 GiB pack is not copied. The per-worktree cost is the
checkout alone. And 34,690 of 37,745 tracked files -- 92% -- are under `data/`,
which `CLAUDE.md` calls a cold-start safety net and "a lossy mirror", explicitly
NOT what production computed. So the default here excludes it: ~3,000 files
instead of ~37,700.

That exclusion is not only a size trick. It removes, structurally, the error
this repo keeps making -- drawing a conclusion about production from a local
`data/` tree of unknown vintage. A session that needs the mirror asks for it
with `--with-data` and thereby says so out loud.

    python scripts/session_worktree.py open --lane my-lane
    python scripts/session_worktree.py list
    python scripts/session_worktree.py land --lane my-lane --dry-run
    python scripts/session_worktree.py close --lane my-lane

STATUS: PROTOTYPE. `land` pushes to `main` and is the one command here that
changes anything shared; it refuses on a dirty tree and prints what it would do
under `--dry-run`. It REPORTS the ledger checkers rather than gating on them --
see `_run_checkers`.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path(os.environ.get("SYNDICATE_SESSION_ROOT") or r"C:/tmp/syndicate-sessions")
BRANCH_PREFIX = "session/"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")

# Everything except the artifact mirror. Non-cone mode: `/*` takes the root,
# `!/data/` drops the 34,690-file tree under it.
SPARSE_PATTERNS = ("/*", "!/data/")


def git(*args, cwd: Path | None = None, check: bool = False) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(cwd or REPO_ROOT),
                            capture_output=True, text=True, timeout=900)
    if check and result.returncode != 0:
        sys.stderr.write((result.stderr or result.stdout).strip() + "\n")
        raise SystemExit(f"FATAL: git {' '.join(args)} failed ({result.returncode})")
    return result


def _slug(value: str) -> str:
    if not SLUG_RE.match(value):
        raise SystemExit(f"FATAL: '{value}' is not a lane slug (lowercase, digits, hyphens)")
    return value


def _path_for(slug: str, root: Path) -> Path:
    return root / slug


def _worktrees() -> list[dict]:
    """Parse `git worktree list --porcelain` into records."""
    out, records, current = git("worktree", "list", "--porcelain").stdout, [], {}
    for line in out.splitlines():
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        records.append(current)
    return records


def _session_worktrees() -> list[dict]:
    return [w for w in _worktrees()
            if w.get("branch", "").startswith("refs/heads/" + BRANCH_PREFIX)]


def cmd_open(args) -> int:
    slug = _slug(args.lane)
    path, branch = _path_for(slug, args.root), BRANCH_PREFIX + slug

    if path.exists():
        print(f"already exists: {path}\n  cd {path}")
        return 0

    print("fetching origin ...")
    git("fetch", "origin", check=True)

    exists = git("rev-parse", "--verify", "--quiet", branch).returncode == 0
    path.parent.mkdir(parents=True, exist_ok=True)

    add = ["worktree", "add", "--no-checkout", str(path)]
    add += [branch] if exists else ["-b", branch, "origin/main"]
    git(*add, check=True)

    if not args.with_data:
        # Non-cone: cone mode cannot express "everything except this directory".
        git("sparse-checkout", "init", "--no-cone", cwd=path, check=True)
        git("sparse-checkout", "set", *SPARSE_PATTERNS, cwd=path, check=True)
    git("checkout", cwd=path, check=True)

    # `ls-files` lists the INDEX, which sparse-checkout does not shrink -- it
    # reported 37,745 while 3,055 files were on disk. `-t` tags each entry: H =
    # present, S = skipped by sparse-checkout. Count what actually exists.
    tagged = git("ls-files", "-t", cwd=path).stdout.splitlines()
    count = sum(1 for line in tagged if line.startswith("H "))
    skipped = sum(1 for line in tagged if line.startswith("S "))
    print(f"\nworktree ready   {path}")
    print(f"branch           {branch}" + ("" if exists else "  (new, from origin/main)"))
    print(f"files on disk    {count:,}"
          + (f"   ({skipped:,} skipped -- data/ excluded)" if skipped else ""))
    print(f"index            its own -- `git add` here touches no other session")
    if not args.with_data:
        print("\nNOTE: data/ is absent by design. It is a lossy mirror, never evidence")
        print("about production. Re-run with --with-data if you genuinely need it.")
    print(f"\n  cd {path}")
    return 0


def _lane_claims(slug: str) -> set[str]:
    """Paths `lanes.md` says this lane holds, via lane-guard's own parser.

    Reusing the hook rather than re-parsing: it is what actually enforces claims,
    and a second parser that disagreed would hand a session the wrong file list
    at exactly the moment it is deciding what to commit.
    """
    import importlib.util
    guard_path = REPO_ROOT / ".claude" / "hooks" / "lane-guard.py"
    spec = importlib.util.spec_from_file_location("lane_guard_adopt", guard_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass                                   # it is a hook: importing runs it
    if not hasattr(module, "_claims"):
        return set()
    lanes = (REPO_ROOT / ".syndicate" / "lanes.md").read_text(encoding="utf-8-sig")
    return {p for s, p in module._claims(lanes) if s == slug}


def cmd_adopt(args) -> int:
    """What is uncommitted in the PRIMARY tree that belongs to this lane.

    THE MIGRATION HAZARD THIS EXISTS FOR. Moving to per-session worktrees does
    not carry the primary tree's uncommitted work with it. Measured 2026-08-18 at
    adoption: 47 modified tracked files there, including real code from at least
    two lanes -- NHL hockeysim (`loaders.py`, `projection.py`,
    `test_hockeysim_loaders.py`) and the MLB/NBA/WNBA vendor trees -- plus new
    untracked files. A session that opens a fresh worktree and carries on leaves
    all of it behind, in a tree everyone has agreed to stop looking at.

    So: land your files from the primary tree FIRST, then open a worktree. This
    lists what is yours by lane claim, and says plainly that it cannot see
    untracked files or work your lane never declared.
    """
    slug = _slug(args.lane)
    claims = _lane_claims(slug)
    dirty = [l[3:] for l in git("status", "--porcelain").stdout.splitlines() if l[:2] != "??"]
    untracked = [l[3:] for l in git("status", "--porcelain").stdout.splitlines() if l[:2] == "??"]

    def owned(path):
        rel = path.replace("\\", "/").strip('"')
        return any(rel == c or rel.endswith("/" + c) or c.endswith("/" + rel) for c in claims)

    mine = sorted(p for p in dirty if owned(p))
    others = len(dirty) - len(mine)

    print(f"lane {slug}: {len(claims)} claimed path(s) in lanes.md")
    print(f"primary tree: {len(dirty)} modified, {len(untracked)} untracked\n")
    if mine:
        print(f"YOURS by lane claim ({len(mine)}) -- land these before you move:")
        for p in mine:
            print(f"  {p}")
        print("\n  git add " + " ".join(mine[:6]) + (" ..." if len(mine) > 6 else ""))
        print("  git commit      # then: session_worktree.py open --lane " + slug)
    else:
        print("nothing modified in the primary tree matches this lane's claims.")
    print(f"\n{others} modified path(s) belong to other lanes or no lane. NOT yours to commit.")
    print(f"{len(untracked)} untracked path(s) are INVISIBLE to this check -- a new file")
    print("your lane never declared in `Files:` cannot be matched to you. Check")
    print("`git status --porcelain` yourself before concluding you are done.")
    return 0


def cmd_list(args) -> int:
    sessions = _session_worktrees()
    if not sessions:
        print("no session worktrees")
        return 0
    print(f"{'lane':<32} {'ahead':>5} {'behind':>6} {'dirty':>5}  path")
    for w in sessions:
        path = Path(w["worktree"])
        branch = w.get("branch", "").replace("refs/heads/", "")
        lane = branch[len(BRANCH_PREFIX):]
        counts = git("rev-list", "--left-right", "--count", f"origin/main...{branch}").stdout.split()
        behind, ahead = (counts + ["?", "?"])[:2]
        dirty = len(git("status", "--porcelain", cwd=path).stdout.splitlines()) if path.exists() else "?"
        print(f"{lane:<32} {ahead:>5} {behind:>6} {dirty:>5}  {path}")
    return 0


def _run_checkers(cwd: Path) -> None:
    """Report ledger coherence. REPORTS, does not gate -- deliberately.

    Both checkers exit non-zero on the repo TODAY (6 duplicated todo ids, 7
    duplicated OPEN lanes, 3 lanes open-and-filed). Gating `land` on them would
    block every session on day one over damage they did not cause, and a gate
    that blocks all work is removed within the afternoon. Report, name the tool,
    let the human decide.
    """
    for script, label in ((("scripts/lane_identity_check.py",), "lanes"),
                          (("scripts/todo_id_reconcile.py", "--no-history"), "todo ids")):
        result = subprocess.run([sys.executable, *script], cwd=str(cwd),
                                capture_output=True, text=True, timeout=900)
        state = "clean" if result.returncode == 0 else "PROBLEMS"
        print(f"  ledger/{label:<9} {state}"
              + ("" if result.returncode == 0 else f"   (run {script[0]})"))


def cmd_land(args) -> int:
    slug = _slug(args.lane)
    path, branch = _path_for(slug, args.root), BRANCH_PREFIX + slug
    if not path.exists():
        raise SystemExit(f"FATAL: no worktree at {path} -- open it first")

    dirty = git("status", "--porcelain", cwd=path).stdout.splitlines()
    if dirty:
        print(f"REFUSING: {len(dirty)} uncommitted change(s) in {path}")
        for line in dirty[:10]:
            print(f"  {line}")
        print("\nCommit or discard them first. Landing a dirty tree is how a")
        print("half-finished edit reaches main under someone else's message.")
        return 1

    git("fetch", "origin", check=True)
    ahead = git("rev-list", "--count", f"origin/main..{branch}", cwd=path).stdout.strip()
    if ahead in ("", "0"):
        print(f"nothing to land -- {branch} has no commits beyond origin/main")
        return 0

    print(f"landing {ahead} commit(s) from {branch}")
    print("  rebasing onto origin/main ...")
    rebase = git("rebase", "origin/main", cwd=path)
    if rebase.returncode != 0:
        print("\nREBASE CONFLICT -- resolve it in the worktree, then re-run land:")
        print(f"  cd {path}")
        print((rebase.stdout + rebase.stderr).strip()[:600])
        return 1

    _run_checkers(path)

    if args.dry_run:
        print(f"\n--dry-run: would push {branch} -> main")
        print(git("log", "--oneline", f"origin/main..{branch}", cwd=path).stdout.rstrip())
        return 0

    push = git("push", "origin", f"{branch}:main", cwd=path)
    if push.returncode != 0:
        print("\nPUSH REJECTED -- origin/main moved again. Re-run land; the rebase")
        print("is idempotent and this is expected with several sessions active.")
        print((push.stderr or push.stdout).strip()[:400])
        return 1
    print(f"\npushed {branch} -> main")
    print((push.stderr or "").strip()[-200:])
    return 0


def cmd_close(args) -> int:
    slug = _slug(args.lane)
    path, branch = _path_for(slug, args.root), BRANCH_PREFIX + slug
    if not path.exists():
        print(f"nothing to close at {path}")
        git("worktree", "prune")
        return 0

    dirty = git("status", "--porcelain", cwd=path).stdout.splitlines()
    git("fetch", "origin")
    unlanded = git("rev-list", "--count", f"origin/main..{branch}", cwd=path).stdout.strip()

    if (dirty or unlanded not in ("", "0")) and not args.force:
        print(f"REFUSING to close {slug}:")
        if dirty:
            print(f"  {len(dirty)} uncommitted change(s)")
        if unlanded not in ("", "0"):
            print(f"  {unlanded} commit(s) not on origin/main")
        print("\nLand them, or pass --force to discard. Nothing here is recoverable")
        print("from another session -- this worktree's index is its own.")
        return 1

    # `git worktree remove` fails on this machine when anything still holds a
    # handle under the checkout -- OneDrive's scanner and a just-exited python
    # both do. Observed twice at adoption: "Permission denied", then exit 255.
    # Falling back to a plain delete + prune is safe because at this point the
    # refusal checks above have already passed: the tree is clean and its
    # commits are on origin/main, so there is nothing in it that git needs.
    removed = git("worktree", "remove", "--force", str(path))
    if removed.returncode != 0:
        shutil.rmtree(path, ignore_errors=True)
        if path.exists():
            print(f"could not delete {path} -- something is holding it open.")
            print("Close anything using it and re-run; the branch is left intact.")
            return 1
        print(f"note: `git worktree remove` failed ({removed.returncode}); "
              "deleted the directory and pruned instead.")
    git("branch", "-D", branch)
    git("worktree", "prune")
    print(f"closed {slug}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                    help=f"where session worktrees live (default {DEFAULT_ROOT})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("open", help="create this session's worktree")
    p.add_argument("--lane", required=True)
    p.add_argument("--with-data", action="store_true",
                   help="check out data/ too (+34,690 files); say why in your lane")
    p.set_defaults(func=cmd_open)

    p = sub.add_parser("adopt", help="what this lane must land from the primary tree first")
    p.add_argument("--lane", required=True)
    p.set_defaults(func=cmd_adopt)

    p = sub.add_parser("list", help="show session worktrees")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("land", help="rebase onto origin/main and push")
    p.add_argument("--lane", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_land)

    p = sub.add_parser("close", help="remove the worktree and its branch")
    p.add_argument("--lane", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_close)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
