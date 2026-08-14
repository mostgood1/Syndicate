"""Trigger a Render deploy for one Syndicate service.

WHY THIS EXISTS RATHER THAN A RAW curl. Deploying needs `RENDER_API_KEY` from
the gitignored `.env`, which means sourcing it in the same shell command --
and that makes the command a compound whose prefix cannot be matched by a
narrow permission rule. The alternative, allowing `Bash(curl *)`, would permit
any POST to anywhere. This script keeps the secret out of argv (so it never
reaches a log or a permission prompt), pins the service allowlist, and lets the
rule be exactly `Bash(python scripts/render_deploy.py *)`.

It deliberately does NOT run the safety gate for you. `scripts/check_deploy_safety.py`
is a separate decision with its own output, and a deploy tool that silently
refuses is one people learn to bypass. Run the gate, read it, then run this.

IT DOES REFUSE A ROLLBACK, and that one is not a judgement call. The live SHA is
re-read HERE, at deploy time, and the target must be a descendant of it. On
2026-08-14 a target chosen as "a pure restart, no new code" became a rollback of
850 lines within ninety seconds, because a concurrent session deployed in
between; it was caught by hand, after the POST. `state.md` already says deployed
SHAs "go stale in minutes, not days" — this makes that a precondition instead of
a habit. `--allow-rollback` when it is deliberate.

If the live SHA cannot be read the guard steps aside rather than blocking: a
deploy must not fail because telemetry did.

    py -3 scripts/render_deploy.py --service web --commit d4bb29b5
    py -3 scripts/render_deploy.py --service refresh-worker --commit HEAD --json
    py -3 scripts/render_deploy.py --service refresh-worker --commit 03073270 --allow-rollback
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Same ids as scripts/deploy_preflight.py and check_deploy_safety.py. An
# allowlist, not a convenience: a typo'd service id would otherwise 404 after
# the permission gate has already been cleared.
SERVICE_IDS = {
    "web": "srv-d88ahvrbc2fs73eodu30",
    "refresh-worker": "srv-d91dpertqb8s73co8ls0",
    "live-odds-worker": "srv-d91dpertqb8s73co8lt0",
}


def _load_api_key() -> str:
    key = os.environ.get("RENDER_API_KEY", "").strip()
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == "RENDER_API_KEY":
                return value.strip().strip('"').strip("'")
    return ""


def _live_commit(service_id: str, key: str) -> str | None:
    """The commit the service is running RIGHT NOW, read at deploy time.

    Read here rather than passed in on purpose: `state.md` records that
    deployed SHAs "go stale in minutes, not days", and the whole failure this
    guards against is a target that was correct when chosen and wrong when
    fired. A value read a minute ago is not a check.
    """
    request = urllib.request.Request(
        f"https://api.render.com/v1/services/{service_id}/deploys?limit=20",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            for row in json.loads(response.read().decode("utf-8")):
                deploy = row.get("deploy", row)
                if deploy.get("status") == "live":
                    return ((deploy.get("commit") or {}).get("id") or "") or None
    except Exception:
        return None  # unreadable -> fall through; never block a deploy on telemetry
    return None


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=str(Path(__file__).resolve().parent.parent),
                                capture_output=True, text=True)
    except Exception:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _resolve(ref: str) -> str | None:
    return _git("rev-parse", "--verify", f"{ref}^{{commit}}")


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    try:
        return subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=str(Path(__file__).resolve().parent.parent), capture_output=True
        ).returncode == 0
    except Exception:
        return False


def _revert_summary(target: str, live: str) -> str:
    stat = _git("diff", "--shortstat", target, live, "--", "*.py")
    return (stat or "unknown").strip() or "no .py difference"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True, choices=sorted(SERVICE_IDS))
    parser.add_argument("--commit", required=True, help="commit SHA to deploy")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--allow-rollback", action="store_true",
                        help="deploy even if it would move production BACKWARDS")
    args = parser.parse_args()

    key = _load_api_key()
    if not key:
        print("RENDER_API_KEY not found in environment or .env", file=sys.stderr)
        return 2

    service_id = SERVICE_IDS[args.service]

    live = _live_commit(service_id, key)
    if live and not args.allow_rollback:
        target = _resolve(args.commit)
        if target is None:
            print(f"cannot resolve {args.commit!r} locally; run `git fetch origin` "
                  f"or pass --allow-rollback if you know what you are doing",
                  file=sys.stderr)
            return 2
        if target == live:
            print(f"{args.service} is ALREADY live on {live[:8]} -- nothing to deploy.",
                  file=sys.stderr)
            return 2
        if not _is_ancestor(live, target):
            print(
                f"REFUSING: {args.service} is live on {live[:8]}, which is NOT an\n"
                f"ancestor of {target[:8]}. This deploy would ROLL BACK production.\n\n"
                f"  reverts: {_revert_summary(target, live)}\n\n"
                f"On 2026-08-14 this exact shape nearly reverted 850 lines of another\n"
                f"session's work: the target was a pure restart when it was chosen and\n"
                f"a rollback ninety seconds later, because a concurrent session had\n"
                f"deployed in between. A SHA checked a minute ago is not a check.\n"
                f"Pass --allow-rollback to do it deliberately.",
                file=sys.stderr,
            )
            return 2

    request = urllib.request.Request(
        f"https://api.render.com/v1/services/{service_id}/deploys",
        data=json.dumps({"commitId": args.commit}).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:400]}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - network
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    commit = (payload.get("commit") or {}).get("id") or "n/a"
    print(
        f"{args.service} <- {commit[:8]}  deploy={payload.get('id')} "
        f"status={payload.get('status')} trigger={payload.get('trigger')} "
        f"created={payload.get('createdAt')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
