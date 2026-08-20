"""Build ONE scoped deploy graft per service, carrying many sessions' files.

WHY THIS EXISTS. Every service runs an OFF-MAIN snapshot and deploys are scoped
grafts onto the previous live SHA. Measured 2026-08-20:

    web               547b541b   78 commits off main   main is 1001 ahead
    refresh-worker    39570b24   94 commits off main   main is  980 ahead
    live-odds-worker  2151f7b6    4 commits off main   main is  149 ahead

So "deploy main to consolidate" is NOT a batch of pending work -- it is a mass
upgrade carrying 53 / 44 / 19 application files of unreviewed drift. The safe
consolidation is one graft per service holding the UNION of every session's
files, parented on that service's CURRENT live SHA.

AND IT HAS TO BE ONE GRAFT, not several. Two grafts do not compose: whichever
lands second silently reverts the first unless it was rebuilt on the newer live
SHA. Measured 2026-08-15 -- a verified refresh-worker fix was live at 21:36:59Z
and gone by 21:45:20Z, with both deploys "successful" and the claim correctly
serialising them. **Serialisation orders deploys; it cannot make them
cumulative.** Batching is what makes them cumulative.

WHAT THIS GUARANTEES, and each one is a failure it has seen:

  * **Parent is read LIVE, at build time.** A graft parented on a stale SHA
    reverts whoever deployed in between. Twice today a graft had to be rebuilt
    for exactly this.
  * **Every blob is taken from origin/main and asserted identical.** The graft
    carries the reviewed content, never a local working-tree copy that might
    hold another session's uncommitted edits.
  * **diff-tree must list EXACTLY the requested paths.** If it lists more, the
    graft is carrying something nobody approved; the script refuses.
  * **A file whose content already matches live is REPORTED and dropped**, so a
    no-op graft is visible rather than deployed as though it did something.

    py -3 scripts/build_consolidated_graft.py --service web --dry-run \
        --file syndicate/features/a.py --file scripts/b.py
    py -3 scripts/build_consolidated_graft.py --service web --push \
        --file ... --message-file batch.txt

Prints the graft SHA. It does NOT deploy -- the claim and preflight are separate
gates on purpose, and a tool that silently deployed would be one people learn to
distrust.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SERVICE_IDS = {
    "web": "srv-d88ahvrbc2fs73eodu30",
    "refresh-worker": "srv-d91dpertqb8s73co8ls0",
    "live-odds-worker": "srv-d2ed2rmmcj7s73f7uleg",
}


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout.strip()


def _render_key() -> str:
    key = os.environ.get("RENDER_API_KEY", "").strip()
    if key:
        return key
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("RENDER_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no RENDER_API_KEY")


def live_sha(service: str) -> tuple[str, str]:
    """(sha, status) read from Render AT BUILD TIME -- never from a cached note.

    Also returns the status so an IN-FLIGHT deploy is visible: a build in
    progress leaves the OLD sha reading live, so 'live == my parent' looks safe
    while a newer sha is seconds from landing.
    """
    sid = SERVICE_IDS[service]
    req = urllib.request.Request(
        f"https://api.render.com/v1/services/{sid}/deploys?limit=5",
        headers={"Authorization": "Bearer " + _render_key(), "Accept": "application/json"})
    data = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    live = None
    inflight = []
    active = {"created", "queued", "build_in_progress", "update_in_progress", "pre_deploy_in_progress"}
    for entry in data:
        dep = entry.get("deploy", entry)
        status = dep.get("status")
        sha = (dep.get("commit") or {}).get("id", "")
        if status == "live" and live is None:
            live = sha
        if status in active:
            inflight.append(f"{dep.get('id')}:{status}:{sha[:12]}")
    if live is None:
        raise SystemExit(f"{service}: no live deploy found")
    return live, ",".join(inflight)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--service", required=True, choices=sorted(SERVICE_IDS))
    ap.add_argument("--file", action="append", default=[], metavar="PATH",
                    help="repo-relative path to take from origin/main. Repeatable.")
    ap.add_argument("--source", default="origin/main", help="tree to take blobs from")
    ap.add_argument("--message-file", type=Path, help="commit message; required unless --dry-run")
    ap.add_argument("--branch", help="deploy branch name (default deploy/consolidated-<service>-<date>)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--push", action="store_true", help="push the graft branch")
    args = ap.parse_args()

    if not args.file:
        raise SystemExit("no --file given; a graft with no files is a no-op")

    git("fetch", "origin", "-q")
    parent, inflight = live_sha(args.service)
    print("=" * 74)
    print(f"CONSOLIDATED GRAFT -- {args.service}")
    print("=" * 74)
    print(f"  parent (LIVE now) : {parent[:12]}")
    if inflight:
        print(f"  !! IN-FLIGHT DEPLOY: {inflight}")
        print("     A build in progress leaves the OLD sha reading live. Wait for it")
        print("     to land and re-run, or this graft will revert it.")
        return 3

    # A file already identical to live contributes nothing; say so rather than
    # shipping a graft that looks like it did something.
    take, noop, missing = [], [], []
    for path in args.file:
        src = git("rev-parse", f"{args.source}:{path}", check=False)
        if not src:
            missing.append(path)
            continue
        cur = git("rev-parse", f"{parent}:{path}", check=False)
        (noop if src == cur else take).append(path)

    for p in missing:
        print(f"  MISSING from {args.source}: {p}")
    for p in noop:
        print(f"  already identical on live (dropped): {p}")
    if missing:
        print("\n  ABORT: a requested file is not on the source tree. Push it first.")
        return 2
    if not take:
        print("\n  NOTHING TO DO: every requested file already matches live.")
        return 0

    print(f"\n  carrying {len(take)} file(s):")
    for p in take:
        print(f"    {p}")

    index = REPO.parent / f".graft-index-{args.service}"
    env = dict(os.environ, GIT_INDEX_FILE=str(index))
    if index.exists():
        index.unlink()
    subprocess.run(["git", "read-tree", parent], cwd=REPO, env=env, check=True)
    for path in take:
        blob = git("rev-parse", f"{args.source}:{path}")
        subprocess.run(["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}"],
                       cwd=REPO, env=env, check=True)
    tree = subprocess.run(["git", "write-tree"], cwd=REPO, env=env,
                          capture_output=True, text=True, check=True).stdout.strip()

    changed = git("diff-tree", "-r", "--name-only", parent, tree).splitlines()
    changed = [c for c in changed if c.strip()]
    print(f"\n  diff-tree vs parent: {len(changed)} path(s)")
    unexpected = sorted(set(changed) - set(take))
    if unexpected:
        print("  !! UNEXPECTED PATHS IN THE GRAFT -- refusing:")
        for u in unexpected:
            print(f"       {u}")
        return 4
    for path in take:
        a = git("rev-parse", f"{args.source}:{path}")
        b = subprocess.run(["git", "ls-tree", tree, path], cwd=REPO,
                           capture_output=True, text=True).stdout.split()
        if not b or b[2] != a:
            print(f"  !! blob mismatch for {path} -- refusing")
            return 5
    print("  every blob identical to source, and no extra paths. OK.")

    if args.dry_run:
        print("\n  DRY RUN -- no commit written.")
        return 0
    if not args.message_file or not args.message_file.is_file():
        raise SystemExit("--message-file is required unless --dry-run")

    sha = subprocess.run(["git", "commit-tree", tree, "-p", parent, "-F", str(args.message_file)],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    print(f"\n  GRAFT SHA: {sha}")
    branch = args.branch or f"deploy/consolidated-{args.service}"
    if args.push:
        git("push", "-q", "origin", f"{sha}:refs/heads/{branch}")
        print(f"  pushed to {branch}")
    else:
        print(f"  not pushed (use --push). Branch would be {branch}")
    print("\n  NOT DEPLOYED. Take the claim and run preflight, then render_deploy.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
