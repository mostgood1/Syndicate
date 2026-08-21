"""Set ONE environment variable on ONE Syndicate service, via Render's API.

WHY THIS EXISTS RATHER THAN A RAW curl, and it is the same reasoning
`scripts/render_deploy.py` gives: the call needs `RENDER_API_KEY` from the
gitignored `.env`, and sourcing that in the same shell command makes a compound
whose prefix no narrow permission rule can match. This script reads the key
itself, so it never reaches argv, a log, or a permission prompt.

WHY THE SINGLE-KEY ENDPOINT AND NOT `render.yaml`. Pushing `render.yaml` fires
`blueprint_sync`, which **rewrites the WHOLE env block of every service** --
measured 2026-08-08, a one-key intent that rewrote 92 -> 93 keys on
refresh-worker and 502'd every route for ~2 minutes. `PUT
/v1/services/<id>/env-vars/<key>` changes exactly the key named here and
nothing else.

**AN ENV CHANGE ALONE DOES NOT REACH THE RUNNING PROCESS.** A restart does not
re-inject env vars; the service must be DEPLOYED afterwards for the new value
to be visible to the code. So the order is always: set the key, then deploy --
and this script says so on exit rather than leaving it implied.

    python scripts/render_env_set.py --service refresh-worker \\
        --key NFL_FANTASY_ARTIFACT_ENABLE_REFRESH_WORKER_AUTORUN --value true
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

# IMPORTED, NOT RETYPED, and this is not a style preference. Writing the map
# out by hand here transposed the two worker ids -- `refresh-worker` would have
# pointed at `live-odds-worker`'s service, so this script would have enabled a
# ~725MB daily job on the 2GB service instead of the 4GB one. That is the exact
# shape of `#241`. Two literals differing in one character, in a file whose
# whole job is to name a service correctly.
#
# `render_deploy.py` already owns this mapping and is the file every deploy
# goes through, so it is the one that stays right.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_deploy import SERVICE_IDS as _DEPLOY_SERVICE_IDS  # noqa: E402

SERVICES: dict[str, str] = dict(_DEPLOY_SERVICE_IDS)
SERVICES.setdefault("syndicate", SERVICES["web"])


def _api_key() -> str:
    key = os.environ.get("RENDER_API_KEY", "").strip()
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("RENDER_API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def _request(method: str, url: str, key: str, payload: dict | None = None) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {key}")
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except Exception as error:  # noqa: BLE001
        return 0, f"{type(error).__name__}: {error}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True, choices=sorted(SERVICES))
    parser.add_argument("--key", required=True)
    parser.add_argument("--value", required=True)
    args = parser.parse_args()

    api_key = _api_key()
    if not api_key:
        print("RENDER_API_KEY not found in the environment or .env", flush=True)
        return 2

    service_id = SERVICES[args.service]
    base = f"https://api.render.com/v1/services/{service_id}/env-vars"

    # Read the current value first, so the change is auditable and idempotent.
    status, body = _request("GET", f"{base}?limit=100", api_key)
    if status != 200:
        print(f"could not read env-vars: HTTP {status} {body[:200]}", flush=True)
        return 1
    try:
        rows = json.loads(body)
    except ValueError:
        print(f"unexpected env-vars payload: {body[:200]}", flush=True)
        return 1

    before = None
    for row in rows:
        item = row.get("envVar") if isinstance(row, dict) else None
        if isinstance(item, dict) and item.get("key") == args.key:
            before = item.get("value")
            break

    print(f"service        {args.service}  ({service_id})")
    print(f"key            {args.key}")
    print(f"before         {before!r}")
    print(f"after (intent) {args.value!r}")

    if before == args.value:
        print("\nNO CHANGE NEEDED -- already set to this value.", flush=True)
        return 0

    status, body = _request("PUT", f"{base}/{args.key}", api_key, {"value": args.value})
    if status not in (200, 201):
        print(f"\nFAILED: HTTP {status} {body[:300]}", flush=True)
        return 1

    print("\nSET OK.")
    print(
        "THE RUNNING PROCESS HAS NOT SEEN THIS YET. A restart does not re-inject\n"
        f"env vars -- deploy {args.service} for the new value to take effect."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
