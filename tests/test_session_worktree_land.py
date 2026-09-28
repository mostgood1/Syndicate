"""`session_worktree.py land --lane X` must find lane X in whichever worktree holds it.

MEASURED 2026-09-28. A worktree is named after the lane that OPENED it, and a
session opened a second lane inside it. `land --lane lane-open-marker-primary-tree`
died with `FATAL: no worktree at .../lane-open-marker-primary-tree`, run from
inside the worktree that held that lane's commit, because `land` only looked at
`<root>/<slug>`. The commit reached main only when landed under the FIRST lane's
name.

These use a real bare origin, a real primary tree and real worktrees. Only the
two ledger checkers are stubbed, because they are repo scripts the fixture does
not have.
"""
from __future__ import annotations

import importlib.util
import subprocess
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "session_worktree.py"
EM = chr(0x2014)


def _load():
    spec = importlib.util.spec_from_file_location("session_worktree_land_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(*args, cwd) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {done.stderr}")
    return done.stdout.strip()


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    base = tmp_path.resolve()
    (base / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(base / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "test")
        monkeypatch.setenv(f"{key}_EMAIL", "test@example.invalid")
    r = SimpleNamespace(origin=base / "origin.git", main=base / "main", sessions=base / "sessions")
    _git("init", "-q", "--bare", "-b", "main", str(r.origin), cwd=base)
    _git("init", "-q", "-b", "main", str(r.main), cwd=base)
    (r.main / ".syndicate").mkdir()
    (r.main / ".syndicate" / "lanes.md").write_text("# Lanes\n\n## OPEN\n\n", encoding="utf-8")
    _git("add", "-A", cwd=r.main)
    _git("commit", "-q", "-m", "c0", cwd=r.main)
    _git("remote", "add", "origin", str(r.origin), cwd=r.main)
    _git("push", "-q", "-u", "origin", "main", cwd=r.main)
    r.sessions.mkdir()
    mod = _load()
    monkeypatch.setattr(mod, "REPO_ROOT", r.main)
    monkeypatch.setattr(mod, "_run_checkers", lambda cwd: [])
    r.mod = mod
    return r


def _open(repo, slug: str) -> Path:
    path = repo.sessions / slug
    _git("worktree", "add", "-q", "-b", f"session/{slug}", str(path), "origin/main", cwd=repo.main)
    return path


def _add_lane(tree: Path, slug: str) -> None:
    """Open a lane inside `tree` and commit it, as lane_open.py + a commit would."""
    lanes = tree / ".syndicate" / "lanes.md"
    lanes.write_text(lanes.read_text(encoding="utf-8")
                     + f"### {slug} {EM} OPEN {EM} opened 2026-09-28 {EM} session s\n"
                     + "- Goal: g\n- Files: x.py\n\n", encoding="utf-8")
    (tree / f"{slug}.txt").write_text("work\n")
    _git("add", "-A", cwd=tree)
    _git("commit", "-q", "-m", f"work for {slug}", cwd=tree)


def test_second_lane_lands_from_the_worktree_that_holds_it(repo, capsys):
    """THE REPRODUCTION."""
    first = _open(repo, "first-lane")
    _add_lane(first, "second-lane")

    rc = repo.mod.cmd_land(Namespace(lane="second-lane", root=repo.sessions,
                                     dry_run=False, allow_duplicate_ids=False))

    assert rc == 0, capsys.readouterr().out
    assert "lands from worktree" in capsys.readouterr().out
    assert "work for second-lane" in _git("log", "--oneline", "main", cwd=repo.origin)


def test_exact_worktree_name_still_wins(repo):
    exact = _open(repo, "the-lane")
    other = _open(repo, "other-lane")
    _add_lane(other, "the-lane")
    path, branch = repo.mod._land_target("the-lane", repo.sessions, cwd=other)
    assert (path.resolve(), branch) == (exact.resolve(), "session/the-lane")


def test_the_worktree_you_are_in_wins_when_several_carry_the_lane(repo):
    """Every worktree rebased after a lane lands carries its block."""
    a, b = _open(repo, "wt-a"), _open(repo, "wt-b")
    _add_lane(a, "shared-lane")
    _add_lane(b, "shared-lane")
    path, branch = repo.mod._land_target("shared-lane", repo.sessions, cwd=b / ".syndicate")
    assert (path, branch) == (b.resolve(), "session/wt-b")


def test_several_candidates_and_none_is_yours_refuses(repo):
    a, b = _open(repo, "wt-a"), _open(repo, "wt-b")
    _add_lane(a, "shared-lane")
    _add_lane(b, "shared-lane")
    with pytest.raises(SystemExit, match="2 session worktrees"):
        repo.mod._land_target("shared-lane", repo.sessions, cwd=repo.main)


def test_unknown_lane_is_still_fatal(repo):
    _open(repo, "wt-a")
    with pytest.raises(SystemExit, match="no worktree at"):
        repo.mod._land_target("no-such-lane", repo.sessions, cwd=repo.main)
