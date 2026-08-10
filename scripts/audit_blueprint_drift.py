"""#312 -- what a `render.yaml` push would actually do to production.

WHY THIS EXISTS. `autoDeploy` is off for code, so pushing `.py` to `main` ships
nothing. `render.yaml` is different: a push triggers `blueprint_sync`, which
rewrites env vars on live services with no deploy anyone ordered (#284). CLAUDE.md
therefore says "enumerate before pushing" -- diff the blueprint against each
service's live env-vars. That advice was never runnable, so nobody ran it. This
is that enumeration, as a command.

THE SEMANTICS, MEASURED RATHER THAN ASSUMED -- and they are narrower than the
warning implies. The 2026-08-08 sync took refresh-worker from 92 to 93 keys
while the blueprint declared 84. A full replace would have driven it DOWN to 84.
So a sync UPSERTS declared keys and leaves live-only keys alone. That means:

    the hazard is NOT "everything gets rewritten"
    the hazard IS  "a DECLARED key whose live value was changed at runtime
                    silently reverts to the literal in the file"

which is exactly #312: disable a flag through the env API, and the next
`render.yaml` push from any lane re-enables it.

Exit code is 1 if anything would be reverted, so this can gate a push.

Read-only. Performs GETs against the Render API and never writes.

    py -3 scripts/audit_blueprint_drift.py
    py -3 scripts/audit_blueprint_drift.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# render.yaml service name -> live Render service id.
SERVICE_IDS = {
    "syndicate": "srv-d88ahvrbc2fs73eodu30",
    "refresh-worker": "srv-d91dpertqb8s73co8ls0",
    "live-odds-worker": "srv-d91dpertqb8s73co8lt0",
}

# Flags an operator might plausibly toggle at runtime during an incident. A
# hardcoded literal on one of these is a kill switch that re-arms itself.
# Deliberately excludes *_TICK_OWNER-style routing keys: those must stay
# consistent ACROSS services, so drift between them is a bug rather than an
# operator action, and the blueprint is the right place to pin them (#278).
KILL_SWITCH_RE = re.compile(r"(ENABLE|DISABLE|_AUTORUN)")
OWNERSHIP_RE = re.compile(r"_(TICK_)?OWNER$")

_MANAGED = "<managed>"
_UNDECLARED = "<undeclared>"


def _api_key() -> str:
    value = str(os.environ.get("RENDER_API_KEY") or "").strip()
    if value:
        return value
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("RENDER_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("RENDER_API_KEY not set in the environment or .env")


def _get(url: str, key: str):
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # The logs/env APIs rate-limit under pagination. Back off rather
            # than letting a 429 surface as an empty result -- a throttled read
            # rendering as "no drift" is the worst possible failure here.
            if exc.code != 429 or attempt == 5:
                raise
            time.sleep(3.0 * (attempt + 1))
    raise RuntimeError("unreachable")


def live_env(service_id: str, key: str) -> dict[str, str]:
    """Every live env var for a service. `limit` above 100 returns HTTP 400."""
    found: dict[str, str] = {}
    cursor = ""
    while True:
        url = f"https://api.render.com/v1/services/{service_id}/env-vars?limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        page = _get(url, key)
        if not page:
            break
        for row in page:
            env = row.get("envVar", row)
            if env.get("key") is None:
                continue
            raw = env.get("value")
            found[str(env["key"])] = str(raw) if raw is not None else "<generated/secret>"
        cursor = str(page[-1].get("cursor") or "")
        if not cursor or len(page) < 100:
            break
    return found


def blueprint_env(render_yaml: Path) -> dict[str, dict[str, tuple[str, bool]]]:
    """service -> {key: (declared_value, sync_false)} parsed from render.yaml.

    Deliberately a small line parser rather than a YAML dependency: this script
    has to be runnable from a bare checkout before anyone installs anything,
    and the file's shape is stable.
    """
    services: dict[str, dict[str, tuple[str, bool]]] = {}
    current: str | None = None
    pending: str | None = None
    for raw in render_yaml.read_text(encoding="utf-8").splitlines():
        name = re.match(r"^\s{4}name:\s*(\S+)\s*$", raw)
        if name and name.group(1) in SERVICE_IDS:
            current = name.group(1)
            services.setdefault(current, {})
            pending = None
            continue
        if current is None:
            continue
        key_match = re.match(r"\s*-\s*key:\s*(\S+)", raw)
        if key_match:
            pending = key_match.group(1)
            services[current][pending] = (_UNDECLARED, False)
            continue
        if not pending:
            continue
        value_match = re.match(r"\s*value:\s*(.*)$", raw)
        if value_match:
            value = value_match.group(1).strip().strip('"').strip("'")
            services[current][pending] = (value, services[current][pending][1])
        elif re.match(r"\s*sync:\s*false", raw):
            services[current][pending] = (services[current][pending][0], True)
        elif re.match(r"\s*(generateValue|fromService|fromDatabase|fromGroup):", raw):
            services[current][pending] = (_MANAGED, services[current][pending][1])
    return services


def audit() -> dict:
    key = _api_key()
    declared_by_service = blueprint_env(REPO_ROOT / "render.yaml")
    report: dict = {"services": {}, "would_revert_total": 0}

    for service, service_id in SERVICE_IDS.items():
        declared = declared_by_service.get(service, {})
        live = live_env(service_id, key)

        would_revert = []
        would_create = []
        for name, (value, sync_false) in sorted(declared.items()):
            if sync_false or value in {_MANAGED, _UNDECLARED}:
                continue
            if name not in live:
                would_create.append({"key": name, "blueprint": value})
            elif live[name] != value:
                would_revert.append({"key": name, "live": live[name], "blueprint": value})

        exposed = [
            name
            for name, (value, sync_false) in sorted(declared.items())
            if KILL_SWITCH_RE.search(name)
            and not OWNERSHIP_RE.search(name)
            and not sync_false
            and value not in {_MANAGED, _UNDECLARED}
        ]

        report["services"][service] = {
            "blueprint_keys": len(declared),
            "live_keys": len(live),
            "would_revert": would_revert,
            "would_create": would_create,
            "live_only": [name for name in sorted(live) if name not in declared],
            "unprotected_kill_switches": exposed,
        }
        report["would_revert_total"] += len(would_revert)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Enumerate what a render.yaml blueprint sync would change in production.")
    parser.add_argument("--json", action="store_true", help="Machine-readable output.")
    args = parser.parse_args()

    report = audit()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if report["would_revert_total"] else 0

    for service, data in report["services"].items():
        print(f"\n=== {service}   blueprint={data['blueprint_keys']}  live={data['live_keys']}")
        if data["would_revert"]:
            print(f"  WOULD REVERT {len(data['would_revert'])} live value(s) -- THIS IS THE #312 HAZARD:")
            for row in data["would_revert"]:
                print(f"    {row['key']}\n      live      = {row['live']!r}\n      blueprint = {row['blueprint']!r}")
        else:
            print("  would revert: none")
        if data["would_create"]:
            print(f"  would CREATE {len(data['would_create'])} key(s) absent live:")
            for row in data["would_create"]:
                print(f"    {row['key']} = {row['blueprint']!r}")
        print(f"  live-only (undeclared, upsert leaves these alone): {len(data['live_only'])}")
        print(f"  kill switches pinned to a literal (latent #312 exposure): {len(data['unprotected_kill_switches'])}")

    total = report["would_revert_total"]
    print(f"\nTOTAL live values a sync would revert right now: {total}")
    if total == 0:
        print("A render.yaml push is currently value-neutral on declared keys.")
        print("NOTE: this is a snapshot. Re-run it immediately before pushing --")
        print("      a single env-API change between now and then makes it non-zero.")
    else:
        print("DO NOT push render.yaml until each line above is an intended change.")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
