"""No-new-failures gate for the pytest suite.

**WHY A BASELINE AND NOT A GREEN GATE.** `#510`, measured 2026-08-22: the full
suite is `76 failed, 9245 passed` on clean `origin/main`, across 26 files, and
every sampled failure reproduces standalone. CI runs
`python -m unittest tests.test_archives` (383 tests) and nothing else, so those
76 can sit there indefinitely while CI shows green -- and the six stale test
targets of `#509` did exactly that.

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


def _run_pytest(pytest_args: list[str], junit_path: Path) -> int:
    command = [
        sys.executable, "-m", "pytest", *pytest_args,
        "-q", "--tb=no", "-p", "no:cacheprovider",
        f"--junitxml={junit_path}",
    ]
    print(f"[pytest_baseline] {' '.join(command)}", flush=True)
    # Output is NOT captured: a 27-minute run with no visible progress is
    # indistinguishable from a hung one, and CI will kill it on that suspicion.
    return subprocess.run(command, cwd=REPO_ROOT).returncode


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
    parser.add_argument("pytest_args", nargs="*", default=["tests/"], help="paths/args passed to pytest")
    args = parser.parse_args(argv)

    baseline_path = Path(args.baseline)
    pytest_args = args.pytest_args or ["tests/"]

    with tempfile.TemporaryDirectory() as tmp:
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
