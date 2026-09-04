#!/usr/bin/env python3
"""Drives `discard-guard.py` against THROWAWAY repos.

The MUST-REFUSE cases come first, because every bug in a guard like this makes
it quieter. A suite that only checked the allow-cases would stay green on a hook
that never fires -- which is the failure this repo has filed three times.

Never touches the live tree: `learnings.md` forbids a guard test that asserts
against the real ledger.

Run: python .claude/hooks/test_discard_guard.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "discard-guard.py")
PASS = FAIL = 0
TMP = []


def check(label, got, want):
    global PASS, FAIL
    ok = got == want
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print("  %s  %-56s got=%s want=%s" % ("PASS" if ok else "FAIL", label, got, want))


def repo(extra_uncommitted=None, seed="### a - OPEN - x\n- Files: `a/b.py`\n"):
    d = tempfile.mkdtemp(prefix="discard-test-")
    TMP.append(d)
    os.makedirs(os.path.join(d, ".syndicate"))
    p = os.path.join(d, ".syndicate", "lanes.md")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(seed)
    g = lambda *a: subprocess.run(["git", "-C", d] + list(a), capture_output=True)
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    g("add", "-A"); g("commit", "-q", "-m", "one")
    if extra_uncommitted:
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(extra_uncommitted)
    return d


def drive(d, cmd, env_extra=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=d)
    env.pop("SYNDICATE_ALLOW_DISCARD", None)
    env.pop("SYNDICATE_DISCARD_GUARD", None)
    if env_extra:
        env.update(env_extra)
    r = subprocess.run([sys.executable, HOOK],
                       input=json.dumps({"tool_name": "Bash", "cwd": d,
                                         "tool_input": {"command": cmd}}),
                       capture_output=True, text=True, env=env)
    return r.returncode, (r.stderr or "")


LOSS = "- **A CLAIM TRANSFER, mid-edit, in no commit anywhere**\n"

print("MUST REFUSE -- content that exists nowhere else")
d = repo(LOSS)
rc, err = drive(d, "git checkout HEAD -- .syndicate/lanes.md")
check("checkout -- <path> over an uncommitted addition", rc, 2)
check("  ^ names the count", "1 uncommitted line(s)" in err, True)
check("  ^ says a deletions count cannot see it",
      "DELETIONS COUNT WILL NOT SHOW" in err, True)
check("  ^ offers a preserving alternative", "git stash push" in err, True)
check("git restore <path>", drive(repo(LOSS), "git restore .syndicate/lanes.md")[0], 2)
check("git reset --hard (no pathspec, sweeps everything)",
      drive(repo(LOSS), "git reset --hard")[0], 2)

print()
print("MUST ALLOW -- each for its own reason")
check("a clean tree has nothing to lose",
      drive(repo(), "git checkout HEAD -- .syndicate/lanes.md")[0], 0)
check("`checkout -b` creates a branch, overwrites no file",
      drive(repo(LOSS), "git checkout -b feature/x")[0], 0)
check("an unrelated command", drive(repo(LOSS), "git status")[0], 0)
check("a commit whose MESSAGE names the path",
      drive(repo(LOSS), "git commit -m 'see .syndicate/lanes.md'")[0], 0)
check("the documented override",
      drive(repo(LOSS), "SYNDICATE_ALLOW_DISCARD=1 git checkout HEAD -- .syndicate/lanes.md")[0], 0)
check("the off switch",
      drive(repo(LOSS), "git checkout HEAD -- .syndicate/lanes.md",
            {"SYNDICATE_DISCARD_GUARD": "off"})[0], 0)

print()
print("THE SOURCE REV MUST BE THE ONE NAMED, not HEAD")
# `git reset --hard origin/main` installs origin/main. Comparing against HEAD
# instead made the message read "in neither HEAD nor HEAD" and OVER-REPORTED --
# every line HEAD lacks was counted, including content safely on the very rev
# being installed. Measured on the author's own tree: 14 settings.json lines
# flagged where the truth against origin/main was 0. An over-reporting guard
# trains people to override it.
import importlib.util as _ilu, io as _io
_spec = _ilu.spec_from_file_location('dg', HOOK)
_dg = _ilu.module_from_spec(_spec)
_old = sys.stdin; sys.stdin = _io.StringIO('{}')
try:
    _spec.loader.exec_module(_dg)
except SystemExit:
    pass
finally:
    sys.stdin = _old
for _cmd, _want in [('git reset --hard origin/main', 'origin/main'),
                    ('git reset --hard', 'HEAD'),
                    ('git reset --hard HEAD~2', 'HEAD~2'),
                    ('git checkout origin/main -- a/b.py', 'origin/main'),
                    ('git checkout HEAD -- a/b.py', 'HEAD')]:
    check('source rev for: ' + _cmd, _dg._targets(_cmd)[0], _want)

print("THE COUNT MUST BE RIGHT, not merely non-zero")
# git output decoded as cp1252 mojibakes em-dashes, so lines stop matching their
# own committed copies and the count inflates. Measured while writing this hook:
# 16 genuinely-uncommitted lines reported as 431.
dash = "—"
seed = "### a " + dash + " OPEN " + dash + " x\n- Files: `a/b.py`\n- Note " + dash + " prose\n"
d = repo("- **one new line " + dash + " with an em-dash**\n", seed=seed)
rc, err = drive(d, "git checkout HEAD -- .syndicate/lanes.md")
check("an em-dash file counts ONE, not the whole file", "1 uncommitted line(s)" in err, True)
check("  ^ and still refuses", rc, 2)

for d in TMP:
    shutil.rmtree(d, ignore_errors=True)

print()
print("%d/%d passed" % (PASS, PASS + FAIL))
sys.exit(1 if FAIL else 0)
