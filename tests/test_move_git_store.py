"""The relocation script's two load-bearing behaviours.

THE FIRST TEST PINS A BUG THE DRY RUN CAUGHT AND NOTHING ELSE WOULD HAVE.
`worktree_pointers` computed the required pointer text from the CURRENT store
instead of the target, so the dry run printed 84 rewrites whose `from` and `to`
were identical. With `--apply` that is silent and total: every pointer gets
"rewritten" to the value it already has, the store moves out from under them,
and all 84 worktrees are left pointing at a path that no longer exists. It
would have looked like a clean run -- 84 rewritten, repair exit 0 -- because
nothing checks that a rewrite CHANGED anything.

The second pins that the preflight refuses rather than warns. A move under a
live session can corrupt that session's index, so "dirty tree" has to be a
refusal; a warning is a thing people scroll past.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_SPEC = importlib.util.spec_from_file_location(
    "move_git_store",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "move_git_store.py",
)
mgs = importlib.util.module_from_spec(_SPEC)
sys.modules["move_git_store"] = mgs
_SPEC.loader.exec_module(mgs)


def _fake_repo(tmp_path: pathlib.Path, names=("alpha", "beta")):
    """A repo + store + N worktrees, wired exactly as git wires them."""
    repo = tmp_path / "repo"
    store = repo / ".git"
    (store / "worktrees").mkdir(parents=True)
    for n in names:
        wt = tmp_path / "wt" / n
        wt.mkdir(parents=True)
        (wt / ".git").write_text(f"gitdir: {(store / 'worktrees' / n).as_posix()}\n", encoding="utf-8")
        entry = store / "worktrees" / n
        entry.mkdir()
        (entry / "gitdir").write_text(str(wt / ".git"), encoding="utf-8")
    return repo, store


def test_required_pointer_derives_from_the_TARGET_not_the_current_store(tmp_path):
    repo, store = _fake_repo(tmp_path)
    target = tmp_path / "gitstore" / "Syndicate.git"

    rows = mgs.worktree_pointers(repo, store, target)
    assert len(rows) == 2
    for wt_path, wt_git, cur, want, name, err in rows:
        assert err is None
        # the whole point: the rewrite must be a CHANGE
        assert cur != want, f"{name}: rewrite is a no-op -- this is the bug"
        assert want == f"gitdir: {(target / 'worktrees' / name).as_posix()}"
        assert str(store.as_posix()) not in want, f"{name}: still points into the old store"


def test_omitting_the_target_yields_the_current_store_for_the_baseline_read(tmp_path):
    """The default is only correct for the read-only baseline call, and is pinned
    so nobody 'simplifies' the parameter away and reintroduces the no-op."""
    repo, store = _fake_repo(tmp_path)
    rows = mgs.worktree_pointers(repo, store)
    for _p, _g, cur, want, _n, _e in rows:
        assert cur == want


def test_a_dead_registration_is_reported_not_skipped(tmp_path):
    """A `.git/worktrees/<name>` with no `gitdir` file is invisible to
    `git worktree list`. That asymmetry hid 36 dead entries; this reads the
    directory, so it must SURFACE them."""
    repo, store = _fake_repo(tmp_path)
    (store / "worktrees" / "ghost").mkdir()
    rows = mgs.worktree_pointers(repo, store, tmp_path / "t")
    ghosts = [r for r in rows if r[5] is not None]
    assert len(ghosts) == 1 and ghosts[0][4] == "ghost"


def test_preflight_refuses_a_target_inside_onedrive(tmp_path, monkeypatch):
    repo, store = _fake_repo(tmp_path)
    monkeypatch.setenv("OneDrive", str(tmp_path / "OneDrive"))
    bad = tmp_path / "OneDrive" / "gitstore"
    problems = mgs.preflight(repo, store, bad)
    assert any("ITSELF inside OneDrive" in p for p in problems), problems


def test_preflight_refuses_while_a_git_operation_is_in_flight(tmp_path):
    repo, store = _fake_repo(tmp_path)
    (store / "index.lock").write_text("", encoding="utf-8")
    problems = mgs.preflight(repo, store, tmp_path / "gitstore")
    assert any("IN FLIGHT" in p for p in problems), problems
