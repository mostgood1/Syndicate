"""`lane_claim_audit` must FAIL on the two defect shapes, not merely pass clean.

A green run on today's ledger proves nothing: the ledger is currently clean, so
a tool that always returned "fine" would look identical. These drive the two
shapes that actually occurred on 2026-08-31, both of which
`check_lane_invariants` reported as healthy at the time.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lane_claim_audit", REPO / "scripts" / "lane_claim_audit.py"
)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def _claims(block: str):
    """Claims lane-guard yields for one lane block, via the real parser."""
    return sorted(set(AUDIT.load_guard()._claims(block)))


def _classify(claims):
    tracked = AUDIT.tracked_files()
    not_pathlike = [p for _, p in claims if not p.endswith(AUDIT._PLAUSIBLE_SUFFIXES)]
    missing = [p for _, p in claims
               if p.endswith(AUDIT._PLAUSIBLE_SUFFIXES) and tracked is not None and p not in tracked]
    return not_pathlike, missing


def test_the_hook_loads_without_reading_stdin():
    """The reachability test. `lane-guard.py` is a PreToolUse hook: running it
    blocks on stdin, and a blocked read is indistinguishable from 'no claims'.
    Three sessions hit that on 2026-08-31."""
    guard = AUDIT.load_guard()
    assert callable(guard._claims) and callable(guard._paths_in)


def test_prose_inside_a_Files_block_is_caught_as_a_non_path():
    """The `1/p` / `15.0` / `85.13` shape: an explanation written inside the
    block, where continuation lines are parsed as claims."""
    block = (
        "### demo - OPEN - opened 2026-08-31 - session x\n"
        "- Files: scripts/real_file.py\n"
        "  the ratio is 1/p and the cap is 15.0 against 85.13\n"
        "- Blocked by: none\n"
    )
    not_pathlike, _ = _classify(_claims(block))
    assert not_pathlike, "prose inside a Files block must be reported"
    assert any("/" in t and not t.endswith(".py") for t in not_pathlike)


def test_a_wellformed_but_NONEXISTENT_path_is_caught():
    """The dot-strip shape. `syndicate/findings_x.md` looks perfectly correct
    and names a file that does not exist, so the extension check alone passes
    it. Only existence catches this one."""
    block = (
        "### demo - OPEN - opened 2026-08-31 - session x\n"
        "- Files: `syndicate/this_file_does_not_exist_anywhere.md`\n"
        "- Blocked by: none\n"
    )
    not_pathlike, missing = _classify(_claims(block))
    assert not not_pathlike, "it LOOKS like a path -- that is the whole point"
    assert missing, "a claim naming a nonexistent path must be reported"


def test_a_clean_block_reports_nothing():
    """off != on, so a tool that flagged everything would not pass here."""
    block = (
        "### demo - OPEN - opened 2026-08-31 - session x\n"
        # a long-tracked file on purpose: this fixture must not depend on
        # whether the tool under test has itself been committed yet.
        "- Files: `scripts/trim_lane_blocks.py`\n"
        "- Blocked by: none\n"
    )
    assert _classify(_claims(block)) == ([], [])


def test_a_CLOSED_lane_contributes_no_claims():
    """`_claims` yields for OPEN lanes only. A hand-written extractor that
    ignored this reported 16 phantom losses on 2026-08-31."""
    block = (
        "### demo - CLOSED 2026-08-30 - opened 2026-08-29 - session x\n"
        "- Files: `scripts/whatever.py`\n"
    )
    assert _claims(block) == []


@pytest.mark.parametrize("path", [".syndicate/x.md", ".claude/hooks/y.py"])
def test_dot_directory_claims_survive_extraction(path):
    """Guards the 4a9c685b fix from the audit side as well as the hook side."""
    assert list(AUDIT.load_guard()._paths_in("`%s`" % path)) == [path]
