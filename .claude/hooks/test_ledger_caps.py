#!/usr/bin/env python3
"""The ledger caps must have exactly ONE source, and it must be the enforcer.

This suite exists because they did not. `5c3ad9c4` raised `lanes.md` from
120,000 to 240,000 in `session-start.sh` -- the only component that enforces a
cap -- and two reporting tools kept their own copy. For months afterwards
`trim_lane_blocks.py` printed

    cap 120000      1.66x -> 1.58x  *** STILL OVER ***

about a file the enforcing hook was perfectly happy with (0.85x). On
2026-09-03 a session read that line and reported an unresolved constraint to
their user that did not exist.

The drift is the whole failure, so the test is a DRIFT test: it re-reads the
shell and asserts every consumer resolves to the same number. Change the cap in
`session-start.sh` and nothing here needs editing; add a fourth consumer with a
hardcoded number and this stays green, which is why the last case greps for
stragglers.

Run: python .claude/hooks/test_ledger_caps.py
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import ledger_caps  # noqa: E402

PASS = FAIL = 0


def check(label, got, want):
    global PASS, FAIL
    ok = got == want
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print("  %s  %-58s" % ("PASS" if ok else "FAIL", label))
    if not ok:
        print("          got  %r" % (got,))
        print("          want %r" % (want,))


hook = os.path.join(REPO, ".claude", "hooks", "session-start.sh")
with open(hook, encoding="utf-8", errors="replace") as fh:
    shell = fh.read()

# The ground truth, parsed independently of the module under test -- otherwise
# this asserts the module agrees with itself.
m = re.search(r"^\s*for\s+f\s+in\s+((?:[A-Za-z0-9_.-]+\.md:\d+\s*)+);\s*do\s*$",
              shell, re.M)
truth = dict((n, int(v)) for n, v in re.findall(r"([A-Za-z0-9_.-]+\.md):(\d+)",
                                                m.group(1))) if m else {}

print("THE ENFORCER IS THE SOURCE")
check("the cap line is parseable at all", bool(truth), True)
check("ledger_caps reports it came from the shell",
      ledger_caps.cap_source(REPO), "session-start.sh")
for name, want in sorted(truth.items()):
    check("ledger_caps agrees on %s (%d)" % (name, want),
          ledger_caps.cap(name, REPO), want)

print()
print("FALLBACK IS VISIBLE, NEVER SILENT")
check("an unreadable root falls back",
      ledger_caps.cap_source(os.path.join(REPO, "no", "such", "dir")), "fallback")
check("  ^ and still returns a usable number",
      ledger_caps.cap("lanes.md", os.path.join(REPO, "no", "such", "dir")) > 0, True)

print()
print("NO CONSUMER MAY CARRY ITS OWN COPY")

# The straggler grep. A hardcoded cap in a reporting tool is invisible until it
# is wrong, which is the entire incident above.
out = subprocess.run(
    ["git", "-C", REPO, "grep", "-n", "-E",
     r"(cap|budget)[^\n]{0,20}\b(120000|240000|400000)\b", "--", "scripts/", ".claude/"],
    capture_output=True, text=True).stdout
offenders = []
for line in out.splitlines():
    path = line.split(":", 1)[0].replace("\\", "/")
    # The enforcer is allowed to hold the numbers; so is the module that reads
    # it, and so is this test.
    if path.endswith(("session-start.sh", "ledger_caps.py", "test_ledger_caps.py")):
        continue
    offenders.append(line.strip()[:110])

check("no other file hardcodes a ledger cap", offenders, [])
if offenders:
    for o in offenders:
        print("        " + o)

print()
print("%d/%d passed" % (PASS, PASS + FAIL))
sys.exit(1 if FAIL else 0)
