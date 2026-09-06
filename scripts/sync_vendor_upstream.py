"""Pull upstream changes into `vendor/` without ever silently reverting a local patch.

WHY THIS NEEDS A BASELINE, which is the whole design.

`vendor/` holds partial copies of sibling repos with no shared git history, so a
file that differs from upstream is AMBIGUOUS: "upstream moved ahead" and "we
patched it locally" are the same observation. Guessing wrong in one direction
loses an upstream fix; guessing wrong in the other silently reverts ours.

That is not hypothetical. When this script was written, 4 of the 24 differing
code files held deletions made hours earlier, whose upstream PRs were still open.
A "take upstream" sync would have reverted five verified fixes and reported
success.

So a third input is recorded: `vendor/upstream_sync.json` stores, per vendored
file, the upstream blob hash AS OF THE LAST SYNC. With local / upstream /
baseline, the six states separate cleanly (see `classify`), and only ONE of them
is safe to apply automatically.

WHAT IT WILL NOT DO, by construction:
  * never deletes a local-only file -- 541 of them exist, mostly generated
    artifacts that live nowhere upstream;
  * never adds files we do not already vendor -- the trees are deliberate
    subsets (507 of upstream's 9,017 for `nba_betting_repo`), and pulling the
    rest would be a different decision;
  * never touches `data/` unless asked -- it is regenerated mirror output, and it
    accounts for 24 of the 48 differing files;
  * never writes at all without `--apply`. Report is the default.

Comparison is by git BLOB HASH, not working-tree bytes. The hash is over content
as git stores it, already EOL-normalised, so CRLF-vs-LF cannot produce a false
difference -- which matters because these trees are CRLF on Windows checkouts and
one file carries a BOM.

RESOLVING AN `UNCLASSIFIED` FILE. The question is whether our version is a
deliberate patch or just an old copy, and it has a mechanical answer: **does our
blob hash appear anywhere in that path's upstream history?** If it does, we are
merely behind and `--adopt-upstream` loses nothing. If it does not, our content
never existed upstream, so it is ours and `--keep-local` records that. Get the
history cheaply with `git log --format= --raw --no-abbrev <branch> -- <path>` on
a blobless clone -- `--raw` reads blob hashes out of the tree diff, whereas
`cat-file` on `<rev>:<path>` triggers a promisor fetch per revision.

Run against the 53 that existed on 2026-09-06, that test returned 53 ours, 0
stale, agreeing with a second check (Syndicate had committed to every one of them
after vendoring). All 53 are now recorded as `LOCAL_PATCH`.

Usage:
    python scripts/sync_vendor_upstream.py                      # report, all trees
    python scripts/sync_vendor_upstream.py --trees nhl          # one tree
    python scripts/sync_vendor_upstream.py --apply              # take UPSTREAM_AHEAD only
    python scripts/sync_vendor_upstream.py --apply --adopt-upstream <path> ...
    python scripts/sync_vendor_upstream.py --keep-local <path> ...   # ours; record it
    python scripts/sync_vendor_upstream.py --seed-baseline      # first run only
    python scripts/sync_vendor_upstream.py --json

Exit codes: 0 nothing to do / applied cleanly, 1 action needed (upstream ahead,
or a conflict), 2 the upstream clone could not be prepared.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "vendor" / "upstream_sync.json"

# Mirrors the mapping in CLAUDE.md's directory map. NHL's default branch is
# `master`; the other three are `main`.
TREES: dict[str, dict[str, str]] = {
    "nba": {"tree": "nba_betting_repo", "repo": "mostgood1/NBA-Betting", "branch": "main"},
    "wnba": {"tree": "wnba_betting_repo", "repo": "mostgood1/WNBA-Betting", "branch": "main"},
    "nhl": {"tree": "nhl_betting_repo", "repo": "mostgood1/NHL-Betting", "branch": "master"},
    "mlb": {"tree": "mlb_bettingv2", "repo": "mostgood1/MLB-BettingV2", "branch": "main"},
}

# Excluded unless --include-data. Regenerated artifact output, and the reason the
# raw differing-file count (48) is twice the code count (24).
DATA_PREFIXES = ("data/",)

# This script's own baseline lives under vendor/ and is ours, not upstream's.
SELF_OWNED = {"upstream_sync.json"}

IN_SYNC = "IN_SYNC"
UPSTREAM_AHEAD = "UPSTREAM_AHEAD"
LOCAL_PATCH = "LOCAL_PATCH"
CONFLICT = "CONFLICT"
UNCLASSIFIED = "UNCLASSIFIED"
LOCAL_ONLY = "LOCAL_ONLY"

ACTIONABLE = (UPSTREAM_AHEAD, CONFLICT, UNCLASSIFIED)


def classify(local: str | None, upstream: str | None, baseline: str | None) -> str:
    """The six states, from (local, upstream, baseline) blob hashes.

    Only UPSTREAM_AHEAD is safe to apply without a human looking at it.
    """
    if upstream is None:
        # Nothing upstream to sync from. Generated artifacts and models live here.
        return LOCAL_ONLY
    if local == upstream:
        return IN_SYNC
    if baseline is None:
        # No record of what we last took, so the difference cannot be attributed.
        # Deliberately NOT treated as "upstream ahead": defaulting an unknown onto
        # the permissive branch is how a guard silently does the wrong thing.
        return UNCLASSIFIED
    if local == baseline:
        return UPSTREAM_AHEAD  # we never touched it; upstream moved
    if upstream == baseline:
        return LOCAL_PATCH  # we changed it; upstream did not. KEEP.
    return CONFLICT  # both moved since the last sync


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def ls_tree(repo: Path, ref: str, prefix: str = "") -> dict[str, str]:
    """{path -> blob hash} for a ref, optionally scoped to a path prefix."""
    args = ["git", "-C", str(repo), "ls-tree", "-r", ref, "--format=%(objectname) %(path)"]
    if prefix:
        args.append(prefix)
    proc = run(args)
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if line.strip():
            sha, path = line.split(" ", 1)
            out[path] = sha
    return out


def prepare_upstream(cache: Path, repo: str, branch: str, offline: bool) -> Path | None:
    """Clone or refresh a bare-ish mirror of one upstream repo."""
    dest = cache / repo.replace("/", "__")
    if dest.exists():
        if not offline:
            fetch = run(["git", "-C", str(dest), "fetch", "--depth", "1", "origin", branch])
            if fetch.returncode != 0:
                print("  ! fetch failed for %s: %s" % (repo, fetch.stderr.strip()[:200]))
                return None
        return dest
    if offline:
        print("  ! %s not cached and --offline given" % repo)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    # `--filter=blob:none --no-checkout`. Comparison needs only blob HASHES,
    # which live in tree objects; CONTENT is needed solely for the few files
    # `--apply` writes, and those are fetched lazily.
    #
    # `--no-checkout` IS THE LOAD-BEARING HALF, and leaving it out is worse than
    # not filtering at all. `git clone` populates a working tree by default,
    # which needs every blob at that commit -- so a blobless clone fetches them
    # all back one request at a time, each landing in its own pack. Measured
    # 2026-09-06 with the filter but no `--no-checkout`: the four caches came to
    # **3.8 GB**, with MLB-BettingV2 alone at 2.6 GB against a repo GitHub
    # reports as 354 MB. The filter was working; the checkout undid it.
    clone = run(["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout",
                 "--branch", branch, "https://github.com/%s.git" % repo, str(dest)])
    if clone.returncode != 0:
        print("  ! clone failed for %s: %s" % (repo, clone.stderr.strip()[:200]))
        return None
    return dest


def load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        return {"version": 1, "trees": {}}
    with open(BASELINE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def save_baseline(data: dict) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BASELINE_PATH, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
        handle.write("\n")


def is_excluded(rel: str, include_data: bool) -> bool:
    if rel in SELF_OWNED:
        return True
    if not include_data and rel.startswith(DATA_PREFIXES):
        return True
    return False


def worktree_hashes(tree: str, rels: list[str]) -> dict[str, str]:
    """{rel -> blob hash of the file ON DISK}.

    Deliberately NOT `ls-tree HEAD`. The working tree is what `--apply` would
    overwrite, so it is what has to be compared: reading HEAD instead makes an
    UNCOMMITTED local edit invisible, and the script would then classify it
    IN_SYNC or UPSTREAM_AHEAD and destroy it. That is the exact failure this
    whole script exists to prevent, and an earlier revision had it.

    `hash-object --stdin-paths` batches the lot into one process and applies the
    same clean filter git would, so the hash is comparable with `ls-tree`'s.
    """
    root = REPO_ROOT / "vendor" / tree
    present = [rel for rel in rels if (root / rel).is_file()]
    if not present:
        return {}
    stdin = "\n".join(str(root / rel) for rel in present) + "\n"
    proc = subprocess.run(["git", "-C", str(REPO_ROOT), "hash-object", "--stdin-paths"],
                          input=stdin, capture_output=True, text=True, encoding="utf-8")
    hashes = [h.strip() for h in proc.stdout.splitlines() if h.strip()]
    if len(hashes) != len(present):
        raise RuntimeError("hash-object returned %d hashes for %d paths" % (len(hashes), len(present)))
    return dict(zip(present, hashes))


def survey(key: str, spec: dict, upstream_repo: Path, baseline: dict, include_data: bool) -> dict:
    tree = spec["tree"]
    prefix = "vendor/%s/" % tree
    # The vendored SET comes from what is tracked; the CONTENT compared comes
    # from disk.
    tracked = [p[len(prefix):] for p in ls_tree(REPO_ROOT, "HEAD", prefix)]
    local = worktree_hashes(tree, tracked)
    remote = ls_tree(upstream_repo, "FETCH_HEAD" if (upstream_repo / ".git" / "FETCH_HEAD").exists() else spec["branch"])
    base = baseline.get("trees", {}).get(tree, {}).get("files", {})

    rows = []
    for rel in sorted(local):
        if is_excluded(rel, include_data):
            continue
        state = classify(local[rel], remote.get(rel), base.get(rel))
        rows.append({
            "path": rel,
            "state": state,
            "local": local[rel],
            "upstream": remote.get(rel),
            "baseline": base.get(rel),
        })
    return {"key": key, "tree": tree, "repo": spec["repo"], "branch": spec["branch"],
            "rows": rows, "upstream_repo": str(upstream_repo),
            "n_local": len(local), "n_upstream": len(remote)}


def apply_row(tree: str, row: dict, upstream_repo: Path, branch: str) -> bool:
    """Overwrite the vendored file with upstream's blob, bytes for bytes.

    Read as BYTES, not text: these trees carry a BOM in at least one file and are
    CRLF on Windows checkouts, and round-tripping through a decode would rewrite
    both. `cat-file blob` gives the stored content verbatim.
    """
    proc = subprocess.run(["git", "-C", str(upstream_repo), "cat-file", "blob", row["upstream"]],
                          capture_output=True)
    if proc.returncode != 0:
        print("      ! could not read upstream blob for %s" % row["path"])
        return False
    dest = REPO_ROOT / "vendor" / tree / row["path"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_match_line_endings(proc.stdout, dest))
    return True


def _match_line_endings(blob: bytes, dest: Path) -> bytes:
    """Write with the line endings the file being replaced already used.

    `cat-file blob` returns git's STORED form, which is LF-normalised. These
    checkouts are CRLF (`core.autocrlf`), so writing the blob verbatim would flip
    one file to LF while its neighbours stay CRLF. Git itself does not care --
    the clean filter normalises on the way back in, so the tracked content and
    its hash are identical either way -- but leaving a mixed-ending tree behind
    is a confusing artefact of the tool rather than of the change.

    Binary files are left exactly as upstream stored them.
    """
    if b"\x00" in blob[:8000]:
        return blob
    try:
        existing = dest.read_bytes()
    except OSError:
        return blob
    if b"\r\n" not in existing:
        return blob
    return blob.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--trees", nargs="+", choices=sorted(TREES), default=sorted(TREES))
    p.add_argument("--apply", action="store_true", help="write UPSTREAM_AHEAD files (default is report only)")
    p.add_argument("--adopt-upstream", nargs="+", default=[], metavar="PATH",
                   help="also take upstream for these tree-relative paths, whatever their state")
    p.add_argument("--keep-local", nargs="+", default=[], metavar="PATH",
                   help="record that these paths hold a deliberate local patch: baseline := upstream's "
                        "CURRENT hash, content untouched. They then read LOCAL_PATCH, and a later "
                        "upstream change to one reads CONFLICT instead of overwriting it.")
    p.add_argument("--keep-all-unclassified", action="store_true",
                   help="apply --keep-local to every UNCLASSIFIED path in scope. Only after you have "
                        "established that none of them is merely STALE -- this writes off the whole "
                        "queue at once, and a stale file blessed this way is a fix you never receive.")
    p.add_argument("--include-data", action="store_true", help="include data/ (regenerated artifacts; off by default)")
    p.add_argument("--seed-baseline", action="store_true",
                   help="record the CURRENT upstream hash for every IN_SYNC file, without writing any source file")
    p.add_argument("--offline", action="store_true", help="use the cached clones, do not fetch")
    p.add_argument("--cache", default=str(Path(os.environ.get("TEMP", "/tmp")) / "syndicate-vendor-upstream"))
    p.add_argument("--json", action="store_true", dest="as_json")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cache = Path(args.cache)
    baseline = load_baseline()
    baseline.setdefault("trees", {})

    surveys = []
    for key in args.trees:
        spec = TREES[key]
        if not (REPO_ROOT / "vendor" / spec["tree"]).is_dir():
            print("skip %s: vendor/%s is not present in this checkout" % (key, spec["tree"]))
            continue
        upstream_repo = prepare_upstream(cache, spec["repo"], spec["branch"], args.offline)
        if upstream_repo is None:
            return 2
        surveys.append(survey(key, spec, upstream_repo, baseline, args.include_data))

    totals: dict[str, int] = {}
    for s in surveys:
        for row in s["rows"]:
            totals[row["state"]] = totals.get(row["state"], 0) + 1

    if args.as_json:
        print(json.dumps({"totals": totals, "trees": surveys}, indent=2))
        return 1 if any(totals.get(s) for s in ACTIONABLE) else 0

    applied = 0
    for s in surveys:
        counts: dict[str, int] = {}
        for row in s["rows"]:
            counts[row["state"]] = counts.get(row["state"], 0) + 1
        print("=== vendor/%s  <-  %s@%s" % (s["tree"], s["repo"], s["branch"]))
        print("    vendoring %d of upstream's %d file(s); %s"
              % (s["n_local"], s["n_upstream"],
                 ", ".join("%s %d" % (k, counts[k]) for k in sorted(counts)) or "nothing in scope"))
        for row in s["rows"]:
            if row["state"] in (IN_SYNC, LOCAL_ONLY):
                continue
            print("      %-14s %s" % (row["state"], row["path"]))
            if row["state"] == LOCAL_PATCH:
                print("          kept -- we changed this and upstream did not")
            elif row["state"] == UNCLASSIFIED:
                print("          no baseline entry; cannot tell who changed it. Decide it:")
                print("          --keep-local %s   (ours: record it, content untouched)" % row["path"])
                print("          --adopt-upstream %s   (stale: take theirs)" % row["path"])
                print("          To tell which: does our blob hash appear anywhere in that path's")
                print("          upstream history? If yes we are merely behind; if no, it is ours.")
            elif row["state"] == CONFLICT:
                print("          both sides moved since the last sync -- merge by hand")

        if args.apply:
            for row in s["rows"]:
                take = row["state"] == UPSTREAM_AHEAD or row["path"] in args.adopt_upstream
                if not take or row["upstream"] is None:
                    continue
                if apply_row(s["tree"], row, Path(s["upstream_repo"]), s["branch"]):
                    baseline["trees"].setdefault(s["tree"], {}).setdefault("files", {})[row["path"]] = row["upstream"]
                    applied += 1
                    print("      applied      %s" % row["path"])

        if args.keep_local or args.keep_all_unclassified:
            files = baseline["trees"].setdefault(s["tree"], {}).setdefault("files", {})
            kept_here = 0
            for row in s["rows"]:
                if row["upstream"] is None:
                    continue
                named = row["path"] in args.keep_local
                sweep = args.keep_all_unclassified and row["state"] == UNCLASSIFIED
                if not (named or sweep):
                    continue
                # Record upstream's CURRENT hash as the baseline while leaving the
                # file alone. That is what "we hold a deliberate patch here" means
                # in this model: local != baseline (ours), upstream == baseline
                # (nothing new from them) -> LOCAL_PATCH. When upstream next moves,
                # both differ from the baseline and it becomes CONFLICT, which is
                # the correct answer -- someone has to look.
                files[row["path"]] = row["upstream"]
                kept_here += 1
            baseline["trees"][s["tree"]]["repo"] = s["repo"]
            baseline["trees"][s["tree"]]["branch"] = s["branch"]
            if kept_here:
                print("    recorded %d local patch(es); content untouched" % kept_here)

        if args.seed_baseline:
            files = baseline["trees"].setdefault(s["tree"], {}).setdefault("files", {})
            seeded = 0
            for row in s["rows"]:
                if row["state"] == IN_SYNC:
                    files[row["path"]] = row["upstream"]
                    seeded += 1
            baseline["trees"][s["tree"]]["repo"] = s["repo"]
            baseline["trees"][s["tree"]]["branch"] = s["branch"]
            print("    seeded baseline for %d IN_SYNC file(s); the other states are left"
                  % seeded)
            print("    unrecorded ON PURPOSE, so nothing that already differs is blessed")
        print()

    if args.apply or args.seed_baseline or args.keep_local or args.keep_all_unclassified:
        save_baseline(baseline)
        print("baseline written: %s" % BASELINE_PATH.relative_to(REPO_ROOT).as_posix())

    print("TOTALS: " + (", ".join("%s %d" % (k, v) for k, v in sorted(totals.items())) or "nothing in scope"))
    if applied:
        print("applied %d file(s). Review `git diff -- vendor/` before committing." % applied)
    pending = sum(totals.get(state, 0) for state in ACTIONABLE)
    if pending and not args.apply:
        print("%d file(s) need a decision. Nothing was written -- pass --apply to take"
              " UPSTREAM_AHEAD." % pending)
    return 1 if pending and not applied else 0


if __name__ == "__main__":
    sys.exit(main())
