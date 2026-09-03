"""Both deploy locks must land in the tree `deploy-guard.py` reads.

MEASURED 2026-09-03. Sessions each work in their own git worktree
(`session_worktree.py`), so a copy of `deploy_claim.py` inside a worktree
resolved `REPO_ROOT` to that worktree and wrote the claim there. The guard reads
`CLAUDE_PROJECT_DIR or cwd` -- the PRIMARY tree -- so it answered
`claim NOT HELD by anyone` seconds after a successful `acquire`. Three times in
one session, once mid-deploy. `deploy_preflight.py` had the identical defect and
produced `the CLEAR preflight is for <a different sha>`.

**The blocked deploy is the smaller half.** The larger half is that two sessions
in two worktrees could each `acquire` the same service and BOTH succeed, because
they were writing to different files -- the lock silently non-mutual at exactly
the moment it is load-bearing. That is `#635`'s bug on a new axis: there, two
NAMES for one box; here, two TREES for one repo. In both, every claim was
"valid".
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def claim_mod():
    return _load("deploy_claim")


@pytest.fixture(scope="module")
def preflight_mod():
    return _load("deploy_preflight")


def _git_common_dir() -> Path | None:
    for args in (
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        ["git", "rev-parse", "--git-common-dir"],
    ):
        try:
            done = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, timeout=15)
        except Exception:
            continue
        if done.returncode == 0 and done.stdout.strip():
            p = Path(done.stdout.strip())
            return p if p.is_absolute() else (ROOT / p).resolve()
    return None


def test_the_claim_dir_is_the_main_worktree_not_this_one(claim_mod) -> None:
    """THE FIX. In a worktree these differ; in the primary tree they are equal.
    Either way the claim lands where the guard looks."""
    common = _git_common_dir()
    if common is None or common.name != ".git":
        pytest.skip("not a normal git checkout")

    assert claim_mod.CLAIM_DIR == common.parent / ".syndicate" / "deploy_claims"


def test_the_preflight_receipt_lands_in_the_same_tree(preflight_mod) -> None:
    """Fixing only the claim still blocks: the guard needs BOTH in its tree."""
    common = _git_common_dir()
    if common is None or common.name != ".git":
        pytest.skip("not a normal git checkout")

    assert preflight_mod.RECEIPT_DIR == common.parent / ".syndicate" / "deploy" / "preflight"


def test_both_locks_agree_on_the_tree(claim_mod, preflight_mod) -> None:
    """A claim the guard can see plus a receipt it cannot is still a blocked
    deploy -- and was the first failure of the day."""
    assert claim_mod.CLAIM_DIR.parents[1] == preflight_mod.RECEIPT_DIR.parents[2]


def test_the_guard_reads_exactly_this_path(claim_mod) -> None:
    """Pins the contract against the guard's own construction
    (`os.path.join(root, ".syndicate", "deploy_claims", alias + ".json")`).
    If either side moves, this fails instead of going quietly non-mutual."""
    assert claim_mod.CLAIM_DIR.name == "deploy_claims"
    assert claim_mod.CLAIM_DIR.parent.name == ".syndicate"
    assert claim_mod._path("web").name == "web.json"
    assert claim_mod._path("syndicate").name == "web.json", "#635: one lock per SERVICE"


def test_resolution_falls_back_instead_of_raising(claim_mod, monkeypatch: pytest.MonkeyPatch) -> None:
    """This tool serialises deploys. A claim in the wrong place beats a crash."""
    import subprocess as sp

    def boom(*a, **k):
        raise OSError("git is not on PATH")

    monkeypatch.setattr(sp, "run", boom)
    assert claim_mod._main_worktree_root() == claim_mod.REPO_ROOT


def test_a_nonzero_git_exit_also_falls_back(claim_mod, monkeypatch: pytest.MonkeyPatch) -> None:
    """Not a git checkout at all -- e.g. a source tarball."""
    import subprocess as sp

    class Done:
        returncode = 128
        stdout = ""

    monkeypatch.setattr(sp, "run", lambda *a, **k: Done())
    assert claim_mod._main_worktree_root() == claim_mod.REPO_ROOT


def test_a_bare_or_unexpected_common_dir_is_not_guessed_at(
    claim_mod, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--git-common-dir` that is not a `.git` directory must fall back rather
    than inventing a parent -- writing a lock to a guessed path is worse than
    writing it locally, because it looks like it worked."""
    import subprocess as sp

    bare = tmp_path / "repo.git"
    bare.mkdir()

    class Done:
        returncode = 0
        stdout = str(bare)

    monkeypatch.setattr(sp, "run", lambda *a, **k: Done())
    assert claim_mod._main_worktree_root() == claim_mod.REPO_ROOT


def test_two_trees_resolve_to_ONE_lock_file(claim_mod, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """THE PROPERTY THAT WAS BROKEN, stated directly: two sessions in two
    different worktrees must compute the SAME claim path, or the lock is not a
    lock. Simulates both trees by varying REPO_ROOT under one common dir."""
    import subprocess as sp

    main_tree = tmp_path / "primary"
    (main_tree / ".git").mkdir(parents=True)

    class Done:
        returncode = 0
        stdout = str(main_tree / ".git")

    monkeypatch.setattr(sp, "run", lambda *a, **k: Done())

    resolved = []
    for tree in (main_tree, tmp_path / "wt-a", tmp_path / "wt-b"):
        monkeypatch.setattr(claim_mod, "REPO_ROOT", tree)
        resolved.append(claim_mod._main_worktree_root() / ".syndicate" / "deploy_claims")

    assert len(set(resolved)) == 1, f"three trees produced {len(set(resolved))} lock paths: {resolved}"
    assert resolved[0] == main_tree / ".syndicate" / "deploy_claims"
