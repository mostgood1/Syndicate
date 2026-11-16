"""Refuse a `render.yaml` push while the file is behind LIVE production env.

WHY THIS EXISTS, and it is not a hypothetical.

`render.yaml` is not a description of production. It is a PROPOSAL TO REPLACE
production: pushing it fires `blueprint_sync`, which rewrites the WHOLE env
block on every service in the file regardless of `autoDeploy = no`.

MEASURED 2026-09-08, key-by-key against each service's live `/v1/services/<id>/env-vars`:

    service            yaml   live   sync would DELETE   would CHANGE
    web                  52     84          33                1
    refresh-worker       84    161          77                1
    live-odds-worker     76    132          56                1

**166 live env vars would have been deleted and `ODDS_API_KEY` overwritten on
all three services** -- including `SYNDICATE_EXECUTION_MODE=live`,
`SYNDICATE_EXECUTION_LIVE_ARMED=1` and the spend caps of a LIVE-MONEY execution
system (`MAX_ORDER_DOLLARS`, `MAX_DAY_DOLLARS`, `..._ALL_VENUES`). The caps have
code defaults, so deletion is not "unlimited" -- it is worse than obvious: it
silently swaps an operator's deliberate limits for whatever the code happens to
default to, with no diff and no log line.

WHY A CHECK AND NOT A RULE. `learnings.md` now carries this as FORBIDDEN, and
prose does not stop a push. `deploy-guard.py` DOES already detect a push
carrying `render.yaml` and demands a claim on all three services -- but a claim
is COORDINATION, not correctness: three locks and a CLEAR preflight would have
let this through. Worse, `deploy-guard.py`'s own header advertises
"`scripts/deploy_preflight.py`   job liveness + render.yaml blast radius", and
preflight contains NO env-var logic whatsoever. The guard was promising a check
nobody had written. This is that check.

USAGE
    py -3 scripts/check_blueprint_drift.py            # all services in render.yaml
    py -3 scripts/check_blueprint_drift.py --json

EXIT CODES
    0  no drift -- a sync would change nothing. `render.yaml` is safe to push.
    1  DRIFT -- a sync would delete or change live keys. Do not push.
    2  could not determine (no API key, API error). NOT a pass: unknown must not
       read as safe, which is the whole failure mode this file guards.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Service ids live in deploy_preflight so there is ONE table, not two that drift
# apart -- the same reasoning `LIVE_LIMIT_FIELDS` uses in execution_guard.py.
import deploy_preflight as dp  # noqa: E402

import os  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

# THE LAST RENDER API READ IN THE REPO `[2026-11-15, lane render-retirement]`.
# deploy_preflight's Render helpers were removed with the rest of its Render path,
# and moved here UNCHANGED, because this script still reads the suspended services'
# env when someone pushes `render.yaml`: the user decided on 2026-11-08 (todo #766
# D3) to keep `render.yaml` and this drift check as they are. Whether to retire it
# too is put back to the user in #766. Until they decide, a `render.yaml` push still
# needs RENDER_API_KEY here, or `SYNDICATE_ALLOW_BLUEPRINT_DRIFT=1`.


def _env_files():
    """`.env` in THIS tree, then in the main worktree. A `.env` beside the script wins."""
    seen, out = set(), []
    for root in (REPO_ROOT, dp._main_worktree_root()):
        path = (root / ".env").resolve()
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            out.append(path)
    return out


def _env_value(name: str) -> str:
    for path in _env_files():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith(name):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _api_key() -> str:
    value = str(os.environ.get("RENDER_API_KEY") or "").strip()
    if value:
        return value
    value = _env_value("RENDER_API_KEY")
    if value:
        return value
    raise SystemExit("RENDER_API_KEY not set in the environment or .env")


def _get(url: str, key: str):
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # A throttled read must not render as "no drift".
            if exc.code != 429 or attempt == 5:
                raise
            time.sleep(3.0 * (attempt + 1))
    raise RuntimeError("unreachable")


def _live_env(service_id: str, api_key: str) -> dict[str, str]:
    """Every live env var for one service.

    PAGINATED AT 100 ON PURPOSE: `limit` > 100 returns HTTP 400 (CLAUDE.md), and
    a silently truncated page would under-report the drift -- reporting LESS
    danger than exists is the one error this file must not make.
    """
    out: dict[str, str] = {}
    cursor = None
    while True:
        url = f"https://api.render.com/v1/services/{service_id}/env-vars?limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        page = _get(url, api_key)
        if not page:
            break
        for row in page:
            env = row.get("envVar") or row
            if "key" in env:
                out[env["key"]] = env.get("value")
            cursor = row.get("cursor") or cursor
        if len(page) < 100:
            break
    return out


def _yaml_env() -> dict[str, dict[str, str]]:
    import yaml

    doc = yaml.safe_load((REPO_ROOT / "render.yaml").read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for svc in doc.get("services", []) or []:
        # A `keyvalue` service (Redis) carries no env block at all -- 0 envVars
        # in the file and nothing to sync -- so it cannot delete or overwrite
        # anything. Skipped as NOT APPLICABLE rather than reported UNKNOWN: an
        # unknown that is really a non-question is noise, and here it did real
        # harm -- it set the exit code to 2 and SUPPRESSED the DRIFT verdict on
        # the three services that actually had drift.
        if str(svc.get("type") or "").lower() == "keyvalue":
            continue
        envs: dict[str, str] = {}
        for entry in svc.get("envVars", []) or []:
            key = entry.get("key")
            if not key:
                continue
            # An entry with no literal `value` (fromService / sync:false /
            # generateValue) does NOT propose a value, so it cannot delete or
            # overwrite one. Recorded as present-but-unvalued rather than
            # skipped, so "only in live" stays honest.
            envs[key] = str(entry["value"]) if "value" in entry else None
        out[svc.get("name")] = envs
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        api_key = _api_key()
    except Exception as exc:  # noqa: BLE001
        print(f"UNKNOWN: cannot read RENDER_API_KEY ({type(exc).__name__}). "
              f"This is NOT a pass -- unknown must not read as safe.", flush=True)
        return 2
    if not api_key:
        print("UNKNOWN: no RENDER_API_KEY. This is NOT a pass.", flush=True)
        return 2

    yaml_by_service = _yaml_env()
    report: dict[str, dict] = {}
    # TRACKED SEPARATELY. Folding these into one `worst` let an UNKNOWN on an
    # unrelated service outrank a real DRIFT finding and skip the verdict line
    # entirely -- the check reported nothing actionable while 167 deletions sat
    # in front of it.
    drift = False
    unknown = False

    for name, yaml_env in yaml_by_service.items():
        service_id = dp.SERVICES.get(name) if hasattr(dp, "SERVICES") else None
        if not service_id:
            service_id = _SERVICE_IDS.get(name)
        if not service_id:
            print(f"UNKNOWN: no service id for {name!r}; cannot check it.", flush=True)
            unknown = True
            continue
        try:
            live = _live_env(service_id, api_key)
        except Exception as exc:  # noqa: BLE001
            print(f"UNKNOWN: live env fetch failed for {name} "
                  f"({type(exc).__name__}: {exc}). NOT a pass.", flush=True)
            unknown = True
            continue

        would_delete = sorted(set(live) - set(yaml_env))
        would_change = sorted(
            k for k in (set(yaml_env) & set(live))
            if yaml_env[k] is not None and str(yaml_env[k]) != str(live[k])
        )
        report[name] = {
            "service_id": service_id,
            "yaml_keys": len(yaml_env),
            "live_keys": len(live),
            "would_delete": would_delete,
            "would_change": would_change,
        }
        if would_delete or would_change:
            drift = True

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        total_del = sum(len(v["would_delete"]) for v in report.values())
        total_chg = sum(len(v["would_change"]) for v in report.values())
        for name, v in report.items():
            print(f"=== {name}  ({v['service_id']})  yaml={v['yaml_keys']} live={v['live_keys']}")
            print(f"    a sync would DELETE {len(v['would_delete'])} live key(s)")
            for k in v["would_delete"][:12]:
                print(f"        - {k}")
            if len(v["would_delete"]) > 12:
                print(f"        ... and {len(v['would_delete']) - 12} more")
            print(f"    a sync would CHANGE {len(v['would_change'])} key(s)")
            for k in v["would_change"]:
                print(f"        ~ {k}")
        print()
        if unknown:
            print("NOTE: at least one service could not be checked (see UNKNOWN "
                  "above). That does not soften anything below.")
        if drift:
            print(f"DRIFT: pushing render.yaml would DELETE {total_del} live env var(s) "
                  f"and CHANGE {total_chg}. DO NOT PUSH.")
            print("Reconcile the live values INTO render.yaml first -- and note that "
                  "secrets (ODDS_API_KEY, ADMIN_TOKEN) must NOT be copied into a "
                  "git-tracked file; those belong to the dashboard and want "
                  "`sync: false`.")
        elif not unknown:
            print("CLEAR: render.yaml matches live env on every service. Safe to push.")

    # DRIFT outranks UNKNOWN: with both, the answer to "may I push?" is still a
    # definite NO, and the caller deserves the actionable code rather than the
    # ambiguous one. No drift but an unknown is 2, because unknown must never
    # read as safe.
    if drift:
        return 1
    return 2 if unknown else 0


# Fallback table only if deploy_preflight ever stops exporting one. Kept here
# rather than as the primary so there is no second source of truth to drift.
_SERVICE_IDS = {
    "syndicate": "srv-d88ahvrbc2fs73eodu30",
    "refresh-worker": "srv-d91dpertqb8s73co8ls0",
    "live-odds-worker": "srv-d91dpertqb8s73co8lt0",
}


if __name__ == "__main__":
    raise SystemExit(main())
