#!/usr/bin/env python3
"""Drives `lane-postwrite-check.py` against THROWAWAY trees.

Never asserts against `.syndicate/*.md` in the primary tree or any worktree --
`learnings.md` 2026-08-20 makes that FORBIDDEN, and for a good reason: a guard
test pinned to the live ledger passes or fails on what other sessions did today.

The MUST-WARN cases come first and are the ones that matter. A hook like this
fails silently by default -- every bug in it makes it quieter, not louder -- so
a suite that only checks the allow cases would stay green on a completely inert
hook. That is not hypothetical here: `ledger-append-guard` read as passing for
its entire existence while being inert, and this directory has the note about
it.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "lane-postwrite-check.py")
SESSION = "test-session-0001"

PASS = FAIL = 0


def check(label, got, want, extra=""):
    global PASS, FAIL
    ok = got == want
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print("  %s  %-58s got=%s want=%s %s"
          % ("PASS" if ok else "FAIL", label, got, want, extra))


def lanes(*blocks):
    return "## OPEN\n\n" + "\n\n".join(blocks) + "\n"


def lane(slug, status, *paths):
    files = ", ".join("`%s`" % p for p in paths)
    return ("### %s — %s — opened 2026-09-03 — session x\n"
            "- Goal: test fixture\n"
            "- Files: %s\n"
            "- Blocked by: none\n" % (slug, status, files))


def make_tree(lanes_md, my_lane, files):
    root = tempfile.mkdtemp(prefix="lane-postwrite-test-")
    os.makedirs(os.path.join(root, ".syndicate"))
    with open(os.path.join(root, ".syndicate", "lanes.md"), "w",
              encoding="utf-8") as fh:
        fh.write(lanes_md)
    if my_lane is not None:
        with open(os.path.join(root, ".syndicate", ".current-lane." + SESSION),
                  "w", encoding="utf-8") as fh:
            fh.write(my_lane)
    for rel, body in files.items():
        p = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
    return root


def run(root, pre=False, tool="Bash", env_extra=None, session=SESSION):
    payload = {"tool_name": tool, "cwd": root, "session_id": session}
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = root
    env.pop("SYNDICATE_LANE_POSTCHECK", None)
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, HOOK] + (["--pre"] if pre else [])
    p = subprocess.run(cmd, input=json.dumps(payload), capture_output=True,
                       text=True, env=env)
    return p.returncode, (p.stderr or "")


def touch(root, rel, body):
    """A SHELL-STYLE write: no Edit tool, no hook in the way. The whole point."""
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    # mtime_ns alone can collide inside one filesystem tick, so every fixture
    # write also changes the SIZE. The hook compares (mtime, size) precisely so
    # that a same-tick rewrite is still caught by the second term.
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(body)


TREES = []


def tree(*a, **k):
    r = make_tree(*a, **k)
    TREES.append(r)
    return r


TWO_LANES = lanes(
    lane("mine", "OPEN", "syndicate/features/mine.py"),
    lane("theirs", "OPEN", "syndicate/features/theirs.py",
         "tests/test_theirs.py"),
    lane("closed-lane", "CLOSED", "syndicate/features/closed.py"),
    lane("ledger-holder", "OPEN", ".syndicate/state.md"),
)
SEED = {
    "syndicate/features/mine.py": "mine\n",
    "syndicate/features/theirs.py": "theirs\n",
    "tests/test_theirs.py": "t\n",
    "syndicate/features/closed.py": "closed\n",
    "syndicate/features/unclaimed.py": "free\n",
    ".syndicate/state.md": "state\n",
}

print("MUST WARN (if these pass, the hook is inert -- the failure mode it has):")

r = tree(TWO_LANES, "mine", SEED)
run(r, pre=True)
touch(r, "syndicate/features/theirs.py", "theirs, rewritten by a heredoc\n")
rc, err = run(r)
check("shell write to ANOTHER lane's file is REPORTED", rc, 2)
check("  ^ names the owning lane", "theirs" in err, True)
check("  ^ names the claimed path", "syndicate/features/theirs.py" in err, True)
check("  ^ names YOUR lane", "'mine'" in err, True)

r = tree(TWO_LANES, "mine", SEED)
run(r, pre=True)
os.remove(os.path.join(r, "syndicate", "features", "theirs.py"))
rc, err = run(r)
check("DELETING another lane's file is REPORTED", rc, 2)
check("  ^ says DELETED, not modified", "DELETED" in err, True)

r = tree(TWO_LANES, "mine", SEED)
run(r, pre=True)
touch(r, "syndicate/features/theirs.py", "a\n")
touch(r, "tests/test_theirs.py", "bb\n")
rc, err = run(r)
check("BOTH files of one lane reported", err.count("claimed by OPEN lane"), 2)

print()
print("MUST BE SILENT -- each for its own reason:")

r = tree(TWO_LANES, "mine", SEED)
run(r, pre=True)
touch(r, "syndicate/features/mine.py", "my own file, edited freely\n")
check("writing YOUR OWN claimed file", run(r)[0], 0)

r = tree(TWO_LANES, "mine", SEED)
run(r, pre=True)
touch(r, "syndicate/features/unclaimed.py", "nobody claims this\n")
check("writing a file NO lane claims", run(r)[0], 0)

r = tree(TWO_LANES, "mine", SEED)
run(r, pre=True)
touch(r, "syndicate/features/closed.py", "a CLOSED lane holds nothing\n")
check("writing a CLOSED lane's former file", run(r)[0], 0)

r = tree(TWO_LANES, "mine", SEED)
run(r, pre=True)
touch(r, ".syndicate/state.md", "every session writes the ledger\n")
check("writing .syndicate/ (exempt, as in lane-guard)", run(r)[0], 0)

r = tree(TWO_LANES, "mine", SEED)
run(r, pre=True)
check("a command that changed nothing", run(r)[0], 0)

r = tree(TWO_LANES, "mine", SEED)
touch(r, "syndicate/features/theirs.py", "changed with NO pre snapshot\n")
check("no pre snapshot -> nothing to compare, stays quiet", run(r)[0], 0)

r = tree(TWO_LANES, "mine", SEED)
run(r, pre=True)
touch(r, "syndicate/features/theirs.py", "x\n")
first = run(r)[0]
check("the same change is NOT re-reported (snapshot consumed)",
      run(r)[0], 0, "(first call was %d)" % first)

r = tree(TWO_LANES, "mine", SEED)
run(r, pre=True)
touch(r, "syndicate/features/theirs.py", "y\n")
check("off switch honoured",
      run(r, env_extra={"SYNDICATE_LANE_POSTCHECK": "off"})[0], 0)

r = tree(TWO_LANES, "mine", SEED)
run(r, pre=True, tool="Read")
touch(r, "syndicate/features/theirs.py", "z\n")
check("a non-shell tool is ignored", run(r, tool="Read")[0], 0)

r = tree(TWO_LANES, None, SEED)
run(r, pre=True)
touch(r, "syndicate/features/theirs.py", "no marker at all\n")
rc, err = run(r)
check("no lane marker -> still reports (claim is real, holder is not you)",
      rc, 2)

print()
print("THE PRE PASS MUST NEVER BLOCK:")

r = tree("not a ledger at all, just junk {{{", "mine", SEED)
check("unparseable lanes.md", run(r, pre=True)[0], 0)

r = tree(TWO_LANES, "mine", SEED)
os.remove(os.path.join(r, ".syndicate", "lanes.md"))
check("lanes.md missing entirely", run(r, pre=True)[0], 0)
check("  ^ and the post pass is quiet too", run(r)[0], 0)

r = tree(TWO_LANES, "mine", SEED)
check("no session id -> no shared snapshot slot, exits clean",
      run(r, pre=True, session="")[0], 0)

print()
print("SESSIONS DO NOT SHARE A SNAPSHOT SLOT:")
r = tree(TWO_LANES, "mine", SEED)
run(r, pre=True, session="session-A")
run(r, pre=True, session="session-B")
touch(r, "syndicate/features/theirs.py", "written during BOTH windows\n")
a = run(r, session="session-A")[0]
b = run(r, session="session-B")[0]
check("session A sees its own window", a, 2)
check("session B's slot was not consumed by A", b, 2)

for t in TREES:
    shutil.rmtree(t, ignore_errors=True)

print()
print("%d/%d passed" % (PASS, PASS + FAIL))
sys.exit(1 if FAIL else 0)
