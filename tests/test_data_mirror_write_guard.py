"""The guard that keeps the suite out of the git-tracked `data/` mirror.

WHY THIS FILE EXISTS AND NOT JUST THE GUARD. The guard in `tests/conftest.py`
is an instrument, and an instrument that has only ever returned "healthy" has
not been read -- this repo has a standing rule about exactly that. So the tests
here make it read UNHEALTHY on purpose, and pin the two ways it could be wrong
in the direction that would matter:

  1.  **Silent on a swallowed raise.** Several writers on this path are
      deliberately never-raise instrumentation -- `append_book_quotes` catches
      `Exception`, prints `FAILED` and returns a payload -- so a guard that only
      raised would leave the run green with the file on disk. That is the actual
      2026-09-09 case: `book_quotes/.jsonl` was written through a bare `except`.

  2.  **Firing on a path that merely LOOKS like the mirror.** A guard that
      matched on the string "data" would condemn every `tmp_path` with `data`
      in it, and a prefix test without a separator would condemn a sibling
      called `data_backup`. Either one gets the guard disabled within a week,
      which is worse than not having it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_a_write_into_the_mirror_is_refused_and_recorded(data_mirror_write_guard):
    """The raise carries the writer; the record survives a swallowed raise."""
    target = REPO_ROOT / "data" / "_write_guard_selfcheck" / "probe.jsonl"

    with pytest.raises(RuntimeError, match="TRACKED data/ MIRROR"):
        target.parent.mkdir(parents=True, exist_ok=True)

    recorded = data_mirror_write_guard.consume()
    assert len(recorded) == 1, recorded
    # The recorded entry is what the teardown assertion prints, so it has to
    # name the operation AND carry the stack -- a bare "something wrote" is not
    # actionable.
    assert "Path.mkdir" in recorded[0]
    assert "test_a_write_into_the_mirror_is_refused_and_recorded" in recorded[0]
    # REFUSED, not merely reported: the guard checks before it delegates, so
    # nothing reached the tree.
    assert not target.parent.exists()


def test_an_open_for_writing_is_refused_and_a_read_is_not(data_mirror_write_guard, tmp_path):
    """Reads must keep working -- 92 tests read this tree on purpose.

    The whole design rests on splitting the operation rather than the path, so
    this is the assertion that says the split is real.
    """
    existing = REPO_ROOT / "data" / "mlb_source"
    if not existing.is_dir():
        pytest.skip("this worktree has no data/ mirror to read (see session_worktree.py)")

    # A read of the mirror: allowed, and must record nothing.
    list(existing.iterdir())
    assert data_mirror_write_guard.consume() == []

    with pytest.raises(RuntimeError, match="TRACKED data/ MIRROR"):
        (existing / "_write_guard_selfcheck.jsonl").open("a", encoding="utf-8")
    assert len(data_mirror_write_guard.consume()) == 1
    assert not (existing / "_write_guard_selfcheck.jsonl").exists()


@pytest.mark.writes_tracked_data
def test_the_marker_is_a_real_escape_hatch():
    """A test that genuinely owns a mirror path must be able to say so.

    Without a working opt-out the first legitimate writer turns the guard off
    for everybody, so this is load-bearing rather than a courtesy.
    """
    target = REPO_ROOT / "data" / "_write_guard_selfcheck_marked.jsonl"
    try:
        target.write_text("{}\n", encoding="utf-8")
        assert target.is_file()
    finally:
        # The unlink is intercepted too, and is allowed here for the same
        # reason the write was.
        if target.exists():
            target.unlink()


@pytest.mark.parametrize(
    "relative, inside",
    [
        ("data", True),
        ("data/mlb_source/tracking/book_quotes/2026-09-09.jsonl", True),
        # The two false positives that would get this guard deleted.
        ("data_backup/x.jsonl", False),
        ("datasets/x.jsonl", False),
        # A sibling tree that is not the mirror at all.
        ("reports/intelligence/kalshi_markets.json", False),
    ],
)
def test_only_the_mirror_itself_classifies_as_the_mirror(data_mirror_write_guard, relative, inside):
    assert data_mirror_write_guard.classifies_as_mirror(REPO_ROOT / relative) is inside


def test_a_scratch_dir_named_data_is_not_the_mirror(data_mirror_write_guard, tmp_path):
    """`tmp_path / "data"` is what a correctly isolated test writes to.

    `SYNDICATE_DATA_ROOT` is pointed at exactly this shape by the fixtures that
    already redirect it, so a guard that flagged it would fire on every one of
    them.
    """
    scratch = tmp_path / "data"
    scratch.mkdir()
    (scratch / "probe.jsonl").write_text("{}\n", encoding="utf-8")
    assert data_mirror_write_guard.consume() == []
    assert data_mirror_write_guard.classifies_as_mirror(scratch) is False


def test_the_guarded_roots_are_this_repos_tracked_mirrors(data_mirror_write_guard):
    """A guard pointed at the wrong tree reads healthy forever.

    Both roots are asserted, because the second one (`vendor/<repo>/data/`) was
    added after the first sweep showed a tracked vendor file being rewritten,
    and a root that silently stopped resolving would look exactly like a clean
    suite.
    """
    roots = data_mirror_write_guard.mirror_roots()
    assert os.path.normcase(str(REPO_ROOT / "data")) in roots
    vendor_wnba = REPO_ROOT / "vendor" / "wnba_betting_repo" / "data"
    if vendor_wnba.is_dir():
        assert os.path.normcase(str(vendor_wnba)) in roots
    assert data_mirror_write_guard.classifies_as_mirror(
        REPO_ROOT / "vendor" / "wnba_betting_repo" / "data" / "processed" / "schedule_2026.csv"
    ) is True


def test_a_mkdir_that_creates_nothing_is_not_reported(data_mirror_write_guard):
    """`mkdir(parents=True, exist_ok=True)` on an existing directory is a no-op.

    Eleven `test_archives.py` tests do exactly this against a directory holding
    208 tracked files. Reporting it would have made the guard's first full-suite
    run look like eleven defects, and a guard with that hit rate gets removed.
    """
    existing = REPO_ROOT / "data" / "mlb_source" / "source_artifacts" / "data" / "live_lens"
    if not existing.is_dir():
        pytest.skip("this worktree has no data/ mirror (see session_worktree.py)")

    existing.mkdir(parents=True, exist_ok=True)
    assert data_mirror_write_guard.consume() == []
    # ...and the same call against a path that does NOT exist is still reported,
    # which is the half that found the `book_quotes` writer. `tracking/` rather
    # than `source_artifacts/` because the latter is ignored wholesale by
    # `.gitignore` -- see the next test.
    probe_dir = REPO_ROOT / "data" / "mlb_source" / "tracking" / "_write_guard_selfcheck_dir"
    with pytest.raises(RuntimeError, match="TRACKED data/ MIRROR"):
        probe_dir.mkdir(parents=True, exist_ok=True)
    assert len(data_mirror_write_guard.consume()) == 1
    assert not probe_dir.exists()


def test_a_gitignored_subtree_is_not_the_tracked_mirror(data_mirror_write_guard):
    """`.gitignore` is the repo's own statement that a subtree is local cache.

    `data/nfl_source/tracking/` is listed there, and nine
    `test_football_sim_engine.py` tests fill the nflverse release cache under it
    through the real ingestion path. Nothing under an ignore rule can reach a
    commit or be read back later as if the mirror had produced it, which is the
    entire harm this guard is about.
    """
    ignored = REPO_ROOT / "data" / "nfl_source" / "tracking" / "_write_guard_selfcheck"
    assert data_mirror_write_guard.classifies_as_mirror(ignored) is True
    assert data_mirror_write_guard.git_ignores(ignored) is True

    probe = ignored / "probe.jsonl"
    try:
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("{}", encoding="utf-8")
        assert data_mirror_write_guard.consume() == []
    finally:
        if probe.exists():
            probe.unlink()
        if probe.parent.is_dir():
            probe.parent.rmdir()


def test_a_tracked_file_is_guarded_even_inside_an_ignored_subtree(data_mirror_write_guard):
    """The exemption is about what git would SURFACE, not about the rules.

    `.gitignore:36` excludes `data/*_source/source_artifacts/` wholesale, and
    that tree nonetheless holds thousands of TRACKED files -- 208 under
    `live_lens` alone. `git check-ignore` answers 1 for anything in the index, so
    overwriting one of those is still reported while a NEW cache file beside it
    is not. Without this test the exemption reads as "source_artifacts is
    exempt", which would blind the guard to the worst case it has.
    """
    tracked = REPO_ROOT / "data" / "mlb_source" / "source_artifacts" / "data" / "live_lens" / "live_lens_2026_05_29.jsonl"
    if not tracked.is_file():
        pytest.skip("this worktree has no data/ mirror (see session_worktree.py)")

    # THE IGNORED SIBLING GOES FIRST, AND NOT FOR TIDINESS. This assertion used
    # to be the LAST act of this test, and it POISONED whatever ran next in the
    # same xdist worker: `_git_ignores` kept a per-directory cache, so one query
    # for an ignored NAME here exempted every tracked file in this directory --
    # 208 of them -- for the rest of the process. The cache is gone (see
    # `_git_ignores`), and this test no longer ends on a priming query either, so
    # the self-check does not depend on an implementation detail of the thing it
    # is supposed to be checking independently.
    beside = tracked.with_name("_write_guard_selfcheck_new.jsonl")
    assert data_mirror_write_guard.git_ignores(beside) is True

    # ...and the TRACKED verdict is asserted AFTER it, which is the ordering that
    # fails against the old cache.
    assert data_mirror_write_guard.git_ignores(tracked) is False
    before = tracked.read_bytes()
    with pytest.raises(RuntimeError, match="TRACKED data/ MIRROR"):
        tracked.open("a", encoding="utf-8")
    assert len(data_mirror_write_guard.consume()) == 1
    assert tracked.read_bytes() == before


def test_an_ignored_sibling_does_not_exempt_a_tracked_file_beside_it(data_mirror_write_guard):
    """The regression test for the per-directory ignore cache.

    THE ORDER IS THE TEST. `git check-ignore` answers NOT ignored for anything in
    the index whatever rules match it, so within ONE directory a tracked file and
    a new name give DIFFERENT answers. A cache keyed on the directory cannot hold
    both, and the old one let the first query win for the rest of the process.

    Measured before the fix, on this exact directory (208 tracked files under a
    trailing-slash rule): tracked -> False, ignored name -> True (primes), tracked
    -> **True, WRONG**. Both orders are asserted below, because the exact-path
    cache hides the defect if the tracked file is queried first -- which is how a
    weaker version of this test would have passed against the bug.
    """
    live_lens = REPO_ROOT / "data" / "mlb_source" / "source_artifacts" / "data" / "live_lens"
    tracked_a = live_lens / "live_lens_2026_05_29.jsonl"
    tracked_b = live_lens / "live_lens_2026_06_02.jsonl"
    if not (tracked_a.is_file() and tracked_b.is_file()):
        pytest.skip("this worktree has no data/ mirror (see session_worktree.py)")

    ignores = data_mirror_write_guard.git_ignores
    ignored_name = live_lens / "_write_guard_selfcheck_never_existed.jsonl"

    # IGNORED FIRST, then a DIFFERENT tracked file in the same directory: the
    # exact-path cache cannot mask this one.
    assert ignores(ignored_name) is True
    assert ignores(tracked_b) is False, (
        "a query for an ignored name exempted a TRACKED file in the same "
        "directory -- the per-directory ignore cache is back"
    )
    # And the other order, for completeness.
    assert ignores(tracked_a) is False
    assert ignores(ignored_name) is True


def test_the_vendored_schedule_fetch_is_blocked_at_the_floor(data_mirror_write_guard):
    """The subprocess block must be in force at IMPORT, not merely per test.

    THIS ASSERTS ON THE FLOOR, and that is not a stylistic choice. Session
    `data-mirror-write-guard-sweep` measured 143 mtime changes on
    `vendor/wnba_betting_repo/data/processed/schedule_2026.{csv,json}` in one
    parallel run, 25 of them with an EMPTY `PYTEST_CURRENT_TEST` -- writes that
    happened BETWEEN tests, from a thread that outlived the test which started
    it. A patch applied by an autouse fixture is in force only DURING a test, so
    those 25 were unprotected by construction.

    They also supplied the reason a naive version of this test is worthless:
    their first regression test for the sibling `reports/` fix PASSED WITH THE
    FIX REMOVED, because inside a test the per-test layer is active either way,
    so the probe could not tell a working wall from a missing one. Hence the
    order below -- the installed-at-import check comes FIRST and the call comes
    second, so a regression fails here instead of spawning the live network
    fetch this block exists to prevent.
    """
    assert data_mirror_write_guard.vendored_schedule_block_installed(), (
        "the vendored fetch-schedule block is not installed at conftest import; "
        "if it has been turned back into an autouse fixture, the between-test "
        "window is open again"
    )

    from syndicate.features.shared import schedule_adapter

    fetch = schedule_adapter._fetch_basketball_schedule_via_cli
    # Patched, not the real function -- checked before calling, because calling
    # the real one shells out to `python -m wnba_betting.cli fetch-schedule` and
    # rewrites a tracked file.
    assert getattr(fetch, "return_value", None) is False, fetch
    assert fetch("wnba") is False


# ---------------------------------------------------------------------------
# The two seams the first version of this guard did not cover.
# ---------------------------------------------------------------------------


def test_os_open_for_writing_is_refused_and_recorded(data_mirror_write_guard):
    """`os.open` was the documented hole, and it was a REAL one.

    MEASURED 2026-09-09, before this was closed: a probe test that appended to
    a tracked mirror file with `os.open(..., O_WRONLY | O_APPEND)` PASSED and
    left the bytes on disk, while the identical append through `Path.open("a")`
    in the same style of test was refused with nothing written. `shutil`'s
    EINVAL fallback in `scripts/refresh_*_oddsapi.py` copies through exactly
    this call, so it was one fallback away from being a production path too.
    """
    target = REPO_ROOT / "data" / "_write_guard_selfcheck_os_open.jsonl"

    with pytest.raises(RuntimeError, match="TRACKED data/ MIRROR"):
        os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_APPEND)

    recorded = data_mirror_write_guard.consume()
    assert len(recorded) == 1, recorded
    assert "os.open" in recorded[0]
    assert not target.exists()


def test_os_open_for_reading_the_mirror_is_not_reported(data_mirror_write_guard):
    """The split is OPERATION, not path -- reads of the mirror must stay free.

    This is the assertion that keeps the `os.open` wrapper from condemning the
    92 tests that read this tree on purpose: `O_RDONLY` is 0, so a read never
    even reaches the path check.
    """
    existing = next((REPO_ROOT / "data" / "mlb_source").rglob("*.json"), None)
    if existing is None:
        pytest.skip("this worktree has no data/ mirror to read (see session_worktree.py)")

    # A FILE, not the directory: Windows refuses `os.open` on a directory with
    # EACCES, which would fail this test for a reason that has nothing to do
    # with the guard.
    fd = os.open(str(existing), os.O_RDONLY)
    os.close(fd)
    assert data_mirror_write_guard.consume() == []


@pytest.mark.parametrize(
    "relative, inside",
    [
        ("vendor/wnba_betting_repo/data/processed/schedule_2026.csv", True),
        ("vendor/nba_betting_repo/data/processed/x.json", True),
        ("vendor/mlb_bettingv2/data/x.json", True),
        # Vendor SOURCE is not an artifact mirror; guarding it would fire on
        # every test that writes a scratch file beside vendored code.
        ("vendor/wnba_betting_repo/app.py", False),
        ("vendor/wnba_betting_repo/src/wnba_betting/cli.py", False),
    ],
)
def test_vendor_data_trees_are_guarded_and_vendor_source_is_not(data_mirror_write_guard, relative, inside):
    """`vendor/*/data/` is the same defect one directory over.

    MEASURED: a full run rewrote all 114 rows of the TRACKED
    `vendor/wnba_betting_repo/data/processed/schedule_2026.csv` and its `.json`
    sibling, from a live ESPN fetch, on every run.
    """
    assert data_mirror_write_guard.classifies_as_mirror(REPO_ROOT / relative) is inside


def test_every_tracked_vendor_data_tree_is_covered(data_mirror_write_guard):
    """A guard pointed at a subset of the trees reads healthy forever.

    Derives the expectation from what is actually TRACKED rather than from a
    hand-written list, so a vendor tree added later fails this test instead of
    being silently unguarded.
    """
    import subprocess

    completed = subprocess.run(
        ["git", "ls-files", "--", "vendor/*/data"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        pytest.skip("git unavailable")
    tracked_trees = {
        "/".join(line.split("/")[:3]) for line in (completed.stdout or "").splitlines() if line.strip()
    }
    if not tracked_trees:
        pytest.skip("this worktree has no vendor data checked out")

    guarded = {os.path.normcase(root) for root in data_mirror_write_guard.mirror_roots()}
    for tree in sorted(tracked_trees):
        assert os.path.normcase(str(REPO_ROOT / tree)) in guarded, tree
