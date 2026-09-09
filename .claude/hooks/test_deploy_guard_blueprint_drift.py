"""Prove the render.yaml branch of deploy-guard actually fires and refuses.

Loads the hook with its fail-open tail stripped (so a real exception would be
visible rather than silently exiting 0), forces the "push carries render.yaml"
detection to True, and asserts the guard returns 2 with the drift message.

Also asserts the NEGATIVE case: with the override env var set, the same push is
allowed through -- so the escape hatch documented in the refusal text is real.
"""
import io
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# PIN THE ROOT. deploy-guard resolves _root() from CLAUDE_PROJECT_DIR, which in a
# real hook run points at the PRIMARY tree -- so without this the test would look
# for scripts/check_blueprint_drift.py in a tree that may not have it yet, the
# checker would be reported missing, the branch would not fire, and the test
# would fail for a reason that has nothing to do with the code under test.
os.environ["CLAUDE_PROJECT_DIR"] = REPO
os.chdir(REPO)
HOOK = os.path.join(REPO, ".claude", "hooks", "deploy-guard.py")


def load():
    src = io.open(HOOK, encoding="utf-8-sig").read()
    for tail in (
        "try:\n    sys.exit(main())\nexcept Exception:\n    sys.exit(0)",
        "try:\r\n    sys.exit(main())\r\nexcept Exception:\r\n    sys.exit(0)",
    ):
        src = src.replace(tail, "")
    ns = {"__name__": "dg_under_test"}
    exec(compile(src, HOOK, "exec"), ns)
    return ns


def run(ns, allow_override):
    payload = {"tool_name": "Bash", "tool_input": {"command": "git push origin HEAD:main"}, "session_id": "t"}
    sys.stdin = io.StringIO(json.dumps(payload))
    err = io.StringIO()
    real_err, sys.stderr = sys.stderr, err
    if allow_override:
        os.environ["SYNDICATE_ALLOW_BLUEPRINT_DRIFT"] = "1"
    else:
        os.environ.pop("SYNDICATE_ALLOW_BLUEPRINT_DRIFT", None)
    try:
        code = ns["main"]()
    finally:
        sys.stderr = real_err
    return code, err.getvalue()


ns = load()
# Force the detection that normally shells out to git.
ns["_push_carries_render_yaml"] = lambda root: True

code, err = run(ns, allow_override=False)
print("=== render.yaml push, drift present ===")
print("  exit:", code, "(want 2 = BLOCKED)")
first = [l for l in err.splitlines() if l.strip()][:2]
for line in first:
    print("  |", line[:88])
assert code == 2, f"expected 2, got {code}"
assert "BEHIND" in err and "DRIFT" in err, "refusal text missing the drift verdict"
print("  PASS: blocked, and the message names the drift")

code2, err2 = run(ns, allow_override=True)
print()
print("=== same push, SYNDICATE_ALLOW_BLUEPRINT_DRIFT=1 ===")
print("  exit:", code2, "(want != 2 = escape hatch works; falls through to lock checks)")
assert "BEHIND" not in err2, "override did not bypass the drift refusal"
print("  PASS: drift refusal bypassed; normal lock logic applies")
os.environ.pop("SYNDICATE_ALLOW_BLUEPRINT_DRIFT", None)
