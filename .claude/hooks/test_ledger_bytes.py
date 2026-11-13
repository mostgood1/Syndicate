#!/usr/bin/env python3
"""Tests for `ledger_bytes.py` and the two hooks that use it.

Run: py -3 .claude/hooks/test_ledger_bytes.py

Every damaged string here is BUILT with chr() -- `BS = chr(92)` -- rather than
typed. A test about backslashes being eaten by escape processing must not be
able to have its own backslashes eaten, and a literal `C:\\tmp` in this source
would be one forgotten `r` prefix away from testing a TAB it never meant to.

The real-damage cases are the actual strings the 11-13 repair found on main:
`findings_2026-10-06...` (`C:\\tmp\\bball_sc\\fit_j1`), `findings_2026-10-09...`
(a split plus a lone CR), todo #797 (`\\2026-11-13` read as octal `\\202`) and
state_ui.md's double-encoded em dash. The history case replays commit
`06fd70625` itself: every file it repaired must read as damaged before it and
clean after it.

Throwaway repos for every hook case, as the sibling suites do: a guard test
that reads the live ledger measures the ledger, not the guard.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOKS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOOKS)
import ledger_bytes as lb  # noqa: E402

COMMIT_GUARD = os.path.join(HOOKS, "ledger-commit-guard.py")
POSTWRITE = os.path.join(HOOKS, "ledger-postwrite-check.py")
# Split so this file's own text never matches the commit guard's COMMIT_RE.
GC = "git " + "commit"
BS, TAB, LF, CR = chr(92), chr(9), chr(10), chr(13)
REPAIR_SHA = "06fd70625"


def path(*parts):
    return BS.join(parts)


# ---- the real damage, rebuilt ------------------------------------------------
GOOD_PATH = path("C:", "tmp", "bball_sc", "fit_j1", "sim_nba")
# \t -> TAB, \b -> BS (U+0008), \f -> FF (U+000C)
BBALL = "C:" + TAB + "mp" + chr(8) + "ball_sc" + chr(12) + "it_j1" + BS + "sim_nba"
# todo #797: `\2026-11-13` read as octal \202 (U+0082) followed by `6-11-13`
TODO797 = ("C:" + TAB + "mp" + BS + "edge-analyses" + BS + "cheat-sheet-sections"
           + chr(0x82) + "6-11-13" + BS)
# findings 10-09: `\nflbt` became a line break, `\read_...` a lone CR
NFLBT = ("`C:" + TAB + "mp" + LF + "flbt" + BS + "kalshi_pooled" + CR
         + "ead_2026-10-13" + BS + "`")
MOJIBAKE = "a " + "\u00e2\u0080\u0094" + " b"


def kinds(text):
    return sorted(f.kind for f in lb.findings(text))


def unit(check):
    # ---- each damage class is seen ----------------------------------------
    check("clean Windows path -> nothing", kinds("- out `" + GOOD_PATH + "`\n"), [])
    check("bball_sc path: TAB + BS + FF",
          kinds("- out `" + BBALL + "`\n"), ["control", "control", "tab_path"])
    check("todo #797 path: TAB + the octal \\202",
          kinds("data: `" + TODO797 + "`.\n"), ["control", "tab_path"])
    check("10-09 split path: TAB at the line end + a lone CR on the next line",
          kinds(NFLBT + "\n"), ["lone_cr", "tab_path"])
    check("double-encoded em dash is ONE mojibake finding, not two C1 controls",
          kinds(MOJIBAKE + "\n"), ["mojibake"])
    check("BEL, VT, ESC and DEL anywhere in a line are controls",
          kinds("x" + chr(7) + "y" + chr(11) + "z" + chr(27) + "w" + chr(127) + "\n"),
          ["control"] * 4)

    # ---- and the legitimate cases are not -----------------------------------
    check("U+FFFD in prose about mojibake is NOT flagged (todo.md quotes it 11x)",
          kinds("names render as `V\ufffdsquez` end to end\n"), [])
    check("a TAB in pasted TSV is not flagged", kinds("col1" + TAB + "col2\n"), [])
    check("a tab-indented code line is not flagged", kinds(TAB + "x = 1\n"), [])
    check("CRLF line endings are not lone CRs",
          kinds("line one" + CR + LF + "line two" + CR + LF), [])
    check("a TAB after a path and then a space is not inside the path",
          kinds("C:" + BS + "x" + TAB + " y\n"), [])

    # ---- only NEW damage counts --------------------------------------------
    old = "head\n- out `" + BBALL + "`\n"
    check("pre-existing damage + a clean new line -> nothing introduced",
          lb.introduced(old + "- a clean line\n", old), [])
    check("the same damaged line a SECOND time is new (multiset, not set)",
          len(lb.introduced(old + "- out `" + BBALL + "`\n", old)), 3)
    check("CRLF working copy vs its LF blob compare equal",
          lb.introduced(old.replace(LF, CR + LF).encode(), old.encode()), [])
    check("new damage on a new line is introduced",
          sorted(f.kind for f in lb.introduced(old + TODO797 + "\n", old)),
          ["control", "tab_path"])
    check("bytes and str inputs agree",
          kinds(("x `" + TODO797 + "`\n").encode("utf-8")), ["control", "tab_path"])

    # ---- the message ---------------------------------------------------------
    f = [x for x in lb.findings("- out `" + BBALL + "`\n") if x.kind == "tab_path"][0]
    d = lb.describe(f)
    check("describe() makes the TAB visible and names the escape",
          ("<TAB>" in d, "(was: " + BS + "t)" in d, d.startswith("line 1,")),
          (True, True, True))
    f = [x for x in lb.findings(TODO797) if x.kind == "control"][0]
    check("describe() names the octal escape for a C1 control",
          "(was: " + BS + "202" in lb.describe(f), True)

    # ---- which files are ledger files ----------------------------------------
    check("ledger paths",
          [lb.is_ledger_path(p) for p in (
              ".syndicate/log/2026-11-13.md", ".syndicate/findings_x.md",
              "docs/ai_context/todo.md", ".syndicate\\lanes.md",
              "README.md", "scripts/x.py", ".syndicate/deploy/x.json")],
          [True, True, True, True, False, False, False])


def history(check):
    """Replay the 11-13 repair: before it, every file it touched is damaged;
    after it, every one is clean -- and the repair introduced nothing."""
    here = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                          text=True, cwd=HOOKS).stdout.strip()
    if not here or subprocess.run(["git", "-C", here, "cat-file", "-e", REPAIR_SHA],
                                  capture_output=True).returncode != 0:
        print("SKIP history: commit %s is not in this clone" % REPAIR_SHA)
        return
    names = subprocess.run(["git", "-C", here, "diff-tree", "--no-commit-id", "--name-only",
                            "-r", REPAIR_SHA], capture_output=True, text=True).stdout.split()

    def blob(rev, name):
        return subprocess.run(["git", "-C", here, "show", "%s:%s" % (rev, name)],
                              capture_output=True).stdout

    dirty_before, clean_after, added = 0, 0, 0
    for n in names:
        before, after = blob(REPAIR_SHA + "~1", n), blob(REPAIR_SHA, n)
        dirty_before += bool(lb.findings(before))
        clean_after += not lb.findings(after)
        added += len(lb.introduced(after, before))
    check("06fd70625 touched 36 ledger files", len(names), 36)
    check("  ...every one reads as DAMAGED before the repair", dirty_before, 36)
    check("  ...every one reads as CLEAN after it", clean_after, 36)
    check("  ...and the repair introduced nothing", added, 0)


# ---- hook harness -----------------------------------------------------------
def _git(root, *args):
    return subprocess.run(["git", "-C", root, *args], capture_output=True)


def _write(root, rel, data):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(data.encode("utf-8") if isinstance(data, str) else data)
    st = os.stat(p)
    # Bump mtime well past the last write so the post-write signature moves.
    _write.tick = getattr(_write, "tick", 0) + 1
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + _write.tick * 1_000_000_000))


def _repo(base, name, files):
    root = os.path.join(base, name)
    os.makedirs(root)
    _git(root, "init", "-q")
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("core.autocrlf", "false")):
        _git(root, "config", k, v)
    files = dict(files)
    files.setdefault(".syndicate/lanes.md", "# Lanes\n\n### alpha \u2014 OPEN\n- Goal: x\n")
    for rel, data in files.items():
        _write(root, rel, data)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _commit_hook(cmd, cwd, env_extra=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=cwd)
    env.pop("SYNDICATE_ALLOW_LEDGER_COMMIT", None)
    env.update(env_extra or {})
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}
    p = subprocess.run([sys.executable, COMMIT_GUARD], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, cwd=cwd,
                       encoding="utf-8", errors="replace")
    return p.returncode, p.stderr


def _post_hook(cwd, statedir):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=cwd, TMPDIR=statedir, TEMP=statedir, TMP=statedir)
    env.pop("SYNDICATE_LEDGER_POSTCHECK", None)
    payload = {"tool_name": "Bash", "tool_input": {"command": "python x.py"}, "cwd": cwd}
    p = subprocess.run([sys.executable, POSTWRITE], input=json.dumps(payload),
                       capture_output=True, text=True, env=env,
                       encoding="utf-8", errors="replace")
    return p.returncode, p.stderr


LOG = ".syndicate/log/2026-11-13.md"
HEAD_LOG = "# 2026-11-13\n\n## 14:30Z entry\n- a clean line\n"


def commit_guard(check, base):
    r = _repo(base, "cg_new", {LOG: HEAD_LOG})
    _write(r, LOG, HEAD_LOG + "- out `" + BBALL + "`\n")
    _git(r, "add", LOG)
    code, err = _commit_hook(GC + " -m x", r)
    check("staged NEW damage in a daily log -> BLOCK",
          (code, "escape-damaged" in err, LOG in err, "<TAB>" in err), (2, True, True, True))

    code, err = _commit_hook("SYNDICATE_ALLOW_LEDGER_COMMIT=1 " + GC + " -m x", r)
    check("  ...the documented override, as a command prefix, lets it through", code, 0)

    r = _repo(base, "cg_old", {LOG: HEAD_LOG + "- out `" + BBALL + "`\n"})
    _write(r, LOG, HEAD_LOG + "- out `" + BBALL + "`\n- another clean line\n")
    _git(r, "add", LOG)
    check("damage already in HEAD + a clean append -> allow",
          _commit_hook(GC + " -m x", r)[0], 0)

    r = _repo(base, "cg_pathspec", {LOG: HEAD_LOG})
    _write(r, LOG, HEAD_LOG + NFLBT + "\n")
    code, err = _commit_hook(GC + " -m x -- " + LOG, r)
    check("pathspec commit of an UNSTAGED damaged file -> BLOCK (reads the working file)",
          (code, "lone CR" in err), (2, True))

    r = _repo(base, "cg_unrecorded", {LOG: HEAD_LOG, ".syndicate/leads.md": "# Leads\n"})
    _write(r, LOG, HEAD_LOG + NFLBT + "\n")
    _write(r, ".syndicate/leads.md", "# Leads\n- a clean lead\n")
    _git(r, "add", ".syndicate/leads.md")
    check("damaged file NOT in this commit (unstaged, plain commit) -> allow",
          _commit_hook(GC + " -m x", r)[0], 0)

    r = _repo(base, "cg_todo", {"docs/ai_context/todo.md": "# TODO\n"})
    _write(r, "docs/ai_context/todo.md", "# TODO\n- #797 data: `" + TODO797 + "`.\n")
    _git(r, "add", "-A")
    code, err = _commit_hook(GC + " -m x", r)
    check("todo #797's octal damage in docs/ai_context -> BLOCK, names the escape",
          (code, "<U+0082>" in err, "was: " + BS + "202" in err), (2, True, True))

    r = _repo(base, "cg_newfile", {})
    _write(r, ".syndicate/findings_2026-11-13_x.md", "# f\n- `" + BBALL + "`\n")
    _git(r, "add", "-A")
    check("a NEW ledger file carrying damage -> BLOCK",
          _commit_hook(GC + " -m x", r)[0], 2)

    r = _repo(base, "cg_mojibake", {".syndicate/state_ui.md": "# ui\n"})
    _write(r, ".syndicate/state_ui.md", "# ui\n" + MOJIBAKE + "\n")
    _git(r, "add", "-A")
    code, err = _commit_hook(GC + " -m x", r)
    check("a double-encoded em dash -> BLOCK as mojibake", (code, "double-encoded" in err),
          (2, True))

    r = _repo(base, "cg_nonledger", {"README.md": "# r\n", "scripts/x.py": "x = 1\n"})
    _write(r, "README.md", "# r\n" + BBALL + "\n")
    _write(r, "scripts/x.py", "x = 1\n# " + BBALL + "\n")
    _git(r, "add", "-A")
    check("the same damage OUTSIDE the ledger -> allow (not this guard's files)",
          _commit_hook(GC + " -m x", r)[0], 0)

    r = _repo(base, "cg_crlf", {LOG: HEAD_LOG})
    _write(r, LOG, (HEAD_LOG + "- a clean CRLF append\n").replace(LF, CR + LF))
    check("`-a` commit of a CRLF working copy over an LF blob, clean -> allow",
          _commit_hook(GC + " -am x", r)[0], 0)
    _write(r, LOG, (HEAD_LOG + "- `" + BBALL + "`\n").replace(LF, CR + LF))
    check("  ...and the same with a damaged append -> BLOCK",
          _commit_hook(GC + " -am x", r)[0], 2)


def postwrite(check, base):
    sd = os.path.join(base, "pw_state1")
    os.makedirs(sd)
    r = _repo(base, "pw_main", {LOG: HEAD_LOG, ".syndicate/findings_x.md": "# f\n"})
    _write(r, LOG, HEAD_LOG + "- `" + BBALL + "`\n")
    check("FIRST sighting of a tree seeds silently, even over uncommitted damage",
          _post_hook(r, sd)[0], 0)

    _write(r, LOG, HEAD_LOG + "- `" + BBALL + "`\n- `" + TODO797 + "`\n")
    code, err = _post_hook(r, sd)
    check("a write that adds damage -> WARN, names the file and the escape",
          (code, LOG in err, "NEW escape-damaged" in err, "<U+0082>" in err),
          (2, True, True, True))
    check("  ...the next call with nothing changed is SILENT", _post_hook(r, sd)[0], 0)

    _write(r, LOG, HEAD_LOG + "- `" + BBALL + "`\n- `" + TODO797 + "`\n- clean\n")
    check("  ...a clean append to the same file does not re-warn (same damage)",
          _post_hook(r, sd)[0], 0)

    _write(r, ".syndicate/findings_x.md", "# f\n" + NFLBT + "\n")
    code, err = _post_hook(r, sd)
    check("damage in a file TRACKED never names (a findings file) -> WARN",
          (code, "findings_x.md" in err), (2, True))

    _write(r, LOG, HEAD_LOG + "- `" + GOOD_PATH + "`\n")
    _write(r, ".syndicate/findings_x.md", "# f\n- fixed\n")
    check("fixing the damage -> silent", _post_hook(r, sd)[0], 0)

    sd = os.path.join(base, "pw_state2")
    os.makedirs(sd)
    r = _repo(base, "pw_committed", {LOG: HEAD_LOG + "- `" + BBALL + "`\n"})
    _post_hook(r, sd)
    _write(r, LOG, HEAD_LOG + "- `" + BBALL + "`\n- clean append\n")
    check("damage already COMMITTED + a clean append -> silent", _post_hook(r, sd)[0], 0)

    sd = os.path.join(base, "pw_state3")
    os.makedirs(sd)
    many = {".syndicate/log/2026-10-%02d.md" % d: "# d\n" for d in range(1, 26)}
    r = _repo(base, "pw_many", many)
    _post_hook(r, sd)
    for rel in many:
        _write(r, rel, "# d\n- `" + BBALL + "`\n")
    check("25 files moving in one call (a checkout/ff) re-seeds instead of reading",
          _post_hook(r, sd)[0], 0)


def main():
    results = []

    def check(label, got, want):
        results.append((label, got, want))

    base = tempfile.mkdtemp(prefix="ledger_bytes_test_")
    try:
        unit(check)
        history(check)
        commit_guard(check, base)
        postwrite(check, base)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    failed = 0
    for label, got, want in results:
        ok = got == want
        failed += not ok
        print(("PASS " if ok else "FAIL ") + label + ("" if ok else "   got %r want %r" % (got, want)))
    print("%d/%d passed" % (len(results) - failed, len(results)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
