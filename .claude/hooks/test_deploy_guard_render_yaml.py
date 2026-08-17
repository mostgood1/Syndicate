"""Exercise the render.yaml-push BLOCKING branch in a throwaway git repo.

The main suite only proved this branch in its ALLOW direction ("push with no
render.yaml"), which on its own is indistinguishable from the branch never
running at all. `blueprint_sync` is the incident this path exists for -- a
render.yaml push rewrote env vars on two live services and 502'd every route --
so the positive case has to be shown, not assumed.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = r"C:\Users\tempadmin\OneDrive\Coding\Syndicate"
HOOK = ROOT + r"\.claude\hooks\deploy-guard.py"
OTHER = "04bb37e1-bbce-48b7-8ac4-426bbf330b78"


def git(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=repo,
                          capture_output=True, text=True)


def run_hook(repo, cmd):
    payload = json.dumps({"tool_name": "Bash", "session_id": OTHER,
                          "tool_input": {"command": cmd}})
    env = dict(os.environ, CLAUDE_PROJECT_DIR=repo)
    p = subprocess.run([sys.executable, HOOK], input=payload.encode(),
                       capture_output=True, env=env)
    return p.returncode, p.stderr.decode("utf-8", "replace")


repo = tempfile.mkdtemp(prefix="rytest")
git(repo, "init", "-q")
git(repo, "config", "user.email", "t@t"); git(repo, "config", "user.name", "t")
os.makedirs(os.path.join(repo, ".syndicate"), exist_ok=True)
with open(os.path.join(repo, ".syndicate", "coordinator.id"), "w") as fh:
    fh.write("some-other-session-id\n")

# base commit, then pretend origin/main is here
with open(os.path.join(repo, "app.py"), "w") as fh:
    fh.write("x = 1\n")
git(repo, "add", "-A"); git(repo, "commit", "-qm", "base")
base = git(repo, "rev-parse", "HEAD").stdout.strip()
git(repo, "update-ref", "refs/remotes/origin/main", base)

# a commit that does NOT touch render.yaml
with open(os.path.join(repo, "app.py"), "w") as fh:
    fh.write("x = 2\n")
git(repo, "add", "-A"); git(repo, "commit", "-qm", "code only")
rc, _ = run_hook(repo, "git push origin main")
print(f"  {'PASS' if rc == 0 else 'FAIL'}  push of CODE only ............... exit={rc} want=0")
ok1 = rc == 0

# now add render.yaml -- this is a production change
with open(os.path.join(repo, "render.yaml"), "w") as fh:
    fh.write("services:\n  - name: web\n")
git(repo, "add", "-A"); git(repo, "commit", "-qm", "blueprint change")
rc, err = run_hook(repo, "git push origin main")
print(f"  {'PASS' if rc == 2 else 'FAIL'}  push carrying render.yaml ....... exit={rc} want=2")
ok2 = rc == 2
ok3 = "blueprint_sync" in err
print(f"  {'PASS' if ok3 else 'FAIL'}  block message names blueprint_sync")
if ok2:
    print("\n  --- what the other session sees ---")
    print("  " + "\n  ".join(err.strip().splitlines()[:3]))

# and the coordinator itself is never blocked
with open(os.path.join(repo, ".syndicate", "coordinator.id"), "w") as fh:
    fh.write(OTHER + "\n")
rc, _ = run_hook(repo, "git push origin main")
print(f"\n  {'PASS' if rc == 0 else 'FAIL'}  same push, but AS coordinator ... exit={rc} want=0")
ok4 = rc == 0

subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", repo], capture_output=True)
sys.exit(0 if all([ok1, ok2, ok3, ok4]) else 1)
