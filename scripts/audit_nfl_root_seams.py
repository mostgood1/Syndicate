"""pytest plugin: catch a test whose NFL path resolution escapes its own fixture.

    PYTHONPATH=scripts py -3 -m pytest tests/test_nfl_*.py -p audit_nfl_root_seams

WHAT IT IS FOR, and why a grep is not enough.

`#672` moved `data_path` off `default_nfl_source_root()` onto a PER-FILE search
across `_source_roots()`; `7931b18a` did the same for the two week ENUMERATORS.
Any test still patching the old helper therefore no longer reaches the code it
is testing -- and it does not simply fail. It silently becomes an assertion
about the repo's own `data/nfl_source`, so it can stay GREEN while proving
nothing about the fixture beside it.

A grep for `default_nfl_source_root` cannot tell those apart. Measured
2026-09-24: 26 test files mention it, 16 already patch a live seam, 5 only
mention it, 5 patch the old seam alone -- and of those 5, **exactly ONE test**
actually resolved into the repo's data directory. The answer was 1 affected
test, not 26 files, and only running the code could say so.

HOW IT DECIDES. It wraps the real resolvers and records every path they RETURN.
A return inside the repo's own `data/nfl_source` while a test is running is the
defect, by definition: that test is reading production data. Reporting is per
TEST ID, so a file with one bad case and nine clean ones is not condemned whole.

ITS OWN FIRST FINDING WAS THE AUTHOR'S REGRESSION. `7931b18a` shipped with
`test_nfl_hide_backfill_weeks.py::test_cards_picks_and_lens_weeks_hide_the_
backfill` red -- 19 escaping resolutions -- because the hand-picked sweep that
gated that deploy did not include the file. See `learnings.md` 2026-09-24.
"""
from __future__ import annotations

import collections
from pathlib import Path

# The repo's own data directory, resolved from THIS file so the plugin works in
# a session worktree as well as the primary tree.
REPO_DATA = Path(__file__).resolve().parents[1] / "data" / "nfl_source"

# The resolvers `#672`/`7931b18a` moved off `default_nfl_source_root`. A test
# that patches only the old helper cannot steer any of these.
WRAPPED = ("data_path", "_resolve_nfl_tracking_path", "nfl_props_path", "real_schedule_path")

_hits: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
_current = {"id": "<collection/setup>"}


def _inside_repo_data(value) -> bool:
    """A path inside the repo's data dir THAT ACTUALLY EXISTS.

    THE `exists()` IS NOT AN OPTIMISATION, IT IS THE CORRECTNESS OF THIS TOOL.
    `data_path` deliberately returns a NAMED FALLBACK under a real root when no
    root has the requested file, so that a caller's error message can name a
    concrete location instead of saying "not found". That fallback points into
    `data/nfl_source` and reads NOTHING.

    Without this check the audit reported 2 extra "affected" tests on its first
    run -- `NflTargetWeekTests::test_missing_file_returns_none` (which asks for
    season 2099 precisely BECAUSE no such file exists) and a chip-week case
    whose `default_week` probes a schedule its fixture never wrote. Both were
    green, both were correct, and both were flagged. An instrument that cannot
    tell "resolved a path" from "read a file" manufactures the defect it exists
    to find.
    """
    try:
        resolved = Path(value).resolve()
        resolved.relative_to(REPO_DATA.resolve())
        return resolved.exists()
    except (ValueError, OSError, TypeError):
        return False


def pytest_configure(config):
    from syndicate.features.nfl import sources

    for name in WRAPPED:
        original = getattr(sources, name, None)
        if original is None or getattr(original, "_seam_audit", False):
            continue

        def make(orig, label):
            def wrapper(*args, **kwargs):
                result = orig(*args, **kwargs)
                if _inside_repo_data(result):
                    _hits[_current["id"]][label] += 1
                return result

            wrapper._seam_audit = True
            return wrapper

        setattr(sources, name, make(original, name))


def pytest_runtest_logstart(nodeid, location):
    _current["id"] = nodeid


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    write = terminalreporter.write_line
    write("")
    write("=== NFL ROOT-SEAM AUDIT: resolutions landing in the repo's data/nfl_source ===")
    if not _hits:
        write("   none -- every resolved NFL path stayed inside its fixture")
        return
    for nodeid, counter in sorted(_hits.items()):
        write("   %-76s %s" % (nodeid[:76], dict(counter)))
    write("   AFFECTED TESTS: %d" % len(_hits))
    write("   (a GREEN test listed here is the dangerous case: it is asserting")
    write("    against production data, not against the fixture beside it)")
