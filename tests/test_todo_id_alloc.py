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
`origin/main` re-issued a landed id (`#569`). The last test drives the real
script in two real worktrees of a throwaway repo.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
    # never read this repo's origin/main or write its shared claim dir.
    # `raising=False` so the same fixture also drives an unfixed module.
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


# --- 2026-09-10: across trees -------------------------------------------------


def test_two_worktrees_never_get_the_same_id(_sandbox, monkeypatch):
    """THE LEAD. Same base commit, two trees, two private copies of the tracked
    claim dir: O_EXCL in either one could not see the other. The lock is now the
    shared dir, which both trees reach."""
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


# --- the real script, in two real worktrees ------------------------------------


def _git(*args, cwd):
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert done.returncode == 0, f"git {' '.join(args)}: {done.stderr}"
    return done.stdout.strip()


def _run(tree: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(tree / "scripts" / "todo_id_alloc.py"), *args],
                          cwd=str(tree), capture_output=True, text=True)


@pytest.fixture
def real_repo(tmp_path, monkeypatch):
    base = tmp_path.resolve()
    (base / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(base / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "test")
        monkeypatch.setenv(f"{key}_EMAIL", "test@example.invalid")
    origin, main, peer, tree = base / "origin.git", base / "main", base / "peer", base / "wt"
    _git("init", "-q", "--bare", "-b", "main", str(origin), cwd=base)
    _git("init", "-q", "-b", "main", str(main), cwd=base)
    (main / "docs" / "ai_context").mkdir(parents=True)
    (main / "docs" / "ai_context" / "todo.md").write_text("### `#100` — a\n", encoding="utf-8")
    (main / "docs" / "ai_context" / "todo_closed.md").write_text("", encoding="utf-8")
    (main / ".syndicate" / "todo_ids").mkdir(parents=True)
    (main / ".syndicate" / "todo_ids" / "100.claim").write_text("{}", encoding="utf-8")
    (main / "scripts").mkdir()
    (main / "scripts" / "todo_id_alloc.py").write_bytes((ROOT / "scripts" / "todo_id_alloc.py").read_bytes())
    _git("add", ".", cwd=main)
    _git("commit", "-q", "-m", "base", cwd=main)
    _git("remote", "add", "origin", str(origin), cwd=main)
    _git("push", "-q", "-u", "origin", "main", cwd=main)
    _git("worktree", "add", "-q", "-b", "session/w", str(tree), "origin/main", cwd=main)
    # A peer lands #107 after both trees were cut: both are now BEHIND origin.
    _git("clone", "-q", str(origin), str(peer), cwd=base)
    with (peer / "docs" / "ai_context" / "todo.md").open("a", encoding="utf-8") as fh:
        fh.write("\n### `#107` — landed by a peer\n")
    _git("commit", "-q", "-am", "peer lands 107", cwd=peer)
    _git("push", "-q", "origin", "main", cwd=peer)
    return main, tree


def test_the_real_script_in_two_real_worktrees(real_repo):
    """No monkeypatch: each tree runs ITS OWN copy, exactly as sessions do."""
    main, tree = real_repo
    in_tree = _run(tree, "--holder", "session-w")
    in_main = _run(main, "--holder", "primary")
    assert in_tree.returncode == 0, in_tree.stderr
    assert in_main.returncode == 0, in_main.stderr
    got = (in_tree.stdout.strip(), in_main.stdout.strip())
    assert got == ("108", "109"), got          # above the peer's 107, and never the same
    assert (main / ".git" / "syndicate" / "todo_ids" / "108.claim").is_file()   # the lock
    assert (main / ".git" / "syndicate" / "todo_ids" / "109.claim").is_file()
    assert (tree / ".syndicate" / "todo_ids" / "108.claim").is_file()           # the record
    assert (main / ".syndicate" / "todo_ids" / "109.claim").is_file()
