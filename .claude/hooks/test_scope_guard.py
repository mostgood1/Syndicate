#!/usr/bin/env python3
"""Drives `scope-guard.py` against THROWAWAY trees.

Never asserts against `.syndicate/*.md` in the primary tree or any worktree --
`learnings.md` 2026-08-20 makes that FORBIDDEN, and this suite would otherwise
pass or fail on whatever another session did to `lanes.md` today. Every case
below builds its own tree and its own lane ledger.

THE MUST-WARN CASES COME FIRST, for the reason `test_lane_postwrite_check.py`
states: a hook like this fails silently by default -- every bug in it makes it
QUIETER, not louder -- so a suite that only checked the allow cases would stay
green on a completely inert hook. `ledger-append-guard` read as passing for its
entire existence while being inert.

THE ONCE-PER-AREA CONTRACT IS TESTED IN BOTH DIRECTIONS, because it is the only
part that can fail in the expensive direction. Too quiet and the guard is
pointless; too loud and it gets switched off, which is how this repo has already
lost two guards. So: a first edit in a new area MUST speak, and the second edit
in that same area MUST be silent.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scope-guard.py")

PASS = FAIL = 0
_TMP = []
_SLOTS = set()  # (root, session) this run touched, so it can clean up after itself


def _forget(root, session):
    """Delete the once-per-area slot for (root, session).

    The hook keeps its state in the OS temp dir, deliberately -- a hook that
    littered the tree it guards would be caught by its siblings. But a TEST that
    litters the temp dir is still a test that litters, and these accumulate one
    file per case per run. Recomputed here rather than imported, because the
    hook's filename has a dash in it and is not importable as a module.
    """
    import hashlib
    key = hashlib.sha1(
        (os.path.normcase(os.path.abspath(root)) + "|" + session).encode("utf-8")
    ).hexdigest()[:16]
    try:
        os.remove(os.path.join(tempfile.gettempdir(),
                               "syndicate-scope-seen-%s.json" % key))
    except OSError:
        pass


def check(label, got, want, extra=""):
    global PASS, FAIL
    ok = got == want
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print("  %s  %-58s got=%s want=%s %s"
          % ("PASS" if ok else "FAIL", label, got, want, extra))


def contains(label, haystack, needle):
    global PASS, FAIL
    ok = needle in haystack
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print("  %s  %-58s needle=%r" % ("PASS" if ok else "FAIL", label, needle))
    if not ok:
        print("        stderr was: %r" % haystack[:400])


LANE = """## OPEN

### my-lane — OPEN — opened 2026-09-08 — session test
- Goal: prove the thing that this lane exists to prove, and nothing else
- Files: `syndicate/features/nfl/cards.py`, `scripts/build_nfl.py`
- Blocked by: none
"""

NO_CLAIMS_LANE = """## OPEN

### my-lane — OPEN — opened 2026-09-08 — session test
- Goal: a lane whose claims were all released
- Files: NONE — all claims RELEASED at checkpoint.
- Blocked by: none
"""

# Every lane header in `lanes.md` is em-dash delimited by the ledger's own rule,
# so goals routinely carry U+2014. Writing one to a cp1252 console raises
# UnicodeEncodeError, `__main__` catches it, and the guard exits 0 -- silent on
# exactly the lanes that follow the house style. Caught live 2026-09-08.
EMDASH_LANE = """## OPEN

### my-lane — OPEN — opened 2026-09-08 — session test
- Goal: prove the thing — verbatim, em-dash and all — and nothing else
- Files: `syndicate/features/nfl/cards.py`
- Blocked by: none
"""


def tree(lanes_text=LANE, lane_slug="my-lane", session="s-0001"):
    root = tempfile.mkdtemp(prefix="scope-guard-test-")
    _TMP.append(root)
    os.makedirs(os.path.join(root, ".syndicate"))
    with open(os.path.join(root, ".syndicate", "lanes.md"), "w",
              encoding="utf-8") as fh:
        fh.write(lanes_text)
    if lane_slug:
        with open(os.path.join(root, ".syndicate", ".current-lane." + session),
                  "w", encoding="utf-8") as fh:
            fh.write(lane_slug)
    return root


def run(root, rel_path, session="s-0001", tool="Edit", env_off=False,
        abs_path=None):
    """(rc, stderr) for one PostToolUse call naming `rel_path`.

    `abs_path` overrides the join, for the case where the written file is not
    under the tree that holds the ledger at all.
    """
    payload = {
        "tool_name": tool,
        "session_id": session,
        "cwd": root,
        "tool_input": {
            "file_path": abs_path or os.path.join(root, rel_path)},
    }
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = root
    if env_off:
        env["SYNDICATE_SCOPE_GUARD"] = "off"
    else:
        env.pop("SYNDICATE_SCOPE_GUARD", None)
    _SLOTS.add((root, session))
    p = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stderr


print("MUST WARN -- if any of these is 0 the guard is inert")

root = tree(session="warn-1")
rc, err = run(root, "syndicate/features/mlb/cards.py", session="warn-1")
check("out-of-area write warns", rc, 2)
contains("names the offending path", err, "syndicate/features/mlb/cards.py")
contains("names the lane", err, "my-lane")
contains("prints the Goal VERBATIM", err,
         "prove the thing that this lane exists to prove, and nothing else")
contains("names the declared areas", err, "syndicate/features/nfl")
contains("asks the question", err, "IS THIS THE GOAL, OR A LEAD?")
# The gradient is the fix, not the warning. If the guard stops naming the CHEAP
# path it is back to telling a session it is drifting and leaving the expensive
# option (7 steps of collision checking) as the only one on offer.
contains("offers the CHEAP path, not just the lane", err, "/lead")

root = tree(lane_slug=None, session="warn-2")
rc, err = run(root, "syndicate/features/mlb/cards.py", session="warn-2")
check("no lane held warns", rc, 2)
contains("says NO LANE", err, "NO LANE")

root = tree(lanes_text=NO_CLAIMS_LANE, session="warn-3")
rc, err = run(root, "syndicate/features/mlb/cards.py", session="warn-3")
check("lane with no parseable claims warns", rc, 2)
contains("points at check_lane_claims", err, "check_lane_claims.py")

root = tree(lanes_text=EMDASH_LANE, session="warn-4")
rc, err = run(root, "syndicate/features/mlb/cards.py", session="warn-4")
check("a non-ASCII goal still WARNS, never crashes to silence", rc, 2)
contains("and the em-dash goal is still carried", err, "prove the thing")

print()
print("ONCE PER AREA -- both directions")

root = tree(session="once-1")
rc1, _ = run(root, "syndicate/features/mlb/cards.py", session="once-1")
rc2, _ = run(root, "syndicate/features/mlb/picks.py", session="once-1")
rc3, err3 = run(root, "syndicate/features/wnba/cards.py", session="once-1")
check("first edit in a new area speaks", rc1, 2)
check("second edit in THAT SAME area is silent", rc2, 0)
check("first edit in a DIFFERENT new area speaks", rc3, 2)
contains("and names the new area", err3, "syndicate/features/wnba")

root = tree(session="once-2")
run(root, "syndicate/features/mlb/cards.py", session="once-2")
rc, _ = run(root, "syndicate/features/mlb/cards.py", session="once-2")
check("same FILE twice is silent", rc, 0)

# A second session must get its own slot -- a shared one is the bug this
# directory refuses to re-make (`.syndicate/.current-lane`, 2026-08-19).
root = tree(session="once-3")
with open(os.path.join(root, ".syndicate", ".current-lane.other-sess"), "w",
          encoding="utf-8") as fh:
    fh.write("my-lane")
run(root, "syndicate/features/mlb/cards.py", session="once-3")
rc, _ = run(root, "syndicate/features/mlb/cards.py", session="other-sess")
check("a DIFFERENT session is not silenced by mine", rc, 2)

print()
print("MUST BE SILENT -- if any of these is 2 the guard is noise")

root = tree(session="ok-1")
check("write inside a declared area",
      run(root, "syndicate/features/nfl/picks.py", session="ok-1")[0], 0)

root = tree(session="ok-2")
check("write to the declared file itself",
      run(root, "syndicate/features/nfl/cards.py", session="ok-2")[0], 0)

root = tree(session="ok-3")
check("tests/ is never drift",
      run(root, "tests/test_mlb_cards.py", session="ok-3")[0], 0)

root = tree(session="ok-4")
check("a test_* basename anywhere is never drift",
      run(root, "syndicate/features/mlb/test_cards.py", session="ok-4")[0], 0)

root = tree(session="ok-5")
check(".syndicate/ is exempt (checkpointing is not drift)",
      run(root, ".syndicate/log/2026-09-08.md", session="ok-5")[0], 0)

root = tree(session="ok-6")
check(".claude/ is exempt",
      run(root, ".claude/hooks/whatever.py", session="ok-6")[0], 0)

root = tree(session="ok-7")
check("a non-Edit tool is ignored",
      run(root, "syndicate/features/mlb/cards.py", session="ok-7",
          tool="Bash")[0], 0)

root = tree(session="ok-8")
check("SYNDICATE_SCOPE_GUARD=off silences it",
      run(root, "syndicate/features/mlb/cards.py", session="ok-8",
          env_off=True)[0], 0)

root = tree(session="")
check("no session id -> no shared slot, stays quiet",
      run(root, "syndicate/features/mlb/cards.py", session="")[0], 0)

# A `relpath` that escapes the tree is not scope-judgeable, and firing on it
# would write a bogus area into the once-per-area slot -- silencing the REAL
# area of that name for the rest of the session.
outside = tempfile.mkdtemp(prefix="scope-guard-outside-")
_TMP.append(outside)
root = tree(session="ok-9")
check("a write OUTSIDE the ledger's tree is not judged",
      run(root, "", session="ok-9",
          abs_path=os.path.join(outside, "cards.py"))[0], 0)

print()
print("FAILS OPEN")

root = tempfile.mkdtemp(prefix="scope-guard-test-")
_TMP.append(root)
check("no ledger at all -> silent",
      run(root, "syndicate/features/mlb/cards.py", session="open-1")[0], 0)

p = subprocess.run([sys.executable, HOOK], input="{not json",
                   capture_output=True, text=True)
check("malformed payload -> silent", p.returncode, 0)

for r, s in _SLOTS:
    _forget(r, s)
for d in _TMP:
    shutil.rmtree(d, ignore_errors=True)

print()
print("%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
