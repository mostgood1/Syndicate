"""scripts/primary_tree_ff.py on throwaway repos: every refusal leaves HEAD and every file exactly as it was,
a clean fast-forward lands, an identical blocker/collision is reset and backed up, a failed merge rolls back,
and the off switch really switches it off (off != on).

Each repo is: a bare `origin`, an `up` clone that pushes new commits, and a `primary` clone -- the tree the
script guards. core.autocrlf is off so bytes are deterministic; the CRLF case is written explicitly.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import primary_tree_ff as m  # noqa: E402


def g(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, "git %s: %s" % (" ".join(args), r.stderr)
    return r.stdout.strip()


def cfg(repo, hooks):
    for k, v in (("user.name", "t"), ("user.email", "t@example.invalid"), ("core.autocrlf", "false"),
                 ("commit.gpgsign", "false"), ("core.hooksPath", str(hooks))):
        g(repo, "config", k, v)


def write(repo, rel, data):
    p = Path(repo, *rel.split("/"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def push(up, files=None, delete=(), force_add=(), msg="upstream"):
    for rel, data in (files or {}).items():
        write(up, rel, data)
    for rel in delete:
        g(up, "rm", "-q", rel)
    g(up, "add", "-A")
    for rel in force_add:
        g(up, "add", "-f", rel)
    g(up, "commit", "-q", "-m", msg)
    g(up, "push", "-q", "origin", "main")
    return g(up, "rev-parse", "HEAD")


class R:
    pass


@pytest.fixture
def r(tmp_path):
    x = R()
    hooks = tmp_path / "nohooks"
    hooks.mkdir()
    x.origin = tmp_path / "origin.git"
    g(tmp_path, "init", "-q", "--bare", "-b", "main", str(x.origin))
    x.up = tmp_path / "up"
    # -c core.autocrlf=false AT CLONE: the checkout happens inside `clone`, so setting it afterwards leaves
    # every file checked out CRLF under this machine's global autocrlf=true -- and reported as modified.
    g(tmp_path, "clone", "-q", "-c", "core.autocrlf=false", str(x.origin), str(x.up))
    cfg(x.up, hooks)
    g(x.up, "symbolic-ref", "HEAD", "refs/heads/main")
    push(x.up, {"a.txt": "a1\n", "keep.txt": "k1\n", "notes.md": "n1\n", ".gitignore": "gen.txt\n"}, msg="base")
    x.primary = tmp_path / "primary"
    g(tmp_path, "clone", "-q", "-c", "core.autocrlf=false", str(x.origin), str(x.primary))
    cfg(x.primary, hooks)
    x.state = m.state_dir_for(x.primary)
    return x


def head(repo):
    return g(repo, "rev-parse", "HEAD")


def snapshot(repo):
    """Every file under the work tree (not .git) by sha256, plus HEAD and the staged list."""
    files = {}
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for f in filenames:
            p = Path(dirpath, f)
            files[p.relative_to(repo).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"files": files, "head": head(repo), "staged": g(repo, "diff", "--cached", "--name-only")}


def refused(r, **kw):
    before = snapshot(r.primary)
    code, rec = m.run(r.primary, do_apply=True, **kw)
    assert code == m.EXIT_REFUSED, rec
    assert rec["result"] == "refused"
    assert snapshot(r.primary) == before, "a refusal must touch nothing"
    st = json.loads((r.state / "status.json").read_text(encoding="utf-8"))
    assert st["result"] == "refused" and st["reasons"] == rec["reasons"]
    return rec


# ---- the happy paths ------------------------------------------------------------------------------------
def test_current_when_nothing_upstream(r):
    code, rec = m.run(r.primary, do_apply=True)
    assert (code, rec["result"]) == (m.EXIT_OK, "current")


def test_clean_ff_lands(r):
    t = push(r.up, {"a.txt": "a2\n", "new/dir/file.md": "x\n"})
    code, rec = m.run(r.primary, do_apply=True)
    assert (code, rec["result"]) == (m.EXIT_OK, "ff"), rec
    assert head(r.primary) == t and rec["behind"] == 1
    assert Path(r.primary, "new/dir/file.md").read_bytes() == b"x\n"
    assert json.loads((r.state / "status.json").read_text(encoding="utf-8"))["result"] == "ff"


def test_dry_run_changes_nothing_and_writes_no_status(r):
    push(r.up, {"a.txt": "a2\n"})
    before = snapshot(r.primary)
    code, rec = m.run(r.primary, do_apply=False)
    assert (code, rec["result"]) == (m.EXIT_OK, "clear")
    assert snapshot(r.primary) == before
    assert not (r.state / "status.json").exists()


def test_modified_file_the_target_does_not_touch_is_kept_byte_identical(r):
    write(r.primary, "keep.txt", "LOCAL WORK\r\n")
    write(r.primary, "scratch.txt", "untracked\n")
    push(r.up, {"a.txt": "a2\n"})
    code, rec = m.run(r.primary, do_apply=True)
    assert rec["result"] == "ff", rec
    assert Path(r.primary, "keep.txt").read_bytes() == b"LOCAL WORK\r\n"
    assert Path(r.primary, "scratch.txt").read_bytes() == b"untracked\n"


def test_blocker_identical_to_target_is_reset_backed_up_and_ff_lands(r):
    t = push(r.up, {"a.txt": "a2\nmore\n"})
    write(r.primary, "a.txt", "a2\r\nmore\r\n")          # the target's content, checked out as CRLF
    code, rec = m.run(r.primary, do_apply=True)
    assert rec["result"] == "ff" and rec["blockers"] == ["a.txt"], rec
    assert head(r.primary) == t
    assert Path(r.primary, "a.txt").read_bytes() == b"a2\nmore\n"
    assert Path(rec["backup"], "files", "a.txt").read_bytes() == b"a2\r\nmore\r\n"


def test_untracked_collision_identical_is_moved_and_recreated(r):
    push(r.up, {"new.txt": "same\n"})
    write(r.primary, "new.txt", "same\n")
    code, rec = m.run(r.primary, do_apply=True)
    assert rec["result"] == "ff" and rec["collisions"] == ["new.txt"], rec
    assert Path(r.primary, "new.txt").read_bytes() == b"same\n"
    assert Path(rec["backup"], "files", "new.txt").read_bytes() == b"same\n"


# ---- every refusal touches nothing --------------------------------------------------------------------
def test_refuses_staged(r):
    push(r.up, {"a.txt": "a2\n"})
    write(r.primary, "keep.txt", "staged\n")
    g(r.primary, "add", "keep.txt")
    # The PLAN's own wording: apply() re-checks staged paths too, and a looser assertion passed on that
    # second guard alone when the first was disabled (mutation check, 2026-11-13).
    assert "1 staged path(s), e.g. keep.txt" in refused(r)["reasons"][0]


def test_refuses_unique_local_edit_the_target_also_changes(r):
    push(r.up, {"a.txt": "a2\n"})
    write(r.primary, "a.txt", "SOMEONE'S UNCOMMITTED WORK\n")
    assert "a.txt has local edits" in refused(r)["reasons"][0]


def test_refuses_local_edit_to_a_file_the_target_deletes(r):
    push(r.up, delete=["notes.md"])
    write(r.primary, "notes.md", "edited\n")
    assert "deletes notes.md" in refused(r)["reasons"][0]


def test_refuses_untracked_file_that_differs_from_the_one_added(r):
    push(r.up, {"new.txt": "upstream\n"})
    write(r.primary, "new.txt", "local\n")
    assert "new.txt is on disk" in refused(r)["reasons"][0]


def test_control_git_overwrites_an_ignored_file_silently(r, tmp_path):
    """The hazard the next test guards against is real: plain git replaces the ignored file without a word."""
    push(r.up, {"gen.txt": "upstream\n"}, force_add=["gen.txt"])
    write(r.primary, "gen.txt", "local generated output\n")
    g(r.primary, "fetch", "-q", "origin")
    g(r.primary, "merge", "--ff-only", "-q", "origin/main")
    assert Path(r.primary, "gen.txt").read_bytes() == b"upstream\n"


def test_refuses_ignored_file_that_differs_from_the_one_added(r):
    push(r.up, {"gen.txt": "upstream\n"}, force_add=["gen.txt"])
    write(r.primary, "gen.txt", "local generated output\n")
    assert "gen.txt is on disk (untracked or IGNORED)" in refused(r)["reasons"][0]


def test_refuses_file_where_the_target_needs_a_directory(r):
    push(r.up, {"sub/x.txt": "x\n"})
    write(r.primary, "sub", "a file, not a dir\n")
    assert "a FILE sits at sub" in refused(r)["reasons"][0]


def test_refuses_head_with_its_own_commits(r):
    push(r.up, {"a.txt": "a2\n"})
    write(r.primary, "keep.txt", "local commit\n")
    g(r.primary, "commit", "-q", "-am", "local")
    assert "not a fast-forward" in refused(r)["reasons"][0]


def test_refuses_target_not_on_origin_main(r):
    push(r.up, {"a.txt": "a2\n"})
    write(r.up, "a.txt", "never pushed\n")
    g(r.up, "commit", "-q", "-am", "unpushed")
    g(r.primary, "fetch", "-q", str(r.up), "main")
    stray = g(r.primary, "rev-parse", "FETCH_HEAD")
    assert "not on origin/main" in refused(r, target=stray)["reasons"][0]


def test_refuses_off_main_branch(r):
    push(r.up, {"a.txt": "a2\n"})
    g(r.primary, "checkout", "-q", "-b", "other")
    assert "not refs/heads/main" in refused(r)["reasons"][0]


def test_refuses_linked_worktree(r, tmp_path):
    push(r.up, {"a.txt": "a2\n"})
    wt = tmp_path / "wt"
    g(r.primary, "worktree", "add", "-q", "--detach", str(wt))
    code, rec = m.run(wt, do_apply=True, state=tmp_path / "st")
    assert code == m.EXIT_REFUSED and "LINKED worktree" in rec["reasons"][0]


def test_refuses_mid_merge(r):
    push(r.up, {"a.txt": "a2\n"})
    Path(r.primary, ".git", "MERGE_HEAD").write_text(head(r.primary) + "\n")
    assert "in progress" in refused(r)["reasons"][0]


def test_refuses_case_only_rename(r):
    push(r.up, {"Readme.md": "r\n"})
    g(r.primary, "pull", "-q", "--ff-only")
    g(r.up, "mv", "Readme.md", "tmpname.md")
    g(r.up, "mv", "tmpname.md", "README.md")
    g(r.up, "commit", "-q", "-m", "case rename")
    g(r.up, "push", "-q", "origin", "main")
    assert "case-only rename" in refused(r)["reasons"][0]


def test_refuses_when_a_blocker_changes_between_plan_and_apply(r):
    push(r.up, {"a.txt": "a2\n"})
    write(r.primary, "a.txt", "a2\n")
    p = m.plan(r.primary)
    write(r.primary, "a.txt", "a scheduled writer appended\n")
    before = snapshot(r.primary)
    with pytest.raises(m.Refused) as e:
        m.apply(p, r.state)
    assert "a.txt changed during the plan" in e.value.reasons[0]
    assert snapshot(r.primary) == before


# ---- failure, lock, off switch, digest ----------------------------------------------------------------
def test_failed_merge_rolls_back_blockers_and_collisions(r):
    push(r.up, {"a.txt": "a2\n", "new.txt": "same\n"})
    write(r.primary, "a.txt", "a2\r\n")
    write(r.primary, "new.txt", "same\n")
    before = snapshot(r.primary)

    def boom(tree, target):
        raise m.GitError("injected merge failure")

    code, rec = m.run(r.primary, do_apply=True, merge=boom)
    assert (code, rec["result"]) == (m.EXIT_FAILED, "failed")
    assert "rolled back" in rec["reasons"][0]
    assert snapshot(r.primary) == before


def test_lock_held_skips_and_a_stale_lock_is_taken(r):
    push(r.up, {"a.txt": "a2\n"})
    r.state.mkdir(parents=True, exist_ok=True)
    lock = r.state / "lock"
    lock.write_text("{}")
    code, rec = m.run(r.primary, do_apply=True)
    assert (code, rec["result"]) == (m.EXIT_SKIPPED, "skipped")
    old = time.time() - m.LOCK_STALE_S - 60
    os.utime(lock, (old, old))
    code, rec = m.run(r.primary, do_apply=True)
    assert rec["result"] == "ff", rec
    assert not lock.exists()


def test_off_switch_is_off_and_on_is_on(r, monkeypatch):
    t = push(r.up, {"a.txt": "a2\n"})
    before = head(r.primary)
    monkeypatch.setenv(m.OFF_ENV, "off")
    code, rec = m.run(r.primary, do_apply=True)
    assert (code, rec["result"], head(r.primary)) == (m.EXIT_SKIPPED, "skipped", before)
    assert m.main(["--apply", "--tree", str(r.primary), "--quiet"]) == m.EXIT_SKIPPED
    assert head(r.primary) == before
    monkeypatch.delenv(m.OFF_ENV)
    assert m.main(["--apply", "--tree", str(r.primary), "--quiet"]) == m.EXIT_OK
    assert head(r.primary) == t


def test_digest_speaks_only_when_a_human_is_needed(r):
    assert m.digest_line(r.state) == ""                                  # never ran
    push(r.up, {"a.txt": "a2\n"})
    write(r.primary, "a.txt", "unique\n")
    m.run(r.primary, do_apply=True)
    line = m.digest_line(r.state)
    assert line.startswith("PRIMARY TREE NOT AUTO-UPDATED (refused") and "a.txt has local edits" in line
    assert "1 behind" in line
    write(r.primary, "a.txt", "a1\n")
    m.run(r.primary, do_apply=True)
    assert m.digest_line(r.state) == ""                                  # ff just now
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=m.STALE_DIGEST_H + 2)
    assert "last ran" in m.digest_line(r.state, now=later)               # trigger stopped running


def test_spawn_is_throttled_by_a_recent_attempt(r):
    launched = []

    def fake(args, **kw):
        launched.append((args, kw))

    assert m.spawn(r.primary, 0, popen=fake) is True and len(launched) == 1
    args, kw = launched[0]
    assert "--apply" in args and kw["stdin"] is m.subprocess.DEVNULL and kw["stdout"] is m.subprocess.DEVNULL
    assert args[args.index("--trigger") + 1] == "session-start"
    # the spawner claimed the gap itself, so a second session starting at once launches nothing
    assert m.spawn(r.primary, 0, popen=fake) is False and len(launched) == 1
    old = time.time() - m.SPAWN_MIN_GAP_S - 60
    os.utime(r.state / "last_attempt", (old, old))
    assert m.spawn(r.primary, 0, popen=fake) is True and len(launched) == 2
