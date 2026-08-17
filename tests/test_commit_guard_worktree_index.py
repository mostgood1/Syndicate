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


def _stage_a_deletion_of_a_file_still_on_disk(repo: Path) -> Path:
    """Predicate 1's shape: `D` in the index, present in the worktree."""
    doomed = repo / "ondisk.txt"
    doomed.write_text("keep-me\n", encoding="utf-8")
    _run(repo, "add", "ondisk.txt")
    _run(repo, "commit", "-qm", "third")
    _run(repo, "rm", "--cached", "-q", "ondisk.txt")
    assert doomed.exists()
    return doomed


def _an_unrelated_edit(repo: Path) -> str:
    """A path with a real worktree change, so a pathspec commit has something to
    do. Returns its repo-relative name."""
    (repo / "mine.txt").write_text("my work\n", encoding="utf-8")
    return "mine.txt"


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


class TestTheCommandSetsTheEnvironment:
    """The guard read `os.environ` for all three of its exemptions, but a
    PreToolUse hook runs BEFORE the shell. Every override this guard documents
    is written as a shell assignment, so none of them could ever reach it.

    Observed 2026-08-17: a session followed the isolated-index recipe printed in
    the guard's own refusal message and was refused again by the same guard.
    """

    def test_the_printed_recipe_is_honoured(self, trees, monkeypatch, capsys):
        """THE LOAD-BEARING ONE. Verbatim the command the refusal message tells
        you to run. Pre-fix this returned 2: the `export` had not run yet."""
        main, _ = trees
        _stage_a_revert(main)
        cmd = ("export GIT_INDEX_FILE=C:/tmp/idx-lane && "
               "git read-tree HEAD && git add -- mine.txt && git commit -m x")
        assert _verdict(monkeypatch, capsys, cmd, cwd=main, project_dir=main) == 0

    def test_the_inline_prefix_form_is_honoured(self, trees, monkeypatch, capsys):
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys,
                        "GIT_INDEX_FILE=/tmp/idx git commit -m x",
                        cwd=main, project_dir=main) == 0

    @pytest.mark.parametrize("var", ["SYNDICATE_ALLOW_STAGED_DELETES",
                                     "SYNDICATE_ALLOW_STAGED_REVERTS"])
    def test_both_documented_overrides_work_from_the_command(
            self, trees, monkeypatch, capsys, var):
        """These are printed as `VAR=1 git commit ...`, which is a shell prefix.
        Neither was reachable before this fix."""
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys, f"{var}=1 git commit -m x",
                        cwd=main, project_dir=main) == 0

    def test_an_assignment_AFTER_the_commit_does_not_exempt_it(
            self, trees, monkeypatch, capsys):
        """Order matters: the commit runs first and sees the shared index."""
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys,
                        "git commit -m x && export GIT_INDEX_FILE=/tmp/idx",
                        cwd=main, project_dir=main) == 2

    def test_an_intervening_unset_wins(self, trees, monkeypatch, capsys):
        """Last write before the commit decides, so `unset` re-arms the guard."""
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys,
                        "export GIT_INDEX_FILE=/tmp/idx; unset GIT_INDEX_FILE; "
                        "git commit -m x",
                        cwd=main, project_dir=main) == 2

    def test_an_empty_assignment_is_not_set(self, trees, monkeypatch, capsys):
        """Matches `os.environ.get()` being falsy for "" -- the behaviour the
        env-only check always had."""
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys, 'GIT_INDEX_FILE="" git commit -m x',
                        cwd=main, project_dir=main) == 2

    def test_a_similarly_named_variable_does_not_exempt(
            self, trees, monkeypatch, capsys):
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys,
                        "MY_GIT_INDEX_FILE_BACKUP=/tmp/x git commit -m x",
                        cwd=main, project_dir=main) == 2


class TestPathspecLimitedCommits:
    """A partial commit builds its tree from HEAD plus the WORKING TREE content
    of the named paths and never consults the index.

    Measured 2026-08-17 against a repo whose index held a revert of one file and
    a `D` of another that was still on disk: `git commit -m x -- <third path>`
    produced a tree that kept both, `--stat` = 1 file. So flagging unrelated
    staged paths on such a commit is a false positive by construction -- which is
    what blocked a `scripts/render_events.py` commit over another session's
    staged `.syndicate/lanes.md`.

    `test_include_is_still_guarded` is the boundary: `-i` is the option that
    re-admits the index, and under it the revert really did land.
    """

    def test_the_observed_false_positive_is_gone(self, trees, monkeypatch, capsys):
        main, _ = trees
        _stage_a_revert(main)
        mine = _an_unrelated_edit(main)
        rc = _verdict(monkeypatch, capsys, f'git commit -m "msg" -- {mine}',
                      cwd=main, project_dir=main)
        assert rc == 0

    def test_a_bare_pathspec_without_the_separator(self, trees, monkeypatch, capsys):
        """`git commit <paths>` is the same partial commit."""
        main, _ = trees
        _stage_a_revert(main)
        mine = _an_unrelated_edit(main)
        assert _verdict(monkeypatch, capsys, f"git commit -m msg {mine}",
                        cwd=main, project_dir=main) == 0

    def test_a_pathspec_naming_the_STALE_path_is_still_exempt(
            self, trees, monkeypatch, capsys):
        """The index is not consulted even for the named paths, so the staged
        blob cannot ride in on its own path either."""
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys, "git commit -m msg -- tracked.txt",
                        cwd=main, project_dir=main) == 0

    def test_predicate_1_is_also_exempt_under_a_pathspec(
            self, trees, monkeypatch, capsys):
        """Both predicates, not just the content one."""
        main, _ = trees
        _stage_a_deletion_of_a_file_still_on_disk(main)
        mine = _an_unrelated_edit(main)
        assert _verdict(monkeypatch, capsys, f"git commit -m msg -- {mine}",
                        cwd=main, project_dir=main) == 0

    def test_pathspec_from_file_is_exempt(self, trees, monkeypatch, capsys):
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys,
                        "git commit --pathspec-from-file=LIST -m msg",
                        cwd=main, project_dir=main) == 0

    def test_amend_with_a_pathspec_is_exempt(self, trees, monkeypatch, capsys):
        main, _ = trees
        _stage_a_revert(main)
        mine = _an_unrelated_edit(main)
        assert _verdict(monkeypatch, capsys, f"git commit --amend -m msg -- {mine}",
                        cwd=main, project_dir=main) == 0

    @pytest.mark.parametrize("opt", ["-i", "--include"])
    def test_include_is_still_guarded(self, trees, monkeypatch, capsys, opt):
        """MEASURED: under `-i` the staged revert LANDED in the commit. This is
        the one pathspec form that re-admits the index."""
        main, _ = trees
        _stage_a_revert(main)
        mine = _an_unrelated_edit(main)
        assert _verdict(monkeypatch, capsys, f"git commit {opt} -m msg -- {mine}",
                        cwd=main, project_dir=main) == 2

    def test_dash_a_is_still_guarded(self, trees, monkeypatch, capsys):
        """`-a` re-stages tracked worktree content, so predicate 2 cannot bite --
        but a `git rm --cached` path is no longer tracked, and MEASURED, `-a`
        committed the deletion. Predicate 1 is live under `-a`."""
        main, _ = trees
        _stage_a_deletion_of_a_file_still_on_disk(main)
        assert _verdict(monkeypatch, capsys, "git commit -a -m msg",
                        cwd=main, project_dir=main) == 2

    def test_a_pathspec_less_commit_is_unchanged(self, trees, monkeypatch, capsys):
        """The whole original contract. Every option here takes a value, and
        none of those values is a pathspec."""
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys,
                        'git commit -m "a message with -- in it" --author="A <a@a>"',
                        cwd=main, project_dir=main) == 2

    def test_a_bare_dash_dash_with_no_paths_is_not_pathspec_limited(
            self, trees, monkeypatch, capsys):
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys, "git commit -m msg --",
                        cwd=main, project_dir=main) == 2

    def test_an_unknown_option_keeps_guarding(self, trees, monkeypatch, capsys):
        """The parser's failure direction must be a false positive, never a
        false negative: an option it cannot classify might be eating the word
        that looks like a pathspec."""
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys,
                        "git commit --some-future-option value",
                        cwd=main, project_dir=main) == 2

    def test_a_later_command_in_the_chain_is_not_read_as_a_pathspec(
            self, trees, monkeypatch, capsys):
        """`shell_words` must stop at the separator, or `git push` becomes a
        pathspec and silences the guard."""
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys, "git commit -m msg && git push",
                        cwd=main, project_dir=main) == 2

    def test_unbalanced_quoting_keeps_guarding(self, trees, monkeypatch, capsys):
        main, _ = trees
        _stage_a_revert(main)
        assert _verdict(monkeypatch, capsys, 'git commit -m "unclosed msg',
                        cwd=main, project_dir=main) == 2


class TestPathspecParsing:
    """Direct unit coverage of the word/option split, where the false-negative
    risk lives: a mis-parsed `-m` value read as a pathspec silences the guard."""

    @pytest.mark.parametrize("cmd,expected", [
        ("-m msg -- a.py", True),
        ("-m msg a.py", True),
        ("a.py -m msg", True),                  # git permutes
        ("-am msg", False),                     # cluster: 'm' eats the next word
        ("-m msg", False),
        ("-mmsg", False),                       # attached value, no pathspec
        ("--message=msg", False),
        ("--message msg", False),
        ("-F msg.txt", False),                  # -F's value is not a pathspec
        ("--file msg.txt", False),
        ("-S a.py", True),                      # -S's key is ATTACHED only
        ("-Skeyid", False),
        ("--amend --no-edit", False),
        ("--amend --no-edit -- a.py", True),
        ("-i -m msg -- a.py", False),
        ("--include -- a.py", False),
        ("--pathspec-from-file=LIST", True),
        ("-a", False),
        ("--", False),
        ("--unknown-opt a.py", False),          # conservative
        ("-m msg -- 'a file.py'", True),
    ])
    def test_pathspec_detection(self, cmd, expected):
        assert guard.pathspec_limited(guard.shell_words(cmd)) is expected

    @pytest.mark.parametrize("text,expected", [
        ("-m msg && git push", ["-m", "msg"]),
        ("-m msg; echo hi", ["-m", "msg"]),
        ("-m 'two words'", ["-m", "two words"]),
        ('-m "$(date)" -- a.py', ["-m", "$(date)", "--", "a.py"]),
        ("-m a\\ b", ["-m", "a b"]),
    ])
    def test_words_stop_at_the_separator(self, text, expected):
        assert guard.shell_words(text) == expected

    def test_unbalanced_quotes_are_unparseable(self):
        assert guard.shell_words('-m "unclosed') is None
