"""No-new-failures gate for the pytest suite.

**WHY A BASELINE AND NOT A GREEN GATE.** `#517`, measured 2026-08-22: the full
suite is `76 failed, 9245 passed` on clean `origin/main`, across 26 files, and
every sampled failure reproduces standalone. CI runs
`python -m unittest tests.test_archives` (383 tests) and nothing else, so those
76 can sit there indefinitely while CI shows green -- and the six stale test
targets of `#516` did exactly that.

Turning the suite on as a plain gate lands red on the first run.
`.github/workflows/ci.yml` already argues why that is worse than nothing: *"a
check that is red on arrival is a check people learn to ignore, and then it is
worth less than nothing -- it looks like coverage"*, and *"a
permanently-tolerated failure is how a gate becomes decoration."* A
`continue-on-error` step is that decoration in one line.

This gates the DERIVATIVE instead: the known-failing set is recorded, and CI
fails when the set GROWS. Regressions are caught from today; the existing debt
stays visible as a number in a file rather than as a red check nobody reads.

**THE BASELINE MUST SHRINK, AND THIS ENFORCES THAT.** A test that starts
passing is ALSO a failure here, with the remedy printed. Without that rule a
baseline only ever grows stale: fixes stop being recorded, the file drifts from
reality, and "no new failures" quietly becomes "no information". A baseline
that cannot shrink is the same decoration in a different shape.

    python scripts/pytest_baseline.py --update     # record the current set
    python scripts/pytest_baseline.py              # gate: fail on any change

**TEST IDENTITY IS `classname::name` FROM THE JUNIT REPORT, NOT A PYTEST NODE
ID.** Node ids have to be reconstructed from the dotted classname, and the
module/class boundary is ambiguous (`tests.test_foo` vs `tests.test_foo.Cls`);
parsing them out of `-q` stdout is worse still, because a parametrised id may
contain spaces and ` - `. The junit pair is exact and needs no parsing.
`--runnable` prints a best-effort pytest selector for humans, which is allowed
to be approximate precisely because nothing machine-readable depends on it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / "tests" / "pytest_baseline.json"

EXIT_OK = 0
EXIT_NEW_FAILURES = 1
EXIT_BASELINE_STALE = 2
EXIT_RUN_BROKEN = 3


def _failed_keys(junit_path: Path) -> tuple[set[str], int]:
    """(failing test keys, total testcases) from a junit XML report.

    A `<testcase>` counts as failing if it carries a `<failure>` or `<error>`
    child. `<error>` covers COLLECTION errors too -- a module that cannot be
    imported at all -- which is the failure mode most worth catching and the one
    a stdout scrape is most likely to miss.
    """
    root = ET.parse(junit_path).getroot()
    keys: set[str] = set()
    total = 0
    for case in root.iter("testcase"):
        total += 1
        if case.find("failure") is None and case.find("error") is None:
            continue
        classname = str(case.get("classname") or "").strip()
        name = str(case.get("name") or "").strip()
        if not name:
            continue
        keys.add(f"{classname}::{name}" if classname else name)
    return keys, total


def _runnable(key: str) -> str:
    """Best-effort pytest selector for a human. Approximate BY DESIGN -- see
    the module docstring; the machine-readable identity is `key` itself."""
    dotted, _, name = key.partition("::")
    parts = dotted.split(".")
    for index, part in enumerate(parts):
        if part.startswith("test_") and index > 0:
            path = "/".join(parts[: index + 1]) + ".py"
            rest = "::".join(parts[index + 1 :])
            return f"{path}::{rest}::{name}" if rest else f"{path}::{name}"
    return key


def _tree_provenance() -> str:
    """The SHA this run describes, and whether the tree was clean.

    **A FAILURE LIST IS NOT A FACT ABOUT `main`. It is a fact about the SHA the
    run STARTED on, and nothing in the output used to name it.** Measured
    2026-09-05: a full run took 37m54s and **3 of its 4 failures were already
    fixed before it finished** -- it had photographed a genuine intermediate
    state (tests landed at 22:20, their producer at 22:52 and 23:09, run started
    22:31). ~22 commits landed on this repo between two consecutive full runs, so
    a result is stale by up to one run length the moment it prints.

    Printed in the run's own header rather than recorded by whoever launched it,
    because the person who has to judge a failure list is usually NOT the person
    who produced it -- and to them the staleness is otherwise invisible.
    `[suggested by lane ncaaf-live-state-worker after being sent a stale list]`

    Fails soft: a run must never die because git is unavailable.
    """
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=30).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                              capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:
        return "provenance UNKNOWN (git unavailable)"
    if not sha:
        return "provenance UNKNOWN (not a git checkout)"
    state = f"{len(dirty.splitlines())} path(s) dirty" if dirty else "clean"
    return f"tree {sha}, {state}"


def _run_pytest(pytest_args: list[str], junit_path: Path) -> int:
    command = [
        sys.executable, "-m", "pytest", *pytest_args,
        "-q", "--tb=no", "-p", "no:cacheprovider",
        f"--junitxml={junit_path}",
    ]
    started = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[pytest_baseline] STARTED {started} -- {_tree_provenance()}", flush=True)
    print("[pytest_baseline] this result describes THAT tree, not whatever "
          "`main` is when it finishes", flush=True)
    print(f"[pytest_baseline] {' '.join(command)}", flush=True)
    # Output is NOT captured: a 27-minute run with no visible progress is
    # indistinguishable from a hung one, and CI will kill it on that suspicion.
    return subprocess.run(command, cwd=REPO_ROOT).returncode


def _chunk_index(path: str, chunks: int) -> int:
    """Which chunk a test file belongs to. A PURE FUNCTION OF THE PATH.

    WHY NOT ROUND-ROBIN, WHICH THIS REPLACED. `groups[index % n]` over a sorted
    list means inserting ONE file shifts every file after it into a different
    process -- and tests that assert on what else is resident then change
    verdict with nobody touching them. Measured across two `ci-suite` runs ~90
    minutes apart at near-identical code: `test_heap_roots` x4 and
    `test_home_mlb_live_lens_states` VANISHED, `test_retainer_census` APPEARED,
    and each was then shown to pass in isolation (`#649`). Chunk 1 collected
    2243 in one run and 1788 in the next. **A gate whose red list moves without
    the code moving cannot be read by a human on a schedule.**

    NOT `hash()`. Python randomises `hash()` for `str` per process unless
    `PYTHONHASHSEED` is pinned, so the built-in would make the split differ
    between two runs of the SAME suite on the SAME commit -- reintroducing the
    exact instability this exists to remove, in a shape that would be much
    harder to see. `blake2b` is stable across processes, machines and versions.

    Balance is no longer exact. Round-robin guaranteed equal file COUNTS;
    hashing gives approximately equal ones, and the peak is set by the worst
    chunk. Measured on the real 1,066-file tree at `--chunks 8` -- see the lane
    note -- the spread stayed within a few files of even, which is well inside
    the variation that file COST already introduces.
    """
    digest = hashlib.blake2b(path.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % max(1, chunks)


def _split_test_files(pytest_args: list[str], chunks: int) -> tuple[list[list[str]], list[str]]:
    """(groups of test files, flags) so each group can run in a FRESH process.

    WHY CHUNKING EXISTS. `#647`: the `ci-suite` cron's pytest step is OOM-killed
    at 2Gi in every configuration tried -- `-n auto`, `-n 2` (1056s in) and
    `-n 0` (537s in) -- and REDUCING worker count made it fail SOONER, so worker
    count was never the lever. Measured locally on the same command, sampling
    the process tree: memory climbs to ~675 MB, sits flat for several minutes,
    then climbs again to a **2443 MB peak** -- past the 2048 MB limit on a box
    with no cgroup accounting and no page cache in the count. One process must
    hold what the whole suite accumulates; N processes each hold ~1/N of it.

    FILES ARE GLOBBED, NOT COLLECTED. `pytest --collect-only` imports every test
    module to enumerate them, which costs the very memory this is trying to
    bound -- paying the peak once just to plan how to avoid paying it.

    ASSIGNMENT IS A HASH OF THE PATH, NOT A POSITION. See `_chunk_index`. It
    still spreads related files the way round-robin did -- which matters because
    the peak is set by the WORST group, not the average -- and it additionally
    makes a file's chunk independent of how many other files exist.

    Returns `([], flags)` when no files can be identified -- a `-k` expression
    or an explicit nodeid -- and the caller then runs unchunked rather than
    inventing a split it cannot verify.
    """
    # A BARE TOKEN IS NOT NECESSARILY A PATH. `-n 0` arrives as two arguments and
    # only the first starts with `-`, so classifying by that alone made the `0` a
    # path, which resolved to nothing and refused the whole split. Order is
    # preserved as tokens are sorted into the two lists, so a flag and its value
    # stay adjacent.
    flags: list[str] = []
    files: list[str] = []
    for raw in pytest_args:
        if raw.startswith("-"):
            flags.append(raw)
            continue
        if "::" in raw or "*" in raw or "?" in raw:
            # A nodeid or a glob: the file set is not something we can enumerate
            # reliably, so refuse rather than invent a split.
            return [], list(pytest_args)
        candidate = REPO_ROOT / raw
        if candidate.is_dir():
            files.extend(sorted(str(f.relative_to(REPO_ROOT).as_posix())
                                for f in candidate.rglob("test_*.py")))
        elif candidate.is_file():
            files.append(raw)
        else:
            # Resolves to nothing on disk, so it is a flag's VALUE, not a path.
            flags.append(raw)
    if not files:
        return [], list(pytest_args)
    n = max(1, chunks)
    groups: list[list[str]] = [[] for _ in range(n)]
    for path in files:
        groups[_chunk_index(path, n)].append(path)
    return [g for g in groups if g], flags


def _load_baseline(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # UNREADABLE IS NOT ABSENT. An absent baseline means "never recorded";
        # a corrupt one means the recorded set is unknown, and treating that as
        # an empty set would report all 76 known failures as NEW.
        raise SystemExit(f"[pytest_baseline] baseline at {path} is unreadable: {exc}")
    return payload if isinstance(payload, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="record the current failures as the baseline")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--junit", default=None, help="reuse an existing junit XML instead of running pytest")
    parser.add_argument("--runnable", action="store_true", help="also print a pytest selector per test")
    parser.add_argument("--chunks", type=int, default=1,
                        help="run the suite in N sequential pytest processes and UNION the "
                             "results. Bounds peak memory, which a 2Gi box needs (`#647`): "
                             "one process holds the whole suite's accumulation, N hold ~1/N "
                             "each. Default 1 = today's behaviour, unchanged.")
    parser.add_argument("pytest_args", nargs="*", default=["tests/"], help="paths/args passed to pytest")
    args = parser.parse_args(argv)

    baseline_path = Path(args.baseline)
    pytest_args = args.pytest_args or ["tests/"]

    groups: list[list[str]] = []
    flags: list[str] = []
    if args.chunks > 1 and not args.junit:
        groups, flags = _split_test_files(pytest_args, args.chunks)
        if not groups:
            print(f"[pytest_baseline] --chunks {args.chunks} requested but the test files could "
                  f"not be identified from {pytest_args!r} -- running UNCHUNKED rather than "
                  f"guessing a split", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        if groups:
            # EVERY CHUNK MUST PRODUCE A REPORT, AND A MISSING ONE IS FATAL.
            # This is the whole risk of chunking: the union of N partial runs
            # looks exactly like a complete run, so a chunk that OOMs or crashes
            # silently removes its tests from `current` -- and because this gate
            # ALSO fails when the failure set SHRINKS, those tests would be
            # reported as newly FIXED. A crash would print as good news.
            print(f"[pytest_baseline] {len(groups)} chunk(s), {sum(len(g) for g in groups)} "
                  f"test file(s), one fresh process each", flush=True)
            current, total = set(), 0
            for index, group in enumerate(groups, start=1):
                chunk_junit = Path(tmp) / f"report_{index}.xml"
                print(f"\n[pytest_baseline] chunk {index}/{len(groups)} -- {len(group)} file(s)", flush=True)
                _run_pytest(group + flags, chunk_junit)
                if not chunk_junit.exists():
                    print(f"[pytest_baseline] chunk {index}/{len(groups)} produced NO JUNIT REPORT -- "
                          f"it did not complete (OOM, import crash, bad args). Refusing to compare a "
                          f"PARTIAL union against a full baseline: the missing tests would read as "
                          f"newly fixed.", flush=True)
                    return EXIT_RUN_BROKEN
                keys, count = _failed_keys(chunk_junit)
                if count == 0:
                    print(f"[pytest_baseline] chunk {index}/{len(groups)} collected 0 testcases -- "
                          f"refusing to treat that as a pass", flush=True)
                    return EXIT_RUN_BROKEN
                current |= keys
                total += count
                print(f"[pytest_baseline] chunk {index}/{len(groups)} collected={count} "
                      f"failing={len(keys)}   running total={total}", flush=True)
        else:
            junit_path = Path(args.junit) if args.junit else Path(tmp) / "report.xml"
            if not args.junit:
                _run_pytest(pytest_args, junit_path)
            if not junit_path.exists():
                # pytest produces a report even when tests fail, so an ABSENT one
                # means the run itself broke (bad args, import crash, OOM). That is
                # never "no failures" and must not be allowed to read as a pass.
                print(f"[pytest_baseline] NO JUNIT REPORT at {junit_path} -- the run did not complete", flush=True)
                return EXIT_RUN_BROKEN
            current, total = _failed_keys(junit_path)

    if total == 0:
        print("[pytest_baseline] 0 testcases collected -- refusing to treat that as a pass", flush=True)
        return EXIT_RUN_BROKEN

    print(f"[pytest_baseline] collected={total} failing={len(current)}", flush=True)

    if args.update:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(
                {
                    "schema": "pytest_baseline_v1",
                    "pytest_args": pytest_args,
                    "total_testcases": total,
                    "failing_count": len(current),
                    "failing": sorted(current),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"[pytest_baseline] wrote {baseline_path} ({len(current)} known failures)", flush=True)
        return EXIT_OK

    baseline = _load_baseline(baseline_path)
    known = set(baseline.get("failing") or [])
    if not baseline:
        print(f"[pytest_baseline] no baseline at {baseline_path}; run --update first", flush=True)
        return EXIT_RUN_BROKEN

    new_failures = sorted(current - known)
    fixed = sorted(known - current)

    if new_failures:
        print(f"\n[pytest_baseline] {len(new_failures)} NEW FAILURE(S) -- not in the baseline:", flush=True)
        for key in new_failures:
            print(f"  {_runnable(key) if args.runnable else key}", flush=True)
        print(
            "\nThese are regressions against the recorded set. Fix them, or -- if a "
            "failure is genuinely pre-existing and was simply never recorded -- say so "
            "explicitly in the commit and re-run with --update.",
            flush=True,
        )
        return EXIT_NEW_FAILURES

    if fixed:
        print(f"\n[pytest_baseline] {len(fixed)} baselined test(s) now PASS (or were removed):", flush=True)
        for key in fixed:
            print(f"  {_runnable(key) if args.runnable else key}", flush=True)
        print(
            "\nThis is good news and it is still a failure, deliberately: a baseline "
            "that never shrinks stops describing reality and becomes decoration. "
            "Record the improvement:\n"
            "    python scripts/pytest_baseline.py --update",
            flush=True,
        )
        return EXIT_BASELINE_STALE

    print(f"[pytest_baseline] OK -- no new failures ({len(known)} known, unchanged)", flush=True)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
