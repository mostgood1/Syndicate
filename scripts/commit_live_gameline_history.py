"""Commit the live-gameline accuracy history rows to origin/main, append-only.

Run by the nightly `live-gameline-accuracy-snapshot` task after its captures.

WHY NOT `git add` + `git commit` IN THE PRIMARY TREE. The primary tree lags
origin/main by tens to hundreds of commits and its index is shared by every
session. Committing its copy of history.jsonl would either conflict on land or,
worse, replace origin's copy with a stale one and drop rows another session had
already pushed. So this never commits the primary tree's file. It:

  1. fetches origin and checks out origin/main in a throwaway sparse worktree
     (reports/live_gameline_accuracy only);
  2. appends every row of the SOURCE copy that origin's copy does not already
     hold -- exact line match, in the source's order -- and never removes or
     rewrites an origin row (the file is append-only; other sessions write it);
  3. refuses to commit unless `git diff --numstat` reads 0 deletions;
  4. commits that one file and pushes HEAD:main, retrying from a fresh
     origin/main if the push loses a race;
  5. removes the worktree whatever happened.

Exit codes: 0 committed (or nothing to commit), 2 git failure, 3 the diff was
not append-only (refused), 4 push lost the race on every attempt.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

REL = "reports/live_gameline_accuracy/history.jsonl"
PRIMARY = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate")
TRAILER = "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"


def _rows(text: str) -> list[str]:
    return [line.rstrip("\r\n") for line in text.splitlines() if line.strip()]


def rows_to_append(origin_text: str, source_text: str) -> list[str]:
    """Source rows origin lacks, in source order. Duplicates within the source
    are kept only once; origin rows are never touched."""
    have = set(_rows(origin_text))
    out = []
    for line in _rows(source_text):
        if line not in have:
            out.append(line)
            have.add(line)
    return out


def append_rows(path: Path, rows: list[str]) -> None:
    raw = path.read_bytes() if path.exists() else b""
    with open(path, "ab") as fh:
        if raw and not raw.endswith(b"\n"):
            fh.write(b"\n")
        for line in rows:
            fh.write((line + "\n").encode("utf-8"))


class GitError(RuntimeError):
    pass


def _git(*args, cwd: Path, check=True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GitError("git %s -> %d: %s" % (" ".join(args), proc.returncode,
                                             (proc.stderr or proc.stdout).strip()))
    return proc


def _deletions(worktree: Path) -> int:
    out = _git("diff", "--numstat", "--", REL, cwd=worktree).stdout.strip()
    if not out:
        return 0
    return sum(int(line.split("\t")[1]) for line in out.splitlines())


def run(repo: Path, source: Path, *, remote="origin", branch="main",
        attempts=3, dry_run=False) -> int:
    source_text = source.read_text(encoding="utf-8") if source.exists() else ""
    worktree = Path(tempfile.mkdtemp(prefix="gameline-history-commit-"))
    worktree.rmdir()          # `git worktree add` wants to create it
    added = False
    try:
        for attempt in range(1, attempts + 1):
            _git("fetch", "-q", remote, cwd=repo)
            if not added:
                _git("worktree", "add", "-q", "--detach", "--no-checkout", str(worktree),
                     "%s/%s" % (remote, branch), cwd=repo)
                added = True
                _git("sparse-checkout", "set", "--no-cone", "/" + REL, cwd=worktree)
            _git("checkout", "-q", "--detach", "-f", "%s/%s" % (remote, branch), cwd=worktree)

            target = worktree / REL
            origin_text = target.read_text(encoding="utf-8") if target.exists() else ""
            new = rows_to_append(origin_text, source_text)
            print("origin rows=%d source rows=%d to append=%d"
                  % (len(_rows(origin_text)), len(_rows(source_text)), len(new)), flush=True)
            if not new:
                print("NOTHING_TO_COMMIT -- origin already holds every source row", flush=True)
                return 0
            if dry_run:
                print("DRY_RUN -- would append %d row(s)" % len(new), flush=True)
                return 0

            target.parent.mkdir(parents=True, exist_ok=True)
            append_rows(target, new)
            dels = _deletions(worktree)
            if dels:
                print("REFUSED -- diff is not append-only (%d deletion(s))" % dels, flush=True)
                return 3

            _git("add", "--", REL, cwd=worktree)
            _git("commit", "-q", "-m",
                 "live_gameline_accuracy history: append %d row(s) (nightly task)\n\n%s"
                 % (len(new), TRAILER), cwd=worktree)
            push = _git("push", "-q", remote, "HEAD:%s" % branch, cwd=worktree, check=False)
            if push.returncode == 0:
                sha = _git("rev-parse", "--short", "HEAD", cwd=worktree).stdout.strip()
                print("COMMITTED %s -- %d row(s) appended, 0 deleted, pushed to %s/%s"
                      % (sha, len(new), remote, branch), flush=True)
                return 0
            print("push attempt %d/%d rejected: %s"
                  % (attempt, attempts, (push.stderr or push.stdout).strip()), flush=True)
        print("PUSH_FAILED -- lost the race %d times; rows stay in %s" % (attempts, source),
              flush=True)
        return 4
    except GitError as exc:
        print("GIT_FAILED %s" % exc, flush=True)
        return 2
    finally:
        if added:
            _git("worktree", "remove", "--force", str(worktree), cwd=repo, check=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=str(PRIMARY),
                    help="any checkout of the repo (used for fetch + worktree add)")
    ap.add_argument("--source", default=None,
                    help="the accumulating history file (default: <primary tree>/%s)" % REL)
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    source = Path(args.source) if args.source else PRIMARY / REL
    return run(Path(args.repo), source, remote=args.remote, branch=args.branch,
               dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
