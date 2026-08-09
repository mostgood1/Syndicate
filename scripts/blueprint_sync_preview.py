"""#281: show what a Render blueprint sync WOULD write, before anyone pushes render.yaml.

WHY THIS EXISTS. `autoDeploy = no` on all three services, and both CLAUDE.md and
todo.md said "pushing to `main` ships nothing on its own". That is true of code
and FALSE OF CONFIG: `blueprint_sync` is a separate mechanism that reads
render.yaml from `main` and applies it to the live services. Measured
2026-08-08, a web deploy at 23:02:26Z carried `trigger = blueprint_sync` with no
user in it, rewrote env vars on two live services, and 502'd every route for
~2 minutes. Nobody deployed it. See `#284`.

THE PART THAT MAKES THIS A GATE RATHER THAN A REPORT: a sync applies the WHOLE
env block, not your diff. So the blast radius of a one-key edit is every value in
the file, including drift nobody has read. Run this before pushing render.yaml
and read the CHANGE section -- an add is usually intended, a change to a key you
did not touch is the one that hurts.

Read-only. Never writes to Render. Exit code 1 if anything would change, so it
can gate a push:

    py -3 scripts/blueprint_sync_preview.py
    py -3 scripts/blueprint_sync_preview.py --service refresh-worker --json

Needs RENDER_API_KEY in .env (or the environment).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# Render's env-vars endpoint returns HTTP 400 for limit > 100. Discovered the
# hard way; the failure looks like an auth problem and is not one.
_PAGE_LIMIT = 100

SERVICE_IDS = {
    "syndicate": "srv-d88ahvrbc2fs73eodu30",
    "refresh-worker": "srv-d91dpertqb8s73co8ls0",
    "live-odds-worker": "srv-d91dpertqb8s73co8lt0",
}


def _load_api_key() -> str:
    key = os.environ.get("RENDER_API_KEY")
    if key:
        return key.strip()
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("RENDER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("RENDER_API_KEY not found in environment or .env")


def _get(url: str, key: str) -> Any:
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def live_env(service_id: str, key: str) -> dict[str, str]:
    """Every env var on the service. Paginated: see _PAGE_LIMIT."""
    env: dict[str, str] = {}
    cursor: str | None = None
    while True:
        url = f"https://api.render.com/v1/services/{service_id}/env-vars?limit={_PAGE_LIMIT}"
        if cursor:
            url += f"&cursor={cursor}"
        rows = _get(url, key)
        if not rows:
            break
        for row in rows:
            var = row.get("envVar") or {}
            if var.get("key") is not None:
                env[str(var["key"])] = str(var.get("value") if var.get("value") is not None else "")
        cursor = rows[-1].get("cursor")
        if len(rows) < _PAGE_LIMIT or not cursor:
            break
    return env


def blueprint_env(path: Path) -> dict[str, dict[str, str]]:
    """Declared env vars per service name, values coerced to str.

    Skips entries with no literal `value` (`sync: false`, `fromService`,
    `generateValue`) -- a sync does not write a literal for those, so including
    them would produce false CHANGE rows.
    """
    import yaml  # local import: only this entrypoint needs it

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for service in document.get("services") or []:
        name = str(service.get("name") or "")
        declared: dict[str, str] = {}
        for entry in service.get("envVars") or []:
            if not isinstance(entry, dict) or "value" not in entry:
                continue
            declared[str(entry.get("key"))] = str(entry.get("value"))
        out[name] = declared
    return out


def compare(declared: dict[str, str], live: dict[str, str]) -> dict[str, list]:
    adds, changes = [], []
    for key, value in sorted(declared.items()):
        if key not in live:
            adds.append((key, value))
        elif live[key] != value:
            changes.append((key, live[key], value))
    # Live-only keys are reported for context but are NOT writes: measured
    # 2026-08-08, refresh-worker went 92 -> 93 vars on a sync while holding many
    # keys the blueprint never declares, so a sync ADDS and UPDATES but does not
    # PRUNE. Reported so nobody assumes the blueprint is the whole picture.
    live_only = sorted(k for k in live if k not in declared)
    return {"add": adds, "change": changes, "live_only": live_only}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", action="append", help="limit to a service name (repeatable)")
    parser.add_argument("--blueprint", default=str(REPO_ROOT / "render.yaml"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    key = _load_api_key()
    declared_all = blueprint_env(Path(args.blueprint))
    wanted = args.service or list(SERVICE_IDS)

    report: dict[str, Any] = {}
    would_write = 0
    for name in wanted:
        service_id = SERVICE_IDS.get(name)
        if not service_id:
            print(f"!! unknown service {name!r}; known: {', '.join(SERVICE_IDS)}", file=sys.stderr)
            continue
        try:
            live = live_env(service_id, key)
        except urllib.error.HTTPError as exc:
            print(f"!! {name}: HTTP {exc.code} fetching env vars", file=sys.stderr)
            return 2
        result = compare(declared_all.get(name, {}), live)
        result["declared_count"] = len(declared_all.get(name, {}))
        result["live_count"] = len(live)
        report[name] = result
        would_write += len(result["add"]) + len(result["change"])

    if args.json:
        print(json.dumps(report, indent=1, sort_keys=True))
    else:
        for name, result in report.items():
            # ASCII only: this runs on a Windows console whose default codepage
            # mangles non-ASCII, and a mangled gate reads as a broken gate.
            print(f"\n=== {name}   blueprint declares {result['declared_count']} | live holds {result['live_count']}")
            if result["add"]:
                print(f"  WOULD ADD ({len(result['add'])}) -- absent on the service today:")
                for k, v in result["add"]:
                    print(f"    + {k} = {v!r}")
            if result["change"]:
                print(f"  WOULD CHANGE ({len(result['change'])}) -- READ THESE, they overwrite live values:")
                for k, was, now in result["change"]:
                    print(f"    ~ {k}: {was!r} -> {now!r}")
            if not result["add"] and not result["change"]:
                print("  in sync -- a blueprint_sync would write nothing")
            print(f"  (live-only, untouched by a sync: {len(result['live_only'])})")

    if would_write:
        print(f"\nA blueprint sync WOULD WRITE {would_write} value(s). Do not push render.yaml until each is intended.")
        return 1
    print("\nNothing would be written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
