"""Falsification suite for lane-guard's ASCII-hyphen handling.

The defect: `LANE_RE` requires U+2014, so `### slug - OPEN - ...` did not parse
at all and its claimed files were silently UNGUARDED. Measured 2026-08-17 on a
live lane; the digest's count of such headers grew 1 -> 5 in a day while being
reported and ignored.

MUST BLOCK cases come first on purpose: a suite that only ever sees green cannot
distinguish a working guard from one that returns 0 unconditionally.
"""
import json
import os
import subprocess
import sys
import tempfile

# The hook sits NEXT to this file. Deriving it from a repo root computed with
# nested dirname() calls got the path wrong by one level, and python exits 2 for
# "cannot open file" -- so all ten cases returned 2 and the suite read as a
# totally broken fix. Verify the harness can find its subject before trusting a
# single result.
HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lane-guard.py")
assert os.path.exists(HOOK), f"hook not found at {HOOK}"

EM = "—"
CLAIMED = "syndicate/features/shared/thing.py"

LANES_HYPHEN = f"""# lanes
## OPEN

### hyphen-lane - OPEN - **shipped, hyphens by mistake**
- Goal: something
- Files (exclusive to this lane):
  - `{CLAIMED}`
"""

LANES_EMDASH = f"""# lanes
## OPEN

### emdash-lane {EM} OPEN {EM} **well formed**
- Goal: something
- Files (exclusive to this lane):
  - `{CLAIMED}`
"""

LANES_CLOSED_HYPHEN = """# lanes
## OPEN

### closed-hyphen-lane - CLOSED - **done**
- Goal: something
- Files (exclusive to this lane):
  - `syndicate/features/shared/other.py`
"""


def run(lanes_text, current_lane, rel_path=CLAIMED, session="sess-under-test"):
    root = tempfile.mkdtemp(prefix="lgt")
    os.makedirs(os.path.join(root, ".syndicate"), exist_ok=True)
    with open(os.path.join(root, ".syndicate", "lanes.md"), "w",
              encoding="utf-8", newline="") as fh:
        fh.write(lanes_text)
    if current_lane is not None:
        with open(os.path.join(root, ".syndicate", f".current-lane.{session}"),
                  "w", encoding="utf-8") as fh:
            fh.write(current_lane)
    payload = json.dumps({"tool_name": "Edit", "session_id": session,
                          "tool_input": {"file_path": root.replace("\\", "/")
                                         + "/" + rel_path}})
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root.replace("\\", "/"))
    p = subprocess.run([sys.executable, HOOK], input=payload.encode(),
                       capture_output=True, env=env)
    return p.returncode, p.stderr.decode("utf-8", "replace")


results = []


def check(name, got, want, extra=True, note=""):
    ok = (got == want) and extra
    results.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name:56s} exit={got} want={want} {note}")


print("MUST BLOCK (if these pass, the fix is inert):")
rc, err = run(LANES_HYPHEN, "some-other-lane")
check("hyphen lane's file is GUARDED against another lane", rc, 2,
      "hyphen-lane" in err)
rc, err = run(LANES_HYPHEN, "hyphen-lane")
check("the OWNER of a hyphen header is blocked", rc, 2,
      "BLOCKED" in err and "em-dash" in err.lower())
check("  ^ block text names U+2014 and the lane", 0, 0,
      "U+2014" in err and "### hyphen-lane" in err)

print("\nMUST ALLOW -- each for its own reason:")
rc, err = run(LANES_EMDASH, "emdash-lane")
check("em-dash lane editing its OWN file", rc, 0)
rc, err = run(LANES_EMDASH, "other-lane", rel_path="README.md")
check("unclaimed path", rc, 0)
rc, err = run(LANES_CLOSED_HYPHEN, "any-lane", rel_path=CLAIMED)
check("CLOSED hyphen header does not claim anything", rc, 0)
rc, err = run(LANES_EMDASH, None, rel_path="README.md")
check("no current-lane marker at all", rc, 0)

print("\nREPORTING (loud, but not blocking innocents):")
rc, err = run(LANES_HYPHEN, "some-other-lane", rel_path="README.md")
check("unrelated file still REPORTS the malformed header", rc, 0,
      "ASCII HYPHENS" in err, "(warned)")

print("\nFAIL-OPEN:")
rc, err = run("### broken header with no separator at all\n", "x",
              rel_path="README.md")
check("unparseable junk does not block", rc, 0)
rc, err = run(LANES_EMDASH, "emdash-lane", rel_path=".syndicate/lanes.md")
check("the ledger itself is never guarded", rc, 0)

bad = len([r for r in results if not r])
print(f"\n{len(results) - bad}/{len(results)} passed")
sys.exit(1 if bad else 0)
