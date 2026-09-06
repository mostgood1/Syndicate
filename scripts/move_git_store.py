#!/usr/bin/env python3
"""Relocate this repo's `.git` store off OneDrive, and repoint every worktree.

WHY THIS EXISTS `[2026-09-05, lane git-out-of-onedrive]`. The repo lives at
`C:\\Users\\<user>\\OneDrive\\Coding\\Syndicate`, so OneDrive's Cloud Files
filter manages `.git` as well as the working tree. Measured 2026-09-05: every
directory under `.git/worktrees/` carried `ReadOnly + ReparsePoint + PINNED`,
and the `logs`/`refs` FILES inside each carried `ReadOnly` too. That makes
`git worktree remove` half-fail -- it deletes the contents, then cannot delete
the metadata -- which leaves BOTH a stale registration and an empty husk
directory. 36 dead registrations and 16 husks had accumulated, and 36 of them
were invisible to `git worktree list` because a missing `gitdir` file hides an
entry from the listing while it still occupies `.git/worktrees/`.

Windows honours `ReadOnly` on FILES, not on directories, and `attrib -R /S /D`
did NOT clear it (118 before, 118 after). What works is `Remove-Item -Force`,
because `-Force` overrides `ReadOnly` itself. That is a workaround for the
symptom; this script addresses the cause.

WHAT IT DOES NOT DO, and read this before running it. Moving `.git` leaves the
WORKING TREE in OneDrive, including `.syndicate/` -- which also carries
`ReadOnly + ReparsePoint + PINNED`. The ledger churn (a CRLF rewrite warning on
every append) and OneDrive arbitrating writes to the ledger are UNCHANGED by
this script. If the goal is to end the whole class, the repo itself has to leave
OneDrive; this only takes the git store out of the blast radius.

THE DANGEROUS PART IS NOT THE MOVE, IT IS CONCURRENCY. Worktree pointers are
ABSOLUTE:

    <worktree>/.git                      -> "gitdir: <repo>/.git/worktrees/<name>"
    <repo>/.git/worktrees/<name>/gitdir  -> "<worktree>/.git"

so the store cannot move without rewriting the first of those for every
worktree (81 of them as of 2026-09-05). Any git command running in any session
during the move can see a half-moved store. This script therefore REFUSES to
run unless the tree looks quiet, and every check is a REFUSAL rather than a
warning.

USAGE

    py -3 scripts/move_git_store.py --target C:/gitstore/Syndicate.git
    py -3 scripts/move_git_store.py --target C:/gitstore/Syndicate.git --apply

Dry run by default, on purpose: it prints the exact rewrite for all worktrees,
validates every one, and touches nothing. `--apply` additionally requires that
the preflight is CLEAR.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys

# A move is only safe with no git command running anywhere in the repo. These
# are the states that prove one IS running, or that the tree is mid-operation.
_INFLIGHT = (
    "index.lock", "HEAD.lock", "config.lock",
    "MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "BISECT_LOG",
    "rebase-merge", "rebase-apply",
)


def _run(args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _git_dir(repo: pathlib.Path) -> pathlib.Path:
    """The REAL store, following a `gitdir:` pointer file if one is already there."""
    g = repo / ".git"
    if g.is_dir():
        return g
    if g.is_file():
        txt = g.read_text(encoding="utf-8", errors="replace").strip()
        if txt.startswith("gitdir:"):
            return pathlib.Path(txt.split(":", 1)[1].strip())
    raise SystemExit(f"no .git found at {repo}")


def worktree_pointers(repo: pathlib.Path, store: pathlib.Path,
                      new_store: pathlib.Path | None = None):
    """[(worktree_path, its .git file, current text, required text)] for every worktree.

    `new_store` is where the store is GOING; the required text is computed from
    it, not from `store`. Passing the current store here is what the first cut
    of this function did, and the dry run printed 84 rewrites whose `from` and
    `to` were identical -- i.e. `--apply` would have "rewritten" every pointer
    to the value it already had and left all 84 worktrees pointing into
    OneDrive after the store had moved out from under them. Defaulting to
    `store` is therefore only correct for the read-only baseline call.

    Derived from `.git/worktrees/<name>/gitdir`, which names the worktree's own
    `.git` FILE -- not from `git worktree list`, because a registration whose
    `gitdir` file is missing is hidden from the listing. That asymmetry is
    exactly what let 36 dead entries accumulate unseen, so this reads the
    directory.
    """
    dest = new_store if new_store is not None else store
    out = []
    wt_root = store / "worktrees"
    if not wt_root.is_dir():
        return out
    for entry in sorted(wt_root.iterdir()):
        gitdir_file = entry / "gitdir"
        if not gitdir_file.is_file():
            out.append((None, None, None, None, entry.name, "no gitdir file (dead registration)"))
            continue
        wt_git = pathlib.Path(gitdir_file.read_text(encoding="utf-8", errors="replace").strip())
        cur = wt_git.read_text(encoding="utf-8", errors="replace").strip() if wt_git.is_file() else None
        want = f"gitdir: {(dest / 'worktrees' / entry.name).as_posix()}"
        out.append((wt_git.parent, wt_git, cur, want, entry.name, None))
    return out


def preflight(repo: pathlib.Path, store: pathlib.Path, target: pathlib.Path) -> list[str]:
    """Every reason this must not run right now. Empty list == CLEAR."""
    problems = []

    for name in _INFLIGHT:
        if (store / name).exists():
            problems.append(f"git operation IN FLIGHT: .git/{name} exists")

    st = _run(["git", "status", "--porcelain"], cwd=repo)
    dirty = [l for l in st.stdout.splitlines() if l[:2] != "??"]
    if dirty:
        problems.append(
            f"{len(dirty)} tracked file(s) modified -- other sessions are writing. "
            "A move under a live session can corrupt its index; wait for a quiet tree."
        )

    if target.exists() and any(target.iterdir()):
        problems.append(f"target {target} exists and is not empty")

    onedrive = os.environ.get("OneDrive", "")
    if onedrive and str(target).lower().startswith(onedrive.lower()):
        problems.append(f"target {target} is ITSELF inside OneDrive ({onedrive}) -- that fixes nothing")

    if target.drive.upper() != repo.drive.upper():
        problems.append(
            f"target is on {target.drive} but the repo is on {repo.drive}; a cross-volume "
            "move is a copy+delete, which is slower and not atomic. Prefer the same volume."
        )

    for wt_path, wt_git, cur, want, name, err in worktree_pointers(repo, store, target):
        if err:
            problems.append(f"worktree registration '{name}': {err} -- run `git worktree prune` first")
        elif cur is None:
            problems.append(f"worktree '{name}': its .git file {wt_git} is missing")
        elif not cur.startswith("gitdir:"):
            problems.append(f"worktree '{name}': .git file is not a gitdir pointer ({cur[:40]!r})")
    return problems


def baseline_heads(repo: pathlib.Path, store: pathlib.Path) -> dict[str, str]:
    """Every worktree's resolved HEAD BEFORE the move, so the move can be proven
    non-destructive afterwards rather than assumed to be."""
    heads = {}
    for wt_path, _g, _c, _w, name, err in worktree_pointers(repo, store):
        if err or wt_path is None:
            continue
        r = _run(["git", "rev-parse", "HEAD"], cwd=wt_path)
        heads[name] = r.stdout.strip() if r.returncode == 0 else f"UNRESOLVED({r.returncode})"
    r = _run(["git", "rev-parse", "HEAD"], cwd=repo)
    heads["(main worktree)"] = r.stdout.strip()
    return heads


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=os.environ.get("CLAUDE_PROJECT_DIR", "."))
    ap.add_argument("--target", required=True, help="new location for the git store, e.g. C:/gitstore/Syndicate.git")
    ap.add_argument("--apply", action="store_true", help="actually move (default: dry run)")
    args = ap.parse_args(argv)

    repo = pathlib.Path(args.repo).resolve()
    target = pathlib.Path(args.target).resolve()
    store = _git_dir(repo)

    print(f"repo   : {repo}")
    print(f"store  : {store}")
    print(f"target : {target}")

    pointers = worktree_pointers(repo, store, target)
    live = [p for p in pointers if p[5] is None]
    dead = [p for p in pointers if p[5] is not None]
    print(f"\nworktrees: {len(live)} live, {len(dead)} dead registration(s)")

    print("\n--- pointer rewrites this would perform ---")
    for wt_path, wt_git, cur, want, name, err in live[:5]:
        print(f"  {name}")
        print(f"      {wt_git}")
        print(f"      from: {cur}")
        print(f"      to  : {want}")
    if len(live) > 5:
        print(f"  ... and {len(live) - 5} more (all validated)")

    bad = [n for _p, _g, c, w, n, e in live if c == w]
    if bad:
        print(f"\n  NOTE: {len(bad)} pointer(s) already point at the target; they are left alone.")

    problems = preflight(repo, store, target)
    print("\n--- preflight ---")
    if problems:
        for p in problems:
            print(f"  REFUSE: {p}")
    else:
        print("  CLEAR")

    if not args.apply:
        print("\nDRY RUN. Nothing was touched. Re-run with --apply when preflight is CLEAR.")
        return 0 if not problems else 1

    if problems:
        print("\nREFUSING to move: preflight is not clear. Every item above is a real "
              "way this corrupts another session's work.")
        return 2

    before = baseline_heads(repo, store)
    print(f"\nbaseline: {len(before)} HEADs recorded")

    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"moving {store} -> {target} ...")
    shutil.move(str(store), str(target))

    (repo / ".git").write_text(f"gitdir: {target.as_posix()}\n", encoding="utf-8")
    print(f"wrote {repo / '.git'} -> gitdir: {target.as_posix()}")

    rewritten = 0
    for wt_path, wt_git, cur, want, name, err in live:
        new = f"gitdir: {(target / 'worktrees' / name).as_posix()}"
        wt_git.write_text(new + "\n", encoding="utf-8")
        rewritten += 1
    print(f"rewrote {rewritten} worktree pointer(s)")

    rep = _run(["git", "worktree", "repair"], cwd=repo)
    print(f"git worktree repair: exit {rep.returncode} {rep.stdout.strip()[:200]}")

    after = baseline_heads(repo, target)
    drift = {k: (before.get(k), after.get(k)) for k in before if before.get(k) != after.get(k)}
    print(f"\nverification: {len(after)} HEADs re-resolved, {len(drift)} mismatch(es)")
    for k, (b, a) in list(drift.items())[:10]:
        print(f"  MISMATCH {k}: before {b} after {a}")
    if drift:
        print("\nMOVE COMPLETED BUT VERIFICATION FAILED. The store is at the target and "
              "the pointers are rewritten; investigate before running anything else.")
        return 3
    print("\nOK: every worktree resolves to the same HEAD it did before the move.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
