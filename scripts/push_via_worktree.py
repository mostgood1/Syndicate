"""Publish specific commits to origin/<branch> via a throwaway worktree.

WHY THIS EXISTS. Local `main` in this repo carries other sessions' commits, so
`git push` is never scoped to your own work. The established workaround is to
cherry-pick onto `origin/main` in a temporary worktree and push that. Done by
hand it has failed the same way four times in one session:

    cd /tmp/wt && git cherry-pick $(git rev-parse HEAD)

`$(git rev-parse HEAD)` is evaluated AFTER the `cd`, so it resolves the
WORKTREE's head and cherry-picks a commit onto itself. Git reports success, the
payload is empty, and `git push` says "Everything up-to-date" -- a silent no-op
that looks exactly like a successful publish.

This script removes the failure by construction: every SHA is resolved in the
main repository BEFORE any worktree exists, and an empty payload is a hard
error rather than a quiet success.

    py -3 scripts/push_via_worktree.py --commit 6a9b1440
    py -3 scripts/push_via_worktree.py --commit a1b2c3d --commit e4f5a6b
    py -3 scripts/push_via_worktree.py --commit HEAD --dry-run
    py -3 scripts/push_via_worktree.py --commit HEAD --only .syndicate

Refuses, loudly, when:
  * a SHA does not resolve, or resolves to something already upstream
  * a cherry-pick conflicts (it stops; resolve by hand and push yourself)
  * the resulting payload is empty
  * --only is given and the payload touches anything outside those prefixes

Read-only until the final push, and --dry-run never pushes at all.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd or REPO), capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            "git %s failed (%d):\n%s%s" % (" ".join(args), result.returncode,
                                           result.stdout, result.stderr)
        )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", action="append", required=True,
                        help="commit to publish; repeatable, applied in order")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--only", action="append", default=[],
                        help="path prefix the payload must stay within (repeatable)")
    parser.add_argument("--dry-run", action="store_true",
                        help="do everything except the push")
    args = parser.parse_args()

    # THE FIX: resolve every SHA here, in the main repo, before a worktree
    # exists. Nothing below re-resolves a symbolic name.
    resolved: list[tuple[str, str]] = []
    for ref in args.commit:
        try:
            sha = git("rev-parse", "--verify", "%s^{commit}" % ref)
        except RuntimeError:
            print("ERROR: %r does not resolve to a commit" % ref, file=sys.stderr)
            return 2
        subject = git("log", "-1", "--format=%s", sha)
        resolved.append((sha, subject))

    git("fetch", "origin", args.branch, "-q")
    upstream = git("rev-parse", "origin/%s" % args.branch)
    print("origin/%s is %s" % (args.branch, upstream[:8]))
    for sha, subject in resolved:
        print("  will publish %s  %s" % (sha[:8], subject[:72]))
        # `--is-ancestor` answers by exit code and prints nothing, so read the
        # code directly rather than its (always empty) stdout.
        already = subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, upstream],
            cwd=str(REPO), capture_output=True).returncode == 0
        if already:
            print("ERROR: %s is already on origin/%s -- nothing to publish"
                  % (sha[:8], args.branch), file=sys.stderr)
            return 2

    with tempfile.TemporaryDirectory(prefix="pvw-") as tmp:
        wt = Path(tmp) / "wt"
        git("worktree", "add", "--detach", str(wt), upstream)
        try:
            for sha, subject in resolved:
                result = subprocess.run(["git", "cherry-pick", sha],
                                        cwd=str(wt), capture_output=True, text=True)
                if result.returncode != 0:
                    conflicts = git("diff", "--name-only", "--diff-filter=U", cwd=wt,
                                    check=False)
                    print("ERROR: cherry-pick of %s stopped." % sha[:8], file=sys.stderr)
                    if conflicts:
                        print("Conflicts:\n  %s" % conflicts.replace("\n", "\n  "),
                              file=sys.stderr)
                    print("\nResolve it yourself -- an automated union-merge here is how a\n"
                          "newer upstream note gets silently reverted. The worktree is\n"
                          "removed on exit; re-run after deciding.", file=sys.stderr)
                    return 1

            stat = git("diff", "--stat", "%s..HEAD" % upstream, cwd=wt)
            names = git("diff", "--name-only", "%s..HEAD" % upstream, cwd=wt)

            # The silent-no-op guard. This is the failure the script exists for.
            if not names.strip():
                print("ERROR: payload is EMPTY -- nothing would be pushed.\n"
                      "This is the signature of a commit cherry-picked onto itself.\n"
                      "Nothing was pushed.", file=sys.stderr)
                return 1

            if args.only:
                stray = [n for n in names.splitlines()
                         if not any(n.startswith(p.rstrip("/")) for p in args.only)]
                if stray:
                    print("ERROR: payload leaves --only %s:\n  %s"
                          % (args.only, "\n  ".join(stray)), file=sys.stderr)
                    return 1

            print("\npayload:\n%s" % stat)

            if args.dry_run:
                print("\n--dry-run: not pushing.")
                return 0

            # Re-check the race between our fetch and now.
            git("fetch", "origin", args.branch, "-q", cwd=wt)
            if subprocess.run(["git", "merge-base", "--is-ancestor",
                               "origin/%s" % args.branch, "HEAD"],
                              cwd=str(wt)).returncode != 0:
                print("ERROR: origin/%s moved while we worked. Nothing pushed; re-run."
                      % args.branch, file=sys.stderr)
                return 1

            print(git("push", "origin", "HEAD:%s" % args.branch, cwd=wt) or "pushed.")
            print("origin/%s is now %s"
                  % (args.branch, git("rev-parse", "HEAD", cwd=wt)[:8]))
            return 0
        finally:
            subprocess.run(["git", "worktree", "remove", str(wt), "--force"],
                           cwd=str(REPO), capture_output=True)
            subprocess.run(["git", "worktree", "prune"], cwd=str(REPO),
                           capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
