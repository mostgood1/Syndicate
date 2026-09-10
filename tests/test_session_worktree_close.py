"""`session_worktree.py close` must finish the job when `git worktree remove` fails.

MEASURED 2026-09-10. `close --lane census-rescue-0910-land`, run from the primary
tree with that worktree's OWN copy of the script, printed
`note: git worktree remove failed (255); deleted the directory and pruned instead.`
and then died with `NotADirectoryError: [WinError 267]`. `REPO_ROOT` is
`Path(__file__).parents[1]` -- the tree it had just deleted -- and every later
`git()` call used it as `cwd`, so the branch was never deleted. An earlier
`close --lane census-rescue-0910 --force` took the same fallback and survived only
because the copy it ran lived in a DIFFERENT tree; `--force` was not the difference.

WHY `remove` FAILS HERE AT ALL. OneDrive sets FILE_ATTRIBUTE_READONLY on every
`.git/worktrees/<id>` directory minutes after git creates it, and Windows refuses
`rmdir` on a read-only directory. Git deletes the files, stops at the first
read-only subdirectory and exits 255, leaving a husk with no `gitdir` that
`git worktree list` cannot see and `git worktree prune` cannot delete. The
Windows-only tests set that attribute for real rather than mocking git.
"""
from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "session_worktree.py"
ON_WINDOWS = os.name == "nt"


def _load(tag: str):
    spec = importlib.util.spec_from_file_location(f"session_worktree_under_test_{tag}", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(*args, cwd, check=True, env=None) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env)
    if check and done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {done.stderr}")
    return done.stdout.strip()


def _set_readonly_dirs(root: Path) -> None:
    """The shape measured on every admin dir: R on the DIRECTORIES, not on the files."""
    for dirpath, _dirs, _files in os.walk(root):
        os.chmod(dirpath, stat.S_IREAD)


def _branch_exists(repo, branch: str) -> bool:
    return subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                          cwd=str(repo.main), capture_output=True).returncode == 0


def _listed_names(repo) -> set[str]:
    out = _git("worktree", "list", "--porcelain", cwd=repo.main)
    return {Path(line[len("worktree "):]).name for line in out.splitlines()
            if line.startswith("worktree ")}


def _open(repo, slug: str, commits: int = 0) -> Path:
    path = repo.sessions / slug
    _git("worktree", "add", "-q", "-b", f"session/{slug}", str(path), "origin/main", cwd=repo.main)
    for i in range(commits):
        (path / f"work{i}.txt").write_text("unlanded\n")
        _git("add", ".", cwd=path)
        _git("commit", "-q", "-m", f"unlanded {i}", cwd=path)
    return path


def _close(mod, repo, slug: str, force: bool = False) -> int:
    return mod.cmd_close(Namespace(lane=slug, root=repo.sessions, force=force))


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    base = tmp_path.resolve()                      # expand 8.3 names before git records a path
    # Hermetic: no hooks, signing or autocrlf from the developer's own git config.
    (base / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(base / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "test")
        monkeypatch.setenv(f"{key}_EMAIL", "test@example.invalid")
    repo = SimpleNamespace(origin=base / "origin.git", main=base / "main", sessions=base / "sessions")
    _git("init", "-q", "--bare", "-b", "main", str(repo.origin), cwd=base)
    _git("init", "-q", "-b", "main", str(repo.main), cwd=base)
    (repo.main / "README").write_text("x\n")
    _git("add", "README", cwd=repo.main)
    _git("commit", "-q", "-m", "c0", cwd=repo.main)
    _git("remote", "add", "origin", str(repo.origin), cwd=repo.main)
    _git("push", "-q", "-u", "origin", "main", cwd=repo.main)
    repo.sessions.mkdir()
    yield repo
    for dirpath, dirs, files in os.walk(base):     # pytest cannot delete a read-only dir either
        for name in (*dirs, *files):
            os.chmod(os.path.join(dirpath, name), stat.S_IREAD | stat.S_IWRITE)


def test_close_completes_after_remove_fails_when_run_from_the_closed_trees_own_copy(
        repo, monkeypatch, capsys):
    """THE REPRODUCTION: `py -3 <worktree>/scripts/session_worktree.py close --lane <it>`."""
    path = _open(repo, "own-copy")
    mod = _load("own_copy")
    monkeypatch.setattr(mod, "REPO_ROOT", path)
    real, calls = mod.git, []

    def git(*args, **kw):
        calls.append((args, Path(kw.get("cwd") or mod.REPO_ROOT)))
        if args[:2] == ("worktree", "remove"):
            return subprocess.CompletedProcess(
                ["git", *args], 255, "", "error: failed to delete '.git/worktrees/own-copy': Permission denied\n")
        return real(*args, **kw)

    monkeypatch.setattr(mod, "git", git)
    rc = _close(mod, repo, "own-copy")

    assert "failed (255)" in capsys.readouterr().out   # the fallback branch really ran
    assert rc == 0
    assert not path.exists()
    assert "own-copy" not in _listed_names(repo)
    assert not (repo.main / ".git" / "worktrees" / "own-copy").exists()
    assert not _branch_exists(repo, "session/own-copy")
    removal = next(i for i, (args, _) in enumerate(calls) if args[:2] == ("worktree", "remove"))
    after = calls[removal + 1:]
    assert after, "nothing ran after the fallback delete"
    assert all(cwd != path for _, cwd in after), [a for a, c in after if c == path]


@pytest.mark.skipif(not ON_WINDOWS, reason="a read-only DIRECTORY blocks rmdir only on Windows")
def test_close_completes_against_a_real_readonly_admin_dir(repo, monkeypatch, capsys):
    """No mock at all: the attribute OneDrive leaves, and the real git it defeats.

    The CONTROL proves the attribute bites in this environment -- plain `git
    worktree remove` fails on it exactly as it does on the OneDrive store -- so
    the close passing below cannot be the environment being kinder than production.
    """
    control = _open(repo, "ro-control")
    control_admin = repo.main / ".git" / "worktrees" / "ro-control"
    _set_readonly_dirs(control_admin)
    done = subprocess.run(["git", "worktree", "remove", "--force", str(control)],
                          cwd=str(repo.main), capture_output=True, text=True)
    assert done.returncode == 255 and control_admin.exists(), done.stderr

    path = _open(repo, "ro-admin")
    admin = repo.main / ".git" / "worktrees" / "ro-admin"
    _set_readonly_dirs(admin)
    mod = _load("ro_admin")
    monkeypatch.setattr(mod, "REPO_ROOT", path)

    rc = _close(mod, repo, "ro-admin")

    out = capsys.readouterr().out
    assert "cleared READONLY" in out, out              # the branch that defeats it really ran
    assert rc == 0
    assert not path.exists()
    assert not admin.exists()
    assert "ro-admin" not in _listed_names(repo)
    assert not _branch_exists(repo, "session/ro-admin")


def test_close_refuses_an_unmerged_branch_and_removes_nothing(repo, monkeypatch, capsys):
    path = _open(repo, "unmerged", commits=1)
    mod = _load("unmerged")
    monkeypatch.setattr(mod, "REPO_ROOT", path)
    real, removes = mod.git, []

    def git(*args, **kw):
        if args[:2] == ("worktree", "remove"):
            removes.append(args)
        return real(*args, **kw)

    monkeypatch.setattr(mod, "git", git)
    assert _close(mod, repo, "unmerged") == 1
    assert "1 commit(s) not on origin/main" in capsys.readouterr().out
    assert removes == []
    assert path.exists()
    assert _branch_exists(repo, "session/unmerged")


def test_rerun_after_a_crashed_close_deletes_a_merged_branch_and_keeps_an_unmerged_one(
        repo, monkeypatch, capsys):
    """What the crash left behind: no directory, no registration, a branch. Re-running
    `close` must finish the job -- and the branch deletion keeps its own merge check."""
    for slug, commits in (("left-merged", 0), ("left-unmerged", 1)):
        path = _open(repo, slug, commits=commits)
        _git("worktree", "remove", "--force", str(path), cwd=repo.main)
        assert _branch_exists(repo, f"session/{slug}")
    mod = _load("rerun")
    monkeypatch.setattr(mod, "REPO_ROOT", repo.main)

    assert _close(mod, repo, "left-merged") == 0
    assert not _branch_exists(repo, "session/left-merged")

    assert _close(mod, repo, "left-unmerged") == 1
    assert _branch_exists(repo, "session/left-unmerged")
    assert "KEPT branch session/left-unmerged" in capsys.readouterr().out

    assert _close(mod, repo, "left-unmerged", force=True) == 0    # --force still discards
    assert not _branch_exists(repo, "session/left-unmerged")


def test_close_treats_an_uncountable_branch_as_unmerged(repo, monkeypatch):
    """`rev-list` failing used to read as "" -> not unlanded -> `branch -D`."""
    path = _open(repo, "uncountable")
    mod = _load("uncountable")
    monkeypatch.setattr(mod, "REPO_ROOT", path)
    real = mod.git

    def git(*args, **kw):
        if args[:1] == ("rev-list",):
            return subprocess.CompletedProcess(["git", *args], 128, "", "fatal: bad revision\n")
        return real(*args, **kw)

    monkeypatch.setattr(mod, "git", git)
    assert _close(mod, repo, "uncountable") == 1
    assert path.exists()
    assert _branch_exists(repo, "session/uncountable")


def test_prune_deletes_only_husks_whose_commits_live_on_elsewhere(repo, monkeypatch, capsys):
    """A husk may hold the last pointer to a commit. Delete it only when that commit is
    reachable, or was rebased (same author time, email and subject) onto something that is."""
    main = repo.main
    head = _git("rev-parse", "HEAD", cwd=main)
    at = _git("log", "-1", "--format=%at", cwd=main)
    env = {**os.environ, "GIT_AUTHOR_DATE": f"{at} +0000"}
    rebased_away = _git("commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "c0", cwd=main, env=env)
    never_landed = _git("commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "work nobody landed", cwd=main)
    admin_root = main / ".git" / "worktrees"
    husks = {"reachable": head, "rebased": rebased_away, "lost": never_landed}
    for name, sha in husks.items():
        (admin_root / name / "logs").mkdir(parents=True)
        (admin_root / name / "ORIG_HEAD").write_text(sha + "\n")
        if ON_WINDOWS:
            _set_readonly_dirs(admin_root / name)
    if ON_WINDOWS:
        _git("worktree", "prune", cwd=main, check=False)            # what every close does today
        assert all((admin_root / n).exists() for n in husks), "precondition: git cannot delete them"

    mod = _load("prune")
    monkeypatch.setattr(mod, "REPO_ROOT", main)

    assert mod.cmd_prune(Namespace(apply=False, root=repo.sessions)) == 0
    assert all((admin_root / n).exists() for n in husks)           # a dry run by default

    assert mod.cmd_prune(Namespace(apply=True, root=repo.sessions)) == 0
    assert not (admin_root / "reachable").exists()
    assert not (admin_root / "rebased").exists()
    assert (admin_root / "lost").exists()
    assert never_landed[:10] in capsys.readouterr().out


def test_prune_holds_a_husk_whose_checkout_folder_still_exists(repo, monkeypatch, capsys):
    """Measured 2026-09-10: `arm2-denominator-wt2` was stale to git while its checkout
    folder still existed -- emptied by a remove that could not delete the folder a shell
    sat in. Once `gitdir` is gone nothing records the path, so the name is the only clue:
    look in the session root and in the directory above it (ad-hoc `C:\\tmp\\<name>`)."""
    main = repo.main
    head = _git("rev-parse", "HEAD", cwd=main)
    admin_root = main / ".git" / "worktrees"
    for name in ("folder-gone", "folder-in-sessions", "folder-adhoc-x7"):
        (admin_root / name / "logs").mkdir(parents=True)
        (admin_root / name / "ORIG_HEAD").write_text(head + "\n")     # nothing lost, either way
    (repo.sessions / "folder-in-sessions").mkdir()                     # empty, like the real one
    (repo.sessions.parent / "folder-adhoc-x7").mkdir()
    mod = _load("prune_guard")
    monkeypatch.setattr(mod, "REPO_ROOT", main)

    assert mod.cmd_prune(Namespace(apply=True, root=repo.sessions)) == 0

    assert not (admin_root / "folder-gone").exists()
    assert (admin_root / "folder-in-sessions").exists()
    assert (admin_root / "folder-adhoc-x7").exists()
    out = capsys.readouterr().out
    assert "HELD folder-in-sessions" in out and str(repo.sessions / "folder-in-sessions") in out
    assert "HELD folder-adhoc-x7" in out
