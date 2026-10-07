"""Which OPEN-lane claims a guard should enforce, and where each one came from.

WHY THIS EXISTS (lane `lane-guard-main-claims`, 2026-09-17). `lane-guard.py`
parsed ONLY the primary tree's `.syndicate/lanes.md`. That copy is shared by
every session, routinely hundreds of commits behind origin/main, and carries
large uncommitted edits, so it keeps claims that main has already released.
Measured the same day: it blocked `syndicate/blueprints/ops.py` on a claim main
had released the previous day, and `tests/test_artifact_publisher.py` on a
claim whose transfer was already on main. Its message never said which copy it
read, so one of those blocks could not be explained at all.

THE RULE. A claim is enforced when EITHER:

- it is on origin/main's `lanes.md` -- the committed truth every session lands
  to; or
- it was ADDED in the primary tree since the tree forked from origin/main
  (claims in the working copy that are absent from the fork point) -- a lane a
  session opened there and has not landed yet.

A claim that is only in the primary tree's shared history, and that main has
since released, is exactly the false block, and it is dropped.

THE SAME RULE GOVERNS THE EXEMPTIONS (lane `lane-guard-loan-main-text`,
2026-10-07). Loans and declared sections are read from lanes.md too, and they
must be read from the SAME view the claims came from. Measured 2026-10-07
~16:35 CT: lane `web-restart-healthz` held a user-approved loan of
`kalshi_board_join.py` recorded on origin/main (55547ac5). The claims came from
main; the loan check read the primary tree's copy, which lacked the borrower's
block entirely -- so the guard BLOCKED a write its own claim source permitted.
`effective_entries` gives the loan and section readers the main/fork/local view.

NEVER LESS STRICT THAN BEFORE WHEN GIT CANNOT ANSWER. If origin/main cannot be
read (no remote ref, git missing, a timeout), every primary-copy claim is
enforced exactly as it always was, and the source says why.

Parses are cached on disk keyed by the two commit ids, so an edit normally
costs two short git calls, not two 500 KB parses.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile

from lane_claims import _claims, _loan_entries, _section_entries

LANES_REL = ".syndicate/lanes.md"
_GIT_TIMEOUT_SECONDS = 8
_CACHE_VERSION = 2

# Every reader of lanes.md the guard decides with. A guard that blocks on one
# copy and exempts on another is wrong in exactly the window where they differ.
_EXTRACTORS = {
    "claims": _claims,  # (slug, path)
    "loans": _loan_entries,  # (borrower, path, lender)
    "sections": _section_entries,  # (slug, path, section)
}


def _git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} exited {result.returncode}")
    return result.stdout.decode("utf-8", errors="replace")


def _cache_path(root):
    digest = hashlib.sha1(os.path.abspath(str(root)).encode("utf-8")).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f"syndicate_lane_claims_{digest}.json")


def _entries_at(root, sha, kind, cache, texts):
    key = f"{_CACHE_VERSION}:{kind}:{sha}"
    if key in cache:
        return [tuple(item) for item in cache[key]]
    if sha not in texts:
        texts[sha] = _git(root, "show", f"{sha}:{LANES_REL}")
    items = sorted(set(_EXTRACTORS[kind](texts[sha])))
    cache[key] = [list(item) for item in items]
    return items


def _effective(root, primary_text, kind):
    """(main_set, local_added_set, info) for one reader of lanes.md.

    An entry counts when it is on origin/main, or was added in the primary tree
    since the tree forked from origin/main. Raises when git cannot answer; the
    callers then fall back to the primary copy.
    """
    primary = set(_EXTRACTORS[kind](primary_text))
    main_sha = _git(root, "rev-parse", "--verify", "-q", "refs/remotes/origin/main").strip()
    if not main_sha:
        raise RuntimeError("no origin/main ref")
    base_sha = _git(root, "merge-base", "HEAD", main_sha).strip()
    cache_file = _cache_path(root)
    try:
        with open(cache_file, encoding="utf-8") as handle:
            cache = json.load(handle)
        if not isinstance(cache, dict):
            cache = {}
    except Exception:
        cache = {}
    texts = {}
    main_set = set(_entries_at(root, main_sha, kind, cache, texts))
    base_set = set(_entries_at(root, base_sha, kind, cache, texts))
    # Two commit ids per run at most; drop anything older so the file stays small.
    wanted = {f"{_CACHE_VERSION}:{k}:{sha}" for k in _EXTRACTORS for sha in (main_sha, base_sha)}
    try:
        with open(cache_file, "w", encoding="utf-8") as handle:
            json.dump({k: v for k, v in cache.items() if k in wanted}, handle)
    except Exception:
        pass
    local_added = primary - base_set - main_set
    return main_set, local_added, {
        "mode": "main+local",
        "main": main_sha,
        "fork_point": base_sha,
        "main_" + kind: len(main_set),
        "local_added": len(local_added),
        "dropped_stale": len(primary & base_set - main_set),
    }


def effective_entries(root, primary_text, kind):
    """([entry, ...], info) for `kind` in ("loans", "sections"), under the same rule
    `effective_claims` enforces, with the same fallback to the primary copy.
    """
    try:
        main_set, local_added, info = _effective(root, primary_text, kind)
    except Exception as exc:
        reason = str(exc) or type(exc).__name__
        return sorted(set(_EXTRACTORS[kind](primary_text))), {"mode": "fallback", "reason": reason}
    return sorted(main_set | local_added), info


def effective_claims(root, primary_text):
    """([(slug, path, source), ...], info) for the guard to match against.

    `primary_text` is the primary tree's `lanes.md` as the guard already read it.
    `source` is a short human label naming where the claim came from.
    """
    try:
        main_claims, local_added, info = _effective(root, primary_text, "claims")
    except Exception as exc:
        reason = str(exc) or type(exc).__name__
        label = f"primary tree lanes.md (fallback: origin/main unreadable -- {reason})"
        primary = sorted(set(_claims(primary_text)))
        return [(slug, path, label) for slug, path in primary], {"mode": "fallback", "reason": reason}

    main_label = f"origin/main@{info['main'][:8]}"
    local_label = f"primary tree lanes.md, added since fork point {info['fork_point'][:8]} (not on origin/main)"
    entries = [(slug, path, main_label) for slug, path in sorted(main_claims)]
    entries += [(slug, path, local_label) for slug, path in sorted(local_added)]
    return entries, info
