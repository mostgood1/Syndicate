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

Overrides:
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
# `git commit` but not `git commit-tree`, and not a commit inside another
# worktree via -C / --git-dir (those have their own index and are the
# documented safe recipe, so leave them alone).
COMMIT_RE = re.compile(r"(?:^|[;&|]|\s)git\s+(?:-c\s+\S+\s+)*commit(?![\w-])")
SCOPED_RE = re.compile(r"(?:^|\s)git\s+(?:-C\s+\S+|--git-dir(?:=|\s)\S+)")


def repo_root():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


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
    if not COMMIT_RE.search(cmd):
        return 0
    # An explicitly scoped git call uses another repo/index -- not our problem,
    # and it is the recipe the ledger tells sessions to use.
    if SCOPED_RE.search(cmd):
        return 0
    if os.environ.get(ALLOW_ENV):
        return 0
    if os.environ.get("GIT_INDEX_FILE"):
        # Isolated index: this is the safe recipe, by construction.
        return 0

    root = repo_root()
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

    reverts = [] if os.environ.get(REVERT_ALLOW_ENV) else staged_reverts(root, out)

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
        "Fix (index-only, cannot disturb any session's working-tree edits):",
        "  git restore --staged " + " ".join(affected[:8]),
        "",
        "Then commit through an ISOLATED index so this cannot recur:",
        "  export GIT_INDEX_FILE=$(mktemp -u /tmp/idx.XXXX)",
        "  git read-tree HEAD && git add -- <your paths> && git diff --cached --stat",
        "",
        "Overrides, if you genuinely mean it:",
        "  %s=1   untracking a file that stays on disk (`git rm --cached`)" % ALLOW_ENV,
        "  %s=1   a deliberate partial revert" % REVERT_ALLOW_ENV,
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
