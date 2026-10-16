"""Move the MLB engine's runtime state from vendor/mlb_bettingv2/data to engines/mlb/data.

Lane mlb-engine-data-native-p4 (2026-10-16). The native engine's DATA root moved from vendor/mlb_bettingv2 to
engines/mlb (scripts/port_mlb_sim_engine.py, ENGINE FILE rule). The 12 git-tracked engine inputs move in git; what the
engine WROTE under the vendored data dir at runtime does not, and without it the next sim would start cold (roster
registry, statcast caches) or read git's copy of a file production has since rewritten (the statcast player features).
This copies that state across:

  * every file under vendor/mlb_bettingv2/data that git does NOT track (runtime state), and
  * every TRACKED file there that differs from HEAD (rewritten at runtime) -- over the git copy in engines/mlb/data.

A destination that already exists with different bytes is NOT overwritten unless --overwrite: after the switch the
engine writes engines/mlb/data itself, and a re-run must never roll its newer state back. Every copy is verified by
sha256. The vendored files are left in place (they are the rollback).

Usage:
  python scripts/migrate_mlb_engine_data.py --dry-run
  python scripts/migrate_mlb_engine_data.py [--repo /home/amyn/Syndicate] [--overwrite]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_REL = Path("vendor") / "mlb_bettingv2" / "data"
DST_REL = Path("engines") / "mlb" / "data"


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_lines(repo: Path, *args: str) -> list[str]:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def _sha_git(git_repo: Path, rel: str) -> str:
    blob = subprocess.run(["git", "-C", str(git_repo), "show", f"HEAD:{rel}"], capture_output=True, check=True).stdout
    return hashlib.sha256(blob).hexdigest()


def plan(repo: Path, git_repo: Path | None = None) -> list[tuple[str, Path, Path]]:
    """[(why, src, dst)] -- runtime state and runtime-rewritten tracked files. `git_repo` answers "tracked / modified"
    when `repo` is a copy without .git (the parity harness's arms)."""
    git_repo = git_repo or repo
    src_root, dst_root = repo / SRC_REL, repo / DST_REL
    if not src_root.is_dir():
        return []
    tracked = set(_git_lines(git_repo, "ls-files", "--", SRC_REL.as_posix()))
    modified = {line[3:] for line in _git_lines(git_repo, "status", "--porcelain", "--", SRC_REL.as_posix())
                if line[:2].strip() == "M"} if git_repo == repo else {
        rel for rel in tracked if (repo / rel).is_file() and _sha(repo / rel) != _sha_git(git_repo, rel)}
    out = []
    for src in sorted(p for p in src_root.rglob("*") if p.is_file()):
        rel_repo = src.relative_to(repo).as_posix()
        if "__pycache__" in src.parts:
            continue
        if rel_repo in tracked and rel_repo not in modified:
            continue  # moved in git, unchanged at runtime
        why = "runtime-rewritten tracked input" if rel_repo in tracked else "runtime state"
        out.append((why, src, dst_root / src.relative_to(src_root)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=str(ROOT), help="the checkout to migrate (default: this one)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--overwrite", action="store_true", help="replace a destination that already differs")
    ap.add_argument("--git-repo", default="", help="answer tracked/modified from this checkout (for a copy without .git)")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    if not (repo / DST_REL.parent).is_dir():
        print(json.dumps({"ok": False, "error": f"{DST_REL.parent} is absent: fast-forward to the engines/mlb commit first"}))
        return 2
    counts = {"runtime state": 0, "runtime-rewritten tracked input": 0, "already identical": 0,
              "kept newer destination": 0, "bytes": 0}
    git_repo = Path(args.git_repo).resolve() if args.git_repo else repo
    for why, src, dst in plan(repo, git_repo):
        if dst.exists():
            if _sha(dst) == _sha(src):
                counts["already identical"] += 1
                continue
            # A tracked input git just wrote equals git's copy; replacing it with production's rewrite is the point.
            git_copy = why == "runtime-rewritten tracked input" and _sha(dst) == _sha_git(
                git_repo, (SRC_REL / dst.relative_to(repo / DST_REL)).as_posix())
            if not (args.overwrite or git_copy):
                counts["kept newer destination"] += 1
                continue
        counts[why] += 1
        counts["bytes"] += src.stat().st_size
        if args.dry_run:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if _sha(dst) != _sha(src):
            print(json.dumps({"ok": False, "error": f"copy verify failed: {dst}"}))
            return 3
    print(json.dumps({"ok": True, "dry_run": args.dry_run, "repo": str(repo), **counts}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
