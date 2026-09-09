"""Chunked runs in `scripts/pytest_baseline.py`. `#647`.

WHY CHUNKING EXISTS. The `ci-suite` cron's pytest step is OOM-killed at 2Gi in
every worker configuration tried -- `-n auto`, `-n 2` (1056s in) and `-n 0`
(537s in) -- and REDUCING worker count made it fail SOONER, because `-n 0` is
the floor for PROCESS COUNT and not for PEAK MEMORY. Measured locally on the
same command, sampling the process tree: the suite peaks at **2443 MB** against
a 2048 MB limit, on a box with no cgroup accounting and no page cache in the
count. One process must hold what the whole suite accumulates; N sequential
processes each hold roughly 1/N.

THE DANGEROUS PART, AND WHY THIS FILE IS MOSTLY ABOUT ONE RISK. The union of N
partial runs looks exactly like one complete run. This gate fails when the
failure set SHRINKS as well as when it grows -- deliberately, so a fixed test
must be recorded rather than silently tolerated. Put those together and a chunk
that dies (OOM, import crash, bad args) removes its tests from the union, and
they are then reported as **newly FIXED**. A crash would print as good news, and
the remedy printed alongside would tell someone to update the baseline, burning
the evidence.

So `main()` refuses on any chunk that produces no junit report or collects zero
testcases, and the tests below assert that refusal in both shapes. Everything
else here is arithmetic.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def baseline_mod():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location(
        "pytest_baseline", REPO_ROOT / "scripts" / "pytest_baseline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# _split_test_files
# --------------------------------------------------------------------------

def test_a_directory_expands_to_its_test_files(baseline_mod):
    groups, flags = baseline_mod._split_test_files(["tests/"], 4)

    assert len(groups) == 4
    every = [f for g in groups for f in g]
    assert all(f.endswith(".py") for f in every)
    assert any(f.endswith("test_pytest_baseline_chunks.py") for f in every)
    assert flags == []


def test_a_flag_VALUE_is_not_treated_as_a_path(baseline_mod):
    """`-n 0` arrives as two tokens and only the first starts with `-`.

    Classifying by that alone made the `0` a path, which resolved to nothing
    and refused the whole split -- the first real run of this feature fell back
    to unchunked for exactly this reason.
    """
    groups, flags = baseline_mod._split_test_files(
        ["tests/", "-n", "0", "--dist=loadscope"], 3)

    assert groups, "the split was refused"
    assert flags == ["-n", "0", "--dist=loadscope"]
    assert "0" not in [f for g in groups for f in g]


def test_flag_and_value_stay_adjacent(baseline_mod):
    """Order matters: `-n` must still be followed by its value."""
    _, flags = baseline_mod._split_test_files(["tests/", "-n", "0", "-p", "no:randomly"], 2)

    assert flags.index("-n") + 1 == flags.index("0")
    assert flags.index("-p") + 1 == flags.index("no:randomly")


def test_round_robin_not_contiguous_blocks(baseline_mod):
    """The peak is set by the WORST chunk, not the average.

    Contiguous slices put neighbouring -- often related, often similarly heavy
    -- files together. Round-robin spreads them.
    """
    groups, _ = baseline_mod._split_test_files(["tests/"], 3)
    every = sorted(f for g in groups for f in g)

    # Reconstruct the round-robin: file i belongs to group i % 3.
    for index, path in enumerate(every):
        assert path in groups[index % 3], path


def test_every_file_appears_exactly_once(baseline_mod):
    """A split that drops or duplicates a file silently changes the result."""
    groups, _ = baseline_mod._split_test_files(["tests/"], 7)
    every = [f for g in groups for f in g]

    assert len(every) == len(set(every))
    on_disk = {str(p.relative_to(REPO_ROOT).as_posix())
               for p in (REPO_ROOT / "tests").rglob("test_*.py")}
    assert set(every) == on_disk


def test_more_chunks_than_files_yields_no_empty_groups(baseline_mod):
    groups, _ = baseline_mod._split_test_files(
        ["tests/test_pytest_baseline_chunks.py"], 9)

    assert groups == [["tests/test_pytest_baseline_chunks.py"]]


@pytest.mark.parametrize("args", [
    ["tests/test_foo.py::TestClass::test_thing"],
    ["tests/test_*.py"],
    ["-k", "something"],
])
def test_an_unenumerable_selection_refuses_to_split(baseline_mod, args):
    """Refuse rather than invent a split.

    The caller runs unchunked on `[]`, which is correct and slower -- the wrong
    answer here is a split that silently omits tests.
    """
    groups, _ = baseline_mod._split_test_files(args, 4)

    assert groups == []


# --------------------------------------------------------------------------
# The union, and the refusals that protect it
# --------------------------------------------------------------------------

def _junit(path: Path, cases: list[tuple[str, str, bool]]) -> None:
    body = "".join(
        f'<testcase classname="{c}" name="{n}">'
        + ("<failure>boom</failure>" if failed else "")
        + "</testcase>"
        for c, n, failed in cases)
    path.write_text(f'<?xml version="1.0"?><testsuite>{body}</testsuite>', encoding="utf-8")


def _baseline_file(tmp_path: Path, failing: list[str]) -> Path:
    p = tmp_path / "baseline.json"
    p.write_text(json.dumps({"schema": "pytest_baseline_v1", "failing": failing}),
                 encoding="utf-8")
    return p


def test_failures_from_every_chunk_reach_the_union(baseline_mod, tmp_path, monkeypatch):
    """A failure in the LAST chunk must count as much as one in the first."""
    calls = {"n": 0}

    def fake_run(args, junit_path):
        calls["n"] += 1
        if calls["n"] == 1:
            _junit(junit_path, [("tests.a", "test_one", False)])
        else:
            _junit(junit_path, [("tests.b", "test_two", True)])
        return 0

    monkeypatch.setattr(baseline_mod, "_run_pytest", fake_run)
    monkeypatch.setattr(baseline_mod, "_split_test_files",
                        lambda a, c: ([["tests/a.py"], ["tests/b.py"]], []))
    base = _baseline_file(tmp_path, ["tests.b::test_two"])

    rc = baseline_mod.main(["--chunks", "2", "--baseline", str(base), "--", "tests/"])

    assert rc == baseline_mod.EXIT_OK, "the known failure in chunk 2 was not seen"
    assert calls["n"] == 2


def test_a_dead_chunk_is_RUN_BROKEN_not_a_pile_of_fixed_tests(baseline_mod, tmp_path, monkeypatch):
    """THE failure mode this feature could have introduced.

    Chunk 2 writes no report, exactly as an OOM-killed process would. Its
    tests vanish from the union, and because this gate also fails on a SHRINKING
    failure set, they would otherwise be announced as newly fixed -- a crash
    printing as good news, with a remedy that says to update the baseline.
    """
    def fake_run(args, junit_path):
        if "a.py" in args[0]:
            _junit(junit_path, [("tests.a", "test_one", False)])
        # chunk 2: writes nothing at all

    monkeypatch.setattr(baseline_mod, "_run_pytest", fake_run)
    monkeypatch.setattr(baseline_mod, "_split_test_files",
                        lambda a, c: ([["tests/a.py"], ["tests/b.py"]], []))
    base = _baseline_file(tmp_path, ["tests.b::test_two"])

    rc = baseline_mod.main(["--chunks", "2", "--baseline", str(base), "--", "tests/"])

    assert rc == baseline_mod.EXIT_RUN_BROKEN


def test_a_chunk_collecting_nothing_is_also_RUN_BROKEN(baseline_mod, tmp_path, monkeypatch):
    """An empty report is a report, and it is not evidence that tests passed."""
    def fake_run(args, junit_path):
        if "a.py" in args[0]:
            _junit(junit_path, [("tests.a", "test_one", False)])
        else:
            _junit(junit_path, [])

    monkeypatch.setattr(baseline_mod, "_run_pytest", fake_run)
    monkeypatch.setattr(baseline_mod, "_split_test_files",
                        lambda a, c: ([["tests/a.py"], ["tests/b.py"]], []))
    base = _baseline_file(tmp_path, [])

    rc = baseline_mod.main(["--chunks", "2", "--baseline", str(base), "--", "tests/"])

    assert rc == baseline_mod.EXIT_RUN_BROKEN


def test_a_new_failure_in_any_chunk_still_fails_the_gate(baseline_mod, tmp_path, monkeypatch):
    def fake_run(args, junit_path):
        if "a.py" in args[0]:
            _junit(junit_path, [("tests.a", "test_one", False)])
        else:
            _junit(junit_path, [("tests.b", "test_two", True)])

    monkeypatch.setattr(baseline_mod, "_run_pytest", fake_run)
    monkeypatch.setattr(baseline_mod, "_split_test_files",
                        lambda a, c: ([["tests/a.py"], ["tests/b.py"]], []))
    base = _baseline_file(tmp_path, [])          # nothing known to fail

    rc = baseline_mod.main(["--chunks", "2", "--baseline", str(base), "--", "tests/"])

    assert rc == baseline_mod.EXIT_NEW_FAILURES


def test_chunks_of_one_is_the_old_path_untouched(baseline_mod, tmp_path, monkeypatch):
    """`--chunks 1` must not enter the chunked branch at all.

    `ci.yml` does not pass the flag, so its behaviour has to be bit-identical.
    """
    seen = {"split": 0}
    monkeypatch.setattr(baseline_mod, "_split_test_files",
                        lambda a, c: seen.__setitem__("split", seen["split"] + 1) or ([], []))
    monkeypatch.setattr(baseline_mod, "_run_pytest",
                        lambda args, junit_path: _junit(junit_path, [("tests.a", "test_one", False)]))
    base = _baseline_file(tmp_path, [])

    rc = baseline_mod.main(["--baseline", str(base), "--", "tests/"])

    assert rc == baseline_mod.EXIT_OK
    assert seen["split"] == 0, "the splitter ran for an unchunked invocation"
