#!/usr/bin/env python3
"""PreToolUse hook - routes ALL production deploys through the coordinator session.

WHY A HOOK AND NOT A PARAGRAPH. `coordination-protocol.md` section 3 already said
"agents prepare, humans execute", written 2026-08-15. It was never followed, and
that section's own opening principle explains why: "any rule of the form
'sessions should remember to check X' fails the first time a session is mid-task
and context-pressured." Exactly one request was ever filed; it sat unexecuted for
two days while direct deploys continued. Three sessions held the refresh-worker
claim inside 70 minutes that night and the live SHA moved twice underneath a
rebase. This file is that section rewritten as something that cannot be forgotten.

WHAT IT GUARDS, and why exactly these three shapes:

  1. `scripts/render_deploy.py` -- the sanctioned entrypoint. Its own docstring
     says the permission rule is `Bash(python scripts/render_deploy.py *)`, so it
     is the choke point every legitimate deploy already shares.
  2. A POST to `/v1/services/<id>/deploys` -- the raw-curl bypass. Matched on
     POST INTENT ONLY. `render_events.py`, `render_logs.py`, `oom_band_report.py`
     and `check_deploy_safety.py` read the Render API constantly and must never
     be blocked; a guard that blocks reads is one people disable.
  3. A push carrying `render.yaml` -- because `blueprint_sync` BYPASSES
     `autoDeploy = no`. Measured 2026-08-08: a `render.yaml` push rewrote env
     vars on two live services and 502'd every route for ~2 minutes with nobody
     having ordered a deploy. "Pushing to main ships nothing" is true of CODE and
     false of CONFIG, so a config push is a deploy and belongs here.

FAIL OPEN, DELIBERATELY, EVERYWHERE. Unreadable payload, no coordinator
registered, git unavailable, malformed grant -- all allow the command. This
matches `lane-guard.py`: a broken guard that blocks real work is worse than no
guard, and it is the difference between a mechanism people keep and one they rip
out. The failure this exists to stop (two sessions deploying different SHAs to
one service minutes apart) needs the guard to be RIGHT, not absolute.

OFF SWITCH: delete `.syndicate/coordinator.id`. No coordinator, no guard.
ESCAPE HATCH: `.syndicate/deploy/grants/<session_id>.json`, written by the
coordinator, with an `expires_epoch`.
"""
import json
import os
import re
import subprocess
import sys
import time

TOOLS = ("Bash", "PowerShell")

RENDER_DEPLOY_SCRIPT = re.compile(r"render_deploy\.py", re.I)
DEPLOYS_ENDPOINT = re.compile(r"/v1/services/[^/\s'\"]+/deploys", re.I)
# POST intent. `-d`/`--data` imply POST for curl even without -X.
POST_INTENT = re.compile(
    r"(-X\s*'?POST|--request\s+'?POST|-Method\s+'?Post|--data\b|--data-raw\b|\s-d\s)", re.I)
GIT_PUSH = re.compile(r"\bgit\s+(?:-\S+\s+|--\S+\s+)*push\b", re.I)


def _root():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _read(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read().strip()
    except Exception:
        return ""


def _push_carries_render_yaml(root):
    """True only when we can PROVE the push carries render.yaml. Unknown -> False.

    An unknown must NOT land on the blocking branch: git can be slow, detached,
    or upstream-less, and a deploy guard that blocks every push because it could
    not run `git` is a guard that gets removed the same afternoon. This is the
    one place the guard is deliberately permissive about its own ignorance.
    """
    for rev in ("@{upstream}..HEAD", "origin/main..HEAD"):
        try:
            out = subprocess.run(["git", "diff", "--name-only", rev],
                                 cwd=root, capture_output=True, timeout=8)
            if out.returncode == 0:
                return "render.yaml" in out.stdout.decode("utf-8", "replace")
        except Exception:
            continue
    return False


def _grant(root, session_id):
    """An unexpired grant for this session, or None. A malformed grant is NOT a grant."""
    if not session_id:
        return None
    path = os.path.join(root, ".syndicate", "deploy", "grants", f"{session_id}.json")
    try:
        with open(path, encoding="utf-8-sig") as fh:
            g = json.load(fh)
        if float(g.get("expires_epoch", 0)) < time.time():
            return None
        return g
    except Exception:
        return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("tool_name") not in TOOLS:
        return 0

    cmd = str((payload.get("tool_input") or {}).get("command") or "")
    if not cmd:
        return 0

    root = _root()
    coordinator = _read(os.path.join(root, ".syndicate", "coordinator.id"))
    if not coordinator:
        return 0                       # no coordinator registered: stand down

    session_id = re.sub(r"[^A-Za-z0-9._-]", "",
                        str(payload.get("session_id") or ""))[:128]
    if session_id and session_id == coordinator:
        return 0                       # this IS the coordinator

    if RENDER_DEPLOY_SCRIPT.search(cmd):
        kind = "a Render deploy (`render_deploy.py`)"
    elif DEPLOYS_ENDPOINT.search(cmd) and POST_INTENT.search(cmd):
        kind = "a Render deploy (POST to /deploys)"
    elif GIT_PUSH.search(cmd) and _push_carries_render_yaml(root):
        kind = ("a push carrying `render.yaml`, which fires `blueprint_sync` and "
                "APPLIES TO PRODUCTION even though autoDeploy is off")
    else:
        return 0

    grant = _grant(root, session_id)
    if grant:
        sys.stderr.write(
            "DEPLOY GRANT IN EFFECT for this session "
            f"(service={grant.get('service', 'any')}; "
            f"granted for: {grant.get('note', 'no note recorded')}).\n"
            "Allowed. Write the outcome to .syndicate/deploys.md with a MEASUREMENT, "
            "and tell the coordinator when it lands.\n")
        return 0

    sys.stderr.write(
        f"BLOCKED: this command is {kind}.\n"
        "\n"
        "Deploys are owned by the COORDINATOR session, which serialises them "
        "across all sessions, holds the sim-in-flight and blueprint_sync "
        "guardrails, and records the measurement afterwards. Not a trust "
        "question: three sessions held the refresh-worker claim in 70 minutes on "
        "2026-08-15 and the live SHA moved twice underneath a rebase.\n"
        "\n"
        "TO GET THIS DEPLOYED -- write the request, then carry on with other "
        "work. Do not block waiting for a reply:\n"
        "\n"
        "  .syndicate/deploy/requests/<UTC-timestamp>-<lane>.md\n"
        "    service:  web | refresh-worker | live-odds-worker\n"
        "    sha:      the commit, and what it is cut from\n"
        "    reason:   what it fixes, in one line\n"
        "    verify:   the READING that proves it worked, and where to take it\n"
        "    rollback: the SHA to go back to\n"
        "    urgency:  and say plainly when nothing is blocked\n"
        "\n"
        "`verify:` is the field that matters. \"Watch the memory profile\" is not "
        "a verification; \"LEDGER_CHUNKS_ACCEPTED falls below 830,832,574 within "
        "one bundle\" is.\n"
        "\n"
        "If it is genuinely urgent, message the coordinator session rather than "
        "working around this. Contract: .syndicate/coordinator.md\n")
    return 2


try:
    sys.exit(main())
except Exception:
    sys.exit(0)                        # fail open, always
