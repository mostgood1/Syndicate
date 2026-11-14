#!/usr/bin/env python3
"""lane-guard's exemption is judged relative to the TREE a path lives in.

THE DEFECT (measured 2026-11-14, lane `lane-guard-desktop-worktree-exempt`).
`lane_claims.is_exempt` returned True for any path with a `.claude` or
`.syndicate` segment ANYWHERE. The Claude desktop app puts every session worktree
at `<repo>/.claude/worktrees/<name>/`, so every file in such a worktree was
exempt: an Edit of a file claimed by two OPEN lanes exited 0 with no message,
while the identical edit in the primary tree or a `C:/tmp/syndicate-sessions`
tree was BLOCKED. `scope-guard` calls the same predicate and was inert there too.

THREE TREE LAYOUTS, each with an exempt LEDGER path and a CLAIMED code path:
  primary          <base>/primary/
  desktop worktree <base>/primary/.claude/worktrees/wt-a/
  session worktree <base>/syndicate-sessions/some-lane/

OFF != ON. The hook is also run from a copy of this directory whose
`lane_claims.is_exempt` is the pre-fix predicate, verbatim. The desktop claimed
path must be ALLOWED there and BLOCKED here -- otherwise the test cannot tell a
fixed guard from one that blocks for some other reason. The primary and session
cases must not move: the fix is scoped to the layout that was broken.

MUST-BLOCK CASES COME FIRST, as in `test_lane_guard_hyphen.py`: a suite that only
sees exit 0 cannot tell a working guard from one that returns 0 unconditionally.

Every case builds its own throwaway trees. It never reads the live ledger
(`learnings.md` 2026-08-20). Run: `python .claude/hooks/test_lane_guard_tree_root.py`.
"""
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "lane-guard.py")
SCOPE_HOOK = os.path.join(HERE, "scope-guard.py")
assert os.path.exists(HOOK), f"hook not found at {HOOK}"
sys.path.insert(0, HERE)

from lane_claims import _norm, is_exempt, tree_relative  # noqa: E402

EM = "\u2014"
CLAIMED = "scripts/claimed_thing.py"
CLAIMED_DIR_FILE = "reports/held_dir/out.json"

# `other-lane` claims a code file, a directory, AND the two exempt paths. A claim
# on an exempt path is what makes the exempt cases meaningful: if the exemption
# did not apply, those edits would be BLOCKED by this claim, not merely allowed
# for want of one.
LANES = f"""# lanes
## OPEN

### other-lane {EM} OPEN {EM} holds the files under test
- Goal: hold files
- Files: `{CLAIMED}`, `reports/held_dir/`, `.syndicate/lanes.md`, `.claude/settings.json`

### my-lane {EM} OPEN {EM} the session under test
- Goal: something else
- Files: `scripts/mine.py`
"""

# The pre-2026-11-14 predicate, verbatim, for the OFF arm.
LEGACY_IS_EXEMPT = '''

def is_exempt(path, roots=()):  # PRE-FIX predicate, appended by the test (OFF arm)
    norm = _norm(path)
    return any(
        norm == marker or norm.startswith(marker + "/") or ("/" + marker + "/") in ("/" + norm)
        for marker in (".syndicate", ".claude")
    )
'''

results = []
_CLEANUP = []


def check(name, got, want, note=""):
    ok = got == want
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got {got!r}, want {want!r} {note}")


def legacy_is_exempt(path):
    ns = {"_norm": _norm}
    exec(LEGACY_IS_EXEMPT, ns)
    return ns["is_exempt"](path)


def build_trees():
    base = tempfile.mkdtemp(prefix="lgtr").replace("\\", "/")
    _CLEANUP.append(base)
    trees = {
        "primary": base + "/primary",
        "desktop worktree": base + "/primary/.claude/worktrees/wt-a",
        "session worktree": base + "/syndicate-sessions/some-lane",
    }
    for root in trees.values():
        os.makedirs(root + "/.syndicate", exist_ok=True)
        with open(root + "/.syndicate/lanes.md", "w", encoding="utf-8", newline="") as fh:
            fh.write(LANES)
    return base, trees


def legacy_hooks_dir():
    """A copy of this directory's modules with the PRE-FIX `is_exempt`."""
    d = tempfile.mkdtemp(prefix="lgtr-legacy")
    _CLEANUP.append(d)
    for src in glob.glob(os.path.join(HERE, "*.py")):
        if not os.path.basename(src).startswith("test_"):
            shutil.copy(src, d)
    with open(os.path.join(d, "lane_claims.py"), "a", encoding="utf-8") as fh:
        fh.write(LEGACY_IS_EXEMPT)
    return d


def run_guard(primary, file_path, lane, session, hook=HOOK):
    with open(os.path.join(primary, ".syndicate", f".current-lane.{session}"),
              "w", encoding="utf-8") as fh:
        fh.write(lane)
    payload = json.dumps({"tool_name": "Edit", "session_id": session,
                          "tool_input": {"file_path": file_path}})
    env = dict(os.environ, CLAUDE_PROJECT_DIR=primary)
    p = subprocess.run([sys.executable, hook], input=payload.encode(),
                       capture_output=True, env=env)
    return p.returncode, p.stderr.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
print("PREDICATE: the shape that was broken")
WT = "C:/Users/u/Coding/Syndicate/.claude/worktrees/serene-x"
check("desktop worktree CODE path is NOT exempt",
      is_exempt(WT + "/scripts/live_totals_width_fit.py"), False)
check("...and was exempt under the pre-fix predicate (the defect)",
      legacy_is_exempt(WT + "/scripts/live_totals_width_fit.py"), True)
check("desktop worktree code path, backslash spelling, is NOT exempt",
      is_exempt(WT.replace("/", "\\") + "\\scripts\\live_totals_width_fit.py"), False)
check("desktop worktree code path is tree-relative",
      tree_relative(WT + "/scripts/live_totals_width_fit.py"), "scripts/live_totals_width_fit.py")
check("the primary's .claude/worktrees itself is NOT harness config",
      is_exempt("C:/r/Syndicate/.claude/worktrees", ("C:/r/Syndicate",)), False)
check("a worktree's own root is NOT exempt",
      is_exempt("C:/r/Syndicate/.claude/worktrees/wt-a", ("C:/r/Syndicate",)), False)

print("\nPREDICATE: ledger + harness stay exempt in every tree")
for label, root in (("primary", "C:/r/Syndicate"),
                    ("desktop", "C:/r/Syndicate/.claude/worktrees/wt-a"),
                    ("session", "C:/tmp/syndicate-sessions/some-lane")):
    for rel, want in ((".syndicate/lanes.md", True),
                      (".syndicate/state_worker.md", True),
                      (".claude/settings.json", True),
                      (".claude/hooks/lane-guard.py", True),
                      (".claude/commands/lane.md", True),
                      ("scripts/claimed_thing.py", False),
                      ("syndicate/blueprints/ops.py", False)):
        check(f"{label:8s} {rel}", is_exempt(root + "/" + rel, ("C:/r/Syndicate",)), want)
check("session tree, `../..` relpath spelling, ledger exempt",
      is_exempt("../../../../tmp/syndicate-sessions/x/.syndicate/lanes.md"), True)
check("session tree, `../..` relpath spelling, code NOT exempt",
      is_exempt("../../../../tmp/syndicate-sessions/x/scripts/a.py"), False)
check("primary path matched case-insensitively against its root (Windows)",
      tree_relative("c:/R/syndicate/.claude/hooks/x.py", ("C:/r/Syndicate",)),
      ".claude/hooks/x.py" if os.name == "nt" else None)

print("\nPREDICATE: claim tokens and paths outside every tree are unchanged")
check("claim token .syndicate/lanes.md", is_exempt(".syndicate/lanes.md"), True)
check("claim token .claude/settings.json", is_exempt(".claude/settings.json"), True)
check("claim token syndicate/blueprints/ops.py", is_exempt("syndicate/blueprints/ops.py"), False)
check("user-level ~/.claude memory file (no tree) stays exempt",
      is_exempt("C:/Users/u/.claude/projects/p/memory/MEMORY.md", ("C:/r/Syndicate",)), True)
check("code in an unnamed tree (C:/tmp/ledger-1002) is NOT exempt",
      is_exempt("C:/tmp/ledger-1002/scripts/a.py", ("C:/r/Syndicate",)), False)
check("ledger in an unnamed tree (C:/tmp/ledger-1002) stays exempt",
      is_exempt("C:/tmp/ledger-1002/.syndicate/lanes.md", ("C:/r/Syndicate",)), True)

# ---------------------------------------------------------------------------
base, trees = build_trees()
primary = trees["primary"]
legacy = legacy_hooks_dir()

print("\nHOOK: MUST BLOCK -- a claimed code path, in every tree")
for label, root in trees.items():
    rc, err = run_guard(primary, root + "/" + CLAIMED, "my-lane", "s-block")
    check(f"{label}: {CLAIMED}", rc, 2, "(BLOCKED)" if "other-lane" in err else "")
    check(f"{label}: BLOCKED message names the tree-relative path",
          f"BLOCKED: {CLAIMED} is claimed" in err, True)
    rc, _ = run_guard(primary, root + "/" + CLAIMED_DIR_FILE, "my-lane", "s-block")
    check(f"{label}: file under a DIRECTORY claim", rc, 2)

print("\nHOOK: MUST ALLOW -- ledger + harness, though claimed, in every tree")
for label, root in trees.items():
    for rel in (".syndicate/lanes.md", ".claude/settings.json"):
        rc, err = run_guard(primary, root + "/" + rel, "my-lane", "s-allow")
        check(f"{label}: {rel}", rc, 0, err.strip()[:80])

print("\nHOOK: MUST ALLOW -- the owner, and unclaimed code")
for label, root in trees.items():
    rc, _ = run_guard(primary, root + "/" + CLAIMED, "other-lane", "s-owner")
    check(f"{label}: owner edits its own claimed file", rc, 0)
    rc, _ = run_guard(primary, root + "/scripts/unclaimed.py", "my-lane", "s-free")
    check(f"{label}: unclaimed code", rc, 0)

print("\nOFF != ON: the same payloads through the PRE-FIX predicate")
for label, root in trees.items():
    rc_off, _ = run_guard(primary, root + "/" + CLAIMED, "my-lane", "s-off", hook=os.path.join(legacy, "lane-guard.py"))
    rc_on, _ = run_guard(primary, root + "/" + CLAIMED, "my-lane", "s-off")
    want_off = 0 if label == "desktop worktree" else 2
    check(f"{label}: pre-fix exit code", rc_off, want_off,
          "(the defect: allowed)" if want_off == 0 else "(unchanged)")
    check(f"{label}: fixed exit code", rc_on, 2)
    for rel in (".syndicate/lanes.md", ".claude/settings.json"):
        rc_off, _ = run_guard(primary, root + "/" + rel, "my-lane", "s-off", hook=os.path.join(legacy, "lane-guard.py"))
        check(f"{label}: {rel} exempt before the fix too", rc_off, 0)

# ---------------------------------------------------------------------------
# scope-guard shares the predicate. From a desktop worktree with no lane it must
# now SPEAK on a code write (it was silent: the exemption returned first) and stay
# silent on the ledger. One case each way; it warns, it never blocks.
print("\nSCOPE-GUARD: no longer inert in a desktop worktree")
wt = trees["desktop worktree"]


def run_scope(file_path, session, hook=SCOPE_HOOK):
    payload = json.dumps({"tool_name": "Edit", "session_id": session, "cwd": wt,
                          "tool_input": {"file_path": file_path}})
    env = dict(os.environ, CLAUDE_PROJECT_DIR=primary)
    env.pop("SYNDICATE_SCOPE_GUARD", None)
    p = subprocess.run([sys.executable, hook], input=payload.encode(),
                       capture_output=True, env=env)
    key = hashlib.sha1((os.path.normcase(os.path.abspath(wt)) + "|" + session)
                       .encode("utf-8")).hexdigest()[:16]
    _CLEANUP.append(os.path.join(tempfile.gettempdir(), "syndicate-scope-seen-%s.json" % key))
    return p.returncode, p.stderr.decode("utf-8", "replace")


rc, err = run_scope(wt + "/" + CLAIMED, "scope-nolane-on")
check("code write from a lane-less session warns", rc, 2, "(warned)" if "NO LANE" in err else err[:80])
rc, _ = run_scope(wt + "/" + CLAIMED, "scope-nolane-off", hook=os.path.join(legacy, "scope-guard.py"))
check("...and was silent under the pre-fix predicate", rc, 0)
rc, _ = run_scope(wt + "/.syndicate/lanes.md", "scope-nolane-ledger")
check("ledger write stays silent", rc, 0)

# ---------------------------------------------------------------------------
for p in _CLEANUP:
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)
    elif os.path.exists(p):
        try:
            os.remove(p)
        except OSError:
            pass

bad = len([r for r in results if not r])
print(f"\n{len(results) - bad}/{len(results)} passed")
sys.exit(1 if bad else 0)
