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

    py -3 scripts/render_deploy.py --service web --commit d4bb29b5
    py -3 scripts/render_deploy.py --service refresh-worker --commit HEAD --json
"""

from __future__ import annotations

import argparse
import json
import os
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True, choices=sorted(SERVICE_IDS))
    parser.add_argument("--commit", required=True, help="commit SHA to deploy")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    key = _load_api_key()
    if not key:
        print("RENDER_API_KEY not found in environment or .env", file=sys.stderr)
        return 2

    service_id = SERVICE_IDS[args.service]
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
