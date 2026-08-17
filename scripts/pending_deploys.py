"""What is committed on `origin/main` and NOT yet running, per service.

WHY THIS EXISTS RATHER THAN A HAND-WRITTEN LIST. A list of "commits waiting to
deploy" is stale the moment another lane pushes, and this repo has had four
sessions pushing to `main` in the same hour. Every number here is re-derived on
each run from the LIVE commit each service actually reports.

WHY IT DOES NOT COUNT "COMMITS BEHIND". Every service runs a curated deploy
branch cut from a live SHA, never `main`, so `rev-list --count live..main`
reports 600-700 and means almost nothing. What matters is the far smaller set of
commits that touch code the service actually executes.

WHAT IT DELIBERATELY DOES NOT DO. It does not tell you a deploy is safe. Job
liveness, the deploy claim and the render.yaml blast radius are
`deploy_preflight.py`'s job, and a second tool answering the same question
differently is worse than no second tool.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Which service EXECUTES a given path. `shared` is listed against every service
# on purpose: `syndicate/features/shared/` is imported by the web app and by both
# workers, and treating it as web-only is how a worker-side fix gets deployed to
# the wrong service. That mistake was made tonight -- Phase 1c targets
# `live_refresh_loop.py`, which only live-odds-worker runs for soccer.
PATH_OWNERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("syndicate/blueprints/", ("web",)),
    ("syndicate/templates/", ("web",)),
    ("syndicate/static/", ("web",)),
    ("scripts/run_refresh_worker.py", ("refresh-worker",)),
    ("scripts/run_live_odds_refresh_worker.py", ("live-odds-worker",)),
    ("pipeline/", ("refresh-worker",)),
    ("syndicate/features/shared/", ("web", "refresh-worker", "live-odds-worker")),
    ("syndicate/features/", ("web", "refresh-worker", "live-odds-worker")),
    ("vendor/", ("refresh-worker",)),
    ("scripts/", ("refresh-worker", "live-odds-worker")),
)

# Paths that change nothing at runtime. Excluded so the manifest reports work,
# not noise -- ledger churn alone is ~73 files per service.
INERT_PREFIXES = (".syndicate/", "docs/", "reports/", "data/", "tests/")


def _git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


def _owners(path: str) -> tuple[str, ...]:
    for prefix, owners in PATH_OWNERS:
        if path.startswith(prefix):
            return owners
    return ()


def _live_commits() -> dict[str, str]:
    """Deployed SHA per service, read from deploy_preflight (the one source)."""
    raw = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "deploy_preflight.py"),
         "--service", "web"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    ).stdout.replace("\r", "")
    out: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in {"web", "refresh-worker", "live-odds-worker"}:
            out[parts[0]] = parts[1]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--base", default="origin/main")
    args = ap.parse_args()

    _git("fetch", "-q", "origin")
    base = _git("rev-parse", args.base)
    live = _live_commits()
    if not live:
        print("could not read live commits from deploy_preflight -- refusing to guess", file=sys.stderr)
        return 2

    report: dict[str, dict] = {}
    for service, sha in sorted(live.items()):
        commits = []
        log = _git("log", "--format=%H\x1f%s", f"{sha}..{base}")
        for line in log.splitlines():
            if "\x1f" not in line:
                continue
            full, subject = line.split("\x1f", 1)
            files = [
                f for f in _git("show", "--pretty=", "--name-only", full).splitlines()
                if f and not f.startswith(INERT_PREFIXES)
            ]
            owned = sorted({f for f in files if service in _owners(f)})
            if owned:
                commits.append({"sha": full[:8], "subject": subject, "files": owned})
        report[service] = {
            "live": sha,
            "pending_code_commits": len(commits),
            "commits": commits,
        }

    if args.json:
        print(json.dumps({"base": base[:8], "services": report}, indent=2))
        return 0

    print(f"# pending deploys against {args.base} ({base[:8]})")
    print("# only commits touching code the service EXECUTES; ledger/docs/data/tests excluded")
    for service, data in report.items():
        print(f"\n== {service}   live={data['live']}   {data['pending_code_commits']} pending code commit(s)")
        for c in data["commits"]:
            print(f"   {c['sha']}  {c['subject'][:78]}")
            for f in c["files"][:4]:
                print(f"        {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
