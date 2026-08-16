"""`commit-guard.py` must read the index the COMMIT will use, not the main one.

Lane `commit-guard-reads-wrong-index`. Evidence: 2026-08-16, a session
committing from `/c/tmp/lgl-ck` was blocked three times over content reverts
staged in the MAIN worktree's index, while its own index held exactly its four
intended appends.

THE TWO FAILURES ARE OPPOSITE AND THE SECOND IS THE DANGEROUS ONE:

  false positive — main's index is dirty, the commit's worktree is clean
                   -> blocked for someone else's problem
  false negative — the commit's worktree index holds a revert, main is clean
                   -> passed silently, which is the entire hazard this guard
                      was written to catch

`test_a_stale_index_in_the_LINKED_worktree_is_caught` is the load-bearing one:
it fails on the pre-fix guard by returning 0, and no amount of testing the false
positive would have revealed it.

These build REAL git repos in tmp_path rather than mocking git. The bug was in
which directory git ran in, so a mocked git would have reproduced nothing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "commit-guard.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("commit_guard", _HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load_guard()


def _run(cwd, *args, **kw):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=True, **kw)


def _repo(path: Path) -> Path:
    """A real repo with two commits, so `HEAD^` resolves."""
    path.mkdir(parents=True, exist_ok=True)
    _run(path, "init", "-q", "-b", "main")
    _run(path, "config", "user.email", "t@t.t")
    _run(path, "config", "user.name", "t")
    f = path / "tracked.txt"
    f.write_text("line-one\n", encoding="utf-8")
    _run(path, "add", "tracked.txt")
    _run(path, "commit", "-qm", "first")
    f.write_text("line-one\nline-two\n", encoding="utf-8")
    _run(path, "add", "tracked.txt")
    _run(path, "commit", "-qm", "second")
    return path


def _stage_a_revert(repo: Path):
    """Stage HEAD^'s blob while the worktree keeps HEAD's content.

    This is the exact shape a stale shared index makes: the staged blob drops a
    line that is present in BOTH HEAD and on disk. Nobody deleted it.
    """
    sha = _run(repo, "rev-parse", "HEAD^:tracked.txt").stdout.strip()
    _run(repo, "update-index", "--cacheinfo", f"100644,{sha},tracked.txt")
    assert (repo / "tracked.txt").read_text(encoding="utf-8").count("line-two") == 1


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Cleared HERE, not inside `_verdict`, so a test can set one afterwards.

    Doing it in the helper silently un-set the very variable
    `test_an_isolated_index_is_still_exempt` had just set, and the test failed
    against a correct guard — a check failing where the subject was fine.
    """
    for key in ("GIT_INDEX_FILE", "SYNDICATE_ALLOW_STAGED_DELETES",
                "SYNDICATE_ALLOW_STAGED_REVERTS"):
        monkeypatch.delenv(key, raising=False)


def _verdict(monkeypatch, capsys, cmd, cwd, project_dir):
    """Run the hook's main() over a PreToolUse payload; return its exit code."""
    payload = {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": cmd}}
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    monkeypatch.setattr(sys, "stdin", _Stdin(json.dumps(payload)))
    rc = guard.main()
    capsys.readouterr()
    return rc


class _Stdin:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text


@pytest.fixture
def trees(tmp_path):
    """A `main` repo and a SEPARATE `linked` repo, each independently dirtyable."""
    return _repo(tmp_path / "main"), _repo(tmp_path / "linked")


class TestWhichIndexIsRead:
    def test_a_stale_index_in_the_LINKED_worktree_is_caught(self, trees, monkeypatch, capsys):
        """THE FALSE NEGATIVE. Pre-fix this returned 0: the guard read main's
        index, found it clean, and waved through a revert-in-waiting."""
        main, linked = trees
        _stage_a_revert(linked)
        rc = _verdict(monkeypatch, capsys,
                      f'cd {linked} && git commit -m x', cwd=main, project_dir=main)
        assert rc == 2

    def test_a_clean_linked_worktree_is_NOT_blocked_by_a_dirty_main(self, trees, monkeypatch, capsys):
        """THE FALSE POSITIVE, observed three times in one session."""
        main, linked = trees
        _stage_a_revert(main)
        rc = _verdict(monkeypatch, capsys,
                      f'cd {linked} && git commit -m x', cwd=main, project_dir=main)
        assert rc == 0

    def test_the_main_worktree_is_still_guarded(self, trees, monkeypatch, capsys):
        """The original behaviour must survive the fix."""
        main, _ = trees
        _stage_a_revert(main)
        rc = _verdict(monkeypatch, capsys, "git commit -m x", cwd=main, project_dir=main)
        assert rc == 2

    def test_a_clean_tree_commits(self, trees, monkeypatch, capsys):
        main, _ = trees
        assert _verdict(monkeypatch, capsys, "git commit -m x",
                        cwd=main, project_dir=main) == 0

    def test_dash_C_is_now_checked_rather_than_waved_through(self, trees, monkeypatch, capsys):
        """`git -C <dir> commit` was skipped on the reasoning that it "has its
        own index". Having your own index is not having a FRESH one."""
        main, linked = trees
        _stage_a_revert(linked)
        rc = _verdict(monkeypatch, capsys, f"git -C {linked} commit -m x",
                      cwd=main, project_dir=main)
        assert rc == 2

    def test_the_payload_cwd_is_used_when_the_command_does_not_cd(self, trees, monkeypatch, capsys):
        """The Bash tool's cwd persists across calls, so a bare `git commit` can
        land in a worktree an EARLIER call cd'd into."""
        main, linked = trees
        _stage_a_revert(linked)
        rc = _verdict(monkeypatch, capsys, "git commit -m x",
                      cwd=linked, project_dir=main)
        assert rc == 2

    def test_the_last_cd_wins_and_relative_hops_compose(self, trees, monkeypatch, capsys):
        main, linked = trees
        _stage_a_revert(linked)
        parent, leaf = linked.parent, linked.name
        rc = _verdict(monkeypatch, capsys,
                      f'cd {parent} && cd {leaf} && git commit -m x',
                      cwd=main, project_dir=main)
        assert rc == 2

    def test_a_quoted_cd_path_resolves(self, tmp_path, monkeypatch, capsys):
        main = _repo(tmp_path / "main")
        spaced = _repo(tmp_path / "dir with space")
        _stage_a_revert(spaced)
        rc = _verdict(monkeypatch, capsys, f'cd "{spaced}" && git commit -m x',
                      cwd=main, project_dir=main)
        assert rc == 2


class TestUnchangedContracts:
    def test_an_isolated_index_is_still_exempt(self, trees, monkeypatch, capsys):
        main, _ = trees
        _stage_a_revert(main)
        monkeypatch.setenv("GIT_INDEX_FILE", "/tmp/whatever")
        assert _verdict(monkeypatch, capsys, "git commit -m x",
                        cwd=main, project_dir=main) == 0

    def test_git_dir_stays_skipped_and_is_a_KNOWN_gap(self, trees, monkeypatch, capsys):
        """Index and worktree decouple here, so predicate 1 has no correct base.
        Asserted so the skip stays a decision rather than becoming an accident."""
        main, linked = trees
        _stage_a_revert(linked)
        rc = _verdict(monkeypatch, capsys,
                      f"git --git-dir={linked}/.git commit -m x", cwd=main, project_dir=main)
        assert rc == 0

    def test_commit_tree_is_not_a_commit(self, trees, monkeypatch, capsys):
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys, "git commit-tree $T -p $P",
                        cwd=main, project_dir=main) == 0

    def test_a_non_repo_cwd_does_not_block_work(self, tmp_path, monkeypatch, capsys):
        """A guard that cannot read must not block."""
        main = _repo(tmp_path / "main")
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        assert _verdict(monkeypatch, capsys, f"cd {outside} && git commit -m x",
                        cwd=main, project_dir=main) == 0

    def test_a_staged_deletion_of_a_file_still_on_disk_is_caught_in_the_linked_tree(
            self, trees, monkeypatch, capsys):
        """Predicate 1 must follow the cwd too, not only predicate 2."""
        main, linked = trees
        _run(linked, "rm", "--cached", "-q", "tracked.txt")
        assert (linked / "tracked.txt").exists()
        rc = _verdict(monkeypatch, capsys, f"cd {linked} && git commit -m x",
                      cwd=main, project_dir=main)
        assert rc == 2
