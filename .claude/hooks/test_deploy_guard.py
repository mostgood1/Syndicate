"""Falsification suite for deploy-guard.py.

Written to prove the guard can BLOCK before any ALLOW is trusted, and that every
ALLOW is allowed for the RIGHT REASON. A guard whose test suite only ever sees
green is indistinguishable from a guard that returns 0 unconditionally -- that
exact shape has burned this repo before (three no-op tests passing on 0.0 == 0.0).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(ROOT, ".claude", "hooks", "deploy-guard.py")
GRANTS = os.path.join(ROOT, ".syndicate", "deploy", "grants")

# Read the CURRENT coordinator rather than hardcoding a session id: this suite
# outlives any one coordinator, and a stale id here would silently turn the
# "from the COORDINATOR" case into a second copy of the "another session" case
# -- i.e. a test that passes for the wrong reason.
with open(os.path.join(ROOT, ".syndicate", "coordinator.id"), encoding="utf-8-sig") as _fh:
    COORD = _fh.read().strip()
assert COORD, "no coordinator registered; this suite has nothing to test"
OTHER = "definitely-not-the-coordinator-session"

DEPLOY = "py -3 scripts/render_deploy.py --service web --commit abc1234"
READONLY = "py -3 scripts/render_events.py --service refresh-worker --failures-only"
GET_DEPLOYS = ("curl -s -H \"Authorization: Bearer $KEY\" "
               "https://api.render.com/v1/services/srv-abc/deploys?limit=5")
POST_DEPLOYS = ("curl -s -X POST -H \"Authorization: Bearer $KEY\" "
                "https://api.render.com/v1/services/srv-abc/deploys")
SAFETY = "py -3 scripts/check_deploy_safety.py --service refresh-worker"
PUSH = "git push origin main"


def run(cmd, session=OTHER, tool="Bash", root=ROOT, raw=None):
    payload = raw if raw is not None else json.dumps({
        "tool_name": tool, "session_id": session,
        "tool_input": {"command": cmd}})
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root)
    p = subprocess.run([sys.executable, HOOK], input=payload.encode(),
                       capture_output=True, env=env)
    return p.returncode, p.stderr.decode("utf-8", "replace")


results = []


def check(name, got, want, note=""):
    ok = got == want
    results.append((ok, name, got, want, note))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:52s} exit={got} want={want} {note}")


print("MUST BLOCK (if any of these pass, the guard is inert):")
rc, err = run(DEPLOY)
check("render_deploy.py from another session", rc, 2)
assert "BLOCKED" in err and "deploy/requests" in err, "block message must tell them what to do"
check("  ^ message names the request path", int("deploy/requests" in err), 1)
rc, _ = run(POST_DEPLOYS)
check("POST to /deploys from another session", rc, 2)
rc, _ = run(DEPLOY, tool="PowerShell")
check("render_deploy.py via PowerShell tool", rc, 2)

print("\nMUST ALLOW -- and each for its own reason:")
rc, _ = run(DEPLOY, session=COORD)
check("render_deploy.py from the COORDINATOR", rc, 0)
rc, _ = run(READONLY)
check("render_events.py (read-only Render API)", rc, 0)
rc, _ = run(GET_DEPLOYS)
check("GET /deploys (no POST intent)", rc, 0)
rc, _ = run(SAFETY)
check("check_deploy_safety.py (never deploys)", rc, 0)
rc, _ = run(PUSH)
check("git push with no render.yaml in the diff", rc, 0)
rc, _ = run("ls -la")
check("an ordinary unrelated command", rc, 0)
rc, _ = run(DEPLOY, tool="Read")
check("non-shell tool carrying the same text", rc, 0)

print("\nFAIL-OPEN paths (a broken guard must not block real work):")
rc, _ = run(None, raw="{not json at all")
check("malformed payload", rc, 0)
rc, _ = run(DEPLOY, raw=json.dumps({"tool_name": "Bash", "tool_input": {}}))
check("payload with no command", rc, 0)
tmp = tempfile.mkdtemp()
rc, _ = run(DEPLOY, root=tmp)
check("no coordinator.id registered (OFF SWITCH)", rc, 0)
shutil.rmtree(tmp, ignore_errors=True)

print("\nGRANTS (the escape hatch, and its expiry):")
os.makedirs(GRANTS, exist_ok=True)
gpath = os.path.join(GRANTS, f"{OTHER}.json")
try:
    with open(gpath, "w", encoding="utf-8") as fh:
        json.dump({"service": "web", "expires_epoch": time.time() + 600,
                   "note": "falsification suite"}, fh)
    rc, err = run(DEPLOY)
    check("unexpired grant allows", rc, 0, "(grant msg)" if "GRANT" in err else "(NO MSG!)")

    with open(gpath, "w", encoding="utf-8") as fh:
        json.dump({"service": "web", "expires_epoch": time.time() - 1,
                   "note": "expired"}, fh)
    rc, _ = run(DEPLOY)
    check("EXPIRED grant does not allow", rc, 2)

    with open(gpath, "w", encoding="utf-8") as fh:
        fh.write("{ this is not valid json")
    rc, _ = run(DEPLOY)
    check("malformed grant is NOT a grant", rc, 2)
finally:
    if os.path.exists(gpath):
        os.remove(gpath)

bad = [r for r in results if not r[0]]
print(f"\n{len(results) - len(bad)}/{len(results)} passed")
sys.exit(1 if bad else 0)
