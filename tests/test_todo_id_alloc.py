"""`#536`. Two sessions must not be handed the same TODO id.

WHY THIS EXISTS. Ids were allocated by reading `todo.md`, taking the largest and
adding one. The read and the write are not atomic, so two sessions looking at the
same moment pick the same number -- and the loser finds out at `git merge`, after
the entry, the code comments and the tests are written and have to be renamed
together, because a stale `#N` in a comment resolves to somebody else's item and
reads as deliberate.

Measured 2026-08-23: **eight collisions in one session**, across at least three
sessions -- 514/515 -> 520/521, 522 -> 523, 524 -> 525, 527/528 -> 530/531,
532 -> 536.

The mechanism is the one `deploy_claim.py` already uses and whose docstring
explains why messaging cannot substitute for it. These tests pin the property
that matters (no two callers get the same number) rather than the file layout.

2026-09-10: the same property ACROSS TREES. With one worktree per session, the
O_EXCL directory was each tree's own copy of the tracked `.syndicate/todo_ids/`,
so two worktrees both won the same number (`#562`/`#563`), and a tree behind
`origin/main` re-issued a landed id (`#569`).

2026-09-10, later: ACROSS CLONES. No local lock reaches another machine, so the
id is reserved by pushing its claim to `main`; the remote's compare-and-swap is
the lock. The last tests drive the real script through a real bare remote.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import todo_id_alloc as alloc

# Captured before any fixture patches them, for the tests that need the real ones.
REAL_ORIGIN_IDS = getattr(alloc, "_origin_ids", None)


def _no_git(*args, **kwargs):
    raise AssertionError(f"a unit test reached the real repo's git: {args}")


@pytest.fixture
def _sandbox(tmp_path, monkeypatch):
    todo = tmp_path / "todo.md"
    closed = tmp_path / "todo_closed.md"
    todo.write_text("# t\n\n### `#100` — a\n\n### `#102` — b\n", encoding="utf-8")
    closed.write_text("### `#101` — c\n", encoding="utf-8")
    monkeypatch.setattr(alloc, "TODO", todo)
    monkeypatch.setattr(alloc, "CLOSED", closed)
    monkeypatch.setattr(alloc, "CLAIM_DIR", tmp_path / "ids")
    # Every source that is not a file in the sandbox, pinned -- a unit test must
    # never read this repo's origin/main, write its shared claim dir, or PUSH.
    # `raising=False` so the same fixture also drives an older module.
    monkeypatch.setattr(alloc, "PUSH", False, raising=False)
    monkeypatch.setattr(alloc, "_origin_ids", lambda fetch: set(), raising=False)
    monkeypatch.setattr(alloc, "_shared_claim_dir", lambda: tmp_path / "shared", raising=False)
    monkeypatch.setattr(alloc, "_main_claim_dir", lambda: None, raising=False)
    monkeypatch.setattr(alloc, "_git", _no_git, raising=False)
    return tmp_path


def test_the_high_water_mark_spans_both_ledgers(_sandbox):
    """An id closed and archived is still ISSUED. Reading only the open file
    would re-issue it, and `todo.md`'s own rule is that ids never repeat."""
    assert alloc.high_water() == 102


def test_it_reads_the_archive_s_older_formats(_sandbox, monkeypatch):
    """The archive carries table rows and bullets, not just headers --
    `todo_id_reconcile.py` documents both eras. A scanner that saw only today's
    format would under-report the mark and collide with history."""
    (_sandbox / "todo_closed.md").write_text(
        "| **310** | old table row |\n- **#311 a bullet\n#### `#312` a sub-header\n",
        encoding="utf-8",
    )
    assert alloc.high_water() == 312


def test_two_callers_never_get_the_same_id(_sandbox):
    """THE PROPERTY. This is the whole point of the tool."""
    first = alloc.allocate("lane-a")
    second = alloc.allocate("lane-b")
    assert first == [103]
    assert second == [104]
    assert set(first).isdisjoint(second)


def test_a_claim_counts_toward_the_mark_before_the_entry_is_written(_sandbox):
    """The gap the ledger scan cannot see: an id allocated a minute ago is not in
    `todo.md` yet -- the entry is still being written. Ignoring claims would hand
    the same number to the next caller, which IS the bug."""
    alloc.allocate("lane-a")
    assert alloc.high_water() == 103


def test_an_existing_claim_is_stepped_over_not_overwritten(_sandbox):
    (_sandbox / "ids").mkdir()
    (_sandbox / "ids" / "103.claim").write_text("{}", encoding="utf-8")
    assert alloc.allocate("lane-b") == [104]
    # The squatter's file must be untouched -- overwriting it would silently
    # transfer an id somebody else is already writing an entry for.
    assert (_sandbox / "ids" / "103.claim").read_text(encoding="utf-8") == "{}"


def test_it_can_allocate_a_contiguous_batch(_sandbox):
    assert alloc.allocate("lane-a", count=3) == [103, 104, 105]


def test_the_claim_records_who_took_it(_sandbox):
    """A claim nobody can attribute is a gap with no owner to ask about."""
    (value,) = alloc.allocate("layer2-sim-view-and-live-projection")
    payload = json.loads((_sandbox / "ids" / f"{value}.claim").read_text(encoding="utf-8"))
    assert payload["id"] == value
    assert payload["holder"] == "layer2-sim-view-and-live-projection"
    assert payload["claimed_at"]


def test_empty_ledgers_start_at_one(_sandbox):
    (_sandbox / "todo.md").write_text("# nothing\n", encoding="utf-8")
    (_sandbox / "todo_closed.md").write_text("", encoding="utf-8")
    assert alloc.allocate("lane-a") == [1]


def test_a_missing_ledger_is_not_a_crash(_sandbox):
    """Absent must not read as id 0 and must not raise -- this runs at the start
    of somebody's work, and a tool that fails there gets bypassed."""
    (_sandbox / "todo_closed.md").unlink()
    assert alloc.high_water() == 102


# --- across trees ------------------------------------------------------------


def test_two_worktrees_never_get_the_same_id(_sandbox, monkeypatch):
    """Same base commit, two trees, two private copies of the tracked claim dir:
    O_EXCL in either one could not see the other. The lock is now the shared
    dir, which both trees reach."""
    first = alloc.allocate("tree-a")
    tree_b = _sandbox / "tree_b"
    tree_b.mkdir()
    for name in ("todo.md", "todo_closed.md"):
        (tree_b / name).write_text((_sandbox / name).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(alloc, "TODO", tree_b / "todo.md")
    monkeypatch.setattr(alloc, "CLOSED", tree_b / "todo_closed.md")
    monkeypatch.setattr(alloc, "CLAIM_DIR", tree_b / "ids")
    second = alloc.allocate("tree-b")
    assert (first, second) == ([103], [104])


def test_a_tree_behind_origin_does_not_reissue_a_landed_id(_sandbox, monkeypatch):
    """`#569`: the local ledger stops at 102, `origin/main` already has 110."""
    monkeypatch.setattr(alloc, "_origin_ids", lambda fetch: {110}, raising=False)
    assert alloc.allocate("stale-tree") == [111]


def test_a_claim_an_older_copy_left_in_the_main_tree_counts(_sandbox, monkeypatch):
    """The primary tree routinely runs a stale copy of this script, and that copy
    writes only into the primary tree's own claim dir."""
    main_ids = _sandbox / "main_ids"
    main_ids.mkdir()
    (main_ids / "120.claim").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(alloc, "_main_claim_dir", lambda: main_ids, raising=False)
    assert alloc.allocate("lane-a") == [121]


def test_the_shared_claim_is_the_lock_and_the_tracked_one_is_the_record(_sandbox):
    (value,) = alloc.allocate("lane-a")
    assert (_sandbox / "shared" / f"{value}.claim").is_file()
    assert (_sandbox / "ids" / f"{value}.claim").is_file()


def test_an_unreachable_origin_warns_and_still_allocates(_sandbox, monkeypatch, capsys):
    """Offline must not block the start of someone's work -- and must not pass
    silently either, because the mark then covers this machine only."""
    assert REAL_ORIGIN_IDS is not None, "no _origin_ids: origin/main is never read"
    monkeypatch.setattr(alloc, "_origin_ids", REAL_ORIGIN_IDS)
    monkeypatch.setattr(alloc, "_git", lambda *a, **k: subprocess.CompletedProcess(a, 128, "", "fatal"))
    assert alloc.high_water(fetch=True) == 102
    err = capsys.readouterr().err
    assert "fetch origin main` failed" in err and "unreadable" in err


# --- across clones: reserved by push ------------------------------------------


def test_a_push_that_loses_the_race_retries_with_a_fresh_mark(_sandbox, monkeypatch):
    """Two clones built the same number on the same parent and the remote took
    the other one. Re-fetch, re-read the mark, take the next number."""
    views = iter([set(), {103}])            # the winner's claim appears on the second fetch
    state = {"origin": set()}

    def origin_base():
        state["origin"] = next(views)
        return "base"

    built, verdicts = [], iter(["moved", "ok"])
    monkeypatch.setattr(alloc, "PUSH", True, raising=False)
    monkeypatch.setattr(alloc, "_origin_base", origin_base, raising=False)
    monkeypatch.setattr(alloc, "_origin_ids", lambda fetch: state["origin"], raising=False)
    monkeypatch.setattr(alloc, "_claim_commit",
                        lambda base, payloads, holder: built.append(sorted(payloads)) or "c", raising=False)
    monkeypatch.setattr(alloc, "_push", lambda commit: next(verdicts), raising=False)
    assert alloc.allocate("clone-b") == [104]
    assert built == [[103], [104]]


def test_a_push_that_cannot_happen_falls_back_to_the_local_lock_loudly(_sandbox, monkeypatch, capsys):
    """Offline or unauthorised: still an id, still the tracked record that makes
    a collision loud at land -- and a warning, because the remote holds nothing."""
    monkeypatch.setattr(alloc, "PUSH", True, raising=False)
    monkeypatch.setattr(alloc, "_origin_base", lambda: "base", raising=False)
    monkeypatch.setattr(alloc, "_claim_commit", lambda *a: "c", raising=False)
    monkeypatch.setattr(alloc, "_push", lambda commit: "error: Authentication failed", raising=False)
    assert alloc.allocate("offline") == [103]
    assert (_sandbox / "ids" / "103.claim").is_file()
    assert "THIS machine only" in capsys.readouterr().err


def test_no_reachable_origin_falls_back_too(_sandbox, monkeypatch, capsys):
    monkeypatch.setattr(alloc, "PUSH", True, raising=False)
    monkeypatch.setattr(alloc, "_origin_base", lambda: None, raising=False)
    assert alloc.allocate("offline") == [103]
    assert "THIS machine only" in capsys.readouterr().err


# --- the real script, through a real bare remote --------------------------------


def _git(*args, cwd):
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert done.returncode == 0, f"git {' '.join(args)}: {done.stderr}"
    return done.stdout.strip()


def _run(tree: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(tree / "scripts" / "todo_id_alloc.py"), *args],
                          cwd=str(tree), capture_output=True, text=True)


def _origin_claims(origin: Path) -> set[str]:
    listed = _git("--git-dir", str(origin), "ls-tree", "--name-only", "main", "--",
                  ".syndicate/todo_ids/", cwd=origin)
    return {Path(line).name for line in listed.splitlines()}


def _hermetic(base: Path, monkeypatch) -> None:
    (base / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(base / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "test")
        monkeypatch.setenv(f"{key}_EMAIL", "test@example.invalid")


def _seed(repo: Path, origin: Path) -> None:
    (repo / "docs" / "ai_context").mkdir(parents=True)
    (repo / "docs" / "ai_context" / "todo.md").write_text("### `#100` — a\n", encoding="utf-8")
    (repo / "docs" / "ai_context" / "todo_closed.md").write_text("", encoding="utf-8")
    (repo / ".syndicate" / "todo_ids").mkdir(parents=True)
    (repo / ".syndicate" / "todo_ids" / "100.claim").write_text("{}", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "todo_id_alloc.py").write_bytes((ROOT / "scripts" / "todo_id_alloc.py").read_bytes())
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)
    _git("remote", "add", "origin", str(origin), cwd=repo)
    _git("push", "-q", "-u", "origin", "main", cwd=repo)


@pytest.fixture
def real_repo(tmp_path, monkeypatch):
    """One clone with a session worktree; a peer lands `#107` after both were cut."""
    base = tmp_path.resolve()
    _hermetic(base, monkeypatch)
    origin, main, peer, tree = base / "origin.git", base / "main", base / "peer", base / "wt"
    _git("init", "-q", "--bare", "-b", "main", str(origin), cwd=base)
    _git("init", "-q", "-b", "main", str(main), cwd=base)
    _seed(main, origin)
    _git("worktree", "add", "-q", "-b", "session/w", str(tree), "origin/main", cwd=main)
    _git("clone", "-q", str(origin), str(peer), cwd=base)
    with (peer / "docs" / "ai_context" / "todo.md").open("a", encoding="utf-8") as fh:
        fh.write("\n### `#107` — landed by a peer\n")
    _git("commit", "-q", "-am", "peer lands 107", cwd=peer)
    _git("push", "-q", "origin", "main", cwd=peer)
    return SimpleNamespace(origin=origin, main=main, tree=tree)


@pytest.fixture
def two_clones(tmp_path, monkeypatch):
    """Two machines: separate clones of one bare remote, sharing no `.git`."""
    base = tmp_path.resolve()
    _hermetic(base, monkeypatch)
    origin, seed, a, b = base / "origin.git", base / "seed", base / "a", base / "b"
    _git("init", "-q", "--bare", "-b", "main", str(origin), cwd=base)
    _git("init", "-q", "-b", "main", str(seed), cwd=base)
    _seed(seed, origin)
    _git("clone", "-q", str(origin), str(a), cwd=base)
    _git("clone", "-q", str(origin), str(b), cwd=base)
    return SimpleNamespace(origin=origin, a=a, b=b)


def test_the_machine_lock_serialises_two_real_worktrees(real_repo):
    """`--no-push`: each tree runs ITS OWN copy, exactly as sessions do, and the
    shared lock in the git common dir is all that stands between them."""
    in_tree = _run(real_repo.tree, "--holder", "session-w", "--no-push")
    in_main = _run(real_repo.main, "--holder", "primary", "--no-push")
    assert in_tree.returncode == 0, in_tree.stderr
    assert in_main.returncode == 0, in_main.stderr
    got = (in_tree.stdout.strip(), in_main.stdout.strip())
    assert got == ("108", "109"), got          # above the peer's 107, and never the same
    lock = real_repo.main / ".git" / "syndicate" / "todo_ids"
    assert (lock / "108.claim").is_file() and (lock / "109.claim").is_file()
    assert (real_repo.tree / ".syndicate" / "todo_ids" / "108.claim").is_file()   # the record
    assert (real_repo.main / ".syndicate" / "todo_ids" / "109.claim").is_file()


def test_two_real_worktrees_reserve_on_the_remote(real_repo):
    """The default: the reservation is a commit on `main`, not a file in the tree."""
    in_tree = _run(real_repo.tree, "--holder", "session-w")
    in_main = _run(real_repo.main, "--holder", "primary")
    assert (in_tree.stdout.strip(), in_main.stdout.strip()) == ("108", "109"), (in_tree.stderr, in_main.stderr)
    assert {"108.claim", "109.claim"} <= _origin_claims(real_repo.origin)
    # No untracked copy: it would block the session's next rebase onto main.
    assert not (real_repo.tree / ".syndicate" / "todo_ids" / "108.claim").exists()
    assert not (real_repo.main / ".syndicate" / "todo_ids" / "109.claim").exists()
    # And the session can still move onto the new main.
    _git("rebase", "-q", "origin/main", cwd=real_repo.tree)


def test_two_separate_clones_are_serialised_by_the_push(two_clones):
    """THE GAP `#563` NAMED: two machines, no shared `.git`, one number each."""
    a = _run(two_clones.a, "--holder", "clone-a")
    b = _run(two_clones.b, "--holder", "clone-b")
    assert a.returncode == 0 and b.returncode == 0, (a.stderr, b.stderr)
    assert (a.stdout.strip(), b.stdout.strip()) == ("101", "102")
    assert {"101.claim", "102.claim"} <= _origin_claims(two_clones.origin)
    subjects = _git("--git-dir", str(two_clones.origin), "log", "-2", "--format=%s", "main",
                    cwd=two_clones.origin).splitlines()
    assert len(subjects) == 2 and all("[skip ci]" in s for s in subjects), subjects


def test_a_reservation_on_a_stale_base_is_rejected_by_the_remote(two_clones, monkeypatch):
    """The property the design rests on, against a REAL remote: a push is a
    compare-and-swap. Clone B builds on the `main` it saw; clone A moves `main`
    first; B's push must be refused, and B's next attempt takes the next number."""
    b = two_clones.b
    monkeypatch.setattr(alloc, "REPO", b)
    monkeypatch.setattr(alloc, "TODO", b / "docs" / "ai_context" / "todo.md")
    monkeypatch.setattr(alloc, "CLOSED", b / "docs" / "ai_context" / "todo_closed.md")
    monkeypatch.setattr(alloc, "CLAIM_DIR", b / ".syndicate" / "todo_ids")
    stale = alloc._origin_base()
    assert _run(two_clones.a, "--holder", "clone-a").stdout.strip() == "101"
    commit = alloc._claim_commit(stale, {101: alloc._payload(101, "clone-b")}, "clone-b")
    assert alloc._push(commit) == "moved"
    assert alloc.allocate("clone-b", push=True) == [102]
    assert {"101.claim", "102.claim"} <= _origin_claims(two_clones.origin)
