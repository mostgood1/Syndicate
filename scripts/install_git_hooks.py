#!/usr/bin/env python3
"""Point this clone's git at `.githooks`, so ledger invariants run on EVERY commit.

    py -3 scripts/install_git_hooks.py          # report only
    py -3 scripts/install_git_hooks.py --apply

WHY A TRACKED DIRECTORY AND NOT `.git/hooks`. Hooks in `.git/hooks` are not
versioned, cannot be reviewed, and drift per clone. `core.hooksPath` points git
at a directory that lives in the repo, so the hook everyone runs is the hook in
the commit.

WHAT IT REFUSES TO DO. Setting `core.hooksPath` makes git ignore `.git/hooks`
ENTIRELY, so an existing hook there would stop running with nothing said. This
refuses rather than silently disabling someone's hook; move it into `.githooks/`
first. Sample files (`*.sample`) never run and are ignored here.

WORKTREES. `core.hooksPath` is written to the SHARED config, so one run covers
every `scripts/session_worktree.py` worktree of this clone -- 47 of them when
this was written, which is the point: the sessions that clobber the ledger are
worktrees, and they all read this one config.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

HOOKS_DIR = ".githooks"


def git(*args, root="."):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="set it even though .git/hooks holds real hooks")
    args = ap.parse_args(argv)

    rc, root = git("rev-parse", "--show-toplevel")
    if rc:
        print("not a git repository")
        return 2
    repo = pathlib.Path(root)
    if not (repo / HOOKS_DIR / "pre-commit").is_file():
        print(f"{HOOKS_DIR}/pre-commit is missing -- nothing to install")
        return 2

    _rc, current = git("config", "--get", "core.hooksPath", root=root)
    print(f"repo               {root}")
    print(f"core.hooksPath     {current or '(unset)'}")

    _rc, common = git("rev-parse", "--git-common-dir", root=root)
    existing = []
    common_path = (repo / common) if not pathlib.Path(common).is_absolute() else pathlib.Path(common)
    hooks_d = common_path / "hooks"
    if hooks_d.is_dir():
        existing = sorted(p.name for p in hooks_d.iterdir()
                          if p.is_file() and not p.name.endswith(".sample"))
    print(f"hooks in {hooks_d}: {len(existing)}{' -> ' + ', '.join(existing) if existing else ''}")

    if existing and not args.force:
        print("\nREFUSED: setting core.hooksPath makes git ignore those entirely.")
        print("Move them into .githooks/ first, or re-run with --force.")
        return 1

    if current == HOOKS_DIR:
        print("\nalready installed -- nothing to do")
        return 0
    if not args.apply:
        print(f"\nDRY RUN. Re-run with --apply to set core.hooksPath={HOOKS_DIR}")
        return 0

    rc, _ = git("config", "core.hooksPath", HOOKS_DIR, root=root)
    if rc:
        print("failed to set core.hooksPath")
        return 2
    _rc, now = git("config", "--get", "core.hooksPath", root=root)
    print(f"\nINSTALLED. core.hooksPath = {now}")
    print("Covers every worktree of this clone. Bypass a single commit with")
    print("  SYNDICATE_ALLOW_LEDGER_COMMIT=1 git commit ...   (or --no-verify)")
    return 0 if now == HOOKS_DIR else 2


if __name__ == "__main__":
    sys.exit(main())
