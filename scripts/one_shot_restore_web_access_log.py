"""Append `--access-logfile -` to web's GUNICORN_CMD_ARGS. One key. Nothing else.

Self-contained on purpose: no repo imports, so there is no sys.path to get
wrong. Reads RENDER_API_KEY from the environment or from the repo-root .env.

THE RISK THIS GUARDS AGAINST. That variable currently carries lane
`nfl-props-autorun-e2e`'s OOM fix (`--max-requests 1000 --max-requests-jitter
100`), set 2026-09-08 23:44Z after 5 `oomKilled` events at 2Gi. OVERWRITING it
instead of APPENDING would silently revert a live memory fix on a 2 GB service.
So this refuses unless it first reads back exactly the value it expects, and
aborts if any key other than this one changes.

It uses the SINGLE-KEY endpoint and does NOT touch render.yaml, so it cannot
fire `blueprint_sync` -- which matters because render.yaml is 166 env vars
behind production and a sync would delete SYNDICATE_EXECUTION_LIVE_ARMED and the
live-money spend caps.

An env change is NOT live until a deploy: Render does not re-inject env on a
restart.

    py -3 scripts/one_shot_restore_web_access_log.py

ALREADY RUN -- THIS IS NOW A RECORD, NOT A TODO `[added 2026-09-09 by session
d5c69f3c when committing the file; the author's session was gone]`. It was run
on 2026-09-08/09 and DID set the key, but stopped short of the deploy its own
docstring calls for, so the emitter stayed dead for 14h49m. Deploy
`dep-dagms5u7bikc73bsf1sg` (web, same SHA `e4552e27`, env-only) made it live at
2026-09-09T14:38:59Z; 104 access lines in the following 74 s against a measured
zero. Full entry: `.syndicate/deploys.md`, 2026-09-09 14:32Z.

Re-running it now correctly REFUSES at the `--access-logfile is already set`
guard. Ignore that refusal's parenthetical "the cause is elsewhere" -- it was
written before the cause was known, and the cause is NOT elsewhere: setting this
variable explicitly REPLACED Render's own default injection for a `python`
service, and that default was the only thing that had ever carried
`--access-logfile -`. Nothing in this repo declared it, which is why grepping
`render.yaml` and `startCommand` for the flag finds nothing while the log ran
for months.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_SERVICE_ID = "srv-d88ahvrbc2fs73eodu30"

KEY_NAME = "GUNICORN_CMD_ARGS"
EXPECTED_NOW = "--max-requests 1000 --max-requests-jitter 100"
ADDITION = "--access-logfile -"


def api_key() -> str:
    value = str(os.environ.get("RENDER_API_KEY") or "").strip()
    if value:
        return value
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("RENDER_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("RENDER_API_KEY not set in the environment or .env")


def call(url: str, key: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = response.read().decode("utf-8")
                return response.status, (json.loads(text) if text.strip() else None)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 5:
                raise SystemExit(
                    "HTTP " + str(exc.code) + " on " + method + " " + url + "\n"
                    + exc.read().decode("utf-8", "ignore")[:400]
                )
            time.sleep(3.0 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 5:
                raise
            time.sleep(3.0 * (attempt + 1))
    raise SystemExit("unreachable")


def read_all(key: str) -> dict[str, str]:
    """PAGINATE. CLAUDE.md: limit > 100 returns HTTP 400, and an unpaginated
    read of this endpoint already produced one retracted 'drift' claim."""
    out: dict[str, str] = {}
    cursor = None
    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        base = "https://api.render.com/v1/services/" + WEB_SERVICE_ID + "/env-vars?"
        _status, page = call(base + urllib.parse.urlencode(params), key)
        if not page:
            break
        for item in page:
            ev = item.get("envVar") or item
            out[ev.get("key")] = ev.get("value")
            cursor = item.get("cursor") or cursor
        if len(page) < 100:
            break
    return out


def main() -> int:
    key = api_key()
    before = read_all(key)
    current = before.get(KEY_NAME)
    print("keys before        : " + str(len(before)))
    print("{} now  : {!r}".format(KEY_NAME, current))

    if current is None:
        print("\nREFUSING: " + KEY_NAME + " is absent. Expected it to exist and carry the OOM fix.")
        return 1
    if current.strip() != EXPECTED_NOW:
        print("\nREFUSING: value is not what this script was written against.")
        print("  expected: {!r}".format(EXPECTED_NOW))
        print("  found:    {!r}".format(current))
        print("Someone changed it. Re-read the ledger before editing.")
        return 1
    if ADDITION.split()[0] in current:
        print("\nREFUSING: --access-logfile is already set. This would be a no-op; "
              "the cause is elsewhere.")
        return 1

    new_value = current.strip() + " " + ADDITION
    print("{} new  : {!r}".format(KEY_NAME, new_value))

    status, _payload = call(
        "https://api.render.com/v1/services/" + WEB_SERVICE_ID + "/env-vars/" + KEY_NAME,
        key, method="PUT", body={"value": new_value},
    )
    print("PUT " + str(status))

    after = read_all(key)
    print("keys after         : {}  (delta {:+d}, expect +0)".format(
        len(after), len(after) - len(before)))
    print("{} readback: {!r}".format(KEY_NAME, after.get(KEY_NAME)))

    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    print("keys whose value changed: {}  (expect exactly ['{}'])".format(changed, KEY_NAME))
    if changed != [KEY_NAME]:
        print("\n!! BLAST RADIUS WRONG -- do NOT deploy; investigate first")
        return 1
    if "--max-requests" not in (after.get(KEY_NAME) or ""):
        print("\n!! THE OOM FIX IS GONE -- the append became an overwrite. Do NOT deploy.")
        return 1

    print("\nENV SET, blast radius verified: 1 key changed, count unchanged, "
          "--max-requests intact.")
    print("NOT LIVE until a deploy -- Render does not re-inject env on restart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
